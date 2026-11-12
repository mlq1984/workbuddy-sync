# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 生成中心 · 派发执行器。设计见 references/architecture.md。

- 通道间池（全局上限）并行，任务间互不阻塞（每任务独立线程）；
- 同通道多张走 n 阶梯：通道自身 n（单限流槽位）→ 自并发扇出（封顶+错峰）→ 降级串行重试；
- 双闸门：executor 预检 switches（友好失败），registry 闸门继续兜底；
- 调用异常一律转 item 错误（服务端原文），绝不抛出——如实报告；
- 状态写入直调 jobs（真相源），进度经 notify 事件喂浏览器。
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import jobs, notify, params, switches, works
from .media import to_data_uri
from .registry import get_channel

logger = logging.getLogger(__name__)

_MAX_CHANNELS = 4    # 通道间并发上限
_MAX_FANOUT = 3      # 同通道扇出硬顶
_STAGGER = 0.8       # 同通道扇出提交间隔（秒），把"齐发"变"流水"

# 中心服务地址（server.main 绑定成功后注入；CLI/脚本直调时为 None → 不弹页）
BASE_URL = None

# 瞬时失败启发式（与 SKILL.md"瞬时失败可重试一次"口径一致；参数/权限类错误不重试）
_TRANSIENT_KEYS = ("429", "503", "500", "502", "timeout", "timed out", "failed",
                   "rate limit", "限流", "负载", "ERR")


def _transient(err: str) -> bool:
    s = str(err)
    return any(k in s for k in _TRANSIENT_KEYS)


def submit(spec: dict) -> dict:
    """生成中心唯一入口：校验 → 过滤 → 建任务 → 异步执行。立即返回，不等待生图。"""
    clean, err = params.validate(spec)
    if err:
        return {"ok": False, "msg": err}
    plan = params.plan(clean)
    if not plan["accepted"]:
        return {"ok": False, "msg": "所选通道均不可用", "dropped": plan["dropped"]}
    job = jobs.create(clean, plan["accepted"], plan["dropped"], plan["units"])
    notify.emit("task.accepted", job_id=job["id"], spec=clean,
                channels=plan["accepted"], dropped=plan["dropped"])
    # 提交即定位作品中心（references/architecture.md §9 单例页面语义）
    if BASE_URL:
        notify.navigate_or_open(BASE_URL, "#jobs-%s" % job["id"])
    threading.Thread(target=_run, args=(job["id"],), daemon=True).start()
    return {"ok": True, "job_id": job["id"],
            "accepted": plan["accepted"], "dropped": plan["dropped"]}


def _run(job_id: str) -> None:
    job = jobs.get(job_id)
    if not job:
        return
    jobs.mark_started(job_id)
    notify.emit("task.started", job_id=job_id)
    chans = sorted({u["channel"] for u in job["items"]})
    pool = ThreadPoolExecutor(max_workers=min(_MAX_CHANNELS, len(chans)))
    futs = {pool.submit(_run_channel, job_id, cid,
                        [u for u in job["items"] if u["channel"] == cid]): cid
            for cid in chans}
    for f in as_completed(futs):
        cid = futs[f]
        try:
            f.result()
        except Exception:
            # 通道级兜底：调用/分派异常已逐 item 落错误，但落盘/通知自身失败
            # （磁盘满、档案写坏等）会漏到这里——此前被静默吞掉，item 永远卡 pending。
            # 只兜底非终态 item（done/failed 不覆盖：异常可能发生在通知阶段，
            # 此时作品已登记、状态已落）；兜底自身再包 try，保证下方 finalize 必达。
            logger.exception("通道线程异常 job=%s channel=%s", job_id, cid)
            job_now = jobs.get(job_id) or {}
            for u in (x for x in job_now.get("items", [])
                      if x.get("channel") == cid and x.get("state") not in ("done", "failed")):
                try:
                    _item_fail(job_id, cid, u["index"], "通道线程异常（详见服务日志）")
                except Exception:
                    logger.exception("兜底落盘失败 job=%s item=%s", job_id, u.get("index"))
    pool.shutdown(wait=True)
    job = jobs.get(job_id) or {}
    s = job.get("summary", {"done": 0, "failed": 0, "total": 0})
    state = "done" if s["failed"] == 0 and s["done"] > 0 else \
        ("partial" if s["done"] else "failed")
    jobs.finalize(job_id, state)
    notify.emit("task.done" if state != "failed" else "task.failed",
                job_id=job_id, state=state, summary=s)
    notify.emit("works.changed")   # 服务端主动告知新作品落库（前端不依赖 task 事件推断）


def _run_channel(job_id: str, cid: str, units: list) -> None:
    # 预检闸门（体验层）：停用/缺失直接产出友好 item 错误，不进入调用
    if not switches.is_enabled(cid):
        for u in units:
            _item_fail(job_id, cid, u["index"], "通道已停用（管理台开关）")
        return
    ch = get_channel(cid)
    if not ch:
        for u in units:
            _item_fail(job_id, cid, u["index"], "通道不存在")
        return

    clean = (jobs.get(job_id) or {}).get("spec", {})
    cap = params.caps(cid, clean.get("model"))
    kw = params.translate(cid, clean)
    action = clean.get("action", "generate")
    n = len(units)
    fn = ch["module"].upscale if action == "upscale" else ch["module"].generate
    reg_prompt = clean.get("prompt") if action == "generate" else \
        (clean.get("upscale_prompt") or "增强放大")
    eff = params.effective(cid, clean)      # 该通道实际生效参数（随作品登记）

    if action == "generate" and n > 1 and cap["n"]:
        # 阶梯1：通道自身 n —— 单请求单限流槽位，原子成功/失败
        try:
            _distribute(job_id, cid, units, fn(**kw), reg_prompt, eff)
        except Exception as e:
            for u in units:
                _item_fail(job_id, cid, u["index"], str(e))
        return

    if action == "generate" and n > 1:
        # 阶梯2：自并发扇出（封顶 CAPS.concurrency 且 ≤3，提交错峰）
        cc = max(1, min(int(cap.get("concurrency") or 1), _MAX_FANOUT, n))
        kw = {k: v for k, v in kw.items() if k != "n"}   # 扇出 = 每请求单张
        done = {}
        with ThreadPoolExecutor(max_workers=cc) as p:
            futs = {}
            for i, u in enumerate(units):
                if i:
                    time.sleep(_STAGGER)
                futs[p.submit(_unit_call, fn, kw)] = u["index"]
            for f in as_completed(futs):
                done[futs[f]] = f.result()
        for u in units:
            idx = u["index"]
            paths, err = done.get(idx, (None, "未执行"))
            if paths is not None:
                _item_done(job_id, cid, idx, paths, reg_prompt, eff)
                continue
            # 阶梯3：降级串行重试一次（仅瞬时类失败值得重试）
            paths2, err2 = (None, err)
            if _transient(err):
                time.sleep(_STAGGER)
                paths2, err2 = _unit_call(fn, kw)
            if paths2 is not None:
                _item_done(job_id, cid, idx, paths2, reg_prompt, eff)
            else:
                _item_fail(job_id, cid, idx, err2 or err or "失败")
        return

    # 单张（含 upscale 全部情形）：直接执行
    paths, err = _unit_call(fn, kw)
    if paths is not None:
        _item_done(job_id, cid, units[0]["index"], paths, reg_prompt, eff)
    else:
        _item_fail(job_id, cid, units[0]["index"], err or "失败")


def _unit_call(fn, kw: dict):
    """执行单次调用。返回 (paths|None, err|None)；图片输入在此统一归一化。"""
    try:
        kw2 = dict(kw)
        if kw2.get("image"):
            imgs = kw2["image"]
            # 参考图可能是多张（各通道上限见 CAPS.image_refs）：必须逐张归一化——
            # 把 list 整体交给 to_data_uri 会因其只收 str 而抛错，导致多图 i2i 全废。
            kw2["image"] = [to_data_uri(x) for x in imgs] \
                if isinstance(imgs, (list, tuple)) else to_data_uri(imgs)
        out = fn(**kw2)
        if isinstance(out, str):
            out = [out]
        paths = [p for p in (out or []) if isinstance(p, str) and p.strip()]
        if not paths:
            return None, "服务端未返回图片"
        return paths, None
    except Exception as e:
        return None, str(e)


def _distribute(job_id: str, cid: str, units: list, paths, prompt: str,
                eff: dict = None) -> None:
    """通道自身 n 的单请求结果按序分派到各 item；少出图的部分记失败。"""
    paths = paths if isinstance(paths, list) else ([paths] if paths else [])
    for u in units:
        p = paths[u["index"] - 1] if u["index"] - 1 < len(paths) else None
        if p:
            _item_done(job_id, cid, u["index"], [p], prompt, eff)
        else:
            _item_fail(job_id, cid, u["index"], "服务端少出图")


def _item_done(job_id: str, cid: str, index: int, paths: list, prompt: str = "",
               eff: dict = None) -> None:
    works.register(paths, cid, prompt, job_id, eff)   # 作品登记簿（显示真相源）
    item = jobs.update_item(job_id, cid, index, "done", paths=paths)
    notify.emit("task.item", job_id=job_id, channel=cid, index=index,
                state="done", paths=list(paths), web=item.get("web") or [], error=None)


def _item_fail(job_id: str, cid: str, index: int, error: str) -> None:
    jobs.update_item(job_id, cid, index, "failed", error=str(error))
    notify.emit("task.item", job_id=job_id, channel=cid, index=index,
                state="failed", paths=[], web=[], error=str(error))

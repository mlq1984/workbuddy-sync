# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 凭证编排中心（统一入口 commit + 启动并发自检）。

commit(cid, key?) 是**唯一**的「落盘 + 验证 + 状态 + 广播」入口：
- 用户手粘 / 用户重验 / 通道页自动获取 / 账号流返回 key / 启动自检 全部汇入；
- store 是唯一真相源（纯存储，不认识通道）；验证经 registry 端口路由；
- 结果写回 store 并 emit status.changed（由 server 接到 SSE 广播）。

启动自检：线程池扇出，所有通道并发 commit，互不阻塞；
as_completed 归集——每完成一个就广播一个（不等待最慢者）。
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from . import builtin, store, switches
from .bus import bus
from .registry import all_channels, get_channel

logger = logging.getLogger("orchestrator")

STATUS_TTL_SECONDS = 300   # 可用性缓存时效：5 分钟内 --status 直接读缓存（秒回）


def commit(cid: str, key: str = None) -> dict:
    """统一落盘+验证入口。key 非空则先落盘；随后用仓库内 Key 验证并广播。

    免Key通道（契约可选字段 KEYLESS=True）：仓库无凭证也直接判"可用"。
    """
    if key and str(key).strip():
        store.set_key(cid, str(key).strip())
        bus.emit("cred.landed", cid=cid)
    elif key is not None:
        # 显式空串（UI 清空输入框验证）= 清除用户 Key，回退默认（内置兜底/无凭证）；
        # key=None（启动自检/CLI）= 仅重验当前凭据，绝不改动用户 Key。
        store.clear_key(cid)

    ch = get_channel(cid)
    if not ch:
        return {"ok": False, "valid": False, "message": "no such channel"}

    k = store.get_key(cid)
    if not k:
        b = builtin.get(cid)
        if b:
            k = b        # 内置兜底：无用户 Key 时按内置凭证验证（用户粘贴后自动优先）
        elif getattr(ch["module"], "KEYLESS", False):
            store.set_status(cid, True, "有效")
            status = store.get_status(cid)
            bus.emit("status.changed", cid=cid, status=status)
            return {"ok": True, "valid": True, "message": "有效"}
        else:
            # 无凭证：不覆盖已有状态，广播当前状态即可
            bus.emit("status.changed", cid=cid, status=store.get_status(cid))
            return {"ok": True, "valid": False, "message": "无凭证"}

    try:
        res = ch["module"].validate_key(k)
    except Exception as e:
        res = {"valid": False, "message": "验证异常: %s" % e}
    valid = bool(res.get("valid") if isinstance(res, dict) else res)
    msg = (res.get("message") if isinstance(res, dict) else "") or ("有效" if valid else "无效")
    store.set_status(cid, valid, msg)
    status = store.get_status(cid)
    bus.emit("status.changed", cid=cid, status=status)
    return {"ok": True, "valid": valid, "message": msg}


def view_status(cid: str) -> dict:
    """管理台/agent 视图状态：在 store 状态上叠加凭证类型语义（仅未验证时）。

    - 已验证（有效/无效）与"用户有 Key 未验"：原样返回（用户层语义不变）；
    - 无用户 Key + 有内置 → state=builtin，message=内置（表示当前生效的是内置）；
    - 无用户 Key + KEYLESS → 直接视为有效（免Key通道仅显示 有效/无效）；
    - 无用户 Key + 无内置 → state=nokey，message=需key。
    """
    st = store.get_status(cid)
    if st.get("state") != "unverified":
        return st
    if store.get_key(cid):
        return st                                   # 用户有 Key 未验 → 未验
    ch = get_channel(cid)
    if ch and getattr(ch["module"], "KEYLESS", False):
        st["state"], st["message"] = "valid", "有效"
    elif builtin.has(cid):
        st["state"], st["message"] = "builtin", "内置"
    else:
        st["state"], st["message"] = "nokey", "需key"
    return st


def credential_label(cid: str) -> str:
    """通道凭证状态标签（供 --status 选项清单说明）：免Key/用户Key/内置Key/需配置。"""
    ch = get_channel(cid)
    if ch and getattr(ch["module"], "KEYLESS", False):
        return "免Key"
    if store.get_key(cid):
        return "用户Key"
    if builtin.has(cid):
        return "内置Key"
    return "需配置"


def check_all(channel_ids=None, refresh: bool = False) -> list:
    """全通道可用性检查：并发 commit（零成本验证），按发现顺序归集结果。

    返回（每通道一项）：id/title/mode/description/icon/valid/message/checked_at。
    供 CLI（启动.py --status）与 auto 路由使用——编排器不生图，只回答"哪条路现在能走"。

    refresh=False（默认）：5 分钟内检查过的通道直接用缓存状态（秒回，不触网），
    落盘轮询场景因此近似零成本；refresh=True 强制全部实测。
    """
    chans = all_channels()
    if channel_ids:
        wanted = set(channel_ids)
        chans = [c for c in chans if c["id"] in wanted]
    if not chans:
        return []

    now = datetime.now()
    results, todo = {}, []
    for c in chans:
        st = store.get_status(c["id"])
        if not refresh and st.get("checked_at") and st.get("state") != "unverified":
            try:
                age = (now - datetime.fromisoformat(st["checked_at"])).total_seconds()
            except ValueError:
                age = None
            if age is not None and 0 <= age < STATUS_TTL_SECONDS:
                results[c["id"]] = {
                    "id": c["id"], "title": c["title"], "mode": c["mode"],
                    "description": c["description"], "icon": c["icon"],
                    "valid": bool(st.get("valid")), "message": st.get("message", ""),
                    "checked_at": st.get("checked_at"),
                    "enabled": switches.is_enabled(c["id"]),
                    "credential": credential_label(c["id"]),
                    "models": getattr(c["module"], "MODELS", None),
                }
                continue
        todo.append(c)

    if todo:
        with ThreadPoolExecutor(max_workers=min(8, len(todo))) as ex:
            futs = {ex.submit(commit, c["id"]): c for c in todo}
            for fut in as_completed(futs):
                c = futs[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = {"ok": False, "valid": False, "message": "检查异常: %s" % e}
                st = store.get_status(c["id"])
                results[c["id"]] = {
                    "id": c["id"], "title": c["title"], "mode": c["mode"],
                    "description": c["description"], "icon": c["icon"],
                    "valid": bool(r.get("valid")), "message": r.get("message", ""),
                    "checked_at": st.get("checked_at"),
                    "enabled": switches.is_enabled(c["id"]),
                    "credential": credential_label(c["id"]),
                    "models": getattr(c["module"], "MODELS", None),
                }
    return [results[c["id"]] for c in chans]


def startup_check() -> None:
    """启动自检：所有通道并发 commit（扇出/扇入），逐个广播，互不阻塞。"""
    cids = [c["id"] for c in all_channels()]
    if not cids:
        return
    logger.info("启动自检：%d 个通道并发验证", len(cids))
    with ThreadPoolExecutor(max_workers=min(8, len(cids))) as ex:
        futs = {ex.submit(commit, cid): cid for cid in cids}
        for fut in as_completed(futs):
            cid = futs[fut]
            try:
                r = fut.result()
                logger.info("自检完成 %s: %s", cid, r.get("message"))
            except Exception:
                logger.exception("自检失败 %s", cid)

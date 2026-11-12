# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 结果中心 · 任务仓库：状态机真相源 + TTL 惰性清理。设计见 references/architecture.md。

- 直调写入（executor 调用），不依赖事件送达；事件只喂浏览器；
- 单文件一任务：~/.aipro/jobs/<id>.json，tmp+os.replace 原子写（与 store/switches 同款）；
- state: pending → running → done | partial | failed（部分成功是合法终态）；
- web 换算统一由 media.web_path / media.resolve_web 承担（/works/<file>）。
"""
import json
import logging
import os
import random
import threading
from datetime import datetime, timedelta

from . import media   # web 换算（web_path/resolve_web）统一在 media

logger = logging.getLogger(__name__)

STATE_DIR = os.path.expanduser("~/.aipro")
JOBS_DIR = os.path.join(STATE_DIR, "jobs")
TTL_HOURS = 48

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _job_path(job_id: str) -> str:
    return os.path.join(JOBS_DIR, "%s.json" % job_id)


def _save(job: dict) -> None:
    os.makedirs(JOBS_DIR, exist_ok=True)
    p = _job_path(job["id"])
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def _load(job_id: str):
    try:
        with open(_job_path(job_id), encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception:
        logger.exception("任务档案读取失败：%s", job_id)
        return None


def cleanup() -> None:
    """TTL 惰性清理：删除超期任务文件；产物图片不清理（归用户资产）。"""
    cutoff = datetime.now() - timedelta(hours=TTL_HOURS)
    try:
        names = os.listdir(JOBS_DIR)
    except FileNotFoundError:
        return
    for name in names:
        if not name.endswith(".json"):
            continue
        p = os.path.join(JOBS_DIR, name)
        try:
            with open(p, encoding="utf-8") as f:
                job = json.loads(f.read())
            if datetime.fromisoformat(job.get("created_at")) < cutoff:
                os.remove(p)
        except Exception:
            continue


def create(spec: dict, channels: list, dropped: list, units: list) -> dict:
    """建任务（pending）。units: [{channel, index}]，预创建全部 item 便于前端先渲染骨架。"""
    with _LOCK:
        cleanup()
        job = {
            "id": "j%s_%04x" % (datetime.now().strftime("%Y%m%d%H%M%S"),
                                random.getrandbits(16)),
            "created_at": _now(), "started_at": None, "ended_at": None,
            "state": "pending",
            "spec": spec,
            "channels": channels,
            "dropped": dropped,
            "items": [dict(channel=u["channel"], index=u["index"], state="pending",
                           paths=[], web=[], error=None) for u in units],
            "summary": {"done": 0, "failed": 0, "total": len(units)},
        }
        _save(job)
    return job


def mark_started(job_id: str) -> None:
    with _LOCK:
        job = _load(job_id)
        if not job:
            return
        job["state"] = "running"
        job["started_at"] = _now()
        _save(job)


def get(job_id: str):
    return _load(job_id)


def list_jobs(limit: int = 20) -> list:
    """任务清单（新→旧）。返回完整任务 dict（本地任务量小，v1 不做分页摘要）。"""
    try:
        names = os.listdir(JOBS_DIR)
    except FileNotFoundError:
        return []
    ids = sorted((n[:-5] for n in names if n.endswith(".json")), reverse=True)[:limit]
    out = []
    for jid in ids:
        j = _load(jid)
        if j:
            out.append(j)
    return out


def update_item(job_id: str, channel: str, index: int, state: str,
                paths: list = None, error: str = None) -> dict:
    """更新单个条目并重算 summary；返回更新后的 item（含 web URL）。"""
    with _LOCK:
        job = _load(job_id)
        if not job:
            return {}
        item = next((it for it in job["items"]
                     if it["channel"] == channel and it["index"] == index), None)
        if item is None:
            return {}
        item["state"] = state
        if paths is not None:
            item["paths"] = list(paths)
            item["web"] = [w for w in (media.web_path(p) for p in item["paths"]) if w]
        if error is not None:
            item["error"] = str(error)
        job["summary"] = {
            "done": sum(1 for it in job["items"] if it["state"] == "done"),
            "failed": sum(1 for it in job["items"] if it["state"] == "failed"),
            "total": len(job["items"]),
        }
        _save(job)
        return item


def finalize(job_id: str, state: str) -> None:
    with _LOCK:
        job = _load(job_id)
        if not job:
            return
        job["state"] = state
        job["ended_at"] = _now()
        _save(job)


def rebase(mapping: dict) -> None:
    """产物目录迁移后，把任务档案中的旧路径批量改写到新根（web 随 web_path 重算）。"""
    if not mapping:
        return
    with _LOCK:
        try:
            names = os.listdir(JOBS_DIR)
        except FileNotFoundError:
            return
        for name in names:
            if not name.endswith(".json"):
                continue
            p = os.path.join(JOBS_DIR, name)
            try:
                with open(p, encoding="utf-8") as f:
                    job = json.loads(f.read())
                changed = False
                for it in job.get("items", []):
                    for i, pt in enumerate(it.get("paths", [])):
                        new = mapping.get(os.path.normpath(pt))
                        if new and new != pt:
                            it["paths"][i] = new
                            changed = True
                    it["web"] = [w for w in (media.web_path(x) for x in it.get("paths", [])) if w]
                if changed:
                    _save(job)
            except Exception:
                continue

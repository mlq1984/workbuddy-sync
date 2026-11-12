# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 统一凭证仓库（单文件·按通道分段）。

所有通道的 Key 与验证状态集中落在  ~/.aipro/credentials.json ，
按通道 id 分段。这是「统一路线」的唯一真相源；通道经 get_key(<id>) 读取。
"""
import json
import os
from datetime import datetime

STATE_DIR = os.path.expanduser("~/.aipro")
KEY_FILE = os.path.join(STATE_DIR, "credentials.json")

# 旧版状态目录（~/.agnes_orchestrator）一次性迁移，保住用户已有凭据后即不再使用
_LEGACY_DIR = os.path.expanduser("~/.agnes_orchestrator")


def _migrate_legacy() -> None:
    try:
        if os.path.exists(KEY_FILE) or not os.path.isdir(_LEGACY_DIR):
            return
        src = os.path.join(_LEGACY_DIR, "credentials.json")
        if os.path.isfile(src):
            os.makedirs(STATE_DIR, exist_ok=True)
            os.replace(src, KEY_FILE)
    except Exception:
        pass


def _migrate_channel_ids() -> None:
    """历史通道 id 迁移：gpt → aurora（Key 与验证状态原样保留，只改分段名）。"""
    try:
        data = _load()
        if "gpt" in data and "aurora" not in data:
            data["aurora"] = data.pop("gpt")
            _save(data)
    except Exception:
        pass


def _load() -> dict:
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception:
        return {}


def _save(data: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = KEY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, KEY_FILE)


def get_key(channel_id: str, fallback=None):
    seg = _load().get(channel_id) or {}
    k = seg.get("key")
    if k:
        return k
    return fallback() if callable(fallback) else fallback


def set_key(channel_id: str, key: str) -> None:
    data = _load()
    seg = data.get(channel_id) or {}
    seg["key"] = key
    # 钥匙变了 -> 旧状态失效，需重验
    seg.pop("valid", None)
    seg.pop("checked_at", None)
    seg.pop("message", None)
    data[channel_id] = seg
    _save(data)


def clear_key(channel_id: str) -> None:
    """清除用户 Key（保留段结构）：空提交=回退默认（内置兜底/无凭证）。"""
    data = _load()
    seg = data.get(channel_id)
    if seg is None:
        return
    seg.pop("key", None)
    # 钥匙没了 -> 旧状态失效，需重验
    seg.pop("valid", None)
    seg.pop("checked_at", None)
    seg.pop("message", None)
    _save(data)


def get_status(channel_id: str) -> dict:
    seg = _load().get(channel_id) or {}
    valid = bool(seg.get("valid"))
    checked = bool(seg.get("checked_at"))
    message = seg.get("message", "未验")
    # state 是给前端的"纯状态"：valid/invalid/unverified，前端只做渲染映射
    state = "valid" if valid else ("invalid" if checked else "unverified")
    return {"valid": valid, "checked_at": seg.get("checked_at"), "message": message, "state": state}


def set_status(channel_id: str, valid: bool, message: str) -> None:
    data = _load()
    seg = data.get(channel_id) or {}
    seg["valid"] = bool(valid)
    seg["checked_at"] = datetime.now().isoformat(timespec="seconds")
    seg["message"] = message
    data[channel_id] = seg
    _save(data)


# ---- 迁移（模块加载时执行一次；必须在 _load/_save 定义之后）----
_migrate_legacy()
_migrate_channel_ids()

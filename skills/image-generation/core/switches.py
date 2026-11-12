# -*- coding: utf-8 -*-
"""通道启用开关（用户偏好，通道中心统一管理）。落盘 ~/.aipro/switches.json，
未记录默认开启；闸门由 registry 统一包装 generate/upscale，通道零改动。"""
import json
import logging
import os

STATE_DIR = os.path.expanduser("~/.aipro")
SWITCH_FILE = os.path.join(STATE_DIR, "switches.json")

logger = logging.getLogger(__name__)


def _load() -> dict:
    try:
        with open(SWITCH_FILE, encoding="utf-8") as f:
            data = json.loads(f.read())
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("通道开关文件读取失败：%s", SWITCH_FILE)
        return {}


def _save(data: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = SWITCH_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, SWITCH_FILE)


# 发行方预设默认停用的通道（用户可随时在管理台打开）；默认全部通道开启
DEFAULT_OFF: set = set()


def is_enabled(channel_id: str) -> bool:
    """通道是否启用（未记录时默认开启）。"""
    return bool(_load().get(channel_id, channel_id not in DEFAULT_OFF))


def set_enabled(channel_id: str, enabled: bool) -> None:
    data = _load()
    data[channel_id] = bool(enabled)
    _save(data)

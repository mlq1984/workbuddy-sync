# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 通道注册表（通道无关，自动发现）。

设计（对应 references/architecture.md）：
- 不写死任何通道：扫描 channels/ 下每个含 app.py 的子目录，importlib 动态加载即注册。
- 模块隔离：每个通道的脚本以裸名（base/account/credential…）导入，加载完本通道后
  清理本次新增的非 app 模块，避免与后续通道同名文件冲突（如 agnes 的 credential.py / client.py）。
- 失败安全：某通道 app.py 导入失败 -> 记日志、跳过，绝不拖垮编排器。
- 通道经 app.py 暴露稳定契约（CHANNEL_ID/TITLE/MODE/DESCRIPTION/ICON + validate_key/acquire_key/account_api；
  可选：ORDER 清单顺序 / KEYLESS 免Key / CARD_MODE 卡片形态）。
"""
import importlib.util
import os
import sys
import traceback

from . import switches

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANNELS_DIR = os.path.join(ROOT, "channels")

# 可移植性（任何电脑/任意启动位置）：把技能根目录固定放进 sys.path，
# 保证通道 app.py 里的 `from core.store import ...` 不依赖启动时的 cwd——
# 无论是 `python -m core.server`、双击 启动.py、还是别处调用，资源都能动态找到。
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 进程内缓存：id -> 描述符
_CHANNELS = {}
_LOADED = False


def _gated(cid: str, name: str, fn):
    """启用闸门：停用通道的 generate/upscale 对任何调用方（含 Agent 直调）抛错。"""
    def wrapper(*a, **kw):
        if not switches.is_enabled(cid):
            raise RuntimeError("通道「%s」已被停用（管理台开关），仅能使用开启的通道。" % cid)
        return fn(*a, **kw)
    wrapper.__name__ = name
    return wrapper


def _gate_wrap(mod) -> None:
    cid = getattr(mod, "CHANNEL_ID", "?")
    for name in ("generate", "upscale"):
        fn = getattr(mod, name, None)
        if callable(fn):
            setattr(mod, name, _gated(cid, name, fn))


def _load_app(path: str, name: str):
    chan_dir = os.path.dirname(path)
    before = set(sys.modules.keys())
    sys.path.insert(0, chan_dir)
    try:
        spec = importlib.util.spec_from_file_location("orch_channel_%s" % name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
    finally:
        # 清理本次加载产生的通道内部模块（裸名），防止与后续通道同名冲突
        for k in list(sys.modules.keys()):
            if k not in before and k != spec.name:
                sys.modules.pop(k, None)
        if chan_dir in sys.path:
            sys.path.remove(chan_dir)
    return mod


def discover(force: bool = False) -> dict:
    """扫描并注册所有通道，返回 id -> 描述符 的字典。"""
    global _CHANNELS, _LOADED
    if _LOADED and not force:
        return _CHANNELS
    found = {}
    if os.path.isdir(CHANNELS_DIR):
        for name in sorted(os.listdir(CHANNELS_DIR)):
            d = os.path.join(CHANNELS_DIR, name)
            app_path = os.path.join(d, "app.py")
            if not (os.path.isdir(d) and os.path.isfile(app_path)):
                continue
            try:
                mod = _load_app(app_path, name)
                _gate_wrap(mod)
                cid = getattr(mod, "CHANNEL_ID", name)
                if cid in found:
                    print("[registry] 重复 CHANNEL_ID=%s（目录 %s 被跳过）" % (cid, name))
                    continue
                found[cid] = {
                    "id": cid,
                    "title": getattr(mod, "TITLE", cid),
                    "mode": getattr(mod, "MODE", "manual"),
                    "description": getattr(mod, "DESCRIPTION", ""),
                    "icon": getattr(mod, "ICON", "🔌"),
                    "order": int(getattr(mod, "ORDER", 100)),
                    "module": mod,
                    "dir": d,
                }
            except Exception as e:
                print("[registry] 跳过通道 %s: %s\n%s" % (name, e, traceback.format_exc()))
    # 动态自定义通道（数据化注册，~/.aipro/custom_channels.json；用户数据不进技能本体）：
    # 适配器为 module-like 对象（CHANNEL_ID/TITLE/generate/validate_key/CAPS…），
    # 与文件夹通道同构，gate 包装、能力协商、执行链路零特判。
    from . import custom_channels
    for rec in custom_channels.list_channels():
        cid = rec["id"]
        if cid in found:
            continue
        models = custom_channels.models_of(rec)
        found[cid] = {"id": cid, "title": rec["name"], "mode": "manual",
                      "description": "【自定义】%s · %s 协议中转（文生图/图生图；模型：%s）" % (
                          rec["name"], rec["protocol"], "、".join(models)),
                      "icon": "🌐", "order": 150,
                      "module": custom_channels.adapter(rec), "dir": None}
    # 卡片/清单顺序：通道可选声明 ORDER（小者在前），未声明按 id 排尾
    _CHANNELS = dict(sorted(found.items(), key=lambda kv: (kv[1]["order"], kv[0])))
    _LOADED = True
    return _CHANNELS


def reload():
    """热刷新：重新扫描通道目录。"""
    global _LOADED
    _LOADED = False
    return discover(force=True)


def all_channels():
    return list(discover().values())


def get_channel(channel_id: str):
    return discover().get(channel_id)


def get_channel_dir(channel_id: str):
    ch = discover().get(channel_id)
    return ch["dir"] if ch else None


def get_meta(channel_id: str) -> dict:
    ch = discover().get(channel_id)
    if not ch:
        return {}
    return {
        "id": ch["id"], "title": ch["title"], "mode": ch["mode"],
        "description": ch["description"], "icon": ch["icon"],
        "card": getattr(ch["module"], "CARD_MODE", "full"),
        "acquire_url": getattr(ch["module"], "ACQUIRE_URL", None),
        "placeholder": getattr(ch["module"], "PLACEHOLDER", None),
    }

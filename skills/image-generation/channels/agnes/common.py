"""Agnes 通道 · 配置与错误信息（仅通道策略；HTTP/落盘等公共机制见 core.httpx / core.media）。

用户配置：~/.agnes/config.ini（可用环境变量 AGNES_HOME 重定向）只存覆盖项，
默认值的唯一来源是本文件 DEFAULTS；Key 不在此处——统一凭证由编排器管理
（~/.aipro/credentials.json，经 core.store 读取）。
"""
import configparser
import os

HOME_ENV = "AGNES_HOME"          # 允许用户把数据目录挪到网盘等位置
DEFAULT_HOME_NAME = ".agnes"     # 默认家目录下的隐藏目录

# 全部默认值的唯一事实来源（用户配置里只写想覆盖的项；严禁在别处再抄一份同样内容）
DEFAULTS = {
    "common": {
        "base_url": "https://api.agnes-ai.cn/v1",
        "credential_timeout": "900",
    },
    "account": {
        "backend": "https://platform-backend.agnes-ai.cn",
        "token_name": "Agnes生图",
        "token_profile": "default",
        "reuse_token": "true",
    },
    "image": {
        "default_model": "agnes-image-2.5-flash",
        "n": "1",
        "response_format": "url",
        "timeout": "360",
    },
}


def home_dir() -> str:
    """用户数据目录：默认 ~/.agnes，可用环境变量 AGNES_HOME 覆盖。"""
    return os.environ.get(HOME_ENV) or os.path.join(os.path.expanduser("~"), DEFAULT_HOME_NAME)


def user_config_path() -> str:
    """用户级配置路径（技能外，运行时唯一读写对象）。"""
    return os.path.join(home_dir(), "config.ini")


def load_config(path: str = None) -> configparser.ConfigParser:
    """读配置：代码内置 DEFAULTS 打底，用户配置（技能外）只做覆盖。"""
    cfg = configparser.ConfigParser()
    for sec, items in DEFAULTS.items():
        cfg[sec] = dict(items)
    try:
        target = path or user_config_path()
    except Exception:
        target = None
    if target and os.path.exists(target):
        user = configparser.ConfigParser()
        user.read(target, encoding="utf-8")
        for sec in user.sections():
            if not cfg.has_section(sec):
                cfg.add_section(sec)
            for k, v in user.items(sec):
                cfg.set(sec, k, v)
    return cfg


def errmsg(payload) -> str:
    """从 Agnes 错误响应里提取可读 message。"""
    if isinstance(payload, dict):
        e = payload.get("error")
        if isinstance(e, dict) and e.get("message"):
            return e["message"]
        if payload.get("message"):
            return payload["message"]
    return str(payload)

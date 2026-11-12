# -*- coding: utf-8 -*-
"""通道 · Cogview-3-Flash（智谱 BigModel，引导式 manual 模式）。

设计：官方直连 + OpenAI 兼容，CogView-3-Flash 为官方免费模型（出图带"AI生成"
合规标识）。通道页「获取」按钮直跳官方 API Key 控制台，用户建 Key 后回管理台
粘贴 → 经统一入口 commit 落盘+校验+广播。

本文件是通道与编排器之间的**唯一桥**：
- 暴露稳定契约（CHANNEL_ID/TITLE/MODE/DESCRIPTION/ICON + validate_key/acquire_key
  + generate）；
- 钥匙经 core.store 统一读写，不落外部 config.ini；
- 生图策略见本目录 client.py（官方 /v4/images/generations）。
"""
from core.credprovider import resolve as get_key   # 凭证提供层：用户Key优先→内置兜底

from client import CogViewClient

CHANNEL_ID = "zhipu"
TITLE = "Cogview-3-Flash"
MODE = "manual"      # 用户从官方控制台复制 Key 后粘贴，符合 manual 语义
ORDER = 5
DESCRIPTION = ("官方直连 · CogView 系列（3-Flash 免费 / 4 付费）；"
               "免费档无次数计费（出图带\"AI生成\"合规标识）。"
               "仅支持文生图，画质约 1K 多档分辨率；"
               "获取可快速跳转官方 API Key 控制台。"
               "质量一般至高、中文理解好，出图快（约 10 秒）。")
MODELS = ("cogview-3-flash", "cogview-4-250304")  # 可选模型（默认在前；spec.model 可指定；付费档为官方带日期后缀 ID）
ICON = "🧠"

# 官网入口：API Key 控制台（创建/复制 Key 在此完成）；管理台「获取」按钮直跳此处
ACQUIRE_URL = "https://bigmodel.cn/apikey/platform"


def validate_key(key: str) -> dict:
    """零成本探活：GET /v4/models；200 有效，401/403 判无效，网络异常按有效放行。"""
    if not key:
        return {"valid": False, "message": "空 Key"}
    try:
        from core.httpx import http_json
        status, _ = http_json("GET", CogViewClient.BASE + "/models",
                              token=key, timeout=15)
        if status == "ERR":
            return {"valid": True, "message": "有效"}   # 网络问题不误杀
        ok = status == 200
    except Exception:
        return {"valid": True, "message": "有效"}   # 网络问题不误杀
    return {"valid": bool(ok), "message": "有效" if ok else "无效"}


def acquire_key():
    """manual 模式：钥匙由用户从官方控制台复制粘贴提供，此处返回 None。"""
    return None


# ---- 生成中心声明（references/architecture.md，可选契约：能力集 + 方言翻译）----
CAPS = {"i2i": False, "upscale": False, "n": False,
        "lang": "zh",                      # 通道自治声明：中文原生更稳（CogView 中文理解好）
        "tiers": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],   # 官方分辨率档仅此 5 种；
        # 越族比例由协商层就近降级——此前 CAPS 超报 8 种，客户端未命中即回落 1024x1024，成静默方图
        "concurrency": 2}


def translate(clean: dict) -> dict:
    """通用 spec → 本通道 generate kwargs（纯映射，禁 IO；仅文生图）。

    ratio → client._size 映射官方分辨率档；约 1K 画质，tier 不透传。
    """
    kw = {"prompt": clean["prompt"]}
    if clean.get("model"):
        kw["model"] = clean["model"]
    if clean.get("ratio"):
        kw["size"] = clean["ratio"]
    return kw


def generate(prompt, **kw):
    """统一调用层透传：从统一仓库取 Key，交给通道客户端生图（文生图）。"""
    key = get_key(CHANNEL_ID)
    if not key:
        raise RuntimeError("请先在通道管理台为「Cogview-3-Flash」配置 Key（官方控制台创建后粘贴）。")
    return CogViewClient(api_key=key).generate(prompt, **kw)

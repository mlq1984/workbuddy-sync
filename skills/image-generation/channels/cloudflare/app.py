# -*- coding: utf-8 -*-
"""通道 · Cloudflare Flux（Cloudflare Workers AI，引导式 manual 模式）。

设计：官方直连，flux-1-schnell 免费额度每天 10,000 Neurons 自动重置（约 173 张/天，
1024x1024/4步，无水印）。通道页「获取」按钮直跳 Cloudflare API Token 页，用户创建
Token 后回管理台粘贴 → 经统一入口 commit 落盘+校验+广播。

本文件是通道与编排器之间的**唯一桥**：
- 暴露稳定契约（CHANNEL_ID/TITLE/MODE/DESCRIPTION/ICON + validate_key/acquire_key
  + generate）；
- 钥匙经 core.store 统一读写，不落外部 config.ini；
- 生图策略见本目录 client.py（官方 /ai/run/{model}）。
"""
from core.httpx import http_json
from core.credprovider import resolve as get_key   # 凭证提供层：用户Key优先→内置兜底

from client import WorkersAIClient

CHANNEL_ID = "cloudflare"
TITLE = "Cloudflare Flux"
MODE = "manual"      # 用户从官方控制台复制 Token 后粘贴，符合 manual 语义
ORDER = 4
DESCRIPTION = ("官方直连 · flux-1-schnell / sdxl / sd15 系列（**尺寸能力按型号**：flux-1-schnell 固定 1024×1024，sdxl/sd15 支持 width/height）；"
               "每天免费 10000 Neurons（约 173 张，自动重置）。"
               "仅支持文生图，画质约 1K、无水印；"
               "粘贴 Token 或 Token@AccountID；"
               "获取可快速跳转官方 API Token 控制台。质量一般至高，出图快（约 7 秒）。")
MODELS = ("flux-1-schnell", "sdxl", "sd15")  # 可选模型（默认在前；spec.model 可指定）
ICON = "⚡"

# 官网入口：API Token 创建页；管理台「获取」按钮直跳此处
ACQUIRE_URL = "https://dash.cloudflare.com/profile/api-tokens"

# 卡片 Key 输入框占位符（可选契约）：提示本通道的复合格式
PLACEHOLDER = "Token@AccountID（或仅 Token）"


def validate_key(key: str) -> dict:
    """零成本探活：GET /user/tokens/verify；success=true 有效，401/403 判无效，网络异常按有效放行。

    支持 `token@account_id` 复合格式：校验只针对 Token 本身，Account ID 在生图时生效。
    """
    token, _ = WorkersAIClient.parse_key(key)
    if not token:
        return {"valid": False, "message": "空 Key"}
    try:
        status, payload = http_json("GET", "%s/user/tokens/verify" % WorkersAIClient.BASE,
                                    token=token, timeout=15)
        if status == "ERR":
            return {"valid": True, "message": "有效"}   # 网络问题不误杀
        ok = status == 200 and isinstance(payload, dict) and payload.get("success")
    except Exception:
        return {"valid": True, "message": "有效"}   # 网络问题不误杀
    return {"valid": bool(ok), "message": "有效" if ok else "无效"}


def acquire_key():
    """manual 模式：钥匙由用户从官方控制台复制粘贴提供，此处返回 None。"""
    return None


# ---- 生成中心声明（references/architecture.md，可选契约：能力集 + 方言翻译）----
CAPS = {"i2i": False, "upscale": False, "n": False,
        "lang": "en",                      # 通道自治声明：中文 prompt 需转英文（官方 Flux 中文渲染弱）
        "tiers": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "concurrency": 3}
# 能力按型号细分（官方口径，developers.cloudflare.com 模型页）：
#   flux-1-schnell —— 官方不支持任意尺寸（512×512 tile 拼接，恒为方图）
#   sdxl / sd15    —— 官方支持 width/height（≤1024、8 的倍数）
MODEL_CAPS = {
    "flux-1-schnell": {"ratios": ["1:1"]},
    "flux": {"ratios": ["1:1"]},        # client 侧 flux 别名同样路由到 flux-1-schnell
    "sdxl": {"ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"]},
    "sd15": {"ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"]},
}


def translate(clean: dict) -> dict:
    """通用 spec → 本通道 generate kwargs（纯映射，禁 IO；仅文生图）。

    flux 系固定官方尺寸（client._size 忽略尺寸参数）；SDXL 系接受 ratio → WxH。
    """
    kw = {"prompt": clean["prompt"]}
    if clean.get("model"):
        kw["model"] = clean["model"]
    if clean.get("ratio"):
        kw["size"] = clean["ratio"]
    _st = (clean.get("options") or {}).get("steps")
    if _st is not None:
        try:
            kw["steps"] = max(1, min(8, int(_st)))   # 官方 1~8（默认 4）
        except (TypeError, ValueError):
            pass
    return kw


def generate(prompt, **kw):
    """统一调用层透传：从统一仓库取 Key，交给通道客户端生图（文生图）。"""
    key = get_key(CHANNEL_ID)
    if not key:
        raise RuntimeError("请先在通道管理台为「Cloudflare Flux」配置 Token（官方控制台创建后粘贴）。")
    return WorkersAIClient(api_key=key).generate(prompt, **kw)

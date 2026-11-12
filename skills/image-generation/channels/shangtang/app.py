# -*- coding: utf-8 -*-
"""通道 · 商汤日日新（SenseNova，引导式 manual 模式）。

设计（与用户商定）：不去逆向官网的 Hydra OAuth 登录流；改为——
- 通道页「前往官网」按钮跳到 SenseNova 官网，用户自己在官网完成登录/注册与「创建 API Key」；
- 用户在官网复制 Key，回通道页（或管理台卡片）粘贴 → 经统一入口 commit 落盘+校验+广播。

本文件是通道与编排器之间的**唯一桥**：
- 暴露稳定契约（CHANNEL_ID/TITLE/MODE/DESCRIPTION/ICON + validate_key/acquire_key
  + generate/upscale/SUPPORTS_UPSCALE）；
- 钥匙经 core.store 统一读写，不落外部 config.ini；
- 生图策略见本目录 client.py（官方 /v1/images/generations + /v1/images/edits）。
"""
from core.credprovider import resolve as get_key   # 凭证提供层：用户Key优先→内置兜底

from client import SenseNovaClient, RATIO_SIZES, TIER_SIZES

CHANNEL_ID = "shangtang"
TITLE = "商汤日日新"
MODE = "manual"      # 用户从官网复制 Key 后粘贴，符合 manual 语义
ORDER = 3
DESCRIPTION = ("官方直连 · sensenova-u1.5 系列（lite/fast）；"
               "按量计费（新用户含赠送额度）。"
               "支持文生图 + 图生图（编辑）+ 增强放大，画质最高 4K；"
               "获取可快速跳转官方 Key 控制台。"
               "质量高、指令遵循强，速度中等（约 20 秒/张）。")
MODELS = ("sensenova-u1.5-lite", "sensenova-u1.5-fast")  # 可选模型（默认在前；spec.model 可指定）
ICON = "🌅"

# 官网入口：登录 + 控制台 Key 管理（创建/复制 Key 在此完成）；管理台「获取」按钮直跳此处
ACQUIRE_URL = "https://platform.sensenova.cn/console/keys"
SITE_LOGIN = "https://platform.sensenova.cn/login"
SITE_KEYS = "https://platform.sensenova.cn/console/keys"


def validate_key(key: str) -> dict:
    """探活：SenseNova 以 Bearer 调用模型列表；200 有效，网络异常按有效放行（避免误杀）。"""
    if not key:
        return {"valid": False, "message": "空 Key"}
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://token.sensenova.cn/v1/models",
            headers={"Authorization": "Bearer %s" % key, "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = r.status == 200
    except Exception as e:
        msg = str(e)
        if "401" in msg or "403" in msg:
            return {"valid": False, "message": "无效"}
        return {"valid": True, "message": "有效"}   # 网络问题不误杀
    return {"valid": bool(ok), "message": "有效" if ok else "无效"}


def acquire_key():
    """manual 模式：钥匙由用户从官网复制粘贴提供，此处返回 None。"""
    return None


# ---- 生成中心声明（references/architecture.md，可选契约：能力集 + 方言翻译）----
CAPS = {"i2i": True, "upscale": True, "n": False,
        "lang": "zh",                      # 通道自治声明：中文更稳（日日新中文原生）
        "tiers": ["1K", "2K", "4K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],   # 官方推荐分辨率表含 3:2/2:3（2K 档 2496x1664 / 1664x2496）
        "concurrency": 2, "image_refs": 5}


def translate(clean: dict) -> dict:
    """通用 spec → 本通道 generate/upscale kwargs（纯映射，禁 IO；spec 字段见 core/params）。"""
    if clean["action"] == "upscale":
        kw = {"image": clean["image"], "scale": clean.get("scale", 2)}
        if clean.get("upscale_prompt"):
            kw["prompt"] = clean["upscale_prompt"]
        return kw
    kw = {"prompt": clean["prompt"]}
    if clean.get("image"):
        kw["image"] = clean["image"]          # 图生图（编辑）
    if clean.get("model"):
        kw["model"] = clean["model"]
    for _k in ("watermark", "output_format", "prompt_extend", "response_format"):
        _v = (clean.get("options") or {}).get(_k)
        if _v is not None:
            kw[_k] = _v               # 官方完整参数透传（client 已全量支持）
    if clean.get("image") and not clean.get("ratio"):
        # 图生图：无用户构图意图 → 不传 size（官方 auto 自动适配主图）。
        # 实测坐实：非方主图 + 显式 WxH 会改变主图比例（1280x704 主图 + 2048x2048 → 方形输出）；
        # "放大到高分辨率"诉求由 upscale（scale）承担，generate(i2i) 不越界。
        return kw
    if clean.get("tier"):
        t = clean["tier"]
        ratio = clean.get("ratio") or ""
        if t == "1K":
            kw["size"] = ratio or "auto"       # 1K 档：官方 1K 表（RATIO_SIZES）映射；无构图交 auto
        elif (t, ratio) in TIER_SIZES:
            kw["size"] = TIER_SIZES[(t, ratio)]  # 官方建议分辨率（真机验证精确生效）
        elif ratio:
            f = {"2K": 2, "4K": 4}[t]          # 官方未列组合：1K 基准 × 倍数
            w, _, h = RATIO_SIZES.get(ratio, "1280x720").partition("x")
            w, h = int(w) * f, int(h) * f
            if max(w, h) > 4096:               # 超限整体缩保持比例（_clamp 逐边夹紧会破坏构图）
                s = 4096.0 / max(w, h)
                w, h = int(round(w * s)), int(round(h * s))
            kw["size"] = "%dx%d" % (w, h)
        else:
            kw["size"] = t                     # 无构图：client._size 落 SIZE_FALLBACK WxH
    elif clean.get("ratio"):
        kw["size"] = clean["ratio"]           # ratio → 官方 1K 档映射
    return kw


def generate(prompt, **kw):
    """统一调用层透传：从统一仓库取 Key，交给通道客户端生图（文生图/图生图）。"""
    key = get_key(CHANNEL_ID)
    if not key:
        raise RuntimeError("请先在通道管理台为「商汤日日新」配置 Key（官网创建后粘贴）。")
    return SenseNovaClient(api_key=key).generate(prompt, **kw)


SUPPORTS_UPSCALE = True


def upscale(image, scale=2, prompt=None, **kw):
    """放大(增强)：以原图作参考、目标分辨率档位调高后重绘放大，返回本地图片路径列表。"""
    key = get_key(CHANNEL_ID)
    if not key:
        raise RuntimeError("请先在通道管理台为「商汤日日新」配置 Key（官网创建后粘贴）。")
    return SenseNovaClient(api_key=key).upscale(image, scale=scale, prompt=prompt, **kw)

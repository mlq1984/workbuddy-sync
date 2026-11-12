# -*- coding: utf-8 -*-
"""通道 · Aurora绮梦绘（manual 模式）。

本文件是通道与编排器之间的**唯一桥**：
- 暴露稳定契约（CHANNEL_ID/TITLE/MODE/DESCRIPTION/ICON + validate_key/acquire_key/account_api）；
- 生图由本通道的 GPTImageClient 完成，编排器(core) 永不调用 generate；
- 钥匙经 core.store 统一读写，不落地到本通道自己的 config.ini。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from base import BaseClient
from gpt_image import GPTImageClient
from nano_banana import NanoBananaClient
from core.credprovider import resolve as get_key   # 凭证提供层：用户Key优先→内置兜底

CHANNEL_ID = "aurora"
TITLE = "Aurora绮梦绘"
MODE = "manual"
ORDER = 1
DESCRIPTION = ("渠道中转 · gpt-image / nano-banana 两大系列，公益免费（满足部分条件）！"
               "支持文生图 + 图生图（编辑，≤2 参考图）+ 增强放大；"
               "画质 1K~4K（nano-banana 系全档；gpt-image-2 仅 1K，gpt-image-2-vip 支持 1K/2K/4K）。"
               "质量高至极高、细节丰富，速度中等（2K/4K 出图较慢）。")
MODELS = ("gpt-image-2", "nano-banana-2", "gpt-image-2-vip",
          "nano-banana-pro", "nano-banana-2-lite")  # 中继在售型号（默认在前；spec.model 可指定；vip/pro 支持 2K/4K，gpt-image-2 与 lite 仅 1K）
ICON = "🛰️"

# 取 Key 页外置 Cloudflare Pages 子域（不在本地技能包内）：管理台「获取」按钮直跳此处
ACQUIRE_URL = "https://yd.cfdaili.top/"


def validate_key(key: str) -> dict:
    """零成本探活：GET /v1/tasks/{假任务号}（详情路由）；401/403 判无效，
    平台路由限制型 403 与网络异常按有效放行（详见 base.BaseClient.validate_key）。"""
    if not key:
        return {"valid": False, "message": "空 Key"}
    try:
        ok = BaseClient(api_key=key).validate_key(key)
    except Exception as e:
        return {"valid": False, "message": "探测异常: %s" % e}
    return {"valid": bool(ok), "message": "有效" if ok else "无效"}


def acquire_key():
    """manual 模式：钥匙由用户在通道页粘贴回填，此处返回 None。"""
    return None


def account_api(action, payload):
    return {"ok": False, "msg": "manual 通道无账号接口"}


# ---- 生成中心声明（references/architecture.md，可选契约：能力集 + 方言翻译）----
CAPS = {"i2i": True, "upscale": True, "n": False,
        "tiers": ["1K", "2K", "4K"],
        "ratios": ["1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "21:9"],
        "concurrency": 2, "image_refs": 2}   # 中继透传 image[] 数组；实测 2 张通过（更高上限待真机验证可调）


def translate(clean: dict) -> dict:
    """通用 spec → 本通道 generate/upscale kwargs（纯映射，禁 IO；spec 字段见 core/params）。"""
    if clean["action"] == "upscale":
        kw = {"image": clean["image"], "scale": clean.get("scale", 2)}
        if clean.get("upscale_prompt"):
            kw["prompt"] = clean["upscale_prompt"]
        # 与 generate 同构：模型/档位/比例照常透传（base.upscale 均可接收）。
        # 不透传的后果：放大永远用默认模型（选 nano 无效）、档位退回 scale 推导、比例退回源图。
        if clean.get("model"):
            kw["model"] = clean["model"]
        if clean.get("tier"):
            kw["image_size"] = clean["tier"]
        if clean.get("ratio"):
            kw["size"] = clean["ratio"]
        _ar = (clean.get("options") or {}).get("aspect_ratio")
        if _ar is not None:
            kw["aspect_ratio"] = str(_ar)     # 与 generate 同构（仅 nano-banana 路由生效）
        return kw
    kw = {"prompt": clean["prompt"]}
    if clean.get("image"):
        kw["image"] = clean["image"]          # 图生图（编辑）
    if clean.get("model"):
        kw["model"] = clean["model"]
    _ar = (clean.get("options") or {}).get("aspect_ratio")
    if _ar is not None:
        kw["aspect_ratio"] = str(_ar)         # 仅 nano-banana 路由生效（app.generate 摘出）
    if clean.get("ratio"):
        kw["size"] = clean["ratio"]           # 比例
    if clean.get("tier"):
        kw["image_size"] = clean["tier"]      # 清晰度档位
    return kw


def generate(prompt, **kw):
    """统一调用层透传：从统一仓库取 Key，交给通道客户端生图。

    按 model 名路由到对应客户端：含 nano/banana 走 NanoBananaClient，
    其余（默认 gpt-image 系列）走 GPTImageClient；两者共用 base 的 OpenAI 兼容流程。
    """
    key = get_key(CHANNEL_ID)
    if not key:
        raise RuntimeError("请先在通道管理台为「Aurora绮梦绘」配置 Key（获取/粘贴并验证）。")
    model = str(kw.get("model") or "")
    aspect_ratio = kw.pop("aspect_ratio", None)   # 仅 nano-banana 官方参数，gpt-image 路由不透传
    if "nano" in model.lower() or "banana" in model.lower():
        client = NanoBananaClient(api_key=key)
        if aspect_ratio is not None:
            return client.generate(prompt, aspect_ratio=aspect_ratio, **kw)
        return client.generate(prompt, **kw)
    client = GPTImageClient(api_key=key)
    return client.generate(prompt, **kw)


SUPPORTS_UPSCALE = True


def upscale(image, scale=2, prompt=None, **kw):
    """放大(增强)：以源图作参考、目标分辨率调高后重绘放大，返回本地图片路径列表。

    按 model 名路由到对应客户端（与 generate 一致），两者共用 base 的 upscale。
    """
    key = get_key(CHANNEL_ID)
    if not key:
        raise RuntimeError("请先在通道管理台为「Aurora绮梦绘」配置 Key（获取/粘贴并验证）。")
    model = str(kw.get("model") or "")
    _ar = kw.pop("aspect_ratio", None)        # 与 generate 同构：aspect_ratio 仅 nano-banana 路由透传
    if "nano" in model.lower() or "banana" in model.lower():
        client = NanoBananaClient(api_key=key)
        if _ar is not None:
            kw["aspect_ratio"] = _ar
    else:
        client = GPTImageClient(api_key=key)
    return client.upscale(image, scale=scale, prompt=prompt, **kw)

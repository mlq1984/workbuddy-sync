# -*- coding: utf-8 -*-
"""通道 · Pollinations 免Key直出（keyless）。

本文件是通道与编排器之间的**唯一桥**：
- KEYLESS=True：无需注册、无需任何 Key；validate_key 恒真，编排器不要求落盘凭证；
- 生图由本通道 generate 完成，编排器(core) 永不调用 generate 之外的入口；
- 产物经 core.media 统一落盘关联产物根（缺省桌面 Ai公益生图Pro 目录，平铺直存、登记 img.json），返回本地文件路径列表。

接口：GET https://image.pollinations.ai/prompt/<prompt>?width&height&model&seed&nologo&private
  - nologo=true 对匿名档已失效（参数仍发送，服务端恢复即自动生效）；private=true 不公开；seed 固定则同提示词复现同图；
  - flux 高质量 / turbo 极速；flux 失败自动降级 turbo（同 seed 保构图）；
  - 响应体 <1KB 视为错误页。
"""
import os
import random
import sys
import time
import urllib.parse

from core.credprovider import resolve as get_key   # 用户 Key 优先（free 无内置兜底）
from core.httpx import fetch_bytes
from core.media import save_output

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

CHANNEL_ID = "free"
TITLE = "Pollinations"
MODE = "manual"
ORDER = 6                 # 通道模式保持二值；免Key是正交能力，用 KEYLESS 表达
DESCRIPTION = ("官方直连 · flux / turbo 模型；"
               "完全免费（公共接口有频次限制），无需注册与 Key。"
               "仅支持文生图，画质约 1K（宽高可调）、右下角带服务端水印；"
               "获取无需任何凭证、粘贴即用。"
               "质量低至一般，turbo 数秒极速，固定 seed 可复现同图。")
MODELS = ("flux", "turbo")  # 可选模型（默认在前；spec.model 可指定）
ICON = "🌱"
KEYLESS = True
SUPPORTS_UPSCALE = False

API_BASE = "https://image.pollinations.ai/prompt/"
MIN_BYTES = 1024                # 响应小于 1KB 视为错误页
TIMEOUT = 240                   # 免费档可能排队，单次上限放宽
RETRIES = 4                     # 同模型重试次数（TLS 干扰窗口摆动 + 排队瞬断）


def validate_key(key=None):
    """免Key通道：恒可用。"""
    return {"valid": True, "message": "有效"}


def acquire_key():
    return None


def account_api(action, payload):
    return {"ok": False, "msg": "免Key通道无账号接口"}


def upscale(image=None, scale=2, prompt=None, **kw):
    """Pollinations 免费通道不支持放大（无图生图能力），明确报错并引导改用其余通道。"""
    raise RuntimeError(
        "Pollinations 免费通道不支持放大（无图生图能力）；"
        "请改用 aurora 或 agnes 通道进行放大。")


def _build_url(prompt, width, height, model, seed, enhance):
    q = urllib.parse.quote(str(prompt), safe="")
    params = {
        "width": str(int(width)),
        "height": str(int(height)),
        "model": model,
        "seed": str(int(seed)),
        "nologo": "true",
        "private": "true",
    }
    if enhance:
        params["enhance"] = "true"
    return "%s%s?%s" % (API_BASE, q, urllib.parse.urlencode(params))


def _fetch(url, key=None):
    """拉取图片字节。返回 bytes；失败/错误页抛 RuntimeError（重试/降级由 generate 编排）。

    key 可选（用户自己的 Pollinations sk_ Key）：按官方 bearerAuth 走 Authorization 头、
    不进 URL——匿名档（无 Key）请求与此前逐字节一致；错误消息对 query 脱敏。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AiPro-Free/1.0",
        "Accept": "image/*,*/*",
    }
    if key:
        headers["Authorization"] = "Bearer %s" % key
    try:
        data = fetch_bytes(url, timeout=TIMEOUT, extra_headers=headers)
    except Exception as e:
        raise RuntimeError("请求失败: %s" % str(e).split("?")[0])
    if len(data) < MIN_BYTES:
        raise RuntimeError("响应过小(%dB)，疑似服务端错误页" % len(data))
    return data


# ---- 生成中心声明（references/architecture.md，可选契约：能力集 + 方言翻译）----
CAPS = {"i2i": False, "upscale": False, "n": True,
        "lang": "en",                      # 通道自治声明：中文 prompt 需转英文
        "tiers": ["1K"],
        "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"],
        "concurrency": 1}   # 匿名档限流最严：即便支持 n 也不自行扇出


def translate(clean: dict) -> dict:
    """通用 spec → 本通道 generate kwargs（纯映射，禁 IO；仅文生图）。

    ratio/1K 档换算像素宽高（8 的倍数，基准 1024，短边 ≥256）。
    """
    kw = {"prompt": clean["prompt"]}
    if clean.get("model"):
        kw["model"] = clean["model"]
    if clean.get("n"):
        kw["n"] = clean["n"]                  # 服务端单请求多张（seed 递增）
    _op = clean.get("options") or {}
    if _op.get("enhance") is not None:
        kw["enhance"] = _op["enhance"]        # 通道专属参数：服务端润色提示词（api.md 已列，必须可达）
    ratio = clean.get("ratio")
    if ratio:
        a, _, b = ratio.partition(":")
        try:
            w = int(round(1024 * int(a) / int(b) / 8.0)) * 8
            h = int(round(1024 * int(b) / int(a) / 8.0)) * 8
        except Exception:
            w = h = 1024
        kw["width"] = max(256, min(1024, w))
        kw["height"] = max(256, min(1024, h))
    return kw


def generate(prompt, width=1024, height=1024, model="flux", seed=None,
             enhance=False, n=1, **kw):
    """免Key生图。返回本地文件路径列表（与 agnes b64 形态一致）。

    - seed 缺省随机；固定 seed + 同提示词 = 复现同图；
    - n>1 时在 seed 基础上递增出多张（显式传 seed 也可复现整组）；
    - flux 失败自动降级 turbo（同 seed 保构图）。
    """
    if not str(prompt or "").strip():
        raise RuntimeError("提示词不能为空")
    base_seed = random.randint(0, 2 ** 31 - 1) if seed is None else int(seed)
    model = str(model or "flux").lower()
    if model not in MODELS:      # 与 SKILL/architecture 口径一致：不静默回落，如实报错并列可用型号
        raise RuntimeError("模型不在本通道清单: %s（可用: %s）" % (model, "、".join(MODELS)))
    n = max(1, min(int(n or 1), 4))

    key = get_key(CHANNEL_ID)    # 可选：用户配置了官方 Key 则走 Bearer（付费档取决于 Key 权限）
    paths = []
    for i in range(n):
        s = base_seed + i
        data = None
        last_err = None
        for attempt in range(1, RETRIES + 1):
            try:
                data = _fetch(_build_url(prompt, width, height, model, s, enhance), key=key)
                break
            except RuntimeError as e:
                last_err = e
                time.sleep(min(2 * attempt, 6))      # 退避抓出网窗口
        if data is None:
            if model == "flux" and "402" in str(last_err):
                # 402 = 匿名档额度受限；turbo/gptimage 已转付费，降级无意义，如实报错
                raise RuntimeError(
                    "Pollinations 匿名档额度受限（HTTP 402 匿名出图被拒，turbo/gptimage 已转付费）；"
                    "请稍后重试，或改用其他通道（管理台/结果页可选）。")
            if model == "flux":                      # 降级 turbo，同 seed 保构图
                data = _fetch(_build_url(prompt, width, height, "turbo", s, enhance), key=key)
            else:
                raise last_err
        paths.append(save_output("free", data, "jpg"))
    return paths

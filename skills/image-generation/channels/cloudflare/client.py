# -*- coding: utf-8 -*-
"""Cloudflare Workers AI 生图客户端：/ai/run/{model}。

已坐实（真机探测，真实 Token 实测通过）：
  - POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell
  - 鉴权 Authorization: Bearer <API Token>（仅需 Workers AI 编辑权限）
  - flux-1-schnell：返回 JSON {"result": {"image": "<b64>"}}，默认 4 步，约 7 秒出图，无水印
  - SDXL 系：返回原始图片二进制（非 JSON），需字节流处理
  - 免费额度：每天 10,000 Neurons 自动重置（flux 1024x1024/4步 ≈ 57.6/张 ≈ 173 张/天）
  - Token 校验：GET /client/v4/user/tokens/verify
  - 仅文生图：Workers AI 图像端点无图生图/编辑能力
尺寸：仅 SDXL 系支持 width/height（建议 ≤1024，8 的倍数）；flux-1-schnell 实测不接受尺寸参数（400），固定 1024x1024；steps 越大越耗 Neurons。
HTTP/落盘等公共机制见 core.httpx / core.media；本文件只保留 Workers AI 策略。
Account ID 为租户标识（非密钥，URL 明文可见），经类常量配置；Token 由编排器统一供给。
"""
import json
import urllib.request

from core import media

DEFAULT_MODEL = "flux-1-schnell"

# 官方模型路由：关键词 -> @cf 模型路径
MODEL_ROUTES = {
    "flux": "@cf/black-forest-labs/flux-1-schnell",
    "sdxl": "@cf/stabilityai/stable-diffusion-xl-baseline",
    "sd15": "@cf/bytedance/stable-diffusion-1.5-naviafair",
}

# ratio -> WxH（flux 支持，8 的倍数，≤1024）
RATIO_SIZES = {
    "1:1": (1024, 1024),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "16:9": (1024, 576),
    "9:16": (576, 1024),
}


class WorkersAIClient:
    BASE = "https://api.cloudflare.com/client/v4"
    # 默认 Account ID（租户标识，非密钥）：仅当粘贴的凭证不含 @account_id 时使用
    ACCOUNT_ID = "828fa594ca4426c554d78aee6bc9bb74"

    def __init__(self, api_key: str = None, timeout: int = None):
        token, account = self.parse_key(api_key)
        if not token:
            raise RuntimeError("缺少 API Token：请先在通道管理台粘贴 Cloudflare Workers AI Token。")
        self.api_key = token
        self.base = "%s/accounts/%s" % (self.BASE, account)
        self.timeout = timeout or 180

    @staticmethod
    def parse_key(key: str) -> tuple:
        """凭证解析（统一入口）：`token@account_id` 复合格式自动拆分——@ 前为 Token、
        @ 后为 Account ID；纯 Token 则用默认 ACCOUNT_ID（向后兼容）。"""
        s = str(key or "").strip()
        if "@" in s:
            token, _, account = s.partition("@")
            token, account = token.strip(), account.strip()
            if token and account:
                return token, account
        return s, WorkersAIClient.ACCOUNT_ID

    # ---- 参数归一 ----
    def _model_path(self, kw: dict) -> str:
        m = str(kw.get("model") or "").strip()
        if m.startswith("@cf/"):
            return m                                  # 已是完整模型路径，透传
        low = (m or DEFAULT_MODEL).lower()
        for k, path in MODEL_ROUTES.items():
            if k in low:
                return path
        # 未知型号不再静默回落 flux（如实告知，通道自治）：
        raise RuntimeError("模型不在本通道清单: %s（可用: %s）"
                           % (m, "、".join(sorted(MODEL_ROUTES.keys()))))

    def _size(self, kw: dict) -> dict:
        """尺寸归一。实测 flux-1-schnell 不接受 width/height（400），仅 SDXL 系支持
        （≤1024、8 的倍数）；flux 固定官方默认 1024x1024。"""
        path = self._model_path(kw)
        if "schnell" in path or "flux" in path:
            return {}
        s = str(kw.get("size") or "").strip()
        if s and "x" in s.lower():
            w, _, h = s.lower().partition("x")
            return {"width": int(w), "height": int(h)}
        if s in RATIO_SIZES:
            w, h = RATIO_SIZES[s]
            return {"width": w, "height": h}
        if kw.get("width") and kw.get("height"):
            return {"width": int(kw["width"]), "height": int(kw["height"])}
        return {}

    @staticmethod
    def _err(status, payload) -> str:
        if isinstance(payload, dict):
            errs = payload.get("errors") or []
            if errs:
                return "HTTP %s: %s" % (status, "; ".join(
                    str(e.get("message")) if isinstance(e, dict) else str(e) for e in errs))
        return "HTTP %s: %s" % (status, str(payload)[:200])

    # ---- 生图 ----
    def generate(self, prompt, **kw):
        """文生图。kw：model/size/width/height/steps。返回本地图片路径列表（统一落盘）。"""
        if not str(prompt or "").strip():
            raise RuntimeError("提示词不能为空")
        if kw.get("image"):
            raise RuntimeError("Workers AI 仅支持文生图，不支持参考图/图生图。")
        body = {"prompt": str(prompt).strip(),
                "steps": max(1, min(int(kw.get("steps") or 4), 8))}
        body.update(self._size(kw))
        url = "%s/ai/run/%s" % (self.base, self._model_path(kw))
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Authorization": "Bearer " + self.api_key,
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode("utf-8", "replace"))
            except Exception:
                payload = {}
            raise RuntimeError(self._err(e.code, payload))
        except Exception as e:
            raise RuntimeError("网络异常: %s" % str(e)[:150])

        if "image" in ctype or ctype.startswith("application/octet-stream"):
            items = [raw]                             # SDXL 系：原始图片字节
        else:                                         # flux：JSON {"result":{"image": b64}}
            try:
                img = (json.loads(raw.decode("utf-8", "replace")).get("result") or {}).get("image")
            except Exception:
                img = None
            if not img:
                raise RuntimeError("响应中未提取到图片：%s" % raw[:200])
            items = ["data:image/png;base64,%s" % img]
        return media.resolve_local(items, "cloudflare")

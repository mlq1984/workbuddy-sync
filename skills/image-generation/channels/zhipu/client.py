# -*- coding: utf-8 -*-
"""智谱 BigModel（CogView）生图客户端：/v4/images/generations。

已坐实（真机探测，真实 Key 实测通过）：
  - Base https://open.bigmodel.cn/api/paas/v4；鉴权 Authorization: Bearer <API Key>
  - POST /v4/images/generations 文生图；响应 OpenAI 风格 data[].url
  - 免费模型 cogview-3-flash（出图右下角带"AI生成"合规标识，服务端固定，无法关闭）
  - cogview-4-250304 为付费模型（首个支持画面汉字渲染），model 参数透传即可切换
  - /v4/models 不列图像模型，图像模型按名直调
  - 仅文生图：CogView 系列无图生图端点，带 image 参数一律拒绝
尺寸档（官方支持分辨率）：1024x1024 / 1152x864 / 864x1152 / 1344x768 / 768x1344
HTTP/提取/落盘等公共机制见 core.httpx / core.media；本文件只保留 CogView 策略。
构造时必须传入 API Key（编排器统一供给）。
"""
from core.httpx import http_json
from core import media

DEFAULT_MODEL = "cogview-3-flash"

# 官方支持分辨率档：ratio -> WxH
RATIO_SIZES = {
    "1:1": "1024x1024",
    "4:3": "1152x864",
    "3:4": "864x1152",
    "16:9": "1344x768",
    "9:16": "768x1344",
}


class CogViewClient:
    BASE = "https://open.bigmodel.cn/api/paas/v4"   # 官方固定端点（OpenAI 兼容）

    def __init__(self, api_key: str = None, timeout: int = None):
        self.base = self.BASE
        self.timeout = timeout or 180
        if not api_key:
            raise RuntimeError("缺少 API Key：请先在通道管理台粘贴官方控制台创建的 Key。")
        self.api_key = api_key

    # ---- 参数归一 ----
    def _size(self, kw: dict) -> str:
        """size 归一：WxH 直传；ratio 映射官方档；width/height 组合；缺省 1024x1024。"""
        s = str(kw.get("size") or "").strip()
        if s:
            if "x" in s.lower():
                return s.lower()                        # WxH 由官方校验
            return RATIO_SIZES.get(s, "1024x1024")      # "1:1" 等 ratio
        w, h = kw.get("width"), kw.get("height")
        if w and h:
            return "%dx%d" % (int(w), int(h))
        return "1024x1024"

    @staticmethod
    def _err(status, payload) -> str:
        if isinstance(payload, dict):
            e = payload.get("error")
            msg = payload.get("message") or (e.get("message") if isinstance(e, dict) else e)
            if msg:
                return "HTTP %s: %s" % (status, msg)
        return "HTTP %s: %s" % (status, str(payload)[:200])

    # ---- 生图 ----
    def generate(self, prompt, **kw):
        """文生图。kw：model/size/width/height。返回本地图片路径列表（统一落盘）。"""
        if not str(prompt or "").strip():
            raise RuntimeError("提示词不能为空")
        if kw.get("image"):
            raise RuntimeError("CogView 系列仅支持文生图，不支持参考图/图生图。")
        body = {
            "model": str(kw.get("model") or DEFAULT_MODEL),
            "prompt": str(prompt).strip(),
            "size": self._size(kw),
        }
        status, payload = http_json("POST", self.base + "/images/generations",
                                    body=body, token=self.api_key, timeout=self.timeout)
        if status != 200:
            raise RuntimeError(self._err(status, payload))
        out = media.extract_images(payload, "zhipu")
        if not out:
            raise RuntimeError("响应中未提取到图片：%s" % str(payload)[:200])
        return media.resolve_local(out, "zhipu")

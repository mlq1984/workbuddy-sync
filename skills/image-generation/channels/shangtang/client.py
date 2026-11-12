# -*- coding: utf-8 -*-
"""商汤日日新（SenseNova）生图客户端：/v1/images/generations + /v1/images/edits。

已坐实（真机探测，真实 Key 实测 3/3 通过）：
  - Base https://token.sensenova.cn/v1；鉴权 Authorization: Bearer <API Key>
  - POST /v1/images/generations 文生图（独立接口，非 Chat Completions，不支持图像输入）
  - POST /v1/images/edits 图生图（≤5 张参考图，第 1 张为主编辑图，image_url 可公网 URL 或 Data URL）
  - 响应 OpenAI 风格：data[].b64_json / data[].url（二选一）；usage.images_count
  - size：auto / WxH（32 的倍数，512~4096，比例 ≤3:1）；官方文档的 "2K"/"4K" 常量
    真机实测被 generate/edits 400 拒绝 → 统一落官方建议 WxH（TIER_SIZES/SIZE_FALLBACK）
  - 官方建议分辨率（真机精确生效）：2K=2048x2048(1:1)/2720x1536(16:9)/1536x2720(9:16)/
    1664x2496(2:3)/2496x1664(3:2)；4K=4096x4096(1:1)；请求非建议组合时上游可能就近微调
    （实测 1280x720→1280x704，不报错）
  - n 仅支持 1；watermark 建议显式传入（false 公测免费）；prompt_extend 默认 true
  - 实测 RPS 限流（HTTP 429 "rps exhausted"）：并发 >1 即触发，请求间隔 ≥10s 串行安全
  - models：sensenova-u1.5-lite（默认，auto 默认输出 2048x1536）/ sensenova-u1.5-fast
    （真机可用，更快，auto 默认 2048x1536，4:3）
HTTP/提取/落盘等公共机制见 core.httpx / core.media；本文件只保留 SenseNova 策略
（端点、默认值、尺寸档位映射）。构造时必须传入 API Key（编排器统一供给）。
"""
import base64
import os

from core.httpx import http_json
from core import media

DEFAULT_MODEL = "sensenova-u1.5-lite"
# 官方文档（技能档案/日日新.md）生图接口仅支持这两个 model_id；精确匹配，未知值回退默认（不臆造路由）
SUPPORTED_MODELS = ("sensenova-u1.5-lite", "sensenova-u1.5-fast")

# 官方建议分辨率档（1K 档）：ratio -> WxH（均为 32 的倍数）
RATIO_SIZES = {
    "1:1": "1024x1024",
    "4:3": "1024x768",
    "3:4": "768x1024",
    "3:2": "1248x832",
    "2:3": "832x1248",
    "16:9": "1280x720",
    "9:16": "720x1280",
    "21:9": "1344x576",
}
SIZE_CONSTANTS = ("2K", "4K")   # 官方分辨率常量（仅部分接口接受，见 SIZE_FALLBACK）
# 坐实（真机 400）：generate/edits 接口拒绝 "2K"/"4K" 常量，仅接受 auto / WIDTHxHEIGHT
# （与 upscale 注释一致）→ 常量统一落为 WxH 兜底；有 ratio 时由 translate 先按比例倍乘。
SIZE_FALLBACK = {"2K": "2048x2048", "4K": "4096x4096"}

# 官方建议分辨率（真机验证 2720x1536/2048x2048/4096x4096 精确生效）：(tier, ratio) -> WxH
TIER_SIZES = {
    ("2K", "1:1"): "2048x2048",
    ("2K", "16:9"): "2720x1536",
    ("2K", "9:16"): "1536x2720",
    ("2K", "2:3"): "1664x2496",
    ("2K", "3:2"): "2496x1664",
    ("4K", "1:1"): "4096x4096",
}

# 放大(增强)：以原图作参考、目标分辨率档位调高的重绘放大（U 系列无独立超分端点）
DEFAULT_UPSCALE_PROMPT = (
    "Upscale and enhance this image: increase resolution and sharpness, "
    "restore fine details, reduce blur and JPEG artifacts, while strictly "
    "preserving the original composition, subjects, style, colors and "
    "overall layout; do not alter the content."
)


class SenseNovaClient:
    BASE = "https://token.sensenova.cn/v1"   # 官方固定端点（OpenAI 风格）

    def __init__(self, api_key: str = None, timeout: int = None):
        self.base = self.BASE
        self.timeout = timeout or 360        # 官方同步接口，2K/4K 出图较慢
        if not api_key:
            raise RuntimeError("缺少 API Key：请先在通道管理台粘贴官网创建的 Key。")
        self.api_key = api_key

    # ---- 参数归一 ----
    def _model(self, kw: dict) -> str:
        m = str(kw.get("model") or "").strip().lower()
        return m if m in SUPPORTED_MODELS else DEFAULT_MODEL

    def _size(self, kw: dict) -> str:
        """size 归一：WxH 直传（校验 32 倍数/范围）；2K/4K 常量落 WxH 兜底；ratio 映射 1K 档；缺省 auto。"""
        s = str(kw.get("size") or "").strip()
        if s:
            up = s.upper()
            if up in SIZE_CONSTANTS:
                w, h = kw.get("width"), kw.get("height")
                if w and h:
                    return self._clamp(int(w), int(h))
                return SIZE_FALLBACK.get(up, up)
            if "x" in s.lower():
                w, _, h = s.lower().partition("x")
                return self._clamp(int(w), int(h))
            return RATIO_SIZES.get(s, "auto")          # "1:1" 等 ratio
        w, h = kw.get("width"), kw.get("height")
        if w and h:
            return self._clamp(int(w), int(h))
        return "auto"

    @staticmethod
    def _clamp(w: int, h: int) -> str:
        mult = lambda v: max(512, min(4096, int(round(v / 32.0)) * 32))
        return "%dx%d" % (mult(w), mult(h))

    @staticmethod
    def _image_refs(image) -> list:
        """image 归一为官方 image_url 列表（edits ≤5 张，第 1 张为主编辑图）：
        公网 URL / Data URL 直传，本地路径转 Data URL；单图入参返回单元素列表。"""
        if isinstance(image, (list, tuple)):
            refs = []
            for x in image:
                if x:
                    refs.extend(SenseNovaClient._image_refs(x))
            if not refs:
                raise RuntimeError("未提供有效参考图")
            return refs
        return [SenseNovaClient._image_refs_one(image)]

    @staticmethod
    def _image_refs_one(image) -> str:
        s = str(image)
        if s.startswith(("http://", "https://", "data:")):
            return s
        if not os.path.isfile(s):
            raise RuntimeError("参考图不存在：%s" % s)
        ext = os.path.splitext(s)[1].lstrip(".").lower() or "png"
        if ext == "jpg":
            ext = "jpeg"
        with open(s, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return "data:image/%s;base64,%s" % (ext, b64)

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
        """文生图 / 图生图。kw：model/image/size/width/height/watermark/output_format/
        prompt_extend/response_format。返回本地图片路径列表（统一落盘）。"""
        if not str(prompt or "").strip():
            raise RuntimeError("提示词不能为空")
        body = {
            "model": self._model(kw),
            "prompt": str(prompt).strip(),
            "n": 1,
            "size": self._size(kw),
            "watermark": bool(kw.get("watermark", False)),
            "output_format": str(kw.get("output_format") or "png"),
            "response_format": str(kw.get("response_format") or "b64_json"),
            "prompt_extend": bool(kw.get("prompt_extend", True)),
        }
        if kw.get("image"):
            body["images"] = [{"image_url": r} for r in self._image_refs(kw["image"])[:5]]
            endpoint = "/images/edits"        # 带参考图 → 同步图片编辑
        else:
            endpoint = "/images/generations"  # 纯文生图
        status, payload = http_json("POST", self.base + endpoint, body=body,
                                    token=self.api_key, timeout=self.timeout)
        if status != 200:
            raise RuntimeError(self._err(status, payload))
        out = media.extract_images(payload, "shangtang")
        if not out:
            raise RuntimeError("响应中未提取到图片：%s" % str(payload)[:200])
        return media.resolve_local(out, "shangtang")

    def upscale(self, image, scale=2, prompt=None, **kw):
        """放大(增强)：以原图作参考、目标分辨率显式算 WxH 后重绘放大。

        实测官方拒绝 "2K" 常量（仅接受 auto / WIDTHxHEIGHT），故由源图尺寸
        ×scale 计算目标 WxH（32 的倍数，512~4096，比例保持、超限整体缩）。
        """
        kw["image"] = image
        if not str(kw.get("size") or "").strip():
            scale = max(1, int(scale or 1))
            dims = media.image_dimensions(image)
            w, h = (dims[0] * scale, dims[1] * scale) if dims else (2048, 2048)
            w, h = float(w), float(h)
            if max(w, h) > 4096:
                f = 4096.0 / max(w, h)
                w, h = w * f, h * f
            kw["size"] = self._clamp(int(round(w)), int(round(h)))
        return self.generate(prompt or DEFAULT_UPSCALE_PROMPT, **kw)

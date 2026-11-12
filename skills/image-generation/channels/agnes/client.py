"""Agnes 生图客户端（OpenAI 兼容）：/v1/images/generations。

已坐实：
  - Base https://api.agnes-ai.cn/v1；鉴权 Authorization: Bearer <API Key>
  - POST /v1/images/generations 与 GET /v1/models 真实存在（假 token 返回 401 无效令牌）
  - 响应按 OpenAI 风格解析：data[].url / data[].b64_json；同时容忍异步任务态（task id）轮询
  - 官方坑位：response_format 必须放 extra_body 内（顶层会 400）；
    图生图输入放 extra_body.image（URL / Data URI，本地图自动转换）；
    图生图不需要 tags:["img2img"]
HTTP/落盘/解析等公共机制见 core.httpx / core.media；本文件只保留 Agnes 策略
（端点、默认值、模型选择、任务轮询节奏）。构造时必须传入 API Key（编排器统一供给）。
"""
import time

import common
from common import load_config, errmsg

from core.httpx import http_json
from core import media

# 放大(增强)：以原图作参考、目标分辨率档位调高的重绘放大（Agnes 无独立超分端点）
AGNES_RATIOS = ["1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"]
DEFAULT_UPSCALE_PROMPT = (
    "Upscale and enhance this image: increase resolution and sharpness, "
    "restore fine details, reduce blur and JPEG artifacts, while strictly "
    "preserving the original composition, subjects, style, colors and "
    "overall layout; do not alter the content."
)


class AgnesImageClient:
    def __init__(self, api_key: str = None, timeout: int = None):
        self.base = load_config().get("common", "base_url",
                                      fallback="https://api.agnes-ai.cn/v1").rstrip("/")
        self.timeout = timeout or load_config().getint("image", "timeout", fallback=360)
        if not api_key:
            raise RuntimeError("缺少 API Key：请先在通道管理中心获取并验证。")
        self.api_key = api_key
        self._models_cache = None

    # ---- 模型 ----
    def list_models(self) -> list:
        if self._models_cache is None:
            status, payload = http_json("GET", f"{self.base}/models",
                                        token=self.api_key, timeout=20, retries=1)
            if status == 200 and isinstance(payload, dict):
                data = payload.get("data") or []
                self._models_cache = [m.get("id") for m in data if isinstance(m, dict)]
            else:
                self._models_cache = []
        return self._models_cache

    def _default_model(self) -> str:
        cfg = load_config()
        m = cfg.get("image", "default_model", fallback="").strip()
        if m:
            return m
        models = self.list_models()
        # /v1/models 无类型字段，靠名称筛选图像模型（优先 2.5，其次 2.1）
        image_models = [x for x in models if "image" in x.lower()]
        for pref in ("2.5", "2.1"):
            hit = [x for x in image_models if pref in x]
            if hit:
                return sorted(hit)[-1]
        if image_models:
            return image_models[0]
        if models:
            raise RuntimeError(f"未找到图像模型，可用模型：{models}；"
                               f"请在 {common.user_config_path()} 指定 [image] default_model")
        raise RuntimeError("无法从 /v1/models 获取模型列表，请检查 Key 或手动指定 model。")

    # ---- 生图（文生图 / 图生图）----
    def generate(self, prompt: str, model: str = None, size: str = None,
                 ratio: str = None, n: int = None, response_format: str = None,
                 image=None, return_base64: bool = None, return_urls: bool = True) -> list:
        """文生图 / 图生图（编辑）。返回图片 URL 列表（return_urls=True）或完整响应 dict（False）。

        参数（对齐 Agnes 官方文档，agnes-image-2.1/2.5-flash）：
          - size：档位 "1K"/"2K"/"3K"/"4K"，或精确尺寸如 "1024x768"（不支持的会被服务端标准化）
          - ratio：与档位式 size 配合 "1:1"/"3:4"/"4:3"/"16:9"/"9:16"/"2:3"/"3:2"/"21:9"（默认 1:1）
          - image：图生图输入。字符串或列表；公网 URL、Data URI、本地文件路径（自动转 Data URI）
          - response_format："url" | "b64_json" —— 官方要求放 extra_body 内（放顶层会 400）
          - return_base64：文生图需 Base64 返回时设 True（官方顶层布尔参数）
        """
        cfg = load_config()
        model = model or self._default_model()
        n = n if n is not None else cfg.getint("image", "n", fallback=1)
        size = size if size is not None else cfg.get("image", "default_size", fallback="").strip()
        response_format = response_format or cfg.get("image", "response_format", fallback="url")

        body = {"model": model, "prompt": prompt, "n": n}
        if size:
            body["size"] = size
        if ratio:
            body["ratio"] = ratio
        if return_base64 is not None:
            body["return_base64"] = bool(return_base64)

        extra = {}
        if response_format:
            extra["response_format"] = response_format
        imgs = media.normalize_images(image)
        if imgs:
            extra["image"] = imgs
        if extra:
            body["extra_body"] = extra

        status, payload = http_json("POST", f"{self.base}/images/generations", body,
                                    token=self.api_key, timeout=self.timeout,
                                    retries=2, backoff=2.0)   # 瞬时失败退避重试
        if status != 200 or not isinstance(payload, dict):
            raise RuntimeError(f"生图失败({status}): {errmsg(payload)}")

        if return_urls:
            return self._extract_urls(payload)
        return payload

    # ---- 放大(增强)：以源图作参考、目标分辨率档位调高后重绘放大 ----
    def upscale(self, image, scale=2, prompt=None, size=None, ratio=None,
                n=None, **kw):
        """放大(增强)：以源图作参考图，目标分辨率档位调高后重绘放大。

        复用 generate（与文生图/图生图同一 OpenAI 兼容流程），返回本地图片路径列表。
        scale 默认 2 → 2K，≥4 → 4K（可经 size 覆盖）；ratio 取源图宽高比最近候选。
        """
        if image is None:
            raise RuntimeError("upscale 需要源图 image（路径/URL/Data URI）")
        dims = media.image_dimensions(image)
        if ratio is None:
            ratio = (media.nearest_ratio(dims[0], dims[1], AGNES_RATIOS)
                     if dims else "1:1")
        if size is None:
            size = "4K" if scale >= 4 else ("2K" if scale >= 2 else "1K")
        return self.generate(prompt=prompt or DEFAULT_UPSCALE_PROMPT,
                             model=kw.get("model"), image=image,
                             size=size, ratio=ratio, n=n)

    # ---- 响应解析（先试同步形态，再容忍异步任务态）----
    def _extract_urls(self, payload: dict) -> list:
        out = media.extract_images(payload, "agnes")
        if out:
            # 统一落盘为本地图片路径，便于调用方（如 WorkBuddy）直接预览
            return media.resolve_local(out, "agnes")
        # 异步任务态：出现任务 id，轮询直到出图
        data = payload.get("data") if isinstance(payload.get("data"), dict) else None
        task_id = payload.get("id") or payload.get("task_id") or (data or {}).get("id")
        if task_id:
            return self._poll_task(task_id)
        raise RuntimeError(f"无法从生图响应中解析图片：{payload}")

    def _poll_task(self, task_id, interval: int = 5, deadline: int = None) -> list:
        url = f"{self.base}/v1/tasks/{task_id}"
        end = time.time() + (deadline or self.timeout)
        while time.time() < end:
            status, payload = http_json("GET", url, token=self.api_key, timeout=20)
            if status == 200 and isinstance(payload, dict):
                data = payload.get("data") or payload
                if isinstance(data, list) and data:
                    return media.resolve_local(media.extract_images({"data": data}, "agnes"), "agnes")
                if isinstance(data, dict) and (data.get("url") or data.get("b64_json")
                                               or data.get("image_url")):
                    return media.resolve_local(media.extract_images({"data": [data]}, "agnes"), "agnes")
                if payload.get("status") in ("failed", "error"):
                    raise RuntimeError(f"生图任务失败：{payload}")
            time.sleep(interval)
        raise RuntimeError("生图任务轮询超时")

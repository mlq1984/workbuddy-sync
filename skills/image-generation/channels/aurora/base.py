# -*- coding: utf-8 -*-
"""aurora 通道客户端底座（rightapi 中转，API: api.site，OpenAI 兼容 + Gemini 形态）。

HTTP 执行/重试/解析等公共机制见 core.httpx / core.media；本文件只保留 aurora 通道策略：
端点与路径、任务轮询节奏（/v1/tasks）、Connection: close 短连接（防 SSL 重置）、
参考图读取（路径/bytes/base64）。
"""
import json
import time
import base64
import os
import configparser

from core.httpx import http_json
from core import media


class BaseClient:
    BASE = "https://api.site"   # API 接口（2026-10-30 官方迁移后的现行地址；主站/登录为 rightapi.io）
    # 技能不内置任何密钥：无可用凭证时必须由用户在凭证页录入
    DEFAULT_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
    _CONFIG_SECTION = None

    # 放大(增强)：以原图作参考、目标分辨率调高的重绘放大（上游无独立超分端点）
    AURORA_RATIOS = ["1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"]
    DEFAULT_UPSCALE_PROMPT = (
        "Upscale and enhance this image: increase resolution and sharpness, "
        "restore fine details, reduce blur and JPEG artifacts, while strictly "
        "preserving the original composition, subjects, style, colors and "
        "overall layout; do not alter the content."
    )

    def __init__(self, api_key=None, user_agent=None, poll_interval=None,
                 timeout=None):
        # 加载 config.ini（通道目录 channels/aurora/），缺失则回退内置默认值
        cfg = self._load_config(getattr(self, "_CONFIG_SECTION", None))
        self.config = cfg

        self.api_key = api_key or cfg.get("api_key") or None
        self.ua = user_agent or cfg.get("user_agent") or self.DEFAULT_UA
        self.base_url = cfg.get("base_url") or self.BASE

        try:
            pi = int(cfg.get("poll_interval", ""))
        except (ValueError, TypeError):
            pi = None
        self.poll_interval = poll_interval or pi or 5

        try:
            to = int(cfg.get("timeout", ""))
        except (ValueError, TypeError):
            to = None
        self.timeout = timeout or to or 360

    @staticmethod
    def _find_config():
        """定位通道自己的 config.ini（channels/aurora/config.ini）。

        此前上溯两级指向 channels/config.ini（该文件不存在），配置永远不生效、
        全部回退代码内置默认；改为同目录定位后，各配置项与内置默认逐项一致
        （base_url/UA/poll/timeout/模型/档位/比例），行为零变化，同时恢复
        "改 config.ini 即可调参" 的能力。"""
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
        return p if os.path.isfile(p) else None

    def _load_config(self, section):
        path = self._find_config()
        if not path:
            return {}
        try:
            cp = configparser.ConfigParser(interpolation=None)
            cp.read(path, encoding="utf-8")
            cfg = {}
            if cp.has_section("common"):
                cfg.update(dict(cp.items("common")))
            if section and cp.has_section(section):
                cfg.update(dict(cp.items(section)))
            return cfg
        except Exception:
            return {}

    def _post(self, path, payload, retries=2):
        url = self.base_url + path
        return http_json("POST", url, body=payload, token=self.api_key,
                         user_agent=self.ua, extra_headers={"Connection": "close"},
                         timeout=90, retries=retries, backoff=2.0)

    def _get_task(self, task_id, retries=3):
        url = self.base_url + "/v1/tasks/" + task_id
        return http_json("GET", url, token=self.api_key, user_agent=self.ua,
                         extra_headers={"Connection": "close"}, timeout=60,
                         retries=retries, backoff=2.0)

    def _wait(self, task_id):
        """轮询任务直至完成（响应出现 data/candidates）或失败/超时。返回最终响应 dict。"""
        start = time.time()
        last = None
        while time.time() - start < self.timeout:
            st, resp = self._get_task(task_id)
            if st is None:
                time.sleep(self.poll_interval)
                continue
            if st != 200:
                raise RuntimeError("任务查询失败 HTTP %s: %s" % (st, resp))
            last = resp
            if not isinstance(resp, dict):
                time.sleep(self.poll_interval)
                continue
            if resp.get("status") == "failed":
                err = resp.get("error", {})
                raise RuntimeError("生图失败: %s" % err.get("message", resp))
            if resp.get("data") or resp.get("candidates"):
                return resp
            time.sleep(self.poll_interval)
        return last or {"status": "timeout"}

    def _generate_openai(self, prompt, model, size, image_size, n, image, return_urls, aspect_ratio=None):
        """OpenAI 兼容流程（gpt-image 与 nano-banana 共用）：提交 → 轮询 → 提取 URL。"""
        payload = {
            "model": model,
            "prompt": prompt,
            "async": True,
            "n": n,
            "size": size,
        }
        if image_size:
            payload["image_size"] = image_size    # 字段名全小写：2026-10-26 新网关拒绝驼峰字段（实测 400）
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if image is not None:
            imgs = image if isinstance(image, (list, tuple)) else [image]
            payload["image"] = [self._read_image(x) for x in imgs]
        st, resp = self._post("/draw/v1/images/generations", payload)
        if st != 200 or not resp.get("task_id"):
            raise RuntimeError("提交失败 HTTP %s: %s" % (st, resp))
        final = self._wait(resp["task_id"])
        urls = self._extract(final)
        if not urls:
            raise RuntimeError("未拿到图片，最终响应: %s" % json.dumps(final, ensure_ascii=False)[:300])
        if not return_urls:
            return final
        # 统一落盘为本地图片路径，便于调用方（如 WorkBuddy）直接预览
        return media.resolve_local(urls, "aurora")

    def upscale(self, image, scale=2, prompt=None, image_size=None, size=None,
                n=1, aspect_ratio=None, **kw):
        """放大(增强)：以源图作参考图，目标分辨率调高后重绘放大。

        复用 _generate_openai（与文生图/图生图同一 OpenAI 兼容流程），
        返回本地图片路径列表。scale 默认 2 → 2K，≥4 → 4K（可经 image_size 覆盖）；
        size 取源图宽高比最近候选（可经 size 覆盖）。
        """
        if image is None:
            raise RuntimeError("upscale 需要源图 image（路径/URL/Data URI）")
        dims = media.image_dimensions(image)
        if size is None:
            size = (media.nearest_ratio(dims[0], dims[1], self.AURORA_RATIOS)
                    if dims else "1:1")
        if image_size is None:
            image_size = "4K" if scale >= 4 else ("2K" if scale >= 2 else "1K")
        model = kw.pop("model", None) or self.default_model
        return self._generate_openai(
            prompt or self.DEFAULT_UPSCALE_PROMPT,
            model=model, size=size, image_size=image_size,
            n=n, image=image, return_urls=True, aspect_ratio=aspect_ratio)

    @staticmethod
    def _extract(resp):
        return media.extract_images(resp, "aurora")

    @staticmethod
    def _read_image(value):
        """参考图归一化：路径/bytes/URL/Data URI → 完整 Data URI。

        文件与 URL/Data URI 走公共层 core.media（避免各通道重复实现）；
        bytes 按 PNG 直接编码（API 要求 data:image/png;base64, 形态）。
        """
        if value is None:
            return None
        if isinstance(value, bytes):
            return "data:image/png;base64," + base64.b64encode(value).decode("ascii")
        return media.to_data_uri(value)

    # 探活用假任务号：走「任务详情」路由（真实轮询同一路由，平台已支持并计费）。
    # 不用 GET /v1/tasks（列表）：rightapi 对该接口在鉴权之后做路由级关闭——
    # 有效 Key 反而收到 403「暂不支持该接口，平台无法对其计费」（与 Key 无关），
    # 曾致一切 aurora Key 被 validate_key 误判无效（2026-10-26 假 Key 实测：两路由无效 Key 均返回 401）。
    PROBE_TASK_ID = "aipro-key-probe"
    # 平台级路由限制特征（发生在鉴权之后、与 Key 是否有效无关）：
    # 403 且响应命中这些字样 → 视为「无法验证」放行，交由实际生图暴露，避免再误拦截。
    ROUTE_BLOCKED_MARKERS = ("暂不支持", "不支持该接口", "无法对其计费")

    def validate_key(self, api_key=None):
        """探测 Key 是否被服务端接受（零成本：仅一次 GET，不触发真实生图）。返回 bool。

        探针 = GET /v1/tasks/{PROBE_TASK_ID}（假任务号，走任务详情路由）：
        服务端先鉴权后路由——Key 无效 → 401/403；Key 有效但任务不存在 → 404。
        故仅 401/403 判定无效；403 若命中平台路由限制特征（与 Key 无关）或网络不可达，
        返回 True 放行，交由实际生成暴露错误，避免误拦截（平台限制 ≠ Key 无效）。
        """
        probe = self if api_key is None else BaseClient(api_key=api_key)
        st, resp = probe._get_task(self.PROBE_TASK_ID, retries=1)
        if st is None:
            return True
        if st == 403 and resp is not None:
            text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)
            if any(m in text for m in self.ROUTE_BLOCKED_MARKERS):
                return True
        return st not in (401, 403)

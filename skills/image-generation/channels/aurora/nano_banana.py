# -*- coding: utf-8 -*-
"""nano-banana 系列客户端（OpenAI 兼容接口，与 gpt-image 共用 base 流程）。"""
from base import BaseClient


class NanoBananaClient(BaseClient):
    _CONFIG_SECTION = "nano_banana"
    DEFAULT_MODEL = "nano-banana-2"
    DEFAULT_SIZE = "1:1"
    DEFAULT_ASPECT_RATIO = None
    DEFAULT_N = 1

    def __init__(self, api_key=None, user_agent=None, poll_interval=None, timeout=None):
        super().__init__(api_key=api_key, user_agent=user_agent,
                         poll_interval=poll_interval, timeout=timeout)
        self.default_model = self.config.get("default_model") or self.DEFAULT_MODEL
        self.default_size = self.config.get("default_size") or self.DEFAULT_SIZE
        vis = (self.config.get("default_image_size") or "").strip()
        self.default_image_size = vis or None
        ar = (self.config.get("default_aspect_ratio") or "").strip()
        self.default_aspect_ratio = ar or None
        try:
            raw = (self.config.get("n") or "").strip()
            self.default_n = int(raw) if raw else self.DEFAULT_N
        except ValueError:
            self.default_n = self.DEFAULT_N

    def generate(self, prompt, model=None, size=None, image_size=None, n=None,
                 image=None, return_urls=True, aspect_ratio=None):
        """OpenAI 兼容文生图 / 图生图（编辑）。返回图片 URL 列表或完整响应 dict。"""
        return self._generate_openai(
            prompt,
            model or self.default_model,
            size or self.default_size,
            image_size if image_size is not None else self.default_image_size,
            n if n is not None else self.default_n,
            image, return_urls,
            aspect_ratio if aspect_ratio is not None else self.default_aspect_ratio)



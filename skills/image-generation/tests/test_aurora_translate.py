# -*- coding: utf-8 -*-
"""aurora translate 单元测试（纯映射，零 IO / 零触网）。

回归背景：upscale 分支此前只透传 image/scale/prompt——模型/档位/比例被丢弃，
经标准 params 流程放大时选 nano 无效、档位退回 scale 推导、比例退回源图，
与 channels/aurora/api.md「model 与 generate 一致 / 可经 image_size 指定」不符。
"""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "channels", "aurora"))

import app as aurora_app  # noqa: E402


class TestAuroraTranslateUpscale(unittest.TestCase):
    def test_upscale_forwards_model_tier_ratio(self):
        """模型/档位/比例照常透传（与 generate 同构）。"""
        kw = aurora_app.translate({
            "action": "upscale", "image": "a.png", "scale": 4,
            "model": "nano-banana-2", "tier": "4K", "ratio": "16:9"})
        self.assertEqual(kw["image"], "a.png")
        self.assertEqual(kw["scale"], 4)
        self.assertEqual(kw["model"], "nano-banana-2")
        self.assertEqual(kw["image_size"], "4K")
        self.assertEqual(kw["size"], "16:9")

    def test_upscale_minimal_unchanged(self):
        """最小 spec：只传 image/scale，不凭空造参。"""
        kw = aurora_app.translate({"action": "upscale", "image": "a.png", "scale": 2})
        self.assertEqual(kw, {"image": "a.png", "scale": 2})

    def test_upscale_prompt_kept(self):
        kw = aurora_app.translate({
            "action": "upscale", "image": "a.png", "scale": 2,
            "upscale_prompt": "增强细节"})
        self.assertEqual(kw["prompt"], "增强细节")


class TestAuroraTranslateGenerate(unittest.TestCase):
    def test_generate_full_mapping(self):
        """文生图/图生图全参数映射（image/model/aspect_ratio/size/image_size）。"""
        kw = aurora_app.translate({
            "action": "generate", "prompt": "换背景", "image": "a.png",
            "model": "nano-banana-2", "options": {"aspect_ratio": "9:16"},
            "ratio": "9:16", "tier": "2K"})
        self.assertEqual(kw["prompt"], "换背景")
        self.assertEqual(kw["image"], "a.png")
        self.assertEqual(kw["model"], "nano-banana-2")
        self.assertEqual(kw["aspect_ratio"], "9:16")
        self.assertEqual(kw["size"], "9:16")
        self.assertEqual(kw["image_size"], "2K")


if __name__ == "__main__":
    unittest.main()

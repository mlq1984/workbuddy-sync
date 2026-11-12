# -*- coding: utf-8 -*-
"""回归测试：params 守门开关默认关闭时行为与既有完全一致；开启时守门生效。

运行（技能根目录）：python -m unittest discover -s tests
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import params  # noqa: E402


def _spec(prompt):
    return {"action": "generate", "channels": ["aurora"], "prompt": prompt}


class TestGuardOffDefault(unittest.TestCase):
    def test_prompt_passthrough_unchanged(self):
        """开关默认关闭：prompt 原样通过（含重复词，不做任何清洗）——行为与既有一致。"""
        p = "高质量，高品质，一只橘猫"
        clean, err = params.validate(_spec(p))
        self.assertIsNone(err)
        self.assertEqual(clean["prompt"], p)

    def test_unknown_field_still_rejected(self):
        clean, err = params.validate({"channels": ["aurora"], "prompt": "x", "foo": 1})
        self.assertIsNone(clean)
        self.assertIn("未知字段", err)

    def test_channels_validation_unchanged(self):
        clean, err = params.validate({"prompt": "x"})
        self.assertIsNone(clean)
        self.assertIn("channels", err)

    def test_empty_prompt_rejected(self):
        clean, err = params.validate(_spec("  "))
        self.assertIsNone(clean)
        self.assertIn("prompt", err)


class TestGuardOn(unittest.TestCase):
    def setUp(self):
        os.environ["AIPO_PROMPT_GUARD"] = "1"

    def tearDown(self):
        os.environ.pop("AIPO_PROMPT_GUARD", None)

    def test_dedup_applied(self):
        clean, err = params.validate(_spec("高质量，高品质，hd，一只橘猫"))
        self.assertIsNone(err)
        self.assertEqual(clean["prompt"], "高质量，一只橘猫")

    def test_overlong_clipped(self):
        p = "，".join(["一只橘猫在窗台晒太阳"] * 40)
        clean, err = params.validate(_spec(p))
        self.assertIsNone(err)
        self.assertLessEqual(len(clean["prompt"]), 200)

    def test_normal_prompt_untouched(self):
        p = "一只橘色虎斑猫，水彩风格，柔和自然光，中景构图"
        clean, err = params.validate(_spec(p))
        self.assertIsNone(err)
        self.assertEqual(clean["prompt"], p)


class TestMultiRefImage(unittest.TestCase):
    """多参考图（image: str|list[str]）与协商截断。"""

    def test_single_image_keeps_str(self):
        clean, err = params.validate({"action": "generate", "channels": ["aurora"],
                                      "prompt": "x", "image": "a.png"})
        self.assertIsNone(err)
        self.assertEqual(clean["image"], "a.png")          # 单图保持 str（兼容旧执行层）

    def test_multi_image_normalized_to_list(self):
        clean, err = params.validate({"action": "generate", "channels": ["aurora"],
                                      "prompt": "x", "image": [" a.png ", "b.png"]})
        self.assertIsNone(err)
        self.assertEqual(clean["image"], ["a.png", "b.png"])  # 去空格归一为 list

    def test_over_limit_hard_clamped(self):
        clean, err = params.validate({"action": "generate", "channels": ["aurora"],
                                      "prompt": "x", "image": ["a"] * 15})
        self.assertIsNone(err)
        self.assertEqual(len(clean["image"]), 14)          # 防滥用硬限 ≤14（官方参考图上限族）

    def test_bad_image_rejected(self):
        for bad in ("", [], ["a", ""], [1, 2], 123):
            clean, err = params.validate({"action": "generate", "channels": ["aurora"],
                                          "prompt": "x", "image": bad})
            self.assertIsNotNone(err, "应拒绝: %r" % (bad,))

    def test_negotiate_truncates_by_caps(self):
        clean = {"action": "generate", "channels": ["x"], "prompt": "p",
                 "image": ["a", "b", "c"]}
        caps = {"image_refs": 2, "tiers": [], "ratios": [], "n": False,
                "i2i": True, "t2i": True, "upscale": False, "concurrency": 1}
        spec = params._negotiate("x", clean, caps)
        self.assertEqual(spec["image"], ["a", "b"])        # 超上限截断，主图保留

    def test_negotiate_single_image_untouched(self):
        clean = {"action": "generate", "channels": ["x"], "prompt": "p", "image": "a.png"}
        caps = {"image_refs": 5, "tiers": [], "ratios": [], "n": False,
                "i2i": True, "t2i": True, "upscale": False, "concurrency": 1}
        spec = params._negotiate("x", clean, caps)
        self.assertEqual(spec["image"], "a.png")           # 单图 str 不受协商影响


class TestOptionsField(unittest.TestCase):
    """options（通道专属参数透传）。"""

    def test_scalar_options_accepted(self):
        clean, err = params.validate({"action": "generate", "channels": ["shangtang"],
                                      "prompt": "x",
                                      "options": {"watermark": False, "steps": 4}})
        self.assertIsNone(err)
        self.assertEqual(clean["options"], {"watermark": False, "steps": 4})

    def test_empty_options_dropped(self):
        clean, err = params.validate({"action": "generate", "channels": ["shangtang"],
                                      "prompt": "x", "options": {}})
        self.assertIsNone(err)
        self.assertNotIn("options", clean)                 # 宁缺勿滥：空对象不进 spec

    def test_nonscalar_options_rejected(self):
        clean, err = params.validate({"action": "generate", "channels": ["shangtang"],
                                      "prompt": "x", "options": {"a": [1, 2]}})
        self.assertIsNone(clean)
        self.assertIn("options", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)

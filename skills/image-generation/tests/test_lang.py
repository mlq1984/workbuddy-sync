# -*- coding: utf-8 -*-
"""core/lang 单元测试（纯标准库 unittest）：语种识别 + 每通道策略 + 硬规则。

运行（技能根目录）：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import lang  # noqa: E402


class TestDetectLanguage(unittest.TestCase):
    def test_zh(self):
        self.assertEqual(lang.detect_language("一只戴头盔的橘猫，水彩风格"), "zh")

    def test_en(self):
        self.assertEqual(lang.detect_language("a cat wearing a helmet, watercolor"), "en")

    def test_empty_defaults_zh(self):
        self.assertEqual(lang.detect_language(""), "zh")
        self.assertEqual(lang.detect_language("   "), "zh")

    def test_mixed_favors_en(self):
        # 英文为主、夹少量中文词 → en（应转英文，无需特殊处理）
        self.assertEqual(lang.detect_language("an orange cat 在 cafe, cinematic"), "en")

    def test_mixed_favors_zh(self):
        # 中文为主、夹英文术语 → zh
        self.assertEqual(lang.detect_language("电影感宽幅构图，一只橘猫，8K"), "zh")


class TestTargetLang(unittest.TestCase):
    def test_flux_channels_force_en(self):
        self.assertEqual(lang.target_lang("cloudflare", "zh"), "en")
        self.assertEqual(lang.target_lang("free", "zh"), "en")
        self.assertEqual(lang.target_lang("cloudflare", "en"), "en")  # 已是英文，不变

    def test_zhipu_shangtang_force_zh(self):
        self.assertEqual(lang.target_lang("zhipu", "en"), "zh")
        self.assertEqual(lang.target_lang("shangtang", "zh"), "zh")

    def test_aurora_agnes_keep_input(self):
        self.assertEqual(lang.target_lang("aurora", "en"), "en")
        self.assertEqual(lang.target_lang("agnes", "zh"), "zh")
        self.assertEqual(lang.target_lang("auto", "en"), "en")

    def test_unknown_channel_keeps_input(self):
        self.assertEqual(lang.target_lang("weird", "zh"), "zh")

    def test_hard_rule_cn_text_wins(self):
        # 图上要中文文字 → 即便 Flux 也保持中文
        self.assertEqual(lang.target_lang("cloudflare", "en", has_cn_text=True), "zh")
        self.assertEqual(lang.target_lang("free", "zh", has_cn_text=True), "zh")

    def test_hard_rule_mode_c_wins(self):
        # C 模式连语言都不动
        self.assertEqual(lang.target_lang("cloudflare", "zh", mode="C"), "zh")
        self.assertEqual(lang.target_lang("zhipu", "en", mode="C"), "en")


class TestNeedsConversion(unittest.TestCase):
    def test_flux_zh_needs_en(self):
        self.assertTrue(lang.needs_conversion("cloudflare", "一只橘猫"))

    def test_flux_en_noop(self):
        self.assertFalse(lang.needs_conversion("free", "an orange cat"))

    def test_zhipu_en_needs_zh(self):
        self.assertTrue(lang.needs_conversion("zhipu", "an orange cat"))

    def test_c_mode_no_conversion(self):
        self.assertFalse(lang.needs_conversion("cloudflare", "一只橘猫", mode="C"))

    def test_cn_text_no_conversion_on_flux(self):
        self.assertFalse(lang.needs_conversion("cloudflare", "一只橘猫", has_cn_text=True))


class TestCli(unittest.TestCase):
    def _run(self, *args):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = lang.main(list(args))
        return rc, json.loads(buf.getvalue())

    def test_cli_flux_zh(self):
        rc, out = self._run("--cid", "cloudflare", "--prompt", "一只戴头盔的橘猫")
        self.assertEqual(rc, 0)
        self.assertEqual(out["detected"], "zh")
        self.assertEqual(out["target"], "en")
        self.assertTrue(out["needs_conversion"])
        self.assertTrue(out["flux_warning"])

    def test_cli_cn_text_overrides_flux(self):
        rc, out = self._run("--cid", "cloudflare", "--prompt", "新春快乐", "--cn-text")
        self.assertEqual(out["target"], "zh")
        self.assertFalse(out["needs_conversion"])
        self.assertFalse(out["flux_warning"])


if __name__ == "__main__":
    unittest.main()

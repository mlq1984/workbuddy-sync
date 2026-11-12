# -*- coding: utf-8 -*-
"""prompt_opt 单元测试（纯标准库 unittest）。

运行（技能根目录）：
  python -m unittest discover -s tests -v
或直接： python tests/test_prompt_opt.py
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import prompt_opt as po  # noqa: E402


class TestDetectLanguage(unittest.TestCase):
    def test_zh(self):
        self.assertEqual(po.detect_language("一只戴头盔的橘猫，水彩风格"), "zh")

    def test_en(self):
        self.assertEqual(po.detect_language("a cat wearing a helmet, watercolor style"), "en")

    def test_empty_defaults_zh(self):
        self.assertEqual(po.detect_language(""), "zh")


class TestDetectMode(unittest.TestCase):
    def test_A_vague(self):
        self.assertEqual(po.detect_mode("画只猫"), "A")
        self.assertEqual(po.detect_mode("做个好看的海报"), "A")

    def test_B_partial(self):
        self.assertEqual(po.detect_mode("水彩风，16:9，一只戴头盔的橘猫"), "B")

    def test_C_full(self):
        p = ("一只戴头盔的橘色虎斑猫骑机车驰骋在滨海公路，黄昏逆光，"
             "电影感宽幅构图，胶片颗粒质感，写实摄影风格，浅景深，毛发随风飘动")
        self.assertEqual(po.detect_mode(p), "C")


class TestPassthrough(unittest.TestCase):
    def test_identity(self):
        p = "一只戴头盔的橘色虎斑猫骑机车驰骋在滨海公路，黄昏逆光，电影感宽幅构图，胶片颗粒质感"
        out, issues = po.passthrough(p)
        self.assertEqual(out, p)
        self.assertEqual(issues, [])

    def test_overlong_clipped(self):
        p = "，".join(["一只橘猫在窗台晒太阳"] * 30)  # > 200 字
        out, issues = po.passthrough(p)
        self.assertLessEqual(len(out), po.ZH_LIMIT)
        self.assertIn("超长已精简", issues)


class TestEnrichKeep(unittest.TestCase):
    def test_keep_preserved_verbatim(self):
        keep = "水彩风，16:9，一只戴头盔的橘猫"
        agent_added = keep + "，骑行赛道场景，柔和自然光，中景构图，纸张纹理与颜料晕染质感"
        out, _ = po.enrich(agent_added, keep=keep)
        for seg in ("水彩风", "16:9", "一只戴头盔的橘猫"):
            self.assertIn(seg, out)

    def test_only_adds_never_removes_user_parts(self):
        keep = "水彩风格，一只橘猫"
        out, _ = po.enrich(keep + "，柔和自然光", keep=keep)
        self.assertIn("水彩风格", out)
        self.assertIn("一只橘猫", out)

    def test_deai_injected_for_realistic(self):
        out, _ = po.enrich("写实摄影风格，一只橘猫", keep="写实摄影风格，一只橘猫")
        self.assertIn("自然光线", out)
        self.assertIn("真实质感", out)

    def test_quality_word_appended(self):
        out, _ = po.enrich("一只橘猫在花园里", keep="一只橘猫在花园里")
        self.assertIn("高质量", out)


class TestValidate(unittest.TestCase):
    def test_synonym_dedup(self):
        out, issues = po.validate("高质量，高品质，hd，一只橘猫")
        self.assertEqual(out, "高质量，一只橘猫")
        self.assertEqual(len([i for i in issues if i.startswith("去重")]), 2)

    def test_conflict_removed(self):
        out, issues = po.validate("夜晚的街道，烈日当空，一只橘猫")
        self.assertNotIn("烈日当空", out)
        self.assertTrue(any("矛盾剔除" in i for i in issues))

    def test_conflict_keep_side_wins(self):
        out, _ = po.validate("夜晚的街道，烈日当空", keep="夜晚的街道")
        self.assertIn("夜晚", out)
        self.assertNotIn("烈日", out)

    def test_keep_style_conflict_removed(self):
        out, issues = po.validate("水彩风格，一只橘猫，油画笔触浓重", keep="水彩风格，一只橘猫")
        self.assertIn("水彩风格", out)
        self.assertNotIn("油画笔触浓重", out)
        self.assertTrue(any("与用户参数冲突剔除" in i for i in issues))

    def test_dimension_coverage_warning(self):
        _, issues = po.validate("一只橘猫")
        self.assertTrue(any("缺维度提醒" in i for i in issues))

    def test_no_false_conflict(self):
        out, issues = po.validate("黄昏逆光下的橘猫，电影感构图，胶片质感")
        self.assertTrue(all("矛盾剔除" not in i for i in issues))
        self.assertIn("黄昏逆光下的橘猫", out)


class TestComposeA(unittest.TestCase):
    def test_all_dims_covered(self):
        out = po.compose_from_scratch("一只橘色虎斑小猫")
        self.assertEqual(po._missing_dims(out), [])
        self.assertIn("一只橘色虎斑小猫", out)

    def test_style_override(self):
        out = po.compose_from_scratch("一只橘猫", style="水彩插画风格")
        self.assertIn("水彩插画风格", out)


class TestCnText(unittest.TestCase):
    def test_text_verbatim_and_constraints(self):
        out = po.inject_cn_text("中秋主题海报背景", "中秋团圆")
        self.assertIn("中秋团圆", out)
        self.assertIn("文字清晰锐利", out)
        self.assertIn("无重影无重叠", out)

    def test_no_duplicate_injection(self):
        once = po.inject_cn_text("海报", "中秋团圆")
        twice = po.inject_cn_text(once, "中秋团圆")
        self.assertEqual(once, twice)


class TestNegative(unittest.TestCase):
    def test_default_terms(self):
        neg = po.negative_default()
        for w in ("畸形", "多余肢体", "文字乱码", "水印"):
            self.assertIn(w, neg)


class TestOptimizeOrchestration(unittest.TestCase):
    def test_C_passthrough_end_to_end(self):
        p = ("一只戴头盔的橘色虎斑猫骑机车驰骋在滨海公路，黄昏逆光，"
             "电影感宽幅构图，胶片颗粒质感，写实摄影风格，浅景深，毛发随风飘动")
        r = po.optimize(p)
        self.assertEqual(r["mode"], "C")
        self.assertEqual(r["prompt"], p)
        self.assertEqual(r["negative"], "")

    def test_A_structured(self):
        r = po.optimize("画只猫")
        self.assertEqual(r["mode"], "A")
        self.assertEqual(po._missing_dims(r["prompt"]), [])
        self.assertTrue(r["negative"])

    def test_B_keeps_user(self):
        r = po.optimize("水彩风，16:9，一只戴头盔的橘猫，骑行赛道场景，柔和自然光",
                        mode="B", keep="水彩风，16:9，一只戴头盔的橘猫")
        self.assertEqual(r["mode"], "B")
        for seg in ("水彩风", "16:9", "一只戴头盔的橘猫"):
            self.assertIn(seg, r["prompt"])

    def test_cn_text_flow(self):
        r = po.optimize("中秋主题海报，国风插画风格，圆月与祥云背景",
                        mode="B", keep="中秋主题海报，国风插画风格", cn_text="中秋团圆")
        self.assertIn("中秋团圆", r["prompt"])
        self.assertIn("文字清晰锐利", r["prompt"])

    def test_mode_override(self):
        r = po.optimize("画只猫", mode="C")
        self.assertEqual(r["prompt"], "画只猫")

    def test_explicit_lang(self):
        r = po.optimize("a cat in the garden", mode="A", lang="en")
        self.assertEqual(r["lang"], "en")


class TestPurity(unittest.TestCase):
    def test_no_io_no_network(self):
        path = os.path.join(os.path.dirname(po.__file__), "prompt_opt.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        for banned in ("import requests", "import urllib", "import socket",
                       "open(", "input(", "os.remove", "shutil"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main(verbosity=2)

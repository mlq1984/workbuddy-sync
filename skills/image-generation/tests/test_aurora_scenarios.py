# -*- coding: utf-8 -*-
"""aurora 全场景一致性测试（mock 网络：零触网、零真生图）。

以 channels/aurora/api.md（【通道1参考】）为基准，验证 Agent 侧参数链
validate → plan → negotiate → translate → 路由/payload 在
open（gpt-image 系）与 gemini（nano-banana 系）两系列、
文生图 / 图生图 / 放大 各场景下的行为与参考一致。
"""
import os
import sys
import unittest
from unittest import mock
from contextlib import contextmanager

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "channels", "aurora"))

from core import params  # noqa: E402  (导入即加载注册表，aurora 为内置通道)
import app as aurora_app  # noqa: E402
import base as aurora_base  # noqa: E402

URIS = ["data:image/png;base64,aa", "data:image/png;base64,bb",
        "data:image/png;base64,cc"]


@contextmanager
def _deterministic():
    """凭证/状态/开关与运行时机器状态解耦，保证测试可重现。"""
    with mock.patch.object(params, "credential_label", return_value="用户Key"), \
         mock.patch.object(params, "view_status", return_value={"state": "valid"}), \
         mock.patch.object(params.switches, "is_enabled", return_value=True):
        yield


class _CaptureHTTP:
    """捕获提交 payload；POST 返回 task_id，GET 任务返回含图响应。"""

    def __init__(self):
        self.payloads = []

    def __call__(self, method, url, **kw):
        if method == "POST":
            self.payloads.append(kw.get("body"))
            return 200, {"task_id": "t1"}
        return 200, {"data": [{"b64_json": "aGk="}]}


def _clean(spec):
    clean, err = params.validate(spec)
    assert err is None, err
    return clean


def _run_generate(spec):
    """spec → validate → translate → app.generate（真实客户端 + 捕获 HTTP）。

    返回 (使用的客户端系列列表, 最后一次提交的 payload)。
    """
    clean = _clean(spec)
    with _deterministic():
        kw = params.translate("aurora", clean)
    created, http = [], _CaptureHTTP()

    class SpyGPT(aurora_app.GPTImageClient):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            created.append("gpt")

    class SpyNano(aurora_app.NanoBananaClient):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            created.append("nano")

    with mock.patch.object(aurora_app, "GPTImageClient", SpyGPT), \
         mock.patch.object(aurora_app, "NanoBananaClient", SpyNano), \
         mock.patch.object(aurora_app, "get_key", return_value="k"), \
         mock.patch.object(aurora_base, "http_json", http), \
         mock.patch.object(aurora_base.media, "resolve_local", return_value=["p.png"]):
        aurora_app.generate(**kw)
    return created, (http.payloads[-1] if http.payloads else None)


class TestValidate(unittest.TestCase):
    """spec 合法性（core.params.validate，通道无关层）。"""

    def test_t2i_minimal_ok(self):
        clean = _clean({"action": "generate", "channels": ["aurora"], "prompt": "猫"})
        self.assertEqual(clean["prompt"], "猫")

    def test_unknown_field_rejected(self):
        clean, err = params.validate({"channels": ["aurora"], "prompt": "x", "foo": 1})
        self.assertIsNone(clean)
        self.assertIn("未知字段", err)

    def test_bad_ratio_rejected(self):
        _, err = params.validate({"action": "generate", "channels": ["aurora"],
                                  "prompt": "x", "ratio": "16x9"})
        self.assertIn("ratio", err)

    def test_out_of_family_tier_passed_through(self):
        """越族档位属通道自治：core 原样透传，由通道按 CAPS.tiers 就近降级（8K→4K）。"""
        clean = _clean({"action": "generate", "channels": ["aurora"],
                        "prompt": "x", "tier": "8K"})
        self.assertEqual(clean.get("tier"), "8K")          # core 不替通道判定合法性
        cap = params.caps("aurora")                        # 通道声明的能力集
        out = params._negotiate("aurora", clean, cap)
        self.assertEqual(out.get("tier"), "4K")            # 通道侧就近向上降级

    def test_n_bounds(self):
        _, err = params.validate({"action": "generate", "channels": ["aurora"],
                                  "prompt": "x", "n": 5})
        self.assertIn("n", err)
        clean = _clean({"action": "generate", "channels": ["aurora"], "prompt": "x", "n": 3})
        self.assertEqual(clean["n"], 3)

    def test_upscale_requires_image(self):
        _, err = params.validate({"action": "upscale", "channels": ["aurora"]})
        self.assertIn("image", err)

    def test_scale_clamped_to_2_or_4(self):
        c1 = _clean({"action": "upscale", "channels": ["aurora"], "image": "a.png", "scale": 10})
        c2 = _clean({"action": "upscale", "channels": ["aurora"], "image": "a.png", "scale": 1})
        self.assertEqual(c1["scale"], 4)
        self.assertEqual(c2["scale"], 2)

    def test_over_limit_hard_clamped(self):
        clean = _clean({"action": "generate", "channels": ["aurora"], "prompt": "x",
                        "image": ["a"] * 15})
        self.assertEqual(len(clean["image"]), 14)

    def test_relay_model_ids_accepted(self):
        for m in ("gpt-image-2", "gpt-image-2-vip", "nano-banana-2",
                  "nano-banana-pro", "nano-banana-2-lite"):
            clean = _clean({"action": "generate", "channels": ["aurora"],
                            "prompt": "x", "model": m})
            self.assertEqual(clean["model"], m)


class TestPlanNegotiate(unittest.TestCase):
    """能力门控与就近协商（aurora CAPS：i2i/upscale=True、n=False、refs=2）。"""

    def test_i2i_and_upscale_accepted(self):
        with _deterministic():
            r1 = params.plan(_clean({"action": "generate", "channels": ["aurora"],
                                     "prompt": "x", "image": "a.png"}))
            r2 = params.plan(_clean({"action": "upscale", "channels": ["aurora"],
                                     "image": "a.png"}))
        self.assertIn("aurora", r1["accepted"])
        self.assertIn("aurora", r2["accepted"])

    def test_upscale_dropped_without_credential(self):
        """漏洞回归：无凭证通道的放大应在计划层剔除（与 generate 同门控）。"""
        with mock.patch.object(params, "credential_label", return_value="需配置"), \
             mock.patch.object(params, "view_status", return_value={"state": "unverified"}), \
             mock.patch.object(params.switches, "is_enabled", return_value=True):
            r = params.plan(_clean({"action": "upscale", "channels": ["aurora"],
                                    "image": "a.png"}))
        self.assertEqual(r["accepted"], [])
        self.assertEqual(r["dropped"][0]["reason"], "需配置 Key")

    def test_n_dropped_channel_lacks_capability(self):
        with _deterministic():
            kw = params.translate("aurora", _clean(
                {"action": "generate", "channels": ["aurora"], "prompt": "x", "n": 3}))
        self.assertNotIn("n", kw)

    def test_tier_nearest_up(self):
        """3K 不在通道档位 → 就近升档（2K/4K 之一），绝不透传 3K。"""
        with _deterministic():
            kw = params.translate("aurora", _clean(
                {"action": "generate", "channels": ["aurora"], "prompt": "x", "tier": "3K"}))
        self.assertIn(kw["image_size"], ("2K", "4K"))

    def test_ratio_nearest(self):
        with _deterministic():
            kw = params.translate("aurora", _clean(
                {"action": "generate", "channels": ["aurora"], "prompt": "x", "ratio": "5:4"}))
        self.assertIn(kw["size"], ("1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "21:9"))

    def test_multi_image_truncated_to_refs(self):
        with _deterministic():
            kw = params.translate("aurora", _clean(
                {"action": "generate", "channels": ["aurora"], "prompt": "x",
                 "image": URIS}))
        self.assertEqual(kw["image"], URIS[:2])   # image_refs=2，第 1 张为主编辑图

    def test_no_auto_tier_for_paid_channel(self):
        """manual（用户Key）通道不自动补体验档。"""
        with _deterministic():
            kw = params.translate("aurora", _clean(
                {"action": "generate", "channels": ["aurora"], "prompt": "x"}))
        self.assertNotIn("image_size", kw)


class TestRoutingPayload(unittest.TestCase):
    """模型路由 + 请求 payload（open / gemini 两系列）。"""

    def test_open_t2i_payload(self):
        created, p = _run_generate({"action": "generate", "channels": ["aurora"],
                                    "prompt": "猫", "model": "gpt-image-2",
                                    "ratio": "16:9", "tier": "2K"})
        self.assertEqual(created, ["gpt"])
        self.assertEqual(p["model"], "gpt-image-2")
        self.assertEqual(p["prompt"], "猫")
        self.assertTrue(p["async"])
        self.assertEqual(p["n"], 1)
        self.assertEqual(p["size"], "16:9")
        self.assertEqual(p["image_size"], "2K")   # 字段名全小写（新网关校验）
        self.assertNotIn("aspect_ratio", p)
        self.assertNotIn("image", p)

    def test_gemini_t2i_aspect_ratio(self):
        created, p = _run_generate({"action": "generate", "channels": ["aurora"],
                                    "prompt": "猫", "model": "nano-banana-2",
                                    "options": {"aspect_ratio": "9:16"},
                                    "ratio": "9:16", "tier": "4K"})
        self.assertEqual(created, ["nano"])
        self.assertEqual(p["model"], "nano-banana-2")
        self.assertEqual(p["aspect_ratio"], "9:16")
        self.assertEqual(p["size"], "9:16")
        self.assertEqual(p["image_size"], "4K")

    def test_gpt_route_drops_aspect_ratio(self):
        """aspect_ratio 为 nano 官方参数：gpt 路由摘除，不进 payload。"""
        _, p = _run_generate({"action": "generate", "channels": ["aurora"],
                              "prompt": "猫", "model": "gpt-image-2",
                              "options": {"aspect_ratio": "9:16"}, "ratio": "9:16"})
        self.assertNotIn("aspect_ratio", p)
        self.assertEqual(p["size"], "9:16")     # 比例仍经 size 生效

    def test_i2i_single_and_multi(self):
        _, p1 = _run_generate({"action": "generate", "channels": ["aurora"],
                               "prompt": "换背景", "model": "nano-banana-2",
                               "image": URIS[0]})
        self.assertEqual(p1["image"], [URIS[0]])
        _, p2 = _run_generate({"action": "generate", "channels": ["aurora"],
                               "prompt": "换背景", "model": "nano-banana-2",
                               "image": URIS[:2]})
        self.assertEqual(p2["image"], URIS[:2])

    def test_model_routing_cases(self):
        for m, expect in (("gpt-image-2-vip", "gpt"), ("nano-banana-pro", "nano"),
                          ("NANO-BANANA-2", "nano"), ("nano-banana-2-lite", "nano")):
            created, p = _run_generate({"action": "generate", "channels": ["aurora"],
                                        "prompt": "x", "model": m})
            self.assertEqual(created, [expect], m)
            self.assertEqual(p["model"], m)     # 模型 ID 原样透传给中继

    def test_n_always_1_in_payload(self):
        _, p = _run_generate({"action": "generate", "channels": ["aurora"],
                              "prompt": "x", "model": "gpt-image-2", "n": 3})
        self.assertEqual(p["n"], 1)


class TestUpscaleRouting(unittest.TestCase):
    """放大路由与透传（app.upscale → 客户端.upscale）。"""

    def test_full_kwargs_forwarded(self):
        with mock.patch.object(aurora_app, "GPTImageClient") as G, \
             mock.patch.object(aurora_app, "NanoBananaClient") as N, \
             mock.patch.object(aurora_app, "get_key", return_value="k"):
            aurora_app.upscale("a.png", scale=4, prompt="增强", model="nano-banana-2",
                               image_size="4K", size="16:9")
            N.assert_called_once()
            G.assert_not_called()
            N.return_value.upscale.assert_called_once_with(
                "a.png", scale=4, prompt="增强", model="nano-banana-2",
                image_size="4K", size="16:9")

    def test_minimal_upscale(self):
        with mock.patch.object(aurora_app, "GPTImageClient") as G, \
             mock.patch.object(aurora_app, "NanoBananaClient") as N, \
             mock.patch.object(aurora_app, "get_key", return_value="k"):
            aurora_app.upscale("a.png", scale=2)
            G.assert_called_once()              # 无 model → 默认 gpt 系
            N.assert_not_called()
            G.return_value.upscale.assert_called_once_with("a.png", scale=2, prompt=None)


if __name__ == "__main__":
    unittest.main()

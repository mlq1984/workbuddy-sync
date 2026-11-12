# -*- coding: utf-8 -*-
"""路由不变量回归（留仓）：统一入口 / 付费档可达 / 通道自治降级 / 无字段泄漏。"""
import io
import os
import re
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import params, registry        # noqa: E402
from core import custom_channels as cc   # noqa: E402

BUILTIN = ["aurora", "agnes", "shangtang", "zhipu", "cloudflare", "free"]


class TestRouteInvariants(unittest.TestCase):
    """通道中心=统一入口与路由；通道=自治过滤/降级/转换。"""

    def test_only_executor_invokes_channel_generate(self):
        """唯一生图调用点必须是编排层（executor）——杜绝绕过统一入口。"""
        hits = {}
        core_dir = os.path.join(_ROOT, "core")
        for dp, dn, fns in os.walk(core_dir):
            dn[:] = [d for d in dn if d != "__pycache__"]
            for fn in fns:
                if fn.endswith(".py"):
                    p = os.path.join(dp, fn)
                    src = io.open(p, encoding="utf-8").read()
                    for m in re.finditer(r"[^\w.](\w+)\.generate\(", src):
                        hits.setdefault(m.group(1), set()).add(os.path.relpath(p, _ROOT))
        for mod, files in hits.items():
            for f in files:
                self.assertIn("executor", f,
                              "%s.generate 在 %s 被调用（应仅经编排层）" % (mod, f))

    def test_paid_models_are_reachable(self):
        """付费档与免费档一律可达：模型原样下传，不被中心误删。"""
        for cid, m in (("zhipu", "cogview-4-250304"), ("aurora", "gpt-image-2-vip"),
                       ("aurora", "nano-banana-pro"), ("free", "turbo"), ("cloudflare", "sdxl")):
            clean, err = params.validate({"action": "generate", "channels": [cid],
                                          "prompt": "x", "model": m})
            self.assertIsNotNone(clean, err)
            kw = params.translate(cid, clean)
            self.assertEqual(kw.get("model"), m)

    def test_custom_channel_same_route(self):
        """自定义通道与内置通道同走统一链路（模拟注册后）。"""
        rec = {"id": "u1", "name": "o", "protocol": "open",
               "base_url": "https://r.example.com", "model": ""}
        ad = cc.adapter(rec)
        with mock.patch.object(params, "get_channel", return_value={"id": "u1", "module": ad}), \
                mock.patch.object(params, "all_channels",
                                  return_value=[{"id": "u1", "module": ad}]):
            clean, err = params.validate({"action": "generate", "channels": ["u1"],
                                          "prompt": "x", "model": "gpt-image-2.5-sunburst"})
            self.assertIsNotNone(clean, err)
            kw = params.translate("u1", clean)
        self.assertEqual(kw.get("model"), "gpt-image-2.5-sunburst")

    def test_tier_autonomy(self):
        """档位：core 原样透传，通道按自身 CAPS 就近降级（未知档→就近向上）。"""
        clean, err = params.validate({"action": "generate", "channels": ["aurora"],
                                      "prompt": "x", "tier": "8K"})
        self.assertIsNotNone(clean, err)
        self.assertEqual(clean["tier"], "8K")
        cap = params.caps("aurora")
        out = params._negotiate("aurora", clean, cap)
        self.assertEqual(out["tier"], "4K")
        self.assertIn(out["tier"], cap["tiers"])

    def test_no_field_leak_to_channel(self):
        """核心语义键不得原样泄给通道（tier/options 须被转换或不传）。"""
        for cid in BUILTIN:
            clean, _ = params.validate({"action": "generate", "channels": [cid], "prompt": "x",
                                        "ratio": "16:9", "tier": "2K",
                                        "options": {"quality": "max"}})
            if clean is None:
                continue
            kw = params.translate(cid, clean)
            self.assertNotIn("tier", kw, "%s 收到未转换的 tier" % cid)
            self.assertNotIn("options", kw, "%s 收到未转换的 options" % cid)

    def test_unsupported_capability_dropped_with_reason(self):
        """通道不支持的能力被剔除且原因可读（不静默失败）。"""
        clean, _ = params.validate({"action": "generate", "channels": ["zhipu"],
                                    "prompt": "x", "image": ["a.png"]})
        self.assertIsNotNone(clean)
        plan = params.plan(clean)
        self.assertNotIn("zhipu", plan["accepted"])
        self.assertTrue(plan["dropped"] and plan["dropped"][0].get("reason"))

    def test_ratio_and_image_within_channel_caps(self):
        """比例/档位/参考图/张数一律落在通道自声明能力范围内。"""
        for cid in BUILTIN:
            ch = registry.get_channel(cid)
            cap = params.caps(cid)
            clean, err = params.validate({"action": "generate", "channels": [cid], "prompt": "x",
                                          "ratio": "4:5", "tier": "8K", "n": 3,
                                          "image": ["a.png"] * 14})
            if clean is None:
                continue
            kw = params.translate(cid, clean)
            if "size" in kw and cap.get("ratios"):
                self.assertTrue(kw["size"] in cap["ratios"]
                                or kw["size"] in (cap.get("tiers") or [])
                                or re.match(r"^\d+x\d+$", str(kw["size"])),
                                "%s size=%s 越界" % (cid, kw["size"]))
            if "image_size" in kw and cap.get("tiers"):
                self.assertIn(kw["image_size"], cap["tiers"], "%s image_size 越界" % cid)
            if kw.get("n"):
                self.assertTrue(cap.get("n"), "%s 收到 n 但不支持" % cid)
            if isinstance(kw.get("image"), list) and cap.get("image_refs") is not None:
                self.assertLessEqual(len(kw["image"]), cap.get("image_refs") or 1,
                                     "%s 参考图超上限" % cid)


if __name__ == "__main__":
    unittest.main()

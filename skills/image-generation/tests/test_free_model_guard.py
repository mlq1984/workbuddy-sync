# -*- coding: utf-8 -*-
"""通道自治：free 通道未知型号必须如实报错（此前静默归一为 flux）。"""
import importlib.util
import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _load_free_app():
    path = os.path.join(_ROOT, "channels", "free", "app.py")
    spec = importlib.util.spec_from_file_location("free_app_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestFreeModelGuard(unittest.TestCase):
    """free：型号不在通道清单时如实报错（此前任何非 turbo 值静默归一为 flux）。"""

    def setUp(self):
        self.app = _load_free_app()

    def test_known_models_accepted(self):
        # 官方仅 flux / turbo 两种；守门不得误拒官方型号
        for m in self.app.MODELS:
            self.assertIn(m, ("flux", "turbo"))

    def test_unknown_model_raises_with_available_list(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.app.generate("cat", model="gpt-image")
        self.assertIn("模型不在本通道清单", str(ctx.exception))
        self.assertIn("turbo", str(ctx.exception))     # 错误信息列出可用型号

    def test_empty_model_defaults_to_flux(self):
        # 缺省（未传 model）仍走 flux——默认行为零变化
        self.assertEqual(self.app.MODELS[0], "flux")


class TestFreeBearer(unittest.TestCase):
    """free 方案A：可选 Bearer Key（官方 bearerAuth），匿名档零变化，错误脱敏。"""

    def setUp(self):
        self.app = _load_free_app()
        self.caps = []

        def fb(url, timeout=0, extra_headers=None):
            self.caps.append({"url": url, "h": dict(extra_headers or {})})
            return b"x" * 2048

        self.fb = fb

    def _run(self, key):
        self.caps.clear()
        with mock.patch.object(self.app, "get_key", return_value=key), \
                mock.patch.object(self.app, "fetch_bytes", side_effect=self.fb), \
                mock.patch.object(self.app, "save_output", return_value="/p/a.jpg"):
            self.app.generate("cat")

    def test_anonymous_no_auth(self):
        self._run(None)
        self.assertNotIn("Authorization", self.caps[0]["h"])   # 匿名档无鉴权头
        self.assertNotIn("token", self.caps[0]["url"])         # URL 不含任何 token

    def test_bearer_header_key_not_in_url(self):
        self._run("sk_test_123")
        self.assertEqual(self.caps[0]["h"].get("Authorization"), "Bearer sk_test_123")
        self.assertNotIn("sk_test_123", self.caps[0]["url"])   # Key 不进 URL

    def test_error_message_sanitized(self):
        def boom(url, timeout=0, extra_headers=None):
            raise RuntimeError("HTTP 999 https://x/prompt/secret?width=1&token=abc")
        with mock.patch.object(self.app, "get_key", return_value="sk_x"), \
                mock.patch.object(self.app, "fetch_bytes", side_effect=boom):
            with self.assertRaises(RuntimeError) as ctx:
                self.app.generate("cat")
        msg = str(ctx.exception)
        self.assertNotIn("token=abc", msg)                     # query 脱敏
        self.assertIn("请求失败", msg)


class TestUserKeyReadiness(unittest.TestCase):
    """未验证项分析：用户配置自己的 Key 后各通道是否立即可用（mock 出站，零消耗）。"""

    def test_a_all_channels_accept_user_key(self):
        from core import params
        with mock.patch.object(params, "credential_label", side_effect=lambda c: "用户Key"), \
                mock.patch.object(params, "view_status", side_effect=lambda c: {"state": "valid"}):
            for cid in ("aurora", "agnes", "shangtang", "zhipu", "cloudflare", "free"):
                clean, err = params.validate({"action": "generate", "channels": [cid], "prompt": "x"})
                self.assertIsNotNone(clean, err)
                plan = params.plan(clean)
                self.assertIn(cid, plan["accepted"],
                              "%s 用户Key下被剔除: %s" % (cid, plan["dropped"]))

    def test_b_free_paid_tier_chain(self):
        app = _load_free_app()
        caps = []

        def fb(url, timeout=0, extra_headers=None):
            caps.append((url, dict(extra_headers or {})))
            return b"x" * 2048
        with mock.patch.object(app, "get_key", return_value="sk_user_1"), \
                mock.patch.object(app, "fetch_bytes", side_effect=fb), \
                mock.patch.object(app, "save_output", return_value="/p/a.jpg"):
            app.generate("cat", model="turbo")
        url, h = caps[-1]
        self.assertEqual(h.get("Authorization"), "Bearer sk_user_1")
        self.assertNotIn("sk_user_1", url)
        self.assertIn("model=turbo", url)

    def test_c_translate_outbound_user_key(self):
        from core import params
        with mock.patch.object(params, "credential_label", side_effect=lambda c: "用户Key"), \
                mock.patch.object(params, "view_status", side_effect=lambda c: {"state": "valid"}):
            for cid, extra, key in (("zhipu", {"ratio": "9:16"}, "size"),
                                    ("cloudflare", {"ratio": "16:9", "model": "sdxl"}, "size"),
                                    ("agnes", {"tier": "2K"}, "size")):
                clean, err = params.validate(dict(
                    {"action": "generate", "channels": [cid], "prompt": "x"}, **extra))
                self.assertIsNotNone(clean, err)
                kw = params.translate(cid, clean)
                self.assertIn(key, kw, "%s 出站缺 %s" % (cid, key))


if __name__ == "__main__":
    unittest.main()

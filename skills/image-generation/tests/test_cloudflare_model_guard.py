# -*- coding: utf-8 -*-
"""通道自治：未知型号必须如实报错，不得静默回落到别的模型。

加载注意：各通道目录都有同名 client.py，本测试**不得**用 sys.path.insert +
`import client`（会占用全局模块名 client，使 registry 发现其它通道时导入错模块）。
改用 importlib 以唯一名加载，且不改动 sys.path。
"""
import importlib.util
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _load_cloudflare_client():
    path = os.path.join(_ROOT, "channels", "cloudflare", "client.py")
    spec = importlib.util.spec_from_file_location("cf_client_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCloudflareModelGuard(unittest.TestCase):
    """cloudflare：型号不在通道清单时如实报错（此前静默回落 flux-1-schnell）。"""

    def setUp(self):
        self.c = _load_cloudflare_client().WorkersAIClient(api_key="token@acct")

    def test_known_models_route(self):
        for m, frag in (("flux-1-schnell", "flux-1-schnell"), ("sdxl", "stable-diffusion-xl"),
                        ("sd15", "stable-diffusion-1.5"), ("flux", "flux-1-schnell")):
            self.assertIn(frag, self.c._model_path({"model": m}))

    def test_unknown_model_raises_with_available_list(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.c._model_path({"model": "gpt-image-2"})
        msg = str(ctx.exception)
        self.assertIn("模型不在本通道清单", msg)
        self.assertIn("sdxl", msg)          # 错误信息列出可用型号

    def test_empty_model_uses_default(self):
        self.assertIn("flux-1-schnell", self.c._model_path({}))


if __name__ == "__main__":
    unittest.main()

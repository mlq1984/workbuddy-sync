# -*- coding: utf-8 -*-
"""多代理审查定案的「绝对安全项」回归（mock 网络：零触网、零真生图）。

覆盖本轮修复：
1. 版本号三方一致（server.APP_VERSION / SKILL.md / manifest.json）
2. 自定义通道 base_url 归一化（剥尾部 /v1、/v1beta，避免 /v1/v1/... → 404）
3. ratio 两端须为正整数（"1:0" 在校验层 400，不再流到执行层静默卡死）
4. options 只补不盖（核心语义键不被劫持，绕过 n 钳制）
5. options 假值（0/False）按键存在判定透传
6. aurora config.ini 真正被加载，且与内置默认逐项一致（行为零变化）
"""
import json
import os
import re
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "channels", "aurora"))

from core import params            # noqa: E402
from core import custom_channels as cc   # noqa: E402
from core import executor          # noqa: E402
import base as aurora_base         # noqa: E402


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestVersionConsistency(unittest.TestCase):
    """版本号三方一致（此前 server.py 停留在 1.13.0，/api/ping 对外暴露旧版本）。"""

    def test_three_way_version(self):
        app = re.search(r'APP_VERSION\s*=\s*"([^"]+)"',
                        _read(os.path.join(_ROOT, "core", "server.py"))).group(1)
        sk = re.search(r'version:\s*"([^"]+)"',
                       _read(os.path.join(_ROOT, "SKILL.md"))).group(1)
        mf = json.loads(_read(os.path.join(_ROOT, "manifest.json")))["version"]
        self.assertEqual(app, sk, "server.APP_VERSION 与 SKILL.md 版本不一致")
        self.assertEqual(sk, mf, "SKILL.md 与 manifest.json 版本不一致")


class TestBaseUrlNormalize(unittest.TestCase):
    """base_url 归一化：管理台提示填带版本的地址，请求侧统一拼版本段，不归一化会翻倍。"""

    def test_normalize_cases(self):
        f = cc._norm_base_url
        self.assertEqual(f("https://x.com"), "https://x.com")
        self.assertEqual(f("https://x.com/"), "https://x.com")
        self.assertEqual(f("https://x.com/v1"), "https://x.com")
        self.assertEqual(f("https://x.com/v1/"), "https://x.com")
        self.assertEqual(f("https://x.com/v1beta"), "https://x.com")
        self.assertEqual(f("https://x.com/v1beta/"), "https://x.com")
        self.assertEqual(f("https://x.com/api/v1"), "https://x.com/api")
        self.assertEqual(f("https://v1"), "https://v1")        # 主机名不动
        self.assertEqual(f("https://x.com/openai"), "https://x.com/openai")

    def test_request_url_no_double_version(self):
        rec = {"id": "u1", "name": "t", "protocol": "open",
               "base_url": cc._norm_base_url("https://r.example.com/v1"), "model": ""}
        ad = cc.adapter(rec)
        with mock.patch.object(ad, "_http") as mh, \
                mock.patch.object(ad, "_save", return_value="/p/x.png"):
            mh.return_value = (200, {"data": [{"b64_json": "aGk="}]})
            ad.generate("猫")
        self.assertEqual(mh.call_args_list[0][0][1],
                         "https://r.example.com/v1/images/generations")


class TestRatioValidation(unittest.TestCase):
    """ratio 分母为 0 曾让协商层除零 → 5xx/静默卡死；改为校验层拒绝。"""

    def test_zero_denominator_rejected(self):
        clean, err = params.validate({"action": "generate", "channels": ["aurora"],
                                      "prompt": "x", "ratio": "1:0"})
        self.assertIsNone(clean)
        self.assertIsNotNone(err)
        self.assertIn("16:9", err)

    def test_zero_numerator_rejected(self):
        _, err = params.validate({"action": "generate", "channels": ["aurora"],
                                  "prompt": "x", "ratio": "0:9"})
        self.assertIsNotNone(err)

    def test_normal_ratio_accepted(self):
        clean, err = params.validate({"action": "generate", "channels": ["aurora"],
                                      "prompt": "x", "ratio": "16:9"})
        self.assertIsNone(err)
        self.assertEqual(clean["ratio"], "16:9")

    def test_nearest_ratio_guard(self):
        self.assertIsNone(params._nearest_ratio("1:0", ["1:1", "16:9"]))


class TestOptionsSemantics(unittest.TestCase):
    """options 是通道专属参数位：只补不盖核心语义键；假值按键存在判定透传。"""

    def setUp(self):
        self.rec = {"id": "u1", "name": "t", "protocol": "open",
                    "base_url": "https://r.example.com", "model": ""}
        self.ad = cc.adapter(self.rec)

    def _payload(self, **kw):
        kwargs = {"prompt": "猫"}
        kwargs.update(kw)
        with mock.patch.object(self.ad, "_http") as mh, \
                mock.patch.object(self.ad, "_save", return_value="/p/y.png"):
            mh.return_value = (200, {"data": [{"b64_json": "aGk="}]})
            self.ad.generate(**kwargs)
        return mh.call_args_list[0][0][2]

    def test_options_cannot_hijack_n(self):
        with mock.patch.object(params, "get_channel",
                               return_value={"id": "u1", "module": self.ad}):
            kw = params.translate("u1", {"action": "generate", "prompt": "猫",
                                         "options": {"n": 99}})
        self.assertNotIn("n", kw)                     # 核心语义键不被劫持
        p = self._payload(**kw)
        self.assertLessEqual(p.get("n", 1), 4)        # 不再绕过 1~4 钳制

    def test_options_cannot_override_size(self):
        with mock.patch.object(params, "get_channel",
                               return_value={"id": "u1", "module": self.ad}):
            kw = params.translate("u1", {"action": "generate", "prompt": "猫",
                                         "ratio": "16:9", "options": {"size": "1:1"}})
        self.assertEqual(kw["size"], "16:9")

    def test_falsy_options_preserved(self):
        p = self._payload(output_compression=0, moderation=False)
        self.assertIn("output_compression", p)
        self.assertEqual(p["output_compression"], 0)
        self.assertIn("moderation", p)
        self.assertEqual(p["moderation"], False)


class TestAuroraConfigLoaded(unittest.TestCase):
    """aurora config.ini 此前从未被加载（路径上溯错位）；现同目录定位且行为零变化。"""

    def test_find_config_points_to_existing_file(self):
        p = aurora_base.BaseClient._find_config()
        self.assertIsNotNone(p)
        self.assertTrue(os.path.isfile(p))
        self.assertTrue(p.replace("\\", "/").endswith("channels/aurora/config.ini"))

    def test_config_matches_builtin_defaults(self):
        from gpt_image import GPTImageClient
        c = GPTImageClient()
        self.assertEqual(c.default_model, GPTImageClient.DEFAULT_MODEL)
        self.assertEqual(c.default_size, GPTImageClient.DEFAULT_SIZE)
        self.assertEqual(c.base_url, aurora_base.BaseClient.BASE)
        self.assertEqual(c.ua, aurora_base.BaseClient.DEFAULT_UA)
        self.assertEqual(c.timeout, 360)
        self.assertEqual(c.poll_interval, 5)

    def test_no_credential_timeout_entry(self):
        txt = _read(os.path.join(_ROOT, "channels", "aurora", "config.ini"))
        self.assertNotIn("credential_timeout", txt)


class TestExecutorHarvest(unittest.TestCase):
    """通道线程异常此前被静默吞掉（item 永远卡 pending）；现兜底非终态 item 且 finalize 必达。"""

    def _run_with_boom(self, items, summary):
        job = {"id": "j1", "items": items, "summary": summary}
        with mock.patch.object(executor, "_run_channel", side_effect=RuntimeError("boom")), \
                mock.patch.object(executor.notify, "emit"), \
                mock.patch.object(executor.jobs, "get", side_effect=lambda *a, **k: job), \
                mock.patch.object(executor.jobs, "mark_started"), \
                mock.patch.object(executor.jobs, "finalize") as mf, \
                mock.patch.object(executor, "_item_fail") as mfail:
            executor._run("j1")
        return mfail, mf

    def test_pending_item_failed_done_kept(self):
        items = [{"channel": "aurora", "index": 0, "state": "pending"},
                 {"channel": "aurora", "index": 1, "state": "done"}]
        mfail, mf = self._run_with_boom(items, {"done": 1, "failed": 0, "total": 2})
        self.assertEqual(mfail.call_count, 1)              # 只兜底非终态：0 号 pending 被标失败
        self.assertEqual(mfail.call_args[0][2], 0)
        self.assertEqual(mfail.call_args[0][3], "通道线程异常（详见服务日志）")
        mf.assert_called_once()                            # finalize 必达（不被二次异常跳过）

    def test_multi_image_not_collapsed(self):
        """多参考图曾在执行层被单值化（to_data_uri 只收 str）→ 多图 i2i 全废；现逐张归一化。"""

        def fn(**kw):
            captured["image"] = kw.get("image")
            return ["/p/a.png"]
        captured = {}
        uris = ["data:image/png;base64,aa", "data:image/png;base64,bb"]
        paths, err = executor._unit_call(fn, {"prompt": "x", "image": list(uris)})
        self.assertIsNone(err, "多参考图不应在执行层报错")
        self.assertEqual(paths, ["/p/a.png"])
        self.assertEqual(captured["image"], uris)          # 保持数组、逐张归一化

    def test_single_image_unchanged(self):
        def fn(**kw):
            captured["image"] = kw.get("image")
            return ["/p/b.png"]
        captured = {}
        paths, err = executor._unit_call(fn, {"prompt": "x", "image": "data:image/png;base64,aa"})
        self.assertIsNone(err)
        self.assertEqual(captured["image"], "data:image/png;base64,aa")   # 单图仍是标量

    def test_no_terminal_item_overwritten(self):
        items = [{"channel": "aurora", "index": 0, "state": "done"},
                 {"channel": "agnes", "index": 1, "state": "failed"}]
        mfail, mf = self._run_with_boom(items, {"done": 1, "failed": 1, "total": 2})
        mfail.assert_not_called()                          # 终态项不被覆盖
        mf.assert_called_once()


class TestOfficialSync(unittest.TestCase):
    """与官方口径同步：能力声明、型号清单、协议字段名、放大参数透传。"""

    def test_shangtang_capabilities_include_official_3x2_2x3(self):
        """官方推荐分辨率表含 3:2/2:3（2K 档 2496x1664 / 1664x2496）→ CAPS 必须声明。"""
        ratios = params.caps("shangtang")["ratios"]
        for r in ("3:2", "2:3"):
            self.assertIn(r, ratios)

    def test_zhipu_ratios_narrowed_to_official_five(self):
        """官方仅 5 档；超报会让未命中比例静默回落 1024x1024。"""
        ratios = params.caps("zhipu")["ratios"]
        self.assertEqual(sorted(ratios), sorted(["1:1", "16:9", "9:16", "4:3", "3:4"]))

    def test_aurora_models_expose_relay_lineup(self):
        """中继在售型号（含 2K/4K 的 vip/pro）应全部可见，默认仍在前两位。"""
        src = _read(os.path.join(_ROOT, "channels", "aurora", "app.py"))
        for mid in ("gpt-image-2", "gpt-image-2-vip", "nano-banana-2",
                    "nano-banana-pro", "nano-banana-2-lite"):
            self.assertIn('"%s"' % mid, src)

    def test_aurora_upscale_passes_aspect_ratio(self):
        """放大路径与文生图同构：options.aspect_ratio 不应被吞。"""
        import app as aurora_app
        kw = aurora_app.translate({"action": "upscale", "image": "a.png", "scale": 2,
                                   "options": {"aspect_ratio": "16:9"}})
        self.assertEqual(kw.get("aspect_ratio"), "16:9")

    def test_gemini_request_uses_official_camel_case(self):
        """官方 generateContent 规范字段名：inlineData/mimeType（proto3 亦收蛇形）。"""
        src = _read(os.path.join(_ROOT, "core", "custom_channels.py"))
        self.assertIn('"inlineData": {"mimeType"', src)

    def test_truth_source_readers_log_failures(self):
        """jobs/works/switches 读取失败必须留痕（否则损坏即静默消失）。"""
        for rel in ("core/jobs.py", "core/works.py", "core/switches.py"):
            src = _read(os.path.join(_ROOT, *rel.split("/")))
            self.assertIn("logger.exception", src, "%s 缺 logger.exception" % rel)

    def test_caps_narrowed_by_model(self):
        """能力按型号细分：缺省 flux-1-schnell 官方仅 1:1；sdxl/sd15 支持 5 种比例。"""
        self.assertEqual(params.caps("cloudflare")["ratios"], ["1:1"])   # 缺省型号
        self.assertEqual(params.caps("cloudflare", "flux-1-schnell")["ratios"], ["1:1"])
        self.assertIn("16:9", params.caps("cloudflare", "sdxl")["ratios"])
        self.assertIn("16:9", params.caps("cloudflare", "sd15")["ratios"])

    def test_upscale_tier_ratio_negotiated(self):
        """upscale 也做 tier/ratio 就近映射（放大档位/画幅不该直发越界值）。"""
        cap = params.caps("aurora", "nano-banana-2")
        out = params._negotiate("aurora", {"action": "upscale", "image": "a.png",
                                           "scale": 4, "tier": "3K", "ratio": "4:5"}, cap)
        self.assertEqual(out.get("tier"), "4K")
        self.assertIn(out.get("ratio"), ("3:4", "4:3"))
        self.assertNotIn("n", out)                        # 放大不涉及 n

    def test_gemini_model_path_encoded(self):
        """gemini 模型名进 URL 前必须编码（用户可填任意模型名）。"""
        rec = {"id": "u2", "name": "g", "protocol": "gemini",
               "base_url": "https://r.example.com", "model": ""}
        ad = cc.adapter(rec)
        cap = {}

        def fh(m, u, payload=None, key="", dual=False, retries=2):
            cap["url"] = u
            return (200, {"candidates": [{"content": {"parts": [{"inlineData": {"data": "aGk="}}]}}]})
        ad._http = fh
        ad._save = lambda d: "/p/q.png"
        ad.generate("cat", model="gemini 3.1 flash")
        self.assertNotIn(" ", cap["url"])
        self.assertIn("%20", cap["url"])
        cap2 = {}

        def fh2(m, u, payload=None, key="", dual=False, retries=2):
            cap2["url"] = u
            return (200, {"candidates": [{"content": {"parts": [{"inlineData": {"data": "aGk="}}]}}]})
        ad._http = fh2
        ad.generate("cat", model="models/gemini-3-pro-image")
        self.assertIn("/v1beta/models/gemini-3-pro-image:generateContent", cap2["url"])


if __name__ == "__main__":
    unittest.main()

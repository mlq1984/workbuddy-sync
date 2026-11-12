# -*- coding: utf-8 -*-
"""自定义中转通道离线测试：注册表 CRUD / 校验 / 适配器 payload 组装与响应解析（不触网）。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import custom_channels as cc   # noqa: E402


class _TempReg(unittest.TestCase):
    """注册表读写重定向到临时文件，用后即焚。"""

    def setUp(self):
        self._old = cc.REG_FILE
        import tempfile
        fd, cc.REG_FILE = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        if os.path.exists(cc.REG_FILE):
            os.remove(cc.REG_FILE)

    def tearDown(self):
        if os.path.exists(cc.REG_FILE):
            os.remove(cc.REG_FILE)
        cc.REG_FILE = self._old


class TestRegistry(_TempReg):
    def test_add_and_list(self):
        r = cc.add("测试站", "open", "https://api.x.com/v1", "gpt-image-2")
        self.assertTrue(r["ok"])
        self.assertEqual(r["id"], "u1")
        chans = cc.list_channels()
        self.assertEqual(len(chans), 1)
        self.assertEqual(chans[0]["name"], "测试站")
        self.assertEqual(chans[0]["protocol"], "open")
        self.assertNotIn("_", r["id"])            # id 无下划线（作品命名解析依赖）

    def test_add_validation(self):
        r = cc.add("", "open", "https://x.com", "m")            # 名称选填 → 缺省名
        self.assertTrue(r["ok"])
        self.assertEqual(cc.get(r["id"])["name"], "自定义通道")
        self.assertFalse(cc.add("n", "bad", "https://x.com", "m")["ok"])
        self.assertFalse(cc.add("n", "open", "ftp://x.com", "m")["ok"])
        r2 = cc.add("n2", "open", "https://x.com", "")          # 模型选填 → 留空用内置
        self.assertTrue(r2["ok"])

    def test_edit(self):
        r = cc.add("旧名", "open", "https://a.com", "m1")
        cid = r["id"]
        e = cc.edit(cid, "新名", "gemini", "https://b.com/v1beta", "m2", "https://b.com")
        self.assertTrue(e["ok"])
        rec = cc.get(cid)
        self.assertEqual(rec["name"], "新名")
        self.assertEqual(rec["protocol"], "gemini")
        self.assertEqual(rec["base_url"], "https://b.com")   # 归一化：剥掉尾部版本段（请求侧统一拼 /v1beta/...，实际端点不变）
        self.assertFalse(cc.edit("u99", "x", "open", "https://x.com", "m")["ok"])   # 不存在

    def test_id_auto_increment(self):
        cc.add("a", "open", "https://a.com", "m1")
        r = cc.add("b", "open", "https://b.com", "m2")
        self.assertEqual(r["id"], "u2")

    def test_remove_clears_credential(self):
        from core import store
        r = cc.add("a", "open", "https://a.com", "m1")
        cid = r["id"]
        store.set_key(cid, "sk-test")
        self.assertTrue(cc.remove(cid)["ok"])
        self.assertIsNone(cc.get(cid))
        self.assertIsNone(store.get_key(cid))     # 凭证段一并清除


class TestAdapter(unittest.TestCase):
    """适配器 payload 组装与响应解析（mock HTTP，不触网）。"""

    def setUp(self):
        self.rec = {"id": "u1", "name": "测", "protocol": "open",
                    "base_url": "https://api.x.com", "model": "gpt-image-2",
                    "official_url": "https://x.com"}
        self.ad = cc._Adapter(self.rec)

    def test_contract_fields(self):
        self.assertEqual(self.ad.CHANNEL_ID, "u1")
        self.assertEqual(self.ad.MODE, "manual")
        self.assertTrue(self.ad.CAPS["t2i"])
        self.assertTrue(self.ad.CAPS["i2i"])        # 两协议适配器均实现参考图，协商层不得剔除
        self.assertTrue(self.ad.CAPS["n"])          # open：官方 generations 原生支持 n
        self.assertEqual(self.ad.CAPS["image_refs"], 10)
        for r in ("2:3", "3:2", "4:5", "5:4"):      # 官方 10 种比例族
            self.assertIn(r, self.ad.CAPS["ratios"])
        self.assertFalse(self.ad.CAPS["upscale"])

    def test_gemini_caps(self):
        """协议感知 CAPS：gemini 单候选（n 不适用）、官方参考图 10+4=14。"""
        ad = cc.adapter(dict(self.rec, protocol="gemini"))
        self.assertFalse(ad.CAPS["n"])
        self.assertEqual(ad.CAPS["image_refs"], 14)
        self.assertIn("4:5", ad.CAPS["ratios"])

    def test_models_of(self):
        # 内置在前；用户设置（中英文逗号混排）去重并入；空设置 = 纯内置
        rec = dict(self.rec, model="gpt-image-2， my-model,  custom；x，gpt-image-2")
        ms = cc.models_of(rec)
        self.assertEqual(ms[0], "gpt-image-2.5-flare")          # 内置第一个（默认 = 最新在前）
        self.assertIn("my-model", ms)
        self.assertIn("custom；x", ms)                          # 分号不是分隔符
        self.assertEqual(ms.count("gpt-image-2"), 1)            # 去重
        self.assertEqual(len(ms), len(set(ms)))
        self.assertEqual(cc.models_of(dict(self.rec, model=""))[0], "gpt-image-2.5-flare")
        self.assertEqual(                                        # gemini 缺省 = Nano Banana 2.1（官方主力）
            cc.models_of({"protocol": "gemini", "model": ""})[0], "gemini-nano-banana-2.1")

    def test_default_model_fallback(self):
        """spec 未指定 model → 适配器用内置第一个。"""
        with mock.patch.object(self.ad, "_http") as mh, \
             mock.patch("core.httpx.fetch_bytes", return_value=b"IMG"), \
             mock.patch.object(self.ad, "_save", return_value="/p.png"):
            mh.return_value = (200, {"data": [{"b64_json": "aGk="}]})
            self.ad.generate("猫")                              # 不传 model
        self.assertEqual(mh.call_args_list[0][0][2]["model"], "gpt-image-2.5-flare")

    def test_open_async_task_compat(self):
        """open 协议兼容中转的 task_id 异步形态（同步 data 直出与轮询皆可）。"""
        with mock.patch.object(self.ad, "_http") as mh, \
             mock.patch.object(self.ad, "_save", return_value="/p/1.png"), \
             mock.patch("core.httpx.fetch_bytes", return_value=b"IMG"):
            mh.side_effect = [(200, {"task_id": "t1"}),
                              (200, {"data": [{"url": "https://f/x.png"}]})]
            paths = self.ad.generate("一只猫", size="16:9", image_size="2K")
        self.assertEqual(paths, ["/p/1.png"])
        post_payload = mh.call_args_list[0][0][2]
        self.assertEqual(post_payload["size"], "16:9")
        self.assertEqual(post_payload["image_size"], "2K")
        self.assertEqual(post_payload["model"], "gpt-image-2.5-flare")   # 未指定 → 内置第一个（最新在前）

    def test_open_sync_flow(self):
        self.rec["protocol"] = "open"
        with mock.patch.object(self.ad, "_http") as mh, \
             mock.patch.object(self.ad, "_save", return_value="/p/2.png"):
            mh.return_value = (200, {"data": [{"b64_json": "aGk="}]})   # 同步直出 b64
            paths = self.ad.generate("猫", size="1:1", image_size="1K")
        self.assertEqual(paths, ["/p/2.png"])
        payload = mh.call_args_list[0][0][2]
        self.assertEqual(payload["image_size"], "1K")           # open 适配器用 image_size 字段

    def test_gemini_dual_parse(self):
        self.rec["protocol"] = "gemini"
        with mock.patch.object(self.ad, "_http") as mh, \
             mock.patch.object(self.ad, "_save", return_value="/p/x.png"):
            # 两种形态各解析一张：inlineData b64 + text=URL 变体
            mh.return_value = (200, {"candidates": [{"content": {"parts": [
                {"inlineData": {"mimeType": "image/png", "data": "aGk="}},
                {"text": "https://f/y.png"}]}}]})
            with mock.patch("core.httpx.fetch_bytes", return_value=b"IMG"):
                paths = self.ad.generate("猫", size="9:16", image_size="4K")
        self.assertEqual(len(paths), 2)
        payload = mh.call_args_list[0][0][2]
        ic = payload["generationConfig"]["imageConfig"]
        self.assertEqual(ic["aspectRatio"], "9:16")
        self.assertEqual(ic["imageSize"], "4K")
        self.assertEqual(payload["generationConfig"]["responseModalities"], ["TEXT", "IMAGE"])

    # ---- 图生图（i2i）全矩阵模拟：open / gemini 双协议参考图 payload ----
    def test_open_i2i_data_uri_payload(self):
        """open 协议图生图：image → data URI 数组 + 新模型指定（sunburst=编辑精度优先）。"""
        uri = "data:image/png;base64,aGk="
        with mock.patch.object(self.ad, "_http") as mh, \
             mock.patch.object(self.ad, "_save", return_value="/p/3.png"):
            mh.return_value = (200, {"data": [{"b64_json": "aGk="}]})
            paths = self.ad.generate("改成赛博朋克风", size="16:9", image_size="2K",
                                     model="gpt-image-2.5-sunburst", image=uri)
        self.assertEqual(paths, ["/p/3.png"])
        payload = mh.call_args_list[0][0][2]
        self.assertEqual(payload["image"], [uri])                  # 参考图数组（中继透传 image[]）
        self.assertEqual(payload["model"], "gpt-image-2.5-sunburst")
        self.assertEqual(payload["prompt"], "改成赛博朋克风")
        self.assertEqual(payload["size"], "16:9")
        self.assertEqual(payload["image_size"], "2K")

    def test_open_i2i_multi_ref_list(self):
        """多参考图（≤ image_refs=2）：适配器原样转 data URI 数组（截断由协商层负责）。"""
        uris = ["data:image/png;base64,aa", "data:image/png;base64,bb"]
        with mock.patch.object(self.ad, "_http") as mh, \
             mock.patch.object(self.ad, "_save", return_value="/p/5.png"):
            mh.return_value = (200, {"data": [{"b64_json": "aGk="}]})
            self.ad.generate("融合两种风格", image=uris)
        self.assertEqual(mh.call_args_list[0][0][2]["image"], uris)

    def test_gemini_i2i_inline_parts(self):
        """gemini 协议图生图：文本在前 + inline_data 参考图 + 主力模型缺省 + imageConfig。"""
        self.rec["protocol"] = "gemini"
        uri = "data:image/png;base64,aGk="
        with mock.patch.object(self.ad, "_http") as mh, \
             mock.patch.object(self.ad, "_save", return_value="/p/4.png"):
            mh.return_value = (200, {"candidates": [{"content": {"parts": [
                {"inlineData": {"mimeType": "image/png", "data": "aGk="}}]}}]})
            paths = self.ad.generate("改成水彩", size="9:16", image_size="4K", image=uri)
        self.assertEqual(paths, ["/p/4.png"])
        url = mh.call_args_list[0][0][1]
        self.assertIn(":generateContent", url)
        self.assertIn("gemini-nano-banana-2.1", url)               # 主力模型缺省
        payload = mh.call_args_list[0][0][2]
        parts = payload["contents"][0]["parts"]
        self.assertEqual(parts[0], {"text": "改成水彩"})            # 提示词在前
        self.assertEqual(parts[1], {"inlineData": {"mimeType": "image/png",
                                                    "data": "aGk="}})   # 参考图随行（官方规范字段名）
        ic = payload["generationConfig"]["imageConfig"]
        self.assertEqual(ic["aspectRatio"], "9:16")
        self.assertEqual(ic["imageSize"], "4K")

    def test_translate_kwargs_mapping(self):
        """params.translate（缺省翻译器）→ 适配器 kwargs 全参数映射（ratio→size、tier→image_size）。"""
        from core import params
        clean = {"action": "generate", "prompt": "猫", "image": "data:image/png;base64,aa",
                 "ratio": "16:9", "tier": "2K", "model": "gpt-image-2.5-sunburst"}
        with mock.patch.object(params, "get_channel",
                               return_value={"id": "u1", "module": self.ad}):
            kw = params.translate("u1", clean)
        self.assertEqual(kw["prompt"], "猫")
        self.assertEqual(kw["image"], "data:image/png;base64,aa")  # i2i 透传不被剔除（i2i=True）
        self.assertEqual(kw["size"], "16:9")
        self.assertEqual(kw["image_size"], "2K")
        self.assertEqual(kw["model"], "gpt-image-2.5-sunburst")

    def test_open_official_params_passthrough(self):
        """GPT Image 2.5 官方生成参数经 options 白名单并入 payload（未传不造参）。"""
        with mock.patch.object(self.ad, "_http") as mh, \
             mock.patch.object(self.ad, "_save", return_value="/p/6.png"):
            mh.return_value = (200, {"data": [{"b64_json": "aGk="}]})
            self.ad.generate("猫", quality="xhigh", background="transparent",
                             output_format="webp")
        p = mh.call_args_list[0][0][2]
        self.assertEqual(p["quality"], "xhigh")
        self.assertEqual(p["background"], "transparent")
        self.assertEqual(p["output_format"], "webp")
        self.assertNotIn("moderation", p)

    def test_n_passthrough_open(self):
        """open 协议 n 透传（CAPS n=True，官方 generations 原生支持）。"""
        with mock.patch.object(self.ad, "_http") as mh, \
             mock.patch.object(self.ad, "_save", return_value="/p/7.png"):
            mh.return_value = (200, {"data": [{"b64_json": "aGk="}]})
            self.ad.generate("猫", n=3)
        self.assertEqual(mh.call_args_list[0][0][2]["n"], 3)

    def test_translate_options_passthrough(self):
        """options 经适配器 translate 官方白名单并入 kwargs（core 不再代传）（quality 等）。"""
        from core import params
        clean = {"action": "generate", "prompt": "猫", "options": {"quality": "max"}}
        with mock.patch.object(params, "get_channel",
                               return_value={"id": "u1", "module": self.ad}):
            kw = params.translate("u1", clean)
        self.assertEqual(kw["quality"], "max")

    def test_validate_key_zero_cost(self):
        with mock.patch.object(self.ad, "_http", return_value=(200, {"data": []})):
            self.assertTrue(self.ad.validate_key("sk-x")["valid"])      # 200=有效
        with mock.patch.object(self.ad, "_http", return_value=(401, "bad key")):
            self.assertFalse(self.ad.validate_key("sk-x")["valid"])     # 401=无效
        with mock.patch.object(self.ad, "_http", return_value=(None, None)):
            self.assertFalse(self.ad.validate_key("sk-x")["valid"])     # 不可达一律无效（用户裁定）


class TestCredentialRoute(unittest.TestCase):
    """凭证统一入口回归：新增/编辑自定义通道的 Key 一律经 credcenter.commit 路由（mock，不触网）。"""

    @staticmethod
    def _handler(path, body):
        from core import server
        h = server.Handler.__new__(server.Handler)
        h.path = path
        h._body = lambda: body
        h._json = lambda code, obj: {"code": code, "obj": obj}
        return h

    def test_create_routes_key_via_commit(self):
        from core import credcenter, registry, server, store
        with mock.patch.object(cc, "add", return_value={"ok": True, "id": "u1"}), \
             mock.patch.object(registry, "reload"), \
             mock.patch.object(store, "set_key") as sk, \
             mock.patch.object(credcenter, "commit", return_value={"valid": True, "message": "有效"}) as mc:
            r = self._handler("/api/channels/custom", {"name": "n", "protocol": "open",
                                                       "base_url": "https://x.com", "key": "sk-1"}).do_POST()
        mc.assert_called_once_with("u1", "sk-1")   # Key 只经统一入口落盘+验证
        sk.assert_not_called()                     # 端点不得绕过 commit 直写 store
        self.assertTrue(r["obj"]["ok"])

    def test_create_empty_key_rejected(self):
        from core import credcenter, registry
        with mock.patch.object(cc, "add"), mock.patch.object(registry, "reload"), \
             mock.patch.object(credcenter, "commit") as mc:
            r = self._handler("/api/channels/custom", {"name": "n", "protocol": "open",
                                                       "base_url": "https://x.com", "key": " "}).do_POST()
        mc.assert_not_called()
        self.assertEqual(r["code"], 400)

    def test_edit_with_key_routes_via_commit(self):
        from core import credcenter, registry
        with mock.patch.object(cc, "edit", return_value={"ok": True, "id": "u1"}), \
             mock.patch.object(registry, "reload"), \
             mock.patch.object(credcenter, "commit", return_value={"valid": True, "message": "有效"}) as mc:
            r = self._handler("/api/channels/custom/edit", {"id": "u1", "name": "n", "protocol": "open",
                                                            "base_url": "https://x.com", "key": "sk-2"}).do_POST()
        mc.assert_called_once_with("u1", "sk-2")   # 编辑改 Key → 与新增同一条 commit 路径
        self.assertTrue(r["obj"]["ok"])

    def test_edit_without_key_reverify_only(self):
        """未提交 key（仅改元数据的调用方）→ 只重验，绝不动凭证。"""
        from core import credcenter, registry
        with mock.patch.object(cc, "edit", return_value={"ok": True, "id": "u1"}), \
             mock.patch.object(registry, "reload"), \
             mock.patch.object(credcenter, "commit", return_value={"valid": True, "message": "有效"}) as mc:
            self._handler("/api/channels/custom/edit", {"id": "u1"}).do_POST()
        mc.assert_called_once_with("u1")

    def test_edit_empty_key_clears_via_commit(self):
        from core import credcenter, registry
        with mock.patch.object(cc, "edit", return_value={"ok": True, "id": "u1"}), \
             mock.patch.object(registry, "reload"), \
             mock.patch.object(credcenter, "commit",
                               return_value={"ok": True, "valid": False, "message": "无凭证"}) as mc:
            r = self._handler("/api/channels/custom/edit", {"id": "u1", "key": ""}).do_POST()
        mc.assert_called_once_with("u1", "")       # 空串 → commit 内部 clear_key（与卡片「清空」同源）
        self.assertFalse(r["obj"]["valid"])


if __name__ == "__main__":
    unittest.main()

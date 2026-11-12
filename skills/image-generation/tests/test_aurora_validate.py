# -*- coding: utf-8 -*-
"""aurora validate_key 单元测试（mock 网络，零触网）。

背景回归：rightapi 对 GET /v1/tasks（列表）做鉴权后路由级关闭——有效 Key 收到
403「暂不支持该接口，平台无法对其计费」，曾致一切 Key 被误判无效。
修复后探针走 GET /v1/tasks/{假任务号}（详情路由）：401/403=无效、404/200=有效、
平台限制型 403 与网络不可达=放行。

运行（技能根目录）：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "channels", "aurora"))

import base as aurora_base  # noqa: E402

BLOCKED = {"error": "暂不支持该接口，平台无法对其计费"}
AUTH_401 = {"error": "无效的API Key"}


class TestAuroraValidateKey(unittest.TestCase):
    def _probe(self, st, resp):
        client = aurora_base.BaseClient(api_key="k")
        with mock.patch.object(aurora_base.BaseClient, "_get_task",
                               return_value=(st, resp)) as m:
            ok = client.validate_key("k")
        args, kwargs = m.call_args
        return ok, args

    def test_valid_key_404_task_not_found(self):
        ok, args = self._probe(404, {"error": "task not found"})
        self.assertTrue(ok)
        self.assertEqual(args[0], aurora_base.BaseClient.PROBE_TASK_ID)

    def test_valid_key_200(self):
        self.assertTrue(self._probe(200, {"tasks": []})[0])

    def test_invalid_key_401(self):
        ok, _ = self._probe(401, AUTH_401)
        self.assertFalse(ok)

    def test_invalid_key_403_auth(self):
        ok, _ = self._probe(403, {"error": "forbidden"})
        self.assertFalse(ok)

    def test_platform_blocked_403_passes(self):
        # 平台路由限制型 403（与 Key 无关）→ 放行，不得误判无效
        ok, _ = self._probe(403, BLOCKED)
        self.assertTrue(ok)

    def test_platform_blocked_403_str_body(self):
        ok, _ = self._probe(403, "暂不支持该接口，平台无法对其计费")
        self.assertTrue(ok)

    def test_network_unreachable_passes(self):
        ok, _ = self._probe(None, None)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()

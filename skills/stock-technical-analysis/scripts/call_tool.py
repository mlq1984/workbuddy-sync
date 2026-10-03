"""调用选股魔方 REST Skill 工具。"""

import argparse
import json
import os
import sys
from typing import Any, Dict, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import auth

SKILL_BASE = os.environ.get("XGMF_SKILL_BASE", "https://appmcp.abctougu.cn").rstrip("/")


def _post_tool(token: str, tool: str, arguments: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    request = Request(
        SKILL_BASE + "/skill/v1/tools/call",
        data=json.dumps({"tool": tool, "arguments": arguments}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, {"error": "http_error", "error_description": body[:300]}


def _parse_arguments(raw: str) -> Dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--arguments 必须是 JSON 对象")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--arguments", default="{}")
    options = parser.parse_args()
    try:
        arguments = _parse_arguments(options.arguments)
    except (ValueError, json.JSONDecodeError) as error:
        print(f"参数错误: {error}", file=sys.stderr)
        return 1

    auth_result = auth.ensure_auth()
    if auth_result.get("status") != auth.AUTH_OK:
        return auth.print_auth_result(auth_result)

    try:
        status, body = _post_tool(auth_result["token"], options.tool, arguments)
    except (OSError, URLError) as error:
        print(f"网络错误: {error}", file=sys.stderr)
        return 2

    if status == 401:
        if auth_result.get("source") == "environment":
            print("XGMF_ACCESS_TOKEN 已失效，请清除该环境变量后重试。", file=sys.stderr)
            return 2
        auth.clear_file_credentials()
        return auth.print_auth_result(auth.ensure_auth())
    if status >= 400:
        print(json.dumps(body, ensure_ascii=False), file=sys.stderr)
        return 2 if status >= 500 else 1

    print(json.dumps(body, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

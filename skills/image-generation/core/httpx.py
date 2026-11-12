# -*- coding: utf-8 -*-
"""公共 HTTP 机制层：统一执行器 + 重试退避（纯机制，零服务商知识）。

判定标准：换一家生图服务商仍成立的能力才放这里；端点、参数、模型、降级等
策略全部由调用方（通道）决定，本层不内置任何通道语义。

- http_json(...)  ：JSON API 统一执行器，返回 (status, payload)；status 为 int 或 "ERR"
- fetch_bytes(...)：二进制下载（图片产物等），失败抛异常，降级语义由调用方决定
- is_transient(s) ：默认"瞬时失败"判定（网络异常 / 429 / 503 / 5xx）
"""
import json
import time
import urllib.error
import urllib.request

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def is_transient(status) -> bool:
    """默认瞬时失败判定：网络异常 / 429 / 503 / 5xx —— 只有这类才值得重试。"""
    if status == "ERR":
        return True
    return isinstance(status, int) and (status in (429, 503) or 500 <= status < 600)


def _build(method, url, data, token, user_agent, extra_headers):
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("User-Agent", user_agent or DEFAULT_UA)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    return req


def _read(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def http_json(method, url, body=None, token=None, user_agent=None,
              extra_headers=None, timeout=30, retries=0, backoff=1.0,
              retry_if=None, connection_close=False):
    """统一 JSON 执行器。返回 (status:int|"ERR", payload:dict|str)。

    retries   额外重试次数（总尝试 = retries + 1），仅对瞬时失败生效
    backoff   首次退避秒数，按 2^n 指数递增
    retry_if  自定义判定 fn(status, payload) -> bool；缺省用 is_transient(status)
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    if connection_close:
        extra_headers = dict(extra_headers or {}, **{"Connection": "close"})
    for attempt in range(retries + 1):
        req = _build(method, url, data, token, user_agent, extra_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, payload = r.status, _read(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            status, payload = e.code, _read(e.read().decode("utf-8", "replace"))
        except Exception as e:  # 网络不可达 / SSL 重置等
            status, payload = "ERR", str(e)
        if status == 200:
            return status, payload
        if attempt < retries and (
                retry_if(status, payload) if retry_if else is_transient(status)):
            time.sleep(backoff * (2 ** attempt))
            continue
        return status, payload
    return ("ERR", "no attempt")


def fetch_bytes(url, token=None, user_agent=None, extra_headers=None,
                timeout=120, retries=0, backoff=1.0):
    """二进制下载（图片产物等）。返回 bytes；失败抛 RuntimeError（降级/重试语义由调用方决定）。"""
    last = None
    for attempt in range(retries + 1):
        req = _build("GET", url, None, token, user_agent, extra_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(backoff * (2 ** attempt))
    raise RuntimeError("下载失败: %s" % last)


# 内置凭证层 master 分片 B（完整密钥 = A+C+B 三分片运行时拼接，散布于 common/httpx/builtin，见 core/builtin.py）
_BUILTIN_KS_B = "ec207f258015505697a5288c7c99cb71f8e557dc5552cd54"

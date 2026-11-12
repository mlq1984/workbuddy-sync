# -*- coding: utf-8 -*-
"""内置凭证层（发行方资产，通道中心统一管理）。

- 内置 Key 以密文常量随技能分发；明文仅在内存（解密后缓存），不落盘、不入日志；
- keystream = SHA256(master分片 + salt + cid) 循环扩展，密文 = base85(XOR)；
- master 三分片散布（common/httpx/本模块），任何单文件都拼不出完整密钥；
- 使用方：core.credprovider（统一取钥匙入口）；本模块不提供明文导出接口。
"""
import base64
import hashlib

from .common import _BUILTIN_KS_A     # master 分片 A（core/common.py）
from .httpx import _BUILTIN_KS_B      # master 分片 B（core/httpx.py）

_BUILTIN_KS_C = "2b804e29ccc2d530decb6707e351310218100cb301e314c2"

_SALT = {'agnes': 'a7ec749eb16b282b875193d3', 'shangtang': '079791929ffbbd2d33a5c95c', 'cloudflare': '917441603803e8400fea42db', 'zhipu': 'dd20ad44bd9fd31602fc29b8'}
_BLOB = {
    "agnes": "GgeAy<yqVF`5a1OcO8x16GRzgz|6CdPZ8b@qit#+KjfaJC4p;*u7mKhM+93@n4HA",
    "shangtang": "5Bk^BA)R;7^3!EiEn54yQ{XH8J>5q8w1Y>`f6kuFa2Ze",
    "cloudflare": "pCA2>JGf#}j3kdqRXo&}*R9%uSz4#_6?$a*u_V~%r<g_jsJieSro7;97L^lF%IVr9>RdB;R_mrhogkfl8n++Xwy;5<%6Ros?+)z}dOxr>LZk",
    "zhipu": "^(kQ2wW|D^wAVkC2=G2H15^csO|D3w?B{(tb+sXljmfzxoGXuiT0C1JPZQh1g8",
}

_cache = {}


def _keystream(seed: bytes, n: int) -> bytes:
    out, i = b"", 0
    while len(out) < n:
        out += hashlib.sha256(seed + i.to_bytes(4, "big")).digest()
        i += 1
    return out[:n]


def has(cid: str) -> bool:
    """该通道是否有内置凭证（不涉及解密）。"""
    return cid in _BLOB


def get(cid: str) -> "str | None":
    """解密内置 Key（仅内存，进程内缓存）；无内置返回 None。"""
    if cid in _cache:
        return _cache[cid]
    blob = _BLOB.get(cid)
    if not blob:
        return None
    seed = hashlib.sha256("|".join((
        _BUILTIN_KS_A, _BUILTIN_KS_C, _BUILTIN_KS_B, _SALT[cid], cid)).encode()).digest()
    raw = base64.b85decode(blob)
    key = bytes(a ^ b for a, b in zip(raw, _keystream(seed, len(raw)))).decode("utf-8")
    _cache[cid] = key
    return key

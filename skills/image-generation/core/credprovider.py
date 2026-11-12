# -*- coding: utf-8 -*-
"""凭证提供层（统一取钥匙入口，L1.5）。

层级与优先级：
  ① 用户落盘（core.store，用户自己的 Key，原逻辑完全不变）——优先；
  ② 内置层（core.builtin，发行方兜底，密文随技能分发、内存解密）——其次；
  ③ 都没有 → fallback（可调用）。

使用规范：
- generate/upscale/validate 等"这把通道现在用哪把钥匙"的调用，一律走本层 resolve；
- UI 回填（输入框显示）只允许用 store.get_key——内置 Key 永不回显、不经任何接口下发；
- agent/外部调用方只能经编排器 API 使用生图能力，无法取到任何形态的 Key。
"""
from . import builtin, store


def resolve(channel_id: str, fallback=None):
    """取钥匙：用户 Key 优先 → 用户 Key 已知失效时内置兜底 → 内置 → fallback。

    "失效"以验证状态为准（凭据段 state=invalid 且存在内置），零额外网络开销；
    用户 Key 有效或未验证时原样返回（不误伤）。
    """
    k = store.get_key(channel_id)
    if k:
        st = store.get_status(channel_id)
        if st.get("state") == "invalid" and builtin.has(channel_id):
            b = builtin.get(channel_id)
            if b:
                return b                    # 用户 Key 已知失效 → 内置兜底
        return k
    b = builtin.get(channel_id)
    if b:
        return b
    return fallback() if callable(fallback) else fallback

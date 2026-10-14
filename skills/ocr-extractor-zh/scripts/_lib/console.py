"""让 stdout / stderr 按 UTF-8 输出。

为什么必须有这个模块（真实故障）：
Windows 上当 stdout 被**管道或文件捕获**时（CI、GUI、`| findstr`、重定向到文件），
Python 不会走控制台的 UTF-16 写入路径，而是用 ANSI 代码页（简体中文系统 cp936、
英文系统 cp1252）编码，遇到非 ASCII 字符直接抛：

    UnicodeEncodeError: 'charmap' codec can't encode characters in position 0-1:
                        character maps to <undefined>

本项目所有技能与工具都会输出中文回执，所以在 Windows 管道场景下**必然**触发。
实测证据：CI 在 windows-latest 上执行 `_tools/sync_lib.py` 时即因此失败，
而该步骤之后的所有检查（测试、双渠道校验、Windows 静态审计）全部没机会执行。

两层防护：
1. 环境变量 `PYTHONIOENCODING=utf-8`（启动器 / CI / build.sh 里设置）；
2. 本模块在进程启动阶段直接改绑标准流 —— 这样即使用户绕开启动器、
   直接 `python scripts/xxx.py`，或在没有环境变量的沙箱里执行，也不会炸。

只用标准库，兼容 Python 3.9+（`reconfigure` 自 3.7 起提供；更老的解释器走兜底分支）。
"""
from __future__ import annotations

import io
import sys


def force_utf8_streams():
    # type: () -> bool
    """把 stdout / stderr 改绑为 UTF-8。返回是否成功改绑（失败不抛异常）。

    幂等、可重复调用。在没有标准流的环境（pythonw、某些嵌入宿主）下静默跳过。
    """
    if getattr(force_utf8_streams, "_done", False):
        return True

    changed = False
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                # line_buffering=True：管道场景下也能按行及时刷出，便于实时看进度
                reconfigure(encoding="utf-8", errors="backslashreplace", line_buffering=True)
                changed = True
                continue
            except (ValueError, OSError, AttributeError):
                pass  # 已被 detach 或不是可重配的流，走下面的兜底
        # 兜底：重新包一层 UTF-8 的 TextIOWrapper
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            try:
                setattr(sys, name, io.TextIOWrapper(buffer, encoding="utf-8",
                                                    errors="backslashreplace",
                                                    line_buffering=True))
                changed = True
            except (ValueError, OSError):
                pass

    force_utf8_streams._done = changed or True  # 即使没改成功也不重复尝试
    return changed


def describe_streams():
    # type: () -> dict
    """诊断用：报告标准流当前的编码（CI 排查时会很有用）。"""
    out = {}
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        out[name] = {
            "encoding": getattr(stream, "encoding", None),
            "errors": getattr(stream, "errors", None),
            "isatty": bool(getattr(stream, "isatty", lambda: False)()),
            "hasBuffer": hasattr(stream, "buffer"),
        }
    return out

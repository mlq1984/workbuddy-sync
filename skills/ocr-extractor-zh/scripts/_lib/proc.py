r"""跨平台子进程调用（Windows / macOS / Linux 行为一致）。

设计要点（踩过的坑）：
1. **永远传 argv 列表、``shell=False``**：带空格的路径（``C:\\Program Files\\...``）
   在 Windows 上若走 shell 会被拆词，列表传参不受影响。
2. **永远显式 ``encoding="utf-8"``，并用 ``backslashreplace`` 容错**：
   Windows 默认代码页是 GBK/CP936，外部工具（ffmpeg / tesseract / soffice）的输出
   可能混有 UTF-8 与本机代码页，不指定编码会让 ``text=True`` 直接抛 UnicodeDecodeError。
   容错策略用 ``backslashreplace`` 而不是 ``replace``：错误信息里的原始字节会被转成
   ``\xNN`` 保留下来，而不是变成一串 ``?`` —— 诊断 FFmpeg/LibreOffice 报错时这点很重要。
3. **不用 ``os.system`` / ``shell=True``**：避免注入与平台差异。
4. ``CREATE_NO_WINDOW``：Windows 上不弹黑框（GUI 场景必须）。
"""
from __future__ import annotations

import subprocess
import sys
import time
from typing import List, Optional, Sequence

# Windows: 不给子进程开控制台窗口。其它平台该常量不存在。
_CREATE_NO_WINDOW = 0x08000000

# 大输出上限，防止 --version 之类意外刷屏
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


class ProcResult:
    """一次子进程调用的结果（结构化，便于 JSON 回执与测试断言）。"""

    def __init__(self, argv, returncode, stdout, stderr, duration_ms, error=None):
        # type: (Sequence[str], int, str, str, int, Optional[str]) -> None
        self.argv = list(argv)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.duration_ms = duration_ms
        self.error = error  # 启动失败时的原因（如 FileNotFoundError）

    @property
    def ok(self):
        # type: () -> bool
        return self.returncode == 0 and self.error is None

    @property
    def command(self):
        # type: () -> str
        """可读命令回显；含空格的参数加引号，方便用户复制到终端复现。"""
        return " ".join(_quote(a) for a in self.argv)

    def as_dict(self):
        # type: () -> dict
        out = {
            "command": self.command,
            "returncode": self.returncode,
            "durationMs": self.duration_ms,
        }
        if self.error:
            out["error"] = self.error
        return out

    def tail(self, n=2000):
        # type: (int) -> str
        """stderr 尾部片段，用于失败时报错。"""
        text = (self.stderr or "").strip() or (self.stdout or "").strip()
        return text[-n:]


def _quote(arg):
    # type: (str) -> str
    if arg == "" or any(c in arg for c in ' \t"\'\\'):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg


def _popen_kwargs():
    # type: () -> dict
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return kwargs


def run(argv, timeout=600):
    # type: (Sequence[str], int) -> ProcResult
    """执行命令并把 stdout/stderr 当 UTF-8 文本返回。永不抛异常，失败进 ProcResult。"""
    started = time.time()
    argv = [str(a) for a in argv]
    try:
        proc = subprocess.run(
            argv,
            encoding="utf-8",
            errors="backslashreplace",
            timeout=timeout,
            **_popen_kwargs()
        )
    except FileNotFoundError:
        return ProcResult(argv, 127, "", "", _ms(started), "命令不存在: %s" % argv[0])
    except PermissionError:
        return ProcResult(argv, 126, "", "", _ms(started), "没有执行权限: %s" % argv[0])
    except subprocess.TimeoutExpired:
        return ProcResult(argv, 124, "", "", _ms(started), "超时（%ss）" % timeout)
    except OSError as exc:
        return ProcResult(argv, 125, "", "", _ms(started), "启动失败: %s" % exc)

    stdout = _truncate(proc.stdout)
    stderr = _truncate(proc.stderr)
    return ProcResult(argv, proc.returncode, stdout, stderr, _ms(started))


def run_bytes(argv, timeout=600, stdin_bytes=None):
    # type: (Sequence[str], int, Optional[bytes]) -> ProcResult
    """按字节捕获输出（用于二进制管道，如 ffmpeg 写 stdout）。

    失败同样不抛异常，bytes 结果放在 stdout/stderr 上（已按 latin-1 无损转成 str 容器）。
    """
    started = time.time()
    argv = [str(a) for a in argv]
    kwargs = _popen_kwargs()
    kwargs["stdin"] = subprocess.PIPE
    try:
        proc = subprocess.run(
            argv,
            input=stdin_bytes if stdin_bytes is not None else b"",
            timeout=timeout,
            **kwargs
        )
    except subprocess.TimeoutExpired:
        return _BytesResult(argv, 124, b"", b"", _ms(started), "超时（%ss）" % timeout)
    except OSError as exc:
        return _BytesResult(argv, 127, b"", b"", _ms(started), str(exc))
    return _BytesResult(argv, proc.returncode, proc.stdout or b"", proc.stderr or b"", _ms(started))


class _BytesResult(ProcResult):
    def __init__(self, argv, returncode, out_b, err_b, duration_ms, error=None):
        super(_BytesResult, self).__init__(
            argv,
            returncode,
            out_b.decode("utf-8", "replace"),
            err_b.decode("utf-8", "replace"),
            duration_ms,
            error,
        )
        self.out_bytes = out_b
        self.err_bytes = err_b


def _ms(started):
    # type: (float) -> int
    return int((time.time() - started) * 1000)


def _truncate(text):
    # type: (Optional[str]) -> str
    text = text or ""
    if len(text) > MAX_OUTPUT_BYTES:
        return text[:MAX_OUTPUT_BYTES] + "\n...[输出已截断]"
    return text


def probe_command(argv, timeout=20):
    # type: (Sequence[str], int) -> Optional[str]
    """跑一次 ``--version`` 之类的探测，成功返回首行版本串，失败返回 None。"""
    res = run(argv, timeout=timeout)
    if not res.ok:
        return None
    for line in (res.stdout or "").splitlines():
        line = line.strip()
        if line:
            return line[:200]
    first = (res.stderr or "").strip().splitlines()
    return first[0][:200] if first else ""


def run_list(argv, timeout=600):
    # type: (Sequence[str], int) -> List[str]
    """执行命令并返回非空输出行（跨平台统一换行处理）。"""
    res = run(argv, timeout=timeout)
    if not res.ok:
        return []
    raw = (res.stdout or "").replace("\r\n", "\n").replace("\r", "\n")
    return [ln.strip() for ln in raw.split("\n") if ln.strip()]

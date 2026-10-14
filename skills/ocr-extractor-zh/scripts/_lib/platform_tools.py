"""外部工具发现层：同一套 API 覆盖 macOS / Windows / Linux。

为什么需要这一层（而不是直接用 shutil.which）：
- GUI 应用启动时 PATH 往往**不继承**用户 shell 的 PATH：macOS 上 Homebrew 的
  ``/opt/homebrew/bin`` 可能不在；Windows 上 ``C:\\ffmpeg\\bin`` 通常只在用户 PATH 里。
  只查 PATH ⟹ 「我明明装了却检测不到」。
- 所以顺序是：显式 override → PATH → 平台候选路径 → Windows 注册表 → 全盘常见位置。

所有探测都不依赖第三方库，Python 3.9 可跑。
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Dict, List, Optional, Sequence

PLATFORMS = ("darwin", "win32", "linux")


def current_platform():
    # type: () -> str
    """归一化平台名：``darwin`` / ``win32`` / ``linux``。"""
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


class Tool:
    """一个外部工具的发现结果。"""

    def __init__(self, key, path=None, source=None, version=None, hints=None):
        # type: (str, Optional[str], Optional[str], Optional[str], Optional[Dict[str, str]]) -> None
        self.key = key
        self.path = path
        self.source = source  # override / path / candidate / registry / setup
        self.version = version
        self.hints = hints or {}  # platform -> 安装指引

    @property
    def found(self):
        # type: () -> bool
        return bool(self.path)

    def as_dict(self):
        # type: () -> dict
        out = {"tool": self.key, "found": self.found}
        if self.path:
            out["path"] = self.path
            out["source"] = self.source
        if self.version:
            out["version"] = self.version
        if not self.found:
            out["install"] = {p: self.hints.get(p, "") for p in PLATFORMS if self.hints.get(p)}
        return out

    def install_hint(self, platform=None):
        # type: (Optional[str]) -> str
        return self.hints.get(platform or current_platform(), "")


# --------------------------------------------------------------------------
# 候选路径表
# --------------------------------------------------------------------------

def _env_paths():
    # type: () -> Dict[str, str]
    """把 Windows 上带括号的环境变量安全取出来（``%ProgramFiles(x86)%`` 不能直接 os.environ[]）。"""
    out = {}
    for name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA", "APPDATA", "SystemRoot"):
        val = os.environ.get(name)
        if val:
            out[name] = val
    return out


def _candidates(key, platform):
    # type: (str, str) -> List[str]
    """按平台给出候选绝对路径（不含 PATH 查找，PATH 由 shutil.which 负责）。"""
    env = _env_paths()
    pf = env.get("ProgramFiles", r"C:\Program Files")
    pf86 = env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = env.get("LOCALAPPDATA", "")
    sysroot = env.get("SystemRoot", r"C:\Windows")

    if platform == "darwin":
        table = {
            "ffmpeg": ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/local/bin/ffmpeg"],
            "ffprobe": ["/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe", "/opt/local/bin/ffprobe"],
            "soffice": [
                "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                "/opt/homebrew/bin/soffice",
                "/usr/local/bin/soffice",
            ],
            "pandoc": ["/opt/homebrew/bin/pandoc", "/usr/local/bin/pandoc"],
            "tesseract": ["/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/opt/local/bin/tesseract"],
            "osascript": ["/usr/bin/osascript"],
        }
    elif platform == "win32":
        table = {
            "ffmpeg": [
                r"C:\ffmpeg\bin\ffmpeg.exe",
                os.path.join(pf, "ffmpeg", "bin", "ffmpeg.exe"),
                os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe") if local else "",
                r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
                os.path.join(local, "scoop", "shims", "ffmpeg.exe") if local else "",
            ],
            "ffprobe": [
                r"C:\ffmpeg\bin\ffprobe.exe",
                os.path.join(pf, "ffmpeg", "bin", "ffprobe.exe"),
                os.path.join(local, "Microsoft", "WinGet", "Links", "ffprobe.exe") if local else "",
                r"C:\ProgramData\chocolatey\bin\ffprobe.exe",
                os.path.join(local, "scoop", "shims", "ffprobe.exe") if local else "",
            ],
            # soffice.com 是控制台版（能拿到 stdout），优先于 soffice.exe
            "soffice": [
                os.path.join(pf, "LibreOffice", "program", "soffice.com"),
                os.path.join(pf, "LibreOffice", "program", "soffice.exe"),
                os.path.join(pf86, "LibreOffice", "program", "soffice.com"),
                os.path.join(pf86, "LibreOffice", "program", "soffice.exe"),
            ],
            "pandoc": [
                os.path.join(pf, "Pandoc", "pandoc.exe"),
                os.path.join(local, "Pandoc", "pandoc.exe") if local else "",
                os.path.join(local, "Microsoft", "WinGet", "Links", "pandoc.exe") if local else "",
                r"C:\ProgramData\chocolatey\bin\pandoc.exe",
            ],
            "tesseract": [
                os.path.join(pf, "Tesseract-OCR", "tesseract.exe"),
                os.path.join(pf86, "Tesseract-OCR", "tesseract.exe"),
                os.path.join(local, "Programs", "Tesseract-OCR", "tesseract.exe") if local else "",
                os.path.join(local, "Tesseract-OCR", "tesseract.exe") if local else "",
            ],
            "powershell": [
                os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
            ],
            "winword": [
                os.path.join(pf, "Microsoft Office", "root", "Office16", "WINWORD.EXE"),
                os.path.join(pf86, "Microsoft Office", "root", "Office16", "WINWORD.EXE"),
                os.path.join(pf, "Microsoft Office", "Office16", "WINWORD.EXE"),
            ],
        }
    else:  # linux
        table = {
            "ffmpeg": ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/snap/bin/ffmpeg"],
            "ffprobe": ["/usr/bin/ffprobe", "/usr/local/bin/ffprobe"],
            "soffice": ["/usr/bin/soffice", "/usr/bin/libreoffice", "/usr/local/bin/soffice", "/snap/bin/libreoffice"],
            "pandoc": ["/usr/bin/pandoc", "/usr/local/bin/pandoc"],
            "tesseract": ["/usr/bin/tesseract", "/usr/local/bin/tesseract"],
        }
    return [p for p in table.get(key, []) if p]


# --------------------------------------------------------------------------
# Windows 注册表兜底
# --------------------------------------------------------------------------

_WIN_REGISTRY = {
    # key -> [(hive, subkey, value_name)]
    "soffice": [
        ("HKLM", r"SOFTWARE\LibreOffice", "Path"),
        ("HKLM", r"SOFTWARE\WOW6432Node\LibreOffice", "Path"),
    ],
    "ffmpeg": [("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\ffmpeg.exe", "")],
    "pandoc": [("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\pandoc.exe", "")],
    "tesseract": [("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\tesseract.exe", "")],
}


def _registry_lookup(key):
    # type: (str) -> Optional[str]
    """Windows 注册表兜底。非 Windows 或读不到都返回 None（绝不抛异常）。"""
    if current_platform() != "win32":
        return None
    try:
        import winreg  # type: ignore
    except ImportError:
        return None

    for hive_name, subkey, value_name in _WIN_REGISTRY.get(key, []):
        hive = getattr(winreg, hive_name, None)
        if hive is None:
            continue
        try:
            with winreg.OpenKey(hive, subkey) as handle:
                try:
                    raw, _ = winreg.QueryValueEx(handle, value_name)
                except FileNotFoundError:
                    continue
        except OSError:
            continue
        if not raw:
            continue
        candidate = _normalize_registry_path(key, str(raw))
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _normalize_registry_path(key, raw):
    # type: (str, str) -> str
    """注册表里的值可能是目录（LibreOffice 的 Path）也可能已是可执行文件路径。"""
    raw = raw.strip().strip('"')
    if os.path.isfile(raw):
        return raw
    exe_names = {
        "soffice": ["soffice.com", "soffice.exe", "program\\soffice.com", "program\\soffice.exe"],
        "ffmpeg": ["ffmpeg.exe", "bin\\ffmpeg.exe"],
        "pandoc": ["pandoc.exe"],
        "tesseract": ["tesseract.exe"],
    }
    for rel in exe_names.get(key, []):
        candidate = os.path.join(raw, rel.replace("/", os.sep))
        if os.path.isfile(candidate):
            return candidate
    return ""


# --------------------------------------------------------------------------
# 对外主入口
# --------------------------------------------------------------------------

def find_tool(key, override=None, platform=None, extra_candidates=None, version_argv=None):
    # type: (str, Optional[str], Optional[str], Optional[Sequence[str]], Optional[Sequence[str]]) -> Tool
    """定位一个外部工具。

    :param override: 用户显式指定的路径（``--ffmpeg`` / 环境变量），最高优先级
    :param platform: 注入平台（测试用；默认取当前平台）
    :param extra_candidates: 追加候选路径
    :param version_argv: 拿版本号的参数，默认 ``--version``
    """
    platform = platform or current_platform()
    hints = INSTALL_HINTS.get(key, {})
    version_argv = list(version_argv or ["--version"])

    # 1) 显式 override
    if override:
        if os.path.isfile(override) and os.access(override, os.X_OK):
            return Tool(key, override, "override", _version_of(override, version_argv), hints)
        resolved = shutil.which(override)
        if resolved:
            return Tool(key, resolved, "override", _version_of(resolved, version_argv), hints)
        return Tool(key, None, None, None, hints)

    # 2) PATH（Windows 上 shutil.which 会自动补 .exe/.cmd/.bat）
    resolved = shutil.which(key)
    if resolved:
        return Tool(key, resolved, "path", _version_of(resolved, version_argv), hints)

    # 3) 平台候选路径
    for candidate in list(_candidates(key, platform)) + list(extra_candidates or []):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return Tool(key, candidate, "candidate", _version_of(candidate, version_argv), hints)

    # 4) Windows 注册表
    if platform == "win32":
        from_registry = _registry_lookup(key)
        if from_registry:
            return Tool(key, from_registry, "registry", _version_of(from_registry, version_argv), hints)

    return Tool(key, None, None, None, hints)


def _version_of(path, version_argv):
    # type: (str, Sequence[str]) -> Optional[str]
    # 绝对导入而不是相对导入：_lib 是被逐个放进 sys.path 的普通目录（没有 __init__.py），
    # 相对导入会以 "attempted relative import with no known parent package" 失败。
    from proc import probe_command

    try:
        return probe_command([path] + list(version_argv), timeout=25)
    except Exception:  # 版本探测失败不影响「工具已找到」这个事实
        return None


INSTALL_HINTS = {
    # type: Dict[str, Dict[str, str]]
    "ffmpeg": {
        "darwin": "brew install ffmpeg（未装 Homebrew：https://brew.sh）",
        "win32": "winget install Gyan.FFmpeg  |  或 choco install ffmpeg  |  或到 ffmpeg.org 下载后把 bin 目录加进 PATH",
        "linux": "sudo apt install ffmpeg（Debian/Ubuntu）或 sudo dnf install ffmpeg（Fedora）",
    },
    "ffprobe": {
        "darwin": "随 ffmpeg 一起安装：brew install ffmpeg",
        "win32": "随 ffmpeg 一起安装：winget install Gyan.FFmpeg",
        "linux": "随 ffmpeg 一起安装：sudo apt install ffmpeg",
    },
    "soffice": {
        "darwin": "brew install --cask libreoffice  或到 libreoffice.org 下载拖进「应用程序」",
        "win32": "winget install TheDocumentFoundation.LibreOffice  |  或到 libreoffice.org 下载安装",
        "linux": "sudo apt install libreoffice",
    },
    "pandoc": {
        "darwin": "brew install pandoc",
        "win32": "winget install JohnMacFarlane.Pandoc  |  或 choco install pandoc",
        "linux": "sudo apt install pandoc",
    },
    "tesseract": {
        "darwin": "brew install tesseract tesseract-lang",
        "win32": "winget install UB-Mannheim.TesseractOCR  |  或 choco install tesseract",
        "linux": "sudo apt install tesseract-ocr tesseract-ocr-chi-sim",
    },
    "powershell": {
        "win32": "Windows 自带；若缺失说明系统被裁剪，请改用 tesseract 引擎（--engine tesseract）",
    },
}


def tool_report(keys, overrides=None, platform=None):
    # type: (Sequence[str], Optional[Dict[str, str]], Optional[str]) -> Dict[str, dict]
    """一次探测多个工具，返回可直接 JSON 序列化的报告。"""
    overrides = overrides or {}
    out = {}
    for key in keys:
        tool = find_tool(key, override=overrides.get(key), platform=platform)
        out[key] = tool.as_dict()
    return out


def capability_summary(platform=None):
    # type: () -> dict
    """给用户看的「这台机器现在能干什么」。"""
    platform = platform or current_platform()
    report = tool_report(["ffmpeg", "ffprobe", "soffice", "pandoc", "tesseract"], platform=platform)
    return {
        "platform": platform,
        "python": sys.version.split()[0],
        "tools": report,
    }

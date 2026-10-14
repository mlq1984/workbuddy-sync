"""OCR 引擎层：macOS Vision / Windows WinRT / Tesseract，统一成一个接口。

为什么是这三个引擎：
1. **macOS 系统 OCR**：用 ``osascript`` 的 ObjC 桥直调 ``Vision.framework``——
   零安装、零编译、离线（不需要 pyobjc，也不需要 swiftc）。
2. **Windows 系统 OCR**：用 PowerShell 调 ``Windows.Media.Ocr``——
   Windows 10/11 自带，零安装、离线（需已安装对应语言的 OCR 语言包）。
3. **Tesseract**：跨平台兜底；两平台都能装，也常用于 CI。

三者的输出统一成同一份 schema，所以**渲染层完全不知道下面是哪个引擎**，
md/HTML 产物在任何平台上形状一致。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

from platform_tools import current_platform, find_tool
from proc import run

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic", ".pdf")

VISION_LANGUAGES = ("zh-Hans", "zh-Hant", "en-US", "ja-JP", "ko-KR", "fr-FR", "de-DE", "es-ES", "ru-RU")


class OcrError(Exception):
    def __init__(self, message, missing_tool=None):
        # type: (str, Optional[str]) -> None
        super(OcrError, self).__init__(message)
        self.missing_tool = missing_tool


# ---------------------------------------------------------------------------
# 统一数据结构
# ---------------------------------------------------------------------------

class Line:
    def __init__(self, text, confidence=None, box=None, page=1, alternatives=None):
        # type: (str, Optional[float], Optional[List[float]], int, Optional[List[str]]) -> None
        self.text = text
        self.confidence = confidence  # 0~1；语义随引擎不同，见 OcrResult.meta
        self.box = box                # [x, y, w, h]，归一化 0~1（左上原点）
        self.page = page
        self.alternatives = alternatives or []  # 次选文本，供人工核对

    @property
    def uncertain(self):
        # type: () -> bool
        """是否需要人工核对：置信度低，或引擎给出了不同的次选文本。"""
        if self.alternatives:
            return True
        return self.confidence is not None and self.confidence < 0.75

    def as_dict(self):
        # type: () -> dict
        out = {"text": self.text, "page": self.page}  # type: Dict[str, Any]
        if self.confidence is not None:
            out["confidence"] = round(self.confidence, 4)
        if self.box:
            out["box"] = [round(v, 4) for v in self.box]
        if self.alternatives:
            out["alternatives"] = list(self.alternatives)
        return out


class OcrResult:
    def __init__(self, engine, lines, language=None, meta=None):
        # type: (str, List[Line], Optional[str], Optional[Dict[str, Any]]) -> None
        self.engine = engine
        self.lines = lines
        self.language = language
        self.meta = meta or {}

    @property
    def text(self):
        # type: () -> str
        return "\n".join(line.text for line in self.lines)

    @property
    def average_confidence(self):
        # type: () -> Optional[float]
        values = [line.confidence for line in self.lines if line.confidence is not None]
        if not values:
            return None
        return sum(values) / len(values)

    def as_dict(self):
        # type: () -> dict
        out = {"engine": self.engine, "lineCount": len(self.lines)}  # type: Dict[str, Any]
        if self.language:
            out["language"] = self.language
        average = self.average_confidence
        if average is not None:
            out["averageConfidence"] = round(average, 4)
        if self.meta:
            out["meta"] = self.meta
        out["lines"] = [line.as_dict() for line in self.lines]
        return out


# ---------------------------------------------------------------------------
# 引擎可用性
# ---------------------------------------------------------------------------

def available_engines(platform=None, tesseract_path=None):
    # type: (Optional[str], Optional[str]) -> Dict[str, dict]
    """探测三个引擎在这台机器上是否可用（含语言列表）。"""
    platform = platform or current_platform()
    report = {}  # type: Dict[str, dict]

    # macOS Vision：只要有 osascript 就能用（系统自带）
    osascript = shutil.which("osascript") if platform == "darwin" else None
    report["vision"] = {
        "name": "vision",
        "label": "macOS 系统 OCR（Vision.framework）",
        "available": bool(osascript),
        "path": osascript,
        "languages": list(VISION_LANGUAGES),
        "requiresInstall": False,
        "note": "系统自带，离线可用；通过 osascript 的 ObjC 桥调用，不需要 pyobjc/swiftc",
    }

    # Windows WinRT：poweshell + Windows.Media.Ocr
    pwsh = None  # type: Optional[str]
    if platform == "win32":
        pwsh = shutil.which("powershell") or shutil.which("pwsh")
        if not pwsh:
            tool = find_tool("powershell", platform=platform)
            pwsh = tool.path
    languages = []  # type: List[str]
    detail = ""
    if pwsh:
        languages, detail = _winrt_languages(pwsh)
    report["winrt"] = {
        "name": "winrt",
        "label": "Windows 系统 OCR（Windows.Media.Ocr）",
        "available": bool(pwsh) and bool(languages),
        "path": pwsh,
        "languages": languages,
        "requiresInstall": False,
        "note": "Windows 10/11 自带；需已安装 OCR 语言包（设置 → 时间和语言 → 语言）",
        "detail": detail,
    }

    # Tesseract：跨平台兜底
    tess = find_tool("tesseract", override=tesseract_path, platform=platform, version_argv=["--version"])
    tess_langs = _tesseract_languages(tess.path) if tess.found else []
    report["tesseract"] = {
        "name": "tesseract",
        "label": "Tesseract OCR",
        "available": tess.found,
        "path": tess.path,
        "version": tess.version,
        "languages": tess_langs,
        "requiresInstall": True,
        "install": {p: hint for p, hint in (tess.hints or {}).items()},
        "note": "跨平台兜底；中文需额外语言包（chi_sim / chi_tra）",
    }
    return report


def _winrt_languages(powershell):
    # type: (str) -> Tuple[List[str], str]
    """查询 Windows.Media.Ocr 已安装的 OCR 语言。"""
    script = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "try {\n"
        "  [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null\n"
        "  $langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages\n"
        "  $out = @()\n"
        "  foreach ($l in $langs) { $out += $l.LanguageTag }\n"
        "  Write-Output ('LANGS=' + ($out -join ','))\n"
        "} catch { Write-Output ('ERROR=' + $_.Exception.Message) }\n"
    )
    result = run(_powershell_argv(powershell, script), timeout=60)
    if not result.ok:
        return [], result.tail(200)
    for line in (result.stdout or "").splitlines():
        if line.startswith("LANGS="):
            raw = line[len("LANGS="):].strip()
            return [item for item in raw.split(",") if item], ""
        if line.startswith("ERROR="):
            return [], line[len("ERROR="):].strip()
    return [], (result.stdout or "").strip()[:200]


def _tesseract_languages(path):
    # type: (Optional[str]) -> List[str]
    if not path:
        return []
    result = run([path, "--list-langs"], timeout=60)
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    langs = []  # type: List[str]
    for line in text.splitlines():
        line = line.strip()
        if not line or " " in line or line.lower().startswith("list of"):
            continue
        langs.append(line)
    return langs


def _powershell_argv(powershell, script):
    # type: (str, str) -> List[str]
    """把脚本内容编码后传给 powershell，避免任何引号/换行/编码隐患。

    -EncodedCommand 接收 UTF-16LE + base64，是唯一在「路径带空格/非 ASCII」与
    「多行脚本」场景下都不会出问题的传参方式（这是 Windows 自动化的通用做法）。
    """
    import base64

    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [
        powershell,
        "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-EncodedCommand", encoded,
    ]


# ---------------------------------------------------------------------------
# macOS Vision
# ---------------------------------------------------------------------------

_VISION_SCRIPT = r"""
ObjC.import("Vision"); ObjC.import("Foundation"); ObjC.import("AppKit");

function run(argv) {
  const imagePath = argv[0];
  const langs = argv.length > 1 && argv[1] ? argv[1].split(",") : [];
  const url = $.NSURL.fileURLWithPath(imagePath);
  const req = $.VNRecognizeTextRequest.alloc.init;
  req.recognitionLevel = 1;              // 1 = accurate（0 是快速）
  if (langs.length) req.recognitionLanguages = langs;
  req.usesLanguageCorrection = true;

  const handler = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $());
  const ok = handler.performRequestsError($([req]), $());
  const out = [];
  const results = req.results;
  if (results) {
    const count = results.count;
    for (let i = 0; i < count; i++) {
      const obs = results.objectAtIndex(i);
      const cands = obs.topCandidates(3);
      const top = cands.objectAtIndex(0);
      // Vision 的 candidate.confidence 实测恒为 0.5（不随清晰度/语言变化），
      // 不是可用的置信度。真正有信息量的是「首选与次选的差异」——
      // 差异越大说明识别越确定。
      let separation = 1.0;
      if (cands.count > 1) {
        const second = ObjC.unwrap(cands.objectAtIndex(1).string);
        separation = (ObjC.unwrap(top.string) === second) ? 1.0 : 0.0;
      }
      const bb = obs.boundingBox;
      // Vision 的 boundingBox 原点在左下；换算成左上原点，与 WinRT/Tesseract 对齐
      out.push({
        text: ObjC.unwrap(top.string),
        separation: separation,
        alternative: cands.count > 1 ? ObjC.unwrap(cands.objectAtIndex(1).string) : "",
        x: bb.origin.x,
        y: 1 - (bb.origin.y + bb.size.height),
        w: bb.size.width,
        h: bb.size.height
      });
    }
  }
  return JSON.stringify(out);
}
"""


def run_vision(image_path, languages=None, platform=None):
    # type: (str, Optional[str], Optional[str]) -> OcrResult
    """用 macOS Vision 识别。"""
    platform = platform or current_platform()
    if platform != "darwin":
        raise OcrError("Vision 引擎只在 macOS 上可用（当前平台：%s）" % platform, missing_tool="vision")
    osascript = shutil.which("osascript")
    if not osascript:
        raise OcrError("找不到 osascript，无法调用系统 Vision OCR", missing_tool="vision")

    script_path = _write_temp_script(_VISION_SCRIPT, ".js")
    try:
        argv = [osascript, "-l", "JavaScript", script_path, os.path.abspath(image_path)]
        if languages:
            argv.append(languages)
        result = run(argv, timeout=300)
    finally:
        _safe_remove(script_path)

    if not result.ok:
        raise OcrError("Vision 识别失败：%s" % (result.tail(400) or "无输出"))
    payload = _parse_json_array(result.stdout) or []
    lines = []
    ambiguous = 0
    for item in payload:
        box = None
        if all(key in item for key in ("x", "y", "w", "h")):
            box = [item["x"], item["y"], item["w"], item["h"]]
        text = str(item.get("text", ""))
        # 只把「首选与次选文字不同」标为不确定；文字相同则视为确定
        alternatives = [item.get("alternative")] if item.get("alternative") else []
        confidence = None if item.get("separation") is None else _as_float(item.get("separation"))
        if confidence is not None and confidence < 0.5:
            ambiguous += 1
        lines.append(Line(text, confidence, box, alternatives=alternatives))
    return OcrResult("vision", lines, language=languages, meta={
        "enginePath": osascript,
        "recognizer": "VNRecognizeTextRequest(accurate)",
        "confidenceSemantics": "候选差异度（1=首选唯一，0=次选给出了不同文字）",
        "confidenceNote": "Vision 的 candidate.confidence 实测恒为 0.5，不可用作置信度；"
                          "这里改用「首选与次选是否一致」作为不确定信号",
        "ambiguousLines": ambiguous,
    })


# ---------------------------------------------------------------------------
# Windows WinRT
# ---------------------------------------------------------------------------

_WINRT_SCRIPT_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
# PS 5.1 重定向 stdout 时默认用控制台/OEM 代码页（cp936/cp1252），
# 而 Python 侧按 UTF-8 解码 → 非 ASCII 识别结果会变成字面 \xNN，JSON 解析失败，
# 表现为"识别到 0 行"且毫无报错（ASCII 测试图永远发现不了）。必须显式设 UTF-8。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$Path = '%(path)s'
$Lang = '%(lang)s'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

function Await($op, $resultType) {
  $task = $asTaskGeneric.MakeGenericMethod($resultType).Invoke($null, @($op))
  $task.Wait(-1) | Out-Null
  $task.Result
}

[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null

$engine = $null
if ($Lang) {
  try {
    $language = New-Object Windows.Globalization.Language($Lang)
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
  } catch { $engine = $null }
}
if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if ($null -eq $engine) {
  Write-Output '{"error":"no-ocr-language-pack"}'
  exit 0
}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
# OCR 引擎要求 BGRA8 预乘 alpha；解码结果不一定是这个格式，必须显式转换
if ($bitmap.BitmapPixelFormat -ne [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8) {
  $bitmap = [Windows.Graphics.Imaging.SoftwareBitmap]::Convert($bitmap, [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8)
}
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

$lines = @()
foreach ($line in $result.Lines) {
  $words = @()
  $minX = 1.0; $minY = 1.0; $maxX = 0.0; $maxY = 0.0
  foreach ($word in $line.Words) {
    $words += $word.Text
    $r = $word.BoundingRect
    if ($r.X -lt $minX) { $minX = $r.X }
    if ($r.Y -lt $minY) { $minY = $r.Y }
    if (($r.X + $r.Width) -gt $maxX) { $maxX = $r.X + $r.Width }
    if (($r.Y + $r.Height) -gt $maxY) { $maxY = $r.Y + $r.Height }
  }
  if ($words.Count -eq 0) { continue }
  $lines += [pscustomobject]@{
    text = ($words -join ' ')
    x = [math]::Round($minX / $bitmap.PixelWidth, 4)
    y = [math]::Round($minY / $bitmap.PixelHeight, 4)
    w = [math]::Round(($maxX - $minX) / $bitmap.PixelWidth, 4)
    h = [math]::Round(($maxY - $minY) / $bitmap.PixelHeight, 4)
  }
}
$payload = [pscustomobject]@{ language = $engine.RecognizerLanguage.LanguageTag; lines = $lines }
$payload | ConvertTo-Json -Depth 6 -Compress
"""


def run_winrt(image_path, languages=None, platform=None):
    # type: (str, Optional[str], Optional[str]) -> OcrResult
    """用 Windows 系统 OCR 识别。注意：WinRT 的 OcrEngine 只接受单个语言。"""
    platform = platform or current_platform()
    if platform != "win32":
        raise OcrError("WinRT 引擎只在 Windows 上可用（当前平台：%s）" % platform, missing_tool="winrt")
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        tool = find_tool("powershell", platform=platform)
        powershell = tool.path
    if not powershell:
        raise OcrError("找不到 powershell，无法调用 Windows 系统 OCR", missing_tool="powershell")

    # WinRT 只支持单语言，取第一个（请求 zh-Hans,en-US 时优先中文）
    language = ""
    if languages:
        language = str(languages).split(",")[0].strip()

    # 直接用 -EncodedCommand 传整段脚本：不落地临时文件、不经过 shell 引号解析，
    # 也不受系统代码页影响（脚本里有中文提示时尤其重要）。
    script = _WINRT_SCRIPT_TEMPLATE % {
        "path": os.path.abspath(image_path).replace("'", "''"),
        "lang": language.replace("'", "''"),
    }
    result = run(_powershell_argv(powershell, script), timeout=300)
    if not result.ok:
        raise OcrError("Windows OCR 识别失败：%s" % (result.tail(400) or "无输出"))

    payload = _parse_json_object(result.stdout)
    if not isinstance(payload, dict):
        raise OcrError(
            "Windows OCR 的输出无法解析为 JSON 对象（收到 %s）。原始输出片段：%s"
            % (type(payload).__name__, (result.stdout or "").strip()[:200]))
    if payload.get("error") == "no-ocr-language-pack":
        raise OcrError(
            "Windows 系统没有安装任何 OCR 语言包：请到「设置 → 时间和语言 → 语言和区域」"
            "添加中文/英文语言包（含「光学字符识别」可选功能），或改用 --engine tesseract"
        )

    lines = []
    for item in payload.get("lines", []):
        box = None
        if all(key in item for key in ("x", "y", "w", "h")):
            box = [item["x"], item["y"], item["w"], item["h"]]
        # WinRT 不提供逐行置信度 → 明确留空，而不是编一个数字
        lines.append(Line(str(item.get("text", "")), None, box))
    return OcrResult("winrt", lines, language=payload.get("language") or language,
                     meta={"enginePath": powershell, "recognizer": "Windows.Media.Ocr.OcrEngine",
                           "note": "WinRT 不提供置信度，故 confidence 为空"})


# ---------------------------------------------------------------------------
# Tesseract
# ---------------------------------------------------------------------------

def run_tesseract(image_path, languages=None, tesseract_path=None, psm=None, platform=None):
    # type: (str, Optional[str], Optional[str], Optional[str], Optional[str]) -> OcrResult
    """用 Tesseract 识别（TSV 输出，含逐行置信度）。"""
    tool = find_tool("tesseract", override=tesseract_path, platform=platform, version_argv=["--version"])
    if not tool.found:
        raise OcrError("找不到 tesseract", missing_tool="tesseract")

    lang = _map_tesseract_language(languages, tool.path)
    # --psm 必须在输出格式之前：tesseract 的位置参数是
    # `imagename outputbase [options...] [configfile...]`，
    # 写成 `... -l eng tsv --psm 6` 时 --psm 与 6 会被当成**配置文件**，
    # 报 read_params_file: Can't open --psm，参数被静默吞掉（本机 tesseract 5.5.2 复现）。
    argv = [tool.path, os.path.abspath(image_path), "stdout", "-l", lang]
    if psm:
        argv.extend(["--psm", str(psm)])
    argv.append("tsv")
    result = run(argv, timeout=600)
    if not result.ok:
        raise OcrError("Tesseract 识别失败：%s" % (result.tail(400) or "无输出"))

    lines = _parse_tesseract_tsv(result.stdout)
    return OcrResult("tesseract", lines, language=lang,
                     meta={"enginePath": tool.path, "version": tool.version,
                           "recognizer": "tesseract tsv (psm=%s)" % (psm or "默认 3")})


def _map_tesseract_language(languages, path):
    # type: (Optional[str], str) -> str
    """把通用语言写法映射成 tesseract 的语言代码，并做可用性降级。"""
    requested = (languages or "zh-Hans,en-US").replace(" ", "")
    parts = [p for p in requested.split(",") if p]
    mapping = {
        "zh-hans": "chi_sim", "zh-cn": "chi_sim", "chi_sim": "chi_sim",
        "zh-hant": "chi_tra", "zh-tw": "chi_tra", "chi_tra": "chi_tra",
        "en-us": "eng", "en": "eng", "eng": "eng",
        "ja-jp": "jpn", "jpn": "jpn", "ko-kr": "kor", "kor": "kor",
    }
    wanted = []  # type: List[str]
    for part in parts:
        code = mapping.get(part.lower(), part)
        if code not in wanted:
            wanted.append(code)

    installed = set(_tesseract_languages(path))
    usable = [code for code in wanted if not installed or code in installed]
    if not usable:
        usable = ["eng"] if (not installed or "eng" in installed) else wanted[:1]
    return "+".join(usable) if usable else "eng"


def _parse_tesseract_tsv(text):
    # type: (str) -> List[Line]
    """解析 tesseract 的 TSV 输出：按 (block, par, line) 归并成行。"""
    rows = []  # type: List[List[str]]
    for raw in text.splitlines():
        if not raw.strip():
            continue
        rows.append(raw.split("\t"))
    if not rows:
        return []
    header = rows[0]
    try:
        idx = {name: header.index(name) for name in ("level", "block_num", "par_num", "line_num", "text", "conf")}
    except ValueError:
        return []

    grouped = {}  # type: Dict[Tuple[str, str, str], List[Tuple[str, float]]]
    order = []  # type: List[Tuple[str, str, str]]
    for row in rows[1:]:
        if len(row) <= max(idx.values()):
            continue
        try:
            level = int(row[idx["level"]])
        except ValueError:
            continue
        if level != 5:  # 5 = word
            continue
        content = row[idx["text"]].strip()
        if not content:
            continue
        try:
            confidence = float(row[idx["conf"]])
        except ValueError:
            confidence = -1.0
        key = (row[idx["block_num"]], row[idx["par_num"]], row[idx["line_num"]])
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append((content, confidence))

    lines = []  # type: List[Line]
    for key in order:
        words = grouped[key]
        text = " ".join(word for word, _ in words)
        confidences = [conf for _, conf in words if conf >= 0]
        average = (sum(confidences) / len(confidences) / 100.0) if confidences else None
        lines.append(Line(text, average, None))
    return lines


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def auto_engine(platform=None, tesseract_path=None):
    # type: (Optional[str], Optional[str]) -> str
    """按平台优先级选引擎：macOS→vision，Windows→winrt，其余→tesseract。"""
    platform = platform or current_platform()
    report = available_engines(platform=platform, tesseract_path=tesseract_path)
    order = ("vision", "winrt", "tesseract") if platform == "darwin" else (
        "winrt", "tesseract", "vision") if platform == "win32" else ("tesseract", "vision", "winrt")
    for name in order:
        if report.get(name, {}).get("available"):
            return name
    return "tesseract"


def recognize(image_path, engine="auto", languages=None, tesseract_path=None,
              psm=None, platform=None):
    # type: (str, str, Optional[str], Optional[str], Optional[str], Optional[str]) -> OcrResult
    """统一识别入口。``engine="auto"`` 按平台优先级选择，失败则依次降级。"""
    if not os.path.isfile(image_path):
        raise OcrError("图片不存在：%s" % image_path)

    platform = platform or current_platform()
    if engine == "auto":
        candidates = [auto_engine(platform=platform, tesseract_path=tesseract_path)]
        report = available_engines(platform=platform, tesseract_path=tesseract_path)
        candidates.extend(name for name, info in report.items() if info.get("available") and name not in candidates)
    else:
        candidates = [engine]

    errors = []  # type: List[str]
    empty_results = []  # type: List[OcrResult]
    attempted = []  # type: List[str]

    for name in candidates:
        try:
            if name == "vision":
                result = run_vision(image_path, languages=languages, platform=platform)
            elif name == "winrt":
                result = run_winrt(image_path, languages=languages, platform=platform)
            elif name == "tesseract":
                result = run_tesseract(image_path, languages=languages,
                                       tesseract_path=tesseract_path, psm=psm, platform=platform)
            else:
                raise OcrError("未知引擎：%s（可选 vision / winrt / tesseract / auto）" % name)
        except OcrError as exc:
            errors.append("%s：%s" % (name, exc))
            continue

        attempted.append(name)
        if result.lines:
            if len(attempted) > 1:
                # 说明前一个引擎认出 0 行才降级过来，必须如实告知用户
                result.meta["fallbackFrom"] = "、".join(attempted[:-1])
                result.meta["fallbackNote"] = (
                    "前面的引擎在本次图片上识别出 0 行，已自动降级到 %s；"
                    "如果这不是你要的结果，可显式指定 --engine" % name)
            return result

        # 识别成功但一行都没有：不同引擎的行分割能力差异很大
        # （实测同一张合成图，macOS Vision 出 2~3 行、Windows 系统 OCR 出 0~1 行），
        # 所以继续尝试下一个引擎，而不是就此返回空结果。
        empty_results.append(result)

    if empty_results:
        primary = empty_results[0]
        primary.meta["emptyEngines"] = attempted
        primary.meta["emptyNote"] = (
            "以下引擎都执行成功但没识别到文字：%s。"
            "常见原因：文字过小（建议字高 >= 60px）、分辨率过低、语言不匹配，"
            "或图片本身没有文字" % "、".join(attempted))
        return primary

    raise OcrError("所有可用引擎都失败了：\n  - " + "\n  - ".join(errors),
                   missing_tool="tesseract" if any("tesseract" in item for item in errors) else None)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _write_temp_script(content, suffix):
    # type: (str, str) -> str
    handle = tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False,
                                         encoding="utf-8", newline="\n")
    with handle:
        handle.write(content)
    return handle.name


def _safe_remove(path):
    # type: (str) -> None
    try:
        os.remove(path)
    except OSError:
        pass


def _parse_json_array(text):
    # type: (str) -> List[dict]
    payload = _parse_json_object(text, expect_array=True)
    if isinstance(payload, list):
        return payload
    return []   # Vision 的输出可能夹带噪声，解析失败按空结果处理（由调用方决定是否告警）


def _parse_json_object(text, expect_array=False):
    # type: (str, bool) -> Any
    """从混合输出里抠出 JSON（osascript / powershell 都可能夹杂其它行）。

    **顺序至关重要**（真实缺陷）：期望对象时必须以 `{` 优先。
    WinRT 的输出是 `{"language":"en-US","lines":[...]}`；若先试 `[`，
    `find("[")/rfind("]")` 会抠出**内层数组**，`json.loads` 成功返回 list，
    调用方接着 `payload.get(...)` 就抛 AttributeError —— 而且这个异常不是
    OcrError，`recognize()` 的降级逻辑完全兜不住（表现为裸栈崩溃，
    连"0 行自动降级"都走不到）。之前把它误判成"图太小导致 0 行"。
    """
    text = (text or "").strip()
    if not text:
        return None

    if expect_array:
        pairs = (("[", "]"), ("{", "}"))
    else:
        pairs = (("{", "}"), ("[", "]"))

    for opener, closer in pairs:
        start = text.find(opener)
        end = text.rfind(closer)
        if start >= 0 and end > start:
            candidate = text[start:end + 1]
            try:
                parsed = json.loads(candidate)
            except ValueError:
                continue
            # 类型不符就继续尝试下一种括号（例如对象文本里恰好先出现 `[`）
            if expect_array and isinstance(parsed, list):
                return parsed
            if not expect_array and isinstance(parsed, dict):
                return parsed
    # 关键：解析失败返回 None，而不是 {} / []。
    # 否则"输出是垃圾"与"识别到 0 行"无法区分 —— run_winrt 会把它当成
    # 正常的空结果返回，降级逻辑（0 行→试下一个引擎）也就永远不会触发，
    # 用户看到的是"0 行且没有任何说明"（真实 CI 失败暴露的问题）。
    return None


def _as_float(value):
    # type: (Any) -> Optional[float]
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

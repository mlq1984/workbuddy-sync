"""OCR 结果渲染：Markdown / 可交互 HTML / 纯文本 / JSON。

HTML 产物的硬要求（用户明确提出的）：
1. **单文件、零外链**：图片以 data URI 内联，JS 与 CSS 内联，不引用任何 CDN、字体或图标。
   这样才能离线打开、随手转发、直接丢进知识库。
2. **可复制**：每行一个「复制」按钮 + 顶部「复制全文」；用 ``navigator.clipboard``，
   并在 ``file://`` 等非安全上下文下自动回退到 ``document.execCommand('copy')``。
3. **可核对**：左图右文，鼠标悬停/点击行会在图上高亮对应区域（如果有坐标），
   并显示该行置信度 —— 让用户能自己判断哪些字是可信的。
"""
from __future__ import annotations

import base64
import html
import json
import mimetypes
import os
import re
from typing import Any, Dict, List, Optional, Sequence

LOW_CONFIDENCE = 0.75


def _mime_type(path):
    # type: (str) -> str
    guessed, _ = mimetypes.guess_type(path)
    if guessed:
        return guessed
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
        ".tif": "image/tiff", ".tiff": "image/tiff", ".heic": "image/heic",
        ".pdf": "application/pdf",
    }.get(ext, "application/octet-stream")


def image_to_data_uri(path):
    # type: (str) -> str
    with open(path, "rb") as handle:
        payload = base64.b64encode(handle.read()).decode("ascii")
    return "data:%s;base64,%s" % (_mime_type(path), payload)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def to_markdown(result, source_path=None, title=None, include_summary=True, include_confidence=True):
    # type: (Any, Optional[str], Optional[str], bool, bool) -> str
    """OCR → Markdown。

    默认**保留原始换行**（不做段落合并、不做拼写纠正）：
    OCR 的价值是忠实转录，改写是模型的事，不该在识别阶段偷偷发生。
    """
    lines = []  # type: List[str]
    heading = title or (os.path.basename(source_path) if source_path else "识别结果")
    lines.append("# %s" % heading)
    lines.append("")

    if include_summary:
        lines.append(_summary_line(result, source_path))
        lines.append("")

    text_lines = [line.text for line in result.lines]
    if not text_lines:
        lines.append("> 未识别到任何文字。可能原因：图片本身没有文字、分辨率过低、或语言包不匹配。")
        lines.append("")
        return "\n".join(lines)

    for line in result.lines:
        text = line.text.strip()
        if not text:
            continue
        if include_confidence and line.uncertain:
            reason = _uncertain_reason(line)
            lines.append("%s  <!-- 需核对：%s -->" % (text, reason))
        else:
            lines.append(text)
    lines.append("")

    if include_confidence:
        uncertain = [line for line in result.lines if line.uncertain]
        if uncertain:
            lines.append("## 需人工核对的行")
            lines.append("")
            for line in uncertain:
                detail = _uncertain_reason(line)
                alternatives = ("；次选：%s" % "、".join(line.alternatives)) if line.alternatives else ""
                lines.append("- %s（%s%s）" % (line.text, detail, alternatives))
            lines.append("")
        if result.meta.get("confidenceNote"):
            lines.append("> 置信度口径：%s" % result.meta["confidenceNote"])
            lines.append("")
    return "\n".join(lines)


def _uncertain_reason(line):
    # type: (Any) -> str
    if line.alternatives:
        return "引擎给出了不同的次选结果"
    if line.confidence is not None:
        return "置信度 %.0f%%" % (line.confidence * 100)
    return "该引擎不提供置信度"


def _summary_line(result, source_path):
    # type: (Any, Optional[str]) -> str
    parts = ["引擎 `%s`" % result.engine]
    if result.language:
        parts.append("语言 `%s`" % result.language)
    parts.append("识别 %d 行" % len(result.lines))
    uncertain = sum(1 for line in result.lines if line.uncertain)
    if uncertain:
        parts.append("需核对 %d 行" % uncertain)
    average = result.average_confidence
    # 只在引擎真的提供有意义的置信度时才报平均分；否则报 0% 反而是误导
    if average is not None and result.meta.get("confidenceSemantics") is None:
        parts.append("平均置信度 %.1f%%" % (average * 100))
    if source_path:
        parts.append("来源 `%s`" % os.path.basename(source_path))
    return "> " + " ｜ ".join(parts)


# ---------------------------------------------------------------------------
# 纯文本
# ---------------------------------------------------------------------------

def to_text(result):
    # type: (Any) -> str
    return "\n".join(line.text for line in result.lines) + "\n"


# ---------------------------------------------------------------------------
# 可交互 HTML
# ---------------------------------------------------------------------------

def to_html(result, source_path=None, title=None, embed_image=True):
    # type: (Any, Optional[str], Optional[str], bool) -> str
    heading = title or (os.path.basename(source_path) if source_path else "识别结果")
    stats = _stats(result)
    image_block = _image_block(source_path, embed_image)
    lines_html = _lines_html(result)
    payload = json.dumps({"text": result.text, "lines": [l.as_dict() for l in result.lines]},
                         ensure_ascii=False)

    return _HTML_TEMPLATE % {
        "lang": "zh-CN",
        "title": html.escape(heading),
        "heading": html.escape(heading),
        "summary": html.escape(_summary_line(result, source_path).lstrip("> ")),
        "engine": html.escape(str(result.engine)),
        "language": html.escape(str(result.language or "自动")),
        "lineCount": stats["lineCount"],
        "average": stats["average"],
        "lowCount": stats["lowCount"],
        "image": image_block,
        "lines": lines_html,
        "payload": payload.replace("</", "<\\/"),
        "lowThreshold": int(LOW_CONFIDENCE * 100),
    }


def _stats(result):
    # type: (Any) -> Dict[str, Any]
    average = result.average_confidence
    low = [line for line in result.lines if line.uncertain]
    if result.meta.get("confidenceSemantics"):
        # 引擎给的不是概率型置信度 → 不展示「平均置信度」这种会误导的数字
        return {"lineCount": len(result.lines), "average": "该引擎不提供概率型置信度",
                "lowCount": len(low)}
    return {
        "lineCount": len(result.lines),
        "average": ("%.1f%%" % (average * 100)) if average is not None else "不提供",
        "lowCount": len(low),
    }


def _image_block(source_path, embed):
    # type: (Optional[str], bool) -> str
    if not source_path or not os.path.isfile(source_path):
        return '<div class="no-image">（未提供源图片，仅展示识别文本）</div>'
    if not embed:
        return '<img id="src" src="%s" alt="源图">' % html.escape(os.path.basename(source_path))
    try:
        uri = image_to_data_uri(source_path)
    except OSError:
        return '<div class="no-image">（源图读取失败）</div>'
    return '<img id="src" src="%s" alt="源图">' % uri


def _lines_html(result):
    # type: (Any) -> str
    if not result.lines:
        return '<div class="empty">未识别到任何文字。</div>'
    rows = []  # type: List[str]
    for index, line in enumerate(result.lines, start=1):
        confidence = line.confidence
        if confidence is None:
            level = "unknown"
            badge = "不提供"
        elif line.uncertain:
            level = "low"
            badge = "需核对" if line.alternatives else "%.0f%%" % (confidence * 100)
        elif confidence < LOW_CONFIDENCE:
            level = "medium"
            badge = "%.0f%%" % (confidence * 100)
        else:
            level = "high"
            badge = "%.0f%%" % (confidence * 100)

        box_attr = ""
        if line.box:
            box_attr = ' data-box="%s"' % ",".join("%.4f" % value for value in line.box)
        text = html.escape(line.text)
        rows.append(
            '<div class="line %s" data-index="%d"%s>'
            '<span class="idx">%d</span>'
            '<span class="txt">%s</span>'
            '<span class="badge">%s</span>'
            '<button class="copy" type="button" data-copy="%d" title="复制这一行">复制</button>'
            "</div>" % (level, index, box_attr, index, text, badge, index)
        )
    return "\n".join(rows)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="%(lang)s">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s · OCR 识别结果</title>
<style>
:root { color-scheme: light dark; --border: #d8dee4; --bg: #ffffff; --fg: #1f2328;
  --muted: #57606a; --soft: #f6f8fa; --accent: #0969da;
  --low: #d1242f; --medium: #9a6700; --high: #1a7f37; }
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
  "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
  color: var(--fg); background: var(--bg); font-size: 15px; line-height: 1.6;
  -webkit-text-size-adjust: 100%%; }
header { padding: 14px 18px; border-bottom: 1px solid var(--border); background: var(--soft);
  position: sticky; top: 0; z-index: 5; }
h1 { font-size: 17px; margin: 0 0 4px; }
.meta { color: var(--muted); font-size: 12.5px; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
button { font: inherit; font-size: 13px; padding: 6px 12px; border: 1px solid var(--border);
  border-radius: 6px; background: var(--bg); color: var(--fg); cursor: pointer; }
button:hover { border-color: var(--accent); color: var(--accent); }
button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
button.primary:hover { opacity: .9; color: #fff; }
main { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0; height: calc(100vh - 118px); }
.pane { overflow: auto; padding: 16px 18px; }
.pane.image { border-right: 1px solid var(--border); background: var(--soft); }
.pane.image img { max-width: 100%%; height: auto; border: 1px solid var(--border);
  border-radius: 6px; background: #fff; display: block; }
.no-image, .empty { color: var(--muted); padding: 12px; }
.line { display: flex; align-items: flex-start; gap: 8px; padding: 4px 6px; border-radius: 6px;
  border: 1px solid transparent; }
.line:hover { background: var(--soft); }
.line.active { border-color: var(--accent); background: var(--soft); }
.line .idx { color: var(--muted); font-size: 12px; min-width: 2.2em; text-align: right;
  padding-top: 3px; font-variant-numeric: tabular-nums; }
.line .txt { flex: 1; white-space: pre-wrap; word-break: break-word; }
.line .badge { font-size: 11.5px; color: var(--muted); padding-top: 3px;
  font-variant-numeric: tabular-nums; white-space: nowrap; }
.line.low .badge { color: var(--low); font-weight: 600; }
.line.medium .badge { color: var(--medium); }
.line.high .badge { color: var(--high); }
.line .copy { opacity: 0; transition: opacity .12s; padding: 3px 8px; font-size: 12px; }
.line:hover .copy, .line.active .copy { opacity: 1; }
mark.hl { background: rgba(9,105,218,.22); outline: 1px solid var(--accent); border-radius: 3px; }
.toast { position: fixed; left: 50%%; bottom: 24px; transform: translateX(-50%%);
  background: #1f2328; color: #fff; padding: 8px 14px; border-radius: 6px; font-size: 13px;
  opacity: 0; pointer-events: none; transition: opacity .2s; z-index: 20; }
.toast.show { opacity: .95; }
footer { padding: 8px 18px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--border); }
@media (max-width: 860px) {
  main { grid-template-columns: 1fr; height: auto; }
  .pane.image { border-right: 0; border-bottom: 1px solid var(--border); }
  .line .copy { opacity: 1; }
}
</style>
</head>
<body>
<header>
  <h1>%(heading)s</h1>
  <div class="meta">%(summary)s</div>
  <div class="toolbar">
    <button class="primary" id="copy-all" type="button">复制全文</button>
    <button id="copy-text" type="button">复制纯文本（无行号）</button>
    <button id="toggle-low" type="button">只看低置信行</button>
    <button id="show-json" type="button">查看结构化 JSON</button>
  </div>
</header>
<main>
  <section class="pane image" id="image-pane">
    %(image)s
  </section>
  <section class="pane text" id="text-pane">
    %(lines)s
  </section>
</main>
<footer>
  引擎 %(engine)s ｜ 语言 %(language)s ｜ %(lineCount)s 行 ｜ 平均置信度 %(average)s ｜
  低于 %(lowThreshold)s%% 的行 %(lowCount)s 行 —— 低置信行请以原图为准
</footer>
<div class="toast" id="toast"></div>
<script>
(function () {
  "use strict";
  var DATA = %(payload)s;
  var toastEl = document.getElementById("toast");
  var toastTimer = null;

  function toast(message) {
    toastEl.textContent = message;
    toastEl.classList.add("show");
    if (toastTimer) { clearTimeout(toastTimer); }
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 1400);
  }

  // file:// 下 navigator.clipboard 不可用，必须有回退路径
  function copy(text, label) {
    function fallback() {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.top = "-1000px";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
      document.body.removeChild(area);
      toast(ok ? (label + " 已复制") : "复制失败，请手动选择文本");
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { toast(label + " 已复制"); }, fallback);
    } else {
      fallback();
    }
  }

  function lineText(index) {
    return DATA.lines[index - 1] ? DATA.lines[index - 1].text : "";
  }

  document.getElementById("copy-all").addEventListener("click", function () {
    copy(DATA.lines.map(function (l) { return l.text; }).join("\\n"), "全文");
  });
  document.getElementById("copy-text").addEventListener("click", function () {
    copy(DATA.text, "纯文本");
  });

  var lines = Array.prototype.slice.call(document.querySelectorAll(".line"));
  var onlyLow = false;
  document.getElementById("toggle-low").addEventListener("click", function (event) {
    onlyLow = !onlyLow;
    event.target.textContent = onlyLow ? "显示全部行" : "只看低置信行";
    lines.forEach(function (node) {
      var isLow = node.classList.contains("low") || node.classList.contains("medium");
      node.style.display = (onlyLow && !isLow) ? "none" : "";
    });
  });

  document.getElementById("show-json").addEventListener("click", function () {
    copy(JSON.stringify(DATA, null, 2), "结构化 JSON");
  });

  document.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest(".copy") : null;
    if (button) {
      var index = parseInt(button.getAttribute("data-copy"), 10);
      copy(lineText(index), "第 " + index + " 行");
      event.stopPropagation();
      return;
    }
    var row = event.target.closest ? event.target.closest(".line") : null;
    if (row) { activate(row); }
  });

  var image = document.getElementById("src");
  var highlight = null;
  function activate(row) {
    lines.forEach(function (node) { node.classList.remove("active"); });
    row.classList.add("active");
    if (!image) { return; }
    var box = row.getAttribute("data-box");
    if (!box) { return; }
    var parts = box.split(",").map(parseFloat);
    if (parts.length !== 4) { return; }
    var natural = { w: image.naturalWidth || image.width, h: image.naturalHeight || image.height };
    var shown = { w: image.clientWidth, h: image.clientHeight };
    if (!natural.w || !shown.w) { return; }
    var scale = shown.w / natural.w;
    if (!highlight) {
      highlight = document.createElement("div");
      highlight.className = "hl";
      highlight.style.position = "absolute";
      highlight.style.pointerEvents = "none";
      var wrapper = image.parentNode;
      if (getComputedStyle(wrapper).position === "static") { wrapper.style.position = "relative"; }
      wrapper.appendChild(highlight);
    }
    highlight.style.left = (image.offsetLeft + parts[0] * shown.w) + "px";
    highlight.style.top = (image.offsetTop + parts[1] * shown.h) + "px";
    highlight.style.width = Math.max(4, parts[2] * shown.w) + "px";
    highlight.style.height = Math.max(4, parts[3] * shown.h) + "px";
  }

  // 键盘：j/k 或上下键逐行移动，方便逐行核对
  var cursor = -1;
  document.addEventListener("keydown", function (event) {
    if (event.target.tagName === "TEXTAREA" || event.target.tagName === "INPUT") { return; }
    if (event.key === "j" || event.key === "ArrowDown") { cursor = Math.min(lines.length - 1, cursor + 1); }
    else if (event.key === "k" || event.key === "ArrowUp") { cursor = Math.max(0, cursor - 1); }
    else if (event.key === "c" && cursor >= 0) { copy(lineText(cursor + 1), "第 " + (cursor + 1) + " 行"); return; }
    else { return; }
    event.preventDefault();
    if (lines[cursor]) {
      activate(lines[cursor]);
      lines[cursor].scrollIntoView({ block: "center", behavior: "smooth" });
    }
  });
})();
</script>
</body>
</html>
"""

import argparse
import base64
import json
import os
import re
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request
from xml.etree import ElementTree as ET

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from auth import AUTH_ERROR, AUTH_NEED_USER, AUTH_OK, ensure_auth

SKILL_SLUG = "stock-research-report"
TIMEOUT_SECONDS = 1200
AUTH_API_KEY_URL_FALLBACK = "https://ai.eastmoney.com/mxClaw"
# MCP 服务器地址
MCP_URL = "https://ai-saas.eastmoney.com/proxy/app-robo-advisor-api/assistant/write/stock/research"

class _AuthRevoked(Exception):
    """The API rejected EM_API_KEY with HTTP or business status 401/403."""

def _clear_em_api_key_file() -> None:
    cred_path = Path.home() / ".mx-skills" / "em_api_key"
    try:
        cred_path.unlink(missing_ok=True)
    except OSError:
        pass

def _raise_if_auth_revoked(payload: Any) -> None:
    if isinstance(payload, dict):
        code = payload.get("code")
        status = payload.get("status")
        if code in (401, "401", 403, "403") or status in (401, "401", 403, "403"):
            raise _AuthRevoked("business auth rejected: code={0}, status={1}".format(code, status))

def _handle_auth_revoked(reason: str, result: Dict[str, Any]) -> Dict[str, Any]:
    result.pop("remember_api_key", None)
    result.pop("api_key", None)
    _clear_em_api_key_file()
    env_key = os.environ.pop("EM_API_KEY", None)
    try:
        reauth = ensure_auth()
    finally:
        if env_key is not None:
            os.environ["EM_API_KEY"] = env_key
    if reauth.get("status") == AUTH_NEED_USER:
        result["need_auth"] = True
        result["authUrl"] = reauth.get("auth_url")
        result["apiKeyUrl"] = reauth.get("api_key_url") or AUTH_API_KEY_URL_FALLBACK
        result["auth_message"] = (
            "EM_API_KEY 已失效（{0}），已清理保存的 key。请扫码重新授权，"
            "完成后重新发送原指令。".format(reason)
        )
        if env_key and env_key.strip():
            result["auth_message"] += " 环境变量 EM_API_KEY 仍含有失效 key，请先清除该环境变量。"
    elif reauth.get("status") == AUTH_OK:
        result["error"] = (
            "EM_API_KEY 服务端已失效，但环境变量 EM_API_KEY 仍存在。"
            "请清除该环境变量后重新发送原指令以触发授权。"
        )
    else:
        result["error"] = "EM_API_KEY 失效后重新授权失败: {0}".format(
            reauth.get("message", "未知错误")
        )
    return result

def output_root() -> Path:
    value = os.environ.get("STOCK_RESEARCH_OUTPUT_DIR", "").strip()
    return Path(value) if value else Path.cwd() / "miaoxiang" / SKILL_SLUG


def _load_em_api_key() -> str:
    env_value = (os.environ.get("EM_API_KEY") or "").strip()
    if env_value:
        return env_value
    cred_path = Path.home() / ".mx-skills" / "em_api_key"
    if cred_path.exists():
        return cred_path.read_text(encoding="utf-8").strip()
    return ""


def error_message(body: str) -> str:
    try:
        parsed = json.loads(body)
    except Exception:
        return (body or "")[:200]
    if isinstance(parsed, dict):
        for key in ("message", "msg", "error"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return (body or "")[:200]


def call_api(query: str, api_key: str) -> Dict[str, Any]:
    body = json.dumps({"query": query}, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        MCP_URL, data=body, method="POST",
        headers={
            "Content-Type": "application/json",
            "em_api_key": api_key,
            "x-open-id-vendor": "tencent",
            "x-open-id-app": "workbuddy",
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8", errors="replace")
    except urllib_error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        if exc.code in (401, 403):
            raise _AuthRevoked("HTTP {0}: {1}".format(exc.code, error_message(text)))
        raise RuntimeError(error_message(text) or "HTTP {0}".format(exc.code))
    except urllib_error.URLError as exc:
        raise RuntimeError("股票研究接口请求失败: {0}".format(exc.reason))
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("股票研究接口返回了无法解析的响应")
    if not isinstance(result, dict):
        raise RuntimeError("股票研究接口返回格式异常")
    _raise_if_auth_revoked(result)
    return result


def save_base64(value: Any, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        path.write_bytes(base64.b64decode(value.strip(), validate=True))
    except Exception as exc:
        raise RuntimeError("附件解码失败: {0}".format(exc))
    return str(path.resolve())


def attachment_basename(title: Any, article_id: Any = "") -> str:
    """
    Build attachment filename stem from API title.
    Keeps Chinese; strips Windows-illegal characters. Falls back to articleId.
    """
    raw = str(title or "").strip()
    # Windows forbidden: \\ / : * ? " < > |  and control chars
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._")
    if not cleaned:
        fallback = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(article_id or "").strip())
        cleaned = fallback.strip("_") or uuid.uuid4().hex
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip(" ._")
    return cleaned


_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _w_on(el: Optional[ET.Element]) -> bool:
    """OOXML on/off element: present and val not explicitly false/0."""
    if el is None:
        return False
    val = el.attrib.get(_W_NS + "val")
    if val is None:
        val = el.attrib.get("val")
    if val is None:
        return True
    return str(val).lower() not in ("0", "false", "off")


def _run_is_bold(r: ET.Element) -> bool:
    rPr = r.find(_W_NS + "rPr")
    if rPr is None:
        return False
    return _w_on(rPr.find(_W_NS + "b")) or _w_on(rPr.find(_W_NS + "bCs"))


def _run_text(r: ET.Element) -> str:
    parts = []
    for node in r:
        if node.tag == _W_NS + "t" and node.text:
            parts.append(node.text)
        elif node.tag == _W_NS + "tab":
            parts.append("\t")
        elif node.tag == _W_NS + "br":
            parts.append("\n")
    return "".join(parts)


def _para_text(p: ET.Element) -> str:
    """
    Extract paragraph text. Mixed bold runs become Markdown **bold**.
    Fully-bold paragraphs (typical titles/headings) stay plain so heading
    detection in format_as_markdown still works.
    """
    segments = []  # list of (bold, text)

    def add_run(r: ET.Element) -> None:
        text = _run_text(r)
        if text == "":
            return
        bold = _run_is_bold(r)
        if segments and segments[-1][0] == bold:
            segments[-1] = (bold, segments[-1][1] + text)
        else:
            segments.append((bold, text))

    for child in list(p):
        tag = child.tag
        if tag == _W_NS + "r":
            add_run(child)
        elif tag == _W_NS + "hyperlink":
            for r in child.findall(_W_NS + "r"):
                add_run(r)
        elif tag == _W_NS + "ins":
            for r in child.findall(_W_NS + "r"):
                add_run(r)

    if not segments:
        # fallback: nested content (rare)
        plain = []
        for node in p.iter():
            if node.tag == _W_NS + "t" and node.text:
                plain.append(node.text)
        return "".join(plain).strip()

    meaningful = [(b, t) for b, t in segments if t.strip()]
    # Entire paragraph bold → treat as plain title/heading text
    if meaningful and all(b for b, _t in meaningful):
        return "".join(t for _b, t in segments).strip()

    out = []
    for bold, text in segments:
        if not bold:
            out.append(text)
            continue
        # Keep surrounding whitespace outside ** ** markers
        left = text[: len(text) - len(text.lstrip(" \t"))]
        right = text[len(text.rstrip(" \t")) :] if text.rstrip(" \t") != text else ""
        core = text.strip(" \t")
        if not core:
            out.append(text)
        else:
            out.append("{0}**{1}**{2}".format(left, core, right))
    return "".join(out).strip()


def _classify_segment_metric(cell: str) -> Optional[str]:
    """Match only 分板块 metric labels; avoid substring hits like 综合毛利率."""
    s = (cell or "").strip()
    if not s:
        return None
    if re.fullmatch(r"收入占比(\(%\)|（%）)?", s) or s == "收入占比":
        return "收入占比(%)"
    if re.fullmatch(r"毛利率(\(%\)|（%）)?", s) or s == "毛利率":
        return "毛利率(%)"
    if re.fullmatch(r"收入(\((亿元|万元)\)|（(亿元|万元)）)?", s) or s == "收入":
        return "收入(万元)" if "万" in s else "收入(亿元)"
    if s in ("收入(亿元)", "收入（亿元）", "收入(万元)", "收入（万元）"):
        return "收入(万元)" if "万" in s else "收入(亿元)"
    return None


_COMPANY_LEVEL_METRIC_MARKERS = (
    "营业总收入",
    "营业收入",
    "归母净利润",
    "扣非归母",
    "扣非净利润",
    "资产负债率",
    "经营活动现金流",
    "净资产收益率",
    "基准股本",
    "EPS",
    "ROE",
    "ROA",
    "PE",
    "PEG",
)


def _is_segment_name_cell(cell: str) -> bool:
    s = (cell or "").strip()
    if not s or _classify_segment_metric(s):
        return False
    if re.fullmatch(r"-?[\d,]+(?:\.\d+)?%?", s.replace(",", "")):
        return False
    if re.fullmatch(r"\d{4}([-/年]\d{1,2}([-/月]\d{1,2})?)?", s):
        return False
    if any(m in s for m in _COMPANY_LEVEL_METRIC_MARKERS):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", s))


def _extract_numeric_values(row: list, skip: set) -> list:
    vals = []
    for idx, c in enumerate(row):
        if idx in skip:
            continue
        text = (c or "").strip()
        if text in ("", "-", "—", "–"):
            vals.append(text if text else "")
            continue
        if re.fullmatch(r"-?[\d,]+(?:\.\d+)?%?", text.replace(",", "")):
            vals.append(text)
            continue
        if re.search(r"\d", text) and not re.search(r"[\u4e00-\u9fff]", text):
            vals.append(text)
    return vals


def _looks_like_segment_table(header: list, body: list) -> bool:
    """Strict gate: only 分板块 tables, never company-level finance/consensus."""
    header_join = "".join(header)
    if "业务板块" in header_join:
        return True
    # 主要财务指标 / 一致预测 / 普通指标表：首列为公司级指标时绝不重写
    if header and header[0] in ("财务指标", "关键指标", "指标", "项目", "科目"):
        return False
    company_hits = sum(
        1
        for r in body
        for c in r
        if any(m in (c or "") for m in _COMPANY_LEVEL_METRIC_MARKERS)
    )
    if company_hits >= 2:
        return False
    kinds = set()
    for r in body:
        for c in r:
            m = _classify_segment_metric(c)
            if m:
                kinds.add(m)
    has_income = "收入(亿元)" in kinds or "收入(万元)" in kinds
    has_margin = "毛利率(%)" in kinds
    has_share = "收入占比(%)" in kinds
    # Need the segment triad (or income+margin repeated across segments)
    metric_hits = sum(1 for r in body for c in r if _classify_segment_metric(c))
    return has_income and has_margin and (has_share or metric_hits >= 4)


def _fix_segment_merged_table(rows: list) -> list:
    """
    Expand vertically-merged '业务板块' cells for 分板块业务情况 style tables.

    Markdown cannot keep rowspan, so segment names often appear only on the
    middle metric row (收入占比), shifting 收入/毛利率 rows left by one column.
    Rebuild to: 业务板块 | 财务指标 | years... with segment name repeated.
    """
    if not rows or len(rows) < 4:
        return rows

    header = [str(c or "").strip() for c in rows[0]]
    body = [[str(c or "").strip() for c in r] for r in rows[1:]]
    if not _looks_like_segment_table(header, body):
        return rows

    # Already in canonical shape: each body row is 板块 | 指标 | values...
    if body and all(
        len(r) >= 2 and _is_segment_name_cell(r[0]) and _classify_segment_metric(r[1])
        for r in body
    ):
        years = [c for c in header if re.search(r"20\d{2}", c)]
        if not years:
            years = [c for c in header[2:] if c]
        return [["业务板块", "财务指标"] + years] + body

    years = [c for c in header if re.search(r"20\d{2}", c)]
    if not years:
        years = [c for c in header[2:] if c]
    fixed_header = ["业务板块", "财务指标"] + years
    year_n = len(years)

    def parse_row(row: list):
        metric_name = None
        metric_idx = -1
        segment = ""
        for idx, c in enumerate(row):
            m = _classify_segment_metric(c)
            if m:
                metric_name = m
                metric_idx = idx
                break
        if metric_name is None:
            return None
        for idx, c in enumerate(row):
            if idx == metric_idx:
                continue
            if _is_segment_name_cell(c):
                segment = c
                break
        skip = {metric_idx}
        for idx, c in enumerate(row):
            if segment and c == segment and idx != metric_idx:
                skip.add(idx)
                break
        values = _extract_numeric_values(row, skip)
        if year_n > 0:
            if len(values) < year_n:
                values = values + [""] * (year_n - len(values))
            else:
                values = values[:year_n]
        return segment, metric_name, values

    order = ["收入(亿元)", "收入(万元)", "收入占比(%)", "毛利率(%)"]
    out = [fixed_header]
    i = 0
    last_segment = ""
    while i < len(body):
        window = []
        k = i
        while k < len(body) and len(window) < 3:
            parsed = parse_row(body[k])
            k += 1
            if parsed is None:
                if window:
                    break
                # skip non-metric junk row
                i = k
                continue
            window.append(parsed)
            # A complete segment block usually has 3 metrics
            if len(window) == 3:
                break
            # If we already saw 收入 + 毛利率 without 占比, still allow 2-row block
            names = {p[1] for p in window}
            if len(window) == 2 and "毛利率(%)" in names and (
                "收入(亿元)" in names or "收入(万元)" in names
            ) and "收入占比(%)" not in names:
                # peek whether next is another 收入 (new segment)
                if k < len(body):
                    nxt = parse_row(body[k])
                    if nxt and nxt[1] in ("收入(亿元)", "收入(万元)"):
                        break
        if not window:
            break

        segment = next((seg for seg, _n, _v in window if seg), last_segment)
        if segment:
            last_segment = segment
        metrics = {name: vals for _seg, name, vals in window}
        for name in order:
            if name in metrics:
                out.append([segment, name] + list(metrics[name]))
        i = k

    # Safety: never accept a rewrite that drops most rows (false-positive guard).
    if len(out) <= 1:
        return rows
    if len(out) < max(3, int(len(rows) * 0.6)):
        return rows
    return out


def _plain_markdown_table(rows: list) -> str:
    """Markdown table without 分板块 rewrite (for already-clean grids)."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    normalized = [list(r) + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join("" if c is None else str(c) for c in normalized[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    for row in normalized[1:]:
        lines.append("| " + " | ".join("" if c is None else str(c) for c in row) + " |")
    return "\n".join(lines)


def _table_text(tbl: ET.Element) -> str:
    """Extract Word table, expanding vertical merges (vMerge) by repeating cell text."""
    raw_rows = []
    for tr in tbl.findall(_W_NS + "tr"):
        row = []
        for tc in tr.findall(_W_NS + "tc"):
            cell_paras = [_para_text(p) for p in tc.findall(_W_NS + "p")]
            text = " ".join(s for s in cell_paras if s)
            vmerge = None
            span = 1
            tcPr = tc.find(_W_NS + "tcPr")
            if tcPr is not None:
                vm = tcPr.find(_W_NS + "vMerge")
                if vm is not None:
                    val = vm.attrib.get(_W_NS + "val") or vm.attrib.get("val")
                    vmerge = "continue" if val == "continue" else "restart"
                gs = tcPr.find(_W_NS + "gridSpan")
                if gs is not None:
                    try:
                        span = int(gs.attrib.get(_W_NS + "val") or gs.attrib.get("val") or 1)
                    except Exception:
                        span = 1
            row.append({"text": text, "vmerge": vmerge, "span": max(1, span)})
        if row:
            raw_rows.append(row)

    if not raw_rows:
        return ""

    expanded = []
    carry = []
    for row in raw_rows:
        flat = []
        for cell in row:
            flat.extend(
                [cell]
                + [{"text": "", "vmerge": cell["vmerge"], "span": 1}] * (cell["span"] - 1)
            )
        if len(carry) < len(flat):
            carry.extend([""] * (len(flat) - len(carry)))
        out_row = []
        for idx, cell in enumerate(flat):
            text = cell["text"]
            if cell["vmerge"] == "continue":
                text = carry[idx] if idx < len(carry) else ""
            else:
                carry[idx] = text
            out_row.append(text)
        expanded.append(out_row)

    width = max(len(r) for r in expanded)
    matrix = [r + [""] * (width - len(r)) for r in expanded]
    # Upstream sometimes emits 1x1 caption placeholders (no chart image / no grid).
    if _is_placeholder_table(matrix):
        title = (matrix[0][0] or "").strip() or "图表"
        return (
            "> 上游 Word 未下发该章节表格数据（仅占位标题：{0}），"
            "请打开 Word/PDF 附件查看；若附件同样缺失则为接口侧未嵌入图表。"
        ).format(title)
    return _rows_to_markdown_table(matrix)


_PLACEHOLDER_TABLE_TITLES = (
    "分板块业务情况",
    "主要客户情况",
    "主要供应商情况",
    "研发实力与人才布局",
    "研发实力人才储备",
    "主要财务指标",
    "一致盈利预测数据",
    "一致盈利预测",
)


def _is_placeholder_table(matrix: list) -> bool:
    """True for empty/caption-only tables that carry no numeric grid."""
    if not matrix:
        return True
    flat = [(c or "").strip() for r in matrix for c in r]
    nonempty = [c for c in flat if c]
    if not nonempty:
        return True
    if len(matrix) == 1 and len(matrix[0]) == 1:
        cell = nonempty[0]
        return any(cell == t or cell.startswith(t) for t in _PLACEHOLDER_TABLE_TITLES)
    # Single column of titles only, no numbers
    if max(len(r) for r in matrix) <= 1 and not any(re.search(r"\d", c) for c in nonempty):
        return any(any(t in c for t in _PLACEHOLDER_TABLE_TITLES) for c in nonempty)
    return False


def _rows_to_markdown_table(rows: list) -> str:
    if not rows:
        return ""
    rows = _fix_segment_merged_table(rows)
    return _plain_markdown_table(rows)


# Match report titles across markets, e.g. 东方财富(300059.SZ)、腾讯控股(00700.HK)、苹果(AAPL.US)
_H1_RE = re.compile(r"^.+\([^)]+\)股票研究$")
_H2_RE = re.compile(r"^(\d{1,2})\s+\S+")
_H3_NUM_RE = re.compile(r"^(\d{1,2}\.\d+)\s+\S+")
_H3_NAMES = {
    "催化事件时间表",
    "短期逻辑",
    "长期逻辑",
    "主要客户情况",
    "主要供应商情况",
    "研发实力与人才布局",
    "研发实力人才储备",
    "主要财务指标",
    "一致盈利预测数据",
    "一致盈利预测",
    "分板块业务情况",
}
_TABLE_ROW_RE = re.compile(r"^\|.*\|$")
_TABLE_SEP_RE = re.compile(r"^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_MD_IMAGE_RE = re.compile(r"^!\[[^\]]*\]\([^)]+\)$")


def _is_h3_named(line: str) -> bool:
    s = line.strip()
    if s in _H3_NAMES:
        return True
    for name in _H3_NAMES:
        if s.startswith(name + "(") or s.startswith(name + "（"):
            return True
    return False


def _ensure_table_separator(table_lines: list) -> list:
    if not table_lines:
        return table_lines
    if len(table_lines) >= 2 and _TABLE_SEP_RE.match(table_lines[1]):
        return table_lines
    header = table_lines[0]
    cols = max(1, header.count("|") - 1)
    sep = "| " + " | ".join("---" for _ in range(cols)) + " |"
    return [header, sep] + table_lines[1:]


def _push_heading(out: list, heading: str) -> None:
    if out and out[-1] != "":
        out.append("")
    out.append(heading)
    out.append("")


def format_as_markdown(text: str) -> str:
    """
    Convert flat extracted report text into renderable Markdown.
    Only adds structural markers (headings / table separators / spacing).
    Preserves Word-derived **bold** markers; does not rewrite body content.
    """
    if not text or not text.strip():
        return ""
    raw_lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    raw_lines = [ln for ln in raw_lines if not re.match(r"^---\s*page\s+\d+\s*---$", ln.strip(), re.I)]

    out = []
    i = 0
    n = len(raw_lines)

    def plain_heading_candidate(s: str) -> str:
        # strip accidental full-line bold wrappers before heading match
        t = s.strip()
        if t.startswith("**") and t.endswith("**") and t.count("**") == 2:
            return t[2:-2].strip()
        return t

    while i < n:
        line = raw_lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("（信息类型：") or line.startswith("(信息类型："):
            i += 1
            continue

        if _MD_IMAGE_RE.match(line) or line.startswith(">"):
            if out and out[-1] != "":
                out.append("")
            out.append(line)
            out.append("")
            i += 1
            continue

        if _TABLE_ROW_RE.match(line):
            block = []
            while i < n and raw_lines[i].strip() and _TABLE_ROW_RE.match(raw_lines[i].strip()):
                block.append(raw_lines[i].strip())
                i += 1
            block = _ensure_table_separator(block)
            if out and out[-1] != "":
                out.append("")
            out.extend(block)
            out.append("")
            continue

        head = plain_heading_candidate(line)
        if head.startswith("#"):
            _push_heading(out, head)
            i += 1
            continue
        if _H1_RE.match(head) or (i == 0 and "股票研究" in head):
            _push_heading(out, "# " + head.lstrip("# ").strip())
            i += 1
            continue
        if _H3_NUM_RE.match(head):
            _push_heading(out, "### " + head)
            i += 1
            continue
        if _H2_RE.match(head):
            _push_heading(out, "## " + head)
            i += 1
            continue
        if _is_h3_named(head):
            _push_heading(out, "### " + head)
            i += 1
            continue

        out.append(line)
        if line.startswith("资料来源"):
            out.append("")
        i += 1

    cleaned = []
    for ln in out:
        if ln == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(ln)
    return "\n".join(cleaned).strip() + "\n"


def _emit_node(node: ET.Element, out: list) -> None:
    """Extract text and native Word tables only; skip embedded images."""
    tag = node.tag
    if tag == _W_NS + "p":
        text = _para_text(node)
        if text:
            out.append(text)
    elif tag == _W_NS + "tbl":
        table = _table_text(node)
        if table:
            out.append(table)
    elif tag == _W_NS + "sdt":
        content = node.find(_W_NS + "sdtContent")
        target_node = content if content is not None else node
        for child in list(target_node):
            _emit_node(child, out)


def extract_docx_text(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return ""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
            try:
                root = ET.fromstring(xml)
            except Exception:
                return ""
            body = root.find(_W_NS + "body") or root
            out = []
            for child in list(body):
                if child.tag == _W_NS + "sectPr":
                    continue
                _emit_node(child, out)
            return format_as_markdown("\n".join(out))
    except Exception:
        return ""


def extract_pdf_text(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
    except Exception:
        return ""
    pages = []
    for i, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text:
            pages.append(text)
    return format_as_markdown("\n".join(pages))


def _section_has_data_table(text: str, start: int, end: int) -> bool:
    chunk = text[start:end]
    rows = [ln for ln in chunk.splitlines() if ln.startswith("|") and "---" not in ln]
    if len(rows) < 3:
        return False
    # Need a real grid: >=2 columns and some digits
    wide = sum(1 for r in rows if r.count("|") >= 3)
    return wide >= 3 and bool(re.search(r"\d", chunk))


def _looks_incomplete(text: str) -> bool:
    """True when key chapters exist as titles but lack real tables."""
    if not text:
        return True
    # Section-aware: title present but no usable table until next major heading.
    checks = (
        ("分板块业务情况", ("## 5", "5 公司供应链", "### 主要客户")),
        ("主要客户情况", ("主要供应商情况", "## 6", "6 公司研发")),
        ("主要供应商情况", ("## 6", "6 公司研发", "研发实力")),
        ("主要财务指标", ("## 8", "8 公司盈利", "一致盈利")),
        ("一致盈利预测", ("### 8.2", "8.2", "## 9", "估值分析")),
    )
    missing = 0
    present = 0
    for title, stops in checks:
        i = text.find(title)
        if i < 0:
            continue
        present += 1
        end = len(text)
        for s in stops:
            j = text.find(s, i + len(title))
            if j >= 0:
                end = min(end, j)
        if not _section_has_data_table(text, i, end):
            missing += 1
    if present and missing:
        return True
    # Fallback global heuristic
    markers = ("7.2", "8.1", "主要财务指标", "一致盈利预测", "分板块业务情况", "研发实力与人才布局")
    has_marker = any(m in text for m in markers)
    numeric_rows = len(re.findall(r"\|\s*-?[\d.,]+\s*\|", text))
    return has_marker and numeric_rows < 8


def extract_full_content(
    files: Dict[str, str],
    preview: str,
) -> Dict[str, str]:
    word_path = files.get("word") or ""
    pdf_path = files.get("pdf") or ""
    word_text = ""
    if word_path:
        word_text = extract_docx_text(Path(word_path))
        if word_text and not _looks_incomplete(word_text):
            return {"fullContent": word_text, "fullContentSource": "word"}
    if pdf_path:
        pdf_text = extract_pdf_text(Path(pdf_path))
        if pdf_text and not _looks_incomplete(pdf_text):
            return {"fullContent": pdf_text, "fullContentSource": "pdf"}
    # Prefer Word even if partially incomplete (still richer than preview), else preview.
    if word_text:
        return {"fullContent": word_text, "fullContentSource": "word"}
    preview_md = format_as_markdown(preview) if preview else ""
    return {"fullContent": preview_md or preview, "fullContentSource": "preview"}


def generate(query: str, debug: bool = False, save_to_file: bool = True) -> Dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"ok": False, "message": "请提供需要研究的股票名称或代码"}
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    run_dir = output_root() / run_id
    attachment_dir = run_dir / "attachments"
    attachment_dir.mkdir(parents=True, exist_ok=True)
    credential_result: Dict[str, Any] = {}
    auth = ensure_auth()
    if auth.get("status") == AUTH_NEED_USER:
        return {
            "ok": False,
            "message": "",
            "need_auth": True,
            "authUrl": auth.get("auth_url"),
            "apiKeyUrl": auth.get("api_key_url") or AUTH_API_KEY_URL_FALLBACK,
            "auth_message": "尚未完成授权。请优先扫码授权，完成后重新发送原指令。",
        }
    if auth.get("status") == AUTH_ERROR:
        return {"ok": False, "message": auth.get("message", "授权流程出错")}
    newly_obtained_key = auth.get("api_key") if auth.get("newly_obtained") else None
    if newly_obtained_key:
        credential_result["remember_api_key"] = True
        credential_result["api_key"] = newly_obtained_key
    api_key_value = newly_obtained_key or _load_em_api_key()
    if not api_key_value:
        return {"ok": False, "message": "EM_API_KEY 落盘异常，请重新执行或检查 ~/.mx-skills/em_api_key"}
    try:
        raw = call_api(query, api_key_value)
        code, status = raw.get("code"), raw.get("status")
        data = raw.get("data")
        if code not in (None, 0, 200) or status not in (None, 0, 200) or not isinstance(data, dict):
            raise RuntimeError(str(raw.get("message") or "股票研究报告生成失败"))
        content = str(data.get("content") or "").strip()
        if not content:
            raise RuntimeError(str(raw.get("message") or "股票研究报告生成失败"))
        title = str(data.get("title") or "").strip()
        article_id = str(data.get("articleId") or "")
        file_stem = attachment_basename(title, article_id)
        files = {"pdf": "", "word": ""}
        if save_to_file:
            files = {
                "pdf": save_base64(data.get("pdfBase64"), attachment_dir / (file_stem + ".pdf")),
                "word": save_base64(data.get("wordBase64"), attachment_dir / (file_stem + ".docx")),
            }
        full = extract_full_content(files, content)
        full_content = full["fullContent"]
        full_source = full["fullContentSource"]
        if full_content and save_to_file:
            try:
                (run_dir / "full_report.md").write_text(full_content, encoding="utf-8")
            except Exception:
                pass
        if debug:
            # strip huge base64 before dumping debug json
            slim = dict(raw)
            if isinstance(slim.get("data"), dict):
                data_slim = dict(slim["data"])
                for k in ("pdfBase64", "wordBase64"):
                    if k in data_slim and data_slim[k]:
                        data_slim[k] = "<omitted {0} chars>".format(len(str(data_slim[k])))
                slim["data"] = data_slim
            (run_dir / "response.json").write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
        refs = data.get("refIndexList")
        result = {
            "ok": True, "title": title, "content": content,
            "fullContent": full_content, "fullContentSource": full_source,
            "articleId": article_id, "shareUrl": str(data.get("shareUrl") or ""),
            "files": files, "mediaDir": "",
            "referenceCount": len(refs) if isinstance(refs, list) else 0,
        }
        result.update(credential_result)
        return result
    except _AuthRevoked as exc:
        return _handle_auth_revoked(str(exc), {"ok": False, "message": ""})
    except Exception as exc:
        result = {"ok": False, "message": str(exc)}
        result.update(credential_result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a stock research report.")
    parser.add_argument("--query", default="")
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    query = args.query.strip() or sys.stdin.read().strip()
    if not query:
        parser.print_help()
        raise SystemExit(1)
    result = generate(query, args.debug, not args.no_save)

    if result.get("remember_api_key"):
        print("remember_api_key: true")
        print("credential_name: EM_API_KEY")
        print("apiKey: {0}".format(result["api_key"]))
        print("agent_action: 将 apiKey 的精确完整值以 EM_API_KEY 保存到所在平台提供的私有跨会话持久存储；绝不向用户展示、复述或写入业务文件。后续调用前先从该持久存储读取，并仅作为当前进程的 EM_API_KEY 环境变量注入；若平台不支持持久化或读取失败，则回退到正常授权流程。")
        result.pop("remember_api_key", None)
        result.pop("api_key", None)

    if result.get("need_auth"):
        print("need_auth: true")
        if result.get("authUrl"):
            print("authUrl: {0}".format(result["authUrl"]))
        if result.get("apiKeyUrl"):
            print("apiKeyUrl: {0}".format(result["apiKeyUrl"]))
        if result.get("auth_message"):
            print(result["auth_message"])
        raise SystemExit(10)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()

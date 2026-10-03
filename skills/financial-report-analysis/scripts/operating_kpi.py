#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
operating_kpi.py —— 行业 / 公司关键经营指标（KPI）季度序列工具

财务指标是结果，经营指标是原因。本脚本把手工收集的经营指标（销量、ASP、
高端占比、市占率…）按季排成序列，自动计算派生指标、同比、环比与趋势特征，
输出 Markdown / HTML 表格片段，供 financial-report-analysis 技能报告
的「1.5 行业与公司关键经营指标」章节直接引用。

核心原则：派生指标（单车均价、单车净利、占比…）一律用公式计算，不手填，
保证可复算、可核验。

输入 JSON 格式：
{
  "公司": "比亚迪",
  "行业": "汽车",
  "periods": ["2024Q3", "2024Q4", "2025Q1", ...],
  "series": {
    "汽车销量(辆)":   [1130000, 1525000, 1000804, ...],
    "汽车分部收入(亿元)": [ ... ],
    "扣非归母净利(亿元)": [ ... ],
    "高端车销量(辆)":  [ ... ]
  },
  "derived": [
    {"name": "单车均价ASP（万元）", "expr": "汽车分部收入(亿元) * 1e4 / 汽车销量(辆)"},
    {"name": "单车净利（元）",      "expr": "扣非归母净利(亿元) * 1e8 / 汽车销量(辆)"},
    {"name": "高端车占比（%）",     "expr": "高端车销量(辆) / 汽车销量(辆) * 100"}
  ]
}

CSV 输入（首列为指标名，首行为报告期）：
    指标,2024Q3,2024Q4,2025Q1,...
    汽车销量(辆),1130000,1525000,...
  派生定义用 --derived derived.json（同 JSON 的 derived 数组）

用法:
    python3 operating_kpi.py --input byd_kpi.json --out html
    python3 operating_kpi.py --input byd_kpi.csv --derived derived.json --out md
    python3 operating_kpi.py --input byd_kpi.json --out json
"""

import argparse
import csv
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quarterly_trend import (  # noqa: E402  复用季度序列的趋势特征与 HTML 渲染
    arrow_cls, cell_hint, esc, fmt, html_table, md_table, trend_features,
)

# 公式求值环境：只暴露必要的内建函数，禁止一切副作用
SAFE_GLOBALS = {
    "__builtins__": {},
    "abs": abs, "min": min, "max": max, "sum": sum, "round": round,
    "float": float, "int": int,
}

PERIOD_RE = re.compile(r"(\d{4})\D*Q?(\d)")


# ---------------------------------------------------------------- 输入解析

def load_input(path, derived_path=None):
    """返回 (meta, periods, series, derived_defs)。"""
    if path.lower().endswith(".csv"):
        with open(path, "r", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        if len(rows) < 2:
            raise SystemExit("CSV 内容不足：至少需要表头行与一行数据。")
        periods = [c.strip() for c in rows[0][1:] if c.strip()]
        series = {}
        for r in rows[1:]:
            if not r or not r[0].strip():
                continue
            series[r[0].strip()] = [parse_cell(c) for c in r[1:len(periods) + 1]]
        meta = {"公司": os.path.splitext(os.path.basename(path))[0], "行业": "未指定"}
        derived = []
        if derived_path:
            with open(derived_path, "r", encoding="utf-8") as f:
                derived = json.load(f).get("derived", [])
        return meta, periods, series, derived

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    meta = {"公司": raw.get("公司", ""), "行业": raw.get("行业", "未指定")}
    periods = raw.get("periods") or []
    series = raw.get("series") or {}
    derived = raw.get("derived") or []
    if derived_path:
        with open(derived_path, "r", encoding="utf-8") as f:
            derived = derived + json.load(f).get("derived", [])
    if not periods:
        raise SystemExit("输入缺少 periods（报告期标签数组）。")
    series = {k: [parse_cell(v) for v in vals] for k, vals in series.items()}
    return meta, periods, series, derived


def parse_cell(v):
    if v is None or v == "" or v == "-" or v == "—" or v == "未获取":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- 派生指标

def _substitute(expr, series):
    """把中文指标名替换为 __v0.. 变量（长名优先，避免子串误替换）。"""
    mapping = {}
    sub = expr
    for i, k in enumerate(sorted(series.keys(), key=len, reverse=True)):
        var = "__v%d" % i
        sub = sub.replace(k, var)
        mapping[var] = k
    return sub, mapping


def eval_derived(expr, series, n):
    """按季求值派生公式。任一输入缺失则该期输出 None。"""
    sub, mapping = _substitute(expr, series)
    # 校验：公式中引用的变量是否都能对上
    used = set(re.findall(r"__v\d+", sub))
    unknown = [v for v in used if v not in mapping]
    if unknown:
        raise SystemExit("派生公式引用了不存在的指标：%s\n  公式：%s\n  可用指标：%s"
                         % (unknown, expr, "、".join(series.keys())))
    try:
        code = compile(sub, "<kpi>", "eval")
    except SyntaxError as e:
        raise SystemExit("派生公式语法错误：%s（%s）" % (expr, e))
    out = []
    for i in range(n):
        env, ok = {}, True
        # 只对公式实际引用的变量做缺失检查，避免无关指标缺失污染派生结果
        for var in used:
            key = mapping[var]
            vals = series[key]
            v = vals[i] if i < len(vals) else None
            if v is None:
                ok = False
                break
            env[var] = v
        if not ok:
            out.append(None)
            continue
        try:
            out.append(float(eval(code, SAFE_GLOBALS, env)))
        except ZeroDivisionError:
            out.append(None)
        except Exception as e:
            raise SystemExit("派生公式求值失败：%s（%s）" % (expr, e))
    return out


# ---------------------------------------------------------------- 同比环比

def _pq(label):
    m = PERIOD_RE.search(str(label))
    return (int(m.group(1)), int(m.group(2))) if m else None


def yoy(vals, periods):
    """同季对去年同季；标签无法解析时回退为 -4 期。"""
    parsed = [_pq(p) for p in periods]
    out = []
    if all(parsed):
        for i, (y, q) in enumerate(parsed):
            prev = next((j for j, pp in enumerate(parsed)
                         if pp[0] == y - 1 and pp[1] == q), None)
            out.append(_pct(vals[i], vals[prev]) if prev is not None else None)
    else:
        for i in range(len(vals)):
            out.append(_pct(vals[i], vals[i - 4]) if i >= 4 else None)
    return out


def qoq(vals):
    return [_pct(vals[i], vals[i - 1]) if i > 0 else None for i in range(len(vals))]


def _pct(new, old):
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100.0


# ---------------------------------------------------------------- 格式化

INT_UNITS = ("辆", "台", "件", "户", "家", "单", "人", "间", "艘", "架")


def fmt_cell(name, v):
    """按指标名后缀决定显示格式，返回 (文本, css class)。

    水平值一律不着色——「销量 100 万辆」「高端占比 9%」是水平，不是涨跌。
    只有同比/环比等「变化量」列才套红涨绿跌（见 cell_pct）。
    """
    if v is None:
        return ("—", "na")
    s = str(name)
    if "（%）" in s or "(%)" in s:
        return ("%.2f%%" % v, None)
    for u in INT_UNITS:
        if "（%s）" % u in s or "(%s)" % u in s:
            return ("{:,.0f}".format(v), None)
    for u in ("亿元", "万元", "亿美元", "亿"):
        if "（%s）" % u in s or "(%s)" % u in s:
            return ("{:,.2f}".format(v), None)
    a = abs(v)
    if a >= 1000:
        return ("{:,.0f}".format(v), None)
    if a >= 1:
        return ("%.2f" % v, None)
    return ("%.4f" % v, None)


def cell_pct(v):
    return ("—", "na") if v is None else ("%+.1f%%" % v, cell_hint(v))


# ---------------------------------------------------------------- 主流程

def analyze(meta, periods, series, derived_defs):
    n = len(periods)
    warnings = []

    for k, vals in series.items():
        if len(vals) < n:
            vals += [None] * (n - len(vals))
            warnings.append("指标「%s」数据点不足 %d 期，尾部已补空。" % (k, n))
        elif len(vals) > n:
            series[k] = vals[:n]
            warnings.append("指标「%s」数据点多于报告期数，已截断。" % k)

    derived, derived_expr = {}, {}
    for d in derived_defs:
        name = d.get("name")
        expr = d.get("expr")
        if not name or not expr:
            warnings.append("派生定义缺少 name 或 expr，已跳过：%s" % d)
            continue
        derived[name] = eval_derived(expr, series, n)
        derived_expr[name] = expr

    all_series = dict(series)
    all_series.update(derived)

    result = {
        "meta": meta,
        "periods": periods,
        "raw": series,
        "derived": derived,
        "derived_expr": derived_expr,
        "yoy": {k: yoy(v, periods) for k, v in all_series.items()},
        "qoq": {k: qoq(v) for k, v in all_series.items()},
        "trend": {k: trend_features(v) for k, v in all_series.items()},
        "warnings": warnings,
    }
    return result


def render_md(r):
    L, out = r["periods"], []
    out.append("### 行业与公司关键经营指标（KPI 季度序列）\n")
    out.append("> 公司：%s ｜ 行业：%s ｜ 报告期：%s ~ %s\n"
               % (r["meta"].get("公司", "—"), r["meta"].get("行业", "—"), L[0], L[-1]))

    def block(title, mapping, pct_mode=False):
        rows = []
        for k, vals in mapping.items():
            if all(v is None for v in vals):
                continue
            if pct_mode:
                rows.append([k] + [fmt(v, pct_=True, digits=1) for v in vals])
            else:
                rows.append([k] + [fmt_cell(k, v)[0] for v in vals])
        if rows:
            out.append("**%s**\n" % title)
            out.append(md_table(["指标"] + L, rows) + "\n")

    block("原始经营指标", r["raw"])
    if r["derived"]:
        block("派生指标（公式计算，非手填）", r["derived"])
        out.append("> 派生公式为：%s\n" % "；".join(
            "%s = %s" % (k, r["derived_expr"].get(k, "—")) for k in r["derived"]))
    block("同比 YoY（%）", r["yoy"], pct_mode=True)
    block("环比 QoQ（%）", r["qoq"], pct_mode=True)

    out.append("**趋势特征**\n")
    rows = []
    for name, t in r["trend"].items():
        if not t:
            continue
        rows.append([
            name, t["direction"], t["last_step"],
            fmt(t["slope_ann_pct"], pct_=True, digits=1),
            "%d 期" % t["streak"] if t["streak"] else "—",
            fmt(t["cv"], digits=3),
            t["turning_point"] or "—",
        ])
    out.append(md_table(
        ["指标", "方向(按斜率)", "最近一步", "近4季斜率(年化)", "连续同向", "变异系数CV", "拐点"],
        rows) + "\n")

    if r["warnings"]:
        out.append("**⚠️ 数据校验提示**\n")
        out += ["- " + w for w in r["warnings"]]
        out.append("")
    out.append("> 数据缺口填「—」，严禁插值或臆造。派生指标由 `scripts/operating_kpi.py` 按公式计算。")
    return "\n".join(out)


def render_html(r):
    L = r["periods"]
    parts = []

    def emit(title, mapping, pct_mode=False):
        rows = []
        for k, vals in mapping.items():
            if all(v is None for v in vals):
                continue
            if pct_mode:
                rows.append([k] + [cell_pct(v) for v in vals])
            else:
                rows.append([k] + [fmt_cell(k, v) for v in vals])
        if rows:
            parts.append(html_table(["指标"] + L, rows, caption=title))

    emit("原始经营指标", r["raw"])
    if r["derived"]:
        emit("派生指标（公式计算，非手填）", r["derived"])
        formulas = "<br>".join("%s = <code>%s</code>" % (esc(k), esc(r["derived_expr"].get(k, "—")))
                               for k in r["derived"])
        parts.append('<p class="note"><b>派生公式</b>：<br>%s</p>' % formulas)
    emit("同比 YoY（%）", r["yoy"], pct_mode=True)
    emit("环比 QoQ（%）", r["qoq"], pct_mode=True)

    tr = []
    for name, t in r["trend"].items():
        if not t:
            continue
        tr.append([
            name,
            (t["direction"], arrow_cls(t["direction"])),
            (t["last_step"], arrow_cls(t["last_step"])),
            (fmt(t["slope_ann_pct"], pct_=True, digits=1), cell_hint(t["slope_ann_pct"])),
            ("%d 期" % t["streak"] if t["streak"] else "—", None),
            (fmt(t["cv"], digits=3), None),
            (t["turning_point"] or "—", None),
        ])
    if tr:
        parts.append(html_table(
            ["指标", "方向（按斜率）", "最近一步", "近4季斜率（年化）",
             "连续同向", "变异系数 CV", "拐点"],
            tr, caption="经营指标趋势特征"))

    if r["warnings"]:
        w = ['<div class="warn-box"><b>数据校验提示</b><ul>']
        w += ["<li>%s</li>" % esc(x) for x in r["warnings"]]
        w.append("</ul></div>")
        parts.append("\n".join(w))
    parts.append('<p class="note">数据缺口填「—」，严禁插值或臆造；'
                 '派生指标由 <code>scripts/operating_kpi.py</code> 按公式计算，可复算。</p>')
    return "\n\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description="行业与公司关键经营指标（KPI）季度序列工具")
    ap.add_argument("--input", required=True, help="KPI 数据文件（.json 或 .csv）")
    ap.add_argument("--derived", help="派生指标定义 JSON 文件（CSV 输入时使用）")
    ap.add_argument("--out", default="md", choices=["md", "html", "json"])
    a = ap.parse_args()

    meta, periods, series, derived_defs = load_input(a.input, a.derived)
    r = analyze(meta, periods, series, derived_defs)
    if a.out == "json":
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif a.out == "html":
        print(render_html(r))
    else:
        print(render_md(r))


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quarterly_trend.py —— 财报季度序列趋势工具

把 westock-mcp `data_finance` 返回的【累计口径】定期报告数据，拆算为【单季口径】
序列，并计算 YoY / QoQ / TTM 与趋势特征，输出 Markdown 表格，供
financial-report-analysis 技能的「季度明细数据与趋势诊断」章节直接引用。

只输出趋势特征与口径告警，不做「健康/关注/预警」投资定档。

用法:
    python3 quarterly_trend.py --input sh600519.json --market A  --quarters 8
    python3 quarterly_trend.py --input hk00700.json  --market HK --quarters 8
    python3 quarterly_trend.py --input msft.json     --market US --fy-end 6
    python3 quarterly_trend.py --input data.json --out json
"""

import argparse
import json
import math
import sys
from datetime import date

# ---------------------------------------------------------------- 字段映射

FIELDS = {
    "A": {
        "revenue":      "OperatingRevenue",
        "revenue_tot":  "TotalOperatingRevenue",
        "np_parent":    "NPParentCompanyOwners",
        "np_deduct":    "NPDeductNonRecurringPL",
        "gm":           "GrossIncomeRatio",        # 累计毛利率 %
        "ocf":          "NetOperateCashFlow",
        "sale_cash":    "GoodsSaleServiceRenderCash",
        "roe":          "ROE",                     # 累计期口径
        "roic":         "ROIC",
        "rev_ttm":      "OperatingRevenueTTM",
        "np_ttm":       "NPParentCompanyOwnersTTM",
        "ocf_ttm":      "NetOperateCashFlowTTM",
        "roe_ttm":      "ROETTM",
        "debt_ratio":   "DebtAssetsRatio",         # balance
        "equity":       "SEWithoutMI",             # balance
        "cash":         "CashEquivalents",         # balance
        "inventories":  "Inventories",             # balance, 需 fields=all
        "contract_liab": "ContractLiability",      # balance, 需 fields=all
        "ar_rate":      "ARTRate",                 # balance, 累计期周转率
        "inv_rate":     "InventoryTRate",
    },
    "HK": {
        "revenue":      "OperatingIncome",
        "revenue_tot":  "OperatingIncome",
        "np_parent":    "ProfitToShareholders",
        "np_deduct":    None,                      # 港股无扣非
        "gm":           "GrossIncomeRatio",
        "ocf":          "CFO",
        "sale_cash":    None,                      # 港股无销售收现，收现比不可算
        "roe":          "RoeWeighted",
        "roic":         None,
        "rev_ttm":      None,
        "np_ttm":       None,
        "ocf_ttm":      None,
        "roe_ttm":      None,
        "debt_ratio":   "DebtAssetsRatio",         # 港股在 income 里
        "equity":       "SeWithoutMinority",       # balance
        "cash":         "Cash",                    # balance
        "inventories":  None,
        "contract_liab": None,
        "ar_rate":      None,
        "inv_rate":     None,
    },
}
FIELDS["US"] = FIELDS["HK"]

# 数据缺口的人话标签
GAP_LABELS = {
    "np_deduct": "扣非净利（该市场无扣非口径）",
    "sale_cash": "销售商品收到现金（收现比不可算）",
    "rev_ttm":   "官方 TTM 字段（须自算滚动 12 个月）",
}


# ---------------------------------------------------------------- 工具函数

def num(v):
    """安全转 float，失败返回 None。"""
    if v is None or v == "" or v == "-":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_date(s):
    y, m, d = str(s)[:10].split("-")
    return date(int(y), int(m), int(d))


def fiscal_year(d, fy_end_month):
    return d.year if d.month <= fy_end_month else d.year + 1


def period_label(d, fy_end_month):
    """给出 '2026Q2' 这样的标签（按日历年季度，便于阅读）。"""
    return "%dQ%d" % (d.year, (d.month - 1) // 3 + 1)


def locate_tables(raw):
    """从 data_finance 返回体中定位 income/balance/cashflow 列表。"""
    node = raw
    if "data" in node and isinstance(node["data"], dict):
        node = node["data"]
    # 形如 {code: {income: [...], ...}}
    for _ in range(2):
        if isinstance(node, dict):
            keys = {k.lower() for k in node.keys()}
            if {"income", "balance", "cashflow"} & keys:
                break
            vals = [v for v in node.values() if isinstance(v, (dict, list))]
            if len(vals) == 1:
                node = vals[0]
            else:
                break
    if isinstance(node, dict) and not ({"income", "balance"} & {k.lower() for k in node}):
        # 形如 {code: [ {...}, {...} ]}（指定 type 时的返回）
        vals = [v for v in node.values() if isinstance(v, list)]
        if vals:
            return {"rows": vals[0]}
    out = {}
    for k, v in node.items():
        if isinstance(v, list):
            out[k.lower()] = v
    return out


def index_by_date(rows):
    """{date_obj: row}"""
    out = {}
    for r in rows:
        d = r.get("EndDate") or r.get("date") or r.get("_date")
        if d:
            out[parse_date(d)] = r
    return out


def report_months(fy_end_month, ppy):
    """财年内各报告期月份集合。fy_end=12,ppy=4 -> {3,6,9,12}；fy_end=12,ppy=2 -> {6,12}。"""
    step = 12 // ppy
    return sorted(((fy_end_month - (ppy - i) * step - 1) % 12 + 1) for i in range(ppy))


def to_single_period(dates_sorted, series_cum, fy_end_month, ppy=4):
    """累计 -> 单季。同一财年内：Q_i = C_i - C_{i-1}；财年内首个报告期 = 自身。

    若某期在序列中是该财年最早的期间，但其月份并非该财年的首个报告期
    （说明更早的累计值缺失，如序列从 Q3 开始），则单季值不可拆，返回 None。
    """
    months = report_months(fy_end_month, ppy)
    first_month = months[0]
    single, prev_fy, prev_val = {}, None, None
    for d in dates_sorted:
        c = series_cum.get(d)
        fy = fiscal_year(d, fy_end_month)
        if c is None:
            single[d] = None
        elif fy != prev_fy:
            # 该财年在序列中的第一个期间
            single[d] = c if d.month == first_month else None
        elif prev_val is None:
            single[d] = None          # 前一期不可拆，本期连锁不可拆
        else:
            single[d] = c - prev_val
        prev_fy, prev_val = fy, c
    return single


def ratio_single(dates_sorted, cum_value, cum_ratio_pct, fy_end_month, ppy=4):
    """累计比率(%) -> 单季比率：还原分子再相除。返回 {date: 单季比率 %} 或 None。"""
    months = report_months(fy_end_month, ppy)
    first_month = months[0]
    single = {}
    prev_fy, prev_c, prev_r = None, None, None
    for d in dates_sorted:
        c, r = cum_value.get(d), cum_ratio_pct.get(d)
        fy = fiscal_year(d, fy_end_month)
        if c is None or r is None:
            single[d] = None
        elif fy != prev_fy:
            single[d] = r if d.month == first_month else None
        elif prev_c is None or prev_r is None:
            single[d] = None
        else:
            denom = c - prev_c
            single[d] = ((c * r - prev_c * prev_r) / denom) if denom else None
        prev_fy, prev_c, prev_r = fy, c, r
    return single


def pct(new, old):
    if new is None or old is None or old == 0:
        return None
    return (new - old) / abs(old) * 100.0


def trend_features(values):
    """输入按时间升序的单季序列（含 None），输出趋势特征。"""
    pairs = [(i, v) for i, v in enumerate(values) if v is not None]
    vals = [v for _, v in pairs]
    n = len(vals)
    if n == 0:
        return {}
    recent = vals[-4:] if n >= 4 else vals

    # 斜率：对最近 4 期做最小二乘，年化（每期=1季）
    slope_ann = None
    if len(recent) >= 3:
        xs = list(range(len(recent)))
        mx, my = sum(xs) / len(xs), sum(recent) / len(recent)
        den = sum((x - mx) ** 2 for x in xs)
        if den and my:
            k = sum((x - mx) * (y - my) for x, y in zip(xs, recent)) / den
            slope_ann = k * 4 / abs(my) * 100.0  # %/年

    # 连续同向期数（从最近往前，0.5% 阈值过滤噪音）
    streak, step_sign = 0, 0
    for i in range(n - 1, 0, -1):
        step = vals[i] - vals[i - 1]
        sign = 0
        if vals[i - 1] and abs(step) / abs(vals[i - 1]) > 0.005:
            sign = 1 if step > 0 else -1
        if sign == 0:
            break
        if streak == 0:
            step_sign = sign
        if sign == step_sign:
            streak += 1
        else:
            break

    # 变异系数（波动性）
    cv = None
    if n >= 3:
        mu = sum(vals) / n
        if abs(mu) > 1e-12:
            var = sum((v - mu) ** 2 for v in vals) / (n - 1)
            cv = math.sqrt(var) / abs(mu)

    # 拐点：前后半段净变化方向反转
    turn = None
    if n >= 6:
        mid = n // 2
        k1, k2 = vals[mid - 1] - vals[0], vals[-1] - vals[mid]
        if k1 > 0 and k2 < 0:
            turn = "由升转降"
        elif k1 < 0 and k2 > 0:
            turn = "由降转升"

    # 方向以斜率为准（避免被季节性单季跳动误导），另记最近一步
    if slope_ann is None:
        direction = "→"
    elif slope_ann > 2:
        direction = "↑"
    elif slope_ann < -2:
        direction = "↓"
    else:
        direction = "→"

    return {
        "slope_ann_pct": slope_ann,
        "streak": streak,
        "direction": direction,
        "last_step": {1: "↑", -1: "↓", 0: "→"}[step_sign],
        "cv": cv,
        "turning_point": turn,
        "n": n,
    }


def seasonality(dates_sorted, values, fy_end_month, ppy=4):
    """季节性强度 = 各报告期月份均值的离散度 / 总均值。>0.15 视为强季节性。"""
    by_month = {}
    for d, v in zip(dates_sorted, values):
        if v is not None:
            by_month.setdefault(d.month, []).append(v)
    # 只保留有跨年重复的月份（≥2 个年份）
    avgs = [sum(vs) / len(vs) for vs in by_month.values() if len(vs) >= 2]
    if len(avgs) < 2:
        return None
    mu = sum(avgs) / len(avgs)
    if abs(mu) < 1e-12:
        return None
    var = sum((a - mu) ** 2 for a in avgs) / (len(avgs) - 1)
    return math.sqrt(var) / abs(mu)


def fmt(v, unit="", pct_=False, digits=2):
    if v is None:
        return "—"
    if pct_:
        return ("%." + str(digits) + "f%%") % v
    if unit == "亿":
        return ("%." + str(digits) + "f") % (v / 1e8)
    return ("%." + str(digits) + "f") % v


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


# ---------------------------------------------------------------- 主流程

def analyze(raw, market="A", quarters=8, fy_end=12, ppy=4):
    F = FIELDS.get(market, FIELDS["A"])
    tables = locate_tables(raw)
    inc_rows = tables.get("income") or tables.get("rows") or []
    cf_rows = tables.get("cashflow") or []
    bs_rows = tables.get("balance") or []

    inc = index_by_date(inc_rows)
    cf = index_by_date(cf_rows)
    bs = index_by_date(bs_rows)

    # 拆单季需要财年内更早的累计值，故先加载全部期，输出时再截取最后 quarters 期
    all_dates = sorted(inc.keys() or cf.keys() or bs.keys())
    if not all_dates:
        raise SystemExit("未能在输入中定位到任何报告期数据，请检查 JSON 结构。")
    dates = all_dates[-quarters:]

    def series(rows_idx, key):
        if not key:
            return {d: None for d in all_dates}
        return {d: num((rows_idx.get(d) or {}).get(key)) for d in all_dates}

    cum_rev = series(inc, F["revenue"])
    cum_np = series(inc, F["np_parent"])
    cum_ded = series(inc, F["np_deduct"]) if F["np_deduct"] else {d: None for d in all_dates}
    cum_ocf = series(cf, F["ocf"])
    cum_sc = series(cf, F["sale_cash"]) if F["sale_cash"] else {d: None for d in all_dates}
    cum_gm = series(inc, F["gm"])

    # 累计 -> 单季
    q_rev = to_single_period(all_dates, cum_rev, fy_end, ppy)
    q_np = to_single_period(all_dates, cum_np, fy_end, ppy)
    q_ded = to_single_period(all_dates, cum_ded, fy_end, ppy)
    q_ocf = to_single_period(all_dates, cum_ocf, fy_end, ppy)
    q_sc = to_single_period(all_dates, cum_sc, fy_end, ppy)
    q_gm = ratio_single(all_dates, cum_rev, cum_gm, fy_end, ppy)
    q_npm = {d: (q_np[d] / q_rev[d] * 100 if q_np[d] is not None and q_rev.get(d) else None)
             for d in all_dates}
    q_scr = {d: (q_sc[d] / q_rev[d] if q_sc[d] is not None and q_rev.get(d) else None)
             for d in all_dates}
    q_dedr = {d: (q_ded[d] / q_np[d] * 100 if q_ded[d] is not None and q_np.get(d) else None)
              for d in all_dates}

    # 时点类（不拆单季）
    pt_debt = series(bs, F["debt_ratio"]) if F["debt_ratio"] else {d: None for d in all_dates}
    if all(v is None for v in pt_debt.values()):
        pt_debt = series(inc, F["debt_ratio"])
    pt_inv = (series(bs, F["inventories"]) if F["inventories"]
              else {d: None for d in all_dates})
    pt_ar = series(bs, F["ar_rate"]) if F["ar_rate"] else {d: None for d in all_dates}
    pt_invr = series(bs, F["inv_rate"]) if F["inv_rate"] else {d: None for d in all_dates}

    # TTM：优先官方字段，缺失则自算近 4 季（窗口内必须全部可拆）
    off_rev_ttm = series(inc, F["rev_ttm"]) if F["rev_ttm"] else {d: None for d in all_dates}
    off_np_ttm = series(inc, F["np_ttm"]) if F["np_ttm"] else {d: None for d in all_dates}
    off_ocf_ttm = series(cf, F["ocf_ttm"]) if F["ocf_ttm"] else {d: None for d in all_dates}

    def ttm_from(q):
        out = {}
        for i, d in enumerate(all_dates):
            win = [q[dd] for dd in all_dates[max(0, i - 3):i + 1]]
            out[d] = sum(win) if len(win) == 4 and all(v is not None for v in win) else None
        return out

    calc_rev_ttm, calc_np_ttm, calc_ocf_ttm = ttm_from(q_rev), ttm_from(q_np), ttm_from(q_ocf)

    warnings = []
    for name, off, calc in (("营收TTM", off_rev_ttm, calc_rev_ttm),
                            ("归母TTM", off_np_ttm, calc_np_ttm),
                            ("OCF_TTM", off_ocf_ttm, calc_ocf_ttm)):
        for d in dates:
            a, b = off.get(d), calc.get(d)
            if a and b and abs(a - b) / abs(a) > 0.02:
                warnings.append(
                    "%s：%s 官方值 %.2f 亿 vs 自算 %.2f 亿（差异 %.1f%%），请核对财年分组或单季拆算"
                    % (name, d, a / 1e8, b / 1e8, (b - a) / a * 100))

    # YoY：同月对去年（天然剔除季节性，趋势判断的主口径）
    def yoy(q):
        out = {}
        for d in all_dates:
            prev = next((dd for dd in all_dates
                         if dd.year == d.year - 1 and dd.month == d.month), None)
            out[d] = pct(q[d], q[prev]) if prev else None
        return out

    def qoq(q):
        out = {}
        for i, d in enumerate(all_dates):
            prev = all_dates[i - 1] if i > 0 else None
            out[d] = pct(q[d], q[prev]) if prev else None
        return out

    # TTM 不足 4 个可拆单季时提示
    if all(v is None for v in (off_rev_ttm.get(d) or calc_rev_ttm.get(d) for d in dates)):
        warnings.append(
            "TTM 无法计算：可拆的单季不足 4 期。请增加 data_finance 的 num 取值（建议 12 期）。")
    # 首期不可拆告警
    seasons = seasonality(all_dates, [q_rev[d] for d in all_dates], fy_end, ppy)
    head_unusable = [d for d in dates if q_rev.get(d) is None and cum_rev.get(d) is not None]
    if head_unusable:
        warnings.append(
            "以下期次的单季值无法拆算（序列缺少该财年更早的累计值）：%s。"
            "建议 data_finance 取 num=quarters+%d 期，脚本会自动多取并只输出最后 %d 期。"
            % ("、".join(str(d) for d in head_unusable), ppy, quarters))
    if seasons and seasons > 0.15:
        warnings.append(
            "营收季节性强度 %.2f（>0.15）：QoQ 环比不可直接读，请以 YoY 同季对比为准。" % seasons)

    labels = [period_label(d, fy_end) for d in dates]

    result = {
        "market": market, "periods": [str(d) for d in dates], "labels": labels,
        "quarterly": {
            "营业收入(元)": [q_rev[d] for d in dates],
            "归母净利(元)": [q_np[d] for d in dates],
            "扣非归母(元)": [q_ded[d] for d in dates],
            "毛利率(%)": [q_gm[d] for d in dates],
            "净利率(%)": [q_npm[d] for d in dates],
            "扣非/归母(%)": [q_dedr[d] for d in dates],
            "经营现金流(元)": [q_ocf[d] for d in dates],
            "收现比(倍)": [q_scr[d] for d in dates],
        },
        "ttm": {
            "营收TTM(元)": [off_rev_ttm.get(d) or calc_rev_ttm.get(d) for d in dates],
            "归母TTM(元)": [off_np_ttm.get(d) or calc_np_ttm.get(d) for d in dates],
            "OCF_TTM(元)": [off_ocf_ttm.get(d) or calc_ocf_ttm.get(d) for d in dates],
        },
        "point_in_time": {
            "资产负债率(%)": [pt_debt.get(d) for d in dates],
            "存货(元)": [pt_inv.get(d) for d in dates],
            "应收周转率(累计期)": [pt_ar.get(d) for d in dates],
            "存货周转率(累计期)": [pt_invr.get(d) for d in dates],
        },
        "yoy": {
            "营收YoY(%)": [yoy(q_rev)[d] for d in dates],
            "归母YoY(%)": [yoy(q_np)[d] for d in dates],
            "OCF_YoY(%)": [yoy(q_ocf)[d] for d in dates],
        },
        "qoq": {"营收QoQ(%)": [qoq(q_rev)[d] for d in dates]},
        "trend": {
            "营业收入": trend_features([q_rev[d] for d in dates]),
            "归母净利": trend_features([q_np[d] for d in dates]),
            "扣非归母": trend_features([q_ded[d] for d in dates]),
            "毛利率": trend_features([q_gm[d] for d in dates]),
            "净利率": trend_features([q_npm[d] for d in dates]),
            "经营现金流": trend_features([q_ocf[d] for d in dates]),
            "收现比": trend_features([q_scr[d] for d in dates]),
        },
        "seasonality_strength": seasons,
        "warnings": warnings,
        "data_gaps": [GAP_LABELS[k] for k in ("np_deduct", "sale_cash", "rev_ttm")
                      if not F.get(k)],
    }
    return result


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def html_table(headers, rows, caption=None, first_col_left=True):
    """生成 HTML 表格片段，可直接嵌入 assets/report_template.html。

    数值着色遵循 A 股习惯：正=红(up)、负=绿(down)。
    """
    out = ['<div class="tbl-scroll">', "<table>"]
    if caption:
        out.append("<caption>%s</caption>" % esc(caption))
    out.append("<thead><tr>")
    for i, h in enumerate(headers):
        cls = "" if (i == 0 and first_col_left) else " class=\"num\""
        out.append("<th%s>%s</th>" % (cls, esc(h)))
    out.append("</tr></thead>")
    out.append("<tbody>")
    for row in rows:
        out.append("<tr>")
        for i, cell in enumerate(row):
            text, cls = cell if isinstance(cell, tuple) else (cell, None)
            if i == 0 and first_col_left:
                out.append("<td>%s</td>" % esc(text))
            else:
                cls_attr = (' class="num %s"' % cls) if cls else ' class="num"'
                out.append("<td%s>%s</td>" % (cls_attr, esc(text)))
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def arrow_cls(arrow):
    """方向箭头 -> CSS class（红涨绿跌）。"""
    return {"↑": "up", "↓": "down"}.get(arrow, "flat")


def cell_hint(v):
    """数值单元格的正负着色 class（正=红 up，负=绿 down）。"""
    if v is None:
        return None
    return "up" if v > 0 else ("down" if v < 0 else "flat")


def cell_for_html(name, v, colorize=False):
    """按指标名与数值生成 (显示文本, class)。

    colorize=False（默认）：水平值（金额、比率、TTM、时点值）不着色——
    「销量 100 万辆」「毛利率 20%」是水平，不是涨跌，不应套红涨绿跌。
    colorize=True：仅用于同比/环比等「变化量」列。
    """
    if v is None:
        return ("—", "na")
    if "(元)" in name:
        return ("%.2f" % (v / 1e8), None)
    if "(%)" in name:
        return ("%.2f%%" % v, cell_hint(v) if colorize else None)
    return ("%.3f" % v, cell_hint(v) if colorize else None)


def render_html(r):
    """输出 HTML 片段（季度明细各表），可直接嵌入报告 1.2 节。"""
    L = r["labels"]
    parts = []

    def label_of(k):
        """去掉单位后缀，作为表格首列显示名。"""
        return k.replace("(元)", "").strip()

    def emit(title, mapping, colorize=False):
        rows = []
        for k, vals in mapping.items():
            if all(v is None for v in vals):
                continue
            rows.append([label_of(k)] + [cell_for_html(k, v, colorize) for v in vals])
        if rows:
            parts.append(html_table(["指标"] + L, rows, caption=title))

    emit("单季金额（亿元）", {k: v for k, v in r["quarterly"].items() if "(元)" in k})
    emit("单季比率", {k: v for k, v in r["quarterly"].items() if "(元)" not in k})
    emit("TTM（滚动 12 个月，亿元）", r["ttm"])

    yoy_rows = [[label_of(k), *[cell_for_html(k, v, True) for v in vals]]
                for k, vals in r["yoy"].items()]
    yoy_rows += [[label_of(k), *[cell_for_html(k, v, True) for v in vals]]
                 for k, vals in r["qoq"].items()]
    parts.append(html_table(["指标"] + L, yoy_rows, caption="同比 / 环比（%）"))

    pit = {k: v for k, v in r["point_in_time"].items() if not all(x is None for x in v)}
    if pit:
        pit_rows = [[label_of(k), *[cell_for_html(k, v) for v in vals]]
                    for k, vals in pit.items()]
        parts.append(html_table(["指标"] + L, pit_rows,
                                caption="时点指标（期末值，不拆单季）"))

    # 趋势特征表
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
        head = ["指标", "方向（按斜率）", "最近一步", "近4季斜率（年化）",
                "连续同向", "变异系数 CV", "拐点"]
        parts.append(html_table(head, tr, caption="趋势特征"))

    # 告警块
    if r["warnings"]:
        w = ["<div class=\"warn-box\"><b>口径告警</b><ul>"]
        w += ["<li>%s</li>" % esc(x) for x in r["warnings"]]
        w.append("</ul></div>")
        parts.append("\n".join(w))
    if r["data_gaps"]:
        parts.append("<p class=\"note\">数据缺口（该市场无此字段，勿臆造）：%s</p>"
                     % esc("、".join(r["data_gaps"])))
    if r.get("seasonality_strength") is not None:
        parts.append(
            "<p class=\"note\">营收季节性强度：<b>%.2f</b>%s</p>"
            % (r["seasonality_strength"],
               "（&gt;0.15 为强季节性，QoQ 不可直接读，请以 YoY 同季对比为准）"
               if r["seasonality_strength"] > 0.15 else "（季节性不显著）"))
    return "\n\n".join(parts)


def render_md(r):
    L = r["labels"]
    out = []
    out.append("### 季度明细数据（单季口径）\n")
    out.append("> 单季 = 本期累计 − 上期累计（同期财年内）。金额单位：亿元。\n")

    def cells_for(name, vals):
        if "(元)" in name:
            return [fmt(v, "亿") for v in vals]
        if "(%)" in name:
            return [fmt(v, pct_=True) for v in vals]
        return [fmt(v, digits=3) for v in vals]  # 倍数类（收现比）

    def block(title, mapping):
        rows = [[k, *cells_for(k, vals)] for k, vals in mapping.items()
                if not all(v is None for v in vals)]
        if rows:
            out.append("**%s**\n" % title)
            out.append(md_table(["指标"] + L, rows) + "\n")

    block("单季金额（亿元）", {k: v for k, v in r["quarterly"].items() if "(元)" in k})
    block("单季比率", {k: v for k, v in r["quarterly"].items() if "(元)" not in k})

    out.append("**TTM（滚动 12 个月，亿元）**\n")
    out.append(md_table(["指标"] + L,
                        [[k, *cells_for(k, vals)] for k, vals in r["ttm"].items()]) + "\n")

    out.append("**同比 / 环比**\n")
    rows = [[k, *cells_for(k, vals)] for k, vals in r["yoy"].items()]
    rows += [[k, *cells_for(k, vals)] for k, vals in r["qoq"].items()]
    out.append(md_table(["指标"] + L, rows) + "\n")
    out.append("> YoY = 同季对去年同季（天然剔除季节性，趋势判断主口径）；"
               "QoQ = 环比值，强季节性行业须与去年同期 QoQ 对照后再解读。\n")

    out.append("**时点指标（期末值，不拆单季）**\n")
    rows = []
    for k, vals in r["point_in_time"].items():
        if all(v is None for v in vals):
            continue
        if "周转率" in k:
            cells = [fmt(v, digits=2) + " ⚠️" for v in vals]
        else:
            cells = cells_for(k, vals)
        rows.append([k] + cells)
    if rows:
        out.append(md_table(["指标"] + L, rows) + "\n")
        out.append("> ⚠️ 周转率为累计期口径，禁止跨季度横向比较，只能与去年同期同口径对比。\n")

    out.append("### 趋势特征（近 4 季斜率 / 连续同向期数 / 波动）\n")
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
    if r.get("seasonality_strength") is not None:
        out.append("> 营收季节性强度：%.2f（>0.15 为强季节性，QoQ 不可直接读）\n"
                   % r["seasonality_strength"])

    notes = []
    if r["data_gaps"]:
        notes.append("数据缺口（该市场无此字段，勿臆造）：" + "、".join(r["data_gaps"]))
    notes.append("定档规则见 `references/quarterly_trend_analysis.md` 第 5 节；脚本只给特征，不做投资判断。")
    if r["warnings"]:
        out.append("### ⚠️ 口径告警\n")
        out += ["- " + w for w in r["warnings"]]
        out.append("")
    out.append("> " + "　".join(notes))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="财报季度序列趋势工具")
    ap.add_argument("--input", required=True, help="data_finance 返回体的 JSON 文件")
    ap.add_argument("--market", default="A", choices=["A", "HK", "US"])
    ap.add_argument("--quarters", type=int, default=8)
    ap.add_argument("--fy-end", type=int, default=12, help="财年结束月份，默认 12")
    ap.add_argument("--ppy", type=int, default=4, choices=[1, 2, 4],
                    help="每年报告期数：A股/美股季报=4，港股半年报=2（默认 4）")
    ap.add_argument("--out", default="md", choices=["md", "html", "json"],
                    help="md=Markdown 报告片段；html=HTML 表格片段（直接嵌入 HTML 报告）；json=原始数据")
    a = ap.parse_args()

    with open(a.input, "r", encoding="utf-8") as f:
        raw = json.load(f)

    r = analyze(raw, a.market, a.quarters, a.fy_end, a.ppy)
    if a.out == "json":
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif a.out == "html":
        print(render_html(r))
    else:
        print(render_md(r))


if __name__ == "__main__":
    sys.exit(main())

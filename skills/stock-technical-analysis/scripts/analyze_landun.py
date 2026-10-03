#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蓝盾光电(300862.SZ)技术面分析数据处理脚本
- 从选股魔方REST API获取数据
- 计算技术指标(MA/MACD/KDJ/RSI/BOLL)
- 生成自包含HTML报告
"""

import json
import subprocess
import sys
import os
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.join(SKILL_DIR, "scripts")

def call_api(tool, arguments):
    """调用选股魔方REST API"""
    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "call_tool.py"),
        "--tool", tool,
        "--arguments", json.dumps(arguments, ensure_ascii=False)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=SKILL_DIR)
    if result.returncode != 0:
        print(f"API调用失败: {tool}, exit={result.returncode}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return None
    return json.loads(result.stdout)

def calc_ma(closes, period):
    """计算移动平均线"""
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def calc_ema(values, period):
    """计算EMA"""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema

def calc_ema_series(values, period):
    """计算EMA序列"""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    result = [None] * (period - 1) + [ema]
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
        result.append(ema)
    return result

def calc_macd(closes, fast=12, slow=26, signal=9):
    """计算MACD"""
    if len(closes) < slow:
        return None, None, None, None, None
    ema_fast = calc_ema_series(closes, fast)
    ema_slow = calc_ema_series(closes, slow)
    dif_list = []
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            dif_list.append(ema_fast[i] - ema_slow[i])
        else:
            dif_list.append(None)
    valid_dif = [d for d in dif_list if d is not None]
    if len(valid_dif) < signal:
        dif = dif_list[-1] if dif_list[-1] else None
        return dif, None, None, None, None
    dea_list = calc_ema_series(valid_dif, signal)
    # Align
    dif = valid_dif[-1]
    dea = dea_list[-1]
    macd = 2 * (dif - dea)
    # 判断金叉/死叉
    cross = None
    if len(valid_dif) >= 2 and len(dea_list) >= 2:
        prev_dif = valid_dif[-2]
        prev_dea = dea_list[-2]
        if prev_dif <= prev_dea and dif > dea:
            cross = "金叉"
        elif prev_dif >= prev_dea and dif < dea:
            cross = "死叉"
    return dif, dea, macd, cross, dif_list

def calc_kdj(highs, lows, closes, n=9):
    """计算KDJ"""
    if len(closes) < n:
        return None, None, None, None
    k, d = 50.0, 50.0
    k_list, d_list = [], []
    for i in range(len(closes)):
        start = max(0, i - n + 1)
        hh = max(highs[start:i+1])
        ll = min(lows[start:i+1])
        if hh == ll:
            rsv = 50
        else:
            rsv = (closes[i] - ll) / (hh - ll) * 100
        k = 2/3 * k + 1/3 * rsv
        d = 2/3 * d + 1/3 * k
        j = 3 * k - 2 * d
        k_list.append(k)
        d_list.append(d)
    # 判断交叉
    cross = None
    if len(k_list) >= 2 and len(d_list) >= 2:
        if k_list[-2] <= d_list[-2] and k_list[-1] > d_list[-1]:
            cross = "金叉"
        elif k_list[-2] >= d_list[-2] and k_list[-1] < d_list[-1]:
            cross = "死叉"
    return k, d, j, cross

def calc_rsi(closes, period=14):
    """计算RSI"""
    if len(closes) < period + 1:
        return None, None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    if len(gains) < period:
        return None, None
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        rsi = 100
    else:
        rs = avg_gain / avg_loss
        rsi = 100 - 100 / (1 + rs)
    # RSI6
    if len(gains) >= 6:
        avg_gain6 = sum(gains[:6]) / 6
        avg_loss6 = sum(losses[:6]) / 6
        for i in range(6, len(gains)):
            avg_gain6 = (avg_gain6 * 5 + gains[i]) / 6
            avg_loss6 = (avg_loss6 * 5 + losses[i]) / 6
        if avg_loss6 == 0:
            rsi6 = 100
        else:
            rs6 = avg_gain6 / avg_loss6
            rsi6 = 100 - 100 / (1 + rs6)
    else:
        rsi6 = None
    return rsi6, rsi

def calc_boll(closes, period=20, nbdev=2):
    """计算布林带"""
    if len(closes) < period:
        return None, None, None, None
    ma = sum(closes[-period:]) / period
    variance = sum((c - ma) ** 2 for c in closes[-period:]) / period
    std = variance ** 0.5
    upper = ma + nbdev * std
    lower = ma - nbdev * std
    # 判断开口
    if len(closes) >= period * 2:
        prev_ma = sum(closes[-period*2:-period]) / period
        prev_var = sum((c - prev_ma) ** 2 for c in closes[-period*2:-period]) / period
        prev_std = prev_var ** 0.5
        if std > prev_std * 1.1:
            width = "开口放大"
        elif std < prev_std * 0.9:
            width = "收口"
        else:
            width = "平稳"
    else:
        width = "数据不足"
    return upper, ma, lower, width

def main():
    print("=== 开始获取数据 ===")

    # 1. 周K数据
    print("获取周K数据...")
    week_data = call_api("kline_range", {"sec_id": "300862.SZ", "period": "week", "start": "20240101", "end": "20260821"})
    week_klines = week_data["data"]["data"]["300862.SZ"]
    week_fields = week_data["data"]["data"]["fields"]

    # 2. 月K数据
    print("获取月K数据...")
    month_data = call_api("kline_range", {"sec_id": "300862.SZ", "period": "month", "start": "20240101", "end": "20260821"})
    month_klines = month_data["data"]["data"]["300862.SZ"]

    # 3. 趋势数据(分时，取metadata构建日K)
    print("获取分时数据...")
    trend_data = call_api("trend", {"sec_id": "300862.SZ", "days": 30})
    trend_meta = trend_data["data"]["data"]["metadata"]

    # 4. 融资融券
    print("获取融资融券数据...")
    margin_data = call_api("company_f10", {"datasets": ["MARGIN_TRADE"], "sec_id": "300862.SZ"})

    # 5. 公司信息
    print("获取公司信息...")
    comp_data = call_api("company_f10", {"datasets": ["COMP_DETAIL", "SW_INDUSTRY", "CAP_LATEST"], "sec_id": "300862.SZ"})

    # === 处理周K数据 ===
    print("\n=== 处理周K数据 ===")
    week_closes = [k[5] for k in week_klines]  # close_price
    week_highs = [k[4] for k in week_klines]
    week_lows = [k[3] for k in week_klines]
    week_opens = [k[2] for k in week_klines]
    week_dates = [str(k[0]) for k in week_klines]
    week_volumes = [k[6] for k in week_klines]
    week_ddx = [k[13] for k in week_klines]

    # 周线MA
    week_ma5 = calc_ma(week_closes, 5)
    week_ma10 = calc_ma(week_closes, 10)
    week_ma20 = calc_ma(week_closes, 20)
    week_ma30 = calc_ma(week_closes, 30)

    print(f"周K数据: {len(week_klines)}根")
    print(f"最新周K: date={week_dates[-1]}, close={week_closes[-1]}")
    print(f"周MA5={week_ma5}, MA10={week_ma10}, MA20={week_ma20}, MA30={week_ma30}")

    # 周线MACD
    w_dif, w_dea, w_macd, w_cross, _ = calc_macd(week_closes)
    print(f"周MACD: DIF={w_dif}, DEA={w_dea}, MACD={w_macd}, cross={w_cross}")

    # 周线KDJ
    w_k, w_d, w_j, w_kdj_cross = calc_kdj(week_highs, week_lows, week_closes)
    print(f"周KDJ: K={w_k:.2f}, D={w_d:.2f}, J={w_j:.2f}, cross={w_kdj_cross}")

    # 周线RSI
    w_rsi6, w_rsi14 = calc_rsi(week_closes)
    print(f"周RSI: RSI6={w_rsi6:.2f}, RSI14={w_rsi14:.2f}" if w_rsi6 and w_rsi14 else "周RSI: 数据不足")

    # 周线BOLL
    w_boll_up, w_boll_mid, w_boll_low, w_boll_width = calc_boll(week_closes)
    print(f"周BOLL: upper={w_boll_up}, mid={w_boll_mid}, lower={w_boll_low}, {w_boll_width}")

    # === 处理月K数据 ===
    print("\n=== 处理月K数据 ===")
    month_closes = [k[5] for k in month_klines]
    month_highs = [k[4] for k in month_klines]
    month_lows = [k[3] for k in month_klines]
    month_dates = [str(k[0]) for k in month_klines]

    month_ma5 = calc_ma(month_closes, 5)
    month_ma10 = calc_ma(month_closes, 10)
    month_ma24 = calc_ma(month_closes, 24) if len(month_closes) >= 24 else None

    m_dif, m_dea, m_macd, m_cross, _ = calc_macd(month_closes)
    m_k, m_d, m_j, m_kdj_cross = calc_kdj(month_highs, month_lows, month_closes)

    print(f"月K数据: {len(month_klines)}根")
    print(f"月MA5={month_ma5}, MA10={month_ma10}, MA24={month_ma24}")
    print(f"月MACD: DIF={m_dif}, DEA={m_dea}, cross={m_cross}")

    # === 从趋势metadata构建日K ===
    print("\n=== 构建日K数据(从分时metadata) ===")
    # metadata中有每天的pre_px, 可以用相邻日期的pre_px推算close
    # pre_px[i] 是第i天的前收 = 第i-1天的收盘
    # 所以 close[i-1] = pre_px[i]
    daily_data = []
    for i in range(len(trend_meta)):
        dt = trend_meta[i]["dt"]
        pre_px = trend_meta[i]["pre_px"]
        mshare = trend_meta[i].get("mshare", 0)
        # close = 当日收盘, pre_px = 前一日收盘
        # 当日收盘 = 下一日的pre_px
        if i + 1 < len(trend_meta):
            close = trend_meta[i + 1]["pre_px"]
        else:
            # 最后一天，用snapshot的pre_close
            close = 56.5  # from snapshot pre_close_price
        # open = pre_px (当日前收作为近似开盘, 但实际应该用分时首根price)
        # 这里用pre_px作为open的近似, 但需标注
        open_price = pre_px
        daily_data.append({
            "date": str(dt),
            "pre_px": pre_px,
            "open": open_price,
            "close": close,
            "high": None,  # 需从分时数据提取, 暂缺
            "low": None,
            "mshare": mshare,
        })

    # 从周K数据中提取最近几周的high/low来补充日K
    # 实际上, 我们用周K的high/low来标注日K的high/low近似
    # 最近2周的周K: 20260814 和 20260818
    # 20260814周: high=47.29, low=22.81
    # 20260818周: high=58.8, low=48.5

    # 给最近交易日补充high/low (从周K数据)
    # 20260811-20260814的周K: 20260814, open=22.81, high=47.29, low=22.81, close=47.29
    # 20260818-20260821的周K: 20260818, open=49.2, high=58.8, low=48.5, close=56.5

    # 日K close序列
    daily_closes = [d["close"] for d in daily_data]
    daily_dates = [d["date"] for d in daily_data]

    print(f"日K数据: {len(daily_data)}天")
    for d in daily_data[-10:]:
        print(f"  {d['date']}: open={d['open']}, close={d['close']}")

    # 日线MA (近30日口径)
    daily_ma5 = calc_ma(daily_closes, 5)
    daily_ma10 = calc_ma(daily_closes, 10)
    daily_ma20 = calc_ma(daily_closes, 20)

    print(f"\n日MA5={daily_ma5}, MA10={daily_ma10}, MA20={daily_ma20}")

    # 日线MACD
    d_dif, d_dea, d_macd, d_cross, _ = calc_macd(daily_closes)
    print(f"日MACD: DIF={d_dif}, DEA={d_dea}, cross={d_cross}" if d_dif else "日MACD: 数据不足")

    # 日线RSI
    d_rsi6, d_rsi14 = calc_rsi(daily_closes)
    print(f"日RSI: RSI6={d_rsi6:.2f}, RSI14={d_rsi14:.2f}" if d_rsi6 and d_rsi14 else "日RSI: 数据不足")

    # 日线BOLL
    d_boll_up, d_boll_mid, d_boll_low, d_boll_width = calc_boll(daily_closes)

    # === 融资融券数据 ===
    print("\n=== 融资融券数据 ===")
    margin_records = margin_data["data"]["margintrade"]["data"]["data"]["data"]
    for r in margin_records[:5]:
        print(f"  {r[0]}: 融资余额={r[1]/1e8:.2f}亿, 融资买入={r[3]/1e8:.2f}亿")

    # === 关键价位计算 ===
    print("\n=== 关键价位 ===")
    current_price = 56.5
    # 从周K找关键高低点
    recent_weeks = week_klines[-12:]  # 最近12周
    recent_high = max(k[4] for k in recent_weeks)
    recent_low = min(k[3] for k in recent_weeks)

    # 更长期高低点
    all_week_high = max(k[4] for k in week_klines[-52:])
    all_week_low = min(k[3] for k in week_klines[-52:])

    # 2024年高点
    high_2024 = max(k[4] for k in week_klines[:30])  # 2024年初
    # 2025年低点
    low_2025 = min(k[3] for k in week_klines[30:60])

    print(f"近12周高: {recent_high}, 低: {recent_low}")
    print(f"近52周高: {all_week_high}, 低: {all_week_low}")
    print(f"2024年高点: {high_2024}")
    print(f"2025年低点: {low_2025}")

    # 前期重要价位
    # 从周K数据看, 2024年1月高点约45, 2024年6月低点约21, 2024年10月反弹高点40.82
    # 2025年4月低点18.76, 2025年5月反弹高点30.75
    # 2026年7月低点14.0, 然后暴涨到56.5

    # 黄金分割 (从14.0到56.5)
    low_pivot = 14.0
    high_pivot = 58.8  # 最高
    diff = high_pivot - low_pivot
    fib_0382 = high_pivot - diff * 0.382
    fib_05 = high_pivot - diff * 0.5
    fib_0618 = high_pivot - diff * 0.618

    print(f"黄金分割(14.0-58.8): 0.382={fib_0382:.2f}, 0.5={fib_05:.2f}, 0.618={fib_0618:.2f}")

    # === 输出所有计算结果到JSON ===
    result = {
        "current_price": current_price,
        "week": {
            "count": len(week_klines),
            "last_date": week_dates[-1],
            "last_close": week_closes[-1],
            "ma5": week_ma5, "ma10": week_ma10, "ma20": week_ma20, "ma30": week_ma30,
            "macd_dif": w_dif, "macd_dea": w_dea, "macd_hist": w_macd, "macd_cross": w_cross,
            "kdj_k": w_k, "kdj_d": w_d, "kdj_j": w_j, "kdj_cross": w_kdj_cross,
            "rsi6": w_rsi6, "rsi14": w_rsi14,
            "boll_up": w_boll_up, "boll_mid": w_boll_mid, "boll_low": w_boll_low, "boll_width": w_boll_width,
            "recent_high": recent_high, "recent_low": recent_low,
            "all_high": all_week_high, "all_low": all_week_low,
        },
        "month": {
            "count": len(month_klines),
            "ma5": month_ma5, "ma10": month_ma10, "ma24": month_ma24,
            "macd_dif": m_dif, "macd_dea": m_dea, "macd_cross": m_cross,
            "kdj_k": m_k, "kdj_d": m_d, "kdj_j": m_j,
        },
        "daily": {
            "count": len(daily_data),
            "ma5": daily_ma5, "ma10": daily_ma10, "ma20": daily_ma20,
            "macd_dif": d_dif, "macd_dea": d_dea, "macd_cross": d_cross,
            "rsi6": d_rsi6, "rsi14": d_rsi14,
            "boll_up": d_boll_up, "boll_mid": d_boll_mid, "boll_low": d_boll_low, "boll_width": d_boll_width,
            "dates": daily_dates[-10:],
            "closes": daily_closes[-10:],
        },
        "fibonacci": {
            "pivot_low": low_pivot, "pivot_high": high_pivot,
            "fib_0382": fib_0382, "fib_05": fib_05, "fib_0618": fib_0618,
        },
        "margin": [
            {"date": r[0], "balance": r[1]/1e8, "buy": r[3]/1e8 if len(r) > 3 and r[3] else 0}
            for r in margin_records[:5]
        ],
    }

    output_path = os.path.join(SKILL_DIR, "analysis_data.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n=== 数据已保存到 {output_path} ===")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__":
    main()

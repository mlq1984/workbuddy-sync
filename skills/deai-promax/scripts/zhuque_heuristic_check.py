#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zhuque_heuristic_check.py — 朱雀风格启发式自检脚本（零依赖）

近似复现朱雀（腾讯 DetectAI）的五个检测维度，对中文文本做 AI 疑似度评分，
帮助在交给朱雀前先自查、定向修补。注意：这是「启发式近似」，不是朱雀官方模型，
不能替代真实检测，但能指出最像 AI 的几类信号。

用法：
    python zhuque_heuristic_check.py <输入文件.txt> [--json]
    cat 文本.txt | python zhuque_heuristic_check.py - [--json]

维度（分数 0-100，越高越像 AI）：
    1. 突发性 Burstiness   —— 句长是否过于均匀（方差 < 5 高危）
    2. 困惑度 Perplexity   —— 是否有可预测的重复串 / 高频套路
    3. 词汇分布 Vocab      —— AI 偏好词命中频率
    4. 标点痕迹 Punct      —— 破折号 / 提示语冒号 / 英文引号密度
    5. 逻辑明线 Logic      —— 显性逻辑连词密度 + 段落同构
"""

import sys
import json
import re
from collections import Counter


# ───────────────────────────── 内置词典 ─────────────────────────────
# 蒸馏自 banned-words.md。保持与技能文档一致即可，无需穷举。
AI_PREF_WORDS = [
    "此外", "然而", "因此", "与此同时", "总而言之", "事实上", "值得注意",
    "更关键", "更要命", "换句话说", "首先", "其次", "最后", "在这个过程中",
    "在此基础上", "至关重要", "关键性的", "不可或缺的", "深远影响", "标志着",
    "见证了", "彰显了", "充分体现了", "举足轻重", "里程碑", "深远意义",
    "行业报告显示", "观察者指出", "专家认为", "研究表明", "业内人士认为",
    "未来可期", "前景广阔", "充满希望", "毫无疑问", "综上所述", "本质上",
    "归根结底", "简单来说", "赋能", "闭环", "抓手", "落地", "重塑", "深耕",
    "洞察", "剖析", "解构", "聚焦", "驱动", "构建", "打造", "助力", "践行",
    "不由得", "霎时间", "殊不知", "良久", "恍然大悟", "稳稳", "猛地", "死死",
    "狠狠", "如同", "仿佛", "标志着", "不仅", "而且",
]

PROMPT_COLON_HINTS = [
    "核心是", "关键在于", "原因在于", "原因如下", "结论是", "本质上",
    "换句话说", "一句话总结", "答案是", "问题是",
]

LOGIC_WORDS = [
    "因此", "然而", "此外", "与此同时", "首先", "其次", "最后", "所以",
    "于是", "并且", "而且", "但是", "不过", "由此可见", "总而言之", "总之",
    "换言之", "换句话说",
]

SENT_SPLIT = re.compile(r"[。！？!?；;\n]+")
NON_CN = re.compile(r"[^\u4e00-\u9fff]")


def read_text(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def sentences(text):
    parts = [p.strip() for p in SENT_SPLIT.split(text) if p.strip()]
    return parts


def cn_len(s):
    return len(NON_CN.sub("", s))


def variance(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return sum((x - m) ** 2 for x in xs) / n


def count_substr_repeats(text, n=12):
    """统计长度>=n的重复子串（出现>=2次）。返回命中数。"""
    text = NON_CN.sub("", text)  # 只看汉字，去标点干扰
    if len(text) < n * 2:
        return 0
    counter = Counter()
    for i in range(len(text) - n + 1):
        counter[text[i:i + n]] += 1
    return sum(1 for v in counter.values() if v >= 2)


def detect_issues(text):
    raw = text
    text = text.replace("\r", "")
    sents = sentences(text)
    paras = [p for p in text.split("\n") if p.strip()]

    # 基础量
    total_cn = cn_len(text)
    n_sent = len(sents)
    n_para = len(paras)

    # 1) 突发性：句长方差
    sent_lens = [cn_len(s) for s in sents]
    var = variance(sent_lens)
    max_len = max(sent_lens) if sent_lens else 0
    min_len = min(sent_lens) if sent_lens else 0
    # 方差<5 高危；>=25 接近人类
    burst_score = max(0, min(100, int((25 - var) / 25 * 100)))
    if var >= 25:
        burst_score = 5
    elif var <= 5:
        burst_score = 95

    # 2) 困惑度：重复串
    repeat12 = count_substr_repeats(text, 12)
    repeat8 = count_substr_repeats(text, 8)
    ppl_score = min(100, repeat12 * 25 + max(0, repeat8 - repeat12) * 6)

    # 3) 词汇分布：AI 偏好词
    hits = []
    for w in AI_PREF_WORDS:
        c = raw.count(w)
        if c:
            hits.append((w, c))
    density = (sum(c for _, c in hits) / total_cn * 1000) if total_cn else 0
    vocab_score = min(100, int(density * 10))  # 每千字1个≈10分

    # 4) 标点痕迹
    emdash = raw.count("——")
    emdash_density = emdash / total_cn * 1000 if total_cn else 0
    # 提示语冒号：hint + 冒号
    prompt_colon = 0
    for h in PROMPT_COLON_HINTS:
        idx = 0
        while True:
            i = raw.find(h, idx)
            if i == -1:
                break
            # 其后 0-4 字内出现冒号
            nxt = raw[i + len(h): i + len(h) + 5]
            if "：" in nxt or ":" in nxt:
                prompt_colon += 1
            idx = i + len(h)
    eng_quote = raw.count('"') + raw.count('"') + raw.count('"') + raw.count("'") + raw.count("'")
    punct_score = min(100, int(emdash_density * 25 + prompt_colon * 12 + eng_quote / max(1, total_cn / 1000) * 4))

    # 5) 逻辑明线 + 段落同构
    logic_hits = sum(raw.count(w) for w in LOGIC_WORDS)
    logic_density = logic_hits / total_cn * 1000 if total_cn else 0
    # 段落同构：相邻句逗号数相同且长度接近
    iso = 0
    for p in paras:
        ps = sentences(p)
        if len(ps) < 2:
            continue
        for a, b in zip(ps, ps[1:]):
            ca, cb = a.count("，") + a.count(","), b.count("，") + b.count(",")
            la, lb = cn_len(a), cn_len(b)
            if ca == cb and ca >= 2 and abs(la - lb) <= 4:
                iso += 1
    logic_score = min(100, int(logic_density * 12 + iso * 8))

    # 综合（加权）
    composite = int(
        burst_score * 0.28
        + ppl_score * 0.24
        + vocab_score * 0.22
        + punct_score * 0.13
        + logic_score * 0.13
    )

    return {
        "total_cn": total_cn,
        "n_sent": n_sent,
        "n_para": n_para,
        "sent_var": round(var, 2),
        "sent_max": max_len,
        "sent_min": min_len,
        "repeat12": repeat12,
        "repeat8": repeat8,
        "ai_word_hits": hits,
        "ai_word_density": round(density, 2),
        "emdash": emdash,
        "emdash_density": round(emdash_density, 2),
        "prompt_colon": prompt_colon,
        "eng_quote": eng_quote,
        "logic_hits": logic_hits,
        "logic_density": round(logic_density, 2),
        "para_iso": iso,
        "scores": {
            "burstiness": burst_score,
            "perplexity": ppl_score,
            "vocab": vocab_score,
            "punct": punct_score,
            "logic": logic_score,
        },
        "composite": composite,
    }


def suggest(d):
    sugg = []
    s = d["scores"]
    if s["burstiness"] >= 60:
        sugg.append("句长过于均匀 → 注入极短句(≤5字)与长句交替，拉开段落厚度（第一/二层）")
    if s["perplexity"] >= 40:
        sugg.append("存在可预测重复串 → 打破连续相同表述，制造意外搭配（第三/五层）")
    if s["vocab"] >= 40:
        sugg.append("AI 偏好词偏多 → 铲除偏好词，换具体表达（第三层 + banned-words.md）")
    if s["punct"] >= 40:
        sugg.append("标点痕迹明显 → 删破折号/提示语冒号，英文引号改中文（第四层）")
    if s["logic"] >= 40:
        sugg.append("逻辑明线/段落同构 → 删 ≥60% 逻辑连词，打破相邻句同构（第四层）")
    if not sugg:
        sugg.append("五项维度均较安全，可交朱雀复检。仍建议做一次保真回读。")
    return sugg


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    paths = [a for a in args if a != "--json"]
    if not paths:
        print("用法：python zhuque_heuristic_check.py <文件.txt|-> [--json]")
        sys.exit(1)
    text = read_text(paths[0])
    d = detect_issues(text)
    d["suggestions"] = suggest(d)

    if as_json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return

    bar = "══════════════════════════════════════"
    print(bar)
    print("朱雀风格启发式检测报告（近似，非官方）")
    print(bar)
    print(f"文本长度：{d['total_cn']} 字，{d['n_sent']} 句，{d['n_para']} 段")
    print()
    print("【维度评分】（0-100，越高越像 AI）")
    print(f"  1. 突发性 句长均匀度 : {d['scores']['burstiness']:>3}/100  "
          f"(句长方差={d['sent_var']}，最长{d['sent_max']}/最短{d['sent_min']})")
    print(f"  2. 困惑度 可预测重复 : {d['scores']['perplexity']:>3}/100  "
          f"(≥12字重复串 {d['repeat12']} 处, ≥8字 {d['repeat8']} 处)")
    print(f"  3. 词汇分布 AI偏好词 : {d['scores']['vocab']:>3}/100  "
          f"(命中 {len(d['ai_word_hits'])} 类, 密度 {d['ai_word_density']}/千字)")
    print(f"  4. 标点痕迹         : {d['scores']['punct']:>3}/100  "
          f"(破折号{d['emdash']}/千字{d['emdash_density']}, 提示语冒号{d['prompt_colon']}, 英文引号{d['eng_quote']})")
    print(f"  5. 逻辑明线/同构    : {d['scores']['logic']:>3}/100  "
          f"(逻辑词{d['logic_hits']}/千字{d['logic_density']}, 同构段{d['para_iso']})")
    print("─" * 40)
    print(f"综合 AI 疑似度：{d['composite']}/100")
    if d['ai_word_hits']:
        top = "、".join(f"{w}×{c}" for w, c in d['ai_word_hits'][:12])
        print(f"  AI 偏好词命中：{top}")
    print()
    print("【修补建议】")
    for s in d["suggestions"]:
        print(f"  • {s}")
    print(bar)


if __name__ == "__main__":
    main()

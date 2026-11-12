# -*- coding: utf-8 -*-
"""提示中心 · 确定性守门（校验 + 评分 + 兜底判定）。

纯标准库、纯函数、无 I/O、无网络——供 Agent 与 params 可选调用。
四子步流水线：定语言(detect_language) → 选模式(detect_mode) →
构参数(compose_from_scratch/enrich) → 做校验(validate)。
总入口 optimize()；CLI: python -m core.prompt_opt --check --prompt "<文本>" [--keep "<用户参数>"]

方法论：prompt_center/方法论.md（设计档案已移出技能外，运行时不读）
"""
from __future__ import annotations

import argparse
import json
import re
import sys

ZH_LIMIT = 200   # 中文提示词长度守门（字符）
EN_LIMIT = 1200  # 英文提示词长度守门（字符）

# ---------- 词表 ----------

STYLE_WORDS = ("水彩", "油画", "插画", "素描", "水墨", "赛博朋克", "像素", "动漫",
               "卡通", "3D", "摄影", "写实", "电影感", "胶片", "国风", "浮世绘",
               "极简", "蒸汽波", "厚涂", "工笔", "版画", "波普", "水粉", "扁平风")
LIGHT_WORDS = ("光", "影", "晨", "昏", "夜", "阳光", "灯光", "烛光", "逆光", "侧光",
               "顶光", "霓虹", "月光", "黄昏", "黎明", "阴天", "晴天")
COMP_WORDS = ("景深", "特写", "中景", "远景", "全景", "俯拍", "仰拍", "平视", "构图",
              "视角", "广角", "长焦", "宽幅", "竖幅", "居中", "对称", "留白", "航拍")
DETAIL_WORDS = ("质感", "纹理", "细节", "材质", "毛发", "颗粒", "笔触", "晕染",
                "光泽", "绒毛", "织物", "金属", "木质", "皮肤")
QUALITY_WORDS = ("高清", "高质量", "高品质", "细腻", "精细", "4K", "8K", "超清",
                 "杰作", "电影级", "层次分明", "hd")

# 修饰词（用于形容词堆砌检测）：纯修饰无实体支撑时提示术语替形容词
MODIFIER_WORDS = ("高质量", "高品质", "高清", "超清", "4K", "8K", "杰作", "电影级",
                  "细腻", "精细", "精美", "精致", "漂亮", "好看", "层次分明")

DEAI_WORDS = ("自然光线", "真实质感", "生活气息", "有机形态", "不规则纹理")

# 同义词簇：同组只保留首次出现
SYNONYM_GROUPS = (
    ("高质量", "高品质", "高清画质", "超高清", "高画质", "hd"),
    ("真实质感", "质感真实", "真实感"),
    ("细腻", "精细"),
    ("自然光线", "自然光"),
    ("层次分明", "画面层次分明", "层次丰富"),
)

# 语义矛盾对：同时出现则剔除后者（keep 命中者除外）
CONFLICT_PAIRS = (
    ("夜晚", "烈日"), ("夜晚", "阳光明媚"), ("夜晚", "晴天"), ("夜晚", "正午"),
    ("雪景", "烈日"), ("雨天", "烈日"), ("白天", "星空"),
    ("黑白", "高饱和"), ("黑白", "五彩"),
    ("水墨", "赛博朋克"), ("极简", "华丽繁复"),
    # 注："黑白"vs"高饱和"仅整体风格冲突时剔除；含"边框/局部/部分"等限定词
    # （如"黑白照片+高饱和边框"）不判冲突。
)

# 留白/虚实维度：画面呼吸感（负空间、极简构图等写法）
VOID_WORDS = ("留白", "负空间", "呼吸感", "极简构图", "虚空", "空白背景")

_DIM_CHECKS = (("风格", STYLE_WORDS), ("光照", LIGHT_WORDS), ("构图", COMP_WORDS),
               ("细节材质", DETAIL_WORDS), ("质量", QUALITY_WORDS),
               ("留白/虚实", VOID_WORDS))

_SEG_SPLIT = re.compile(r"[，,;；、]\s*")
_RATIO = re.compile(r"\d+\s*[:：]\s*\d+")
_QUOTED = re.compile(r"[「『\"'“”‘’【】]")
_TEXT_INTENT = ("写字", "文字", "标题", "字样", "标语", "logo", "Logo", "LOGO")
_SIZE_WORDS = ("4K", "4k", "2K", "8K", "高清", "超清", "壁纸", "头像", "全高清")


def _segments(prompt: str) -> list:
    return [s.strip() for s in _SEG_SPLIT.split(prompt) if s.strip()]


def _join(segments: list, lang: str) -> str:
    """en → ", " 连接；其余（zh）→ 中文逗号连接。"""
    if lang == "en":
        return ", ".join(segments)
    return "，".join(segments)


def detect_language(text: str) -> str:
    """① 定语言：中文含 CJK 占比 > 0.2 判 zh，否则 en。"""
    if not text or not text.strip():
        return "zh"
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    total = len(re.sub(r"\s", "", text))
    return "zh" if total and cjk / total > 0.2 else "en"


def _missing_dims(text: str) -> list:
    return [name for name, words in _DIM_CHECKS if not any(w in text for w in words)]


def _anchor_count(text: str) -> int:
    n = 0
    if any(w in text for w in STYLE_WORDS):
        n += 1
    if _RATIO.search(text):
        n += 1
    if _QUOTED.search(text) or any(w in text for w in _TEXT_INTENT):
        n += 1
    if any(w in text for w in _SIZE_WORDS):
        n += 1
    return n


def detect_mode(text: str) -> str:
    """② 选模式兜底判据：C 全参直传 / B 守序增补 / A 自主创作。

    C：骨架主要维度覆盖 ≥4 且描述足够具体；B：有 ≥1 个锚点或缺维 ≤3；其余 A。
    Agent 可依据语义覆盖此判据（此处仅确定性兜底）。
    """
    if not text or not text.strip():
        return "A"
    cov = len(_DIM_CHECKS) - len(_missing_dims(text))
    n = len(re.sub(r"\s", "", text))
    if cov >= 4 and n >= 40:
        return "C"
    if _anchor_count(text) >= 1 or cov >= 2:
        return "B"
    return "A"


def parse_intent(text: str) -> dict:
    """抽取已明确参数（锚点）+ 骨架缺维，供模式判定与 B 模式保留区。"""
    styles = [w for w in STYLE_WORDS if w in text]
    ratios = _RATIO.findall(text)
    return {
        "lang": detect_language(text),
        "styles": styles,
        "ratios": ratios,
        "has_text_intent": _QUOTED.search(text) is not None or any(w in text for w in _TEXT_INTENT),
        "has_size": any(w in text for w in _SIZE_WORDS),
        "missing_dims": _missing_dims(text),
    }


def inject_deai(prompt: str) -> str:
    """写实/摄影类追加降 AI 感词簇（已有则不重复）。

    功能：去塑料感/蜡像感等 AI 质感，让写实图更自然。
    """
    realistic = any(w in prompt for w in ("摄影", "写实", "真实", "胶片", "照片", "实拍"))
    if realistic and not any(w in prompt for w in DEAI_WORDS):
        prompt = prompt + "，自然光线，真实质感，生活气息"
    return prompt


def inject_cn_text(prompt: str, text: str) -> str:
    """图上中文配文约束：文字内容逐字保留 + 清晰渲染强制约束。"""
    if not text:
        return prompt
    if text not in prompt:
        prompt = prompt + "，图上呈现中文文字「" + text + "」"
    if "文字清晰锐利" not in prompt:
        prompt = prompt + "，文字清晰锐利，无重影无重叠，与背景对比鲜明"
    return prompt


def negative_default() -> str:
    """通用中文负向词（**并入 prompt 文本**，spec 无 negative 字段）。

    覆盖人像写实常见退化（蜡像感/塑料感/过度平滑等）。
    落位方式：中文 prompt 下由 optimize() 自动并入 prompt 文本（"避免…"句式）；英文 prompt 由 Agent 酌情并入。
    """
    return ("畸形，多余肢体，多余手指，手指畸形，文字乱码，低质模糊，水印，签名，"
            "裁切不全，蜡像感，塑料感皮肤，文字模糊，过度平滑，高饱和撞色")


def compose_from_scratch(brief: str, style: str = None) -> str:
    """模式 A 骨架兜底（创意发散由 Agent 完成，此处保证结构完整不缺维）。"""
    parts = [brief.strip()] if brief and brief.strip() else []
    parts.append(style if style else "真实摄影风格")
    parts.extend(("环境细节丰富", "柔和自然光", "中景构图",
                  "材质纹理细腻", "画面层次分明", "留白得当", "高质量"))
    return "，".join(parts)


def clip_length(prompt: str, lang: str = None) -> tuple:
    """长度守门：按逗号分段贪心保留（保证主体段在最前），返回 (prompt, clipped)。"""
    lang = lang or detect_language(prompt)
    limit = ZH_LIMIT if lang == "zh" else EN_LIMIT
    if len(prompt) <= limit:
        return prompt, False
    kept, total = [], 0
    sep_len = 1 if lang == "zh" else 2
    for seg in _segments(prompt):
        add = len(seg) + (sep_len if kept else 0)
        if kept and total + add > limit:
            break
        kept.append(seg)
        total += add
    if not kept:
        kept = [prompt[:limit]]
    return _join(kept, lang), True


def validate(prompt: str, keep: str = None) -> tuple:
    """④ 做校验：同义去重 / 矛盾与 keep 冲突剔除 / 维度覆盖 / 长度守门。

    返回 (清洗后 prompt, issues 列表)。B 模式红线：与 keep 冲突的增补一律剔除。
    """
    issues = []
    lang = detect_language(prompt)
    segs = _segments(prompt)

    # 1) 同义/近义与完全重复去重（保留首次）
    seen_exact, seen_group, kept = set(), set(), []
    group_of = {}
    for gi, group in enumerate(SYNONYM_GROUPS):
        for w in group:
            group_of[w] = gi
    for seg in segs:
        key = seg.lower()
        gi = None
        for w, g in group_of.items():
            if w in seg:
                gi = g
                break
        if key in seen_exact or (gi is not None and gi in seen_group):
            issues.append("去重：" + seg)
            continue
        seen_exact.add(key)
        if gi is not None:
            seen_group.add(gi)
        kept.append(seg)

    # 2) 语义矛盾对剔除（keep 命中者优先保留）
    low_keep = (keep or "").lower()
    low_all = " ".join(kept).lower()
    for a, b in CONFLICT_PAIRS:
        # 黑白 vs 高饱和 的局部豁免（黑白照片+高饱和边框 等）
        if (a, b) == ("黑白", "高饱和") and any(
                w in low_all for w in ("边框", "局部", "部分", "边缘", "点缀")):
            continue
        ia = next((i for i, s in enumerate(kept) if a in s), None)
        ib = next((i for i, s in enumerate(kept) if b in s), None)
        if ia is None or ib is None or ia == ib:
            continue
        # 判定哪侧属于用户 keep，保留 keep 侧
        a_in_keep, b_in_keep = a in low_keep, b in low_keep
        if a_in_keep and not b_in_keep:
            drop = ib
        elif b_in_keep and not a_in_keep:
            drop = ia
        else:
            drop = max(ia, ib)
        issues.append("矛盾剔除：" + kept[drop])
        kept.pop(drop)

    # 3) 与用户 keep 的风格冲突剔除（keep 有风格词时，prompt 中其他风格词视为冲突增补）
    if low_keep:
        keep_styles = [w for w in STYLE_WORDS if w in low_keep]
        if keep_styles:
            for i, seg in enumerate(kept):
                seg_styles = [w for w in STYLE_WORDS if w in seg]
                foreign = [w for w in seg_styles if w not in keep_styles]
                # 整段仅由"外来风格词"构成才剔除（避免误伤含用户词的复合段）
                if foreign and all(w in foreign for w in seg_styles) and seg_styles:
                    issues.append("与用户参数冲突剔除：" + seg)
                    kept[i] = None
            kept = [s for s in kept if s]

    clean = _join(kept, lang)

    # 4) 维度覆盖检查（提醒，不改写）
    missing = _missing_dims(clean)
    if missing:
        issues.append("缺维度提醒：" + "、".join(missing))

    # 4.5) 常见错误检查（形容词堆砌 / 一大段没结构）——仅提示，不改写
    modifier_hits = sum(1 for w in MODIFIER_WORDS if w in clean)
    if modifier_hits >= 4:
        issues.append("形容词堆砌(疑似)：修饰词太多，建议换成具体描述")
    # S9：散文长提示词 = 存在超长单段(>50字一逗到底无结构)；结构化多短段不触发
    if _segments(clean) and max(len(s) for s in _segments(clean)) > 50:
        issues.append("一大段没结构(疑似)：存在超过50字的超长单句，建议拆成短句、按部分写")

    # 5) 长度守门
    clean, clipped = clip_length(clean, lang)
    if clipped:
        issues.append("超长已精简")

    return clean, issues


def enrich(prompt: str, keep: str = None) -> tuple:
    """模式 B 守序增补：确定性部分=降 AI 感注入 + 质量词兜底 + 校验。

    用户 keep 参数只被保留不被改写；维度创意补全由 Agent 完成。
    默认补全项在 issues 中显式声明。
    """
    p = inject_deai(prompt)
    iss_extra = []
    if not any(w in p for w in QUALITY_WORDS):
        p = p + "，高质量"
        iss_extra.append("默认补全：质量词「高质量」")
    clean, iss = validate(p, keep=keep)
    return clean, iss + iss_extra


def passthrough(prompt: str) -> tuple:
    """模式 C：零增补逐字直传，仅超长触发精简。"""
    clean, clipped = clip_length(prompt)
    return clean, (["超长已精简"] if clipped else [])


def score(clean: str, lang: str = None, missing: list = None, issues: list = None) -> int:
    """L5 质量评分门（0-100，纯函数，只评估不删改）。

    构成：维度覆盖(60) + 长度合理(20) + 无冲突/矛盾(20) - 常见错误扣分。
    调用方据 core/params.py 的 AIPO_PROMPT_GUARD(阈值) 决定是否触发重优化。
    """
    lang = lang or detect_language(clean)
    missing = missing if missing is not None else _missing_dims(clean)
    issues = issues or []
    total = len(_DIM_CHECKS)
    cov = (total - len(missing)) / total if total else 0
    s = cov * 60
    n = len(clean)
    limit = ZH_LIMIT if lang == "zh" else EN_LIMIT
    if n >= 20:
        s += 10
    if n <= limit:
        s += 10
    if not any(("矛盾" in i or "冲突" in i or "剔除" in i) for i in issues):
        s += 20
    if any("形容词堆砌" in i for i in issues):
        s -= 10
    if any("没结构" in i for i in issues):
        s -= 10
    return max(0, min(100, round(s)))


def optimize(prompt: str, mode: str = None, lang: str = None,
             keep: str = None, cn_text: str = None, style: str = None) -> dict:
    """四子步流水线总入口。返回 dict：mode/lang/prompt/negative/issues。

    - mode/lang 缺省时用确定性判据；Agent 可显式传入覆盖（mode/lang）。
    - negative 仅 A/B 返回；**中文 prompt 下已自动并入 prompt 文本**（"避免…"句式），英文 prompt 由 Agent 酌情并入；spec 无 negative 字段，勿单独传输。
    - cn_text：图上需渲染的中文文字（逐字保留）。
    """
    lang = lang or detect_language(prompt)
    mode = (mode or detect_mode(prompt)).upper()
    issues = []
    negative = ""

    if mode == "C":
        clean, iss = passthrough(prompt)
        issues += iss
    elif mode == "B":
        clean, iss = enrich(prompt, keep=keep)
        issues += iss
        negative = negative_default()
    elif mode == "A":
        clean = compose_from_scratch(prompt, style=style)
        clean = inject_deai(clean)
        clean, iss = validate(clean)
        issues += iss
        issues.append("默认补全：真实摄影风格 + 环境/光照/构图/材质/质量兜底维")
        negative = negative_default()
    else:
        raise ValueError("未知模式: %s" % mode)

    if cn_text:
        clean = inject_cn_text(clean, cn_text)
        clean, iss = validate(clean, keep=keep)
        issues += iss

    # 负向自动并入 prompt 文本（spec 无 negative 字段，"避免…"句式；中文 prompt 生效）
    if lang == "zh" and negative and "避免" not in clean:
        clean = clean + "，避免" + negative
        clean, _ = clip_length(clean, lang)
        issues.append("负向已并入 prompt")

    grade = score(clean, lang=lang, missing=_missing_dims(clean), issues=issues)
    issues = list(dict.fromkeys(issues))  # 去重（如 A 模式补全 + 中文配文二次校验重复提醒）
    return {"mode": mode, "lang": lang, "prompt": clean,
            "negative": negative, "issues": issues, "score": grade}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")   # CLI JSON 跨环境恒为 UTF-8（不随控制台代码页）
    ap = argparse.ArgumentParser(description="提示中心 · 确定性守门")
    ap.add_argument("--check", action="store_true", help="执行四子步流水线并输出 JSON")
    ap.add_argument("--prompt", required=True, help="优化后/原始提示词")
    ap.add_argument("--keep", default=None, help="用户已给参数（B 模式保留区，冲突剔除依据）")
    ap.add_argument("--mode", default=None, choices=["A", "B", "C"], help="显式指定模式")
    ap.add_argument("--cn-text", default=None, help="图上需渲染的中文文字")
    args = ap.parse_args(argv)
    result = optimize(args.prompt, mode=args.mode, keep=args.keep, cn_text=args.cn_text)
    result["ok"] = True
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""通道语言策略（纯函数，无 IO、无网络）。

职责（与 方法论 3.1 对齐，并经联网调研坐实）：
- detect_language(text)        识别输入语种（zh/en）；
- lang_policy(cid)             读通道 CAPS.lang 声明（唯一声明处，en/zh/any）；
- target_lang(...)            计算某通道应使用的最终目标语种；
- needs_conversion(...)       该通道是否需把 prompt 转语种（供 Agent 决策 / 中心告警）。

设计定位：
- 提示词「语种转换」由 Agent（LLM）按本策略执行——核心模块为纯函数、无翻译服务，
  故转换动作发生在 Agent 组装 spec 之前；本模块提供**确定性、可测试**的识别与策略，
  并供 `python -m core.lang` 查询，使 Agent 的语种决策可验证、可审计。
- 中心 translate() 会在声明 lang=en 的通道收到中文且无图上中文文字时记警告，
  提示 Agent 先转英文再提交（Flux 英文更稳，论文 arxiv 2508.14405 佐证）。
"""
import argparse
import json
import re
import sys

# 语种策略唯一声明处 = 各通道自己的 CAPS.lang（通道自治）：
#   "en" -> 该通道英文更稳（Flux 系）；"zh" -> 中文原生/更稳（CogView/日日新）；
#   未声明 -> "any"（中英皆可，保持用户输入语言）。
# 本模块（lang_policy/target_lang/CLI）全部为该声明的**派生视图**，不另设通道清单。


def lang_policy(cid: str) -> str:
    """通道语种策略：读通道 CAPS 声明的 lang（en/any）；未声明 → any。"""
    try:
        from .registry import get_channel
        ch = get_channel(cid) if cid else None
        caps = getattr(ch["module"], "CAPS", None) if ch else None
        return (caps or {}).get("lang", "any")
    except Exception:
        return "any"


def detect_language(text: str) -> str:
    """识别语种：CJK 字符（含扩展区）占比 > 0.2 判 zh，否则 en；空/全空白 → zh。

    仅做识别，不做任何转换。阈值与既有 prompt_opt.detect_language 口径一致。
    """
    if not text or not text.strip():
        return "zh"
    body = re.sub(r"\s+", "", text)
    if not body:
        return "zh"
    cjk = len(re.findall(r"[\u4e00-\u9fff\uf900-\ufaff]", body))
    return "zh" if (cjk / len(body)) > 0.2 else "en"


def target_lang(cid: str, input_lang: str, mode: str = None, has_cn_text: bool = False) -> str:
    """计算某通道应使用的最终目标语种（zh/en）。

    优先级（硬规则最高优先，与 方法论 3.1 两条硬规矩一致）：
      1. has_cn_text（图上要渲染中文文字）→ "zh"（保持中文，由你智能提炼文字）
      2. mode == "C"（原样模式）→ input_lang（连语言都不动）
      3. 否则按通道策略：cloudflare/free→en；zhipu/shangtang→zh；
         aurora/agnes/auto/未知→"any"（即保持 input_lang）
    """
    if has_cn_text:
        return "zh"
    if (mode or "").upper() == "C":
        return input_lang
    policy = lang_policy(cid)
    return input_lang if policy == "any" else policy


def needs_conversion(cid: str, prompt: str, mode: str = None, has_cn_text: bool = False) -> bool:
    """该通道是否需把 prompt 从识别语种转到 target_lang。"""
    detected = detect_language(prompt)
    return detected != target_lang(cid, detected, mode=mode, has_cn_text=has_cn_text)


def main(argv=None):
    ap = argparse.ArgumentParser(description="通道语言策略查询（确定性、可测试）")
    ap.add_argument("--cid", required=True,
                    help="通道 id（语种策略以该通道 CAPS.lang 声明为准，实时读取）")
    ap.add_argument("--prompt", required=True, help="提示词（用于识别输入语种）")
    ap.add_argument("--mode", default=None, help="A/B/C 模式（C 模式不触动语言）")
    ap.add_argument("--cn-text", dest="cn_text", action="store_true",
                    help="图上要渲染中文文字（保持中文）")
    args = ap.parse_args(argv)
    detected = detect_language(args.prompt)
    target = target_lang(args.cid, detected, mode=args.mode, has_cn_text=args.cn_text)
    out = {
        "detected": detected,
        "target": target,
        "needs_conversion": detected != target,
        "flux_warning": (lang_policy(args.cid) == "en" and detected == "zh" and not args.cn_text),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

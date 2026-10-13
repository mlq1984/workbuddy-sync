#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文书要素检查。
用法：
  python3 template-check.py < 文书
"""
import sys

def main():
    text = sys.stdin.read()
    out = []
    out.append("【文书要素检查】")
    checks = [
        ("含标题", len(text.strip().splitlines()) >= 1 and len(text.strip()) > 5),
        ("含主体/对象", any(w in text for w in ["致", "甲方", "乙方", "委托人", "单位", "兹"])),
        ("有事实/事项描述", len(text.strip()) > 30),
        ("含日期", "日期" in text or "年" in text or "月" in text),
        ("含量化/具体信息", sum(c.isdigit() for c in text) >= 2),
        ("疑似缺落款", ("日期" not in text or "单位" not in text)),
    ]
    for label, ok in checks:
        out.append("- [%s] %s" % ("x" if ok else " ", label))
    out.append("-" * 34)
    out.append("合规：不伪造不代签；重大合同咨询律师。")
    return "\n".join(out)

if __name__ == "__main__":
    print(main())

# -*- coding: utf-8 -*-
"""「员工沟通模板」输出质量校验模块（可独立运行）。

用途：对 Skill 产出做「结构 / 字段 / 引用」三项自检，
      避免「栏目漏填」「字段缺失」「引用失效」等问题流入下一环节。

用法：
    from scripts import check_output, check_package, format_report
    report = check_output(open("output.md", encoding="utf-8").read())

命令行：
    python scripts/quality_check.py <交付物.md>     # 校验一份交付物
    python scripts/quality_check.py --package      # 校验本技能包自身（默认）
"""

import io
import os
import re

SKILL_SLUG = 'employee-communication-template'
SKILL_NAME = '员工沟通模板'
MODULE_VERSION = "1.0.0"

# —— 校验口径：全部抽自本包 SKILL.md，SKILL.md 变更后须同步更新 ——
# 「六、输出结构」声明的必备栏目（子串命中即算存在）
REQUIRED_SECTIONS = ['沟通场景识别', '沟通模板', '注意事项', '后续跟进']

# 「六、输出结构」括注字段 + 通用必备要素
REQUIRED_ELEMENTS = ['主题', '受众', '敏感度', '对象', '渠道', '时机', '正文', '禁忌', '信息分级', '法律合规']

# 占位 / 模板残留（命中即判不通过）
PLACEHOLDERS = ['XXX', 'xxx', '待补', '待填', '待补充', 'TBD', 'TODO', '示例文本', '（略）', '此处略', '[待']

# 包级自检：SKILL.md 应齐备的章节与应存在的 references 文件
PACKAGE_SECTIONS = ['一、技能说明', '二、触发场景', '三、核心理论框架（四层对齐）', '四、核心方法（本技能专属）', '五、输入要求', '六、输出结构', '七、写作风格指南', '八、示例（⚠️ 示范样例）', '九、知识库调用', '十、质量检查清单', '十一、上下游Skill', '十二、理论参考']
PACKAGE_REFERENCES = ['references/examples.md', 'references/theory.md']

_SEC = re.compile(r"^##(?!#)\s*(.+?)\s*$", re.M)
_NUM = re.compile(r"\d")


def _norm(text):
    """统一行尾并压缩连续空行，避免 CRLF 与空行干扰判定。"""
    if not isinstance(text, str):
        raise TypeError("text 必须是 str")
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", t)


def _split_blocks(text):
    """把 Markdown 按 H2 切成 {标题: 正文}，用于空栏目检测。"""
    out, cur = {}, None
    for ln in _norm(text).split("\n"):
        m = _SEC.match(ln)
        if m:
            cur = m.group(1)
            out[cur] = []
            continue
        if cur is not None:
            out[cur].append(ln)
    return {k: "\n".join(v) for k, v in out.items()}


def check_output(text):
    """校验一份交付物是否满足本技能的结构与要素要求。

    :param text: 交付物 Markdown 全文
    :return: dict(skill, slug, score, passed, checks, missing_sections,
                  missing_elements, empty_sections, placeholders)
    """
    body = _norm(text)
    miss_sec = [s for s in REQUIRED_SECTIONS if s not in body]
    miss_el = [e for e in REQUIRED_ELEMENTS if e not in body]
    blk = _split_blocks(body)
    empty_sec = [k for k, v in blk.items() if not v.strip()]
    hits = [p for p in PLACEHOLDERS if p in body]
    has_digit = bool(_NUM.search(body))

    checks = [
        ("结构完整", not miss_sec),
        ("字段齐全", not miss_el),
        ("无空栏目", not empty_sec),
        ("无占位残留", not hits),
        ("含量化信息", has_digit),
    ]
    ok = sum(1 for _, v in checks if v)
    return {
        "skill": SKILL_NAME,
        "slug": SKILL_SLUG,
        "score": round(ok / len(checks) * 100, 1),
        "passed": ok == len(checks),
        "checks": checks,
        "missing_sections": miss_sec,
        "missing_elements": miss_el,
        "empty_sections": empty_sec,
        "placeholders": hits,
    }


def check_package(root=None):
    """校验本技能包自身：章节齐备、references 引用有效。"""
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    problems = []
    md = os.path.join(root, "SKILL.md")
    if not os.path.isfile(md):
        return {"slug": SKILL_SLUG, "passed": False, "score": 0.0,
                "problems": ["缺少 SKILL.md"], "declared_refs": PACKAGE_REFERENCES}
    text = _norm(io.open(md, encoding="utf-8").read())
    for s in PACKAGE_SECTIONS:
        if ("## " + s) not in text:
            problems.append("SKILL.md 缺少章节：" + s)
    for rel in PACKAGE_REFERENCES:
        if not os.path.isfile(os.path.join(root, rel)):
            problems.append("声明文件缺失：" + rel)
    for rel in sorted(set(re.findall(r"references/[A-Za-z0-9_\-]+\.md", text))):
        if not os.path.isfile(os.path.join(root, rel)):
            problems.append("引用失效：" + rel)
    return {"slug": SKILL_SLUG, "passed": not problems,
            "score": 100.0 if not problems else 0.0,
            "problems": problems, "declared_refs": PACKAGE_REFERENCES}


def format_report(report):
    lines = ["技能：%s（%s）" % (report["skill"], report["slug"]),
             "得分：%s" % report["score"], ""]
    for name, ok in report["checks"]:
        lines.append("  [%s] %s" % ("√" if ok else "×", name))
    lines.append("")
    if report["passed"]:
        lines.append("结果：通过 —— 结构完整、字段齐全、无占位残留。")
        return "\n".join(lines)
    lines.append("结果：不通过")
    for key, label in (("missing_sections", "缺失栏目"),
                       ("missing_elements", "缺失字段"),
                       ("empty_sections", "空栏目"),
                       ("placeholders", "占位残留")):
        if report[key]:
            lines.append("")
            lines.append(label + "：")
            lines += ["  - " + str(x) for x in report[key]]
    return "\n".join(lines)


def format_package_report(report):
    lines = ["技能包：%s" % report["slug"],
             "得分：%s" % report["score"], ""]
    lines.append("声明 references：%s" % ("、".join(report["declared_refs"]) or "（无）"))
    if report["passed"]:
        lines.append("")
        lines.append("结果：通过 —— 章节齐备，references 引用有效。")
        return "\n".join(lines)
    lines.append("")
    lines.append("结果：不通过")
    lines.append("")
    for p in report["problems"]:
        lines.append("  - " + p)
    return "\n".join(lines)

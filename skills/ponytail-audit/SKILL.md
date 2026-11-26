---
name: "ponytail-audit"
version: "5.0.0"
display_name: "Ponytail Audit"
display_name_en: "Repo-wide Quality Audit (Lazy Senior)"
description: "仓库级质量审计：像刚接手这段代码、马上会被电话叫起来修 bug 的资深开发那样扫一遍。正确性、安全、负载、测试、速度、精简六个维度打分，按重要性排序，每条带具体用例和最小修复建议。一次出报告，不动代码。最多列 20 条，其余说明数量。"
description_zh: "仓库级质量审计：像刚接手这段代码、马上会被电话叫起来修 bug 的资深开发那样扫一遍。正确性、安全、负载、测试、速度、精简六个维度打分，按重要性排序，每条带具体用例和最小修复建议。一次出报告，不动代码。最多列 20 条，其余说明数量。"
description_en: "Quality audit of a whole repo: bugs, security holes, scale problems, missing tests, slow paths, what to delete/merge/split. Ranked by importance, each with a concrete case and smallest fix. One-shot report, changes nothing. Max 20 findings."
triggers: "audit；仓库审查；看看整个项目有没有问题；/ponytail-audit；找臃肿代码"
examples_zh:
  - "/ponytail-audit 看看这个项目里有什么需要修的"
  - "audit 一下我的仓库，告诉我先改哪里"
  - "这个 repo 有什么隐患？帮我找找"
examples_en:
  - "/ponytail-audit scan this repo for issues"
  - "what should I fix first?"
  - "find bloat in my codebase"
license: "MIT"
compatibility: 任意语言
metadata:
  author: DietrichGebert
  source: https://github.com/DietrichGebert/ponytail/blob/main/skills/ponytail-audit/SKILL.md
  related_skills: ["ponytail", "ponytail-review", "ponytail-debt"]
---

# Ponytail Audit

像刚接手这段代码、马上就要被半夜电话叫起来的资深开发那样扫整仓。优先级：正确 → 安全 → 扛得住负载 → 有测试 → 够快 → 精简。精简同样重要——每多一行都得再多读一遍、多测一次。这是一份用户主动要的审计报告，所以给出完整内容。

## 1. 先摸清

审用户指出的东西：某个文件夹、某个包、或整个仓库。没点名就审全仓。读 README、部署和构建配置、依赖清单、入口（main / routes / handlers / jobs / CLI commands）和测试。找预期负载：单人跑脚本还是很多人多进程并发？按此量级判断并声明你用的假设。

端到端追踪主流程：数据从哪进、存哪、从哪出。这些路径**通篇读完**：用户输入、钱、认证、数据写入、后台 job、任何跨进程共享的路径。大仓库：**往代价最高的地方深挖**，而不是逐文件平推。把没读的部分在末尾列出。

## 2. 找这些

同 `/ponytail-review` 的六项（bug / risk / scale / missing test / speed / lean），只是范围扩大到全仓。注意：两个地方用不同方式应用同一规则也算 bug。

## 3. 报告前核实

- 每条发现一个具体用例
- 说某段代码未使用前 grep 全树（含测试、fixture、配置、字符串/动态引用）
- `shortcut:` 注释属决策，除非预期负载越过那条线才算问题
- 给出最小修复，优先删
- 不提风格品味，不设"考虑"，不说模糊担忧

## 4. 输出

简单直白。开头两到三句 `What this repo does:` + 你假设的负载规模。

三份清单，最重要排前，空组跳过：
- **Must fix**：bug、安全、数据丢失、预期负载下崩掉
- **Should fix**：有风险但无测试、真慢、重复、职责混乱、不该存在的代码
- **Nice to have**：小加速、更短写法

全局连续编号（最多 20 条；若漏了小的，注明总共少了多少）。每条同样四段：现象 + 位置 + 是什么 + 怎么修 + 不改的后果。结尾：
- `Verdict:` 一条：healthy 或先改什么
- 有精简发现时：`Lean: -<N> lines, -<M> dependencies possible.`
- `Not checked:` 读过但没机会跑 / 没读的部分

啥都没发现：`Healthy. Nothing to fix.` + 一句话说明了扫了什么。

只报告、不动代码。

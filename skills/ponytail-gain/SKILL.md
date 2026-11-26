---
name: "ponytail-gain"
version: "5.0.0"
display_name: "Ponytail Gain"
display_name_en: "Benchmark Impact Scoreboard"
description: "展示 Ponytail 公开基准测试的 measured savings：代码量↓53%、时间↓41%、成本↓26%、token↓45%，同时在 risky 逻辑处附带测试比例从 68%→98%。纯展示卡片，不做模式切换、不写文件、不变动任何状态。不可据此推算当前仓库的具体节省量。"
description_zh: "展示 Ponytail 公开基准测试的 measured savings：代码量↓53%、时间↓41%、成本↓26%、token↓45%，同时在 risky 逻辑处附带测试比例从 68%→98%。纯展示卡片，不做模式切换、不写文件、不变动任何状态。不可据此推算当前仓库的具体节省量。"
description_en: "Show Ponytail's published benchmark gains — fewer lines, tokens, cost, time; more tested risky logic. Display only: no mode change, no file writes, no persistence. Never fabricate per-repo savings numbers."
triggers: "gain；收益；看 ponytail 省了多少；/ponytail-gain"
examples_zh:
  - "/ponytail-gain 看看效果数据"
  - "ponytail 到底能省多少？"
examples_en:
  - "/ponytail-gain show me the numbers"
  - "what does ponytail save?"
license: "MIT"
compatibility: 任意代理工具
metadata:
  author: DietrichGebert
  source: https://github.com/DietrichGebert/ponytail/blob/main/skills/ponytail-gain/SKILL.md
  related_skills: ["ponytail", "ponytail-review", "ponytail-debt"]
---

# Ponytail Gain — 已测量收益看板

调用时就显示这张计分板。一次性展示：不切模式、不写 flag 文件、不持久化任何状态。

以下数字来自公开发布的 agentic 基准测试（Ponytail 5 vs 同款 agent 不带 skill）：39 个任务 × 5 次运行，Opus 5.5 无头 Claude Code，默认 effort。其中 18 个任务藏了正确性与安全性检查点。每项取各任务中位数的几何平均。这是**测量值，不是从你当前仓库推算出来的**。

## 计分板

纯 ASCII 条形图，条长代表 ponytail 相对无 skill 基线的占比：

```
  ponytail gain           benchmark · 39 tasks × 5 runs · Opus 5.5

  no-skill        ████████████████████  100%
  Lines of code   █████████████·······   47%   ▼ 53%
  Output tokens   ██████████████······   55%   ▼ 45%
  Cost            ████████████████····   74%   ▼ 26%
  Time            ██████████████······   59%   ▼ 41%
  Hidden checks passed   97%  (no-skill 96%)
  Tests where logic needs one   98%  (no-skill 68%)

  This repo shortcuts:  /ponytail-debt
  What's still cuttable: /ponytail-audit
```

## 诚实边界

这些都是基准**均值**，不是你当前仓库的数字。**永远不要打印"你这个仓库省了 X 行/token"**：因为未写出的版本从未存在，没有真实的减法 baseline。当前仓库唯一真实可查的数字是 `/ponytail-debt`（已被标定的账本），这张卡会引导去看那里而不是凭空造数。

## 边界

纯展示，一次响应后结束。不编辑、不改变模式、不写文件。

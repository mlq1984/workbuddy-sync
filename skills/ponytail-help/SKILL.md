---
name: "ponytail-help"
version: "5.0.0"
display_name: "Ponytail Help"
display_name_en: "Ponytail Quick Reference"
description: "Ponytail 速查卡：级别对照、6 个子技能清单与触发方式、band 控制、默认模式配置、更新方式。一次性展示，不改变模式、不写文件。"
description_zh: "Ponytail 速查卡：级别对照、6 个子技能清单与触发方式、band 控制、默认模式配置、更新方式。一次性展示，不改变模式、不写文件。"
description_en: "Quick reference for ponytail levels, skills, commands, band controls, config, and updates. One-shot display; changes nothing."
triggers: "help；帮助；/ponytail-help；怎么用 ponytail"
examples_zh:
  - "/ponytail-help 怎么切换级别？"
  - "ponytail 有哪些命令？"
examples_en:
  - "/ponytail-help"
  - "what can ponytail do?"
license: "MIT"
compatibility: 任意代理工具
metadata:
  author: DietrichGebert
  source: https://github.com/DietrichGebert/ponytail/blob/main/skills/ponytail-help/SKILL.md
  related_skills: ["ponytail", "ponytail-review", "ponytail-audit", "ponytail-debt", "ponytail-gain"]
---

# Ponytail Help — 速查卡

调用时展示这张参考卡。一次性：不切模式、不写 flag 文件、不持久化状态。

## 级别

| 级别 | 触发 | 行为变化 |
|------|------|----------|
| **lite** | `/ponytail lite` | 只做被要求的部分；一句话点出更简选项让用户选。 |
| **full** | `/ponytail` | 最小完整改动 + 边界检查 + 回复末尾交代跳过项和风险。**默认**。 |
| **ultra** | `/ponytail ultra` | 在 full 基础上反向质疑需求本身，先 push back 再动手。 |

级别在整个会话内保持，直到用户改或会话结束。

## 子技能

| 技能 | 触发词 | 作用 |
|------|--------|------|
| **ponytail** | `/ponytail` | 懒模式本体：最少新代码、明确交代跳过的和风险的回复。 |
| **ponytail-review** | `/ponytail-review` | Diff / PR 级质量审查：bug、安全、负载、缺测试、速度、精简。每条带具体用例和修法。 |
| **ponytail-audit** | `/ponytail-audit` | 整仓审计：同上维度但针对整个仓库，按重要性排序。 |
| **ponytail-debt** | `/ponytail-debt` | 收集所有 `shortcut:` 注释成账本，找出静默烂掉的无触发标记。 |
| **ponytail-gain** | `/ponytail-gain` | 公开基准收益看板（代码↓53%、时间↓41% 等）。纯展示。 |
| **ponytail-help** | `/ponytail-help` | 就是这张卡。 |

Claude Code 和 OpenCode 用斜杠命令调用；Codex CLI / IDE 扩展用 `$ponytail:<skill-name>` 格式。

## 关闭

说 `stop ponytail`、`normal mode` 或 `/ponytail off` 都行。随时再用 `/ponytail` 重新激活。

## Band（Claude Code 专用）

`/ponytail band` —— 隐藏 prompt 上方的 band；再发一次恢复。也可 `/ponytail band on` / `off` 直接设定。`/ponytail band import` 把你过去的 Claude Code 会话成本/时长/token 导入 board。

## 配置默认级别

默认 = `full`，每次新会话自动激活。要换：

**环境变量**（优先级最高）：
```bash
export PONYTAIL_DEFAULT_MODE=ultra
```

**配置文件**（Windows: `%APPDATA%\ponytail\config.json`）：
```json
{ "defaultMode": "lite" }
```

解析顺序：env > 配置文件 > `full`。设 `"off"` 则禁用启动自启，手动 `/ponytail` 唤出。

## 更新

让 Ponytail 自动更新：在 Claude Code 里打开 `/plugin` → Marketplaces → 选 ponytail → 开 auto-update。之后每次启动都会拉新版（看到提示后跑 `/reload-plugins`）。手动刷新：`/plugin marketplace update ponytail` + `/reload-plugins`。

如果你的 Claude Code 不认识 `/plugin`，说明版本太旧——升级它（`npm install -g @anthropic-ai/claude-code@latest` 或 `brew upgrade claude-code`）然后重启。其他宿主用各自的更新流程。

## 更多

完整文档 + 示例：https://github.com/DietrichGebert/ponytail

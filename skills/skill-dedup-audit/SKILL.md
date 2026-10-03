---
name: skill-dedup-audit
description: 技能库去重审计与清理流程。扫描 ~/.workbuddy/skills 全部 SKILL.md，提取 frontmatter 描述，按功能重叠分组对比，生成交互式勾选面板，用户确认后批量备份删除。当用户提到"技能太多"、"skill 重复"、"清理技能"、"整理技能库"、"skill dedup"时触发。
description_zh: "技能库去重审计：扫描→分组对比→勾选面板→备份删除"
agent_created: true
---

# Skill Dedup Audit — 技能库去重审计

## 流程

### 1. 提取全部技能描述
用受管 Python 批量读取 `C:\Users\king\.workbuddy\skills\*/SKILL.md`，解析 YAML frontmatter 的 name/description（注意 `>-`、`|` 多行块要合并后续缩进行；部分技能无 frontmatter，直接取正文开头）。输出 `目录名\tname||desc` 清单到临时文件后用 Read 查看。

### 2. 分组对比
将功能相同/高度重叠的技能归组（示例维度：股票分析、出行、电商、部署、OCR、笔记、学习打卡等）。每组输出 markdown 表格：技能名 | 主要功能 | 核心区别，并给出"荐留/荐删"建议。特别注意：
- 平台专属技能在当前 OS 上是否失效（如 macOS 专属技能在 Windows 无效）
- 与插件市场官方插件重复的用户级副本
- 超集 vs 子集关系（超集保留）

### 3. 交互式勾选面板
用 show_widget（interactive 模块）生成勾选面板：打勾=保留，默认按推荐预勾选，每项带荐留/荐删标签和一句区别说明，底部有全选/恢复推荐/清空 + 提交按钮（submit 用 sendPrompt 把"保留：…\n删除：…"清单发回对话）。
**不要用 markdown `- [ ]` 清单——用户无法点击勾选。**
注意：sendPrompt 文本过长会被截断，超长时按组分批执行，截断点之后的组默认不处理并向用户确认。

### 4. 备份并删除
1. `mkdir C:\Users\king\.workbuddy\skills_backup_<YYYYMMDD>`
2. 逐个 `mv` 技能目录到备份；`mv` 报 Permission denied 时改 `cp -r` + `rm -rf`
3. 大目录（含 node_modules 等）耗时长，用 run_in_background
4. 用 `find . -maxdepth 2 -name SKILL.md | wc -l` 核对数量
5. 记录到当日工作日志

### 5. 收尾
告知用户备份位置，等用户明确确认后再 `rm -rf` 备份目录（属不可逆操作，必须二次确认）。

## 坑
- `mv` 到备份可能因文件占用 Permission denied → cp+rm 兜底
- 沙箱可能拦截备份目录删除（safe-delete 路径限制）→ 需用户批准沙箱外执行
- 一次别执行超长删除清单，按用户消息到达的顺序在截断点之前执行

---
name: "ponytail-debt"
version: "5.0.0"
display_name: "Ponytail Debt Ledger"
display_name_en: "Shortcut Debt Collector"
description: "收集所有 `shortcut:`（或旧 `ponytail:`）注释成一个待还债账本。一行一份，分组按文件。给每条标记是否缺少升级触发条件（no-trigger = 静默烂掉的）。不改动代码。"
description_zh: "收集所有 `shortcut:`（或旧 `ponytail:`）注释成一个待还债账本。一行一份，分组按文件。给每条标记是否缺少升级触发条件（no-trigger = 静默烂掉的）。不改动代码。"
description_en: "Collect every deliberate ponytail shortcut (`shortcut:` or older `ponytail:`) into one ledger so a deferral can't quietly become permanent. One row per marker, grouped by file. Tag ones with no upgrade trigger as rot risk. Read-only."
triggers: "债务；debt；ponytail-debt；看哪些捷径该回头处理了；列一下 shortcut"
examples_zh:
  - "/ponytail-debt 看看我们留了多少坑"
  - "盘点一下 shortcut: 注释"
  - "哪些代债还没还？"
examples_en:
  - "/ponytail-debt list all shortcuts"
  - "what debt did we defer?"
  - "find any un-triggered shortcut markers"
license: "MIT"
compatibility: 任意语言
metadata:
  author: DietrichGebert
  source: https://github.com/DietrichGebert/ponytail/blob/main/skills/ponytail-debt/SKILL.md
  related_skills: ["ponytail", "ponytail-review", "ponytail-audit"]
---

# Ponytail Debt — 快捷债账本

每一个故意的 ponytail 捷径都该用一条 `shortcut:` 注释记下它的上限和升级路径（旧代码里可能是 `ponytail:`）。这份技能把它们集合到一个账本里，防止"以后再说"悄悄变成"永远不处理"。

## 扫描

在仓库内 grep 注释标记，跳过 `.git` 和 `.gitignore` 忽略的一切（dependencies、build 产物、caches 等）：

```bash
git grep --no-index --exclude-standard -nE '(#|//|/\*) ?(shortcut|ponytail):'
```

（你的栈用别的注释前缀就加上）如果用户指定了自己的关键词（如 `/ponytail-debt TODO`），grep 那个词替代。

每个命中算账本的一行。注释前缀的作用是过滤掉正文里只是提到这条约定的情况。跳过那些不是"延期"的命中，比如键盘快捷键的说明。

## 输出

每组按文件排列：

```
<file>:<line>, <这里做了哪些简化>. ceiling: <注释里写的上限>. upgrade: <注释里写的触发条件>.
```

约定格式通常是 `shortcut: <ceiling>, <upgrade path>`，直接把 ceiling 和 trigger 从注释里拎出来。要不要每行再加个 owner？可以加 `git blame -L<line>,<line>`。

对那种**没写升级触发条件**的标记打上 `no-trigger` 标签 —— 这些是最容易悄无声息烂掉的。

结尾汇总：`<N> markers, <M> with no trigger.` 啥都没有就说 `No shortcut debt. Clean ledger.`

## 边界

只读不写。想落盘的话问一句再写（写到 `PONYTAIL-DEBT.md` 之类）。一次性命令。

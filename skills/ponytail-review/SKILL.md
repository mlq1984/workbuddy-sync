---
name: "ponytail-review"
version: "5.0.0"
display_name: "Ponytail Review"
display_name_en: "Code Review (Lazy Senior)"
description: "代码审查：像即将被半夜电话叫起来修 bug 的资深开发那样审视改动。从正确性、安全性、负载下表现、测试覆盖、速度、精简六个维度打分。每一条发现必须有具体用例支撑，给出最小修复方案并优先推荐删除。不碰风格偏好、不设 '考虑'、不说虚的。"
description_zh: "代码审查：像即将被半夜电话叫起来修 bug 的资深开发那样审视改动。从正确性、安全性、负载下表现、测试覆盖、速度、精简六个维度打分。每一条发现必须有具体用例支撑，给出最小修复方案并优先推荐删除。不碰风格偏好、不设 '考虑'、不说虚的。"
description_en: "Quality review of a change: is the logic right, safe, holds under real load, tested, fast enough, lean? Every finding needs a concrete case. Smallest fix preferred, deletion beats addition. No style taste, no 'consider', no vague worries."
triggers: "review；代码审查；/ponytail-review；看看这段代码有没有问题"
examples_zh:
  - "/ponytail-review 看下我刚提交的这段 PR"
  - "review 一下这个文件改了什么"
  - "是不是过度设计了？帮我看一眼"
examples_en:
  - "/ponytail-review look at my latest commit"
  - "review these changes"
  - "is this over-engineered?"
license: "MIT"
compatibility: 任意语言
metadata:
  author: DietrichGebert
  source: https://github.com/DietrichGebert/ponytail/blob/main/skills/ponytail-review/SKILL.md
  related_skills: ["ponytail", "ponytail-audit", "ponytail-debt"]
---

# Ponytail Review

像那个会被半夜电话叫起来修 bug 的资深开发那样审这条改动。优先级：正确 → 安全 → 扛得住负载 → 有测试 → 够快 → 精简。精简也很重要：每多一行都得多读一遍、多测一次、多处改掉。

## 1. 先懂

审用户指出的东西：未提交改动、暂存区、某个分支、PR 链接、或指定文件。没点名就看未提交改动或最近一次提交。读 diff，然后读它触碰的代码：每个被改函数的所有调用方、它调用的函数、相关测试、README。

追踪真实数据流：数据从哪进、存在哪、从哪出。一次改动可以坏掉它**没有触碰**的代码——签名、返回值、行为一变，grep 所有调用方。

从 README / 部署配置里找预期负载：单人跑脚本？还是很多人多个进程并发？按这个量级判断。

## 2. 找这些

1. **Bug**：结果错、崩溃、遗漏的边界（空值、零、最后一个、取整、时区），被改动影响的调用方，一个调用方修了别的调用方没修
2. **Risk**：安全漏洞（注入、弱随机、泄露 secrets、输入检查缺失）、数据丢失（吞掉错误、写入顺序错、无事务）
3. **Scale**：一个人够用、多人崩掉：竞态 check-then-write、每个进程做同样的工作、只增长的内存/列表、逐条查询、O(n²)、本该共享却各自维护的状态
4. **Missing test**：有风险的新逻辑（分支、parser、钱、安全、数据写入）里没有一条**会在它崩时挂掉**的测试。一条好测试胜过覆盖率数字
5. **Speed**：大 slowdowns 才算问题。hot loop 里重复工作的小优化算建议；有些软件计较每毫秒
6. **Lean**：不该存在或可以更小的代码
   - delete：死代码、未用选项、投机性功能
   - reuse：库里已有同款 helper（点名路径）
   - stdlib/native：标准库或平台原生能力能做到；少几行不值得新引入依赖
   - yagni：只有一个实现的接口、只有一个产物的工厂、纯透传的包装
   - merge：几乎一样的副本总得一起改
   - split：一个函数干好几件不相干事，拆开按职责分，不按行数分

## 3. 报告前核实

每条发现必须有一个**具体用例**："这个输入或场景会导向这个错误结果"。没用例就没有发现。重读对应行确认：调用方确实存在、值真的可能为空、代码真的没被引用。带有 `shortcut:`（或旧 `ponytail:`）注释并指明了上限和升级路径的捷径算**决策不是问题**，除非预期负载已经越过那条线。给出**最小的可行修复**，优先删代码。绝不多加一层框架/配置。

## 4. 输出

很简单的英文/中文：短句、日常词汇，技术词第一次出现要解释，读者可能没见过这段代码。

开头两到三句 `What this change does:`。

随后三份清单（按重要性排，空组可省）：
- **Must fix**：bug、安全、数据丢失、预期负载下崩掉
- **Should fix**：有风险但无测试的代码、真慢、重复代码、职责混乱的函数、不该存在的代码
- **Nice to have**：小加速、更短写法

全局连续编号，方便用户回 "fix 2 and 5"。每条都四段：现象标题 + 位置 + 是什么 + 怎么修 + 不改的后果。例：

```
2. **订单落在错误的日期** (`billing/close_day.py:L40-52`)
   - **是什么：** 午夜这个 job 关账并按当天结算所有订单。
   - **问题：** 从服务器时钟取"今天"，而服务器跑的是 UTC。柏林 00:30 下的单会被算在前一天。
   - **修法：** 在店铺时区算一次日期即可：`datetime.now(ZoneInfo("Europe/Berlin")).date()`。只这一行。
   - **不改的后果：** 晚下单的日期内对不上账，财务只能手工订。
```

结尾：
- `Verdict: Ship.` 或 `Verdict: fix 1 and 3 first.`
- 有精简发现时：`Lean: -<N> lines possible.`
- 有什么重要但你没机会查的：`Not checked:` 一行概括

啥都没发现：`Looks good. Ship.` + 一句话说明了读了什么。

只报告、不动代码。

# 品牌与平台规范（FBS × 福帮手 × 双通道宿主）

> **版本**：1.3 · **日期**：2026-04-12
> **用途**：约束当前 `WorkBuddy Marketplace` 与 `CodeBuddy Plugin` 双通道中的品牌、平台和宿主能力表述
> **数据来源**：`host-capability-detect.mjs`、`workbuddy/channel-manifest.json`、`codebuddy/channel-manifest.json`

---

## 一、当前分发结构

当前正式发布分为两条通道：

- **WorkBuddy Marketplace 包**：`dist/fbs-bookwriter-v211-workbuddy.zip`
- **CodeBuddy Plugin 包**：`dist/fbs-bookwriter-v210-codebuddy.zip`

共同约束：

- **用户侧品牌名**：福帮手
- **技术标识**：FBS / FBS-BookWriter / `fbs-bookwriter`
- **宿主能力真值**：仅以当前会话实际可见能力和对应通道清单为准；探测文件只提供线索，不证明工具已注册
- **WorkBuddy角色方法**：市场Skill内 `references/fbs-team-lead.md` 与 `references/fbs-writer.md`，由当前Skill会话执行，不是宿主代理目录
- **CodeBuddy插件元数据与代理目录**：仅属于CodeBuddy通道，见下表，不由WorkBuddy Skill推导
- **发布后反馈回流**：`scripts/release-feedback-bridge.mjs` → `.fbs/org-feedback/`

> 从这一版开始，宿主能力描述统一以 **探测脚本快照 + 通道 manifest** 为准，不再允许文档各自维护一套“手工判断”。

---

## 二、品牌区隔规则

### 2.1 名称映射

| 场景 | 使用名称 | 说明 |
|------|---------|------|
| 与用户交互（对话、通知、通报） | **福帮手** | 中文品牌名，用户侧 |
| 代码/技术标识符 | **FBS** / **FBS-BookWriter** / `fbs-bookwriter` | 内部技术代号 |
| 提及宿主平台 | **WorkBuddy** / **CodeBuddy** | 只在明确说明通道差异时出现 |
| 插件包内部元数据 | **`fbs-bookwriter`** | 与 `SKILL.md` frontmatter `name` 对齐 |

### 2.2 禁止示例

```text
❌ 「当前还是单一 WorkBuddy 审核包」
❌ 「一个包同时表示 WorkBuddy / CodeBuddy 的全部能力」
❌ 「minimax-xlsx 是 WorkBuddy Tier1」
❌ 「plugin.json 只是源码内参考，不需要随包交付」
```

### 2.3 正确示例

```text
✅ 「福帮手已就绪，你要写什么？」
✅ 「当前在 WorkBuddy 通道，已检测到本地市场与已启用插件」
✅ 「当前在 CodeBuddy 通道，默认代理是 fbs-team-lead」
✅ 「Excel 能力当前统一走 xlsx 插件，这是唯一方案」
```

---

## 三、通道能力对照表

| 能力 | WorkBuddy Marketplace | CodeBuddy Plugin | 说明 |
|------|-----------------------|------------------|------|
| 通道清单 | `workbuddy/channel-manifest.json` | `codebuddy/channel-manifest.json` | 各自的随包真值 |
| Skill入口/元数据 | `SKILL.md`与WorkBuddy市场包字段 | CodeBuddy插件manifest与入口 | 分别按当前通道规则检查 |
| 角色职责 | references中的角色方法，由当前Skill会话执行 | `.codebuddy/agents/`（仅随已定义的CodeBuddy插件注册） | Skill角色方法不等于宿主成员 |
| 插件元数据 | 不要求`.codebuddy-plugin/plugin.json` | `.codebuddy-plugin/plugin.json` | CodeBuddy专用 |
| Provider注册表 | 不由WorkBuddy Skill默认携带 | `.codebuddy/providers/provider-registry.yml` | CodeBuddy专用 |
| Tier1 本地市场 | ✅ `~/.workbuddy/skills-marketplace/` | ❌ | 仅 WorkBuddy 包使用 |
| Tier2 宿主插件 | ✅ `~/.workbuddy/settings.json` | ✅ 宿主插件与工作区 `.codebuddy/` | 都支持，但来源不同 |
| 默认代理 | 本Skill不声明已注册代理；当前助手按主持方法履职 | 仅在实际CodeBuddy插件元数据注册时有效 | 不跨通道推断 |
| 组织反馈回流 | ✅ | ✅ | 回流到 `.fbs/org-feedback/` |
| XLSX 本地市场技能 | ❌ 无 `minimax-xlsx` | ❌ 无 | Excel 统一只走 `xlsx` 插件 |

---

## 四、运行时平台检测

在入口路由或宿主能力检测时，统一使用 `scripts/host-capability-detect.mjs`：

- **WorkBuddy**：检查 `~/.workbuddy`、`settings.json`、`skills-marketplace/skills/`
- **CodeBuddy**：检查 `%APPDATA%/CodeBuddy` / `CODEBUDDY_HOME` 与当前工作区 `.codebuddy/`
- **Fallback**：都不可用时进入 `script-only` 模式

对外说明时，必须始终带上“当前通道”这一层：

```text
✅ 「当前是 WorkBuddy Skill 市场通道；角色方法由当前会话履行，委派能力以实际工具为准」
✅ 「当前是 CodeBuddy 插件通道；仅在已加载插件并确认其代理清单后使用该通道定义」
❌ 「当前宿主平台自己会判断」
```

---

## 五、发布与回流规范

### 5.1 打包入口

- `npm run pack:workbuddy`
- `npm run pack:codebuddy`
- `npm run pack:release`（一次生成双通道产物）

### 5.2 发布后反馈回流

- 记录反馈：`node scripts/bookwriter.mjs run scripts/release-feedback-bridge.mjs record <bookRoot> ...`
- 汇总反馈：`node scripts/bookwriter.mjs run scripts/release-feedback-bridge.mjs summary <bookRoot>`
- 应用反馈：`node scripts/bookwriter.mjs run scripts/release-feedback-bridge.mjs apply <bookRoot> --feedback-id <id> ...`

反馈记录必须落盘到 `.fbs/org-feedback/`，并同步回 `releases/*-release.json` 的 `organizationFeedback` 摘要。

---

## 六、自检清单

- [ ] `SKILL.md` 是否已改成双通道分轨说明
- [ ] `_plugin_meta.json` 是否声明 `workbuddy-marketplace` 与 `codebuddy-plugin`
- [ ] WorkBuddy Skill包是否只声明入口与角色方法，不假设存在CodeBuddy代理注册
- [ ] 若另行发行CodeBuddy插件，才检查`.codebuddy-plugin/plugin.json`及代理清单
- [ ] `scripts/release-feedback-bridge.mjs` 是否已进入包内并可写入 `.fbs/org-feedback/`
- [ ] 所有 XLSX 描述是否都明确为“仅有 `xlsx` 插件方案”


本发行版角色约定：上述具名角色为包内方法，由当前助手执行；不表示宿主已注册成员。定义见 [主持方法](fbs-team-lead.md) 与 [写作方法](fbs-writer.md)。原生委派以本会话真实工具为准，未提供时串行完成。

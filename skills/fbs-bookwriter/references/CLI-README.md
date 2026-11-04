# BookWriter CLI 2026.10.311

本候选基于正式 3.0.1 安装树，保留 `fbs-bookwriter` 身份。当前发行版本为2026.10.311；原3.0.1和cli-r1保留为历史基线。原安装目录及旧发行件未改；旧 WorkBuddy/CodeBuddy 通道元数据和市场打包脚本仍是历史材料，不用于构建本候选。

## 安装和执行

需要 Node.js 22+、npm；本轮在 Windows、Node.js 24.16.0、npm 11.13.0 验证。解压到独立目录，在技能根执行：

```text
npm ci --ignore-scripts --no-audit --no-fund
node scripts/bookwriter.mjs run scripts/standard-execution-chain.mjs --skill-root . --book-root <本书目录> --chapter-id Ch01 --no-auto-preview
```

锁文件固定 Markdown-it 14.2.0、脚注插件4.0.0及其传递依赖；同时锁定主入口所需glob、iconv-lite。安装不会下载浏览器，也不执行包安装脚本；CLI运行使用本地规则，未配置远程场景表或账户。依赖缺失时先停止，提示执行安装命令。[npm ci 的锁文件行为](https://docs.npmjs.com/cli/v11/commands/npm-ci/)可供核对。

默认仍执行 S3 启动、章节检索和文档链接门禁，然后核验 S4 审校回执，生成 S5 Markdown/HTML及 S6 本地转化材料。`--runtime-only` 仅用于已有章节的恢复；`--gates-only` 只检查门禁。子流程默认上限120秒，可用 `--subprocess-timeout-ms` 设置100至300000毫秒。

## 审校回执

旧模块的模拟分数已移除。先由用户选定的编辑/审校流程完成内容、合规和业务检查，再在本书 `.fbs/reviews/Ch01.json` 保存结果；也可通过 `--review-receipt` 指定本书内的其他路径。结构见 `CLI-REVIEW-EXAMPLE.json`。

回执必须明确批准、完成三项检查、匹配章节ID，并记录实际章节文件的相对路径与 SHA256。缺项、拒绝、越出本书目录、内容变更均停止。CLI只核验这份调用方提供的记录与文件字节，不替代审校，也不认证审校者身份。不要根据CLI返回值宣称已完成专业合规意见。

S5的Markdown和HTML使用同一份已审字节快照，HTML转义原始标签并保留脚注；S6使用已交付Markdown并再次核对哈希。输出位于本书目录的 `deliverables/`、`releases/` 和 `.fbs/`，发布映射只是本地材料，不会自动对外发布。

## 验证与边界

已验证默认门禁及完整合成交付、恢复入口、缺依赖、缺回执、过期/错误回执、源文件越界、检索失败、超时和非零退出等拒绝路径。试验阻止网络和监听器并记录尝试，未发现尝试；全部材料为显式合成数据。自动预览和实际 WorkBuddy 新会话未在本轮验证。

测试设置 `FBS_DISABLE_REWARD_EVENTS=1` 并关闭自动预览。原有本地场景模块可能在技能目录创建默认运行配置/账本；这些状态不随候选包分发。备份与打包使用外部白名单构建器，不复制 `node_modules`、账本、安装标记或测试书稿。

本修复范围为上述可选CLI；不宣称旧通道打包脚本、全部历史开发脚本或所有其他技能能力已验收。恢复的历史文档与示例只用于修复已有链接，不将其旧验收陈述当成本次证据。

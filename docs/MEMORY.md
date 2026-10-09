# User Memory

## 用户偏好
- **设计输出格式**：设计Logo、海报、图片等内容时，直接输出 JPG/PNG 图片文件，不要用 SVG/HTML 预览页面
- **生图/海报默认流程（2026-10-07 指定）**：以后要生成一张图或海报，默认走 Edge + duck.ai 流程（技能：`poster-gen-duckai`，依赖 `edge-cdp-control`），成品保存 JPG 并 present_files 展示
- **生图后关浏览器（2026-10-08 指定）**：图片生成流程结束后必须关闭为生图打开的浏览器/标签页（只关 CDP 自动化实例 `edge-cdp-profile` 相关的，不动用户日常 Edge 标签）
- **海报主标题字体（2026-10-08 指定）**：优先 AI 烫金毛笔书法方案（ImageGen 深红底 + 色键抠图，即国庆海报同款），Pillow 本地字体效果不满意

## 基础设施（用户确认，2026-08-11）
- **Lucky 网关** 与 **NAS** 分别存在局域网（IP 经多次纠正，以用户最新所述为准：项目 192.168.50.4、NAS 192.168.50.10）
- **股票分析同步状态**：桌面端 = `个股分析/report.html`（Electron 应用 个股分析报告.exe），手机端 = mobile-stock PWA（CloudStudio 部署）。两端通过 **GitHub Gist**（Gist ID `412c848a9162fae9e8e196dff42669a8`，文件 key `favs.json`）自动同步自选。桌面端用 `FAV_KEY='stockFavorites'`，手机端用 `FAV_KEY='favStock'`，数据格式 `{code,name,market}` 一致。
- **已弃用**：`股票分析/桌面版/stockintegrated.html`（旧桌面版），以 个股分析 为准

## 企业微信推送通道（2026-10-03 打通）
- 已安装并授权 `@wecom/cli`（`wecom-cli`），可"生成图片/文本 → 发到企业微信"。个人微信无官方接口，用户选择走企业微信。
- 机器人：孟孟的机器人；授权真人 userid：`woeEe4SAAADwo-n-KeKBM2apNO2_qxyg`（可直接作为单聊 chat_id）
- 发文本：`wecom-cli message send --chat-id <id> --msg-type text --text '{"content":"..."}'`
- 发图片：先 `wecom-cli media upload --file-path <file> --type image` 拿 media_id，再 `wecom-cli message aibot send --chat-id <id> --msg-type image --image '{"media_id":"..."}'`
- CLI 需 `export PATH="/c/Users/king/.workbuddy/binaries/node/versions/22.22.2-3:$PATH"`；wecom-unified 技能的旧命令名已过时（以实测为准）
- 未授权时重新扫码：`wecom-cli auth init`（后台运行读取二维码链接给用户）
# sync smoke test 13:25:02

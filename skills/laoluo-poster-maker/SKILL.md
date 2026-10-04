---
name: laoluo-poster-maker
description: 当用户需要设计 9:16 手机长图海报、营销海报、朋友圈传播图或把内容排成长图时，使用 HTML+CSS 设计并用 Playwright 截图成高清 PNG。风格偏向腾讯云/Apple 官网风（蓝白渐变、毛玻璃卡片、留白、科技感）。
agent_created: true
version: 1.0.0
display_name: "LaoLuo Poster Maker"
display_name_en: "LaoLuo Poster Maker"
description_zh: "用 HTML+CSS 设计 9:16 手机长图、营销海报、朋友圈传播图，再用浏览器渲染成高清 PNG。"
description_en: "Design 9:16 mobile posters, marketing visuals and social share images with HTML+CSS, then render them into high-resolution PNG via a headless browser."
---

# 海报设计转 PNG（HTML + Playwright 截图）

## 概述

将海报设计为 9:16 竖屏 HTML 长图，再使用 Playwright 全页截图生成高清 PNG。这种方法比 AI 生图更可控：文字零乱码、卡片整齐、颜色精准，适合包含结构化信息的企业营销海报。

## 何时触发

- 用户要求“做一张海报”且内容含多屏/卡片/对比表/CTA
- 用户提到“朋友圈海报”“9:16 长图”“手机长图”“公众号海报”
- 用户要“科技风”“蓝白渐变”“毛玻璃”“Apple/腾讯云 风格”
- 需要先出稿、再小调文案/配色的场景

## 工作流

1. **确认需求**：询问用途（朋友圈传播 vs 客户咨询/转化）、主题文案、尺寸基调（9:16）、是否有 Logo/二维码素材。若用户未提供 Logo/二维码，使用占位符并在最终交付时说明替换位置。
2. **设计 HTML**：
   - 固定宽度 1080px，高度由内容自然撑开；页面整体 9:16 竖屏基调，必要时可更长。
   - 风格：蓝白渐变背景 + 毛玻璃卡片（rgba 背景 + backdrop-filter: blur + 细边框）+ 大面积留白 + 企业级科技感。
   - 优先使用 SVG 线性图标而非 emoji，避免卡通感。
   - 如需 3D 示意图或装饰，用纯 CSS（perspective、rotateX/Y、radial-gradient 光斑）实现，不依赖外部素材。
3. **截图**：使用 `scripts/poster_shot.py` 或环境里的 Python 运行：
   ```bash
   python3 \
     ~/.workbuddy/skills/poster-html-to-png/scripts/poster_shot.py \
     <input.html> <output.png>
   ```
   - 默认 device_scale_factor=2，输出 2160px 宽高清图，适合展示和打印。
   - 若需要小文件，可改为 1。
4. **检查效果**：打开生成的 PNG，检查文字是否清晰、卡片是否对齐、CTA 是否醒目。
5. **交付**：交付 PNG 和 HTML 源文件，方便用户改字/换色/替换 Logo/二维码后重截图。

## 设计规范

- **字体**：`"PingFang SC","Microsoft YaHei",-apple-system,BlinkMacSystemFont,sans-serif`
- **主色**：腾讯蓝 `#0052D9`，浅亮 `#2B6FF2`，深蓝黑 `#0B1F3A`
- **背景**：Hero 用深色渐变（`#04163C → #0052D9`）做视觉冲击；正文用浅蓝白渐变（`#f3f7ff → #ffffff`）+ 大面积留白。
- **卡片**：半透明白背景（rgba(255,255,255,0.66)）、backdrop-filter blur、1px 浅色边框、柔和阴影（`0 18px 50px rgba(3,24,63,0.10)`）、圆角 22-24px。
- **CTA**：底部深蓝渐变，白色大字，二维码/Logo 居中，突出行动指令。
- **占位元素**：
  - Logo：虚线边框圆角框 + 文字提示“LOGO 占位”
  - 二维码：内联 SVG 绘制类似 QR 的占位图案，提示用户替换为真实二维码

## 资源

- `scripts/poster_shot.py`：Playwright 全页截图脚本，输出 2x 高清 PNG。
- `assets/poster-template.html`：基础海报 HTML 模板，可直接复制后修改。

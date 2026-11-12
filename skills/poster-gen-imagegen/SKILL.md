---
name: poster-gen-imagegen
description: "文生图/海报生成（内置 ImageGen 线路，2026-11-11 16:15 起降为备选）。当前默认路线见下方路由提示：image-generation 技能的 zhipu 通道。带中文标题的海报走 AI 烫金书法+程序压字混合流程。触发词：生成图片、海报、手机海报、封面图、宣传图、poster、生图。"
---

# ImageGen 生图/海报流程（2026-11-11 16:15 起降为备选）

> ⚠️ **路由提示（最新）**：孟姐 2026-11-11 16:15 明确「暂时还是使用 zhipu」。以后生成图/海报，**默认走 `image-generation`（Ai公益生图Pro）技能的 `zhipu` 通道**，不要默认调用内置 ImageGen；只有用户明确点名 ImageGen、或需要本技能的烫金书法压字链路时才执行本流程。
> 默认动线：`image-generation` → ping 中心 8765 → 中文短提示词 → `POST /api/execute`（9:16）→ 本地排版补中文标题 → JPG。详见用户级 MEMORY.md。

历史：2026-11-11 上午曾拍板默认改内置 ImageGen，取代 Edge→duck.ai（后者降为备选，见 `poster-gen-duckai`）；同日下午经四通道比稿后改定 zhipu。

## 交付要求（固定）

- 成品保存为 **JPG**（孟姐偏好，不要 PNG/SVG/HTML 预览页交付）
- 保存到当前工作区根目录，文件名 = 主题，如 `圣诞手机海报.jpg`
- 完成后必须 `present_files` 展示
- 回复中简述：提示词要点、尺寸、用了几次生图

## 调用方式

1. `ToolSearch` 加载 `ImageGen` 的 schema（tool_names: ["ImageGen"]）
2. `DeferExecuteTool` 调用，参数以实际 schema 为准（已验证字段：prompt / size / quality / output_dir / image1 等）
3. **计费提示**：ImageGen 每张约消耗 5-10 credit，批量生图前先告知孟姐

## Prompt 规范（实测有效）

- **必须英文提示词**（含中文的 prompt 易 500）
- 结尾加 `no text, no watermark`
- 比例写明：手机海报 `vertical 9:16` → size 用 `1024x1536`；方图 `1024x1024`；横版 `1536x1024`
- 需要后期压字时写 `empty breathing room at top (or bottom) for title`
- 风格词库参考 `ai-poster-hybrid` 技能（国潮/3D 潮玩/极简高级等）

## 带中文标题的海报 → 混合流程（仍是孟姐偏好）

AI 直出中文字易笔画错误，主标题不要让生图模型直出在画面里：

1. **底图**：ImageGen 出无文字艺术底图（prompt 加 `no text, no watermark` + 题字空间）
2. **主标题**：ImageGen 出烫金毛笔书法（prompt 模板见 `~/.workbuddy/skills/ai-poster-hybrid/scripts/extract_gold_title.py` 文档头；关键点：`solid dark crimson red background (#8B0D0D)` + `molten gold metallic brush calligraphy`，纯色深红底才能色键抠图）
3. **抠图**：`extract_gold_title.py 原图.png 透明.png`（size 1024x1024 出 4 字横排效果佳）
4. **人工验字（必做）**：用 ViewImage 自查字形，再展示给孟姐确认——AI 中文字形可能错；错字就重 roll 标题图（底图不用动）
5. **合成**：写 HTML 压字模板（参考 `~/.workbuddy/skills/ai-poster-hybrid/assets/overlay-template.html`，标题用 `<img class="title-img" src="抠好的透明.png">`），然后：
   ```bash
   "C:\Users\king\.workbuddy\binaries\python\envs\default\Scripts\python.exe" \
     ~/.workbuddy/skills/ai-poster-hybrid/scripts/compose_poster.py \
     --html 模板.html --bg 底图.png -o 成品.png --width 1080 --height 1920
   ```
   - 坑：渲染器不支持 `file:///` 与相对路径，必须用 compose_poster.py（自动把页面内所有本地 img 转 base64 内联）；直接跑 render.mjs 会静默丢图
   - 校验输出 `[verify] 色差 <80` + ✅ 才算成功
   - compose_poster.py 里 NODE 路径当前为 `22.22.2-6`，Node 升级后需同步改脚本第 16 行
6. **转 JPG**：Pillow `convert('RGB')` + `save(..., quality=95)` 存工作区根目录

## 尺寸速查

| 用途 | size 参数 | 成品 |
|---|---|---|
| 手机海报/朋友圈 | 1024x1536 | 1080×1920 |
| 小红书/方图 | 1024x1024 | 1080×1080 |
| 横版 banner | 1536x1024 | 1920×1080 |

## 故障与降级

- ImageGen 报 500：稍等重试；连续失败 → 纯 CSS 渐变底图兜底（模板 `.bg` 换渐变 div）
- 风格不满意：同构图换风格词重 roll 底图即可，HTML/标题不动
- 孟姐不满意：按反馈改 prompt 重出对应图层，重组装即可（分层流程的好处）

## 无需清理

本流程不开浏览器、不起后台进程。若中途用过 duck.ai 备选流程，才需要按 `poster-gen-duckai` 的收尾步骤关浏览器。

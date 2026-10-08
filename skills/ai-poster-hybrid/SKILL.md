---
name: ai-poster-hybrid
description: "AI底图+程序压字的混合海报出图流程。用于生成手机海报、节日海报、营销图、公众号封面等：用 ImageGen 生成无文字艺术底图，再用 poster-maker 本地渲染精确叠加中文标题，彻底规避 AI 生图中文乱码问题。触发词：海报、手机海报、节日海报、封面图、宣传图、poster。"
agent_created: true
---

# AI底图 + 程序压字 混合海报

## 目的

生成带中文标题的高质量海报。直接用 ImageGen 渲染中文经常笔画出错、字形糊；本技能改为两段式：AI 只画无文字画面，文字由本地渲染精确叠加，字体笔画 100% 干净、排版像素可控。

## 使用时机

- 用户要求生成海报/封面/宣传图且包含中文标题时（首选本方案）
- 用户抱怨"AI 图上的中文是错的/糊的"时

## 流程

### 第 1 步：ImageGen 生成无文字艺术底图

- **必须用英文 prompt**（含中文的 prompt 经常 500 报错）
- prompt 结尾必须加：`no text, no watermark`
- 竖版手机海报写 `vertical 9:16 composition`，方图写 `square 1:1`
- 画面留出题字空间：指定 `empty breathing room at top (or bottom) for title`
- 风格示例（按需替换）：
  - 国潮：`Guochao style illustration, golden line-art palace gate, auspicious clouds (xiangyun), fireworks, doves, lanterns, imperial red and gold palette`
  - 3D 潮玩：`Dreamy 3D C4D render, soft rounded miniature landmarks, candy-like fireworks, fluffy clouds, warm rim lighting`
  - 极简高级：`minimalist luxury design, deep red silk gradient, golden light rays, subtle bokeh`
- 若 ImageGen 报 internal server error：稍等重试；连续失败则降级为纯 HTML/CSS 渐变底图（见第 2 步模板的 .bg 替换方案）

### 第 2 步：HTML 压字模板

参考 `assets/overlay-template.html`，要点：

- 舞台尺寸 = 最终图尺寸（手机海报 1080×1920，公众号封面 900×383，方图 1080×1080）
- `<img class="bg" src="__BG_IMAGE__">` 引用底图（compose 脚本会自动转 base64 内联），`object-fit:cover`
- **顶/底渐变遮罩**（`.shade`）保证文字压在任何画面上都可读——深色底图用深红/深黑半透明渐变
- 中文字体：`"Microsoft YaHei"`（Windows）；标题 `font-weight:900` + `letter-spacing` + `text-shadow` 深红投影
- **标题首选方案：AI 烫金毛笔书法字（用户确认偏好，已存库）**：
  1. ImageGen 生成烫金字（prompt 模板见 `scripts/extract_gold_title.py` 文档头；关键：纯色深红底 #8B0D0D + molten gold metallic brush calligraphy，才能色键抠图）
  2. `python scripts/extract_gold_title.py 原图.png 透明.png` 抠出透明素材
  3. **人工验字**（AI 中文字形可能错）后作为 `<img class="title-img">` 内联
  - 已验证存库素材：`assets/titles/title_庆祝国庆_烫金毛笔.png`（1024×735 透明底，国庆主题可直接复用）
- **艺术字体备选（Pillow 方案）**：渲染器不支持 `@font-face file:///` 字体（和底图同一个坑），用 Pillow `ImageFont.truetype` 画文字 → L mask → 逐行金属金渐变（浅金→白金高光带→深金铜）→ `img.paste(grad, mask)` + MaxFilter 铜色描边。技能字体库 `assets/fonts/`：马善政楷书（毛笔楷）、LongCang 龙藏体（行楷）、LiuJianMaoCao 柳建毛草（狂草）、ZhiMangXing 智猛行书（行草），全部免费商用 OFL；`assets/fonts/candidates/` 另有站酷黄油体/小薇/快乐等。金属渐变正确做法是 mask+paste，逐行 d.text 会被覆盖成单色（错误做法）
- 元素结构：`.title`（主标）/ `.sub`（副标）/ `.rule`（金线装饰）/ `.stamp`（角标印章）/ `.year`（底部落款）
- 文字颜色规则：红金喜庆用 `#ffe9a8`/`#ffd76e`；深色科技风用白色+品牌色描边

### 第 3 步：本地渲染（必须用 compose_poster.py，禁止直接调 render.mjs 压底图）

**关键坑**：poster-maker 的渲染器 (takumi) **不支持 `file:///` 本地图片和相对路径**——`<img src="file:///...">`、`<img src="素材.png">` 都会被静默忽略（2026-10-07 实例：烫金标题 PNG 用相对路径被丢，海报没主标题且无任何报错）。必须用本技能的封装脚本，它会把**页面内所有本地 `<img>`（底图+标题 PNG 等素材）统一转 base64 data URI 内联**再渲染，并自动做像素校验。注意：现成校验只查中部底图色差，标题是否渲染成功需另查（如标题区域金色像素占比 >5% 判定通过）。

```bash
"<PY venv路径>/python.exe" ~/.workbuddy/skills/ai-poster-hybrid/scripts/compose_poster.py \
  --html <模板.html> --bg <底图.png> -o <输出.png> --width 1080 --height 1920
```

- PY venv：`C:\Users\king\.workbuddy\binaries\python\envs\default`
- 校验输出 `[verify] 中部区域底图/成品平均色差 <80` 且 `✅` 才算成功；失败会返回退出码 2
- 成品文件通常 >1MB（含底图）

- NODE 路径：`C:\Users\king\.workbuddy\binaries\node\versions\22.22.2-3\node.exe`
- 输出到 `generated-images/` 目录（交付目录），命名含主题
- stderr 出现 CJK 字体 Warning 时检查 font-family 是否命中 msyh
- 渲染是毫秒级的，布局不满意直接改 HTML 重渲

### 第 4 步：交付

- `present_files` 展示最终 PNG（不是底图）
- 用户要求发送时走 wecom-cli（先发 present，再按记忆里的企微命令推送）

## 尺寸速查

| 用途 | 尺寸 |
|---|---|
| 手机海报/朋友圈 | 1080×1920 |
| 公众号封面 | 900×383 |
| 小红书/方图 | 1080×1080 |
| 横版 banner | 1920×1080 |

## 降级方案

- ImageGen 持续故障 → 用纯 CSS 渐变/图案做底（模板里 `.bg` 换成渐变 div），其余流程不变
- 生图风格不满意 → 同一构图换风格词重roll底图，HTML 不动，重渲即可

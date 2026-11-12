---
name: ai-painting-workflow
version: 1.0.0
display_name: "AI绘画生产工作流"
display_name_en: "AI Painting Workflow"
description_zh: "AI绘画生产工作流：在一个入口完成文生图、图生图改图与批量生成，内置提示词优化、教程配图/白板总结图/社媒配图三场景模板、批量清单参数与配置自动同步。当用户提到画一张图、生成图片、改图、修改图片、批量出图、配图、插画、提示词优化等场景时使用。"
description_en: "AI painting production workflow: text-to-image, image-to-image editing, and batch generation in one entry, with prompt optimization, scenario templates (tutorial illustration, whiteboard summary, social media), batch plan parameters, and auto-synced config. Use when the user asks to generate an image, draw, edit or refine an image, batch-generate images, or optimize prompts. Trigger phrases: '画一张', '生成图片', '改图', '批量出图', '配图', 'generate an image', 'edit image', 'batch generate'."
description: "AI绘画生产工作流：在一个入口完成文生图、图生图改图与批量生成，内置提示词优化、教程配图/白板总结图/社媒配图三场景模板、批量清单参数与配置自动同步。当用户提到画一张图、生成图片、改图、修改图片、批量出图、配图、插画、提示词优化等场景时使用。"
agent_created: true
---

# AI绘画生产工作流

## 目的

把「绘图 → 改图 → 批量生成」收敛到一个工作流入口，减少来回切换工具；针对教程配图、白板总结图、社媒配图等高频内容场景提供稳定可复用的提示词模板与批量参数，跨会话自动同步配置。

底层能力：WorkBuddy 内置的 `ImageGen` 工具（文生图 + 图生图）。本技能不替代该工具，而是提供流程纪律、提示词工程与配置管理。

## 成本纪律（每次任务开始前必读）

1. 单张图片消耗约 5–10 积分。**首次生成前必须向用户口头告知预计积分消耗**，批量任务必须给出「条数 × 单张成本」的总预估并获用户确认后才执行。
2. 用户明确说「本轮只做单图/不做批量」时，不得自动扩展为批量任务。
3. 改图默认基于最近一张生成图；如用户意图是全新图片，不携带参考图。

## 工作流决策树

```
用户请求
├─ 新图（文生图）        → 模式 A
├─ 改图（基于已有图）    → 模式 B
└─ 多张 / 清单 / 批量    → 模式 C
```

### 模式 A：文生图

1. 按下方「提示词优化」规则把用户描述扩写为结构化提示词；扩写结果（提示词优化前后对照）在输出阶段展示给用户。
2. 调用 `ImageGen`：`prompt` 必填；常用参数 `size`（1024x1024 / 1024x1536 / 1536x1024）、`quality`（low/medium/high）、`style`、`output_dir`。
3. 输出目录：用户未指定时写入 `<工作区>/ai绘画输出/`，文件名保留工具自动命名。
4. 完成后执行「配置自动同步」。

### 模式 B：图生图（改图）

1. 确定参考图：用户指定的图 > 本会话最近生成图 > 工作区输出目录最近一张。
2. 改图提示词 = 保留什么 + 改什么。先写「保留原图的……」，再写「强化/增加/替换……」，避免模型全图重画。
3. 需要贴近原图时传 `input_fidelity: high`；需要风格大改时省略或用低值。
4. 连续改图时每轮展示优化后的提示词，形成「提示词迭代链」，最终交付时一并列出。

### 模式 C：批量生成

1. 要批量清单：用户给清单文件（CSV/JSON，列模板见 `assets/batch-template.csv`）或口述多条需求。口述时先整理成清单回显。
2. 用 `scripts/batch_plan.py` 校验并展开清单为执行计划 JSON（补默认参数、编号、输出路径）。
3. 向用户展示：计划条数、每条提示词摘要、总积分预估，**确认后执行**。
4. 逐条调用 `ImageGen`，单条失败不中断批次，结束后汇总成功/失败清单。
5. 批量默认用同一 `size`/`quality`（来自配置文件），单条可覆盖。

## 提示词优化规则

用户原话通常太短。按六要素扩写（详细模板与三场景预设见 `references/prompt-playbook.md`）：

```
主体（是什么） + 风格（什么画风） + 光线氛围 + 构图视角 + 细节锚点 + 质量词
```

- 保留用户原意，只做补全不做改写；用户给了明确风格词（如「赛博朋克」）时原样保留并补充该风格的标志性元素。
- 改图场景额外写清「保留项」。
- 中文用户默认用中文提示词；涉及英文风格术语（cyberpunk、isometric 等）可中英并用。

## 配置自动同步

配置文件：`<工作区>/.workbuddy/painting-config.json`（不存在则从 `assets/config.template.json` 复制创建）。

- **读取**：任务开始时若配置存在，`default_size` / `default_quality` / `default_style` / `output_dir` 作为默认参数。
- **写回**：每轮生成完成后，把实际使用的参数与最近 3 条提示词（`recent_prompts`，新条目在前、去重）写回配置。
- 作用：跨会话复用偏好（如教程配图固定 1536x1024），多轮改图不断档。
- 配置只记录参数与提示词，不记录图片二进制。

## 输出与交付

1. 生成结果用 `present_files` 展示图片文件。
2. 交付说明固定包含三块：最终图路径、提示词优化结果（原话 → 最终提示词的对照）、本轮消耗（张数与积分档位说明）。
3. 多轮改图时按「初版 → 迭代版 → 最终版」列全路径。

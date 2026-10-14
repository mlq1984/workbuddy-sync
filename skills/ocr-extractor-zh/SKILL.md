---
name: ocr-extractor-zh
display_name: OCR文字识别
display_name_en: OCR Text Extractor
description: OCR 文字识别技能：从图片、截图、照片、扫描件里识别文字，输出可复制的 Markdown 或单文件交互式 HTML。优先使用系统自带 OCR——macOS 走 Vision.framework（通过 osascript 的 ObjC 桥调用，零安装离线可用），Windows 走 Windows.Media.Ocr（零安装，需已装对应语言包），两者都不可用时降级到 Tesseract；支持中英日韩等多语言、逐行置信度或候选差异度标注、低置信行单独列出供人工核对。HTML 产物为单文件零外链：图片以 data URI 内联，内置「复制全文」「复制本行」「复制纯文本」「只看需核对行」「导出结构化 JSON」，支持键盘 j/k 逐行核对，悬停或选中行会在原图上高亮对应区域。适用于发票、合同、表格、截图、PPT 照片、书页等场景。当用户说『识别这张图里的文字』『图片转文字』『截图里的字提取出来』『OCR 一下』『扫描件识别文字』『把这张发票/合同转成文字』『提取图片中的表格文字』『帮我抄下这张图的内容』时使用。
description_zh: 优先调用系统 OCR（macOS Vision、Windows WinRT）识别图片文字，输出带置信度标注的 Markdown 或单文件可复制的交互式 HTML。
description_en: Extract text from images using system OCR (macOS Vision / Windows WinRT) or Tesseract, outputting Markdown or a self-contained interactive HTML with copy buttons.
version: 1.0.0
author: BILL
---

# OCR 文字识别

从图片里把文字**如实**取出来，产出可复制、可核对的结果。

## 一、引擎：优先用系统自带，不折腾安装

| 平台 | 默认引擎 | 是否需要安装 | 说明 |
|---|---|---|---|
| macOS | **Vision.framework** | **不需要** | 经 `osascript` 的 ObjC 桥调用，离线可用；不需要 pyobjc，也不需要 swiftc |
| Windows | **Windows.Media.Ocr** | **不需要** | 系统自带；需已安装对应语言的 OCR 语言包 |
| 任意平台 | Tesseract | 需要 | 跨平台兜底；中文需额外装 `chi_sim` / `chi_tra` 语言包 |

先跑一次探测，把「这台机器能用什么」搞清楚再动手：

```bash
python3 ${CODEBUDDY_SKILL_DIR}/scripts/ocr_cli.py engines
```

输出会列出每个引擎是否可用、路径、版本、**已安装的语言**，以及默认会选哪个引擎。
Windows 上若显示语言列表为空，说明没装 OCR 语言包——直接告诉用户去「设置 → 时间和语言 → 语言和区域」添加中文/英文语言包（勾选「光学字符识别」可选功能），或改用 `--engine tesseract`。

## 二、命令清单

> 路径统一用 `${CODEBUDDY_SKILL_DIR}` 表示技能安装目录，不要写死绝对路径。
> 桌面安装包附带 `run.sh` / `run.cmd`（自动探测 Python）；平台侧直接用 `python3` 调用即可。

### 1) 识别

```bash
# 自动选引擎，输出 Markdown
python3 ${CODEBUDDY_SKILL_DIR}/scripts/ocr_cli.py run 发票.png

# 输出单文件可交互 HTML（可直接复制、逐行核对）
python3 ${CODEBUDDY_SKILL_DIR}/scripts/ocr_cli.py run 发票.png --to html

# 指定语言（中英混排）
python3 ${CODEBUDDY_SKILL_DIR}/scripts/ocr_cli.py run 合同.png --lang zh-Hans,en-US

# 指定引擎与输出路径
python3 ${CODEBUDDY_SKILL_DIR}/scripts/ocr_cli.py run 截图.png --engine tesseract --to md --out 结果.md

# 版面比较复杂的表格截图，用 tesseract 的单块模式
python3 ${CODEBUDDY_SKILL_DIR}/scripts/ocr_cli.py run 表格.png --engine tesseract --psm 6

# 结构化结果（含逐行坐标、置信度、候选文本）
python3 ${CODEBUDDY_SKILL_DIR}/scripts/ocr_cli.py run 发票.png --to json

# 只在终端看，不写文件
python3 ${CODEBUDDY_SKILL_DIR}/scripts/ocr_cli.py run 发票.png --no-file --print
```

### 2) 引擎探测

```bash
python3 ${CODEBUDDY_SKILL_DIR}/scripts/ocr_cli.py engines --format json
```

## 三、置信度口径：不能糊弄

**这是本技能最容易出错的地方，必须按引擎如实说明：**

| 引擎 | 是否提供概率型置信度 | 本技能怎么标注 |
|---|---|---|
| Tesseract | 是（0~100 的词级置信度） | 逐行给出百分比；低于 75% 的行标为需核对 |
| Windows WinRT | **否** | 明确写"该引擎不提供置信度"，不编造数字 |
| macOS Vision | **否**（`candidate.confidence` 实测恒为 0.5，不随清晰度/语言变化） | 改用**候选差异度**：首选与次选文字不同即标为需核对，并把次选文本一并给出 |

所以交付时：

- **不要说"识别准确率 95%"** 这类没有依据的话。
- 有需核对的行时，必须把行内容与原因（低置信 / 有不同次选）直接展示给用户。
- 图表、印章、手写体、艺术字、低分辨率截图上的小字，**默认应当告知可能不准**。

## 四、产出物规格

### Markdown（默认）

- 一级标题 + 一行摘要（引擎、语言、行数、需核对行数、来源文件名）。
- **逐行保留原始换行**，不做段落合并、不做拼写纠正、不做改写——识别阶段只做转录。
- 需核对的行在行尾用 HTML 注释标注原因，并在文末「需人工核对的行」小节集中列出。

### 交互式 HTML（`--to html`）

硬要求（已内置）：

- **单文件、零外链**：图片以 `data:` URI 内联；CSS/JS 内联；不引用任何 CDN、外部字体或图标，可离线打开、随手转发、直接入知识库。
- **可复制**：「复制全文」「复制纯文本」「复制本行」「复制结构化 JSON」；`file://` 环境下自动回退到 `execCommand` 复制。
- **可核对**：左图右文；点击或悬停某行会在原图上高亮对应区域并显示该行状态；支持 `j`/`k`（或方向键）逐行移动、`c` 复制当前行；「只看需核对行」一键过滤。
- HTML 里的识别文本必须转义，避免识别内容里的 `<script>` 之类被当成标签执行。

### JSON（`--to json`）

含每行的 `text` / `page` / `confidence`（若有）/ `box`（归一化坐标，左上原点，便于在原图上定位）/ `alternatives`（次选文本）。

## 五、执行流程（带确认门）

1. **确认输入**：文件存在、格式受支持（png/jpg/jpeg/tiff/bmp/gif/webp/heic/pdf）。是大图或 PDF 时提醒用户单页识别效果更稳。
2. **探测引擎**：先 `engines`，确认默认引擎与语言可用；Windows 上语言包缺失要提前说。
3. **执行识别**：一条命令一个文件。
4. **交付**：如实报出引擎、语言、行数、需核对行数与产物路径；有需核对行就把它们列出来，不要藏。
5. **人工核对提示**：明确告诉用户"低置信行请以原图为准"，不要暗示结果 100% 可信。

## 六、质量红线（禁止事项）

- **不得改写识别结果**：不润色、不补全、不"顺手修正"错字。识别到什么就输出什么。
- **不得编造置信度**：引擎不给就不给；不许用 0.5 之类的默认值冒充置信度。
- **不得假装识别成功**：没识别到文字时，如实说明可能原因（无文字、分辨率低、语言包不匹配），并建议换引擎或提高清晰度。
- **不得遗漏低置信提示**：只要存在需核对的行，交付时必须显式列出。
- **不得引入外链**：HTML 产物必须自包含；不许为了好看去引 CDN 字体或图标库。
- **不得宣称能处理手写/艺术字**：系统 OCR 对手写与艺术字支持有限，要如实说明。

## 七、参考文件索引

- `references/engines.md` —— 三个引擎的能力边界、语言代码对照、如何选择与降级。
- `references/confidence.md` —— 置信度口径详解：为什么 Vision 不能报百分比、候选差异度怎么读。
- `references/troubleshooting.md` —— 常见问题：Windows 语言包缺失、中文识别差、表格串行、PDF 扫描件、权限与路径问题。
- `scripts/ocr_cli.py` —— 命令行入口（run / engines）。
- `scripts/ocr.py` —— 三个引擎的统一封装与可用性探测。
- `scripts/render.py` —— Markdown / 交互式 HTML / 文本 / JSON 渲染（自包含约束在这里）。

# OCR 引擎能力与选择

## 一、三个引擎对照

| | macOS Vision | Windows WinRT | Tesseract |
|---|---|---|---|
| 安装 | 系统自带（零安装） | 系统自带（零安装） | 需单独安装 |
| 离线 | 是 | 是 | 是 |
| 调用方式 | `osascript` 的 ObjC 桥（JXA） | PowerShell + `Windows.Media.Ocr` | 命令行 |
| 中文支持 | `zh-Hans` / `zh-Hant` | 需安装中文 OCR 语言包 | 需安装 `chi_sim` / `chi_tra` |
| 逐行置信度 | 无（见 `confidence.md`） | 无 | **有**（0~100） |
| 坐标 | 有（归一化） | 有（归一化） | TSV 里有（本实现只用行级） |
| 多语言同时 | 可传多个 | **只支持单语言** | 可用 `+` 组合（如 `eng+chi_sim`） |
| 版面模式 | 不支持 | 不支持 | 支持 `--psm 0~13` |
| 速度 | 快 | 快 | 较慢（尤其多语言） |

## 二、选择顺序

本技能 `--engine auto` 的默认优先级：

```
macOS  → vision → tesseract
Windows→ winrt  → tesseract
其它   → tesseract → vision → winrt
```

每一次自动选择都会先探测可用性；首选引擎失败会自动降级到下一个，
并把**所有**失败原因一起报出来（不会只报最后一个）。

## 三、诊断命令

```bash
python3 ${CODEBUDDY_SKILL_DIR}/scripts/ocr_cli.py engines
```

会报告：每个引擎是否可用、可执行文件路径、版本、**已安装语言列表**、以及默认选择。
`--format json` 可拿到结构化结果。

## 四、语言代码对照

用户在 Windows 上看到的是 BCP-47 标签，在 tesseract 里是另一套代码，本技能会自动映射：

| 用户写法 | tesseract 代码 | 说明 |
|---|---|---|
| `zh-Hans` / `zh-CN` | `chi_sim` | 简体中文（需 `tesseract-ocr-chi-sim`） |
| `zh-Hant` / `zh-TW` | `chi_tra` | 繁体中文（需 `tesseract-ocr-chi-tra`） |
| `en-US` / `en` | `eng` | 英文 |
| `ja-JP` | `jpn` | 日文 |
| `ko-KR` | `kor` | 韩文 |

Windows WinRT 只接受一个语言标签，所以 `--lang zh-Hans,en-US` 在 WinRT 上会**取第一个**
（优先中文）；需要中英混排更好的效果时建议改用 tesseract 的 `chi_sim+eng`。

## 五、Windows 语言包

WinRT OCR 需要已安装对应语言的「光学字符识别」可选功能：

```
设置 → 时间和语言 → 语言和区域 → 添加语言（如中文(简体, 中国)）
  → 语言选项 → 可选语言功能 → 勾选「光学字符识别」
```

企业环境常用 DISM 批量安装：

```powershell
# 查看已有语言能力
Get-WindowsCapability -Online | Where-Object Name -like 'Language.OCR*'

# 安装简体中文 OCR
Add-WindowsCapability -Online -Name "Language.OCR~~~zh-CN~0.0.1.0"
```

未安装时本技能的 `engines` 会显示语言列表为空，`run` 会给出明确提示而不是静默失败。

## 六、实测差异：同一张图不同引擎的行数可能不同

CI 跨平台实测（同一张自制点阵图，2 行文字）：

| 引擎 | 识别行数 | 说明 |
|---|---|---|
| macOS Vision | 2~3 行 | 行分割符合预期 |
| Tesseract (`engs`/`chi_sim+eng`) | 2~3 行 | 行分割符合预期 |
| **Windows 系统 OCR（WinRT）** | **1 行** | 对紧凑排版的点阵字体，`Windows.Media.Ocr` 会把多行并成一行或只取一行 |

**这意味着**：不要对"行数"做跨平台假设。需要逐行结构（如表格、票据行项）时，
建议在 Windows 上显式指定 `--engine tesseract`；只关心整段文字时用系统 OCR 更快。

### 自动降级（v1.0.0 起）

`--engine auto` 的降级不只发生在"引擎报错"，也发生在**引擎成功但一行都没认出来**时：

```
auto → 首选引擎 → 0 行？ → 继续试下一个引擎 → …
        ↓ 全部 0 行
     返回空结果 + 明确说明「以下引擎都执行成功但没识别到文字：…」+ 常见原因
```

- 降级发生时，回执的 `engine.fallbackFrom` 会写明是从哪些引擎降下来的，并给出提示；
- **显式指定 `--engine` 时不做降级**（用户既然指定了，就不该被悄悄换掉）；
- 图片过小是 0 行的首因：**建议字高 >= 60px**（本技能生成的测试图用 84px 字高）。

> 这条规则来自真实 CI 失败：Windows 系统 OCR 对 42px 字高的合成图返回 0 行，
> 而同一张图在 macOS Vision 与 Tesseract 上能出 2~3 行。

> 该结论来自真实 CI 失败（`lineCount >= 2` 在 Windows 上不成立），不是推测。
> 相关断言已拆成两条：引擎链路通（≥1 行，跨平台）+ tesseract 多行基准（≥2 行，有 tesseract 即可）。

## 七、引擎不适用的情况（要如实说明）

| 场景 | 建议 |
|---|---|
| 手写体 | 系统 OCR 对中文手写支持有限，效果可能很差——提前说明，不要承诺 |
| 艺术字 / 花体 / 印章 | 基本不可靠，建议人工录入 |
| 极低分辨率截图 | 先放大图片再识别，或请用户提供原图 |
| 表格线密集 | tesseract `--psm 6`（单块文本）常比默认更好；复杂表格建议人工校对 |
| 竖排中文 | 三个引擎支持都不好，需人工校对 |
| 整页扫描 PDF | 先用文档转换技能把 PDF 拆成图片，再逐页 OCR |

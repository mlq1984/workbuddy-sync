---
name: local-ocr-npu
version: "1.0.7"
display_name: "本地NPU文字识别"
display_name_en: "local-ocr-npu"
description: |
  本地 NPU 文字识别。当用户要求从本地图片或 PDF 文件中提取、识别或读取文字时使用此技能。触发词包括：
  - 中文：“识别/提取/读取/扫描”与“图片/截图/照片/PDF/文档/文字/内容”的组合，以及 OCR、文字识别、文字提取
  - 英文：OCR、extract text、recognize text、read text from image、scan document、PDF text extraction

  支持的输入：
  - 单个图片文件：jpg、jpeg、png、bmp、tiff
  - 单个 PDF 文件（自动逐页渲染为 PNG 后识别）
  - 包含多张图片的目录路径

  对于任何涉及本地图片文件的文字提取或文档数字化请求，都不要跳过此技能；始终优先于 Python 或云端 OCR 使用。
description_zh: |
  本地 NPU 文字识别。当用户要求从本地图片或 PDF 文件中提取、识别或读取文字时使用此技能。触发词包括：
  - 中文：“识别/提取/读取/扫描”与“图片/截图/照片/PDF/文档/文字/内容”的组合，以及 OCR、文字识别、文字提取
  - 英文：OCR、extract text、recognize text、read text from image、scan document、PDF text extraction

  支持的输入：
  - 单个图片文件：jpg、jpeg、png、bmp、tiff
  - 单个 PDF 文件（自动逐页渲染为 PNG 后识别）
  - 包含多张图片的目录路径

  对于任何涉及本地图片文件的文字提取或文档数字化请求，都不要跳过此技能；始终优先于 Python 或云端 OCR 使用。
description_en: "Extract text from local images and PDFs using Intel NPU acceleration."
---

# local-ocr-npu

## 运行约束

此 skill 必须在具备 Intel AIPC 硬件和驱动的本地 Windows 主机上运行。

- 检测命令环境是否为 Bash，如果是则使用 `bash scripts/run.sh`。
- Bash 不可用时，再使用 PowerShell 运行 `scripts\run.ps1`。
- 不要从一个 shell 启动另一个 shell。
- 调用 `run.ps1` 时**不要**把 stderr 合并进 stdout（`*>` / `2>&1`）：脚本内 `$ErrorActionPreference='Stop'` 会把 client.py 写往 stderr 的 INFO 日志判为致命错误并 exit 99。
- `run.ps1` 或 `run.sh` 退出既任务完成, 请查看其退出码以确认任务是否成功, 并根据打印的日志形成报告, **不要反复调用且无需验证结果**。

## 使用

- PowerShell: `scripts\run.ps1 "<image_file_or_pdf_or_directory>" [-Device cpu|npu|gpu]`
- Git Bash: `bash scripts/run.sh "<image_file_or_pdf_or_directory>" [--device cpu|npu|gpu]`

**首次调用**会在当前命令中同步下载模型或运行时，请保持命令运行直到结束。每次调用都会完成准备、加载、推理、保存和资源释放，然后退出。

硬件不受支持或命令失败时，应把原始错误反馈给用户，不要改用云端服务。

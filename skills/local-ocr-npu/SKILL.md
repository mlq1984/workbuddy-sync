---
name: local-ocr-npu
version: "1.0.22"
display_name: "本地NPU文字识别"
display_name_en: "local-ocr-npu"
description: |
  本地 英特尔NPU 文字识别。当用户要求从本地图片或 PDF 文件中提取、识别或读取文字时使用此技能。触发词包括：
  - 中文：“识别/提取/读取/扫描”与“图片/截图/照片/PDF/文档/文字/内容”的组合，以及 OCR、文字识别、文字提取
  - 英文：OCR、extract text、recognize text、read text from image、scan document、PDF text extraction

  支持的输入：
  - 单个图片文件：jpg、jpeg、png、bmp、tiff
  - 单个 PDF 文件（自动逐页渲染为 PNG 后识别）
  - 包含多张图片的目录路径

  对于任何涉及本地图片文件的文字提取或文档数字化请求，都不要跳过此技能；始终优先于 Python 或云端 OCR 使用。
description_zh: |
  本地 英特尔NPU 文字识别。当用户要求从本地图片或 PDF 文件中提取、识别或读取文字时使用此技能。触发词包括：
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

此 skill 必须在具备 Intel AIPC 硬件和驱动的本地 Windows 主机上运行。 `run.ps1` 都会尝试 AIPC 检测，查询明确返回硬件不受支持时退出并报错。

- 使用 **PowerShell** 环境来运行 `scripts\run.ps1`。
- 不要从一个 shell 启动另一个 shell。
- 调用 `run.ps1` 时**不要**把 stderr 合并进 stdout（`*>` / `2>&1`）：脚本内 `$ErrorActionPreference='Stop'` 会把 client.py 写往 stderr 的 INFO 日志判为致命错误并 exit 99。
- 不要仅凭工具显示 `Command completed with exit code 0` 判断 OCR 成功。必须检查脚本退出码并读取本次结果；工具没有回显不代表没有结果，也不是再次运行 OCR 的理由。

## 使用

- PowerShell: `scripts\run.ps1 "<image_file_or_pdf_or_directory>" [-Device cpu|npu|gpu]`

**首次调用**会在当前命令中同步下载模型或运行时，请保持命令运行直到结束。每次调用都会完成准备、加载、推理、保存和资源释放，然后退出。

本次用户实测（非性能保证）：首次下载包含 2 个运行时压缩包及 12 个模型文件，共 14 个资产，约 30 秒（视网络情况而定）；解压后的 bin 目录约 214 MB，两个模型约 90 MB，这些是磁盘占用，不是网络下载量。NPU 首次编译约 27–28 秒，之后单图推理约 0.3–0.9 秒。耗时随网络、硬件和输入变化；下载和首次编译是不同阶段。

硬件不受支持或命令失败时，应把原始错误反馈给用户，不要改用云端服务。

## PowerShell 结果捕获

两个入口均将输入复制到 `%USERPROFILE%\.openvino\temp\ocr_npu_*\input`，以 ASCII 文件名调用 OCR，结束后清理本次临时目录，不修改原文件。清理失败（例如执行宿主注入的 `Remove-Item` 安全删除代理拒绝删除）只记一条 `WARN: temp cleanup failed, left <路径>`（写入日志；Git Bash 同时写 stderr），不影响已输出的结果和退出码。目录输入不递归子目录。NPU 失败后清空结果再尝试一次 CPU；PDF 转换和最终 OCR 的非零退出码会保留，结果枚举或读取失败也按失败处理。批量结果附文件名标题，没有结果文件时输出 `[no text found]`。

两个入口均支持 `OCR_DEVICE`、`PPOCR_EXE`、`DET_MODEL_DIR`、`REC_MODEL_DIR`、`DET_MODEL_NAME`、`REC_MODEL_NAME`、`REC_BATCH_SIZE` 和 `REC_SCORE_THRESH`。本地缓存目录名与下载源模型名独立。模型缺文件时仅补下载缺失项，先写入 `.partial`，校验通过后改名；失败不删除已有完整文件。

日志：两个入口每次调用都写一个 `.openvino\log\ocr-npu-<时间戳>.log`，记录解析出的运行时与模型路径、下载前判定缺失的每个文件、ppocr 退出码，成功时写入 `Done. elapsed=... lines=N`r。平台差异：共享 AIPC 检测在 Git Bash 无法查询处理器时会警告并跳过，不能据此认定硬件受支持；PowerShell 查询失败会报错。检测脚本缺失时两个入口都会警告并跳过。

在调用前确定脚本、输入和结果文件的绝对路径。结果文件必须位于已存在的可写目录、在临时工作目录之外，且使用本次调用独有的新文件名。替换下列三个示例路径后，将整个 `& { ... }` 作为**一条完整工具命令**提交，不要拆成多次调用。

```powershell
& {
  $ErrorActionPreference = 'Stop'
  $runScript = 'C:\absolute\scripts\run.ps1'
  $inputPath = 'C:\absolute\input.png'
  $resultPath = 'C:\absolute\ocr-result-unique.txt'
  try {
    if (Test-Path -LiteralPath $resultPath) { throw 'Result path already exists; choose a new filename.' }
    $LASTEXITCODE = 0
    & $runScript $inputPath | Out-String | Set-Content -LiteralPath $resultPath -Encoding UTF8 -ErrorAction Stop
    $pipelineSucceeded = $?
    $ocrExitCode = $LASTEXITCODE
    if (-not $pipelineSucceeded) { throw 'OCR output pipeline failed.' }
    if ($ocrExitCode -ne 0) { throw "OCR script failed with exit code $ocrExitCode." }
    if (-not (Test-Path -LiteralPath $resultPath -PathType Leaf)) { throw 'OCR result file was not created.' }
    $result = Get-Content -LiteralPath $resultPath -Raw -Encoding UTF8 -ErrorAction Stop
    if ([string]::IsNullOrWhiteSpace($result)) { throw 'OCR result file is empty.' }
    Write-Output $result
    exit 0
  } catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
  }
}
```

- 不合并 stderr，也不以管道最后一个命令成功代替脚本成功；`$ErrorActionPreference = 'Stop'` 不会自动把原生程序或脚本的非零退出码变成异常，所以仍须单独检查 `$LASTEXITCODE`。
- 结果文件为 UTF-8 编码（Windows PowerShell 5.1 写入 BOM），请按 UTF-8 读取。不要改用 `powershell.exe ... 1> 文件` 之类的子进程重定向捕获结果：这违反“不要从一个 shell 启动另一个 shell”，且 PowerShell 5.1 的 `1>`/`2>` 重定向会写成 UTF-16LE，按 UTF-8 读取会乱码。
- 日志中的 `ppocr.exe exited: code=0` 只代表 OCR 程序本身退出成功；本次调用是否完成以退出码 0、结果文件非空，以及日志末尾出现 `Done. elapsed=... lines=N` 为准。
- 工具不回显时，使用文件读取工具读取上面预先确定的结果文件，确认其中有识别文本或明确的 `[no text found]`，不能把 INFO 日志当作识别结果。
- 文件不存在、为空或调用失败时，报告未获得有效结果，并读取 `.openvino\log\ocr-npu-*.log` 中与本次调用对应的日志排查。失败时产生的部分文件不代表成功；不要盲目重复调用 OCR。

## 下载与完整性

- 下载源：仅使用 ModelScope；模型与 OCR 运行时来自 ModelScope 模型仓库，PDF 工具来自 ModelScope 资产库。下载失败时报告错误，不切换其他来源。
- TLS 证书校验默认**开启**。PowerShell 支持用户显式设置 `OCR_ALLOW_INSECURE_TLS=1` 临时关闭校验；Git Bash 不支持该开关。**不要主动替用户设置该变量**，必须先说明它会关闭下载来源的身份验证。
- `runtime-checksums.txt` 已包含全部 14 个默认下载资产的 SHA-256，来自 ModelScope 发布仓库元数据，并已逐个下载复算一致；来源及修订号记录在清单中。这依赖发布方和 HTTPS，不等同于独立数字签名。若使用自定义资产或清单而出现 `no SHA-256 recorded ... integrity not verified`，仍表示未执行完整性比对，不能隐藏警告或声称下载已验证。
- 校验仅针对新下载的资产，不会重新校验已安装文件。已有指纹不匹配时拒绝该下载并终止调用；缺少指纹时保留警告并继续，不是严格校验模式。
- 模型键必须为 `PP-OCRv5_server_det_ov/inference.bin` 或 `PP-OCRv5_server_rec_ov/inference.bin` 等完整名称；旧的裸文件名键无法区分模型，不再使用，需重新生成并核验。
- 发布维护者须提供原始 `ppocr-windows-x64.zip` 和 `pdfium.zip`（正常下载解压后会删除压缩包），运行 `scripts\pin-runtime-checksums.ps1 -ArchiveDir "C:\verified-archives"`；模型默认读取 `%USERPROFILE%\.openvino\models`，也可用 `-RuntimeRoot` 指定缓存根目录。生成器要求全部 14 个资产齐全，默认只写 `runtime-checksums.candidate.txt`，不会覆盖发布清单。
- 候选指纹必须与可信发布方或独立核验过的发布资产逐项确认，之后才可更新 `runtime-checksums.txt` 并随技能发布。仅对本次未验证下载计算哈希不能建立可信性，也不能从解压后的 exe/dll 推导原始 zip 的哈希。
- PowerShell 的系统代理默认不启用，确需使用时由用户设置 `OCR_USE_SYSTEM_PROXY=1`；Git Bash 不读取此开关，使用 curl 自身的代理配置。

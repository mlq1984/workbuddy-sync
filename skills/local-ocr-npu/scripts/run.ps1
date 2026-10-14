param(
    [Parameter(Position=0)]
    [string]$InputPath,
    [string]$Device = ''
)

$ErrorActionPreference = 'Stop'

# --- TLS ---
# Negotiate TLS 1.2 and KEEP certificate validation enabled, so every downloaded
# runtime/model is authenticated against the host it came from.
# Hardened build - see README.md and THIRD-PARTY-NOTICES.md.
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# Corporate SSL-inspection appliances present an untrusted CA, which makes the
# downloads below fail. The upstream revision disabled certificate validation
# unconditionally to work around that; it is now strictly opt-in, because
# disabling validation would let any network attacker substitute the
# executables that this skill later runs.
if ($env:OCR_ALLOW_INSECURE_TLS -eq '1') {
    Write-Warning 'OCR_ALLOW_INSECURE_TLS=1: TLS certificate validation is DISABLED for this run.'
    try {
        Add-Type -TypeDefinition @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class PpocrTrustAll : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int err) { return true; }
}
"@
        [System.Net.ServicePointManager]::CertificatePolicy = New-Object PpocrTrustAll
    } catch { }
}

# --- Proxy ---
# Only used when explicitly requested: handing the machine's default credentials
# to an arbitrary proxy is an avoidable credential exposure.
if ($env:OCR_USE_SYSTEM_PROXY -eq '1') {
    [System.Net.WebRequest]::DefaultWebProxy.Credentials = [System.Net.CredentialCache]::DefaultCredentials
}

# ===========================================================================
#  Configuration — the skill package ships no executables. Every native
#  runtime file (ppocr.exe, openvino.dll, pdf2png.exe, pdfium.dll) is
#  downloaded on first run into %USERPROFILE%\.openvino\bin\, next to the
#  models. Only bin\platform.ps1 lives inside the package.
#  Override via environment variables or edit defaults below.
# ===========================================================================
$SkillRoot          = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$OpenVinoRoot       = Join-Path $env:USERPROFILE '.openvino'
$ModelsRoot         = Join-Path $OpenVinoRoot 'models'
$RuntimeBinDir      = Join-Path $OpenVinoRoot 'bin'
$DefaultDevice      = if ($env:OCR_DEVICE)       { $env:OCR_DEVICE }       else { 'npu' }
$DefaultPpOcrExe    = if ($env:PPOCR_EXE)        { $env:PPOCR_EXE }        else { Join-Path $RuntimeBinDir 'ppocr.exe' }
$DefaultDetModelDir = if ($env:DET_MODEL_DIR)     { $env:DET_MODEL_DIR }    else { Join-Path $ModelsRoot 'PP-OCRv5_server_det_ov' }
$DefaultRecModelDir = if ($env:REC_MODEL_DIR)     { $env:REC_MODEL_DIR }    else { Join-Path $ModelsRoot 'PP-OCRv5_server_rec_ov' }
$DetModelName       = if ($env:DET_MODEL_NAME)    { $env:DET_MODEL_NAME }   else { 'PP-OCRv5_server_det' }
$RecModelName       = if ($env:REC_MODEL_NAME)    { $env:REC_MODEL_NAME }   else { 'PP-OCRv5_server_rec' }
$RecBatchSize       = if ($env:REC_BATCH_SIZE)    { $env:REC_BATCH_SIZE }   else { '1' }
$RecScoreThresh     = if ($env:REC_SCORE_THRESH)  { $env:REC_SCORE_THRESH } else { '0.0' }

# ModelScope is primary; HuggingFace is the fallback
$MsRepoUrl   = if ($env:MS_REPO_URL)       { $env:MS_REPO_URL }       else { 'https://modelscope.cn/models/FionaGu1019/PaddleOCR-OpenVINO/resolve/master' }
$HfRepoUrl   = if ($env:HF_REPO_URL)       { $env:HF_REPO_URL }       else { 'https://huggingface.co/Fiona1019/PaddleOCR-OpenVINO/resolve/main' }
$BinAssetName = 'ppocr-windows-x64.zip'
# The PDF renderer (pdf2png.exe + pdfium.dll) lives in the shared skill-asset
# bucket, not in the OCR model repo.
$SkillAssetsUrl  = if ($env:SKILL_ASSETS_URL) { $env:SKILL_ASSETS_URL } else { 'https://modelscope.cn/datasets/aiplayground/Local-AIPC-Skills/resolve/master' }
$PdfiumAssetName = 'pdfium.zip'
# ===========================================================================

$EffectiveDevice = if ($Device) { $Device } else { $DefaultDevice }
$PpOcrExe        = $DefaultPpOcrExe
$DetModelDir     = $DefaultDetModelDir
$RecModelDir     = $DefaultRecModelDir

# --- Logging ---
$LogDir = Join-Path $env:USERPROFILE '.openvino\log'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$LogTimestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$LogFile = Join-Path $LogDir "ocr-npu-$LogTimestamp.log"
Add-Content $LogFile "[$(Get-Date)] Log initialized. SkillRoot=$SkillRoot"
function Write-Log($msg) { Add-Content $LogFile "[$(Get-Date)] $msg" }

# --- Integrity check helpers (runtime-checksums.txt) ----------------------
# Every downloaded asset is matched against the SHA-256 recorded in
# runtime-checksums.txt. Regenerate that file with
# scripts\pin-runtime-checksums.ps1 after a verified download. An asset with no
# recorded digest still downloads, but the gap is reported instead of ignored;
# a digest that does not match aborts that asset.
$ChecksumsFile = if ($env:OCR_CHECKSUMS_FILE) { $env:OCR_CHECKSUMS_FILE } else { Join-Path $SkillRoot 'runtime-checksums.txt' }

function Get-ExpectedHash([string]$AssetName) {
    if (-not (Test-Path -LiteralPath $ChecksumsFile)) { return $null }
    $pattern = '^([0-9a-fA-F]{64})\s+\*?' + [regex]::Escape($AssetName) + '$'
    foreach ($line in (Get-Content -LiteralPath $ChecksumsFile -ErrorAction SilentlyContinue)) {
        $m = [regex]::Match(([string]$line).Trim(), $pattern)
        if ($m.Success) { return $m.Groups[1].Value.ToLower() }
    }
    return $null
}

function Test-AssetSha256([string]$FilePath, [string]$AssetName) {
    $expected = Get-ExpectedHash $AssetName
    if (-not $expected) {
        Write-Host "  [WARN] No SHA-256 recorded for $AssetName; integrity not verified."
        Write-Log "No checksum for $AssetName (integrity not verified)."
        return $true
    }
    $actual = (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected) {
        Write-Host "  [ERROR] SHA-256 mismatch for $AssetName"
        Write-Host "          expected: $expected"
        Write-Host "          actual:   $actual"
        Write-Log "SHA-256 mismatch for $AssetName (expected $expected, got $actual)."
        return $false
    }
    Write-Host "  [OK] SHA-256 verified: $AssetName"
    Write-Log "SHA-256 verified: $AssetName"
    return $true
}

# --- Argument check ---
if (-not $InputPath) {
    Write-Host 'Usage: scripts\run.ps1 "<image_file_or_pdf_or_directory>" [-Device cpu|npu|gpu]'
    exit 1
}

Write-Log "run.ps1 started: InputPath='$InputPath' Device='$EffectiveDevice'"
Write-Host "========================================"
Write-Host " Local NPU OCR"
Write-Host "========================================"

# ===========================================================================
#  STEP 1 -- Environment check
# ===========================================================================
Write-Host ""
Write-Host "[1/4] Checking environment..."

$PlatformScript = Join-Path $SkillRoot 'bin\platform.ps1'
if (Test-Path $PlatformScript) {
    $IsAipc = & $PlatformScript --is-aipc
    Write-Log "platform --is-aipc returned $IsAipc"
    if ($IsAipc -ne '1') {
        Write-Host 'This skill requires an Intel AIPC platform.'
        exit 1
    }
} else {
    Write-Host 'WARN: bin\platform.ps1 missing; skipping AIPC check.'
}

# --- Validate input path ---
if (-not (Test-Path $InputPath)) {
    Write-Host "  [ERROR] Input path does not exist: $InputPath"
    exit 1
}
$OriginalInputItem = Get-Item -LiteralPath $InputPath
$IsPdfInput = (-not $OriginalInputItem.PSIsContainer) -and ($OriginalInputItem.Extension -ieq '.pdf')
Write-Host "  [OK] Device: $($EffectiveDevice.ToUpper())  |  Input: $InputPath"

# ===========================================================================
#  DOWNLOAD -- on first install, download runtime + models synchronously,
#  showing a progress message and waiting until it finishes before continuing.
# ===========================================================================
$BinDir       = Split-Path $PpOcrExe -Parent
$downloadLog  = Join-Path $LogDir 'ocr-npu-download.log'

$needBin = -not (Test-Path (Join-Path $BinDir 'openvino.dll'))
$needPdf = -not ((Test-Path (Join-Path $BinDir 'pdf2png.exe')) -and (Test-Path (Join-Path $BinDir 'pdfium.dll')))
$needDet = -not (Test-Path $DetModelDir)
$needRec = -not (Test-Path $RecModelDir)

if ($needBin -or $needPdf -or $needDet -or $needRec) {
    $dlScript = Join-Path $PSScriptRoot 'download.ps1'
    Write-Host ""
    Write-Host "  [DL] 首次安装: 正在下载运行时和模型 (~200 MB), 请稍候..."
    Write-Host "       进度日志: $downloadLog"
    Write-Log "Synchronous download starting via download.ps1."

    & $dlScript -BinDir $BinDir `
                -LogFile $downloadLog `
                -HfRepoUrl $HfRepoUrl `
                -MsRepoUrl $MsRepoUrl `
                -BinAssetName $BinAssetName `
                -SkillAssetsUrl $SkillAssetsUrl `
                -PdfiumAssetName $PdfiumAssetName `
                -DetModelDir $DetModelDir `
                -RecModelDir $RecModelDir

    Write-Host "  [DL] 下载完成, 继续运行..."
    Write-Log "Synchronous download finished; continuing."
}

# ===========================================================================
#  STEP 2 -- Validate runtime (ppocr.exe + DLLs)
# ===========================================================================
Write-Host ""
Write-Host "[2/4] Checking OCR runtime..."

if (-not (Test-Path $PpOcrExe)) {
    Write-Host "  [ERROR] ppocr.exe not found: $PpOcrExe"
    Write-Host "          运行时下载失败, 请检查网络后重新运行。日志: $downloadLog"
    exit 1
}
Write-Host "  [OK] ppocr.exe ready ($([math]::Round((Get-Item $PpOcrExe).Length/1KB,0)) KB)"
Write-Log "ppocr.exe resolved: $PpOcrExe"

# ===========================================================================
#  STEP 3 -- Validate models
# ===========================================================================
function Download-ModelDir {
    param([string]$ModelName, [string]$DestDir)
    Write-Host "  [...] Downloading model $ModelName (first-time install)..."
    Write-Log "Auto-download model: $ModelName -> $DestDir"
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null

    $apiUrl = "https://huggingface.co/api/models/Fiona1019/PaddleOCR-OpenVINO"
    try {
        $modelInfo = Invoke-RestMethod -Uri $apiUrl -TimeoutSec 30
        $siblings = $modelInfo.siblings | Where-Object { $_.rfilename -like "$ModelName/*" }
    } catch {
        Write-Log "HF API failed: $_  Using static file list."
        $siblings = $null
    }

    if (-not $siblings) {
        $knownFiles = @('inference.xml', 'inference.bin', 'inference.yml')
        if ($ModelName -match '_det_') { $knownFiles += 'inference_960.xml' }
        if ($ModelName -match '_rec_') {
            $knownFiles += @('inference_320.xml','inference_480.xml','inference_640.xml',
                             'inference_800.xml','inference_1280.xml')
        }
        $siblings = $knownFiles | ForEach-Object { [pscustomobject]@{ rfilename = "$ModelName/$_" } }
    }

    $downloaded = 0; $failed = 0
    foreach ($s in $siblings) {
        $fileName = Split-Path $s.rfilename -Leaf
        $destFile  = Join-Path $DestDir $fileName
        $ok = $false
        foreach ($url in @("$HfRepoUrl/$($s.rfilename)", "$MsRepoUrl/$($s.rfilename)")) {
            try {
                $ProgressPreference = 'SilentlyContinue'
                Invoke-WebRequest -Uri $url -OutFile $destFile -TimeoutSec 300 -UseBasicParsing
                $ProgressPreference = 'Continue'
                Write-Log "  OK: $fileName"
                $ok = $true; break
            } catch { Write-Log "  FAIL: $fileName from $url : $_" }
        }
        if ($ok -and (Test-AssetSha256 $destFile $fileName)) {
            $downloaded++
        } elseif ($ok) {
            $failed++
            Remove-Item -LiteralPath $destFile -Force -ErrorAction SilentlyContinue
        } else {
            $failed++
            Write-Host "  [WARN] Failed to download: $fileName"
        }
    }

    if ($failed -gt 0) {
        Write-Host "  [WARN] Model $ModelName incomplete ($failed file(s) failed)"
        Write-Host "         Manual download: https://huggingface.co/Fiona1019/PaddleOCR-OpenVINO"
    } else {
        Write-Host "  [OK] Model downloaded: $ModelName ($downloaded files)"
    }
    Write-Log "Model download done: $ModelName  ok=$downloaded  fail=$failed"
}

$needDownloadDet = -not (Test-Path $DetModelDir)
$needDownloadRec = -not (Test-Path $RecModelDir)

if ($needDownloadDet -or $needDownloadRec) {
    Write-Host ""
    Write-Host "[3/4] Downloading OCR models (first-time install, ~176 MB)..."
    New-Item -ItemType Directory -Path $ModelsRoot -Force | Out-Null
    if ($needDownloadDet) { Download-ModelDir -ModelName (Split-Path $DetModelDir -Leaf) -DestDir $DetModelDir }
    if ($needDownloadRec) { Download-ModelDir -ModelName (Split-Path $RecModelDir -Leaf) -DestDir $RecModelDir }
} else {
    Write-Host ""
    Write-Host "[3/4] Checking OCR models..."
    Write-Host "  [OK] Det model: $(Split-Path $DetModelDir -Leaf)"
    Write-Host "  [OK] Rec model: $(Split-Path $RecModelDir -Leaf)"
}

if (-not (Test-Path $DetModelDir)) {
    Write-Host "  [ERROR] Det model not found: $DetModelDir"
    exit 1
}
if (-not (Test-Path $RecModelDir)) {
    Write-Host "  [ERROR] Rec model not found: $RecModelDir"
    exit 1
}

# --- Add bin to PATH so DLLs are found ---
$PpOcrDir = Split-Path $PpOcrExe -Parent
$env:PATH = "$PpOcrDir;$env:PATH"

# --- Prepare output dir ---
$SavePath = Join-Path $env:TEMP 'ocr_npu_skill_output'
if (Test-Path $SavePath) { Remove-Item $SavePath -Recurse -Force }
New-Item -ItemType Directory -Path $SavePath | Out-Null
Write-Log "Output dir: $SavePath"

# --- Render PDF pages to temporary PNG files ---
$PdfPagesDir = $null
$PdfPageCount = 0
if ($IsPdfInput) {
    # Same directory the runtime was downloaded into, so a PPOCR_EXE override
    # keeps the PDF tool and the OCR runtime together.
    $PdfToolDir = $BinDir
    $PdfConverter = Join-Path $PdfToolDir 'pdf2png.exe'
    if (-not (Test-Path -LiteralPath $PdfConverter) -or -not (Test-Path -LiteralPath (Join-Path $PdfToolDir 'pdfium.dll'))) {
        Write-Host '  [ERROR] PDF 转换工具未就绪 (下载失败或未完成)。'
        Write-Host "          请检查网络后重新运行, 会自动重试下载。日志: $downloadLog"
        if (Test-Path $SavePath) { Remove-Item $SavePath -Recurse -Force }
        exit 1
    }

    $PdfPagesDir = Join-Path ([IO.Path]::GetTempPath()) ("ocr_npu_pdf_{0}" -f [guid]::NewGuid().ToString('N'))
    Write-Host "  [PDF] Rendering $($OriginalInputItem.Name) to PNG pages (200 DPI)..."
    Write-Log "Rendering PDF '$InputPath' to '$PdfPagesDir' with bundled PDFium."
    & $PdfConverter --input $InputPath --output $PdfPagesDir --dpi 200
    if ($LASTEXITCODE -ne 0) {
        Write-Host '  [ERROR] PDF conversion failed.'
        if (Test-Path $PdfPagesDir) { Remove-Item $PdfPagesDir -Recurse -Force }
        if (Test-Path $SavePath) { Remove-Item $SavePath -Recurse -Force }
        exit $LASTEXITCODE
    }

    $PdfPageCount = @(Get-ChildItem -LiteralPath $PdfPagesDir -Filter '*.png' -File).Count
    if ($PdfPageCount -eq 0) {
        Write-Host '  [ERROR] PDF conversion produced no PNG pages.'
        Remove-Item $PdfPagesDir -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item $SavePath -Recurse -Force -ErrorAction SilentlyContinue
        exit 1
    }
    $InputPath = $PdfPagesDir
    Write-Host "  [PDF] Ready: $PdfPageCount page(s)"
}

# ===========================================================================
#  STEP 4 -- Run OCR
# ===========================================================================
Write-Host ""
Write-Host "[4/4] Running OCR..."
$inputName = Split-Path $InputPath -Leaf
if ((Get-Item $InputPath).PSIsContainer) { $inputName = "$inputName (directory)" }
if ($IsPdfInput) { $inputName = "$($OriginalInputItem.Name) ($PdfPageCount pages)" }
Write-Host "  Input: $inputName  |  Device: $($EffectiveDevice.ToUpper())  |  Model: $DetModelName + $RecModelName"
if ($EffectiveDevice -eq 'npu') {
    Write-Host "  Note: first NPU run compiles model (~27s); subsequent runs ~0.3s"
}
Write-Log "Running ppocr.exe: device=$EffectiveDevice input=$InputPath"
$t0 = Get-Date

Push-Location $PpOcrDir
# Convert absolute paths to relative (avoids long-path crash in ppocr.exe)
$RelDetModelDir = Resolve-Path -Relative $DetModelDir
$RelRecModelDir = Resolve-Path -Relative $RecModelDir
$RelInputPath   = Resolve-Path -Relative $InputPath
$RelSavePath    = Resolve-Path -Relative $SavePath
& $PpOcrExe ocr `
    "--input=$RelInputPath" `
    "--text_detection_model_name=$DetModelName" `
    "--text_detection_model_dir=$RelDetModelDir" `
    "--text_recognition_model_name=$RecModelName" `
    "--text_recognition_model_dir=$RelRecModelDir" `
    "--device=$EffectiveDevice" `
    "--text_recognition_batch_size=$RecBatchSize" `
    "--text_rec_score_thresh=$RecScoreThresh" `
    "--save_path=$RelSavePath"
$ExitCode = $LASTEXITCODE
Pop-Location
Write-Log "ppocr.exe exited: code=$ExitCode"

# Auto-retry on CPU if NPU failed
if ($ExitCode -ne 0 -and $EffectiveDevice -eq 'npu') {
    Write-Host "  [WARN] NPU inference failed (exit $ExitCode) -- retrying on CPU..."
    Write-Log "NPU failed; retrying on CPU."
    $EffectiveDevice = 'cpu'
    if (Test-Path $SavePath) { Remove-Item $SavePath -Recurse -Force }
    New-Item -ItemType Directory -Path $SavePath | Out-Null
    Push-Location $PpOcrDir
    $RelDetModelDir = Resolve-Path -Relative $DetModelDir
    $RelRecModelDir = Resolve-Path -Relative $RecModelDir
    $RelInputPath   = Resolve-Path -Relative $InputPath
    $RelSavePath    = Resolve-Path -Relative $SavePath
    & $PpOcrExe ocr `
        "--input=$RelInputPath" `
        "--text_detection_model_name=$DetModelName" `
        "--text_detection_model_dir=$RelDetModelDir" `
        "--text_recognition_model_name=$RecModelName" `
        "--text_recognition_model_dir=$RelRecModelDir" `
        "--device=cpu" `
        "--text_recognition_batch_size=$RecBatchSize" `
        "--text_rec_score_thresh=$RecScoreThresh" `
        "--save_path=$RelSavePath"
    $ExitCode = $LASTEXITCODE
    Pop-Location
    Write-Log "CPU retry exited: code=$ExitCode"
}

$elapsed = [math]::Round(((Get-Date) - $t0).TotalSeconds, 2)

if ($ExitCode -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] OCR failed (exit code $ExitCode) | ${elapsed}s | $($EffectiveDevice.ToUpper())"
    Write-Host "  Log: $LogFile"
    if (Test-Path $SavePath) { Remove-Item $SavePath -Recurse -Force }
    if ($PdfPagesDir -and (Test-Path $PdfPagesDir)) { Remove-Item $PdfPagesDir -Recurse -Force }
    exit $ExitCode
}

# --- Print results ---
$TxtFiles = Get-ChildItem $SavePath -Filter '*.txt' -ErrorAction SilentlyContinue
$lineCount = 0
Write-Host ""
Write-Host "------------------------------------------------------------------------"
if ($TxtFiles.Count -eq 0) {
    Write-Host '[no text found]'
} else {
    foreach ($f in $TxtFiles) {
        if ($TxtFiles.Count -gt 1) { Write-Host "-- $($f.BaseName) --" }
        $lines = Get-Content $f.FullName -Encoding UTF8
        $lines | ForEach-Object { Write-Host $_; $lineCount++ }
    }
}
Write-Host "------------------------------------------------------------------------"
Write-Host ""
Write-Host "[OK] OCR complete | $($TxtFiles.Count) image(s) | $lineCount line(s) | ${elapsed}s | $($EffectiveDevice.ToUpper())"
Write-Host "  Log: $LogFile"

# --- Cleanup ---
if (Test-Path $SavePath) { Remove-Item $SavePath -Recurse -Force }
if ($PdfPagesDir -and (Test-Path $PdfPagesDir)) { Remove-Item $PdfPagesDir -Recurse -Force }
Write-Log "Done. elapsed=${elapsed}s lines=$lineCount"
exit 0

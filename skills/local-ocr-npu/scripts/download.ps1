# Background download script for local-ocr-npu skill
# Called synchronously by run.ps1. Do NOT call directly.
#
# Download sources:
#   OCR runtime : ModelScope CDN only
#   PDF tool    : ModelScope CDN only
#   Models      : ModelScope CDN --> HuggingFace fallback
#
# Everything lands in $BinDir (%USERPROFILE%\.openvino\bin) -- the skill
# package itself ships no executables.

param(
    [string]$BinDir,
    [string]$LogFile,
    [string]$HfRepoUrl,
    [string]$MsRepoUrl,
    [string]$BinAssetName,
    [string]$SkillAssetsUrl,
    [string]$PdfiumAssetName,
    [string]$DetModelDir,
    [string]$RecModelDir
)

$Log = $LogFile
$LogParent = Split-Path $Log -Parent
if ($LogParent -and -not (Test-Path $LogParent)) {
    New-Item -ItemType Directory -Path $LogParent -Force | Out-Null
}

function L($msg) { Add-Content $Log "[$(Get-Date -Format 'HH:mm:ss')] $msg" }

# --- TLS ---
# TLS 1.2 with certificate validation ON. See README.md "安全与合规说明".
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
if ($env:OCR_ALLOW_INSECURE_TLS -eq '1') {
    Write-Warning 'OCR_ALLOW_INSECURE_TLS=1: TLS certificate validation is DISABLED for this run.'
    L 'WARNING: TLS certificate validation disabled by OCR_ALLOW_INSECURE_TLS=1.'
    try {
        Add-Type -TypeDefinition @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class DlTrustAll : ICertificatePolicy {
    public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int err) { return true; }
}
"@
        [System.Net.ServicePointManager]::CertificatePolicy = New-Object DlTrustAll
    } catch { }
}

# --- Proxy (opt-in: do not leak default credentials to an arbitrary proxy) ---
$SystemProxy = $null
if ($env:OCR_USE_SYSTEM_PROXY -eq '1') {
    try {
        [System.Net.WebRequest]::DefaultWebProxy.Credentials = [System.Net.CredentialCache]::DefaultCredentials
        $testUri = [System.Uri]'https://www.modelscope.cn'
        $proxyUri = [System.Net.WebRequest]::GetSystemWebProxy().GetProxy($testUri)
        if ($proxyUri -and $proxyUri.Host -ne 'www.modelscope.cn') {
            $SystemProxy = $proxyUri.AbsoluteUri
            L "System proxy detected: $SystemProxy"
        }
    } catch { }
} else {
    L 'System proxy not used (set OCR_USE_SYSTEM_PROXY=1 to enable).'
}

# --- Integrity check (runtime-checksums.txt) -------------------------------
# Matches each downloaded asset against a pinned SHA-256. An asset with no
# pinned digest is downloaded with a logged warning; a digest that does not
# match rejects the file. Regenerate the pins with pin-runtime-checksums.ps1.
$ChecksumsFile = if ($env:OCR_CHECKSUMS_FILE) { $env:OCR_CHECKSUMS_FILE } else {
    Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'runtime-checksums.txt'
}

function Test-AssetSha256([string]$FilePath, [string]$AssetName) {
    if (-not (Test-Path -LiteralPath $ChecksumsFile)) {
        L "WARN: no checksum file at $ChecksumsFile; integrity of $AssetName not verified."
        return $true
    }
    $pattern = '^([0-9a-fA-F]{64})\s+\*?' + [regex]::Escape($AssetName) + '$'
    $expected = $null
    foreach ($line in (Get-Content -LiteralPath $ChecksumsFile -ErrorAction SilentlyContinue)) {
        $m = [regex]::Match(([string]$line).Trim(), $pattern)
        if ($m.Success) { $expected = $m.Groups[1].Value.ToLower(); break }
    }
    if (-not $expected) {
        L "WARN: no SHA-256 recorded for $AssetName; integrity not verified."
        return $true
    }
    $actual = (Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected) {
        L "ERROR: SHA-256 mismatch for $AssetName (expected $expected, got $actual)."
        return $false
    }
    L "SHA-256 verified: $AssetName"
    return $true
}

# ---------------------------------------------------------------------------
# Progress reporting: the host agent relays these lines to the user. The first
# line is emitted as soon as the download starts, then at most one line per
# $ProgressDisplayInterval seconds -- a long download reports in every 5 minutes
# instead of printing a line per completed file. -Force bypasses the throttle and
# is used for the final 100% line so the finish is never swallowed.
# ---------------------------------------------------------------------------
$script:ProgressTotal = 0
$script:ProgressDone  = 0
$script:ProgressDisplayInterval = 300
$script:ProgressLastShown = $null

function Report-Progress {
    param([string]$Label, [switch]$Force)
    if ($script:ProgressTotal -le 0) { return }
    $now = Get-Date
    if (-not $Force -and $null -ne $script:ProgressLastShown -and
        ($now - $script:ProgressLastShown).TotalSeconds -lt $script:ProgressDisplayInterval) {
        return
    }
    $script:ProgressLastShown = $now
    $pct = [math]::Min(100.0, 100.0 * $script:ProgressDone / $script:ProgressTotal)
    $filled = [int][math]::Round(20.0 * $pct / 100.0)
    $bar = ('#' * $filled) + ('-' * (20 - $filled))
    $line = "模型下载中 [$bar] {0,5:N1}% | {1}/{2} 文件 | {3}" -f $pct, $script:ProgressDone, $script:ProgressTotal, $Label
    Write-Host $line
    L $line
}

function Get-ModelFiles {
    param([string]$ModelName)
    $files = @('inference.xml', 'inference.bin', 'inference.yml')
    if ($ModelName -match '_det_') { $files += 'inference_960.xml' }
    if ($ModelName -match '_rec_') {
        $files += @('inference_320.xml','inference_480.xml','inference_640.xml',
                    'inference_800.xml','inference_1280.xml')
    }
    return $files
}

function Download-File {
    param([string[]]$Urls, [string]$OutFile)
    foreach ($url in $Urls) {
        # Build parameter sets: try with proxy first (if detected), then without
        $paramSets = @( @{ UseBasicParsing=$true; TimeoutSec=300; Uri=$url; OutFile=$OutFile } )
        if ($SystemProxy) {
            $paramSets = @(
                @{ UseBasicParsing=$true; TimeoutSec=300; Uri=$url; OutFile=$OutFile; Proxy=$SystemProxy; ProxyUseDefaultCredentials=$true },
                @{ UseBasicParsing=$true; TimeoutSec=300; Uri=$url; OutFile=$OutFile }
            )
        }
        foreach ($params in $paramSets) {
            try {
                $ProgressPreference = 'SilentlyContinue'
                Invoke-WebRequest @params
                if ((Test-Path -LiteralPath $OutFile) -and (Get-Item -LiteralPath $OutFile).Length -gt 0) {
                    return $true
                }
                L "  Empty download from $url; trying next source."
            } catch { }
        }
    }
    return $false
}

try {
    "$(Get-Date -Format 'HH:mm:ss') Download started." | Set-Content $Log

    # -------------------------------------------------------------------------
    # 1. Download ppocr.exe + DLLs
    #    Try ModelScope CDN first (fast in CN), then GitHub
    # -------------------------------------------------------------------------
    $ovinoDll  = Join-Path $BinDir 'openvino.dll'
    $pdf2png   = Join-Path $BinDir 'pdf2png.exe'
    $pdfiumDll = Join-Path $BinDir 'pdfium.dll'
    $needPdfTool = -not ((Test-Path $pdf2png) -and (Test-Path $pdfiumDll))

    # Count everything that still has to be fetched so the percentage is
    # meaningful from the very first line.
    $script:ProgressTotal = 0
    if (-not (Test-Path $ovinoDll)) { $script:ProgressTotal += 1 }
    if ($needPdfTool) { $script:ProgressTotal += 1 }
    if (-not (Test-Path $DetModelDir)) { $script:ProgressTotal += (Get-ModelFiles (Split-Path $DetModelDir -Leaf)).Count }
    if (-not (Test-Path $RecModelDir)) { $script:ProgressTotal += (Get-ModelFiles (Split-Path $RecModelDir -Leaf)).Count }
    $script:ProgressDone = 0
    Report-Progress '准备下载'

    if (-not (Test-Path $ovinoDll)) {
        L 'Downloading ppocr.exe + DLLs...'
        New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
        $zip = Join-Path $env:TEMP 'ppocr-skill-dl.zip'

        $msBinUrl = "$MsRepoUrl/bin/$BinAssetName"
        L "  Downloading from ModelScope: $msBinUrl"
        $ok = Download-File -Urls @($msBinUrl) -OutFile $zip
        if ($ok -and -not (Test-AssetSha256 $zip $BinAssetName)) {
            Remove-Item $zip -Force -ErrorAction SilentlyContinue
            $ok = $false
        }

        if ($ok) {
            Expand-Archive -Path $zip -DestinationPath $BinDir -Force
            Remove-Item $zip -Force -ErrorAction SilentlyContinue
            L 'ppocr.exe + DLLs: OK'
            $script:ProgressDone += 1
            Report-Progress 'OpenVINO 运行时'
        } else {
            L 'ppocr.exe + DLLs: FAILED -- manual download required'
            L "  From ModelScope: https://modelscope.cn/models/FionaGu1019/PaddleOCR-OpenVINO"
        }
    } else {
        L 'ppocr.exe + DLLs: already present.'
    }

    # -------------------------------------------------------------------------
    # 2. Download the PDF renderer (pdf2png.exe + pdfium.dll), ~3 MB.
    #    A failure here is not fatal: image and directory OCR still work, and
    #    run.ps1 reports a clear error only when the input is actually a PDF.
    # -------------------------------------------------------------------------
    if ($needPdfTool) {
        L 'Downloading pdf2png.exe + pdfium.dll...'
        New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
        $pdfZip = Join-Path $env:TEMP 'pdfium-skill-dl.zip'

        $pdfUrl = "$SkillAssetsUrl/$PdfiumAssetName"
        L "  Downloading from ModelScope: $pdfUrl"
        $ok = Download-File -Urls @($pdfUrl) -OutFile $pdfZip
        if ($ok -and -not (Test-AssetSha256 $pdfZip $PdfiumAssetName)) {
            Remove-Item $pdfZip -Force -ErrorAction SilentlyContinue
            $ok = $false
        }

        if ($ok) {
            Expand-Archive -Path $pdfZip -DestinationPath $BinDir -Force
            Remove-Item $pdfZip -Force -ErrorAction SilentlyContinue
            L 'pdf2png.exe + pdfium.dll: OK'
            $script:ProgressDone += 1
            Report-Progress 'PDF 转换工具'
        } else {
            L 'pdf2png.exe + pdfium.dll: FAILED -- PDF input will be unavailable until the next run.'
            Write-Host '  [WARN] PDF 转换工具下载失败, 图片识别不受影响; 处理 PDF 前请重新运行以重试下载。'
            # Do not count it as done: the remaining percentage stays honest.
            $script:ProgressTotal -= 1
        }
    } else {
        L 'pdf2png.exe + pdfium.dll: already present.'
    }

    # -------------------------------------------------------------------------
    # 3. Download models (parallel, ModelScope first)
    # -------------------------------------------------------------------------
    function Download-Model {
        param([string]$ModelName, [string]$DestDir)
        L "Downloading model: $ModelName"
        New-Item -ItemType Directory -Path $DestDir -Force | Out-Null

        $files = Get-ModelFiles $ModelName

        # Parallel download using jobs (one job per file)
        $jobs =         foreach ($fn in $files) {
            $destFile = Join-Path $DestDir $fn
            $urls = @("$MsRepoUrl/$ModelName/$fn", "$HfRepoUrl/$ModelName/$fn")
            Start-Job -ScriptBlock {
                param($u, $o)
                foreach ($url in $u) {
                    try {
                        $ProgressPreference = 'SilentlyContinue'
                        Invoke-WebRequest -Uri $url -OutFile $o -TimeoutSec 300 -UseBasicParsing
                        return "OK: $(Split-Path $o -Leaf)"
                    } catch { }
                }
                return "FAIL: $(Split-Path $o -Leaf)"
            } -ArgumentList $urls, $destFile
        }

        # Wait for all jobs and collect results
        # Poll instead of Wait-Job so progress is reported as each file lands,
        # not in one burst after every job has finished.
        $pending = [System.Collections.ArrayList]@($jobs)
        while ($pending.Count -gt 0) {
            $finished = @($pending | Where-Object { $_.State -ne 'Running' })
            foreach ($job in $finished) {
                $result = [string](Receive-Job $job)
                L "  $result"
                Remove-Job $job
                $pending.Remove($job)
                if ($result -like 'OK: *') {
                    $completedName = $result.Substring(4).Trim()
                    $completedFile = Join-Path $DestDir $completedName
                    if (-not (Test-AssetSha256 $completedFile $completedName)) {
                        Remove-Item -LiteralPath $completedFile -Force -ErrorAction SilentlyContinue
                        L "  rejected $completedName (SHA-256 mismatch)"
                    }
                }
                $script:ProgressDone += 1
                Report-Progress $ModelName
            }
            if ($pending.Count -gt 0) { Start-Sleep -Milliseconds 500 }
        }
    }

    if (-not (Test-Path $DetModelDir)) { Download-Model (Split-Path $DetModelDir -Leaf) $DetModelDir }
    if (-not (Test-Path $RecModelDir)) { Download-Model (Split-Path $RecModelDir -Leaf) $RecModelDir }

    # -Force so the completed 100% line is always shown, even if the last
    # per-file update happened inside the current throttle window.
    Report-Progress '下载完成' -Force

    L 'ALL DONE -- skill ready. Re-run to start OCR.'

} catch {
    L "ERROR: $_"
}

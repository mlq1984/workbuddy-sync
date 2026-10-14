#!/usr/bin/env bash
set -u
set -o pipefail

[[ $# -ge 1 ]] || { printf '%s\n' 'Usage: bash scripts/run.sh <image-or-pdf-or-directory> [--device cpu|npu|gpu]'; exit 1; }
input_path="$1"; shift
device="${OCR_DEVICE:-npu}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        -Device|--device)
            [[ $# -ge 2 ]] || { printf 'ERROR: Missing value for %s\n' "$1" >&2; exit 1; }
            device="$2"
            shift 2
            ;;
        *) printf 'ERROR: Unknown argument: %s\n' "$1" >&2; exit 1;;
    esac
done
case "${device,,}" in
    cpu|npu|gpu) device="${device,,}" ;;
    *) printf 'ERROR: Unsupported device: %s\n' "$device" >&2; exit 1;;
esac
[[ -e "$input_path" ]] || { printf 'ERROR: Input path does not exist: %s\n' "$input_path" >&2; exit 1; }

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 1
skill_root="$(cd -- "$script_dir/.." && pwd -P)" || exit 1
helper="$script_dir/git-bash-env.sh"
[[ -f "$helper" ]] || helper="$script_dir/../../../../common/scripts/git-bash-env.sh"
[[ -f "$helper" ]] || { printf '%s\n' 'ERROR: Git Bash runtime helper is missing.' >&2; exit 1; }
. "$helper" || exit 1
check_aipc || exit $?
command -v cygpath >/dev/null 2>&1 || { skill_fail 'This entry point requires Git Bash for Windows.'; exit 1; }

user_profile="${USERPROFILE:-${HOME:-}}"
# The skill package ships no executables: every native runtime file is
# downloaded on first run into %USERPROFILE%\.openvino\bin, next to the models.
openvino_root="$(cygpath -u "$user_profile")/.openvino"
models_root="$openvino_root/models"
bin_dir="$openvino_root/bin"
exe="$bin_dir/ppocr.exe"
det_name='PP-OCRv5_server_det'
rec_name='PP-OCRv5_server_rec'
det_dir="$models_root/PP-OCRv5_server_det_ov"
rec_dir="$models_root/PP-OCRv5_server_rec_ov"
ms_root="${MS_REPO_URL:-https://modelscope.cn/models/FionaGu1019/PaddleOCR-OpenVINO/resolve/master}"
hf_root="${HF_REPO_URL:-https://huggingface.co/Fiona1019/PaddleOCR-OpenVINO/resolve/main}"
# The PDF renderer lives in the shared skill-asset bucket, not the model repo.
skill_assets_url="${SKILL_ASSETS_URL:-https://modelscope.cn/datasets/aiplayground/Local-AIPC-Skills/resolve/master}"
bin_asset='ppocr-windows-x64.zip'
pdfium_asset='pdfium.zip'
pdf_tool_dir="$bin_dir"

# ---------------------------------------------------------------------------
# Integrity metadata. Every downloaded asset is checked against the SHA-256
# recorded in runtime-checksums.txt (format: "<sha256>␣␣<asset-name>").
# Regenerate that file with scripts/pin-runtime-checksums.ps1 after a verified
# download. When an asset has no recorded hash the download still proceeds,
# but a warning is printed so the gap is never silent.
# ---------------------------------------------------------------------------
checksums_file="${OCR_CHECKSUMS_FILE:-$skill_root/runtime-checksums.txt}"

verify_sha256() {
    local file="$1" asset="$2" expected actual
    [[ -f "$checksums_file" ]] || return 2
    expected="$(sed -nE "s/^([0-9a-fA-F]{64})[[:space:]]+\*?${asset//./\\.}$/\1/p" "$checksums_file" | head -n 1)"
    [[ -n "$expected" ]] || return 2
    command -v sha256sum >/dev/null 2>&1 || return 2
    actual="$(sha256sum "$file" | awk '{print $1}')" || return 1
    if [[ "${actual,,}" != "${expected,,}" ]]; then
        printf 'ERROR: SHA-256 mismatch for %s\n  expected: %s\n  actual:   %s\n' \
            "$asset" "$expected" "$actual" >&2
        return 1
    fi
    printf 'SHA-256 verified: %s\n' "$asset"
    return 0
}

download_file() {
    local output="$1" primary="$2" fallback="$3" asset="${4:-$(basename -- "$1")}"
    local partial="${output}.partial" verify_rc
    mkdir -p "$(dirname "$output")" || return 1
    rm -f "$partial"
    if command -v curl.exe >/dev/null 2>&1; then
        local partial_win
        partial_win="$(cygpath -w "$partial")" || return 1
        curl.exe -fL --ssl-no-revoke -o "$partial_win" "$primary" \
            || { [[ -n "$fallback" ]] && curl.exe -fL --ssl-no-revoke -o "$partial_win" "$fallback"; } \
            || return 1
    else
        curl -fL -o "$partial" "$primary" \
            || { [[ -n "$fallback" ]] && curl -fL -o "$partial" "$fallback"; } \
            || return 1
    fi
    [[ -s "$partial" ]] || {
        printf 'ERROR: downloaded file is empty: %s\n' "$asset" >&2
        rm -f "$partial"; return 1
    }
    verify_sha256 "$partial" "$asset"
    verify_rc=$?
    if [[ $verify_rc -eq 1 ]]; then
        rm -f "$partial"
        return 1
    elif [[ $verify_rc -eq 2 ]]; then
        printf 'WARN: no SHA-256 recorded for %s; integrity not verified.\n' "$asset" >&2
    fi
    mv -f "$partial" "$output"
}

if [[ ! -f "$bin_dir/openvino.dll" ]]; then
    mkdir -p "$bin_dir"
    zip_file="${TEMP:-/tmp}/ppocr-windows-x64.zip"
    download_file "$zip_file" "$ms_root/bin/$bin_asset" "${PPOCR_BIN_URL_FALLBACK:-}" "$bin_asset" || exit 1
    zip_posix="$(cygpath -u "$zip_file")" || exit 1
    # NOTE: this archive is zipped by a Windows tool, so its entry names use
    # backslash path separators. unzip then prints
    # "appears to use backslashes as path separators" and exits with code 1
    # even though every file IS extracted correctly. Writing
    # `unzip ... || exit 1` therefore aborts the very first run right after a
    # successful extraction. Tolerate 1 (warning); fail only on a real error
    # (>=2) or when the essential runtime files are missing.
    unzip -oq "$zip_posix" -d "$bin_dir"
    unzip_status=$?
    if [[ $unzip_status -ge 2 || ! -f "$bin_dir/openvino.dll" || ! -f "$bin_dir/ppocr.exe" ]]; then
        printf 'ERROR: failed to extract the OCR runtime archive (unzip exit code %s).\n' "$unzip_status" >&2
        exit 1
    fi
    if [[ $unzip_status -ne 0 ]]; then
        printf 'WARN: unzip exit code %s (path-separator warning); extraction verified OK.\n' "$unzip_status" >&2
    fi
    rm -f "$zip_posix"
fi

# The PDF renderer (~3 MB). A failure here is not fatal: image and directory
# OCR still work, and the PDF branch below reports a clear error only when the
# input actually is a PDF. The next run retries the download.
if [[ ! -f "$bin_dir/pdf2png.exe" || ! -f "$bin_dir/pdfium.dll" ]]; then
    mkdir -p "$bin_dir"
    pdf_zip="${TEMP:-/tmp}/pdfium-skill-dl.zip"
    if download_file "$pdf_zip" "$skill_assets_url/$pdfium_asset" "${PDFIUM_URL_FALLBACK:-}" "$pdfium_asset"; then
        pdf_zip_posix="$(cygpath -u "$pdf_zip")" || exit 1
        # See the note above: tolerate unzip's non-fatal warning exit code and
        # judge success by the extracted files instead.
        unzip -oq "$pdf_zip_posix" -d "$bin_dir"
        rm -f "$pdf_zip_posix"
    fi
    if [[ ! -f "$bin_dir/pdf2png.exe" || ! -f "$bin_dir/pdfium.dll" ]]; then
        printf '%s\n' 'WARN: PDF 转换工具下载失败, 图片识别不受影响; 处理 PDF 前请重新运行以重试下载。' >&2
    fi
fi

download_model() {
    local name="$1" destination="$2"; shift 2
    mkdir -p "$destination"
    local filename
    for filename in "$@"; do
        [[ -f "$destination/$filename" ]] && continue
        printf '模型下载中: %s/%s\n' "$name" "$filename"
        download_file "$destination/$filename" "$ms_root/$name/$filename" "$hf_root/$name/$filename" "$filename" || return 1
    done
}
download_model "${det_name}_ov" "$det_dir" inference.xml inference.bin inference.yml inference_960.xml || exit 1
download_model "${rec_name}_ov" "$rec_dir" inference.xml inference.bin inference.yml inference_320.xml inference_480.xml inference_640.xml inference_800.xml inference_1280.xml || exit 1

pdf_pages_dir=''
if [[ ! -d "$input_path" && "${input_path,,}" == *.pdf ]]; then
    [[ -x "$pdf_tool_dir/pdf2png.exe" && -f "$pdf_tool_dir/pdfium.dll" ]] || {
        printf '%s\n' 'ERROR: PDF 转换工具未就绪 (下载失败或未完成)。请检查网络后重新运行, 会自动重试下载。' >&2
        exit 1
    }
    pdf_pages_dir="$(mktemp -d "${TMPDIR:-/tmp}/ocr_npu_pdf.XXXXXX")" || exit 1
    printf 'Rendering PDF to PNG pages (200 DPI)...\n'
    "$pdf_tool_dir/pdf2png.exe" \
        --input "$(cygpath -w "$input_path")" --output "$(cygpath -w "$pdf_pages_dir")" --dpi 200 || {
        rm -rf -- "$pdf_pages_dir"
        exit 1
    }
    find "$pdf_pages_dir" -maxdepth 1 -type f -name '*.png' -print -quit | grep -q . || {
        printf '%s\n' 'ERROR: PDF conversion produced no PNG pages.' >&2
        rm -rf -- "$pdf_pages_dir"
        exit 1
    }
    input_path="$pdf_pages_dir"
fi

output_dir="$(mktemp -d "${TMPDIR:-/tmp}/ocr_npu_skill_output.XXXXXX")" || exit 1
cleanup_output() {
    rm -rf -- "$output_dir"
    [[ -z "$pdf_pages_dir" ]] || rm -rf -- "$pdf_pages_dir"
}
trap cleanup_output EXIT
export PATH="$bin_dir:$PATH"
cd "$bin_dir" || exit 1
"$exe" ocr \
  "--input=$(cygpath -w "$input_path")" \
  "--text_detection_model_name=$det_name" \
  "--text_detection_model_dir=$(cygpath -w "$det_dir")" \
  "--text_recognition_model_name=$rec_name" \
  "--text_recognition_model_dir=$(cygpath -w "$rec_dir")" \
  "--device=$device" --text_recognition_batch_size=1 --text_rec_score_thresh=0.0 \
  "--save_path=$(cygpath -w "$output_dir")"
status=$?
if [[ $status -ne 0 && "$device" == npu ]]; then
    "$exe" ocr "--input=$(cygpath -w "$input_path")" \
      "--text_detection_model_name=$det_name" "--text_detection_model_dir=$(cygpath -w "$det_dir")" \
      "--text_recognition_model_name=$rec_name" "--text_recognition_model_dir=$(cygpath -w "$rec_dir")" \
      --device=cpu --text_recognition_batch_size=1 --text_rec_score_thresh=0.0 \
      "--save_path=$(cygpath -w "$output_dir")"
    status=$?
fi
[[ $status -eq 0 ]] && find "$output_dir" -type f -name '*.txt' -exec sed -e 's/\r$//' {} \;
exit $status

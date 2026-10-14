#!/usr/bin/env bash
# ocr-extractor-zh launcher (macOS / Linux).
#
# Purpose: find a usable Python 3.9+ and forward all arguments to the main script.
# Why: GUI-launched processes often do not inherit the shell PATH, so a hardcoded
#      "python3" fails on many user machines.
#
# NOTE: kept ASCII-only on purpose -- under a C/POSIX locale a UTF-8 message would
#       print as garbage. User-facing Chinese messages come from the Python scripts,
#       which are guaranteed to write UTF-8.
set -u

# 解析脚本自身所在目录：优先纯内建展开（不依赖外部 dirname ——
# 精简 PATH 或受限环境下 dirname 可能不存在，会让 HERE 变空、
# 报出 "Main script not found: <错误路径>" 这种极难懂的错）。
_SOURCE="${BASH_SOURCE[0]}"
HERE="${_SOURCE%/*}"
if [ "$HERE" = "$_SOURCE" ]; then
  HERE="."                      # 以裸文件名被调用（PATH 查找）时没有目录部分
fi
if command -v cd >/dev/null 2>&1 && [ "$HERE" != "$(pwd)" ]; then
  HERE="$(cd "$HERE" 2>/dev/null && pwd)" || HERE="${_SOURCE%/*}"
fi
MAIN="$HERE/scripts/ocr_cli.py"

if [ ! -f "$MAIN" ]; then
  echo "[ERROR] Main script not found: $MAIN" >&2
  exit 4
fi

export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

find_python() {
  local candidate
  for candidate in "${PYTHON:-}" python3 /usr/bin/python3 /usr/local/bin/python3; do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
        printf '%s' "$candidate"
        return 0
      fi
    fi
  done
  # App-bundled Python shipped with the desktop client
  for candidate in \
    "$HOME/.workbuddy/binaries/python/versions"/*/bin/python3 \
    "$HOME/Library/Application Support/WorkBuddy/binaries/python/versions"/*/bin/python3; do
    [ -x "$candidate" ] || continue
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

PY="$(find_python || true)"
if [ -z "$PY" ]; then
  cat >&2 <<'EOF'
[ERROR] Python 3.9 or newer was not found.

How to install:
  macOS   brew install python            (or the python.org installer)
  Linux   sudo apt install python3       (or sudo dnf install python3)

Already installed but not detected? Point at it explicitly:
  PYTHON=/full/path/to/python3 bash run.sh ...
EOF
  exit 3
fi

if [ "${DOC_MEDIA_SKILLS_DEBUG:-0}" = "1" ]; then
  echo "[debug] interpreter: $PY" >&2
fi

exec "$PY" "$MAIN" "$@"

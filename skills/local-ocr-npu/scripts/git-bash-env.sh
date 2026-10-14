#!/usr/bin/env bash

# Shared Git Bash bootstrap for local Python skills. This file is sourced by a
# skill's run.sh and deliberately invokes native Windows executables directly.
#
# Hardened build — see README.md "安全与合规说明" and THIRD-PARTY-NOTICES.md.
# The upstream revision of this helper also carried an unused
# `prepare_python_runtime()` routine that downloaded `uv.exe` from a
# third-party personal repository and then executed it. No entry point in this
# skill ever called it, so it has been removed to eliminate the
# download-and-execute supply-chain risk.

skill_fail() {
    printf 'ERROR: %s\n' "$1" >&2
    return 1
}

check_aipc() {
    local platform_script platform_script_win is_aipc
    platform_script="${skill_root:-}/bin/platform.ps1"
    if [[ -z "${skill_root:-}" || ! -f "$platform_script" ]]; then
        printf '%s\n' 'WARN: AIPC check script is unavailable; skipping AIPC check.'
        return 0
    fi

    platform_script_win="$(cygpath -w "$platform_script" 2>/dev/null)" || {
        printf '%s\n' 'WARN: CPU model query failed; skipping AIPC check.'
        return 0
    }
    is_aipc="$(powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$platform_script_win" --is-aipc 2>/dev/null)" || {
        printf '%s\n' 'WARN: CPU model query failed; skipping AIPC check.'
        return 0
    }
    is_aipc="$(printf '%s' "$is_aipc" | tr -d '[:space:]')"
    if [[ "$is_aipc" != '1' ]]; then
        printf '%s\n' 'This skill requires an Intel AIPC platform.'
        return 1
    fi
}

_read_info_string() {
    local info_json="$1" key="$2"
    sed -nE "s/^[[:space:]]*\"${key}\"[[:space:]]*:[[:space:]]*\"([^\"]+)\".*/\1/p" "$info_json" | head -n 1
}

# --- uv bootstrap ---------------------------------------------------------
# uv is never fetched from a third-party file host. Each helper below installs
# uv through an official channel and prints the path of the uv.exe it produced,
# or returns non-zero when that channel is unavailable. None of them put the new
# uv.exe on this shell's PATH, so each one resolves the file by path itself.
# Keep this chain identical to Step 1 of install-env.ps1.

_uv_find_winget_copy() {
    # winget's portable installer publishes a symlink under ...\WinGet\Links.
    # Prefer the real file under ...\WinGet\Packages so the shared copy is a
    # plain file: restricted hosts such as WorkBuddy reject symlinks.
    local local_appdata root hit
    local_appdata="${LOCALAPPDATA:-}"
    [[ -n "$local_appdata" ]] || return 1
    local_appdata="$(cygpath -u "$local_appdata")" || return 1
    for root in "$local_appdata/Microsoft/WinGet/Packages" "$local_appdata/Microsoft/WinGet/Links"; do
        [[ -d "$root" ]] || continue
        hit="$(find "$root" -maxdepth 5 -name 'uv.exe' -print -quit 2>/dev/null)"
        [[ -n "$hit" ]] && { printf '%s\n' "$hit"; return 0; }
    done
    return 1
}

_uv_install_with_pip() {
    # `pip install --user` leaves the host's system site-packages untouched and
    # works without administrator rights. Tsinghua mirror first, PyPI second --
    # the same order every other pip install in this file uses.
    local mirror="$1" python_exe pip_exe scripts_dir candidate installed index flag scheme
    local -a runner flag_sets attempt

    python_exe="$(command -v python.exe 2>/dev/null || command -v python 2>/dev/null || true)"
    if [[ -n "$python_exe" ]]; then
        runner=("$python_exe" -m pip)
    else
        pip_exe="$(command -v pip.exe 2>/dev/null || command -v pip 2>/dev/null || command -v pip3 2>/dev/null || true)"
        [[ -n "$pip_exe" ]] || return 1
        runner=("$pip_exe")
    fi

    # Everything these helpers print goes to stderr: the command substitution
    # in _bootstrap_uv must capture nothing but the resolved uv.exe path.
    printf '%s\n' 'Installing uv with pip...' >&2
    # pip refuses `--user` outright inside a virtual environment ("User
    # site-packages are not visible in this virtualenv"), and the python on a
    # host's PATH very often IS a venv. Pick the flag accordingly, and still
    # retry without it when pip was found without a python to interrogate.
    flag_sets=(--user '')
    if [[ -n "$python_exe" ]] && \
        "$python_exe" -c "import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)" 2>/dev/null; then
        flag_sets=('')
    fi

    installed=false
    for index in "$mirror" ''; do
        for flag in "${flag_sets[@]}"; do
            attempt=("${runner[@]}" install)
            [[ -n "$flag" ]] && attempt+=("$flag")
            attempt+=(--disable-pip-version-check uv)
            [[ -n "$index" ]] && attempt+=(--index-url "$index")
            if "${attempt[@]}" >&2; then installed=true; break; fi
        done
        [[ "$installed" == true ]] && break
    done
    [[ "$installed" == true ]] || return 1

    # The scripts directory pip installed into is not on PATH; ask Python for
    # both the per-user and the current-environment locations.
    if [[ -n "$python_exe" ]]; then
        for scheme in "sysconfig.get_path('scripts', scheme='nt_user')" "sysconfig.get_path('scripts')"; do
            scripts_dir="$("$python_exe" -c "import sysconfig; print($scheme)" 2>/dev/null || true)"
            [[ -n "$scripts_dir" ]] || continue
            candidate="$(cygpath -u "$scripts_dir" 2>/dev/null || true)/uv.exe"
            [[ -f "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
        done
    elif [[ -n "${pip_exe:-}" ]]; then
        candidate="$(dirname "$pip_exe")/uv.exe"
        [[ -f "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
    fi
    if [[ -n "${APPDATA:-}" ]]; then
        candidate="$(find "$(cygpath -u "$APPDATA")/Python" -maxdepth 3 -name 'uv.exe' -print -quit 2>/dev/null)"
        [[ -n "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
    fi
    return 1
}

_uv_install_with_winget() {
    command -v winget.exe >/dev/null 2>&1 || command -v winget >/dev/null 2>&1 || return 1
    printf '%s\n' 'Installing uv with winget...' >&2
    # The agreement flags are required for an unattended run; without them
    # winget waits for interactive confirmation and the skill appears to hang.
    winget install --id=astral-sh.uv -e --silent \
        --accept-source-agreements --accept-package-agreements >&2 || true
    _uv_find_winget_copy
}

_uv_install_with_astral_script() {
    # UV_INSTALL_DIR puts uv straight into the shared location; without it the
    # installer picks its own directory. UV_NO_MODIFY_PATH stops it from editing
    # the user's PATH environment variable behind their back.
    local install_dir="$1" install_dir_win candidate
    command -v powershell.exe >/dev/null 2>&1 || return 1
    install_dir_win="$(cygpath -w "$install_dir")" || return 1
    printf '%s\n' 'Installing uv with the official astral.sh installer...' >&2
    # PSModulePath is inherited from whatever launched this shell. When that is
    # PowerShell 7, Windows PowerShell 5.1 is pointed at PS7's module directory
    # and the installer dies on `Get-ExecutionPolicy` with "the module could not
    # be loaded". Clearing it makes 5.1 fall back to its own defaults.
    UV_INSTALL_DIR="$install_dir_win" UV_NO_MODIFY_PATH=1 PSModulePath= \
        powershell.exe -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" >&2 || true
    candidate="$install_dir/uv.exe"
    [[ -f "$candidate" ]] && { printf '%s\n' "$candidate"; return 0; }
    return 1
}

_uv_install_from_archive() {
    # Last resort: the pinned release archive published by Astral itself. The
    # caller owns (and removes) the scratch directory passed in.
    local work_dir="$1" archive archive_win hit
    local url='https://releases.astral.sh/github/uv/releases/download/0.12.14/uv-x86_64-pc-windows-msvc.zip'

    mkdir -p "$work_dir" || return 1
    archive="$work_dir/uv.zip"
    printf '%s\n' 'Downloading the uv release archive...' >&2
    if command -v curl.exe >/dev/null 2>&1; then
        archive_win="$(cygpath -w "$archive")" || return 1
        curl.exe -fL --ssl-no-revoke -o "$archive_win" "$url" >&2 || true
    fi
    if [[ ! -s "$archive" ]] && command -v curl >/dev/null 2>&1; then
        curl -fL -o "$archive" "$url" >&2 || true
    fi
    [[ -s "$archive" ]] || return 1

    unzip -oq "$archive" -d "$work_dir" >/dev/null 2>&1
    hit="$(find "$work_dir" -name 'uv.exe' -print -quit 2>/dev/null)"
    [[ -n "$hit" ]] || return 1
    printf '%s\n' "$hit"
}

_bootstrap_uv() {
    local shared_uv_dir="$1" uv_exe="$2" mirror_index="$3"
    local archive_dir found uv_temp status

    archive_dir="$shared_uv_dir/.uv-archive.$$"
    found="$(_uv_install_with_pip "$mirror_index" || true)"
    [[ -n "$found" ]] || found="$(_uv_install_with_winget || true)"
    [[ -n "$found" ]] || found="$(_uv_install_with_astral_script "$shared_uv_dir" || true)"
    [[ -n "$found" ]] || found="$(_uv_install_from_archive "$archive_dir" || true)"

    status=1
    if [[ -f "$uv_exe" ]]; then
        # The astral installer writes straight into the shared location.
        status=0
    elif [[ -n "$found" ]]; then
        # Copy through a private temporary file, then rename it into place. Two
        # skills can be launched at once on a fresh host; no caller may ever
        # observe a partially copied uv.exe.
        uv_temp="$uv_exe.partial.$$"
        if cp -f "$found" "$uv_temp" && mv -f "$uv_temp" "$uv_exe"; then
            status=0
        fi
        rm -f "$uv_temp"
    fi

    rm -rf -- "$archive_dir"
    if [[ $status -ne 0 ]]; then
        skill_fail 'Failed to install uv.exe; please check your network connection and try again.'
        return 1
    fi
}

prepare_python_runtime() {
    local skill_root="$1" info_json venv_name python_version user_profile temp_root temp_root_unix
    local user_root openvino_root shared_uv_dir uv_exe legacy_uv_exe venv_dir venv_python
    local requirements_file wheels_dir wheel_urls_file mirror_index path_uv requirements_hash existing_hash

    command -v cygpath >/dev/null 2>&1 || { skill_fail 'This entry point requires Git Bash for Windows.'; return 1; }
    info_json="$skill_root/info.json"
    [[ -f "$info_json" ]] || { skill_fail "info.json not found at $info_json"; return 1; }
    venv_name="$(_read_info_string "$info_json" venv_name)"
    python_version="$(_read_info_string "$info_json" python_version)"
    [[ -n "$venv_name" ]] || { skill_fail 'venv_name not found in info.json.'; return 1; }
    [[ -n "$python_version" ]] || python_version='3.11'

    # Match install-env.ps1: keep uv's cache under the OS temp directory so
    # restricted hosts do not intercept cache cleanup in %LOCALAPPDATA%.
    temp_root="${TEMP:-${TMP:-}}"
    [[ -n "$temp_root" ]] || { skill_fail 'TEMP and TMP are both unset.'; return 1; }
    temp_root_unix="$(cygpath -u "$temp_root")" || return 1
    export UV_CACHE_DIR="$(cygpath -w "$temp_root_unix/openvino-uv-cache")" || return 1

    user_profile="${USERPROFILE:-${HOME:-}}"
    [[ -n "$user_profile" ]] || { skill_fail 'USERPROFILE and HOME are both unset.'; return 1; }
    user_root="$(cygpath -u "$user_profile")"
    openvino_root="$user_root/.openvino"
    shared_uv_dir="$user_root/.local/bin"
    uv_exe="$shared_uv_dir/uv.exe"
    legacy_uv_exe="$skill_root/bin/uv.exe"
    venv_dir="$openvino_root/venv/$venv_name"
    venv_python="$venv_dir/Scripts/python.exe"
    requirements_file="$skill_root/requirements.txt"
    wheels_dir="$skill_root/wheels"
    wheel_urls_file="$skill_root/wheel-urls.txt"
    mirror_index='https://pypi.tuna.tsinghua.edu.cn/simple'

    if [[ ! -f "$uv_exe" ]]; then
        mkdir -p "$shared_uv_dir" || return 1
        if [[ -f "$legacy_uv_exe" ]]; then
            printf 'Migrating uv.exe to shared location: %s\n' "$uv_exe"
            cp -f "$legacy_uv_exe" "$uv_exe" || return 1
        else
            path_uv="$(command -v uv.exe 2>/dev/null || command -v uv 2>/dev/null || true)"
            if [[ -n "$path_uv" ]]; then
                cp -f "$path_uv" "$uv_exe" || return 1
            else
                # Keep one shared private copy for every skill under
                # %USERPROFILE%\.local\bin, always as a plain file.
                _bootstrap_uv "$shared_uv_dir" "$uv_exe" "$mirror_index" || return 1
            fi
        fi
    fi

    local venv_dir_win venv_python_win
    venv_dir_win="$(cygpath -w "$venv_dir")"
    venv_python_win="$(cygpath -w "$venv_python")"
    if [[ ! -f "$venv_python" ]]; then
        "$uv_exe" venv --clear --seed --python "$python_version" "$venv_dir_win" || return 1
    fi
    "$venv_python" -m pip --version >/dev/null 2>&1 || \
        "$uv_exe" pip install --python "$venv_python_win" pip --index-url "$mirror_index" || \
        "$uv_exe" pip install --python "$venv_python_win" pip || return 1

    if [[ -f "$requirements_file" ]]; then
        local requirements_sha_file requirements_file_win
        requirements_sha_file="$venv_dir/requirements.sha"
        requirements_file_win="$(cygpath -w "$requirements_file")"
        requirements_hash="$("$venv_python" -c \
            'import hashlib,pathlib,sys;print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest().upper())' \
            "$requirements_file_win")" || return 1
        existing_hash=''
        [[ -f "$requirements_sha_file" ]] && existing_hash="$(tr -d '[:space:]' < "$requirements_sha_file")"
        if [[ "$requirements_hash" != "$existing_hash" ]]; then
            local pip_args=(pip install --python "$venv_python_win" -r "$requirements_file_win")
            [[ -d "$wheels_dir" ]] && pip_args+=(--find-links "$(cygpath -w "$wheels_dir")")
            "$uv_exe" "${pip_args[@]}" --index-url "$mirror_index" || \
                "$uv_exe" "${pip_args[@]}" || return 1
            printf '%s\n' "$requirements_hash" > "$requirements_sha_file"
        fi
    fi

    if [[ -f "$wheel_urls_file" ]]; then
        mkdir -p "$wheels_dir" || return 1
        local wheel_url wheel_url_path wheel_name wheel wheel_win wheel_temp wheel_temp_win package_name normalized_package_name
        local wheel_hash wheel_sha_file installed_wheel_hash installed_version wheels_dir_win
        while IFS= read -r wheel_url || [[ -n "$wheel_url" ]]; do
            wheel_url="${wheel_url//$'\r'/}"
            wheel_url="$(printf '%s' "$wheel_url" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
            [[ -z "$wheel_url" || "$wheel_url" == \#* ]] && continue
            [[ "$wheel_url" == http://* || "$wheel_url" == https://* ]] || {
                skill_fail "Invalid wheel URL: $wheel_url"
                return 1
            }

            wheel_url_path="${wheel_url%%\?*}"
            wheel_name="${wheel_url_path##*/}"
            [[ "$wheel_name" == *.whl ]] || {
                skill_fail "Wheel URL does not end in .whl: $wheel_url"
                return 1
            }
            wheel="$wheels_dir/$wheel_name"
            if [[ ! -s "$wheel" ]]; then
                wheel_temp="$wheel.partial.$$"
                rm -f "$wheel_temp"
                printf 'Downloading %s with curl...\n' "$wheel_name"
                if command -v curl.exe >/dev/null 2>&1; then
                    wheel_temp_win="$(cygpath -w "$wheel_temp")" || return 1
                    curl.exe -fL --ssl-no-revoke --retry 3 --retry-delay 1 \
                        -o "$wheel_temp_win" "$wheel_url" || {
                        rm -f "$wheel_temp"
                        skill_fail "Failed to download $wheel_name."
                        return 1
                    }
                elif command -v curl >/dev/null 2>&1; then
                    curl -fL --retry 3 --retry-delay 1 -o "$wheel_temp" "$wheel_url" || {
                        rm -f "$wheel_temp"
                        skill_fail "Failed to download $wheel_name."
                        return 1
                    }
                else
                    skill_fail 'curl is required to download the special wheel.'
                    return 1
                fi
                [[ -s "$wheel_temp" ]] || {
                    rm -f "$wheel_temp"
                    skill_fail "Downloaded wheel is empty: $wheel_name"
                    return 1
                }
                mv -f "$wheel_temp" "$wheel" || return 1
            fi

            package_name="${wheel_name%%-*}"
            normalized_package_name="$(printf '%s' "$package_name" | tr '[:upper:]_' '[:lower:]-')"
            wheel_hash="$("$venv_python" -c \
                'import hashlib,pathlib,sys;print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest().upper())' \
                "$(cygpath -w "$wheel")")" || return 1
            wheel_sha_file="$venv_dir/managed-wheel-$normalized_package_name.sha"
            installed_wheel_hash=''
            [[ -f "$wheel_sha_file" ]] && installed_wheel_hash="$(tr -d '[:space:]' < "$wheel_sha_file")"
            installed_version="$("$venv_python" - "$normalized_package_name" 2>/dev/null <<'PY' || true
import importlib.metadata
import sys

try:
    print(importlib.metadata.version(sys.argv[1]))
except importlib.metadata.PackageNotFoundError:
    raise SystemExit(1)
PY
)"
            if [[ -n "$installed_version" && "$installed_wheel_hash" == "$wheel_hash" ]]; then
                printf '%s managed wheel is already installed. Skipping.\n' "$normalized_package_name"
                continue
            fi

            wheel_win="$(cygpath -w "$wheel")" || return 1
            wheels_dir_win="$(cygpath -w "$wheels_dir")" || return 1
            local managed_pip_args=(
                pip install --python "$venv_python_win" "$wheel_win"
                --reinstall-package "$normalized_package_name" --find-links "$wheels_dir_win"
            )
            "$uv_exe" "${managed_pip_args[@]}" --index-url "$mirror_index" || \
                "$uv_exe" "${managed_pip_args[@]}" || return 1
            printf '%s\n' "$wheel_hash" > "$wheel_sha_file"
        done < "$wheel_urls_file"
    fi

    if [[ -d "$wheels_dir" ]]; then
        local wheel wheel_win wheel_name package_name wheel_version
        shopt -s nullglob
        for wheel in "$wheels_dir"/*.whl; do
            wheel_name="$(basename "$wheel" .whl)"
            package_name="${wheel_name%%-*}"
            wheel_version="${wheel_name#*-}"
            wheel_version="${wheel_version%%-*}"
            if ! "$venv_python" - "$package_name" "$wheel_version" <<'PY'
import importlib.metadata
import re
import sys

normalize = lambda value: re.sub(r"[-_.]+", "-", value).lower()
installed = next(
    (dist.version for dist in importlib.metadata.distributions()
     if dist.metadata.get("Name") and normalize(dist.metadata["Name"]) == normalize(sys.argv[1])),
    None,
)
if installed is None:
    raise SystemExit(0)
try:
    from packaging.version import Version
except ImportError:
    from pip._vendor.packaging.version import Version
raise SystemExit(0 if Version(installed) < Version(sys.argv[2]) else 1)
PY
            then
                continue
            fi
            wheel_win="$(cygpath -w "$wheel")"
            "$uv_exe" pip install --python "$venv_python_win" "$wheel_win" --index-url "$mirror_index" || \
                "$uv_exe" pip install --python "$venv_python_win" "$wheel_win" || return 1
        done
        shopt -u nullglob
    fi

    VENV_PY="$venv_python"
    export VENV_PY
}

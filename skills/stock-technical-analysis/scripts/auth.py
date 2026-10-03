"""RFC 8628 Device Authorization 的幂等客户端。"""

import base64
import binascii
import hashlib
import json
import os
import stat
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

AUTH_BASE = os.environ.get("XGMF_AUTH_BASE", "https://app.abctougu.cn").rstrip("/")
CLIENT_ID = "xgmf-stock-skill"
SCOPE = "stock.read"
GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

EXIT_OK = 0
EXIT_NEED_USER = 10
EXIT_ERROR = 2

AUTH_OK = "ok"
AUTH_NEED_USER = "need_user"
AUTH_ERROR = "error"

QR_MAX_BYTES = 5 * 1024 * 1024
QR_SUFFIXES = (".png", ".jpg", ".gif", ".webp")
QR_LEGACY_NAMES = ("authorization_qr.svg", "authorization_qr.tmp.svg")


def _state_dir() -> Path:
    return Path.home() / ".xgmf-skills"


def _token_path() -> Path:
    return _state_dir() / "access_token"


def _pending_path() -> Path:
    return _state_dir() / "pending_device.json"


def _qr_paths() -> Tuple[Path, ...]:
    return tuple(_state_dir() / ("authorization_qr" + suffix) for suffix in QR_SUFFIXES)


def _qr_temp_path() -> Path:
    return _state_dir() / "authorization_qr.tmp"


def _qr_session_path() -> Path:
    return _state_dir() / "authorization_qr.session"


def _qr_session_temp_path() -> Path:
    return _state_dir() / "authorization_qr.session.tmp"


def _protect(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, NotImplementedError):
        pass


def read_token() -> Tuple[Optional[str], Optional[str]]:
    env_token = (os.environ.get("XGMF_ACCESS_TOKEN") or "").strip()
    if env_token:
        return env_token, "environment"
    path = _token_path()
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token, "file"
    return None, None


def _write_token(token: str) -> None:
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip() + "\n", encoding="utf-8")
    _protect(path)
    _clear_qr_files()


def _clear_qr_files() -> None:
    legacy_paths = tuple(_state_dir() / name for name in QR_LEGACY_NAMES)
    for path in (
        *_qr_paths(),
        _qr_temp_path(),
        _qr_session_path(),
        _qr_session_temp_path(),
        *legacy_paths,
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _ensure_qr_cache_cleared() -> None:
    _clear_qr_files()
    if any(path.exists() for path in (*_qr_paths(), _qr_session_path())):
        raise OSError("无法清理旧二维码缓存")


def _qr_cache_key(user_code: str) -> str:
    return hashlib.sha256(user_code.encode("utf-8")).hexdigest()


def _existing_qr_path(user_code: str) -> Optional[Path]:
    path = next((candidate for candidate in _qr_paths() if candidate.is_file()), None)
    if path is None:
        return None
    try:
        cached_key = _qr_session_path().read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        cached_key = ""
    if cached_key != _qr_cache_key(user_code):
        _clear_qr_files()
        return None
    return path


def _image_suffix(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("服务端返回的二维码不是受支持的图片格式")


def _decode_qr(value: Any) -> Tuple[bytes, str]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("服务端未返回微信二维码")
    encoded = value.strip()
    if encoded.startswith("data:"):
        header, separator, encoded = encoded.partition(",")
        if not separator or ";base64" not in header.lower():
            raise ValueError("服务端返回的二维码 Data URL 无效")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("服务端返回的二维码 Base64 无效") from error
    if not data or len(data) > QR_MAX_BYTES:
        raise ValueError("服务端返回的二维码大小无效")
    return data, _image_suffix(data)


def _write_qr(user_code: str) -> Path:
    cached = _existing_qr_path(user_code)
    if cached is not None:
        return cached.resolve()

    status, response = _get_json(
        "/oauth/device-authorizations/" + quote(user_code, safe=""),
    )
    if status != 200:
        raise RuntimeError(response.get("error_description") or f"获取微信二维码失败 HTTP {status}")
    if response.get("status") != "pending":
        raise RuntimeError("授权会话已完成或过期，请重新执行原请求")
    data, suffix = _decode_qr(response.get("qrcode"))

    path = _state_dir() / ("authorization_qr" + suffix)
    temp = _qr_temp_path()
    session_path = _qr_session_path()
    session_temp = _qr_session_temp_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_qr_cache_cleared()
    try:
        temp.write_bytes(data)
        _protect(temp)
        os.replace(temp, path)
        session_temp.write_text(_qr_cache_key(user_code) + "\n", encoding="ascii")
        _protect(session_temp)
        os.replace(session_temp, session_path)
    finally:
        for temporary in (temp, session_temp):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    _protect(path)
    _protect(session_path)
    return path.resolve()


def clear_file_credentials() -> None:
    for path in (_token_path(), _pending_path()):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    _clear_qr_files()


def _read_pending() -> Optional[Dict[str, Any]]:
    path = _pending_path()
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not value.get("deviceCode") or not value.get("userCode"):
            raise ValueError("invalid pending state")
        if int(value.get("expiresAt", 0)) <= int(time.time()):
            raise ValueError("expired pending state")
        return value
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        _clear_qr_files()
        return None


def _write_pending(value: Dict[str, Any]) -> None:
    path = _pending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    _protect(path)


def _post_form(path: str, form: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    request = Request(
        AUTH_BASE + path,
        data=urlencode(form).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, {"error": "http_error", "error_description": body[:300]}


def _get_json(path: str) -> Tuple[int, Dict[str, Any]]:
    request = Request(
        AUTH_BASE + path,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            return error.code, json.loads(body)
        except json.JSONDecodeError:
            return error.code, {"error": "http_error", "error_description": body[:300]}


def _create() -> Dict[str, Any]:
    _ensure_qr_cache_cleared()
    status, data = _post_form(
        "/oauth/device_authorization",
        {"client_id": CLIENT_ID, "scope": SCOPE},
    )
    if status != 200 or not data.get("device_code") or not data.get("user_code"):
        raise RuntimeError(data.get("error_description") or f"创建设备授权失败 HTTP {status}")
    now = int(time.time())
    interval = max(1, int(data.get("interval", 5)))
    pending = {
        "deviceCode": data["device_code"],
        "userCode": data["user_code"],
        "expiresAt": now + int(data.get("expires_in", 300)) - 5,
        "interval": interval,
        "nextPollAt": now + interval,
    }
    _write_pending(pending)
    return pending


def _poll(pending: Dict[str, Any]) -> Dict[str, Any]:
    status, data = _post_form(
        "/oauth/token",
        {
            "grant_type": GRANT_TYPE,
            "device_code": pending["deviceCode"],
            "client_id": CLIENT_ID,
        },
    )
    if status == 200 and data.get("access_token"):
        _write_token(data["access_token"])
        _pending_path().unlink(missing_ok=True)
        return {"status": AUTH_OK, "token": data["access_token"], "newly_obtained": True}

    error = data.get("error")
    if error in ("authorization_pending", "slow_down"):
        if error == "slow_down":
            pending["interval"] = int(pending.get("interval", 5)) + 5
        pending["nextPollAt"] = int(time.time()) + int(pending.get("interval", 5))
        _write_pending(pending)
        return _need_user(pending)
    if error in ("expired_token", "access_denied", "invalid_grant"):
        _pending_path().unlink(missing_ok=True)
        _clear_qr_files()
        return {"status": "restart"}
    return {
        "status": AUTH_ERROR,
        "message": data.get("error_description") or f"令牌兑换失败 HTTP {status}",
    }


def _need_user(pending: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "status": AUTH_NEED_USER,
        "user_code": pending.get("userCode", ""),
    }


def ensure_auth() -> Dict[str, Any]:
    token, source = read_token()
    if token:
        return {"status": AUTH_OK, "token": token, "source": source}

    pending = _read_pending()
    if pending is not None:
        if int(pending.get("nextPollAt", 0)) > int(time.time()):
            return _need_user(pending)
        try:
            result = _poll(pending)
        except (OSError, URLError, RuntimeError) as error:
            return {"status": AUTH_ERROR, "message": f"查询授权结果失败: {error}"}
        if result.get("status") != "restart":
            return result

    try:
        return _need_user(_create())
    except (OSError, URLError, RuntimeError) as error:
        return {"status": AUTH_ERROR, "message": f"创建设备授权失败: {error}"}


def print_auth_result(result: Dict[str, Any]) -> int:
    if result.get("status") == AUTH_OK:
        return EXIT_OK
    if result.get("status") == AUTH_NEED_USER:
        try:
            qr_path = _write_qr(result["user_code"])
        except (OSError, URLError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            print(f"错误: 生成授权二维码失败: {error}", file=sys.stderr)
            return EXIT_ERROR
        print("need_auth: true")
        print(f"qrMarkdown: ![微信授权二维码]({qr_path.as_posix()})")
        print("请使用微信扫描上方二维码，完成后重新发送原请求。")
        return EXIT_NEED_USER
    print(f"错误: {result.get('message', '授权失败')}", file=sys.stderr)
    return EXIT_ERROR


def main() -> int:
    return print_auth_result(ensure_auth())


if __name__ == "__main__":
    sys.exit(main())

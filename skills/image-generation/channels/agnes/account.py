"""Agnes 账号层：复刻官网「登录 / 找回密码(兼注册) / 建 Key」流程（仅标准库）。

官方接口（采集自官网真实流量 platform-backend.agnes-ai.cn）：
  - 发验证码(注册/找回共用): GET  {backend}/api/verification?email=&purpose=reset
  - 重置密码(新邮箱=建号):   POST {backend}/api/reset_password
                              {email, new_password, new_password_confirm, code}
  - 登录:                    POST {backend}/api/user/login        {username, password}
  - 建 Key:                  POST {backend}/api/token             {name, api_key_profile} (Bearer)
  - 列出现有 Key(用于复用):   GET  {backend}/api/token?key_profile= (Bearer)
  - 取 Key(对已有 Key 亦可):  POST {backend}/api/token/{id}/key    (Bearer)
  - 删除 Key:                DELETE {backend}/api/token/{id}       (Bearer)
  - 登出(尽力):              GET  {backend}/api/user/logout        (Bearer)

关键点（与官网一致）：
  - 官网对「新账号」与「已注册但密码错」走的是同一条链路：
    login(401) -> verification(reset) -> reset_password(建号/改密) -> login。
    因此本模块不区分两者，统一以 reset_password 处理，不存在独立的 register 接口。
  - 响应信封统一为 {code, message, data}，HTTP 状态码与 body 的 code 一致。
  - 账号域 platform-backend 与生图域 api 是两个独立服务，token 不通用。
"""
import common
from common import load_config
from core.httpx import http_json

# 官网请求头（采集自 platform.agnes-ai.cn 真实流量）
OFFICIAL_HEADERS = {"x-user-language": "zh-CN",
                    "referer": "https://platform.agnes-ai.cn/"}


def _b() -> str:
    return load_config().get("account", "backend",
                             fallback="https://platform-backend.agnes-ai.cn").rstrip("/")


def send_verification_code(email: str) -> None:
    """发送验证码（purpose=reset，注册/找回密码共用）。非 200 视为失败并抛错。"""
    url = f"{_b()}/api/verification?email={email}&purpose=reset"
    status, payload = http_json("GET", url, timeout=20,
                                       extra_headers=OFFICIAL_HEADERS)
    if status != 200:
        raise RuntimeError(f"发送验证码失败({status}): {common.errmsg(payload)}")


def reset_password(email, password, code) -> None:
    """重置密码；官网中该接口对新邮箱=建号、对老邮箱=改密。返回即成功。"""
    url = f"{_b()}/api/reset_password"
    body = {"email": email, "new_password": password,
            "new_password_confirm": password, "code": code}
    status, payload = http_json("POST", url, body=body, timeout=20,
                                       extra_headers=OFFICIAL_HEADERS)
    if status != 200:
        raise RuntimeError(f"重置/注册失败({status}): {common.errmsg(payload)}")


def login(email, password) -> str:
    """登录，成功返回 JWT 字符串。"""
    url = f"{_b()}/api/user/login"
    body = {"username": email, "password": password}
    status, payload = http_json("POST", url, body=body, timeout=20,
                                       extra_headers=OFFICIAL_HEADERS)
    if status != 200:
        raise RuntimeError(f"登录失败({status}): {common.errmsg(payload)}")
    return _jwt(payload)


def create_token(jwt: str) -> dict:
    url = f"{_b()}/api/token"
    name = load_config().get("account", "token_name", fallback="Agnes生图")
    profile = load_config().get("account", "token_profile", fallback="default")
    body = {"name": name, "api_key_profile": profile}
    status, payload = http_json("POST", url, body=body, token=jwt, timeout=20,
                                       extra_headers=OFFICIAL_HEADERS)
    if status != 200:
        raise RuntimeError(f"创建 Key 失败({status}): {common.errmsg(payload)}")
    return _data(payload)


def list_tokens(jwt: str, profile: str = None) -> list:
    """列出现有 Key（GET /api/token?key_profile=），失败返回 [] —— 列表失败不致命，交给上层新建。

    响应形如 {code,message,data:{total,items:[{id,name,key_profile,status,remain_quota,...}],...}}
    """
    try:
        profile = profile or load_config().get("account", "token_profile",
                                               fallback="default")
        url = f"{_b()}/api/token?key_profile={profile}"
        status, payload = http_json("GET", url, token=jwt, timeout=20,
                                           extra_headers=OFFICIAL_HEADERS)
        if status != 200:
            return []
        items = (_data(payload) or {}).get("items") or []
        return items if isinstance(items, list) else []
    except Exception:
        return []


def _pick_token(items: list, name: str) -> dict:
    """从列表挑一个可复用 Key：只认启用(status=1)的，优先同名，其次任意一个。"""
    alive = [t for t in items if isinstance(t, dict)
             and str(t.get("status", "1")) == "1" and t.get("id")]
    if not alive:
        return None
    for t in alive:                                   # 优先复用本工具自己建的（同名）
        if t.get("name") == name:
            return t
    return alive[0]                                   # 否则退而复用任意一个启用中的


def fetch_key(jwt: str, token_id) -> str:
    url = f"{_b()}/api/token/{token_id}/key"
    status, payload = http_json("POST", url, token=jwt, timeout=20,
                                       extra_headers=OFFICIAL_HEADERS)
    if status != 200:
        raise RuntimeError(f"获取 Key 失败({status}): {common.errmsg(payload)}")
    return _data(payload).get("key", "")


def logout(jwt: str) -> None:
    try:
        http_json("GET", f"{_b()}/api/user/logout", token=jwt, timeout=10,
                         extra_headers=OFFICIAL_HEADERS)
    except Exception:
        pass


def _finish_login(jwt: str) -> str:
    """拿到 JWT 后取 Key：**优先复用已有 Key**，没有才新建，最后登出并返回 Key。

    为什么要复用：官方对单账号有 max_keys 上限（采集到 default profile 为 20 个）。
    旧实现无条件 POST /api/token 新建，导致每登录一次就多一个 Key，很快堆到上限；
    而采集证据显示 `POST /api/token/{id}/key` 对**历史已存在的** Key 也能取回明文，
    因此可以直接沿用旧 Key，无需新建。列表/取 Key 失败时静默退回新建，不影响登录。
    """
    cfg = load_config()
    name = cfg.get("account", "token_name", fallback="Agnes生图")
    profile = cfg.get("account", "token_profile", fallback="default")
    if cfg.getboolean("account", "reuse_token", fallback=True):
        try:
            tok = _pick_token(list_tokens(jwt, profile), name)
            if tok:
                key = fetch_key(jwt, tok.get("id"))
                if key:
                    logout(jwt)
                    return key
        except Exception:
            pass  # 复用链路失败不致命，静默退回新建

    created = create_token(jwt)
    key = created.get("key") or fetch_key(jwt, created.get("id"))
    logout(jwt)
    if not key:
        raise RuntimeError("未取到 Key（响应中既无 key 也无 id）")
    return key


def _jwt(payload) -> str:
    try:
        return _data(payload)["access_token"]
    except Exception:
        raise RuntimeError(f"响应缺少 access_token: {payload}")


def _data(payload) -> dict:
    if isinstance(payload, dict):
        return payload.get("data", payload)
    return {}

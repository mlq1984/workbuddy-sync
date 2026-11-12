"""Agnes 凭证校验层（仅标准库）。

编排器架构下本层只负责一件事：validate_key —— 零成本鉴权探测（GET /v1/models）。
Key 的获取与落盘统一由编排器负责（core.store / core.credcenter）；
HTTP 执行走公共机制层 core.httpx。

仅标准库。
"""
from common import load_config
from core.httpx import http_json


def _base_url() -> str:
    return load_config().get("common", "base_url",
                             fallback="https://api.agnes-ai.cn/v1").rstrip("/")


def validate_key(api_key: str) -> bool:
    """零成本鉴权探测：GET /v1/models，200 即有效；网络异常按有效放行（由真实生图暴露错误）。"""
    if not api_key:
        return False
    status, _ = http_json("GET", f"{_base_url()}/models", token=api_key, timeout=20)
    if status == "ERR":
        return True
    return status == 200

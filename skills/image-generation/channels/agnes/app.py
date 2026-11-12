# -*- coding: utf-8 -*-
"""通道 · Agnes ai（auto 模式）。

本文件是通道与编排器之间的**唯一桥**：
- 暴露稳定契约；auto 模式额外提供 account_api（登录/发码/重置）代理官网账号流；
- 生图由本通道的 AgnesImageClient 完成，编排器(core) 永不调用 generate；
- 钥匙经 core.store 统一读写（不落 ~/.agnes/config.ini）。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import account
import credential
from client import AgnesImageClient
from core.credprovider import resolve as get_key   # 凭证提供层：用户Key优先→内置兜底

CHANNEL_ID = "agnes"
TITLE = "Agnes ai"
MODE = "auto"
ORDER = 2
DESCRIPTION = ("官方直连 · agnes-image 系列（2.5-flash 等）；"
               "限时免费不限量。"
               "支持文生图 + 图生图（编辑）+ 增强放大，画质 1K~4K 多档；"
               "获取可一键注册并创建 Key（自动回填、验证）。"
               "质量一般至高、色彩自然，出图快。")
MODELS = ("agnes-image-2.5-flash",)  # 可选模型（默认在前；spec.model 可指定）
ICON = "🤖"


def validate_key(key: str) -> dict:
    """零成本探活：GET /v1/models；200 有效，网络异常按有效放行。"""
    if not key:
        return {"valid": False, "message": "空 Key"}
    try:
        ok = credential.validate_key(key)
    except Exception as e:
        return {"valid": False, "message": "探测异常: %s" % e}
    return {"valid": bool(ok), "message": "有效" if ok else "无效"}


def acquire_key():
    """auto 模式：钥匙由账号流在通道页内获取并回填，此处返回 None。"""
    return None


def account_api(action: str, payload: dict) -> dict:
    """代理官网账号接口：发码 / 重置(注册) / 登录(取 Key)。"""
    try:
        if action == "code":
            account.send_verification_code(payload["email"])
            return {"ok": True}
        if action == "reset":
            account.reset_password(payload["email"], payload["password"], payload["code"])
            return {"ok": True}
        if action == "login":
            jwt = account.login(payload["email"], payload["password"])
            key = account._finish_login(jwt)
            return {"ok": True, "key": key}
    except Exception as e:
        return {"ok": False, "msg": str(e)}
    return {"ok": False, "msg": "未知操作: %s" % action}


# ---- 生成中心声明（references/architecture.md，可选契约：能力集 + 方言翻译）----
CAPS = {"i2i": True, "upscale": True, "n": False,   # 上游 400 强制 n=1，多张走扇出阶梯
        "tiers": ["1K", "2K", "3K", "4K"],
        "ratios": ["1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"],
        "concurrency": 2, "image_refs": 5}          # 官方「字符串或列表」多参考图（上限未载，按 5 防滥用）


def translate(clean: dict) -> dict:
    """通用 spec → 本通道 generate/upscale kwargs（纯映射，禁 IO；spec 字段见 core/params）。"""
    if clean["action"] == "upscale":
        kw = {"image": clean["image"], "scale": clean.get("scale", 2)}
        if clean.get("upscale_prompt"):
            kw["prompt"] = clean["upscale_prompt"]
        return kw
    kw = {"prompt": clean["prompt"]}
    if clean.get("image"):
        kw["image"] = clean["image"]          # 图生图（编辑）
    if clean.get("model"):
        kw["model"] = clean["model"]
    if clean.get("tier"):
        kw["size"] = clean["tier"]            # 档位式 size（1K~4K）
    if clean.get("ratio"):
        kw["ratio"] = clean["ratio"]          # 与档位式 size 配合
    if clean.get("n"):
        kw["n"] = clean["n"]                  # 服务端单请求多张
    return kw


def generate(prompt, **kw):
    """统一调用层透传：从统一仓库取 Key，交给通道客户端生图。"""
    key = get_key(CHANNEL_ID)
    if not key:
        raise RuntimeError("请先在通道管理台为「Agnes ai」获取 Key（登录/注册自动回填）。")
    client = AgnesImageClient(api_key=key)
    return client.generate(prompt, **kw)


SUPPORTS_UPSCALE = True


def upscale(image, scale=2, prompt=None, **kw):
    """放大(增强)：以源图作参考、目标分辨率调高后重绘放大，返回本地图片路径列表。"""
    key = get_key(CHANNEL_ID)
    if not key:
        raise RuntimeError("请先在通道管理台为「Agnes ai」获取 Key（登录/注册自动回填）。")
    client = AgnesImageClient(api_key=key)
    return client.upscale(image, scale=scale, prompt=prompt, **kw)

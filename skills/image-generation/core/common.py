# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 公共底座：日志、Bing 背景。

注意：本文件是**编排器自身**的 common，使用相对导入（from .xxx），
不占用顶层 `common` 名 —— 通道（Agnes）自带的 common 以顶层名存在，互不冲突。
凭证读写不在本层（唯一实现见 core.store）。
"""
import json
import logging
import os
import urllib.request

# 编排器根目录（core 的上级）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.ini")


def get_logger() -> logging.Logger:
    logger = logging.getLogger("orchestrator")
    if not logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
    return logger


# ---- Bing 每日壁纸（观感，失败退回 CSS 渐变） ----
def bing_bg() -> dict:
    try:
        api = "https://www.bing.com/HPImageArchive.aspx?format=js&idx=0&n=1&mkt=zh-CN"
        req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        urlbase = data["images"][0]["url"]
        full = urlbase if urlbase.startswith("http") else "https://www.bing.com" + urlbase
        return {"ok": True, "url": full}
    except Exception:
        return {"ok": False, "url": ""}


# 内置凭证层 master 分片 A（完整密钥 = A+C+B 三分片运行时拼接，见 core/builtin.py；
# 本常量只是派生材料之一，单独存在无任何意义）
_BUILTIN_KS_A = "b04207c3fff8c60f6102bfd6362fe01b1ee9b4ddd7da0f47"

# -*- coding: utf-8 -*-
"""公共媒体机制层：图生图输入归一化 / b64 落盘 / 统一产物目录 / 响应图片提取。

判定标准：与具体生图服务商无关的纯机制才放这里；端点、参数、模型、降级等策略归通道。
产物**平铺直存**产物根（v1.8.0，不再建通道子目录），命名 `{通道}_{YYYYMMDD}_{HHMMSS}_{毫秒}.{ext}`
（人类可读可解析）；产物根解析优先级：运行时关联 storage.json > config.ini > 桌面 > 旧路径，
任一来源与技能目录重叠即弃用（安全自愈）。作品登记簿（img.json）见 core/works.py。
"""
import base64
import binascii
import configparser
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse

logger = logging.getLogger("orchestrator")

# 存储锁：associate 迁移全程 与 save_output 落盘 互斥——
# 关闭"迁移扫描已过、文件落旧根"与"复制半成品"两个并发窗口
_STORAGE_LOCK = threading.RLock()

_ROOT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "config.ini")
_ASSOC_FILE = os.path.join(os.path.expanduser("~"), ".aipro", "storage.json")
_LEGACY_OUTPUT_ROOT = os.path.join(os.path.expanduser("~"), ".aipro", "output")
SKILL_ROOT = os.path.normpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WORKS_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _inside_or_eq(target: str, base: str) -> bool:
    """target 是否等于 base 或位于 base 内部（含盘符大小写归一）。"""
    t, b = os.path.normpath(target).lower(), os.path.normpath(base).lower()
    return t == b or t.startswith(b + os.sep)


def _safe_output_dir(d):
    """产物根安全校验：不得等于技能目录、位于技能内部或包含技能目录；不安全返回 None。"""
    if not d:
        return None
    if _inside_or_eq(d, SKILL_ROOT) or _inside_or_eq(SKILL_ROOT, d):
        logger.warning("忽略不安全的产物目录（与技能目录重叠）: %s", d)
        return None
    return d


def _configured_dir():
    """config.ini [result] dir 显式产物目录（无配置/解析失败返回 None）。"""
    try:
        cp = configparser.ConfigParser()
        cp.read(_ROOT_FILE, encoding="utf-8")
        d = str(cp.get("result", "dir") or "").strip()
        return os.path.expanduser(d) if d else None
    except Exception:
        return None


def _assoc_dir():
    """运行时关联目录（管理台「修改关联位置」写入 ~/.aipro/storage.json）；技能重叠自愈。"""
    try:
        with open(_ASSOC_FILE, encoding="utf-8") as f:
            d = str(json.load(f).get("dir") or "").strip()
        d = os.path.expanduser(d) if d else None
        return _safe_output_dir(d)
    except Exception:
        return None


def _save_assoc(d: str) -> None:
    os.makedirs(os.path.dirname(_ASSOC_FILE), exist_ok=True)
    tmp = _ASSOC_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"dir": d}, f, ensure_ascii=False)
    os.replace(tmp, _ASSOC_FILE)


def _desktop_dir():
    """桌面目录探测：OneDrive 重定向优先，其次 Desktop/桌面；均无返回 None。"""
    home = os.path.expanduser("~")
    for cand in ("OneDrive/Desktop", "OneDrive/桌面", "Desktop", "桌面"):
        d = os.path.normpath(os.path.join(home, cand))
        if os.path.isdir(d):
            return d
    return None


def _resolve_output_root() -> str:
    """解析优先级：运行时关联 storage.json > config.ini > 桌面 > 旧路径（references/architecture.md）。
    任一来源与技能目录重叠即弃用该来源（启动自愈）。"""
    d = _safe_output_dir(_assoc_dir())
    if d:
        return d
    d = _safe_output_dir(_configured_dir())
    if d:
        return d
    dk = _desktop_dir()
    if dk:
        return os.path.join(dk, "Ai公益生图Pro")
    return _LEGACY_OUTPUT_ROOT


OUTPUT_ROOT = _resolve_output_root()
logger.info("产物目录: %s", OUTPUT_ROOT)


# ---- 关联位置（运行时）----

def open_folder(dir_path: str = None) -> dict:
    """在系统文件管理器中打开目录（缺省=当前产物根；新窗口并取得前台焦点）。"""
    d = str(dir_path or "").strip()
    d = os.path.abspath(os.path.expanduser(d)) if d else OUTPUT_ROOT
    if not os.path.isdir(d):
        return {"ok": False, "msg": "目录不存在：" + d}
    try:
        if os.name == "nt":
            os.startfile(d)  # noqa: 仅 Windows
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
        else:
            subprocess.Popen(["xdg-open", d])
        return {"ok": True, "dir": d}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


_PICKING = False


def pick_folder() -> dict:
    """弹出原生目录选择框，仅返回所选路径（不落盘、不迁移——由调用方决定后续动作）。"""
    global _PICKING
    if _PICKING:
        return {"ok": False, "msg": "已有选择框打开"}
    _PICKING = True
    try:
        import queue
        q = queue.Queue()

        def ask():
            d = ""
            try:
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                d = filedialog.askdirectory(title="选择作品保存目录") or ""
                root.destroy()
            except Exception:
                d = ""
            q.put(d)

        threading.Thread(target=ask, daemon=True).start()
        d = q.get()
        return {"ok": True, "dir": d} if d else {"ok": False, "msg": "已取消"}
    finally:
        _PICKING = False


def associate(new_dir: str) -> dict:
    """关联新产物根：落盘偏好 → 旧根图片平移到新根（文件名不变，img.json 随迁）。

    新目录与旧根重叠/嵌套、或与技能目录相关，一律拒绝。
    返回含 mapping（旧路径→新路径），供编排层改写任务档案（jobs.rebase）。
    """
    global OUTPUT_ROOT
    d = os.path.normpath(os.path.abspath(os.path.expanduser(str(new_dir or "").strip())))
    if not d or d == os.sep:
        return {"ok": False, "msg": "目录无效"}
    if os.path.normpath(d) == os.path.normpath(OUTPUT_ROOT):
        return {"ok": False, "msg": "目录未变更"}
    if _inside_or_eq(d, SKILL_ROOT) or _inside_or_eq(SKILL_ROOT, d):
        return {"ok": False, "msg": "不能关联技能目录本身、其内部或其上级目录"}
    rr = os.path.normpath(OUTPUT_ROOT)
    if _inside_or_eq(d, rr) or _inside_or_eq(rr, d):
        return {"ok": False, "msg": "新目录不能与现有产物目录重叠"}
    try:                       # 先验证目录可建（盘符不存在/无权限等），通过后才落偏好
        os.makedirs(d, exist_ok=True)
    except OSError as e:
        return {"ok": False, "msg": "目录不可用：%s" % e}
    _save_assoc(d)
    old_root = OUTPUT_ROOT
    mapping = {}
    with _STORAGE_LOCK:                     # 迁移全程与 save_output 互斥（关闭并发窗口）
        OUTPUT_ROOT = d
        moved = copied = failed = 0
        if os.path.isdir(old_root):
            for dirpath, _dirs, files in os.walk(old_root):
                if _inside_or_eq(dirpath, SKILL_ROOT):   # 兜底：迁移永不触碰技能目录
                    continue
                for fn in files:
                    src = os.path.join(dirpath, fn)
                    dst = os.path.join(d, fn)
                    try:
                        os.replace(src, dst)
                        moved += 1
                    except OSError:
                        try:                                   # 文件被占用 → 复制，原件保留
                            shutil.copy2(src, dst)
                            copied += 1
                        except Exception:
                            failed += 1
                            continue
                    mapping[os.path.normpath(src)] = dst
        try:                       # 旧根已空则移除，桌面不留空壳
            if os.path.isdir(old_root) and not os.listdir(old_root):
                os.rmdir(old_root)
        except OSError:
            pass
    logger.info("产物目录已关联: %s（迁移 %d，复制 %d，失败 %d）", d, moved, copied, failed)
    return {"ok": True, "dir": d, "moved": moved, "copied": copied,
            "failed": failed, "mapping": mapping}

_MIME = {".png": "image/png", ".jpg": "image/jpeg",
         ".jpeg": "image/jpeg", ".webp": "image/webp"}


def to_data_uri(value: str) -> str:
    """图生图输入归一化：本地文件→Data URI；URL / Data URI 原样返回；其余报错。"""
    v = str(value).strip()
    if v.startswith(("http://", "https://", "data:")):
        return v
    if os.path.isfile(v):
        mime = _MIME.get(os.path.splitext(v)[1].lower(), "image/png")
        with open(v, "rb") as f:
            return "data:%s;base64,%s" % (mime, base64.b64encode(f.read()).decode())
    raise RuntimeError("参考图需为公网 URL、Data URI 或本地文件路径：%s" % v[:80])


def normalize_images(image):
    """图生图输入归一化（批量）：str→[str]；None→[]；元素经 to_data_uri。"""
    if image is None:
        return []
    items = image if isinstance(image, (list, tuple)) else [image]
    return [to_data_uri(v) for v in items if str(v).strip()]


# ---- 放大(增强)辅助：纯机制，与具体服务商无关 ----

def _read_bytes(value):
    """源图→原始字节：bytes / 本地文件 / Data URI / 公网 URL 均可。取不到返回 None。"""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        v = value.strip()
        if os.path.isfile(v):
            with open(v, "rb") as f:
                return f.read()
        if v.startswith("data:"):
            try:
                _, b = v.split(",", 1)
                return base64.b64decode(b)
            except Exception:
                return None
        if v.startswith(("http://", "https://")):
            try:
                from core.httpx import fetch_bytes
                return fetch_bytes(v)
            except Exception:
                return None
    return None


def image_dimensions(value):
    """读图尺寸 (w, h)；不支持的格式或读取失败返回 None。仅标准库（PNG/JPEG）。"""
    data = _read_bytes(value)
    if not data or len(data) < 24:
        return None
    # PNG
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            w = int.from_bytes(data[16:20], "big")
            h = int.from_bytes(data[20:24], "big")
            return (w, h)
        except Exception:
            return None
    # JPEG
    if data[:2] == b"\xff\xd8":
        i, n = 2, len(data)
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h = int.from_bytes(data[i + 5:i + 7], "big")
                w = int.from_bytes(data[i + 7:i + 9], "big")
                return (w, h)
            if marker in (0xD9, 0xDA):
                break
            seg_len = int.from_bytes(data[i + 2:i + 4], "big")
            if seg_len <= 0:
                break
            i += 2 + seg_len
        return None
    return None


def nearest_ratio(w, h, ratios):
    """从候选比例中选与 (w, h) 最接近者；无有效输入回退首个。"""
    if not w or not h or not ratios:
        return ratios[0] if ratios else "1:1"
    tgt = w / h
    best, best_diff = ratios[0], None
    for r in ratios:
        try:
            a, b = r.split(":")
            rr = int(a) / int(b)
        except Exception:
            continue
        d = abs(rr - tgt)
        if best_diff is None or d < best_diff:
            best_diff, best = d, r
    return best


def save_output(channel_id: str, data: bytes, ext: str = "png") -> str:
    """产物落盘：<产物根>/<通道>_<YYYYMMDD>_<HHMMSS>_<毫秒>.<ext>，返回绝对路径。

    v1.8.0 平铺直存产物根（不再建通道子目录），人类可读命名，毫秒防同秒碰撞。
    """
    with _STORAGE_LOCK:                     # 与 associate 迁移互斥：切换期间落盘等待，落新根
        os.makedirs(OUTPUT_ROOT, exist_ok=True)   # 首次使用/外部删除后自动重建
        t = time.localtime()
        name = "%s_%04d%02d%02d_%02d%02d%02d_%03d.%s" % (
            channel_id, t.tm_year, t.tm_mon, t.tm_mday,
            t.tm_hour, t.tm_min, t.tm_sec, int(time.time() * 1000) % 1000, ext)
        path = os.path.join(OUTPUT_ROOT, name)
        with open(path, "wb") as f:
            f.write(data)
    return path


def web_path(path: str):
    """本地产物路径 → /works/<file> 相对 URL；不在产物根内/非图片返回 None。"""
    try:
        real = os.path.realpath(str(path))
        root = os.path.realpath(OUTPUT_ROOT)
        if not _inside_or_eq(real, root) or os.path.normpath(real) == root:
            return None
        rel = os.path.relpath(real, root).replace("\\", "/")
        if not rel.lower().endswith(_WORKS_EXT):
            return None
        return "/works/" + urllib.parse.quote(rel)
    except Exception:
        return None


def resolve_web(url_path: str):
    """/works/<file> → 本地绝对路径（server 静态路由用）；白名单 + 防穿越。"""
    rel = urllib.parse.unquote(url_path[len("/works/"):])
    cand = os.path.realpath(os.path.join(OUTPUT_ROOT, rel.replace("/", os.sep)))
    root = os.path.realpath(OUTPUT_ROOT)
    if not _inside_or_eq(cand, root) or os.path.normpath(cand) == root:
        return None
    if not cand.lower().endswith(_WORKS_EXT) or not os.path.isfile(cand):
        return None
    return cand


def b64_to_file(b64: str, channel_id: str, ext: str = "png"):
    """Base64 → 落盘并返回路径；非标准 base64 原样返回（交由上层报错/透传）。"""
    try:
        raw = base64.b64decode(b64)
    except (binascii.Error, ValueError):
        return b64
    return save_output(channel_id, raw, ext)


def extract_images(payload, channel_id: str = None) -> list:
    """OpenAI 兼容响应的图片提取。覆盖三种形态，b64 自动落盘（需 channel_id）：
      1) data[].url / image_url / b64_json（OpenAI 同步）
      2) 顶层 url / b64_json（单图响应）
      3) candidates[].content.parts[].text（Gemini 形态，内容即图片 URL）
    什么都提取不到时返回 []（调用方决定继续轮询还是报错）。
    """
    out = []
    if isinstance(payload, dict):
        items = payload.get("data")
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    if it.get("url"):
                        out.append(it["url"])
                    elif it.get("image_url"):
                        out.append(it["image_url"])
                    elif it.get("b64_json"):
                        out.append(b64_to_file(it["b64_json"], channel_id)
                                   if channel_id else it["b64_json"])
        if not out:
            if payload.get("url"):
                out.append(payload["url"])
            elif payload.get("b64_json"):
                out.append(b64_to_file(payload["b64_json"], channel_id)
                           if channel_id else payload["b64_json"])
        if not out:
            for c in payload.get("candidates", []) or []:
                content = c.get("content", {}) if isinstance(c, dict) else {}
                for p in content.get("parts", []) or []:
                    if isinstance(p, dict) and p.get("text"):
                        out.append(p["text"])
    return out


def _suffix_ext(s: str) -> str:
    """从 URL/路径推断图片扩展名；无法识别时回退 png。"""
    p = s.split("?")[0].split("#")[0]
    ext = os.path.splitext(p)[1].lower().strip(".")
    return ext if ext in ("png", "jpg", "jpeg", "webp", "gif") else "png"


def resolve_local(items, channel_id: str, ext: str = None) -> list:
    """把生成结果（URL / Data URI / 本地路径）统一落盘为本地文件，返回本地路径列表。

    用途：让调用方直接预览 —— 无论服务端返回 URL 还是 b64，
    都下载/解码到产物根（见模块头，平铺直存）并返回绝对路径；
    已是本地路径的原样返回。下载失败退化为原值，不抛异常。
    """
    if not isinstance(items, (list, tuple)):
        items = [items]
    out = []
    for it in items:
        if not isinstance(it, str) or not it.strip():
            if it is not None:
                out.append(it)
            continue
        s = it.strip()
        if os.path.isfile(s):
            out.append(s)
            continue
        if s.startswith("data:"):
            try:
                head, b = s.split(",", 1)
                m = re.match(r"data:image/([a-zA-Z0-9.+-]+)", head)
                e = (m.group(1) if m else "png").lower()
                e = "jpg" if e in ("jpeg", "jpg") else e
                out.append(b64_to_file(b, channel_id, e))
            except Exception:
                out.append(s)
            continue
        if s.startswith(("http://", "https://")):
            try:
                from core.httpx import fetch_bytes
                e = _suffix_ext(s) if ext is None else ext
                out.append(save_output(channel_id, fetch_bytes(s), e))
            except Exception:
                out.append(s)
            continue
        out.append(s)
    return out

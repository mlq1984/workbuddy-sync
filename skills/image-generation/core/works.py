# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 结果中心 · 作品登记簿（img.json = 作品资产单一真相源）。
设计见 references/architecture.md 索引 v1.8.0 条目（作品资产模型重构）。

- 关联根下所有"我们的图片"（命名 {通道}_{YYYYMMDD}_{HHMMSS}_{毫秒}.{ext}）都登记于此；
- list_works() = 目录扫描 ⊕ 登记簿联接：未登记但命名可解析 → 按名补登记（提示词留空）；
  登记指向已消失文件 → 自愈清除；命名不可解析的外来图 → 不登记也不显示；
- 删除 = 删文件 + 删登记（remove_file）。
"""
import json
import logging
import os
import re
import threading

from . import media

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_FILE_RE = re.compile(r"^(?P<ch>[^_]+)_(?P<d>\d{8})_(?P<t>\d{6})_(?P<ms>\d{3})\."
                      r"(?P<ext>png|jpg|jpeg|webp|gif)$", re.I)


def _works_file() -> str:
    return os.path.join(media.OUTPUT_ROOT, "img.json")


def _load() -> dict:
    """登记簿 → {文件名: {channel, time, prompt, job, params}}；损坏视为空。"""
    try:
        with open(_works_file(), encoding="utf-8") as f:
            data = json.loads(f.read())
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("作品登记簿读取失败：%s", _works_file())
        return {}


def _save(reg: dict) -> None:
    os.makedirs(media.OUTPUT_ROOT, exist_ok=True)   # 登记簿随产物根创建
    tmp = _works_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _works_file())


def _parse_name(filename: str):
    """{通道}_{YYYYMMDD}_{HHMMSS}_{毫秒}.{ext} → (channel, "YYYY/MM/DD HH:MM:SS")；不可解析 None。"""
    m = _FILE_RE.match(os.path.basename(filename))
    if not m:
        return None
    d, t = m.group("d"), m.group("t")
    return m.group("ch"), "%s/%s/%s %s:%s:%s" % (d[:4], d[4:6], d[6:8],
                                                 t[:2], t[2:4], t[4:6])


def register(paths: list, channel: str, prompt: str = "", job: str = "",
             params: dict = None) -> None:
    """生成完成后登记作品（executor 调用；路径已由 save_output 以标准命名落盘）。

    params = 该通道实际生效的生图参数（core/params.py: effective），与 prompt 同属作品资产。
    """
    with _LOCK:
        reg = _load()
        for p in paths or []:
            fn = os.path.basename(p)
            parsed = _parse_name(fn)
            if parsed:
                ch, tm = parsed
                reg[fn] = {"channel": channel or ch, "time": tm,
                           "prompt": prompt or "", "job": job or "",
                           "params": params or {}}
        _save(reg)


def remove_file(filename: str) -> dict:
    """删除作品：删文件 + 删登记。"""
    fn = os.path.basename(filename)
    path = os.path.realpath(os.path.join(media.OUTPUT_ROOT, fn))
    root = os.path.realpath(media.OUTPUT_ROOT)
    if not media._inside_or_eq(path, root) or not os.path.isfile(path):
        return {"ok": False, "msg": "not found"}
    try:
        os.remove(path)
    except OSError as e:
        return {"ok": False, "msg": str(e)}
    with _LOCK:
        reg = _load()
        reg.pop(fn, None)
        _save(reg)
    return {"ok": True}


def scan_join() -> list:
    """扫描产物根 ⊕ 登记簿 → 作品中心数据（新→旧）。

    - 已登记 → 全字段（channel/time/prompt/params/job）；
    - 未登记但命名可解析 → 按名补登记（channel/time，prompt 与 params 空）；
    - 命名不可解析的外来图 → 不登记不显示；
    - 登记指向已消失文件 → 自愈清除。
    """
    with _LOCK:
        root = media.OUTPUT_ROOT
        reg = _load()
        try:
            files = {f for f in os.listdir(root)
                     if f.lower().endswith(media._WORKS_EXT) and f != "img.json"}
        except FileNotFoundError:
            files = set()          # 产物根尚未创建（首次使用）→ 视为空
        changed = False
        for fn in list(reg):
            if fn not in files:                  # 登记指向已消失文件 → 自愈清除
                reg.pop(fn); changed = True
        for fn in files - set(reg):              # 未登记但可解析 → 按名补登记
            parsed = _parse_name(fn)
            if parsed:
                ch, tm = parsed
                reg[fn] = {"channel": ch, "time": tm, "prompt": "", "job": "",
                           "params": {}}
                changed = True
        if changed:
            _save(reg)
    out = []
    for fn, rec in sorted(reg.items(), key=lambda kv: kv[1].get("time", ""), reverse=True):
        full = os.path.join(media.OUTPUT_ROOT, fn)
        if not os.path.isfile(full):
            continue
        w = media.web_path(full)
        if w:
            out.append({"file": fn, "web": w, "channel": rec.get("channel", ""),
                        "time": rec.get("time", ""), "prompt": rec.get("prompt", ""),
                        "params": rec.get("params") or {}, "job": rec.get("job", "")})
    return out


def snapshot() -> dict:
    """目录+登记簿指纹（监控线程用）：文件名→mtime。"""
    snap = {}
    try:
        for f in os.listdir(media.OUTPUT_ROOT):
            if f.lower().endswith(media._WORKS_EXT):
                snap[f] = os.path.getmtime(os.path.join(media.OUTPUT_ROOT, f))
    except FileNotFoundError:
        pass
    return snap

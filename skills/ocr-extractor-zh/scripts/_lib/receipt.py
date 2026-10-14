"""统一回执：三个技能的命令行输出用同一套结构。

为什么统一：模型/用户读回执来判断「到底发生了什么」。若每个命令自己拼字符串，
就无法机器判读，也无法在测试里断言。所有命令都支持 ``--format json``。

退出码约定（跨技能一致）：
  0  成功
  1  运行时失败（转换报错、识别无结果等）
  2  参数错误
  3  缺少外部依赖（会同时给出该平台的安装指引）
  4  输入不可读 / 格式无法识别
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_MISSING_DEP = 3
EXIT_BAD_INPUT = 4


class Receipt:
    def __init__(self, action, status="ok"):
        # type: (str, str) -> None
        self.action = action
        self.status = status
        self.inputs = []          # type: List[dict]
        self.params = {}          # type: Dict[str, Any]
        self.engine = {}          # type: Dict[str, Any]
        self.outputs = []         # type: List[dict]
        self.warnings = []        # type: List[str]
        self.errors = []          # type: List[str]
        self.notes = []           # type: List[str]
        self.defaults_used = []   # type: List[str]
        self.data = {}            # type: Dict[str, Any]

    # ---- 链式填充 ----
    def add_input(self, path, **extra):
        # type: (str, **Any) -> Receipt
        item = {"path": path}
        item.update(extra)
        self.inputs.append(item)
        return self

    def add_output(self, path, kind=None, **extra):
        # type: (str, Optional[str], **Any) -> Receipt
        item = {"path": path}
        if kind:
            item["kind"] = kind
        item.update(extra)
        self.outputs.append(item)
        return self

    def warn(self, message):
        # type: (str) -> Receipt
        self.warnings.append(message)
        return self

    def note(self, message):
        # type: (str) -> Receipt
        self.notes.append(message)
        return self

    def fail(self, message):
        # type: (str) -> Receipt
        self.errors.append(message)
        self.status = "failed"
        return self

    def use_default(self, message):
        # type: (str) -> Receipt
        """记录「本次用了默认参数」——用户必须看得见，不能悄悄替用户决定。"""
        self.defaults_used.append(message)
        return self

    # ---- 序列化 ----
    def as_dict(self):
        # type: () -> dict
        out = {"status": self.status, "action": self.action}  # type: Dict[str, Any]
        if self.engine:
            out["engine"] = self.engine
        if self.inputs:
            out["inputs"] = self.inputs
        if self.params:
            out["params"] = self.params
        if self.defaults_used:
            out["defaultsUsed"] = self.defaults_used
        if self.outputs:
            out["outputs"] = self.outputs
        if self.notes:
            out["notes"] = self.notes
        if self.warnings:
            out["warnings"] = self.warnings
        if self.errors:
            out["errors"] = self.errors
        if self.data:
            out["data"] = self.data
        return out

    def to_json(self):
        # type: () -> str
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2, sort_keys=False)

    def to_text(self):
        # type: () -> str
        """人类可读版：先结论、再产物路径、后警告。"""
        lines = []  # type: List[str]
        head = {"ok": "✅ 完成", "failed": "❌ 失败", "partial": "⚠️ 部分完成"}.get(self.status, self.status)
        lines.append("%s  %s" % (head, self.action))

        for item in self.inputs:
            lines.append("  输入：%s" % item.get("path", ""))
        for key in sorted(self.params):
            lines.append("  参数·%s：%s" % (key, self.params[key]))
        for message in self.defaults_used:
            lines.append("  默认：%s" % message)
        if self.engine:
            engine_name = self.engine.get("name", "")
            extra = self.engine.get("version") or self.engine.get("reason") or ""
            lines.append("  引擎：%s%s" % (engine_name, ("（%s）" % extra) if extra else ""))
        for item in self.outputs:
            size = item.get("bytes")
            suffix = "（%.1f KB）" % (size / 1024.0) if isinstance(size, int) else ""
            lines.append("  产物：%s%s" % (item.get("path", ""), suffix))
        for message in self.notes:
            lines.append("  说明：%s" % message)
        for message in self.warnings:
            lines.append("  ⚠️  %s" % message)
        for message in self.errors:
            lines.append("  ❌ %s" % message)
        return "\n".join(lines)


def emit(receipt, fmt="text", stream=None):
    # type: (Receipt, str, Optional[Any]) -> int
    """按格式打印回执并返回退出码。"""
    stream = stream or sys.stdout
    if fmt == "json":
        stream.write(receipt.to_json() + "\n")
    else:
        stream.write(receipt.to_text() + "\n")
    if receipt.status == "ok":
        return EXIT_OK
    if receipt.status == "partial":
        return EXIT_OK
    return EXIT_FAILED


def emit_missing_dependency(receipt, tool_key, hint, fmt="text"):
    # type: (Receipt, str, str, str) -> int
    """缺外部依赖的统一出口：退出码 3 + 平台安装指引。"""
    receipt.fail("缺少外部依赖：%s" % tool_key)
    receipt.note("安装方式：%s" % hint)
    if fmt == "json":
        receipt.data.setdefault("missingTool", tool_key)
        receipt.data.setdefault("installHint", hint)
    return emit(receipt, fmt=fmt)


def human_size(num_bytes):
    # type: (Optional[int]) -> str
    if not num_bytes:
        return ""
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return "%.1f %s" % (size, unit)
        size /= 1024.0
    return "%d B" % num_bytes

#!/usr/bin/env python3
"""OCR CLI：调用系统 OCR（macOS Vision / Windows WinRT）或 Tesseract，输出可复制的结果。

用法示例：
    python3 ocr_cli.py run 发票.png                       # 自动选引擎，输出 md
    python3 ocr_cli.py run 发票.png --format html          # 可交互 HTML（单文件、可复制）
    python3 ocr_cli.py run 合同.pdf --lang zh-Hans,en-US
    python3 ocr_cli.py run 截图.png --engine tesseract --psm 6
    python3 ocr_cli.py engines                             # 这台机器有哪些 OCR 引擎
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (os.path.join(os.path.dirname(_HERE), "shared"), os.path.join(_HERE, "_lib")):
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.append(_candidate)

# 让 stdout/stderr 走 UTF-8：Windows 管道场景下 Python 默认用 ANSI 代码页，
# 输出中文/箭头会抛 UnicodeEncodeError（实测让 CI 整条流水线在该步就中断）。
for _candidate in (os.path.join(os.path.dirname(_HERE), "shared"), os.path.join(_HERE, "_lib")):
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.append(_candidate)
try:
    from console import force_utf8_streams

    force_utf8_streams()
except Exception:  # 兜底模块不可用时不能阻塞主流程
    pass

import ocr  # noqa: E402
import render  # noqa: E402
from platform_tools import current_platform  # noqa: E402
from receipt import EXIT_BAD_INPUT, EXIT_MISSING_DEP, EXIT_OK, EXIT_USAGE, Receipt, emit  # noqa: E402


def build_parser():
    # type: () -> argparse.ArgumentParser
    parser = argparse.ArgumentParser(prog="ocr", description="系统 OCR / tesseract 文字识别")
    fmt_parent = argparse.ArgumentParser(add_help=False)
    fmt_parent.add_argument("--format", dest="output_format", choices=["text", "json"],
                            default=argparse.SUPPRESS, help="控制台回执格式（默认 text）")
    parser.add_argument("--format", dest="output_format", choices=["text", "json"], default="text")
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="识别图片/PDF 文字", parents=[fmt_parent])
    run.add_argument("source", help="图片路径（png/jpg/tiff/bmp/webp/gif）或 PDF")
    run.add_argument("--engine", default="auto", choices=["auto", "vision", "winrt", "tesseract"],
                     help="识别引擎（默认 auto：macOS→Vision，Windows→WinRT，其它→tesseract）")
    run.add_argument("--lang", default=None,
                     help="语言，逗号分隔，如 zh-Hans,en-US；tesseract 会自动映射成 chi_sim+eng")
    run.add_argument("--out", help="结果文件路径（默认同目录同名 .md / .html）")
    run.add_argument("--to", default="md", choices=["md", "html", "txt", "json"],
                     help="结果文件格式（默认 md）")
    run.add_argument("--title", help="结果标题")
    run.add_argument("--psm", help="tesseract 版面模式（默认 3=全自动；6=单块文本）")
    run.add_argument("--tesseract", help="显式指定 tesseract 可执行文件路径")
    run.add_argument("--no-embed", action="store_true", help="HTML 不内联图片（默认内联，保证单文件）")
    run.add_argument("--print", dest="print_text", action="store_true", help="同时把识别文本打到标准输出")
    run.add_argument("--no-file", action="store_true", help="只打印，不写结果文件")

    subparsers.add_parser("engines", help="列出本机可用的 OCR 引擎与语言", parents=[fmt_parent])
    return parser


def cmd_run(args):
    # type: (argparse.Namespace) -> int
    receipt = Receipt("ocr")
    if not os.path.isfile(args.source):
        receipt.fail("文件不存在：%s" % args.source)
        emit(receipt, fmt=args.output_format)
        return EXIT_BAD_INPUT

    try:
        result = ocr.recognize(
            args.source, engine=args.engine, languages=args.lang,
            tesseract_path=args.tesseract, psm=args.psm,
        )
    except ocr.OcrError as exc:
        if exc.missing_tool:
            from platform_tools import find_tool

            hint = find_tool(exc.missing_tool).install_hint()
            receipt.fail(str(exc))
            if hint:
                receipt.note("安装方式：%s" % hint)
            receipt.data["missingTool"] = exc.missing_tool
            emit(receipt, fmt=args.output_format)
            return EXIT_MISSING_DEP
        receipt.fail(str(exc))
        emit(receipt, fmt=args.output_format)
        return EXIT_BAD_INPUT

    receipt.add_input(os.path.abspath(args.source))
    receipt.engine = {
        "name": result.engine,
        "language": result.language or "自动",
    }
    if result.meta:
        receipt.engine.update({k: v for k, v in result.meta.items() if v})
    average = result.average_confidence
    receipt.data["lineCount"] = len(result.lines)
    if average is not None:
        receipt.data["averageConfidence"] = round(average, 4)

    # 引擎降级/空结果必须写进回执（用户要能看见"试过什么、为什么换引擎"）
    if result.meta.get("fallbackNote"):
        receipt.note(result.meta["fallbackNote"])
    if result.meta.get("emptyNote"):
        receipt.note(result.meta["emptyNote"])

    uncertain = [line for line in result.lines if line.uncertain]
    probability_scale = result.meta.get("confidenceSemantics") is None
    if not probability_scale:
        # 引擎不给概率型置信度（如 Vision）→ 不要把「候选差异度」当百分比播报
        receipt.engine["confidenceSemantics"] = result.meta.get("confidenceSemantics")
        receipt.data.pop("averageConfidence", None)
    if not result.lines:
        receipt.warn("没有识别到任何文字：可能是纯图形图片、分辨率过低，或语言包不匹配")
    elif probability_scale and average is not None and average < render.LOW_CONFIDENCE:
        receipt.warn("平均置信度偏低（%.0f%%），建议人工核对或提高图片清晰度" % (average * 100))
    if uncertain:
        if probability_scale:
            receipt.note("有 %d 行置信度低于 %.0f%%，已在结果中标注"
                         % (len(uncertain), render.LOW_CONFIDENCE * 100))
        else:
            receipt.note("有 %d 行识别不确定（引擎给出了不同的次选结果），已在结果中标注并附次选文本"
                         % len(uncertain))
    if result.meta.get("confidenceNote"):
        receipt.note(result.meta["confidenceNote"])

    # 写结果文件
    if not args.no_file:
        output = args.out or _default_output(args.source, args.to)
        content = _render_content(result, args, output)
        with open(output, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        receipt.add_output(os.path.abspath(output), kind=args.to, bytes=os.path.getsize(output))

    if args.print_text or args.no_file:
        receipt.note("识别文本见下方 data.text（--format json 时完整返回）")
        receipt.data["text"] = result.text

    emit(receipt, fmt=args.output_format)
    if args.print_text and args.output_format == "text":
        sys.stdout.write("\n----- 识别文本 -----\n%s\n" % result.text)
    return EXIT_OK


def _default_output(source, target):
    # type: (str, str) -> str
    base, _ = os.path.splitext(source)
    return "%s-ocr.%s" % (base, target)


def _render_content(result, args, output):
    # type: (object, argparse.Namespace, str) -> str
    if args.to == "md":
        return render.to_markdown(result, source_path=args.source, title=args.title)
    if args.to == "html":
        return render.to_html(result, source_path=args.source, title=args.title,
                              embed_image=not args.no_embed)
    if args.to == "txt":
        return render.to_text(result)
    if args.to == "json":
        import json

        return json.dumps(result.as_dict(), ensure_ascii=False, indent=2) + "\n"
    raise ValueError("未知输出格式：%s" % args.to)


def cmd_engines(args):
    # type: (argparse.Namespace) -> int
    report = ocr.available_engines()
    platform = current_platform()
    if args.output_format == "json":
        import json

        print(json.dumps({"platform": platform, "engines": report,
                          "default": ocr.auto_engine()}, ensure_ascii=False, indent=2))
        return EXIT_OK

    print("平台：%s" % platform)
    for name in ("vision", "winrt", "tesseract"):
        info = report[name]
        mark = "✅" if info["available"] else "❌"
        print("%s %-10s %s" % (mark, name, info["label"]))
        if info.get("path"):
            print("             路径：%s" % info["path"])
        if info.get("version"):
            print("             版本：%s" % info["version"])
        languages = info.get("languages") or []
        if languages:
            preview = "、".join(languages[:12])
            if len(languages) > 12:
                preview += " …（共 %d 个）" % len(languages)
            print("             语言：%s" % preview)
        elif info["available"]:
            print("             语言：未检测到已安装的语言包")
        if info.get("detail"):
            print("             详情：%s" % info["detail"])
        if not info["available"] and info.get("install"):
            for platform_name, hint in info["install"].items():
                print("             %-7s %s" % (platform_name, hint))
    print("")
    print("默认引擎：%s" % ocr.auto_engine())
    return EXIT_OK


def main(argv=None):
    # type: (object) -> int
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    if args.command == "run":
        return cmd_run(args)
    if args.command == "engines":
        return cmd_engines(args)
    parser.print_help()
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())

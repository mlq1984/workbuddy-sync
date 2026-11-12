#!/usr/bin/env python
"""batch_plan.py - 把批量清单 CSV 校验并展开为执行计划 JSON。

用法:
    python batch_plan.py <batch.csv> [--config <config.json>] [-o plan.json]

清单列: id,prompt,size,quality,style,ref_image (见 assets/batch-template.csv)
输出: 执行计划 JSON（含默认参数补全与积分预估），供 AI 逐条调用 ImageGen。
仅做计划，不调用任何生成接口。
"""
import argparse
import csv
import json
import sys
from pathlib import Path

VALID_SIZES = {"1024x1024", "1024x1536", "1536x1024"}
VALID_QUALITY = {"low", "medium", "high"}
CREDIT_LOW, CREDIT_HIGH = 5, 10  # 单张积分区间


def load_config(path: str | None) -> dict:
    if not path or not Path(path).exists():
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"警告: 配置文件解析失败({e})，忽略配置", file=sys.stderr)
        return {}


def load_batch(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("错误: 清单为空")
    if "prompt" not in rows[0]:
        raise SystemExit("错误: 清单缺少必填列 prompt")
    return rows


def build_plan(rows: list[dict], cfg: dict) -> dict:
    default_size = cfg.get("default_size", "1024x1024")
    default_quality = cfg.get("default_quality", "high")
    default_style = cfg.get("default_style", "")
    output_dir = cfg.get("output_dir", "ai绘画输出")

    tasks, errors = [], []
    for i, r in enumerate(rows, 1):
        tid = (r.get("id") or "").strip() or f"{i:03d}"
        prompt = (r.get("prompt") or "").strip()
        if not prompt:
            errors.append(f"[{tid}] prompt 为空，已跳过")
            continue
        size = (r.get("size") or "").strip() or default_size
        quality = (r.get("quality") or "").strip() or default_quality
        style = (r.get("style") or "").strip() or default_style
        ref = (r.get("ref_image") or "").strip()

        if size not in VALID_SIZES:
            errors.append(f"[{tid}] size 非法({size})，改用 {default_size}")
            size = default_size
        if quality not in VALID_QUALITY:
            errors.append(f"[{tid}] quality 非法({quality})，改用 {default_quality}")
            quality = default_quality

        mode = "img2img" if ref else "txt2img"
        if ref and not Path(ref).exists():
            errors.append(f"[{tid}] 参考图不存在({ref})，该条降级为文生图")
            ref, mode = "", "txt2img"

        tasks.append({
            "id": tid, "mode": mode, "prompt": prompt,
            "size": size, "quality": quality,
            "style": style or None, "ref_image": ref or None,
            "output_dir": output_dir,
        })

    n = len(tasks)
    return {
        "total": n,
        "credit_estimate": f"{n * CREDIT_LOW}-{n * CREDIT_HIGH} 积分",
        "txt2img": sum(1 for t in tasks if t["mode"] == "txt2img"),
        "img2img": sum(1 for t in tasks if t["mode"] == "img2img"),
        "warnings": errors,
        "tasks": tasks,
    }


def main():
    ap = argparse.ArgumentParser(description="批量清单 -> 执行计划 JSON")
    ap.add_argument("batch_csv", help="批量清单 CSV 路径")
    ap.add_argument("--config", help="painting-config.json 路径(可选)")
    ap.add_argument("-o", "--output", help="计划输出路径(默认 stdout)")
    args = ap.parse_args()

    if not Path(args.batch_csv).exists():
        raise SystemExit(f"错误: 清单不存在 {args.batch_csv}")

    plan = build_plan(load_batch(args.batch_csv), load_config(args.config))
    out = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out + "\n", encoding="utf-8")
        print(f"计划已写入 {args.output}")
    else:
        print(out)
    if plan["warnings"]:
        print("警告项:", file=sys.stderr)
        for w in plan["warnings"]:
            print(f"  - {w}", file=sys.stderr)


if __name__ == "__main__":
    main()

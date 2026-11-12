# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 任意位置启动器（管理台 / 通道可用性检查，二合一入口）。

用法（任何电脑、任何当前目录、双击均可）：
    python 启动.py                     # 启动中心服务（工作台 /：通道中心+作品中心 + 全部 API）
    python 启动.py --status [id ...]   # 通道可用性检查（Agent 用：stdout 纯 JSON）
    python 启动.py --status --refresh  # 跳过缓存强制实测
    python 启动.py --jobs              # 结果中心任务清单（Agent 用：stdout 纯 JSON）
    python 启动.py --job <id>          # 单个任务详情（stdout 纯 JSON）

--status 约定：
    stdout 只输出一行机器 JSON：{"suggest": "<首个可用通道id|null>", "channels": [...]}
    默认 5 分钟内复用缓存状态（秒回）；人读摘要走 stderr；
    退出码 0=全部可用  2=部分可用  3=全部不可用（含无通道）。

--jobs / --job 约定（references/architecture.md）：
    stdout 只输出一行机器 JSON；任务不存在时 --job 输出 null、退出码 4。

技能内全部资源路径由 __file__ 动态解析，不依赖启动位置；
通道发现、core 包导入、凭据仓库、静态资源均自动定位。
"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def cmd_status(channel_ids, refresh=False):
    from core import credcenter
    results = credcenter.check_all(channel_ids or None, refresh=refresh)
    valid = [r for r in results if r["valid"] and r.get("enabled", True)]   # 停用通道不参与 auto 路由
    payload = {
        "suggest": valid[0]["id"] if valid else None,   # auto 路由建议：第一个可用通道
        "channels": results,
    }
    print(json.dumps(payload, ensure_ascii=False))
    print("可用 %d/%d%s" % (
        len(valid), len(results),
        ("；auto 建议：" + valid[0]["id"]) if valid else ""), file=sys.stderr)
    if not results:
        sys.exit(3)
    sys.exit(0 if len(valid) == len(results) else (2 if valid else 3))


def cmd_jobs():
    from core import jobs
    print(json.dumps(jobs.list_jobs(), ensure_ascii=False))


def cmd_job(job_id):
    from core import jobs
    j = jobs.get(job_id)
    print(json.dumps(j, ensure_ascii=False))
    sys.exit(0 if j else 4)


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--status" in argv or "--check" in argv:
        key = "--status" if "--status" in argv else "--check"
        tail = argv[argv.index(key) + 1:]
        cmd_status([a for a in tail if not a.startswith("-")],
                   refresh="--refresh" in argv)
    elif "--jobs" in argv:
        cmd_jobs()
    elif "--job" in argv:
        tail = argv[argv.index("--job") + 1:]
        cmd_job(tail[0] if tail else "")
    else:
        from core.server import main
        main()

# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 通知中心：事件目录 + 路由策略（bus/sse 之上的策略门面）。

设计见 references/architecture.md。分工口径：
- task.* 任务事件：executor 经本模块 emit → bus（进程内）+ hub（SSE 浏览器）双路，
  SSE 帧统一 {"type":"task", "event":"task.xxx", ...载荷}；
- status.changed / enabled / cred.landed：维持既有接线（credcenter bus.emit +
  server bus.on → hub.publish，含 view_status 增补与 Key 回填语义），不泛化进本模块；
- 事件名白名单校验：拼错事件名开发期即抛错，目录即事实源。
"""
import queue
import webbrowser

from .bus import bus
from .sse import hub

# 任务事件目录（SSE 白名单；事件目录全表见 references/architecture.md）
TASK_EVENTS = {"task.accepted", "task.started", "task.item", "task.done", "task.failed",
               "works.changed"}


def emit(event: str, **data) -> None:
    """唯一任务事件入口：进程内 bus 始终广播；SSE 按 task.* 白名单转发。"""
    if event not in TASK_EVENTS:
        raise ValueError("未登记的任务事件: %s（目录见 references/architecture.md）" % event)
    bus.emit(event, **data)
    frame = dict(data)
    frame["type"] = "task"
    frame["event"] = event
    hub.publish(frame)


def navigate(target: str) -> None:
    """UI 导航指令（仅 SSE，非任务事件）：已有页面在线时原地切换，不新开页面。

    target 为锚点：#jobs-<id> / #works（作品中心）、#channels（通道中心）。
    """
    hub.publish({"type": "navigate", "target": target})


def navigate_or_open(base_url: str, target: str) -> str:
    """单例页面语义的统一入口（提交定位作品中心 / 调起管理台共用）。

    页面在线（SSE 有 img 订阅者）→ 原地切换，返回 "navigated"；
    无页面在线 → webbrowser.open 新开直达，返回 "opened"。
    base_url 为中心根（如 http://127.0.0.1:8765），target 为锚点。
    """
    if subscriber_count("img") > 0:
        navigate(target)
        return "navigated"
    try:
        webbrowser.open(base_url.rstrip("/") + target)
    except Exception:
        pass
    return "opened"


def subscribe(tag: str = None) -> queue.Queue:
    """订阅 SSE 推送（tag 标记客户端类型，当前仅 img＝工作台/结果页）。"""
    return hub.subscribe(tag)


def unsubscribe(q) -> None:
    hub.unsubscribe(q)


def subscriber_count(tag: str = None) -> int:
    """订阅者数（可按客户端类型统计；结果中心自动弹页判据）。"""
    return hub.subscriber_count(tag)

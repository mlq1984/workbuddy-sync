# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 进程内事件总线（发布/订阅）。

仅在「必要耦合点」使用（见 references/architecture.md）：
- cred.landed    : 统一落盘后触发（生产者=编排层）
- status.changed : 状态变化后广播（生产者=编排层，消费者=SSE Hub）
- log            : 可选运维事件

线程安全：订阅表加锁；emit 时逐个调用，单个订阅者异常不影响其他。
"""
import logging
import threading

logger = logging.getLogger("orchestrator")


class Bus:
    def __init__(self):
        self._subs = {}
        self._lock = threading.Lock()

    def on(self, event, handler):
        with self._lock:
            self._subs.setdefault(event, []).append(handler)

    def emit(self, event, **data):
        with self._lock:
            handlers = list(self._subs.get(event, ()))
        for h in handlers:
            try:
                h(**data)
            except Exception:
                logger.exception("事件处理失败: %s", event)


bus = Bus()

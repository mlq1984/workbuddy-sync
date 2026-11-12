# -*- coding: utf-8 -*-
"""Ai公益生图Pro · SSE Hub（服务端单向推送）。

前端订阅 /api/events：连接即收到 snapshot，此后实时刷新——
工作台（console.html：通道屏消费 status/enabled 帧，作品屏消费 task 帧）。
SSE 选型依据：单向推送场景下比 WebSocket 更简单（纯 HTTP、自动重连），
本系统无"浏览器→服务端推送"需求（动作走普通 fetch）。

tag 机制（references/architecture.md）：subscribe(tag) 标记客户端类型（img/console），
subscriber_count(tag) 按类型计数——结果中心"自动弹页"的判据；不传 tag 行为不变。
"""
import queue
import threading


class SSEHub:
    def __init__(self):
        self._qs = {}          # queue -> client tag（None=未标记）
        self._lock = threading.Lock()

    def subscribe(self, tag: str = None) -> queue.Queue:
        q = queue.Queue(maxsize=256)
        with self._lock:
            self._qs[q] = tag
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            self._qs.pop(q, None)

    def subscriber_count(self, tag: str = None) -> int:
        """当前订阅者数；带 tag 则只统计该类型客户端。"""
        with self._lock:
            if tag is None:
                return len(self._qs)
            return sum(1 for t in self._qs.values() if t == tag)

    def publish(self, obj: dict) -> None:
        with self._lock:
            qs = list(self._qs)
        for q in qs:
            try:
                q.put_nowait(obj)
            except queue.Full:
                pass


hub = SSEHub()

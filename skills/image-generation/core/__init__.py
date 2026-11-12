# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 核心包（编排器自身，通道无关）。

四运行中心：通知(notify) / 通道中心(registry+store+switches+credcenter+builtin+credprovider) /
生成中心(params+executor) / 结果中心(jobs+works)；接线与服务(server)、
事件总线(bus)、SSE Hub(sse)、公共底座(common)、公共 HTTP 机制(httpx)、公共媒体机制(media)。
本包不依赖任何具体通道；通道经 channels/<id>/app.py 契约接入。
"""

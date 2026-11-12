# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 同源本地服务（通道无关 · 编排层 = 四运行中心接线点）。

分层（references/architecture.md、06）：本文件是 L2 编排层 = HTTP API + SSE Hub 接线 + 通道页托管。
- 资产管理台（/）· 结果中心画廊（/img 跳转 /#works）· 通道页（/channel/<id>）· 产物（/works/...）同源托管；
- 凭证统一入口：POST /api/channel/<id>/credential（别名 /key、/validate）→ credcenter.commit；
- 生成中心入口：POST /api/execute（通用 spec）→ executor.submit，立即返回 job_id；
- 结果中心查询：GET /api/jobs、GET /api/job/<id>、GET /api/ping（实例发现/健康检查）；
- SSE：GET /api/events?client=img|console —— 连接即 snapshot，此后 status/task 实时推送；
- 通道页服务时仅注入薄垫片：把页面内 /api/... 前缀改写为 /api/channel/<id>/...
  （/api/bg、/api/channels、/api/events 除外）；根绝对静态资源重定位到 /channel/<id>/ 下。
"""
import configparser
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import credcenter, custom_channels, executor, jobs, media, notify, \
    registry, switches, works
from .bus import bus
from .common import bing_bg, get_logger
from .credcenter import view_status
from .registry import all_channels, get_channel, get_channel_dir, get_meta
from .sse import hub
from .store import get_key, get_status

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONSOLE_HTML = os.path.join(ROOT, "ui", "console.html")
UI_DIR = os.path.join(ROOT, "ui")
CENTER_FILE = os.path.join(os.path.expanduser("~/.aipro"), "center.json")
DEFAULT_PORT = 8765
APP_VERSION = "1.21.0"     # 与 SKILL.md / manifest.json 版本号保持三方一致

logger = get_logger()

# 通道页内请求里，保持全局（不被改写前缀）的 API
_API_WHITELIST = {"/api/bg", "/api/channels", "/api/events"}

# 通道页里的根绝对静态资源（如 /favicon.png、/qrcode.png）→ 重定位到 /channel/<id>/ 下；
# /api/ 开头的请求交给运行时垫片处理，此处不动。
_ROOT_ABS_RE = re.compile(r'(src|href)="/(?!api/)([^"/][^"]*)"')


def _rebase(channel_id: str, html: str) -> str:
    return _ROOT_ABS_RE.sub(
        lambda m: '%s="/channel/%s/%s"' % (m.group(1), channel_id, m.group(2)), html
    )


def _shim(channel_id: str) -> str:
    """注入通道页的薄垫片：仅做 /api 前缀改写（状态刷新已由 SSE 全局广播承担）。"""
    cid = channel_id
    wl = "|".join(_API_WHITELIST)
    return (
        "<script>(function(){"
        "var ID=%s;var WL=%s;"
        "function rw(u){if(typeof u!=='string')return u;var p=u.split('?')[0];"
        "if(WL.indexOf(p)>=0)return u;if(u.indexOf('/api/')!==0)return u;"
        "return u.replace(/^(\\/api\\/)/,'/api/channel/'+ID+'/');}"
        "var real=window.fetch.bind(window);"
        "window.fetch=function(input,init){"
        "if(typeof input==='string'){return real(rw(input),init||{});}"
        "var nu=rw(input.url);var ro=new Request(nu,{method:input.method,headers:input.headers,body:input.body});"
        "return real(ro,init);};"
        "})();</script>"
    ) % (json.dumps(cid), json.dumps(wl))


# 通道页主题：管理台同风格的覆盖样式（仅换肤，不动通道文件与布局）+ 暗色 scrim 纠正
# （通道页自带 JS 会往 body 写暖色遮罩内联样式，此处用 MutationObserver 实时改写为管理台同款暗 scrim）
_THEME = (
    '<link rel="stylesheet" href="/ui/channel_theme.css">'
    "<script>(function(){"
    "var DARK='linear-gradient(180deg, rgba(8,14,26,.48), rgba(8,14,26,.62)), ';"
    "function fix(){var b=document.body;if(!b)return;var s=b.style,bi=s.backgroundImage||'';"
    "if(bi&&bi.indexOf('url(')>=0&&bi.indexOf('rgba(8,14,26')<0){"
    "var m=bi.match(/url\\([\"']?([^\"')]+)[\"']?\\)/);"
    "if(m)s.backgroundImage=DARK+'url(\"'+m[1]+'\")';}}"
    "function attach(){if(!document.body){setTimeout(attach,40);return;}"
    "try{new MutationObserver(fix).observe(document.body,{attributes:true,attributeFilter:['style']});}catch(e){}"
    "fix();}"
    "attach();"
    "document.addEventListener('DOMContentLoaded',fix);"
    "window.addEventListener('load',fix);"
    "var n=0,iv=setInterval(function(){fix();if(++n>20)clearInterval(iv);},400);"
    "})();</script>"
)

# ---- SSE 接线：status.changed 事件 → 广播给所有浏览器（含当前 Key 供输入框回填） ----
bus.on("status.changed", lambda cid, status: hub.publish(
    {"type": "status", "id": cid, "status": view_status(cid), "key": get_key(cid) or ""}))


def _channel_views():
    """通道清单视图：元数据 + 状态（含内置/需key语义）+ 用户 Key（回填用）+ 启用开关 + 自定义标记。
    自定义通道附加 rec（注册原始数据：name/protocol/base_url/model/official_url，编辑回填用；不含 Key）。"""
    views = []
    for c in all_channels():
        rec = custom_channels.get(c["id"])
        views.append(dict(get_meta(c["id"]), key=get_key(c["id"]) or "",
                          status=view_status(c["id"]),
                          enabled=switches.is_enabled(c["id"]),
                          custom=bool(rec), rec=rec or None))
    return views


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _ctype(self, path):
        ext = os.path.splitext(path)[1].lower()
        return {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".svg": "image/svg+xml", ".ico": "image/x-icon",
            ".css": "text/css", ".js": "application/javascript", ".json": "application/json",
            ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
        }.get(ext, "application/octet-stream")

    def _file(self, path_):
        try:
            with open(path_, "rb") as f:
                b = f.read()
        except Exception:
            self._json(404, {"ok": False, "msg": "not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", self._ctype(path_))
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or "0")
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _sse(self):
        """GET /api/events：连接即发 snapshot，此后实时推送状态/任务变化。

        ?client=img|console 标记客户端类型（结果中心自动弹页按 img 类计数）。
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        tag = (qs.get("client") or [None])[0]
        q = notify.subscribe(tag)
        try:
            snap = {"type": "snapshot", "channels": _channel_views(),
                    "worksCount": len(works.snapshot())}
            self.wfile.write(("data: %s\n\n" % json.dumps(snap, ensure_ascii=False)).encode("utf-8"))
            self.wfile.flush()
            while True:
                try:
                    item = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")   # 保活注释帧
                    self.wfile.flush()
                    continue
                self.wfile.write(("data: %s\n\n" % json.dumps(item, ensure_ascii=False)).encode("utf-8"))
                self.wfile.flush()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            notify.unsubscribe(q)

    # ---------------- GET ----------------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            return self._file(CONSOLE_HTML)
        if path.startswith("/ui/"):
            rel = path[len("/ui/"):]
            cand = os.path.normpath(os.path.join(UI_DIR, rel))
            if os.path.isfile(cand) and os.path.commonpath([cand, UI_DIR]) == UI_DIR:
                return self._file(cand)
            return self._json(404, {"ok": False, "msg": "not found"})
        if path == "/api/ping":
            return self._json(200, {"ok": True, "service": "aipro-center",
                                    "version": APP_VERSION})
        if path == "/api/jobs":
            return self._json(200, jobs.list_jobs())
        if path.startswith("/api/job/"):
            parts = [p for p in path.split("/") if p]
            j = jobs.get(parts[2]) if len(parts) > 2 else None
            return self._json(200, j) if j else \
                self._json(404, {"ok": False, "msg": "no such job"})
        if path == "/img":   # 兼容旧入口：结果中心已并入工作台第二屏
            self.send_response(302)
            self.send_header("Location", "/#works")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path.startswith("/works/"):
            fp = media.resolve_web(path)
            return self._file(fp) if fp else self._json(404, {"ok": False, "msg": "not found"})
        if path == "/api/channels":
            return self._json(200, _channel_views())
        if path == "/api/works":     # 作品中心数据（目录扫描 ⊕ img.json 登记簿）
            return self._json(200, {"ok": True, "works": works.scan_join()})
        if path == "/api/storage":   # 当前产物根（设置弹窗回显）
            return self._json(200, {"ok": True, "dir": media.OUTPUT_ROOT})
        if path == "/api/bg":
            return self._json(200, bing_bg())
        if path == "/api/events":
            return self._sse()
        if path.startswith("/api/channel/") and path.endswith("/status"):
            cid = path.split("/")[3]
            return self._json(200, get_status(cid))
        if path.startswith("/channel/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) < 2:
                return self._json(404, {"ok": False, "msg": "not found"})
            cid = parts[1]
            ch_dir = get_channel_dir(cid)
            if not ch_dir:
                return self._json(404, {"ok": False, "msg": "no such channel"})
            rel = parts[2] if len(parts) > 2 else "index.html"
            cand = os.path.normpath(os.path.join(ch_dir, rel))
            if not (os.path.isfile(cand) and os.path.commonpath([cand, ch_dir]) == ch_dir):
                return self._json(404, {"ok": False, "msg": "not found"})
            if rel == "index.html":
                with open(cand, "r", encoding="utf-8", errors="replace") as f:
                    html = f.read()
                html = _rebase(cid, html)
                html = html.replace("</head>", _THEME + _shim(cid) + "</head>", 1)
                if "</head>" not in html:
                    html = _shim(cid) + html
                b = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)
                return
            return self._file(cand)
        self._json(404, {"ok": False, "msg": "not found"})

    # ---------------- POST ----------------
    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/execute":   # 生成中心唯一入口：通用 spec，立即返回 job_id
            res = executor.submit(self._body())
            return self._json(200 if res.get("ok") else 400, res)
        if path == "/api/console/open":   # 调起管理台（单例页面语义）：在线→原地切通道中心；未开→新开
            mode = notify.navigate_or_open(executor.BASE_URL, "#channels")
            return self._json(200, {"ok": True, "mode": mode})
        if path == "/api/channels/custom":        # 自定义中转通道：注册 → 热刷新 → Key 经统一入口落盘验证
            b = self._body() or {}
            if not str(b.get("key") or "").strip():
                return self._json(400, {"ok": False, "msg": "Key 不能为空"})
            res = custom_channels.add(b.get("name"), b.get("protocol"),
                                      b.get("base_url"), b.get("model"),
                                      b.get("official_url") or "")
            if not res.get("ok"):
                return self._json(400, res)
            registry.reload()
            vres = credcenter.commit(res["id"], str(b["key"]).strip())   # 落盘+验证+广播，与卡片同源
            return self._json(200, {"ok": True, "id": res["id"],
                                    "valid": vres.get("valid"),
                                    "message": vres.get("message", "")})
        if path == "/api/channels/custom/delete":  # 删除自定义通道（凭证一并清；作品保留）
            res = custom_channels.remove((self._body() or {}).get("id", ""))
            if res.get("ok"):
                registry.reload()
                bus.emit("status.changed", cid="", status={})
            return self._json(200, res)
        if path == "/api/channels/custom/edit":    # 编辑自定义通道：元数据 + 凭证（Key 同经统一入口）
            b = self._body() or {}
            res = custom_channels.edit(b.get("id"), b.get("name"), b.get("protocol"),
                                       b.get("base_url"), b.get("model"),
                                       b.get("official_url") or "")
            if not res.get("ok"):
                return self._json(400, res)
            registry.reload()
            cid = res["id"]
            if "key" in b:
                # 提交了 key：非空=设/改，空串=清（与卡片「验证/清空」同一条 commit 路径）
                vres = credcenter.commit(cid, str(b["key"]).strip())
            else:
                vres = credcenter.commit(cid)      # 未提交 key（仅改元数据）→ 信息变了（地址/模型）→ 重验并广播
            return self._json(200, {"ok": True, "id": cid,
                                    "valid": vres.get("valid"),
                                    "message": vres.get("message", "")})
        if path == "/api/storage/open":   # 打开目录（缺省=当前产物根；资源管理器新窗置前）
            return self._json(200, media.open_folder((self._body() or {}).get("dir")))
        if path == "/api/storage/pick":   # 原生选目录，仅返回路径（保存由 associate 执行）
            return self._json(200, media.pick_folder())
        if path == "/api/storage/associate":   # 关联新产物根 + 迁移（档案路径随迁改写）
            res = media.associate((self._body() or {}).get("dir", ""))
            if res.get("ok") and res.get("mapping"):
                jobs.rebase(res.pop("mapping"))
            return self._json(200, res)
        if path == "/api/works/delete":   # 作品删除：删文件 + 删登记（业务在 works）
            res = works.remove_file((self._body() or {}).get("file", ""))
            if res.get("ok"):
                notify.emit("works.changed")
            return self._json(200, res)
        if not path.startswith("/api/channel/"):
            return self._json(404, {"ok": False, "msg": "not found"})
        parts = [p for p in path.split("/") if p]   # ["api","channel",cid,tail]
        if len(parts) < 4:
            return self._json(404, {"ok": False, "msg": "not found"})
        cid, tail = parts[2], parts[3]
        ch = get_channel(cid)
        if not ch:
            return self._json(404, {"ok": False, "msg": "no such channel"})
        data = self._body()

        # 统一凭证入口：credential（规范名，当前页面在用）/ key、validate（历史兼容别名，仓内零调用方）
        if tail in ("credential", "key", "validate"):
            return self._json(200, credcenter.commit(cid, data.get("key")))

        # 通道启用开关：落盘 + 广播（多管理台同步）
        if tail == "enabled":
            enabled = bool(data.get("enabled", True))
            switches.set_enabled(cid, enabled)
            hub.publish({"type": "enabled", "id": cid, "enabled": enabled})
            return self._json(200, {"ok": True, "id": cid, "enabled": enabled})

        if tail in ("login", "code", "reset"):   # auto 通道：账号子步骤
            res = ch["module"].account_api(tail, data)
            # 一旦账号流产出 key → 立刻汇入统一入口（落盘+验证+广播）
            if isinstance(res, dict) and res.get("ok") and res.get("key"):
                res["credential"] = credcenter.commit(cid, res.get("key"))
            return self._json(200, res or {"ok": False, "msg": "no response"})

        self._json(404, {"ok": False, "msg": "not found"})

    def log_message(self, *a):
        pass


def _port() -> int:
    """中心端口：config.ini [server] port 可覆盖，缺省 8765（references/architecture.md）。"""
    cp = configparser.ConfigParser()
    try:
        cp.read(os.path.join(ROOT, "config.ini"), encoding="utf-8")
        return int(cp.get("server", "port"))
    except Exception:
        return DEFAULT_PORT


def _alive(port: int) -> bool:
    """探测端口上是否已有中心实例（/api/ping）。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def _write_center(port: int) -> None:
    """落盘实例发现文件 ~/.aipro/center.json（不含任何秘密，Agent 寻址用）。"""
    try:
        os.makedirs(os.path.dirname(CENTER_FILE), exist_ok=True)
        tmp = CENTER_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"port": port, "pid": os.getpid(),
                       "started_at": datetime.now().isoformat(timespec="seconds")}, f)
        os.replace(tmp, CENTER_FILE)
    except Exception:
        pass


def _works_monitor():
    """作品文件夹监控：2s 快照对比，外部增删图片 → 广播 works.changed（前端刷新作品中心）。"""
    last = works.snapshot()
    while True:
        try:
            time.sleep(2)
            snap = works.snapshot()
            if snap != last:
                last = snap
                notify.emit("works.changed")
        except Exception:
            pass


class Server(ThreadingHTTPServer):
    allow_reuse_address = False   # Windows 下禁止同端口重复绑定，避免多实例脑裂


def main():
    port = _port()
    try:
        httpd = Server(("127.0.0.1", port), Handler)
    except OSError:
        if _alive(port):      # 已有实例：复用，不重复起服务
            url = "http://127.0.0.1:%d/" % port
            executor.BASE_URL = url.rstrip("/")
            logger.info("中心已在运行，复用：%s", url)
            print("中心已在运行，复用：", url, flush=True)
            try:   # 调起管理台（服务进程全权处理：在线→原地切通道中心；未开→新开页面）
                req = urllib.request.Request(
                    url + "/api/console/open", data=b"{}",
                    headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=3).read()
            except Exception:
                pass
            return
        print("端口 %d 被占用且无中心实例；可在 config.ini [server] port 换端口。"
              % port, flush=True)
        sys.exit(1)
    url = "http://127.0.0.1:%d/" % httpd.server_address[1]
    executor.BASE_URL = url.rstrip("/")
    _write_center(port)
    logger.info("Ai公益生图Pro 中心已启动：%s（工作台 /：通道中心 + 作品中心）", url)
    print("中心已启动：", url, flush=True)
    print("  工作台（通道中心 + 作品中心）：", url, flush=True)
    # 启动自检：后台线程并发验证所有通道，逐个 SSE 广播（不阻塞服务启动）
    threading.Thread(target=credcenter.startup_check, daemon=True).start()
    # 作品文件夹监控：外部增删图片实时反映到作品中心
    threading.Thread(target=_works_monitor, daemon=True).start()
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 自定义中转通道（数据化注册 + 协议适配器）。

用户在管理台录入（名称/协议/请求地址/模型名/Key/官网）→ 写注册表
~/.aipro/custom_channels.json（用户数据不进技能本体）→ registry 合并呈现；
两个协议适配器把通用 spec 翻译为对应 HTTP 请求：
- open    OpenAI 兼容（官方/中转）：POST /v1/images/generations（size 比例或像素、
          image_size 档位、image data URI 数组即图生图）；同步 data 或 task_id 轮询皆兼容
- gemini  Gemini 兼容：POST /v1beta/models/{model}:generateContent
          （imageConfig.aspectRatio/imageSize；响应兼容 inlineData/inline_data 与 text=URL 变体）
Key 走统一凭证仓库（store），Agent 不可见；验证零成本（不触发真实生图）。

内置模型族（2026-10 官方文档核实，最新在前 = 缺省模型）：
- open    GPT Image 2.5 双子星（flare=快速高质量日常缺省；sunburst=编辑精度优先，图生图推荐）
          + 旧族 gpt-image-2 / 1.5 / 1 / 1-mini
- gemini  Nano Banana 2.1（gemini-nano-banana-2.1，官方主力，缺省）+ Nano Banana 2 / Pro（GA）
          + Lite（gemini-3.1-flash-lite-image）+ 旧款 2.5
两协议均支持文生图与图生图（参考图上限随协议：open 10 / gemini 14，协商层截断）。
比例族为官方现行 10 种；open 协议原生支持 n（1~4）与 quality 等官方生成参数
（options 透传白名单：quality/background/output_format/output_compression/moderation）。
"""
import base64
import json
import os
import re
import threading
import time
import urllib.parse

from . import httpx, media, store

REG_FILE = os.path.join(os.path.expanduser("~/.aipro"), "custom_channels.json")
_LOCK = threading.Lock()
PROTOCOLS = ("open", "gemini")
# 各协议官网现行模型族（2026-10 官方文档核实；最新在前 = 缺省模型，用户注册时可补充自定义模型名）
# open:   GPT Image 2.5 双子星（flare=快速高质量日常；sunburst=编辑精度优先）+ 旧族 2/1.5/1/1-mini
# gemini: Nano Banana 2.1（官方钦定主力工作模型）+ Nano Banana 2/Pro GA 型号 + Lite + 旧款 2.5
BUILTIN_MODELS = {
    "open": ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst",
             "gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini"],
    "gemini": ["gemini-nano-banana-2.1", "gemini-3.1-flash-image", "gemini-3-pro-image",
               "gemini-3.1-flash-lite-image", "gemini-2.5-flash-image"],
}
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
_POLL_INTERVAL = 3
_POLL_TIMEOUT = 300
# 官方现行比例族（2026-10 核实）：Gemini 官方 imageConfig.aspectRatio 全表 10 种；
# OpenAI 2.5 自定义像素规则允许 1:3~3:1，中继通行同族（协商层对越族比例就近映射）
_RATIOS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]
_BASE_CAPS = {"t2i": True, "i2i": True, "upscale": False,
              "tiers": ["1K", "2K", "4K"], "ratios": _RATIOS, "concurrency": 1}
# 协议差异（官方口径）：open generations 原生支持 n（校验族 1~4），参考图中继通行 10；
# gemini generateContent 图像模型单候选（n 不适用），Nano Banana 2.1/Pro 官方参考图 10+4 / 6+5+3 = 14
_PROTOCOL_CAPS = {"open": {"n": True, "image_refs": 10},
                  "gemini": {"n": False, "image_refs": 14}}
# GPT Image 2.5 官方生成参数（options 透传白名单，标量；未传不造参）
_OPEN_EXTRA = ("quality", "background", "output_format",
               "output_compression", "moderation")


def _norm_base_url(raw: str) -> str:
    """归一化中转站地址：去尾斜杠，并剥掉路径末端的版本段（/v1、/v1beta）。

    管理台提示用户填带版本的完整地址（如 https://api.xx.com/v1），而请求侧
    统一拼 /v1/...（open）或 /v1beta/...（gemini）；不归一化会拼成
    /v1/v1/... 导致 404。只处理路径末段、不动主机名（主机名恰为 v1 时不受影响）。
    """
    s = str(raw or "").strip().rstrip("/")
    m = re.match(r"^(https?://[^/]+)(/.*)?$", s)
    if not m:
        return s
    host, path = m.group(1), (m.group(2) or "")
    if path.rsplit("/", 1)[-1] in ("v1", "v1beta"):
        path = path.rsplit("/", 1)[0]
    return host + path


# ---------- 注册表 ----------
def _load() -> dict:
    try:
        with open(REG_FILE, encoding="utf-8") as f:
            return json.loads(f.read())
    except Exception:
        return {}


def _save(data: dict) -> None:
    tmp = REG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REG_FILE)


def list_channels() -> list:
    """注册表 → 通道记录列表（保持创建顺序）。"""
    return list(_load().values())


def get(cid: str):
    return _load().get(cid)


def models_of(rec: dict) -> list:
    """通道可用模型清单：内置官网模型在前 + 用户设置（中英文逗号分隔）去重并入。"""
    builtin = list(BUILTIN_MODELS.get(rec.get("protocol"), []))
    raw = str(rec.get("model") or "")
    extra = [m.strip() for m in re.split(r"[,，]", raw) if m.strip()]
    out = []
    for m in builtin + extra:
        if m not in out:
            out.append(m)
    return out


def add(name: str, protocol: str, base_url: str, model: str,
        official_url: str = "") -> dict:
    """录入校验 → 分配 id（u<序号>，无下划线——作品命名解析依赖）→ 落注册表。"""
    name = str(name or "").strip() or "自定义通道"
    protocol = str(protocol or "").strip().lower()
    base_url = _norm_base_url(base_url)
    model = str(model or "").strip()
    official_url = str(official_url or "").strip()
    if protocol not in PROTOCOLS:
        return {"ok": False, "msg": "协议需为 open / gemini"}
    if not re.match(r"^https?://", base_url):
        return {"ok": False, "msg": "请求地址需为 http(s):// 开头的 URL"}
    # model 选填：留空用协议内置模型；多模型用中英文逗号分隔（models_of 规范化）
    with _LOCK:
        data = _load()
        cid = "u1"
        while cid in data:
            cid = "u%d" % (int(cid[1:]) + 1)
        data[cid] = {"id": cid, "name": name, "protocol": protocol,
                     "base_url": base_url, "model": model,
                     "official_url": official_url}
        _save(data)
    return {"ok": True, "id": cid}


def edit(cid: str, name: str, protocol: str, base_url: str, model: str,
         official_url: str = "") -> dict:
    """编辑通道信息（Key 不在此改——由调用方经 credcenter.commit 统一落盘，编辑弹窗可回填/覆盖/清空）。"""
    with _LOCK:
        data = _load()
        rec = data.get(cid)
        if not rec:
            return {"ok": False, "msg": "通道不存在"}
        protocol = str(protocol or "").strip().lower()
        base_url = _norm_base_url(base_url)
        model = str(model or "").strip()
        if protocol not in PROTOCOLS:
            return {"ok": False, "msg": "协议需为 open / gemini"}
        if not re.match(r"^https?://", base_url):
            return {"ok": False, "msg": "请求地址需为 http(s):// 开头的 URL"}
        # model 选填（与 add 一致）：留空回退协议内置模型；多模型用中英文逗号分隔
        rec.update({"name": str(name or "").strip() or "自定义通道",
                    "protocol": protocol, "base_url": base_url, "model": model,
                    "official_url": str(official_url or "").strip()})
        _save(data)
    return {"ok": True, "id": cid}


def remove(cid: str) -> dict:
    """删除通道：注册表移除 + 凭证段清除（已出图作品保留，与作品无关）。"""
    with _LOCK:
        data = _load()
        if cid not in data:
            return {"ok": False, "msg": "通道不存在"}
        del data[cid]
        _save(data)
    store.clear_key(cid)
    return {"ok": True}


# ---------- 适配器（module-like 对象，registry 合并后与文件夹通道同构） ----------
def adapter(rec: dict):
    return _Adapter(rec)


class _Adapter:
    """单条自定义通道的 module-like 适配器：registry/params/executor 契约全兼容。"""

    def __init__(self, rec: dict):
        self._rec = rec
        self.CHANNEL_ID = rec["id"]
        self.TITLE = rec["name"]
        self.MODE = "manual"
        self.DESCRIPTION = "%s · %s 协议中转（文生图/图生图；模型 %s）" % (
            rec["name"], rec["protocol"], rec["model"])
        self.ICON = "🌐"
        self.ORDER = 150
        if rec.get("official_url"):
            self.ACQUIRE_URL = rec["official_url"]

    def translate(self, clean: dict) -> dict:
        """通道级方言翻译（自治）：通用 spec → 本通道 generate kwargs。

        协议差异在此体现——open 透传官方生成参数白名单（quality 等官方字段）；
        gemini 的 generationConfig.imageConfig 为官方封闭集，**不透传** options。
        （core 不再代劳通道专属参数：options 由本通道按官方能力取用。）
        """
        kw = {"prompt": clean["prompt"]}
        if clean.get("model"):
            kw["model"] = clean["model"]
        if clean.get("ratio"):
            kw["size"] = clean["ratio"]
        if clean.get("tier"):
            kw["image_size"] = clean["tier"]
        if clean.get("n"):
            kw["n"] = clean["n"]
        if clean.get("image"):
            kw["image"] = clean["image"]
        if self._rec["protocol"] == "open":
            for k in _OPEN_EXTRA:
                v = (clean.get("options") or {}).get(k)
                if v is not None:
                    kw[k] = v
        return kw

    @property
    def CAPS(self) -> dict:
        """协议感知能力集：随 rec.protocol 实时派生（与 MODELS 同模式，协议切换不脱节）。"""
        caps = dict(_BASE_CAPS)
        caps.update(_PROTOCOL_CAPS.get(self._rec["protocol"], {}))
        return caps

    @property
    def MODELS(self) -> list:
        """通道可用模型清单：随 rec 实时派生（内置官网模型 + 用户补充，去重保序）。

        与 base_url/protocol 的实时读取模式保持一致——避免 rec 变更后
        （协议 open↔gemini 切换）模型清单与请求 URL 脱节。"""
        return models_of(self._rec)

    # ---- registry/credcenter 契约：零成本验证（不触发真实生图）；不可达一律无效（用户裁定） ----
    def validate_key(self, key: str) -> dict:
        p = self._rec["protocol"]
        base = self._rec["base_url"]
        if p == "open":         # OpenAI 生态事实标准：GET /v1/models
            st, body = self._http("GET", base + "/v1/models", key=key)
        else:                   # gemini：官方模型列表端点
            st, body = self._http(
                "GET", base + "/v1beta/models?key=" + urllib.parse.quote(key),
                key=key, dual=True)
        if st is None:
            return {"valid": False, "message": "验证不可达"}
        if st in (401, 403):
            return {"valid": False, "message": self._err(body, "Key 无效")}
        return {"valid": True, "message": "有效"}

    # ---- executor 契约：generate（签名与缺省翻译器 kwargs 对齐） ----
    def generate(self, prompt: str, size: str = None, image_size: str = None,
                 n: int = 1, model: str = None, image=None, **opts) -> list:
        rec = self._rec
        p = rec["protocol"]
        base = rec["base_url"]
        key = store.get_key(rec["id"])
        model = model or (self.MODELS[0] if self.MODELS else rec["model"])
        uris = self._data_uris(image)
        paths = []
        if p == "open":
            payload = {"model": model, "prompt": prompt, "n": n}
            if size:
                payload["size"] = size
            if image_size:
                payload["image_size"] = image_size
            if uris:
                payload["image"] = uris
            for k in _OPEN_EXTRA:                  # 官方生成参数（options 白名单透传）
                if k in opts and opts[k] is not None:   # 按键存在判定：0/False 也是有效取值
                    payload[k] = opts[k]
            st, resp = self._http("POST", base + "/v1/images/generations",
                                  payload, key=key)
            task = resp.get("task_id") if isinstance(resp, dict) else None
            if task:                                    # 网关式异步任务（兼容）
                resp = self._poll(base, task, key)
            paths = self._open_paths(resp)
        else:                   # gemini（官方形态；inlineData 与 text=URL 双解析）
            parts = [{"text": prompt}]
            parts += [{"inlineData": {"mimeType": "image/png", "data": u.split(",", 1)[-1]}}
                      for u in uris]                # 官方 generateContent 规范字段名（驼峰）
            gencfg = {"responseModalities": ["TEXT", "IMAGE"]}
            ic = {}
            if size:
                ic["aspectRatio"] = size
            if image_size:
                ic["imageSize"] = image_size
            if ic:
                gencfg["imageConfig"] = ic
            payload = {"contents": [{"parts": parts}], "generationConfig": gencfg}
            mpath = urllib.parse.quote(str(model).split("/")[-1], safe="")
            st, resp = self._http(
                "POST", base + "/v1beta/models/%s:generateContent" % mpath,
                payload, key=key, dual=True)
            task = resp.get("task_id") if isinstance(resp, dict) else None
            if task:
                resp = self._poll(base, task, key)
            paths = self._gemini_paths(resp)
        if not paths:
            raise RuntimeError("未拿到图片：%s" % self._short(resp))
        return paths

    def upscale(self, image: str, scale: int = 2, **_) -> list:
        raise RuntimeError("该中转通道不支持放大（CAPS 已声明，此路径不应到达）")

    # ---- 内部：HTTP / 轮询 / 提取 / 落盘 ----
    @staticmethod
    def _short(resp) -> str:
        try:
            return json.dumps(resp, ensure_ascii=False)[:300]
        except Exception:
            return str(resp)[:300]

    @staticmethod
    def _err(body: str, default: str) -> str:
        try:
            m = json.loads(body).get("error", {})
            return m.get("message") or default
        except Exception:
            return (body or default)[:200]

    def _http(self, method: str, url: str, payload: dict = None,
              key: str = "", dual: bool = False, retries: int = 2):
        """统一 HTTP（复用 core.httpx 公共层）：UA 必带（网关任务查询 403 code 1010）。"""
        extra = {"x-goog-api-key": key} if dual else None   # gemini 官方/中转双兼容
        return httpx.http_json(method, url, payload, token=key or "",
                               user_agent=_UA, extra_headers=extra,
                               timeout=90, retries=retries,
                               connection_close=True)

    def _poll(self, base: str, task_id: str, key: str) -> dict:
        """统一任务轮询（网关 async:true）：响应出现 data/candidates 即完成（无 status 字段）。"""
        start = time.time()
        last = {}
        while time.time() - start < _POLL_TIMEOUT:
            st, resp = self._http("GET", base + "/v1/tasks/" + task_id, key=key)
            if st == 200 and isinstance(resp, dict):
                last = resp
                if resp.get("status") == "failed":
                    raise RuntimeError("生图失败: %s" % self._short(
                        resp.get("error") or resp))
                if resp.get("data") or resp.get("candidates"):
                    return resp
            time.sleep(_POLL_INTERVAL)
        raise RuntimeError("生图轮询超时（%ds）" % _POLL_TIMEOUT)

    @staticmethod
    def _data_uris(image) -> list:
        """spec.image（路径/URL/纯 b64，str 或 list）→ data URI 数组。"""
        imgs = [image] if isinstance(image, str) else (image or [])
        out = []
        for v in imgs:
            v = str(v).strip()
            if not v:
                continue
            if v.startswith("data:"):
                out.append(v)
            elif v.startswith("http://") or v.startswith("https://"):
                out.append("data:image/png;base64," +
                           base64.b64encode(httpx.fetch_bytes(v, user_agent=_UA)).decode("ascii"))
            else:
                with open(v, "rb") as f:
                    out.append("data:image/png;base64," +
                               base64.b64encode(f.read()).decode("ascii"))
        return out

    def _save(self, data: bytes) -> str:
        return media.save_output(self._rec["id"], data, "png")

    def _open_paths(self, resp) -> list:
        """OpenAI 形态提取：data[].url（立即下载）或 data[].b64_json。"""
        paths = []
        if not isinstance(resp, dict):
            return paths
        for it in resp.get("data") or []:
            if not isinstance(it, dict):
                continue
            if it.get("b64_json"):
                paths.append(self._save(base64.b64decode(it["b64_json"])))
            elif it.get("url"):
                paths.append(self._save(httpx.fetch_bytes(it["url"], user_agent=_UA)))
        return paths

    def _gemini_paths(self, resp) -> list:
        """Gemini 形态提取：inlineData/inline_data b64；网关变体 parts[].text=URL。"""
        paths = []
        if not isinstance(resp, dict):
            return paths
        for c in resp.get("candidates") or []:
            for p in (c.get("content", {}) or {}).get("parts") or []:
                if not isinstance(p, dict):
                    continue
                d = p.get("inlineData") or p.get("inline_data") or {}
                if d.get("data"):
                    paths.append(self._save(base64.b64decode(d["data"])))
                elif str(p.get("text") or "").startswith("http"):
                    paths.append(self._save(httpx.fetch_bytes(p["text"], user_agent=_UA)))
        return paths

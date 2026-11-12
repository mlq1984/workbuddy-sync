# -*- coding: utf-8 -*-
"""Ai公益生图Pro · 生成中心 · 参数中心：通用 spec 校验 / 能力过滤 / 方言翻译。机制详见 references/architecture.md（设计档案已移出技能外，运行时不读）。

- core 零通道知识：个体方言全部由通道 app.py 可选声明 translate(clean)（纯映射，禁 IO）；
  未声明者走本模块缺省翻译器（OpenAI 兼容通行语义）；
- 能力以通道可选声明 CAPS 为准（缺省值见 DEFAULT_CAPS）；
- 宁缺勿滥进代码：Agent 未提供的可选字段不进翻译输出（None ≠ 传默认）。
"""
import logging
import os
import re

from . import switches
from .credcenter import check_all, credential_label, view_status
from .registry import all_channels, get_channel

logger = logging.getLogger(__name__)

SPEC_FIELDS = {"action", "channels", "prompt", "image", "scale",
               "upscale_prompt", "ratio", "tier", "n", "model", "options"}
DEFAULT_CAPS = {"t2i": True, "i2i": False, "upscale": False, "n": False,
                "tiers": ["1K"], "ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
                "concurrency": 1, "image_refs": 0}


def caps(cid: str, model: str = None) -> dict:
    """通道能力集：声明优先，缺省补齐。

    可选按型号细分：通道声明 MODEL_CAPS = {model: {能力字段: 值}}（部分覆盖），
    用于"同通道不同型号官方能力不同"的事实（如 Cloudflare：flux-1-schnell 官方
    不支持任意尺寸，sdxl/sd15 支持 width/height）。
    未指定 model 时按通道缺省型号（MODELS[0]）取能力——即缺省即默认行为。
    """
    ch = get_channel(cid)
    declared = getattr(ch["module"], "CAPS", None) if ch else None
    c = dict(DEFAULT_CAPS)
    if isinstance(declared, dict):
        c.update(declared)
    mc = getattr(ch["module"], "MODEL_CAPS", None) if ch else None
    if isinstance(mc, dict) and mc:
        m = model
        if not m:
            models = getattr(ch["module"], "MODELS", None) if ch else None
            m = models[0] if models else None
        over = next((v for k, v in mc.items() if k.lower() == str(m).lower()), None) or {}   # 型号名大小写不敏感命中
        if isinstance(over, dict):
            c.update(over)
    return c


def validate(spec: dict):
    """spec → (clean_spec, error)。未知字段拒绝；必填校验；可选字段有值才收。"""
    if not isinstance(spec, dict):
        return None, "spec 必须为 JSON 对象"
    unknown = set(spec) - SPEC_FIELDS
    if unknown:
        return None, "未知字段: %s" % ", ".join(sorted(unknown))
    action = str(spec.get("action") or "generate")
    if action not in ("generate", "upscale"):
        return None, "action 仅支持 generate/upscale"
    chans = spec.get("channels")
    if not isinstance(chans, list) or not chans or \
            not all(isinstance(c, str) and c.strip() for c in chans):
        return None, "channels 必须为非空通道 id 列表"
    known = {c["id"] for c in all_channels()}
    bad = [c for c in chans if c != "auto" and c not in known]
    if bad:
        return None, "未知通道: %s" % ", ".join(bad)
    if "auto" in chans and len(chans) > 1:
        return None, "auto 不能与其他通道混选（auto 单独解析）"

    clean = {"action": action, "channels": list(chans)}
    if action == "generate":
        if not str(spec.get("prompt") or "").strip():
            return None, "generate 需要非空 prompt"
        clean["prompt"] = str(spec["prompt"]).strip()
        # 提示中心·服务端守门（默认关闭；环境变量 AIPO_PROMPT_GUARD 控制，做加法可回退）
        #   "1"/true/yes   = 仅去重/矛盾/维度/长度守门（保持原行为，零变化）
        #   整数(如 60)     = 守门 + 质量评分门阈值（守门提示与评分记入服务日志，不阻断）
        _guard_val = os.environ.get("AIPO_PROMPT_GUARD")
        if _guard_val:
            from .prompt_opt import validate as _guard, score as _score
            clean["prompt"], _issues = _guard(clean["prompt"], keep=clean["prompt"])
            if _guard_val not in ("1", "true", "True", "yes", "on"):
                try:
                    _thr = int(_guard_val)
                    _grade = _score(clean["prompt"], issues=_issues)
                    _issues.append("质量评分 %d/100" % _grade)
                    if _grade < _thr:
                        _issues.append("评分低于阈值 %d，建议回 L1 重述或补维" % _thr)
                except ValueError:
                    pass
            if _issues:
                logger.info("提示中心守门[%s]: %s", _guard_val, "；".join(_issues))
    if spec.get("image") is not None:
        raw = spec["image"]
        imgs = [raw] if isinstance(raw, str) else raw
        if not isinstance(imgs, list) or not imgs or \
                not all(isinstance(x, str) and x.strip() for x in imgs):
            return None, "image 需为非空字符串或非空字符串列表（≤14 张，第 1 张为主编辑图）"
        imgs = [x.strip() for x in imgs][:14]  # 防滥用硬限（官方参考图上限族）；各通道实际上限见 CAPS.image_refs（协商层截断）
        # 单图保持 str（兼容既有执行层路径），多图才用 list
        clean["image"] = imgs[0] if len(imgs) == 1 else imgs
    if action == "upscale":
        if not clean.get("image"):
            return None, "upscale 需要 image（源图）"
        try:
            scale = int(spec.get("scale") or 2)
        except (TypeError, ValueError):
            return None, "scale 需为整数"
        clean["scale"] = 4 if scale >= 4 else 2
        if str(spec.get("upscale_prompt") or "").strip():
            clean["upscale_prompt"] = str(spec["upscale_prompt"]).strip()
    if str(spec.get("ratio") or "").strip():
        r = str(spec["ratio"]).strip()
        # 两端均须为正整数：分母为 0（如 "1:0"）会让协商层的就近映射除零 → 5xx，
        # 故在校验层直接拒绝，不让它流到执行层变成静默失败。
        if not re.match(r"^[1-9]\d{0,2}:[1-9]\d{0,2}$", r):
            return None, "ratio 需形如 16:9（两端为正整数）"
        clean["ratio"] = r
    if str(spec.get("tier") or "").strip():
        # 档位取值合法性属**通道自治**：core 原样传递，由通道按 CAPS.tiers 就近降级并告知
        clean["tier"] = str(spec["tier"]).strip().upper()
    if spec.get("n") is not None:
        if isinstance(spec["n"], bool):   # bool 是 int 子类：true/false 不是合法张数，如实拒绝
            return None, "n 需为整数（不接受布尔）"
        try:
            n = int(spec["n"])
        except (TypeError, ValueError):
            return None, "n 需为整数"
        if not 1 <= n <= 4:
            return None, "n 取值 1~4"
        if action == "generate":
            clean["n"] = n            # 放大无张数语义
    if str(spec.get("model") or "").strip():
        clean["model"] = str(spec["model"]).strip()
    if spec.get("options") is not None:
        opts = spec["options"]
        if not isinstance(opts, dict) or not all(
                isinstance(v, (str, int, float, bool)) for v in opts.values()):
            return None, "options 需为标量值对象（通道专属参数透传，各通道 translate 自行取用）"
        if opts:
            clean["options"] = opts
    return clean, None


def plan(clean: dict) -> dict:
    """clean spec → {accepted, dropped, units}。auto 单独解析为 suggest（用户明确选择才生效）。"""
    chans = list(clean["channels"])
    if chans == ["auto"]:
        suggest = next((r["id"] for r in check_all()
                        if r["valid"] and r.get("enabled")), None)
        if not suggest:
            return {"accepted": [], "units": [],
                    "dropped": [{"id": "auto", "reason": "当前无可用通道"}]}
        chans = [suggest]

    accepted, dropped, units = [], [], []
    action = clean["action"]
    n = (clean.get("n") or 1) if action == "generate" else 1
    for cid in chans:
        cap = caps(cid, clean.get("model"))
        reason = None
        if not switches.is_enabled(cid):
            reason = "通道已停用"
        elif action == "generate" and clean.get("image") and not cap["i2i"]:
            reason = "不支持图生图（编辑）"
        elif action == "upscale" and not cap["upscale"]:
            reason = "不支持放大（增强）"
        elif credential_label(cid) == "需配置":
            reason = "需配置 Key"          # generate/upscale 均需凭证（放大与生图同走生图链路）
        elif view_status(cid).get("state") == "invalid":
            reason = "凭证无效"
        if reason:
            dropped.append({"id": cid, "reason": reason})
        else:
            accepted.append(cid)
            units += [{"channel": cid, "index": i + 1} for i in range(n)]
    return {"accepted": accepted, "dropped": dropped, "units": units}


_TIER_ORDER = {"1K": 1, "2K": 2, "3K": 3, "4K": 4}


def _nearest_tier(target: str, tiers: list):
    """就近升档优先：无更高档则取通道最高档。"""
    if not tiers:
        return None
    t = _TIER_ORDER.get(target)
    if t is None:          # 未知档位（如 8K）→ 就近向上取通道最高档
        return max(tiers, key=lambda x: _TIER_ORDER.get(x, 1))
    ups = [x for x in tiers if _TIER_ORDER.get(x, 1) >= t]
    if ups:
        return min(ups, key=lambda x: _TIER_ORDER.get(x, 1))
    return max(tiers, key=lambda x: _TIER_ORDER.get(x, 1))


def _ratio_val(r: str):
    a, _, b = r.partition(":")
    try:
        return int(a) / int(b)
    except Exception:
        return None


def _nearest_ratio(target: str, ratios: list):
    tv = _ratio_val(target)
    if tv is None:                    # 防御：非法比例（分母 0 等）不参与就近映射
        return None
    cands = [(abs((_ratio_val(r) or 0) - tv), r) for r in ratios if _ratio_val(r)]
    return min(cands)[1] if cands else None


def _negotiate(cid: str, clean: dict, cap: dict) -> dict:
    """可选参数逐通道协商（references/architecture.md 体验协商）：
    - 用户提了但不支持 → 就近降级（tier 就近升档优先 / ratio 就近比例）；
    - 用户没提且通道为免费额度（免Key/内置Key）→ 补体验档 2K（不支持则通道最高档）；
    - 用户没提的 ratio 不凭空造（构图交服务端默认）；
    - 通道无 n 能力 → 参数不下发（executor 扇出阶梯处理）；
    - 多参考图超出通道 image_refs 上限 → 截断保留前 N 张（第 1 张为主编辑图）。
    硬能力不匹配（i2i/upscale/停用/无凭证）不在此层，由 plan 剔除。
    """
    spec = dict(clean)
    is_gen = spec["action"] == "generate"
    tiers = cap.get("tiers") or []
    if spec.get("tier"):
        if tiers and spec["tier"] not in tiers:
            spec["tier"] = _nearest_tier(spec["tier"], tiers)
    elif is_gen and credential_label(cid) in ("免Key", "内置Key") and tiers:
        spec["tier"] = "2K" if "2K" in tiers else tiers[-1]
    if spec.get("ratio") and cap.get("ratios") and spec["ratio"] not in cap["ratios"]:
        spec["ratio"] = _nearest_ratio(spec["ratio"], cap["ratios"]) or None
        if spec["ratio"] is None:
            spec.pop("ratio")
    if not is_gen:
        # upscale：只做 tier/ratio 就近映射（用户显式给的档位与画幅）——
        # 不自动补体验档、不动 n 与参考图（放大是单图单目标动作）
        return {k: v for k, v in spec.items() if v is not None}
    if spec.get("n") and not cap.get("n"):
        spec.pop("n")
    if isinstance(spec.get("image"), list):
        max_refs = int(cap.get("image_refs") or 1)
        if len(spec["image"]) > max_refs:      # 超出通道参考图上限 → 保留前 N 张（第 1 张为主编辑图）
            spec["image"] = spec["image"][:max_refs]
    return {k: v for k, v in spec.items() if v is not None}


_EFFECTIVE_KEYS = ("action", "ratio", "tier", "n", "scale", "model")


def effective(cid: str, clean: dict) -> dict:
    """该通道协商后**实际生效**的语义参数（就近降级/自动补体验档之后），供作品登记与复现。

    不含 prompt/image 等内容字段——只有执行语义（尺寸/档位/张数/动作/模型），不是画面描述。
    """
    spec = _negotiate(cid, clean, caps(cid, clean.get("model")))
    return {k: spec[k] for k in _EFFECTIVE_KEYS if spec.get(k)}


def translate(cid: str, clean: dict) -> dict:
    """clean spec → 该通道 generate/upscale 的 kwargs：先逐通道协商，再走方言翻译。"""
    spec = _negotiate(cid, clean, caps(cid, clean.get("model")))
    ch = get_channel(cid)
    fn = getattr(ch["module"], "translate", None) if ch else None
    if callable(fn):
        out = fn(spec)
        out = out if isinstance(out, dict) else {}
    else:
        out = _default_translate(spec)
    # 语种策略告警：Flux 系通道（cloudflare/free）收到中文且无图上中文文字 → 提示转英文。
    # 转换动作由 Agent 按 core/lang 策略在组装 spec 前执行；此处仅做确定性兜底告警。
    try:
        from .lang import detect_language, lang_policy
        if lang_policy(cid) == "en" and detect_language(spec.get("prompt", "")) == "zh":
            logger.warning(
                "语言策略[%s]：prompt 识别为中文，Flux 英文更稳——建议 Agent 先转英文再提交"
                "（图上需中文文字则改用智谱/商汤/aurora，见 SKILL 4.2）。", cid)
    except Exception:
        pass
    return out


def _default_translate(clean: dict) -> dict:
    """缺省翻译器：OpenAI 兼容通行语义（prompt/model/n；ratio→size；tier→image_size）。
    仅服务未声明 translate 的新通道；个体方言应自行声明 translate（references/architecture.md）。"""
    if clean["action"] == "upscale":
        kw = {"image": clean["image"], "scale": clean.get("scale", 2)}
        if clean.get("upscale_prompt"):
            kw["prompt"] = clean["upscale_prompt"]
        return kw
    kw = {"prompt": clean["prompt"]}
    if clean.get("image"):
        kw["image"] = clean["image"]
    if clean.get("model"):
        kw["model"] = clean["model"]
    if clean.get("ratio"):
        kw["size"] = clean["ratio"]
    if clean.get("tier"):
        kw["image_size"] = clean["tier"]
    if clean.get("n"):
        kw["n"] = clean["n"]
    # options（通道专属参数）**不由 core 透传**——由通道自己的 translate 按官方能力取用。
    return kw

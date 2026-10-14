#!/usr/bin/env python3
"""
wxml2html.py — Convert a WeChat Mini Program page (WXML + WXSS) to a standalone HTML preview.

Usage:
    python wxml2html.py <page.wxml> [options]

Options:
    --wxss <file>        WXSS stylesheet (default: same path with .wxss extension)
    --data <file.json>   Mock page-data JSON to resolve {{expressions}}
    --out <file.html>    Output HTML path (default: same path with .html extension)
    --title <text>       Preview title

The converter handles:
    <view>/<text>/<image>/<button>/<scroll-view>/<swiper>  -> div/span/img equivalents
    wx:for / wx:if / wx:elif / wx:else / wx:key            -> rendered with mock data
    {{ expr }}                                              -> evaluated against page data
    rpx units                                               -> px (divided by 2)
"""
import argparse
import json
import os
import re
import sys

try:
    from bs4 import BeautifulSoup, NavigableString
except ImportError:
    sys.stderr.write("Need bs4. Install with: pip install beautifulsoup4 lxml\n")
    sys.exit(1)

TAG_MAP = {
    "view": "div",
    "text": "span",
    "image": "img",
    "button": "button",
    "scroll-view": "div",
    "swiper": "div",
    "swiper-item": "div",
    "navigator": "a",
    "block": None,  # unwrap
    "input": "input",
    "textarea": "textarea",
    "icon": "i",
}

SELF_CLOSE = {"image", "img", "input"}


def resolve(path_expr, ctx):
    """Resolve a simple dotted/indexed expression like products[0].name against ctx."""
    if path_expr.strip() == "":
        return ""
    expr = path_expr.strip()
    # unwrap full mustache: "{{products}}" -> "products"
    m = re.fullmatch(r"\{\{([^}]+)\}\}", expr)
    if m:
        expr = m.group(1).strip()
    if expr in ("true", "false"):
        return expr == "true"
    # string literal
    if (expr.startswith("'") and expr.endswith("'")) or (expr.startswith('"') and expr.endswith('"')):
        return expr[1:-1]
    # number
    try:
        return int(expr) if "." not in expr else float(expr)
    except ValueError:
        pass
    # ternary a ? b : c  (simple, no nested)
    m = re.match(r"^(.+?)\?(.+?):(.+)$", expr)
    if m and "?" in expr and ":" in expr:
        cond = resolve(m.group(1), ctx)
        if isinstance(cond, str):
            truthy = cond.strip() not in ("", "false", "0", "None")
        elif cond is None:
            truthy = False
        else:
            truthy = bool(cond)
        return resolve(m.group(2) if truthy else m.group(3), ctx)
    # comparison == / !=
    for op in ("===", "!==", "==", "!="):
        if op in expr:
            a, b = [s.strip() for s in expr.split(op, 1)]
            va, vb = resolve(a, ctx), resolve(b, ctx)
            eq = str(va) == str(vb)
            if op in ("==", "==="):
                return eq
            else:
                return not eq
    # template string a + b
    if "+" in expr:
        parts = [str(resolve(p, ctx)) for p in expr.split("+")]
        return "".join(parts)
    # dotted/indexed path
    cur = ctx
    for token in re.findall(r"[^.\[\]]+|\[\s*[^\]]*\s*\]", expr):
        if token.startswith("["):
            key = resolve(token.strip("[]"), ctx)
            try:
                cur = cur[int(key)]
            except Exception:
                return ""
        else:
            if isinstance(cur, dict) and token in cur:
                cur = cur[token]
            else:
                return ""
    return cur


def render_mustache(text, ctx):
    return re.sub(
        r"\{\{([^}]+)\}\}",
        lambda m: str(resolve(m.group(1), ctx)),
        text,
    )


def get_scope(el):
    return getattr(el, "_scope", None)


def truthy(v):
    if isinstance(v, str):
        return v.strip() not in ("", "false", "0", "None")
    if v is None:
        return False
    return bool(v)


def convert(wxml_text, data):
    soup = BeautifulSoup(wxml_text, "lxml")
    root = soup.body if soup.body else soup
    # inject root scope on first processing pass — process recursively
    process_children(root, dict(data))
    return str(soup)


def process_children(parent, scope):
    # iterate over snapshot of children since we mutate
    for child in list(parent.children):
        process_node(child, parent, scope)


def process_node(node, parent, scope):
    if isinstance(node, NavigableString):
        new_text = render_mustache(str(node), scope)
        if new_text != str(node):
            node.replace_with(NavigableString(new_text))
        return

    if node.name is None:  # comment / doctype
        return

    # wx:for — process on the node itself, generating clones
    if "wx:for" in node.attrs:
        # unwrap block-with-wx:for: move wx:for onto a temporary handling —
        # simplest: if node is a block, rename to span-marker div then continue normal path
        if node.name == "block":
            node.name = "div"
        items = resolve(node.attrs["wx:for"][0] if isinstance(node.attrs["wx:for"], list) else node.attrs["wx:for"], scope)
        if not isinstance(items, list):
            items = []
        item_name = (node.attrs.get("wx:for-item") or ["item"])[0] if isinstance(node.attrs.get("wx:for-item"), list) else node.attrs.get("wx:for-item", "item")
        index_name = (node.attrs.get("wx:for-index") or ["index"])[0] if isinstance(node.attrs.get("wx:for-index"), list) else node.attrs.get("wx:for-index", "index")
        import copy
        clones = []
        was_block = node.name == "block"  # already renamed to div above
        for idx, item in enumerate(items):
            clone = copy.copy(node)
            child_scope = dict(scope)
            child_scope[item_name] = item
            child_scope[index_name] = idx
            finish_clone(clone, child_scope)
            if was_block:
                # loop root was <block>: splice its children directly
                inner = list(clone.children)
                if inner:
                    clones.extend(inner)
                continue
            clones.append(clone)
        # insert clones before the original while it is still attached, then remove original
        for c in clones:
            node.insert_before(c)
        node.extract()
        return

    # wx:if / wx:elif / wx:else
    for cond_attr in ("wx:if", "wx:elif"):
        if cond_attr in node.attrs:
            val = node.attrs[cond_attr]
            val = val[0] if isinstance(val, list) else val
            if not truthy(resolve(val, scope)):
                node.extract()
                return
            del node.attrs[cond_attr]

    # unwrap "block" tags but keep children
    if node.name == "block":
        # process children in current scope, then unwrap
        process_children(node, scope)
        node.unwrap()
        return

    # normal element: rename tag, handle attrs
    new_tag = TAG_MAP.get(node.name, node.name)

    # image -> img with src attribute mapping
    if node.name == "image":
        node.name = "img"
        if "src" in node.attrs:
            src = node.attrs["src"]
            src = src[0] if isinstance(src, list) else src
            node.attrs["src"] = render_mustache(src, scope)
        mode = node.attrs.pop("mode", None)
    else:
        if new_tag and node.name != new_tag:
            node.name = new_tag

    # render mustache in attributes (class, style, etc.)
    for attr in list(node.attrs.keys()):
        if attr.startswith("wx:"):
            del node.attrs[attr]
            continue
        if attr.startswith("bind") or attr.startswith("catch") or attr.startswith("data-"):
            del node.attrs[attr]
            continue
        val = node.attrs[attr]
        vals = val if isinstance(val, list) else [val]
        node.attrs[attr] = [render_mustache(v, scope) for v in vals]

    # class attr special: wx: class="{{cond?'active':''}}" already handled by mustache render above.

    # process children in a child scope equal to current scope
    process_children(node, scope)


def finish_clone(clone, child_scope):
    # recursively rename tags and strip wx: directives inside the clone
    _preprocess_clone(clone)
    render_clone_inplace(clone, child_scope)


def _preprocess_clone(node):
    if isinstance(node, NavigableString) or node.name is None:
        return
    # rename tag mapping (image->img, view->div, block->unwrap)
    if node.name == "block":
        for child in list(node.children):
            _preprocess_clone(child)
        # safe unwrap for detached trees: replace with children
        for child in list(node.children):
            node.insert_before(child)
        node.extract()
        return
    new_tag = TAG_MAP.get(node.name, node.name)
    if node.name == "image":
        node.name = "img"
    elif new_tag and node.name != new_tag:
        node.name = new_tag
    for attr in list(node.attrs.keys()):
        if attr.startswith("bind") or attr.startswith("catch") or attr.startswith("data-") or attr.startswith("wx:"):
            del node.attrs[attr]
    for child in list(node.children):
        _preprocess_clone(child)


def render_clone_inplace(node, scope):
    if isinstance(node, NavigableString):
        node.replace_with(NavigableString(render_mustache(str(node), scope)))
        return
    if node.name is None:
        return
    for attr in list(node.attrs.keys()):
        if attr.startswith("wx:"):
            if attr != "wx:key":
                del node.attrs[attr]
            continue
        val = node.attrs[attr]
        vals = val if isinstance(val, list) else [val]
        node.attrs[attr] = [render_mustache(v, scope) for v in vals]
    for child in list(node.children):
        render_clone_inplace(child, scope)


def wxss_to_css(wxss_text):
    # naive rpx -> px conversion, page selector -> body
    css = wxss_text
    css = re.sub(r"(\d+(?:\.\d+)?)rpx", lambda m: f"{float(m.group(1)) / 2:.1f}px", css)
    css = re.sub(r"(^|[\s,{])page\b", r"\1.phone-body", css)
    return css


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{ color-scheme: light; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #e8e8e8; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; display: flex; justify-content: center; padding: 30px 10px; }}
.phone {{ width: 375px; background: #f5f5f5; border: 12px solid #222; border-radius: 44px; overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,.25); }}
.phone-header {{ background: #fff; text-align: center; padding: 14px 0 10px; font-size: 15px; font-weight: 600; border-bottom: 1px solid #eee; }}
.phone-body {{ height: 667px; overflow-y: auto; background: #f5f5f5; }}
img {{ max-width: 100%; display: block; }}
{css}
</style>
</head>
<body>
<div class="phone">
  <div class="phone-header">{title}</div>
  <div class="phone-body">
{body}
  </div>
</div>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wxml")
    ap.add_argument("--wxss")
    ap.add_argument("--data")
    ap.add_argument("--out")
    ap.add_argument("--title", default="小程序预览")
    args = ap.parse_args()

    wxml_path = args.wxml
    if not os.path.exists(wxml_path):
        sys.stderr.write(f"Not found: {wxml_path}\n")
        sys.exit(1)

    wxss_path = args.wxss or os.path.splitext(wxml_path)[0] + ".wxss"
    css = ""
    if os.path.exists(wxss_path):
        with open(wxss_path, "r", encoding="utf-8") as f:
            css = wxss_to_css(f.read())

    data = {}
    if args.data and os.path.exists(args.data):
        with open(args.data, "r", encoding="utf-8") as f:
            data = json.load(f)

    with open(wxml_path, "r", encoding="utf-8") as f:
        wxml_text = f.read()

    body_html = convert(wxml_text, data)

    out = args.out or os.path.splitext(wxml_path)[0] + "_preview.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(HTML_TEMPLATE.format(title=args.title, css=css, body=body_html))
    print(out)


if __name__ == "__main__":
    main()

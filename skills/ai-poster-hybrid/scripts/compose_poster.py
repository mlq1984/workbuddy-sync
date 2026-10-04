#!/usr/bin/env python3
"""compose_poster.py — 底图 + HTML 压字合成海报（poster-maker 渲染前自动内联 base64 底图）

用法:
  python compose_poster.py --html overlay.html --bg bg.png -o out.png [--width 1080 --height 1920]

说明:
  poster-maker (takumi) 不支持 file:/// 本地图片,直接引用会渲染出纯文字无底图。
  本脚本把 HTML 中 <img class="bg" src="__BG_IMAGE__">（或任意本地 src）替换为
  base64 data URI,再调 render.mjs 渲染,最后程序化校验成品确含底图。
"""
import argparse, base64, mimetypes, re, subprocess, sys
from pathlib import Path

RENDER_MJS = Path.home() / ".workbuddy/skills/poster-maker/scripts/render.mjs"
NODE = r"C:\Users\king\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"

def inline_bg(html_text: str, bg_path: Path) -> str:
    mime = mimetypes.guess_type(str(bg_path))[0] or "image/png"
    data = base64.b64encode(bg_path.read_bytes()).decode()
    uri = f"data:{mime};base64,{data}"
    if "__BG_IMAGE__" in html_text:
        return html_text.replace("__BG_IMAGE__", str(bg_path.resolve().as_uri())).replace(str(bg_path.resolve().as_uri()), uri)
    # 替换 img.bg 或任意本地 file/相对路径 src
    def repl(m):
        src = m.group(2)
        if src.startswith("data:"):
            return m.group(0)
        p = Path(src.replace("file:///", "").replace("file://", "/").lstrip("/"))
        if not p.exists():
            p = (bg_path.parent / src).resolve()
        if p.exists():
            m2 = mimetypes.guess_type(str(p))[0] or "image/png"
            d = base64.b64encode(p.read_bytes()).decode()
            return f'{m.group(1)}src="data:{m2};base64,{d}"'
        return m.group(0)
    return re.sub(r'(<img[^>]*?)src="([^"]+)"', repl, html_text)

def verify(out_png: Path, bg_png: Path) -> bool:
    try:
        import numpy as np
        from PIL import Image
        fg = np.array(Image.open(out_png).convert("RGB").resize((216, 384)))
        bg = np.array(Image.open(bg_png).convert("RGB").resize((216, 384)))
        box = (slice(180, 300), slice(60, 160))
        diff = np.abs(fg[box].astype(int) - bg[box].astype(int)).mean()
        print(f"[verify] 中部区域底图/成品平均色差: {diff:.1f} (应 <80；越大越可能缺底图)")
        return diff < 80
    except ImportError:
        print("[verify] 无 numpy/Pillow，跳过像素校验；请检查成品文件大小(带底图通常 >300KB)")
        return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--bg", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--width", default="1080")
    ap.add_argument("--height", default="1920")
    a = ap.parse_args()

    html_path = Path(a.html)
    text = html_path.read_text(encoding="utf-8")
    inlined = inline_bg(text, Path(a.bg))
    tmp = html_path.with_name(html_path.stem + ".inlined.html")
    tmp.write_text(inlined, encoding="utf-8")

    r = subprocess.run([NODE, str(RENDER_MJS), "--html", str(tmp), "-o", a.out,
                        "--width", a.width, "--height", a.height],
                       capture_output=True, text=True)
    if r.returncode != 0 or not Path(a.out).exists():
        print(r.stdout, r.stderr); sys.exit(1)
    ok = verify(Path(a.out), Path(a.bg))
    print(("✅" if ok else "⚠️"), a.out)
    sys.exit(0 if ok else 2)

if __name__ == "__main__":
    main()

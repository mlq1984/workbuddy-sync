#!/usr/bin/env python3
"""extract_gold_title.py — 从深红底 AI 烫金书法图抠出透明标题 PNG

用法:
  python extract_gold_title.py <输入.png> <输出.png>

配套生成 prompt 模板（ImageGen，必须纯色深红底才能色键抠图）:
  Magnificent Chinese brush calligraphy of the four characters "XXXX" written in
  powerful bold cursive brushstroke style, luxurious molten gold metallic 3D letters
  with realistic gold reflections, beveled edges and feibai dry-brush texture, ink
  splatter accents in deep red around strokes, on a clean solid dark crimson red
  background (#8B0D0D), horizontal composition centered, the four characters clearly
  readable in correct traditional calligraphy order, premium title design, dramatic
  lighting, ultra high detail, no other text, no watermark.

注意: AI 生成的中文字形可能出错，产出后必须人工验字！
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter


def extract(src: Path, dst: Path):
    img = Image.open(src).convert("RGB")
    a = np.array(img).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    # 金色判据: 亮度高 + 绿色通道不为零(排除纯红背景) + 红蓝差(排除灰白)
    gold = (a.max(axis=2) > 120) & (g > 60) & (r - b > 20)
    mask = Image.fromarray((gold * 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.GaussianBlur(1.5))
    mask = mask.point(lambda p: 255 if p > 100 else (int(p * 2) if p > 40 else 0))
    rgba = img.convert("RGBA")
    rgba.putalpha(mask)
    bbox = mask.getbbox()
    if not bbox:
        print("未检出金色内容，请确认背景为纯色深红且文字为金色")
        sys.exit(1)
    rgba.crop(bbox).save(dst)
    print("saved:", dst, rgba.crop(bbox).size)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    extract(Path(sys.argv[1]), Path(sys.argv[2]))

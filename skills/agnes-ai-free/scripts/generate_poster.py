#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
海报全链路生成脚本（基于 agnes-ai-free 技能）
流程：文案生成(agnes-3.0-flash) → 图像生成(agnes-image-2.5-flash) → HTML排版 → JPG交付
"""

import os
import sys
import json
import base64
import time
from pathlib import Path
from typing import Literal

# 添加技能脚本目录到路径
SKILL_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from agnes_client import AgnesClient, create_client

OUTPUT_DIR = Path("poster_output")
OUTPUT_DIR.mkdir(exist_ok=True)

TEMPLATES_DIR = SKILL_DIR / "assets/templates"
FINAL_WIDTH = 1080
FINAL_HEIGHT = 1920
DEVICE_SCALE = 2  # 视网膜级 2x


def load_template(template_name: str) -> str:
    """加载 HTML 模板"""
    template_path = TEMPLATES_DIR / f"{template_name}.html"
    if not template_path.exists():
        raise FileNotFoundError(f"模板不存在: {template_path}")
    return template_path.read_text(encoding="utf-8")


def render_template(template_name: str, base_image_bytes: bytes, copy_data: dict) -> str:
    """渲染 HTML 模板，返回完整 HTML 字符串"""
    html = load_template(template_name)
    
    # 底图转 base64
    b64_img = base64.b64encode(base_image_bytes).decode()
    img_uri = f"data:image/jpeg;base64,{b64_img}"
    
    # 卖点 HTML
    sp_html = ""
    for sp in copy_data.get("selling_points", []):
        main = sp.get("main", "")
        sub = sp.get("sub", "")
        if template_name == "beauty":
            sp_html += f"""
            <div class="selling-point">
                <span class="sp-icon">◦</span>
                <div class="sp-text">
                    <div class="sp-main">{main}</div>
                    <div class="sp-sub">{sub}</div>
                </div>
            </div>"""
        elif template_name == "minimal":
            sp_html += f'<div class="sp">{main}{" | " + sub if sub else ""}</div>'
        else:
            # festival 模板不显示 selling_points 区域
            pass
    
    # 替换占位符
    replacements = {
        "{{BASE_IMAGE_URI}}": img_uri,
        "{{TITLE}}": copy_data.get("title", ""),
        "{{SUBTITLE}}": copy_data.get("subtitle", ""),
        "{{SLOGAN}}": copy_data.get("slogan", ""),
        "{{SELLING_POINTS_HTML}}": sp_html,
        "{{QUOTE_SLOGAN}}": copy_data.get("slogan", ""),
        "{{DIVIDER_EN}}": copy_data.get("divider_en", "BEAUTY & SCIENCE"),
        "{{CTA_TEXT}}": copy_data.get("cta", "立即咨询"),
        "{{CONTACT_INFO}}": copy_data.get("contact", ""),
    }
    
    for k, v in replacements.items():
        html = html.replace(k, v)
    
    return html


def render_with_playwright(html: str, output_path: Path):
    """用 Playwright 渲染 HTML 为高质量 JPG"""
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": FINAL_WIDTH, "height": FINAL_HEIGHT},
            device_scale_factor=DEVICE_SCALE
        )
        page.set_content(html, wait_until="networkidle")
        page.wait_for_timeout(2000)  # 等待字体加载
        page.screenshot(path=str(output_path), type="jpeg", quality=95, full_page=True)
        browser.close()
    
    print(f"  🎨 排版完成: {output_path.name} ({output_path.stat().st_size/1024:.1f} KB)")


def generate_poster(
    theme: str,
    style: Literal["beauty", "festival", "minimal"] = "beauty",
    brand: str = "",
    product: str = "",
    extra_context: str = "",
    size: str = "2K",
    ratio: str = "9:16",
    api_key: str = None,
) -> Path:
    """一键生成海报完整流程"""
    
    print(f"\n{'='*60}")
    print(f"🎯 海报生成: {theme} [{style}]")
    print(f"{'='*60}")
    
    client = create_client(api_key)
    
    # 1. 文案生成
    print("\n📝 步骤 1/3: 文案生成 (agnes-3.0-flash)...")
    copy_result = client.generate_poster_copy(theme, style=style, brand=brand, product=product, extra_context=extra_context)
    if not copy_result.ok:
        raise RuntimeError(f"文案生成失败: {copy_result.error}")
    
    copy_data = copy_result.data
    print(f"   ✅ 标题: {copy_data['title']}")
    print(f"   ✅ 图像提示词: {copy_data['image_prompt'][:80]}...")
    
    # 2. 图像生成
    print(f"\n🖼️ 步骤 2/3: 图像生成 (agnes-image-2.5-flash, {size} {ratio})...")
    img_result = client.generate_image(
        prompt=copy_data["image_prompt"],
        size=size,
        ratio=ratio
    )
    if not img_result.ok:
        raise RuntimeError(f"图像生成失败: {img_result.error}")
    
    img_bytes = img_result.data
    img_info = img_result.raw
    print(f"   ✅ 尺寸: {img_info.get('size', 'unknown')}")
    
    # 3. 排版合成
    print("\n🎨 步骤 3/3: HTML/CSS 排版合成...")
    html = render_template(style, img_bytes, copy_data)
    
    timestamp = int(time.time())
    output_path = OUTPUT_DIR / f"poster_{style}_{timestamp}.jpg"
    render_with_playwright(html, output_path)
    
    print(f"\n✅ 海报生成完成!")
    print(f"   📁 文件: {output_path}")
    print(f"   📐 规格: {FINAL_WIDTH*DEVICE_SCALE}x{FINAL_HEIGHT*DEVICE_SCALE} (交付 {FINAL_WIDTH}x{FINAL_HEIGHT} @2x)")
    
    return output_path


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="海报全链路生成 (agnes-ai-free skill)")
    parser.add_argument("--theme", required=True, help="海报主题")
    parser.add_argument("--style", choices=["beauty", "festival", "minimal"], default="beauty")
    parser.add_argument("--brand", default="")
    parser.add_argument("--product", default="")
    parser.add_argument("--extra", default="")
    parser.add_argument("--size", choices=["1K", "2K", "3K", "4K"], default="2K")
    parser.add_argument("--ratio", choices=["1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"], default="9:16")
    parser.add_argument("--api-key", default=None)
    
    args = parser.parse_args()
    
    try:
        out = generate_poster(
            theme=args.theme,
            style=args.style,
            brand=args.brand,
            product=args.product,
            extra_context=args.extra,
            size=args.size,
            ratio=args.ratio,
            api_key=args.api_key,
        )
        print(f"\n🎉 完成! {out}")
    except Exception as e:
        print(f"\n❌ 失败: {e}")
        sys.exit(1)
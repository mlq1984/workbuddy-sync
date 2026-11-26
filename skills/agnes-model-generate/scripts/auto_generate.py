#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agnes AI 模型自动生成 - 用户交互层脚本
自动组合 agnes-ai-free 技能的能力，提供自然语言交互入口
"""

import sys
import os
import json
import re
from pathlib import Path
from typing import Literal, Optional

# 添加 agnes-ai-free 技能路径
FREE_SKILL_DIR = Path(__file__).parent.parent.parent / "agnes-ai-free"
sys.path.insert(0, str(FREE_SKILL_DIR / "scripts"))

from agnes_client import AgnesClient, create_client
from generate_poster import generate_poster, load_template, render_template, render_with_playwright

OUTPUT_DIR = Path("poster_output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ===================== 自动风格识别 =====================
def detect_style(user_input: str) -> Literal["beauty", "festival", "minimal"]:
    """根据用户输入自动识别推荐风格"""
    input_lower = user_input.lower()
    
    # 节庆/国潮关键词
    festival_keywords = [
        "春节", "中秋", "国庆", "端午", "元旦", "情人节", "圣诞", "万圣节",
        "节日", "国潮", "传统", "佳节", "庆祝", "祝贺", "贺岁",
        "除夕", "年夜饭", "红包", "灯笼", "烟花", "喜庆"
    ]
    
    # 极简/现代/科技关键词
    minimal_keywords = [
        "极简", "现代", "科技", "商务", "简约", "高端", "品牌", "国际",
        "留白", "无衬线", "几何", "扁平", "miui", "ios", "苹果风",
        "极简主义", "less is more", "minimal", "clean", "tech"
    ]
    
    # 美业/护肤关键词（默认）
    beauty_keywords = [
        "护肤", "美容", "医美", "美白", "补水", "抗衰", "年轻", "面膜",
        "精华", "乳液", "面霜", "洗面奶", "防晒", "眼霜", "精油",
        "敏感肌", "干皮", "油皮", "混干", "混油", "产后", "孕妇",
        "美业", "美容院", "皮肤管理", "光子", "热玛吉", "超声炮",
        "玻尿酸", "胶原蛋白", "胜肽", "维A醇", "烟酰胺", "VC",
        "发布", "新品", "上市", "体验装", "试用", "领取"
    ]
    
    # 优先级：节庆 > 极简 > 美业(默认)
    for kw in festival_keywords:
        if kw in input_lower:
            return "festival"
    
    for kw in minimal_keywords:
        if kw in input_lower:
            return "minimal"
    
    for kw in beauty_keywords:
        if kw in input_lower:
            return "beauty"
    
    return "beauty"  # 默认


def extract_info(user_input: str) -> dict:
    """从用户输入中提取结构化信息"""
    info = {
        "theme": "",
        "brand": "官方",
        "product": "",
        "extra": "",
        "style": "beauty"
    }
    
    # 简单提取：品牌、产品、主题
    # 这里用简单规则，实际可用 LLM 做 NER
    
    # 品牌模式：品牌是 xxx / 品牌叫 xxx / 是 xxx 的
    brand_match = re.search(r'品牌(?:是|叫|为)\s*([^，,。\s]{2,20})', user_input)
    if brand_match:
        info["brand"] = brand_match.group(1).strip()
    
    # 产品模式：产品是 xxx / 主打 xxx / 售卖 xxx
    product_match = re.search(r'(?:产品|主打|售卖|推广)(?:是|为|叫)\s*([^，,。\s]{2,30})', user_input)
    if product_match:
        info["product"] = product_match.group(1).strip()
    
    # 补充信息：适合 xxx / 适用 xxx / 核心成分 xxx
    extra_matches = re.findall(r'(?:适合|适用|核心成分|成分|功效|针对)\s*([^，,。\s]{2,30})', user_input)
    if extra_matches:
        info["extra"] = "，".join(extra_matches[:3])
    
    # 主题：生成 xxx 海报 / 做 xxx
    theme_match = re.search(r'(?:生成|做|制作|创作)(?:一张|一个)?\s*([^，,。\s]{2,30})(?:海报|图|图片|配图)', user_input)
    if not theme_match:
        theme_match = re.search(r'(?:主题|内容)(?:是|为|叫)\s*([^，,。\s]{2,30})', user_input)
    if not theme_match:
        # 兜底：取前 20 字符作为主题
        clean = re.sub(r'(?:生成|做|制作|创作|海报|图片|配图|一张|一个|帮我|请|给我)', '', user_input).strip()
        if clean:
            info["theme"] = clean[:30]
    else:
        info["theme"] = theme_match.group(1).strip()
    
    # 自动识别风格
    info["style"] = detect_style(user_input)
    
    return info


# ===================== 核心生成流程 =====================
def auto_generate_poster(user_input: str, api_key: str = None) -> dict:
    """
    一键生成海报：从用户自然语言输入到最终 JPG
    返回: {success, output_path, copy_data, error}
    """
    print(f"🎯 收到需求: {user_input}")
    
    # 1. 解析用户输入
    info = extract_info(user_input)
    print(f"   📋 解析结果: 主题={info['theme']}, 品牌={info['brand']}, 产品={info['product']}, 风格={info['style']}")
    
    if not info["theme"]:
        return {"success": False, "error": "无法识别主题，请明确说明要生成什么内容的海报"}
    
    try:
        # 2. 调用完整流程（文案 + 图像 + 排版）
        client = create_client(api_key)
        
        # 2.1 生成文案
        print("   📝 正在生成文案...")
        copy_result = client.generate_poster_copy(
            theme=info["theme"],
            style=info["style"],
            brand=info["brand"],
            product=info["product"],
            extra_context=info["extra"]
        )
        if not copy_result.ok:
            return {"success": False, "error": f"文案生成失败: {copy_result.error}"}
        
        copy_data = copy_result.data
        print(f"      ✅ 标题: {copy_data['title']}")
        
        # 2.2 生成图像
        print("   🖼️ 正在生成底图...")
        img_result = client.generate_image(
            prompt=copy_data["image_prompt"],
            size="2K",
            ratio="9:16"
        )
        if not img_result.ok:
            return {"success": False, "error": f"图像生成失败: {img_result.error}"}
        
        img_bytes = img_result.data
        print(f"      ✅ 尺寸: {img_result.raw.get('size', '1472x2624')}")
        
        # 2.3 排版合成
        print("   🎨 正在排版合成...")
        html = render_template(info["style"], img_bytes, copy_data)
        
        import time
        timestamp = int(time.time())
        output_path = OUTPUT_DIR / f"poster_{info['style']}_{timestamp}.jpg"
        render_with_playwright(html, output_path)
        
        print(f"   ✅ 完成: {output_path}")
        
        return {
            "success": True,
            "output_path": str(output_path),
            "copy_data": copy_data,
            "style": info["style"],
            "size": "1080x1920@2x"
        }
        
    except Exception as e:
        return {"success": False, "error": f"生成过程异常: {str(e)}"}


def auto_generate_copy(user_input: str, api_key: str = None) -> dict:
    """仅生成文案（不生成图片、不排版）"""
    info = extract_info(user_input)
    
    if not info["theme"]:
        return {"success": False, "error": "无法识别主题"}
    
    client = create_client(api_key)
    copy_result = client.generate_poster_copy(
        theme=info["theme"],
        style=info["style"],
        brand=info["brand"],
        product=info["product"],
        extra_context=info["extra"]
    )
    
    if copy_result.ok:
        return {"success": True, "copy_data": copy_result.data}
    return {"success": False, "error": copy_result.error}


def auto_generate_image(prompt: str, size: str = "2K", ratio: str = "9:16", api_key: str = None) -> dict:
    """直接生成图片（不生成文案、不排版）"""
    client = create_client(api_key)
    img_result = client.generate_image(prompt=prompt, size=size, ratio=ratio)
    
    if img_result.ok:
        import time
        timestamp = int(time.time())
        out_path = OUTPUT_DIR / f"image_{timestamp}.jpg"
        out_path.write_bytes(img_result.data)
        return {"success": True, "output_path": str(out_path), "size": img_result.raw.get('size')}
    return {"success": False, "error": img_result.error}


# ===================== CLI 入口 =====================
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Agnes AI 模型自动生成 - 用户交互层")
    parser.add_argument("input", nargs="?", help="用户需求（自然语言）")
    parser.add_argument("--mode", choices=["poster", "copy", "image"], default="poster")
    parser.add_argument("--prompt", help="直接指定图像提示词（image 模式用）")
    parser.add_argument("--size", choices=["1K", "2K", "3K", "4K"], default="2K")
    parser.add_argument("--ratio", choices=["1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"], default="9:16")
    parser.add_argument("--api-key", default=None)
    
    args = parser.parse_args()
    
    if args.mode == "poster":
        if not args.input:
            parser.error("poster 模式需要提供用户需求")
        result = auto_generate_poster(args.input, args.api_key)
    elif args.mode == "copy":
        if not args.input:
            parser.error("copy 模式需要提供用户需求")
        result = auto_generate_copy(args.input, args.api_key)
    elif args.mode == "image":
        if not args.prompt:
            parser.error("image 模式需要提供 --prompt")
        result = auto_generate_image(args.prompt, args.size, args.ratio, args.api_key)
    
    if result.get("success"):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"❌ 失败: {result.get('error')}")
        sys.exit(1)
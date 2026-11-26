#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agnes AI 免费模型统一客户端
支持: 文本(agnes-3.0-flash)、图像(agnes-image-2.5-flash)、视频(agnes-video-2.5-flash)
内置: 重试、降级、参数规范化、统一返回格式
"""

import os
import json
import time
import requests
from dataclasses import dataclass
from typing import Optional, Literal, Any
from pathlib import Path
from enum import Enum

# ===================== 常量配置 =====================
BASE_URL = "https://apihub.agnes-ai.com/v1"
DEFAULT_API_KEY = "sk-nNWR2IFP4dZnc3qFmvneQXMkWuu8yEmUQ5Uldf1UPiz4MNCD"

# 免费模型 ID
class Model(Enum):
    TEXT = "agnes-3.0-flash"
    IMAGE = "agnes-image-2.5-flash"
    VIDEO = "agnes-video-2.5-flash"

# 图像尺寸档位
IMAGE_SIZES = {
    "1K":  {"1:1": (1024, 1024), "3:4": (864, 1152), "4:3": (1152, 864), "16:9": (1312, 736), "9:16": (736, 1312), "2:3": (832, 1248), "3:2": (1248, 832), "21:9": (1568, 672)},
    "2K":  {"1:1": (2048, 2048), "3:4": (1728, 2304), "4:3": (2304, 1728), "16:9": (2624, 1472), "9:16": (1472, 2624), "2:3": (1664, 2496), "3:2": (2496, 1664), "21:9": (3136, 1344)},
    "3K":  {"1:1": (3072, 3072), "3:4": (2592, 3456), "4:3": (3456, 2592), "16:9": (3936, 2208), "9:16": (2208, 3936), "2:3": (2496, 3744), "3:2": (3744, 2496), "21:9": (4704, 2016)},
    "4K":  {"1:1": (4096, 4096), "3:4": (3456, 4608), "4:3": (4608, 3456), "16:9": (5248, 2944), "9:16": (2944, 5248), "2:3": (3328, 4992), "3:2": (4992, 3328), "21:9": (6272, 2688)},
}

# 视频分辨率
VIDEO_SIZES = ["720P", "1080P", "1K", "2K"]
VIDEO_MODES = ["text", "keyframe", "reference"]
VIDEO_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]

# 重试配置
MAX_RETRIES = 3
BASE_DELAY = 2
TIMEOUT = 180

# ===================== 数据结构 =====================
@dataclass
class AgnesResponse:
    success: bool
    data: Any = None
    error: str = ""
    channel: str = ""
    raw: Any = None

    @property
    def ok(self) -> bool:
        return self.success


# ===================== 核心客户端 =====================
class AgnesClient:
    """Agnes AI 免费模型统一调用客户端"""

    def __init__(self, api_key: str = None, base_url: str = BASE_URL):
        self.api_key = api_key or DEFAULT_API_KEY
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    # ---------- 通用重试装饰器 ----------
    def _retry_request(self, func, *args, **kwargs) -> AgnesResponse:
        last_error = ""
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except requests.exceptions.Timeout:
                last_error = f"请求超时 ({TIMEOUT}s)"
            except requests.exceptions.ConnectionError as e:
                last_error = f"连接失败: {e}"
            except requests.exceptions.HTTPError as e:
                last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                if e.response.status_code in (401, 403, 404):
                    break  # 不重试认证/路径错误
            except Exception as e:
                last_error = f"未知错误: {e}"

            if attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt)
                print(f"  ⚠️ 第 {attempt+1} 次失败: {last_error}，{delay}s 后重试...")
                time.sleep(delay)

        return AgnesResponse(success=False, error=last_error, channel="agnes")

    # ---------- 1. 文本生成 ----------
    def generate_text(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        json_mode: bool = False,
        model: str = Model.TEXT.value
    ) -> AgnesResponse:
        """调用文本模型 (agnes-3.0-flash)"""

        def _call():
            payload = {
                "model": model,
                "messages": [],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if system_prompt:
                payload["messages"].append({"role": "system", "content": system_prompt})
            payload["messages"].append({"role": "user", "content": prompt})

            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            resp = self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            if json_mode:
                content = json.loads(content)

            return AgnesResponse(success=True, data=content, channel="agnes-text", raw=data)

        return self._retry_request(_call)

    # ---------- 2. 图像生成 ----------
    def generate_image(
        self,
        prompt: str,
        size: str = "2K",
        ratio: str = "9:16",
        model: str = Model.IMAGE.value,
        reference_images: list[str] = None,
        return_base64: bool = False
    ) -> AgnesResponse:
        """
        调用图像模型 (agnes-image-2.5-flash)
        :param prompt: 英文提示词
        :param size: 档位 1K/2K/3K/4K
        :param ratio: 宽高比 1:1/3:4/4:3/16:9/9:16/2:3/3:2/21:9
        :param reference_images: 图生图/多图合成时的参考图 URL 列表
        :param return_base64: 是否返回 base64 (文生图用 return_base64=True，图生图用 extra_body.response_format)
        :return: AgnesResponse.data = image_bytes (bytes)
        """

        def _call():
            # 验证参数
            if size not in IMAGE_SIZES:
                raise ValueError(f"不支持的 size: {size}，可选: {list(IMAGE_SIZES.keys())}")
            if ratio not in IMAGE_SIZES[size]:
                raise ValueError(f"该 size 不支持 ratio: {ratio}，可选: {list(IMAGE_SIZES[size].keys())}")

            w, h = IMAGE_SIZES[size][ratio]
            print(f"  📐 目标尺寸: {w}x{h} ({size} {ratio})")

            payload = {
                "model": model,
                "prompt": prompt,
                "size": size,
                "ratio": ratio,
                "extra_body": {
                    "response_format": "b64_json" if return_base64 else "url"
                }
            }

            if reference_images:
                payload["extra_body"]["image"] = reference_images

            resp = self.session.post(
                f"{self.base_url}/images/generations",
                json=payload,
                timeout=TIMEOUT
            )
            resp.raise_for_status()
            data = resp.json()

            # 下载图片
            if return_base64:
                b64 = data["data"][0]["b64_json"]
                img_bytes = base64.b64decode(b64)
            else:
                img_url = data["data"][0]["url"]
                img_resp = requests.get(img_url, timeout=60)
                img_resp.raise_for_status()
                img_bytes = img_resp.content

            return AgnesResponse(
                success=True,
                data=img_bytes,
                channel="agnes-image",
                raw={"url": data["data"][0].get("url"), "size": f"{w}x{h}", "task_id": data.get("task_id")}
            )

        return self._retry_request(_call)

    # ---------- 3. 视频生成 ----------
    def generate_video(
        self,
        prompt: str,
        mode: str = "text",
        seconds: str = "5",
        size: str = "720P",
        aspect_ratio: str = "16:9",
        first_frame: str = None,
        last_frame: str = None,
        reference_images: list[str] = None,
        reference_audios: list[str] = None,
        reference_videos: list[dict] = None,
        seed: int = None,
        model: str = Model.VIDEO.value
    ) -> AgnesResponse:
        """
        调用视频模型 (agnes-video-2.5-flash) - 异步任务
        :return: AgnesResponse.data = {"video_id": str, "task_id": str, "status": str, "video_url": str or None}
        """

        def _create_task():
            # 验证参数
            if mode not in VIDEO_MODES:
                raise ValueError(f"不支持的 mode: {mode}，可选: {VIDEO_MODES}")
            if size not in VIDEO_SIZES:
                raise ValueError(f"不支持的 size: {size}，可选: {VIDEO_SIZES}")
            if aspect_ratio not in VIDEO_RATIOS:
                raise ValueError(f"不支持的 aspect_ratio: {aspect_ratio}，可选: {VIDEO_RATIOS}")

            payload = {
                "model": model,
                "prompt": prompt,
                "mode": mode,
                "seconds": seconds,
                "size": size,
                "aspect_ratio": aspect_ratio,
            }
            if seed is not None:
                payload["seed"] = seed
            if mode == "keyframe":
                if first_frame:
                    payload["first_frame"] = first_frame
                if last_frame:
                    payload["last_frame"] = last_frame
            elif mode == "reference":
                if reference_images:
                    payload["images"] = reference_images
                if reference_audios:
                    payload["audios"] = reference_audios
                if reference_videos:
                    payload["videos"] = reference_videos

            resp = self.session.post(
                f"{self.base_url}/videos",
                json=payload,
                timeout=TIMEOUT
            )
            resp.raise_for_status()
            return resp.json()

        def _poll_result(video_id: str, task_id: str = None):
            # 推荐用 video_id 查询
            poll_url = f"{self.base_url.replace('/v1', '')}/agnesapi"
            params = {"video_id": video_id, "model_name": model}
            # 兼容旧版 task_id
            if task_id and not video_id:
                params = {"task_id": task_id}

            for _ in range(120):  # 最多轮询 120 次 (约 2-4 分钟)
                resp = self.session.get(poll_url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                status = data.get("status") or data.get("data", {}).get("status")
                if status == "completed":
                    video_url = (
                        data.get("metadata", {}).get("url") or
                        data.get("data", {}).get("metadata", {}).get("url") or
                        data.get("video_url") or
                        data.get("data", {}).get("video_url")
                    )
                    return {"status": "completed", "video_url": video_url, "raw": data}
                elif status == "failed":
                    return {"status": "failed", "error": data.get("error", "生成失败"), "raw": data}

                time.sleep(2)

            return {"status": "timeout", "error": "轮询超时", "raw": None}

        # 创建任务
        create_result = self._retry_request(_create_task)
        if not create_result.ok:
            return create_result

        create_data = create_result.raw
        video_id = create_data.get("video_id") or create_data.get("id")
        task_id = create_data.get("task_id")

        if not video_id and not task_id:
            return AgnesResponse(success=False, error="创建任务未返回 video_id/task_id", channel="agnes-video")

        print(f"  🎬 任务创建成功: video_id={video_id}, task_id={task_id}")

        # 轮询结果
        poll_result = self._retry_request(_poll_result, video_id, task_id)
        if not poll_result.ok:
            return poll_result

        result_data = poll_result.data
        if result_data.get("status") != "completed":
            return AgnesResponse(success=False, error=result_data.get("error", "视频生成失败"), channel="agnes-video", raw=result_data.get("raw"))

        # 下载视频
        video_url = result_data["video_url"]
        print(f"  📥 下载视频: {video_url}")
        video_resp = requests.get(video_url, timeout=300)
        video_resp.raise_for_status()

        return AgnesResponse(
            success=True,
            data=video_resp.content,
            channel="agnes-video",
            raw={"video_url": video_url, "video_id": video_id, "task_id": task_id}
        )

    # ---------- 4. 海报文案生成 (专用) ----------
    def generate_poster_copy(
        self,
        theme: str,
        style: Literal["beauty", "festival", "minimal"] = "beauty",
        brand: str = "",
        product: str = "",
        extra_context: str = ""
    ) -> AgnesResponse:
        """
        一键生成海报完整文案（标题、副标、Slogan、卖点、CTA、图像提示词）
        :return: data = {title, subtitle, slogan, selling_points[], cta, contact, image_prompt}
        """

        prompts = {
            "beauty": f"""你是高端美业/护肤品牌的资深文案策划。为以下主题生成一套完整的海报文案，风格：米白柔光、左文右图、完整商业信息层级。

主题: {theme}
品牌: {brand}
产品: {product}
补充: {extra_context}

请输出严格 JSON，字段：
- title: 中文主标题（粗大，8-12字）
- subtitle: 小副标（细体，10-16字）
- slogan: 引号包裹的金句（15-25字）
- selling_points: 3-4条卖点，每条对象含 main(主标4-6字) 和 sub(副标8-12字)
- cta: 行动号召（4-6字）
- contact: 联系信息占位
- image_prompt: 英文图像生成提示词，结构=[主体]+[场景/环境]+[风格]+[光照]+[构图]+[质量要求]，体现"米白柔光、亚洲女性人像占右半脸部完整、左侧留白、绿叶白花大理石、金色细线、橄榄墨绿配色、no text" """,

            "festival": f"""你是节庆/国潮品牌的资深文案策划。为以下主题生成海报文案，风格：深红底、烫金毛笔书法、居中对称、传统节日氛围。

主题: {theme}
品牌: {brand}
产品: {product}
补充: {extra_context}

请输出严格 JSON，字段：
- title: 中文主标题（烫金书法感，6-10字）
- subtitle: 小副标（节日氛围，8-16字）
- slogan: 金句（12-20字）
- selling_points: 2-3条核心卖点，每条含 main/sub
- cta: 行动号召（4-8字）
- contact: 品牌署名
- image_prompt: 英文图像提示词，体现"深红背景、金色烟花/灯笼/祥云、电影级布光、对称构图、8k、no text" """,

            "minimal": f"""你是极简风格品牌的文案策划。生成简洁有力的海报文案。

主题: {theme}
品牌: {brand}
产品: {product}
补充: {extra_context}

请输出严格 JSON，字段：
- title: 主标题（简洁有力，6-10字）
- subtitle: 副标题（8-16字）
- slogan: 一句话金句（10-20字）
- selling_points: 2-3条核心点
- cta: 行动号召
- contact: 联系信息
- image_prompt: 英文提示词，极简留白风格 """
        }

        system_prompt = "你是专业商业文案策划，只输出有效 JSON，不加任何解释或 markdown 代码块。"
        prompt = prompts.get(style, prompts["beauty"])

        result = self.generate_text(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=1500,
            json_mode=True
        )

        if result.ok:
            # 确保字段完整
            data = result.data
            defaults = {
                "title": theme, "subtitle": "", "slogan": "",
                "selling_points": [], "cta": "立即咨询", "contact": "", "image_prompt": ""
            }
            for k, v in defaults.items():
                if k not in data or not data[k]:
                    data[k] = v
            result.data = data

        return result


# ===================== 便捷函数 =====================
def create_client(api_key: str = None) -> AgnesClient:
    """创建客户端实例"""
    return AgnesClient(api_key=api_key)


# ===================== CLI 测试 =====================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agnes AI 免费模型测试")
    parser.add_argument("--mode", choices=["text", "image", "video", "copy"], default="image")
    parser.add_argument("--prompt", default="A beautiful minimalist poster, soft ivory background, elegant composition, high quality commercial photography style, no text")
    parser.add_argument("--theme", default="国庆节庆祝")
    parser.add_argument("--style", choices=["beauty", "festival", "minimal"], default="festival")
    parser.add_argument("--size", default="2K")
    parser.add_argument("--ratio", default="9:16")
    parser.add_argument("--seconds", default="5")
    parser.add_argument("--video-size", default="720P")
    args = parser.parse_args()

    client = create_client()

    if args.mode == "text":
        print("📝 测试文本生成...")
        r = client.generate_text(args.prompt, json_mode=False)
        print(f"结果: {r.data if r.ok else r.error}")

    elif args.mode == "image":
        print(f"🖼️ 测试图像生成: {args.size} {args.ratio}")
        r = client.generate_image(args.prompt, size=args.size, ratio=args.ratio)
        if r.ok:
            out = Path(f"test_image_{args.size}_{args.ratio}.jpg")
            out.write_bytes(r.data)
            print(f"✅ 保存: {out} ({len(r.data)/1024:.1f} KB)")
        else:
            print(f"❌ {r.error}")

    elif args.mode == "video":
        print(f"🎬 测试视频生成: {args.video_size} {args.seconds}s")
        r = client.generate_video(args.prompt, size=args.video_size, seconds=args.seconds)
        if r.ok:
            out = Path(f"test_video_{args.video_size}_{args.seconds}s.mp4")
            out.write_bytes(r.data)
            print(f"✅ 保存: {out} ({len(r.data)/1024/1024:.1f} MB)")
        else:
            print(f"❌ {r.error}")

    elif args.mode == "copy":
        print(f"📋 测试海报文案生成: {args.theme} [{args.style}]")
        r = client.generate_poster_copy(args.theme, style=args.style)
        if r.ok:
            print(json.dumps(r.data, ensure_ascii=False, indent=2))
        else:
            print(f"❌ {r.error}")
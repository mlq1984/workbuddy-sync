---
name: agnes-ai-free
description: Agnes AI 免费模型统一调用技能。提供文本(agnes-3.0-flash)、图像(agnes-image-2.5-flash)、视频(agnes-video-2.5-flash)三大免费模型的标准化调用接口，含重试降级、参数规范化、结果统一格式。适用于海报生成、文案创作、短视频素材等全链路创意生产场景。
agent_created: true
---

# Agnes AI 免费模型统一调用技能

## 适用场景

- 需要调用 Agnes AI 免费模型进行文本生成、图像生成、视频生成
- 海报/配图/营销素材批量生产流水线
- 文案自动生成（标题、副标、卖点、Slogan）
- 短视频首帧/动态海报素材生成
- 多模态创意工作流（文本→图像→视频）

## 核心模型（均为天使用户体验价 $0）

| 模型 ID | 类型 | 端点 | 关键能力 | 免费额度 |
|---------|------|------|----------|----------|
| `agnes-3.0-flash` | 文本 | `/v1/chat/completions` | 聊天、推理、代码、结构化输出 | 输入/输出 Token 全免费 |
| `agnes-image-2.5-flash` | 图像 | `/v1/images/generations` | 文生图、图生图、多图合成、高信息密度 | 全分辨率(1K-4K)免费，含参考图 |
| `agnes-video-2.5-flash` | 视频 | `/v1/videos` + `/agnesapi` | 文生视频、关键帧控制、多模态参考 | 720P 限时免费 |

## 统一配置

```python
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}
API_KEY = "sk-nNWR2IFP4dZnc3qFmvneQXMkWuu8yEmUQ5Uldf1UPiz4MNCD"  # 内置默认 key
```

## 调用规范

### 1. 文本生成 (`agnes-3.0-flash`)

```python
payload = {
    "model": "agnes-3.0-flash",
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.7,
    "max_tokens": 2000,
    "response_format": {"type": "json_object"}  # 结构化输出时使用
}
POST /v1/chat/completions
```

**海报文案专用提示词模板**见 `references/poster_copy_prompts.md`

### 2. 图像生成 (`agnes-image-2.5-flash`)

```python
payload = {
    "model": "agnes-image-2.5-flash",
    "prompt": prompt,  # 必须用英文
    "size": "2K",       # 档位: 1K/2K/3K/4K
    "ratio": "9:16",    # 宽高比: 1:1/3:4/4:3/16:9/9:16/2:3/3:2/21:9
    "extra_body": {
        "response_format": "url",  # 或 "b64_json"
        "image": [...]  # 图生图/多图合成时必填，数组含 URL 或 Data URI
    }
}
POST /v1/images/generations
```

**尺寸对照表**见 `references/image_sizes.md`

### 3. 视频生成 (`agnes-video-2.5-flash`)

```python
# 创建任务
payload = {
    "model": "agnes-video-2.5-flash",
    "prompt": prompt,  # 英文
    "mode": "text",    # text/keyframe/reference
    "seconds": "5",    # "4"-"12"
    "size": "720P",    # 720P/1080P/1K/2K (flash 仅 720P 免费)
    "aspect_ratio": "16:9",  # 16:9/9:16/1:1/4:3/3:4/21:9
}
POST /v1/videos
# 返回含 video_id, task_id

# 轮询结果 (推荐用 video_id)
GET /agnesapi?video_id={video_id}&model_name=agnes-video-2.5-flash
# 直到 status=completed，取 metadata.url
```

## 重试与降级策略

内置脚本 `scripts/agnes_client.py` 实现：
- 指数退避重试 (3 次，2s/4s/8s)
- 通道失败自动降级（可扩展接入智谱/其他备选）
- 统一返回格式：`{"success": bool, "data": ..., "error": ..., "channel": ...}`

## 综合工作流示例

### 海报全自动生成（文案+图像+排版）

```python
from scripts.agnes_client import AgnesClient

client = AgnesClient()

# 1. 文案生成
copy = client.generate_poster_copy(
    theme="国庆节庆祝",
    style="festival",
    brand="官方"
)
# 返回: {title, subtitle, slogan, selling_points, cta}

# 2. 图像生成
img_bytes = client.generate_image(
    prompt=copy["image_prompt"],  # 文案中包含的英文图像提示词
    size="2K",
    ratio="9:16"
)

# 3. 排版合成（调用外部 generate_poster.py 或内置模板）
# 产出 1080x1920 JPG
```

## 脚本引用

| 脚本 | 用途 |
|------|------|
| `scripts/agnes_client.py` | 统一客户端，含三模型调用、重试、降级 |
| `scripts/generate_poster.py` | 海报全链路：文案→生图→HTML排版→JPG交付 |

## 参考文档

| 文件 | 内容 |
|------|------|
| `references/poster_copy_prompts.md` | 海报文案生成提示词模板（美业/节庆/极简三风格） |
| `references/image_sizes.md` | 图像尺寸档位与宽高比对照表 |
| `references/video_params.md` | 视频生成参数详解与模式对比 |
| `references/error_codes.md` | 常见错误码与排查指南 |

## 资源文件

| 文件 | 用途 |
|------|------|
| `assets/templates/beauty.html` | 美业海报 HTML 模板（左文右图） |
| `assets/templates/festival.html` | 节庆海报 HTML 模板（全屏居中烫金） |
| `assets/templates/minimal.html` | 通用极简 HTML 模板 |

---

## 使用指令

当用户需要以下任务时，**必须**加载本技能并使用内置脚本：

1. "用 Agnes 生成图片/视频/文案"
2. "做海报/配图/营销素材" 且指定或隐含使用免费模型
3. "批量生成创意内容" 需要统一调用接口
4. 任何涉及 `agnes-image-2.5-flash`、`agnes-3.0-flash`、`agnes-video-2.5-flash` 的调用

**调用方式**：
```python
# 在 Python 中直接 import
from scripts.agnes_client import AgnesClient
client = AgnesClient(api_key="...")  # 可选，默认用内置 key
result = client.generate_image(prompt="...", size="2K", ratio="9:16")
```
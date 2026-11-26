# Agnes AI 视频生成参数详解

## 模型：`agnes-video-2.5-flash` (免费 720P)

### 核心参数

| 参数 | 类型 | 必填 | 说明 | 可选值/范围 |
|------|------|------|------|-------------|
| `model` | string | ✅ | 模型 ID | `agnes-video-2.5-flash` |
| `prompt` | string | ✅ | 视频描述(英文) | 建议 < 500 字符 |
| `mode` | string | ✅ | 生成模式 | `text` / `keyframe` / `reference` |
| `seconds` | string | ❌ | 时长(秒) | `"4"`-`"12"`，默认 `"5"` |
| `size` | string | ❌ | 分辨率档位 | `"720P"` / `"1080P"` / `"1K"` / `"2K"` |
| `aspect_ratio` | string | ❌ | 宽高比 | `"16:9"` / `"9:16"` / `"1:1"` / `"4:3"` / `"3:4"` / `"21:9"` |
| `seed` | integer | ❌ | 随机种子 | 固定种子可复现 |
| `first_frame` | string | keyframe时✅ | 首帧图片 URL | 公开可访问 HTTPS |
| `last_frame` | string | keyframe时✅ | 尾帧图片 URL | 公开可访问 HTTPS |
| `images` | string[] | reference时✅ | 参考图片数组 | 最多 5 张免费 |
| `audios` | string[] | reference时❌ | 参考音频数组 | 公开可访问 HTTPS |
| `videos` | object[] | reference时❌ | 参考视频对象 | 见下文结构 |

### 三种生成模式详解

#### 1. Text-to-Video (`mode: "text"`)
纯文本生成，最简单。
```json
{
  "model": "agnes-video-2.5-flash",
  "prompt": "A futuristic city street after rain, neon lights reflected on pavement, silver sports car passing slowly, cinematic camera movement",
  "mode": "text",
  "seconds": "5",
  "size": "720P",
  "aspect_ratio": "16:9"
}
```

#### 2. Keyframe Control (`mode: "keyframe"`)
首尾帧控制，适合**转场、变身、展开**类视频。
- 必须提供 `first_frame` 或 `last_frame` 或两者
- 中间帧由模型自动插帧生成
```json
{
  "model": "agnes-video-2.5-flash",
  "prompt": "Smooth transition from day to night, city lights turning on gradually",
  "mode": "keyframe",
  "first_frame": "https://example.com/day.jpg",
  "last_frame": "https://example.com/night.jpg",
  "seconds": "5",
  "size": "720P",
  "aspect_ratio": "16:9"
}
```

#### 3. Multimodal Reference (`mode: "reference"`)
多模态参考：图片/音频/视频作为内容/风格/节奏/动作参考。
```json
{
  "model": "agnes-video-2.5-flash",
  "prompt": "Generate video following the rhythm and style of reference, subject dancing",
  "mode": "reference",
  "images": ["https://example.com/style_ref.jpg"],
  "audios": ["https://example.com/beat.mp3"],
  "videos": [{"video_url": "https://example.com/motion_ref.mp4", "reference_type": "motion"}],
  "seconds": "5",
  "size": "720P",
  "aspect_ratio": "9:16"
}
```

**reference_type 可选**：`content`(内容)、`style`(风格)、`motion`(动作)、`rhythm`(节奏)

### 异步任务流程

```
POST /v1/videos (创建任务)
    ↓ 返回 {video_id, task_id, status: "queued"}
GET /agnesapi?video_id={video_id}&model_name=agnes-video-2.5-flash (轮询)
    ↓ 每 1-2 秒轮询
status: "in_progress" → 继续轮询
status: "completed" → 取 metadata.url 下载
status: "failed" → 结束
```

**关键点**：
- 必须用 `video_id` + `model_name` 查询，**不要用 task_id**（会导致排队异常 >5 分钟）
- `flash` 版仅 720P 免费，1080P/1K/2K 需付费
- 视频时长 4-12 秒，`num_frames` 需满足 `8n+1`（内部自动处理）

### 免费额度与计费

| 项目 | 刊例价 | 天使用户体验价 |
|------|--------|----------------|
| 720P 视频秒数 | $0.025/秒 | **$0/秒 (限时免费)** |
| 1080P/1K 视频秒数 | $0.040/秒 | $0.040/秒 |
| 2K 视频秒数 | $0.055/秒 | $0.055/秒 |
| 第 6 张起输入图片 | $0.005/张 | $0.005/张 |
| 输入视频时长 | 计入输出时长同价 | 计入输出时长同价 |

**当前策略**：仅 720P 免费，适合做**短视频首帧、动态海报预览、社交媒体短视频草稿**。

### 推荐预设

| 场景 | seconds | size | aspect_ratio | 用途 |
|------|---------|------|--------------|------|
| **动态海报/竖屏短视频** | `"5"` | `"720P"` | `"9:16"` | 手机海报动态版、Reels/TikTok |
| **横版视频封面/预告** | `"5"` | `"720P"` | `"16:9"` | YouTube/B站封面动图 |
| **正方形/动态配图** | `"4"` | `"720P"` | `"1:1"` | 朋友圈/小红书动图 |
| **快速冒烟测试** | `"4"` | `"720P"` | `"16:9"` | 验证 prompt 效果 |

### 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 轮询一直 queued/in_progress | 正常，视频生成需 30-120 秒 | 耐心等待，设置 180s 超时 |
| 返回 404 task not found | 用了 task_id 而非 video_id | 改用 `GET /agnesapi?video_id=...` |
| 视频模糊/崩坏 | prompt 过于复杂或模糊 | 简化 prompt，明确主体/动作/镜头/光效 |
| 首尾帧不一致 | keyframe 模式下两帧差异过大 | 选用构图/主体相似的首尾帧 |
| reference 模式无效 | 参考媒体 URL 不可访问 | 确保公开 HTTPS，无需登录/cookie |

### 提示词编写建议

**结构**：`[主体动作] + [场景环境] + [镜头语言] + [光影氛围] + [风格质感]`

```
示例 1: "Young woman walking on beach at sunset, golden hour lighting, waves gently touching feet, slow motion, cinematic 4k, photorealistic"
示例 2: "Product rotating 360 degrees on marble pedestal, soft studio lighting, clean background, commercial product photography style, smooth camera orbit"
示例 3: "Anime style, cherry blossoms falling in wind, Japanese temple background, soft pink petals, gentle breeze, Makoto Shinkai style, high detail"
```

**避免**：过长句子、多个主体并列、抽象概念(如"表达快乐")、中文提示词(需先翻译)。
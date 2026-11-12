# 通道说明 · shangtang（商汤日日新 / SenseNova）

- **模式**：`manual`（引导式）——用户前往官网登录/注册并在控制台创建 Key，回管理台粘贴，统一落盘验证
- **官网入口**：`https://platform.sensenova.cn/console/keys`（创建/复制 API Key）
- **来源采集**：`技能档案/通道参考/商汤日日新采集/日日新_采集结果.json`

## 1. 凭证获取（引导式，不做 OAuth 逆向）

- 通道没有独立登录页：用户在管理台卡片粘贴 Key 即可；「获取」按钮直接跳转官网密钥页。
- `app.py::validate_key`：以 `Bearer` 调 `https://token.sensenova.cn/v1/models` 探活；401/403 判无效，网络异常按有效放行（不误杀）。
- 落盘统一经 `POST /api/channel/shangtang/credential`（别名 `/key`、`/validate`）→ `commit`（落盘+校验+SSE 广播）。

## 2. 生图接口（本通道的核心，聚焦于此）

> 商汤日日新 **兼容 OpenAI 图像接口协议**，基址统一为 `https://token.sensenova.cn/v1`（`token` 非 `api`）。

### 2.1 端点
```
POST https://token.sensenova.cn/v1/images/generations
Authorization: Bearer <API_KEY>      # sk- 开头，控制台创建
Content-Type: application/json
```
> 注意：图像生成**专用** `/v1/images/generations`，不是 `/v1/chat/completions`。

### 2.2 支持的生图模型（model 字段，官方文档 + 真机双重坐实）
| 模型 ID | 实测 | 官方定位 |
|---|---|---|
| `sensenova-u1.5-lite` | ✅ 真机出图（文生图+编辑+放大全通） | 默认模型；生成与编辑一体，参考图灵活修改 |
| `sensenova-u1.5-fast` | ✅ 真机出图（约 14s，快于 lite） | 加速版；官方强调"增强复杂图文创作、**文字渲染与信息布局**、多重指令遵循"——**中文配文/海报类可优先此模型** |

- 官方生图接口仅支持以上两个 model_id；client 按白名单**精确匹配**，未知/缺省回退 `lite`（不臆造路由）。
- 两模型参数表完全一致（同端点、同参数、同建议分辨率表）；仅速度与文字渲染能力有差异。

### 2.3 请求参数（真机坐实）
| 字段 | 必填 | 说明 |
|---|---|---|
| `model` | 是 | 上表模型 ID |
| `prompt` | 是 | 文生图文本 / 编辑指令 |
| `n` | 否 | 仅支持 1 |
| `size` | 否 | **实测仅接受 `auto` 或 `WIDTHxHEIGHT`**（32 的倍数，512~4096，比例 ≤3:1）；官方文档的 `2K`/`4K` 常量实测被 400 拒绝 → client 统一落官方建议 WxH（见下表） |
| `watermark` | 建议 | 显式传入；`false` 公测免费去水印 |
| `response_format` | 否 | `b64_json`（默认）/ `url`（24h 临时链接，已实测兼容落盘） |
| `output_format` | 否 | `png`（默认）/ `jpeg` / `webp`（jpeg 已实测） |
| `prompt_extend` | 否 | 提示词自动润色，默认 `true`（与提示中心叠加：Agent 优化后的 prompt 仍会被官方润色，润色失败自动回退原文） |

**官方建议分辨率（真机精确生效，client.TIER_SIZES）**：
| WxH | 比例 | 档 |
|---|---|---|
| 2048x2048 | 1:1 | 2K |
| 2720x1536 | 16:9 | 2K |
| 1536x2720 | 9:16 | 2K |
| 1664x2496 | 2:3 | 2K |
| 2496x1664 | 3:2 | 2K |
| 4096x4096 | 1:1 | 4K |

- 请求非建议组合（如 1280x720）上游**可能就近微调**（实测 1280x720 → 1280x704，不报错）。
- **限流（实测）**：HTTP 429 `rps exhausted`——并发 >1 即触发；串行 + 请求间隔 ≥10s 稳定。

### 2.4 图生图（独立端点）
```
POST https://token.sensenova.cn/v1/images/edits
body.images = [{"image_url": "https://... 或 data:image/png;base64,..."}]   # ≤5 张，第 1 张为主编辑图
```
- 输入支持公网 URL 与 Data URL（需完整 `data:image/{format};base64,` 前缀）；本地图由 client 自动转 Data URL。
- 官方支持**至多 5 张参考图**（第 1 张为主编辑图）；通用 spec 的 `image` 可传数组，协商层按 `image_refs=5` 截断（超出取前 5 张，第 1 张始终为主编辑图）。
- edits 的 `output_format` 官方另支持 `jpg` 别名（generations 为 png/jpeg/webp）；client 透传不限。

### 2.5 响应
OpenAI 兼容结构：`data[].b64_json` / `data[].url`（二选一，由 `response_format` 决定）+ `size` / `usage.images_count`。

## 3. 生图内核（已实现，全场景真机验证通过）
`client.py`（SenseNovaClient）只保留通道策略；HTTP/提取/落盘走 `core.httpx` / `core.media`：
- `generate(prompt, **kw)`：纯文本 → `/images/generations`；带 `image` → `/images/edits`；
  **i2i 无用户 ratio 时一律不传 size（官方 auto 适配主图）**——实测非方主图 + 显式 WxH 会改变主图比例；
  文生图 size 归一：WxH 直传（_clamp 归一 32 倍数/范围）→ tier+ratio 官方表（TIER_SIZES）→
  官方未列组合 1K 基准×倍数（超 4096 整体缩保持比例）→ 无 ratio 的 2K/4K 落 SIZE_FALLBACK →
  1K+ratio 用 1K 表 → 缺省 auto（lite 的 auto 默认输出 2048x1536）；
- `upscale(image, scale)`：读源图尺寸 ×scale 显式算 WxH（32 倍数、4096 上限、比例保持）重绘放大（实测 2x → 4096x4096）；
- 结果经 `media.resolve_local` 统一落盘**关联结果目录**（缺省 `桌面\Ai公益生图Pro\`，命名 `shangtang_YYYYMMDD_HHMMSS_毫秒.ext`）并登记 `img.json`，返回本地路径列表（与其他通道契约一致）。

- **计费与权限**：官方直连、**按量计费**（新用户含赠送额度），能否使用取决于你自己的账号余额与 Key 权限。
- **比例族**：通道 CAPS 为 7 种（不含 21:9）；用户要 21:9 会由协商层就近降级并如实告知生效值。
- **分辨率档**：2K/4K 官方建议值见上表；4K 仅 1:1 有官方值，其余组合按 1K 基准 ×倍数推导并钳到 4096。

## 4. 已知限制（真机坐实）
- `output_format` 传非 png 时图片内容正确，但落盘扩展名仍为 `.png`（`core.media` 命名不感知格式；spec 不暴露该字段，正常动线恒为 png，不受影响）。
- 上游可能对非官方建议的 WxH 就近微调（如 1280x720→1280x704）。
- RPS 限流严格：提交方（executor 扇出）与外部脚本均应避免对本通道并发。

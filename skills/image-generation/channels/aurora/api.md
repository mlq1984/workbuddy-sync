# 通道说明 · aurora（Aurora绮梦绘）

- **模式**：`manual`（自带 Key 粘贴，无账号体系）
- **实现模块**：`base.py` / `gpt_image.py` / `nano_banana.py` / `config.ini`
- **取 Key 页面**：外置于 Cloudflare Pages `https://yd.cfdaili.top/`（本地不再托管；管理台「获取」按钮直跳）
- **适配器**：`app.py`

## 路由（由编排器统一前缀为 `/api/channel/aurora/...`）

| 动作 | 入口 | 说明 |
|---|---|---|
| 回填 Key | `POST /api/channel/aurora/key` `{key}` | 通道页粘贴提交后自动落统一仓库 |
| 校验 Key | `POST /api/channel/aurora/validate` `{key?}` | 缺省用仓库内 Key；返回 `{valid,message}` |
| 获取 Key | 管理台「获取」按钮 → `https://yd.cfdaili.top/` 扫码/复制 Key → 回管理台粘贴 | manual 模式，无自动账号流 |

> 注：`/key` 与 `/validate` 均为规范端点 `POST /api/channel/aurora/credential` 的别名；该统一入口由编排器 `core/server.py` 路由至 `credcenter.commit`，再调用本通道 `validate_key` / 落盘凭证。

## 生图（通道客户端契约：仅供显式声明的脚本/测试场景）

> Agent 正常动线一律组装通用 spec 提交 `POST /api/execute`（见 SKILL.md 核心原则 1）；直调本模块无 job 记录、不进作品中心。

```python
import sys, os
sys.path.insert(0, os.path.join("<编排器根>", "channels", "aurora"))
from app import generate
paths = generate("一只戴头盔的橘猫", size="16:9")  # 返回本地图片路径列表
```

## 图生图（编辑）

与文生图同一入口 `generate`，多传 `image` 即可（本地路径 / 公网 URL / Data URI；
单张为 str，多张为 list，**≤2 张**，第 1 张为主编辑图，超出由协商层截断）：

```python
from app import generate
paths = generate("把背景换成赛博朋克夜景", image="input.png",
                 model="nano-banana-2", size="16:9", image_size="2K")
```

- gpt-image 与 nano-banana 两客户端均支持参考图（base 透传 `image[]` 数组，实测 2 张通过）。
- 并发：通道级 `concurrency=2`（由编排器调度）。
- 参数同文生图：`model` / `size`（比例）/ `image_size`（档位）；nano-banana 另支持官方 `aspect_ratio`（仅 nano 路由透传）。

## 放大（增强）

Aurora 上游（rightapi 中继 gpt-image / nano-banana，**API: `api.site`**，2026-10-30 迁移）无独立超分端点，故"放大"以**原图作参考、目标分辨率调高**的重绘方式实现（AI 增强放大，非像素级超分）。

```python
from app import upscale
paths = upscale("<本地路径/URL/Data URI>", scale=2)   # 返回本地图片路径列表
```

| 参数 | 说明 |
|---|---|
| `image` | 待放大源图：本地路径 / 公网 URL / Data URI（自动归一化） |
| `scale` | 放大倍数：`2`→`2K`，`≥4`→`4K`，`<2`→`1K`（标准 spec 路径下 scale 钳为 2/4；1K 档请经 `image_size`/`tier` 直接指定） |
| `size` | 画幅比例，默认取源图宽高比最近候选（`1:1`/`3:4`/`4:3`/`16:9`/`9:16`/`2:3`/`3:2`/`21:9`） |
| `prompt` | 增强提示词，默认"保持原构图、仅提升清晰度与细节" |
| `model` | 模型（含 nano/banana 走 NanoBananaClient，其余走 GPTImageClient，与 generate 一致） |

- 复用 `base.BaseClient._generate_openai`（与文生图/图生图同一 OpenAI 兼容流程），返回本地图片路径列表，可直接预览。
- `model` / `image_size` / `size` 均可显式指定（translate 与 generate 同构透传）；缺省时分别用默认模型 / 按 scale 推导档位 / 取源图比例。

## 模型与质量档位（rightapi 中继现行；2026-10-30 官方通知 API 迁移至 api.site）

| 系列 | 模型 ID | 支持档位 |
|---|---|---|
| gpt-image | `gpt-image-2`（默认） | 1K |
| gpt-image | `gpt-image-2-vip` | 1K / 2K / 4K |
| nano-banana | `nano-banana-2`（默认） | 1K / 2K / 4K |
| nano-banana | `nano-banana-pro` | 1K / 2K / 4K |
| nano-banana | `nano-banana-2-lite` | 1K |

- 通道 CAPS 档位为 `1K/2K/4K`（通道级）；**gpt-image-2 仅 1K**——需要 2K/4K 时请指定 nano-banana 系或 `gpt-image-2-vip`。
- 比例 8 种：`1:1`/`3:2`/`2:3`/`4:3`/`3:4`/`16:9`/`9:16`/`21:9`。
- 两系列统一走 `POST /draw/v1/images/generations`（中继同端点支持全部模型，异步任务）；中继另有 Gemini `generateContent` 形态，aurora 不使用——单一路径，不分叉。
- 本表为**档位参考**（供选型定档）；通道**默认型号**为 `app.MODELS` 的第 1 项（`gpt-image-2`），表中其余型号属"可显式指定"（传 `model` 即可）。以中继现行文档为准；中继上架变化时同步本表。

## 凭证统一管理

- 所有 Key 统一落 `~/.aipro/credentials.json` 的 `aurora` 段。
- `app.py` 经 `core.credprovider.resolve("aurora")` 读取（用户 Key 优先）；**本通道无内置兜底 Key**，缺失即提示先配置自备中继 Key。
- **额度与可用性**：本通道为公益中转（有每日免费额度），具体额度与可用性取决于中继政策与你的 Key 权限。
- **探活口径**：校验走任务详情路由（`GET /v1/tasks/{假任务号}`），中继**可能对探活计费**；仅 401/403 判无效，平台路由限制型 403 按有效放行（真正错误由生图暴露）。
- 不改原技能逻辑；原 `config.ini [common] api_key` 不再被作为主来源。

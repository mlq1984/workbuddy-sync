# 通道说明 · agnes（Agnes ai）

- **模式**：`auto`（账号一键创建或登录，自动获取 Key 回填、验证）
- **实现模块**：`account.py` / `client.py` / `common.py` / `credential.py`
- **取 Key 页面**：`index.html`
- **适配器**：`app.py`

## 路由（由编排器统一前缀为 `/api/channel/agnes/...`）

| 动作 | 入口 | 说明 |
|---|---|---|
| 发验证码 | `POST /api/channel/agnes/code` `{email}` | 注册/找回共用 |
| 重置/注册 | `POST /api/channel/agnes/reset` `{email,password,code}` | 新邮箱=建号，老邮箱=改密 |
| 登录取 Key | `POST /api/channel/agnes/login` `{email,password}` | 成功后自动 `set_key` 并标记有效 |
| 校验 Key | `POST /api/channel/agnes/validate` `{key?}` | |
| 获取 Key | 打开 `/channel/agnes` 页面，走登录/注册流 | auto 模式，成功后自动回填并通知主界面 |

## 生图（通道客户端契约：仅供显式声明的脚本/测试场景）

> Agent 正常动线一律组装通用 spec 提交 `POST /api/execute`（见 SKILL.md 核心原则 1）；直调本模块无 job 记录、不进作品中心。

```python
import sys, os
sys.path.insert(0, os.path.join("<编排器根>", "channels", "agnes"))
from app import generate
urls = generate("一只戴头盔的橘猫")
```

参数（对齐 Agnes 官方文档，agnes-image-2.1/2.5-flash）：

| 参数 | 说明 |
|---|---|
| `prompt` | 提示词（必填） |
| `size` | 档位 `1K`/`2K`/`3K`/`4K`，或精确尺寸如 `1024x768`（实测 2K+16:9 → 2624×1472） |
| `ratio` | 与档位式 size 配合：`1:1` `3:4` `4:3` `16:9` `9:16` `2:3` `3:2` `21:9` |
| `image` | 图生图输入：公网 URL / Data URI / 本地文件路径（自动转 Data URI）；字符串或列表 |
| `n` | 上游强制单请求单张（`CAPS.n=False`）：该参数会被协商层丢弃，多张由中心自动走并发扇出 |

- **额度与权限**：免费政策与剩余额度以官方账号为准（官方 Key 侧有剩余额度字段），**能否使用取决于你自己的账号与 Key 权限**。
- **Key 复用**：优先复用已存在且启用的 Key，无则新建；官方对单账号有 Key 数量上限（约 20）。
- **校验口径**：`GET /v1/models` 探活；网络异常按有效放行（不误杀），真实错误由生图暴露。
| `response_format` | `url`（默认）/ `b64_json` —— **放 extra_body 内**（顶层会 400，官方明确） |
| `return_base64` | 文生图需 Base64 返回时设 `true` |

官方坑位（已内置处理）：图生图输入必须放 `extra_body.image` 而非顶层；不需要 `tags:["img2img"]`；b64 产物经 `core.media` 统一落盘关联产物根（缺省桌面 Ai公益生图Pro 目录，命名 `agnes_YYYYMMDD_HHMMSS_毫秒.ext` 平铺直存，登记 img.json；见 architecture §7）并返回本地路径；统一返回本地图片路径列表（URL 也会下载落盘），可直接预览。

## 放大（增强）

Agnes 无独立超分端点，故"放大"以**原图作参考、目标分辨率档位调高**的重绘方式实现（AI 增强放大，非像素级超分）。

```python
from app import upscale
paths = upscale("<本地路径/URL/Data URI>", scale=2)   # 返回本地图片路径列表
```

| 参数 | 说明 |
|---|---|
| `image` | 待放大源图：本地路径 / 公网 URL / Data URI（自动归一化） |
| `scale` | 放大倍数：`2`→`2K`，`≥4`→`4K`（也可经 `size` 直接指定 `1K`~`4K`） |
| `ratio` | 画幅比例，默认取源图宽高比最近候选（见上方比例表） |
| `prompt` | 增强提示词，默认"保持原构图、仅提升清晰度与细节" |
| `n` / `model` | 张数 / 模型（同生图） |

- 复用 `generate`（同一 OpenAI 兼容流程），返回本地图片路径列表，可直接预览。

## 凭证统一管理

- 所有 Key 统一落 `~/.aipro/credentials.json` 的 `agnes` 段（不再落 `~/.agnes/config.ini`（原 Agnes 技能旧配置，本技能不写入））。
- `app.py` 经 `core.credprovider.resolve("agnes")` 读取（用户 Key 优先 → 内置兜底）。
- 不改原技能逻辑；账号流接口(domain)仍走官网 `platform-backend.agnes-ai.cn`。

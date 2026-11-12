# 通道说明 · cloudflare（Cloudflare Flux / Workers AI）

- **模式**：`manual`（引导式）——用户在官方 API Token 页创建 Token，回管理台粘贴，统一落盘验证
- **获取入口**：`https://dash.cloudflare.com/profile/api-tokens`；Token 权限仅需「帐户 → Workers AI → 编辑」，勿用 Global API Key
- **凭证格式（统一入口自动解析）**：
  - 只粘贴 Token：使用内置默认 Account ID；
  - 粘贴 `Token@AccountID`（如 `cfut_xxx@828fa5...`）：自动拆分，@ 前为 Token、@ 后为 Account ID——**其他用户请用此格式填自己的账号 ID**；
  - `validate_key` 校验只针对 Token 本身；Account ID 在生图时生效（配错会在出图时报 403/404）。

## 1. 凭证获取（引导式）

- 通道没有独立登录页：用户在管理台卡片粘贴 Token 即可；「获取」按钮直跳官方 Token 页。
- `app.py::validate_key`：`GET /client/v4/user/tokens/verify`；`success=true` 有效、401/403 判无效，网络异常按有效放行。
- **Account ID** 为租户标识（非密钥，控制台地址栏明文可见），配置于 `client.py::WorkersAIClient.ACCOUNT_ID`。

## 2. 生图接口（真机坐实）

### 2.1 端点
```
POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell
Authorization: Bearer <API_TOKEN>
```

### 2.2 模型与响应形态
| 模型 | 响应 | 说明 |
|---|---|---|
| `@cf/black-forest-labs/flux-1-schnell`（默认） | JSON `{"result":{"image":b64}}` | 主力，约 7 秒，无水印 |
| `@cf/stabilityai/stable-diffusion-xl-baseline` | 原始图片字节 | SDXL，按 model 关键词路由 |
| `@cf/bytedance/stable-diffusion-1.5-naviafair` | 原始图片字节 | 轻量备用 |

### 2.3 请求参数
| 字段 | 必填 | 说明 |
|---|---|---|
| `prompt` | 是 | 文生图文本（英文效果最佳） |
| `steps` | 否 | 1~8，默认 4；越大越耗 Neurons（4 步 ≈ 57.6/张） |
| `width`/`height` | 否 | **能力按型号**（官方口径）：`flux-1-schnell` 不支持任意尺寸（512×512 tile 拼接，恒 1024×1024）；`sdxl`/`sd15` 支持 width/height（≤1024、8 的倍数）。协商层按**所选型号**就近映射比例并如实登记生效值（如 flux + 9:16 → 就近 1:1，作品登记记 1:1） |

- **型号名对照**（`spec.model` → 官方 @cf 路径）：`flux-1-schnell`（或别名 `flux`）→ `@cf/black-forest-labs/flux-1-schnell`；`sdxl` → `@cf/stabilityai/stable-diffusion-xl-baseline`；`sd15` → `@cf/bytedance/stable-diffusion-1.5-naviafair`。
- **额度与权限**：每日 10,000 Neurons 免费额度自动重置（约 173 张/天）；**超出后按量计费**，可用性取决于你自己的 Token 权限与账户状态。

### 2.4 免费额度
每天 10,000 Neurons 自动重置 ≈ **173 张/天**（1024x1024/4步）；超额 $0.011/千 Neurons（约 $0.0006/张）。

## 3. 能力边界
- **仅文生图**：无图生图/编辑端点，带 image 参数一律拒绝；
- **无增强放大**（`CAPS.upscale=False`）；
- 响应为非 OpenAI 标准形态（result.image / 二进制），产物经 `core.media` 统一落盘关联产物根（缺省桌面 Ai公益生图Pro 目录，命名 `cloudflare_时间戳.ext` 平铺直存，登记 img.json；见 architecture §7）。

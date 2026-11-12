# 通道说明 · zhipu（Cogview-3-Flash / 智谱 BigModel）

- **模式**：`manual`（引导式）——用户在官方 API Key 控制台创建 Key，回管理台粘贴，统一落盘验证
- **获取入口**：`https://bigmodel.cn/apikey/platform`（管理台「获取」按钮直跳此处）

## 1. 凭证获取（引导式）

- 通道没有独立登录页：用户在管理台卡片粘贴 Key 即可；「获取」按钮直跳官方 Key 控制台。
- `app.py::validate_key`：以 `Bearer` 调 `https://open.bigmodel.cn/api/paas/v4/models` 探活；200 有效、401/403 判无效，网络异常按有效放行（不误杀）。
- 落盘统一经 `commit`（落盘+校验+SSE 广播）。

## 2. 生图接口（真机坐实）

### 2.1 端点
```
POST https://open.bigmodel.cn/api/paas/v4/images/generations
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

### 2.2 模型
| 模型 ID | 价格 | 说明 |
|---|---|---|
| `cogview-3-flash`（默认） | **免费** | 出图右下角带"AI生成"合规标识（服务端固定） |
| `cogview-4-250304` | 付费 | 首个支持画面汉字渲染；model 参数透传切换 |

- **额度与权限**：免费档无次数计费（出图带"AI生成"标识）、付费档按官方计费；**两档能否使用取决于你自己的 Key 权限与账户余额**。
- **尺寸**：官方仅 5 档比例；非官方档 WxH 直传会被官方拒绝（协商层已限 5 档并就近映射）。

### 2.3 请求参数
| 字段 | 必填 | 说明 |
|---|---|---|
| `model` | 是 | 上表模型 ID |
| `prompt` | 是 | 文生图文本，中英双语 |
| `size` | 否 | 官方档：`1024x1024` / `1152x864` / `864x1152` / `1344x768` / `768x1344` |

### 2.4 响应
OpenAI 风格：`data[].url`；产物经 `core.media` 统一落盘到关联产物根（缺省桌面 Ai公益生图Pro 目录，命名 `zhipu_YYYYMMDD_HHMMSS_毫秒.ext` 平铺直存，登记 img.json；见 architecture §7）。

## 3. 能力边界
- **仅文生图**：CogView 系列无图生图端点，带 image 参数一律拒绝；
- **无增强放大**（`CAPS.upscale=False`）；
- `/v4/models` 不列图像模型，图像模型按名直调。

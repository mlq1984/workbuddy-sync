# 通道说明 · free（Pollinations）

- **模式**：keyless（`MODE="manual"` + 契约可选字段 `KEYLESS=True`）——无需注册、无需任何 Key
- **卡片**：与其余通道完全一致（输入框/验证/获取均可正常操作）；"获取"经通道页跳转 Pollinations 官方 API 文档
- **实现模块**：`app.py`（自包含，仅标准库）
- **通道页面**：`index.html`（跳转 Pollinations 官方 API 文档）

## 生图接口（通道客户端契约：仅供显式声明的脚本/测试场景）

> Agent 正常动线一律组装通用 spec 提交 `POST /api/execute`（见 SKILL.md 核心原则 1）；直调本模块无 job 记录、不进作品中心。

```python
generate(prompt, width=1024, height=1024, model="flux", seed=None, enhance=False, n=1)
```

| 参数 | 说明 |
|---|---|
| `prompt` | 提示词（必填） |
| `width / height` | 像素尺寸，默认 1024×1024 |
| `model` | `flux`（高质量，默认）/ `turbo`（极速，**官方在售付费档**：能否使用取决于你自己的 Key/付费额度，匿名档不可用） |

- **比例族**：本通道支持 8 种比例（1:1 16:9 9:16 4:3 3:4 3:2 2:3 21:9），按 1024 基准换算像素并钳制在 256~1024。
- **韧性口径**：同模型退避重试；`flux` 失败自动降级 `turbo`（同 seed 保构图），但**匿名档 402 额度受限时直接如实报错、不降级**。
| `seed` | 缺省随机；固定 seed + 同提示词 = 复现同图 |
| `enhance` | `true` 时服务端润色提示词 |
| `n` | 一次出几张（1~4，seed 递增） |

- **返回**：本地文件路径列表（产物经 `core.media` 统一落盘关联产物根，缺省桌面 Ai公益生图Pro 目录，命名 `free_时间戳.ext` 平铺直存，登记 img.json；见 architecture §7），与 agnes 通道 `b64_json` 形态一致。
- **韧性**：同模型退避重试（TLS 干扰窗口摆动 + 排队瞬断）；flux 失败自动降级 turbo（同 seed 保构图）；响应体 <1KB 判为服务端错误页。

## 已知边界（2026-10-13 实测）

- **匿名免费档出图右下角带 `pollinations.ai` 水印**：`nologo=true` 对匿名档已失效（归档经验过期），参数仍保留发送，服务端恢复即自动生效；
- 不支持参考图/图生图；高峰期可能排队较久（单次上限 240s）；
- 不支持放大：`upscale` 会明确报错并引导改用 `aurora` / `agnes` 通道（无图生图能力，无独立超分端点）；

## 凭证行为

- `validate_key(key)` 恒返回 `{"valid": True, "message": "有效"}`（格式无法本地核验，真实可用性在生图时暴露）；
- **可选带 Key**：用户在卡片粘贴自己的 Pollinations Key（enter.pollinations.ai 获取，`sk_` 开头）→ 落盘 `~/.aipro/credentials.json` 的 free 段 → 生图时按官方 bearerAuth 经 `Authorization: Bearer` 头携带（**不进 URL**，不落日志与任务库）。有 Key 走付费档（turbo 等），能否使用取决于 Key 权限与付费额度；**无 Key 匿名档行为与此前逐字节一致**；
- 请求失败时错误消息对 URL query 脱敏（不带 prompt 等查询参数）。

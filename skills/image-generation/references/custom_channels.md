# 自定义中转通道（用户自建）· 通道说明

> 对应实现：`core/custom_channels.py`（注册表 `~/.aipro/custom_channels.json` + open/gemini 双协议适配器）。
> 内置 6 通道的说明见各自 `channels/<id>/api.md`；本文件是**自定义中转通道**的对应文档。
> **各通道自治**：本通道完全复用上游中转站/官方协议能力，能否使用、是否付费，**取决于用户自己的 Key 权限与中转站计费规则**，本技能不代为判定。

## 1. 注册与管理
- 通道中心「＋ 添加通道」注册（`POST /api/channels/custom`）：名称 / 协议（open·gemini）/ 请求地址 / 模型名 / Key / 官网 → 校验 → 落 Key 凭证仓库 → 真鉴权 → registry 热刷新。
- 编辑（`/edit`）与删除（`/delete`）同源；Key 与元数据统一经 `credcenter.commit` 落盘与广播（与内置通道卡片同路径）。
- 请求地址会被归一化：去掉尾斜杠与尾部版本段（`/v1`、`/v1beta`）——协议端点由本模块统一拼接（`…/v1/...`、`…/v1beta/...`）。

## 2. 能力集（CAPS，协议感知）
| 能力 | open 协议 | gemini 协议 |
|---|---|---|
| 文生图 t2i | ✅ | ✅ |
| 图生图 i2i | ✅ 参考图 ≤10 | ✅ 参考图 ≤14（官方 Nano Banana 2.1/Pro 口径） |
| 增强放大 upscale | ❌（提交会被自动过滤并说明） | ❌ |
| 张数 n | ✅ 1~4（官方 generations 原生） | ❌（单候选） |
| 清晰度档位 | 1K / 2K / 4K | 1K / 2K / 4K（`imageConfig.imageSize`） |
| 画幅比例 | 官方现行 10 种（1:1 2:3 3:2 3:4 4:3 4:5 5:4 9:16 16:9 21:9），越族由协商层就近映射 | 同左（`imageConfig.aspectRatio`） |

- 通道专属参数 `options` **仅 open 协议**白名单透传：`quality` / `background` / `output_format` / `output_compression` / `moderation`；gemini 协议 `imageConfig` 为官方封闭集，不透传（静默忽略，不报错）。

## 3. 协议与端点
| 协议 | 生图端点 | 验证端点（零成本，不触发生图） |
|---|---|---|
| open | `POST {base}/v1/images/generations` | `GET {base}/v1/models` |
| gemini | `POST {base}/v1beta/models/{model}:generateContent` | `GET {base}/v1beta/models?key=` |

- 兼容两种响应：OpenAI 风格 `data[].url` / `b64_json`；Gemini 风格 `candidates[].parts[].inlineData`（另兼容 `inline_data` 与 `text=URL` 变体）；网关式异步任务 `task_id` 会自动轮询 `{base}/v1/tasks/{id}`。
- **中转扩展约定**：`size` 传比例串（如 `16:9`）、`image_size` 传档位、顶层 `image` 传 data URI 数组，均为**中转站常见约定**；官方 OpenAI 直连不接受这些写法（官方图生图须走 `/v1/images/edits`）。请按你的中转站实际约定填写地址与模型名。

## 4. 模型清单
- 缺省 = 清单第一个（协议内置官网模型在前，用户补充在后）：
  - open：`gpt-image-2.5-flare`（日常）/ `gpt-image-2.5-sunburst`（编辑精度优先）/ `gpt-image-2` / `gpt-image-1.5` / `gpt-image-1` / `gpt-image-1-mini`
  - gemini：`gemini-nano-banana-2.1` / `gemini-3.1-flash-image` / `gemini-3-pro-image` / `gemini-3.1-flash-lite-image` / `gemini-2.5-flash-image`
- 中转商另提供的别名/新型号，直接填在「模型名」栏即可（会追加到清单末尾）。

## 5. 额度与权限
- 本通道**不提供任何免费额度**；出图费用、可用性、限流、审核口径**全部由用户自己的 Key 与中转站决定**。
- Key 只存于本机 `~/.aipro/credentials.json`，Agent 不可见、不入对话与日志。

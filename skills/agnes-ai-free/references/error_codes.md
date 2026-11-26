# Agnes AI 常见错误码与排查指南

## HTTP 状态码

| 状态码 | 含义 | 常见原因 | 排查步骤 |
|--------|------|----------|----------|
| **200** | 成功 | - | 正常返回 |
| **400** | 请求参数错误 | 缺少必填字段、字段类型错误、不支持的参数值、精确尺寸不被支持 | 1. 对照文档检查 payload 结构<br>2. 确认 `size`/`ratio`/`mode` 在允许范围<br>3. 图生图检查 `extra_body.image` 是否提供<br>4. 视频检查 `seconds` 是否为字符串 |
| **401** | 未授权 | API Key 无效/过期/格式错误、Key 被删除 | 1. 重新复制 Key 确认 `Authorization: Bearer <key>` 格式(注意空格)<br>2. 控制台检查 Key 状态<br>3. 尝试重新生成 Key |
| **402** | 余额不足/权限不够 | 免费额度用尽、非免费模型需付费、Token Plan 未订阅 | 1. 确认用的是免费模型(flash 系列)<br>2. 检查账户余额/订阅状态<br>3. 免费模型不应触发，可能是误判 |
| **404** | 端点/模型/任务不存在 | URL 路径错误、模型 ID 拼写错误、video_id 错误 | 1. 核对 Base URL: `https://apihub.agnes-ai.com/v1`<br>2. 确认模型 ID 完全匹配<br>3. 视频查询必须用 `video_id` + `model_name` |
| **429** | 限流 | RPM 超限、并发过高、订阅配额用尽 | 1. 降低并发，指数退避重试<br>2. 检查控制台 RPM 限制<br>3. 免费用户通常有较低 RPM |
| **500** | 服务端内部错误 | 上游模型故障、临时异常 | 1. 指数退避重试 (2s→4s→8s)<br>2. 稍后再试<br>3. 持续发生联系支持 |
| **503** | 服务繁忙 | 高负载、排队中 | 1. 退避重试<br>2. 避开高峰期 |

## 业务错误码 (响应体中)

### 图像生成错误

| 错误信息 | 原因 | 解决 |
|----------|------|------|
| `"response_format must be in extra_body"` | 顶层放了 `response_format` | 移到 `extra_body.response_format` |
| `"image is required for img2img"` | 图生图缺少 `extra_body.image` | 提供参考图数组 |
| `"invalid size/ratio combination"` | 该档位不支持该宽高比 | 查阅 `image_sizes.md` 对照表 |
| `"prompt too long"` | 提示词超长 | 缩短至 500 字符内 |
| `"chinese prompt not supported"` | 中文提示词被拦截 | **必须翻译成英文**再发送 |
| `"content policy violation"` | 触发内容安全 | 简化 prompt，避免敏感词、人脸、版权角色 |

### 视频生成错误

| 错误信息 | 原因 | 解决 |
|----------|------|------|
| `"video_id is required for retrieval"` | 查询缺少 video_id | 创建任务后保存 video_id，查询必带 |
| `"model_name is required"` | 查询缺少 model_name | 加上 `&model_name=agnes-video-2.5-flash` |
| `"invalid mode"` | mode 值错误 | 必须是 `text`/`keyframe`/`reference` |
| `"first_frame and last_frame cannot both be empty"` | keyframe 模式未提供首尾帧 | 至少提供一个 |
| `"reference media url not accessible"` | 参考媒体无法下载 | 确保公开 HTTPS，无重定向、无鉴权 |
| `"seconds must be string"` | seconds 传了数字而非字符串 | 改为 `"5"` 而非 `5` |
| `"num_frames must satisfy 8n+1"` | 帧数不符合要求 | 通常由服务端自动处理，忽略或显式设置合法值 |

## 网络/连接错误

| 错误现象 | 可能原因 | 解决 |
|----------|----------|------|
| `ProxyError / RemoteDisconnected` | 代理/网络波动、GFW 干扰 | 1. 重试机制覆盖<br>2. 确保直连或稳定代理<br>3. 增加 timeout 到 180s |
| `SSLError / CERTIFICATE_VERIFY_FAILED` | 证书验证失败 | 1. 更新 certifi<br>2. 企业环境可能需配置 CA 证书 |
| `ReadTimeout` | 生成耗时过长 | 图像 180s，视频创建 180s，轮询单次 30s |
| `ConnectionError` | DNS/网络不可达 | 检查 `apihub.agnes-ai.com` 解析、防火墙 |

## 调试清单

请求失败时按顺序检查：

1. **Base URL 正确？** `https://apihub.agnes-ai.com/v1` (注意 `/v1`)
2. **Header 正确？** `Authorization: Bearer <key>` + `Content-Type: application/json`
3. **Model ID 精确？** `agnes-3.0-flash` / `agnes-image-2.5-flash` / `agnes-video-2.5-flash`
4. **Endpoint 正确？** 文本 `/chat/completions`、图像 `/images/generations`、视频创建 `/videos`、视频查询 `/agnesapi`
5. **必填参数全？** 图像需 `model,prompt,size`；视频需 `model,prompt,mode,seconds,size`
6. **参数类型对？** `seconds` 必须字符串，`size`/`ratio`/`mode` 必须枚举值
7. **Prompt 英文？** 中文会被拦截或产生乱码
8. **Reference URL 可达？** 公开 HTTPS，浏览器能直接打开
9. **内容安全？** 避免政治、暴恐、色情、真人面部、版权 IP

## 最佳实践：客户端侧错误处理

```python
def handle_response(resp: requests.Response) -> dict:
    if resp.status_code == 200:
        return resp.json()
    
    error_map = {
        400: "参数错误，检查 payload 结构",
        401: "API Key 无效，重新获取",
        402: "余额/权限不足，确认免费模型",
        404: "端点/模型/任务不存在",
        429: "限流，退避重试",
        500: "服务端错误，稍后重试",
        503: "服务繁忙，退避重试",
    }
    hint = error_map.get(resp.status_code, f"HTTP {resp.status_code}")
    raise RuntimeError(f"{hint}: {resp.text[:200]}")
```

## 联系支持

持续无法解决时，收集以下信息发送至 `support@agnes-ai.com`：
- HTTP 状态码
- 完整响应体 (脱敏 API Key)
- 请求时间 (ISO 8601)
- Request ID (响应头 `x-request-id` 或 body 中)
- 复现步骤 / 完整 payload (脱敏)
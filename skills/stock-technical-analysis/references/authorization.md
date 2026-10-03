# Device Authorization 授权协议

本 Skill 使用 RFC 8628 Device Authorization Grant。授权服务直接签发与当前设备会话绑定的微信小程序码；脚本将其保存为本地图片，模型只负责在 skill client 中展示图片。

## 协议端点

- 创建设备会话：`POST {XGMF_AUTH_BASE}/oauth/device_authorization`
- 获取微信小程序码：`GET {XGMF_AUTH_BASE}/oauth/device-authorizations/{user_code}`
- 兑换令牌：`POST {XGMF_AUTH_BASE}/oauth/token`
- 客户端：`xgmf-stock-skill`
- Scope：`stock.read`
- Grant Type：`urn:ietf:params:oauth:grant-type:device_code`

## 幂等流程

1. 优先读取当前进程的 `XGMF_ACCESS_TOKEN`，其次读取用户目录 `.xgmf-skills/access_token`。
2. 没有 Token 时，复用未过期的 `.xgmf-skills/pending_device.json`；只在服务端给定的 `interval` 到期后轮询一次。
3. 没有可复用会话时，创建设备会话并保存 `device_code` 与 `user_code`，再用 `user_code` 从设备授权查询端点取得服务端生成的 Base64 微信小程序码。
4. 校验图片格式和大小后，将小程序码原子写入 `.xgmf-skills/authorization_qr.<图片格式>`，并将当前 `user_code` 的 SHA-256 写入缓存会话标记；stdout 只输出图片的 Markdown，不输出授权 URL 或 User Code。
5. 仅当缓存会话标记与当前 `user_code` 匹配时复用图片；创建新会话、标记缺失或标记不匹配时先清除旧图再获取新图。服务端返回 `authorization_pending` 或 `slow_down` 时，保留待授权会话并展示与该会话匹配的缓存图片，退出码为 `10`。
6. 兑换成功后以仅当前用户可读写权限保存 Token，并删除待授权会话与二维码文件。
7. REST API 返回 401 时删除文件 Token、待授权会话和旧二维码，再创建并展示新二维码。环境变量 Token 失效时仅报告，不能修改父进程环境。

## 模型行为

- 收到退出码 `10` 后，将 `qrMarkdown:` 后的 Markdown 图片原样放入回复，使 skill client 直接展示微信小程序码；提示用户扫码后重新发送原请求，不要持续轮询或阻塞等待。
- 不要展示、复述或链接授权页面；不要把授权页面 URL 重新编码成二维码，也不要把图片改为第三方二维码服务 URL。
- 不得输出、复述、复制或主动读取 Access Token 与 Device Code。
- `authorization_pending`、`slow_down`、`expired_token`、`access_denied` 必须按 RFC 8628 语义处理，不得降级到 PKCE、API Key 或 MCP。

## 信任边界

用户服务负责生成微信小程序码、身份确认与令牌签发；`xgmf-connector` 通过自省验证 `active=true` 且 Scope 包含 `stock.read`；Skill 脚本只向该第一方授权服务获取二维码图片，并持有当前用户的设备令牌调用 `/skill/v1/tools/call`。二维码不经过第三方服务，也不包含授权页面跳转。

# MJ 绘画调用合同

## 运行与已有接口

Node.js 22 或以上。安装完整目录，保留 scripts、references 和 service.json。HTTP 请求使用 Authorization Bearer，凭证读取宿主的 `MX_AI_API_KEY`。Key 创建和删除走原接入页，不新增授权接口。

所属产品：`mxai`。服务：`https://mcp.mxai.cn`。

| 命令 | 原有接口 | 用途 |
| --- | --- | --- |
| auth verify / account | GET /mcp/api/user | 验证 Key、查询积分 |
| models | GET /mcp/api/models?type=mj | 可用模型或工具 |
| tasks | GET /mcp/api/tasks | 最近任务 |
| task 编号 秒数 | GET /mcp/api/task/{serial_no} | 查询结果，等待 0–600 秒 |
| run @参数.json | POST /mcp/api/mj/draw | 创建本专项任务 |

## 输入要求

模型以 models 返回为准，省略可选项时使用服务端默认值。

必填文字：`prompt`。

允许字段：`prompt`、`model`、`aspect_ratio`、`speed`、`quality`、`stylize`、`chaos`、`iw`、`sref`、`cref`、`oref`、`input_images`、`public`。

参考图片最少 0 张，上限按模型列表和服务端校验。本地路径数组 input_files 与远程图片字段不能混用。识别真实 PNG/JPEG/WebP，单文件最多 20MB，供应商限制可能更低。

prompt 表达目标，model 是真实 slug；aspect_ratio、resolution、duration 的选项因模型而异。仅允许字段包含 dry_run 的包可报价，返回 quoted，不创建生成任务。

积分按服务端规则，不固定价格。创建必须返回 serial_no；0/1 未完成，2 成功，3 失败。结果来自真实 image_urls、path 或描述词字段，不拼接 CDN。查询失败不自动重新生成，未知提交先核对最近任务。

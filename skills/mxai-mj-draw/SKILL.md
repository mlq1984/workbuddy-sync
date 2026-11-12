---
name: "mxai-mj-draw"
slug: "mxai-mj-draw"
displayName: "MXAI MJ 绘画"
version: "1.0.1"
description: "使用 MidJourney 生成图片，并对四宫格执行放大、变体和重绘。"
summary: "使用 MidJourney 生成图片，并对四宫格执行放大、变体和重绘。"
author: "MXAI"
homepage: "https://www.mxai.cn/home/"
allowed-tools: "Bash"
display_name: "MXAI MJ 绘画"
display_name_en: "MXAI MidJourney Drawing"
description_zh: "使用 MidJourney 生成图片，并对四宫格执行放大、变体和重绘。"
description_en: "Create MidJourney images and perform upscales, variations or rerolls through existing MXAI tools."
metadata: {"openclaw":{"requires":{"env":["MX_AI_API_KEY"]},"primaryEnv":"MX_AI_API_KEY"}}
---

# MXAI MJ 绘画

使用 MidJourney 生成图片，并对四宫格执行放大、变体和重绘。

## 接入与鉴权

同产品 Skills 共用宿主环境变量 `MX_AI_API_KEY`，只配置一次。Key 在 [已有接入页面](https://www.mxai.cn/home/#/mcp?source=skill&skill=mxai-mj-draw) 创建；不要打印 Key 或写入参数文件、安装包，不按前缀、长度猜测有效性。

在本包目录执行 `node scripts/mxai-client.mjs auth verify`，只调用现有账户接口，不生成任务、不扣积分。缺少 Key 时配置环境后继续原任务；Key 无效时核对所属产品。网络或服务故障不能当作 Key 无效。

MXAI 与 Nano 分别配置自己的 Key，不自动借用对方的 Key。每个包自含脚本，可独立安装，无需先装接入 Skill。所有网络调用通过 helper。

## 完成任务

1. 核对目标、素材及关键参数。有明确执行意图可继续，歧义只询问必需项；不增加任务数量或改为其他工具。
2. 按需读取 @references/api.md，用 `models` 查询真实模型或工具，不猜名称、字段和积分价格。
3. 生成和处理会消耗积分。本地图片使用 `input_files`，远程图片使用本包的图片字段；多图顺序须符合工具用途。
4. 提交后保留真实 `serial_no` 和 `provider`。`accepted` 仅表示受理，用 `task` 查询到 2 成功或 3 失败。等待结束后仍未完成时保留编号并说明仍在处理中。
5. 依据真实产物交付图片、视频或描述词，不能编造 URL 或承诺效果。

```bash
node scripts/mxai-client.mjs models
node scripts/mxai-client.mjs run @参数.json
node scripts/mxai-client.mjs task 任务编号 120
```

参数示例：

```json
{
  "prompt": "月光下的森林，电影质感"
}
```

四宫格后续操作：`mj-action 编号 U1` 放大第 1 张，`V1` 变体，`REROLL` 重绘。每次创建新任务并可能消耗积分，需明确执行意图、跟踪新编号。

## 错误与后续使用

- `api_key_required`：配置对应环境变量，使用返回的已有接入页面。
- `api_key_invalid`：服务拒绝了 Key，核对所属产品；不生成本地替代 Key。
- `insufficient_credits`：说明积分不足；购买后先查账户和最近任务，用户明确要求后再提交。
- `result_unknown`：可能已经提交，先用 `tasks` 核对，禁止自动重试收费请求或假定退款。
- 其他异常按真实返回处理；任务受理不等于完成。

结果可交给其他同产品 Skill，共用原 Key；新收费任务仍需明确执行意图。网页继续操作使用 [MJ 绘画工作台](https://www.mxai.cn/home/#/mj?source=skill&skill=mxai-mj-draw)。

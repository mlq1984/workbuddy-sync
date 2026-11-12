# 架构权威 · Agent 运行时速查

> 本文是**运行时架构的唯一权威速查**，替代旧的 `records/06~14` 指引（开发设计档案已移出至 `../技能开发工作区/records/`，Agent 运行时**勿读**）。
> 何时读：需要深挖"协议细节 / spec 字段语义 / 落盘与查结果机制 / 为什么能这么做"时读本文。日常执行按 `SKILL.md` 第 4 节动线即可，不必读本文。

## 1. Agent 定位与铁律
- Agent 只是**生成中心的一个客户端**，动作即 SKILL 第 4 节主流程五步的机制侧：查通道 `--status` → 定 spec → `POST /api/execute` 提交 → 引路 + 下一轮 `--jobs` 汇报。
- 铁律（不可违背）：
  - **生图只经 `POST /api/execute`**；Agent 动线内绝不出现 `generate/upscale` 直调。
  - Agent **不做**：方言翻译、并发/n 阶梯编排、结果轮询等待、图片落盘与路径管理、Key 读写与验证、页面逻辑。
  - 提交后**本轮即可结束**，中心后台继续执行；用户下一轮任意发言时 `--jobs` 如实汇报。
  - **绝不静默换通道**：用户所选通道不可用 → 调起管理台 `python 启动.py`，交还用户决策。

## 2. 第 0 步：中心寻址与拉起
1. 读 `~/.aipro/center.json` → `{port, pid}`；
2. `GET http://127.0.0.1:<port>/api/ping`（超时 1s，需 `service=="aipro-center"`）→ 复用直接提交；
3. 失败 / `center.json` 缺失 → **分离启动** `python 启动.py`（脱离 Agent 生命周期，不占对话轮次）→ 轮询 `/api/ping` ≤5s → 提交。

## 3. 通信协议（纯标准库，urllib 即可）
### CLI
| 命令 | 作用 |
|---|---|
| `python 启动.py` | 启动/唤醒中心服务（托管管理台 console + 全部 API；作品屏已并入 console 的 `#works`） |
| `python 启动.py --status [--refresh]` | 全通道状态：stdout 单行机器 JSON（默认 5 分钟缓存，`--refresh` 强制实测）；退出码 0/2/3 |
| `python 启动.py --jobs` | 任务清单 JSON |
| `python 启动.py --job <id>` | 任务详情 JSON（items/paths/error 原文） |

### HTTP（提交/查询一发即走）
- 提交：`POST http://127.0.0.1:<port>/api/execute`，`Content-Type: application/json`，body 即 spec。
  - `200 {"ok":true,"job_id":"j...","accepted":[...],"dropped":[{id,reason}...]}`
  - `400 {"ok":false,"msg":"<校验原因>","dropped":[...]}`（spec 非法，或 accepted 为空）
- 查询：`GET /api/jobs`（清单）、`GET /api/job/<id>`（详情）、`GET /api/ping`（实例发现）；产物 `GET /works/<file>`。
- 调起管理台：`POST /api/console/open`（单例页面语义：页面在线→SSE 原地切 `#channels`，未开→服务端代开新页）。
- 自定义中转通道：`POST /api/channels/custom`（注册：名称/协议 open·gemini/地址/模型/Key/官网 → 校验 → 落 Key 凭证仓库 → 真鉴权 → registry 热刷新）、`POST /api/channels/custom/edit`（编辑信息后重验）、`POST /api/channels/custom/delete`（删除：注册表移除+凭证段清除，作品保留）。

**端点族全表**（`core/server.py` 实际路由；Agent 仅用前四类，其余为管理台与页面用）：
| 类别 | 端点 |
|---|---|
| 生图与结果 | `POST /api/execute`；`GET /api/jobs`、`GET /api/job/<id>`；`GET /api/ping`；`GET /works/<file>` |
| 实例与页面 | `POST /api/console/open`；`GET /`（工作台）、`GET /ui/<rel>`、`GET /channel/<id>/…`（通道页）、`GET /img`（旧入口 302 → `/#works`） |
| 通道管理 | `GET /api/channels`、`GET /api/channel/<id>/status`；`POST /api/channel/<id>/credential`（别名 `key`/`validate`）、`/enabled`、`/login`、`/code`、`/reset`；`POST /api/channels/custom`、`/edit`、`/delete` |
| 作品与存储 | `GET /api/works`、`POST /api/works/delete`；`GET /api/storage`、`POST /api/storage/open`、`/pick`、`/associate`；`GET /api/bg`；`GET /api/events`（SSE） |

## 4. spec 字段（权威源 `core/params.py` SPEC_FIELDS）
| 字段 | 类型/可选 | 规则与语义 |
|---|---|---|
| `action` | str 可选 | 缺省 `"generate"`；仅 `generate`/`upscale`，其余 400 |
| `channels` | list[str] 必填非空 | 未知 id → 400；`"auto"` 单独解析、**不可与具体通道混选**；多选=多通道并列生图 |
| `prompt` | str generate 必填 | strip 后非空；upscale 不需要 |
| `image` | str 或 list[str] 可选 | generate=编辑参考图（需通道 i2i；**支持多参考图（硬上限 ≤14；各通道实际上限见 `CAPS.image_refs`：aurora 2 / 商汤·agnes 5 / 自定义 open 10、gemini 14，超出由协商层截断），第 1 张为主编辑图**，超出通道上限由协商层截断）；upscale 必填（源图，取第 1 张）；空串 400；本地路径或 URL |
| `options` | object 可选 | 通道专属参数透传（标量值；如商汤 watermark/output_format/prompt_extend/response_format、cloudflare steps、aurora aspect_ratio），各通道 translate 自行取用，宁缺勿滥 |
| `scale` | int 仅 upscale | 缺省 2；`>=4` 归 4，否则 2；非整数 400 |
| `upscale_prompt` | str 仅 upscale 可选 | 增强提示词 |
| `ratio` | str 可选 | 须匹配 `^[1-9]\d{0,2}:[1-9]\d{0,2}$`（两端为正整数）；不传=服务端默认，**不凭空造** |
| `tier` | str 可选 | 大小写归一；**取值合法性属通道自治**：core 原样下传，通道按 `CAPS.tiers` 就近降级（未知档位就近向上取通道最高档）并如实告知生效值 |
| `n` | int 仅 generate | 1~4 |
| `model` | str 可选 | 用户点名**或从 4.3 模型选项中选定**才传 |
| 未知字段 | — | **一律 400**（防臆造） |

### 语义补全 + 协商降级（服务端自动，Agent 只需语义补全）
- **宁缺勿滥**：**完全无线索**的 `ratio/tier/n` 不进 spec（不传 ≠ 传默认）；若用途/质量词语义可推断（"手机壁纸"→9:16、"高清"→2K）则按语义补全并在交付时声明（与 SKILL 4.5 守同类）。
- 协商（仅 generate）：tier 不支持→**就近升档优先**（无更高档取通道最高档）；ratio 不支持→就近比例（无候选删参数）；通道无 `CAPS.n`→删 n 交 executor 扇出；**免费额度通道（免Key/内置Key）用户没提 tier → 补 2K 或通道最高档**，用户 Key 通道不擅自加档。
- **accepted 为空 → 整单 400**（dropped 全量返回）；`translate` 对 CAPS 之外参数直接丢弃（宁缺勿滥，不记日志）。
- `dropped` 原因 → 动作映射（Agent 按此转述或引导，**不换参数重试**）：

| 原因 | 该做什么 |
|---|---|
| `通道已停用` | 引导用户在管理台卡片打开该通道开关 → `--status <id> --refresh` 重验 |
| `需配置 Key` | 引导到管理台该通道卡片获取/粘贴 Key 并验证（付费档需有权限的 Key） |
| `凭证无效` | 同上；或清空用户 Key 走内置 Key 重验 |
| `不支持图生图（编辑）` / `不支持放大（增强）` | **能力问题，配 Key 无效**：如实告知 + 列出支持该能力的通道，请用户重新选择 |
| `模型不在该通道清单`（**执行期 item 错误**，非 dropped——plan 层不校验模型归属） | 列出该通道可用型号请用户改选（通道明确报错，不静默回落） |
| 额度/限流（服务端 402/429 等原文） | 如实说明是额度或上游限流：等重试或换通道，由用户决定 |

## 4.5 分层与边界（通道中心 vs 通道自治）

**通道中心 = 统一管控与路由**（用户与各通道之间的纽带）：
- **通道级参数**（内部处理，不下传）：`channels`（选哪条通道）、`action`（生图/放大）、通道开关与凭证（`~/.aipro/credentials.json`）、能力门控（按通道 CAPS 过滤 i2i/upscale）、停用与无凭证剔除。
- **生图参数**（原样下传，由通道按官方规则处理）：`prompt` / `image` / `ratio` / `tier` / `n` / `model` / `scale` / `upscale_prompt` / `options`。通道中心只做**结构级校验**（类型/非空/格式），**不替通道判定取值合法性**——档位/比例/n 是否支持，一律由通道按自己 CAPS 与官方规则决定。
- 路由与编排：选通道 → 按 CAPS 过滤 → 协商（就近降级，规则来自通道 CAPS）→ 交通道 `translate` 做方言转换 → 通道执行。

**各通道 = 独立自治**：
- 声明自己的能力集（`CAPS`，可按型号细分 `MODEL_CAPS`）、模型清单（`MODELS`）、语种策略（`CAPS.lang`）、方言转换（`translate`）与执行实现（`generate`/`upscale`）。
- 收到中心下传的生图参数后：**按自己能力过滤不支持的部分**（丢弃或就近降级），**转换成自己支持的参数**，再实际调用官方协议。
- 不支持时**自动降级并如实告知**（如 Key 权限不足 → 提示用户换用有权限的 Key），不静默失败。
- 付费档与免费档**一律如实支持并暴露**；能否使用取决于用户自己的 Key 权限与官方/中转站政策，通道中心不代为判定。

> 边界铁律：core **零通道知识**——不硬编码任何通道 id 的能力/语种/参数语义；一切以通道声明（CAPS/MODELS/MODEL_CAPS/translate）为准。

## 5. 通道无关性（背景机制，Agent 无需查通道能力）
- 三支柱：①约定式发现（扫 `channels/*/app.py` 常量 `CHANNEL_ID/TITLE/MODE/...`，目录即清单；另有**动态自定义通道**——`core/custom_channels.py` 注册表 `~/.aipro/custom_channels.json` 数据化注册，open/gemini 两协议适配器与 registry 合并呈现，增删走管理台"＋ 添加通道"→ `POST /api/channels/custom`（注册含真鉴权）、`/edit`、`/delete`，用户数据不进技能本体）②单一契约 `validate_key`/`acquire_key`/`account_api` ③增删通道=增删文件夹，core 零改动。
- `CAPS`（能力集）与 `translate(spec)`（方言翻译）由通道**可选声明**；不声明走 `core/params.py` 缺省。**能力可按型号细分**：通道可选声明 `MODEL_CAPS = {model: {能力字段: 值}}`（部分覆盖），用于"同通道不同型号官方能力不同"的事实（如 Cloudflare：flux-1-schnell 官方不支持任意尺寸、sdxl/sd15 支持 width/height）；未指定 model 时按通道缺省型号（`MODELS[0]`）取能力。Agent 不需读 CAPS/translate——语义补全后，过滤/协商/翻译全部由生成中心完成。
- `auto` 仅在用户明确选择时，单独解析为 `check_all()` 的 `suggest`；不与具体通道混选。

## 6. 凭证与安全（Agent 拿不到 Key）
- 取 Key 顺序（`core.credprovider.resolve`）：用户落盘 Key 优先 → 用户 Key 失效且有内置则内置兜底 → 有效/未验证原样返回用户 Key → 无用户 Key 用内置 → 都无则 fail。
- 内置 Key：密文随技能分发、**内存解密、不落盘、不入日志、无明文导出接口**；Agent 只能经 API 生图，**无法取得任何形态的 Key**。
- **双闸门**：①管理台开关 `~/.aipro/switches.json`（未记录默认开启）②executor 派发预检。停用通道对**经中心的一切调用**拒绝；闸门在通道发现时装载，直调 `channels/<id>/app.py` 不受其约束（故红线禁止直调）。
- 事件流 / 任务文件 / 日志**一律不含任何形态 Key**；页面侧唯一例外是**本机 127.0.0.1 管理台**的通道卡片与编辑弹窗（显示用户自己录入的 Key，便于核对与更换）——不对外提供任何 Key 导出接口。

## 7. 结果、落盘与查结果
- 任务 JSON：`~/.aipro/jobs/<id>.json`（原子写）；id=`j`+YYYYMMDDHHMMSS+`_`+4位hex；TTL 48h 惰性清理（**产物图片不 TTL**）。
- 状态机：`pending → running → done | partial | failed`（**partial=部分成功是合法终态**）。
- `items[]={channel,index,state(done/failed/pending),paths[],web[],error}`；单张失败→`error=服务端原文`，**不抛出、不拖垮整单**。
- 落盘命名：`<产物根>/<cid>_<YYYYMMDD>_<HHMMSS>_<毫秒>.<ext>`（平铺直存；**通道 id 不得含下划线**——作品登记/扫描按此命名解析通道归属）；**img.json=作品资产单一真相源**（`{文件名:{channel,time,prompt,params,job}}`；`params`=该通道**实际生效**的生图参数，取自 `core/params.py: effective()`——协商降级/自动补体验档之后的值，而非 Agent 原始提交值）。
- 产物根解析：`~/.aipro/storage.json`（运行时关联）> `config.ini [result] dir` > 桌面 `\Ai公益生图Pro\` > 旧 `~/.aipro/output/`。
- 查结果：`--jobs` / `--job <id>`；HTTP `GET /api/jobs` `/api/job/<id>`；works 屏 `/#works`；提交成功且工作台未打开时中心自动弹 `/#jobs-<id>`。

## 8. 异常与并发（异常动线以 SKILL 4.6 为准，本节为机制视角）
- **多选通道互不影响**：通道间线程池 `min(len(accepted),4)`；单通道异常逐 item 落错，绝不抛出。
- **同通道 n 阶梯**（n>1，中心处理，Agent 不感知）：`CAPS.n` 单请求 → 无则扇出错峰 → 瞬时类(429/5xx/timeout/限流)串行重试一次 → 仍败 item failed+原文。
- **单通道失败动线**：读 `--job` 服务端原文 → `python 启动.py` 调起管理台 → 轮询 `--status <id> --refresh` 每 5~10s 至 `valid=true` → 重新提交；用户取消则终止并说明。（**必须带 `--refresh`**：默认 5 分钟缓存不刷新会一直读到旧状态。）
- `dropped` 涉及用户所选通道 → 调起管理台；spec 400 → 转述原文，**不猜测、不重试、绝不静默换通道**。

## 9. 模块依赖与事件目录（深挖，Agent 日常不必读）
- **模块依赖（单向无环）**：`notify` 位于最底层、被三方依赖；生成中心依赖通道中心（清单/凭证/开关/CAPS）+ 通知中心；结果中心依赖通知中心 + 公共层；`server.py` 是唯一组装点；core 零通道硬编码（增删通道=增删 `channels/<id>/` 文件夹）。
- **事件目录（SSE，喂浏览器、非 Agent 依赖）**：`task.accepted / task.started / task.item* / task.done | task.failed`，订阅 `GET /api/events`。事件之外另有 **UI 导航指令**（SSE 帧 `type:"navigate"`，`core/notify.py: navigate(target)`）：提交任务时已有页面在线 → 原地切 `#jobs-<id>`；调起管理台且页面在线 → 原地切 `#channels`——**单例页面语义，不新增标签页**；无页面在线才 `webbrowser.open`。**状态真相源是 jobs 文件，不是事件**（事件丢了页面可重拉 `/api/jobs` 对账）——Agent 只经 `/api/execute` 与 `--jobs/--job`，不感知事件。

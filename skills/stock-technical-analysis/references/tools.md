# REST 工具路由

统一调用 `POST /skill/v1/tools/call`，请求体为：

```json
{"tool":"snapshot","arguments":{"sec_id":"600519.SH"}}
```

| 需求 | tool | 关键参数 |
|---|---|---|
| 名称或简称转证券代码 | `lookup_sec_id` | `keyword` |
| 行情快照 | `snapshot` | `sec_id`，可选 `fields`、`date` |
| 板块成分或排行榜 | `snapshot_sort` | `sec_id`，可选 `order`、`order_type`、`fields`、`start_pos`、`limit`、`filter`、`topn`、`get_total` |
| 分时走势 | `trend` | `sec_id`，可选 `date`、`days`、`min_time` |
| 相对位置 K 线 | `kline_offset` | `sec_id`、`period`，可选 `exer`、`date`、`min_time`、`limit` |
| 日期范围 K 线 | `kline_range` | `sec_id`、`period`、`start`、`end`，可选 `exer` |
| 市场宽度、温度、量能、情绪 | `market_signal` | `sec_id`，可选 `type`、`fields`、`date`、`limit` |
| 公司 F10（含财务报表、公司概况、股东、高管等） | `company_f10` | `datasets`，除新闻详情外通常需 `sec_id`；其他参数按数据集要求传入 |
| 指标股池 | `indicator_sec_pool` | `pool`，可选 `date`、`date_type`、`groups`、`sec_id`、`single_type`、`filter_pool`、`filter_pool_range`、`order`、`order_type`、`offset`、`limit` |

当前 REST 白名单不暴露已下线的 VIP 原始指标工具，也不暴露未注册为服务 Bean 的历史工具。

结果中的比率、金额和数组字段按接口返回的字段字典解释。比较多个标的时统一交易日、报告期、复权方式和单位。

## 公司 F10

`company_f10` 的 `datasets` 必须是至少包含一个枚举值的 JSON 数组，可一次查询多个数据集。除 `NEWS_ONE` 外均需传 `sec_id`。

```json
{
  "tool": "company_f10",
  "arguments": {
    "datasets": ["COMP_DETAIL", "MAIN_INDICATORS"],
    "sec_id": "600519.SH",
    "report_type": 0,
    "page": 1,
    "rows": 10
  }
}
```

通用可选参数：`report_type`、`report_period`、`ann_dt`、`holder_code`、`event_id`、`date`、`news_id`、`manager_type`、`holder_category`、`free_type_code`、`sw_code`、`type`、`idx`、`sub_type`、`order`、`sort_type`、`page`、`rows`。只传所选数据集需要的参数。

`report_type`：`0` 按报告期、`1` 按年度、`2` 按单季度（仅利润表/现金流量表）、`4` 按中报、`5` 按一季报、`6` 按三季报、`7` 最新；`DUPONT`、`DUPONT_RPS` 仅支持 `0` 或 `1`。

### 数据集枚举

“必填”指除 `datasets`、`sec_id` 外必须补充的参数；未注明的参数不要传。

| 分类 | datasets 枚举 | 含义与附加参数 |
|---|---|---|
| 公司概况 | `COMP_DETAIL` | 公司资料 |
| 公司概况 | `COMP_IPO` | 发行相关 |
| 公司概况 | `COMPANY_HOLD_SHARES` | 参控股公司；可选 `order`、`sort_type`、`page`、`rows` |
| 股本股东 | `HOLDER_NUMBER` | 股东户数/股东情况；可选 `page`、`rows` |
| 股本股东 | `FLOAT_HOLDER_ANNDT` | 十大流通股东公告日期列表；可选 `rows` |
| 股本股东 | `FLOAT_HOLDER` | 十大流通股东；必填 `ann_dt` |
| 股本股东 | `FLOAT_HOLDER_ONE` | 单个流通股东持股详情；必填 `holder_code`，可选 `page`、`rows` |
| 股本股东 | `INSIDE_HOLDER_ANNDT` | 十大股东公告日期列表；可选 `rows` |
| 股本股东 | `INSIDE_HOLDER` | 十大股东；必填 `ann_dt` |
| 股本股东 | `INSIDE_HOLDER_ONE` | 单个股东持股详情；必填 `holder_code`，可选 `page`、`rows` |
| 股本股东 | `INST_HOLDER` | 机构持仓汇总 |
| 股本股东 | `INST_HOLDER_DETAIL` | 机构持仓详情；必填 `report_period`、`holder_category`，可选 `page`、`rows` |
| 股本股东 | `COMP_ACTUAL_CONTROLLER` | 控股关系/实际控制人 |
| 股本股东 | `UNLOCKED_RESTRICTED_SHARES` | 限售解禁列表；可选 `page`、`rows` |
| 股本股东 | `RESTRICTED` | 解禁明细；必填 `date`，可选 `free_type_code`、`page`、`rows` |
| 股本股东 | `CAP_LATEST` | 股本结构 |
| 股本股东 | `CAP_HIS` | 历史股本变动；可选 `page`、`rows` |
| 股本股东 | `SHAREHOLDER_CHANGES_GD` | 股东持股变动；可选 `page`、`rows` |
| 公司高管 | `MANAGEMENT` | 高管资料；可选 `manager_type`（0 董事会、1 高管、2 监事会等） |
| 公司高管 | `SHAREHOLDER_CHANGES_GG` | 高管持股变动；可选 `page`、`rows` |
| 经营分析 | `COMP_MAIN_INTRODUCTION` | 主营介绍 |
| 经营分析 | `SALESSEGMENT_RPS` | 主营结构报告期列表；可选 `rows` |
| 经营分析 | `SALESSEGMENT` | 主营结构；必填 `report_period` |
| 经营分析 | `CUSTOMER_SUPPLIER_RPS` | 客户及供应商报告期列表；可选 `rows` |
| 经营分析 | `CUSTOMER_SUPPLIER` | 主要客户及供应商；必填 `report_period` |
| 资本运作 | `FUND_SOURCE`、`FUND_INVEST`、`RESTRUCTURING_EVENTS` | 募集资金来源、项目投资、收购兼并；可选 `page`、`rows` |
| 资本运作 | `RELATED_TRADE` | 关联交易 |
| 盈利预测 | `EARNINGEST` | 业绩预测 |
| 盈利预测 | `EARNINGEST_DETAIL` | 预测明细；可选 `page`、`rows` |
| 盈利预测 | `EARNINGEST_METRICS` | 详细指标预测 |
| 盈利预测 | `STOCK_RATING_CONSUS` | 投资评级 |
| 机构调研 | `ACTIVITY` | 机构调研列表；可选 `page`、`rows` |
| 机构调研 | `ACTIVITY_ONE` | 机构调研活动纪要；必填 `event_id`（先查 `ACTIVITY`） |
| 财务分析 | `MAIN_INDICATORS`、`BALANCE_SHEET`、`INCOME`、`CASHFLOW` | 主要指标、资产负债表、利润表、现金流量表；可选 `report_type`、`page`、`rows` |
| 财务分析 | `DUPONT_RPS` | 杜邦分析报告期列表；可选 `report_type`、`page`、`rows` |
| 财务分析 | `DUPONT` | 杜邦分析；必填 `report_period`，可选 `report_type` |
| 分红融资 | `DIVIDEND`、`SEO`、`RIGHT_ISSUE` | 分红送转、增发概况、配股概况；可选 `page`、`rows` |
| 公司大事 | `MAJOR_EVENT`、`BLOCK_TRADE`、`MARGIN_TRADE` | 大事提醒、大宗交易、融资融券；可选 `page`、`rows` |
| 公司大事 | `STRANGE_TRADE_DT` | 龙虎榜日期列表；可选 `rows` |
| 公司大事 | `STRANGE_TRADE` | 龙虎榜某日明细；必填 `date`（先查 `STRANGE_TRADE_DT`） |
| 行业对比 | `SW_INDUSTRY` | 所属申万行业，返回可供后续使用的 `sw_code` |
| 行业对比 | `SW_INDUSTRY_RPS` | 行业对比报告期列表；可选 `rows` |
| 行业对比 | `SW_INDUSTRY_IND` | 行业对比指标；必填 `report_period`，可选 `sw_code`、`type`、`sub_type`、`page`、`rows` |
| 估值分析 | `VAL_IND`、`VAL_BAND` | 估值趋势、估值通道；可选 `type`（0/1/2/3 对应近 1/3/5/10 年）、`idx`（`pe`/`pb`/`ps`/`pcf`） |
| 新闻公告 | `NEWS` | 新闻列表；可选 `page`、`rows` |
| 新闻公告 | `NEWS_ONE` | 新闻详情；必填 `news_id`，无需 `sec_id`（先查 `NEWS`） |
| 新闻公告 | `ANNO` | 公告列表；可选 `page`、`rows` |

`SW_INDUSTRY_IND.type`：`1` 每股指标、`2` 盈利能力、`3` 成长能力、`4` 营运能力、`5` 规模比较、`6` 阶段涨幅、`7` 估值水平；仅 `type=7` 时使用 `sub_type`（1 PE、2 PB、3 PS、4 PCF）。

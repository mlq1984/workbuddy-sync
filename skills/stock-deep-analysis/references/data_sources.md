# 数据源使用手册

## 一、westock-data 命令速查

> ⚠️ **实际调用方式**：westock-data 是 npm 包 `westock-data-clawhub@1.0.4`，通过 `npx -y` 调用（供应链中等风险，由腾讯自选股团队发布）。
> 前置：在命令前 `export PATH="/Users/zhuofeng/.workbuddy/binaries/node/versions/22.12.0/bin:$PATH"` 以使用 managed node。
> ⚠️ **渠道限制**：部分命令（如 `quote`、`news`）在当前渠道不可用；行情/PE 改用 neodata，研报用 neodata docData 或 WebSearch 获取。

```bash
# 代码格式：A股沪市 sh600519 / 深市 sz000001 / 北交所 bj430047
#            港股 hk00700 / 美股 usAAPL

# 股票代码搜索
npx -y westock-data-clawhub@1.0.4 search <公司名> 2>&1

# 公司简况（行业/主营业务）
npx -y westock-data-clawhub@1.0.4 profile <code> 2>&1

# 财务报表（最近4期，含利润表/资产负债表/现金流量表）
npx -y westock-data-clawhub@1.0.4 finance <code> --num 4 2>&1

# 股东结构（前十大流通股东）
npx -y westock-data-clawhub@1.0.4 shareholder <code> 2>&1

# 分红历史
npx -y westock-data-clawhub@1.0.4 dividend <code> --all 2>&1

# 更多命令（kline/minute/technical/chip/asfund 等）见 westock-data SKILL.md
```

---

## 二、neodata-financial-search 查询范式

> ⚠️ **Python 解释器必须带 requests**：managed `python3` 3.13.12 **没有** requests，直接跑会报「需要安装 requests」。
> 必须用已装好依赖的 venv：

```bash
# ✅ 正确（envs/default 已装 requests）
/Users/zhuofeng/.workbuddy/binaries/python/envs/default/bin/python \
  /Users/zhuofeng/.workbuddy/skills-marketplace/skills/neodata-financial-search/scripts/query.py \
  --query "<自然语言查询>" 2>&1

# ❌ 错误：会报缺 requests
/Users/zhuofeng/.workbuddy/binaries/python/versions/3.13.12/bin/python3 .../query.py
```

# Token 过期时的处理流程（凭证约 12 小时过期）
# 1. 调用 connect_cloud_service 工具（需 ToolSearch + DeferExecuteTool）获取 tempToken
# 2. 保存 token：--save-token "tk_xxxxx"
# 3. 重新执行查询

### 常用查询模板

```
{公司名}{代码} 最新PE分位数百分位，当前PE估值处于历史什么位置
{公司名}{代码} ROE、资产负债率、毛利率、净利率、流动比率 最新数据
{公司名}{代码} 上市以来历次增发、配股、可转债等集资总额，以及历次分红总额，比较分红额是否大于集资额
{公司名}{代码} 主营业务构成、营收增长趋势
{公司名}{代码} 竞争格局、行业地位、市场份额
```

### 年均 ROE / ROIC 查询模板（财务筛查专用）

> 财务筛查要求「年均 ROE / 年均 ROIC > 15%（最近10年均值，不足10年按实际年份）」。
> 必须拉取**逐年度**数据，不能用单一年度 TTM 值代替。

```
{公司名}{代码} 最近10年 每年 ROE（净资产收益率）逐年数据，列出 2016-2025 各年数值
{公司名}{代码} 最近10年 每年 ROIC（投入资本回报率）逐年数据，列出 2016-2025 各年数值
```

**计算口径**：
- 取 neodata 返回的逐年数值，做算术平均。
- 若上市/有数据年份 < 10 年，按实际年份数求平均，并在筛查表中标注实际年份区间（如 2020-2025 共6年）。
- 若 neodata 无法返回完整的逐年序列，用 WebSearch 补「{公司名} 历年 ROE 年报」或巨潮资讯/年报原文核对，并在证据来源中注明「neodata 缺失 N 年，已由公开年报补全」。
- 严禁用 TTM ROE 直接当作「年均」——TTM 是滚动12个月，不是多年平均。

---

## 三、数据优先级策略（避免无效调用）

| 数据类型 | 第一选择 | 切换条件 |
|----------|----------|----------|
| 估值（PE/PB/市值） | westock-data quote | — |
| 盈利能力（ROE/毛利率/净利率） | neodata（自然语言，更全） | neodata 无数据 → westock finance |
| 年均 ROE（近10年均值） | neodata（逐年 ROE 序列，自行求均值） | neodata 不全 → WebSearch 年报补全 |
| 年均 ROIC（近10年均值） | neodata（逐年 ROIC 序列，自行求均值） | neodata 不全 → WebSearch 年报补全 |
| 偿债能力（负债率/流动比率） | neodata | — |
| 财务报表明细 | westock-data finance | — |
| PE 历史分位数 | neodata | — |
| 研报全文 | westock-data ncontent | — |
| 公告全文 | westock-data news 获取 ID → ncontent 读取全文 | — |
| 集资/分红对比 | neodata（累计派现募资比） | — |
| 机构持有率 | westock-data shareholder（观察前十大流通股东中机构占比） | — |

---

## 五、美股（港股/中概）专项说明

> 本套数据源以 A 股为主，做美股时会遇到一批**结构性缺口**。以下为实测结论（2026-09，Alphabet/GOOGL 案例）。

### 已知不可用 / 缺失的项

| 项目 | 实测结果 | 替代方案 |
|---|---|---|
| `westock-data quote usGOOGL.OQ` | 返回「命令 quote 在当前渠道不可用」 | 用 neodata 搜「{公司名} 美股行情指标」取市值/PE/PB；或 WebSearch |
| `westock-data shareholder` | 返回「美股无股东数据源」 | 无法替代 → 筛查表标注「⚠️ 证据不足」 |
| PE 历史分位数 | neodata 对美股不返回该字段 | 无法替代 → 标注「⚠️ 证据不足」，**严禁估算** |
| 年均 ROE/ROIC 早年数据 | 2016/2017 常返回 `apiRecall: []`（空） | 用 10-K 的 **Selected Financial Data**（SEC EDGAR）自行计算，逐年补齐 |
| 商誉科目 | 可获取的资产负债表不含商誉 | 10-K 原文核对；仍无则标注证据不足 |
| 机构持有率 | 无 | 标注证据不足 |

### 美股财务数据补齐路径（按优先级）

1. **neodata 自然语言**：近 8 年 ROE/ROIC、毛利率、净利率、负债率、流动比率、CFO/FCF 通常可取。
2. **10-K / 10-Q 原文（SEC EDGAR）**：早年数据、分部收入、TAC、capex、回购与融资明细、风险因素。
3. **季度财报新闻稿（Business Wire / PR Newswire / abc.xyz investor）**：当季 GAAP 净利的构成拆解（见下方「净利润污染」）。
4. **WebSearch 交叉校验**：Macrotrends / Investing.com / StatMuse 校验历史净利与市值。

### ⚠️ 必查陷阱：美股净利润被未实现投资收益污染

美科技巨头持有大量股权证券，GAAP 净利润常含巨额**未实现公允价值变动**，会让 PE 看起来极低。

- 做法：打开当季新闻稿，找 `unrealized gains (losses) on non-marketable securities` / `equity securities` 科目，把税前金额与对 EPS 的贡献（新闻稿通常会直接给出「contributed $X.XX to EPS」）单独摘出。
- 报告中必须**并列两套估值锚**：GAAP 口径 PE vs 剔除后的核心口径 PE。
- 计算核心 EPS 时，税后调整 ≈ 税前收益 × (1 − 有效税率)，需注明为近似。

### 美股资本配置重点看什么（A 股模板之外要补的）

- **回购**：找「连续 N 个季度回购」的说法，核对当年 H1 回购金额与去年同期对比 —— 突然归零是重大信号。
- **融资结构**：股权（私募/优先股/ATM 额度）+ 债务（发债金额、票息、期限）逐年列示；注意 ATM 未使用额度也要披露。
- **capex 与 FCF**：AI 资本开支周期下 FCF 可能转负，需要单列季度 FCF 并说明原因。
- **增量 ROIC 骤降**：重资产投入期 1Y 增量 ROIC 会从 30% 掉到 10% 附近，这是判断「投入期 vs 失效期」的关键指标，务必算 5Y/3Y/1Y 三档对照。

---

## 四、处理常见错误

| 错误 | 处理方式 |
|------|----------|
| neodata 返回 401/Token expired | connect_cloud_service → --save-token → 重试 |
| neodata 报「需要安装 requests」 | 换 `/Users/zhuofeng/.workbuddy/binaries/python/envs/default/bin/python` 跑脚本（见第二节） |
| westock-data 返回数据为空 | 换 neodata 自然语言查询 |
| westock-data quote / shareholder 对美股不可用 | 见第五节「美股专项说明」，改用 neodata 行情查询；股东数据标注证据不足 |
| WebFetch 返回 403/抓取失败 | 换 WebSearch 搜索摘要信息 |
| 知乎/雪球/职友集无法直接抓取 | 标注「证据不足」，说明已尝试获取 |
| 研报 ncontent 返回 JSON 格式 | `python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data'][0]['detail'][:3000])"` 解析 |

### Python 计算脚本的两个高频坑（写增量 ROIC / g / 资本配置回报时）

1. **字典字面量放进 `for` 循环会报错**：`for k, v in {"a":1}.items()` 写法没问题，但把三个字典并列写进列表推导时会被解析成三元组迭代 → `SyntaxError: ':' expected after dictionary key`。
   正确写法：把每个字典用 `dict(...)` 或先定义成变量，再放进 `[...]`。
2. **Key 缺失导致 `KeyError`**：跨 10 年计算 `ic(y) = eq[y] + ltd[y] + std[y]` 时，最早年份（如 2015）常缺 `ltd`/`std`，**所有字典必须补满同一年份区间**再计算。

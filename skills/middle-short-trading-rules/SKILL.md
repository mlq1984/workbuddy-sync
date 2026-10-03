# middle-short-trading-rules

中短线（2-4 周）股票买卖规则框架。包含：
- **配置层**：分层止盈/止损/仓位/建仓节奏/持有期
- **核心计算函数**：动态分层买入点/止盈/止损/盈亏比/仓位建议
- **渲染模版**：详情页「🎯 中短线计划」+「💼 仓位建议」
- **集成指南**：如何接入现有评分体系

---

## 📦 安装

```bash
# 放入 ~/.workbuddy/skills/middle-short-trading-rules/
# 无需额外依赖，纯前端 JS
```

---

## ⚙️ 配置层（CFG 扩展）

```javascript
const CFG = {
  // ... 原有配置 ...
  
  // === 中短线交易参数 ===
  HOLD_DAYS: 21,                    // 目标持有天数
  ENTRY_FACTOR: 0.98,               // 第一批买入：现价 × 98%
  
  // 止盈分层（按综合评分）
  TARGET_AGGRESSIVE: [0.15, 0.25],   // ≥8 分：激进 +15% / +25%
  TARGET_STANDARD:   [0.10, 0.18],   // 6-8 分：标准 +10% / +18%
  TARGET_CONSERVATIVE:[0.05, 0.10],  // <6 分：保守 +5% / +10%
  
  // 止损三层取大（避免被洗）
  STOP_LOSS_MA_FACTOR: 0.97,        // ma20 × 0.97
  STOP_LOSS_52W_FACTOR: 0.98,       // 52周最低 × 0.98
  STOP_LOSS_CUR_FACTOR: 0.93,       // 现价 × 0.93
  
  // 仓位建议文案
  POSITION_STRONG: '重仓（70-100%）',
  POSITION_BUY:    '半仓（50%）',
  POSITION_WAIT:   '轻仓（20-30%）',
  POSITION_CAUTIOUS:'观望（≤20%）',
  POSITION_AVOID:  '回避（0%）',
};
```

---

## 🧮 核心计算函数（可直接复制）

```javascript
/**
 * 计算中短线交易计划
 * @param {Object} params
 * @param {number} params.total - 综合评分（0-10）
 * @param {number} params.cur - 当前价
 * @param {number} params.ma20 - MA20 值（可为 null）
 * @param {number} params.l - 52周最低价（可为 null）
 * @param {number} params.ADVICE_STRONG - 强烈推荐阈值（默认 8）
 * @param {number} params.ADVICE_BUY - 推荐买入阈值（默认 6）
 * @param {number} params.ADVICE_WAIT - 观望等待阈值（默认 4）
 * @param {number} params.ADVICE_CAUTIOUS - 谨慎操作阈值（默认 2）
 * @returns {Object} 交易计划
 */
function calcTradePlan(params) {
  const {
    total, cur, ma20, l,
    ADVICE_STRONG = 8, ADVICE_BUY = 6, ADVICE_WAIT = 4, ADVICE_CAUTIOUS = 2,
    ENTRY_FACTOR = 0.98,
    TARGET_AGGRESSIVE = [0.15, 0.25],
    TARGET_STANDARD = [0.10, 0.18],
    TARGET_CONSERVATIVE = [0.05, 0.10],
    STOP_LOSS_MA_FACTOR = 0.97,
    STOP_LOSS_52W_FACTOR = 0.98,
    STOP_LOSS_CUR_FACTOR = 0.93,
    POSITION_STRONG = '重仓（70-100%）',
    POSITION_BUY = '半仓（50%）',
    POSITION_WAIT = '轻仓（20-30%）',
    POSITION_CAUTIOUS = '观望（≤20%）',
    POSITION_AVOID = '回避（0%）',
  } = params;

  const tn = +total;

  // 1. 止盈分层
  const TARGET = tn >= ADVICE_STRONG ? TARGET_AGGRESSIVE
               : tn >= ADVICE_BUY ? TARGET_STANDARD
               : TARGET_CONSERVATIVE;

  // 2. 仓位分层
  const POS = tn >= ADVICE_STRONG ? POSITION_STRONG
            : tn >= ADVICE_BUY ? POSITION_BUY
            : tn >= ADVICE_WAIT ? POSITION_WAIT
            : tn >= ADVICE_CAUTIOUS ? POSITION_CAUTIOUS
            : POSITION_AVOID;

  // 3. 买入点（分批）
  const entry1 = cur ? +(cur * ENTRY_FACTOR).toFixed(2) : null;
  const entry2 = (cur && ma20) ? +(Math.min(cur * 0.99, ma20)).toFixed(2) : null;

  // 4. 止盈
  const t1 = cur ? +(cur * (1 + TARGET[0])).toFixed(2) : null;
  const t2 = cur ? +(cur * (1 + TARGET[1])).toFixed(2) : null;

  // 5. 止损：三层取大
  const slCandidates = [];
  if (ma20) slCandidates.push(ma20 * STOP_LOSS_MA_FACTOR);
  if (l) slCandidates.push(l * STOP_LOSS_52W_FACTOR);
  if (cur) slCandidates.push(cur * STOP_LOSS_CUR_FACTOR);
  const sl = slCandidates.length ? +Math.max(...slCandidates).toFixed(2) : null;

  // 6. 盈亏比
  const rrr = (sl && t1 && cur) ? +((t1 - cur) / (cur - sl)).toFixed(2) : null;

  return {
    entry1,
    entry2,
    t1,
    t2,
    sl,
    rrr,
    position: POS,
    targetTier: tn >= ADVICE_STRONG ? '激进' : tn >= ADVICE_BUY ? '标准' : '保守',
  };
}
```

---

## 🖥️ 详情页渲染模版

```javascript
// 在 loadStock() 内，计算完 total/ma20/l 后调用：
const plan = calcTradePlan({
  total, cur, ma20, l,
  ADVICE_STRONG: CFG.ADVICE_STRONG,
  ADVICE_BUY: CFG.ADVICE_BUY,
  ADVICE_WAIT: CFG.ADVICE_WAIT,
  ADVICE_CAUTIOUS: CFG.ADVICE_CAUTIOUS,
  ENTRY_FACTOR: CFG.ENTRY_FACTOR,
  TARGET_AGGRESSIVE: CFG.TARGET_AGGRESSIVE,
  TARGET_STANDARD: CFG.TARGET_STANDARD,
  TARGET_CONSERVATIVE: CFG.TARGET_CONSERVATIVE,
  STOP_LOSS_MA_FACTOR: CFG.STOP_LOSS_MA_FACTOR,
  STOP_LOSS_52W_FACTOR: CFG.STOP_LOSS_52W_FACTOR,
  STOP_LOSS_CUR_FACTOR: CFG.STOP_LOSS_CUR_FACTOR,
  POSITION_STRONG: CFG.POSITION_STRONG,
  POSITION_BUY: CFG.POSITION_BUY,
  POSITION_WAIT: CFG.POSITION_WAIT,
  POSITION_CAUTIOUS: CFG.POSITION_CAUTIOUS,
  POSITION_AVOID: CFG.POSITION_AVOID,
});

// 渲染 HTML
const tradePlanHtml = `
  <div style="font-size:12px;color:#666;margin-bottom:10px">
    🎯 中短线计划（持有 ${CFG.HOLD_DAYS} 天）：
    买入 ${plan.entry1?plan.entry1:'-'} 元 ${plan.entry2?'/ '+plan.entry2+' 元（加仓）':''} |
    目标 ${plan.t1||'-'} ${plan.t2?'/ '+plan.t2:''} 元 |
    止损 ${plan.sl||'-'} 元
    ${plan.rrr?'| 盈亏比 1:'+plan.rrr:''}
  </div>
  <div style="font-size:12px;color:#666;margin-bottom:10px">
    💼 仓位建议：<b style="color:${ac}">${plan.position}</b>
  </div>
`;
```

---

## 🔌 集成清单

| 文件 | 改动点 |
|------|--------|
| `index.html` / `stockintegrated.html` | 1. CFG 扩展 14 项配置<br>2. 引入 `calcTradePlan()` 函数<br>3. `loadStock()` 内替换原买卖点计算<br>4. 详情页渲染块替换为模版 |
| `sw.js` | 缓存版本号 +1 |

---

## 🎯 适用场景

| 场景 | 适用性 | 备注 |
|------|--------|------|
| 短线波段（1-2 周） | ⚠️ 需调参 | 缩短 HOLD_DAYS、收紧止损、提高止盈 |
| 中短线波段（2-4 周） | ✅ 最佳 | 默认参数即用 |
| 中线趋势（1-3 月） | ⚠️ 需调参 | 延长 HOLD_DAYS、放宽止损、分批止盈 |
| 长线价值投资（>3 月） | ❌ 不适用 | 逻辑完全不同，需基本面估值模型 |

---

## 📝 版本记录

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-08-05 | 初始版本：分层止盈/止损/仓位/分批建仓/盈亏比 |

---

## ⚠️ 免责声明

本框架仅供研究参考，**不构成投资建议**。实盘请结合自身风险承受能力、资金管理规则独立决策。过往回测不代表未来收益。
# Multi-Instrument Trading Methodology v1.0
> Integrated Framework: Stocks + Options + Futures | $1.5M NAV | 2x Leverage Cap
> 2026-05-28 | US Trading System V6.2 Extension

---

## §0 Architecture Overview

三层叠加结构，每层独立sizing但总暴露统一管理：

```
┌─────────────────────────────────────────────┐
│          Total Gross Exposure ≤ 2× NAV       │
│              ($3,000,000 cap)                │
├──────────┬──────────┬──────────┬─────────────┤
│ Layer 1  │ Layer 2  │ Layer 3  │   Hedge     │
│  STOCK   │ OPTIONS  │ FUTURES  │  LAYER      │
│ 60-120%  │ 0-30%    │ 0-30%    │ -5~-15%     │
│  NAV     │  NAV Δ   │  NAV     │  NAV        │
│(core)    │(leverage)│(beta)    │(protection) │
└──────────┴──────────┴──────────┴─────────────┘
```

**总暴露计算公式:**
```
Gross Exposure = Stock_MV + Options_Delta_Adjusted_Notional + Futures_Notional
Net Exposure = Long - Short - Hedge
Leverage Ratio = Gross Exposure / NAV  (cap: 2.0)
```

---

## §1 Layer 1: Stock (Core Layer — 60-120% NAV)

继承 US_TRADING_SYSTEM_V6.2 全部规则。此处不重复。

**与期权/期货整合的关键变化:**
- 单标的总暴露 = 正股市值 + LEAPS delta-adjusted notional + short put notional → 合计不超过SABCT上限
- 正股仓位优先级最高：期权/期货是增强器，不替代正股核心仓位
- 止损只用正股价格触发（期权stop由到期/premium管理）

---

## §2 Layer 2: Options (Leverage + Income + Protection)

### 总量控制

| 指标 | 限制 |
|------|------|
| 总期权premium at risk | ≤ 10% NAV ($150K) |
| 单笔premium | ≤ 3% NAV ($45K) |
| 同时持有期权头寸 | ≤ 6笔 |
| 期权delta-adjusted notional | 计入总暴露 |
| 非covered/非hedge期权 | ≤ 5% NAV premium |

### Strategy A: LEAPS — 高conviction杠杆 (S/A+/A only)

**用途:** 用有限premium获取12-18个月的高conviction标的杠杆暴露。替代margin借贷。

**适用条件:**
- SABCT S/A+/A级 only（A-及以下不用LEAPS）
- F21 beat cycle ≥ 3 consecutive beats（趋势确认）
- 催化剂链 > 6个月（不只一个event）
- 正股仓位已接近或达到grade上限

**执行参数:**
| 参数 | 规则 |
|------|------|
| Expiry | 12-18个月（LEAPS定义：>9个月） |
| Strike | ATM 或轻度 ITM (delta 0.60-0.80) — 时间价值占比最低 |
| Sizing | 单标的premium ≤ 2% NAV ($30K)；合计 ≤ 5% NAV ($75K) |
| 杠杆效果 | 10 contracts @ $24/contract = $24K premium → ~$110K effective notional (4.6x) |
| Delta管理 | 月度review，delta <0.50 考虑roll up |

**退出规则:**
1. Premium翻倍 → 止盈50%仓位，trailing stop on remainder
2. Thesis break → 立即全平
3. 剩余90天到期 → 评估roll vs close（roll成本 > premium 30%则close）
4. 正股触及ATR止损 → LEAPS同步关闭

**当前适用标的:**
- NVDA: S/A+ level conviction, Jan 2028 $230C
- MU: A+ level, HBM supercycle thesis, Jan 2028 $950C
- AVGO: A+ level, custom silicon, Jan 2028 $450C

### Strategy B: Covered Calls — 持仓收益增强

**用途:** 在没有近期催化剂的持仓上卖call收premium。月化收益target: 1-3%。

**适用条件:**
- 持仓 ≥ 100股（整手合约）
- 未来30天无重大催化剂（earnings/product launch/conference）
- 不在S级持仓上卖call（不限制S级upside）
- 正股当前价格在50dma以上（趋势完好）

**执行参数:**
| 参数 | 规则 |
|------|------|
| Strike | 10-15% OTM（被call走也是满意价格） |
| DTE | 30-45天（Tastytrade甜蜜区） |
| 管理 | 50% profit → 买回（Tastytrade规则）；21 DTE未盈利 → 评估roll/close |
| 如被行权 | 按SABCT规则决定是否重新建仓 |
| 避开 | 催化剂前14天内不卖call |

**当前适用:**
- VST 800sh → 8 contracts, 30DTE $175C (~10% OTM)
- AAON 1200sh → 12 contracts, 30DTE $155C (~11% OTM)
- CLS 400sh → 4 contracts, 30DTE $395C (~10% OTM)
- AMAT 320sh → 3 contracts (不整手，可320/300=3份)

**不适用:**
- GEV 140sh → 仅1 contract (100sh)，其余40sh无法cover
- MU 160sh → 仅1 contract，且MU 6/25有earnings催化剂，不卖

### Strategy C: Bull/Bear Spreads — 事件驱动定义风险

**用途:** 催化剂前的方向性博弈，最大亏损=净premium。

**适用条件:**
- 明确催化剂 7-14天内
- 方向性conviction A级以上
- 标的有足够期权流动性（bid-ask spread < 5%）

**执行参数:**
| 类型 | 结构 | 典型sizing | 风险/收益 |
|------|------|-----------|-----------|
| Bull Call Spread | Buy ATM call + Sell OTM call | $5-15K net debit | Max loss = debit; Max gain = width - debit |
| Bear Put Spread | Buy ATM put + Sell OTM put | $5-15K net debit | 同上 |
| Put Credit Spread | Sell OTM put + Buy further OTM put | Credit received | Max loss = width - credit |

**管理:**
- Catalyst day +1: 无条件平仓
- 盈利 50%: 提前止盈
- 亏损 50%: 减半或close

### Strategy D: Cash-Secured Puts — 价格有纪律的建仓

**用途:** 想买但觉得当前价格略贵，用卖put同时收premium。

**适用条件:**
- 想买入的标的，但当前价格不是最优入场点
- IV Rank > 40%（premium足够补偿）
- 真正愿意在strike价格接货
- 有足够现金/保证金 cover assignment

**执行参数:**
| 参数 | 规则 |
|------|------|
| Strike | 5-10% OTM (支撑位附近) |
| DTE | 30-45天 |
| Premium target | ≥ strike的1%/月 |
| 管理 | 50% profit买回；被assign → 转为正股持仓 |
| 避开 | Earnings前不卖put |

### Strategy E: Portfolio Hedge — 尾部风险保护

**用途:** 组合暴露 > 100% NAV时，保护downside tail。

**结构:**
| 工具 | 规格 | 成本目标 |
|------|------|---------|
| SPY Put Spread | Buy -5% OTM put / Sell -15% OTM put, 90-120DTE | < 0.5% NAV/季 |
| VIX Calls | Strike $25-30, 60-90DTE | < 0.2% NAV |
| 总对冲成本 | | < 0.7% NAV/季 ($10K) |

**触发条件:**
- Long exposure > 100% NAV → 必须建立hedge
- VIX < 16 → hedge便宜，主动建立
- VIX > 25 → hedge已贵，考虑realize已有hedge利润

---

## §3 Layer 3: Futures (Beta Exposure)

### 总量控制

| 指标 | 限制 |
|------|------|
| 总期货notional | ≤ 30% NAV ($450K) |
| 总margin占用 | ≤ 10% NAV ($150K) |
| 同时持有合约 | ≤ 4个 (across products) |
| Overnight margin buffer | 维持 > 1.5x initial margin |

### Product Specs

| 合约 | 乘数 | ~Notional/合约 | ~Margin/合约 | 杠杆 | 用途 |
|------|------|---------------|-------------|------|------|
| ES (E-mini S&P) | $50 × index | ~$275K | ~$15K | ~18x | 大额方向性 |
| MES (Micro S&P) | $5 × index | ~$27.5K | ~$1.5K | ~18x | 精细调仓 |
| NQ (E-mini Nasdaq) | $20 × index | ~$420K | ~$19K | ~22x | 科技beta |
| MNQ (Micro Nasdaq) | $2 × index | ~$42K | ~$1.9K | ~22x | 精细调仓 |

### Strategy F: Directional Beta — 市场beta快速调整

**用途:** 当正股部署需要时间（例如等earnings），用期货先获取market beta暴露。

**适用条件:**
- Regime = BULL
- 有明确的macro view但暂无个股催化剂
- 需要快速增加/减少market exposure

**Sizing:**
| 场景 | 合约 | Notional | 占NAV |
|------|------|---------|-------|
| 增加Tech beta | 2 MNQ | ~$84K | 5.7% |
| 增加Market beta | 4 MES | ~$110K | 7.5% |
| 最大加仓 | 1 NQ + 2 MES | ~$475K | 32% |

**管理:**
- 用做"bridge"：期货持有直到正股仓位建好 → 减期货
- 止损：合约亏损 > $5K → 减半或close
- Roll: 每季到期前7天roll到下个季度合约

### Strategy G: VIX Futures Hedge

**用途:** VIX contango时买入VIX期货作为portfolio crash insurance。

**条件:** VIX < 18 且 VIX期货contango > 5%
**Sizing:** 1-2 contracts, max $30K notional
**关闭:** VIX > 25 → 减半；VIX > 30 → 全平realize利润

---

## §4 Integrated Risk Framework

### 4.1 Total Exposure Calculation

```python
# Per-Name Exposure
name_exposure = stock_mv + leaps_delta * leaps_notional + short_put_notional

# Portfolio Level
gross_long = sum(stock_mv) + sum(options_delta_adj) + sum(futures_long_notional)
gross_short = sum(short_stock_mv) + sum(put_spreads_notional) + sum(futures_short_notional)
gross_exposure = gross_long + abs(gross_short)
net_exposure = gross_long - abs(gross_short)
leverage = gross_exposure / NAV
```

### 4.2 Hard Limits (Circuit Breakers)

| 指标 | 限值 | 动作 |
|------|------|------|
| Leverage Ratio | > 2.0x | 强制减仓至 < 2.0x |
| Single-name total exposure | > 20% NAV | 减至 ≤ 20% |
| Options premium at risk | > 10% NAV | 不开新期权 |
| Futures margin | > 10% NAV | 不开新期货 |
| Portfolio drawdown -10% | CB YELLOW | New positions ×0.5 sizing |
| Portfolio drawdown -15% | CB RED | No new positions, reduce to 50% cash |
| VIX > 30 | Emergency | Close all futures, close all non-hedge options |

### 4.3 SABCT Grade → Instrument Matrix

| Grade | 正股 Max | LEAPS | Covered Calls | Spreads | Cash-Secured Puts |
|-------|---------|-------|---------------|---------|-------------------|
| S | 20% | ✅ 3% NAV premium | ❌ (不cap upside) | ✅ | ✅ |
| A+ | 15% | ✅ 2% NAV premium | ✅ (earnings后) | ✅ | ✅ |
| A | 12% | ✅ 1.5% NAV | ✅ | ✅ | ✅ |
| A- | 8% | ❌ | ✅ | ✅ (小量) | ✅ |
| B+ | 10% | ❌ | ✅ | ❌ | ✅ (小量) |
| B | 8% | ❌ | ✅ | ❌ | ❌ |

### 4.4 Regime → Instrument Adjustment

| Regime | Stock Exposure | Options | Futures | Hedge |
|--------|---------------|---------|---------|-------|
| BULL | 80-120% | 全策略可用 | 方向性+bridge | 可选 (>100%时必须) |
| NEUTRAL | 60-80% | Covered calls + hedge only | 仅hedge | 必须 |
| CORRECTION | 40-60% | 仅hedge (protective puts) | 仅VIX hedge | 加倍 |
| BEAR | 30-50% | 仅protective puts | 仅VIX/short ES | 最大化 |

---

## §5 Execution Decision Tree

每session开盘时执行:

```
1. 更新价格 (update_prices.py)
2. 风控检查 (risk_monitor.py)
3. 计算当前各层暴露
4. IF gross_exposure < target_exposure:
     → 评估: 正股建仓 vs LEAPS vs 期货bridge
     → 有明确标的+catalyst → 正股 > LEAPS
     → 无明确标的但看好market → 期货bridge (MES/MNQ)
     → 正股已满仓但conviction高 → LEAPS加码
5. IF 持仓有催化剂即将到来:
     → 正股已满 → bull call spread加杠杆
     → 空头thesis → bear put spread 或 buy put
6. IF 持仓无近期催化剂:
     → covered call收premium (30-45DTE, 10-15% OTM)
7. IF gross_exposure > 100% NAV:
     → 必须建立portfolio hedge (SPY put spread + VIX call)
8. 月度review: 所有期权头寸到期管理
```

---

## §6 DO / DON'T

### DO
- 每笔期权/期货交易前写进场检查表（同正股R3要求）
- 期权到期前21天review: roll or close
- 期货每季roll前7天操作
- Covered calls在50% profit主动买回
- LEAPS delta <0.50时评估roll up
- Hedge比例随leverage比例同步调整
- 所有delta-adjusted notional记入portfolio exposure计算

### DON'T
- 不做straddle/strangle/butterfly/condor（复杂度管理）
- 不在S级持仓上卖covered call（不限制S级upside）
- 不在earnings前14天内卖covered call
- 不在VIX > 30时开新的方向性期货
- 不让任何期权自然到期归零（到期前1天必须close）
- 不超过2x leverage ratio（hard cap，无例外）
- 不把期权/期货当作"反正是模拟盘随便搞"—每笔交易有thesis有纪律

---

## §7 Portfolio State Schema Extension

```json
{
  "options_positions": [
    {
      "ticker": "NVDA",
      "type": "call",           // call | put
      "direction": "long",      // long | short
      "strategy": "leaps",      // leaps | covered_call | spread | cash_secured_put | hedge
      "strike": 230,
      "expiry": "2028-01-21",
      "contracts": 10,
      "entry_premium": 24.1,    // per share
      "current_premium": 28.5,
      "delta": 0.72,
      "notional": 110000,       // delta-adjusted
      "cost_basis": 24100,      // total premium paid
      "market_value": 28500,
      "unrealized_pnl": 4400,
      "entry_date": "2026-05-28"
    }
  ],
  "futures_positions": [
    {
      "product": "MES",
      "direction": "long",
      "contracts": 4,
      "entry_price": 5500,
      "current_price": 5520,
      "multiplier": 5,
      "notional": 110400,
      "margin_required": 6000,
      "unrealized_pnl": 400,
      "entry_date": "2026-05-28",
      "roll_date": "2026-06-15"
    }
  ]
}
```

---

*v1.0 | 2026-05-28 | 首次发布 | 对应 US_TRADING_SYSTEM_V6.2 + options-framework v4.0 升级*

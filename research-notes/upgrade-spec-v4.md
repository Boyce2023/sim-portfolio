# 模拟盘系统升级规格书 v4.0

> 基于：H1回测(15 agents, 125笔verified trades) + Day 1-5实盘复盘 + 自我诊断
> 写入日期：2026-05-22
> 目的：今晚升级session的完整输入，包含所有问题诊断+修正方案+具体参数

---

## Part 1: H1回测核心发现

### 1.1 总体数据

| 指标 | 数值 |
|------|------|
| 测试期间 | 2025-05-22 → 2025-11-21 (126个交易日) |
| 总交易 | 166笔trade ideas, 125笔有verified PnL |
| 胜率 | 72.3% (86W / 33L / 6 Flat) |
| 平均PnL/trade | +5.10% |
| 平均赢 | +9.56% |
| 平均亏 | -5.59% |
| Profit Factor | 4.46x |
| Win/Loss Ratio | 1.71x |

### 1.2 多空对比（关键发现）

| 方向 | 交易数 | 胜率 | 平均PnL |
|------|--------|------|---------|
| 做多 | 86 | 71% | +4.4% |
| **做空** | **38** | **75%** | **+6.3%** |

**结论：做空是更强的alpha来源。** 胜率更高且平均收益更高。

### 1.3 月度表现

| 月份 | 交易 | 胜率 | 平均PnL | 累计 | 主题 |
|------|------|------|---------|------|------|
| May | 12 | 73% | +7.1% | +85.4% | Bill + Moody's |
| Jun | 37 | 76% | +7.0% | +257.7% | 以色列-伊朗 + GENIUS Act |
| Jul | 8 | 88% | +3.5% | +27.8% | CPI降温 + 银行财报 |
| Aug | 26 | 71% | +3.3% | +84.7% | 日本Carry + Jackson Hole |
| Sep | 9 | 78% | +5.8% | +52.5% | FOMC降息 + S&P入选 |
| Oct | 16 | 75% | +4.1% | +65.7% | Q3财报 + AMD-OpenAI |
| **Nov** | **17** | **53%** | **+3.8%** | +63.9% | **鹰派转向 ← 最差月** |

### 1.4 Top 10 Winners / Losers

**Winners:**
1. SMR Short +30.4% — pre-revenue核能投机股（NuScale取消旗舰项目）
2. MARA Long +27.7% — BTC miner leverage（GENIUS Act）
3. COIN Long +27.0% — 同上
4. LULU Short +26.1% — 关税margin压力 + guidance cut
5. AMD Long +22.7% — beta最高半导体标的
6. CLSK Long +21.7% — BTC miner
7. OKTA Short +21.5% — growth deceleration + 高估值SaaS
8. AMD Long +20.2% — 中国出口许可反转
9. COIN Long +20.2% — 加密监管利好
10. NVDA Long +18.9% — Blackwell ramp

**Losers:**
1. CRCL Long -24.9% — IPO gap追涨（early investor distribution）
2. META Long -18.8% — $16B税务冲销黑天鹅
3. APP Long -12.8% — S&P入选"sell the effective date"
4. NVDA Long -11.8% — regime shift后继续做多
5. UCO Long -9.9% — 地缘冲突做多油（方向反了，应做空峰值）

### 1.5 Ticker排行榜

| Ticker | 交易次数 | 累计PnL | 平均PnL |
|--------|---------|---------|---------|
| AMD | 9 | +92.8% | +10.3% |
| TSLA | 9 | +63.9% | +7.1% |
| COIN | 4 | +58.4% | +14.6% |
| NVDA | 13 | +53.3% | +4.1% |
| GLD | 7 | +30.8% | +4.4% |

### 1.6 20条核心Lesson（浓缩版）

**入场时机：**
- L1: >15% gap不追，等3-5天consolidation
- L2: 地缘事件前入场，不是当天
- L3: 财报前dip buy高conviction名字
- L4: NVDA空头等财报后，不提前5天

**做空edge：**
- L5: Growth decel + 高估值SaaS = 最高确定性空头
- L6: 结构性空头(UNH DOJ) >> 催化剂博弈空头(NFLX)
- L7: 高估值AI股财报后8-10天 = 蜜月期结束
- L8: 投机核能 vs 运营核能 pairs trade
- L9: TSLA公开交付数据 = 重复做空edge

**宏观/催化剂：**
- L10: GLD = 降息周期标配（multi-path正收益）
- L11: September effect在Fed pivot年失效
- L12: TSMC财报 = NVDA领先指标
- L13: S&P入选公告日买，effective date卖
- L14: 政策链条trade(OBBBA→IWM/XHB) > 个股

**仓位管理：**
- L15: 单笔earnings bet ≤ 8%
- L16: 同方向选beta最高标的
- L17: AI邻接股(WDC/ANET/VST)比核心AI拥挤度低
- L18: $20B+回购 = 持续买盘地板

**Regime/风险：**
- L19: Regime shift = 最贵错误。FOMC转向24h内翻转方向
- L20: F15共识反向信号 ≠ 做空信号，只是无做多alpha

---

## Part 2: Day 1-5实盘诊断

### 2.1 成绩单

| 指标 | A股 | 美股 |
|------|-----|------|
| NAV | ¥1,033,434 (+3.34%) | $148,599 (-0.93%) |
| Alpha vs基准 | +2.8% (vs CSI300) | **-1.2% (vs SPY)** |
| 持仓数 | 6 | 11 |
| 空头 | N/A | **0** |
| 现金 | 35.6% | 30.5% |
| 交易笔数 | 11 | 15 |

### 2.2 七大问题诊断

#### 问题1: 做空暴露=0（致命度★★★★★）

- Backtest空头75% WR / +6.3% avg > 多头71% / +4.4%
- 用户核心竞争力是做空（供给侧分析天然适配）
- watchlist有MSTR/INTC但5天没动
- **机会成本估计：$500-1000/周**

#### 问题2: 散弹枪——11只美股太分散（致命度★★★★）

- 5只是2%试单（CRM/DG/COPX/LEU/FPS），贡献alpha≈0
- 回测证明：top 20 trades (+18% avg) vs 全部125 trades (+5.1% avg)
- 集中在5-7只 + 做空 >> 分散在11只 + 纯多头
- **3K试单是心理安慰不是投资**

#### 问题3: 方法论诊断了没执行（致命度★★★★）

- v3.0写了rebalance建议（卖GOOGL/SRUUF → 买FPS/GEV）
- Day 5只加了FPS 60股，其他没动
- "诊断了病没吃药"
- 方法论写入 → 执行之间gap不应>2个交易日

#### 问题4: Sizing与Conviction倒挂（致命度★★★）

- SRUUF(C-, 无催化剂) 8.1% > FPS(B+, momentum A) 4.6%
- GOOGL(C, 无30天催化剂) 7.8% > FPS 4.6%
- 按"安全感"而非conviction分配
- 违反L14铁律

#### 问题5: Regime detection缺失（致命度★★★）

- H1 Agent 14因FOMC鹰派转向后继续做多 → 40%胜率（全场最差）
- 当前无检测机制
- 最贵错误类型——不是选错股，是方向反了

#### 问题6: A股执行节奏失控（致命度★★）

- Day 1-4现金70%+ → Day 5一天砸¥145K
- 错过水晶/立讯/深南（选股力≠执行力）
- Day 5集中建仓有追赶心态

#### 问题7: Backtest lesson闲置（致命度★★）

- 20条lesson写好了，Day 1-5操作没reference过
- 缺少check机制把lesson转化为交易纪律

---

## Part 3: 修正方案（供今晚升级实施）

### 3.1 Strategy.md 需要新增/修改的条目

#### 新增：做空配置目标
```
- 美股空头暴露目标：10-15%（$15-22K）
- 至少1只空头持仓（Week 2起强制）
- 每周三执行空头扫描（从short_candidates评估）
- 空头不占"同日3只新建仓"限额（独立计算）
```

#### 新增：集中度规则
```
- 美股持仓上限：7只多头 + 2只空头 = 9只总上限
- 最低建仓金额：$7.5K（5%仓位），取消$3K试单
- C级标的2周内必须升级到B或清仓，不允许长期挂C
```

#### 新增：Regime Detection协议
```
每次FOMC/CPI/NFP事件后强制执行：
1. CME Fed Fund Futures变化（>15bp = signal）
2. VIX变化（>3点 = signal）
3. 2Y-10Y利差变化
4. 结论：unchanged / shifted dovish / shifted hawkish
5. 如果shifted → 24h内调整方向
```

#### 新增：方法论→执行强制链
```
- 方法论产出rebalance建议后，下一个交易日必须执行Priority 1
- 不执行需要写明理由到daily-review
- 连续2个交易日不执行 → 自动升级为"系统失败"标记
```

#### 修改：现金部署（§3.5）
```
增加：候选标的必须有触发价格（不是"等合适时机"）
增加：前3天未部署30%现金 → 强制从watchlist选B级以上建仓
```

#### 新增：H1 Backtest Checklist（每日/每笔交易前）
```
每笔建仓前check：
□ 这笔trade是否违反20条lesson中的任何一条？
□ 如果是做多：beta是否是同方向可选标的中最高的？(L16)
□ 如果是财报前：仓位是否≤8%？(L15)
□ 如果是gap >15%：是否在追涨？(L1)
□ 当前有空头暴露吗？没有的话先建空头 (L5)
```

### 3.2 CLAUDE.md 需要新增的条目

#### 催化剂日历补充
```
- 每周三：空头扫描日
- 每次FOMC/CPI/NFP后：regime check（强制）
```

#### 行为铁律补充
```
L16 — 散弹枪禁令：不建$3K试单。最低$7.5K(5%)，否则不值得占注意力和持仓槽。
L17 — 方法论执行链：写了rebalance建议，下一交易日必须执行P1。
L18 — 空头强制：Week 2起至少持有1只空头。无空头=系统不完整。
```

### 3.3 watchlist_config.json 需要更新

```
- 从us_short_candidates升级最高conviction空头到"ready to execute"状态
- MSTR和INTC需要完整entry checklist（thesis/catalyst/date/stop_loss）
- 新增GLD/IAU到watchlist作为对冲候选
```

### 3.4 Portfolio具体rebalance计划（v3.0 Priority 1）

| 动作 | Ticker | 股数 | ~金额 | 理由 |
|------|--------|------|-------|------|
| SELL | GOOGL | 10 | ~$3,877 | C级，无30天催化剂，dead weight |
| SELL | SRUUF | 200 | ~$3,912 | C-级，无催化剂，流动性差 |
| BUY | FPS | 100 | ~$4,852 | B+升级，revenue +103%，momentum A |
| BUY | GEV | 3 | ~$3,131 | B+升级，DC电力垄断，near ATH |
| SHORT | TBD | TBD | ~$15K | 从short_candidates选1只 |
| BUY | GLD/IAU | TBD | ~$7.5K | 降息周期对冲 |

净效果：集中度↑，做空暴露从0→10%，GLD对冲加入

### 3.5 文件清单（今晚升级需要修改的文件）

| 文件 | 修改内容 |
|------|---------|
| `strategy.md` | 新增§做空配置/§集中度/§Regime Detection/§执行链/§Backtest Checklist, 修改§3.5 |
| `CLAUDE.md` | 新增L16-L18铁律, 催化剂日历补充, 空头强制规则 |
| `watchlist_config.json` | 升级short_candidates, 新增GLD, FPS/GEV目标仓位更新 |
| `portfolio_state.json` | 执行rebalance后更新 |

---

## Part 4: 盈利能力提升的数学

### 当前模型（17只持仓 × 低conviction × 0空头）
- Expected monthly alpha vs SPY: **~0%**
- H1回测验证：125笔散弹枪 ≈ SPY return

### 目标模型（7多头 + 2空头 + GLD + 20%现金）
- 7只多头 × 10%仓位 × 3%/月avg = +2.1%
- 2只空头 × 10%仓位 × 4%/月avg = +0.8%
- GLD 10% × 1%/月 = +0.1%
- **Expected monthly: +3%/月, vs SPY ~1.5%/月 = +1.5% alpha/月**
- **剩余26天: target +5-8% alpha**

### 条件
- 集中（减到10只以内）
- 做空（至少1只10%空头）
- Regime detection不犯错
- **三个条件缺一个就回到SPY+0**

---

*升级规格书完成。今晚session直接按Part 3执行修改。*

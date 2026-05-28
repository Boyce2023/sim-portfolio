<!-- DEPRECATED: This file is preserved as reference only.
     Authority: US_TRADING_SYSTEM_V4.md §0-§7
     Last sync: 2026-05-22
     Do not modify this file — changes go to the main doc
     Note: Part 5集中度表格中的"S≤40%"是旧规则（v3.0遗留），已被裁决为S≤25%（见主文档§3.1）
     Use case: Regime State Machine图、H1/H2 Regime Error完整复盘（重大亏损复盘时参考） -->

# Risk Framework v4.0 — Regime Detection & Risk Control
> Agent-17 | 2026-05-22 | P0模块
> 数据基础: H1+H2 263笔回测 | VIX 501交易日历史 | 两次regime shift error定性分析

---

## 核心结论（先出）

两次最贵错误共同原因：**宏观regime已切换，持仓停在旧配置，没有强制检查点**。

- Agent-14 (H1 Oct): FOMC鹰派 → VIX spike+30% → 继续做多科技 → 4笔亏损累计 ~-26%
- Agent-09 (H2 Mar): 伊朗战争 → VIX>25 → 开始做空 → 4笔空头全输 -48.15%

**如果有本框架**: Agent-14 FOMC后24h翻转可避免约-25%累计亏损; Agent-09 VIX>25禁止做空可直接避免-48%的4笔空头。两次合计，regime detection是整个系统单一最高ROI的改进。

---

## Part 1: 三重信号系统

### 信号定义

| 信号 | 数据源 | Warning触发 | Action触发 |
|------|--------|------------|-----------|
| **S1: VIX 5日变化率** | yf history ^VIX 5d | +20% | +30% |
| **S2: 10Y yield 5日变化** | yf history ^TNX 5d | +10bp | +15bp |
| **S3: 2Y-10Y利差变化** | yf history ^IRX vs ^TNX | 利差收窄>10bp/周 | 曲线反转（2Y>10Y且变化>15bp） |

### 触发逻辑

```
Warning: 3个信号中任意1个触发 → Cautious模式
Action:  3个信号中任意2个同时触发 → Regime Shift Confirmed
```

**历史验证**:
- H1 Oct 10: VIX单日+32%（S1触发）+ FOMC dot plot砍降息（S2同步）= 双信号→ 应立即切Cautious; 3天后Action Confirmed
- H2 Mar 6: VIX 5日+49%（S1极端触发）+ 伊朗战争冲击10Y（S2同步）= 双信号→ 当天就是Regime Shift Confirmed，不应追空

---

## Part 2: 四种Regime状态

```
┌─────────────────────────────────────────────────────────────┐
│              REGIME STATE MACHINE                           │
│                                                             │
│  RISK-ON ──(S1/S2触发)──► CAUTIOUS ──(2+信号)──► RISK-OFF  │
│    ▲                          │                     │       │
│    │                          │                     │       │
│    └──(VIX 5日-15%+高位回落)──┘         VIX>35      ▼       │
│                                       EXTREME FEAR         │
│                                    (逆向做多窗口)            │
└─────────────────────────────────────────────────────────────┘
```

### 状态详情

**RISK-ON** (VIX<18, S1/S2/S3均未触发)
- 正常交易，momentum入场
- 多头sizing无约束（遵循原始仓位上限）
- 做空需要独立catalyst，不受额外限制
- 历史: Dec 2025 VIX均值15.5 → 100%WR

**CAUTIOUS** (VIX 18-25，或任意1个信号触发)
- 暂停新建仓，现有持仓维持不动
- 新机会等待Regime方向确认（2个交易日）
- 空头需要更强catalyst（不能只靠感觉）
- 历史: Nov 2025 VIX均值19.9 → 53%WR，未及时切换代价

**RISK-OFF** (VIX>25，或2+信号同时触发)
- **核心规则1: 停止所有做空**（H2 Agent-09的-48%教训）
- **核心规则2: 24h内关闭所有现有空头**
- 多头减仓至组合的60%（卖出最低conviction持仓）
- 只持有quality names（高评级/低杠杆/强现金流）
- 历史: Mar 2026 VIX>25 → 做空全输，做多quality有机会

**EXTREME FEAR** (VIX>35，或市场单日跌>3%)
- 立即评估逆向做多quality的机会（参照Agent-10 Apr模板）
- 不追空（VIX>35 = 历史12个月后S&P 100%正收益）
- 等VIX 5日delta出现-15%信号 → 执行逆向建仓
- 历史: Mar 27 VIX=31 + Apr 8停火 → VIX 5日-16.7% → Agent-10入场 91%WR

---

## Part 3: 事件后强制检查SOP

**触发事件**: FOMC / CPI / NFP / 重大地缘政治事件

**执行时间**: 事件发布后**次日开盘前**（美股为当天收盘后至次日premarket）

### 5步检查清单（每步都要记录结果）

```
Step 1: VIX水位
  □ 当前VIX: ____
  □ 5日delta: ____%（(今日-5日前)/5日前）
  □ 状态判断: Risk-On / Cautious / Risk-Off / Extreme Fear
  □ 与事件前状态相比: 未变化 / 升级 / 降级

Step 2: 10Y Yield变化
  □ 事件前TNX: ____%  →  事件后TNX: ____%
  □ 5日变化: ____bp
  □ S2信号: 未触发 / Warning(+10bp) / Action(+15bp)
  □ 超过4.7%? 是→禁止新建高PE成长股多头 / 否

Step 3: Regime判断
  □ 触发信号数量: 0 / 1 / 2 / 3
  □ Regime是否切换? 是 / 否
  □ 如果切换: 从___切换到___

Step 4: 持仓审计（Regime切换时执行）
  □ 当前最高风险持仓: ___（VIX高位期间的空头？高PE成长股？）
  □ 需要在24h内关闭的持仓: ___
  □ 执行计划: ___

Step 5: 记录
  □ 写入当日daily-reviews
  □ 格式: [Regime Check] 事件: ___ | 信号: ___ | 状态: ___ → ___ | 行动: ___
```

**强制性规则**: Step 3判断Regime切换 → Step 4和Step 5不可跳过，当日必须执行。

---

## Part 4: Regime Shift后行动协议

### 升级方向（风险加剧）

**Risk-On → Cautious**
- 暂停所有新建仓位
- 现有持仓维持，但收紧止损到最近低点（而非原始止损）
- 等2个交易日确认方向后再操作
- 不需要强制减仓

**Risk-On → Risk-Off（或Cautious → Risk-Off）**
- 24h内关闭所有空头（VIX>25做空历史WR接近0）
- 24h内将整体多头减仓至60%上限（优先卖低conviction持仓）
- 只保留: S/A级conviction + quality属性（低杠杆/稳现金流）
- 禁止新建任何方向仓位，直到Regime确认转向

**Any → Extreme Fear（VIX>35 或单日跌>3%）**
- 所有空头立即覆盖
- 现金提高至40%+
- 设置逆向做多监控: 等VIX 5日delta出现-15%（从>25高位回落）
- 准备candidate list: 高conviction quality names（参照Agent-10的AMD/GOOGL/AMZN）

### 降级方向（风险缓解）

**Risk-Off → Cautious**
- VIX回落至20-25区间 → 可开始小规模布局（C级conviction，≤8%仓位）
- 继续保持空头禁令直至VIX<20
- 逐步释放被压缩的多头

**Risk-Off → Risk-On（VIX回落+5日delta <-15%）**
- 这是最高alpha窗口（参照Apr 2026 88%WR模板）
- 优先建仓: 之前因Regime限制未能建的高conviction标的
- 速度: 3-5个交易日内建仓至目标size，不拖延
- 参照Agent-10的入场逻辑: 停火/政策转向确认后，第一天就执行，不等

**Extreme Fear → Risk-Off**
- VIX从>35回落至25-30 → 保持谨慎但可以开始评估
- 确认信号: VIX 5日delta -15% + 有明确catalyst（停火/政策/数据）
- 逆向做多执行时机: catalyst出现的**当天**（不等确认，参照Apr 8案例）

---

## Part 5: 组合层面风控规则

### 回撤控制

| 触发条件 | 执行动作 | 优先级 |
|---------|---------|--------|
| 单日亏损 >-2% | 次日暂停新建仓，只执行止损 | 高 |
| 单日亏损 >-3% | 次日暂停所有交易，全面review | 极高 |
| 组合回撤 -10%（从NAV高点） | 触发全面持仓review，评估Regime状态 | 高 |
| 组合回撤 -15% | 强制减仓至50%总仓位，关闭所有新建计划 | 极高（硬规则） |

### 集中度控制

| 维度 | 上限 | 违反处理 |
|------|------|---------|
| 单板块（美股） | 35% | 超限当日减仓至限制以内 |
| 单标的（美股） | 按conviction级别（S≤40%/A≤25%/B≤15%/C≤8%） | 建仓前检查，建仓后不追加 |
| 前3大持仓相关性 | <0.8（Pearson，滚动30日） | >0.8发Warning，不新建同板块仓位 |
| 做空总敞口 | Risk-On: 无限制 / Cautious: ≤20% / Risk-Off: 0% | Regime切换后24h内执行 |

### 相关性计算参考（简化版）

```
高相关板块对（通常>0.8）:
- NVDA + AMD + AVGO（AI半导体）
- QQQ + XLK + MSFT（科技指数/大盘科技）
- CEG + NRG（电力/核能）
- XOM + OXY + XLE（能源）

持有任意2只同板块时: 合并计算板块集中度，不拆分算
```

---

## Part 6: Regime Detection决策树（简化版，30秒执行）

```
每次入场前 + FOMC/CPI/NFP后执行:

① VIX在哪里?
   <15     → RISK-ON (绿灯)
   15-18   → RISK-ON (绿灯)
   18-25   → CAUTIOUS (黄灯)
   25-35   → RISK-OFF (红灯) ← VIX>25做空=直接-48%
   >35     → EXTREME FEAR (逆向做多评估)

② VIX 5日delta?
   <+20%   → 无额外信号
   +20%~+30% → WARNING: 暂停新建多头，等2天
   >+30%   → ACTION REQUIRED: 立即评估所有持仓方向
   <-15%（且从>25回落） → 逆向做多窗口激活

③ TNX 5日变化?
   <+10bp  → 无信号
   +10~15bp → S2 WARNING（Cautious加权）
   >+15bp  → S2 ACTION（叠加S1计算）
   突破4.7% → 禁止新建高PE成长股多头（PE>30x）

④ 信号汇总
   0个信号触发 → 当前Regime维持
   1个信号触发 → Warning，进入Cautious
   2+个信号触发 → Regime Shift Confirmed，执行对应行动协议

⑤ 拟操作方向检查（入场前）
   拟做空 + VIX>25 → 拒绝（硬规则，无例外）
   拟做多 + VIX>25 + 5日delta<-15% → 允许（逆向）
   拟做多 + 2+信号触发 → 不建新仓，等Regime确认
```

---

## Part 7: H1+H2验证（如果有本框架能避免多少损失）

### Agent-14验证（H1 Oct-Nov 2025）

| 时间 | 实际发生 | 如果有本框架 |
|------|---------|------------|
| Oct 10 | VIX +32%单日，无动作 | S1触发 → Warning → 暂停新建多头 |
| Oct 29 | FOMC鹰派，无Regime检查 | 24h SOP强制检查 → S1+S2双触发 → Regime Shift Confirmed → Risk-Off |
| Nov 3 | 继续做多科技4笔 | Risk-Off状态下禁止新建多头，4笔均不执行 |
| Nov结果 | NVDA -11.8%, MSFT -8.2%, CEG -3.5%, NRG -2.3% | 4笔全避免，约-25.8%累计损失 |

**可避免损失估算**: ~-25%累计（H1最贵单一错误来源）

### Agent-09验证（H2 Mar 2026）

| 时间 | 实际发生 | 如果有本框架 |
|------|---------|------------|
| Mar 6 | VIX 5日+49%，无动作 | S1极端触发 → Regime Shift Confirmed → Risk-Off |
| Mar 16 | 开始做空（VIX=21.4黄灯区） | Cautious状态，新空头需更强catalyst；但S2同步触发应已是Risk-Off |
| Mar 20 | 做空QQQ（VIX=25.8红灯区） | Risk-Off → 禁止做空，该笔-11.3%直接避免 |
| Mar 24 | 做空GOOGL | 禁止，该笔-16.8%直接避免 |
| Mar 27 | 做空SPY（VIX=31极端恐惧） | 禁止；同时Extreme Fear触发逆向做多评估 |
| Apr 8 | （Agent-10接手）停火+逆向做多 | 本框架在Mar 27 VIX=31时已识别Extreme Fear，提前准备candidate list |
| 最终 | 4笔空头: -16.8%, -12.8%, -11.3%, -7.3% = -48.2% | 4笔全避免，-48.2%完整保住 |

**可避免损失估算**: ~-48%（H2唯一最贵错误，4笔空头全军覆没）

### 两次合计
- 总可避免损失: ~-73%累计PnL（分布在两个half period）
- 这解释了为什么"两次regime shift error合计亏损超过总PnL的80%"
- 本框架的核心价值: **不是提高WR，是消除单一最大损失来源**

---

## 附录: 每日例行检查脚本提示

### 每日开盘前（30秒）
```bash
yf history ^VIX 5d   # 计算5日delta，确认Regime状态
yf history ^TNX 5d   # 确认S2信号
```

### FOMC/CPI/NFP当天额外执行
```bash
yf history ^VIX 1d   # 事件后VIX即时反应
yf history ^TNX 1d   # 10Y yield即时反应
# 对照SOP 5步检查清单，记录到daily-reviews
```

### Regime状态快速查表（贴近strategy.md）

| VIX | 5日Delta | TNX | Regime | 最大空头敞口 | 最大多头敞口 |
|-----|----------|-----|--------|------------|------------|
| <18 | <+20% | <+10bp | RISK-ON | 无限制 | 无限制 |
| 18-25 | 任意 | 任意 | CAUTIOUS | 20% | 暂停新建 |
| >25 | 任意 | 任意 | RISK-OFF | **0%（硬规则）** | 60%上限 |
| >35 | <-15%（回落） | 任意 | EXTREME→逆向 | 0% | 建逆向多头 |

---

*数据来源: H1+H2 263笔回测 | yfinance VIX 501交易日历史（2024-2026）| agent-sentiment.md + agent-macro.md诊断报告*
*优先级: P0 — 本模块错误代价 = 总PnL的80%+*

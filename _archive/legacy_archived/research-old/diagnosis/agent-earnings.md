# Earnings Surprise与股价反应 — 诊断报告
**Agent-3 | 美股交易系统v4.0重建 | 2026-05-22**

---

## 核心结论（一句话）

Beat本身只是入场门票，**guidance质量 + 估值水位 + 预期差是否真实存在** 才是决定方向的三个变量。

---

## 一、基础统计数据

**2025年S&P500 earnings season数据（FactSet）：**
- Beat率：82%（Q2 2025，历史高位，上一次相同水平是2021年Q3）
- Beat后平均价格反应：+0.9%（两天窗口，略低于5年均值+1.0%）
- Miss后平均价格反应：-5.6%（Q2 2025，远高于5年均值-2.4%）
- 结论：**市场对miss的惩罚严厉程度是beat奖励的6倍以上**，且2025年惩罚力度超历史均值

**关键不对称：**
- 82%的公司beat，但beat后next-day正收益率不足50%
- 即：超过一半的"beat"在当日没有产生正回报

---

## 二、Beat=涨 的四个必要条件

### 条件1：预期差是真实的，不是"共识beat"
- 隐含预期（options定价的move）往往高于卖方共识
- 统计：股价在implied move范围内概率约70-75%（因IV在财报前被高估）
- 如果pre-earnings run-up已经反映了beat，实际beat只是"兑现预期"
- **信号**：如果财报前一个月股价涨幅显著，beat后反弹空间被压缩

### 条件2：Guidance不能disappointing
- 前向Guidance是更重要的变量（案例验证见第三节）
- 市场定价未来现金流而非历史季度，一个季度的beat无法改变DCF
- **法则**：Beat EPS + 下调Guidance = 大概率跌；Miss EPS + 上调Guidance = 可能涨

### 条件3：估值不能过高（高PE是beat后下跌的加速器）
- 高估值股ticket需要"exceptional positives"才能维持或提升倍数
- 任何low quality beat（cost cut驱动而非revenue growth）都会被惩罚
- 案例：一家PE=72.7x的股票beat后仍然下跌，因为定价已隐含多季度完美执行
- **阈值参考**：PE>40x的成长股，beat后当天-5%属于正常波动

### 条件4：Beat质量 — Revenue beat比EPS beat更重要
- Revenue beat = 真实需求旺盛
- EPS beat via cost cut = 短期操作，市场会打折扣
- **最强信号**：Revenue beat + EPS beat + Guidance raise = 三连击，几乎必涨

---

## 三、H1/H2案例拆解

| 案例 | Beat情况 | 实际走势 | 失败原因 |
|------|---------|---------|---------|
| AAPL H1 | Beat | Day1 -2.5% → 最终+13.4% | 短期sell the news，但PEAD（后续漂移）生效，本质是高质量beat |
| META H1 | Beat | -18.8% | 税务冲销黑天鹅，非财报本身；条件外因素 |
| CRM H1 | Beat | -7.9% | Priced in：pre-earnings涨幅已消化预期，guidance一般 |
| MU Q4 H2 | Blowout beat | +46.9% | 周期底部+超预期revenue+guidance大幅上调，三连击满足 |
| NVDA Q4 H2 Feb | Beat $81.6B +85%YoY | -9% | 高PE+sell the news：市场已定价完美，任何"只是beat"都不够 |
| META Jan 29 H2 | Beat +12% gap | 20天后-12.2% | Gap IS the move — 开盘跳涨已是全部奖励，拿住=回吐 |

**规律提取：**
1. **MU类型**（周期股+真实blowout）：买入可持有，PEAD效应最强
2. **NVDA类型**（高PE AI股+market darling）：beat后第1天是卖出窗口，不是买入
3. **META类型**（大gap开盘）：gap就是全部收益，不追不加，等回调

---

## 四、Beat后漂移（PEAD）规律

- PEAD有效期：60-90天（学术文献确认）
- 2024年研究：做多top SUE decile + 做空bottom SUE decile，3个月风险调整收益5.1%（年化20%+）
- **PEAD在高关注度股票（AI/Tech）衰减明显** — 机构快速套利导致漂移缩短
- **PEAD在低关注度股票（中小盘）仍然强劲**

L1规则（>15% gap不追，等3-5天）的理论支撑：
- 大gap后存在short-term mean reversion
- PEAD会提供后续入场机会，无需在gap当天追入

---

## 五、估值水位与反应放大系数

| PE水位 | Beat后正常反应 | Beat不足时惩罚 |
|-------|--------------|--------------|
| <15x（价值股） | +3-5% | -2-3% |
| 15-30x（合理成长） | +1-3% | -3-5% |
| 30-50x（高成长） | +0-2% | -5-10% |
| >50x（Market darling） | -5%-+5%随机 | -10-20% |

结论：**PE>50x时，beat是中性事件，guidance才是定价变量**

---

## 六、可操作框架 — Earnings Trade DO/DON'T

### DO

| 规则 | 场景 | 理由 |
|------|------|------|
| **财报前dip buy高conviction名字** (L3) | Pre-earnings 3-5天小跌 | 市场hedging导致的非基本面下跌，期望值正 |
| **周期股blowout时全仓持有** | MU/能源/大宗类的超预期 | PEAD效应在低估值周期股最强，漂移持续60-90天 |
| **三连击时加仓**（Rev beat + EPS beat + Guidance raise） | 任何时候 | 概率最高的setup，错误率低 |
| **首先看Revenue beat而非EPS** | 所有财报 | Revenue=真实需求，EPS可以被cost cut操控 |
| **Gap IS the move时当日减仓** (META模式) | 大gap开盘（>10%） | 20天后-12.2%的案例说明gap后拿住=回吐收益 |
| **单笔earnings bet ≤ 8%** (L15) | 任何财报trade | 不确定性事件，仓位控制 |

### DON'T

| 禁止行为 | 原因 |
|---------|------|
| **追 >15% gap（L1）** | 当天追入者等于承接机构的出货，买在最高点 |
| **高PE（>50x）AI/科技股财报后加仓** | NVDA模式：beat就是sell the news的信号 |
| **只看EPS不看Guidance** | Revenue/Guidance才是定价变量，EPS是滞后指标 |
| **财报前已涨30%+还做earnings bet** | Pre-earnings run-up消化预期，实际beat=兑现=卖 |
| **把"82%公司beat"当做多理由** | Beat率高=预期已调低，市场对beat奖励越来越少 |
| **蜜月期后（8-10天）继续持有高估值财报反弹** (L7) | AI股蜜月期8-10天后开始回归，定时退出 |
| **用期权赌特定方向（除非implied move明显低估）** | Options IV财报前被高估，70-75%实际move < implied |

---

## 七、决策树（实战用）

```
Q1: 这是周期股还是高PE成长股？
├─ 周期股（PE<20x）+ Blowout beat → 买入，PEAD效应显著，持有60天
├─ 成长股（PE 20-40x）→ Q2
│   Q2: Revenue beat还是只有EPS beat？
│   ├─ Revenue beat → 看Guidance → 上调则买入，平或下调则观望
│   └─ 只有EPS beat（cost cut驱动）→ 不操作
└─ 高PE成长股（PE>40x）→ Q3
    Q3: Guidance方向？
    ├─ 强力上调Guidance → 当天买，持有8-10天（L7蜜月期）
    └─ 平或下调Guidance → 卖出/做空（beat是卖出机会）

Q4: Pre-earnings run-up >20%？
└─ 是 → 任何情况下都不追，等回调3-5天后评估（L1）
```

---

## 八、v4.0策略配置建议

1. **Earnings trade仓位上限**：单笔 ≤ 8%（L15不变），一个季度不超过3笔earnings bet
2. **最高胜率setup**：周期股底部 + 三连击（Revenue+EPS+Guidance） = 全力打
3. **最低胜率setup**：高PE AI股 + 只有EPS beat + pre-earnings已大涨 = 坚决不做
4. **PEAD应用**：beat后第3-5天entry（等短期sell-the-news消化），持有至60天
5. **Gap规则**：>10% gap当天减仓50%，>15% gap全部退出等回调

---

*来源: FactSet Earnings Insight 2025, StableBread analysis, Quantpedia PEAD research, heygotrade.com, kavout.com*

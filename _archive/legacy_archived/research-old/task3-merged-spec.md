# Task 3 完整规格：美股交易方法论重建 v4.0

> 合并来源：原定时任务prompt + H1回测125笔trade + Day 1-5自我诊断 + upgrade-spec-v4
> 今晚执行用。H2回测结果产出后补充到§数据输入。

---

## 任务定义

你是交易系统架构师。基于H1回测（125笔verified trades）+ H2回测（待补充）+ Day 1-5实盘诊断，重建Claude美股交易方法论。目标：从"跑不赢SPY"升级到"+5-8% alpha/月"。

---

## 数据输入（执行前必读）

### 输入1：H1回测总结
- 文件：`sim-portfolio/research-notes/h1/H1_SUMMARY.md`
- 关键数据：125笔trade, 72.3% WR, +5.10% avg, profit factor 4.46x
- 做空75% WR / +6.3% avg > 做多71% / +4.4%
- 20条core lessons（完整版在文件中）
- Agent 14 regime failure: FOMC鹰派后继续做多→40%胜率（全场最差）

### 输入2：H2回测总结
- 文件：`sim-portfolio/research-notes/h2/H2_SUMMARY.md`（6pm产出后补充）
- 覆盖2025-11-22 → 2026-05-21

### 输入3：Day 1-5实盘诊断
- 文件：`sim-portfolio/research-notes/self-review-day5.md`
- 文件：`sim-portfolio/research-notes/upgrade-spec-v4.md`
- A股+3.34% (alpha +2.8%) / 美股-0.93% (alpha -1.2%)
- 7个已诊断问题（按致命度排序）：
  1. 做空暴露=0（★★★★★）
  2. 散弹枪11只持仓太分散（★★★★）
  3. 方法论诊断了没执行（★★★★）
  4. Sizing与Conviction倒挂（★★★）
  5. Regime detection缺失（★★★）
  6. A股执行节奏失控（★★）
  7. Backtest lesson闲置（★★）

### 输入4：当前策略文件
- `sim-portfolio/strategy.md` — v3.0（需升级到v4.0）
- `sim-portfolio/CLAUDE.md` — 当前操作指南
- `sim-portfolio/watchlist_config.json` — 候选标的池
- `sim-portfolio/portfolio_state.json` — 当前持仓状态

### 输入5：已知美股方法论缺陷（5条，Day 1-5验证）
1. **过度淘汰**: 25+标的经过压力测试→0个通过20% bear case硬规则→空仓踏空
2. **共识=priced in在美股不成立**: AMD YTD+312%、FN YTD+207%都是共识股但持续涨
3. **反复说"等回调/等确认"**: 催化剂在前面的标的应该提前买，不是等确认后追高
4. **缺乏momentum维度**: 纯基本面分析忽略了美股趋势延续性
5. **A股逻辑套美股**: A股散户主导→热点轮动快→小票弹性大；美股机构主导→趋势持久→大票也有alpha

---

## 执行架构：两阶段，共~20个agent

### 阶段1：诊断（10个agent并行）

每个agent负责一个诊断维度。**必须引用H1/H2回测数据验证结论。**

| # | Agent | 任务 | H1/H2数据锚点 |
|---|-------|------|---------------|
| 1 | **Agent-Factor** | 过去1年美股什么factor赚钱？搜索factor ETF表现：MTUM/VLUE/IWF/QUAL/IWM vs SPY | H1 ticker leaderboard: AMD +92.8%, TSLA +63.9% 是momentum还是value？ |
| 2 | **Agent-Sector** | 板块轮动图谱。哪些板块什么时候领先？AI/能源/医药/金融/消费的相对强弱时间线 | H1月度数据：Jun(地缘) > Jul(银行) > Sep(降息) > Nov(鹰派) 板块轮动验证 |
| 3 | **Agent-Earnings** | Earnings surprise和股价反应关系。Beat后涨vs beat后跌的规律 | H1: AAPL beat但day1 -2.5%→+13.4%; AMZN beat但-8.3%; META beat但-18.8%(税务冲销) |
| 4 | **Agent-Momentum** | 动量策略实际表现。买52W新高 vs 超跌反弹胜率 | H1: 做多71%WR vs 做空75%WR; FPS(momentum A)表现优于SRUUF(momentum C-) |
| 5 | **Agent-Options** | 过去1年什么期权策略最赚钱？Covered call/protective put/straddle around earnings | H1: LULU Put +26.1%是最佳期权trade |
| 6 | **Agent-Sentiment** | Put-call ratio/VIX/AAII和市场方向关系 | H1 Agent 14: VIX signal missed → regime failure |
| 7 | **Agent-Flow** | ETF流入流出/13F/insider buying信号有效性 | H1: APP/HOOD S&P入选→机械买入+26.8%/+24.8% |
| 8 | **Agent-Macro** | 利率/美元/油价/中美对板块传导 | H1: Jackson Hole→GLD+7.4%; FOMC降息→IWM+3.5%; 以色列-伊朗→油价±7% |
| 9 | **Agent-China-Compare** | A股vs美股差异深度对比 | 实盘: A股+3.34%(alpha+2.8%) vs 美股-0.93%(alpha-1.2%)——同一个系统为什么差距这么大？ |
| 10 | **Agent-Mistake-Pattern** | AI选股普遍犯什么错？搜索"Claude AI stock picking mistakes" | 自我诊断: 散弹枪/sizing倒挂/方法论不执行/做空=0/regime blind |

### 阶段2：重建（10个agent并行）

基于阶段1诊断 + H1/H2回测lessons，构建方法论各模块。**每条规则必须有回测数据支持。**

| # | Agent | 任务 | 回测锚点/约束 |
|---|-------|------|--------------|
| 1 | **Agent-Screen** | 新筛选框架。多维度评分制替代bear case 20%硬门槛（momentum+基本面+催化剂+估值+资金流） | H1: bear case 4-tier已在v3.0引入但未执行。评分制需量化权重 |
| 2 | **Agent-Entry** | 入场时机框架。催化剂分类（earnings/政策/产品/M&A）+ 最优入场窗口 | H1 L1-L4: gap>15%不追/地缘事件前入场/财报前dip buy/NVDA空头等财报后 |
| 3 | **Agent-Position** | 仓位管理框架。解决sizing倒挂问题。Kelly变体？momentum加仓？conviction sizing？ | 实盘问题: SRUUF(C-) 8.1% > FPS(B+) 4.6%。H1 L15: 单笔earnings≤8%。H1 L16: 同方向选beta最高 |
| 4 | **Agent-Exit** | 退出框架。trailing stop vs fixed vs catalyst-based | H1: PLTR蜜月期8-10天→fade; AAPL day1-2.5%→+13.4%(固定止损会错杀) |
| 5 | **Agent-Short** | 做空/对冲框架。**核心模块**——回测证明空头是最强alpha | H1空头: 75%WR/+6.3%avg。L5-L9五条做空lesson。OKTA/LULU/SMR/TSLA/UNH全赢 |
| 6 | **Agent-Options-Strategy** | 期权策略模块 | H1: LULU Put+26.1%; MSFT Call+200%+ |
| 7 | **Agent-Risk** | 风控框架。Regime detection是核心 | H1 Agent14: FOMC转鹰后继续做多=40%WR。需要CME/VIX/yield curve三重信号 |
| 8 | **Agent-Calendar** | 催化剂日历系统化 | H1 L12: TSMC=NVDA领先指标。L13: S&P入选公告日买effective date卖 |
| 9 | **Agent-Independence** | 70-80%自主发现机会，不依赖用户输入 | 实盘问题: 等用户说才动，缺少主动扫描机制 |
| 10 | **Agent-Synthesis** | 汇总前9个agent输出 + 阶段1诊断，写成完整《美股交易系统v4.0》 | 见下方§最终产出 |

---

## 最终产出（Agent-Synthesis负责）

### 产出1：`US_TRADING_SYSTEM_V4.md`（独立完整文档）
- 可操作规则（不是抽象原则），每条有H1/H2数据支持
- 明确标出和A股方法论的差异
- 必须包含：筛选→入场→sizing→退出→做空→期权→风控→日历 完整链路
- 核心目标：**赚钱**，不是学术完美

### 产出2：`strategy.md` 升级到 v4.0
需要新增/修改的具体条目：

**新增：**
- §做空配置目标（10-15%暴露，Week 2起强制，每周三空头扫描）
- §集中度规则（美股≤7多头+2空头=9上限，最低建仓$7.5K，取消$3K试单）
- §Regime Detection协议（FOMC/CPI/NFP后强制检查，CME/VIX/yield curve三重信号）
- §方法论→执行强制链（rebalance建议后下一交易日必须执行P1）
- §H1/H2 Backtest Checklist（每笔建仓前check 20条lesson）

**修改：**
- §3.5 现金部署：增加触发价格要求，前3天未部署30%→强制建仓
- §美股筛选：从bear case 20%硬门槛改为多维度评分制
- §consensus处理：15/15看多 ≠ 排除，需看beat率和赛道扩张

### 产出3：`CLAUDE.md` 更新
- 新增L16（散弹枪禁令）、L17（执行链）、L18（空头强制）
- 催化剂日历补充每周三空头扫描
- 更新当前美股持仓ticker列表

### 产出4：`watchlist_config.json` 更新
- 升级short_candidates到"ready to execute"状态（含完整entry checklist）
- 新增GLD/IAU到对冲候选
- FPS/GEV目标仓位更新

### 产出5：诊断文件（中间产出）
- `diagnosis/agent-{name}.md`（10个诊断agent各一份）
- `system-v2/agent-{name}.md`（10个重建agent各一份）

---

## 执行约束

1. **所有结论必须有数据支持** — H1/H2回测数据、yfinance价格、搜索结果。不接受"一般来说"/"通常"
2. **Agent并行但不写同一文件** — 阶段1各写自己的diagnosis/，阶段2各写自己的system-v2/，最后Agent-Synthesis汇总
3. **Agent prompt ≤ 5个topic** — 每个agent聚焦自己的维度，不要越界
4. **强观点配强证据** — 不对冲、不免责式罗列。每个模块给出明确的"DO"和"DON'T"
5. **大刀阔斧修改没问题** — 推翻v3.0的错误观点是好事。核心是实用，不是保守
6. **用yfinance获取价格数据** — `pip install yfinance`
7. **用WebSearch搜索市场数据** — factor ETF表现、earnings反应统计等

---

## 成功标准

升级完成后，方法论必须能回答以下问题（用具体规则，不是模糊原则）：

1. 给我一只股票，我怎么在5分钟内决定买不买？（评分制）
2. 决定买了，什么时候入场？（入场窗口框架）
3. 买多少？（conviction→sizing映射）
4. 什么时候卖？（退出规则）
5. 什么时候做空？空什么？（做空框架）
6. 大盘突然转向怎么办？（regime detection）
7. 怎么确保方法论被执行而不是写完就放着？（执行链）

如果任何问题的答案是"视情况而定"而没有具体条件分支，就没过关。

---

## 和原始定时任务prompt的差异

| 维度 | 原始prompt | 本次合并版 |
|------|-----------|-----------|
| 数据输入 | 无（从零搜索） | H1回测125笔trade + H2回测 + Day 1-5实盘 |
| 问题诊断 | 5条已知缺陷 | 5条+7条自我诊断+20条backtest lessons |
| 版本目标 | v2.0 | **v4.0**（跳过v2/v3因为已在Day 1-5迭代过） |
| 产出范围 | 只写新文档 | 新文档 + **修改strategy.md/CLAUDE.md/watchlist** |
| 做空权重 | 1/10 agent | **核心模块**（回测证明是最强alpha） |
| 执行保障 | 无 | 方法论→执行强制链 + checklist |
| Regime | 1/10 agent | **P0优先级**（Agent 14教训） |

---

*本文件是今晚Task 3的完整执行spec。H2回测完成后，补充§输入2的数据锚点即可开始。*

# Task 3: 美股交易方法论重建 v4.0 — 优化后执行Prompt

> 基于: H1回测(125笔) + H2回测(待补充) + Day 1-5实盘诊断
> 用法: H2完成后手动执行。先跑阶段1（10 diagnosis agents），再跑阶段2（10 rebuild agents）
> 完整spec参考: task3-merged-spec.md

---

## 执行Prompt（完整版）

你是交易系统架构师。基于H1回测（125笔verified trades, 72.3% WR, +5.10% avg, profit factor 4.46x）+ H2回测 + Day 1-5实盘诊断，重建Claude美股交易方法论v4.0。

### 数据输入（执行前必读）

```
必读文件（按顺序）:
1. sim-portfolio/research-notes/h1/H1_SUMMARY.md — H1回测总结
2. sim-portfolio/research-notes/h2/H2_SUMMARY.md — H2回测总结（执行前确认已存在）
3. sim-portfolio/research-notes/self-review-day5.md — Day 1-5实盘诊断
4. sim-portfolio/research-notes/upgrade-spec-v4.md — 升级规格书
5. sim-portfolio/strategy.md — 当前v3.0策略
6. sim-portfolio/CLAUDE.md — 当前操作指南
7. sim-portfolio/watchlist_config.json — 候选标的池
8. sim-portfolio/portfolio_state.json — 当前持仓
```

### 已确认的7个系统性问题（按致命度排序）

1. **做空暴露=0**（★★★★★）— H1空头75%WR/+6.3% > 多头71%/+4.4%，但实盘5天0空头
2. **散弹枪11只太分散**（★★★★）— 5只2%试单贡献alpha≈0，top 20 trades avg +18% vs 全部+5.1%
3. **方法论诊断了没执行**（★★★★）— v3.0写了rebalance建议但5天只动了FPS 60股
4. **Sizing与Conviction倒挂**（★★★）— SRUUF(C-) 8.1% > FPS(B+) 4.6%
5. **Regime detection缺失**（★★★）— Agent 14因FOMC鹰派后继续做多→40%WR全场最差
6. **A股执行节奏失控**（★★）— Day 1-4现金70%→Day 5一天砸¥145K
7. **Backtest lesson闲置**（★★）— 20条lesson写了没用过

### 5个美股方法论结构性缺陷

1. 过度淘汰: 25+标的→0通过→空仓踏空
2. 共识=priced in在美股不成立: AMD YTD+312%都是共识股
3. 反复"等回调/等确认": 催化剂在前面应提前买
4. 缺乏momentum维度: 纯基本面忽略趋势延续性
5. A股逻辑套美股: 散户→机构主导差异

---

## 阶段1: 诊断（10个agent并行）

**每个agent必须引用H1/H2回测数据验证结论。不接受"一般来说"/"通常"。**
**每个agent写自己的文件到 `sim-portfolio/research-notes/diagnosis/` 目录。**

### Agent-1-Factor
```
任务: 过去1年美股什么factor赚钱？
执行:
1. WebSearch搜索factor ETF过去1年表现: MTUM vs VLUE vs IWF vs QUAL vs IWM vs SPY
2. 用yfinance获取6个ETF的1年价格数据，计算回报率
3. 分析: momentum vs value vs growth vs quality，哪个factor占优？
4. 对照H1数据: AMD +92.8%, TSLA +63.9%是momentum还是value驱动？
5. 结论: 当前regime下应该倾向什么factor？

输出: diagnosis/agent-factor.md（含数据表格+结论，2000字以内）
```

### Agent-2-Sector
```
任务: 板块轮动图谱
执行:
1. WebSearch搜索过去1年各板块ETF表现(XLK/XLE/XLF/XLV/XLY/XLC/XLI/XLRE/XLU/XLP/XLB)
2. 用yfinance获取11个板块ETF月度表现
3. 绘制轮动时间线: 哪个板块什么时候领先？
4. 对照H1月度数据验证: Jun(地缘)→Jul(银行)→Sep(降息)→Nov(鹰派)
5. 识别当前领先/落后板块

输出: diagnosis/agent-sector.md
```

### Agent-3-Earnings
```
任务: Earnings surprise与股价反应关系
执行:
1. WebSearch搜索"earnings surprise stock price reaction 2025 2026 statistics"
2. 搜索具体案例: beat后涨 vs beat后跌的规律
3. 对照H1数据:
   - AAPL beat day1 -2.5%→最终+13.4%（beat但先跌后涨）
   - META beat但-18.8%（税务冲销黑天鹅）
   - CRM beat但-7.9%（priced in）
4. 分析: 什么条件下beat=涨？什么条件下beat≠涨？
5. 可操作框架: earnings trade的DO和DON'T

输出: diagnosis/agent-earnings.md
```

### Agent-4-Momentum
```
任务: 动量策略实际表现
执行:
1. WebSearch搜索"momentum strategy US stocks 2025 2026 performance"
2. 对比: 买52周新高 vs 超跌反弹 vs trend-following的胜率数据
3. 用yfinance验证: 过去1年买入52周新高的股票20天后平均表现
4. 对照H1: 做多71%WR vs 做空75%WR; FPS(momentum A)表现
5. 结论: momentum应该在筛选框架中占多少权重？

输出: diagnosis/agent-momentum.md
```

### Agent-5-Options
```
任务: 什么期权策略最赚钱？
执行:
1. WebSearch搜索"best options strategies 2025 2026 performance covered call protective put"
2. 分析: covered call / protective put / straddle / earnings play各自适用场景
3. 对照H1: LULU Put +26.1%是最佳期权trade，TSLA Short Put +13.1%
4. 期权vs正股: 什么时候用期权替代正股？杠杆vs时间损耗权衡
5. 可操作建议: 模拟盘应该怎么用期权？

输出: diagnosis/agent-options.md
```

### Agent-6-Sentiment
```
任务: 情绪指标与市场方向关系
执行:
1. WebSearch搜索"put call ratio VIX AAII sentiment 2025 2026 market prediction"
2. 获取VIX历史数据(yfinance ^VIX)，分析VIX水平与后续市场表现关系
3. 搜索AAII牛熊比历史数据，极端值的反转信号
4. 对照H1 Agent 14: VIX signal missed→regime failure，如果有VIX监控会怎样？
5. 可操作信号: 什么VIX水平/AAII读数应该触发行动？

输出: diagnosis/agent-sentiment.md
```

### Agent-7-Flow
```
任务: 资金流信号有效性
执行:
1. WebSearch搜索"ETF fund flows 2025 2026 stock market prediction"
2. 搜索"13F filings big fund positions 2025 2026"
3. 搜索"insider buying selling signals effectiveness"
4. 对照H1: APP/HOOD S&P入选→机械买入+26.8%/+24.8%
5. 可操作框架: 哪些资金流信号值得关注？S&P入选策略如何复制？

输出: diagnosis/agent-flow.md
```

### Agent-8-Macro
```
任务: 宏观变量对板块传导
执行:
1. WebSearch搜索"interest rate dollar oil price sector impact 2025 2026"
2. 用yfinance获取: 10Y yield(^TNX), DXY(DX-Y.NYB), 油价(CL=F), 金价(GC=F)
3. 分析传导链: 利率→科技估值, 美元→出口商, 油价→能源+消费
4. 对照H1: Jackson Hole→GLD+7.4%; FOMC降息→IWM+3.5%; 以色列-伊朗→油价±7%
5. 关税冲击传导(H2独有): 关税→哪些板块受损/受益？

输出: diagnosis/agent-macro.md
```

### Agent-9-China-Compare
```
任务: A股vs美股差异深度对比
执行:
1. WebSearch搜索"A shares vs US stocks market structure differences"
2. 分析结构差异: 散户/机构比例, 涨跌停, T+1/T+0, 做空机制, 注册制
3. 分析策略差异: A股热点轮动快/美股趋势持久, A股小票弹性大/美股大票也有alpha
4. 对照实盘: A股+3.34%(alpha+2.8%) vs 美股-0.93%(alpha-1.2%)——同一系统为什么差距这么大？
5. 可操作结论: 哪些A股策略不能直接套美股？哪些可以？

输出: diagnosis/agent-china-compare.md
```

### Agent-10-Mistake-Pattern
```
任务: AI选股普遍犯什么错？
执行:
1. WebSearch搜索"AI stock picking mistakes common errors 2025 2026"
2. WebSearch搜索"Claude AI investment mistakes" / "ChatGPT stock picking performance"
3. 分析AI选股的系统性偏差: 共识偏差/recency bias/过度分散/不会做空等
4. 对照自我诊断: 散弹枪/sizing倒挂/方法论不执行/做空=0/regime blind
5. 哪些错误是AI特有的？哪些是通用的？如何针对性修正？

输出: diagnosis/agent-mistake-pattern.md
```

---

## 阶段2: 重建（10个agent并行）

**基于阶段1诊断 + H1/H2 lessons构建方法论各模块。每条规则必须有回测数据支持。**
**每个agent写自己的文件到 `sim-portfolio/research-notes/system-v4/` 目录。**

### Agent-11-Screen（筛选框架）
```
任务: 设计新的多维度评分筛选框架，替代bear case 20%硬门槛

必读: diagnosis/agent-factor.md, diagnosis/agent-momentum.md

设计要求:
1. 5个维度打分(每维度1-10分): Momentum / 基本面 / 催化剂 / 估值 / 资金流
2. 每个维度定义明确的评分标准（不是模糊描述）
3. 总分→等级映射: S(≥45) / A(38-44) / B(30-37) / C(22-29) / T(<22)
4. 保留bear case检查但不再是一票否决（改为估值维度的一个输入）
5. 用H1 top 10 winners和top 10 losers回测验证评分系统
6. 与A股筛选框架的差异必须标明

输出: system-v4/screening-framework.md（含评分卡模板+回测验证）
```

### Agent-12-Entry（入场时机）
```
任务: 设计入场时机框架

必读: diagnosis/agent-earnings.md, H1 Lessons L1-L4

设计要求:
1. 催化剂分类: Earnings / 政策 / 产品发布 / M&A / 指数调整 / 宏观事件
2. 每类催化剂的最优入场窗口（天数）
3. GAP规则: >15%不追(L1), 具体的"等X天"量化标准
4. 财报交易框架: pre-earnings dip buy vs post-earnings fade
5. 宏观事件入场: 地缘前入场(L2), FOMC/CPI后反应
6. 用H1/H2数据验证每条规则的胜率

输出: system-v4/entry-framework.md（含决策树+每条规则的回测验证）
```

### Agent-13-Position（仓位管理）
```
任务: 解决sizing与conviction倒挂问题

必读: diagnosis/agent-factor.md, H1 Lessons L15-L18, self-review-day5.md §问题4/§问题5

设计要求:
1. Conviction→Sizing明确映射: S/A/B/C/T → 最大仓位% → 初始建仓%
2. Kelly变体? Momentum加仓? 还是固定分级? — 选一个并论证
3. 集中度规则: 最多几只多头 + 几只空头
4. 最低建仓金额（消灭$3K试单）
5. 加仓/减仓规则: 什么触发加仓？什么触发减仓？
6. 用H1数据验证: 如果按新规则sizing，整体表现会怎样？

输出: system-v4/position-framework.md
```

### Agent-14-Exit（退出框架）
```
任务: 设计退出规则

必读: diagnosis/agent-earnings.md, H1 Lessons L7/L11

设计要求:
1. 三种退出类型: 止损退出 / 目标退出 / 催化剂退出
2. 止损: 固定% vs trailing vs 催化剂based？什么情况用哪种？
3. H1教训: AAPL day1 -2.5%→+13.4%（固定止损会错杀）, PLTR蜜月期8-10天→fade
4. 时间止损: 持仓超过X天无催化剂→评估退出
5. 分批退出: 催化剂当天减半 vs 一次全退？
6. 用H1/H2数据验证: optimal holding period是多少天？

输出: system-v4/exit-framework.md
```

### Agent-15-Short（做空框架）★核心模块★
```
任务: 设计完整做空/对冲框架（H1证明空头是最强alpha）

必读: diagnosis/agent-sentiment.md, H1 Lessons L5-L9, H1 top 10 winners中的空头案例

设计要求:
1. 空头分类: 结构性空头(UNH DOJ) / 催化剂空头(earnings miss) / 估值空头(bubble) / 对冲空头(index put)
2. 每类空头的胜率和平均收益（从H1/H2数据提取）
3. 空头筛选标准（对应多头的评分制）
4. 空头仓位规则: 总暴露目标10-15%, 单只上限, 止损规则
5. 每周三空头扫描协议（具体步骤）
6. 做空的DO和DON'T（强观点，配H1数据）
7. H1空头全胜记录回测: SMR/LULU/OKTA/PLTR/UNH — 共性是什么？

输出: system-v4/short-framework.md
```

### Agent-16-Options-Strategy（期权策略）
```
任务: 设计期权使用框架

必读: diagnosis/agent-options.md, H1 LULU Put / MSFT Call案例

设计要求:
1. 什么时候用期权替代正股？（杠杆/有限亏损/方向性对冲）
2. Earnings期权策略: straddle vs directional，什么条件选什么
3. 保护性策略: 什么时候买put对冲？成本计算
4. 期权sizing: 期权仓位占总portfolio的上限
5. 期权到期管理: 什么时候roll vs close
6. 简单规则优先（模拟盘不搞复杂Greeks）

输出: system-v4/options-framework.md
```

### Agent-17-Risk（风控框架）★P0优先级★
```
任务: 设计Regime Detection和风控系统

必读: diagnosis/agent-sentiment.md, diagnosis/agent-macro.md, H1 Agent 14 failure案例

设计要求:
1. Regime Detection协议（三重信号）:
   - CME Fed Fund Futures变化（>15bp = signal）
   - VIX变化（>3点 = signal）
   - 2Y-10Y利差变化
2. 事件后强制检查: FOMC/CPI/NFP后24h内必须执行
3. Regime结论: unchanged / shifted dovish / shifted hawkish
4. Regime shift后的行动协议: 24h内调整方向的具体步骤
5. 组合层面风控: max drawdown / sector concentration / correlation
6. 用H1 Agent 14数据验证: 如果有regime detection，能避免多少亏损？

输出: system-v4/risk-framework.md
```

### Agent-18-Calendar（催化剂日历）
```
任务: 催化剂日历系统化

必读: H1 Lessons L12/L13, diagnosis/agent-earnings.md

设计要求:
1. 月度固定事件: FOMC(8次/年) / CPI(12次) / NFP(12次) / 财报季(4次)
2. 催化剂链条: TSMC→NVDA领先指标(L12), S&P入选公告→effective date(L13)
3. 每周三空头扫描日
4. 每次事件的pre-trade checklist
5. 催化剂过期处理: 催化剂落地后holding period多久？
6. 日历维护协议: 谁更新？多久更新一次？

输出: system-v4/calendar-framework.md
```

### Agent-19-Independence（自主发现机制）
```
任务: 设计70-80%自主发现机会的机制

必读: diagnosis/agent-flow.md, diagnosis/agent-sector.md

设计要求:
1. 每日主动扫描协议: 看什么？扫描频率？扫描工具？
2. 异常检测: 什么信号应该触发"这里有机会"？
3. 减少对用户输入的依赖: 现在是用户说才动，目标是主动发现
4. 信息源定义: 财经新闻/SEC filings/social media/ETF flows
5. 从信号到trade idea的决策流程
6. 与筛选框架(Agent-11)的衔接: 发现→筛选→入场

输出: system-v4/independence-framework.md
```

### Agent-20-Synthesis（汇总）★最重要★
```
任务: 汇总前19个agent输出，写成完整交易系统v4.0

必读: 所有 diagnosis/ 和 system-v4/ 文件

产出清单:

1. **US_TRADING_SYSTEM_V4.md**（独立完整文档）
   - 完整链路: 筛选→入场→sizing→退出→做空→期权→风控→日历
   - 每条规则有H1/H2数据支持
   - 标出和A股方法论的差异
   - DO和DON'T清单
   - 核心目标: 赚钱，不是学术完美

2. **strategy.md 升级到 v4.0**
   新增: §做空配置 / §集中度规则 / §Regime Detection / §执行强制链 / §Backtest Checklist
   修改: §3.5现金部署 / §美股筛选 / §consensus处理

3. **CLAUDE.md 更新**
   新增: L16散弹枪禁令 / L17执行链 / L18空头强制
   更新: 催化剂日历 / 持仓ticker列表

4. **watchlist_config.json 更新**
   - short_candidates升级到ready-to-execute
   - 新增GLD/IAU到对冲候选
   - FPS/GEV目标仓位更新

汇总原则:
- 从19个agent取精华，不是堆砌
- 有冲突的规则选回测数据支持更强的那个
- 每条规则必须可操作（不是抽象原则）
- 总页面控制在50页以内（太长没人看）
```

---

## 执行约束（所有agent遵守）

1. **数据支持** — 每条结论引用H1/H2数据、yfinance价格或搜索结果。不接受"一般来说"
2. **不写同一文件** — 阶段1各写diagnosis/，阶段2各写system-v4/，Agent-20最后汇总
3. **Prompt ≤ 5 topics** — 每个agent聚焦自己的维度
4. **强观点配强证据** — 不对冲、不免责式罗列。每个模块给"DO"和"DON'T"
5. **推翻v3.0是好事** — 核心是实用，不是保守
6. **用yfinance获取价格** — `yf price TICKER` 或 `pip install yfinance`
7. **用WebSearch搜索** — factor ETF、earnings统计等
8. **每个agent输出 ≤ 3000字** — 简洁有力，不是面面俱到

## 成功标准

升级完成后，方法论必须能用**具体规则**（不是"视情况而定"）回答：

1. 给我一只股票，5分钟内决定买不买？→ 评分制5维度打分
2. 决定买了，什么时候入场？→ 催化剂分类+入场窗口
3. 买多少？→ conviction→sizing映射表
4. 什么时候卖？→ 三种退出类型+时间止损
5. 什么时候做空？空什么？→ 空头分类+筛选标准+每周三扫描
6. 大盘突然转向怎么办？→ regime detection三重信号+24h行动协议
7. 怎么确保方法论被执行？→ 执行强制链+checklist

---

*H2回测完成后，补充H2数据到各agent prompt中的回测锚点，然后执行。*

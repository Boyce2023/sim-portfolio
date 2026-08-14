# 硬熔断层 — A股交易决策前必读（≤15条）

> **这是什么**: 每次涉及"买/卖/持有/仓位"决策时，过一遍这15条。不是知识，是闸门——任一条命中就先处理它，再继续原来的分析。
> **不是什么**: 不是完整方法论。数字/参数以 `sim-portfolio/strategy_astock.md` 为准（本层不重复数值，避免和代码/策略文档drift）。完整推理见 `principles.md`；案例见 `cases/INDEX.md`。
> **来源**: 从86个feedback文件中萃取(D3重构, 2026-08-14)。每条标了源文件，要看完整论证/事故经过，去源文件或`_archive`区读原文。

---

### G1 ⛔⛔ 模拟盘调仓买卖 = 自主决策+执行+事后报告，不问"要不要"
问用户执行意见 = 违规，触发自罚。真正不可逆的对外/删除/真实资金动作除外(那些仍需点名式授权)。
*源: feedback_autonomous_execution.md(07-09) + feedback_no_inferred_authorization.md(07-30) + feedback_monitor_autonomous_exec.md(06-26)*

### G2 ⛔⛔ 永不用残缺数据下结论
多步任务(扫描/workflow/批量)没100%完整跑完，绝不给结论。中途失败=诊断根因→彻底修复→完整重跑→验证所有step→才给。Constitutional级。
*源: feedback_complete_data_only.md(06-30)*

### G3 ⛔ A股数据只用 astock_data_layer / 腾讯 / 本地yf CLI，禁 `import yfinance`
yfinance对A股是淘汰源(市值可错10倍)。派agent取数prompt必须显式写这条约束(子进程不继承拦截器)。
*源: feedback_data_sources.md(06-01, 06-16扩展) — 对应CLAUDE.md D12*

### G4 ⛔ A股建仓门槛 = SABCT ≥ A-，B+以下只进观察池
UASS/扫描结果不构成建仓理由，必须完成产品级研究。18天实盘：研究驱动建仓全盈利(+10~14%)，扫描驱动建仓全亏损(-4%~-7%)。
*源: feedback_system_reset_v12.md(06-05) + feedback_uass_system.md v4.0 + feedback_sabct_system.md*

### G5 ⛔⛔ 卖出/持有只认5(6)道出场门，哪道先响走哪道
①破前10日低 ②灾难线-12%(绝对地板) ③round-trip(峰值+15%吐回) ④thesis证伪 ⑤催化兑现 ⑥regime转空。**破位+灾难线同破=无条件出，thesis/信心/催化都不能override。** 没门响=让利润跑，禁单日结论(判持仓强制看30-60天结构)。
*源: feedback_integrated_trend_system.md(07-09 PIT定稿) — 对应CLAUDE.md T18*

### G6 ⛔⛔ 扫描/agent名单物理上不得作为已建仓标的的卖出理由
"扫描未重现"/"52-agent未入围"/"TB降档"一律不构成卖出信号，也不得作为绕过A-门槛的建仓理由。去留只由thesis-delta三问(供给约束/主beta/催化时间线变了吗)判定。07-01复盘：这一条违反栽了8+只票。
*源: feedback_replay_hold_discipline.md(07-01) — 对应CLAUDE.md T14*

### G7 ⛔⛔ 冲动追涨/换仓断路器：计划外买入先过两问
手里那只预期打破了吗？你是不是看它涨了才想买？两问不过=拦下，30秒冷静期。Buwen亲述"80%亏损来源"。每早写死当日买入清单，盘中清单外=非法。
*源: feedback_impulse_buy_circuit_breaker.md(07-10) — 头号交易铁律*

### G8 ⛔ 基本面×涨跌二维独立，涨跌永不否决基本面
基本面轴定"值不值得买"，量价轴定"买入时机"。基本面好+主升中=更该买，不是该reject。涨幅大本身不是末段信号，看量价结构(放量上涨vs放量滞涨)。06-30三次扫描59埋伏→0建仓的死锁教训。
*源: feedback_screening_two_axis.md(06-30)*

### G9 ⛔ PEG唯一估值锚；供需是唯一锚，卖方目标价不用
单一PE数字永远不构成买卖理由，必须配G(来源G1guidance/G2订单/G3斜率/G4产能)成PEG。不引用/不参考卖方目标价，即使用户没问也不主动提。Constitutional级，A股+美股通用。
*源: feedback_valuation_peg.md(05-29)*

### G10 ⛔⛔ 写下的计划，执行时不许自己改
建仓卡片白纸黑字的仓位/标的，实际下单不得超过计划。要超必须有计划时未知的新基本面事实(订单/产能/催化剂确认)，"它涨了/板块很强/怕踏空"不构成理由。08-10当天买超计划4倍被撤销10笔的事故。
*源: feedback_plan_integrity.md(08-10)*

### G11 ⛔ 仓位灵活总纲：出击重仓，防守等待；禁感受仓
防守期(普跌/regime差)现金厚40-50%+只守深研核心；出击期(主升+深研高信念)集中3-5个单标的15-20%重仓。扫描出probe≠建仓，建仓门槛="敢不敢下15-20%重仓"，不建5%感受仓凑数。
*源: feedback_position_flexibility.md(07-07, 07-08两次震怒纠错)*

### G12 ⛔ 主动监控：持仓异常先flag，宏观讨论必连持仓
单日变动>±5%/累计回撤>25%的持仓必须主动review，不等用户问。讨论宏观/板块话题时若有相关持仓，必须在同一回复中说影响。AVGX -45%全程未flag的教训。
*源: feedback_proactive_monitoring.md(06-11) — 对应CLAUDE.md T2/Q5*

### G13 ⛔ A股/美股方法论完全独立，不跨市场套用逻辑
A股：催化剂驱动+momentum优先+供给侧验证；美股：价值投资×科技信仰。两个系统交叉点只在信息层，方法论层完全隔离。session级隔离，脚本必须显式`--market`。
*源: feedback_astock_us_separation.md + feedback_market_isolation.md*

### G14 ⛔ 后台任务必须验活，死因未知不许编因果
起完workflow 2-5分钟内验活一次，之后每次报进度前实际查一次。技术故障没日志证据就写"未知"，时间吻合≠因果。08-10同一天两次workflow死亡3天没发现的事故。
*源: feedback_plan_integrity.md(08-10) ②③*

### G15 ⛔ 买入前查催化剂是否已兑现
任何建仓前两问：①该标的最近一期定期报告披露了吗？②如果已披露，市场反应幅度多大？已兑现且股价已大幅反应=不得再列为"前瞻催化剂"。08-14发现两笔买入实为买在利好兑现后第3-4天。
*源: feedback_plan_integrity.md(08-14追加) ④ — 已写入 astock_scan_sop.md R9*

---

## 用法
1. 涉及买/卖/持有/仓位的每次决策，先扫一遍这15条标题，命中的展开读。
2. 不确定某条是否还有效 → 查 `strategy_astock.md` 顶部的"效力警告"区(它会标注哪些memory规则已被更新的实盘回测取代)。
3. 这15条不是全部——完整的"情境→行动→原因→证据"在 `principles.md`；这里只是最高频/最高代价的子集。
4. 新增硬熔断规则的门槛：连续违反同一条≥2次，或用户"震怒/连纠"级别的事故 → 才升级进本文件，防止≤15的预算被灌水。

# 美股专属交易原则（隔离区 — A股session不读本文件）

> **市场隔离铁律**: 本文件+`data_discipline_us.md`仅供美股session boot使用。A股session不读、不引用、不展示本区内容(feedback_market_isolation.md + feedback_astock_us_separation.md)。放在同一个`memory_trading/`父目录下纯粹是共享交易记忆基础设施(备份/归档/索引机制)，不代表内容共享。
> 来源：D3重构(2026-08-14)，从美股专属的feedback文件提炼(与A股(a)(b)(e)分类同批筛出，但按市场隔离原则单独隔区)。

---

## 1. 现金是亏损仓位（第零原则）

WHEN 非BEAR regime，账户有闲置现金 → THEN 视现金为"每天跑输QQQ的亏损仓位"，满仓/杠杆是基准状态不是"激进" → WHY BULL regime下现金年化~4% vs QQQ年化~20%，"安全"是幻觉——你没亏钱但确定性跑输benchmark → *aggressive_stance.md*

**Aggression Gate（执行任何交易批次≥2笔前的3项机械检查）**：
- Gate1净敞口：买入≥卖出×0.9(允许10%净减仓margin)
- Gate2杠杆：1.80x(BULL硬下限)≤目标~2.0x≤2.0x(硬上限)，卖出个股后必须同批次用ETF补回等额敞口
- Gate3新仓sizing：B级≥10%，A级≥15%，C级观察仓例外
- Gate4现金拖累：BULL regime下正现金>5%净值=BLOCKED

**唯一例外**: Regime=BEAR 或 用户明确说"保守/降杠杆"。

## 2. 杠杆ETF大跌不等于thesis变

WHEN 3x杠杆ETF(SOXL/TQQQ等)短期大跌 → THEN 先问"thesis变了吗"(如SOX指数跌8%不等于半导体周期结束)，thesis没变=持有或加仓，不是清仓 → WHY 清仓+重买=锁亏+摩擦成本，最蠢的操作；3x杠杆日内波动30%是正常特征不是bug → *soxl_lesson.md(SOXL $280→$182清仓后又买回同价的教训)*

## 3. "美股全面扫描"= 固定动作链，不用用户细说

WHEN 用户说"美股全面扫描" → THEN 按序执行：①push(update_prices+push_all) ②宏观模块(macro_scan.py: 利率/VIX/DXY/商品/Regime) ③6阶段非持仓OUS扫描(排除已持仓，走Workflow后台) ④完整报告(OUS 6区格式) → WHY 用户不想每次重复讲全流程要求 → *us_full_scan_command.md(06-24) — 报告格式见 ous_report_format.md(未migrate，仍在原memory/位置)*

## 4. 视野开放：Pod管仓位不管研究范围

WHEN 用户提到不在预设Pod(PEAD+AI infra)里的标的(航空/消费/周期) → THEN 默认"让我认真看看"，不因行业不匹配自动降低兴趣 → WHY 系统性窄视野错过DAL(BRK $26.5亿建仓)、铠侠等机会；Pod是仓位管理工具不是研究筛选器 → *此原则市场通用，完整版见 `../research_methodology.md` §5，此处仅标注美股Pod架构的具体应用*

---

## 5. 三层beta嵌套 — 大beta必须对，alpha全部来自选股（Buwen投资宪法，08-14）

WHEN 任何仓位/择时判断 → THEN 分清三层精度要求：大beta(几年尺度)必须正确/中beta(半年)70-80%/小beta(月度)50%胜率即可；alpha完全来自选股，beta只决定站位对不对不产生alpha → WHY 30-agent自审：真实alpha(去杠杆)全周期−3.33pp，与SPY相关系数仅0.148=没有大beta的数学指纹；"能非常有效地不亏钱，但没有机制迫使它去赚该赚的钱——不是在市场上下注，是在自己的规则里下注" → *feedback_three_layer_beta.md(08-14)，完整30-agent病历见 sim-portfolio/research-notes/us-database/2026-08-14_30agent自审病历.md*

**⛔ 关键缺口**：全部规则族盘点后，没有一条负责"顺势而为"——每条都是"当X发生时不要做Y"，暴跌侧有T2/T18/灾难线，**暴涨侧/踏空侧一个进攻触发器都没有**。大beta裁决(48-agent)选定三条主战场：电力实体层(核心)/西方国防重装/铀(卫星)，"买约束不买最被叙事化的名字"。

**五个反直觉发现(升级时勿凭直觉浪费规则去治不存在的病)**：①不存在处置效应(赢家持仓8.45天>输家7.01天) ②大赢家止盈时点大多对，真卖飞仅2/29笔 ③T14在美股净正但只是下限保护非进攻机制 ④8月"少动"本身没错，错的是不动的内容 ⑤交易频率与收益相关性不显著(r≈−0.21)。

*详细48-agent大beta裁决见 sim-portfolio/research-notes/us-database/2026-08-14_大beta裁决_CIO排序.md*

---

## Related
[[data_discipline_us.md]] — A股对应版见 `../principles.md`(内容不互通，仅结构对称)

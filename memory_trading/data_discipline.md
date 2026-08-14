# 数据纪律层 — A股交易数据规则

> 覆盖：数据源选型、复权口径、信息时效、完整性。美股数据栈见 `us_market/data_discipline_us.md`(市场隔离，不进A股session boot)。
> 来源：D3重构(2026-08-14)，从(b)数据纪律类6个feedback文件提炼。

---

## 1. 数据源分层（禁yfinance是Constitutional级）

| 层级 | 数据源 | 用途 | 覆盖 | 备注 |
|------|--------|------|------|------|
| 主源 | akshare `stock_zh_a_spot_em()` | 全量行情 | 5,500+ | 3秒 |
| 备源 | push2delay.eastmoney.com HTTPS | 全量行情 | 5,857 | EM代理挂时兜底 |
| 验证 | baostock | T+0日线+行业+财务 | 5,494(无北交所) | 慢 |
| 批量价格 | 腾讯qt.gtimg.cn | 收盘价批量 | ~4,800 | 12秒/900只 |
| 专项 | akshare涨停/龙虎/北向 | 涨停池+龙虎榜+北向 | 各自完整 | 快 |
| 单季财务 | akshare `stock_financial_abstract` | 单季净利/毛利率拐点 | — | 前瞻PE计算必用单季，不用TTM冒充单季 |

**⛔ 禁用**: `import yfinance` 取A股任何数据(价格/市值/PE/涨跌幅)。yfinance对A股是淘汰源——曾导致宏和/鼎泰市值少算10倍、生益报183实为179。yfinance仅用于A股数据的交叉验证(差异<2%才采信)，不作主源。

**⛔ 规则必须显式注入subagent prompt**：主脑记得"A股禁yfinance"，但派出去的workflow subagent是独立进程，不继承CLAUDE.md/memory/本地拦截器(YFinanceCNBlocker只拦本地`yf` CLI)。任何让subagent取A股定量数据的prompt，必须显式写明数据源约束，否则agent会自己`import yfinance`拉出脏数据(PCB研究曾因此把生益183写成误差)。

**主脑取数优先级**: `astock_data_layer.get_batch_prices()` → 市值/PE字段为0时用eastmoney f116/f162或腾讯qt.gtimg补 → 都不用yfinance。

*源: feedback_data_sources.md(06-01审计+06-09/06-16两次违反后升级) — 对应CLAUDE.md D12*

---

## 2. 复权口径

**A股数据源(astock_data_layer/eastmoney)是不复权(真实成交价)**；用户/多数炒股软件默认看**前复权**图表。送转(如10转3)会造成两套价差一个factor。

- 报历史价/做跨期对比前先自检口径，主动声明差异
- 查标的近期有无送转(年报方案 + K线是否有大缺口)
- 持仓若held through送转ex-date，系统不自动除权：avg_cost和shares需手动按factor调整(÷1.3 / ×1.3)，否则P&L显示假亏
- `update_prices.py`已加除权检测(单日跌>11%疑似除权)，触发时先核对送转方案再信P&L

*源: feedback_fuquan_chuquan.md(06-16安集事故)*

---

## 3. 信息时效与真实性

**事件/催化剂报告强制标"首次公开日期"**：Agent看到"提到X"容易自动归类为"发布X"，但大多数会议80%内容是重复旧闻。三级分类：
- A-新: 此前无任何公开来源提及 → 可称"首次公布"
- B-确认: 此前有传闻，今天官方首次确认 → "正式确认，此前有传闻"
- C-重提: 此前已发布，今天再提 → "重申"或不提，零信息量

只有A级可作为"新催化剂"影响交易判断。Agent prompt模板必须要求"搜索最早公开提及日期，找不到才能标NEW"。

**Portfolio数据引用前必须交叉验证**：PEG/Fwd PE/催化剂日期，用`yf quote`(美股)或astock_data_layer(A股)核对，不一致以实时数据为准并更新SSOT。SSOT本身也会有脏数据。

*源: feedback_information_quality.md(06-01 COMPUTEX事故)*

---

## 4. 实时行情问答：先取数后开口

用户问任何价格/涨跌幅问题：**第一个动作是取数(A股用astock_data_layer/腾讯，美股用yf)，不是WebSearch**。WebSearch搜到的数字来源杂(不同时间点/不同网站/转载误差)，直接输出=传播脏数据。原因/新闻/定性分析才用WebSearch补充，且WebSearch数字要与实时数据交叉验证，不一致以实时数据为准。

**3轮上限**：同一问题搜索3轮仍无答案，立即说"搜不到"+推测(标注)，不继续搜第4轮。

**产品确认优先**：用户说"我买的XX"时先确认具体产品(ticker/交易所/产品类型)，不猜测。

*源: feedback_realtime_data_discipline.md(06-10海力士事故，KOSPI数字连错5轮才认)*

---

## 5. 完整性铁律（Constitutional级）

任何多步任务(扫描/workflow/批量分析)，没有100%完整跑完，绝不给结论。

- 禁止：用部分完成的结果拼凑/推断"完整结论"；用"已完成的部分先给你"代替完整交付
- 中途失败(卡死/数据源挂/agent hung) → 诊断根因 → 彻底修复(换工具/修数据源) → 完整重跑 → 验证所有step都出真实结果 → 才给结论
- 20分钟无进展或20次同类报错 = 立即主动复查修复，不反复重试拖时间，不等用户问

*源: feedback_complete_data_only.md(06-30用户震怒) — 亦见 hardgate G2，Constitutional级*

---

## Related
[[principles.md]] [[research_methodology.md]] — 对应CLAUDE.md D1/D2/D9/D10/D11/D12

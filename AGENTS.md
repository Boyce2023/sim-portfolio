# Sim-Portfolio 双本账交易总纲（2026-10-29 瘦身零冲突定版）

> **完整历史归档**：`docs/90_内部_给Claude读/archive_sim_portfolio_AGENTS_20261029.md`（原8-9月SABCT、五道门、午间/收盘强制调仓、B策略3成专户等旧规已全部废止，严禁再引用）。

## 一、双本账物理隔离铁律（2026-10-20 Buwen 定）
1. **A股（实盘+模拟盘）走纯机械账**：
   - **唯一现行准则**：[`sim-portfolio/strategy_astock.md`](/Users/huaichuaibeimeng/claude-projects/sim-portfolio/strategy_astock.md)
   - **核心数据与盘中工具**：取价统一用 `astock_data_layer.get_batch_prices`（严禁 `yfinance`）；盘中异动与竞价核查用 `python3 sim-portfolio/scripts/astock_intraday_check.py`（1秒直出 `000002` 等基准 10日100% 硬异动线、93%提前线及近10日公告次数）。
2. **美股（实盘+模拟盘）走慢账**：
   - **唯一现行准则**：[`sim-portfolio/strategy_us.md`](/Users/huaichuaibeimeng/claude-projects/sim-portfolio/strategy_us.md) + [`sim-portfolio/US_HANDOFF.md`](/Users/huaichuaibeimeng/claude-projects/sim-portfolio/US_HANDOFF.md)
   - **核心机制**：代码级切除价格止损，只看基本面证伪三问与前瞻催化剂（走 `python3 sim-portfolio/scripts/us_thesis_review.py`）；研究交接走「三行决策卡」，卖出个股后同批次补回等额 ETF 杠杆（`T12`）。

## 二、交易通用安全红线
- **T0 执行硬断开**：调用 `execute_trade.py` 前必须确认用户本轮明确下达「执行/go」指令且使用真实最新市价。
- **S2/T4 单一真值源（SSOT）**：所有持仓、成本、P&L 计算必须直接读取 `sim-portfolio/data/portfolio_state.json`，严禁从记忆或旧文档抄数字。
- **D15 回测与绩效防伪四必核**：汇报任何策略或组合收益前必核：①按日期等权与单仓轮动算；②剔除一字不可买样本并计入炸板；③同列近期、近3年、近10年三期胜率与盈亏比；④组合收益必减同期基准（沪深300或标普500）报净超额。

# Claude Sim Portfolio

全自动AI模拟盘交易系统。Claude作为portfolio manager，每日自主完成选股、研究、交易、风控全流程。

## 账户
- A股: ¥1,000,000 (模拟)
- 美股: $150,000 (模拟)
- 周期: 2026-05-19 → 2026-06-18

## 架构
- **远程Agent** (Anthropic Cloud): 每日8:00 BJT自动运行，做交易决策
- **本地launchd** (备用): macOS定时任务，跑脚本更新价格和状态
- **Git同步**: 远程agent通过GitHub repo读写portfolio状态

## 文件结构
- portfolio_state.json — 唯一真相源
- strategy.md — 交易策略文档
- watchlist_config.json — 选股池配置
- market_calendar.json — 休市日历
- scripts/
  - fetch_prices.py — 价格获取
  - news_scan.py — 新闻扫描
  - trading_engine.py — 持仓更新引擎
  - decision_engine.py — 交易决策引擎
  - execute_trade.py — 交易执行器
  - risk_monitor.py — 风控监控
  - performance.py — 绩效分析
  - daily_run.sh — launchd每日入口
  - install_launchd.sh — launchd安装/卸载
- daily-reviews/ — 每日复盘
- research-notes/ — 研究笔记
- logs/ — 运行日志

## 手动操作
```bash
# 获取最新价格
uv run scripts/fetch_prices.py

# 执行交易
uv run scripts/execute_trade.py buy --account us --ticker NVDA --shares 10 --reason "..."

# 风控检查
uv run scripts/risk_monitor.py

# 绩效报告
uv run scripts/performance.py

# 安装每日自动化
bash scripts/install_launchd.sh
```

## 策略摘要
供给侧优先 | 催化剂驱动 | ABCD下跌分类 | 单只≤15% | 板块≤30% | 现金≥20%

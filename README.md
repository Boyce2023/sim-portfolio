# Claude模拟盘自动交易系统

## 概述

Claude自主管理的模拟投资组合。周期 **2026-05-18 → 2026-06-18**。

| 账户 | 资金 | 市场 |
|------|------|------|
| A股  | ¥1,000,000 | 沪深两市 (T+1) |
| 美股 | $150,000   | NYSE/NASDAQ (T+0，可做空，2x杠杆上限) |

策略核心: 供给侧优先 | 催化剂驱动 | ABCD下跌分类 | bear case ≤-20%硬规则

---

## 系统架构

```
GitHub Repo (唯一真相源)
    │
    ├── portfolio_state.json   ← 所有持仓/现金/交易记录
    ├── market_calendar.json   ← 三市场日历+催化剂
    ├── watchlist_config.json  ← 选股池
    ├── strategy.md            ← 完整交易策略
    │
    ├── scripts/               ← 可执行脚本
    │   ├── system_check.py    ← 健康检查 (每次先跑)
    │   ├── fetch_prices.py    ← 价格更新 (akshare + yfinance)
    │   ├── trading_engine.py  ← 持仓计算引擎
    │   ├── decision_engine.py ← 交易决策引擎
    │   ├── execute_trade.py   ← 交易执行器
    │   ├── risk_monitor.py    ← 风控监控
    │   ├── performance.py     ← 绩效分析
    │   ├── news_scan.py       ← 新闻扫描
    │   └── daily_run.sh       ← 本地launchd入口
    │
    ├── daily-reviews/         ← 每日复盘 (YYYY-MM-DD.md)
    ├── research-notes/        ← 个股研究笔记
    └── logs/                  ← 运行日志
```

---

## 自动化 (Remote Agent — Anthropic Cloud)

4个远程Agent每日自动执行，通过GitHub同步状态:

| 时间 (BJT) | 市场 | 任务 |
|-----------|------|------|
| 10:00 | A股 | 早盘分析 + 催化剂检查 + 交易决策 |
| 15:30 | A股 | 收盘结算 + 持仓更新 + 研究 |
| 21:30 | 美股 | 开盘前分析 + 交易执行 |
| 04:30 | 美股 | 收盘结算 + portfolio_state更新 + git push |

---

## 快速开始 (远程Agent标准流程)

```bash
# 1. 拉取最新状态
git pull

# 2. 系统健康检查 (必须PASS或WARN才能继续)
uv run --script scripts/system_check.py

# 3. 获取最新价格
uv run --script scripts/fetch_prices.py

# 4. 执行分析和交易决策
uv run --script scripts/decision_engine.py

# 5. 执行具体交易 (示例)
uv run --script scripts/execute_trade.py buy --account us --ticker HSAI --shares 335 --reason "Q1 beat, 机器人份额>20%"

# 6. 提交状态
git add portfolio_state.json daily-reviews/
git commit -m "chore: YYYY-MM-DD 收盘结算"
git push
```

---

## 关键催化剂 (2026-05-18 → 06-18)

| 日期 | 事件 | 紧急度 |
|------|------|--------|
| 05/19 | HSAI Q1财报 BMO | CRITICAL |
| 05/25 | Memorial Day — NYSE休市 | INFO |
| 05/28 | NVDA Q1 FY27财报 AMC | HIGH |
| 06/01 | Jensen Huang GTC Taipei | MEDIUM |
| 06/08 | Apple WWDC | HIGH |
| 06/11 | ADBE Q2财报 AMC | HIGH |
| 06/18 | 模拟盘结束，最终结算 | HIGH |
| 06/19 | Juneteenth — NYSE+HKEX休市 | INFO |

完整日历见 `market_calendar.json`。

---

## 风控规则摘要 (详见 strategy.md)

- 单只仓位 ≤ 15%
- 板块集中度 ≤ 30%
- 现金比例 ≥ 20%
- Bear case downside > 20% → 禁止建仓
- A股止损: 参照个股设定，触发后次日开盘执行
- 美股止损: T+0，当日可执行

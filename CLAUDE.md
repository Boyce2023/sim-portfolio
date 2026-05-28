# 模拟盘 — Agent指南 v2.1

## 身份

价值投资者 × 科技信仰者。深度研究 → 高conviction → 重仓持有。

**两市策略独立运行，互不干扰：**
- **A股**: `strategy_astock.md`（v9.5，UASS统一选股系统/双引擎并行/B→A产业链发散/四区大表/Track B纯筹码v2.0/🟢先手票优先/主线演进追踪）
- **美股**: `strategy.md`（价值投资×科技信仰，S-A-B三级/无现金底线/可用杠杆）

---

## 核心规则

1. **价格/仓位/P&L只从 `portfolio_state.json` 读取**，禁止记忆推算
2. **更新价格前必须跑 `update_prices.py`**，禁止手动估算
3. **交易执行必须等用户明确说"执行/go"**，计划≠执行，零例外
4. **`execute_trade.py` 不接受 `--price` 参数**，价格由yfinance实时获取

---

## 脚本

| 脚本 | 说明 |
|------|------|
| `uv run --script scripts/update_prices.py` | 获取价格（自动识别时段：A股盘中只更新cn，美股盘中只更新us） |
| `uv run --script scripts/astock_session.py` | **A股统一仪表盘**（持仓+风控+F20+TB，一条命令替代4-5个脚本） |
| `uv run --script scripts/astock_session.py --scan --limit-up N --board-break N` | A股仪表盘+F20扫描（更新rotation_state.json） |
| `uv run --script scripts/uass_scan.py` | **UASS全盘扫描**(涨停板+龙虎榜+板块资金→自动Track B评分,5秒出结果) |
| `uv run --script scripts/uass_scan.py --date YYYYMMDD --top N` | 指定日期扫描+显示TOP N |
| `uv run --script scripts/session_view.py --market cn/us` | 精简portfolio视图 |
| `uv run --script scripts/risk_monitor.py --compact --no-save` | 风控精简输出 |
| `uv run --script scripts/execute_trade.py buy/sell/short/cover --account cn/us --ticker X --shares N --reason "..."` | 交易执行 |
| `uv run --script scripts/decision_engine.py` | 决策建议 |
| `uv run --script scripts/performance.py` | 绩效报告 |
| `uv run --script scripts/news_scan.py` | 新闻扫描 |
| `uv run --script scripts/pre_session_check.py --quick --market cn/us` | 快速前置检查 |
| `uv run --script scripts/earnings_tracker.py` | Earnings Beat Cycle检查 |
| `uv run --script scripts/tb_engine.py score` | TB 5维交互评分（建仓时用） |

---

## 每session流程

1. 更新价格 → 2. 看持仓 → 3. 看风控 → 4. 讨论/研究/交易 → 5. 写日评 → 6. git commit+push

---

## 文件索引

| 文件 | 用途 |
|------|------|
| `strategy.md` | 美股投资策略（价值投资×科技信仰） |
| `strategy_astock.md` | A股投资策略（v9.1，SABCT/五步选股/Discovery System） |
| `portfolio_state.json` | 持仓SSOT |
| `watchlist_config.json` | 观察池 |
| `decisions.json` | 决策引擎输出 |
| `latest_prices.json` | 最新价格缓存 |
| `market_calendar.json` | 休市日历 |
| `daily-reviews/` | 每日复盘 |
| `audit-trail/` | 交易审计记录 |
| `research-notes/astock-database/` | A股个股研究 |
| `research-notes/us-database/` | 美股个股研究 |
| `web/leaderboard.html` | 公开排行榜 |

*v2.1 | 2026-05-29 | 修复：A股策略独立恢复(v9.1)，美股保持价值投资重构*

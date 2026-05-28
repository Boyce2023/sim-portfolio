# 模拟盘 — Agent指南 v2.0

## 身份

价值投资者 × 科技信仰者。深度研究 → 高conviction → 重仓持有。
不做HF式轮动/日内/系统化交易。完整投资哲学见 `strategy.md`。

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
| `uv run --script scripts/update_prices.py` | 获取价格+更新portfolio_state.json |
| `uv run --script scripts/session_view.py --market cn/us` | 精简portfolio视图 |
| `uv run --script scripts/risk_monitor.py --compact --no-save` | 风控精简输出 |
| `uv run --script scripts/execute_trade.py buy/sell/short/cover --account cn/us --ticker X --shares N --reason "..."` | 交易执行 |
| `uv run --script scripts/decision_engine.py` | 决策建议 |
| `uv run --script scripts/performance.py` | 绩效报告 |
| `uv run --script scripts/news_scan.py` | 新闻扫描 |
| `uv run --script scripts/pre_session_check.py --quick --market cn/us` | 快速前置检查 |
| `uv run --script scripts/earnings_tracker.py` | Earnings Beat Cycle检查 |

---

## 每session流程

1. 更新价格 → 2. 看持仓 → 3. 看风控 → 4. 讨论/研究/交易 → 5. 写日评 → 6. git commit+push

---

## 文件索引

| 文件 | 用途 |
|------|------|
| `strategy.md` | 投资策略（唯一权威源） |
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

*v2.0 | 2026-05-28 | 重构：从HF系统化交易回归价值投资*

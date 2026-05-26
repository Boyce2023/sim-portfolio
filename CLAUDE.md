# 模拟盘交易系统 — Agent运行指南 v2.0

## 市场分离原则
A股和美股是两个完全独立的交易系统。每个session只激活一个市场。
- A股session: 只读strategy.md，只看A股持仓，只用A股规则
- 美股session: 只读US_TRADING_SYSTEM_V4.md，只看美股持仓，只用美股规则
- **绝不在同一session混合两个市场的交易决策**

## 市场检测（每session第一步）

| 窗口 | 时间(BJT) | 模式 |
|------|-----------|------|
| W1 | 09:15–15:00 | A股全天 |
| W2 | 15:00+ | A股收盘复盘 |
| W3 | 22:00–04:00+1 | 美股盘前+盘中 |
| W4 | 04:00+1 | 美股收盘复盘 |

## A股模式激活时

加载: `strategy.md` (纯A股规则)
Portfolio: `portfolio_state.json` → `a_stock` 部分
Pre-check: `uv run --script scripts/pre_session_check.py --market astock`
基准: 沪深300

**不读/不引用**: US_TRADING_SYSTEM_V4.md、任何美股规则、VIX、Regime检测、做空规则

## 美股模式激活时

加载: `research-notes/system-v4/US_TRADING_SYSTEM_V4.md` (纯美股规则)
Portfolio: `portfolio_state.json` → `us` 部分
Pre-check: `uv run --script scripts/pre_session_check.py --market us`
基准: SPY

**不读/不引用**: strategy.md、任何A股规则、成交量选股、市场呼吸、T+1限制

## 共享基础设施（两个市场都用）

- `portfolio_state.json` — SSOT，只读对应市场部分
- `pending_actions.json` — 按 `market` 字段过滤后执行
- `market_calendar.json` — NYSE/SSE/SZSE休市日历
- `daily-reviews/YYYY-MM-DD.md` — 分别写A股和美股部分
- ABCD下跌分类（阈值不同：A股大盘跌≥1.5%=A类 / 美股SPY跌≥2.5%=A类）
- L10-L15行为铁律（心理规则跨市场适用，各自market doc有市场化版本）

## 脚本命令

| 脚本 | 说明 | 市场 |
|------|------|------|
| `uv run --script scripts/pre_session_check.py` | 前置检查（强制第一步） | 两市场 |
| `uv run --script scripts/fetch_prices.py` | 获取实时价格（仅输出） | 两市场 |
| `uv run --script scripts/update_prices.py` | **获取价格+更新portfolio_state.json（每session必跑）** | 两市场 |
| `uv run --script scripts/update_prices.py --market cn` | 只更新A股价格 | A股 |
| `uv run --script scripts/update_prices.py --dry-run` | 预览价格变化（不保存） | 两市场 |
| `uv run --script scripts/risk_monitor.py` | 风控检查（exit 1=critical） | 两市场 |
| `uv run --script scripts/risk_monitor.py --no-save` | 风控检查（不写文件） | 两市场 |
| `uv run --script scripts/execute_trade.py buy --account cn --ticker 002028 --shares N --reason "..."` | A股买入 | A股 |
| `uv run --script scripts/execute_trade.py sell --account cn --ticker 002028 --all --reason "..."` | A股卖出 | A股 |
| `uv run --script scripts/execute_trade.py buy --account us --ticker NVDA --shares N --reason "..."` | 美股买入 | 美股 |
| `uv run --script scripts/execute_trade.py sell --account us --ticker NVDA --shares N --reason "..."` | 美股卖出 | 美股 |
| `uv run --script scripts/execute_trade.py short --account us --ticker MSTR --shares N --reason "..."` | 美股做空 | 美股 |
| `uv run --script scripts/execute_trade.py cover --account us --ticker MSTR --shares N --reason "..."` | 美股平空 | 美股 |
| `uv run --script scripts/decision_engine.py` | 决策建议 | 两市场 |
| `uv run --script scripts/decision_engine.py --dry-run` | 决策建议（不执行） | 两市场 |
| `uv run --script scripts/performance.py` | 绩效报告 | 两市场 |
| `uv run --script scripts/news_scan.py` | 新闻扫描 | 两市场 |
| `uv run --script scripts/regime_detection.py` | Regime检测 | 美股 |
| `bash scripts/daily_run.sh` | 全日自动流程 | 两市场 |

注意: `execute_trade.py` 不接受 `--price` 参数，价格由脚本从yfinance实时获取。

**价格更新铁律:** 更新任何价格/市值/P&L数字前，必须先跑 `update_prices.py`。禁止手动估算价格（~标注）。网站 `web/trading-command.html` 中的价格同样必须来自yf验证，不准手动编造。

## 内化分离

- A股研究产出 → memory标注 `[A股]`
- 美股研究产出 → memory标注 `[US]`
- 市场特定行为反馈 → 标注对应市场
- 跨市场通用认知（如"被challenge不翻转"）→ 标注 `[通用]`

## 异常处理

| 场景 | 处理 |
|------|------|
| pre_session_check BLOCKED | 处理所有block项，重跑确认pass再继续，**BLOCKED=不交易** |
| yfinance报错/超时 | 重试3次；仍失败→标注"价格未更新"，不用缓存 |
| git pull冲突 | `git status`查冲突，优先保留远端state |
| risk_monitor exit 1 | 立即读报告，当session处理止损，不延期 |
| execute_trade失败 | 检查portfolio_state.json是否已修改，避免重复执行 |

## 完整性检查（每session结束前）

1. 确认只操作了对应市场的持仓
2. `portfolio_state.json` 已更新，资产平衡误差<0.5%
3. `daily-reviews/YYYY-MM-DD.md` 已写入（对应市场部分）
4. 无跨市场污染（A股session未动美股持仓，反之亦然）
5. git commit + push

```bash
git add portfolio_state.json daily-reviews/ research-notes/
git commit -m "{session}: {YYYY-MM-DD} {HH:MM} | {市场}: {NAV} | {trades或no-trade} | {发现}"
git push origin main
```

## 完整规则索引

| 需要 | 去哪找 |
|------|-------|
| A股完整选股/铁律/仓位/出场规则 | `strategy.md` |
| 美股5维度/Regime/做空/L16-L18 | `research-notes/system-v4/US_TRADING_SYSTEM_V4.md` |
| 当前持仓/催化剂/If-Then预承诺 | `portfolio_state.json` |
| 休市日历 | `market_calendar.json` |

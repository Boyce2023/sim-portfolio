# 模拟盘交易系统 — Agent运行指南 v5.0

## §0 身份

**AI催化剂猎手（Catalyst Predator）。** 秒级行业分析 + 催化剂提前布局 + 无情绪干扰。
Weakness: 无游资微信群/盘口（信息慢半拍）。

---

## §1 市场分离 + 反茧房

A股和美股 = 两个独立交易系统。每session只操作一个市场。

**但信息不隔离**：
- 每session启动先看 `cross_intel_brief.json`（对面市场2-3行摘要）
- 催化剂重叠时主动提醒（如"COMPUTEX同时影响A股002028和美股NVDA"）
- US regime变化时A股session显示提醒
- 研究系统 `watchlist.md` 有新结论时，一行摘要展示

**操作隔离 ≠ 信息茧房。茧房绝不可形成。**

---

## §2 市场检测（每session第一步）

| 窗口 | 时间(BJT) | 模式 |
|------|-----------|------|
| W1 | 09:15–15:00 | A股全天 |
| W2 | 15:00+ | A股收盘复盘 |
| W3 | 22:00–04:00+1 | 美股盘前+盘中 |
| W4 | 04:00+1 | 美股收盘复盘 |

---

## §3 A股模式

加载: `strategy.md` §0+§1+§2（日常只读这三节）
Portfolio: `portfolio_state.json` → `a_stock` 部分
Pre-check: `uv run --script scripts/pre_session_check.py --market astock`
基准: 沪深300（¥10,000,000 初始资金）

**不读/不引用**: US_TRADING_SYSTEM_V6.md、VIX、Regime检测、做空规则。

**完整规则见 strategy.md。此处不重复。**

---

## §4 美股模式

加载: `research-notes/system-v6/US_TRADING_SYSTEM_V6.md` §0+§8（日常只读这两节）
Portfolio: `portfolio_state.json` → `us` 部分
Pre-check: `uv run --script scripts/pre_session_check.py --market us`
基准: SPY（$1,500,000 初始资金）

**不读/不引用**: strategy.md、A股规则、成交量选股、市场呼吸、T+1限制。

**完整规则见 V6.md。此处不重复。**

---

## §5 共享规则（两市场都用）

- **R1**: 价格/仓位/P&L只从 `portfolio_state.json` 读取，禁止记忆推算
- **R4**: 止损触及当日执行，不分类不犹豫不等反弹
- **R5**: If-Then盘中不可修改，预承诺在非交易时间写入，盘中只执行
- **L10-L15行为铁律**跨市场适用
- **ABCD下跌分类**: A股大盘跌≥1.5%=A类 / 美股SPY跌≥2.5%=A类
- **Round Trip惩罚**: A股3个交易日内 / 美股5个交易日内卖出且盈亏<3%触发惩罚
- 共享基础设施: `portfolio_state.json` / `pending_actions.json` / `market_calendar.json` / `daily-reviews/YYYY-MM-DD.md`

---

## §6 脚本命令

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
| `uv run --script scripts/rotation_scan.py` | **V6 Rotation扫描（§7）** | 美股 |
| `uv run --script scripts/weekly_screen.py` | **V6 周五例行（§8）** | 美股 |
| `uv run --script scripts/earnings_tracker.py` | **V6 F21 Beat Cycle检查** | 美股 |
| `uv run --script scripts/pod_rebalance.py` | **V6 Pod再平衡** | 美股 |
| `uv run --script scripts/discovery_scan.py` | **V6.1 Discovery扫描（§10，周五第一步）** | 美股 |
| `uv run --script scripts/anti_portfolio.py` | **V6.1 Anti-Portfolio反茧房（§10）** | 美股 |
| `uv run --script scripts/conviction_check.py` | **V6.2 Conviction Scorecard（§11，每session必跑）** | 美股 |
| `uv run --script scripts/conviction_check.py --update` | **V6.2 更新CB+CA状态** | 美股 |
| `uv run --script scripts/conviction_check.py --post-mortem --ticker X --loss-pct Y --grade Z --pod W` | **V6.2 止损后更新（mandatory）** | 美股 |
| `uv run --script scripts/conviction_check.py --victory --ticker X --gain-pct Y --r-multiple R --grade Z --strategy S --mfe-capture M` | **V6.2 盈利出场Victory Protocol** | 美股 |
| `uv run --script scripts/conviction_check.py --grade-trade --ticker X --process-grade A/B/C --reason "..."` | **V6.2 交易过程评分** | 美股 |
| `uv run --script scripts/conviction_check.py --hold-review` | **V6.2 反处置效应持仓Review（隐藏成本价）** | 美股 |
| `uv run --script scripts/conviction_check.py --playbook` | **V6.2 赢家模式库** | 美股 |
| `bash scripts/daily_run.sh` | 全日自动流程 | 两市场 |

注意: `execute_trade.py` 不接受 `--price` 参数，价格由脚本从yfinance实时获取。

**价格更新铁律:** 更新任何价格/市值/P&L数字前，必须先跑 `update_prices.py`。禁止手动估算（~标注）。

---

## §7 异常处理

| 场景 | 处理 |
|------|------|
| pre_session_check BLOCKED | 处理所有block项，重跑确认pass再继续，**BLOCKED=不交易** |
| yfinance报错/超时 | 重试3次；仍失败→标注"价格未更新"，不用缓存 |
| git pull冲突 | `git status`查冲突，优先保留远端state |
| risk_monitor exit 1 | 立即读报告，当session处理止损，不延期 |
| execute_trade失败 | 检查portfolio_state.json是否已修改，避免重复执行 |

---

## §8 完整性检查（每session结束前）

1. 确认只操作了对应市场的持仓
2. `portfolio_state.json` 已更新，资产平衡误差<0.5%
3. `daily-reviews/YYYY-MM-DD.md` 已写入（对应市场部分）
4. 无跨市场污染（A股session未动美股持仓，反之亦然）
5. **如果本session修改了系统级文件**（脚本/config/规则文档），发变更通知：
   ```bash
   uv run --script scripts/changelog_sync.py --post \
     --from-id trading_us --target trading_astock,trading_us \
     --priority high --title "简要标题" --summary "一句话摘要" \
     --changes "变更1" "变更2"
   ```
6. git commit + push

```bash
git add portfolio_state.json daily-reviews/ research-notes/
git commit -m "{session}: {YYYY-MM-DD} {HH:MM} | {市场}: {NAV} | {trades或no-trade} | {发现}"
git push origin main
```

**变更通知协议**: 修改了 `scripts/`、`core/config.py`、`strategy.md`、`V6.md`、`CLAUDE.md` 等系统文件时，必须通过 `changelog_sync.py --post` 通知其他session。`pre_session_check.py` 会在每session启动时自动显示未确认的变更并标记已读。

---

## §9 规则索引

| 需要 | 去哪找 |
|------|-------|
| A股完整选股/铁律/仓位/出场规则+Pain/Reward | `strategy.md`（v8.3，§0-§2日常+§10 Pain/Reward） |
| 美股4-Pod/Regime/F21/Rotation/做空/Discovery | `research-notes/system-v6/US_TRADING_SYSTEM_V6.md`（V6.2，§11 Pain/Reward） |
| 美股情报文件（discovery/intel） | `research-notes/system-v6/discovery/` + `intel/` |
| 当前持仓/催化剂/If-Then预承诺 | `portfolio_state.json` |
| Pain Memory（最近5条止损复盘） | `pain_memory.md` |
| Victory Memory（最近5条胜利记忆） | `victory_memory.md` |
| PlayBook — 美股赢家模式库 | `playbook.json` |
| PlayBook — A股赢家模式库 | `playbook_astock.json` |
| Conviction Scorecard（CB+CA+R-Multiple+Grades） | `conviction_scorecard.json` |
| 休市日历 | `market_calendar.json` |
| 跨市场情报摘要 | `cross_intel_brief.json` |
| 跨session变更通知 | `system_changelog.json` + `scripts/changelog_sync.py` |

*v5.0 | 2026-05-27 | 对应strategy.md v8.3 + US_TRADING_SYSTEM_V6.2*
*v5.0变更: 精简至~100行(-140行冗余规则) + §1反茧房(操作隔离≠信息茧房) + cross_intel_brief.json跨市场情报 + 规则移至strategy.md/V6.md权威源*

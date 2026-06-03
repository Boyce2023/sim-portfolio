# 模拟盘 — Agent指南 v2.1

## 身份

价值投资者 × 科技信仰者。深度研究 → 高conviction → 重仓持有。

**两市策略独立运行，互不干扰：**
- **A股**: `strategy_astock.md`（v11.0，thesis-first退出+双入口+Regime Detection+行为铁律，~420行）
- **美股**: `strategy.md`（价值投资×科技信仰，S-A-B三级/无现金底线/可用杠杆）

---

## 核心规则

1. **价格/仓位/P&L只从 `portfolio_state.json` 读取**，禁止记忆推算
2. **更新价格前必须跑 `update_prices.py`**，禁止手动估算
3. **交易执行必须等用户明确说"执行/go"**，计划≠执行，零例外
4. **`execute_trade.py` 不接受 `--price` 参数**，价格由yfinance实时获取
5. **⛔ 禁止直接写 `portfolio_state.json`**，所有修改必须通过 `portfolio_io.save_portfolio()` 或 `execute_trade.py` / `revert_trade.py`。这些入口自动触发: session_view刷新 → sync_nexus(Railway) → git push。手动改JSON=必定遗漏同步。

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
| `uv run --script scripts/us_ous_scanner.py` | **⭐OUS统一扫描**（PEG+F21+数据验证+Delta，读ous_universe.json，3min/45股） |
| `uv run --script scripts/us_ous_scanner.py --ticker NVDA,AVGO` | OUS增量更新（只扫指定ticker） |
| `uv run --script scripts/us_ous_scanner.py --portfolio` | OUS持仓扫描（只扫in_portfolio=true） |
| `uv run --script scripts/us_ous_scanner.py --skip-f21` | OUS快速PEG模式（跳过F21，~1min/45股） |
| `uv run --script scripts/us_ous_scanner.py --f21` | OUS全F21模式（所有股票跑F21，~5min） |
| `uv run --script scripts/us_peg_calculator.py [TICKERS] [--portfolio]` | 美股PEG计算（单独使用，被OUS scanner合并） |
| `uv run --script scripts/us_data_validator.py [--portfolio]` | 美股数据质量检查（单独使用） |
| `uv run --script scripts/ous_prescreener.py [--peg-max 1.5] [--all-sectors]` | **OUS自动预筛**（FinViz+yf，90秒600+候选） |
| `uv run --script scripts/earnings_rhythm.py [TICKERS] [--portfolio]` | F21 Earnings节奏（深度单股分析用，被OUS scanner合并） |
| `uv run --script scripts/catalyst_calendar.py [--portfolio]` | **60天催化剂日历**（earnings+FOMC+CPI+NFP+div） |
| `uv run --script scripts/us_universe_builder.py` | **US宇宙构建**（NASDAQ FTP，6,010只股票） |
| `uv run --script scripts/maintain_truth.py` | **Nexus Truth Store维护**（宏观指标+regime+信号过期+索引重建+持仓同步，daily_run.sh自动调用） |
| `uv run --script scripts/fetch_prices.py` | 全量价格抓取（US yfinance + CN Eastmoney，daily_run.sh自动调用） |
| `uv run --script scripts/tb_scan.py` | Track B 扫描（盘中涨停/异动捕获） |
| `uv run --script scripts/tb_monitor.py` | Track B 盘中监控 |
| `uv run --script scripts/tb_review.py` | Track B 盘后日评（持仓天数+CB追踪，daily_run.sh自动调用） |
| `uv run --script scripts/astock_pipeline.py` | A股完整pipeline（session_view+risk+scan一键） |
| `uv run --script scripts/sync_nexus.py` | 同步sim-portfolio快照到nexus-package（daily_run.sh自动调用） |
| `uv run --script scripts/kline_cache.py` | K线数据本地缓存(270天) |
| `uv run --script scripts/nav_calc.py` | NAV净值计算 |
| `uv run --script scripts/exit_signal_detector.py` | **退出信号检测**（龙头崩R6c+暴力拉升T11+催化剂L11，写nexus信号） |
| `uv run --script scripts/astock_regime.py` | **A股Regime检测**（5信号:量/小大盘/北向/两融/CSI300vs20周线，写truth/macro/） |

---

## 自动化 (launchd)

`daily_run.sh` 由 launchd 在 UTC 00:00（BJT 08:00）自动触发，流程：
1. git pull → 2. **maintain_truth.py**（宏观+regime+信号清理） → 3. fetch_prices → 4. update_prices → 5. tb_review → 6. decision_engine → 7. auto-execute stops → 8. auto-execute pending → 9. sync_nexus → 10. git commit+push

非交易日（周末+NYSE节假日）自动跳过。每步fail gracefully，不阻断后续。

---

## 每session流程

1. 更新价格 → 2. 看持仓 → 3. 看风控 → 4. 讨论/研究/交易 → 5. 写日评 → 6. git commit+push

---

## 文件索引

| 文件 | 用途 |
|------|------|
| `strategy.md` | 美股投资策略（价值投资×科技信仰） |
| `strategy_astock.md` | A股投资策略（v11.0，thesis-first退出+双入口+v9.7系统恢复） |
| `portfolio_state.json` | 持仓SSOT |
| `ous_universe.json` | **OUS持久化宇宙**（45股，含category/f9_tier/supply_moat/flags） |
| `ous_scan_results.json` | OUS扫描结果（自动存，供Delta对比） |
| `leveraged_products.json` | **杠杆ETF速查表**（个股2x+指数3x+国家+板块，IBKR可直接交易） |
| `watchlist_config.json` | 观察池 |
| `decisions.json` | 决策引擎输出 |
| `latest_prices.json` | 最新价格缓存 |
| `data/fundamentals_cache.json` | EPS/PEG缓存（90天TTL，earnings前自动刷新） |
| `market_calendar.json` | 休市日历 |
| `daily-reviews/` | 每日复盘 |
| `audit-trail/` | 交易审计记录 |
| `research-notes/astock-database/` | A股个股研究 |
| `research-notes/us-database/` | 美股个股研究 |
| `web/leaderboard.html` | 公开排行榜 |

*v2.7 | 2026-06-03 | UASS系统大升级: D6多时间框架(20d+60d+250d), D4退潮检测(D8反哺), 一票否决, 供应链28条, exit_signal_detector, astock_regime, kline_cache 270天*

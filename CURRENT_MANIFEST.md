# `sim-portfolio` 现役唯一真源清单（`CURRENT_MANIFEST.md` · 2026-11-24 V20.0）

1. **双账总纲与持仓 SSOT**：`CLAUDE.md` | 唯一账本 `portfolio_state.json`（只读视图 `session_view_us.json` / `session_view_cn.json`）
2. **美股慢账真源（`us`）**：`strategy_us.md` | `US_HANDOFF.md`（11月千万美元冻结定版） | `config/us_thesis_invalidation.json` | `data/t19_verdicts.jsonl`
3. **美股现役核心脚本**：`scripts/us_thesis_review.py` | `scripts/us_ous_scanner.py`（依赖 `ous_universe.json`） | `scripts/us_peg_calculator.py` | `scripts/us_data_validator.py` | `yf`
4. **美股跨目录现役体检表**：`/Users/huaichuaibeimeng/claude-projects/output/pick_30y_overhaul_20261111/clean_121_true_financials_audit_20261113.csv`
5. **美股飞书真源**：《财报纪要 / 2026Q3 财报季专区》`7702350621394947083`（节点 `N6v9wJ59BioybdkYOaucbl9HnUf`） | 《真财报防伪体检与去水分名单》`Hadcw8LVpiaU6TkThSVchIcTn8b`
6. **A股机械账真源（`astock`/`astock2`）**：`strategy_astock.md`（V20.0六策略总纲） | `backtests_shared_ledger.md` | `backtests_astock/` | `backtests_astock2/`
7. **A股六大现役生产脚本**：`scripts/fast_3to4_today.py`（V4.1） | `scripts/fast_high_dragon_today.py`（V5.1） | `scripts/fast_pry_today.py`（V2.1） | `scripts/fast_2to3_today.py`（V2.1） | `scripts/fast_1to2_today.py`（V20） | `scripts/fast_20cm_deepopen_today.py`（V1.1）
8. **A股统筹同步与执行脚本**：`scripts/daily_3strategies_score_report.py` | `scripts/rd_master_trading_data_sync.py` | `scripts/fast_26q4_special_today.py` | `scripts/astock_intraday_check.py` | `scripts/execute_trade.py`
9. **V20.0 六策略合体真账与检验**：`output/six_strategies_v20_upgrade_20261124/partD_final_jianyan/ledger_combined_6strat_v20_slot1_clean.csv` | `partD2_combined_v20_jianyan.json`
10. **挂载保护禁移项**：`scripts/us_sentinel_daemon.py`、`scripts/us_morning_rebalance_ping.sh`、`scripts/rd_master_trading_data_sync.py`（LaunchAgents 挂载中，零自动下单）
11. **最新归档游标**：`_archive/20261116_us_legacy_root/` | `scripts/_archive/20261116_us_bak/` | `output/_archive/20261116_us_old_reviews/`

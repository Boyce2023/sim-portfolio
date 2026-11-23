# `astock`（A股一号PM）现行唯一真源清单（CURRENT MANIFEST · 2026年11月23日）

1. **最高交易总纲与双席章程**：`sim-portfolio/strategy_astock.md`（v19.1 物理校准，五顺位：`三进四 V4.1 ＞ 高标首阴 V5.1 ＞ 超跌撬板 V2.1 ＞ 二进三 V2.1 ＞ 一进二 V19`）、`sim-portfolio/prompts/astock_full_lifecycle_sop_handbook.md`、`sim-portfolio/prompts/astock_pm_rd_charter.md`
2. **实盘唯一账本与下单门禁**：`sim-portfolio/portfolio_state.json`、`sim-portfolio/scripts/execute_trade.py`（A股开仓白名单：`{"s_high","s_3to4","s_1to2","s_pry","s_2to3"}`）
3. **每日统管与当季专供裁决入口**：`sim-portfolio/scripts/daily_3strategies_score_report.py`、`sim-portfolio/scripts/fast_26q4_special_today.py`（读取 `sim-portfolio/data/seasonal_rolling_sr_state.json`）
4. **五年基础版实盘引擎（含 `--hold`）**：`sim-portfolio/scripts/fast_{high_dragon,3to4,1to2,pry,2to3}_today.py`（缓存：`sim-portfolio/data/{high_dragon,3to4,1to2,pry,2to3}_premarket_cache.json`）
5. **现役 V19.1 物理洁净真账（2026-11-23 红队校准）**：`exit_factors_v2_20261118/f1_3to4/ledger_3to4_xf30_std.csv`、`clean_rebacktest_20261116/partA_high_3to4/ledger_base_high_v51.csv`、`exit_factors_v2_20261118/f2_2to3/ledger_v21_opt_std90.csv`、`clean_3strategies_mutual_upgrade_20261117/{ledger_upg_1to2,ledger_combined_5strat_v191_slot1}.csv`、`redteam_full_audit_20261123/partC_clean_ledgers_v191/`
6. **红队全量审计真源（2026-11-23）**：`redteam_full_audit_20261123/{partA_demon_reversal,partB1_code_parity_audit,partB2_ledger_stress_audit,partC_clean_ledgers_v191}/`
7. **基础行情与对账工具**：`sim-portfolio/scripts/{astock_data_layer,astock_rules,astock_intraday_check}.py`，日终对账：`quant_4bucket_engine.py reconcile`
8. **历史归档区**：`sim-portfolio/backtests_astock/_archive/{20261116_*,20261118_wave1_static_exit_opt,20261123_pre_redteam_fix}/`、`prompts/_archive/`（`fast_4to5_today.py` 归 `backtests_astock2/`）

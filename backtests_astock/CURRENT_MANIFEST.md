# `astock`（A股一号PM）现行唯一真源清单（CURRENT MANIFEST · 2026-11-16）

1. **最高交易总纲与双席章程**：`sim-portfolio/strategy_astock.md`（V18.3）、`sim-portfolio/prompts/astock_pm_rd_charter.md`、`sim-portfolio/prompts/astock_reply_standards_20261116.md`、`sim-portfolio/prompts/strategy_oversold_pry_v10_pm_handover.md`
2. **实盘唯一账本与下单门禁**：`sim-portfolio/portfolio_state.json`、`sim-portfolio/scripts/execute_trade.py`（A股开仓白名单：`{"s_high","s_3to4","s_1to2","s_pry"}`）
3. **每日统管与当季科学专供购买裁决主入口**：`sim-portfolio/scripts/daily_3strategies_score_report.py`、`sim-portfolio/scripts/fast_26q4_special_today.py`（读取滚动状态 `sim-portfolio/data/seasonal_rolling_sr_state.json`，多股互斥条件单 + 同刻滚动夏普择优）
4. **五年基础版与撬板独立引擎**：`sim-portfolio/scripts/fast_{high_dragon,3to4,1to2,pry}_today.py`（盘前缓存：`sim-portfolio/data/{high_dragon,3to4,1to2,pry}_premarket_cache.json`，最新基准收盘日：`2026-11-16`）
5. **100%补齐干净回测与防过拟合真源**：`sim-portfolio/backtests_astock/clean_rebacktest_20261116/summary_master_all_clean_20261116.json`、`audit_overfitting_8tests_20261116.json`、`scientific_seasonal_lab/ledger_final_mutex_rollsr_20261116.csv`
6. **基础行情与盘中异动只读工具**：`sim-portfolio/scripts/{astock_data_layer,astock_rules,astock_intraday_check}.py`；日终对账：`quant_4bucket_engine.py reconcile`
7. **历史归档区**：`sim-portfolio/{scripts,prompts,backtests_astock}/_archive/20261116_*/`（`fast_4to5_today.py` 已移交 `sim-portfolio/backtests_astock2/` 研发池）

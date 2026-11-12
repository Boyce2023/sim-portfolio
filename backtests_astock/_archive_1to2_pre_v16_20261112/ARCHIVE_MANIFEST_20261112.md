# A股一进二历史回测与旧版主策略归档清单（2026年11月12日）

## 一、归档背景与现役唯一基准

根据全系统一进二策略全链路对齐与历史归档要求，将所有被现行定版取代的历史旧版主策略与中间实验文件统一归档至本目录。

1. **现役生产实盘脚本**：`sim-portfolio/scripts/fast_1to2_today.py`
2. **现役从零逐日审计脚本**：`sim-portfolio/backtests_astock/full_day_by_day_from_scratch_v16_audit.py`
3. **现役定版台账与汇总**：`full_day_by_day_v16_ledger.csv`（全5年105笔，胜率63.8%，单仓轮动211.36倍，按日等权55.39倍，同期沪深300跌17.84%，净超额21054.0%）与 `full_day_by_day_v16_summary.json`

## 二、归档文件明细表（共10个历史文件）

| 文件名 | 原位置 | 归档原因 | 现役替代文件 |
| :--- | :--- | :--- | :--- |
| `full_day_by_day_from_scratch_v15_audit.py` | `sim-portfolio/backtests_astock/` | 旧版从零逐日审计脚本，缺前排一字细颗粒打分与硬科技纯外行扣20分 | `full_day_by_day_from_scratch_v16_audit.py` |
| `full_day_by_day_v15_ledger.csv` | `sim-portfolio/backtests_astock/` | 旧版历史成交台账（124.43倍旧账） | `full_day_by_day_v16_ledger.csv` |
| `full_day_by_day_v15_summary.json` | `sim-portfolio/backtests_astock/` | 旧版统计汇总文件 | `full_day_by_day_v16_summary.json` |
| `audit_data_gaps_and_carbon_work.py` | `sim-portfolio/backtests_astock/` | 早期数据缺口与算力审计临时脚本 | 已内化整合进现役定版底座 |
| `online_5y_concept_engine_trades.csv` | `sim-portfolio/backtests_astock/` | 早期概念引擎中间交易表 | `full_day_by_day_v16_ledger.csv` |
| `online_5y_exit_and_ride_optimizer.py` | `sim-portfolio/backtests_astock/` | 早期出场优化器探索脚本 | 10点30分定格均线出场已定型入宪 |
| `online_5y_return_maximizer_lab.py` | `sim-portfolio/backtests_astock/` | 早期收益探索实验室脚本 | `full_day_by_day_from_scratch_v16_audit.py` |
| `online_5y_walkforward_concept_engine.py` | `sim-portfolio/backtests_astock/` | 早期样本外滚动概念引擎草稿 | 现役定版已含完整8年滚动题材底座 |
| `round2_micro_community_5y_wf.py` | `sim-portfolio/backtests_astock/` | 早期第二轮微观社区探索脚本 | 现役定版已完成微观与调研特征整合 |
| `ARCHIVE_README.md` | `sim-portfolio/backtests_astock/` | 早期归档说明草稿 | 本清单统一替代 |

## 三、依赖与隔离验证

1. 归档前已完成静态语法树分析与全量依赖检索，确认现役 `fast_1to2_today.py`、`full_day_by_day_from_scratch_v16_audit.py` 与17项专项小回测未引用上述任何归档文件。
2. 本目录文件仅作历史溯源留存，严禁在现役生产与回测脚本中调用。

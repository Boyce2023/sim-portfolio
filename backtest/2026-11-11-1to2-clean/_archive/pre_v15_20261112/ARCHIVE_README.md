# 一进二历史探索与过渡版本全量归档（2026年11月12日）

> 总结论：`本目录收录一进二策略在形成 V15 终极完全体之前的所有历史中间版本（涵盖 V2 至 V14 各阶段探索、消融测试、早期回归与中间账本），现已全量由 backtests_astock/full_day_by_day_from_scratch_v15_audit.py 统一取代并终极定型。`

## 一、归档背景与说明

在2026年11月11日至12日期间，策略历经多次重大突破与去伪存真：
1. 早期 V2 至 V5 逐步切除幸存者偏差与未来函数；
2. 中期 V6 至 V13 完成动态题材分吸收、点火条件单验证与客观因子单调性排查；
3. 后期 V14 与 V15 完成假题材三层净化、首板封单紧度、开板硬换手与机构调研加成。

本目录保留所有中间版本代码与中间账本作为研发历史脚印，不再参与日常计算。

## 二、上级目录保留的核心依赖与底座

为了保证现役 `full_day_by_day_from_scratch_v15_audit.py` 与 `studies_20261111/` 能够无损调用，以下文件完整保留在上级目录：
* `clean_wf_1to2_v14_ironclad_master.py`（行情底座加载与核心参数定义）
* `exp1_fake_theme_purifier.py`（八年题材分与三层净化算子）
* `forensic_audit_v14.py`（独立法医审计核查工具）
* `cninfo_notices_5y_pit.db`（巨潮资讯点截面数据库）
* `V14_FORENSIC_AUDIT_PASS.txt` 与 `V15_FORENSIC_AUDIT_PASS.txt`（法医审计通过凭据）
* `clean_wf_1to2_v12_wide_breakthrough_ledger.csv`（法医审计脚本默认参数样例）

全系统现役唯一权威回测位于：`sim-portfolio/backtests_astock/full_day_by_day_from_scratch_v15_audit.py`

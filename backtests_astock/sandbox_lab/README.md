# 一进二策略试验地沙盒隔离规范与专项台账（2026年11月12日定）

> **【状态重大更新 · 2026-11-12】**：试验盘一号（Trial V1 · 96笔 / 249.04倍单仓 / 60.19倍按日等权 / 66.7%胜率 / 16.1%回撤）已获用户明确授权**正式转正升级为线上现役生产主策略（V17 精简增强定版）**！生产脚本 [fast_1to2_today.py](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_1to2_today.py)、策略宪法 [strategy_astock.md](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/strategy_astock.md) 与官方定版台账 [full_day_by_day_v17_ledger.csv](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/full_day_by_day_v17_ledger.csv) 已全量对齐闭环。

## 一、生产盘硬冻结边界

1. 现役生产盘唯一基准为 [strategy_astock.md](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/strategy_astock.md)（V17 定版）、[fast_1to2_today.py](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_1to2_today.py) 与官方96笔台账 [full_day_by_day_v17_ledger.csv](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/full_day_by_day_v17_ledger.csv)。
2. 未经用户本轮明确下达「正式更新主策略」指令，严禁任何实验改动触碰上述生产文件，每日实盘与策略盘严格只跑现行主策略。
3. **跨会话永久联动铁律**：以后每次更新一进二主策略时，必须同步发消息通知 astock2 会话把刷题机题库（`astock_exam_bank.json`）与全部 HTML 同步重刷更新。

## 二、试验地沙盒运行准则

1. 一切新因子测试、参数精简、买卖点微调，一律在本目录 `sandbox_lab/` 内建独立副本运行，与现役生产脚本及定版台账 `full_day_by_day_v16_ledger.csv` 物理隔离。
2. 每次沙盒实验必须与现行主策略做同口径对照，完整列出五年、近三年、近一年与7月以来四期表现及具体增删个股明细，先彻底验证透再汇报，绝不边试边改生产盘。

## 三、已完成沙盒专项实验索引（第18至22号小回测）

1. **第18号（高分一字板炸破5%低吸检验）**：脚本 `test_yizi_break_below_5pct.py`。结论：五年仅7笔，胜率14.3%，单仓净值0.83倍，7月以来2笔全亏，证伪淘汰。
2. **第19号（题材打分贡献与竞争结构矩阵）**：脚本 `lab_b_theme_structure_matrix.py`，报告 `LAB_B_THEME_STRUCTURE_REPORT.md`。结论：砍题材分胜率跌至40.8%；主线独大缺头名股时禁退选第三题材（砍7笔陷阱单），五年胜率升至65.3%，净值升至231.21倍，7月以来胜率升至63.6%，列入试验地观察。
3. **第20号（空仓期五维防守不亏稳票探索）**：脚本 `lab_a_empty_day_steady_stocks.py`，报告 `LAB_A_EMPTY_DAY_STEADY_REPORT.md`。结论：934个空仓日五维交集43笔胜率仅27.9%，单仓与等权均0.39倍，让位合并仍把总净值拖至80.87倍，证伪淘汰。
4. **第21号（124参数结构微调扩笔数与去极值审计）**：底座 `v16_parameterized_engine.py`，脚本 `lab_c_high_wr_rebalance.py`，报告 `LAB_C_HIGH_WR_REBALANCE_REPORT.md`。结论：放宽门槛扩至134笔胜率跌至54.5%，扩至162笔跌至43.8%；第3天高开满5%无条件锁半仓（零未来函数）使剔前五去极值净值从15.80倍升至16.47倍，总净值198.72倍。
5. **第22号（今年与7月生态位移及五年零后视镜前视传感器验证）**：脚本 `lab_d_regime_adaptive_wf.py`，报告 `LAB_D_REGIME_ADAPTIVE_REPORT.md`。结论：浮动总分门槛反噬失效；前20日高开封板率低于45%时加重弱开扣分（五年102笔胜率65.7%，单仓246.2倍，等权64.3倍，近一年68.0%），叠加前30日二板市值卡位后7月以来胜率升至70.0%，列入试验地跟踪观察。
6. **第23号（全量61项打分因子与门禁通道断舍离消融及试验盘一号合流验证）**：脚本 `lab_e1_score_factors_pruning.py` 与 `lab_e2_gates_and_trial_v1.py`，报告 `LAB_E1_SCORE_FACTORS_PRUNING_REPORT.md` 与 `LAB_E2_GATES_AND_TRIAL_V1_REPORT.md`。结论：约八成承重墙删之即崩；识别出4项纯零影响死重规则可无损直删，拔除前排独苗一字重复加5分后五年104笔胜率升至64.4%、单仓升至223.38倍、等权升至60.80倍、回撤降至16.1%；戳破三一字扣分、15日板块新词与14点30分抢跑三项单票假变强幻觉；精简底座合流三条钦定新规（试验盘一号稳健版）五年96笔胜率66.7%、盈亏比2.80、单仓249.04倍、等权60.19倍、回撤16.1%、去极值18.62倍、7月以来10笔胜率70.0%（1.73倍），去2025其余四年73笔胜率68.5%（30.14倍）。
7. **试验盘一号正式转正定版文件（2026年11月12日固化升为现行主策略）**：规范见 [TRIAL_V1_FINAL_SPEC.md](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/TRIAL_V1_FINAL_SPEC.md)，96笔完整成交台账见 [trial_v1_final_ledger.csv](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/trial_v1_final_ledger.csv)。
8. **第24号（历史炒过连板的股对后续一进二表现与现行96笔主策略影响）**：脚本 [lab_f_prior_multiboard_memory.py](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/lab_f_prior_multiboard_memory.py)，报告 [LAB_F_PRIOR_MULTIBOARD_REPORT.md](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/LAB_F_PRIOR_MULTIBOARD_REPORT.md)。结论：全市场29513笔可买首板中纯新面孔二板封板率垫底（11.57%），冷却20日内回头草点火大面率最高（45.56%）；现行96笔主策略中曾连板老股占96.9%（93笔），筹码双通道已内生滤掉绝大多数退潮余孽，任何一刀切冷却拦截或老妖加分均导致全五年或去2025四年退化，保持现行96笔主策略不变。

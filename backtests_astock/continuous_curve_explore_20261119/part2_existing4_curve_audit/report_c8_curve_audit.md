# C8：现有四大主战策略 × 8连续曲线特征 PIT（点时点）审计报告

## 总结论
**现有四大主战策略（三进四 V4.1 / 高标首阴 V5.1 / 二进三 V2.1 / 一进二 V19）的多日连续曲线信息已被既有筹码位置因子（`pos20/dd20/dd60`）与打分门控基本榨干。** 在 329 笔实盘模拟账本交易（含 7 只退市股，严格 `signal_date` 截断并前复权至信号日）上，32 个 `4策略 × 8特征` 组合中，**无任何一项**同时满足 `IS (2021 至 2023)` 与 `OOS (2024 至 2026)` 双段同向、正交残差有效、组合净值不降及宽池盲测泛化四大条件。建议维持现有四大策略选股规则不变。

## 4策略 × 8特征 双段同向审计热力图

| 特征 | 三进四 V4.1 (N=95) | 高标首阴 V5.1 (N=42) | 二进三 V2.1 (N=95) | 一进二 V19 (N=97) |
|---|---|---|---|---|
| `F1_ER10` | 异号失效 / 有符号已吸收(`pos20=+0.84`) | 无显著增量 / 有符号已吸收(`+0.66`) | 非单调砍净值 / 有符号已吸收(`+0.80`) | 非单调砍净值 / 有符号已吸收(`+0.66`) |
| `F2_VCP` | 非单调砍净值 (`OOS` 3Y 净值腰斩) | 异号失效 (`G3` 非单调) | 异号失效 (`G3` U形 / `G2` 异号) | 异号失效 (`OOS` 均值 `-0.21pp`) |
| `F3_MA_ALIGN` | 异号失效 (`MA20` 斜率 `OOS -18.9pp`) | 异号失效 (`MA_SCORE OOS -10.6pp`) | 异号失效 / 已吸收(`pos20=+0.55`) | 已吸收(`dd60=+0.65`, 残差负向) |
| `F4_VOL_BUILD` | 异号失效 (`rho` 由 `+0.29` 翻 `-0.23`) | 弱/小样本噪声 (`IS=17`, 剔除砍半净值) | 异号失效 (`OOS` 残差 `-0.33`) | 砍净值/减胜率 (`OOS` 胜率降 `3.9pp`) |
| `F5_N_WAVE` | 弱同向但砍 75% 样本 (`NAV 2319x->17x`) | 异号失效 (`OOS -7.89pp`) | 异号失效 (`IS +10.8 / OOS -1.8pp`) | 异号失效 (`IS +3.8 / OOS -8.5pp`) |
| `F6_MA5_HUG` | **伪候选（宽池证伪，见下）** | 异号失效 (`OOS` 均值不升) | 异号失效 (`OOS` 残差负, `pos20=+0.75`) | 异号失效 (`rho_oos=+0.02`, `OOS` 负) |
| `F7_YANG_RATIO` | 已吸收(`pos20=+0.57`, 3分位负向) | 异号失效 (`rho` 全负) | 异号失效 (`G3` 负, `OOS` 负向) | 异号失效 (`G2` 异号, 砍净值) |
| `F8_DIST_HI120` | 已吸收(`dd60=+0.89`, `IS` 残差负) | 已吸收(`dd60=+0.74`, 无增量) | 异号失效 (`rho` 由 `+0.23` 翻 `-0.17`) | 已吸收(`dd60=+0.89`, `OOS` 残差 `-0.08`) |

## 重点疑似项核查与证伪依据
1. **三进四 `F6_MA5_HUG >= 5`（表面最亮眼但未通过宽池盲测）**：在 95 笔现役账本中 `F6_MA5_HUG >= 5` 连续 5 个自然年均值占优（`IS +4.42pp`, `OOS +11.07pp`, 全周期 `p_perm = 0.0583`），4 策略单仓合体 5Y 净值由 `2305万x` 升至 `3650万x`（低位被二进三与一进二补位）且回撤由 `34.02%` 降至 `26.05%`。但三大反证将其证伪：
   - 与既有 `pos20` 共线达 `+0.746`；
   - 单独三进四剔除 `<= 4`（砍掉 27 笔）后 5Y 净值反从 `2319x` 降至 `912x`，1000 万封顶实盘倍数从 `79.02x` 降至 `66.33x`，错失浙江建投（`+44.8%`）、长白山（`+38.7%`）、梦网科技（`+35.1%`）等核心龙头；
   - **独立宽池盲测完全归零**：在三进四未入选现役账本的 `254` 笔骨架候选池中，`F6_MA5_HUG` 的 `OOS Spearman = -0.002`（`p = 0.99`），`78<=score<90` 组 `F6 >= 5` 反而跑输 `-1.88pp`。说明其仅为 95 笔小样本高分池的局部波动叠加 `pos20` 映射，并非可泛化的普适曲线 Alpha。
2. **一进二 `F8_DIST_HI120` 与四策略 `F1_ER10_SIGNED`**：与 `dd60`（`+0.89`）及 `pos20`（`+0.66` 至 `+0.84`）高度共线；在控制 `pos20/dd20/dd60/score` 后，`1to2 F8` 的 `OOS` 残差相关性为 `-0.082`（`p = 0.57`），信息已被既有筹码因子完全吸收。
3. **三进四 `F5_N_WAVE`**：N 字二波仅占 25%（`24/95`），剔除纯首波令 5Y 净值暴跌至 `17.2x`，且 `254` 笔宽池的 `IS` 相关性为 `-0.021`。

## 落盘文件清单
- 特征明细表：[all_trades_curve_features_pit.csv](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit/all_trades_curve_features_pit.csv)
- 全量统计与残差审计：[audit_summary_matrix.csv](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit/audit_summary_matrix.csv) / [audit_details.json](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit/audit_details.json)
- 热力摘要与报告：[heatmap_4x8_summary.csv](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit/heatmap_4x8_summary.csv) / [report_c8_curve_audit.md](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit/report_c8_curve_audit.md)

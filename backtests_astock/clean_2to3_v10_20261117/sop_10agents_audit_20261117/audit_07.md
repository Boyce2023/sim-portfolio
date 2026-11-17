# 第 07 号独立历史一致性审查报告（手册第六阶段）

- **审查对象**：`sim-portfolio/prompts/astock_full_lifecycle_sop_handbook.md` 第六阶段（L263-292）
- **核对真源**：
  - `sim-portfolio/data/seasonal_rolling_sr_state.json`
  - `sim-portfolio/scripts/fast_26q4_special_today.py` 与 `sim-portfolio/scripts/daily_3strategies_score_report.py`
  - `sim-portfolio/backtests_astock/clean_rebacktest_20261116/scientific_seasonal_lab/true_walkforward_results_20261116.json`、`scientific_seasonal_comparison_20261116.json`、`run_true_walkforward_seasonal.py`、`ledger_final_mutex_rollsr_20261116.csv`
  - `sim-portfolio/backtests_astock/clean_rebacktest_20261116/audit_overfitting_8tests_20261116.json`

---

## 一、核心审计结论

手册第六阶段存在 **3 处严重机制张冠李戴/事实冲突**，尽管引用的多组单个数值本身可与 JSON 对应，但将两套完全不同的算法与实验结论强行拼接在一起，且对实盘代码能力与回测压平崖壁的描述与源码及 JSON 直接矛盾：

1. **实盘引擎与走步实验脱节，且缺少状态更新脚本**：`seasonal_rolling_sr_state.json` 的数字可在 `full_candidates_3main_5y.pkl` 独立触发池上精确复现（近 10 笔而非近 N 天），但仓库中**不存在**生成该 JSON 与 `ledger_final_mutex_rollsr_20261116.csv` 的脚本，也无每日自动滚动更新该 JSON 的任务；而实验脚本 `run_true_walkforward_seasonal.py` 跑的是另一套完全不同的 `W=40` 交易日连亏收紧与固定偏置算法，根本没跑近 10 笔 `50/50` 贝叶斯夏普收缩和 `>=1.50` 越级规则。
2. **「多股互斥条件单」仅停留在文档与 docstring，实盘代码并未实装**：`fast_26q4_special_today.py` 文件头部 docstring 声称支持「多股互斥条件单」，但其主流程代码（L339-356）实际只输出 1 笔 `09:26 唯一挂单`；手册 L291 所写的「输出多股互斥条件单排序方案」在 `fast_26q4_special_today.py` 与 `daily_3strategies_score_report.py` 中均**未实装**，而 L291 提到的 `RD014` 二进三 `>=96` 分提醒仅存在于第六阶段未提及的 `daily_3strategies_score_report.py` 中。
3. **「彻底压平手工参数崖壁」与 `M3` 实验 JSON 直接矛盾**：手册 L291 引用的 `M3` 绩效数字与 JSON 对齐，但隐去了同份 JSON 显示 `M3` 参数微抖保留率仅 **`35.36%`**、明确触发 **`悬崖警报 (跌幅超50%)`**（比旧版 `26Q4` 的 `48.17%` 更陡），且 `M3` 全五年、2026 全年与 `PBO` 均跑输严格 0926 唯一挂单口径的静态五年基础版，同时 `run_true_walkforward_seasonal.py` L233 注释定版的是 `M1` 而非 `M3`。

---

## 二、逐项挑刺核对明细

### 挑刺 1：`train_stds_2021_2025`、`blended_seasonal_sr` 与近 10 笔窗口一致性

1. **数值与实盘读取完全对齐，但计算口径存在隐藏细节**：
   - `seasonal_rolling_sr_state.json`、`fast_26q4_special_today.py`（L37-38）、`daily_3strategies_score_report.py`（L88-89）与手册 L277-279 完全一致：
     - `train_stds_2021_2025`：高标 `14.9334`、三进四 `6.8491`、一进二 `26.1185`
     - `train_prior_sr_2021_2025`：高标 `0.4763`、三进四 `0.4117`、一进二 `0.2995`
     - `recent_10_paper_sr`（`recent_10_count = 10`）：高标 `1.5006`、三进四 `0.6553`、一进二 `0.8109`
     - `blended_seasonal_sr`：高标 `0.9884`、三进四 `0.5335`、一进二 `0.5552`（严格等于 `0.5 * train_prior_sr + 0.5 * recent_10_paper_sr`）
   - 经针对 `full_candidates_3main_5y.pkl` 实算核验：该 JSON 取自独立策略全池中 `is_base_passed == True & triggered == True` 的样本（而非单仓合体交割单）。其中 `train_stds` 与 `train_prior_sr` 对 `buy_date < 2026-01-01` 用样本标准差（`ddof=1`，实算：`14.933375 / 6.849143 / 26.118490` 与 `0.476280 / 0.411720 / 0.299483`），而 `recent_10_paper_sr` 对最近 `10` 笔已触发合格样本改用总体标准差（`ddof=0` / `np.std`，实算：`1.500591 / 0.655273 / 0.810861`）。同一张 JSON 内部混用 `ddof=1` 与 `ddof=0`。
2. **实盘代码 vs 实验脚本严重裂痕（两套完全不同的引擎）**：
   - **生成脚本缺失与静态冻结**：全仓无任何 `.py` 脚本写出 `seasonal_rolling_sr_state.json` 或同时间戳落盘的 `ledger_final_mutex_rollsr_20261116.csv`（187 笔，全五年复利 `43,399.81` 倍）。现役 `fast_26q4_special_today.py` 与 `daily_3strategies_score_report.py` 均只读 `seasonal_rolling_sr_state.json`（锁死在 `as_of_date: 2026-11-16`），无每日自动滚动重算 `recent_10_paper_sr` 的脚本或定时任务。
   - **实验脚本 `run_true_walkforward_seasonal.py` 根本不是这一套算法**：
     - 标准差口径不同：`run_true_walkforward_seasonal.py` L56-58 对 `train_all` 全样本（含未过线与未触发样本）求 `std()`，得到的是 `16.1798 / 8.5963 / 31.7554`，而非 `14.9334 / 6.8491 / 26.1185`；
     - 择优底分不同：L148-150 / L184-186 / L223-225 使用静态层级偏置（高标 `+0.50`、三进四 `+0.25`、一进二 `+0.00`）按 `z_comp` 降序直接选第一名，既不用 `blended_seasonal_sr`，也不用 `>= 1.50` 越级裁决树；
     - 滚动窗口与调节逻辑不同：`run_true_walkforward_seasonal.py` 的 `M1` / `M3` 使用过去 **`W=40` 个交易日**窗口（而非近 10 笔）内「最近 2 笔全亏就抬高门槛」（`M1`：高标 `+3` / 三进四 `+3` / 一进二 `+8`；`M3`：三进四 `+2` / 一进二 `+6` 叠加 `csi_20d < -0.02` 时三进四 `+3`）。这些动态抬门槛规则在实盘 `fast_26q4_special_today.py` 中完全不存在。

---

### 挑刺 2：`fast_26q4_special_today.py`、`daily_3strategies_score_report.py` 与手册的机制差异

1. **`fast_26q4_special_today.py` 自相矛盾（docstring 写多股互斥，实际代码跑唯一挂单）**：
   - 文件头 docstring（L4、L8-9）与 `argparse` 描述（L294）仍写：「多股互斥条件单 + 滚动夏普把握度择优」，声称若无开盘直买单而有多只突破条件单过线，则「同挂同花顺多股互斥条件单（未触发不冻资，谁先触及突破价先成交，同刻触发按 `rk_prio` 择优）」。
   - 但实际决策代码（L339-356）执行的是「严格盘前唯一单挂单裁决」：各策略只取排名第 1 的过线标的组成 `top_cands`，比较 `priority` 最高者与 `rk_prio` 最高者，仅当 `top_by_conv["rk_prio"] - top_by_order["rk_prio"] >= 1.50` 时越级，否则按 `priority` 选唯一 1 笔 `chosen`（L354 输出 `09:26 唯一挂单`）。**并未实现任何多股互斥条件单输出逻辑**。
2. **两份实盘脚本的真实差异**：
   - **策略覆盖不同**：`fast_26q4_special_today.py` 仅评估三大主策略（高标、三进四、一进二）；`daily_3strategies_score_report.py` 评估五大策略（额外纳入第 3 顺位 `超跌撬板 V1.0` 与第 5 顺位 `二进三 V1.0`），L269-285 在无高标/三进四过线且符合分档条件时优先切入 `09:25` 超跌撬板，三大策略都空窗时补位 `二进三`，并在 L298-300 单列二进三 `>=96` 分提醒。在三大主策略碰撞裁决上，两者逻辑完全相同（均为 L273-276 的 `>= 1.50` 唯一挂单越级，而非互斥条件单）。
   - **同策略计算细节漂移**：
     - 高标一字否决：`fast_26q4_special_today.py` L104 检查 `q.get("is_yizi", False)` 并写入 `veto_reasons`；`daily_3strategies_score_report.py` L96-115 缺少该一字否决判断；
     - 基准日门禁：`daily_3strategies_score_report.py` L66-68 强制校验四大缓存日期一致（`[S15基准日硬断言阻断]`）；`fast_26q4_special_today.py` 无此校验；
     - 缺失行情兜底与精度：`fast_26q4_special_today.py` 三进四 `buyable_open` 缺失行情时用 `r["px_d3"] * 1.10` 作涨停价且一进二 `rk_prio` 保留 3 位小数；`daily_3strategies_score_report.py` 用 `999` 作缺失涨停价兜底且一进二 `rk_prio` 未四舍五入。
3. **手册第六阶段未讲清且存在未实装声明**：
   - 第六阶段通篇只点名 `fast_26q4_special_today.py`，未交代 `daily_3strategies_score_report.py` 在当季专供仲裁中的五策略整合角色（后者仅在第七阶段 L330 作为 10:40 复盘工具出现）。
   - 手册 L291 声称「在实盘 `09:26` 无竞价直买单而有多只突破单同时过线时，系统亦可依据同一套标准输出多股互斥条件单排序方案，并在触发 `RD014` 二进三 `>=96` 分时单列高确信提醒」：其中「输出多股互斥条件单排序方案」在两份脚本中均未实装；`RD014` 提醒仅存在于 `daily_3strategies_score_report.py`，不在手册唯一指定的 `fast_26q4_special_today.py` 中。

---

### 挑刺 3：手工微调 `26Q4` 警报数字与 `M3` 走步前向盲测数字核对

1. **手工微调 `26Q4` 专供（手册 L269 vs `audit_overfitting_8tests_20261116.json`）**：
   - **全部具体数字 100% 对齐**：
     - `2026_10_11` 交易笔数 `1 至 7` 笔：高标 `1` 笔、三进四 `3` 笔、一进二 `5` 笔、三主合体 `7` 笔；
     - `2022_2025` 单笔平均收益较基础版倒退 `0.5%` 至 `2.0%`：高标 `5.95% -> 5.16%`（`-0.79pp`）、三进四 `10.13% -> 8.18%`（`-1.95pp`）、一进二 `8.03% -> 6.13%`（`-1.90pp`）、三主合体 `7.45% -> 6.09%`（`-1.36pp`；`scientific_seasonal_comparison_20261116.json` 费率对齐后为 `6.19%`，`-1.26pp`）；
     - 保留率与 `PBO`：三主合体 `min_perturbation_retention_pct = 48.17%`、`pbo = 0.3286`（`32.86%`）；一进二 `pbo = 0.2286`（`22.86%`）；高标 `pbo = 0.4143`（`41.43%`）。
   - **隐瞒的重要对照上下文**：JSON 中基础版三主合体的 `min_perturbation_retention_pct` 本身为 `41.16%`（同样触发 `"悬崖警报 (跌幅超50%)"`），且 `26Q4` 各项 `PBO` 在 JSON 中的 `pbo_verdict` 字段均写 `"稳健通过 (PBO < 50%)"`，手册将其定性为「过拟合警报」虽有理据（较基础版 `0%~4.29%` 显著飙升），但未交代基础版合体自身也低于 50% 保留率红线。

2. **`M3` 走步前向盲测（手册 L291 vs `true_walkforward_results_20261116.json`）**：
   - **数字引用 100% 对齐**：
     - 全五年 `181` 笔、`nav_slot = 20636.35`（`cap10m_mult = 109.54`）；
     - 2026 全年 `39` 笔、`win_rate = 69.23%`、`nav_slot = 11.23`（`cap10m_mult = 11.19`）；
     - 2026 年 10 月以来 `4` 笔、`win_rate = 75.0%`、`nav_slot = 1.25`、`excess_slot_pp = 33.21`；
     - `test4_cscv_pbo.pbo = 0.1714`（`17.14%`）、`test1_dsr_hlz.DSR_prob_M150 = 0.9992`、`years_beating_csi300 = "5/5"`、`test8_hell_mode.hell_mode_excess_pp = 832.95`。
   - **三处实质性冲突与报喜不报忧**：
     1. **与 JSON 崖壁检测直接冲突**：手册 L291 声称「该架构彻底压平了手工参数崖壁」，但 JSON（L674-676）明确记载 `M3` 的 `min_retention_pct = 35.36`，`plateau_verdict = "悬崖警报 (跌幅超50%)"`，微抖保留率比旧版 `26Q4`（`48.17%`）和静态五年基础版（`41.16%`）**更低**；
     2. **绩效与定版双重错配**：实验脚本 `run_true_walkforward_seasonal.py` L233-235 最终导出定版的是 **`M1`**（`N=184`, `nav_slot=26011.16`, `PBO=12.86%`），而非手册宣传的 `M3`；且无论是 `M1` 还是 `M3`，均不是实盘 `fast_26q4_special_today.py` 所运行的算法；
     3. **跑输基准未如实披露**：在同份 `true_walkforward_results_20261116.json` 中，严格 0926 唯一挂单口径的「静态五年基础版」（`N=187`）全五年净值 `39,647.03` 倍（千万封顶 `116.98` 倍）、2026 全年 `11.97` 倍、`2021-2025(Train)` 均益 `7.28%`、`PBO = 8.57%`，全面优于 `M3`（仅在 `2026年7月以来` `3.01x vs 3.22x` 和 `2026年10月以来` `1.14x vs 1.25x` 两个短窗劣于 `M3`）。

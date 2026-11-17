# 03 号独立历史一致性审查报告

> **总结论先行**：手册《第二阶段》对「三进四 V3.4」、「超跌撬板 V1.0」、「四进五 V2.0 下放」、「二进三 V1.0」核心打分卡框架基本忠实于对应主研究代码，**但实盘脚本与文档及台账之间存在 6 处 P0 级硬冲突与 14 处 P1/P2 级口径及数字漂移**。最严重的三项实盘隐患为：① `fast_4to5_today.py` 仍在沿用未修复的旧版打分与重复计分 Bug，且漏掉「昨日午后未炸板」硬门、读取了不存在的 `3to4_premarket_cache.json` `"score"` 字段并误标 `[4to5 第3顺位]`；② `fast_pry_today.py` 漏掉「非ST」硬门且脚本与交接文档仍硬编码旧的 `[s_pry 第4顺位]`；③ `backtests_shared_ledger.md` 与手册内部在 `ST009` 定版状态、RD011 代表案例得分与极严档单仓笔数净值、以及二进三合体净值与测试淘汰项披露上多处自相矛盾。

***

## 一、三进四 V3.4 一致性审查

**总结论**：`score_3to4_v31_card.py` 与手册第 150 行因子、门槛、13:45 护利及禁挂 93% 异动单规则一致；**但 `backtests_astock2/CURRENT_MANIFEST.md` 仍挂着已过时的 V3.2 回测脚本，台账 `ST006` 与策略宪章仍停留在旧版 `53笔 / 160.39倍`，实盘缓存与盘中计算存在多处静默回退默认值。**

1. **版本与代码漂移（P1）**：`sim-portfolio/backtests_astock2/CURRENT_MANIFEST.md` L4 仍将 `bt_3to4_v32_final_build.py` 列为当前三进四现行脚本，但该文件实为 **V3.2 旧版**（L137/150~151 仍把 `is_top1_3b_open`、`lock_top10/real_free_mcap`、`prev_to` 放在硬骨架 `skel_v32` 中，且 `p_elo >= 115` 给 `+5` 分而非 `+3` 分，缺失开板时间 `+3`、节后或周一 `+2`、1/5月 `-4`）。真正实现 V3.4 规则的是命名仍叫 `v31` 的 `sim-portfolio/backtests_astock2/score_3to4_v31_card.py`（L40 起：底分 `78`、6 门、10 加分 + 13 扣分，三档门槛 `90/98/102`）。
2. **交易微观逻辑核验（通过 + 细节误差）**：
   1. `core_3to4_5m_engine.py` L182~196 `pm1345_5m` 实测先检查 `hhmm >= 1345 and peak >= pck*1.085 and bl <= pck*1.050 and bc < ztk-0.01`，后更新 `peak = op_k`（无未来函数），挂 `min(bo, pck*1.050)` 卖出，且 `partA_high_3to4/build_partA_rebacktest.py` L302 确认传入 `use_dev93=False`（禁用 93% 异动挂单）与 `use_yang_imm=True`。
   2. 细节口径差异：`core_3to4_5m_engine.py` L226 强留条件为 `(c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)`，即「收假阳线但收盘跌破前收 `p4`」或「高开收阴 `c4 < o4`」均触发斩仓；手册 L150 简写为「未封收绿或次日高开不足0.5%于09:25斩仓」，不如 `strategy_astock.md` L69「收绿收跌」严谨。
3. **跨文件业绩数字打架（P1）**：手册 L182 与权威源 `partA_high_3to4/summary_base_3to4_v34.json` 一致（全5年 `88笔 / 胜率 64.77% / 盈亏比 2.23 / 562.10倍 / 62.06倍 / 回撤 31.25%`；近3年 `56笔 / 69.64% / 202.48倍`）。但 `sim-portfolio/backtests_shared_ledger.md` L32（`ST006`）与 `sim-portfolio/strategy_astock.md` L70 仍写旧版 **「近3年 53笔胜率 67.9% 净值 160.39倍、eq_nav 1910.05倍、双半仓 282.82倍、CSI300 5年 `-17.84%`」**；此外 `p3_deep_100/common_eval_harness.py` L54 注释仍写 `三进四 V3.4 精确 79 笔`。
4. **实盘脚本静默回退与阈值偏差（P1）**：`live_3to4_cache_builder.py` L269 在股东锁仓缺失时默认填 `lock10 = 38.0`；`live_3to4_intraday.py` L61~63 默认 `plate_peers_open_avg=0.01`；`daily_3strategies_score_report.py` L133 统计 `plate_fb_ho_cnt` 用 `>= 0.025`，与 `live_3to4_intraday.py` L124 的 `>= 0.03` 不一致。

***

## 二、超跌撬板 V1.0 一致性审查

**总结论**：交接文档 `strategy_oversold_pry_v10_pm_handover.md` 与回测引擎 `precompute_return_matrix.py`（`E8_nextday_w2s` + `X10`）逻辑相符，**但实盘脚本 `fast_pry_today.py` 缺失「非ST」硬门且顺位标签过时，手册表内漏写连板持有分支并把不同统计母体的 `76.0%` 与 `72.0%`、`1.34倍` 与 `1.26倍` 混用。**

1. **实盘「非ST」硬门缺失与全市场涨停计数口径偏差（P0）**：手册 L152 与 `strategy_oversold_pry_v10_pm_handover.md` L14 明确要求 4 道硬门含「非ST」；但 `sim-portfolio/scripts/fast_pry_today.py` L203~211 全文**未检查股票名称是否含 ST 也未读取 `st_universe.json`**，仅按 `00/60` 主板前缀与 `tox_codes` 过滤。同时该脚本 L130 与 L280 仅统计 `00/60` 主板股 `zt_open_cnt`（约 3,195 只，报错文案 L279 却写 `< 4500`），而交接文档写「全市场竞价涨停家数满12家」。
2. **全局顺位互殴与越级提醒空转（P0）**：
   1. 手册 L235/L239、`strategy_astock.md` L15/L40、`daily_3strategies_score_report.py` L270 与 `backtests_shared_ledger.md` L35 已锁定新 5 顺位：**超跌撬板为第3顺位（四进五已下放）**。
   2. 但 **`fast_pry_today.py` L4/268/272/290 仍硬编码 `[s_pry 第4顺位] ... 顺延至第5顺位一进二`**；`CURRENT_MANIFEST.md` L1 挂在首位的 **`strategy_oversold_pry_v10_pm_handover.md` L3/32/34/52 仍锁定旧版「高标 > 三进四 > 四进五120分 > 超跌撬板165分 > 一进二」**；手册 L152 自身也只含糊写「排在高级别策略之后、压在一进二之前」。
   3. 手册 L261 要求「超跌撬板 165至174分 普通过线档不得盲目挤占 一进二 S档（>=355分）」，但 `daily_3strategies_score_report.py` L269~270 在 `p_pry` 过线时无条件直接输出第3顺位超跌撬板，未对 `一进二 >= 355分` 做越级比较拦截。
3. **动态止盈公式与手册遗漏分支（P1）**：`p5_full_pry_universe/_archive/20261116_stage12_sweeps/precompute_return_matrix.py` L31~88 实盘模拟 `X10` 规则确认为：`clip(0.45 * abs(prev_ret10), 0.06, 0.16)`，最长 4 天，盘前挂 `round(buy_px * (1 + tp_r), 2)` 限价单；回封跌停次日斩仓；**若买入当日或中途封死涨停，走 `hold_zt_relay` 连板持有至断板**。交接文档 L38 完整保留了连板持有分支，但手册 L152 单元格遗漏了该分支，且 `fast_pry_today.py` 仅校验 `sub.iloc[-11]["close"]`（未复权收盘价，缺交易日缺失保护）并把缺失股东锁仓默认填 `0.0`（L233）。
4. **回测数字与底池口径混用（P1）**：
   1. `65,911` 条实际是 `full_pry_master_enriched.parquet` 扩展候选全集（含昨日触跌停、连续跌停等，纯触跌停仅 `37,443` 条），手册 L133 写成「65,911 条跌停触及底池」不准确。
   2. `p5_full_pry_universe/v1_oversold_pry_165_strict_ledger.csv`（435 笔全候选池按 25 天等权）每日等权胜率为 **`76.0%`**，而 11 月 16 日权威单日头名台账 `partC_aux/ledger_aux_pry_v10.csv`（25 笔）实际胜率为 **`72.0%`**（18/25，因 `2026-07-22` 头名 `1259` 亏 `-5.08%` 而同日第2名 `2695` 赚 `+11.14%` 拉正全天均值），等权净值 `3.8925倍`；近3年单仓净值权威口径为 **`1.2632倍`（`1.26倍`，PLR `0.78`，手册 L184 一致）**，而 `backtests_shared_ledger.md` L16（RD009）与交接文档仍混写「25日等权 `76.0%`、近3年 `1.34倍`（PLR `1.12`）、与旧3策略合体 `136,325.63倍`（111.84pp）」。

***

## 三、四进五 V2.0 下放一致性审查

**总结论**：**本模块是全库漂移最严重的重灾区**。现行日常脚本 `fast_4to5_today.py` 与研究脚本 `w2_4to5_v20_scorecard.py`、11 月 16 日修复版 `run_ref_4to5_fixed()`、台账 `ST007` 及手册第 154 行之间**存在五方口径互不相容的问题**，若继续作为下放观察脚本运行会产出失真信号。

1. **交接文档物理路径失效（P1）**：`strategy_astock.md` L109 与 `backtests_shared_ledger.md` L33 均指向 `sim-portfolio/prompts/strategy_4to5_v20_pm_handover.md`，该路径文件**已不存在**（已归档至 `prompts/_archive/20261116_legacy_prompts/strategy_4to5_v20_pm_handover.md`）。
2. **`fast_4to5_today.py` 存在 6 处代码级 Bug 与严重规则漂移（P0）**：
   1. **顺位自相矛盾**：文件头 L6 写「不上实盘」，但 L387/396/443/448 仍输出 **`[4to5 第3顺位]`** 与「顺延至第4顺位超跌撬板或第5顺位一进二」。
   2. **丢失核心硬门**：手册 L154 明确要求「昨日午后未炸板」（即 `d4_blown_pm == 0`），`fast_4to5_today.py` **完全未读取 5 分钟线，根本没有午后炸板过滤**。
   3. **重犯已证伪的重复计分 Bug**：`partC_aux/run_partC_aux_clean_rebacktest.py` L315~318 已点名修复 `w2_4to5_v20_scorecard.py` 把唯一活口同日再当第1名叠加 `+6 + +3 = +9` 的 Bug（改用 `elif` 仅加 `+6`）；但 `fast_4to5_today.py` L427~428 仍沿用 `if is_sole: +6` 再 `if is_top1: +3` 的双倍计分 Bug。
   4. **左翼基因维度读取了空字段**：`fast_4to5_today.py` L290~300 改写了原评分表第5维（删去 `is_held_3to4`、`d4_op>9.2%&open 2~6%`、`obc>=1&d3_obc>=1&to_ratio`，自造 `d3_is_yz and not d4_is_yz` 与 `to_d4>=10%`），并从 `3to4_premarket_cache.json` 读取 `c3_cand.get("score", c3_cand.get("static_score", 85.0))`，**而 `live_3to4_cache_builder.py` L298~310 根本不输出 `"score"` 或 `"static_score"` 字段**，导致永远回退到常数 `85.0`（且 `left_sc = min(15, left_sc)` 实际封顶仅 12）。
   5. **指数基准与缺失默认值静默错配**：`fast_4to5_today.py` L183~184 读取 `sh000001`（上证综指）和 `sz399001`（深证成指），违背手册 L104 指定的 `sh000002`（上证A指）与 `sz399107`（深证A指）；L221 对缺失 `lock/fmcap` 直接静默填 `38.0` / `25.0`。
   6. **第7维缺失与扣分篡改**：`fast_4to5_today.py` L321~325 删去了 `f47_reb_zt_r10 >= 0.20 (+6)`（即手册 L154 写的「反包热区」）和 `d4_mkt_nuke_cnt >= 1 (-3)`，并将 1/5 月扣分 `-6`、同板块3板+扣分 `-6` 擅自改成 `-4` 与 `-4`。
3. **120 分账本 CSV 与固定后净值不一致（P1）**：`p3_deep_100/w2_4to5_v20_ledger.csv` 实存 **51 笔（`v20_score >= 114`，含 114~119 分且开盘 `-1% ~ +8.5%`）**，并非 120 分高严档；`backtests_shared_ledger.md` L33（`ST007`）仍写旧的 Bug 版「19笔 8.11倍」，而 11 月 16 日修复重复计分后的权威文件 `partC_aux/summary_ref_4to5_fixed.json` 实为 **原始 17 笔 / 单仓 15 笔 / 胜率 66.67% / 净值 9.47倍 / 回撤 13.45%**。

***

## 四、二进三 V1.0（ST009 / RD014）一致性审查

**总结论**：底分 `58` 分、5 道硬门、14 项整数加减分及 `90 / 96` 门槛在 `bt_2to3_v10_clean_master.py` 与 `fast_2to3_today.py` 间对齐度极高；**但手册自身定版状态前后撕裂、Phase 3 未按承诺披露 `RD014` 弱项与红黄灯指标、S/A 分档统计混淆了两个不同口径、且主回测脚本与 5 顺位审计脚本因同分排序差异导致全5年合体净值出现 21,422 倍漂移。**

1. **定版状态与 `ST009` 编号自相矛盾（P1）**：
   1. 手册 Phase 0（L39）明文规定「已定型策略 ST001 至 ST008，如 `RD014` 二进三不得提前虚增 `ST009`」，Phase 2（L153）仍标注「`RD014` 在研、仅研发论证阶段，待定版后决定是否进实盘白名单」。
   2. **但同一份手册 Phase 5（L235/239）已把 `s_2to3` 列入「五大实盘策略」第5顺位和 `execute_trade.py` 白名单**，`backtests_shared_ledger.md` L21/L35 已赋号 `ST009（已定版入宪）`，`strategy_astock.md` L118 与 `execute_trade.py` L95 均已实装 `s_2to3`。
2. **两套权威脚本合体净值差 `21,422` 倍的代码根因（P1）**：`bt_2to3_v10_clean_master.py`（`summary_2to3_v10_d15_and_audit.json`）报告 5 策略第5顺位 5 年净值为 **`1,472,852.44倍`（PLR 2.65）**，而 `audit_5strategies_priority_winrate.py` 与手册 L235 报告 **`1,451,430.04倍`（PLR 2.64）**。实测两者 229 笔交易组成完全一致（`67 / 63 / 53 / 35 / 11`），唯一差别在 `2023-08-08` 当日有两只同为 `91.0` 分的二进三标的：`bt_2to3` 按 `clean_2to3_5y.parquet` 原始顺序由 `run_1slot` 稳定排序买入 `000936 华西股份`（`-9.89%`），而 `audit_5strategies` L34 先按 `open_pct` 排序导出 `candidates_2to3_v10_all_raw90.csv` 买入 `600468 百利电气`（`-11.20%`）。
3. **手册 Phase 3 选择性漏报 `RD014` 不及格项（P1）**：手册 L162 承诺「严禁隐瞒黄灯或红灯项」，但 L166~L173 表 1、表 2 仅列出 `RD014` 的 Test 2（`p=0.0022`）、Test 3（`100% > 1x`，中位 `11.54x`）和 Test 8（`77/32`，`0.0`），**完全隐去了 `summary_2to3_v10_d15_and_audit.json` 中实测未达标或黄红灯的 4 项硬伤**：`std90` 的 `HLZ t = 2.53 < 3.0`（`strict96` 为 `2.27`）、`DSR(M=150) = 0.4008 < 0.90`（`strict96` 为 `0.2302`）、`Test 7 去前15%大牛后净值跌破1倍 = 0.44x`、`CSCV PBO (S=10) = 36.51%`。
4. **S/A 分档统计混用口径与数字错误（P1）**：
   1. 手册 L254 写高标首阴 `S档 (>=96分)` 为 **`19笔 / 73.68%`**；核查权威单仓台账 `ledger_base_high_v51.csv` 实为 **`34笔 / 73.53%`**（25/34），而无遮蔽触发池 `full_candidates_3main_5y.pkl` 每日头名为 **`38笔 / 73.68%`**（28/38），`19笔` 无磁盘对应文件。
   2. 手册 L255 写二进三 S 档 `29笔 / 62.07% (单仓 75.00%)`，把**独立每日头名池（29 笔，注意纯独立单仓实为 27 笔 / 62.96%）**与**5策略第5顺位组合内实做（16 笔 / 75.00%）**混写在同一括号。
   3. 手册 L256 写二进三 A 档 `62笔 / 43.55% (单仓 47.22%)`，其中 `62笔 / 43.55%` 为独立每日头名，但权威 5 策略第5顺位台账 `ledger_combined_5strat_slot5_canonical.csv` 内 A 档实做是 **`37笔 / 48.65%`**（18/37），并非 `47.22%`。
5. **实盘脚本与代码细节瑕疵（P2）**：
   1. `bt_2to3_v10_clean_master.py` L108 注释写 `满分理论 119 分`，按 L122~147 实算最大正向分量之和为 `58 + 69 = 127 分`；`summary_2to3` L889~891 显示 `has_5m_buy_pct = 0.0%`、`has_5m_d4_unsealed_pct = 0.0%`（因二进三买在 09:25 竞价、不封死 3 板走日线收盘卖出，与手册 L101/124 宣称的「5m 覆盖 100% Gate1」易引发误解）。
   2. `fast_2to3_today.py` L970 与 `strategy_astock.md` L101 均写 `14:55（收盘）清仓`，手册 L101 写 `15:00`（回测取收盘价 `ret_opn_cc`）；`fast_2to3_today.py` L970 漏标 `(一字跌停顺延)`；L353/366 解析 `notices.db` 时用 `nd <= buy_date` 未加 `09:25:00` 时间截断；L123 `is_yz` 用 `>= 0.095` 而三进四、撬板与四进五实盘脚本均用 `0.090`；L493 在 `q_hhmm < 1500` 遇到盘前缓存落后时直接 `pass`。

***

## 五、`astock2` 辅助课题 RD010 至 RD013 一致性核查

**总结论**：RD010 与 RD013 报告基数大体真实可复现，**但 RD011 内部代码、研究报告与总台账出现多处严重的公式权重、个股打分及单仓笔数净值矛盾；RD012 报告中「近3年恐慌崩盘胜率 66.7%、+1.22%」在账本中无对应记录；RD013 在 11 月 17 日新跑的 `summary_v51_ge3_final.json` 尚未回写总台账。**

1. **RD010（证监会监管发言 144 因子）**：
   1. **核对一致**：`factors_144_full_ledger.csv` 确为 `144` 行（有效核心 `22`、条件或弱有效 `19`、证伪 `103`）；`master_events_pit.parquet` 确为 `657` 条对齐事件（2000 至 2026）。
   2. **轻微脱节（P2）**：原始分片 JSON 已移入 `output/csrc_policy_100factors_20261114/_archive/20261116_shards_and_logs/shards/`，但 `csrc_corpus_compiler.py` L13 仍读未归档的 `shards/`；`backtests_shared_ledger.md` L17 错拼成 `stock2`（应为 `astock2`）。
2. **RD011（跨年大妖 120 因子与 V4.0 打分卡）：多处直接矛盾（P0/P1）**：
   1. **公式权重不匹配**：`report_rd011_v4_120factors.md` L65~67 写 `Top2题材 +15`、`地缘上限 +10`、`重大合同 +8`、`新子公司 +8`，漏写扣分与小项；而官方代码 `step4_run_v4_scorecard_official.py` L14~52 实为 `Top1 +15 / Top2 +8`、`地缘上限 +12`、`重大合同 +10`、新增 `is_ir_unpopular_90d (+6)`、`name_matches_theme_or_map (+6)`、`is_csrc_outsider (-15)`、`dev_10d>0.70 (-20)`、`dev_30d>1.85 (-25)` 与 `days_since_last_ord_abn * 1.5 (上限+15)`。
   2. **代表案例得分四中三错**：按 `step4` 官方脚本与 `grand_cross_year_120factors.parquet` 实算并核对 `v4_scorecard_ledger.csv`（门槛 `>= 60`）：
      1) `000547 航天发展` (`2025-12-01`)：代码与 `backtests_shared_ledger.md` L18 均为 **`129.8 分`**（`+57.33%`），**但 `report_rd011` L90 写成 `110.3 分`**。
      2) `000592 平潭发展` (`2025-10-23`)：代码实算仅 **`45.0 分`（未过 60 分门槛，不在 `v4_scorecard_ledger.csv` 中）**，**但 `report_rd011` L91 谎称「打分卡评分通过」**。
      3) `603778 国晟科技` (`2025-11-24`)：代码实算 **`57.7 分`**，**`report_rd011` L92 写成 `44.7 分`**。
      4) `603929 亚翔集成` (`2025-11-03`)：代码与 `v4_scorecard_ledger.csv` 实为 **`69.0 分`（已过 60 分线）**，**`report_rd011` L93 写成 `53.0 分`**。
   3. **98 分极严档单仓笔数及净值与总台账不一致**：`step4_run_v4_scorecard_official.py` 官方落盘阈值实为 **`>= 60`**（全5年 `45~350亿` 单仓 `49笔 / 14.3% / 净值 0.37倍`）。即使按 `step4` 完全相同的单仓轮动代码过滤 `v4_score >= 98`（`45~350亿`），实测得 **全5年 `8笔 / 胜率 25.0% / 净值 1.2664倍 / 超额 +26.49pp`；近3年 `6笔 / 胜率 33.33% / 净值 1.2917倍 / 超额 +28.96pp`**，并非 `backtests_shared_ledger.md` L18 所写的 **「9笔净值1.27倍超额25.5%、近3年7笔胜率42.9%净值1.29倍超额27.9%」**。
   4. **D15 基准违背**：`step4` L78/82 仅按持仓窗口累乘 `hs300_ret_smart`，导致同一 5 年周期内 `45~350亿` 档等权报告 `hs300_return_pct = +4.5%` 而单仓报告 `-4.5%`（`v4_scorecard_summary.json`）。
3. **RD012（科技暴跌切换消费与银行）**：
   1. 绝大部分数据与 `summary_defensive_switch.json` 核对一致（白酒跷跷板3日 `19笔 / 36.8% / -0.62%`、生猪5日 `22笔 / 22.7% / -2.04%`、模式1阴跌银行红 `36笔 / 36.1% / -0.44%`、2024至2026 高ROE银行持5日 `43笔 / 67.44% / +0.97% / 回撤 6.06%`）。
   2. **矛盾点（P1）**：`report_defensive_switch_consumption_bank_v1.md` L22/L79 声称高 ROE 银行在「模式2 恐慌暴跌大盘」下 **「近3年胜率 66.7%、均值 +1.22%」**；但 `run_topic2_defensive_switch.py` L490~513 并未生成按年代拆分的 `Pattern2` 统计，直接核查 `ledger_defensive_switch.csv` 中 `era=='2024_2026'` 与 `dt>='2023-11-16'`（`T0_Close, 3d`）均实为 **`11笔 / 胜率 72.73% / 均值 +1.37%`**，不存在 `66.7% / +1.22%`。
4. **RD013（断板反包与 N 天 M 板）**：
   1. 2026年11月16日 原报告核心数字与 `summary_rd013.json` 一致（`Alpha_All 16.14%`、`F05 brk_r10>=15%` 实为 `23笔 / 60.87% / +5.75%`）。
   2. **未同步更新（P2）**：目录内新增 2026年11月17日 运行产出的 `run_final_rebound_ge3_v51.py` 与 `summary_v51_ge3_final.json`（证实全市场 `>=3板` 反包仅得 `N=28`、其中 3 板仅 2 笔、5 年胜率 `50.0%`、单仓净值 `1.78倍`），`backtests_shared_ledger.md` L20 尚未补充记录该结论。

***

## 六、清单与台账互锁缺失及建议修订点（供汇总组定稿）

1. **`backtests_astock2/CURRENT_MANIFEST.md` 严重过期**：未登记 `RD010`、`RD011`、`RD012`、`RD013` 目录路径，也未将现行三进四 V3.4 脚本指向 `score_3to4_v31_card.py`，仍列着旧版 `bt_3to4_v32_final_build.py` 与未修 Bug 的 `fast_4to5_today.py`。
2. **`backtests_astock/CURRENT_MANIFEST.md` 仅 9 行且含失效链接**：L1 仍挂着顺位过时的 `strategy_oversold_pry_v10_pm_handover.md`，缺少 `clean_2to3_v10_20261117/` 与 `ST009` 说明。
3. **建议集中修补项**：① 立即修复 `fast_pry_today.py` 缺失非ST硬门与 `[第4顺位]` 旧标签；② 停用或按 `run_ref_4to5_fixed()` + 5m 午后炸板检测彻底重写 `fast_4to5_today.py`，并将 `w2_4to5_v20_ledger.csv` 与 `ST007` 统一到 120 分及 17 笔 9.47 倍口径；③ 手册 Phase 0/2/5 对 `ST009` 定版状态统一表态，Phase 3 补齐 `RD014` 弱项披露，Phase 5 重核 `高标首阴 >=96`（34笔/73.53%）与 `二进三 A档`（37笔/48.65%）分档口径；④ 清理 `backtests_shared_ledger.md` 中 `ST006`、`RD009`、`RD011` 与 `strategy_astock.md` 的旧数字及断链。

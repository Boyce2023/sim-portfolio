# 第 05 号独立历史一致性审查报告（手册第四阶段 vs 磁盘现役源码）

- **审查对象**：`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/prompts/astock_full_lifecycle_sop_handbook.md` 第四阶段（L193-L211）
- **核查方式**：只读逐行核验磁盘现役生产脚本、回测引擎与 `backtests_shared_ledger.md`
- **总体结论**：手册第四阶段 7 项补丁中，**仅补丁 5（锁仓百分制与 `bias10` 升序）完全一致**；其余 6 项均存在不同程度的代码漂移、门禁缺失、白名单过时或源链路描述失实，其中 **补丁 6（三源回退顺序与6道门禁）** 与 **补丁 7（`execute_trade.py` 白名单、T0门禁、锁机制）** 出入最严重。

---

## 一、逐项核查明细（精确到文件、行号与函数名）

### 补丁 1：日线落盘滞后自动缝合补丁（手册 L197）
- **手册声称**：`live_3to4_cache_builder.py`、`fast_pry_today.py`、`fast_high_dragon_today.py` 与 `fast_1to2_today.py` 均内置腾讯实时收盘快照补齐（检测 `sh000300` 最新交易日大于本地最大日期且过 `15:00` 时并发拉齐 `>=2000` 只主板），且回测与主报告强制断言 `data_as_of_date == 最新收盘交易日`。
- **源码一致项**：
  1. `sim-portfolio/backtests_astock2/live_3to4_cache_builder.py`（`build_premarket_cache`, L51-L85）：确实查 `qt.gtimg.cn/q=sh000300`，判断 `q_dt > max_p_date and q_hhmm >= 1500`（L57），并发补齐且要求 `len(patch_rows) >= 2000`（L82）。
  2. `sim-portfolio/scripts/fast_pry_today.py`（`build_premarket_cache`, L100-L119）：同样查 `sh000300`，判断 `q_dt > max_p_date and q_hhmm >= 1500`（L106）及 `len(patch_rows) >= 2000`（L116）。
  3. `sim-portfolio/scripts/fast_2to3_today.py`（`_check_tencent_close_date` L154-L165、`build_premarket_cache` L470-L495、`assert_data_as_of_date` L895-L902）：完整实现了 `sh000300` 检测、`>=2000` 门禁、`data_as_of_date` 写入（L870）及在 `--premarket`（L1017）和 `run_live`（L929）强制断言阻断。
- **源码出入与缺口**：
  1. **手册遗漏 `fast_2to3_today.py`**，它是目前全仓唯一在盘前/盘中均严格执行 `data_as_of_date == 最新收盘日` 断言的实时脚本。
  2. **`fast_high_dragon_today.py` 未按手册规范实现**（`build_premarket_cache`, L299-L339）：未请求 `sh000300` 校验交易日历，仅用本机时间 `now.weekday() < 5` 且过 `15:05`（L302）及 `max_p_date < today_str`（L303）触发补齐（若遇工作日节假日休市会把上一交易日快照误标为 `today_str`）；无 `>= 2000` 条数下限（L336 仅 `if rows_today:`）；无 `data_as_of_date` 字段（用 `as_of_d1`，L952）与硬断言。
  3. **`fast_1to2_today.py` 未按手册规范实现**（`_patch_today_daily_if_needed`, L170-L235）：同样未查 `sh000300`，只判本机 `15:05` 与 `max_d == today_str`（L173-L181）；无 `>= 2000` 条数下限（L227 仅 `if not today_rows:`）；且无 `data_as_of_date` 字段与硬断言（用 `d1_date`，L1102）。
  4. **主报告与多数脚本缺失 `data_as_of_date` 硬断言**：`daily_3strategies_score_report.py`（L62-L68）仅断言 `1to2/3to4/pry/2to3` 四个缓存日期相等，既**未校验 `high_dragon_premarket_cache.json`（`as_of_d1`）**，也**未校验是否等于真实最新收盘交易日**；`live_3to4_cache_builder.py` / `live_3to4_intraday.py` / `fast_3to4_today.py` / `fast_pry_today.py` 与 `clean_rebacktest_20261116`（`partA/partB/partC`）均无 `data_as_of_date` 硬断言（仅 `bt_2to3_v10_clean_master.py` L79-L82 有硬编码 `DATA_AS_OF_EXPECTED = "2026-11-16"` 断言）。

---

### 补丁 2：一字跌停闷杀顺延至真实开板日补丁（手册 L198）
- **手册声称**：现行全部回测引擎严格执行顺延循环，卖日处于一字跌停（`open <= dt_px + 0.01` 且 `high <= dt_px + 0.01`）则强制顺延至首个撬开跌停的真实交易日按开盘价或收盘价计损。
- **源码一致项**：
  1. `sim-portfolio/backtests_astock2/core_3to4_5m_engine.py`（`sim_exit_5m` L208-L216, L263-L270）：通过 `while k < n and bool(cb["is_yizi_dt"][k]): k += 1` 顺延，开板日按开盘价卖出（L216, L270）。
  2. `sim-portfolio/backtests_astock/clean_rebacktest_20261116/partB_1to2/run_rebacktest_v18_clean.py`（`make_clean_trade_engine` L760-L771, L783-L784）：跳过 `is_yizi_dt`（`b[7]`），在首个非一字跌停日按开盘价斩仓（L764）。
  3. `sim-portfolio/backtests_astock2/p5_full_pry_universe/_archive/20261116_stage12_sweeps/precompute_return_matrix.py`（`first_sellable_day`, L14-L20）与 `s2_custom_exits_eval.py`（L53-L58）：通过 `while p < L - 1 and d["is_yizi_dt"][p]: p += 1` 顺延（其中 `L15` 注释写判定容差为 `high <= dt_px + 0.005`，与手册写的 `+ 0.01` 有微小数值差异）。
- **源码出入项**：
  1. `sim-portfolio/backtests_astock/clean_rebacktest_20261116/partA_high_3to4/build_partA_rebacktest.py`（L207-L262）：高标首阴 `V5.1` 复跑直接消费历史台账 `v5_morn_42_ledger.csv`（L186）中的 `r.exit_date` 并按该日收盘/开盘/5m 价卖出（L237-L260），脚本自身**未做** `is_yizi_dt` 校验或顺延循环。

---

### 补丁 3：`T+1` 同日尾盘卖早盘买时序穿越补丁（手册 L199-L205）
- **手册声称**：现行单仓与双半仓引擎全部升级为分钟级物理交割锁 `buy_date > free_dt or (buy_date == free_dt and buy_hhmm > free_hhmm)`，并在 `synthesize_master_clean_20261116.py` 与 `bt_2to3_v10_clean_master.py` 中使用展示代码及 `assert (out["exit_date"] > out["buy_date"]).all()`。
- **源码一致项**：
  1. `bt_2to3_v10_clean_master.py`（`sim_single_slot` L173, L200；`sim_two_half_slots` L246）：与手册代码框完全一致，单仓第 173 行使用 `(not free_dt) or (bd > free_dt) or (bd == free_dt and 925 > free_hh)`，第 200 行含完全一致的 `assert (out["exit_date"] > out["buy_date"]).all(), "T+0 violation detected!"`。
  2. `core_3to4_5m_engine.py`（`_sim_single_slot_chrono` L299、`_sim_two_half_slots_chrono` L329）：均已升级分钟级物理锁。
  3. `synthesize_master_clean_20261116.py`（`run_1slot`, L68）：实现分钟级锁，但变量名为 `cur_exit_dt`/`cur_exit_hhmm`，且未直接 `assert`，而是以指标 `t0_violations`、`overlap_violations` 统计导出（L169-L175）。
- **源码重大出入项**：
  1. `sim-portfolio/backtests_astock/clean_rebacktest_20261116/partC_aux/run_partC_aux_clean_rebacktest.py`（`calc_single_slot`, L35-L51）：虽在 `run_pry_v10()` 中生成了 `buy_hhmm` 与 `exit_hhmm`（L169-L176），但 `calc_single_slot` 在 L44 **仍使用粗放日级锁 `if free_after == "" or bd > free_after:`**（同日 `09:30/09:35` 卖出后亦不允许同日买，与分钟锁不一致；且 `run_5board`/`run_ref_4to5_fixed` 并无 `exit_hhmm` 字段）。
  2. `s3_champion_scorecard.py`（`simulate_slot_trades`, L90）：仍使用粗放日级锁 `slot_free[i] < bd`。

---

### 补丁 4：超跌撬板严禁盘中撤单博涨停补丁（手册 L207）
- **手册声称**：定版 `V1.0` 每日盘前按前 10 日跌幅绝对值 `0.45` 倍（限幅 `6.0%` 至 `16.0%`）预埋限价单，触及即成交，严禁盘中撤单。
- **源码一致项**：
  1. `fast_pry_today.py`（`build_premarket_cache` L235, L241；`main` L287）：实盘打分与止盈价严格锁定 `dyn_tp_pct = np.clip(0.45 * abs(ret10), 0.06, 0.16) * 100`，`tp_px = round(q["open"] * (1.0 + c["dyn_tp_pct"] / 100.0), 2)`，无撤单逻辑。
  2. `run_partC_aux_clean_rebacktest.py`（L132, L139-L165）：读取严校后人工逐笔核验的 `v1_oversold_pry_165_strict_ledger.csv`，对应 `backtests_shared_ledger.md` L16（`RD009`「严校剔除盘中撤单微瑕」）。
- **历史代码遗留提示**：`p5_full_pry_universe/_archive/20261116_stage12_sweeps/precompute_return_matrix.py`（L71-L86）与 `s3_champion_scorecard.py`（L170-L172）的 `X10` 仍保留了旧版「若当日涨停则 `hold_zt_relay` 撤单博连板」以及早期的 `0.08/0.05` 两档止盈代码，该文件已移入 `_archive`，未再被现役实盘调用。

---

### 补丁 5：股东锁仓百分制与超跌 `bias10` 符号统一补丁（手册 L208）
- **核查结果：完全一致**。
  1. 历史事故源码实证：`sim-portfolio/backtests_astock2/_archive/20261116/old_phase1_phase2_supersede/p2_2to3/screen_36_factors.py` L106-L107 确实曾误写 `pool["lock_top10"] >= 0.45` 与 `>= 0.50`。
  2. 现行全部源码：`live_3to4_cache_builder.py`（L266, L302-L303）、`fast_high_dragon_today.py`（L794, L807-L808）、`fast_pry_today.py`（L230, L234, L238）、`fast_2to3_today.py`（L821-L822）、`bt_2to3_v10_clean_master.py`（L144）、`run_partC_aux_clean_rebacktest.py`（L219, L300-L304）均 100% 统一 `lock_top10` 为 `0` 至 `100` 百分制，并按 `1.0 - lock / 100.0` 扣减计算自由流通市值。
  3. `bias10` 符号与排序：`fast_pry_today.py`（L210, L244, L289）与 `run_partC_aux_clean_rebacktest.py`（L133）均按 `close / ma10 - 1.0` 计算（负值代表跌破均线），并按升序（最负优先）排序。

---

### 补丁 6：刷题机三源日线回退与六道 K 线几何门禁补丁（手册 L209）
- **核查对象**：`sim-portfolio/backtests_astock2/live_daily_question_builder.py`
- **源码一致项**：`assemble_live_case_dict`（L897-L900）在调用 `validate_single_kline` 不通过时确实直接 `raise RuntimeError("K-line gate blocked output: ...")` 阻断生成残缺 HTML。
- **源码重大出入项（3 处）**：
  1. **三源回退顺序与数据源名称不符**：手册称顺序为「`kline_cache.db` → 本地 `a_daily` → `fqkline` 实时接口」；而源码 `load_static_enrichment`（L408-L465）真实顺序是 **腾讯 `fqkline`（`fetch_tencent_daily_klines`, L414）→ 新浪日线（`fetch_sina_daily_klines`, L417）→（不足 `d1_date` 补腾讯实时快照 `fetch_tencent_rt_d1_bar`, L422）→ 本地 `a_daily.parquet`（L441-L465）**。全文件**完全没有读取 `kline_cache.db`**！
  2. **成交量单位换算表述误读**：手册称「强制统一上海与深圳手股成交量换算单位」；实际源码中变量名 `is_sh_unit`（L415, L425, L433）的 `sh` 指的是**腾讯日线接口返回单位为「手」（需 `* 100.0` 转为股）**，与新浪/Parquet/实时快照的「股」统一，与沪深交易所无关。
  3. **K 线门禁实为 5 项而非 6 项**：`validate_single_kline`（L152-L171）虽在 docstring 写「六维数学硬门禁」，但实际代码仅校验了 **5 项**：① 根数 `>= 5`（L154）；② 单根长度 `>= 5`（L158）；③ OHLC 正值与高低包络几何合法性（L161）；④ 非假平线 `max(highs) <= min(lows)`（L165）；⑤ 末根收盘与 D1 昨收偏差 `<= 1.8%`（L169）。解包了 `v = float(b[4])`（L160）却**从未对 `v` 做非零校验**，少 1 项检查。

---

### 补丁 7：下单门禁 `T0` 硬断开、同票互斥与白名单补丁（手册 L210）
- **核查对象**：`sim-portfolio/scripts/execute_trade.py`（及 `portfolio_io.py`）
- **源码一致项**：
  1. 在 `validate_buy`（L667-L686）与 `_astock_pre_buy_gate`（L1469-L1481）中，明确阻断 `s_fund` 与 `s_4to5` 及白名单外 `strategy_id`；
  2. `_next_trade_id`（L140-L149）已从 `max(len(trade_log), max_id) + 1` 取值，避免删单后单号回退撞号。
- **源码重大出入项（4 处）**：
  1. **开仓白名单数量不符**：手册 L210 写 `{"s_high", "s_3to4", "s_1to2", "s_pry"}`（4 个）；源码 `execute_trade.py` L95 真实集合为 **`{"s_high", "s_3to4", "s_1to2", "s_pry", "s_2to3"}`（5 个，含 `s_2to3`）**。
  2. **`T0` 用户本轮授权硬门禁在代码内缺失**：`execute_trade.py` 全文**不存在**检查用户本轮指令授权的参数或代码拦截门；`T0` 仅靠规则文件 `AGENTS.md` 约束，未写入脚本硬门禁（此外 L967 报错提示的 `--force-t0` 也未在 `build_parser()` L3143-L3239 注册）。
  3. **同票跨策略互斥与卖出归属锁存在空值绕过漏洞**：
     - 买入互斥（`validate_buy` L673-L679）：仅当已有持仓 `exist_sid` 非空**且**本次传入 `--strategy-id` 时才拦截（L675）；若旧仓无 `strategy_id` 或本次不传 `--strategy-id`（走 SABCT 或 `--book b`），仍可对同票加仓串仓。
     - 卖出归属锁（`validate_sell` L932-L938）：仅在 `strategy_id` 参数非空且 `pos_sid` 非空时校验相等（L934）；**不传 `--strategy-id` 即可绕过归属锁直接卖出任何策略持仓**。
  4. **双写状态且未触发文件排他锁**：`execute_trade.py` L156-L180 仍使用本地 `load_portfolio()` 与 `save_portfolio_atomic(state)` 直接读写 `portfolio_state.json`（L3323, L3376），**未调用 `portfolio_io.load_portfolio()` 挂载 `fcntl.flock` 排他锁**，写盘后再于 L3416-L3418 调 `portfolio_io.save_portfolio(state_fresh, ...)` 二次覆盖同步，并非「只准通过 `portfolio_io.save_portfolio` 写入」，并发场景下依然存在竞态写覆盖风险。

---

## 二、`backtests_shared_ledger.md` 核对附记
- `RD007`（L14）：与补丁 2、3、5 历史溯源完全一致。
- `RD008` / `ST007`（L15, L33）与 `RD009` / `ST008`（L16, L34）：台账中保留了 11-14/11-15 历史状态（`ST007` 写“移交PM”、`ST008` 写“第4顺位”），而 `ST009`（L35）及现役代码 `execute_trade.py` L94 已将 `s_4to5` 下放 `astock2` 不上实盘，撬板升为第 3 顺位、`s_2to3` 为第 5 顺位。
- `DF021`（L61）：记录早期撬板证伪及阶段性 `1.5%` 条件单/`+7%` 3天规则（最终 `ST008` 演进定版为次日 `09:25` 弱转强 `E8` + `X10`）。
- `DF022`（L62）：记录 20cm 跌停撬板 `kline_cache` 交叉除脏（仅 6 笔胜率 16.7%）及宽口径撬板因 `T+1` 占用早盘资金（分钟级锁）挤掉高标首阴而被证伪淘汰。

# A股五大实盘策略生产代码与规则一致性红队全量审计报告（2026年11月23日）

结论先行：现役五大实盘策略的整数打分卡与核心门槛（`90/102`、`88`、`165/175`、`90/96`、`304.8/329.8`）与研发回测真源及 [strategy_astock.md](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/strategy_astock.md) 保持高度一致（`s_2to3` 与 `s_3to4` 各 `1500` 组边界网格重放均 `0` 误差），`cninfo_notices_5y_pit.db` 中 `23868` 条延后 `avail` 记录经核实系春节/五一/国庆长假顺延，并非日期漏洞；但生产代码、统管协调器、缓存构建时序与下单锁之间存在 **5 类 P0 致命错误、5 类 P1 实质口径漂移与 4 类 P2 工程瑕疵**，其中 `fast_26q4_special_today.py` 彻底漏掉 `s_pry`、`daily_3strategies_score_report.py` 篡改五顺位裁决、THS `open_num=null` 被写死成 `0` 误杀 `盛剑科技`、`fast_2to3`/`fast_high_dragon` 缺 `q_dt` 校验与 `execute_trade.py` 纯单仓/隔离绕过漏洞需最高优先级修复。

---

## 一、P0 致命错误（直接影响选股、顺位裁决、实盘开平仓安全）

### 1. 统管脚本 `fast_26q4_special_today.py` 彻底遗漏第 3 顺位 `s_pry`
* **证据**：[fast_26q4_special_today.py:24-28](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_26q4_special_today.py#L24-L28)、[364-374](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_26q4_special_today.py#L364-L374)、[386](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_26q4_special_today.py#L386)、[394](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_26q4_special_today.py#L394)。
* **事实**：头文件与主面板标题（`386` 行）均写明 `三进四V4.1＞高标V5.1＞超跌撬板V2.1＞二进三V2.1＞一进二V19`，但全脚本未读取 `pry_premarket_cache.json`，也未评估 `s_pry`，空仓兜底列表也仅列四大主战。若当日仅 `s_pry` 过线，专供裁决将漏单并错误买向低顺位或宣告全线空仓。

### 2. `daily_3strategies_score_report.py` 篡改 `s_pry` 全局第 3 顺位铁律
* **证据**：[daily_3strategies_score_report.py:319-332](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/daily_3strategies_score_report.py#L319-L332) vs [strategy_astock.md:15,22,40](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/strategy_astock.md#L15-L40)。
* **事实**：总纲死律规定 `s_pry` 满 `165` 分即稳居全局第 3 顺位，排在 `s_2to3` 与 `s_1to2` 之前，仅低顺位当季把握度 `rk_prio` 领先 `>= 1.50` 才可越级。但 `daily_3strategies_score_report.py:319` 硬编码仅当 `s_pry >= 175` 或同时满足 `(not p_23_96) and ((not p_12) or p_12[0]["tot_v18"] < 355.0)` 才排在第 3，否则在第 `330` 行被压到 `p_23_90` 与 `p_12` 之后；且 `seasonal_rolling_sr_state.json` 根本没有 `超跌撬板` 条目。

### 3. `s_3to4` THS `open_num=null` 被静默写为 `0`，触发 `三板未开板死封` 误杀（实证命中 `盛剑科技`）
* **证据**：[rd_incremental_sources.py:139](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/rd_incremental_sources.py#L139)、[live_3to4_v40_engine.py:598-600, 739-741, 108](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/live_3to4_v40_engine.py#L739-L741)、[audit_parity_verify_result.json:290-573](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/redteam_full_audit_20261123/partB1_code_parity_audit/audit_parity_verify_result.json#L290-L573)。
* **实证**：`2026-11-11` 至 `2026-11-20` 同花顺涨停池每日 `45%` 至 `61%` 个股 `"open_num": null`（`11-19` `12/23` 只为 `null`、`11-20` `17/28` 只为 `null`）。`603324 盛剑科技` 在 `2026-11-19` 三连板日线 `open=22.72 < close=25.19`、换手 `7.04%`、首次封板 `09:37:40`，属典型换手板，但 THS JSON `open_num` 为 `null`，经 `rd_incremental_sources.py:139` 与 `live_3to4_v40_engine.py:739` 的 `int(... or 0)` 全部写死为 `0`（`zt_micro_tape` 全库 `NULL` 计数为 `0`，`0` 计数高达 `52948` 行），次日触发 `open_board_count < 1` 假否决。

### 4. `fast_2to3_today.py`、`fast_high_dragon_today.py`、`live_3to4_v40_engine.py` 缺失 `q_dt` 实盘校验或伪造开盘价
* **证据**：
  * [fast_2to3_today.py:162, 1148-1167](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_2to3_today.py#L1148-L1167)：`run_live` 忽略 `q["q_dt"]`，盘前抓到昨日报价直接当今日竞价算分，若无报价则在 `line 1165` 直接伪造 `op_pct=0.0, buyable=True`（与两大统管脚本校验 `q_dt > d23_str` 完全相反）。
  * [fast_high_dragon_today.py:133-157, 1074-1085](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_high_dragon_today.py#L1074-L1085)：`fetch_tencent_batch` 根本未解析腾讯 `f[30]`（`q_dt`），盘前调用直接把昨日 D1 报价当 D2 竞价；且 `lines 945-949` 用系统当前时间 `now + 1` 推导 `next_trade_date`，导致 `2026-11-23 09:12` 生成的 `high_dragon_premarket_cache.json` 把 `next_trade_date` 错写成 `2026-11-24`（真实 `as_of_d1=2026-11-20`，交易日应为 `2026-11-23`）。
  * [live_3to4_v40_engine.py:938-947, 977-988](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/live_3to4_v40_engine.py#L938-L988)：非开盘期/缺报价时默认代入 `+5.5%` 开盘与 `+1.5%/+1.0%` 同板块涨幅并输出达标结果，与统管脚本的 `-999` 拦截口径冲突。

### 5. `execute_trade.py` 物理隔离锁存在三大绕过路径且 A股保留 `yfinance` 违规兜底
* **证据**：[execute_trade.py:45, 95, 283-303, 661-686, 932, 1416, 1469-1481](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/execute_trade.py#L661-L686)。
* **事实**：`CN_VALID_BUY_STRATEGY_IDS` 精确为 `{"s_high","s_3to4","s_1to2","s_pry","s_2to3"}`（`line 95`），且显式传入 `s_fund`/`s_4to5` 会被拦（`lines 668, 1470`）。但存在四处高危缺口：
  1. **漏传 `--strategy-id` 整锁失效**：`sell` 路径 `if account_key == CN_ACCOUNT_KEY and strategy_id:`（`line 932`）若不传 `--strategy-id`，直接绕过卖出归属核验；`buy` 路径（`lines 667, 1469`）若不传则绕过白名单与同票跨策略互斥，且仅当既有持仓 `exist_sid` 非空时才拦截混买（`line 675`）。
  2. **`--book b` 直接短路**：`validate_buy` 第 `661` 行与 `_astock_pre_buy_gate` 第 `1416` 行在遇到 `book == "b"` 时立即跳过全部策略白名单与物理隔离检查。
  3. **完全未执行 `纯单仓` 代码硬拦**：`validate_buy` 第 `686` 行校验通过即 `return`，未校验 `account["positions"]` 是否已持有其他 A股持仓，系统可同时买入多只机械仓。
  4. **A股违规导入并兜底调用 `yfinance`（违反 D12）**：第 `45` 行全局导入 `yfinance`，第 `283-303` 行在腾讯/akshare/push2delay 失败时于 CN 分支调用 `yf.Ticker`（同源隐患见 `exit_signal_detector.py:93-130`）。

---

## 二、P1 实质口径漂移

### 1. `fast_3to4_today.py --hold` 与 `fast_pry_today.py --hold` 盘前错日 Bug，及 `09:25` 涨停家数统计分叉
* **盘前 `target_dt` 错判成昨日**：[fast_pry_today.py:321, 343-385](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_pry_today.py#L321-L385) 与 [fast_3to4_today.py:177-180](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_3to4_today.py#L177-L180) 均用 `q_dt if (q_dt and close/price > 0) else today_str`。在 `09:15` 前开盘前执行时 `q_dt` 为上一交易日（已有昨日收盘价），`target_dt` 被设为昨日，连带把 `d_prev` 退回 `T-2`、`ref_prev_c` 错取 `T-2` 收盘价，且令 `fast_pry` 把 `T+off` 少算 1 天（当日买入错看成 `T+0`）、`[XF16b]` 看错成前前日跌停数。
* **东财公告线上补查未来函数**：[fast_3to4_today.py:268, 307](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_3to4_today.py#L268-L307) 未传 `--buy-date` 时默认回溯 7 天（会混入买前监管函），且东财 API 仅比较日期 `nd[:10] <= win_hi[:10]`，未截断 `< 09:25:00`。
* **`09:25` 涨停家数 `6家 vs 8家` 根因**：`fast_pry_today.py:138` 构建 `main_codes_sample` 共 `3186` 只股，实测混入 `140` 只 `st_universe.json` 成分股；主程序（`line 461`）直接 `sum(is_zt_open)` 不过滤 `st_set` 且不校验 `q_dt == mkt_qdt`（将停牌日前一日竞价涨停股计入）；而 `--hold`（`line 371`）同时过滤 `c_k not in st_set` 与 `q_dt == mkt_qdt`。`daily_3strategies_score_report.py:263-266` 虽校验 `q_dt > dpr_str` 却同样未过滤 `st_set` 且缺报价数不足 `< 4500` 告警。

### 2. 五大脚本 `pre_c` 漏乘复权因子，及 `fast_high_dragon_today.py` 多项回测口径偏差
* **全系 `pre_c` 未复权**：[live_3to4_v40_engine.py:533](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/live_3to4_v40_engine.py#L533)、[fast_high_dragon_today.py:348](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_high_dragon_today.py#L348)、[fast_pry_today.py:131](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_pry_today.py#L131)、[fast_2to3_today.py:650](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_2to3_today.py#L650)、[fast_1to2_today.py:298](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_1to2_today.py#L298) 在计算 `pre_c` 时均未像回测 `upgrade_3to4_pit.py:515` 乘以 `adjf.shift(1)/adjf`（近 `40` 日内 `000338`、`000513`、`000582` 等 `15+` 只股均有 `>0.5%` 除权跳变）。
* **`fast_high_dragon_today.py` 细节漂移**：`lines 227-238` 双异动 `calc_double_dev_for_stock` 未剥离 `day == today` 当日 K 线（对比 `astock_intraday_check.py:314-317`，10:02 实测 Sina 尚未输出当日棒，但收盘入库后即错位 1 天）；`line 88` `Q_RE` 漏掉 `国泰海通` 仅写 `国泰君安.*总部`（`live_3to4:70` 与 `fast_1to2:109` 仍写 `国泰君安.*宜昌`）；`lines 581,591` 用 `.min()` 混聚龙虎榜 1/3 日表且未过滤分类账户名；`line 296` 未过滤 ST；`line 609` 读 `1to2_premarket_cache` 不校验 `d1_date == d1_date`；`line 639` `s_reg_hit` 接受未来 5 天内（`-5 <= days <= 10`）；`line 792` 缺 `HOLDERS_FREE` 补充。

### 3. `s_3to4` / `s_pry` / `s_1to2` 生产与回测局部口径偏差
* **`s_3to4`**：回测 `upgrade_3to4_pit.py:826` 的 `has_ex_reg` 为交易所 `6` 交易日内 `>= 1` 只监管（合并 `part1` 与 `PQ_REG_TOX`/`ZDJK`），而生产 `live_3to4_v40_engine.py:608,627,776` 卡 `5` 交易日 `>= 2` 只且仅查公告双库；`cut_reg` 用 `15` 自然日且卡 `<= d3_date 23:59:59` 漏 `d3` 晚至 `buy_date 09:25` 公告；`live_3to4_v40_engine.py:451` 与 `fast_3to4_today.py:218` Elo 兜底未过滤 `NON_THEME` 且仅传 `120/60` 天日线；`fast_3to4_today.py:72-76` `RE_DAY_SURF_V41` 比 `step1_build_exit_pit_db.py:43-45` 多出 3 席位，且 `_query_lhb_prev`（`lines 127-142`）将 `lhb_buy` 与 `lhb_sell` 同 `TRADE_ID` 同席位合并加总导致金额双倍计数。
* **`s_pry`**：[fast_pry_today.py:207, 253](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_pry_today.py#L207-L253) 按 `机构净买 > 0` 加 `10` 分（对齐 `strategy_astock.md:96`），但回测 `expB:1207` 与 `build_full_36k_pry_master.py:40` 实为总买入 `inst_buy_prev > 0`；且生产代码 `178-200` 未对龙虎榜 `TRADE_ID` 去重（会重复叠加 3 日榜）。
* **`s_1to2`**：[fast_1to2_today.py:114-146](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_1to2_today.py#L114-L146) 已优先读 PIT `csrc_industry_pit_clean.csv`（仅缺号/未到 `start_date` 回退静态 `csrc_industry_l2.csv`），且 `close<=60`、`18<=mcap<=220` 与回测对齐；但生产构建题材仅算 `TECH_PAT_TIMELESS`（`line 609`）而非回测 `TECH_PAT_ORIG`（`upgrade_1to2_pit.py:439`）；`check_live:1720` 漏 `(~tot_v18) &` 使主轨股偶尔被标 `fb_dom295=True`（`evaluate_1to2_v19_df:1994` 已修）；`nuclear_halt`（`1572,1876`）在盘前 `--mock-open` 只模拟单只负开盘时误触发全天熔断；`M1` 卖点不在本脚本内，需人工在 `astock_intraday_check.py:100-110` 传 `--xq-cnt` 与 `--d2-seal-ratio`。另确认 `upgrade_1to2_pit.py:989` 自身把 `fb_dom295` 优先级错写成 `+500`，生产 `fast_1to2_today.py:1730` 已正确修正为 `-500`。

### 4. 统管引擎 `seasonal_rolling_sr_state.json` 僵尸化与 `--mock-open` 局部失真
* [seasonal_rolling_sr_state.json:2-34](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/seasonal_rolling_sr_state.json#L2-L34) 冻结在 `2026-11-16`，全仓无任何脚本或 `LaunchAgent` 刷新它，缺 `超跌撬板`，且键名滞留在 `三进四_V34`/`一进二_V18`。
* [fast_26q4_special_today.py](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/fast_26q4_special_today.py) 缺 `--strict` 缓存日对齐断言；其 `lines 180-181` 把 `9.5%~9.8%` 非一字首板直接判作一字（实测 `000111 +9.6%` 扣 7 分）；`lines 355-360` `--mock-open` 未重置 `is_yizi`/`zt_px`（实测 `TEST_HD` 被旧 `is_yizi=True` 误杀）；`daily_3strategies_score_report.py:132` 与 `fast_26q4:356` `--mock-open` 优先拿盘中 `cur/price` 当 `pre_ref`；`daily_3strategies:195`/`fast_26q4:160` 用 `px*1.095` 判 `top1_c` 买与 `live_3to4:944`（`<0.098 and not yizi`）漂移。

### 5. 数据与定时链路静默雷
* **IR 双库分叉**：`data/cninfo_ir_qa_5y_pit.db` 停留在 `2026-11-16`（`42149` 行），仅 `backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db` 随 [rd_master_trading_data_sync.py:77](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/rd_master_trading_data_sync.py#L77) 同步至 `2026-11-20`（`42174` 行），`f1_3to4/step1:298` 仍读旧库。
* **雪球/社区同步时序倒挂**：`xueqiu_guba_5y_pit.db` 已停更（`xq 11-13` / `guba 11-12`），`rd_master_trading_data_sync.py` 在 `lines 140-147` 先生成 `2to3_premarket_cache.json`（`fast_2to3_today.py:553-567` 不叠加 `astock_community.json`），直到 `line 189` 才调 `sync_community_live_to_pit.py` 写入 `astock_community_5y_pit.db`，致 `2to3` 漏掉最近一轮增量雪球帖。另查 `astock_community.json` `max_time="2026-11-23 12:44"` 含超当前时间脏数据（`sync_community_live_to_pit.py:57` 会钳位，直接读 JSON 时依靠 `< buy_date 09:25:00` 过滤）。
* **ST 快照过期**：[st_universe.json:1-9](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/st_universe.json#L1-L9) 停在 `2026-09-16`（`323` 只），实盘腾讯 `00/60` 活跃 `140` 只 ST 中已漏 `000972 *ST中基` 与 `600363 ST联光` 共 `2` 只。

---

## 三、P2 轻微工程瑕疵

1. **`--help` 命令行崩溃**：`fast_2to3_today.py:1243`（`+9.2%/+8.5%/+6.5%`）与 `fast_3to4_today.py:374`（`+8.5%/+7.0%/+5.0%`）在 `argparse` `help` 字符串未转义 `%`，实测执行 `--help` 均以 `returncode=1`、`ValueError: unsupported format character '/'` 崩溃。
2. **13:45 护利缺少时钟校验**：`fast_2to3_today.py:1226` 与 `astock_intraday_check.py:115` 对 `high >= +8.5% 且 now <= +6.5%` 未卡时间 `>= 13:45`，早盘冲高回落也会打印触发告警。
3. **其余边界微瑕**：`fast_1to2_today.py:1567` 缺失 `op > 0` 守卫（`1871` 行已有）；`risk_monitor.py:268` 与 `uass_scoring.py:310` 保留未使用旧 `yfinance` 函数；`execute_trade.py:93` 注释仍写旧版本 `二进三 V1.0 第5顺位`。

---

## 四、已确认完全一致项（含澄清结论）

1. **核心打分与硬门重放 100% 一致**：
   * `s_2to3`：`evaluate_2to3_candidate` vs `upgrade_2to3_pit.compute_v20_components` `1500` 组边界矩阵重放 `mismatches=0, max_abs_diff=0`；
   * `s_3to4`：`score_single_3to4_v40_row` vs `upgrade_3to4_pit:909-955` `1500` 组边界矩阵 `mismatches=0`，且 `fast_3to4_today.py:244-342` 7 因子名称、数值阈值（`135`、`2000万`、`3.5x`、`-2%/-2.5%`、`<20%`）均对齐 `f1_3to4/exit_factor_engine.py:293-483`；
   * `s_high`：22 因子、`88` 分线、买点及 `93%` 双异动与 `expB:663-805` 及总纲完全一致；
   * `s_1to2`：`304.8/329.8`、`close<=60`、`18<=mcap<=220`、`d1_tightness>=37.0`、`fb_dom295` 过线掩码与 `upgrade_1to2_pit.py` 一致；
   * `s_pry`：V2.1 四步动态阶梯卖点（`09:25 < 5家`、`T+1 -1.5%` 与 `CLV >= 0.70` 豁免、`+3%/+3%` 封顶 `+18%`、`T+2..T+4`）对齐 `backtest_30_factors.py` 与总纲。
2. **`cninfo_notices_5y_pit.db` `trade_date_avail` 跨度正常**：实测 `1,018,543` 行中 `23,868` 条 `avail > pub + 5d` 全部分布于 `01/02/04/09` 月（`6` 至 `11` 天长假顺延），`gt12d=0`、`avail < pub = 0`。
3. **现役选股与算分主链零 `yfinance` 导入**：五大 `fast_*_today.py`、`live_3to4_v40_engine.py`、`daily_3strategies_score_report.py`、`fast_26q4_special_today.py`、`astock_intraday_check.py` 均无 `yfinance` 导入；`execute_trade.py:95,1187` 白名单与 A 股 T15 短路正确生效。

---

## 附件清单（纯只读落盘）
* 验证脚本：[audit_parity_verify.py](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/redteam_full_audit_20261123/partB1_code_parity_audit/audit_parity_verify.py)
* 实测数据：[audit_parity_verify_result.json](file:///Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/redteam_full_audit_20261123/partB1_code_parity_audit/audit_parity_verify_result.json)

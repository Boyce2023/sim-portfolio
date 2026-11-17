# 第08号独立历史一致性审查报告（第七阶段第1节与第2节）

- **审查对象**：`sim-portfolio/prompts/astock_full_lifecycle_sop_handbook.md` 第七阶段第1节与第2节（第293至339行）
- **核对真源**：`~/Library/LaunchAgents/com.{claude,buwen}.*.plist`、`launchctl list`、`sim-portfolio/scripts/rd_master_trading_data_sync.py`、`sim-portfolio/data/rd_data_health_status.json`、`sim-portfolio/data/*premarket_cache.json`、`sim-portfolio/scripts/quant_4bucket_engine.py`、`sim-portfolio/prompts/astock_pm_rd_charter.md`、`sim-portfolio/strategy_astock.md`、`docs/90_内部_给Claude读/all_hands_20261116/FINAL_CHARTER_20261116.md`
- **总结论**：`com.claude.strategy1-exit.plist` 已彻底卸载移除，18 个在跑定时 plist 时点与主路径基本对齐，`rd_master_trading_data_sync.py` 已接入 `2to3_premarket_cache.json`（5 个实盘必建 + 1 个研发可选共 6 个缓存）；但查出 **4 类实质偏差**：① `com.claude.open-check.plist`（`09:26`）空转调用已退役的 `quant_4bucket_engine.py open`；② `15:08` 日终对账 `quant_4bucket_engine.py reconcile` 因 `FOUR_BUCKET_RETIRED=True` 已跳过零漏单核验却仍报「账实核对零误差」；③ 4 份脚本/plist 未按「统一锁死 `python3.13`」执行；④ 手册 7.2《`09:26` 同花顺交割挂单卡》与 `astock_pm_rd_charter.md` 在「高标绿开归类」「`今开*1.015` 适用范围」「遗漏 `s_2to3` 二进三」「撬板 0.45 倍限价误放突破单句末」四处未对齐。

---

## 一、macOS LaunchAgents 定时任务时间表与 `strategy1-exit` 卸载核验

### 1.1 `com.claude.strategy1-exit.plist` 卸载与归档核验（完全一致）
1. `ls -la ~/Library/LaunchAgents/*strategy1*` 返回无匹配文件，该 plist 已从 `LaunchAgents` 物理移除。
2. `launchctl list | grep strategy1` 返回空，确认已彻底卸载未驻留。
3. 原脚本 `strategy1_exit.py` 已移入 `sim-portfolio/scripts/_archive/20261116_legacy_astock/strategy1_exit.py`（仅 `scripts/__pycache__/strategy1_exit.cpython-313.pyc` 残留编译缓存），符合 `FINAL_CHARTER_20261116.md` 决议。

### 1.2 手册 7.1 现役 18 个 plist 逐一核对表

| plist 名称 | 手册 7.1 标注时间与脚本 | plist 实测 `StartCalendarInterval` 与 `ProgramArguments` | 核对结论 |
|---|---|---|---|
| `com.claude.astock-brief.plist` | `07:15` `daily_brief_gen.py (含行业财报全景)` | `Hour=7, Minute=15`（`RunAtLoad=True`）；`/opt/homebrew/bin/python3.13 .../scripts/daily_brief_gen.py`（内调 `industry_earnings_brief`） | 一致 |
| `com.claude.sim-portfolio.plist` | `08:00` `daily_run.sh` | `Hour=8, Minute=0`；`/bin/bash .../scripts/daily_run.sh` | 时点与入口一致；脚本内含裸 `python3` 与 `uv`（见偏差 1.3.2） |
| `com.buwen.verdict.nag.plist` | `08:40` `verdict_nag.sh` | `Hour=8, Minute=40`；`.../scripts/verdict_nag.sh` | 时点与入口一致；脚本内硬编码 `/opt/homebrew/bin/python3`（见偏差 1.3.2） |
| `com.claude.1to2-premarket-sync.plist` | `08:45/09:08/15:35/16:35/18:25/21:30` `rd_master_trading_data_sync.py` | `08:45`, `09:08`, `15:35`, `16:35`, `18:25`, `21:30`；`/opt/homebrew/bin/python3.13 .../scripts/rd_master_trading_data_sync.py` | 完全一致 |
| `com.claude.1to2-live-question.plist` | `08:52/09:25/16:42 与每小时:05` `live_daily_question_builder.py / ths_watchlist_sync.py` | `Minute=5`, `16:42`, `08:52`, `09:25`；`09:25` 跑 `live_daily_question_builder.py --auction-scheduled`（内部精确等待 `09:25:03.2` 与 `09:25:07.5`），`:05` 跑 `ths_watchlist_sync.py --hourly`，`08:52/16:42` 跑 `--premarket`，全用 `python3.13` | 代码块完全一致；汇总表漏列 `16:42`（见偏差 1.3.4） |
| `com.buwen.auction.collect.plist` | `09:14 (工作日)` `auction_daily.sh` | `Weekday=1..5, Hour=9, Minute=14`；`.../scripts/auction_daily.sh` | 时点与入口一致；脚本内硬编码 `/opt/homebrew/bin/python3`（见偏差 1.3.2） |
| `com.claude.open-check.plist` | `09:26` `open_check_ping.sh` | `Hour=9, Minute=26`；`/bin/bash .../scripts/open_check_ping.sh` | **存在空转退役偏差**（见偏差 1.3.1） |
| `com.claude.auction-surge.plist` | `09:26/15:05` `auction_surge.py scan / fill` | `Weekday=1..5` 的 `09:26` 与 `15:05`；`H<1200` 跑 `python3.13 scripts/auction_surge.py scan`，否则跑 `fill` | 逻辑一致；手册漏标 `(工作日)`（见偏差 1.3.3） |
| `com.claude.kpl-archive.plist` | `09:45/14:40/15:25` `kpl_archive.py pianlizhi / all` | `09:45`, `14:40`, `15:25`；`H>=1500` 跑 `python3.13 scripts/kpl_archive.py all`，否则跑 `pianlizhi` | 代码块完全一致；汇总表漏列 `15:25`（见偏差 1.3.4） |
| `com.claude.astock-refresh.plist` | `10:00/16:00` `push_all.sh` | `10:00`, `16:00`；`/bin/bash .../scripts/push_all.sh 'auto: A股定时刷新'` | 时点与入口一致；`push_all.sh` 内用 `uv run` |
| `com.claude.oversold-trigger.plist` | `15:05 (工作日)` `oversold_trigger.py` | `Weekday=1..5, Hour=15, Minute=5`；`python3.13 scripts/oversold_trigger.py` | 完全一致 |
| `com.claude.quant-4bucket.plist` | `15:08 (工作日)` `quant_4bucket_engine.py reconcile` | `Weekday=1..5, Hour=15, Minute=8`；`python3.13 scripts/quant_4bucket_engine.py reconcile` | 时点与入口一致；**`reconcile` 实质功能偏差**（见第四节） |
| `com.claude.weekly-scorecard.plist` | `周五 15:10` `strategy_scoreboard.py weekly` | `Weekday=5, Hour=15, Minute=10`；`python3.13 scripts/strategy_scoreboard.py weekly` | 完全一致 |
| `com.claude.tree-tracker.plist` | `周五 15:20` `tree_tracker.py` | `Weekday=5, Hour=15, Minute=20`；`/opt/homebrew/bin/python3.13 .../scripts/tree_tracker.py` | 完全一致 |
| `com.claude.zt-pool.plist` | `15:30` `zt_pool_snapshot.py` | `Hour=15, Minute=30`；`/opt/homebrew/bin/python3.13 .../scripts/zt_pool_snapshot.py` | 完全一致 |
| `com.claude.cn-price-db.plist` | `15:40/18:15` `cn_price_db_update.py` | `15:40`, `18:15`；`/opt/homebrew/bin/python3.13 .../scripts/cn_price_db_update.py` | 完全一致 |
| `com.claude.eod-rebalance.plist` | `16:00` `eod_rebalance_ping.sh` | `Hour=16, Minute=0`；`/bin/bash .../scripts/eod_rebalance_ping.sh`（若 `data/eod_done/YYYYMMDD` 缺失则用 `python3.13` 补跑 `reconcile`） | 完全一致 |
| `com.claude.eod-receipt.plist` | `16:40` `eod_receipt_check.sh` | `Hour=16, Minute=40`；`/bin/bash .../scripts/eod_receipt_check.sh` | 完全一致 |

### 1.3 LaunchAgents 与手册 7.1 偏差明细
1. **`com.claude.open-check.plist`（`09:26`）空转调用已退役函数**：`open_check_ping.sh` 第 4 行调用 `/opt/homebrew/bin/python3.13 scripts/quant_4bucket_engine.py open`，而 `quant_4bucket_engine.py` 第 72 行已设 `FOUR_BUCKET_RETIRED = True`，第 1144 至 1146 行 `cmd_open` 在开头直接打印 `[open] ... 旧四分仓已退役停用，严禁09:26自动开新仓` 后直接 `return`。手册第 307 行仍将此任务列为现役定时真源，未标明「已退役停用待清理」。
2. **「统一锁死 `python3.13`」声明与实际脚本调用不完全一致**：手册第 300 行声称「统一锁死 `python3.13`」，但 4 个 shell 入口内部未锁死 `python3.13`：
   - `verdict_nag.sh`（`com.buwen.verdict.nag.plist` `08:40`）第 10、19 行调用 `/opt/homebrew/bin/python3`；
   - `auction_daily.sh`（`com.buwen.auction.collect.plist` `09:14`）第 76 行定义 `PY="/opt/homebrew/bin/python3"`；
   - `daily_run.sh`（`com.claude.sim-portfolio.plist` `08:00`）第 67、199、208、394、451 行调用裸 `python3`，第 181、223 行调用 `uv run --script`（且第 221 行仍探测已归档的 `astock_regime.py`，第 425 行仍写入已废弃的 `~/.claude/session-inbox/astock.jsonl`）；
   - `push_all.sh`（`com.claude.astock-refresh.plist` `10:00/16:00`）第 122 行调用 `uv run --script scripts/update_prices.py`。
   （注：实测 `/opt/homebrew/bin/python3 --version` 当前为 `Python 3.13.14`，现阶段运行未报错，但存在若 Homebrew 再次升级 `python3` 软链即失效的隐患。）
3. **工作日标记遗漏**：`com.claude.auction-surge.plist`（`09:26` / `15:05`）在 plist 内显式配置了 `Weekday=1..5`，但手册第 308 行未如第 306、311、312 行一样标注 `(工作日)`。
4. **7.1 汇总表（第 321 至 334 行）遗漏与表述不精**：
   - 第 329 行与第 334 行未显式列出 `com.claude.1to2-live-question.plist` 的 `16:42` 触发点及 `com.claude.kpl-archive.plist` 的 `15:25` 触发点；
   - 第 329 行把每小时 `:05` 归在早盘表项中，实际 plist `Minute=5` 为全天 24 小时每小时 `:05` 执行 `ths_watchlist_sync.py --hourly`；
   - 第 334 行写「日线两轮入库」，未体现 `rd_master_trading_data_sync.py` 第 59 行在 `>=15:15` 且 `a_daily` 滞后时也会先调 `cn_price_db_update.py`（15:35 轮次实际具备补拉能力）。

---

## 二、`rd_master_trading_data_sync.py` 增量同步管线核验

### 2.1 一致项
1. **已包含 `2to3_premarket_cache.json`**：`sim-portfolio/scripts/rd_master_trading_data_sync.py` 第 89 至 96 行 `cache_builders` 已写入 `("s6_2to3", [sys.executable, f"{SCRIPTS_DIR}/fast_2to3_today.py", "--build-cache"], f"{DATA_DIR}/2to3_premarket_cache.json")`。
2. **5 个实盘必建缓存全部齐备**：除 `s6_2to3` 外，其余 4 个实盘阻塞缓存为 `1to2_premarket_cache.json`（`s5_1to2`）、`high_dragon_premarket_cache.json`（`s1_high_dragon`）、`3to4_premarket_cache.json`（`s2_3to4`）、`pry_premarket_cache.json`（`s4_pry`），共 **5 个实盘必建缓存**；外加 `s3_4to5`（`4to5_premarket_cache.json`）在代码第 101、113 行标为 `optional_rd=True`（非阻塞研发缓存），列表总计 **6 个**。
3. **日期字段兼容**：实测 `data/2to3_premarket_cache.json`（`2026-11-17 12:23:09` 生成）同时包含 `data_as_of_date: "2026-11-16"` 与 `sig_date: "2026-11-16"`，可被 `rd_master_trading_data_sync.py` 第 109 行 `js.get("as_of_d1") or js.get("sig_date") ...` 正常读取，不会误报滞后。

### 2.2 偏差项
1. **健康状态文件尚未刷新出 `s6_2to3`**：`rd_master_trading_data_sync.py` 修改时间为 `2026-11-17 12:14:03`，但 `sim-portfolio/data/rd_data_health_status.json` 仍停留在 `checked_at: "2026-11-17 09:08:05"`，其 `caches` 对象目前仅含 `s5_1to2`、`s1_high_dragon`、`s2_3to4`、`s3_4to5`、`s4_pry` 共 5 项，尚未包含 `s6_2to3`（需待 `15:35` 定时触发或补跑后才会落盘）。
2. **手册数字措辞歧义**：手册第 324、334 行仅写「五大策略盘前缓存 / 五大盘前缓存」，未说明 `rd_master_trading_data_sync.py` 实际同时构建 5 个实盘缓存与 1 个非阻塞研发缓存（`4to5_premarket_cache.json`），共 6 个 json 文件。

---

## 三、`09:26` 同花顺交割挂单卡规格与 `astock_pm_rd_charter.md` 逐要素比对

逐字对照 `astock_full_lifecycle_sop_handbook.md` 第 336 至 338 行与 `astock_pm_rd_charter.md` 第 19、48 行（及 `strategy_astock.md` 第 55、68、86、97、101 行），发现**未做到一字不差，存在 4 处实质偏差**：

| 要素维度 | `astock_pm_rd_charter.md`（第19行/第48行） | 手册 7.2（第338行） | 偏差定性 |
|---|---|---|---|
| **1. 高标绿开归属** | 第 19 行把「高标绿开填 `今开乘1.015`」写在**《普通限价单》**括号内 | 把「高标绿开」归入**《股价云条件单》**（「一进二常规、三进四、高标绿开」） | **严重归类冲突**：对照 `strategy_astock.md` 第 55 行，高标绿开系 `09:26` 挂 `今开*1.015` 条件单、`11:30` 撤单，属于云条件单；`charter` 第 19 行把高标绿开混入《普通限价单》自身有笔误，手册与 `charter` 未对齐 |
| **2. 《普通限价单》委托价与适用范围** | 第 19 行写「`09:25`直买类按开盘价买入，`09:30` 首笔成交」（仅高标绿开写了 `今开乘1.015`） | 把 `round(今开 * 1.015, 2)` 保护价统一写给所有《普通限价单》直买单（并新增解释「防填涨停价冻结资金少买 `6%` 至 `8%` 仓位」） | **口径扩张未同步**：`charter` 未写全直买统一用 `round(今开 * 1.015, 2)` 保护价，手册未注明该规则与 `charter`「按开盘价买入」的衔接关系 |
| **3. 遗漏第 5 顺位《二进三 V1.0》直买** | 第 19 行含「五大实盘策略（含 `fast_2to3_today.py`）」，第 48 行明确 `二进三 V1.0` 为「`跌6.5%至涨2.5%` `09:25`直买头名（第5顺位）」 | 《普通限价单》括号仅列 3 项：`高标平红开 0.0% 至 4.5%`、`超跌撬板 0.0% 至 5.0%`、`一进二周一高分断层领涨` | **明显漏项**：手册 7.2 遗漏 `s_2to3` 二进三 V1.0（`跌6.5%至涨2.5%` `09:25` 直买） |
| **4. 止盈预埋说明混挂在突破型句末** | 第 19 行中性概括为「同步附带成交后次日卖出预埋价与护利触发价精确元数」 | 在「对于突破型买点（一进二常规、三进四、高标绿开）……」整句末尾写「预先写明成交后次日需要预埋的止盈触发价（高标双异动 93% 缓冲价或**撬板 0.45 倍限价**）与午后护利价格」 | **句法归属错位**：超跌撬板属于直买型《普通限价单》，手册却把「撬板 0.45 倍限价」挂在突破型《股价云条件单》长句末尾 |

此外，在《股价云条件单》填表文字上，二者亦有措辞差异：`charter` 第 19 行使用「股价达到 `XX.XX元`」「点全仓按钮」「每日时段 `09:30至11:30`」「未成交当日收盘删云单」，手册 7.2 使用「向上突破触发价（精确到 `0.01元`）」「数量点全仓」「有效时段锁定 `09:30` 至 `11:30`」「`11:30` 未触发自动失效并于当日收盘手动删除云单」，并非一字不差。

---

## 四、`15:08` 日终对账真实行为核验

- **手册陈述（第 312、333 行）**：`com.claude.quant-4bucket.plist -> 15:08 (工作日) quant_4bucket_engine.py reconcile`，核心动作为「**PM 对账核验零漏单并更新沪深300基准快照**」。
- **代码真实行为（`quant_4bucket_engine.py` 第 72 行、第 1440 至 1532 行）**：
  1. 第 72 行已设 `FOUR_BUCKET_RETIRED = True`；
  2. 第 1461 至 1475 行 `if not FOUR_BUCKET_RETIRED:` 块被整体跳过，导致「四桶现金合计 vs SSOT 现金」「台账持仓 vs SSOT 持仓」「14:57 尾盘扫描记录」三项漏单与一致性校验**完全不再执行**，`anomalies` 列表恒为空；
  3. 脚本目前仅执行 `refresh_ssot_marks`、计算相对 `DAY1_HS300_BASE = 4833.52` 的净超额、写入 `data/eod_done/YYYYMMDD` 与 `YYYYMMDD_close.json`；
  4. 第 1525 至 1529 行仍向飞书推送 `[四分仓·15:08日终对账闭环] 账实核对零误差`（2026-11-16 实测日志：账户净值 `753.03万`，而下面仍打印已退役旧四桶权益合计 `925.27万`，却因 `anomalies=[]` 报「零误差」）。
- **结论**：手册 7.1 第 333 行「核验零漏单」与当前 `quant_4bucket_engine.py reconcile` 实际行为存在名实不符偏差，需在手册中降级说明为「刷新 SSOT 市值、沪深300基准与 `eod_done` 标记（旧四分仓核验已退役跳过）」或重构为针对 `portfolio_state.json` 五大现役策略的真核验脚本。

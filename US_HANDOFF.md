# 美股慢账系统总交接（US_HANDOFF · 2026年11月16日现役唯一真值版）

`美股千万美元账户自2026年11月9日起由Buwen全权接管并永久冻结自动调仓，本文件第1行起即为现役权威状态。`

> 历史归档：2026年6月早期版本（原 §§1 至 5）已按 S15 制度拆入 `sim-portfolio/_archive/20261116_us_legacy_root/US_HANDOFF_20260616_s1_to_s5_archived.md`。

## 一、账户主权、冻结铁律与最新账面锚点

1. **主权移交与操作全停（最高优先级）**：
   - 美股账户初始本金重置为 `$10,000,000.00`，由 Buwen 本人全权接管，永久冻结一切自动与半自动调仓。
   - **唯一合法改仓条件（`T0` 硬锁）**：仅当 Buwen 本轮在对话中明确指定标的代码、买卖数量或比例并下达执行指令时，方可调用 `scripts/execute_trade.py` 代为记账落盘；未经本轮明示严禁触碰持仓。
   - **远端推送禁令**：`/Users/huaichuaibeimeng/claude-projects/nexus-package` 的远端推送已锁死为 `DISABLED_PER_BUWEN_20261109`，严禁触发 Railway 推送。
2. **11 只「星辰大海」定版持仓与账面核对口径**：
   - 唯一真源：`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json`（只读衍生视图 `sim-portfolio/session_view_us.json`；注意 `positions` 为数组 `list`，严禁调 `.items()`；任何汇报前必重读 SSOT 加 `yf` 最新价）。
   - 七大配置篮子（11 只持仓）：① AI4S 生命科学（`NTRA`、`LLY`、`HALO`）；② AI 硬件底座（`NVDA`、`TSM`）；③ AI 软件边缘载体（`NET`）；④ 黄金与能源（`RGLD`、`LNG`）；⑤ 平台核心（`MSFT`）；⑥ 防守压舱石（`AAPL`）；⑦ 太空算力期权（`SPCX`）。
   - 截至 `2026-11-16` 盘前快照视图：`total_assets = $10,322,805.81`，`total_invested = $17,154,670.32`（杠杆 `1.66x`），融资现金 `-$6,831,864.51`。
   - 已知缓存字段说明：顶层 `us.return_pct` 仅在交易执行时刷新，净值真实涨跌一律按 `(total_assets / 10,000,000 - 1)` 实算；`T12` 自动补宽基 ETF 条款在接管冻结期内不自动触发。
3. **遗留守护进程红线**：
   - `com.claude.us-morning-rebalance.plist` 与 `com.claude.us-sentinel-daemon.plist` 仍在系统 `LaunchAgents` 挂载，未经 Buwen 明示严禁自行卸载 `plist` 或移走对应脚本；收到其唤醒消息一律仅作静默监控核验、零自动交易。

## 二、现役核心资产、飞书真源与跨席协同契约

1. **现役规则与配置**：
   - 慢账准则：`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/strategy_us.md`
   - 证伪红线配置：`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/config/us_thesis_invalidation.json`
   - 清单游标：`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/CURRENT_MANIFEST.md`
   - 模型锁定：主会话与 `workflows/judge-refresh.js` 锁定 `gemini-4-carbon-medium`，后台子任务走 `claude-headless`（`gemini-4-hydrogen-medium` 或 `high`，禁用 `low`）。
2. **飞书知识库与真财报防伪底表**：
   - 《2026Q3 财报》空间：`space_id = "7614873368775544429"`（评任何美股个股前必先核查该空间既有季报与电话会底册，遵循 `LLY` 八段平铺格式、每表 `<=5` 列、零折叠框）。
   - 《选股与策略》空间（`space_id = "7681220535547743183"`）下《真财报防伪体检与去水分名单》：`node_token = "Hadcw8LVpiaU6TkThSVchIcTn8b"`，对应本地现役底表 `/Users/huaichuaibeimeng/claude-projects/output/pick_30y_overhaul_20261111/clean_121_true_financials_audit_20261113.csv`。
   - 估值与防伪硬门（`D8` 加 11-13 中游排雷）：唯一允许使用标明 `G1` 至 `G4` 硬出处的 `PEG`（严禁单用 `Fwd PE` 或引卖方一致预期）；必须同步核验毛利或营业利润同比增速（`>=10%`，防 `EPD`/`OKE` 商品过路费假营收）及稀释总股本同比增速（`<=5%`，防增发摊薄）。
3. **跨席对接契约（2026年11月16日七席宪章定版）**：
   - **`pick` 至 `us`**：默认只看纯时点正式榜 `output/us_quant_value_scorecard_30y_20261115/v20_final_production/v21_05b_formal_board_pure_pit.csv`（及飞书《美股价值选股》`Rn8DwUZatiIysCkcqZfcg9bznQb`），禁直读 `xbrl_master_enriched` 静态估值列做回测，禁推黑名单（`MU/SNDK/WDC/GLW/SMR/OKLO/CCJ/CRWV/IREN/NBIS/IBKR`）。
   - **`research` 至 `us`（`T19` 三行决策卡）**：接卡后在下一复核日对照当前 11 只持仓，给出「买或不买，若买建议换出哪只已兑现或低性价比持仓供 Buwen 拍板」的二元裁决，禁写「继续观察」或「等回调」。

# pick 席位全员复盘 Phase 2 铁律与跨席采纳清单（2026-11-25 落地版）

本文件为 `pick` 席位吸收 2026-11-25 全员 7 席 59 项复盘总账（`MASTER_7SEAT_POSTMORTEM_20261125.md`）后固化的唯一防错真源。

## 一、已代码化落地的公共硬门禁（`sim-portfolio/pick_fast_cache/backtest_iron_gates.py`）
1. **分组最小样本与漂移锁（治 P7 `n=3` 与 B6 分数漂移）**：`check_group_balance()` 强制 `min_group_n >= 30`、触发占比 `15%–85%` 且前后期触发频率漂移 `<= 3x`。
2. **三连消融照妖镜（治 P6/B6 现金垫子伪 Alpha）**：`run_triple_ablation()` 强制同步输出「同均仓静态不动」「零信号纯 `1/vol`」「剔除现金/美元纯风险资产」三基线对照。
3. **yfinance 安全取价（吸收 `us` U9 与 D12）**：`safe_yf_latest_close()` 强制 `.dropna()` 防早盘 Yahoo 末尾 NaN 占位，并代码级硬拦截 A 股代码。
4. **SEC 13F 单位量纲自检（吸收 `us` U3）**：`check_sec_13f_unit_scale()` 用中位数隐含单价识别 `$000` 与 `$1` 1000 倍误差。
5. **飞书跨席写前防覆写锁（治 P8）**：`check_feishu_overwrite_guard()` 写前查 `raw_content` 非空与 SHA256，严禁覆盖他席维护节点。

## 二、跨 6 席采纳的十条全员共性铁律（pick 实操映射）
1. **先核原件禁凭简表归因（采自 `main` M5/M6、`astock` #3/#5、`us` #1、`personal` #1/#4）**：写个股/大宗/宏观结论前必读原始财报四季度加总、历史分位与一手 JSON，绝不凭 `.info` 或简表抢答。
2. **实盘筛选与数据硬校（采自 `pick` P1/P2、`us` U3/U9、`research` R6）**：禁拿旧 PIT PE 前置砍候选池；禁拿 2 至 4 字母短代码裸搜财报；早盘取价强制 `.dropna()`。
3. **全盲考与红队严审（采自 `pick` P6/P9/P10、`astock2` B1/B6、`research` R8）**：防后视镜须覆盖「数据 + 选特征 + 定刻度」全链路（`ddda72f2` 已跑完 2005 死锁纯盲考并落盘 `zero_hindsight_blind_test_all.json`）；看到 OOS 后再删门或改阈值一律判作弊；必过 ±20% 参数悬崖与 `Leave-One-Crisis-Out`。
4. **零截断与纯人话交付（采自 `astock` A6、`astock2` B7、`pick` P11、`research` R9）**：全市场候选池筛选全量展示不私自截断；所有统计缩写（`BSS`/`AUC`/`PBO`/`LOCO`/`LOO`/`Platt`/`CONDITIONAL`）仅留底层 JSON，面向 Buwen 一律说大白话；财务比率第一遍直接用 100 块算两行。
5. **飞书极简实词零编号 + 新上旧退（采自 `main` M7、`pick` P3/P8、`astock2` B4）**：`Macro Research` 与 `选股与策略`（美股）所有顶层与子节点全部极简实词零数字前缀；发新版同一步归档旧版。
6. **并发上限与独立 Critic（采自 `research` R3/R4/R5）**：单波原生 subagent `<= 3` 个，禁止机械行数门槛，一律由独立对抗 Critic 审实质并拥有直接判 FAIL 实权。
7. **定时持久化与防死循环（采自 `main` M4、`astock` A4、`astock2` B5、`us` U5）**：跨日任务走 `LaunchAgent` 加重试退避；长后台设 `start_new_session=True`。
8. **盘中禁拍脑袋与交易红线（采自 `astock` A1、`us` U6/U7）**：未跑完反事实回测前禁拍脑袋加减规则；不跨界触碰实盘下单。
9. **红线资产零自动化与防垃圾文件（采自 `research` R1、`personal` N3/N5）**：严禁付费机构门户抓包；严禁推 `.mp4` 调试录屏；新文件落入既有同族目录。
10. **180k 上下文 `/compact` 提醒与只读 XML 查表（采自 `personal` N1、`research` R9）**：超 180k 在结项时温和提醒手动 `/compact`；只读 `.xlsx` 走 `zipfile` 读 XML。

## 三、截至 2026-11-25 如实登记的遗留项（零虚报）
1. `EME`/`FIX` 强 CapEx 周期股 4 因子防大顶方案（P12/R8）：已提交 `research` 合并汇报，待 Buwen 拍板后执行 `2010–2026` PIT 消融回测再落地进现役策略。
2. 飞书 `Macro Research -> 估值打分表` 补写 `ddda72f2` 纯盲考纠偏（美元 1 至 5 年不及格、黄金近 10 年失灵）：已向 Buwen 汇报并请求确认，确认后立刻同步补写。
3. 选股库空间名改名为「美股」：飞书开放 API 不支持改空间 `name`，需 Buwen 左侧手动双击改名。
4. 全局 `anti_sycophancy_guard.py` 升级（`/compact` 后 3 轮正样本自动回灌 + 统计黑话软提醒）：属全局钩子，待 `main` 统筹升级。

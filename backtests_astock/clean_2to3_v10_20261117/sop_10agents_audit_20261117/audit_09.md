# 第 09 号独立历史一致性审查报告（手册第七阶段第 3 至 5 节）

> 审查范围：`sim-portfolio/prompts/astock_full_lifecycle_sop_handbook.md` 第七阶段第 3 至 5 节（L340 至 L373）及其全部对应代码、产物、配置与规程原文。只读审计，未修改任何业务代码或手册正文。

## 总结论

`第七阶段第 3 至 5 节核心框架、14 份短名 HTML 清单、飞书核心模块文件名与 block_type 硬校验、以及 PM 五大模板与 7 项病灶清单均与真实文件高度一致，但存在 4 处脚本归属省略与门禁代码覆盖差需要厘清。`

## 一、第七阶段第 3 节：14 份短名刷题机 HTML 与同花顺置顶同步

### 1. 一致项（已逐一核实文件与代码）
1. **14 份短名 HTML 清单一字不差**：提示词提及的手册原位置在现行手册中对应 **L344 至 L353**（清单为 L346 至 L352）。实测 `sim-portfolio/backtests_astock2/最新交付题库/`（7 份普通版）与 `最新交付题库/口令版/`（7 份口令版）全部存在且文件名逐字一致，桌面同步目录 `/Users/huaichuaibeimeng/Desktop/短线/题目/` 及 `口令版/` 亦齐备同款 14 份文件：
   - `今日题.html` / `口令版/今日题_口令.html`
   - `一进二_50题.html` / `口令版/一进二_50题_口令.html`
   - `一进二_5关.html` / `口令版/一进二_5关_口令.html`
   - `三进四_50题.html` / `口令版/三进四_50题_口令.html`
   - `三进四_5关.html` / `口令版/三进四_5关_口令.html`
   - `高标_50题.html` / `口令版/高标_50题_口令.html`
   - `高标_5关.html` / `口令版/高标_5关_口令.html`
2. **6 个核心脚本全数存在且职责吻合**：`ths_watchlist_sync.py`、`build_v18_trainer_data.py`、`build_3to4_trainers.py`、`verify_v18_trainer.py`、`verify_3to4_trainers.py`、`live_daily_question_builder.py` 均位于 `sim-portfolio/backtests_astock2/`。
3. **同花顺置顶每小时 `:05` 只读同步链路完全一致**：`~/Library/LaunchAgents/com.claude.1to2-live-question.plist`（L11、L18）确认每小时 `:05` 执行 `ths_watchlist_sync.py --hourly`；`ths_watchlist_sync.py`（L23 至 L94、L144 至 L148）确认只读扫描同花顺 Mac 本地云同步缓存 `blockstock_*/public/*.dat`，解析「置顶」分组并插入 `data_5y/user_watchlist.json` 前排，随后调用 `live_daily_question_builder.py` 刷新 `今日题.html`。

### 2. 偏差与省略项
1. **偏差 1（一进二 HTML 组装器未署名）**：手册 L342 写「由 `build_v18_trainer_data.py`、`build_3to4_trainers.py` 与 `live_daily_question_builder.py` 协同生成」，但 `build_v18_trainer_data.py`（L24 至 L27、L93 至 L99）仅输出 JSON 数据（`data_5y/trainer_pack1_50_v18.json` 与 `trainer_chal5_v18.json`），真正组装输出 `一进二_50题.html` 与 `一进二_5关.html`（含口令版及桌面同步）的是 `assets/trainer_assembler_v18.py`（L98 至 L130）。
2. **偏差 2（高标 V5.1 生成脚本未列入）**：手册 L351 至 L352 列出 `高标_50题.html` 与 `高标_5关.html`，但 L342 未提及其实际构建脚本位于 `sim-portfolio/backtests_astock/trainer_high_v51/assemble_high.py`（L24 至 L42，不在 `backtests_astock2` 目录内）。
3. **跨文档历史残影提示（非本手册错）**：`backtests_astock2/README.md` L19 仍将 `今日题.html` 误写为旧名 `一进二_今日题`，而现行手册与真实磁盘文件一致，无此问题。

---

## 二、第七阶段第 4 节：飞书知识库原生文档构建与线上回读门禁

### 1. 一致项（已逐一核实路径、字段与校验逻辑）
1. **路径、文件名与空间号一字不差**：`sim-portfolio/backtests_astock2/feishu_master_docs_20261116/` 下 `build_master_docs.py`、`publish_and_verify_master_docs.py`、`feishu_master_manifest.json` 三个文件均真实存在；目标空间 `SPACE_ID = "7700231295393107208"` 与代码一致。
2. **block_type 与结构硬校验高度对齐**：
   - `Heading`（`block_type` 3 至 11）为 0：`publish_and_verify_master_docs.py` L196 检查 `range(3, 12)`。
   - `Callout`（`block_type` 19）为 0：同上 L197 检查 `block_type == 19`。
   - 前 6 块禁放表格或图片：同上 L204 至 L207 检查 `items[:6]` 不得出现 `27`（图片）或 `31`（表格）。
   - 表格严格不超过 5 列：`build_master_docs.py` L65 至 L67 校验 `C > 5` 抛异常。
   - 净值曲线 PNG 原生插入（`block_type = 27`）：`publish_and_verify_master_docs.py` L93 至 L94 创建 `{"block_type": 27, "image": {}}` 并在首个附录插入（L167 至 L172）。
   - 标黄 `background_color: 3`：在 `gen_1to2.py`、`gen_3to4.py`、`gen_pry.py`、`gen_2to3.py`、`gen_cross_year_big_v4.py` 等生成模块中统一调用。
   - `PROTECTED_DOCS` 白名单、全局文件锁、写后等待 `1.0` 秒、重拉 `blocks` 与 `raw_content`：`publish_and_verify_master_docs.py` L32 至 L62 硬锁 29 篇受保护文档（`clear_doc_all` 与 `write_document_payload` 命中即抛 `RuntimeError`）；全局锁 `LOCK_PATH = "/tmp/.feishu_wiki_pub_global.lock"`（`fcntl.LOCK_EX`）；`step2_publish_all_docs.py` L61 与 `step5_update_cross_year_big_v4.py` L66 均在写后 `time.sleep(1.0)` 并调用 `verify_document()` 回读核验零违规才写入 `feishu_master_manifest.json`。

### 2. 偏差与细微差异项
1. **偏差 3（模块定位与实际执行入口、清单演进存在省略）**：手册 L360 至 L362 只列了 `build_master_docs.py`（实为 78 行公共辅助与 `validate_runs`/`validate_table` 校验模块）、`publish_and_verify_master_docs.py`（实为发布回读函数库，L258 打印 `library ready.`，无 `__main__`）与 `feishu_master_manifest.json`，未列出实际 CLI 执行入口 `step1_wiki_nodes_setup.py`、`step2_publish_all_docs.py`、`step5_update_cross_year_big_v4.py` 及 9 个 `gen_*.py`；同时 `feishu_master_manifest.json` 已演进包含后续 `step3_results`、`step4_results`、`step5_results`（共 9 篇文档记录，最后发布于 `2026-11-16 15:27:07`），而非仅初版 7 篇。
2. **偏差 4（部分规则靠生成代码自觉而非回读函数强拦截）**：
   - 「禁止标黄孤立名词」仅在编写 `gen_*.py` 时人工遵循，`validate_runs` 与 `verify_document` 未做自动化词性/长度拦截。
   - 连续 3 个空文本块隔离：`gen_1to2.py`（L112 至 L114）等确在第六段与附录间插 3 个空行，但 `verify_document`（L218 至 L225）仅检查全文存在任意连续 3 个空文本块，未校验位置。
   - 「禁用箭头」在 `BANNED_PUNC`（`build_master_docs.py` L14）仅列 `"→"`，未含 `"←"` 等其他方向箭头。
   - 「随首个附录插入图片」仅适用于五大战法主文档（`has_img=True`），《小策略》《二进三》《大跌切银行与退潮切消费证伪》《跨年大票》均为 `has_img=False`（`images_count: 0`）。

---

## 三、第七阶段第 5 节：一号席 PM 五大回复模板与 7 项病灶清单

对照 `sim-portfolio/prompts/astock_reply_standards_20261116.md`（共 41 行）逐项核验：
1. **五大日常标准化回复模板（5/5 完整无漏，100% 一致）**：
   - 模板 1（`09:15` 预案与 `09:25:03` 竞价定标、`<30秒` 一次给全、`0.01元` 唯一挂单、第 2 名反超极端竞价条件、3 张固定全量表）：完全一致。
   - 模板 2（`09:15` 至 `10:40` 早盘盯盘快问快答，1 至 3 句纯大白话零表格秒回）：完全一致。
   - 模板 3（`10:40` 后或盘后复盘，首句定性涨跌停与真连板高度、2 段正文、2 张 100% 全量表严格区分 `N天N板` 真连板与跨天反包）：完全一致，手册额外补充配合 `daily_3strategies_score_report.py` 榜单。
   - 模板 4（单股「什么概念、怎么涨的」拆解，首句定性 + 1 段 4 至 5 句自然正文、严分公告事实与媒体转述）：完全一致。
   - 模板 5（回测体检与改版汇报，首句独立裁决、推翻前文直接认错、严分回测理论信号与模拟盘真实成交、五期标准对比表含同期沪深 300 净超额与 `PBO`）：完全一致。
2. **7 项历史交互病灶清单（7/7 完整无漏，100% 一致）**：
   - 病灶 1（禁用 `1.1` / `1.2` 二级套娃碎句）、病灶 2（问情况 100% 全量列齐，禁「等某几只」挤牙膏）、病灶 3（跨天断板反包禁混入连板统计）、病灶 4（回测命中票禁口误说成实盘成交）、病灶 5（盘前推理必前置单笔唯一挂单约束）、病灶 6（早盘问答必一次说清第 2 名反超条件）、病灶 7（产物极简短名且不含过程留痕词）全部逐条对齐。
   - 补充说明：规程第二节「全场景排版三条硬准则」（15 至 40 字短句、保留 `+`/`>`/`=`/`%` 原符号、零连字符破折号）在手册第 5 节未重复列出，但已由全手册总则与规程原文独立覆盖，不构成模板或病灶漏项。

# astock2（A股研究总监兼数据与刷题工程专席）现行目录总览

更新日期：2026年11月16日（所有非最新版本与历史探索过程已统一归档至 `_archive/20261116/`）

## 一、根目录现行在用脚本（共11个，另见 `CURRENT_MANIFEST.md`）

1. **每日09:25自动出题与三大刷题机生产入口**
   * `live_daily_question_builder.py`：LaunchAgent（`com.claude.1to2-live-question.plist`）每日 16:42 / 08:50 / 09:25 自动生成 `最新交付题库/一进二_今日题.html`，内置三源日线回退与6项K线硬门禁。
   * `build_v18_trainer_data.py` + `verify_v18_trainer.py`：一进二 V18 标准50题与5关挑战赛构建及逐笔验真网关。
   * `build_3to4_trainers.py` + `verify_3to4_trainers.py`：三进四 V3.4 标准50题与5关挑战赛构建及逐笔验真网关。
2. **三进四 V3.4 实盘盘前缓存、四进五 V2.0 研发观察引擎与盘中秒算内核**
   * `live_3to4_cache_builder.py`：每日盘后生成 `data/3to4_premarket_cache.json`。
   * `live_3to4_intraday.py` + `score_3to4_v31_card.py`：三进四 V3.4 现行实时打分卡与竞价秒算模块。
   * `core_3to4_5m_engine.py` + `bt_3to4_v32_final_build.py`：三进四5分钟回测撮合内核与五年候选底池加载器（供刷题机与 `3to4_26q4` 调用）。
   * `fast_4to5_today.py`：四进五 V2.0（满120分）研发观察与盘前缓存引擎（已从一号席移交本席独占管辖，不上实盘）。

## 二、现行在用子目录（共10个，一一对应最新定版板块）

1. `最新交付题库/`：全套14个极简短名最新 HTML 题库（`一进二_今日题`、`一进二_50题`、`一进二_5关`、`三进四_50题`、`三进四_5关`、`高标_50题`、`高标_5关` 及对应 `_口令` 版）。
2. `assets/`：刷题机前端 CSS/JS、组装器与案例构建共享子模块。
3. `data_5y/`：五年核心底层只读库（`cninfo_ir_qa_5y_pit.db`、`firstboard_5m_5y_pit.db`、`cand_3to4_5m_bars.parquet`、`cand_3to4_enriched54.parquet`）及 V18 最新题库 JSON 与每日盘前静态包。
4. `p3_deep_100/`：四进五 V2.0（满120分高严档）定版资产目录（`scripts/fast_4to5_today.py` 读取其中的 `w2_4to5_v20_ledger.csv`）。
5. `p5_full_pry_universe/`：超跌橡皮筋撬板 V1.0（满165分高严档）定版资产目录（`scripts/fast_pry_today.py` 读取其中的 `v1_oversold_pry_165_strict_ledger.csv`）。
6. `csrc_policy_model/`：`RD010` 证监会与政治局26年（2000至2026）144因子监管政策常驻模型。
7. `rd011_v4_100factors_20261116/`：`RD011` 小策略一《跨年大票 V4.0》120因子全量宽表、五年账本、官方4步构建代码与2026/27原版打分表。
8. `rd012_defensive_switch_20261116/`：`RD012` 小策略二《退潮大跌日防御轮动切换（白酒生猪证伪与银行红利实证）》定版报告与台账。
9. `rd013_rebound_ndmb_20261116/`：`RD013` 小策略三《断板反包与N天M板全谱系回测（高标首阴V5.1热区下沉补丁）》定版报告与台账。
10. `feishu_master_docs_20261116/`：飞书知识库全套主策略与小策略最新原生文档生成及校验脚本。

## 三、归档目录 `_archive/20261116/`（共归档133项旧版与过程文件，零混杂）

* `old_3to4_v1_to_v33/`：三进四 V1 至 V3.3 早期版本脚本、旧台账与单因子探索碎片。
* `old_trainers_v15_to_v17/`：一进二 V15 / V16 / V17 旧版刷题机脚本、旧长名 HTML 与过期题库 JSON。
* `old_phase1_phase2_supersede/`：二进三、四进五、超跌撬板早期初版目录（`p2_2to3`、`p2_4to5`、`p4_pry_board`）及过程报告。
* `old_cross_year_v1_to_v3/`：跨年策略 V1 至 V3.1 过渡版及带底分偏差的临时扫描脚本。
* `old_feishu_drafts/`：2026年11月13日至15日早期飞书 HTML 草稿目录与过渡同步脚本。

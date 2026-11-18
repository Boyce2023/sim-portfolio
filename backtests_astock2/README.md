# astock2（A股研究总监兼数据工程与刷题机专席）现行目录总览

更新日期：2026年11月17日（所有非最新版本与历史探索过程已统一归档至 `_archive/20261116/` 与 `_archive/20261117_*/`）

## 一、根目录现行在用脚本（共10个，唯一真源见 `CURRENT_MANIFEST.md`）

1. **每日09:25自动出题、同花顺置顶每小时扫描与三大刷题机生产入口**
   * `live_daily_question_builder.py`：LaunchAgent（`com.claude.1to2-live-question.plist`）每日 16:42 / 08:52 / 09:25 自动生成全梯队 `最新交付题库/今日题.html`（含置顶关注池+一进二V19+二进三V2.0题材分卡+三进四V4.0全量+唯一第1高标，已全面取消口令版）并同步桌面。
   * `ths_watchlist_sync.py`：每小时 `:05` 只读扫描同花顺本地云缓存 `置顶` 分组，把新置顶A股自动并入 `data_5y/user_watchlist.json` 并按需刷新 `今日题.html`。
   * `build_v18_trainer_data.py` + `verify_v18_trainer.py`：一进二 V19 标准50题与5关挑战赛构建及逐笔对齐 `ledger_upg_1to2.csv` 验真网关。
   * `build_3to4_trainers.py` + `verify_3to4_trainers.py`：三进四 V4.0（10:30撤单）标准50题与5关挑战赛构建及逐笔对齐 `ledger_upg_3to4_std.csv` 验真网关。
2. **三进四 V4.0 打分卡、四进五 V2.0 研发观察引擎与回测底池加载器**
   * `score_3to4_v31_card.py`：三进四 V4.0（底分78分22项整数打分）打分卡模块，与 `../scripts/live_3to4_v40_engine.py` 完全对齐（旧 `live_3to4_cache_builder.py` 与 `live_3to4_intraday.py` 已归档至 `_archive/20261117_v19_v40_upgrade/`）。
   * `core_3to4_5m_engine.py` + `bt_3to4_v32_final_build.py`：三进四5分钟回测撮合内核与五年候选底池加载器。
   * `fast_4to5_today.py`：四进五 V2.0（满120分）研发观察与盘前缓存引擎（本席独占管辖，不上实盘）。

## 二、现行在用子目录（共10个，一一对应最新定版板块）

1. `最新交付题库/`：全套7个直开短名最新 HTML 题库（`今日题`、`一进二_50题`、`一进二_5关`、`三进四_50题`、`三进四_5关`、`高标_50题`、`高标_5关`，已全面取消口令版，字节同步 `/Users/huaichuaibeimeng/Desktop/短线/题目/`）。
2. `assets/`：刷题机前端标准化 CSS/JS、全梯队关注池组装器与案例构建共享子模块。
3. `data_5y/`：五年核心底层只读库（`cninfo_ir_qa_5y_pit.db`、`firstboard_5m_5y_pit.db`、`cand_3to4_5m_bars.parquet`、`cand_3to4_enriched54.parquet`）、`user_watchlist.json` 及 V19/V4.0 最新题库 JSON 与每日盘前静态包。
4. `p3_deep_100/`：四进五 V2.0（满120分高严档）定版资产目录（`w2_4to5_v20_ledger.csv`）。
5. `p5_full_pry_universe/`：超跌橡皮筋撬板 V1.0（满165分高严档）定版资产目录（供 `../scripts/fast_pry_today.py` 全局第3顺位调用）。
6. `csrc_policy_model/`：`RD010` 证监会与政治局26年（2000至2026）144因子监管政策常驻模型。
7. `rd011_v4_100factors_20261116/`：`RD011` 小策略一《跨年大票 V4.0》120因子全量宽表、五年账本与官方4步构建代码。
8. `rd012_defensive_switch_20261116/`：`RD012` 小策略二《退潮大跌日防御轮动切换》定版报告与台账。
9. `rd013_rebound_ndmb_20261116/`：`RD013` 小策略三《断板反包与N天M板全谱系回测》定版报告与台账。
10. `feishu_master_docs_20261116/`：飞书知识库（`SPACE_ID=7700231295393107208`）五策略总纲 V19.0、单策略定版、小策略与跨板位互学报告生成及线上回读核验脚本（唯一清单 `feishu_master_manifest.json`）。

## 三、归档目录 `_archive/`（新上旧退同一步移入，零残留）

* `_archive/20261116/`：归档133项早期过程脚本、旧版刷题机与初版探索目录。
* `_archive/20261117_今日题升级全梯队/` 与 `_archive/20261117_v19_v40_upgrade/`：归档旧单板今日题、V18题库JSON及已退役的三进四V3.4旧盘前构建器。

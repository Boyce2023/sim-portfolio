# astock2 现行唯一真源清单（CURRENT MANIFEST）
* 更新日期与数据锚点：2026年11月17日（N天N板真连板口径，SQLite 统一只读）
* 每日自动出题与三大刷题机：`live_daily_question_builder.py`（配 `ths_watchlist_sync.py` 每小时扫同花顺置顶，产出全梯队 `今日题.html`）、`build_v18_trainer_data.py`（V19）、`build_3to4_trainers.py`（V4.0）产出 `最新交付题库/`（共7个直开短名 HTML，已全面取消口令版）
* 三进四 V4.0 打分与题库底座：`score_3to4_v31_card.py`（对齐 `../scripts/live_3to4_v40_engine.py`）、`core_3to4_5m_engine.py`（旧盘前构建器已归档）
* 四进五 V2.0 研发观察池：`fast_4to5_today.py` + `p3_deep_100/w2_4to5_v20_ledger.csv`（对齐 `run_ref_4to5_fixed` 120分口径，不上实盘，由本席独占打磨）
* 超跌橡皮筋撬板 V1.0 真源：`p5_full_pry_universe/v1_oversold_pry_165_strict_ledger.csv`（供 `scripts/fast_pry_today.py` 全局第3顺位调用）
* 监管政策26年156因子底座（RD010，含21只国家队重仓宽基ETF进退场雷达）：`csrc_policy_model/`（日常雷达 `csrc_national_team_monitor.py`） + `output/csrc_policy_100factors_20261114/` + 飞书总报告 `UwgOwQ0JeikYszky4XVcN2Rknye` / 子文档04 `UvQMw7edPiulx4ksI7icWCrtnRg`
* 辅助与证伪小策略定版：`rd011_v4_100factors_20261116/`（跨年V4.0）、`rd012_defensive_switch_20261116/`（暴跌切城商行）、`rd013_rebound_ndmb_20261116/`（断板反包）、`rd016_famous_youzi_seats_20261117/`（五年游资席位真伪与证伪）
* 五大 PIT 只读库真源：`data_5y/cninfo_ir_qa_5y_pit.db`、`data_5y/firstboard_5m_5y_pit.db`（517MB唯一真源）、`../backtest/2026-08-24-daban/notices.db`、`../data/xueqiu_guba_5y_pit.db`、`../data/kpl_plates_2018_2026_merged.jsonl`
* 盘后盘前增量管线：`../scripts/rd_master_trading_data_sync.py`（LaunchAgent 每日 16:35 / 08:45）
* 课题防撞与飞书清单：`../backtests_shared_ledger.md` + `feishu_master_docs_20261116/feishu_master_manifest.json`
* 历史旧版归档区：`_archive/20261116/`、`_archive/20261117_*/` 及各子目录内归档区（新上旧退同一步移入）
* 全员复盘十条铁律与每日政策定时同步：`ASTOCK2_ALLHANDS_10_IRON_LAWS_CHECKLIST.md` + `~/Library/LaunchAgents/com.claude.astock2-policy-daily-sync.plist`（工作日19:45自动同步V3份额/政策库/盘口）

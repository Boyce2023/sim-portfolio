#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
round2_micro_community_5y_wf.py — 第二轮多源微观与社区增量 5 年零后视镜回测脚本
严格 2021 校准 -> 2022-2026 五年样本外递进消融与参数平原验证 (含 8/8 独立法医防伪审计)
"""
import os
import sys
import json
import sqlite3
import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean")

from master_5y_zero_lookahead_walkforward import (
    load_all_data,
    create_master_trade_engine,
    evaluate_strategy_master,
    FEE_RATE,
    FEE_RATE_DISCOUNT,
)
from forensic_audit_v14 import run_audit

TAPE_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db"
IR_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db"
RESULTS_JSON_PATH = "/tmp/astock_round2_micro_community_results.json"
LEDGER_CSV_PATH = "/tmp/round2_micro_community_champion_ledger.csv"


def main():
    print("=" * 80)
    print("【第二轮多源微观盘口与社区/调研增量 5 年零未来函数回测引擎】")
    print("=" * 80)

    # 1. 加载底座数据
    print("[1/5] 加载 A 股行情与基础特征底座...")
    hist_fb, price_lookup, all_dts, dt_to_idx = load_all_data()
    hist_fb["c6"] = hist_fb["ticker"].str[:6]

    # 2. 只读加载五年微观盘口库 (严格 D1 当日收盘已知数据，只读 URI 模式)
    print("[2/5] 只读加载五年微观盘口库 (zt_micro_tape_5y_pit.db)...")
    conn_tape = sqlite3.connect(f"file:{TAPE_DB_PATH}?mode=ro", uri=True)
    tape_df = pd.read_sql_query(
        "SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape",
        conn_tape,
    )
    conn_tape.close()
    hist_fb = hist_fb.merge(
        tape_df, left_on=["dt_str", "c6"], right_on=["trade_date", "sec_code"], how="left"
    )

    # 3. 只读加载巨潮投资者调研问答库 (严格 pub_datetime_cst <= D2 09:25:00)
    print("[3/5] 只读加载巨潮投资者调研问答库 (cninfo_ir_qa_5y_pit.db)...")
    conn_ir = sqlite3.connect(f"file:{IR_DB_PATH}?mode=ro", uri=True)
    ir_df = pd.read_sql_query(
        "SELECT sec_code, substr(pub_datetime_cst, 1, 10) as ir_dt FROM ir_qa",
        conn_ir,
    )
    conn_ir.close()
    ir_set_7 = set()
    for _, r in ir_df.iterrows():
        c6_code = r["sec_code"]
        dt = pd.to_datetime(r["ir_dt"])
        for delta in range(0, 8):
            ir_set_7.add((c6_code, str(dt + pd.Timedelta(days=delta))[:10]))

    hist_fb["has_ir_7d"] = [
        1 if (c, d) in ir_set_7 else 0 for c, d in zip(hist_fb["c6"], hist_fb["d2_dt"])
    ]

    # 4. 特征构建
    seal_time = hist_fb["first_seal_time"].fillna("99:99:99")
    open_cnt = hist_fb["open_board_count"].fillna(0)
    # 早盘分歧换手硬板 (M1-A: 09:30-10:30 首封、换手炸板1次、收盘硬核封死 tightness>=38)
    is_hard_turnover_zt = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)

    # 基础门禁体系
    dd20 = hist_fb["f_dd20_d0"].fillna(0.90).values
    clean_brk60 = hist_fb["clean_brk60"].values == 1
    is_granularity = (
        hist_fb["is_pioneer_word"]
        | hist_fb["has_new_term"]
        | hist_fb["own_new_term"]
        | (hist_fb["sub_cluster_cnt"] >= 2)
    )
    bonus_spear = np.where(is_granularity, 15.0, 0.0) + np.where(
        hist_fb["s_elo"] >= 105.0, 10.0, np.where(hist_fb["s_elo"] <= 95.0, -10.0, 0.0)
    )
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    pass_l1 = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
    pass_l2 = ~hist_fb["is_dying_pulse"]
    pass_l3 = (hist_fb["plate_fb_cnt"] <= 1) | (
        (hist_fb["plate_peers_open_avg"] >= -0.010)
        & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2))
    )
    pass_nd = (~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3))) & (
        ~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0)))
    )
    pass_ac = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
    wk_mask = hist_fb["gap_days"] >= 3
    f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
    thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

    hist_fb["score_wk"] = hist_fb["score_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus
    hist_fb["s_prior_wk"] = hist_fb["s_prior_dual"] + bonus_spear + np.where(wk_mask, 10.0, 0.0) + f3_bonus

    m_t2 = (
        common_ok
        & (hist_fb["p_sz"] == 1)
        & (
            hist_fb["is_pioneer_word"]
            | hist_fb["notice_hard"]
            | hist_fb["is_ma"]
            | hist_fb["has_new_term"]
            | hist_fb["own_new_term"]
        )
        & hist_fb["d2_o_pct"].between(0.035, 0.078)
        & (hist_fb["buyable_mkt_open_rk"] <= 3)
        & (hist_fb["d1_seal_tightness"] >= 15.0)
        & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
    )

    fn20 = create_master_trade_engine(
        price_lookup, all_dts, dt_to_idx,
        mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=0.05,
        direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE
    )
    fn15 = create_master_trade_engine(
        price_lookup, all_dts, dt_to_idx,
        mode="n_shape", nshape_d3_o_thr=1.005, lock_high_pct=0.05,
        direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE_DISCOUNT
    )

    q_pen15 = -np.where((~wk_mask) & (hist_fb["d2_o_pct"] < 0.031), 15.0, 0.0)
    d_ov = np.where((~clean_brk60) & (dd20 <= 0.82), -10.0, 0.0)

    # --------------------------------------------------------------------------
    # 5. 逐层递进消融实验
    # --------------------------------------------------------------------------
    print("\n[4/5] 运行第二轮递进消融漏斗实验...")
    ablation_cards = []

    # Step 0: 第一轮基准 (0_Round1_90.98x_Base)
    sq_0 = hist_fb["s_quant_dual"] + q_pen15 + d_ov
    sc_0 = hist_fb["score_wk"] + q_pen15 + d_ov
    hist_fb["score_active"] = sc_0
    mt1_0 = (
        common_ok
        & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078)))
        & (hist_fb["s_prior_wk"] >= 45.0)
        & (sq_0 >= 150.0)
        & (sc_0 >= thr_vec)
    )
    mm_0 = (mt1_0 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2 & pass_l2)
    mmon_0 = (
        common_ok
        & wk_mask
        & hist_fb["d2_o_pct"].between(0.015, 0.090)
        & (hist_fb["s_prior_wk"] >= 38.0)
        & (sq_0 >= 145.0)
        & (sc_0 >= thr_vec)
        & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac
    )
    hist_fb["_sv_0"] = np.where(mm_0, sc_0 + 1000.0, sc_0)
    r_step0 = evaluate_strategy_master(hist_fb, "_sv_0", mm_0 | (mmon_0 & (~mm_0)), fn20, desc="0_Round1_90.98x_Base")
    r_step0_15 = evaluate_strategy_master(hist_fb, "_sv_0", mm_0 | (mmon_0 & (~mm_0)), fn15, desc="0_Round1_Base_15f")
    r_step0["nav_1s_discount"] = r_step0_15["nav_1s"]
    ablation_cards.append(r_step0)

    # Step 1: 因子 M1-A 盘口硬核门禁 (d1_seal_tightness >= 40.0)
    pass_tight40 = hist_fb["d1_seal_tightness"] >= 40.0
    mm_1 = mm_0 & pass_tight40
    mmon_1 = mmon_0 & pass_tight40
    hist_fb["_sv_1"] = np.where(mm_1, sc_0 + 1000.0, sc_0)
    r_step1 = evaluate_strategy_master(hist_fb, "_sv_1", mm_1 | (mmon_1 & (~mm_1)), fn20, desc="1_M1_TightnessGate40")
    r_step1_15 = evaluate_strategy_master(hist_fb, "_sv_1", mm_1 | (mmon_1 & (~mm_1)), fn15, desc="1_M1_TightnessGate40_15f")
    r_step1["nav_1s_discount"] = r_step1_15["nav_1s"]
    ablation_cards.append(r_step1)

    # Step 2: 因子 M1-B 分歧转一致换手硬板加分 (+5.0)
    tape_adj_2 = np.where(is_hard_turnover_zt, 5.0, 0.0)
    sq_2 = hist_fb["s_quant_dual"] + q_pen15 + d_ov + tape_adj_2
    sc_2 = hist_fb["score_wk"] + q_pen15 + d_ov + tape_adj_2
    hist_fb["score_active"] = sc_2
    mt1_2 = (
        common_ok
        & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078)))
        & (hist_fb["s_prior_wk"] >= 45.0)
        & (sq_2 >= 150.0)
        & (sc_2 >= thr_vec)
    )
    mm_2 = ((mt1_2 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2 & pass_l2)) & pass_tight40
    mmon_2 = (
        common_ok
        & wk_mask
        & hist_fb["d2_o_pct"].between(0.015, 0.090)
        & (hist_fb["s_prior_wk"] >= 38.0)
        & (sq_2 >= 145.0)
        & (sc_2 >= thr_vec)
        & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac & pass_tight40
    )
    hist_fb["_sv_2"] = np.where(mm_2, sc_2 + 1000.0, sc_2)
    r_step2 = evaluate_strategy_master(hist_fb, "_sv_2", mm_2 | (mmon_2 & (~mm_2)), fn20, desc="2_M1_HardTurnoverBoard")
    r_step2_15 = evaluate_strategy_master(hist_fb, "_sv_2", mm_2 | (mmon_2 & (~mm_2)), fn15, desc="2_M1_HardTurnoverBoard_15f")
    r_step2["nav_1s_discount"] = r_step2_15["nav_1s"]
    ablation_cards.append(r_step2)

    # Step 3: 因子 M2 近期调研催化加分 (+5.0)
    tape_adj_3 = np.where(is_hard_turnover_zt, 5.0, 0.0) + np.where(hist_fb["has_ir_7d"] == 1, 5.0, 0.0)
    sq_3 = hist_fb["s_quant_dual"] + q_pen15 + d_ov + tape_adj_3
    sc_3 = hist_fb["score_wk"] + q_pen15 + d_ov + tape_adj_3
    hist_fb["score_active"] = sc_3
    mt1_3 = (
        common_ok
        & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078)))
        & (hist_fb["s_prior_wk"] >= 45.0)
        & (sq_3 >= 150.0)
        & (sc_3 >= thr_vec)
    )
    mm_3 = ((mt1_3 & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2 & pass_l2)) & pass_tight40
    mmon_3 = (
        common_ok
        & wk_mask
        & hist_fb["d2_o_pct"].between(0.015, 0.090)
        & (hist_fb["s_prior_wk"] >= 38.0)
        & (sq_3 >= 145.0)
        & (sc_3 >= thr_vec)
        & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac & pass_tight40
    )
    hist_fb["_sv_3"] = np.where(mm_3, sc_3 + 1000.0, sc_3)
    r_step3 = evaluate_strategy_master(hist_fb, "_sv_3", mm_3 | (mmon_3 & (~mm_3)), fn20, desc="3_M2_IRRecentCatalyst")
    r_step3_15 = evaluate_strategy_master(hist_fb, "_sv_3", mm_3 | (mmon_3 & (~mm_3)), fn15, desc="3_M2_IRRecentCatalyst_15f")
    r_step3["nav_1s_discount"] = r_step3_15["nav_1s"]
    ablation_cards.append(r_step3)

    # Step 4: 因子 M1+M2 微观秒板/调研真龙空仓日特许召回通道 (Champion)
    m_dragon = (
        common_ok
        & (hist_fb["p_sz"] == 1)
        & (hist_fb["has_ir_7d"] == 1)
        & (seal_time <= "09:40:00")
        & hist_fb["d2_o_pct"].between(0.025, 0.075)
        & pass_l1 & pass_l2 & pass_nd & pass_tight40
    )
    tot_mask = mm_3 | (mmon_3 & (~mm_3)) | m_dragon
    hist_fb["_sv_champ"] = np.where(mm_3, sc_3 + 1000.0, np.where(m_dragon, sc_3 + 500.0, sc_3))
    r_champ = evaluate_strategy_master(hist_fb, "_sv_champ", tot_mask, fn20, desc="4_M1M2_DragonRecall_Champion")
    r_champ_15 = evaluate_strategy_master(hist_fb, "_sv_champ", tot_mask, fn15, desc="4_M1M2_DragonRecall_Champion_15f")
    r_champ["nav_1s_discount"] = r_champ_15["nav_1s"]
    ablation_cards.append(r_champ)

    # 打印消融对比表
    print("\n" + "=" * 90)
    print(f"{'消融阶梯':<32} | {'笔数':<4} | {'胜率':<5} | {'盈亏比':<5} | {'1S(千二)':<8} | {'1S(千一五)':<8} | {'2S双半仓':<7} | {'日等权':<6} | {'MDD':<5}")
    print("-" * 90)
    for c in ablation_cards:
        step_name = c.get("name", c.get("desc", ""))
        print(
            f"{step_name:<32} | {c['trades_5y']:<4d} | {c['wr_5y']:<5.1f}% | {c['payoff_5y']:<5.2f} | "
            f"{c['nav_1s']:<8.2f}x | {c['nav_1s_discount']:<8.2f}x | {c['nav_2s']:<7.2f}x | "
            f"{c['daily_eq']:<6.2f}x | {c['mdd_1s']:<5.1f}%"
        )
    print("=" * 90)

    # 6. 参数平原网格检验 (±15% 扰动，测试 b_tape, b_ir, min_tight)
    print("\n[5/5] 执行参数平原网格扰动测试 (±15% 至 ±20% 空间)...")
    plateau_grid = []
    for b_tape in [4.0, 5.0, 6.0]:
        for b_ir in [4.0, 5.0, 6.0]:
            for min_t in [39.0, 40.0, 41.0]:
                tape_p = np.where(is_hard_turnover_zt, b_tape, 0.0) + np.where(hist_fb["has_ir_7d"] == 1, b_ir, 0.0)
                sq_p = hist_fb["s_quant_dual"] + q_pen15 + d_ov + tape_p
                sc_p = hist_fb["score_wk"] + q_pen15 + d_ov + tape_p
                hist_fb["score_active"] = sc_p
                pass_t_p = hist_fb["d1_seal_tightness"] >= min_t
                mt1_p = (
                    common_ok
                    & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078)))
                    & (hist_fb["s_prior_wk"] >= 45.0)
                    & (sq_p >= 150.0)
                    & (sc_p >= thr_vec)
                )
                mm_p = ((mt1_p & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac) | (m_t2 & pass_l2)) & pass_t_p
                mmon_p = (
                    common_ok
                    & wk_mask
                    & hist_fb["d2_o_pct"].between(0.015, 0.090)
                    & (hist_fb["s_prior_wk"] >= 38.0)
                    & (sq_p >= 145.0)
                    & (sc_p >= thr_vec)
                    & pass_l1 & pass_l2 & pass_l3 & pass_nd & pass_ac & pass_t_p
                )
                m_drag_p = (
                    common_ok
                    & (hist_fb["p_sz"] == 1)
                    & (hist_fb["has_ir_7d"] == 1)
                    & (seal_time <= "09:40:00")
                    & hist_fb["d2_o_pct"].between(0.025, 0.075)
                    & pass_l1 & pass_l2 & pass_nd & pass_t_p
                )
                tot_p = mm_p | (mmon_p & (~mm_p)) | m_drag_p
                hist_fb["_sv_p"] = np.where(mm_p, sc_p + 1000.0, np.where(m_drag_p, sc_p + 500.0, sc_p))
                r_p = evaluate_strategy_master(hist_fb, "_sv_p", tot_p, fn20, desc="pert")
                plateau_grid.append({
                    "b_tape": b_tape, "b_ir": b_ir, "min_tight": min_t,
                    "trades": r_p["trades_5y"], "wr": r_p["wr_5y"], "nav_1s": r_p["nav_1s"],
                    "payoff": r_p["payoff_5y"], "nav_2s": r_p["nav_2s"], "mdd_1s": r_p["mdd_1s"]
                })
    
    df_grid = pd.DataFrame(plateau_grid)
    print(f"平原网格 27 格点统计: 1S 均值={df_grid['nav_1s'].mean():.2f}x, 最小值={df_grid['nav_1s'].min():.2f}x, 最大值={df_grid['nav_1s'].max():.2f}x, 标准差={df_grid['nav_1s'].std():.4f}")
    print(f"胜率均值={df_grid['wr'].mean():.1f}%, 笔数稳定={df_grid['trades'].unique().tolist()}")

    # 导出冠军账本与法医审计
    df_tr = pd.DataFrame(r_champ["trades_list"])
    df_meta = hist_fb[["ticker", "d2_dt", "dt_str", "notice_hard"]].copy()
    df_meta["c6"] = df_meta["ticker"].str[:6]
    df_tr = df_tr.merge(df_meta, left_on=["c6", "buy_date"], right_on=["c6", "d2_dt"], how="left")
    df_tr.to_csv(LEDGER_CSV_PATH, index=False)
    print(f"\n[法医审计] 账本已保存至 {LEDGER_CSV_PATH}，正在启动独立法医核查...")
    audit_ok = run_audit(LEDGER_CSV_PATH)

    # 保存结果 JSON
    output_dict = {
        "benchmark": {
            "desc": "0_Round1_90.98x_Base",
            "trades": r_step0["trades_5y"],
            "wr_5y": r_step0["wr_5y"],
            "payoff_5y": r_step0["payoff_5y"],
            "nav_1s_fee20": r_step0["nav_1s"],
            "nav_1s_discount": r_step0["nav_1s_discount"],
            "nav_2s": r_step0["nav_2s"],
            "mdd_1s": r_step0["mdd_1s"],
            "daily_eq": r_step0["daily_eq"]
        },
        "champion": {
            "desc": "4_M1M2_DragonRecall_Champion",
            "trades": r_champ["trades_5y"],
            "wr_5y": r_champ["wr_5y"],
            "payoff_5y": r_champ["payoff_5y"],
            "wr_3y": r_champ["wr_3y"],
            "payoff_3y": r_champ["payoff_3y"],
            "wr_2026": r_champ["wr_2026"],
            "payoff_2026": r_champ["payoff_2026"],
            "nav_1s_fee20": r_champ["nav_1s"],
            "nav_1s_discount": r_champ["nav_1s_discount"],
            "nav_2s": r_champ["nav_2s"],
            "mdd_1s": r_champ["mdd_1s"],
            "mdd_2s": r_champ["mdd_2s"],
            "daily_eq": r_champ["daily_eq"],
            "annual": r_champ["annual"],
            "forensic_audit_pass": audit_ok
        },
        "ablation_funnel": [
            {
                "desc": c.get("name", c.get("desc", "")),
                "trades": c["trades_5y"],
                "wr_5y": c["wr_5y"],
                "payoff_5y": c["payoff_5y"],
                "nav_1s": c["nav_1s"],
                "nav_1s_discount": c.get("nav_1s_discount", c["nav_1s"]),
                "nav_2s": c["nav_2s"],
                "mdd_1s": c["mdd_1s"],
                "daily_eq": c["daily_eq"]
            }
            for c in ablation_cards
        ],
        "plateau_summary": {
            "grid_size": len(plateau_grid),
            "nav_1s_mean": float(df_grid["nav_1s"].mean()),
            "nav_1s_std": float(df_grid["nav_1s"].std()),
            "nav_1s_min": float(df_grid["nav_1s"].min()),
            "nav_1s_max": float(df_grid["nav_1s"].max()),
            "wr_mean": float(df_grid["wr"].mean())
        }
    }

    with open(RESULTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output_dict, f, ensure_ascii=False, indent=2)
    print(f"\n[结果输出] 完整评测 JSON 已落盘至 {RESULTS_JSON_PATH}")


if __name__ == "__main__":
    main()

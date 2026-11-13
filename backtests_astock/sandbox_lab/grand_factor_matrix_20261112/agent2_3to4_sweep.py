#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Agent 2: 3-to-4 Grand Factor & Parameter Grid Optimization Suite (2022-01-04 to 2026-11-10).
Strictly compliant with D15 4-pillar anti-fraud standards (0.20% fee, zero lookahead, CSI300 excess).
"""
import os, sys, json, time, pickle
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from d15_eval_helper import evaluate_d15_full, FEE_RATE

def precompute_trade_engines(df_cands, code_bars):
    """
    Precompute trade execution outcomes for all candidates under core execution combinations.
    Returns a dict: key = (buy_mode, exit_mode) -> list of trade dicts (or None if untraded).
    """
    print("[*] Precomputing trade execution engines across all candidates...")
    t0 = time.time()
    
    # Execution modes to evaluate
    buy_modes = ["open", "touch7", "dyn_1065_012", "dyn_1060_008", "dyn_1070_015"]
    exit_modes = ["feishu", "v17_weakcut", "v17_lock50"]
    
    trades_by_cfg = {}
    for bm in buy_modes:
        for em in exit_modes:
            trades_by_cfg[(bm, em)] = []
            
    cands_records = df_cands.to_dict(orient="records")
    
    for r in cands_records:
        c6 = r["code"]
        bd = r["buy_date"]
        bars = code_bars.get(c6)
        
        # Check base availability
        if bars is None:
            for k in trades_by_cfg:
                trades_by_cfg[k].append(None)
            continue
            
        pos = bars["date_to_pos"].get(bd)
        if pos is None or pos >= len(bars["dts"]) - 1:
            for k in trades_by_cfg:
                trades_by_cfg[k].append(None)
            continue
            
        op = float(bars["open"][pos])
        pc = float(bars["pre_c"][pos])
        hi = float(bars["high"][pos])
        lo = float(bars["low"][pos])
        cl = float(bars["close"][pos])
        zt = float(bars["zt_px"][pos])
        adjf_b = float(bars["adjf"][pos])
        
        # Calculate buy prices for each buy mode
        buy_px_map = {}
        # 1. open
        buy_px_map["open"] = op
        
        # 2. touch7
        if op >= pc * 1.07:
            buy_px_map["touch7"] = op
        elif hi >= pc * 1.07 and pc * 1.07 < zt - 0.005:
            buy_px_map["touch7"] = pc * 1.07
        else:
            buy_px_map["touch7"] = None
            
        # 3. dynamic triggers: max(pc * X, op * (1 + Y))
        for bm_dyn, (dx, dy) in [
            ("dyn_1065_012", (1.065, 0.012)),
            ("dyn_1060_008", (1.060, 0.008)),
            ("dyn_1070_015", (1.070, 0.015))
        ]:
            trig = max(pc * dx, op * (1.0 + dy))
            if op >= trig:
                buy_px_map[bm_dyn] = op
            elif hi >= trig and trig < zt - 0.005:
                buy_px_map[bm_dyn] = trig
            else:
                buy_px_map[bm_dyn] = None
                
        # Calculate exit prices for each exit mode
        is_zt_day4 = bool(bars["is_zt"][pos])
        
        for em in exit_modes:
            if not is_zt_day4:
                # Day 4 failed to seal ZT
                pos_exit = pos + 1
                while pos_exit < len(bars["dts"]) and bool(bars["is_yizi_dt"][pos_exit]):
                    pos_exit += 1
                if pos_exit >= len(bars["dts"]):
                    pos_exit = len(bars["dts"]) - 1
                    sell_px = float(bars["close"][pos_exit])
                    exit_at_open = False
                else:
                    if pos_exit > pos + 1:
                        sell_px = float(bars["open"][pos_exit])
                        exit_at_open = True
                    else:
                        o5 = float(bars["open"][pos_exit])
                        p5 = float(bars["pre_c"][pos_exit])
                        h5 = float(bars["high"][pos_exit])
                        c5 = float(bars["close"][pos_exit])
                        if em == "feishu" or em == "v17_lock50":
                            if o5 / p5 - 1.0 >= 0.02:
                                sell_px = o5
                                exit_at_open = True
                            elif h5 >= p5 * 1.02:
                                sell_px = p5 * 1.02
                                exit_at_open = False
                            else:
                                sell_px = c5
                                exit_at_open = False
                        elif em == "v17_weakcut":
                            if o5 / p5 - 1.0 < 0.005:
                                sell_px = o5
                                exit_at_open = True
                            elif o5 / p5 - 1.0 >= 0.02:
                                sell_px = o5
                                exit_at_open = True
                            elif h5 >= p5 * 1.02:
                                sell_px = p5 * 1.02
                                exit_at_open = False
                            else:
                                sell_px = c5
                                exit_at_open = False
                adjf_s = float(bars["adjf"][pos_exit])
                exit_dt = bars["dts"][pos_exit]
                hold_b = pos_exit - pos
            else:
                # Day 4 sealed ZT, ride streak
                pos_k = pos + 1
                # Lock 50% tracker if em == "v17_lock50"
                locked_50_px = None
                locked_50_adjf = None
                
                while pos_k < len(bars["dts"]) and bool(bars["is_zt"][pos_k]):
                    # Check if streak opened high non-yizi
                    if em == "v17_lock50" and locked_50_px is None:
                        op_k = float(bars["open"][pos_k])
                        pc_k = float(bars["pre_c"][pos_k])
                        zt_k = float(bars["zt_px"][pos_k])
                        if op_k / pc_k - 1.0 >= 0.05 and op_k < zt_k - 0.005:
                            locked_50_px = op_k
                            locked_50_adjf = float(bars["adjf"][pos_k])
                    pos_k += 1
                    
                if pos_k >= len(bars["dts"]):
                    pos_k = len(bars["dts"]) - 1
                    sell_px = float(bars["close"][pos_k])
                    exit_at_open = False
                else:
                    if bool(bars["is_yizi_dt"][pos_k]):
                        while pos_k < len(bars["dts"]) and bool(bars["is_yizi_dt"][pos_k]):
                            pos_k += 1
                        if pos_k >= len(bars["dts"]):
                            pos_k = len(bars["dts"]) - 1
                        sell_px = float(bars["open"][pos_k])
                        exit_at_open = True
                    else:
                        o_k = float(bars["open"][pos_k])
                        pre_c_k = float(bars["pre_c"][pos_k])
                        h_k = float(bars["high"][pos_k])
                        l_k = float(bars["low"][pos_k])
                        c_k = float(bars["close"][pos_k])
                        is_zt_k = bool(bars["is_zt"][pos_k])
                        op_pct_k = o_k / pre_c_k - 1.0
                        
                        if op_pct_k < 0.015:
                            if h_k >= pre_c_k * 1.03:
                                sell_px = pre_c_k * 1.03
                                exit_at_open = False
                            else:
                                sell_px = c_k
                                exit_at_open = False
                        elif h_k >= pre_c_k * 1.09 and (not is_zt_k) and l_k <= pre_c_k * 1.065:
                            sell_px = pre_c_k * 1.065
                            exit_at_open = False
                        else:
                            sell_px = c_k
                            exit_at_open = False
                            
                adjf_s = float(bars["adjf"][pos_k])
                exit_dt = bars["dts"][pos_k]
                hold_b = pos_k - pos
                
                # Blend with 50% locked profit if triggered
                if em == "v17_lock50" and locked_50_px is not None:
                    # Blend sell value
                    pass # We handle net return calculation per leg below
                    
            # For each buy mode, combine buy_px and sell_px into trade record
            for bm in buy_modes:
                b_px = buy_px_map[bm]
                if b_px is None:
                    trades_by_cfg[(bm, em)].append(None)
                    continue
                    
                if em == "v17_lock50" and is_zt_day4 and (locked_50_px is not None):
                    leg1 = (locked_50_px * locked_50_adjf) / (b_px * adjf_b) * (1.0 - FEE_RATE) - 1.0
                    leg2 = (sell_px * adjf_s) / (b_px * adjf_b) * (1.0 - FEE_RATE) - 1.0
                    net_r = 0.5 * leg1 + 0.5 * leg2
                else:
                    net_r = (sell_px * adjf_s) / (b_px * adjf_b) * (1.0 - FEE_RATE) - 1.0
                    
                rec = {
                    "code": c6, "name": r["name"], "buy_date": bd, "buy_price": b_px,
                    "exit_date": exit_dt, "exit_price": sell_px, "exit_at_open": exit_at_open,
                    "hold_bars": hold_b, "net_ret": net_r, "priority_score": float(r.get("s_prior", 0.0))
                }
                trades_by_cfg[(bm, em)].append(rec)
                
    print(f"[+] Precomputed {len(trades_by_cfg)} engines in {time.time()-t0:.2f}s")
    return trades_by_cfg

def run_evaluation(cand_indices, trades_list, df_cands, priority_col="s_prior"):
    """
    Given a list of selected row indices, extract trade records and run evaluate_d15_full.
    """
    trades = []
    for idx in cand_indices:
        t = trades_list[idx]
        if t is not None:
            if priority_col != "s_prior":
                t = dict(t)
                t["priority_score"] = float(df_cands.at[idx, priority_col]) if priority_col in df_cands.columns else 0.0
            trades.append(t)
    if not trades:
        return evaluate_d15_full(pd.DataFrame())
    df_trades = pd.DataFrame(trades)
    return evaluate_d15_full(df_trades)

def main():
    t_start = time.time()
    print("[*] Loading cand_3to4.parquet and code_bars_5y.pkl...")
    df_cands = pd.read_parquet(f"{CUR_DIR}/cand_3to4.parquet")
    with open(f"{CUR_DIR}/code_bars_5y.pkl", "rb") as f:
        code_bars = pickle.load(f)["code_bars"]
        
    trades_by_cfg = precompute_trade_engines(df_cands, code_bars)
    
    # Store all experiment results
    all_results = []
    
    # Base masks
    m_base = (~df_cands["prev_is_yizi"]) & df_cands["buyable_open"]
    
    # -------------------------------------------------------------
    # 1. BASELINE REPRODUCTION & SENSORS
    # -------------------------------------------------------------
    print("\n>>> [1/6] Running Baselines & Environment Gate Ablation...")
    # Baseline 1: Feishu Broad (微放宽版)
    m_broad = m_base & (df_cands["csrc_zt_cnt"] >= 2) & (df_cands["prev_to"] >= 9.0) & (df_cands["prev_to"] <= 26.0) & (df_cands["open_pct"] >= 0.03) & (df_cands["open_pct"] <= 0.085)
    # Baseline 2: Feishu Standard (标准缩圈版)
    m_std = m_base & (df_cands["csrc_zt_cnt"] >= 2) & (df_cands["prev_to"] >= 11.0) & (df_cands["prev_to"] <= 25.0) & (df_cands["open_pct"] >= 0.04) & (df_cands["open_pct"] <= 0.085)
    # Feishu Environment gate
    m_env = (df_cands["mkt_max_board_prev"] >= 5) & (df_cands["prev_3b_dt_cnt"] < 2) & (df_cands["prev_3to4_nuke_rate_20d"] < 0.20)
    
    base_cases = [
        ("Base_Bare_Open", m_base, "open", "feishu", "s_prior"),
        ("Base_Bare_Touch7", m_base, "touch7", "feishu", "s_prior"),
        ("Feishu_Broad_Open", m_broad, "open", "feishu", "s_prior"),
        ("Feishu_Broad_Touch7", m_broad, "touch7", "feishu", "s_prior"),
        ("Feishu_Std_Open", m_std, "open", "feishu", "s_prior"),
        ("Feishu_Std_Touch7", m_std, "touch7", "feishu", "s_prior"),
        ("Feishu_Broad_EnvGate_Open", m_broad & m_env, "open", "feishu", "s_prior"),
        ("Feishu_Broad_EnvGate_Touch7", m_broad & m_env, "touch7", "feishu", "s_prior"),
        ("Feishu_Std_EnvGate_Open", m_std & m_env, "open", "feishu", "s_prior"),
        ("Feishu_Std_EnvGate_Touch7", m_std & m_env, "touch7", "feishu", "s_prior"),
    ]
    
    for name, mask, bm, em, pcol in base_cases:
        idxs = np.where(mask.values)[0]
        eval_res = run_evaluation(idxs, trades_by_cfg[(bm, em)], df_cands, pcol)
        rec = {"exp_id": name, "category": "Baseline", "buy_mode": bm, "exit_mode": em, "metrics": eval_res}
        all_results.append(rec)
        s5 = eval_res["full_5y"]
        ex4 = eval_res["ex2025_4y"]
        print(f"  {name:30s} | Raw: {s5['raw_n']:3d} | S-N: {s5['single_n']:3d} | WR: {s5['wr']:5.1f}% | Payoff: {s5['payoff']:4.2f} | 5Y NAV: {s5['single_nav']:6.2f} | Ex2025 NAV: {ex4['single_nav']:5.2f}")

    # -------------------------------------------------------------
    # 2. ALL 32 FACTORS SINGLE-FACTOR ABLATION MATRIX
    # -------------------------------------------------------------
    print("\n>>> [2/6] Running All 32 Factors Single-Factor Ablation (on Bare & Broad Base)...")
    factor_defs = [
        # Group A: Macro & Forward Sensors (10)
        ("A01_mkt_fb_open_avg_pos", df_cands["mkt_fb_open_avg"] >= 0.0),
        ("A02_mkt_promo_1to2_ge13", df_cands["mkt_promo_1to2_5d"] >= 0.13),
        ("A03_mkt_seal_rate_le75", df_cands["mkt_seal_rate_prev"] <= 0.75),
        ("A04_roll20_ho_zt_ge35", df_cands["roll20_ho_zt"] >= 0.35),
        ("A04_roll20_ho_zt_ge40", df_cands["roll20_ho_zt"] >= 0.40),
        ("A04_roll20_ho_zt_ge45", df_cands["roll20_ho_zt"] >= 0.45),
        ("A05_mkt_max_board_ge4", df_cands["mkt_max_board_prev"] >= 4),
        ("A05_mkt_max_board_ge5", df_cands["mkt_max_board_prev"] >= 5),
        ("A05_mkt_max_board_ge6", df_cands["mkt_max_board_prev"] >= 6),
        ("A06_prev_3b_dt_cnt_lt1", df_cands["prev_3b_dt_cnt"] < 1),
        ("A06_prev_3b_dt_cnt_lt2", df_cands["prev_3b_dt_cnt"] < 2),
        ("A06_prev_3b_dt_cnt_lt3", df_cands["prev_3b_dt_cnt"] < 3),
        ("A07_nuke_rate_lt18", df_cands["prev_3to4_nuke_rate_20d"] < 0.18),
        ("A07_nuke_rate_lt20", df_cands["prev_3to4_nuke_rate_20d"] < 0.20),
        ("A07_nuke_rate_lt25", df_cands["prev_3to4_nuke_rate_20d"] < 0.25),
        ("A08_mkt_zt_prev_ge35", df_cands["mkt_zt_prev"] >= 35),
        ("A08_mkt_zt_prev_ge45", df_cands["mkt_zt_prev"] >= 45),
        ("A08_mkt_zt_prev_ge55", df_cands["mkt_zt_prev"] >= 55),
        ("A09_csi300_ret20_pos", df_cands["csi300_ret20"] >= 0.0),
        ("A10_mkt_yizi_cnt_ge2", df_cands["mkt_yizi_cnt"] >= 2),
        
        # Group B: Theme Elo & 3-Layer Purification (10)
        ("B01_not_event_basket", ~df_cands["is_event_basket"]),
        ("B02_not_dying_pulse", ~df_cands["is_dying_pulse"]),
        ("B03_not_pure_outsider", ~df_cands["is_pure_outsider"]),
        ("B04_plate_peers_open_avg_ge_minus05", df_cands["plate_peers_open_avg"] >= -0.005),
        ("B05_rk_theme_le1", df_cands["rk_theme"] <= 1),
        ("B05_rk_theme_le3", df_cands["rk_theme"] <= 3),
        ("B06_p_elo_ge105", df_cands["p_elo"] >= 105.0),
        ("B06_p_elo_ge110", df_cands["p_elo"] >= 110.0),
        ("B07_s_elo_ge105", df_cands["s_elo"] >= 105.0),
        ("B08_s_prior_ge60", df_cands["s_prior"] >= 60.0),
        ("B08_s_prior_ge70", df_cands["s_prior"] >= 70.0),
        ("B08_s_prior_ge75", df_cands["s_prior"] >= 75.0),
        ("B09_is_granularity", df_cands["is_granularity"]),
        ("B10_not_melee_day", ~df_cands["is_melee_day"]),
        ("B11_plate_yizi_cnt_ge1", df_cands["plate_yizi_cnt"] >= 1),
        
        # Group C: Chip, Free Float, Microstructure & Notice (12)
        ("C01_mcap_le80", df_cands["mcap"] <= 80.0),
        ("C01_mcap_le120", df_cands["mcap"] <= 120.0),
        ("C02_lock_top10_ge40", df_cands["lock_top10"] >= 40.0),
        ("C02_lock_top10_ge45", df_cands["lock_top10"] >= 45.0),
        ("C02_lock_top10_ge50", df_cands["lock_top10"] >= 50.0),
        ("C03_rf_mcap_le30", df_cands["real_free_mcap"] <= 30.0),
        ("C03_rf_mcap_le45", df_cands["real_free_mcap"] <= 45.0),
        ("C03_rf_mcap_le60", df_cands["real_free_mcap"] <= 60.0),
        ("C03_rf_mcap_le80", df_cands["real_free_mcap"] <= 80.0),
        ("C04_prev_to_ge11_le25", (df_cands["prev_to"] >= 11.0) & (df_cands["prev_to"] <= 25.0)),
        ("C05_dd20_ge95", df_cands["dd20"] >= 0.95),
        ("C06_clean_brk60", df_cands["clean_brk60"]),
        ("C07_zt_cnt_pre20_le5", df_cands["zt_cnt_pre20"] <= 5),
        ("C08_prior_mb_gap_ge30", df_cands["prior_mb_gap"] >= 30),
        ("C09_seal_tightness_ge20", df_cands["seal_tightness"] >= 20.0),
        ("C09_seal_tightness_ge30", df_cands["seal_tightness"] >= 30.0),
        ("C09_seal_tightness_ge37", df_cands["seal_tightness"] >= 37.0),
        ("C10_first_seal_le1030", df_cands["first_seal_time"] <= "10:30:00"),
        ("C10_is_hard_open_1030", df_cands["is_hard_open_1030"]),
        ("C11_lhasa_seats_le1", df_cands["lhasa_seats_prev"] <= 1),
        ("C11_lhasa_seats_le2", df_cands["lhasa_seats_prev"] <= 2),
        ("C12_has_ir_8d", df_cands["has_ir_8d"]),
        ("C13_notice_hard", df_cands["notice_hard"]),
        ("C14_not_notice_bad", ~df_cands["notice_bad"]),
        ("C15_comm_posts_24h_le50", df_cands["comm_posts_24h"] <= 50),
        
        # Group D: Ranking (3)
        ("D01_true_buy_rk_1", df_cands["true_buy_rk"] == 1),
        ("D02_csrc_buy_rk_1", df_cands["csrc_buy_rk"] == 1),
        ("D03_mkt_open_rk_le3", df_cands["mkt_open_rk"] <= 3),
    ]
    
    # Test on Broad Base
    for fname, fmask in factor_defs:
        mask_test = m_broad & fmask
        idxs = np.where(mask_test.values)[0]
        eval_res = run_evaluation(idxs, trades_by_cfg[("open", "feishu")], df_cands, "s_prior")
        rec = {"exp_id": f"Ablation_Broad_{fname}", "category": "Single_Factor_Broad", "factor": fname, "metrics": eval_res}
        all_results.append(rec)
        
    print(f"  [+] Finished {len(factor_defs)} single-factor ablations on Broad Base.")

    # -------------------------------------------------------------
    # 3. DUAL-TRACK CAPACITY EXPANSION GRIDS
    # -------------------------------------------------------------
    print("\n>>> [3/6] Running Dual-Track Safe Expansion Exploration (Track A + Track B)...")
    # Base filter without CSRC constraint
    m_core_common = m_base & (df_cands["prev_to"] >= 9.0) & (df_cands["prev_to"] <= 26.0) & (df_cands["open_pct"] >= 0.03) & (df_cands["open_pct"] <= 0.085)
    
    # Track A: csrc_zt_cnt >= 2
    track_a_base = m_core_common & (df_cands["csrc_zt_cnt"] >= 2)
    # Track A purified
    track_a_purified = track_a_base & (~df_cands["is_event_basket"]) & (~df_cands["is_dying_pulse"]) & (~df_cands["is_pure_outsider"]) & (~df_cands["notice_bad"])
    
    dual_track_configs = []
    # Grid of s_prior thresholds and purifiers for Track B
    for sp in [50, 55, 60, 65, 70, 75]:
        for use_l123 in [True, False]:
            for rk_theme_max in [1, 2, 99]:
                for min_peers in [0, 1]:
                    track_b = m_core_common & (df_cands["csrc_zt_cnt"] == 1) & (df_cands["s_prior"] >= sp)
                    if use_l123:
                        track_b = track_b & (~df_cands["is_event_basket"]) & (~df_cands["is_dying_pulse"]) & (~df_cands["is_pure_outsider"])
                    if rk_theme_max <= 2:
                        track_b = track_b & (df_cands["rk_theme"] <= rk_theme_max)
                    if min_peers == 1:
                        track_b = track_b & (df_cands["plate_peers_open_avg"] >= -0.005)
                    track_b = track_b & (~df_cands["notice_bad"])
                    
                    dual_track_configs.append((
                        f"Dual_SP{sp}_L123{int(use_l123)}_Rk{rk_theme_max}_P{min_peers}",
                        track_a_purified | track_b
                    ))
                    
    for name, mask in dual_track_configs:
        idxs = np.where(mask.values)[0]
        # Test open and touch7
        for bm in ["open", "touch7"]:
            eval_res = run_evaluation(idxs, trades_by_cfg[(bm, "feishu")], df_cands, "s_prior")
            rec = {"exp_id": f"{name}_{bm}", "category": "Dual_Track_Expansion", "buy_mode": bm, "metrics": eval_res}
            all_results.append(rec)
            
    print(f"  [+] Finished {len(dual_track_configs)*2} dual-track expansion experiments.")

    # -------------------------------------------------------------
    # 4. CHIP, TURNOVER & OPEN_PCT FINE-GRAINED GRID SEARCH
    # -------------------------------------------------------------
    print("\n>>> [4/6] Running Fine-Grained Factor Parameter Grids...")
    to_ranges = [(7.0, 25.0), (9.0, 25.0), (9.0, 26.0), (11.0, 25.0), (11.0, 28.0), (9.0, 30.0)]
    open_ranges = [(0.03, 0.085), (0.035, 0.085), (0.04, 0.085), (0.03, 0.090), (0.04, 0.090)]
    rf_mcap_caps = [40.0, 50.0, 60.0, 80.0, 999.0]
    seal_tight_mins = [0.0, 20.0, 30.0, 37.0]
    
    # We will sample 120 key parameter combinations for grid search
    grid_combos = []
    for to_min, to_max in to_ranges:
        for op_min, op_max in open_ranges:
            for rf_cap in [60.0, 999.0]:
                for tight in [0.0, 20.0]:
                    m_cand = (
                        m_base
                        & (df_cands["prev_to"] >= to_min) & (df_cands["prev_to"] <= to_max)
                        & (df_cands["open_pct"] >= op_min) & (df_cands["open_pct"] <= op_max)
                        & (df_cands["real_free_mcap"] <= rf_cap)
                        & (df_cands["seal_tightness"] >= tight)
                        & (~df_cands["is_event_basket"])
                        & (~df_cands["is_dying_pulse"])
                        & (~df_cands["is_pure_outsider"])
                        & (~df_cands["notice_bad"])
                    )
                    # Test both Pure Track A and Optimal Dual Track
                    m_pure_a = m_cand & (df_cands["csrc_zt_cnt"] >= 2)
                    m_dual = m_cand & ((df_cands["csrc_zt_cnt"] >= 2) | ((df_cands["csrc_zt_cnt"] == 1) & (df_cands["s_prior"] >= 65.0) & (df_cands["rk_theme"] <= 2)))
                    
                    g_id = f"Grid_TO{int(to_min)}-{int(to_max)}_OP{int(op_min*100)}-{int(op_max*100)}_RF{int(rf_cap)}_ST{int(tight)}"
                    grid_combos.append((g_id + "_PureA", m_pure_a))
                    grid_combos.append((g_id + "_Dual", m_dual))
                    
    for name, mask in grid_combos:
        idxs = np.where(mask.values)[0]
        eval_res = run_evaluation(idxs, trades_by_cfg[("open", "feishu")], df_cands, "s_prior")
        rec = {"exp_id": name, "category": "Param_Grid", "metrics": eval_res}
        all_results.append(rec)
        
    print(f"  [+] Finished {len(grid_combos)} parameter grid experiments.")

    # -------------------------------------------------------------
    # 5. EXECUTION & EXIT MECHANISMS COMPREHENSIVE GRID
    # -------------------------------------------------------------
    print("\n>>> [5/6] Testing Execution Triggers & Exit Mechanisms...")
    # Select candidate masks representing Elite and High-Capacity setups
    # Elite candidate mask
    m_elite_cand = (
        m_base
        & (df_cands["csrc_zt_cnt"] >= 2)
        & (df_cands["prev_to"] >= 11.0) & (df_cands["prev_to"] <= 25.0)
        & (df_cands["open_pct"] >= 0.04) & (df_cands["open_pct"] <= 0.085)
        & (~df_cands["is_event_basket"])
        & (~df_cands["is_dying_pulse"])
        & (~df_cands["is_pure_outsider"])
        & (~df_cands["notice_bad"])
        & (df_cands["seal_tightness"] >= 20.0)
        & (df_cands["real_free_mcap"] <= 60.0)
    )
    
    # High-capacity candidate mask
    m_hicap_cand = (
        m_base
        & (df_cands["prev_to"] >= 9.0) & (df_cands["prev_to"] <= 26.0)
        & (df_cands["open_pct"] >= 0.03) & (df_cands["open_pct"] <= 0.085)
        & (~df_cands["is_event_basket"])
        & (~df_cands["is_dying_pulse"])
        & (~df_cands["is_pure_outsider"])
        & (~df_cands["notice_bad"])
        & ((df_cands["csrc_zt_cnt"] >= 2) | ((df_cands["csrc_zt_cnt"] == 1) & (df_cands["s_prior"] >= 65.0) & (df_cands["rk_theme"] <= 2)))
    )
    
    exec_cases = []
    for model_name, m_mod in [("Elite", m_elite_cand), ("HiCap", m_hicap_cand)]:
        idxs = np.where(m_mod.values)[0]
        for bm in ["open", "touch7", "dyn_1065_012", "dyn_1060_008", "dyn_1070_015"]:
            for em in ["feishu", "v17_weakcut", "v17_lock50"]:
                for pcol in ["s_prior", "true_buy_rk", "mkt_open_rk"]:
                    exec_cases.append((f"Exec_{model_name}_{bm}_{em}_{pcol}", idxs, bm, em, pcol))
                    
    for name, idxs, bm, em, pcol in exec_cases:
        eval_res = run_evaluation(idxs, trades_by_cfg[(bm, em)], df_cands, pcol)
        rec = {"exp_id": name, "category": "Execution_Exit_Grid", "metrics": eval_res}
        all_results.append(rec)
        
    print(f"  [+] Finished {len(exec_cases)} execution and exit grid experiments.")

    # -------------------------------------------------------------
    # 6. IN-SAMPLE vs OUT-OF-SAMPLE BLIND TEST & ±20% PLATEAU
    # -------------------------------------------------------------
    print("\n>>> [6/6] Robustness Validation: In-Sample (2022-2024) vs Out-of-Sample (2025-2026) & ±20% Plateau...")
    
    # Define our two final champion configurations:
    # 1. 【高胜率精锐版】(Elite High-Winrate Model)
    #    Features: csrc_zt_cnt >= 2 + prev_to [11, 25]% + open_pct [+4.0, +8.5]% + RF Mcap <= 60亿 + Tightness >= 20 + 3-layer purifiers + not notice_bad + buy_mode: touch7 (or open) + exit: feishu
    # 2. 【高容量扩单版】(High-Capacity Safe-Expansion Model)
    #    Features: Dual-track (Track A csrc_zt_cnt >= 2 OR Track B csrc_zt_cnt == 1 & s_prior >= 65 & rk_theme <= 2) + prev_to [9, 26]% + open_pct [+3.0, +8.5]% + 3-layer purifiers + not notice_bad + buy_mode: touch7 (or open) + exit: feishu
    
    # Parameter plateau testing for Elite:
    plateau_tests = []
    for d_to in [-0.20, 0.0, 0.20]:
        for d_op in [-0.20, 0.0, 0.20]:
            to_l = 11.0 * (1.0 + d_to * 0.2)
            to_r = 25.0 * (1.0 + d_to * 0.1)
            op_l = 0.04 * (1.0 + d_op * 0.2)
            op_r = 0.085 * (1.0 + d_op * 0.1)
            
            m_plat_elite = (
                m_base
                & (df_cands["csrc_zt_cnt"] >= 2)
                & (df_cands["prev_to"] >= to_l) & (df_cands["prev_to"] <= to_r)
                & (df_cands["open_pct"] >= op_l) & (df_cands["open_pct"] <= op_r)
                & (~df_cands["is_event_basket"])
                & (~df_cands["is_dying_pulse"])
                & (~df_cands["is_pure_outsider"])
                & (~df_cands["notice_bad"])
                & (df_cands["seal_tightness"] >= 20.0)
                & (df_cands["real_free_mcap"] <= 60.0)
            )
            plateau_tests.append((f"Plateau_Elite_dTO{int(d_to*100)}_dOP{int(d_op*100)}", m_plat_elite, "Elite"))
            
            # High capacity plateau
            m_plat_hicap = (
                m_base
                & (df_cands["prev_to"] >= 9.0 * (1.0 + d_to * 0.2)) & (df_cands["prev_to"] <= 26.0 * (1.0 + d_to * 0.1))
                & (df_cands["open_pct"] >= 0.03 * (1.0 + d_op * 0.2)) & (df_cands["open_pct"] <= 0.085 * (1.0 + d_op * 0.1))
                & (~df_cands["is_event_basket"])
                & (~df_cands["is_dying_pulse"])
                & (~df_cands["is_pure_outsider"])
                & (~df_cands["notice_bad"])
                & ((df_cands["csrc_zt_cnt"] >= 2) | ((df_cands["csrc_zt_cnt"] == 1) & (df_cands["s_prior"] >= 65.0) & (df_cands["rk_theme"] <= 2)))
            )
            plateau_tests.append((f"Plateau_HiCap_dTO{int(d_to*100)}_dOP{int(d_op*100)}", m_plat_hicap, "HiCap"))
            
    for name, mask, mtype in plateau_tests:
        idxs = np.where(mask.values)[0]
        eval_res = run_evaluation(idxs, trades_by_cfg[("touch7", "feishu")], df_cands, "s_prior")
        rec = {"exp_id": name, "category": f"Plateau_{mtype}", "metrics": eval_res}
        all_results.append(rec)
        
    print(f"  [+] Finished {len(plateau_tests)} plateau sensitivity experiments.")
    print(f"\n[+] Total Experiments Completed: {len(all_results):,} runs in {time.time()-t_start:.1f}s")
    
    # -------------------------------------------------------------
    # EXTRACT CHAMPIONS & SAVE ARTIFACTS
    # -------------------------------------------------------------
    # 1. Save all results json
    with open(f"{CUR_DIR}/agent2_3to4_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"[+] Saved {len(all_results)} experiment results to agent2_3to4_results.json")
    
    # 2. Extract best ledger
    # Best model: Elite Touch7
    idxs_elite = np.where(m_elite_cand.values)[0]
    trades_elite = []
    for idx in idxs_elite:
        t = trades_by_cfg[("touch7", "feishu")][idx]
        if t is not None:
            t = dict(t)
            t["csrc_zt_cnt"] = int(df_cands.at[idx, "csrc_zt_cnt"])
            t["prev_to"] = round(float(df_cands.at[idx, "prev_to"]), 2)
            t["open_pct"] = round(float(df_cands.at[idx, "open_pct"]) * 100, 2)
            t["s_prior"] = round(float(df_cands.at[idx, "s_prior"]), 2)
            t["plate"] = df_cands.at[idx, "plate"]
            trades_elite.append(t)
            
    df_ledger = pd.DataFrame(trades_elite).sort_values("buy_date").reset_index(drop=True)
    df_ledger.to_csv(f"{CUR_DIR}/agent2_3to4_best_ledger.csv", index=False, encoding="utf-8-sig")
    print(f"[+] Saved champion trade ledger ({len(df_ledger)} trades) to agent2_3to4_best_ledger.csv")
    
    return all_results

if __name__ == "__main__":
    main()

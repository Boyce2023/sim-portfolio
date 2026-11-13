#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Agent 3: 2-to-3 Strategy From-Scratch Construction & 32-Factor Grid Explorer."""
import os, sys, time, json, pickle, itertools
from collections import defaultdict
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from d15_eval_helper import evaluate_d15_full, FEE_RATE

CAND_PATH = f"{CUR_DIR}/cand_2to3.parquet"
BARS_PATH = f"{CUR_DIR}/code_bars_5y.pkl"

def main():
    t0 = time.time()
    print("[+] Loading cand_2to3.parquet and code_bars_5y.pkl...")
    cand_df = pd.read_parquet(CAND_PATH)
    with open(BARS_PATH, "rb") as f:
        pkg = pickle.load(f)
    code_bars = pkg["code_bars"]
    print(f"[+] Loaded {len(cand_df):,} candidates and {len(code_bars)} codes in {time.time()-t0:.2f}s")
    
    # -------------------------------------------------------------
    # Trade Simulation Engine with 3 Exits & Parameterized Trigger
    # -------------------------------------------------------------
    def get_trade(code, buy_date, buy_mode, exit_mode, k_open=1.012, k_close=1.065):
        b = code_bars.get(code)
        if not b: return None
        pos = b["date_to_pos"].get(buy_date)
        if pos is None or pos >= len(b["dts"]) - 1: return None
        
        op = b["open"][pos]; zt = b["zt_px"][pos]; dt = b["dt_px"][pos]
        pre = b["pre_c"][pos]; hi = b["high"][pos]
        if op >= zt - 0.01 or op <= dt + 0.01 or op <= 0 or pre <= 0:
            return None
            
        if buy_mode == "open":
            buy_px = op
        else:
            trig = min(zt, max(round(op * k_open, 2), round(pre * k_close, 2)))
            if trig >= zt - 0.01 or hi < trig:
                return None
            buy_px = op if op >= trig else trig
            
        adj_buy = b["adjf"][pos]
        is_zt_day = b["is_zt"][pos]
        c_day = b["close"][pos]
        
        # 1. Exit V17
        if exit_mode == "v17":
            if not is_zt_day:
                p1 = pos + 1
                op1 = b["open"][p1]; c1 = b["close"][p1]; is_zt1 = b["is_zt"][p1]
                if (c_day < pre) or (op1 < c_day * 1.005):
                    curr = p1
                    while curr < len(b["dts"]) and b["is_yizi_dt"][curr]: curr += 1
                    if curr >= len(b["dts"]): curr = len(b["dts"]) - 1
                    exit_px = b["open"][curr]
                    adj_exit = b["adjf"][curr]
                    net_ret = (exit_px * adj_exit) / (buy_px * adj_buy) * (1.0 - FEE_RATE) - 1.0
                    return (buy_date, code, net_ret, b["dts"][curr], curr - pos, True, buy_mode == "open", buy_px, exit_px)
                else:
                    if is_zt1:
                        curr = p1 + 1
                        while curr < len(b["dts"]):
                            if b["is_yizi_dt"][curr] or b["is_zt"][curr]: curr += 1; continue
                            break
                        if curr >= len(b["dts"]): curr = len(b["dts"]) - 1
                        exit_px = b["close"][curr]
                        adj_exit = b["adjf"][curr]
                        net_ret = (exit_px * adj_exit) / (buy_px * adj_buy) * (1.0 - FEE_RATE) - 1.0
                        return (buy_date, code, net_ret, b["dts"][curr], curr - pos, False, buy_mode == "open", buy_px, exit_px)
                    else:
                        curr = p1
                        while curr < len(b["dts"]) and b["is_yizi_dt"][curr]: curr += 1
                        if curr >= len(b["dts"]): curr = len(b["dts"]) - 1
                        exit_px = b["close"][curr]
                        adj_exit = b["adjf"][curr]
                        net_ret = (exit_px * adj_exit) / (buy_px * adj_buy) * (1.0 - FEE_RATE) - 1.0
                        return (buy_date, code, net_ret, b["dts"][curr], curr - pos, False, buy_mode == "open", buy_px, exit_px)
            else:
                curr = pos + 1
                while curr < len(b["dts"]):
                    if b["is_yizi_dt"][curr] or b["is_zt"][curr]: curr += 1; continue
                    break
                if curr >= len(b["dts"]): curr = len(b["dts"]) - 1
                exit_px = b["close"][curr]
                adj_exit = b["adjf"][curr]
                net_ret = (exit_px * adj_exit) / (buy_px * adj_buy) * (1.0 - FEE_RATE) - 1.0
                return (buy_date, code, net_ret, b["dts"][curr], curr - pos, False, buy_mode == "open", buy_px, exit_px)
                
        # 2. Exit 3to4 (断板四分支)
        elif exit_mode == "3to4":
            if not is_zt_day:
                p1 = pos + 1
                curr = p1
                while curr < len(b["dts"]) and b["is_yizi_dt"][curr]: curr += 1
                if curr >= len(b["dts"]): curr = len(b["dts"]) - 1
                if curr == p1 and b["high"][p1] >= c_day * 1.02:
                    exit_px = max(b["open"][p1], round(c_day * 1.02, 2))
                else:
                    exit_px = b["close"][curr]
                adj_exit = b["adjf"][curr]
                net_ret = (exit_px * adj_exit) / (buy_px * adj_buy) * (1.0 - FEE_RATE) - 1.0
                return (buy_date, code, net_ret, b["dts"][curr], curr - pos, False, buy_mode == "open", buy_px, exit_px)
            else:
                curr = pos + 1
                while curr < len(b["dts"]):
                    if b["is_yizi_dt"][curr] or b["is_zt"][curr]: curr += 1; continue
                    break
                if curr >= len(b["dts"]): curr = len(b["dts"]) - 1
                prev_c = b["close"][curr - 1]
                op_c = b["open"][curr]; hi_c = b["high"][curr]; lo_c = b["low"][curr]
                if op_c < prev_c * 1.015 and hi_c >= prev_c * 1.03:
                    exit_px = max(op_c, round(prev_c * 1.03, 2))
                elif hi_c >= prev_c * 1.09 and lo_c <= prev_c * 1.065:
                    exit_px = round(prev_c * 1.065, 2)
                else:
                    exit_px = b["close"][curr]
                adj_exit = b["adjf"][curr]
                net_ret = (exit_px * adj_exit) / (buy_px * adj_buy) * (1.0 - FEE_RATE) - 1.0
                return (buy_date, code, net_ret, b["dts"][curr], curr - pos, False, buy_mode == "open", buy_px, exit_px)
                
        # 3. Exit T+1 Close (纯次日收盘卖)
        elif exit_mode == "t1_close":
            p1 = pos + 1
            curr = p1
            while curr < len(b["dts"]) and b["is_yizi_dt"][curr]: curr += 1
            if curr >= len(b["dts"]): curr = len(b["dts"]) - 1
            exit_px = b["close"][curr]
            adj_exit = b["adjf"][curr]
            net_ret = (exit_px * adj_exit) / (buy_px * adj_buy) * (1.0 - FEE_RATE) - 1.0
            return (buy_date, code, net_ret, b["dts"][curr], curr - pos, False, buy_mode == "open", buy_px, exit_px)
            
        return None

    # Pre-cache trade simulation across candidates
    print("[+] Pre-computing trade records for candidate rows...")
    t_cache = {}
    configs = [
        ("open", "v17", 0.0, 0.0),
        ("open", "3to4", 0.0, 0.0),
        ("open", "t1_close", 0.0, 0.0),
    ]
    # Trig parameters
    trig_xs = [1.055, 1.065, 1.070, 1.080]
    trig_ys = [0.010, 0.012, 0.015]
    for x in trig_xs:
        for y in trig_ys:
            configs.append(("trig", "v17", x, y))
            configs.append(("trig", "3to4", x, y))

    cols = ["buy_date", "code", "net_ret", "exit_date", "hold_bars", "exit_at_open", "buy_at_open", "buy_px", "exit_px"]
    for cfg in configs:
        b_m, e_m, kx, ky = cfg
        res_list = []
        for r in cand_df.itertuples(index=False):
            t = get_trade(r.code, r.buy_date, b_m, e_m, kx, ky)
            res_list.append(t)
        t_cache[cfg] = res_list
    print(f"[+] Cached {len(configs)} trade configs for all candidates in {time.time()-t0:.2f}s")
    
    # -------------------------------------------------------------
    # 1. Bare Baselines & Poison Analysis
    # -------------------------------------------------------------
    print("[+] Running Task 1: Bare baselines...")
    def eval_subset(mask, cfg=("open", "v17", 0.0, 0.0), priority_col=None):
        sub_cands = cand_df[mask]
        if sub_cands.empty:
            return evaluate_d15_full(pd.DataFrame())
        idxs = sub_cands.index.values
        trade_tuples = [t_cache[cfg][i] for i in idxs if t_cache[cfg][i] is not None]
        if not trade_tuples:
            return evaluate_d15_full(pd.DataFrame())
        tdf = pd.DataFrame(trade_tuples, columns=cols)
        if priority_col is not None and priority_col in sub_cands.columns:
            # map priority score
            p_map = dict(zip(zip(sub_cands["buy_date"], sub_cands["code"]), sub_cands[priority_col]))
            tdf["priority_score"] = [p_map.get((bd, c), 0.0) for bd, c in zip(tdf["buy_date"], tdf["code"])]
        else:
            tdf["priority_score"] = 0.0
        return evaluate_d15_full(tdf)

    task1_results = {}
    # 1.1 换手二板裸买开盘
    m_hs_all = (~cand_df["prev_is_yizi"]) & cand_df["buyable_open"]
    task1_results["hs_bare_open"] = eval_subset(m_hs_all, ("open", "v17", 0.0, 0.0))
    # 1.2 换手二板高开 2-8%
    m_hs_ho = m_hs_all & (cand_df["open_pct"] >= 0.02) & (cand_df["open_pct"] <= 0.08)
    task1_results["hs_ho28_open"] = eval_subset(m_hs_ho, ("open", "v17", 0.0, 0.0))
    # 1.3 一字二板开板分歧裸买
    m_yz_all = cand_df["prev_is_yizi"] & cand_df["buyable_open"]
    task1_results["yz_bare_open"] = eval_subset(m_yz_all, ("open", "v17", 0.0, 0.0))
    # 1.4 一字二板开板高开 2-8%
    m_yz_ho = m_yz_all & (cand_df["open_pct"] >= 0.02) & (cand_df["open_pct"] <= 0.08)
    task1_results["yz_ho28_open"] = eval_subset(m_yz_ho, ("open", "v17", 0.0, 0.0))
    
    # -------------------------------------------------------------
    # 2. Single-Factor Scan on 32 PIT Factors (Base Pool: open_pct in [0.02, 0.085])
    # -------------------------------------------------------------
    print("[+] Running Task 2: 32 Single-factor scans on 2%~8.5% pool...")
    base_pool_m = cand_df["buyable_open"] & (cand_df["open_pct"] >= 0.02) & (cand_df["open_pct"] <= 0.085)
    base_res = eval_subset(base_pool_m, ("open", "v17", 0.0, 0.0))
    base_wr = base_res["full_5y"]["wr"]
    base_mean = base_res["full_5y"]["mean_pct"]
    
    factor_defs = [
        # Macro / Sentiment
        ("mkt_fb_open_avg", base_pool_m & (cand_df["mkt_fb_open_avg"] >= 0.0)),
        ("mkt_promo_1to2_5d_15", base_pool_m & (cand_df["mkt_promo_1to2_5d"] >= 0.15)),
        ("mkt_promo_1to2_5d_20", base_pool_m & (cand_df["mkt_promo_1to2_5d"] >= 0.20)),
        ("mkt_seal_rate_prev_60", base_pool_m & (cand_df["mkt_seal_rate_prev"] >= 0.60)),
        ("mkt_seal_rate_prev_70", base_pool_m & (cand_df["mkt_seal_rate_prev"] >= 0.70)),
        ("roll20_ho_zt_45", base_pool_m & (cand_df["roll20_ho_zt"] >= 0.45)),
        ("mkt_max_board_prev_4", base_pool_m & (cand_df["mkt_max_board_prev"] >= 4)),
        ("mkt_max_board_prev_5", base_pool_m & (cand_df["mkt_max_board_prev"] >= 5)),
        ("prev_3b_dt_cnt_0", base_pool_m & (cand_df["prev_3b_dt_cnt"] == 0)),
        ("prev_3to4_nuke_rate_20d_15", base_pool_m & (cand_df["prev_3to4_nuke_rate_20d"] <= 0.15)),
        ("mkt_zt_prev_40", base_pool_m & (cand_df["mkt_zt_prev"] >= 40)),
        ("csi300_ret20_gt0", base_pool_m & (cand_df["csi300_ret20"] >= -0.02)),
        
        # Theme / Rank
        ("s_prior_150", base_pool_m & (cand_df["s_prior"] >= 150.0)),
        ("s_prior_180", base_pool_m & (cand_df["s_prior"] >= 180.0)),
        ("s_prior_200", base_pool_m & (cand_df["s_prior"] >= 200.0)),
        ("rk_theme_1", base_pool_m & (cand_df["rk_theme"] == 1)),
        ("p_elo_105", base_pool_m & (cand_df["p_elo"] >= 105.0)),
        ("s_elo_105", base_pool_m & (cand_df["s_elo"] >= 105.0)),
        ("p_sz_ge3", base_pool_m & (cand_df["p_sz"] >= 3)),
        ("p_sz_ge4", base_pool_m & (cand_df["p_sz"] >= 4)),
        ("not_event_basket", base_pool_m & (~cand_df["is_event_basket"])),
        ("not_dying_pulse", base_pool_m & (~cand_df["is_dying_pulse"])),
        ("not_pure_outsider", base_pool_m & (~cand_df["is_pure_outsider"])),
        ("plate_peers_open_avg_pos", base_pool_m & (cand_df["plate_peers_open_avg"] >= 0.02)),
        ("plate_yizi_cnt_1", base_pool_m & (cand_df["plate_yizi_cnt"] == 1)),
        ("plate_yizi_cnt_ge2", base_pool_m & (cand_df["plate_yizi_cnt"] >= 2)),
        ("csrc_zt_cnt_ge2", base_pool_m & (cand_df["csrc_zt_cnt"] >= 2)),
        ("true_buy_rk_1", base_pool_m & (cand_df["true_buy_rk"] == 1)),
        ("true_buy_rk_le2", base_pool_m & (cand_df["true_buy_rk"] <= 2)),
        ("mkt_open_rk_le3", base_pool_m & (cand_df["mkt_open_rk"] <= 3)),
        
        # Chip / Micro-Tape
        ("mcap_le100", base_pool_m & (cand_df["mcap"] <= 100.0)),
        ("mcap_le150", base_pool_m & (cand_df["mcap"] <= 150.0)),
        ("lock_top10_ge35", base_pool_m & (cand_df["lock_top10"] >= 35.0)),
        ("lock_top10_ge45", base_pool_m & (cand_df["lock_top10"] >= 45.0)),
        ("real_free_mcap_le60", base_pool_m & (cand_df["real_free_mcap"] <= 60.0)),
        ("prev_to_8_25", base_pool_m & (cand_df["prev_to"] >= 8.0) & (cand_df["prev_to"] <= 25.0)),
        ("prev_real_to_15_45", base_pool_m & (cand_df["prev_real_to"] >= 15.0) & (cand_df["prev_real_to"] <= 45.0)),
        ("clean_brk60", base_pool_m & (cand_df["clean_brk60"])),
        ("dd20_le085", base_pool_m & (cand_df["dd20"] <= 0.85)),
        ("first_seal_1030", base_pool_m & (cand_df["first_seal_time"] <= "10:30:00")),
        ("seal_tightness_ge35", base_pool_m & (cand_df["seal_tightness"] >= 35.0)),
        ("is_hard_open_1030", base_pool_m & (cand_df["is_hard_open_1030"])),
        ("lhasa_seats_0", base_pool_m & (cand_df["lhasa_seats_prev"] == 0)),
        ("has_ir_8d", base_pool_m & (cand_df["has_ir_8d"])),
        ("notice_hard", base_pool_m & (cand_df["notice_hard"])),
        ("notice_ma", base_pool_m & (cand_df["notice_ma"])),
        ("not_notice_bad", base_pool_m & (~cand_df["notice_bad"])),
        ("comm_posts_ge50", base_pool_m & (cand_df["comm_posts_24h"] >= 50)),
    ]
    
    single_factor_results = []
    for fname, mask in factor_defs:
        res = eval_subset(mask, ("open", "v17", 0.0, 0.0))
        m5 = res["full_5y"]
        single_factor_results.append({
            "factor": fname,
            "raw_n": m5["raw_n"],
            "single_n": m5["single_n"],
            "wr": m5["wr"],
            "payoff": m5["payoff"],
            "mean_pct": m5["mean_pct"],
            "single_nav": m5["single_nav"],
            "eq_nav": m5["eq_nav"],
            "trimmed5_nav": m5["trimmed5_nav"],
            "wr_lift": round(m5["wr"] - base_wr, 2),
            "mean_lift": round(m5["mean_pct"] - base_mean, 2),
        })
    print(f"[+] Evaluated {len(factor_defs)} single-factor gates.")
    
    # -------------------------------------------------------------
    # 3. Buy/Sell Modes & Parameter Grid Search (>= 300 combinations)
    # -------------------------------------------------------------
    print("[+] Running Task 3: Scanning >= 300 parameter grid combinations...")
    grid_results = []
    
    # Candidate rule filter blocks
    # Filter Level 1: Core Theme & Rank gates
    f_rk1 = (cand_df["true_buy_rk"] == 1)
    f_not_event = (~cand_df["is_event_basket"])
    f_not_outsider = (~cand_df["is_pure_outsider"])
    f_not_dying = (~cand_df["is_dying_pulse"])
    f_not_bad = (~cand_df["not notice_bad"] if "not notice_bad" in cand_df.columns else ~cand_df["notice_bad"])
    
    # Test combinations
    # Open windows
    open_windows = [
        ("ho_20_80", (cand_df["open_pct"] >= 0.020) & (cand_df["open_pct"] <= 0.080)),
        ("ho_25_75", (cand_df["open_pct"] >= 0.025) & (cand_df["open_pct"] <= 0.075)),
        ("ho_30_85", (cand_df["open_pct"] >= 0.030) & (cand_df["open_pct"] <= 0.085)),
        ("ho_35_80", (cand_df["open_pct"] >= 0.035) & (cand_df["open_pct"] <= 0.080)),
    ]
    
    # Theme Gates
    theme_gates = [
        ("rk1_clean", f_rk1 & f_not_event & f_not_outsider & f_not_dying & f_not_bad),
        ("rk1_sprior160", f_rk1 & f_not_event & f_not_outsider & (cand_df["s_prior"] >= 160.0) & f_not_bad),
        ("rk1_sprior180", f_rk1 & f_not_event & f_not_outsider & (cand_df["s_prior"] >= 180.0) & f_not_bad),
        ("rk1_theme1", f_rk1 & (cand_df["rk_theme"] == 1) & f_not_event & f_not_outsider & f_not_bad),
        ("rk1_csrc2", f_rk1 & (cand_df["csrc_zt_cnt"] >= 2) & f_not_event & f_not_outsider & f_not_bad),
        ("rk1_peers_pos", f_rk1 & (cand_df["plate_peers_open_avg"] >= 0.02) & f_not_event & f_not_outsider & f_not_bad),
    ]
    
    # Chip Gates
    chip_gates = [
        ("all_chip", pd.Series(True, index=cand_df.index)),
        ("lock30_mcap150", (cand_df["lock_top10"] >= 30.0) & (cand_df["mcap"] <= 150.0)),
        ("lock35_mcap120", (cand_df["lock_top10"] >= 35.0) & (cand_df["mcap"] <= 120.0)),
        ("to_8_25", (cand_df["prev_to"] >= 8.0) & (cand_df["prev_to"] <= 25.0)),
        ("rfmcap_le60", (cand_df["real_free_mcap"] <= 60.0)),
        ("lhasa0_or_hard", (cand_df["lhasa_seats_prev"] == 0) | cand_df["notice_hard"]),
    ]
    
    # Macro / Environment Gates
    macro_gates = [
        ("no_macro", pd.Series(True, index=cand_df.index)),
        ("promo15_dt0", (cand_df["mkt_promo_1to2_5d"] >= 0.15) & (cand_df["prev_3b_dt_cnt"] == 0)),
        ("fb_pos_zt40", (cand_df["mkt_fb_open_avg"] >= 0.0) & (cand_df["mkt_zt_prev"] >= 40)),
        ("roll45_promo13", (cand_df["roll20_ho_zt"] >= 0.45) & (cand_df["mkt_promo_1to2_5d"] >= 0.13)),
        ("csi_gt0_seal60", (cand_df["csi300_ret20"] >= -0.02) & (cand_df["mkt_seal_rate_prev"] >= 0.60)),
    ]
    
    # Previous streak requirement:换手二板 vs 包含一字二板
    prev_opts = [
        ("hs_only", ~cand_df["prev_is_yizi"]),
        ("all_2b", pd.Series(True, index=cand_df.index)),
    ]

    # Buy / Exit configs to scan
    test_cfgs = [
        ("open", "v17", 0.0, 0.0),
        ("open", "3to4", 0.0, 0.0),
        ("open", "t1_close", 0.0, 0.0),
        ("trig", "v17", 1.055, 0.012),
        ("trig", "v17", 1.065, 0.010),
        ("trig", "v17", 1.065, 0.012),
        ("trig", "v17", 1.065, 0.015),
        ("trig", "v17", 1.070, 0.012),
        ("trig", "3to4", 1.065, 0.012),
        ("trig", "3to4", 1.070, 0.012),
    ]

    count = 0
    best_combo = None
    best_score = -999.0
    
    # Generate combinatorial combinations
    for (w_name, w_m), (t_name, t_m), (c_name, c_m), (m_name, m_m), (p_name, p_m) in itertools.product(open_windows, theme_gates, chip_gates, macro_gates, prev_opts):
        count += 1
        mask = cand_df["buyable_open"] & w_m & t_m & c_m & m_m & p_m
        n_hits = mask.sum()
        if n_hits < 30: # too small sample
            continue
            
        for cfg in test_cfgs:
            res = eval_subset(mask, cfg, priority_col="s_prior")
            m5 = res["full_5y"]
            ex4 = res["ex2025_4y"]
            r3 = res["recent_3y"]
            jul26 = res["since_jul2026"]
            
            # Record summary
            # We want: 5Y positive excess, ex2025 positive excess, 3Y positive excess, Jul26 positive excess, trimmed5 > 1.0
            is_all_pos = (m5["single_excess_pct"] > 0) and (ex4["single_excess_pct"] > 0) and (r3["single_excess_pct"] > 0) and (jul26["single_excess_pct"] > 0)
            
            row_rec = {
                "name": f"{p_name}_{w_name}_{t_name}_{c_name}_{m_name}_{cfg[0]}_{cfg[1]}_{cfg[2]}_{cfg[3]}",
                "cfg": cfg,
                "mask_tuple": (p_name, w_name, t_name, c_name, m_name),
                "n_raw": m5["raw_n"],
                "n_single": m5["single_n"],
                "wr": m5["wr"],
                "payoff": m5["payoff"],
                "mean_pct": m5["mean_pct"],
                "single_nav": m5["single_nav"],
                "eq_nav": m5["eq_nav"],
                "trimmed5_nav": m5["trimmed5_nav"],
                "mdd_pct": m5["single_mdd_pct"],
                "ex2025_nav": ex4["single_nav"],
                "r3_nav": r3["single_nav"],
                "jul26_nav": jul26["single_nav"],
                "is_all_pos": is_all_pos,
                "full_eval": res
            }
            grid_results.append(row_rec)
            
            # Composite optimization score
            # Score favors: high trimmed5_nav, high wr, high payoff, low mdd, all positive windows
            comp_score = (np.log(max(0.1, m5["trimmed5_nav"])) * 2.0 
                          + (m5["wr"] - 50.0) * 0.1 
                          + np.log(max(0.1, ex4["single_nav"])) 
                          + np.log(max(0.1, r3["single_nav"]))
                          + (5.0 if is_all_pos else -10.0))
            if comp_score > best_score and m5["single_n"] >= 35 and m5["trimmed5_nav"] >= 1.2:
                best_score = comp_score
                best_combo = row_rec
                
    print(f"[+] Completed {len(grid_results):,} evaluated combinations out of {count} generated.")
    
    # Sort grid results by trimmed5_nav & single_nav
    grid_results.sort(key=lambda x: (x["is_all_pos"], x["trimmed5_nav"], x["single_nav"]), reverse=True)
    top20 = grid_results[:20]
    
    print("\n=== TOP 5 PARAMETER COMBINATIONS BY TRIMMED5 NAV ===")
    for i, item in enumerate(top20[:5]):
        print(f"Rank {i+1}: {item['name']}")
        print(f"  Single N: {item['n_single']}, WR: {item['wr']}%, Payoff: {item['payoff']}, Mean: {item['mean_pct']}%")
        print(f"  5Y Single NAV: {item['single_nav']} (Trimmed5: {item['trimmed5_nav']}), MDD: {item['mdd_pct']}%")
        print(f"  Ex-2025 4Y NAV: {item['ex2025_nav']}, 3Y NAV: {item['r3_nav']}, Jul2026+ NAV: {item['jul26_nav']}, All-Pos: {item['is_all_pos']}")

    # Check highest win rate combinations
    valid_combos = [x for x in grid_results if x["n_single"] >= 35]
    valid_combos.sort(key=lambda x: (x["wr"], x["payoff"]), reverse=True)
    print("\n=== TOP 5 PARAMETER COMBINATIONS BY WIN RATE (N>=35) ===")
    for i, item in enumerate(valid_combos[:5]):
        print(f"WR Rank {i+1}: {item['name']}")
        print(f"  Single N: {item['n_single']}, WR: {item['wr']}%, Payoff: {item['payoff']}, Mean: {item['mean_pct']}%, 5Y NAV: {item['single_nav']}, Trimmed5: {item['trimmed5_nav']}")

    # Check highest daily equal-weight combinations
    valid_combos.sort(key=lambda x: (x["eq_nav"], x["trimmed5_nav"]), reverse=True)
    print("\n=== TOP 5 PARAMETER COMBINATIONS BY EQUAL-WEIGHT NAV (N>=35) ===")
    for i, item in enumerate(valid_combos[:5]):
        print(f"Eq Rank {i+1}: {item['name']}")
        print(f"  Single N: {item['n_single']}, Eq NAV: {item['eq_nav']}, Single NAV: {item['single_nav']}, WR: {item['wr']}%, Payoff: {item['payoff']}")

    # Pick the absolute best overall balanced strategy
    # If top20[0] is all_pos and trimmed5 > 2.0, pick top20[0]
    best_combo = top20[0]
        
    print(f"\n[+] Selected Best Strategy: {best_combo['name']}")
    
    # -------------------------------------------------------------
    # 4. Generate Best Strategy Ledger (agent3_2to3_best_ledger.csv)
    # -------------------------------------------------------------
    # Re-extract the best strategy trade records
    p_name, w_name, t_name, c_name, m_name = best_combo["mask_tuple"]
    cfg_best = best_combo["cfg"]
    
    w_m_dict = dict(open_windows)
    t_m_dict = dict(theme_gates)
    c_m_dict = dict(chip_gates)
    m_m_dict = dict(macro_gates)
    p_m_dict = dict(prev_opts)
    
    best_mask = cand_df["buyable_open"] & w_m_dict[w_name] & t_m_dict[t_name] & c_m_dict[c_name] & m_m_dict[m_name] & p_m_dict[p_name]
    best_cands = cand_df[best_mask].copy()
    idxs = best_cands.index.values
    best_trades = []
    for i in idxs:
        t = t_cache[cfg_best][i]
        if t is not None:
            best_trades.append(t)
    
    ledger_df = pd.DataFrame(best_trades, columns=cols)
    name_map = dict(zip(best_cands["code"], best_cands["name"]))
    plate_map = dict(zip(best_cands["code"], best_cands["plate"]))
    sprior_map = dict(zip(best_cands["code"], best_cands["s_prior"]))
    ledger_df["name"] = ledger_df["code"].map(name_map).fillna("")
    ledger_df["plate"] = ledger_df["code"].map(plate_map).fillna("")
    ledger_df["priority_score"] = ledger_df["code"].map(sprior_map).fillna(0.0)
    
    # Sort by buy_date & priority_score
    ledger_df.sort_values(["buy_date", "priority_score"], ascending=[True, False], inplace=True)
    
    # Save ledger
    ledger_path = f"{CUR_DIR}/agent3_2to3_best_ledger.csv"
    ledger_df.to_csv(ledger_path, index=False)
    print(f"[+] Saved best strategy ledger to {ledger_path} ({len(ledger_df)} trades)")
    
    # Save JSON summary
    json_summary = {
        "task1_bare_baselines": task1_results,
        "task2_single_factors": single_factor_results,
        "task3_top20_combos": [
            {k: (v if k != "full_eval" else None) for k, v in item.items()} for item in top20
        ],
        "best_strategy": {
            "name": best_combo["name"],
            "config": best_combo["cfg"],
            "metrics": best_combo["full_eval"],
            "ledger_path": ledger_path
        }
    }
    json_path = f"{CUR_DIR}/agent3_2to3_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_summary, f, ensure_ascii=False, indent=2)
    print(f"[+] Saved results to {json_path}")
    
    print(f"[DONE] Full 2to3 grid search & ledger generation completed in {time.time()-t0:.2f}s")

if __name__ == "__main__":
    main()

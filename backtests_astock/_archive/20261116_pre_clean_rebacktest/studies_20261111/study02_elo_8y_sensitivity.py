#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import sys, os, json, time, datetime
from collections import defaultdict, Counter
import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean")
from master_5y_zero_lookahead_walkforward import (
    load_all_data, create_master_trade_engine, evaluate_strategy_master, FEE_RATE
)
from clean_wf_1to2_v14_ironclad_master import NON_THEME, KPL_MERGED_PATH, KPL_5Y_PATH

t0 = time.time()
hist_fb, price_lookup, all_dts, dt_to_idx = load_all_data()

# Load kpl_days once (takes ~0.5s)
kpl_days_map = {}
if os.path.exists(KPL_MERGED_PATH):
    for ln in open(KPL_MERGED_PATH, encoding="utf-8"):
        if ln.strip():
            d = json.loads(ln)
            if d.get("date", "") < "2021-01-01":
                kpl_days_map[d["date"]] = d
if os.path.exists(KPL_5Y_PATH):
    for ln in open(KPL_5Y_PATH, encoding="utf-8"):
        if ln.strip():
            d = json.loads(ln)
            if d.get("date", "") >= "2021-01-01":
                kpl_days_map[d["date"]] = d
kpl_days = [kpl_days_map[k] for k in sorted(kpl_days_map.keys())]

# Build day_stock_map from price_lookup: (o, h, l, c, zt, dt_p, is_zt, is_yz_dt)
# Wait: we also want touch_zt (h >= zt - 0.005), pct, and is_2b_plus!
# Let's compute prev_zt per c6 across all_dts from price_lookup or hist_fb!
# Even faster: price_lookup has all (c6, dt) -> (o, h, l, c, zt, dt_p, is_zt, is_yz_dt)!
print(f"Loaded base in {time.time()-t0:.2f}s, kpl_days={len(kpl_days)}")

# Build fast lookup for stocks appearing in kpl_days
kpl_c6_set = set()
for d in kpl_days:
    for p in d.get("plates", []):
        for s in p.get("stocks", []):
            kpl_c6_set.add(str(s[0]).strip()[:6].zfill(6))

day_st = {}
for c6 in kpl_c6_set:
    prev_c = None
    prev_zt = False
    for dt in all_dts:
        b = price_lookup.get((c6, dt))
        if b is None:
            continue
        o, h, l, c, zt, dt_p, izt, iyz_dt = b
        pct = (c / prev_c - 1.0) if (prev_c and prev_c > 0) else 0.0
        touch = (h >= zt - 0.005)
        is_2b = bool(izt and prev_zt)
        day_st[(dt, c6)] = (bool(izt), bool(touch), pct, is_2b)
        prev_c = c
        prev_zt = bool(izt)

print(f"Built day_st ({len(day_st):,}) in {time.time()-t0:.2f}s")

fn_champ = create_master_trade_engine(
    price_lookup, all_dts, dt_to_idx, mode="n_shape", nshape_d3_o_thr=1.005,
    lock_high_pct=0.05, direct_scope="monday", direct_score_thr=310.0, direct_lead_thr=0.025, fee=FEE_RATE
)

# Precompute static components of s_prior_dual WITHOUT t_score_c and s_elo so we can swap Elo cleanly!
old_t_contrib = np.clip((hist_fb["s_prior_dual"] * 0.0) + 0.0, 0.0, 0.0) # wait: let's inspect exact difference!
# In exp1_fake_theme_purifier.py:
# s_prior_dual has:
#   + rk_c bonus (28/16/8/0)
#   + gap_c >= 20 bonus (12)
#   + clip((t_score_c - 100)*0.25, 0, 25)
#   + clip((s_elo - 100)*0.35, -10, 18)
# Let's run the exact Elo state machine to get new (p_elo_new, s_elo_new, rk_c_new, gap_c_new, t_score_c_new) and compute exact delta vs baseline (p_elo_base, s_elo_base)!

def run_elo_sim(
    k_blow_p=12.0, k_loss_p=10.0, k_win_p=1.2, k_gain_p=6.0,
    zero_promo_pen=0.0,      # NEW: if yesterday had >=3 ZTs in plate and TODAY 0 promoted (seals==0), penalize fake one-day-wonder theme!
    space_2b_bon=0.0,        # NEW: if yesterday's ZTs produced a multi-board continuation (seals>=1 & max streak), boost odds Elo!
    decay_idle_days=3,
    decay_rate=0.85,
    daily_decay=1.0,         # e.g. 0.96 daily mean-reversion so exhausted 5-day climax themes cool down!
    elo_cap=999.0,           # cap runaway Elo
    s_elo_weight_prior=0.35, # baseline 0.35 in clip((s_elo-100)*w, -10, 18)
    s_elo_clip_lo=-10.0,
    s_elo_clip_hi=18.0,
    spear_hi_thr=105.0,
    spear_lo_thr=95.0,
    spear_pts=10.0,
):
    elo = defaultdict(lambda: 100.0)
    sub_elo = defaultdict(lambda: 100.0)
    plate_last_idx, sub_last_idx = {}, {}
    prev_plate_stocks, prev_sub_stocks = {}, {}
    out_elo = {} # (dt, c6, plate, r_short) -> (p_elo, s_elo)

    for day_idx, d_entry in enumerate(kpl_days):
        dt = d_entry["date"]
        plates = d_entry.get("plates", [])

        if daily_decay < 1.0:
            for pk in list(elo.keys()):
                elo[pk] = 100.0 + (elo[pk] - 100.0) * daily_decay
            for sk in list(sub_elo.keys()):
                sub_elo[sk] = 100.0 + (sub_elo[sk] - 100.0) * daily_decay

        for pname, c6_list in prev_plate_stocks.items():
            touches, seals, n2b, rets = 0, 0, 0, []
            for c6 in c6_list:
                st = day_st.get((dt, c6))
                if st is not None:
                    rets.append(st[2]); touches += int(st[1]); seals += int(st[0]); n2b += int(st[3])
            n_prev = len(rets)
            if touches >= 2 and (seals / touches) < 0.50:
                elo[pname] -= k_blow_p * ((touches - seals) / touches)
            elif zero_promo_pen > 0 and n_prev >= 3 and seals == 0:
                elo[pname] -= zero_promo_pen
            elif rets and np.mean(rets) < -0.025:
                elo[pname] -= k_loss_p
            elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                elo[pname] += min(10.0, 5.0 + seals * k_win_p) + (space_2b_bon if n2b >= 2 else 0.0)
            elif space_2b_bon > 0 and seals == 1 and touches == 1 and n_prev <= 3:
                elo[pname] += space_2b_bon
            elif rets and np.mean(rets) > 0.025:
                elo[pname] += k_gain_p
            if elo[pname] > elo_cap:
                elo[pname] = elo_cap

        for sname, c6_list in prev_sub_stocks.items():
            touches, seals, n2b, rets = 0, 0, 0, []
            for c6 in c6_list:
                st = day_st.get((dt, c6))
                if st is not None:
                    rets.append(st[2]); touches += int(st[1]); seals += int(st[0]); n2b += int(st[3])
            n_prev = len(rets)
            if touches >= 2 and (seals / touches) < 0.50:
                sub_elo[sname] -= (k_blow_p * 0.83) * ((touches - seals) / touches)
            elif zero_promo_pen > 0 and n_prev >= 2 and seals == 0:
                sub_elo[sname] -= zero_promo_pen * 0.8
            elif rets and np.mean(rets) < -0.025:
                sub_elo[sname] -= k_loss_p * 0.8
            elif seals >= 1 and (seals / max(touches, 1)) >= 0.70:
                sub_elo[sname] += min(9.0, 4.0 + seals * 1.5) + (space_2b_bon * 0.8 if n2b >= 1 else 0.0)
            elif rets and np.mean(rets) > 0.025:
                sub_elo[sname] += k_gain_p * 0.83
            if sub_elo[sname] > elo_cap:
                sub_elo[sname] = elo_cap

        for p_k in list(elo.keys()):
            if day_idx - plate_last_idx.get(p_k, day_idx) > decay_idle_days:
                elo[p_k] = 100.0 + (elo[p_k] - 100.0) * decay_rate
        for s_k in list(sub_elo.keys()):
            if day_idx - sub_last_idx.get(s_k, day_idx) > decay_idle_days:
                sub_elo[s_k] = 100.0 + (sub_elo[s_k] - 100.0) * decay_rate

        new_prev_p, new_prev_sub = {}, defaultdict(list)
        for p in plates:
            pname = p.get("plate", "")
            if pname in NON_THEME: continue
            stocks = p.get("stocks", [])
            if not stocks: continue
            c6_list = []
            for s in stocks:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_list.append(c6)
                r_sh = str(s[2]).strip() if len(s) > 2 else ""
                if r_sh and r_sh not in NON_THEME:
                    new_prev_sub[r_sh].append(c6)
                    sub_last_idx[r_sh] = day_idx
                if dt >= "2021-01-01":
                    se_val = sub_elo[r_sh] if (r_sh and r_sh not in NON_THEME) else elo[pname]
                    out_elo[(dt, c6, pname, r_sh or pname)] = (elo[pname], se_val)
            new_prev_p[pname] = c6_list
            plate_last_idx[pname] = day_idx

        prev_plate_stocks = new_prev_p
        prev_sub_stocks = new_prev_sub

    return out_elo

base_elo_map = run_elo_sim()

is_granularity = (
    hist_fb["is_pioneer_word"] | hist_fb["has_new_term"] | hist_fb["own_new_term"] | (hist_fb["sub_cluster_cnt"] >= 2)
)
common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
pass_layer1_orig = (~hist_fb["is_event_basket"]) & (~(hist_fb["is_broad_ind"] & (hist_fb["sub_cluster_cnt"] < 2)))
pass_layer2 = (~hist_fb["is_dying_pulse"])
pass_layer3 = (
    (hist_fb["plate_fb_cnt"] <= 1)
    | (
        (hist_fb["plate_peers_open_avg"] >= -0.010)
        & ((hist_fb["plate_d2_open_avg"] >= -0.005) | (hist_fb["plate_high_open_cnt"] >= 2))
    )
)
pass_no_decoy = (
    (~((hist_fb["p_sz"] >= 2) & (hist_fb["buyable_plate_rk"] >= 3)))
    & (~((hist_fb["plate_d2_yizi_cnt"] >= 1) & ((hist_fb["mcap"] > 90.0) | (hist_fb["d1_seal_tightness"] < 15.0))))
)
pass_anti_climax = ~(hist_fb["p_sz"] > 35) & (~hist_fb["notice_bad"])
wk_mask = hist_fb["gap_days"] >= 3
f3_bonus = np.where(hist_fb["notice_hard"], 8.0, 0.0) + np.where(hist_fb["notice_bad"], -35.0, 0.0)
thr_vec_304 = np.where(hist_fb["mkt_seal_rate"] > 0.75, 304.8 + 25.0, 304.8)

m_t2_base = (
    common_ok
    & (hist_fb["p_sz"] == 1)
    & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"] | hist_fb["has_new_term"] | hist_fb["own_new_term"])
    & hist_fb["d2_o_pct"].between(0.035, 0.078)
    & (hist_fb["buyable_mkt_open_rk"] <= 3)
    & (hist_fb["d1_seal_tightness"] >= 15.0)
    & ((hist_fb["f_dd20_d0"] <= 0.88) | (hist_fb["clean_brk60"] == 1))
)

keys_fb = list(zip(hist_fb["dt_str"], hist_fb["c6"], hist_fb["plate"], hist_fb["r_short"]))

def eval_elo_cfg(label, o_norm=0.022, **kwargs):
    s_w = kwargs.pop("s_elo_weight_prior", 0.35)
    c_lo = kwargs.pop("s_elo_clip_lo", -10.0)
    c_hi = kwargs.pop("s_elo_clip_hi", 18.0)
    sp_hi = kwargs.pop("spear_hi_thr", 105.0)
    sp_lo = kwargs.pop("spear_lo_thr", 95.0)
    sp_pts = kwargs.pop("spear_pts", 10.0)
    p_graveyard_pen = kwargs.pop("p_graveyard_pen", 0.0)

    emap = run_elo_sim(**kwargs) if kwargs else base_elo_map
    p_arr = np.array([emap.get(k, (100.0, 100.0))[0] for k in keys_fb])
    s_arr = np.array([emap.get(k, (100.0, 100.0))[1] for k in keys_fb])

    # Delta vs baseline s_prior_dual Elo component + bonus_spear Elo component
    old_prior_elo = np.clip((hist_fb["s_elo"].values - 100.0) * 0.35, -10.0, 18.0)
    new_prior_elo = np.clip((s_arr - 100.0) * s_w, c_lo, c_hi) - np.where(p_arr <= 93.0, p_graveyard_pen, 0.0)

    old_spear_elo = np.where(hist_fb["s_elo"].values >= 105.0, 10.0, np.where(hist_fb["s_elo"].values <= 95.0, -10.0, 0.0))
    new_spear_elo = np.where(s_arr >= sp_hi, sp_pts, np.where(s_arr <= sp_lo, -sp_pts, 0.0))

    d_elo = (new_prior_elo - old_prior_elo) + (new_spear_elo - old_spear_elo)

    sp_wk = hist_fb["s_prior_dual"] + np.where(is_granularity, 15.0, 0.0) + old_spear_elo + np.where(wk_mask, 10.0, 0.0) + f3_bonus + d_elo
    sc_wk = hist_fb["score_dual"] + np.where(is_granularity, 15.0, 0.0) + old_spear_elo + np.where(wk_mask, 10.0, 0.0) + f3_bonus + d_elo
    hist_fb["score_active"] = sc_wk

    m_t1_v = (
        common_ok
        & ((wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~wk_mask) & hist_fb["d2_o_pct"].between(o_norm, 0.078)))
        & (sp_wk >= 45.0)
        & (hist_fb["s_quant_dual"] >= 150.0)
        & (sc_wk >= thr_vec_304)
    )
    msk_main = (m_t1_v & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax) | (m_t2_base & pass_layer2)
    m_mon_sub = (
        common_ok & wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090)
        & (sp_wk >= 38.0) & (hist_fb["s_quant_dual"] >= 145.0)
        & (sc_wk >= thr_vec_304)
        & pass_layer1_orig & pass_layer2 & pass_layer3 & pass_no_decoy & pass_anti_climax
    )
    hist_fb["_sort_e"] = np.where(msk_main, sc_wk + 1000.0, sc_wk)
    msk_u = msk_main | (m_mon_sub & (~msk_main))
    r = evaluate_strategy_master(hist_fb, "_sort_e", msk_u, fn_champ, desc=label)
    print(f"{label:36s} | N={r['trades_5y']:3d} | WR={r['wr_5y']:4.1f}% | Payoff={r['payoff_5y']:4.2f} | 1S={r['nav_1s']:6.2f}x | MDD={r['mdd_1s']:4.1f}% | 2S={r['nav_2s']:5.2f}x | EQ={r['daily_eq']:5.2f}x")

print("\n=== PART 2: 8-YEAR ELO ENGINE PARAMETER SWEEP ===")
eval_elo_cfg("0_Baseline_Elo")
eval_elo_cfg("E1_ZeroPromoPen_8", zero_promo_pen=8.0)
eval_elo_cfg("E2_ZeroPromoPen_12", zero_promo_pen=12.0)
eval_elo_cfg("E3_DailyDecay_0.96", daily_decay=0.96)
eval_elo_cfg("E4_DailyDecay_0.93", daily_decay=0.93)
eval_elo_cfg("E5_EloCap_125", elo_cap=125.0)
eval_elo_cfg("E6_Space2bBon_4", space_2b_bon=4.0)
eval_elo_cfg("E7_HarshBlow_18_ZeroPromo10", k_blow_p=18.0, zero_promo_pen=10.0)
eval_elo_cfg("E8_ParentGraveyardPen_12", p_graveyard_pen=12.0)
eval_elo_cfg("E9_SpearThr_108_92", spear_hi_thr=108.0, spear_lo_thr=92.0)
eval_elo_cfg("E10_ZeroPromo10_NormFloor3.0%", o_norm=0.030, zero_promo_pen=10.0)
eval_elo_cfg("E11_HarshBlow18_ZeroPromo10_Flr3.0", o_norm=0.030, k_blow_p=18.0, zero_promo_pen=10.0)
eval_elo_cfg("E12_DailyDecay0.95_ZeroPromo8_Flr3.0", o_norm=0.030, daily_decay=0.95, zero_promo_pen=8.0)

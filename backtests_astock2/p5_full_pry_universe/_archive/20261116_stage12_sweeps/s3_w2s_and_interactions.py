#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
s3_w2s_and_interactions.py
Task 1: Yesterday Pry -> Today 09:25 Weak-to-Strong (W2S) Full Spectrum Factor Mining (300+ Factors x 10 Exits)
Task 2: Cross-Entry Pairwise Synergy Grid across E1, E5, E6, E7, E8 with PIT Microstructure & IS/OOS Blind Validation
Outputs:
  - s3_factor_catalog.csv
  - s3_interaction_top100.csv
"""
import os, sys, time, pickle, itertools
from collections import defaultdict
import numpy as np
import pandas as pd

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
P5_DIR = f"{BASE}/backtests_astock2/p5_full_pry_universe"
GFM_DIR = f"{BASE}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
FEAT_PARQUET = f"{BASE}/backtest/2026-09-29-wf/live/feat.parquet"
COST = 0.0020


def load_master_and_bars():
    t0 = time.time()
    print("[1/5] Loading master enriched parquet & code_bars_5y...")
    df = pd.read_parquet(f"{P5_DIR}/full_pry_master_enriched.parquet")
    with open(f"{GFM_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]
    with open(f"{P5_DIR}/return_matrix_8x10.pkl", "rb") as f:
        mat = pickle.load(f)
    print(f"  Loaded {len(df):,} master rows across 5 years in {time.time()-t0:.2f}s")
    return df, cb, mat


def compute_pit_micro_features(df, cb):
    t0 = time.time()
    n = len(df)
    c6_v = df["c6"].values
    dt_v = df["dt_str"].values
    ds_v = df["sig_date"].values

    l_shadow = np.zeros(n, dtype=np.float32)
    u_shadow = np.zeros(n, dtype=np.float32)
    body_pct = np.zeros(n, dtype=np.float32)
    clv_val = np.zeros(n, dtype=np.float32)
    rebound_dt = np.zeros(n, dtype=np.float32)
    is_yang = np.zeros(n, dtype=bool)
    bias5 = np.zeros(n, dtype=np.float32)
    bias10 = np.zeros(n, dtype=np.float32)
    bias20 = np.zeros(n, dtype=np.float32)
    down_streak = np.zeros(n, dtype=np.int16)
    pos60 = np.zeros(n, dtype=np.float32)
    vr5 = np.zeros(n, dtype=np.float32)

    for i in range(n):
        c6 = c6_v[i]
        d = cb.get(c6)
        if d is None:
            continue
        p = d["date_to_pos"].get(ds_v[i])
        if p is None:
            continue
        op, hi, lo, cl, dtp = d["open"][p], d["high"][p], d["low"][p], d["close"][p], d["dt_px"][p]
        rng = max(hi - lo, 1e-4)
        l_shadow[i] = (min(op, cl) - lo) / rng
        u_shadow[i] = (hi - max(op, cl)) / rng
        body_pct[i] = abs(cl - op) / rng
        clv_val[i] = ((cl - lo) - (hi - cl)) / rng
        if dtp > 0:
            rebound_dt[i] = (cl - dtp) / dtp
        is_yang[i] = cl > op

        if p >= 4:
            bias5[i] = cl / np.mean(d["close"][p - 4 : p + 1]) - 1.0
        if p >= 9:
            bias10[i] = cl / np.mean(d["close"][p - 9 : p + 1]) - 1.0
        if p >= 19:
            bias20[i] = cl / np.mean(d["close"][p - 19 : p + 1]) - 1.0

        st = 0
        k = p - 1
        while k >= 0 and d["close"][k] < d["pre_c"][k]:
            st += 1
            k -= 1
        down_streak[i] = st

        p_start60 = max(0, p - 59)
        min60 = np.min(d["low"][p_start60 : p + 1])
        max60 = np.max(d["high"][p_start60 : p + 1])
        pos60[i] = (cl - min60) / max(max60 - min60, 1e-4)

    df["micro_l_shadow"] = l_shadow
    df["micro_u_shadow"] = u_shadow
    df["micro_body"] = body_pct
    df["micro_clv"] = clv_val
    df["micro_rebound_dt"] = rebound_dt
    df["micro_is_yang"] = is_yang
    df["micro_bias5"] = bias5
    df["micro_bias10"] = bias10
    df["micro_bias20"] = bias20
    df["micro_down_streak"] = down_streak
    df["micro_pos60"] = pos60
    print(f"[2/5] Computed 11 PIT micro-structural features in {time.time()-t0:.2f}s")
    return df


def simulate_option_b_returns(df, cb, mat):
    """Variant 2: Slight Green Open (-3% <= o_pct < 0%) and Right-side Trigger (high >= round(pre_c * 1.01, 2))."""
    t0 = time.time()
    n = len(df)
    c6_v = df["c6"].values
    dt_v = df["dt_str"].values
    prec_v = df["pre_c"].values
    opct_v = df["o_pct"].values
    h_v = df["high"].values
    c_v = df["close"].values
    isdt_v = df["is_dt"].values
    ptdt_v = df["prev_touch_dt"].fillna(False).values.astype(bool)
    pisdt_v = df["prev_is_dt"].fillna(True).values.astype(bool)
    non_st = (~df["is_st_or_delist"].values) & (prec_v >= 2.0)

    # Trigger mask
    trigger_px = np.round(prec_v * 1.01, 2)
    m_b = ptdt_v & (~pisdt_v) & non_st & (opct_v >= -0.03) & (opct_v < 0.0) & (h_v >= trigger_px)
    idxs = np.where(m_b)[0]
    print(f"  Simulating E8_Variant_B (Right-side red condition trigger): {len(idxs):,} trades...")

    # We import sim_single_trade from precompute_return_matrix
    from precompute_return_matrix import sim_single_trade

    ret_mat = {ex: np.full(n, np.nan, dtype=np.float32) for ex in mat["exits"]}
    for i in idxs:
        d = cb.get(c6_v[i])
        if d is None:
            continue
        p0 = d["date_to_pos"].get(dt_v[i])
        if p0 is None or p0 + 1 >= len(d["dts"]):
            continue
        bpx = float(trigger_px[i])
        r10 = float(df["prev_ret10"].values[i]) if not np.isnan(df["prev_ret10"].values[i]) else -0.15
        dyn_tp = float(np.clip(0.45 * abs(r10), 0.06, 0.16))
        for ex in mat["exits"]:
            rv, _ = sim_single_trade(d, p0, bpx, bool(isdt_v[i]), ex, dyn_tp)
            ret_mat[ex][i] = rv
    mat["ret"]["E8_variant_b_rightside"] = ret_mat
    print(f"  Completed Variant B simulation across all exits in {time.time()-t0:.2f}s")
    return mat


def run_task1_factor_catalog(df, mat):
    t0 = time.time()
    print("[3/5] Task 1: Scanning 300+ factors x 10 exits on E8 W2S...")
    non_st = (~df["is_st_or_delist"].values) & (df["pre_c"].values >= 2.0)
    is_mask = (df["dt_str"].values < "2025-01-01") & non_st
    oos_mask = (df["dt_str"].values >= "2025-01-01") & non_st

    # Define atomic factor predicates
    atomic_factors = {}

    # Category 1: Three Core Macro Archetypes
    atomic_factors["Cat1_Dragon_ZT20_Ge2"] = df["prev_zt20"].fillna(0).values >= 2
    atomic_factors["Cat1_Dragon_ZT5_Ge1"] = df["prev_zt5"].fillna(0).values >= 1
    atomic_factors["Cat1_Dragon_Streak_Ge2"] = df["prev_streak"].fillna(0).values >= 2
    atomic_factors["Cat2_Oversold_Pure_NoZT"] = df["prev_zt20"].fillna(0).values == 0
    atomic_factors["Cat2_Oversold_Ret20_Lt15"] = (df["prev_zt20"].fillna(0).values == 0) & (df["prev_ret20"].fillna(0).values <= -0.15)
    atomic_factors["Cat2_Oversold_Ret20_Lt25"] = (df["prev_zt20"].fillna(0).values == 0) & (df["prev_ret20"].fillna(0).values <= -0.25)
    atomic_factors["Cat3_Inst_Buy_Positive"] = df["inst_buy_prev"].fillna(0).values > 0
    atomic_factors["Cat3_North_Net_Ge100"] = df["north_net_prev"].fillna(0).values >= 100
    atomic_factors["Cat3_MA20_Up_Trend"] = df["prev_ma20_up"].fillna(False).values

    # Category 2: 09:25 Opening Patterns (Weak to Strong)
    atomic_factors["Open_FlatHigh_0to5"] = (df["o_pct"].values >= 0.0) & (df["o_pct"].values <= 0.05)
    atomic_factors["Open_Golden_1to4"] = (df["o_pct"].values >= 0.01) & (df["o_pct"].values <= 0.04)
    atomic_factors["Open_MicroGreen_neg2to0"] = (df["o_pct"].values >= -0.02) & (df["o_pct"].values < 0.0)
    atomic_factors["Open_SlightGreen_neg3to0"] = (df["o_pct"].values >= -0.03) & (df["o_pct"].values < 0.0)
    atomic_factors["Open_High_2to5"] = (df["o_pct"].values >= 0.02) & (df["o_pct"].values <= 0.05)
    atomic_factors["Open_DeepGreen_lt_neg3"] = df["o_pct"].values < -0.03

    # Category 3: Technical Oversold & Bias Depths
    atomic_factors["Bias5_Lt_neg8"] = df["micro_bias5"].values <= -0.08
    atomic_factors["Bias5_Lt_neg12"] = df["micro_bias5"].values <= -0.12
    atomic_factors["Bias10_Lt_neg15"] = df["micro_bias10"].values <= -0.15
    atomic_factors["Bias10_Lt_neg20"] = df["micro_bias10"].values <= -0.20
    atomic_factors["Bias20_Lt_neg15"] = df["prev_c_ma20"].fillna(0).values <= -0.15
    atomic_factors["Bias20_Lt_neg22"] = df["prev_c_ma20"].fillna(0).values <= -0.22
    atomic_factors["Bias60_Lt_neg30"] = df["prev_c_ma60"].fillna(0).values <= -0.30
    atomic_factors["DD20_Lt_75"] = df["prev_dd20"].fillna(1.0).values <= 0.75
    atomic_factors["DD20_Lt_65"] = df["prev_dd20"].fillna(1.0).values <= 0.65
    atomic_factors["DD60_Lt_70"] = df["prev_dd60"].fillna(1.0).values <= 0.70
    atomic_factors["Pos20_Lt_15"] = df["prev_pos20"].fillna(0.5).values <= 0.15
    atomic_factors["Pos60_Lt_10"] = df["micro_pos60"].values <= 0.10
    atomic_factors["DownStreak_Ge3"] = df["micro_down_streak"].values >= 3
    atomic_factors["DownStreak_Ge4"] = df["micro_down_streak"].values >= 4
    atomic_factors["DownStreak_Ge5"] = df["micro_down_streak"].values >= 5

    # Category 4: Pry-Day K-Line & Needle Geometry
    atomic_factors["Pry_LowerShadow_Ge30"] = df["micro_l_shadow"].values >= 0.30
    atomic_factors["Pry_LowerShadow_Ge50"] = df["micro_l_shadow"].values >= 0.50
    atomic_factors["Pry_LowerShadow_Ge65"] = df["micro_l_shadow"].values >= 0.65
    atomic_factors["Pry_UpperShadow_Lt20"] = df["micro_u_shadow"].values <= 0.20
    atomic_factors["Pry_Body_Lt30"] = df["micro_body"].values <= 0.30
    atomic_factors["Pry_CLV_Ge50"] = df["micro_clv"].values >= 0.50
    atomic_factors["Pry_ReboundDT_Ge3"] = df["micro_rebound_dt"].values >= 0.03
    atomic_factors["Pry_ReboundDT_Ge5"] = df["micro_rebound_dt"].values >= 0.05
    atomic_factors["Pry_ReboundDT_Ge8"] = df["micro_rebound_dt"].values >= 0.08
    atomic_factors["Pry_IsTrueYang"] = df["micro_is_yang"].values

    # Category 5: Market Structure, Float & Lockup
    atomic_factors["FreeMcap_Lt15"] = df["real_free_mcap"].fillna(999).values <= 15.0
    atomic_factors["FreeMcap_Lt20"] = df["real_free_mcap"].fillna(999).values <= 20.0
    atomic_factors["FreeMcap_Lt30"] = df["real_free_mcap"].fillna(999).values <= 30.0
    atomic_factors["LockTop10_Ge50"] = df["lock_top10"].fillna(0).values >= 50.0
    atomic_factors["LockTop10_Ge60"] = df["lock_top10"].fillna(0).values >= 60.0
    atomic_factors["LockBig5_Ge40"] = df["lock_big5"].fillna(0).values >= 40.0
    atomic_factors["Pry_VR_Ge15"] = df["prev_vr"].fillna(0).values >= 1.5
    atomic_factors["Pry_VR_Ge25"] = df["prev_vr"].fillna(0).values >= 2.5
    atomic_factors["Pry_RealTO_Ge15"] = df["prev_real_to"].fillna(0).values >= 0.15
    atomic_factors["Pry_RealTO_Ge25"] = df["prev_real_to"].fillna(0).values >= 0.25

    # Category 6: Capital Flow, LHB & Lhasa Filter
    atomic_factors["LHB_InstBuy_Ge1000"] = df["inst_buy_prev"].fillna(0).values >= 1000.0
    atomic_factors["LHB_InstNetBuy_Pos"] = (df["inst_buy_prev"].fillna(0).values - df["inst_sell_prev"].fillna(0).values) > 0
    atomic_factors["LHB_Youzi_Ge1"] = df["youzi_cnt_prev"].fillna(0).values >= 1
    atomic_factors["LHB_Quant_Ge1"] = df["quant_cnt_prev"].fillna(0).values >= 1
    atomic_factors["LHB_Lhasa_Lt2"] = df["lhasa_cnt_prev"].fillna(0).values <= 1
    atomic_factors["LHB_LhasaShare_Lt15"] = df["lhasa_sh_prev"].fillna(0).values <= 0.15
    atomic_factors["LHB_LhasaShare_Lt25"] = df["lhasa_sh_prev"].fillna(0).values <= 0.25

    # Category 7: Announcements, Notices & Risk Exclusion
    atomic_factors["Notice_Buyback90"] = df["n_buyback90"].fillna(False).values
    atomic_factors["Notice_Win90"] = df["n_win90"].fillna(False).values
    atomic_factors["Notice_Good7"] = df["n_good7"].fillna(False).values
    atomic_factors["Notice_NoPoison"] = (~df["n_poison90"].fillna(False).values) & (~df["n_del90"].fillna(False).values) & (~df["n_inv90"].fillna(False).values)
    atomic_factors["Notice_NoLoss90"] = ~df["n_los90"].fillna(False).values
    atomic_factors["Notice_NoReduce90"] = ~df["n_red90"].fillna(False).values

    # Category 8: 09:25 Macro & Auction Sentiment Sensors
    atomic_factors["MktOpen_ZT_Ge10"] = df["mkt_open_zt_0925"].fillna(0).values >= 10
    atomic_factors["MktOpen_ZT_Ge15"] = df["mkt_open_zt_0925"].fillna(0).values >= 15
    atomic_factors["MktOpen_DT_Lt10"] = df["mkt_open_dt_0925"].fillna(99).values <= 10
    atomic_factors["MktOpen_DT_Lt15"] = df["mkt_open_dt_0925"].fillna(99).values <= 15
    atomic_factors["MktOpen_Avg_Ge_neg05"] = df["mkt_open_avg_0925"].fillna(-1).values >= -0.005
    atomic_factors["Mkt_CSI300_Ret20_Pos"] = df["csi300_ret20"].fillna(0).values > 0
    atomic_factors["Mkt_CSI300_Ret5_Pos"] = df["csi300_ret5"].fillna(0).values > 0
    atomic_factors["Mkt_SealRate_Prev_Ge70"] = df["mkt_seal_rate_prev"].fillna(0).values >= 0.70

    # Test all factors across all 10 exits for E8_nextday_w2s
    catalog_rows = []
    e8_ret_dict = mat["ret"]["E8_nextday_w2s"]
    exits = mat["exits"]

    for fname, mask in atomic_factors.items():
        for ex in exits:
            r_arr = e8_ret_dict[ex]
            valid_r = ~np.isnan(r_arr)
            m_is = mask & is_mask & valid_r
            m_oos = mask & oos_mask & valid_r
            n_is = int(m_is.sum())
            n_oos = int(m_oos.sum())
            if n_is < 10:
                continue

            r_is = r_arr[m_is]
            r_oos = r_arr[m_oos]
            wr_is = float((r_is > 0).mean() * 100.0)
            mean_is = float(r_is.mean() * 100.0)
            pos_is = float(r_is[r_is > 0].mean()) if (r_is > 0).sum() else 0.0
            neg_is = float(abs(r_is[r_is <= 0].mean())) if (r_is <= 0).sum() else 1.0
            po_is = float(pos_is / neg_is)

            wr_oos = float((r_oos > 0).mean() * 100.0) if n_oos else 0.0
            mean_oos = float(r_oos.mean() * 100.0) if n_oos else 0.0
            pos_oos = float(r_oos[r_oos > 0].mean()) if n_oos and (r_oos > 0).sum() else 0.0
            neg_oos = float(abs(r_oos[r_oos <= 0].mean())) if n_oos and (r_oos <= 0).sum() else 1.0
            po_oos = float(pos_oos / neg_oos) if n_oos else 0.0

            catalog_rows.append({
                "factor_name": fname,
                "exit_mode": ex,
                "is_n": n_is, "is_wr_pct": round(wr_is, 2), "is_mean_pct": round(mean_is, 2), "is_payoff": round(po_is, 2),
                "oos_n": n_oos, "oos_wr_pct": round(wr_oos, 2), "oos_mean_pct": round(mean_oos, 2), "oos_payoff": round(po_oos, 2),
                "dual_positive": bool(mean_is > 0 and mean_oos > 0),
                "score": round(wr_is * max(mean_is, 0) * (max(mean_oos, 0.01)), 2),
            })

    catalog_df = pd.DataFrame(catalog_rows).sort_values("score", ascending=False)
    catalog_path = f"{P5_DIR}/s3_factor_catalog.csv"
    catalog_df.to_csv(catalog_path, index=False, encoding="utf-8-sig")
    print(f"  [+] Saved {len(catalog_df):,} factor-exit combinations to {catalog_path} in {time.time()-t0:.2f}s")
    return atomic_factors, catalog_df


def run_task2_pairwise_synergies(df, mat, atomic_factors):
    t0 = time.time()
    print("[4/5] Task 2: Running cross-entry pairwise synergy grid across E8, E6, E5, E1...")
    non_st = (~df["is_st_or_delist"].values) & (df["pre_c"].values >= 2.0)
    is_mask = (df["dt_str"].values < "2025-01-01") & non_st
    oos_mask = (df["dt_str"].values >= "2025-01-01") & non_st

    target_entries = [
        ("E8_nextday_w2s", "X7"),
        ("E8_nextday_w2s", "X5"),
        ("E8_nextday_w2s", "X10"),
        ("E8_variant_b_rightside", "X7"),
        ("E6_tail1457_yang", "X5"),
        ("E6_tail1457_yang", "X7"),
        ("E5_tail1457_all", "X5"),
        ("E1_opendt_lift15", "X10"),
    ]

    synergy_list = []
    factor_names = list(atomic_factors.keys())
    pairs = list(itertools.combinations(factor_names, 2))
    print(f"  Scanning {len(pairs):,} factor pairs across {len(target_entries)} execution combinations...")

    for ename, ex in target_entries:
        if ename not in mat["ret"] or ex not in mat["ret"][ename]:
            continue
        r_arr = mat["ret"][ename][ex]
        valid_r = ~np.isnan(r_arr)

        for f1, f2 in pairs:
            # Skip mutually exclusive or identical category duplicates
            if f1.startswith("Cat1") and f2.startswith("Cat2"):
                continue
            if f1.startswith("Open_") and f2.startswith("Open_"):
                continue
            if f1.startswith("Bias10") and f2.startswith("Bias10"):
                continue

            m_pair = atomic_factors[f1] & atomic_factors[f2]
            m_is = m_pair & is_mask & valid_r
            n_is = int(m_is.sum())
            if n_is < 20:
                continue

            r_is = r_arr[m_is]
            wr_is = float((r_is > 0).mean() * 100.0)
            mean_is = float(r_is.mean() * 100.0)
            pos_is = float(r_is[r_is > 0].mean()) if (r_is > 0).sum() else 0.0
            neg_is = float(abs(r_is[r_is <= 0].mean())) if (r_is <= 0).sum() else 1.0
            po_is = float(pos_is / neg_is)

            # Strict IS filters: WR >= 65%, Mean >= 3.0%, Payoff >= 1.2
            if wr_is < 65.0 or mean_is < 3.0 or po_is < 1.10:
                continue

            m_oos = m_pair & oos_mask & valid_r
            n_oos = int(m_oos.sum())
            r_oos = r_arr[m_oos]
            wr_oos = float((r_oos > 0).mean() * 100.0) if n_oos else 0.0
            mean_oos = float(r_oos.mean() * 100.0) if n_oos else 0.0
            pos_oos = float(r_oos[r_oos > 0].mean()) if n_oos and (r_oos > 0).sum() else 0.0
            neg_oos = float(abs(r_oos[r_oos <= 0].mean())) if n_oos and (r_oos <= 0).sum() else 1.0
            po_oos = float(pos_oos / neg_oos) if n_oos else 0.0

            # Combined ranking score prioritizing dual stability and high mean return
            synergy_score = round(wr_is * mean_is * (wr_oos if wr_oos > 50 else 30.0) * (max(mean_oos, 0.5)), 2)

            synergy_list.append({
                "entry": ename,
                "exit": ex,
                "factor_1": f1,
                "factor_2": f2,
                "pair_name": f"{f1} + {f2}",
                "is_n": n_is, "is_wr_pct": round(wr_is, 2), "is_mean_pct": round(mean_is, 2), "is_payoff": round(po_is, 2),
                "oos_n": n_oos, "oos_wr_pct": round(wr_oos, 2), "oos_mean_pct": round(mean_oos, 2), "oos_payoff": round(po_oos, 2),
                "oos_profitable": bool(mean_oos > 0),
                "synergy_score": synergy_score,
            })

    # Sort and pick top 100
    synergy_df = pd.DataFrame(synergy_list).sort_values("synergy_score", ascending=False).drop_duplicates(subset=["entry", "pair_name"]).reset_index(drop=True)
    top100_df = synergy_df.head(100)
    top100_path = f"{P5_DIR}/s3_interaction_top100.csv"
    top100_df.to_csv(top100_path, index=False, encoding="utf-8-sig")
    print(f"  [+] Saved Top 100 Pairwise Synergies to {top100_path} in {time.time()-t0:.2f}s")
    return top100_df


def main():
    t_start = time.time()
    df, cb, mat = load_master_and_bars()
    df = compute_pit_micro_features(df, cb)
    mat = simulate_option_b_returns(df, cb, mat)
    atomic_factors, catalog_df = run_task1_factor_catalog(df, mat)
    top100_df = run_task2_pairwise_synergies(df, mat, atomic_factors)
    print(f"[Done] Task 1 & Task 2 completed successfully in {time.time()-t_start:.1f}s!")


if __name__ == "__main__":
    main()

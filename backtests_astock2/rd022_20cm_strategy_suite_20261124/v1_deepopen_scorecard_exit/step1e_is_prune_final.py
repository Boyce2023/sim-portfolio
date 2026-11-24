#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 1e (IS-ONLY <= 2024-08-31):
Test clean orthogonal pruning & integer weight calibration strictly on IS.
"""
import sys
import numpy as np
import pandas as pd
from step1_is_hardgate_and_factor_scan import sim_t2_strict, one_slot_stats

sys.dont_write_bytecode = True
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"


def build_v1_candidate(d: pd.DataFrame, variant: str = "A") -> pd.DataFrame:
    f = pd.DataFrame(index=d.index)
    # Dim 1: Chips & Free Float
    f["C01_lock_top10_ge40"] = np.where(d["lock_top10"].fillna(0.0) >= 40.0, 6, 0)
    if variant == "A":
        f["C02_rfmcap_le20"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    else:
        f["C02_rfmcap_le20_gt50"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 4, np.where(d["real_free_mcap"].fillna(0.0) > 40.0, -4, 0))

    # Dim 2: Position, Open Gap, Abn Space, ZT Microstructure
    f["P03_open_sweet_vs_nuke"] = np.where(d["f1_o_pct"] < -0.080, -12, np.where(d["f1_o_pct"].between(-0.065, -0.030), 5, 0))
    f["P04_bias20_le12"] = np.where(d["bias20"].fillna(1.0) <= 0.12, 5, 0)
    f["P05_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
    f["P06_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
    if variant == "A":
        f["P07_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -7, 0)
    else:
        f["P07_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -6, 0)
        f["P07b_zt_early_le945_pen"] = np.where(d["zt_hhmm"] <= 945, -5, 0)

    # Dim 3: LHB Capital Seats
    f["L08_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 6, 0)
    if variant == "B":
        f["L08b_lhasa_panic_pos"] = np.where(d["lhb_lh_net_pos"].fillna(0) == 1, 4, 0)
    f["L09_quant_noinst_pen"] = np.where((d["lhb_quant"].fillna(0) >= 1) & (d["lhb_inst_net"].fillna(0.0) <= 0.0), -6, 0)
    f["L10_surf_yz_pen"] = np.where((d["lhb_surf"].fillna(0) == 1) & (d["lhb_lh_net_pos"].fillna(0) == 0), -5, 0)

    # Dim 4: Theme & 09:25 Market Sentiment
    f["M11_mkt10_zt_gt70"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 7, 0)
    f["M12_kpl_20crowd_pen"] = np.where(d["kpl_20zt"].fillna(0) >= 3, -5, 0)
    f["M13_peers20_nuke_pen"] = np.where(d["f1_mkt20_prev1b_open"].fillna(0.0) < -0.015, -7, 0)
    f["M14_yizi20_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)

    # Dim 5: Community & Announcements (<09:00)
    f["I15_xq_pre_ge1_pen"] = np.where(d["xq_t1_0900"].fillna(0) >= 1, -12, 0)
    f["I16_earn_pos_sellnews_pen"] = np.where(d["cat_earn_pos_3d"].fillna(0) == 1, -10, 0)

    # Dim 6: Calendar
    f["T17_monday_pen"] = np.where(d["f1_weekday"] == 0, -10, 0)
    if variant == "B":
        f["T18_jan_apr_pen"] = np.where(d["f1_month"].isin(["01", "04"]), -4, 0)
    return f


def run_eval(sub: pd.DataFrame, fm: pd.DataFrame, label: str):
    sc = 70.0 + fm.sum(axis=1).to_numpy()
    sub = sub.copy()
    sub["score"] = sc
    print(f"\n==================== [IS ONLY] {label} ({fm.shape[1]} items) ====================")
    for th in [70, 72, 74, 75, 76, 78, 80, 82, 85, 88]:
        st = one_slot_stats(sim_t2_strict(sub[sub["score"] >= th]))
        print(f"  th>={th:2d} | raw={st['raw_n']:3d} 1sN={st['n1']:3d} WR={st['wr']:5.2f}% mn={st['mean']:+5.2f}% PO={st['po']:4.2f} 1s={st['nav1']:6.3f}x EW={st['ew']:6.3f}x MDD={st['mdd']:5.1f}%")

    tr_all = sim_t2_strict(sub)
    tr_all["score"] = sub.iloc[tr_all["idx"].values]["score"].values
    print("  --- IS Score Buckets ---")
    for lbl, lo, hi in [("<65", -999, 64.9), ("65~71", 65, 71.9), ("72~76", 72, 76.9), ("77~81", 77, 81.9), ("82~86", 82, 86.9), (">=87", 87, 999)]:
        s = tr_all[tr_all["score"].between(lo, hi)]
        st = one_slot_stats(s)
        print(f"    {lbl:6s} | raw={st['raw_n']:3d} 1sN={st['n1']:3d} WR={st['wr']:5.2f}% mn={st['mean']:+5.2f}% PO={st['po']:4.2f} 1s={st['nav1']:6.3f}x EW={st['ew']:6.3f}x")

    # LOO at th=75
    b = one_slot_stats(sim_t2_strict(sub[sub["score"] >= 75]))
    print(f"  --- IS LOO at th>=75 (Base: N={b['n1']}, WR={b['wr']}%, mn={b['mean']}%, 1s={b['nav1']}x, EW={b['ew']}x) ---")
    for col in fm.columns:
        sd_df = sub.copy()
        sd_df["score"] = sc - fm[col].to_numpy()
        sd = one_slot_stats(sim_t2_strict(sd_df[sd_df["score"] >= 75]))
        print(f"    Keep {col:24s} | d_1s={b['nav1']-sd['nav1']:+6.2f}x d_EW={b['ew']-sd['ew']:+6.2f}x d_WR={b['wr']-sd['wr']:+5.2f}pp d_mn={b['mean']-sd['mean']:+5.2f}pp")


def main():
    df = pd.read_parquet(f"{OUT_DIR}/p1_clean_candidates.parquet")
    sub = df[(df["f1_dt"] <= "2024-08-31") & df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    for var in ["A", "B"]:
        fm = build_v1_candidate(sub, var)
        run_eval(sub, fm, f"Variant {var}")


if __name__ == "__main__":
    main()

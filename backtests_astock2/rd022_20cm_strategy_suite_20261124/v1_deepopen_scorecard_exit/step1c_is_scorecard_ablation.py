#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 1c (IS-ONLY <= 2024-08-31):
Design, tune, and LOO-prune the 12-18 item pure-integer orthogonal scorecard strictly on IS.
Zero OOS peeking!
"""
import sys
import numpy as np
import pandas as pd
from step1_is_hardgate_and_factor_scan import sim_t2_strict, one_slot_stats

sys.dont_write_bytecode = True
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"


def build_candidate_factors(d: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Construct orthogonal integer factor matrix covering all 6 dimensions (pure IS physics):
    Base score = 70
    """
    feats = pd.DataFrame(index=d.index)
    # Dim 1: Chips & Liquidity
    feats["F01_lock_top10_ge40"] = np.where(d["lock_top10"].fillna(0.0) >= 40.0, 6, 0)
    feats["F02_rfmcap_gt30_pen"] = np.where(d["real_free_mcap"].fillna(999.0) > 30.0, -6, 0)
    feats["F03_vol_ratio5_lt18"] = np.where(d["vol_ratio5"].fillna(99.0) < 1.8, 5, 0)

    # Dim 2: Price/Position, Abn Space, ZT Tape
    feats["F04_open_sweet_30_65"] = np.where(d["f1_o_pct"].between(-0.065, -0.030), 5, 0)
    feats["F05_open_nuke_lt80"] = np.where(d["f1_o_pct"] < -0.080, -12, 0)
    feats["F06_bias20_le12"] = np.where(d["bias20"].fillna(1.0) <= 0.12, 8, 0)
    feats["F07_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 5, 0)
    feats["F08_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
    feats["F09_zt_early_trap_le945"] = np.where(d["zt_hhmm"] <= 945, -8, 0)
    feats["F10_zt_late_ge1400"] = np.where((d["zt_hhmm"] >= 1400) & (d["zt_hhmm"] < 9999), 5, 0)
    feats["F11_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -6, 0)

    # Dim 3: LHB Capital Seats
    feats["F12_lhb_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 7, 0)
    feats["F13_lhb_lhasa_net_pos"] = np.where(d["lhb_lh_net_pos"].fillna(0) == 1, 7, 0)
    feats["F14_lhb_quant_noinst_pen"] = np.where((d["lhb_quant"].fillna(0) >= 1) & (d["lhb_inst_net"].fillna(0.0) <= 0.0), -6, 0)
    feats["F15_lhb_surf_yz_pen"] = np.where((d["lhb_surf"].fillna(0) == 1) & (d["lhb_lh_net_pos"].fillna(0) == 0), -5, 0)

    # Dim 4: Theme & Sentiment (KPL + Market + 09:25 Peers)
    feats["F16_mkt10_zt_gt70"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 8, 0)
    feats["F17_kpl_overheat_pen"] = np.where((d["kpl_elo"].fillna(100.0) >= 112.0) | (d["kpl_20zt"].fillna(0) >= 3), -6, 0)
    feats["F18_f1_peers20_nuke_pen"] = np.where(d["f1_mkt20_prev1b_open"].fillna(0.0) < -0.015, -8, 0)
    feats["F19_f1_20yizi_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -6, 0)

    # Dim 5: Community & Notices (<09:00)
    feats["F20_xq_pre_ge1_pen"] = np.where(d["xq_t1_0900"].fillna(0) >= 1, -12, 0)
    feats["F21_gb_quiet_le30"] = np.where(d["gb_t1_0900"].fillna(0) <= 30, 4, 0)
    feats["F22_earn_pos_sellnews_pen"] = np.where(d["cat_earn_pos_3d"].fillna(0) == 1, -10, 0)

    # Dim 6: Calendar
    feats["F23_monday_pen"] = np.where(d["f1_weekday"] == 0, -10, 0)
    feats["F24_jan_apr_pen"] = np.where(d["f1_month"].isin(["01", "04"]), -6, 0)

    # Optional test factors for ablation
    feats["F25_star_688"] = np.where(d["is_chinext"] == 0, 4, 0)
    feats["F26_ir10d_ge1"] = np.where(d["ir_10d_0900"].fillna(0) >= 1, 4, 0)
    return feats, {c: int(feats[c][feats[c] != 0].iloc[0]) if (feats[c] != 0).any() else 0 for c in feats.columns}


def eval_score_grid(df_is: pd.DataFrame, sc: np.ndarray, thresholds: list[float]) -> list[dict]:
    d = df_is.copy()
    d["score"] = sc
    rows = []
    for th in thresholds:
        sub = d[d["score"] >= th]
        tr = sim_t2_strict(sub)
        st = one_slot_stats(tr)
        st["th"] = th
        rows.append(st)
    return rows


def main():
    df = pd.read_parquet(f"{OUT_DIR}/p1_clean_candidates.parquet")
    df_is_all = df[df["f1_dt"] <= "2024-08-31"].copy().reset_index(drop=True)

    # 1. Compare hard gate skeletons WITH full candidate scorecard on IS!
    print("=== [IS ONLY] HARD SKELETON COMPARISON WITH SCORECARD ===")
    skels = [
        ("[-12,-2] mkt20<16", df_is_all["f1_o_pct"].between(-0.12, -0.02) & (df_is_all["mkt20_zt_cnt"] < 16)),
        ("[-10,-2.5] mkt20<16", df_is_all["f1_o_pct"].between(-0.10, -0.025) & (df_is_all["mkt20_zt_cnt"] < 16)),
        ("[-10,-3.0] mkt20<16", df_is_all["f1_o_pct"].between(-0.10, -0.030) & (df_is_all["mkt20_zt_cnt"] < 16)),
        ("[-10,-3.5] mkt20<16", df_is_all["f1_o_pct"].between(-0.10, -0.035) & (df_is_all["mkt20_zt_cnt"] < 16)),
        ("[-10,-3.0] all_mkt(soft-15)", df_is_all["f1_o_pct"].between(-0.10, -0.030)),
    ]
    for nm, m in skels:
        sub = df_is_all[m].copy().reset_index(drop=True)
        fm, _ = build_candidate_factors(sub)
        sc = 70.0 + fm.sum(axis=1).to_numpy()
        if "soft" in nm:
            sc += np.where(sub["mkt20_zt_cnt"] >= 16, -15.0, 0.0)
        res = eval_score_grid(sub, sc, [70, 75, 80, 85, 90])
        line = " | ".join(f">={int(r['th'])}: N={r['raw_n']}/{r['n1']} WR={r['wr']:.1f}% 1s={r['nav1']:.2f}x EW={r['ew']:.2f}x MDD={r['mdd']:.1f}%" for r in res)
        print(f"  {nm:26s} || {line}")

    # 2. Detailed IS Leave-One-Out Ablation on [-10%, -3.0%] & mkt20_zt_cnt < 16
    core = df_is_all[df_is_all["f1_o_pct"].between(-0.10, -0.030) & (df_is_all["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    fm, weights = build_candidate_factors(core)
    sc_full = 70.0 + fm.sum(axis=1).to_numpy()

    # Print correlation among active candidate factors (|r| >= 0.20)
    bin_fm = (fm != 0).astype(int)
    corr = bin_fm.corr()
    print("\n=== [IS ONLY] PAIRWISE CORRELATIONS |r| >= 0.20 ===")
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            v = corr.iloc[i, j]
            if abs(v) >= 0.20:
                print(f"  {cols[i]:26s} <-> {cols[j]:26s} : r={v:+.3f}")

    # LOO Ablation on IS at threshold >= 76 and >= 80
    print("\n=== [IS ONLY] LEAVE-ONE-OUT ABLATION (Core [-10%,-3.0%], mkt20<16) ===")
    for th_eval in [76, 80]:
        base_st = eval_score_grid(core, sc_full, [th_eval])[0]
        print(f"\n  --- Threshold >= {th_eval} Baseline: N={base_st['raw_n']}/{base_st['n1']} WR={base_st['wr']:.2f}% mn={base_st['mean']:+.2f}% PO={base_st['po']:.2f} 1s={base_st['nav1']:.3f}x EW={base_st['ew']:.3f}x MDD={base_st['mdd']:.1f}% ---")
        for col in fm.columns:
            sc_drop = sc_full - fm[col].to_numpy()
            st_d = eval_score_grid(core, sc_drop, [th_eval])[0]
            # Delta = Baseline - Without_Factor (positive means keeping the factor HELPS!)
            d_1s = base_st["nav1"] - st_d["nav1"]
            d_ew = base_st["ew"] - st_d["ew"]
            d_wr = base_st["wr"] - st_d["wr"]
            d_mn = base_st["mean"] - st_d["mean"]
            d_mdd = st_d["mdd"] - base_st["mdd"]
            print(f"  Drop {col:26s} (w={weights[col]:+3d}, hits={(fm[col]!=0).sum():3d}) | "
                  f"Keep delta: 1s={d_1s:+6.2f}x EW={d_ew:+6.2f}x WR={d_wr:+5.2f}pp mn={d_mn:+5.2f}pp | no_fac: N={st_d['n1']:3d} 1s={st_d['nav1']:6.2f}x EW={st_d['ew']:6.2f}x")

    # 3. Check IS score buckets granularity for 24-factor vs pruned subsets
    print("\n=== [IS ONLY] SCORE BUCKET MONOTONICITY (26-factor full) ===")
    core_sc = core.copy()
    core_sc["score"] = sc_full
    tr_all = sim_t2_strict(core_sc)
    tr_all["score"] = core_sc.iloc[tr_all["idx"].values]["score"].values
    for lbl, lo, hi in [("<65", -999, 64.9), ("65~74", 65, 74.9), ("75~79", 75, 79.9), ("80~84", 80, 84.9), ("85~89", 85, 89.9), ("90~94", 90, 94.9), (">=95", 95, 999)]:
        s = tr_all[tr_all["score"].between(lo, hi)]
        if s.empty:
            continue
        st = one_slot_stats(s)
        print(f"  {lbl:8s} | raw={st['raw_n']:3d} 1sN={st['n1']:3d} WR={st['wr']:5.2f}% mn={st['mean']:+5.2f}% PO={st['po']:4.2f} 1s={st['nav1']:6.3f}x EW={st['ew']:6.3f}x")


if __name__ == "__main__":
    main()

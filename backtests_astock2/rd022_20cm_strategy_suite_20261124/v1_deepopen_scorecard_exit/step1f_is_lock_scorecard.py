#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 1f (IS-ONLY <= 2024-08-31):
Test 18-item vs 17-item vs 16-item orthogonal integer scorecard (strictly 12..18 items)
and lock exact A-tier & S-tier thresholds strictly on IS before ever touching OOS.
"""
import sys
import numpy as np
import pandas as pd
from step1_is_hardgate_and_factor_scan import sim_t2_strict, one_slot_stats

sys.dont_write_bytecode = True
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"


def build_scorecard_18(d: pd.DataFrame, drop_cols: tuple = ()) -> pd.DataFrame:
    """
    18-item pure-integer orthogonal scorecard (Base = 70), covering all 6 dimensions:
    Dim 1 (Chips, 2 items): lock_top10, real_free_mcap
    Dim 2 (Position/Micro, 5 items): open_gap, bias20, dist_3d30, zt_cnt_60d, zt_hhmm_early
    Dim 3 (LHB Capital, 4 items): inst_net_pos, lhasa_panic, quant_noinst_pen, surf_yz_pen
    Dim 4 (Theme & Sentiment, 4 items): mkt10_zt_gt70, kpl_20crowd_pen, peers20_nuke_pen, yizi20_siphon_pen
    Dim 5 (Community & Notices <09:00, 2 items): xq_pre_pen, earn_pos_sellnews_pen
    Dim 6 (Calendar, 2 items -> total 18 if dropping 1, or let's count exact!)
    Wait: 2 + 5 + 4 + 4 + 2 + 2 = 19! If we combine quant/surf OR drop bias20/dist3d30/lhasa -> 17 or 18!
    Let's test 18-item (e.g. combine surf/quant OR drop seal_ratio & test dropping 1 of bias20/lhasa/dist3d30).
    """
    f = pd.DataFrame(index=d.index)
    # Dim 1: Chips & Free Float (2 items)
    f["F01_lock_top10_ge40"] = np.where(d["lock_top10"].fillna(0.0) >= 40.0, 6, 0)
    f["F02_rfmcap_tier"] = np.where(d["real_free_mcap"].fillna(999.0) <= 20.0, 4, np.where(d["real_free_mcap"].fillna(0.0) > 40.0, -4, 0))
    # Dim 2: Position, Open, Abn Space, ZT Time (5 items)
    f["F03_open_gap_zone"] = np.where(d["f1_o_pct"] < -0.080, -12, np.where(d["f1_o_pct"].between(-0.065, -0.030), 5, 0))
    f["F04_bias20_le12"] = np.where(d["bias20"].fillna(1.0) <= 0.12, 5, 0)
    f["F05_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
    f["F06_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
    f["F07_zt_early_le945_pen"] = np.where(d["zt_hhmm"] <= 945, -6, 0)
    # Dim 3: LHB Seats (4 items)
    f["F08_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 6, 0)
    f["F09_lhasa_panic_pos"] = np.where(d["lhb_lh_net_pos"].fillna(0) == 1, 5, 0)
    f["F10_quant_noinst_pen"] = np.where((d["lhb_quant"].fillna(0) >= 1) & (d["lhb_inst_net"].fillna(0.0) <= 0.0), -6, 0)
    f["F11_surf_yz_pen"] = np.where((d["lhb_surf"].fillna(0) == 1) & (d["lhb_lh_net_pos"].fillna(0) == 0), -5, 0)
    # Dim 4: Theme & 09:25 Market Sentiment (4 items)
    f["F12_mkt10_zt_gt70"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 7, 0)
    f["F13_kpl_20crowd_pen"] = np.where(d["kpl_20zt"].fillna(0) >= 3, -5, 0)
    f["F14_peers20_nuke_pen"] = np.where(d["f1_mkt20_prev1b_open"].fillna(0.0) < -0.015, -7, 0)
    f["F15_yizi20_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)
    # Dim 5: Community & Announcements <09:00 (2 items)
    f["F16_xq_pre_ge1_pen"] = np.where(d["xq_t1_0900"].fillna(0) >= 1, -12, 0)
    f["F17_earn_pos_sellnews_pen"] = np.where(d["cat_earn_pos_3d"].fillna(0) == 1, -10, 0)
    # Dim 6: Calendar (2 items)
    f["F18_monday_pen"] = np.where(d["f1_weekday"] == 0, -10, 0)
    f["F19_jan_apr_pen"] = np.where(d["f1_month"].isin(["01", "04"]), -4, 0)

    for c in drop_cols:
        if c in f.columns:
            f = f.drop(columns=[c])
    return f


def eval_card(sub: pd.DataFrame, drop_cols: tuple, name: str):
    fm = build_scorecard_18(sub, drop_cols)
    sc = 70.0 + fm.sum(axis=1).to_numpy()
    d = sub.copy()
    d["score"] = sc
    print(f"\n==================== [IS ONLY] {name} ({fm.shape[1]} items) ====================")
    for th in [74, 75, 76, 77, 78, 80, 84, 86, 88]:
        st = one_slot_stats(sim_t2_strict(d[d["score"] >= th]))
        print(f"  th>={th:2d} | raw={st['raw_n']:3d} 1sN={st['n1']:3d} WR={st['wr']:5.2f}% mn={st['mean']:+5.2f}% PO={st['po']:4.2f} 1s={st['nav1']:6.3f}x EW={st['ew']:6.3f}x MDD={st['mdd']:5.1f}%")
    tr_all = sim_t2_strict(d)
    tr_all["score"] = d.iloc[tr_all["idx"].values]["score"].values
    print("  --- IS Score Buckets ---")
    for lbl, lo, hi in [("<65", -999, 64.9), ("65~70", 65, 70.9), ("71~75", 71, 75.9), ("76~80", 76, 80.9), ("81~85", 81, 85.9), (">=86", 86, 999)]:
        st = one_slot_stats(tr_all[tr_all["score"].between(lo, hi)])
        print(f"    {lbl:6s} | raw={st['raw_n']:3d} 1sN={st['n1']:3d} WR={st['wr']:5.2f}% mn={st['mean']:+5.2f}% PO={st['po']:4.2f} 1s={st['nav1']:6.3f}x EW={st['ew']:6.3f}x")
    b = one_slot_stats(sim_t2_strict(d[d["score"] >= 76]))
    print(f"  --- IS LOO at th>=76 (Base: N={b['n1']}, WR={b['wr']}%, mn={b['mean']}%, 1s={b['nav1']}x, EW={b['ew']}x) ---")
    for col in fm.columns:
        dd = d.copy(); dd["score"] = sc - fm[col].to_numpy()
        sd = one_slot_stats(sim_t2_strict(dd[dd["score"] >= 76]))
        print(f"    Keep {col:24s} | d_1s={b['nav1']-sd['nav1']:+6.2f}x d_EW={b['ew']-sd['ew']:+6.2f}x d_WR={b['wr']-sd['wr']:+5.2f}pp d_mn={b['mean']-sd['mean']:+5.2f}pp")


def main():
    df = pd.read_parquet(f"{OUT_DIR}/p1_clean_candidates.parquet")
    sub = df[(df["f1_dt"] <= "2024-08-31") & df["f1_o_pct"].between(-0.10, -0.030) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    eval_card(sub, (), "19-item base (no seal_ratio)")
    eval_card(sub, ("F04_bias20_le12",), "18-item (drop bias20)")
    eval_card(sub, ("F09_lhasa_panic_pos",), "18-item (drop lhasa)")
    eval_card(sub, ("F04_bias20_le12", "F09_lhasa_panic_pos"), "17-item (drop bias20 + lhasa)")
    eval_card(sub, ("F04_bias20_le12", "F05_dist3d30_ge10"), "17-item (drop bias20 + dist3d30)")


if __name__ == "__main__":
    main()

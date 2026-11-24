#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 1d:
1. Check yearly feature coverage (2021~2026) on clean pool (no returns checked on OOS!) to detect crawler/data drift (like Guba!).
2. Refine & lock 16-item pure-integer orthogonal scorecard strictly on IS (<= 2024-08-31).
"""
import sys
import numpy as np
import pandas as pd
from step1_is_hardgate_and_factor_scan import sim_t2_strict, one_slot_stats

sys.dont_write_bytecode = True
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"


def check_yearly_feature_coverage(df: pd.DataFrame):
    d = df[df["f1_o_pct"].between(-0.10, -0.025) & (df["mkt20_zt_cnt"] < 16)].copy()
    d["yr"] = d["f1_dt"].str[:4]
    print("=== YEARLY FEATURE COVERAGE / SCRAPER DRIFT AUDIT (NO RETURNS) ===")
    cols_check = [
        ("gb_le30%", lambda x: x["gb_t1_0900"] <= 30),
        ("gb_med", "median_gb"),
        ("xq_ge1%", lambda x: x["xq_t1_0900"] >= 1),
        ("lhb_has%", lambda x: x["lhb_has"] == 1),
        ("inst_pos%", lambda x: x["lhb_inst_net"] > 0),
        ("lh_pos%", lambda x: x["lhb_lh_net_pos"] == 1),
        ("lock_na%", lambda x: x["lock_top10"].isna()),
        ("kpl_in%", lambda x: x["kpl_in"] == 1),
        ("cat_ep%", lambda x: x["cat_earn_pos_3d"] == 1),
        ("mkt10>70%", lambda x: x["mkt10_zt_cnt"] > 70),
    ]
    for yr, grp in d.groupby("yr"):
        parts = [f"N={len(grp):3d}"]
        for nm, fn in cols_check:
            if fn == "median_gb":
                parts.append(f"gb_med={grp['gb_t1_0900'].median():4.0f}")
            else:
                parts.append(f"{nm}={fn(grp).mean()*100:4.1f}%")
        print(f"  {yr}: " + " | ".join(parts))


def build_clean_16_factors(d: pd.DataFrame) -> pd.DataFrame:
    """
    Clean 16-item pure-integer orthogonal scorecard (Base = 70):
    All features 100% consistent coverage 2021~2026, strictly <= T+1 09:25 PIT, zero Guba drift.
    """
    f = pd.DataFrame(index=d.index)
    # 1. 筹码与自由流通 (Dim 1: Chips)
    f["C01_lock_top10_ge40"] = np.where(d["lock_top10"].fillna(0.0) >= 40.0, 6, 0)
    f["C02_rfmcap_gt30_pen"] = np.where(d["real_free_mcap"].fillna(999.0) > 30.0, -6, 0)
    # 2. 量价位置、异动空间与封板微观 (Dim 2: Price/Position/Micro)
    f["P03_open_sweet_vs_nuke"] = np.where(d["f1_o_pct"] < -0.080, -12, np.where(d["f1_o_pct"].between(-0.065, -0.030), 5, 0))
    f["P04_bias20_le12"] = np.where(d["bias20"].fillna(1.0) <= 0.12, 8, 0)
    f["P05_dist3d30_ge10"] = np.where(d["dist_3d30"].fillna(0.0) >= 0.10, 4, 0)
    f["P06_zt60d_ge2"] = np.where(d["zt_cnt_60d"].fillna(0) >= 2, 5, 0)
    f["P07_zt_time_early_vs_late"] = np.where(d["zt_hhmm"] <= 945, -8, np.where((d["zt_hhmm"] >= 1400) & (d["zt_hhmm"] < 9999), 5, 0))
    f["P08_seal_ratio_ge10_pen"] = np.where(d["zt_seal_ratio"].fillna(0.0) >= 0.10, -6, 0)
    # 3. 龙虎榜资金席位 (Dim 3: LHB Capital)
    f["L09_inst_net_pos"] = np.where(d["lhb_inst_net"].fillna(0.0) > 0.0, 7, 0)
    f["L10_lhasa_panic_pos"] = np.where(d["lhb_lh_net_pos"].fillna(0) == 1, 7, 0)
    f["L11_quant_noinst_pen"] = np.where((d["lhb_quant"].fillna(0) >= 1) & (d["lhb_inst_net"].fillna(0.0) <= 0.0), -6, 0)
    f["L12_surf_yz_pen"] = np.where((d["lhb_surf"].fillna(0) == 1) & (d["lhb_lh_net_pos"].fillna(0) == 0), -5, 0)
    # 4. 题材与板块情绪 (Dim 4: Theme & 09:25 Peers)
    f["M13_mkt10_zt_gt70"] = np.where(d["mkt10_zt_cnt"].fillna(0) > 70, 8, 0)
    f["M14_kpl_overheat_pen"] = np.where((d["kpl_elo"].fillna(100.0) >= 112.0) | (d["kpl_20zt"].fillna(0) >= 3), -6, 0)
    f["M15_peers20_nuke_pen"] = np.where(d["f1_mkt20_prev1b_open"].fillna(0.0) < -0.015, -8, 0)
    f["M16_yizi20_siphon_pen"] = np.where(d["f1_mkt20_0925_zt"].fillna(0) >= 1, -5, 0)
    # 5. 社区与公告 (Dim 5: Stealth & Notices <09:00)
    f["I17_xq_pre_ge1_pen"] = np.where(d["xq_t1_0900"].fillna(0) >= 1, -12, 0)
    f["I18_earn_pos_sellnews_pen"] = np.where(d["cat_earn_pos_3d"].fillna(0) == 1, -10, 0)
    # 6. 日历 (Dim 6: Calendar)
    f["T19_monday_pen"] = np.where(d["f1_weekday"] == 0, -10, 0)
    f["T20_jan_apr_pen"] = np.where(d["f1_month"].isin(["01", "04"]), -6, 0)
    return f


def main():
    df = pd.read_parquet(f"{OUT_DIR}/p1_clean_candidates.parquet")
    check_yearly_feature_coverage(df)

    df_is = df[(df["f1_dt"] <= "2024-08-31") & df["f1_o_pct"].between(-0.10, -0.025) & (df["mkt20_zt_cnt"] < 16)].copy().reset_index(drop=True)
    # Compare open [-10, -2.5] vs [-10, -3.0] on IS with Clean 16/20-item card, and also test dropping weak/collinear items!
    for w_lbl, mask_w in [
        ("[-10,-2.5] mkt20<16", df_is["f1_o_pct"].between(-0.10, -0.025)),
        ("[-10,-3.0] mkt20<16", df_is["f1_o_pct"].between(-0.10, -0.030)),
    ]:
        sub = df_is[mask_w].copy().reset_index(drop=True)
        fm = build_clean_16_factors(sub)
        sc = 70.0 + fm.sum(axis=1).to_numpy()
        sub["score"] = sc
        print(f"\n=== [IS ONLY] CLEAN 20-ITEM CARD on {w_lbl} ===")
        for th in [70, 74, 75, 76, 78, 80, 84, 88]:
            tr = sim_t2_strict(sub[sub["score"] >= th])
            st = one_slot_stats(tr)
            print(f"  th>={th:2d} | raw={st['raw_n']:3d} 1sN={st['n1']:3d} WR={st['wr']:5.2f}% mn={st['mean']:+5.2f}% PO={st['po']:4.2f} 1s={st['nav1']:6.3f}x EW={st['ew']:6.3f}x MDD={st['mdd']:5.1f}%")

        # Bucket monotonicity on IS
        tr_all = sim_t2_strict(sub)
        tr_all["score"] = sub.iloc[tr_all["idx"].values]["score"].values
        print(f"  --- IS Score Buckets ({w_lbl}) ---")
        for lbl, lo, hi in [("<65", -999, 64.9), ("65~73", 65, 73.9), ("74~79", 74, 79.9), ("80~85", 80, 85.9), ("86~91", 86, 91.9), (">=92", 92, 999)]:
            s = tr_all[tr_all["score"].between(lo, hi)]
            st = one_slot_stats(s)
            print(f"    {lbl:6s} | raw={st['raw_n']:3d} 1sN={st['n1']:3d} WR={st['wr']:5.2f}% mn={st['mean']:+5.2f}% PO={st['po']:4.2f} 1s={st['nav1']:6.3f}x EW={st['ew']:6.3f}x")

    # Test IS LOO Ablation on [-10,-3.0] at th>=75 and th>=76 to prune to cleanest 15-17 orthogonal items!
    sub = df_is[df_is["f1_o_pct"].between(-0.10, -0.030)].copy().reset_index(drop=True)
    fm = build_clean_16_factors(sub)
    sc0 = 70.0 + fm.sum(axis=1).to_numpy()
    sub["score"] = sc0
    base_st = one_slot_stats(sim_t2_strict(sub[sub["score"] >= 75]))
    print(f"\n=== [IS LOO ABLATION on [-10,-3.0] th>=75] Base: N={base_st['n1']} WR={base_st['wr']}% mn={base_st['mean']}% 1s={base_st['nav1']}x EW={base_st['ew']}x ===")
    for col in fm.columns:
        sub_d = sub.copy()
        sub_d["score"] = sc0 - fm[col].to_numpy()
        sd = one_slot_stats(sim_t2_strict(sub_d[sub_d["score"] >= 75]))
        print(f"  Keep {col:26s} | d_1s={base_st['nav1']-sd['nav1']:+6.2f}x d_EW={base_st['ew']-sd['ew']:+6.2f}x d_WR={base_st['wr']-sd['wr']:+5.2f}pp d_mn={base_st['mean']-sd['mean']:+5.2f}pp (without: N={sd['n1']}, 1s={sd['nav1']:.2f}x)")


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 1b (IS-ONLY <= 2024-08-31): Fine inflection points, KPL/notice/chip buckets, and factor correlation matrix."""
import sys
import numpy as np
import pandas as pd
from step1_is_hardgate_and_factor_scan import sim_t2_strict, one_slot_stats

sys.dont_write_bytecode = True
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/v1_deepopen_scorecard_exit"


def bucket_report(sub: pd.DataFrame, col: str, bins: list, labels: list | None = None):
    print(f"\n--- IS Bucket: {col} ---")
    s = pd.cut(sub[col], bins=bins, labels=labels, include_lowest=True)
    for b, grp in sub.groupby(s, observed=False):
        if len(grp) == 0:
            continue
        r = grp["net2"].to_numpy()
        wr = (r > 0).mean() * 100.0
        mn = r.mean() * 100.0
        ew = np.prod(1.0 + grp.groupby("buy_date")["net2"].mean().to_numpy())
        print(f"  {str(b):20s} | N={len(r):4d} WR={wr:5.1f}% mn={mn:+6.2f}% ew={ew:6.2f}x")


def main():
    df = pd.read_parquet(f"{OUT_DIR}/p1_clean_candidates.parquet")
    df_is = df[(df["f1_dt"] <= "2024-08-31") & df["f1_o_pct"].between(-0.12, -0.02)].copy().reset_index(drop=True)
    df_is["score"] = -df_is["f1_o_pct"] * 100.0
    tr = sim_t2_strict(df_is)
    sub = df_is.iloc[tr["idx"].values].copy().reset_index(drop=True)
    sub["net2"] = tr["net_ret"].values
    sub["buy_date"] = tr["buy_date"].values

    bucket_report(sub, "f1_o_pct", [-0.12, -0.09, -0.08, -0.065, -0.05, -0.035, -0.028, -0.02])
    bucket_report(sub, "mkt20_zt_cnt", [-1, 3, 6, 10, 15, 25, 999])
    bucket_report(sub, "mkt10_zt_cnt", [-1, 30, 50, 70, 95, 999])
    bucket_report(sub, "lock_top10", [0, 30, 40, 50, 100])
    bucket_report(sub, "real_free_mcap", [0, 15, 30, 50, 9999])
    bucket_report(sub, "vol_ratio5", [0, 1.5, 2.5, 4.5, 999])
    bucket_report(sub, "real_to", [0, 15, 25, 45, 999])
    bucket_report(sub, "bias20", [-1, 0.05, 0.12, 0.22, 99])
    bucket_report(sub, "zt_hhmm", [0, 945, 1005, 1130, 1400, 1500, 9999])
    bucket_report(sub, "zt_seal_ratio", [0, 0.02, 0.05, 0.10, 99])
    bucket_report(sub, "zt_obc", [-1, 0, 1, 3, 99])
    bucket_report(sub, "kpl_elo", [0, 100, 108, 118, 135, 999])
    bucket_report(sub, "kpl_10zt", [-1, 0, 2, 5, 999])
    bucket_report(sub, "kpl_20zt", [-1, 0, 1, 3, 999])
    bucket_report(sub, "lhb_inst_net", [-1e9, -1000, -1, 0, 1500, 1e9])
    bucket_report(sub, "lhb_lh_cnt", [-1, 0, 1, 2, 10])
    bucket_report(sub, "f1_mkt20_prev1b_open", [-0.25, -0.025, -0.01, 0.01, 0.25])
    bucket_report(sub, "csi_5d", [-0.5, -0.03, -0.01, 0.015, 0.5])
    bucket_report(sub, "gb_t1_0900", [-1, 10, 30, 80, 99999])

    # Also check lhb_lh_cnt == 1 vs >=2, lhb_lh_net_pos, and kpl_in==0 vs kpl_elo buckets
    print("\n--- Special discrete checks on IS [-12,-2] ---")
    checks = {
        "lhb_has==0": sub["lhb_has"] == 0,
        "lhb_lh_cnt==0 (when has)": (sub["lhb_has"] == 1) & (sub["lhb_lh_cnt"] == 0),
        "lhb_lh_cnt==1": sub["lhb_lh_cnt"] == 1,
        "lhb_lh_cnt>=2": sub["lhb_lh_cnt"] >= 2,
        "lhb_lh_net_pos==1": sub["lhb_lh_net_pos"] == 1,
        "lhb_surf==1 & lh_net_pos==0": (sub["lhb_surf"] == 1) & (sub["lhb_lh_net_pos"] == 0),
        "lhb_quant>=1 & inst<=0": (sub["lhb_quant"] >= 1) & (sub["lhb_inst_net"] <= 0),
        "kpl_in==0": sub["kpl_in"] == 0,
        "kpl_in==1 & elo<110": (sub["kpl_in"] == 1) & (sub["kpl_elo"] < 110),
        "kpl_in==1 & elo>=110": (sub["kpl_in"] == 1) & (sub["kpl_elo"] >= 110),
        "kpl_in==1 & 10zt>=5": (sub["kpl_in"] == 1) & (sub["kpl_10zt"] >= 5),
        "cat_clarify_3d==1": sub["cat_clarify_3d"] == 1,
        "cat_bb_5d_0900==1": sub["cat_bb_5d_0900"] == 1,
        "cat_cont_3d_0900==1": sub["cat_cont_3d_0900"] == 1,
        "cat_ma_5d_0900==1": sub["cat_ma_5d_0900"] == 1,
        "f1_mkt20_0925_zt>=1": sub["f1_mkt20_0925_zt"] >= 1,
        "f1_mkt10_0925_zt<8": sub["f1_mkt10_0925_zt"] < 8,
    }
    for nm, m in checks.items():
        grp = sub[m]
        if len(grp) == 0:
            continue
        r = grp["net2"].to_numpy()
        ew = np.prod(1.0 + grp.groupby("buy_date")["net2"].mean().to_numpy())
        print(f"  {nm:30s} | N={len(r):4d} WR={(r>0).mean()*100:5.1f}% mn={r.mean()*100:+6.2f}% ew={ew:6.2f}x")

    # Correlation matrix among candidate orthogonal factors on IS CORE [-10,-3.0]
    core = sub[sub["f1_o_pct"].between(-0.10, -0.030)].copy()
    cand_feats = pd.DataFrame({
        "lock40": (core["lock_top10"].fillna(0) >= 40).astype(int),
        "rfmcap_le30": (core["real_free_mcap"] <= 30).astype(int),
        "volr_lt18": (core["vol_ratio5"] < 1.8).astype(int),
        "open_sweet": core["f1_o_pct"].between(-0.08, -0.04).astype(int),
        "open_nuke": (core["f1_o_pct"] < -0.08).astype(int),
        "bias20_le12": (core["bias20"] <= 0.12).astype(int),
        "dist3d_ge10": (core["dist_3d30"] >= 0.10).astype(int),
        "zt60_ge2": (core["zt_cnt_60d"] >= 2).astype(int),
        "zt_early": (core["zt_hhmm"] <= 1000).astype(int),
        "zt_late": ((core["zt_hhmm"] >= 1400) & (core["zt_hhmm"] < 9999)).astype(int),
        "seal_big": (core["zt_seal_ratio"] >= 0.10).astype(int),
        "inst_pos": (core["lhb_inst_net"] > 0).astype(int),
        "lh_net_pos": (core["lhb_lh_net_pos"] == 1).astype(int),
        "quant_noinst": ((core["lhb_quant"] >= 1) & (core["lhb_inst_net"] <= 0)).astype(int),
        "surf_yz": (core["lhb_surf"] == 1).astype(int),
        "mkt20_ge16": (core["mkt20_zt_cnt"] >= 16).astype(int),
        "mkt10_gt70": (core["mkt10_zt_cnt"] > 70).astype(int),
        "peers20_nuke": (core["f1_mkt20_prev1b_open"] < -0.02).astype(int),
        "xq_ge1": (core["xq_t1_0900"] >= 1).astype(int),
        "earn_pos": (core["cat_earn_pos_3d"] == 1).astype(int),
        "mon": (core["f1_weekday"] == 0).astype(int),
        "jan_apr": core["f1_month"].isin(["01", "04"]).astype(int),
    })
    corr = cand_feats.corr()
    print("\n--- Pairwise Factor Correlations |r| >= 0.25 on IS CORE[-10,-3] ---")
    cols = corr.columns
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            v = corr.iloc[i, j]
            if abs(v) >= 0.25:
                print(f"  {cols[i]:15s} <-> {cols[j]:15s} : r={v:+.3f}")


if __name__ == "__main__":
    main()

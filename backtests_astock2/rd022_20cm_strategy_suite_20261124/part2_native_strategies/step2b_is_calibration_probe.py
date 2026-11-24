#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2b: IS-only (<= 2024-08-31) fine calibration probe on clean skeletons of P1_S1, P2_S3, P3_S4."""
import pickle, time
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def attach_t2_ret(pool: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for r in pool.itertuples(index=False):
        if not r.f1_buyable or not r.f1_dt or np.isnan(r.f1_ao) or r.f1_ao <= 0:
            continue
        k = 2
        while k < 11 and not getattr(r, f"f{k}_sellable", False):
            k += 1
        if k > 10 or np.isnan(getattr(r, f"f{k}_ac", np.nan)):
            continue
        s_px = float(getattr(r, f"f{k}_ac"))
        net2 = (s_px / float(r.f1_ao)) * 0.9970 - 1.0
        # Also compute T+3 close if available
        k3 = 3
        while k3 < 11 and not getattr(r, f"f{k3}_sellable", False):
            k3 += 1
        net3 = (float(getattr(r, f"f{k3}_ac")) / float(r.f1_ao)) * 0.9970 - 1.0 if (k3 <= 10 and not np.isnan(getattr(r, f"f{k3}_ac", np.nan))) else net2
        d = {c: getattr(r, c) for c in [
            "dt", "f1_dt", "c6", "close", "ret", "to", "vol_ratio5", "pos20", "prev_pos20", "pos60", "bias20",
            "amp", "close_pos", "is_true_yang", "prev_ret5", "zt_cnt_20d", "zt_cnt_60d", "dist_3d30", "dist_10d100",
            "mcap", "lock_top10", "real_free_mcap", "real_to", "zt_hhmm", "zt_obc", "zt_seal_ratio",
            "kpl_in", "kpl_sz", "kpl_10zt", "kpl_10yz", "kpl_20zt", "kpl_elo", "kpl_hist_10zt_max", "kpl_hist_10yz_max", "kpl_peers_f1o",
            "lhb_has", "lhb_inst_net", "lhb_lh_cnt", "lhb_lh_share", "lhb_lh_net_pos", "lhb_good_yz", "lhb_surf", "lhb_quant", "lhb_north", "bayes_t2",
            "xq_t1_pre", "gb_surge", "reg_10d", "cat_any", "ir_10d", "ir_30d", "is_tech",
            "mkt20_zt_cnt", "mkt10_zt_cnt", "mkt20_ew_ret", "f1_mkt10_0925_zt", "f1_mkt10_prev1b_open", "csi_5d",
            "f1_o_pct", "prev_streak", "prev_zt_hhmm", "prev_zt_obc", "prev_lhb_lh_cnt",
        ]}
        d["net2"] = net2
        d["net3"] = net3
        rows.append(d)
    return pd.DataFrame(rows)


def scan_is(title: str, df_t: pd.DataFrame, tests: list):
    is_d = df_t[df_t["f1_dt"] <= "2024-08-31"]
    print(f"\n=== {title} (IS N={len(is_d)}, WR={(is_d['net2']>0).mean()*100:.1f}%, mean={is_d['net2'].mean()*100:+.2f}%, T3mean={is_d['net3'].mean()*100:+.2f}%) ===")
    for name, fn in tests:
        m = fn(is_d)
        s = is_d[m]
        if len(s) < 15:
            continue
        r = s["net2"].to_numpy()
        t = r.mean() / r.std(ddof=1) * np.sqrt(len(r)) if r.std(ddof=1) > 0 else 0
        ew = np.prod(1.0 + s.groupby("f1_dt")["net2"].mean().to_numpy())
        print(f"  {name:30s} | N={len(s):4d} WR={(r>0).mean()*100:5.1f}% mn={r.mean()*100:+5.2f}% t={t:+5.2f} ew={ew:6.2f}x | mn_not={is_d[~m]['net2'].mean()*100:+5.2f}%")


def main():
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    g = df.groupby("c6", sort=False)
    df["prev_zt_hhmm"] = g["zt_hhmm"].shift(1).fillna(9999).astype(int)
    df["prev_zt_obc"] = g["zt_obc"].shift(1).fillna(-1).astype(int)
    df["prev_lhb_lh_cnt"] = g["lhb_lh_cnt"].shift(1).fillna(0).astype(int)
    base = df[df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0) & (df["tox_90d"] == 0)].copy()

    common_tests = [
        ("mkt20_zt>=16(过热)", lambda d: d["mkt20_zt_cnt"] >= 16),
        ("mkt20_zt<=10", lambda d: d["mkt20_zt_cnt"] <= 10),
        ("f1_0925_zt<12", lambda d: d["f1_mkt10_0925_zt"] < 12),
        ("f1_prev1b_open>=0", lambda d: d["f1_mkt10_prev1b_open"] >= 0),
        ("reg_10d==0", lambda d: d["reg_10d"] == 0),
        ("xq_t1_pre<4", lambda d: d["xq_t1_pre"] < 4),
        ("xq_t1_pre>=2", lambda d: d["xq_t1_pre"] >= 2),
        ("pos20<=0.40", lambda d: d["pos20"] <= 0.40),
        ("pos60<=0.50", lambda d: d["pos60"] <= 0.50),
        ("prev_pos20<=0.45", lambda d: d["prev_pos20"] <= 0.45),
        ("prev_pos20>0.75", lambda d: d["prev_pos20"] > 0.75),
        ("bias20<=0.10", lambda d: d["bias20"] <= 0.10),
        ("mcap<=40亿", lambda d: d["mcap"] <= 40.0),
        ("mcap>100亿", lambda d: d["mcap"] > 100.0),
        ("rf_mcap<=30亿", lambda d: d["real_free_mcap"] <= 30.0),
        ("lock_top10>=45%", lambda d: d["lock_top10"] >= 45.0),
        ("real_to>=30%", lambda d: d["real_to"] >= 30.0),
        ("real_to<20%", lambda d: d["real_to"] < 20.0),
        ("close<=25", lambda d: d["close"] <= 25.0),
        ("close>40", lambda d: d["close"] > 40.0),
        ("zt_cnt_60d>=2", lambda d: d["zt_cnt_60d"] >= 2),
        ("dist_3d30>=0.10", lambda d: d["dist_3d30"] >= 0.10),
        ("kpl_in==1", lambda d: d["kpl_in"] == 1),
        ("kpl_10zt>=3", lambda d: d["kpl_10zt"] >= 3),
        ("kpl_hist_10zt>=4", lambda d: d["kpl_hist_10zt_max"] >= 4),
        ("kpl_peers_f1o>=-0.01", lambda d: d["kpl_peers_f1o"] >= -0.01),
        ("lhb_inst_net>0", lambda d: d["lhb_inst_net"] > 0),
        ("lhb_lh_cnt==0", lambda d: (d["lhb_has"] == 1) & (d["lhb_lh_cnt"] == 0)),
        ("lhb_lh_net_pos==1", lambda d: d["lhb_lh_net_pos"] == 1),
        ("lhb_quant>=1", lambda d: d["lhb_quant"] >= 1),
        ("lhb_surf==1", lambda d: d["lhb_surf"] == 1),
        ("is_tech==1", lambda d: d["is_tech"] == 1),
        ("weekday==Mon", lambda d: pd.to_datetime(d["f1_dt"]).dt.dayofweek == 0),
        ("month in (1,4)", lambda d: d["f1_dt"].str.slice(5, 7).isin(["01", "04"])),
    ]

    p1 = attach_t2_ret(base[base["is_zt"] & (base["streak"] == 1) & (~base["is_yizi_zt"]) & (base["f1_o_pct"].between(-0.10, -0.035))])
    scan_is("P1_S1 (首板open -10%~-3.5%)", p1, common_tests + [
        ("zt_hhmm<=1000", lambda d: d["zt_hhmm"] <= 1000),
        ("zt_hhmm(1000,1430)", lambda d: (d["zt_hhmm"] > 1000) & (d["zt_hhmm"] < 1430)),
        ("zt_hhmm>=1430", lambda d: d["zt_hhmm"] >= 1430),
        ("zt_obc>=1", lambda d: d["zt_obc"] >= 1),
        ("open[-8%,-4.5%)", lambda d: d["f1_o_pct"].between(-0.08, -0.045)),
    ])

    p2 = attach_t2_ret(base[(base["prev_streak"] >= 1) & (~base["is_zt"]) & (base["is_true_yang"]) & (base["to"] <= 35.0) & (base["f1_o_pct"].between(-0.07, 0.02))])
    scan_is("P2_S3 (首板+断板真阳 to<=35 open-7~+2)", p2, common_tests + [
        ("prev_streak==1", lambda d: d["prev_streak"] == 1),
        ("open[-7%,-2%)", lambda d: d["f1_o_pct"].between(-0.07, -0.02)),
        ("open[-2%,+2%]", lambda d: d["f1_o_pct"].between(-0.02, 0.02)),
        ("close_pos>=0.60", lambda d: d["close_pos"] >= 0.60),
        ("amp<0.10", lambda d: d["amp"] < 0.10),
        ("to[10%,25%]", lambda d: d["to"].between(10.0, 25.0)),
        ("ret_d0>=0", lambda d: d["ret"] >= 0),
        ("prev_zt_obc==0", lambda d: d["prev_zt_obc"] == 0),
    ])

    p3 = attach_t2_ret(base[base["is_touch_zt"] & (~base["is_zt"]) & (base["ret"] < 0.12) & (base["f1_o_pct"].between(-0.10, -0.025))])
    scan_is("P3_S4 (炸板<12% open-10~-2.5)", p3, common_tests + [
        ("ret<0.08", lambda d: d["ret"] < 0.08),
        ("to<=30%", lambda d: d["to"] <= 30.0),
        ("is_true_yang", lambda d: d["is_true_yang"]),
        ("open<-4%", lambda d: d["f1_o_pct"] < -0.04),
    ])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 1c: Fine open-bucket & sub-structure probe on S1_deep, S3_trueyang, S4_zhaban, S6_earn_ir."""
import pickle, time
import pandas as pd
from backtest_utils import calc_d15_suite, simulate_fixed_hold

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def test_var(rows, grp, name, sub, entry, hold, sh300, ew20):
    if sub.empty:
        return
    tr = simulate_fixed_hold(sub, entry, hold, fee=0.0030, score_col="score")
    m = calc_d15_suite(tr, sh300, ew20)
    IS, OOS, Y26 = m["IS"], m["OOS"], m["2026"]
    print(f"[{grp:4s}] {name:38s} | IS: N={IS['raw_n']:4d}/{IS['n_1s']:3d} WR={IS['wr_1s']:5.1f}% 1s={IS['nav_1s']:5.2f}x 3s={IS['nav_3s']:5.2f}x ew={IS['ew_nav']:5.2f}x | "
          f"OOS: N={OOS['raw_n']:4d}/{OOS['n_1s']:3d} WR={OOS['wr_1s']:5.1f}% 1s={OOS['nav_1s']:5.2f}x 3s={OOS['nav_3s']:5.2f}x ew={OOS['ew_nav']:5.2f}x | 26:1s={Y26['nav_1s']:4.2f}x ew={Y26['ew_nav']:4.2f}x")
    rows.append({"grp": grp, "name": name, "IS_ew": IS["ew_nav"], "OOS_ew": OOS["ew_nav"], "IS_1s": IS["nav_1s"], "OOS_1s": OOS["nav_1s"], "Y26_1s": Y26["nav_1s"], "Y26_ew": Y26["ew_nav"]})


def main():
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    aux = pickle.load(open(f"{OUT_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20 = aux["sh300"], aux["ew20_daily"]
    base = df[df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0)].copy()
    rows = []

    # S1 fine open buckets
    s1 = base[base["is_zt"] & (base["streak"] == 1) & (~base["is_yizi_zt"]) & (base["tox_90d"] == 0)].copy()
    s1["score"] = (1000 - s1["zt_hhmm"]) * 0.1 + s1["kpl_10zt"] * 2.0
    for lbl, lo, hi in [("<-8%", -0.25, -0.08), ("-8~-5%", -0.08, -0.05), ("-5~-3%", -0.05, -0.03), ("-3~0%", -0.03, 0.0), ("<-3%", -0.25, -0.03)]:
        test_var(rows, "S1", f"S1_首板_open{lbl}_T2", s1[(s1["f1_o_pct"] >= lo) & (s1["f1_o_pct"] < hi)], "T1_open", 2, sh300, ew20)

    # S3 fine buckets (prev_streak==1 vs >=1, true_yang & ret sign & open buckets)
    s3 = base[(base["prev_streak"] == 1) & (~base["is_zt"]) & (base["tox_90d"] == 0)].copy()
    s3["score"] = -s3["to"] * 0.1 + s3["kpl_hist_10zt_max"] * 1.0
    for lbl, m in [
        ("真阳全部_open-6~0%_T2", s3["is_true_yang"] & s3["f1_o_pct"].between(-0.06, 0.0)),
        ("真阳全部_open<-4%_T2", s3["is_true_yang"] & (s3["f1_o_pct"] < -0.04)),
        ("真阳全部_open-6~+3%_T2", s3["is_true_yang"] & s3["f1_o_pct"].between(-0.06, 0.03)),
        ("真阳收绿(假阴真阳)_open-6~+3%_T2", s3["is_true_yang"] & (s3["ret"] < 0) & s3["f1_o_pct"].between(-0.06, 0.03)),
        ("真阳收红_open-6~+3%_T2", s3["is_true_yang"] & (s3["ret"] >= 0) & s3["f1_o_pct"].between(-0.06, 0.03)),
        ("阴线小跌>-6%_open<-3%_T2", (~s3["is_true_yang"]) & (s3["ret"] > -0.06) & (s3["f1_o_pct"] < -0.03)),
    ]:
        test_var(rows, "S3", f"S3_首板断板_{lbl}", s3[m], "T1_open", 2, sh300, ew20)

    # S4 fine buckets (broken zt)
    s4 = base[base["is_touch_zt"] & (~base["is_zt"]) & (base["tox_90d"] == 0)].copy()
    s4["score"] = -s4["f1_o_pct"].fillna(0) * 50.0
    for lbl, rlo, rhi, olo, ohi in [
        ("收<10%_open<-3%_T2", -0.25, 0.10, -0.25, -0.03),
        ("收<12%_open<-3%_T2", -0.25, 0.12, -0.25, -0.03),
        ("收<15%_open<-4%_T2", -0.25, 0.15, -0.25, -0.04),
        ("收0~12%_open-8~-2%_T2", 0.0, 0.12, -0.08, -0.02),
        ("全炸板_open<-4%_T2", -0.25, 0.195, -0.25, -0.04),
    ]:
        test_var(rows, "S4", f"S4_炸板_{lbl}", s4[(s4["ret"].between(rlo, rhi)) & (s4["f1_o_pct"].between(olo, ohi))], "T1_open", 2, sh300, ew20)

    # S6 fine buckets
    s6_e = base[(base["cat_earn_3d"] == 1) & (base["tox_90d"] == 0) & (base["vol_ratio5"] >= 1.5)].copy()
    s6_e["score"] = s6_e["vol_ratio5"]
    test_var(rows, "S6", "S6_业绩预增+放量_低平开-4~+2%_T3", s6_e[s6_e["f1_o_pct"].between(-0.04, 0.02)], "T1_open", 3, sh300, ew20)
    test_var(rows, "S6", "S6_业绩预增+放量_高开+2~+8%_T3", s6_e[s6_e["f1_o_pct"].between(0.02, 0.08)], "T1_open", 3, sh300, ew20)
    s6_ir = base[(base["ir_10d"] >= 2) & (base["tox_90d"] == 0) & (base["vol_ratio5"] >= 1.5) & (base["bias20"] > 0)].copy()
    s6_ir["score"] = s6_ir["vol_ratio5"]
    test_var(rows, "S6", "S6_调研10d>=2+放量MA20_绿平开_T3", s6_ir[s6_ir["f1_o_pct"].between(-0.03, 0.02)], "T1_open", 3, sh300, ew20)


if __name__ == "__main__":
    main()

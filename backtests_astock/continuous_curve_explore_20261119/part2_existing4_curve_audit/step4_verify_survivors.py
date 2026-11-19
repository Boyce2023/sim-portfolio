#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step4_verify_survivors.py — 严苛审讯：
1. 检验 pos20/dd20/dd60 本身在四大现役账本 IS/OOS 的残余表现
2. 对所有表面疑似候选做「控制 pos20/dd20/dd60 后分层检验 + 4策略1-slot合体净值/回撤增益 + 置换检验(p-value)」
"""
import os
import numpy as np
import pandas as pd
from scipy import stats

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit"
FEAT_CSV = os.path.join(OUT_DIR, "all_trades_curve_features_pit.csv")
PRIORITY = {"3to4": 1, "high": 2, "2to3": 3, "1to2": 4}


def run_1slot(pool: pd.DataFrame) -> pd.DataFrame:
    df_s = pool.copy()
    df_s["priority"] = df_s["strategy"].map(PRIORITY)
    df_s = df_s.sort_values(["buy_date", "priority", "score", "buy_hhmm"], ascending=[True, True, False, True]).reset_index(drop=True)
    picked = []
    cur_ed, cur_eh = "", 0
    for row in df_s.itertuples(index=False):
        if not cur_ed or row.buy_date > cur_ed or (row.buy_date == cur_ed and row.buy_hhmm > cur_eh):
            picked.append(row._asdict())
            cur_ed = row.exit_date
            cur_eh = row.exit_hhmm
    return pd.DataFrame(picked)


def win_metrics(sub: pd.DataFrame, start_dt: str) -> dict:
    s = sub[sub["buy_date"] >= start_dt]
    if s.empty:
        return {"n": 0, "wr": 0.0, "mean": 0.0, "plr": 0.0, "nav": 1.0, "mdd": 0.0}
    r = s.sort_values(["buy_date", "buy_hhmm"])["net_ret"].to_numpy(dtype=float)
    wins, losses = r[r > 0], r[r <= 0]
    wr = float(len(wins) / len(r) * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else 99.9
    cum = np.cumprod(1.0 + r)
    peaks = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
    mdd = float(np.max((peaks - cum) / peaks) * 100.0)
    return {"n": len(r), "wr": round(wr, 2), "mean": round(float(r.mean() * 100), 2), "plr": round(plr, 2), "nav": round(float(cum[-1]), 2), "mdd": round(mdd, 2)}


def main():
    df = pd.read_csv(FEAT_CSV)

    print("=== 1. BASELINE CHIP/POSITION FACTORS (pos20, dd20, dd60) IN ACTIVE 4 LEDGERS ===")
    for strat in ["3to4", "high", "2to3", "1to2"]:
        s = df[df["strategy"] == strat]
        is_s, oos_s = s[s["is_oos"] == 0], s[s["is_oos"] == 1]
        for ref in ["pos20", "dd20", "dd60"]:
            r_is, _ = stats.spearmanr(is_s[ref], is_s["net_ret"])
            r_oos, _ = stats.spearmanr(oos_s[ref], oos_s["net_ret"])
            med = is_s[ref].median()
            is_lo = is_s[is_s[ref] <= med]["net_ret"].mean() * 100
            is_hi = is_s[is_s[ref] > med]["net_ret"].mean() * 100
            oos_lo = oos_s[oos_s[ref] <= med]["net_ret"].mean() * 100
            oos_hi = oos_s[oos_s[ref] > med]["net_ret"].mean() * 100
            print(f"  {strat:4s} | {ref:5s} | IS_med={med:.3f} | rho_is={r_is:+.3f}, rho_oos={r_oos:+.3f} | IS(lo/hi)={is_lo:.2f}/{is_hi:.2f} | OOS(lo/hi)={oos_lo:.2f}/{oos_hi:.2f}")

    print("\n=== 2. DEEP CHECK: 3to4 F6_MA5_HUG (IS_med=6) & F1_ER10_SIGNED vs pos20 ===")
    s34 = df[df["strategy"] == "3to4"].copy()
    print("  3to4 F6_MA5_HUG exact value breakdown (all 95):")
    print(s34.groupby("F6_MA5_HUG").agg(n=("net_ret", "count"), wr=("net_ret", lambda x: round((x > 0).mean() * 100, 1)), mean=("net_ret", lambda x: round(x.mean() * 100, 2)), pos20_med=("pos20", "median")).to_string())
    # Stratified check: inside pos20 <= 0.56 and pos20 > 0.56
    p20_med = s34[s34["is_oos"] == 0]["pos20"].median()
    for lbl, sub_p in [("pos20<=IS_med", s34[s34["pos20"] <= p20_med]), ("pos20>IS_med", s34[s34["pos20"] > p20_med])]:
        for period, sub_t in [("IS", sub_p[sub_p["is_oos"] == 0]), ("OOS", sub_p[sub_p["is_oos"] == 1])]:
            lo = sub_t[sub_t["F6_MA5_HUG"] <= 6]["net_ret"]
            hi = sub_t[sub_t["F6_MA5_HUG"] >= 7]["net_ret"]
            print(f"  Stratified {lbl} {period}: F6<=6 (n={len(lo)}, wr={(lo>0).mean()*100 if len(lo) else 0:.1f}%, mean={lo.mean()*100 if len(lo) else 0:.2f}%) vs F6>=7 (n={len(hi)}, wr={(hi>0).mean()*100 if len(hi) else 0:.1f}%, mean={hi.mean()*100 if len(hi) else 0:.2f}%)")

    # Also check F6_MA5_HUG <= 3 or <= 4 (only dropping bottom tail so N stays large!)
    print("\n  3to4 F6_MA5_HUG tail cutoffs (<=3, <=4, <=5):")
    for cut in [3, 4, 5, 6]:
        kept = s34[s34["F6_MA5_HUG"] > cut]
        drop = s34[s34["F6_MA5_HUG"] <= cut]
        is_k, is_d = kept[kept["is_oos"] == 0], drop[drop["is_oos"] == 0]
        oos_k, oos_d = kept[kept["is_oos"] == 1], drop[drop["is_oos"] == 1]
        print(f"    F6>{cut}: drop_n(IS={len(is_d)},OOS={len(oos_d)}), IS_drop_mean={is_d['net_ret'].mean()*100:.2f}% vs keep={is_k['net_ret'].mean()*100:.2f}%, "
              f"OOS_drop_mean={oos_d['net_ret'].mean()*100:.2f}% vs keep={oos_k['net_ret'].mean()*100:.2f}%, "
              f"5Y={win_metrics(kept,'2021-11-15')}, 2026={win_metrics(kept,'2026-01-01')}")

    print("\n=== 3. DEEP CHECK: 1to2 sig_F4_VOL_BUILD & F8_DIST_HI120 ===")
    s12 = df[df["strategy"] == "1to2"].copy()
    is12, oos12 = s12[s12["is_oos"] == 0], s12[s12["is_oos"] == 1]
    for col in ["sig_F4_VOL_BUILD", "F8_DIST_HI120"]:
        med = is12[col].median()
        q33, q67 = np.quantile(is12[col], [1/3, 2/3])
        print(f"  1to2 {col}: IS_med={med:.3f}, q33={q33:.3f}, q67={q67:.3f}")
        for tag, cond_fn in [("<=q33", lambda x: x <= q33), ("q33-q67", lambda x: (x > q33) & (x <= q67)), (">q67", lambda x: x > q67), ("<=med", lambda x: x <= med), (">med", lambda x: x > med)]:
            a, b = is12[cond_fn(is12[col])]["net_ret"], oos12[cond_fn(oos12[col])]["net_ret"]
            print(f"    {tag:8s}: IS(n={len(a):2d}, wr={(a>0).mean()*100:5.1f}%, mean={a.mean()*100:5.2f}%) | OOS(n={len(b):2d}, wr={(b>0).mean()*100:5.1f}%, mean={b.mean()*100:5.2f}%)")

    # Check 1to2 F8_DIST_HI120 stratified by dd60!
    dd60_med = is12["dd60"].median()
    for lbl, sub_p in [("dd60<=IS_med", s12[s12["dd60"] <= dd60_med]), ("dd60>IS_med", s12[s12["dd60"] > dd60_med])]:
        f8_med = is12["F8_DIST_HI120"].median()
        for period, sub_t in [("IS", sub_p[sub_p["is_oos"] == 0]), ("OOS", sub_p[sub_p["is_oos"] == 1])]:
            lo = sub_t[sub_t["F8_DIST_HI120"] <= f8_med]["net_ret"]
            hi = sub_t[sub_t["F8_DIST_HI120"] > f8_med]["net_ret"]
            print(f"  Stratified 1to2 {lbl} {period}: F8<=med (n={len(lo)}, mean={lo.mean()*100 if len(lo) else np.nan:.2f}%) vs F8>med (n={len(hi)}, mean={hi.mean()*100 if len(hi) else np.nan:.2f}%)")

    print("\n=== 4. 4-STRATEGY 1-SLOT PORTFOLIO IMPACT OF EVERY PLAUSIBLE CANDIDATE FILTER ===")
    base_slot = run_1slot(df)
    scenarios = [
        ("BASELINE_NO_FILTER", df),
        ("3to4_drop_F6<=4 (drop 25/95)", df[~((df["strategy"] == "3to4") & (df["F6_MA5_HUG"] <= 4))]),
        ("3to4_drop_F6<=6 (drop 53/95)", df[~((df["strategy"] == "3to4") & (df["F6_MA5_HUG"] <= 6))]),
        ("3to4_drop_F1sig<=0.032 (drop 34/95)", df[~((df["strategy"] == "3to4") & (df["F1_ER10_SIGNED"] <= 0.032))]),
        ("3to4_only_F5_N_WAVE==1 (drop 71/95)", df[~((df["strategy"] == "3to4") & (df["F5_N_WAVE"] == 0))]),
        ("high_drop_F4v15<=1.15 (drop 16/42)", df[~((df["strategy"] == "high") & (df["F4_VOL_BUILD15"] <= 1.151))]),
        ("1to2_drop_sigF4<=med (drop 56/97)", df[~((df["strategy"] == "1to2") & (df["sig_F4_VOL_BUILD"] <= is12["sig_F4_VOL_BUILD"].median()))]),
        ("1to2_drop_sigF4<=q33 (drop 30/97)", df[~((df["strategy"] == "1to2") & (df["sig_F4_VOL_BUILD"] <= np.quantile(is12["sig_F4_VOL_BUILD"], 1/3)))]),
    ]
    for name, pool in scenarios:
        slot = run_1slot(pool)
        m5 = win_metrics(slot, "2021-11-15")
        m3 = win_metrics(slot, "2023-11-16")
        mo = win_metrics(slot, "2024-01-01")
        m26 = win_metrics(slot, "2026-01-01")
        print(f"  {name:36s} | 5Y:n={m5['n']:3d},WR={m5['wr']:5.2f},NAV={m5['nav']:10.2f}x,MDD={m5['mdd']:5.2f}% | "
              f"OOS:n={mo['n']:3d},WR={mo['wr']:5.2f},NAV={mo['nav']:8.2f}x,MDD={mo['mdd']:5.2f}% | "
              f"2026:n={m26['n']:2d},WR={m26['wr']:5.2f},NAV={m26['nav']:5.2f}x")


if __name__ == "__main__":
    main()

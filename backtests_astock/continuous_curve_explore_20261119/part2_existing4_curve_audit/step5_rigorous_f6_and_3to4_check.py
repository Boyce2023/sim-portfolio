#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step5_rigorous_f6_and_3to4_check.py — 对 3to4×F6_MA5_HUG 做逐年/置换/样本例证/D15全套严格校验
"""
import os, json
import numpy as np
import pandas as pd
from scipy import stats

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit"
FEAT_CSV = os.path.join(OUT_DIR, "all_trades_curve_features_pit.csv")
CSI_JSON = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_rebacktest_20261116/csi300_canonical_20261116.json"
PRIORITY = {"3to4": 1, "high": 2, "2to3": 3, "1to2": 4}


def run_1slot(pool: pd.DataFrame) -> pd.DataFrame:
    df_s = pool.copy()
    df_s["priority"] = df_s["strategy"].map(PRIORITY)
    df_s = df_s.sort_values(["buy_date", "priority", "score", "buy_hhmm"], ascending=[True, True, False, True]).reset_index(drop=True)
    picked, cur_ed, cur_eh = [], "", 0
    for row in df_s.itertuples(index=False):
        if not cur_ed or row.buy_date > cur_ed or (row.buy_date == cur_ed and row.buy_hhmm > cur_eh):
            picked.append(row._asdict())
            cur_ed, cur_eh = row.exit_date, row.exit_hhmm
    return pd.DataFrame(picked)


def d15_metrics(slot_df: pd.DataFrame, all_df: pd.DataFrame, start_dt: str, csi_pct: float) -> dict:
    s = slot_df[slot_df["buy_date"] >= start_dt].sort_values(["buy_date", "buy_hhmm"])
    a = all_df[all_df["buy_date"] >= start_dt]
    if s.empty:
        return {"n": 0}
    r = s["net_ret"].to_numpy(dtype=float)
    wins, losses = r[r > 0], r[r <= 0]
    wr = float(len(wins) / len(r) * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else 99.9
    cum = np.cumprod(1.0 + r)
    peaks = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
    mdd = float(np.max((peaks - cum) / peaks) * 100.0)
    day_r = a.groupby("buy_date")["net_ret"].mean().sort_index().to_numpy()
    nav_eq = float(np.prod(1.0 + day_r)) if len(day_r) else 1.0
    cap = 100.0
    for x in r:
        cap += min(cap, 1000.0) * float(x)
    ret_pct = (float(cum[-1]) - 1.0) * 100.0
    return {
        "n_slot": len(r), "wr": round(wr, 2), "mean": round(float(r.mean() * 100), 2),
        "plr": round(plr, 2), "nav_slot": round(float(cum[-1]), 2), "nav_eq": round(nav_eq, 2),
        "mdd": round(mdd, 2), "cap10m_x": round(cap / 100.0, 2),
        "csi_pct": round(csi_pct, 2), "excess_pp": round(ret_pct - csi_pct, 2),
    }


def main():
    df = pd.read_csv(FEAT_CSV)
    csi = json.load(open(CSI_JSON))
    s34 = df[df["strategy"] == "3to4"].copy()
    s34["year"] = s34["buy_date"].str[:4]

    print("=== 1. YEAR-BY-YEAR: 3to4 F6_MA5_HUG <= 4 vs >= 5 ===")
    for yr, g in s34.groupby("year"):
        lo = g[g["F6_MA5_HUG"] <= 4]["net_ret"]
        hi = g[g["F6_MA5_HUG"] >= 5]["net_ret"]
        print(f"  {yr}: <=4 (n={len(lo):2d}, wr={(lo>0).mean()*100 if len(lo) else 0:5.1f}%, mean={lo.mean()*100 if len(lo) else 0:6.2f}%) "
              f"vs >=5 (n={len(hi):2d}, wr={(hi>0).mean()*100 if len(hi) else 0:5.1f}%, mean={hi.mean()*100 if len(hi) else 0:6.2f}%)")

    print("\n=== 2. STATISTICAL TESTS FOR 3to4 F6_MA5_HUG >= 5 vs <= 4 ===")
    for lbl, sub in [("IS (2022-23)", s34[s34["is_oos"] == 0]), ("OOS (2024-26)", s34[s34["is_oos"] == 1]), ("FULL 5Y", s34)]:
        lo = sub[sub["F6_MA5_HUG"] <= 4]["net_ret"].to_numpy()
        hi = sub[sub["F6_MA5_HUG"] >= 5]["net_ret"].to_numpy()
        t_stat, p_t = stats.ttest_ind(hi, lo, equal_var=False, alternative="greater")
        u_stat, p_u = stats.mannwhitneyu(hi, lo, alternative="greater")
        # 10000-rep permutation p-value for mean diff
        rng = np.random.default_rng(42)
        obs = hi.mean() - lo.mean()
        comb = np.concatenate([hi, lo])
        nhi = len(hi)
        cnt = 0
        for _ in range(10000):
            perm = rng.permutation(comb)
            if perm[:nhi].mean() - perm[nhi:].mean() >= obs:
                cnt += 1
        p_perm = cnt / 10000.0
        print(f"  {lbl:14s}: lo(n={len(lo):2d}, wr={(lo>0).mean()*100:5.1f}%, mean={lo.mean()*100:5.2f}%) vs "
              f"hi(n={len(hi):2d}, wr={(hi>0).mean()*100:5.1f}%, mean={hi.mean()*100:5.2f}%) | "
              f"diff={obs*100:+5.2f}pp | p_welch={p_t:.4f}, p_mwu={p_u:.4f}, p_perm={p_perm:.4f}")

    print("\n=== 3. SAMPLE DROPPED TRADES (3to4 F6_MA5_HUG <= 4, bottom & top) ===")
    dropped = s34[s34["F6_MA5_HUG"] <= 4].sort_values("net_ret")
    cols_p = ["c6", "name", "buy_date", "net_ret", "score", "F6_MA5_HUG", "pos20", "dd60", "F1_ER10_SIGNED"]
    print("  Worst 8 dropped:")
    print(dropped[cols_p].head(8).to_string(index=False))
    print("  Best 5 dropped:")
    print(dropped[cols_p].tail(5).to_string(index=False))

    print("\n=== 4. D15 FULL CHECK: 3to4 STANDALONE & 4-STRAT COMBINED (Base vs F6>=5) ===")
    wins = [
        ("5Y", "2021-11-15", csi["全五年(2021-11-16起)"][0]),
        ("Near3Y", "2023-11-16", csi["近三年(2023-11-16起)"][0]),
        ("OOS24_26", "2024-01-01", csi["近三年(2024-01-01起)"][0]),
        ("2026", "2026-01-01", csi["2026全年"][0]),
    ]
    s34_filt = s34[s34["F6_MA5_HUG"] >= 5].copy()
    for lbl, a_df in [("3to4_Base", s34), ("3to4_F6>=5", s34_filt)]:
        for wname, d0, csi_p in wins:
            print(f"  {lbl:12s} | {wname:8s} | {d15_metrics(a_df, a_df, d0, csi_p)}")

    pool_base = df.copy()
    pool_filt = df[~((df["strategy"] == "3to4") & (df["F6_MA5_HUG"] <= 4))].copy()
    slot_base = run_1slot(pool_base)
    slot_filt = run_1slot(pool_filt)
    for lbl, s_df, a_df in [("4Strat_Base", slot_base, pool_base), ("4Strat_3to4F6>=5", slot_filt, pool_filt)]:
        for wname, d0, csi_p in wins:
            print(f"  {lbl:16s} | {wname:8s} | {d15_metrics(s_df, a_df, d0, csi_p)}")


if __name__ == "__main__":
    main()

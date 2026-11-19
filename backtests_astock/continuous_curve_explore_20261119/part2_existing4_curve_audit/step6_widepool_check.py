#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step6_widepool_check.py — 在三进四宽池 (skel==True, 391笔 & 78<=sc<90 未入选池 & sc>=78池)
独立盲测 F6_MA5_HUG, F5_N_WAVE, F1_ER10_SIGNED, pos20 是否真的泛化，还是仅 95 笔偶然波动！
"""
import os, sys, pickle
import numpy as np
import pandas as pd
from scipy import stats

F1_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_factors_v2_20261118/f1_3to4"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit"
sys.path.insert(0, F1_DIR)
import exit_factor_engine as efe

PQ_ACT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
PQ_DEL = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"


def main():
    pk = pickle.load(open(f"{F1_DIR}/pit_exit_cache_full.pkl", "rb"))
    # Evaluate all skel==True trades with V4.0 base exit
    res = efe.evaluate_rule(pk, {}, None, "ALL_SKEL", -999.0)
    raw = res["raw_df"].copy()
    raw["c6"] = raw["code"].astype(str).str.zfill(6)
    print(f"Total skel & buyable raw trades: {len(raw)}, sc>=78: {(raw['score']>=78).sum()}, 75<=sc<90: {((raw['score']>=75)&(raw['score']<90)).sum()}, sc<90: {(raw['score']<90).sum()}, sc>=90: {(raw['score']>=90).sum()}")

    # Load PIT prices for these c6
    c6s = set(raw["c6"])
    cols = ["date", "ticker", "open", "high", "low", "close", "qfq_factor"]
    d1 = pd.read_parquet(PQ_ACT, columns=cols)
    d1["c6"] = d1["ticker"].str[:6]; d1 = d1[d1["c6"].isin(c6s)].copy(); d1["src"] = 0
    d2 = pd.read_parquet(PQ_DEL, columns=cols)
    d2["c6"] = d2["ticker"].str[:6]; d2 = d2[d2["c6"].isin(c6s)].copy(); d2["src"] = 1
    px = pd.concat([d1, d2], ignore_index=True)
    px = px[px["c6"].str.startswith(("00", "60")) & (~px["ticker"].str.endswith(".BJ"))].copy()
    px["dt"] = px["date"].dt.strftime("%Y-%m-%d")
    px.sort_values(["c6", "dt", "src"], inplace=True)
    px.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    by_c6 = {c6: g.reset_index(drop=True) for c6, g in px.groupby("c6")}

    f6_vals, pos20_vals, f1s_vals = [], [], []
    for r in raw.itertuples(index=False):
        g = by_c6.get(r.c6)
        if g is None:
            f6_vals.append(np.nan); pos20_vals.append(np.nan); f1s_vals.append(np.nan); continue
        matches = g.index[g["dt"] == r.buy_date].tolist()
        if not matches:
            f6_vals.append(np.nan); pos20_vals.append(np.nan); f1s_vals.append(np.nan); continue
        buy_idx = matches[0]
        sig_idx = buy_idx - 1
        d0_idx = sig_idx - 3
        if d0_idx < 20:
            f6_vals.append(np.nan); pos20_vals.append(np.nan); f1s_vals.append(np.nan); continue
        sub = g.iloc[: sig_idx + 1]
        scale = float(sub["qfq_factor"].iloc[sig_idx]) / sub["qfq_factor"].to_numpy(dtype=float)
        c = sub["close"].to_numpy(dtype=float) * scale
        h = sub["high"].to_numpy(dtype=float) * scale
        l = sub["low"].to_numpy(dtype=float) * scale

        ma5 = pd.Series(c).rolling(5).mean().to_numpy()
        f6 = int(np.sum(c[d0_idx - 9 : d0_idx + 1] >= ma5[d0_idx - 9 : d0_idx + 1]))
        min20 = float(np.min(l[d0_idx - 19 : d0_idx + 1]))
        max20 = float(np.max(h[d0_idx - 19 : d0_idx + 1]))
        p20 = float((c[d0_idx] - min20) / (max20 - min20 + 1e-8))
        dc = float(np.sum(np.abs(np.diff(c[d0_idx - 10 : d0_idx + 1]))))
        f1s = float((c[d0_idx] - c[d0_idx - 10]) / dc) if dc > 1e-12 else 0.0

        f6_vals.append(f6)
        pos20_vals.append(p20)
        f1s_vals.append(f1s)

    raw["F6_MA5_HUG"] = f6_vals
    raw["pos20"] = pos20_vals
    raw["F1_ER10_SIGNED"] = f1s_vals
    raw = raw.dropna(subset=["F6_MA5_HUG"]).copy()
    raw["is_oos"] = (raw["buy_date"] >= "2024-01-01").astype(int)

    # Load active ledger to verify overlap & inspect disjoint sc<90!
    active = pd.read_csv("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_factors_v2_20261118/f1_3to4/ledger_3to4_xf30_std.csv")
    act_keys = set(zip(active["code"].astype(str).str.zfill(6), active["buy_date"]))
    raw["in_active"] = [((c6, bd) in act_keys) for c6, bd in zip(raw["c6"], raw["buy_date"])]

    for pname, sub in [
        ("ALL_SKEL (all candidates)", raw),
        ("WIDE_SC>=78 (N=all)", raw[raw["score"] >= 78]),
        ("DISJOINT_UNSEEN (not in active95, all skel)", raw[~raw["in_active"]]),
        ("DISJOINT_SC78_89 (78<=sc<90)", raw[(raw["score"] >= 78) & (~raw["in_active"])]),
        ("SC>=90_BASE_V40", raw[raw["score"] >= 90]),
    ]:
        print(f"\n=== {pname} (n={len(sub)}) ===")
        for period, psub in [("IS(21-23)", sub[sub["is_oos"] == 0]), ("OOS(24-26)", sub[sub["is_oos"] == 1]), ("FULL", sub)]:
            lo = psub[psub["F6_MA5_HUG"] <= 4]["net_ret"]
            hi = psub[psub["F6_MA5_HUG"] >= 5]["net_ret"]
            rho, pval = stats.spearmanr(psub["F6_MA5_HUG"], psub["net_ret"]) if len(psub) > 5 else (0.0, 1.0)
            print(f"  {period:10s} | F6<=4(n={len(lo):3d},wr={(lo>0).mean()*100 if len(lo) else 0:5.1f}%,mean={lo.mean()*100 if len(lo) else 0:5.2f}%) "
                  f"vs F6>=5(n={len(hi):3d},wr={(hi>0).mean()*100 if len(hi) else 0:5.1f}%,mean={hi.mean()*100 if len(hi) else 0:5.2f}%) | "
                  f"diff={(hi.mean()-lo.mean())*100 if (len(lo) and len(hi)) else 0:+5.2f}pp | rho={rho:+.3f}(p={pval:.3f})")


if __name__ == "__main__":
    main()

import warnings; warnings.filterwarnings("ignore")
#!/usr/bin/env python3
"""RD021 Follow-up: Rigorous PIT verification for Buwen's 5 deep questions.
1. Exact Hog turning-point waves (Stock Peak vs Spot/LH0 Peak & Trough).
2. Exit-rule ablation (what exit works best for Lead vs Sync commodities).
3. Stock-Predicts-Futures real PIT shift(1) backtest (Long-only & Long/Short + fwd returns).
4. Sub-period regime decay check: 2016-2020 vs 2021-2024 vs 2025.01-2026.11.20!
5. Coal JM0 / Gold AU0 why-left-side-failed diagnostic.
Strictly NO yfinance. Reads data_cache/*.parquet & existing results JSONs.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/commodities_leadlag_10y_20261123")
CACHE = BASE / "data_cache"

a_close = pd.read_parquet(CACHE / "a_stocks_close.parquet")
a_open = pd.read_parquet(CACHE / "a_stocks_open.parquet")
cn_fut = pd.read_parquet(CACHE / "cn_futures_close.parquet")
gl_fut = pd.read_parquet(CACHE / "global_futures_close.parquet")
hog_spot = pd.read_parquet(CACHE / "hog_spot_weekly.parquet")["hog_spot"].groupby(level=0).last()
hs300 = pd.read_parquet(CACHE / "sh000300.parquet")["sh000300"]

l_res = json.load(open(BASE / "results_lithium_hog_coal.json"))
m_res = json.load(open(BASE / "results_metals_energy.json"))

# Build equal-weight stock baskets
baskets = {
    "生猪": a_close[["002714.SZ", "300498.SZ"]].pct_change().mean(axis=1).add(1).cumprod(),
    "碳酸锂": a_close[["002460.SZ", "002466.SZ", "000792.SZ"]].loc["2023-07-21":].pct_change().mean(axis=1).add(1).cumprod(),
    "铜": a_close[["601899.SH", "603993.SH"]].pct_change().mean(axis=1).add(1).cumprod(),
    "石油": a_close[["601857.SH", "600938.SH"]].pct_change().mean(axis=1).add(1).cumprod(),
    "黄金": a_close[["600547.SH", "600988.SH"]].pct_change().mean(axis=1).add(1).cumprod(),
    "煤炭": a_close[["000983.SZ", "601699.SH", "601088.SH"]].pct_change().mean(axis=1).add(1).cumprod(),
}
baskets_open = {
    k: a_open[cols].loc[baskets[k].index].pct_change().mean(axis=1)
    for k, cols in [
        ("生猪", ["002714.SZ", "300498.SZ"]), ("碳酸锂", ["002460.SZ", "002466.SZ", "000792.SZ"]),
        ("铜", ["601899.SH", "603993.SH"]), ("石油", ["601857.SH", "600938.SH"]),
        ("黄金", ["600547.SH", "600988.SH"]), ("煤炭", ["000983.SZ", "601699.SH", "601088.SH"]),
    ]
}
comm_map = {
    "生猪_现货": (baskets["生猪"], hog_spot.reindex(a_close.index).ffill()),
    "生猪_LH0": (baskets["生猪"], cn_fut["LH0"].dropna()),
    "碳酸锂_LC0": (baskets["碳酸锂"], cn_fut["LC0"].dropna()),
    "铜_CU0": (baskets["铜"], cn_fut["CU0"].dropna()),
    "铜_HG": (baskets["铜"], gl_fut["HG_F"].groupby(level=0).last().reindex(a_close.index).ffill()),
    "石油_SC0": (baskets["石油"], cn_fut["SC0"].dropna()),
    "黄金_AU0": (baskets["黄金"], cn_fut["AU0"].dropna()),
    "煤炭_JM0": (baskets["煤炭"], cn_fut["JM0"].dropna()),
}

def xcorr_scan(stk, com, start, end, ret_w=60, max_lag=180):
    df = pd.DataFrame({"s": stk, "c": com}).dropna().loc[start:end]
    if len(df) < ret_w + 60:
        return None
    sr, cr = df["s"].pct_change(ret_w), df["c"].pct_change(ret_w)
    lim = min(max_lag, len(df) // 3)
    best_k, best_r, r0 = 0, -9.0, float(sr.corr(cr))
    for k in range(-lim, lim + 1):
        r = float(sr.corr(cr.shift(-k)))  # k>0: stock(t) predicts comm(t+k)
        if np.isfinite(r) and r > best_r:
            best_r, best_k = r, k
    return {"n": len(df), "peak_k": best_k, "peak_r": round(best_r, 3), "r0": round(r0, 3), "lim": lim}

print("=== Q4: EXACT HOG TURNING-POINT WAVES (Stock vs Spot & LH0) ===")
for trk in ["spot_10y", "lh0_5y"]:
    print(f"--- {trk} (HOG_EQ & 002714.SZ) ---")
    for tgt in ["HOG_EQ", "002714.SZ"]:
        w = l_res["hog"][trk]["module1_turning_points"][tgt]["waves"]
        print(f"  [{tgt}] waves (lead>0 = Stock BEFORE Comm):")
        for x in w:
            print("   ", x.get("type"), "| comm:", x.get("comm_date"), "| stk:", x.get("stock_date"), "| lead_d:", x.get("lead_days"))

print("\n=== Q5: SUB-PERIOD REGIME DECAY (60d & 20d xcorr: 2016-2020 vs 2021-2024 vs 2025-2026.11) ===")
periods = [("2016-2020", "2016-01-04", "2020-12-31"), ("2021-2024", "2021-01-04", "2024-12-31"), ("2025-2026", "2025-01-02", "2026-11-20")]
for name, (stk, com) in comm_map.items():
    out = []
    for plbl, s0, s1 in periods:
        res60 = xcorr_scan(stk, com, s0, s1, ret_w=60, max_lag=160)
        res20 = xcorr_scan(stk, com, s0, s1, ret_w=20, max_lag=120)
        if res60:
            out.append(f"{plbl}[60d:{res60['peak_k']:+d}d(r={res60['peak_r']:+.2f},r0={res60['r0']:+.2f})|20d:{res20['peak_k']:+d}d(r={res20['peak_r']:+.2f})]")
    print(f"{name:10s}: " + " ; ".join(out))

print("\n=== Q3: PIT STOCK-PREDICTS-FUTURES REAL TRADING BACKTEST (shift(1), fee=0.05% RT) ===")
def test_stk_pred_fut(name, stk, fut, start="2016-01-04", end="2026-11-20", fee=0.0005):
    df = pd.DataFrame({"s": stk, "f": fut}).dropna()
    df["s_ma60"] = df["s"].rolling(60).mean()
    df["f_ma60"] = df["f"].rolling(60).mean()
    df["s_r60"] = df["s"].pct_change(60)
    df["f_r60"] = df["f"].pct_change(60)
    df["f_ret1"] = df["f"].pct_change()
    sub = df.loc[start:end].copy()
    if len(sub) < 120:
        return None
    # Strictly PIT: signal decided at close t -> position active for close(t)->close(t+1) (or t+1->t+2 via shift(2) conservative!)
    # Use shift(2) so signal at close t executes at close t+1 (strictly zero close-to-close same-day leakage!)
    def eval_pos(pos_raw):
        pos = pos_raw.shift(2).fillna(0.0)
        turn = pos.diff().abs().fillna(0.0)
        net = pos * sub["f_ret1"] - turn * (fee / 2.0)
        eq = (1.0 + net).cumprod()
        yrs = len(sub) / 242.0
        cagr = (eq.iloc[-1] ** (1.0 / yrs) - 1.0) * 100.0
        mdd = (eq / eq.cummax() - 1.0).min() * 100.0
        sh = (net.mean() / (net.std() + 1e-12)) * np.sqrt(242)
        return f"CAGR={cagr:+5.1f}%,MDD={mdd:5.1f}%,Sh={sh:+.2f}"

    # S1: Stock Trend -> Long/Short Futures (s > ma60 -> +1 else -1)
    p_ls = np.where(sub["s"] > sub["s_ma60"], 1.0, -1.0)
    # S2: Stock Trend -> Long-Only Futures (s > ma60 -> +1 else 0)
    p_lo = np.where(sub["s"] > sub["s_ma60"], 1.0, 0.0)
    # S3: Divergence (Stock strong & Fut weak: s>ma60 & s_r60-f_r60>0.08 -> +1; s<ma60 & s_r60-f_r60<-0.08 -> -1)
    p_div = np.where((sub["s"] > sub["s_ma60"]) & (sub["s_r60"] - sub["f_r60"] > 0.08), 1.0,
            np.where((sub["s"] < sub["s_ma60"]) & (sub["s_r60"] - sub["f_r60"] < -0.08), -1.0, 0.0))
    # S4: Futures Self-Trend (f > f_ma60 -> +1 else -1)
    p_self = np.where(sub["f"] > sub["f_ma60"], 1.0, -1.0)
    # Forward 60d futures return conditioned on stock 60d return > +15% vs < -15%
    fwd60 = sub["f"].shift(-60) / sub["f"] - 1.0
    hi_m = fwd60[sub["s_r60"] > 0.15].dropna()
    lo_m = fwd60[sub["s_r60"] < -0.15].dropna()
    bh_cagr = ((sub["f"].iloc[-1] / sub["f"].iloc[0]) ** (242.0 / len(sub)) - 1.0) * 100.0
    print(f"{name:12s} ({start[:4]}~{end[:4]}, n={len(sub):4d}) | BH={bh_cagr:+5.1f}% | Stk->Fut LS:[{eval_pos(pd.Series(p_ls, index=sub.index))}] | Div LS:[{eval_pos(pd.Series(p_div, index=sub.index))}] | FutSelf LS:[{eval_pos(pd.Series(p_self, index=sub.index))}] | Fwd60(s>+15%/<-15%): {hi_m.mean()*100 if len(hi_m) else np.nan:+5.1f}%/{lo_m.mean()*100 if len(lo_m) else np.nan:+5.1f}%")

for nm, k in [("生猪LH0", "生猪_LH0"), ("碳酸锂LC0", "碳酸锂_LC0"), ("铜CU0", "铜_CU0"), ("石油SC0", "石油_SC0"), ("黄金AU0", "黄金_AU0"), ("煤炭JM0", "煤炭_JM0")]:
    s_s, f_s = comm_map[k]
    test_stk_pred_fut(nm + "_全窗", s_s, f_s, "2016-01-04", "2026-11-20")
    test_stk_pred_fut(nm + "_25+",  s_s, f_s, "2025-01-02", "2026-11-20")

print("\n=== Q2 & Q5: 2025.01-2026.11.20 STOCK STRATEGIES & EXIT RULE ABLATION (生猪/碳酸锂/铜/油) ===")
def test_exits_and_2025(name, stk_c, stk_o_ret, com, start, end, is_lc=False):
    df = pd.DataFrame({"s": stk_c, "so_r": stk_o_ret, "c": com}).dropna()
    q_w = 252 if is_lc else 756
    df["c_pct"] = df["c"].rolling(q_w, min_periods=min(120, q_w)).rank(pct=True)
    df["c_dd"] = df["c"] / df["c"].rolling(252, min_periods=60).max() - 1.0
    df["s_ma60"] = df["s"].rolling(60).mean()
    df["s_ma20"] = df["s"].rolling(20).mean()
    df["c_ma60"] = df["c"].rolling(60).mean()
    df["s_r20"] = df["s"].pct_change(20)
    df["c_r20"] = df["c"].pct_change(20)
    df["c_r60"] = df["c"].pct_change(60)
    sub = df.loc[start:end].copy()
    if len(sub) < 100: return
    def sim(entry_cond, exit_cond, fee=0.003):
        pos = np.zeros(len(sub))
        in_p = False
        e_arr, x_arr = entry_cond.values, exit_cond.values
        for i in range(len(sub)):
            if not in_p and e_arr[i]: in_p = True
            elif in_p and x_arr[i]: in_p = False
            pos[i] = 1.0 if in_p else 0.0
        # execute t+1 open -> return from t+1 open to t+2 open = so_r.shift(-1), equivalent to pos.shift(1) * so_r_next
        p_s = pd.Series(pos, index=sub.index).shift(1).fillna(0.0)
        turn = p_s.diff().abs().fillna(0.0)
        # Daily open-to-open return for holding from day i open to day i+1 open is sub['so_r'].shift(-1)
        ret = p_s * sub["so_r"].shift(-1).fillna(0.0) - turn * (fee / 2.0)
        eq = (1.0 + ret).cumprod()
        yrs = len(sub) / 242.0
        cagr = (eq.iloc[-1] ** (1.0 / yrs) - 1.0) * 100.0
        mdd = (eq / eq.cummax() - 1.0).min() * 100.0
        return f"CAGR={cagr:+5.1f}%,MDD={mdd:5.1f}%,Exp={p_s.mean()*100:4.1f}%"

    ent_A = ((sub["c_pct"] < 0.25) | (sub["c_dd"] <= -0.25)) & (sub["s"] > sub["s_ma60"]) & (sub["s_r20"] > sub["c_r20"])
    ent_B = (sub["c"] > sub["c_ma60"]) & (sub["c_r60"] > 0.05)
    ex_orig = ((sub["c_pct"] > 0.85) & (sub["s"] < sub["s_ma20"])) | ((sub["s"] < sub["s_ma60"]).rolling(3).sum() == 3)
    ex_stk_only = (sub["s"] < sub["s_ma60"]).rolling(3).sum() == 3
    ex_comm_hot = (sub["c_pct"] > 0.75) | ((sub["s"] < sub["s_ma60"]).rolling(3).sum() == 3)
    ex_div_top = ((sub["c_r60"] > 0.15) & (sub["s"] < sub["s_ma20"])) | ((sub["s"] < sub["s_ma60"]).rolling(3).sum() == 3)
    ex_B = sub["c"] < sub["c_ma60"]
    bh = ((sub["s"].iloc[-1] / sub["s"].iloc[0]) ** (242.0 / len(sub)) - 1.0) * 100.0
    print(f"{name:14s} ({start[:4]}~{end[:4]}) | BH={bh:+5.1f}% | A_原卖:[{sim(ent_A, ex_orig)}] | A_纯破60:[{sim(ent_A, ex_stk_only)}] | A_商品热75卖:[{sim(ent_A, ex_comm_hot)}] | A_期强股弱20卖:[{sim(ent_A, ex_div_top)}] | B右:[{sim(ent_B, ex_B)}]")

for nm, bk, ck, lc in [("生猪现货", "生猪", "生猪_现货", False), ("碳酸锂LC0", "碳酸锂", "碳酸锂_LC0", True), ("铜HG", "铜", "铜_HG", False), ("石油SC0", "石油", "石油_SC0", False), ("黄金AU0", "黄金", "黄金_AU0", False), ("煤炭JM0", "煤炭", "煤炭_JM0", False)]:
    test_exits_and_2025(nm + "_全窗", baskets[bk], baskets_open[bk], comm_map[ck][1], "2016-01-04", "2026-11-20", is_lc=lc)
    test_exits_and_2025(nm + "_25+",  baskets[bk], baskets_open[bk], comm_map[ck][1], "2025-01-02", "2026-11-20", is_lc=lc)

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-6 Module E (Bonus Cross-Seat Brainstorm: US #11 + Research #1):
  US Second-Tier Bottleneck Leader Overnight Volume Surge -> A-Share 09:25 Unpriced Gap
  + Negative Reflexivity Minefield (US leader vol-dump while A-share opens up).
Strict PIT: latest US trading bar strictly < A-share buy_date (US 16:00 ET = CST ~04:00-05:00).
Peak RAM < 2.0 GB, single thread, zero yfinance.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import pickle
import sys
import time

import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _w2b6_common as cm
import wf_scorecard_engine as wf

# Map product_tree_map.json trees to US supply-chain leaders in us_price_db/all_daily.parquet
TREE_TO_US = [
    (["半导体设备", "MLCC"], ["LRCX", "AMAT", "KLAC", "ASML"]),
    (["AI算力", "光纤光缆"], ["NVDA", "AVGO", "COHR", "LITE", "MU", "TSM"]),
    (["AI供电", "可控核聚变", "电力/核电"], ["VRT", "ETN", "GEV", "CEG", "VST"]),
    (["GLP-1", "CXO", "创新药"], ["LLY", "NVO", "TMO"]),
    (["苹果新形态", "AI端侧"], ["AAPL", "QCOM"]),
    (["人形机器人", "智能驾驶", "电动车", "固态电池"], ["TSLA", "ALB"]),
    (["钨硬质合金", "战略小金属", "铜"], ["FCX", "SCCO"]),
    (["军工", "商业航天"], ["LMT", "RTX", "RKLB"]),
]


def load_us_leaders_map() -> tuple[pd.DataFrame, pd.DataFrame]:
    with open(f"{cm.DATA_DIR}/product_tree_map.json", encoding="utf-8") as f:
        ptm = json.load(f)

    rows = []
    for ts in ptm["tree_structure"]:
        tname = ts["tree"]
        us_list = None
        for keys, tickers in TREE_TO_US:
            if any(k in tname for k in keys):
                us_list = tickers
                break
        if not us_list:
            continue
        for node in ts.get("nodes", []):
            is_mm = 1 if node.get("is_mingmen", False) else 0
            for tk in node.get("tickers", []):
                c6 = str(tk.get("code", "")).zfill(6)
                if c6.startswith(("00", "60", "30", "688", "689")):
                    for ut in us_list:
                        rows.append((c6, ut, is_mm, tname))

    map_df = pd.DataFrame(rows, columns=["code", "us_ticker", "is_mingmen_node", "tree_name"])
    map_df = map_df.sort_values(["code", "us_ticker", "is_mingmen_node"], ascending=[True, True, False]).drop_duplicates(["code", "us_ticker"])

    all_us = sorted(map_df["us_ticker"].unique().tolist())
    us_p = pd.read_parquet(
        f"{cm.DATA_DIR}/us_price_db/all_daily.parquet",
        columns=["date", "ticker", "adj_close", "volume"],
        filters=[("ticker", "in", all_us)],
    )
    us_p["us_date"] = pd.to_datetime(us_p["date"]).dt.strftime("%Y-%m-%d")
    us_p = us_p[us_p["us_date"] >= "2020-11-01"].sort_values(["ticker", "us_date"]).reset_index(drop=True)
    g = us_p.groupby("ticker", sort=False)
    us_p["us_ret1d"] = (us_p["adj_close"] / g["adj_close"].shift(1) - 1.0) * 100.0
    us_p["us_ret3d"] = (us_p["adj_close"] / g["adj_close"].shift(3) - 1.0) * 100.0
    us_p["us_vol_r20"] = us_p["volume"] / g["volume"].transform(lambda s: s.rolling(20, min_periods=5).mean().shift(1))
    us_p = us_p[us_p["us_date"] <= "2026-11-16"].copy()
    return map_df, us_p[["us_date", "ticker", "us_ret1d", "us_ret3d", "us_vol_r20"]]


def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context(cm.BASE_DIR)
    px_idx = cm.PriceReturnIndex(end_cutoff="2026-11-25")
    cal_cn = sorted([d for d in v20_ctx["bench"]["trade_date"].tolist() if "2021-01-04" <= d <= "2026-11-16"])

    map_df, us_p = load_us_leaders_map()
    print(f"[ModE] Mapped A-share codes: {map_df['code'].nunique()} across {map_df['us_ticker'].nunique()} US leaders | RSS={cm.peak_rss_mb()} MB")

    # Align each CN trade_date strictly to latest US session < cn_date (merge_asof allow_exact_matches=False)
    cn_dt_df = pd.DataFrame({"buy_date": cal_cn, "cn_ts": pd.to_datetime(cal_cn)}).sort_values("cn_ts")
    us_p["us_ts"] = pd.to_datetime(us_p["us_date"])
    aligned_list = []
    for utk, grp in us_p.groupby("ticker"):
        m = pd.merge_asof(cn_dt_df, grp.sort_values("us_ts"), left_on="cn_ts", right_on="us_ts", direction="backward", allow_exact_matches=False)
        m["us_ticker"] = utk
        aligned_list.append(m[["buy_date", "us_ticker", "us_ret1d", "us_ret3d", "us_vol_r20"]])
    us_cn = pd.concat(aligned_list, ignore_index=True)

    # Filter US trigger days (surge >= +4% with vol_r20 >= 1.4, OR crash <= -4% with vol_r20 >= 1.4)
    us_trig = us_cn[(us_cn["us_ret1d"].abs() >= 4.0) & (us_cn["us_vol_r20"] >= 1.4)].copy()
    cands = us_trig.merge(map_df, on="us_ticker", how="inner")
    cands["abs_r"] = cands["us_ret1d"].abs()
    cands = cands.sort_values(["buy_date", "code", "abs_r"], ascending=[True, True, False]).drop_duplicates(["buy_date", "code"]).drop(columns=["abs_r", "tree_name", "us_ticker"]).reset_index(drop=True)
    print(f"[ModE] US shock -> A-share candidate events: {len(cands)}")

    horizons = (1, 3, 5)
    ret_df = px_idx.lookup_forward_returns(cands, horizons=horizons, buy_at="open", min_amt_yi=0.0)
    # Pre-filter using px_idx open_pct/amount_yi BEFORE heavy 140-col join to keep RSS < 1.6 GB!
    ret_df = ret_df[ret_df["can_buy"]].copy().reset_index(drop=True)
    # Attach open_pct from px_idx directly to filter PosGap/NegDump cleanly first
    op_vals = np.full(len(ret_df), np.nan, dtype=np.float32)
    for idx_r, (c_r, d_r) in enumerate(zip(ret_df["code"], ret_df["buy_date"])):
        cid = px_idx.c6_to_id.get(c_r, -1)
        did = px_idx.dt_to_id.get(d_r, -1)
        if cid >= 0 and did >= 0:
            s, e = px_idx.bounds[cid]
            dt_sub = px_idx.dt_id[s:e]
            rel = int(np.searchsorted(dt_sub, did))
            if rel < len(dt_sub) and int(dt_sub[rel]) == did:
                op_vals[idx_r] = px_idx.open_pct[s + rel]
    ret_df["_op_pre"] = op_vals
    keep_mask = ((ret_df["us_ret1d"] >= 4.0) & (ret_df["_op_pre"].between(-2.0, 3.0))) | ((ret_df["us_ret1d"] <= -4.0) & (ret_df["_op_pre"] >= 1.5))
    ret_df = ret_df[keep_mask].drop(columns=["_op_pre"]).reset_index(drop=True)
    del cands, us_trig, us_cn, us_p, map_df
    gc.collect()

    feat_df, fcols = cm.attach_pit_features(ret_df, buy_at="open", extra_cols=["us_ret1d", "us_ret3d", "us_vol_r20", "is_mingmen_node"])
    del ret_df
    gc.collect()
    feat_df = feat_df[feat_df["can_buy"] & (feat_df["amount_yi_t1"] >= 0.8)].copy().reset_index(drop=True)
    feat_df["us_a_unpriced_gap"] = feat_df["us_ret1d"] - feat_df["open_pct"]

    # Audit Positive Unpriced Gap vs Negative Trap (US dump <= -4% & A-share open >= +1.5%)
    trap_audit = {}
    for h in horizons:
        rc = f"gross_ret_h{h}"
        sub_v = feat_df[feat_df[rc].notna()].copy()
        sub_v["net_r"] = (1.0 + sub_v[rc]) * (1.0 - 0.0030) - 1.0
        pos_m = (sub_v["us_ret1d"] >= 4.0) & (sub_v["open_pct"].between(-1.5, 2.5))
        neg_m = (sub_v["us_ret1d"] <= -4.0) & (sub_v["open_pct"] >= 1.5)
        trap_audit[f"H{h}"] = {
            "Pos_US_Up_A_FlatOpen": {
                "n": int(pos_m.sum()),
                "wr_pct": round(float((sub_v.loc[pos_m, "net_r"] > 0).mean() * 100.0), 2) if pos_m.any() else 0.0,
                "mean_pct": round(float(sub_v.loc[pos_m, "net_r"].mean() * 100.0), 3) if pos_m.any() else 0.0,
            },
            "Neg_US_Dump_A_GapUp": {
                "n": int(neg_m.sum()),
                "wr_pct": round(float((sub_v.loc[neg_m, "net_r"] > 0).mean() * 100.0), 2) if neg_m.any() else 0.0,
                "mean_pct": round(float(sub_v.loc[neg_m, "net_r"].mean() * 100.0), 3) if neg_m.any() else 0.0,
            },
        }
        print(f"[ModE Trap Audit H{h}] PosGap={trap_audit[f'H{h}']['Pos_US_Up_A_FlatOpen']} | NegDump={trap_audit[f'H{h}']['Neg_US_Dump_A_GapUp']}")

    fcols = fcols + ["us_a_unpriced_gap"]
    pools = {
        "E1_US4pct_A_Unpriced": (
            feat_df[(feat_df["us_ret1d"] >= 4.0) & (feat_df["open_pct"].between(-2.0, 3.0))].copy().reset_index(drop=True),
            "monthly",
        ),
        "E2_US6pct2xVol_A_Unpriced": (
            feat_df[(feat_df["us_ret1d"] >= 6.0) & (feat_df["us_vol_r20"] >= 2.0) & (feat_df["open_pct"].between(-1.5, 2.5))].copy().reset_index(drop=True),
            "daily",
        ),
        "E3_US4pct_MingmenOnly": (
            feat_df[(feat_df["us_ret1d"] >= 4.0) & (feat_df["is_mingmen_node"] == 1) & (feat_df["open_pct"].between(-2.0, 3.0))].copy().reset_index(drop=True),
            "daily_h1_else_monthly",
        ),
    }
    del feat_df
    gc.collect()

    results = []
    for pname, (pdf, rfreq_cfg) in pools.items():
        print(f"[ModE] Pool {pname}: {len(pdf)} rows across {pdf['buy_date'].nunique()} days ({rfreq_cfg})")
        for h in horizons:
            rfreq = "daily" if (rfreq_cfg == "daily" or (rfreq_cfg == "daily_h1_else_monthly" and h == 1)) else "monthly"
            sub = pdf.copy()
            sub["exit_date"] = sub[f"exit_date_h{h}"]
            sub["gross_ret"] = sub[f"gross_ret_h{h}"]
            sub = sub[(sub["exit_date"] > sub["buy_date"]) & sub["gross_ret"].notna()].reset_index(drop=True)
            tid = f"ModE_{pname}_H{h}"
            res = cm.evaluate_and_audit_track(
                track_id=tid,
                module_name="ModuleE_USBottleneckGap",
                desc=f"{pname} hold {h}d (open, {rfreq})",
                cand_df=sub,
                feature_cols=fcols,
                px_idx=px_idx,
                v20_ctx=v20_ctx,
                buy_at="open",
                thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80),
                recalc_freq=rfreq,
                min_warmup_trades=80 if len(sub) >= 1500 else 35,
                min_warmup_trades_rare=40 if len(sub) >= 1500 else 20,
                perm_n=1000,
                run_trunc_check=(h == 1),
                trunc_threshold="top20",
            )
            br = res["best_row"]
            t_pass = res["truncation_20241231"]["zero_leakage_pass"] if res["truncation_20241231"] else "NA"
            print(f"  -> {tid:30s} best={br['threshold']:8s} n={br['n_trades_wf']:3d} WR={br['wr_wf_pct']:5.1f}% mean={br['mean_wf_pct']:5.2f}% NAV={br['nav_wf']:6.3f} ex5={br['ex5_wf']:6.3f} Sh={br['sharpe_wf']:5.2f} dNAV_V20={br['patch_delta_nav_ratio']:6.4f} p={br['perm_sd_p']} trunc={t_pass}")
            results.append(res)

    out_pkl = f"{cm.OUT_DIR}/_modE_results.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump({"results": results, "trap_audit": trap_audit}, f)
    print(f"[ModE] Completed in {time.time()-t0:.1f}s | Peak RSS={cm.peak_rss_mb()} MB -> {out_pkl}")


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Ablation Check on ModE_E3 (prev_streak == 0 pure non-limit-up vs all) + ModA/ModC check.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
import gc, json, pickle, sys, time
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
import _w2b6_common as cm
import wf_scorecard_engine as wf
import run_w2b6_modE_us_gap as mE

def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context(cm.BASE_DIR)
    px_idx = cm.PriceReturnIndex(end_cutoff="2026-11-25")
    cal_cn = sorted([d for d in v20_ctx["bench"]["trade_date"].tolist() if "2021-01-04" <= d <= "2026-11-16"])
    map_df, us_p = mE.load_us_leaders_map()
    cn_dt_df = pd.DataFrame({"buy_date": cal_cn, "cn_ts": pd.to_datetime(cal_cn)}).sort_values("cn_ts")
    us_p["us_ts"] = pd.to_datetime(us_p["us_date"])
    aligned_list = []
    for utk, grp in us_p.groupby("ticker"):
        m = pd.merge_asof(cn_dt_df, grp.sort_values("us_ts"), left_on="cn_ts", right_on="us_ts", direction="backward", allow_exact_matches=False)
        m["us_ticker"] = utk
        aligned_list.append(m[["buy_date", "us_ticker", "us_ret1d", "us_ret3d", "us_vol_r20"]])
    us_cn = pd.concat(aligned_list, ignore_index=True)
    us_trig = us_cn[(us_cn["us_ret1d"] >= 4.0) & (us_cn["us_vol_r20"] >= 1.4)].copy()
    cands = us_trig.merge(map_df[map_df["is_mingmen_node"] == 1], on="us_ticker", how="inner")
    cands = cands.sort_values(["buy_date", "code", "us_ret1d"], ascending=[True, True, False]).drop_duplicates(["buy_date", "code"]).drop(columns=["tree_name", "us_ticker"]).reset_index(drop=True)
    ret_df = px_idx.lookup_forward_returns(cands, horizons=(1,), buy_at="open", min_amt_yi=0.0)
    ret_df = ret_df[ret_df["can_buy"]].copy().reset_index(drop=True)
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
    ret_df = ret_df[(op_vals >= -2.0) & (op_vals <= 3.0)].copy().reset_index(drop=True)
    del cands, us_trig, us_cn, us_p, map_df
    gc.collect()
    feat_df, fcols = cm.attach_pit_features(ret_df, buy_at="open", extra_cols=["us_ret1d", "us_ret3d", "us_vol_r20", "is_mingmen_node"])
    del ret_df
    gc.collect()
    feat_df["us_a_unpriced_gap"] = feat_df["us_ret1d"] - feat_df["open_pct"]
    fcols.append("us_a_unpriced_gap")
    sub = feat_df[(feat_df["amount_yi_t1"] >= 0.8) & (feat_df["prev_streak"] == 0)].copy().reset_index(drop=True)
    sub["exit_date"] = sub["exit_date_h1"]
    sub["gross_ret"] = sub["gross_ret_h1"]
    sub = sub[(sub["exit_date"] > sub["buy_date"]) & sub["gross_ret"].notna()].reset_index(drop=True)
    del feat_df
    gc.collect()
    res = cm.evaluate_and_audit_track(
        track_id="ModE_E3b_Mingmen_NoZT_H1",
        module_name="ModuleE_USBottleneckGap",
        desc="E3b US>=4% Mingmen prev_streak==0 hold 1d (daily)",
        cand_df=sub,
        feature_cols=fcols,
        px_idx=px_idx,
        v20_ctx=v20_ctx,
        buy_at="open",
        thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80),
        recalc_freq="daily",
        min_warmup_trades=80,
        min_warmup_trades_rare=40,
        perm_n=1000,
        run_trunc_check=True,
        trunc_threshold="top5",
    )
    br = res["best_row"]
    print(f"[ModE_E3b_NoZT] best={br['threshold']} n={br['n_trades_wf']} WR={br['wr_wf_pct']}% mean={br['mean_wf_pct']}% NAV={br['nav_wf']} ex5={br['ex5_wf']} Sh={br['sharpe_wf']} dNAV_V20={br['patch_delta_nav_ratio']} p={br['perm_sd_p']} trunc={res['truncation_20241231']['zero_leakage_pass']} | RSS={cm.peak_rss_mb()} MB")
    with open(f"{cm.OUT_DIR}/_modE_results.pkl", "rb") as f:
        dE = pickle.load(f)
    dE["results"] = [r for r in dE["results"] if r["track_id"] != "ModE_E3b_Mingmen_NoZT_H1"] + [res]
    with open(f"{cm.OUT_DIR}/_modE_results.pkl", "wb") as f:
        pickle.dump(dE, f)

if __name__ == "__main__":
    main()

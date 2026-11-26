#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-6 Module A (Ultra-Low-RSS Streaming Edition < 1.5 GB):
39% V20 Empty-Slot Full-Market Unbiased Multi-Factor Scorecard Blind Mining.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import pickle
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _w2b6_common as cm
import wf_scorecard_engine as wf


def build_module_a_pools(empty_dts: list[str]) -> dict[str, tuple[pd.DataFrame, str]]:
    """Filter each 100k batch on-the-fly so peak RAM stays well under 1.5 GB."""
    cols = [
        "c6", "dt", "open", "close", "open_pct", "ret_1d", "clv",
        "is_zt", "is_dt", "is_yizi_zt", "is_yizi_dt", "is_st_pit", "is_20cm",
        "amount_yi", "amount_yi_t1", "ret_1d_t1", "prev_clv", "prev_streak",
        "vol_ratio5_t1", "ret_5d_t1", "ret_20d_t1", "dd_20d_t1", "bias20_t1",
        "down_streak_t1",
    ]
    emp_set = set(empty_dts)
    pf = pq.ParquetFile(cm.STOCK_DAY_PQ)
    acc = {k: [] for k in ("a1c", "a1o", "a2c", "a3c", "a3o", "a4")}

    for i_b, batch in enumerate(pf.iter_batches(batch_size=100_000, columns=cols)):
        b_df = batch.to_pandas(categories=["c6", "dt"])
        dt_cats = b_df["dt"].cat.categories.astype(str).str[:10]
        valid_dc = set(np.flatnonzero(dt_cats.isin(emp_set)))
        if not valid_dc:
            continue
        m_emp = b_df["dt"].cat.codes.isin(valid_dc).to_numpy()
        if not m_emp.any():
            continue
        df = b_df.loc[m_emp].copy()
        c6_cats = df["c6"].cat.categories.astype(str).str.zfill(6).to_numpy()
        dt_cats_arr = df["dt"].cat.categories.astype(str).str[:10].to_numpy()
        df["buy_date"] = dt_cats_arr[df["dt"].cat.codes.to_numpy()]
        df["code"] = c6_cats[df["c6"].cat.codes.to_numpy()]

        non_st = (df["is_st_pit"] == 0) & (df["is_yizi_zt"] == 0) & (df["is_yizi_dt"] == 0)
        lim_pct = np.where(df["is_20cm"] == 1, 19.5, 9.5)
        intraday_oc = ((df["close"] / np.maximum(1e-6, df["open"])) - 1.0) * 100.0

        m_a1c = (
            non_st & (df["is_zt"] == 0) & (df["is_dt"] == 0)
            & (df["amount_yi"] >= 1.5) & (df["ret_1d"] >= 2.0) & (df["ret_1d"] < lim_pct)
            & (intraday_oc >= 1.0) & (df["clv"] >= 0.65)
            & (df["amount_yi"] >= 1.2 * np.maximum(0.1, df["amount_yi_t1"].fillna(0.0)))
        )
        if m_a1c.any():
            s1 = df.loc[m_a1c, ["buy_date", "code", "amount_yi", "ret_1d"]].copy()
            s1["_rk"] = s1["amount_yi"] * np.maximum(0.5, s1["ret_1d"])
            acc["a1c"].append(s1[["buy_date", "code", "_rk"]])

        m_a1o = (
            non_st & (df["prev_streak"] == 0) & (df["amount_yi_t1"] >= 1.5)
            & (df["ret_1d_t1"].between(2.0, 9.5)) & (df["prev_clv"] >= 0.65)
            & (df["vol_ratio5_t1"] >= 1.25) & (df["open_pct"].between(-3.0, 4.5))
        )
        if m_a1o.any():
            acc["a1o"].append(df.loc[m_a1o, ["buy_date", "code", "amount_yi_t1"]].rename(columns={"amount_yi_t1": "_rk"}))

        m_a2c = (
            non_st & (df["is_zt"] == 0) & (df["is_dt"] == 0) & (df["amount_yi"] >= 1.0)
            & (df["ret_20d_t1"] >= 5.0) & (df["ret_5d_t1"].between(-12.0, -0.5))
            & (df["amount_yi"] <= 0.85 * np.maximum(0.1, df["amount_yi_t1"].fillna(0.0)))
            & (df["ret_1d"].between(-1.5, 4.5)) & (df["clv"] >= 0.55)
        )
        if m_a2c.any():
            acc["a2c"].append(df.loc[m_a2c, ["buy_date", "code", "amount_yi_t1"]].rename(columns={"amount_yi_t1": "_rk"}))

        m_a3c = (
            non_st & (df["is_zt"] == 0) & (df["is_dt"] == 0) & (df["amount_yi"] >= 1.0)
            & ((df["dd_20d_t1"] <= -15.0) | (df["bias20_t1"] <= -8.0))
            & ((df["down_streak_t1"] >= 2) | (df["ret_5d_t1"] <= -7.0))
            & (df["ret_1d"] >= 0.5) & (df["ret_1d"] < lim_pct) & (df["clv"] >= 0.60)
        )
        if m_a3c.any():
            acc["a3c"].append(df.loc[m_a3c, ["buy_date", "code", "amount_yi"]].rename(columns={"amount_yi": "_rk"}))

        m_a3o = (
            non_st & (df["amount_yi_t1"] >= 1.0)
            & ((df["dd_20d_t1"] <= -15.0) | (df["bias20_t1"] <= -9.0))
            & (df["down_streak_t1"] >= 3) & (df["open_pct"].between(-2.5, 3.0))
        )
        if m_a3o.any():
            s3o = df.loc[m_a3o, ["buy_date", "code", "bias20_t1"]].copy()
            s3o["_rk"] = -s3o["bias20_t1"]
            acc["a3o"].append(s3o[["buy_date", "code", "_rk"]])

        m_a4 = (
            non_st & (df["is_zt"] == 0) & (df["is_dt"] == 0)
            & (df["amount_yi"] >= 2.0) & (df["ret_1d"].abs() < 9.5)
        )
        if m_a4.any():
            acc["a4"].append(df.loc[m_a4, ["buy_date", "code", "amount_yi", "ret_1d"]])

        if i_b % 10 == 0:
            pa.default_memory_pool().release_unused()

    pa.default_memory_pool().release_unused()
    gc.collect()

    def _top30(lst):
        d = pd.concat(lst, ignore_index=True)
        return d.sort_values(["buy_date", "_rk"], ascending=[True, False]).groupby("buy_date", as_index=False).head(30)[["buy_date", "code"]].reset_index(drop=True)

    d4 = pd.concat(acc["a4"], ignore_index=True)
    top_amt = d4.sort_values(["buy_date", "amount_yi"], ascending=[True, False]).groupby("buy_date", as_index=False).head(25)
    top_mom = d4.sort_values(["buy_date", "ret_1d"], ascending=[True, False]).groupby("buy_date", as_index=False).head(25)
    p_a4 = pd.concat([top_amt, top_mom], ignore_index=True).drop_duplicates(["buy_date", "code"])[["buy_date", "code"]].reset_index(drop=True)

    pools = {
        "A1_ActiveYang_Close": (_top30(acc["a1c"]), "close"),
        "A1_ActiveYang_Open": (_top30(acc["a1o"]), "open"),
        "A2_ShrinkPullback_Close": (_top30(acc["a2c"]), "close"),
        "A3_OversoldBounce_Close": (_top30(acc["a3c"]), "close"),
        "A3_OversoldBounce_Open": (_top30(acc["a3o"]), "open"),
        "A4_Top50Unbiased_Close": (p_a4, "close"),
    }
    del acc, d4, top_amt, top_mom
    gc.collect()
    return pools


def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context(cm.BASE_DIR)
    cal = v20_ctx["calendar_5y"]
    empty_dts = sorted(cal.loc[cal["v20_empty_slot"] & (~cal["v20_has_stier_wait"]), "trade_date"].tolist())
    print(f"[ModA] V20 strict empty dates: {len(empty_dts)} ({empty_dts[0]}..{empty_dts[-1]})")

    px_idx = cm.PriceReturnIndex(end_cutoff="2026-11-25")
    print(f"[ModA] PriceReturnIndex loaded in {time.time()-t0:.1f}s | RSS={cm.peak_rss_mb()} MB")

    pools = build_module_a_pools(empty_dts)
    print(f"[ModA] Pools built | RSS={cm.peak_rss_mb()} MB")
    for k, (pdf, ba) in pools.items():
        print(f"  Pool {k} ({ba}): {len(pdf)} cands across {pdf['buy_date'].nunique()} days")

    all_track_results = []
    horizons = (1, 2, 3, 5)
    for pool_name, (raw_df, buy_at) in pools.items():
        ret_df = px_idx.lookup_forward_returns(raw_df, horizons=horizons, buy_at=buy_at, min_amt_yi=(1.0 if buy_at == "close" else 0.0))
        feat_df, fcols = cm.attach_pit_features(ret_df, buy_at=buy_at)
        del ret_df
        gc.collect()
        print(f"[ModA] {pool_name}: joined {len(feat_df)} rows x {len(fcols)} PIT cols | RSS={cm.peak_rss_mb()} MB")

        for h in horizons:
            sub = feat_df.copy()
            sub["exit_date"] = sub[f"exit_date_h{h}"]
            sub["gross_ret"] = sub[f"gross_ret_h{h}"]
            sub = sub[sub["can_buy"] & (sub["exit_date"] > sub["buy_date"]) & sub["gross_ret"].notna()].reset_index(drop=True)
            tid = f"ModA_{pool_name}_H{h}"
            res = cm.evaluate_and_audit_track(
                track_id=tid,
                module_name="ModuleA_EmptyBlind",
                desc=f"{pool_name} hold {h}d ({buy_at})",
                cand_df=sub,
                feature_cols=fcols,
                px_idx=px_idx,
                v20_ctx=v20_ctx,
                buy_at=buy_at,
                thresholds=("all_cands", "top30", "top20", "top10", 70, 75),
                recalc_freq="monthly",
                min_warmup_trades=80,
                min_warmup_trades_rare=40,
                perm_n=200,
                run_trunc_check=False,
            )
            br = res["best_row"]
            print(f"  -> {tid:34s} best={br['threshold']:8s} n={br['n_trades_wf']:3d} WR={br['wr_wf_pct']:5.1f}% mean={br['mean_wf_pct']:5.2f}% NAV={br['nav_wf']:6.3f} ex5={br['ex5_wf']:6.3f} Sh={br['sharpe_wf']:5.2f} MDD={br['mdd_wf_pct']:5.1f}% corrV20={br['corr_v20_wf']:6.3f} dNAV_V20={br['patch_delta_nav_ratio']:6.4f}")
            res["best_slot_df"] = None
            all_track_results.append(res)
            del sub
            gc.collect()
        del feat_df
        gc.collect()

    ranked = sorted(
        all_track_results,
        key=lambda r: (
            r["best_row"]["patch_delta_nav_ratio"] > 1.0,
            r["best_row"]["sharpe_wf"] if r["best_row"]["n_trades_wf"] >= 20 else -99.0,
        ),
        reverse=True,
    )
    top_ids = [r["track_id"] for r in ranked[:4]]
    print(f"\n[ModA] Re-running top 4 in DAILY recalc + 1000x perm + 2024-12-31 truncation check: {top_ids}")

    daily_top_results = []
    for tid in top_ids:
        pool_name, h_str = tid[len("ModA_"):].rsplit("_H", 1)
        h = int(h_str)
        raw_df, buy_at = pools[pool_name]
        ret_df = px_idx.lookup_forward_returns(raw_df, horizons=(h,), buy_at=buy_at, min_amt_yi=(1.0 if buy_at == "close" else 0.0))
        feat_df, fcols = cm.attach_pit_features(ret_df, buy_at=buy_at)
        sub = feat_df.copy()
        sub["exit_date"] = sub[f"exit_date_h{h}"]
        sub["gross_ret"] = sub[f"gross_ret_h{h}"]
        sub = sub[sub["can_buy"] & (sub["exit_date"] > sub["buy_date"]) & sub["gross_ret"].notna()].reset_index(drop=True)
        res_d = cm.evaluate_and_audit_track(
            track_id=f"{tid}_DAILY",
            module_name="ModuleA_EmptyBlind_Daily",
            desc=f"{pool_name} hold {h}d ({buy_at}, daily recalc)",
            cand_df=sub,
            feature_cols=fcols,
            px_idx=px_idx,
            v20_ctx=v20_ctx,
            buy_at=buy_at,
            thresholds=("all_cands", "top30", "top20", "top10", 70, 75),
            recalc_freq="daily",
            min_warmup_trades=80,
            min_warmup_trades_rare=40,
            perm_n=1000,
            run_trunc_check=True,
            trunc_threshold="top20",
        )
        br = res_d["best_row"]
        print(f"  [DAILY] {res_d['track_id']} best={br['threshold']} n={br['n_trades_wf']} NAV={br['nav_wf']} Sh={br['sharpe_wf']} perm_sd={br['perm_sd_p']} trunc={res_d['truncation_20241231']['zero_leakage_pass']}")
        daily_top_results.append(res_d)
        del ret_df, feat_df, sub
        gc.collect()

    out_pkl = f"{cm.OUT_DIR}/_modA_results.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump({"sweep_monthly": all_track_results, "top_daily": daily_top_results}, f)
    print(f"[ModA] Completed in {time.time()-t0:.1f}s | Peak RSS={cm.peak_rss_mb()} MB -> {out_pkl}")


if __name__ == "__main__":
    main()

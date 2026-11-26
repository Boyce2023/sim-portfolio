#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-6 Module D:
US Brainstorm #5 — 5-Minute Intraday Microstructure Divergence:
  Smart_Close (14:00 -> 14:55) - Retail_Impulse (overnight + 09:30 -> 10:00)
Evaluates BOTH:
  1. Positive Score: Continuous morning wash + tail institutional push -> close-buy T 15:00 (2021..2026 full coverage) & T-1 multi-day open-buy
  2. Negative Reflexivity / Minefield Penalty: Morning surge + afternoon bleed-out (Retail_Impulse >= +2%, Smart_Close <= -1%)
Peak RAM < 2.0 GB, single thread, zero yfinance.
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

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _w2b6_common as cm
import wf_scorecard_engine as wf


def extract_5m_micro_features(px_idx: cm.PriceReturnIndex) -> pd.DataFrame:
    """
    Compute 5m Smart_Close (14:00->14:55), Retail_Impulse (prev_close->10:00),
    tail volume share, and afternoon bleed strictly up to 14:55 (before 15:00 buy!).
    """
    p5 = f"{cm.DATA_DIR}/all_strategies_5m_complete_pit.parquet"
    df5 = pd.read_parquet(p5, columns=["c6", "date", "hhmm_int", "open", "close", "amount"])
    df5["c6"] = df5["c6"].astype(str).str.zfill(6)
    df5["date"] = df5["date"].astype(str).str[:10]
    df5 = df5[(df5["date"] <= "2026-11-16") & (df5["hhmm_int"] <= 1455)].copy()

    tot_amt = df5.groupby(["date", "c6"], sort=False)["amount"].sum()
    tail_amt = df5[df5["hhmm_int"] >= 1405].groupby(["date", "c6"], sort=False)["amount"].sum()
    morn_amt = df5[df5["hhmm_int"] <= 1000].groupby(["date", "c6"], sort=False)["amount"].sum()

    piv_c = df5[df5["hhmm_int"].isin([1000, 1130, 1400, 1455])].pivot(index=["date", "c6"], columns="hhmm_int", values="close")
    piv_o935 = df5[df5["hhmm_int"] == 935].set_index(["date", "c6"])["open"]
    del df5
    gc.collect()

    feat = pd.DataFrame({
        "o_0930": piv_o935,
        "c_1000": piv_c.get(1000),
        "c_1130": piv_c.get(1130),
        "c_1400": piv_c.get(1400),
        "c_1455": piv_c.get(1455),
        "amt_tot": tot_amt,
        "amt_tail": tail_amt,
        "amt_morn": morn_amt,
    }).reset_index()
    del piv_c, piv_o935, tot_amt, tail_amt, morn_amt
    gc.collect()

    feat.rename(columns={"date": "buy_date", "c6": "code"}, inplace=True)
    # Join prev_close_raw strictly from stock_day_core_features_pit (via Attach or reading 3 cols)
    import pyarrow as pa
    import pyarrow.parquet as pq
    pf = pq.ParquetFile(cm.STOCK_DAY_PQ)
    pair_set = set(zip(feat["buy_date"], feat["code"]))
    dt_set = set(feat["buy_date"].unique())
    prev_chunks = []
    for i_b, batch in enumerate(pf.iter_batches(batch_size=100_000, columns=["c6", "dt", "prev_close_raw", "close"])):
        b_df = batch.to_pandas(categories=["c6", "dt"])
        dt_cats = b_df["dt"].cat.categories.astype(str).str[:10]
        valid_dc = set(np.flatnonzero(dt_cats.isin(dt_set)))
        if not valid_dc:
            continue
        m = b_df["dt"].cat.codes.isin(valid_dc).to_numpy()
        if not m.any():
            continue
        sub = b_df.loc[m].copy()
        c6_cats = sub["c6"].cat.categories.astype(str).str.zfill(6).to_numpy()
        dt_cats_arr = sub["dt"].cat.categories.astype(str).str[:10].to_numpy()
        bc = c6_cats[sub["c6"].cat.codes.to_numpy()]
        bd = dt_cats_arr[sub["dt"].cat.codes.to_numpy()]
        mp = np.array([(d, c) in pair_set for d, c in zip(bd, bc)], dtype=bool)
        if mp.any():
            hit = sub.loc[mp].copy()
            hit["buy_date"] = bd[mp]
            hit["code"] = bc[mp]
            hit.drop(columns=["c6", "dt"], inplace=True)
            prev_chunks.append(hit)
        if i_b % 10 == 0:
            pa.default_memory_pool().release_unused()
    pc_df = pd.concat(prev_chunks, ignore_index=True).drop_duplicates(["buy_date", "code"])
    feat = feat.merge(pc_df, on=["buy_date", "code"], how="inner")
    del prev_chunks, pc_df
    gc.collect()

    # Check raw price alignment (5m prices are unadjusted raw; prev_close_raw is ex-div adjusted prev close!)
    pc = feat["prev_close_raw"].to_numpy(float)
    ok = np.isfinite(pc) & (pc > 0) & (feat["c_1455"] > 0) & (feat["c_1400"] > 0) & (feat["c_1000"] > 0)
    feat = feat[ok].copy().reset_index(drop=True)

    feat["m5_retail_impulse_pct"] = (feat["c_1000"] / feat["prev_close_raw"] - 1.0) * 100.0
    feat["m5_morning_30m_pct"] = (feat["c_1000"] / feat["o_0930"] - 1.0) * 100.0
    feat["m5_smart_close_pct"] = (feat["c_1455"] / feat["c_1400"] - 1.0) * 100.0
    feat["m5_aft_ret_pct"] = (feat["c_1455"] / feat["c_1130"] - 1.0) * 100.0
    feat["m5_smart_div_pct"] = feat["m5_smart_close_pct"] - feat["m5_retail_impulse_pct"]
    feat["m5_aft_div_pct"] = feat["m5_aft_ret_pct"] - feat["m5_retail_impulse_pct"]
    feat["m5_tail_amt_share"] = np.where(feat["amt_tot"] > 0, feat["amt_tail"].fillna(0.0) / feat["amt_tot"], 0.0)
    feat["m5_morn_amt_share"] = np.where(feat["amt_tot"] > 0, feat["amt_morn"].fillna(0.0) / feat["amt_tot"], 0.0)
    feat["m5_tail_vs_morn_ratio"] = np.where(feat["m5_morn_amt_share"] > 0.01, feat["m5_tail_amt_share"] / feat["m5_morn_amt_share"], 0.0)

    # Also compute consecutive-day / rolling 5d 5m features if stock appeared in past 5 trading days
    cal_arr = px_idx.dt_list
    dt_to_i = px_idx.dt_to_id
    feat["ti"] = feat["buy_date"].map(dt_to_i).fillna(-1).astype(np.int32)
    feat = feat[feat["ti"] >= 0].sort_values(["code", "ti"]).reset_index(drop=True)

    c_arr = feat["code"].to_numpy()
    t_arr = feat["ti"].to_numpy()
    sd_arr = feat["m5_smart_div_pct"].to_numpy(float)
    sc_arr = feat["m5_smart_close_pct"].to_numpy(float)
    ri_arr = feat["m5_retail_impulse_pct"].to_numpy(float)

    n = len(feat)
    roll5_cnt = np.zeros(n, dtype=np.int8)
    roll5_smart_div = np.full(n, np.nan, dtype=np.float32)
    roll5_pos_days = np.zeros(n, dtype=np.int8)
    roll5_neg_days = np.zeros(n, dtype=np.int8)

    brk = np.flatnonzero(c_arr[1:] != c_arr[:-1]) + 1
    for s, e in zip(np.concatenate(([0], brk)), np.concatenate((brk, [n]))):
        ts = t_arr[s:e]
        for k in range(e - s):
            tk = ts[k]
            vals = []
            pos_c, neg_c = 0, 0
            for j in range(k, -1, -1):
                if tk - ts[j] <= 4:
                    vals.append(sd_arr[s + j])
                    if sc_arr[s + j] > 0.2 and ri_arr[s + j] < 0.5:
                        pos_c += 1
                    if ri_arr[s + j] >= 2.0 and sc_arr[s + j] <= -0.5:
                        neg_c += 1
                else:
                    break
            roll5_cnt[s + k] = len(vals)
            roll5_smart_div[s + k] = float(np.mean(vals))
            roll5_pos_days[s + k] = pos_c
            roll5_neg_days[s + k] = neg_c

    feat["m5_roll5_obs_cnt"] = roll5_cnt
    feat["m5_roll5_smart_div_mean"] = roll5_smart_div
    feat["m5_roll5_inst_push_days"] = roll5_pos_days
    feat["m5_roll5_retail_dump_days"] = roll5_neg_days
    feat.drop(columns=["o_0930", "c_1000", "c_1130", "c_1400", "c_1455", "amt_tot", "amt_tail", "amt_morn", "prev_close_raw", "close", "ti"], inplace=True)
    return feat


def main():
    t0 = time.time()
    v20_ctx = wf.load_v20_reference_context(cm.BASE_DIR)
    px_idx = cm.PriceReturnIndex(end_cutoff="2026-11-25")

    m5_df = extract_5m_micro_features(px_idx)
    print(f"[ModD] Extracted 5m micro features: {len(m5_df)} pairs | yr={m5_df['buy_date'].str[:4].value_counts().sort_index().to_dict()} | RSS={cm.peak_rss_mb()} MB")

    horizons = (1, 3, 5)
    ret_df = px_idx.lookup_forward_returns(m5_df, horizons=horizons, buy_at="close", min_amt_yi=0.5)
    m5_extra = [
        "m5_retail_impulse_pct", "m5_morning_30m_pct", "m5_smart_close_pct",
        "m5_aft_ret_pct", "m5_smart_div_pct", "m5_aft_div_pct",
        "m5_tail_amt_share", "m5_morn_amt_share", "m5_tail_vs_morn_ratio",
        "m5_roll5_obs_cnt", "m5_roll5_smart_div_mean",
        "m5_roll5_inst_push_days", "m5_roll5_retail_dump_days",
    ]
    feat_df, fcols = cm.attach_pit_features(ret_df, buy_at="close", extra_cols=m5_extra)
    feat_df = feat_df[feat_df["can_buy"]].copy().reset_index(drop=True)
    del m5_df, ret_df
    gc.collect()

    # Diagnostic bucket comparison: Positive Inst Push vs Neutral vs Negative Minefield (Morning Surge + Afternoon Bleed)
    bucket_audit = {}
    for h in horizons:
        r_col = f"gross_ret_h{h}"
        sub_v = feat_df[feat_df[r_col].notna()].copy()
        sub_v["net_r"] = (1.0 + sub_v[r_col]) * (1.0 - 0.0030) - 1.0
        pos_m = (sub_v["m5_smart_close_pct"] >= 0.5) & (sub_v["m5_retail_impulse_pct"] <= 1.0) & (sub_v["m5_smart_div_pct"] >= 1.5)
        neg_m = (sub_v["m5_retail_impulse_pct"] >= 2.0) & (sub_v["m5_smart_close_pct"] <= -0.8) & (sub_v["m5_smart_div_pct"] <= -3.5)
        b_stats = {}
        for label, m in [("Positive_InstWashPush", pos_m), ("Neutral_Other", ~(pos_m | neg_m)), ("Negative_RetailTrapBleed", neg_m)]:
            arr = sub_v.loc[m, "net_r"].to_numpy(float)
            arr_wf = sub_v.loc[m & (sub_v["buy_date"] >= "2023-01-03"), "net_r"].to_numpy(float)
            b_stats[label] = {
                "n_all": int(len(arr)),
                "wr_all_pct": round(float((arr > 0).mean() * 100.0), 2) if len(arr) else 0.0,
                "mean_all_pct": round(float(arr.mean() * 100.0), 3) if len(arr) else 0.0,
                "n_wf": int(len(arr_wf)),
                "wr_wf_pct": round(float((arr_wf > 0).mean() * 100.0), 2) if len(arr_wf) else 0.0,
                "mean_wf_pct": round(float(arr_wf.mean() * 100.0), 3) if len(arr_wf) else 0.0,
            }
        bucket_audit[f"H{h}"] = b_stats
        print(f"[ModD Bucket H{h}] Pos={b_stats['Positive_InstWashPush']['mean_wf_pct']}% (n={b_stats['Positive_InstWashPush']['n_wf']}) vs NegMine={b_stats['Negative_RetailTrapBleed']['mean_wf_pct']}% (n={b_stats['Negative_RetailTrapBleed']['n_wf']})")

    # Run WF Scorecard Mode A on:
    #   D1_5m_AllPool: full 5m universe (learning positive Smart_Div & negative Retail_Trap weights causally)
    #   D2_5m_ExclTrap: exclude Negative Retail Trap (m5_retail_impulse>=2 & smart_close<=-0.8)
    #   D3_5m_InstDivOnly: focus on Positive Divergence (smart_div >= 0.5)
    #   D4_5m_OnlyM5Features: pure 5m microstructure features alone (ablation proving 5m signal alpha!)
    # Run sequentially without duplicating all 4 large DataFrames simultaneously in memory
    pool_specs = [
        ("D1_5m_FullCovered", None, fcols, "monthly"),
        ("D2_5m_ExclRetailTrap", ~((feat_df["m5_retail_impulse_pct"] >= 2.0) & (feat_df["m5_smart_close_pct"] <= -0.8)), fcols, "monthly"),
        ("D3_5m_PosSmartDiv", feat_df["m5_smart_div_pct"] >= 0.5, fcols, "monthly"),
        ("D4_5m_PureMicroOnly", None, m5_extra + ["open_pct", "ret_1d", "clv", "amount_yi_t1"], "daily"),
    ]

    results = []
    for pname, mask_s, fc, rfreq in pool_specs:
        pdf = feat_df if mask_s is None else feat_df.loc[mask_s].copy().reset_index(drop=True)
        if pname == "D4_5m_PureMicroOnly":
            del feat_df
            gc.collect()
        print(f"[ModD] Pool {pname}: {len(pdf)} rows across {pdf['buy_date'].nunique()} days ({rfreq})")
        for h in horizons:
            base_cols = ["buy_date", "code", "can_buy", "is_yizi", "buy_hhmm", "exit_hhmm"]
            sub = pdf[list(dict.fromkeys(base_cols + fc))].copy()
            sub["exit_date"] = pdf[f"exit_date_h{h}"].to_numpy()
            sub["gross_ret"] = pdf[f"gross_ret_h{h}"].to_numpy()
            sub = sub[(sub["exit_date"] > sub["buy_date"]) & sub["gross_ret"].notna()].reset_index(drop=True)
            tid = f"ModD_{pname}_H{h}"
            # Note: for D4 (17 features across 1359 days), run daily on H5 (winner) and monthly on H1/H3 for speed
            eff_rfreq = "daily" if (pname == "D4_5m_PureMicroOnly" and h == 5) else ("monthly" if len(sub) > 5000 else rfreq)
            res = cm.evaluate_and_audit_track(
                track_id=tid,
                module_name="ModuleD_5mDivergence",
                desc=f"{pname} hold {h}d (15:00 close, {eff_rfreq})",
                cand_df=sub,
                feature_cols=fc,
                px_idx=px_idx,
                v20_ctx=v20_ctx,
                buy_at="close",
                thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80),
                recalc_freq=eff_rfreq,
                min_warmup_trades=80,
                min_warmup_trades_rare=40,
                perm_n=1000,
                run_trunc_check=(h == 1 or (pname == "D4_5m_PureMicroOnly" and h == 5)),
                trunc_threshold="top20",
            )
            br = res["best_row"]
            t_pass = res["truncation_20241231"]["zero_leakage_pass"] if res["truncation_20241231"] else "NA"
            print(f"  -> {tid:30s} [{eff_rfreq:7s}] best={br['threshold']:8s} n={br['n_trades_wf']:3d} WR={br['wr_wf_pct']:5.1f}% mean={br['mean_wf_pct']:5.2f}% NAV={br['nav_wf']:6.3f} ex5={br['ex5_wf']:6.3f} Sh={br['sharpe_wf']:5.2f} MDD={br['mdd_wf_pct']:5.1f}% dNAV_V20={br['patch_delta_nav_ratio']:6.4f} p={br['perm_sd_p']} trunc={t_pass}")
            results.append(res)
            del sub
            gc.collect()
        if mask_s is not None:
            del pdf
            gc.collect()

    out_pkl = f"{cm.OUT_DIR}/_modD_results.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump({"results": results, "bucket_audit": bucket_audit}, f)
    print(f"[ModD] Completed in {time.time()-t0:.1f}s | Peak RSS={cm.peak_rss_mb()} MB -> {out_pkl}")


if __name__ == "__main__":
    main()

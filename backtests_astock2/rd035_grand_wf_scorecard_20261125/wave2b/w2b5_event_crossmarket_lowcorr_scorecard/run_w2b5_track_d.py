#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2B-5 Track D: Extreme Commodity Futures Reversal + Stock-Futures Lead-Lag WF Scorecard.
Combines Research Brainwave #1 (Fut 20d hit 120d high + Stock 60d < 15% + Ring 1/2) & Extreme Low Reversal
across 3~10 day empty-slot holdings (0.30% RT fee, exclude yizi, defer limit-down exits, exact MTM).
Zero yfinance (D12). Zero cap10m. Single-thread, RAM < 2 GB.
"""
import gc
import json
import os
import resource
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _w2b5_common as wc

COMM_DIR = f"{wc.SIM}/output/extreme_commodities_3ring_backtest_20261125"
STOCK_CORE_PQ = f"{wc.WAVE1_DIR}/stock_day_core_features_pit.parquet"
MKT_PIT_PQ = f"{wc.WAVE1_DIR}/market_daily_all_new_factors_pit.parquet"


def main():
    t0 = time.time()
    print("\n=== [Track D] Commodity Futures Breakout/Reversal + Stock-Futures Lead-Lag WF Scorecard ===")
    v20_ctx = wc.wfp.load_v20_reference_context(wc.WAVE1_DIR)
    mkt_df = pd.read_parquet(MKT_PIT_PQ)

    with open(f"{COMM_DIR}/three_ring_mapping.json", encoding="utf-8") as f:
        trm = json.load(f)

    # Map each unique A-share ticker -> best (tier, sym, driver, group) priority tier 1 < 2 < 3
    stock_map = {}
    for sym, info in trm["commodities"].items():
        drv = info.get("driver", sym)
        grp = info.get("group", "HIGH")
        for tier, key in ((1, "ring1"), (2, "ring2"), (3, "ring3")):
            for tk in info.get(key, []):
                c6 = str(tk)[:6].zfill(6)
                if c6 not in stock_map or tier < stock_map[c6][0]:
                    stock_map[c6] = (tier, sym, drv, grp)

    mapped_codes = sorted(stock_map.keys())
    print(f"  Mapped commodity stocks: {len(mapped_codes)} across {len(trm['commodities'])} commodities")

    # 1. Build strictly causal futures signal panel (all dates strictly < trade_date)
    cf = pd.read_parquet(f"{COMM_DIR}/data_cache/cn_futures_close.parquet")
    gf = pd.read_parquet(f"{COMM_DIR}/data_cache/global_futures_close.parquet")
    all_fut = pd.concat([cf, gf], axis=1).sort_index()
    all_fut.index = pd.to_datetime(all_fut.index).strftime("%Y-%m-%d")
    all_fut = all_fut[all_fut.index >= "2015-01-01"].copy()

    used_drivers = sorted(set(v[2] for v in stock_map.values() if v[2] in all_fut.columns))
    fut_sub = all_fut[used_drivers].copy()

    # Compute per-driver causal metrics on futures dates (before alignment to A-share t)
    cal_dates = sorted(mkt_df["trade_date"].astype(str).unique().tolist())
    cal_ts = pd.DataFrame({"dt": cal_dates, "dt_ts": pd.to_datetime(cal_dates)}).sort_values("dt_ts")

    drv_panels = {}
    for drv in used_drivers:
        s = fut_sub[drv].dropna().copy()
        if len(s) < 150:
            continue
        r5 = s.pct_change(5) * 100.0
        r20 = s.pct_change(20) * 100.0
        r60 = s.pct_change(60) * 100.0
        hi120_prev = s.rolling(120, min_periods=60).max().shift(1)
        brk_120 = (s / hi120_prev - 1.0) * 100.0
        hit_120_20d = (brk_120 >= 0.0).rolling(20, min_periods=1).max()
        # Causal 5Y (1260d) percentile
        vals = s.to_numpy(float)
        pct5y = np.full(len(vals), np.nan)
        for i in range(180, len(vals)):
            w = vals[max(0, i - 1259) : i + 1]
            pct5y[i] = float(np.mean(w <= vals[i]))
        df_d = pd.DataFrame({
            "fut_ts": pd.to_datetime(s.index),
            "fut_ret5": r5.values,
            "fut_ret20": r20.values,
            "fut_ret60": r60.values,
            "fut_brk120": brk_120.values,
            "fut_hit120_20d": hit_120_20d.values,
            "fut_pct5y": pct5y,
        }).sort_values("fut_ts")
        # Strictly allow_exact_matches=False -> fut_ts < dt_ts (zero lookahead!)
        al = pd.merge_asof(cal_ts, df_d, left_on="dt_ts", right_on="fut_ts", direction="backward", allow_exact_matches=False)
        drv_panels[drv] = al.set_index("dt")[["fut_ret5", "fut_ret20", "fut_ret60", "fut_brk120", "fut_hit120_20d", "fut_pct5y"]]

    # 2. Load stock_day_core_features_pit ONLY for mapped_codes (~476k rows)
    cols = [
        "dt", "c6", "open", "close", "adj_factor", "ret_1d", "open_pct", "is_st_pit", "is_20cm",
        "is_yizi_zt", "is_yizi_dt", "is_dt",
        "mcap_yi_t1", "amount_yi_t1", "ret_1d_t1", "ret_5d_t1", "ret_20d_t1",
        "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1",
        "vol_ratio5_t1", "turn_5_20_t1", "real_turn_pct_t1", "down_streak_t1",
        "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "ir_cnt_30d_pre", "abn_notice_30d_pre",
    ]
    ds_core = ds.dataset(STOCK_CORE_PQ, format="parquet")
    st_df = ds_core.scanner(
        columns=cols,
        filter=ds.field("c6").isin(mapped_codes) & (ds.field("dt") <= "2026-11-25"),
    ).to_table().to_pandas()
    st_df["dt"] = st_df["dt"].astype(str)
    st_df["c6"] = st_df["c6"].astype(str).str.zfill(6)
    st_df = st_df.sort_values(["c6", "dt"]).reset_index(drop=True)
    st_df["ao"] = st_df["open"].astype(float) * st_df["adj_factor"].astype(float)
    st_df["ac"] = st_df["close"].astype(float) * st_df["adj_factor"].astype(float)

    # Strictly T-1 60d stock return (shift(1) vs shift(61))
    g = st_df.groupby("c6", sort=False)
    st_df["stk_ret60_t1"] = ((g["ac"].shift(1) / g["ac"].shift(61) - 1.0) * 100.0).astype(np.float32)

    # Attach commodity metadata & causal driver signals
    tiers, drvs = [], []
    for c6 in st_df["c6"]:
        tr, _, dr, _ = stock_map[c6]
        tiers.append(tr)
        drvs.append(dr)
    st_df["comm_ring_tier"] = np.array(tiers, dtype=np.int8)
    st_df["driver"] = drvs

    # Vectorized map of driver features onto (driver, dt)
    fut_rows = []
    for drv, fdf in drv_panels.items():
        tmp = fdf.reset_index()
        tmp["driver"] = drv
        fut_rows.append(tmp)
    fut_all = pd.concat(fut_rows, ignore_index=True)
    st_df = st_df.merge(fut_all, on=["driver", "dt"], how="left")

    st_df["lag_spread_20d"] = st_df["fut_ret20"] - st_df["ret_20d_t1"]
    st_df["lag_spread_60d"] = st_df["fut_ret60"] - st_df["stk_ret60_t1"]

    # Join T-1 market features
    mkt_keep = [
        "trade_date", "L1_sent_phase_t1", "L1_zt_cnt_t1", "L1_ew_bias20_t1",
        "mkt_pct_above_ma20_t1", "comm_cu_au_ratio_ret20_t1", "us_dxy_ret5d_on", "comm_bdi_ret20_t1",
    ]
    st_df = st_df.merge(mkt_df[mkt_keep], left_on="dt", right_on="trade_date", how="left")

    # Build fast lookup ONLY for candidate stocks actually in pools later -> build px_lookup AFTER filtering st_df!
    stk_arrays = {}
    for c6, grp in st_df.groupby("c6", sort=False):
        dts_s = grp["dt"].to_numpy()
        ao_s = grp["ao"].to_numpy(float)
        ac_s = grp["ac"].to_numpy(float)
        stk_arrays[c6] = (dts_s, {d: i for i, d in enumerate(dts_s)}, ao_s, ac_s, grp["is_yizi_dt"].to_numpy(bool), grp["is_dt"].to_numpy(bool))
    px_lookup = {}  # Populate minimally per selected trades or directly from stk_arrays when needed!
    for c6, (dts_s, _, ao_s, ac_s, _, _) in stk_arrays.items():
        for d_v, o_v, c_v in zip(dts_s, ao_s, ac_s):
            if str(d_v) >= "2023-01-01":
                px_lookup[(c6, str(d_v))] = (float(o_v), float(c_v))

    def _build_pool_with_horizon(cand_sub: pd.DataFrame, hold_td: int) -> pd.DataFrame:
        # Filter buyable at T open
        m_buy = (
            (cand_sub["is_st_pit"] == 0)
            & (cand_sub["is_yizi_zt"] == 0)
            & (cand_sub["is_yizi_dt"] == 0)
            & cand_sub["open_pct"].notna()
        )
        lim = np.where(cand_sub["is_20cm"] == 1, 0.194, 0.094)
        m_buy &= (cand_sub["open_pct"] < lim) & (cand_sub["open_pct"] > -lim)
        sub = cand_sub[m_buy].copy().reset_index(drop=True)

        ex_dts, bpxs, epxs, grets, valids = [], [], [], [], []
        step = hold_td - 1  # H=5 -> buy day pos open, exit day pos+4 close
        for c6, dt_v in zip(sub["c6"], sub["dt"]):
            tup = stk_arrays.get(c6)
            if tup is None:
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); valids.append(False)
                continue
            dts_s, d_map, ao_s, ac_s, yz_dt_s, dt_s = tup
            pos = d_map.get(dt_v)
            if pos is None or pos + step >= len(dts_s):
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); valids.append(False)
                continue
            b_px = ao_s[pos]
            if not (np.isfinite(b_px) and b_px > 0):
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); valids.append(False)
                continue
            ex_pos = pos + step
            while ex_pos < len(dts_s) - 1 and ex_pos < pos + step + 6 and (yz_dt_s[ex_pos] or dt_s[ex_pos]):
                ex_pos += 1
            e_px = ac_s[ex_pos]
            if not (np.isfinite(e_px) and e_px > 0):
                ex_dts.append(""); bpxs.append(np.nan); epxs.append(np.nan); grets.append(np.nan); valids.append(False)
                continue
            ex_dts.append(str(dts_s[ex_pos]))
            bpxs.append(float(b_px))
            epxs.append(float(e_px))
            grets.append(float(e_px / b_px - 1.0))
            valids.append(True)

        sub["buy_date"] = sub["dt"]
        sub["code"] = sub["c6"]
        sub["exit_date"] = ex_dts
        sub["buy_px"] = bpxs
        sub["exit_px"] = epxs
        sub["gross_ret"] = grets
        sub["buy_hhmm"] = 925
        sub["exit_hhmm"] = 1500
        sub["is_yizi"] = False
        sub["can_buy"] = valids
        return sub[sub["can_buy"] & (sub["exit_date"] > sub["buy_date"])].copy().reset_index(drop=True)

    # Candidate definitions (all strictly PIT < dt)
    m_bw1 = (st_df["fut_hit120_20d"] >= 1.0) & (st_df["stk_ret60_t1"] < 15.0) & (st_df["comm_ring_tier"].isin([1, 2]))
    m_low_rev = (st_df["fut_pct5y"] <= 0.25) & (st_df["fut_ret5"] > 0.0) & (st_df["stk_ret60_t1"] < 15.0) & (st_df["comm_ring_tier"].isin([1, 2]))
    m_unified = (
        ((st_df["fut_hit120_20d"] >= 1.0) | ((st_df["fut_pct5y"] <= 0.25) & (st_df["fut_ret5"] > 0.0)) | (st_df["fut_ret20"] >= 8.0))
        & (st_df["stk_ret60_t1"] < 20.0)
        & (st_df["comm_ring_tier"].isin([1, 2]))
    )

    pool_bw1_h5 = _build_pool_with_horizon(st_df[m_bw1], hold_td=5)
    pool_bw1_h10 = _build_pool_with_horizon(st_df[m_bw1], hold_td=10)
    pool_low_h5 = _build_pool_with_horizon(st_df[m_low_rev], hold_td=5)
    pool_low_h10 = _build_pool_with_horizon(st_df[m_low_rev], hold_td=10)
    pool_uni_h3 = _build_pool_with_horizon(st_df[m_unified], hold_td=3)
    pool_uni_h5 = _build_pool_with_horizon(st_df[m_unified], hold_td=5)
    pool_uni_h10 = _build_pool_with_horizon(st_df[m_unified], hold_td=10)

    print(f"  Pool sizes: BW1_H5={len(pool_bw1_h5)}, LowRev_H5={len(pool_low_h5)}, Uni_H3={len(pool_uni_h3)}, Uni_H5={len(pool_uni_h5)}, Uni_H10={len(pool_uni_h10)}")

    fcols = [
        "comm_ring_tier", "fut_ret5", "fut_ret20", "fut_ret60", "fut_brk120", "fut_hit120_20d", "fut_pct5y",
        "stk_ret60_t1", "ret_20d_t1", "ret_5d_t1", "ret_1d_t1", "lag_spread_20d", "lag_spread_60d",
        "open_pct", "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1",
        "vol_ratio5_t1", "turn_5_20_t1", "real_turn_pct_t1", "down_streak_t1", "mcap_yi_t1",
        "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "ir_cnt_30d_pre", "abn_notice_30d_pre",
        "L1_sent_phase_t1", "L1_zt_cnt_t1", "mkt_pct_above_ma20_t1", "comm_cu_au_ratio_ret20_t1", "us_dxy_ret5d_on",
    ]

    trunc_d = wc.wfe.verify_truncation_zero_leakage(
        pool_uni_h5, fcols, mode="A", cutoff="2024-12-31", score_threshold="top10",
        v20_ctx=v20_ctx, wf_start_date="2023-01-03", min_warmup_trades=100, min_warmup_trades_rare=60,
        min_warmup_months=18, recalc_freq="daily", top_k=10, min_k=4, fee_rt=0.0030, gross_ret_col="gross_ret",
    )
    print(f"  [Track D] Truncation 2024-12-31 proof: {trunc_d}")

    variants = [
        ("D1_BW1_Fut120Brk_H5", "Research脑洞#1(期货20日创半年新高+个股60日<15%) 5天持仓", pool_bw1_h5, "daily"),
        ("D2_BW1_Fut120Brk_H10", "Research脑洞#1(期货20日创半年新高+个股60日<15%) 10天持仓", pool_bw1_h10, "daily"),
        ("D3_LowExtremeRev_H5", "极端低位期货反转(5Y<=25%且5d转正+个股<15%) 5天持仓", pool_low_h5, "daily"),
        ("D4_LowExtremeRev_H10", "极端低位期货反转(5Y<=25%且5d转正+个股<15%) 10天持仓", pool_low_h10, "daily"),
        ("D5_Unified_LeadLag_H3", "大宗突破+低位反转统一打分池 3天持仓", pool_uni_h3, "monthly"),
        ("D6_Unified_LeadLag_H5", "大宗突破+低位反转统一打分池 5天持仓", pool_uni_h5, "daily"),
        ("D7_Unified_LeadLag_H10", "大宗突破+低位反转统一打分池 10天持仓", pool_uni_h10, "daily"),
    ]

    track_res = {}
    csv_rows = []
    for vid, desc, df_v, rf in variants:
        res = wc.evaluate_scorecard_with_exact_mtm(
            df_v, fcols, px_lookup, v20_ctx, fee_rt=0.0030, gross_ret_col="gross_ret",
            wf_start_date="2023-01-03", end_date="2026-11-16",
            min_warmup_trades=100, min_warmup_trades_rare=60, min_warmup_months=18,
            recalc_freq=rf, top_k=10, min_k=4, max_corr=0.65,
            thresholds=("all_cands", "top30", "top20", "top10", 70, 75),
            perm_n=1000, seed=20261125,
        )
        print(f"  [{vid}] ({rf}) start={res['meta']['wf_actual_start']}, cands={len(df_v)}")
        print(res["summary_table"][["threshold", "n_trades", "wr_pct", "plr", "nav_wf", "ex5_wf", "mdd_pct", "sharpe", "nav_2526", "nav_y26", "perm_sd_p", "corr_v20"]].to_string(index=False))

        wf_start = res["meta"]["wf_actual_start"] or "2023-01-03"
        th_out = {}
        for tname, td in res["threshold_results"].items():
            vp = td["v20_empty_patch"]
            th_out[tname] = {
                "metrics": td["metrics"],
                "corr_diag": td["corr_diag"],
                "v20_empty_patch": {
                    "mode1_strict_combined_no_peek": {k: v for k, v in vp["mode1_strict_combined_no_peek"].items() if k != "skipped_v20_trades"},
                    "mode2_empty_slot_standalone": vp["mode2_empty_slot_standalone"],
                } if vp else None,
            }
            if tname in ("all_cands", "top20", "top10", "abs_70"):
                csv_rows.append(wc.extract_track_row(
                    "TrackD_Commodity_LeadLag", vid, desc, tname, 0.0030, wf_start,
                    td["metrics"], vp, td["corr_diag"], trunc_d["zero_leakage_pass"],
                ))

        track_res[vid] = {
            "desc": desc,
            "recalc_freq": rf,
            "n_total_cands": int(len(df_v)),
            "wf_actual_start": wf_start,
            "n_daily_rebuilds": res["meta"]["n_rebuilds"],
            "summary_table": res["summary_table"].to_dict("records"),
            "thresholds": th_out,
            "latest_scorecard_factors": [
                {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "budget_pts": f["budget_pts"], "bin_pts": f["bin_pts"], "bin_wr_pct": f["bin_wr_pct"], "bin_mean_pct": f["bin_mean_pct"]}
                for f in (res["meta"]["latest_scorecard"]["factors"] if res["meta"]["latest_scorecard"] else [])
            ],
            "best_slot_df": res["threshold_results"]["top10"]["slot_df"],
        }

    # Save best candidate slot trades
    track_res["D6_Unified_LeadLag_H5"]["best_slot_df"].drop(columns=["mtm_segs"], errors="ignore").to_parquet(
        f"{wc.CACHE_DIR}/track_d_best_slot.parquet", index=False
    )
    for v in track_res.values():
        v.pop("best_slot_df", None)

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    out = wc.sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "truncation_20241231_proof": trunc_d,
        "variants": track_res,
        "csv_rows": csv_rows,
    })
    with open(f"{wc.CACHE_DIR}/w2b5_track_d.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[Track D DONE in {time.time()-t0:.1f}s | RSS={rss_mb} MB]")


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD042 Step 2: Track B — 北交所 30cm 情绪套利
  - B1: 北交所 30cm 首板/涨停 (>=29.5%) 次日深水低开 / 分歧承接
  - B2: 主板情绪退潮或一字堵死买不到时，北交所大阳 (15%..29.5%) 或 30cm 涨停次日接力
  - B3: 北交所多因子打分制 × 逐日前视镜 (exit_date < t) + 严格 09:25 补 V20 空仓日
Mandatory Pre-924 (2021.11.15-2024.09.23) vs Post-924 (2024.09.24-2026.11.25) liquidity regime split,
>=5000万 & >=1亿 capacity filters, 30/50/80bps friction, 1000x perm, 2024-12-31 physical truncation check.

Zero yfinance (D12). Zero cap10m. Threads <= 1. Peak RSS < 2.0 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd042_bse30cm_subnew_20261126"
for p in (BASE_DIR, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf  # noqa: E402
import _wf_sim_and_metrics as wfm  # noqa: E402
import _rd042_eval as rd_ev  # noqa: E402

BSE_PQ = f"{OUT_DIR}/bse_30cm_daily_cache.parquet"
MKT_DAY_PQ = f"{BASE_DIR}/market_daily_all_new_factors_pit.parquet"
EXITS = ["S1_hold1c", "S2_hold2c", "S3_hold3c", "S4_hold5c", "S5_zt_ride", "S6_ma5_stop"]
END_BAR_DATE = "2026-11-25"

MKT_PIT_COLS = [
    "L1_zt_cnt_t1", "L1_nat_zt_cnt_t1", "L1_dt_cnt_t1", "L1_zt_dt_logratio_t1",
    "L1_zb_rate_t1", "L1_max_board_t1", "L1_lianban_cnt_t1", "L1_zt_prem_t1",
    "L1_lb_promo_t1", "L1_duanban_damian_t1", "L1_zt_mom3v20_t1", "L1_zt_pct60_t1",
    "L1_sent_phase_t1", "L1_smb_5d_t1", "L1_smb_20d_t1", "L1_amt_ratio20_t1",
    "L1_ew_bias20_t1", "L1_ew_pos60_t1", "L1_is_earn_win", "L1_is_month_end3", "L1_weekday",
    "mkt20_zt_cnt_t1", "mkt_yizi_zt_cnt_t1", "mkt_amt_tril_t1", "mkt_broken_avg_ret_t1",
    "mkt_zt_next_oc_t1", "mkt_0925_zt_cnt", "mkt_0925_dt_cnt", "mkt_0925_avg_gap_pct",
    "th_style_ice_point_sig_t1", "us_ixic_ret1d_on", "us_vix_level_on",
    "pol_rescue_signal_10d", "pol_crackdown_signal_10d",
]


def peak_rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)


def build_bse_features_and_events() -> pd.DataFrame:
    """Build causal stock + BSE market + Mainboard features & extract B1/B2 events."""
    t0 = time.time()
    df = pd.read_parquet(BSE_PQ)
    df["c6"] = df["c6"].astype(str).str.zfill(6)
    df["dt"] = df["dt"].astype(str).str[:10]
    df = df.sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"]).reset_index(drop=True)

    g = df.groupby("c6", sort=False)
    df["bar_idx"] = g.cumcount() + 1
    df["prev_adj_close"] = g["adj_close"].shift(1)
    df["prev_close_raw"] = df["prev_adj_close"] * (df["close"] / df["adj_close"])
    df["ret_1d"] = ((df["adj_close"] / df["prev_adj_close"] - 1.0) * 100.0).astype(np.float64)
    df["open_pct"] = ((df["open"] / df["prev_close_raw"] - 1.0) * 100.0).astype(np.float64)
    hl = (df["high"] - df["low"]).to_numpy(np.float64)
    df["clv"] = np.where(hl > 1e-6, (df["close"] - df["low"]) / hl, 0.5).astype(np.float64)

    # BSE day-1 IPO has NO 30% limit; NEEQ shifts on 2021-11-15 had 30% limit but bar_idx==1 has no prev_close
    df["is_ipo_day1"] = ((df["dt"] == df["list_date"]) & (df["list_date"] > "2021-11-15")).astype(np.int8)
    has_limit = (df["bar_idx"] >= 2) & (df["is_ipo_day1"] == 0) & df["prev_close_raw"].notna() & (df["prev_close_raw"] > 0)

    zt_px = np.round(df["prev_close_raw"].to_numpy(np.float64) * 1.30 + 1e-9, 2)
    dt_px = np.round(df["prev_close_raw"].to_numpy(np.float64) * 0.70 + 1e-9, 2)
    cl_v = df["close"].to_numpy(np.float64)
    hi_v = df["high"].to_numpy(np.float64)
    lo_v = df["low"].to_numpy(np.float64)
    op_v = df["open"].to_numpy(np.float64)
    r1_v = df["ret_1d"].to_numpy(np.float64)

    df["zt_px"] = zt_px
    df["dt_px"] = dt_px
    df["is_zt30"] = (has_limit.to_numpy() & (r1_v >= 29.5) & (cl_v >= hi_v - 0.015)).astype(np.int8)
    df["hit_zt30"] = (has_limit.to_numpy() & ((hi_v >= zt_px - 0.015) | (r1_v >= 29.5))).astype(np.int8)
    df["is_broken_zt30"] = ((df["hit_zt30"] == 1) & (df["is_zt30"] == 0)).astype(np.int8)
    df["is_yizi_zt30"] = ((df["is_zt30"] == 1) & (op_v >= hi_v - 0.015) & (lo_v >= hi_v - 0.015)).astype(np.int8)
    df["is_dt30"] = (has_limit.to_numpy() & (r1_v <= -29.5) & (cl_v <= lo_v + 0.015)).astype(np.int8)
    df["is_yizi_dt30"] = ((df["is_dt30"] == 1) & (op_v <= lo_v + 0.015) & (hi_v <= lo_v + 0.015)).astype(np.int8)

    # Streak & rolling per-stock causal features
    c6_vals = df["c6"].to_numpy()
    zt_arr = df["is_zt30"].to_numpy()
    streak = np.zeros(len(df), dtype=np.int16)
    down_stk = np.zeros(len(df), dtype=np.int16)
    cur_s = cur_d = 0
    prev_c = ""
    for i in range(len(df)):
        ck = c6_vals[i]
        if ck != prev_c:
            cur_s = cur_d = 0
            prev_c = ck
        cur_s = cur_s + 1 if zt_arr[i] == 1 else 0
        cur_d = cur_d + 1 if (np.isfinite(r1_v[i]) and r1_v[i] < 0.0) else 0
        streak[i] = cur_s
        down_stk[i] = cur_d
    df["streak"] = streak
    df["down_stk"] = down_stk

    # Aggregate BSE market daily stats strictly causal (shifted by 1 day on BSE calendar!)
    bse_cal = sorted(df["dt"].unique())
    prev_dt_map = {bse_cal[i]: bse_cal[i - 1] for i in range(1, len(bse_cal))}
    df["prev_dt"] = df["dt"].map(prev_dt_map)

    mkt_bj = df.groupby("dt", as_index=False).agg(
        bj_mkt_zt30_cnt=("is_zt30", "sum"),
        bj_mkt_surge15_cnt=("ret_1d", lambda s: int((s >= 15.0).sum())),
        bj_mkt_dt30_cnt=("is_dt30", "sum"),
        bj_mkt_amt_yi=("amount_yi", "sum"),
        bj_mkt_med_ret=("ret_1d", "median"),
        bj_mkt_0925_avg_gap=("open_pct", "mean"),
        bj_mkt_0925_hi3_cnt=("open_pct", lambda s: int((s >= 3.0).sum())),
        bj_mkt_0925_zt_cnt=("is_yizi_zt30", "sum"),
    ).sort_values("dt").reset_index(drop=True)
    mkt_bj["bj_mkt_amt_ma20"] = mkt_bj["bj_mkt_amt_yi"].rolling(20, min_periods=5).mean()
    mkt_bj["bj_mkt_amt_ratio20"] = mkt_bj["bj_mkt_amt_yi"] / mkt_bj["bj_mkt_amt_ma20"].replace(0, np.nan)

    # Shift end-of-day BSE market stats to T-1 (`t1` join on prev_dt == dt), keep 09:25 stats on dt!
    t1_cols = ["bj_mkt_zt30_cnt", "bj_mkt_surge15_cnt", "bj_mkt_dt30_cnt", "bj_mkt_amt_yi", "bj_mkt_amt_ratio20", "bj_mkt_med_ret"]
    mkt_bj_t1 = mkt_bj[["dt"] + t1_cols].rename(columns={c: f"{c}_t1" for c in t1_cols}).rename(columns={"dt": "prev_dt"})
    df = df.merge(mkt_bj_t1, on="prev_dt", how="left")
    df = df.merge(mkt_bj[["dt", "bj_mkt_0925_avg_gap", "bj_mkt_0925_hi3_cnt", "bj_mkt_0925_zt_cnt"]], on="dt", how="left")

    # Merge mainboard PIT market factors on dt
    mkt_a = pd.read_parquet(MKT_DAY_PQ, columns=["trade_date"] + MKT_PIT_COLS)
    mkt_a["dt"] = mkt_a["trade_date"].astype(str).str[:10]
    mkt_a = mkt_a.drop(columns=["trade_date"]).drop_duplicates("dt")
    df = df.merge(mkt_a, on="dt", how="left").sort_values(["c6", "dt"]).reset_index(drop=True)

    events = []
    for c6, grp in df.groupby("c6", sort=False):
        n = len(grp)
        if n < 5:
            continue
        dts = grp["dt"].to_numpy()
        op = grp["open"].to_numpy(np.float64)
        hi = grp["high"].to_numpy(np.float64)
        lo = grp["low"].to_numpy(np.float64)
        cl = grp["close"].to_numpy(np.float64)
        af = grp["adj_factor"].to_numpy(np.float64)
        ac = grp["adj_close"].to_numpy(np.float64)
        r1 = grp["ret_1d"].to_numpy(np.float64)
        opct = grp["open_pct"].to_numpy(np.float64)
        clv = grp["clv"].to_numpy(np.float64)
        amt_yi = grp["amount_yi"].to_numpy(np.float64)
        trn_pct = grp["turn_pct"].to_numpy(np.float64)
        osh = grp["oshare"].to_numpy(np.float64)
        pc_raw = grp["prev_close_raw"].to_numpy(np.float64)
        zt_px_arr = grp["zt_px"].to_numpy(np.float64)
        zt = grp["is_zt30"].to_numpy(np.int8)
        hit_zt = grp["hit_zt30"].to_numpy(np.int8)
        brk_zt = grp["is_broken_zt30"].to_numpy(np.int8)
        yzz = grp["is_yizi_zt30"].to_numpy(np.int8)
        dt_f = grp["is_dt30"].to_numpy(np.int8)
        yzd = grp["is_yizi_dt30"].to_numpy(np.int8)
        stk = grp["streak"].to_numpy(np.int16)
        dstk = grp["down_stk"].to_numpy(np.int16)
        bidx = grp["bar_idx"].to_numpy(np.int32)
        ipo1 = grp["is_ipo_day1"].to_numpy(np.int8)
        nm_str = str(grp["name"].iloc[0])

        ma5 = np.full(n, np.nan)
        for idx in range(4, n):
            ma5[idx] = np.mean(ac[idx - 4 : idx + 1]) / af[idx]

        mkt_dicts = grp[
            ["bj_mkt_zt30_cnt_t1", "bj_mkt_surge15_cnt_t1", "bj_mkt_dt30_cnt_t1", "bj_mkt_amt_yi_t1",
             "bj_mkt_amt_ratio20_t1", "bj_mkt_med_ret_t1", "bj_mkt_0925_avg_gap", "bj_mkt_0925_hi3_cnt",
             "bj_mkt_0925_zt_cnt"] + MKT_PIT_COLS
        ].to_dict("records")

        for b in range(2, n - 1):
            sig = b - 1
            if ipo1[sig] == 1 or ipo1[b] == 1 or bidx[sig] < 2:
                continue
            if op[b] <= 0 or af[b] <= 0 or yzz[b] == 1 or yzd[b] == 1:
                continue
            if not np.isfinite(pc_raw[b]) or pc_raw[b] <= 0:
                continue
            # Exclude 09:25 limit-up auction open (unbuyable 30cm queue)
            if op[b] >= zt_px_arr[b] - 0.015 or opct[b] >= 29.0:
                continue
            # Require real trading on signal day
            if amt_yi[sig] <= 0:
                continue

            is_b1 = (zt[sig] == 1)
            is_b2 = (not is_b1) and np.isfinite(r1[sig]) and (15.0 <= r1[sig] < 29.5)
            if not (is_b1 or is_b2):
                continue

            ex_res = rd_ev.simulate_exits_generic(b, n, op, hi, lo, cl, af, ac, dts, zt, dt_f, yzd, ma5)
            if not ex_res:
                continue

            # Causal per-stock features strictly <= sig (T-1) or 09:25 at b
            vr3_t1 = float(amt_yi[sig] / max(1e-6, np.mean(amt_yi[max(0, sig - 3) : sig]))) if sig > 0 else 1.0
            vr5_t1 = float(amt_yi[sig] / max(1e-6, np.mean(amt_yi[max(0, sig - 5) : sig]))) if sig > 0 else 1.0
            r5_t1 = float((ac[sig] / ac[sig - 5] - 1.0) * 100.0) if sig >= 5 else np.nan
            r20_t1 = float((ac[sig] / ac[sig - 20] - 1.0) * 100.0) if sig >= 20 else np.nan
            bias10_t1 = float((ac[sig] / np.mean(ac[sig - 9 : sig + 1]) - 1.0) * 100.0) if sig >= 9 else np.nan
            bias20_t1 = float((ac[sig] / np.mean(ac[sig - 19 : sig + 1]) - 1.0) * 100.0) if sig >= 19 else np.nan
            w20 = ac[max(0, sig - 19) : sig + 1]
            pos20_t1 = float((ac[sig] - np.min(w20)) / (np.max(w20) - np.min(w20))) if (len(w20) >= 5 and np.max(w20) > np.min(w20)) else 0.5
            dd20_t1 = float((ac[sig] / np.max(w20) - 1.0) * 100.0) if len(w20) >= 5 else np.nan
            amp20_t1 = float((np.max(w20) / np.min(w20) - 1.0) * 100.0) if (len(w20) >= 5 and np.min(w20) > 0) else np.nan
            w60 = ac[max(0, sig - 59) : sig + 1]
            pos60_t1 = float((ac[sig] - np.min(w60)) / (np.max(w60) - np.min(w60))) if (len(w60) >= 15 and np.max(w60) > np.min(w60)) else np.nan
            hit20_t1 = int(np.sum(hit_zt[max(0, sig - 19) : sig + 1]))
            float_mcap_yi_t1 = float(cl[sig] * osh[sig] / 1e8) if (osh[sig] > 0) else np.nan

            md = mkt_dicts[b]
            sp_val = md.get("L1_sent_phase_t1")
            db_val = md.get("L1_duanban_damian_t1")
            zb_val = md.get("L1_zb_rate_t1")
            yz_t1 = md.get("mkt_yizi_zt_cnt_t1")
            yz_0925 = md.get("mkt_0925_zt_cnt")
            is_retreat = int(
                (np.isfinite(sp_val) and int(sp_val) in (1, 5))
                or (np.isfinite(db_val) and float(db_val) >= 25.0)
                or (np.isfinite(zb_val) and float(zb_val) >= 38.0)
            )
            is_yizi_jam = int(
                (np.isfinite(yz_t1) and float(yz_t1) >= 7.0)
                or (np.isfinite(yz_0925) and float(yz_0925) >= 10.0)
            )
            is_spillover = int(is_retreat == 1 or is_yizi_jam == 1)

            base_rec = {
                "code": c6,
                "name": nm_str,
                "sig_date": str(dts[sig]),
                "buy_date": str(dts[b]),
                "buy_hhmm": 925,
                "buy_px": round(float(op[b]), 3),
                "is_yizi": False,
                "regime_924": "POST_924" if str(dts[b]) >= "2024-09-24" else "PRE_924",
                "entry_type": "B1_ZT30" if is_b1 else "B2_YANG15",
                "is_mainboard_retreat": is_retreat,
                "is_mainboard_yizi_jam": is_yizi_jam,
                "is_spillover_cond": is_spillover,
                "open_pct": round(float(opct[b]), 4),
                "bj_open_pct": round(float(opct[b]), 4),
                "bj_ret_1d_t1": round(float(r1[sig]), 4),
                "bj_clv_t1": round(float(clv[sig]), 4),
                "bj_amt_yi_t1": round(float(amt_yi[sig]), 4),
                "bj_turn_pct_t1": round(float(trn_pct[sig]), 4),
                "bj_mcap_float_yi_t1": round(float_mcap_yi_t1, 3) if np.isfinite(float_mcap_yi_t1) else np.nan,
                "bj_vr3_t1": round(vr3_t1, 4),
                "bj_vr5_t1": round(vr5_t1, 4),
                "bj_is_zt30_t1": int(zt[sig]),
                "bj_is_yizi_t1": int(yzz[sig]),
                "bj_streak_t1": int(stk[sig]),
                "bj_down_streak_pre": int(dstk[sig - 1]) if sig >= 1 else 0,
                "bj_ret_5d_t1": round(r5_t1, 3) if np.isfinite(r5_t1) else np.nan,
                "bj_ret_20d_t1": round(r20_t1, 3) if np.isfinite(r20_t1) else np.nan,
                "bj_bias10_t1": round(bias10_t1, 3) if np.isfinite(bias10_t1) else np.nan,
                "bj_bias20_t1": round(bias20_t1, 3) if np.isfinite(bias20_t1) else np.nan,
                "bj_pos_20d_t1": round(pos20_t1, 4),
                "bj_pos_60d_t1": round(pos60_t1, 4) if np.isfinite(pos60_t1) else np.nan,
                "bj_dd_20d_t1": round(dd20_t1, 3) if np.isfinite(dd20_t1) else np.nan,
                "bj_amp_20d_t1": round(amp20_t1, 3) if np.isfinite(amp20_t1) else np.nan,
                "bj_hit_zt_cnt_20d_t1": hit20_t1,
                "bj_bar_idx_t1": int(bidx[sig]),
            }
            base_rec.update(md)
            for sname, sdict in ex_res.items():
                base_rec[f"{sname}_exit_date"] = sdict["exit_date"]
                base_rec[f"{sname}_exit_hhmm"] = sdict["exit_hhmm"]
                base_rec[f"{sname}_gross_ret"] = sdict["gross_ret"]
                base_rec[f"{sname}_reason"] = sdict["reason"]
                base_rec[f"{sname}_mtm_json"] = json.dumps(sdict["mtm_gross"])
            events.append(base_rec)

    ev_df = pd.DataFrame(events).sort_values(["buy_date", "entry_type", "code"]).reset_index(drop=True)
    ev_pq = f"{OUT_DIR}/track_b_bse_events_pit.parquet"
    ev_df.to_parquet(ev_pq, index=False, compression="snappy")
    print(f"[TrackB] Extracted {len(ev_df):,} BSE events in {time.time()-t0:.1f}s | B1_ZT30={(ev_df['entry_type']=='B1_ZT30').sum()} (post924={((ev_df['entry_type']=='B1_ZT30')&(ev_df['regime_924']=='POST_924')).sum()}), B2_YANG15={(ev_df['entry_type']=='B2_YANG15').sum()} (post924={((ev_df['entry_type']=='B2_YANG15')&(ev_df['regime_924']=='POST_924')).sum()}) | RSS={peak_rss_mb()} MB", flush=True)
    del df
    gc.collect()
    return ev_df


def get_track_b_features(df_view: pd.DataFrame) -> list[str]:
    bj_cols = [
        "bj_open_pct", "bj_ret_1d_t1", "bj_clv_t1", "bj_amt_yi_t1", "bj_turn_pct_t1",
        "bj_mcap_float_yi_t1", "bj_vr3_t1", "bj_vr5_t1", "bj_is_zt30_t1", "bj_is_yizi_t1",
        "bj_streak_t1", "bj_down_streak_pre", "bj_ret_5d_t1", "bj_ret_20d_t1",
        "bj_bias10_t1", "bj_bias20_t1", "bj_pos_20d_t1", "bj_pos_60d_t1", "bj_dd_20d_t1",
        "bj_amp_20d_t1", "bj_hit_zt_cnt_20d_t1", "bj_bar_idx_t1",
        "bj_mkt_zt30_cnt_t1", "bj_mkt_surge15_cnt_t1", "bj_mkt_dt30_cnt_t1",
        "bj_mkt_amt_yi_t1", "bj_mkt_amt_ratio20_t1", "bj_mkt_med_ret_t1",
        "bj_mkt_0925_avg_gap", "bj_mkt_0925_hi3_cnt", "bj_mkt_0925_zt_cnt",
        "is_mainboard_retreat", "is_mainboard_yizi_jam", "is_spillover_cond",
    ]
    cands = list(dict.fromkeys(bj_cols + MKT_PIT_COLS))
    w = df_view[df_view["buy_date"] <= "2023-06-30"]  # Pre-WF/early-WF non-degeneracy check
    if len(w) < 30:
        w = df_view[df_view["buy_date"] <= "2024-06-30"]
    clean = []
    for c in cands:
        if c not in df_view.columns or not pd.api.types.is_numeric_dtype(df_view[c]):
            continue
        s = w[c].dropna()
        if len(s) < 20:
            continue
        vc = s.value_counts()
        if len(vc) <= 1:
            continue
        if len(vc) <= 3 and int(vc.min()) < 5:
            continue
        clean.append(c)
    return clean


def main():
    t0 = time.time()
    ev_df = build_bse_features_and_events()
    v20_ctx = wf.load_v20_reference_context(BASE_DIR)
    bench_df = v20_ctx["bench"]

    windows_bse = [
        ("FULL_5Y", "2021-11-15", END_BAR_DATE),
        ("PRE_924", "2021-11-15", "2024-09-23"),
        ("POST_924", "2024-09-24", END_BAR_DATE),
        ("WF_2326", "2023-01-03", END_BAR_DATE),
        ("Y2025_2026", "2025-01-01", END_BAR_DATE),
        ("Y2026", "2026-01-01", END_BAR_DATE),
        ("Y2026_H2", "2026-07-01", END_BAR_DATE),
    ]

    amt5000w = (ev_df["bj_amt_yi_t1"] >= 0.50).to_numpy()
    amt1yi = (ev_df["bj_amt_yi_t1"] >= 1.00).to_numpy()
    deep_open = ev_df["bj_open_pct"].between(-15.0, -1.0).to_numpy()
    div_open = ev_df["bj_open_pct"].between(-12.0, 3.0).to_numpy()
    fb30 = (ev_df["bj_streak_t1"] == 1).to_numpy() & (ev_df["bj_is_yizi_t1"] == 0).to_numpy()
    retreat = (ev_df["is_mainboard_retreat"] == 1).to_numpy()
    yizijam = (ev_df["is_mainboard_yizi_jam"] == 1).to_numpy()
    spill = (ev_df["is_spillover_cond"] == 1).to_numpy()
    post924 = (ev_df["regime_924"] == "POST_924").to_numpy()
    pre924 = (ev_df["regime_924"] == "PRE_924").to_numpy()

    blind_slices = [
        ("B1_zt30_all", "B1_ZT30", None),
        ("B1_fb30_all", "B1_ZT30", fb30),
        ("B1_zt30_deep", "B1_ZT30", deep_open),
        ("B1_zt30_div", "B1_ZT30", div_open),
        ("B1_zt30_amt5000w", "B1_ZT30", amt5000w),
        ("B1_zt30_amt1yi", "B1_ZT30", amt1yi),
        ("B1_zt30_div_amt5000w", "B1_ZT30", div_open & amt5000w),
        ("B1_zt30_pre924", "B1_ZT30", pre924),
        ("B1_zt30_post924", "B1_ZT30", post924),
        ("B1_zt30_post924_amt1yi", "B1_ZT30", post924 & amt1yi),
        ("B2_yang15_all", "B2_YANG15", None),
        ("B2_yang15_retreat", "B2_YANG15", retreat),
        ("B2_yang15_yizijam", "B2_YANG15", yizijam),
        ("B2_yang15_spillover", "B2_YANG15", spill),
        ("B2_yang15_amt5000w", "B2_YANG15", amt5000w),
        ("B2_yang15_amt1yi", "B2_YANG15", amt1yi),
        ("B2_yang15_spill_amt5000w", "B2_YANG15", spill & amt5000w),
        ("B2_yang15_pre924", "B2_YANG15", pre924),
        ("B2_yang15_post924", "B2_YANG15", post924),
        ("B_ALL15plus_all", "ALL", None),
        ("B_ALL15plus_retreat", "ALL", retreat),
        ("B_ALL15plus_yizijam", "ALL", yizijam),
        ("B_ALL15plus_spillover", "ALL", spill),
        ("B_ALL15plus_amt5000w", "ALL", amt5000w),
        ("B_ALL15plus_amt1yi", "ALL", amt1yi),
        ("B_ALL15plus_post924_amt5000w", "ALL", post924 & amt5000w),
    ]

    blind_rows = []
    for s_name, ent, msk in blind_slices:
        for ex in EXITS:
            view = rd_ev.make_clean_view(ev_df, ent, ex, extra_mask=msk, fee_rt=0.0030)
            if len(view) < 10:
                continue
            _, slot = wfm.select_single_slot_trades(view.assign(wf_score=100.0), score_col="wf_score", threshold=None, wf_only=False)
            ev30 = rd_ev.eval_windows_exact(slot, view, view, bench_df, "mtm_json_use", 0.0030, "2021-11-15", END_BAR_DATE, windows_bse, perm_n=100)
            ev50 = rd_ev.eval_windows_exact(
                slot.assign(net_ret=(1.0 + slot["gross_ret"]) * (1.0 - 0.0050) - 1.0),
                view.assign(net_ret=(1.0 + view["gross_ret"]) * (1.0 - 0.0050) - 1.0),
                view, bench_df, "mtm_json_use", 0.0050, "2021-11-15", END_BAR_DATE, windows_bse[:3], perm_n=20,
            )
            ev80 = rd_ev.eval_windows_exact(
                slot.assign(net_ret=(1.0 + slot["gross_ret"]) * (1.0 - 0.0080) - 1.0),
                view.assign(net_ret=(1.0 + view["gross_ret"]) * (1.0 - 0.0080) - 1.0),
                view, bench_df, "mtm_json_use", 0.0080, "2021-11-15", END_BAR_DATE, windows_bse[:3], perm_n=20,
            )
            f5 = ev30["windows"].get("FULL_5Y", {})
            pre = ev30["windows"].get("PRE_924", {})
            post = ev30["windows"].get("POST_924", {})
            wf23 = ev30["windows"].get("WF_2326", {})
            y2526 = ev30["windows"].get("Y2025_2026", {})
            y26 = ev30["windows"].get("Y2026", {})
            y26h2 = ev30["windows"].get("Y2026_H2", {})
            blind_rows.append({
                "section": "BLIND_B", "track": s_name, "exit_rule": ex,
                "n_cands": int(len(view)), "raw_wr_pct": round(float((view["net_ret"] > 0).mean() * 100), 2),
                "raw_mean_pct": round(float(view["net_ret"].mean() * 100), 2),
                "n_trades": f5.get("n", 0), "wr_pct": f5.get("wr_pct", 0.0), "plr": f5.get("plr", 0.0),
                "mean_pct": f5.get("mean_pct", 0.0),
                "nav_30": f5.get("nav", 1.0), "ex5_30": f5.get("ex_top5_nav", 1.0),
                "mdd_pct": f5.get("daily_mdd_pct", 0.0), "sharpe": f5.get("daily_sharpe", 0.0), "calmar": f5.get("daily_calmar", 0.0),
                "mtm_diff": ev30["mtm_reconciliation_diff"],
                "excess_csi300_pp": f5.get("excess_csi300_pp", 0.0),
                "nav_50": ev50["windows"].get("FULL_5Y", {}).get("nav", 1.0),
                "nav_80": ev80["windows"].get("FULL_5Y", {}).get("nav", 1.0),
                "n_pre924": pre.get("n", 0), "nav_pre924": pre.get("nav", 1.0), "ex5_pre924": pre.get("ex_top5_nav", 1.0),
                "n_post924": post.get("n", 0), "nav_post924": post.get("nav", 1.0), "ex5_post924": post.get("ex_top5_nav", 1.0),
                "sharpe_post924": post.get("daily_sharpe", 0.0),
                "nav_post924_50": ev50["windows"].get("POST_924", {}).get("nav", 1.0),
                "nav_post924_80": ev80["windows"].get("POST_924", {}).get("nav", 1.0),
                "n_wf": wf23.get("n", 0), "nav_wf": wf23.get("nav", 1.0), "ex5_wf": wf23.get("ex_top5_nav", 1.0),
                "nav_2526": y2526.get("nav", 1.0), "nav_y26": y26.get("nav", 1.0), "nav_26h2": y26h2.get("nav", 1.0),
            })
    blind_df = pd.DataFrame(blind_rows)
    blind_df.to_csv(f"{OUT_DIR}/rd042_track_b_blind.csv", index=False, encoding="utf-8-sig")
    print(f"[TrackB] Blind matrix saved ({len(blind_df)} rows). Top 8 by nav_post924:")
    print(blind_df.sort_values("nav_post924", ascending=False)[["track", "exit_rule", "n_pre924", "nav_pre924", "n_post924", "nav_post924", "ex5_post924", "nav_y26"]].head(8).to_string())

    # 2. B3: Multi-factor 0..100 WF Scorecards (strict exit_date < t) + V20 empty-slot patch + trunc
    wf_specs = [
        ("WF_B1_zt30_S1", "B1_ZT30", "S1_hold1c", None, True),
        ("WF_B1_zt30_S2", "B1_ZT30", "S2_hold2c", None, False),
        ("WF_B1_zt30_S5zt", "B1_ZT30", "S5_zt_ride", None, True),
        ("WF_B1_div_S1", "B1_ZT30", "S1_hold1c", div_open, False),
        ("WF_B1_div_S5zt", "B1_ZT30", "S5_zt_ride", div_open, False),
        ("WF_B1_amt5000w_S1", "B1_ZT30", "S1_hold1c", amt5000w, False),
        ("WF_B2_yang15_S1", "B2_YANG15", "S1_hold1c", None, True),
        ("WF_B2_yang15_S2", "B2_YANG15", "S2_hold2c", None, False),
        ("WF_B2_yang15_spill_S1", "B2_YANG15", "S1_hold1c", spill, False),
        ("WF_B2_yang15_amt5000w_S1", "B2_YANG15", "S1_hold1c", amt5000w, False),
        ("WF_B_ALL15_S1", "ALL", "S1_hold1c", None, True),
        ("WF_B_ALL15_S2", "ALL", "S2_hold2c", None, False),
        ("WF_B_ALL15_S5zt", "ALL", "S5_zt_ride", None, False),
        ("WF_B_ALL15_amt5000w_S1", "ALL", "S1_hold1c", amt5000w, True),
        ("WF_B_ALL15_amt5000w_S5zt", "ALL", "S5_zt_ride", amt5000w, False),
    ]
    wf_rows, wf_audits = [], {}
    for tid, ent, ex, msk, run_tr in wf_specs:
        view = rd_ev.make_clean_view(ev_df, ent, ex, extra_mask=msk, fee_rt=0.0030)
        if len(view) < 60:
            print(f"  [Skip {tid}] len={len(view)}")
            continue
        fcols = get_track_b_features(view)
        au, rows, _ = rd_ev.evaluate_wf_track(
            tid, view, fcols, v20_ctx, liq_col="bj_amt_yi_t1", liq_thresholds=(0.50, 1.00),
            wf_start_req="2023-01-03", end_dt=END_BAR_DATE,
            thresholds=("all_cands", "top30", "top20", "top10", "top5", 70, 75, 80),
            run_trunc=run_tr, min_warmup_trades=45, min_warmup_trades_rare=30, min_warmup_months=12, perm_n=1000,
            extra_eval_windows=[("PRE_924", "2023-01-03", "2024-09-23"), ("POST_924", "2024-09-24", END_BAR_DATE)],
        )
        # Also compute PRE_924 vs POST_924 breakdown on each WF threshold's slot_df via exact eval!
        wf_audits[tid] = au
        wf_rows.extend(rows)
        t20 = [r for r in rows if r["threshold"] == "top20"][0]
        print(f"  -> {tid}: n={t20['n_trades']}, wr={t20['wr_pct']}%, nav30={t20['nav_30']}, ex5={t20['ex5_30']}, nav2526={t20['nav_2526']}, nav26={t20['nav_y26']}, liq5kw={t20['liq_0.5_nav']}, liq1yi={t20['liq_1.0_nav']}, trunc={t20['trunc_pass']} ({au['elapsed_sec']}s)", flush=True)

    wf_df = pd.DataFrame(wf_rows)
    wf_df.to_csv(f"{OUT_DIR}/rd042_track_b_wf.csv", index=False, encoding="utf-8-sig")
    with open(f"{OUT_DIR}/rd042_track_b_audit.json", "w", encoding="utf-8") as f:
        json.dump({"elapsed_sec": round(time.time() - t0, 2), "peak_rss_mb": peak_rss_mb(), "audits": wf_audits}, f, ensure_ascii=False, indent=2)
    print(f"[TrackB] Complete in {time.time()-t0:.1f}s | peak RSS={peak_rss_mb()} MB")


if __name__ == "__main__":
    main()

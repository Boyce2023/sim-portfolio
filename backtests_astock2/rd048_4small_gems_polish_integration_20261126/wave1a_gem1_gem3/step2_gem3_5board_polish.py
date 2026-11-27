#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD048 Wave 1-A Gem 3 (`5board` 2021-01-04..2026-11-24):
  1. Full 5-year reconstruction of 5-board+ episodes using canonical PM spec
     (`fast_five_board_today.py` + `merged_final.csv`: clean PIT ST state machine,
      delisted included, consecutive streak>=5, buy first non-yizi day open<=+5.5%,
      defer >=6 if closed ZT, Day 2..4 frozen 95% line reset_mkt10_line_stk10, D4 close / is_dt defer)
  2. Exact parity audit vs `merged_final.csv` (26/26 settled + 2026-07..11-24 incl. Nov additions)
  3. Structural & low-DOF slice evaluation across 2021-2026, 2023-2025 (explicit slump audit),
     Recent 3Y, 2026, and 26H2:
     - All-market baseline vs SZ 00 vs SH 60
     - Deferred 6+ vs Exact 5
     - Sole highest vs Non-sole
     - PIT Lock >= 50% vs < 50%
     - Low-DOF 2-factor combos + exit ablations + causal rolling regime switch (`exit_date < t`)
  4. D15 (30/50/80bps, ex5, exact MTM Sharpe/MDD, CSI300 excess) + 4 small-sample tests
     (10,000x Bootstrap, Sequential Bayesian + k-loss stop, Contemporaneous Reverse Control Permutation,
      CUSUM/Pettitt Regime Changepoint + 2023-2025 check + Peak DD)
  5. Physical 2024-12-31 truncation re-run (`max_abs_diff == 0.0`)
Zero yfinance (D12). Read-only on production files. Peak RSS < 2.2 GB.
"""
import gc
import json
import math
import os
import resource
import sqlite3
import sys
import warnings
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION"

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import _common_rd048 as cm

ROOT = cm.ROOT
SIM = cm.SIM
OUT_DIR = cm.OUT_DIR
WAVE1_BASE = cm.WAVE1_BASE

WINDOWS_G3 = [
    ("5Y_2021_2026", "2021-01-04", "2026-11-24"),
    ("Recent_3Y_23_26", "2023-11-25", "2026-11-24"),
    ("Period_2023_2025", "2023-01-01", "2025-12-31"),
    ("Y2026", "2026-01-01", "2026-11-24"),
    ("Y26H2", "2026-07-01", "2026-11-24"),
]


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0)


def convert_fee_arr(r: np.ndarray, from_fee: float, to_fee: float) -> np.ndarray:
    return (1.0 + r) / (1.0 - from_fee) * (1.0 - to_fee) - 1.0


def load_bars_for_5b(codes: set[str], max_dt: str = "2026-11-25") -> dict[str, dict]:
    """Load rich daily OHLC + adj_close for candidate 5-board+ codes (single-threaded scanner < 150MB)."""
    if not codes:
        return {}
    import pyarrow as pa
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    tks = sorted({f"{c}.SH" for c in codes} | {f"{c}.SZ" for c in codes})
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume"]
    flt = (ds.field("date") >= pd.Timestamp("2020-11-01")) & (ds.field("date") <= pd.Timestamp(max_dt)) & ds.field("ticker").isin(tks)
    frames = []
    for pq_path, dl_flag in [
        (f"{SIM}/data/cn_hk_price_db/a_daily.parquet", 0),
        (f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", 1),
    ]:
        sc = ds.dataset(pq_path, format="parquet").scanner(columns=cols, filter=flt, batch_size=65536, use_threads=False)
        for batch in sc.to_batches():
            dfb = batch.to_pandas()
            if not dfb.empty:
                dfb = dfb[dfb["volume"] > 0].drop(columns=["volume"]).copy()
                if not dfb.empty:
                    dfb["dl_flag"] = dl_flag
                    frames.append(dfb)
    pa.default_memory_pool().release_unused()
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True)
    del frames
    df["c6"] = df["ticker"].astype(str).str[:6]
    df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["c6", "dt", "dl_flag"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    out = {}
    for c6, g in df.groupby("c6", sort=False):
        g = g.sort_values("dt").reset_index(drop=True)
        dts = g["dt"].tolist()
        op = g["open"].to_numpy(float)
        hi = g["high"].to_numpy(float)
        lo = g["low"].to_numpy(float)
        cl = g["close"].to_numpy(float)
        acl = g["adj_close"].to_numpy(float)
        adjf = np.where((cl > 0) & np.isfinite(acl) & (acl > 0), acl / cl, 1.0)
        cl_adj = cl * adjf
        n = len(dts)
        pre_c = np.zeros(n, dtype=float)
        pre_c[0] = cl[0]
        if n > 1:
            pre_c[1:] = cl[:-1] * adjf[:-1] / adjf[1:]
        zt_px = np.floor(pre_c * 1.10 * 100.0 + 0.5) / 100.0
        dt_px = np.floor(pre_c * 0.90 * 100.0 + 0.5) / 100.0
        pct = np.where(pre_c > 0, cl / pre_c - 1.0, 0.0)
        is_zt = (cl >= zt_px - 0.011) & (pct >= 0.095) & (pre_c > 0)
        is_dt = (cl <= dt_px + 0.011) & (pct <= -0.095) & (pre_c > 0)
        is_yizi_dt = is_dt & (op <= dt_px + 0.011) & (hi <= dt_px + 0.011)
        ma5_adj = pd.Series(cl_adj).rolling(5, min_periods=1).mean().to_numpy(float)
        out[c6] = {
            "dts": dts,
            "dt_idx": {d: i for i, d in enumerate(dts)},
            "open": op,
            "high": hi,
            "low": lo,
            "close": cl,
            "adjf": adjf,
            "cl_adj": cl_adj,
            "pre_c": pre_c,
            "zt_px": zt_px,
            "dt_px": dt_px,
            "is_zt": is_zt,
            "is_dt": is_dt,
            "is_yizi_dt": is_yizi_dt,
            "ma5_adj": ma5_adj,
        }
    return out


def sim_5b_exits(
    c6: str,
    ed: str,
    gb: dict,
    idx_m: dict,
    all_dts: list[str],
    dt_idx: dict[str, int],
    lr_hist: np.ndarray,
    fee: float = 0.0030,
) -> dict:
    """
    Simulate canonical PM DEV95_D2to4 + alternative exits (`D2_close`, `D3_close`, `Broken_close`, `MA5_stop`, `DEV93_D4`)
    strictly on causal executable prices. Returns dict of exit outcomes.
    """
    bmap = gb["dt_idx"]
    em = dt_idx.get(ed)
    bpos = bmap.get(ed)
    if em is None or bpos is None:
        return {}
    bpx = float(gb["open"][bpos])
    ba = float(gb["adjf"][bpos])
    n_b = len(gb["dts"])
    n_m = len(all_dts)

    def _ret(k_idx: int, px: float) -> float:
        return (px * float(gb["adjf"][k_idx])) / (bpx * ba) * (1.0 - fee) - 1.0

    def _first_sellable_after_market_dt(target_dt: str) -> tuple[Optional[str], float, int, str]:
        cands = [i for i in range(n_b) if gb["dts"][i] >= target_dt]
        if not cands:
            return None, np.nan, 925, "unfinished"
        kk = cands[0]
        while kk < n_b and bool(gb["is_dt"][kk]):
            kk += 1
        if kk >= n_b:
            return None, np.nan, 925, "unfinished"
        return gb["dts"][kk], _ret(kk, float(gb["open"][kk])), 925, "delayed"

    def _sim_dev_d2to4(dev_thr: float) -> tuple[Optional[str], float, int, str]:
        for d in (1, 2, 3):
            if em + d >= n_m:
                return None, np.nan, 1500, "unfinished"
            tdt = all_dts[em + d]
            if tdt not in bmap:
                if d == 3:
                    return _first_sellable_after_market_dt(tdt)
                continue
            k = bmap[tdt]
            iprev = idx_m.get(all_dts[em + d - 1])
            caps = []
            for j in range(max(int(lr_hist[k]), k - 10), k):
                ib = idx_m.get(gb["dts"][j])
                if ib and iprev:
                    t_raw = float(gb["cl_adj"][j]) * (1.0 + (iprev / ib - 1.0) + dev_thr) / float(gb["adjf"][k])
                    caps.append(math.ceil(t_raw * 100.0 - 1e-12) / 100.0)
            line_p = min(caps) if caps else 1e9
            ok, hk = float(gb["open"][k]), float(gb["high"][k])
            if ok >= line_p:
                if not bool(gb["is_yizi_dt"][k]):
                    return tdt, _ret(k, ok), 925, "gap_open"
            if hk >= line_p + 0.01 and line_p > float(gb["dt_px"][k]) + 0.01:
                return tdt, _ret(k, line_p), 1030, "trade_through"
            if d == 3:
                if bool(gb["is_dt"][k]):
                    kk = k + 1
                    while kk < n_b and bool(gb["is_dt"][kk]):
                        kk += 1
                    if kk >= n_b:
                        return None, np.nan, 925, "unfinished"
                    return gb["dts"][kk], _ret(kk, float(gb["open"][kk])), 925, "delayed"
                return tdt, _ret(k, float(gb["close"][k])), 1500, "sched_close"
        return None, np.nan, 1500, "unfinished"

    def _sim_fixed_day_close(d_off: int) -> tuple[Optional[str], float, int]:
        if em + d_off >= n_m:
            return None, np.nan, 1500
        tdt = all_dts[em + d_off]
        if tdt not in bmap:
            ex_d, r_v, eh, _ = _first_sellable_after_market_dt(tdt)
            return ex_d, r_v, eh
        k = bmap[tdt]
        if bool(gb["is_dt"][k]):
            kk = k + 1
            while kk < n_b and bool(gb["is_dt"][kk]):
                kk += 1
            if kk >= n_b:
                return None, np.nan, 925
            return gb["dts"][kk], _ret(kk, float(gb["open"][kk])), 925
        return tdt, _ret(k, float(gb["close"][k])), 1500

    def _sim_broken_or_ma5(use_ma5: bool) -> tuple[Optional[str], float, int]:
        # Start checking from bpos: if Day 1 not ZT, exit at Day 2 (em+1) open if weak or Day 2 close if not DT; if ZT, ride until first break / MA5 break
        if not bool(gb["is_zt"][bpos]):
            return _sim_fixed_day_close(1)
        k = bpos + 1
        while k < n_b:
            if bool(gb["is_yizi_dt"][k]):
                k += 1
                continue
            if use_ma5:
                if float(gb["cl_adj"][k]) < float(gb["ma5_adj"][k]):
                    if bool(gb["is_dt"][k]):
                        kk = k + 1
                        while kk < n_b and bool(gb["is_dt"][kk]):
                            kk += 1
                        if kk >= n_b:
                            return None, np.nan, 925
                        return gb["dts"][kk], _ret(kk, float(gb["open"][kk])), 925
                    return gb["dts"][k], _ret(k, float(gb["close"][k])), 1500
            else:
                if not bool(gb["is_zt"][k]):
                    if bool(gb["is_dt"][k]):
                        kk = k + 1
                        while kk < n_b and bool(gb["is_dt"][kk]):
                            kk += 1
                        if kk >= n_b:
                            return None, np.nan, 925
                        return gb["dts"][kk], _ret(kk, float(gb["open"][kk])), 925
                    return gb["dts"][k], _ret(k, float(gb["close"][k])), 1500
            k += 1
        return None, np.nan, 1500

    d95_dt, d95_r, d95_hh, d95_why = _sim_dev_d2to4(0.95)
    d93_dt, d93_r, d93_hh, _ = _sim_dev_d2to4(0.93)
    d2_dt, d2_r, d2_hh = _sim_fixed_day_close(1)
    d3_dt, d3_r, d3_hh = _sim_fixed_day_close(2)
    brk_dt, brk_r, brk_hh = _sim_broken_or_ma5(False)
    ma5_dt, ma5_r, ma5_hh = _sim_broken_or_ma5(True)

    return {
        "bpx": bpx,
        "DEV95": (d95_dt, d95_r, d95_hh, d95_why),
        "DEV93": (d93_dt, d93_r, d93_hh),
        "D2_Close": (d2_dt, d2_r, d2_hh),
        "D3_Close": (d3_dt, d3_r, d3_hh),
        "Broken_Close": (brk_dt, brk_r, brk_hh),
        "MA5_Stop": (ma5_dt, ma5_r, ma5_hh),
    }


def make_iso_g3(
    df: pd.DataFrame,
    vname: str,
    is_slot: bool,
    ex_col: str,
    eh_col: str,
    r30_col: str,
    cal_dts: list[str],
    bar_lu: dict,
) -> pd.DataFrame:
    r30 = df[r30_col].to_numpy(float)
    r50 = convert_fee_arr(r30, 0.0030, 0.0050)
    r80 = convert_fee_arr(r30, 0.0030, 0.0080)
    out = pd.DataFrame({
        "buy_date": df["buy_date"].astype(str).str[:10],
        "buy_hhmm": np.full(len(df), 925, dtype="int64"),
        "exit_date": df[ex_col].astype(str).str[:10],
        "exit_hhmm": df[eh_col].astype("int64"),
        "code": df["code"].astype(str).str.zfill(6),
        "name": df["name"].astype(str),
        "strategy": np.full(len(df), "5board"),
        "tier": np.where(df["is_sz00"], "SZ00", "SH60"),
        "score": df["score"].astype("float64"),
        "net_ret": r30.astype("float64"),
        "buy_price_val": df["buy_price_val"].astype("float64"),
        "is_adj_px": np.full(len(df), False, dtype="bool"),
        "is_untrig": np.full(len(df), False, dtype="bool"),
        "prio": np.full(len(df), 5, dtype="int64"),
        "phase": np.full(len(df), 1, dtype="int64"),
    })
    out["mtm_pairs_json"] = cm.build_mtm_pairs_for_trades(out, cal_dts, bar_lu, ret_col="net_ret", px_col="buy_price_val")
    out["variant"] = vname
    out["is_single_slot"] = bool(is_slot)
    out["gross_ret"] = ((1.0 + r30) / (1.0 - 0.0030) - 1.0).astype("float64")
    out["net_ret_020"] = convert_fee_arr(r30, 0.0030, 0.0020).astype("float64")
    out["net_ret_030"] = r30.astype("float64")
    out["net_ret_050"] = r50.astype("float64")
    out["net_ret_080"] = r80.astype("float64")
    return out


def run_all_gem3(trunc_date: Optional[str] = None) -> dict:
    bench, sh2, sz2, csi, all_dts = cm.load_bench_and_index(include_1126=False)
    if trunc_date:
        bench = bench[bench["trade_date"] <= trunc_date].copy()
        sh2 = {k: v for k, v in sh2.items() if k <= trunc_date}
        sz2 = {k: v for k, v in sz2.items() if k <= trunc_date}
        all_dts = [d for d in all_dts if d <= trunc_date]

    cal_dts = bench["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(all_dts)}

    # Load market ecology & core_pit filtered via single-threaded pyarrow scanner (< 150MB)
    df_mk = pd.read_parquet(f"{WAVE1_BASE}/market_daily_all_new_factors_pit.parquet")
    if trunc_date:
        df_mk = df_mk[df_mk["trade_date"] <= trunc_date].copy()
    mk_map = df_mk.set_index("trade_date").to_dict("index")

    sc_cols = [
        "dt", "c6", "open", "high", "low", "close", "open_pct", "ret_1d",
        "is_zt", "is_yizi_zt", "is_dt", "is_yizi_dt", "is_st_pit", "is_20cm",
        "streak", "prev_streak", "lock_top10_pct_pre", "real_turn_pct_t1",
        "free_mcap_yi_t1", "hr10d_space_t1", "kpl_in_t1", "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1",
    ]
    sc_ds = ds.dataset(f"{WAVE1_BASE}/stock_day_core_features_pit.parquet", format="parquet")
    flt_s = (ds.field("streak") >= 4) | (ds.field("prev_streak") >= 4)
    if trunc_date:
        flt_s = flt_s & (ds.field("dt") <= trunc_date)
    chunks = [b.to_pandas() for b in sc_ds.scanner(columns=sc_cols, filter=flt_s, batch_size=65536, use_threads=False).to_batches()]
    df_sc = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame(columns=sc_cols)
    del chunks
    gc.collect()

    df_sc["dt"] = df_sc["dt"].astype(str)
    df_sc["c6"] = df_sc["c6"].astype(str)
    df_sc = df_sc[(df_sc["c6"].str.startswith(("00", "60"))) & (~df_sc["is_20cm"]) & (~df_sc["is_st_pit"])].sort_values(["c6", "dt"]).reset_index(drop=True)

    # Daily top1 & top2 streaks across non-ST 10cm stocks for sole_highest calculation
    max_s_by_dt = df_sc[df_sc["streak"] >= 4].groupby("dt")["streak"].agg(lambda x: sorted(x.tolist(), reverse=True)).to_dict()

    c5_codes = set(df_sc[df_sc["streak"] >= 5]["c6"].unique())
    max_bar_dt = trunc_date or "2026-11-25"
    bars_5b = load_bars_for_5b(c5_codes, max_dt=max_bar_dt)
    bar_lu = {}
    for c6_k, cb in bars_5b.items():
        for i_k, dt_k in enumerate(cb["dts"]):
            bar_lu[(c6_k, dt_k)] = (float(cb["open"][i_k]), float(cb["close"][i_k]), float(cb["adjf"][i_k]))

    # Stock name map from zt_micro_tape_5y_pit.db + merged_final fallback
    name_map = {}
    con_zt = sqlite3.connect(f"file:{SIM}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for sc6, snm in con_zt.execute("SELECT sec_code, sec_name FROM zt_micro_tape WHERE trade_date <= ? ORDER BY trade_date", (max_bar_dt,)):
        if sc6 in c5_codes and snm:
            name_map[str(sc6).zfill(6)] = str(snm)
    con_zt.close()

    # Precompute lr_hist (reset_mkt10) per c6 in bars_5b
    lr_hist_map = {}
    for c6, gb in bars_5b.items():
        idx_m = sh2 if c6.startswith("6") else sz2
        n_g = len(gb["dts"])
        lr = 0
        lh = np.zeros(n_g, dtype=int)
        for t in range(1, n_g):
            lh[t] = lr
            dt_t = gb["dts"][t]
            it = idx_m.get(dt_t)
            if not it:
                continue
            md = -9.0
            for j in range(max(lr, t - 10), t):
                dt_j = gb["dts"][j]
                if dt_t in dt_idx and dt_j in dt_idx and (dt_idx[dt_t] - dt_idx[dt_j]) > 10:
                    continue
                ij = idx_m.get(dt_j)
                if ij:
                    d_v = (float(gb["cl_adj"][t]) / float(gb["cl_adj"][j]) - 1.0) - (it / ij - 1.0)
                    if d_v > md:
                        md = d_v
            if md >= 1.00:
                lr = t
        lr_hist_map[c6] = lh

    # Construct all 5-board+ episodes across 2021-01-04..max_target
    max_target = trunc_date or "2026-11-24"
    ep_rows = []
    unfinished_rows = []

    for c6 in sorted(c5_codes):
        g_sc = df_sc[df_sc["c6"] == c6].sort_values("dt").reset_index(drop=True)
        gb = bars_5b.get(c6)
        if gb is None:
            continue
        idx_m = sh2 if c6.startswith("6") else sz2
        lh = lr_hist_map[c6]

        five_idxs = g_sc.index[(g_sc["dt"] >= "2021-01-04") & (g_sc["dt"] <= max_target) & (g_sc["streak"] == 5)].tolist()
        for fi in five_idxs:
            sel_row = None
            for k in range(fi + 1, len(g_sc)):
                rk = g_sc.iloc[k]
                if str(rk["dt"]) > max_target:
                    break
                if int(rk["prev_streak"]) < 5:
                    break
                # Entry day: open_pct <= 5.5% and non-yizi
                bpos = gb["dt_idx"].get(str(rk["dt"]))
                if bpos is not None:
                    ok_px = float(gb["open"][bpos])
                    zt_px = float(gb["zt_px"][bpos])
                    op_pct_raw = float(rk["open_pct"])
                    if op_pct_raw <= 5.500001 and ok_px < zt_px - 0.005 and int(rk["is_yizi_zt"]) == 0:
                        sel_row = rk
                        break
                if int(rk["is_zt"]) == 0:
                    break

            if sel_row is None:
                continue

            ed = str(sel_row["dt"])
            h = int(sel_row["prev_streak"])
            k_pos = g_sc.index[g_sc["dt"] == ed][0]
            sig_dt = str(g_sc["dt"].iloc[k_pos - 1])
            top_ss = max_s_by_dt.get(sig_dt, [])
            is_sole_hi = bool(top_ss and (h == top_ss[0]) and (len(top_ss) < 2 or top_ss[1] < h))
            is_mkt_hi = bool(top_ss and (h == top_ss[0]))

            ex_out = sim_5b_exits(c6, ed, gb, idx_m, all_dts, dt_idx, lh, fee=0.0030)
            if not ex_out:
                continue
            d95_dt, d95_r, d95_hh, d95_why = ex_out["DEV95"]
            if d95_dt is None or (trunc_date and d95_dt > trunc_date) or ((not trunc_date) and d95_dt > "2026-11-25"):
                unfinished_rows.append({
                    "buy_date": ed,
                    "code": c6,
                    "name": name_map.get(c6, c6),
                    "height": h,
                    "open_pct": round(float(sel_row["open_pct"]), 2),
                    "lock_top10": round(float(sel_row["lock_top10_pct_pre"] or 0.0), 1),
                    "is_sz00": c6.startswith("00"),
                })
                continue

            mk = mk_map.get(ed, {})
            lock_v = float(sel_row["lock_top10_pct_pre"]) if pd.notna(sel_row["lock_top10_pct_pre"]) else np.nan
            rto_v = float(sel_row["real_turn_pct_t1"]) if pd.notna(sel_row["real_turn_pct_t1"]) else np.nan

            def _safe_ex(tup, fb_dt, fb_r, fb_hh):
                xd, xr, xh = tup
                if xd is None or (trunc_date and xd > trunc_date) or ((not trunc_date) and xd > "2026-11-25") or not np.isfinite(xr):
                    return fb_dt, fb_r, fb_hh
                return xd, float(xr), int(xh)

            d93_dt, d93_r, d93_hh = _safe_ex(ex_out["DEV93"], d95_dt, d95_r, d95_hh)
            d2_dt, d2_r, d2_hh = _safe_ex(ex_out["D2_Close"], d95_dt, d95_r, d95_hh)
            d3_dt, d3_r, d3_hh = _safe_ex(ex_out["D3_Close"], d95_dt, d95_r, d95_hh)
            brk_dt, brk_r, brk_hh = _safe_ex(ex_out["Broken_Close"], d95_dt, d95_r, d95_hh)
            ma5_dt, ma5_r, ma5_hh = _safe_ex(ex_out["MA5_Stop"], d95_dt, d95_r, d95_hh)

            # Tiebreak / score: baseline priority uses height + lock_top10/100 (or open_pct)
            sc_val = float(h * 10 + (10 if c6.startswith("00") else 0) + (5 if is_sole_hi else 0))

            ep_rows.append({
                "buy_date": ed,
                "sig_date": sig_dt,
                "code": c6,
                "name": name_map.get(c6, c6),
                "height": h,
                "open_pct": float(sel_row["open_pct"]),
                "buy_price_val": float(ex_out["bpx"]),
                "is_sz00": c6.startswith("00"),
                "is_sh60": c6.startswith("60"),
                "is_defer6": h >= 6,
                "is_exact5": h == 5,
                "is_sole_highest": is_sole_hi,
                "is_mkt_highest": is_mkt_hi,
                "lock_top10": lock_v,
                "real_to_t1": rto_v,
                "mkt_zt_prev": float(mk.get("L1_zt_cnt_t1", 50.0)),
                "kpl_in_t1": int(sel_row["kpl_in_t1"] or 0),
                "hr10_t1": float(sel_row["hr10d_space_t1"]) if pd.notna(sel_row["hr10d_space_t1"]) else 25.0,
                "score": sc_val,
                "exdt_DEV95": d95_dt, "exhh_DEV95": d95_hh, "ret30_DEV95": d95_r, "why_DEV95": d95_why,
                "exdt_DEV93": d93_dt, "exhh_DEV93": d93_hh, "ret30_DEV93": d93_r,
                "exdt_D2": d2_dt, "exhh_D2": d2_hh, "ret30_D2": d2_r,
                "exdt_D3": d3_dt, "exhh_D3": d3_hh, "ret30_D3": d3_r,
                "exdt_Broken": brk_dt, "exhh_Broken": brk_hh, "ret30_Broken": brk_r,
                "exdt_MA5": ma5_dt, "exhh_MA5": ma5_hh, "ret30_MA5": ma5_r,
            })

    df_ep = pd.DataFrame(ep_rows).sort_values(["buy_date", "code"]).reset_index(drop=True)

    # Parity check against `merged_final.csv` (26 settled)
    parity_info = {}
    if not trunc_date:
        mf = pd.read_csv(f"{ROOT}/docs/90_内部_给Claude读/astock/五板策略明细/merged_final.csv")
        mf_sel = mf[(mf["status"] == "selected") & (mf["DEV95_day2to4_reason"] != "full_day4_horizon_unfinished")].copy()
        mf_sel["c6"] = mf_sel["code"].astype(str).str.zfill(6)
        m_chk = mf_sel.merge(df_ep[["buy_date", "code", "exdt_DEV95", "ret30_DEV95"]], left_on=["entry_date", "c6"], right_on=["buy_date", "code"], how="left")
        m_chk["err_pp"] = np.abs(m_chk["ret30_DEV95"] * 100.0 - m_chk["DEV95_day2to4_net030_pct"])
        parity_info = {
            "merged_final_settled_n": int(len(mf_sel)),
            "matched_n": int(m_chk["ret30_DEV95"].notna().sum()),
            "max_abs_err_pp": round(float(m_chk["err_pp"].max()), 4),
            "med_abs_err_pp": round(float(m_chk["err_pp"].median()), 4),
        }

    # Causal rolling regime switch on SZ00 (strictly exit_date < t, trailing 8 settled SZ00 trades positive mean OR Bayesian P(EV>0)>0.55)
    sz_mask_all = df_ep["is_sz00"].to_numpy(bool)
    bd_arr = df_ep["buy_date"].to_numpy()
    ex_arr = df_ep["exdt_DEV95"].to_numpy()
    r30_arr = df_ep["ret30_DEV95"].to_numpy(float)
    sz_regime_mask = np.zeros(len(df_ep), dtype=bool)
    for i in range(len(df_ep)):
        if not sz_mask_all[i]:
            continue
        hist = r30_arr[(sz_mask_all) & (ex_arr < bd_arr[i])]
        if len(hist) < 8:
            sz_regime_mask[i] = True
        else:
            sz_regime_mask[i] = float(hist[-8:].mean()) > 0.0

    # Boolean conditions
    m_all = np.ones(len(df_ep), dtype=bool)
    m_sz = df_ep["is_sz00"].to_numpy(bool)
    m_sh = df_ep["is_sh60"].to_numpy(bool)
    m_def6 = df_ep["is_defer6"].to_numpy(bool)
    m_ex5 = df_ep["is_exact5"].to_numpy(bool)
    m_sole = df_ep["is_sole_highest"].to_numpy(bool)
    m_mkthi = df_ep["is_mkt_highest"].to_numpy(bool)
    m_lock50 = (df_ep["lock_top10"].fillna(-1).to_numpy(float) >= 50.0)
    m_lock_lt50 = (df_ep["lock_top10"].notna().to_numpy(bool) & (df_ep["lock_top10"].to_numpy(float) < 50.0))
    m_rto15 = (df_ep["real_to_t1"].fillna(0).to_numpy(float) >= 15.0)
    m_act45 = (df_ep["mkt_zt_prev"].to_numpy(float) >= 45.0)
    m_lowop = (df_ep["open_pct"].to_numpy(float) <= 0.0)
    m_kpl = (df_ep["kpl_in_t1"].to_numpy(int) == 1)

    # Variants: (vname, mask, rev_mask, rev_label, exit_tag, is_core)
    variants_spec = [
        # Single-factor & structural slices
        ("G3_Base_All", m_all, ~m_all, "none", "DEV95", True),
        ("G3_SZ00", m_sz, m_sh, "SH60_pure", "DEV95", True),
        ("G3_SH60", m_sh, m_sz, "SZ00_pure", "DEV95", True),
        ("G3_Defer6Plus", m_def6, m_ex5, "Exact5", "DEV95", True),
        ("G3_Exact5", m_ex5, m_def6, "Defer6Plus", "DEV95", False),
        ("G3_SoleHighest", m_sole, ~m_sole, "NonSoleHighest", "DEV95", True),
        ("G3_NonSole", ~m_sole, m_sole, "SoleHighest", "DEV95", False),
        ("G3_MktHighest", m_mkthi, ~m_mkthi, "NonMktHighest", "DEV95", False),
        ("G3_Lock50", m_lock50, m_lock_lt50, "LockLt50", "DEV95", True),
        ("G3_LockLt50", m_lock_lt50, m_lock50, "LockGe50", "DEV95", False),
        # Low-DOF 2-factor / 3-factor combinations
        ("G3_SZ00_SoleHighest", m_sz & m_sole, m_all & (~(m_sz & m_sole)), "Non_SZ00_Sole", "DEV95", True),
        ("G3_SZ00_Defer6Plus", m_sz & m_def6, m_all & (~(m_sz & m_def6)), "Non_SZ00_Defer6", "DEV95", True),
        ("G3_SZ00_Lock50", m_sz & m_lock50, m_sz & m_lock_lt50, "SZ00_LockLt50", "DEV95", True),
        ("G3_SZ00_Lock50_To15", m_sz & m_lock50 & m_rto15, m_sz & (~(m_lock50 & m_rto15)), "SZ00_Other", "DEV95", True),
        ("G3_SoleHighest_Lock50", m_sole & m_lock50, m_all & (~(m_sole & m_lock50)), "Non_Sole_Lock50", "DEV95", True),
        ("G3_Defer6_Lock50", m_def6 & m_lock50, m_all & (~(m_def6 & m_lock50)), "Non_Defer6_Lock50", "DEV95", False),
        ("G3_SZ00_Active45", m_sz & m_act45, m_sz & (~m_act45), "SZ00_ColdLt45", "DEV95", True),
        ("G3_SZ00_LowOpen0", m_sz & m_lowop, m_sz & (~m_lowop), "SZ00_HighOpen", "DEV95", False),
        ("G3_SZ00_KPL", m_sz & m_kpl, m_sz & (~m_kpl), "SZ00_NonKPL", "DEV95", False),
        # Causal rolling regime switch (exit_date < t)
        ("G3_SZ00_CausalRegime8", sz_regime_mask, m_sz & (~sz_regime_mask), "SZ00_RegimeOff", "DEV95", True),
        # Exit ablations on Base & SZ00 & SoleHighest
        ("G3_Base_E_D2", m_all, ~m_all, "none", "D2", False),
        ("G3_Base_E_D3", m_all, ~m_all, "none", "D3", False),
        ("G3_Base_E_Broken", m_all, ~m_all, "none", "Broken", False),
        ("G3_Base_E_MA5", m_all, ~m_all, "none", "MA5", False),
        ("G3_Base_E_DEV93", m_all, ~m_all, "none", "DEV93", False),
        ("G3_SZ00_E_D2", m_sz, m_sh, "SH60_D2", "D2", True),
        ("G3_SZ00_E_D3", m_sz, m_sh, "SH60_D3", "D3", False),
        ("G3_SZ00_E_Broken", m_sz, m_sh, "SH60_Broken", "Broken", True),
        ("G3_SZ00_E_MA5", m_sz, m_sh, "SH60_MA5", "MA5", False),
        ("G3_SZ00_E_DEV93", m_sz, m_sh, "SH60_DEV93", "DEV93", False),
    ]

    results = {}
    all_ledger_frames = []

    for vname, mask, rev_mask, rev_label, ex_tag, is_core in variants_spec:
        ex_c, eh_c, r_c = f"exdt_{ex_tag}", f"exhh_{ex_tag}", f"ret30_{ex_tag}"
        df_w = df_ep.copy()
        df_w["exit_date"] = df_w[ex_c]
        df_w["exit_hhmm"] = df_w[eh_c]
        df_w["net_ret"] = df_w[r_c]

        pass_df, slot_df = cm.select_single_slot(df_w, mask=mask, score_col="score", tie_col="open_pct")
        pass_iso = make_iso_g3(pass_df, vname, False, "exit_date", "exit_hhmm", "net_ret", cal_dts, bar_lu) if not pass_df.empty else pd.DataFrame()
        slot_iso = make_iso_g3(slot_df, vname, True, "exit_date", "exit_hhmm", "net_ret", cal_dts, bar_lu) if not slot_df.empty else pd.DataFrame()

        _, mtm_diff_full = cm.daily_mtm_series(slot_iso, cal_dts, ret_col="net_ret") if not slot_iso.empty else (np.zeros(len(cal_dts)), 0.0)
        d15 = cm.evaluate_d15_windows(slot_iso, pass_iso, bench, WINDOWS_G3, base_fee=0.0030)

        rets_ss = slot_iso["net_ret"].to_numpy(float) if not slot_iso.empty else np.array([], dtype=float)
        rev_df = df_w[rev_mask].copy() if np.any(rev_mask) else pd.DataFrame()
        t1 = cm.tool1_bootstrap(rets_ss, n_boot=10000, seed=42)
        t2 = cm.tool2_bayesian_posterior(rets_ss)
        t3 = cm.tool3_reverse_control_perm(rets_ss, rev_df, n_perm=10000, seed=42, rev_label=rev_label)
        t4 = cm.tool4_regime_changepoint_and_dd(slot_iso, n_perm=2000, seed=42)

        # Also evaluate 26H2 reverse-control permutation specifically so 26H2 vs 5Y contrast is explicit
        t3_h2 = {}
        if not slot_iso.empty and not rev_df.empty:
            s_h2 = slot_iso[slot_iso["buy_date"] >= "2026-07-01"]["net_ret"].to_numpy(float)
            r_h2 = rev_df[rev_df["buy_date"] >= "2026-07-01"].copy()
            if len(s_h2) >= 2 and len(r_h2) >= 2:
                t3_h2 = cm.tool3_reverse_control_perm(s_h2, r_h2, n_perm=10000, seed=42, rev_label=f"{rev_label}_26H2")

        results[vname] = {
            "is_core": is_core,
            "exit_rule": ex_tag,
            "ss_n": int(len(slot_iso)),
            "raw_n": int(len(pass_iso)),
            "mtm_diff": round(float(mtm_diff_full), 10),
            "d15": d15,
            "tool1_bootstrap": t1,
            "tool2_bayesian": t2,
            "tool3_reverse_control": t3,
            "tool3_reverse_control_26H2": t3_h2,
            "tool4_regime_dd": t4,
        }

        if not trunc_date and is_core:
            if not slot_iso.empty:
                all_ledger_frames.append(slot_iso)
            if not pass_iso.empty:
                all_ledger_frames.append(pass_iso)

    return {
        "parity": parity_info,
        "total_settled_episodes": int(len(df_ep)),
        "unfinished_20261124": unfinished_rows,
        "variants": results,
        "ledger_df": pd.concat(all_ledger_frames, ignore_index=True) if all_ledger_frames else pd.DataFrame(),
        "rss_mb": round(rss_mb(), 1),
    }


def main():
    import argparse
    import subprocess
    import pyarrow as pa
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)

    parser = argparse.ArgumentParser()
    parser.add_argument("--trunc-only-out", default="")
    args = parser.parse_args()

    if args.trunc_only_out:
        tr = run_all_gem3(trunc_date="2024-12-31")
        tr.pop("ledger_df", None)
        pa.default_memory_pool().release_unused()
        with open(args.trunc_only_out, "w", encoding="utf-8") as f:
            json.dump(cm.sanitize_json({"rss_mb": round(rss_mb(), 1), "variants": tr["variants"]}), f, ensure_ascii=False)
        return

    print("[RD048 Wave1-A Gem 3] Running full 5-year 2021-01-04..2026-11-24 reconstruction & polish...")
    full_res = run_all_gem3(trunc_date=None)

    parquet_path = f"{OUT_DIR}/rd048_gem3_trades.parquet"
    json_path = f"{OUT_DIR}/rd048_gem3_5board.json"
    full_ledger_df = full_res.pop("ledger_df")
    full_ledger_df.to_parquet(parquet_path, index=False)

    trunc_ref_map = {}
    for vname, full_v in full_res["variants"].items():
        if not full_v["is_core"]:
            continue
        sub_f = full_ledger_df[(full_ledger_df["variant"] == vname) & (full_ledger_df["is_single_slot"]) & (full_ledger_df["exit_date"] <= "2024-12-31")].sort_values(["buy_date", "code"]).reset_index(drop=True)
        if not sub_f.empty:
            trunc_ref_map[vname] = (
                int(len(sub_f)),
                round(float(np.prod(1.0 + sub_f["net_ret"].to_numpy(float))), 4),
                round(float(sub_f["net_ret"].to_numpy(float).mean() * 100.0), 2),
            )
        else:
            trunc_ref_map[vname] = (0, 1.0, 0.0)
    parquet_rows = int(len(full_ledger_df))
    parquet_cols = list(full_ledger_df.columns)
    del full_ledger_df
    gc.collect()
    pa.default_memory_pool().release_unused()

    print("[RD048 Wave1-A Gem 3] Running 2024-12-31 physical truncation verification in isolated child process...")
    tmp_trunc = f"{OUT_DIR}/_tmp_g3_trunc.json"
    subprocess.run([sys.executable, os.path.abspath(__file__), "--trunc-only-out", tmp_trunc], check=True)
    with open(tmp_trunc, encoding="utf-8") as f:
        trunc_res = json.load(f)
    os.remove(tmp_trunc)

    trunc_diffs = {}
    max_abs_diff = 0.0
    for vname, (f_n, f_nav, f_mean) in trunc_ref_map.items():
        tv = trunc_res["variants"].get(vname, {})
        t_win = tv.get("d15", {}).get("5Y_2021_2026", {})
        t_nav = t_win.get("nav", 1.0)
        t_mean = t_win.get("mean_pct", 0.0)
        t_n = t_win.get("ss_n", 0)
        d_nav = abs(f_nav - t_nav)
        d_mean = abs(f_mean - t_mean)
        d_n = abs(f_n - t_n)
        max_abs_diff = max(max_abs_diff, d_nav, d_mean, float(d_n))
        trunc_diffs[vname] = {"full_n": f_n, "trunc_n": t_n, "nav_diff": round(d_nav, 10), "mean_diff": round(d_mean, 10)}

    max_mtm_diff = max(v["mtm_diff"] for v in full_res["variants"].values())
    peak_rss = max(round(rss_mb(), 1), float(trunc_res.get("rss_mb", 0.0)))

    out_json = {
        "meta": {
            "strategy": "Gem3_5board",
            "window": "2021-01-04..2026-11-24",
            "primary_fee_bps": 30,
            "stress_fee_bps": [50, 80],
            "parquet_path": parquet_path,
            "parquet_rows": parquet_rows,
            "parquet_cols": parquet_cols,
            "total_settled_episodes": full_res["total_settled_episodes"],
            "max_mtm_diff": round(max_mtm_diff, 10),
            "trunc_20241231_max_abs_diff": round(max_abs_diff, 10),
            "peak_rss_mb": peak_rss,
            "parent_rss_mb": round(rss_mb(), 1),
            "trunc_child_rss_mb": float(trunc_res.get("rss_mb", 0.0)),
        },
        "merged_final_parity": full_res["parity"],
        "unfinished_20261124": full_res["unfinished_20261124"],
        "truncation_20241231_audit": trunc_diffs,
        "variants": full_res["variants"],
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(out_json), f, ensure_ascii=False, indent=2)

    print(f"Saved: {json_path} & {parquet_path} | rows={parquet_rows} | peak_rss={peak_rss:.1f}MB (parent={rss_mb():.1f}MB, child={trunc_res.get('rss_mb',0):.1f}MB)")
    print(f"Parity={full_res['parity']} | max_mtm_diff={max_mtm_diff} | trunc_max_diff={max_abs_diff}")
    print("\n--- Gem 3 All Variants Summary (30bps primary) ---")
    for vn, vd in full_res["variants"].items():
        fw = vd["d15"]["5Y_2021_2026"]
        p23 = vd["d15"]["Period_2023_2025"]
        y26 = vd["d15"]["Y2026"]
        h2 = vd["d15"]["Y26H2"]
        b1 = vd["tool1_bootstrap"]
        b2 = vd["tool2_bayesian"]["priors"]["Beta(2,2)_neutral"]
        t3 = vd["tool3_reverse_control"].get("perm_vs_rev_slot", {})
        t4 = vd["tool4_regime_dd"]
        cp = t4.get("changepoint", {})
        print(f"{vn:22s} | n={fw['ss_n']:3d}(raw={fw['raw_n']:3d}) | WR={fw['wr_pct']:5.1f}% PLR={fw['plr']:4.2f} | 5Y={fw['nav']:6.3f}x ex5={fw['ex5_nav']:5.3f}x Sh={fw['daily_sharpe']:5.2f} | 23-25:{p23['ss_n']:3d}b {p23['nav']:5.3f}x | H2:{h2['ss_n']:2d}b WR={h2['wr_pct']:4.1f}% {h2['nav']:5.2f}x | Boot={b1['prob_mean_gt_0']:.3f} k={b2['k_consec_loss_prob50_capped25']} perm_p={t3.get('p_mean_1s',1):.3f} | cp={cp.get('changepoint_date')}(p={cp.get('cusum_p_perm',1):.3f})")


if __name__ == "__main__":
    main()

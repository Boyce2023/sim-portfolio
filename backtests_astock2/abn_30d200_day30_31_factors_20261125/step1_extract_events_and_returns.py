#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 1: Strict PIT Extraction of 30d-200% Near-Miss ("卡住严重异动") Events (2021-01-01 ~ 2026-11-24)
& Exact Physical Trade Simulation (D30 Close Buy vs D31 Open Buy).
- Merges active a_daily.parquet + delisted a_delisted_daily.parquet (zero survivorship bias).
- Zero static st_universe.json usage; strict causal PIT ST detection (KPL + CNINFO title + 5% band).
- Strictly no yfinance; strictly no cap10m; computes single-slot rotation, daily EW, and HS300 excess.
"""

import json
import os
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = Path("/Users/huaichuaibeimeng/claude-projects")
SIM = ROOT / "sim-portfolio"
OUT_DIR = SIM / "backtests_astock2/abn_30d200_day30_31_factors_20261125"
OUT_DIR.mkdir(parents=True, exist_ok=True)

A_DAILY = SIM / "data/cn_hk_price_db/a_daily.parquet"
A_DELISTED = SIM / "data/cn_hk_price_db/a_delisted_daily.parquet"
IDX_JSON = SIM / "backtests_astock/sandbox_lab/index_klines_5y_cache.json"
KPL_JSONL = SIM / "data/kpl_plates_2018_2026_merged.jsonl"
CNINFO_DB = SIM / "data/cninfo_notices_5y_pit.db"

FEE_30BPS = 0.0030
FEE_50BPS = 0.0050


def load_indices():
    with open(IDX_JSON, encoding="utf-8") as f:
        idx_js = json.load(f)
    out = {}
    for k in ("sh000002", "sz399107", "sh000300"):
        d = idx_js[k]
        s = pd.Series(
            {pd.Timestamp(dt): float(v["close"] if isinstance(v, dict) else v) for dt, v in d.items()}
        ).sort_index()
        out[k] = s
    return out


def build_pit_st_history():
    """
    Build strict causal ST intervals per 6-digit code using:
    1) KPL daily stock name containing 'ST' or plate == 'ST板块' (PIT on each date)
    2) CNINFO notice title prefix/content (PIT on trade_date_avail; NEVER uses backfilled sec_name!)
    """
    kpl_st_dates = defaultdict(set)
    name_latest_pit = {}
    with open(KPL_JSONL, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            dt = obj.get("date", "")
            if dt < "2020-01-01":
                continue
            for pl in obj.get("plates", []):
                pname = pl.get("plate", "")
                for st in pl.get("stocks", []):
                    if isinstance(st, dict):
                        c6 = str(st.get("code", ""))[:6].zfill(6)
                        nm = str(st.get("name", ""))
                    elif isinstance(st, list) and len(st) >= 2:
                        c6 = str(st[0])[:6].zfill(6)
                        nm = str(st[1])
                    else:
                        continue
                    if "ST" in nm.upper() or pname == "ST板块":
                        kpl_st_dates[c6].add(dt)
                    name_latest_pit[(c6, dt)] = nm.strip()

    # CNINFO title-based PIT ST events (start ST vs revoke ST)
    conn = sqlite3.connect(f"file:{CNINFO_DB}?mode=ro", uri=True)
    # Only query notices mentioning ST or 风险警示 to stay super fast
    q = """
    SELECT sec_code, trade_date_avail, title
    FROM notices
    WHERE title LIKE '%ST%' OR title LIKE '%风险警示%'
    ORDER BY sec_code, trade_date_avail
    """
    cn_st_prefix_dates = defaultdict(list)  # (date, is_st_bool)
    title_st_re = re.compile(r"^(?:【[^】]*】)?\s*\*?ST|(?::|：)\s*\*?ST")
    apply_re = re.compile(r"(实施(?:退市|其他)?风险警示|被实施.*风险警示|股票简称变更为\*?ST)")
    revoke_re = re.compile(r"(撤销(?:退市|其他)?风险警示|申请撤销.*风险警示.*获准|股票简称.*变更为(?!\*?ST))")
    for c6, dt, title in conn.execute(q):
        c6 = str(c6)[:6].zfill(6)
        t = str(title or "")
        if revoke_re.search(t) and "不予" not in t and "未能" not in t and "提示性" not in t:
            cn_st_prefix_dates[c6].append((dt, False))
        elif title_st_re.match(t) or apply_re.search(t):
            cn_st_prefix_dates[c6].append((dt, True))
    conn.close()
    return kpl_st_dates, cn_st_prefix_dates, name_latest_pit


def is_pit_st(c6: str, t0_dt: str, d30_dt: str, pct_win: np.ndarray, is_20: bool,
              kpl_st_dates: dict, cn_st_events: dict) -> tuple[bool, str]:
    """Strictly causal PIT check whether c6 is ST on D30 (or during [t0..D30])."""
    # 1. Mainboard empirical 5% daily price limit band during the +165%+ 30d run
    if not is_20 and len(pct_win) >= 15:
        max_abs = float(np.nanmax(np.abs(pct_win)))
        cap_days = int(np.sum((np.abs(pct_win) >= 0.045) & (np.abs(pct_win) <= 0.056)))
        if max_abs <= 0.056 and cap_days >= 2:
            return True, "5pct_band"

    # 2. KPL PIT ST tag within [t0-90d .. D30]
    k_dts = kpl_st_dates.get(c6)
    if k_dts:
        # Check if any KPL ST tag appeared between t0_dt - 180d and d30_dt
        lo_bound = (pd.Timestamp(t0_dt) - pd.Timedelta(days=180)).strftime("%Y-%m-%d")
        if any(lo_bound <= kd <= d30_dt for kd in k_dts):
            return True, "kpl_st"

    # 3. CNINFO chronological title status up to d30_dt
    evs = cn_st_events.get(c6)
    if evs:
        st_state = False
        last_true = None
        for dt, flag in evs:
            if dt > d30_dt:
                break
            st_state = flag
            if flag:
                last_true = dt
        if st_state:
            return True, "cninfo_st"
        if last_true is not None and last_true >= t0_dt:
            return True, "cninfo_st_during_wave"

    return False, ""


def load_merged_prices():
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2020-09-01")
    d1 = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    d1["is_delisted_src"] = 0
    d2 = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    d2["is_delisted_src"] = 1
    df = pd.concat([d1, d2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & df["c6"].str.startswith(("00", "60", "300", "301", "688", "689"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str", "is_delisted_src"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)
    print(f"[Prices] Loaded {len(df)} rows, {df['c6'].nunique()} stocks (active+delisted) in {time.time()-t0:.1f}s")
    return df


def compute_exit_return(buy_px, target_ex, n, open_a, close_a, is_dt_a, is_yz_dt_a, dts_str, fee):
    """Simulate realistic exit at target_ex close (or D31 open if target_ex_mode='open') with limit-down deferral."""
    if target_ex >= n or not (buy_px > 0):
        return np.nan, None, False
    ex = target_ex
    deferred = False
    while ex < n - 1 and is_yz_dt_a[ex]:
        ex += 1
        deferred = True
    if is_yz_dt_a[ex]:
        s_px = close_a[ex]
    elif is_dt_a[ex] and ex < n - 1:
        deferred = True
        ex2 = ex + 1
        while ex2 < n - 1 and is_yz_dt_a[ex2]:
            ex2 += 1
        s_px = open_a[ex2] if not is_yz_dt_a[ex2] else close_a[ex2]
        ex = ex2
    else:
        s_px = close_a[ex]
    if not (s_px > 0):
        return np.nan, None, deferred
    return (s_px / buy_px) * (1.0 - fee) - 1.0, dts_str[ex], deferred


def compute_open_exit_return(buy_px, target_ex, n, open_a, close_a, is_yz_dt_a, dts_str, fee):
    """Sell at target_ex OPEN (e.g. D31 open or D32 open), deferring if locked yizi limit-down."""
    if target_ex >= n or not (buy_px > 0):
        return np.nan, None, False
    ex = target_ex
    deferred = False
    while ex < n - 1 and is_yz_dt_a[ex]:
        ex += 1
        deferred = True
    s_px = open_a[ex] if not is_yz_dt_a[ex] else close_a[ex]
    if not (s_px > 0):
        return np.nan, None, deferred
    return (s_px / buy_px) * (1.0 - fee) - 1.0, dts_str[ex], deferred


def main():
    t_start = time.time()
    idx_map = load_indices()
    sh_s = idx_map["sh000002"]
    sz_s = idx_map["sz399107"]
    hs_s = idx_map["sh000300"]

    kpl_st_dates, cn_st_events, kpl_names = build_pit_st_history()
    df = load_merged_prices()

    # Global market calendar mapping
    all_mkt_dts = sorted(df["dt_str"].unique())
    mkt_pos = {d: idx for idx, d in enumerate(all_mkt_dts)}
    sh_aligned = sh_s.reindex(pd.to_datetime(all_mkt_dts)).ffill()
    sz_aligned = sz_s.reindex(pd.to_datetime(all_mkt_dts)).ffill()
    sh_dict = {d: float(v) for d, v in zip(all_mkt_dts, sh_aligned.values)}
    sz_dict = {d: float(v) for d, v in zip(all_mkt_dts, sz_aligned.values)}

    # Build CNINFO name map (only non-ST or earliest reliable name for display, prefer KPL name)
    events_hold = []
    events_breach = []
    st_skipped = []

    for c6, sub in df.groupby("c6", sort=False):
        sub = sub.reset_index(drop=True)
        n = len(sub)
        if n < 60:
            continue
        adj_c = sub["adj_close"].values.astype(float)
        if np.any(adj_c <= 0):
            continue
        # Fast pre-filter: ever had 30d move >= 145%
        s_c = pd.Series(adj_c)
        if float((s_c / s_c.rolling(31).min() - 1.0).max()) < 1.45:
            continue

        is_20 = c6.startswith(("300", "301", "688", "689"))
        lim_exact = 0.20 if is_20 else 0.10
        lim_thr = 0.194 if is_20 else 0.094

        dts_str = sub["dt_str"].values
        raw_o = sub["open"].values.astype(float)
        raw_hi = sub["high"].values.astype(float)
        raw_lo = sub["low"].values.astype(float)
        raw_c = sub["close"].values.astype(float)
        qfq = sub["qfq_factor"].values.astype(float)
        ratio = np.where(raw_c > 0, adj_c / raw_c, 1.0)
        adj_o = raw_o * ratio
        adj_hi = raw_hi * ratio
        adj_lo = raw_lo * ratio

        pre_adj_c = np.r_[np.nan, adj_c[:-1]]
        pct = adj_c / pre_adj_c - 1.0
        o_pct = adj_o / pre_adj_c - 1.0

        # Exact tick limit prices (using pre_raw_c when no XD, else adjusted)
        pre_raw_c = np.r_[np.nan, raw_c[:-1]]
        pre_qfq = np.r_[np.nan, qfq[:-1]]
        no_xd = np.abs(qfq / np.where(pre_qfq > 0, pre_qfq, np.nan) - 1.0) < 1e-6
        ref_c = np.where(no_xd, pre_raw_c, pre_adj_c / np.where(ratio > 0, ratio, 1.0))
        zt_px = np.floor(ref_c * (1.0 + lim_exact) * 100.0 + 0.5) / 100.0
        dt_px = np.floor(ref_c * (1.0 - lim_exact) * 100.0 + 0.5) / 100.0

        is_zt = (raw_c >= zt_px - 0.011) & (pct >= lim_thr) & (pre_adj_c > 0)
        is_dt = (raw_c <= dt_px + 0.011) & (pct <= -lim_thr) & (pre_adj_c > 0)
        # Closed sealed at limit-up (cannot buy at close 14:55-15:00)
        close_sealed_zt = is_zt & (raw_c >= raw_hi - 0.005)
        is_yizi_zt = is_zt & (raw_o >= zt_px - 0.011) & (raw_lo >= zt_px - 0.011)
        is_yizi_dt = is_dt & (raw_o <= dt_px + 0.011) & (raw_hi <= dt_px + 0.011)

        idx_arr = np.array([sh_dict[d] if c6.startswith(("60", "688", "689")) else sz_dict[d] for d in dts_str], dtype=float)
        if np.any(idx_arr <= 0):
            continue

        # Compute exact max_dev30[i] and binding base_idx[i] for i >= 30
        max_dev30 = np.full(n, -9.0)
        base_idx = np.full(n, -1, dtype=int)
        for i in range(30, n):
            bases = np.arange(i - 30, i)
            devs = (adj_c[i] / adj_c[bases] - 1.0) - (idx_arr[i] / idx_arr[bases] - 1.0)
            bi = int(np.argmax(devs))
            max_dev30[i] = devs[bi]
            base_idx[i] = bases[bi]

        last_ev_peak = -999
        last_ev_end = -999
        last_ev_breach = -999
        for i in range(35, n - 1):  # i is D30, i+1 is D31!
            d30_dt = str(dts_str[i])
            d31_dt = str(dts_str[i + 1])
            if d30_dt < "2021-01-01" or d31_dt > "2026-11-24":
                continue

            t0 = i - 30
            if base_idx[i] != t0:
                continue

            devs_from_t0 = (adj_c[t0 + 1:i + 1] / adj_c[t0] - 1.0) - (idx_arr[t0 + 1:i + 1] / idx_arr[t0] - 1.0)
            peak_dev = float(np.max(devs_from_t0))
            if peak_dev < 1.65:
                continue

            end_dev = float(devs_from_t0[-1])
            win_max_any = float(np.max(max_dev30[t0 + 1:i + 1]))
            is_hold = win_max_any < 2.00

            if is_hold:
                cand_peak = (i - last_ev_peak >= 25)
                cand_end = (end_dev >= 1.65) and (i - last_ev_end >= 25)
                if not cand_peak and not cand_end:
                    continue
            else:
                cand_peak = False
                cand_end = False
                if i - last_ev_breach < 25:
                    continue

            t0_dt = str(dts_str[t0])
            st_flag, st_reason = is_pit_st(c6, t0_dt, d30_dt, pct[t0:i + 1], is_20, kpl_st_dates, cn_st_events)
            if st_flag:
                if is_hold:
                    st_skipped.append((d30_dt, c6, st_reason, round(end_dev * 100, 1)))
                continue

            # Roll-out relief on D31 (dropping t0) and over D31..D33 (dropping t0..t0+2, strictly PIT!)
            ex_t0 = float(np.max((adj_c[i] / adj_c[t0 + 1:i] - 1.0) - (idx_arr[i] / idx_arr[t0 + 1:i] - 1.0)))
            relief_1d_pp = (end_dev - ex_t0) * 100.0
            ex_3d = float(np.max((adj_c[i] / adj_c[t0 + 3:i] - 1.0) - (idx_arr[i] / idx_arr[t0 + 3:i] - 1.0)))
            relief_3d_pp = (end_dev - ex_3d) * 100.0

            peak_c = float(np.max(adj_c[t0 + 1:i + 1]))
            dd_at_d30 = (adj_c[i] / peak_c - 1.0) * 100.0

            # Market trading day gaps
            d31_mkt_gap = mkt_pos[d31_dt] - mkt_pos[d30_dt]
            d30_buyable_close = not bool(close_sealed_zt[i])
            d30_not_yizi = not bool(is_yizi_zt[i])
            d31_buyable_open = (not bool(is_yizi_zt[i + 1])) and (not bool(is_yizi_dt[i + 1])) and (d31_mkt_gap == 1)
            d31_open_zt = bool(o_pct[i + 1] >= lim_thr)

            # Display name from KPL (latest <= d30_dt) or c6
            disp_name = c6
            for kd in sorted([d for (cc, d) in kpl_names if cc == c6 and d <= d30_dt], reverse=True)[:1]:
                disp_name = kpl_names[(c6, kd)]

            rec = {
                "c6": c6,
                "ticker": sub["ticker"].iloc[0],
                "name": disp_name,
                "is_20": bool(is_20),
                "is_delisted_src": int(sub["is_delisted_src"].iloc[0]),
                "t0_date": t0_dt,
                "d30_date": d30_dt,
                "d31_date": d31_dt,
                "d30_yr": int(d30_dt[:4]),
                "d31_yr": int(d31_dt[:4]),
                "t0_idx": int(t0),
                "d30_idx": int(i),
                "peak_dev30": round(peak_dev * 100.0, 2),
                "end_dev30": round(end_dev * 100.0, 2),
                "win_max_any": round(win_max_any * 100.0, 2),
                "relief_1d_pp": round(relief_1d_pp, 2),
                "relief_3d_pp": round(relief_3d_pp, 2),
                "dd_at_d30": round(dd_at_d30, 2),
                "d30_pct": round(float(pct[i]) * 100.0, 2),
                "d30_close_zt": bool(close_sealed_zt[i]),
                "d30_yizi": bool(is_yizi_zt[i]),
                "d30_buyable": bool(d30_buyable_close),
                "d31_yizi": bool(is_yizi_zt[i + 1]),
                "d31_open_zt": bool(d31_open_zt),
                "d31_mkt_gap": int(d31_mkt_gap),
                "d31_buyable": bool(d31_buyable_open),
                "d31_gap": round(float(o_pct[i + 1]) * 100.0, 2),
                "d31_c2c": round(float(pct[i + 1]) * 100.0, 2),
                "d31_o2c": round(float(adj_c[i + 1] / adj_o[i + 1] - 1.0) * 100.0, 2) if adj_o[i + 1] > 0 else np.nan,
            }

            # Entry A: D30 Close Buy -> D31 Open, D31 Close, D32 Close, D33 Close, D35 Close, D40 Close, D50 Close
            b_d30c = adj_c[i]
            for fee, ftag in [(FEE_30BPS, "30"), (FEE_50BPS, "50")]:
                r_o, dt_o, df_o = compute_open_exit_return(b_d30c, i + 1, n, adj_o, adj_c, is_yizi_dt, dts_str, fee)
                rec[f"r30c_d31o_f{ftag}"] = r_o
                if ftag == "30":
                    rec["exdt_30c_d31o"] = dt_o
                    rec["def_30c_d31o"] = df_o
                for h in (1, 2, 3, 5, 10, 20):
                    r_h, dt_h, df_h = compute_exit_return(b_d30c, i + h, n, adj_o, adj_c, is_dt, is_yizi_dt, dts_str, fee)
                    rec[f"r30c_d{30+h}c_f{ftag}"] = r_h
                    if ftag == "30":
                        rec[f"exdt_30c_d{30+h}c"] = dt_h
                        rec[f"def_30c_d{30+h}c"] = df_h

            # Entry B: D31 Open Buy -> D32 Open, D32 Close, D33 Close, D35 Close, D40 Close, D50 Close
            # Plus non-T+1 diagnostic D31 Open -> D31 Close
            b_d31o = adj_o[i + 1]
            for fee, ftag in [(FEE_30BPS, "30"), (FEE_50BPS, "50")]:
                r_t0diag, _, _ = compute_exit_return(b_d31o, i + 1, n, adj_o, adj_c, is_dt, is_yizi_dt, dts_str, fee)
                rec[f"r31o_d31c_t0diag_f{ftag}"] = r_t0diag
                r_32o, dt_32o, _ = compute_open_exit_return(b_d31o, i + 2, n, adj_o, adj_c, is_yizi_dt, dts_str, fee)
                rec[f"r31o_d32o_f{ftag}"] = r_32o
                if ftag == "30":
                    rec["exdt_31o_d32o"] = dt_32o
                for h in (2, 3, 5, 10, 20):
                    r_h, dt_h, df_h = compute_exit_return(b_d31o, i + h, n, adj_o, adj_c, is_dt, is_yizi_dt, dts_str, fee)
                    rec[f"r31o_d{30+h}c_f{ftag}"] = r_h
                    if ftag == "30":
                        rec[f"exdt_31o_d{30+h}c"] = dt_h
                        rec[f"def_31o_d{30+h}c"] = df_h

            if is_hold:
                rec["in_peak_pool"] = bool(cand_peak)
                rec["in_end_pool"] = bool(cand_end)
                events_hold.append(rec)
                if cand_peak:
                    last_ev_peak = i
                if cand_end:
                    last_ev_end = i
            else:
                rec["in_peak_pool"] = True
                rec["in_end_pool"] = bool(end_dev >= 1.65)
                events_breach.append(rec)
                last_ev_breach = i

    eh = pd.DataFrame(events_hold)
    eb = pd.DataFrame(events_breach)
    eh.to_parquet(OUT_DIR / "events_hold_base.parquet", index=False)
    eb.to_parquet(OUT_DIR / "events_breach_base.parquet", index=False)
    print(f"[Events] Strict Hold (<200%): total={len(eh)} (10cm={(~eh['is_20']).sum()}, 20cm={eh['is_20'].sum()}, delisted={eh['is_delisted_src'].sum()})")
    print(f"[Events] Breach (>=200%): total={len(eb)} (10cm={(~eb['is_20']).sum()}, 20cm={eb['is_20'].sum()})")
    print(f"[ST Skipped] {len(st_skipped)} PIT ST events excluded: {st_skipped[:10]}")
    print(f"[Suspensions] d31_mkt_gap > 1 count in Hold: {(eh['d31_mkt_gap'] > 1).sum()}")
    print(f"Done in {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    main()

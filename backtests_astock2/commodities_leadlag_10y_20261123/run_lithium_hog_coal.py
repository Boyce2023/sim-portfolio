#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RD021 Commodities vs Equities Lead-Lag & Strategy Backtest: Lithium, Hog, Coal.
Strictly reads local cleaned parquets in data_cache/. Zero external network/yfinance calls.
All signals <= t close; trades execute at t+1 open with 0.15% buy + 0.15% sell (0.30% RT).
"""
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from scipy.stats import t as student_t

ROOT = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/commodities_leadlag_10y_20261123")
DATA_DIR = ROOT / "data_cache"
OUT_JSON = ROOT / "results_lithium_hog_coal.json"
sys.path.append("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/theory_backtest_15y_20261119")
from tei_metrics import compute_period_metrics  # noqa: E402

NAMES = {
    "002714.SZ": "牧原股份",
    "300498.SZ": "温氏股份",
    "HOG_EQ": "生猪等权(牧原+温氏)",
    "002460.SZ": "赣锋锂业",
    "002466.SZ": "天齐锂业",
    "000792.SZ": "盐湖股份",
    "LITHIUM_EQ_3": "锂电3龙等权(赣锋+天齐+盐湖)",
    "LITHIUM_EQ_2": "锂电2龙等权(赣锋+天齐)",
    "ALB": "Albemarle",
    "SQM": "SQM",
    "US_LI_EQ": "美股锂等权(ALB+SQM)",
    "000983.SZ": "山西焦煤",
    "601699.SH": "潞安环能",
    "601088.SH": "中国神华",
    "COAL_EQ": "煤炭3龙等权(焦煤+潞安+神华)",
    "COAL_COKING_EQ": "双焦纯度等权(焦煤+潞安)",
}


def load_all_data() -> dict:
    a_close = pd.read_parquet(DATA_DIR / "a_stocks_close.parquet").sort_index()
    a_open = pd.read_parquet(DATA_DIR / "a_stocks_open.parquet").sort_index()
    us_close = pd.read_parquet(DATA_DIR / "us_stocks_close.parquet").sort_index()
    cn_fut = pd.read_parquet(DATA_DIR / "cn_futures_close.parquet").sort_index()
    hog = pd.read_parquet(DATA_DIR / "hog_spot_weekly.parquet").sort_index()
    hog = hog[~hog.index.duplicated(keep="last")]
    nc = pd.read_parquet(DATA_DIR / "newcastle_coal_monthly.parquet").sort_index()
    hs300 = pd.read_parquet(DATA_DIR / "sh000300.parquet").sort_index()["sh000300"]
    return {
        "a_close": a_close,
        "a_open": a_open,
        "us_close": us_close,
        "cn_fut": cn_fut,
        "hog_weekly": hog["hog_spot"],
        "nc_monthly": nc["newcastle_coal"],
        "hs300": hs300,
    }


def build_ew_index(df_close: pd.DataFrame, tickers: List[str], cal: pd.DatetimeIndex) -> pd.Series:
    sub = df_close[tickers].reindex(cal).ffill()
    rets = sub.pct_change(fill_method=None)
    ew_ret = rets.mean(axis=1, skipna=True).fillna(0.0)
    idx_series = 100.0 * (1.0 + ew_ret).cumprod()
    first_valid = sub.notna().any(axis=1)
    idx_series = idx_series[first_valid]
    return idx_series


def zigzag_pivots(s: pd.Series, pct: float) -> List[Tuple[str, pd.Timestamp, float]]:
    s = s.dropna()
    if len(s) < 3:
        return []
    vals = s.values.astype(float)
    dates = s.index
    pivots: List[Tuple[str, pd.Timestamp, float]] = []
    min_i, min_v = 0, vals[0]
    max_i, max_v = 0, vals[0]
    state = 0
    for i in range(1, len(vals)):
        v = vals[i]
        if state == 0:
            if v < min_v:
                min_i, min_v = i, v
            if v > max_v:
                max_i, max_v = i, v
            up_min = (v / min_v - 1.0) >= pct if min_v > 0 else False
            dn_max = (v / max_v - 1.0) <= -pct if max_v > 0 else False
            if up_min and not dn_max:
                pivots.append(("T", dates[min_i], float(min_v)))
                state = 1
                max_i, max_v = i, v
            elif dn_max and not up_min:
                pivots.append(("P", dates[max_i], float(max_v)))
                state = -1
                min_i, min_v = i, v
            elif up_min and dn_max:
                if min_i < max_i:
                    pivots.append(("T", dates[min_i], float(min_v)))
                    state = 1
                    max_i, max_v = i, v
                else:
                    pivots.append(("P", dates[max_i], float(max_v)))
                    state = -1
                    min_i, min_v = i, v
        elif state == 1:
            if v > max_v:
                max_i, max_v = i, v
            elif max_v > 0 and v <= max_v * (1.0 - pct):
                pivots.append(("P", dates[max_i], float(max_v)))
                state = -1
                min_i, min_v = i, v
        else:
            if v < min_v:
                min_i, min_v = i, v
            elif min_v > 0 and v >= min_v * (1.0 + pct):
                pivots.append(("T", dates[min_i], float(min_v)))
                state = 1
                max_i, max_v = i, v
    return pivots


def centered_extrema_flags(s: pd.Series, half_win: int) -> Dict[pd.Timestamp, str]:
    s = s.dropna()
    vals = s.values.astype(float)
    dates = s.index
    out = {}
    for i in range(len(vals)):
        lo = max(0, i - half_win)
        hi = min(len(vals), i + half_win + 1)
        w = vals[lo:hi]
        is_p = vals[i] >= w.max() - 1e-12 and (i == 0 or vals[i] > vals[i - 1])
        is_t = vals[i] <= w.min() + 1e-12 and (i == 0 or vals[i] < vals[i - 1])
        if is_p and not is_t:
            out[dates[i]] = "P"
        elif is_t and not is_p:
            out[dates[i]] = "T"
    return out


def extract_major_comm_pivots(s: pd.Series, pct: float = 0.20, hw_major: int = 120, hw_mid: int = 60) -> List[dict]:
    s = s.dropna()
    zz = zigzag_pivots(s, pct)
    ext_major = centered_extrema_flags(s, hw_major)
    ext_mid = centered_extrema_flags(s, hw_mid)
    major = [p for p in zz if ext_major.get(p[1]) == p[0]]
    # Ensure strict alternation by inserting best opposite ZZ pivot (preferring L121) between same-type neighbors
    if not major:
        major = [p for p in zz if ext_mid.get(p[1]) == p[0]] or zz
    cleaned = []
    for p in major:
        if cleaned and cleaned[-1][0] == p[0]:
            prev_dt = cleaned[-1][1]
            cands = [q for q in zz if q[0] != p[0] and prev_dt < q[1] < p[1]]
            mid_cands = [q for q in cands if ext_mid.get(q[1]) == q[0]]
            pool = mid_cands or cands
            if pool:
                best_opp = min(pool, key=lambda x: x[2]) if p[0] == "P" else max(pool, key=lambda x: x[2])
                cleaned.append(best_opp)
            else:
                if (p[0] == "P" and p[2] > cleaned[-1][2]) or (p[0] == "T" and p[2] < cleaned[-1][2]):
                    cleaned[-1] = p
                continue
        cleaned.append(p)
    res = []
    for idx, (pt, dt, val) in enumerate(cleaned):
        swing_pct = None
        if idx > 0 and cleaned[idx - 1][2] > 0:
            swing_pct = round((val / cleaned[idx - 1][2] - 1.0) * 100.0, 2)
        res.append({
            "type": "trough" if pt == "T" else "peak",
            "pt": pt,
            "date": dt,
            "val": round(val, 4),
            "swing_pct": swing_pct,
            "in_l241": ext_major.get(dt) == pt,
            "in_l121": ext_mid.get(dt) == pt,
        })
    return res


def extract_stock_pivots(s: pd.Series, pct: float = 0.25, hw_major: int = 120, hw_mid: int = 60) -> List[dict]:
    s = s.dropna()
    zz = zigzag_pivots(s, pct)
    ext_major = centered_extrema_flags(s, hw_major)
    ext_mid = centered_extrema_flags(s, hw_mid)
    seen = {}
    for pt, dt, val in zz:
        if ext_major.get(dt) == pt:
            tier, pen = "ZZ+L241", 0.0
        elif ext_mid.get(dt) == pt:
            tier, pen = "ZZ+L121", 15.0
        else:
            tier, pen = "ZZ_only", 40.0
        seen[(pt, dt)] = {"pt": pt, "date": dt, "val": float(val), "tier": tier, "pen": pen}
    for dt, pt in ext_major.items():
        if (pt, dt) not in seen:
            seen[(pt, dt)] = {"pt": pt, "date": dt, "val": float(s.loc[dt]), "tier": "L241_only", "pen": 80.0}
    raw_pivs = sorted(seen.values(), key=lambda x: x["date"])
    # Deduplicate same-type near-duplicate pivots within 20 calendar days (keep stronger tier / more extreme val)
    deduped = []
    for p in raw_pivs:
        dup_idx = None
        for idx in range(len(deduped) - 1, -1, -1):
            q = deduped[idx]
            if q["pt"] == p["pt"] and (p["date"] - q["date"]).days <= 20:
                dup_idx = idx
                break
        if dup_idx is not None:
            q = deduped[dup_idx]
            p_better = (p["pen"] < q["pen"]) or (
                p["pen"] == q["pen"] and ((p["pt"] == "P" and p["val"] > q["val"]) or (p["pt"] == "T" and p["val"] < q["val"]))
            )
            if p_better:
                deduped[dup_idx] = p
        else:
            deduped.append(p)
    return deduped


def _p_value_eff(r: float, n_eff: float) -> Optional[float]:
    if not np.isfinite(r) or n_eff <= 2.5 or abs(r) >= 0.999999:
        return 0.0 if abs(r) >= 0.999999 else None
    df = max(n_eff - 2.0, 1.0)
    t_val = abs(r) * math.sqrt(df / (1.0 - r * r))
    return round(float(2.0 * student_t.sf(t_val, df)), 4)


def match_turning_points(
    comm_pivs: List[dict],
    stock_pivs: List[dict],
    cal: pd.DatetimeIndex,
    max_lag: int = 180,
    monthly_comm_eom: bool = False,
) -> dict:
    cal_pos = {d: i for i, d in enumerate(cal)}

    def to_pos(dt: pd.Timestamp, eom_shift: bool = False) -> int:
        if eom_shift:
            target = dt + pd.offsets.MonthEnd(0)
            idx = cal.searchsorted(target, side="right") - 1
            return int(np.clip(idx, 0, len(cal) - 1))
        if dt in cal_pos:
            return cal_pos[dt]
        idx = cal.searchsorted(dt, side="left")
        return int(np.clip(idx, 0, len(cal) - 1))

    # Precompute stock prior opposite pivot value for wave amplitude
    stock_swing_map = {}
    for k, sp in enumerate(stock_pivs):
        sw = None
        for j in range(k - 1, -1, -1):
            if stock_pivs[j]["pt"] != sp["pt"] and stock_pivs[j]["val"] > 0:
                sw = round((sp["val"] / stock_pivs[j]["val"] - 1.0) * 100.0, 2)
                break
        stock_swing_map[(sp["pt"], sp["date"])] = sw

    waves = []
    matched_stock_keys = set()
    for ptype in ("T", "P"):
        c_sub = [c for c in comm_pivs if c["pt"] == ptype]
        s_sub = [s for s in stock_pivs if s["pt"] == ptype]
        if not c_sub or not s_sub:
            continue
        cost = np.full((len(c_sub), len(s_sub)), 1e6, dtype=float)
        for i, cp in enumerate(c_sub):
            cpos = to_pos(cp["date"], eom_shift=monthly_comm_eom)
            for j, sp in enumerate(s_sub):
                spos = to_pos(sp["date"], eom_shift=False)
                diff = abs(cpos - spos)
                if diff <= max_lag:
                    cost[i, j] = diff + sp["pen"]
        row_ind, col_ind = linear_sum_assignment(cost)
        for i, j in zip(row_ind, col_ind):
            if cost[i, j] >= 1e5:
                continue
            cp = c_sub[i]
            sp = s_sub[j]
            cpos = to_pos(cp["date"], eom_shift=monthly_comm_eom)
            spos = to_pos(sp["date"], eom_shift=False)
            lead = int(cpos - spos)
            matched_stock_keys.add((sp["pt"], sp["date"]))
            waves.append({
                "type": cp["type"],
                "comm_date": str(cp["date"])[:10],
                "comm_cal_date": str(cal[cpos])[:10],
                "comm_val": cp["val"],
                "comm_swing_pct": cp["swing_pct"],
                "stock_date": str(sp["date"])[:10],
                "stock_val": round(sp["val"], 4),
                "stock_swing_pct": stock_swing_map.get((sp["pt"], sp["date"])),
                "stock_tier": sp["tier"],
                "lead_days": lead,
            })
    waves.sort(key=lambda x: x["comm_date"])

    def _agg(sub_type: str) -> dict:
        tot = sum(1 for c in comm_pivs if c["type"] == sub_type)
        sub = [w for w in waves if w["type"] == sub_type]
        if not sub:
            return {"n_comm": tot, "n_matched": 0, "lead_median": None, "lead_mean": None, "lead_min": None, "lead_max": None, "stock_led_pct": None}
        lds = [w["lead_days"] for w in sub]
        return {
            "n_comm": tot,
            "n_matched": len(sub),
            "lead_median": round(float(np.median(lds)), 1),
            "lead_mean": round(float(np.mean(lds)), 1),
            "lead_min": int(min(lds)),
            "lead_max": int(max(lds)),
            "stock_led_pct": round(sum(1 for d in lds if d > 0) / len(lds) * 100.0, 1),
        }

    return {
        "n_comm_major_pivots": len(comm_pivs),
        "troughs_summary": _agg("trough"),
        "peaks_summary": _agg("peak"),
        "all_summary": {
            "n_matched": len(waves),
            "lead_median": round(float(np.median([w["lead_days"] for w in waves])), 1) if waves else None,
            "lead_mean": round(float(np.mean([w["lead_days"] for w in waves])), 1) if waves else None,
        },
        "waves": waves,
    }


def scan_xcorr(stock_s: pd.Series, comm_s: pd.Series, cal: pd.DatetimeIndex, max_lag: int = 180) -> dict:
    st = stock_s.reindex(stock_s.index.union(cal)).sort_index().ffill().reindex(cal)
    cm = comm_s.reindex(comm_s.index.union(cal)).sort_index().ffill().reindex(cal)
    df = pd.DataFrame({"st": st, "cm": cm}).dropna()
    out = {}
    curves = {}
    for win in (60, 20):
        rs = df["st"].pct_change(win, fill_method=None)
        rc = df["cm"].pct_change(win, fill_method=None)
        rows = []
        for k in range(-max_lag, max_lag + 1):
            sub = pd.DataFrame({"s": rs, "c": rc.shift(-k)}).dropna()
            n = len(sub)
            r = float(sub["s"].corr(sub["c"])) if n > 25 else np.nan
            rows.append((k, r, n))
        rdf = pd.DataFrame(rows, columns=["k", "r", "n"]).dropna()

        def _summarize(sub_df: pd.DataFrame) -> dict:
            b = sub_df.loc[sub_df["r"].idxmax()]
            n_val = int(b["n"])
            n_eff = round(n_val / float(win), 2)
            r_val = round(float(b["r"]), 4)
            pos = sub_df[sub_df["k"] > 0]
            neg = sub_df[sub_df["k"] < 0]
            bp = pos.loc[pos["r"].idxmax()] if len(pos) else None
            bn = neg.loc[neg["r"].idxmax()] if len(neg) else None
            r0_s = sub_df.loc[sub_df["k"] == 0, "r"]
            return {
                "peak_lag": int(b["k"]),
                "peak_corr": r_val,
                "N": n_val,
                "n_eff": n_eff,
                "p_eff": _p_value_eff(r_val, n_eff),
                "corr_lag0": round(float(r0_s.iloc[0]), 4) if len(r0_s) else None,
                "pos_peak_lag": int(bp["k"]) if bp is not None else None,
                "pos_peak_corr": round(float(bp["r"]), 4) if bp is not None else None,
                "neg_peak_lag": int(bn["k"]) if bn is not None else None,
                "neg_peak_corr": round(float(bn["r"]), 4) if bn is not None else None,
            }

        key = f"ret_{win}d"
        out[key] = _summarize(rdf)
        if len(df) < 1000 and max_lag >= 180:
            out[f"{key}_within_120"] = _summarize(rdf[rdf["k"].abs() <= 120])
        sampled = rdf[rdf["k"] % 5 == 0]
        curves[key] = {
            "lags": [int(x) for x in sampled["k"].tolist()],
            "corrs": [round(float(x), 4) for x in sampled["r"].tolist()],
        }
    out["curves_5d"] = curves
    out["n_aligned_days"] = int(len(df))
    return out


def scan_monthly_xcorr(stock_s: pd.Series, comm_monthly: pd.Series, start_dt: str, end_dt: str) -> dict:
    st_m = stock_s.loc[start_dt:end_dt].resample("MS").last()
    cm_m = comm_monthly.loc[start_dt:end_dt]
    df = pd.DataFrame({"st": st_m, "cm": cm_m}).dropna()
    out = {}
    for win in (3, 1):
        rs = df["st"].pct_change(win, fill_method=None)
        rc = df["cm"].pct_change(win, fill_method=None)
        pts = []
        for km in range(-6, 7):
            sub = pd.DataFrame({"s": rs, "c": rc.shift(-km)}).dropna()
            r = float(sub["s"].corr(sub["c"])) if len(sub) >= 12 else np.nan
            pts.append({"lag_months": km, "corr": round(r, 4) if np.isfinite(r) else None, "N": int(len(sub))})
        valid = [p for p in pts if p["corr"] is not None]
        best = max(valid, key=lambda x: x["corr"]) if valid else None
        out[f"ret_{win}m"] = {"peak": best, "curve": pts}
    return out


def _build_signals(
    sc: pd.Series,
    cm: pd.Series,
    strat: str,
    q_win: int = 756,
    q_min: int = 120,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    c_rank = cm.rolling(q_win, min_periods=q_min).rank(pct=True)
    c_max252 = cm.rolling(252, min_periods=min(60, q_min)).max()
    c_dd252 = cm / c_max252 - 1.0
    c_ma60 = cm.rolling(60, min_periods=60).mean()
    c_ret20 = cm.pct_change(20, fill_method=None)
    c_ret60 = cm.pct_change(60, fill_method=None)
    c_min252 = cm.rolling(252, min_periods=min(60, q_min)).min()

    s_ma60 = sc.rolling(60, min_periods=60).mean()
    s_ma20 = sc.rolling(20, min_periods=20).mean()
    s_ret20 = sc.pct_change(20, fill_method=None)
    below_ma60_3d = (sc < s_ma60).rolling(3).sum() == 3

    if strat == "A":
        entry_sig = ((c_rank < 0.25) | (c_dd252 <= -0.25)) & (sc > s_ma60) & (s_ret20 > c_ret20)
        exit_sig = ((c_rank > 0.85) & (sc < s_ma20)) | below_ma60_3d
    elif strat == "A2":
        entry_sig = c_rank < 0.20
        exit_sig = c_rank > 0.80
    elif strat == "B":
        entry_sig = (cm > c_ma60) & (c_ret60 > 0.05)
        exit_sig = cm < c_ma60
    elif strat == "C":
        false_s = pd.Series(False, index=sc.index)
        return false_s, false_s, c_min252
    else:
        raise ValueError(f"Unknown strategy: {strat}")
    return entry_sig.fillna(False), exit_sig.fillna(False), c_min252


def simulate_single_asset(
    ticker: str,
    s_close_raw: pd.Series,
    s_open_raw: pd.Series,
    comm_s: pd.Series,
    cal_full: pd.DatetimeIndex,
    eval_start: str,
    eval_end: str,
    strat: str,
    q_win: int = 756,
    q_min: int = 120,
    fee: float = 0.0015,
) -> dict:
    sc_raw = s_close_raw.reindex(cal_full)
    so_raw = s_open_raw.reindex(cal_full)
    sc = sc_raw.ffill()
    cm = comm_s.reindex(comm_s.index.union(cal_full)).sort_index().ffill().reindex(cal_full)

    entry_sig, exit_sig, c_min252 = _build_signals(sc, cm, strat, q_win=q_win, q_min=q_min)

    eval_mask = (cal_full >= pd.Timestamp(eval_start)) & (cal_full <= pd.Timestamp(eval_end))
    eval_dates = cal_full[eval_mask]
    start_pos = cal_full.get_loc(eval_dates[0])
    end_pos = cal_full.get_loc(eval_dates[-1])

    daily_ret = pd.Series(0.0, index=eval_dates)
    active = pd.Series(0.0, index=eval_dates)
    trades = []

    if strat == "C":
        # Buy & hold from first tradable open in eval window
        entered = False
        for i in range(start_pos, end_pos + 1):
            dt = cal_full[i]
            if not entered:
                op, cl = so_raw.iloc[i], sc_raw.iloc[i]
                if pd.notna(op) and pd.notna(cl) and op > 0:
                    daily_ret.loc[dt] = (1.0 - fee) * (float(cl) / float(op)) - 1.0
                    active.loc[dt] = 1.0
                    entered = True
            else:
                if pd.notna(sc_raw.iloc[i]) and pd.notna(sc.iloc[i - 1]):
                    daily_ret.loc[dt] = float(sc_raw.iloc[i]) / float(sc.iloc[i - 1]) - 1.0
                active.loc[dt] = 1.0
        return {"daily_ret": daily_ret, "active": active, "trades": trades}

    pos = 0
    pending = None
    entry_sig_dt = None
    entry_dt = None
    entry_open = None
    hold_days = 0
    exit_sig_dt = None

    for i in range(start_pos, end_pos + 1):
        dt = cal_full[i]
        executed_exit_today = False
        if i > start_pos and pending is not None:
            op, cl = so_raw.iloc[i], sc_raw.iloc[i]
            if pd.notna(op) and pd.notna(cl) and op > 0:
                if pending == "BUY" and pos == 0:
                    pos = 1
                    entry_dt = dt
                    entry_open = float(op)
                    hold_days = 0
                    daily_ret.loc[dt] = (1.0 - fee) * (float(cl) / float(op)) - 1.0
                    active.loc[dt] = 1.0
                    pending = None
                elif pending == "SELL" and pos == 1:
                    prev_cl = float(sc.iloc[i - 1])
                    daily_ret.loc[dt] = (float(op) / prev_cl) * (1.0 - fee) - 1.0
                    active.loc[dt] = 0.0
                    net_tr = (float(op) / entry_open) * ((1.0 - fee) ** 2) - 1.0
                    trades.append({
                        "ticker": ticker,
                        "name": NAMES.get(ticker, ticker),
                        "strategy": strat,
                        "entry_signal_date": str(entry_sig_dt)[:10],
                        "entry_date": str(entry_dt)[:10],
                        "entry_open": round(entry_open, 4),
                        "exit_signal_date": str(exit_sig_dt)[:10],
                        "exit_date": str(dt)[:10],
                        "exit_open": round(float(op), 4),
                        "hold_days": int(hold_days),
                        "net_ret_pct": round(net_tr * 100.0, 2),
                        "status": "closed",
                    })
                    pos = 0
                    pending = None
                    entry_dt = None
                    entry_open = None
                    executed_exit_today = True
            else:
                # Stock halted on open
                if pending == "BUY":
                    pending = None
                elif pending == "SELL":
                    active.loc[dt] = 1.0
                    hold_days += 1
                    continue
        if pos == 1 and (i == start_pos or not (daily_ret.loc[dt] != 0.0 or active.loc[dt] > 0)):
            # Normal holding day (did not just enter on today's open)
            if dt != entry_dt:
                if pd.notna(sc_raw.iloc[i]) and pd.notna(sc.iloc[i - 1]):
                    daily_ret.loc[dt] = float(sc_raw.iloc[i]) / float(sc.iloc[i - 1]) - 1.0
                active.loc[dt] = 1.0
                hold_days += 1

        if i < end_pos:
            if pos == 0 and bool(entry_sig.iloc[i]):
                pending = "BUY"
                entry_sig_dt = dt
            elif pos == 1:
                ex = bool(exit_sig.iloc[i])
                if strat == "A2" and hold_days >= 252:
                    if pd.notna(cm.iloc[i]) and pd.notna(c_min252.iloc[i]) and float(cm.iloc[i]) <= float(c_min252.iloc[i]) + 1e-12:
                        ex = True
                if ex:
                    pending = "SELL"
                    exit_sig_dt = dt
        elif executed_exit_today:
            pass

    if pos == 1 and entry_open is not None:
        last_cl = float(sc.iloc[end_pos])
        mtm = (last_cl / entry_open) * (1.0 - fee) - 1.0
        trades.append({
            "ticker": ticker,
            "name": NAMES.get(ticker, ticker),
            "strategy": strat,
            "entry_signal_date": str(entry_sig_dt)[:10],
            "entry_date": str(entry_dt)[:10],
            "entry_open": round(entry_open, 4),
            "exit_signal_date": None,
            "exit_date": str(cal_full[end_pos])[:10],
            "exit_open": round(last_cl, 4),
            "hold_days": int(hold_days),
            "net_ret_pct": round(mtm * 100.0, 2),
            "status": "open",
        })

    return {"daily_ret": daily_ret, "active": active, "trades": trades}


def simulate_ew_basket(
    basket_name: str,
    tickers: List[str],
    a_close: pd.DataFrame,
    a_open: pd.DataFrame,
    comm_s: pd.Series,
    cal_full: pd.DatetimeIndex,
    eval_start: str,
    eval_end: str,
    strat: str,
    q_win: int = 756,
    q_min: int = 120,
    fee: float = 0.0015,
) -> dict:
    # Build daily-rebalanced EW signal price index strictly from <= t closes
    sub_c_raw = a_close[tickers].reindex(cal_full)
    sub_o_raw = a_open[tickers].reindex(cal_full)
    sub_c = sub_c_raw.ffill()
    ew_ret_idx = sub_c.pct_change(fill_method=None).mean(axis=1, skipna=True).fillna(0.0)
    eq_close = 100.0 * (1.0 + ew_ret_idx).cumprod()
    cm = comm_s.reindex(comm_s.index.union(cal_full)).sort_index().ffill().reindex(cal_full)

    entry_sig, exit_sig, c_min252 = _build_signals(eq_close, cm, strat, q_win=q_win, q_min=q_min)

    eval_mask = (cal_full >= pd.Timestamp(eval_start)) & (cal_full <= pd.Timestamp(eval_end))
    eval_dates = cal_full[eval_mask]
    start_pos = cal_full.get_loc(eval_dates[0])
    end_pos = cal_full.get_loc(eval_dates[-1])

    daily_ret = pd.Series(0.0, index=eval_dates)
    active = pd.Series(0.0, index=eval_dates)
    trades = []

    if strat == "C":
        for i in range(start_pos, end_pos + 1):
            dt = cal_full[i]
            if i == start_pos:
                legs = []
                for tk in tickers:
                    op, cl = sub_o_raw[tk].iloc[i], sub_c_raw[tk].iloc[i]
                    if pd.notna(op) and pd.notna(cl) and op > 0:
                        legs.append((1.0 - fee) * (float(cl) / float(op)) - 1.0)
                daily_ret.loc[dt] = float(np.mean(legs)) if legs else 0.0
            else:
                legs = []
                for tk in tickers:
                    c0, c1 = sub_c[tk].iloc[i - 1], sub_c[tk].iloc[i]
                    if pd.notna(c0) and pd.notna(c1) and c0 > 0:
                        legs.append(float(c1) / float(c0) - 1.0)
                daily_ret.loc[dt] = float(np.mean(legs)) if legs else 0.0
            active.loc[dt] = 1.0
        return {"daily_ret": daily_ret, "active": active, "trades": trades}

    pos = 0
    pending = None
    entry_sig_dt = None
    entry_dt = None
    exit_sig_dt = None
    hold_days = 0
    # Track leg weights & values (initial sum = 1.0) inside each trade
    leg_vals: Dict[str, float] = {}
    halted_exit_legs: Dict[str, float] = {}

    for i in range(start_pos, end_pos + 1):
        dt = cal_full[i]
        day_pnl = 0.0
        prev_total = sum(leg_vals.values()) + sum(halted_exit_legs.values())

        # First settle any previously halted exiting legs if now tradable
        if halted_exit_legs:
            still_halted = {}
            for tk, val in halted_exit_legs.items():
                op = sub_o_raw[tk].iloc[i]
                prev_cl = sub_c[tk].iloc[i - 1]
                if pd.notna(op) and pd.notna(prev_cl) and op > 0:
                    day_pnl += val * ((float(op) / float(prev_cl)) * (1.0 - fee) - 1.0)
                else:
                    still_halted[tk] = val
            halted_exit_legs = still_halted

        if i > start_pos and pending == "BUY" and pos == 0:
            tradable = [tk for tk in tickers if pd.notna(sub_o_raw[tk].iloc[i]) and pd.notna(sub_c_raw[tk].iloc[i]) and sub_o_raw[tk].iloc[i] > 0]
            if tradable:
                w = 1.0 / len(tradable)
                leg_vals = {}
                for tk in tradable:
                    op, cl = float(sub_o_raw[tk].iloc[i]), float(sub_c_raw[tk].iloc[i])
                    new_v = w * (1.0 - fee) * (cl / op)
                    day_pnl += new_v - w
                    leg_vals[tk] = new_v
                daily_ret.loc[dt] = day_pnl
                active.loc[dt] = 1.0
                pos = 1
                entry_dt = dt
                hold_days = 0
            pending = None
        elif i > start_pos and pending == "SELL" and pos == 1:
            new_halted = {}
            exit_val_sum = 0.0
            for tk, val in leg_vals.items():
                op = sub_o_raw[tk].iloc[i]
                prev_cl = sub_c[tk].iloc[i - 1]
                if pd.notna(op) and pd.notna(prev_cl) and op > 0:
                    exit_v = val * (float(op) / float(prev_cl)) * (1.0 - fee)
                    day_pnl += exit_v - val
                    exit_val_sum += exit_v
                else:
                    new_halted[tk] = val
                    exit_val_sum += val
            halted_exit_legs.update(new_halted)
            daily_ret.loc[dt] = day_pnl / prev_total if prev_total > 0 else 0.0
            active.loc[dt] = 0.0 if not halted_exit_legs else 0.5
            trades.append({
                "ticker": basket_name,
                "name": NAMES.get(basket_name, basket_name),
                "strategy": strat,
                "entry_signal_date": str(entry_sig_dt)[:10],
                "entry_date": str(entry_dt)[:10],
                "entry_open": 1.0,
                "exit_signal_date": str(exit_sig_dt)[:10],
                "exit_date": str(dt)[:10],
                "exit_open": round(exit_val_sum, 4),
                "hold_days": int(hold_days),
                "net_ret_pct": round((exit_val_sum - 1.0) * 100.0, 2),
                "status": "closed",
            })
            leg_vals = {}
            pos = 0
            pending = None
        else:
            if pos == 1 and leg_vals:
                new_legs = {}
                for tk, val in leg_vals.items():
                    c0, c1 = sub_c[tk].iloc[i - 1], sub_c[tk].iloc[i]
                    if pd.notna(sub_c_raw[tk].iloc[i]) and pd.notna(c0) and c0 > 0:
                        nv = val * (float(c1) / float(c0))
                    else:
                        nv = val
                    day_pnl += nv - val
                    new_legs[tk] = nv
                leg_vals = new_legs
                daily_ret.loc[dt] = day_pnl / prev_total if prev_total > 0 else 0.0
                active.loc[dt] = 1.0
                hold_days += 1
            elif halted_exit_legs:
                daily_ret.loc[dt] = day_pnl / prev_total if prev_total > 0 else 0.0

        if i < end_pos:
            if pos == 0 and bool(entry_sig.iloc[i]):
                pending = "BUY"
                entry_sig_dt = dt
            elif pos == 1:
                ex = bool(exit_sig.iloc[i])
                if strat == "A2" and hold_days >= 252:
                    if pd.notna(cm.iloc[i]) and pd.notna(c_min252.iloc[i]) and float(cm.iloc[i]) <= float(c_min252.iloc[i]) + 1e-12:
                        ex = True
                if ex:
                    pending = "SELL"
                    exit_sig_dt = dt

    if pos == 1 and leg_vals:
        cur_val = sum(leg_vals.values()) * (1.0 - fee)
        trades.append({
            "ticker": basket_name,
            "name": NAMES.get(basket_name, basket_name),
            "strategy": strat,
            "entry_signal_date": str(entry_sig_dt)[:10],
            "entry_date": str(entry_dt)[:10],
            "entry_open": 1.0,
            "exit_signal_date": None,
            "exit_date": str(cal_full[end_pos])[:10],
            "exit_open": round(cur_val, 4),
            "hold_days": int(hold_days),
            "net_ret_pct": round((cur_val - 1.0) * 100.0, 2),
            "status": "open",
        })

    return {"daily_ret": daily_ret, "active": active, "trades": trades}


def summarize_d15_windows(
    strat_res: dict,
    bh_res: dict,
    hs300_ret: pd.Series,
    eval_start: str,
    eval_end: str,
) -> dict:
    s_ret = strat_res["daily_ret"]
    act = strat_res["active"]
    b_ret = bh_res["daily_ret"]
    trades = strat_res["trades"]

    windows = [("full", eval_start, eval_end)]
    if pd.Timestamp(eval_start) <= pd.Timestamp("2021-11-22") and pd.Timestamp(eval_end) >= pd.Timestamp("2026-11-01"):
        windows.append(("last_5y", "2021-11-22", eval_end))
    if pd.Timestamp(eval_start) <= pd.Timestamp("2023-11-21") and pd.Timestamp(eval_end) >= pd.Timestamp("2026-11-01"):
        windows.append(("last_3y", "2023-11-21", eval_end))

    out = {}
    for wname, ws, we in windows:
        mask = (s_ret.index >= pd.Timestamp(ws)) & (s_ret.index <= pd.Timestamp(we))
        sub_s = s_ret.loc[mask]
        sub_a = act.loc[mask]
        sub_b = b_ret.loc[mask]
        sub_hs = hs300_ret.reindex(sub_s.index).fillna(0.0)
        if len(sub_s) < 20:
            continue
        m_hs = compute_period_metrics(sub_s, sub_hs, sub_a)
        m_bh = compute_period_metrics(sub_s, sub_b, sub_a)
        tot_ret = (float((1.0 + sub_s).prod()) - 1.0) * 100.0

        closed_in_win = [t for t in trades if t["status"] == "closed" and ws <= t["exit_date"] <= we]
        open_in_win = [t for t in trades if t["status"] == "open" and t["entry_date"] <= we]
        wins = [t["net_ret_pct"] for t in closed_in_win if t["net_ret_pct"] > 0]
        losses = [t["net_ret_pct"] for t in closed_in_win if t["net_ret_pct"] <= 0]
        win_rate = round(len(wins) / len(closed_in_win) * 100.0, 1) if closed_in_win else None
        if wins and losses and abs(np.mean(losses)) > 1e-9:
            pl_ratio = round(float(np.mean(wins) / abs(np.mean(losses))), 2)
        else:
            pl_ratio = None

        out[wname] = {
            "start": str(sub_s.index[0])[:10],
            "end": str(sub_s.index[-1])[:10],
            "n_days": m_hs["n_days"],
            "total_ret_pct": round(tot_ret, 2),
            "cagr_pct": m_hs["ann_ret"],
            "mdd_pct": m_hs["mdd"],
            "sharpe": m_hs["sharpe"],
            "calmar": m_hs["calmar"],
            "ir_vs_hs300": m_hs["ir"],
            "trades_n": len(closed_in_win),
            "open_trades_n": len(open_in_win),
            "win_rate_pct": win_rate,
            "pl_ratio": pl_ratio,
            "exposure_pct": m_hs["exposure_pct"],
            "hs300_cagr_pct": m_hs["bench_ann_ret"],
            "bh_cagr_pct": m_bh["bench_ann_ret"],
            "excess_vs_hs300_ann_pct": m_hs["excess_ann"],
            "excess_vs_bh_ann_pct": m_bh["excess_ann"],
            "tei": m_hs["tei"],
            "tei_vs_bh": m_bh["tei"],
            "tei_pillars": m_hs["tei_pillars"],
        }
    return out


def run_track(
    track_name: str,
    comm_series: pd.Series,
    stock_defs: List[Tuple[str, Optional[List[str]]]],
    data: dict,
    eval_start: str,
    eval_end: str,
    warmup_start: str = "2015-01-05",
    q_win: int = 756,
    q_min: int = 120,
    max_lag: int = 180,
    run_module3: bool = True,
    comm_monthly_raw: Optional[pd.Series] = None,
    us_assets: Optional[List[str]] = None,
) -> dict:
    hs300 = data["hs300"]
    cal_full = hs300.index[(hs300.index >= warmup_start) & (hs300.index <= eval_end)]
    cal_eval = hs300.index[(hs300.index >= eval_start) & (hs300.index <= eval_end)]
    hs300_ret = hs300.reindex(cal_full).ffill().pct_change(fill_method=None).reindex(cal_eval).fillna(0.0)

    a_close = data["a_close"]
    a_open = data["a_open"]
    us_close = data["us_close"]

    # Build aligned series dict for Module 1 & 2
    stock_series = {}
    for tk, constituents in stock_defs:
        if constituents is None:
            if tk in a_close.columns:
                stock_series[tk] = a_close[tk].reindex(cal_eval).ffill()
            elif tk in us_close.columns:
                stock_series[tk] = us_close[tk].reindex(us_close.index.union(cal_eval)).sort_index().ffill().reindex(cal_eval)
        else:
            df_src = us_close if all(c in us_close.columns for c in constituents) else a_close
            stock_series[tk] = build_ew_index(df_src, constituents, cal_eval)

    if us_assets:
        for uk in us_assets:
            if uk == "US_LI_EQ":
                stock_series[uk] = build_ew_index(us_close, ["ALB", "SQM"], cal_eval)
            else:
                stock_series[uk] = us_close[uk].reindex(us_close.index.union(cal_eval)).sort_index().ffill().reindex(cal_eval)

    # Module 1: Turning points
    if comm_monthly_raw is not None:
        cm_sub = comm_monthly_raw.loc[eval_start:eval_end]
        comm_pivs = extract_major_comm_pivots(cm_sub, pct=0.20, hw_major=6, hw_mid=3)
        m1_eom = True
    else:
        cm_eval = comm_series.reindex(comm_series.index.union(cal_eval)).sort_index().ffill().reindex(cal_eval).dropna()
        comm_pivs = extract_major_comm_pivots(cm_eval, pct=0.20, hw_major=120, hw_mid=60)
        m1_eom = False

    module1 = {}
    module2 = {}
    for tk, s_ser in stock_series.items():
        s_pivs = extract_stock_pivots(s_ser, pct=0.25, hw_major=120, hw_mid=60)
        module1[tk] = match_turning_points(comm_pivs, s_pivs, cal_eval, max_lag=max_lag, monthly_comm_eom=m1_eom)
        module2[tk] = scan_xcorr(s_ser, comm_series, cal_eval, max_lag=max_lag)
        if comm_monthly_raw is not None:
            module2[tk]["monthly_xcorr"] = scan_monthly_xcorr(s_ser, comm_monthly_raw, eval_start, eval_end)

    module3 = {}
    all_trades_by_strat = {"A": [], "A2": [], "B": []}
    if run_module3:
        single_res_cache = {}
        for tk, constituents in stock_defs:
            if constituents is None:
                if tk not in a_close.columns:
                    continue
                bh = simulate_single_asset(tk, a_close[tk], a_open[tk], comm_series, cal_full, eval_start, eval_end, "C", q_win, q_min)
                single_res_cache[tk] = {"C": bh}
                tk_res = {"name": NAMES.get(tk, tk), "C_bh": summarize_d15_windows(bh, bh, hs300_ret, eval_start, eval_end)}
                for st in ("A", "A2", "B"):
                    sr = simulate_single_asset(tk, a_close[tk], a_open[tk], comm_series, cal_full, eval_start, eval_end, st, q_win, q_min)
                    single_res_cache[tk][st] = sr
                    tk_res[st] = summarize_d15_windows(sr, bh, hs300_ret, eval_start, eval_end)
                    all_trades_by_strat[st].extend(sr["trades"])
                module3[tk] = tk_res

        # Now run EW baskets
        for tk, constituents in stock_defs:
            if constituents is None or not all(c in a_close.columns for c in constituents):
                continue
            bh = simulate_ew_basket(tk, constituents, a_close, a_open, comm_series, cal_full, eval_start, eval_end, "C", q_win, q_min)
            tk_res = {"name": NAMES.get(tk, tk), "constituents": constituents, "C_bh": summarize_d15_windows(bh, bh, hs300_ret, eval_start, eval_end)}
            for st in ("A", "A2", "B"):
                sr = simulate_ew_basket(tk, constituents, a_close, a_open, comm_series, cal_full, eval_start, eval_end, st, q_win, q_min)
                tk_res[st] = summarize_d15_windows(sr, bh, hs300_ret, eval_start, eval_end)
                all_trades_by_strat[st].extend(sr["trades"])
                # Also compute subaccount average sensitivity
                if all(c in single_res_cache and st in single_res_cache[c] for c in constituents):
                    sub_r = pd.concat([single_res_cache[c][st]["daily_ret"] for c in constituents], axis=1).mean(axis=1)
                    sub_a = pd.concat([single_res_cache[c][st]["active"] for c in constituents], axis=1).mean(axis=1)
                    sub_obj = {"daily_ret": sub_r, "active": sub_a, "trades": []}
                    tk_res[f"{st}_subaccounts_avg"] = summarize_d15_windows(sub_obj, bh, hs300_ret, eval_start, eval_end)
            module3[tk] = tk_res

    top5_extreme = {}
    for st in ("A", "B"):
        trs = sorted(all_trades_by_strat[st], key=lambda x: abs(x["net_ret_pct"]), reverse=True)
        top5_extreme[st] = trs[:5]

    return {
        "track": track_name,
        "eval_start": eval_start,
        "eval_end": eval_end,
        "q_win": q_win,
        "q_min": q_min,
        "comm_major_pivots": [
            {"type": p["type"], "date": str(p["date"])[:10], "val": p["val"], "swing_pct": p["swing_pct"]}
            for p in comm_pivs
        ],
        "module1_turning_points": module1,
        "module2_xcorr": module2,
        "module3_backtest": module3,
        "top5_extreme_trades": top5_extreme,
    }


def main():
    data = load_all_data()
    cn_fut = data["cn_fut"]
    hog_w = data["hog_weekly"]
    nc_m = data["nc_monthly"]

    # Pit-aligned daily hog spot & conservative +5d lag check
    hog_lag5 = hog_w.copy()
    hog_lag5.index = hog_lag5.index + pd.Timedelta(days=7)

    # Pit-aligned Newcastle coal (+1 month shift: Sept avg visible Oct 1)
    nc_pit = nc_m.copy()
    nc_pit.index = nc_pit.index + pd.offsets.MonthBegin(1)

    results = {
        "meta": {
            "as_of_date": "2026-11-20",
            "fee_round_trip_pct": 0.30,
            "execution": "t+1_open",
            "zero_yfinance": True,
            "zero_lookahead_notes": [
                "000792.SZ excluded from 2016-2022 due to 2021-08-10 +306% bankruptcy resumption jump; clean from 2023-07-21.",
                "hog_spot_weekly deduplicated and forward-filled strictly PIT to trading calendar (+7d lag sensitivity included).",
                "newcastle_coal_monthly lagged +1 month for daily PIT visibility in Module 2/3.",
            ],
        },
        "hog": {},
        "lithium": {},
        "coal": {},
    }

    # 1. Hog
    results["hog"]["spot_10y"] = run_track(
        "hog_spot_10y", hog_w,
        [("HOG_EQ", ["002714.SZ", "300498.SZ"]), ("002714.SZ", None), ("300498.SZ", None)],
        data, "2016-01-04", "2026-11-20", "2015-01-05", q_win=756, q_min=120,
    )
    results["hog"]["spot_10y_lag7d_sens"] = run_track(
        "hog_spot_10y_lag7d_sens", hog_lag5,
        [("HOG_EQ", ["002714.SZ", "300498.SZ"]), ("002714.SZ", None), ("300498.SZ", None)],
        data, "2016-01-04", "2026-11-20", "2015-01-05", q_win=756, q_min=120,
    )
    results["hog"]["lh0_5y"] = run_track(
        "hog_lh0_5y", cn_fut["LH0"].dropna(),
        [("HOG_EQ", ["002714.SZ", "300498.SZ"]), ("002714.SZ", None), ("300498.SZ", None)],
        data, "2021-01-08", "2026-11-20", "2021-01-08", q_win=756, q_min=120,
    )

    # 2. Lithium
    results["lithium"]["lc0_live"] = run_track(
        "lithium_lc0_live", cn_fut["LC0"].dropna(),
        [
            ("LITHIUM_EQ_3", ["002460.SZ", "002466.SZ", "000792.SZ"]),
            ("LITHIUM_EQ_2", ["002460.SZ", "002466.SZ"]),
            ("002460.SZ", None), ("002466.SZ", None), ("000792.SZ", None),
        ],
        data, "2023-07-21", "2026-11-20", "2023-07-21", q_win=756, q_min=60, max_lag=180,
        us_assets=["ALB", "SQM", "US_LI_EQ"],
    )
    results["lithium"]["lc0_live_roll252_sens"] = run_track(
        "lithium_lc0_live_roll252_sens", cn_fut["LC0"].dropna(),
        [
            ("LITHIUM_EQ_3", ["002460.SZ", "002466.SZ", "000792.SZ"]),
            ("002460.SZ", None), ("002466.SZ", None), ("000792.SZ", None),
        ],
        data, "2023-07-21", "2026-11-20", "2023-07-21", q_win=252, q_min=60, max_lag=180,
    )
    # 10Y CN vs US Lithium Equity cross-market lead-lag (2016-01 ~ 2026-11)
    us_li_eq = build_ew_index(data["us_close"], ["ALB", "SQM"], data["hs300"].loc["2015-01-05":"2026-11-20"].index)
    results["lithium"]["cross_mkt_10y_vs_alb"] = run_track(
        "lithium_10y_cn_vs_alb", data["us_close"]["ALB"].dropna(),
        [("LITHIUM_EQ_2", ["002460.SZ", "002466.SZ"]), ("002460.SZ", None), ("002466.SZ", None)],
        data, "2016-01-04", "2026-11-20", "2015-01-05", run_module3=False,
    )
    results["lithium"]["cross_mkt_10y_vs_sqm"] = run_track(
        "lithium_10y_cn_vs_sqm", data["us_close"]["SQM"].dropna(),
        [("LITHIUM_EQ_2", ["002460.SZ", "002466.SZ"]), ("002460.SZ", None), ("002466.SZ", None)],
        data, "2016-01-04", "2026-11-20", "2015-01-05", run_module3=False,
    )
    results["lithium"]["cross_mkt_10y_vs_us_eq"] = run_track(
        "lithium_10y_cn_vs_us_eq", us_li_eq,
        [("LITHIUM_EQ_2", ["002460.SZ", "002466.SZ"]), ("002460.SZ", None), ("002466.SZ", None)],
        data, "2016-01-04", "2026-11-20", "2015-01-05", run_module3=False,
    )

    # 3. Coal
    coal_stocks = [
        ("COAL_EQ", ["000983.SZ", "601699.SH", "601088.SH"]),
        ("COAL_COKING_EQ", ["000983.SZ", "601699.SH"]),
        ("000983.SZ", None), ("601699.SH", None), ("601088.SH", None),
    ]
    results["coal"]["jm0_10y"] = run_track(
        "coal_jm0_10y", cn_fut["JM0"].dropna(), coal_stocks,
        data, "2016-01-04", "2026-11-20", "2015-01-05", q_win=756, q_min=120,
    )
    results["coal"]["j0_10y"] = run_track(
        "coal_j0_10y", cn_fut["J0"].dropna(), coal_stocks,
        data, "2016-01-04", "2026-11-20", "2015-01-05", q_win=756, q_min=120,
    )
    results["coal"]["zc0_16_22"] = run_track(
        "coal_zc0_16_22", cn_fut["ZC0"].dropna(), [("601088.SH", None)],
        data, "2016-01-04", "2022-12-30", "2015-05-26", q_win=756, q_min=120,
    )
    results["coal"]["newcastle_16_26"] = run_track(
        "coal_newcastle_16_26", nc_pit, [("601088.SH", None)],
        data, "2016-01-04", "2026-11-20", "2015-01-05", q_win=756, q_min=120,
        comm_monthly_raw=nc_m,
    )

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"SAVED: {OUT_JSON} ({OUT_JSON.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

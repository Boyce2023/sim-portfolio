#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RD028 Step 2: Multi-Process 5-10Y Strictly PIT 3-Ring Backtests & Lead/Lag Analysis.
- Zero lookahead: causal rolling 10Y (2520d) & 5Y (1260d) percentiles at close[t].
- Execution: T+1 open buy, 0.30% (30bps) round-trip cost, excludes T+1 open one-word limit-up (yizi).
- Limit-down / blown boards remain in denominator; exit postpones if suspended or one-word limit-down.
- De-clustered 60-trading-day independent events across T+20 / T+60 / T+120 / T+250.
- Full (2016-2026), IS (2016-2021), OOS (2022-2026), and Last 3Y (2024-2026) splits vs CSI 300.
Strictly NO yfinance imports (D12) and NO cap10m.
"""
import concurrent.futures
import json
import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

assert "yfinance" not in sys.modules, "D12 violation"

OUT_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/output/extreme_commodities_3ring_backtest_20261125")
CACHE_DIR = OUT_DIR / "data_cache"

EVAL_START = pd.Timestamp("2016-01-04")
EVAL_END = pd.Timestamp("2026-11-24")
IS_END = pd.Timestamp("2021-12-31")
OOS_START = pd.Timestamp("2022-01-01")
LAST3Y_START = pd.Timestamp("2024-01-01")
FEE_ONE_WAY = 0.0015  # 0.15% buy + 0.15% sell = 0.30% round-trip
HORIZONS = [20, 60, 120, 250]
DECLUSTER_DAYS = 60

# Globals initialized per worker for fast multi-process execution
_G = {}


def init_worker():
    _G["mapping"] = json.loads((OUT_DIR / "three_ring_mapping.json").read_text(encoding="utf-8"))
    _G["ac_raw"] = pd.read_parquet(CACHE_DIR / "a_stocks_close.parquet")
    _G["ao_raw"] = pd.read_parquet(CACHE_DIR / "a_stocks_open.parquet")
    _G["yizi_up"] = pd.read_parquet(CACHE_DIR / "a_stocks_yizi_up.parquet")
    _G["yizi_dn"] = pd.read_parquet(CACHE_DIR / "a_stocks_yizi_down.parquet")
    _G["cn_fut"] = pd.read_parquet(CACHE_DIR / "cn_futures_close.parquet")
    _G["gl_fut"] = pd.read_parquet(CACHE_DIR / "global_futures_close.parquet")
    _G["hog_spot"] = pd.read_parquet(CACHE_DIR / "hog_spot.parquet")["HOG_SPOT"]
    _G["bdi"] = pd.read_parquet(CACHE_DIR / "bdi.parquet")["BDI"]
    _G["csi300"] = pd.read_parquet(CACHE_DIR / "csi300.parquet")
    us_p = CACHE_DIR / "us_stocks_close.parquet"
    _G["us_stk"] = pd.read_parquet(us_p) if us_p.exists() else pd.DataFrame()

    a_cal = _G["csi300"].loc["2015-01-01":EVAL_END].index
    _G["a_cal"] = a_cal
    ac = _G["ac_raw"].reindex(a_cal)
    ao = _G["ao_raw"].reindex(a_cal)
    _G["ac_raw"] = ac
    _G["ao_raw"] = ao
    _G["yizi_up"] = _G["yizi_up"].reindex(a_cal).fillna(False)
    _G["yizi_dn"] = _G["yizi_dn"].reindex(a_cal).fillna(False)

    # Forward-fill close strictly AFTER each stock's listing date for indicator signals only
    ac_ff = ac.copy()
    first_valid_pos = {}
    for col in ac_ff.columns:
        fv = ac_ff[col].first_valid_index()
        if fv is not None:
            ac_ff.loc[fv:, col] = ac_ff.loc[fv:, col].ffill()
            first_valid_pos[col] = int(a_cal.get_loc(fv))
        else:
            first_valid_pos[col] = 999999
    _G["ac_ff"] = ac_ff
    _G["first_valid_pos"] = first_valid_pos


def clean_num(v, nd=2):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), nd)


def build_pit_ring_index(tickers: list[str], a_cal: pd.DatetimeIndex, ac_raw: pd.DataFrame, ac_ff: pd.DataFrame, fv_pos: dict) -> pd.Series:
    """Strictly PIT equal-weight ring index: includes a stock only >= 60 trading days after listing."""
    rets = []
    for tk in tickers:
        if tk not in ac_raw.columns:
            continue
        p0 = fv_pos.get(tk, 999999)
        if p0 >= len(a_cal) - 65:
            continue
        s = ac_ff[tk]
        r = s.pct_change(fill_method=None)
        # Mask before listing + 60 trading days warmup
        r.iloc[: p0 + 60] = np.nan
        # Mask non-trading days so suspension doesn't distort active average, keep 0 only if needed
        r = r.where(ac_raw[tk].notna(), np.nan)
        rets.append(r)
    if not rets:
        return pd.Series(np.nan, index=a_cal)
    df_r = pd.concat(rets, axis=1)
    ew_r = df_r.mean(axis=1)
    # Only start index when at least 1 stock is active
    fv_idx = ew_r.first_valid_index()
    if fv_idx is None:
        return pd.Series(np.nan, index=a_cal)
    ew_r_sub = ew_r.loc[fv_idx:].fillna(0.0)
    idx_series = 100.0 * (1.0 + ew_r_sub).cumprod()
    return idx_series.reindex(a_cal)


def corr_stats(r: float, n_obs: int, ret_win: int):
    n_eff = float(n_obs) / float(ret_win)
    if n_eff <= 3.0 or r is None or not np.isfinite(r):
        return None, None, False
    if abs(r) >= 0.999999:
        return (99.0 if r > 0 else -99.0), 0.0, True
    df = n_eff - 2.0
    t_stat = float(r * math.sqrt(df / (1.0 - r * r)))
    p_val = float(2.0 * stats.t.sf(abs(t_stat), df=df))
    return round(t_stat, 2), round(p_val, 4), bool(p_val < 0.05)


def compute_lead_lag(stk_s: pd.Series, comm_s: pd.Series, start_dt: pd.Timestamp, ret_win: int = 60, max_lag: int = 180) -> dict:
    sr = stk_s.pct_change(ret_win, fill_method=None)
    cr = comm_s.pct_change(ret_win, fill_method=None)
    sr_eval = sr.loc[start_dt:]
    corrs, nobs = {}, {}
    for k in range(-max_lag, max_lag + 1):
        # k > 0 => corr(stock(t), comm(t+k)) => stock leads commodity by k days
        cr_sh = cr.shift(-k).reindex(sr_eval.index)
        pair = pd.concat([sr_eval, cr_sh], axis=1).dropna()
        n = len(pair)
        nobs[k] = n
        if n >= max(60, ret_win + 15):
            corrs[k] = float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
        else:
            corrs[k] = np.nan
    valid = [k for k in range(-max_lag, max_lag + 1) if np.isfinite(corrs[k])]
    if not valid:
        return {"insufficient": True}
    pos_k = max(valid, key=lambda k: corrs[k])
    neg_k = min(valid, key=lambda k: corrs[k])
    abs_k = max(valid, key=lambda k: abs(corrs[k]))
    r0 = corrs.get(0, np.nan)
    _, p0, sig0 = corr_stats(r0, nobs.get(0, 0), ret_win)
    _, p_pos, sig_pos = corr_stats(corrs[pos_k], nobs[pos_k], ret_win)
    _, p_neg, sig_neg = corr_stats(corrs[neg_k], nobs[neg_k], ret_win)

    # Short-window [-30, +30] peak
    short_valid = [k for k in valid if -30 <= k <= 30]
    s_abs_k = max(short_valid, key=lambda k: abs(corrs[k])) if short_valid else abs_k

    # Classify mechanism
    pos_r, neg_r = corrs[pos_k], corrs[neg_k]
    if abs(neg_r) > abs(pos_r) and neg_r <= -0.22 and sig_neg:
        regime = "成本反向受益"
    elif max(abs(pos_r), abs(neg_r)) < 0.20 or (not sig_pos and not sig_neg):
        regime = "弱/伪相关"
    elif abs(pos_k) <= 10 and np.isfinite(r0) and r0 >= 0.22:
        regime = "0天同步共振"
    elif pos_k > 10 and sig_pos:
        regime = "股领先期"
    elif pos_k < -10 and sig_pos:
        regime = "期领先股(补涨)"
    else:
        regime = "弱同步"

    return {
        "n_obs": int(nobs.get(0, 0)),
        "lag0_r": clean_num(r0, 3), "lag0_p": p0,
        "pos_peak_lag": int(pos_k), "pos_peak_r": clean_num(pos_r, 3), "pos_peak_p": p_pos,
        "neg_peak_lag": int(neg_k), "neg_peak_r": clean_num(neg_r, 3), "neg_peak_p": p_neg,
        "abs_peak_lag": int(abs_k), "abs_peak_r": clean_num(corrs[abs_k], 3),
        "short30_peak_lag": int(s_abs_k), "short30_peak_r": clean_num(corrs[s_abs_k], 3),
        "regime": regime,
    }


def extract_zigzag_pivots(s: pd.Series, cal_idx: pd.DatetimeIndex, pct: float) -> list[dict]:
    s = s.dropna()
    if len(s) < 40:
        return []
    vals = s.values.astype(float)
    dates = s.index
    pivots = []
    min_p, min_i = vals[0], 0
    max_p, max_i = vals[0], 0
    direction, start_i = 0, 0
    for i in range(1, len(vals)):
        p = vals[i]
        if p < min_p:
            min_p, min_i = p, i
        if p > max_p:
            max_p, max_i = p, i
        if p >= min_p * (1.0 + pct):
            pivots.append(("L", dates[min_i], float(min_p), min_i))
            direction, last_p, last_i, start_i = 1, p, i, i
            break
        if p <= max_p * (1.0 - pct):
            pivots.append(("H", dates[max_i], float(max_p), max_i))
            direction, last_p, last_i, start_i = -1, p, i, i
            break
    if direction == 0:
        return []
    for i in range(start_i + 1, len(vals)):
        p = vals[i]
        if direction == 1:
            if p >= last_p:
                last_p, last_i = p, i
            elif p <= last_p * (1.0 - pct):
                pivots.append(("H", dates[last_i], float(last_p), last_i))
                direction, last_p, last_i = -1, p, i
        else:
            if p <= last_p:
                last_p, last_i = p, i
            elif p >= last_p * (1.0 + pct):
                pivots.append(("L", dates[last_i], float(last_p), last_i))
                direction, last_p, last_i = 1, p, i
    out = []
    for typ, dt, val, pos in pivots:
        w60 = vals[max(0, pos - 60):min(len(vals), pos + 61)]
        is_121 = bool((val == np.max(w60)) if typ == "H" else (val == np.min(w60)))
        if dt in cal_idx:
            out.append({"typ": typ, "date": str(dt)[:10], "val": val, "cal_pos": int(cal_idx.get_loc(dt)), "is_121": is_121})
    return out


def turning_point_lead_median(comm_s: pd.Series, stk_s: pd.Series, a_cal: pd.DatetimeIndex) -> dict:
    st_dt = max(comm_s.dropna().index.min(), stk_s.dropna().index.min(), EVAL_START)
    c_piv = [p for p in extract_zigzag_pivots(comm_s.loc[st_dt:], a_cal, 0.15) if p["is_121"]]
    s_piv = extract_zigzag_pivots(stk_s.loc[st_dt:], a_cal, 0.20)
    if not c_piv or not s_piv:
        return {"n_matched": 0, "med_lead_d": None, "bot_med_d": None, "top_med_d": None}
    b_leads, t_leads = [], []
    for cp in c_piv:
        cands = [cp["cal_pos"] - sp["cal_pos"] for sp in s_piv if sp["typ"] == cp["typ"] and abs(cp["cal_pos"] - sp["cal_pos"]) <= 180]
        if cands:
            best = min(cands, key=abs)
            if cp["typ"] == "L":
                b_leads.append(best)
            else:
                t_leads.append(best)
    all_l = b_leads + t_leads
    return {
        "n_matched": len(all_l),
        "med_lead_d": round(float(np.median(all_l)), 1) if all_l else None,
        "bot_med_d": round(float(np.median(b_leads)), 1) if b_leads else None,
        "top_med_d": round(float(np.median(t_leads)), 1) if t_leads else None,
    }


def decluster_dates(sig: pd.Series, gap: int = DECLUSTER_DAYS) -> list[int]:
    """Return integer positions on sig index separated by at least `gap` trading days."""
    idxs = []
    last = -999999
    arr = sig.values.astype(bool)
    for i in range(len(arr)):
        if arr[i] and (i - last >= gap):
            idxs.append(i)
            last = i
    return idxs


def evaluate_event_list(
    sig_positions: list[int],
    tickers: list[str],
    a_cal: pd.DatetimeIndex,
    ao_raw: pd.DataFrame,
    ac_raw: pd.DataFrame,
    ac_ff: pd.DataFrame,
    yizi_up: pd.DataFrame,
    yizi_dn: pd.DataFrame,
    fv_pos: dict,
    csi300_open: pd.Series,
    csi300_close: pd.Series,
) -> dict:
    """Strictly PIT T+1 open buy, 0.30% two-way cost, skip T+1 yizi-up unbuyable stocks."""
    n_cal = len(a_cal)
    ao_arr = {tk: ao_raw[tk].values if tk in ao_raw.columns else None for tk in tickers}
    ac_arr = {tk: ac_raw[tk].values if tk in ac_raw.columns else None for tk in tickers}
    ff_arr = {tk: ac_ff[tk].values if tk in ac_ff.columns else None for tk in tickers}
    yu_arr = {tk: yizi_up[tk].values if tk in yizi_up.columns else None for tk in tickers}
    yd_arr = {tk: yizi_dn[tk].values if tk in yizi_dn.columns else None for tk in tickers}
    csi_o = csi300_open.values
    csi_c = csi300_close.values

    events_by_h = {h: [] for h in HORIZONS}
    excluded_all_yizi = 0

    for t_sig in sig_positions:
        t_buy = t_sig + 1
        if t_buy >= n_cal - 20:
            continue
        # Check tradable & non-yizi-up stocks on T+1 open
        buyable = []
        for tk in tickers:
            if ao_arr[tk] is None:
                continue
            if t_sig < fv_pos.get(tk, 999999) + 60:
                continue
            op_v = ao_arr[tk][t_buy]
            cl_v = ac_arr[tk][t_buy]
            if not (np.isfinite(op_v) and np.isfinite(cl_v) and op_v > 0):
                continue
            if bool(yu_arr[tk][t_buy]):
                continue  # Exclude T+1 open one-word limit-up (unbuyable)
            buyable.append(tk)

        if not buyable:
            excluded_all_yizi += 1
            continue

        b_open_csi = float(csi_o[t_buy])
        if not np.isfinite(b_open_csi) or b_open_csi <= 0:
            continue

        sig_date = str(a_cal[t_sig])[:10]
        buy_date = str(a_cal[t_buy])[:10]

        for h in HORIZONS:
            t_target_sell = t_buy + h
            if t_target_sell >= n_cal:
                continue

            leg_rets = []
            leg_mdds = []
            for tk in buyable:
                p_in = float(ao_arr[tk][t_buy]) * (1.0 + FEE_ONE_WAY)
                # Find actual exit day >= t_target_sell (postpone if suspended or one-word limit-down)
                t_ex = t_target_sell
                while t_ex < n_cal - 1:
                    op_ex = ao_arr[tk][t_ex]
                    if np.isfinite(op_ex) and op_ex > 0 and not bool(yd_arr[tk][t_ex]):
                        break
                    t_ex += 1
                p_out_raw = ao_arr[tk][t_ex]
                if not (np.isfinite(p_out_raw) and p_out_raw > 0):
                    p_out_raw = ff_arr[tk][t_ex]
                if not (np.isfinite(p_out_raw) and p_out_raw > 0):
                    continue
                p_out = float(p_out_raw) * (1.0 - FEE_ONE_WAY)
                leg_rets.append(p_out / p_in - 1.0)

                # Intra-trade drawdown using ff close path
                path = ff_arr[tk][t_buy: t_ex + 1]
                valid_p = path[np.isfinite(path)]
                if len(valid_p) > 0:
                    curve = np.concatenate([[float(ao_arr[tk][t_buy])], valid_p])
                    pk = np.maximum.accumulate(curve)
                    mdd = float(np.min(curve / pk - 1.0))
                    leg_mdds.append(mdd)

            if not leg_rets:
                continue

            # CSI 300 benchmark over exact [t_buy open -> t_target_sell open]
            s_open_csi = float(csi_o[t_target_sell])
            if not np.isfinite(s_open_csi) or s_open_csi <= 0:
                s_open_csi = float(csi_c[t_target_sell])
            csi_ret = s_open_csi / b_open_csi - 1.0

            net_ret = float(np.mean(leg_rets))
            ex_ret = net_ret - csi_ret
            events_by_h[h].append({
                "sig_date": sig_date,
                "buy_date": buy_date,
                "ts": a_cal[t_sig],
                "net_pct": net_ret * 100.0,
                "csi_pct": csi_ret * 100.0,
                "ex_pct": ex_ret * 100.0,
                "mdd_pct": float(np.mean(leg_mdds)) * 100.0 if leg_mdds else 0.0,
                "n_legs": len(leg_rets),
            })

    def summarize_evs(evs: list[dict]) -> dict:
        if not evs:
            return {"n": 0}
        nets = np.array([e["net_pct"] for e in evs])
        exs = np.array([e["ex_pct"] for e in evs])
        mdds = np.array([e["mdd_pct"] for e in evs])
        wins_a = nets[nets > 0]
        loss_a = nets[nets <= 0]
        wins_e = exs[exs > 0]
        loss_e = exs[exs <= 0]
        pl_a = (float(np.mean(wins_a)) / abs(float(np.mean(loss_a)))) if (len(wins_a) and len(loss_a) and abs(np.mean(loss_a)) > 1e-6) else None
        pl_e = (float(np.mean(wins_e)) / abs(float(np.mean(loss_e)))) if (len(wins_e) and len(loss_e) and abs(np.mean(loss_e)) > 1e-6) else None
        return {
            "n": int(len(evs)),
            "abs_mean_pct": round(float(np.mean(nets)), 2),
            "abs_med_pct": round(float(np.median(nets)), 2),
            "ex_mean_pct": round(float(np.mean(exs)), 2),
            "ex_med_pct": round(float(np.median(exs)), 2),
            "win_abs_pct": round(float(np.mean(nets > 0) * 100.0), 1),
            "win_ex_pct": round(float(np.mean(exs > 0) * 100.0), 1),
            "pl_abs": round(pl_a, 2) if pl_a is not None else None,
            "pl_ex": round(pl_e, 2) if pl_e is not None else None,
            "avg_mdd_pct": round(float(np.mean(mdds)), 2),
        }

    out = {"excluded_yizi_events": int(excluded_all_yizi), "horizons": {}}
    for h in HORIZONS:
        evs = evs_full = events_by_h[h]
        evs_is = [e for e in evs if e["ts"] <= IS_END]
        evs_oos = [e for e in evs if e["ts"] >= OOS_START]
        evs_3y = [e for e in evs if e["ts"] >= LAST3Y_START]
        out["horizons"][str(h)] = {
            "full": summarize_evs(evs_full),
            "is": summarize_evs(evs_is),
            "oos": summarize_evs(evs_oos),
            "last_3y": summarize_evs(evs_3y),
            "raw_events": [
                {"sig_date": e["sig_date"], "buy_date": e["buy_date"],
                 "net_pct": round(e["net_pct"], 2), "csi_pct": round(e["csi_pct"], 2),
                 "ex_pct": round(e["ex_pct"], 2), "mdd_pct": round(e["mdd_pct"], 2)}
                for e in evs
            ],
        }
    return out


def process_one_commodity(task: tuple[str, dict, str]) -> tuple[str, dict]:
    """Worker function for ProcessPoolExecutor."""
    track_id, spec, drv_sym = task
    a_cal = _G["a_cal"]
    ac_raw, ao_raw, ac_ff = _G["ac_raw"], _G["ao_raw"], _G["ac_ff"]
    yu, yd, fv_pos = _G["yizi_up"], _G["yizi_dn"], _G["first_valid_pos"]
    csi_o = _G["csi300"]["csi300_open"].reindex(a_cal).ffill()
    csi_c = _G["csi300"]["csi300_close"].reindex(a_cal).ffill()

    # Load commodity price series and align strictly forward onto A-share calendar
    if drv_sym == "HOG_SPOT":
        raw_comm = _G["hog_spot"].dropna()
    elif drv_sym == "BDI":
        raw_comm = _G["bdi"].dropna()
    elif drv_sym in _G["cn_fut"].columns:
        raw_comm = _G["cn_fut"][drv_sym].dropna()
    elif drv_sym in _G["gl_fut"].columns:
        raw_comm = _G["gl_fut"][drv_sym].dropna()
        raw_comm = raw_comm[raw_comm.index.dayofweek < 5]
    else:
        return track_id, {"error": f"missing_driver:{drv_sym}"}

    # For US commodities, shift 1 day if needed? Note: US settlement T occurs overnight CST after T-1 A-share close,
    # Wait: US date T closes at 05:00 CST on T+1 morning BEFORE A-share T+1 open!
    # So signal at US date T close is strictly known BEFORE A-share T+1 open (or align US T -> A-share T for T+1 open buy).
    # Keep full pre-2016 commodity history for causal rolling percentile!
    comm_full_a = raw_comm.reindex(raw_comm.index.union(a_cal)).sort_index().ffill()
    comm_a = comm_full_a.reindex(a_cal)
    fv_comm = raw_comm.index.min()
    comm_a = comm_a.where(a_cal >= fv_comm, np.nan)

    # Strictly causal percentiles computed on full pre-2016+ commodity series before slicing to a_cal
    # Use min_periods=120 for newly listed contracts (<4Y), 252 otherwise
    total_yrs = (raw_comm.index.max() - raw_comm.index.min()).days / 365.25
    min_p = 120 if total_yrs < 4.5 else 252
    # Compute rolling rank on raw_comm's own valid trading days (to avoid weekend/holiday duplication)
    raw_valid = raw_comm.copy()
    p10_raw = raw_valid.rolling(2520, min_periods=min_p).rank(pct=True)
    p5_raw = raw_valid.rolling(1260, min_periods=min_p).rank(pct=True)
    ma20_raw = raw_valid.rolling(20, min_periods=20).mean()
    ret20_raw = raw_valid.pct_change(20, fill_method=None)

    # Map strictly forward to a_cal (no bfill!)
    p10_a = p10_raw.reindex(a_cal, method="ffill").where(a_cal >= fv_comm, np.nan)
    p5_a = p5_raw.reindex(a_cal, method="ffill").where(a_cal >= fv_comm, np.nan)
    ma20_a = ma20_raw.reindex(a_cal, method="ffill").where(a_cal >= fv_comm, np.nan)
    ret20_a = ret20_raw.reindex(a_cal, method="ffill").where(a_cal >= fv_comm, np.nan)

    # Build Ring 1 / Ring 2 / Ring 3 PIT equal-weight indices
    ring_indices = {}
    for rk in ("ring1", "ring2", "ring3"):
        ring_indices[rk] = build_pit_ring_index(spec[rk], a_cal, ac_raw, ac_ff, fv_pos)

    eval_mask = a_cal >= max(EVAL_START, fv_comm + pd.Timedelta(days=90))
    eval_start_dt = a_cal[eval_mask][0] if eval_mask.any() else EVAL_START
    last5_dt = max(eval_start_dt, pd.Timestamp("2021-11-24"))

    # Module 1: Lead/Lag & Correlation across Rings 1 / 2 / 3
    leadlag = {"full": {}, "last_5y": {}, "turning_points": {}, "stock_level_lag0": {}}
    for rk in ("ring1", "ring2", "ring3"):
        stk_s = ring_indices[rk]
        leadlag["full"][rk] = {
            "ret60": compute_lead_lag(stk_s, comm_a, eval_start_dt, ret_win=60),
            "ret20": compute_lead_lag(stk_s, comm_a, eval_start_dt, ret_win=20),
        }
        leadlag["last_5y"][rk] = {
            "ret60": compute_lead_lag(stk_s, comm_a, last5_dt, ret_win=60),
        }
        leadlag["turning_points"][rk] = turning_point_lead_median(comm_a, stk_s, a_cal)

        # Top stock-level lag0 correlation inside each ring
        stk_corrs = []
        cr60 = comm_a.pct_change(60, fill_method=None)
        for tk in spec[rk]:
            if tk in ac_ff.columns:
                sr60 = ac_ff[tk].pct_change(60, fill_method=None)
                pair = pd.concat([sr60, cr60], axis=1).loc[eval_start_dt:].dropna()
                r_val = float(pair.iloc[:, 0].corr(pair.iloc[:, 1])) if len(pair) >= 60 else None
                stk_corrs.append({"ticker": tk, "r60_lag0": clean_num(r_val, 3), "n": int(len(pair))})
        leadlag["stock_level_lag0"][rk] = stk_corrs

    # US peer cross-correlation if available
    us_corrs = {}
    if spec.get("us_peers") and not _G["us_stk"].empty:
        us_df = _G["us_stk"]
        comm_us_ref = raw_comm.reindex(us_df.index, method="ffill").where(us_df.index >= fv_comm, np.nan)
        for up in spec["us_peers"]:
            if up in us_df.columns:
                us_corrs[up] = compute_lead_lag(us_df[up], comm_us_ref, EVAL_START, ret_win=60)
    leadlag["us_peers"] = us_corrs

    # Module 2: Extreme Event Reversal Study across Rings 1 / 2 / 3
    # Build causal trigger signals on a_cal >= EVAL_START
    in_eval = pd.Series(a_cal >= EVAL_START, index=a_cal)
    low_ext = ((p10_a <= 0.10) | (p5_a <= 0.05)) & in_eval
    high_ext = ((p10_a >= 0.85) | (p5_a >= 0.85)) & in_eval

    # Deep extreme state in past 20 trading days (for physical/trend reversal trigger)
    low_zone_20 = ((p10_a <= 0.15) | (p5_a <= 0.10)).rolling(20, min_periods=1).max().astype(bool) & in_eval
    high_zone_20 = ((p10_a >= 0.80) | (p5_a >= 0.80)).rolling(20, min_periods=1).max().astype(bool) & in_eval

    comm_up_rev = low_zone_20 & (comm_a > ma20_a) & (ret20_a > 0.0)
    comm_dn_rev = high_zone_20 & (comm_a < ma20_a) & (ret20_a < 0.0)

    triggers_comm = {
        "LOW_BARE": decluster_dates(low_ext.fillna(False)),
        "LOW_COMM_REV": decluster_dates(comm_up_rev.fillna(False)),
        "HIGH_BARE": decluster_dates(high_ext.fillna(False)),
        "HIGH_COMM_REV": decluster_dates(comm_dn_rev.fillna(False)),
    }

    events_out = {}
    for rk in ("ring1", "ring2", "ring3"):
        stk_s = ring_indices[rk]
        stk_ma20 = stk_s.rolling(20, min_periods=20).mean()
        stk_ret20 = stk_s.pct_change(20, fill_method=None)
        stk_up_rev = low_zone_20 & (stk_s > stk_ma20) & (stk_ret20 > 0.0)
        stk_dn_rev = high_zone_20 & (stk_s < stk_ma20) & (stk_ret20 < 0.0)

        rk_triggers = {
            **triggers_comm,
            "LOW_STK_REV": decluster_dates(stk_up_rev.fillna(False)),
            "HIGH_STK_REV": decluster_dates(stk_dn_rev.fillna(False)),
        }
        events_out[rk] = {}
        for trig_nm, pos_list in rk_triggers.items():
            events_out[rk][trig_nm] = evaluate_event_list(
                pos_list, spec[rk], a_cal, ao_raw, ac_raw, ac_ff, yu, yd, fv_pos, csi_o, csi_c
            )

    return track_id, {
        "track_id": track_id,
        "name": spec["name"],
        "group": spec["group"],
        "driver": drv_sym,
        "history_years": round(total_yrs, 2),
        "eval_start": str(eval_start_dt)[:10],
        "screen": spec.get("screen", {}),
        "leadlag": leadlag,
        "events": events_out,
    }


def aggregate_pooled_events(all_results: dict) -> dict:
    """Aggregate raw events across commodities (excluding proxy duplicates) for Ring 1 vs 2 vs 3 verdict."""
    # Use primary tracks (skip _10Y_PROXY duplicates so we don't double-count LH0+HOG_SPOT or EC0+BDI)
    primary_keys = [k for k in all_results if not k.endswith("_PROXY")]
    long5y_keys = [k for k in primary_keys if all_results[k].get("history_years", 0) >= 5.0]

    def summarize_raw(raw_list: list[dict], drop_top3: bool = False) -> dict:
        if not raw_list:
            return {"n": 0}
        arr = sorted(raw_list, key=lambda x: x["ex_pct"], reverse=True)
        if drop_top3 and len(arr) > 10:
            arr = arr[3:]
        nets = np.array([x["net_pct"] for x in arr])
        exs = np.array([x["ex_pct"] for x in arr])
        mdds = np.array([x["mdd_pct"] for x in arr])
        wins_a = nets[nets > 0]
        loss_a = nets[nets <= 0]
        wins_e = exs[exs > 0]
        loss_e = exs[exs <= 0]
        pl_a = float(np.mean(wins_a)) / abs(float(np.mean(loss_a))) if (len(wins_a) and len(loss_a) and abs(np.mean(loss_a)) > 1e-6) else None
        pl_e = float(np.mean(wins_e)) / abs(float(np.mean(loss_e))) if (len(wins_e) and len(loss_e) and abs(np.mean(loss_e)) > 1e-6) else None
        t_st, p_val = stats.ttest_1samp(exs, 0.0) if len(exs) >= 5 else (0.0, 1.0)
        return {
            "n": int(len(arr)),
            "abs_mean_pct": round(float(np.mean(nets)), 2),
            "abs_med_pct": round(float(np.median(nets)), 2),
            "ex_mean_pct": round(float(np.mean(exs)), 2),
            "ex_med_pct": round(float(np.median(exs)), 2),
            "win_abs_pct": round(float(np.mean(nets > 0) * 100.0), 1),
            "win_ex_pct": round(float(np.mean(exs > 0) * 100.0), 1),
            "pl_abs": round(pl_a, 2) if pl_a is not None else None,
            "pl_ex": round(pl_e, 2) if pl_e is not None else None,
            "avg_mdd_pct": round(float(np.mean(mdds)), 2),
            "ex_std_pct": round(float(np.std(exs, ddof=1)), 2) if len(exs) > 1 else None,
            "ex_t_stat": round(float(t_st), 2),
            "ex_p_val": round(float(p_val), 4),
        }

    pooled = {}
    subsets = {
        "ALL_29": primary_keys,
        "HIGH_GROUP": [k for k in primary_keys if all_results[k]["group"] == "HIGH"],
        "LOW_GROUP": [k for k in primary_keys if all_results[k]["group"] == "LOW"],
        "LONG_HIST_5Y": long5y_keys,
    }
    triggers = ["LOW_BARE", "LOW_COMM_REV", "LOW_STK_REV", "HIGH_BARE", "HIGH_COMM_REV", "HIGH_STK_REV"]

    for sub_nm, keys in subsets.items():
        pooled[sub_nm] = {}
        for trig in triggers:
            pooled[sub_nm][trig] = {}
            for rk in ("ring1", "ring2", "ring3"):
                pooled[sub_nm][trig][rk] = {}
                for h in HORIZONS:
                    raw_all = []
                    for k in keys:
                        ev_block = all_results[k]["events"][rk][trig]["horizons"][str(h)]
                        raw_all.extend(ev_block.get("raw_events", []))
                    raw_is = [e for e in raw_all if e["sig_date"] <= "2021-12-31"]
                    raw_oos = [e for e in raw_all if e["sig_date"] >= "2022-01-01"]
                    raw_3y = [e for e in raw_all if e["sig_date"] >= "2024-01-01"]
                    pooled[sub_nm][trig][rk][str(h)] = {
                        "full": summarize_raw(raw_all),
                        "full_drop_top3": summarize_raw(raw_all, drop_top3=True),
                        "is": summarize_raw(raw_is),
                        "oos": summarize_raw(raw_oos),
                        "last_3y": summarize_raw(raw_3y),
                    }
    return pooled


def main():
    mapping = json.loads((OUT_DIR / "three_ring_mapping.json").read_text(encoding="utf-8"))
    tasks = []
    for sym, spec in mapping["commodities"].items():
        tasks.append((sym, spec, spec["driver"]))
        if spec.get("proxy_10y"):
            tasks.append((f"{sym}_{spec['proxy_10y']}_PROXY", spec, spec["proxy_10y"]))

    print(f"Launching ProcessPoolExecutor(max_workers=8) for {len(tasks)} commodity tracks...")
    results = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=8, initializer=init_worker) as ex:
        for track_id, res in ex.map(process_one_commodity, tasks):
            results[track_id] = res
            print(f"  [OK] {track_id} ({res.get('name')}) | yrs={res.get('history_years')} | "
                  f"R1={res['leadlag']['full']['ring1']['ret60'].get('regime')} "
                  f"(r0={res['leadlag']['full']['ring1']['ret60'].get('lag0_r')}, pk={res['leadlag']['full']['ring1']['ret60'].get('pos_peak_lag')}d)")

    pooled = aggregate_pooled_events(results)

    # Strip raw_events from main lightweight summary while keeping full ledger in separate json
    full_ledger_path = OUT_DIR / "backtest_3ring_events_ledger.json"
    with open(full_ledger_path, "w", encoding="utf-8") as f:
        json.dump({"commodities": results, "pooled": pooled}, f, ensure_ascii=False)

    # Save compact master results without raw_events arrays
    compact = {"as_of_date": "2026-11-24", "pooled": pooled, "commodities": {}}
    for k, v in results.items():
        cv = {kk: vv for kk, vv in v.items() if kk != "events"}
        cv["events"] = {}
        for rk, rmap in v["events"].items():
            cv["events"][rk] = {}
            for tr, tmap in rmap.items():
                cv["events"][rk][tr] = {
                    "excluded_yizi_events": tmap["excluded_yizi_events"],
                    "horizons": {
                        h: {p: hv[p] for p in ("full", "is", "oos", "last_3y")}
                        for h, hv in tmap["horizons"].items()
                    },
                }
        compact["commodities"][k] = cv

    out_path = OUT_DIR / "backtest_3ring_summary.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, ensure_ascii=False, indent=2)
    print(f"\nDONE Step 2: wrote {out_path} and {full_ledger_path}")


if __name__ == "__main__":
    main()

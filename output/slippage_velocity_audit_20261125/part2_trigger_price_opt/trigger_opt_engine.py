#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part 2 Trigger-Price & Fixed Limit-Cap Optimization Engine.
Unified 3-tier velocity slippage (0% / +0.5% / +1.0%, zt_px capped),
full pre-market pool evaluation (including untriggered stocks),
D15 metrics, daily MTM, HLZ/DSR(M=150), and CSCV PBO (S=8, S=10).
ZERO import yfinance (D12).
"""
import itertools
import json
import math
import os
import pickle
import sys
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/output/slippage_velocity_audit_20261125/part2_trigger_price_opt"
PART1_DIR = f"{SIM}/output/slippage_velocity_audit_20261125/part1_individual_and_scoring"
PARTA_DIR = f"{SIM}/output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
ABL_DIR = f"{SIM}/backtests_astock/ablation_1to2_psz35_tight37_20261123"
MW1_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high"
MW3_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part3_1to2"
F1_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4"
HD_DIR = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
GOLD_DIR = f"{SIM}/backtests_astock/sandbox_lab/golden_regime_20261113"
A2_ASSETS = f"{SIM}/backtests_astock2/assets"

PATH_5M_MAIN = f"{SIM}/data/all_strategies_5m_complete_pit.parquet"
PATH_5M_PATCH = f"{OUT_DIR}/_patch_5m_bars.parquet"
PATH_5M_C34 = f"{SIM}/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet"
PATH_5M_GT60 = f"{SIM}/backtests_astock/ablation_1to2_price60_20261119/gt60_5m_patch.parquet"
PATH_SUB2_5M = f"{HD_DIR}/sub2_5m_bars_cache.pkl"
PATH_A_DAILY = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
PATH_A_DELIST = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
PATH_IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

FEE_RATE = 0.0020
TRD_DAYS_YEAR = 242.0

CANON_WINDOWS = [
    ("FULL", "2021-11-16", "2026-11-16"),
    ("IS", "2021-11-16", "2024-06-30"),
    ("OOS", "2024-07-04", "2026-11-16"),
    ("Near3Y", "2023-11-16", "2026-11-16"),
    ("Y2026", "2026-01-01", "2026-11-16"),
]


def sf(x, digits=6):
    if x is None:
        return None
    v = float(x)
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, digits)


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def load_all_5m_and_daily():
    """Load CSI 300, merged 5m bar arrays keyed by (c6, dt), and full daily truth dmap."""
    with open(PATH_IDX_JSON, "r", encoding="utf-8") as f:
        idx_raw = json.load(f)
    sh300 = {k: float(v) for k, v in idx_raw["sh000300"].items()}
    all_sh_dts = sorted(sh300.keys())
    cal_5y = [d for d in all_sh_dts if "2021-11-16" <= d <= "2026-11-16"]
    dt_idx_5y = {d: i for i, d in enumerate(cal_5y)}

    bars_5m = {}
    for path in (PATH_5M_MAIN, PATH_5M_C34, PATH_5M_GT60, PATH_5M_PATCH):
        if not os.path.exists(path):
            continue
        df5 = pd.read_parquet(
            path,
            columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        )
        df5["c6"] = df5["c6"].astype(str).str.zfill(6)
        df5["dt"] = df5["date"].astype(str).str[:10]
        df5 = df5[df5["dt"] <= "2026-11-16"].sort_values(["c6", "dt", "hhmm_int"])
        for (c6, dt), grp in df5.groupby(["c6", "dt"], sort=False):
            if (c6, dt) not in bars_5m:
                bars_5m[(c6, dt)] = grp[
                    ["hhmm_int", "open", "high", "low", "close", "volume", "amount"]
                ].to_numpy(dtype=float)

    sub2_raw = pickle.load(open(PATH_SUB2_5M, "rb"))
    for k, v in sub2_raw.items():
        c6, dt = str(k[0]).zfill(6), str(k[2])[:10]
        if (c6, dt) not in bars_5m and isinstance(v, pd.DataFrame) and not v.empty:
            sub = v[v["date"].astype(str).str[:10] == dt]
            if not sub.empty:
                hh = sub["hhmm"].astype(str).str.replace(":", "").astype(int).to_numpy(float)
                bars_5m[(c6, dt)] = np.column_stack([
                    hh, sub["open"], sub["high"], sub["low"], sub["close"], sub["volume"], sub["amount"]
                ]).astype(float)

    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    flt = ds.field("date") >= pd.Timestamp("2020-12-01")
    da = ds.dataset(PATH_A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(PATH_A_DELIST, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    df_d = pd.concat([da, dd], ignore_index=True)
    df_d["c6"] = df_d["ticker"].astype(str).str[:6]
    df_d = df_d[df_d["c6"].str.startswith(("00", "60")) & (~df_d["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df_d["dt"] = df_d["date"].dt.strftime("%Y-%m-%d")
    df_d.sort_values(["c6", "dt", "dl"], inplace=True)
    df_d.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df_d.reset_index(drop=True, inplace=True)
    df_d["adjf"] = np.where((df_d["close"] > 0) & (df_d["adj_close"] > 0), df_d["adj_close"] / df_d["close"], 1.0)
    g = df_d.groupby("c6", sort=False)
    df_d["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df_d["adjf"]
    df_d["zt_px"] = np.floor(df_d["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df_d["dt_px"] = np.floor(df_d["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df_d["is_dt_exact"] = (df_d["close"] <= df_d["dt_px"] + 0.005) & (df_d["pre_c"] > 0)
    df_d["is_yizi_dt"] = df_d["is_dt_exact"] & (df_d["open"] <= df_d["dt_px"] + 0.005) & (df_d["high"] <= df_d["dt_px"] + 0.005)

    dmap = {
        (r.c6, r.dt): {
            "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close),
            "adj_close": float(r.adj_close), "qfq": float(r.qfq_factor), "adjf": float(r.adjf),
            "pre_c": float(r.pre_c) if pd.notna(r.pre_c) else np.nan,
            "zt_px": float(r.zt_px) if pd.notna(r.zt_px) else np.nan,
            "dt_px": float(r.dt_px) if pd.notna(r.dt_px) else np.nan,
            "is_dt_exact": bool(r.is_dt_exact),
            "is_yizi_dt": bool(r.is_yizi_dt),
        }
        for r in df_d.itertuples(index=False)
    }
    return sh300, all_sh_dts, cal_5y, dt_idx_5y, bars_5m, dmap


def exec_intraday_vel_or_cap(
    arr_5m: np.ndarray | None,
    open_d: float,
    pre_c: float,
    zt_px: float,
    new_trig: float,
    cancel_hhmm: int,
    force_0925: bool = False,
    cap_pct: float | None = None,
    force_pullback_if_fast: bool = False,
    round_trig_2dec: bool = True,
    match_3to4_open_floor: bool = False,
    trig_eps: float = 0.0,
) -> dict:
    """
    Unified 5m trigger scan + 3-tier velocity slippage + fixed limit-cap pullback check.

    Status outcomes:
      - 'filled_0925': filled at 09:25 open (0% extra slip)
      - 'filled_intraday': triggered intraday and filled (sell5 or limit cap)
      - 'missed_cap': triggered on fast surge (or open_5m > cap), failed causal pullback <= cap by cancel_hhmm
      - 'untriggered': never touched new_trig <= cancel_hhmm (or new_trig >= zt_px - 0.005)
      - 'unbuyable_yizi': 09:25 already sealed at zt_px
    """
    if open_d <= 0 or pre_c <= 0 or zt_px <= 0 or open_d >= zt_px - 0.005:
        return {"status": "unbuyable_yizi"}

    if force_0925:
        return {
            "status": "filled_0925",
            "buy_hhmm": 925,
            "trig_px": round(open_d, 2),
            "pre_slip_px": round(open_d, 2),
            "eff_buy": round(open_d, 2),
            "vel_tier": "auction_0925",
            "nom_slip": 0.0,
            "real_slip": 0.0,
            "zt_capped": False,
            "open_gt_trig": False,
            "is_zt_hit": False,
            "is_zt_sealed": False,
            "pulled_back": True,
        }

    trig_eval = round(float(new_trig), 2) if round_trig_2dec else float(new_trig)
    if trig_eval >= zt_px - 0.005:
        return {"status": "untriggered", "reason": "trig_at_zt"}

    if open_d >= trig_eval:
        return {
            "status": "filled_0925",
            "buy_hhmm": 925,
            "trig_px": round(open_d, 2),
            "pre_slip_px": round(open_d, 2),
            "eff_buy": round(open_d, 2),
            "vel_tier": "auction_0925",
            "nom_slip": 0.0,
            "real_slip": 0.0,
            "zt_capped": False,
            "open_gt_trig": False,
            "is_zt_hit": False,
            "is_zt_sealed": False,
            "pulled_back": True,
        }

    if arr_5m is None or len(arr_5m) == 0:
        return {"status": "untriggered", "reason": "missing_5m"}

    hit_idx = None
    for bi in range(len(arr_5m)):
        hh = int(arr_5m[bi, 0])
        if hh > cancel_hhmm:
            break
        bh = float(arr_5m[bi, 2])
        bl = float(arr_5m[bi, 3])
        if bl >= zt_px - 0.01:
            continue
        if bh >= trig_eval - trig_eps:
            hit_idx = bi
            break

    if hit_idx is None:
        return {"status": "untriggered", "reason": "no_touch"}

    hh = int(arr_5m[hit_idx, 0])
    o5 = float(arr_5m[hit_idx, 1])
    h5 = float(arr_5m[hit_idx, 2])
    l5 = float(arr_5m[hit_idx, 3])
    c5 = float(arr_5m[hit_idx, 4])

    open_gt_trig = bool(o5 > trig_eval + 1e-4)
    # Match Part 1 base trigger price convention (for 3to4/high, max(o5, trig) rounded to 2 dec if o5 > trig)
    if match_3to4_open_floor:
        base_tp = round(max(o5, trig_eval), 2)
    else:
        base_tp = round(trig_eval, 2) if round_trig_2dec else float(trig_eval)

    if base_tp >= zt_px - 0.005:
        return {"status": "untriggered", "reason": "open_jump_zt"}

    surge = (h5 - base_tp) / base_tp
    jump = (h5 - o5) / pre_c
    hit_zt = h5 >= zt_px - 0.01
    seal_zt = hit_zt and (c5 >= zt_px - 0.01)

    if hit_zt or surge >= 0.025 or jump >= 0.040:
        tier, slip = "fast", 0.010
    elif surge >= 0.010 or jump >= 0.020:
        tier, slip = "medium", 0.005
    else:
        tier, slip = "slow", 0.000

    # Unconstrained sell-5 sweep execution price (never below open_5m when bar opens > trig)
    eff_sell5 = min(max(o5, base_tp * (1.0 + slip)), zt_px) if open_gt_trig else min(base_tp * (1.0 + slip), zt_px)

    if cap_pct is None:
        return {
            "status": "filled_intraday",
            "buy_hhmm": hh,
            "trig_px": round(base_tp, 4),
            "pre_slip_px": round(base_tp, 4),
            "eff_buy": round(eff_sell5, 6),
            "vel_tier": tier,
            "nom_slip": slip,
            "real_slip": eff_sell5 / base_tp - 1.0,
            "zt_capped": bool(eff_sell5 < base_tp * (1.0 + slip) - 1e-6),
            "open_gt_trig": open_gt_trig,
            "is_zt_hit": bool(hit_zt),
            "is_zt_sealed": bool(seal_zt),
            "pulled_back": True,
        }

    # Fixed limit-price cap mode: cap = min(trig * (1 + cap_pct), zt_px)
    cap_px = min(base_tp * (1.0 + float(cap_pct)), zt_px)
    # Needs pullback if:
    #   (a) bar opened > cap_px (even if slow/med), OR
    #   (b) fast bar (+1.0%) and cap_px < eff_sell5 - 1e-6 (cap < +1.0%, and not physically capped at zt_px <= cap), OR
    #   (c) diagnostic force_pullback_if_fast=True (models >+1.0% real fast sweep even when cap=+1.0%)
    needs_pb = (o5 > cap_px + 1e-6) or (tier == "fast" and (eff_sell5 > cap_px + 1e-6 or force_pullback_if_fast))

    if not needs_pb:
        eff_cap = min(eff_sell5, cap_px)
        return {
            "status": "filled_intraday",
            "buy_hhmm": hh,
            "trig_px": round(base_tp, 4),
            "pre_slip_px": round(base_tp, 4),
            "eff_buy": round(eff_cap, 6),
            "vel_tier": tier,
            "nom_slip": slip,
            "real_slip": eff_cap / base_tp - 1.0,
            "zt_capped": bool(eff_cap >= zt_px - 1e-6),
            "open_gt_trig": open_gt_trig,
            "is_zt_hit": bool(hit_zt),
            "is_zt_sealed": bool(seal_zt),
            "pulled_back": True,
        }

    # Strict causal pullback check on bar hit_idx and subsequent bars <= cancel_hhmm
    # On hit_idx: if o5 < base_tp, bar low may have occurred BEFORE hitting base_tp;
    #   so only c5 <= cap_px (or o5 >= base_tp and l5 <= cap_px) proves post-trigger pullback on bar hit_idx.
    fill_hhmm = None
    if (c5 <= cap_px + 1e-6 and c5 < zt_px - 0.01) or (o5 >= base_tp - 1e-4 and l5 <= cap_px + 1e-6 and l5 < zt_px - 0.01):
        fill_hhmm = hh
    else:
        for bi in range(hit_idx + 1, len(arr_5m)):
            hh_j = int(arr_5m[bi, 0])
            if hh_j > cancel_hhmm:
                break
            lj = float(arr_5m[bi, 3])
            if lj <= cap_px + 1e-6 and lj < zt_px - 0.01:
                fill_hhmm = hh_j
                break

    if fill_hhmm is None:
        return {
            "status": "missed_cap",
            "buy_hhmm": hh,
            "trig_px": round(base_tp, 4),
            "vel_tier": tier,
            "eff_sell5": round(eff_sell5, 6),
            "cap_px": round(cap_px, 6),
            "open_gt_trig": open_gt_trig,
            "is_zt_hit": bool(hit_zt),
            "is_zt_sealed": bool(seal_zt),
            "pulled_back": False,
        }

    # If o5 > cap_px and filled via pullback, fill is cap_px; if o5 <= cap_px on fast pullback, fill is cap_px (not < eff_sell5 if cap=1%)
    eff_cap = min(cap_px, zt_px)
    return {
        "status": "filled_intraday",
        "buy_hhmm": fill_hhmm,
        "trig_px": round(base_tp, 4),
        "pre_slip_px": round(base_tp, 4),
        "eff_buy": round(eff_cap, 6),
        "vel_tier": tier,
        "nom_slip": eff_cap / base_tp - 1.0,
        "real_slip": eff_cap / base_tp - 1.0,
        "zt_capped": bool(eff_cap >= zt_px - 1e-6),
        "open_gt_trig": open_gt_trig,
        "is_zt_hit": bool(hit_zt),
        "is_zt_sealed": bool(seal_zt),
        "pulled_back": True,
    }


def build_daily_mtm_series(
    df_tr: pd.DataFrame,
    cal_dts: list[str],
    dt_to_idx: dict,
    dmap: dict,
    ret_col: str = "net_ret",
    buy_px_col: str = "eff_buy_price",
) -> tuple[np.ndarray, float]:
    T = len(cal_dts)
    day_mult = np.ones(T, dtype=float)
    if df_tr.empty:
        return np.zeros(T, dtype=float), 0.0
    for r in df_tr.itertuples(index=False):
        bi = dt_to_idx.get(str(r.buy_date)[:10])
        ei = dt_to_idx.get(str(r.exit_date)[:10])
        if bi is None:
            continue
        c6 = str(r.c6).zfill(6)
        bb = dmap.get((c6, str(r.buy_date)[:10]))
        bp = float(getattr(r, buy_px_col))
        b_adj = bp * bb["adjf"] if bb else bp
        if b_adj <= 0:
            b_adj = 1.0
        prev_v, last_c = b_adj, b_adj
        end_loop = ei if (ei is not None and ei > bi) else T
        for t in range(bi, end_loop):
            bt = dmap.get((c6, cal_dts[t]))
            cur_c = bt["adj_close"] if bt else last_c
            if cur_c <= 0:
                cur_c = last_c
            day_mult[t] *= (cur_c / prev_v)
            prev_v, last_c = cur_c, cur_c
        ret_v = float(getattr(r, ret_col))
        if ei is not None and ei > bi:
            day_mult[ei] *= (b_adj * (1.0 + ret_v)) / prev_v
    daily_r = day_mult - 1.0
    mtm_nav = float(np.prod(day_mult))
    tr_nav = float(np.prod(1.0 + df_tr[ret_col].to_numpy(float)))
    return daily_r, abs(mtm_nav - tr_nav)


def get_csi_ret(sh300: dict, all_sh_dts: list[str], sdt: str, edt: str) -> float:
    dts = [d for d in all_sh_dts if sdt <= d <= edt]
    if not dts:
        return 0.0
    prevs = [d for d in all_sh_dts if d < dts[0]]
    p0 = sh300[prevs[-1]] if prevs else sh300[dts[0]]
    return float((sh300[dts[-1]] / p0 - 1.0) * 100.0)


def calc_d15_window(
    df_tr: pd.DataFrame,
    daily_mtm_r: np.ndarray,
    cal_dts: list[str],
    dt_to_idx: dict,
    sh300: dict,
    all_sh_dts: list[str],
    sdt: str,
    edt: str,
    ret_col: str = "net_ret",
    pool_df: pd.DataFrame | None = None,
    pool_ret_col: str = "net_ret",
) -> dict:
    csi_pct = get_csi_ret(sh300, all_sh_dts, sdt, edt)
    sub = df_tr[(df_tr["buy_date"] >= sdt) & (df_tr["buy_date"] <= edt)] if not df_tr.empty else pd.DataFrame()
    win_idx = [dt_to_idx[d] for d in cal_dts if sdt <= d <= edt]
    dr = daily_mtm_r[win_idx] if win_idx else np.zeros(1)
    T = len(dr)

    mtm_nav = float(np.prod(1.0 + dr))
    cum_d = np.cumprod(1.0 + dr)
    pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
    daily_mdd = float(np.max((pk_d - cum_d) / pk_d) * 100.0) if T > 0 else 0.0
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if (T > 0 and mtm_nav > 0) else -100.0
    calmar = (cagr / daily_mdd) if daily_mdd > 1e-6 else 0.0

    eq_nav, eq_days = 1.0, 0
    if pool_df is not None and not pool_df.empty:
        sp = pool_df[(pool_df["buy_date"] >= sdt) & (pool_df["buy_date"] <= edt)]
        if not sp.empty:
            daily_eq_s = sp.groupby("buy_date", sort=True)[pool_ret_col].mean().to_numpy(float)
            eq_days = int(len(daily_eq_s))
            eq_nav = float(np.prod(1.0 + daily_eq_s))

    if sub.empty:
        return {
            "trades": 0, "win_rate_pct": 0.0, "plr": 0.0, "mean_ret_pct": 0.0,
            "nav_1s": 1.0, "ex_top3_nav": 1.0, "ex_top5_nav": 1.0,
            "trade_mdd_pct": 0.0, "daily_mtm_mdd_pct": sf(daily_mdd, 2),
            "daily_sharpe": sf(sharpe, 3), "daily_calmar": sf(calmar, 2),
            "eq_days_pool": eq_days, "eq_nav_pool": sf(eq_nav, 4),
            "csi300_pct": sf(csi_pct, 2),
            "excess_1s_pp": sf(-csi_pct, 2),
            "excess_eq_pp": sf((eq_nav - 1.0) * 100.0 - csi_pct, 2),
        }

    rets = sub[ret_col].to_numpy(float)
    w, l = rets[rets > 0], rets[rets < 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l)) else (99.0 if len(w) else 0.0)
    nav = float(np.prod(1.0 + rets))
    s_rets = np.sort(rets)
    ex3 = float(np.prod(1.0 + s_rets[:-3])) if len(rets) > 3 else 1.0
    ex5 = float(np.prod(1.0 + s_rets[:-5])) if len(rets) > 5 else 1.0
    cum_t = np.cumprod(1.0 + rets)
    pk_t = np.maximum.accumulate(np.insert(cum_t, 0, 1.0))[1:]
    trade_mdd = float(np.max((pk_t - cum_t) / pk_t) * 100.0)

    return {
        "trades": int(len(rets)),
        "win_rate_pct": sf(wr, 2),
        "plr": sf(plr, 2),
        "mean_ret_pct": sf(rets.mean() * 100.0, 2),
        "nav_1s": sf(nav, 4),
        "ex_top3_nav": sf(ex3, 4),
        "ex_top5_nav": sf(ex5, 4),
        "trade_mdd_pct": sf(trade_mdd, 2),
        "daily_mtm_mdd_pct": sf(daily_mdd, 2),
        "daily_sharpe": sf(sharpe, 3),
        "daily_calmar": sf(calmar, 2),
        "eq_days_pool": eq_days,
        "eq_nav_pool": sf(eq_nav, 4),
        "csi300_pct": sf(csi_pct, 2),
        "excess_1s_pp": sf((nav - 1.0) * 100.0 - csi_pct, 2),
        "excess_eq_pp": sf((eq_nav - 1.0) * 100.0 - csi_pct, 2),
    }


def calc_hlz_dsr(df_tr: pd.DataFrame, sh300: dict, all_sh_dts: list[str], ret_col: str = "net_ret", m_trials: int = 150) -> tuple[float, float]:
    n = len(df_tr)
    if n < 5:
        return 0.0, 0.0
    def _b(bd, ed):
        prevs = [d for d in all_sh_dts if d < bd]
        posts = [d for d in all_sh_dts if d <= ed]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_sh_dts[0]]
        return float(sh300[posts[-1]] / p0 - 1.0)
    ex = np.array([float(getattr(r, ret_col)) - _b(str(r.buy_date)[:10], str(r.exit_date)[:10]) for r in df_tr.itertuples(index=False)], float)
    sd = float(ex.std(ddof=1))
    if sd <= 1e-12:
        return 0.0, 0.0
    sr = float(ex.mean() / sd)
    t_val = sr * math.sqrt(n)
    sk = float(stats.skew(ex, bias=False)) if n > 2 else 0.0
    ku = max(1.0, float(stats.kurtosis(ex, fisher=False, bias=False))) if n > 3 else 3.0
    gm = 0.5772156649
    sr0 = (1.0 / math.sqrt(n - 1)) * ((1.0 - gm) * stats.norm.ppf(1.0 - 1.0 / m_trials) + gm * stats.norm.ppf(1.0 - 1.0 / (m_trials * math.e)))
    den = math.sqrt(max(1e-12, 1.0 - sk * sr + ((ku - 1.0) / 4.0) * (sr ** 2)))
    return sf(t_val, 2), sf(float(stats.norm.cdf((sr - sr0) * math.sqrt(n - 1) / den)), 4)


def calc_cscv_pbo_matrix(daily_r_map: dict[str, np.ndarray], base_name: str, cal_dts: list[str], df_map: dict[str, pd.DataFrame], ret_col: str = "net_ret") -> dict:
    """Compute CSCV PBO (S=8 and S=10) on BOTH daily MTM series and exit-date trade series."""
    names = list(daily_r_map.keys())
    R_mtm = np.column_stack([daily_r_map[nm] for nm in names])
    dt_to_idx = {d: i for i, d in enumerate(cal_dts)}
    cols_ed = []
    for nm in names:
        v = np.zeros(len(cal_dts), float)
        for r in df_map[nm].itertuples(index=False):
            i = dt_to_idx.get(str(r.exit_date)[:10])
            if i is not None:
                v[i] += float(getattr(r, ret_col))
        cols_ed.append(v)
    R_ed = np.column_stack(cols_ed)
    i_base = names.index(base_name)

    def _run_cscv(R: np.ndarray) -> dict:
        out = {}
        for S in (8, 10):
            gs = len(R) // S
            gidx = [list(range(i * gs, (i + 1) * gs if i < S - 1 else len(R))) for i in range(S)]
            omegas, beat_base = [], []
            win_cnt = {nm: 0 for nm in names}
            for te in itertools.combinations(range(S), S // 2):
                trg = [k for k in range(S) if k not in te]
                rt = R[[x for k in trg for x in gidx[k]]]
                re_ = R[[x for k in te for x in gidx[k]]]
                sdt, sde = rt.std(0, ddof=1), re_.std(0, ddof=1)
                st = np.divide(rt.mean(0), sdt, out=np.zeros_like(sdt), where=sdt > 1e-12)
                se = np.divide(re_.mean(0), sde, out=np.zeros_like(sde), where=sde > 1e-12)
                b = int(np.argmax(st))
                win_cnt[names[b]] += 1
                omegas.append(float(np.mean(se > se[b])))
                beat_base.append(bool(se[b] > se[i_base]))
            om_arr = np.array(omegas)
            out[f"S{S}"] = {
                "combinations": int(len(omegas)),
                "pbo_pct": sf(float(np.mean(om_arr > 0.50) * 100.0), 2),
                "mean_omega": sf(float(np.mean(om_arr)), 4),
                "is_winner_strictly_beats_current_oos_pct": sf(float(np.mean(beat_base) * 100.0), 2),
                "is_winners": {k: v for k, v in win_cnt.items() if v > 0},
            }
        return out

    return {
        "daily_mtm_cscv": _run_cscv(R_mtm),
        "exit_date_cscv": _run_cscv(R_ed),
    }


def evaluate_variant_d15(
    df_slot: pd.DataFrame,
    df_pool: pd.DataFrame,
    exec_stats: dict,
    cal_5y: list[str],
    dt_idx_5y: dict,
    sh300: dict,
    all_sh_dts: list[str],
    dmap: dict,
    ret_col: str = "net_ret",
    buy_px_col: str = "eff_buy_price",
) -> tuple[dict, np.ndarray]:
    dr, mtm_diff = build_daily_mtm_series(df_slot, cal_5y, dt_idx_5y, dmap, ret_col=ret_col, buy_px_col=buy_px_col)
    assert mtm_diff < 1e-3, f"MTM diff {mtm_diff}"
    wins = {
        wn: calc_d15_window(df_slot, dr, cal_5y, dt_idx_5y, sh300, all_sh_dts, sd, ed, ret_col, df_pool, ret_col)
        for wn, sd, ed in CANON_WINDOWS
    }
    hlz_t, dsr = calc_hlz_dsr(df_slot, sh300, all_sh_dts, ret_col=ret_col, m_trials=150)
    return {
        "execution_stats": exec_stats,
        "hlz_t": hlz_t,
        "dsr_m150": dsr,
        "windows": wins,
    }, dr

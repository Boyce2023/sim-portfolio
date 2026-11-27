#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD049 Shared Core: 2D State Machine, Dynamic Thresholds, Exact 1x & 1.5x Margin Simulators."""
import math
import os
import resource
import sys
import warnings

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"

if RD038 not in sys.path:
    sys.path.insert(0, RD038)
import _rd038_engine as eng

TRD_DAYS_YEAR = 242.0
WF_START = "2023-01-03"
WF_END = "2026-11-16"

CFG_V20 = {
    "s20": "base_76", "s34": "base", "s23": "base", "shi": "base",
    "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only",
}
CFG_V21 = {
    "s20": "stack_c50_avg", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15", "shi": "m1_causal_cold_drop40_t0",
    "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only",
}


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def build_2d_states(reg: pd.DataFrame, y_cut: float = 42.0, x_sh: float = 20.0, x_dp: float = 42.0) -> pd.DataFrame:
    """
    Construct pure causal T-1 2D Risk State Machine with zero future leakage:
      - Dimension X (Macro Breakdown Slope Stress in [0, 100])
      - Dimension Y (High-Board Infighting Micro Temperature in [0, 100])
      - Non-linear union R_union = 100 * (1 - (1 - X/100) * (1 - Y/100))
      - 5-Tier Physical Traffic Light (L1_纯绿畅通 .. L5_红灯地板)
    """
    df = reg.copy()
    x_ma20 = np.clip((-1.0 - df["gz_vs_ma20_t1"].fillna(0.0)) / 5.5, 0.0, 1.0)
    x_dd20 = np.clip((-3.0 - df["gz_dd20_t1"].fillna(0.0)) / 8.5, 0.0, 1.0)
    x_r5 = np.clip((-1.5 - df["gz_r5_t1"].fillna(0.0)) / 5.5, 0.0, 1.0)
    x_r10 = np.clip((-2.0 - df["gz_r10_t1"].fillna(0.0)) / 7.5, 0.0, 1.0)
    x_med5 = np.clip((-1.5 - df["alla_med_r5_t1"].fillna(0.0)) / 5.0, 0.0, 1.0)
    df["X_score"] = (0.25 * x_ma20 + 0.25 * x_dd20 + 0.20 * x_r5 + 0.15 * x_r10 + 0.15 * x_med5) * 100.0

    y_prm = np.clip((0.40 - df["hb2_promo_t1"].fillna(0.40)) / 0.22, 0.0, 1.0)
    y_dbm = np.clip((df["L1_duanban_damian_t1"].fillna(15.0) - 15.0) / 25.0, 0.0, 1.0)
    y_pb = np.clip((-2.0 - df["pb_hb2_fail_open_t1"].fillna(-2.0)) / 4.0, 0.0, 1.0)
    y_zb = np.clip((df["zb_rate_t1"].fillna(30.0) - 30.0) / 16.0, 0.0, 1.0)
    y_dt = np.clip((df["dt_cnt_t1"].fillna(5.0) - 5.0) / 15.0, 0.0, 1.0)
    df["Y_score"] = (0.20 * y_prm + 0.20 * y_dbm + 0.20 * y_pb + 0.20 * y_zb + 0.20 * y_dt) * 100.0

    df["is_red_floor"] = (
        (df["gz_dd20_t1"] <= -13.5) | (df["gz_r10_t1"] <= -11.5) | (df["gz_r5_t1"] <= -8.5)
    ).fillna(False)

    df["R_lin"] = 0.55 * df["X_score"] + 0.45 * df["Y_score"]
    df["R_union"] = 100.0 * (1.0 - (1.0 - df["X_score"] / 100.0) * (1.0 - df["Y_score"] / 100.0))

    def _cls(r):
        if r["is_red_floor"]:
            return "L5_红灯地板"
        if r["X_score"] >= x_dp:
            return "L4_深黄主跌"
        if r["X_score"] >= x_sh:
            return "L3_浅黄预警"
        if r["Y_score"] >= y_cut:
            return "L2_绿灯内杀"
        return "L1_纯绿畅通"

    df["light_5"] = df.apply(_cls, axis=1)
    return df


def apply_rd049_filter(
    cache: dict,
    reg_idx: pd.DataFrame,
    mode: str = "base",
    d_l4: float = 12.0,
    d_l3: float = 9.0,
    d_l2: float = 9.0,
    af03_weak: bool = False,
    af03_all: bool = False,
    pry_cold: bool = False,
    r0: float = 38.0,
    rk: float = 12.0,
    raf: float = 45.0,
    hh_cut: int = 1030,
    s34_925_weak: bool = False,
    b5_info: dict | None = None,
    honest_delay935: bool = False,
    de_singleton: bool = False,
) -> dict:
    """Return a clean shallow-copied cache with RD049 pre-market causal filters applied."""
    c2 = {**cache, "pools_ext": {k: v.copy() for k, v in cache["pools_ext"].items()}}
    d34 = c2["pools_ext"]["3to4"]

    if de_singleton:
        m_ds = ((d34["buy_date"] == "2025-01-03") & (d34["code"] == "600778")) | (
            (d34["buy_date"] == "2024-12-23") & (d34["code"] == "603421")
        )
        d34.loc[m_ds, "can_buy_hygiene"] = False

    keep = d34["can_buy_hygiene"].to_numpy(bool).copy()
    sc = d34["orig_score"].to_numpy(float)
    dts = d34["buy_date"].astype(str).str[:10].tolist()
    lmap = reg_idx["light_5"].to_dict()
    rumap = reg_idx["R_union"].to_dict()
    redmap = reg_idx["is_red_floor"].to_dict()

    l5s = np.array([lmap.get(d, "L1_纯绿畅通") for d in dts])
    rus = np.array([rumap.get(d, 0.0) for d in dts])
    reds = np.array([redmap.get(d, False) for d in dts])
    weak_m = np.isin(l5s, ["L2_绿灯内杀", "L3_浅黄预警", "L4_深黄主跌"])

    if mode == "tier":
        deltas = np.where(
            l5s == "L4_深黄主跌", d_l4,
            np.where(l5s == "L3_浅黄预警", d_l3, np.where(l5s == "L2_绿灯内杀", d_l2, 0.0)),
        )
        keep &= (sc >= 90.0 + deltas)
        if af03_weak:
            keep &= (~weak_m) | (d34["s34_af_03"].to_numpy(float) == 4.0)
    elif mode == "runion":
        deltas = np.where(~reds, rk * np.clip((rus - r0) / 35.0, 0.0, 1.0), 0.0)
        keep &= (sc >= 90.0 + deltas)
        if af03_weak:
            wm_r = (~reds) & (rus >= raf)
            keep &= (~wm_r) | (d34["s34_af_03"].to_numpy(float) == 4.0)
    elif mode == "skip_yellow":
        keep &= ~np.isin(l5s, ["L3_浅黄预警", "L4_深黄主跌"])
    elif mode == "skip_l2l3l4":
        keep &= ~weak_m
    elif mode == "base" and af03_weak:
        keep &= (~weak_m) | (d34["s34_af_03"].to_numpy(float) == 4.0)

    if af03_all:
        keep &= (d34["s34_af_03"].to_numpy(float) == 4.0)
    if s34_925_weak:
        keep &= (~weak_m) | (d34["buy_hhmm"].to_numpy(int) == 925)
    if hh_cut < 1030:
        keep &= (d34["buy_hhmm"].to_numpy(int) <= hh_cut)

    if honest_delay935 and b5_info is not None:
        bhs = d34["buy_hhmm"].to_numpy(int)
        codes = d34["code"].astype(str).str.zfill(6).tolist()
        n_rets = d34["net_ret_030"].to_numpy(float).copy()
        mtms = list(d34["mtm_5y_030"])
        for i in range(len(d34)):
            if not keep[i] or bhs[i] != 935:
                continue
            info = b5_info.get((dts[i], codes[i]))
            if info is None:
                continue
            if info["red935"] or info["sealed_940"]:
                keep[i] = False
            else:
                old_px = float(d34.iloc[i]["buy_price"]) if pd.notna(d34.iloc[i]["buy_price"]) else info["o940"]
                new_px = info["o940"]
                if old_px > 0 and new_px > 0:
                    n_rets[i] = (1.0 + n_rets[i]) * (old_px / new_px) - 1.0
                    segs = list(mtms[i])
                    if segs:
                        segs[0] = (segs[0][0], segs[0][1] * (old_px / new_px))
                        mtms[i] = tuple(segs)
        d34["net_ret_030"] = n_rets
        d34["mtm_5y_030"] = mtms

    d34["can_buy_hygiene"] = keep

    if pry_cold:
        dp = c2["pools_ext"]["pry"]
        dp["can_buy_hygiene"] = dp["can_buy_hygiene"].to_numpy(bool) & (dp["mkt10_zt_est_t1"].to_numpy(float) >= 50.0)
    return c2


def compute_window_metrics(dr_5y: np.ndarray, tr_df: pd.DataFrame, cal_5y: list[str], sdt: str, edt: str, sizing_arr: np.ndarray | None = None) -> dict:
    dr_use = dr_5y if sizing_arr is None else (dr_5y * sizing_arr)
    pos = [i for i, d in enumerate(cal_5y) if sdt <= d <= edt]
    if not pos:
        return {}
    ds = dr_use[pos]
    T = len(ds)
    nav = float(np.prod(1.0 + ds))
    cv = np.concatenate([[1.0], np.cumprod(1.0 + ds)])
    pk = np.maximum.accumulate(cv)
    mdd = float(np.max((pk - cv) / pk) * 100.0)
    sd = float(np.std(ds, ddof=1)) if T > 1 else 0.0
    sh = float(np.mean(ds) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if nav > 0 else -100.0
    calmar = (cagr / mdd) if mdd > 1e-6 else 0.0
    sub = tr_df[tr_df["buy_date"].between(sdt, edt)] if not tr_df.empty else tr_df
    rets = sub["net_ret"].to_numpy(float) if not sub.empty else np.array([])
    wr = float((rets > 0).mean() * 100.0) if len(rets) else 0.0
    w, l = rets[rets > 0], rets[rets <= 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else 0.0
    return {
        "n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2) if len(rets) else 0.0,
        "nav": round(nav, 4),
        "mdd_pct": round(mdd, 2),
        "sharpe": round(sh, 3),
        "calmar": round(calmar, 2),
        "cagr_pct": round(cagr, 2),
    }


def preload_low_bars_for_trades(trades_dfs: list[pd.DataFrame], cal_5y: list[str]) -> dict:
    """Load exact daily (low_adj, open_adj, close_adj, adjf) for all holding windows of target ledgers."""
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    T = len(cal_5y)
    needed_pairs = set()
    needed_codes = set()
    for df in trades_dfs:
        if df is None or df.empty:
            continue
        for r in df[["code", "buy_date", "exit_date"]].itertuples(index=False):
            c = str(r.code).zfill(6)
            bi = idx_5y.get(str(r.buy_date)[:10])
            ei = idx_5y.get(str(r.exit_date)[:10])
            if bi is None:
                continue
            ei_use = ei if (ei is not None and ei >= bi) else (T - 1)
            needed_codes.add(c)
            for t in range(bi, min(ei_use + 1, T)):
                needed_pairs.add((c, cal_5y[t]))

    tks = sorted({f"{c}.SH" for c in needed_codes} | {f"{c}.SZ" for c in needed_codes})
    cols = ["date", "ticker", "open", "low", "close", "adj_close"]
    flt = (ds.field("date") >= pd.Timestamp("2021-11-01")) & (ds.field("date") <= pd.Timestamp("2026-11-25")) & ds.field("ticker").isin(tks)
    bar_lu = {}
    for ppath, dl_flag in [(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", 0), (f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", 1)]:
        scanner = ds.dataset(ppath).scanner(columns=cols, filter=flt, batch_size=65536)
        for batch in scanner.to_batches():
            dfb = batch.to_pandas()
            if dfb.empty:
                continue
            c6s = dfb["ticker"].astype(str).str[:6]
            dts = pd.to_datetime(dfb["date"]).dt.strftime("%Y-%m-%d")
            keep = [((c, d) in needed_pairs) for c, d in zip(c6s, dts)]
            if not any(keep):
                continue
            sub = dfb.loc[keep]
            for c, d, op, lo, cl, acl in zip(c6s.loc[keep], dts.loc[keep], sub["open"], sub["low"], sub["close"], sub["adj_close"]):
                k = (c, d)
                if dl_flag == 0 or k not in bar_lu:
                    adjf = (float(acl) / float(cl)) if (cl > 0 and acl > 0) else 1.0
                    bar_lu[k] = (float(op) * adjf, float(lo) * adjf, float(cl) * adjf, adjf)
    return bar_lu


def simulate_margin_15x(
    sim_res: dict,
    cal_5y: list[str],
    bar_low_lu: dict,
    f5_low_lu: dict,
    elig_map: dict,
    mode: str = "15x_theo_full",
    annual_rate: float = 0.055,
) -> dict:
    """
    Simulate 1.5x margin trading with:
      - 5.5% annual financing cost charged by actual holding calendar days, debt reset to 0 on exit
      - 0.30% round-trip slippage already included in net_ret (scales with leverage)
      - Daily intraday-LOW Maintenance Margin Ratio (MMR = Total Asset / Debt, init=300%, warn=150%, liq=130%)
      - mode='15x_theo_full': all trades at 1.5x
      - mode='15x_elig_only': only T-1 official SSE/SZSE margin-eligible trades at 1.5x, others at 1.0x cash
    """
    tr_df = sim_res["trades_df"]
    idx_5y = {d: i for i, d in enumerate(cal_5y)}
    T = len(cal_5y)
    day_mult_lev = np.ones(T, dtype=float)

    mmr_records = []
    n_elig = 0
    lev_sum = 0.0

    for r in tr_df.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        bi = idx_5y.get(bd)
        ei = idx_5y.get(ed)
        is_elig = bool(elig_map.get(f"{c6}|{bd}", False))
        if is_elig:
            n_elig += 1
        L = 1.5 if (mode == "15x_theo_full" or (mode == "15x_elig_only" and is_elig)) else 1.0
        lev_sum += L

        cal_days = max(1, (pd.Timestamp(ed) - pd.Timestamp(bd)).days)
        interest_tot = (L - 1.0) * annual_rate * (cal_days / 365.0)
        net_ret_1x = float(r.net_ret)
        net_ret_L = L * net_ret_1x - interest_tot

        # Daily MTM equity path during [bi .. ei] starting from E=1.0
        segs = getattr(r, "mtm_use", None)
        if bi is not None and ei is not None and ei > bi:
            if segs:
                # Reconstruct cumulative 1x value V_t at each day in [bi..ei]
                v_curr = 1.0
                e_prev = 1.0
                for step_k, (ti, mult1x) in enumerate(segs):
                    if not (0 <= int(ti) < T):
                        continue
                    v_curr *= float(mult1x)
                    dt_t = cal_5y[int(ti)]
                    cd_t = max(0, (pd.Timestamp(dt_t) - pd.Timestamp(bd)).days)
                    int_t = (L - 1.0) * annual_rate * (cd_t / 365.0)
                    if int(ti) == ei:
                        e_curr = max(1e-6, 1.0 + net_ret_L)
                    else:
                        # Unlevered closing value -> leveraged equity
                        e_curr = max(1e-6, 1.0 + L * (v_curr - 1.0) - int_t)
                    day_mult_lev[int(ti)] *= (e_curr / e_prev)
                    e_prev = e_curr
            else:
                span = ei - bi + 1
                g = (1.0 + max(-0.99, net_ret_L)) ** (1.0 / span)
                day_mult_lev[bi : ei + 1] *= g

        # Exact Intraday LOW MMR check on every holding day (only when L > 1.0)
        if L > 1.0 and bi is not None and ei is not None:
            bb = bar_low_lu.get((c6, bd))
            if pd.notna(getattr(r, "buy_price_val", np.nan)) and bb is not None:
                b_adj = float(r.buy_price_val) * bb[3]
            elif bb is not None:
                # Fallback from close & net_ret or open
                b_adj = bb[0]
            else:
                b_adj = np.nan

            if np.isfinite(b_adj) and b_adj > 0:
                min_mmr_trade = 999.0
                min_mmr_dt = bd
                bh = int(getattr(r, "buy_hhmm", 925))
                eh = int(getattr(r, "exit_hhmm", 1500))
                for t in range(bi, min(ei + 1, T)):
                    dt_t = cal_5y[t]
                    bt = bar_low_lu.get((c6, dt_t))
                    if bt is None:
                        continue
                    # Determine intraday low price after entry / before exit
                    if t == bi and bh > 925:
                        low_raw_5m = f5_low_lu.get((c6, dt_t, "after", bh))
                        low_adj = (low_raw_5m * bt[3]) if low_raw_5m is not None else bt[1]
                    elif t == ei and eh <= 930:
                        low_adj = bt[0]  # exited at 09:25 open auction
                    elif t == ei and eh < 1500:
                        low_raw_5m = f5_low_lu.get((c6, dt_t, "before", eh))
                        low_adj = (low_raw_5m * bt[3]) if low_raw_5m is not None else bt[1]
                    else:
                        low_adj = bt[1]

                    asset_low = L * (low_adj / b_adj)
                    cd_t = max(1, (pd.Timestamp(dt_t) - pd.Timestamp(bd)).days)
                    debt_t = (L - 1.0) * (1.0 + annual_rate * (cd_t / 365.0))
                    mmr_t = (asset_low / debt_t) * 100.0 if debt_t > 0 else 999.0
                    if mmr_t < min_mmr_trade:
                        min_mmr_trade = mmr_t
                        min_mmr_dt = dt_t
                mmr_records.append({
                    "buy_date": bd, "exit_date": ed, "code": c6, "name": r.name,
                    "strategy": r.strategy, "net_ret_1x_pct": round(net_ret_1x * 100, 2),
                    "net_ret_lev_pct": round(net_ret_L * 100, 2),
                    "min_mmr_pct": round(min_mmr_trade, 2), "min_mmr_dt": min_mmr_dt,
                })

    dr_lev = day_mult_lev - 1.0
    mmr_df = pd.DataFrame(mmr_records)
    min_mmr_overall = float(mmr_df["min_mmr_pct"].min()) if not mmr_df.empty else 999.0
    n_warn_150 = int((mmr_df["min_mmr_pct"] < 150.0).sum()) if not mmr_df.empty else 0
    n_liq_130 = int((mmr_df["min_mmr_pct"] < 130.0).sum()) if not mmr_df.empty else 0
    worst_mmr_row = mmr_df.sort_values("min_mmr_pct").iloc[0].to_dict() if not mmr_df.empty else {}

    def _w(s, e):
        pos = [i for i, d in enumerate(cal_5y) if s <= d <= e]
        ds_w = dr_lev[pos]
        T_w = len(ds_w)
        nav = float(np.prod(1.0 + ds_w))
        cv = np.concatenate([[1.0], np.cumprod(1.0 + ds_w)])
        pk = np.maximum.accumulate(cv)
        mdd = float(np.max((pk - cv) / pk) * 100.0)
        sd = float(np.std(ds_w, ddof=1)) if T_w > 1 else 0.0
        sh = float(np.mean(ds_w) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
        cagr = (nav ** (TRD_DAYS_YEAR / T_w) - 1.0) * 100.0 if nav > 0 else -100.0
        calmar = (cagr / mdd) if mdd > 1e-6 else 0.0
        return {"nav": round(nav, 4), "mdd_pct": round(mdd, 2), "sharpe": round(sh, 3), "calmar": round(calmar, 2), "cagr_pct": round(cagr, 2)}

    return {
        "mode": mode,
        "n_trades": int(len(tr_df)),
        "n_eligible": int(n_elig),
        "elig_pct": round(n_elig / max(1, len(tr_df)) * 100.0, 2),
        "avg_eff_leverage": round(lev_sum / max(1, len(tr_df)), 3),
        "min_mmr_pct": round(min_mmr_overall, 2),
        "n_warn_below_150": n_warn_150,
        "n_liq_below_130": n_liq_130,
        "worst_mmr_trade": worst_mmr_row,
        "windows": {
            "FULL_5Y": _w("2021-11-16", "2026-11-16"),
            "Y3_2426": _w("2024-01-01", "2026-11-16"),
            "WF_2326": _w("2023-01-03", "2026-11-16"),
            "Y2026": _w("2026-01-01", "2026-11-16"),
        },
        "dr_lev": dr_lev,
        "mmr_df": mmr_df,
    }

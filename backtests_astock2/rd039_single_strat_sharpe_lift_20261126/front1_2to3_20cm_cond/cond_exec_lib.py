#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD039-A Front 1 Library:
  - Strict 5m intraday conditional order execution engine (zero lookahead)
  - 3-tier velocity slippage (0% / +0.5% / +1.0%, zt_px capped) + 30/50/80bps fee tiers
  - Strict ZT-lock & ZT-near踏空 handling + sealed-ZT-bar stress diagnostics
  - Multi-candidate selection (`rank1_only` vs `first_touch_prio`)
  - Exact daily bar MTM (`mtm_diff == 0.0`), D15 metrics, Paired-t, 1000x Perm, CSCV PBO
"""
import itertools
import math
import os
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

TRD_DAYS_YEAR = 242.0


def _round2(x: float) -> float:
    return float(math.floor(float(x) * 100.0 + 0.5 + 1e-9) / 100.0)


def simulate_bar_execution(
    arr_5m: Optional[np.ndarray],
    open_d: float,
    pre_c: float,
    zt_px: float,
    open_pct: float,
    kind: str,
    cancel_hhmm: int,
    param: dict | float | None = None,
) -> dict:
    """
    Simulate strict chronological 5m conditional order execution.
    Returns dict with status in:
      'filled_0925' | 'filled_intraday' | 'missed_zt' | 'untriggered' | 'missing_5m'
    """
    if kind == "auc_0925":
        return {
            "status": "filled_0925",
            "buy_hhmm": 925,
            "trig_px": round(open_d, 4),
            "fill_base": round(open_d, 4),
            "eff_buy_vel": round(open_d, 6),
            "eff_buy_flat": round(open_d, 6),
            "vel_tier": "auction_0925",
            "nom_slip": 0.0,
            "real_slip": 0.0,
            "is_zt_hit_bar": False,
            "is_zt_sealed_bar": False,
            "strict_seal_missed": False,
        }

    if open_d <= 0 or pre_c <= 0 or zt_px <= 0 or open_d >= zt_px - 0.005:
        return {"status": "missed_zt", "reason": "open_at_zt"}

    if arr_5m is None or len(arr_5m) == 0:
        return {"status": "missing_5m", "reason": "no_5m"}

    # Determine causal trigger price & start bar hhmm
    start_hhmm = 935
    allow_0925 = False
    direct_0925 = False
    trig_px = np.nan

    if kind == "open_mult":
        trig_px = _round2(open_d * float(param))
    elif kind == "prev_close_mult":
        p = param if isinstance(param, dict) else {"pc_mult": float(param)}
        trig_px = _round2(pre_c * float(p.get("pc_mult", 1.0)))
        allow_0925 = bool(p.get("allow_0925", True))
        op_floor = p.get("op_floor", None)
        if op_floor is not None:
            trig_px = max(trig_px, _round2(open_d * float(op_floor)))
    elif kind == "brk_5m_hi":
        p = param if isinstance(param, dict) else {}
        pad = float(p.get("pad", 0.01))
        b935 = arr_5m[arr_5m[:, 0] == 935]
        if len(b935) == 0:
            return {"status": "untriggered", "reason": "no_935_bar"}
        if float(b935[0, 3]) >= zt_px - 0.01:
            return {"status": "missed_zt", "reason": "935_locked_zt"}
        trig_px = _round2(float(b935[0, 2]) + pad)
        start_hhmm = 940
    elif kind == "brk_10m_hi":
        p = param if isinstance(param, dict) else {}
        pad = float(p.get("pad", 0.01))
        b10 = arr_5m[(arr_5m[:, 0] >= 935) & (arr_5m[:, 0] <= 940)]
        if len(b10) < 2:
            return {"status": "untriggered", "reason": "no_10m_bars"}
        if float(b10[-1, 3]) >= zt_px - 0.01:
            return {"status": "missed_zt", "reason": "10m_locked_zt"}
        trig_px = _round2(float(np.max(b10[:, 2])) + pad)
        start_hhmm = 945
    elif kind == "hybrid_23":
        mode = str(param)
        if mode == "lowFH_hi0925":
            if open_pct < 0.0:
                trig_px = _round2(pre_c)
            else:
                direct_0925 = True
        elif mode == "lowFH_hiOp10":
            trig_px = _round2(pre_c) if open_pct < 0.0 else _round2(open_d * 1.010)
        elif mode == "lowOp20_hiOp10":
            trig_px = _round2(open_d * 1.020) if open_pct < 0.0 else _round2(open_d * 1.010)
        elif mode == "lowOp20_hi0925":
            if open_pct < 0.0:
                trig_px = _round2(open_d * 1.020)
            else:
                direct_0925 = True
        elif mode == "deepFH_midOp15_hiOp05":
            if open_pct < -0.02:
                trig_px = _round2(pre_c)
            elif open_pct < 0.0:
                trig_px = _round2(open_d * 1.015)
            else:
                trig_px = _round2(open_d * 1.005)
        else:
            raise ValueError(f"Unknown hybrid_23 mode: {mode}")
    elif kind == "hybrid_20":
        mode = str(param)
        if mode == "deepOp30_shOp15":
            trig_px = _round2(open_d * (1.030 if open_pct <= -0.06 else 1.015))
        elif mode == "deepOp40_shOp20":
            trig_px = _round2(open_d * (1.040 if open_pct <= -0.06 else 1.020))
        elif mode == "deepFH_shOp20":
            trig_px = _round2(pre_c) if open_pct <= -0.06 else _round2(open_d * 1.020)
        elif mode == "deepOp30_shBrk5m":
            if open_pct <= -0.06:
                trig_px = _round2(open_d * 1.030)
            else:
                b935 = arr_5m[arr_5m[:, 0] == 935]
                if len(b935) == 0:
                    return {"status": "untriggered", "reason": "no_935_bar"}
                trig_px = _round2(float(b935[0, 2]) + 0.01)
                start_hhmm = 940
        else:
            raise ValueError(f"Unknown hybrid_20 mode: {mode}")
    else:
        raise ValueError(f"Unknown trigger kind: {kind}")

    if direct_0925 or (allow_0925 and open_d >= trig_px - 1e-6):
        return {
            "status": "filled_0925",
            "buy_hhmm": 925,
            "trig_px": round(open_d, 4),
            "fill_base": round(open_d, 4),
            "eff_buy_vel": round(open_d, 6),
            "eff_buy_flat": round(open_d, 6),
            "vel_tier": "auction_0925",
            "nom_slip": 0.0,
            "real_slip": 0.0,
            "is_zt_hit_bar": False,
            "is_zt_sealed_bar": False,
            "strict_seal_missed": False,
        }

    if cancel_hhmm < start_hhmm:
        return {"status": "untriggered", "reason": "cancel_before_start"}

    zt_near = zt_px * 0.999
    if trig_px >= zt_px - 0.005:
        return {"status": "missed_zt", "reason": "trig_at_zt"}

    # Scan chronologically from start_hhmm to cancel_hhmm
    hit_idx = None
    saw_locked_zt_before_fill = False
    for bi in range(len(arr_5m)):
        hh = int(arr_5m[bi, 0])
        if hh < start_hhmm:
            continue
        if hh > cancel_hhmm:
            break
        o5, h5, l5, c5 = float(arr_5m[bi, 1]), float(arr_5m[bi, 2]), float(arr_5m[bi, 3]), float(arr_5m[bi, 4])
        if l5 >= zt_px - 0.01:
            if h5 >= trig_px - 1e-6:
                saw_locked_zt_before_fill = True
            continue  # Locked ZT bar, unbuyable
        if h5 >= trig_px - 1e-6:
            # Check if trigger/open is >= zt_px - 0.1% and sealed without subsequent open-board fill
            fb_tmp = _round2(max(trig_px, o5))
            if fb_tmp >= zt_near - 1e-6 and c5 >= zt_px - 0.01:
                saw_locked_zt_before_fill = True
                continue
            hit_idx = bi
            break

    if hit_idx is None:
        if saw_locked_zt_before_fill:
            return {"status": "missed_zt", "reason": "locked_zt_no_reopen"}
        return {"status": "untriggered", "reason": "no_touch"}

    hh = int(arr_5m[hit_idx, 0])
    o5, h5, l5, c5 = float(arr_5m[hit_idx, 1]), float(arr_5m[hit_idx, 2]), float(arr_5m[hit_idx, 3]), float(arr_5m[hit_idx, 4])
    fill_base = _round2(max(trig_px, o5))

    if fill_base >= zt_px - 0.005:
        return {"status": "missed_zt", "reason": "fill_base_at_zt"}

    # Velocity slippage (strictly aligned with slippage_velocity_audit_20261125)
    surge = (h5 - fill_base) / fill_base
    jump = (h5 - o5) / pre_c
    hit_zt = bool(h5 >= zt_px - 0.01)
    seal_zt = bool(hit_zt and (c5 >= zt_px - 0.01))

    if hit_zt or surge >= 0.025 or jump >= 0.040:
        tier, slip = "fast", 0.010
    elif surge >= 0.010 or jump >= 0.020:
        tier, slip = "medium", 0.005
    else:
        tier, slip = "slow", 0.000

    eff_buy_vel = min(max(o5, fill_base * (1.0 + slip)), zt_px)

    # Strict ZT-near miss check if eff_buy_vel >= zt_near and bar sealed without later reopen
    reopens_later = False
    if seal_zt:
        for bj in range(hit_idx + 1, len(arr_5m)):
            if int(arr_5m[bj, 0]) > cancel_hhmm:
                break
            if float(arr_5m[bj, 3]) < zt_px - 0.01:
                reopens_later = True
                break

    if fill_base >= zt_near - 1e-6 and seal_zt and not reopens_later:
        return {"status": "missed_zt", "reason": "trig_near_zt_sealed"}

    strict_seal_missed = bool(seal_zt and not reopens_later)
    return {
        "status": "filled_intraday",
        "buy_hhmm": hh,
        "trig_px": round(trig_px, 4),
        "fill_base": round(fill_base, 4),
        "eff_buy_vel": round(eff_buy_vel, 6),
        "eff_buy_flat": round(fill_base, 6),
        "vel_tier": tier,
        "nom_slip": slip,
        "real_slip": eff_buy_vel / fill_base - 1.0,
        "is_zt_hit_bar": hit_zt,
        "is_zt_sealed_bar": seal_zt,
        "strict_seal_missed": strict_seal_missed,
    }


def build_exact_daily_mtm(
    slot_df: pd.DataFrame,
    cal_dts: list[str],
    dmap: dict,
    ret_col: str,
    buy_px_raw_col: str = "eff_buy_vel",
) -> tuple[np.ndarray, float]:
    T = len(cal_dts)
    if slot_df.empty:
        return np.zeros(T, dtype=float), 0.0
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    day_mult = np.ones(T, dtype=float)
    for r in slot_df.itertuples(index=False):
        bd = str(r.buy_date)[:10]
        ed = str(r.exit_date)[:10]
        bi = dt_idx.get(bd)
        ei = dt_idx.get(ed)
        if bi is None:
            continue
        c6 = str(r.code).zfill(6)
        bb = dmap.get((c6, bd))
        bp_raw = float(getattr(r, buy_px_raw_col))
        adjf_b = bb["adjf"] if bb else 1.0
        b_adj = bp_raw * adjf_b
        if b_adj <= 0:
            b_adj = 1.0
        prev_v, last_c = b_adj, b_adj
        end_loop = ei if (ei is not None and ei > bi) else T
        for t in range(bi, end_loop):
            bt = dmap.get((c6, cal_dts[t]))
            cur_c = bt["adj_close"] if (bt and bt["adj_close"] > 0) else last_c
            day_mult[t] *= (cur_c / prev_v)
            prev_v, last_c = cur_c, cur_c
        ret_v = float(getattr(r, ret_col))
        if ei is not None and ei > bi:
            day_mult[ei] *= (b_adj * (1.0 + ret_v)) / prev_v
    dr = day_mult - 1.0
    tr_sub = slot_df[slot_df["buy_date"].isin(dt_idx)]
    tr_nav = float(np.prod(1.0 + tr_sub[ret_col].to_numpy(float))) if not tr_sub.empty else 1.0
    return dr, abs(float(np.prod(day_mult)) - tr_nav)


def calc_window_metrics(
    slot_df: pd.DataFrame,
    dr_full: np.ndarray,
    cal_dts: list[str],
    dt_idx: dict[str, int],
    csi_arr: np.ndarray,
    ew_arr: np.ndarray,
    sdt: str,
    edt: str,
    ret_col: str = "net_ret_vel_30",
) -> dict:
    win_pos = [dt_idx[d] for d in cal_dts if sdt <= d <= edt]
    T = len(win_pos)
    if T == 0:
        return {"n": 0, "nav": 1.0, "sharpe": 0.0, "mdd_pct": 0.0}
    dr = dr_full[win_pos]
    csi_pct = (float(np.prod(1.0 + csi_arr[win_pos])) - 1.0) * 100.0
    ew_pct = (float(np.prod(1.0 + ew_arr[win_pos])) - 1.0) * 100.0

    mtm_nav = float(np.prod(1.0 + dr))
    curve = np.concatenate([[1.0], np.cumprod(1.0 + dr)])
    pk = np.maximum.accumulate(curve)
    mdd = float(np.max((pk - curve) / pk) * 100.0)
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if mtm_nav > 0 else -100.0
    calmar = (cagr / mdd) if mdd > 1e-6 else 0.0

    sub = slot_df[slot_df["buy_date"].between(sdt, edt)] if not slot_df.empty else pd.DataFrame()
    if sub.empty:
        return {
            "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav": 1.0, "ex3_nav": 1.0, "ex5_nav": 1.0,
            "mdd_pct": round(mdd, 2), "sharpe": round(sharpe, 3), "calmar": round(calmar, 2),
            "big_loss_m7_pct": 0.0, "big_loss_m7_cnt": 0,
            "excess_csi300_pp": round(-csi_pct, 2), "excess_ew_pp": round(-ew_pct, 2),
            "pct_0935plus": 0.0, "avg_slip_bps": 0.0,
        }

    rets = sub[ret_col].to_numpy(float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    nav = float(np.prod(1.0 + rets))
    sr = np.sort(rets)
    ex3 = float(np.prod(1.0 + sr[:-3])) if len(rets) > 3 else 1.0
    ex5 = float(np.prod(1.0 + sr[:-5])) if len(rets) > 5 else 1.0
    bl_cnt = int(np.sum(rets <= -0.07))
    bl_pct = float(bl_cnt / len(rets) * 100.0)
    pct_intraday = float((sub["buy_hhmm"].to_numpy(int) >= 935).mean() * 100.0)
    avg_slip_bps = float(sub["real_slip"].mean() * 10000.0) if "real_slip" in sub.columns else 0.0

    return {
        "n": int(len(rets)),
        "wr_pct": round(wr, 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(nav, 4),
        "ex3_nav": round(ex3, 4),
        "ex5_nav": round(ex5, 4),
        "mdd_pct": round(mdd, 2),
        "sharpe": round(sharpe, 3),
        "calmar": round(calmar, 2),
        "big_loss_m7_pct": round(bl_pct, 2),
        "big_loss_m7_cnt": bl_cnt,
        "excess_csi300_pp": round((nav - 1.0) * 100.0 - csi_pct, 2),
        "excess_ew_pp": round((nav - 1.0) * 100.0 - ew_pct, 2),
        "pct_0935plus": round(pct_intraday, 2),
        "avg_slip_bps": round(avg_slip_bps, 2),
    }


def compute_cscv_pbo(dr_mat: np.ndarray, names: list[str], n_blocks: int = 10) -> dict:
    T, N = dr_mat.shape
    if N < 2 or T < n_blocks * 10:
        return {"pbo_pct": 100.0, "n_models": int(N), "n_splits": 0}
    gs = T // n_blocks
    blocks = [list(range(i * gs, (i + 1) * gs if i < n_blocks - 1 else T)) for i in range(n_blocks)]
    omegas, ranks, is_best = [], [], []
    for te_b in itertools.combinations(range(n_blocks), n_blocks // 2):
        te_set = set(te_b)
        tri = [x for k in range(n_blocks) if k not in te_set for x in blocks[k]]
        tei = [x for k in range(n_blocks) if k in te_set for x in blocks[k]]
        rt, re = dr_mat[tri], dr_mat[tei]
        sdt, sde = rt.std(0, ddof=1), re.std(0, ddof=1)
        st = np.divide(rt.mean(0), sdt, out=np.zeros(N), where=sdt > 1e-12)
        se = np.divide(re.mean(0), sde, out=np.zeros(N), where=sde > 1e-12)
        b = int(np.argmax(st))
        n_bet = float(np.sum(se > se[b]))
        n_tie = float(np.sum(se == se[b])) - 1.0
        fb = (n_bet + 0.5 * max(0.0, n_tie)) / N
        omegas.append(fb)
        ranks.append(1.0 - fb)
        is_best.append(names[b])
    return {
        "n_models": int(N),
        "n_blocks": int(n_blocks),
        "n_splits": int(len(omegas)),
        "pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2),
        "median_oos_pct_rank": round(float(np.median(ranks) * 100.0), 2),
        "is_best_top3": pd.Series(is_best).value_counts().head(3).to_dict(),
    }


def compute_paired_t(dr_var: np.ndarray, dr_base: np.ndarray) -> dict:
    diff = dr_var - dr_base
    T = len(diff)
    sd = float(np.std(diff, ddof=1)) if T > 1 else 0.0
    t_all = float(np.mean(diff) / (sd / math.sqrt(T))) if sd > 1e-12 else 0.0
    p_all = float(2.0 * stats.t.sf(abs(t_all), df=T - 1)) if T > 1 else 1.0
    act = (dr_var != 0.0) | (dr_base != 0.0)
    na = int(act.sum())
    if na >= 10 and float(np.std(diff[act], ddof=1)) > 1e-12:
        t_act = float(np.mean(diff[act]) / (np.std(diff[act], ddof=1) / math.sqrt(na)))
        p_act = float(2.0 * stats.t.sf(abs(t_act), df=na - 1))
    else:
        t_act, p_act = 0.0, 1.0
    return {
        "t_daily_vs_0925": round(t_all, 3),
        "p_daily_vs_0925_2s": round(p_all, 4),
        "t_active_vs_0925": round(t_act, 3),
        "p_active_vs_0925_2s": round(p_act, 4),
        "n_active_union_days": na,
    }


def perm_test_1000(slot_df: pd.DataFrame, cand_pool_df: pd.DataFrame, sdt: str, edt: str, ret_col: str, n_perm: int = 1000, seed: int = 20261126) -> dict:
    sub_s = slot_df[slot_df["buy_date"].between(sdt, edt)] if not slot_df.empty else pd.DataFrame()
    sub_p = cand_pool_df[cand_pool_df["buy_date"].between(sdt, edt)].copy()
    sub_p = sub_p[sub_p[ret_col].notna()] if ret_col in sub_p.columns else pd.DataFrame()
    n_tr = len(sub_s)
    if n_tr < 3 or sub_p.empty:
        return {"n_perm": n_perm, "n_trades": n_tr, "same_day_p_nav": 1.0, "any_cand_day_p_nav": 1.0}
    rng = np.random.default_rng(seed)
    obs_rets = sub_s[ret_col].to_numpy(float)
    obs_nav = float(np.prod(1.0 + obs_rets))
    by_dt = {d: g[ret_col].to_numpy(float) for d, g in sub_p.groupby("buy_date")}
    day_arrs = list(by_dt.values())
    same_cols = [by_dt.get(d, obs_rets)[rng.integers(0, len(by_dt.get(d, obs_rets)), size=n_perm)] for d in sub_s["buy_date"]]
    sd_mat = np.column_stack(same_cols)
    p_sd = float((np.sum(np.prod(1.0 + sd_mat, axis=1) >= obs_nav - 1e-12) + 1) / (n_perm + 1))

    n_days = len(day_arrs)
    pick_d = rng.integers(0, n_days, size=(n_perm, n_tr))
    any_mat = np.empty((n_perm, n_tr), dtype=float)
    for j in range(n_tr):
        col = pick_d[:, j]
        for k in range(n_perm):
            arr = day_arrs[col[k]]
            any_mat[k, j] = arr[rng.integers(0, len(arr))]
    p_any = float((np.sum(np.prod(1.0 + any_mat, axis=1) >= obs_nav - 1e-12) + 1) / (n_perm + 1))
    return {"n_perm": int(n_perm), "n_trades": int(n_tr), "same_day_p_nav": round(p_sd, 4), "any_cand_day_p_nav": round(p_any, 4)}

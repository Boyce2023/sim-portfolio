#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD044 Step 1 — Family 1: Cross-Sectional Statistical Reversal & Intraday Microstructure
Strict causal T-1 factors, real T open execution (skip one-word ZT / suspended, delay one-word DT exit),
expanding walk-forward IC weighting (exit_date < t), liquidity tiers (>=50m & >=200m), 30bps & 50bps costs.
Zero yfinance (D12). Peak RAM < 1.5 GB.
"""
import gc
import json
import os
import resource
import sys
import time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

RD044_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd044_quant_4families_review_20261126"
if RD044_DIR not in sys.path:
    sys.path.insert(0, RD044_DIR)

import _rd044_common as cm

BASE_DIR = cm.BASE_DIR
CACHE_DIR = cm.CACHE_DIR


def load_dense_market_panel(end_dt: str = "2026-11-24") -> dict:
    """
    Load stock_day_core_features_pit.parquet up to end_dt via streaming pyarrow column chunks
    (zero full-table pandas allocation) and construct compact [N_D, N_S] float32 matrices.
    Peak RSS strictly < 1.5 GB.
    """
    t0 = time.time()
    pq_path = f"{BASE_DIR}/stock_day_core_features_pit.parquet"

    def _read_col(col_name: str):
        t_c = pq.read_table(pq_path, columns=[col_name], filters=[("dt", "<=", end_dt)])
        return t_c.column(0).to_pandas()

    s_dt = _read_col("dt")
    s_c6 = _read_col("c6")
    cal_dts = [str(d) for d in s_dt.cat.categories if str(d) <= end_dt]
    stocks = [str(c) for c in s_c6.cat.categories]
    N_D, N_S = len(cal_dts), len(stocks)
    di = s_dt.cat.codes.values.astype(np.int32)
    si = s_c6.cat.codes.values.astype(np.int32)
    del s_dt, s_c6
    gc.collect()

    n = len(di)
    brk = np.flatnonzero(si[1:] != si[:-1]) + 1
    starts = np.concatenate(([0], brk))
    ends = np.concatenate((brk, [n]))

    def _np(col_name: str, dtype=np.float64):
        return _read_col(col_name).to_numpy(dtype=dtype, copy=False)

    op_raw = _np("open", np.float64)
    cl_raw = _np("close", np.float64)
    adj_f = _np("adj_factor", np.float64)
    adj_close = cl_raw * adj_f
    adj_open = op_raw * adj_f
    del adj_f

    r1 = np.nan_to_num(_np("ret_1d", np.float64), nan=0.0) / 100.0
    on1 = np.clip(np.nan_to_num(_np("open_pct", np.float64), nan=0.0) / 100.0, -0.5, 1.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        id1 = np.where(op_raw > 0, cl_raw / op_raw - 1.0, 0.0)
    id1 = np.clip(np.nan_to_num(id1, nan=0.0), -0.5, 1.0)
    log_on1 = np.log1p(on1)
    log_id1 = np.log1p(id1)
    turn_v = np.nan_to_num(_np("turn_pct", np.float64), nan=0.0)
    amt_v = np.nan_to_num(_np("amount_yi", np.float64), nan=0.0)
    clv_v = np.nan_to_num(_np("clv", np.float64), nan=0.5)
    del on1, id1

    ret10_t1 = np.full(n, np.nan, dtype=np.float32)
    vol20_t1 = np.full(n, np.nan, dtype=np.float32)
    on20_t1 = np.full(n, np.nan, dtype=np.float32)
    id20_t1 = np.full(n, np.nan, dtype=np.float32)
    vp_corr20_t1 = np.full(n, np.nan, dtype=np.float32)
    clv5_t1 = np.full(n, np.nan, dtype=np.float32)
    amt20_t1 = np.full(n, np.nan, dtype=np.float32)

    for s, e in zip(starts, ends):
        m = e - s
        if m < 2:
            continue
        ac = adj_close[s:e]
        if m > 11:
            ret10_t1[s + 11 : e] = ((ac[10:-1] / ac[:-11] - 1.0) * 100.0).astype(np.float32)

        cs_r1 = np.concatenate(([0.0], np.cumsum(r1[s:e])))
        cs_r1_sq = np.concatenate(([0.0], np.cumsum(r1[s:e] ** 2)))
        cs_on = np.concatenate(([0.0], np.cumsum(log_on1[s:e])))
        cs_id = np.concatenate(([0.0], np.cumsum(log_id1[s:e])))
        cs_tr = np.concatenate(([0.0], np.cumsum(turn_v[s:e])))
        cs_tr_sq = np.concatenate(([0.0], np.cumsum(turn_v[s:e] ** 2)))
        cs_rt = np.concatenate(([0.0], np.cumsum(r1[s:e] * turn_v[s:e])))
        cs_am = np.concatenate(([0.0], np.cumsum(amt_v[s:e])))
        cs_cl = np.concatenate(([0.0], np.cumsum(clv_v[s:e])))

        if m >= 6:
            clv5_t1[s + 5 : e] = ((cs_cl[5:-1] - cs_cl[:-6]) / 5.0).astype(np.float32)
            for i in range(5, min(20, m)):
                amt20_t1[s + i] = float(cs_am[i] / i)

        if m >= 21:
            idx_hi = np.arange(20, m)
            idx_lo = idx_hi - 20
            w = 20.0
            mean_r = (cs_r1[idx_hi] - cs_r1[idx_lo]) / w
            mean_r2 = (cs_r1_sq[idx_hi] - cs_r1_sq[idx_lo]) / w
            var_r = np.maximum(0.0, mean_r2 - mean_r ** 2) * (w / (w - 1.0))
            vol20_t1[s + 20 : e] = (np.sqrt(var_r) * 100.0).astype(np.float32)

            on20_t1[s + 20 : e] = (np.expm1(cs_on[idx_hi] - cs_on[idx_lo]) * 100.0).astype(np.float32)
            id20_t1[s + 20 : e] = (np.expm1(cs_id[idx_hi] - cs_id[idx_lo]) * 100.0).astype(np.float32)

            mean_t = (cs_tr[idx_hi] - cs_tr[idx_lo]) / w
            mean_t2 = (cs_tr_sq[idx_hi] - cs_tr_sq[idx_lo]) / w
            var_t = np.maximum(0.0, mean_t2 - mean_t ** 2) * (w / (w - 1.0))
            cov_rt = ((cs_rt[idx_hi] - cs_rt[idx_lo]) / w - mean_r * mean_t) * (w / (w - 1.0))
            denom = np.sqrt(var_r * var_t)
            with np.errstate(divide="ignore", invalid="ignore"):
                vp_corr20_t1[s + 20 : e] = np.where(denom > 1e-12, cov_rt / denom, 0.0).astype(np.float32)

            amt20_t1[s + 20 : e] = ((cs_am[idx_hi] - cs_am[idx_lo]) / w).astype(np.float32)

    del r1, log_on1, log_id1, turn_v, clv_v
    gc.collect()

    is_st = _np("is_st_pit", np.int8) == 1
    is_20 = _np("is_20cm", np.int8) == 1
    dt_codes_260706 = int(np.searchsorted(np.array(cal_dts), "2026-07-06", side="left"))
    lim = np.where(is_20, 0.20, np.where(is_st & (di < dt_codes_260706), 0.05, 0.10))
    prev_raw = _np("prev_close_raw", np.float64)
    zt_px = np.round(prev_raw * (1.0 + lim), 2)
    dt_px = np.round(prev_raw * (1.0 - lim), 2)
    del prev_raw, is_20

    valid_px = (op_raw > 0) & (cl_raw > 0) & (amt_v > 0)
    yz_zt = _np("is_yizi_zt", np.int8)
    yz_dt = _np("is_yizi_dt", np.int8)
    is_dt_f = _np("is_dt", np.int8)

    can_buy_open = valid_px & (yz_zt == 0) & np.where(np.isfinite(zt_px) & (zt_px > 0), op_raw < zt_px - 1e-4, True)
    can_sell_open_px = valid_px & (yz_dt == 0) & np.where(np.isfinite(dt_px) & (dt_px > 0), op_raw > dt_px + 1e-4, True)
    can_sell_close_px = valid_px & (yz_dt == 0) & (~can_sell_open_px) & (is_dt_f == 0)
    sell_exec_adj = np.where(can_sell_open_px, adj_open, np.where(can_sell_close_px, adj_close, np.nan)).astype(np.float32)
    del op_raw, cl_raw, amt_v, zt_px, dt_px, yz_zt, yz_dt, is_dt_f, can_sell_open_px, can_sell_close_px

    def _to_mat(arr, fill=np.nan, dtype=np.float32):
        mat = np.full((N_D, N_S), fill, dtype=dtype)
        mat[di, si] = arr.astype(dtype)
        return mat

    panel = {
        "cal_dts": cal_dts,
        "stocks": stocks,
        "N_D": N_D,
        "N_S": N_S,
        "tradable": _to_mat(valid_px, fill=False, dtype=bool),
        "can_buy_open": _to_mat(can_buy_open, fill=False, dtype=bool),
        "adj_open": _to_mat(adj_open, fill=np.nan, dtype=np.float32),
        "adj_close": _to_mat(adj_close, fill=np.nan, dtype=np.float32),
        "sell_exec_adj": _to_mat(sell_exec_adj, fill=np.nan, dtype=np.float32),
        "is_st": _to_mat(is_st, fill=True, dtype=bool),
        "list_age": _to_mat(_np("list_age", np.int16), fill=-1, dtype=np.int16),
        "amt_t1": _to_mat(_np("amount_yi_t1", np.float32), fill=np.nan, dtype=np.float32),
        "amt20_t1": _to_mat(amt20_t1, fill=np.nan, dtype=np.float32),
        "F_REV10": _to_mat(-ret10_t1, fill=np.nan, dtype=np.float32),
        "F_LOWVOL": _to_mat(-vol20_t1, fill=np.nan, dtype=np.float32),
        "F_ON20": _to_mat(on20_t1, fill=np.nan, dtype=np.float32),
        "F_ID20_REV": _to_mat(-id20_t1, fill=np.nan, dtype=np.float32),
        "F_VP_CORR": _to_mat(-vp_corr20_t1, fill=np.nan, dtype=np.float32),
        "F_CLV5_REV": _to_mat(-clv5_t1, fill=np.nan, dtype=np.float32),
        "F_REV5": _to_mat(-_np("ret_5d_t1", np.float32), fill=np.nan, dtype=np.float32),
        "F_REV20": _to_mat(-_np("ret_20d_t1", np.float32), fill=np.nan, dtype=np.float32),
        "F_TURN_ABN": _to_mat(-_np("turn_5_20_t1", np.float32), fill=np.nan, dtype=np.float32),
        "F_LOWAMP": _to_mat(-_np("amp_20d_t1", np.float32), fill=np.nan, dtype=np.float32),
    }

    del adj_close, adj_open, ret10_t1, vol20_t1, on20_t1, id20_t1, vp_corr20_t1, clv5_t1, amt20_t1
    del valid_px, can_buy_open, sell_exec_adj, is_st, di, si
    gc.collect()

    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    print(f"[Family1] Panel built ({N_D} days x {N_S} stocks) in {time.time()-t0:.1f}s | Peak RSS={rss_mb:.1f} MB")
    return panel


def cross_sectional_rank_z(mat: np.ndarray, elig_mask: np.ndarray) -> np.ndarray:
    """Exact cross-sectional rank z-score in [-sqrt(3), +sqrt(3)] on each day strictly over elig_mask."""
    N_D, N_S = mat.shape
    out = np.full((N_D, N_S), np.nan, dtype=np.float32)
    for d in range(N_D):
        m = elig_mask[d] & np.isfinite(mat[d])
        k = int(m.sum())
        if k < 20:
            continue
        vals = mat[d, m]
        # Average rank via double argsort
        order = np.argsort(vals, kind="mergesort")
        ranks = np.empty(k, dtype=np.float64)
        ranks[order] = np.arange(k, dtype=np.float64)
        # Uniform in (-1, 1) -> z-score mean 0, std 1
        u = (ranks + 0.5) / k - 0.5
        out[d, m] = (u / 0.28867513).astype(np.float32)
    return out


def build_composite_scores(panel: dict, elig_mask: np.ndarray, hold_days: int = 10) -> dict:
    """
    Build cross-sectional standardized single factors, equal-weight composite,
    and STRICT EXPANDING CAUSAL Rank-IC weighted composite (exit_date < t).
    """
    factor_names = [
        "F_REV5", "F_REV10", "F_REV20", "F_TURN_ABN",
        "F_LOWVOL", "F_LOWAMP", "F_ON20", "F_ID20_REV", "F_VP_CORR", "F_CLV5_REV",
    ]
    z_mats = {fn: cross_sectional_rank_z(panel[fn], elig_mask) for fn in factor_names}
    # Overnight vs Intraday split composite
    z_on_id = np.full_like(z_mats["F_ON20"], np.nan)
    m_oi = np.isfinite(z_mats["F_ON20"]) & np.isfinite(z_mats["F_ID20_REV"])
    z_on_id[m_oi] = 0.5 * (z_mats["F_ON20"][m_oi] + z_mats["F_ID20_REV"][m_oi])
    z_mats["F_ON_MINUS_ID"] = z_on_id

    # Core 6 orthogonal alpha pillars for EW and Expanding WF-IC composite
    core_6 = ["F_REV10", "F_TURN_ABN", "F_LOWVOL", "F_ON_MINUS_ID", "F_VP_CORR", "F_CLV5_REV"]

    # Equal-weight composite (mean of finite pillars, require >= 4 finite)
    N_D, N_S = elig_mask.shape
    ew_sum = np.zeros((N_D, N_S), dtype=np.float32)
    ew_cnt = np.zeros((N_D, N_S), dtype=np.int8)
    for fn in core_6:
        z = z_mats[fn]
        ok = np.isfinite(z)
        ew_sum[ok] += z[ok]
        ew_cnt[ok] += 1
    z_ew = np.where(ew_cnt >= 4, ew_sum / np.maximum(ew_cnt, 1), np.nan).astype(np.float32)

    # Expanding Walk-Forward Rank-IC composite (strict exit_date < t, i.e., d + H < t)
    # Forward H-day open-to-open return for IC training (ONLY used when d + H < t!)
    adj_open = panel["adj_open"]
    trad = panel["tradable"]
    fwd_ret = np.full((N_D, N_S), np.nan, dtype=np.float32)
    if N_D > hold_days + 1:
        op_in = adj_open[:-hold_days]
        op_out = adj_open[hold_days:]
        ok_f = trad[:-hold_days] & trad[hold_days:] & (op_in > 0) & (op_out > 0) & panel["can_buy_open"][:-hold_days]
        fwd_ret[:-hold_days] = np.where(ok_f, op_out / np.maximum(op_in, 1e-6) - 1.0, np.nan)

    # Precompute daily Rank-IC (corr between z_fn[d] and rank(fwd_ret[d])) for each factor
    daily_ic = np.full((N_D, len(core_6)), np.nan, dtype=np.float64)
    for d in range(N_D - hold_days - 1):
        fr = fwd_ret[d]
        m_f = elig_mask[d] & np.isfinite(fr)
        if m_f.sum() < 50:
            continue
        r_vals = fr[m_f]
        ord_r = np.argsort(r_vals, kind="mergesort")
        rk_r = np.empty(len(r_vals), dtype=np.float64)
        rk_r[ord_r] = np.arange(len(r_vals), dtype=np.float64)
        rk_r = (rk_r - rk_r.mean()) / max(rk_r.std(), 1e-9)
        for fi, fn in enumerate(core_6):
            zv = z_mats[fn][d, m_f]
            ok_z = np.isfinite(zv)
            if ok_z.sum() < 50:
                continue
            z_sub = zv[ok_z]
            r_sub = rk_r[ok_z]
            z_sub = (z_sub - z_sub.mean()) / max(z_sub.std(), 1e-9)
            daily_ic[d, fi] = float(np.mean(z_sub * r_sub))

    # Strict causal expanding ICIR weighting at day t using ONLY d where d + hold_days < t
    z_ic = np.full((N_D, N_S), np.nan, dtype=np.float32)
    ic_weights_log = {}
    for t in range(N_D):
        cutoff_d = t - hold_days - 1  # strictly exit_date = d + hold_days < t
        if cutoff_d < 30:
            # Warmup fallback: equal weight
            z_ic[t] = z_ew[t]
            continue
        hist_ic = daily_ic[: cutoff_d + 1]
        w_vec = np.zeros(len(core_6), dtype=np.float64)
        for fi in range(len(core_6)):
            col = hist_ic[:, fi]
            v = col[np.isfinite(col)]
            if len(v) >= 20 and np.std(v, ddof=1) > 1e-9:
                icir = float(np.mean(v) / np.std(v, ddof=1))
                w_vec[fi] = max(0.0, icir)
        if w_vec.sum() <= 1e-6:
            w_vec[:] = 1.0 / len(core_6)
        else:
            w_vec /= w_vec.sum()
        if panel["cal_dts"][t] in ("2023-01-03", "2024-12-31", "2026-11-24"):
            ic_weights_log[panel["cal_dts"][t]] = {fn: round(float(w_vec[i]), 4) for i, fn in enumerate(core_6)}

        acc = np.zeros(N_S, dtype=np.float32)
        wt_s = np.zeros(N_S, dtype=np.float32)
        for fi, fn in enumerate(core_6):
            if w_vec[fi] <= 0:
                continue
            z_row = z_mats[fn][t]
            ok = np.isfinite(z_row)
            acc[ok] += float(w_vec[fi]) * z_row[ok]
            wt_s[ok] += float(w_vec[fi])
        z_ic[t] = np.where(wt_s > 0.4, acc / np.maximum(wt_s, 1e-6), np.nan)

    z_mats["Z_EW_COMP"] = z_ew
    z_mats["Z_WF_IC_COMP"] = z_ic
    z_mats["_ic_weights_log"] = ic_weights_log
    return z_mats


def simulate_xs_portfolio(
    panel: dict,
    score_mat: np.ndarray,
    elig_mask: np.ndarray,
    top_k: int = 20,
    rebal_days: int = 10,
    rebal_offset: int = 0,
    fee_rt: float = 0.0030,
    start_dt: str = "2021-01-04",
    end_dt: str = "2026-11-24",
    risk_off_mask: np.ndarray = None,
) -> dict:
    """
    Exact daily MTM qty/cash portfolio simulator with:
      - Open-to-open rebalance every `rebal_days` trading days
      - Buy-side skip & cascade when open is suspended or limit-up one-word/at-limit
      - Sell-side lock & delay when suspended or one-word limit-down (sells on first open-board day)
      - Only trades delta shares for kept holdings (zero redundant fee!)
    """
    cal_dts = panel["cal_dts"]
    N_D, N_S = panel["N_D"], panel["N_S"]
    trad = panel["tradable"]
    can_buy = panel["can_buy_open"]
    adj_open = panel["adj_open"]
    adj_close = panel["adj_close"]
    sell_px = panel["sell_exec_adj"]
    amt20 = panel["amt20_t1"]

    fee_buy = fee_rt * (1.0 / 3.0)
    fee_sell = fee_rt * (2.0 / 3.0)

    qty = np.zeros(N_S, dtype=np.float64)
    last_px = np.zeros(N_S, dtype=np.float64)
    pending_sell = np.zeros(N_S, dtype=bool)
    cash = 1.0
    nav_prev = 1.0

    dr = np.zeros(N_D, dtype=np.float64)
    to_daily = np.zeros(N_D, dtype=np.float64)
    act_mask = np.zeros(N_D, dtype=bool)
    cap_daily_yi = np.full(N_D, np.nan, dtype=np.float64)

    sim_indices = [i for i, d in enumerate(cal_dts) if start_dt <= d <= end_dt]
    if not sim_indices:
        return {"dr": dr, "to_daily": to_daily, "act_mask": act_mask, "cap_daily_yi": cap_daily_yi}

    buy_skip_cnt = 0
    sell_lock_cnt = 0
    rebal_step = 0

    for t in sim_indices:
        traded_val = 0.0

        # 1. Execute any pending sells from previous days that just unlocked
        if pending_sell.any():
            ps_idx = np.flatnonzero(pending_sell & (qty > 0))
            for s in ps_idx:
                px = float(sell_px[t, s])
                if np.isfinite(px) and px > 0:
                    proceeds = qty[s] * px * (1.0 - fee_sell)
                    traded_val += qty[s] * px
                    cash += proceeds
                    qty[s] = 0.0
                    pending_sell[s] = False

        is_risk_off = bool(risk_off_mask[t]) if risk_off_mask is not None else False
        is_rebal = (rebal_step % rebal_days == rebal_offset % rebal_days)
        rebal_step += 1

        if is_risk_off:
            # Liquidate all sellable holdings
            held = np.flatnonzero(qty > 0)
            for s in held:
                px = float(sell_px[t, s])
                if np.isfinite(px) and px > 0:
                    traded_val += qty[s] * px
                    cash += qty[s] * px * (1.0 - fee_sell)
                    qty[s] = 0.0
                    pending_sell[s] = False
                else:
                    pending_sell[s] = True
                    sell_lock_cnt += 1
        elif is_rebal:
            # Determine target Top K among eligible & buyable stocks
            # Note: already-held stocks that remain eligible & in Top K don't need to be can_buy_open!
            sc_row = score_mat[t]
            pool_m = elig_mask[t] & np.isfinite(sc_row) & (can_buy[t] | (qty > 0))
            cand_idx = np.flatnonzero(pool_m)
            targets = []
            if len(cand_idx) > 0:
                order = cand_idx[np.argsort(-sc_row[cand_idx], kind="mergesort")]
                for s in order:
                    if qty[s] > 0 or can_buy[t, s]:
                        targets.append(int(s))
                        if len(targets) >= top_k:
                            break
                    else:
                        buy_skip_cnt += 1

            target_set = set(targets)
            # Sell holdings NOT in target_set (or mark pending_sell if locked)
            held = np.flatnonzero(qty > 0)
            locked_val = 0.0
            for s in held:
                if s not in target_set:
                    px = float(sell_px[t, s])
                    if np.isfinite(px) and px > 0:
                        traded_val += qty[s] * px
                        cash += qty[s] * px * (1.0 - fee_sell)
                        qty[s] = 0.0
                        pending_sell[s] = False
                    else:
                        pending_sell[s] = True
                        sell_lock_cnt += 1
                        locked_val += qty[s] * (last_px[s] if last_px[s] > 0 else 0.0)

            if targets:
                # Rebalance kept + new targets cleanly at open[t]
                # Estimate open value of deployable equity (cash + kept stocks valued at open or last_px)
                kept_vals = {}
                for s in targets:
                    if qty[s] > 0:
                        px_o = float(adj_open[t, s]) if (trad[t, s] and np.isfinite(adj_open[t, s]) and adj_open[t, s] > 0) else last_px[s]
                        kept_vals[s] = qty[s] * px_o
                    else:
                        kept_vals[s] = 0.0
                deployable = cash + sum(kept_vals.values())
                tgt_each = deployable / len(targets)

                # First trim overweight kept positions (if sellable at open)
                for s in targets:
                    if qty[s] > 0 and kept_vals[s] > tgt_each * 1.02:
                        px = float(sell_px[t, s])
                        if np.isfinite(px) and px > 0:
                            sell_amt = kept_vals[s] - tgt_each
                            dq = min(qty[s], sell_amt / px)
                            traded_val += dq * px
                            cash += dq * px * (1.0 - fee_sell)
                            qty[s] -= dq

                # Then buy underweight / new targets proportionally to remaining cash
                need_list = []
                for s in targets:
                    if not can_buy[t, s]:
                        continue
                    px_b = float(adj_open[t, s])
                    if not (np.isfinite(px_b) and px_b > 0):
                        continue
                    cur_v = qty[s] * px_b
                    if tgt_each > cur_v + 1e-6:
                        need_list.append((s, px_b, tgt_each - cur_v))
                tot_need = sum(x[2] for x in need_list)
                if tot_need > 1e-9 and cash > 1e-9:
                    scale = min(1.0, cash / (tot_need * (1.0 + fee_buy)))
                    for s, px_b, want_v in need_list:
                        spend = want_v * scale
                        dq = spend / px_b
                        qty[s] += dq
                        traded_val += spend
                        cash -= spend * (1.0 + fee_buy)

        # Update MTM at t close
        held_now = np.flatnonzero(qty > 0)
        if len(held_now) > 0:
            tr_h = trad[t, held_now]
            ac_h = adj_close[t, held_now]
            ok_u = tr_h & np.isfinite(ac_h) & (ac_h > 0)
            last_px[held_now[ok_u]] = ac_h[ok_u]
            pos_val = float(np.sum(qty[held_now] * last_px[held_now]))
            act_mask[t] = True
            # Capacity estimate: portfolio size if each position <= 1% of stock's 20d ADV
            adv_h = amt20[t, held_now]
            if np.isfinite(adv_h).any():
                min_adv = float(np.nanpercentile(adv_h, 20))
                cap_daily_yi[t] = 0.01 * min_adv * len(held_now)
        else:
            pos_val = 0.0

        nav_now = cash + pos_val
        dr[t] = (nav_now / nav_prev) - 1.0 if nav_prev > 0 else 0.0
        to_daily[t] = (traded_val / (2.0 * nav_prev)) if nav_prev > 0 else 0.0
        nav_prev = nav_now

    return {
        "dr": dr,
        "to_daily": to_daily,
        "act_mask": act_mask,
        "cap_daily_yi": cap_daily_yi,
        "buy_skip_cnt": int(buy_skip_cnt),
        "sell_lock_cnt": int(sell_lock_cnt),
    }


def run_family1(end_dt: str = "2026-11-24", run_trunc_check: bool = True) -> dict:
    t0 = time.time()
    bench_ctx = cm.load_bench_and_v20(end_dt=end_dt)
    panel = load_dense_market_panel(end_dt=end_dt)

    # Liquidity masks
    base_elig = (~panel["is_st"]) & (panel["list_age"] >= 60) & panel["tradable"]
    elig_50m = base_elig & (panel["amt20_t1"] >= 0.50) & (panel["amt_t1"] >= 0.25)
    elig_200m = base_elig & (panel["amt20_t1"] >= 2.00) & (panel["amt_t1"] >= 1.00)

    # Build z-scores on 50m & 200m separately
    z50 = build_composite_scores(panel, elig_50m, hold_days=10)
    z200 = build_composite_scores(panel, elig_200m, hold_days=10)

    results = []
    daily_series = {}

    def _run_one(tag: str, score_m: np.ndarray, elig_m: np.ndarray, liq: str, top_k: int, reb: int, fee: float, off: int = 0):
        sim = simulate_xs_portfolio(panel, score_m, elig_m, top_k=top_k, rebal_days=reb, rebal_offset=off, fee_rt=fee, start_dt="2021-01-04", end_dt=end_dt)
        ev = cm.evaluate_daily_series(sim["dr"], bench_ctx, turnover_daily=sim["to_daily"], active_mask=sim["act_mask"], cap_daily_yi=sim["cap_daily_yi"])
        row = {
            "family": "F1_XS_StatRev",
            "strategy_id": tag,
            "liq_tier": liq,
            "top_k": top_k,
            "rebal_days": reb,
            "fee_bps": int(round(fee * 10000)),
            "buy_skips": sim["buy_skip_cnt"],
            "sell_locks": sim["sell_lock_cnt"],
            "windows": ev,
        }
        results.append(row)
        daily_series[tag] = sim["dr"]
        return row

    # 1. Single factor tests (50m, Top 20, H=10, 30bps)
    single_factors = ["F_REV5", "F_REV10", "F_REV20", "F_TURN_ABN", "F_LOWVOL", "F_LOWAMP", "F_ON_MINUS_ID", "F_VP_CORR", "F_CLV5_REV"]
    for fn in single_factors:
        _run_one(f"F1_S_{fn}_50m_K20_H10_30bp", z50[fn], elig_50m, ">=50m", 20, 10, 0.0030)

    # Also add 3-pillar Quality Microstructure Composite (LOWVOL + TURN_ABN + ON_MINUS_ID, excluding falling-knife REV10)
    for tag_z, zm in [("50m", z50), ("200m", z200)]:
        q3 = np.where(
            np.isfinite(zm["F_LOWVOL"]) & np.isfinite(zm["F_TURN_ABN"]) & np.isfinite(zm["F_ON_MINUS_ID"]),
            (zm["F_LOWVOL"] + zm["F_TURN_ABN"] + zm["F_ON_MINUS_ID"]) / 3.0,
            np.nan,
        ).astype(np.float32)
        zm["Z_Q3_MICRO"] = q3

    # Also compute mean OOS Rank-IC across all single factors (50m)
    factor_ic_summary = {}
    adj_open = panel["adj_open"]
    trad = panel["tradable"]
    N_D = panel["N_D"]
    fwd10 = np.full_like(adj_open, np.nan)
    fwd10[:-10] = np.where(trad[:-10] & trad[10:] & panel["can_buy_open"][:-10] & (adj_open[:-10] > 0) & (adj_open[10:] > 0), adj_open[10:] / np.maximum(adj_open[:-10], 1e-6) - 1.0, np.nan)
    wf_i0 = next(i for i, d in enumerate(panel["cal_dts"]) if d >= "2023-01-03")
    for fn in single_factors + ["Z_EW_COMP", "Z_WF_IC_COMP", "Z_Q3_MICRO"]:
        ics = []
        zm_f = z50[fn]
        for d in range(wf_i0, N_D - 11):
            m = elig_50m[d] & np.isfinite(fwd10[d]) & np.isfinite(zm_f[d])
            if m.sum() < 50:
                continue
            r_v = fwd10[d, m]
            ord_r = np.argsort(r_v, kind="mergesort")
            rk_r = np.empty(len(r_v), dtype=np.float64)
            rk_r[ord_r] = np.arange(len(r_v), dtype=np.float64)
            rk_r = (rk_r - rk_r.mean()) / max(rk_r.std(), 1e-9)
            z_v = zm_f[d, m].astype(np.float64)
            z_v = (z_v - z_v.mean()) / max(z_v.std(), 1e-9)
            ics.append(float(np.mean(z_v * rk_r)))
        if ics:
            arr_ic = np.array(ics)
            factor_ic_summary[fn] = {
                "mean_ic": round(float(arr_ic.mean()), 4),
                "icir": round(float(arr_ic.mean() / max(arr_ic.std(ddof=1), 1e-9)), 3),
                "ic_pos_pct": round(float((arr_ic > 0).mean() * 100.0), 1),
            }

    # 2. Composite grid (EW, WF_IC, Q3_MICRO across K=10/20/30/50, H=5/10/20, 50m/200m, 30bp/50bp)
    for comp_name in ["Z_EW_COMP", "Z_WF_IC_COMP", "Z_Q3_MICRO"]:
        for reb in [5, 10, 20]:
            for top_k in [10, 20, 30, 50]:
                if comp_name != "Z_Q3_MICRO" and top_k == 50:
                    continue
                for fee in [0.0030, 0.0050]:
                    _run_one(f"F1_{comp_name}_50m_K{top_k}_H{reb}_{int(fee*10000)}bp", z50[comp_name], elig_50m, ">=50m", top_k, reb, fee)
        # 200m Institutional liquidity checks
        for reb in [10, 20]:
            for top_k in [20, 30]:
                for fee in [0.0030, 0.0050]:
                    _run_one(f"F1_{comp_name}_200m_K{top_k}_H{reb}_{int(fee*10000)}bp", z200[comp_name], elig_200m, ">=200m", top_k, reb, fee)
    # Also check LOWVOL & TURN_ABN at H=20 & K=30 & >=200m
    for fn in ["F_LOWVOL", "F_TURN_ABN"]:
        for top_k in [20, 30, 50]:
            for fee in [0.0030, 0.0050]:
                _run_one(f"F1_S_{fn}_50m_K{top_k}_H20_{int(fee*10000)}bp", z50[fn], elig_50m, ">=50m", top_k, 20, fee)
                _run_one(f"F1_S_{fn}_200m_K{top_k}_H20_{int(fee*10000)}bp", z200[fn], elig_200m, ">=200m", top_k, 20, fee)

    # Identify best OOS Sharpe (30bps, 50m & 200m) for offset invariance & 80bps stress & truncation check
    oos_30_50 = [r for r in results if r["fee_bps"] == 30 and r["liq_tier"] == ">=50m" and r["top_k"] >= 20]
    best_50 = max(oos_30_50, key=lambda r: r["windows"]["WF_OOS"]["sharpe"])
    oos_30_200 = [r for r in results if r["fee_bps"] == 30 and r["liq_tier"] == ">=200m"]
    best_200 = max(oos_30_200, key=lambda r: r["windows"]["WF_OOS"]["sharpe"])

    def _resolve_score_key(sid: str) -> str:
        if "Z_WF_IC_COMP" in sid:
            return "Z_WF_IC_COMP"
        if "Z_EW_COMP" in sid:
            return "Z_EW_COMP"
        for k in z50.keys():
            if f"_{k}_" in sid:
                return k
        return "Z_EW_COMP"

    b_comp = _resolve_score_key(best_50["strategy_id"])
    _run_one(f"{best_50['strategy_id']}_80bp", z50[b_comp], elig_50m, ">=50m", best_50["top_k"], best_50["rebal_days"], 0.0080)
    offset_sharpes = []
    for off in range(best_50["rebal_days"]):
        sim_o = simulate_xs_portfolio(panel, z50[b_comp], elig_50m, top_k=best_50["top_k"], rebal_days=best_50["rebal_days"], rebal_offset=off, fee_rt=0.0030, start_dt="2021-01-04", end_dt=end_dt)
        ev_o = cm.evaluate_daily_series(sim_o["dr"], bench_ctx)
        offset_sharpes.append({"offset": off, "wf_sharpe": ev_o["WF_OOS"]["sharpe"], "wf_cagr": ev_o["WF_OOS"]["cagr_pct"], "wf_mdd": ev_o["WF_OOS"]["mdd_pct"]})

    # Physical truncation verification at 2024-12-31 (in fresh subprocess to keep RSS < 2.3 GB!)
    trunc_audit = {}
    if run_trunc_check:
        import subprocess
        sub_code = (
            f"import sys, json, numpy as np; sys.path.insert(0, {RD044_DIR!r}); "
            f"import step1_family1_xs_stat_rev as f1; "
            f"p_tr = f1.load_dense_market_panel(end_dt='2024-12-31'); "
            f"e_tr = (~p_tr['is_st']) & (p_tr['list_age'] >= 60) & p_tr['tradable'] & (p_tr['amt20_t1'] >= 0.50) & (p_tr['amt_t1'] >= 0.25); "
            f"z_tr = f1.build_composite_scores(p_tr, e_tr, hold_days=10); "
            f"s_b = f1.simulate_xs_portfolio(p_tr, z_tr[{b_comp!r}], e_tr, top_k={best_50['top_k']}, rebal_days={best_50['rebal_days']}, fee_rt=0.0030, start_dt='2021-01-04', end_dt='2024-12-31'); "
            f"s_ic = f1.simulate_xs_portfolio(p_tr, z_tr['Z_WF_IC_COMP'], e_tr, top_k=20, rebal_days=20, fee_rt=0.0030, start_dt='2021-01-04', end_dt='2024-12-31'); "
            f"np.savez({CACHE_DIR + '/_f1_trunc_tmp.npz'!r}, dr_b=s_b['dr'], dr_ic=s_ic['dr'], n=len(p_tr['cal_dts']))"
        )
        subprocess.run([sys.executable, "-c", sub_code], check=True)
        tz = np.load(f"{CACHE_DIR}/_f1_trunc_tmp.npz")
        n_tr = int(tz["n"])
        diff_b = float(np.max(np.abs(daily_series[best_50["strategy_id"]][:n_tr] - tz["dr_b"][:n_tr])))
        diff_ic = float(np.max(np.abs(daily_series["F1_Z_WF_IC_COMP_50m_K20_H20_30bp"][:n_tr] - tz["dr_ic"][:n_tr])))
        trunc_audit = {
            "best_strategy_id": best_50["strategy_id"],
            "n_days_to_20241231": n_tr,
            "best_max_abs_ret_diff": diff_b,
            "wf_ic_max_abs_ret_diff": diff_ic,
            "passed": (diff_b == 0.0) and (diff_ic == 0.0),
        }
        print(f"[Family1] 2024-12-31 Physical Truncation Check: best_diff={diff_b}, wf_ic_diff={diff_ic}")

    # Save outputs
    np.savez_compressed(f"{CACHE_DIR}/f1_daily_returns.npz", cal_dts=np.array(bench_ctx["cal_dts"]), **{k: v for k, v in daily_series.items()})
    out_obj = {
        "family": "F1_XS_StatRev",
        "elapsed_sec": round(time.time() - t0, 1),
        "best_50m": best_50["strategy_id"],
        "best_200m": best_200["strategy_id"],
        "factor_ic_summary_oos": factor_ic_summary,
        "offset_invariance": offset_sharpes,
        "physical_truncation_20241231": trunc_audit,
        "results": results,
    }
    with open(f"{CACHE_DIR}/f1_results.json", "w", encoding="utf-8") as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

    print("\n=== FAMILY 1 TOP OOS SUMMARY (WF 2023-01-03..2026-11-24) ===")
    for r in sorted(results, key=lambda x: -x["windows"]["WF_OOS"]["sharpe"])[:12]:
        w = r["windows"]["WF_OOS"]
        print(f"{r['strategy_id']:40s} | CAGR={w['cagr_pct']:6.2f}% | Sh={w['sharpe']:5.3f} | MDD={w['mdd_pct']:5.2f}% | Ex300={w['excess_csi300_pp']:7.1f}pp | TO={w['ann_turnover_pct']:5.0f}%")
    return out_obj


if __name__ == "__main__":
    run_family1()

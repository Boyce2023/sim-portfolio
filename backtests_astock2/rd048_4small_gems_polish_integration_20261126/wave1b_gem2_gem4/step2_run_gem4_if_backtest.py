#!/usr/bin/env python3
"""Step 2 for Gem 4: National Team Rescue Long Real CFFEX IF Futures (1x..7x)
with Daily Mark-to-Market, Intraday Low Margin-Call / Forced-Liquidation Audit,
Rollover-Free Same-Contract Execution, Polish Grid, D15 + 4 Small-Sample Tests,
and 2024-12-31 Physical Truncation Verification. Strictly ZERO yfinance imports.
"""
import os
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[k] = "1"

import json
import resource
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path("/Users/huaichuaibeimeng/claude-projects")
OUT_DIR = BASE / "sim-portfolio/backtests_astock2/rd048_4small_gems_polish_integration_20261126/wave1b_gem2_gem4"
W1_BASE = BASE / "sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"

sys.path.insert(0, str(OUT_DIR))
import gem_stats_lib as gsl


def load_panel(cutoff_date: str = "2026-11-25") -> pd.DataFrame:
    if_df = pd.read_parquet(OUT_DIR / "if_continuous_daily_cache.parquet")
    if_df = if_df[(if_df["date"] >= "2021-01-04") & (if_df["date"] <= cutoff_date)].copy()

    mdf_cols = [
        "trade_date", "nt_v3_score_live_t1", "nt_v3_score_eod_t1",
        "mkt_csi300_ret1d_t1", "th_tech_csi300_rsi14_t1",
        "th_tech_csi300_ma20_dist_t1", "mkt_pct_above_ma20_t1",
        "L1_sent_phase_t1", "L1_ew_bias20_t1",
    ]
    mdf = pd.read_parquet(W1_BASE / "market_daily_all_new_factors_pit.parquet", columns=mdf_cols)
    mdf["date"] = mdf["trade_date"].astype(str)
    mdf = mdf[(mdf["date"] >= "2021-01-04") & (mdf["date"] <= cutoff_date)].copy()

    bench = pd.read_parquet(W1_BASE / "v20_daily_bench_20210104_20261125.parquet")
    bench["date"] = bench["trade_date"].astype(str)
    bench["csi300_ret"] = bench["csi300_daily_ret"].astype(np.float64)
    bench = bench[(bench["date"] >= "2021-01-04") & (bench["date"] <= cutoff_date)].copy()

    panel = bench[["date", "csi300_ret"]].merge(if_df, on="date", how="inner").merge(mdf, on="date", how="inner")
    panel = panel.sort_values("date").reset_index(drop=True)
    return panel


def simulate_variant(
    panel: pd.DataFrame,
    variant_name: str,
    instrument: str,         # "ETF_510300" or "IF"
    leverage: float,
    signal_mask: np.ndarray,
    hold_days: int = 5,
    fee_rt: float = 0.0010,  # unlevered nominal RT cost on notional (applied as fee_rt * leverage on equity)
    sl_nom: float = None,    # e.g. -0.02, -0.03, -0.04 on cumulative nominal contract path
    trail_act_nom: float = None,  # e.g. +0.035 prior close peak triggers trail stop
    trail_dd_nom: float = None,   # e.g. 0.018 pull-back from prior close peak
    init_margin_rate: float = 0.145,  # broker initial margin (12% exch + 2.5% broker)
    maint_margin_rate: float = 0.120, # CFFEX exchange 12% maintenance margin
    roll_slip_nom: float = 0.0002,    # 2bps nominal rollover cost if holding across roll day
    sl_close_today_extra: float = 0.00023, # extra 万2.3 if intraday SL triggers on entry day
    sl_slip_nom: float = 0.0005,      # extra 5bps stop execution slippage
    start_date: str = "2021-01-04",
) -> tuple[pd.DataFrame, np.ndarray]:
    """Simulate strict single-slot sequential futures/ETF strategy with intraday low MTM & liquidation check."""
    dates = panel["date"].to_numpy()
    n_cal = len(dates)
    dt_to_idx = {str(d): i for i, d in enumerate(dates)}

    if instrument == "ETF_510300":
        p_open = panel["etf_510300_open_hfq"].to_numpy(dtype=np.float64)
        p_high = panel["etf_510300_high_hfq"].to_numpy(dtype=np.float64)
        p_low = panel["etf_510300_low_hfq"].to_numpy(dtype=np.float64)
        p_close = panel["etf_510300_close_hfq"].to_numpy(dtype=np.float64)
        prev_c = np.concatenate([[np.nan], p_close[:-1]])
        is_roll = np.zeros(n_cal, dtype=bool)
        code = "510300"
        name = "沪深300ETF"
    else:
        p_open = panel["open"].to_numpy(dtype=np.float64)
        p_high = panel["high"].to_numpy(dtype=np.float64)
        p_low = panel["low"].to_numpy(dtype=np.float64)
        p_close = panel["close"].to_numpy(dtype=np.float64)
        prev_c = panel["same_contract_prev_close"].to_numpy(dtype=np.float64)
        is_roll = panel["is_roll_day"].to_numpy(dtype=bool)
        code = "IF0"
        name = "沪深300股指期货IF"

    half_fee = fee_rt * 0.5
    trades = []
    daily_mtm_rets = np.zeros(n_cal, dtype=np.float64)

    busy_until_idx = -1
    for i0 in range(n_cal):
        if dates[i0] < start_date or i0 <= busy_until_idx:
            continue
        if not signal_mask[i0]:
            continue
        # Check at least can close on i0 if held; need >=1 bar
        if not np.isfinite(p_open[i0]) or p_open[i0] <= 0:
            continue

        target_exit = min(i0 + hold_days - 1, n_cal - 1)
        # Position opens at 09:25/09:30 open[i0]
        # Fixed contract notional at entry = leverage * 1.0
        N0 = float(leverage)
        E_start = 1.0
        # Entry cost deducted immediately at open
        entry_fee_eq = N0 * half_fee
        E_prev = E_start - entry_fee_eq
        cum_nom_close = 0.0  # nominal return relative to entry open[i0]
        max_prior_close_nom = 0.0

        min_eq_intraday = E_prev
        min_margin_ratio_intraday = (E_prev / N0) if N0 > 0 else 1.0
        max_margin_dd_pct = 0.0
        hit_mc_140 = False
        hit_mc_145 = False
        hit_mc_150 = False
        hit_liq_12 = False
        hit_wipeout = False
        sl_triggered = False
        tp_triggered = False
        exit_reason = f"H{hold_days}_CLOSE"
        exit_idx = target_exit
        exit_hhmm = 1500
        mtm_pairs = []

        for d in range(i0, target_exit + 1):
            E_day_start = E_prev
            if d == i0:
                ref_p = p_open[i0]
                day_open_ret = 0.0
                day_low_ret = p_low[i0] / ref_p - 1.0
                day_close_ret = p_close[i0] / ref_p - 1.0
                day_high_ret = p_high[i0] / ref_p - 1.0
                roll_cost_eq = 0.0
            else:
                # Rollover handling: roll occurs at close[d-1] -> open[d] on dom_contract[d],
                # using rollover-free same_contract_prev_close[d]
                ref_p = prev_c[d]
                day_open_ret = p_open[d] / ref_p - 1.0
                day_low_ret = p_low[d] / ref_p - 1.0
                day_close_ret = p_close[d] / ref_p - 1.0
                day_high_ret = p_high[d] / ref_p - 1.0
                roll_cost_eq = (N0 * roll_slip_nom) if (instrument == "IF" and is_roll[d]) else 0.0

            # Nominal cumulative points along held contract path (anchored at prior close cum_nom_close)
            nom_factor_prev = 1.0 + cum_nom_close
            nom_open = nom_factor_prev * (1.0 + day_open_ret) - 1.0
            nom_low = nom_factor_prev * (1.0 + day_low_ret) - 1.0
            nom_high = nom_factor_prev * (1.0 + day_high_ret) - 1.0
            nom_close = nom_factor_prev * (1.0 + day_close_ret) - 1.0

            # Trailing TP threshold (only armed from prior days' peak close >= trail_act_nom -> exit at open/intraday if breached)
            eff_stop_nom = sl_nom
            if d > i0 and trail_act_nom is not None and trail_dd_nom is not None:
                if max_prior_close_nom >= trail_act_nom:
                    trail_lvl = max_prior_close_nom - trail_dd_nom
                    if eff_stop_nom is None or trail_lvl > eff_stop_nom:
                        eff_stop_nom = trail_lvl

            # Check stop/trail on day d (open gap first, then intraday low)
            # Note: evaluate margin call & liquidation BEFORE exit if gap/low already exceeds liquidation threshold!
            triggered_exit_today = False
            exec_nom_today = nom_close
            today_fee_eq = N0 * half_fee  # will only subtract on exit day

            # Worst point before planned exit if we wait through low
            # If sl triggers at eff_stop_nom (or nom_open if gapped below), trader only experiences down to exec_nom
            worst_nom_for_margin = nom_low
            if eff_stop_nom is not None and nom_low <= eff_stop_nom:
                # Could gap below sl at open on d > i0
                if d > i0 and nom_open <= eff_stop_nom:
                    exec_nom_today = nom_open - sl_slip_nom
                else:
                    exec_nom_today = eff_stop_nom - sl_slip_nom
                worst_nom_for_margin = exec_nom_today
                triggered_exit_today = True
                if sl_nom is not None and eff_stop_nom <= sl_nom + 1e-9:
                    sl_triggered = True
                    exit_reason = f"SL_{int(round(abs(sl_nom)*100))}pct"
                else:
                    tp_triggered = True
                    exit_reason = "TRAIL_TP"
                exit_hhmm = 1100 if d > i0 and nom_open > eff_stop_nom else (930 if d > i0 else 1400)

            # Compute equity at worst intraday point encountered before stop/exit
            pnl_worst_to_date = N0 * (worst_nom_for_margin - cum_nom_close)
            E_low_worst = E_prev - roll_cost_eq + pnl_worst_to_date
            notional_worst = N0 * (1.0 + worst_nom_for_margin)
            if notional_worst > 0:
                mr_low = E_low_worst / notional_worst
            else:
                mr_low = -1.0
            min_eq_intraday = min(min_eq_intraday, E_low_worst)
            min_margin_ratio_intraday = min(min_margin_ratio_intraday, mr_low)
            max_margin_dd_pct = max(max_margin_dd_pct, max(0.0, (E_start - min_eq_intraday) / E_start * 100.0))

            if instrument == "IF":
                if E_low_worst <= 0.0:
                    hit_wipeout = True
                if mr_low < 0.140:
                    hit_mc_140 = True
                if mr_low < init_margin_rate:
                    hit_mc_145 = True
                if mr_low < 0.150:
                    hit_mc_150 = True
                if mr_low <= maint_margin_rate:
                    hit_liq_12 = True

            # Forced broker liquidation wins if stopping at eff_stop_nom still breaches 12% maintenance margin
            # (meaning liquidation price was reached BEFORE the looser stop-loss price), OR if no stop triggered!
            if instrument == "IF" and mr_low <= maint_margin_rate:
                # Solve nominal loss threshold where (E_prev - roll + N0*(x - cum_prev)) / (N0*(1+x)) == maint_margin_rate
                # i.e. E_prev - roll + N0*(x - cum_prev) = m * N0 * (1 + x) => N0*(1-m)*x = m*N0 - E_prev + roll + N0*cum_prev
                denom = N0 * (1.0 - maint_margin_rate)
                x_liq = (maint_margin_rate * N0 - (E_prev - roll_cost_eq) + N0 * cum_nom_close) / denom if denom > 0 else worst_nom_for_margin
                # If gapped past liquidation at open, liquidate at open minus impact
                if d > i0 and (E_prev - roll_cost_eq + N0 * (nom_open - cum_nom_close)) <= maint_margin_rate * N0 * (1.0 + nom_open):
                    x_liq = nom_open - 0.0010
                else:
                    x_liq = x_liq - 0.0010  # 10bps liquidation impact
                E_exit = max(0.0, E_prev - roll_cost_eq + N0 * (x_liq - cum_nom_close) - today_fee_eq - (N0 * sl_close_today_extra if d == i0 else 0.0))
                exit_idx = d
                exit_reason = "FORCED_LIQ_12PCT"
                exit_hhmm = 1330
                sl_triggered = False
                tp_triggered = False
                d_ret = (E_exit / E_start - 1.0) if d == i0 else (E_exit / E_prev - 1.0)
                mtm_pairs.append((str(dates[d]), float(d_ret)))
                E_prev = E_exit
                break

            if triggered_exit_today:
                extra_ct = (N0 * sl_close_today_extra) if (instrument == "IF" and d == i0) else 0.0
                E_exit = max(0.0, E_prev - roll_cost_eq + N0 * (exec_nom_today - cum_nom_close) - today_fee_eq - extra_ct)
                exit_idx = d
                d_ret = (E_exit / E_start - 1.0) if d == i0 else (E_exit / E_prev - 1.0)
                mtm_pairs.append((str(dates[d]), float(d_ret)))
                E_prev = E_exit
                break

            # Otherwise normal hold through close[d]
            E_close = max(0.0, E_prev - roll_cost_eq + N0 * (nom_close - cum_nom_close))
            if d == target_exit:
                E_close = max(0.0, E_close - today_fee_eq)
                exit_idx = d
                exit_hhmm = 1500
            d_ret = (E_close / E_start - 1.0) if d == i0 else (E_close / E_prev - 1.0)
            mtm_pairs.append((str(dates[d]), float(d_ret)))
            E_prev = E_close
            cum_nom_close = nom_close
            max_prior_close_nom = max(max_prior_close_nom, nom_close)
            if E_close <= 0.0:
                hit_wipeout = True
                exit_idx = d
                exit_reason = "WIPEOUT"
                break

        net_ret = E_prev / E_start - 1.0
        # Verify exact trade MTM product equals 1 + net_ret
        mtm_prod = float(np.prod([1.0 + r for _, r in mtm_pairs]))
        assert abs(mtm_prod - (1.0 + net_ret)) < 1e-10, f"MTM mismatch on {dates[i0]}: {mtm_prod} vs {1+net_ret}"

        for dt_s, dr_v in mtm_pairs:
            idx_d = dt_to_idx[dt_s]
            daily_mtm_rets[idx_d] = (1.0 + daily_mtm_rets[idx_d]) * (1.0 + dr_v) - 1.0

        trades.append({
            "variant": variant_name,
            "instrument": instrument,
            "leverage": float(leverage),
            "fee_bps": round(fee_rt * 10000.0, 1),
            "buy_date": str(dates[i0]),
            "exit_date": str(dates[exit_idx]),
            "buy_hhmm": 925,
            "exit_hhmm": int(exit_hhmm),
            "code": code,
            "name": name,
            "hold_days_actual": int(exit_idx - i0 + 1),
            "exit_reason": exit_reason,
            "v3_live_t1": float(panel.loc[i0, "nt_v3_score_live_t1"]),
            "v3_eod_t1": float(panel.loc[i0, "nt_v3_score_eod_t1"]),
            "basis_pct_entry": round(float(panel.loc[i0, "basis_pct"]), 4) if pd.notna(panel.loc[i0, "basis_pct"]) else np.nan,
            "net_ret": float(net_ret),
            "min_eq_intraday": round(float(min_eq_intraday), 5),
            "min_margin_ratio_pct": round(float(min_margin_ratio_intraday * 100.0), 3),
            "max_margin_dd_pct": round(float(max_margin_dd_pct), 2),
            "hit_mc_140": bool(hit_mc_140),
            "hit_mc_145": bool(hit_mc_145),
            "hit_mc_150": bool(hit_mc_150),
            "hit_forced_liq_12": bool(hit_liq_12),
            "hit_wipeout": bool(hit_wipeout),
            "sl_triggered": bool(sl_triggered),
            "tp_triggered": bool(tp_triggered),
            "mtm_pairs_json": json.dumps([[dt_s, round(dr_v, 10)] for dt_s, dr_v in mtm_pairs]),
        })
        busy_until_idx = exit_idx

    return pd.DataFrame(trades), daily_mtm_rets


def full_eval_package(
    panel: pd.DataFrame,
    trades_df: pd.DataFrame,
    daily_mtm_rets: np.ndarray,
    neg_ctrl_summary: dict = None,
) -> dict:
    cal_dates = panel["date"].to_numpy(dtype=str)
    bench_rets = panel["csi300_ret"].to_numpy(dtype=np.float64)
    end_dt = str(cal_dates[-1])

    # D15 4 windows: 5Y, Near 3Y (WF 2023-2026), 2026, 26H2
    d15 = {}
    for wkey, wstart in [("W_5Y_2021_2026", "2021-01-04"), ("W_3Y_2023_2026", "2023-01-03"), ("W_2026", "2026-01-05"), ("W_26H2", "2026-07-01")]:
        d15[wkey] = gsl.compute_window_d15_metrics(trades_df, daily_mtm_rets, cal_dates, bench_rets, wstart, end_dt)

    # Futures margin / liquidation risk summary across all trades
    if len(trades_df) > 0:
        margin_audit = {
            "n_trades_5y": int(len(trades_df)),
            "max_intraday_margin_dd_pct": round(float(trades_df["max_margin_dd_pct"].max()), 2),
            "mean_intraday_margin_dd_pct": round(float(trades_df["max_margin_dd_pct"].mean()), 2),
            "min_margin_ratio_pct": round(float(trades_df["min_margin_ratio_pct"].min()), 3),
            "mc_140_count": int(trades_df["hit_mc_140"].sum()),
            "mc_145_count": int(trades_df["hit_mc_145"].sum()),
            "mc_145_rate_pct": round(float(trades_df["hit_mc_145"].mean() * 100.0), 2),
            "mc_150_count": int(trades_df["hit_mc_150"].sum()),
            "forced_liq_12_count": int(trades_df["hit_forced_liq_12"].sum()),
            "forced_liq_12_rate_pct": round(float(trades_df["hit_forced_liq_12"].mean() * 100.0), 2),
            "wipeout_count": int(trades_df["hit_wipeout"].sum()),
            "sl_trigger_count": int(trades_df["sl_triggered"].sum()),
            "tp_trigger_count": int(trades_df["tp_triggered"].sum()),
        }
    else:
        margin_audit = {"n_trades_5y": 0}

    tests4 = gsl.run_four_small_sample_tests(
        trades_df, daily_mtm_rets, cal_dates, bench_rets,
        ret_col="net_ret", neg_ctrl_summary=neg_ctrl_summary, seed=20261126,
    )
    return {
        "d15": d15,
        "margin_audit": margin_audit,
        "four_small_sample_tests": tests4,
    }


def make_signals(panel: pd.DataFrame):
    v3l = panel["nt_v3_score_live_t1"].to_numpy(dtype=np.float64)
    v3e = panel["nt_v3_score_eod_t1"].to_numpy(dtype=np.float64)
    r1 = panel["mkt_csi300_ret1d_t1"].to_numpy(dtype=np.float64)
    rsi = panel["th_tech_csi300_rsi14_t1"].to_numpy(dtype=np.float64)
    ewb = panel["L1_ew_bias20_t1"].to_numpy(dtype=np.float64)

    panic = (r1 <= -0.012) | (rsi < 38.0) | (ewb < -0.04)
    return {
        "V3Live_ge60": (v3l >= 60.0),
        "V3Live_ge65": (v3l >= 65.0),
        "V3Live_ge70": (v3l >= 70.0),
        "V3Live_ge75": (v3l >= 75.0),
        "V3EOD_ge60": (v3e >= 60.0),
        "V3EOD_ge65": (v3e >= 65.0),
        "V3Live_ge60_Panic": (v3l >= 60.0) & panic,
        "V3Live_ge65_Panic": (v3l >= 65.0) & panic,
        "NegCtrl_V3Live_lt40": (v3l < 40.0),
    }


def build_configs(sigs: dict):
    """Build baseline + 6-tier leverage comparison + clean low-DOF polish grid."""
    configs = []

    # Group A: 6-tier leverage comparison on baseline (V3Live >= 60, H5, No SL)
    configs.append(("A_ETF510300_1x_V3Live60_H5", "ETF_510300", 1.0, "V3Live_ge60", 5, 0.0005, None, None, None))
    for lev in (1.0, 3.0, 5.0, 6.0, 7.0):
        configs.append((f"A_IF_{int(lev)}x_V3Live60_H5_NoSL_10bps", "IF", lev, "V3Live_ge60", 5, 0.0010, None, None, None))
        # Stress 20bps & SL -3%
        configs.append((f"B_IF_{int(lev)}x_V3Live60_H5_SL3_10bps", "IF", lev, "V3Live_ge60", 5, 0.0010, -0.03, None, None))
        if lev in (3.0, 5.0, 6.0):
            configs.append((f"S_IF_{int(lev)}x_V3Live60_H5_NoSL_20bps", "IF", lev, "V3Live_ge60", 5, 0.0020, None, None, None))

    # Group C: Polish grid (low DOF): Entry thresholds, Panic filter, H3/H5/H10/H20, SL -2/-3/-4%, Trail TP
    for sig_name in ("V3Live_ge60", "V3Live_ge65", "V3Live_ge70", "V3Live_ge75", "V3EOD_ge60", "V3EOD_ge65", "V3Live_ge60_Panic"):
        for H in (3, 5, 10, 20):
            for sl in (None, -0.02, -0.03, -0.04):
                for lev in (3.0, 5.0):
                    sl_lbl = "NoSL" if sl is None else f"SL{int(abs(sl)*100)}"
                    vname = f"P_IF_{int(lev)}x_{sig_name}_H{H}_{sl_lbl}"
                    configs.append((vname, "IF", lev, sig_name, H, 0.0010, sl, None, None))

    # Trailing TP test on core candidates
    for lev in (3.0, 5.0):
        for sig_name in ("V3Live_ge60", "V3Live_ge65", "V3Live_ge60_Panic"):
            configs.append((f"P_IF_{int(lev)}x_{sig_name}_H10_SL3_TrailTP", "IF", lev, sig_name, 10, 0.0010, -0.03, 0.030, 0.015))
            configs.append((f"P_IF_{int(lev)}x_{sig_name}_H5_SL3_TrailTP", "IF", lev, sig_name, 5, 0.0010, -0.03, 0.025, 0.012))

    return configs


def main():
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = load_panel("2026-11-25")
    sigs = make_signals(panel)

    # First check Track C exact WF parity (2023-01-03..2026-11-25)
    t_etf_wf, _ = simulate_variant(panel, "W2B5_PARITY", "ETF_510300", 1.0, sigs["V3Live_ge60"], 5, 0.0005, start_date="2023-01-03")
    wf_nav_check = float((1.0 + t_etf_wf["net_ret"]).prod())
    print(f"Track C WF parity check: n={len(t_etf_wf)}, wr={(t_etf_wf['net_ret']>0).mean()*100:.2f}%, nav={wf_nav_check:.4f}")

    # Negative controls: V3Live < 40 on normal days for 1x, 3x, 5x, 6x, 7x (H5 & H10)
    neg_ctrls = {}
    for lev in (1.0, 3.0, 5.0, 6.0, 7.0):
        for H in (5, 10):
            for sl in (None, -0.03):
                nc_t, nc_mtm = simulate_variant(panel, f"NegCtrl_{int(lev)}x_H{H}", "IF", lev, sigs["NegCtrl_V3Live_lt40"], H, 0.0010, sl, start_date="2021-01-04")
                nc_r = nc_t["net_ret"].to_numpy(dtype=np.float64)
                sd = float(np.std(nc_mtm, ddof=1)) if len(nc_mtm) > 1 else 0.0
                nc_sh = float(np.mean(nc_mtm) / sd * np.sqrt(252.0)) if sd > 1e-12 else 0.0
                neg_ctrls[(lev, H, sl)] = {
                    "rule": "nt_v3_score_live_t1 < 40 (normal days)",
                    "n_trades_5y": int(len(nc_t)),
                    "wr_5y_pct": round(float((nc_r > 0).mean() * 100.0), 2) if len(nc_r) else 0.0,
                    "mean_ret_pct": round(float(nc_r.mean() * 100.0), 3) if len(nc_r) else 0.0,
                    "nav_5y": round(float(np.prod(1.0 + nc_r)), 4),
                    "sharpe_5y": round(nc_sh, 3),
                    "forced_liq_12_rate_pct": round(float(nc_t["hit_forced_liq_12"].mean() * 100.0), 2) if len(nc_t) else 0.0,
                }

    configs = build_configs(sigs)
    # Deduplicate variant names
    seen = set()
    uniq_configs = []
    for c in configs:
        if c[0] not in seen:
            seen.add(c[0])
            uniq_configs.append(c)

    results = {}
    summary_rows = []
    trade_tables = []

    for vname, inst, lev, sig_key, H, fee, sl, tr_act, tr_dd in uniq_configs:
        tdf, mtm = simulate_variant(
            panel, vname, inst, lev, sigs[sig_key], H, fee, sl, tr_act, tr_dd, start_date="2021-01-04"
        )
        nc_key = (lev, H if H in (5, 10) else 5, sl if sl == -0.03 else None)
        eval_pkg = full_eval_package(panel, tdf, mtm, neg_ctrl_summary=neg_ctrls.get(nc_key, {}))
        results[vname] = {
            "params": {"instrument": inst, "leverage": lev, "signal": sig_key, "hold_days": H, "fee_bps": round(fee * 10000, 1), "sl_nom": sl, "trail_act_nom": tr_act, "trail_dd_nom": tr_dd},
            **eval_pkg,
        }
        w5 = eval_pkg["d15"]["W_5Y_2021_2026"]
        w3 = eval_pkg["d15"]["W_3Y_2023_2026"]
        w26 = eval_pkg["d15"]["W_2026"]
        w26h2 = eval_pkg["d15"]["W_26H2"]
        ma = eval_pkg["margin_audit"]
        b1 = eval_pkg["four_small_sample_tests"]["test1_bootstrap_10k"]
        summary_rows.append({
            "variant": vname,
            "inst": inst,
            "lev": lev,
            "signal": sig_key,
            "H": H,
            "fee_bps": round(fee * 10000, 1),
            "sl_nom": sl,
            "n_5y": w5["n_trades"],
            "wr_5y": w5["wr_pct"],
            "nav_5y": w5["mtm_nav"],
            "ex5_5y": w5["ex5_nav"],
            "mdd_5y": w5["mdd_pct"],
            "sharpe_5y": w5["sharpe"],
            "excess_5y_pp": w5["excess_csi300_pp"],
            "n_3y": w3["n_trades"],
            "nav_3y": w3["mtm_nav"],
            "sharpe_3y": w3["sharpe"],
            "excess_3y_pp": w3["excess_csi300_pp"],
            "nav_2026": w26["mtm_nav"],
            "nav_26H2": w26h2["mtm_nav"],
            "mc_145_rate": ma.get("mc_145_rate_pct", 0.0),
            "liq_12_rate": ma.get("forced_liq_12_rate_pct", 0.0),
            "max_margin_dd": ma.get("max_intraday_margin_dd_pct", 0.0),
            "boot_p_pos": b1.get("prob_positive_expectancy_pct", 0.0),
            "boot_mean_p05": b1.get("mean_ret_pct_p05", 0.0),
        })
        # Save trades for key comparison set + top polished variants into rd048_gem4_trades.parquet
        if len(tdf) > 0:
            trade_tables.append(tdf)

    sum_df = pd.DataFrame(summary_rows)
    # Identify best safe polished variants (liq_12_rate == 0, n_5y >= 15, highest Sharpe_5Y / Calmar)
    safe_df = sum_df[(sum_df["inst"] == "IF") & (sum_df["liq_12_rate"] == 0.0) & (sum_df["fee_bps"] == 10.0) & (sum_df["n_5y"] >= 15)].copy()
    best_safe_3x = safe_df[safe_df["lev"] == 3.0].sort_values(["sharpe_5y", "nav_5y"], ascending=False).head(3).to_dict(orient="records")
    best_safe_5x = safe_df[safe_df["lev"] == 5.0].sort_values(["sharpe_5y", "nav_5y"], ascending=False).head(3).to_dict(orient="records")

    # Select key variants to export in detailed JSON & verify 2024-12-31 truncation zero leakage
    key_variants = [
        "A_ETF510300_1x_V3Live60_H5",
        "A_IF_1x_V3Live60_H5_NoSL_10bps",
        "A_IF_3x_V3Live60_H5_NoSL_10bps",
        "A_IF_5x_V3Live60_H5_NoSL_10bps",
        "A_IF_6x_V3Live60_H5_NoSL_10bps",
        "A_IF_7x_V3Live60_H5_NoSL_10bps",
        "B_IF_3x_V3Live60_H5_SL3_10bps",
        "B_IF_5x_V3Live60_H5_SL3_10bps",
        "B_IF_6x_V3Live60_H5_SL3_10bps",
        "B_IF_7x_V3Live60_H5_SL3_10bps",
        "S_IF_3x_V3Live60_H5_NoSL_20bps",
        "S_IF_5x_V3Live60_H5_NoSL_20bps",
    ]
    for r in best_safe_3x[:2] + best_safe_5x[:2]:
        if r["variant"] not in key_variants:
            key_variants.append(r["variant"])

    # Physical Truncation Test: 2024-12-31
    panel_trunc = load_panel("2024-12-31")
    sigs_trunc = make_signals(panel_trunc)
    trunc_results = {}
    max_trunc_diff_all = 0.0
    cfg_map = {c[0]: c for c in uniq_configs}

    for vn in key_variants:
        _, inst, lev, sig_key, H, fee, sl, tr_act, tr_dd = cfg_map[vn]
        t_full, mtm_full = simulate_variant(panel, vn, inst, lev, sigs[sig_key], H, fee, sl, tr_act, tr_dd, start_date="2021-01-04")
        t_tr, mtm_tr = simulate_variant(panel_trunc, vn, inst, lev, sigs_trunc[sig_key], H, fee, sl, tr_act, tr_dd, start_date="2021-01-04")
        # Compare all trades resolved <= 2024-12-31 AND daily MTM <= 2024-12-31 (on trades entering & exiting <= 2024-12-31)
        f_sub = t_full[t_full["exit_date"] <= "2024-12-31"].reset_index(drop=True)
        tr_sub = t_tr[t_tr["exit_date"] <= "2024-12-31"].reset_index(drop=True)
        n_diff = abs(len(f_sub) - len(tr_sub))
        ret_diff = float(np.max(np.abs(f_sub["net_ret"].to_numpy() - tr_sub["net_ret"].to_numpy()))) if (n_diff == 0 and len(f_sub) > 0) else (0.0 if n_diff == 0 else 999.0)
        n_tr_days = len(panel_trunc)
        mtm_trunc_diff = float(np.max(np.abs(mtm_full[:n_tr_days] - mtm_tr[:n_tr_days])))
        max_v = max(ret_diff, mtm_trunc_diff)
        max_trunc_diff_all = max(max_trunc_diff_all, max_v)
        trunc_results[vn] = {
            "n_resolved_le_20241231": int(len(f_sub)),
            "count_diff": int(n_diff),
            "trade_ret_max_abs_diff": float(ret_diff),
            "mtm_daily_max_abs_diff": float(mtm_trunc_diff),
            "pass": bool(max_v == 0.0),
        }

    # Save parquet (all key variants + all Group A/B/S + best polished variants for Wave 2)
    all_trades_df = pd.concat(trade_tables, ignore_index=True)
    trades_pq = OUT_DIR / "rd048_gem4_trades.parquet"
    all_trades_df.to_parquet(trades_pq, index=False)

    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": round(peak_rss_mb, 2),
        "d12_yfinance_imported": False,
        "w2b5_track_c_wf_parity_check": {
            "variant": "C_510300_V3Live_ge60_H5 (WF >= 2023-01-03)",
            "n_trades": int(len(t_etf_wf)),
            "wr_pct": round(float((t_etf_wf["net_ret"] > 0).mean() * 100.0), 2),
            "nav_wf": round(wf_nav_check, 4),
            "w2b5_reported": {"n_trades": 15, "wr_pct": 73.33, "nav_wf": 1.3395},
        },
        "six_tier_leverage_table": summary_rows[:21],
        "best_safe_polished_3x": best_safe_3x,
        "best_safe_polished_5x": best_safe_5x,
        "key_variants_full_eval": {k: results[k] for k in key_variants},
        "truncation_20241231_audit": {
            "max_abs_diff_all_key_variants": float(max_trunc_diff_all),
            "all_pass": bool(max_trunc_diff_all == 0.0),
            "details": trunc_results,
        },
        "all_variants_summary": summary_rows,
        "outputs": {
            "trades_parquet": str(trades_pq),
            "total_trade_rows_saved": int(len(all_trades_df)),
        },
    }
    out_json = OUT_DIR / "rd048_gem4_if_futures.json"
    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"DONE step2_run_gem4_if_backtest in {out['elapsed_sec']}s | peak RSS={out['peak_rss_mb']} MB | trunc max_abs_diff={max_trunc_diff_all}")
    print("\n=== 6-Tier Leverage Comparison (V3Live >= 60, H5) ===")
    cols_show = ["variant", "n_5y", "wr_5y", "nav_5y", "ex5_5y", "mdd_5y", "sharpe_5y", "excess_5y_pp", "n_3y", "nav_3y", "nav_2026", "mc_145_rate", "liq_12_rate", "max_margin_dd", "boot_p_pos"]
    print(sum_df[sum_df["variant"].str.startswith(("A_", "B_IF_"))][cols_show].to_string(index=False))
    print("\n=== Best Safe Polished 3x & 5x (liq==0) ===")
    print(pd.DataFrame(best_safe_3x + best_safe_5x)[cols_show].to_string(index=False))


if __name__ == "__main__":
    main()

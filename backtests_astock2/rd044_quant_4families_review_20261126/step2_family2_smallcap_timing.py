#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD044 Step 2 — Family 2: Small-Cap / Micro-Cap Toxic-Notice Screening + Pure Causal Crowding/Momentum Risk Switches
Tests >=30m & >=50m liquidity floors (and >=100m stress), strict 20d toxic-notice exclusion,
4D small-cap quality composite, and pure causal switches during 2024 Jan-Feb DMA crash & 2024 Apr GuoJiuTiao.
Zero yfinance (D12). Peak RAM < 1.5 GB.
"""
import gc
import json
import os
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
import step1_family1_xs_stat_rev as f1

BASE_DIR = cm.BASE_DIR
CACHE_DIR = cm.CACHE_DIR


def load_smallcap_panel(end_dt: str = "2026-11-24") -> dict:
    """Load Family 1 dense panel + attach free_mcap_yi_t1, mcap_yi_t1, and exact causal 20d tox_pre mask."""
    panel = f1.load_dense_market_panel(end_dt=end_dt)
    cal_dts = panel["cal_dts"]
    dt_map = {d: i for i, d in enumerate(cal_dts)}
    stk_map = {s: i for i, s in enumerate(panel["stocks"])}
    N_D, N_S = panel["N_D"], panel["N_S"]

    df_m = pq.read_table(
        f"{BASE_DIR}/stock_day_core_features_pit.parquet",
        columns=["dt", "c6", "free_mcap_yi_t1", "mcap_yi_t1", "tox_reg_30d_pre"],
        filters=[("dt", "<=", end_dt)],
    ).to_pandas()
    di = df_m["dt"].cat.codes.values.astype(np.int32)
    si = df_m["c6"].cat.codes.values.astype(np.int32)

    fmcap = np.full((N_D, N_S), np.nan, dtype=np.float32)
    fmcap[di, si] = df_m["free_mcap_yi_t1"].values.astype(np.float32)
    mcap = np.full((N_D, N_S), np.nan, dtype=np.float32)
    mcap[di, si] = df_m["mcap_yi_t1"].values.astype(np.float32)
    tox30 = np.zeros((N_D, N_S), dtype=bool)
    tox30[di, si] = df_m["tox_reg_30d_pre"].values > 0
    del df_m
    gc.collect()

    # Exact strict 20-trading-day toxic-notice mask from Step 0 cache (buy_date <= end_dt)
    tox20 = np.zeros((N_D, N_S), dtype=bool)
    tox_p = f"{CACHE_DIR}/tox_notices_pit.parquet"
    if os.path.exists(tox_p):
        tdf = pd.read_parquet(tox_p)
        tdf = tdf[tdf["buy_date"] <= end_dt].copy()
        cal_arr = np.array(cal_dts)
        for c6_v, b_dt in tdf[["c6", "buy_date"]].itertuples(index=False, name=None):
            s_i = stk_map.get(c6_v)
            if s_i is None:
                continue
            d_i = int(np.searchsorted(cal_arr, b_dt, side="left"))
            if d_i < N_D:
                tox20[d_i : min(N_D, d_i + 20), s_i] = True

    panel["free_mcap_yi_t1"] = fmcap
    panel["mcap_yi_t1"] = mcap
    panel["tox_20d"] = tox20 | tox30
    return panel


def build_causal_risk_switches(panel: dict, end_dt: str = "2026-11-25") -> dict:
    """
    Build strictly causal T-1 risk-off boolean masks + 511010 Bond ETF daily return series for defensive switch.
    """
    cal_dts = panel["cal_dts"]
    N_D = panel["N_D"]
    mkt = pd.read_parquet(f"{BASE_DIR}/market_daily_all_new_factors_pit.parquet")
    mkt = mkt[mkt["trade_date"] <= end_dt].copy()
    mkt_map = mkt.set_index("trade_date")

    # Compute causal small-cap bottom-400 equal-weight index return & crowding (purely from <= T-1)
    # Use free_mcap_yi_t1 bottom 400 eligible non-ST >=30m stocks on each day T-1
    elig_base = (~panel["is_st"]) & (panel["list_age"] >= 60) & panel["tradable"] & (panel["amt20_t1"] >= 0.30) & np.isfinite(panel["free_mcap_yi_t1"])
    fm = panel["free_mcap_yi_t1"]
    adj_c = panel["adj_close"]
    trad = panel["tradable"]

    # Causal T-1 daily return of bottom-400 small-cap proxy & turnover crowding
    sc_ret_t1 = np.zeros(N_D, dtype=np.float64)
    sc_amt_share_t1 = np.full(N_D, np.nan, dtype=np.float64)
    for d in range(1, N_D):
        # Strictly T-1 = d-1
        m_prev = elig_base[d - 1]
        idx = np.flatnonzero(m_prev)
        if len(idx) < 50:
            continue
        sub_fm = fm[d - 1, idx]
        bot = idx[np.argsort(sub_fm)[:400]]
        if d >= 2:
            ok_r = trad[d - 1, bot] & trad[d - 2, bot] & (adj_c[d - 2, bot] > 0)
            if ok_r.sum() >= 20:
                r_vec = adj_c[d - 1, bot[ok_r]] / adj_c[d - 2, bot[ok_r]] - 1.0
                sc_ret_t1[d] = float(np.clip(np.mean(r_vec), -0.25, 0.25))
        # Crowding: bottom-400 dollar share of total market at T-1
        tot_amt = float(np.nansum(panel["amt_t1"][d]))
        bot_amt = float(np.nansum(panel["amt_t1"][d, bot]))
        if tot_amt > 1.0:
            sc_amt_share_t1[d] = bot_amt / tot_amt

    # Build T-1 causal index level & MA20 / Mom20 (at day d, index reflects up to d-1 close!)
    sc_idx = np.cumprod(1.0 + sc_ret_t1)
    sw_mom20 = np.zeros(N_D, dtype=bool)
    sw_dt_panic = np.zeros(N_D, dtype=bool)
    sw_crowd = np.zeros(N_D, dtype=bool)
    sw_combo = np.zeros(N_D, dtype=bool)

    dt_cnt_t1 = np.array([float(mkt_map.loc[d, "L1_dt_cnt_t1"]) if d in mkt_map.index else 0.0 for d in cal_dts])
    ew_ret20_t1 = np.array([float(mkt_map.loc[d, "L1_ew_ret20_t1"]) if d in mkt_map.index else 0.0 for d in cal_dts])

    panic_cool = 0
    for d in range(25, N_D):
        # 1. Small-cap proxy 20d momentum < -4% OR EW_ret20 < -6%
        sc_m20 = sc_idx[d] / sc_idx[d - 20] - 1.0
        sc_ma20 = float(np.mean(sc_idx[d - 19 : d + 1]))
        sw_mom20[d] = (sc_m20 < -0.04) or (sc_idx[d] < sc_ma20 * 0.97)

        # 2. Limit-down panic switch (dt_cnt_t1 >= 35 triggers exit until < 15 for 3 straight days)
        if dt_cnt_t1[d] >= 35.0:
            panic_cool = 3
            sw_dt_panic[d] = True
        elif panic_cool > 0:
            sw_dt_panic[d] = True
            if dt_cnt_t1[d] < 15.0:
                panic_cool -= 1
            else:
                panic_cool = 3

        # 3. Causal crowding overheat (>90th pct trailing 250d of small-cap amt share AND negative 10d mom)
        if d >= 60 and np.isfinite(sc_amt_share_t1[d]):
            w_sh = sc_amt_share_t1[max(1, d - 250) : d + 1]
            w_sh = w_sh[np.isfinite(w_sh)]
            if len(w_sh) >= 40:
                pct_sh = float(np.mean(w_sh <= sc_amt_share_t1[d]))
                sc_m10 = sc_idx[d] / sc_idx[d - 10] - 1.0
                if pct_sh >= 0.90 and sc_m10 < -0.01:
                    sw_crowd[d] = True

        sw_combo[d] = sw_mom20[d] or sw_dt_panic[d] or sw_crowd[d]

    # Load 511010 Bond ETF daily return (open-to-open / close-to-close) for risk-off parking
    etf_df = pd.read_parquet(f"{RD044_DIR}/etf_daily_qfq_cache.parquet")
    b511 = etf_df[etf_df["code"] == "511010"].sort_values("dt").copy()
    b511["ret_1d"] = b511["close"].pct_change().fillna(0.0)
    b511_map = dict(zip(b511["dt"], b511["ret_1d"]))
    bond_dr = np.array([float(b511_map.get(d, 0.0)) for d in cal_dts], dtype=np.float64)

    return {
        "SW_NONE": np.zeros(N_D, dtype=bool),
        "SW_MOM20": sw_mom20,
        "SW_DT_PANIC": sw_dt_panic,
        "SW_CROWD": sw_crowd,
        "SW_COMBO": sw_combo,
        "bond_511010_dr": bond_dr,
    }


def apply_defensive_bond_return(sim: dict, risk_off_mask: np.ndarray, bond_dr: np.ndarray, etf_fee_rt: float = 0.0005) -> np.ndarray:
    """When risk_off_mask is True and portfolio is flat (~active), earn 511010 Bond ETF return (charging 5bps on switches)."""
    dr = sim["dr"].copy()
    # Strictly only on days where strategy is NOT holding equities and risk_off_mask is True
    in_bond = risk_off_mask & (~sim["act_mask"])
    prev_b = np.concatenate(([False], in_bond[:-1]))
    sw_cost = np.where(in_bond != prev_b, etf_fee_rt * 0.5, 0.0)
    dr[in_bond] = bond_dr[in_bond] - sw_cost[in_bond]
    dr[~in_bond] = dr[~in_bond] - sw_cost[~in_bond]
    return dr


def run_family2(end_dt: str = "2026-11-24", run_trunc_check: bool = True) -> dict:
    t0 = time.time()
    bench_ctx = cm.load_bench_and_v20(end_dt=end_dt)
    end_p = end_dt
    panel = load_smallcap_panel(end_dt=end_p)
    switches = build_causal_risk_switches(panel, end_dt=end_p)

    # Eligibility masks
    base = (~panel["is_st"]) & (panel["list_age"] >= 60) & panel["tradable"] & np.isfinite(panel["free_mcap_yi_t1"])
    elig_30m_notox = base & (~panel["tox_20d"]) & (panel["amt20_t1"] >= 0.30) & (panel["amt_t1"] >= 0.15)
    elig_30m_raw = base & (panel["amt20_t1"] >= 0.30) & (panel["amt_t1"] >= 0.15)  # tox ablation
    elig_50m_notox = base & (~panel["tox_20d"]) & (panel["amt20_t1"] >= 0.50) & (panel["amt_t1"] >= 0.25)
    elig_100m_notox = base & (~panel["tox_20d"]) & (panel["amt20_t1"] >= 1.00) & (panel["amt_t1"] >= 0.50)

    # Score 1: Pure smallest free float mcap
    sc_pure_30 = -panel["free_mcap_yi_t1"]
    # Score 2: 4D Composite (small cap + low turnover + short reversal + low vol)
    z_mc_30 = f1.cross_sectional_rank_z(-panel["free_mcap_yi_t1"], elig_30m_notox)
    z_tr_30 = f1.cross_sectional_rank_z(panel["F_TURN_ABN"], elig_30m_notox)
    z_rv_30 = f1.cross_sectional_rank_z(panel["F_REV10"], elig_30m_notox)
    z_lv_30 = f1.cross_sectional_rank_z(panel["F_LOWVOL"], elig_30m_notox)
    sc_4d_30 = (0.40 * z_mc_30 + 0.20 * np.nan_to_num(z_tr_30) + 0.20 * np.nan_to_num(z_rv_30) + 0.20 * np.nan_to_num(z_lv_30)).astype(np.float32)

    z_mc_50 = f1.cross_sectional_rank_z(-panel["free_mcap_yi_t1"], elig_50m_notox)
    z_tr_50 = f1.cross_sectional_rank_z(panel["F_TURN_ABN"], elig_50m_notox)
    z_rv_50 = f1.cross_sectional_rank_z(panel["F_REV10"], elig_50m_notox)
    z_lv_50 = f1.cross_sectional_rank_z(panel["F_LOWVOL"], elig_50m_notox)
    sc_4d_50 = (0.40 * z_mc_50 + 0.20 * np.nan_to_num(z_tr_50) + 0.20 * np.nan_to_num(z_rv_50) + 0.20 * np.nan_to_num(z_lv_50)).astype(np.float32)

    results = []
    daily_series = {}

    def _run_sc(tag: str, sc_m: np.ndarray, el_m: np.ndarray, liq: str, top_k: int, reb: int, fee: float, sw_name: str = "SW_NONE", park_bond: bool = False):
        sw_mask = switches[sw_name]
        sim = f1.simulate_xs_portfolio(panel, sc_m, el_m, top_k=top_k, rebal_days=reb, fee_rt=fee, start_dt="2021-01-04", end_dt=end_dt, risk_off_mask=sw_mask)
        dr = apply_defensive_bond_return(sim, sw_mask, switches["bond_511010_dr"]) if (park_bond and sw_name != "SW_NONE") else sim["dr"]
        ev = cm.evaluate_daily_series(dr, bench_ctx, turnover_daily=sim["to_daily"], active_mask=sim["act_mask"], cap_daily_yi=sim["cap_daily_yi"])
        row = {
            "family": "F2_SmallCap",
            "strategy_id": tag,
            "liq_tier": liq,
            "top_k": top_k,
            "rebal_days": reb,
            "fee_bps": int(round(fee * 10000)),
            "switch": f"{sw_name}{'_Bond' if park_bond else ''}",
            "risk_off_days_pct": round(float(sw_mask.mean() * 100.0), 1),
            "buy_skips": sim["buy_skip_cnt"],
            "sell_locks": sim["sell_lock_cnt"],
            "windows": ev,
        }
        results.append(row)
        daily_series[tag] = dr
        return row

    # 1. Pure smallest mcap variants (>=30m & >=50m) + tox ablation
    for top_k in [20, 30, 50]:
        for reb in [5, 10]:
            _run_sc(f"F2_PURE_30m_K{top_k}_H{reb}_30bp", sc_pure_30, elig_30m_notox, ">=30m", top_k, reb, 0.0030)
            _run_sc(f"F2_PURE_50m_K{top_k}_H{reb}_30bp", sc_pure_30, elig_50m_notox, ">=50m", top_k, reb, 0.0030)
    _run_sc("F2_PURE_30m_NOTOX_ABL_K30_H10_30bp", sc_pure_30, elig_30m_raw, ">=30m_noTox", 30, 10, 0.0030)
    _run_sc("F2_PURE_100m_K30_H10_30bp", sc_pure_30, elig_100m_notox, ">=100m", 30, 10, 0.0030)

    # 2. 4D composite variants (with 30bps & 50bps)
    for top_k in [20, 30]:
        for reb in [5, 10]:
            for fee in [0.0030, 0.0050]:
                _run_sc(f"F2_4D_30m_K{top_k}_H{reb}_{int(fee*10000)}bp", sc_4d_30, elig_30m_notox, ">=30m", top_k, reb, fee)
                _run_sc(f"F2_4D_50m_K{top_k}_H{reb}_{int(fee*10000)}bp", sc_4d_50, elig_50m_notox, ">=50m", top_k, reb, fee)

    # 3. Pure causal risk switches on both PURE_30m/50m and 4D_30m/50m (K=30, H=10 & H=5)
    for sw_n in ["SW_MOM20", "SW_DT_PANIC", "SW_CROWD", "SW_COMBO"]:
        _run_sc(f"F2_PURE_30m_K30_H5_{sw_n}_Bond", sc_pure_30, elig_30m_notox, ">=30m", 30, 5, 0.0030, sw_n, True)
        _run_sc(f"F2_PURE_50m_K30_H5_{sw_n}_Bond", sc_pure_30, elig_50m_notox, ">=50m", 30, 5, 0.0030, sw_n, True)
        _run_sc(f"F2_4D_30m_K30_H5_{sw_n}_Bond", sc_4d_30, elig_30m_notox, ">=30m", 30, 5, 0.0030, sw_n, True)
        _run_sc(f"F2_4D_50m_K30_H5_{sw_n}_Bond", sc_4d_50, elig_50m_notox, ">=50m", 30, 5, 0.0030, sw_n, True)
        _run_sc(f"F2_4D_50m_K30_H5_{sw_n}_50bp_Bond", sc_4d_50, elig_50m_notox, ">=50m", 30, 5, 0.0050, sw_n, True)

    # Best >=50m Calmar/Sharpe model for truncation & 80bps check
    cand_50 = [r for r in results if r["liq_tier"] == ">=50m" and r["fee_bps"] == 30]
    best_50 = max(cand_50, key=lambda r: r["windows"]["WF_OOS"]["sharpe"])
    sw_best = best_50["switch"].replace("_Bond", "")
    is_4d = "4D" in best_50["strategy_id"]
    _run_sc(f"{best_50['strategy_id']}_80bp", sc_4d_50 if is_4d else sc_pure_30, elig_50m_notox, ">=50m", best_50["top_k"], best_50["rebal_days"], 0.0080, sw_best, "_Bond" in best_50["switch"])

    trunc_audit = {}
    if run_trunc_check:
        import subprocess
        sub_code = (
            f"import sys, numpy as np; sys.path.insert(0, {RD044_DIR!r}); "
            f"import step1_family1_xs_stat_rev as f1, step2_family2_smallcap_timing as f2; "
            f"p_tr = f2.load_smallcap_panel(end_dt='2024-12-31'); "
            f"sw_tr = f2.build_causal_risk_switches(p_tr, end_dt='2024-12-31'); "
            f"e_tr = (~p_tr['is_st']) & (p_tr['list_age'] >= 60) & p_tr['tradable'] & (~p_tr['tox_20d']) & np.isfinite(p_tr['free_mcap_yi_t1']) & (p_tr['amt20_t1'] >= 0.50) & (p_tr['amt_t1'] >= 0.25); "
            f"is_4d = {is_4d}; "
            f"sc_tr = (0.40 * f1.cross_sectional_rank_z(-p_tr['free_mcap_yi_t1'], e_tr) + 0.20 * np.nan_to_num(f1.cross_sectional_rank_z(p_tr['F_TURN_ABN'], e_tr)) + 0.20 * np.nan_to_num(f1.cross_sectional_rank_z(p_tr['F_REV10'], e_tr)) + 0.20 * np.nan_to_num(f1.cross_sectional_rank_z(p_tr['F_LOWVOL'], e_tr))).astype(np.float32) if is_4d else -p_tr['free_mcap_yi_t1']; "
            f"sim_tr = f1.simulate_xs_portfolio(p_tr, sc_tr, e_tr, top_k={best_50['top_k']}, rebal_days={best_50['rebal_days']}, fee_rt=0.0030, start_dt='2021-01-04', end_dt='2024-12-31', risk_off_mask=sw_tr[{sw_best!r}]); "
            f"dr_tr = f2.apply_defensive_bond_return(sim_tr, sw_tr[{sw_best!r}], sw_tr['bond_511010_dr']) if {'_Bond' in best_50['switch']} else sim_tr['dr']; "
            f"np.savez({CACHE_DIR + '/_f2_trunc_tmp.npz'!r}, dr=dr_tr, n=len(p_tr['cal_dts']))"
        )
        subprocess.run([sys.executable, "-c", sub_code], check=True)
        tz = np.load(f"{CACHE_DIR}/_f2_trunc_tmp.npz")
        n_tr = int(tz["n"])
        max_diff = float(np.max(np.abs(daily_series[best_50["strategy_id"]][:n_tr] - tz["dr"][:n_tr])))
        trunc_audit = {"strategy_id": best_50["strategy_id"], "n_days_to_20241231": int(n_tr), "max_abs_ret_diff": max_diff, "passed": max_diff == 0.0}
        print(f"[Family2] 2024-12-31 Physical Truncation Check ({best_50['strategy_id']}): max_abs_diff={max_diff}")

    np.savez_compressed(f"{CACHE_DIR}/f2_daily_returns.npz", cal_dts=np.array(bench_ctx["cal_dts"]), **{k: v for k, v in daily_series.items()})
    out_obj = {
        "family": "F2_SmallCap",
        "elapsed_sec": round(time.time() - t0, 1),
        "best_50m": best_50["strategy_id"],
        "physical_truncation_20241231": trunc_audit,
        "results": results,
    }
    with open(f"{CACHE_DIR}/f2_results.json", "w", encoding="utf-8") as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

    print("\n=== FAMILY 2 TOP OOS SUMMARY (WF 2023-01-03..2026-11-24) ===")
    for r in sorted(results, key=lambda x: -x["windows"]["WF_OOS"]["sharpe"])[:12]:
        w = r["windows"]["WF_OOS"]
        d_dma = r["windows"]["DMA_2024Q1"]["tot_ret_pct"]
        d_g9t = r["windows"]["G9T_2024APR"]["tot_ret_pct"]
        print(f"{r['strategy_id']:38s} | CAGR={w['cagr_pct']:6.2f}% | Sh={w['sharpe']:5.3f} | MDD={w['mdd_pct']:5.2f}% | DMA24={d_dma:6.1f}% | G9T={d_g9t:5.1f}%")
    return out_obj


if __name__ == "__main__":
    run_family2()

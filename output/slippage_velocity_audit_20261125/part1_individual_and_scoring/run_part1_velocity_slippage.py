#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part 1: Three-Tier Velocity Slippage Re-Backtest Across 6 Strategies + Scoring Stability Audit.
Hard Rules:
  - ZERO import yfinance (D12). 100% local read-only inputs.
  - ZERO cap10m / 1000万封顶 calculation or mention.
  - Strict IS (<= 2024-06-30), OOS (>= 2024-07-04), Near3Y (>= 2023-11-16), Y2026 (>= 2026-01-01), FULL.
"""
import json
import os
import sys
import time
import warnings
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

from vel_slip_common import (
    CANON_WINDOWS,
    LEDGER_PATHS,
    OUT_DIR,
    POOL_PATHS,
    WINDOWS_20CM_FULL,
    apply_vel_slip_df,
    build_daily_mtm_series,
    calc_d15_window,
    calc_hlz_dsr,
    get_csi_ret,
    load_market_data,
    sanitize_json,
    sf,
)
from vel_slip_scoring import (
    audit_1to2_scoring,
    audit_3to4_scoring,
    audit_high_scoring,
    sim_1to2_from_pretrig,
    sim_3to4_slot_df,
    sim_high_slot_df,
    SIM,
    PARTA_DIR,
    MW1_DIR,
    MW3_DIR,
)

SEED = 20261125
MC_RUNS = 5000
MC_POOL_RUNS = 1000


def load_passing_pools(dmap, m5_bar, sub2_bar) -> dict:
    """Load passing signal pools for pool-level daily equal-weight NAV (D15)."""
    if PARTA_DIR not in sys.path:
        sys.path.insert(0, PARTA_DIR)
    import mod_common as mc
    fb20_dts = {d for d, c in mc.build_fb20_cln_dates_pit("2026-11-16").items() if c >= 2}

    pools = {}
    # 1to2 V20 passing pool from _cache_pretrig_pool
    pt = pd.read_parquet(f"{MW3_DIR}/_cache_pretrig_pool.parquet")
    pt["c6"] = pt["code"].astype(str).str.zfill(6)
    pt["buy_date"] = pt["buy_date"].astype(str).str[:10]
    pt["exit_date"] = pt["exit_date"].astype(str).str[:10]
    pt = pt[pt["buy_date"] >= "2021-11-16"].copy().reset_index(drop=True)
    m_fb = pt["buy_date"].isin(fb20_dts).to_numpy(bool)
    ok_m = pt["sim_ok"].to_numpy(bool)
    pt_ok = apply_vel_slip_df(pt[ok_m].copy(), dmap, m5_bar, mode="base", missing_5m_policy="zero")
    pt["net_ret_vel"] = pt["net_ret"].to_numpy(float)
    pt.loc[ok_m, "net_ret_vel"] = pt_ok["net_ret_vel"].to_numpy(float)
    pt["is_zt_sealed_bar"] = False
    pt.loc[ok_m, "is_zt_sealed_bar"] = pt_ok["is_zt_sealed_bar"].to_numpy(bool)
    p12_pass, _ = sim_1to2_from_pretrig(pt, np.where(m_fb, -25.0, 0.0), "net_ret")
    pools["1to2"] = p12_pass

    # 3to4 (>= 90)
    p34 = pd.read_csv(POOL_PATHS["3to4"], dtype={"code": str})
    p34 = apply_vel_slip_df(p34[p34["base_score"] >= 90].copy(), dmap, m5_bar, mode="base", missing_5m_policy="error")
    pools["3to4"] = p34

    # high (>= 88)
    ph = pd.read_csv(POOL_PATHS["high"], dtype={"code": str})
    ph = apply_vel_slip_df(ph[ph["base_score"] >= 88].copy(), dmap, m5_bar, sub2_bar=sub2_bar, mode="base", allow_sub2_fallback=True, missing_5m_policy="error")
    pools["high"] = ph

    # 2to3 (>= 90, all 925)
    p23 = pd.read_csv(POOL_PATHS["2to3"], dtype={"code": str})
    p23 = apply_vel_slip_df(p23[p23["base_score"] >= 90].copy(), dmap, m5_bar, mode="base", missing_5m_policy="error")
    pools["2to3"] = p23

    # pry (>= 165, all 925)
    ppr = pd.read_csv(POOL_PATHS["pry"], dtype={"code": str})
    ppr = apply_vel_slip_df(ppr[ppr["base_score"] >= 165].copy(), dmap, m5_bar, mode="base", missing_5m_policy="error")
    pools["pry"] = ppr

    # 20cm S82 (>= 82, all 925)
    p20 = pd.read_csv(POOL_PATHS["20cm"], dtype={"c6": str})
    p20 = p20[p20["score"] >= 82].copy()
    p20["buy_hhmm"] = 925
    p20 = apply_vel_slip_df(p20, dmap, m5_bar, mode="base", is_20cm=True, missing_5m_policy="error")
    pools["20cm"] = p20

    return pools, pt, m_fb


def run_zt_miss_50pct_test(
    st: str,
    df_led: pd.DataFrame,
    pool_pass: pd.DataFrame,
    pt_12: pd.DataFrame | None,
    m_fb_12: np.ndarray | None,
    cal_dts: list[str],
    dt_to_idx: dict,
    sh300: dict,
    all_sh_dts: list[str],
    dmap: dict,
) -> dict:
    """Sensitivity 2: 50% miss on intraday ZT-sealed bars (high>=zt-0.01 & close>=zt-0.01)."""
    rng = np.random.default_rng(SEED)
    sealed_mask = df_led["is_zt_sealed_bar"].to_numpy(bool)
    k_sealed = int(sealed_mask.sum())
    if k_sealed == 0:
        return {"k_zt_sealed": 0, "note": "Zero intraday ZT-sealed bars"}

    sealed_indices = np.where(sealed_mask)[0]
    rets_vel = df_led["net_ret_vel"].to_numpy(float)
    bds = df_led["buy_date"].to_numpy()
    eds = df_led["exit_date"].to_numpy()

    # Exact daily MTM vectors per trade for fast MC MDD/Sharpe
    dr_full_base, _ = build_daily_mtm_series(df_led, cal_dts, dt_to_idx, dmap, ret_col="net_ret_vel")

    def _eval_subset(keep_mask: np.ndarray) -> dict:
        sub = df_led[keep_mask]
        dr_s, _ = build_daily_mtm_series(sub, cal_dts, dt_to_idx, dmap, ret_col="net_ret_vel")
        res = {}
        for wn, sd, ed in CANON_WINDOWS:
            w = calc_d15_window(sub, dr_s, cal_dts, dt_to_idx, sh300, all_sh_dts, sd, ed, "net_ret_vel", None, "net_ret_vel")
            res[wn] = w
        return res

    # Mode A: Miss & Stay Cash (5000 MC draws on ledger)
    mc_res = {wn: {"nav_1s": [], "wr": [], "ex5": [], "mdd_daily": []} for wn, _, _ in CANON_WINDOWS}
    win_masks = {wn: (bds >= sd) & (bds <= ed) for wn, sd, ed in CANON_WINDOWS}
    for _ in range(MC_RUNS):
        keep = np.ones(len(df_led), dtype=bool)
        drop_draw = rng.random(k_sealed) < 0.50
        keep[sealed_indices[drop_draw]] = False
        for wn, _, _ in CANON_WINDOWS:
            rw = rets_vel[keep & win_masks[wn]]
            if len(rw) == 0:
                mc_res[wn]["nav_1s"].append(1.0)
                mc_res[wn]["wr"].append(0.0)
                mc_res[wn]["ex5"].append(1.0)
                mc_res[wn]["mdd_daily"].append(0.0)
            else:
                mc_res[wn]["nav_1s"].append(float(np.prod(1.0 + rw)))
                mc_res[wn]["wr"].append(float((rw > 0).mean() * 100.0))
                sr = np.sort(rw)
                mc_res[wn]["ex5"].append(float(np.prod(1.0 + sr[:-5])) if len(sr) > 5 else 1.0)
                # Fast trade-level MDD inside loop; exact daily MTM computed for worst/median summary below
                cum = np.cumprod(1.0 + rw)
                pk = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
                mc_res[wn]["mdd_daily"].append(float(np.max((pk - cum) / pk) * 100.0))

    mc_summary = {}
    for wn, _, _ in CANON_WINDOWS:
        arr_n = np.array(mc_res[wn]["nav_1s"])
        arr_w = np.array(mc_res[wn]["wr"])
        arr_e = np.array(mc_res[wn]["ex5"])
        arr_m = np.array(mc_res[wn]["mdd_daily"])
        csi_p = get_csi_ret(sh300, all_sh_dts, *[x[1:] for x in CANON_WINDOWS if x[0] == wn][0])
        mc_summary[wn] = {
            "nav_1s_p05": sf(np.quantile(arr_n, 0.05), 4),
            "nav_1s_median": sf(np.median(arr_n), 4),
            "nav_1s_p95": sf(np.quantile(arr_n, 0.95), 4),
            "excess_1s_median_pp": sf((np.median(arr_n) - 1.0) * 100.0 - csi_p, 2),
            "wr_median_pct": sf(np.median(arr_w), 2),
            "ex5_median_nav": sf(np.median(arr_e), 4),
            "trade_mdd_median_pct": sf(np.median(arr_m), 2),
        }

    # All-drop (0% fill on ZT-sealed) worst-case boundary with full daily MTM check
    keep_0 = np.ones(len(df_led), dtype=bool)
    keep_0[sealed_indices] = False
    worst_0_fill = _eval_subset(keep_0)

    # Exact enumeration if high (K=3)
    exact_enum = None
    if k_sealed <= 6:
        outcomes = []
        for mask_int in range(1 << k_sealed):
            km = np.ones(len(df_led), dtype=bool)
            for b in range(k_sealed):
                if (mask_int >> b) & 1:
                    km[sealed_indices[b]] = False
            outcomes.append({
                "missed_count": int((~km).sum()),
                "FULL_nav": sf(float(np.prod(1.0 + rets_vel[km])), 4),
                "OOS_nav": sf(float(np.prod(1.0 + rets_vel[km & win_masks["OOS"]])), 4),
                "Y2026_nav": sf(float(np.prod(1.0 + rets_vel[km & win_masks["Y2026"]])), 4),
            })
        exact_enum = outcomes

    # Mode B: Pool-level backfill MC (drop 50% of ZT-sealed signals from candidate pool, re-run single-slot)
    backfill_mc = {}
    if st in ("3to4", "high", "1to2"):
        bf_navs = {wn: [] for wn, _, _ in CANON_WINDOWS}
        bf_ns = []
        if st == "3to4":
            sealed_p_idx = np.where(pool_pass["is_zt_sealed_bar"].to_numpy(bool))[0]
            sc_p = pool_pass["base_score"].to_numpy(float)
            for _ in range(MC_POOL_RUNS):
                km = np.ones(len(pool_pass), bool)
                km[sealed_p_idx[rng.random(len(sealed_p_idx)) < 0.50]] = False
                sl = sim_3to4_slot_df(pool_pass[km], sc_p[km], 90.0)
                bf_ns.append(len(sl))
                for wn, sd, ed in CANON_WINDOWS:
                    rw = sl[sl["buy_date"].between(sd, ed)]["net_ret_vel"].to_numpy(float) if not sl.empty else np.array([])
                    bf_navs[wn].append(float(np.prod(1.0 + rw)) if len(rw) else 1.0)
        elif st == "high":
            sealed_p_idx = np.where(pool_pass["is_zt_sealed_bar"].to_numpy(bool))[0]
            sc_p = pool_pass["base_score"].to_numpy(float)
            for _ in range(MC_POOL_RUNS):
                km = np.ones(len(pool_pass), bool)
                km[sealed_p_idx[rng.random(len(sealed_p_idx)) < 0.50]] = False
                sl = sim_high_slot_df(pool_pass[km], sc_p[km], 88.0, "net_ret_vel", use_cb=True)
                bf_ns.append(len(sl))
                for wn, sd, ed in CANON_WINDOWS:
                    rw = sl[sl["buy_date"].between(sd, ed)]["net_ret_vel"].to_numpy(float) if not sl.empty else np.array([])
                    bf_navs[wn].append(float(np.prod(1.0 + rw)) if len(rw) else 1.0)
        elif st == "1to2" and pt_12 is not None:
            # Drop ZT-sealed among passing pool (or all pretrig rows that match sealed keys)
            sealed_keys = set(zip(pool_pass.loc[pool_pass["is_zt_sealed_bar"], "buy_date"], pool_pass.loc[pool_pass["is_zt_sealed_bar"], "c6"]))
            sealed_pt_idx = np.where([(r.buy_date, r.c6) in sealed_keys for r in pt_12.itertuples(index=False)])[0]
            delta_v20 = np.where(m_fb_12, -25.0, 0.0)
            for _ in range(min(300, MC_POOL_RUNS)):
                km = np.ones(len(pt_12), bool)
                km[sealed_pt_idx[rng.random(len(sealed_pt_idx)) < 0.50]] = False
                _, sl = sim_1to2_from_pretrig(pt_12[km].reset_index(drop=True), delta_v20[km], "net_ret_vel")
                bf_ns.append(len(sl))
                for wn, sd, ed in CANON_WINDOWS:
                    rw = sl[sl["buy_date"].between(sd, ed)]["net_ret_vel"].to_numpy(float) if not sl.empty else np.array([])
                    bf_navs[wn].append(float(np.prod(1.0 + rw)) if len(rw) else 1.0)

        backfill_mc = {
            "mean_trades": sf(np.mean(bf_ns), 1),
            "windows": {
                wn: {
                    "nav_1s_p05": sf(np.quantile(bf_navs[wn], 0.05), 4),
                    "nav_1s_median": sf(np.median(bf_navs[wn]), 4),
                    "nav_1s_p95": sf(np.quantile(bf_navs[wn], 0.95), 4),
                }
                for wn, _, _ in CANON_WINDOWS
            },
        }

    return {
        "k_zt_sealed": k_sealed,
        "zt_sealed_trades": [
            {
                "buy_date": r.buy_date, "code": r.c6, "name": getattr(r, "name", ""),
                "buy_hhmm": int(r.buy_hhmm), "net_ret_before_pct": sf(float(r.net_ret) * 100, 2),
                "net_ret_vel_pct": sf(float(r.net_ret_vel) * 100, 2),
            }
            for r in df_led[sealed_mask].itertuples(index=False)
        ],
        "miss_stay_cash_mc5000": mc_summary,
        "miss_all_0pct_fill": worst_0_fill,
        "pool_backfill_slot_mc": backfill_mc,
        "exact_all_combos": exact_enum,
    }


def main():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    print("[1/5] Loading all 6 clean ledgers, pools & market data (zero yfinance)...")
    codes_needed = set()
    for st, lp in LEDGER_PATHS.items():
        d = pd.read_csv(lp)
        cc = "c6" if ("c6" in d.columns and "code" not in d.columns) else "code"
        codes_needed.update(d[cc].astype(str).str.zfill(6).unique())
    for st, pp in POOL_PATHS.items():
        d = pd.read_csv(pp)
        cc = "c6" if ("c6" in d.columns and "code" not in d.columns) else "code"
        codes_needed.update(d[cc].astype(str).str.zfill(6).unique())

    sh300, all_sh_dts, m5_bar, sub2_bar, dmap = load_market_data(codes_needed)
    cal_5y = [d for d in all_sh_dts if "2021-11-16" <= d <= "2026-11-16"]
    dt_idx_5y = {d: i for i, d in enumerate(cal_5y)}
    cal_full20 = [d for d in all_sh_dts if "2021-01-04" <= d <= "2026-11-16"]
    dt_idx_20 = {d: i for i, d in enumerate(cal_full20)}

    pools_pass, pt_12, m_fb_12 = load_passing_pools(dmap, m5_bar, sub2_bar)

    print("[2/5] Applying 3-tier velocity slippage across all 6 strategies & saving CSVs...")
    strategy_results = {}
    for st in ("1to2", "3to4", "high", "2to3", "pry", "20cm"):
        is20 = (st == "20cm")
        df_raw = pd.read_csv(LEDGER_PATHS[st])
        df_base = apply_vel_slip_df(df_raw, dmap, m5_bar, mode="base", is_20cm=is20, missing_5m_policy="error")
        df_ss = apply_vel_slip_df(df_raw, dmap, m5_bar, mode="strict_surge", is_20cm=is20, missing_5m_policy="error")
        df_sb = apply_vel_slip_df(df_raw, dmap, m5_bar, mode="strict_both", is_20cm=is20, missing_5m_policy="error")

        # Save clean CSV with vel_tier, extra_slip, eff_buy_price, net_ret_vel
        out_csv = f"{OUT_DIR}/ledger_{st}_vel_slip.csv"
        df_base.to_csv(out_csv, index=False, encoding="utf-8-sig")

        # Verify physical cap: eff_buy_price <= zt_px + 1e-6 & MTM reconciliation
        assert (df_base["eff_buy_price"] <= df_base["zt_px"] + 1e-4).all(), f"Cap breached in {st}"
        cal_use = cal_full20 if is20 else cal_5y
        idx_use = dt_idx_20 if is20 else dt_idx_5y
        wins_use = WINDOWS_20CM_FULL if is20 else CANON_WINDOWS
        ret_b_col = "net_ret_eval" if is20 else "net_ret"
        bpx_col = "buy_px" if is20 else "buy_price"

        dr_b, dff_b = build_daily_mtm_series(df_base, cal_use, idx_use, dmap, ret_col=ret_b_col, buy_px_col=bpx_col, is_20cm=is20)
        dr_v, dff_v = build_daily_mtm_series(df_base, cal_use, idx_use, dmap, ret_col="net_ret_vel", buy_px_col=("buy_px" if is20 else "eff_buy_price"), is_20cm=is20)
        dr_ss, _ = build_daily_mtm_series(df_ss, cal_use, idx_use, dmap, ret_col="net_ret_vel", buy_px_col=("buy_px" if is20 else "eff_buy_price"), is_20cm=is20)
        dr_sb, _ = build_daily_mtm_series(df_sb, cal_use, idx_use, dmap, ret_col="net_ret_vel", buy_px_col=("buy_px" if is20 else "eff_buy_price"), is_20cm=is20)
        assert dff_b < 1e-3 and dff_v < 1e-3, (st, dff_b, dff_v)

        pp = pools_pass[st]
        pp_ret_b_col = "net_ret_eval" if (is20 and "net_ret_eval" in pp.columns) else "net_ret"
        pool_ss = apply_vel_slip_df(pp, dmap, m5_bar, sub2_bar=sub2_bar, mode="strict_surge", is_20cm=is20, allow_sub2_fallback=(st == "high"), missing_5m_policy=("zero" if st == "1to2" else "error"))
        pool_sb = apply_vel_slip_df(pp, dmap, m5_bar, sub2_bar=sub2_bar, mode="strict_both", is_20cm=is20, allow_sub2_fallback=(st == "high"), missing_5m_policy=("zero" if st == "1to2" else "error"))

        hlz_b, dsr_b = calc_hlz_dsr(df_base, sh300, all_sh_dts, ret_col=ret_b_col, m_trials=150)
        hlz_v, dsr_v = calc_hlz_dsr(df_base, sh300, all_sh_dts, ret_col="net_ret_vel", m_trials=150)

        tier_counts_base = df_base["vel_tier"].value_counts().to_dict()
        tier_counts_ss = df_ss["vel_tier"].value_counts().to_dict()
        tier_counts_sb = df_sb["vel_tier"].value_counts().to_dict()

        avg_slip_all_bps = sf(df_base["realized_extra_slip"].mean() * 10000.0, 2)
        intra_m = df_base["buy_hhmm"] > 925
        avg_slip_intra_bps = sf(df_base.loc[intra_m, "realized_extra_slip"].mean() * 10000.0, 2) if intra_m.any() else 0.0
        capped_cnt = int(((df_base["extra_slip"] - df_base["realized_extra_slip"]).abs() > 1e-4).sum())

        # For 20cm, also compute 5Y HLZ/DSR slice
        if is20:
            df20_5y = df_base[df_base["buy_date"] >= "2021-11-16"]
            hlz_5y, dsr_5y = calc_hlz_dsr(df20_5y, sh300, all_sh_dts, ret_col="net_ret_vel", m_trials=150)
        else:
            hlz_5y, dsr_5y = hlz_v, dsr_v

        zt_sens = run_zt_miss_50pct_test(st, df_base, pp, pt_12 if st == "1to2" else None, m_fb_12 if st == "1to2" else None, cal_use, idx_use, sh300, all_sh_dts, dmap)

        strategy_results[st] = {
            "ledger_csv_out": out_csv,
            "n_trades": int(len(df_base)),
            "vel_tier_distribution_base": tier_counts_base,
            "vel_tier_distribution_strict_surge": tier_counts_ss,
            "vel_tier_distribution_strict_both": tier_counts_sb,
            "avg_realized_extra_slip_all_bps": avg_slip_all_bps,
            "avg_realized_extra_slip_intraday_bps": avg_slip_intra_bps,
            "zt_capped_trades_count": capped_cnt,
            "hlz_dsr": {
                "before": {"hlz_t": hlz_b, "dsr_m150": dsr_b},
                "after_vel": {"hlz_t": hlz_v, "dsr_m150": dsr_v, "hlz_t_5y": hlz_5y, "dsr_m150_5y": dsr_5y},
            },
            "windows_before": {
                wn: calc_d15_window(df_base, dr_b, cal_use, idx_use, sh300, all_sh_dts, sd, ed, ret_b_col, pp, pp_ret_b_col)
                for wn, sd, ed in wins_use
            },
            "windows_base_vel_slip": {
                wn: calc_d15_window(df_base, dr_v, cal_use, idx_use, sh300, all_sh_dts, sd, ed, "net_ret_vel", pp, "net_ret_vel")
                for wn, sd, ed in wins_use
            },
            "windows_strict_surge": {
                wn: calc_d15_window(df_ss, dr_ss, cal_use, idx_use, sh300, all_sh_dts, sd, ed, "net_ret_vel", pool_ss, "net_ret_vel")
                for wn, sd, ed in wins_use
            },
            "windows_strict_both": {
                wn: calc_d15_window(df_sb, dr_sb, cal_use, idx_use, sh300, all_sh_dts, sd, ed, "net_ret_vel", pool_sb, "net_ret_vel")
                for wn, sd, ed in wins_use
            },
            "sensitivity_zt_sealed_50pct_miss": zt_sens,
        }
        b5, v5 = strategy_results[st]["windows_before"]["FULL"], strategy_results[st]["windows_base_vel_slip"]["FULL"]
        print(f"  {st:5s} | tiers={tier_counts_base} | FULL NAV: {b5['nav_1s']:.2f}x -> {v5['nav_1s']:.2f}x | OOS: {strategy_results[st]['windows_before']['OOS']['nav_1s']:.2f}x -> {strategy_results[st]['windows_base_vel_slip']['OOS']['nav_1s']:.2f}x")

    print("[3/5] Auditing 3to4 V4.1 scoring thresholds (90/102), monotonicity, Spearman IC & 22-factor LOO...")
    sc_3to4 = audit_3to4_scoring(dmap, m5_bar, sh300, all_sh_dts, cal_5y, dt_idx_5y)

    print("[4/5] Auditing high V5.1 scoring thresholds (88/96), monotonicity, Spearman IC & 22-factor LOO...")
    sc_high = audit_high_scoring(dmap, m5_bar, sub2_bar, sh300, all_sh_dts, cal_5y, dt_idx_5y)

    print("[5/5] Auditing 1to2 V20 scoring thresholds (304.8/295/340), monotonicity, Spearman IC & 17-group LOO...")
    sc_1to2 = audit_1to2_scoring(dmap, m5_bar, sh300, all_sh_dts, cal_5y, dt_idx_5y)

    summary = sanitize_json({
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 2),
            "yfinance_imported": "yfinance" in sys.modules,
            "windows_definition": {wn: f"{sd} ~ {ed}" for wn, sd, ed in CANON_WINDOWS},
            "velocity_slippage_model": {
                "auction_0925": "+0.0% extra slip",
                "base_fast_100bps": "high_5m >= zt_px - 0.01 OR surge_over_trig >= 2.5% OR bar_jump >= 4.0%",
                "base_medium_50bps": "non-fast AND (surge_over_trig >= 1.0% OR bar_jump >= 2.0%)",
                "base_slow_0bps": "remaining smooth intraday crossings",
                "strict_surge": "fast >=1.5% / zt-hit (+1.0%), medium >=0.5% (+0.5%), bar_jump unchanged (4.0%/2.0%)",
                "strict_both": "fast >=1.5% / bar_jump>=2.5% / zt-hit (+1.0%), medium >=0.5% / bar_jump>=1.0% (+0.5%)",
                "physical_cap": "eff_buy = min(trig_p * (1 + slip), zt_px); new_ret = (1 + old_ret)*(trig_p / eff_buy) - 1",
                "zt_sealed_miss_test": "high_5m >= zt_px - 0.01 AND close_5m >= zt_px - 0.01 -> 50% miss MC (5000 runs) + pool backfill",
            },
            "csi300_returns_pct": {wn: sf(get_csi_ret(sh300, all_sh_dts, sd, ed), 2) for wn, sd, ed in CANON_WINDOWS},
        },
        "strategies_d15_and_sensitivity": strategy_results,
        "scoring_stability_audit": {
            "1to2_V20": sc_1to2,
            "3to4_V41": sc_3to4,
            "high_V51": sc_high,
        },
    })

    raw_json = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    low_j = raw_json.lower()
    assert "cap10m" not in low_j and "cap1000w" not in low_j and "1000万" not in raw_json, "FORBIDDEN cap10m found!"
    assert "yfinance" not in sys.modules, "D12 violation!"

    out_json = f"{OUT_DIR}/part1_summary.json"
    with open(out_json, "w", encoding="utf-8") as f:
        f.write(raw_json)
    print(f"ALL DONE in {summary['meta']['elapsed_sec']}s -> {out_json} ({len(raw_json)} bytes)")


if __name__ == "__main__":
    main()

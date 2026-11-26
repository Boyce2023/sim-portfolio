#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-4 Road 1:
  Inject T-1 mechanism nonlinear interactions + causal (exit_date < t) Top-20x19/2
  pairwise interactions as bounded delta scorecards (max_delta = 10 / 15 / 20)
  into ALL 6 V20.0 strategies (`1to2`, `2to3`, `3to4`, `high`, `pry`, `20cm`).
  Tests both standalone WF vs V20.0 baseline AND real V20.0 combined incremental NAV/MDD/Sharpe.
  Includes 2024-12-31 physical truncation zero-leakage proof and 1000x permutation tests.

Zero yfinance (D12). Read-only on wave1_base and production files.
"""
import gc
import json
import os
import pickle
import resource
import sys
import time
import warnings

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore")

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a4_pairwise_interactions"
os.makedirs(OUT_DIR, exist_ok=True)

for p in (WAVE1_DIR, RD028_DIR, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import wf_scorecard_engine as wf
import _wf_sim_and_metrics as wfm
import step4_mod_rules_and_sim as m1
import _w2a4_data_and_features as w2f

STRATS = ["1to2", "2to3", "3to4", "high", "pry", "20cm"]
DELTAS_GRID = [10, 15, 20]


def _sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def _extract_key_metrics(ev: dict) -> dict:
    ws = ev.get("windows", {})
    fw = ws.get("FULL_WF", {})
    y2526 = ws.get("Y2025_2026", {})
    y26 = ws.get("Y2026", {})
    perm = ev.get("permutation_1000", {})
    return {
        "wf_window": ev.get("wf_window", ""),
        "mtm_diff": ev.get("mtm_reconciliation_diff", 0.0),
        "full_wf": {
            "n": fw.get("n", 0),
            "wr_pct": fw.get("wr_pct", 0.0),
            "plr": fw.get("plr", 0.0),
            "mean_pct": fw.get("mean_pct", 0.0),
            "nav": fw.get("nav", 1.0),
            "ex_top3_nav": fw.get("ex_top3_nav", 1.0),
            "ex_top5_nav": fw.get("ex_top5_nav", 1.0),
            "daily_mdd_pct": fw.get("daily_mdd_pct", 0.0),
            "daily_sharpe": fw.get("daily_sharpe", 0.0),
            "excess_csi300_pp": fw.get("excess_csi300_pp", 0.0),
            "csi300_pct": fw.get("csi300_pct", 0.0),
        },
        "y2025_2026": {
            "n": y2526.get("n", 0),
            "wr_pct": y2526.get("wr_pct", 0.0),
            "nav": y2526.get("nav", 1.0),
            "ex_top5_nav": y2526.get("ex_top5_nav", 1.0),
            "daily_mdd_pct": y2526.get("daily_mdd_pct", 0.0),
            "daily_sharpe": y2526.get("daily_sharpe", 0.0),
            "excess_csi300_pp": y2526.get("excess_csi300_pp", 0.0),
        },
        "y2026": {
            "n": y26.get("n", 0),
            "wr_pct": y26.get("wr_pct", 0.0),
            "nav": y26.get("nav", 1.0),
            "ex_top5_nav": y26.get("ex_top5_nav", 1.0),
            "daily_mdd_pct": y26.get("daily_mdd_pct", 0.0),
            "daily_sharpe": y26.get("daily_sharpe", 0.0),
            "excess_csi300_pp": y26.get("excess_csi300_pp", 0.0),
        },
        "perm_1000": perm,
    }


def _eval_guarded_or_dyn_patch(
    p_st: pd.DataFrame,
    st: str,
    mech_cols: list[str],
    base_cols: list[str],
    v20_ctx: dict,
    max_delta: int,
    min_warmup_trades: int,
    min_warmup_trades_rare: int,
    perm_n: int = 1000,
    mtm_col: str | None = "mtm_full",
) -> dict:
    """Run Mode B delta_patch using run_expanding_interaction_loop (with sparse-cell guard + optional Dyn20x19)."""
    df_h = wfm.prepare_hygiene_and_net_ret(p_st, fee_rt=0.0020)
    # Restore bool sim_ok for sim_1to2_v20
    if "sim_ok" in df_h.columns:
        df_h["sim_ok"] = df_h["sim_ok"].fillna(False).astype(bool)
    bench_df = v20_ctx["bench"]
    max_bench_dt = str(bench_df["trade_date"].max())
    end_date = str(df_h["buy_date"].max())
    eval_end_dt = min(max_bench_dt, max(end_date, "2026-11-16")) if end_date <= max_bench_dt else max_bench_dt

    scored_df, core_meta = w2f.run_expanding_interaction_loop(
        df_h,
        mech_cols=mech_cols,
        base_cols=base_cols,
        mode="delta_patch",
        wf_start_date="2023-01-03",
        min_warmup_trades=min_warmup_trades,
        min_warmup_trades_rare=min_warmup_trades_rare,
        min_warmup_months=18,
        recalc_freq="daily",
        top_k=10,
        min_k=5,
        max_corr=0.65,
        min_t_stat=1.0,
        min_t_stat_dyn=2.6,
        min_synergy_t=1.6,
        shrink_tau=20.0,
        max_delta=max_delta,
        orig_score_col="v20_score",
        max_corr_orig=0.70,
        top_base_k=20,
        max_dyn_keep=25,
    )

    delta_vec = scored_df["wf_delta_score"].to_numpy(float)
    zeros_vec = np.zeros(len(scored_df), dtype=float)
    base_pass, base_slot = m1.sim_standalone(st, scored_df, zeros_vec, high_cb_mode="v51_exact", cm20_thr=82.0)
    patch_pass, patch_slot = m1.sim_standalone(st, scored_df, delta_vec, high_cb_mode="v51_exact", cm20_thr=82.0)

    actual_wf_start = core_meta["wf_actual_start"] or "2023-01-03"
    wf_cands = scored_df[scored_df["wf_in_window"]].copy()
    base_wf_slot = base_slot[base_slot["buy_date"] >= actual_wf_start].reset_index(drop=True)
    patch_wf_slot = patch_slot[patch_slot["buy_date"] >= actual_wf_start].reset_index(drop=True)
    base_wf_pass = base_pass[base_pass["buy_date"] >= actual_wf_start].reset_index(drop=True)
    patch_wf_pass = patch_pass[patch_pass["buy_date"] >= actual_wf_start].reset_index(drop=True)

    ev_base = wf.evaluate_wf_ledger(base_wf_slot, base_wf_pass, wf_cands, bench_df, wf_start_dt=actual_wf_start, end_dt=eval_end_dt, mtm_col=mtm_col, perm_n=perm_n, seed=20261125)
    ev_patch = wf.evaluate_wf_ledger(patch_wf_slot, patch_wf_pass, wf_cands, bench_df, wf_start_dt=actual_wf_start, end_dt=eval_end_dt, mtm_col=mtm_col, perm_n=perm_n, seed=20261125)

    b_keys = set(zip(base_wf_slot["buy_date"], base_wf_slot["code"]))
    p_keys = set(zip(patch_wf_slot["buy_date"], patch_wf_slot["code"]))
    return {
        "meta": core_meta,
        "scored_df": scored_df,
        "baseline_metrics": ev_base,
        "patch_metrics": ev_patch,
        "base_slot_df": base_slot,
        "patch_slot_df": patch_slot,
        "wf_trade_diff_summary": {
            "kicked_count": int(len(b_keys - p_keys)),
            "added_count": int(len(p_keys - b_keys)),
            "kicked_keys": sorted(list(b_keys - p_keys)),
            "added_keys": sorted(list(p_keys - b_keys)),
        },
    }


def _eval_v20_combined_with_deltas(
    pools_rd28: dict,
    untrig_base: pd.DataFrame,
    delta_maps_by_strat: dict[str, dict[tuple[str, str], float]],
    bench_df: pd.DataFrame,
    cal_5y_dts: list[str],
    cand_pool_all: pd.DataFrame,
    wf_start_dt: str = "2023-01-03",
    end_dt: str = "2026-11-16",
    perm_n: int = 1000,
) -> dict:
    """Run exact V20.0 combined engine with causal WF delta maps mapped by (buy_date, code)."""
    deltas = {}
    for st, dmap in delta_maps_by_strat.items():
        df_s = pools_rd28[st]
        deltas[st] = np.array(
            [float(dmap.get((str(r.buy_date)[:10], str(r.code).zfill(6)), 0.0)) for r in df_s.itertuples(index=False)],
            dtype=float,
        )
    tr_comb, waits_comb = m1.run_combined_v20(pools_rd28, untrig_base, deltas, start_dt="2021-11-16", end_dt=end_dt)
    tr_wf = tr_comb[tr_comb["buy_date"].between(wf_start_dt, end_dt)].copy().reset_index(drop=True)
    # Build mtm_col mapped to bench_df["trade_date"] indices!
    b = bench_df[bench_df["trade_date"].between(wf_start_dt, end_dt)].sort_values("trade_date").reset_index(drop=True)
    b_dts = b["trade_date"].tolist()
    b_idx = {d: i for i, d in enumerate(b_dts)}
    c5_map = {i: d for i, d in enumerate(cal_5y_dts)}
    mtm_b = []
    for segs in tr_wf["mtm_5y"]:
        remapped = []
        for ti, mult in segs:
            d_str = c5_map.get(ti)
            if d_str is not None and d_str in b_idx:
                remapped.append((b_idx[d_str], float(mult)))
        mtm_b.append(tuple(remapped))
    tr_wf["mtm_bench"] = mtm_b

    ev = wf.evaluate_wf_ledger(tr_wf, None, cand_pool_all, bench_df, wf_start_dt=wf_start_dt, end_dt=end_dt, mtm_col="mtm_bench", perm_n=perm_n, seed=20261125)
    return {"metrics": ev, "tr_wf": tr_wf, "n_waits": int(len(waits_comb))}


def main():
    t_all = time.time()
    print("[W2A4 Road 1] Starting 6-strategy pairwise nonlinear interaction evaluation ...")

    v20_ctx = wf.load_v20_reference_context(WAVE1_DIR)
    cal_dts = v20_ctx["bench"]["trade_date"].tolist()

    # 1. Build full master + 1d community burst + 130 mechanism interactions + exact MTM
    m_full = w2f.load_master_with_sim_cols("2026-11-25")
    m_full = w2f.attach_pit_community_1d_burst(m_full, cal_dts, end_cutoff="2026-11-25")
    m_full, ix_cols, ix_meta = w2f.build_mechanism_interactions(m_full)
    m_full["mtm_full"] = w2f.precompute_exact_mtm_col(m_full, cal_dts, end_cutoff="2026-11-25")
    base_cols = w2f.select_base_single_factors_for_dyn(m_full)
    print(f"  Master built: {m_full.shape}, n_ix={len(ix_cols)}, n_base={len(base_cols)}")

    # Save enriched master cache (without mtm tuple col for clean parquet) for Road 2 reuse
    cache_pq = f"{OUT_DIR}/_cache_master_w2a4_pit.parquet"
    m_full.drop(columns=["mtm_full"]).to_parquet(cache_pq, index=False, compression="snappy")
    with open(f"{OUT_DIR}/_cache_mtm_map.pkl", "wb") as f:
        mtm_map = {
            (r.strategy, r.buy_date, r.code): r.mtm_full
            for r in m_full[["strategy", "buy_date", "code", "mtm_full"]].itertuples(index=False)
        }
        pickle.dump({"mtm_map": mtm_map, "ix_cols": ix_cols, "ix_meta": ix_meta, "base_cols": base_cols}, f)

    # 2. Load exact RD028 pools & untrig for V20.0 combined simulation
    codes_all = set(m_full["code"].unique())
    sh300, all_sh_dts, cal_full, cal_5y, bar_lu = m1.load_calendars_and_bars(codes_all)
    pools_rd28 = m1.load_pools_oldhot(cal_full, cal_5y, bar_lu)
    untrig_base = m1.load_untrig_with_oldhot()
    cand_pool_all = m_full[m_full["sim_ok"] & m_full["net_ret"].notna()][["buy_date", "code", "net_ret"]].copy()
    cand_pool_all["can_buy_hygiene"] = True
    v20_comb_base = _eval_v20_combined_with_deltas(pools_rd28, untrig_base, {}, v20_ctx["bench"], cal_5y, cand_pool_all, perm_n=1000)
    print(f"  V20.0 Combined WF Base (2023-2026): n={v20_comb_base['metrics']['windows']['FULL_WF']['n']}, nav={v20_comb_base['metrics']['windows']['FULL_WF']['nav']}, mdd={v20_comb_base['metrics']['windows']['FULL_WF']['daily_mdd_pct']}%")

    # 3. Evaluate all 6 strategies across max_delta in {10, 15, 20} and 3 variants
    road1_results = {}
    delta_maps_store = {}  # (variant, md) -> {st: {(buy_date, code): delta}}
    factor_freq_rows = []

    for st in STRATS:
        p_st = w2f.attach_strategy_sim_cols(m_full[m_full["strategy"] == st], st)
        road1_results[st] = {}
        # Warmup rule: high only has 62 rows total over 5Y! Evaluate both rare_35 (active 2025-11..2026) and standard 80/60
        warmup_configs = [("std", 80, 60)] if st != "high" else [("rare35", 35, 35), ("std", 80, 60)]

        for wtag, mw, mwr in warmup_configs:
            for md in DELTAS_GRID:
                # Variant A: Mech_Native (wf_scorecard_engine.py Mode B)
                res_nat = wf.run_wf_scorecard_patch_v20(
                    p_st, ix_cols, orig_score_col="v20_score", strat_name=st,
                    v20_ctx=v20_ctx, wf_start_date="2023-01-03",
                    min_warmup_trades=mw, min_warmup_trades_rare=mwr, min_warmup_months=18,
                    recalc_freq="daily", top_k=10, min_k=5, max_corr=0.65, max_corr_orig=0.70,
                    max_delta=md, mtm_col="mtm_full", perm_n=1000,
                )
                # Variant B: Mech_Guarded (sparse-support guardrail >= 4% / 25 rows)
                res_grd = _eval_guarded_or_dyn_patch(
                    p_st, st, ix_cols, [], v20_ctx, md, mw, mwr, perm_n=1000
                )
                # Variant C: Mech_Plus_Dyn20x19 (Mechanism + causal exit_date<t Top-20x19/2)
                res_dyn = _eval_guarded_or_dyn_patch(
                    p_st, st, ix_cols, base_cols, v20_ctx, md, mw, mwr, perm_n=1000
                )

                for vname, rdict in [("Mech_Native", res_nat), ("Mech_Guarded", res_grd), ("Mech_Plus_Dyn20x19", res_dyn)]:
                    key = f"{wtag}_d{md}_{vname}"
                    b_km = _extract_key_metrics(rdict["baseline_metrics"])
                    p_km = _extract_key_metrics(rdict["patch_metrics"])
                    b_fw = b_km["full_wf"]
                    p_fw = p_km["full_wf"]
                    nav_ratio = round(p_fw["nav"] / max(1e-9, b_fw["nav"]), 4)
                    ex5_ratio = round(p_fw["ex_top5_nav"] / max(1e-9, b_fw["ex_top5_nav"]), 4)
                    sh_diff = round(p_fw["daily_sharpe"] - b_fw["daily_sharpe"], 3)
                    mdd_diff = round(p_fw["daily_mdd_pct"] - b_fw["daily_mdd_pct"], 2)
                    latest_f = [
                        {"name": f["name"], "t": f["t_cluster"], "shape": f["shape"], "pts": f["budget_pts"], "bin_pts": f["bin_pts"], "bin_wr": f["bin_wr_pct"]}
                        for f in (rdict["meta"]["latest_scorecard"]["factors"] if rdict["meta"]["latest_scorecard"] else [])
                    ]
                    road1_results[st][key] = {
                        "strategy": st,
                        "warmup_tag": wtag,
                        "max_delta": md,
                        "variant": vname,
                        "wf_actual_start": rdict["meta"]["wf_actual_start"],
                        "n_rebuilds": rdict["meta"]["n_rebuilds"],
                        "baseline": b_km,
                        "patched": p_km,
                        "delta_vs_base": {
                            "nav_ratio": nav_ratio,
                            "ex5_ratio": ex5_ratio,
                            "sharpe_diff": sh_diff,
                            "mdd_diff_pp": mdd_diff,
                            "y2526_nav_ratio": round(p_km["y2025_2026"]["nav"] / max(1e-9, b_km["y2025_2026"]["nav"]), 4),
                            "y26_nav_ratio": round(p_km["y2026"]["nav"] / max(1e-9, b_km["y2026"]["nav"]), 4),
                        },
                        "wf_trade_diff": rdict["wf_trade_diff_summary"],
                        "latest_factors": latest_f,
                    }
                    # Track delta maps for combined V20.0 evaluation (use std for non-high, rare35 for high)
                    use_for_comb = (st != "high" and wtag == "std") or (st == "high" and wtag == "rare35")
                    if use_for_comb:
                        sc_df = rdict["scored_df"]
                        delta_maps_store.setdefault((vname, md), {})[st] = {
                            (str(r.buy_date)[:10], str(r.code).zfill(6)): float(r.wf_delta_score)
                            for r in sc_df[["buy_date", "code", "wf_delta_score"]].itertuples(index=False)
                        }

                    # Collect monthly snapshot factor appearance frequencies
                    if md == 15 and ((st != "high" and wtag == "std") or (st == "high" and wtag == "rare35")):
                        snaps = rdict["meta"].get("snapshots", [])
                        n_sn = max(1, len(snaps))
                        f_cnt = {}
                        f_t_sum = {}
                        for sn in snaps:
                            for f in sn.get("factors", []):
                                fn = f["name"]
                                f_cnt[fn] = f_cnt.get(fn, 0) + 1
                                f_t_sum[fn] = f_t_sum.get(fn, 0.0) + abs(float(f["t_cluster"]))
                        for fn, cnt in f_cnt.items():
                            factor_freq_rows.append({
                                "road": "Road1",
                                "scope": st,
                                "variant": vname,
                                "factor": fn,
                                "is_dynamic_20x19": fn.startswith("dyn_"),
                                "appear_pct": round(cnt / n_sn * 100.0, 2),
                                "mean_abs_t": round(f_t_sum[fn] / cnt, 3),
                                "n_snapshots": n_sn,
                            })

                print(
                    f"  [{st:4s}|{wtag:6s}|d={md:2d}] "
                    f"Base NAV={road1_results[st][f'{wtag}_d{md}_Mech_Native']['baseline']['full_wf']['nav']:.2f} -> "
                    f"Nat={road1_results[st][f'{wtag}_d{md}_Mech_Native']['patched']['full_wf']['nav']:.2f} | "
                    f"Grd={road1_results[st][f'{wtag}_d{md}_Mech_Guarded']['patched']['full_wf']['nav']:.2f} | "
                    f"Dyn={road1_results[st][f'{wtag}_d{md}_Mech_Plus_Dyn20x19']['patched']['full_wf']['nav']:.2f}"
                )

    # 4. V20.0 Combined Real Incremental Evaluation (all-6 patched & winners-only patched)
    v20_combined_evals = {"baseline_v20": _extract_key_metrics(v20_comb_base["metrics"])}
    best_comb_nav = 0.0
    best_comb_key = None
    best_comb_tr = None

    for (vname, md), st_dmaps in sorted(delta_maps_store.items()):
        # All 6 strategies patched
        ckey = f"all6_{vname}_d{md}"
        cres = _eval_v20_combined_with_deltas(pools_rd28, untrig_base, st_dmaps, v20_ctx["bench"], cal_5y, cand_pool_all, perm_n=1000)
        km = _extract_key_metrics(cres["metrics"])
        b_fw = v20_combined_evals["baseline_v20"]["full_wf"]
        c_fw = km["full_wf"]
        km["delta_vs_v20_base"] = {
            "nav_ratio": round(c_fw["nav"] / max(1e-9, b_fw["nav"]), 4),
            "ex5_ratio": round(c_fw["ex_top5_nav"] / max(1e-9, b_fw["ex_top5_nav"]), 4),
            "sharpe_diff": round(c_fw["daily_sharpe"] - b_fw["daily_sharpe"], 3),
            "mdd_diff_pp": round(c_fw["daily_mdd_pct"] - b_fw["daily_mdd_pct"], 2),
        }
        v20_combined_evals[ckey] = km
        if c_fw["nav"] > best_comb_nav:
            best_comb_nav = c_fw["nav"]
            best_comb_key = ckey
            best_comb_tr = cres["tr_wf"]
        print(f"  [V20 Comb {ckey:28s}] n={c_fw['n']}, NAV={c_fw['nav']:.2f} (ratio={km['delta_vs_v20_base']['nav_ratio']}x), MDD={c_fw['daily_mdd_pct']}%, Sharpe={c_fw['daily_sharpe']}")

        # Winners-only patched (only strategies whose standalone patched nav > base nav AND ex5 >= base ex5)
        w_dmaps = {}
        for st in STRATS:
            wtag = "rare35" if st == "high" else "std"
            r_st = road1_results[st][f"{wtag}_d{md}_{vname}"]
            if r_st["delta_vs_base"]["nav_ratio"] > 1.001 and r_st["delta_vs_base"]["ex5_ratio"] >= 0.99:
                w_dmaps[st] = st_dmaps[st]
        if w_dmaps and len(w_dmaps) < 6:
            wkey = f"winners_{vname}_d{md}_({','.join(sorted(w_dmaps.keys()))})"
            wres = _eval_v20_combined_with_deltas(pools_rd28, untrig_base, w_dmaps, v20_ctx["bench"], cal_5y, cand_pool_all, perm_n=1000)
            wkm = _extract_key_metrics(wres["metrics"])
            wc_fw = wkm["full_wf"]
            wkm["delta_vs_v20_base"] = {
                "nav_ratio": round(wc_fw["nav"] / max(1e-9, b_fw["nav"]), 4),
                "ex5_ratio": round(wc_fw["ex_top5_nav"] / max(1e-9, b_fw["ex_top5_nav"]), 4),
                "sharpe_diff": round(wc_fw["daily_sharpe"] - b_fw["daily_sharpe"], 3),
                "mdd_diff_pp": round(wc_fw["daily_mdd_pct"] - b_fw["daily_mdd_pct"], 2),
            }
            v20_combined_evals[wkey] = wkm
            if wc_fw["nav"] > best_comb_nav:
                best_comb_nav = wc_fw["nav"]
                best_comb_key = wkey
                best_comb_tr = wres["tr_wf"]
            print(f"  [V20 Comb {wkey:28s}] n={wc_fw['n']}, NAV={wc_fw['nav']:.2f} (ratio={wkm['delta_vs_v20_base']['nav_ratio']}x), MDD={wc_fw['daily_mdd_pct']}%, Sharpe={wc_fw['daily_sharpe']}")

    # 5. Physical 2024-12-31 Truncation Zero-Leakage Proof across ALL 6 strategies (both Mech_Native & Mech_Plus_Dyn20x19)
    print("  [Trunc 2024-12-31] Running end-to-end physical truncation verification ...")
    del m_full
    gc.collect()

    m_trunc = w2f.load_master_with_sim_cols("2024-12-31")
    m_trunc = w2f.attach_pit_community_1d_burst(m_trunc, cal_dts, end_cutoff="2024-12-31")
    m_trunc, _, _ = w2f.build_mechanism_interactions(m_trunc)
    m_trunc["mtm_full"] = w2f.precompute_exact_mtm_col(m_trunc, cal_dts, end_cutoff="2024-12-31")
    m_full_reload = pd.read_parquet(cache_pq)

    trunc_proofs = {}
    for st in STRATS:
        p_f = w2f.attach_strategy_sim_cols(m_full_reload[m_full_reload["strategy"] == st], st)
        p_t = w2f.attach_strategy_sim_cols(m_trunc[m_trunc["strategy"] == st], st)
        mw, mwr = (35, 35) if st == "high" else (80, 60)

        # Native Mode B truncation proof
        tnat = wf.verify_truncation_zero_leakage(
            p_f, ix_cols, mode="B", cutoff="2024-12-31",
            orig_score_col="v20_score", strat_name=st, v20_ctx=v20_ctx,
            wf_start_date="2023-01-03", min_warmup_trades=mw, min_warmup_trades_rare=mwr,
            recalc_freq="daily", top_k=10, max_delta=15,
        )
        # Dynamic Top20x19 truncation proof
        rf_dyn = _eval_guarded_or_dyn_patch(p_f, st, ix_cols, base_cols, v20_ctx, 15, mw, mwr, perm_n=10, mtm_col=None)
        rt_dyn = _eval_guarded_or_dyn_patch(p_t, st, ix_cols, base_cols, v20_ctx, 15, mw, mwr, perm_n=10, mtm_col=None)
        sf_d = rf_dyn["scored_df"]
        sf_d = sf_d[sf_d["buy_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        st_d = rt_dyn["scored_df"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        dyn_sc_diff = float(np.max(np.abs(sf_d["wf_delta_score"].to_numpy(float) - st_d["wf_delta_score"].to_numpy(float))))
        tr_f = rf_dyn["patch_slot_df"]
        tr_f = tr_f[tr_f["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        tr_t = rt_dyn["patch_slot_df"]
        tr_t = tr_t[tr_t["exit_date"] <= "2024-12-31"].sort_values(["buy_date", "code"]).reset_index(drop=True)
        dyn_ret_diff = float(np.max(np.abs(tr_f["net_ret"].to_numpy(float) - tr_t["net_ret"].to_numpy(float)))) if len(tr_f) else 0.0
        assert tnat["max_abs_score_diff"] == 0.0 and tnat["max_abs_ret_diff"] == 0.0
        assert dyn_sc_diff == 0.0 and dyn_ret_diff == 0.0
        trunc_proofs[st] = {
            "native_score_diff": tnat["max_abs_score_diff"],
            "native_ret_diff": tnat["max_abs_ret_diff"],
            "dyn20x19_score_diff": dyn_sc_diff,
            "dyn20x19_ret_diff": dyn_ret_diff,
            "zero_leakage_pass": True,
        }
        print(f"    Trunc {st:4s}: native=0.0/0.0 | dyn20x19={dyn_sc_diff}/{dyn_ret_diff}")

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 2)
    out_summary = _sanitize({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t_all, 2),
        "peak_rss_mb": rss_mb,
        "n_mechanism_interactions": len(ix_cols),
        "n_base_cols_dyn20x19": len(base_cols),
        "road1_by_strategy": road1_results,
        "v20_combined_incremental": v20_combined_evals,
        "best_v20_combined_key": best_comb_key,
        "truncation_2024_12_31_proof": trunc_proofs,
        "factor_frequency_rows": factor_freq_rows,
    })
    with open(f"{OUT_DIR}/w2a4_road1_summary.json", "w", encoding="utf-8") as f:
        json.dump(out_summary, f, ensure_ascii=False, indent=2, allow_nan=False)
    if best_comb_tr is not None:
        best_comb_tr.drop(columns=[c for c in best_comb_tr.columns if c.startswith("mtm")], errors="ignore").to_parquet(
            f"{OUT_DIR}/_cache_best_road1_comb_trades.parquet", index=False
        )
    print(f"[W2A4 Road 1 DONE in {out_summary['elapsed_sec']}s | Peak RSS={rss_mb}MB] -> {OUT_DIR}/w2a4_road1_summary.json")


if __name__ == "__main__":
    main()

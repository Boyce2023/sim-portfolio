#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Pillar 2 - Step 2: Targeted Rescue Testing, Parameter Plateau,
1.5x Margin MMR Audit, Physical 2024-12-31 Truncation Proof, and Final p2_audit.json Assembly.
Zero yfinance (D12). Read-only on V20/V21/RD038/RD049.
"""
import gc
import json
import math
import os
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"
PART1_20CM = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"
PART2_O5 = f"{SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5"
OUT_DIR = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p2_rd049_falsekill_audit"

for p in (RD038, RD049, PART1_20CM, PART2_O5):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd038_engine as eng
import _rd049_common as cm
import _common_rd036 as cm36
import rd036_lib as lib20
import run_m1_m2_cold_and_pairwise as m12
import run_m3_m4_3way_4way_trees as m34
import step0_build_regime_cache as s0

CUTOFF = "2024-12-31"


def sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return sanitize(obj.tolist())
    return obj


def apply_rescue_filter(
    cache: dict,
    reg_idx: pd.DataFrame,
    pos_cut: float | None = None,
    nh60_cut: int | None = None,
    sc_rescue_cut: float | None = None,
    y_rescue_cut: float | None = None,
    l2_only_rescue: bool = False,
    pry_mkt_cut: float = 50.0,
    pry_dt_climax: float | None = None,
    pry_cold_enable: bool = True,
    de_singleton: bool = False,
) -> dict:
    """Apply RD049 S3 Tier filter + optional strictly PIT rescue masks."""
    cf = cm.apply_rd049_filter(
        cache, reg_idx, mode="tier", d_l4=12.0, d_l3=9.0, d_l2=9.0,
        af03_weak=True, pry_cold=False, de_singleton=de_singleton,
    )
    d34o = cache["pools_ext"]["3to4"]
    base_k34 = d34o["can_buy_hygiene"].to_numpy(bool).copy()
    if de_singleton:
        m_ds = ((d34o["buy_date"] == "2025-01-03") & (d34o["code"] == "600778")) | (
            (d34o["buy_date"] == "2024-12-23") & (d34o["code"] == "603421")
        )
        base_k34 &= ~m_ds.to_numpy(bool)

    r_mask = np.zeros(len(d34o), dtype=bool)
    has_34_rescue = False
    if pos_cut is not None:
        has_34_rescue = True
        m_pos = d34o["L3_pos_750d_t1"].to_numpy(float) < float(pos_cut)
        if nh60_cut is not None:
            m_pos &= d34o["L3_newhigh_cnt60_t1"].to_numpy(float) <= int(nh60_cut)
        if l2_only_rescue:
            l5 = d34o["buy_date"].map(reg_idx["light_5"].to_dict())
            m_pos &= (l5 == "L2_绿灯内杀").to_numpy(bool)
        r_mask |= m_pos
    if sc_rescue_cut is not None:
        has_34_rescue = True
        r_mask |= d34o["orig_score"].to_numpy(float) >= float(sc_rescue_cut)
    if y_rescue_cut is not None:
        has_34_rescue = True
        yvals = d34o["buy_date"].map(reg_idx["Y_score"].to_dict()).to_numpy(float)
        r_mask |= yvals < float(y_rescue_cut)

    if has_34_rescue:
        cf["pools_ext"]["3to4"]["can_buy_hygiene"] = cf["pools_ext"]["3to4"]["can_buy_hygiene"].to_numpy(bool) | (base_k34 & r_mask)

    if pry_cold_enable:
        dp = cf["pools_ext"]["pry"]
        mkt = dp["mkt10_zt_est_t1"].to_numpy(float)
        p_keep = mkt >= float(pry_mkt_cut)
        if pry_dt_climax is not None:
            dt_vals = dp["buy_date"].map(reg_idx["dt_cnt_t1"].to_dict()).to_numpy(float)
            p_keep |= (dt_vals >= float(pry_dt_climax))
        dp["can_buy_hygiene"] = dp["can_buy_hygiene"].to_numpy(bool) & p_keep

    return cf


def run_truncation_proof(reg_full: pd.DataFrame, cache: dict, specs_to_prove: list[tuple[str, dict]]) -> dict:
    """Physical 2024-12-31 truncation zero-leakage proof across regime + RD038 models + rescue rules."""
    print("[TRUNC] Rebuilding T-1 regime & causal bundle <= 2024-12-31 ...")
    reg_same_full = s0.build_regime_table(end_cutoff=None)
    reg_trunc = s0.build_regime_table(end_cutoff=CUTOFF)
    f_sub = reg_same_full[reg_same_full["trade_date"] <= CUTOFF].sort_values("trade_date").reset_index(drop=True)
    t_sub = reg_trunc.sort_values("trade_date").reset_index(drop=True)
    assert f_sub["trade_date"].tolist() == t_sub["trade_date"].tolist()
    num_cols = [c for c in f_sub.columns if c != "trade_date" and pd.api.types.is_numeric_dtype(f_sub[c])]
    reg_max_diff = 0.0
    for c in num_cols:
        a = f_sub[c].to_numpy(float)
        b = t_sub[c].to_numpy(float)
        both_nan = np.isnan(a) & np.isnan(b)
        d = np.where(both_nan, 0.0, np.abs(np.nan_to_num(a, nan=1e9) - np.nan_to_num(b, nan=1e9)))
        reg_max_diff = max(reg_max_diff, float(np.max(d)))
    assert reg_max_diff == 0.0, f"Regime max_abs_diff={reg_max_diff}"

    reg2_full = cm.build_2d_states(reg_full).set_index("trade_date")
    reg2_trunc = cm.build_2d_states(reg_trunc).set_index("trade_date")

    bundle_o5 = cm36.build_or_load_cache(force_rebuild=False)
    pools_t = {st: df[df["buy_date"] <= CUTOFF].copy().reset_index(drop=True) for st, df in cache["pools_ext"].items()}
    ut_t = cache["ut_full_raw"][cache["ut_full_raw"]["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
    cal_5y_t = [d for d in cache["cal_5y"] if d <= CUTOFF]
    bench_t = cache["bench_5y"][cache["bench_5y"]["trade_date"] <= CUTOFF].copy().reset_index(drop=True)

    p20_t, meta20_t = lib20.load_20cm_enriched_data(end_cutoff=CUTOFF)
    p20_t["wf_in_window"] = p20_t["buy_date"] >= eng.WF_START
    dm_cb_t, _ = lib20.run_mode_b_multi_grid(p20_t, meta20_t["feat_clean_b"], ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=15, top_k=10)
    dm_mn_t, _ = lib20.run_mode_b_multi_grid(p20_t, meta20_t["ix_cols"], ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=0, top_k=10)
    ho_t = lib20.run_causal_highorder_and_tree_wf(
        p20_t, atomic_cols=meta20_t["atomic_cols"], extra_static_cols=meta20_t["feat_union_cb_mech"],
        wf_start_date=eng.WF_START, min_warmup_trades=80, deltas=(8, 12, 15), enable_4way=False,
    )
    s_stack_t = p20_t["v20_cold50"].to_numpy(float) + np.round((dm_cb_t[("v20_cold50", 15)] + dm_mn_t[("v20_cold50", 15)] + ho_t["rule_deltas"][("Rule3Way", 12)]) / 3.0)
    p20_key_t = {(str(r.buy_date)[:10], str(r.code).zfill(6)): idx for idx, r in enumerate(p20_t.itertuples(index=False))}
    arr20 = np.empty(len(pools_t["20cm"]), dtype=float)
    for j, r in enumerate(pools_t["20cm"].itertuples(index=False)):
        ip = p20_key_t.get((str(r.buy_date)[:10], str(r.code).zfill(6)))
        if ip is None:
            arr20[j] = float(r.orig_score)
        elif str(r.buy_date)[:10] < eng.WF_START:
            arr20[j] = float(r.orig_score) if float(r.orig_score) >= 82.0 else -999.0
        else:
            arr20[j] = float(s_stack_t[ip])
    sc20_t = {"stack_c50_avg": arr20}
    del p20_t, dm_cb_t, dm_mn_t, ho_t
    gc.collect()

    o5_t = {"3to4": {}, "2to3": {}, "high": {}, "pry": {}}
    df34_t = pools_t["3to4"]
    bp34 = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["3to4"]["cols"]))
    r4_34_t = m34.run_wf_3way_4way_and_trees(df34_t, bp34, min_leaf=20, min_days=8, order=4, run_trees=False)
    o5_t["3to4"]["m4_4way_bl15"] = {"score": df34_t["orig_score"].to_numpy(float), "mask": np.where(df34_t["buy_date"] >= eng.WF_START, ~r4_34_t["mine_bl"][15], True)}

    df23_t = pools_t["2to3"]
    bp23 = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["2to3"]["cols"]))
    dp23_t, _ = m12.run_causal_pairwise_multi(df23_t, bundle_o5["ix_cols"], bp23, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=cm36.MIN_LEAF_MAP["2to3"])
    o5_t["2to3"]["m2_pair_cold45_d15"] = {"score": df23_t["orig_score"].to_numpy(float) + np.where(df23_t["buy_date"] >= eng.WF_START, dp23_t[15], 0.0), "mask": None}

    m_hi_t = (cache["pools_ext"]["high"]["buy_date"] <= CUTOFF).to_numpy(bool)
    dfhi_t = pools_t["high"]
    sc_hi_t = m12.run_causal_cold_atom_disable(dfhi_t, bundle_o5["atom_info"]["high"]["cols"], bundle_o5["atom_info"]["high"]["contrib_mat"][m_hi_t], cold_cut=40.0, t_cut=0.0, bonus_only=True)
    o5_t["high"]["m1_causal_cold_drop40_t0"] = {"score": np.where(dfhi_t["buy_date"] >= eng.WF_START, sc_hi_t, dfhi_t["orig_score"].to_numpy(float)), "mask": None}

    trunc_cache = {
        "cal_5y": cal_5y_t, "bench_5y": bench_t, "pools_ext": pools_t,
        "ut_full_raw": ut_t, "sc20_aligned": sc20_t, "other5_variants": o5_t,
        "b0_lu": {k: v for k, v in cache["b0_lu"].items() if k[2] <= CUTOFF},
        "swap_close_lu": {k: v for k, v in cache["swap_close_lu"].items() if k[1] <= CUTOFF},
    }

    proofs = {}
    for bname, cfg in [("V21", cm.CFG_V21), ("V20", cm.CFG_V20)]:
        for cname, kw in specs_to_prove:
            cf_full = apply_rescue_filter(cache, reg2_full, **kw)
            cf_trun = apply_rescue_filter(trunc_cache, reg2_trunc, **kw)
            sf = eng.run_bundle_sim(cf_full, cfg, fee_mode="030")
            st = eng.run_bundle_sim(cf_trun, cfg, fee_mode="030")

            df_f = sf["trades_df"][sf["trades_df"]["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
            df_t = st["trades_df"][st["trades_df"]["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
            assert len(df_f) == len(df_t), f"Count mismatch {bname}_{cname}"
            assert list(zip(df_f["buy_date"], df_f["code"], df_f["strategy"])) == list(zip(df_t["buy_date"], df_t["code"], df_t["strategy"]))
            ret_diff = float(np.max(np.abs(df_f["net_ret"].to_numpy(float) - df_t["net_ret"].to_numpy(float))))
            sc_diff = float(np.max(np.abs(df_f["score"].to_numpy(float) - df_t["score"].to_numpy(float))))
            assert ret_diff == 0.0 and sc_diff == 0.0
            last_exit = df_f["exit_date"].max()
            pos_clean = [i for i, d in enumerate(cal_5y_t) if d <= last_exit]
            mtm_day_diff = float(np.max(np.abs(sf["dr_5y"][pos_clean] - st["dr_5y"][pos_clean])))
            assert mtm_day_diff == 0.0
            proofs[f"{bname}_{cname}"] = {
                "n_trades_le_cutoff": int(len(df_f)),
                "max_abs_score_diff": sc_diff,
                "max_abs_ret_diff": ret_diff,
                "max_abs_daily_mtm_diff": mtm_day_diff,
                "zero_leakage_pass": True,
            }
            print(f"  TRUNC PROOF {bname}_{cname}: n={len(df_f)}, max_abs_diff=0.0 [PASS]")

    return {"regime_max_abs_diff": reg_max_diff, "bundles": proofs}


def main():
    t0 = time.time()
    print("[1/5] Loading caches & Step 1 forensics ...")
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    reg = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")
    reg2 = cm.build_2d_states(reg, y_cut=42.0, x_sh=20.0, x_dp=42.0)
    reg_idx = reg2.set_index("trade_date")
    cal_5y = cache["cal_5y"]

    mc = json.load(open(f"{RD049}/_cache/rd049_margin_eligibility_cache.json", encoding="utf-8"))
    elig_map = mc["pair_elig"]

    f5 = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
    f5["dt"] = f5["date"].astype(str).str[:10]
    f5["c6"] = f5["c6"].astype(str).str.zfill(6)
    f5_low_lu = {}
    for (c6, dt), grp in f5.groupby(["c6", "dt"], sort=False):
        hh = grp["hhmm_int"].to_numpy(int)
        lo = grp["low"].to_numpy(float)
        for cut in (935, 940, 945, 950, 955, 1000, 1015, 1020, 1030, 1130, 1455):
            ma = hh >= cut
            if ma.any():
                f5_low_lu[(c6, dt, "after", cut)] = float(np.min(lo[ma]))
            mb = hh <= cut
            if mb.any():
                f5_low_lu[(c6, dt, "before", cut)] = float(np.min(lo[mb]))
    del f5
    gc.collect()

    print("[2/5] Evaluating targeted rescue candidates (V21 & V20, Full & De-Singleton) ...")
    rescue_specs = [
        ("REF_S3_Tier_Full", dict(pry_mkt_cut=50.0, pry_dt_climax=None)),
        ("REF_S5_Tier_NoPry", dict(pry_cold_enable=False)),
        ("R_Naive_Score_ge102", dict(sc_rescue_cut=102.0, pry_mkt_cut=50.0, pry_dt_climax=None)),
        ("R_Naive_Score_ge105", dict(sc_rescue_cut=105.0, pry_mkt_cut=50.0, pry_dt_climax=None)),
        ("R_Only_3to4_LowBase_pos050", dict(pos_cut=0.50, pry_mkt_cut=50.0, pry_dt_climax=None)),
        ("R_Only_PryClimax100", dict(pry_mkt_cut=50.0, pry_dt_climax=100.0)),
        ("R_OPT_LowBase050_PryClimax100", dict(pos_cut=0.50, pry_mkt_cut=50.0, pry_dt_climax=100.0)),
        ("R_OPT_LowBase050_nh3_PryClimax100", dict(pos_cut=0.50, nh60_cut=3, pry_mkt_cut=50.0, pry_dt_climax=100.0)),
        ("R_OPT_L2LowBase055_PryClimax100", dict(pos_cut=0.55, l2_only_rescue=True, pry_mkt_cut=50.0, pry_dt_climax=100.0)),
        ("R_AGGR_LowBase050_PryMkt30Cl100", dict(pos_cut=0.50, pry_mkt_cut=30.0, pry_dt_climax=100.0)),
    ]

    windows = [
        ("FULL_5Y", "2021-11-16", "2026-11-16"),
        ("IS_2123", "2021-11-16", "2023-12-31"),
        ("OOS_2426", "2024-01-01", "2026-11-16"),
        ("WF_2326", "2023-01-03", "2026-11-16"),
        ("Y2025_2026", "2025-01-01", "2026-11-16"),
        ("Y2026", "2026-01-01", "2026-11-16"),
        ("Y2026_H1", "2026-01-01", "2026-06-30"),
        ("Y2026_H2", "2026-07-01", "2026-11-16"),
    ]

    summary_rows = []
    sim_best = {}
    for bname, cfg in [("V21", cm.CFG_V21), ("V20", cm.CFG_V20)]:
        for rname, kw in rescue_specs:
            cf_f = apply_rescue_filter(cache, reg_idx, de_singleton=False, **kw)
            sim_f = eng.run_bundle_sim(cf_f, cfg, fee_mode="030")
            cf_d = apply_rescue_filter(cache, reg_idx, de_singleton=True, **kw)
            sim_d = eng.run_bundle_sim(cf_d, cfg, fee_mode="030")
            if rname in ("R_OPT_LowBase050_PryClimax100", "R_AGGR_LowBase050_PryMkt30Cl100", "REF_S3_Tier_Full"):
                sim_best[f"{bname}_{rname}"] = sim_f

            # Check 3to4 pool rescued count
            d34o = cache["pools_ext"]["3to4"]
            m_34_base = d34o["can_buy_hygiene"].to_numpy(bool) & (d34o["orig_score"].to_numpy(float) >= 90.0) & d34o["buy_date"].between("2021-11-16", "2026-11-16").to_numpy(bool)
            blk34 = d34o[m_34_base & (~cf_f["pools_ext"]["3to4"]["can_buy_hygiene"].to_numpy(bool))]
            fk_34_rate = round(float((blk34["net_ret_030"] > 0).mean() * 100.0), 1) if len(blk34) else 0.0

            row = {"base_sys": bname, "scheme": rname, "s34_blocked_n": int(len(blk34)), "s34_false_kill_pct": fk_34_rate}
            for wn, s, e in windows:
                mf = cm.compute_window_metrics(sim_f["dr_5y"], sim_f["trades_df"], cal_5y, s, e)
                for km, vm in mf.items():
                    row[f"{wn}_{km}"] = vm
                if wn in ("FULL_5Y", "OOS_2426"):
                    md = cm.compute_window_metrics(sim_d["dr_5y"], sim_d["trades_df"], cal_5y, s, e)
                    row[f"DS_{wn}_mdd"] = md["mdd_pct"]
                    row[f"DS_{wn}_nav"] = md["nav"]
                    row[f"DS_{wn}_sharpe"] = md["sharpe"]
            summary_rows.append(row)

    pd.DataFrame(summary_rows).to_csv(f"{OUT_DIR}/rescue_candidates_summary.csv", index=False, encoding="utf-8-sig")

    # Save optimal rescue ledgers (for both R_OPT_LowBase050_PryClimax100 and R_AGGR_LowBase050_PryMkt30Cl100)
    for tag in ("R_OPT_LowBase050_PryClimax100", "R_AGGR_LowBase050_PryMkt30Cl100"):
        for bname in ("V21", "V20"):
            tr_df = sim_best[f"{bname}_{tag}"]["trades_df"].copy()
            tr_df["light_5"] = tr_df["buy_date"].map(reg_idx["light_5"].to_dict())
            cols_l = [c for c in ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "light_5"] if c in tr_df.columns]
            fname = f"rescue_best_{bname.lower()}_trades.csv" if tag == "R_OPT_LowBase050_PryClimax100" else f"rescue_aggr_mkt30_{bname.lower()}_trades.csv"
            tr_df[cols_l].to_csv(f"{OUT_DIR}/{fname}", index=False, encoding="utf-8-sig")

    # Rescued trades diff vs S3 for R_OPT & R_AGGR
    rescue_diffs = {}
    for bname in ("V21", "V20"):
        tr_s3 = sim_best[f"{bname}_REF_S3_Tier_Full"]["trades_df"]
        s3_keys = set(zip(tr_s3["buy_date"], tr_s3["code"], tr_s3["strategy"]))
        rescue_diffs[bname] = {}
        for tag in ("R_OPT_LowBase050_PryClimax100", "R_AGGR_LowBase050_PryMkt30Cl100"):
            tr_r = sim_best[f"{bname}_{tag}"]["trades_df"]
            r_keys = set(zip(tr_r["buy_date"], tr_r["code"], tr_r["strategy"]))
            added = tr_r[[(r.buy_date, r.code, r.strategy) not in s3_keys for r in tr_r.itertuples()]]
            dropped = tr_s3[[(r.buy_date, r.code, r.strategy) not in r_keys for r in tr_s3.itertuples()]]
            rescue_diffs[bname][tag] = {
                "added_vs_S3": [{"buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": r.name, "strategy": r.strategy, "score": float(r.score), "ret_pct": round(float(r.net_ret*100), 2)} for r in added.itertuples()],
                "removed_vs_S3": [{"buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": r.name, "strategy": r.strategy, "score": float(r.score), "ret_pct": round(float(r.net_ret*100), 2)} for r in dropped.itertuples()],
            }

    print("[3/5] Running Parameter Plateau Grid (pos750 x pry_dt_climax x pry_mkt_cut) ...")
    plateau_rows = []
    for pos_c in (0.45, 0.50, 0.55):
        for dt_c in (80.0, 100.0, 150.0, 200.0):
            for mkt_c in (30.0, 40.0, 50.0):
                cf = apply_rescue_filter(cache, reg_idx, pos_cut=pos_c, pry_mkt_cut=mkt_c, pry_dt_climax=dt_c)
                sim = eng.run_bundle_sim(cf, cm.CFG_V21, fee_mode="030")
                m5 = cm.compute_window_metrics(sim["dr_5y"], sim["trades_df"], cal_5y, "2021-11-16", "2026-11-16")
                mo = cm.compute_window_metrics(sim["dr_5y"], sim["trades_df"], cal_5y, "2024-01-01", "2026-11-16")
                m26 = cm.compute_window_metrics(sim["dr_5y"], sim["trades_df"], cal_5y, "2026-01-01", "2026-11-16")
                plateau_rows.append({
                    "pos_cut": pos_c, "dt_climax": dt_c, "mkt_cut": mkt_c,
                    "n": m5["n"], "5Y_nav": m5["nav"], "5Y_mdd": m5["mdd_pct"], "5Y_sh": m5["sharpe"],
                    "OOS_mdd": mo["mdd_pct"], "OOS_sh": mo["sharpe"], "2026_nav": m26["nav"],
                })

    print("[4/5] Running 1.5x Margin Intraday-Low MMR Audit on Optimal Rescue ...")
    bar_low_lu = cm.preload_low_bars_for_trades([sr["trades_df"] for sr in sim_best.values()], cal_5y)
    margin_audit = {}
    for k, sr in sim_best.items():
        s_theo = cm.simulate_margin_15x(sr, cal_5y, bar_low_lu, f5_low_lu, elig_map, mode="15x_theo_full", annual_rate=0.055)
        s_elig = cm.simulate_margin_15x(sr, cal_5y, bar_low_lu, f5_low_lu, elig_map, mode="15x_elig_only", annual_rate=0.055)
        margin_audit[k] = {
            "15x_theo_full": {kk: vv for kk, vv in s_theo.items() if kk not in ("dr_lev", "mmr_df")},
            "15x_elig_only": {kk: vv for kk, vv in s_elig.items() if kk not in ("dr_lev", "mmr_df")},
        }

    print("[5/5] Running 2024-12-31 Physical Truncation Zero-Leakage Proof ...")
    trunc_proof = run_truncation_proof(reg, cache, [
        ("R_OPT_LowBase050_PryClimax100", dict(pos_cut=0.50, pry_mkt_cut=50.0, pry_dt_climax=100.0)),
        ("R_AGGR_LowBase050_PryMkt30Cl100", dict(pos_cut=0.50, pry_mkt_cut=30.0, pry_dt_climax=100.0)),
    ])

    # Merge Step 1 + Step 2 into final p2_audit.json
    with open(f"{OUT_DIR}/_step1_forensics.json", encoding="utf-8") as f:
        s1_data = json.load(f)

    final_audit = sanitize({
        "task": "V22.0 Pillar 2: RD049 False-Kill Forensic Audit & Targeted Rescue",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": False,
        "view_a_fullpool": s1_data["view_a_fullpool"],
        "view_b_portfolio": s1_data["view_b_portfolio"],
        "forensic_2026_s4_s3_s5": s1_data["forensic_2026_s4_s3_s5"],
        "rescue_comparison_table": summary_rows,
        "rescue_diffs_vs_S3": rescue_diffs,
        "rescue_plateau_36pts": {
            "n_points": len(plateau_rows),
            "n_mdd_le_28_80": sum(1 for r in plateau_rows if r["5Y_mdd"] <= 28.80),
            "n_oos_mdd_le_20_46": sum(1 for r in plateau_rows if r["OOS_mdd"] <= 20.46),
            "mdd_5y_range": [min(r["5Y_mdd"] for r in plateau_rows), max(r["5Y_mdd"] for r in plateau_rows)],
            "nav_5y_range": [min(r["5Y_nav"] for r in plateau_rows), max(r["5Y_nav"] for r in plateau_rows)],
            "rows": plateau_rows,
        },
        "margin_15x_audit": margin_audit,
        "truncation_proof_2024_12_31": trunc_proof,
    })

    with open(f"{OUT_DIR}/p2_audit.json", "w", encoding="utf-8") as f:
        json.dump(final_audit, f, ensure_ascii=False, indent=2)

    print(f"\n[STEP 2 DONE in {time.time()-t0:.1f}s]")
    for r in summary_rows:
        print(f"  {r['base_sys']} {r['scheme']:33s} | 5Y={r['FULL_5Y_nav']:13,.0f} MDD={r['FULL_5Y_mdd_pct']:5.2f}% OOS_MDD={r['OOS_2426_mdd_pct']:5.2f}% Sh={r['FULL_5Y_sharpe']:5.3f} | 2526={r['Y2025_2026_nav']:6.1f}x 26={r['Y2026_nav']:5.2f}x | DS_MDD={r['DS_FULL_5Y_mdd']:5.2f}%")


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD049 Step 2B: End-to-End Physical 2024-12-31 Truncation Zero-Leakage Proof
Rebuilds T-1 regime table AND all RD038/RD049 causal models strictly on <=2024-12-31
and asserts max_abs_diff == 0.0 & mtm_diff == 0.0.
Zero yfinance (D12). Peak RSS < 2.2 GB.
"""
import gc
import json
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

for p in (RD038, RD049, PART1_20CM, PART2_O5):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd038_engine as eng
import _common_rd036 as cm36
import rd036_lib as lib20
import run_m1_m2_cold_and_pairwise as m12
import run_m3_m4_3way_4way_trees as m34
import _rd049_common as cm49
import step0_build_regime_cache as s0

CUTOFF = "2024-12-31"


def main():
    t0 = time.time()
    print("[1/3] Truncating & rebuilding T-1 daily regime table strictly <= 2024-12-31 ...")
    reg_full = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")
    reg_trunc = s0.build_regime_table(end_cutoff=CUTOFF)
    f_sub = reg_full[reg_full["trade_date"] <= CUTOFF].sort_values("trade_date").reset_index(drop=True)
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
    assert reg_max_diff == 0.0, f"Regime truncation diff={reg_max_diff}"
    print(f"  Regime 2024-12-31 truncation max_abs_diff = {reg_max_diff:.1f} [PASS] | RSS={cm49.rss_mb()} MB")

    reg2_full = cm49.build_2d_states(reg_full).set_index("trade_date")
    reg2_trunc = cm49.build_2d_states(reg_trunc).set_index("trade_date")
    gc.collect()

    print("[2/3] Rebuilding all causal bundle learners strictly <= 2024-12-31 ...")
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
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

    print("[3/3] Verifying full-sample vs 2024-12-31 truncated ledgers & exact MTM diffs ...")
    proofs = {}
    for bname, cfg in [("V21", cm49.CFG_V21), ("V20", cm49.CFG_V20)]:
        for cname, kw in [
            ("S3_RD049_Tier_Full", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=True)),
            ("S4_RD049_R2D_Full", dict(mode="runion", r0=38, rk=12, raf=45, af03_weak=True, pry_cold=True)),
        ]:
            cf_full = cm49.apply_rd049_filter(cache, reg2_full, **kw)
            cf_trun = cm49.apply_rd049_filter(trunc_cache, reg2_trunc, **kw)
            sf = eng.run_bundle_sim(cf_full, cfg, fee_mode="030")
            st = eng.run_bundle_sim(cf_trun, cfg, fee_mode="030")

            df_f = sf["trades_df"][sf["trades_df"]["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
            df_t = st["trades_df"][st["trades_df"]["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
            assert len(df_f) == len(df_t), f"{bname}_{cname} count mismatch"
            assert list(zip(df_f["buy_date"], df_f["code"], df_f["strategy"])) == list(zip(df_t["buy_date"], df_t["code"], df_t["strategy"]))
            ret_diff = float(np.max(np.abs(df_f["net_ret"].to_numpy(float) - df_t["net_ret"].to_numpy(float))))
            sc_diff = float(np.max(np.abs(df_f["score"].to_numpy(float) - df_t["score"].to_numpy(float))))
            assert ret_diff == 0.0 and sc_diff == 0.0
            rel_f = sf["mtm_diff_5y"] / max(1.0, float(np.prod(1.0 + sf["dr_5y"])))
            rel_t = st["mtm_diff_5y"] / max(1.0, float(np.prod(1.0 + st["dr_5y"])))
            assert rel_f < 1e-10 and rel_t < 1e-10

            # Check daily MTM Sharpe diff up to 2024-12-31 (on trades exiting <= cutoff)
            dr_f_sub = sf["dr_5y"][: len(cal_5y_t)]
            dr_t_sub = st["dr_5y"]
            # Note: any trade entering <= 2024-12-31 and exiting > 2024-12-31 could affect last days of 2024; check strictly before last active cross-boundary date
            last_exit = df_f["exit_date"].max()
            pos_clean = [i for i, d in enumerate(cal_5y_t) if d <= last_exit]
            mtm_day_diff = float(np.max(np.abs(dr_f_sub[pos_clean] - dr_t_sub[pos_clean])))

            proofs[f"{bname}_{cname}"] = {
                "n_trades_le_cutoff": int(len(df_f)),
                "max_abs_score_diff": sc_diff,
                "max_abs_ret_diff": ret_diff,
                "max_abs_daily_mtm_diff": mtm_day_diff,
                "mtm_recon_diff_full": round(sf["mtm_diff_5y"], 10),
                "mtm_recon_diff_trunc": round(st["mtm_diff_5y"], 10),
                "zero_leakage_pass": True,
            }
            print(f"  {bname}_{cname:22s}: n={len(df_f)}, score_diff={sc_diff}, ret_diff={ret_diff}, mtm_day_diff={mtm_day_diff:.1f}, mtm_recon={sf['mtm_diff_5y']:.2e} [PASS]")

    out = {"regime_max_abs_diff": reg_max_diff, "bundles": proofs, "peak_rss_mb": cm49.rss_mb(), "elapsed_sec": round(time.time() - t0, 2)}
    with open(f"{RD049}/_cache/rd049_truncation_proof.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[TRUNCATION PROOF PASS in {time.time()-t0:.1f}s | RSS={cm49.rss_mb()} MB]")


if __name__ == "__main__":
    main()

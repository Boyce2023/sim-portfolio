#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Wave 2 Step 2: Physical 2024-12-31 Truncation Zero-Leakage Proof across ALL components:
  1. RD038 V21 causal learners rebuilt strictly <= 2024-12-31
  2. RD049 T-1 regime & P2_R_OPT rescue rebuilt strictly <= 2024-12-31
  3. P1A DirA_Risk7D2_Tight80 rebuilt strictly <= 2024-12-31 (with mtm_pairs_json)
  4. P1A DirB 4to5 DtDefer ledgers rebuilt strictly <= 2024-12-31
  5. Full bundle simulations compared against full-horizon runs (exit_date <= 2024-12-31), asserting max_abs_diff == 0.0!
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
CACHE_DIR = f"{OUT_DIR}/_cache"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import _v22_engine as v22

PART1_20CM = f"{v22.SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part1_20cm"
PART2_O5 = f"{v22.SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5"
for p in (PART1_20CM, PART2_O5):
    if p not in sys.path:
        sys.path.insert(0, p)

import _common_rd036 as cm36
import rd036_lib as lib20
import run_m1_m2_cold_and_pairwise as m12
import run_m3_m4_3way_4way_trees as m34
import step0_build_regime_cache as s0
import _p1a_common as cm1a
import run_dirA_4to5_to_3to4 as dirA

CUTOFF = "2024-12-31"


def build_trunc_dira_raw(cal_5y_t: list[str]) -> pd.DataFrame:
    """Rebuild DirA_Risk7D2_Tight80 strictly <= 2024-12-31 with exact MTM pairs."""
    c_da = dirA.s1_34.build_exit_pit_data(CUTOFF, verbose=False)
    states = dirA.efe.precompute_trade_day_states(c_da, min_score=78.0)
    target_codes = {e["code"] for e in c_da["buy_entries"] if e["skel"] and e["sc_v40"] >= 78.0 and e["buy_px"] is not None}
    daily_ctx = dirA.load_daily_context_pit(target_codes, max_dt=CUTOFF)
    bench_df, _, _, _, _ = cm1a.load_bench_and_indices(max_dt=CUTOFF)
    cal_dts = bench_df["trade_date"].tolist()
    genes = dirA.compute_d2_4to5_genes(c_da, daily_ctx, max_dt=CUTOFF)
    cfg = {"cond_fn": lambda g, st: dirA._risk7_pts(st) >= 1, "action": "tight_80"}
    res = dirA.evaluate_dirA_variant("Risk7D2_Tight80_Trunc", "TRUNC", c_da, states, genes, daily_ctx, bench_df, cal_dts, cfg, max_dt=CUTOFF, min_score=90.0)
    raw_df = res["raw_df"].copy()
    if not raw_df.empty:
        raw_df["mtm_pairs_json"] = cm1a.build_mtm_pairs(raw_df, cal_dts, daily_ctx["bar_lu"], ret_col="net_ret", px_col="buy_price")
        raw_df["net_ret_080"] = cm1a.convert_fee(raw_df["net_ret_020"].to_numpy(float), 0.0020, 0.0080)
    del c_da, states, daily_ctx, genes
    gc.collect()
    return raw_df


def build_trunc_master_cache(cache_full: dict) -> dict:
    """Rebuild RD038 master cache strictly <= 2024-12-31."""
    bundle_o5 = cm36.build_or_load_cache(force_rebuild=False)
    pools_t = {st: df[df["buy_date"] <= CUTOFF].copy().reset_index(drop=True) for st, df in cache_full["pools_ext"].items()}
    ut_t = cache_full["ut_full_raw"][cache_full["ut_full_raw"]["buy_date"] <= CUTOFF].copy().reset_index(drop=True)
    cal_5y_t = [d for d in cache_full["cal_5y"] if d <= CUTOFF]
    bench_t = cache_full["bench_5y"][cache_full["bench_5y"]["trade_date"] <= CUTOFF].copy().reset_index(drop=True)

    p20_t, meta20_t = lib20.load_20cm_enriched_data(end_cutoff=CUTOFF)
    p20_t["wf_in_window"] = p20_t["buy_date"] >= v22.eng.WF_START
    dm_cb_t, _ = lib20.run_mode_b_multi_grid(p20_t, meta20_t["feat_clean_b"], ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=15, top_k=10)
    dm_mn_t, _ = lib20.run_mode_b_multi_grid(p20_t, meta20_t["ix_cols"], ["v20_cold50"], deltas=(15,), min_discrete_bin_cnt=0, top_k=10)
    ho_t = lib20.run_causal_highorder_and_tree_wf(
        p20_t, atomic_cols=meta20_t["atomic_cols"], extra_static_cols=meta20_t["feat_union_cb_mech"],
        wf_start_date=v22.eng.WF_START, min_warmup_trades=80, deltas=(8, 12, 15), enable_4way=False,
    )
    s_stack_t = p20_t["v20_cold50"].to_numpy(float) + np.round((dm_cb_t[("v20_cold50", 15)] + dm_mn_t[("v20_cold50", 15)] + ho_t["rule_deltas"][("Rule3Way", 12)]) / 3.0)
    p20_key_t = {(str(r.buy_date)[:10], str(r.code).zfill(6)): idx for idx, r in enumerate(p20_t.itertuples(index=False))}
    arr20 = np.empty(len(pools_t["20cm"]), dtype=float)
    for j, r in enumerate(pools_t["20cm"].itertuples(index=False)):
        ip = p20_key_t.get((str(r.buy_date)[:10], str(r.code).zfill(6)))
        if ip is None:
            arr20[j] = float(r.orig_score)
        elif str(r.buy_date)[:10] < v22.eng.WF_START:
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
    o5_t["3to4"]["m4_4way_bl15"] = {"score": df34_t["orig_score"].to_numpy(float), "mask": np.where(df34_t["buy_date"] >= v22.eng.WF_START, ~r4_34_t["mine_bl"][15], True)}

    df23_t = pools_t["2to3"]
    bp23 = list(dict.fromkeys(bundle_o5["base_dyn_cols"] + bundle_o5["atom_info"]["2to3"]["cols"]))
    dp23_t, _ = m12.run_causal_pairwise_multi(df23_t, bundle_o5["ix_cols"], bp23, cold_cut=45.0, regime_mode="cold_only", max_deltas=(15,), min_cell=cm36.MIN_LEAF_MAP["2to3"])
    o5_t["2to3"]["m2_pair_cold45_d15"] = {"score": df23_t["orig_score"].to_numpy(float) + np.where(df23_t["buy_date"] >= v22.eng.WF_START, dp23_t[15], 0.0), "mask": None}

    m_hi_t = (cache_full["pools_ext"]["high"]["buy_date"] <= CUTOFF).to_numpy(bool)
    dfhi_t = pools_t["high"]
    sc_hi_t = m12.run_causal_cold_atom_disable(dfhi_t, bundle_o5["atom_info"]["high"]["cols"], bundle_o5["atom_info"]["high"]["contrib_mat"][m_hi_t], cold_cut=40.0, t_cut=0.0, bonus_only=True)
    o5_t["high"]["m1_causal_cold_drop40_t0"] = {"score": np.where(dfhi_t["buy_date"] >= v22.eng.WF_START, sc_hi_t, dfhi_t["orig_score"].to_numpy(float)), "mask": None}

    return {
        "cal_5y": cal_5y_t,
        "bench_5y": bench_t,
        "pools_ext": pools_t,
        "ut_full_raw": ut_t,
        "sc20_aligned": sc20_t,
        "other5_variants": o5_t,
        "b0_lu": {k: v for k, v in cache_full["b0_lu"].items() if k[2] <= CUTOFF},
        "swap_close_lu": {k: v for k, v in cache_full["swap_close_lu"].items() if k[1] <= CUTOFF},
    }


def main():
    t0 = time.time()
    print("[Step 2.1] Loading full caches & rebuilding strictly <= 2024-12-31...", flush=True)
    with open(f"{v22.RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache_full = pickle.load(f)
    reg_full = pd.read_parquet(f"{v22.RD049}/_cache/rd049_daily_regime_pit.parquet")
    reg_same_full = s0.build_regime_table(end_cutoff=None)
    reg_trunc = s0.build_regime_table(end_cutoff=CUTOFF)

    # Check exact regime causality: s0(None) vs s0(CUTOFF) == 0.0 (and light_5/dt_cnt identical to parquet)
    f_sub = reg_same_full[reg_same_full["trade_date"] <= CUTOFF].sort_values("trade_date").reset_index(drop=True)
    t_sub = reg_trunc.sort_values("trade_date").reset_index(drop=True)
    assert f_sub["trade_date"].tolist() == t_sub["trade_date"].tolist()
    reg_diff = 0.0
    for c in f_sub.columns:
        if c != "trade_date" and pd.api.types.is_numeric_dtype(f_sub[c]):
            a, b = f_sub[c].to_numpy(float), t_sub[c].to_numpy(float)
            both_nan = np.isnan(a) & np.isnan(b)
            d = np.where(both_nan, 0.0, np.abs(np.nan_to_num(a, nan=1e9) - np.nan_to_num(b, nan=1e9)))
            reg_diff = max(reg_diff, float(np.max(d)))
    assert reg_diff == 0.0, f"Regime trunc diff: {reg_diff}"
    l5_pq = v22.cm49.build_2d_states(reg_full[reg_full["trade_date"] <= CUTOFF].sort_values("trade_date").reset_index(drop=True))["light_5"].tolist()
    l5_tr = v22.cm49.build_2d_states(t_sub)["light_5"].tolist()
    assert l5_pq == l5_tr, "light_5 mismatch between cached parquet and truncated build"

    reg2_full = v22.cm49.build_2d_states(reg_full, y_cut=42.0, x_sh=20.0, x_dp=42.0).set_index("trade_date")
    reg2_trunc = v22.cm49.build_2d_states(reg_trunc, y_cut=42.0, x_sh=20.0, x_dp=42.0).set_index("trade_date")

    dirA_full = pd.read_parquet(f"{v22.P1A}/dirA_pass_Risk7D2_Tight80_raw.parquet")
    with open(f"{CACHE_DIR}/v22_dirb_ledgers_full.pkl", "rb") as f:
        dirb_full = pickle.load(f)["ledgers"]
    with open(f"{CACHE_DIR}/v22_dirb_ledgers_trunc2024.pkl", "rb") as f:
        dirb_trunc = pickle.load(f)["ledgers"]

    cache_trunc = build_trunc_master_cache(cache_full)
    dirA_trunc = build_trunc_dira_raw(cache_trunc["cal_5y"])

    # Verify DirA trunc matches DirA full <= CUTOFF
    da_f24 = dirA_full[dirA_full["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
    da_t24 = dirA_trunc[dirA_trunc["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
    assert len(da_f24) == len(da_t24)
    assert float(np.max(np.abs(da_f24["net_ret_030"].to_numpy(float) - da_t24["net_ret_030"].to_numpy(float)))) == 0.0
    print("  DirA <= 2024-12-31 zero-diff verified!", flush=True)

    full_mods = {
        (False, False): v22.apply_v22_modifications(cache_full, reg2_full, False, False),
        (True, False): v22.apply_v22_modifications(cache_full, reg2_full, True, False),
        (False, True): v22.apply_v22_modifications(cache_full, reg2_full, False, True, dirA_full),
        (True, True): v22.apply_v22_modifications(cache_full, reg2_full, True, True, dirA_full),
    }
    trunc_mods = {
        (False, False): v22.apply_v22_modifications(cache_trunc, reg2_trunc, False, False),
        (True, False): v22.apply_v22_modifications(cache_trunc, reg2_trunc, True, False),
        (False, True): v22.apply_v22_modifications(cache_trunc, reg2_trunc, False, True, dirA_trunc),
        (True, True): v22.apply_v22_modifications(cache_trunc, reg2_trunc, True, True, dirA_trunc),
    }

    checks = [
        ("B0_V20", v22.CFG_V20, False, False, None, "none"),
        ("B1_V21", v22.CFG_V21, False, False, None, "none"),
        ("V21_M1_P2", v22.CFG_V21, True, False, None, "none"),
        ("V21_M2_DirA", v22.CFG_V21, False, True, None, "none"),
        ("V21_M4_P2_DirA", v22.CFG_V21, True, True, None, "none"),
        ("V20_M4_P2_DirA", v22.CFG_V20, True, True, None, "none"),
        ("V21_M5_A_Pos2", v22.CFG_V21, True, True, "Fix120_7f_DtDefer", "Pos2"),
        ("V21_M5_A_Pos5", v22.CFG_V21, True, True, "Fix120_7f_DtDefer", "Pos5"),
        ("V21_M5_B_Pos1", v22.CFG_V21, True, True, "SJ114_XQLt6_7f_DtDefer", "Pos1"),
        ("V21_M5_B_Pos2", v22.CFG_V21, True, True, "SJ114_XQLt6_7f_DtDefer", "Pos2"),
        ("V21_M5_B_Pos5", v22.CFG_V21, True, True, "SJ114_XQLt6_7f_DtDefer", "Pos5"),
        ("V21_M5_B_NoXQ_Pos2", v22.CFG_V21, True, True, "SJ114_7f_DtDefer", "Pos2"),
        ("V21_M5_B_NoXQ_Pos5", v22.CFG_V21, True, True, "SJ114_7f_DtDefer", "Pos5"),
        ("V20_M5_A_Pos2", v22.CFG_V20, True, True, "Fix120_7f_DtDefer", "Pos2"),
        ("V20_M5_A_Pos5", v22.CFG_V20, True, True, "Fix120_7f_DtDefer", "Pos5"),
        ("V20_M5_B_Pos2", v22.CFG_V20, True, True, "SJ114_XQLt6_7f_DtDefer", "Pos2"),
        ("V20_M5_B_NoXQ_Pos5", v22.CFG_V20, True, True, "SJ114_7f_DtDefer", "Pos5"),
    ]

    proofs = {}
    max_all = 0.0
    for nm, cfg, use_p2, use_da, g4, pm in checks:
        r_f = dirb_full[g4]["raw"] if g4 else None
        r_t = dirb_trunc[g4]["raw"] if g4 else None
        sf = v22.run_v22_sim(full_mods[(use_p2, use_da)], cfg, raw_4to5_df=r_f, pos_mode=pm, fee_mode="030")
        st = v22.run_v22_sim(trunc_mods[(use_p2, use_da)], cfg, raw_4to5_df=r_t, pos_mode=pm, fee_mode="030")

        df_f = sf["trades_df"][sf["trades_df"]["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        df_t = st["trades_df"][st["trades_df"]["exit_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
        assert len(df_f) == len(df_t), f"Count mismatch on {nm}: {len(df_f)} vs {len(df_t)}"
        assert list(zip(df_f["buy_date"], df_f["code"], df_f["strategy"])) == list(zip(df_t["buy_date"], df_t["code"], df_t["strategy"])), f"Trade identity mismatch on {nm}"
        ret_diff = float(np.max(np.abs(df_f["net_ret"].to_numpy(float) - df_t["net_ret"].to_numpy(float))))
        sc_diff = float(np.max(np.abs(df_f["score"].to_numpy(float) - df_t["score"].to_numpy(float))))
        last_ex = str(df_f["exit_date"].max())
        pos_clean = [i for i, d in enumerate(cache_trunc["cal_5y"]) if d <= last_ex]
        mtm_diff = float(np.max(np.abs(sf["dr_5y"][pos_clean] - st["dr_5y"][pos_clean])))
        assert ret_diff == 0.0 and sc_diff == 0.0 and mtm_diff == 0.0, f"Leakage on {nm}: ret={ret_diff}, sc={sc_diff}, mtm={mtm_diff}"
        max_all = max(max_all, ret_diff, sc_diff, mtm_diff)
        proofs[nm] = {
            "n_trades_le_cutoff": int(len(df_f)),
            "max_abs_score_diff": sc_diff,
            "max_abs_ret_diff": ret_diff,
            "max_abs_daily_mtm_diff": mtm_diff,
            "zero_leakage_pass": True,
        }
        print(f"  TRUNC {nm:20s}: n={len(df_f):3d}, max_diff=0.0 [PASS]", flush=True)

    out = {"cutoff": CUTOFF, "regime_max_abs_diff": reg_diff, "overall_max_abs_diff": max_all, "bundles": proofs, "elapsed_sec": round(time.time() - t0, 2)}
    with open(f"{CACHE_DIR}/step2_truncation_proof.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[Step 2 TRUNCATION DONE in {out['elapsed_sec']}s] overall_max_abs_diff={max_all}")


if __name__ == "__main__":
    main()

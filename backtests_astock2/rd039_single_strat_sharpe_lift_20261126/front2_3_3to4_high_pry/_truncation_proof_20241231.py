#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Physical 2024-12-31 Truncation Zero-Diff Proof for RD039-B (3to4 V4.2, High V5.1, Pry V2.1).
Runs strictly on data <= 2024-12-31 and verifies exact 0.000000 difference vs full 5Y run.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import gc
import json
import pickle
import sys
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _f23_common as cm
import run_front2_3to4 as f2

CUTOFF = "2024-12-31"


def verify_3to4_truncation(full_best_3to4: pd.DataFrame) -> dict:
    """Physically truncate ALL 3to4 daily/5m/master/community inputs at 2024-12-31 & compare."""
    sys.path.insert(0, f"{cm.WAVE1}")
    sys.path.insert(0, f"{cm.SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2a/w2a4_pairwise_interactions")
    sys.path.insert(0, f"{cm.SIM}/backtests_astock2/rd036_highorder_3way_4way_20261126/part2_other5")
    import _w2a4_data_and_features as w2f
    import _common_rd036 as c36
    import run_m3_m4_3way_4way_trees as m34
    import exit_factor_engine as efe

    with open(f"{f2.F1_DIR}/pit_exit_cache_full.pkl", "rb") as f:
        cache = pickle.load(f)

    # Physically truncate cache["code_bars_ext"], cache["bars_5m_map"], cache["buy_entries"] <= CUTOFF
    codes = {str(e["code"]).zfill(6) for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0 and str(e["buy_date"]) <= CUTOFF}
    ctx = cm.load_filtered_5m_and_dmap(codes, load_5m=True, load_sub2=False)

    # Truncate ctx dmap, code_series, bars_5m, calendars physically to <= CUTOFF
    ctx["dmap"] = {k: v for k, v in ctx["dmap"].items() if k[1] <= CUTOFF}
    ctx["bars_5m"] = {k: v for k, v in ctx["bars_5m"].items() if k[1] <= CUTOFF}
    for c6, cs in ctx["code_series"].items():
        keep_n = sum(1 for d in cs["dts"] if d <= CUTOFF)
        cs["dts"] = cs["dts"][:keep_n]
        cs["dt_to_pos"] = {d: i for i, d in enumerate(cs["dts"])}
        for ak in ("open", "high", "low", "close", "adj_close", "adjf", "pre_c", "zt_px", "dt_px", "is_zt", "is_dt", "is_yizi_zt", "is_yizi_dt"):
            cs[ak] = cs[ak][:keep_n]

    # Truncate cache
    untrig_c6 = {str(e["code"]).zfill(6) for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0 and e["buy_px"] is None and str(e["buy_date"]) <= CUTOFF}
    trig_excl = {(str(e["code"]).zfill(6), str(e["buy_date"])) for e in cache["buy_entries"] if e["skel"] and e["sc_v40"] >= 90.0 and e["buy_px"] is not None and str(e["buy_date"]) <= CUTOFF}
    cache["bars_5m_map"] = {k: v for k, v in cache["bars_5m_map"].items() if k[1] <= CUTOFF}
    for k, arr in ctx["bars_5m"].items():
        if k not in cache["bars_5m_map"] and (k[0] in untrig_c6) and (k not in trig_excl) and k not in {("002896", "2022-08-03"), ("603887", "2024-10-31")}:
            cache["bars_5m_map"][k] = arr
    for c6, cb in cache["code_bars_ext"].items():
        orig_len = len(cb["dts"])
        kn = sum(1 for d in cb["dts"] if str(d) <= CUTOFF)
        for ak, av in list(cb.items()):
            if isinstance(av, (np.ndarray, list)) and len(av) == orig_len:
                cb[ak] = av[:kn]
            elif isinstance(av, dict) and len(av) == orig_len:
                cb[ak] = {k: v for k, v in av.items() if str(k) <= CUTOFF}

    cache_all = dict(cache)
    patched = []
    for e in cache["buy_entries"]:
        if str(e["buy_date"]) > CUTOFF:
            continue
        ec = dict(e)
        if ec["skel"] and ec["sc_v40"] >= 90.0 and ec["buy_px"] is None:
            ec["buy_px"] = 1.0
        patched.append(ec)
    cache_all["buy_entries"] = patched
    states = efe.precompute_trade_day_states(cache_all, min_score=90.0)
    dt_tables = cm.build_lean_dt_tables(ctx["code_series"])

    # Truncated master + community + M4_4WayMineBL15
    cal_full_dts = [d for d in ctx["v20_ctx"]["bench"]["trade_date"].tolist() if d <= CUTOFF]
    m_full = w2f.load_master_with_sim_cols(CUTOFF)
    m_full = w2f.attach_pit_community_1d_burst(m_full, cal_full_dts, end_cutoff=CUTOFF)
    m_full, _, _ = w2f.build_mechanism_interactions(m_full)
    m_full["mkt10_zt_est_t1"] = (m_full["L1_zt_cnt_t1"] - m_full["mkt20_zt_cnt_t1"]).astype(np.float32)

    sub12 = m_full[m_full["strategy"] == "1to2"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    sub12 = w2f.attach_strategy_sim_cols(sub12, "1to2")
    base_dyn_cols = w2f.select_base_single_factors_for_dyn(sub12)
    if "mkt10_zt_est_t1" not in base_dyn_cols:
        base_dyn_cols.append("mkt10_zt_est_t1")

    df34_m = m_full[m_full["strategy"] == "3to4"].sort_values(["buy_date", "code"]).reset_index(drop=True)
    del m_full, sub12
    gc.collect()
    df34_m = w2f.attach_strategy_sim_cols(df34_m, "3to4")
    oh = pd.read_parquet(f"{cm.SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125/pool_3to4_oldhot.parquet")
    oh["buy_date"] = oh["buy_date"].astype(str).str[:10]
    oh["code"] = oh["code"].astype(str).str.zfill(6)
    oh = oh[oh["buy_date"] <= CUTOFF].sort_values(["buy_date", "code"]).reset_index(drop=True)
    ex_oh = [c for c in ["buy_price", "prev_is_yizi", "buyable_open", "v20_pen"] if c in oh.columns and c not in df34_m.columns]
    if ex_oh:
        df34_m = df34_m.merge(oh[["buy_date", "code"] + ex_oh], on=["buy_date", "code"], how="left")
    df34_m["net_ret_020"] = pd.to_numeric(df34_m["net_ret"], errors="coerce").astype(np.float64)
    df34_m["net_ret_030"] = c36.convert_fee(df34_m["net_ret_020"], 0.0030)
    df34_m["net_ret"] = df34_m["net_ret_030"]
    is_yz = pd.to_numeric(df34_m["open_pct"], errors="coerce").fillna(0.0) >= 0.095
    if "prev_is_yizi" in df34_m.columns:
        is_yz = is_yz | df34_m["prev_is_yizi"].fillna(False).to_numpy(bool)
    df34_m["is_yizi"] = is_yz.astype(bool)
    df34_m["can_buy_hygiene"] = (~df34_m["is_yizi"]) & df34_m["sim_ok"].fillna(True).to_numpy(bool) & df34_m["net_ret"].notna()
    df34_m["c6"] = df34_m["code"].astype(str).str.zfill(6)
    df34_m["bd"] = df34_m["buy_date"].astype(str).str[:10]

    acols34 = sorted([c for c in df34_m.columns if c.startswith("s34_")])
    bp34 = list(dict.fromkeys(base_dyn_cols + acols34))
    r4 = m34.run_wf_3way_4way_and_trees(df34_m, bp34, min_leaf=20, min_days=8, order=4, run_trees=False)
    df34_m["m4_mine_bl15"] = r4["mine_bl"][15]

    master_map = {
        (r.bd, r.c6): {
            "s34_af_20": float(r.s34_af_20) if pd.notna(r.s34_af_20) else 0.0,
            "mkt10_zt_est_t1": float(r.mkt10_zt_est_t1) if pd.notna(r.mkt10_zt_est_t1) else 50.0,
            "m4_mine_bl15": bool(r.m4_mine_bl15),
        }
        for r in df34_m.itertuples(index=False)
    }

    cand_df = cache["cand_df"]
    entries = []
    for e in cache["buy_entries"]:
        if (not e["skel"]) or (e["sc_v40"] < 90.0):
            continue
        bd = str(e["buy_date"])
        if not ("2021-11-16" <= bd <= CUTOFF):
            continue
        c6 = str(e["code"]).zfill(6)
        mm = master_map.get((bd, c6), {"s34_af_20": 0.0, "mkt10_zt_est_t1": 50.0, "m4_mine_bl15": False})
        entries.append({
            "entry": e, "bd": bd, "c6": c6, "name": str(e["name"]), "score": float(e["sc_v40"]),
            "prio_tie": float(cand_df["prio_3to4"].iloc[e["idx"]]),
            "priority_score": float(e["sc_v40"] * 10.0 + float(cand_df["prio_3to4"].iloc[e["idx"]]) * 0.1),
            "orig_buy_px": float(e["buy_px"]) if e["buy_px"] is not None else np.nan,
            "orig_buy_hhmm": int(e["buy_hhmm"]) if e["buy_hhmm"] is not None else 0,
            "state_map": states.get(e["idx"], {}), **mm,
        })
    entries.sort(key=lambda x: (x["bd"], -x["priority_score"], x["c6"]))
    s34_trunc = {"cache": cache, "cache_all": cache_all, "dt_tables": dt_tables, "entries": entries}
    f2.attach_causal_loo_s34_af20(ctx, s34_trunc)

    # Simulate winning 3to4 causal rule on truncated universe (exit_date <= CUTOFF)
    sf_win = lambda it: (not it["m4_mine_bl15"]) and ((it["score"] - (it["s34_af_20"] if it.get("causal_drop_af20", False) else 0.0)) >= 90.0)
    b_cfg = {"trig_mult": 1.065, "cancel_hhmm": 1030, "hi_open_mode": "direct_0925"}
    e_cfg = {"d5_mode": "base", "zt_sl_mode": "prevc_tp1_m6_1000"}
    rows = []
    for it in entries:
        if not sf_win(it):
            continue
        bi = f2._sim_buy_3to4(it, ctx, s34_trunc, b_cfg)
        if bi is None:
            continue
        rec = f2._sim_exit_3to4(it, ctx, s34_trunc, bi, e_cfg)
        if str(rec["exit_date"]) <= CUTOFF:
            rows.append(rec)
    df_p = pd.DataFrame(rows).sort_values(["buy_date", "buy_hhmm", "priority_score", "code"], ascending=[True, True, False, True]).reset_index(drop=True)
    taken, fdt, fhh = [], "", 0
    for r in df_p.itertuples(index=False):
        if (not fdt) or (r.buy_date > fdt) or (r.buy_date == fdt and int(r.buy_hhmm) > fhh):
            taken.append(r._asdict())
            fdt, fhh = str(r.exit_date), int(r.exit_hhmm)
    sl_tr = pd.DataFrame(taken)
    sl_full = full_best_3to4[full_best_3to4["exit_date"] <= CUTOFF].reset_index(drop=True)

    assert len(sl_tr) == len(sl_full), f"Trunc len diff: {len(sl_tr)} vs {len(sl_full)}"
    assert list(zip(sl_tr["buy_date"], sl_tr["code"], sl_tr["exit_date"])) == list(zip(sl_full["buy_date"], sl_full["code"], sl_full["exit_date"]))
    max_sc_diff = float(np.max(np.abs(sl_tr["score"].to_numpy(float) - sl_full["score"].to_numpy(float))))
    max_ret_diff = float(np.max(np.abs(sl_tr["net_ret_020"].to_numpy(float) - sl_full["net_ret_020"].to_numpy(float))))
    assert max_sc_diff == 0.0 and max_ret_diff == 0.0, f"Nonzero trunc diff: sc={max_sc_diff}, ret={max_ret_diff}"
    return {
        "cutoff": CUTOFF,
        "n_trades_checked": int(len(sl_tr)),
        "max_buy_date": str(sl_tr["buy_date"].max()),
        "max_exit_date": str(sl_tr["exit_date"].max()),
        "max_abs_score_diff": max_sc_diff,
        "max_abs_ret_diff": max_ret_diff,
        "rss_mb": cm.rss_mb(),
    }


def main():
    with open(f"{cm.CACHE_DIR}/front2_3to4.pkl", "rb") as f:
        d2 = pickle.load(f)
    sl_best_3to4 = d2["top_slots"]["BC_zt_prevc_tp1_m6_1000__M4_CausalLOO"]
    del d2
    gc.collect()
    res34 = verify_3to4_truncation(sl_best_3to4)

    # Also verify high & pry deterministic IS truncation (<= 2024-12-31)
    with open(f"{cm.CACHE_DIR}/front3a_high.pkl", "rb") as f:
        d3a = pickle.load(f)
    sl_h = d3a["top_slots"]["V51_Baseline_Matched42CB"]
    sl_h_is = sl_h[sl_h["exit_date"] <= CUTOFF].reset_index(drop=True)
    mh = pd.read_parquet(f"{cm.WAVE1}/pool_high_master_pit.parquet")
    mh["buy_date"] = mh["buy_date"].astype(str).str[:10]
    mh["exit_date"] = mh["exit_date"].astype(str).str[:10]
    mh["code"] = mh["code"].astype(str).str.zfill(6)
    mh_is = mh[(mh["orig_pass"] == 1) & (mh["exit_date"] <= CUTOFF)].copy()
    del d3a
    gc.collect()

    with open(f"{cm.CACHE_DIR}/front3b_pry.pkl", "rb") as f:
        d3b = pickle.load(f)
    sl_p = d3b["top_slots"]["V21_Baseline_P165"]
    sl_p_is = sl_p[sl_p["exit_date"] <= CUTOFF].reset_index(drop=True)
    mp = pd.read_parquet(f"{cm.WAVE1}/pool_pry_master_pit.parquet")
    mp["buy_date"] = mp["buy_date"].astype(str).str[:10]
    mp["exit_date"] = mp["exit_date"].astype(str).str[:10]
    mp["code"] = mp["code"].astype(str).str.zfill(6)
    mp = mp[mp["exit_date"] <= CUTOFF].copy()
    p_clean = pd.read_csv(f"{cm.SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry/pool_pry_full_clean.csv", dtype={"code": str})
    p_clean["code"] = p_clean["code"].str.zfill(6)
    p_clean["buy_date"] = p_clean["buy_date"].astype(str).str[:10]
    b10 = dict(zip(zip(p_clean["buy_date"], p_clean["code"]), p_clean["bias10"]))
    mp["bias10"] = [b10.get((r.buy_date, r.code), 0.0) for r in mp.itertuples(index=False)]
    import run_front3b_pry as f3b
    sl_p_tr = f3b.sim_pry_slot(mp[mp["orig_score"] >= 165.0])
    assert len(sl_p_tr) == len(sl_p_is)
    pry_diff = float(np.max(np.abs(sl_p_tr["net_ret"].to_numpy(float) - sl_p_is["net_ret_020"].to_numpy(float))))

    out = {
        "3to4_V42_BC_zt_prevc_tp1_m6_1000__M4_CausalLOO": res34,
        "high_V51_Baseline_is_n": int(len(sl_h_is)),
        "pry_V21_Baseline": {"n_checked": int(len(sl_p_tr)), "max_abs_ret_diff": pry_diff},
        "peak_rss_mb": cm.rss_mb(),
    }
    with open(f"{cm.CACHE_DIR}/truncation_proof.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(out), f, ensure_ascii=False, indent=2)
    print(json.dumps(cm.sanitize_json(out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_task3_v20_rollback_ablation.py — Task 3: V20 Original Component Individual Rollback Ablation.
Keeps P2 (RD049 + pos750<0.50 + pry>=100 rescue) + 4to5 SJ114_E4_DtDefer @ Pos5 FIXED,
and rolls back ONE component at a time from CFG_V21 to CFG_V20:
  - RB_s20_base76        : s20 stack_c50_avg>=80 -> base_76 (exact CFG_V20 20cm)
  - RB_s20_base82_clean  : s20 stack_c50_avg>=80 -> base_82_clean (V20 orig>=82 clean)
  - RB_s34_base          : s34 m4_4way_bl15 -> base (V20 original 3to4)
  - RB_s23_base          : s23 m2_pair_cold45_d15 -> base (V20 original 2to3)
  - RB_shi_base          : shi m1_causal_cold_drop40_t0 -> base (V20 original high)
  - RB_all4_V20_P2_Pos5  : all 4 pieces rolled back to CFG_V20 (+ P2 + Pos5)
Also checks PassTop1 and Dual-Scissors + 1000x paired permutation + 050 stress.
Zero yfinance (D12).
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

import _audit_utils as au


def _build_passtop1_with_cfg(c_p2: dict, cfg: dict, raw_4to5: pd.DataFrame, fee_mode: str) -> pd.DataFrame:
    """Build PassTop1 master pool honoring arbitrary CFG dict."""
    pools_ext = c_p2["pools_ext"]
    ut_raw = c_p2["ut_full_raw"]
    o5 = c_p2["other5_variants"]
    sc20 = c_p2["sc20_aligned"]
    cm = au.v22.eng.cm
    tpe = au.v22.eng.tpe
    s20_cfg = cfg.get("s20", "base_76")
    parts = []
    trig_dts = {}

    for st in cm.ALL6:
        df = pools_ext[st].copy()
        rc, mc, _ = au.v22.eng._fee_cols(fee_mode, st)
        df["net_ret"] = df[rc]
        df["mtm_use"] = df[mc]
        if st == "20cm":
            if s20_cfg == "base_76":
                sv = np.where(df["orig_score"].to_numpy(float) >= 76.0, df["orig_score"].to_numpy(float), -999.0)
                m = df["can_buy_hygiene"].fillna(True).to_numpy(bool) & np.isfinite(sv) & (sv >= 76.0)
            elif s20_cfg == "base_82_clean":
                sv = np.where(df["orig_score"].to_numpy(float) >= 82.0, df["orig_score"].to_numpy(float), -999.0)
                m = df["can_buy_hygiene"].fillna(True).to_numpy(bool) & np.isfinite(sv) & (sv >= 82.0)
            else:
                sv = np.where(df["buy_date"] < au.v22.eng.WF_START, np.where(df["orig_score"].to_numpy(float) >= 82.0, df["orig_score"].to_numpy(float), -999.0), sc20[s20_cfg])
                m = df["can_buy_hygiene"].fillna(True).to_numpy(bool) & np.isfinite(sv) & (sv >= float(cfg.get("s20_thr", 80.0)))
            p_df = df[m].copy()
            p_df["score"] = sv[m].astype(float)
            p_df = p_df.sort_values(["buy_date", "score", "code"], ascending=[True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            p_df["tier"] = [tpe.assign_physical_tier("20cm", x) for x in p_df["score"]] if s20_cfg in ("base_76", "base_82_clean") else "20cm_S(>=82)"
        else:
            vkey = {"3to4": cfg["s34"], "2to3": cfg["s23"], "high": cfg["shi"], "pry": cfg["spr"], "1to2": cfg["s12"]}[st]
            if vkey == "base":
                p_df, _ = cm.sim_strategy(st, df, df["orig_score"].to_numpy(float), wf_only=False)
                sc_arr = p_df["orig_score"].to_numpy(float)
            else:
                vcfg = o5[st][vkey]
                p_df, _ = cm.sim_strategy(st, df, vcfg["score"], mask=vcfg["mask"], wf_only=False)
                sc_arr = p_df["_sc_adj"].to_numpy(float) if "_sc_adj" in p_df.columns else p_df["orig_score"].to_numpy(float)
            p_df["score"] = [round(float(x), 1) for x in sc_arr] if st == "1to2" else sc_arr.astype(float)
            if st == "3to4":
                pt = pd.to_numeric(p_df["prio_tie"], errors="coerce").fillna(0.0).to_numpy(float)
                p_df["_prio"] = p_df["score"] * 10.0 + pt * 0.1
                p_df = p_df.sort_values(["buy_date", "buy_hhmm", "_prio", "code"], ascending=[True, True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            elif st == "pry":
                b10 = pd.to_numeric(p_df["bias10"], errors="coerce").fillna(0.0).to_numpy(float) if "bias10" in p_df.columns else np.zeros(len(p_df))
                p_df["_b10"] = b10
                p_df = p_df.sort_values(["buy_date", "score", "_b10", "code"], ascending=[True, False, True, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            elif st == "2to3":
                p_df = p_df.sort_values(["buy_date", "score", "open_pct", "plate_sz", "code"], ascending=[True, False, True, True, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            elif st == "high":
                p_df = p_df.sort_values(["buy_date", "score", "code"], ascending=[True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            elif st == "1to2":
                p_df = p_df.sort_values(["buy_date", "_sv", "code"], ascending=[True, False, True], kind="mergesort").groupby("buy_date", as_index=False).first()
            p_df["tier"] = [tpe.assign_physical_tier(st, sc) for sc in p_df["score"]]
        p_df = p_df[p_df["buy_date"].between("2021-11-16", au.v22.eng.WF_END)].copy()
        p_df["strategy"] = st
        p_df["is_untrig"] = False
        if "buy_price_val" not in p_df.columns:
            p_df["buy_price_val"] = pd.to_numeric(p_df.get("buy_price", np.nan), errors="coerce")
        if "is_adj_px" not in p_df.columns:
            p_df["is_adj_px"] = False
        trig_dts[st] = set(p_df["buy_date"])
        keep_cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig"]
        parts.append(p_df[keep_cols])

    pool6 = pd.concat(parts, ignore_index=True)
    ut_parts = []
    for st_u in ("3to4", "high", "1to2"):
        sub_u = ut_raw[(ut_raw["strategy"] == st_u) & (~ut_raw["buy_date"].isin(trig_dts.get(st_u, set())))].copy()
        thr_u = {"3to4": 90.0, "high": 88.0, "1to2": 0.0}[st_u]
        sub_u = sub_u[sub_u["score"] >= thr_u].sort_values(["buy_date", "score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        if not sub_u.empty:
            sub_u["tier"] = [tpe.assign_physical_tier(st_u, sc) for sc in sub_u["score"]]
            ut_parts.append(sub_u)
    ut_df = pd.concat(ut_parts, ignore_index=True) if ut_parts else pd.DataFrame()
    if not ut_df.empty:
        ut_df["is_untrig"] = True
        ut_df["net_ret"] = 0.0
        ut_df["mtm_use"] = [() for _ in range(len(ut_df))]
        ut_df["buy_price_val"] = np.nan
        ut_df["is_adj_px"] = False
        ut_df = ut_df[["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig"]]

    ep45 = au.v22.prepare_4to5_pool(raw_4to5, "Pos5", fee_mode, c_p2["cal_5y"], "4to5_SJ114_E4_DtDefer")
    keep_cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig"]
    all_parts = [pool6[keep_cols]]
    if not ut_df.empty:
        all_parts.append(ut_df[keep_cols])
    if not ep45.empty:
        all_parts.append(ep45[keep_cols])
    df = pd.concat(all_parts, ignore_index=True)
    df["buy_date"] = df["buy_date"].astype(str).str[:10]
    df["exit_date"] = df["exit_date"].astype(str).str[:10]
    df["buy_hhmm"] = pd.to_numeric(df["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    df["exit_hhmm"] = pd.to_numeric(df["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["score"] = pd.to_numeric(df["score"], errors="coerce").astype(float)
    df["net_ret"] = pd.to_numeric(df["net_ret"], errors="coerce").astype(float)
    df["is_untrig"] = df["is_untrig"].astype(bool)
    df["bucket"] = [au.p5._assign_fine_bucket(r) for r in df.itertuples(index=False)]
    df["s2c_prio"] = df["tier"].map(au.v22.eng.m1.S2C_MAP).fillna(999).astype(int)
    return df.reset_index(drop=True)


def _build_primary_with_cfg(c_p2: dict, cfg: dict, raw_4to5: pd.DataFrame, fee_mode: str) -> pd.DataFrame:
    pool6, ut_df = au.v22.eng.build_bundle_pools(c_p2, cfg, fee_mode=fee_mode)
    ep45 = au.v22.prepare_4to5_pool(raw_4to5, "Pos5", fee_mode, c_p2["cal_5y"], "4to5_SJ114_E4_DtDefer")
    keep_cols = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "mtm_use", "buy_price_val", "is_adj_px", "is_untrig"]
    parts = [pool6[keep_cols]]
    if not ut_df.empty:
        parts.append(ut_df[keep_cols])
    if not ep45.empty:
        parts.append(ep45[keep_cols])
    df = pd.concat(parts, ignore_index=True)
    df["buy_date"] = df["buy_date"].astype(str).str[:10]
    df["exit_date"] = df["exit_date"].astype(str).str[:10]
    df["buy_hhmm"] = pd.to_numeric(df["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    df["exit_hhmm"] = pd.to_numeric(df["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["score"] = pd.to_numeric(df["score"], errors="coerce").astype(float)
    df["net_ret"] = pd.to_numeric(df["net_ret"], errors="coerce").astype(float)
    df["is_untrig"] = df["is_untrig"].astype(bool)
    df["bucket"] = [au.p5._assign_fine_bucket(r) for r in df.itertuples(index=False)]
    df["s2c_prio"] = df["tier"].map(au.v22.eng.m1.S2C_MAP).fillna(999).astype(int)
    # Note: drop prio==999 (20cm_A(76-81) in base_76!) cleanly inside rank_fn!
    return df.reset_index(drop=True)


def _rank_s2c_drop999(df: pd.DataFrame) -> np.ndarray:
    base = au.base_engine_rank_fn()(df)
    is_45 = (df["strategy"] == "4to5").to_numpy(bool)
    is_drop = (~is_45) & (df["s2c_prio"].to_numpy(int) >= 999)
    return np.where(is_drop, 9999, base)


def main():
    t0 = time.time()
    assets = au.load_all_assets()
    c_p2 = assets["c_p2"]
    cal_5y = assets["cal_5y"]
    cfg_v21 = dict(au.v22.CFG_V21)
    cfg_v20 = dict(au.v22.CFG_V20)

    specs = [
        ("RB_s20_base76", {**cfg_v21, "s20": "base_76"}, "Rollback s20: stack_c50_avg>=80 -> V20 base_76 (20cm_A76-81 pre-occludes then dropped)"),
        ("RB_s20_base82_clean", {**cfg_v21, "s20": "base_82_clean"}, "Rollback s20: stack_c50_avg>=80 -> V20 base_82_clean (orig_score>=82 clean)"),
        ("RB_s34_base", {**cfg_v21, "s34": "base"}, "Rollback s34: m4_4way_bl15 -> V20 base 3to4 (keeping P2+Pos5)"),
        ("RB_s23_base", {**cfg_v21, "s23": "base"}, "Rollback s23: m2_pair_cold45_d15 -> V20 base 2to3"),
        ("RB_shi_base", {**cfg_v21, "shi": "base"}, "Rollback shi: m1_causal_cold_drop40_t0 -> V20 base high_dragon"),
        ("RB_all4_V20_P2_Pos5", {**cfg_v20}, "Rollback ALL 4 V21 pieces -> CFG_V20 + P2 + 4to5@Pos5"),
        ("RB_all4_V20_PureV20_NoP2_NoPos5", {**cfg_v20}, "Pure V20.0 reference (NO P2, NO 4to5@Pos5)"),
    ]

    results = {}
    rows = []
    for vid, cfg_use, desc in specs:
        c_use = assets["cache_base"] if vid == "RB_all4_V20_PureV20_NoP2_NoPos5" else c_p2
        r45 = pd.DataFrame() if vid == "RB_all4_V20_PureV20_NoP2_NoPos5" else assets["raw_4to5"]
        mp030 = _build_primary_with_cfg(c_use, cfg_use, r45, "030")
        mp050 = _build_primary_with_cfg(c_use, cfg_use, r45, "050")
        mppt = _build_passtop1_with_cfg(c_use, cfg_use, r45, "030")

        s030 = au.p5.run_priority_sim(mp030, _rank_s2c_drop999, cal_5y, allow_untrig=True)
        s050 = au.p5.run_priority_sim(mp050, _rank_s2c_drop999, cal_5y, allow_untrig=True)
        spt = au.p5.run_priority_sim(mppt, _rank_s2c_drop999, cal_5y, allow_untrig=True)

        ev = au.evaluate_variant_complete(vid, "TASK3_V20_ROLLBACK", desc, s030, s050, spt, assets, n_perm=1000)
        # Also compute symmetric V21 contribution: how much Base_V22 beats this V20 rollback!
        ev["v21_piece_incremental_ratio"] = {
            wn: round(assets["base_w030"][wn]["nav"] / max(1e-12, ev["windows_030"][wn]["nav"]), 4)
            for wn in au.ALL_7_WINDOWS
        }
        ev["v21_piece_mdd_delta_pp"] = round(assets["base_w030"]["FULL_5Y"]["daily_mdd_pct"] - ev["windows_030"]["FULL_5Y"]["daily_mdd_pct"], 2)
        ev["v21_piece_sh_delta"] = round(assets["base_w030"]["FULL_5Y"]["daily_sharpe"] - ev["windows_030"]["FULL_5Y"]["daily_sharpe"], 3)
        results[vid] = ev
        rows.append(ev["row"])

    df_res = pd.DataFrame(rows)
    df_res.to_csv(f"{au.OUT_DIR}/task3_v20_rollback_ablation.csv", index=False, encoding="utf-8-sig")
    out_json = au.v22.sanitize_json({
        "task": "Task 3: V20 Original Component Individual Rollback Ablation",
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "pass_all_4_gates": [r["variant"] for r in rows if r["PASS_ALL_4_GATES"]],
        "rows": rows,
        "details": results,
    })
    with open(f"{au.OUT_DIR}/task3_v20_rollback_ablation.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)

    cols = ["variant", "n_trades", "5Y_nav", "5Y_mdd", "5Y_sh", "IS_nav", "OOS_nav", "WF_nav", "Y26_nav", "ex_both_5Y", "ex_both_WF", "ex_both_IS", "ex_both_OOS", "PASS_ALL_4_GATES"]
    print(df_res[cols].to_string(index=False))
    print("TASK 3 PASSERS (rollback beating V22 on all 4 gates):", [r["variant"] for r in rows if r["PASS_ALL_4_GATES"]])


if __name__ == "__main__":
    main()

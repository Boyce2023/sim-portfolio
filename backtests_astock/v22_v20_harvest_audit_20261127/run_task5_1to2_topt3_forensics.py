#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_task5_1to2_topt3_forensics.py — Task 5: Fine-Priority Last-Mile Audit
1to2_cond >= thr moved to top of Tier 3 (ahead of 3to4_A_cond & high_A_cond):
  - Sweep thr in [295.0, 304.8, 320.0, 330.0, 335.0, 340.0, 345.0, 350.0, 354.0, 355.0, 360.0, 365.0, 370.0]
  - Compare EngineS2C anchor vs Strict3Tier anchor
  - Compare with untriggered waits (is_untrig=True allowed to block 3to4_A_cond) vs triggered-only jump!
  - Full trade-by-trade diff dissection, Dual-Scissors, and 1000x paired permutation test.
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


def _make_1to2_cond_topt3_fn(thr: float, trig_only_jump: bool = False, strict_3tier: bool = False):
    """Move 1to2 intraday (>925) conditional >= thr ahead of 3to4_A_cond & high_A_cond."""
    def _fn(df: pd.DataFrame) -> np.ndarray:
        is_45 = (df["strategy"] == "4to5").to_numpy(bool)
        is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]).to_numpy(bool)
        hh = df["buy_hhmm"].to_numpy(int)
        is_p0 = (hh == 925) | is_s_cond
        s2c_p = df["s2c_prio"].to_numpy(int)
        if strict_3tier:
            base_rk = np.where(is_s_cond, s2c_p * 10, np.where(is_p0, 100 + s2c_p * 10, 1000 + s2c_p * 10))
        else:
            base_rk = np.where(is_p0, s2c_p * 10, 1000 + s2c_p * 10)
        is_12c = (df["strategy"] == "1to2").to_numpy(bool) & (hh > 925) & (df["score"].to_numpy(float) >= float(thr))
        if trig_only_jump:
            is_12c = is_12c & (~df["is_untrig"].to_numpy(bool))
        rk = np.where(is_12c, 1005, base_rk)
        return np.where(is_45, 2000, rk)
    return _fn


def _collect_all_1to2_cond_collisions(mp: pd.DataFrame) -> list[dict]:
    """Find every date where a Tier 3 1to2_cond (>925) coexists with 3to4_A_cond or high_A_cond."""
    c_rows = []
    for dt, grp in mp.groupby("buy_date"):
        m12 = grp[(grp["strategy"] == "1to2") & (grp["buy_hhmm"] > 925)]
        m_other_t3 = grp[grp["bucket"].isin(["3to4_A_cond", "high_A_cond"])]
        if m12.empty or m_other_t3.empty:
            continue
        p0 = grp[(grp["strategy"] != "4to5") & ((grp["buy_hhmm"] == 925) | grp["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]))]
        for r12 in m12.itertuples(index=False):
            for ro in m_other_t3.itertuples(index=False):
                c_rows.append({
                    "buy_date": dt,
                    "has_higher_p0_on_day": not p0.empty,
                    "p0_strats": sorted(p0["strategy"].unique().tolist()),
                    "1to2_code": r12.code, "1to2_name": r12.name, "1to2_score": round(float(r12.score), 2),
                    "1to2_untrig": bool(r12.is_untrig), "1to2_ret_pct": round(float(r12.net_ret) * 100.0, 2),
                    "other_strat": ro.strategy, "other_code": ro.code, "other_name": ro.name,
                    "other_score": round(float(ro.score), 2), "other_untrig": bool(ro.is_untrig),
                    "other_ret_pct": round(float(ro.net_ret) * 100.0, 2),
                })
    return c_rows


def main():
    t0 = time.time()
    assets = au.load_all_assets()
    cal_5y = assets["cal_5y"]

    collisions = _collect_all_1to2_cond_collisions(assets["mp030"])

    thrs = [295.0, 304.8, 320.0, 330.0, 335.0, 340.0, 345.0, 350.0, 354.0, 355.0, 360.0, 365.0, 370.0]
    specs = []
    for thr in thrs:
        specs.append((f"T5_Eng_ge{thr:g}_WithUT", thr, False, False, f"EngineS2C + 1to2_cond>={thr:g} top of Tier3 (incl. untriggered waits)"))
        if thr in (304.8, 340.0, 350.0, 354.0, 360.0):
            specs.append((f"T5_Eng_ge{thr:g}_TrigOnly", thr, True, False, f"EngineS2C + 1to2_cond>={thr:g} triggered-only top of Tier3"))
            specs.append((f"T5_Str3_ge{thr:g}_WithUT", thr, False, True, f"Strict3Tier + 1to2_cond>={thr:g} top of Tier3"))

    results = {}
    rows = []
    for vid, thr, trig_only, s3t, desc in specs:
        rfn = _make_1to2_cond_topt3_fn(thr, trig_only_jump=trig_only, strict_3tier=s3t)
        s030 = au.p5.run_priority_sim(assets["mp030"], rfn, cal_5y, allow_untrig=True)
        s050 = au.p5.run_priority_sim(assets["mp050"], rfn, cal_5y, allow_untrig=True)
        spt = au.p5.run_priority_sim(assets["mp_pt030"], rfn, cal_5y, allow_untrig=True)
        ev = au.evaluate_variant_complete(vid, "TASK5_1TO2_TOPT3", desc, s030, s050, spt, assets, n_perm=1000)
        results[vid] = ev
        rows.append(ev["row"])

    df_res = pd.DataFrame(rows)
    df_res.to_csv(f"{au.OUT_DIR}/task5_1to2_topt3_forensics.csv", index=False, encoding="utf-8-sig")
    out_json = au.v22.sanitize_json({
        "task": "Task 5: 1to2_cond >= 340 TopT3 vs >= 360 Non-Monotonicity Forensics",
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "all_tier3_1to2_collisions_in_pool": collisions,
        "pass_all_4_gates": [r["variant"] for r in rows if r["PASS_ALL_4_GATES"]],
        "rows": rows,
        "details": results,
    })
    with open(f"{au.OUT_DIR}/task5_1to2_topt3_forensics.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)

    cols = ["variant", "n_trades", "5Y_nav", "5Y_mdd", "5Y_sh", "IS_nav", "OOS_nav", "WF_nav", "Y26_nav", "n_added", "n_removed", "ex_both_5Y", "ex_both_WF", "ex_both_IS", "ex_both_OOS", "paired_p1_WF", "PASS_ALL_4_GATES"]
    print(df_res[cols].to_string(index=False))
    print("\nALL 1to2_cond vs T3 collisions count:", len(collisions))
    for c in collisions:
        if not c["has_higher_p0_on_day"]:
            print("  ACTIVE (no P0):", c)


if __name__ == "__main__":
    main()

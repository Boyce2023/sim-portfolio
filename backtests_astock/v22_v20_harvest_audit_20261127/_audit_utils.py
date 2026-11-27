#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
_audit_utils.py — Shared V22.0 Causal Audit Core (Read-only on Prod/P5/P3/RD038).
Reproduces Pure_V21_P2_SJ114_E4_Pos5 and provides 7-window D15, Dual-Scissors,
1000x paired permutation, 050 stress, PassTop1 cross-check, and 2024-12-31 truncation proof.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import json
import pickle
import sys
from typing import Callable, Optional

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock/v22_v20_harvest_audit_20261127"
P3 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p3_v22_grand_assembly"
P5 = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p5_v22_collision_priority_audit"
RD038 = f"{SIM}/backtests_astock2/rd038_grand_bundle_assembly_20261126"
RD049 = f"{SIM}/backtests_astock2/rd049_traffic_light_granular_20261126"

for p in (P3, P5, RD038, RD049):
    if p not in sys.path:
        sys.path.insert(0, p)

import _v22_engine as v22
import _p5_engine as p5

ALL_7_WINDOWS = ["FULL_5Y", "IS_2123", "OOS_2426", "WF_2326", "Y2025_2026", "Y2026", "Y2026_H2"]


def base_engine_rank_fn(map_4to5: Optional[dict[str, int]] = None):
    m45 = map_4to5 or {"4to5_S120": 900, "4to5_114_119": 900}
    return p5.make_engine_s2c_rank_fn(m45)


def load_all_assets() -> dict:
    assets = p5.load_p5_raw_assets()
    c_p2 = assets["c_p2"]
    cal_5y = c_p2["cal_5y"]
    mp030 = p5.build_p5_master_pool(c_p2, assets["raw_4to5"], fee_mode="030", use_pass_top1=False)
    mp050 = p5.build_p5_master_pool(c_p2, assets["raw_4to5"], fee_mode="050", use_pass_top1=False)
    mp_pt030 = p5.build_p5_master_pool(c_p2, assets["raw_4to5"], fee_mode="030", use_pass_top1=True)

    rfn_base = base_engine_rank_fn()
    b030 = p5.run_priority_sim(mp030, rfn_base, cal_5y, allow_untrig=True)
    bw030 = p5.eval_fast_windows(b030, assets["cache_base"])
    b050 = p5.run_priority_sim(mp050, rfn_base, cal_5y, allow_untrig=True)
    bw050 = p5.eval_fast_windows(b050, assets["cache_base"])
    bpt = p5.run_priority_sim(mp_pt030, rfn_base, cal_5y, allow_untrig=True)
    bwpt = p5.eval_fast_windows(bpt, assets["cache_base"])

    # Hard assert exact reproduction of Pure_V21_P2_SJ114_E4_Pos5
    assert bw030["FULL_5Y"]["n"] == 276
    assert abs(bw030["FULL_5Y"]["nav"] - 4165511674.47) < 1.0, bw030["FULL_5Y"]["nav"]
    assert abs(bw030["FULL_5Y"]["daily_mdd_pct"] - 28.80) < 1e-6
    assert abs(bw030["WF_2326"]["nav"] - 28047344.00) < 1.0

    return {
        **assets,
        "cal_5y": cal_5y,
        "mp030": mp030,
        "mp050": mp050,
        "mp_pt030": mp_pt030,
        "base_030": b030,
        "base_w030": bw030,
        "base_050": b050,
        "base_w050": bw050,
        "base_pt": bpt,
        "base_wpt": bwpt,
    }


def extract_7win_compact(w_dict: dict) -> dict:
    out = {}
    for wn in ALL_7_WINDOWS:
        x = w_dict[wn]
        out[wn] = {
            "n": int(x["n"]),
            "nav": float(x["nav"]),
            "daily_mdd_pct": float(x["daily_mdd_pct"]),
            "second_mdd_pct": float(x["second_mdd_pct"]),
            "daily_sharpe": float(x["daily_sharpe"]),
            "daily_calmar": float(x["daily_calmar"]),
            "excess_csi300_pp": float(x["excess_csi300_pp"]),
            "csi300_pct": float(x["csi300_pct"]),
            "wr_pct": float(x["wr_pct"]),
            "plr": float(x["plr"]),
            "mean_pct": float(x["mean_pct"]),
            "ex_top5_nav": float(x["ex_top5_nav"]),
        }
    return out


def compute_diff_trades(base_tr: pd.DataFrame, cand_tr: pd.DataFrame) -> list[dict]:
    kb = {(str(r.buy_date)[:10], str(r.code).zfill(6), str(r.strategy)): r for r in base_tr.itertuples(index=False)}
    kn = {(str(r.buy_date)[:10], str(r.code).zfill(6), str(r.strategy)): r for r in cand_tr.itertuples(index=False)}
    diffs = []
    for k in sorted(kb):
        if k not in kn:
            r = kb[k]
            diffs.append({
                "action": "REMOVED", "buy_date": r.buy_date, "exit_date": r.exit_date,
                "buy_hhmm": int(r.buy_hhmm), "strategy": r.strategy, "tier": str(r.tier),
                "bucket": str(getattr(r, "bucket", "")), "code": r.code, "name": str(r.name),
                "score": round(float(r.score), 2), "ret_pct": round(float(r.net_ret) * 100.0, 2),
                "window_tag": "IS" if r.buy_date <= "2023-12-31" else "OOS",
            })
    for k in sorted(kn):
        if k not in kb:
            r = kn[k]
            diffs.append({
                "action": "ADDED", "buy_date": r.buy_date, "exit_date": r.exit_date,
                "buy_hhmm": int(r.buy_hhmm), "strategy": r.strategy, "tier": str(r.tier),
                "bucket": str(getattr(r, "bucket", "")), "code": r.code, "name": str(r.name),
                "score": round(float(r.score), 2), "ret_pct": round(float(r.net_ret) * 100.0, 2),
                "window_tag": "IS" if r.buy_date <= "2023-12-31" else "OOS",
            })
    diffs.sort(key=lambda d: (d["buy_date"], d["action"], d["code"]))
    return diffs


def evaluate_variant_complete(
    vid: str,
    group: str,
    desc: str,
    s030: dict,
    s050: dict,
    spt: Optional[dict],
    assets: dict,
    n_perm: int = 1000,
) -> dict:
    rel_5y = s030["mtm_diff_5y"] / max(1.0, float(np.prod(1.0 + s030["dr_5y"])))
    rel_wf = s030["mtm_diff_wf"] / max(1.0, float(np.prod(1.0 + s030["dr_wf"])))
    assert rel_5y < 1e-8, f"MTM rel diff 5y on {vid}: {rel_5y} (abs={s030['mtm_diff_5y']})"
    assert rel_wf < 1e-8, f"MTM rel diff wf on {vid}: {rel_wf} (abs={s030['mtm_diff_wf']})"

    cache_base = assets["cache_base"]
    w030 = p5.eval_fast_windows(s030, cache_base)
    w050 = p5.eval_fast_windows(s050, cache_base)
    wpt = p5.eval_fast_windows(spt, cache_base) if spt is not None else None

    b030 = assets["base_030"]
    bw030 = assets["base_w030"]
    b050 = assets["base_050"]
    bw050 = assets["base_w050"]

    sc_5y = p5.calc_window_dual_scissors(s030["trades_df"], b030["trades_df"], w030, bw030, "FULL_5Y", "2021-11-16", "2026-11-16")
    sc_wf = p5.calc_window_dual_scissors(s030["trades_df"], b030["trades_df"], w030, bw030, "WF_2326", "2023-01-03", "2026-11-16")
    sc_is = p5.calc_window_dual_scissors(s030["trades_df"], b030["trades_df"], w030, bw030, "IS_2123", "2021-11-16", "2023-12-31")
    sc_oos = p5.calc_window_dual_scissors(s030["trades_df"], b030["trades_df"], w030, bw030, "OOS_2426", "2024-01-01", "2026-11-16")

    p_wf = v22.paired_perm_test(s030["dr_wf"], b030["dr_wf"], n_perm=n_perm)
    p_5y = v22.paired_perm_test(s030["dr_5y"], b030["dr_5y"], n_perm=n_perm)

    # Four Cold-Blooded Anti-Overfit Gates (strict parity with P5 step2)
    g1_is_oos_all = bool(
        w030["IS_2123"]["nav"] >= bw030["IS_2123"]["nav"] - 1e-6
        and w030["OOS_2426"]["nav"] >= bw030["OOS_2426"]["nav"] - 1e-6
        and w030["WF_2326"]["nav"] >= bw030["WF_2326"]["nav"] - 1e-6
        and w030["Y2025_2026"]["nav"] >= bw030["Y2025_2026"]["nav"] - 1e-6
        and w030["Y2026"]["nav"] >= bw030["Y2026"]["nav"] - 1e-6
        and w030["FULL_5Y"]["nav"] > bw030["FULL_5Y"]["nav"] + 1e-6
    )
    g1_strict_both_is_oos = bool(
        w030["IS_2123"]["nav"] > bw030["IS_2123"]["nav"] + 1e-6
        and w030["OOS_2426"]["nav"] > bw030["OOS_2426"]["nav"] + 1e-6
    )
    g2_dual_scissors_strict = bool(
        sc_5y["mult_ex_both"] > 1.0
        and sc_wf["mult_ex_both"] > 1.0
        and sc_is["mult_ex_both"] > 1.0
        and sc_oos["mult_ex_both"] > 1.0
    )
    g2_dual_scissors_p5 = bool(
        sc_5y["mult_ex_both"] > 1.0
        and sc_wf["mult_ex_both"] > 1.0
        and sc_is["mult_ex_both"] >= 1.0
        and sc_oos["mult_ex_both"] > 1.0
    )
    g3_mdd_2880 = bool(w030["FULL_5Y"]["daily_mdd_pct"] <= 28.80 + 1e-6)
    g4_050_stress = bool(
        w050["IS_2123"]["nav"] >= bw050["IS_2123"]["nav"] - 1e-6
        and w050["OOS_2426"]["nav"] >= bw050["OOS_2426"]["nav"] - 1e-6
        and w050["Y2025_2026"]["nav"] >= bw050["Y2025_2026"]["nav"] - 1e-6
        and w050["Y2026"]["nav"] >= bw050["Y2026"]["nav"] - 1e-6
        and w050["FULL_5Y"]["nav"] > bw050["FULL_5Y"]["nav"] + 1e-6
        and w050["FULL_5Y"]["daily_mdd_pct"] <= bw050["FULL_5Y"]["daily_mdd_pct"] + 1e-6
    )
    pass_all4_p5 = bool(g1_is_oos_all and g2_dual_scissors_p5 and g3_mdd_2880 and g4_050_stress)
    pass_all4_strict = bool(g1_is_oos_all and g2_dual_scissors_strict and g3_mdd_2880 and g4_050_stress)

    diffs = compute_diff_trades(b030["trades_df"], s030["trades_df"])

    flat_row = {
        "variant": vid, "group": group, "desc": desc,
        "n_trades": int(w030["FULL_5Y"]["n"]), "n_waits": int(len(s030["waits"])),
        "5Y_nav": w030["FULL_5Y"]["nav"], "5Y_mdd": w030["FULL_5Y"]["daily_mdd_pct"],
        "5Y_dd2": w030["FULL_5Y"]["second_mdd_pct"], "5Y_sh": w030["FULL_5Y"]["daily_sharpe"],
        "5Y_cal": w030["FULL_5Y"]["daily_calmar"], "5Y_ex300": w030["FULL_5Y"]["excess_csi300_pp"],
        "IS_nav": w030["IS_2123"]["nav"], "IS_mdd": w030["IS_2123"]["daily_mdd_pct"],
        "OOS_nav": w030["OOS_2426"]["nav"], "OOS_mdd": w030["OOS_2426"]["daily_mdd_pct"],
        "WF_nav": w030["WF_2326"]["nav"], "WF_mdd": w030["WF_2326"]["daily_mdd_pct"],
        "Y2526_nav": w030["Y2025_2026"]["nav"], "Y26_nav": w030["Y2026"]["nav"],
        "Y26H2_nav": w030["Y2026_H2"]["nav"],
        "050_5Y_nav": w050["FULL_5Y"]["nav"], "050_5Y_mdd": w050["FULL_5Y"]["daily_mdd_pct"],
        "050_IS_nav": w050["IS_2123"]["nav"], "050_OOS_nav": w050["OOS_2426"]["nav"], "050_Y26_nav": w050["Y2026"]["nav"],
        "pt_5Y_nav": wpt["FULL_5Y"]["nav"] if wpt else None,
        "pt_IS_nav": wpt["IS_2123"]["nav"] if wpt else None,
        "pt_OOS_nav": wpt["OOS_2426"]["nav"] if wpt else None,
        "pt_WF_nav": wpt["WF_2326"]["nav"] if wpt else None,
        "n_added": sc_5y["n_added"], "n_removed": sc_5y["n_removed"],
        "ex_both_5Y": sc_5y["mult_ex_both"], "ex_both_WF": sc_wf["mult_ex_both"],
        "ex_both_IS": sc_is["mult_ex_both"], "ex_both_OOS": sc_oos["mult_ex_both"],
        "paired_t_5Y": p_5y["paired_t"], "paired_p1_5Y": p_5y["paired_perm_p_1sided"],
        "paired_t_WF": p_wf["paired_t"], "paired_p1_WF": p_wf["paired_perm_p_1sided"],
        "gate_is_oos_all": g1_is_oos_all,
        "strict_both_is_oos": g1_strict_both_is_oos,
        "gate_dual_scissors": g2_dual_scissors_p5,
        "gate_dual_scissors_strict": g2_dual_scissors_strict,
        "gate_mdd_2880": g3_mdd_2880,
        "gate_050_stress": g4_050_stress,
        "PASS_ALL_4_GATES": pass_all4_p5,
        "PASS_ALL_4_GATES_STRICT": pass_all4_strict,
    }

    return {
        "row": flat_row,
        "windows_030": extract_7win_compact(w030),
        "windows_050": extract_7win_compact(w050),
        "windows_passtop1": extract_7win_compact(wpt) if wpt else None,
        "dual_scissors": {"FULL_5Y": sc_5y, "WF_2326": sc_wf, "IS_2123": sc_is, "OOS_2426": sc_oos},
        "paired_5y": p_5y,
        "paired_wf": p_wf,
        "gates": {
            "gate_is_oos_all": g1_is_oos_all,
            "strict_both_is_oos": g1_strict_both_is_oos,
            "gate_dual_scissors": g2_dual_scissors_p5,
            "gate_dual_scissors_strict": g2_dual_scissors_strict,
            "gate_mdd_2880": g3_mdd_2880,
            "gate_050_stress": g4_050_stress,
            "PASS_ALL_4_GATES": pass_all4_p5,
            "PASS_ALL_4_GATES_STRICT": pass_all4_strict,
        },
        "diffs_vs_base": diffs,
    }

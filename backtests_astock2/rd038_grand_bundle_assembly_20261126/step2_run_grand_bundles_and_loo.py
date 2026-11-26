#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD038 Step 2 & 3: Grand Bundle Assembly (0.30/0.50/0.80), LOO, Forward Stepwise, Crowding Forensics & Portfolio DSR."""

import json
import os
import pickle
import resource
import sys
import time
from typing import Optional

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd038_grand_bundle_assembly_20261126"
CACHE_PKL = f"{OUT_DIR}/_cache/rd038_master_cache.pkl"
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

import _rd038_engine as eng
import _common_rd036 as cm

MONSTER_NAMES = {"合富中国", "艾艾精工", "超越科技", "正丹股份", "万邦医药", "盛帮股份", "东方精工", "双成药业", "海能达", "常山北明"}


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 1)


def classify_trade_diffs(
    bundle_name: str,
    sim_new: dict,
    sim_base: dict,
) -> list[dict]:
    """Forensic attribution of every removed V20 trade and every added trade vs BASE_V20_Unified."""
    tb = sim_base["trades_df"]
    tn = sim_new["trades_df"]
    kb = {(r.buy_date, r.code, r.strategy): r for r in tb.itertuples(index=False)}
    kn = {(r.buy_date, r.code, r.strategy): r for r in tn.itertuples(index=False)}

    pool_n_keys = {(r.buy_date, r.code, r.strategy): r for r in sim_new["pool6"].itertuples(index=False)}
    pool_b_keys = {(r.buy_date, r.code, r.strategy): r for r in sim_base["pool6"].itertuples(index=False)}

    # Build quick slot occupancy / day candidate maps on sim_new
    tn_by_dt = {r.buy_date: r for r in tn.itertuples(index=False)}
    tb_by_dt = {r.buy_date: r for r in tb.itertuples(index=False)}
    wait_n_by_dt = {w["buy_date"]: w for w in sim_new["waits"]}
    wait_b_by_dt = {w["buy_date"]: w for w in sim_base["waits"]}
    swap_n_by_dt = {s["swap_date"]: s for s in sim_new["swaps"]}

    # Occupied intervals by prior trade in sim_new
    tn_sorted = tn.sort_values(["buy_date", "buy_hhmm"]).reset_index(drop=True)
    tb_sorted = tb.sort_values(["buy_date", "buy_hhmm"]).reset_index(drop=True)

    def _find_blocking_trade(dt: str, bh: int, df_tr: pd.DataFrame) -> Optional[object]:
        for tr in df_tr.itertuples(index=False):
            if tr.buy_date < dt and (tr.exit_date > dt or (tr.exit_date == dt and int(tr.exit_hhmm) >= bh)):
                return tr
        return None

    rows = []
    # Removed V20 trades
    for k, rb in sorted(kb.items()):
        if k in kn:
            continue
        dt, cd, st = k
        bh = int(rb.buy_hhmm)
        if k not in pool_n_keys:
            cause = "DIRECT_RULE_DROP"
            blocker = f"{st}_filtered"
        elif dt in wait_n_by_dt and dt not in wait_b_by_dt:
            wn = wait_n_by_dt[dt]
            cause = "UNTRIG_WAIT_BLOCK"
            blocker = f"wait:{wn['wait_strategy']}:{wn['wait_code']}"
        elif dt in tn_by_dt:
            rn = tn_by_dt[dt]
            cause = "W2A5_SWAP_REPLACE" if dt in swap_n_by_dt else "SAME_DAY_PRIO_CROWD"
            blocker = f"{rn.strategy}:{rn.code}({rn.name})"
        else:
            bt = _find_blocking_trade(dt, bh, tn_sorted)
            if bt is not None:
                cause = "PRIOR_TRADE_LOCK"
                blocker = f"held:{bt.strategy}:{bt.code}({bt.name})->{bt.exit_date}"
            else:
                cause = "OTHER_CONFLICT"
                blocker = ""
        rows.append({
            "bundle": bundle_name, "diff_type": "REMOVED_FROM_V20", "window": "WF" if dt >= eng.WF_START else "IS",
            "buy_date": dt, "exit_date": str(rb.exit_date), "strategy": st, "tier": str(rb.tier),
            "code": cd, "name": str(rb.name), "is_monster": str(rb.name) in MONSTER_NAMES,
            "net_ret_030_pct": round(float(rb.net_ret) * 100.0, 2), "cause": cause, "blocker_or_source": blocker,
        })

    # Added vs V20 trades
    for k, rn in sorted(kn.items()):
        if k in kb:
            continue
        dt, cd, st = k
        bh = int(rn.buy_hhmm)
        if k not in pool_b_keys:
            cause = "DIRECT_RULE_ADD"
            src = f"{st}_new_pass"
        elif dt in swap_n_by_dt and swap_n_by_dt[dt]["new_code"] == cd:
            cause = "W2A5_SWAP_REPLACE"
            src = f"swap_from:{swap_n_by_dt[dt]['old_code']}"
        elif dt in tb_by_dt:
            rb = tb_by_dt[dt]
            cause = "SLOT_FREED_OR_PRIO_UP"
            src = f"beat:{rb.strategy}:{rb.code}({rb.name})"
        else:
            bt = _find_blocking_trade(dt, bh, tb_sorted)
            cause = "SLOT_FREED_BY_PRIOR_DROP" if bt is not None else "OTHER_FREE"
            src = f"v20_was_held:{bt.strategy}:{bt.code}({bt.name})" if bt is not None else ""
        rows.append({
            "bundle": bundle_name, "diff_type": "ADDED_VS_V20", "window": "WF" if dt >= eng.WF_START else "IS",
            "buy_date": dt, "exit_date": str(rn.exit_date), "strategy": st, "tier": str(rn.tier),
            "code": cd, "name": str(rn.name), "is_monster": str(rn.name) in MONSTER_NAMES,
            "net_ret_030_pct": round(float(rn.net_ret) * 100.0, 2), "cause": cause, "blocker_or_source": src,
        })
    return rows


def flatten_bundle_row(ev030: dict, ev050: dict, ev080: dict, cfg: dict, is_native: bool = False) -> list[dict]:
    """Flatten multi-window & multi-slippage metrics into tidy rows for CSV."""
    out = []
    for fee_tag, ev in ([("native", ev030)] if is_native else [("030", ev030), ("050", ev050), ("080", ev080)]):
        for wn, w in ev["windows"].items():
            out.append({
                "bundle": ev030["name"], "group": ev030["group"], "fee": fee_tag, "window": wn,
                "n": w["n"], "wr_pct": w["wr_pct"], "plr": w["plr"], "mean_pct": w["mean_pct"],
                "nav": w["nav"], "mtm_nav": w["mtm_nav"], "ex_top3_nav": w["ex_top3_nav"], "ex_top5_nav": w["ex_top5_nav"],
                "daily_sharpe": w["daily_sharpe"], "daily_mdd_pct": w["daily_mdd_pct"], "daily_calmar": w["daily_calmar"],
                "excess_csi300_pp": w["excess_csi300_pp"], "excess_alla_ew_pp": w["excess_alla_ew_pp"],
                "exposure_pct": w["exposure_pct"], "mtm_diff_wf": ev["mtm_diff_wf"],
                "perm_same_p": ev["perm_wf"].get("same_day_p_nav"), "perm_any_p": ev["perm_wf"].get("any_cand_day_p_nav"),
                "paired_t_vs_v20": ev["vs_v20_wf"].get("paired_t"), "paired_p_vs_v20": ev["vs_v20_wf"].get("paired_p_2sided"),
                "n_waits": ev["n_waits"], "n_swaps": ev["n_swaps"],
                "cfg_json": json.dumps(cfg, ensure_ascii=False),
            })
    return out


def main():
    t0 = time.time()
    print("[Step 2] Loading rd038_master_cache.pkl ...")
    with open(CACHE_PKL, "rb") as f:
        cache = pickle.load(f)

    # 1. Exact V20.0 Native & Unified Baselines
    cfg_v20 = {"s20": "base_76", "s34": "base", "s23": "base", "shi": "base", "spr": "base", "s12": "base", "w2a5": "none", "w2a6": "s_tier_reserve_only"}
    sim_nat = eng.run_bundle_sim(cache, cfg_v20, fee_mode="native")
    ev_nat = eng.evaluate_bundle("BASE_V20_Native", "0_BASELINE", sim_nat, cache, perm_n=1000)
    assert ev_nat["windows"]["FULL_5Y"]["n"] == 278 and abs(ev_nat["windows"]["FULL_5Y"]["nav"] - 69134091.5067) < 2.5
    assert ev_nat["windows"]["WF_2326"]["n"] == 207 and abs(ev_nat["windows"]["WF_2326"]["nav"] - 611729.5546) < 0.05
    assert ev_nat["mtm_diff_5y"] < 1e-6 and ev_nat["mtm_diff_wf"] < 1e-6
    print(f"  [BASE_V20_Native PASS] 5Y={ev_nat['windows']['FULL_5Y']['nav']:,.2f}x | WF={ev_nat['windows']['WF_2326']['nav']:,.2f}x Sh={ev_nat['windows']['WF_2326']['daily_sharpe']}")

    sim_b030 = eng.run_bundle_sim(cache, cfg_v20, fee_mode="030")
    sim_b050 = eng.run_bundle_sim(cache, cfg_v20, fee_mode="050")
    sim_b080 = eng.run_bundle_sim(cache, cfg_v20, fee_mode="080")
    ref_dr_wf = sim_b030["dr_wf"]
    ev_b030 = eng.evaluate_bundle("BASE_V20_Unified", "0_BASELINE", sim_b030, cache, ref_dr_wf=ref_dr_wf, perm_n=1000)
    ev_b050 = eng.evaluate_bundle("BASE_V20_Unified", "0_BASELINE", sim_b050, cache, perm_n=0)
    ev_b080 = eng.evaluate_bundle("BASE_V20_Unified", "0_BASELINE", sim_b080, cache, perm_n=0)

    bundle_defs = [
        ("BASE_V20_S82_Clean", "0_BASELINE", {**cfg_v20, "s20": "base_82_clean"}),
        ("BASE_V20_S80_Thresh", "0_BASELINE", {**cfg_v20, "s20": "base_80_wf"}),
        ("ONLY_20CM_COLD50_WF", "1_20CM_ONLY", {**cfg_v20, "s20": "cold50_wf"}),
        ("ONLY_20CM_COLD50_5Y", "1_20CM_ONLY", {**cfg_v20, "s20": "cold50_5y"}),
        ("ONLY_20CM_CLEANB", "1_20CM_ONLY", {**cfg_v20, "s20": "cleanb_c50_d15"}),
        ("ONLY_20CM_STACK", "1_20CM_ONLY", {**cfg_v20, "s20": "stack_c50_avg"}),
        ("ONLY_20CM_STACK_NoRound", "1_20CM_ONLY", {**cfg_v20, "s20": "stack_c50_noround"}),
        ("ONLY_20CM_BLEND", "1_20CM_ONLY", {**cfg_v20, "s20": "blend_c50_half"}),
        ("ONLY_20CM_BLEND_NoRound", "1_20CM_ONLY", {**cfg_v20, "s20": "blend_c50_noround"}),
        ("OTHER5_ONLY_ALLIN", "2_OTHER5_ONLY", {
            "s20": "base_76", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15",
            "shi": "m1_causal_cold_drop40_t0", "spr": "m1_skip_cold50", "s12": "base",
            "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S",
        }),
        ("ALLIN_ROBUST", "3_ALLIN", {
            "s20": "stack_c50_avg", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15",
            "shi": "m1_causal_cold_drop40_t0", "spr": "m1_skip_cold50", "s12": "base",
            "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S",
        }),
        ("ALLIN_ROBUST_NoRound", "3_ALLIN", {
            "s20": "stack_c50_noround", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15",
            "shi": "m1_causal_cold_drop40_t0", "spr": "m1_skip_cold50", "s12": "base",
            "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S",
        }),
        ("ALLIN_OFFENSIVE", "3_ALLIN", {
            "s20": "blend_c50_half", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15",
            "shi": "m1_causal_cold_drop40_t0", "spr": "m2_pair_cold45_d15", "s12": "base",
            "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S",
        }),
        ("ALLIN_OFFENSIVE_NoRound", "3_ALLIN", {
            "s20": "blend_c50_noround", "s34": "m4_4way_bl15", "s23": "m2_pair_cold45_d15",
            "shi": "m1_causal_cold_drop40_t0", "spr": "m2_pair_cold45_d15", "s12": "base",
            "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S",
        }),
        ("STATIC_LOO_REF", "5_NONCAUSAL_REF", {
            "s20": "blend_c50_half", "s34": "static_loo_af20", "s23": "static_cold_loo_af17",
            "shi": "m1_causal_cold_drop40_t0", "spr": "m2_pair_cold45_d15", "s12": "base",
            "w2a5": "S_HighTier_0925", "w2a6": "s_tier_plus_1to2S",
        }),
    ]

    all_rows = flatten_bundle_row(ev_nat, ev_nat, ev_nat, cfg_v20, is_native=True)
    all_rows.extend(flatten_bundle_row(ev_b030, ev_b050, ev_b080, cfg_v20))
    bundle_sims030 = {"BASE_V20_Unified": sim_b030}
    bundle_evals030 = {"BASE_V20_Unified": ev_b030}
    trial_daily_srs = [
        float(np.mean(sim_b030["dr_wf"]) / np.std(sim_b030["dr_wf"], ddof=1)),
    ]

    def _run_tri_fee(name: str, grp: str, cfg: dict, perm_n: int = 1000):
        s30 = eng.run_bundle_sim(cache, cfg, fee_mode="030")
        s50 = eng.run_bundle_sim(cache, cfg, fee_mode="050")
        s80 = eng.run_bundle_sim(cache, cfg, fee_mode="080")
        assert s30["mtm_diff_wf"] < 1e-6 and s30["mtm_diff_5y"] < 1e-6, f"MTM diff error on {name}"
        e30 = eng.evaluate_bundle(name, grp, s30, cache, ref_dr_wf=ref_dr_wf, perm_n=perm_n)
        e50 = eng.evaluate_bundle(name, grp, s50, cache, perm_n=0)
        e80 = eng.evaluate_bundle(name, grp, s80, cache, perm_n=0)
        trial_daily_srs.append(float(np.mean(s30["dr_wf"]) / np.std(s30["dr_wf"], ddof=1)))
        return s30, e30, e50, e80

    print("\n[Bundles] Evaluating core V20 / 20cm-only / All-In / Static-Ref across 0.30/0.50/0.80 ...")
    for bname, bgrp, bcfg in bundle_defs:
        s30, e30, e50, e80 = _run_tri_fee(bname, bgrp, bcfg, perm_n=1000)
        all_rows.extend(flatten_bundle_row(e30, e50, e80, bcfg))
        bundle_sims030[bname] = s30
        bundle_evals030[bname] = e30
        wf = e30["windows"]["WF_2326"]
        h2 = e30["windows"]["Y2026_H2"]
        print(f"  {bname:26s} | n={wf['n']:3d} WF={wf['nav']:12,.2f}x Ex5={wf['ex_top5_nav']:9,.2f}x Sh={wf['daily_sharpe']:.3f} MDD={wf['daily_mdd_pct']:5.2f}% 26H2={h2['nav']:.2f}x p={e30['vs_v20_wf']['paired_p_2sided']:.4f}")

    # =========================================================================
    # Step 3A: Leave-One-Out (LOO) on ALLIN_ROBUST and ALLIN_OFFENSIVE
    # =========================================================================
    print("\n[Step 3A] Leave-One-Out (LOO) decomposition on ALLIN_ROBUST & ALLIN_OFFENSIVE ...")
    loo_rows = []
    for base_tag, base_name in [("ROBUST", "ALLIN_ROBUST"), ("OFFENSIVE", "ALLIN_OFFENSIVE")]:
        base_cfg = dict(dict((n, c) for n, _, c in bundle_defs)[base_name])
        eb = bundle_evals030[base_name]["windows"]["WF_2326"]
        eh2 = bundle_evals030[base_name]["windows"]["Y2026_H2"]
        sb = bundle_sims030[base_name]

        loo_specs = [
            ("DROP_20cm_to_base76", {**base_cfg, "s20": "base_76"}),
            ("SWAP_20cm_to_base80", {**base_cfg, "s20": "base_80_wf"}),
            ("DROP_3to4_M4", {**base_cfg, "s34": "base"}),
            ("ALT_3to4_PairCold45", {**base_cfg, "s34": "m2_pair_cold45_d15"}),
            ("ALT_3to4_W2A2_BL15", {**base_cfg, "s34": "w2a2_mine_bl15"}),
            ("DROP_2to3_PairCold45", {**base_cfg, "s23": "base"}),
            ("DROP_high_ColdDrop40", {**base_cfg, "shi": "base"}),
            ("DROP_pry_upgrade", {**base_cfg, "spr": "base"}),
            ("DROP_w2a5_WeakRed", {**base_cfg, "w2a5": "none"}),
            ("ALT_w2a5_StrictHigherPrio", {**base_cfg, "w2a5": "StrictHigherPrio_0925"}),
            ("DROP_w2a6_1to2S_All", {**base_cfg, "w2a6": "s_tier_reserve_only"}),
            ("ALT_w2a6_TrigOnly_NoWait", {**base_cfg, "w2a6": "trig_1to2S_phase0_no_wait"}),
        ]
        for ltag, lcfg in loo_specs:
            sl = eng.run_bundle_sim(cache, lcfg, fee_mode="030")
            el = eng.evaluate_bundle(f"{base_tag}__{ltag}", "LOO", sl, cache, ref_dr_wf=sb["dr_wf"], perm_n=0)
            trial_daily_srs.append(float(np.mean(sl["dr_wf"]) / np.std(sl["dr_wf"], ddof=1)))
            wl = el["windows"]["WF_2326"]
            wh2 = el["windows"]["Y2026_H2"]
            # Contribution of the removed/baseline feature = AllIn minus LOO
            diffs = classify_trade_diffs(f"{base_tag}__{ltag}", sb, sl)
            n_crowded = sum(1 for d in diffs if d["window"] == "WF" and d["diff_type"] == "REMOVED_FROM_V20")
            n_added = sum(1 for d in diffs if d["window"] == "WF" and d["diff_type"] == "ADDED_VS_V20")
            loo_rows.append({
                "mode": "LOO", "parent": base_name, "action": ltag,
                "n_wf": wl["n"], "nav_wf": wl["nav"], "ex5_wf": wl["ex_top5_nav"],
                "sharpe_wf": wl["daily_sharpe"], "mdd_wf": wl["daily_mdd_pct"], "nav_26h2": wh2["nav"],
                "marginal_nav_ratio_if_included": round(eb["nav"] / max(1e-9, wl["nav"]), 4),
                "marginal_ex5_ratio_if_included": round(eb["ex_top5_nav"] / max(1e-9, wl["ex_top5_nav"]), 4),
                "marginal_sharpe_diff_if_included": round(eb["daily_sharpe"] - wl["daily_sharpe"], 4),
                "marginal_mdd_diff_pp": round(eb["daily_mdd_pct"] - wl["daily_mdd_pct"], 2),
                "marginal_26h2_ratio": round(eh2["nav"] / max(1e-9, wh2["nav"]), 4),
                "wf_trades_dropped": n_crowded, "wf_trades_added": n_added,
                "swaps_triggered_wf": len([x for x in sl["swaps"] if x["swap_date"] >= eng.WF_START]),
            })
            print(f"  LOO {base_tag:9s} | {ltag:26s} -> WF={wl['nav']:11,.2f}x (marg={eb['nav']/wl['nav']:.3f}x, dSh={eb['daily_sharpe']-wl['daily_sharpe']:+.3f}) Ex5={wl['ex_top5_nav']:8,.2f}x")

    # =========================================================================
    # Step 3B: Forward Stepwise from BASE_V20_Unified (Stack & Blend tracks)
    # =========================================================================
    print("\n[Step 3B] Forward Stepwise from BASE_V20_Unified ...")
    greedy_winners = {}
    for track_name, s20_mod, spr_mod in [("ROBUST_STACK", "stack_c50_avg", "m1_skip_cold50"), ("OFFENSIVE_BLEND", "blend_c50_half", "m2_pair_cold45_d15")]:
        cur_cfg = dict(cfg_v20)
        cur_sim = sim_b030
        cur_ev = ev_b030
        # Candidate atomic steps (exclude untrig 1to2S wait trap if separated; test both!)
        cand_steps = [
            ("add_20cm", {"s20": s20_mod}),
            ("add_3to4_M4", {"s34": "m4_4way_bl15"}),
            ("add_3to4_Pair45", {"s34": "m2_pair_cold45_d15"}),
            ("add_2to3_Pair45", {"s23": "m2_pair_cold45_d15"}),
            ("add_high_ColdDrop40", {"shi": "m1_causal_cold_drop40_t0"}),
            ("add_pry", {"spr": spr_mod}),
            ("add_w2a5_WeakRed", {"w2a5": "S_HighTier_0925"}),
            ("add_w2a6_TrigOnly", {"w2a6": "trig_1to2S_phase0_no_wait"}),
            ("add_w2a6_FullWait", {"w2a6": "s_tier_plus_1to2S"}),
        ]
        used_keys = set()
        step_idx = 0
        while True:
            step_idx += 1
            best_step = None
            best_score = -1e9
            cur_wf = cur_ev["windows"]["WF_2326"]
            for sname, patch in cand_steps:
                pkeys = set(patch.keys())
                if pkeys & used_keys:
                    continue
                ncfg = {**cur_cfg, **patch}
                nsim = eng.run_bundle_sim(cache, ncfg, fee_mode="030")
                nev = eng.evaluate_bundle(f"FWD_{track_name}_{step_idx}_{sname}", "STEPWISE", nsim, cache, ref_dr_wf=cur_sim["dr_wf"], perm_n=0)
                trial_daily_srs.append(float(np.mean(nsim["dr_wf"]) / np.std(nsim["dr_wf"], ddof=1)))
                nwf = nev["windows"]["WF_2326"]
                nh2 = nev["windows"]["Y2026_H2"]
                ch2 = cur_ev["windows"]["Y2026_H2"]
                d_sh = nwf["daily_sharpe"] - cur_wf["daily_sharpe"]
                r_nav = nwf["nav"] / max(1e-9, cur_wf["nav"])
                r_ex5 = nwf["ex_top5_nav"] / max(1e-9, cur_wf["ex_top5_nav"])
                r_h2 = nh2["nav"] / max(1e-9, ch2["nav"])
                loo_rows.append({
                    "mode": f"STEP_{step_idx}", "parent": track_name, "action": sname,
                    "n_wf": nwf["n"], "nav_wf": nwf["nav"], "ex5_wf": nwf["ex_top5_nav"],
                    "sharpe_wf": nwf["daily_sharpe"], "mdd_wf": nwf["daily_mdd_pct"], "nav_26h2": nh2["nav"],
                    "marginal_nav_ratio_if_included": round(r_nav, 4),
                    "marginal_ex5_ratio_if_included": round(r_ex5, 4),
                    "marginal_sharpe_diff_if_included": round(d_sh, 4),
                    "marginal_mdd_diff_pp": round(nwf["daily_mdd_pct"] - cur_wf["daily_mdd_pct"], 2),
                    "marginal_26h2_ratio": round(r_h2, 4),
                    "wf_trades_dropped": 0, "wf_trades_added": 0,
                    "swaps_triggered_wf": len([x for x in nsim["swaps"] if x["swap_date"] >= eng.WF_START]),
                })
                # Require genuine non-wait improvement: strict positive Sharpe & Ex5 >= 0.99 & NAV > 1.0 & 26H2 >= 0.98
                # Also ban untriggered wait-only gains if w2a6_FullWait relies solely on accidental blocking unless no better
                is_clean_acc = (d_sh > 0.002) and (r_nav > 1.01) and (r_ex5 >= 0.99) and (r_h2 >= 0.98) and (sname != "add_w2a6_FullWait")
                if is_clean_acc and d_sh > best_score:
                    best_score = d_sh
                    best_step = (sname, patch, ncfg, nsim, nev)
            if best_step is None:
                break
            sname, patch, cur_cfg, cur_sim, cur_ev = best_step
            used_keys |= set(patch.keys())
            print(f"  Stepwise {track_name} step {step_idx}: PICK {sname} -> WF={cur_ev['windows']['WF_2326']['nav']:,.2f}x Sh={cur_ev['windows']['WF_2326']['daily_sharpe']:.3f} Ex5={cur_ev['windows']['WF_2326']['ex_top5_nav']:,.2f}x")
        greedy_winners[track_name] = cur_cfg

    # Evaluate GREEDY_CLEAN (offensive greedy) and GREEDY_ROBUST (robust greedy) across all 3 fees with 1000x perm
    for gname, gkey in [("GREEDY_CLEAN", "OFFENSIVE_BLEND"), ("GREEDY_ROBUST", "ROBUST_STACK")]:
        gcfg = greedy_winners[gkey]
        s30, e30, e50, e80 = _run_tri_fee(gname, "4_GREEDY", gcfg, perm_n=1000)
        all_rows.extend(flatten_bundle_row(e30, e50, e80, gcfg))
        bundle_sims030[gname] = s30
        bundle_evals030[gname] = e30
        wf = e30["windows"]["WF_2326"]
        print(f"  [{gname}] cfg={gcfg} -> WF={wf['nav']:,.2f}x Ex5={wf['ex_top5_nav']:,.2f}x Sh={wf['daily_sharpe']:.3f} MDD={wf['daily_mdd_pct']}%")

    # =========================================================================
    # Forensics CSV & DSR summary JSON
    # =========================================================================
    forensics_rows = []
    for bcheck in ["ONLY_20CM_STACK", "ONLY_20CM_BLEND", "OTHER5_ONLY_ALLIN", "ALLIN_ROBUST", "ALLIN_OFFENSIVE", "GREEDY_CLEAN", "GREEDY_ROBUST", "STATIC_LOO_REF"]:
        forensics_rows.extend(classify_trade_diffs(bcheck, bundle_sims030[bcheck], sim_b030))
    pd.DataFrame(forensics_rows).to_csv(f"{OUT_DIR}/rd038_trade_crowding_forensics.csv", index=False)
    pd.DataFrame(all_rows).to_csv(f"{OUT_DIR}/rd038_bundles_compare.csv", index=False)
    pd.DataFrame(loo_rows).to_csv(f"{OUT_DIR}/rd038_loo_stepwise_audit.csv", index=False)

    # Portfolio-level Multi-Trial DSR across V20 Baseline vs Only20cm vs AllIn vs Greedy
    n_rd038 = len(trial_daily_srs)
    var_local = float(np.var(trial_daily_srs, ddof=1)) if n_rd038 > 1 else eng.DSR_VAR_POOLED
    var_null = 1.0 / max(1, len(ref_dr_wf) - 1)
    n_cum = eng.DSR_N_CUM_PRIOR + n_rd038

    dsr_summary = {
        "n_trials_rd038": n_rd038,
        "n_trials_cum_with_rd035_rd036": n_cum,
        "var_sr_daily_rd038_local": round(var_local, 6),
        "var_sr_daily_pooled_prior": eng.DSR_VAR_POOLED,
        "var_sr_daily_null_1_over_T": round(var_null, 6),
        "bundles": {},
    }
    print("\n[Portfolio DSR Comparison vs BASE_V20_Unified]")
    for bkey in ["BASE_V20_Unified", "BASE_V20_S80_Thresh", "ONLY_20CM_STACK", "ONLY_20CM_BLEND", "OTHER5_ONLY_ALLIN", "ALLIN_ROBUST", "ALLIN_OFFENSIVE", "GREEDY_CLEAN", "GREEDY_ROBUST", "STATIC_LOO_REF"]:
        dr_wf = bundle_sims030[bkey]["dr_wf"]
        d_loc = cm.calc_dsr(dr_wf, n_rd038, var_local)
        d_cum_loc = cm.calc_dsr(dr_wf, n_cum, var_local)
        d_cum_pool = cm.calc_dsr(dr_wf, n_cum, eng.DSR_VAR_POOLED)
        d_cum_null = cm.calc_dsr(dr_wf, n_cum, var_null)
        dsr_summary["bundles"][bkey] = {
            "wf_sr_ann": d_loc["sr_ann"],
            "single_round_N_local_var": d_loc,
            "cum_N_local_var": d_cum_loc,
            "cum_N_pooled_var": d_cum_pool,
            "cum_N_null_var": d_cum_null,
        }
        print(f"  {bkey:22s} | SR={d_loc['sr_ann']:.3f} | DSR(single N={n_rd038})={d_loc['dsr']:.4f} | DSR(cum N={n_cum}, pool)={d_cum_pool['dsr']:.4f} | DSR(cum null)={d_cum_null['dsr']:.4f}")

    out_meta = {
        "greedy_configs": greedy_winners,
        "dsr_summary": dsr_summary,
        "swaps_detail": {k: bundle_sims030[k]["swaps"] for k in ["ALLIN_ROBUST", "ALLIN_OFFENSIVE", "GREEDY_CLEAN", "GREEDY_ROBUST"]},
        "evals_030": {k: {wk: wv for wk, wv in v.items()} for k, v in bundle_evals030.items()},
    }
    with open(f"{OUT_DIR}/_cache/rd038_step2_summary.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(out_meta), f, indent=2, ensure_ascii=False)

    print(f"\n[STEP 2+3 DONE in {time.time()-t0:.1f}s | RSS={rss_mb()} MB] N_rd038={n_rd038}, N_cum={n_cum}")


if __name__ == "__main__":
    main()

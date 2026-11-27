#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step1_collision_panorama_and_pairwise.py — V22.0 Pillar 5 Tasks 1 & 2:
  1. Full-history (1,212 trading days) 7-strategy collision panorama on Pure_V21_P2_SJ114_E4:
     - Same-day collision days & pairs (trig-only and trig+untrig)
     - 3-type exact breakdown: (1) 09:25 direct vs 09:25 direct, (2) Tier-1 S-cond reservation & Pos5 wait-blocking,
       (3) Cross-day T+1 holding shadowing (raw 7x7 shadow matrix + realized simulation occlusion)
     - Exports `p5_collision_days_detail.csv`
  2. 7x7 Pairwise Same-Day Collision Win-Rate & Excess Return Matrix (FULL_5Y / IS_2123 / OOS_2426),
     plus sub-tier splits and unfiltered pass_top1 cross-check.
     - Exports `p5_pairwise_7x7.csv` and `_step1_panorama_pairwise.json`.
Zero yfinance (D12). Read-only on V20/V21/RD038/RD049/P2/P3.
"""
import json
import math
import os
import sys
import time
from itertools import combinations

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

P5 = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/v22_grand_convergence_20261126/p5_v22_collision_priority_audit"
if P5 not in sys.path:
    sys.path.insert(0, P5)

import _p5_engine as p5


def _dedup_daily_top1(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the top-ranked signal per (buy_date, strategy), distinguishing trig vs untrig (trig wins if any)."""
    srt = df.sort_values(
        ["buy_date", "strategy", "is_untrig", "s2c_prio", "score", "buy_hhmm", "code"],
        ascending=[True, True, True, True, False, True, True],
        kind="mergesort",
    )
    return srt.groupby(["buy_date", "strategy"], as_index=False).first()


def analyze_panorama(mp: pd.DataFrame, cal_5y: list[str], label: str) -> tuple[dict, pd.DataFrame]:
    """Full 5-year / IS / OOS collision anatomy + per-day collision detail DataFrame."""
    cal_set = set(cal_5y)
    sub = mp[mp["buy_date"].isin(cal_set)].copy()
    dedup = _dedup_daily_top1(sub)
    trig = dedup[~dedup["is_untrig"]].copy()

    # Run baseline simulation to record realized winners & wait blocks & cross-day shadows
    rfn_base = p5.make_engine_s2c_rank_fn({"4to5_S120": 900, "4to5_114_119": 900})
    sim_base = p5.run_priority_sim(mp, rfn_base, cal_5y)
    tr_base = sim_base["trades_df"]
    wait_map = {w["buy_date"]: w for w in sim_base["waits"]}
    win_map = {r.buy_date: r for r in tr_base.itertuples(index=False)}

    # Also compute exact open-holding status on every trading day in Base sim
    held_on_dt = {}
    for r in tr_base.itertuples(index=False):
        for dt in cal_5y:
            if r.buy_date < dt < r.exit_date:
                held_on_dt[dt] = (r.strategy, r.code, r.name, r.buy_date, r.exit_date, r.exit_hhmm, "FULL_DAY_HELD")
            elif dt == r.exit_date:
                held_on_dt[dt] = (r.strategy, r.code, r.name, r.buy_date, r.exit_date, r.exit_hhmm, f"EXIT_AT_{r.exit_hhmm}")

    def _window_stats(sdt: str, edt: str, win_lbl: str) -> dict:
        w_cal = [d for d in cal_5y if sdt <= d <= edt]
        d_all = dedup[dedup["buy_date"].between(sdt, edt)]
        d_tr = trig[trig["buy_date"].between(sdt, edt)]

        grp_all = d_all.groupby("buy_date")
        grp_tr = d_tr.groupby("buy_date")

        mult_all = grp_all.size().value_counts().sort_index().to_dict()
        mult_tr = grp_tr.size().value_counts().sort_index().to_dict()

        col_days_tr = [dt for dt, g in grp_tr if len(g) >= 2]
        col_pairs_tr = sum(len(g) * (len(g) - 1) // 2 for _, g in grp_tr if len(g) >= 2)
        col_days_all = [dt for dt, g in grp_all if len(g) >= 2]
        col_pairs_all = sum(len(g) * (len(g) - 1) // 2 for _, g in grp_all if len(g) >= 2)

        # Type 1: >=2 confirmed 09:25 direct buys on the same day
        t1_days, t1_pairs = [], 0
        for dt, g in grp_tr:
            g925 = g[g["buy_hhmm"] == 925]
            if len(g925) >= 2:
                t1_days.append(dt)
                t1_pairs += len(g925) * (len(g925) - 1) // 2

        # Type 2: S-tier intraday conditional (3to4_S>=102 or high_S>=96 with hhmm>925 or untrig) colliding with 09:25 direct buys
        # Plus Subtype 2b: Tier-3 intraday/wait colliding with 4to5@0925 under Pos5
        t2_s_vs_925_days = []
        t2_s_trig_vs_925 = []
        t2_s_untrig_vs_925 = []
        t2_any_cond_vs_4to5 = []
        t2_all_days = set()
        for dt, g in grp_all:
            g925 = g[(~g["is_untrig"]) & (g["buy_hhmm"] == 925)]
            if g925.empty:
                continue
            s_cond = g[g["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]) & ((g["buy_hhmm"] > 925) | g["is_untrig"])]
            if not s_cond.empty:
                # Note: check if g925 has strategies other than s_cond's strategy
                s_strats = set(s_cond["strategy"])
                other_925 = g925[~g925["strategy"].isin(s_strats)]
                if not other_925.empty:
                    t2_s_vs_925_days.append(dt)
                    t2_all_days.add(dt)
                    if (~s_cond["is_untrig"]).any():
                        t2_s_trig_vs_925.append(dt)
                    else:
                        t2_s_untrig_vs_925.append(dt)
            g45 = g925[g925["strategy"] == "4to5"]
            g_cond_base = g[(g["strategy"] != "4to5") & ((g["buy_hhmm"] > 925) | g["is_untrig"])]
            if (not g45.empty) and (not g_cond_base.empty):
                t2_any_cond_vs_4to5.append(dt)
                t2_all_days.add(dt)

        # Type 3: Cross-day T+1 holding shadowing (strictly B.buy_date > A.buy_date and (B.buy_date, B.buy_hhmm) <= (A.exit_date, A.exit_hhmm))
        shadow_mat = {s1: {s2: 0 for s2 in p5.ALL7} for s1 in p5.ALL7}
        by_st = {s: d_tr[d_tr["strategy"] == s] for s in p5.ALL7}
        cross_day_shadowed_signals = set()
        for s1 in p5.ALL7:
            for s2 in p5.ALL7:
                if s1 == s2:
                    continue
                cnt = 0
                for r1 in by_st[s1].itertuples(index=False):
                    for r2 in by_st[s2].itertuples(index=False):
                        if r2.buy_date > r1.buy_date and (r2.buy_date, int(r2.buy_hhmm)) <= (r1.exit_date, int(r1.exit_hhmm)):
                            cnt += 1
                            cross_day_shadowed_signals.add((r2.buy_date, r2.strategy))
                shadow_mat[s1][s2] = cnt

        # Realized simulation breakdown of all triggered signals in window
        real_win = 0
        real_lost_sameday = 0
        real_lost_crossday = 0
        real_by_strat = {s: {"total_trig": 0, "realized": 0, "lost_sameday": 0, "lost_crossday": 0} for s in p5.ALL7}
        for r in d_tr.itertuples(index=False):
            st = r.strategy
            real_by_strat[st]["total_trig"] += 1
            wm = win_map.get(r.buy_date)
            if wm is not None and wm.strategy == st and wm.code == r.code:
                real_win += 1
                real_by_strat[st]["realized"] += 1
            else:
                h_info = held_on_dt.get(r.buy_date)
                is_held_block = False
                if h_info is not None:
                    if h_info[6] == "FULL_DAY_HELD" or (int(r.buy_hhmm) <= int(h_info[5])):
                        is_held_block = True
                if is_held_block:
                    real_lost_crossday += 1
                    real_by_strat[st]["lost_crossday"] += 1
                else:
                    real_lost_sameday += 1
                    real_by_strat[st]["lost_sameday"] += 1

        # Multi-way >=3 combos (triggered)
        multi3_tr = {}
        for dt, g in grp_tr:
            if len(g) >= 3:
                k = "+".join(sorted(g["strategy"].tolist()))
                multi3_tr[k] = multi3_tr.get(k, 0) + 1

        return {
            "window": win_lbl,
            "n_trading_days": len(w_cal),
            "n_trig_strat_days": int(len(d_tr)),
            "n_all_incl_ut_strat_days": int(len(d_all)),
            "unique_trig_days": int(len(grp_tr)),
            "unique_all_days": int(len(grp_all)),
            "multiplicity_trig": {str(k): int(v) for k, v in mult_tr.items()},
            "multiplicity_all": {str(k): int(v) for k, v in mult_all.items()},
            "collision_days_trig_ge2": int(len(col_days_tr)),
            "collision_pairs_trig": int(col_pairs_tr),
            "collision_days_all_ge2": int(len(col_days_all)),
            "collision_pairs_all": int(col_pairs_all),
            "multi_way_ge3_trig": multi3_tr,
            "type1_0925_hard_collision_days": int(len(t1_days)),
            "type1_0925_hard_collision_pairs": int(t1_pairs),
            "type2_stier_cond_vs_0925_days": int(len(t2_s_vs_925_days)),
            "type2_stier_cond_trig_days": int(len(t2_s_trig_vs_925)),
            "type2_stier_cond_untrig_days": int(len(t2_s_untrig_vs_925)),
            "type2_intraday_cond_vs_4to5_days": int(len(t2_any_cond_vs_4to5)),
            "type2_total_unique_days": int(len(t2_all_days)),
            "type3_raw_cross_day_shadow_pairs_sum": int(sum(sum(v.values()) for v in shadow_mat.values())),
            "type3_raw_cross_day_shadow_matrix": shadow_mat,
            "type3_raw_cross_day_shadowed_unique_signals": int(len(cross_day_shadowed_signals)),
            "realized_base_accounting": {
                "total_trig": int(len(d_tr)),
                "realized": int(real_win),
                "lost_sameday_collision_or_wait": int(real_lost_sameday),
                "lost_crossday_held_shadow": int(real_lost_crossday),
                "by_strategy": real_by_strat,
            },
        }

    summary = {
        "pool_label": label,
        "FULL_5Y": _window_stats("2021-11-16", "2026-11-16", "FULL_5Y"),
        "IS_2123": _window_stats("2021-11-16", "2023-12-31", "IS_2123"),
        "OOS_2426": _window_stats("2024-01-01", "2026-11-16", "OOS_2426"),
        "counts_by_strategy_full": dedup.groupby(["strategy", "is_untrig"]).size().unstack(fill_value=0).to_dict(),
    }

    # Build comprehensive per-day collision detail CSV (every day with >=2 signals in dedup OR wait collision)
    detail_rows = []
    for dt, g in dedup.groupby("buy_date", sort=True):
        if len(g) < 2 and dt not in wait_map:
            continue
        g_tr = g[~g["is_untrig"]]
        g925 = g_tr[g_tr["buy_hhmm"] == 925]
        s_cond = g[g["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]) & ((g["buy_hhmm"] > 925) | g["is_untrig"])]
        has_t1 = len(g925) >= 2
        has_t2_s = (not g925.empty) and (not s_cond.empty) and (not g925[~g925["strategy"].isin(set(s_cond["strategy"]))].empty)
        has_t2_45 = (not g925[g925["strategy"] == "4to5"].empty) and (not g[(g["strategy"] != "4to5") & ((g["buy_hhmm"] > 925) | g["is_untrig"])].empty)

        h_info = held_on_dt.get(dt)
        held_str = f"{h_info[0]}({h_info[1]}{h_info[2]},exit={h_info[4]} {h_info[5]})" if h_info else ""
        wm = win_map.get(dt)
        wt = wait_map.get(dt)
        if wm is not None:
            base_action = f"BUY {wm.strategy}:{wm.code}{wm.name}({wm.bucket},{wm.net_ret*100:+.2f}%)"
        elif wt is not None:
            base_action = f"WAIT_UNTRIG {wt['strategy']}:{wt['code']}{wt['name']}({wt['bucket']},cancel={wt['cancel_hhmm']})"
        elif h_info is not None:
            base_action = f"BLOCKED_BY_HELD {held_str}"
        else:
            base_action = "EMPTY"

        cands_desc = " | ".join(
            f"{r.strategy}[{'UT' if r.is_untrig else r.buy_hhmm},{r.bucket},sc={r.score:.1f}] {r.code}{r.name}({'UT0.00%' if r.is_untrig else f'{r.net_ret*100:+.2f}%'})"
            for r in g.sort_values(["s2c_prio", "score"], ascending=[True, False]).itertuples(index=False)
        )
        ctype = []
        if has_t1:
            ctype.append("T1_0925硬撞车")
        if has_t2_s:
            ctype.append("T2_S档条件占位")
        if has_t2_45:
            ctype.append("T2_盘中阻断四进五")
        if len(g) >= 2 and not ctype:
            ctype.append("T1B_0925与盘中同日(0925先买)")
        if h_info is not None:
            ctype.append("T3_受前持仓跨日遮蔽")

        detail_rows.append({
            "buy_date": dt,
            "period": "IS_2123" if dt <= "2023-12-31" else "OOS_2426",
            "n_all_signals": int(len(g)),
            "n_trig_signals": int(len(g_tr)),
            "n_0925_signals": int(len(g925)),
            "collision_types": "+".join(ctype) if ctype else "WAIT_ONLY",
            "strategies_present": "+".join(g.sort_values("strategy")["strategy"].tolist()),
            "base_v22_action": base_action,
            "held_shadow_context": held_str,
            "candidates_detail": cands_desc,
        })

    return summary, pd.DataFrame(detail_rows)


def compute_pairwise_7x7(mp: pd.DataFrame, cal_5y: list[str]) -> tuple[pd.DataFrame, dict]:
    """Compute 7x7 pairwise same-day collision win rate and excess spread (FULL_5Y, IS_2123, OOS_2426)."""
    cal_set = set(cal_5y)
    trig = _dedup_daily_top1(mp[mp["buy_date"].isin(cal_set) & (~mp["is_untrig"])])
    by_st = {st: trig[trig["strategy"] == st].set_index("buy_date") for st in p5.ALL7}

    rows = []
    matrix_json = {}
    windows = [
        ("FULL_5Y", "2021-11-16", "2026-11-16"),
        ("IS_2123", "2021-11-16", "2023-12-31"),
        ("OOS_2426", "2024-01-01", "2026-11-16"),
    ]
    for wn, sdt, edt in windows:
        matrix_json[wn] = {}
        for s_a in p5.ALL7:
            matrix_json[wn][s_a] = {}
            da = by_st[s_a]
            da_w = da[(da.index >= sdt) & (da.index <= edt)]
            for s_b in p5.ALL7:
                if s_a == s_b:
                    continue
                db = by_st[s_b]
                db_w = db[(db.index >= sdt) & (db.index <= edt)]
                common = sorted(set(da_w.index) & set(db_w.index))
                n_col = len(common)
                if n_col == 0:
                    rec = {
                        "window": wn, "strat_a": s_a, "strat_b": s_b, "n_col": 0,
                        "a_wr_pct": None, "a_mean_pct": None, "a_med_pct": None,
                        "b_wr_pct": None, "b_mean_pct": None, "b_med_pct": None,
                        "spread_a_minus_b_pp": None, "wr_diff_pp": None,
                        "pct_days_a_gt_b": None, "paired_t": None,
                    }
                else:
                    ra = da_w.loc[common, "net_ret"].to_numpy(float)
                    rb = db_w.loc[common, "net_ret"].to_numpy(float)
                    diff = ra - rb
                    sd = float(np.std(diff, ddof=1)) if n_col > 1 else 0.0
                    t_st = float(np.mean(diff) / (sd / math.sqrt(n_col))) if sd > 1e-12 else 0.0
                    a_wr = float((ra > 0).mean() * 100.0)
                    b_wr = float((rb > 0).mean() * 100.0)
                    rec = {
                        "window": wn, "strat_a": s_a, "strat_b": s_b, "n_col": int(n_col),
                        "a_wr_pct": round(a_wr, 2),
                        "a_mean_pct": round(float(ra.mean() * 100.0), 2),
                        "a_med_pct": round(float(np.median(ra) * 100.0), 2),
                        "b_wr_pct": round(b_wr, 2),
                        "b_mean_pct": round(float(rb.mean() * 100.0), 2),
                        "b_med_pct": round(float(np.median(rb) * 100.0), 2),
                        "spread_a_minus_b_pp": round(float(diff.mean() * 100.0), 2),
                        "wr_diff_pp": round(a_wr - b_wr, 2),
                        "pct_days_a_gt_b": round(float((ra > rb).mean() * 100.0), 2),
                        "paired_t": round(t_st, 3) if n_col >= 2 else None,
                    }
                rows.append(rec)
                matrix_json[wn][s_a][s_b] = rec

    # Also compute fine-bucket pairwise stats for key splits (4to5_S120 vs others, 20cm_S86 vs 1to2, 2to3_S vs others)
    fine_pairs = []
    fine_defs = [
        ("4to5_S120", trig[(trig["strategy"] == "4to5") & (trig["score"] >= 120.0)]),
        ("4to5_114_119", trig[(trig["strategy"] == "4to5") & (trig["score"] < 120.0)]),
        ("20cm_S86", trig[(trig["strategy"] == "20cm") & (trig["score"] >= 86.0)]),
        ("20cm_80_85", trig[(trig["strategy"] == "20cm") & (trig["score"] < 86.0)]),
        ("2to3_S", trig[(trig["strategy"] == "2to3") & (trig["score"] >= 96.0)]),
        ("2to3_A", trig[(trig["strategy"] == "2to3") & (trig["score"] < 96.0)]),
        ("3to4_925", trig[(trig["strategy"] == "3to4") & (trig["buy_hhmm"] == 925)]),
        ("3to4_cond", trig[(trig["strategy"] == "3to4") & (trig["buy_hhmm"] > 925)]),
        ("high_925", trig[(trig["strategy"] == "high") & (trig["buy_hhmm"] == 925)]),
        ("high_cond", trig[(trig["strategy"] == "high") & (trig["buy_hhmm"] > 925)]),
        ("1to2_925", trig[(trig["strategy"] == "1to2") & (trig["buy_hhmm"] == 925)]),
        ("1to2_cond", trig[(trig["strategy"] == "1to2") & (trig["buy_hhmm"] > 925)]),
    ]
    fine_map = {nm: df.set_index("buy_date") for nm, df in fine_defs}
    for wn, sdt, edt in windows:
        for nm_a, da in fine_map.items():
            da_w = da[(da.index >= sdt) & (da.index <= edt)]
            for s_b in p5.ALL7:
                if nm_a.startswith(s_b):
                    continue
                db = by_st[s_b]
                db_w = db[(db.index >= sdt) & (db.index <= edt)]
                common = sorted(set(da_w.index) & set(db_w.index))
                if not common:
                    continue
                ra = da_w.loc[common, "net_ret"].to_numpy(float)
                rb = db_w.loc[common, "net_ret"].to_numpy(float)
                fine_pairs.append({
                    "window": wn, "sub_a": nm_a, "strat_b": s_b, "n_col": len(common),
                    "a_wr_pct": round(float((ra > 0).mean() * 100.0), 2),
                    "a_mean_pct": round(float(ra.mean() * 100.0), 2),
                    "b_wr_pct": round(float((rb > 0).mean() * 100.0), 2),
                    "b_mean_pct": round(float(rb.mean() * 100.0), 2),
                    "spread_a_minus_b_pp": round(float((ra - rb).mean() * 100.0), 2),
                })

    return pd.DataFrame(rows), {"matrix": matrix_json, "fine_subtier_collisions": fine_pairs}


def main():
    t0 = time.time()
    print("[P5 Step 1] Loading Pure_V21_P2_SJ114_E4 assets...", flush=True)
    assets = p5.load_p5_raw_assets()
    cal_5y = assets["c_p2"]["cal_5y"]

    mp_primary = p5.build_p5_master_pool(assets["c_p2"], assets["raw_4to5"], fee_mode="030", use_pass_top1=False)
    mp_pass1 = p5.build_p5_master_pool(assets["c_p2"], assets["raw_4to5"], fee_mode="030", use_pass_top1=True)

    pan_prim, df_detail = analyze_panorama(mp_primary, cal_5y, "Primary_PureV22_Pool6_Plus_4to5")
    pan_pass1, _ = analyze_panorama(mp_pass1, cal_5y, "CrossCheck_PassTop1_Plus_4to5")

    df_pair_prim, pair_pkg_prim = compute_pairwise_7x7(mp_primary, cal_5y)
    df_pair_pass1, pair_pkg_pass1 = compute_pairwise_7x7(mp_pass1, cal_5y)

    # Combine primary + crosscheck into p5_pairwise_7x7.csv with scope tag
    df_pair_prim["pool_scope"] = "Primary_PureV22"
    df_pair_pass1["pool_scope"] = "CrossCheck_PassTop1"
    df_pair_all = pd.concat([df_pair_prim, df_pair_pass1], ignore_index=True)

    df_detail.to_csv(f"{P5}/p5_collision_days_detail.csv", index=False, encoding="utf-8-sig")
    df_pair_all.to_csv(f"{P5}/p5_pairwise_7x7.csv", index=False, encoding="utf-8-sig")

    pkg = p5.v22.sanitize_json({
        "elapsed_sec": round(time.time() - t0, 2),
        "panorama_primary": pan_prim,
        "panorama_crosscheck_passtop1": pan_pass1,
        "pairwise_7x7_primary": pair_pkg_prim,
        "pairwise_7x7_crosscheck_passtop1": pair_pkg_pass1,
    })
    with open(f"{P5}/_step1_panorama_pairwise.json", "w", encoding="utf-8") as f:
        json.dump(pkg, f, ensure_ascii=False, indent=2)

    print(f"[P5 Step 1 DONE in {time.time()-t0:.2f}s] collision_days_detail={len(df_detail)} rows, pairwise_7x7={len(df_pair_all)} rows")
    f5 = pan_prim["FULL_5Y"]
    print("  FULL_5Y Primary: days=", f5["n_trading_days"], "trig_strat_days=", f5["n_trig_strat_days"], "incl_ut=", f5["n_all_incl_ut_strat_days"])
    print("    Col days (trig>=2):", f5["collision_days_trig_ge2"], "pairs:", f5["collision_pairs_trig"], "| Col days (incl ut):", f5["collision_days_all_ge2"], "pairs:", f5["collision_pairs_all"])
    print("    Type1 (0925 vs 0925):", f5["type1_0925_hard_collision_days"], "days,", f5["type1_0925_hard_collision_pairs"], "pairs")
    print("    Type2 (S-cond vs 0925):", f5["type2_stier_cond_vs_0925_days"], "days (trig=", f5["type2_stier_cond_trig_days"], ", ut=", f5["type2_stier_cond_untrig_days"], "), cond vs 4to5=", f5["type2_intraday_cond_vs_4to5_days"])
    print("    Type3 (cross-day raw shadow pairs):", f5["type3_raw_cross_day_shadow_pairs_sum"], "| realized_acct:", f5["realized_base_accounting"]["realized"], "realized /", f5["realized_base_accounting"]["lost_sameday_collision_or_wait"], "sameday_lost /", f5["realized_base_accounting"]["lost_crossday_held_shadow"], "crossday_shadowed")


if __name__ == "__main__":
    main()

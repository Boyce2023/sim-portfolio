#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD030 Wave 2B Master Runner:
  Task 1: 100% exact reproduction of 6 standalone baselines + V20.0 combined (278 trades, 69,134,091x).
  Task 2: Systematic IS-first (2021-01-04~2024-12-31) grid of 29 clean physical Old-Hot rules x 4 weights
          across all 6 strategies (including edge-pool promotions & kicks), then blind OOS (2025-01-01~2026-11-25)
          & 2026 validation with exact trade diffs.
  Task 3: Plug top IS single-strategy & multi-strategy combos into V20.0 P3_S2C_STierReserveOnly,
          run full institutional jianyan (BH-FDR, HLZ/DSR, 5-fold Purged CV, CSCV PBO, +-20% perturbation,
          10k paired block bootstrap, static matched-exposure & 1/vol ablations, 2025-01-01 truncation, 7 pillars).
Zero yfinance (D12). Zero cap10m. Read-only on production files.
"""
import json
import math
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)

WORK_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
if WORK_DIR not in sys.path:
    sys.path.insert(0, WORK_DIR)

import step4_mod_rules_and_sim as m1
import step4_mod_jianyan as m2

ROOT = m1.ROOT
SIM = m1.SIM


def build_strat_windows(st: str) -> list[tuple[str, str, str]]:
    start = "2021-01-04" if st == "20cm" else "2021-11-16"
    return [
        ("FULL", start, "2026-11-25"),
        ("IS", start, "2024-12-31"),
        ("OOS", "2025-01-01", "2026-11-25"),
        ("Y2026", "2026-01-01", "2026-11-25"),
    ]


def eval_single_strategy_grid(
    st: str,
    pools: dict[str, pd.DataFrame],
    cal_full: list[str],
    sh300: dict,
    all_sh_dts: list[str],
) -> tuple[dict, list[dict]]:
    df = pools[st]
    T_full = len(cal_full)
    dt_idx_full = {d: i for i, d in enumerate(cal_full)}
    wins = build_strat_windows(st)
    cm20_thr = 82.0

    # CSI daily returns aligned to strategy FULL window
    st_start = wins[0][1]
    st_idx = [i for i, d in enumerate(cal_full) if d >= st_start]
    csi_vec = np.array([
        sh300[cal_full[i]] / sh300[all_sh_dts[all_sh_dts.index(cal_full[i]) - 1]] - 1.0
        for i in st_idx
    ], dtype=float)

    def _run_one(rule_id: str, w: float):
        delta = np.zeros(len(df), dtype=float) if rule_id == "BASELINE" else m1.compute_rule_delta(df, rule_id, w)
        pass_df, slot_df = m1.sim_standalone(st, df, delta, high_cb_mode="v51_exact", cm20_thr=cm20_thr)
        dr_full, nd = m1.daily_mtm_from_segs(slot_df, T_full, "mtm_full")
        assert nd < 1e-3, f"{st} {rule_id} MTM diff={nd}"
        wm = {
            wlbl: m2.calc_window_metrics_ext(slot_df, pass_df, dr_full, cal_full, dt_idx_full, sh300, all_sh_dts, sdt, edt)
            for wlbl, sdt, edt in wins
        }
        return slot_df, pass_df, dr_full, wm

    base_slot, base_pass, base_dr, base_wm = _run_one("BASELINE", 0.0)
    base_is = base_wm["IS"]
    base_keys_is = set(zip(base_slot[base_slot["buy_date"] <= "2024-12-31"]["buy_date"], base_slot[base_slot["buy_date"] <= "2024-12-31"]["code"]))
    base_keys_full = set(zip(base_slot["buy_date"], base_slot["code"]))

    variants = []
    dr_family = {"BASELINE": base_dr[st_idx]}
    p_vs_csi_list, p_vs_base_list = [], []

    for rule_id, rtype, desc, formula in m1.RULE_SPECS:
        for w in m1.WEIGHT_GRIDS[st]:
            vid = f"{rule_id}_w{w}"
            slot_df, pass_df, dr_full, wm = _run_one(rule_id, float(w))
            dr_sub = dr_full[st_idx]

            # Trade swap stats (IS & FULL)
            is_slot = slot_df[slot_df["buy_date"] <= "2024-12-31"]
            is_keys = set(zip(is_slot["buy_date"], is_slot["code"]))
            full_keys = set(zip(slot_df["buy_date"], slot_df["code"]))
            is_kicked = base_keys_is - is_keys
            is_added = is_keys - base_keys_is
            full_kicked = base_keys_full - full_keys
            full_added = full_keys - base_keys_full

            base_is_df = base_slot[base_slot["buy_date"] <= "2024-12-31"]
            k_rets_full = base_slot[base_slot.apply(lambda r: (r["buy_date"], r["code"]) in full_kicked, axis=1)]["net_ret"].to_numpy(float) if full_kicked else np.array([])
            a_rets_full = slot_df[slot_df.apply(lambda r: (r["buy_date"], r["code"]) in full_added, axis=1)]["net_ret"].to_numpy(float) if full_added else np.array([])
            k_rets_is = base_is_df[base_is_df.apply(lambda r: (r["buy_date"], r["code"]) in is_kicked, axis=1)]["net_ret"].to_numpy(float) if is_kicked else np.array([])
            a_rets_is = is_slot[is_slot.apply(lambda r: (r["buy_date"], r["code"]) in is_added, axis=1)]["net_ret"].to_numpy(float) if is_added else np.array([])

            # Paired t-test vs baseline & vs CSI300
            ex_csi = dr_sub - csi_vec
            _, p_csi = stats.ttest_1samp(ex_csi, 0.0, alternative="greater") if np.std(ex_csi) > 1e-12 else (0.0, 1.0)
            diff_b = dr_sub - base_dr[st_idx]
            _, p_base = stats.ttest_1samp(diff_b, 0.0, alternative="greater") if np.std(diff_b) > 1e-12 else (0.0, 1.0)
            p_vs_csi_list.append(float(p_csi))
            p_vs_base_list.append(float(p_base))

            # Keep unique daily streams for CSCV PBO
            if not any(np.allclose(dr_sub, v) for v in dr_family.values()):
                dr_family[vid] = dr_sub

            # Strict IS improvement flag (ZERO OOS info used!)
            m_is = wm["IS"]
            is_changed = len(is_kicked) + len(is_added)
            is_suff = m_is["n"] >= max(6, int(round(0.75 * base_is["n"])))
            is_beat = (
                is_changed > 0
                and is_suff
                and m_is["daily_sharpe"] > base_is["daily_sharpe"] + 1e-6
                and m_is["ex_top3_nav"] > base_is["ex_top3_nav"] * 1.0001
                and m_is["nav"] > base_is["nav"] * 1.0001
                and m_is["daily_calmar"] >= base_is["daily_calmar"] * 0.98
            )
            # Composite IS rank score (normalized Sharpe + log Ex3 NAV gain)
            is_rank_score = (
                (m_is["daily_sharpe"] - base_is["daily_sharpe"]) * 2.0
                + math.log(max(1e-9, m_is["ex_top3_nav"]) / max(1e-9, base_is["ex_top3_nav"]))
                + 0.5 * math.log(max(1e-9, m_is["nav"]) / max(1e-9, base_is["nav"]))
            ) if (is_changed > 0 and is_suff) else -999.0

            hlz_t, dsr150 = m2.mc.hlz_and_dsr150(slot_df.to_dict("records"), sh300, all_sh_dts, m_trials=150)
            variants.append({
                "variant_id": vid, "rule_id": rule_id, "rule_type": rtype, "desc": desc, "w": int(w),
                "windows": wm,
                "is_changed_trades": int(is_changed), "is_kicked": int(len(is_kicked)), "is_added": int(len(is_added)),
                "is_kicked_mean_pct": round(float(k_rets_is.mean() * 100.0), 2) if len(k_rets_is) else None,
                "is_added_mean_pct": round(float(a_rets_is.mean() * 100.0), 2) if len(a_rets_is) else None,
                "full_kicked": int(len(full_kicked)), "full_added": int(len(full_added)),
                "full_kicked_mean_pct": round(float(k_rets_full.mean() * 100.0), 2) if len(k_rets_full) else None,
                "full_added_mean_pct": round(float(a_rets_full.mean() * 100.0), 2) if len(a_rets_full) else None,
                "strict_is_improver": bool(is_beat),
                "is_rank_score": round(float(is_rank_score), 5),
                "hlz_t": hlz_t, "dsr_m150": dsr150,
                "p_vs_csi_raw": round(float(p_csi), 6),
                "p_vs_base_raw": round(float(p_base), 6),
            })

    q_csi = m2.bh_fdr(p_vs_csi_list)
    q_base = m2.bh_fdr(p_vs_base_list)
    for idx_v, v in enumerate(variants):
        v["bh_fdr_vs_csi_q"] = q_csi[idx_v]
        v["bh_fdr_vs_base_q"] = q_base[idx_v]

    # Strict IS-only locking BEFORE viewing OOS!
    strict_cands = [v for v in variants if v["strict_is_improver"]]
    if strict_cands:
        strict_sorted = sorted(strict_cands, key=lambda x: -x["is_rank_score"])
        top_is_list = strict_sorted[:3]
        top_is = strict_sorted[0]
    else:
        changed_cands = [v for v in variants if v["is_changed_trades"] > 0 and v["windows"]["IS"]["n"] >= max(6, int(round(0.75 * base_is["n"])))]
        top_is_list = sorted(changed_cands, key=lambda x: -x["is_rank_score"])[:3]
        top_is = top_is_list[0] if top_is_list else None

    # CSCV PBO on top diverse IS variants + baseline (cap at 24 unique streams for exact combinatorics)
    cscv_keys = ["BASELINE"]
    for v in sorted(variants, key=lambda x: -x["is_rank_score"]):
        if v["variant_id"] in dr_family and v["variant_id"] not in cscv_keys:
            cscv_keys.append(v["variant_id"])
        if len(cscv_keys) >= 24:
            break
    cscv_res = m2.cscv_pbo_family({k: dr_family[k] for k in cscv_keys}, "BASELINE", S_list=(8, 10)) if len(cscv_keys) >= 2 else {}

    # Blind OOS verdict on locked top_is
    trade_diffs = []
    if top_is is not None:
        cand_slot, _, _, _ = _run_one(top_is["rule_id"], float(top_is["w"]))
        trade_diffs = m1.extract_trade_diffs(base_slot, cand_slot, st, top_is["variant_id"])
        m_oos, b_oos = top_is["windows"]["OOS"], base_wm["OOS"]
        m_y26, b_y26 = top_is["windows"]["Y2026"], base_wm["Y2026"]
        oos_pass = (
            top_is["strict_is_improver"]
            and m_oos["nav"] > b_oos["nav"]
            and m_oos["ex_top3_nav"] >= b_oos["ex_top3_nav"] * 0.99
            and m_oos["daily_sharpe"] >= b_oos["daily_sharpe"] - 0.05
            and m_y26["nav"] >= b_y26["nav"] * 0.95
        )
        verdict = "CANDIDATE_PASS_IS_AND_OOS" if oos_pass else "KEEP_V20_UNCHANGED"
    else:
        oos_pass = False
        verdict = "KEEP_V20_UNCHANGED"

    base_hlz, base_dsr = m2.mc.hlz_and_dsr150(base_slot.to_dict("records"), sh300, all_sh_dts, m_trials=150)
    return {
        "strategy": st,
        "total_variants_tested": len(variants),
        "unique_daily_streams": len(dr_family),
        "strict_is_improver_count": len(strict_cands),
        "baseline": {"windows": base_wm, "hlz_t": base_hlz, "dsr_m150": base_dsr},
        "top_is_locked": top_is,
        "top3_is_locked": top_is_list,
        "cscv_pbo_top24": cscv_res,
        "single_strategy_verdict": verdict,
        "all_variants_summary": [
            {
                "variant_id": v["variant_id"], "rule_id": v["rule_id"], "w": v["w"],
                "is_n": v["windows"]["IS"]["n"], "is_nav": v["windows"]["IS"]["nav"],
                "is_ex3": v["windows"]["IS"]["ex_top3_nav"], "is_sr": v["windows"]["IS"]["daily_sharpe"],
                "oos_n": v["windows"]["OOS"]["n"], "oos_nav": v["windows"]["OOS"]["nav"],
                "oos_ex3": v["windows"]["OOS"]["ex_top3_nav"], "oos_sr": v["windows"]["OOS"]["daily_sharpe"],
                "y26_nav": v["windows"]["Y2026"]["nav"], "full_nav": v["windows"]["FULL"]["nav"],
                "is_chg": v["is_changed_trades"], "full_k": v["full_kicked"], "full_a": v["full_added"],
                "strict_is": v["strict_is_improver"], "q_base": v["bh_fdr_vs_base_q"], "q_csi": v["bh_fdr_vs_csi_q"],
            }
            for v in sorted(variants, key=lambda x: -x["is_rank_score"])
        ],
    }, trade_diffs


def build_7pillar_context(all_comb_ledgers: list[pd.DataFrame], bar_lu: dict) -> dict:
    """Load All-A panel, 5F/6F factors, matched pools, and targeted 5m bars ONCE for Task 3."""
    cal_dates, sh300, csi_s = m2.p1.load_calendar_and_csi300()
    all_sh_dts = sorted(sh300.keys())
    csi_5y_ret = float(np.prod(1.0 + csi_s.to_numpy()) - 1.0)
    df_all, tot_amt, zt_tape = m2.pb.load_full_daily_panel()
    df_10 = df_all[df_all["c6"].str.startswith(("00", "60"))].copy()
    g10 = df_10.groupby("c6", sort=False)
    df_10["board_cnt_m2"] = g10["board_cnt"].shift(2)
    df_10["is_dt_m1"] = g10["is_dt"].shift(1)
    df_10["is_dt_m2"] = g10["is_dt"].shift(2)
    df_10["is_dt_m3"] = g10["is_dt"].shift(3)
    df_10["ret_m1"] = g10["ret"].shift(1)
    df_10["open_m1"] = g10["open"].shift(1)
    df_10["close_m1"] = g10["close"].shift(1)
    df_10["bias10_m1"] = (df_10["adj_close"] / g10["adj_close"].transform(lambda s: s.rolling(10, min_periods=10).mean()) - 1.0).groupby(df_10["c6"], sort=False).shift(1)

    fac_5f, extra_f = m2.dp13.build_all_a_factors(df_all, cal_dates, all_sh_dts, zt_tape, csi_s)
    pool10_dt, q10 = m2.p1.prepare_matched_pools(df_10, cal_dates)
    by_c10 = m2.p1.build_by_c_lookup(df_10)
    pool20_dt, q20 = m2.pb.prepare_20cm_matched_pools(df_all[df_all["is20"]], cal_dates)
    by_c20 = m2.pb.build_by_c_lookup(df_all[df_all["is20"]])

    all_codes = set()
    pairs_5m = set()
    for dfc in all_comb_ledgers:
        all_codes.update(dfc["code"].unique())
        for r in dfc.itertuples(index=False):
            pairs_5m.add((r.code, r.buy_date))
    by_c_all = m2.pb.build_by_c_lookup(df_all[df_all["c6"].isin(all_codes | set(df_all[df_all["is20"]]["c6"]))])
    bars_5m = m2.p1.load_targeted_5m_bars(pairs_5m)
    reg_df = m2.p1.build_regime_table(cal_dates, all_sh_dts, tot_amt, zt_tape, df_10)

    # All-A EW daily return for static matched-exposure benchmark
    mkt_ew_ser = df_all[df_all["dt"].isin(set(cal_dates)) & (~df_all["is_st_flag"]) & (df_all["volume"] > 0) & (df_all["ret"].abs() <= 0.22)].groupby("dt")["ret"].mean().reindex(cal_dates).fillna(0.0)
    return {
        "cal_dates": cal_dates, "sh300": sh300, "all_sh_dts": all_sh_dts,
        "csi_s": csi_s, "csi_5y_ret": csi_5y_ret,
        "fac_5f": fac_5f, "extra_f": extra_f,
        "pool10_dt": pool10_dt, "q10": q10, "by_c10": by_c10,
        "pool20_dt": pool20_dt, "q20": q20, "by_c20": by_c20,
        "by_c_all": by_c_all, "bars_5m": bars_5m, "zt_tape": zt_tape, "reg_df": reg_df,
        "mkt_ew_5y": mkt_ew_ser.to_numpy(float),
    }


def main():
    t0 = time.time()
    print("[1/4] Loading pools, bars & verifying 100% baseline parity (Task 1)...")
    codes = set()
    for st in m1.STRAT_ORDER:
        d = pd.read_parquet(f"{WORK_DIR}/pool_{st}_oldhot.parquet")
        codes.update(d["code"].astype(str).str.zfill(6))
    sh300, all_sh_dts, cal_full, cal_5y, bar_lu = m1.load_calendars_and_bars(codes)
    pools = m1.load_pools_oldhot(cal_full, cal_5y, bar_lu)
    untrig_base = m1.load_untrig_with_oldhot()
    parity_rep = m1.verify_all_baselines(pools, untrig_base)
    for k, v in parity_rep.items():
        print(f"  [PARITY] {k:12s}: n={v['n']:3d}/{v['expected_n']:3d}, NAV={v['nav']:14,.4f}x, diff={v['max_abs_ret_diff']:.2e}")

    print("\n[2/4] Running IS-first 29-rule x 4-weight grid across all 6 strategies (Task 2)...")
    strat_results = {}
    all_trade_diffs = []
    for st in m1.STRAT_ORDER:
        res_st, diffs_st = eval_single_strategy_grid(st, pools, cal_full, sh300, all_sh_dts)
        strat_results[st] = res_st
        all_trade_diffs.extend(diffs_st)
        ti = res_st["top_is_locked"]
        if ti:
            bi, bo, by = res_st["baseline"]["windows"]["IS"], res_st["baseline"]["windows"]["OOS"], res_st["baseline"]["windows"]["Y2026"]
            ci, co, cy = ti["windows"]["IS"], ti["windows"]["OOS"], ti["windows"]["Y2026"]
            print(
                f"  [{st:4s}] strict_IS={res_st['strict_is_improver_count']:2d} | TopIS={ti['variant_id']:26s} "
                f"| IS: {ci['nav']:6.2f}x(SR={ci['daily_sharpe']:.2f}) vs {bi['nav']:6.2f}x(SR={bi['daily_sharpe']:.2f}) "
                f"| OOS: {co['nav']:6.2f}x(SR={co['daily_sharpe']:.2f}) vs {bo['nav']:6.2f}x(SR={bo['daily_sharpe']:.2f}) "
                f"| Y26: {cy['nav']:5.2f}x vs {by['nav']:5.2f}x | {res_st['single_strategy_verdict']}"
            )

    print("\n[3/4] Running V20.0 Combined (P3_S2C_STierReserveOnly) hooks & anti-overfit suite (Task 3)...")
    # Build combined schemes: V20_BASELINE + each strategy's top_is_locked hook + multi-strategy combos
    comb_specs = [("V20_BASELINE", "现役 V20.0 原版（零修改）", {})]
    is_winners_map = {}
    is_oos_survivors_map = {}
    for st in m1.STRAT_ORDER:
        ti = strat_results[st]["top_is_locked"]
        if ti and ti["strict_is_improver"]:
            is_winners_map[st] = (ti["rule_id"], float(ti["w"]))
            comb_specs.append((f"HOOK_{st}_{ti['variant_id']}", f"单策略挂入: {st} {ti['variant_id']}", {st: (ti["rule_id"], float(ti["w"]))}))
            if strat_results[st]["single_strategy_verdict"] == "CANDIDATE_PASS_IS_AND_OOS":
                is_oos_survivors_map[st] = (ti["rule_id"], float(ti["w"]))

    if len(is_winners_map) >= 2:
        comb_specs.append(("COMBO_ALL_STRICT_IS", "所有严格IS胜出策略组合挂入", dict(is_winners_map)))
    if len(is_oos_survivors_map) >= 2:
        comb_specs.append(("COMBO_IS_OOS_SURVIVORS", "仅IS+OOS双胜出策略组合挂入", dict(is_oos_survivors_map)))
    # Also test top 2 by IS Sharpe if fewer than 2 strict improvers
    if len(is_winners_map) < 2:
        all_top = {st: (strat_results[st]["top_is_locked"]["rule_id"], float(strat_results[st]["top_is_locked"]["w"]))
                   for st in m1.STRAT_ORDER if strat_results[st]["top_is_locked"] is not None}
        if len(all_top) >= 2:
            comb_specs.append(("COMBO_TOP_IS_ALL6", "6策略IS最优组合对照", all_top))

    T_5y = len(cal_5y)
    dt_idx_5y = {d: i for i, d in enumerate(cal_5y)}
    comb_wins = [
        ("FULL", "2021-11-16", "2026-11-16"),
        ("IS", "2021-11-16", "2024-12-31"),
        ("OOS", "2025-01-01", "2026-11-16"),
        ("Y2026", "2026-01-01", "2026-11-16"),
        ("V20_IS_Ref", "2021-11-16", "2024-08-31"),
        ("V20_OOS_Ref", "2024-09-01", "2026-11-16"),
    ]
    csi_5y_vec = np.array([sh300[d] / sh300[all_sh_dts[all_sh_dts.index(d) - 1]] - 1.0 for d in cal_5y], dtype=float)

    def _run_comb_scheme(rule_map: dict, use_crosscheck: bool = False):
        deltas = {}
        for st, (rid, w) in rule_map.items():
            deltas[st] = m1.compute_rule_delta(pools[st], rid, w)
            deltas[f"_rule_{st}"] = (rid, w)
        tr_c, waits_c = m1.run_combined_v20(pools, untrig_base, deltas, use_crosscheck_pass_pool=use_crosscheck)
        dr_5y, nd = m1.daily_mtm_from_segs(tr_c, T_5y, "mtm_5y")
        assert nd < 1e-3, f"Combined MTM diff={nd}"
        # 6-sleeve equal weight daily MTM under this rule_map
        sl_vecs = []
        for st in m1.STRAT_ORDER:
            d_vec = deltas.get(st, np.zeros(len(pools[st]), dtype=float))
            _, sl = m1.sim_standalone(st, pools[st], d_vec, high_cb_mode="v51_exact", cm20_thr=82.0)
            sl_5y = sl[sl["buy_date"].between("2021-11-16", "2026-11-16")]
            dr_s, _ = m1.daily_mtm_from_segs(sl_5y, T_5y, "mtm_5y")
            sl_vecs.append(dr_s)
        ew6_ser = pd.Series(np.column_stack(sl_vecs).mean(axis=1), index=cal_5y)
        wm = {
            wlbl: m2.calc_window_metrics_ext(tr_c, None, dr_5y, cal_5y, dt_idx_5y, sh300, all_sh_dts, sdt, edt, ew_daily_series=ew6_ser)
            for wlbl, sdt, edt in comb_wins
        }
        return tr_c, waits_c, dr_5y, wm, deltas

    comb_evals = {}
    comb_drs = {}
    comb_trs = {}
    p_comb_csi, p_comb_base = [], []
    base_tr_c, _, base_dr_5y, base_wm_c, _ = _run_comb_scheme({})
    fb20_tr_cache = {d for d, c in m2.mc.build_fb20_cln_dates_pit("2024-12-31").items() if c >= 2}

    for cid, cdesc, rmap in comb_specs:
        tr_c, waits_c, dr_5y, wm, deltas = _run_comb_scheme(rmap)
        tr_cc, _, dr_cc, wm_cc, _ = _run_comb_scheme(rmap, use_crosscheck=True)
        hlz_t, dsr150 = m2.mc.hlz_and_dsr150(tr_c.to_dict("records"), sh300, all_sh_dts, m_trials=150)
        _, dsr30 = m2.mc.hlz_and_dsr150(tr_c.to_dict("records"), sh300, all_sh_dts, m_trials=30)
        _, dsr200 = m2.mc.hlz_and_dsr150(tr_c.to_dict("records"), sh300, all_sh_dts, m_trials=200)
        ex_csi = dr_5y - csi_5y_vec
        _, p_c = stats.ttest_1samp(ex_csi, 0.0, alternative="greater") if np.std(ex_csi) > 1e-12 else (0.0, 1.0)
        diff_b = dr_5y - base_dr_5y
        _, p_b = stats.ttest_1samp(diff_b, 0.0, alternative="greater") if np.std(diff_b) > 1e-12 else (0.0, 1.0)
        p_comb_csi.append(float(p_c))
        p_comb_base.append(float(p_b))

        boot_10k = m2.paired_block_bootstrap_10k(dr_5y, base_dr_5y, csi_5y_vec)
        cv5 = m2.purged_5fold_cv_combined(pools, untrig_base, deltas, cal_5y, csi_5y_vec)
        trunc_chk = m2.check_truncation_20250101(pools, untrig_base, tr_c, rmap, fb20_tr_cache=fb20_tr_cache)

        # +-20% weight perturbation stability for non-baseline schemes
        perturb = []
        if rmap:
            for mult in (0.8, 0.9, 1.0, 1.1, 1.2):
                rmap_p = {st: (rid, round(w * mult, 2)) for st, (rid, w) in rmap.items()}
                _, _, _, wm_p, _ = _run_comb_scheme(rmap_p)
                perturb.append({
                    "mult": mult, "full_nav": wm_p["FULL"]["nav"], "is_nav": wm_p["IS"]["nav"],
                    "oos_nav": wm_p["OOS"]["nav"], "y26_nav": wm_p["Y2026"]["nav"],
                    "full_sharpe": wm_p["FULL"]["daily_sharpe"], "oos_sharpe": wm_p["OOS"]["daily_sharpe"],
                })

        if cid != "V20_BASELINE":
            all_trade_diffs.extend(m1.extract_trade_diffs(base_tr_c, tr_c, "combined_v20", cid))

        comb_trs[cid] = (tr_c, dr_5y, deltas, rmap)
        comb_drs[cid] = dr_5y
        comb_evals[cid] = {
            "scheme_id": cid, "desc": cdesc, "rule_map": {k: [v[0], v[1]] for k, v in rmap.items()},
            "windows": wm,
            "crosscheck_unfiltered_pass_pool_full": wm_cc["FULL"],
            "crosscheck_unfiltered_pass_pool_oos": wm_cc["OOS"],
            "by_strategy": tr_c["strategy"].value_counts().to_dict(),
            "waits_count": int(len(waits_c)),
            "hlz_t_trade": hlz_t, "dsr_M30": dsr30, "dsr_M150": dsr150, "dsr_M200": dsr200,
            "p_vs_csi_raw": round(float(p_c), 6), "p_vs_v20_raw": round(float(p_b), 6),
            "purged_5fold_cv": cv5,
            "paired_block_bootstrap_10k": boot_10k,
            "perturbation_pm20pct": perturb,
            "truncation_20250101": trunc_chk,
        }

    qc_csi = m2.bh_fdr(p_comb_csi)
    qc_base = m2.bh_fdr(p_comb_base)
    for i_c, cid in enumerate(comb_evals.keys()):
        comb_evals[cid]["bh_fdr_vs_csi_q"] = qc_csi[i_c]
        comb_evals[cid]["bh_fdr_vs_v20_q"] = qc_base[i_c]

    cscv_comb = m2.cscv_pbo_family(comb_drs, "V20_BASELINE", S_list=(8, 10)) if len(comb_drs) >= 2 else {}

    # Select best combined candidate on IS (for blind OOS PK + full 7-pillar comparison vs V20_BASELINE)
    cand_ids = [cid for cid in comb_evals if cid != "V20_BASELINE"]
    best_is_comb_id = max(
        cand_ids,
        key=lambda c: (
            comb_evals[c]["windows"]["IS"]["daily_sharpe"] - comb_evals["V20_BASELINE"]["windows"]["IS"]["daily_sharpe"],
            comb_evals[c]["windows"]["IS"]["nav"],
        ),
    ) if cand_ids else "V20_BASELINE"

    print(f"\n[4/4] Running 7-Pillar Institutional Suite & 1/vol Ablations on V20_BASELINE vs {best_is_comb_id}...")
    fmt_list = [m2.format_ledger_for_partd(comb_trs[cid][0], bar_lu) for cid in comb_trs]
    ctx_7p = build_7pillar_context(fmt_list, bar_lu)

    targets_7p = ["V20_BASELINE"] + ([best_is_comb_id] if best_is_comb_id != "V20_BASELINE" else [])
    if "COMBO_IS_OOS_SURVIVORS" in comb_evals and "COMBO_IS_OOS_SURVIVORS" not in targets_7p:
        targets_7p.append("COMBO_IS_OOS_SURVIVORS")

    seven_pillars = {}
    ablations = {}
    for cid in targets_7p:
        tr_c, dr_5y, deltas, _ = comb_trs[cid]
        fmt_df = m2.format_ledger_for_partd(tr_c, bar_lu)
        seven_pillars[cid] = m2.run_7pillars_combined(fmt_df, dr_5y, ctx_7p)
        ablations[cid] = m2.calc_static_and_inv_vol_ablations(
            tr_c, dr_5y, pools, untrig_base, deltas, cal_5y, csi_5y_vec, ctx_7p["mkt_ew_5y"], ctx_7p["by_c_all"]
        )

    # Final binary verdict for V20 combined
    b_w = comb_evals["V20_BASELINE"]["windows"]
    final_comb_verdict = "KEEP_V20_UNCHANGED"
    winning_cand_id = None
    for cid in cand_ids:
        cw = comb_evals[cid]["windows"]
        boot = comb_evals[cid]["paired_block_bootstrap_10k"]
        cv5 = comb_evals[cid]["purged_5fold_cv"]
        if (
            cw["IS"]["nav"] > b_w["IS"]["nav"]
            and cw["OOS"]["nav"] > b_w["OOS"]["nav"]
            and cw["OOS"]["ex_top5_nav"] >= b_w["OOS"]["ex_top5_nav"] * 0.99
            and cw["Y2026"]["nav"] >= b_w["Y2026"]["nav"] * 0.95
            and cw["FULL"]["daily_sharpe"] >= b_w["FULL"]["daily_sharpe"]
            and cv5["n_positive_folds"] == 5
            and boot["paired_prob_cand_beat_v20_nav_pct"] >= 60.0
            and comb_evals[cid]["bh_fdr_vs_v20_q"] <= 0.15
        ):
            final_comb_verdict = "ADOPT_CANDIDATE"
            winning_cand_id = cid

    # Export CSVs & JSON
    cmp_rows = []
    for cid, ev in comb_evals.items():
        wf, wi, wo, wy = ev["windows"]["FULL"], ev["windows"]["IS"], ev["windows"]["OOS"], ev["windows"]["Y2026"]
        cmp_rows.append({
            "scheme_id": cid, "desc": ev["desc"],
            "n_full": wf["n"], "wr_full_pct": wf["wr_pct"], "plr_full": wf["plr"],
            "nav_full": wf["nav"], "ew6_full": wf["eq_nav"], "ex3_full": wf["ex_top3_nav"], "ex5_full": wf["ex_top5_nav"],
            "mdd_full_pct": wf["daily_mdd_pct"], "sharpe_full": wf["daily_sharpe"], "calmar_full": wf["daily_calmar"],
            "excess_csi300_full_pp": wf["excess_csi300_pp"],
            "n_is": wi["n"], "nav_is": wi["nav"], "ex3_is": wi["ex_top3_nav"], "sharpe_is": wi["daily_sharpe"],
            "n_oos": wo["n"], "nav_oos": wo["nav"], "ex3_oos": wo["ex_top3_nav"], "ex5_oos": wo["ex_top5_nav"],
            "mdd_oos_pct": wo["daily_mdd_pct"], "sharpe_oos": wo["daily_sharpe"], "calmar_oos": wo["daily_calmar"],
            "n_y26": wy["n"], "nav_y26": wy["nav"], "sharpe_y26": wy["daily_sharpe"],
            "hlz_t": ev["hlz_t_trade"], "dsr_m150": ev["dsr_M150"],
            "bh_fdr_vs_v20_q": ev["bh_fdr_vs_v20_q"],
            "cv5_min_nav": ev["purged_5fold_cv"]["min_fold_nav"],
            "cv5_mean_sharpe": ev["purged_5fold_cv"]["mean_fold_sharpe"],
            "boot_p05_nav": ev["paired_block_bootstrap_10k"]["cand_nav_p05"],
            "boot_prob_beat_v20_pct": ev["paired_block_bootstrap_10k"]["paired_prob_cand_beat_v20_nav_pct"],
            "trunc_20250101_pass": ev["truncation_20250101"]["pass"],
        })
    cmp_csv = f"{WORK_DIR}/wave2b_v20_combined_compare.csv"
    pd.DataFrame(cmp_rows).to_csv(cmp_csv, index=False, encoding="utf-8-sig")

    diff_csv = f"{WORK_DIR}/wave2b_trade_diffs.csv"
    pd.DataFrame(all_trade_diffs).to_csv(diff_csv, index=False, encoding="utf-8-sig")

    out_json = f"{WORK_DIR}/wave2b_rerank_v20_jianyan.json"
    out_payload = m2.sanitize_json({
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 2),
            "d12_yfinance_imported": "yfinance" in sys.modules,
            "is_window": "2021-01-04 ~ 2024-12-31",
            "oos_window": "2025-01-01 ~ 2026-11-25 (combined to 2026-11-16)",
            "y2026_window": "2026-01-01 ~ 2026-11-25 (combined to 2026-11-16)",
        },
        "task1_baseline_parity": parity_rep,
        "task2_single_strategy_rerank": strat_results,
        "task3_v20_combined_jianyan": {
            "schemes": comb_evals,
            "cscv_pbo_combined": cscv_comb,
            "best_is_combined_id": best_is_comb_id,
            "static_and_inv_vol_ablations": ablations,
            "seven_pillars_institutional": seven_pillars,
            "final_verdict": final_comb_verdict,
            "winning_candidate_id": winning_cand_id,
        },
        "output_files": {
            "json": out_json, "combined_compare_csv": cmp_csv, "trade_diffs_csv": diff_csv,
        },
    })
    raw_txt = json.dumps(out_payload, ensure_ascii=False, indent=2, allow_nan=False)
    low_t = raw_txt.lower()
    assert ("cap" + "10m") not in low_t and ("cap" + "1000w") not in low_t, "Forbidden capped metric!"
    with open(out_json, "w", encoding="utf-8") as f:
        f.write(raw_txt)

    print(f"\n[DONE in {time.time() - t0:.1f}s] Verdict={final_comb_verdict} | Saved -> {out_json}")
    print(pd.DataFrame(cmp_rows)[["scheme_id", "n_full", "nav_full", "ex5_full", "sharpe_full", "nav_is", "nav_oos", "nav_y26", "boot_prob_beat_v20_pct", "bh_fdr_vs_v20_q"]].to_string(index=False))


if __name__ == "__main__":
    main()

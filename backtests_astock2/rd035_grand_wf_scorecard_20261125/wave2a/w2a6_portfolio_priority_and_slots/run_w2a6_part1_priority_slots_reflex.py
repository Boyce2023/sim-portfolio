#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 2A-6 Part 1:
  Module 1: 6-Strategy Priority Shuffling (all 720 perms + named + dynamic causal exit_date<t + S-tier wait ablation)
  Module 2: Single Slot 100% vs Light Dual-Slot (50/50, 70+30, Vol Sizing <= 100%)
  Module 3: PM Pain Point #4A (Solo vs Multi-Strategy Resonance + Same-Theme Overlap + Score Spread + Causal Tilt)
  Module 5: Equity Curve Reflexivity (Post-Loss/Post-Win Streaks + Autocorrelation + Causal Sizing)
Zero yfinance (D12). Zero lookahead. 2024-12-31 physical truncation verified.
"""
import itertools
import json
import math
import os
import resource
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd
import scipy.stats as stats

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import _w2a6_common as w2c

OUT_DIR = w2c.OUT_DIR


def _build_tier_causal_stats_by_day(ref_df: pd.DataFrame, cal_5y: list[str], idx_5y: dict[str, int], metric: str = "daily_eff", roll_n: int | None = None, by_strat: bool = False) -> dict[str, dict[str, int]]:
    """
    Strictly causal (exit_date < t) Empirical Bayes ranking of tiers (or strategies) for every day t in cal_5y.
    Returns {dt: {key: rank_int (1=best)}}.
    """
    df = ref_df.copy()
    df["buy_date"] = df["buy_date"].astype(str).str[:10]
    df["exit_date"] = df["exit_date"].astype(str).str[:10]
    df["hold_td"] = np.maximum(1, df["exit_date"].map(idx_5y).fillna(0) - df["buy_date"].map(idx_5y).fillna(0)).astype(float)
    df["log_ret"] = np.log1p(np.maximum(-0.99, df["net_ret"].to_numpy(float)))
    df["key"] = df["strategy"] if by_strat else df["tier"]
    df = df.sort_values(["exit_date", "buy_date", "code"], kind="mergesort").reset_index(drop=True)

    keys_all = sorted(df["key"].unique().tolist())
    # Canonical fallback order
    base_ord = w2c.CANON_S2C_STRAT_PRIO if by_strat else w2c.CANON_S2C_TIER_MAP

    ex_dts = df["exit_date"].to_numpy()
    key_arr = df["key"].to_numpy()
    ret_arr = df["net_ret"].to_numpy(float)
    lr_arr = df["log_ret"].to_numpy(float)
    ht_arr = df["hold_td"].to_numpy(float)

    n_tot = len(df)
    ptr = 0
    hist_by_k = defaultdict(list)  # list of (ret, lr, ht)
    all_rets = []
    all_lrs = []
    all_hts = []

    daily_ranks = {}
    for dt in cal_5y:
        while ptr < n_tot and ex_dts[ptr] < dt:
            k = key_arr[ptr]
            r = float(ret_arr[ptr])
            lr = float(lr_arr[ptr])
            ht = float(ht_arr[ptr])
            hist_by_k[k].append((r, lr, ht))
            all_rets.append(r)
            all_lrs.append(lr)
            all_hts.append(ht)
            ptr += 1

        n_all = len(all_rets)
        if n_all < 20:
            daily_ranks[dt] = dict(base_ord)
            continue

        g_ret = float(np.mean(all_rets))
        g_lr = float(np.mean(all_lrs))
        g_ht = float(np.mean(all_hts))
        g_sd = max(0.02, float(np.std(all_rets, ddof=1)))
        tau = 10.0

        scores = {}
        for k in keys_all:
            if k == "20cm_A(76-81)":
                scores[k] = -999.0
                continue
            lst = hist_by_k.get(k, [])
            if len(lst) < 5:
                # Warmup prior biased subtly by canonical order so ties don't jump randomly
                scores[k] = -100.0 - base_ord.get(k, 50)
                continue
            use = lst[-roll_n:] if (roll_n is not None and len(lst) > roll_n) else lst
            nk = len(use)
            rs = np.array([x[0] for x in use])
            lrs = np.array([x[1] for x in use])
            hts = np.array([x[2] for x in use])
            if metric == "exp_ret":
                val = (rs.sum() + tau * g_ret) / (nk + tau)
            elif metric == "daily_eff":
                eb_lr = (lrs.sum() + tau * g_lr) / (nk + tau)
                eb_ht = (hts.sum() + tau * g_ht) / (nk + tau)
                val = eb_lr / max(1.0, eb_ht)
            elif metric == "sharpe":
                eb_r = (rs.sum() + tau * g_ret) / (nk + tau)
                sd_k = float(np.std(rs, ddof=1)) if nk > 1 else g_sd
                eb_sd = (nk * sd_k + tau * g_sd) / (nk + tau)
                val = eb_r / max(0.01, eb_sd)
            else:
                raise ValueError(metric)
            scores[k] = float(val)

        ranked = sorted(keys_all, key=lambda x: (-scores[x], base_ord.get(x, 50)))
        pmap = {}
        for idx_r, k in enumerate(ranked, 1):
            pmap[k] = 999 if k == "20cm_A(76-81)" else idx_r
        daily_ranks[dt] = pmap

    return daily_ranks


def run_module1(ctx: dict) -> tuple[dict, list[dict]]:
    print("[Module 1] Running 720 strategy permutations + named + causal dynamic priority + S-tier wait ablations...")
    cal_5y = ctx["cal_5y"]
    idx_5y = ctx["idx_5y"]
    slot_pool = ctx["slot_pool_64"]
    pass_pool = ctx["pass_pool_64"]
    ut_5y = ctx["untrig_base"][ctx["untrig_base"]["buy_date"].between("2021-11-16", "2026-11-16")].copy()

    # 1A. Fast sweep of all 720 permutations on slot_pool (exact V20 universe) & pass_pool
    # Fast vectorized pre-index per day for 720 permutations (in pure Python tuples for speed)
    def sweep_720(pool_x: pd.DataFrame, label: str) -> dict:
        df_s = pd.concat([pool_x[pool_x["tier"] != "20cm_A(76-81)"], ut_5y], ignore_index=True)
        is_s_cond = df_s["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"])
        df_s["phase"] = np.where((df_s["buy_hhmm"] == 925) | is_s_cond, 0, 1)
        # Keep top 1 per (buy_date, strategy, is_untrig) or sort dynamically per perm
        records = []
        for r in df_s.itertuples(index=False):
            records.append((
                r.buy_date, int(r.phase), r.strategy, float(r.score), int(r.buy_hhmm),
                r.code, r.exit_date, int(r.exit_hhmm), bool(r.is_untrig), float(r.net_ret)
            ))
        # Group by buy_date
        by_dt = defaultdict(list)
        for rec in records:
            by_dt[rec[0]].append(rec)
        dts_sorted = sorted(by_dt.keys())

        perms = list(itertools.permutations(w2c.STRAT_ORDER))
        rows_out = []
        for perm in perms:
            pmap = {st: i + 1 for i, st in enumerate(perm)}
            cur_ed, cur_eh = "", 0
            tr_rets_is, tr_rets_oos, tr_rets_y26, tr_rets_wf, tr_rets_5y = [], [], [], [], []
            for dt in dts_sorted:
                if cur_ed and dt < cur_ed:
                    continue
                cands = sorted(by_dt[dt], key=lambda x: (x[1], pmap[x[2]], -x[3], x[4], x[5]))
                for x in cands:
                    bd, _, _, _, bh, _, ed, eh, is_ut, nr = x
                    if (not cur_ed) or (bd > cur_ed) or (bd == cur_ed and bh > cur_eh):
                        cur_ed, cur_eh = ed, eh
                        if not is_ut:
                            tr_rets_5y.append(nr)
                            if bd <= "2024-12-31":
                                tr_rets_is.append(nr)
                            else:
                                tr_rets_oos.append(nr)
                            if bd >= "2023-01-03":
                                tr_rets_wf.append(nr)
                            if bd >= "2026-01-01":
                                tr_rets_y26.append(nr)
                        break
            nav_5y = float(np.prod(1.0 + np.asarray(tr_rets_5y))) if tr_rets_5y else 1.0
            nav_is = float(np.prod(1.0 + np.asarray(tr_rets_is))) if tr_rets_is else 1.0
            nav_oos = float(np.prod(1.0 + np.asarray(tr_rets_oos))) if tr_rets_oos else 1.0
            nav_wf = float(np.prod(1.0 + np.asarray(tr_rets_wf))) if tr_rets_wf else 1.0
            nav_y26 = float(np.prod(1.0 + np.asarray(tr_rets_y26))) if tr_rets_y26 else 1.0
            rows_out.append({
                "perm": ">".join(perm),
                "n_5y": len(tr_rets_5y), "nav_5y": nav_5y,
                "nav_is": nav_is, "nav_oos": nav_oos, "nav_wf": nav_wf, "nav_y26": nav_y26,
            })

        pdf = pd.DataFrame(rows_out)
        s2c_str = ">".join(w2c.STRAT_ORDER)
        s2c_row = pdf[pdf["perm"] == s2c_str].iloc[0].to_dict()
        pdf_sorted_5y = pdf.sort_values("nav_5y", ascending=False).reset_index(drop=True)
        pdf_sorted_is = pdf.sort_values("nav_is", ascending=False).reset_index(drop=True)
        pdf_sorted_oos = pdf.sort_values("nav_oos", ascending=False).reset_index(drop=True)
        s2c_rk_5y = int(pdf_sorted_5y.index[pdf_sorted_5y["perm"] == s2c_str][0]) + 1
        s2c_rk_is = int(pdf_sorted_is.index[pdf_sorted_is["perm"] == s2c_str][0]) + 1
        s2c_rk_oos = int(pdf_sorted_oos.index[pdf_sorted_oos["perm"] == s2c_str][0]) + 1
        rho_is_oos, p_is_oos = stats.spearmanr(np.log(pdf["nav_is"]), np.log(pdf["nav_oos"]))
        return {
            "pool_label": label,
            "n_perms": len(pdf),
            "s2c_perm": s2c_str,
            "s2c_metrics": s2c_row,
            "s2c_rank_5y": s2c_rk_5y,
            "s2c_rank_is": s2c_rk_is,
            "s2c_rank_oos": s2c_rk_oos,
            "is_vs_oos_spearman_rho": round(float(rho_is_oos), 4),
            "is_vs_oos_spearman_p": round(float(p_is_oos), 6),
            "top5_by_5y": pdf_sorted_5y.head(5).to_dict("records"),
            "top5_by_is": pdf_sorted_is.head(5).to_dict("records"),
            "top5_by_oos": pdf_sorted_oos.head(5).to_dict("records"),
            "bottom3_by_5y": pdf_sorted_5y.tail(3).to_dict("records"),
            "nav_5y_quantiles": {q: float(pdf["nav_5y"].quantile(float(q))) for q in (0.05, 0.25, 0.50, 0.75, 0.95)},
            "nav_oos_quantiles": {q: float(pdf["nav_oos"].quantile(float(q))) for q in (0.05, 0.25, 0.50, 0.75, 0.95)},
        }

    sweep_slot = sweep_720(slot_pool, "slot_pool_v20")
    sweep_pass = sweep_720(pass_pool, "pass_pool_full")
    print(f"  [720 Sweep slot_pool] S2C rank 5Y={sweep_slot['s2c_rank_5y']}/720, IS={sweep_slot['s2c_rank_is']}, OOS={sweep_slot['s2c_rank_oos']}, IS-OOS rho={sweep_slot['is_vs_oos_spearman_rho']}")
    print(f"  [720 Sweep pass_pool] S2C rank 5Y={sweep_pass['s2c_rank_5y']}/720, IS={sweep_pass['s2c_rank_is']}, OOS={sweep_pass['s2c_rank_oos']}, IS-OOS rho={sweep_pass['is_vs_oos_spearman_rho']}")

    # 1B. Full MTM + 1000x Perm evaluation on key Module 1 schemes
    # Note: slot_pool already includes 20cm_A(76-81) from cm20_preslot_thr=76.0!
    # Also build pass_with_20a from pass_pool + m20_a76_pool (deduped) if needed, or simply allow_20a on slot_pool.
    m20_a76_pool = ctx["master_5y"][(ctx["master_5y"]["strategy"] == "20cm") & (ctx["master_5y"]["is_obs_a76"] == 1)].copy()
    m20_a76_pool["score"] = m20_a76_pool["v20_score"].astype(float)
    m20_a76_pool["tier"] = "20cm_A(76-81)"
    m20_a76_pool["net_ret"] = m20_a76_pool["net_ret_f64"]
    m20_a76_pool["is_untrig"] = False
    m20_a76_pool["buy_hhmm"] = 925
    m20_a76_pool["exit_hhmm"] = 1500
    cols_sub = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "tier", "score", "net_ret", "is_untrig", "mtm_5y", "open_pct"]
    pool_with_20a = pd.concat([slot_pool[slot_pool["tier"] != "20cm_A(76-81)"], m20_a76_pool[cols_sub]], ignore_index=True)

    def _strat_map_fn(order_list: list[str], allow_20a: bool = False):
        smap = {st: i + 1 for i, st in enumerate(order_list)}
        def fn(d: pd.DataFrame) -> pd.DataFrame:
            out = d.copy()
            p = out["strategy"].map(smap).fillna(999).astype(int)
            if not allow_20a:
                p = np.where(out["tier"] == "20cm_A(76-81)", 999, p)
            else:
                p = np.where(out["tier"] == "20cm_A(76-81)", 7, p)
            out["prio"] = p
            return out
        return fn

    def _tier_map_fn(tmap: dict):
        def fn(d: pd.DataFrame) -> pd.DataFrame:
            out = d.copy()
            out["prio"] = out["tier"].map(tmap).fillna(999).astype(int)
            return out
        return fn

    def _dyn_rank_fn(daily_ranks: dict, by_strat: bool = False):
        def fn(d: pd.DataFrame) -> pd.DataFrame:
            out = d.copy()
            key_col = "strategy" if by_strat else "tier"
            out["prio"] = [
                daily_ranks.get(bd, {}).get(k, 999)
                for bd, k in zip(out["buy_date"], out[key_col])
            ]
            return out
        return fn

    # Precompute causal daily ranks
    dyn_tier_eff = _build_tier_causal_stats_by_day(slot_pool, cal_5y, idx_5y, metric="daily_eff", by_strat=False)
    dyn_tier_ret = _build_tier_causal_stats_by_day(slot_pool, cal_5y, idx_5y, metric="exp_ret", by_strat=False)
    dyn_tier_sr = _build_tier_causal_stats_by_day(slot_pool, cal_5y, idx_5y, metric="sharpe", by_strat=False)
    dyn_strat_eff = _build_tier_causal_stats_by_day(slot_pool, cal_5y, idx_5y, metric="daily_eff", by_strat=True)
    dyn_strat_roll30 = _build_tier_causal_stats_by_day(slot_pool, cal_5y, idx_5y, metric="daily_eff", roll_n=30, by_strat=True)

    # Also build IS-top1 & OOS-top1 from 720 sweep
    is_best_perm = sweep_slot["top5_by_is"][0]["perm"].split(">")
    y5_best_perm = sweep_slot["top5_by_5y"][0]["perm"].split(">")

    tier_1to2s_split = {
        "3to4_S(>=102)": 1, "3to4_A(90-101)": 1, "high_S(>=96)": 2, "high_A(88-95)": 2,
        "pry_S(>=175)": 3, "pry_A(165-174)": 3, "2to3_S(>=96)": 4, "2to3_A(90-95)": 4,
        "1to2_S(>=340)": 5, "20cm_S(>=82)": 6, "1to2_A(304.8-339.9)": 7, "1to2_FB(295-304.7)": 8,
        "20cm_A(76-81)": 999,
    }

    specs_m1 = [
        ("M1_BASE_V20_P3_S2C", "现行 V20.0 P3_S2C_STierReserveOnly 基准", slot_pool, _tier_map_fn(w2c.CANON_S2C_TIER_MAP), "s_tier_reserve_only", 1),
        ("M1_S3B_20cm_gt_1to2", "静态重排: 20cm提权压1to2 (S3B)", slot_pool, _strat_map_fn(["3to4", "high", "pry", "2to3", "20cm", "1to2"]), "s_tier_reserve_only", 1),
        ("M1_20cm_P1_First", "静态重排: 20cm提权至第1顺位", slot_pool, _strat_map_fn(["20cm", "3to4", "high", "pry", "2to3", "1to2"]), "s_tier_reserve_only", 1),
        ("M1_20cm_gt_2to3_1to2", "静态重排: 20cm提权至第4顺位压2to3+1to2", slot_pool, _strat_map_fn(["3to4", "high", "pry", "20cm", "2to3", "1to2"]), "s_tier_reserve_only", 1),
        ("M1_high_P1_First", "静态重排: 高标首阴提权至第1顺位", slot_pool, _strat_map_fn(["high", "3to4", "pry", "2to3", "1to2", "20cm"]), "s_tier_reserve_only", 1),
        ("M1_1to2_P1_First", "静态重排: 一进二提权至第1顺位", slot_pool, _strat_map_fn(["1to2", "3to4", "high", "pry", "2to3", "20cm"]), "s_tier_reserve_only", 1),
        ("M1_1to2_gt_2to3", "静态重排: 一进二提权压2to3", slot_pool, _strat_map_fn(["3to4", "high", "pry", "1to2", "2to3", "20cm"]), "s_tier_reserve_only", 1),
        ("M1_2to3_P1_First", "静态重排: 二进三提权至第1顺位", slot_pool, _strat_map_fn(["2to3", "3to4", "high", "pry", "1to2", "20cm"]), "s_tier_reserve_only", 1),
        ("M1_pry_P1_First", "静态重排: 撬板提权至第1顺位", slot_pool, _strat_map_fn(["pry", "3to4", "high", "2to3", "1to2", "20cm"]), "s_tier_reserve_only", 1),
        ("M1_IS_Best_Perm", f"静态720枚举IS最优盲测: {'>'.join(is_best_perm)}", slot_pool, _strat_map_fn(is_best_perm), "s_tier_reserve_only", 1),
        ("M1_5Y_Best_Perm", f"静态720枚举5Y事后最优(过拟合对照): {'>'.join(y5_best_perm)}", slot_pool, _strat_map_fn(y5_best_perm), "s_tier_reserve_only", 1),
        ("M1_1to2S_Split_gt_20cm", "精细分档: 1to2_S>=340 > 20cm_S82 > 1to2_A/FB", slot_pool, _tier_map_fn(tier_1to2s_split), "s_tier_reserve_only", 1),
        ("M1_S2C_with_20cmA76_P7", "纳入20cm_A(76-81)至第7顺位补位", pool_with_20a, _strat_map_fn(w2c.STRAT_ORDER, allow_20a=True), "s_tier_reserve_only", 1),
        ("M1_S2C_FullPassPool", "全过线池(解除独立槽互卡)按S2C单仓", pass_pool, _tier_map_fn(w2c.CANON_S2C_TIER_MAP), "s_tier_reserve_only", 1),
        ("M1_DYN_Tier_DailyEff", "逐日前视镜(exit_date<t): 12分档EB日均效率动态抢仓", slot_pool, _dyn_rank_fn(dyn_tier_eff, False), "s_tier_reserve_only", 1),
        ("M1_DYN_Tier_ExpRet", "逐日前视镜(exit_date<t): 12分档EB单笔期望收益动态抢仓", slot_pool, _dyn_rank_fn(dyn_tier_ret, False), "s_tier_reserve_only", 1),
        ("M1_DYN_Tier_Sharpe", "逐日前视镜(exit_date<t): 12分档EB单笔Sharpe动态抢仓", slot_pool, _dyn_rank_fn(dyn_tier_sr, False), "s_tier_reserve_only", 1),
        ("M1_DYN_Strat_DailyEff", "逐日前视镜(exit_date<t): 6策略EB日均效率动态抢仓", slot_pool, _dyn_rank_fn(dyn_strat_eff, True), "s_tier_reserve_only", 1),
        ("M1_DYN_Strat_Roll30_Eff", "逐日前视镜(exit_date<t): 6策略近30笔滚动效率动态抢仓", slot_pool, _dyn_rank_fn(dyn_strat_roll30, True), "s_tier_reserve_only", 1),
        ("M1_WAIT_Cancel_0925First", "取消S档等待: 全部09:25确定买优先于盘中条件单", slot_pool, _tier_map_fn(w2c.CANON_S2C_TIER_MAP), "confirmed_0925_first", 1),
        ("M1_WAIT_NaiveOracle", "无等待上界Oracle对照(事后已知未触不占位)", slot_pool, _tier_map_fn(w2c.CANON_S2C_TIER_MAP), "naive", 1),
        ("M1_WAIT_ReserveAll", "强化等待: A+S全部盘中条件单皆可占位等待", slot_pool, _tier_map_fn(w2c.CANON_S2C_TIER_MAP), "reserve_all", 1),
        ("M1_WAIT_Plus1to2S", "强化S档等待: 3to4_S + high_S + 1to2_S>=340占位", slot_pool, _tier_map_fn(w2c.CANON_S2C_TIER_MAP), "s_tier_plus_1to2S", 1),
        ("M1_WAIT_3to4S_Only", "精简S档等待: 仅3to4_S>=102占位等待(high_S不等待)", slot_pool, _tier_map_fn(w2c.CANON_S2C_TIER_MAP), "s_tier_3to4S_only", 1),
    ]

    evals = {}
    csv_rows = []
    sims_cache = {}
    for sid, desc, pool_x, rfn, tmode, max_ps in specs_m1:
        sim = w2c.simulate_multi_slot_mtm(
            pool_x, rfn, cal_5y, idx_5y, n_slots=1,
            untrig_df=ut_5y, timing_mode=tmode, max_per_strat_per_day=max_ps,
        )
        ev = w2c.evaluate_portfolio_windows(sim["trades_df"], sim["dr_5y"], ctx, perm_n=1000)
        ev["waits_count"] = int(len(sim["waits"]))
        ev["desc"] = desc
        evals[sid] = ev
        sims_cache[sid] = sim
        csv_rows.append(_flatten_scheme_row("Module1_Priority", sid, desc, ev))

    # Physical truncation 2024-12-31 test on dynamic priority engine
    cutoff = "2024-12-31"
    cal_tr = [d for d in cal_5y if d <= cutoff]
    idx_tr = {d: i for i, d in enumerate(cal_tr)}
    slot_tr = slot_pool[slot_pool["buy_date"] <= cutoff].copy()
    ut_tr = ut_5y[ut_5y["buy_date"] <= cutoff].copy()
    dyn_tier_eff_tr = _build_tier_causal_stats_by_day(slot_tr, cal_tr, idx_tr, metric="daily_eff", by_strat=False)
    sim_tr = w2c.simulate_multi_slot_mtm(
        slot_tr, _dyn_rank_fn(dyn_tier_eff_tr, False), cal_tr, idx_tr,
        n_slots=1, untrig_df=ut_tr, timing_mode="s_tier_reserve_only",
    )
    full_tr_le = sims_cache["M1_DYN_Tier_DailyEff"]["trades_df"]
    full_tr_le = full_tr_le[full_tr_le["exit_date"] <= cutoff].reset_index(drop=True)
    trunc_tr_le = sim_tr["trades_df"][sim_tr["trades_df"]["exit_date"] <= cutoff].reset_index(drop=True)
    assert len(full_tr_le) == len(trunc_tr_le)
    assert list(zip(full_tr_le["buy_date"], full_tr_le["code"])) == list(zip(trunc_tr_le["buy_date"], trunc_tr_le["code"]))
    trunc_diff = float(np.max(np.abs(full_tr_le["net_ret"].to_numpy(float) - trunc_tr_le["net_ret"].to_numpy(float)))) if len(full_tr_le) else 0.0
    assert trunc_diff == 0.0, f"Module 1 truncation diff != 0: {trunc_diff}"

    return {
        "sweep_720_slot_pool": sweep_slot,
        "sweep_720_pass_pool": sweep_pass,
        "schemes": evals,
        "latest_causal_tier_eff_rank": dyn_tier_eff[cal_5y[-1]],
        "latest_causal_strat_eff_rank": dyn_strat_eff[cal_5y[-1]],
        "truncation_20241231_M1_DYN": {"n_trades_le_cutoff": int(len(full_tr_le)), "max_abs_ret_diff": trunc_diff, "pass": trunc_diff == 0.0},
    }, csv_rows


def _simulate_fixed_two_subaccounts(pool_x: pd.DataFrame, ut_5y: pd.DataFrame, cal_5y: list[str], idx_5y: dict[str, int]) -> dict:
    """Two completely independent 50%-initial-capital sub-accounts (never rebalanced across slots)."""
    T = len(cal_5y)
    df = pd.concat([pool_x, ut_5y], ignore_index=True)
    df["prio"] = df["tier"].map(w2c.CANON_S2C_TIER_MAP).fillna(999).astype(int)
    df = df[df["prio"] < 999].copy()
    is_s_cond = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"])
    df["phase"] = np.where((df["buy_hhmm"] == 925) | is_s_cond, 0, 1)
    df = df.sort_values(["buy_date", "phase", "prio", "score", "buy_hhmm", "code"], ascending=[True, True, True, False, True, True]).reset_index(drop=True)
    by_day = {d: g for d, g in df.groupby("buy_date", sort=False)}

    # Two independent slots starting at 0.50 capital each
    s_state = [
        {"cash": 0.50, "pos": None},
        {"cash": 0.50, "pos": None},
    ]
    dr_5y = np.zeros(T, dtype=float)
    prev_eq = 1.0
    taken = []

    for ti, dt in enumerate(cal_5y):
        grp = by_day.get(dt)
        if grp is not None and not grp.empty:
            for r in grp.itertuples(index=False):
                # Free any slot exiting strictly before r.buy_hhmm on dt
                for sl in s_state:
                    p = sl["pos"]
                    if p is not None and ((p["exit_date"] < dt) or (p["exit_date"] == dt and p["exit_hhmm"] < int(r.buy_hhmm))):
                        if not p["is_wait"]:
                            p["val"] *= p["mmap"].get(ti, 1.0)
                            p["applied"].add(ti)
                            sl["cash"] += p["val"]
                        sl["pos"] = None
                # Prevent same code in both slots simultaneously
                if any(sl["pos"] is not None and (not sl["pos"]["is_wait"]) and sl["pos"]["code"] == r.code for sl in s_state):
                    continue
                for sl in s_state:
                    if sl["pos"] is None:
                        if r.is_untrig:
                            sl["pos"] = {"exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm), "is_wait": True, "code": r.code, "val": 0.0, "mmap": {}, "applied": set()}
                        else:
                            alloc = sl["cash"]
                            sl["cash"] = 0.0
                            mmap = {t_i: float(mult) for t_i, mult in r.mtm_5y} if hasattr(r, "mtm_5y") and r.mtm_5y else {}
                            sl["pos"] = {"exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm), "is_wait": False, "code": r.code, "val": alloc, "mmap": mmap, "applied": set()}
                            taken.append({
                                "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm), "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm),
                                "code": r.code, "name": getattr(r, "name", ""), "strategy": r.strategy, "tier": r.tier,
                                "score": float(r.score), "net_ret": float(r.net_ret),
                                "alloc_weight": round(alloc / max(1e-12, prev_eq), 6),
                            })
                        break

        for sl in s_state:
            p = sl["pos"]
            if p is not None:
                if (not p["is_wait"]) and ti not in p["applied"]:
                    p["val"] *= p["mmap"].get(ti, 1.0)
                    p["applied"].add(ti)
                if p["exit_date"] <= dt:
                    if not p["is_wait"]:
                        sl["cash"] += p["val"]
                    sl["pos"] = None

        eq_eod = sum(sl["cash"] + (sl["pos"]["val"] if (sl["pos"] and not sl["pos"]["is_wait"]) else 0.0) for sl in s_state)
        dr_5y[ti] = eq_eod / prev_eq - 1.0
        prev_eq = eq_eod

    return {"trades_df": pd.DataFrame(taken), "dr_5y": dr_5y, "nav_equity": float(prev_eq)}


def run_module2(ctx: dict) -> tuple[dict, list[dict]]:
    print("[Module 2] Running Single Slot 100% vs Dual-Slot (50/50, 70+30, Vol Sizing <= 100%)...")
    cal_5y = ctx["cal_5y"]
    idx_5y = ctx["idx_5y"]
    slot_pool = ctx["slot_pool_64"]
    pass_pool = ctx["pass_pool_64"]
    ut_5y = ctx["untrig_base"][ctx["untrig_base"]["buy_date"].between("2021-11-16", "2026-11-16")].copy()

    def tier_rank_fn(d: pd.DataFrame) -> pd.DataFrame:
        out = d.copy()
        out["prio"] = out["tier"].map(w2c.CANON_S2C_TIER_MAP).fillna(999).astype(int)
        return out

    # Precompute causal market 20d volatility (using strictly t-20..t-1 alla_ew_daily_ret)
    ew_ser = ctx["ew_5y"]
    mkt_vol_20d = np.full(len(cal_5y), np.nan)
    for ti in range(20, len(cal_5y)):
        mkt_vol_20d[ti] = float(np.std(ew_ser[ti - 20:ti], ddof=1))

    # Precompute causal stock amp_20d median & strategy vol strictly < t
    def build_causal_vol_maps():
        amps_done = []
        strat_rets = defaultdict(list)
        sp_sorted = slot_pool.sort_values(["exit_date", "buy_date", "code"]).reset_index(drop=True)
        ex_dts = sp_sorted["exit_date"].to_numpy()
        st_arr = sp_sorted["strategy"].to_numpy()
        nr_arr = sp_sorted["net_ret"].to_numpy(float)
        amp_arr = sp_sorted["amp_20d_t1"].to_numpy(float)
        ptr = 0
        med_amp_by_dt = {}
        med_mktvol_by_dt = {}
        strat_vol_by_dt = {}
        for ti, dt in enumerate(cal_5y):
            while ptr < len(sp_sorted) and ex_dts[ptr] < dt:
                if np.isfinite(amp_arr[ptr]) and amp_arr[ptr] > 0:
                    amps_done.append(float(amp_arr[ptr]))
                strat_rets[st_arr[ptr]].append(float(nr_arr[ptr]))
                ptr += 1
            med_amp_by_dt[dt] = float(np.median(amps_done)) if len(amps_done) >= 15 else 6.0
            past_mvols = mkt_vol_20d[:ti]
            past_mvols = past_mvols[np.isfinite(past_mvols)]
            med_mktvol_by_dt[dt] = float(np.median(past_mvols)) if len(past_mvols) >= 20 else 0.015
            sv = {}
            all_sds = []
            for st_k, lst in strat_rets.items():
                if len(lst) >= 10:
                    sd_k = float(np.std(lst, ddof=1))
                    sv[st_k] = sd_k
                    all_sds.append(sd_k)
            med_sv = float(np.median(all_sds)) if all_sds else 0.12
            strat_vol_by_dt[dt] = (sv, med_sv)
        return med_amp_by_dt, med_mktvol_by_dt, strat_vol_by_dt

    med_amp_by_dt, med_mktvol_by_dt, strat_vol_by_dt = build_causal_vol_maps()

    # Slot fraction functions (strictly <= 1.0 total!)
    def frac_50_50(acc, n_slots, info):
        return [0.50] * len(acc)

    def frac_70_30_strict(acc, n_slots, info):
        # Main 70% + Sub 30% only when >= 2 signals trigger on day when both slots free
        if info["n_busy_existing"] == 0:
            if len(acc) >= 2:
                return [0.70, 0.30]
            return [0.70]
        # If 1 slot already busy, only open remaining 30% sub-slot if cash >= 0.25 and today's free slot isn't main
        # Wait: if existing busy is 70%, cash ~ 0.30; only fill sub-slot if >=2 signals triggered today
        n_sig_today = sum(1 for c in info["cand_rows"] if not c.is_untrig)
        return [0.30] if n_sig_today >= 2 else [0.0]

    def frac_solo100_multi70_30(acc, n_slots, info):
        if info["n_busy_existing"] == 0:
            if len(acc) >= 2:
                return [0.70, 0.30]
            return [1.00]
        return [0.0]  # Main slot already 100% or 70/30 handled

    def frac_solo100_multi50_50(acc, n_slots, info):
        if info["n_busy_existing"] == 0:
            if len(acc) >= 2:
                return [0.50, 0.50]
            return [1.00]
        return [0.0]

    def frac_mkt_vol_cap100(acc, n_slots, info):
        ti, dt = info["ti"], info["dt"]
        v = mkt_vol_20d[ti]
        if not np.isfinite(v) or v <= 1e-6:
            return [1.0] * len(acc)
        tgt = med_mktvol_by_dt[dt]
        w = float(np.clip(tgt / v, 0.35, 1.00))
        return [w] * len(acc)

    def frac_stock_amp_cap100(acc, n_slots, info):
        dt = info["dt"]
        med_a = med_amp_by_dt[dt]
        out = []
        for r in acc:
            a = getattr(r, "amp_20d_t1", np.nan)
            if pd.isna(a) or float(a) <= 0.5:
                out.append(1.0)
            else:
                out.append(float(np.clip(med_a / float(a), 0.40, 1.00)))
        return out

    def frac_strat_vol_cap100(acc, n_slots, info):
        dt = info["dt"]
        sv, med_sv = strat_vol_by_dt[dt]
        out = []
        for r in acc:
            v = sv.get(r.strategy, med_sv)
            out.append(float(np.clip(med_sv / max(0.02, v), 0.40, 1.00)))
        return out

    m2_specs = [
        ("M2_Slot1_100pct", "单仓100% V20.0基准", slot_pool, 1, None, 1),
        ("M2_Dual_50_50_PassPool", "50%/50% 双槽独立滚动(动态净值不超100%, 6策略各选1)", pass_pool, 2, frac_50_50, 1),
        ("M2_Dual_50_50_SameStrat2", "50%/50% 双槽独立滚动(允许同策略取第1+第2名)", pass_pool, 2, frac_50_50, 2),
        ("M2_Dual_50_50_SlotPool", "50%/50% 双槽独立滚动(基于独立槽候选池)", slot_pool, 2, frac_50_50, 1),
        ("M2_Main70_Sub30_MultiOnly", "70%主仓+30%副仓(仅>=2信号日开副仓, 单信号留30%现金)", pass_pool, 2, frac_70_30_strict, 1),
        ("M2_Solo100_Multi70_30", "单信号100% vs 多信号70%主+30%副(总仓位<=100%)", pass_pool, 2, frac_solo100_multi70_30, 1),
        ("M2_Solo100_Multi50_50", "单信号100% vs 多信号50%+50%(总仓位<=100%)", pass_pool, 2, frac_solo100_multi50_50, 1),
        ("M2_VolTarget_Mkt20d_Cap100", "动态市场波动率目标仓位(0.35~1.00, 严守<=100%)", slot_pool, 1, frac_mkt_vol_cap100, 1),
        ("M2_VolInv_StockAmp20d_Cap100", "动态个股20日振幅反比仓位(0.40~1.00, 严守<=100%)", slot_pool, 1, frac_stock_amp_cap100, 1),
        ("M2_VolInv_StratVol_Cap100", "动态策略历史波动率反比仓位(0.40~1.00, 严守<=100%)", slot_pool, 1, frac_strat_vol_cap100, 1),
    ]

    evals = {}
    csv_rows = []
    sims_m2 = {}
    for sid, desc, pool_x, nsl, ffn, mps in m2_specs:
        sim = w2c.simulate_multi_slot_mtm(
            pool_x, tier_rank_fn, cal_5y, idx_5y, n_slots=nsl,
            slot_frac_fn=ffn, untrig_df=ut_5y, timing_mode="s_tier_reserve_only",
            max_per_strat_per_day=mps,
        )
        ev = w2c.evaluate_portfolio_windows(sim["trades_df"], sim["dr_5y"], ctx, perm_n=1000)
        ev["desc"] = desc
        evals[sid] = ev
        sims_m2[sid] = sim
        csv_rows.append(_flatten_scheme_row("Module2_Slots", sid, desc, ev))

    # Also evaluate Fixed 50/50 Two Separate Subaccounts
    sim_fixed = _simulate_fixed_two_subaccounts(pass_pool, ut_5y, cal_5y, idx_5y)
    ev_fixed = w2c.evaluate_portfolio_windows(sim_fixed["trades_df"], sim_fixed["dr_5y"], ctx, perm_n=1000)
    ev_fixed["desc"] = "50%/50% 双独立子账户(初始各50%互不rebalance)"
    evals["M2_Dual_50_50_FixedHalf"] = ev_fixed
    csv_rows.append(_flatten_scheme_row("Module2_Slots", "M2_Dual_50_50_FixedHalf", ev_fixed["desc"], ev_fixed))

    # Truncation 2024-12-31 test on M2_VolInv_StockAmp20d_Cap100
    cutoff = "2024-12-31"
    cal_tr = [d for d in cal_5y if d <= cutoff]
    idx_tr = {d: i for i, d in enumerate(cal_tr)}
    slot_tr = slot_pool[slot_pool["buy_date"] <= cutoff].copy()
    ut_tr = ut_5y[ut_5y["buy_date"] <= cutoff].copy()
    sim_m2_tr = w2c.simulate_multi_slot_mtm(
        slot_tr, tier_rank_fn, cal_tr, idx_tr, n_slots=1,
        slot_frac_fn=frac_stock_amp_cap100, untrig_df=ut_tr, timing_mode="s_tier_reserve_only",
    )
    f_le = sims_m2["M2_VolInv_StockAmp20d_Cap100"]["trades_df"]
    f_le = f_le[f_le["exit_date"] <= cutoff].reset_index(drop=True)
    t_le = sim_m2_tr["trades_df"][sim_m2_tr["trades_df"]["exit_date"] <= cutoff].reset_index(drop=True)
    assert len(f_le) == len(t_le)
    w_diff = float(np.max(np.abs(f_le["alloc_weight"].to_numpy(float) - t_le["alloc_weight"].to_numpy(float)))) if len(f_le) else 0.0
    assert w_diff == 0.0, f"Module 2 truncation diff != 0: {w_diff}"

    return {
        "schemes": evals,
        "truncation_20241231_M2_VolAmp": {"n_trades_le_cutoff": int(len(f_le)), "max_abs_weight_diff": w_diff, "pass": w_diff == 0.0},
    }, csv_rows


def _group_stats(rets: np.ndarray) -> dict:
    if len(rets) == 0:
        return {"n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0, "median_pct": 0.0}
    w, l = rets[rets > 0], rets[rets <= 0]
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    return {
        "n": int(len(rets)),
        "wr_pct": round(float((rets > 0).mean() * 100.0), 2),
        "plr": round(plr, 2),
        "mean_pct": round(float(rets.mean() * 100.0), 2),
        "median_pct": round(float(np.median(rets) * 100.0), 2),
        "solo_nav": round(float(np.prod(1.0 + rets)), 4),
    }


def run_module3(ctx: dict) -> tuple[dict, list[dict]]:
    print("[Module 3] Auditing PM #4A Solo vs Resonance + Theme Overlap + Score Spread + Causal Tilts...")
    pass_pool = ctx["pass_pool_64"].copy()
    pass_pool = pass_pool[pass_pool["tier"] != "20cm_A(76-81)"].copy()
    tr_base = ctx["tr_base"].copy()
    cal_5y = ctx["cal_5y"]
    idx_5y = ctx["idx_5y"]
    slot_pool = ctx["slot_pool_64"]
    ut_5y = ctx["untrig_base"][ctx["untrig_base"]["buy_date"].between("2021-11-16", "2026-11-16")].copy()

    # Daily resonance profile from pass_pool (excluding 20cm_A)
    day_profile = {}
    for dt, grp in pass_pool.groupby("buy_date"):
        n_cands = len(grp)
        n_strats = grp["strategy"].nunique()
        strats_set = set(grp["strategy"].unique())
        # Same KPL plate across >= 2 distinct strategies
        kpl_map = defaultdict(set)
        ind_map = defaultdict(set)
        for r in grp.itertuples(index=False):
            kp = str(r.kpl_plate_t1).strip()
            if kp and kp not in ("", "其他", "nan", "None"):
                kpl_map[kp].add(r.strategy)
            ci = r.csrc_ind_id
            if pd.notna(ci):
                ind_map[int(ci)].add(r.strategy)
        same_kpl_res = any(len(v) >= 2 for v in kpl_map.values())
        same_ind_res = any(len(v) >= 2 for v in ind_map.values())
        day_profile[dt] = {
            "n_cands": int(n_cands),
            "n_strats": int(n_strats),
            "same_kpl_res": bool(same_kpl_res),
            "same_ind_res": bool(same_ind_res),
            "strats": sorted(list(strats_set)),
        }

    # 3A. Audit on ALL passing candidates (ranked 1 per day by S2C) AND on V20.0 278 executed trades
    pass_pool["prio"] = pass_pool["tier"].map(w2c.CANON_S2C_TIER_MAP).fillna(999).astype(int)
    pass_top1 = pass_pool.sort_values(["buy_date", "prio", "score", "buy_hhmm", "code"], ascending=[True, True, False, True, True]).groupby("buy_date", as_index=False).first()

    def _audit_resonance_buckets(df_in: pd.DataFrame, label: str) -> dict:
        buckets = defaultdict(list)
        for r in df_in.itertuples(index=False):
            dp = day_profile.get(r.buy_date, {"n_cands": 1, "n_strats": 1, "same_kpl_res": False, "same_ind_res": False})
            nr = float(r.net_ret)
            if dp["n_strats"] == 1 and dp["n_cands"] == 1:
                buckets["1_solo_1strat_1cand"].append(nr)
            elif dp["n_strats"] == 1 and dp["n_cands"] >= 2:
                buckets["2_solo_1strat_multi_cands"].append(nr)
            elif dp["n_strats"] == 2:
                buckets["3_resonance_2strats"].append(nr)
            else:
                buckets["4_resonance_ge3strats"].append(nr)

            if dp["n_strats"] == 1:
                buckets["agg_1strat"].append(nr)
            else:
                buckets["agg_ge2strats"].append(nr)
                if dp["same_kpl_res"]:
                    buckets["multi_same_kpl_theme"].append(nr)
                else:
                    buckets["multi_diff_kpl_theme"].append(nr)
                if dp["same_ind_res"]:
                    buckets["multi_same_csrc_ind"].append(nr)
                else:
                    buckets["multi_diff_csrc_ind"].append(nr)

        res = {k: _group_stats(np.asarray(v, float)) for k, v in sorted(buckets.items())}
        a1 = np.asarray(buckets["agg_1strat"], float)
        a2 = np.asarray(buckets["agg_ge2strats"], float)
        if len(a1) > 5 and len(a2) > 5:
            t_v, p_v = stats.ttest_ind(a1, a2, equal_var=False)
            res["ttest_solo_vs_multi"] = {"t_stat": round(float(t_v), 3), "p_val": round(float(p_v), 4)}
        return res

    audit_all_top1 = _audit_resonance_buckets(pass_top1, "daily_top1_all_pass_days")
    audit_v20_278 = _audit_resonance_buckets(tr_base, "v20_executed_278")
    audit_v20_is = _audit_resonance_buckets(tr_base[tr_base["buy_date"] <= "2024-12-31"], "v20_is")
    audit_v20_oos = _audit_resonance_buckets(tr_base[tr_base["buy_date"] >= "2025-01-01"], "v20_oos")

    # 3B. Rank 1 vs Rank 2 Score Spread (Within-Strategy + Cross-Strategy Causal Expected Return Spread)
    spread_stats = {}
    # Within same strategy where >= 2 passing cands on same day (excluding pry crash days with 278 rows or include cleanly)
    same_strat_spreads = []
    for (st, bd), grp in pass_pool.groupby(["strategy", "buy_date"]):
        if len(grp) < 2:
            continue
        gs = grp.sort_values(["score", "code"], ascending=[False, True])
        r1, r2 = gs.iloc[0], gs.iloc[1]
        same_strat_spreads.append({
            "strategy": st, "buy_date": bd, "gap": float(r1["score"] - r2["score"]),
            "r1_ret": float(r1["net_ret"]), "r2_ret": float(r2["net_ret"]),
        })
    sdf = pd.DataFrame(same_strat_spreads)
    if not sdf.empty:
        # Normalize gap per strategy by median gap
        med_gaps = sdf.groupby("strategy")["gap"].transform("median")
        wide = sdf[sdf["gap"] >= med_gaps]
        tight = sdf[sdf["gap"] < med_gaps]
        spread_stats["same_strat_multi_cands"] = {
            "n_pairs": int(len(sdf)),
            "wide_lead_r1": _group_stats(wide["r1_ret"].to_numpy(float)),
            "wide_lead_r2": _group_stats(wide["r2_ret"].to_numpy(float)),
            "tight_tie_r1": _group_stats(tight["r1_ret"].to_numpy(float)),
            "tight_tie_r2": _group_stats(tight["r2_ret"].to_numpy(float)),
        }

    # Cross-strategy Rank 1 vs Rank 2 causal expected return gap (using exit_date < t)
    sp_ex = slot_pool.sort_values(["exit_date", "buy_date"]).reset_index(drop=True)
    ex_d = sp_ex["exit_date"].to_numpy()
    st_ex = sp_ex["strategy"].to_numpy()
    nr_ex = sp_ex["net_ret"].to_numpy(float)
    st_hist = defaultdict(list)
    ptr = 0
    causal_strat_mu = {}
    for dt in cal_5y:
        while ptr < len(sp_ex) and ex_d[ptr] < dt:
            st_hist[st_ex[ptr]].append(float(nr_ex[ptr]))
            ptr += 1
        causal_strat_mu[dt] = {s: (float(np.mean(v)) if len(v) >= 5 else 0.05) for s, v in st_hist.items()}

    cross_spreads = []
    for bd, grp in pass_pool.groupby("buy_date"):
        if grp["strategy"].nunique() < 2:
            continue
        gs = grp.sort_values(["prio", "score", "code"], ascending=[True, False, True]).drop_duplicates("strategy", keep="first")
        if len(gs) < 2:
            continue
        r1, r2 = gs.iloc[0], gs.iloc[1]
        mu_map = causal_strat_mu.get(bd, {})
        gap_mu = abs(mu_map.get(r1["strategy"], 0.05) - mu_map.get(r2["strategy"], 0.05))
        cross_spreads.append({"buy_date": bd, "gap_mu": gap_mu, "r1_ret": float(r1["net_ret"]), "r2_ret": float(r2["net_ret"])})
    cdf = pd.DataFrame(cross_spreads)
    if not cdf.empty:
        mg = float(cdf["gap_mu"].median())
        cw, ct = cdf[cdf["gap_mu"] >= mg], cdf[cdf["gap_mu"] < mg]
        spread_stats["cross_strat_multi_cands"] = {
            "n_pairs": int(len(cdf)), "median_causal_er_gap_pct": round(mg * 100.0, 2),
            "wide_lead_r1": _group_stats(cw["r1_ret"].to_numpy(float)),
            "wide_lead_r2": _group_stats(cw["r2_ret"].to_numpy(float)),
            "tight_tie_r1": _group_stats(ct["r1_ret"].to_numpy(float)),
            "tight_tie_r2": _group_stats(ct["r2_ret"].to_numpy(float)),
        }

    # 3C. Causal Resonance Position Tilt Backtests
    # Build causal solo vs multi mean history (exit_date < t)
    tr_sorted = tr_base.sort_values(["exit_date", "buy_date"]).reset_index(drop=True)
    tr_ex = tr_sorted["exit_date"].to_numpy()
    tr_bd = tr_sorted["buy_date"].to_numpy()
    tr_nr = tr_sorted["net_ret"].to_numpy(float)
    solo_rets_h, multi_rets_h = [], []
    ptr_t = 0
    causal_solo_vs_multi_w = {}
    for dt in cal_5y:
        while ptr_t < len(tr_sorted) and tr_ex[ptr_t] < dt:
            dp = day_profile.get(tr_bd[ptr_t], {"n_strats": 1})
            if dp["n_strats"] == 1:
                solo_rets_h.append(float(tr_nr[ptr_t]))
            else:
                multi_rets_h.append(float(tr_nr[ptr_t]))
            ptr_t += 1
        if len(solo_rets_h) >= 10 and len(multi_rets_h) >= 10:
            ms, mm = float(np.mean(solo_rets_h)), float(np.mean(multi_rets_h))
            w_s = 1.0 if ms >= mm else 0.60
            w_m = 1.0 if mm >= ms else 0.60
            causal_solo_vs_multi_w[dt] = (w_s, w_m)
        else:
            causal_solo_vs_multi_w[dt] = (1.0, 1.0)

    def _tier_fn(d):
        out = d.copy()
        out["prio"] = out["tier"].map(w2c.CANON_S2C_TIER_MAP).fillna(999).astype(int)
        return out

    def _tilt_fn(w_solo: float, w_multi: float):
        def fn(acc, n_slots, info):
            dp = day_profile.get(info["dt"], {"n_strats": 1})
            w = w_solo if dp["n_strats"] == 1 else w_multi
            return [w] * len(acc)
        return fn

    def _tilt_causal_fn(acc, n_slots, info):
        dp = day_profile.get(info["dt"], {"n_strats": 1})
        ws, wm = causal_solo_vs_multi_w.get(info["dt"], (1.0, 1.0))
        return [ws if dp["n_strats"] == 1 else wm] * len(acc)

    m3_specs = [
        ("M3_Tilt_Solo50_Res100", "独苗日半仓50% + 共振日满仓100%", _tilt_fn(0.50, 1.00)),
        ("M3_Tilt_Solo70_Res100", "独苗日70% + 共振日满仓100%", _tilt_fn(0.70, 1.00)),
        ("M3_Tilt_Solo100_Res50", "独苗日满仓100% + 共振日半仓50%(防拥挤)", _tilt_fn(1.00, 0.50)),
        ("M3_Tilt_Solo100_Res70", "独苗日满仓100% + 共振日70%(防拥挤)", _tilt_fn(1.00, 0.70)),
        ("M3_Tilt_Causal_60_100", "逐日前视镜(exit_date<t)动态独苗vs共振倾斜(60%/100%)", _tilt_causal_fn),
    ]

    evals_m3 = {}
    csv_rows = []
    for sid, desc, ffn in m3_specs:
        sim = w2c.simulate_multi_slot_mtm(
            slot_pool, _tier_fn, cal_5y, idx_5y, n_slots=1,
            slot_frac_fn=ffn, untrig_df=ut_5y, timing_mode="s_tier_reserve_only",
        )
        ev = w2c.evaluate_portfolio_windows(sim["trades_df"], sim["dr_5y"], ctx, perm_n=1000)
        ev["desc"] = desc
        evals_m3[sid] = ev
        csv_rows.append(_flatten_scheme_row("Module3_Resonance", sid, desc, ev))

    return {
        "daily_top1_all_pass_days": audit_all_top1,
        "v20_executed_278": audit_v20_278,
        "v20_is": audit_v20_is,
        "v20_oos": audit_v20_oos,
        "rank1_vs_rank2_score_spread": spread_stats,
        "tilt_schemes": evals_m3,
    }, csv_rows


def run_module5(ctx: dict) -> tuple[dict, list[dict]]:
    print("[Module 5] Auditing Equity Curve Reflexivity (Post-Loss / Post-Win Streaks + Causal Sizing)...")
    tr_base = ctx["tr_base"].sort_values(["buy_date", "buy_hhmm", "code"]).reset_index(drop=True)
    cal_5y = ctx["cal_5y"]
    idx_5y = ctx["idx_5y"]
    slot_pool = ctx["slot_pool_64"]
    ut_5y = ctx["untrig_base"][ctx["untrig_base"]["buy_date"].between("2021-11-16", "2026-11-16")].copy()

    def _streak_audit(df_tr: pd.DataFrame) -> dict:
        rets = df_tr["net_ret"].to_numpy(float)
        if len(rets) < 10:
            return {"n": int(len(rets))}
        wins = (rets > 0).astype(int)
        # Note: in single-slot, trade k-1 exited strictly before trade k entered!
        loss_streak = np.zeros(len(rets), dtype=int)
        win_streak = np.zeros(len(rets), dtype=int)
        roll5_mean = np.full(len(rets), np.nan)
        roll10_mean = np.full(len(rets), np.nan)
        cl, cw = 0, 0
        for i in range(len(rets)):
            loss_streak[i] = cl
            win_streak[i] = cw
            if i >= 5:
                roll5_mean[i] = float(np.mean(rets[i - 5:i]))
            if i >= 10:
                roll10_mean[i] = float(np.mean(rets[i - 10:i]))
            if rets[i] > 0:
                cw += 1
                cl = 0
            else:
                cl += 1
                cw = 0

        r_corr_1, p_corr_1 = stats.pearsonr(rets[1:], rets[:-1])
        w_corr_1, wp_corr_1 = stats.pearsonr(wins[1:], wins[:-1])
        buckets = {
            "unconditional": _group_stats(rets),
            "after_L1_exact": _group_stats(rets[loss_streak == 1]),
            "after_L2_ge2": _group_stats(rets[loss_streak >= 2]),
            "after_L3_ge3": _group_stats(rets[loss_streak >= 3]),
            "after_W1_exact": _group_stats(rets[win_streak == 1]),
            "after_W2_exact": _group_stats(rets[win_streak == 2]),
            "after_W3_ge3": _group_stats(rets[win_streak >= 3]),
            "after_W4_ge4": _group_stats(rets[win_streak >= 4]),
            "after_hot_roll5_gt_8pct": _group_stats(rets[np.isfinite(roll5_mean) & (roll5_mean >= 0.08)]),
            "after_cold_roll5_lt_0pct": _group_stats(rets[np.isfinite(roll5_mean) & (roll5_mean < 0.0)]),
            "after_hot_roll10_gt_8pct": _group_stats(rets[np.isfinite(roll10_mean) & (roll10_mean >= 0.08)]),
            "after_cold_roll10_lt_3pct": _group_stats(rets[np.isfinite(roll10_mean) & (roll10_mean < 0.03)]),
        }
        return {
            "n": int(len(rets)),
            "lag1_ret_corr": round(float(r_corr_1), 4), "lag1_ret_p": round(float(p_corr_1), 4),
            "lag1_win_corr": round(float(w_corr_1), 4), "lag1_win_p": round(float(wp_corr_1), 4),
            "buckets": buckets,
        }

    audit = {
        "v20_combined_5y": _streak_audit(tr_base),
        "v20_combined_wf_2023_2026": _streak_audit(tr_base[tr_base["buy_date"] >= "2023-01-03"]),
        "v20_combined_is_2021_2024": _streak_audit(tr_base[tr_base["buy_date"] <= "2024-12-31"]),
        "v20_combined_oos_2025_2026": _streak_audit(tr_base[tr_base["buy_date"] >= "2025-01-01"]),
        "by_standalone_strategy": {
            st: _streak_audit(slot_pool[slot_pool["strategy"] == st].sort_values(["buy_date", "code"]))
            for st in w2c.STRAT_ORDER
        },
    }

    # Precompute causal streak state per buy_date strictly from closed trades exit_date < t
    tr_ex_s = tr_base.sort_values(["exit_date", "buy_date"]).reset_index(drop=True)
    ex_dts = tr_ex_s["exit_date"].to_numpy()
    nr_ex = tr_ex_s["net_ret"].to_numpy(float)
    ptr = 0
    cl_cur, cw_cur = 0, 0
    eq_hist, pk_hist = 1.0, 1.0
    streak_by_dt = {}
    for dt in cal_5y:
        while ptr < len(tr_ex_s) and ex_dts[ptr] < dt:
            r = float(nr_ex[ptr])
            eq_hist *= (1.0 + r)
            pk_hist = max(pk_hist, eq_hist)
            if r > 0:
                cw_cur += 1
                cl_cur = 0
            else:
                cl_cur += 1
                cw_cur = 0
            ptr += 1
        dd_cur = (pk_hist - eq_hist) / pk_hist * 100.0
        streak_by_dt[dt] = (cl_cur, cw_cur, dd_cur)

    def _tier_fn(d):
        out = d.copy()
        out["prio"] = out["tier"].map(w2c.CANON_S2C_TIER_MAP).fillna(999).astype(int)
        return out

    def _reflex_frac(rule_type: str):
        def fn(acc, n_slots, info):
            cl, cw, dd = streak_by_dt.get(info["dt"], (0, 0, 0.0))
            if rule_type == "half_L2":
                w = 0.50 if cl >= 2 else 1.0
            elif rule_type == "half_L3":
                w = 0.50 if cl >= 3 else 1.0
            elif rule_type == "half_W3":
                w = 0.50 if cw >= 3 else 1.0
            elif rule_type == "half_DD15":
                w = 0.50 if dd >= 15.0 else 1.0
            else:
                w = 1.0
            return [w] * len(acc)
        return fn

    m5_specs = [
        ("M5_Half_After_L2", "反身性减半: 刚连亏>=2笔后下一笔半仓50%", "half_L2"),
        ("M5_Half_After_L3", "反身性减半: 刚连亏>=3笔后下一笔半仓50%", "half_L3"),
        ("M5_Half_After_W3", "逆向止盈减半: 刚连赢>=3笔后下一笔半仓50%", "half_W3"),
        ("M5_Half_In_DD15", "回撤保护: 已平仓净值回撤>=15%时半仓50%", "half_DD15"),
    ]
    evals_m5 = {}
    csv_rows = []
    for sid, desc, rtype in m5_specs:
        sim = w2c.simulate_multi_slot_mtm(
            slot_pool, _tier_fn, cal_5y, idx_5y, n_slots=1,
            slot_frac_fn=_reflex_frac(rtype), untrig_df=ut_5y, timing_mode="s_tier_reserve_only",
        )
        ev = w2c.evaluate_portfolio_windows(sim["trades_df"], sim["dr_5y"], ctx, perm_n=1000)
        ev["desc"] = desc
        evals_m5[sid] = ev
        csv_rows.append(_flatten_scheme_row("Module5_Reflexivity", sid, desc, ev))

    return {"statistical_audit": audit, "sizing_schemes": evals_m5}, csv_rows


def _flatten_scheme_row(module: str, sid: str, desc: str, ev: dict) -> dict:
    w = ev["windows"]
    w5 = w["Y5"]
    wf = w["WF_2023_2026"]
    wo = w["Y2025_2026"]
    wy = w["Y2026"]
    wi = w["IS_2021_2024"]
    p5 = ev.get("perm_5y", {})
    pw = ev.get("perm_wf", {})
    return {
        "module": module,
        "scheme_id": sid,
        "desc": desc,
        "n_5y": w5["n"], "wr_5y_pct": w5["wr_pct"], "plr_5y": w5["plr"], "mean_5y_pct": w5["mean_pct"],
        "nav_5y": w5["nav"], "mtm_nav_5y": w5["mtm_nav"], "ex5_5y": w5["ex_top5_nav"],
        "mdd_5y_pct": w5["daily_mdd_pct"], "sharpe_5y": w5["daily_sharpe"], "calmar_5y": w5["daily_calmar"],
        "excess_csi_5y_pp": w5["excess_csi300_pp"], "perm_sd_p_5y": p5.get("same_day_p_nav"), "perm_any_p_5y": p5.get("any_cand_day_p_nav"),
        "n_wf": wf["n"], "nav_wf": wf["nav"], "ex5_wf": wf["ex_top5_nav"],
        "mdd_wf_pct": wf["daily_mdd_pct"], "sharpe_wf": wf["daily_sharpe"], "calmar_wf": wf["daily_calmar"],
        "excess_csi_wf_pp": wf["excess_csi300_pp"], "perm_sd_p_wf": pw.get("same_day_p_nav"),
        "n_is": wi["n"], "nav_is": wi["nav"], "sharpe_is": wi["daily_sharpe"],
        "n_2526": wo["n"], "nav_2526": wo["nav"], "ex5_2526": wo["ex_top5_nav"],
        "mdd_2526_pct": wo["daily_mdd_pct"], "sharpe_2526": wo["daily_sharpe"], "calmar_2526": wo["daily_calmar"],
        "excess_csi_2526_pp": wo["excess_csi300_pp"],
        "n_2026": wy["n"], "nav_2026": wy["nav"], "ex5_2026": wy["ex_top5_nav"],
        "mdd_2026_pct": wy["daily_mdd_pct"], "sharpe_2026": wy["daily_sharpe"], "calmar_2026": wy["daily_calmar"],
        "excess_csi_2026_pp": wy["excess_csi300_pp"],
    }


def main():
    t0 = time.time()
    ctx = w2c.load_w2a6_context()
    m1_res, m1_rows = run_module1(ctx)
    m2_res, m2_rows = run_module2(ctx)
    m3_res, m3_rows = run_module3(ctx)
    m5_res, m5_rows = run_module5(ctx)

    all_rows = m1_rows + m2_rows + m3_rows + m5_rows
    df_cmp = pd.DataFrame(all_rows)
    cmp_csv = f"{OUT_DIR}/w2a6_part1_compare.csv"
    df_cmp.to_csv(cmp_csv, index=False, encoding="utf-8-sig")

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024.0 * 1024.0), 2)
    payload = w2c.sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "peak_rss_mb": rss_mb,
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "baseline_parity": ctx["parity_info"],
        "module1_priority": m1_res,
        "module2_slots": m2_res,
        "module3_resonance": m3_res,
        "module5_reflexivity": m5_res,
    })
    out_json = f"{OUT_DIR}/_part1_results.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)

    print(f"[PART 1 DONE in {time.time()-t0:.2f}s | RSS={rss_mb}MB] -> {out_json}")
    print(df_cmp[["scheme_id", "n_5y", "nav_5y", "mdd_5y_pct", "sharpe_5y", "calmar_5y", "nav_wf", "nav_2526", "nav_2026"]].to_string(index=False))


if __name__ == "__main__":
    main()

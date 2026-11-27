#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Pillar 2 - Step 1: Full-Pool & Portfolio-Level Forensic Audit of RD049 False Kills.
Zero yfinance (D12). Read-only on V20/V21/RD038/RD049. All metrics at 30bps.
"""
import gc
import json
import math
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
OUT_DIR = f"{SIM}/backtests_astock/v22_grand_convergence_20261126/p2_rd049_falsekill_audit"
os.makedirs(OUT_DIR, exist_ok=True)

for p in (RD038, RD049):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd038_engine as eng
import _rd049_common as cm

VARIANTS = [
    ("BASE", dict(mode="base")),
    ("S1_SkipYellow34", dict(mode="skip_yellow", pry_cold=True)),
    ("S3_RD049_Tier_Full", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=True)),
    ("S4_RD049_R2D_Full", dict(mode="runion", r0=38, rk=12, raf=45, af03_weak=True, pry_cold=True)),
    ("S5_RD049_Tier_NoPry", dict(mode="tier", d_l4=12, d_l3=9, d_l2=9, af03_weak=True, pry_cold=False)),
    ("M3_OnlyAf03_Weak", dict(mode="base", af03_weak=True, pry_cold=False)),
]

YEAR_WINDOWS = [
    ("2021", "2021-11-16", "2021-12-31"),
    ("2022", "2022-01-01", "2022-12-31"),
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("2026H1", "2026-01-01", "2026-06-30"),
    ("2026H2", "2026-07-01", "2026-11-16"),
    ("2026_FULL", "2026-01-01", "2026-11-16"),
]


def sanitize(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return sanitize(obj.tolist())
    return obj


def bootstrap_diff_test(kept_rets: np.ndarray, blk_rets: np.ndarray, n_boot: int = 10000, seed: int = 20261126) -> dict:
    """Two-sample bootstrap & permutation test on kept vs blocked mean return and win rate."""
    if len(kept_rets) == 0 or len(blk_rets) == 0:
        return {}
    rng = np.random.default_rng(seed)
    obs_mean_diff = float(np.mean(kept_rets) - np.mean(blk_rets))
    obs_wr_diff = float(np.mean(kept_rets > 0) - np.mean(blk_rets > 0))
    # Bootstrap CIs for mean_diff and wr_diff
    k_idx = rng.integers(0, len(kept_rets), size=(n_boot, len(kept_rets)))
    b_idx = rng.integers(0, len(blk_rets), size=(n_boot, len(blk_rets)))
    bk = kept_rets[k_idx]
    bb = blk_rets[b_idx]
    boot_mean_diff = bk.mean(axis=1) - bb.mean(axis=1)
    boot_wr_diff = (bk > 0).mean(axis=1) - (bb > 0).mean(axis=1)
    # Permutation p-value under H0: kept == blocked
    pooled = np.concatenate([kept_rets, blk_rets])
    nk = len(kept_rets)
    perm_mean_ge = 0
    perm_wr_ge = 0
    for _ in range(n_boot):
        perm = rng.permutation(pooled)
        pk, pb = perm[:nk], perm[nk:]
        if (pk.mean() - pb.mean()) >= obs_mean_diff - 1e-12:
            perm_mean_ge += 1
        if ((pk > 0).mean() - (pb > 0).mean()) >= obs_wr_diff - 1e-12:
            perm_wr_ge += 1
    return {
        "obs_mean_diff_pp": round(obs_mean_diff * 100.0, 2),
        "boot_mean_diff_ci95_pp": [round(float(np.percentile(boot_mean_diff, 2.5) * 100.0), 2), round(float(np.percentile(boot_mean_diff, 97.5) * 100.0), 2)],
        "perm_p_mean_1sided": round((perm_mean_ge + 1) / (n_boot + 1), 4),
        "obs_wr_diff_pp": round(obs_wr_diff * 100.0, 2),
        "boot_wr_diff_ci95_pp": [round(float(np.percentile(boot_wr_diff, 2.5) * 100.0), 2), round(float(np.percentile(boot_wr_diff, 97.5) * 100.0), 2)],
        "perm_p_wr_1sided": round((perm_wr_ge + 1) / (n_boot + 1), 4),
    }


def summarize_subset(df: pd.DataFrame, ret_col: str = "net_ret_030") -> dict:
    if df.empty:
        return {"n": 0, "wr_pct": 0.0, "mean_pct": 0.0, "median_pct": 0.0, "solo_nav": 1.0, "n_mines": 0, "mine_avg_pct": 0.0, "n_winners": 0, "winner_avg_pct": 0.0, "n_ge15": 0, "n_ge30": 0}
    r = df[ret_col].to_numpy(float)
    losers = r[r <= 0]
    winners = r[r > 0]
    return {
        "n": int(len(r)),
        "wr_pct": round(float((r > 0).mean() * 100.0), 2),
        "mean_pct": round(float(r.mean() * 100.0), 2),
        "median_pct": round(float(np.median(r) * 100.0), 2),
        "solo_nav": round(float(np.prod(1.0 + r)), 4),
        "n_mines": int(len(losers)),
        "mine_avg_pct": round(float(losers.mean() * 100.0), 2) if len(losers) else 0.0,
        "worst_mine_pct": round(float(losers.min() * 100.0), 2) if len(losers) else 0.0,
        "n_winners": int(len(winners)),
        "winner_avg_pct": round(float(winners.mean() * 100.0), 2) if len(winners) else 0.0,
        "best_winner_pct": round(float(winners.max() * 100.0), 2) if len(winners) else 0.0,
        "n_ge15": int((r >= 0.15).sum()),
        "n_ge30": int((r >= 0.30).sum()),
    }


def decompose_episodes(tr_b: pd.DataFrame, tr_v: pd.DataFrame):
    """Split divergence between baseline and variant ledgers into exact disjoint episodes."""
    b_list = tr_b.sort_values("buy_date").to_dict("records")
    v_list = tr_v.sort_values("buy_date").to_dict("records")
    ib, iv = 0, 0
    episodes = []
    while ib < len(b_list) or iv < len(v_list):
        if ib < len(b_list) and iv < len(v_list):
            rb, rv = b_list[ib], v_list[iv]
            if (rb["buy_date"], rb["code"], rb["strategy"], rb["exit_date"], int(rb["exit_hhmm"])) == (
                rv["buy_date"], rv["code"], rv["strategy"], rv["exit_date"], int(rv["exit_hhmm"])
            ):
                ib += 1
                iv += 1
                continue
        b_ep, v_ep = [], []
        while True:
            if ib < len(b_list) and iv < len(v_list) and (len(b_ep) > 0 or len(v_ep) > 0):
                rb, rv = b_list[ib], v_list[iv]
                if (rb["buy_date"], rb["code"], rb["strategy"], rb["exit_date"], int(rb["exit_hhmm"])) == (
                    rv["buy_date"], rv["code"], rv["strategy"], rv["exit_date"], int(rv["exit_hhmm"])
                ):
                    break
            if ib >= len(b_list) and iv >= len(v_list):
                break
            if ib < len(b_list) and (iv >= len(v_list) or (b_list[ib]["buy_date"], int(b_list[ib]["buy_hhmm"])) <= (v_list[iv]["buy_date"], int(v_list[iv]["buy_hhmm"]))):
                b_ep.append(b_list[ib])
                ib += 1
            else:
                v_ep.append(v_list[iv])
                iv += 1
        episodes.append((b_ep, v_ep))
    return episodes


def main():
    t0 = time.time()
    print("[1/4] Loading RD038 master cache & RD049 T-1 regime table ...")
    with open(f"{RD038}/_cache/rd038_master_cache.pkl", "rb") as f:
        cache = pickle.load(f)
    reg = pd.read_parquet(f"{RD049}/_cache/rd049_daily_regime_pit.parquet")
    reg2 = cm.build_2d_states(reg, y_cut=42.0, x_sh=20.0, x_dp=42.0)
    reg_idx = reg2.set_index("trade_date")
    cal_5y = cache["cal_5y"]

    # Map regime lookups
    lmap = reg_idx["light_5"].to_dict()
    xmap = reg_idx["X_score"].to_dict()
    ymap = reg_idx["Y_score"].to_dict()
    rmap = reg_idx["R_union"].to_dict()
    redmap = reg_idx["is_red_floor"].to_dict()
    dtmap = reg_idx["dt_cnt_t1"].to_dict()

    # Run all variants on V21 and V20
    print("[2/4] Running BASE + 5 RD049 variants on V21 & V20 (30bps) ...")
    sims = {"V21": {}, "V20": {}}
    filtered_caches = {}
    for vname, kw in VARIANTS:
        cf = cm.apply_rd049_filter(cache, reg_idx, **kw)
        filtered_caches[vname] = cf
        for bname, cfg in [("V21", cm.CFG_V21), ("V20", cm.CFG_V20)]:
            sim = eng.run_bundle_sim(cf, cfg, fee_mode="030")
            rel_diff = sim["mtm_diff_5y"] / max(1.0, float(np.prod(1.0 + sim["dr_5y"])))
            assert rel_diff < 1e-10, f"MTM mismatch {bname}_{vname}: {rel_diff}"
            sims[bname][vname] = sim

    # Helper to find what was held in BASE on a given date
    def held_str(tr_df: pd.DataFrame, dt: str) -> str:
        sub = tr_df[(tr_df["buy_date"] <= dt) & (tr_df["exit_date"] >= dt)]
        if sub.empty:
            return "FREE"
        return "; ".join([f"{r.strategy}:{r.code}{r.name}({r.buy_date}->{r.exit_date},{r.net_ret*100:+.2f}%)" for r in sub.itertuples()])

    # ------------------------------------------------------------------
    # VIEW A: 3to4 Full Pool + PRY Full Pool Forensic CSV & Stats
    # ------------------------------------------------------------------
    print("[3/4] Building Perspective A (Full Pool 3to4 & PRY false-kill tables) ...")
    d34 = cache["pools_ext"]["3to4"].copy()
    d34["v21_m4_pass"] = cache["other5_variants"]["3to4"]["m4_4way_bl15"]["mask"]
    b34 = d34[d34["can_buy_hygiene"] & (d34["orig_score"] >= 90.0) & d34["buy_date"].between("2021-11-16", "2026-11-16")].copy()
    b34["light_5"] = b34["buy_date"].map(lmap)
    b34["X_score"] = b34["buy_date"].map(xmap)
    b34["Y_score"] = b34["buy_date"].map(ymap)
    b34["R_union"] = b34["buy_date"].map(rmap)
    b34["is_red_floor"] = b34["buy_date"].map(redmap)
    b34["dt_cnt_t1"] = b34["buy_date"].map(dtmap)

    tr21_base = sims["V21"]["BASE"]["trades_df"]
    tr20_base = sims["V20"]["BASE"]["trades_df"]
    v21_34_keys = set(zip(tr21_base[tr21_base["strategy"] == "3to4"]["buy_date"], tr21_base[tr21_base["strategy"] == "3to4"]["code"]))
    v20_34_keys = set(zip(tr20_base[tr20_base["strategy"] == "3to4"]["buy_date"], tr20_base[tr20_base["strategy"] == "3to4"]["code"]))
    b34["in_v21_base_portfolio"] = [((r.buy_date, str(r.code).zfill(6)) in v21_34_keys) for r in b34.itertuples()]
    b34["in_v20_base_portfolio"] = [((r.buy_date, str(r.code).zfill(6)) in v20_34_keys) for r in b34.itertuples()]
    b34["v21_base_slot_on_day"] = [held_str(tr21_base, r.buy_date) for r in b34.itertuples()]
    b34["v20_base_slot_on_day"] = [held_str(tr20_base, r.buy_date) for r in b34.itertuples()]

    # Standalone 3to4 single-slot baseline keys (V20 & V21)
    _, sl34_v20 = eng.cm.sim_strategy("3to4", cache["pools_ext"]["3to4"], cache["pools_ext"]["3to4"]["orig_score"].to_numpy(float), wf_only=False)
    sl34_v20 = sl34_v20[sl34_v20["buy_date"].between("2021-11-16", "2026-11-16")]
    sl34_v20_keys = set(zip(sl34_v20["buy_date"], sl34_v20["code"]))
    b34["in_3to4_standalone_slot"] = [((r.buy_date, str(r.code).zfill(6)) in sl34_v20_keys) for r in b34.itertuples()]

    view_a_stats = {"V20_pool_n115": {}, "V21_m4_pool_n107": {}, "V20_standalone_slot": {}}
    for vname, _ in VARIANTS[1:]:
        k34 = filtered_caches[vname]["pools_ext"]["3to4"]["can_buy_hygiene"].to_numpy(bool)
        b34[f"keep_{vname}"] = k34[b34.index]
        b34[f"blocked_{vname}"] = ~b34[f"keep_{vname}"]

        # Stats on full V20 pool (n=115)
        blk = b34[b34[f"blocked_{vname}"]]
        kp = b34[b34[f"keep_{vname}"]]
        view_a_stats["V20_pool_n115"][vname] = {
            "blocked": summarize_subset(blk),
            "kept": summarize_subset(kp),
            "false_kill_rate_pct": round(float((blk["net_ret_030"] > 0).mean() * 100.0), 2) if len(blk) else 0.0,
            "bootstrap_kept_vs_blocked": bootstrap_diff_test(kp["net_ret_030"].to_numpy(float), blk["net_ret_030"].to_numpy(float)),
            "big_winners_ge15": [
                {"buy_date": r.buy_date, "code": r.code, "name": r.name, "score": float(r.orig_score), "af03": int(r.s34_af_03), "light_5": r.light_5, "ret_pct": round(float(r.net_ret_030 * 100), 2), "pos750": round(float(r.L3_pos_750d_t1), 3), "in_v21_base": bool(r.in_v21_base_portfolio), "in_v20_base": bool(r.in_v20_base_portfolio)}
                for r in blk[blk["net_ret_030"] >= 0.15].sort_values("net_ret_030", ascending=False).itertuples()
            ],
        }
        # Stats on V21 m4-passing pool (n=107)
        b34_m4 = b34[b34["v21_m4_pass"]]
        blk_m4 = b34_m4[b34_m4[f"blocked_{vname}"]]
        kp_m4 = b34_m4[b34_m4[f"keep_{vname}"]]
        view_a_stats["V21_m4_pool_n107"][vname] = {
            "blocked": summarize_subset(blk_m4),
            "kept": summarize_subset(kp_m4),
            "false_kill_rate_pct": round(float((blk_m4["net_ret_030"] > 0).mean() * 100.0), 2) if len(blk_m4) else 0.0,
            "bootstrap_kept_vs_blocked": bootstrap_diff_test(kp_m4["net_ret_030"].to_numpy(float), blk_m4["net_ret_030"].to_numpy(float)),
        }
        # Standalone 3to4 single-slot stats
        df34_v = filtered_caches[vname]["pools_ext"]["3to4"]
        _, sl_v = eng.cm.sim_strategy("3to4", df34_v, df34_v["orig_score"].to_numpy(float), wf_only=False)
        sl_v = sl_v[sl_v["buy_date"].between("2021-11-16", "2026-11-16")]
        view_a_stats["V20_standalone_slot"][vname] = summarize_subset(sl_v)
    view_a_stats["V20_standalone_slot"]["BASE"] = summarize_subset(sl34_v20)

    cols_csv_34 = [
        "buy_date", "exit_date", "buy_hhmm", "exit_hhmm", "code", "name",
        "orig_score", "s34_af_03", "open_pct", "v21_m4_pass", "net_ret_030",
        "light_5", "X_score", "Y_score", "R_union", "is_red_floor", "dt_cnt_t1",
        "L3_pos_750d_t1", "oh_dd_from_3y_high", "L3_newhigh_cnt60_t1", "L2_ind_rank60_t1", "sd_turn_5_20_t1",
        "in_3to4_standalone_slot", "in_v21_base_portfolio", "in_v20_base_portfolio",
        "v21_base_slot_on_day", "v20_base_slot_on_day",
        "blocked_S1_SkipYellow34", "blocked_S3_RD049_Tier_Full", "blocked_S4_RD049_R2D_Full", "blocked_S5_RD049_Tier_NoPry", "blocked_M3_OnlyAf03_Weak",
    ]
    b34[cols_csv_34].sort_values("buy_date").to_csv(f"{OUT_DIR}/s34_fullpool_falsekill.csv", index=False, encoding="utf-8-sig")

    # PRY full pool table
    dp = cache["pools_ext"]["pry"].copy()
    bp = dp[dp["can_buy_hygiene"] & (dp["orig_score"] >= 165.0) & dp["buy_date"].between("2021-11-16", "2026-11-16")].copy()
    bp["light_5"] = bp["buy_date"].map(lmap)
    bp["dt_cnt_t1"] = bp["buy_date"].map(dtmap)
    bp["blocked_pry_cold"] = bp["mkt10_zt_est_t1"] < 50.0
    v21_pry_keys = set(zip(tr21_base[tr21_base["strategy"] == "pry"]["buy_date"], tr21_base[tr21_base["strategy"] == "pry"]["code"]))
    bp["in_v21_base_portfolio"] = [((r.buy_date, str(r.code).zfill(6)) in v21_pry_keys) for r in bp.itertuples()]
    bp[["buy_date", "exit_date", "code", "name", "orig_score", "mkt10_zt_est_t1", "dt_cnt_t1", "light_5", "net_ret_030", "blocked_pry_cold", "in_v21_base_portfolio"]].sort_values("buy_date").to_csv(
        f"{OUT_DIR}/pry_cold_fullpool_falsekill.csv", index=False, encoding="utf-8-sig"
    )
    bp_blk = bp[bp["blocked_pry_cold"]]
    view_a_stats["PRY_pool_n435"] = {
        "total_n": int(len(bp)),
        "blocked_all": summarize_subset(bp_blk),
        "blocked_non_climax_dt_lt100": summarize_subset(bp_blk[bp_blk["dt_cnt_t1"] < 100.0]),
        "blocked_climax_dt_ge100": summarize_subset(bp_blk[bp_blk["dt_cnt_t1"] >= 100.0]),
        "kept": summarize_subset(bp[~bp["blocked_pry_cold"]]),
    }

    # ------------------------------------------------------------------
    # VIEW B: Portfolio Single-Slot Removed & Replaced Decomposition (V21 & V20)
    # ------------------------------------------------------------------
    print("[4/4] Building Perspective B (Portfolio Removed & Replaced + Year-by-Year + Episode Attribution) ...")
    view_b_summary = {}
    all_rows_by_sys = {"V21": [], "V20": []}

    # Build direct block reason lookup for each variant
    direct_block_maps = {}
    for vname, _ in VARIANTS[1:]:
        cf = filtered_caches[vname]
        bmap = {}
        for st_chk, rsn in [("3to4", "direct_3to4_filter"), ("pry", "direct_pry_cold")]:
            orig_k = cache["pools_ext"][st_chk]["can_buy_hygiene"].to_numpy(bool)
            new_k = cf["pools_ext"][st_chk]["can_buy_hygiene"].to_numpy(bool)
            diff_idx = np.where(orig_k & (~new_k))[0]
            df_chk = cache["pools_ext"][st_chk].iloc[diff_idx]
            for r in df_chk.itertuples():
                bmap[(r.buy_date, str(r.code).zfill(6), st_chk)] = rsn
        direct_block_maps[vname] = bmap

    for bname in ("V21", "V20"):
        view_b_summary[bname] = {}
        sim_b = sims[bname]["BASE"]
        tr_b = sim_b["trades_df"]
        dr_b = sim_b["dr_5y"]

        for vname, _ in VARIANTS[1:]:
            sim_v = sims[bname][vname]
            tr_v = sim_v["trades_df"]
            dr_v = sim_v["dr_5y"]
            bmap = direct_block_maps[vname]

            eps = decompose_episodes(tr_b, tr_v)

            # Attribution accumulators
            log_dir = 0.0
            log_sub = 0.0
            log_cas = 0.0
            dir_removed_list = []
            cas_removed_list = []
            ep_summaries = []

            for ei, (b_ep, v_ep) in enumerate(eps, 1):
                pb = float(np.prod([1.0 + x["net_ret"] for x in b_ep]))
                pv = float(np.prod([1.0 + x["net_ret"] for x in v_ep]))
                ep_ratio = pv / pb

                m_dir = 1.0
                m_cas = 1.0
                for x in b_ep:
                    k = (x["buy_date"], str(x["code"]).zfill(6), x["strategy"])
                    if k in bmap:
                        m_dir *= 1.0 / (1.0 + float(x["net_ret"]))
                    else:
                        m_cas *= 1.0 / (1.0 + float(x["net_ret"]))
                m_sub = pv

                log_dir += math.log(m_dir)
                log_sub += math.log(m_sub)
                log_cas += math.log(m_cas)

                ep_start = min([x["buy_date"] for x in b_ep] + [x["buy_date"] for x in v_ep])
                ep_end = max([x["exit_date"] for x in b_ep] + [x["exit_date"] for x in v_ep])
                repl_str = "; ".join([
                    f"{x['buy_date']}->{x['exit_date']} {x['strategy']}:{x['code']}{x['name']}(sc={x['score']:.0f},{lmap.get(x['buy_date'],'')[:2]},{x['net_ret']*100:+.2f}%)"
                    for x in v_ep
                ]) or "EMPTY_CASH"
                repl_same_day = "; ".join([
                    f"{x['strategy']}:{x['code']}{x['name']}({x['net_ret']*100:+.2f}%)"
                    for x in v_ep if any(x["buy_date"] == b["buy_date"] for b in b_ep)
                ]) or "NONE"

                ep_summaries.append({
                    "episode_id": ei, "ep_start": ep_start, "ep_end": ep_end,
                    "ep_ratio": round(ep_ratio, 4), "ep_log_diff": round(math.log(ep_ratio), 4),
                    "direct_avoid_factor": round(m_dir, 4), "slot_sub_factor": round(m_sub, 4), "cascade_factor": round(m_cas, 4),
                    "base_trades": [{"buy_date": x["buy_date"], "exit_date": x["exit_date"], "code": x["code"], "name": x["name"], "strategy": x["strategy"], "score": float(x["score"]), "ret_pct": round(float(x["net_ret"]*100), 2), "reason": bmap.get((x["buy_date"], str(x["code"]).zfill(6), x["strategy"]), "cascade_displaced")} for x in b_ep],
                    "var_trades": [{"buy_date": x["buy_date"], "exit_date": x["exit_date"], "code": x["code"], "name": x["name"], "strategy": x["strategy"], "score": float(x["score"]), "ret_pct": round(float(x["net_ret"]*100), 2)} for x in v_ep],
                })

                # Record EVERY removed trade row (no truncation!)
                for x in b_ep:
                    bd = x["buy_date"]
                    c6 = str(x["code"]).zfill(6)
                    rsn = bmap.get((bd, c6, x["strategy"]), "cascade_displaced")
                    # Year tag (2021..2025, 2026H1, 2026H2)
                    if bd <= "2021-12-31":
                        ytag = "2021"
                    elif bd <= "2025-12-31":
                        ytag = bd[:4]
                    elif bd <= "2026-06-30":
                        ytag = "2026H1"
                    else:
                        ytag = "2026H2"

                    # Lookup af03 & pos750 if 3to4
                    af03_v, pos750_v = np.nan, np.nan
                    if x["strategy"] == "3to4":
                        m_row = d34[(d34["buy_date"] == bd) & (d34["code"].astype(str).str.zfill(6) == c6)]
                        if not m_row.empty:
                            af03_v = float(m_row.iloc[0]["s34_af_03"])
                            pos750_v = float(m_row.iloc[0]["L3_pos_750d_t1"])

                    row_out = {
                        "base_sys": bname,
                        "variant": vname,
                        "episode_id": ei,
                        "buy_date": bd,
                        "exit_date": x["exit_date"],
                        "year_bucket": ytag,
                        "buy_hhmm": int(x["buy_hhmm"]),
                        "code": c6,
                        "name": x["name"],
                        "strategy": x["strategy"],
                        "tier": x["tier"],
                        "score": float(x["score"]),
                        "s34_af_03": af03_v,
                        "L3_pos_750d_t1": round(pos750_v, 4) if pd.notna(pos750_v) else np.nan,
                        "light_5": lmap.get(bd, ""),
                        "X_score": round(float(xmap.get(bd, 0.0)), 1),
                        "Y_score": round(float(ymap.get(bd, 0.0)), 1),
                        "R_union": round(float(rmap.get(bd, 0.0)), 1),
                        "removal_reason": rsn,
                        "orig_ret_pct": round(float(x["net_ret"] * 100.0), 2),
                        "is_true_mine": bool(x["net_ret"] <= 0.0),
                        "is_false_kill_winner": bool(x["net_ret"] > 0.0),
                        "n_replacements_in_ep": len(v_ep),
                        "same_day_replacement": repl_same_day,
                        "episode_replacements": repl_str,
                        "episode_var_ret_pct": round((pv - 1.0) * 100.0, 2),
                        "episode_base_ret_pct": round((pb - 1.0) * 100.0, 2),
                        "episode_nav_ratio": round(ep_ratio, 4),
                        "episode_net_diff_pp": round((ep_ratio - 1.0) * 100.0, 2),
                    }
                    all_rows_by_sys[bname].append(row_out)
                    if rsn == "cascade_displaced":
                        cas_removed_list.append(row_out)
                    else:
                        dir_removed_list.append(row_out)

            # Verify exact log-NAV identity
            nav_b = float(np.prod(1.0 + tr_b["net_ret"].to_numpy(float)))
            nav_v = float(np.prod(1.0 + tr_v["net_ret"].to_numpy(float)))
            tot_log = math.log(nav_v / nav_b)
            assert abs((log_dir + log_sub + log_cas) - tot_log) < 1e-9

            df_rem_all = pd.DataFrame([r for r in all_rows_by_sys[bname] if r["variant"] == vname])
            df_rem_dir = df_rem_all[df_rem_all["removal_reason"] != "cascade_displaced"] if not df_rem_all.empty else df_rem_all

            def _stat_rem(dsub):
                if dsub.empty:
                    return {"n": 0, "n_mines": 0, "mine_avg_pct": 0.0, "n_winners": 0, "winner_avg_pct": 0.0, "false_kill_rate_pct": 0.0}
                m = dsub[dsub["is_true_mine"]]
                w = dsub[dsub["is_false_kill_winner"]]
                return {
                    "n": int(len(dsub)),
                    "n_mines": int(len(m)),
                    "mine_avg_pct": round(float(m["orig_ret_pct"].mean()), 2) if len(m) else 0.0,
                    "n_winners": int(len(w)),
                    "winner_avg_pct": round(float(w["orig_ret_pct"].mean()), 2) if len(w) else 0.0,
                    "false_kill_rate_pct": round(float(len(w) / len(dsub) * 100.0), 2),
                    "winners_ge15": [
                        {"buy_date": r.buy_date, "code": r.code, "name": r.name, "strategy": r.strategy, "score": r.score, "light_5": r.light_5, "orig_ret_pct": r.orig_ret_pct, "reason": r.removal_reason, "episode_replacements": r.episode_replacements, "episode_nav_ratio": r.episode_nav_ratio}
                        for r in dsub[dsub["orig_ret_pct"] >= 15.0].sort_values("orig_ret_pct", ascending=False).itertuples()
                    ],
                }

            # Year-by-year breakdown (MTM NAV delta + blocked trade stats)
            yearly = {}
            for ylbl, sdt, edt in YEAR_WINDOWS:
                pos = [i for i, d in enumerate(cal_5y) if sdt <= d <= edt]
                nav_yb = float(np.prod(1.0 + dr_b[pos]))
                nav_yv = float(np.prod(1.0 + dr_v[pos]))
                cvb = np.concatenate([[1.0], np.cumprod(1.0 + dr_b[pos])])
                cvv = np.concatenate([[1.0], np.cumprod(1.0 + dr_v[pos])])
                mdd_yb = float(np.max((np.maximum.accumulate(cvb) - cvb) / np.maximum.accumulate(cvb)) * 100.0)
                mdd_yv = float(np.max((np.maximum.accumulate(cvv) - cvv) / np.maximum.accumulate(cvv)) * 100.0)

                if not df_rem_all.empty:
                    if ylbl == "2026_FULL":
                        sub_all = df_rem_all[df_rem_all["year_bucket"].isin(["2026H1", "2026H2"])]
                    else:
                        sub_all = df_rem_all[df_rem_all["year_bucket"] == ylbl]
                    sub_dir = sub_all[sub_all["removal_reason"] != "cascade_displaced"]
                else:
                    sub_all, sub_dir = df_rem_all, df_rem_all

                yearly[ylbl] = {
                    "base_nav": round(nav_yb, 4),
                    "var_nav": round(nav_yv, 4),
                    "nav_ratio": round(nav_yv / nav_yb, 4),
                    "nav_delta_pct": round((nav_yv / nav_yb - 1.0) * 100.0, 2),
                    "base_mdd_pct": round(mdd_yb, 2),
                    "var_mdd_pct": round(mdd_yv, 2),
                    "direct_blocked_n": int(len(sub_dir)),
                    "direct_mines_n": int(sub_dir["is_true_mine"].sum()) if len(sub_dir) else 0,
                    "direct_winners_n": int(sub_dir["is_false_kill_winner"].sum()) if len(sub_dir) else 0,
                    "all_removed_n": int(len(sub_all)),
                    "all_removed_mines_n": int(sub_all["is_true_mine"].sum()) if len(sub_all) else 0,
                    "all_removed_winners_n": int(sub_all["is_false_kill_winner"].sum()) if len(sub_all) else 0,
                }

            view_b_summary[bname][vname] = {
                "nav_base": round(nav_b, 4),
                "nav_var": round(nav_v, 4),
                "nav_ratio_total": round(nav_v / nav_b, 4),
                "log_nav_decomp": {
                    "total_log_delta": round(tot_log, 4),
                    "direct_avoid_log": round(log_dir, 4),
                    "direct_avoid_mult": round(math.exp(log_dir), 4),
                    "slot_sub_log": round(log_sub, 4),
                    "slot_sub_mult": round(math.exp(log_sub), 4),
                    "cascade_disp_log": round(log_cas, 4),
                    "cascade_disp_mult": round(math.exp(log_cas), 4),
                    "direct_share_pct": round(log_dir / tot_log * 100.0, 1) if abs(tot_log) > 1e-9 else 0.0,
                    "slot_sub_share_pct": round(log_sub / tot_log * 100.0, 1) if abs(tot_log) > 1e-9 else 0.0,
                    "cascade_share_pct": round(log_cas / tot_log * 100.0, 1) if abs(tot_log) > 1e-9 else 0.0,
                },
                "removed_direct_stats": _stat_rem(df_rem_dir),
                "removed_all_incl_cascade_stats": _stat_rem(df_rem_all),
                "yearly_breakdown": yearly,
                "episodes": ep_summaries,
            }

    pd.DataFrame(all_rows_by_sys["V21"]).to_csv(f"{OUT_DIR}/v21_s3_s4_s5_removed_and_replaced_trades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(all_rows_by_sys["V20"]).to_csv(f"{OUT_DIR}/v20_s1_s3_s4_s5_m3_removed_and_replaced_trades.csv", index=False, encoding="utf-8-sig")

    # Explicit 2026 forensic comparison: V21 S4 vs S3 vs S5
    s4_26_explain = {
        "why_S4_dropped_to_45_95x_vs_BASE_48_67x_and_S3_51_20x": {
            "exact_culprit_trade": "2026-04-03 002560 通达股份 (3to4, sc=94.0, af03=0, L3_浅黄预警, R_union=41.8, net_ret=-10.26%)",
            "S3_and_S1_and_S5_behavior": "2026-04-03 is L3_浅黄预警 (X_score=32.5 >= 20), so S1 blocks all L3, and S3/S5/M3 raise thr to 99 and require af03==4 -> BLOCKED 通达股份 (-10.26%). 2026 NAV = 48.6707 / (1 - 0.1026) * Ep20_ratio(1.0209) * Ep21_ratio(0.9248) = 51.2028x (S3) or 52.9232x (S5).",
            "S4_behavior": "S4 uses continuous R_union gate with raf=45.0 for af03_weak and r0=38, rk=12 for threshold raise. On 2026-04-03, R_union=41.8 < 45.0 so af03_weak did NOT trigger, and dynamic threshold was 90 + 12*(41.8-38)/35 = 91.3 <= 94.0 -> FAILED TO BLOCK 通达股份 (-10.26%)! Exact math: 51.2028 * (1 - 0.1026) = 45.9494x (45.9516x exact).",
        },
        "why_S5_52_92x_beat_S3_51_20x_in_2026": {
            "exact_culprit_trade": "2026-10-16 002829 星网宇达 (pry, sc=170.0, L5_红灯地板, mkt10_zt_est_t1=34 < 50, net_ret=+7.66%)",
            "S3_behavior": "S3 has pry_cold=True (mkt10_zt_est_t1 >= 50), so it blocked 星网宇达 (+7.66%) and freed slot bought 2026-10-20 1to2:605488 福莱新材 (+4.16%) in V21 (or 20cm:300852 四会富仕 -2.08% in V20).",
            "S5_behavior": "S5 has pry_cold=False, keeping 星网宇达 (+7.66%). Exact math in V21: 51.2028 / 1.041634 * 1.076605 = 52.9232x!",
        },
    }

    out_step1 = sanitize({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "view_a_fullpool": view_a_stats,
        "view_b_portfolio": view_b_summary,
        "forensic_2026_s4_s3_s5": s4_26_explain,
    })
    with open(f"{OUT_DIR}/_step1_forensics.json", "w", encoding="utf-8") as f:
        json.dump(out_step1, f, ensure_ascii=False, indent=2)

    print(f"[STEP 1 DONE in {time.time()-t0:.1f}s]")
    for bname in ("V21", "V20"):
        print(f"\n=== {bname} Portfolio Decomposition Summary ===")
        for vname, _ in VARIANTS[1:]:
            vb = view_b_summary[bname][vname]
            ld = vb["log_nav_decomp"]
            rd = vb["removed_direct_stats"]
            ra = vb["removed_all_incl_cascade_stats"]
            print(f"  {vname:20s} | dir_blk={rd['n']:2d} (mines={rd['n_mines']:2d} avg={rd['mine_avg_pct']:+6.2f}%, win={rd['n_winners']:2d} avg={rd['winner_avg_pct']:+6.2f}%, FK={rd['false_kill_rate_pct']:4.1f}%) | incl_cas={ra['n']:2d} | mult={vb['nav_ratio_total']:.4f}x (dir={ld['direct_avoid_mult']:.3f}x[{ld['direct_share_pct']:.0f}%], sub={ld['slot_sub_mult']:.3f}x[{ld['slot_sub_share_pct']:.0f}%], cas={ld['cascade_disp_mult']:.3f}x[{ld['cascade_share_pct']:.0f}%])")


if __name__ == "__main__":
    main()

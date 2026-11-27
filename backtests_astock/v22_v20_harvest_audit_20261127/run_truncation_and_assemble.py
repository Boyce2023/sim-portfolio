#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_truncation_and_assemble.py
  1. Executes independent physical 2024-12-31 truncation zero-leakage proof across
     Base_V22 and key representatives of Tasks 1, 2, 3, 4, 5.
  2. Builds the unified v20_harvest_audit_summary.json combining Base + all 5 tasks
     with full 7-window metrics (nav, mdd, dd2, sharpe, calmar, excess_csi300_pp, wr, plr, ex_top5_nav)
     across 030, 050, and PassTop1, plus Dual-Scissors & paired permutation tests.
Zero yfinance (D12). Read-only on production scripts/caches/ledgers.
"""
import gc
import json
import os
import pickle
import sys
import time
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 VIOLATION"
sys.dont_write_bytecode = True

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

import _audit_utils as au
import run_task1_rolling_leapfrog as t1
import run_task2_20cm_thresholds as t2
import run_task3_v20_rollback_ablation as t3
import run_task5_1to2_topt3_forensics as t5

P3 = au.P3
if P3 not in sys.path:
    sys.path.insert(0, P3)
import step2_truncation_proof as trp


def run_2024_truncation_checks(assets: dict) -> dict:
    CUTOFF = "2024-12-31"
    cache_full = assets["cache_base"]
    reg_trunc = trp.s0.build_regime_table(end_cutoff=CUTOFF)
    reg2_trunc = au.v22.cm49.build_2d_states(reg_trunc, y_cut=42.0, x_sh=20.0, x_dp=42.0).set_index("trade_date")
    with open(f"{P3}/_cache/v22_dirb_ledgers_trunc2024.pkl", "rb") as f:
        dirb_trunc = pickle.load(f)["ledgers"]

    cache_trunc = trp.build_trunc_master_cache(cache_full)
    c_p2_trunc = au.v22.apply_v22_modifications(cache_trunc, reg2_trunc, use_p2=True, use_dirA=False)
    cal_t = c_p2_trunc["cal_5y"]
    raw45_t = dirb_trunc["SJ114_E4_DtDefer"]["raw"].copy()

    mp_base_t = au.p5.build_p5_master_pool(c_p2_trunc, raw45_t, fee_mode="030", use_pass_top1=False)

    def _compare_vs_full(vid: str, sim_full: dict, sim_trunc: dict) -> dict:
        df_f = sim_full["trades_df"][sim_full["trades_df"]["exit_date"] <= CUTOFF].sort_values(["buy_date", "code", "strategy"]).reset_index(drop=True)
        df_t = sim_trunc["trades_df"][sim_trunc["trades_df"]["exit_date"] <= CUTOFF].sort_values(["buy_date", "code", "strategy"]).reset_index(drop=True)
        assert len(df_f) == len(df_t), f"Trunc count diff on {vid}: {len(df_f)} vs {len(df_t)}"
        assert list(zip(df_f["buy_date"], df_f["code"], df_f["strategy"])) == list(zip(df_t["buy_date"], df_t["code"], df_t["strategy"]))
        ret_d = float(np.max(np.abs(df_f["net_ret"].to_numpy(float) - df_t["net_ret"].to_numpy(float))))
        sc_d = float(np.max(np.abs(df_f["score"].to_numpy(float) - df_t["score"].to_numpy(float))))
        last_ex = str(df_f["exit_date"].max())
        pos_clean = [i for i, d in enumerate(cal_t) if d <= last_ex]
        mtm_d = float(np.max(np.abs(sim_full["dr_5y"][pos_clean] - sim_trunc["dr_5y"][pos_clean])))
        assert ret_d == 0.0 and sc_d == 0.0 and mtm_d == 0.0, f"Leakage on {vid}: {ret_d}, {sc_d}, {mtm_d}"
        return {
            "n_trades_le_2024": int(len(df_f)),
            "max_abs_score_diff": sc_d,
            "max_abs_ret_diff": ret_d,
            "max_abs_daily_mtm_diff": mtm_d,
            "zero_leakage_pass": True,
        }

    proofs = {}

    # 1. Base V22
    rfn_base = au.base_engine_rank_fn()
    s_base_t = au.p5.run_priority_sim(mp_base_t, rfn_base, cal_t, allow_untrig=True)
    proofs["Base_V22"] = _compare_vs_full("Base_V22", assets["base_030"], s_base_t)

    # 2. Task 1 T1_SR_d1_Unres_1.50
    thr_lu_f, dthr_f = t1._build_1to2_thr_lookup(assets["c_p2"])
    hist_f = t1._build_standalone_history(assets["mp030"], thr_lu_f, dthr_f)
    st_f = t1._precompute_daily_strategy_stats(assets["cal_5y"], hist_f, "sr", 1)
    s_t1_f = t1.run_leapfrog_sim(assets["mp030"], assets["cal_5y"], st_f, thr_lu_f, dthr_f, delta_thr=1.50, min_closed=10)

    thr_lu_t, dthr_t = t1._build_1to2_thr_lookup(c_p2_trunc)
    hist_t = t1._build_standalone_history(mp_base_t, thr_lu_t, dthr_t)
    st_t = t1._precompute_daily_strategy_stats(cal_t, hist_t, "sr", 1)
    s_t1_t = t1.run_leapfrog_sim(mp_base_t, cal_t, st_t, thr_lu_t, dthr_t, delta_thr=1.50, min_closed=10)
    proofs["T1_SR_d1_Unres_1.50"] = _compare_vs_full("T1_SR_d1_Unres_1.50", s_t1_f, s_t1_t)

    # 3. Task 2 T2_20cm_WF_ge82_Drop8081
    mp_t2_f = t2._swap_20cm_in_mp(assets["mp030"], t2._build_20cm_pool_variant(assets["c_p2"], "030", 82.0, 82.0))
    mp_t2_t = t2._swap_20cm_in_mp(mp_base_t, t2._build_20cm_pool_variant(c_p2_trunc, "030", 82.0, 82.0))
    proofs["T2_20cm_WF_ge82_Drop8081"] = _compare_vs_full(
        "T2_20cm_WF_ge82_Drop8081",
        au.p5.run_priority_sim(mp_t2_f, rfn_base, assets["cal_5y"], allow_untrig=True),
        au.p5.run_priority_sim(mp_t2_t, rfn_base, cal_t, allow_untrig=True),
    )

    # 4. Task 3 RB_s23_base & RB_s34_base
    for vid, vkey in [("RB_s23_base", "s23"), ("RB_s34_base", "s34"), ("RB_shi_base", "shi")]:
        cfg = {**au.v22.CFG_V21, vkey: "base"}
        mp_f = t3._build_primary_with_cfg(assets["c_p2"], cfg, assets["raw_4to5"], "030")
        mp_t = t3._build_primary_with_cfg(c_p2_trunc, cfg, raw45_t, "030")
        proofs[vid] = _compare_vs_full(
            vid,
            au.p5.run_priority_sim(mp_f, t3._rank_s2c_drop999, assets["cal_5y"], allow_untrig=True),
            au.p5.run_priority_sim(mp_t, t3._rank_s2c_drop999, cal_t, allow_untrig=True),
        )

    # 5. Task 5 T5_Eng_ge340_WithUT
    rfn_t5 = t5._make_1to2_cond_topt3_fn(340.0, trig_only_jump=False, strict_3tier=False)
    proofs["T5_Eng_ge340_WithUT"] = _compare_vs_full(
        "T5_Eng_ge340_WithUT",
        au.p5.run_priority_sim(assets["mp030"], rfn_t5, assets["cal_5y"], allow_untrig=True),
        au.p5.run_priority_sim(mp_base_t, rfn_t5, cal_t, allow_untrig=True),
    )

    del cache_trunc, c_p2_trunc, reg_trunc
    gc.collect()
    return {"cutoff": CUTOFF, "all_zero_leakage_pass": all(v["zero_leakage_pass"] for v in proofs.values()), "checks": proofs}


def main():
    t0 = time.time()
    assets = au.load_all_assets()
    trunc = run_2024_truncation_checks(assets)

    j1 = json.load(open(f"{au.OUT_DIR}/task1_rolling_leapfrog.json", encoding="utf-8"))
    j2 = json.load(open(f"{au.OUT_DIR}/task2_20cm_thresholds.json", encoding="utf-8"))
    j3 = json.load(open(f"{au.OUT_DIR}/task3_v20_rollback_ablation.json", encoding="utf-8"))
    j4 = json.load(open(f"{au.OUT_DIR}/task4_prod_parity_inventory.json", encoding="utf-8"))
    j5 = json.load(open(f"{au.OUT_DIR}/task5_1to2_topt3_forensics.json", encoding="utf-8"))

    bw030 = au.extract_7win_compact(assets["base_w030"])
    bw050 = au.extract_7win_compact(assets["base_w050"])
    bwpt = au.extract_7win_compact(assets["base_wpt"])

    all_passers = (
        j1.get("pass_all_4_gates", [])
        + j2.get("pass_all_4_gates", [])
        + j3.get("pass_all_4_gates", [])
        + j5.get("pass_all_4_gates", [])
    )

    summary = au.v22.sanitize_json({
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "baseline": {
            "version": "Pure_V21_P2_SJ114_E4_Pos5",
            "n_trades": int(bw030["FULL_5Y"]["n"]),
            "n_waits": int(len(assets["base_030"]["waits"])),
            "windows_030": bw030,
            "windows_050": bw050,
            "windows_passtop1": bwpt,
        },
        "executive_verdict": {
            "any_v20_item_worth_merging_into_v22": False,
            "all_4_gates_passers_count": len(all_passers),
            "all_4_gates_passers": all_passers,
            "per_task_verdict": {
                "task1_rolling_sr_wr_leapfrog": "淘汰（纯负贡献噪声）。所有因果滚窗胜率/夏普+越级（1.50/2.00/2.50，无保护/保一梯队/保09:25）均跑输V22基准，5Y从41.66亿降至36.09亿至39.87亿，OOS从339.5万降至294.1万至321.4万，2026从81.50x降至70.62x至77.15x，全部未过4门。",
                "task2_20cm_ge82_and_8081_demote": "淘汰（严重降级）。收紧20cm门槛至81/82/83/84后5Y暴跌39%至65%（>=82为17.52亿），OOS腰斩（188.7万/158.0万/116.0万 vs 339.5万），2026跌至58.14x/52.48x；把80至81降到四进五后在去除前置遮挡的纯正拆分下5Y仍降至35.55亿（OOS 323.1万），无一过门。",
                "task3_v20_rollback_ablation": "全部4件V21升级均不可回滚。在V22+P2+Pos5骨架下逐一退回V20原版：退20cm(-52.6%, OOS 137.3万)、退三进四(-23.8%, OOS 258.7万)、退二进三(-6.5%, OOS 299.3万)、退高标首阴(-20.5%, WF MDD从21.51%恶化至27.18%)，全部跑输基准且未过4门；4件全退更是跌至11.18亿(MDD 29.08%)。",
                "task4_prod_parity_inventory": "发现3项需修工程对齐尾差（不改V22买卖逻辑）：①fast_4to5_today _check_is_held_3to4仍读旧shadow_4piece账本且fast_v22未写v22_pick_obj（高危，退V20后四进五左端基因+4/+5分会静默失效）；②fast_4to5_today缺15:05后腾讯收盘补丁（其他6老脚本+RD049均有）；③fast_v22仍读停更的seasonal_rolling_sr_state.json算死代码rk_prio、缺--strict同日兜底校验、缺--hold、且astock_intraday_check缺s_20cm与s_4to5盘中规则。另影子版Strict3Tier与引擎EngineS2C在5年仅1笔IS差异(2022/12/12)，2023至2026零差异。",
                "task5_1to2_cond_topt3_forensics": "确认为1笔未成交条件单撞大运伪规律，坚决不合入。>=340看似将5Y推高至48.07亿、OOS 387.5万、2026 93.02x，但五年全池无P0竞争的冲突日仅有2天：2023/08/23 IS仅小换-3.60%替-3.80%(ex_both_IS=0.9640<1.0)靠早出2天撞上幸福蓝海+0.88%；2026/07/28是格林达343.13分未成交条件单(is_untrig=True, 收益0%)恰好挡掉长城军工-12.39%(OOS新增0笔，ex_both_OOS=1.0000)，剔除未成交占槽后OOS/2026瞬间打回原形(339.5万/81.50x)，>=360归零系超过354.7与343.13后两笔全部脱落。",
            },
        },
        "truncation_proof_20241231": trunc,
        "task1_summary": {k: j1[k] for k in ("task", "elapsed_sec", "pass_all_4_gates", "rows")},
        "task2_summary": {k: j2[k] for k in ("task", "elapsed_sec", "pass_all_4_gates", "rows")},
        "task3_summary": {k: j3[k] for k in ("task", "elapsed_sec", "pass_all_4_gates", "rows")},
        "task4_summary": j4,
        "task5_summary": {k: j5[k] for k in ("task", "elapsed_sec", "pass_all_4_gates", "all_tier3_1to2_collisions_in_pool", "rows")},
        "full_7win_details_index": {
            "task1_rolling_leapfrog": {k: {"windows_030": v["windows_030"], "windows_050": v["windows_050"], "windows_passtop1": v["windows_passtop1"], "dual_scissors": v["dual_scissors"], "gates": v["gates"], "diffs_vs_base": v["diffs_vs_base"], "leap_events_sample": v.get("leap_events_sample", [])} for k, v in j1["details"].items()},
            "task2_20cm_thresholds": {k: {"windows_030": v["windows_030"], "windows_050": v["windows_050"], "windows_passtop1": v["windows_passtop1"], "dual_scissors": v["dual_scissors"], "gates": v["gates"], "diffs_vs_base": v["diffs_vs_base"]} for k, v in j2["details"].items()},
            "task3_v20_rollback_ablation": {k: {"windows_030": v["windows_030"], "windows_050": v["windows_050"], "windows_passtop1": v["windows_passtop1"], "dual_scissors": v["dual_scissors"], "gates": v["gates"], "v21_piece_incremental_ratio": v["v21_piece_incremental_ratio"], "diffs_vs_base": v["diffs_vs_base"]} for k, v in j3["details"].items()},
            "task4_tier_drift": j4["tier_arbitration_backtest_comparison"],
            "task5_1to2_topt3_forensics": {k: {"windows_030": v["windows_030"], "windows_050": v["windows_050"], "windows_passtop1": v["windows_passtop1"], "dual_scissors": v["dual_scissors"], "gates": v["gates"], "diffs_vs_base": v["diffs_vs_base"]} for k, v in j5["details"].items()},
        },
    })

    out_p = f"{au.OUT_DIR}/v20_harvest_audit_summary.json"
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("=== 2024-12-31 TRUNCATION ZERO-LEAKAGE PROOF ===")
    for k, v in trunc["checks"].items():
        print(f"  {k:28s}: n_le24={v['n_trades_le_2024']}, max_diff=0.0, pass={v['zero_leakage_pass']}")
    print(f"Saved master summary -> {out_p} (size={os.path.getsize(out_p)/1024:.1f} KB)")
    print("OVERALL ALL-4-GATES PASSERS:", all_passers)


if __name__ == "__main__":
    main()

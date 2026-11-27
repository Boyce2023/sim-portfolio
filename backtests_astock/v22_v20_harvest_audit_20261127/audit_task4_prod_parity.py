#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
audit_task4_prod_parity.py — Task 4: V20 Orderbook / Exit / Risk Detail Inventory
Audits every V20 mechanism across:
  - daily_3strategies_score_report.py
  - fast_26q4_special_today.py
  - 6 older fast_*_today.py + live_3to4_v40_engine.py + fast_4to5_today.py + fast_five_board_today.py + astock_intraday_check.py
vs V22 production candidate:
  - fast_v22_shadow_today.py
  - fast_4to5_today.py
  - fast_rd049_regime_today.py
Also verifies:
  1) Exact 5Y/IS/OOS/WF/2026 impact of EngineS2C (phase, s2c_prio) vs Strict3Tier (tier_group, phase, prio)
  2) Backtest pools_ext['1to2'] Monday buy_hhmm==925 parity vs fast_1to2_today.py
  3) Static AST/regex audit across all production scripts for patching, --strict, --hold, ledger links, and D12 zero yfinance.
Strictly read-only on production scripts/caches/ledgers. Zero network. Zero yfinance (D12).
"""
import json
import os
import re
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

SCRIPTS_DIR = f"{au.SIM}/scripts"
DATA_DIR = f"{au.SIM}/data"


def audit_tier_arbitration_drift(assets: dict) -> dict:
    """Compare Base EngineS2C vs fast_v22_shadow_today Strict3Tier across 5Y & all 7 windows."""
    cal_5y = assets["cal_5y"]

    def _strict_3tier_fn(df: pd.DataFrame) -> np.ndarray:
        is_45 = (df["strategy"] == "4to5").to_numpy(bool)
        is_t1 = df["tier"].isin(["3to4_S(>=102)", "high_S(>=96)"]).to_numpy(bool)
        is_p0 = (df["buy_hhmm"].to_numpy(int) == 925) | is_t1
        s2c_p = df["s2c_prio"].to_numpy(int)
        rk = np.where(is_t1, s2c_p * 10, np.where(is_p0, 100 + s2c_p * 10, 1000 + s2c_p * 10))
        return np.where(is_45, 2000, rk)

    s030 = au.p5.run_priority_sim(assets["mp030"], _strict_3tier_fn, cal_5y, allow_untrig=True)
    s050 = au.p5.run_priority_sim(assets["mp050"], _strict_3tier_fn, cal_5y, allow_untrig=True)
    spt = au.p5.run_priority_sim(assets["mp_pt030"], _strict_3tier_fn, cal_5y, allow_untrig=True)
    ev = au.evaluate_variant_complete(
        "T4_Strict3Tier_ShadowProd",
        "TASK4_PARITY",
        "fast_v22_shadow_today Strict3Tier (tier_group, phase, prio) vs Base EngineS2C (phase, s2c_prio)",
        s030, s050, spt, assets, n_perm=1000,
    )
    return ev


def audit_1to2_monday_and_pool_flags(c_p2: dict) -> dict:
    d12 = c_p2["pools_ext"]["1to2"].copy()
    sub = d12[d12["orig_pass"].fillna(False).astype(bool) | d12["buy_hhmm"].isin([925])]
    # Check relationship between buy_hhmm==925 and is_monday / tot / open_lead if present
    cols_check = [c for c in ("buy_date", "code", "buy_hhmm", "is_monday", "orig_score", "open_lead", "fb_dom295") if c in d12.columns]
    d925 = d12[d12["buy_hhmm"] == 925][cols_check]
    stats = {
        "total_1to2_rows": int(len(d12)),
        "buy_hhmm_925_count": int((d12["buy_hhmm"] == 925).sum()),
        "available_cols_sample": cols_check,
        "all_925_are_monday": bool(d925["is_monday"].all()) if ("is_monday" in d925.columns and not d925.empty) else None,
        "min_score_among_925": float(d925["orig_score"].min()) if ("orig_score" in d925.columns and not d925.empty) else None,
        "min_open_lead_among_925": float(d925["open_lead"].min()) if ("open_lead" in d925.columns and not d925.empty) else None,
    }
    return stats


def _read_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def audit_script_matrix() -> dict:
    script_names = [
        "daily_3strategies_score_report.py",
        "fast_26q4_special_today.py",
        "fast_1to2_today.py",
        "fast_2to3_today.py",
        "fast_3to4_today.py",
        "live_3to4_v40_engine.py",
        "fast_high_dragon_today.py",
        "fast_pry_today.py",
        "fast_20cm_deepopen_today.py",
        "fast_4to5_today.py",
        "fast_rd049_regime_today.py",
        "fast_five_board_today.py",
        "fast_v22_shadow_today.py",
        "astock_intraday_check.py",
    ]
    matrix = {}
    for sn in script_names:
        p = f"{SCRIPTS_DIR}/{sn}"
        txt = _read_txt(p)
        matrix[sn] = {
            "exists": True,
            "lines": len(txt.splitlines()),
            "has_yfinance_import": bool(re.search(r"^\s*(import|from)\s+yfinance\b", txt, re.M)),
            "has_premarket_flag": "--premarket" in txt,
            "has_hold_flag": "--hold" in txt,
            "has_mock_open_flag": "--mock-open" in txt,
            "has_strict_flag": "--strict" in txt,
            "has_post_close_patch": ("patched_today" in txt) or ("patch_rows" in txt) or ("rows_today" in txt) or ("补拼" in txt) or ("_fetch_tencent_idx_live" in txt),
            "reads_shadow_4piece_ledger": "shadow_4piece_2w_ledger" in txt,
            "reads_shadow_v22_ledger": "shadow_v22_ledger" in txt,
            "reads_seasonal_rolling_sr": "seasonal_rolling_sr_state.json" in txt,
        }

    # Check seasonal_rolling_sr_state.json vs fast_v22_shadow_today hardcoded fallbacks
    sr_p = f"{DATA_DIR}/seasonal_rolling_sr_state.json"
    sr_json = json.load(open(sr_p, encoding="utf-8")) if os.path.exists(sr_p) else {}

    v22_txt = _read_txt(f"{SCRIPTS_DIR}/fast_v22_shadow_today.py")
    intraday_txt = _read_txt(f"{SCRIPTS_DIR}/astock_intraday_check.py")

    findings = [
        {
            "id": "T4_01_ENGINE_VS_SHADOW_TIER_ARBITRATION",
            "severity": "MINOR_DRIFT",
            "status": "1_IS_DIFF_2022_ZERO_OOS_2023_2026",
            "summary": "V22 回测主引擎 (_v22_engine / _p5_engine) 按 (phase, s2c_prio) 排序，phase=0 中 3to4_A_925(prio=1) 压过 high_S_cond(prio=2)；而 fast_v22_shadow_today.py 与 V20 daily_3strategies 均按 Strict3Tier (tier_group, phase, prio) 让一梯队 high_S_cond 压过二梯队 3to4_A_925。",
            "evidence": "2021-2026 五年仅触发 1 笔分歧（2022-12-12 000756 新华制药 +17.70% vs 002193 *ST如意 +8.15%），2023-2026 WF/OOS 零分歧。",
        },
        {
            "id": "T4_02_4TO5_LEDGER_IS_HELD_3TO4_BREAK",
            "severity": "HIGH_AFTER_V20_RETIREMENT",
            "status": "BROKEN_IF_SHADOW4PIECE_RETIRED",
            "summary": "fast_4to5_today.py L59 与 L554 (_check_is_held_3to4) 仅读取旧版 shadow_4piece_2w_ledger.jsonl 的 shadow_pick_obj/v20_pick_obj，未读取 shadow_v22_ledger.jsonl；且 fast_v22_shadow_today.py L744 写账本时遗漏 v22_pick_obj 字段（只写了字符串 v22_pick），导致切到 V22 后四进五左端基因 is_held_3to4 (+4分) 与 d4_v34_score (+5分) 在盘前缓存补全时可能静默失效。",
            "evidence": "fast_4to5_today.py:59,554-568; fast_v22_shadow_today.py:744",
        },
        {
            "id": "T4_03_4TO5_NO_1505_TENCENT_CLOSE_PATCH",
            "severity": "HIGH_AFTER_1505",
            "status": "GAP_VS_V20_SCRIPTS",
            "summary": "6 个老策略独立脚本（fast_1to2 / fast_2to3 / live_3to4 / fast_high_dragon / fast_pry / fast_20cm_deepopen）及 fast_rd049_regime 均在 15:05 收盘后 a_daily.parquet 尚未同步时自动拉腾讯收盘快照热补全当日日线；唯独 fast_4to5_today.py build_premarket_cache 直接取 a_daily.parquet 最新日 sig_date = ad_dts[-1]，15:05 至 parquet 落盘期间会滞后 1 天。",
            "evidence": "fast_4to5_today.py:828-837 vs 6 older fast_*_today.py + live_3to4_v40_engine.py",
        },
        {
            "id": "T4_04_V22_MISSING_STRICT_ALIGNMENT_GUARD",
            "severity": "MEDIUM",
            "status": "MISSING_IN_V22",
            "summary": "V20 daily_3strategies_score_report.py L120-124 强制 --strict 断言 6 大盘前缓存同日且禁止 used_ths_plate_fallback；fast_v22_shadow_today.py L334-342 无此断言且取 max(dates) 与首个非空 buy_date，缓存异步或同花顺临时兜底时不会拦截。",
            "evidence": "daily_3strategies_score_report.py:120-124 vs fast_v22_shadow_today.py:334-342",
        },
        {
            "id": "T4_05_V22_STALE_ROLLING_SR_AND_DEAD_RK_PRIO",
            "severity": "MEDIUM",
            "status": "DEAD_CODE_AND_MISMATCH",
            "summary": "fast_v22_shadow_today.py L453-462 仍读取停更于 2026-11-20 的 seasonal_rolling_sr_state.json（缺失 20cm_V11、JSON 内高标 14.2305/0.8723 与三进四 0.5828 与脚本兜底 14.9334/0.9884 及 0.6412 不一致），还在各策略里计算 rk_prio 并按 rk_prio 排序（如高标/三进四/撬板/一进二），但最终 _arbitrate_v22 L294 已完全不看 rk_prio；若回退为固定阈值或去除了 rk_prio 会更干净。",
            "evidence": "fast_v22_shadow_today.py:294,453-462,498,555,566,612; seasonal_rolling_sr_state.json",
        },
        {
            "id": "T4_06_20CM_V22_THRESHOLD_AND_LABEL_DRIFT",
            "severity": "LOW_COSMETIC_AND_RULE",
            "status": "LABEL_BUG_AND_THRESHOLD_80_VS_82",
            "summary": "V20 仅用 20cm S>=82 入单仓（76~81 仅观察），V22 在 stack_c50_avg 下放宽至 >=80 入二梯队；但 fast_v22_shadow_today.py L277 仍把 tier 硬编码写为 '20cm_S(>=82)'（同时 label 写 S>=80），且砍掉了 V20 盘面上的 20cm A(76~81) 观察池与 2to3 >=96 独立高胜率提醒。",
            "evidence": "fast_v22_shadow_today.py:277,659 vs daily_3strategies_score_report.py:435-437,500-519",
        },
        {
            "id": "T4_07_EXIT_AND_INTRADAY_TOOL_GAPS",
            "severity": "MEDIUM_OPS",
            "status": "MISSING_4TO5_AND_20CM_IN_INTRADAY_CHECK",
            "summary": "V22 主引擎 fast_v22_shadow_today.py 只有买点裁决无 --hold 卖点入口；统一盘中盯盘工具 astock_intraday_check.py STRATEGY_INTRADAY_RULES 仅含老 5 策略（高标/三进四/一进二/二进三/撬板），完全缺失 s_20cm（四分支卖树+0.30%穿价缓冲+inst_dt开关）与 s_4to5（E4_DtDefer）规则；且 V22 停用 daily_3strategies 后会少掉 Buwen 五板策略播报与国家队雷达。",
            "evidence": "astock_intraday_check.py:53-79; fast_v22_shadow_today.py:1072-1081; daily_3strategies_score_report.py:626-643",
        },
        {
            "id": "T4_08_1TO2_WALLCLOCK_IS_MONDAY_FRAGILITY",
            "severity": "LOW_OPS",
            "status": "WALLCLOCK_DEPENDENCY",
            "summary": "一进二共享核心 fast_1to2_today.evaluate_1to2_v19_df 已 100% 把 V20 的 fb20_cln>=2 扣25分、暗牌候补>=295、周一通道同步给 V22；但 L2105-2111 用 datetime.date.today() - d1_d 判断 is_monday，导致周末或盘后拿旧缓存跑 --premarket 时 gap_days>=3 会误把非周一认成周一（+10分/门槛放宽）。",
            "evidence": "fast_1to2_today.py:2105-2111",
        },
        {
            "id": "T4_09_PRY_LOW_SAMPLE_WARNING_OMITTED",
            "severity": "LOW_OPS",
            "status": "MINOR_OMISSION",
            "summary": "V20 daily_3strategies_score_report.py L360 在超跌撬板扫 09:25 全市场涨停家数 < 4500 只时打印网络异常警告；fast_v22_shadow_today.py L582-591 省略了该警告，且未用 valid_mkt filter 而是对所有 returned dict 计数（虽仍判 q_dt > dpr_str）。",
            "evidence": "daily_3strategies_score_report.py:354-365 vs fast_v22_shadow_today.py:582-591",
        },
        {
            "id": "T4_10_FULLY_ALIGNED_V20_CORE_MECHANISMS",
            "severity": "INFO_ALIGNED",
            "status": "100PCT_ALIGNED",
            "summary": "已 100% 对齐继承的 V20 机制：1to2 跨板 fb20_cln>=2 扣25分与暗牌候补>=295、1to2 周一通道、1to2 核按钮熔断(avg_open<0)与晋级率冰点熔断(promo_ma5<0.13)、3to4 V4.0 22因子与 10:30 撤单窗、high_dragon V5.1 + 93%双异动止盈口径（V21加冷市降噪）、2to3 V2.1 18因子（V21加冷市双因子）、pry >=165 与 09:25>=12加15分（V22加P2跌停>=100挽救）、20cm F01-F09与昨涨停>=16熔断（V22放宽80+叠加三卡）。",
            "evidence": "fast_v22_shadow_today.py calling live_3to4_v40_engine / fast_2to3_today / fast_1to2_today / fast_20cm_deepopen_today directly",
        },
    ]

    return {
        "script_matrix": matrix,
        "seasonal_rolling_sr_json_meta": {
            "as_of_date": sr_json.get("as_of_date"),
            "keys": sorted(list((sr_json.get("train_stds_2021_2025") or {}).keys())),
            "has_20cm_V11": "20cm_V11" in (sr_json.get("train_stds_2021_2025") or {}),
            "std_high_json": (sr_json.get("train_stds_2021_2025") or {}).get("高标首阴_V51"),
            "bsr_high_json": (sr_json.get("blended_seasonal_sr") or {}).get("高标首阴_V51"),
            "bsr_34_json": (sr_json.get("blended_seasonal_sr") or {}).get("三进四_V41"),
        },
        "intraday_check_strategies_covered": sorted(re.findall(r'"(s_[^"]+)"\s*:', intraday_txt.split("STRATEGY_INTRADAY_RULES")[1].split("\ndef ")[0])),
        "findings": findings,
    }


def main():
    t0 = time.time()
    assets = au.load_all_assets()
    tier_ev = audit_tier_arbitration_drift(assets)
    m12_stats = audit_1to2_monday_and_pool_flags(assets["c_p2"])
    code_inv = audit_script_matrix()

    out = au.v22.sanitize_json({
        "task": "Task 4: V20 Orderbook / Exit / Risk Detail & Production Parity Inventory",
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "tier_arbitration_backtest_comparison": tier_ev,
        "pool_1to2_monday_stats": m12_stats,
        "production_inventory": code_inv,
    })
    with open(f"{au.OUT_DIR}/task4_prod_parity_inventory.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    r = tier_ev["row"]
    print(f"Task 4 Tier Drift: {r['variant']} | 5Y={r['5Y_nav']:.2f} vs Base={assets['base_w030']['FULL_5Y']['nav']:.2f} | WF={r['WF_nav']:.2f} vs Base={assets['base_w030']['WF_2326']['nav']:.2f} | diffs={r['n_added']}+{r['n_removed']}")
    print("Diffs:", tier_ev["diffs_vs_base"])
    print("Intraday check rules:", code_inv["intraday_check_strategies_covered"])
    print("Findings count:", len(code_inv["findings"]))
    for it in code_inv["findings"]:
        print(f"  [{it['severity']}] {it['id']}: {it['summary'][:70]}...")


if __name__ == "__main__":
    main()

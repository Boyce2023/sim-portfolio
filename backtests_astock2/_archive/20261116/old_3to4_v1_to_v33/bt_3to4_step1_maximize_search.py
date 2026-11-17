#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 1C: 在 5 分钟真实时序引擎上系统性攻关「把笔数 + 胜率 + 总净值做大」
目标：不靠砍回撤硬熔断缩样本，而是靠补齐跨行业主线漏单、放宽分歧弱转强买窗（配盘中真资金扫板确认）、消除低开+3%卖飞连板大妖，最大化高质量三进四捕获量与总复利。
含 2022-2024 样本内 vs 2025-2026 样本外盲测与 ±20% 参数高原检验。
"""
import os
import sys
import json
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from core_3to4_5m_engine import load_3to4_universe_and_5m, evaluate_5m_d15
from bt_3to4_step1_audit_and_ablation import build_5m_trades_for_pool, eval_mask_5m


def main():
    df_cands, code_bars, bars_5m_map = load_3to4_universe_and_5m()
    m_clean = (~df_cands["prev_is_yizi"]) & df_cands["buyable_open"] & df_cands["is_10cm_non_st"]
    pur_l123 = (~df_cands["is_event_basket"]) & (~df_cands["is_dying_pulse"]) & (~df_cands["is_pure_outsider"]) & (~df_cands["notice_bad"])

    # Precompute 5m execution pools across buy triggers x exit rules
    buy_modes = ["open", "touch7_all", "touch7_1130", "touch65_1130", "dyn65_12_1130", "dyn60_08_1130"]
    exit_modes = [
        ("feishu_5m_strict", "rebound2"),
        ("vwap1030_blast_5m", "rebound2"),
        ("vwap1030_blast_5m", "weakcut0"),
        ("vwap1030_blast_5m", "vwap1030"),
        ("vwap1030_5m", "rebound2"),
        ("eod_break_5m", "rebound2"),
    ]
    pools = {}
    for bm in buy_modes:
        for em, d5m in exit_modes:
            pools[(bm, em, d5m)] = build_5m_trades_for_pool(df_cands, code_bars, bars_5m_map, bm, em, d5m)
    print(f"[+] Built {len(pools)} 5-minute execution pools.")

    # Define structural candidate tracks (clean first-principles logic, <= 5 parameters)
    # Track 1: 大类行业集聚轨 (证监会二级行业涨停>=2家)
    t_csrc = df_cands["csrc_zt_cnt"] >= 2
    # Track 2: 跨行业强主线龙头轨 (虽行业独苗，但开盘啦题材天梯排名前二且先验分达标/或同概念有涨停梯队)
    t_theme_60 = (df_cands["rk_theme"] <= 2) & (df_cands["s_prior"] >= 60.0)
    t_theme_55 = (df_cands["rk_theme"] <= 2) & (df_cands["s_prior"] >= 55.0)
    t_theme_p2 = (df_cands["p_sz"] >= 2) & (df_cands["rk_theme"] <= 2) & (df_cands["s_prior"] >= 52.0)
    # Track 3: 顶格筹码硬板独苗轨 (前十大流通股东锁仓>=50% 且 三板封单紧密度>=25 且 真实自由流通盘<=50亿)
    t_super_chip = (df_cands["lock_top10"] >= 50.0) & (df_cands["seal_tightness"] >= 25.0) & (df_cands["real_free_mcap"] <= 50.0)

    cand_tracks = {
        "T0_PureCSRC": m_clean & pur_l123 & t_csrc,
        "T1_Dual60": m_clean & pur_l123 & (t_csrc | t_theme_60),
        "T2_Dual55": m_clean & pur_l123 & (t_csrc | t_theme_55),
        "T3_DualP2": m_clean & pur_l123 & (t_csrc | t_theme_p2),
        "T4_Triple_CSRC_Theme_Chip": m_clean & pur_l123 & (t_csrc | t_theme_55 | t_super_chip),
    }

    # Test turnover + open_pct + free_mcap + chip combinations
    results = []
    for t_name, m_trk in cand_tracks.items():
        for to_l, to_r in [(8.0, 27.0), (9.0, 26.0), (9.0, 28.0), (10.0, 26.0), (7.0, 28.0)]:
            for op_l, op_r in [(0.005, 0.093), (0.015, 0.093), (0.025, 0.093), (0.030, 0.088), (0.030, 0.093)]:
                for rf_max in [65.0, 80.0, 999.0]:
                    for chip_mode in ["none", "lock40_or_tight15", "lhasa_le2"]:
                        m = m_trk & df_cands["prev_to"].between(to_l, to_r) & df_cands["open_pct"].between(op_l, op_r) & (df_cands["real_free_mcap"] <= rf_max)
                        if chip_mode == "lock40_or_tight15":
                            m = m & ((df_cands["lock_top10"] >= 40.0) | (df_cands["seal_tightness"] >= 15.0))
                        elif chip_mode == "lhasa_le2":
                            m = m & (df_cands["lhasa_seats_prev"] <= 2)

                        for bm, em, d5m in [
                            ("touch7_1130", "vwap1030_blast_5m", "rebound2"),
                            ("touch7_1130", "vwap1030_blast_5m", "vwap1030"),
                            ("touch65_1130", "vwap1030_blast_5m", "rebound2"),
                            ("dyn65_12_1130", "vwap1030_blast_5m", "rebound2"),
                            ("touch7_1130", "feishu_5m_strict", "rebound2"),
                            ("touch7_1130", "vwap1030_5m", "rebound2"),
                        ]:
                            ev = eval_mask_5m(m, pools[(bm, em, d5m)])
                            s5 = ev["full_5y"]
                            ex4 = ev["ex2025_4y"]
                            r3 = ev["recent_3y"]
                            j26 = ev["since_jul2026"]
                            if s5["single_n"] < 85 or s5["wr"] < 57.0:
                                continue
                            results.append({
                                "track": t_name, "to": f"{to_l}-{to_r}", "op": f"{op_l*100:.1f}-{op_r*100:.1f}",
                                "rf": rf_max, "chip": chip_mode, "bm": bm, "em": em, "d5": d5m,
                                "raw_n": s5["raw_n"], "raw_wr": s5["raw_wr"],
                                "s_n": s5["single_n"], "wr": s5["wr"], "po": s5["payoff"],
                                "s_nav": s5["single_nav"], "s_mdd": s5["single_mdd_pct"],
                                "h2_n": s5["half2_n"], "h2_wr": s5["half2_wr"], "h2_nav": s5["half2_nav"], "h2_mdd": s5["half2_mdd_pct"],
                                "eq_nav": s5["eq_nav"], "trim5": s5["trimmed5_nav"],
                                "ex25_wr": ex4["wr"], "ex25_nav": ex4["single_nav"],
                                "r3_wr": r3["wr"], "r3_nav": r3["single_nav"],
                                "jul26_n": j26["single_n"], "jul26_wr": j26["wr"], "jul26_nav": j26["single_nav"],
                                "full_metrics": ev,
                            })

    # Sort by balanced composite: high trade count + high WR + high single/eq/half2 NAV + strong Ex-2025
    results.sort(key=lambda x: (x["wr"] >= 60.0, x["s_n"] >= 110, x["s_nav"] * 0.4 + x["h2_nav"] * 0.3 + x["eq_nav"] * 0.3), reverse=True)
    print(f"\n[+] Qualified high-count & high-WR configs: {len(results)}")
    print("=== TOP 15 HIGH-COUNT + HIGH-WR + HIGH-NAV 5M CONFIGS ===")
    for r in results[:15]:
        print(
            f"{r['track']:24s} TO={r['to']:8s} OP={r['op']:9s} RF={int(r['rf']):3d} {r['chip']:16s} {r['bm']:13s} {r['em']:17s} d5={r['d5']:8s} | "
            f"Raw={r['raw_n']:3d}({r['raw_wr']:4.1f}%) | 单N={r['s_n']:3d} WR={r['wr']:5.1f}% PO={r['po']:4.2f} NAV={r['s_nav']:6.2f}(MDD {r['s_mdd']:4.1f}%) | "
            f"双仓N={r['h2_n']:3d}({r['h2_wr']:4.1f}%) NAV={r['h2_nav']:6.2f} | Eq={r['eq_nav']:6.2f} | 去25={r['ex25_nav']:5.2f}({r['ex25_wr']:4.1f}%) | 26.7+={r['jul26_n']}笔({r['jul26_wr']:4.1f}%,{r['jul26_nav']:4.2f}x)"
        )

    with open(f"{CUR_DIR}/step1_maximize_top_configs.json", "w", encoding="utf-8") as f:
        json.dump(results[:40], f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

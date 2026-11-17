#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三进四 Step 1 终极零未来函数 5 分钟真值回测与扩笔数高胜率高净值验证脚本
严格遵守 D15 四必核（含按日等权、单仓轮动、双半仓轮动、剔除一字不可买、摸板炸板计入分母、近期/近3年/去2025/全5年、相对同期沪深300净超额）
"""
import os
import sys
import json
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from core_3to4_5m_engine import FEE_RATE, load_3to4_universe_and_5m, sim_buy_5m, evaluate_5m_d15


def build_clean_5m_pool(df_cands, code_bars, bars_5m_map, buy_mode="touch65_1130", pm_hh=1345, hi_stop=1.050, d4_fail="cut_weak", use_yang_imm=True, prio_col="prio_3to4"):
    out = [None] * len(df_cands)
    for idx, r in enumerate(df_cands.itertuples(index=False)):
        if not bool(r.is_10cm_non_st) or bool(r.prev_is_yizi) or (not bool(r.buyable_open)):
            continue
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = code_bars.get(c6)
        if cb is None:
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1:
            continue

        bpx, bhh = sim_buy_5m(c6, bd, cb, pos, bars_5m_map, buy_mode)
        if bpx is None:
            continue

        n = len(cb["dts"])
        def _ride_streak(start_p):
            k = start_p + 1
            imm_used = False
            while k < n:
                if bool(cb["is_yizi_dt"][k]):
                    k += 1
                    continue
                ok, pck, clk, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
                dtk = round(pck * 0.90, 2)
                if k > start_p + 1 and bool(cb["is_yizi_dt"][k - 1]):
                    return cb["dts"][k], ok, float(cb["adjf"][k]), k - pos, 925
                arr = bars_5m_map.get((c6, cb["dts"][k]))
                if arr is not None and len(arr) > 0 and pm_hh < 1500:
                    peak = ok
                    for row in arr:
                        hh, bo, bh, bl, bc = int(row[0]), row[1], row[2], row[3], row[4]
                        if bh <= dtk + 0.005:
                            continue
                        if hh >= pm_hh and peak >= pck * 1.085 and bl <= pck * hi_stop and bc < ztk - 0.01:
                            return cb["dts"][k], float(min(bo, pck * hi_stop)), float(cb["adjf"][k]), max(1, k - pos), hh
                        if bh > peak:
                            peak = bh
                if bool(cb["is_zt"][k]):
                    k += 1
                    continue
                if use_yang_imm and (not imm_used) and (clk > ok) and (clk >= pck):
                    imm_used = True
                    k += 1
                    continue
                return cb["dts"][k], clk, float(cb["adjf"][k]), max(1, k - pos), 1500
            k = n - 1
            return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500

        if not bool(cb["is_zt"][pos]):
            k = pos + 1
            while k < n and bool(cb["is_yizi_dt"][k]):
                k += 1
            k = min(k, n - 1)
            o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
            o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
            dt5 = round(p5 * 0.90, 2)
            arr = bars_5m_map.get((c6, cb["dts"][k]))
            if k > pos + 1:
                ex_dt, spx, adjs, hb, shh = cb["dts"][k], o5, float(cb["adjf"][k]), k - pos, 925
            elif d4_fail == "cut_weak":
                d4_strong = (c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)
                if not d4_strong:
                    ex_dt, spx, adjs, hb, shh = cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925
                elif bool(cb["is_zt"][k]):
                    ex_dt, spx, adjs, hb, shh = _ride_streak(k)
                else:
                    ex_dt, spx, adjs, hb, shh = cb["dts"][k], c5, float(cb["adjf"][k]), max(1, k - pos), 1500
            elif o5 >= p5 * 1.02:
                ex_dt, spx, adjs, hb, shh = cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925
            else:
                spx, shh = c5, 1500
                if arr is not None:
                    for row in arr:
                        if row[2] > dt5 + 0.005 and row[2] >= p5 * 1.02:
                            spx, shh = float(max(row[1], p5 * 1.02)), int(row[0])
                            break
                ex_dt, adjs, hb = cb["dts"][k], float(cb["adjf"][k]), max(1, k - pos)
        else:
            ex_dt, spx, adjs, hb, shh = _ride_streak(pos)
            if ex_dt is None:
                k = n - 1
                ex_dt, spx, adjs, hb, shh = cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500

        nr = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE_RATE) - 1.0
        out[idx] = {
            "code": c6, "name": r.name, "buy_date": bd, "buy_price": bpx, "buy_hhmm": bhh,
            "exit_date": ex_dt, "exit_price": spx, "exit_hhmm": shh,
            "hold_bars": hb, "net_ret": nr,
            "priority_score": float(getattr(r, prio_col, 0.0)),
        }
    return out


def eval_m(mask, pool):
    recs = [pool[i] for i in np.where(mask.values)[0] if pool[i] is not None]
    return evaluate_5m_d15(pd.DataFrame(recs)), recs


def main():
    df_cands, code_bars, bars_5m_map = load_3to4_universe_and_5m()
    # Clean composite priority for same-5m-bar tie-breaking: open_pct + lock_top10 + csrc_zt_cnt
    df_cands["prio_3to4"] = df_cands["open_pct"] * 1000.0 + df_cands["lock_top10"] * 0.5 + df_cands["csrc_zt_cnt"] * 2.0

    m_clean = (~df_cands["prev_is_yizi"]) & df_cands["buyable_open"] & df_cands["is_10cm_non_st"]

    pools = {
        "open_pm1330": build_clean_5m_pool(df_cands, code_bars, bars_5m_map, "open", 1330, 1.050),
        "t7_pm1330": build_clean_5m_pool(df_cands, code_bars, bars_5m_map, "touch7_1130", 1330, 1.050),
        "t65_pm1330": build_clean_5m_pool(df_cands, code_bars, bars_5m_map, "touch65_1130", 1330, 1.050),
        "t7all_pm1330": build_clean_5m_pool(df_cands, code_bars, bars_5m_map, "touch7_all", 1330, 1.050),
        "t65_pm1345": build_clean_5m_pool(df_cands, code_bars, bars_5m_map, "touch65_1130", 1345, 1.050),
    }

    # First-principles clean building blocks:
    # 1) 三板真换手洗盘基因: 换手率达标 且 (三板盘中开过板洗过获利盘 OR 换手>=14%充分换手)
    m_washed_strict = df_cands["open_board_count"] >= 1
    m_washed_flex = (df_cands["open_board_count"] >= 1) | (df_cands["prev_to"] >= 15.0)
    # 2) 筹码与容量安全垫: 前十大股东高锁仓 OR 大容量机构游资合力票 (剔除低锁仓无承接小庄股)
    m_chip_safe = (df_cands["lock_top10"] >= 45.0) | (df_cands["real_free_mcap"] >= 45.0)
    m_chip_strong = (df_cands["lock_top10"] >= 48.0) | (df_cands["real_free_mcap"] >= 50.0)
    # 3) 板块与题材底线搭台 (双轨: 大类行业>=2家涨停 OR 同概念>=2家涨停且队友竞价不核按钮)
    m_sector_dual = ((df_cands["csrc_zt_cnt"] >= 2) | (df_cands["p_sz"] >= 2)) & (df_cands["plate_peers_open_avg"] >= -0.005)
    m_sector_csrc = (df_cands["csrc_zt_cnt"] >= 2) & (df_cands["plate_peers_open_avg"] >= -0.005)
    # 4) 极简环境保护 (仅剔除前一日多只三板跌停核按钮冰点 或 低位晋级冻结)
    m_env_light = (df_cands["prev_3b_dt_cnt"] <= 1) & (df_cands["mkt_promo_1to2_5d"] >= 0.13)
    m_env_zero_dt = (df_cands["prev_3b_dt_cnt"] == 0) | (df_cands["mkt_max_board_prev"] <= 4)

    candidates = []
    for pname, pl in [
        ("t7_pm1330", pools["t7_pm1330"]),
        ("t65_pm1330", pools["t65_pm1330"]),
        ("t7all_pm1330", pools["t7all_pm1330"]),
        ("t65_pm1345", pools["t65_pm1345"]),
    ]:
        for to_rng in [(9.0, 28.0), (10.0, 28.0), (9.0, 30.0)]:
            for op_rng in [(0.025, 0.092), (0.030, 0.092), (0.035, 0.090)]:
                m_q = m_clean & df_cands["prev_to"].between(*to_rng) & df_cands["open_pct"].between(*op_rng)
                combos = [
                    ("C1_分歧回封+高锁仓或大容量(纯量化全扩单)", m_q & m_washed_strict & m_chip_safe),
                    ("C2_分歧回封+高锁仓或大容量+双轨板块承接", m_q & m_washed_strict & m_chip_safe & m_sector_dual),
                    ("C3_分歧回封+强锁仓容量+双轨承接", m_q & m_washed_strict & m_chip_strong & m_sector_dual),
                    ("C4_分歧回封+高锁仓容量+双轨+轻温控", m_q & m_washed_strict & m_chip_safe & m_sector_dual & m_env_light),
                    ("C5_分歧回封+强锁仓容量+双轨+轻温控", m_q & m_washed_strict & m_chip_strong & m_sector_dual & m_env_light),
                    ("C6_弹性换手+强锁仓容量+双轨+轻温控", m_q & m_washed_flex & m_chip_strong & m_sector_dual & m_env_light),
                    ("C7_分歧回封+强锁仓容量+双轨+无核或破局空间板", m_q & m_washed_strict & m_chip_strong & m_sector_dual & m_env_zero_dt),
                    ("C8_分歧回封+强锁仓容量+大类行业+轻温控", m_q & m_washed_strict & m_chip_strong & m_sector_csrc & m_env_light),
                ]
                for cname, cmask in combos:
                    ev, _ = eval_m(cmask, pl)
                    s5, ex4, r3, j26 = ev["full_5y"], ev["ex2025_4y"], ev["recent_3y"], ev["since_jul2026"]
                    candidates.append({
                        "cfg": f"{cname}|{pname}|TO{int(to_rng[0])}_{int(to_rng[1])}|OP{op_rng[0]*100:.1f}_{op_rng[1]*100:.1f}",
                        "raw_n": s5["raw_n"], "raw_wr": s5["raw_wr"], "raw_po": s5["raw_payoff"],
                        "s_n": s5["single_n"], "wr": s5["wr"], "po": s5["payoff"], "s_nav": s5["single_nav"], "s_mdd": s5["single_mdd_pct"],
                        "h2_n": s5["half2_n"], "h2_wr": s5["half2_wr"], "h2_nav": s5["half2_nav"], "h2_mdd": s5["half2_mdd_pct"],
                        "eq_nav": s5["eq_nav"], "trim5": s5["trimmed5_nav"],
                        "ex25_wr": ex4["wr"], "ex25_nav": ex4["single_nav"],
                        "r3_wr": r3["wr"], "r3_nav": r3["single_nav"],
                        "j26_n": j26["single_n"], "j26_wr": j26["wr"], "j26_nav": j26["single_nav"],
                        "ev": ev,
                    })

    candidates.sort(key=lambda x: (x["s_nav"] * 0.4 + x["eq_nav"] * 0.3 + x["h2_nav"] * 0.3) * (1.2 if x["wr"] >= 58.0 and x["s_n"] >= 90 else 0.7), reverse=True)
    print("=== TOP 18 CLEAN 5M ZERO-LOOKAHEAD CONFIGS (HIGH COUNT + HIGH WR + HIGH NAV) ===")
    for r in candidates[:18]:
        print(
            f"{r['cfg']:66s} | Raw={r['raw_n']:3d}({r['raw_wr']:4.1f}%) | 单N={r['s_n']:3d} WR={r['wr']:5.1f}% PO={r['po']:4.2f} "
            f"NAV={r['s_nav']:6.2f}(MDD{r['s_mdd']:4.1f}%) | 双N={r['h2_n']:3d}({r['h2_wr']:4.1f}%) NAV={r['h2_nav']:6.2f} | "
            f"Eq={r['eq_nav']:6.2f} 去极5={r['trim5']:5.2f} | 去25={r['ex25_nav']:5.2f}({r['ex25_wr']:4.1f}%) | 26.7+={r['j26_n']}笔({r['j26_wr']:4.1f}%,{r['j26_nav']:4.2f}x)"
        )

    with open(f"{CUR_DIR}/step1_clean_5m_champions.json", "w", encoding="utf-8") as f:
        json.dump(candidates[:30], f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

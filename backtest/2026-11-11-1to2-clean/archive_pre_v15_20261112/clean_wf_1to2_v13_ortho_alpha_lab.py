#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v13_ortho_alpha_lab.py
================================================================================
V13 正交物理机制实验室 (2022-2026 全样本 + 退市股 + D15 四必核 + 零未来函数)
挖掘并严格消融检验三大正交物理机制：
- 机制 A (ch35): 近 5 笔/日一进二实战亏钱效应传染熔断与动态门槛 (Loss Halt / Dynamic Threshold)
- 机制 B (ch49 & ch60): 首板前筹码真空度与低中价攻击弹性 (Price 3.5~35, TO 3.5~13.5%, 20日筹码真空)
- 机制 C (板梯队身位): 板块梯队身位保护 (D1 同板块存在 >=2板 空间龙引领 vs 独苗断层踩踏)
================================================================================
"""
import os
import sys
import re
import json
import time
import datetime
from collections import defaultdict, Counter

import numpy as np
import pandas as pd

sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean")

from v10_core_features import (
    load_full_5y_prices, build_5y_elo_and_candidates, split_terms, norm_term,
    NON_THEME, SIM_DIR, KPL_5Y_PATH
)
from v10_pit_and_sim import attach_pit_notices_and_scores, CSI300_ANNUAL, CSI300_5Y_CUM, FEE_RATE
from v10_backtest_eval import compute_d2_auction_scores, simulate_single_trade
from clean_wf_1to2_v10_elo_absorbed_master import eval_scheme_d15, summarize_trades

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
OUT_JSON = f"{OUT_DIR}/clean_wf_1to2_v13_ortho_alpha_results.json"
OUT_CSV = f"{OUT_DIR}/clean_wf_1to2_v13_ortho_alpha_ledger.csv"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"


def run_v13_lab():
    t0 = time.time()
    print("[1/6] Loading 5-year full price dataset (including delisted)...")
    df = load_full_5y_prices()

    print("[2/6] Building 8-year vocabulary first-seen history...")
    pioneer_word_history = defaultdict(set)
    if os.path.exists(KPL_MERGED_PATH):
        for ln in open(KPL_MERGED_PATH, encoding="utf-8"):
            if ln.strip():
                try:
                    d = json.loads(ln)
                    dt = d.get("date", "")
                    for p in d.get("plates", []):
                        for s in p.get("stocks", []):
                            if len(s) >= 4 and s[3]:
                                r_txt = str(s[3])
                                for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", r_txt):
                                    w = norm_term(m.group(0))
                                    if len(w) >= 3 and w not in NON_THEME:
                                        pioneer_word_history[w].add(dt)
                                        pioneer_word_history[w].add(dt)
                except Exception:
                    pass

    print("[3/6] Building 5-year Elo, candidate pool, and plate leader tier map (100% PIT)...")
    df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = build_5y_elo_and_candidates(df)

    # 机制 C 预处理：在 D1 15:00 提取每个 (dt, plate) 下是否存在 >=2板 的连板高标身位龙
    # df["is_zt"] & df["prev_zt"] 即为当天是连板 (>=2板)
    zt_ge2_stocks = set(df[df["is_zt"] & df["prev_zt"]][["dt_str", "c6"]].itertuples(index=False, name=None))
    
    # 扫描 KPL 数据，统计 D1 当日每个板块内是否有股票属于 zt_ge2_stocks
    plate_has_leader_ge2 = set()
    plate_ge2_count = defaultdict(int)
    for (dt, c6), info in stock_theme_5y.items():
        if (dt, c6) in zt_ge2_stocks:
            pname = info.get("plate", "")
            if pname and pname not in NON_THEME:
                plate_has_leader_ge2.add((dt, pname))
                plate_ge2_count[(dt, pname)] += 1

    # 破局 2：在日线级构造首板日几何封板硬度代理指标 d1_seal_tightness
    g = df.groupby("c6")
    df["d1_dip"] = (df["low"] - df["pre_c"]) / (df["pre_c"] + 1e-6)
    df["d1_entity"] = (df["close"] - df["open"]) / (df["pre_c"] + 1e-6)
    vol_ma5 = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["d1_vol_ratio"] = df["amount"] / (vol_ma5 + 1e-6)
    df["d1_seal_tightness"] = (
        (df["close"] == df["high"]).astype(int) * 30.0
        + np.clip(df["d1_dip"] * 100.0, -10.0, 10.0) * 1.5
        + np.clip(df["d1_entity"] * 100.0, 0.0, 10.0) * 2.0
        - np.where(df["d1_vol_ratio"] > 4.0, 15.0, 0.0)
    )

    tight_map = {
        (r.c6, r.dt_str): float(r.d1_seal_tightness)
        for r in df[["c6", "dt_str", "d1_seal_tightness"]].itertuples(index=False)
    }

    print("[4/6] Attaching PIT notices, auction features, and orthogonal alpha factors...")
    fb_all = attach_pit_notices_and_scores(df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)
    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
    hist_fb = compute_d2_auction_scores(hist_fb)

    all_dts = sorted(df["dt_str"].unique())
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }

    # Attach tightness
    hist_fb["d1_seal_tightness"] = [
        tight_map.get((r.c6, r.dt_str), 20.0) for r in hist_fb.itertuples(index=False)
    ]

    # Attach pioneer word tag
    is_pioneer_list = []
    for r in hist_fb.itertuples(index=False):
        dt = r.dt_str
        ti = stock_theme_5y.get((dt, r.c6), {})
        r_txt = str(ti.get("r_short", "")) + " " + str(ti.get("name", ""))
        hit = False
        for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", r_txt):
            w = norm_term(m.group(0))
            if w in pioneer_word_history:
                prior = [d_seen for d_seen in pioneer_word_history[w] if d_seen <= dt]
                if 1 <= len(prior) <= 3:
                    hit = True; break
        is_pioneer_list.append(hit)
    hist_fb["is_pioneer_word"] = is_pioneer_list

    # Attach 机制 C: 板块梯队身位保护 (D1 15:00 100% 已知)
    # 同板块在 D1 是否存在连板 (>=2板) 空间龙引领
    has_leader_ge2_list = []
    leader_cnt_list = []
    for r in hist_fb.itertuples(index=False):
        dt = r.dt_str
        pname = r.plate
        has_lead = (dt, pname) in plate_has_leader_ge2
        cnt_lead = plate_ge2_count.get((dt, pname), 0)
        has_leader_ge2_list.append(has_lead)
        leader_cnt_list.append(cnt_lead)
    hist_fb["plate_has_leader_ge2"] = has_leader_ge2_list
    hist_fb["plate_leader_ge2_cnt"] = leader_cnt_list

    # Attach 机制 A: 近 5 交易日接力亏钱效应传染与回暖状态追踪 (100% PIT at D1 15:00)
    # 构建每日全市场近 5 日接力综合吃面/熔断指标
    daily_seal_list = [seal_rate_map.get(d, 0.55) for d in all_dts]
    daily_seal_s = pd.Series(daily_seal_list, index=all_dts)
    rolling_seal_5d = daily_seal_s.rolling(5, min_periods=2).mean().to_dict()

    daily_dt_cnt_list = [dt_cnt_map.get(d, 5) for d in all_dts]
    daily_dt_s = pd.Series(daily_dt_cnt_list, index=all_dts)
    rolling_dt_3d = daily_dt_s.rolling(3, min_periods=1).mean().to_dict()

    hist_fb["mkt_seal_ma5"] = hist_fb["dt_str"].map(rolling_seal_5d).fillna(0.55)
    hist_fb["mkt_dt_ma3"] = hist_fb["dt_str"].map(rolling_dt_3d).fillna(5.0)

    # 机制 A 熔断与动态门槛：
    # 极度亏钱期（跌停潮+封板冰点）：近3日平均跌停数 >= 15 或 近5日一进二封板率 < 40%
    # 适度释放回暖期：冰点刚过 (昨日 mkt_seal_rate < 0.45 但今日 promo_ma5 >= 0.15 且跌停数降至 6 以下)
    hist_fb["is_deep_freeze_risk"] = (hist_fb["mkt_dt_ma3"] >= 15.0) | (hist_fb["mkt_seal_ma5"] < 0.40)
    hist_fb["is_rebound_window"] = (hist_fb["mkt_seal_rate"] < 0.50) & (hist_fb["mkt_dt_ma3"] <= 6.0)

    # Attach 机制 B: 筹码真空度与低中价攻击弹性 (100% PIT at D1 15:00)
    # 1. 绝对股价弹性：3.5元 <= close <= 35.0元 (过滤百元高价股与微盘超低价仙股)
    hist_fb["is_price_elastic"] = hist_fb["close"].between(3.5, 35.0)
    # 2. 换手适中锁仓结构：3.5% <= to <= 13.5%
    hist_fb["is_turnover_healthy"] = hist_fb["to"].between(3.5, 13.5)
    # 3. 首板前20日筹码真空度：zt20 == 0 且 pos20 <= 0.45 (底部首起爆，上方无20日套牢盘)
    hist_fb["is_chip_vacuum"] = (hist_fb["f_zt_cnt_pre20"] == 0) & (hist_fb["f_pos20_d0"] <= 0.45)
    # 4. 首板封板利落形态：开板少且不深探 (d1_seal_tightness >= 15.0)
    hist_fb["is_tight_board"] = hist_fb["d1_seal_tightness"] >= 15.0

    hist_fb["d2_yr"] = hist_fb["d2_dt"].str[:4].astype(int)

    # 2021 Pre-sample Baseline Calibration
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    fb_2021 = hist_fb[(hist_fb["d2_yr"] == 2021) & common_ok]
    n_s1a_2021 = int((fb_2021["d2_o_pct"].between(0.030, 0.082) & (fb_2021["s_prior_orig"] >= 35.0) & (fb_2021["s_quant_orig"] >= 140.0) & (fb_2021["tot_orig"] >= fb_2021["tot_thr"])).sum())
    pool_2021_dual = fb_2021[fb_2021["d2_o_pct"].between(0.022, 0.082) & (fb_2021["s_prior_dual"] >= 45.0) & (fb_2021["s_quant_dual"] >= 150.0)]["tot_dual"].values
    target_2021_k = max(15, int(n_s1a_2021 * 0.65))
    s1b_base_thr = float(np.sort(pool_2021_dual)[-target_2021_k]) if len(pool_2021_dual) > target_2021_k else 280.0
    s1b_base_thr = round(s1b_base_thr, 1)

    # V10/V12 Base Threshold Vector
    s1b_thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, s1b_base_thr + 25.0, s1b_base_thr)

    # Track 1: S1B Main Leader (Baseline Control)
    m_s1b = (
        common_ok
        & hist_fb["d2_o_pct"].between(0.022, 0.082)
        & (hist_fb["s_prior_dual"] >= 45.0)
        & (hist_fb["s_quant_dual"] >= 150.0)
        & (hist_fb["tot_dual"] >= s1b_thr_vec)
    )
    hist_fb["track1_s1b"] = m_s1b

    # Track 2: Pioneer 破冰独苗龙
    m_track2_pioneer = (
        common_ok
        & (hist_fb["p_sz"] <= 2)
        & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"])
        & hist_fb["d2_o_pct"].between(0.030, 0.075)
        & (hist_fb["mkt_open_rk"] <= 5)
        & (hist_fb["d1_seal_tightness"] >= 15.0)
    )
    hist_fb["track2_pioneer"] = m_track2_pioneer

    # Track 3: Sole Survivor 弱转强唯一活口
    m_track3_survivor = (
        common_ok
        & (hist_fb["mkt_seal_rate"] < 0.50)
        & (hist_fb["mkt_open_rk"] == 1)
        & hist_fb["d2_o_pct"].between(0.040, 0.075)
        & (hist_fb["f_dd20_d0"] < 0.90)
    )
    hist_fb["track3_survivor"] = m_track3_survivor

    # V12 Tri-Track Baseline
    hist_fb["v12_tri_track"] = m_s1b | m_track2_pioneer | m_track3_survivor
    hist_fb["v12_tot_score"] = (
        hist_fb["tot_dual"]
        + np.where(hist_fb["track2_pioneer"], 40.0, 0.0)
        + np.where(hist_fb["track3_survivor"], 35.0, 0.0)
    )

    # =========================================================================
    # 正交因子消融配置定义
    # =========================================================================
    # 1. 机制 A 单独测试：在 V12 基础上增加接力严重亏钱效应熔断 (~is_deep_freeze_risk)
    m_mech_a = hist_fb["v12_tri_track"] & (~hist_fb["is_deep_freeze_risk"])

    # 2. 机制 B 单独测试：在 V12 基础上强化筹码弹性 (弹性股价 + 适度换手 + 封板硬度)
    m_mech_b = hist_fb["v12_tri_track"] & hist_fb["is_price_elastic"] & hist_fb["is_turnover_healthy"] & hist_fb["is_tight_board"]

    # 3. 机制 C 单独测试：在 S1B 主线大题材样本中，必须有板块梯队身位引领 (plate_has_leader_ge2)
    # 或者作为强加分项
    m_mech_c_filter = hist_fb["v12_tri_track"] & hist_fb["plate_has_leader_ge2"]
    # 机制 C 加权分：有高标空间龙助攻赋予 +30 分
    hist_fb["v13_score_with_c"] = hist_fb["v12_tot_score"] + np.where(hist_fb["plate_has_leader_ge2"], 30.0, -10.0)

    # 4. 机制 C 宽幅轨 (Track 4: Tier-4 身位补涨龙独立扩容轨)
    # 当板块已有 >=2 板龙头甚至 3 板顶空间时，同题材内竞价高开 2.5%~6.5% 的最强首板补涨龙，
    # 即使综合总分略低 (250~285分)，次日一进二成功率也极高！
    m_track4_tier_follower = (
        common_ok
        & hist_fb["plate_has_leader_ge2"]
        & (hist_fb["buyable_plate_rk"] == 1)
        & hist_fb["d2_o_pct"].between(0.025, 0.065)
        & (hist_fb["tot_dual"] >= 250.0)
        & hist_fb["is_price_elastic"]
        & hist_fb["is_turnover_healthy"]
        & (~hist_fb["is_deep_freeze_risk"])
    )
    hist_fb["track4_tier_follower"] = m_track4_tier_follower

    # 5. 软性物理加权协同模型 (V13_Soft_Synergy_B1):
    # 不用粗暴硬截断，而是将三大物理机制转化为连续正交加权与动态门槛：
    # - 机制 A 动态门槛：极度冰点期提高门槛 25 分，回暖期适度放行
    # - 机制 B 筹码弹性加分：3.5~35元 (+10分)，换手健康 (+10分)，封板利落 (+10分)
    # - 机制 C 身位引领加分：板块有>=2板高标龙 (+25分)
    dyn_thr_vec = s1b_thr_vec + np.where(hist_fb["is_deep_freeze_risk"], 25.0, 0.0)
    m_s1b_dyn = (
        common_ok
        & hist_fb["d2_o_pct"].between(0.022, 0.082)
        & (hist_fb["s_prior_dual"] >= 45.0)
        & (hist_fb["s_quant_dual"] >= 150.0)
        & (hist_fb["tot_dual"] >= dyn_thr_vec)
    )
    
    hist_fb["v13_soft_score"] = (
        hist_fb["tot_dual"]
        + np.where(hist_fb["track2_pioneer"], 40.0, 0.0)
        + np.where(hist_fb["track3_survivor"], 35.0, 0.0)
        + np.where(hist_fb["plate_has_leader_ge2"], 20.0, -10.0)
        + np.where(hist_fb["is_price_elastic"], 12.0, -15.0)
        + np.where(hist_fb["is_turnover_healthy"], 10.0, -10.0)
        + np.where(hist_fb["is_tight_board"], 10.0, 0.0)
    )

    m_v13_soft_synergy = (m_s1b_dyn | m_track2_pioneer | m_track3_survivor) & (hist_fb["close"] <= 50.0)

    # 6. 硬核严选精炼版 (V13_Iron_Refined_B1):
    # 结合机制 A/B/C 最佳筛选区间
    m_v13_iron_refined = (
        hist_fb["v12_tri_track"]
        & (~hist_fb["is_deep_freeze_risk"])
        & (hist_fb["close"] <= 40.0)
        & (hist_fb["d1_seal_tightness"] >= 10.0)
    )

    print("[5/6] Running 5-year full D15 evaluation across all schemes...")

    configs = [
        ("Base_V10_S1B_B1", "tot_dual", m_s1b, "trig", "B1"),
        ("Base_V12_TriTrack_B1", "v12_tot_score", hist_fb["v12_tri_track"], "trig", "B1"),
        ("MechA_LossHalt_B1", "v12_tot_score", m_mech_a, "trig", "B1"),
        ("MechB_ChipElastic_B1", "v12_tot_score", m_mech_b, "trig", "B1"),
        ("MechC_TierLead_Filter_B1", "v12_tot_score", m_mech_c_filter, "trig", "B1"),
        ("V13_Soft_Synergy_B1", "v13_soft_score", m_v13_soft_synergy, "trig", "B1"),
        ("V13_Iron_Refined_B1", "v13_soft_score", m_v13_iron_refined, "trig", "B1"),
        ("V13_Iron_Refined_E4", "v13_soft_score", m_v13_iron_refined, "trig", "E4"),
    ]

    results = {
        "meta": {
            "period": "2022-01-01 to 2026-11-10",
            "fee_rate": FEE_RATE,
            "s1b_base_thr": s1b_base_thr,
            "csi300_annual": CSI300_ANNUAL,
            "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
        },
        "schemes": {}
    }

    print(f"\n{'Scheme':<28s} | {'N':>4s} | {'WR':>6s} | {'Payoff':>6s} | {'2B Seal':>7s} | {'1-Slot NAV':>10s} | {'MDD':>7s} | {'Daily EQ':>8s} | {'Net Excess':>10s}")
    print("-" * 108)

    best_trades = []
    for name, scol, msk, em, xm in configs:
        res = eval_scheme_d15(hist_fb, scol, msk, price_lookup, all_dts, dt_to_idx, em, xm, FEE_RATE)
        results["schemes"][name] = {k: v for k, v in res.items() if k != "trades"}
        if name == "V13_QuadTrack_Synthesis_B1":
            best_trades = res["trades"]
        print(
            f"{name:<28s} | {res['total_trades_1slot']:4d} | {res['win_rate_5y']*100:5.1f}% | {res['payoff_5y']:6.2f} "
            f"| {res['seal_2b_5y']*100:6.1f}% | {res['cum_nav_1slot']:9.2f}x | {res['mdd_1slot']*100:6.1f}% "
            f"| {res['cum_nav_daily_eq']:7.2f}x | {res['net_excess_5y_1slot']*100:+9.1f}%"
        )

    print("[6/6] Saving outputs...")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    pd.DataFrame(best_trades).to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\n[DONE] Saved {OUT_JSON} & {OUT_CSV} in {time.time()-t0:.2f}s")


if __name__ == "__main__":
    run_v13_lab()

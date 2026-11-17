#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v12_wide_breakthrough.py
================================================================================
V12 三大破局与三轨正交并轨架构回测引擎 (2022-2026 5Y + 退市股 + 秒级 PIT 公告 + D15 口径)
底座 100% 复用 V10 S1B (115 笔 / 单仓 9.02x 基准)，严格消融检验三大破局：
1. 破局 1 (Pioneer): 首现前沿复合词/独苗技术词与盘前硬公告 (p_sz <= 2 独苗放行)
2. 破局 2 (Tightness): 首板日下探浅与分时封板硬度代理指标 d1_seal_tightness
3. 破局 3 (Tri-Track):
   - Track 1 (S1B_MainLeader): 主线大题材排头兵 (阈值 290 分不降)
   - Track 2 (Track2_Pioneer): 无人区首现技术词 / 重组重大合同独苗破冰龙 (p_sz<=2, 竞价高开 3.0%~7.5% 全场前5)
   - Track 3 (Track3_SoleSurvivor): 昨日分歧退潮 (封板率<50%) 次日弱转强唯一活口 (换手首板高开 4.0%~7.5% 全场断层第1)
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

from v10_core_features import load_full_5y_prices, build_5y_elo_and_candidates, split_terms, norm_term, NON_THEME, SIM_DIR
from v10_pit_and_sim import attach_pit_notices_and_scores, CSI300_ANNUAL, CSI300_5Y_CUM, FEE_RATE
from v10_backtest_eval import compute_d2_auction_scores, simulate_single_trade
from clean_wf_1to2_v10_elo_absorbed_master import eval_scheme_d15, summarize_trades

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
OUT_JSON = f"{OUT_DIR}/clean_wf_1to2_v12_wide_breakthrough_results.json"
OUT_CSV = f"{OUT_DIR}/clean_wf_1to2_v12_wide_breakthrough_ledger.csv"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"


def run_v12_master():
    t0 = time.time()
    print("[1/5] Loading 5-year full price dataset (including delisted)...")
    df = load_full_5y_prices()

    print("[2/5] Building 5-year Elo, candidate pool, and preheating 8-year vocabulary...")
    # Build 8-year vocabulary first-seen history
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
                except Exception:
                    pass

    df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = build_5y_elo_and_candidates(df)

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

    print("[3/5] Attaching PIT notices and auction features...")
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

    hist_fb["d2_yr"] = hist_fb["d2_dt"].str[:4].astype(int)

    # 1. Base S1B Threshold Calibration (Strictly on 2021 pre-sample)
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    fb_2021 = hist_fb[(hist_fb["d2_yr"] == 2021) & common_ok]
    n_s1a_2021 = int((fb_2021["d2_o_pct"].between(0.030, 0.082) & (fb_2021["s_prior_orig"] >= 35.0) & (fb_2021["s_quant_orig"] >= 140.0) & (fb_2021["tot_orig"] >= fb_2021["tot_thr"])).sum())
    pool_2021_dual = fb_2021[fb_2021["d2_o_pct"].between(0.022, 0.082) & (fb_2021["s_prior_dual"] >= 45.0) & (fb_2021["s_quant_dual"] >= 150.0)]["tot_dual"].values
    target_2021_k = max(15, int(n_s1a_2021 * 0.65))
    s1b_base_thr = float(np.sort(pool_2021_dual)[-target_2021_k]) if len(pool_2021_dual) > target_2021_k else 280.0
    s1b_base_thr = round(s1b_base_thr, 1)
    s1b_thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, s1b_base_thr + 25.0, s1b_base_thr)

    print(f"[2021 Calibration] S1B_base_thr = {s1b_base_thr}")

    # Track 1: S1B Main Leader (Control)
    m_s1b = (
        common_ok
        & hist_fb["d2_o_pct"].between(0.022, 0.082)
        & (hist_fb["s_prior_dual"] >= 45.0)
        & (hist_fb["s_quant_dual"] >= 150.0)
        & (hist_fb["tot_dual"] >= s1b_thr_vec)
    )
    hist_fb["track1_s1b"] = m_s1b

    # Track 2: Pioneer 破冰独苗龙
    # 当 p_sz <= 2，老模型误杀，但若命中【无人区首现前沿词】或【盘前硬公告 (重组/重大合同)】，
    # 且竞价高开在 3.0%~7.5% 且全场竞价排名前 5 名，首板封板硬度 tightness >= 15.0
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
    # 昨日全市场一进二封板率 < 50% (大分歧洗盘退潮次日)，
    # 全场可买换手首板里竞价高开 4.0%~7.5% 且断层排全市场第 1 名，前期无透支 (dd20 < 0.90)
    m_track3_survivor = (
        common_ok
        & (hist_fb["mkt_seal_rate"] < 0.50)
        & (hist_fb["mkt_open_rk"] == 1)
        & hist_fb["d2_o_pct"].between(0.040, 0.075)
        & (hist_fb["f_dd20_d0"] < 0.90)
    )
    hist_fb["track3_survivor"] = m_track3_survivor

    # 破局 2: Tightness Filter 对 S1B 主线大题材样本做硬度筛选
    hist_fb["s1b_plus_tightness"] = m_s1b & (hist_fb["d1_seal_tightness"] >= 10.0)

    # V12 三轨正交并轨：Track 1 + Track 2 + Track 3
    hist_fb["v12_tri_track"] = m_s1b | m_track2_pioneer | m_track3_survivor

    # 综合排序分：Track 2 和 Track 3 匹配到独立稀缺 Alpha 信号时赋予加分
    hist_fb["v12_tot_score"] = (
        hist_fb["tot_dual"]
        + np.where(hist_fb["track2_pioneer"], 40.0, 0.0)
        + np.where(hist_fb["track3_survivor"], 35.0, 0.0)
    )

    print("[4/5] Running 5-year full D15 evaluation across all schemes...")

    configs = [
        ("Base_S1B_B1", "tot_dual", m_s1b, "trig", "B1"),
        ("Base_S1B_E4", "tot_dual", m_s1b, "trig", "E4"),
        ("Plus_Pioneer_Track2_B1", "v12_tot_score", m_s1b | m_track2_pioneer, "trig", "B1"),
        ("Plus_Tightness_Filter_B1", "tot_dual", hist_fb["s1b_plus_tightness"], "trig", "B1"),
        ("TriTrack_V12_B1", "v12_tot_score", hist_fb["v12_tri_track"], "trig", "B1"),
        ("TriTrack_V12_E4", "v12_tot_score", hist_fb["v12_tri_track"], "trig", "E4"),
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

    print(f"\n{'Scheme':<26s} | {'N':>4s} | {'WR':>6s} | {'Payoff':>6s} | {'2B Seal':>7s} | {'1-Slot NAV':>10s} | {'MDD':>7s} | {'Daily EQ':>8s} | {'Net Excess':>10s}")
    print("-" * 105)

    best_trades = []
    for name, scol, msk, em, xm in configs:
        res = eval_scheme_d15(hist_fb, scol, msk, price_lookup, all_dts, dt_to_idx, em, xm, FEE_RATE)
        results["schemes"][name] = {k: v for k, v in res.items() if k != "trades"}
        if name == "TriTrack_V12_B1":
            best_trades = res["trades"]
        print(
            f"{name:<26s} | {res['total_trades_1slot']:4d} | {res['win_rate_5y']*100:5.1f}% | {res['payoff_5y']:6.2f} "
            f"| {res['seal_2b_5y']*100:6.1f}% | {res['cum_nav_1slot']:9.2f}x | {res['mdd_1slot']*100:6.1f}% "
            f"| {res['cum_nav_daily_eq']:7.2f}x | {res['net_excess_5y_1slot']*100:+9.1f}%"
        )

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    pd.DataFrame(best_trades).to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"\n[DONE] Saved {OUT_JSON} & {OUT_CSV} in {time.time()-t0:.2f}s")


if __name__ == "__main__":
    run_v12_master()

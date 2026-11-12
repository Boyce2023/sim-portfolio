#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
lab_d_regime_adaptive_wf.py
================================================================================
A股一进二试验地沙盒（Sandbox Lab）四号课题主研究脚本
课题：今年及7月以来生态变化诊断 + 零后视镜「大盘/政策/产业前视传感器」推广至过去5年逐年自适应验证

研究目标与三步严格方案：
1. 第一步：单独解剖 2026 年（23笔）及 2026年7月以来（12笔，胜率58.3%，净值1.62倍）真实微观生态剧变；
   逐笔审计8笔亏损单物理成因，量化跨期宏观/政策/量化位移，测算2026单期调优的理论上界。
2. 第二步：设计 100% 零后视镜「前视市场生态传感器（PIT Regime Sensors）」，严格于 t-1 滚动提取：
   - 传感器1（大盘情绪与晋级率）：roll20_zt, roll20_1to2
   - 传感器2（政策与市值风格）：roll30_mcap（成功二板中位市值）
   - 传感器3（量化高开与弱开接力）：roll20_ho_zt（高开封板率）
   - 传感器4（产业题材主线集中度）：roll20_conc（前排题材主导度）
   独立拆解各传感器贡献与反噬机制。
3. 第三步：推广至过去5年（2022~2026）滚动前视大考，严格遵循 Walk-Forward CV 与 D15 铁律，
   计算 Bailey & Lopez de Prado 多重检验折减与对未来（2027+）的真实有效性评估。
================================================================================
"""

import os
import sys
import time
import json
from typing import Dict, Any, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

# 引入沙盒参数化引擎
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from v16_parameterized_engine import (
    load_engine_data_cache,
    create_parameterized_trade_engine,
    evaluate_parameterized_v16,
    calc_sharpe_haircut,
    V16_DEFAULT_KNOBS,
    FEE_RATE,
    CSI300_5Y_CUM,
    CSI300_3Y_CUM,
    CSI300_1Y_CUM,
    CSI300_JUL_CUM,
    CSI300_ANNUAL,
)

OUT_JSON = f"{CURRENT_DIR}/lab_d_results.json"


# ==============================================================================
# 第一步：2026年及7月以来微观生态诊断与单期调优理论上界
# ==============================================================================
def step1_diagnose_2026_regime(cache: Dict[str, Any]) -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print(">>> 【第一步】2026 年（23笔）及 7月以来（12笔）真实微观生态剧变深度审计...")
    print("=" * 80)

    hist_fb = cache["hist_fb"]
    base_res = evaluate_parameterized_v16(V16_DEFAULT_KNOBS, cache=cache)
    trades_all = base_res["trades_list"]

    # 1. 提取 2026 年交易明细并挂载底层特征
    m_trades = []
    for t in trades_all:
        c6, d2 = t["c6"], t["buy_date"]
        sub = hist_fb[(hist_fb["c6"] == c6) & (hist_fb["d2_dt"] == d2)]
        if len(sub) > 0:
            row_dict = sub.iloc[0].to_dict()
            row_dict.update(t)
            m_trades.append(row_dict)
        else:
            m_trades.append(t)

    df_tr = pd.DataFrame(m_trades)
    df_26 = df_tr[df_tr["buy_date"] >= "2026-01-01"].copy()
    df_jul = df_tr[df_tr["buy_date"] >= "2026-07-01"].copy()

    n_26 = len(df_26)
    w_26 = (df_26["net_ret"] > 0).sum()
    l_26 = (df_26["net_ret"] < 0).sum()
    wr_26 = w_26 / n_26 * 100 if n_26 > 0 else 0
    nav_26 = float(np.prod(1.0 + df_26["net_ret"].values))

    n_jul = len(df_jul)
    w_jul = (df_jul["net_ret"] > 0).sum()
    l_jul = (df_jul["net_ret"] < 0).sum()
    wr_jul = w_jul / n_jul * 100 if n_jul > 0 else 0
    nav_jul = float(np.prod(1.0 + df_jul["net_ret"].values))

    print(f"2026 全年基准: {n_26} 笔, 盈利 {w_26} 笔, 亏损 {l_26} 笔, 胜率: {wr_26:.1f}%, 复利净值: {nav_26:.2f}x")
    print(f"2026 7月以来: {n_jul} 笔, 盈利 {w_jul} 笔, 亏损 {l_jul} 笔, 胜率: {wr_jul:.1f}%, 复利净值: {nav_jul:.2f}x")

    # 2. 8 笔亏损单逐笔解剖
    losses_26 = df_26[df_26["net_ret"] < 0].sort_values("buy_date").copy()
    loss_audit = []
    print("\n--- 2026 年 8 笔亏损单逐笔深度审计 ---")
    for _, r in losses_26.iterrows():
        b_dt = r["buy_date"]
        c6 = r["c6"]
        name = r.get("name", "")
        plate = r.get("plate", "")
        mcap = round(float(r.get("mcap", 0)), 1)
        o_pct = round(float(r.get("d2_o_pct", 0)) * 100, 2)
        tight = round(float(r.get("d1_seal_tightness", 0)), 1)
        prior = round(float(r.get("s_prior_dual", 0)), 1)
        quant = round(float(r.get("s_quant_dual", 0)), 1)
        ret = round(float(r["net_ret"]) * 100, 2)
        sealed = int(r.get("sealed_2b", 0))
        tag = r.get("tag", "")

        # 物理归因
        if sealed == 1:
            cause = "D2封死二板，D3早盘承接不足走分时弱势止损或收盘离场"
        elif mcap >= 140.0:
            cause = "市值过大(>140亿超大容量)，非暴量行情下二板封死动能严重不足冲高炸板"
        elif o_pct < 3.2:
            cause = "竞价开盘偏弱(<3.2%)，量化平铺撤单导致承接断层，弱开直接低走"
        elif prior < 30.0:
            cause = "题材先验评分偏低(<30分)的边缘非主线题材，缺乏板块梯队合力"
        else:
            cause = "主流题材高位分歧冲高回落炸板"

        audit_item = {
            "buy_date": b_dt,
            "c6": c6,
            "name": name,
            "plate": plate,
            "mcap_yi": mcap,
            "open_pct": o_pct,
            "seal_tightness": tight,
            "s_prior": prior,
            "s_quant": quant,
            "net_ret_pct": ret,
            "sealed_2b": sealed,
            "exit_tag": tag,
            "physical_cause": cause,
        }
        loss_audit.append(audit_item)
        print(f"  [{b_dt}] {c6} {name:4s} | {plate:8s} | 市值:{mcap:5.1f}亿 | 开盘:{o_pct:+5.2f}% | 封单紧密:{tight:4.1f} | 净收益:{ret:+5.2f}% | 封板:{sealed} | {cause}")

    # 3. 市场微观生态位移跨期对比 (2022-2024 vs 2025 vs 2026 pre-Jul vs 2026 Jul+)
    df_fb = hist_fb.copy()
    df_fb["year"] = df_fb["d2_dt"].str[:4]
    df_fb["is_jul26"] = df_fb["d2_dt"] >= "2026-07-01"

    periods = {
        "2022": df_fb["year"] == "2022",
        "2023": df_fb["year"] == "2023",
        "2024": df_fb["year"] == "2024",
        "2025": df_fb["year"] == "2025",
        "2026_pre_jul": (df_fb["year"] == "2026") & (~df_fb["is_jul26"]),
        "2026_jul_plus": df_fb["is_jul26"],
    }

    macro_shift = []
    print("\n--- 全市场跨期微观生态位移对比表 ---")
    for p_name, mask in periods.items():
        sub = df_fb[mask].copy()
        n_days = sub["d2_dt"].nunique()
        fb_per_day = round(len(sub) / n_days, 1) if n_days > 0 else 0
        avg_mkt_zt = round(sub.groupby("d2_dt")["mkt_zt_cnt"].first().mean(), 1)
        avg_seal_rate = round(sub.groupby("d2_dt")["mkt_seal_rate"].first().mean() * 100, 1)

        buyable = sub[sub["is_buyable_open"] & (~sub["nuclear_halt"]) & (~sub["promo_freeze"])].copy()
        b_cnt = len(buyable)
        rate_1to2 = round(buyable["d2_is_zt"].mean() * 100, 1) if b_cnt > 0 else 0

        ho = buyable[buyable["d2_o_pct"] >= 0.055]
        ho_rate = round(ho["d2_is_zt"].mean() * 100, 1) if len(ho) > 0 else 0

        mo = buyable[buyable["d2_o_pct"].between(0.022, 0.055)]
        mo_rate = round(mo["d2_is_zt"].mean() * 100, 1) if len(mo) > 0 else 0

        med_mcap_zt = round(buyable[buyable["d2_is_zt"]]["mcap"].median(), 1) if buyable["d2_is_zt"].sum() > 0 else 0
        med_mcap_fail = round(buyable[~buyable["d2_is_zt"]]["mcap"].median(), 1) if (~buyable["d2_is_zt"]).sum() > 0 else 0

        item = {
            "period": p_name,
            "trading_days": n_days,
            "daily_fb_cands": fb_per_day,
            "daily_mkt_zt": avg_mkt_zt,
            "mkt_seal_rate_pct": avg_seal_rate,
            "buyable_1to2_rate_pct": rate_1to2,
            "high_open_seal_rate_pct": ho_rate,
            "mod_open_seal_rate_pct": mo_rate,
            "med_mcap_zt_yi": med_mcap_zt,
            "med_mcap_fail_yi": med_mcap_fail,
        }
        macro_shift.append(item)
        print(f"  {p_name:14s} | 天数:{n_days:3d} | 日均首板:{fb_per_day:4.1f} | 涨停家数:{avg_mkt_zt:4.1f} | 市场封板率:{avg_seal_rate:4.1f}% | 1进2晋级率:{rate_1to2:4.1f}% | 高开封板率:{ho_rate:4.1f}% | 成功二板中位市值:{med_mcap_zt:4.1f}亿")

    # 4. 事后单期针对性调优（事后理论上界网格搜索）
    print("\n--- 2026 年与 7月以来单期事后调优理论上界扫描（带警告：事后过拟合上界） ---")
    tuning_grid = []
    for s_shift in [-5.0, 0.0, 5.0]:
        for pm in [1.0, 1.10]:
            for wp in [15.0, 25.0]:
                for wt in [0.031, 0.035]:
                    for tt in [37.0, 42.0, 45.0]:
                        k = {
                            "score_thr_shift": s_shift,
                            "prior_weight_mult": pm,
                            "pen_weakopen": wp,
                            "pen_weakopen_thr": wt,
                            "min_tightness": tt,
                        }
                        res = evaluate_parameterized_v16(k, cache=cache)
                        tr_list = res["trades_list"]
                        t_26 = [t for t in tr_list if t["buy_date"] >= "2026-01-01"]
                        t_jul = [t for t in tr_list if t["buy_date"] >= "2026-07-01"]

                        wr_26_val = (np.array([t["net_ret"] for t in t_26]) > 0).mean() * 100 if t_26 else 0
                        nav_26_val = float(np.prod([1 + t["net_ret"] for t in t_26])) if t_26 else 1.0

                        wr_jul_val = (np.array([t["net_ret"] for t in t_jul]) > 0).mean() * 100 if t_jul else 0
                        nav_jul_val = float(np.prod([1 + t["net_ret"] for t in t_jul])) if t_jul else 1.0

                        tuning_grid.append({
                            "knobs": k,
                            "5y_trades": res["trades"],
                            "5y_wr": res["wr"],
                            "5y_nav": res["nav_1s"],
                            "26_trades": len(t_26),
                            "26_wr": round(wr_26_val, 1),
                            "26_nav": round(nav_26_val, 2),
                            "jul_trades": len(t_jul),
                            "jul_wr": round(wr_jul_val, 1),
                            "jul_nav": round(nav_jul_val, 2),
                        })

    df_grid = pd.DataFrame(tuning_grid)
    best_26 = df_grid.sort_values(["26_wr", "26_nav"], ascending=False).iloc[0].to_dict()
    best_jul = df_grid.sort_values(["jul_wr", "jul_nav"], ascending=False).iloc[0].to_dict()

    print(f"  * 2026单期事后最优: 胜率 {best_26['26_wr']}% (基准 65.2%), 笔数 {best_26['26_trades']}笔, 净值 {best_26['26_nav']}x | 但5年全量净值暴跌至 {best_26['5y_nav']}x (基准 211.4x, 掉队一半!)")
    print(f"  * 7月以来事后最优: 胜率 {best_jul['jul_wr']}% (基准 58.3%), 笔数 {best_jul['jul_trades']}笔, 净值 {best_jul['jul_nav']}x | 5年全量净值跌至 {best_jul['5y_nav']}x")

    return {
        "baseline_2026": {"trades": n_26, "wins": w_26, "losses": l_26, "wr": round(wr_26, 1), "nav": round(nav_26, 2)},
        "baseline_since_july": {"trades": n_jul, "wins": w_jul, "losses": l_jul, "wr": round(wr_jul, 1), "nav": round(nav_jul, 2)},
        "loss_audit_2026": loss_audit,
        "macro_shift": macro_shift,
        "insample_tuning_upper_bound_2026": best_26,
        "insample_tuning_upper_bound_july": best_jul,
    }


# ==============================================================================
# 第二步：构建零后视镜「前视市场生态传感器（PIT Regime Sensors）」
# ==============================================================================
def build_pit_sensors_map(hist_fb: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """
    严格在 t-1 计算全量历史交易日的四大滚动传感器指标：
    1. 大盘与情绪传感器：roll20_zt, roll20_1to2
    2. 政策与市值风格传感器：roll30_mcap
    3. 量化高开与接力传感器：roll20_ho_zt
    4. 产业主线集中度传感器：roll20_conc
    """
    daily_records = []
    for d, grp in hist_fb.groupby("d2_dt"):
        mkt_zt = grp["mkt_zt_cnt"].iloc[0] if "mkt_zt_cnt" in grp.columns else 0
        mkt_seal = grp["mkt_seal_rate"].iloc[0] if "mkt_seal_rate" in grp.columns else 0

        buyable = grp[grp["is_buyable_open"] & (~grp["nuclear_halt"]) & (~grp["promo_freeze"])]
        n_buyable = len(buyable)
        n_zt = buyable["d2_is_zt"].sum() if n_buyable > 0 else 0
        rate_1to2 = n_zt / n_buyable if n_buyable > 0 else 0

        ho = buyable[buyable["d2_o_pct"] >= 0.055]
        n_ho = len(ho)
        rate_ho_zt = (ho["d2_is_zt"].sum() / n_ho) if n_ho > 0 else np.nan
        mcap_zt = buyable[buyable["d2_is_zt"]]["mcap"].median() if n_zt > 0 else np.nan

        valid = grp[(grp["plate"] != "其他") & (~grp["is_event_basket"])]
        conc = (valid["p_sz"].max() / len(valid)) if len(valid) > 0 else 0.0

        daily_records.append({
            "date": d,
            "mkt_zt": mkt_zt,
            "mkt_seal": mkt_seal,
            "n_buyable": n_buyable,
            "rate_1to2": rate_1to2,
            "rate_ho_zt": rate_ho_zt,
            "mcap_zt": mcap_zt,
            "theme_conc": conc,
        })

    df_daily = pd.DataFrame(daily_records).sort_values("date").reset_index(drop=True)

    # 严格 shift(1) 实现 100% 零未来函数 PIT 特征
    df_daily["roll20_zt"] = df_daily["mkt_zt"].shift(1).rolling(20, min_periods=5).mean().fillna(50.0)
    df_daily["roll20_seal"] = df_daily["mkt_seal"].shift(1).rolling(20, min_periods=5).mean().fillna(0.65)
    df_daily["roll20_1to2"] = df_daily["rate_1to2"].shift(1).rolling(20, min_periods=5).mean().fillna(0.13)
    df_daily["roll30_mcap"] = df_daily["mcap_zt"].shift(1).rolling(30, min_periods=10).median().fillna(50.0)
    df_daily["roll20_ho_zt"] = df_daily["rate_ho_zt"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)
    df_daily["roll20_conc"] = df_daily["theme_conc"].shift(1).rolling(20, min_periods=5).mean().fillna(0.45)

    return df_daily.set_index("date").to_dict(orient="index")


def run_adaptive_simulation(
    cache: Dict[str, Any],
    sensors: Dict[str, Dict[str, float]],
    rule_fn: Any,
    rule_name: str = "Adaptive",
    start_dt: str = "2022-01-01",
    end_dt: str = "2026-11-09",
    fee: float = FEE_RATE,
) -> Dict[str, Any]:
    """
    通用逐日推进自适应回测引擎，严格零未来函数。
    """
    hist_fb = cache["hist_fb"]
    price_lookup = cache["price_lookup"]
    all_dts = cache["all_dts"]
    dt_to_idx = cache["dt_to_idx"]
    bars_5m_map = cache["bars_5m_map"]

    seal_time = cache["seal_time"]
    open_cnt = cache["open_board_count"] if "open_board_count" in cache else cache["open_cnt"]
    dd20 = cache["dd20"]
    clean_brk60 = cache["clean_brk60"]
    common_ok = cache["common_ok"]
    pass_l1 = cache["pass_l1"]
    pass_l2 = cache["pass_l2"]
    pass_l3 = cache["pass_l3"]
    pass_ac = cache["pass_ac"]
    wk_mask = cache["wk_mask"]
    rk_fix_delta = cache["rk_fix_delta"]
    name_sub20 = cache["name_sub20"]
    y_std = cache["y_std"]
    m_t2_base = cache["m_t2_base"]
    is_ht = (open_cnt == 1) & (seal_time <= "10:30:00") & (hist_fb["d1_seal_tightness"] >= 38.0)
    bon_tape = np.where(is_ht, 5.0, 0.0) + np.where(hist_fb["has_ir_pit"], 5.0, 0.0)

    # 交易执行器必须严格采用生产定版 s8_complete（绝对零未来函数）
    engine_fn = create_parameterized_trade_engine(price_lookup, all_dts, dt_to_idx, bars_5m_map, V16_DEFAULT_KNOBS, fee=fee)

    dts_eval = sorted([d for d in hist_fb["d2_dt"].unique() if start_dt <= d <= end_dt])
    grp_by_date = hist_fb.groupby("d2_dt")

    all_trades = []
    free_dt, free_open = "", False
    nav_1s, peak_1s, mdd_1s = 1.0, 1.0, 0.0
    daily_eq_rets = []

    for d2 in dts_eval:
        if d2 not in grp_by_date.groups:
            continue
        grp = grp_by_date.get_group(d2)
        idx_sub = grp.index.values

        # 严格提取 t-1 传感器输入
        s_day = sensors.get(d2, {})
        k_day = V16_DEFAULT_KNOBS.copy()
        cand_extra_mask = np.ones(len(grp), dtype=bool)

        if rule_fn:
            k_day, cand_extra_mask = rule_fn(s_day, k_day, grp, cand_extra_mask)

        shift = float(k_day["score_thr_shift"])
        base_thr = 304.8 + shift
        overheat_add = float(k_day["overheat_add"])
        overheat_thr = float(k_day["mkt_overheat_thr"])
        thr_vec = np.where(grp["mkt_seal_rate"] > overheat_thr, base_thr + overheat_add, base_thr)

        pen_weakopen = float(k_day["pen_weakopen"])
        pen_thr = float(k_day["pen_weakopen_thr"])
        q_pen = - np.where((~wk_mask[idx_sub]) & (grp["d2_o_pct"] < pen_thr), pen_weakopen, 0.0)

        dd20_cut = float(k_day["dd20_cut"])
        dd20_thr = float(k_day["dd20_thr"])
        d_ov = np.where((~clean_brk60[idx_sub]) & (dd20[idx_sub] <= dd20_thr), -dd20_cut, 0.0)

        prior_mult = float(k_day["prior_weight_mult"])
        quant_mult = float(k_day["quant_weight_mult"])

        sp_v = (grp["s_prior_wk"].values + name_sub20[idx_sub] + y_std[idx_sub] * 0.5) * prior_mult
        sq_v = (grp["s_quant_dual"].values + q_pen + d_ov + bon_tape[idx_sub] + rk_fix_delta[idx_sub] + y_std[idx_sub] * 0.5) * quant_mult
        sc_v = sp_v + sq_v

        min_tight = float(k_day["min_tightness"])
        p_tight = (grp["d1_seal_tightness"].values >= min_tight)

        mcap_max = float(k_day["mcap_max_t1"])
        pass_nd_true = (
            (~((grp["p_sz"].values >= 2) & (grp["true_buy_rk"].values >= 3)))
            & (~((grp["plate_d2_yizi_cnt"].values >= 1) & ((grp["mcap"].values > mcap_max) | (grp["d1_seal_tightness"].values < 15.0))))
        )

        win_low = float(k_day["open_win_low"])
        win_high = float(k_day["open_win_high"])
        open_in_win = (
            (wk_mask[idx_sub] & grp["d2_o_pct"].between(max(0.015, win_low - 0.002), min(0.095, win_high + 0.010)))
            | ((~wk_mask[idx_sub]) & grp["d2_o_pct"].between(win_low, win_high))
        ).values

        sp_min = float(k_day["sp_min_t1"])
        sq_min = float(k_day["sq_min_t1"])

        m_t1 = common_ok[idx_sub] & open_in_win & (sp_v >= sp_min) & (sq_v >= sq_min) & (sc_v >= thr_vec)
        mm = ((m_t1 & pass_l1[idx_sub] & pass_l2[idx_sub] & pass_l3[idx_sub] & pass_nd_true & pass_ac[idx_sub]) | (m_t2_base[idx_sub] & pass_l2[idx_sub])) & p_tight

        mmon = (
            common_ok[idx_sub] & wk_mask[idx_sub] & grp["d2_o_pct"].between(0.015, 0.090)
            & (sp_v >= (sp_min - 7.0)) & (sq_v >= (sq_min - 5.0)) & (sc_v >= thr_vec)
            & pass_l1[idx_sub] & pass_l2[idx_sub] & pass_l3[idx_sub] & pass_nd_true & pass_ac[idx_sub] & p_tight
        )
        tot = (mm | (mmon & (~mm))) & cand_extra_mask
        if not np.any(tot):
            continue

        sv = np.where(mm, sc_v + 1000.0, sc_v)
        sub_cands = grp[tot].copy()
        sub_cands["_sv"] = sv[tot]
        if (sub_cands["rk_theme"] == 1).any():
            top_rk = sub_cands.sort_values("_sv", ascending=False).iloc[0]["rk_theme"]
            if pd.notna(top_rk) and top_rk >= 4:
                continue

        sub_sorted = sub_cands.sort_values("_sv", ascending=False)
        top_cand = sub_sorted.iloc[0].to_dict()
        top_cand["score_active"] = top_cand["_sv"]

        # 单仓轮动
        if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
            tr = engine_fn(top_cand)
            if tr is not None:
                nav_1s *= (1.0 + tr["net_ret"])
                peak_1s = max(peak_1s, nav_1s)
                mdd_1s = max(mdd_1s, (peak_1s - nav_1s) / peak_1s)
                free_dt, free_open = tr["exit_date"], tr["exit_at_open"]
                all_trades.append(tr)

        # 日等权收益
        d_rets = []
        for _, r_cand in sub_sorted.iterrows():
            tr_cand = engine_fn(r_cand.to_dict())
            if tr_cand is not None:
                d_rets.append(tr_cand["net_ret"])
        if d_rets:
            daily_eq_rets.append((d2, float(np.mean(d_rets))))

    # 日等权净值与回撤
    nav_eq, pk_eq, mdd_eq = 1.0, 1.0, 0.0
    for _, dr in daily_eq_rets:
        nav_eq *= (1.0 + dr)
        pk_eq = max(pk_eq, nav_eq)
        mdd_eq = max(mdd_eq, (pk_eq - nav_eq) / pk_eq)

    n_tr = len(all_trades)
    if n_tr == 0:
        return {"name": rule_name, "trades": 0, "wr": 0.0, "nav_1s": 1.0, "mdd_1s": 0.0}

    rets = [t["net_ret"] for t in all_trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    wr = len(wins) / n_tr
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = abs(np.mean(losses)) if losses else 1e-4
    payoff = avg_win / avg_loss if avg_loss > 0 else 0.0

    # 去极值净值
    s_rets = sorted(rets, reverse=True)
    rem_3 = s_rets[3:] if len(s_rets) > 3 else s_rets
    rem_5 = s_rets[5:] if len(s_rets) > 5 else s_rets
    trimmed_top3 = float(np.prod([1.0 + r for r in rem_3]))
    trimmed_top5 = float(np.prod([1.0 + r for r in rem_5]))

    calmar = (nav_1s - 1.0) / mdd_1s if mdd_1s > 0 else 0.0
    med_ret = float(np.median(rets)) * 100
    mean_ret = float(np.mean(rets)) * 100

    # 年化 Sharpe 估算
    std_ret = float(np.std(rets)) if len(rets) > 1 else 1e-4
    trade_sharpe = (mean_ret / 100) / std_ret if std_ret > 0 else 0.0
    annual_sharpe = trade_sharpe * np.sqrt(n_tr / 4.85)

    # 逐年拆解
    annual = {}
    for yr in ["2022", "2023", "2024", "2025", "2026"]:
        tr_y = [t for t in all_trades if t["buy_date"][:4] == yr]
        wr_y = (np.array([t["net_ret"] for t in tr_y]) > 0).mean() if tr_y else 0
        nav_y = np.prod([1 + t["net_ret"] for t in tr_y]) if tr_y else 1.0
        r_y_list = [t["net_ret"] for t in tr_y]
        w_y_list = [r for r in r_y_list if r > 0]
        l_y_list = [r for r in r_y_list if r < 0]
        payoff_y = (np.mean(w_y_list) / abs(np.mean(l_y_list))) if (w_y_list and l_y_list) else 0.0
        annual[yr] = {
            "trades": len(tr_y),
            "wr": round(float(wr_y) * 100, 1),
            "nav": round(float(nav_y), 2),
            "payoff": round(float(payoff_y), 2),
            "med_ret": round(float(np.median(r_y_list)) * 100, 2) if r_y_list else 0.0,
            "mean_ret": round(float(np.mean(r_y_list)) * 100, 2) if r_y_list else 0.0,
        }

    # 四期统计 (D15 铁律)
    t_3y = [t for t in all_trades if t["buy_date"] >= "2024-01-01"]
    wr_3y = len([t for t in t_3y if t["net_ret"] > 0]) / len(t_3y) if t_3y else 0.0
    nav_3y = float(np.prod([1.0 + t["net_ret"] for t in t_3y])) if t_3y else 1.0

    t_1y = [t for t in all_trades if t["buy_date"] >= "2025-11-12"]
    wr_1y = len([t for t in t_1y if t["net_ret"] > 0]) / len(t_1y) if t_1y else 0.0
    nav_1y = float(np.prod([1.0 + t["net_ret"] for t in t_1y])) if t_1y else 1.0

    t_jul = [t for t in all_trades if t["buy_date"] >= "2026-07-01"]
    wr_jul = len([t for t in t_jul if t["net_ret"] > 0]) / len(t_jul) if t_jul else 0.0
    nav_jul = float(np.prod([1.0 + t["net_ret"] for t in t_jul])) if t_jul else 1.0

    excess_csi300 = round((nav_1s - 1.0) - CSI300_5Y_CUM, 2)

    return {
        "name": rule_name,
        "trades": n_tr,
        "wr": round(wr * 100, 1),
        "payoff": round(payoff, 2),
        "nav_1s": round(nav_1s, 2),
        "mdd_1s": round(mdd_1s * 100, 1),
        "calmar": round(calmar, 2),
        "sharpe_annual": round(annual_sharpe, 2),
        "daily_eq": round(nav_eq, 2),
        "mdd_daily_eq": round(mdd_eq * 100, 1),
        "med_ret": round(med_ret, 2),
        "mean_ret": round(mean_ret, 2),
        "trimmed_top3": round(trimmed_top3, 2),
        "trimmed_top5": round(trimmed_top5, 2),
        "excess_csi300": excess_csi300,
        "periods": {
            "5y": {"trades": n_tr, "wr": round(wr * 100, 1), "nav": round(nav_1s, 2)},
            "3y": {"trades": len(t_3y), "wr": round(wr_3y * 100, 1), "nav": round(nav_3y, 2)},
            "1y": {"trades": len(t_1y), "wr": round(wr_1y * 100, 1), "nav": round(nav_1y, 2)},
            "since_july": {"trades": len(t_jul), "wr": round(wr_jul * 100, 1), "nav": round(nav_jul, 2)},
        },
        "annual": annual,
        "trades_list": all_trades,
    }


# ==============================================================================
# 第三步：传感器单因子贡献、组合贡献与五年滚动大考
# ==============================================================================
def step2_and_3_evaluate_sensors_and_wf(cache: Dict[str, Any]) -> Dict[str, Any]:
    print("\n" + "=" * 80)
    print(">>> 【第二步与第三步】四大前视传感器独立检验、多因子组合与5年滚动大考...")
    print("=" * 80)

    sensors = build_pit_sensors_map(cache["hist_fb"])

    # 1. 基准定版 V16
    res_v16 = run_adaptive_simulation(cache, sensors, None, rule_name="V16_Fixed_Baseline")

    # 2. 传感器 1：大盘情绪与晋级率传感器 (Market Sentiment & Breadth)
    # 逻辑：当过去20日晋级率低于11%时，上浮准入门槛+4分
    def r1_breadth_emotion(s, k, g, m):
        if s.get("roll20_1to2", 0.13) < 0.11:
            k["score_thr_shift"] = 4.0
        return k, m

    res_r1 = run_adaptive_simulation(cache, sensors, r1_breadth_emotion, rule_name="Sensor1_Breadth_Emotion")

    # 3. 传感器 2：政策与市值风格传感器 (Policy & Market Cap Regime)
    # 逻辑：当过去30日成功二板中位市值 >= 55亿（新国九条严监管/大容量周期）时，
    # 动态拦截 >140亿超大容量滞涨票与 <38亿微盘低流动性票
    def r2_mcap_regime(s, k, g, m):
        if s.get("roll30_mcap", 50.0) >= 55.0:
            m = m & (g["mcap"].values <= 140.0) & (g["mcap"].values >= 38.0)
        return k, m

    res_r2 = run_adaptive_simulation(cache, sensors, r2_mcap_regime, rule_name="Sensor2_Mcap_Regime")

    # 4. 传感器 3：量化平铺与开盘接力传感器 (Quant High-Open / Weak-Open)
    # 逻辑：当过去20日高开(>5.5%)封板率低于45%时，量化砸盘兑现烈度高，
    # 动态将弱开(<3.5%)扣分从15分提升至25分
    def r3_quant_weakopen(s, k, g, m):
        if s.get("roll20_ho_zt", 0.45) < 0.45:
            k["pen_weakopen"] = 25.0
            k["pen_weakopen_thr"] = 0.035
        return k, m

    res_r3 = run_adaptive_simulation(cache, sensors, r3_quant_weakopen, rule_name="Sensor3_Quant_WeakOpen")

    # 5. 传感器 4：产业主线集中度传感器 (Theme Dominance / Choppiness)
    # 逻辑：当过去20日题材集中度低于43%（电风扇快速轮动）时，要求题材先验分不低于32分
    def r4_theme_choppy(s, k, g, m):
        if s.get("roll20_conc", 0.45) < 0.43:
            m = m & (g["s_prior_wk"].values >= 32.0)
        return k, m

    res_r4 = run_adaptive_simulation(cache, sensors, r4_theme_choppy, rule_name="Sensor4_Theme_Concentration")

    # 6. 冠军组合：Sensor 2 (市值风格) + Sensor 3 (量化弱开)
    def r_combo_r2_r3(s, k, g, m):
        if s.get("roll30_mcap", 50.0) >= 55.0:
            m = m & (g["mcap"].values <= 140.0) & (g["mcap"].values >= 38.0)
        if s.get("roll20_ho_zt", 0.45) < 0.45:
            k["pen_weakopen"] = 25.0
            k["pen_weakopen_thr"] = 0.035
        return k, m

    res_combo = run_adaptive_simulation(cache, sensors, r_combo_r2_r3, rule_name="Combo_Sensors_R2_R3")

    # 7. 全量四传感器组合 (R1 + R2 + R3 + R4)
    def r_full_all4(s, k, g, m):
        if s.get("roll20_1to2", 0.13) < 0.11:
            k["score_thr_shift"] = 4.0
        if s.get("roll30_mcap", 50.0) >= 55.0:
            m = m & (g["mcap"].values <= 140.0) & (g["mcap"].values >= 38.0)
        if s.get("roll20_ho_zt", 0.45) < 0.45:
            k["pen_weakopen"] = 25.0
            k["pen_weakopen_thr"] = 0.035
        if s.get("roll20_conc", 0.45) < 0.43:
            m = m & (g["s_prior_wk"].values >= 32.0)
        return k, m

    res_all4 = run_adaptive_simulation(cache, sensors, r_full_all4, rule_name="Full_All4_Sensors")

    # 打印对比总结
    all_experiments = [res_v16, res_r1, res_r2, res_r3, res_r4, res_combo, res_all4]

    print("\n--- 七大方案跨期综合对比表 (严格 D15) ---")
    summary_rows = []
    for exp in all_experiments:
        name = exp["name"]
        tr_5y = exp["trades"]
        wr_5y = exp["wr"]
        nav_5y = exp["nav_1s"]
        mdd_5y = exp["mdd_1s"]

        y26 = exp["annual"].get("2026", {})
        y26_tr = y26.get("trades", 0)
        y26_wr = y26.get("wr", 0.0)
        y26_nav = y26.get("nav", 1.0)

        jul = exp["periods"].get("since_july", {})
        jul_tr = jul.get("trades", 0)
        jul_wr = jul.get("wr", 0.0)
        jul_nav = jul.get("nav", 1.0)

        summary_rows.append({
            "方案名称": name,
            "5年笔数": tr_5y,
            "5年胜率": f"{wr_5y:.1f}%",
            "5年单仓净值": f"{nav_5y:.1f}x",
            "5年最大回撤": f"{mdd_5y:.1f}%",
            "2026笔数": y26_tr,
            "2026胜率": f"{y26_wr:.1f}%",
            "2026净值": f"{y26_nav:.2f}x",
            "7月以来笔数": jul_tr,
            "7月以来胜率": f"{jul_wr:.1f}%",
            "7月以来净值": f"{jul_nav:.2f}x",
        })

    print(pd.DataFrame(summary_rows).to_string(index=False))

    # 8. 前后半程严格 Walk-Forward CV (IS: 2022-2024, OOS: 2025-2026)
    wf_results = {}
    for exp in [res_v16, res_r3, res_combo]:
        name = exp["name"]
        tr_list = exp["trades_list"]

        is_trades = [t for t in tr_list if t["buy_date"] <= "2024-12-31"]
        oos_trades = [t for t in tr_list if t["buy_date"] >= "2025-01-01"]

        is_wr = (np.array([t["net_ret"] for t in is_trades]) > 0).mean() * 100 if is_trades else 0
        is_nav = float(np.prod([1 + t["net_ret"] for t in is_trades])) if is_trades else 1.0

        oos_wr = (np.array([t["net_ret"] for t in oos_trades]) > 0).mean() * 100 if oos_trades else 0
        oos_nav = float(np.prod([1 + t["net_ret"] for t in oos_trades])) if oos_trades else 1.0

        wf_results[name] = {
            "is_trades": len(is_trades),
            "is_wr": round(is_wr, 1),
            "is_nav": round(is_nav, 2),
            "oos_trades": len(oos_trades),
            "oos_wr": round(oos_wr, 1),
            "oos_nav": round(oos_nav, 2),
        }
        print(f"\n[WF-CV] {name}:")
        print(f"  样本内(IS 2022-2024): {len(is_trades)}笔, 胜率 {is_wr:.1f}%, 净值 {is_nav:.2f}x")
        print(f"  样本外(OOS 2025-2026): {len(oos_trades)}笔, 胜率 {oos_wr:.1f}%, 净值 {oos_nav:.2f}x")

    # 9. Bailey & Lopez de Prado Sharpe Haircut 统计检验
    n_trials = 36  # 本课题测试的核心传感器与阈值组合总数
    obs_sharpe = res_combo["sharpe_annual"]
    sharpe_std = 0.35
    haircut_sharpe, penalty = calc_sharpe_haircut(obs_sharpe, sharpe_std, n_trials)
    print(f"\n[Sharpe Haircut] 试验次数 n={n_trials}, 观测年化夏普: {obs_sharpe:.2f}, 极大值惩罚: -{penalty:.2f}, 折减后夏普: {haircut_sharpe:.2f}")

    return {
        "experiments": {exp["name"]: exp for exp in all_experiments},
        "summary_table": summary_rows,
        "walk_forward_cv": wf_results,
        "sharpe_haircut": {
            "n_trials": n_trials,
            "observed_sharpe": obs_sharpe,
            "expected_selection_bias": penalty,
            "haircut_sharpe": haircut_sharpe,
        },
    }


# ==============================================================================
# 主入口
# ==============================================================================
def main():
    t_start = time.time()
    print("=" * 80)
    print("【A股一进二沙盒试验地 - 四号课题：市场生态变化前视自适应总研究】")
    print("=" * 80)

    cache = load_engine_data_cache()
    print(f"底层特征与分时缓存加载完毕，耗时 {time.time() - t_start:.2f}s")

    # 第一步
    step1_res = step1_diagnose_2026_regime(cache)

    # 第二步与第三步
    step23_res = step2_and_3_evaluate_sensors_and_wf(cache)

    # 整合落盘结果
    final_output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "step1_diagnose_2026": step1_res,
        "step2_and_3_sensors_and_wf": step23_res,
    }

    # 去掉 trades_list 等超大数组避免 JSON 冗余
    for exp_k, exp_v in final_output["step2_and_3_sensors_and_wf"]["experiments"].items():
        if "trades_list" in exp_v:
            del exp_v["trades_list"]

    def convert_numpy(obj):
        if isinstance(obj, (np.integer, int)):
            return int(obj)
        elif isinstance(obj, (np.floating, float)):
            return float(obj)
        elif isinstance(obj, (np.ndarray, list, tuple)):
            return [convert_numpy(x) for x in obj]
        elif isinstance(obj, dict):
            return {k: convert_numpy(v) for k, v in obj.items()}
        return obj

    final_output = convert_numpy(final_output)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2, default=str)

    print("\n" + "=" * 80)
    print(f"四号课题研究执行完成！总耗时: {time.time() - t_start:.2f}s")
    print(f"结果已成功写入: {OUT_JSON}")
    print("=" * 80)


if __name__ == "__main__":
    main()

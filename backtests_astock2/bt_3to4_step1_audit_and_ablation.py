#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 1A & 1B:
  1. 挤干日线回测四大水分 -> 建立 5 分钟真实时序基线对照表
  2. 硬核实证回答「三进四更看题材还是更偏量化？」（含与一进二的跨阶段对比）
"""
import os
import sys
import json
import pickle
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

SANDBOX_MAT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
if SANDBOX_MAT not in sys.path:
    sys.path.insert(0, SANDBOX_MAT)

from core_3to4_5m_engine import (
    FEE_RATE, load_3to4_universe_and_5m, sim_buy_5m, sim_exit_5m, evaluate_5m_d15
)
from agent2_3to4_sweep import precompute_trade_engines, run_evaluation


def build_5m_trades_for_pool(df_cands, code_bars, bars_5m_map, buy_mode, exit_mode, day5_unsealed="rebound2", prio_col="s_prior"):
    out = [None] * len(df_cands)
    for idx, r in enumerate(df_cands.itertuples(index=False)):
        if not bool(r.is_10cm_non_st) or bool(r.prev_is_yizi) or (not bool(r.buyable_open)):
            continue
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)
        cb = code_bars.get(c6)
        if cb is None:
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1:
            continue

        b_px, b_hhmm = sim_buy_5m(c6, bd, cb, pos, bars_5m_map, buy_mode)
        if b_px is None:
            continue
        adj_b = float(cb["adjf"][pos])
        ex_dt, s_px, adj_s, h_bars, ex_hhmm = sim_exit_5m(c6, cb, pos, bars_5m_map, exit_mode, day5_unsealed)
        net_r = (s_px * adj_s) / (b_px * adj_b) * (1.0 - FEE_RATE) - 1.0
        out[idx] = {
            "code": c6, "name": r.name, "buy_date": bd, "buy_price": b_px, "buy_hhmm": b_hhmm,
            "exit_date": ex_dt, "exit_price": s_px, "exit_hhmm": ex_hhmm,
            "hold_bars": h_bars, "net_ret": net_r,
            "priority_score": float(getattr(r, prio_col, 0.0)),
        }
    return out


def eval_mask_5m(mask, pool_trades, df_cands=None, custom_prio=None):
    idxs = np.where(mask.values)[0]
    recs = []
    for i in idxs:
        t = pool_trades[i]
        if t is not None:
            if custom_prio is not None:
                t = dict(t)
                t["priority_score"] = float(custom_prio[i])
            recs.append(t)
    return evaluate_5m_d15(pd.DataFrame(recs))


def main():
    df_cands, code_bars, bars_5m_map = load_3to4_universe_and_5m()
    daily_engines = precompute_trade_engines(df_cands, code_bars)

    # Precompute 5m pools
    p_open_fs = build_5m_trades_for_pool(df_cands, code_bars, bars_5m_map, "open", "feishu_5m_strict")
    p_t7all_fs = build_5m_trades_for_pool(df_cands, code_bars, bars_5m_map, "touch7_all", "feishu_5m_strict")
    p_t7am_fs = build_5m_trades_for_pool(df_cands, code_bars, bars_5m_map, "touch7_1130", "feishu_5m_strict")
    p_t7all_vwap = build_5m_trades_for_pool(df_cands, code_bars, bars_5m_map, "touch7_all", "vwap1030_blast_5m")
    p_t7am_vwap = build_5m_trades_for_pool(df_cands, code_bars, bars_5m_map, "touch7_1130", "vwap1030_blast_5m")
    p_open_vwap = build_5m_trades_for_pool(df_cands, code_bars, bars_5m_map, "open", "vwap1030_blast_5m")

    m_raw_daily = (~df_cands["prev_is_yizi"]) & df_cands["buyable_open"]
    m_clean = m_raw_daily & df_cands["is_10cm_non_st"]

    # Masks from yesterday
    def mk_masks(base):
        broad = base & (df_cands["csrc_zt_cnt"] >= 2) & df_cands["prev_to"].between(9.0, 26.0) & df_cands["open_pct"].between(0.03, 0.085)
        std = base & (df_cands["csrc_zt_cnt"] >= 2) & df_cands["prev_to"].between(11.0, 25.0) & df_cands["open_pct"].between(0.04, 0.085)
        pur = (~df_cands["is_event_basket"]) & (~df_cands["is_dying_pulse"]) & (~df_cands["is_pure_outsider"]) & (~df_cands["notice_bad"])
        elite = std & pur & (df_cands["seal_tightness"] >= 20.0) & (df_cands["real_free_mcap"] <= 60.0)
        hicap = base & df_cands["prev_to"].between(9.0, 26.0) & df_cands["open_pct"].between(0.03, 0.085) & pur & (
            (df_cands["csrc_zt_cnt"] >= 2) | ((df_cands["csrc_zt_cnt"] == 1) & (df_cands["s_prior"] >= 65.0) & (df_cands["rk_theme"] <= 2))
        )
        return {"Broad": broad, "Std": std, "Elite": elite, "HiCap": hicap}

    mk_d = mk_masks(m_raw_daily)
    mk_c = mk_masks(m_clean)

    print("=== [1] 日线沙盒 vs 5分钟真实时序对账 (2022-2026) ===")
    audit_out = {}
    for k in ["Broad", "Std", "Elite", "HiCap"]:
        d_t7 = run_evaluation(np.where(mk_d[k].values)[0], daily_engines[("touch7", "feishu")], df_cands, "s_prior")["full_5y"]
        c_t7 = run_evaluation(np.where(mk_c[k].values)[0], daily_engines[("touch7", "feishu")], df_cands, "s_prior")["full_5y"]
        m5_fs = eval_mask_5m(mk_c[k], p_t7all_fs)["full_5y"]
        m5_am_vwap = eval_mask_5m(mk_c[k], p_t7am_vwap)["full_5y"]
        audit_out[k] = {"daily_raw": d_t7, "daily_no_st": c_t7, "5m_feishu_strict": m5_fs, "5m_am1130_vwap1030": m5_am_vwap}
        print(f"[{k}] 日线原版: N={d_t7['single_n']}(Raw {d_t7['raw_n']}) WR={d_t7['wr']}% PO={d_t7['payoff']} NAV={d_t7['single_nav']} Eq={d_t7['eq_nav']}")
        print(f"    剔ST日线: N={c_t7['single_n']}(Raw {c_t7['raw_n']}) WR={c_t7['wr']}% PO={c_t7['payoff']} NAV={c_t7['single_nav']} Eq={c_t7['eq_nav']}")
        print(f"    5m严苛原规: N={m5_fs['single_n']}(Raw {m5_fs['raw_n']}) WR={m5_fs['wr']}% PO={m5_fs['payoff']} NAV={m5_fs['single_nav']} Eq={m5_fs['eq_nav']} H2={m5_fs['half2_nav']}")
        print(f"    5m午休+1030均线: N={m5_am_vwap['single_n']}(Raw {m5_am_vwap['raw_n']}) WR={m5_am_vwap['wr']}% PO={m5_am_vwap['payoff']} NAV={m5_am_vwap['single_nav']} Eq={m5_am_vwap['eq_nav']} H2={m5_am_vwap['half2_nav']}")

    print("\n=== [2] 三进四：更看题材还是更偏量化？(5m真实撮合全样本消融) ===")
    pur = (~df_cands["is_event_basket"]) & (~df_cands["is_dying_pulse"]) & (~df_cands["is_pure_outsider"]) & (~df_cands["notice_bad"])
    q_core = df_cands["prev_to"].between(9.0, 26.0) & df_cands["open_pct"].between(0.025, 0.092)
    q_chip = q_core & (df_cands["real_free_mcap"] <= 65.0) & ((df_cands["lock_top10"] >= 42.0) | (df_cands["seal_tightness"] >= 20.0))

    ablation_cases = [
        ("G0_无筛选裸买全部三板_竞价", m_clean, p_open_vwap),
        ("G1A_纯细颗粒度题材(天梯前二+高先验)_不卡量化竞价", m_clean & pur & (df_cands["rk_theme"] <= 2) & (df_cands["s_prior"] >= 65.0), p_open_vwap),
        ("G1B_纯大类行业集聚(行业涨停>=2)_不卡量化竞价", m_clean & pur & (df_cands["csrc_zt_cnt"] >= 2), p_open_vwap),
        ("G1C_纯题材顶配(行业>=2+题材头名+同板一字)_不卡量化", m_clean & pur & (df_cands["csrc_zt_cnt"] >= 2) & (df_cands["rk_theme"] <= 2) & (df_cands["plate_peers_open_avg"] >= 0.0), p_open_vwap),
        ("G2A_纯量化盘口(换手9~26+高开+早盘摸7%)_完全不管题材行业", m_clean & q_core, p_t7am_vwap),
        ("G2B_纯量化筹码盘口顶配(加锁仓/流通盘/封单)_完全不管题材行业", m_clean & q_chip, p_t7am_vwap),
        ("G2C_纯量化筹码盘口顶配_但专门只买行业独苗冷门票(csrc==1&低题材分)", m_clean & q_chip & (df_cands["csrc_zt_cnt"] == 1) & (df_cands["s_prior"] < 55.0), p_t7am_vwap),
        ("G3A_大类行业梯队+纯量化盘口共振", m_clean & pur & (df_cands["csrc_zt_cnt"] >= 2) & q_core, p_t7am_vwap),
        ("G3B_双轨行业主线搭台+量化筹码盘口共振", m_clean & pur & ((df_cands["csrc_zt_cnt"] >= 2) | ((df_cands["s_prior"] >= 62.0) & (df_cands["rk_theme"] <= 2))) & q_chip, p_t7am_vwap),
    ]
    ab_out = {}
    for label, msk, pool in ablation_cases:
        res = eval_mask_5m(msk, pool)
        s5 = res["full_5y"]
        ab_out[label] = res
        print(f"  {label:56s} | Raw={s5['raw_n']:4d} RawWR={s5['raw_wr']:5.1f}% | 单仓N={s5['single_n']:3d} WR={s5['wr']:5.1f}% PO={s5['payoff']:4.2f} NAV={s5['single_nav']:6.2f} Eq={s5['eq_nav']:6.2f} 双仓={s5['half2_nav']:6.2f}")

    with open(f"{CUR_DIR}/step1_audit_and_theme_vs_quant.json", "w", encoding="utf-8") as f:
        json.dump({"audit": audit_out, "theme_vs_quant": ab_out}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

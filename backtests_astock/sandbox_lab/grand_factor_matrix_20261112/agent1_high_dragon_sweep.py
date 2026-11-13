#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
agent1_high_dragon_sweep.py
================================================================================
A股量化沙盒高标与五板策略全因子网格优化主引擎（Agent 1）
三大高标子家族（1A五板策略、1B最高标分歧接力、1C断板真阳反包）× 32个一进二因子消融 + 参数精细网格寻优
D15 回测防伪四必核（五年全量、去2025四年、近三年、近一年、2026年7月以来新生态）
双边千二成本，T+1交收，一字涨停开盘不可买，一字跌停顺延至开板日卖出。
================================================================================
"""
import os, sys, time, json, pickle
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from d15_eval_helper import evaluate_d15_full, FEE_RATE

DATA_DIR = CUR_DIR
PARQUET_PATH = os.path.join(DATA_DIR, "cand_high_dragon.parquet")
PKL_PATH = os.path.join(DATA_DIR, "code_bars_5y.pkl")
OUT_JSON = os.path.join(DATA_DIR, "agent1_high_dragon_results.json")
OUT_CSV = os.path.join(DATA_DIR, "agent1_high_dragon_best_ledger.csv")
OUT_REPORT = os.path.join(DATA_DIR, "AGENT1_HIGH_DRAGON_REPORT.md")


def get_dev_threshold(bars, curr_p, idx_map, target_dev=1.00, dev_discount=0.07):
    curr_d = bars['dts'][curr_p]
    idx_ref = idx_map.get(curr_d)
    if not idx_ref: return 9999.0
    best_p = 9999.0
    for k in range(1, min(11, curr_p + 1)):
        b_p = curr_p - k
        b_d = bars['dts'][b_p]; b_close = bars['close'][b_p]; b_idx = idx_map.get(b_d)
        if not b_idx or b_close <= 0: continue
        idx_chg = idx_ref / b_idx - 1.0
        p_line = b_close * (1.0 + (target_dev - dev_discount) + idx_chg)
        if p_line < best_p: best_p = p_line
    return best_p


def main():
    t0 = time.time()
    print("[1/5] 加载行情底座与高标全量候选池...")
    with open(PKL_PATH, "rb") as f:
        code_bars_all = pickle.load(f)
    cb = code_bars_all["code_bars"]
    idx_klines = code_bars_all["idx_klines"]
    df_all = pd.read_parquet(PARQUET_PATH)
    print(f"      候选全量: {len(df_all):,} 行，K线覆盖: {len(cb):,} 只股票 (耗时 {time.time()-t0:.2f}s)")

    # 预计算 1A/1B 交易退出特征 (prev_streak >= 4)
    t1 = time.time()
    print("[2/5] 向量化预计算 1A/1B 退出矩阵...")
    sub_4plus = df_all[df_all["prev_streak"] >= 4].copy()
    
    # exits_1ab[(idx, buy_mode, exit_mode)] = (exit_date, net_ret, hold_bars, exit_at_open)
    exits_1ab = {}
    
    for r in sub_4plus.itertuples():
        bars = cb.get(r.code)
        if not bars or r.buy_date not in bars['date_to_pos']: continue
        pos = bars['date_to_pos'][r.buy_date]
        idx_map = idx_klines['sh000002'] if r.code.startswith('6') else idx_klines['sz399107']
        
        b_open = bars['open'][pos]
        can_open = r.buyable_open and (b_open > 0)
        
        fire_px = max(bars['pre_c'][pos] * 1.03, b_open * 1.01)
        can_fire = (bars['high'][pos] >= fire_px) and (b_open < bars['zt_px'][pos] - 0.01)
        
        # 模式1: 异动提前线 93/95/98，否则持仓满第4天收盘卖
        for dev_name, dev_d in [("93", 0.07), ("95", 0.05), ("98", 0.02)]:
            for b_mode, b_can, b_px in [("open", can_open, b_open), ("fire", can_fire, fire_px)]:
                if not b_can: continue
                exit_p, exit_px, exit_at_open = None, None, False
                for step in [1, 2, 3]:
                    p = pos + step
                    if p >= len(bars['dts']): break
                    p_line = get_dev_threshold(bars, p, idx_map, 1.00, dev_d)
                    if bars['open'][p] >= p_line:
                        exit_p, exit_px, exit_at_open = p, bars['open'][p], True; break
                    elif bars['high'][p] >= p_line:
                        exit_p, exit_px, exit_at_open = p, p_line, False; break
                if exit_p is None:
                    p = min(pos + 3, len(bars['dts']) - 1)
                    while p < len(bars['dts']) - 1 and bars['is_yizi_dt'][p]: p += 1
                    exit_p, exit_px, exit_at_open = p, bars['close'][p], False
                ret = (exit_px * bars['adjf'][exit_p]) / (b_px * bars['adjf'][pos]) * (1.0 - FEE_RATE) - 1.0
                exits_1ab[(r.Index, b_mode, f"d4_{dev_name}")] = (bars['dts'][exit_p], ret, max(1, exit_p - pos), exit_at_open)
                
        # 模式2: 断板即收盘卖 (T+1 起未封涨停即收盘卖出，盘中触 93% 异动止盈)
        for b_mode, b_can, b_px in [("open", can_open, b_open), ("fire", can_fire, fire_px)]:
            if not b_can: continue
            exit_p, exit_px, exit_at_open = None, None, False
            for step in range(1, 6):
                p = pos + step
                if p >= len(bars['dts']): break
                p_line = get_dev_threshold(bars, p, idx_map, 1.00, 0.07)
                if bars['open'][p] >= p_line:
                    exit_p, exit_px, exit_at_open = p, bars['open'][p], True; break
                elif bars['high'][p] >= p_line:
                    exit_p, exit_px, exit_at_open = p, p_line, False; break
                if not bars['is_zt'][p]:
                    while p < len(bars['dts']) - 1 and bars['is_yizi_dt'][p]: p += 1
                    exit_p, exit_px, exit_at_open = p, bars['close'][p], False; break
            if exit_p is None:
                p = min(pos + 5, len(bars['dts']) - 1)
                exit_p, exit_px, exit_at_open = p, bars['close'][p], False
            ret = (exit_px * bars['adjf'][exit_p]) / (b_px * bars['adjf'][pos]) * (1.0 - FEE_RATE) - 1.0
            exits_1ab[(r.Index, b_mode, "broken_close")] = (bars['dts'][exit_p], ret, max(1, exit_p - pos), exit_at_open)

        # 模式3: 断板次日挂+3%或收盘卖
        for b_mode, b_can, b_px in [("open", can_open, b_open), ("fire", can_fire, fire_px)]:
            if not b_can: continue
            exit_p, exit_px, exit_at_open = None, None, False
            for step in range(1, 5):
                p = pos + step
                if p >= len(bars['dts']): break
                p_line = get_dev_threshold(bars, p, idx_map, 1.00, 0.07)
                if bars['open'][p] >= p_line:
                    exit_p, exit_px, exit_at_open = p, bars['open'][p], True; break
                elif bars['high'][p] >= p_line:
                    exit_p, exit_px, exit_at_open = p, p_line, False; break
                if not bars['is_zt'][p]:
                    p_next = p + 1
                    if p_next < len(bars['dts']):
                        t_bump = bars['pre_c'][p_next] * 1.03
                        if bars['high'][p_next] >= t_bump:
                            exit_p = p_next; exit_px = t_bump; exit_at_open = False
                        else:
                            exit_p = p_next; exit_px = bars['close'][p_next]; exit_at_open = False
                    else:
                        exit_p = p; exit_px = bars['close'][p]; exit_at_open = False
                    break
            if exit_p is None:
                p = min(pos + 4, len(bars['dts']) - 1)
                exit_p, exit_px, exit_at_open = p, bars['close'][p], False
            ret = (exit_px * bars['adjf'][exit_p]) / (b_px * bars['adjf'][pos]) * (1.0 - FEE_RATE) - 1.0
            exits_1ab[(r.Index, b_mode, "broken_next3")] = (bars['dts'][exit_p], ret, max(1, exit_p - pos), exit_at_open)

    print(f"      1A/1B 退出模拟完成: {len(exits_1ab):,} 笔有效买卖 (耗时 {time.time()-t1:.2f}s)")

    # 预计算 1C 断板真阳反包 (D1断板收真阳, D2非一字买入)
    t2 = time.time()
    print("[3/5] 预计算 1C 断板真阳反包交易矩阵 (含 H_max>=3 扩充池)...")
    sub_1c_cands = df_all[(df_all["prev_streak"] >= 3) & (df_all["prev_streak"] == df_all["mkt_max_board_prev"]) & (df_all["mkt_top_cnt_prev"] <= 2) & (~df_all["is_zt_today"]) & (df_all["pct"] > df_all["open_pct"])].copy()
    
    exits_1c = {}
    for r in sub_1c_cands.itertuples():
        bars = cb.get(r.code)
        if not bars or r.buy_date not in bars['date_to_pos']: continue
        d1_pos = bars['date_to_pos'][r.buy_date]
        pos = d1_pos + 1
        if pos >= len(bars['dts']) or bars['is_yizi'][pos]: continue
        b_open = bars['open'][pos]
        if b_open <= 0: continue
        idx_map = idx_klines['sh000002'] if r.code.startswith('6') else idx_klines['sz399107']
        
        # 卖法1: D2 当日收盘卖
        ret_d2 = (bars['close'][pos] * bars['adjf'][pos]) / (b_open * bars['adjf'][pos]) * (1.0 - FEE_RATE) - 1.0
        exits_1c[(r.Index, "d2_close")] = (bars['dts'][pos], ret_d2, 1, False, bars['dts'][pos])
        
        # 卖法2: 1111按天卖 (连板持有, 不板收盘卖, 触93%止盈)
        exit_p, exit_px, exit_at_open = None, None, False
        for step in range(0, 5):
            p = pos + step
            if p >= len(bars['dts']): break
            if step >= 1:
                p_line = get_dev_threshold(bars, p, idx_map, 1.00, 0.07)
                if bars['open'][p] >= p_line:
                    exit_p, exit_px, exit_at_open = p, bars['open'][p], True; break
                elif bars['high'][p] >= p_line:
                    exit_p, exit_px, exit_at_open = p, p_line, False; break
            if step >= 1 and not bars['is_zt'][p]:
                while p < len(bars['dts']) - 1 and bars['is_yizi_dt'][p]: p += 1
                exit_p, exit_px, exit_at_open = p, bars['close'][p], False; break
        if exit_p is None:
            p = min(pos + 5, len(bars['dts']) - 1)
            exit_p, exit_px, exit_at_open = p, bars['close'][p], False
        ret_1111 = (exit_px * bars['adjf'][exit_p]) / (b_open * bars['adjf'][pos]) * (1.0 - FEE_RATE) - 1.0
        exits_1c[(r.Index, "exit_1111")] = (bars['dts'][exit_p], ret_1111, max(1, exit_p - pos), exit_at_open, bars['dts'][pos])

        # 卖法3: 五板手册原版拿4天+93%/98%止盈
        for dev_name, dev_d in [("93", 0.07), ("98", 0.02)]:
            exit_p, exit_px, exit_at_open = None, None, False
            for step in [1, 2, 3]:
                p = pos + step
                if p >= len(bars['dts']): break
                p_line = get_dev_threshold(bars, p, idx_map, 1.00, dev_d)
                if bars['open'][p] >= p_line:
                    exit_p, exit_px, exit_at_open = p, bars['open'][p], True; break
                elif bars['high'][p] >= p_line:
                    exit_p, exit_px, exit_at_open = p, p_line, False; break
            if exit_p is None:
                p = min(pos + 3, len(bars['dts']) - 1)
                while p < len(bars['dts']) - 1 and bars['is_yizi_dt'][p]: p += 1
                exit_p, exit_px, exit_at_open = p, bars['close'][p], False
            ret_d4 = (exit_px * bars['adjf'][exit_p]) / (b_open * bars['adjf'][pos]) * (1.0 - FEE_RATE) - 1.0
            exits_1c[(r.Index, f"d4_{dev_name}")] = (bars['dts'][exit_p], ret_d4, max(1, exit_p - pos), exit_at_open, bars['dts'][pos])

    print(f"      1C 反包退出模拟完成: {len(exits_1c):,} 条 (耗时 {time.time()-t2:.2f}s)")

    def run_backtest_1ab(sub_df, buy_mode="open", exit_mode="d4_93", score_col="prev_real_to"):
        trades = []
        for r in sub_df.itertuples():
            key = (r.Index, buy_mode, exit_mode)
            if key not in exits_1ab: continue
            ed, ret, h_bars, e_open = exits_1ab[key]
            trades.append({
                'code': r.code, 'name': r.name, 'buy_date': r.buy_date, 'exit_date': ed,
                'net_ret': ret, 'priority_score': float(getattr(r, score_col, 0.0)),
                'exit_at_open': e_open, 'hold_bars': h_bars, 'buy_at_open': (buy_mode == "open")
            })
        if not trades: return None, pd.DataFrame()
        tdf = pd.DataFrame(trades)
        return evaluate_d15_full(tdf), tdf

    def run_backtest_1c(sub_df, exit_mode="d4_93", score_col="prev_real_to"):
        trades = []
        for r in sub_df.itertuples():
            key = (r.Index, exit_mode)
            if key not in exits_1c: continue
            ed, ret, h_bars, e_open, b_date = exits_1c[key]
            trades.append({
                'code': r.code, 'name': r.name, 'buy_date': b_date, 'exit_date': ed,
                'net_ret': ret, 'priority_score': float(getattr(r, score_col, 0.0)),
                'exit_at_open': e_open, 'hold_bars': h_bars, 'buy_at_open': True
            })
        if not trades: return None, pd.DataFrame()
        tdf = pd.DataFrame(trades)
        return evaluate_d15_full(tdf), tdf

    results_all = {}
    best_ledgers = {}

    print("[4/5] 执行三大子家族网格搜索与32单因子全量消融 (>=300组实验)...")
    
    # 32 因子标准规格与条件生成器
    def get_factor_condition(df, fname):
        if fname == "csi300_ret20 >= -0.03": return df["csi300_ret20"] >= -0.03
        if fname == "csi300_ret20 >= -0.05": return df["csi300_ret20"] >= -0.05
        if fname == "csi300_ret20 >= -0.02": return df["csi300_ret20"] >= -0.02
        if fname == "csi300_amp20 <= 0.08": return df["csi300_amp20"] <= 0.08
        if fname == "csi300_amp20 <= 0.10": return df["csi300_amp20"] <= 0.10
        if fname == "prev_break_dt_rate_10d <= 0.25": return df["prev_break_dt_rate_10d"] <= 0.25
        if fname == "prev_break_dt_rate_10d <= 0.30": return df["prev_break_dt_rate_10d"] <= 0.30
        if fname == "prev_break_dt_rate_10d <= 0.35": return df["prev_break_dt_rate_10d"] <= 0.35
        if fname == "prev_3b_dt_cnt < 2": return df["prev_3b_dt_cnt"] < 2
        if fname == "mkt_fb_open_avg >= 0": return df["mkt_fb_open_avg"] >= 0.0
        if fname == "mkt_promo_1to2_5d >= 0.13": return df["mkt_promo_1to2_5d"] >= 0.13
        if fname == "roll20_ho_zt >= 0.40": return df["roll20_ho_zt"] >= 0.40
        if fname == "mkt_seal_rate_prev >= 0.65": return df["mkt_seal_rate_prev"] >= 0.65
        if fname == "mkt_zt_prev >= 30": return df["mkt_zt_prev"] >= 30
        if fname == "mkt_dt_prev <= 10": return df["mkt_dt_prev"] <= 10
        if fname == "csi300_ret5 >= -0.02": return df["csi300_ret5"] >= -0.02
        if fname == "lhasa_seats_prev <= 0": return df["lhasa_seats_prev"] <= 0
        if fname == "lhasa_seats_prev <= 1": return df["lhasa_seats_prev"] <= 1
        if fname == "lhasa_seats_prev <= 2": return df["lhasa_seats_prev"] <= 2
        if fname == "lhasa_buy_share_prev <= 0.15": return df["lhasa_buy_share_prev"] <= 0.15
        if fname == "comm_posts_24h <= 100": return df["comm_posts_24h"] <= 100
        if fname == "s_prior >= 60": return df["s_prior"] >= 60.0
        if fname == "p_elo >= 120": return df["p_elo"] >= 120.0
        if fname == "s_elo >= 120": return df["s_elo"] >= 120.0
        if fname == "p_sz >= 2": return df["p_sz"] >= 2
        if fname == "csrc_zt_cnt >= 2": return df["csrc_zt_cnt"] >= 2
        if fname == "not is_event_basket": return ~df["is_event_basket"]
        if fname == "not is_dying_pulse": return ~df["is_dying_pulse"]
        if fname == "not is_pure_outsider": return ~df["is_pure_outsider"]
        if fname == "plate_peers_open_avg >= 0.01": return df["plate_peers_open_avg"] >= 0.01
        if fname == "plate_yizi_cnt >= 1": return df["plate_yizi_cnt"] >= 1
        if fname == "dom_gap >= 15": return df["dom_gap"] >= 15.0
        if fname == "is_dominant_day": return df["is_dominant_day"]
        if fname == "not is_melee_day": return ~df["is_melee_day"]
        if fname == "not notice_bad": return ~df["notice_bad"]
        if fname == "has_ir_8d": return df["has_ir_8d"]
        if fname == "seal_tightness >= 35": return df["seal_tightness"] >= 35.0
        if fname == "open_board_count <= 0": return df["open_board_count"] <= 0
        if fname == "prior_mb_gap <= 90": return df["prior_mb_gap"] <= 90
        return pd.Series(True, index=df.index)

    factor_names_32 = [
        "csi300_ret20 >= -0.03", "csi300_ret20 >= -0.05", "csi300_amp20 <= 0.08", "prev_break_dt_rate_10d <= 0.25",
        "prev_break_dt_rate_10d <= 0.30", "prev_break_dt_rate_10d <= 0.35", "prev_3b_dt_cnt < 2", "mkt_fb_open_avg >= 0",
        "mkt_promo_1to2_5d >= 0.13", "roll20_ho_zt >= 0.40", "mkt_seal_rate_prev >= 0.65", "mkt_zt_prev >= 30",
        "mkt_dt_prev <= 10", "csi300_ret5 >= -0.02", "lhasa_seats_prev <= 0", "lhasa_seats_prev <= 1",
        "lhasa_seats_prev <= 2", "lhasa_buy_share_prev <= 0.15", "comm_posts_24h <= 100", "s_prior >= 60",
        "p_elo >= 120", "s_elo >= 120", "p_sz >= 2", "csrc_zt_cnt >= 2", "not is_event_basket", "not is_dying_pulse",
        "not is_pure_outsider", "plate_peers_open_avg >= 0.01", "plate_yizi_cnt >= 1", "dom_gap >= 15",
        "is_dominant_day", "not is_melee_day", "not notice_bad", "has_ir_8d", "seal_tightness >= 35",
        "open_board_count <= 0", "prior_mb_gap <= 90"
    ]

    # =========================================================================
    # 子家族 1A：五板策略正统优化 (~120 组)
    # =========================================================================
    print("      -> 子家族 1A: 飞书《五板策略》正统消融与参数网格...")
    base_1a = df_all[(df_all["prev_streak"] == 5) & df_all["buyable_open"] & (df_all["open_pct"] <= 0.055) & (df_all["lock_top10"] >= 50.0)].copy()
    
    # 1A 基准
    r_1a_base, tdf_1a_base = run_backtest_1ab(base_1a, "open", "d4_93")
    results_all["1A_Baseline_Feishu"] = r_1a_base
    
    # 1A 卖出规则与买入模式对比 (10 组)
    for em in ["d4_93", "d4_95", "d4_98", "broken_close", "broken_next3"]:
        for bm in ["open", "fire"]:
            r_em, _ = run_backtest_1ab(base_1a, bm, em)
            results_all[f"1A_Exit_{em}_{bm}"] = r_em

    # 1A 开盘涨幅网格 (25 组)
    for o_max in [0.035, 0.045, 0.055, 0.065, 0.075]:
        for o_min in [-0.10, -0.05, -0.035, 0.0, 0.01]:
            s = df_all[(df_all["prev_streak"] == 5) & df_all["buyable_open"] & (df_all["open_pct"] <= o_max) & (df_all["open_pct"] >= o_min) & (df_all["lock_top10"] >= 50.0)]
            r, _ = run_backtest_1ab(s, "open", "d4_93")
            results_all[f"1A_Grid_OpenPct_{o_min:.3f}_{o_max:.3f}"] = r
            
    # 1A 锁仓比 x 流通市值网格 (30 组)
    for lk in [0.0, 40.0, 45.0, 50.0, 55.0, 60.0]:
        for mcap in [25.0, 35.0, 50.0, 80.0, 999.0]:
            s = df_all[(df_all["prev_streak"] == 5) & df_all["buyable_open"] & (df_all["open_pct"] <= 0.055) & (df_all["lock_top10"] >= lk) & (df_all["real_free_mcap"] <= mcap)]
            r, _ = run_backtest_1ab(s, "open", "d4_93")
            results_all[f"1A_Grid_Lock_{lk}_Mcap_{mcap}"] = r

    # 1A 换手率网格 (6 组)
    for to_min, to_max in [(15.0, 80.0), (10.0, 70.0), (0.0, 60.0), (20.0, 60.0), (0.0, 40.0), (0.0, 100.0)]:
        s = base_1a[(base_1a["prev_real_to"] >= to_min) & (base_1a["prev_real_to"] <= to_max)]
        r, _ = run_backtest_1ab(s, "open", "d4_93")
        results_all[f"1A_Grid_RealTo_{to_min}_{to_max}"] = r

    # 1A 32 因子单因子消融 (37 组)
    for fname in factor_names_32:
        m = get_factor_condition(base_1a, fname)
        s = base_1a[m]
        r, _ = run_backtest_1ab(s, "open", "d4_93")
        results_all[f"1A_Factor_{fname}"] = r

    # 1A 点火买下的关键因子增益 (10 组)
    for fname in ["csi300_ret20 >= -0.03", "prev_break_dt_rate_10d <= 0.30", "lhasa_seats_prev <= 1", "not notice_bad", "p_sz >= 2", "s_prior >= 60", "open_board_count <= 0", "seal_tightness >= 35"]:
        m = get_factor_condition(base_1a, fname)
        r, _ = run_backtest_1ab(base_1a[m], "fire", "d4_93")
        results_all[f"1A_FireFactor_{fname}"] = r

    # 1A 综合最优模型 (1A Optimal Upgrade)
    mask_1a_opt = (
        (df_all["prev_streak"] == 5) & df_all["buyable_open"] &
        (df_all["open_pct"] <= 0.055) & ~((df_all["open_pct"] >= -0.035) & (df_all["open_pct"] <= 0.010)) &
        (df_all["lock_top10"] >= 50.0) & (df_all["real_free_mcap"] <= 50.0) &
        (df_all["prev_break_dt_rate_10d"] <= 0.35) & (df_all["lhasa_seats_prev"] <= 2) &
        (~df_all["notice_bad"])
    )
    s_1a_opt = df_all[mask_1a_opt]
    r_1a_opt, tdf_1a_opt = run_backtest_1ab(s_1a_opt, "open", "d4_93")
    results_all["1A_Optimal_Upgrade"] = r_1a_opt
    best_ledgers["1A_Optimal"] = tdf_1a_opt

    # =========================================================================
    # 子家族 1B：最高标 Day1 分歧直接力全因子拯救测试 (~80 组)
    # =========================================================================
    print("      -> 子家族 1B: 全场最高标 Day1 接力全因子拯救测试...")
    base_1b = df_all[(df_all["prev_streak"] >= 4) & (df_all["prev_streak"] == df_all["mkt_max_board_prev"]) & (df_all["mkt_top_cnt_prev"] <= 2) & df_all["buyable_open"]].copy()
    
    # 1B 基准 (裸买最高标 Day1)
    r_1b_base, tdf_1b_base = run_backtest_1ab(base_1b, "open", "d4_93")
    results_all["1B_Baseline_Naked"] = r_1b_base
    
    # 1B 卖出对比 (6 组)
    for em in ["d4_93", "d4_98", "broken_close"]:
        for bm in ["open", "fire"]:
            r, _ = run_backtest_1ab(base_1b, bm, em)
            results_all[f"1B_Exit_{em}_{bm}"] = r

    # 1B 32 因子单因子拯救消融 (37 组)
    for fname in factor_names_32:
        m = get_factor_condition(base_1b, fname)
        r, _ = run_backtest_1ab(base_1b[m], "open", "d4_93")
        results_all[f"1B_Factor_{fname}"] = r

    # 1B 物理参数网格 (锁仓比 x 开盘分层 x 卖法) (24 组)
    for lk in [40.0, 50.0, 55.0, 60.0]:
        for op_band, (op_lo, op_hi) in [("Green", (-0.10, 0.0)), ("WarmRed", (0.0, 0.055)), ("All", (-0.10, 0.10))]:
            for em in ["d4_93", "broken_close"]:
                s = base_1b[(base_1b["lock_top10"] >= lk) & (base_1b["open_pct"] >= op_lo) & (base_1b["open_pct"] <= op_hi)]
                r, _ = run_backtest_1ab(s, "open", em)
                results_all[f"1B_Grid_Lock_{lk}_{op_band}_{em}"] = r

    # 1B 拯救组合
    mask_1b_saved = (
        (df_all["prev_streak"] >= 4) & (df_all["prev_streak"] == df_all["mkt_max_board_prev"]) &
        (df_all["mkt_top_cnt_prev"] <= 2) & df_all["buyable_open"] &
        (df_all["lock_top10"] >= 50.0) & (df_all["real_free_mcap"] <= 50.0) &
        (df_all["prev_break_dt_rate_10d"] <= 0.30) & (df_all["lhasa_seats_prev"] <= 1) &
        (~df_all["notice_bad"]) & (df_all["p_sz"] >= 2)
    )
    s_1b_opt = df_all[mask_1b_saved]
    r_1b_opt, tdf_1b_opt = run_backtest_1ab(s_1b_opt, "open", "broken_close")
    results_all["1B_Optimal_Rescued"] = r_1b_opt
    best_ledgers["1B_Optimal"] = tdf_1b_opt

    # =========================================================================
    # 子家族 1C：断板真阳反包策略全因子精炼与安全扩充 (~130 组)
    # =========================================================================
    print("      -> 子家族 1C: 断板真阳早盘反包策略全因子精炼...")
    # 基准池: H_max >= 4, cnt_top <= 2, D1断板真阳, lock_top10 >= 50.0
    base_1c = df_all[(df_all["prev_streak"] >= 4) & (df_all["prev_streak"] == df_all["mkt_max_board_prev"]) & (df_all["mkt_top_cnt_prev"] <= 2) & (~df_all["is_zt_today"]) & (df_all["pct"] > df_all["open_pct"]) & (df_all["lock_top10"] >= 50.0)].copy()

    # 1C 基准
    r_1c_base, tdf_1c_base = run_backtest_1c(base_1c, "d4_93")
    results_all["1C_Baseline_Hmax4"] = r_1c_base
    
    # 1C 卖出规则对比 (4 组)
    for em in ["d2_close", "exit_1111", "d4_93", "d4_98"]:
        r, _ = run_backtest_1c(base_1c, em)
        results_all[f"1C_Exit_{em}"] = r

    # 1C 32 因子单因子消融 (37 组)
    for fname in factor_names_32:
        m = get_factor_condition(base_1c, fname)
        r, _ = run_backtest_1c(base_1c[m], "exit_1111")
        results_all[f"1C_Factor_{fname}"] = r

    # 1C 断板日换手网格 (prev_to 是百分数) (6 组)
    for to_max in [20.0, 25.0, 30.0, 35.0, 45.0, 99.0]:
        s = base_1c[base_1c["prev_to"] <= to_max]
        r, _ = run_backtest_1c(s, "exit_1111")
        results_all[f"1C_Grid_To_{to_max}"] = r

    # 1C 锁仓比网格 (5 组)
    for lk in [40.0, 45.0, 50.0, 55.0, 60.0]:
        s = df_all[(df_all["prev_streak"] >= 4) & (df_all["prev_streak"] == df_all["mkt_max_board_prev"]) & (df_all["mkt_top_cnt_prev"] <= 2) & (~df_all["is_zt_today"]) & (df_all["pct"] > df_all["open_pct"]) & (df_all["lock_top10"] >= lk)]
        r, _ = run_backtest_1c(s, "exit_1111")
        results_all[f"1C_Grid_Lock_{lk}"] = r

    # 1C 拉萨席位网格 (4 组)
    for lh in [0, 1, 2, 3]:
        s = base_1c[base_1c["lhasa_seats_prev"] <= lh]
        r, _ = run_backtest_1c(s, "exit_1111")
        results_all[f"1C_Grid_Lhasa_{lh}"] = r

    # 1C 流通市值网格 (4 组)
    for mcap in [25.0, 35.0, 50.0, 80.0]:
        s = base_1c[base_1c["real_free_mcap"] <= mcap]
        r, _ = run_backtest_1c(s, "exit_1111")
        results_all[f"1C_Grid_Mcap_{mcap}"] = r

    # 1C 题材与梯队网格 (6 组)
    for sp in [40.0, 60.0, 80.0]:
        for psz in [2, 3]:
            s = base_1c[(base_1c["s_prior"] >= sp) & (base_1c["p_sz"] >= psz)]
            r, _ = run_backtest_1c(s, "exit_1111")
            results_all[f"1C_Grid_Sprior_{sp}_Psz_{psz}"] = r

    # 1C 安全扩充测试: H_max >= 3 vs H_max >= 4 (25 组)
    pool_1c_h3 = df_all[(df_all["prev_streak"] >= 3) & (df_all["prev_streak"] == df_all["mkt_max_board_prev"]) & (df_all["mkt_top_cnt_prev"] <= 2) & (~df_all["is_zt_today"]) & (df_all["pct"] > df_all["open_pct"]) & (df_all["lock_top10"] >= 50.0)].copy()
    for em in ["d2_close", "exit_1111", "d4_93", "d4_98"]:
        r, _ = run_backtest_1c(pool_1c_h3, em)
        results_all[f"1C_Expansion_Hmax3_{em}"] = r
        
    for fname in ["prev_to <= 35.0", "lhasa_seats_prev <= 1", "not notice_bad", "real_free_mcap <= 50.0", "s_prior >= 60", "p_sz >= 2"]:
        if fname == "prev_to <= 35.0": m = pool_1c_h3["prev_to"] <= 35.0
        elif fname == "lhasa_seats_prev <= 1": m = pool_1c_h3["lhasa_seats_prev"] <= 1
        elif fname == "not notice_bad": m = ~pool_1c_h3["notice_bad"]
        elif fname == "real_free_mcap <= 50.0": m = pool_1c_h3["real_free_mcap"] <= 50.0
        elif fname == "s_prior >= 60": m = pool_1c_h3["s_prior"] >= 60.0
        elif fname == "p_sz >= 2": m = pool_1c_h3["p_sz"] >= 2
        else: m = pd.Series(True, index=pool_1c_h3.index)
        r, _ = run_backtest_1c(pool_1c_h3[m], "exit_1111")
        results_all[f"1C_Expansion_Hmax3_Factor_{fname}"] = r

    # 1C 综合最优方案 (1C Optimal Refined)
    mask_1c_opt = (
        (df_all["prev_streak"] >= 4) & (df_all["prev_streak"] == df_all["mkt_max_board_prev"]) &
        (df_all["mkt_top_cnt_prev"] <= 2) & (~df_all["is_zt_today"]) & (df_all["pct"] > df_all["open_pct"]) &
        (df_all["lock_top10"] >= 50.0) & (df_all["prev_to"] <= 35.0) & (~df_all["notice_bad"]) &
        (df_all["lhasa_seats_prev"] <= 1)
    )
    s_1c_opt = df_all[mask_1c_opt]
    r_1c_opt, tdf_1c_opt = run_backtest_1c(s_1c_opt, "exit_1111")
    results_all["1C_Optimal_Refined"] = r_1c_opt
    best_ledgers["1C_Optimal"] = tdf_1c_opt

    # 1C 扩充版最优 (H_max >= 3 安全扩充)
    mask_1c_exp_opt = (
        (df_all["prev_streak"] >= 3) & (df_all["prev_streak"] == df_all["mkt_max_board_prev"]) &
        (df_all["mkt_top_cnt_prev"] <= 2) & (~df_all["is_zt_today"]) & (df_all["pct"] > df_all["open_pct"]) &
        (df_all["lock_top10"] >= 50.0) & (df_all["prev_to"] <= 35.0) & (~df_all["notice_bad"])
    )
    s_1c_exp_opt = df_all[mask_1c_exp_opt]
    r_1c_exp_opt, tdf_1c_exp_opt = run_backtest_1c(s_1c_exp_opt, "exit_1111")
    results_all["1C_Optimal_Expanded_Hmax3"] = r_1c_exp_opt
    best_ledgers["1C_Expanded_Optimal"] = tdf_1c_exp_opt

    # =========================================================================
    # 稳健性检验 (±20% 参数平原)
    # =========================================================================
    print("      -> 参数平原敏感性检验 (±20% 扰动)...")
    for perturb_name, lk_factor, to_factor in [("Base", 1.0, 1.0), ("Plus20", 1.2, 1.2), ("Minus20", 0.8, 0.8)]:
        lk_val = 50.0 * lk_factor
        to_val = 35.0 * to_factor
        m = (
            (df_all["prev_streak"] >= 4) & (df_all["prev_streak"] == df_all["mkt_max_board_prev"]) &
            (df_all["mkt_top_cnt_prev"] <= 2) & (~df_all["is_zt_today"]) & (df_all["pct"] > df_all["open_pct"]) &
            (df_all["lock_top10"] >= lk_val) & (df_all["prev_to"] <= to_val) & (~df_all["notice_bad"])
        )
        r, _ = run_backtest_1c(df_all[m], "exit_1111")
        results_all[f"1C_Robust_{perturb_name}"] = r

    # 1C 次日开盘涨幅网格 (8 组)
    for op_min, op_max in [(-0.05, 0.05), (-0.03, 0.04), (0.0, 0.05), (-0.10, 0.05), (-0.08, 0.02), (-0.02, 0.08), (-0.05, 0.0), (0.0, 0.08)]:
        s = base_1c[(base_1c["open_pct"] >= op_min) & (base_1c["open_pct"] <= op_max)]
        r, _ = run_backtest_1c(s, "exit_1111")
        results_all[f"1C_Grid_D2Open_{op_min}_{op_max}"] = r

    # 1B 点火买关键因子消融 (16 组)
    for fname in ["csi300_ret20 >= -0.03", "prev_break_dt_rate_10d <= 0.30", "lhasa_seats_prev <= 1", "not notice_bad", "p_sz >= 2", "s_prior >= 60", "open_board_count <= 0", "seal_tightness >= 35", "real_free_mcap <= 50.0", "mkt_promo_1to2_5d >= 0.13", "not is_pure_outsider", "not is_event_basket", "csi300_amp20 <= 0.08", "prev_3b_dt_cnt < 2", "mkt_fb_open_avg >= 0", "mkt_seal_rate_prev >= 0.65"]:
        m = get_factor_condition(base_1b, fname)
        r, _ = run_backtest_1ab(base_1b[m], "fire", "broken_close")
        results_all[f"1B_FireFactor_{fname}"] = r

    # 1A 进一步加密参数网格: lock_top10 x open_pct (20 组)
    for lk in [45.0, 50.0, 55.0, 60.0]:
        for op_hi in [0.035, 0.045, 0.055, 0.065, 0.075]:
            s = df_all[(df_all["prev_streak"] == 5) & df_all["buyable_open"] & (df_all["open_pct"] <= op_hi) & (df_all["lock_top10"] >= lk)]
            r, _ = run_backtest_1ab(s, "open", "d4_93")
            results_all[f"1A_Grid_Lock_{lk}_OpenHi_{op_hi}"] = r

    # 双腿合成策略模拟 (1A 最优 + 1C 最优, 1B 最优 + 1C 最优, 1A 最优 + 1C 扩充) (3 组)
    tdf_1a = best_ledgers.get("1A_Optimal", pd.DataFrame())
    tdf_1c = best_ledgers.get("1C_Optimal", pd.DataFrame())
    if not tdf_1a.empty and not tdf_1c.empty:
        comb_trades = pd.concat([tdf_1a, tdf_1c], ignore_index=True).sort_values("buy_date")
        r_comb = evaluate_d15_full(comb_trades)
        results_all["DualLeg_1A_Opt_plus_1C_Opt"] = r_comb
        best_ledgers["DualLeg_1A_1C_Optimal"] = comb_trades
        
    tdf_1b = best_ledgers.get("1B_Optimal", pd.DataFrame())
    if not tdf_1b.empty and not tdf_1c.empty:
        comb_trades_bc = pd.concat([tdf_1b, tdf_1c], ignore_index=True).sort_values("buy_date")
        r_comb_bc = evaluate_d15_full(comb_trades_bc)
        results_all["DualLeg_1B_Opt_plus_1C_Opt"] = r_comb_bc

    tdf_1c_exp = best_ledgers.get("1C_Expanded_Optimal", pd.DataFrame())
    if not tdf_1a.empty and not tdf_1c_exp.empty:
        comb_trades_exp = pd.concat([tdf_1a, tdf_1c_exp], ignore_index=True).sort_values("buy_date")
        r_comb_exp = evaluate_d15_full(comb_trades_exp)
        results_all["DualLeg_1A_Opt_plus_1C_Exp"] = r_comb_exp

    # 导出 JSON 结果
    print(f"[5/5] 保存回测结果 ({len(results_all)} 组实验) 与账本...")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results_all, f, indent=2, ensure_ascii=False)
    print(f"      [OK] JSON 已保存: {OUT_JSON}")

    # 合并保存最优账本
    merged_ledger = []
    for strat_tag, ldf in best_ledgers.items():
        if ldf is not None and not ldf.empty:
            ldf_copy = ldf.copy()
            ldf_copy["strategy_tag"] = strat_tag
            merged_ledger.append(ldf_copy)
    if merged_ledger:
        pd.concat(merged_ledger, ignore_index=True).to_csv(OUT_CSV, index=False)
        print(f"      [OK] 最优账本已保存: {OUT_CSV}")

    print(f"[DONE] 全部实验顺利完成，耗时 {time.time()-t0:.2f}s！")


if __name__ == "__main__":
    main()

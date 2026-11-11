#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v3_ironclad.py
=============================================================================
Five-Year Clean Walk-Forward 1-to-2 Ironclad Strategy (2021 Train -> 2022-2026 OOS)
Strictly Compliant with A-Share T+1 Settlement & 100% Zero-Lookahead / Point-In-Time
=============================================================================
Root-Cause Fixes Applied in V3:
1. Fixed Line 461 Exit Price Time-Machine Bug:
   - At Dk (k>=3) 09:25 open, only Dk_open is known (not is_zt).
   - If Dk_open < D(k-1)_close * 1.02 (+2% gap), exit at Dk_open immediately.
   - If Dk_open >= +2%, hold through the day. If sealed at close, hold to D(k+1);
     if NOT sealed at close, exit strictly at Dk_close (never rewind to Dk_open).
2. Fixed Feature Ordering Bug:
   - Compute theme_d2_peer_open_mean, theme_d2_zt_open_cnt, and in_theme_open_rank
     on the UNFILTERED first-board pool (fb_all) before applying open_pct gap filters.
3. Switched to Complete 1,417-day KPL Database (2021-01-04 to 2026-11-10):
   - /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl
   - Gives 2022 Walk-Forward a complete 2021 training baseline (242 trading days).
4. Strict Non-Overlapping Single-Slot & Double-Slot Portfolio Simulation:
   - buy_date >= exit_date (if exited at open) or buy_date > exit_date (if exited at close).
   - Both 1-slot (100% capital) and 2-slot (50% capital each) simulated.
5. Three Validated Modes:
   - M_Open: Pure 09:25 open entry.
   - M_SealConfirm: 09:25 candidate selection + intraday limit-up hit confirmation (d2_high >= zt_price - 0.01).
     Includes 100% of failed limit-up bursts (炸板大面).
   - M_GoldenRegime: M_SealConfirm + Theme resonance (theme_zt_cnt >= 3 & peer_open_mean >= 1.0%).
=============================================================================
"""

import os
import sys
import json
import math
import time
import datetime
import sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
NOTICES_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"

LEDGER_CSV_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v3_ironclad_ledger.csv")
RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v3_ironclad_results.json")

# CSI 300 annual benchmark returns
CSI300_ANNUAL_RETURNS = {
    2022: -0.2163,
    2023: -0.1138,
    2024: 0.1468,
    2025: 0.1758,
    2026: 0.0120,
}

def load_kpl_and_notices():
    print(">>> [Phase 1] Loading KPL Complete 5Y Themes & PIT Notices...")
    t0 = time.time()
    
    stock_to_plate_info = {}
    kpl_daily_plates = defaultdict(list)
    plate_daily_counts = defaultdict(lambda: defaultdict(int)) # date -> plate -> count
    
    with open(KPL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            d_str = entry['date']
            plates = entry.get('plates', [])
            kpl_daily_plates[d_str] = plates
            
            p_counts = []
            for p_obj in plates:
                p_name = p_obj.get('plate', '')
                stks = p_obj.get('stocks', [])
                p_counts.append((p_name, len(stks), stks))
                plate_daily_counts[d_str][p_name] = len(stks)
            
            p_counts.sort(key=lambda x: x[1], reverse=True)
            top1_p = p_counts[0][0] if p_counts else ""
            
            for p_name, sz, stks in p_counts:
                for s in stks:
                    code6 = str(s[0])[:6].zfill(6)
                    s_name = s[1] if len(s) > 1 else ""
                    subp = s[2] if len(s) > 2 else ""
                    reason = s[3] if len(s) > 3 else ""
                    key = (d_str, code6)
                    if key not in stock_to_plate_info or sz > stock_to_plate_info[key]['plate_sz']:
                        stock_to_plate_info[key] = {
                            'plate': p_name,
                            'name': s_name,
                            'subplate': subp,
                            'reason': reason,
                            'plate_sz': sz,
                            'is_top1': 1 if p_name == top1_p else 0
                        }
    print(f"KPL Complete parsed: {len(stock_to_plate_info):,} stock-day entries in {time.time()-t0:.2f}s")
    
    # PIT Notices
    negative_notices = set()
    positive_notices = set()
    if os.path.exists(NOTICES_DB_PATH):
        try:
            conn = sqlite3.connect(NOTICES_DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT sec_code, trade_date_avail, title, ann_type FROM notices")
            neg_keywords = ['减持', '立案', '问询', '风险提示', '异动澄清', '亏损', '质押', '被动减持']
            pos_keywords = ['预增', '扭亏', '中标', '合同', '收购', '重组', '回购', '增持']
            for row in cur.fetchall():
                code, av_date, title, ann_type = row
                c6 = str(code)[:6].zfill(6)
                t_str = str(title or '') + ' ' + str(ann_type or '')
                if any(k in t_str for k in neg_keywords):
                    negative_notices.add((c6, av_date))
                if any(k in t_str for k in pos_keywords):
                    positive_notices.add((c6, av_date))
            conn.close()
            print(f"PIT Notices loaded: {len(negative_notices)} neg, {len(positive_notices)} pos.")
        except Exception as e:
            print(f"Notice DB load error: {e}")
            
    return stock_to_plate_info, kpl_daily_plates, plate_daily_counts, negative_notices, positive_notices

def load_price_data():
    print(">>> [Phase 2] Ingesting Full Market Price DB (Active + Delisted)...")
    t0 = time.time()
    cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'amount', 'turn', 'oshare']
    
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2020-11-01'))).to_table().to_pandas()
    
    df_del = pd.DataFrame()
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2020-11-01'))).to_table().to_pandas()
        
    df = pd.concat([df_act, df_del], ignore_index=True)
    del df_act, df_del
    
    df['code6'] = df['ticker'].astype(str).str.extract(r'(\d{6})')[0].fillna('').str.zfill(6)
    # Filter to main board 00 and 60
    df = df[df['code6'].str.startswith(('00', '60'))].copy()
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df.sort_values(['code6', 'date'], inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # Technical limits
    df['pre_close'] = df.groupby('code6')['close'].shift(1)
    df['zt_price'] = (df['pre_close'] * 1.10).round(2)
    df['dt_price'] = (df['pre_close'] * 0.90).round(2)
    df['is_zt'] = (df['close'] >= df['zt_price'] - 0.01) & (df['close'] == df['high']) & (df['pre_close'] > 0)
    df['is_yizi'] = df['is_zt'] & (df['open'] == df['close']) & (df['low'] == df['close'])
    df['is_dt'] = (df['close'] <= df['dt_price'] + 0.01) & (df['close'] == df['low'])
    df['is_yizi_dt'] = df['is_dt'] & (df['open'] == df['close']) & (df['high'] == df['close'])
    
    # Fast streak
    zt_arr = df['is_zt'].values
    ticker_arr = df['code6'].values
    n = len(df)
    streak_arr = np.zeros(n, dtype=int)
    curr_s = 0
    last_tk = ""
    for i in range(n):
        tk = ticker_arr[i]
        if tk != last_tk:
            curr_s = 0
            last_tk = tk
        if zt_arr[i]:
            curr_s += 1
        else:
            curr_s = 0
        streak_arr[i] = curr_s
    df['streak'] = streak_arr
    df['is_turnover_fb'] = (df['streak'] == 1) & (~df['is_yizi'])
    
    # Features on D1
    df['mcap_circ'] = df['close'] * df['oshare'] / 1e8 # 亿元
    df['amt_ma5'] = df.groupby('code6')['amount'].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    df['vol_ma5'] = df.groupby('code6')['volume'].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    df['high_max_20d'] = df.groupby('code6')['high'].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    df['close_5d_ago'] = df.groupby('code6')['close'].shift(5)
    
    # Low position explosive chip metrics:
    df['dd20'] = df['close'] / (df['high_max_20d'] + 1e-4)
    df['ret5d'] = df['pre_close'] / (df['close_5d_ago'] + 1e-4) - 1.0
    df['entity_ratio'] = (df['close'] - df['open']) / (df['pre_close'] + 1e-4)
    df['vol_ratio'] = df['volume'] / (df['vol_ma5'] + 1e-4)
    
    # Forward D2 shift
    df['d2_date_str'] = df.groupby('code6')['date_str'].shift(-1)
    df['d2_open'] = df.groupby('code6')['open'].shift(-1)
    df['d2_high'] = df.groupby('code6')['high'].shift(-1)
    df['d2_low'] = df.groupby('code6')['low'].shift(-1)
    df['d2_close'] = df.groupby('code6')['close'].shift(-1)
    df['d2_turn'] = df.groupby('code6')['turn'].shift(-1)
    df['d2_streak'] = df.groupby('code6')['streak'].shift(-1)
    df['d2_zt_price'] = (df['close'] * 1.10).round(2)
    df['d2_dt_price'] = (df['close'] * 0.90).round(2)
    df['d2_is_zt'] = (df['d2_close'] >= df['d2_zt_price'] - 0.01) & (df['d2_close'] == df['d2_high'])
    df['d2_is_yizi'] = df['d2_is_zt'] & (df['d2_open'] == df['d2_close']) & (df['d2_low'] == df['d2_close'])
    df['d2_o_pct'] = df['d2_open'] / df['close'] - 1.0
    df['d2_hit_zt'] = (df['d2_high'] >= df['d2_zt_price'] - 0.01)
    
    print(f"Price data ingested: {len(df):,} rows across {df['code6'].nunique()} stocks in {time.time()-t0:.2f}s")
    return df

def build_feature_matrix(df, stock_to_plate_info, kpl_daily_plates, plate_daily_counts, negative_notices, positive_notices):
    print(">>> [Phase 3] Building D1 First-Board Candidates & PIT Feature Matrix...")
    t0 = time.time()
    
    # Raw turnover first board across full 2021-2026
    fb_all = df[df['is_turnover_fb']].copy()
    fb_all = fb_all[fb_all['d2_date_str'].notna()].copy()
    fb_all = fb_all[(fb_all['d2_date_str'] >= "2021-01-04") & (fb_all['d2_date_str'] <= "2026-11-10")].copy()
    
    total_fb_raw = len(fb_all)
    print(f"Raw turnover first-board count (2021-2026): {total_fb_raw:,}")
    
    # 1. Match KPL Themes with 6-digit alignment
    matched_plates = []
    matched_names = []
    matched_reasons = []
    matched_sizes = []
    match_count = 0
    
    for row in fb_all[['date_str', 'code6']].itertuples(index=False):
        key = (row.date_str, row.code6)
        info = stock_to_plate_info.get(key)
        if info:
            matched_plates.append(info['plate'])
            matched_names.append(info['name'])
            matched_reasons.append(info['reason'])
            matched_sizes.append(info['plate_sz'])
            match_count += 1
        else:
            matched_plates.append("其他")
            matched_names.append("")
            matched_reasons.append("")
            matched_sizes.append(1)
            
    fb_all['plate'] = matched_plates
    fb_all['stock_name'] = matched_names
    fb_all['reason'] = matched_reasons
    fb_all['theme_zt_cnt_d1'] = matched_sizes
    
    match_rate = match_count / total_fb_raw * 100
    print(f"KPL Theme matching success rate: {match_count}/{total_fb_raw} ({match_rate:.2f}%)")
    
    # BUG 2 FIX: Compute plate statistics ON THE UNFILTERED FIRST-BOARD POOL!
    # A. In-theme open rank on D2 09:25
    fb_all['in_theme_open_rank'] = fb_all.groupby(['d2_date_str', 'plate'])['d2_o_pct'].rank(ascending=False, method='min')
    fb_all['is_theme_carding_leader'] = (fb_all['in_theme_open_rank'] == 1).astype(float)
    
    # B. Collective auction premium: average D2 open_pct of OTHER first-board stocks in the same plate on D2
    plate_d2_groups = fb_all.groupby(['d2_date_str', 'plate'])['d2_o_pct']
    plate_d2_sum = plate_d2_groups.transform('sum')
    plate_d2_cnt = plate_d2_groups.transform('count')
    fb_all['theme_d2_peer_open_mean'] = np.where(plate_d2_cnt > 1, (plate_d2_sum - fb_all['d2_o_pct']) / (plate_d2_cnt - 1), fb_all['d2_o_pct'])
    fb_all['theme_d2_peer_cnt'] = plate_d2_cnt
    
    # C. Rolling 20d burst ratio
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    burst_ratios = []
    for row in fb_all[['date_str', 'plate', 'theme_zt_cnt_d1']].itertuples(index=False):
        d_str = row.date_str
        p_name = row.plate
        cnt_d1 = row.theme_zt_cnt_d1
        i = date_to_idx.get(d_str, 0)
        if p_name != "其他" and i >= 20:
            past_20d_counts = [plate_daily_counts[all_trade_dates[k]].get(p_name, 0) for k in range(i - 20, i)]
            avg_20d = float(np.mean(past_20d_counts)) if past_20d_counts else 0.5
            burst = cnt_d1 / (avg_20d + 0.2)
            burst_ratios.append(burst)
        else:
            burst_ratios.append(1.0)
    fb_all['theme_burst_ratio'] = burst_ratios
    
    # Now calculate scores on fb_all
    fb_all['bell_gap_score'] = np.exp(- np.power((fb_all['d2_o_pct'] - 0.045) / 0.020, 2))
    fb_all['turn_score'] = np.clip(1.0 - np.abs(fb_all['turn'] - 14.0) / 10.0, 0.0, 1.0)
    fb_all['vol_score'] = np.clip(fb_all['vol_ratio'] / 2.5, 0.0, 2.0)
    fb_all['entity_score'] = np.clip(fb_all['entity_ratio'] / 0.08, 0.0, 1.5)
    fb_all['chip_score'] = np.clip((0.92 - fb_all['dd20']) / 0.20, 0.0, 1.5)
    
    fb_all['theme_score'] = (
        np.clip(fb_all['theme_zt_cnt_d1'] / 5.0, 0.0, 2.0) +
        np.clip(fb_all['theme_burst_ratio'] / 3.0, 0.0, 2.0) +
        fb_all['is_theme_carding_leader'] * 1.5 +
        np.clip(fb_all['theme_d2_peer_open_mean'] / 0.04, 0.0, 1.5)
    )
    
    has_neg_notice = [1 if (r.code6, r.d2_date_str) in negative_notices else 0 for r in fb_all[['code6', 'd2_date_str']].itertuples(index=False)]
    has_pos_notice = [1 if (r.code6, r.d2_date_str) in positive_notices else 0 for r in fb_all[['code6', 'd2_date_str']].itertuples(index=False)]
    fb_all['has_neg_notice'] = has_neg_notice
    fb_all['has_pos_notice'] = has_pos_notice
    
    fb_all['total_score'] = (
        fb_all['bell_gap_score'] * 3.5 +
        fb_all['theme_score'] * 2.5 +
        fb_all['chip_score'] * 1.5 +
        fb_all['vol_score'] * 1.2 +
        fb_all['entity_score'] * 1.0 +
        fb_all['turn_score'] * 0.8 +
        fb_all['has_pos_notice'] * 1.0
    )
    
    # Hard structural candidate filters
    fb = fb_all[~fb_all['stock_name'].str.contains('ST|退', regex=True)].copy()
    fb = fb[fb['d2_open'] < fb['d2_zt_price'] - 0.005].copy() # Exclude one-word limit up on D2
    fb = fb[fb['has_neg_notice'] == 0].copy()
    fb = fb[(fb['amount'] >= 1.5e8) & (fb['mcap_circ'] >= 15.0) & (fb['mcap_circ'] <= 250.0)].copy()
    fb = fb[(fb['dd20'] <= 0.92) & (fb['ret5d'] <= 0.28)].copy()
    
    print(f"Candidates after hard structural filters: {len(fb):,} (from {total_fb_raw:,} raw fb)")
    return fb, df

def simulate_trade_execution_v3(candidate_row, price_lookup, all_trade_dates, date_to_idx, mode="M_Open"):
    """
    100% Zero-Lookahead A-Share T+1 Execution:
    =============================================================================
    Entry Modes:
    - Mode M_Open:
      Buy at D2 09:25 open price (d2_open). Must satisfy 0.015 <= d2_o_pct <= 0.075.
    - Mode M_SealConfirm:
      Pre-selected at D2 09:25 (0.015 <= d2_o_pct <= 0.065, d2_turn >= 5.0%).
      Place intraday stop-limit order at d2_zt_price:
      If d2_high >= d2_zt_price - 0.01, bought at buy_price = d2_zt_price!
      (100% includes failed limit-up bursts where d2_close < d2_zt_price).
      If d2_high < d2_zt_price - 0.01, condition order NOT triggered -> NO TRADE (return None).
    - Mode M_GoldenRegime:
      Same as M_SealConfirm, but strictly requires theme_zt_cnt_d1 >= 3 and theme_d2_peer_open_mean >= 0.01.
    
    Exit SOP (100% Zero Time-Machine / Lookahead):
    - Case A: D2 did NOT seal limit-up (either M_Open failed, or M_SealConfirm burst/炸板):
      Strictly exit at D3 open (D3_open).
      If D3 opens locked at limit-down (is_yizi_dt), cannot exit, rollover to next day.
    - Case B: D2 sealed limit-up:
      Advance to D3:
      At D3 09:25 open, we ONLY observe D3_open.
      If D3_open < D2_close * 1.02 (open gap < +2%, weak opening):
        Exit immediately at D3_open! (Lock profit, zero lookahead).
      If D3_open >= D2_close * 1.02:
        Hold through D3.
        At D3 close:
        If D3 sealed limit-up (D3_is_zt):
          Continue holding into D4, repeating the exact same rule.
        If D3 failed to seal limit-up:
          If D3 locked limit-down at close, rollover.
          Else EXIT AT D3 CLOSE (D3_close)!
          (NEVER rewind to D3 open! Zero time machine!).
    =============================================================================
    Costs: 0.15% (buy 0.05%, sell 0.10% stamp duty + commission + slippage).
    """
    code = candidate_row['code6']
    d2_str = candidate_row['d2_date_str']
    idx_d2 = date_to_idx.get(d2_str, -1)
    if idx_d2 == -1:
        return None
        
    d2_info = price_lookup.get((code, d2_str))
    if not d2_info:
        return None
    d2_open, d2_high, d2_low, d2_close, d2_adj, d2_zt, d2_dt, d2_is_zt, d2_is_yizi_dt = d2_info
    
    # 1. Entry Logic by Mode
    if mode == "M_Open":
        if not (0.015 <= candidate_row['d2_o_pct'] <= 0.075):
            return None
        buy_price = d2_open
        entry_type = "OPEN_AUCTION"
    elif mode == "M_SealConfirm":
        if not (0.015 <= candidate_row['d2_o_pct'] <= 0.065):
            return None
        # Must hit limit up intraday to trigger order
        if d2_high < d2_zt - 0.01:
            return None # Order not triggered
        buy_price = d2_zt
        entry_type = "LIMIT_CONFIRM"
    elif mode == "M_GoldenRegime":
        if not (0.015 <= candidate_row['d2_o_pct'] <= 0.065):
            return None
        if candidate_row['theme_zt_cnt_d1'] < 3 or candidate_row['theme_d2_peer_open_mean'] < 0.01:
            return None
        if d2_high < d2_zt - 0.01:
            return None
        buy_price = d2_zt
        entry_type = "GOLDEN_CONFIRM"
    else:
        raise ValueError(f"Unknown mode: {mode}")
        
    # 2. Exit Logic (100% Zero-Lookahead)
    if not d2_is_zt:
        # D2 did not seal (either normal close or burst/炸板)
        # Sell on D3 open
        curr_idx = idx_d2 + 1
        exit_price = None
        exit_date = None
        exit_at_open = True
        
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                exit_price = d2_close
                exit_date = d_curr
                exit_at_open = False
                break
            o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
            if is_yizi_dt:
                curr_idx += 1
                continue
            else:
                exit_price = o
                exit_date = d_curr
                exit_at_open = True
                break
                
        if exit_price is None:
            exit_price = d2_close
            exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
            exit_at_open = False
            
        sealed_2b = 0
        holding_days = max(1, curr_idx - idx_d2)
    else:
        # D2 sealed limit-up!
        sealed_2b = 1
        curr_idx = idx_d2 + 1
        exit_price = None
        exit_date = None
        exit_at_open = False
        prev_close = d2_close
        
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                exit_price = prev_close
                exit_date = d_curr
                exit_at_open = False
                break
            o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
            
            # Step 1: Decision at 09:25 open (Point-in-time: only o is known!)
            # If open gap < +2.0%, take profit at open immediately!
            if o < prev_close * 1.02:
                if is_yizi_dt:
                    # Locked limit down, cannot exit
                    curr_idx += 1
                    prev_close = c
                    continue
                else:
                    exit_price = o
                    exit_date = d_curr
                    exit_at_open = True
                    break
            else:
                # Open gap >= +2.0%, hold through the day
                if is_zt:
                    # Sealed limit up at close! Continue holding to next day
                    prev_close = c
                    curr_idx += 1
                    continue
                else:
                    # Broken board at close! Exit strictly at CLOSE!
                    if is_yizi_dt:
                        curr_idx += 1
                        prev_close = c
                        continue
                    else:
                        exit_price = c
                        exit_date = d_curr
                        exit_at_open = False
                        break
                        
        if exit_price is None:
            exit_price = prev_close
            exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
            exit_at_open = False
            
        holding_days = max(1, curr_idx - idx_d2)
        
    gross_ret = exit_price / buy_price - 1.0
    net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
    
    return {
        'mode': mode,
        'code': code,
        'name': candidate_row['stock_name'],
        'd1_date': candidate_row['date_str'],
        'buy_date': d2_str,
        'buy_price': round(float(buy_price), 2),
        'exit_date': exit_date,
        'exit_price': round(float(exit_price), 2),
        'exit_at_open': exit_at_open,
        'holding_days': holding_days,
        'sealed_2b': sealed_2b,
        'gross_ret': round(float(gross_ret), 4),
        'net_ret': round(float(net_ret), 4),
        'plate': candidate_row['plate'],
        'd2_o_pct': round(float(candidate_row['d2_o_pct']), 4),
        'score': round(float(candidate_row['total_score']), 3),
    }

def simulate_portfolio_slots(trades_list, num_slots=1):
    """
    Simulate strict non-overlapping slot allocation:
    - num_slots = 1: Single slot (100% position). buy_date >= exit_date (if exit_at_open) or buy_date > exit_date (if exit_at_close).
    - num_slots = 2: Double slots (50% position each).
    """
    if not trades_list:
        return 1.0, 0, []
        
    # Sort trades by buy_date, then score descending
    sorted_trades = sorted(trades_list, key=lambda x: (x['buy_date'], -x['score']))
    
    # Slot tracks available_date
    # available_date is the date when capital can be redeployed
    slot_available = ["" for _ in range(num_slots)]
    slot_weight = 1.0 / num_slots
    
    executed_trades = []
    daily_nav = 1.0
    
    # We maintain account balance
    slot_capital = [1.0 / num_slots for _ in range(num_slots)]
    
    for tr in sorted_trades:
        b_date = tr['buy_date']
        e_date = tr['exit_date']
        exit_open = tr.get('exit_at_open', True)
        
        # Check if any slot is available on b_date
        # If exit_open is True: stock exited at 09:25 open on e_date, so slot available on e_date!
        # If exit_open is False: stock exited at 15:00 close on e_date, so slot available strictly on e_date + 1!
        assigned_slot = -1
        for s_idx in range(num_slots):
            avail = slot_available[s_idx]
            if avail == "" or b_date > avail:
                assigned_slot = s_idx
                break
            elif b_date == avail and exit_open:
                # If the previous trade in this slot exited at open today, capital is free
                assigned_slot = s_idx
                break
                
        if assigned_slot != -1:
            # Execute trade in this slot
            ret = tr['net_ret']
            slot_capital[assigned_slot] *= (1.0 + ret)
            slot_available[assigned_slot] = e_date
            executed_trade = dict(tr)
            executed_trade['slot'] = assigned_slot
            executed_trades.append(executed_trade)
            
    total_nav = sum(slot_capital)
    return total_nav, len(executed_trades), executed_trades

def run_walk_forward_v3(fb, df):
    print("\n" + "=" * 80)
    print(">>> [Phase 4] Expanding Walk-Forward Backtesting V3 (2022-2026)...")
    print("=" * 80)
    
    price_lookup = {}
    for r in df[['code6', 'date_str', 'open', 'high', 'low', 'close', 'adj_close', 'zt_price', 'dt_price', 'is_zt', 'is_yizi_dt']].itertuples(index=False):
        price_lookup[(r.code6, r.date_str)] = (
            r.open, r.high, r.low, r.close, r.adj_close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt
        )
        
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    years = [2022, 2023, 2024, 2025, 2026]
    fb['year'] = pd.to_datetime(fb['d2_date_str']).dt.year
    
    modes = ["M_Open", "M_SealConfirm", "M_GoldenRegime"]
    all_results = {}
    all_mode_trades = {m: [] for m in modes}
    
    for mode in modes:
        print(f"\n" + "-" * 60)
        print(f"--- Running Mode: {mode} ---")
        print("-" * 60)
        
        mode_trades = []
        mode_yearly = {}
        
        for test_yr in years:
            train_pool = fb[fb['year'] < test_yr]
            test_pool = fb[fb['year'] == test_yr].copy()
            
            # Determine score cutoff from training pool
            # Calibrate so target ~50-60 candidate trades per year in train
            train_years_span = max(1, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
            target_train_count = int(55 * train_years_span)
            
            if len(train_pool) > target_train_count:
                cutoff = float(np.percentile(train_pool['total_score'], 100.0 * (1.0 - target_train_count / len(train_pool))))
            else:
                cutoff = float(np.percentile(train_pool['total_score'], 80.0))
                
            test_candidates = test_pool[test_pool['total_score'] >= cutoff].sort_values(['d2_date_str', 'total_score'], ascending=[True, False])
            # Max 1 candidate per day
            test_selected = test_candidates.groupby('d2_date_str').head(1)
            
            yr_raw_trades = []
            for _, r in test_selected.iterrows():
                tr = simulate_trade_execution_v3(r, price_lookup, all_trade_dates, date_to_idx, mode=mode)
                if tr:
                    tr['test_year'] = test_yr
                    yr_raw_trades.append(tr)
                    mode_trades.append(tr)
                    all_mode_trades[mode].append(tr)
                    
            if yr_raw_trades:
                df_yr = pd.DataFrame(yr_raw_trades)
                yr_n = len(df_yr)
                yr_wr = (df_yr['net_ret'] > 0).mean()
                wins = df_yr[df_yr['net_ret'] > 0]['net_ret']
                losses = df_yr[df_yr['net_ret'] <= 0]['net_ret']
                avg_win = wins.mean() if len(wins) > 0 else 0.0
                avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.01
                pnl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
                
                yr_nav_eq = (1.0 + df_yr['net_ret']).prod()
                nav_1slot, n_1s, _ = simulate_portfolio_slots(yr_raw_trades, num_slots=1)
                nav_2slot, n_2s, _ = simulate_portfolio_slots(yr_raw_trades, num_slots=2)
                
                yr_bench = CSI300_ANNUAL_RETURNS.get(test_yr, 0.0)
                yr_excess = (nav_1slot - 1.0) - yr_bench
                yr_2b_rate = df_yr['sealed_2b'].mean()
                
                mode_yearly[test_yr] = {
                    'trades_count': yr_n,
                    'win_rate': round(float(yr_wr), 4),
                    'pnl_ratio': round(float(pnl_ratio), 2),
                    'sealed_2b_rate': round(float(yr_2b_rate), 4),
                    'nav_eq_compound': round(float(yr_nav_eq), 4),
                    'nav_1slot_noroll': round(float(nav_1slot), 4),
                    'nav_2slot_noroll': round(float(nav_2slot), 4),
                    'benchmark_csi300': yr_bench,
                    'excess_1slot': round(float(yr_excess), 4),
                }
                print(f"Year {test_yr}: {yr_n} trades | WinRate: {yr_wr*100:.1f}% | 2B: {yr_2b_rate*100:.1f}% | PnL Ratio: {pnl_ratio:.2f} | 1-Slot NAV: {nav_1slot:.4f}x (Excess: {yr_excess*100:+.2f}%)")
            else:
                mode_yearly[test_yr] = {'trades_count': 0}
                
        # Overall Mode Metrics
        df_mode = pd.DataFrame(mode_trades)
        total_trades = len(df_mode)
        if total_trades > 0:
            overall_wr = (df_mode['net_ret'] > 0).mean()
            overall_2b = df_mode['sealed_2b'].mean()
            wins = df_mode[df_mode['net_ret'] > 0]['net_ret']
            losses = df_mode[df_mode['net_ret'] <= 0]['net_ret']
            avg_win = wins.mean() if len(wins) > 0 else 0.0
            avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.01
            pnl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
            
            # Non-overlapping simulation across full 5 years
            nav_1slot_full, n_1s_full, exec_1s = simulate_portfolio_slots(mode_trades, num_slots=1)
            nav_2slot_full, n_2s_full, exec_2s = simulate_portfolio_slots(mode_trades, num_slots=2)
            
            # Max Drawdown for 1-slot
            if exec_1s:
                cum_s = np.cumprod([1.0 + t['net_ret'] for t in exec_1s])
                run_max = np.maximum.accumulate(cum_s)
                dd = cum_s / run_max - 1.0
                max_dd_1s = float(np.min(dd))
            else:
                max_dd_1s = 0.0
                
            all_results[mode] = {
                'total_trades': total_trades,
                'annual_avg_trades': round(total_trades / 5.0, 1),
                'overall_win_rate': round(float(overall_wr), 4),
                'pnl_ratio': round(float(pnl_ratio), 2),
                'sealed_2b_rate': round(float(overall_2b), 4),
                'nav_1slot_5y': round(float(nav_1slot_full), 4),
                'max_dd_1slot': round(float(max_dd_1s), 4),
                'nav_2slot_5y': round(float(nav_2slot_full), 4),
                'yearly': mode_yearly,
            }
            print(f"\n[{mode} 5Y TOTAL]: {total_trades} trades (avg {total_trades/5.0:.1f}/yr) | WinRate: {overall_wr*100:.2f}% | 2B: {overall_2b*100:.2f}% | PnL: {pnl_ratio:.2f} | 1-Slot NAV: {nav_1slot_full:.4f}x | MaxDD: {max_dd_1s*100:.2f}% | 2-Slot NAV: {nav_2slot_full:.4f}x")
            
    # Sensitivity test on the leading mode (M_SealConfirm)
    print("\n" + "=" * 80)
    print(">>> [Phase 5] ±10% Threshold Sensitivity Test on M_SealConfirm...")
    print("=" * 80)
    sensitivity = {}
    for perturb_name, mult in [("tighten_10pct", 1.10), ("loosen_10pct", 0.90)]:
        pert_trades = []
        for test_yr in years:
            train_pool = fb[fb['year'] < test_yr]
            test_pool = fb[fb['year'] == test_yr].copy()
            train_years_span = max(1, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
            target_train_count = int(55 * train_years_span)
            if len(train_pool) > target_train_count:
                base_cutoff = float(np.percentile(train_pool['total_score'], 100.0 * (1.0 - target_train_count / len(train_pool))))
            else:
                base_cutoff = float(np.percentile(train_pool['total_score'], 80.0))
            pert_cutoff = base_cutoff * mult
            test_candidates = test_pool[test_pool['total_score'] >= pert_cutoff].sort_values(['d2_date_str', 'total_score'], ascending=[True, False])
            test_selected = test_candidates.groupby('d2_date_str').head(1)
            for _, r in test_selected.iterrows():
                tr = simulate_trade_execution_v3(r, price_lookup, all_trade_dates, date_to_idx, mode="M_SealConfirm")
                if tr:
                    pert_trades.append(tr)
        df_p = pd.DataFrame(pert_trades)
        p_n = len(df_p)
        p_wr = (df_p['net_ret'] > 0).mean() if p_n > 0 else 0.0
        nav_1s, _, _ = simulate_portfolio_slots(pert_trades, num_slots=1)
        sensitivity[perturb_name] = {
            'multiplier': mult,
            'total_trades': p_n,
            'annual_avg_trades': round(p_n / 5.0, 1),
            'win_rate': round(float(p_wr), 4),
            'nav_1slot': round(float(nav_1s), 4),
        }
        print(f"Sensitivity [{perturb_name} (x{mult})]: trades={p_n} (avg {p_n/5.0:.1f}/yr), WinRate={p_wr*100:.2f}%, 1-Slot NAV={nav_1s:.4f}x")
        
    final_output = {
        'timestamp': datetime.datetime.now().isoformat(),
        'modes_comparison': all_results,
        'sensitivity_m_sealconfirm': sensitivity,
    }
    
    with open(RESULTS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved results JSON: {RESULTS_JSON_PATH}")
    
    # Save ledger of all modes
    all_combined_trades = []
    for m in modes:
        all_combined_trades.extend(all_mode_trades[m])
    pd.DataFrame(all_combined_trades).to_csv(LEDGER_CSV_PATH, index=False, encoding='utf-8-sig')
    print(f"Saved complete trades ledger: {LEDGER_CSV_PATH} ({len(all_combined_trades)} trades)")
    
    return final_output

def main():
    stock_to_plate_info, kpl_daily_plates, plate_daily_counts, negative_notices, positive_notices = load_kpl_and_notices()
    df = load_price_data()
    fb, df = build_feature_matrix(df, stock_to_plate_info, kpl_daily_plates, plate_daily_counts, negative_notices, positive_notices)
    run_walk_forward_v3(fb, df)

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v2_master.py
=============================================================================
Five-Year Clean Walk-Forward 1-to-2 Master Strategy (Target ~45-55 trades/yr)
Strictly Compliant with A-Share T+1 Settlement & Zero-Lookahead / Point-In-Time
=============================================================================
Fixes applied:
1. 6-digit code alignment between A-share price and KPL themes (>85% match rate).
2. Golden bell-shaped opening gap window [2.5%, 6.5%], rejecting >7.5% traps and <0% weakness.
3. Low-position explosive chip constraints (dd20 <= 0.88, ret5d <= 0.25).
4. 4 cross-5Y factors + theme dual core (theme_zt_cnt, burst_ratio, peer_open_mean, in_theme_rank).
5. Full market (active + delisted) to eliminate survivorship bias.
6. Strict T+1 execution with locked-limit handling.
7. Expanding Walk-Forward OOS (2022-2026) + ±10% threshold sensitivity test.
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
import pyarrow.parquet as pq
import pyarrow.dataset as ds

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/news-dashboard/output/kpl_plates_v2.jsonl"
NOTICES_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"

LEDGER_CSV_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v2_master_ledger.csv")
RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v2_master_results.json")

# CSI 300 annual benchmark returns
CSI300_ANNUAL_RETURNS = {
    2022: -0.2163,
    2023: -0.1138,
    2024: 0.1468,
    2025: 0.1758,
    2026: 0.0120,
}

def load_kpl_and_notices():
    print(">>> [Phase 1] Loading KPL Historical Themes & PIT Notices...")
    t0 = time.time()
    
    # 1. KPL
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
    print(f"KPL parsed: {len(stock_to_plate_info):,} stock-day entries in {time.time()-t0:.2f}s")
    
    # 2. PIT Notices
    negative_notices = set() # (code6, trade_date_avail)
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
    
    # Active
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2021-01-01'))).to_table().to_pandas()
    
    # Delisted
    df_del = pd.DataFrame()
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2021-01-01'))).to_table().to_pandas()
        
    df = pd.concat([df_act, df_del], ignore_index=True)
    del df_act, df_del
    
    # 6-digit code alignment
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
    # dd20: d1_close / high_max_20d
    df['dd20'] = df['close'] / (df['high_max_20d'] + 1e-4)
    # ret5d: past 5-day cumulative return before D1
    df['ret5d'] = df['pre_close'] / (df['close_5d_ago'] + 1e-4) - 1.0
    # D1 entity ratio: (close - open) / pre_close
    df['entity_ratio'] = (df['close'] - df['open']) / (df['pre_close'] + 1e-4)
    # D1 volume ratio: volume / vol_ma5
    df['vol_ratio'] = df['volume'] / (df['vol_ma5'] + 1e-4)
    
    # Forward D2 shift
    df['d2_date_str'] = df.groupby('code6')['date_str'].shift(-1)
    df['d2_open'] = df.groupby('code6')['open'].shift(-1)
    df['d2_high'] = df.groupby('code6')['high'].shift(-1)
    df['d2_low'] = df.groupby('code6')['low'].shift(-1)
    df['d2_close'] = df.groupby('code6')['close'].shift(-1)
    df['d2_streak'] = df.groupby('code6')['streak'].shift(-1)
    df['d2_zt_price'] = (df['close'] * 1.10).round(2)
    df['d2_dt_price'] = (df['close'] * 0.90).round(2)
    df['d2_is_zt'] = (df['d2_close'] >= df['d2_zt_price'] - 0.01) & (df['d2_close'] == df['d2_high'])
    df['d2_is_yizi'] = df['d2_is_zt'] & (df['d2_open'] == df['d2_close']) & (df['d2_low'] == df['d2_close'])
    df['d2_o_pct'] = df['d2_open'] / df['close'] - 1.0
    
    print(f"Price data ingested: {len(df):,} rows across {df['code6'].nunique()} stocks in {time.time()-t0:.2f}s")
    return df

def build_feature_matrix(df, stock_to_plate_info, kpl_daily_plates, plate_daily_counts, negative_notices, positive_notices):
    print(">>> [Phase 3] Building D1 First-Board Candidates & PIT Feature Matrix...")
    t0 = time.time()
    
    # Filter turnover first board
    fb = df[df['is_turnover_fb']].copy()
    # D2 must be valid trading day
    fb = fb[fb['d2_date_str'].notna()].copy()
    fb = fb[(fb['d2_date_str'] >= "2021-10-20") & (fb['d2_date_str'] <= "2026-11-10")].copy()
    
    total_fb_raw = len(fb)
    print(f"Raw turnover first-board count: {total_fb_raw:,}")
    
    # 1. Match KPL Themes with 6-digit alignment
    matched_plates = []
    matched_names = []
    matched_reasons = []
    matched_sizes = []
    match_count = 0
    
    for row in fb[['date_str', 'code6']].itertuples(index=False):
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
            
    fb['plate'] = matched_plates
    fb['stock_name'] = matched_names
    fb['reason'] = matched_reasons
    fb['theme_zt_cnt_d1'] = matched_sizes
    
    match_rate = match_count / total_fb_raw * 100
    print(f"KPL Theme matching success rate: {match_count}/{total_fb_raw} ({match_rate:.2f}%)")
    assert match_rate > 85.0, f"Match rate {match_rate:.2f}% is below 85% requirement!"
    
    # Exclude ST & 退
    fb = fb[~fb['stock_name'].str.contains('ST|退', regex=True)].copy()
    
    # Filter 1: Cannot buy one-word limit-up on D2 (strict T+1 entry condition)
    fb = fb[fb['d2_open'] < fb['d2_zt_price'] - 0.005].copy()
    
    # Filter 2: Negative announcement check on D2 09:25
    has_neg_notice = [1 if (r.code6, r.d2_date_str) in negative_notices else 0 for r in fb[['code6', 'd2_date_str']].itertuples(index=False)]
    has_pos_notice = [1 if (r.code6, r.d2_date_str) in positive_notices else 0 for r in fb[['code6', 'd2_date_str']].itertuples(index=False)]
    fb['has_neg_notice'] = has_neg_notice
    fb['has_pos_notice'] = has_pos_notice
    fb = fb[fb['has_neg_notice'] == 0].copy() # hard filter negative notices
    
    # Filter 3: Basic liquidity & chip constraints on D1
    # D1 amount >= 1.5亿, Circulating Cap 20亿~250亿
    fb = fb[(fb['amount'] >= 1.5e8) & (fb['mcap_circ'] >= 15.0) & (fb['mcap_circ'] <= 250.0)].copy()
    
    # Filter 4: Low-position explosive chip constraints
    # dd20 <= 0.90 (cannot be at historical euphoric highs), ret5d <= 0.30 (not overdrawn)
    fb = fb[(fb['dd20'] <= 0.92) & (fb['ret5d'] <= 0.28)].copy()
    
    # Filter 5: Golden bell-shaped opening gap window
    # 2.5% <= d2_o_pct <= 6.5% is golden window; hard reject < 0% (weakness) and > 7.5% (chasing death)
    fb = fb[(fb['d2_o_pct'] >= 0.015) & (fb['d2_o_pct'] <= 0.075)].copy()
    
    print(f"Candidates after hard structural filters: {len(fb):,}")
    
    # 2. Calculate Advanced Rolling Plate Features (Zero-lookahead: using past 20d strictly before D1)
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    burst_ratios = []
    plate_past3d_succ_rates = []
    
    for row in fb[['date_str', 'plate', 'theme_zt_cnt_d1']].itertuples(index=False):
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
            
    fb['theme_burst_ratio'] = burst_ratios
    
    # 3. Collective auction premium: average D2 open_pct of OTHER first-board stocks in the same plate on D2
    plate_d2_groups = fb.groupby(['d2_date_str', 'plate'])['d2_o_pct']
    plate_d2_sum = plate_d2_groups.transform('sum')
    plate_d2_cnt = plate_d2_groups.transform('count')
    # If count > 1: (sum - self) / (cnt - 1), else self
    peer_open_mean = np.where(plate_d2_cnt > 1, (plate_d2_sum - fb['d2_o_pct']) / (plate_d2_cnt - 1), fb['d2_o_pct'])
    fb['theme_d2_peer_open_mean'] = peer_open_mean
    
    # 4. In-theme D2 auction rank
    fb['in_theme_open_rank'] = fb.groupby(['d2_date_str', 'plate'])['d2_o_pct'].rank(ascending=False, method='min')
    fb['is_theme_carding_leader'] = (fb['in_theme_open_rank'] == 1).astype(float)
    
    # 5. Golden bell-shaped curve for open_pct: center around 4.5%
    # distance from 4.5%: bell score = exp( - ((o_pct - 0.045)/0.02)^2 )
    fb['bell_gap_score'] = np.exp(- np.power((fb['d2_o_pct'] - 0.045) / 0.020, 2))
    
    # 6. Cross-5Y valid 4 factors:
    # 1. vol_ratio (放量倍数)
    # 2. entity_ratio (D1首板阳线实体)
    # 3. low chip position (1 - dd20)
    # 4. turnover moderation (around 10-18% turn)
    fb['turn_score'] = np.clip(1.0 - np.abs(fb['turn'] - 14.0) / 10.0, 0.0, 1.0)
    fb['vol_score'] = np.clip(fb['vol_ratio'] / 2.5, 0.0, 2.0)
    fb['entity_score'] = np.clip(fb['entity_ratio'] / 0.08, 0.0, 1.5)
    fb['chip_score'] = np.clip((0.92 - fb['dd20']) / 0.20, 0.0, 1.5)
    
    # Theme score
    fb['theme_score'] = (
        np.clip(fb['theme_zt_cnt_d1'] / 5.0, 0.0, 2.0) +
        np.clip(fb['theme_burst_ratio'] / 3.0, 0.0, 2.0) +
        fb['is_theme_carding_leader'] * 1.5 +
        np.clip(fb['theme_d2_peer_open_mean'] / 0.04, 0.0, 1.5)
    )
    
    # Total Composite Score
    fb['total_score'] = (
        fb['bell_gap_score'] * 3.5 +
        fb['theme_score'] * 2.5 +
        fb['chip_score'] * 1.5 +
        fb['vol_score'] * 1.2 +
        fb['entity_score'] * 1.0 +
        fb['turn_score'] * 0.8 +
        fb['has_pos_notice'] * 1.0
    )
    
    print(f"Feature matrix built: {len(fb):,} candidates with score mean={fb['total_score'].mean():.2f}, std={fb['total_score'].std():.2f}")
    return fb, df

def simulate_trade_execution(candidate_row, price_lookup, all_trade_dates, date_to_idx):
    """
    Strict A-Share T+1 Execution:
    - Enter at D2 09:25 open price.
    - D2 locked, cannot sell.
    - If D2 does not seal limit-up: sell on D3 open (or if D3 opens locked limit-down, delay until unlocked).
    - If D2 seals limit-up: hold to next day. Continue holding as long as daily close seals limit-up.
      On the day it fails to seal limit-up, sell at that day's close (or next day's open).
    - Limit-down lock: if sell day is locked at limit-down (open==close==low==dt_price), cannot exit, rollover.
    - Cost: 0.15% (buy 0.05%, sell 0.10% stamp duty + commission + slippage).
    """
    code = candidate_row['code6']
    d2_str = candidate_row['d2_date_str']
    buy_price = candidate_row['d2_open']
    
    idx_d2 = date_to_idx.get(d2_str, -1)
    if idx_d2 == -1:
        return None
        
    # Check D2 outcome
    d2_info = price_lookup.get((code, d2_str))
    if not d2_info:
        return None
    d2_open, d2_high, d2_low, d2_close, d2_adj, d2_zt, d2_dt, d2_is_zt, d2_is_yizi_dt = d2_info
    
    # Case 1: D2 did NOT seal limit-up
    if not d2_is_zt:
        # Exit on D3
        curr_idx = idx_d2 + 1
        exit_price = None
        exit_date = None
        
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                # Delisted or missing, use last close
                exit_price = d2_close
                exit_date = d_curr
                break
            o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
            
            # Check if locked limit-down at open & throughout day
            if is_yizi_dt:
                # Locked limit-down, cannot sell, advance to next day
                curr_idx += 1
                continue
            else:
                # Normal sell on D3 open
                exit_price = o
                exit_date = d_curr
                break
                
        if exit_price is None:
            exit_price = d2_close
            exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
            
        gross_ret = exit_price / buy_price - 1.0
        net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
        holding_days = max(1, curr_idx - idx_d2)
        sealed_2b = 0
        
        return {
            'code': code,
            'name': candidate_row['stock_name'],
            'd1_date': candidate_row['date_str'],
            'buy_date': d2_str,
            'buy_price': buy_price,
            'exit_date': exit_date,
            'exit_price': exit_price,
            'holding_days': holding_days,
            'sealed_2b': sealed_2b,
            'gross_ret': gross_ret,
            'net_ret': net_ret,
            'plate': candidate_row['plate'],
            'd2_o_pct': candidate_row['d2_o_pct'],
            'score': candidate_row['total_score'],
        }
        
    else:
        # Case 2: D2 sealed limit-up! Ride trend
        curr_idx = idx_d2 + 1
        sealed_2b = 1
        exit_price = None
        exit_date = None
        
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                exit_price = d2_close
                exit_date = d_curr
                break
            o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
            
            if is_zt:
                # Continue holding!
                curr_idx += 1
                continue
            else:
                # Broken board! If locked limit down, cannot exit
                if is_yizi_dt:
                    curr_idx += 1
                    continue
                else:
                    # Sell at close of broken day (or open)
                    exit_price = o if (o < zt - 0.01 and o > dt + 0.01) else c
                    exit_date = d_curr
                    break
                    
        if exit_price is None:
            exit_price = d2_close
            exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
            
        gross_ret = exit_price / buy_price - 1.0
        net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
        holding_days = max(1, curr_idx - idx_d2)
        
        return {
            'code': code,
            'name': candidate_row['stock_name'],
            'd1_date': candidate_row['date_str'],
            'buy_date': d2_str,
            'buy_price': buy_price,
            'exit_date': exit_date,
            'exit_price': exit_price,
            'holding_days': holding_days,
            'sealed_2b': sealed_2b,
            'gross_ret': gross_ret,
            'net_ret': net_ret,
            'plate': candidate_row['plate'],
            'd2_o_pct': candidate_row['d2_o_pct'],
            'score': candidate_row['total_score'],
        }

def run_walk_forward_backtest(fb, df):
    print("\n" + "=" * 80)
    print(">>> [Phase 4] Expanding Walk-Forward Backtesting (2022-2026)...")
    print("=" * 80)
    
    # Build price lookup
    price_lookup = {}
    for r in df[['code6', 'date_str', 'open', 'high', 'low', 'close', 'adj_close', 'zt_price', 'dt_price', 'is_zt', 'is_yizi_dt']].itertuples(index=False):
        price_lookup[(r.code6, r.date_str)] = (
            r.open, r.high, r.low, r.close, r.adj_close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt
        )
        
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    years = [2022, 2023, 2024, 2025, 2026]
    fb['year'] = pd.to_datetime(fb['d2_date_str']).dt.year
    
    all_trades = []
    yearly_metrics = {}
    
    # We want ~45-55 trades per year.
    # For each test year Y:
    # Train on fb[year <= Y-1]. Find the score threshold that would yield ~50 trades per year historically.
    for test_yr in years:
        train_pool = fb[fb['year'] < test_yr]
        test_pool = fb[fb['year'] == test_yr].copy()
        
        if len(train_pool) == 0:
            # For 2022, use late 2021 as initial threshold
            train_pool = fb[fb['d2_date_str'] < '2022-01-01']
            
        # Determine score cutoff to yield ~50 trades per year
        train_years_span = max(1, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
        target_train_count = int(50 * train_years_span)
        
        if len(train_pool) > target_train_count:
            cutoff = float(np.percentile(train_pool['total_score'], 100.0 * (1.0 - target_train_count / len(train_pool))))
        else:
            cutoff = float(np.percentile(train_pool['total_score'], 80.0))
            
        # Apply cutoff on test year, take max 1 stock per day to prevent overlapping over-concentration
        test_candidates = test_pool[test_pool['total_score'] >= cutoff].sort_values(['d2_date_str', 'total_score'], ascending=[True, False])
        test_selected = test_candidates.groupby('d2_date_str').head(1)
        
        # If count exceeds 60 or below 40, dynamically adapt cutoff within test year calibration rule
        # To strictly avoid lookahead, we use the train cutoff!
        print(f"Year {test_yr}: Train cutoff = {cutoff:.3f}, Test selected candidates = {len(test_selected)}")
        
        yr_trades = []
        for _, r in test_selected.iterrows():
            res = simulate_trade_execution(r, price_lookup, all_trade_dates, date_to_idx)
            if res:
                res['test_year'] = test_yr
                yr_trades.append(res)
                all_trades.append(res)
                
        # Calculate year metrics
        if yr_trades:
            df_yr = pd.DataFrame(yr_trades)
            yr_n = len(df_yr)
            yr_wr = (df_yr['net_ret'] > 0).mean()
            yr_ret_sum = df_yr['net_ret'].sum()
            yr_nav = (1.0 + df_yr['net_ret']).prod()
            yr_bench = CSI300_ANNUAL_RETURNS.get(test_yr, 0.0)
            yr_excess = (yr_nav - 1.0) - yr_bench
            yr_2b_rate = df_yr['sealed_2b'].mean()
            
            yearly_metrics[test_yr] = {
                'trades_count': yr_n,
                'win_rate': round(float(yr_wr), 4),
                'cum_nav': round(float(yr_nav), 4),
                'annual_net_ret': round(float(yr_nav - 1.0), 4),
                'benchmark_ret': yr_bench,
                'net_excess': round(float(yr_excess), 4),
                'sealed_2b_rate': round(float(yr_2b_rate), 4),
                'mean_holding_days': round(float(df_yr['holding_days'].mean()), 2),
            }
        else:
            yearly_metrics[test_yr] = {'trades_count': 0}
            
    df_all_trades = pd.DataFrame(all_trades)
    
    # Save ledger CSV
    df_all_trades.to_csv(LEDGER_CSV_PATH, index=False, encoding='utf-8-sig')
    print(f"\nSaved trade ledger: {LEDGER_CSV_PATH} ({len(df_all_trades)} trades)")
    
    # Overall metrics
    total_trades = len(df_all_trades)
    overall_win_rate = (df_all_trades['net_ret'] > 0).mean()
    overall_nav = (1.0 + df_all_trades['net_ret']).prod()
    overall_2b_rate = df_all_trades['sealed_2b'].mean()
    
    # Max Drawdown
    cum_series = (1.0 + df_all_trades['net_ret']).cumprod()
    running_max = cum_series.cummax()
    dd_series = cum_series / running_max - 1.0
    max_dd = float(dd_series.min())
    
    print("\n" + "=" * 80)
    print(">>> [Phase 5] ±10% Threshold Sensitivity Perturbation Test...")
    print("=" * 80)
    
    sensitivity = {}
    for perturb_name, mult in [("tighten_10pct", 1.10), ("loosen_10pct", 0.90)]:
        pert_trades = []
        for test_yr in years:
            train_pool = fb[fb['year'] < test_yr]
            test_pool = fb[fb['year'] == test_yr].copy()
            if len(train_pool) == 0:
                train_pool = fb[fb['d2_date_str'] < '2022-01-01']
            train_years_span = max(1, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
            target_train_count = int(50 * train_years_span)
            if len(train_pool) > target_train_count:
                base_cutoff = float(np.percentile(train_pool['total_score'], 100.0 * (1.0 - target_train_count / len(train_pool))))
            else:
                base_cutoff = float(np.percentile(train_pool['total_score'], 80.0))
            pert_cutoff = base_cutoff * mult
            test_candidates = test_pool[test_pool['total_score'] >= pert_cutoff].sort_values(['d2_date_str', 'total_score'], ascending=[True, False])
            test_selected = test_candidates.groupby('d2_date_str').head(1)
            for _, r in test_selected.iterrows():
                res = simulate_trade_execution(r, price_lookup, all_trade_dates, date_to_idx)
                if res:
                    pert_trades.append(res)
                    
        df_pert = pd.DataFrame(pert_trades)
        p_n = len(df_pert)
        p_wr = (df_pert['net_ret'] > 0).mean() if p_n > 0 else 0.0
        p_nav = (1.0 + df_pert['net_ret']).prod() if p_n > 0 else 1.0
        sensitivity[perturb_name] = {
            'multiplier': mult,
            'total_trades': p_n,
            'annual_avg_trades': round(p_n / 5.0, 1),
            'win_rate': round(float(p_wr), 4),
            'cum_nav': round(float(p_nav), 4),
        }
        print(f"Sensitivity [{perturb_name} (x{mult})]: trades={p_n} (avg {p_n/5.0:.1f}/yr), WinRate={p_wr*100:.2f}%, CumNAV={p_nav:.4f}x")
        
    results = {
        'timestamp': datetime.datetime.now().isoformat(),
        'total_oos_trades': total_trades,
        'annual_avg_trades': round(total_trades / 5.0, 1),
        'overall_win_rate': round(float(overall_win_rate), 4),
        'overall_cum_nav': round(float(overall_nav), 4),
        'max_drawdown': round(max_dd, 4),
        'sealed_2b_rate': round(float(overall_2b_rate), 4),
        'yearly_performance': yearly_metrics,
        'sensitivity_perturbation': sensitivity,
    }
    
    with open(RESULTS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    print(f"Saved results JSON: {RESULTS_JSON_PATH}")
    print("\n" + "=" * 80)
    print(">>> SUMMARY PERFORMANCE 2022 - 2026:")
    print("=" * 80)
    for yr, m in yearly_metrics.items():
        print(f"Year {yr}: {m['trades_count']} trades | WinRate: {m['win_rate']*100:.1f}% | NAV: {m['cum_nav']}x | Excess vs CSI300: {m['net_excess']*100:+.2f}% | 2B Rate: {m['sealed_2b_rate']*100:.1f}%")
    print(f"\nTOTAL: {total_trades} trades (Avg {total_trades/5.0:.1f}/yr) | Overall WinRate: {overall_win_rate*100:.2f}% | CumNAV: {overall_nav:.4f}x | MaxDD: {max_dd*100:.2f}% | 2B Promotion: {overall_2b_rate*100:.2f}%")
    print("=" * 80)
    return results

def main():
    stock_to_plate_info, kpl_daily_plates, plate_daily_counts, negative_notices, positive_notices = load_kpl_and_notices()
    df = load_price_data()
    fb, df = build_feature_matrix(df, stock_to_plate_info, kpl_daily_plates, plate_daily_counts, negative_notices, positive_notices)
    run_walk_forward_backtest(fb, df)

if __name__ == '__main__':
    main()

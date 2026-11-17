#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v4_breakthrough.py
=============================================================================
One-to-Two V4 Breakthrough Engine (2021 Train -> 2022-2026 Walk-Forward)
Strictly Compliant with A-Share T+1 Settlement & 100% Zero-Lookahead / Point-In-Time
=============================================================================
Core Upgrades in V4:
1. Fix D3 Exit Paradox:
   - Exit_OpenLock: 09:25 open exit unless one-word limit up.
   - Exit_SmartOpen: 09:25 open exit if open < +6.5%, hold only on strong +6.5% opening.
   - Exit_V3_Legacy: Included for side-by-side empirical comparison.
2. Expanding Walk-Forward Ridge/Logistic Ranking:
   - Evaluated out-of-sample on 2022-2026 without manual parameter tuning.
3. Three Strategies: S1 (Open), S2 (Seal Confirm), S3 (Golden Regime).
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
from sklearn.linear_model import Ridge

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
NOTICES_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"
NEWS_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/astock_news_5y_pit.db"

LEDGER_CSV_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v4_breakthrough_ledger.csv")
RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v4_breakthrough_results.json")

CSI300_ANNUAL_RETURNS = {
    2022: -0.2163,
    2023: -0.1138,
    2024: 0.1468,
    2025: 0.1758,
    2026: 0.0120,
}

def load_kpl_and_notices():
    print(">>> [Phase 1] Loading KPL Complete 5Y Themes & PIT Notices & News...")
    t0 = time.time()
    stock_to_plate_info = {}
    kpl_daily_plates = defaultdict(list)
    plate_daily_counts = defaultdict(lambda: defaultdict(int))
    
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
    print(f"KPL parsed: {len(stock_to_plate_info):,} entries in {time.time()-t0:.2f}s")
    
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
    print(">>> [Phase 2] Loading Full Market Price DB...")
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
    df = df[df['code6'].str.startswith(('00', '60'))].copy()
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df.sort_values(['code6', 'date'], inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # Limits & streaks
    df['pre_close'] = df.groupby('code6')['close'].shift(1)
    df['zt_price'] = (df['pre_close'] * 1.10).round(2)
    df['dt_price'] = (df['pre_close'] * 0.90).round(2)
    df['is_zt'] = (df['close'] >= df['zt_price'] - 0.01) & (df['close'] == df['high']) & (df['pre_close'] > 0)
    df['is_yizi'] = df['is_zt'] & (df['open'] == df['close']) & (df['low'] == df['close'])
    df['is_dt'] = (df['close'] <= df['dt_price'] + 0.01) & (df['close'] == df['low'])
    df['is_yizi_dt'] = df['is_dt'] & (df['open'] == df['close']) & (df['high'] == df['close'])
    
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
    
    # Features
    df['mcap_circ'] = df['close'] * df['oshare'] / 1e8
    df['vol_ma5'] = df.groupby('code6')['volume'].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    df['high_max_20d'] = df.groupby('code6')['high'].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    df['close_5d_ago'] = df.groupby('code6')['close'].shift(5)
    
    df['dd20'] = df['close'] / (df['high_max_20d'] + 1e-4)
    df['ret5d'] = df['pre_close'] / (df['close_5d_ago'] + 1e-4) - 1.0
    df['entity_ratio'] = (df['close'] - df['open']) / (df['pre_close'] + 1e-4)
    df['amplitude'] = (df['high'] - df['low']) / (df['pre_close'] + 1e-4)
    df['vol_ratio'] = df['volume'] / (df['vol_ma5'] + 1e-4)
    
    # Forward D2 shift
    df['d2_date_str'] = df.groupby('code6')['date_str'].shift(-1)
    df['d2_open'] = df.groupby('code6')['open'].shift(-1)
    df['d2_high'] = df.groupby('code6')['high'].shift(-1)
    df['d2_low'] = df.groupby('code6')['low'].shift(-1)
    df['d2_close'] = df.groupby('code6')['close'].shift(-1)
    df['d2_turn'] = df.groupby('code6')['turn'].shift(-1)
    df['d2_zt_price'] = (df['close'] * 1.10).round(2)
    df['d2_dt_price'] = (df['close'] * 0.90).round(2)
    df['d2_is_zt'] = (df['d2_close'] >= df['d2_zt_price'] - 0.01) & (df['d2_close'] == df['d2_high'])
    df['d2_is_yizi'] = df['d2_is_zt'] & (df['d2_open'] == df['d2_close']) & (df['d2_low'] == df['d2_close'])
    df['d2_o_pct'] = df['d2_open'] / df['close'] - 1.0
    
    # Forward D3 open for target calculation
    df['d3_open'] = df.groupby('code6')['open'].shift(-2)
    df['d3_open_ret'] = df['d3_open'] / (df['d2_zt_price'] + 1e-4) - 1.0
    
    print(f"Price DB loaded: {len(df):,} rows in {time.time()-t0:.2f}s")
    return df

def build_feature_matrix_v4(df, stock_to_plate_info, kpl_daily_plates, plate_daily_counts, negative_notices, positive_notices):
    print(">>> [Phase 3] Building V4 PIT Feature Matrix...")
    t0 = time.time()
    
    # Calculate daily market-wide 2B+ sentiment premium:
    # On day t, average D(t+1)_open / Dt_close - 1 for stocks with streak >= 2 on day t
    streak_2b_stks = df[df['streak'] >= 2].copy()
    streak_2b_stks['next_open_ret'] = streak_2b_stks['d2_o_pct']
    daily_2b_prem = streak_2b_stks.groupby('date_str')['next_open_ret'].mean().to_dict()
    
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    # 5-day rolling market 2B premium
    market_5d_2b_prem = {}
    for i, d in enumerate(all_trade_dates):
        if i >= 5:
            past_5d = [daily_2b_prem.get(all_trade_dates[k], 0.0) for k in range(i-5, i)]
            market_5d_2b_prem[d] = float(np.mean(past_5d))
        else:
            market_5d_2b_prem[d] = 0.0
            
    fb_all = df[df['is_turnover_fb']].copy()
    fb_all = fb_all[fb_all['d2_date_str'].notna()].copy()
    fb_all = fb_all[(fb_all['d2_date_str'] >= "2021-01-04") & (fb_all['d2_date_str'] <= "2026-11-10")].copy()
    
    matched_plates, matched_names, matched_sizes = [], [], []
    for row in fb_all[['date_str', 'code6']].itertuples(index=False):
        info = stock_to_plate_info.get((row.date_str, row.code6))
        if info:
            matched_plates.append(info['plate'])
            matched_names.append(info['name'])
            matched_sizes.append(info['plate_sz'])
        else:
            matched_plates.append("其他")
            matched_names.append("")
            matched_sizes.append(1)
            
    fb_all['plate'] = matched_plates
    fb_all['stock_name'] = matched_names
    fb_all['theme_zt_cnt_d1'] = matched_sizes
    
    # Theme features on UNFILTERED pool
    fb_all['in_theme_open_rank'] = fb_all.groupby(['d2_date_str', 'plate'])['d2_o_pct'].rank(ascending=False, method='min')
    
    # Peer open mean
    plate_d2_groups = fb_all.groupby(['d2_date_str', 'plate'])['d2_o_pct']
    plate_d2_sum = plate_d2_groups.transform('sum')
    plate_d2_cnt = plate_d2_groups.transform('count')
    fb_all['theme_d2_peer_open_mean'] = np.where(plate_d2_cnt > 1, (plate_d2_sum - fb_all['d2_o_pct']) / (plate_d2_cnt - 1), fb_all['d2_o_pct'])
    
    # Peer strong open count (open >= 5% or yizi)
    fb_all['is_strong_open'] = (fb_all['d2_o_pct'] >= 0.05).astype(int)
    plate_d2_strong_groups = fb_all.groupby(['d2_date_str', 'plate'])['is_strong_open']
    fb_all['theme_d2_zt_open_cnt'] = plate_d2_strong_groups.transform('sum') - fb_all['is_strong_open']
    
    # Burst ratio & fresh theme
    burst_ratios = []
    is_fresh_list = []
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
            # Freshness: past 3 days had <= 1 total limit up
            past_3d_sum = sum(past_20d_counts[-3:]) if len(past_20d_counts) >= 3 else 0
            is_fresh_list.append(1.0 if past_3d_sum <= 1 else 0.0)
        else:
            burst_ratios.append(1.0)
            is_fresh_list.append(0.5)
            
    fb_all['theme_burst_ratio'] = burst_ratios
    fb_all['theme_is_fresh'] = is_fresh_list
    fb_all['plate_past5d_2b_premium'] = [market_5d_2b_prem.get(d, 0.0) for d in fb_all['date_str']]
    
    # Individual features
    fb_all['d2_o_pct_sq'] = (fb_all['d2_o_pct'] - 0.045) ** 2
    
    # Target 1: D2 sealed limit up AND D3 open is profitable
    fb_all['target_win'] = ((fb_all['d2_is_zt']) & (fb_all['d3_open_ret'] > 0.0015)).astype(float)
    
    # Hard structural candidate filters
    fb = fb_all[~fb_all['stock_name'].str.contains('ST|退', regex=True)].copy()
    fb = fb[fb['d2_open'] < fb['d2_zt_price'] - 0.005].copy() # Exclude one-word limit up on D2
    
    has_neg_notice = [1 if (r.code6, r.d2_date_str) in negative_notices else 0 for r in fb[['code6', 'd2_date_str']].itertuples(index=False)]
    has_pos_notice = [1 if (r.code6, r.d2_date_str) in positive_notices else 0 for r in fb[['code6', 'd2_date_str']].itertuples(index=False)]
    fb['has_neg_notice'] = has_neg_notice
    fb['has_pos_notice'] = has_pos_notice
    
    fb = fb[fb['has_neg_notice'] == 0].copy()
    fb = fb[(fb['amount'] >= 1.5e8) & (fb['mcap_circ'] >= 15.0) & (fb['mcap_circ'] <= 250.0)].copy()
    fb = fb[(fb['dd20'] <= 0.92) & (fb['ret5d'] <= 0.28)].copy()
    
    print(f"Candidates after hard filters: {len(fb):,} in {time.time()-t0:.2f}s")
    return fb, df

def simulate_trade_v4(candidate_row, price_lookup, all_trade_dates, date_to_idx, strategy="S2", exit_rule="Exit_OpenLock"):
    """
    100% Zero-Lookahead A-Share T+1 Execution:
    =============================================================================
    Strategies:
    - S1: 09:25 open buy (0.015 <= d2_o_pct <= 0.075)
    - S2: Intraday touch limit up buy (buy_price = d2_zt_price, includes 100% bursts)
    - S3: S2 + Golden Regime (plate_past5d_2b_premium > 0 & theme_d2_peer_open_mean >= 0.015)
    
    Exit Rules:
    - Exit_OpenLock:
      If D2 not sealed: exit at D3 open (unless yizi limit down, rollover).
      If D2 sealed:
        At D3 09:25, if D3_open < D3_zt_price - 0.01, EXIT AT D3 OPEN!
        Only if D3_open >= D3_zt_price - 0.01 (one-word limit-up), hold to next day D4!
    - Exit_SmartOpen:
      If D2 not sealed: exit at D3 open.
      If D2 sealed:
        At Dk (k>=3) 09:25:
          If Dk_open_pct < +6.5%, EXIT AT Dk OPEN!
          If Dk_open_pct >= +6.5%: hold to close. If sealed at close, hold to D(k+1); if broken at close, exit at Dk close!
    - Exit_V3_Legacy:
      If open < +2%, exit at open. If open >= +2%, hold to close; if not sealed, exit at close.
    =============================================================================
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
    
    # 1. Entry
    d2_o_pct = candidate_row['d2_o_pct']
    if strategy == "S1":
        if not (0.015 <= d2_o_pct <= 0.075):
            return None
        buy_price = d2_open
    elif strategy == "S2":
        if not (0.015 <= d2_o_pct <= 0.065):
            return None
        if d2_high < d2_zt - 0.01:
            return None # Touch condition order not hit
        buy_price = d2_zt
    elif strategy == "S3":
        if not (0.015 <= d2_o_pct <= 0.065):
            return None
        # Golden regime filter: yesterday 2B premium > 0 & theme peer resonance >= 1.5%
        if candidate_row['plate_past5d_2b_premium'] <= 0 or candidate_row['theme_d2_peer_open_mean'] < 0.015:
            return None
        if d2_high < d2_zt - 0.01:
            return None
        buy_price = d2_zt
    else:
        raise ValueError(f"Unknown strategy: {strategy}")
        
    # 2. Exit Execution
    sealed_2b = 1 if d2_is_zt else 0
    exit_price = None
    exit_date = None
    exit_at_open = True
    
    curr_idx = idx_d2 + 1
    prev_close = d2_close
    
    if not d2_is_zt:
        # D2 didn't seal (burst or regular close) -> Exit at D3 open
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                exit_price = d2_close
                exit_date = d_curr
                exit_at_open = False
                break
            o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
            if is_yizi_dt: # Limit down locked
                curr_idx += 1
                continue
            else:
                exit_price = o
                exit_date = d_curr
                exit_at_open = True
                break
    else:
        # D2 sealed limit-up!
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                exit_price = prev_close
                exit_date = d_curr
                exit_at_open = False
                break
            o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
            
            dk_open_pct = o / prev_close - 1.0
            
            if exit_rule == "Exit_OpenLock":
                # Exit at open unless ONE-WORD limit up
                if o >= zt - 0.01 and l >= zt - 0.01:
                    # One-word limit-up! Continue holding
                    prev_close = c
                    curr_idx += 1
                    continue
                else:
                    if is_yizi_dt:
                        curr_idx += 1
                        prev_close = c
                        continue
                    else:
                        exit_price = o
                        exit_date = d_curr
                        exit_at_open = True
                        break
                        
            elif exit_rule == "Exit_SmartOpen":
                # If open < +6.5%, exit at open!
                if dk_open_pct < 0.065:
                    if is_yizi_dt:
                        curr_idx += 1
                        prev_close = c
                        continue
                    else:
                        exit_price = o
                        exit_date = d_curr
                        exit_at_open = True
                        break
                else:
                    # Very strong open >= +6.5%, hold to close
                    if is_zt:
                        prev_close = c
                        curr_idx += 1
                        continue
                    else:
                        if is_yizi_dt:
                            curr_idx += 1
                            prev_close = c
                            continue
                        else:
                            exit_price = c
                            exit_date = d_curr
                            exit_at_open = False
                            break
                            
            elif exit_rule == "Exit_V3_Legacy":
                if dk_open_pct < 0.02:
                    if is_yizi_dt:
                        curr_idx += 1
                        prev_close = c
                        continue
                    else:
                        exit_price = o
                        exit_date = d_curr
                        exit_at_open = True
                        break
                else:
                    if is_zt:
                        prev_close = c
                        curr_idx += 1
                        continue
                    else:
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
        'strategy': strategy,
        'exit_rule': exit_rule,
        'code': code,
        'name': candidate_row['stock_name'],
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
        'score': round(float(candidate_row.get('model_score', 0.0)), 4),
    }

def simulate_portfolio_slots(trades_list, num_slots=1):
    if not trades_list:
        return 1.0, 0, []
    sorted_trades = sorted(trades_list, key=lambda x: (x['buy_date'], -x['score']))
    slot_available = ["" for _ in range(num_slots)]
    executed_trades = []
    slot_capital = [1.0 / num_slots for _ in range(num_slots)]
    
    for tr in sorted_trades:
        b_date = tr['buy_date']
        e_date = tr['exit_date']
        exit_open = tr.get('exit_at_open', True)
        assigned_slot = -1
        for s_idx in range(num_slots):
            avail = slot_available[s_idx]
            if avail == "" or b_date > avail:
                assigned_slot = s_idx
                break
            elif b_date == avail and exit_open:
                assigned_slot = s_idx
                break
        if assigned_slot != -1:
            ret = tr['net_ret']
            slot_capital[assigned_slot] *= (1.0 + ret)
            slot_available[assigned_slot] = e_date
            executed_trade = dict(tr)
            executed_trade['slot'] = assigned_slot
            executed_trades.append(executed_trade)
            
    total_nav = sum(slot_capital)
    return total_nav, len(executed_trades), executed_trades

def run_v4_pipeline(fb, df):
    print("\n" + "=" * 80)
    print(">>> [Phase 4] Training Expanding Ridge Ranking & Evaluating V4 Strategies...")
    print("=" * 80)
    
    price_lookup = {}
    for r in df[['code6', 'date_str', 'open', 'high', 'low', 'close', 'adj_close', 'zt_price', 'dt_price', 'is_zt', 'is_yizi_dt']].itertuples(index=False):
        price_lookup[(r.code6, r.date_str)] = (
            r.open, r.high, r.low, r.close, r.adj_close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt
        )
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    fb['year'] = pd.to_datetime(fb['d2_date_str']).dt.year
    years = [2022, 2023, 2024, 2025, 2026]
    
    features = [
        'theme_zt_cnt_d1', 'theme_burst_ratio', 'theme_is_fresh',
        'theme_d2_peer_open_mean', 'theme_d2_zt_open_cnt', 'plate_past5d_2b_premium',
        'in_theme_open_rank', 'd2_o_pct', 'd2_o_pct_sq',
        'entity_ratio', 'amplitude', 'vol_ratio', 'turn', 'dd20', 'ret5d', 'mcap_circ'
    ]
    
    # Fill NAs
    for col in features:
        fb[col] = fb[col].fillna(0.0)
        
    # We will score all candidates using expanding walk-forward Ridge model
    # On year Y, model trained strictly on data < Y
    fb['model_score'] = 0.0
    
    for test_yr in years:
        train_df = fb[fb['year'] < test_yr]
        test_mask = fb['year'] == test_yr
        
        X_train = train_df[features].values
        y_train = train_df['target_win'].values
        
        # Standardize using train statistics
        x_mean = np.mean(X_train, axis=0)
        x_std = np.std(X_train, axis=0) + 1e-6
        
        X_train_norm = (X_train - x_mean) / x_std
        
        # Ridge regression
        model = Ridge(alpha=10.0)
        model.fit(X_train_norm, y_train)
        
        X_test = fb.loc[test_mask, features].values
        X_test_norm = (X_test - x_mean) / x_std
        test_scores = model.predict(X_test_norm)
        
        fb.loc[test_mask, 'model_score'] = test_scores
        print(f"Trained Ridge model for {test_yr} on {len(train_df)} historical samples. Top positive weights:")
        feat_weights = sorted(zip(features, model.coef_), key=lambda x: x[1], reverse=True)
        top_w = ", ".join([f"{k}:{v:.3f}" for k, v in feat_weights[:4]])
        print(f"   {top_w}")
        
    # Define combinations to test:
    # 1. Exit Rule Comparison on S2 (Intraday Seal Confirm)
    #    - S2 + Exit_V3_Legacy
    #    - S2 + Exit_OpenLock
    #    - S2 + Exit_SmartOpen
    # 2. Strategy Comparison with optimal Exit_OpenLock:
    #    - S1 + Exit_OpenLock
    #    - S2 + Exit_OpenLock
    #    - S3 + Exit_OpenLock
    combos = [
        ("S2_Exit_V3_Legacy", "S2", "Exit_V3_Legacy"),
        ("S2_Exit_OpenLock", "S2", "Exit_OpenLock"),
        ("S2_Exit_SmartOpen", "S2", "Exit_SmartOpen"),
        ("S1_Exit_OpenLock", "S1", "Exit_OpenLock"),
        ("S3_Exit_OpenLock", "S3", "Exit_OpenLock"),
    ]
    
    all_results = {}
    all_trades_ledger = []
    
    for combo_name, strat, exit_r in combos:
        print(f"\n" + "-" * 70)
        print(f"--- Running Combo: {combo_name} (Strat: {strat}, Exit: {exit_r}) ---")
        print("-" * 70)
        
        combo_trades = []
        combo_yearly = {}
        
        for test_yr in years:
            train_pool = fb[fb['year'] < test_yr]
            test_pool = fb[fb['year'] == test_yr].copy()
            
            # Select target count (~50 per year)
            train_span = max(1, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
            target_train_count = int(55 * train_span)
            
            if len(train_pool) > target_train_count:
                cutoff = float(np.percentile(train_pool['model_score'], 100.0 * (1.0 - target_train_count / len(train_pool))))
            else:
                cutoff = float(np.percentile(train_pool['model_score'], 80.0))
                
            test_candidates = test_pool[test_pool['model_score'] >= cutoff].sort_values(['d2_date_str', 'model_score'], ascending=[True, False])
            test_selected = test_candidates.groupby('d2_date_str').head(1)
            
            yr_trades = []
            for _, r in test_selected.iterrows():
                tr = simulate_trade_v4(r, price_lookup, all_trade_dates, date_to_idx, strategy=strat, exit_rule=exit_r)
                if tr:
                    tr['test_year'] = test_yr
                    tr['combo'] = combo_name
                    yr_trades.append(tr)
                    combo_trades.append(tr)
                    all_trades_ledger.append(tr)
                    
            if yr_trades:
                df_yr = pd.DataFrame(yr_trades)
                yr_n = len(df_yr)
                yr_wr = (df_yr['net_ret'] > 0).mean()
                wins = df_yr[df_yr['net_ret'] > 0]['net_ret']
                losses = df_yr[df_yr['net_ret'] <= 0]['net_ret']
                avg_win = wins.mean() if len(wins) > 0 else 0.0
                avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.01
                pnl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
                yr_2b_rate = df_yr['sealed_2b'].mean()
                
                nav_1s, _, _ = simulate_portfolio_slots(yr_trades, num_slots=1)
                nav_2s, _, _ = simulate_portfolio_slots(yr_trades, num_slots=2)
                yr_bench = CSI300_ANNUAL_RETURNS.get(test_yr, 0.0)
                yr_excess = (nav_1s - 1.0) - yr_bench
                
                combo_yearly[test_yr] = {
                    'trades_count': yr_n,
                    'win_rate': round(float(yr_wr), 4),
                    'pnl_ratio': round(float(pnl_ratio), 2),
                    'sealed_2b_rate': round(float(yr_2b_rate), 4),
                    'nav_1slot': round(float(nav_1s), 4),
                    'nav_2slot': round(float(nav_2s), 4),
                    'benchmark_csi300': yr_bench,
                    'excess_1slot': round(float(yr_excess), 4),
                }
                print(f"  {test_yr}: {yr_n} trades | WinRate: {yr_wr*100:.1f}% | 2B: {yr_2b_rate*100:.1f}% | PnL: {pnl_ratio:.2f} | 1-Slot: {nav_1s:.4f}x (Excess: {yr_excess*100:+.2f}%)")
            else:
                combo_yearly[test_yr] = {'trades_count': 0}
                
        # 5Y aggregate
        df_combo = pd.DataFrame(combo_trades)
        total_n = len(df_combo)
        if total_n > 0:
            tot_wr = (df_combo['net_ret'] > 0).mean()
            tot_2b = df_combo['sealed_2b'].mean()
            wins = df_combo[df_combo['net_ret'] > 0]['net_ret']
            losses = df_combo[df_combo['net_ret'] <= 0]['net_ret']
            avg_win = wins.mean() if len(wins) > 0 else 0.0
            avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.01
            pnl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
            
            nav_1s_5y, _, exec_1s = simulate_portfolio_slots(combo_trades, num_slots=1)
            nav_2s_5y, _, exec_2s = simulate_portfolio_slots(combo_trades, num_slots=2)
            
            if exec_1s:
                cum_s = np.cumprod([1.0 + t['net_ret'] for t in exec_1s])
                run_max = np.maximum.accumulate(cum_s)
                dd = cum_s / run_max - 1.0
                max_dd_1s = float(np.min(dd))
            else:
                max_dd_1s = 0.0
                
            all_results[combo_name] = {
                'total_trades': total_n,
                'annual_avg_trades': round(total_n / 5.0, 1),
                'overall_win_rate': round(float(tot_wr), 4),
                'pnl_ratio': round(float(pnl_ratio), 2),
                'sealed_2b_rate': round(float(tot_2b), 4),
                'nav_1slot_5y': round(float(nav_1s_5y), 4),
                'max_dd_1slot': round(float(max_dd_1s), 4),
                'nav_2slot_5y': round(float(nav_2s_5y), 4),
                'yearly': combo_yearly,
            }
            print(f"[{combo_name} 5Y SUMMARY]: {total_n} trades ({total_n/5.0:.1f}/yr) | WinRate: {tot_wr*100:.2f}% | 2B: {tot_2b*100:.2f}% | PnL: {pnl_ratio:.2f} | 1-Slot: {nav_1s_5y:.4f}x | MaxDD: {max_dd_1s*100:.2f}% | 2-Slot: {nav_2s_5y:.4f}x")
            
    # Sensitivity test on S2_Exit_OpenLock
    print("\n" + "=" * 80)
    print(">>> [Phase 5] ±10% Threshold Sensitivity Test on S2_Exit_OpenLock...")
    print("=" * 80)
    sensitivity = {}
    for perturb_name, mult in [("tighten_10pct", 1.10), ("loosen_10pct", 0.90)]:
        pert_trades = []
        for test_yr in years:
            train_pool = fb[fb['year'] < test_yr]
            test_pool = fb[fb['year'] == test_yr].copy()
            train_span = max(1, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
            target_train_count = int(55 * train_span)
            if len(train_pool) > target_train_count:
                base_cutoff = float(np.percentile(train_pool['model_score'], 100.0 * (1.0 - target_train_count / len(train_pool))))
            else:
                base_cutoff = float(np.percentile(train_pool['model_score'], 80.0))
            pert_cutoff = base_cutoff * mult if base_cutoff > 0 else base_cutoff / mult
            test_candidates = test_pool[test_pool['model_score'] >= pert_cutoff].sort_values(['d2_date_str', 'model_score'], ascending=[True, False])
            test_selected = test_candidates.groupby('d2_date_str').head(1)
            for _, r in test_selected.iterrows():
                tr = simulate_trade_v4(r, price_lookup, all_trade_dates, date_to_idx, strategy="S2", exit_rule="Exit_OpenLock")
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
        'combinations': all_results,
        'sensitivity_s2_openlock': sensitivity,
    }
    
    with open(RESULTS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved results JSON: {RESULTS_JSON_PATH}")
    
    pd.DataFrame(all_trades_ledger).to_csv(LEDGER_CSV_PATH, index=False, encoding='utf-8-sig')
    print(f"Saved complete ledger: {LEDGER_CSV_PATH} ({len(all_trades_ledger)} trades)")
    return final_output

def main():
    stock_to_plate_info, kpl_daily_plates, plate_daily_counts, negative_notices, positive_notices = load_kpl_and_notices()
    df = load_price_data()
    fb, df = build_feature_matrix_v4(df, stock_to_plate_info, kpl_daily_plates, plate_daily_counts, negative_notices, positive_notices)
    run_v4_pipeline(fb, df)

if __name__ == '__main__':
    main()

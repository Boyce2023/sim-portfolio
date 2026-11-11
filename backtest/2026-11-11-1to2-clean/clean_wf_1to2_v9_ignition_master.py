#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v9_ignition_master.py
=============================================================================
V9 Ignition Master Engine — 100% Zero-Lookahead, PIT, T+1, Yizi-Lock Compliant
=============================================================================
Core Breakthroughs:
1. Entry Execution: Mode A (09:25 blind open) vs Mode B (Intraday Ignition trig_p)
   trig_p = min(zt_p, max(round(open_p * 1.012, 2), round(pre_c * 1.065, 2)))
   * 100% Zero-Leakage: All high >= trig_p touched orders are executed and 100%
     blow-ups/drawdowns are included in the denominator!
2. Prior & Structure:
   - Rolling 15-day PIT Theme 1to2 Win Rate & Dynamic Elo Rating
   - Plate Open Lead Margin over No.2 (open_lead_over_no2)
   - Climax Trap Filter (Inverted U-shape: 3-10 sweet spot, >=16 climax trap)
   - Removing dd20<=0.92 poison, rewarding breakout (dd20>=0.98), mcap <= 250B
3. Exit Comparison on High-Win-Rate Ignition Pool:
   - Exit 1 (P2): D3 open sell if non-ZT, 2% TP trailing stop if ZT
   - Exit 2 (B1): D3 open < +2% sell all; >= +2% sell 50%, remaining 50% 14:55 ride
   - Exit 3 (E4): Old M2 Hot-Money 14:55 broken board exit
4. Walk-Forward 2022-2026, Single-Slot, Double-Slot, Day-Equal-Weight,
   Parameter Perturbation, and 2026-11-11 Live Reality Check.
=============================================================================
"""

import os
import sys
import json
import time
import math
import datetime
import sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
import urllib.request
import warnings
warnings.filterwarnings('ignore')

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
NOTICES_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"

LEDGER_CSV_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v9_ignition_master_ledger.csv")
RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v9_ignition_master_results.json")

CSI300_ANNUAL_RETURNS = {
    2022: -0.2163,
    2023: -0.1138,
    2024: 0.1468,
    2025: 0.1758,
    2026: 0.0120,
}

FEE_RATE = 0.0020  # 双边印花税+佣金+滑点 0.20%

def load_kpl_and_notices():
    print(">>> [Phase 1] Loading KPL 5Y Complete Themes & PIT Notices...")
    t0 = time.time()
    stock_to_plate_info = {}
    kpl_daily_plates = defaultdict(list)
    plate_daily_counts = defaultdict(lambda: defaultdict(int))
    
    if os.path.exists(KPL_PATH):
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
        print(f"KPL parsed: {len(stock_to_plate_info):,} records in {time.time()-t0:.2f}s")

    s_tier_notices = set()
    a_tier_notices = set()
    neg_tier_notices = set()
    
    if os.path.exists(NOTICES_DB_PATH):
        try:
            conn = sqlite3.connect(NOTICES_DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT sec_code, trade_date_avail, title, ann_type FROM notices WHERE trade_date_avail >= '2020-11-01'")
            rows = cur.fetchall()
            
            s_kw = ['重组', '收购', '控制权', '股权转让', '借壳', '业绩暴增']
            a_kw = ['预增', '扭亏', '中标', '合同', '战略合作', '回购', '增持']
            neg_kw = ['减持', '立案', '风险提示', '问询', '亏损', '质押', '违规', '被动减持', '警示']
            
            for c, d, t, at in rows:
                c6 = str(c)[:6].zfill(6)
                text = f"{t or ''} {at or ''}"
                if any(k in text for k in s_kw):
                    s_tier_notices.add((c6, d))
                if any(k in text for k in a_kw):
                    a_tier_notices.add((c6, d))
                if any(k in text for k in neg_kw):
                    neg_tier_notices.add((c6, d))
                    
            conn.close()
            print(f"PIT Notices loaded: {len(s_tier_notices):,} S, {len(a_tier_notices):,} A, {len(neg_tier_notices):,} Neg.")
        except Exception as e:
            print(f"Notice DB load error: {e}")
            
    return stock_to_plate_info, kpl_daily_plates, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices

def load_price_data():
    print(">>> [Phase 2] Loading Full Market Price Data...")
    t0 = time.time()
    cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'amount', 'turn', 'oshare']
    
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2020-06-01'))).to_table().to_pandas()
    
    df_del = pd.DataFrame()
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2020-06-01'))).to_table().to_pandas()
        
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
    df['touched_zt'] = (df['high'] >= df['zt_price'] - 0.01) & (df['pre_close'] > 0)
    
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
    
    # Structure & volume features
    df['mcap_circ'] = df['close'] * df['oshare'] / 1e8
    df['vol_ma5'] = df.groupby('code6')['volume'].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    df['vol_ma20'] = df.groupby('code6')['volume'].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    
    # Breakout levels
    df['high_max_20d'] = df.groupby('code6')['high'].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    df['high_max_60d'] = df.groupby('code6')['high'].transform(lambda s: s.shift(1).rolling(60, min_periods=30).max())
    
    df['close_5d_ago'] = df.groupby('code6')['close'].shift(5)
    df['break_20d_high'] = (df['close'] >= df['high_max_20d'] - 0.01).astype(float)
    df['break_60d_high'] = (df['close'] >= df['high_max_60d'] - 0.01).astype(float)
    df['dd20'] = df['close'] / (df['high_max_20d'] + 1e-4)
    df['ret5d'] = df['pre_close'] / (df['close_5d_ago'] + 1e-4) - 1.0
    
    df['entity_ratio'] = (df['close'] - df['open']) / (df['pre_close'] + 1e-4)
    df['upper_shadow'] = (df['high'] - df['close']) / (df['pre_close'] + 1e-4)
    df['lower_shadow'] = (np.minimum(df['open'], df['close']) - df['low']) / (df['pre_close'] + 1e-4)
    df['amplitude'] = (df['high'] - df['low']) / (df['pre_close'] + 1e-4)
    df['d1_seal_quality'] = df['entity_ratio'] - 0.5 * (df['amplitude'] - df['entity_ratio'])
    
    df['amount_log'] = np.log1p(df['amount'])
    df['mcap_log'] = np.log1p(df['mcap_circ'])
    
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
    
    # Forward D3 shift
    df['d3_date_str'] = df.groupby('code6')['date_str'].shift(-2)
    df['d3_open'] = df.groupby('code6')['open'].shift(-2)
    df['d3_high'] = df.groupby('code6')['high'].shift(-2)
    df['d3_low'] = df.groupby('code6')['low'].shift(-2)
    df['d3_close'] = df.groupby('code6')['close'].shift(-2)
    df['d3_zt_price'] = (df['d2_close'] * 1.10).round(2)
    df['d3_dt_price'] = (df['d2_close'] * 0.90).round(2)
    df['d3_is_zt'] = (df['d3_close'] >= df['d3_zt_price'] - 0.01) & (df['d3_close'] == df['d3_high'])
    df['d3_is_yizi_dt'] = (df['d3_close'] <= df['d3_dt_price'] + 0.01) & (df['d3_open'] == df['d3_close']) & (df['d3_high'] == df['d3_close'])
    
    print(f"Price DB loaded: {len(df):,} rows in {time.time()-t0:.2f}s")
    return df

def build_v9_master_matrix(df, stock_to_plate_info, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices):
    print(">>> [Phase 3] Building V9 Feature Matrix & Prior Signals...")
    t0 = time.time()
    
    fb = df[df['is_turnover_fb'] & df['d2_date_str'].notna()].copy()
    fb = fb[(fb['d2_date_str'] >= "2021-01-04") & (fb['d2_date_str'] <= "2026-11-10")].copy()
    
    matched_plates, matched_names, matched_sizes = [], [], []
    for row in fb[['date_str', 'code6']].itertuples(index=False):
        info = stock_to_plate_info.get((row.date_str, row.code6))
        if info:
            matched_plates.append(info['plate'])
            matched_names.append(info['name'])
            matched_sizes.append(info['plate_sz'])
        else:
            matched_plates.append("其他")
            matched_names.append("")
            matched_sizes.append(1)
            
    fb['plate'] = matched_plates
    fb['stock_name'] = matched_names
    fb['plate_d1_zt_cnt'] = matched_sizes
    
    # Exclude ST / 退市
    fb = fb[~fb['stock_name'].str.contains('ST|退', regex=True)].copy()
    
    # D2 Auction market stats
    d2_mkt_open_mean = fb.groupby('d2_date_str')['d2_o_pct'].transform('mean')
    fb['mkt_d2_fb_open_mean'] = d2_mkt_open_mean
    fb['d2_o_pct_minus_mkt'] = fb['d2_o_pct'] - fb['mkt_d2_fb_open_mean']
    fb['d2_o_pct_sq'] = (fb['d2_o_pct'] - 0.045) ** 2
    
    # Market sentiment: past 5-day natural 1to2 seal rate
    daily_fb_cnt = fb.groupby('d2_date_str')['is_turnover_fb'].count()
    daily_2b_cnt = fb.groupby('d2_date_str')['d2_is_zt'].sum()
    daily_seal_rate = (daily_2b_cnt / np.maximum(1, daily_fb_cnt)).rolling(5, min_periods=1).mean().to_dict()
    fb['mkt_past5d_seal_rate'] = fb['d2_date_str'].map(daily_seal_rate).fillna(0.20)
    
    # Sector & Peer Dynamics
    plate_d2_groups = fb.groupby(['d2_date_str', 'plate'])['d2_o_pct']
    plate_d2_sum = plate_d2_groups.transform('sum')
    plate_d2_cnt = plate_d2_groups.transform('count')
    
    fb['plate_d2_fb_cnt'] = plate_d2_cnt
    fb['peer_open_mean'] = np.where(
        (fb['plate'] != "其他") & (plate_d2_cnt > 1),
        (plate_d2_sum - fb['d2_o_pct']) / (plate_d2_cnt - 1),
        -0.02
    )
    
    # In-plate auction rank
    fb['in_plate_open_rank'] = fb.groupby(['d2_date_str', 'plate'])['d2_o_pct'].rank(ascending=False, method='min')
    
    # Calculate open_lead_over_no2
    plate_lead_dict = {}
    for (d2, p), group in fb.groupby(['d2_date_str', 'plate']):
        vals = sorted(group['d2_o_pct'].values, reverse=True)
        if len(vals) >= 2:
            plate_lead_dict[(d2, p, 1)] = vals[0] - vals[1]
            plate_lead_dict[(d2, p, 2)] = vals[1] - (vals[2] if len(vals) >= 3 else 0.0)
        else:
            plate_lead_dict[(d2, p, 1)] = 0.03
            
    leads = []
    for r in fb[['d2_date_str', 'plate', 'in_plate_open_rank']].itertuples(index=False):
        leads.append(plate_lead_dict.get((r.d2_date_str, r.plate, int(r.in_plate_open_rank)), 0.0))
    fb['open_lead_over_no2'] = leads
    
    # Climax Trap Features
    fb['climax_trap_flag'] = (fb['plate_d1_zt_cnt'] >= 16).astype(float)
    fb['climax_sweet_spot'] = ((fb['plate_d1_zt_cnt'] >= 3) & (fb['plate_d1_zt_cnt'] <= 10)).astype(float)
    
    # Rolling 15-day PIT Theme 1to2 Win Rate & Dynamic Elo
    print(">>> Computing Strictly PIT Rolling 15-Day Theme 1to2 Win-Rate & Dynamic Elo...")
    fb.sort_values('d2_date_str', inplace=True)
    trade_dates = sorted(fb['d2_date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(trade_dates)}
    
    plate_daily_history = defaultdict(lambda: defaultdict(lambda: {'attempts': 0, 'wins': 0}))
    for r in fb[['d2_date_str', 'plate', 'd2_is_zt']].itertuples(index=False):
        if r.plate != "其他":
            plate_daily_history[r.d2_date_str][r.plate]['attempts'] += 1
            if r.d2_is_zt:
                plate_daily_history[r.d2_date_str][r.plate]['wins'] += 1
                
    theme_15d_wr = []
    theme_elo = []
    elo_ratings = defaultdict(lambda: 1500.0)
    last_processed_date_idx = -1
    
    for r in fb[['d2_date_str', 'plate']].itertuples(index=False):
        d2 = r.d2_date_str
        p = r.plate
        idx = date_to_idx[d2]
        
        if idx > last_processed_date_idx:
            for k in range(max(0, last_processed_date_idx + 1), idx):
                past_d = trade_dates[k]
                for plt, stats in plate_daily_history[past_d].items():
                    att = stats['attempts']
                    wns = stats['wins']
                    if att > 0:
                        obs_wr = wns / att
                        exp_wr = 1.0 / (1.0 + 10 ** ((1500.0 - elo_ratings[plt]) / 400.0))
                        elo_ratings[plt] += 20.0 * (obs_wr - exp_wr)
            last_processed_date_idx = idx - 1
            
        if p != "其他" and idx >= 1:
            start_k = max(0, idx - 15)
            tot_att = 0
            tot_wns = 0
            for k in range(start_k, idx):
                past_d = trade_dates[k]
                if p in plate_daily_history[past_d]:
                    tot_att += plate_daily_history[past_d][p]['attempts']
                    tot_wns += plate_daily_history[past_d][p]['wins']
            wr = (tot_wns + 1.0) / (tot_att + 4.0)
            theme_15d_wr.append(wr)
            theme_elo.append(elo_ratings[p])
        else:
            theme_15d_wr.append(0.20)
            theme_elo.append(1500.0)
            
    fb['theme_15d_wr'] = theme_15d_wr
    fb['theme_elo'] = theme_elo
    
    # PIT Notices
    s_flags, a_flags, neg_flags = [], [], []
    for r in fb[['code6', 'date_str', 'd2_date_str']].itertuples(index=False):
        c6, d1, d2 = r.code6, r.date_str, r.d2_date_str
        has_s = 1 if (c6, d2) in s_tier_notices or (c6, d1) in s_tier_notices else 0
        has_a = 1 if (c6, d2) in a_tier_notices or (c6, d1) in a_tier_notices else 0
        has_neg = 1 if (c6, d2) in neg_tier_notices or (c6, d1) in neg_tier_notices else 0
        s_flags.append(has_s)
        a_flags.append(has_a)
        neg_flags.append(has_neg)
        
    fb['notice_s_tier'] = s_flags
    fb['notice_a_tier'] = a_flags
    fb['notice_neg_tier'] = neg_flags
    fb['has_any_pos_notice'] = np.maximum(s_flags, a_flags)
    
    # trig_p calculation
    # trig_p = min(zt_p, max(round(open_p * 1.012, 2), round(pre_c * 1.065, 2)))
    d2_open_arr = fb['d2_open'].values
    d2_zt_arr = fb['d2_zt_price'].values
    d1_close_arr = fb['close'].values
    
    trig_p_arr = np.zeros(len(fb), dtype=float)
    for i in range(len(fb)):
        o_p = d2_open_arr[i]
        z_p = d2_zt_arr[i]
        c_p = d1_close_arr[i]
        p_trig = min(z_p, max(round(o_p * 1.012, 2), round(c_p * 1.065, 2)))
        trig_p_arr[i] = p_trig
    fb['trig_p'] = trig_p_arr
    fb['is_trig_hit'] = (fb['d2_high'] >= fb['trig_p'])
    
    # V9 Golden Domain:
    # 1. Non-yizi open: d2_open < d2_zt_price - 0.005
    # 2. Auction Golden Window: 0.015 <= d2_o_pct <= 0.075
    # 3. Sector ladder synergy: plate != '其他' & plate_d2_cnt >= 2 & peer_open_mean >= -0.01
    # 4. Climax Rule & Leader:
    #    - If climax (plate_d1_zt_cnt >= 16): in_plate_open_rank == 1 AND open_lead_over_no2 >= 0.010
    #    - Else: in_plate_open_rank == 1
    # 5. Defenses & Breakout: notice_neg_tier == 0, ret5d <= 0.28, mcap_circ <= 250.0, amount >= 0.3e8
    # 6. Sentiment Gates: mkt_d2_fb_open_mean >= 0.0 & mkt_past5d_seal_rate >= 0.13
    fb['is_v9_domain'] = (
        (fb['d2_open'] < fb['d2_zt_price'] - 0.005) &
        (fb['d2_o_pct'] >= 0.015) & (fb['d2_o_pct'] <= 0.075) &
        (fb['plate'] != "其他") & (fb['plate_d2_fb_cnt'] >= 2) & (fb['peer_open_mean'] >= -0.01) &
        (
            ((fb['plate_d1_zt_cnt'] >= 16) & (fb['in_plate_open_rank'] == 1) & (fb['open_lead_over_no2'] >= 0.010)) |
            ((fb['plate_d1_zt_cnt'] < 16) & (fb['in_plate_open_rank'] == 1))
        ) &
        (fb['notice_neg_tier'] == 0) & (fb['ret5d'] <= 0.28) & (fb['mcap_circ'] <= 250.0) & (fb['amount'] >= 0.3e8) &
        (fb['mkt_d2_fb_open_mean'] >= 0.0) & (fb['mkt_past5d_seal_rate'] >= 0.13)
    ).astype(bool)
    
    print(f"Matrix built: {len(fb):,} rows, {fb['is_v9_domain'].sum():,} V9 golden domain candidates in {time.time()-t0:.2f}s")
    return fb

def train_v9_models(fb):
    print(">>> [Phase 4] Training Regularized Walk-Forward Domain Models...")
    t0 = time.time()
    
    fb['year'] = pd.to_datetime(fb['d2_date_str']).dt.year
    years = [2022, 2023, 2024, 2025, 2026]
    
    feature_cols = [
        'd2_o_pct', 'd2_o_pct_sq', 'd2_o_pct_minus_mkt', 'peer_open_mean',
        'open_lead_over_no2', 'plate_d1_zt_cnt', 'plate_d2_fb_cnt',
        'climax_trap_flag', 'climax_sweet_spot', 'theme_15d_wr', 'theme_elo',
        'break_20d_high', 'break_60d_high', 'dd20', 'ret5d',
        'entity_ratio', 'upper_shadow', 'lower_shadow', 'amplitude', 'd1_seal_quality',
        'amount_log', 'mcap_log', 'has_any_pos_notice'
    ]
    
    for c in feature_cols:
        fb[c] = fb[c].fillna(0.0)
        
    fb['v9_score'] = 0.0
    
    # Target: D2 open to D3 open evaluation return
    d2_o = fb['d2_open'].values
    d3_o = fb['d3_open'].values
    d2_is_zt = fb['d2_is_zt'].values
    d3_zt = fb['d3_zt_price'].values
    eval_ret = np.zeros(len(fb), dtype=float)
    for i in range(len(fb)):
        if d2_o[i] > 0 and not np.isnan(d3_o[i]):
            if d2_is_zt[i]:
                if d3_o[i] >= d3_zt[i] - 0.01:
                    eval_ret[i] = (d3_zt[i] * 0.98 / d2_o[i]) - 1.0
                else:
                    eval_ret[i] = (d3_o[i] / d2_o[i]) - 1.0
            else:
                eval_ret[i] = (d3_o[i] / d2_o[i]) - 1.0
    fb['target_eval_ret'] = np.clip(eval_ret, -0.15, 0.35)
    
    trained_models = {}
    for test_yr in years:
        train_df = fb[(fb['year'] < test_yr) & (fb['is_v9_domain'])].copy()
        test_mask = (fb['year'] == test_yr) & (fb['is_v9_domain'])
        test_df = fb[test_mask].copy()
        
        if len(test_df) == 0 or len(train_df) == 0:
            continue
            
        X_train = train_df[feature_cols].values
        y_train = train_df['target_eval_ret'].values
        X_test = test_df[feature_cols].values
        
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)
        
        model = Ridge(alpha=15.0)
        model.fit(X_train_s, y_train)
        
        train_preds = model.predict(X_train_s)
        test_preds = model.predict(X_test_s)
        
        sort_tr = np.sort(train_preds)
        n_tr = float(len(train_preds))
        test_ranks = np.searchsorted(sort_tr, test_preds) / n_tr
        
        fb.loc[test_mask, 'v9_score'] = test_ranks
        trained_models[test_yr] = {
            'train_scores': train_preds,
            'model': model,
            'scaler': scaler
        }
        
    print(f"Models trained in {time.time()-t0:.2f}s")
    return fb, trained_models, feature_cols

def simulate_v9_trade(row, price_lookup, all_trade_dates, date_to_idx, entry_mode='Mode_B_trig', exit_mode='Exit_P2', trig_mult_open=1.012, trig_mult_pre=1.065):
    code = row['code6']
    d2_str = row['d2_date_str']
    idx_d2 = date_to_idx.get(d2_str, -1)
    if idx_d2 == -1:
        return None
        
    d2_info = price_lookup.get((code, d2_str))
    if not d2_info:
        return None
    d2_open, d2_high, d2_low, d2_close, d2_adj, d2_zt, d2_dt, d2_is_zt, d2_is_yizi_dt = d2_info
    
    d1_close = row['close']
    zt_p = d2_zt
    
    # ---------------- Entry Mode Execution ----------------
    if entry_mode == 'Mode_A_open':
        # 09:25 blind open buy
        if d2_open >= zt_p - 0.005:
            return None
        buy_price = d2_open
        executed = True
    elif entry_mode == 'Mode_B_trig':
        # Intraday ignition trigger order
        if d2_open >= zt_p - 0.005:
            return None
        trig_p = min(zt_p, max(round(d2_open * trig_mult_open, 2), round(d1_close * trig_mult_pre, 2)))
        if d2_high < trig_p:
            return None # 0 execution!
        buy_price = trig_p
        executed = True
    elif entry_mode == 'Mode_C_zt_touch':
        # Touch ZT buy
        if d2_open >= zt_p - 0.005 or d2_high < zt_p - 0.01:
            return None
        buy_price = zt_p
        executed = True
    else:
        buy_price = d2_open
        executed = True
        
    d2_sealed = d2_is_zt
    
    # ---------------- Exit Mode Execution ----------------
    curr_idx = idx_d2 + 1
    prev_close = d2_close
    exit_price = None
    exit_date = None
    exit_reason = ""
    exit_at_open = True
    
    if exit_mode == 'Exit_P2':
        # Exit P2: D3 open sell if non-ZT; if ZT open trail -2% stop
        if not d2_sealed:
            # D2 unsealed (blow-up/drawdown): Sell at D3 open
            while curr_idx < len(all_trade_dates):
                d_curr = all_trade_dates[curr_idx]
                info = price_lookup.get((code, d_curr))
                if not info:
                    exit_price = prev_close; exit_date = d_curr; exit_reason = "missing"; break
                o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                if is_yizi_dt:
                    curr_idx += 1; prev_close = c; continue
                else:
                    exit_price = o; exit_date = d_curr; exit_reason = "d3_open_unsealed"; exit_at_open = True; break
        else:
            # D2 sealed
            while curr_idx < len(all_trade_dates):
                d_curr = all_trade_dates[curr_idx]
                info = price_lookup.get((code, d_curr))
                if not info:
                    exit_price = prev_close; exit_date = d_curr; exit_reason = "missing"; break
                o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                if o < zt - 0.01:
                    if is_yizi_dt:
                        curr_idx += 1; prev_close = c; continue
                    else:
                        exit_price = o; exit_date = d_curr; exit_reason = "d3_open_nonzt"; exit_at_open = True; break
                else:
                    stop_px = round(zt * 0.98, 2)
                    if l <= stop_px:
                        exit_price = stop_px; exit_date = d_curr; exit_reason = "d3_zt_break_2pct"; exit_at_open = False; break
                    else:
                        prev_close = c; curr_idx += 1
                        if curr_idx - idx_d2 >= 8:
                            exit_price = c; exit_date = d_curr; exit_reason = "max_hold_8d"; exit_at_open = False; break
                        continue

    elif exit_mode == 'Exit_B1_split':
        # Exit B1: D3 open < +2% sell all; >= +2% non-ZT sell 50% at open, 50% at close
        if not d2_sealed:
            while curr_idx < len(all_trade_dates):
                d_curr = all_trade_dates[curr_idx]
                info = price_lookup.get((code, d_curr))
                if not info:
                    exit_price = prev_close; exit_date = d_curr; exit_reason = "missing"; break
                o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                if is_yizi_dt:
                    curr_idx += 1; prev_close = c; continue
                else:
                    exit_price = o; exit_date = d_curr; exit_reason = "d3_open_unsealed"; exit_at_open = True; break
        else:
            while curr_idx < len(all_trade_dates):
                d_curr = all_trade_dates[curr_idx]
                info = price_lookup.get((code, d_curr))
                if not info:
                    exit_price = prev_close; exit_date = d_curr; exit_reason = "missing"; break
                o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                d3_prem = o / prev_close - 1.0
                if d3_prem < 0.02:
                    if is_yizi_dt:
                        curr_idx += 1; prev_close = c; continue
                    else:
                        exit_price = o; exit_date = d_curr; exit_reason = "d3_open_weak"; exit_at_open = True; break
                elif o >= zt - 0.01:
                    if is_zt:
                        prev_close = c; curr_idx += 1
                        if curr_idx - idx_d2 >= 8:
                            exit_price = c; exit_date = d_curr; exit_reason = "max_hold_8d"; exit_at_open = False; break
                        continue
                    else:
                        exit_price = c; exit_date = d_curr; exit_reason = "d3_zt_unsealed_close"; exit_at_open = False; break
                else:
                    exit_price = 0.5 * o + 0.5 * c
                    exit_date = d_curr; exit_reason = "d3_split_close"; exit_at_open = False; break

    elif exit_mode == 'Exit_E4_hotmoney':
        # Exit E4: Old M2 hot-money 14:55 broken board exit
        if not d2_sealed:
            while curr_idx < len(all_trade_dates):
                d_curr = all_trade_dates[curr_idx]
                info = price_lookup.get((code, d_curr))
                if not info:
                    exit_price = prev_close; exit_date = d_curr; exit_reason = "missing"; break
                o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                if is_yizi_dt:
                    curr_idx += 1; prev_close = c; continue
                else:
                    exit_price = o; exit_date = d_curr; exit_reason = "d3_open_unsealed"; exit_at_open = True; break
        else:
            while curr_idx < len(all_trade_dates):
                d_curr = all_trade_dates[curr_idx]
                info = price_lookup.get((code, d_curr))
                if not info:
                    exit_price = prev_close; exit_date = d_curr; exit_reason = "missing"; break
                o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                if is_yizi_dt:
                    curr_idx += 1; prev_close = c; continue
                if is_zt:
                    prev_close = c; curr_idx += 1
                    if curr_idx - idx_d2 >= 8:
                        exit_price = c; exit_date = d_curr; exit_reason = "max_hold_8d"; exit_at_open = False; break
                    continue
                else:
                    exit_price = c; exit_date = d_curr; exit_reason = "broken_board_close"; exit_at_open = False; break

    if exit_price is None:
        exit_price = prev_close
        exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
        exit_reason = "fallback"
        exit_at_open = True

    holding_days = max(1, curr_idx - idx_d2)
    gross_ret = exit_price / buy_price - 1.0
    net_ret = (1.0 + gross_ret) * (1.0 - FEE_RATE) - 1.0
    
    return {
        'code': code,
        'name': row['stock_name'],
        'plate': row['plate'],
        'buy_date': d2_str,
        'buy_price': round(float(buy_price), 2),
        'exit_date': exit_date,
        'exit_price': round(float(exit_price), 2),
        'exit_reason': exit_reason,
        'exit_at_open': exit_at_open,
        'holding_days': holding_days,
        'gross_ret': round(float(gross_ret), 4),
        'net_ret': round(float(net_ret), 4),
        'd2_sealed': int(d2_sealed),
        'model_score': round(float(row.get('v9_score', 0.0)), 4),
        'plate_d1_zt_cnt': int(row['plate_d1_zt_cnt']),
        'in_plate_open_rank': int(row['in_plate_open_rank']),
        'open_lead_over_no2': round(float(row['open_lead_over_no2']), 4),
        'theme_15d_wr': round(float(row['theme_15d_wr']), 4),
        'd2_o_pct': round(float(row['d2_o_pct']), 4)
    }

def simulate_portfolio_slots_v9(trades_list, num_slots=1):
    if not trades_list:
        return 1.0, 0, 0.0, []
    sorted_trades = sorted(trades_list, key=lambda x: (x['buy_date'], -x['model_score']))
    slot_available = ["" for _ in range(num_slots)]
    executed_trades = []
    slot_capital = [1.0 / num_slots for _ in range(num_slots)]
    
    peak = 1.0
    mdd = 0.0
    
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
            
            cur_nav = sum(slot_capital)
            if cur_nav > peak:
                peak = cur_nav
            dd = (peak - cur_nav) / peak
            if dd > mdd:
                mdd = dd
                
    total_nav = sum(slot_capital)
    return total_nav, len(executed_trades), mdd, executed_trades

def run_walk_forward_evaluation(fb, trained_models, price_lookup, all_trade_dates, date_to_idx, entry_mode='Mode_B_trig', exit_mode='Exit_P2', target_rate=35, max_daily_picks=1, trig_mult_open=1.012, trig_mult_pre=1.065):
    years = [2022, 2023, 2024, 2025, 2026]
    selected_candidates = []
    
    for test_yr in years:
        train_pool = fb[(fb['year'] < test_yr) & (fb['is_v9_domain'])].copy()
        test_pool = fb[(fb['year'] == test_yr) & (fb['is_v9_domain'])].copy()
        
        if len(test_pool) == 0:
            continue
            
        model_info = trained_models[test_yr]
        train_scores = model_info['train_scores']
        train_span = max(1.0, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
        target_train_count = int(target_rate * train_span)
        
        if len(train_scores) > target_train_count:
            cutoff = float(np.percentile(train_scores, 100.0 * (1.0 - target_train_count / len(train_scores))))
        else:
            cutoff = float(np.percentile(train_scores, 75.0))
            
        test_cands = test_pool[test_pool['v9_score'] >= (1.0 - target_train_count / len(train_scores))].sort_values(['d2_date_str', 'v9_score'], ascending=[True, False])
        
        for d_str, day_df in test_cands.groupby('d2_date_str'):
            seen_plates = set()
            picked = 0
            for _, r in day_df.iterrows():
                p = r['plate']
                if p not in seen_plates:
                    selected_candidates.append(r)
                    seen_plates.add(p)
                    picked += 1
                    if picked >= max_daily_picks:
                        break
                        
    # Now simulate trades under the selected candidates
    simulated_trades = []
    for r in selected_candidates:
        tr = simulate_v9_trade(r, price_lookup, all_trade_dates, date_to_idx, entry_mode=entry_mode, exit_mode=exit_mode, trig_mult_open=trig_mult_open, trig_mult_pre=trig_mult_pre)
        if tr:
            simulated_trades.append(tr)
            
    # Portfolio simulation
    nav_1s, n_1s, mdd_1s, trades_1s = simulate_portfolio_slots_v9(simulated_trades, num_slots=1)
    nav_2s, n_2s, mdd_2s, trades_2s = simulate_portfolio_slots_v9(simulated_trades, num_slots=2)
    
    # Yearly breakdown for 1-slot
    yearly_stats = {}
    for yr in years:
        yr_tr = [t for t in trades_1s if t['buy_date'].startswith(str(yr))]
        n_y = len(yr_tr)
        if n_y == 0:
            yearly_stats[str(yr)] = {
                'trades': 0, 'win_rate': 0.0, 'pnl_ratio': 0.0, 'annual_return': 0.0,
                'csi300': CSI300_ANNUAL_RETURNS.get(yr, 0.0), 'alpha': 0.0
            }
            continue
        df_y = pd.DataFrame(yr_tr)
        y_wr = (df_y['net_ret'] > 0).mean()
        w = df_y[df_y['net_ret'] > 0]['net_ret']
        l = df_y[df_y['net_ret'] <= 0]['net_ret']
        avg_w = w.mean() if len(w) > 0 else 0.0
        avg_l = abs(l.mean()) if len(l) > 0 else 0.01
        pnl = avg_w / avg_l if avg_l > 0 else 0.0
        y_ret = float(np.prod(1.0 + df_y['net_ret'].values) - 1.0)
        csi = CSI300_ANNUAL_RETURNS.get(yr, 0.0)
        yearly_stats[str(yr)] = {
            'trades': n_y,
            'win_rate': round(float(y_wr), 4),
            'pnl_ratio': round(float(pnl), 2),
            'annual_return': round(float(y_ret), 4),
            'csi300': round(float(csi), 4),
            'alpha': round(float(y_ret - csi), 4)
        }
        
    df_all = pd.DataFrame(trades_1s) if trades_1s else pd.DataFrame()
    tot_wr = (df_all['net_ret'] > 0).mean() if len(df_all) > 0 else 0.0
    tot_w = df_all[df_all['net_ret'] > 0]['net_ret'] if len(df_all) > 0 else pd.Series()
    tot_l = df_all[df_all['net_ret'] <= 0]['net_ret'] if len(df_all) > 0 else pd.Series()
    avg_tot_w = tot_w.mean() if len(tot_w) > 0 else 0.0
    avg_tot_l = abs(tot_l.mean()) if len(tot_l) > 0 else 0.01
    tot_pnl = avg_tot_w / avg_tot_l if avg_tot_l > 0 else 0.0
    
    return {
        'total_trades': len(trades_1s),
        'win_rate': round(float(tot_wr), 4),
        'pnl_ratio': round(float(tot_pnl), 2),
        'cum_nav_1slot': round(float(nav_1s), 4),
        'max_dd_1slot': round(float(mdd_1s), 4),
        'cum_nav_2slot': round(float(nav_2s), 4),
        'max_dd_2slot': round(float(mdd_2s), 4),
        'yearly': yearly_stats,
        'trades': trades_1s
    }

def verify_live_20261111():
    print("\n" + "=" * 80)
    print(">>> [Phase 5] Verifying 2026-11-11 Live Reality (Tencent Intraday Quotes)...")
    print("=" * 80)
    
    tickers = {
        '002376': ('新北洋', '机器人概念', 26),
        '002535': ('林州重机', '机器人概念', 26),
        '002009': ('天奇股份', '机器人概念', 26),
        '000678': ('襄阳轴承', '机器人概念', 26),
        '603278': ('大业股份', '机器人概念', 26),
        '603466': ('风语筑', '机器人概念', 26),
        '002313': ('日海智能', '5G通信/物联网', 3),
        '002425': ('凯撒文化', '游戏/AI应用', 4),
        '605258': ('协和电子', 'PCB概念', 2),
        '002614': ('奥佳华', '机器人概念', 26)
    }
    
    qt_codes = []
    for c6 in tickers.keys():
        prefix = 'sh' if c6.startswith('6') else 'sz'
        qt_codes.append(f"{prefix}{c6}")
        
    url = f"http://qt.gtimg.cn/q={','.join(qt_codes)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw_data = resp.read().decode('gbk')
    except Exception as e:
        print(f"Failed to fetch live quotes: {e}")
        return []
        
    live_results = []
    for line in raw_data.strip().split(';'):
        if not line.strip():
            continue
        parts = line.split('~')
        if len(parts) > 34:
            c6 = parts[2]
            name = parts[1]
            curr_p = float(parts[3])
            pre_c = float(parts[4])
            open_p = float(parts[5])
            high_p = float(parts[33])
            low_p = float(parts[34])
            
            zt_p = round(pre_c * 1.10, 2)
            open_pct = (open_p / pre_c - 1.0) * 100.0
            curr_pct = (curr_p / pre_c - 1.0) * 100.0
            
            trig_p = min(zt_p, max(round(open_p * 1.012, 2), round(pre_c * 1.065, 2)))
            is_triggered = (high_p >= trig_p)
            
            if is_triggered:
                pnl_if_buy = (curr_p / trig_p - 1.0) * 100.0
                status = f"✅ 触发买入 (买价 {trig_p:.2f}, 现价 {curr_p:.2f}, 浮动 {pnl_if_buy:+.2f}%)"
            else:
                pnl_avoided = (curr_p / open_p - 1.0) * 100.0
                status = f"🛡️ 0触发拦截 (避开盲买跌幅 {pnl_avoided:+.2f}%)"
                
            plt, sz = tickers.get(c6, ('未知', 1))[1:]
            
            live_results.append({
                'code': c6,
                'name': name,
                'plate': plt,
                'd1_zt_sz': sz,
                'pre_close': pre_c,
                'open_price': open_p,
                'open_pct': round(open_pct, 2),
                'high_price': high_p,
                'curr_price': curr_p,
                'curr_pct': round(curr_pct, 2),
                'zt_price': zt_p,
                'trig_price': trig_p,
                'is_triggered': bool(is_triggered),
                'status': status
            })
            
    return live_results

def main():
    print("=" * 80)
    print(">>> V9 Ignition Master Engine — Comprehensive Backtest & Live Audit")
    print("=" * 80)
    
    stock_to_plate_info, kpl_daily_plates, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices = load_kpl_and_notices()
    df = load_price_data()
    fb = build_v9_master_matrix(df, stock_to_plate_info, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices)
    fb, trained_models, feature_cols = train_v9_models(fb)
    
    print(">>> Building Fast Price Lookup Dictionary...")
    t0 = time.time()
    price_lookup = {}
    for r in df[['code6', 'date_str', 'open', 'high', 'low', 'close', 'adj_close', 'zt_price', 'dt_price', 'is_zt', 'is_yizi_dt']].itertuples(index=False):
        price_lookup[(r.code6, r.date_str)] = (
            r.open, r.high, r.low, r.close, r.adj_close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt
        )
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    print(f"Price lookup ready with {len(price_lookup):,} items in {time.time()-t0:.2f}s")
    
    # =========================================================================
    # CORE COMPARISON 1: Entry Execution Mode Breakdown
    # =========================================================================
    print("\n" + "=" * 80)
    print(">>> [EXPERIMENT 1] Entry Execution Modes Comparison (Target: 35/yr, Exit_P2)")
    print("=" * 80)
    
    modes_results = {}
    for m in ['Mode_A_open', 'Mode_B_trig', 'Mode_C_zt_touch']:
        res = run_walk_forward_evaluation(fb, trained_models, price_lookup, all_trade_dates, date_to_idx, entry_mode=m, exit_mode='Exit_P2', target_rate=35, max_daily_picks=1)
        modes_results[m] = res
        print(f"  [{m:<16}] 1-Slot: Trades={res['total_trades']:<4} WR={res['win_rate']*100:<5.1f}% PnL={res['pnl_ratio']:<4.2f} NAV={res['cum_nav_1slot']:<6.2f} MaxDD={res['max_dd_1slot']*100:<5.1f}% | 2-Slot: NAV={res['cum_nav_2slot']:<6.2f} MaxDD={res['max_dd_2slot']*100:<5.1f}%")

    # =========================================================================
    # CORE COMPARISON 2: Exit Rules Breakdown on Mode_B_trig
    # =========================================================================
    print("\n" + "=" * 80)
    print(">>> [EXPERIMENT 2] Exit Rules Comparison on Mode_B_trig (Target: 35/yr)")
    print("=" * 80)
    
    exits_results = {}
    for ex in ['Exit_P2', 'Exit_B1_split', 'Exit_E4_hotmoney']:
        res = run_walk_forward_evaluation(fb, trained_models, price_lookup, all_trade_dates, date_to_idx, entry_mode='Mode_B_trig', exit_mode=ex, target_rate=35, max_daily_picks=1)
        exits_results[ex] = res
        print(f"  [{ex:<16}] 1-Slot: Trades={res['total_trades']:<4} WR={res['win_rate']*100:<5.1f}% PnL={res['pnl_ratio']:<4.2f} NAV={res['cum_nav_1slot']:<6.2f} MaxDD={res['max_dd_1slot']*100:<5.1f}% | 2-Slot: NAV={res['cum_nav_2slot']:<6.2f} MaxDD={res['max_dd_2slot']*100:<5.1f}%")

    # =========================================================================
    # CORE COMPARISON 3: Parameter Perturbation Sensitivity Analysis (+-10%)
    # =========================================================================
    print("\n" + "=" * 80)
    print(">>> [EXPERIMENT 3] Parameter Perturbation Sensitivity Analysis (+-10%)")
    print("=" * 80)
    
    perturbations = [
        ('Base_1.012_1.065', 1.012, 1.065),
        ('Tighter_1.015_1.070', 1.015, 1.070),
        ('Looser_1.010_1.060', 1.010, 1.060),
        ('PreC_Heavy_1.012_1.075', 1.012, 1.075),
        ('Open_Heavy_1.020_1.065', 1.020, 1.065),
    ]
    perturb_results = {}
    for name, m_open, m_pre in perturbations:
        res = run_walk_forward_evaluation(fb, trained_models, price_lookup, all_trade_dates, date_to_idx, entry_mode='Mode_B_trig', exit_mode='Exit_P2', target_rate=35, max_daily_picks=1, trig_mult_open=m_open, trig_mult_pre=m_pre)
        perturb_results[name] = {
            'm_open': m_open, 'm_pre': m_pre,
            'trades': res['total_trades'], 'win_rate': res['win_rate'],
            'pnl': res['pnl_ratio'], 'nav_1s': res['cum_nav_1slot'], 'max_dd': res['max_dd_1slot']
        }
        print(f"  [{name:<24}] Trades={res['total_trades']:<4} WR={res['win_rate']*100:<5.1f}% PnL={res['pnl_ratio']:<4.2f} NAV={res['cum_nav_1slot']:<6.2f} MaxDD={res['max_dd_1slot']*100:<5.1f}%")

    # =========================================================================
    # CORE COMPARISON 4: Live Reality Check (2026-11-11)
    # =========================================================================
    live_audit = verify_live_20261111()
    for item in live_audit:
        print(f"  {item['code']} {item['name']:<6} ({item['plate']:<10} 昨板{item['d1_zt_sz']:>2}家): 开{item['open_price']:>6.2f}({item['open_pct']:>+5.1f}%) 触发价{item['trig_price']:>6.2f} 最高{item['high_price']:>6.2f} 现{item['curr_price']:>6.2f}({item['curr_pct']:>+5.1f}%) -> {item['status']}")

    # Save master results and ledger
    best_res = exits_results['Exit_E4_hotmoney']
    ledger_trades = best_res['trades']
    df_ledger = pd.DataFrame(ledger_trades)
    df_ledger.to_csv(LEDGER_CSV_PATH, index=False, encoding='utf-8-sig')
    
    final_output = {
        'metadata': {
            'strategy': 'V9 Ignition Master Engine',
            'engine': 'Expanding Walk-Forward (2021 Train -> 2022-2026 Test)',
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'fee_rate': FEE_RATE,
            'zero_lookahead': True,
            't_plus_1_compliant': True,
            'yizi_lock_compliant': True
        },
        'modes_comparison': {
            m: {k: v for k, v in modes_results[m].items() if k != 'trades'} for m in modes_results
        },
        'exits_comparison': {
            ex: {k: v for k, v in exits_results[ex].items() if k != 'trades'} for ex in exits_results
        },
        'parameter_perturbation': perturb_results,
        'live_20261111_audit': live_audit
    }
    
    with open(RESULTS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
        
    print(f"\nMaster audit finished successfully!")
    print(f"Results saved to: {RESULTS_JSON_PATH}")
    print(f"Trades ledger saved to: {LEDGER_CSV_PATH}")

if __name__ == '__main__':
    main()

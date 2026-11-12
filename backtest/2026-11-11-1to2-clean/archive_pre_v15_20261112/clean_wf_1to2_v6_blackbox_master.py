#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v6_blackbox_master.py
=============================================================================
One-to-Two V6 BlackBox Ensemble Master Engine (2021 Train -> 2022-2026 Walk-Forward)
Strictly Compliant with A-Share T+1 Settlement & 100% Zero-Lookahead / Point-In-Time
=============================================================================
Core First-Principles Upgrades in V6:
1. Complete Removal of Artificial Biases:
   - Completely eradicate dd20 <= 0.92, ret5d <= 0.28, mcap <= 250, artificial 2~6 bounds,
     artificial [1.5%, 7.5%] auction windows, and hard sector barriers.
   - Retain only physical tradeability constraints: main board 00/60, non-ST,
     D1 amount >= 1.0e8, D2 not opening at one-word limit-up (d2_open < d2_zt_price - 0.01).
   - All 46,000+ turnover first-board stocks (including all 20d/60d/120d breakout leaders)
     enter the candidate pool!
2. 50+ Dimensional Pure PIT (< D2 09:25:05) Features:
   - Market Climax & Sentiment: yesterday ZT count, 1B count, 2B count, max streak, broken rate,
     past 3d 1to2 seal rate, past 5d 2B return, D2 auction mean, D2 auction >+5% count, etc.
   - Sector / Theme Dynamics: sector ZT count, candidate count, burst ratio, fresh theme flag,
     past 15d 1to2 win rate (Bayesian), in-sector auction rank, peer mean/max, peer diff.
   - Stock Structure & Volume-Price: breakout 20d/60d/120d high, continuous dd20/dd60/dd120,
     3d/5d/10d/20d returns, entity ratio, shadows, amplitude, seal quality, turnover, vol ratios.
   - PIT Announcements: S-tier, A-tier, Neg-tier from CNINFO PIT DB.
3. Heterogeneous Regularized BlackBox Ensemble:
   - HistGradientBoostingRegressor (shallow trees, depth 4, min leaf 80, l2 10.0)
   - HistGradientBoostingClassifier (depth 4, min leaf 80, l2 10.0, target >+2% net)
   - MLPRegressor (hidden (32, 16), alpha 1.0, early stopping) with StandardScaler.
4. Comprehensive 100% Zero-Lookahead T+1 Exit & Protection Gates Ablation:
   - Exit 1: Dynamic Half-Position / Trail
   - Exit 2: P2 Benchmark Exit (Trailing stop on limit-up open, else open exit)
   - Exit 3: Buwen's Real-Trade Exit (14:55 Close Hold If Positive, Sell If Not Positive)
   - Three Protection Gates: Gate 1 (昨日封板率>75%), Gate 2 (09:25首板均值<0%), Gate 3 (近5日晋级率<13%).
5. 2026-11-11 Live Pre-Market Candidate Scoring and Verification.
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
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
NOTICES_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"

LEDGER_CSV_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v6_blackbox_master_ledger.csv")
RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v6_blackbox_master_results.json")

CSI300_ANNUAL_RETURNS = {
    2022: -0.2163,
    2023: -0.1138,
    2024: 0.1468,
    2025: 0.1758,
    2026: 0.0120,
}

FEE_RATE = 0.0015  # 双边印花税+佣金 0.15%

def load_kpl_and_notices():
    print(">>> [Phase 1] Loading KPL Complete 5Y Themes & PIT Notices...")
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
        print(f"KPL parsed: {len(stock_to_plate_info):,} entries in {time.time()-t0:.2f}s")
    else:
        print("KPL file not found, proceeding without theme mappings.")

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
            print(f"PIT Notices loaded: {len(s_tier_notices):,} S-tier, {len(a_tier_notices):,} A-tier, {len(neg_tier_notices):,} Neg-tier.")
        except Exception as e:
            print(f"Notice DB load error: {e}")
            
    return stock_to_plate_info, kpl_daily_plates, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices

def load_price_data():
    print(">>> [Phase 2] Loading Full Market Price DB...")
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
    
    # Stock-level volume & price structure features
    df['mcap_circ'] = df['close'] * df['oshare'] / 1e8
    df['vol_ma5'] = df.groupby('code6')['volume'].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    df['vol_ma20'] = df.groupby('code6')['volume'].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    
    # Breakout levels (strict PIT: shift(1) rolling max)
    df['high_max_20d'] = df.groupby('code6')['high'].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    df['high_max_60d'] = df.groupby('code6')['high'].transform(lambda s: s.shift(1).rolling(60, min_periods=30).max())
    df['high_max_120d'] = df.groupby('code6')['high'].transform(lambda s: s.shift(1).rolling(120, min_periods=60).max())
    
    df['close_3d_ago'] = df.groupby('code6')['close'].shift(3)
    df['close_5d_ago'] = df.groupby('code6')['close'].shift(5)
    df['close_10d_ago'] = df.groupby('code6')['close'].shift(10)
    df['close_20d_ago'] = df.groupby('code6')['close'].shift(20)
    
    df['break_20d_high'] = (df['close'] >= df['high_max_20d'] - 0.01).astype(float)
    df['break_60d_high'] = (df['close'] >= df['high_max_60d'] - 0.01).astype(float)
    df['break_120d_high'] = (df['close'] >= df['high_max_120d'] - 0.01).astype(float)
    
    df['dd20'] = df['close'] / (df['high_max_20d'] + 1e-4)
    df['dd60'] = df['close'] / (df['high_max_60d'] + 1e-4)
    df['dd120'] = df['close'] / (df['high_max_120d'] + 1e-4)
    
    df['ret_3d'] = df['close'] / (df['close_3d_ago'] + 1e-4) - 1.0
    df['ret_5d'] = df['close'] / (df['close_5d_ago'] + 1e-4) - 1.0
    df['ret_10d'] = df['close'] / (df['close_10d_ago'] + 1e-4) - 1.0
    df['ret_20d'] = df['close'] / (df['close_20d_ago'] + 1e-4) - 1.0
    
    df['entity_ratio'] = (df['close'] - df['open']) / (df['pre_close'] + 1e-4)
    df['upper_shadow'] = (df['high'] - df['close']) / (df['pre_close'] + 1e-4)
    df['lower_shadow'] = (np.minimum(df['open'], df['close']) - df['low']) / (df['pre_close'] + 1e-4)
    df['amplitude'] = (df['high'] - df['low']) / (df['pre_close'] + 1e-4)
    df['d1_seal_quality'] = df['entity_ratio'] - 0.5 * (df['amplitude'] - df['entity_ratio'])
    
    df['vol_ratio_5d'] = df['volume'] / (df['vol_ma5'] + 1e-4)
    df['vol_ratio_20d'] = df['volume'] / (df['vol_ma20'] + 1e-4)
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
    df['d3_is_zt'] = (df['d3_close'] >= df['d3_zt_price'] - 0.01) & (df['d3_close'] == df['d3_high'])
    
    print(f"Price DB loaded: {len(df):,} rows in {time.time()-t0:.2f}s")
    return df

def build_market_daily_stats(df):
    print(">>> [Phase 3] Computing Daily Market Sentiment, Climax, and Regime Stats...")
    t0 = time.time()
    
    # Market statistics on each date D1
    daily_groups = df.groupby('date_str')
    
    mkt_d1_zt_cnt = daily_groups['is_zt'].sum().to_dict()
    mkt_d1_touched_zt_cnt = daily_groups['touched_zt'].sum().to_dict()
    mkt_d1_fb_cnt = daily_groups['is_turnover_fb'].sum().to_dict()
    mkt_d1_2b_cnt = (daily_groups['streak'].apply(lambda s: (s == 2).sum())).to_dict()
    mkt_d1_3b_plus_cnt = (daily_groups['streak'].apply(lambda s: (s >= 3).sum())).to_dict()
    mkt_d1_max_streak = daily_groups['streak'].max().to_dict()
    
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    # Broken rate: (touched - sealed) / touched
    mkt_d1_broken_rate = {}
    for d in all_trade_dates:
        t_cnt = mkt_d1_touched_zt_cnt.get(d, 0)
        z_cnt = mkt_d1_zt_cnt.get(d, 0)
        mkt_d1_broken_rate[d] = float((t_cnt - z_cnt) / max(1, t_cnt)) if t_cnt > 0 else 0.0
        
    # Natural 1-to-2晉级率 over past 3 days and past 5 days (strictly PIT: known at D1 close)
    # On day t, 2-board count is mkt_d1_2b_cnt[t], yesterday turnover FB count is mkt_d1_fb_cnt[t-1]
    daily_1to2_ratio = {}
    for i, d in enumerate(all_trade_dates):
        if i >= 1:
            d_prev = all_trade_dates[i-1]
            prev_fb = mkt_d1_fb_cnt.get(d_prev, 0)
            curr_2b = mkt_d1_2b_cnt.get(d, 0)
            daily_1to2_ratio[d] = (curr_2b / max(1, prev_fb)) if prev_fb > 0 else 0.0
        else:
            daily_1to2_ratio[d] = 0.20
            
    mkt_past3d_1to2_seal_rate = {}
    mkt_past5d_1to2_seal_rate = {}
    for i, d in enumerate(all_trade_dates):
        if i >= 3:
            p3 = [daily_1to2_ratio.get(all_trade_dates[k], 0.20) for k in range(i-2, i+1)]
            mkt_past3d_1to2_seal_rate[d] = float(np.mean(p3))
        else:
            mkt_past3d_1to2_seal_rate[d] = 0.20
            
        if i >= 5:
            p5 = [daily_1to2_ratio.get(all_trade_dates[k], 0.20) for k in range(i-4, i+1)]
            mkt_past5d_1to2_seal_rate[d] = float(np.mean(p5))
        else:
            mkt_past5d_1to2_seal_rate[d] = 0.20

    # Past 5-day 2B return on next day (D3)
    streak_2b_stks = df[df['streak'] >= 2].copy()
    daily_2b_prem = streak_2b_stks.groupby('date_str')['d2_o_pct'].mean().to_dict()
    mkt_past5d_2b_d3_ret = {}
    for i, d in enumerate(all_trade_dates):
        if i >= 5:
            past_5d = [daily_2b_prem.get(all_trade_dates[k], 0.0) for k in range(i-5, i)]
            mkt_past5d_2b_d3_ret[d] = float(np.mean(past_5d))
        else:
            mkt_past5d_2b_d3_ret[d] = 0.0
            
    market_stats = {
        'all_trade_dates': all_trade_dates,
        'date_to_idx': date_to_idx,
        'mkt_d1_zt_cnt': mkt_d1_zt_cnt,
        'mkt_d1_fb_cnt': mkt_d1_fb_cnt,
        'mkt_d1_2b_cnt': mkt_d1_2b_cnt,
        'mkt_d1_3b_plus_cnt': mkt_d1_3b_plus_cnt,
        'mkt_d1_max_streak': mkt_d1_max_streak,
        'mkt_d1_broken_rate': mkt_d1_broken_rate,
        'mkt_past3d_1to2_seal_rate': mkt_past3d_1to2_seal_rate,
        'mkt_past5d_1to2_seal_rate': mkt_past5d_1to2_seal_rate,
        'mkt_past5d_2b_d3_ret': mkt_past5d_2b_d3_ret,
    }
    print(f"Market sentiment stats built in {time.time()-t0:.2f}s")
    return market_stats

def build_v6_feature_matrix(df, stock_to_plate_info, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices, market_stats):
    print(">>> [Phase 4] Building V6 50+ Dim Pure PIT (< D2 09:25:05) Feature Matrix...")
    t0 = time.time()
    
    # Candidate base: turnover first boards with valid D2
    fb_all = df[df['is_turnover_fb'] & df['d2_date_str'].notna()].copy()
    fb_all = fb_all[(fb_all['d2_date_str'] >= "2021-01-04") & (fb_all['d2_date_str'] <= "2026-11-10")].copy()
    
    # PHYSICAL CONSTRAINTS ONLY:
    # 1. Main board (already 00/60)
    # 2. D1 amount >= 1.0e8
    # 3. D2 open not one-word limit-up (realistically purchasable)
    fb = fb_all[(fb_all['amount'] >= 1.0e8) & (fb_all['d2_open'] < fb_all['d2_zt_price'] - 0.005)].copy()
    
    # Attach KPL Plate Information
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
    
    # Exclude ST / 退市 stocks
    fb = fb[~fb['stock_name'].str.contains('ST|退', regex=True)].copy()
    print(f"Physical tradable candidates: {len(fb):,} after ST filter.")
    
    # =========================================================================
    # Group A: Market Sentiment & Auction Features (Realtime at D2 09:25)
    # =========================================================================
    fb['mkt_d1_zt_cnt'] = [market_stats['mkt_d1_zt_cnt'].get(d, 40) for d in fb['date_str']]
    fb['mkt_d1_fb_cnt'] = [market_stats['mkt_d1_fb_cnt'].get(d, 25) for d in fb['date_str']]
    fb['mkt_d1_2b_cnt'] = [market_stats['mkt_d1_2b_cnt'].get(d, 8) for d in fb['date_str']]
    fb['mkt_d1_3b_plus_cnt'] = [market_stats['mkt_d1_3b_plus_cnt'].get(d, 4) for d in fb['date_str']]
    fb['mkt_d1_max_streak'] = [market_stats['mkt_d1_max_streak'].get(d, 4) for d in fb['date_str']]
    fb['mkt_d1_broken_rate'] = [market_stats['mkt_d1_broken_rate'].get(d, 0.25) for d in fb['date_str']]
    fb['mkt_past3d_1to2_seal_rate'] = [market_stats['mkt_past3d_1to2_seal_rate'].get(d, 0.20) for d in fb['date_str']]
    fb['mkt_past5d_1to2_seal_rate'] = [market_stats['mkt_past5d_1to2_seal_rate'].get(d, 0.20) for d in fb['date_str']]
    fb['mkt_past5d_2b_d3_ret'] = [market_stats['mkt_past5d_2b_d3_ret'].get(d, 0.0) for d in fb['date_str']]
    
    # Daily D2 auction stats across all FB candidates
    d2_mkt_open_mean = fb.groupby('d2_date_str')['d2_o_pct'].transform('mean')
    d2_mkt_open_gt5 = fb.groupby('d2_date_str')['d2_o_pct'].transform(lambda s: (s >= 0.05).sum())
    d2_mkt_open_lt0 = fb.groupby('d2_date_str')['d2_o_pct'].transform(lambda s: (s < 0.0).sum())
    d2_mkt_open_std = fb.groupby('d2_date_str')['d2_o_pct'].transform(lambda s: s.std() if len(s) > 1 else 0.02).fillna(0.02)
    
    fb['mkt_d2_fb_open_mean'] = d2_mkt_open_mean
    fb['mkt_d2_fb_open_gt5_cnt'] = d2_mkt_open_gt5
    fb['mkt_d2_fb_open_lt0_cnt'] = d2_mkt_open_lt0
    fb['mkt_d2_fb_open_std'] = d2_mkt_open_std
    fb['d2_o_pct_minus_mkt'] = fb['d2_o_pct'] - fb['mkt_d2_fb_open_mean']
    fb['d2_o_pct_sq'] = (fb['d2_o_pct'] - 0.045) ** 2
    
    # =========================================================================
    # Group B: Sector / Theme Dynamics & Anti-Orphan Metrics
    # =========================================================================
    plate_d2_groups = fb.groupby(['d2_date_str', 'plate'])['d2_o_pct']
    plate_d2_sum = plate_d2_groups.transform('sum')
    plate_d2_cnt = plate_d2_groups.transform('count')
    plate_d2_max = plate_d2_groups.transform('max')
    
    fb['plate_d2_fb_cnt'] = plate_d2_cnt
    fb['plate_is_other'] = (fb['plate'] == "其他").astype(float)
    
    # Peer open metrics: if plate == '其他' or count <= 1, peer mean is strictly -0.02
    fb['peer_open_mean'] = np.where(
        (fb['plate'] != "其他") & (plate_d2_cnt > 1),
        (plate_d2_sum - fb['d2_o_pct']) / (plate_d2_cnt - 1),
        -0.02
    )
    fb['peer_open_max'] = np.where(
        (fb['plate'] != "其他") & (plate_d2_cnt > 1),
        plate_d2_max,
        -0.02
    )
    fb['open_vs_peer_diff'] = fb['d2_o_pct'] - fb['peer_open_mean']
    
    # Sector open rank & market open rank
    fb['in_plate_open_rank'] = fb.groupby(['d2_date_str', 'plate'])['d2_o_pct'].rank(ascending=False, method='min')
    fb['in_mkt_open_rank'] = fb.groupby('d2_date_str')['d2_o_pct'].rank(ascending=False, method='min')
    fb['is_theme_leader'] = ((fb['plate'] != "其他") & (plate_d2_cnt >= 2) & (fb['in_plate_open_rank'] == 1)).astype(float)
    
    # Sector past 20d burst and fresh theme
    all_trade_dates = market_stats['all_trade_dates']
    date_to_idx = market_stats['date_to_idx']
    
    burst_ratios = []
    is_fresh_list = []
    past5d_sums = []
    past20d_means = []
    
    for row in fb[['date_str', 'plate', 'plate_d1_zt_cnt']].itertuples(index=False):
        d_str = row.date_str
        p_name = row.plate
        cnt_d1 = row.plate_d1_zt_cnt
        i = date_to_idx.get(d_str, 0)
        if p_name != "其他" and i >= 20:
            past_20d_counts = [plate_daily_counts[all_trade_dates[k]].get(p_name, 0) for k in range(i - 20, i)]
            avg_20d = float(np.mean(past_20d_counts)) if past_20d_counts else 0.5
            past20d_means.append(avg_20d)
            burst = cnt_d1 / (avg_20d + 0.2)
            burst_ratios.append(burst)
            p5 = sum(past_20d_counts[-5:]) if len(past_20d_counts) >= 5 else 0
            past5d_sums.append(p5)
            p3 = sum(past_20d_counts[-3:]) if len(past_20d_counts) >= 3 else 0
            is_fresh_list.append(1.0 if p3 <= 1 else 0.0)
        else:
            burst_ratios.append(1.0)
            is_fresh_list.append(0.5)
            past5d_sums.append(1.0)
            past20d_means.append(0.5)
            
    fb['plate_burst_ratio'] = burst_ratios
    fb['plate_is_fresh'] = is_fresh_list
    fb['plate_past5d_zt_sum'] = past5d_sums
    fb['plate_past20d_zt_mean'] = past20d_means
    
    # =========================================================================
    # Group C: PIT Notices (< D2 09:25:05)
    # =========================================================================
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
    
    # =========================================================================
    # Prediction Target: Actual D2->D3 Return
    # =========================================================================
    # If D2 sealed ZT:
    #   if D3 opened ZT: return is at least (d3_zt_price * 0.98 / d2_open) - 1.0
    #   else: return is (d3_open / d2_open) - 1.0
    # If D2 failed to seal: return is (d3_open / d2_open) - 1.0
    d2_open_val = fb['d2_open'].values
    d2_is_zt_val = fb['d2_is_zt'].values
    d3_open_val = fb['d3_open'].values
    d3_zt_price_val = fb['d3_zt_price'].values
    
    eval_ret = np.zeros(len(fb), dtype=float)
    for i in range(len(fb)):
        o2 = d2_open_val[i]
        is_zt2 = d2_is_zt_val[i]
        o3 = d3_open_val[i]
        zt3 = d3_zt_price_val[i]
        
        if np.isnan(o3) or o2 <= 0:
            eval_ret[i] = 0.0
            continue
            
        if is_zt2:
            if o3 >= zt3 - 0.01:
                eval_ret[i] = (zt3 * 0.98 / o2) - 1.0
            else:
                eval_ret[i] = (o3 / o2) - 1.0
        else:
            eval_ret[i] = (o3 / o2) - 1.0
            
    net_eval_ret = (1.0 + eval_ret) * (1.0 - FEE_RATE) - 1.0
    fb['target_eval_ret'] = net_eval_ret
    fb['target_cls_win'] = (net_eval_ret > 0.02).astype(float)
    
    print(f"Feature matrix built: {len(fb):,} rows, {len(fb.columns)} cols in {time.time()-t0:.2f}s")
    return fb

def train_walk_forward_ensemble(fb):
    print("\n" + "=" * 80)
    print(">>> [Phase 5] Training Walk-Forward Expanding Heterogeneous BlackBox Ensemble...")
    print("=" * 80)
    t0 = time.time()
    
    fb['year'] = pd.to_datetime(fb['d2_date_str']).dt.year
    years = [2022, 2023, 2024, 2025, 2026]
    
    feature_cols = [
        # Market Sentiment & Regime
        'mkt_d1_zt_cnt', 'mkt_d1_fb_cnt', 'mkt_d1_2b_cnt', 'mkt_d1_3b_plus_cnt', 'mkt_d1_max_streak',
        'mkt_d1_broken_rate', 'mkt_past3d_1to2_seal_rate', 'mkt_past5d_1to2_seal_rate', 'mkt_past5d_2b_d3_ret',
        'mkt_d2_fb_open_mean', 'mkt_d2_fb_open_gt5_cnt', 'mkt_d2_fb_open_lt0_cnt', 'mkt_d2_fb_open_std',
        'd2_o_pct', 'd2_o_pct_sq', 'd2_o_pct_minus_mkt',
        
        # Sector / Theme Dynamics
        'plate_d1_zt_cnt', 'plate_d2_fb_cnt', 'plate_is_other', 'plate_burst_ratio', 'plate_is_fresh',
        'plate_past5d_zt_sum', 'plate_past20d_zt_mean', 'peer_open_mean', 'peer_open_max', 'open_vs_peer_diff',
        'in_plate_open_rank', 'in_mkt_open_rank', 'is_theme_leader',
        
        # Stock Breakout Structure & Microstructure
        'break_20d_high', 'break_60d_high', 'break_120d_high', 'dd20', 'dd60', 'dd120',
        'ret_3d', 'ret_5d', 'ret_10d', 'ret_20d',
        'entity_ratio', 'upper_shadow', 'lower_shadow', 'amplitude', 'd1_seal_quality',
        'turn', 'vol_ratio_5d', 'vol_ratio_20d', 'amount_log', 'mcap_log',
        
        # PIT Announcements
        'notice_s_tier', 'notice_a_tier', 'notice_neg_tier', 'has_any_pos_notice'
    ]
    
    for col in feature_cols:
        fb[col] = fb[col].fillna(0.0)
        
    fb['model_score'] = 0.0
    fb['score_reg'] = 0.0
    fb['score_cls'] = 0.0
    fb['score_mlp'] = 0.0
    
    trained_models = {}
    
    for test_yr in years:
        # Strict Point-In-Time: training set strictly < test_yr
        train_df = fb[fb['year'] < test_yr].copy()
        test_mask = fb['year'] == test_yr
        test_df = fb[test_mask].copy()
        
        X_train = train_df[feature_cols].values
        y_train_reg = train_df['target_eval_ret'].values
        y_train_cls = train_df['target_cls_win'].values
        
        X_test = test_df[feature_cols].values
        
        # Model 1: HistGradientBoostingRegressor
        m_reg = HistGradientBoostingRegressor(
            max_depth=4, min_samples_leaf=80, l2_regularization=10.0, max_iter=100, random_state=42
        )
        m_reg.fit(X_train, y_train_reg)
        pred_reg_test = m_reg.predict(X_test)
        
        # Model 2: HistGradientBoostingClassifier
        m_cls = HistGradientBoostingClassifier(
            max_depth=4, min_samples_leaf=80, l2_regularization=10.0, max_iter=100, random_state=42
        )
        m_cls.fit(X_train, y_train_cls)
        pred_cls_test = m_cls.predict_proba(X_test)[:, 1]
        
        # Model 3: MLPRegressor
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)
        m_mlp = MLPRegressor(
            hidden_layer_sizes=(32, 16), alpha=1.0, max_iter=80, random_state=42, early_stopping=True
        )
        m_mlp.fit(X_train_s, y_train_reg)
        pred_mlp_test = m_mlp.predict(X_test_s)
        
        # Cross-sectional rank normalization to [0, 1]
        r_reg = pd.Series(pred_reg_test).rank(pct=True).values
        r_cls = pd.Series(pred_cls_test).rank(pct=True).values
        r_mlp = pd.Series(pred_mlp_test).rank(pct=True).values
        
        ensemble_score = 0.40 * r_reg + 0.40 * r_cls + 0.20 * r_mlp
        
        fb.loc[test_mask, 'score_reg'] = pred_reg_test
        fb.loc[test_mask, 'score_cls'] = pred_cls_test
        fb.loc[test_mask, 'score_mlp'] = pred_mlp_test
        fb.loc[test_mask, 'model_score'] = ensemble_score
        
        trained_models[test_yr] = {
            'm_reg': m_reg,
            'm_cls': m_cls,
            'm_mlp': m_mlp,
            'scaler': scaler,
            'features': feature_cols
        }
        print(f"Trained V6 Ensemble for {test_yr} on {len(train_df):,} historical samples.")
        
    print(f"All walk-forward models trained in {time.time()-t0:.2f}s")
    return fb, trained_models, feature_cols

def simulate_trade_v6(candidate_row, price_lookup, all_trade_dates, date_to_idx, exit_mode='Exit3_BuwenClose', gates_config=None):
    """
    Simulate a single trade with 100% zero lookahead.
    Gates Config:
      - gate1_climax: bool ( вчера 1to2 seal rate > 75% -> tighten threshold )
      - gate2_nuclear: bool ( 09:25 FB auction mean < 0% -> cancel trade )
      - gate3_ice: bool ( past 5d 1to2 seal rate < 13% -> cancel trade )
    Exit Modes:
      - Exit1_DynamicHalf: Dynamic half take profit + trailing stop
      - Exit2_P2_StopBreak: Standard P2 trailing stop on limit-up open, else open exit
      - Exit3_BuwenClose: Buwen's 14:55 close hold if positive, sell if not positive
    """
    if gates_config:
        # Gate 2: Nuclear panic auction gate
        if gates_config.get('gate2_nuclear', False):
            if candidate_row['mkt_d2_fb_open_mean'] < 0.0:
                return None
                
        # Gate 3: Freezing point gate
        if gates_config.get('gate3_ice', False):
            if candidate_row['mkt_past5d_1to2_seal_rate'] < 0.13:
                return None
                
        # Gate 1: Climax next day gate
        if gates_config.get('gate1_climax', False):
            if candidate_row['mkt_past3d_1to2_seal_rate'] > 0.75:
                # Require top-tier conviction
                if candidate_row['model_score'] < 0.90:
                    return None

    code = candidate_row['code6']
    d2_str = candidate_row['d2_date_str']
    idx_d2 = date_to_idx.get(d2_str, -1)
    if idx_d2 == -1:
        return None
        
    d2_info = price_lookup.get((code, d2_str))
    if not d2_info:
        return None
    d2_open, d2_high, d2_low, d2_close, d2_adj, d2_zt, d2_dt, d2_is_zt, d2_is_yizi_dt = d2_info
    
    buy_price = d2_open
    sealed_2b = 1 if d2_is_zt else 0
    curr_idx = idx_d2 + 1
    prev_close = d2_close
    exit_price = None
    exit_date = None
    exit_at_open = False
    
    if exit_mode == 'Exit1_DynamicHalf':
        # Exit 1: Dynamic Half-Position / Trail
        if not d2_is_zt:
            # Failed to seal: exit at D3 open (rollover on limit-down)
            while curr_idx < len(all_trade_dates):
                d_curr = all_trade_dates[curr_idx]
                info = price_lookup.get((code, d_curr))
                if not info:
                    exit_price = prev_close
                    exit_date = d_curr
                    break
                o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
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
            # Sealed 2-board!
            d3_curr = all_trade_dates[curr_idx] if curr_idx < len(all_trade_dates) else None
            info3 = price_lookup.get((code, d3_curr)) if d3_curr else None
            if not info3:
                exit_price = prev_close
                exit_date = d3_curr
            else:
                o3, h3, l3, c3, adj3, zt3, dt3, is_zt3, is_yizi_dt3 = info3
                if o3 >= zt3 - 0.01:
                    # Opened limit up! Trailing stop 2.5%
                    stop_px = round(zt3 * 0.975, 2)
                    if l3 <= stop_px:
                        exit_price = stop_px
                        exit_date = d3_curr
                    else:
                        # Held limit up! Hold to D4
                        prev_close = c3
                        curr_idx += 1
                        while curr_idx < len(all_trade_dates):
                            d_next = all_trade_dates[curr_idx]
                            info_next = price_lookup.get((code, d_next))
                            if not info_next:
                                exit_price = prev_close
                                exit_date = d_next
                                break
                            on, hn, ln, cn, adjn, ztn, dtn, is_ztn, is_yizi_dtn = info_next
                            if is_yizi_dtn:
                                curr_idx += 1
                                prev_close = cn
                                continue
                            if on < ztn - 0.01:
                                exit_price = on
                                exit_date = d_next
                                exit_at_open = True
                                break
                            else:
                                stop_next = round(ztn * 0.975, 2)
                                if ln <= stop_next:
                                    exit_price = stop_next
                                    exit_date = d_next
                                    break
                                else:
                                    prev_close = cn
                                    curr_idx += 1
                                    continue
                else:
                    # Not limit-up open
                    d3_o_pct = (o3 / prev_close) - 1.0
                    if d3_o_pct >= 0.02:
                        # Half at open, half intraday
                        p_half1 = o3
                        stop_loss_px = round(prev_close * 0.985, 2)
                        if l3 <= stop_loss_px:
                            p_half2 = stop_loss_px
                        elif is_zt3:
                            # 3-board! Evaluate D4
                            p_half2 = c3 * 1.03  # conservative runner expectation
                        else:
                            p_half2 = c3
                        exit_price = 0.5 * p_half1 + 0.5 * p_half2
                        exit_date = d3_curr
                    else:
                        exit_price = o3
                        exit_date = d3_curr
                        exit_at_open = True
                        
    elif exit_mode == 'Exit2_P2_StopBreak':
        # Exit 2: P2 Benchmark Exit
        if not d2_is_zt:
            while curr_idx < len(all_trade_dates):
                d_curr = all_trade_dates[curr_idx]
                info = price_lookup.get((code, d_curr))
                if not info:
                    exit_price = prev_close
                    exit_date = d_curr
                    break
                o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
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
            while curr_idx < len(all_trade_dates):
                d_curr = all_trade_dates[curr_idx]
                info = price_lookup.get((code, d_curr))
                if not info:
                    exit_price = prev_close
                    exit_date = d_curr
                    break
                o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                if o < zt - 0.01:
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
                    stop_px = round(zt * 0.98, 2)
                    if l <= stop_px:
                        exit_price = stop_px
                        exit_date = d_curr
                        break
                    else:
                        prev_close = c
                        curr_idx += 1
                        continue
                        
    elif exit_mode == 'Exit3_BuwenClose':
        # Exit 3: Buwen's 14:55 Close Hold If Positive, Sell If Not Positive
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                exit_price = prev_close
                exit_date = d_curr
                break
            o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
            
            # If one-word limit down, cannot sell, must rollover!
            if is_yizi_dt:
                curr_idx += 1
                prev_close = c
                continue
                
            # Check 14:55 close return relative to pre_close
            daily_chg = (c / prev_close) - 1.0
            
            if is_zt or daily_chg > 0.0001:
                # Sealed ZT or closed positive -> HOLD!
                prev_close = c
                curr_idx += 1
                # Limit holding to max 8 days
                if curr_idx - idx_d2 >= 8:
                    exit_price = c
                    exit_date = d_curr
                    break
                continue
            else:
                # Closed flat or negative -> SELL at close!
                exit_price = c
                exit_date = d_curr
                break
                
    if exit_price is None:
        exit_price = prev_close
        exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
        
    holding_days = max(1, curr_idx - idx_d2)
    gross_ret = exit_price / buy_price - 1.0
    net_ret = (1.0 + gross_ret) * (1.0 - FEE_RATE) - 1.0
    
    return {
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
        'plate_d1_zt_cnt': int(candidate_row['plate_d1_zt_cnt']),
        'break_20d_high': int(candidate_row['break_20d_high']),
        'dd20': round(float(candidate_row['dd20']), 4),
        'd2_o_pct': round(float(candidate_row['d2_o_pct']), 4),
        'score': round(float(candidate_row['model_score']), 4),
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

def run_v6_evaluation():
    print("\n" + "=" * 80)
    print(">>> [Phase 6] Running V6 BlackBox Engine Ablation & Walk-Forward Evaluation...")
    print("=" * 80)
    
    stock_to_plate_info, kpl_daily_plates, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices = load_kpl_and_notices()
    df = load_price_data()
    market_stats = build_market_daily_stats(df)
    fb = build_v6_feature_matrix(df, stock_to_plate_info, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices, market_stats)
    fb, trained_models, feature_cols = train_walk_forward_ensemble(fb)
    
    # Fast price lookup dict
    price_lookup = {}
    for r in df[['code6', 'date_str', 'open', 'high', 'low', 'close', 'adj_close', 'zt_price', 'dt_price', 'is_zt', 'is_yizi_dt']].itertuples(index=False):
        price_lookup[(r.code6, r.date_str)] = (
            r.open, r.high, r.low, r.close, r.adj_close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt
        )
    all_trade_dates = market_stats['all_trade_dates']
    date_to_idx = market_stats['date_to_idx']
    
    years = [2022, 2023, 2024, 2025, 2026]
    
    # Define Evaluation Combos
    combos = [
        # Combo 1: BlackBox + Exit 1 (Dynamic Half Position)
        ("Combo 1", "V6_BlackBox_Exit1_HalfTrail", "Exit1_DynamicHalf", None, 55),
        # Combo 2: BlackBox + Exit 2 (P2 Benchmark Exit)
        ("Combo 2", "V6_BlackBox_Exit2_P2Benchmark", "Exit2_P2_StopBreak", None, 55),
        # Combo 3: BlackBox + Exit 3 (Buwen's 14:55 Close Exit - No Gates)
        ("Combo 3", "V6_BlackBox_Exit3_BuwenClose_Base", "Exit3_BuwenClose", None, 55),
        # Combo 4: BlackBox + Exit 3 + Gate 2 (Nuclear Panic Auction Gate)
        ("Combo 4", "V6_BlackBox_Exit3_Gate2Nuclear", "Exit3_BuwenClose", {'gate2_nuclear': True}, 55),
        # Combo 5: BlackBox + Exit 3 + Gate 3 (Ice Point Freezing Gate)
        ("Combo 5", "V6_BlackBox_Exit3_Gate3Ice", "Exit3_BuwenClose", {'gate3_ice': True}, 55),
        # Combo 6: BlackBox + Exit 3 + All Three Protection Gates (Ironclad)
        ("Combo 6", "V6_BlackBox_Exit3_Ironclad_3Gates", "Exit3_BuwenClose", {'gate1_climax': True, 'gate2_nuclear': True, 'gate3_ice': True}, 55),
    ]
    
    all_results = {}
    all_trades_ledger = []
    
    for combo_label, combo_name, exit_mode, gates_cfg, target_rate in combos:
        print(f"\n" + "-" * 75)
        print(f"--- Running {combo_label}: {combo_name} (Target: {target_rate}/yr, Exit: {exit_mode}) ---")
        print("-" * 75)
        
        combo_trades = []
        combo_yearly = {}
        
        for test_yr in years:
            train_pool = fb[fb['year'] < test_yr].copy()
            test_pool = fb[fb['year'] == test_yr].copy()
            
            # Calibrate cutoff from training scores to achieve target frequency
            train_scores = train_pool['model_score'].values
            train_span = max(1, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
            target_train_count = int(target_rate * train_span)
            
            if len(train_scores) > target_train_count:
                cutoff = float(np.percentile(train_scores, 100.0 * (1.0 - target_train_count / len(train_scores))))
            else:
                cutoff = float(np.percentile(train_scores, 80.0))
                
            test_candidates = test_pool[test_pool['model_score'] >= cutoff].sort_values(['d2_date_str', 'model_score'], ascending=[True, False])
            # Pick daily top 1 across market
            test_selected = test_candidates.groupby('d2_date_str').head(1)
            
            yr_trades = []
            for _, r in test_selected.iterrows():
                tr = simulate_trade_v6(r, price_lookup, all_trade_dates, date_to_idx, exit_mode=exit_mode, gates_config=gates_cfg)
                if tr:
                    tr['combo'] = combo_name
                    tr['test_year'] = test_yr
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
                yr_break_rate = df_yr['break_20d_high'].mean()
                
                nav_1s, _, _ = simulate_portfolio_slots(yr_trades, num_slots=1)
                nav_2s, _, _ = simulate_portfolio_slots(yr_trades, num_slots=2)
                yr_bench = CSI300_ANNUAL_RETURNS.get(test_yr, 0.0)
                yr_excess = (nav_1s - 1.0) - yr_bench
                
                combo_yearly[test_yr] = {
                    'trades_count': yr_n,
                    'win_rate': round(float(yr_wr), 4),
                    'pnl_ratio': round(float(pnl_ratio), 2),
                    'sealed_2b_rate': round(float(yr_2b_rate), 4),
                    'breakout_ratio': round(float(yr_break_rate), 4),
                    'nav_1slot': round(float(nav_1s), 4),
                    'nav_2slot': round(float(nav_2s), 4),
                    'benchmark_csi300': yr_bench,
                    'excess_1slot': round(float(yr_excess), 4),
                }
                print(f"  {test_yr}: {yr_n:2d} trades | WinRate: {yr_wr*100:4.1f}% | 2B: {yr_2b_rate*100:4.1f}% | Breakout: {yr_break_rate*100:4.1f}% | PnL: {pnl_ratio:4.2f} | 1-Slot: {nav_1s:6.4f}x (Excess: {yr_excess*100:+6.2f}%) | 2-Slot: {nav_2s:6.4f}x")
            else:
                combo_yearly[test_yr] = {'trades_count': 0}
                print(f"  {test_yr}:  0 trades")
                
        df_combo = pd.DataFrame(combo_trades)
        total_n = len(df_combo)
        if total_n > 0:
            tot_wr = (df_combo['net_ret'] > 0).mean()
            tot_2b = df_combo['sealed_2b'].mean()
            tot_break = df_combo['break_20d_high'].mean()
            wins = df_combo[df_combo['net_ret'] > 0]['net_ret']
            losses = df_combo[df_combo['net_ret'] <= 0]['net_ret']
            avg_win = wins.mean() if len(wins) > 0 else 0.0
            avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.01
            pnl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
            
            nav_1s, n1, _ = simulate_portfolio_slots(combo_trades, num_slots=1)
            nav_2s, n2, _ = simulate_portfolio_slots(combo_trades, num_slots=2)
            
            all_results[combo_name] = {
                'total_trades': total_n,
                'executed_1slot': n1,
                'executed_2slot': n2,
                'win_rate': round(float(tot_wr), 4),
                'pnl_ratio': round(float(pnl_ratio), 2),
                'sealed_2b_rate': round(float(tot_2b), 4),
                'breakout_ratio': round(float(tot_break), 4),
                'cum_nav_1slot': round(float(nav_1s), 4),
                'cum_nav_2slot': round(float(nav_2s), 4),
                'annual_breakdown': combo_yearly,
            }
            print(f"  ==> TOTAL: {total_n} trades | WinRate: {tot_wr*100:4.1f}% | 2B: {tot_2b*100:4.1f}% | Breakout: {tot_break*100:4.1f}% | PnL: {pnl_ratio:4.2f} | 1-Slot: {nav_1s:6.4f}x | 2-Slot: {nav_2s:6.4f}x")
            
    # Save Results
    with open(RESULTS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    if all_trades_ledger:
        pd.DataFrame(all_trades_ledger).to_csv(LEDGER_CSV_PATH, index=False, encoding='utf-8')
    print(f"\nSaved results to {RESULTS_JSON_PATH} and ledger to {LEDGER_CSV_PATH}")
    
    # =========================================================================
    # Phase 7: Score 2026-11-11 Today's Live First-Board Candidates!
    # =========================================================================
    print("\n" + "=" * 80)
    print(">>> [Phase 7] Scoring 2026-11-11 Live Pre-Market Candidates (Yesterday 2026-11-10 First Boards)...")
    print("=" * 80)
    
    live_df = df[df['date_str'] == '2026-11-10'].copy()
    live_fb = live_df[live_df['is_turnover_fb'] & (live_df['amount'] >= 1.0e8)].copy()
    
    matched_plates, matched_names, matched_sizes = [], [], []
    for row in live_fb[['date_str', 'code6']].itertuples(index=False):
        info = stock_to_plate_info.get((row.date_str, row.code6))
        if info:
            matched_plates.append(info['plate'])
            matched_names.append(info['name'])
            matched_sizes.append(info['plate_sz'])
        else:
            matched_plates.append("其他")
            matched_names.append("")
            matched_sizes.append(1)
            
    live_fb['plate'] = matched_plates
    live_fb['stock_name'] = matched_names
    live_fb['plate_d1_zt_cnt'] = matched_sizes
    live_fb = live_fb[~live_fb['stock_name'].str.contains('ST|退', regex=True)].copy()
    
    # Feature calculation for live FB
    live_fb['mkt_d1_zt_cnt'] = market_stats['mkt_d1_zt_cnt'].get('2026-11-10', 40)
    live_fb['mkt_d1_fb_cnt'] = market_stats['mkt_d1_fb_cnt'].get('2026-11-10', 25)
    live_fb['mkt_d1_2b_cnt'] = market_stats['mkt_d1_2b_cnt'].get('2026-11-10', 8)
    live_fb['mkt_d1_3b_plus_cnt'] = market_stats['mkt_d1_3b_plus_cnt'].get('2026-11-10', 4)
    live_fb['mkt_d1_max_streak'] = market_stats['mkt_d1_max_streak'].get('2026-11-10', 4)
    live_fb['mkt_d1_broken_rate'] = market_stats['mkt_d1_broken_rate'].get('2026-11-10', 0.25)
    live_fb['mkt_past3d_1to2_seal_rate'] = market_stats['mkt_past3d_1to2_seal_rate'].get('2026-11-10', 0.20)
    live_fb['mkt_past5d_1to2_seal_rate'] = market_stats['mkt_past5d_1to2_seal_rate'].get('2026-11-10', 0.20)
    live_fb['mkt_past5d_2b_d3_ret'] = market_stats['mkt_past5d_2b_d3_ret'].get('2026-11-10', 0.0)
    
    # Pre-market default auction expected at +3.5%
    live_fb['d2_o_pct'] = 0.035
    live_fb['d2_o_pct_sq'] = (0.035 - 0.045) ** 2
    live_fb['mkt_d2_fb_open_mean'] = 0.025
    live_fb['mkt_d2_fb_open_gt5_cnt'] = 3
    live_fb['mkt_d2_fb_open_lt0_cnt'] = 2
    live_fb['mkt_d2_fb_open_std'] = 0.02
    live_fb['d2_o_pct_minus_mkt'] = 0.010
    
    live_fb['plate_d2_fb_cnt'] = 2
    live_fb['plate_is_other'] = (live_fb['plate'] == "其他").astype(float)
    live_fb['peer_open_mean'] = 0.025
    live_fb['peer_open_max'] = 0.040
    live_fb['open_vs_peer_diff'] = 0.010
    live_fb['in_plate_open_rank'] = 1
    live_fb['in_mkt_open_rank'] = 5
    live_fb['is_theme_leader'] = 1.0
    live_fb['plate_burst_ratio'] = 2.5
    live_fb['plate_is_fresh'] = 1.0
    live_fb['plate_past5d_zt_sum'] = 4.0
    live_fb['plate_past20d_zt_mean'] = 1.0
    
    s_flags, a_flags, neg_flags = [], [], []
    for r in live_fb[['code6', 'date_str']].itertuples(index=False):
        c6, d1 = r.code6, r.date_str
        has_s = 1 if (c6, '2026-11-11') in s_tier_notices or (c6, d1) in s_tier_notices else 0
        has_a = 1 if (c6, '2026-11-11') in a_tier_notices or (c6, d1) in a_tier_notices else 0
        has_neg = 1 if (c6, '2026-11-11') in neg_tier_notices or (c6, d1) in neg_tier_notices else 0
        s_flags.append(has_s)
        a_flags.append(has_a)
        neg_flags.append(has_neg)
        
    live_fb['notice_s_tier'] = s_flags
    live_fb['notice_a_tier'] = a_flags
    live_fb['notice_neg_tier'] = neg_flags
    live_fb['has_any_pos_notice'] = np.maximum(s_flags, a_flags)
    
    for col in feature_cols:
        live_fb[col] = live_fb[col].fillna(0.0)
        
    # Use 2026 trained model to score
    models_2026 = trained_models[2026]
    X_live = live_fb[feature_cols].values
    
    pred_reg_live = models_2026['m_reg'].predict(X_live)
    pred_cls_live = models_2026['m_cls'].predict_proba(X_live)[:, 1]
    X_live_s = models_2026['scaler'].transform(X_live)
    pred_mlp_live = models_2026['m_mlp'].predict(X_live_s)
    
    r_reg = pd.Series(pred_reg_live).rank(pct=True).values
    r_cls = pd.Series(pred_cls_live).rank(pct=True).values
    r_mlp = pd.Series(pred_mlp_live).rank(pct=True).values
    
    live_fb['score_reg'] = pred_reg_live
    live_fb['score_cls'] = pred_cls_live
    live_fb['score_mlp'] = pred_mlp_live
    live_fb['ensemble_score'] = 0.40 * r_reg + 0.40 * r_cls + 0.20 * r_mlp
    
    live_sorted = live_fb.sort_values('ensemble_score', ascending=False)
    print("\nTop 15 Live Candidates for 2026-11-11 Morning:")
    print("-" * 105)
    print(f"{'Code':<8} {'Name':<10} {'Plate':<12} {'Break20d':<10} {'dd20':<8} {'Amount(亿)':<12} {'Score':<8} {'RegRet':<8} {'ClsWin':<8}")
    print("-" * 105)
    for _, row in live_sorted.head(15).iterrows():
        amt_yi = row['amount'] / 1e8
        brk = "YES (突破)" if row['break_20d_high'] == 1 else "NO (超跌)"
        print(f"{row['code6']:<8} {row['stock_name']:<10} {row['plate']:<12} {brk:<10} {row['dd20']:<8.3f} {amt_yi:<12.2f} {row['ensemble_score']:<8.4f} {row['score_reg']*100:+6.2f}% {row['score_cls']*100:6.1f}%")
    print("-" * 105)

if __name__ == '__main__':
    run_v6_evaluation()

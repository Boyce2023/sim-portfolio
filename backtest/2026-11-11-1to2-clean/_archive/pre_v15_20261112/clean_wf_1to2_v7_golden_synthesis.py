#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v7_golden_synthesis.py
=============================================================================
One-to-Two V7 Golden Domain & BlackBox Synthesis Engine
(2021 Train -> 2022-2026 Walk-Forward)
Strictly Compliant with A-Share T+1 Settlement & 100% Zero-Lookahead / Point-In-Time
=============================================================================
Synthesizes the 12-factor ablation results with V6 BlackBox Engine:
- Edict: Eradicate the 3 Plagues (dd20<=0.92, mcap>=15B lower bound, amount>=1.5B)
- Retain the 5 Golden Rules:
  1. Main board 00/60, non-ST, D2 open < zt_price - 0.01 (non-yizi)
  2. Auction Golden Window: 0.015 <= d2_o_pct <= 0.075
  3. Real Theme Ladder: plate != '其他' & plate_d2_cnt >= 2 & peer_open_mean >= -0.01
  4. Defenses: notice_neg_tier == 0, ret5d <= 0.28, mcap_circ <= 200, amount >= 0.3e8
  5. Market Sentiment Gates: Gate 2 (d2_auc_mean >= 0) & Gate 3 (past5d_seal_rate >= 0.13)
- Models trained & evaluated STRICTLY within is_golden_domain.
- Regularized Heterogeneous Ensemble: HistGBRegressor + HistGBClassifier + Domain Ridge(alpha=15).
- Exits Evaluated:
  * Exit A: Buwen 14:55 Close Hold If Positive, Sell If Negative (intraday -6% floor)
  * Exit B: Half D3 Open Lock + Half Buwen 14:55 Close Ride
  * Exit C: Touch ZT Buy on High Open Divergence + Exit A
- Full 5-Year Walk-Forward, Perturbation Test, and 2026-11-11 Live Candidates.
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
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
NOTICES_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"

LEDGER_CSV_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v7_golden_synthesis_ledger.csv")
RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v7_golden_synthesis_results.json")

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
    
    # Structure & volume features
    df['mcap_circ'] = df['close'] * df['oshare'] / 1e8
    df['vol_ma5'] = df.groupby('code6')['volume'].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    df['vol_ma20'] = df.groupby('code6')['volume'].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    
    # Breakout levels
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
    df['ret5d'] = df['pre_close'] / (df['close_5d_ago'] + 1e-4) - 1.0
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
    print(">>> [Phase 3] Computing Daily Market Sentiment, Climax, and Natural 1to2 Stats...")
    t0 = time.time()
    daily_groups = df.groupby('date_str')
    
    mkt_d1_zt_cnt = daily_groups['is_zt'].sum().to_dict()
    mkt_d1_touched_zt_cnt = daily_groups['touched_zt'].sum().to_dict()
    mkt_d1_fb_cnt = daily_groups['is_turnover_fb'].sum().to_dict()
    mkt_d1_2b_cnt = (daily_groups['streak'].apply(lambda s: (s == 2).sum())).to_dict()
    mkt_d1_3b_plus_cnt = (daily_groups['streak'].apply(lambda s: (s >= 3).sum())).to_dict()
    mkt_d1_max_streak = daily_groups['streak'].max().to_dict()
    
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    mkt_d1_broken_rate = {}
    for d in all_trade_dates:
        t_cnt = mkt_d1_touched_zt_cnt.get(d, 0)
        z_cnt = mkt_d1_zt_cnt.get(d, 0)
        mkt_d1_broken_rate[d] = float((t_cnt - z_cnt) / max(1, t_cnt)) if t_cnt > 0 else 0.0
        
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

def build_v7_feature_matrix(df, stock_to_plate_info, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices, market_stats):
    print(">>> [Phase 4] Building V7 Feature Matrix & Golden Domain Flag...")
    t0 = time.time()
    
    fb_all = df[df['is_turnover_fb'] & df['d2_date_str'].notna()].copy()
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
    fb_all['plate_d1_zt_cnt'] = matched_sizes
    
    # Exclude ST / 退市
    fb = fb_all[~fb_all['stock_name'].str.contains('ST|退', regex=True)].copy()
    
    # Market sentiment stats
    fb['mkt_d1_zt_cnt'] = [market_stats['mkt_d1_zt_cnt'].get(d, 40) for d in fb['date_str']]
    fb['mkt_d1_fb_cnt'] = [market_stats['mkt_d1_fb_cnt'].get(d, 25) for d in fb['date_str']]
    fb['mkt_d1_2b_cnt'] = [market_stats['mkt_d1_2b_cnt'].get(d, 8) for d in fb['date_str']]
    fb['mkt_d1_3b_plus_cnt'] = [market_stats['mkt_d1_3b_plus_cnt'].get(d, 4) for d in fb['date_str']]
    fb['mkt_d1_max_streak'] = [market_stats['mkt_d1_max_streak'].get(d, 4) for d in fb['date_str']]
    fb['mkt_d1_broken_rate'] = [market_stats['mkt_d1_broken_rate'].get(d, 0.25) for d in fb['date_str']]
    fb['mkt_past3d_1to2_seal_rate'] = [market_stats['mkt_past3d_1to2_seal_rate'].get(d, 0.20) for d in fb['date_str']]
    fb['mkt_past5d_1to2_seal_rate'] = [market_stats['mkt_past5d_1to2_seal_rate'].get(d, 0.20) for d in fb['date_str']]
    fb['mkt_past5d_2b_d3_ret'] = [market_stats['mkt_past5d_2b_d3_ret'].get(d, 0.0) for d in fb['date_str']]
    
    # D2 Auction stats
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
    
    # Sector & peer dynamics
    plate_d2_groups = fb.groupby(['d2_date_str', 'plate'])['d2_o_pct']
    plate_d2_sum = plate_d2_groups.transform('sum')
    plate_d2_cnt = plate_d2_groups.transform('count')
    plate_d2_max = plate_d2_groups.transform('max')
    
    fb['plate_d2_fb_cnt'] = plate_d2_cnt
    fb['plate_is_other'] = (fb['plate'] == "其他").astype(float)
    
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
    fb['in_plate_open_rank'] = fb.groupby(['d2_date_str', 'plate'])['d2_o_pct'].rank(ascending=False, method='min')
    fb['in_mkt_open_rank'] = fb.groupby('d2_date_str')['d2_o_pct'].rank(ascending=False, method='min')
    fb['is_theme_leader'] = ((fb['plate'] != "其他") & (plate_d2_cnt >= 2) & (fb['in_plate_open_rank'] == 1)).astype(float)
    
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
    
    # =========================================================================
    # Five Golden Rules (is_golden_domain) Definition:
    # 1. Non-yizi open: d2_open < d2_zt_price - 0.005
    # 2. Golden auction window: 0.015 <= d2_o_pct <= 0.075
    # 3. Sector ladder synergy: plate != '其他' & plate_d2_cnt >= 2 & peer_open_mean >= -0.01
    # 4. Sound structure & defenses: notice_neg_tier == 0, ret5d <= 0.28, mcap_circ <= 200.0, amount >= 0.3e8
    # 5. Market sentiment gates: mkt_d2_fb_open_mean >= 0.0 & mkt_past5d_1to2_seal_rate >= 0.13
    # =========================================================================
    fb['is_golden_domain'] = (
        (fb['d2_open'] < fb['d2_zt_price'] - 0.005) &
        (fb['d2_o_pct'] >= 0.015) & (fb['d2_o_pct'] <= 0.075) &
        (fb['plate'] != "其他") & (fb['plate_d2_fb_cnt'] >= 2) & (fb['peer_open_mean'] >= -0.01) &
        (fb['notice_neg_tier'] == 0) & (fb['ret5d'] <= 0.28) & (fb['mcap_circ'] <= 200.0) & (fb['amount'] >= 0.3e8) &
        (fb['mkt_d2_fb_open_mean'] >= 0.0) & (fb['mkt_past5d_1to2_seal_rate'] >= 0.13)
    ).astype(bool)
    
    # Target definition
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
    
    n_golden = fb['is_golden_domain'].sum()
    print(f"Total clean candidates: {len(fb):,}, in Golden Domain: {n_golden:,} ({n_golden/len(fb)*100:.1f}%) in {time.time()-t0:.2f}s")
    return fb

def train_golden_domain_ensemble(fb):
    print("\n" + "=" * 80)
    print(">>> [Phase 5] Training Regularized Ensemble STRICTLY within Golden Domain...")
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
        'plate_d1_zt_cnt', 'plate_d2_fb_cnt', 'plate_burst_ratio', 'plate_is_fresh',
        'plate_past5d_zt_sum', 'plate_past20d_zt_mean', 'peer_open_mean', 'peer_open_max', 'open_vs_peer_diff',
        'in_plate_open_rank', 'in_mkt_open_rank', 'is_theme_leader',
        
        # Stock Breakout Structure & Microstructure
        'break_20d_high', 'break_60d_high', 'break_120d_high', 'dd20', 'dd60', 'dd120',
        'ret_3d', 'ret5d', 'ret_10d', 'ret_20d',
        'entity_ratio', 'upper_shadow', 'lower_shadow', 'amplitude', 'd1_seal_quality',
        'turn', 'vol_ratio_5d', 'vol_ratio_20d', 'amount_log', 'mcap_log',
        
        # PIT Announcements
        'notice_s_tier', 'notice_a_tier', 'has_any_pos_notice'
    ]
    
    for col in feature_cols:
        fb[col] = fb[col].fillna(0.0)
        
    fb['model_score'] = 0.0
    trained_models = {}
    
    for test_yr in years:
        # STRICTLY TRAIN ON HISTORICAL SAMPLES IN GOLDEN DOMAIN!
        train_df = fb[(fb['year'] < test_yr) & (fb['is_golden_domain'])].copy()
        test_mask = (fb['year'] == test_yr) & (fb['is_golden_domain'])
        test_df = fb[test_mask].copy()
        
        if len(test_df) == 0:
            continue
            
        X_train = train_df[feature_cols].values
        y_train_reg = train_df['target_eval_ret'].values
        y_train_cls = train_df['target_cls_win'].values
        
        X_test = test_df[feature_cols].values
        
        # Model 1: Shallow Regularized HistGBRegressor
        m_reg = HistGradientBoostingRegressor(
            max_depth=4, min_samples_leaf=30, l2_regularization=10.0, max_iter=80, random_state=42
        )
        m_reg.fit(X_train, y_train_reg)
        pred_reg_test = m_reg.predict(X_test)
        
        # Model 2: Shallow Regularized HistGBClassifier
        m_cls = HistGradientBoostingClassifier(
            max_depth=4, min_samples_leaf=30, l2_regularization=10.0, max_iter=80, random_state=42
        )
        m_cls.fit(X_train, y_train_cls)
        pred_cls_test = m_cls.predict_proba(X_test)[:, 1]
        
        # Model 3: Domain Ridge(alpha=15.0)
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)
        m_ridge = Ridge(alpha=15.0)
        m_ridge.fit(X_train_s, y_train_reg)
        pred_ridge_test = m_ridge.predict(X_test_s)
        
        # Rank-based ensemble
        r_reg = pd.Series(pred_reg_test).rank(pct=True).values
        r_cls = pd.Series(pred_cls_test).rank(pct=True).values
        r_ridge = pd.Series(pred_ridge_test).rank(pct=True).values
        
        ensemble_score = 0.40 * r_reg + 0.40 * r_cls + 0.20 * r_ridge
        fb.loc[test_mask, 'model_score'] = ensemble_score
        
        trained_models[test_yr] = {
            'm_reg': m_reg,
            'm_cls': m_cls,
            'm_ridge': m_ridge,
            'scaler': scaler,
            'features': feature_cols
        }
        print(f"Trained Golden Domain Models for {test_yr} on {len(train_df):,} golden historical samples.")
        
    print(f"Ensemble trained in {time.time()-t0:.2f}s")
    return fb, trained_models, feature_cols

def simulate_trade_v7(candidate_row, price_lookup, all_trade_dates, date_to_idx, exit_mode='Exit_A_BuwenClose'):
    """
    Simulate trade with 100% zero lookahead.
    Exit Modes:
      - Exit_A_BuwenClose:
        * D2 failed to seal: exit at D3 open (rollover on limit down)
        * D2 sealed: from D3 onwards, each day at 14:55:
          - Intraday floor: if low <= pre_close * 0.94 -> stop loss at pre_close * 0.94
          - Close judgment: if is_zt or close > pre_close -> HOLD!
                            if close <= pre_close -> SELL at close!
      - Exit_B_HalfLock_HalfBuwen:
        * D2 failed: exit D3 open
        * D2 sealed: 50% exit D3 open; 50% follow Exit A.
      - Exit_C_TouchBuy_ExitA:
        * Buy condition: if d2_o_pct > 0.05 and peer_open_mean < 0.02:
            buy at d2_zt_price only if touched (high >= zt). If not touched -> return None.
          else:
            buy at d2_open.
        * Exit follows Exit A.
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
    
    # Determine buy price
    if exit_mode == 'Exit_C_TouchBuy_ExitA':
        if candidate_row['d2_o_pct'] > 0.05 and candidate_row['peer_open_mean'] < 0.02:
            # Requires touch of limit up
            if d2_high < d2_zt - 0.005:
                return None  # Order not filled!
            buy_price = d2_zt
        else:
            buy_price = d2_open
    else:
        buy_price = d2_open
        
    sealed_2b = 1 if d2_is_zt else 0
    curr_idx = idx_d2 + 1
    prev_close = d2_close
    exit_price = None
    exit_date = None
    exit_at_open = False
    
    if exit_mode in ('Exit_A_BuwenClose', 'Exit_C_TouchBuy_ExitA'):
        if not d2_is_zt:
            # D2 failed to seal -> Exit at D3 09:25 open
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
            # D2 sealed limit up! Ride the monster runner!
            while curr_idx < len(all_trade_dates):
                d_curr = all_trade_dates[curr_idx]
                info = price_lookup.get((code, d_curr))
                if not info:
                    exit_price = prev_close
                    exit_date = d_curr
                    break
                o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                
                # Limit-down rollover
                if is_yizi_dt:
                    curr_idx += 1
                    prev_close = c
                    continue
                    
                # Intraday -6% stop-loss floor
                stop_floor_px = round(prev_close * 0.94, 2)
                if l <= stop_floor_px:
                    exit_price = stop_floor_px
                    exit_date = d_curr
                    break
                    
                # 14:55 Close decision: positive vs pre_close
                daily_chg = (c / prev_close) - 1.0
                if is_zt or daily_chg > 0.0001:
                    # Sealed ZT or closed positive -> HOLD!
                    prev_close = c
                    curr_idx += 1
                    if curr_idx - idx_d2 >= 8:  # 8 days max ride
                        exit_price = c
                        exit_date = d_curr
                        break
                    continue
                else:
                    # Flat or negative -> SELL at close!
                    exit_price = c
                    exit_date = d_curr
                    break
                    
    elif exit_mode == 'Exit_B_HalfLock_HalfBuwen':
        if not d2_is_zt:
            # D2 failed to seal -> Exit at D3 open
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
            # D2 sealed limit up! Half at D3 open, half rides
            d3_curr = all_trade_dates[curr_idx] if curr_idx < len(all_trade_dates) else None
            info3 = price_lookup.get((code, d3_curr)) if d3_curr else None
            if not info3:
                exit_price = prev_close
                exit_date = d3_curr
            else:
                o3, h3, l3, c3, adj3, zt3, dt3, is_zt3, is_yizi_dt3 = info3
                half1_price = o3
                
                # Half 2 follows Buwen ride
                half2_price = c3
                curr_h2_idx = curr_idx
                prev_c_h2 = prev_close
                while curr_h2_idx < len(all_trade_dates):
                    d_c = all_trade_dates[curr_h2_idx]
                    inf = price_lookup.get((code, d_c))
                    if not inf:
                        half2_price = prev_c_h2
                        break
                    oc, hc, lc, cc, adjc, ztc, dtc, is_ztc, is_yizi_dtc = inf
                    if is_yizi_dtc:
                        curr_h2_idx += 1
                        prev_c_h2 = cc
                        continue
                    stop_px = round(prev_c_h2 * 0.94, 2)
                    if lc <= stop_px:
                        half2_price = stop_px
                        break
                    chg_c = (cc / prev_c_h2) - 1.0
                    if is_ztc or chg_c > 0.0001:
                        prev_c_h2 = cc
                        curr_h2_idx += 1
                        if curr_h2_idx - idx_d2 >= 8:
                            half2_price = cc
                            break
                        continue
                    else:
                        half2_price = cc
                        break
                        
                exit_price = 0.5 * half1_price + 0.5 * half2_price
                exit_date = d3_curr
                
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
        'break_60d_high': int(candidate_row['break_60d_high']),
        'dd20': round(float(candidate_row['dd20']), 4),
        'd2_o_pct': round(float(candidate_row['d2_o_pct']), 4),
        'score': round(float(candidate_row['model_score']), 4),
    }

def simulate_portfolio_slots(trades_list, num_slots=1):
    if not trades_list:
        return 1.0, 0, 0.0, []
    sorted_trades = sorted(trades_list, key=lambda x: (x['buy_date'], -x['score']))
    slot_available = ["" for _ in range(num_slots)]
    executed_trades = []
    slot_capital = [1.0 / num_slots for _ in range(num_slots)]
    
    daily_nav_history = [1.0]
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

def run_v7_synthesis():
    print("\n" + "=" * 80)
    print(">>> [Phase 6] Running V7 Golden Domain & BlackBox Synthesis Walk-Forward...")
    print("=" * 80)
    
    stock_to_plate_info, kpl_daily_plates, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices = load_kpl_and_notices()
    df = load_price_data()
    market_stats = build_market_daily_stats(df)
    fb = build_v7_feature_matrix(df, stock_to_plate_info, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices, market_stats)
    fb, trained_models, feature_cols = train_golden_domain_ensemble(fb)
    
    price_lookup = {}
    for r in df[['code6', 'date_str', 'open', 'high', 'low', 'close', 'adj_close', 'zt_price', 'dt_price', 'is_zt', 'is_yizi_dt']].itertuples(index=False):
        price_lookup[(r.code6, r.date_str)] = (
            r.open, r.high, r.low, r.close, r.adj_close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt
        )
    all_trade_dates = market_stats['all_trade_dates']
    date_to_idx = market_stats['date_to_idx']
    
    years = [2022, 2023, 2024, 2025, 2026]
    
    combos = [
        ("Combo A", "V7_Golden_BuwenClose", "Exit_A_BuwenClose", 55, 1),
        ("Combo A2", "V7_Golden_BuwenClose_Top2DiffPlate", "Exit_A_BuwenClose", 55, 2),
        ("Combo B", "V7_Golden_HalfLock_HalfRide", "Exit_B_HalfLock_HalfBuwen", 55, 1),
        ("Combo C", "V7_Golden_TouchBuy_BuwenClose", "Exit_C_TouchBuy_ExitA", 55, 1),
    ]
    
    all_results = {}
    all_trades_ledger = []
    
    for combo_label, combo_name, exit_mode, target_rate, max_daily_picks in combos:
        print(f"\n" + "-" * 75)
        print(f"--- Running {combo_label}: {combo_name} (Target: {target_rate}/yr, MaxDaily: {max_daily_picks}) ---")
        print("-" * 75)
        
        combo_trades = []
        combo_yearly = {}
        
        for test_yr in years:
            train_pool = fb[(fb['year'] < test_yr) & (fb['is_golden_domain'])].copy()
            test_pool = fb[(fb['year'] == test_yr) & (fb['is_golden_domain'])].copy()
            
            if len(test_pool) == 0:
                continue
                
            train_scores = train_pool['model_score'].values
            train_span = max(1, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
            target_train_count = int(target_rate * train_span)
            
            if len(train_scores) > target_train_count:
                cutoff = float(np.percentile(train_scores, 100.0 * (1.0 - target_train_count / len(train_scores))))
            else:
                cutoff = float(np.percentile(train_scores, 75.0))
                
            test_cands = test_pool[test_pool['model_score'] >= cutoff].sort_values(['d2_date_str', 'model_score'], ascending=[True, False])
            
            # Select top 1 or top 2 in different plates
            selected_rows = []
            for d_str, day_df in test_cands.groupby('d2_date_str'):
                seen_plates = set()
                picked = 0
                for _, r in day_df.iterrows():
                    p = r['plate']
                    if p not in seen_plates:
                        selected_rows.append(r)
                        seen_plates.add(p)
                        picked += 1
                        if picked >= max_daily_picks:
                            break
                            
            yr_trades = []
            for r in selected_rows:
                tr = simulate_trade_v7(r, price_lookup, all_trade_dates, date_to_idx, exit_mode=exit_mode)
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
                
                nav_1s, _, mdd1, _ = simulate_portfolio_slots(yr_trades, num_slots=1)
                nav_2s, _, mdd2, _ = simulate_portfolio_slots(yr_trades, num_slots=2)
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
                    'mdd_1slot': round(float(mdd1), 4),
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
            
            nav_1s, n1, mdd1, _ = simulate_portfolio_slots(combo_trades, num_slots=1)
            nav_2s, n2, mdd2, _ = simulate_portfolio_slots(combo_trades, num_slots=2)
            
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
                'max_drawdown_1slot': round(float(mdd1), 4),
                'max_drawdown_2slot': round(float(mdd2), 4),
                'annual_breakdown': combo_yearly,
            }
            print(f"  ==> TOTAL: {total_n} trades | WinRate: {tot_wr*100:4.1f}% | 2B: {tot_2b*100:4.1f}% | Breakout: {tot_break*100:4.1f}% | PnL: {pnl_ratio:4.2f} | 1-Slot: {nav_1s:6.4f}x (MDD: {mdd1*100:4.1f}%) | 2-Slot: {nav_2s:6.4f}x (MDD: {mdd2*100:4.1f}%)")
            
    # ±10% Perturbation Test on Combo A
    print("\n" + "=" * 80)
    print(">>> [Phase 7] Running ±10% Parameter Perturbation Stress Test on Combo A...")
    print("=" * 80)
    perturbation_results = {}
    for perturb_factor, p_name in [(0.90, "Cutoff_-10%"), (1.00, "Base"), (1.10, "Cutoff_+10%")]:
        p_trades = []
        for test_yr in years:
            train_pool = fb[(fb['year'] < test_yr) & (fb['is_golden_domain'])].copy()
            test_pool = fb[(fb['year'] == test_yr) & (fb['is_golden_domain'])].copy()
            train_scores = train_pool['model_score'].values
            train_span = max(1, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
            target_train_count = int(55 * perturb_factor * train_span)
            if len(train_scores) > target_train_count:
                cutoff = float(np.percentile(train_scores, 100.0 * (1.0 - target_train_count / len(train_scores))))
            else:
                cutoff = float(np.percentile(train_scores, 75.0))
            test_cands = test_pool[test_pool['model_score'] >= cutoff].sort_values(['d2_date_str', 'model_score'], ascending=[True, False])
            test_selected = test_cands.groupby('d2_date_str').head(1)
            for _, r in test_selected.iterrows():
                tr = simulate_trade_v7(r, price_lookup, all_trade_dates, date_to_idx, exit_mode='Exit_A_BuwenClose')
                if tr:
                    p_trades.append(tr)
        df_p = pd.DataFrame(p_trades)
        wr_p = (df_p['net_ret'] > 0).mean() if len(df_p) > 0 else 0.0
        n1s, _, _, _ = simulate_portfolio_slots(p_trades, num_slots=1)
        n2s, _, _, _ = simulate_portfolio_slots(p_trades, num_slots=2)
        perturbation_results[p_name] = {
            'trades': len(p_trades),
            'win_rate': round(float(wr_p), 4),
            'nav_1slot': round(float(n1s), 4),
            'nav_2slot': round(float(n2s), 4),
        }
        print(f"  {p_name:<15}: {len(p_trades):3d} trades | WinRate: {wr_p*100:4.1f}% | 1-Slot: {n1s:6.4f}x | 2-Slot: {n2s:6.4f}x")
    all_results['perturbation_test'] = perturbation_results
    
    # Save Results
    with open(RESULTS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    if all_trades_ledger:
        pd.DataFrame(all_trades_ledger).to_csv(LEDGER_CSV_PATH, index=False, encoding='utf-8')
    print(f"\nSaved results to {RESULTS_JSON_PATH} and ledger to {LEDGER_CSV_PATH}")
    
    # =========================================================================
    # Phase 8: Score 2026-11-11 Today's Live Candidates in Golden Domain!
    # =========================================================================
    print("\n" + "=" * 80)
    print(">>> [Phase 8] Scoring 2026-11-11 Live Pre-Market Candidates in Golden Domain...")
    print("=" * 80)
    
    live_df = df[df['date_str'] == '2026-11-10'].copy()
    live_fb = live_df[live_df['is_turnover_fb']].copy()
    
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
    
    # Live market stats
    live_fb['mkt_d1_zt_cnt'] = market_stats['mkt_d1_zt_cnt'].get('2026-11-10', 40)
    live_fb['mkt_d1_fb_cnt'] = market_stats['mkt_d1_fb_cnt'].get('2026-11-10', 25)
    live_fb['mkt_d1_2b_cnt'] = market_stats['mkt_d1_2b_cnt'].get('2026-11-10', 8)
    live_fb['mkt_d1_3b_plus_cnt'] = market_stats['mkt_d1_3b_plus_cnt'].get('2026-11-10', 4)
    live_fb['mkt_d1_max_streak'] = market_stats['mkt_d1_max_streak'].get('2026-11-10', 4)
    live_fb['mkt_d1_broken_rate'] = market_stats['mkt_d1_broken_rate'].get('2026-11-10', 0.25)
    live_fb['mkt_past3d_1to2_seal_rate'] = market_stats['mkt_past3d_1to2_seal_rate'].get('2026-11-10', 0.20)
    live_fb['mkt_past5d_1to2_seal_rate'] = market_stats['mkt_past5d_1to2_seal_rate'].get('2026-11-10', 0.20)
    live_fb['mkt_past5d_2b_d3_ret'] = market_stats['mkt_past5d_2b_d3_ret'].get('2026-11-10', 0.0)
    
    # Pre-market default expected auction at +3.5%
    live_fb['d2_o_pct'] = 0.035
    live_fb['d2_o_pct_sq'] = (0.035 - 0.045) ** 2
    live_fb['mkt_d2_fb_open_mean'] = 0.025
    live_fb['mkt_d2_fb_open_gt5_cnt'] = 3
    live_fb['mkt_d2_fb_open_lt0_cnt'] = 2
    live_fb['mkt_d2_fb_open_std'] = 0.02
    live_fb['d2_o_pct_minus_mkt'] = 0.010
    
    # Group plate counts on live day
    p_cnts = live_fb.groupby('plate')['code6'].transform('count')
    live_fb['plate_d2_fb_cnt'] = p_cnts
    live_fb['plate_is_other'] = (live_fb['plate'] == "其他").astype(float)
    live_fb['peer_open_mean'] = np.where(live_fb['plate_d2_fb_cnt'] > 1, 0.030, -0.02)
    live_fb['peer_open_max'] = np.where(live_fb['plate_d2_fb_cnt'] > 1, 0.045, -0.02)
    live_fb['open_vs_peer_diff'] = 0.005
    live_fb['in_plate_open_rank'] = 1
    live_fb['in_mkt_open_rank'] = 3
    live_fb['is_theme_leader'] = (live_fb['plate_d2_fb_cnt'] >= 2).astype(float)
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
    
    # Filter live golden domain:
    # 1. d2_o_pct in [0.015, 0.075] (default 0.035)
    # 2. plate != '其他' & plate_d2_fb_cnt >= 2 & peer_open_mean >= -0.01
    # 3. notice_neg_tier == 0, ret5d <= 0.28, mcap_circ <= 200.0, amount >= 0.3e8
    live_golden = live_fb[
        (live_fb['plate'] != "其他") & (live_fb['plate_d2_fb_cnt'] >= 2) &
        (live_fb['notice_neg_tier'] == 0) & (live_fb['ret5d'] <= 0.28) &
        (live_fb['mcap_circ'] <= 200.0) & (live_fb['amount'] >= 0.3e8)
    ].copy()
    
    for col in feature_cols:
        live_golden[col] = live_golden[col].fillna(0.0)
        
    models_2026 = trained_models[2026]
    X_live = live_golden[feature_cols].values
    
    pred_reg_live = models_2026['m_reg'].predict(X_live)
    pred_cls_live = models_2026['m_cls'].predict_proba(X_live)[:, 1]
    X_live_s = models_2026['scaler'].transform(X_live)
    pred_ridge_live = models_2026['m_ridge'].predict(X_live_s)
    
    r_reg = pd.Series(pred_reg_live).rank(pct=True).values
    r_cls = pd.Series(pred_cls_live).rank(pct=True).values
    r_ridge = pd.Series(pred_ridge_live).rank(pct=True).values
    
    live_golden['ensemble_score'] = 0.40 * r_reg + 0.40 * r_cls + 0.20 * r_ridge
    live_sorted = live_golden.sort_values('ensemble_score', ascending=False)
    
    print("\nTop 10 Live Golden Domain Candidates for 2026-11-11:")
    print("-" * 110)
    print(f"{'Code':<8} {'Name':<10} {'Plate':<14} {'Break20d':<10} {'dd20':<8} {'Mcap(亿)':<10} {'Amount(亿)':<12} {'Score':<8}")
    print("-" * 110)
    for _, row in live_sorted.head(10).iterrows():
        amt_yi = row['amount'] / 1e8
        mcap_yi = row['mcap_circ']
        brk = "YES(突破)" if row['break_20d_high'] == 1 else "NO(震荡)"
        print(f"{row['code6']:<8} {row['stock_name']:<10} {row['plate']:<14} {brk:<10} {row['dd20']:<8.3f} {mcap_yi:<10.2f} {amt_yi:<12.2f} {row['ensemble_score']:<8.4f}")
    print("-" * 110)

if __name__ == '__main__':
    run_v7_synthesis()

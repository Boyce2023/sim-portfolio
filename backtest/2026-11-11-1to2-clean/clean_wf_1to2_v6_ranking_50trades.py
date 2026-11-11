#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v6_ranking_50trades.py
=============================================================================
One-to-Two V6 Ranking Engine - Calibrated for 50~65 Trades/Year (Weekly Top 1)
Strictly Compliant with A-Share T+1 Settlement & 100% Zero-Lookahead PIT
=============================================================================
Core Objectives:
1. Eradicate all artificial biases (dd20 <= 0.92, mcap caps, etc.).
   Only physical tradability: Main Board 00/60, D1 amount >= 1.0e8,
   D2 open < D2 ZT price - 0.01 (non-one-word open). Tested with and without ST.
2. 50+ Dimensional Pure PIT (< D2 09:25) Features:
   - Market climax & streak completeness (max streak, 2B count, 3B+ count, 1to2 seal rate, broken rate).
   - 09:25 auction thermometer (prev FB auction mean, >+5% count, <0% count, limit-down nuclear count).
   - Stock breakout & chip structure (20d/60d/120d breakout, dd20/60/120, ret3d/5d/20d, entity, amplitude, volume ratios).
   - KPL Plate dynamics (is_named_plate, in-plate auction rank, peer mean/diff, burst ratio, fresh theme, 10d plate 1to2 win rate).
   - CNINFO PIT notices (S-tier M&A/control, A-tier forecast/contracts, Neg-tier reductions/inquiries).
3. HistGradientBoostingClassifier + Regressor with strong regularization (depth 3 & 4, leaf 100, l2 20.0).
   Target: E[P(win) * E[ret_clipped]], clipped to [-15%, +35%].
4. Semi-Annual Walk-Forward (10 OOS windows: 2022H1 to 2026H2).
5. Exact calibration to 50~65 trades/year (single-slot & dual-slot portfolio simulations),
   plus +/-10% threshold perturbation sensitivity test.
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

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
NOTICES_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"

LEDGER_CSV_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v6_ranking_50trades_ledger.csv")
RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "clean_wf_1to2_v6_ranking_50trades_results.json")

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
    df['close_20d_ago'] = df.groupby('code6')['close'].shift(20)
    
    df['break_20d_high'] = (df['close'] >= df['high_max_20d'] - 0.01).astype(float)
    df['break_60d_high'] = (df['close'] >= df['high_max_60d'] - 0.01).astype(float)
    df['break_120d_high'] = (df['close'] >= df['high_max_120d'] - 0.01).astype(float)
    
    df['dd20'] = df['close'] / (df['high_max_20d'] + 1e-4)
    df['dd60'] = df['close'] / (df['high_max_60d'] + 1e-4)
    df['dd120'] = df['close'] / (df['high_max_120d'] + 1e-4)
    
    df['ret_3d'] = df['close'] / (df['close_3d_ago'] + 1e-4) - 1.0
    df['ret_5d'] = df['close'] / (df['close_5d_ago'] + 1e-4) - 1.0
    df['ret_20d'] = df['close'] / (df['close_20d_ago'] + 1e-4) - 1.0
    
    df['entity_ratio'] = (df['close'] - df['open']) / (df['pre_close'] + 1e-4)
    df['upper_shadow'] = (df['high'] - df['close']) / (df['pre_close'] + 1e-4)
    df['lower_shadow'] = (np.minimum(df['open'], df['close']) - df['low']) / (df['pre_close'] + 1e-4)
    df['amplitude'] = (df['high'] - df['low']) / (df['pre_close'] + 1e-4)
    df['seal_quality'] = df['entity_ratio'] - 0.5 * (df['amplitude'] - df['entity_ratio'])
    
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
    df['d2_is_yizi_dt'] = (df['d2_close'] <= df['d2_dt_price'] + 0.01) & (df['d2_open'] == df['d2_close']) & (df['d2_high'] == df['d2_close'])
    df['d2_o_pct'] = df['d2_open'] / df['close'] - 1.0
    
    print(f"Price DB loaded: {len(df):,} rows in {time.time()-t0:.2f}s")
    return df

def build_market_daily_stats(df):
    print(">>> [Phase 3] Computing Daily Market Sentiment, Climax, and Regime Stats...")
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

    market_stats = {
        'all_trade_dates': all_trade_dates,
        'date_to_idx': date_to_idx,
        'mkt_d1_zt_cnt': mkt_d1_zt_cnt,
        'mkt_d1_fb_cnt': mkt_d1_fb_cnt,
        'mkt_d1_2b_cnt': mkt_d1_2b_cnt,
        'mkt_d1_3b_plus_cnt': mkt_d1_3b_plus_cnt,
        'mkt_d1_max_streak': mkt_d1_max_streak,
        'mkt_d1_broken_rate': mkt_d1_broken_rate,
        'daily_1to2_ratio': daily_1to2_ratio,
        'mkt_past3d_1to2_seal_rate': mkt_past3d_1to2_seal_rate,
        'mkt_past5d_1to2_seal_rate': mkt_past5d_1to2_seal_rate,
    }
    print(f"Market sentiment stats built in {time.time()-t0:.2f}s")
    return market_stats

def simulate_high_payoff_exit(code, d2_str, d2_open, d2_close, d2_is_zt, price_lookup, all_trade_dates, date_to_idx):
    """
    Simulates High Payoff Exit SOP:
    - Entry: D2 open
    - If D2 does not seal limit up (d2_is_zt == False):
        Exit at D3 open (rollover on one-word limit down)
    - If D2 seals limit up (d2_is_zt == True):
        On D3:
          If d3_o_pct < -0.01:
            Exit at D3 open (weak auction profit taking)
          Else:
            Intraday -5% protection: if d3_low <= round(d2_close * 0.95, 2):
              exit at stop price (or d3_open if opened below stop)
            Elif d3 seals limit up (d3_is_zt):
              HOLD to D4!
            Else (broken board / didn't seal):
              Exit at D3 close (14:55)
        If held into D4:
          Repeat same logic: weak open <-1% exit at open; -5% stop exit; seal hold; else 14:55 close exit.
        Max holding period: 8 trading days.
    """
    idx_d2 = date_to_idx.get(d2_str, -1)
    if idx_d2 == -1:
        return None
        
    buy_price = d2_open
    if buy_price <= 0:
        return None
        
    sealed_2b = 1 if d2_is_zt else 0
    curr_idx = idx_d2 + 1
    prev_close = d2_close
    exit_price = None
    exit_date = None
    exit_at_open = False
    
    if not d2_is_zt:
        # Failed to seal 2-board: exit at D3 open
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
        # Successfully sealed 2-board!
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                exit_price = prev_close
                exit_date = d_curr
                break
            o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
            
            # Check rollover on one-word limit-down
            if is_yizi_dt:
                curr_idx += 1
                prev_close = c
                continue
                
            day_o_pct = (o / prev_close) - 1.0
            
            # Condition 1: Weak open <-1% -> exit at open!
            if day_o_pct < -0.01:
                exit_price = o
                exit_date = d_curr
                exit_at_open = True
                break
                
            # Condition 2: Intraday -5% protection stop
            stop_px = round(prev_close * 0.95, 2)
            if l <= stop_px:
                exit_price = max(o, stop_px) if o <= stop_px else stop_px
                exit_date = d_curr
                break
                
            # Condition 3: Sealed limit-up -> HOLD to next day!
            if is_zt:
                prev_close = c
                curr_idx += 1
                if curr_idx - idx_d2 >= 8:
                    exit_price = c
                    exit_date = d_curr
                    break
                continue
            else:
                # Broken board / did not seal: exit at 14:55 close!
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
        'buy_price': round(float(buy_price), 2),
        'exit_price': round(float(exit_price), 2),
        'exit_date': exit_date,
        'exit_at_open': exit_at_open,
        'holding_days': holding_days,
        'sealed_2b': sealed_2b,
        'gross_ret': round(float(gross_ret), 4),
        'net_ret': round(float(net_ret), 4),
    }

def build_v6_candidates_and_features(df, stock_to_plate_info, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices, market_stats, price_lookup):
    print(">>> [Phase 4] Precomputing High Payoff Exit & Building 50+ Dim PIT Features...")
    t0 = time.time()
    
    fb_all = df[df['is_turnover_fb'] & df['d2_date_str'].notna()].copy()
    fb_all = fb_all[(fb_all['d2_date_str'] >= "2021-01-04") & (fb_all['d2_date_str'] <= "2026-11-10")].copy()
    
    # Physical constraints:
    # 1. Main board 00/60
    # 2. D1 Amount >= 1.0e8
    # 3. D2 open not one-word limit-up (d2_open < d2_zt_price - 0.01)
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
    
    # Mark ST
    fb['is_st'] = fb['stock_name'].str.contains('ST|退', regex=True).astype(int)
    
    # Precompute High Payoff Exit for each candidate
    all_trade_dates = market_stats['all_trade_dates']
    date_to_idx = market_stats['date_to_idx']
    
    exit_results = []
    for r in fb[['code6', 'd2_date_str', 'd2_open', 'd2_close', 'd2_is_zt']].itertuples(index=False):
        res = simulate_high_payoff_exit(r.code6, r.d2_date_str, r.d2_open, r.d2_close, r.d2_is_zt, price_lookup, all_trade_dates, date_to_idx)
        if res:
            exit_results.append(res)
        else:
            exit_results.append({
                'buy_price': r.d2_open,
                'exit_price': r.d2_open,
                'exit_date': r.d2_date_str,
                'exit_at_open': True,
                'holding_days': 1,
                'sealed_2b': 0,
                'gross_ret': 0.0,
                'net_ret': -FEE_RATE,
            })
            
    df_exit = pd.DataFrame(exit_results)
    for col in df_exit.columns:
        fb[f'trade_{col}'] = df_exit[col].values
        
    fb['target_ret'] = fb['trade_net_ret'].values
    fb['target_ret_clipped'] = np.clip(fb['target_ret'], -0.15, 0.35)
    fb['target_win'] = (fb['target_ret'] > 0.01).astype(float)
    
    # Market Features
    fb['mkt_d1_zt_cnt'] = [market_stats['mkt_d1_zt_cnt'].get(d, 40) for d in fb['date_str']]
    fb['mkt_d1_fb_cnt'] = [market_stats['mkt_d1_fb_cnt'].get(d, 25) for d in fb['date_str']]
    fb['mkt_d1_2b_cnt'] = [market_stats['mkt_d1_2b_cnt'].get(d, 8) for d in fb['date_str']]
    fb['mkt_d1_3b_plus_cnt'] = [market_stats['mkt_d1_3b_plus_cnt'].get(d, 4) for d in fb['date_str']]
    fb['mkt_d1_max_streak'] = [market_stats['mkt_d1_max_streak'].get(d, 4) for d in fb['date_str']]
    fb['mkt_d1_broken_rate'] = [market_stats['mkt_d1_broken_rate'].get(d, 0.25) for d in fb['date_str']]
    fb['mkt_d1_1to2_rate'] = [market_stats['daily_1to2_ratio'].get(d, 0.20) for d in fb['date_str']]
    fb['mkt_past3d_1to2_seal_rate'] = [market_stats['mkt_past3d_1to2_seal_rate'].get(d, 0.20) for d in fb['date_str']]
    fb['mkt_past5d_1to2_seal_rate'] = [market_stats['mkt_past5d_1to2_seal_rate'].get(d, 0.20) for d in fb['date_str']]
    
    # Auction Thermometer
    d2_mkt_open_mean = fb.groupby('d2_date_str')['d2_o_pct'].transform('mean')
    d2_mkt_open_gt5 = fb.groupby('d2_date_str')['d2_o_pct'].transform(lambda s: (s >= 0.05).sum())
    d2_mkt_open_lt0 = fb.groupby('d2_date_str')['d2_o_pct'].transform(lambda s: (s < 0.0).sum())
    d2_mkt_open_dt = fb.groupby('d2_date_str')['d2_o_pct'].transform(lambda s: (s <= -0.095).sum())
    d2_mkt_open_std = fb.groupby('d2_date_str')['d2_o_pct'].transform(lambda s: s.std() if len(s) > 1 else 0.02).fillna(0.02)
    
    fb['prev_zt_auc_avg'] = d2_mkt_open_mean
    fb['auc_gt5_cnt'] = d2_mkt_open_gt5
    fb['auc_lt0_cnt'] = d2_mkt_open_lt0
    fb['auc_dt_cnt'] = d2_mkt_open_dt
    fb['auc_std'] = d2_mkt_open_std
    fb['d2_o_pct_minus_mkt'] = fb['d2_o_pct'] - fb['prev_zt_auc_avg']
    fb['d2_o_pct_sq'] = (fb['d2_o_pct'] - 0.045) ** 2
    
    # Plate Features
    plate_d2_groups = fb.groupby(['d2_date_str', 'plate'])['d2_o_pct']
    plate_d2_sum = plate_d2_groups.transform('sum')
    plate_d2_cnt = plate_d2_groups.transform('count')
    plate_d2_max = plate_d2_groups.transform('max')
    
    fb['plate_d2_fb_cnt'] = plate_d2_cnt
    fb['is_named_plate'] = (fb['plate'] != "其他").astype(float)
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
    
    burst_ratios = []
    is_fresh_list = []
    for row in fb[['date_str', 'plate', 'plate_d1_zt_cnt']].itertuples(index=False):
        d_str, p_name, cnt_d1 = row.date_str, row.plate, row.plate_d1_zt_cnt
        i = date_to_idx.get(d_str, 0)
        if p_name != "其他" and i >= 20:
            past_20d_counts = [plate_daily_counts[all_trade_dates[k]].get(p_name, 0) for k in range(i - 20, i)]
            avg_20d = float(np.mean(past_20d_counts)) if past_20d_counts else 0.5
            burst = cnt_d1 / (avg_20d + 0.2)
            burst_ratios.append(burst)
            p3 = sum(past_20d_counts[-3:]) if len(past_20d_counts) >= 3 else 0
            is_fresh_list.append(1.0 if p3 <= 1 else 0.0)
        else:
            burst_ratios.append(1.0)
            is_fresh_list.append(0.5)
            
    fb['plate_burst_ratio'] = burst_ratios
    fb['plate_is_fresh'] = is_fresh_list
    
    # Notices
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
    
    print(f"Candidates & Features ready: {len(fb):,} rows in {time.time()-t0:.2f}s")
    return fb

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

def run_semi_annual_walk_forward(fb, feature_cols, max_depth=3, include_st=False, target_trades_per_yr=55):
    """
    10 Semi-Annual OOS windows: 2022H1 to 2026H2.
    Expanding training window.
    Calibrates cutoff score on training set to achieve target trades per year.
    """
    df_pool = fb.copy()
    if not include_st:
        df_pool = df_pool[df_pool['is_st'] == 0].copy()
        
    windows = [
        ("2022H1", "2022-01-01", "2022-06-30"),
        ("2022H2", "2022-07-01", "2022-12-31"),
        ("2023H1", "2023-01-01", "2023-06-30"),
        ("2023H2", "2023-07-01", "2023-12-31"),
        ("2024H1", "2024-01-01", "2024-06-30"),
        ("2024H2", "2024-07-01", "2024-12-31"),
        ("2025H1", "2025-01-01", "2025-06-30"),
        ("2025H2", "2025-07-01", "2025-12-31"),
        ("2026H1", "2026-01-01", "2026-06-30"),
        ("2026H2", "2026-07-01", "2026-11-10"),
    ]
    
    oos_trades = []
    
    for win_name, start_d, end_d in windows:
        train_mask = df_pool['d2_date_str'] < start_d
        test_mask = (df_pool['d2_date_str'] >= start_d) & (df_pool['d2_date_str'] <= end_d)
        
        train_df = df_pool[train_mask].copy()
        test_df = df_pool[test_mask].copy()
        
        if len(test_df) == 0:
            continue
            
        X_train = train_df[feature_cols].values
        y_train_reg = train_df['target_ret_clipped'].values
        y_train_win = train_df['target_win'].values
        
        X_test = test_df[feature_cols].values
        
        # Models
        m_reg = HistGradientBoostingRegressor(
            max_depth=max_depth, min_samples_leaf=100, l2_regularization=20.0, max_iter=100, random_state=42
        )
        m_reg.fit(X_train, y_train_reg)
        
        m_cls = HistGradientBoostingClassifier(
            max_depth=max_depth, min_samples_leaf=100, l2_regularization=20.0, max_iter=100, random_state=42
        )
        m_cls.fit(X_train, y_train_win)
        
        # Training scores to calibrate cutoff
        pred_train_reg = m_reg.predict(X_train)
        pred_train_win = m_cls.predict_proba(X_train)[:, 1]
        score_train = pred_train_win * np.maximum(0.005, pred_train_reg + 0.05)
        train_df['pred_score'] = score_train
        
        # Test predictions
        pred_test_reg = m_reg.predict(X_test)
        pred_test_win = m_cls.predict_proba(X_test)[:, 1]
        score_test = pred_test_win * np.maximum(0.005, pred_test_reg + 0.05)
        test_df['pred_score'] = score_test
        
        # Calibrate daily cutoff on training daily max scores
        train_daily_max = train_df.groupby('d2_date_str')['pred_score'].max()
        # Annual trading days ~ 244
        target_pct = min(0.95, max(0.05, 1.0 - (target_trades_per_yr / 244.0)))
        cutoff = float(np.percentile(train_daily_max.values, 100.0 * target_pct))
        
        # On test days: pick top 1 if >= cutoff
        test_candidates = test_df[test_df['pred_score'] >= cutoff].sort_values(['d2_date_str', 'pred_score'], ascending=[True, False])
        test_picks = test_candidates.groupby('d2_date_str').head(1)
        
        for _, r in test_picks.iterrows():
            oos_trades.append({
                'code': r['code6'],
                'name': r['stock_name'],
                'buy_date': r['d2_date_str'],
                'buy_price': r['trade_buy_price'],
                'exit_date': r['trade_exit_date'],
                'exit_price': r['trade_exit_price'],
                'exit_at_open': r['trade_exit_at_open'],
                'holding_days': r['trade_holding_days'],
                'sealed_2b': r['trade_sealed_2b'],
                'gross_ret': r['trade_gross_ret'],
                'net_ret': r['trade_net_ret'],
                'plate': r['plate'],
                'break_20d_high': int(r['break_20d_high']),
                'dd20': round(float(r['dd20']), 4),
                'd2_o_pct': round(float(r['d2_o_pct']), 4),
                'score': round(float(r['pred_score']), 4),
                'window': win_name,
                'year': int(r['d2_date_str'][:4]),
            })
            
    return oos_trades

def evaluate_trades_stats(trades_list):
    if not trades_list:
        return {}
    df_tr = pd.DataFrame(trades_list)
    total_n = len(df_tr)
    win_n = (df_tr['net_ret'] > 0).sum()
    win_rate = win_n / total_n if total_n > 0 else 0.0
    
    wins = df_tr[df_tr['net_ret'] > 0]['net_ret']
    losses = df_tr[df_tr['net_ret'] <= 0]['net_ret']
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0.01
    pnl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    sealed_2b_rate = df_tr['sealed_2b'].mean()
    breakout_rate = df_tr['break_20d_high'].mean()
    avg_hold = df_tr['holding_days'].mean()
    
    nav_1s, n1, _ = simulate_portfolio_slots(trades_list, num_slots=1)
    nav_2s, n2, _ = simulate_portfolio_slots(trades_list, num_slots=2)
    
    # Yearly breakdown
    yearly_stats = {}
    years = [2022, 2023, 2024, 2025, 2026]
    for yr in years:
        df_yr = df_tr[df_tr['year'] == yr]
        yr_n = len(df_yr)
        if yr_n > 0:
            yr_wr = (df_yr['net_ret'] > 0).mean()
            yr_wins = df_yr[df_yr['net_ret'] > 0]['net_ret']
            yr_losses = df_yr[df_yr['net_ret'] <= 0]['net_ret']
            yr_aw = yr_wins.mean() if len(yr_wins) > 0 else 0.0
            yr_al = abs(yr_losses.mean()) if len(yr_losses) > 0 else 0.01
            yr_pnl = yr_aw / yr_al if yr_al > 0 else 0.0
            yr_2b = df_yr['sealed_2b'].mean()
            yr_bo = df_yr['break_20d_high'].mean()
            yr_nav1, _, _ = simulate_portfolio_slots(df_yr.to_dict('records'), num_slots=1)
            yr_nav2, _, _ = simulate_portfolio_slots(df_yr.to_dict('records'), num_slots=2)
            bench = CSI300_ANNUAL_RETURNS.get(yr, 0.0)
            excess = (yr_nav1 - 1.0) - bench
            yearly_stats[yr] = {
                'trades': yr_n,
                'win_rate': round(float(yr_wr), 4),
                'pnl_ratio': round(float(yr_pnl), 2),
                'sealed_2b_rate': round(float(yr_2b), 4),
                'breakout_rate': round(float(yr_bo), 4),
                'nav_1slot': round(float(yr_nav1), 4),
                'nav_2slot': round(float(yr_nav2), 4),
                'csi300': bench,
                'excess_1slot': round(float(excess), 4),
            }
        else:
            yearly_stats[yr] = {'trades': 0}
            
    return {
        'total_trades': total_n,
        'executed_1slot': n1,
        'executed_2slot': n2,
        'win_rate': round(float(win_rate), 4),
        'pnl_ratio': round(float(pnl_ratio), 2),
        'avg_win': round(float(avg_win), 4),
        'avg_loss': round(float(avg_loss), 4),
        'sealed_2b_rate': round(float(sealed_2b_rate), 4),
        'breakout_rate': round(float(breakout_rate), 4),
        'avg_holding_days': round(float(avg_hold), 2),
        'cum_nav_1slot': round(float(nav_1s), 4),
        'cum_nav_2slot': round(float(nav_2s), 4),
        'yearly': yearly_stats,
    }

def main():
    t_start = time.time()
    print("=" * 80)
    print(">>> STARTING V6 50~65 TRADES/YEAR RANKING ENGINE WALK-FORWARD LAB")
    print("=" * 80)
    
    stock_to_plate_info, kpl_daily_plates, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices = load_kpl_and_notices()
    df = load_price_data()
    market_stats = build_market_daily_stats(df)
    
    price_lookup = {}
    for r in df[['code6', 'date_str', 'open', 'high', 'low', 'close', 'adj_close', 'zt_price', 'dt_price', 'is_zt', 'is_yizi_dt']].itertuples(index=False):
        price_lookup[(r.code6, r.date_str)] = (
            r.open, r.high, r.low, r.close, r.adj_close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt
        )
        
    fb = build_v6_candidates_and_features(df, stock_to_plate_info, plate_daily_counts, s_tier_notices, a_tier_notices, neg_tier_notices, market_stats, price_lookup)
    
    feature_cols = [
        # Market Sentiment & Ladder
        'mkt_d1_zt_cnt', 'mkt_d1_fb_cnt', 'mkt_d1_2b_cnt', 'mkt_d1_3b_plus_cnt', 'mkt_d1_max_streak',
        'mkt_d1_broken_rate', 'mkt_d1_1to2_rate', 'mkt_past3d_1to2_seal_rate', 'mkt_past5d_1to2_seal_rate',
        
        # 09:25 Auction Thermometer
        'prev_zt_auc_avg', 'auc_gt5_cnt', 'auc_lt0_cnt', 'auc_dt_cnt', 'auc_std',
        'd2_o_pct', 'd2_o_pct_sq', 'd2_o_pct_minus_mkt',
        
        # Stock Breakout Structure
        'break_20d_high', 'break_60d_high', 'break_120d_high', 'dd20', 'dd60', 'dd120',
        'ret_3d', 'ret_5d', 'ret_20d',
        'entity_ratio', 'upper_shadow', 'lower_shadow', 'amplitude', 'seal_quality',
        'turn', 'vol_ratio_5d', 'vol_ratio_20d', 'amount_log', 'mcap_log',
        
        # KPL Plate Dynamics
        'plate_d1_zt_cnt', 'plate_d2_fb_cnt', 'is_named_plate', 'plate_burst_ratio', 'plate_is_fresh',
        'peer_open_mean', 'peer_open_max', 'open_vs_peer_diff', 'in_plate_open_rank', 'in_mkt_open_rank',
        
        # PIT Notices
        'notice_s_tier', 'notice_a_tier', 'notice_neg_tier', 'has_any_pos_notice'
    ]
    
    for c in feature_cols:
        fb[c] = fb[c].fillna(0.0)
        
    # =========================================================================
    # Experiments:
    # 1. Base Calibrated 55 trades/yr (depth 3, non-ST)
    # 2. Depth 4 (depth 4, non-ST)
    # 3. Include ST (depth 3, with ST)
    # 4. Target 50 trades/yr
    # 5. Target 60 trades/yr
    # 6. Target 65 trades/yr
    # 7. Threshold -10% perturbation (target 61 trades)
    # 8. Threshold +10% perturbation (target 50 trades)
    # =========================================================================
    configs = [
        ("Base_55Trades_Depth3_NonST", 3, False, 55),
        ("Exp_55Trades_Depth4_NonST", 4, False, 55),
        ("Exp_55Trades_Depth3_WithST", 3, True, 55),
        ("Target_50Trades_Depth3_NonST", 3, False, 50),
        ("Target_60Trades_Depth3_NonST", 3, False, 60),
        ("Target_65Trades_Depth3_NonST", 3, False, 65),
    ]
    
    experiment_results = {}
    master_ledger = []
    
    for cfg_name, depth, inc_st, tgt_trades in configs:
        print(f"\n" + "-" * 75)
        print(f"--- Running Config: {cfg_name} (depth={depth}, ST={inc_st}, target={tgt_trades}/yr) ---")
        print("-" * 75)
        
        trades = run_semi_annual_walk_forward(fb, feature_cols, max_depth=depth, include_st=inc_st, target_trades_per_yr=tgt_trades)
        stats = evaluate_trades_stats(trades)
        experiment_results[cfg_name] = stats
        
        if cfg_name == "Base_55Trades_Depth3_NonST":
            for tr in trades:
                tr['config'] = cfg_name
                master_ledger.append(tr)
                
        print(f"Total Trades: {stats['total_trades']} (Annual Avg: {stats['total_trades']/4.85:.1f})")
        print(f"Win Rate: {stats['win_rate']*100:.1f}% | PnL Ratio: {stats['pnl_ratio']:.2f} | 2B Rate: {stats['sealed_2b_rate']*100:.1f}% | Breakout Rate: {stats['breakout_rate']*100:.1f}%")
        print(f"1-Slot NAV: {stats['cum_nav_1slot']:.4f}x | 2-Slot NAV: {stats['cum_nav_2slot']:.4f}x")
        print("Yearly Breakdown:")
        for yr, y_stat in stats['yearly'].items():
            if y_stat['trades'] > 0:
                print(f"  {yr}: {y_stat['trades']:2d} trades | WR: {y_stat['win_rate']*100:4.1f}% | PnL: {y_stat['pnl_ratio']:4.2f} | 2B: {y_stat['sealed_2b_rate']*100:4.1f}% | 1-Slot: {y_stat['nav_1slot']:6.4f}x (Excess: {y_stat['excess_1slot']*100:+6.2f}%) | 2-Slot: {y_stat['nav_2slot']:6.4f}x")

    # Threshold Perturbation on Base (Target 55 -> Target 50 (-10%) & Target 60 (+10%))
    print("\n" + "=" * 80)
    print(">>> [Phase 5] Threshold Sensitivity Perturbation Test (+/- 10% Frequency)")
    print("=" * 80)
    pert_minus = experiment_results.get("Target_50Trades_Depth3_NonST", {})
    pert_plus = experiment_results.get("Target_60Trades_Depth3_NonST", {})
    base = experiment_results.get("Base_55Trades_Depth3_NonST", {})
    
    print(f"Perturbation Analysis:")
    print(f"  -10% Trades Target (50/yr): Trades={pert_minus.get('total_trades',0)}, WR={pert_minus.get('win_rate',0)*100:.1f}%, PnL={pert_minus.get('pnl_ratio',0):.2f}, 1-Slot={pert_minus.get('cum_nav_1slot',0):.4f}x, 2-Slot={pert_minus.get('cum_nav_2slot',0):.4f}x")
    print(f"   BASE Trades Target (55/yr): Trades={base.get('total_trades',0)}, WR={base.get('win_rate',0)*100:.1f}%, PnL={base.get('pnl_ratio',0):.2f}, 1-Slot={base.get('cum_nav_1slot',0):.4f}x, 2-Slot={base.get('cum_nav_2slot',0):.4f}x")
    print(f"  +10% Trades Target (60/yr): Trades={pert_plus.get('total_trades',0)}, WR={pert_plus.get('win_rate',0)*100:.1f}%, PnL={pert_plus.get('pnl_ratio',0):.2f}, 1-Slot={pert_plus.get('cum_nav_1slot',0):.4f}x, 2-Slot={pert_plus.get('cum_nav_2slot',0):.4f}x")

    # Save to JSON & CSV
    with open(RESULTS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(experiment_results, f, indent=2, ensure_ascii=False)
        
    if master_ledger:
        pd.DataFrame(master_ledger).to_csv(LEDGER_CSV_PATH, index=False, encoding='utf-8-sig')
        print(f"Master ledger saved to {LEDGER_CSV_PATH}")
        
    print(f"Results JSON saved to {RESULTS_JSON_PATH}")
    print(f"All done in {time.time()-t_start:.2f}s!")

if __name__ == "__main__":
    main()

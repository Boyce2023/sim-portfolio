#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ablation_all_constraints_5y.py
=============================================================================
5-Year Full-Sample (2021-2026) Constraint Ablation Matrix for 1-to-2 Strategy
=============================================================================
Evaluates the marginal contribution of 12 distinct constraints on:
- Sample Count (N)
- 2nd Board Seal Rate (2B封板率)
- D3 Avg Net Return (D3净收益均值)
- >=3 Consecutive Limit-Up Monster Rate (>=3连板成妖率)
- >-8% Severe Loss Rate (>-8%大面率)
- Win/Loss Ratio (盈亏比)

Output:
/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean/ablation_all_constraints_5y.json
"""

import os
import sys
import json
import time
import sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)
JSON_OUTPUT = os.path.join(OUTPUT_DIR, "ablation_all_constraints_5y.json")

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
NOTICES_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"

def load_data():
    t0 = time.time()
    print(">>> [1/4] Loading Full Market Price Database (Active + Delisted)...")
    cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'amount', 'turn', 'oshare']
    
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2020-10-01'))).to_table().to_pandas()
    
    df_del = pd.DataFrame()
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2020-10-01'))).to_table().to_pandas()
        
    df = pd.concat([df_act, df_del], ignore_index=True)
    del df_act, df_del
    
    df['code6'] = df['ticker'].astype(str).str.extract(r'(\d{6})')[0].fillna('').str.zfill(6)
    df = df[df['code6'].str.startswith(('00', '60'))].copy()
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df.sort_values(['code6', 'date'], inplace=True)
    df.reset_index(drop=True, inplace=True)
    print(f"Price DB loaded: {len(df):,} records across {df['code6'].nunique()} tickers in {time.time()-t0:.2f}s")
    
    # 2. Limit Up calculations
    print(">>> [2/4] Identifying Limit-Ups, Streaks and T+1 Forward Targets...")
    t1 = time.time()
    df['pre_close'] = df.groupby('code6')['close'].shift(1)
    df['zt_price'] = (df['pre_close'] * 1.10).round(2)
    df['dt_price'] = (df['pre_close'] * 0.90).round(2)
    
    # Detect ST by daily price limit ~5% (i.e. close / pre_close <= 1.055 when hitting upper ceiling)
    # Also check if stock name has ST from KPL later
    df['is_zt'] = (df['close'] >= df['zt_price'] - 0.01) & (df['close'] == df['high']) & (df['pre_close'] > 0)
    df['is_yizi'] = df['is_zt'] & (df['open'] == df['close']) & (df['low'] == df['close'])
    
    # Check streak
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
    
    # Price features on D1
    df['mcap_circ'] = df['close'] * df['oshare'] / 1e8 # 亿
    df['amount_yi'] = df['amount'] / 1e8 # 亿
    df['turn_pct'] = df['turn'] * 100.0 # 百分比换手率
    
    df['high_max_20d'] = df.groupby('code6')['high'].transform(lambda s: s.shift(1).rolling(20, min_periods=10).max())
    df['high_max_60d'] = df.groupby('code6')['high'].transform(lambda s: s.shift(1).rolling(60, min_periods=20).max())
    df['close_5d_ago'] = df.groupby('code6')['close'].shift(5)
    
    df['dd20'] = df['close'] / (df['high_max_20d'] + 1e-4)
    df['dd60'] = df['close'] / (df['high_max_60d'] + 1e-4)
    df['ret5d'] = df['pre_close'] / (df['close_5d_ago'] + 1e-4) - 1.0
    
    # D2 forward features
    df['d2_date_str'] = df.groupby('code6')['date_str'].shift(-1)
    df['d2_open'] = df.groupby('code6')['open'].shift(-1)
    df['d2_high'] = df.groupby('code6')['high'].shift(-1)
    df['d2_low'] = df.groupby('code6')['low'].shift(-1)
    df['d2_close'] = df.groupby('code6')['close'].shift(-1)
    df['d2_zt_price'] = (df['close'] * 1.10).round(2)
    df['d2_is_zt'] = (df['d2_close'] >= df['d2_zt_price'] - 0.01) & (df['d2_close'] == df['d2_high'])
    df['d2_is_yizi'] = df['d2_is_zt'] & (df['d2_open'] == df['d2_close']) & (df['d2_low'] == df['d2_close'])
    df['d2_o_pct'] = df['d2_open'] / df['close'] - 1.0
    
    # D3 forward features
    df['d3_open'] = df.groupby('code6')['open'].shift(-2)
    df['d3_close'] = df.groupby('code6')['close'].shift(-2)
    df['d3_streak'] = df.groupby('code6')['streak'].shift(-2)
    
    # Reach 3B: D2 is ZT and D3 streak >= 3
    df['reach_3b'] = np.where(df['d2_is_zt'] & (df['d3_streak'] >= 3), 1, 0)
    
    # D3 net return: buy at D2 open, exit at D3 open (fee = 0.0014)
    df['d3_net_ret'] = df['d3_open'] / (df['d2_open'] + 1e-4) - 1.0 - 0.0014
    df['is_big_loss'] = np.where(df['d3_net_ret'] < -0.08, 1, 0)
    print(f"Features and forward targets ready in {time.time()-t1:.2f}s")
    
    # 3. Load KPL plates and CNINFO Notices
    print(">>> [3/4] Ingesting KPL Plates and CNINFO Notices...")
    t2 = time.time()
    stock_to_plate_info = {}
    kpl_stock_names = {}
    with open(KPL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            d_str = entry['date']
            plates = entry.get('plates', [])
            p_counts = []
            for p_obj in plates:
                p_name = p_obj.get('plate', '')
                stks = p_obj.get('stocks', [])
                p_counts.append((p_name, len(stks), stks))
            p_counts.sort(key=lambda x: x[1], reverse=True)
            for p_name, sz, stks in p_counts:
                for s in stks:
                    c6 = str(s[0])[:6].zfill(6)
                    s_name = s[1] if len(s) > 1 else ""
                    key = (d_str, c6)
                    kpl_stock_names[c6] = s_name
                    if key not in stock_to_plate_info or sz > stock_to_plate_info[key]['plate_sz']:
                        stock_to_plate_info[key] = {
                            'plate': p_name,
                            'name': s_name,
                            'plate_sz': sz,
                        }
                        
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
        except Exception as e:
            print(f"Error loading notices: {e}")
            
    print(f"KPL & Notices ready in {time.time()-t2:.2f}s")
    return df, stock_to_plate_info, kpl_stock_names, negative_notices, positive_notices

def prepare_base_universe(df, stock_to_plate_info, kpl_stock_names, negative_notices, positive_notices):
    print(">>> [4/4] Filtering Base Universe (2021-2026 Tradable Turnover First Boards)...")
    fb = df[df['is_turnover_fb']].copy()
    fb = fb[fb['d2_date_str'].notna()].copy()
    fb = fb[(fb['d2_date_str'] >= "2021-01-04") & (fb['d2_date_str'] <= "2026-11-10")].copy()
    
    # D2 must be open and tradable (not one-word ZT where buyer cannot buy)
    fb = fb[fb['d2_open'].notna()].copy()
    fb = fb[fb['d2_open'] < fb['d2_zt_price'] - 0.005].copy()
    
    # Attach plate info & stock name
    plates = []
    names = []
    plate_sizes = []
    for row in fb[['date_str', 'code6']].itertuples(index=False):
        info = stock_to_plate_info.get((row.date_str, row.code6))
        if info:
            plates.append(info['plate'])
            names.append(info['name'])
            plate_sizes.append(info['plate_sz'])
        else:
            plates.append("其他")
            names.append(kpl_stock_names.get(row.code6, ""))
            plate_sizes.append(1)
            
    fb['plate'] = plates
    fb['stock_name'] = names
    fb['theme_zt_cnt_d1'] = plate_sizes
    
    # ST indicator
    # Check if stock_name contains ST or *ST
    is_st_name = fb['stock_name'].str.contains(r'ST|退', regex=True, na=False)
    # Also check if daily return capped at 5%
    is_st_return = (fb['close'] / fb['pre_close'] <= 1.055) & (fb['close'] == fb['high'])
    fb['is_st'] = is_st_name | is_st_return
    
    # Notice indicators
    fb['has_neg_notice'] = [1 if (r.code6, r.d2_date_str) in negative_notices else 0 for r in fb[['code6', 'd2_date_str']].itertuples(index=False)]
    fb['has_pos_notice'] = [1 if (r.code6, r.d2_date_str) in positive_notices else 0 for r in fb[['code6', 'd2_date_str']].itertuples(index=False)]
    
    # Market Gates
    # Gate 1: Yesterday's 1-to-2 rate (d1_date's 1to2 rate)
    # Calculate daily 1to2 success rate for all dates
    daily_1to2_rate = fb.groupby('date_str')['d2_is_zt'].mean().to_dict()
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    gate1_prev_1to2_rate = {}
    gate3_roll5d_1to2_rate = {}
    for i, d in enumerate(all_trade_dates):
        if i >= 1:
            prev_d = all_trade_dates[i-1]
            gate1_prev_1to2_rate[d] = daily_1to2_rate.get(prev_d, 0.20)
        else:
            gate1_prev_1to2_rate[d] = 0.20
            
        if i >= 5:
            past_5d = [daily_1to2_rate.get(all_trade_dates[k], 0.20) for k in range(i-5, i)]
            gate3_roll5d_1to2_rate[d] = float(np.mean(past_5d))
        else:
            gate3_roll5d_1to2_rate[d] = 0.20
            
    # Gate 2: 09:25 D2 market-wide first board open mean
    d2_mkt_open_mean = fb.groupby('d2_date_str')['d2_o_pct'].mean().to_dict()
    
    fb['gate1_prev_1to2_rate'] = [gate1_prev_1to2_rate.get(d, 0.20) for d in fb['d2_date_str']]
    fb['gate2_mkt_open_mean'] = [d2_mkt_open_mean.get(d, 0.0) for d in fb['d2_date_str']]
    fb['gate3_roll5d_1to2_rate'] = [gate3_roll5d_1to2_rate.get(d, 0.20) for d in fb['d2_date_str']]
    
    print(f"Base Universe Ready: N = {len(fb):,} tradable turnover 1-to-2 candidates across 2021-2026.")
    return fb

def compute_metrics(sub_df):
    n = len(sub_df)
    if n == 0:
        return {
            'N': 0, 'pct_of_total': 0.0, 'seal_2b_rate': 0.0, 'd3_avg_net_ret': 0.0,
            'reach_3b_rate': 0.0, 'big_loss_rate': 0.0, 'win_rate': 0.0, 'win_loss_ratio': 0.0
        }
    seal_2b = sub_df['d2_is_zt'].mean()
    d3_ret = sub_df['d3_net_ret'].mean()
    reach_3b = sub_df['reach_3b'].mean()
    big_loss = sub_df['is_big_loss'].mean()
    win_rate = (sub_df['d3_net_ret'] > 0).mean()
    
    wins = sub_df.loc[sub_df['d3_net_ret'] > 0, 'd3_net_ret']
    losses = sub_df.loc[sub_df['d3_net_ret'] < 0, 'd3_net_ret']
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 1e-4
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    return {
        'N': int(n),
        'seal_2b_rate': round(float(seal_2b) * 100, 2),
        'd3_avg_net_ret': round(float(d3_ret) * 100, 2),
        'reach_3b_rate': round(float(reach_3b) * 100, 2),
        'big_loss_rate': round(float(big_loss) * 100, 2),
        'win_rate': round(float(win_rate) * 100, 2),
        'win_loss_ratio': round(float(win_loss_ratio), 2)
    }

def run_ablation():
    df, stock_to_plate_info, kpl_stock_names, negative_notices, positive_notices = load_data()
    fb = prepare_base_universe(df, stock_to_plate_info, kpl_stock_names, negative_notices, positive_notices)
    total_n = len(fb)
    
    # Benchmark metrics
    benchmark = compute_metrics(fb)
    benchmark['pct_of_total'] = 100.0
    
    print("\n" + "=" * 90)
    print("5-YEAR FULL-SAMPLE (2021-2026) 1-TO-2 CONSTRAINT ABLATION MATRIX")
    print(f"Base Universe: N = {total_n:,} | 2B Rate: {benchmark['seal_2b_rate']}% | D3 Net Ret: {benchmark['d3_avg_net_ret']}% | 3B+ Rate: {benchmark['reach_3b_rate']}% | Big Loss: {benchmark['big_loss_rate']}%")
    print("=" * 90)
    
    results = {
        'benchmark': benchmark,
        'ablations': {}
    }
    
    # Non-ST base for conditions 2-12 (to ensure clean comparison)
    # 1. 股票池范围：ST股 vs 非ST正常股
    print("\n[Condition 1] Stock Pool Scope: ST vs Non-ST Normal Stocks")
    cond1 = {
        "非ST主板正常股": fb[~fb['is_st']],
        "ST股": fb[fb['is_st']]
    }
    results['ablations']['1_stock_pool_scope'] = {}
    for k, v in cond1.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / total_n * 100, 2)
        results['ablations']['1_stock_pool_scope'][k] = m
        print(f"  {k:20s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # Use Non-ST pool as standard operating universe for testing specific constraints
    fb_clean = fb[~fb['is_st']].copy()
    n_clean = len(fb_clean)
    
    # 2. 流通市值区间
    print("\n[Condition 2] Circulating Market Cap (mcap_circ in 亿)")
    cond2 = {
        "<15亿": fb_clean[fb_clean['mcap_circ'] < 15.0],
        "15~30亿": fb_clean[(fb_clean['mcap_circ'] >= 15.0) & (fb_clean['mcap_circ'] < 30.0)],
        "30~60亿": fb_clean[(fb_clean['mcap_circ'] >= 30.0) & (fb_clean['mcap_circ'] < 60.0)],
        "60~150亿": fb_clean[(fb_clean['mcap_circ'] >= 60.0) & (fb_clean['mcap_circ'] < 150.0)],
        "150~300亿": fb_clean[(fb_clean['mcap_circ'] >= 150.0) & (fb_clean['mcap_circ'] < 300.0)],
        ">300亿": fb_clean[fb_clean['mcap_circ'] >= 300.0]
    }
    results['ablations']['2_circulating_market_cap'] = {}
    for k, v in cond2.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['2_circulating_market_cap'][k] = m
        print(f"  {k:20s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # 3. 首板成交额下限 (amount_yi in 亿)
    print("\n[Condition 3] Day 1 Turnover Amount (amount in 亿)")
    cond3 = {
        "<1亿": fb_clean[fb_clean['amount_yi'] < 1.0],
        "1~1.5亿": fb_clean[(fb_clean['amount_yi'] >= 1.0) & (fb_clean['amount_yi'] < 1.5)],
        "1.5~5亿": fb_clean[(fb_clean['amount_yi'] >= 1.5) & (fb_clean['amount_yi'] < 5.0)],
        "5~15亿": fb_clean[(fb_clean['amount_yi'] >= 5.0) & (fb_clean['amount_yi'] < 15.0)],
        ">15亿": fb_clean[fb_clean['amount_yi'] >= 15.0]
    }
    results['ablations']['3_d1_amount'] = {}
    for k, v in cond3.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['3_d1_amount'][k] = m
        print(f"  {k:20s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # 4. 股价距 20 日 / 60 日高点位置 (dd20)
    print("\n[Condition 4] Price Distance from 20-Day High (dd20) & 60-Day High (dd60)")
    cond4 = {
        "dd20 <0.80 (深跌超跌)": fb_clean[fb_clean['dd20'] < 0.80],
        "dd20 0.80~0.92 (低位震荡)": fb_clean[(fb_clean['dd20'] >= 0.80) & (fb_clean['dd20'] < 0.92)],
        "dd20 0.92~0.99 (临界蓄势)": fb_clean[(fb_clean['dd20'] >= 0.92) & (fb_clean['dd20'] < 0.99)],
        "dd20 >=1.00 (创20日新高突破!)": fb_clean[fb_clean['dd20'] >= 1.00],
        "dd60 >=1.00 (创60日新高大突破!)": fb_clean[fb_clean['dd60'] >= 1.00],
        "昔日毒门禁 dd20<=0.92 整体": fb_clean[fb_clean['dd20'] <= 0.92],
        "昔日被误杀 dd20>0.92 整体": fb_clean[fb_clean['dd20'] > 0.92]
    }
    results['ablations']['4_distance_to_high'] = {}
    for k, v in cond4.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['4_distance_to_high'][k] = m
        print(f"  {k:32s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # 5. 首板前 5 日涨幅 (ret5d)
    print("\n[Condition 5] Prior 5-Day Cumulative Return (ret5d)")
    cond5 = {
        "<0% (超跌反弹)": fb_clean[fb_clean['ret5d'] < 0.0],
        "0%~15% (温和攀升)": fb_clean[(fb_clean['ret5d'] >= 0.0) & (fb_clean['ret5d'] < 0.15)],
        "15%~28% (强势连阳)": fb_clean[(fb_clean['ret5d'] >= 0.15) & (fb_clean['ret5d'] < 0.28)],
        ">28% (加速急拉)": fb_clean[fb_clean['ret5d'] >= 0.28]
    }
    results['ablations']['5_ret5d'] = {}
    for k, v in cond5.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['5_ret5d'][k] = m
        print(f"  {k:22s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # 6. 首板换手率区间 (turn in %)
    print("\n[Condition 6] Day 1 Turnover Rate (turn in %)")
    cond6 = {
        "<3% (微量一字/无分歧)": fb_clean[fb_clean['turn_pct'] < 3.0],
        "3%~10% (轻度换手)": fb_clean[(fb_clean['turn_pct'] >= 3.0) & (fb_clean['turn_pct'] < 10.0)],
        "10%~18% (黄金充分换手)": fb_clean[(fb_clean['turn_pct'] >= 10.0) & (fb_clean['turn_pct'] < 18.0)],
        "18%~25% (分歧换手)": fb_clean[(fb_clean['turn_pct'] >= 18.0) & (fb_clean['turn_pct'] < 25.0)],
        ">25% (死亡爆量换手)": fb_clean[fb_clean['turn_pct'] >= 25.0]
    }
    results['ablations']['6_d1_turnover_rate'] = {}
    for k, v in cond6.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['6_d1_turnover_rate'][k] = m
        print(f"  {k:24s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # 7. 次日 09:25 开盘涨幅区间 (d2_o_pct)
    print("\n[Condition 7] Day 2 09:25 Auction Open Return (d2_o_pct)")
    cond7 = {
        "<-2% (核按钮开盘)": fb_clean[fb_clean['d2_o_pct'] < -0.02],
        "-2%~+1.5% (弱势平开)": fb_clean[(fb_clean['d2_o_pct'] >= -0.02) & (fb_clean['d2_o_pct'] < 0.015)],
        "+1.5%~+4.5% (温和高开)": fb_clean[(fb_clean['d2_o_pct'] >= 0.015) & (fb_clean['d2_o_pct'] < 0.045)],
        "+4.5%~+7.5% (强力高开)": fb_clean[(fb_clean['d2_o_pct'] >= 0.045) & (fb_clean['d2_o_pct'] < 0.075)],
        "+7.5%~+9.8% (超高开接盘)": fb_clean[(fb_clean['d2_o_pct'] >= 0.075) & (fb_clean['d2_o_pct'] <= 0.098)]
    }
    results['ablations']['7_d2_auction_open_pct'] = {}
    for k, v in cond7.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['7_d2_auction_open_pct'][k] = m
        print(f"  {k:24s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # 8. 板块首板梯队人数 (theme_zt_cnt_d1)
    print("\n[Condition 8] Sector Echelon Headcount (theme_zt_cnt_d1)")
    cond8 = {
        "独苗1只(含其他孤儿股)": fb_clean[fb_clean['theme_zt_cnt_d1'] <= 1],
        "2~3只(小梯队)": fb_clean[(fb_clean['theme_zt_cnt_d1'] >= 2) & (fb_clean['theme_zt_cnt_d1'] <= 3)],
        "4~6只(中梯队主线雏形)": fb_clean[(fb_clean['theme_zt_cnt_d1'] >= 4) & (fb_clean['theme_zt_cnt_d1'] <= 6)],
        "7~12只(大主线爆发)": fb_clean[(fb_clean['theme_zt_cnt_d1'] >= 7) & (fb_clean['theme_zt_cnt_d1'] <= 12)],
        ">12只(超级主线井喷)": fb_clean[fb_clean['theme_zt_cnt_d1'] > 12]
    }
    results['ablations']['8_sector_echelon_count'] = {}
    for k, v in cond8.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['8_sector_echelon_count'][k] = m
        print(f"  {k:24s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # 9. 盘前公告过滤
    print("\n[Condition 9] Pre-Market Announcement Filtering (PIT cninfo notices)")
    cond9 = {
        "负向公告(减持/立案/问询/预亏)": fb_clean[fb_clean['has_neg_notice'] == 1],
        "中性无负向公告(纯技术/情绪)": fb_clean[(fb_clean['has_neg_notice'] == 0) & (fb_clean['has_pos_notice'] == 0)],
        "正向公告(重组/控制权/预增/中标)": fb_clean[fb_clean['has_pos_notice'] == 1]
    }
    results['ablations']['9_announcement_filtering'] = {}
    for k, v in cond9.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['9_announcement_filtering'][k] = m
        print(f"  {k:30s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # 10. 保护闸一：昨日一进二封板率 >75% (高潮次日)
    print("\n[Condition 10] Market Protection Gate 1: Yesterday's 1to2 Seal Rate")
    cond10 = {
        "<=75% (正常与冰点情绪)": fb_clean[fb_clean['gate1_prev_1to2_rate'] <= 0.75],
        ">75% (极度狂热亢奋高潮)": fb_clean[fb_clean['gate1_prev_1to2_rate'] > 0.75]
    }
    results['ablations']['10_market_gate_climax'] = {}
    for k, v in cond10.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['10_market_gate_climax'][k] = m
        print(f"  {k:26s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # 11. 保护闸二：09:25 昨日首板竞价均值 <0% (核按钮日)
    print("\n[Condition 11] Market Protection Gate 2: Today's 09:25 D1 Auction Mean Return")
    cond11 = {
        ">=0% (正常/溢价竞价)": fb_clean[fb_clean['gate2_mkt_open_mean'] >= 0.0],
        "<0% (核按钮踩踏恐慌日)": fb_clean[fb_clean['gate2_mkt_open_mean'] < 0.0]
    }
    results['ablations']['11_market_gate_nuclear_auction'] = {}
    for k, v in cond11.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['11_market_gate_nuclear_auction'][k] = m
        print(f"  {k:26s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # 12. 保护闸三：近 5 日一进二自然晋级率 <13% (冰点期)
    print("\n[Condition 12] Market Protection Gate 3: Rolling 5-Day 1to2 Seal Rate")
    cond12 = {
        ">=13% (活跃/中性行情)": fb_clean[fb_clean['gate3_roll5d_1to2_rate'] >= 0.13],
        "<13% (冰点极度低迷期)": fb_clean[fb_clean['gate3_roll5d_1to2_rate'] < 0.13]
    }
    results['ablations']['12_market_gate_ice_point'] = {}
    for k, v in cond12.items():
        m = compute_metrics(v)
        m['pct_of_total'] = round(len(v) / n_clean * 100, 2)
        results['ablations']['12_market_gate_ice_point'][k] = m
        print(f"  {k:26s} | N={m['N']:5d} ({m['pct_of_total']:4.1f}%) | 2B%: {m['seal_2b_rate']:5.2f}% | D3 Ret%: {m['d3_avg_net_ret']:+5.2f}% | 3B+%: {m['reach_3b_rate']:4.2f}% | Big Loss%: {m['big_loss_rate']:4.2f}% | W/L: {m['win_loss_ratio']}")

    # Save to JSON
    with open(JSON_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n>>> Results successfully written to: {JSON_OUTPUT}")

if __name__ == '__main__':
    run_ablation()

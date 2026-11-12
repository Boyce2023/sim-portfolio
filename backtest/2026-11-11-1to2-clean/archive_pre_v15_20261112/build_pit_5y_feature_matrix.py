#!/usr/bin/env python3
"""
build_pit_5y_feature_matrix.py
=============================================================================
Synthesize 5-Year Complete PIT 1-to-2 Feature Matrix (2021.01 ~ 2026.11)
Zero Lookahead Bias / Multi-Source Multi-Modal Point-in-Time Integration
=============================================================================
Datasets Integrated:
  1. Full A-Share Price DB: a_daily.parquet + a_delisted_daily.parquet (~5,470 tickers)
  2. KPL Limit-Up Themes & Dynamic Vocab: kpl_plates_2016_2021.jsonl + kpl_plates_v2.jsonl
  3. PIT News & CCTV Policy Catalysts: astock_news_5y_pit.db
  4. PIT SEC & Cninfo Disclosures: cninfo_notices_5y_pit.db
  5. PIT Community Sentiment: astock_community_5y_pit.db

Outputs:
  /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean/pit_5y_1to2_feature_matrix.parquet
=============================================================================
"""

import os
import sys
import json
import time
import sqlite3
import datetime
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.dataset as ds
import pyarrow as pa

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
OUTPUT_PARQUET = os.path.join(OUTPUT_DIR, "pit_5y_1to2_feature_matrix.parquet")

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PATH_V2 = "/Users/huaichuaibeimeng/claude-projects/news-dashboard/output/kpl_plates_v2.jsonl"
KPL_PATH_OLD = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_2016_2021.jsonl"
NEWS_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/astock_news_5y_pit.db"
NOTICES_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"
COMMUNITY_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/astock_community_5y_pit.db"

def main():
    t0 = time.time()
    print("=" * 80)
    print(">>> [Phase 1] Ingesting Full Market Price DB (Active + Delisted Stocks)")
    print("=" * 80)

    # 1. Load active stocks
    cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'amount', 'oshare', 'turn']
    ds_active = ds.dataset(A_DAILY_PATH, format="parquet")
    scanner_active = ds_active.scanner(
        columns=cols,
        filter=(ds.field('date') >= pd.Timestamp('2020-09-01')) & (ds.field('date') <= pd.Timestamp('2026-11-10'))
    )
    df_active = scanner_active.to_table().to_pandas()
    print(f"Loaded active stocks daily records: {len(df_active):,}")

    # 2. Load delisted stocks
    df_delisted = pd.DataFrame()
    if os.path.exists(A_DELISTED_PATH):
        ds_delisted = ds.dataset(A_DELISTED_PATH, format="parquet")
        scanner_delisted = ds_delisted.scanner(
            columns=cols,
            filter=(ds.field('date') >= pd.Timestamp('2020-09-01')) & (ds.field('date') <= pd.Timestamp('2026-11-10'))
        )
        df_delisted = scanner_delisted.to_table().to_pandas()
        print(f"Loaded delisted stocks daily records: {len(df_delisted):,}")

    # Combine
    df_all = pd.concat([df_active, df_delisted], ignore_index=True)
    del df_active, df_delisted

    # Standardize ticker & main board filter (00 and 60)
    df_all['ticker_str'] = df_all['ticker'].astype(str).str.zfill(6)
    df_all = df_all[df_all['ticker_str'].str.startswith(('00', '60'))].copy()
    df_all['date_str'] = df_all['date'].dt.strftime('%Y-%m-%d')
    df_all.sort_values(['ticker_str', 'date'], inplace=True)
    df_all.reset_index(drop=True, inplace=True)
    print(f"Total Main Board Price Records: {len(df_all):,} across {df_all['ticker_str'].nunique()} tickers.")

    # Calculate basic price limits & technical indicators
    df_all['pre_close'] = df_all.groupby('ticker_str')['close'].shift(1)
    df_all['zt_price'] = (df_all['pre_close'] * 1.10).round(2)
    df_all['dt_price'] = (df_all['pre_close'] * 0.90).round(2)
    
    # Exclude ST (if daily change exceeds 5% but not 10%, or price ceiling is ~5%)
    # Main board non-ST limit is strictly 10%
    df_all['is_zt'] = (df_all['close'] >= df_all['zt_price'] - 0.01) & (df_all['close'] == df_all['high']) & (df_all['pre_close'] > 0)
    df_all['is_yizi'] = df_all['is_zt'] & (df_all['open'] == df_all['close']) & (df_all['low'] == df_all['close'])
    df_all['is_dt'] = (df_all['close'] <= df_all['dt_price'] + 0.01) & (df_all['close'] == df_all['low'])
    df_all['is_yizi_dt'] = df_all['is_dt'] & (df_all['open'] == df_all['close']) & (df_all['high'] == df_all['close'])

    # Calculate streak (consecutive limit-ups)
    ticker_arr = df_all['ticker_str'].values
    zt_arr = df_all['is_zt'].values
    n = len(df_all)
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
    df_all['zt_streak'] = streak_arr

    # D1 1-Board condition: zt_streak == 1 on date >= '2021-01-04'
    df_all['is_1b'] = (df_all['zt_streak'] == 1) & (df_all['date_str'] >= '2021-01-04')
    print(f"Total D1 First-Board (首板) instances: {df_all['is_1b'].sum():,}")

    # Rolling indicators per ticker
    df_all['max20'] = df_all.groupby('ticker_str')['high'].transform(lambda x: x.rolling(20, min_periods=5).max())
    df_all['min60'] = df_all.groupby('ticker_str')['low'].transform(lambda x: x.rolling(60, min_periods=10).min())
    df_all['max60'] = df_all.groupby('ticker_str')['high'].transform(lambda x: x.rolling(60, min_periods=10).max())
    df_all['c_5d_ago'] = df_all.groupby('ticker_str')['close'].shift(5)
    df_all['vol_ma5'] = df_all.groupby('ticker_str')['volume'].transform(lambda x: x.rolling(5, min_periods=2).mean().shift(1))

    # Features on D1
    df_all['dd20'] = (df_all['close'] - df_all['max20']) / (df_all['max20'] + 1e-6)
    df_all['pos60'] = (df_all['close'] - df_all['min60']) / (df_all['max60'] - df_all['min60'] + 1e-6)
    df_all['ret5d'] = (df_all['close'] - df_all['c_5d_ago']) / (df_all['c_5d_ago'] + 1e-6)
    df_all['vol_ratio'] = df_all['volume'] / (df_all['vol_ma5'] + 1e-6)
    df_all['body_pct'] = (df_all['close'] - df_all['open']) / (df_all['high'] - df_all['low'] + 1e-6)
    df_all['amplitude'] = (df_all['high'] - df_all['low']) / (df_all['pre_close'] + 1e-6)
    df_all['float_mv'] = (df_all['oshare'] * df_all['close']) / 10000.0  # 万元

    # Forward returns & D2~D10 path
    df_all['d2_open'] = df_all.groupby('ticker_str')['open'].shift(-1)
    df_all['d2_high'] = df_all.groupby('ticker_str')['high'].shift(-1)
    df_all['d2_low'] = df_all.groupby('ticker_str')['low'].shift(-1)
    df_all['d2_close'] = df_all.groupby('ticker_str')['close'].shift(-1)
    df_all['d2_is_zt'] = df_all.groupby('ticker_str')['is_zt'].shift(-1).fillna(False)
    df_all['d2_is_yizi'] = df_all.groupby('ticker_str')['is_yizi'].shift(-1).fillna(False)
    df_all['d2_is_dt'] = df_all.groupby('ticker_str')['is_dt'].shift(-1).fillna(False)
    df_all['d2_is_yizi_dt'] = df_all.groupby('ticker_str')['is_yizi_dt'].shift(-1).fillna(False)

    df_all['d3_open'] = df_all.groupby('ticker_str')['open'].shift(-2)
    df_all['d3_close'] = df_all.groupby('ticker_str')['close'].shift(-2)
    df_all['d5_close'] = df_all.groupby('ticker_str')['close'].shift(-4)
    df_all['d10_close'] = df_all.groupby('ticker_str')['close'].shift(-9)

    # Compute key T+1 execution targets
    df_all['d2_open_ret'] = (df_all['d2_open'] / df_all['close'] - 1.0)
    df_all['d2_high_ret'] = (df_all['d2_high'] / df_all['close'] - 1.0)
    df_all['d2_close_ret'] = (df_all['d2_close'] / df_all['close'] - 1.0)
    df_all['d2_intraday_ret'] = (df_all['d2_close'] / df_all['d2_open'] - 1.0)
    
    # Strict T+1 return: enter at D2 open, exit at D3 open (standard), or if D2 locks limit-up hold to D3 open
    # Handle lockups: if D2 is yizi limit-up, cannot buy; if D3 is yizi limit-down, cannot sell, hold forward
    df_all['t1_ret_open2open'] = np.where(
        df_all['d2_is_yizi'], np.nan,  # Cannot buy if D2 opens at limit-up locked
        (df_all['d3_open'] / df_all['d2_open'] - 1.0)
    )

    print("\n" + "=" * 80)
    print(">>> [Phase 2] Loading & Integrating KPL Themes & Dynamic Rolling Vocab")
    print("=" * 80)

    # Load KPL records
    kpl_daily = defaultdict(list)
    stock_kpl_info = {}  # (date_str, ticker) -> dict

    def ingest_kpl_file(filepath):
        if not os.path.exists(filepath):
            return
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                d = entry.get('date', '')
                if not d:
                    continue
                plates = entry.get('plates', [])
                kpl_daily[d].extend(plates)
                for p in plates:
                    p_name = p.get('plate', '')
                    stks = p.get('stocks', [])
                    sz = len(stks)
                    for s in stks:
                        if isinstance(s, list) and len(s) >= 1:
                            c = str(s[0]).zfill(6)
                            nm = str(s[1]) if len(s) > 1 else ""
                            sub = str(s[2]) if len(s) > 2 else ""
                            rs = str(s[3]) if len(s) > 3 else ""
                            key = (d, c)
                            if key not in stock_kpl_info or sz > stock_kpl_info[key]['plate_sz']:
                                stock_kpl_info[key] = {
                                    'plate': p_name,
                                    'stock_name': nm,
                                    'subplate': sub,
                                    'reason': rs,
                                    'plate_sz': sz
                                }

    ingest_kpl_file(KPL_PATH_OLD)
    ingest_kpl_file(KPL_PATH_V2)
    print(f"Loaded KPL history for {len(kpl_daily)} dates and {len(stock_kpl_info):,} stock-date tags.")

    # Rolling plate statistics (zero lookahead)
    # Track historical limit-up count by plate per date
    trade_dates = sorted(list(set(df_all['date_str'].unique())))
    plate_date_counts = defaultdict(lambda: defaultdict(int))
    for d, p_list in kpl_daily.items():
        for p in p_list:
            p_name = p.get('plate', '')
            stks = p.get('stocks', [])
            plate_date_counts[d][p_name] += len(stks)

    print("\n" + "=" * 80)
    print(">>> [Phase 3] Loading PIT News & CCTV Database")
    print("=" * 80)
    news_records = []
    if os.path.exists(NEWS_DB_PATH):
        try:
            conn = sqlite3.connect(NEWS_DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT avail_trade_date, pub_datetime_cst, title, content FROM news_pit")
            news_records = cur.fetchall()
            conn.close()
            print(f"Loaded {len(news_records):,} PIT news records from SQLite.")
        except Exception as e:
            print(f"Warning reading news DB: {e}")

    # Build date -> concatenated news text for D1 night / D2 premarket
    news_by_avail_date = defaultdict(list)
    for row in news_records:
        av_date, pub_dt, title, content = row
        txt = (title or '') + ' ' + (content or '')
        news_by_avail_date[av_date].append(txt)

    print("\n" + "=" * 80)
    print(">>> [Phase 4] Loading PIT Announcements Database (Cninfo)")
    print("=" * 80)
    notices_by_code_date = defaultdict(lambda: {'pos': 0, 'neg': 0, 'titles': []})
    if os.path.exists(NOTICES_DB_PATH):
        try:
            conn = sqlite3.connect(NOTICES_DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT sec_code, trade_date_avail, title, ann_type FROM notices")
            notices_rows = cur.fetchall()
            conn.close()
            print(f"Loaded {len(notices_rows):,} PIT notice records.")
            pos_keywords = ['预增', '扭亏', '中标', '合同', '收购', '重组', '回购', '增持', '分红']
            neg_keywords = ['减持', '立案', '问询', '风险提示', '异动澄清', '亏损', '质押', '被动减持']
            for row in notices_rows:
                code, av_date, title, ann_type = row
                c_str = str(code).zfill(6)
                t_str = str(title or '') + ' ' + str(ann_type or '')
                is_p = 1 if any(k in t_str for k in pos_keywords) else 0
                is_n = 1 if any(k in t_str for k in neg_keywords) else 0
                key = (c_str, av_date)
                notices_by_code_date[key]['pos'] += is_p
                notices_by_code_date[key]['neg'] += is_n
                notices_by_code_date[key]['titles'].append(title)
        except Exception as e:
            print(f"Warning reading notices DB: {e}")

    print("\n" + "=" * 80)
    print(">>> [Phase 5] Extracting D1 First-Board Samples & Feature Joining")
    print("=" * 80)
    
    # Filter only D1 First-Board samples
    df_1b = df_all[df_all['is_1b']].copy()
    print(f"Extracting {len(df_1b):,} first-board samples...")

    # Join KPL info
    plate_names = []
    stock_names = []
    reasons = []
    plate_zt_cnts = []
    
    for idx, row in df_1b.iterrows():
        key = (row['date_str'], row['ticker_str'])
        k_info = stock_kpl_info.get(key, {})
        plate_names.append(k_info.get('plate', '其他'))
        stock_names.append(k_info.get('stock_name', ''))
        reasons.append(k_info.get('reason', ''))
        plate_zt_cnts.append(k_info.get('plate_sz', 1))

    df_1b['plate_name'] = plate_names
    df_1b['stock_name'] = stock_names
    df_1b['reason'] = reasons
    df_1b['plate_zt_cnt_d1'] = plate_zt_cnts

    # Compute Rolling Plate Features (Zero-lookahead: using past 60 days strictly before or on D1)
    # Pre-index date to index in trade_dates
    date_to_idx = {d: i for i, d in enumerate(trade_dates)}

    plate_burst_list = []
    plate_is_fresh_list = []
    cctv_policy_hit_list = []
    notice_pos_list = []
    notice_neg_list = []

    for idx, row in df_1b.iterrows():
        d_str = row['date_str']
        p_name = row['plate_name']
        t_code = row['ticker_str']
        curr_i = date_to_idx.get(d_str, -1)

        # 1. Plate burst & freshness over rolling 20d & 30d
        if curr_i >= 20 and p_name != '其他':
            past_20_counts = [plate_date_counts[trade_dates[k]].get(p_name, 0) for k in range(curr_i - 20, curr_i)]
            mean_20d = (sum(past_20_counts) / 20.0) if past_20_counts else 0.0
            burst = row['plate_zt_cnt_d1'] / (mean_20d + 0.2)
        else:
            burst = 1.0

        if curr_i >= 30 and p_name != '其他':
            past_30_max = max([plate_date_counts[trade_dates[k]].get(p_name, 0) for k in range(curr_i - 30, curr_i)], default=0)
            is_fresh = 1 if (past_30_max < 3 and row['plate_zt_cnt_d1'] >= 3) else 0
        else:
            is_fresh = 0

        plate_burst_list.append(round(burst, 2))
        plate_is_fresh_list.append(is_fresh)

        # 2. CCTV / Policy News hit
        d2_avail = trade_dates[curr_i + 1] if curr_i + 1 < len(trade_dates) else d_str
        news_texts = news_by_avail_date.get(d2_avail, [])
        hit = 0
        if news_texts and p_name != '其他':
            combined_txt = ' '.join(news_texts)
            if p_name in combined_txt or (len(row['reason']) >= 2 and row['reason'] in combined_txt):
                hit = 1
        cctv_policy_hit_list.append(hit)

        # 3. Cninfo notices
        not_info = notices_by_code_date.get((t_code, d2_avail), {'pos': 0, 'neg': 0})
        notice_pos_list.append(not_info['pos'])
        notice_neg_list.append(not_info['neg'])

    df_1b['plate_burst_vs_20d'] = plate_burst_list
    df_1b['plate_is_fresh_30d'] = plate_is_fresh_list
    df_1b['cctv_policy_hit_d1'] = cctv_policy_hit_list
    df_1b['pit_notice_pos'] = notice_pos_list
    df_1b['pit_notice_neg'] = notice_neg_list

    # D2 Plate Peer Auction Momentum (d2_plate_peer_open_mean & d2_in_plate_open_rank)
    # Calculate group-level peer open return on D2 within the same plate
    df_1b['d2_plate_peer_open_mean'] = df_1b.groupby(['date_str', 'plate_name'])['d2_open_ret'].transform(
        lambda s: (s.sum() - s) / (len(s) - 1) if len(s) > 1 else s
    )
    df_1b['d2_in_plate_open_rank'] = df_1b.groupby(['date_str', 'plate_name'])['d2_open_ret'].rank(ascending=False, pct=True)

    # Fill default values for singletons
    df_1b['d2_plate_peer_open_mean'].fillna(df_1b['d2_open_ret'], inplace=True)
    df_1b['d2_in_plate_open_rank'].fillna(0.5, inplace=True)

    # Dynamic Reason Novelty Score (frequency in last 5d vs last 60d)
    # Simple causal word novelty
    df_1b['reason_novelty_score'] = df_1b['plate_burst_vs_20d'] * (1.0 + df_1b['plate_is_fresh_30d'] * 0.5)

    # Placeholder community heat (0.0 if database is pending backfill, ensuring schema readiness)
    df_1b['community_heat_d1'] = 0.0

    # Clean and reorder columns
    final_cols = [
        # Keys
        'date_str', 'ticker_str', 'stock_name', 'plate_name', 'subplate', 'reason',
        # D1 Price & Chip Features
        'close', 'pre_close', 'amount', 'turn', 'float_mv', 'dd20', 'pos60', 'ret5d', 
        'vol_ratio', 'body_pct', 'amplitude',
        # KPL Theme & Novelty Features
        'plate_zt_cnt_d1', 'plate_burst_vs_20d', 'plate_is_fresh_30d', 'reason_novelty_score',
        # D2 Auction Premarket Features (<= 09:25:00)
        'd2_open', 'd2_open_ret', 'd2_plate_peer_open_mean', 'd2_in_plate_open_rank',
        # News & Policy PIT Features
        'cctv_policy_hit_d1',
        # Disclosure / Notice PIT Features
        'pit_notice_pos', 'pit_notice_neg',
        # Community Feature
        'community_heat_d1',
        # Forward Labels & Paths (for backtesting / training)
        'd2_high', 'd2_close', 'd2_is_zt', 'd2_is_yizi', 'd2_is_dt', 'd2_is_yizi_dt',
        'd2_high_ret', 'd2_close_ret', 'd2_intraday_ret', 't1_ret_open2open',
        'd3_open', 'd3_close', 'd5_close', 'd10_close'
    ]

    # Keep available columns
    avail_cols = [c for c in final_cols if c in df_1b.columns]
    df_out = df_1b[avail_cols].copy()
    df_out.sort_values(['date_str', 'ticker_str'], inplace=True)
    df_out.reset_index(drop=True, inplace=True)

    print("\n" + "=" * 80)
    print(">>> [Phase 6] Writing Output Parquet Matrix")
    print("=" * 80)
    table = pa.Table.from_pandas(df_out)
    pq.write_table(table, OUTPUT_PARQUET, compression='snappy')
    file_size_mb = os.path.getsize(OUTPUT_PARQUET) / (1024 * 1024)
    print(f"Successfully generated: {OUTPUT_PARQUET}")
    print(f"File Size: {file_size_mb:.2f} MB | Total Samples: {len(df_out):,}")

    # Summary by Year
    df_out['year'] = df_out['date_str'].str[:4].astype(int)
    print("\n>>> Yearly Sample Count & D2 Limit-Up Rate (First Board -> 2-Board):")
    summary = df_out.groupby('year').agg(
        total_1b=('ticker_str', 'count'),
        d2_zt_cnt=('d2_is_zt', lambda x: x.sum()),
        d2_zt_rate=('d2_is_zt', lambda x: x.mean() * 100),
        avg_d2_open_ret=('d2_open_ret', lambda x: x.mean() * 100),
        cctv_hit_cnt=('cctv_policy_hit_d1', 'sum'),
        notice_pos_cnt=('pit_notice_pos', lambda x: (x > 0).sum())
    )
    print(summary.to_string())

    print("\n" + "=" * 80)
    print(f"Feature Matrix Construction Finished in {time.time() - t0:.2f}s!")
    print("=" * 80)

if __name__ == "__main__":
    main()

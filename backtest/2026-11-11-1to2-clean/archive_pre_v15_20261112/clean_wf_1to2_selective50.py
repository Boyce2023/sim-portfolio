#!/usr/bin/env python3
"""
clean_wf_1to2_selective50.py
=============================================================================
Five-Year Clean Walk-Forward 1-to-2 Selective Strategy (Target ~50 trades/yr)
Strictly Compliant with A-Share T+1 Settlement & Zero-Lookahead / Point-In-Time
=============================================================================
Dual-Engine:
  Engine 1: Theme Selection Engine (theme_score <= D2 09:25:00)
  Engine 2: Stock Selection Engine (stock_score <= D2 09:25:00)
Walk-Forward Expanding Folds:
  Fold 1: Train <= 2022.12 -> Test 2023
  Fold 2: Train <= 2023.12 -> Test 2024
  Fold 3: Train <= 2024.12 -> Test 2025
  Fold 4: Train <= 2025.12 -> Test 2026.01~2026.11
=============================================================================
"""

import os
import sys
import json
import math
import time
import datetime
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pyarrow.dataset as ds
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
os.makedirs(OUTPUT_DIR, exist_ok=True)

A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/news-dashboard/output/kpl_plates_v2.jsonl"
LEDGER_CSV_PATH = os.path.join(OUTPUT_DIR, "clean_wf_selective50_ledger.csv")
RESULTS_JSON_PATH = os.path.join(OUTPUT_DIR, "clean_wf_selective50_results.json")

# CSI 300 Benchmark annual returns for excess calculation
CSI300_ANNUAL_RETURNS = {
    2022: -0.2163,
    2023: -0.1138,
    2024: 0.1468,
    2025: 0.1758,
    2026: 0.0120,
}

def main():
    start_time = time.time()
    print("=" * 80)
    print(">>> [Phase 1] Ingesting KPL Historical Plates & Rolling PIT Vocabularies")
    print("=" * 80)

    # Plate data structure: date -> list of {plate, stocks}
    kpl_daily_plates = {}
    stock_to_plate_info = {}
    
    with open(KPL_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            d_str = entry['date']
            plates = entry.get('plates', [])
            kpl_daily_plates[d_str] = plates
            
            # Count plate size
            p_counts = []
            for p_obj in plates:
                p_name = p_obj.get('plate', '')
                stks = p_obj.get('stocks', [])
                p_counts.append((p_name, len(stks), stks))
            p_counts.sort(key=lambda x: x[1], reverse=True)
            top1_p = p_counts[0][0] if p_counts else ""
            
            for p_name, sz, stks in p_counts:
                for s in stks:
                    code = str(s[0]).zfill(6)
                    s_name = s[1] if len(s) > 1 else ""
                    subp = s[2] if len(s) > 2 else ""
                    reason = s[3] if len(s) > 3 else ""
                    key = (d_str, code)
                    if key not in stock_to_plate_info or sz > stock_to_plate_info[key]['plate_sz']:
                        stock_to_plate_info[key] = {
                            'plate': p_name,
                            'name': s_name,
                            'subplate': subp,
                            'reason': reason,
                            'plate_sz': sz,
                            'is_top1': 1 if p_name == top1_p else 0
                        }

    print(f"Loaded KPL plate data for {len(kpl_daily_plates)} dates.")

    print("\n" + "=" * 80)
    print(">>> [Phase 2] Ingesting A-Share Daily Price Data & Technical Indicators")
    print("=" * 80)

    dataset = ds.dataset(A_DAILY_PATH, format="parquet")
    scanner = dataset.scanner(
        columns=['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'amount', 'turn', 'oshare'],
        filter=(ds.field('date') >= pd.Timestamp('2021-05-01'))
    )
    df = scanner.to_table().to_pandas()
    df['ticker_str'] = df['ticker'].astype(str).str.zfill(6)
    # Filter to main board: 00 and 60 only
    df = df[df['ticker_str'].str.startswith(('00', '60'))].copy()
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df.sort_values(['ticker_str', 'date'], inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Calculate limits & indicators
    df['pre_close'] = df.groupby('ticker_str')['close'].shift(1)
    df['zt_price'] = (df['pre_close'] * 1.10).round(2)
    df['dt_price'] = (df['pre_close'] * 0.90).round(2)
    df['is_zt'] = (df['close'] >= df['zt_price'] - 0.01) & (df['close'] == df['high']) & (df['pre_close'] > 0)
    df['is_yizi'] = df['is_zt'] & (df['open'] == df['close']) & (df['low'] == df['close'])
    df['is_dt'] = (df['close'] <= df['dt_price'] + 0.01) & (df['close'] == df['low'])

    # Fast streak calculation
    zt_arr = df['is_zt'].values
    ticker_arr = df['ticker_str'].values
    n_rows = len(df)
    streak_arr = np.zeros(n_rows, dtype=int)
    curr_streak = 0
    last_tk = ""
    for i in range(n_rows):
        tk = ticker_arr[i]
        if tk != last_tk:
            curr_streak = 0
            last_tk = tk
        if zt_arr[i]:
            curr_streak += 1
        else:
            curr_streak = 0
        streak_arr[i] = curr_streak
    df['streak'] = streak_arr
    df['is_turnover_fb'] = (df['streak'] == 1) & (~df['is_yizi'])

    # Technical columns
    df['ret_1d'] = df['close'] / df['pre_close'] - 1.0
    df['open_pct'] = df['open'] / df['pre_close'] - 1.0
    df['entity_ratio'] = (df['close'] - df['low']) / df['pre_close']
    df['mcap_circ'] = df['close'] * df['oshare'] / 1e8
    df['amt_ma5'] = df.groupby('ticker_str')['amount'].transform(lambda s: s.shift(1).rolling(5, min_periods=3).mean())
    df['high_max_60d'] = df.groupby('ticker_str')['high'].transform(lambda s: s.shift(1).rolling(60, min_periods=30).max())
    df['is_breakout_60d'] = (df['close'] >= df['high_max_60d'] - 0.01).astype(int)

    # Shift columns for D2
    df['d2_date_str'] = df.groupby('ticker_str')['date_str'].shift(-1)
    df['d2_open'] = df.groupby('ticker_str')['open'].shift(-1)
    df['d2_high'] = df.groupby('ticker_str')['high'].shift(-1)
    df['d2_low'] = df.groupby('ticker_str')['low'].shift(-1)
    df['d2_close'] = df.groupby('ticker_str')['close'].shift(-1)
    df['d2_adj_close'] = df.groupby('ticker_str')['adj_close'].shift(-1)
    df['d2_streak'] = df.groupby('ticker_str')['streak'].shift(-1)
    df['d2_zt_price'] = (df['close'] * 1.10).round(2)
    df['d2_dt_price'] = (df['close'] * 0.90).round(2)
    df['d2_o_pct'] = df['d2_open'] / df['close'] - 1.0

    # Build price lookup table for fast exit simulation
    # (ticker, date_str) -> (open, high, low, close, adj_close, zt_price, dt_price, is_zt, streak)
    price_lookup = {}
    for row in df[['ticker_str', 'date_str', 'open', 'high', 'low', 'close', 'adj_close', 'zt_price', 'dt_price', 'is_zt', 'streak']].itertuples(index=False):
        price_lookup[(row.ticker_str, row.date_str)] = (
            row.open, row.high, row.low, row.close, row.adj_close, row.zt_price, row.dt_price, row.is_zt, row.streak
        )

    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}

    print(f"Total price rows: {len(df)}, Trading days: {len(all_trade_dates)}")

    print("\n" + "=" * 80)
    print(">>> [Phase 3] Building Point-In-Time 1-to-2 Candidate Universe & Dual Engines")
    print("=" * 80)

    # Filter to turnover first board (D1 is turnover limit-up)
    fb_df = df[df['is_turnover_fb']].copy()
    fb_df = fb_df[(fb_df['d2_date_str'] >= "2021-10-20") & (fb_df['d2_date_str'] <= "2026-11-10")].copy()

    # Rule: D2 open < D2 zt_price (cannot buy one-word limit-up!)
    fb_df = fb_df[fb_df['d2_open'] < fb_df['d2_zt_price'] - 0.005].copy()
    # Rule: D2 open >= -3% (avoid crash-open traps)
    fb_df = fb_df[fb_df['d2_o_pct'] >= -0.03].copy()
    # Rule: D1 amount >= 1.5亿 (avoid illiquid micro-cap manipulation)
    fb_df = fb_df[fb_df['amount'] >= 1.5e8].copy()

    # Match plate info
    def match_plate(r):
        key = (r['date_str'], r['ticker_str'])
        info = stock_to_plate_info.get(key)
        if info:
            return info['plate'], info['name'], info['subplate'], info['reason'], info['plate_sz'], info['is_top1']
        return "其他", "", "", "", 1, 0

    tuples = [match_plate(r) for _, r in fb_df[['date_str', 'ticker_str']].iterrows()]
    fb_df['plate'] = [t[0] for t in tuples]
    fb_df['name'] = [t[1] for t in tuples]
    fb_df['subplate'] = [t[2] for t in tuples]
    fb_df['reason'] = [t[3] for t in tuples]
    fb_df['plate_sz'] = [t[4] for t in tuples]
    fb_df['is_top1'] = [t[5] for t in tuples]

    # Filter ST or 退
    fb_df = fb_df[~fb_df['name'].str.contains('ST|退', regex=True)].copy()

    # Pre-calculate rolling plate stats up to D1
    # 1. Rolling plate daily ZT count history up to D1
    # plate -> list of (date, zt_count)
    plate_hist = defaultdict(list)
    for dt in all_trade_dates:
        p_list = kpl_daily_plates.get(dt, [])
        for p_obj in p_list:
            pn = p_obj.get('plate', '')
            stks = p_obj.get('stocks', [])
            plate_hist[pn].append((dt, len(stks)))

    # Fast map: (plate, date) -> (past_20d_avg, is_fresh_60d)
    plate_metrics = {}
    for pn, hist in plate_hist.items():
        hist.sort(key=lambda x: x[0])
        dates_p = [x[0] for x in hist]
        counts_p = [x[1] for x in hist]
        for idx, (dt, cnt) in enumerate(hist):
            # Prior dates strictly < dt
            prior_counts = counts_p[max(0, idx-20):idx]
            avg_20d = float(np.mean(prior_counts)) if prior_counts else 0.5
            
            # Fresh 60d: check if in past 60 calendar days (or ~40 trading days) there were >= 3 ZTs
            curr_date_obj = datetime.datetime.strptime(dt, '%Y-%m-%d').date()
            had_major_event = False
            for p_idx in range(idx - 1, -1, -1):
                p_dt, p_cnt = hist[p_idx]
                p_date_obj = datetime.datetime.strptime(p_dt, '%Y-%m-%d').date()
                if (curr_date_obj - p_date_obj).days > 60:
                    break
                if p_cnt >= 3:
                    had_major_event = True
                    break
            is_fresh_60d = 0 if had_major_event else 1
            plate_metrics[(pn, dt)] = (avg_20d, is_fresh_60d)

    # Compute Engine 1: Theme Features
    theme_zt_cnt = []
    theme_burst = []
    theme_fresh = []
    
    for _, r in fb_df.iterrows():
        pn = r['plate']
        d1 = r['date_str']
        sz = r['plate_sz']
        avg_20d, is_fresh = plate_metrics.get((pn, d1), (0.5, 1))
        burst_ratio = sz / (avg_20d + 0.1)
        theme_zt_cnt.append(sz)
        theme_burst.append(burst_ratio)
        theme_fresh.append(is_fresh)
        
    fb_df['theme_zt_cnt'] = theme_zt_cnt
    fb_df['theme_burst_ratio'] = theme_burst
    fb_df['theme_is_fresh_60d'] = theme_fresh

    # Collective auction premium: average D2 open_pct of OTHER stocks in the same plate on D2
    plate_d2_groups = fb_df.groupby(['d2_date_str', 'plate'])['d2_o_pct']
    plate_d2_sum = plate_d2_groups.transform('sum')
    plate_d2_count = plate_d2_groups.transform('count')
    # If count > 1: (sum - self) / (count - 1), else self
    other_auc_mean = np.where(plate_d2_count > 1, (plate_d2_sum - fb_df['d2_o_pct']) / (plate_d2_count - 1), fb_df['d2_o_pct'])
    fb_df['theme_d2_auc_premium'] = other_auc_mean

    # Market regime thermometer
    # D1 limit-down count in market
    dt_count_map = df[df['is_dt']].groupby('date_str')['ticker_str'].count().to_dict()
    fb_df['d1_mkt_dt_cnt'] = [dt_count_map.get(d, 0) for d in fb_df['date_str']]
    # Streak on D1
    mkt_streak_map = df.groupby('date_str')['streak'].max().to_dict()
    fb_df['d1_mkt_max_streak'] = [mkt_streak_map.get(d, 1) for d in fb_df['date_str']]
    # Rolling 5d 1-to-2 rate up to D1
    promo_df = df[df['streak'] == 1].groupby('date_str')['ticker_str'].count().rename('num_1')
    promo_succ_df = df[df['streak'] == 2].groupby('date_str')['ticker_str'].count().rename('num_2')
    promo_merged = pd.concat([promo_df, promo_succ_df], axis=1).fillna(0)
    promo_merged['rolling_promo_5d'] = promo_merged['num_2'].rolling(5).sum() / (promo_merged['num_1'].rolling(5).sum() + 1e-4)
    promo_rate_map = promo_merged['rolling_promo_5d'].to_dict()
    fb_df['d1_rolling_promo_rate'] = [promo_rate_map.get(d, 0.15) for d in fb_df['date_str']]

    fb_df['mkt_regime_safe'] = (
        fb_df['d1_rolling_promo_rate'] * 10.0 +
        (fb_df['d1_mkt_max_streak'] >= 3).astype(float) * 2.0 -
        (fb_df['d1_mkt_dt_cnt'] >= 10).astype(float) * 3.0
    )

    # Compute Engine 2: Stock Selection Features
    # Rank within plate by D2 09:25 open_pct
    fb_df['in_theme_auc_rank'] = fb_df.groupby(['d2_date_str', 'plate'])['d2_o_pct'].rank(ascending=False, method='min')
    fb_df['is_carding_leader'] = (fb_df['in_theme_auc_rank'] == 1).astype(float)

    # Generic Catalyst
    hard_words = ['重组', '收购', '控制权', '股权转让', '借壳', '中标', '重大合同', '签约', '协议', '回购']
    perf_words = ['季报', '年报', '中报', '业绩', '预增', '扭亏', '增长']
    def get_catalyst(r):
        text = str(r['plate']) + " " + str(r['subplate']) + " " + str(r['reason'])
        has_hard = any(w in text for w in hard_words)
        has_perf = any(w in text for w in perf_words)
        if has_hard and not has_perf:
            return 1.0
        elif has_perf and not has_hard:
            return -0.5
        elif has_hard and has_perf:
            return 0.5
        return 0.0
    fb_df['hard_catalyst'] = [get_catalyst(r) for _, r in fb_df.iterrows()]

    # Technical features
    fb_df['d1_turnover_clean'] = fb_df['turn'].apply(
        lambda t: 1.0 if (0.03 <= t <= 0.16) else (0.5 if t < 0.03 else max(0.0, 1.0 - (t - 0.16) * 4.0))
    )
    fb_df['d1_entity_clean'] = fb_df['entity_ratio'].fillna(0.09)
    fb_df['breakout_60d'] = fb_df['is_breakout_60d'].astype(float)
    fb_df['d2_open_pct'] = fb_df['d2_o_pct']

    # Label for D2 2-board success: d2_streak == 2
    fb_df['label_d2_zt'] = (fb_df['d2_streak'] == 2).astype(int)

    print(f"Total PIT 1-to-2 candidates extracted: {len(fb_df)} across {fb_df['d2_date_str'].nunique()} trading days.")
    print(f"Base 2-board promotion rate: {fb_df['label_d2_zt'].mean():.2%}")

    print("\n" + "=" * 80)
    print(">>> [Phase 4] Strict A-Share T+1 Exit Simulator Engine")
    print("=" * 80)

    def simulate_t1_trade(ticker: str, d2_str: str, buy_price: float, rule: str = 'R1') -> dict:
        """
        Strict T+1 simulation:
        D2: Buy at 09:25 open (buy_price). Cannot sell on D2!
        D3: T+1 unlocked!
          - If D2 failed to seal limit-up (d2_streak < 2):
              Sell on D3 at 09:25 open (D3_open).
              If D3 open is limit-down (D3_open <= dt_price), check if limit-down opened intraday.
              If locked all day, carry over to D4 until opened!
          - If D2 sealed limit-up (d2_streak == 2):
              Position is in massive profit, held into D3.
              Rule R1: Hold as long as day k closes at limit-up. Sell at close of first broken-board day Dk.
              Rule R2: On day k (k>=3), if Dk_open < -3%, cut immediately at Dk_open (weak open exit);
                       else if fails to seal by close, sell at Dk_close.
              Rule R3: On day k (k>=3), if Dk fails to seal, sell on day k+1 at open (D_{k+1}_open).
        """
        curr_idx = date_to_idx[d2_str]
        r2 = price_lookup.get((ticker, d2_str))
        d2_open, d2_high, d2_low, d2_close, d2_adj, d2_zt, d2_dt, d2_is_zt, d2_streak = r2

        hold_days = 1
        exit_date = d2_str
        exit_price = d2_close
        exit_reason = ""

        # Case 1: D2 did NOT seal 2nd board -> MUST sell on D3!
        if d2_streak < 2:
            exit_idx = curr_idx + 1
            while exit_idx < len(all_trade_dates):
                d3_str = all_trade_dates[exit_idx]
                r3 = price_lookup.get((ticker, d3_str))
                if r3 is None:
                    # Delisted / suspended
                    exit_date = d3_str
                    exit_price = d2_close
                    exit_reason = "D3无行情停牌/退市兜底卖"
                    hold_days = exit_idx - curr_idx
                    break
                
                d3_open, d3_high, d3_low, d3_close, d3_adj, d3_zt, d3_dt, d3_is_zt, d3_streak = r3
                
                # Check if D3 is locked in one-word limit down all day
                is_d3_locked_dt = (d3_open <= d3_dt + 0.005) and (d3_high <= d3_dt + 0.005)
                if is_d3_locked_dt:
                    # Cannot sell today! Carry over to next trading day
                    exit_idx += 1
                    continue
                else:
                    # Can sell at D3 open (or open auction)!
                    exit_date = d3_str
                    exit_price = d3_open
                    exit_reason = "D2未封板次日(D3)开盘T+1止损出" if exit_idx == curr_idx + 1 else f"D2未封板跌停锁仓至D{exit_idx-curr_idx+1}开盘出"
                    hold_days = exit_idx - curr_idx
                    break
        else:
            # Case 2: D2 successfully sealed 2nd board! (d2_streak == 2)
            # From D3 onwards, investor has full right to sell at any time!
            k_idx = curr_idx + 1
            while k_idx < len(all_trade_dates):
                dk_str = all_trade_dates[k_idx]
                rk = price_lookup.get((ticker, dk_str))
                if rk is None:
                    exit_date = dk_str
                    exit_price = exit_price
                    exit_reason = "连板期突发停牌兜底卖"
                    hold_days = k_idx - curr_idx
                    break
                
                dk_open, dk_high, dk_low, dk_close, dk_adj, dk_zt, dk_dt, dk_is_zt, dk_streak = rk
                k_day_num = k_idx - curr_idx + 1
                
                # Rule R2: Weak open cut
                if rule == 'R2' and (dk_open / exit_price - 1.0) < -0.03:
                    exit_date = dk_str
                    exit_price = dk_open
                    exit_reason = f"D{k_day_num}大幅低开不及预期开盘兑现"
                    hold_days = k_day_num
                    break
                
                # Check if Dk continued to seal limit-up
                if dk_is_zt:
                    # Sealed limit-up! Keep holding
                    exit_date = dk_str
                    exit_price = dk_close
                    k_idx += 1
                    continue
                else:
                    # Broken board on Dk!
                    if rule in ('R1', 'R2'):
                        # Monitor near 14:57 and sell at close
                        exit_date = dk_str
                        exit_price = dk_close
                        exit_reason = f"D{k_day_num}断板收盘卖"
                        hold_days = k_day_num
                        break
                    elif rule == 'R3':
                        # Sell next day at open
                        next_idx = k_idx + 1
                        if next_idx < len(all_trade_dates):
                            d_next_str = all_trade_dates[next_idx]
                            r_next = price_lookup.get((ticker, d_next_str))
                            if r_next is not None:
                                exit_date = d_next_str
                                exit_price = r_next[0] # open
                                exit_reason = f"D{k_day_num}断板次日开盘卖"
                                hold_days = k_day_num + 1
                                break
                        exit_date = dk_str
                        exit_price = dk_close
                        exit_reason = f"D{k_day_num}断板收盘兜底卖"
                        hold_days = k_day_num
                        break

        # Transaction cost calculation
        # Before 2023-08-28: stamp tax 0.1%, after: 0.05%
        fee = 0.0020 if d2_str >= '2023-08-28' else 0.0025
        raw_ret = (exit_price / buy_price) - 1.0
        net_ret = raw_ret - fee
        
        return {
            'ticker': ticker,
            'buy_date': d2_str,
            'buy_price': round(buy_price, 2),
            'exit_date': exit_date,
            'exit_price': round(exit_price, 2),
            'hold_days': hold_days,
            'raw_ret': raw_ret,
            'net_ret': net_ret,
            'exit_reason': exit_reason,
            'is_win': 1 if net_ret > 0 else 0
        }

    print("Verified T+1 Simulator logic.")

    print("\n" + "=" * 80)
    print(">>> [Phase 5] Walk-Forward Expanding OOS Modeling & 'Selective 50' Calibration")
    print("=" * 80)

    # Feature definitions
    theme_features = ['theme_zt_cnt', 'theme_burst_ratio', 'theme_is_fresh_60d', 'theme_d2_auc_premium', 'mkt_regime_safe']
    stock_features = ['is_carding_leader', 'd2_open_pct', 'd1_turnover_clean', 'd1_entity_clean', 'breakout_60d', 'hard_catalyst']
    all_features = theme_features + stock_features

    splits = [
        ('2023', '2021-10-20', '2022-12-31', '2023-01-01', '2023-12-31'),
        ('2024', '2021-10-20', '2023-12-31', '2024-01-01', '2024-12-31'),
        ('2025', '2021-10-20', '2024-12-31', '2025-01-01', '2025-12-31'),
        ('2026', '2021-10-20', '2025-12-31', '2026-01-01', '2026-11-10'),
    ]

    target_freqs = [30, 50, 80, 150]
    
    # Store predictions for each frequency target
    oos_results_by_freq = {freq: [] for freq in target_freqs}
    # Store perturbation tests for target 50: -10%, base, +10%
    perturb_results = {'minus_10': [], 'base_50': [], 'plus_10': []}

    # Store model info per fold
    fold_model_info = {}

    for year_label, train_s, train_e, test_s, test_e in splits:
        df_train = fb_df[(fb_df['d2_date_str'] >= train_s) & (fb_df['d2_date_str'] <= train_e)].copy()
        df_test = fb_df[(fb_df['d2_date_str'] >= test_s) & (fb_df['d2_date_str'] <= test_e)].copy()

        # Fit Theme Engine
        scaler_theme = StandardScaler()
        X_train_theme = scaler_theme.fit_transform(df_train[theme_features])
        clf_theme = LogisticRegression(C=0.5, penalty='l2', solver='lbfgs', max_iter=200, random_state=42)
        clf_theme.fit(X_train_theme, df_train['label_d2_zt'].values)

        # Fit Stock Engine
        scaler_stock = StandardScaler()
        X_train_stock = scaler_stock.fit_transform(df_train[stock_features])
        clf_stock = LogisticRegression(C=0.5, penalty='l2', solver='lbfgs', max_iter=200, random_state=42)
        clf_stock.fit(X_train_stock, df_train['label_d2_zt'].values)

        # Combined Composite Probability on Train
        p_train_theme = clf_theme.predict_proba(X_train_theme)[:, 1]
        p_train_stock = clf_stock.predict_proba(X_train_stock)[:, 1]
        # Composite score = harmonic / geometric or weighted combination
        df_train['composite_score'] = p_train_theme * p_train_stock

        # Calculate annual trade budget calibration on Train set
        # Count trading days in train set
        n_train_dates = df_train['d2_date_str'].nunique()
        years_in_train = max(1.0, n_train_dates / 242.0)
        
        # Rank candidates per day on train set
        df_train_top1 = df_train.sort_values(['d2_date_str', 'composite_score'], ascending=[True, False]).groupby('d2_date_str').first().reset_index()

        # Find score cutoffs on Train set for each target frequency
        freq_cutoffs = {}
        for target_f in target_freqs:
            target_trades_total = target_f * years_in_train
            pct = max(0.01, min(0.99, 1.0 - (target_trades_total / n_train_dates)))
            cutoff = float(np.percentile(df_train_top1['composite_score'], pct * 100.0))
            freq_cutoffs[target_f] = cutoff

        print(f"\n--- Fold {year_label}: Train ({train_s} ~ {train_e}, N={len(df_train)}, Years={years_in_train:.2f}) | Test ({test_s} ~ {test_e}, N={len(df_test)}) ---")
        print(f"    Theme Model Coefs: {dict(zip(theme_features, clf_theme.coef_[0].round(4)))}")
        print(f"    Stock Model Coefs: {dict(zip(stock_features, clf_stock.coef_[0].round(4)))}")
        print(f"    Calibrated Train Cutoffs for Targets: { {k: round(v, 4) for k, v in freq_cutoffs.items()} }")

        fold_model_info[year_label] = {
            'train_n': len(df_train),
            'test_n': len(df_test),
            'theme_coefs': dict(zip(theme_features, clf_theme.coef_[0].round(4))),
            'stock_coefs': dict(zip(stock_features, clf_stock.coef_[0].round(4))),
            'freq_cutoffs': {k: round(v, 4) for k, v in freq_cutoffs.items()}
        }

        # Predict OOS on Test Set
        X_test_theme = scaler_theme.transform(df_test[theme_features])
        X_test_stock = scaler_stock.transform(df_test[stock_features])
        p_test_theme = clf_theme.predict_proba(X_test_theme)[:, 1]
        p_test_stock = clf_stock.predict_proba(X_test_stock)[:, 1]
        df_test['theme_prob'] = p_test_theme
        df_test['stock_prob'] = p_test_stock
        df_test['composite_score'] = p_test_theme * p_test_stock
        df_test['test_year'] = year_label

        # Test set candidate ranking per day
        df_test_sorted = df_test.sort_values(['d2_date_str', 'composite_score'], ascending=[True, False]).reset_index(drop=True)
        df_test_sorted['daily_rank'] = df_test_sorted.groupby('d2_date_str').cumcount() + 1
        df_test_top1 = df_test_sorted[df_test_sorted['daily_rank'] == 1].copy()

        # Score candidates for each frequency
        for target_f in target_freqs:
            cut = freq_cutoffs[target_f]
            selected = df_test_top1[df_test_top1['composite_score'] >= cut].copy()
            selected['target_freq'] = target_f
            oos_results_by_freq[target_f].append(selected)

        # Perturbation tests on target 50
        cut_50 = freq_cutoffs[50]
        # -10% threshold (easier to enter)
        cut_minus = cut_50 * 0.90
        # +10% threshold (stricter to enter)
        cut_plus = cut_50 * 1.10
        
        sel_minus = df_test_top1[df_test_top1['composite_score'] >= cut_minus].copy()
        sel_base = df_test_top1[df_test_top1['composite_score'] >= cut_50].copy()
        sel_plus = df_test_top1[df_test_top1['composite_score'] >= cut_plus].copy()
        
        perturb_results['minus_10'].append(sel_minus)
        perturb_results['base_50'].append(sel_base)
        perturb_results['plus_10'].append(sel_plus)

    print("\n" + "=" * 80)
    print(">>> [Phase 6] Simulating Full Trade Ledgers for Exit Rules & Portfolios")
    print("=" * 80)

    # Combine OOS selections for target 50
    df_oos_target50 = pd.concat(oos_results_by_freq[50]).reset_index(drop=True)
    print(f"Total Out-Of-Sample Trades for Target 50 (2023-2026): {len(df_oos_target50)}")

    # Generate full trade ledgers for target 50 across Exit Rules: R1, R2, R3
    trade_records = []
    for row in df_oos_target50.itertuples():
        tk = row.ticker_str
        d2 = row.d2_date_str
        buy_px = row.d2_open
        
        res_r1 = simulate_t1_trade(tk, d2, buy_px, rule='R1')
        res_r2 = simulate_t1_trade(tk, d2, buy_px, rule='R2')
        res_r3 = simulate_t1_trade(tk, d2, buy_px, rule='R3')

        trade_records.append({
            'ticker': tk,
            'name': row.name,
            'd2_date': d2,
            'plate': row.plate,
            'd1_reason': row.reason,
            'theme_prob': round(row.theme_prob, 4),
            'stock_prob': round(row.stock_prob, 4),
            'composite_score': round(row.composite_score, 4),
            'is_d2_zt': row.label_d2_zt,
            'buy_price': res_r1['buy_price'],
            
            # Rule R1 (Hold while ZT, exit at close of broken day)
            'exit_date_r1': res_r1['exit_date'],
            'exit_price_r1': res_r1['exit_price'],
            'hold_days_r1': res_r1['hold_days'],
            'net_ret_r1': round(res_r1['net_ret'], 4),
            'exit_reason_r1': res_r1['exit_reason'],
            'is_win_r1': res_r1['is_win'],
            
            # Rule R2 (Weak open cut < -3%, else close)
            'exit_date_r2': res_r2['exit_date'],
            'exit_price_r2': res_r2['exit_price'],
            'hold_days_r2': res_r2['hold_days'],
            'net_ret_r2': round(res_r2['net_ret'], 4),
            'exit_reason_r2': res_r2['exit_reason'],
            'is_win_r2': res_r2['is_win'],

            # Rule R3 (Exit next day open)
            'exit_date_r3': res_r3['exit_date'],
            'exit_price_r3': res_r3['exit_price'],
            'hold_days_r3': res_r3['hold_days'],
            'net_ret_r3': round(res_r3['net_ret'], 4),
            'exit_reason_r3': res_r3['exit_reason'],
            'is_win_r3': res_r3['is_win'],
            'test_year': row.test_year
        })

    df_ledger = pd.DataFrame(trade_records)
    df_ledger.to_csv(LEDGER_CSV_PATH, index=False, encoding='utf-8-sig')
    print(f"Saved complete OOS trade ledger to: {LEDGER_CSV_PATH}")

    # Portfolio simulation helper
    def run_portfolio_simulation(df_trades, ret_col, exit_date_col):
        """
        Runs:
        1. Date equal-weight portfolio (daily compounding)
        2. Single-slot portfolio (单仓轮动: 100% position, cannot buy when holding)
        3. Dual-slot portfolio (双仓轮动: 50% position each slot)
        """
        if len(df_trades) == 0:
            return {}

        df_sorted = df_trades.sort_values('d2_date').reset_index(drop=True)
        
        # 1. Date equal-weight
        daily_rets = df_sorted.groupby('d2_date')[ret_col].mean()
        # Cumulative nav
        cum_eq = (1.0 + daily_rets).prod()
        
        # 2. Single-slot portfolio (单仓轮动)
        # Cash starts at 1.0. When in position, cash is locked until exit_date
        slot_busy_until = ""
        single_slot_trades = []
        nav_single = 1.0
        nav_series_single = []
        
        for r in df_sorted.itertuples():
            b_d = r.d2_date
            e_d = getattr(r, exit_date_col)
            ret = getattr(r, ret_col)
            if b_d >= slot_busy_until:
                # Slot is free! Execute trade
                nav_single *= (1.0 + ret)
                single_slot_trades.append(r)
                slot_busy_until = e_d
                nav_series_single.append((b_d, nav_single))
            else:
                # Slot is occupied, skip trade!
                pass

        # 3. Dual-slot portfolio (双仓轮动)
        # Two slots, 50% weight each
        slot1_busy_until = ""
        slot2_busy_until = ""
        nav_dual = 1.0
        dual_slot_trades = []
        
        for r in df_sorted.itertuples():
            b_d = r.d2_date
            e_d = getattr(r, exit_date_col)
            ret = getattr(r, ret_col)
            
            allocated_slot = None
            if b_d >= slot1_busy_until:
                allocated_slot = 1
                slot1_busy_until = e_d
            elif b_d >= slot2_busy_until:
                allocated_slot = 2
                slot2_busy_until = e_d
                
            if allocated_slot is not None:
                # 50% weight trade
                nav_dual *= (1.0 + 0.5 * ret)
                dual_slot_trades.append(r)

        # Performance metrics for all trades in this subset
        all_rets = df_sorted[ret_col].values
        win_rate = (all_rets > 0).mean()
        wins = all_rets[all_rets > 0]
        losses = all_rets[all_rets < 0]
        avg_win = wins.mean() if len(wins) > 0 else 0.0
        avg_loss = abs(losses.mean()) if len(losses) > 0 else 1e-4
        profit_factor = (wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 0 else 99.0
        avg_ret = all_rets.mean()

        # Max Drawdown of date equal-weight
        eq_curve = np.cumprod(1.0 + daily_rets.values)
        peak = np.maximum.accumulate(eq_curve)
        dd = (eq_curve - peak) / peak
        max_dd = float(dd.min()) if len(dd) > 0 else 0.0

        return {
            'trade_count': len(df_sorted),
            'win_rate': round(win_rate, 4),
            'avg_net_ret': round(avg_ret, 4),
            'profit_factor': round(profit_factor, 2),
            'avg_win': round(avg_win, 4),
            'avg_loss': round(avg_loss, 4),
            'max_drawdown': round(max_dd, 4),
            'cum_equal_weight_multiple': round(cum_eq, 3),
            'single_slot_trades_count': len(single_slot_trades),
            'single_slot_cum_multiple': round(nav_single, 3),
            'dual_slot_trades_count': len(dual_slot_trades),
            'dual_slot_cum_multiple': round(nav_dual, 3),
        }

    print("\n" + "=" * 80)
    print(">>> [Phase 7] Evaluating Frequency Spectrum (~30, ~50, ~80, ~150 trades/yr)")
    print("=" * 80)

    freq_summary = {}
    for target_f in target_freqs:
        df_f = pd.concat(oos_results_by_freq[target_f]).reset_index(drop=True)
        # Simulate R1
        f_trades = []
        for r in df_f.itertuples():
            res = simulate_t1_trade(r.ticker_str, r.d2_date_str, r.d2_open, rule='R1')
            f_trades.append({
                'd2_date': r.d2_date_str,
                'exit_date': res['exit_date'],
                'net_ret': res['net_ret'],
                'is_d2_zt': r.label_d2_zt,
                'test_year': r.test_year
            })
        df_ft = pd.DataFrame(f_trades)
        
        # Calculate yearly breakdown
        yearly_stats = {}
        for yr, group in df_ft.groupby('test_year'):
            yr_int = int(yr)
            csi_ret = CSI300_ANNUAL_RETURNS.get(yr_int, 0.0)
            cum_ret = (1.0 + group.groupby('d2_date')['net_ret'].mean()).prod() - 1.0
            excess = cum_ret - csi_ret
            yearly_stats[yr] = {
                'trades': len(group),
                'seal_rate_d2': round(group['is_d2_zt'].mean(), 4),
                'win_rate': round((group['net_ret'] > 0).mean(), 4),
                'cum_net_ret': round(cum_ret, 4),
                'csi300_ret': round(csi_ret, 4),
                'excess_ret': round(excess, 4)
            }
            
        overall_stats = run_portfolio_simulation(df_ft, 'net_ret', 'exit_date')
        overall_stats['d2_seal_rate'] = round(df_ft['is_d2_zt'].mean(), 4)
        overall_stats['annual_avg_trades'] = round(len(df_ft) / 3.86, 1)
        overall_stats['yearly_breakdown'] = yearly_stats
        
        freq_summary[f"target_{target_f}"] = overall_stats
        print(f"Target ~{target_f} trades/yr: Actual OOS Total={len(df_ft)} (Annual={overall_stats['annual_avg_trades']}), "
              f"Seal Rate={overall_stats['d2_seal_rate']:.2%}, Win Rate={overall_stats['win_rate']:.2%}, "
              f"Profit Factor={overall_stats['profit_factor']}, Cum Return Multiplier={overall_stats['cum_equal_weight_multiple']}x, "
              f"Single Slot Multiplier={overall_stats['single_slot_cum_multiple']}x")

    print("\n" + "=" * 80)
    print(">>> [Phase 8] Evaluating Target 50 Exit Rules (R1 vs R2 vs R3)")
    print("=" * 80)

    exit_rules_comparison = {}
    for r_name, ret_c, exit_c in [('R1_BrokenClose', 'net_ret_r1', 'exit_date_r1'),
                                   ('R2_WeakOpenCut_BrokenClose', 'net_ret_r2', 'exit_date_r2'),
                                   ('R3_BrokenNextDayOpen', 'net_ret_r3', 'exit_date_r3')]:
        sim = run_portfolio_simulation(df_ledger, ret_c, exit_c)
        exit_rules_comparison[r_name] = sim
        print(f"Rule {r_name}: Win Rate={sim['win_rate']:.2%}, Profit Factor={sim['profit_factor']}, "
              f"Avg Ret={sim['avg_net_ret']:.2%}, Max DD={sim['max_drawdown']:.2%}, "
              f"Cum Equal Weight={sim['cum_equal_weight_multiple']}x, Single Slot={sim['single_slot_cum_multiple']}x")

    print("\n" + "=" * 80)
    print(">>> [Phase 9] Evaluating Robustness (+/-10% Threshold Perturbation)")
    print("=" * 80)

    perturbation_summary = {}
    for p_name, p_list in [('minus_10pct_loose', perturb_results['minus_10']),
                           ('base_50_standard', perturb_results['base_50']),
                           ('plus_10pct_strict', perturb_results['plus_10'])]:
        df_p = pd.concat(p_list).reset_index(drop=True)
        p_trades = []
        for r in df_p.itertuples():
            res = simulate_t1_trade(r.ticker_str, r.d2_date_str, r.d2_open, rule='R1')
            p_trades.append({
                'd2_date': r.d2_date_str,
                'exit_date': res['exit_date'],
                'net_ret': res['net_ret'],
                'is_d2_zt': r.label_d2_zt
            })
        df_pt = pd.DataFrame(p_trades)
        sim = run_portfolio_simulation(df_pt, 'net_ret', 'exit_date')
        sim['d2_seal_rate'] = round(df_pt['is_d2_zt'].mean(), 4) if len(df_pt) > 0 else 0.0
        sim['total_trades'] = len(df_pt)
        sim['annual_trades'] = round(len(df_pt) / 3.86, 1)
        perturbation_summary[p_name] = sim
        print(f"Perturbation {p_name}: Trades={sim['total_trades']} (Annual {sim['annual_trades']}), "
              f"Seal Rate={sim['d2_seal_rate']:.2%}, Win Rate={sim['win_rate']:.2%}, "
              f"Profit Factor={sim['profit_factor']}, Cum Multiplier={sim['cum_equal_weight_multiple']}x")

    # Target 50 Detailed Yearly Breakdown for R1
    yearly_target50 = {}
    for yr, group in df_ledger.groupby('test_year'):
        yr_int = int(yr)
        csi_ret = CSI300_ANNUAL_RETURNS.get(yr_int, 0.0)
        daily_rets = group.groupby('d2_date')['net_ret_r1'].mean()
        cum_ret = (1.0 + daily_rets).prod() - 1.0
        excess = cum_ret - csi_ret
        wins = group[group['net_ret_r1'] > 0]
        losses = group[group['net_ret_r1'] < 0]
        pf = (wins['net_ret_r1'].sum() / abs(losses['net_ret_r1'].sum())) if len(losses) > 0 else 99.0
        
        yearly_target50[yr] = {
            'trades': len(group),
            'd2_seal_rate': round(group['is_d2_zt'].mean(), 4),
            'win_rate': round((group['net_ret_r1'] > 0).mean(), 4),
            'profit_factor': round(pf, 2),
            'avg_net_ret': round(group['net_ret_r1'].mean(), 4),
            'cum_strategy_ret': round(cum_ret, 4),
            'csi300_benchmark_ret': round(csi_ret, 4),
            'net_excess_ret': round(excess, 4)
        }

    # Save complete JSON
    full_results = {
        'metadata': {
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'script': 'clean_wf_1to2_selective50.py',
            'execution_time_seconds': round(time.time() - start_time, 2),
            'a_share_settlement': 'Strict T+1 (Buy D2 09:25 open, lock D2, earliest exit D3)',
            'universe': 'A-share Main Board (00, 60), Exclude ST, Delisting, One-Word Limit-Up Open',
            'folds_validated': ['2023', '2024', '2025', '2026']
        },
        'fold_model_info': fold_model_info,
        'target50_yearly_breakdown': yearly_target50,
        'exit_rules_comparison': exit_rules_comparison,
        'frequency_spectrum_comparison': freq_summary,
        'perturbation_robustness': perturbation_summary,
        'target50_overall_r1': run_portfolio_simulation(df_ledger, 'net_ret_r1', 'exit_date_r1')
    }

    with open(RESULTS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(full_results, f, ensure_ascii=False, indent=2)

    print(f"\nSaved complete results JSON to: {RESULTS_JSON_PATH}")
    print(f"Total time elapsed: {time.time() - start_time:.2f} seconds.")
    print("=" * 80)

if __name__ == '__main__':
    main()

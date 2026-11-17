#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clean_wf_1to2_v5_high_payoff_50.py
--------------------------------------------------------------------------------
1to2 V5.0 High-Payoff Monster-Stock Ride & 50+ Trades Clean Engine
1. 100% 零未来函数换手晋级出场机制（Zero-Lookahead Turnover Monster Ride）：
   - 彻底修复 V4.5 在 D3 早上对非涨停开盘（o < zt - 0.01）一刀切卖出导致右尾腰斩的致命短板。
   - Scheme B1（分仓锁利法）：D3 若 o >= prev_close * 1.02，09:25 集合竞价卖出 50% 锁利；
     剩余 50% 挂条件单 stop_px = round(min(o * 0.96, prev_close * 0.985), 2)。
     若盘中 l <= stop_px，触发止盈/止损出局；若全天 l > stop_px 且收盘封死涨停（is_zt），继续持有骑乘连板！
     若收盘未封板（not is_zt），在 14:57 集合竞价按收盘价 c 卖出（断板必走）。
   - Scheme B2（全仓条件单法）：D3 若 o >= prev_close * 1.02，全仓挂 stop_px = round(o * 0.965, 2)。
     若 l <= stop_px 按 stop_px 卖出；若 l > stop_px 且 is_zt 继续骑乘，not is_zt 按收盘价 c 卖出。
   - 弱开（o < prev_close * 1.02）：09:25 开盘按 o 全卖。
2. 彻底修复 cninfo 100.4万条公告库特征：
   - 修复时间错位：覆盖 D0（前一交易日）、D1（首板盘前引爆催化）与 D2（二板竞价前）。
   - 细分催化分级：
     * S级（实控人变更/控制权/重大重组/借壳/预增>=100%/暴增）
     * A级（预增/扭亏/重大合同/中标/战略合作/回购）
     * 负面风险（减持/立案/问询/风险提示/异动/亏损/警示）-> 严格事前过滤剔除！
3. 严格 expanding walk-forward（2022 至 2026，train < Y），无任何未来函数。
"""

import os
import sys
import re
import json
import time
import sqlite3
import numpy as np
import pandas as pd
from collections import defaultdict
import pyarrow.dataset as ds
from sklearn.linear_model import Ridge
import warnings
warnings.filterwarnings('ignore')

CSI300_ANNUAL_RETURNS = {
    2022: -0.2163,
    2023: -0.1138,
    2024: +0.1468,
    2025: -0.0350,
    2026: +0.0120
}

DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
NOTICES_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"

RESULTS_JSON = os.path.join(DATA_DIR, "clean_wf_1to2_v5_high_payoff_50_results.json")
TRADES_CSV = os.path.join(DATA_DIR, "clean_wf_1to2_v5_high_payoff_50_ledger.csv")

sys.path.insert(0, DATA_DIR)
from clean_wf_1to2_v4_3_master import simulate_portfolio_slots

def load_kpl_and_notices_v5():
    print(">>> [Phase 1] Loading KPL Complete 5Y Themes & PIT Notices V5 (S/A/Risk Graded)...")
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
    
    # Graded notices: S, A, Risk
    s_notices = set()
    a_notices = set()
    risk_notices = set()
    
    s_pattern = re.compile(r'控制权|实控人|重大资产重组|收购|借壳|暴增|预增.*[1-9][0-9]{2}%')
    a_keywords = ['预增', '扭亏', '中标', '合同', '重大合同', '战略合作', '回购', '增持']
    risk_keywords = ['减持', '立案', '问询', '风险提示', '异动澄清', '亏损', '质押', '被动减持', '警示']
    
    if os.path.exists(NOTICES_DB_PATH):
        try:
            conn = sqlite3.connect(NOTICES_DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT sec_code, trade_date_avail, title, ann_type FROM notices")
            for row in cur.fetchall():
                code, av_date, title, ann_type = row
                c6 = str(code)[:6].zfill(6)
                t_str = str(title or '') + ' ' + str(ann_type or '')
                key = (c6, av_date)
                
                # Check Risk first
                if any(k in t_str for k in risk_keywords):
                    risk_notices.add(key)
                
                # Check S-tier
                if s_pattern.search(t_str):
                    s_notices.add(key)
                elif any(k in t_str for k in a_keywords):
                    a_notices.add(key)
            conn.close()
            print(f"PIT Notices V5 loaded: {len(s_notices):,} S-tier, {len(a_notices):,} A-tier, {len(risk_notices):,} Risk notices.")
        except Exception as e:
            print(f"Notice DB load error: {e}")
            
    return stock_to_plate_info, kpl_daily_plates, plate_daily_counts, s_notices, a_notices, risk_notices

def load_price_data_v5():
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
    
    # Prior date (D0)
    df['d0_date_str'] = df.groupby('code6')['date_str'].shift(1)
    
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

def build_feature_matrix_v5(df, stock_to_plate_info, kpl_daily_plates, plate_daily_counts, s_notices, a_notices, risk_notices):
    print(">>> [Phase 3] Building V5 PIT Feature Matrix with S/A Graded Catalyst & Anti-Orphan Fix...")
    t0 = time.time()
    
    streak_2b_stks = df[df['streak'] >= 2].copy()
    streak_2b_stks['next_open_ret'] = streak_2b_stks['d2_o_pct']
    daily_2b_prem = streak_2b_stks.groupby('date_str')['next_open_ret'].mean().to_dict()
    
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
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
    
    # Realtime 09:25 market-wide first board open mean
    d2_daily_mkt_open = fb_all.groupby('d2_date_str')['d2_o_pct'].mean().to_dict()
    fb_all['mkt_d2_fb_open_mean'] = [d2_daily_mkt_open.get(d, 0.0) for d in fb_all['d2_date_str']]
    
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
    
    # In-theme open rank
    fb_all['in_theme_open_rank'] = fb_all.groupby(['d2_date_str', 'plate'])['d2_o_pct'].rank(ascending=False, method='min')
    
    # Strict Peer Open Mean (Eradicate Orphan Falsely Claiming Sector Synergy)
    plate_d2_groups = fb_all.groupby(['d2_date_str', 'plate'])['d2_o_pct']
    plate_d2_sum = plate_d2_groups.transform('sum')
    plate_d2_cnt = plate_d2_groups.transform('count')
    fb_all['plate_d2_cnt'] = plate_d2_cnt
    
    fb_all['theme_d2_peer_open_mean'] = np.where(
        (fb_all['plate'] != "其他") & (plate_d2_cnt > 1),
        (plate_d2_sum - fb_all['d2_o_pct']) / (plate_d2_cnt - 1),
        -0.02
    )
    
    # True Sector Leader indicator
    fb_all['is_true_sector_leader'] = (
        (fb_all['plate'] != "其他") & 
        (plate_d2_cnt >= 2) & 
        (fb_all['in_theme_open_rank'] == 1)
    ).astype(float)
    
    # D1 seal quality
    fb_all['d1_seal_quality'] = fb_all['entity_ratio'] - 0.5 * (fb_all['amplitude'] - fb_all['entity_ratio'])
    
    # Peer strong open count
    fb_all['is_strong_open'] = (fb_all['d2_o_pct'] >= 0.05).astype(int)
    plate_d2_strong_groups = fb_all.groupby(['d2_date_str', 'plate'])['is_strong_open']
    fb_all['theme_d2_zt_open_cnt'] = np.where(
        (fb_all['plate'] != "其他") & (plate_d2_cnt > 1),
        plate_d2_strong_groups.transform('sum') - fb_all['is_strong_open'],
        0
    )
    
    burst_ratios = []
    is_fresh_list = []
    for d_str, p_name in zip(fb_all['date_str'], fb_all['plate']):
        if p_name != "其他":
            idx = date_to_idx.get(d_str, -1)
            past_20d_counts = []
            for k in range(max(0, idx-20), idx):
                past_d = all_trade_dates[k]
                cnt = plate_daily_counts[past_d].get(p_name, 0)
                past_20d_counts.append(cnt)
            curr_cnt = plate_daily_counts[d_str].get(p_name, 1)
            past_mean = np.mean(past_20d_counts) if past_20d_counts else 0.0
            ratio = curr_cnt / (past_mean + 1.0)
            burst_ratios.append(min(5.0, ratio))
            past_3d_sum = sum(past_20d_counts[-3:]) if len(past_20d_counts) >= 3 else 0
            is_fresh_list.append(1.0 if past_3d_sum <= 1 else 0.0)
        else:
            burst_ratios.append(1.0)
            is_fresh_list.append(0.5)
            
    fb_all['theme_burst_ratio'] = burst_ratios
    fb_all['theme_is_fresh'] = is_fresh_list
    fb_all['plate_past5d_2b_premium'] = [market_5d_2b_prem.get(d, 0.0) for d in fb_all['date_str']]
    
    # Quadratic opening term
    fb_all['d2_o_pct_sq'] = (fb_all['d2_o_pct'] - 0.045) ** 2
    
    # Target 1: D2 sealed limit up AND D3 open is profitable
    fb_all['target_win'] = ((fb_all['d2_is_zt']) & (fb_all['d3_open_ret'] > 0.0015)).astype(float)
    
    # Hard structural candidate filters
    fb = fb_all[~fb_all['stock_name'].str.contains('ST|退', regex=True)].copy()
    fb = fb[fb['d2_open'] < fb['d2_zt_price'] - 0.005].copy() # Exclude one-word limit up on D2
    
    # =========================================================================
    # V5 NOTICE INTEGRATION: D0, D1, D2 Graded Catalysts
    # =========================================================================
    has_risk = []
    has_s_notice = []
    has_a_notice = []
    notice_tier = []
    
    for r in fb[['code6', 'd0_date_str', 'date_str', 'd2_date_str']].itertuples(index=False):
        c6 = r.code6
        dates_to_check = [r.d0_date_str, r.date_str, r.d2_date_str]
        
        # Risk check: any risk notice on D0, D1, D2?
        is_risk = any((c6, d) in risk_notices for d in dates_to_check if pd.notna(d))
        has_risk.append(1 if is_risk else 0)
        
        # S-tier check: S catalyst on D0, D1, D2?
        is_s = any((c6, d) in s_notices for d in dates_to_check if pd.notna(d))
        has_s_notice.append(1 if is_s else 0)
        
        # A-tier check: A catalyst on D0, D1, D2?
        is_a = any((c6, d) in a_notices for d in dates_to_check if pd.notna(d))
        has_a_notice.append(1 if is_a else 0)
        
        if is_s:
            notice_tier.append(2.0)
        elif is_a:
            notice_tier.append(1.0)
        else:
            notice_tier.append(0.0)
            
    fb['has_risk_notice'] = has_risk
    fb['has_s_notice'] = has_s_notice
    fb['has_a_notice'] = has_a_notice
    fb['notice_tier'] = notice_tier
    fb['has_pos_notice'] = ((fb['has_s_notice'] == 1) | (fb['has_a_notice'] == 1)).astype(int)
    
    # Hard filter: exclude risk notices
    fb = fb[fb['has_risk_notice'] == 0].copy()
    fb = fb[(fb['amount'] >= 1.5e8) & (fb['mcap_circ'] >= 15.0) & (fb['mcap_circ'] <= 250.0)].copy()
    fb = fb[(fb['dd20'] <= 0.92) & (fb['ret5d'] <= 0.28)].copy()
    
    print(f"Candidates after hard filters & notice grading: {len(fb):,} in {time.time()-t0:.2f}s")
    print(f"  S-tier notices: {(fb['has_s_notice'] == 1).sum():,}, A-tier notices: {(fb['has_a_notice'] == 1).sum():,}")
    return fb, df

def simulate_trade_v5(candidate_row, price_lookup, all_trade_dates, date_to_idx, 
                       exit_mode="B1_Ride", regime_mode="AllWeather", use_touch_order=True):
    """
    100% Zero-Lookahead Simulation:
    - Entry at D2 open or TouchProtect
    - Exit logic:
      * If D2 not sealed: exit at D3 09:25 open
      * If D2 sealed:
        - Mode "P2_Legacy": Original V4.5 exit (cut off at D3 open if o < zt)
        - Mode "B1_Ride" (Split 50/50):
          * D3 open >= zt - 0.01:
            100% hang stop_px = round(zt * 0.97, 2). If l <= stop_px exit at stop_px.
            Else if is_zt hold 100% overnight to D4; else exit 100% at c (14:57).
          * D3 o < zt - 0.01 and o >= prev_close * 1.02:
            50% sold at open o (lock-in).
            50% hang stop_px = round(min(o * 0.96, prev_close * 0.985), 2).
            If l <= stop_px, exit 50% at stop_px (trade avg = 0.5*o + 0.5*stop_px, done D3).
            If l > stop_px:
              if is_zt: hold 50% overnight into D4+!
              if not is_zt: exit 50% at close c (trade avg = 0.5*o + 0.5*c, done D3).
          * D3 o < prev_close * 1.02:
            100% sold at open o.
        - Mode "B2_Ride" (Full 100% Condition Order):
          * D3 open >= zt - 0.01: stop_px = round(zt * 0.97, 2).
          * D3 o < zt - 0.01 and o >= prev_close * 1.02:
            100% hang stop_px = round(o * 0.965, 2).
            If l <= stop_px exit 100% at stop_px.
            If l > stop_px: if is_zt hold 100% overnight into D4+; else exit at c.
          * D3 o < prev_close * 1.02: exit 100% at open o.
    """
    code = candidate_row['code6']
    d2_str = candidate_row['d2_date_str']
    idx_d2 = date_to_idx.get(d2_str)
    if idx_d2 is None:
        return None
        
    d2_info = price_lookup.get((code, d2_str))
    if not d2_info:
        return None
    d2_open, d2_high, d2_low, d2_close, d2_adj, d2_zt, d2_dt, d2_is_zt, d2_is_yizi_dt = d2_info
    
    d2_o_pct = candidate_row['d2_o_pct']
    if not (0.015 <= d2_o_pct <= 0.075):
        return None
    if candidate_row['plate'] == "其他" or candidate_row['plate_d2_cnt'] < 2 or candidate_row['theme_d2_peer_open_mean'] < -0.01:
        return None
        
    # Regime Filter
    if regime_mode == "GoldenRegime":
        if candidate_row['plate_past5d_2b_premium'] <= -0.005 or candidate_row['theme_d2_peer_open_mean'] < 0.005:
            return None
    elif regime_mode == "RegimeSafe":
        if candidate_row['plate_past5d_2b_premium'] < -0.02 or candidate_row['mkt_d2_fb_open_mean'] < -0.015:
            return None
            
    # Entry Execution
    if not use_touch_order or d2_o_pct <= 0.050 or candidate_row['theme_d2_peer_open_mean'] >= 0.020:
        buy_price = d2_open
    else:
        if d2_high >= d2_zt - 0.01:
            buy_price = d2_zt
        else:
            return None # Avoided waterfall drop
            
    sealed_2b = 1 if d2_is_zt else 0
    curr_idx = idx_d2 + 1
    prev_close = d2_close
    exit_price = None
    exit_date = None
    
    if not d2_is_zt:
        # D2 failed to seal: exit at D3 09:25 open
        while curr_idx < len(all_trade_dates):
            d_curr = all_trade_dates[curr_idx]
            info = price_lookup.get((code, d_curr))
            if not info:
                exit_price = d2_close
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
                break
        if exit_price is None:
            exit_price = prev_close
            exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
        holding_days = max(1, curr_idx - idx_d2)
        gross_ret = exit_price / buy_price - 1.0
        net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
        return {
            'code': code, 'name': candidate_row['stock_name'], 'buy_date': d2_str,
            'buy_price': round(float(buy_price), 2), 'exit_date': exit_date,
            'exit_price': round(float(exit_price), 2), 'holding_days': holding_days,
            'sealed_2b': sealed_2b, 'gross_ret': round(float(gross_ret), 4),
            'net_ret': round(float(net_ret), 4), 'plate': candidate_row['plate'],
            'notice_tier': float(candidate_row.get('notice_tier', 0.0)),
            'score': round(float(candidate_row.get('model_score', 0.0)), 4),
        }
        
    # =========================================================================
    # D2 SEALED LIMIT UP!
    # =========================================================================
    if exit_mode == "P2_Legacy":
        # Legacy V4.5 P2 exit
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
        if exit_price is None:
            exit_price = prev_close
            exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
        holding_days = max(1, curr_idx - idx_d2)
        gross_ret = exit_price / buy_price - 1.0
        net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
        return {
            'code': code, 'name': candidate_row['stock_name'], 'buy_date': d2_str,
            'buy_price': round(float(buy_price), 2), 'exit_date': exit_date,
            'exit_price': round(float(exit_price), 2), 'holding_days': holding_days,
            'sealed_2b': sealed_2b, 'gross_ret': round(float(gross_ret), 4),
            'net_ret': round(float(net_ret), 4), 'plate': candidate_row['plate'],
            'notice_tier': float(candidate_row.get('notice_tier', 0.0)),
            'score': round(float(candidate_row.get('model_score', 0.0)), 4),
        }

    elif exit_mode == "B1_Ride":
        # Scheme B1: Split 50/50 Position
        # In D3:
        d3_date = all_trade_dates[curr_idx]
        d3_info = price_lookup.get((code, d3_date))
        if not d3_info:
            exit_price = prev_close
            exit_date = d3_date
            holding_days = 1
            gross_ret = exit_price / buy_price - 1.0
            net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
            return {
                'code': code, 'name': candidate_row['stock_name'], 'buy_date': d2_str,
                'buy_price': round(float(buy_price), 2), 'exit_date': exit_date,
                'exit_price': round(float(exit_price), 2), 'holding_days': holding_days,
                'sealed_2b': sealed_2b, 'gross_ret': round(float(gross_ret), 4),
                'net_ret': round(float(net_ret), 4), 'plate': candidate_row['plate'],
                'notice_tier': float(candidate_row.get('notice_tier', 0.0)),
                'score': round(float(candidate_row.get('model_score', 0.0)), 4),
            }
            
        o3, h3, l3, c3, adj3, zt3, dt3, is_zt3, is_yizi_dt3 = d3_info
        
        # Case A: D3 opens at limit up (o3 >= zt3 - 0.01)
        if o3 >= zt3 - 0.01:
            stop_px = round(zt3 * 0.97, 2)
            if l3 <= stop_px:
                exit_price = stop_px
                exit_date = d3_date
                holding_days = 1
            elif not is_zt3:
                exit_price = c3
                exit_date = d3_date
                holding_days = 1
            else:
                # Sealed 3B! Hold 100% to D4 and subsequent days
                curr_idx += 1
                prev_close = c3
                exit_price = None
                while curr_idx < len(all_trade_dates):
                    d_curr = all_trade_dates[curr_idx]
                    info = price_lookup.get((code, d_curr))
                    if not info:
                        exit_price = prev_close
                        exit_date = d_curr
                        break
                    o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                    if o >= zt - 0.01:
                        st_px = round(zt * 0.97, 2)
                        if l <= st_px:
                            exit_price = st_px
                            exit_date = d_curr
                            break
                        elif not is_zt:
                            exit_price = c
                            exit_date = d_curr
                            break
                        else:
                            prev_close = c
                            curr_idx += 1
                            continue
                    else:
                        st_px = round(o * 0.965, 2)
                        if l <= st_px:
                            exit_price = st_px
                            exit_date = d_curr
                            break
                        elif not is_zt:
                            exit_price = c
                            exit_date = d_curr
                            break
                        else:
                            prev_close = c
                            curr_idx += 1
                            continue
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
                
        # Case B: D3 opens strong (prev_close * 1.02 <= o3 < zt3 - 0.01)
        elif o3 >= prev_close * 1.02:
            px_part1 = o3 # 50% sold at open
            stop_px = round(min(o3 * 0.96, prev_close * 0.985), 2)
            
            if l3 <= stop_px:
                px_part2 = stop_px
                exit_date = d3_date
                holding_days = 1
                exit_price = 0.5 * px_part1 + 0.5 * px_part2
            elif not is_zt3:
                px_part2 = c3 # 14:57 close exit
                exit_date = d3_date
                holding_days = 1
                exit_price = 0.5 * px_part1 + 0.5 * px_part2
            else:
                # Sealed turnover 3B! 50% rides into D4+
                curr_idx += 1
                prev_close = c3
                px_part2 = None
                while curr_idx < len(all_trade_dates):
                    d_curr = all_trade_dates[curr_idx]
                    info = price_lookup.get((code, d_curr))
                    if not info:
                        px_part2 = prev_close
                        exit_date = d_curr
                        break
                    o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                    if o >= zt - 0.01:
                        st_px = round(zt * 0.97, 2)
                        if l <= st_px:
                            px_part2 = st_px
                            exit_date = d_curr
                            break
                        elif not is_zt:
                            px_part2 = c
                            exit_date = d_curr
                            break
                        else:
                            prev_close = c
                            curr_idx += 1
                            continue
                    else:
                        st_px = round(o * 0.965, 2)
                        if l <= st_px:
                            px_part2 = st_px
                            exit_date = d_curr
                            break
                        elif not is_zt:
                            px_part2 = c
                            exit_date = d_curr
                            break
                        else:
                            prev_close = c
                            curr_idx += 1
                            continue
                if px_part2 is None:
                    px_part2 = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
                exit_price = 0.5 * px_part1 + 0.5 * px_part2
                
        # Case C: D3 opens weak (o3 < prev_close * 1.02)
        else:
            if is_yizi_dt3:
                # Handle yizi falling limit
                curr_idx += 1
                prev_close = c3
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
                        break
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
            else:
                exit_price = o3
                exit_date = d3_date
                holding_days = 1
                
        gross_ret = exit_price / buy_price - 1.0
        net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
        return {
            'code': code, 'name': candidate_row['stock_name'], 'buy_date': d2_str,
            'buy_price': round(float(buy_price), 2), 'exit_date': exit_date,
            'exit_price': round(float(exit_price), 2), 'holding_days': holding_days,
            'sealed_2b': sealed_2b, 'gross_ret': round(float(gross_ret), 4),
            'net_ret': round(float(net_ret), 4), 'plate': candidate_row['plate'],
            'notice_tier': float(candidate_row.get('notice_tier', 0.0)),
            'score': round(float(candidate_row.get('model_score', 0.0)), 4),
        }

    elif exit_mode == "B2_Ride":
        # Scheme B2: 100% Condition Order Ride
        d3_date = all_trade_dates[curr_idx]
        d3_info = price_lookup.get((code, d3_date))
        if not d3_info:
            exit_price = prev_close
            exit_date = d3_date
            holding_days = 1
            gross_ret = exit_price / buy_price - 1.0
            net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
            return {
                'code': code, 'name': candidate_row['stock_name'], 'buy_date': d2_str,
                'buy_price': round(float(buy_price), 2), 'exit_date': exit_date,
                'exit_price': round(float(exit_price), 2), 'holding_days': holding_days,
                'sealed_2b': sealed_2b, 'gross_ret': round(float(gross_ret), 4),
                'net_ret': round(float(net_ret), 4), 'plate': candidate_row['plate'],
                'notice_tier': float(candidate_row.get('notice_tier', 0.0)),
                'score': round(float(candidate_row.get('model_score', 0.0)), 4),
            }
            
        o3, h3, l3, c3, adj3, zt3, dt3, is_zt3, is_yizi_dt3 = d3_info
        
        if o3 >= zt3 - 0.01:
            st_px = round(zt3 * 0.97, 2)
            if l3 <= st_px:
                exit_price = st_px
                exit_date = d3_date
                holding_days = 1
            elif not is_zt3:
                exit_price = c3
                exit_date = d3_date
                holding_days = 1
            else:
                curr_idx += 1
                prev_close = c3
                exit_price = None
                while curr_idx < len(all_trade_dates):
                    d_curr = all_trade_dates[curr_idx]
                    info = price_lookup.get((code, d_curr))
                    if not info:
                        exit_price = prev_close
                        exit_date = d_curr
                        break
                    o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                    if o >= zt - 0.01:
                        st = round(zt * 0.97, 2)
                        if l <= st:
                            exit_price = st; exit_date = d_curr; break
                        elif not is_zt:
                            exit_price = c; exit_date = d_curr; break
                        else:
                            prev_close = c; curr_idx += 1; continue
                    else:
                        st = round(o * 0.965, 2)
                        if l <= st:
                            exit_price = st; exit_date = d_curr; break
                        elif not is_zt:
                            exit_price = c; exit_date = d_curr; break
                        else:
                            prev_close = c; curr_idx += 1; continue
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
        elif o3 >= prev_close * 1.025:
            st_px = round(o3 * 0.965, 2)
            if l3 <= st_px:
                exit_price = st_px
                exit_date = d3_date
                holding_days = 1
            elif not is_zt3:
                exit_price = c3
                exit_date = d3_date
                holding_days = 1
            else:
                curr_idx += 1
                prev_close = c3
                exit_price = None
                while curr_idx < len(all_trade_dates):
                    d_curr = all_trade_dates[curr_idx]
                    info = price_lookup.get((code, d_curr))
                    if not info:
                        exit_price = prev_close
                        exit_date = d_curr
                        break
                    o, h, l, c, adj, zt, dt, is_zt, is_yizi_dt = info
                    if o >= zt - 0.01:
                        st = round(zt * 0.97, 2)
                        if l <= st:
                            exit_price = st; exit_date = d_curr; break
                        elif not is_zt:
                            exit_price = c; exit_date = d_curr; break
                        else:
                            prev_close = c; curr_idx += 1; continue
                    else:
                        st = round(o * 0.965, 2)
                        if l <= st:
                            exit_price = st; exit_date = d_curr; break
                        elif not is_zt:
                            exit_price = c; exit_date = d_curr; break
                        else:
                            prev_close = c; curr_idx += 1; continue
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
        else:
            if is_yizi_dt3:
                curr_idx += 1
                prev_close = c3
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
                        break
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
            else:
                exit_price = o3
                exit_date = d3_date
                holding_days = 1
                
        gross_ret = exit_price / buy_price - 1.0
        net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
        return {
            'code': code, 'name': candidate_row['stock_name'], 'buy_date': d2_str,
            'buy_price': round(float(buy_price), 2), 'exit_date': exit_date,
            'exit_price': round(float(exit_price), 2), 'holding_days': holding_days,
            'sealed_2b': sealed_2b, 'gross_ret': round(float(gross_ret), 4),
            'net_ret': round(float(net_ret), 4), 'plate': candidate_row['plate'],
            'notice_tier': float(candidate_row.get('notice_tier', 0.0)),
            'score': round(float(candidate_row.get('model_score', 0.0)), 4),
        }

def run_v5_pipeline():
    print("=" * 80)
    print(">>> [Phase 1] Loading Clean Data & Building V5 Feature Matrix...")
    print("=" * 80)
    
    stock_to_plate_info, kpl_daily_plates, plate_daily_counts, s_notices, a_notices, risk_notices = load_kpl_and_notices_v5()
    df = load_price_data_v5()
    fb, df = build_feature_matrix_v5(df, stock_to_plate_info, kpl_daily_plates, plate_daily_counts, s_notices, a_notices, risk_notices)
    
    price_lookup = {}
    for r in df[['code6', 'date_str', 'open', 'high', 'low', 'close', 'adj_close', 'zt_price', 'dt_price', 'is_zt', 'is_yizi_dt']].itertuples(index=False):
        price_lookup[(r.code6, r.date_str)] = (
            r.open, r.high, r.low, r.close, r.adj_close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt
        )
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    
    fb['year'] = pd.to_datetime(fb['d2_date_str']).dt.year
    years = [2022, 2023, 2024, 2025, 2026]
    
    # V5 Features: Including S/A Catalysts, Focus, TurnSweet
    fb['theme_focus_2_6'] = ((fb['plate_d2_cnt'] >= 2) & (fb['plate_d2_cnt'] <= 6)).astype(float)
    turn_pct = fb['turn'] * 100.0 if fb['turn'].median() < 1.0 else fb['turn']
    fb['turn_sweet'] = ((turn_pct >= 3.0) & (turn_pct <= 16.0)).astype(float) - (turn_pct > 22.0).astype(float)
    
    features = [
        'theme_zt_cnt_d1', 'theme_burst_ratio', 'theme_is_fresh',
        'theme_d2_peer_open_mean', 'theme_d2_zt_open_cnt', 'plate_past5d_2b_premium',
        'in_theme_open_rank', 'is_true_sector_leader', 
        'has_s_notice', 'has_a_notice', 'notice_tier', # V5 graded notice features
        'd1_seal_quality', 'd2_o_pct', 'd2_o_pct_sq',
        'entity_ratio', 'amplitude', 'vol_ratio', 'turn', 'dd20', 'ret5d', 'mcap_circ',
        'theme_focus_2_6', 'turn_sweet'
    ]
    for col in features:
        fb[col] = fb[col].fillna(0.0)
        
    fb['model_score'] = 0.0
    
    # Domain definition
    is_domain = (
        (fb['plate'] != '其他') & 
        (fb['plate_d2_cnt'] >= 2) & 
        (fb['d2_o_pct'] >= 0.015) & 
        (fb['d2_o_pct'] <= 0.075) & 
        (fb['theme_d2_peer_open_mean'] >= -0.01)
    )
    
    print(f"Total candidates: {len(fb):,}, Domain candidates: {is_domain.sum():,}")
    
    # Train Ridge for expanding window
    alpha_val = 10.0
    models_dict = {}
    for test_yr in years:
        train_df = fb[(fb['year'] < test_yr) & is_domain]
        X_train = train_df[features].values
        y_train = train_df['target_win'].values
        
        x_mean = np.mean(X_train, axis=0)
        x_std = np.std(X_train, axis=0) + 1e-6
        X_train_norm = (X_train - x_mean) / x_std
        
        model = Ridge(alpha=alpha_val)
        model.fit(X_train_norm, y_train)
        models_dict[test_yr] = (model, x_mean, x_std)
        
        # Check notice weights in 2026 model
        if test_yr == 2026:
            coefs = dict(zip(features, model.coef_))
            print(f"\n2026 Ridge Weights Top Features:")
            for k, v in sorted(coefs.items(), key=lambda x: abs(x[1]), reverse=True)[:10]:
                print(f"  {k:25s}: {v:+.5f}")
                
    # Strategy Combos to test
    # We test:
    # 1. Baseline: V4.5 Legacy P2 (Target 55, MaxSectors 2)
    # 2. Scheme B1 (Split 50/50 Ride): Target 55, MaxSectors 2
    # 3. Scheme B1 (Split 50/50 Ride): Target 65, MaxSectors 2 (Annual 50-60 trades!)
    # 4. Scheme B1 (Split 50/50 Ride): Target 75, MaxSectors 2 (Annual 60 trades)
    # 5. Scheme B2 (100% Ride): Target 55, MaxSectors 2
    # 6. Scheme B2 (100% Ride): Target 65, MaxSectors 2 (Annual 50-60 trades!)
    # 7. Scheme B1 GoldenRegime: Target 65, MaxSectors 2
    combos = [
        ("Combo 1", "V5_P2_Legacy_Baseline", 65, 2, True, "P2_Legacy", "AllWeather"),
        ("Combo 2", "V5_B1_SplitRide_Target55", 55, 2, True, "B1_Ride", "AllWeather"),
        ("Combo 3", "V5_B1_SplitRide_Target65_50Trades", 65, 2, True, "B1_Ride", "AllWeather"),
        ("Combo 4", "V5_B1_SplitRide_Target75_60Trades", 75, 2, True, "B1_Ride", "AllWeather"),
        ("Combo 5", "V5_B2_FullRide_Target55", 55, 2, True, "B2_Ride", "AllWeather"),
        ("Combo 6", "V5_B2_FullRide_Target65_50Trades", 65, 2, True, "B2_Ride", "AllWeather"),
        ("Combo 7", "V5_B1_GoldenRegime_Target65", 65, 2, True, "B1_Ride", "GoldenRegime"),
    ]
    
    all_results = {}
    all_trades_ledger = []
    
    for combo_label, combo_name, target_rate, max_sectors, use_touch, exit_mode, regime_mode in combos:
        print(f"\n" + "=" * 80)
        print(f"--- Running {combo_label}: {combo_name} (Target: {target_rate}/yr, MaxSectors: {max_sectors}, Exit: {exit_mode}, Regime: {regime_mode}) ---")
        print("=" * 80)
        
        combo_trades = []
        combo_yearly = {}
        
        for test_yr in years:
            model, x_mean, x_std = models_dict[test_yr]
            train_pool = fb[(fb['year'] < test_yr) & is_domain].copy()
            test_pool = fb[fb['year'] == test_yr].copy()
            
            # Compute test pool scores
            X_test = test_pool[features].values
            X_test_norm = (X_test - x_mean) / x_std
            test_pool['model_score'] = model.predict(X_test_norm)
            
            # Compute train cutoff
            X_tr = train_pool[features].values
            X_tr_norm = (X_tr - x_mean) / x_std
            train_scores = model.predict(X_tr_norm)
            
            train_span = max(1.0, (pd.to_datetime(train_pool['d2_date_str'].max()) - pd.to_datetime(train_pool['d2_date_str'].min())).days / 365.25)
            target_train_count = int(target_rate * train_span)
            
            if len(train_scores) > target_train_count:
                cutoff = float(np.percentile(train_scores, 100.0 * (1.0 - target_train_count / len(train_scores))))
            else:
                cutoff = float(np.percentile(train_scores, 80.0))
                
            test_cands = test_pool[test_pool['model_score'] >= cutoff].sort_values(['d2_date_str', 'model_score'], ascending=[True, False])
            
            yr_trades = []
            for d_str, day_group in test_cands.groupby('d2_date_str'):
                seen_plates = set()
                picks_count = 0
                for _, r in day_group.iterrows():
                    p = r['plate']
                    if p in seen_plates:
                        continue
                    seen_plates.add(p)
                    picks_count += 1
                    
                    tr = simulate_trade_v5(r, price_lookup, all_trade_dates, date_to_idx, 
                                           exit_mode=exit_mode, regime_mode=regime_mode, use_touch_order=use_touch)
                    if tr:
                        tr['combo'] = combo_name
                        tr['test_year'] = test_yr
                        yr_trades.append(tr)
                        combo_trades.append(tr)
                        all_trades_ledger.append(tr)
                        
                    if picks_count >= max_sectors:
                        break
                        
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
                    'avg_win': round(float(avg_win), 4),
                    'avg_loss': round(float(avg_loss), 4),
                    'nav_1slot': round(float(nav_1s), 4),
                    'nav_2slot': round(float(nav_2s), 4),
                    'benchmark_csi300': yr_bench,
                    'excess_1slot': round(float(yr_excess), 4),
                }
                print(f"  {test_yr}: {yr_n:2d} trades | WinRate: {yr_wr*100:4.1f}% | 2B: {yr_2b_rate*100:4.1f}% | PnL: {pnl_ratio:4.2f} (Win: {avg_win*100:+.1f}%, Loss: {-avg_loss*100:.1f}%) | 1-Slot: {nav_1s:6.4f}x (Excess: {yr_excess*100:+6.2f}%) | 2-Slot: {nav_2s:6.4f}x")
            else:
                combo_yearly[test_yr] = {'trades_count': 0}
                print(f"  {test_yr}:  0 trades")
                
        df_combo = pd.DataFrame(combo_trades)
        total_n = len(df_combo)
        if total_n > 0:
            tot_wr = (df_combo['net_ret'] > 0).mean()
            wins = df_combo[df_combo['net_ret'] > 0]['net_ret']
            losses = df_combo[df_combo['net_ret'] <= 0]['net_ret']
            tot_win = wins.mean() if len(wins) > 0 else 0.0
            tot_loss = abs(losses.mean()) if len(losses) > 0 else 0.01
            tot_pnl = tot_win / tot_loss if tot_loss > 0 else 0.0
            tot_2b = df_combo['sealed_2b'].mean()
            tot_nav_1s, _, _ = simulate_portfolio_slots(combo_trades, num_slots=1)
            tot_nav_2s, _, _ = simulate_portfolio_slots(combo_trades, num_slots=2)
            
            # Big monster trades analysis (trades with net_ret >= +20%)
            big_monsters = df_combo[df_combo['net_ret'] >= 0.20]
            
            all_results[combo_name] = {
                'total_trades': total_n,
                'annual_trades_avg': round(total_n / 5.0, 1),
                'win_rate': round(float(tot_wr), 4),
                'pnl_ratio': round(float(tot_pnl), 2),
                'avg_win': round(float(tot_win), 4),
                'avg_loss': round(float(tot_loss), 4),
                'sealed_2b_rate': round(float(tot_2b), 4),
                'cum_nav_1slot': round(float(tot_nav_1s), 4),
                'cum_nav_2slot': round(float(tot_nav_2s), 4),
                'big_monster_trades_cnt': len(big_monsters),
                'yearly': combo_yearly
            }
            print(f"  => 5Y Total: {total_n} trades ({total_n/5.0:.1f}/yr) | WinRate: {tot_wr*100:4.1f}% | 2B: {tot_2b*100:4.1f}% | PnL: {tot_pnl:4.2f} (Win: {tot_win*100:+.1f}%, Loss: {-tot_loss*100:.1f}%) | Monsters(>=+20%): {len(big_monsters)} | 1-Slot: {tot_nav_1s:6.4f}x | 2-Slot: {tot_nav_2s:6.4f}x")

    with open(RESULTS_JSON, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    pd.DataFrame(all_trades_ledger).to_csv(TRADES_CSV, index=False, encoding='utf-8-sig')
    print(f"\nAll V5 results saved to: {RESULTS_JSON}")
    print(f"All V5 trades ledger saved to: {TRADES_CSV}")

if __name__ == '__main__':
    run_v5_pipeline()

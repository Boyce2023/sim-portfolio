#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ablation_8_exit_rules_5y.py
--------------------------------------------------------------------------------
Comprehensive 5-Year (2022-2026) Comparison of 8 Zero-Lookahead T+1 Exit Rules
on Standard 1-to-2 Selected Buy Pool (245 trades).
"""

import os
import sys
import json
import time
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
LEDGER_CSV = os.path.join(DATA_DIR, "clean_wf_1to2_v4_5_domain_ridge_ledger.csv")
A_DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
JSON_OUTPUT = os.path.join(DATA_DIR, "ablation_8_exit_rules_5y.json")

def simulate_portfolio_slots(trades, num_slots=1, initial_capital=1000000.0):
    if not trades:
        return 1.0, 0.0, [1.0]
    df_trades = pd.DataFrame(trades).sort_values('buy_date').reset_index(drop=True)
    all_dates = sorted(list(set(df_trades['buy_date'].tolist() + df_trades['exit_date'].tolist())))
    
    slots = [{'cash': initial_capital / num_slots, 'stock': None, 'shares': 0, 'exit_date': None, 'exit_price': 0, 'net_ret': 0} for _ in range(num_slots)]
    daily_equity = []
    
    date_to_trades = {}
    for _, tr in df_trades.iterrows():
        b_d = tr['buy_date']
        if b_d not in date_to_trades:
            date_to_trades[b_d] = []
        date_to_trades[b_d].append(tr)
        
    date_to_exits = {}
    for _, tr in df_trades.iterrows():
        e_d = tr['exit_date']
        if e_d not in date_to_exits:
            date_to_exits[e_d] = []
        date_to_exits[e_d].append(tr)

    equity_curve = [1.0]
    total_cap = initial_capital
    
    for d in all_dates:
        # Free up slots exiting today
        for slot in slots:
            if slot['stock'] is not None and slot['exit_date'] <= d:
                # slot freed
                total_ret = slot['net_ret']
                slot['cash'] = slot['cash'] * (1.0 + total_ret)
                slot['stock'] = None
                slot['exit_date'] = None
                
        # Allocate new buys today
        if d in date_to_trades:
            for tr in date_to_trades[d]:
                # find free slot
                free_slots = [s for s in slots if s['stock'] is None]
                if free_slots:
                    target_slot = free_slots[0]
                    target_slot['stock'] = tr['code']
                    target_slot['exit_date'] = tr['exit_date']
                    target_slot['net_ret'] = tr['net_ret']
                    
        curr_total = sum(s['cash'] * (1.0 if s['stock'] is None else (1.0 + s['net_ret'] * 0.5)) for s in slots)
        equity_curve.append(curr_total / initial_capital)
        
    final_nav = sum(s['cash'] for s in slots) / initial_capital
    peak = 1.0
    max_dd = 0.0
    for nav in equity_curve:
        if nav > peak:
            peak = nav
        dd = (peak - nav) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return final_nav, max_dd, equity_curve

def load_price_lookup():
    print(">>> Loading price dataset...")
    cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close']
    ds_act = ds.dataset(A_DAILY_PATH, format="parquet")
    df_act = ds_act.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2021-12-01'))).to_table().to_pandas()
    df_del = pd.DataFrame()
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format="parquet")
        df_del = ds_del.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2021-12-01'))).to_table().to_pandas()
    df = pd.concat([df_act, df_del], ignore_index=True)
    df['code6'] = df['ticker'].astype(str).str.extract(r'(\d{6})')[0].fillna('').str.zfill(6)
    df = df[df['code6'].str.startswith(('00', '60'))].copy()
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df.sort_values(['code6', 'date_str'], inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    df['pre_close'] = df.groupby('code6')['close'].shift(1)
    df['zt_price'] = (df['pre_close'] * 1.10).round(2)
    df['dt_price'] = (df['pre_close'] * 0.90).round(2)
    df['is_zt'] = (df['close'] >= df['zt_price'] - 0.01) & (df['close'] == df['high']) & (df['pre_close'] > 0)
    df['is_yizi_dt'] = (df['open'] == df['dt_price']) & (df['close'] == df['dt_price']) & (df['high'] == df['dt_price']) & (df['low'] == df['dt_price'])
    
    # 5-day MA
    df['ma5'] = df.groupby('code6')['close'].transform(lambda s: s.rolling(5).mean())
    
    price_lookup = {}
    for r in df.itertuples(index=False):
        price_lookup[(r.code6, r.date_str)] = {
            'open': r.open,
            'high': r.high,
            'low': r.low,
            'close': r.close,
            'pre_close': r.pre_close,
            'zt_price': r.zt_price,
            'dt_price': r.dt_price,
            'is_zt': r.is_zt,
            'is_yizi_dt': r.is_yizi_dt,
            'ma5': r.ma5
        }
    all_trade_dates = sorted(df['date_str'].unique())
    date_to_idx = {d: i for i, d in enumerate(all_trade_dates)}
    return price_lookup, all_trade_dates, date_to_idx

def run_ablation():
    price_lookup, all_trade_dates, date_to_idx = load_price_lookup()
    
    # Load candidate pool: 245 trades from V4_5_Selected50_P2_TouchProtect
    ledger = pd.read_csv(LEDGER_CSV)
    base_pool = ledger[ledger['combo'] == 'V4_5_Selected50_P2_TouchProtect'].copy()
    base_pool['code6'] = base_pool['code'].astype(str).str.split('.').str[0].str.zfill(6)
    print(f"Base pool size: {len(base_pool)} buy signals from 2022 to 2026.")
    
    rules = ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"]
    rule_descriptions = {
        "E1": "D3 09:25 无脑开盘全卖",
        "E2": "V4.5 P2规则 (非涨停开盘全卖 + 涨停开盘挂2%条件单)",
        "E3": "老策略83行 (14:55看收涨继续拿，收跌/走平卖出)",
        "E4": "游资经典断板收盘走 (封死涨停死拿，未封死14:55按收盘卖)",
        "E5": "弱开早走+强开博连板 (绿盘<-1%开盘走，平高开拿至收盘，盘中-5%硬保护)",
        "E6": "50% D3早盘锁利 + 50% 连板格局分仓法",
        "E7": "老策略strategy1 (涨停或收真阳线继续拿，收阴/收跌/破5日均线卖)",
        "E8": "连板+严重异动主动止盈 (同E5，但累计10日涨幅达异动线或5板板上主动止盈)"
    }
    
    results = {}
    
    for rule in rules:
        rule_trades = []
        for _, row in base_pool.iterrows():
            code = row['code6']
            buy_date = row['buy_date']
            buy_price = row['buy_price']
            sealed_2b = row['sealed_2b']
            
            idx_d2 = date_to_idx.get(buy_date)
            if idx_d2 is None:
                continue
                
            curr_idx = idx_d2 + 1
            exit_price = None
            exit_date = None
            prev_close = buy_price
            holding_days = 0
            
            # Simulate according to rule
            if rule == "E1":
                # E1: Sell at D3 09:25 open regardless
                while curr_idx < len(all_trade_dates):
                    d_curr = all_trade_dates[curr_idx]
                    info = price_lookup.get((code, d_curr))
                    if not info:
                        exit_price = prev_close
                        exit_date = d_curr
                        break
                    if info['is_yizi_dt']:
                        curr_idx += 1
                        prev_close = info['close']
                        continue
                    else:
                        exit_price = info['open']
                        exit_date = d_curr
                        break
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
                gross_ret = exit_price / buy_price - 1.0
                net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0
                
            elif rule == "E2":
                # E2: V4.5 P2
                if not sealed_2b:
                    # D2 not sealed: sell D3 open
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = info['close']
                            continue
                        else:
                            exit_price = info['open']
                            exit_date = d_curr
                            break
                else:
                    # D2 sealed
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        o, h, l, c, zt = info['open'], info['high'], info['low'], info['close'], info['zt_price']
                        if o < zt - 0.01:
                            if info['is_yizi_dt']:
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

            elif rule == "E3":
                # E3: strategy_astock line 83: if sealed_2b == 0: exit D3 open; if sealed_2b == 1: at 14:55 if c > prev_close hold, else sell at c
                if not sealed_2b:
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = info['close']
                            continue
                        else:
                            exit_price = info['open']
                            exit_date = d_curr
                            break
                else:
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        o, h, l, c, pc = info['open'], info['high'], info['low'], info['close'], info['pre_close']
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = c
                            continue
                        if c > pc: # Daily gain > 0%: hold!
                            prev_close = c
                            curr_idx += 1
                            continue
                        else: # Daily gain <= 0%: sell at close
                            exit_price = c
                            exit_date = d_curr
                            break
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
                gross_ret = exit_price / buy_price - 1.0
                net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0

            elif rule == "E4":
                # E4: Classic "Exit on break": if sealed_2b == 0 exit D3 open; if sealed_2b == 1: if is_zt hold, not is_zt sell at c
                if not sealed_2b:
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = info['close']
                            continue
                        else:
                            exit_price = info['open']
                            exit_date = d_curr
                            break
                else:
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        c, is_zt = info['close'], info['is_zt']
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = c
                            continue
                        if is_zt:
                            prev_close = c
                            curr_idx += 1
                            continue
                        else:
                            exit_price = c
                            exit_date = d_curr
                            break
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
                gross_ret = exit_price / buy_price - 1.0
                net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0

            elif rule == "E5":
                # E5: Weak open early exit + strong open ride (open < -1% sell open; else stop_loss -5%, else if is_zt hold, else sell c)
                if not sealed_2b:
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = info['close']
                            continue
                        else:
                            exit_price = info['open']
                            exit_date = d_curr
                            break
                else:
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        o, h, l, c, pc, is_zt = info['open'], info['high'], info['low'], info['close'], info['pre_close'], info['is_zt']
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = c
                            continue
                        # If open < pc * 0.99: sell at open
                        if o < pc * 0.99:
                            exit_price = o
                            exit_date = d_curr
                            break
                        # Else intraday stop at pc * 0.95
                        stop_px = round(pc * 0.95, 2)
                        if l <= stop_px:
                            exit_price = stop_px
                            exit_date = d_curr
                            break
                        if is_zt:
                            prev_close = c
                            curr_idx += 1
                            continue
                        else:
                            exit_price = c
                            exit_date = d_curr
                            break
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
                gross_ret = exit_price / buy_price - 1.0
                net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0

            elif rule == "E6":
                # E6: 50% D3 morning lock + 50% E5 ride
                # Part 1: exit at D3 open if not zt open
                d3_idx = idx_d2 + 1
                ret_p1 = None
                p1_exit_date = None
                if not sealed_2b:
                    # All exit at D3 open
                    pass
                # Let's compute part 1 and part 2:
                # Part 1: D3 open exit
                curr1 = idx_d2 + 1
                p1_px = None
                while curr1 < len(all_trade_dates):
                    d_c = all_trade_dates[curr1]
                    inf = price_lookup.get((code, d_c))
                    if not inf:
                        p1_px = prev_close
                        p1_exit_date = d_c
                        break
                    if inf['is_yizi_dt']:
                        curr1 += 1
                        continue
                    else:
                        p1_px = inf['open']
                        p1_exit_date = d_c
                        break
                if p1_px is None:
                    p1_px = buy_price
                    p1_exit_date = all_trade_dates[min(curr1, len(all_trade_dates)-1)]
                ret_p1 = (p1_px / buy_price - 1.0)
                
                # Part 2: exactly E5
                # simulate E5 logic
                curr2 = idx_d2 + 1
                p2_px = None
                p2_exit_date = None
                p2_prev_c = buy_price
                if not sealed_2b:
                    p2_px = p1_px
                    p2_exit_date = p1_exit_date
                else:
                    while curr2 < len(all_trade_dates):
                        d_c = all_trade_dates[curr2]
                        inf = price_lookup.get((code, d_c))
                        if not inf:
                            p2_px = p2_prev_c
                            p2_exit_date = d_c
                            break
                        o, h, l, c, pc, is_zt = inf['open'], inf['high'], inf['low'], inf['close'], inf['pre_close'], inf['is_zt']
                        if inf['is_yizi_dt']:
                            curr2 += 1
                            p2_prev_c = c
                            continue
                        if o < pc * 0.99:
                            p2_px = o
                            p2_exit_date = d_c
                            break
                        stop_px = round(pc * 0.95, 2)
                        if l <= stop_px:
                            p2_px = stop_px
                            p2_exit_date = d_c
                            break
                        if is_zt:
                            p2_prev_c = c
                            curr2 += 1
                            continue
                        else:
                            p2_px = c
                            p2_exit_date = d_c
                            break
                    if p2_px is None:
                        p2_px = p2_prev_c
                        p2_exit_date = all_trade_dates[min(curr2, len(all_trade_dates)-1)]
                ret_p2 = (p2_px / buy_price - 1.0)
                
                if not sealed_2b:
                    gross_ret = ret_p1
                    exit_price = p1_px
                    exit_date = p1_exit_date
                    holding_days = max(1, curr1 - idx_d2)
                else:
                    gross_ret = 0.5 * ret_p1 + 0.5 * ret_p2
                    exit_price = round(0.5 * p1_px + 0.5 * p2_px, 2)
                    exit_date = max(p1_exit_date, p2_exit_date)
                    holding_days = max(1, max(curr1, curr2) - idx_d2)
                net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0

            elif rule == "E7":
                # E7: strategy1 style: hold if is_zt or (c >= o and c > pre_close); if c < o or c <= pre_close or c < ma5: exit at c
                if not sealed_2b:
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = info['close']
                            continue
                        else:
                            exit_price = info['open']
                            exit_date = d_curr
                            break
                else:
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        o, h, l, c, pc, is_zt, ma5 = info['open'], info['high'], info['low'], info['close'], info['pre_close'], info['is_zt'], info['ma5']
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = c
                            continue
                        # Hold if limit-up OR (strong real candle: c >= o and c > pc and (ma5 is None or c >= ma5))
                        is_strong = is_zt or (c >= o and c > pc and (ma5 is None or np.isnan(ma5) or c >= ma5))
                        if is_strong:
                            prev_close = c
                            curr_idx += 1
                            continue
                        else:
                            exit_price = c
                            exit_date = d_curr
                            break
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
                gross_ret = exit_price / buy_price - 1.0
                net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0

            elif rule == "E8":
                # E8: E5 + Abnormal Deviation Profit Taking (cumulative streak >= 5 boards or cumulative gain >= 95%)
                if not sealed_2b:
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = info['close']
                            continue
                        else:
                            exit_price = info['open']
                            exit_date = d_curr
                            break
                else:
                    streak = 1 # D2 is 2nd board
                    while curr_idx < len(all_trade_dates):
                        d_curr = all_trade_dates[curr_idx]
                        info = price_lookup.get((code, d_curr))
                        if not info:
                            exit_price = prev_close
                            exit_date = d_curr
                            break
                        o, h, l, c, pc, is_zt = info['open'], info['high'], info['low'], info['close'], info['pre_close'], info['is_zt']
                        if info['is_yizi_dt']:
                            curr_idx += 1
                            prev_close = c
                            continue
                            
                        # Check serious abnormal condition: 5 boards or gain >= 90%
                        cum_gain = c / buy_price - 1.0
                        if is_zt:
                            streak += 1
                            if streak >= 5 or cum_gain >= 0.85:
                                # Take profit at limit up close!
                                exit_price = c
                                exit_date = d_curr
                                break
                            prev_close = c
                            curr_idx += 1
                            continue
                            
                        if o < pc * 0.99:
                            exit_price = o
                            exit_date = d_curr
                            break
                        stop_px = round(pc * 0.95, 2)
                        if l <= stop_px:
                            exit_price = stop_px
                            exit_date = d_curr
                            break
                        exit_price = c
                        exit_date = d_curr
                        break
                if exit_price is None:
                    exit_price = prev_close
                    exit_date = all_trade_dates[min(curr_idx, len(all_trade_dates)-1)]
                holding_days = max(1, curr_idx - idx_d2)
                gross_ret = exit_price / buy_price - 1.0
                net_ret = (1.0 + gross_ret) * (1.0 - 0.0015) - 1.0

            rule_trades.append({
                'code': code,
                'name': row['name'],
                'buy_date': buy_date,
                'buy_price': buy_price,
                'exit_date': exit_date,
                'exit_price': exit_price,
                'holding_days': holding_days,
                'gross_ret': round(gross_ret, 4),
                'net_ret': round(net_ret, 4),
                'rule': rule
            })
            
        df_r = pd.DataFrame(rule_trades)
        n = len(df_r)
        wr = (df_r['net_ret'] > 0).mean()
        wins = df_r[df_r['net_ret'] > 0]['net_ret']
        losses = df_r[df_r['net_ret'] <= 0]['net_ret']
        avg_w = wins.mean() if len(wins) > 0 else 0.0
        avg_l = abs(losses.mean()) if len(losses) > 0 else 0.01
        payoff = avg_w / avg_l if avg_l > 0 else 0.0
        max_profit = df_r['net_ret'].max()
        count_ge_30 = int((df_r['net_ret'] >= 0.30).sum())
        count_le_minus_10 = int((df_r['net_ret'] <= -0.10).sum())
        
        nav_1s, mdd_1s, _ = simulate_portfolio_slots(rule_trades, num_slots=1)
        nav_2s, mdd_2s, _ = simulate_portfolio_slots(rule_trades, num_slots=2)
        
        results[rule] = {
            'rule_name': rule,
            'description': rule_descriptions[rule],
            'total_trades': n,
            'win_rate': round(float(wr), 4),
            'payoff_ratio': round(float(payoff), 2),
            'avg_win_pct': round(float(avg_w * 100), 2),
            'avg_loss_pct': round(float(avg_l * 100), 2),
            'max_profit': round(float(max_profit), 4),
            'count_ge_30': count_ge_30,
            'count_le_minus_10': count_le_minus_10,
            'cum_nav_1slot': round(float(nav_1s), 4),
            'max_drawdown_1slot': round(float(mdd_1s), 4),
            'cum_nav_2slot': round(float(nav_2s), 4),
            'max_drawdown_2slot': round(float(mdd_2s), 4),
            'avg_holding_days': round(float(df_r['holding_days'].mean()), 2)
        }
        print(f"[{rule}] WR: {wr:.2%}, Payoff: {payoff:.2f}, MaxProf: {max_profit:.2%}, >=30%: {count_ge_30}, <=-10%: {count_le_minus_10}, Nav1: {nav_1s:.2f}, MDD1: {mdd_1s:.2%}, Nav2: {nav_2s:.2f}")

    with open(JSON_OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved results to {JSON_OUTPUT}")

if __name__ == '__main__':
    run_ablation()

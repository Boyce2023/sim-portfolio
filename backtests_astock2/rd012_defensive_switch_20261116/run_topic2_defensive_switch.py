#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_topic2_defensive_switch.py
================================================================================
课题二：退潮与大跌日「板块突然切换」防御小策略深度回测（2021-01 至 2026-11 全样本）
实证检验两大分支：
分支 A：科技大退潮日 -> 切换买消费（白酒核心大票、白酒最强前排、生猪核心龙头）
分支 B：大盘下跌日 -> 切换买银行（国有四大行、高ROE绩优城商行、当日银行最抗跌前排）

严格防伪要求：
1. 扣除千二双边真实摩擦 (0.002)
2. 绝对净收益率与绝对赚钱胜率 (net_ret > 0)
3. 相对同期沪深300超额收益与超额胜率
4. 时代环境差异拆解 (2021-2023 vs 2024-2026)
5. 盘面特征拆解 (缩量阴跌护盘 vs 放量暴跌泥沙俱下 vs 结构性分化)
6. T0 尾盘买 (14:55收盘价) vs T+1 早盘买 (09:25开盘价)，持仓 1/3/5/10 天
================================================================================
"""
import os, sys, json, time
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock2/p6_small_strategies_20261116"
os.makedirs(OUT_DIR, exist_ok=True)

A_DAILY_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
INDEX_CACHE_PATH = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
INDUSTRY_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/industry.csv"

FEE_RATE = 0.0020  # 双边千二摩擦

# Asset baskets:
LIQUOR_CORE = ['600519', '000858', '000568', '600809'] # 贵州茅台、五粮液、泸州老窖、山西汾酒
PIG_CORE = ['002714', '300498', '603477'] # 牧原股份、温氏股份、巨星农牧
BANK_BIG4 = ['601398', '601288', '601988', '601939'] # 工商银行、农业银行、中国银行、建设银行
BANK_HIGH_ROE = ['600036', '600919', '601838', '600926', '002142'] # 招商银行、江苏银行、成都银行、杭州银行、宁波银行

def load_index_hs300():
    with open(INDEX_CACHE_PATH) as f:
        d = json.load(f)
    hs = d['sh000300']
    s = pd.Series(hs)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()

def load_industry_and_names():
    df_ind = pd.read_csv(INDUSTRY_PATH)
    name_map = dict(zip(df_ind['code'].str[3:], df_ind['code_name']))
    ind_map = dict(zip(df_ind['code'].str[3:], df_ind['industry']))
    return name_map, ind_map

def load_data():
    print("[1/5] Loading price data from 2020-11-01 to 2026-11-13...")
    cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'amount', 'volume', 'turn', 'oshare']
    ds_act = ds.dataset(A_DAILY_PATH, format='parquet')
    df_act = ds_act.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2020-11-01'))).to_table().to_pandas()
    parts = [df_act]
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format='parquet')
        df_del = ds_del.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2020-11-01'))).to_table().to_pandas()
        parts.append(df_del)
    df = pd.concat(parts, ignore_index=True)
    df['c6'] = df['ticker'].astype(str).str[:6]
    df = df[df['c6'].str.startswith(('00', '60', '30')) & (~df['ticker'].str.endswith('.BJ'))].copy()
    df['dt_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df.sort_values(['c6', 'dt_str'], inplace=True)
    df.drop_duplicates(subset=['c6', 'dt_str'], keep='first', inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    g = df.groupby('c6')
    df['pre_c'] = g['close'].shift(1)
    df['pct'] = df['close'] / df['pre_c'] - 1.0
    df['o_pct'] = df['open'] / df['pre_c'] - 1.0
    
    # Forward prices up to 10 days
    for k in range(1, 11):
        df[f'fwd_c_{k}'] = g['close'].shift(-k)
        df[f'fwd_o_{k}'] = g['open'].shift(-k)
        df[f'fwd_dt_{k}'] = g['dt_str'].shift(-k)
        
    print(f"Loaded {len(df):,} price records.")
    return df

print("Starting Topic 2 execution...")
hs300_s = load_index_hs300()
hs300_ret = hs300_s.pct_change()
name_map, ind_map = load_industry_and_names()
df = load_data()

# Identify Tech, Liquor, Pig, Bank stocks
tech_codes = set([c for c, ind in ind_map.items() if str(ind).startswith(('C39', 'I65', 'I63'))])
liquor_all = set([c for c, ind in ind_map.items() if str(ind).startswith('C15') and any(k in name_map.get(c,'') for k in ['酒', '茅台', '五粮液', '汾酒', '老窖'])])
pig_all = set([c for c, ind in ind_map.items() if (str(ind).startswith('A03') or '畜牧' in str(ind)) and any(k in name_map.get(c,'') for k in ['牧原', '温氏', '巨星', '新希望', '天邦', '傲农', '唐人神', '大北农'])])
bank_all = set([c for c, ind in ind_map.items() if str(ind).startswith('J66') and any(k in name_map.get(c,'') for k in ['银行'])])

print(f"Tech stocks: {len(tech_codes)}, Liquor stocks: {len(liquor_all)}, Pig stocks: {len(pig_all)}, Bank stocks: {len(bank_all)}")

# Daily Market aggregates
print("[2/5] Computing daily market & sector aggregates...")
all_dts = sorted(df['dt_str'].unique())

# Map: dt -> daily metrics
daily_stats = {}
df_by_dt = df.groupby('dt_str')

for dt, grp in df_by_dt:
    if dt < '2021-01-01':
        continue
    # Tech daily return
    t_grp = grp[grp['c6'].isin(tech_codes)]
    tech_mean_pct = t_grp['pct'].mean() if len(t_grp) > 0 else 0.0
    tech_amount = t_grp['amount'].sum() if len(t_grp) > 0 else 0.0
    
    # All market return & volume
    mkt_mean_pct = grp['pct'].mean()
    mkt_amount = grp['amount'].sum()
    tech_amt_share = (tech_amount / mkt_amount) if mkt_amount > 0 else 0.0
    
    # Limit down count (<= -9.5% on main/gem)
    dt_cnt = (grp['pct'] <= -0.095).sum()
    
    # HS300 return on dt
    t_dt = pd.to_datetime(dt)
    hs_ret_day = hs300_ret.get(t_dt, np.nan)
    if np.isnan(hs_ret_day):
        hs_ret_day = mkt_mean_pct # fallback
        
    daily_stats[dt] = {
        'tech_ret': tech_mean_pct,
        'tech_amt_share': tech_amt_share,
        'mkt_ret': mkt_mean_pct,
        'mkt_amount': mkt_amount,
        'dt_cnt': int(dt_cnt),
        'hs300_ret': float(hs_ret_day),
    }

df_daily_stats = pd.DataFrame.from_dict(daily_stats, orient='index')
df_daily_stats.index.name = 'dt_str'
df_daily_stats['mkt_amt_ma20'] = df_daily_stats['mkt_amount'].rolling(20, min_periods=5).mean()
df_daily_stats['tech_ret_20d'] = df_daily_stats['tech_ret'].rolling(20, min_periods=5).sum()
df_daily_stats['hs300_ret_5d'] = df_daily_stats['hs300_ret'].rolling(5, min_periods=3).sum()

print("Daily aggregates computed.")

# ==============================================================================
# Helper for Trade Simulation
# ==============================================================================
def calc_trade_metrics(trades_list):
    if not trades_list:
        return {
            'trades': 0, 'win_rate': 0.0, 'avg_net_ret': 0.0, 'win_loss_ratio': 0.0,
            'max_drawdown': 0.0, 'cum_net_ret': 0.0, 'hs300_excess': 0.0, 'excess_win_rate': 0.0
        }
    df_t = pd.DataFrame(trades_list)
    cnt = len(df_t)
    win_rate = (df_t['net_ret'] > 0).mean()
    excess_win_rate = (df_t['excess_ret'] > 0).mean()
    avg_net = df_t['net_ret'].mean()
    avg_excess = df_t['excess_ret'].mean()
    
    wins = df_t[df_t['net_ret'] > 0]['net_ret']
    losses = df_t[df_t['net_ret'] <= 0]['net_ret']
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 1e-6
    wl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    
    # Date compounding
    date_rets = df_t.groupby('buy_dt')['net_ret'].mean()
    cum_eq = (1.0 + date_rets).cumprod()
    cum_ret = cum_eq.iloc[-1] - 1.0 if len(cum_eq) > 0 else 0.0
    running_max = cum_eq.cummax()
    dd = (cum_eq - running_max) / running_max
    mdd = abs(dd.min()) if len(dd) > 0 else 0.0
    
    date_excess = df_t.groupby('buy_dt')['excess_ret'].mean()
    cum_exc = (1.0 + date_excess).cumprod().iloc[-1] - 1.0 if len(date_excess) > 0 else 0.0
    
    return {
        'trades': int(cnt),
        'win_rate': float(win_rate),
        'excess_win_rate': float(excess_win_rate),
        'avg_net_ret': float(avg_net),
        'avg_excess_ret': float(avg_excess),
        'win_loss_ratio': float(wl_ratio),
        'max_drawdown': float(mdd),
        'cum_net_ret': float(cum_ret),
        'hs300_excess': float(cum_exc),
    }

# ==============================================================================
# Part A: Tech Big Retreat -> Switch to Consumption
# ==============================================================================
print("\n[3/5] Running Branch A: Tech Retreat -> Switch to Consumption...")
# Evaluate across:
# 1. Tech Drop Thresholds: -2.0%, -2.5%, -3.0%
# 2. Entry Timing: T0 close vs T+1 open
# 3. Holding Days: 1, 3, 5, 10
# 4. Confirmation: Unconditional Blind vs Seesaw Confirmed (Target positive or outperforming tech >=3%, dt_cnt < 30)
# 5. Target Asset: Liquor Core, Liquor Top1, Pig Core

ledger_branch_a = []

for dt in df_daily_stats.index:
    row = df_daily_stats.loc[dt]
    tech_r = row['tech_ret']
    if tech_r > -0.02:
        continue # Not a tech retreat day
        
    dt_cnt = row['dt_cnt']
    mkt_r = row['mkt_ret']
    grp = df[df['dt_str'] == dt]
    
    # Targets on dt
    # 1. Liquor Core
    grp_liq_core = grp[grp['c6'].isin(LIQUOR_CORE)]
    # 2. Liquor Top Runner (highest pct on dt)
    grp_liq_all = grp[grp['c6'].isin(liquor_all)]
    liq_top1 = grp_liq_all.sort_values('pct', ascending=False).iloc[0]['c6'] if len(grp_liq_all) > 0 else None
    # 3. Pig Core
    grp_pig_core = grp[grp['c6'].isin(PIG_CORE)]
    
    # Target configurations to test
    targets = {
        'Liquor_Core': grp_liq_core,
        'Liquor_Top1': grp[grp['c6'] == liq_top1] if liq_top1 else pd.DataFrame(),
        'Pig_Core': grp_pig_core,
    }
    
    for t_name, t_df in targets.items():
        if len(t_df) == 0:
            continue
        t_ret_dt = t_df['pct'].mean()
        
        # Seesaw confirmation condition
        # Target closed green OR outperformed Tech by >= +3.0%, AND market not crash (dt_cnt < 30)
        seesaw_confirmed = ((t_ret_dt > 0.0) or (t_ret_dt - tech_r >= 0.03)) and (dt_cnt < 30)
        
        # Test holding 1, 3, 5, 10 days for both T0 close and T+1 open
        for hold_k in [1, 3, 5, 10]:
            # T0 close entry: buy at close of dt, exit at close of dt+hold_k
            # T+1 open entry: buy at open of dt+1, exit at close of dt+hold_k
            
            # Aggregate returns across target basket
            net_rets_t0 = []
            net_rets_t1 = []
            hs_rets_t0 = []
            hs_rets_t1 = []
            
            for _, stk_row in t_df.iterrows():
                px_c0 = stk_row['close']
                px_o1 = stk_row['fwd_o_1']
                px_exit = stk_row[f'fwd_c_{hold_k}']
                exit_dt = stk_row[f'fwd_dt_{hold_k}']
                
                if pd.isna(px_exit) or px_exit <= 0:
                    continue
                    
                # T0 close
                if px_c0 > 0:
                    net_t0 = (px_exit * (1.0 - FEE_RATE)) / (px_c0 * (1.0 + FEE_RATE)) - 1.0
                    net_rets_t0.append(net_t0)
                    # HS300 return
                    hs_sub0 = hs300_s[(hs300_s.index >= pd.to_datetime(dt)) & (hs300_s.index <= pd.to_datetime(exit_dt))]
                    hs_ret0 = (hs_sub0.iloc[-1] / hs_sub0.iloc[0] - 1.0) if len(hs_sub0) >= 2 else 0.0
                    hs_rets_t0.append(hs_ret0)
                    
                # T+1 open
                if px_o1 > 0:
                    net_t1 = (px_exit * (1.0 - FEE_RATE)) / (px_o1 * (1.0 + FEE_RATE)) - 1.0
                    net_rets_t1.append(net_t1)
                    # HS300 return
                    dt1_str = stk_row['fwd_dt_1']
                    hs_sub1 = hs300_s[(hs300_s.index >= pd.to_datetime(dt1_str)) & (hs300_s.index <= pd.to_datetime(exit_dt))]
                    hs_ret1 = (hs_sub1.iloc[-1] / hs_sub1.iloc[0] - 1.0) if len(hs_sub1) >= 2 else 0.0
                    hs_rets_t1.append(hs_ret1)
                    
            if net_rets_t0:
                mean_net_t0 = np.mean(net_rets_t0)
                mean_hs_t0 = np.mean(hs_rets_t0)
                ledger_branch_a.append({
                    'branch': 'A_TechRetreat_Consumption',
                    'dt': dt,
                    'tech_ret': tech_r,
                    'dt_cnt': dt_cnt,
                    'target': t_name,
                    'entry_timing': 'T0_Close',
                    'hold_days': hold_k,
                    'seesaw_confirmed': seesaw_confirmed,
                    'net_ret': mean_net_t0,
                    'hs_ret': mean_hs_t0,
                    'excess_ret': mean_net_t0 - mean_hs_t0,
                    'buy_dt': dt,
                })
                
            if net_rets_t1:
                mean_net_t1 = np.mean(net_rets_t1)
                mean_hs_t1 = np.mean(hs_rets_t1)
                ledger_branch_a.append({
                    'branch': 'A_TechRetreat_Consumption',
                    'dt': dt,
                    'tech_ret': tech_r,
                    'dt_cnt': dt_cnt,
                    'target': t_name,
                    'entry_timing': 'T1_Open',
                    'hold_days': hold_k,
                    'seesaw_confirmed': seesaw_confirmed,
                    'net_ret': mean_net_t1,
                    'hs_ret': mean_hs_t1,
                    'excess_ret': mean_net_t1 - mean_hs_t1,
                    'buy_dt': dt,
                })

df_branch_a = pd.DataFrame(ledger_branch_a)
print(f"Total Branch A simulated rows: {len(df_branch_a)}")

# ==============================================================================
# Part B: Market Drop -> Switch to Bank
# ==============================================================================
print("\n[4/5] Running Branch B: Market Drop -> Switch to Bank...")
# Evaluate across:
# 1. Market Drop Triggers: HS300 <= -1.0%, <= -1.5%, <= -2.0%
# 2. Era: 2021-2023 vs 2024-2026
# 3. Market Patterns:
#    - Pattern 1: Low-volume Bleed + Bank Green (mkt_amount < mkt_amt_ma20 and bank_ret > 0)
#    - Pattern 2: High-volume Panic Crash (mkt_amount >= mkt_amt_ma20 and hs300 <= -2.0%)
#    - Pattern 3: Structural Divergence (tech_ret <= -2.5% but hs300 > -1.0%)
# 4. Target Bank Assets: Bank Big4, Bank High-ROE, Bank Top2
# 5. Entry Timing: T0 close vs T+1 open
# 6. Holding Days: 1, 3, 5, 10

ledger_branch_b = []

for dt in df_daily_stats.index:
    row = df_daily_stats.loc[dt]
    hs_ret_day = row['hs300_ret']
    tech_r = row['tech_ret']
    amt = row['mkt_amount']
    amt_ma = row['mkt_amt_ma20']
    
    # Check if meets any market drop trigger or structural divergence
    is_drop_10 = (hs_ret_day <= -0.010)
    is_drop_15 = (hs_ret_day <= -0.015)
    is_drop_20 = (hs_ret_day <= -0.020)
    is_struct_div = (tech_r <= -0.025 and hs_ret_day > -0.010)
    
    if not (is_drop_10 or is_struct_div):
        continue
        
    grp = df[df['dt_str'] == dt]
    
    # Bank targets
    grp_big4 = grp[grp['c6'].isin(BANK_BIG4)]
    grp_high_roe = grp[grp['c6'].isin(BANK_HIGH_ROE)]
    grp_bank_all = grp[grp['c6'].isin(bank_all)]
    top2_codes = grp_bank_all.sort_values('pct', ascending=False)['c6'].head(2).tolist()
    grp_top2 = grp[grp['c6'].isin(top2_codes)]
    
    bank_mean_ret = grp_bank_all['pct'].mean() if len(grp_bank_all) > 0 else 0.0
    
    # Patterns
    is_pattern1 = (amt < amt_ma) and (bank_mean_ret > 0.0) # Bleed + State team bank green
    is_pattern2 = (amt >= amt_ma) and is_drop_20 # Panic crash
    is_pattern3 = is_struct_div # Structural divergence
    
    era = '2021_2023' if dt < '2024-01-01' else '2024_2026'
    
    bank_targets = {
        'Bank_Big4': grp_big4,
        'Bank_High_ROE': grp_high_roe,
        'Bank_Top2': grp_top2,
    }
    
    for t_name, t_df in bank_targets.items():
        if len(t_df) == 0:
            continue
            
        for hold_k in [1, 3, 5, 10]:
            net_rets_t0 = []
            net_rets_t1 = []
            hs_rets_t0 = []
            hs_rets_t1 = []
            
            for _, stk_row in t_df.iterrows():
                px_c0 = stk_row['close']
                px_o1 = stk_row['fwd_o_1']
                px_exit = stk_row[f'fwd_c_{hold_k}']
                exit_dt = stk_row[f'fwd_dt_{hold_k}']
                
                if pd.isna(px_exit) or px_exit <= 0:
                    continue
                    
                # T0 close
                if px_c0 > 0:
                    net_t0 = (px_exit * (1.0 - FEE_RATE)) / (px_c0 * (1.0 + FEE_RATE)) - 1.0
                    net_rets_t0.append(net_t0)
                    hs_sub0 = hs300_s[(hs300_s.index >= pd.to_datetime(dt)) & (hs300_s.index <= pd.to_datetime(exit_dt))]
                    hs_ret0 = (hs_sub0.iloc[-1] / hs_sub0.iloc[0] - 1.0) if len(hs_sub0) >= 2 else 0.0
                    hs_rets_t0.append(hs_ret0)
                    
                # T+1 open
                if px_o1 > 0:
                    net_t1 = (px_exit * (1.0 - FEE_RATE)) / (px_o1 * (1.0 + FEE_RATE)) - 1.0
                    net_rets_t1.append(net_t1)
                    dt1_str = stk_row['fwd_dt_1']
                    hs_sub1 = hs300_s[(hs300_s.index >= pd.to_datetime(dt1_str)) & (hs300_s.index <= pd.to_datetime(exit_dt))]
                    hs_ret1 = (hs_sub1.iloc[-1] / hs_sub1.iloc[0] - 1.0) if len(hs_sub1) >= 2 else 0.0
                    hs_rets_t1.append(hs_ret1)
                    
            if net_rets_t0:
                mean_net_t0 = np.mean(net_rets_t0)
                mean_hs_t0 = np.mean(hs_rets_t0)
                ledger_branch_b.append({
                    'branch': 'B_MarketDrop_Bank',
                    'dt': dt,
                    'hs300_ret_day': hs_ret_day,
                    'is_drop_15': is_drop_15,
                    'is_drop_20': is_drop_20,
                    'era': era,
                    'pattern': 'Pattern1_Bleed_BankGreen' if is_pattern1 else ('Pattern2_Panic_Crash' if is_pattern2 else ('Pattern3_Struct_Div' if is_pattern3 else 'Other_Drop')),
                    'target': t_name,
                    'entry_timing': 'T0_Close',
                    'hold_days': hold_k,
                    'net_ret': mean_net_t0,
                    'hs_ret': mean_hs_t0,
                    'excess_ret': mean_net_t0 - mean_hs_t0,
                    'buy_dt': dt,
                })
                
            if net_rets_t1:
                mean_net_t1 = np.mean(net_rets_t1)
                mean_hs_t1 = np.mean(hs_rets_t1)
                ledger_branch_b.append({
                    'branch': 'B_MarketDrop_Bank',
                    'dt': dt,
                    'hs300_ret_day': hs_ret_day,
                    'is_drop_15': is_drop_15,
                    'is_drop_20': is_drop_20,
                    'era': era,
                    'pattern': 'Pattern1_Bleed_BankGreen' if is_pattern1 else ('Pattern2_Panic_Crash' if is_pattern2 else ('Pattern3_Struct_Div' if is_pattern3 else 'Other_Drop')),
                    'target': t_name,
                    'entry_timing': 'T1_Open',
                    'hold_days': hold_k,
                    'net_ret': mean_net_t1,
                    'hs_ret': mean_hs_t1,
                    'excess_ret': mean_net_t1 - mean_hs_t1,
                    'buy_dt': dt,
                })

df_branch_b = pd.DataFrame(ledger_branch_b)
print(f"Total Branch B simulated rows: {len(df_branch_b)}")

# Save combined ledger
df_all_defensive = pd.concat([df_branch_a, df_branch_b], ignore_index=True)
df_all_defensive.to_csv(f"{OUT_DIR}/ledger_defensive_switch.csv", index=False, encoding='utf-8-sig')

# ==============================================================================
# Aggregate & Summarize Results
# ==============================================================================
print("\n[5/5] Compiling Strategy Grid Summaries...")

summary_defensive = {}

# 1. Branch A Grids
summary_defensive['Branch_A'] = {}

# Blind vs Seesaw Confirmed for Liquor Core & Pig Core (T0 Close, 3 days hold)
for target in ['Liquor_Core', 'Liquor_Top1', 'Pig_Core']:
    summary_defensive['Branch_A'][target] = {}
    for entry in ['T0_Close', 'T1_Open']:
        summary_defensive['Branch_A'][target][entry] = {}
        for hold_k in [1, 3, 5, 10]:
            sub_blind = df_branch_a[(df_branch_a['target'] == target) & (df_branch_a['entry_timing'] == entry) & (df_branch_a['hold_days'] == hold_k)]
            sub_confirmed = sub_blind[sub_blind['seesaw_confirmed'] == True]
            summary_defensive['Branch_A'][target][entry][f'hold_{hold_k}d'] = {
                'blind': calc_trade_metrics(sub_blind.to_dict('records')),
                'seesaw_confirmed': calc_trade_metrics(sub_confirmed.to_dict('records'))
            }

# 2. Branch B Grids
summary_defensive['Branch_B'] = {}

for target in ['Bank_Big4', 'Bank_High_ROE', 'Bank_Top2']:
    summary_defensive['Branch_B'][target] = {}
    # Overall
    summary_defensive['Branch_B'][target]['Overall_Drop15_T0_Hold3d'] = calc_trade_metrics(
        df_branch_b[(df_branch_b['target'] == target) & (df_branch_b['is_drop_15'] == True) & (df_branch_b['entry_timing'] == 'T0_Close') & (df_branch_b['hold_days'] == 3)].to_dict('records')
    )
    # By Era
    summary_defensive['Branch_B'][target]['Era_2021_2023_Drop15_T0_Hold3d'] = calc_trade_metrics(
        df_branch_b[(df_branch_b['target'] == target) & (df_branch_b['is_drop_15'] == True) & (df_branch_b['era'] == '2021_2023') & (df_branch_b['entry_timing'] == 'T0_Close') & (df_branch_b['hold_days'] == 3)].to_dict('records')
    )
    summary_defensive['Branch_B'][target]['Era_2024_2026_Drop15_T0_Hold3d'] = calc_trade_metrics(
        df_branch_b[(df_branch_b['target'] == target) & (df_branch_b['is_drop_15'] == True) & (df_branch_b['era'] == '2024_2026') & (df_branch_b['entry_timing'] == 'T0_Close') & (df_branch_b['hold_days'] == 3)].to_dict('records')
    )
    # By Pattern
    for pat in ['Pattern1_Bleed_BankGreen', 'Pattern2_Panic_Crash', 'Pattern3_Struct_Div']:
        summary_defensive['Branch_B'][target][f'Pattern_{pat}'] = calc_trade_metrics(
            df_branch_b[(df_branch_b['target'] == target) & (df_branch_b['pattern'] == pat) & (df_branch_b['entry_timing'] == 'T0_Close') & (df_branch_b['hold_days'] == 3)].to_dict('records')
        )
    # Holding Period sensitivity (Drop 1.5%, T0 Close, 2024-2026 vs Full)
    for hold_k in [1, 3, 5, 10]:
        summary_defensive['Branch_B'][target][f'Full_Hold_{hold_k}d'] = calc_trade_metrics(
            df_branch_b[(df_branch_b['target'] == target) & (df_branch_b['is_drop_15'] == True) & (df_branch_b['entry_timing'] == 'T0_Close') & (df_branch_b['hold_days'] == hold_k)].to_dict('records')
        )
        summary_defensive['Branch_B'][target][f'Era2024_2026_Hold_{hold_k}d'] = calc_trade_metrics(
            df_branch_b[(df_branch_b['target'] == target) & (df_branch_b['is_drop_15'] == True) & (df_branch_b['era'] == '2024_2026') & (df_branch_b['entry_timing'] == 'T0_Close') & (df_branch_b['hold_days'] == hold_k)].to_dict('records')
        )

with open(f"{OUT_DIR}/summary_defensive_switch.json", 'w', encoding='utf-8') as f:
    json.dump(summary_defensive, f, ensure_ascii=False, indent=2)

print("Topic 2 finished. Saved to summary_defensive_switch.json and ledger_defensive_switch.csv.")

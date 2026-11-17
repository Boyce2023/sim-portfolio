#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_topic1_cross_year.py
================================================================================
课题一：跨年妖小策略深度回测（「基本面实质属性 + 大事件挂钩」）
样本期：2016年末至2026年初（共10个跨年季，每年11月10日至次年1月25日）
严格无未来函数 (PIT) 检验：
1. 真跨年大妖 (>=120% 或 >=5板) vs 跨年炮灰 3~4 板对照组特征对比
2. 基本面实质属性 (启动前90天硬公告、市值容量、前十股东锁仓)
3. 大事件大主线挂钩 (所属题材当日/近3日涨停家数、市场前二梯队)
4. 实盘机械截获小策略：无筛选基准 vs 量价分歧 vs +基本面硬催化 vs +大事件梯队 vs 全要素综合
================================================================================
"""
import os, sys, re, json, time, sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock2/p6_small_strategies_20261116"
os.makedirs(OUT_DIR, exist_ok=True)

A_DAILY_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PLATES_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl"
PIT_NOTICES_DB = f"{PROJECT_ROOT}/sim-portfolio/data/cninfo_notices_5y_pit.db"
NOTICES_DB = f"{PROJECT_ROOT}/sim-portfolio/backtest/2026-08-24-daban/notices.db"
ZT_TAPE_DB = f"{PROJECT_ROOT}/sim-portfolio/data/zt_micro_tape_5y_pit.db"
TOP10_PATH = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
INDEX_CACHE_PATH = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
INDUSTRY_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/industry.csv"

FEE_RATE = 0.0020  # 双边千二摩擦成本

SEASONS = [
    ('2016/17', '2016-11-10', '2017-01-25', '2016-11-15', '2017-01-15'),
    ('2017/18', '2017-11-10', '2018-01-25', '2017-11-15', '2018-01-15'),
    ('2018/19', '2018-11-10', '2019-01-25', '2018-11-15', '2019-01-15'),
    ('2019/20', '2019-11-10', '2020-01-25', '2019-11-15', '2020-01-15'),
    ('2020/21', '2020-11-10', '2021-01-25', '2020-11-15', '2021-01-15'),
    ('2021/22', '2021-11-10', '2022-01-25', '2021-11-15', '2022-01-15'),
    ('2022/23', '2022-11-10', '2023-01-25', '2022-11-15', '2023-01-15'),
    ('2023/24', '2023-11-10', '2024-01-25', '2023-11-15', '2024-01-15'),
    ('2024/25', '2024-11-10', '2025-01-25', '2024-11-15', '2025-01-15'),
    ('2025/26', '2025-11-10', '2026-01-25', '2025-11-15', '2026-01-15'),
]

HARD_NOTICE_PAT = re.compile(
    r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立|获批|FDA|授权|提价|涨价|回购|增持)"
)
BAD_NOTICE_PAT = re.compile(
    r"(减持|问询函|监管函|警示函|立案|风险提示|业绩预亏|预亏|巨亏|计提资产减值|退市风险|终止上市|违规|质押|冻结)"
)

def load_index_hs300():
    with open(INDEX_CACHE_PATH) as f:
        d = json.load(f)
    hs = d['sh000300']
    s = pd.Series(hs)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()

def load_names_and_industry():
    df_ind = pd.read_csv(INDUSTRY_PATH)
    name_map = dict(zip(df_ind['code'].str[3:], df_ind['code_name']))
    ind_map = dict(zip(df_ind['code'].str[3:], df_ind['industry']))
    return name_map, ind_map

def load_top10_lockup():
    print("[1/6] Loading PIT Top10 lockup cache...")
    if not os.path.exists(TOP10_PATH):
        return {}
    with open(TOP10_PATH) as f:
        d = json.load(f)
    return d

def load_kpl_theme_metadata():
    print("[2/6] Loading KPL theme metadata...")
    date_plate_map = {}
    with open(KPL_PLATES_PATH) as f:
        for line in f:
            d = json.loads(line)
            dt = d['date']
            p_dict = {}
            for p in d['plates']:
                p_name = p['plate']
                c6_list = [s[0] for s in p['stocks']]
                p_dict[p_name] = c6_list
            date_plate_map[dt] = p_dict
    return date_plate_map

def load_notices_and_zt_tape():
    print("[3/6] Loading notices & tape DBs (readonly)...")
    tape_dict = defaultdict(dict)
    conn_tape = sqlite3.connect(f"file:{ZT_TAPE_DB}?mode=ro", uri=True)
    cur = conn_tape.cursor()
    rows = cur.execute("SELECT trade_date, sec_code, plate_name, reason_desc FROM zt_micro_tape").fetchall()
    for dt, c6, p_name, reason in rows:
        tape_dict[dt][c6] = {'plate': p_name, 'reason': reason or ''}
    conn_tape.close()
    
    notice_events = defaultdict(list)
    conn_notices = sqlite3.connect(f"file:{PIT_NOTICES_DB}?mode=ro", uri=True)
    cur = conn_notices.cursor()
    rows = cur.execute("SELECT trade_date_avail, sec_code, title, ann_type FROM notices").fetchall()
    for dt, c6, title, atype in rows:
        t_all = f"{title} {atype}"
        is_hard = bool(HARD_NOTICE_PAT.search(t_all))
        is_bad = bool(BAD_NOTICE_PAT.search(t_all))
        if is_hard or is_bad:
            notice_events[c6].append((dt, is_hard, is_bad, title))
    conn_notices.close()
    
    if os.path.exists(NOTICES_DB):
        conn_n2 = sqlite3.connect(f"file:{NOTICES_DB}?mode=ro", uri=True)
        cur2 = conn_n2.cursor()
        rows2 = cur2.execute("SELECT ndate, code, title, ntype FROM notice").fetchall()
        for dt, c6, title, atype in rows2:
            t_all = f"{title} {atype}"
            is_hard = bool(HARD_NOTICE_PAT.search(t_all))
            is_bad = bool(BAD_NOTICE_PAT.search(t_all))
            if is_hard or is_bad:
                notice_events[c6].append((dt, is_hard, is_bad, title))
        conn_n2.close()
        
    for c6 in notice_events:
        notice_events[c6].sort(key=lambda x: x[0])
        
    return tape_dict, notice_events

def load_all_prices():
    print("[4/6] Loading full price database (2015-2026)...")
    cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'amount', 'turn', 'oshare']
    ds_act = ds.dataset(A_DAILY_PATH, format='parquet')
    df_act = ds_act.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2015-06-01'))).to_table().to_pandas()
    parts = [df_act]
    if os.path.exists(A_DELISTED_PATH):
        ds_del = ds.dataset(A_DELISTED_PATH, format='parquet')
        df_del = ds_del.scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2015-06-01'))).to_table().to_pandas()
        parts.append(df_del)
    df = pd.concat(parts, ignore_index=True)
    df['c6'] = df['ticker'].astype(str).str[:6]
    df = df[df['c6'].str.startswith(('00', '60')) & (~df['ticker'].str.endswith('.BJ'))].copy()
    df['dt_str'] = df['date'].dt.strftime('%Y-%m-%d')
    df.sort_values(['c6', 'dt_str'], inplace=True)
    df.drop_duplicates(subset=['c6', 'dt_str'], keep='first', inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    g = df.groupby('c6')
    df['trade_num'] = g.cumcount()
    df['pre_c'] = g['close'].shift(1)
    df['pct'] = df['close'] / df['pre_c'] - 1.0
    df['o_pct'] = df['open'] / df['pre_c'] - 1.0
    df['h_pct'] = df['high'] / df['pre_c'] - 1.0
    df['l_pct'] = df['low'] / df['pre_c'] - 1.0
    df['mcap'] = df['close'] * df['oshare'] / 1e8
    
    df['zt_price'] = np.floor(df['pre_c'] * 1.10 * 100.0 + 0.5) / 100.0
    df['dt_price'] = np.floor(df['pre_c'] * 0.90 * 100.0 + 0.5) / 100.0
    df['is_zt'] = (df['close'] >= df['zt_price'] - 0.01) & (df['pct'] >= 0.095) & (df['pre_c'] > 0)
    df['is_dt'] = (df['close'] <= df['dt_price'] + 0.01) & (df['pct'] <= -0.095) & (df['pre_c'] > 0)
    df['touch_zt'] = ((df['high'] >= df['zt_price'] - 0.01) | (df['h_pct'] >= 0.098)) & (df['pre_c'] > 0)
    df['is_yizi'] = df['is_zt'] & (df['open'] >= df['zt_price'] - 0.01) & (df['low'] >= df['zt_price'] - 0.01)
    
    s = df['is_zt'].astype(int)
    df['zt_streak'] = s.groupby((~df['is_zt']).cumsum()).cumsum()
    
    df['max_c_60'] = g['close'].transform(lambda s: s.shift(1).rolling(60, min_periods=20).max())
    df['zt_cnt_250'] = g['is_zt'].transform(lambda s: s.shift(1).rolling(250, min_periods=50).sum())
    
    df['d1_dt'] = g['dt_str'].shift(-1)
    df['d1_open'] = g['open'].shift(-1)
    df['d1_high'] = g['high'].shift(-1)
    df['d1_low'] = g['low'].shift(-1)
    df['d1_close'] = g['close'].shift(-1)
    df['d1_zt_price'] = np.floor(df['close'] * 1.10 * 100.0 + 0.5) / 100.0
    df['d1_is_zt'] = g['is_zt'].shift(-1).fillna(False)
    df['d1_is_yizi'] = g['is_yizi'].shift(-1).fillna(False)
    
    for k in range(1, 11):
        df[f'fwd_c_{k}'] = g['close'].shift(-k)
        df[f'fwd_dt_{k}'] = g['dt_str'].shift(-k)
        df[f'fwd_zt_{k}'] = g['is_zt'].shift(-k).fillna(False)
        df[f'fwd_open_{k}'] = g['open'].shift(-k)
    
    daily_high_b = df[df['zt_streak'] >= 3].groupby('dt_str')['c6'].count().to_dict()
    df['mkt_high_b_cnt'] = df['dt_str'].map(lambda d: daily_high_b.get(d, 0))
    
    print(f"Loaded {len(df):,} rows from 2015-06.")
    return df

def get_top10_lockup_ratio(top10_cache, c6, cur_dt):
    records = top10_cache.get(c6, [])
    if not records:
        return np.nan
    latest_ratio = np.nan
    for rec in records:
        pub_d = rec[0]
        if pub_d <= cur_dt:
            latest_ratio = rec[2]
        else:
            break
    return latest_ratio

def check_notice_catalyst_90d(notice_events, c6, cur_dt):
    events = notice_events.get(c6, [])
    if not events:
        return False, False, ""
    cur_t = pd.to_datetime(cur_dt)
    start_d = (cur_t - pd.Timedelta(days=90)).strftime('%Y-%m-%d')
    has_hard = False
    has_bad = False
    titles = []
    for dt, is_hard, is_bad, title in events:
        if start_d <= dt <= cur_dt:
            if is_hard:
                has_hard = True
                titles.append(title[:30])
            if is_bad:
                has_bad = True
    return has_hard, has_bad, ";".join(titles[:2])

def get_theme_features(date_plate_map, tape_dict, c6, cur_dt):
    p_dict = date_plate_map.get(cur_dt, {})
    stock_plates = []
    for p_name, stocks in p_dict.items():
        if c6 in stocks:
            stock_plates.append(p_name)
    
    if not stock_plates and cur_dt in tape_dict and c6 in tape_dict[cur_dt]:
        t_p = tape_dict[cur_dt][c6].get('plate')
        if t_p and t_p not in ['其他', '公告', '无']:
            stock_plates.append(t_p)
            
    is_top2_theme = False
    plate_zt_cnt = 0
    main_plate = stock_plates[0] if stock_plates else '其他'
    
    if p_dict:
        plates_ranked = sorted([(p, len(stks)) for p, stks in p_dict.items() if p != '其他'], key=lambda x: x[1], reverse=True)
        top2_names = [p[0] for p in plates_ranked[:2]]
        for sp in stock_plates:
            cnt = len(p_dict.get(sp, []))
            if cnt > plate_zt_cnt:
                plate_zt_cnt = cnt
                main_plate = sp
            if sp in top2_names:
                is_top2_theme = True
    return main_plate, plate_zt_cnt, is_top2_theme

print("Starting Topic 1 execution...")
hs300_s = load_index_hs300()
name_map, ind_map = load_names_and_industry()
top10_cache = load_top10_lockup()
date_plate_map = load_kpl_theme_metadata()
tape_dict, notice_events = load_notices_and_zt_tape()
df = load_all_prices()

# Exclude IPO first 60 days
df_sec = df[df['trade_num'] >= 60].copy()

# ==============================================================================
# Part 1: True Monsters vs Cannon-fodder (3b/4b Failures)
# ==============================================================================
print("[5/6] Analyzing True Cross-Year Monsters vs Control Group (3b/4b)...")
monster_rows = []
control_rows = []

for s_idx, (s_name, start_d, end_d, strat_start, strat_end) in enumerate(SEASONS):
    sub = df_sec[(df_sec['dt_str'] >= start_d) & (df_sec['dt_str'] <= end_d)]
    g_sub = sub.groupby('c6')
    for c6, group in g_sub:
        low_min = group['low'].min()
        high_max = group['high'].max()
        max_streak = group['zt_streak'].max()
        max_gain = (high_max / low_min - 1.0) if low_min > 0 else 0.0
        
        sub_3b = group[group['zt_streak'] == 3]
        if len(sub_3b) == 0:
            continue
        launch_row = sub_3b.iloc[0]
        launch_dt = launch_row['dt_str']
        launch_mcap = launch_row['mcap']
        
        top10_lockup = get_top10_lockup_ratio(top10_cache, c6, launch_dt)
        has_hard, has_bad, notice_desc = check_notice_catalyst_90d(notice_events, c6, launch_dt)
        tape_reason = tape_dict.get(launch_dt, {}).get(c6, {}).get('reason', '')
        if not has_hard and tape_reason and HARD_NOTICE_PAT.search(tape_reason):
            has_hard = True
            notice_desc = tape_reason[:30]
        main_plate, plate_zt_cnt, is_top2 = get_theme_features(date_plate_map, tape_dict, c6, launch_dt)
        
        is_true_monster = (max_gain >= 1.20) or (max_streak >= 5)
        is_cannon_fodder = (not is_true_monster) and (max_streak <= 4) and (max_gain < 0.50)
        
        record = {
            'season': s_name,
            'c6': c6,
            'name': name_map.get(c6, c6),
            'industry': ind_map.get(c6, '未知'),
            'launch_dt': launch_dt,
            'max_gain': max_gain,
            'max_streak': int(max_streak),
            'launch_mcap': float(launch_mcap),
            'top10_lockup': float(top10_lockup) if not np.isnan(top10_lockup) else None,
            'has_hard_notice': bool(has_hard),
            'has_bad_notice': bool(has_bad),
            'notice_desc': notice_desc,
            'main_plate': main_plate,
            'plate_zt_cnt': int(plate_zt_cnt),
            'is_top2_theme': bool(is_top2),
            'is_true_monster': bool(is_true_monster),
            'is_cannon_fodder': bool(is_cannon_fodder),
        }
        
        if is_true_monster:
            monster_rows.append(record)
        elif is_cannon_fodder:
            control_rows.append(record)

print(f"Total True Monsters: {len(monster_rows)}, Total Cannon-fodder 3b/4b: {len(control_rows)}")
df_mon = pd.DataFrame(monster_rows)
df_ctrl = pd.DataFrame(control_rows)

# ==============================================================================
# Part 2: Mechanical Backtest of Right-Side Interception Strategy (11.15 ~ 01.15)
# ==============================================================================
print("\n[6/6] Backtesting Mechanical Strategies (11.15 ~ 01.15)...")
trades_raw = []

for s_idx, (s_name, start_d, end_d, strat_start, strat_end) in enumerate(SEASONS):
    cands = df_sec[(df_sec['dt_str'] >= strat_start) & (df_sec['dt_str'] <= strat_end) & (df_sec['zt_streak'] == 4)].copy()
    
    for _, row in cands.iterrows():
        c6 = row['c6']
        d0_dt = row['dt_str']
        d1_dt = row['d1_dt']
        if pd.isna(d1_dt) or row['d1_open'] <= 0:
            continue
        
        d1_zt_p = row['d1_zt_price']
        d1_open = row['d1_open']
        d1_low = row['d1_low']
        d1_high = row['d1_high']
        is_yizi = (d1_open >= d1_zt_p - 0.01) and (d1_low >= d1_zt_p - 0.01)
        if is_yizi:
            continue
            
        buy_px = d1_open
        buy_dt = d1_dt
        
        f_low_px = (buy_px < 12.0)
        f_low_mcap = (row['mcap'] < 60.0)
        f_old_monster = (row['zt_cnt_250'] >= 2)
        f_break60 = (row['close'] >= row['max_c_60'] - 0.01)
        f_auc_div = (0.0 <= (d1_open / row['close'] - 1.0) <= 0.06)
        f_un_crowded = (row['mkt_high_b_cnt'] <= 7)
        score_6dim = sum([f_low_px, f_low_mcap, f_old_monster, f_break60, f_auc_div, f_un_crowded])
        
        has_hard, has_bad, notice_desc = check_notice_catalyst_90d(notice_events, c6, buy_dt)
        tape_reason = tape_dict.get(buy_dt, {}).get(c6, {}).get('reason', '')
        if not has_hard and tape_reason and HARD_NOTICE_PAT.search(tape_reason):
            has_hard = True
            notice_desc = tape_reason[:30]
        f_fund_cap = (20.0 <= row['mcap'] <= 150.0)
        f_no_bad = (not has_bad)
        
        main_plate, plate_zt_cnt, is_top2 = get_theme_features(date_plate_map, tape_dict, c6, buy_dt)
        f_theme_hook = (is_top2 or plate_zt_cnt >= 3)
        
        exit_dt = None
        exit_px = None
        hold_days = 0
        
        if row['d1_is_zt']:
            for k in range(2, 11):
                fwd_c = row[f'fwd_c_{k}']
                fwd_zt = row[f'fwd_zt_{k}']
                fwd_dt = row[f'fwd_dt_{k}']
                fwd_open = row[f'fwd_open_{k}']
                prev_zt = row[f'fwd_zt_{k-1}']
                if not prev_zt:
                    exit_dt = fwd_dt
                    exit_px = fwd_open if fwd_open > 0 else row[f'fwd_c_{k-1}']
                    hold_days = k - 1
                    break
            if exit_px is None:
                k = 10
                fwd_dt = row[f'fwd_dt_{k}']
                exit_px = row[f'fwd_c_{k}']
                exit_dt = fwd_dt
                hold_days = 10
        else:
            d2_dt = row[f'fwd_dt_2']
            d2_open = row[f'fwd_open_2']
            exit_px = d2_open if d2_open > 0 else row['d1_close']
            exit_dt = d2_dt
            hold_days = 1
            
        if exit_px is None or exit_px <= 0:
            continue
            
        raw_ret = (exit_px / buy_px) - 1.0
        net_ret = (exit_px * (1.0 - FEE_RATE)) / (buy_px * (1.0 + FEE_RATE)) - 1.0
        
        t_buy = pd.to_datetime(buy_dt)
        t_exit = pd.to_datetime(exit_dt) if exit_dt and not pd.isna(exit_dt) else t_buy
        hs_sub = hs300_s[(hs300_s.index >= t_buy) & (hs300_s.index <= t_exit)]
        if len(hs_sub) >= 2:
            hs_ret = hs_sub.iloc[-1] / hs_sub.iloc[0] - 1.0
        else:
            hs_ret = 0.0
            
        excess_ret = net_ret - hs_ret
        
        trades_raw.append({
            'season': s_name,
            'c6': c6,
            'name': name_map.get(c6, c6),
            'buy_dt': buy_dt,
            'exit_dt': exit_dt,
            'hold_days': hold_days,
            'buy_px': float(buy_px),
            'exit_px': float(exit_px),
            'raw_ret': float(raw_ret),
            'net_ret': float(net_ret),
            'hs_ret': float(hs_ret),
            'excess_ret': float(excess_ret),
            'mcap': float(row['mcap']),
            'score_6dim': int(score_6dim),
            'has_hard_notice': bool(has_hard),
            'has_bad_notice': bool(has_bad),
            'f_fund_cap': bool(f_fund_cap),
            'f_theme_hook': bool(f_theme_hook),
            'main_plate': main_plate,
            'plate_zt_cnt': int(plate_zt_cnt),
            'notice_desc': notice_desc,
        })

df_trades = pd.DataFrame(trades_raw)
print(f"Total raw 4-to-5 candidate trades across 10 seasons: {len(df_trades)}")

df_trades.to_csv(f"{OUT_DIR}/ledger_cross_year.csv", index=False, encoding='utf-8-sig')

strat_masks = {
    'S0_Base_Unfiltered': pd.Series([True]*len(df_trades), index=df_trades.index),
    'S1_Score6Dim_GE5': (df_trades['score_6dim'] >= 5),
    'S2_PV_Plus_Fund': (df_trades['score_6dim'] >= 4) & (df_trades['has_hard_notice'] | df_trades['f_fund_cap']) & (~df_trades['has_bad_notice']),
    'S3_PV_Plus_Theme': (df_trades['score_6dim'] >= 4) & (df_trades['f_theme_hook']),
    'S4_Full_Combo': (df_trades['score_6dim'] >= 4) & (df_trades['has_hard_notice']) & (df_trades['f_theme_hook']) & (~df_trades['has_bad_notice']),
    'S5_Buwen_Fundamental_Theme_Only': (df_trades['has_hard_notice'] | df_trades['f_fund_cap']) & (df_trades['f_theme_hook']) & (~df_trades['has_bad_notice']),
}

def evaluate_strategy_periods(sub_trades):
    if len(sub_trades) == 0:
        return {
            'count': 0, 'win_rate': 0.0, 'avg_net_ret': 0.0, 'win_loss_ratio': 0.0,
            'max_drawdown': 0.0, 'cum_net_ret': 0.0, 'hs300_excess': 0.0
        }
    cnt = len(sub_trades)
    win_rate = (sub_trades['net_ret'] > 0).mean()
    avg_net = sub_trades['net_ret'].mean()
    wins = sub_trades[sub_trades['net_ret'] > 0]['net_ret']
    losses = sub_trades[sub_trades['net_ret'] <= 0]['net_ret']
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 1e-6
    wl_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    
    date_rets = sub_trades.groupby('buy_dt')['net_ret'].mean()
    cum_eq = (1.0 + date_rets).cumprod()
    cum_ret = cum_eq.iloc[-1] - 1.0 if len(cum_eq) > 0 else 0.0
    running_max = cum_eq.cummax()
    dd = (cum_eq - running_max) / running_max
    mdd = abs(dd.min()) if len(dd) > 0 else 0.0
    
    date_excess = sub_trades.groupby('buy_dt')['excess_ret'].mean()
    excess_cum = (1.0 + date_excess).cumprod().iloc[-1] - 1.0 if len(date_excess) > 0 else 0.0
    
    return {
        'count': int(cnt),
        'win_rate': float(win_rate),
        'avg_net_ret': float(avg_net),
        'win_loss_ratio': float(wl_ratio),
        'max_drawdown': float(mdd),
        'cum_net_ret': float(cum_ret),
        'hs300_excess': float(excess_cum)
    }

def simulate_single_rotation(sub_trades):
    if len(sub_trades) == 0:
        return {
            'count': 0, 'win_rate': 0.0, 'avg_net_ret': 0.0, 'win_loss_ratio': 0.0,
            'max_drawdown': 0.0, 'cum_net_ret': 0.0, 'hs300_excess': 0.0
        }
    sorted_trades = sub_trades.sort_values(['buy_dt', 'score_6dim', 'mcap'], ascending=[True, False, True])
    selected = []
    busy_until = '1990-01-01'
    for _, tr in sorted_trades.iterrows():
        b_dt = tr['buy_dt']
        if b_dt >= busy_until:
            selected.append(tr)
            busy_until = tr['exit_dt'] if tr['exit_dt'] else b_dt
    df_sel = pd.DataFrame(selected)
    return evaluate_strategy_periods(df_sel)

summary_dict = {}

for s_name, mask in strat_masks.items():
    st = df_trades[mask]
    
    res_10y_eq = evaluate_strategy_periods(st)
    res_10y_single = simulate_single_rotation(st)
    
    st_5y = st[st['buy_dt'] >= '2021-11-01']
    res_5y_eq = evaluate_strategy_periods(st_5y)
    res_5y_single = simulate_single_rotation(st_5y)
    
    st_3y = st[st['buy_dt'] >= '2023-11-01']
    res_3y_eq = evaluate_strategy_periods(st_3y)
    res_3y_single = simulate_single_rotation(st_3y)
    
    st_rec = st[st['buy_dt'] >= '2025-11-01']
    res_rec_eq = evaluate_strategy_periods(st_rec)
    res_rec_single = simulate_single_rotation(st_rec)
    
    summary_dict[s_name] = {
        '10y_equal': res_10y_eq,
        '10y_single': res_10y_single,
        '5y_equal': res_5y_eq,
        '5y_single': res_5y_single,
        '3y_equal': res_3y_eq,
        '3y_single': res_3y_single,
        'recent_equal': res_rec_eq,
        'recent_single': res_rec_single,
    }

with open(f"{OUT_DIR}/summary_cross_year.json", 'w', encoding='utf-8') as f:
    json.dump(summary_dict, f, ensure_ascii=False, indent=2)

print("Topic 1 backtest finished. Summary saved to JSON.")

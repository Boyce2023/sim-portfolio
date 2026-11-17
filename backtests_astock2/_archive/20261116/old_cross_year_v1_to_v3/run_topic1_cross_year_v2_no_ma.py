#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_topic1_cross_year_v2_no_ma.py
================================================================================
课题一 V2 紧急纠偏重算版：纯净非重组跨年妖深度回测（2016–2026，10个跨年季）
核心纠偏（Buwen 明确定义）：
1. 100% 物理剔除全部 ST/*ST 股，以及任何含并购重组/控制权变更/股权转让/借壳公告与题材的股票！
2. 市值容量放宽至 20亿~350亿（覆盖商业航天、卫星互联网等弹性龙与中军）；
3. 卖点测试现代双严重异动新规下的「绕异动波段趋势锁仓（MA10/MA5）」对比「断板次日无脑全卖」；
4. 测试两大实战右侧截获买法：
   - 买法1：首波主线立标杆（3~4板换手突破 + MA10趋势持仓吃二波三波）
   - 买法2：首波龙头断板回踩MA10不破后的绕异动二波反包/转强首板
5. 逐年输出真实市场非重组跨年大妖前五名 vs 策略筛出前五名对账表（重点核验 2025/26 去年实盘对账）
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
INDEX_CACHE_PATH = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
INDUSTRY_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/industry.csv"

FEE_RATE = 0.0020  # 双边千二成本

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

# 严格一票否决：并购重组、实控人变更、股权转让、借壳等
MA_STRICT_PAT = re.compile(
    r"(并购|重大资产重组|控制权变更|实控人变更|股权转让|借壳|发行股份购买资产|协议转让|要约收购|资产注入)"
)
# 毒丸一票否决：立案调查、减持、业绩预亏
POISON_PAT = re.compile(
    r"(立案调查|立案|被立案|涉嫌违法|大额减持|减持计划|清仓减持|业绩预亏|预亏|巨亏|计提减值|重大亏损)"
)

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

def load_kpl_theme_metadata():
    print("[1/5] Loading KPL theme metadata...")
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
    print("[2/5] Loading notices & tape DBs (readonly mode)...")
    tape_dict = defaultdict(dict)
    conn_tape = sqlite3.connect(f"file:{ZT_TAPE_DB}?mode=ro", uri=True)
    cur = conn_tape.cursor()
    rows = cur.execute("SELECT trade_date, sec_code, plate_name, reason_desc FROM zt_micro_tape").fetchall()
    for dt, c6, p_name, reason in rows:
        tape_dict[dt][c6] = {'plate': p_name, 'reason': reason or ''}
    conn_tape.close()
    
    # notices: map c6 -> list of (date, is_ma, is_poison, title)
    notice_events = defaultdict(list)
    conn_notices = sqlite3.connect(f"file:{PIT_NOTICES_DB}?mode=ro", uri=True)
    cur = conn_notices.cursor()
    rows = cur.execute("SELECT trade_date_avail, sec_code, title, ann_type FROM notices").fetchall()
    for dt, c6, title, atype in rows:
        t_all = f"{title} {atype}"
        is_ma = bool(MA_STRICT_PAT.search(t_all))
        is_poison = bool(POISON_PAT.search(t_all))
        if is_ma or is_poison:
            notice_events[c6].append((dt, is_ma, is_poison, title))
    conn_notices.close()
    
    if os.path.exists(NOTICES_DB):
        conn_n2 = sqlite3.connect(f"file:{NOTICES_DB}?mode=ro", uri=True)
        cur2 = conn_n2.cursor()
        rows2 = cur2.execute("SELECT ndate, code, title, ntype FROM notice").fetchall()
        for dt, c6, title, atype in rows2:
            t_all = f"{title} {atype}"
            is_ma = bool(MA_STRICT_PAT.search(t_all))
            is_poison = bool(POISON_PAT.search(t_all))
            if is_ma or is_poison:
                notice_events[c6].append((dt, is_ma, is_poison, title))
        conn_n2.close()
        
    for c6 in notice_events:
        notice_events[c6].sort(key=lambda x: x[0])
        
    return tape_dict, notice_events

def load_all_prices():
    print("[3/5] Loading price database (2015-2026)...")
    cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'amount', 'volume', 'turn', 'oshare']
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
    df['is_yizi'] = df['is_zt'] & (df['open'] >= df['zt_price'] - 0.01) & (df['low'] >= df['zt_price'] - 0.01)
    
    s = df['is_zt'].astype(int)
    df['zt_streak'] = s.groupby((~df['is_zt']).cumsum()).cumsum()
    
    # Technical Indicators: MA5, MA10, MA20
    df['ma5'] = g['close'].transform(lambda s: s.rolling(5, min_periods=3).mean())
    df['ma10'] = g['close'].transform(lambda s: s.rolling(10, min_periods=5).mean())
    df['ma20'] = g['close'].transform(lambda s: s.rolling(20, min_periods=10).mean())
    df['max_c_60'] = g['close'].transform(lambda s: s.shift(1).rolling(60, min_periods=20).max())
    df['zt_cnt_250'] = g['is_zt'].transform(lambda s: s.shift(1).rolling(250, min_periods=50).sum())
    
    # Next day prices
    df['d1_dt'] = g['dt_str'].shift(-1)
    df['d1_open'] = g['open'].shift(-1)
    df['d1_high'] = g['high'].shift(-1)
    df['d1_low'] = g['low'].shift(-1)
    df['d1_close'] = g['close'].shift(-1)
    df['d1_zt_price'] = np.floor(df['close'] * 1.10 * 100.0 + 0.5) / 100.0
    df['d1_is_zt'] = g['is_zt'].shift(-1).fillna(False)
    df['d1_is_yizi'] = g['is_yizi'].shift(-1).fillna(False)
    
    # Forward prices up to 40 days for wave 2/3 tracking
    for k in range(1, 41):
        df[f'fwd_c_{k}'] = g['close'].shift(-k)
        df[f'fwd_o_{k}'] = g['open'].shift(-k)
        df[f'fwd_h_{k}'] = g['high'].shift(-k)
        df[f'fwd_l_{k}'] = g['low'].shift(-k)
        df[f'fwd_dt_{k}'] = g['dt_str'].shift(-k)
        df[f'fwd_zt_{k}'] = g['is_zt'].shift(-k).fillna(False)
        df[f'fwd_ma10_{k}'] = g['ma10'].shift(-k)
        df[f'fwd_ma5_{k}'] = g['ma5'].shift(-k)
    
    daily_high_b = df[df['zt_streak'] >= 3].groupby('dt_str')['c6'].count().to_dict()
    df['mkt_high_b_cnt'] = df['dt_str'].map(lambda d: daily_high_b.get(d, 0))
    
    print(f"Loaded {len(df):,} price records.")
    return df

def is_stock_clean_non_ma(c6, name, cur_dt, notice_events, tape_dict):
    # 1. 严格一票否决 ST/*ST/退市
    if not name or name.startswith('*ST') or name.startswith('ST') or '退' in name:
        return False, "ST/退市"
        
    # 2. 检查启动前90天公告
    cur_t = pd.to_datetime(cur_dt)
    start_d = (cur_t - pd.Timedelta(days=90)).strftime('%Y-%m-%d')
    events = notice_events.get(c6, [])
    for dt, is_ma, is_poison, title in events:
        if start_d <= dt <= cur_dt:
            if is_ma:
                return False, f"公告含并购重组: {title[:20]}"
            if is_poison:
                return False, f"公告含立案减持预亏: {title[:20]}"
                
    # 3. 检查 tape_dict 涨停原因与板块名
    cur_tape = tape_dict.get(cur_dt, {}).get(c6, {})
    p_name = cur_tape.get('plate', '')
    reason = cur_tape.get('reason', '')
    tape_all = f"{p_name} {reason}"
    if MA_STRICT_PAT.search(tape_all):
        return False, f"盘面含重组/股权转让题材: {p_name}"
    if 'ST' in p_name:
        return False, "ST板块"
        
    return True, "CLEAN"

def get_theme_strength(date_plate_map, tape_dict, c6, cur_dt):
    p_dict = date_plate_map.get(cur_dt, {})
    stock_plates = []
    for p_name, stocks in p_dict.items():
        if c6 in stocks:
            stock_plates.append(p_name)
    if not stock_plates and cur_dt in tape_dict and c6 in tape_dict[cur_dt]:
        tp = tape_dict[cur_dt][c6].get('plate')
        if tp and tp not in ['其他', '公告', '无']:
            stock_plates.append(tp)
            
    is_top2 = False
    plate_zt_cnt = 0
    main_p = stock_plates[0] if stock_plates else '其他'
    if p_dict:
        plates_ranked = sorted([(p, len(stks)) for p, stks in p_dict.items() if p != '其他'], key=lambda x: x[1], reverse=True)
        top2 = [p[0] for p in plates_ranked[:2]]
        for sp in stock_plates:
            cnt = len(p_dict.get(sp, []))
            if cnt > plate_zt_cnt:
                plate_zt_cnt = cnt
                main_p = sp
            if sp in top2:
                is_top2 = True
    return main_p, plate_zt_cnt, is_top2

print("Starting Topic 1 V2 execution...")
hs300_s = load_index_hs300()
name_map, ind_map = load_industry_and_names()
date_plate_map = load_kpl_theme_metadata()
tape_dict, notice_events = load_notices_and_zt_tape()
df = load_all_prices()

# Exclude IPO first 60 days
df_sec = df[df['trade_num'] >= 60].copy()

# ==============================================================================
# Part 1: 10年跨年季真实市场纯净非重组妖股对账表（前五名提取）
# ==============================================================================
print("\n[4/5] Extracting Real Market Non-M&A Top 5 Monsters per Season...")
yearly_real_monsters = {}

for s_name, start_d, end_d, strat_start, strat_end in SEASONS:
    sub = df_sec[(df_sec['dt_str'] >= start_d) & (df_sec['dt_str'] <= end_d)]
    g_sub = sub.groupby('c6')
    mon_list = []
    for c6, group in g_sub:
        name = name_map.get(c6, c6)
        low_min = group['low'].min()
        high_max = group['high'].max()
        if low_min <= 0: continue
        gain = (high_max / low_min) - 1.0
        max_streak = group['zt_streak'].max()
        mcap_init = group.iloc[0]['mcap']
        
        # 严格非重组/非ST过滤
        is_clean, reason = is_stock_clean_non_ma(c6, name, start_d, notice_events, tape_dict)
        if not is_clean:
            continue
        # 容量要求：20亿~350亿
        if mcap_init < 20.0 or mcap_init > 350.0:
            continue
            
        # 主题标签
        sub_zt = group[group['is_zt']]
        p_name = '其他'
        if len(sub_zt) > 0:
            zt_dt = sub_zt.iloc[0]['dt_str']
            p_name, _, _ = get_theme_strength(date_plate_map, tape_dict, c6, zt_dt)
            
        mon_list.append({
            'season': s_name,
            'c6': c6,
            'name': name,
            'max_gain': gain,
            'max_streak': int(max_streak),
            'init_mcap': float(mcap_init),
            'theme': p_name,
        })
        
    mon_list.sort(key=lambda x: x['max_gain'], reverse=True)
    yearly_real_monsters[s_name] = mon_list[:5]

print("Top 5 Non-M&A Monsters Sample (2025/26 Season):")
for r in yearly_real_monsters['2025/26']:
    print(f"  {r['c6']} {r['name']:8s} MaxGain: {r['max_gain']*100:6.1f}%, Streak: {r['max_streak']}板, Mcap: {r['init_mcap']:.1f}亿, Theme: {r['theme']}")

# ==============================================================================
# Part 2: 实盘可执行右侧截获策略回测 (11.15 ~ 01.15)
# ==============================================================================
print("\n[5/5] Backtesting Right-Side Strategies (Method 1 & Method 2)...")

trades_all = []

for s_name, start_d, end_d, strat_start, strat_end in SEASONS:
    # 窗口内全部交易日
    sub_season = df_sec[(df_sec['dt_str'] >= strat_start) & (df_sec['dt_str'] <= strat_end)]
    
    # --------------------------------------------------------------------------
    # 买法 1：首波主线立标杆换手突破 (3板或4板良性竞价买入)
    # --------------------------------------------------------------------------
    cands_m1 = sub_season[sub_season['zt_streak'].isin([3, 4])].copy()
    for _, row in cands_m1.iterrows():
        c6 = row['c6']
        name = name_map.get(c6, c6)
        d0_dt = row['dt_str']
        d1_dt = row['d1_dt']
        if pd.isna(d1_dt) or row['d1_open'] <= 0:
            continue
            
        # 1. 严格非重组/非ST/非毒丸
        is_clean, clean_reason = is_stock_clean_non_ma(c6, name, d1_dt, notice_events, tape_dict)
        if not is_clean:
            continue
            
        # 2. 市值容量: 20亿~350亿
        if row['mcap'] < 20.0 or row['mcap'] > 350.0:
            continue
            
        # 3. 大事件大主线梯队挂钩 (所属题材当日涨停>=3家或全场前二主线)
        main_p, plate_zt_cnt, is_top2 = get_theme_strength(date_plate_map, tape_dict, c6, d1_dt)
        if not (is_top2 or plate_zt_cnt >= 3):
            continue
            
        # 4. 可买性检验：非一字涨停
        d1_zt_p = row['d1_zt_price']
        d1_open = row['d1_open']
        d1_low = row['d1_low']
        if d1_open >= d1_zt_p - 0.01 and d1_low >= d1_zt_p - 0.01:
            continue # 一字不可买
            
        # 5. 竞价幅度过滤：良性分歧 (开盘在 -2% 至 +6.5% 之间)
        o_gap = (d1_open / row['close']) - 1.0
        if o_gap < -0.02 or o_gap > 0.065:
            continue
            
        buy_px = d1_open
        buy_dt = d1_dt
        
        # ----------------------------------------------------------------------
        # 模拟不同出场规则：
        # 规则 A：断板次日开盘卖 (Legacy)
        # 规则 B：收盘跌破 MA10 次日开盘卖 (Trend MA10)
        # 规则 C：收盘跌破 MA5 次日开盘卖 (Trend MA5)
        # ----------------------------------------------------------------------
        # Rule A: Break next open
        exit_dt_a, exit_px_a, hold_a = None, None, 1
        if row['d1_is_zt']:
            for k in range(2, 40):
                prev_zt = row[f'fwd_zt_{k-1}']
                fwd_dt = row[f'fwd_dt_{k}']
                fwd_open = row[f'fwd_o_{k}']
                if not prev_zt:
                    exit_dt_a = fwd_dt
                    exit_px_a = fwd_open if fwd_open > 0 else row[f'fwd_c_{k-1}']
                    hold_a = k - 1
                    break
            if exit_px_a is None:
                exit_dt_a = row['fwd_dt_20']
                exit_px_a = row['fwd_c_20']
                hold_a = 20
        else:
            exit_dt_a = row['fwd_dt_2']
            exit_px_a = row['fwd_o_2'] if row['fwd_o_2'] > 0 else row['d1_close']
            hold_a = 1
            
        # Rule B: Trend MA10
        exit_dt_b, exit_px_b, hold_b = None, None, 1
        for k in range(1, 40):
            c_k = row[f'fwd_c_{k}']
            ma10_k = row[f'fwd_ma10_{k}']
            dt_k = row[f'fwd_dt_{k}']
            next_open = row[f'fwd_o_{k+1}']
            next_dt = row[f'fwd_dt_{k+1}']
            if pd.isna(c_k) or c_k <= 0:
                break
            # Check if close below MA10
            if not pd.isna(ma10_k) and c_k < ma10_k:
                exit_dt_b = next_dt
                exit_px_b = next_open if next_open > 0 else c_k
                hold_b = k
                break
        if exit_px_b is None:
            exit_dt_b = row['fwd_dt_20']
            exit_px_b = row['fwd_c_20']
            hold_b = 20
            
        # Rule C: Trend MA5
        exit_dt_c, exit_px_c, hold_c = None, None, 1
        for k in range(1, 40):
            c_k = row[f'fwd_c_{k}']
            ma5_k = row[f'fwd_ma5_{k}']
            dt_k = row[f'fwd_dt_{k}']
            next_open = row[f'fwd_o_{k+1}']
            next_dt = row[f'fwd_dt_{k+1}']
            if pd.isna(c_k) or c_k <= 0:
                break
            if not pd.isna(ma5_k) and c_k < ma5_k:
                exit_dt_c = next_dt
                exit_px_c = next_open if next_open > 0 else c_k
                hold_c = k
                break
        if exit_px_c is None:
            exit_dt_c = row['fwd_dt_20']
            exit_px_c = row['fwd_c_20']
            hold_c = 20
            
        # Net returns
        net_ret_a = (exit_px_a * (1.0 - FEE_RATE)) / (buy_px * (1.0 + FEE_RATE)) - 1.0 if exit_px_a and exit_px_a > 0 else 0.0
        net_ret_b = (exit_px_b * (1.0 - FEE_RATE)) / (buy_px * (1.0 + FEE_RATE)) - 1.0 if exit_px_b and exit_px_b > 0 else 0.0
        net_ret_c = (exit_px_c * (1.0 - FEE_RATE)) / (buy_px * (1.0 + FEE_RATE)) - 1.0 if exit_px_c and exit_px_c > 0 else 0.0
        
        # Benchmark HS300 returns
        t_buy = pd.to_datetime(buy_dt)
        t_exit_b = pd.to_datetime(exit_dt_b) if exit_dt_b else t_buy
        hs_sub = hs300_s[(hs300_s.index >= t_buy) & (hs300_s.index <= t_exit_b)]
        hs_ret_b = (hs_sub.iloc[-1] / hs_sub.iloc[0] - 1.0) if len(hs_sub) >= 2 else 0.0
        
        trades_all.append({
            'method': 'M1_Leader_Breakout',
            'season': s_name,
            'c6': c6,
            'name': name,
            'theme': main_p,
            'buy_dt': buy_dt,
            'buy_px': float(buy_px),
            'mcap': float(row['mcap']),
            'streak': int(row['zt_streak']),
            # Rule A
            'exit_dt_a': exit_dt_a,
            'exit_px_a': float(exit_px_a) if exit_px_a else 0.0,
            'net_ret_a': float(net_ret_a),
            'hold_a': hold_a,
            # Rule B (MA10)
            'exit_dt_b': exit_dt_b,
            'exit_px_b': float(exit_px_b) if exit_px_b else 0.0,
            'net_ret_b': float(net_ret_b),
            'hold_b': hold_b,
            'hs_ret_b': float(hs_ret_b),
            'excess_b': float(net_ret_b - hs_ret_b),
            # Rule C (MA5)
            'exit_dt_c': exit_dt_c,
            'exit_px_c': float(exit_px_c) if exit_px_c else 0.0,
            'net_ret_c': float(net_ret_c),
            'hold_c': hold_c,
        })

    # --------------------------------------------------------------------------
    # 买法 2：首波龙头断板回踩 MA10 不破后的二波转强首板/反包买点
    # --------------------------------------------------------------------------
    # 条件：过去15天内曾走出 >=3 连板、期间未跌破 MA10/MA20、今日首板且非一字
    cands_m2 = sub_season[sub_season['is_zt'] & (sub_season['zt_streak'] == 1)].copy()
    for _, row in cands_m2.iterrows():
        c6 = row['c6']
        name = name_map.get(c6, c6)
        dt = row['dt_str']
        
        # 1. 严格非重组/非ST
        is_clean, clean_reason = is_stock_clean_non_ma(c6, name, dt, notice_events, tape_dict)
        if not is_clean:
            continue
        if row['mcap'] < 20.0 or row['mcap'] > 350.0:
            continue
            
        # 2. 检查过去 15 个交易日内是否有过 >=3 连板
        past_bars = df_sec[(df_sec['c6'] == c6) & (df_sec['dt_str'] < dt)].tail(15)
        if len(past_bars) < 5:
            continue
        max_past_streak = past_bars['zt_streak'].max()
        if max_past_streak < 3:
            continue
            
        # 3. 检查回调期间是否守住 MA10 (最低价未跌破 MA20 超过 3%)
        min_low_to_ma20 = (past_bars['low'] / past_bars['ma20'] - 1.0).min()
        if min_low_to_ma20 < -0.05:
            continue # 跌漏均线体系，破位诱多
            
        # 4. 大事件主题梯队共振
        main_p, plate_zt_cnt, is_top2 = get_theme_strength(date_plate_map, tape_dict, c6, dt)
        if not (is_top2 or plate_zt_cnt >= 2):
            continue
            
        # 5. 次日早盘买入检验 (d1_open 非一字)
        d1_dt = row['d1_dt']
        d1_open = row['d1_open']
        d1_zt_p = row['d1_zt_price']
        d1_low = row['d1_low']
        if pd.isna(d1_dt) or d1_open <= 0:
            continue
        if d1_open >= d1_zt_p - 0.01 and d1_low >= d1_zt_p - 0.01:
            continue
            
        buy_px = d1_open
        buy_dt = d1_dt
        
        # 模拟出场：跌破 MA10 次日开盘卖
        exit_dt, exit_px, hold_days = None, None, 1
        for k in range(1, 40):
            c_k = row[f'fwd_c_{k}']
            ma10_k = row[f'fwd_ma10_{k}']
            next_open = row[f'fwd_o_{k+1}']
            next_dt = row[f'fwd_dt_{k+1}']
            if pd.isna(c_k) or c_k <= 0:
                break
            if not pd.isna(ma10_k) and c_k < ma10_k:
                exit_dt = next_dt
                exit_px = next_open if next_open > 0 else c_k
                hold_days = k
                break
        if exit_px is None:
            exit_dt = row['fwd_dt_20']
            exit_px = row['fwd_c_20']
            hold_days = 20
            
        net_ret = (exit_px * (1.0 - FEE_RATE)) / (buy_px * (1.0 + FEE_RATE)) - 1.0 if exit_px and exit_px > 0 else 0.0
        
        t_buy = pd.to_datetime(buy_dt)
        t_exit = pd.to_datetime(exit_dt) if exit_dt else t_buy
        hs_sub = hs300_s[(hs300_s.index >= t_buy) & (hs300_s.index <= t_exit)]
        hs_ret = (hs_sub.iloc[-1] / hs_sub.iloc[0] - 1.0) if len(hs_sub) >= 2 else 0.0
        
        trades_all.append({
            'method': 'M2_Wave2_Rebound',
            'season': s_name,
            'c6': c6,
            'name': name,
            'theme': main_p,
            'buy_dt': buy_dt,
            'buy_px': float(buy_px),
            'mcap': float(row['mcap']),
            'streak': int(max_past_streak),
            'exit_dt_a': exit_dt,
            'exit_px_a': float(exit_px) if exit_px else 0.0,
            'net_ret_a': float(net_ret), # same
            'hold_a': hold_days,
            'exit_dt_b': exit_dt,
            'exit_px_b': float(exit_px) if exit_px else 0.0,
            'net_ret_b': float(net_ret),
            'hold_b': hold_days,
            'hs_ret_b': float(hs_ret),
            'excess_b': float(net_ret - hs_ret),
            'exit_dt_c': exit_dt,
            'exit_px_c': float(exit_px) if exit_px else 0.0,
            'net_ret_c': float(net_ret),
            'hold_c': hold_days,
        })

df_trades = pd.DataFrame(trades_all)
print(f"Total simulated non-M&A trades: {len(df_trades)}")

df_trades.to_csv(f"{OUT_DIR}/ledger_cross_year.csv", index=False, encoding='utf-8-sig')

# ==============================================================================
# Helper for D15 Multi-period Metrics
# ==============================================================================
def calc_d15_metrics(sub_df, ret_col='net_ret_b', excess_col='excess_b'):
    if len(sub_df) == 0:
        return {
            'trades': 0, 'win_rate': 0.0, 'avg_net_ret': 0.0, 'win_loss_ratio': 0.0,
            'max_drawdown': 0.0, 'cum_net_ret': 0.0, 'hs300_excess': 0.0
        }
    cnt = len(sub_df)
    rets = sub_df[ret_col]
    exc = sub_df[excess_col] if excess_col in sub_df.columns else rets
    win_rate = (rets > 0).mean()
    avg_net = rets.mean()
    
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 1e-6
    wl_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    date_rets = sub_df.groupby('buy_dt')[ret_col].mean()
    cum_eq = (1.0 + date_rets).cumprod()
    cum_ret = cum_eq.iloc[-1] - 1.0 if len(cum_eq) > 0 else 0.0
    running_max = cum_eq.cummax()
    dd = (cum_eq - running_max) / running_max
    mdd = abs(dd.min()) if len(dd) > 0 else 0.0
    
    date_exc = sub_df.groupby('buy_dt')[excess_col].mean() if excess_col in sub_df.columns else date_rets
    cum_exc = (1.0 + date_exc).cumprod().iloc[-1] - 1.0 if len(date_exc) > 0 else 0.0
    
    return {
        'trades': int(cnt),
        'win_rate': float(win_rate),
        'avg_net_ret': float(avg_net),
        'win_loss_ratio': float(wl_ratio),
        'max_drawdown': float(mdd),
        'cum_net_ret': float(cum_ret),
        'hs300_excess': float(cum_exc),
    }

def simulate_single_rotation(sub_df, ret_col='net_ret_b', exit_col='exit_dt_b'):
    if len(sub_df) == 0:
        return calc_d15_metrics(sub_df, ret_col=ret_col)
    sorted_df = sub_df.sort_values(['buy_dt', 'mcap'], ascending=[True, True])
    selected = []
    busy_until = '1990-01-01'
    for _, tr in sorted_df.iterrows():
        b_dt = tr['buy_dt']
        if b_dt >= busy_until:
            selected.append(tr)
            busy_until = tr[exit_col] if tr[exit_col] else b_dt
    df_sel = pd.DataFrame(selected)
    return calc_d15_metrics(df_sel, ret_col=ret_col)

# Strategy Performance Comparisons
results_summary = {}

methods = {
    'M1_RuleA_BreakSell': ('M1_Leader_Breakout', 'net_ret_a', 'exit_dt_a'),
    'M1_RuleB_TrendMA10': ('M1_Leader_Breakout', 'net_ret_b', 'exit_dt_b'),
    'M1_RuleC_TrendMA5':  ('M1_Leader_Breakout', 'net_ret_c', 'exit_dt_c'),
    'M2_Wave2_Rebound':   ('M2_Wave2_Rebound', 'net_ret_b', 'exit_dt_b'),
    'Combined_M1B_M2':    ('ALL', 'net_ret_b', 'exit_dt_b'),
}

for strat_key, (m_type, r_col, e_col) in methods.items():
    if m_type == 'ALL':
        st = df_trades.copy()
    else:
        st = df_trades[df_trades['method'] == m_type].copy()
        
    st_5y = st[st['buy_dt'] >= '2021-11-01']
    st_3y = st[st['buy_dt'] >= '2023-11-01']
    st_rec = st[st['buy_dt'] >= '2025-11-01']
    
    results_summary[strat_key] = {
        '10y_equal': calc_d15_metrics(st, ret_col=r_col),
        '10y_single': simulate_single_rotation(st, ret_col=r_col, exit_col=e_col),
        '5y_equal': calc_d15_metrics(st_5y, ret_col=r_col),
        '5y_single': simulate_single_rotation(st_5y, ret_col=r_col, exit_col=e_col),
        '3y_equal': calc_d15_metrics(st_3y, ret_col=r_col),
        '3y_single': simulate_single_rotation(st_3y, ret_col=r_col, exit_col=e_col),
        'recent_equal': calc_d15_metrics(st_rec, ret_col=r_col),
        'recent_single': simulate_single_rotation(st_rec, ret_col=r_col, exit_col=e_col),
    }

# Also save yearly real monsters
results_summary['yearly_real_monsters'] = yearly_real_monsters

with open(f"{OUT_DIR}/summary_cross_year.json", 'w', encoding='utf-8') as f:
    json.dump(results_summary, f, ensure_ascii=False, indent=2)

print("Topic 1 V2 completed successfully.")

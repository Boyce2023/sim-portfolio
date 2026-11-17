import os, sys, re, json, sqlite3, time
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock2/rd011_v4_100factors_20261116"
os.makedirs(OUT_DIR, exist_ok=True)

A_DAILY_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
KPL_PLATES_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl"
PIT_NOTICES_DB = f"{PROJECT_ROOT}/sim-portfolio/data/cninfo_notices_5y_pit.db"
ZT_TAPE_DB = f"{PROJECT_ROOT}/sim-portfolio/data/zt_micro_tape_5y_pit.db"
INDUSTRY_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/industry.csv"

# 1. Names
df_ind = pd.read_csv(INDUSTRY_PATH)
name_map = dict(zip(df_ind['code'].str[3:], df_ind['code_name']))

# 2. MA notices (120 days prior)
print("[1/5] Loading M&A notices from PIT DB...")
MA_PAT = re.compile(r"重大资产重组|控制权变更|实控人变更|筹划控制权|借壳|要约收购|筹划重大资产|购买资产.*复牌|协议转让.*控制权")
EXCLUDE_PAT = re.compile(r"解除限售|限售股上市|募集资金账户注销|业绩承诺补偿")

conn = sqlite3.connect(f"file:{PIT_NOTICES_DB}?mode=ro", uri=True)
c = conn.cursor()
rows = c.execute("SELECT trade_date_avail, sec_code, title, ann_type FROM notices WHERE trade_date_avail >= '2021-05-01'").fetchall()
conn.close()

ma_notices = {}
for dt, c6, title, atype in rows:
    t_all = f"{title} {atype}"
    if MA_PAT.search(t_all) and not EXCLUDE_PAT.search(t_all):
        if c6 not in ma_notices:
            ma_notices[c6] = []
        ma_notices[c6].append(dt)

# 3. Tape & KPL MA themes
print("[2/5] Loading Tape & KPL MA themes...")
TAPE_MA_PAT = re.compile(r"并购重组|股权转让|实控人变更|借壳|壳资源|ST板块")
conn = sqlite3.connect(f"file:{ZT_TAPE_DB}?mode=ro", uri=True)
c = conn.cursor()
rows = c.execute("SELECT trade_date, sec_code, plate_name, reason_desc FROM zt_micro_tape WHERE trade_date >= '2021-05-01'").fetchall()
conn.close()

tape_ma_set = set()
for dt, c6, p_name, reason in rows:
    t_all = f"{p_name} {reason or ''}"
    if TAPE_MA_PAT.search(t_all):
        tape_ma_set.add((dt, c6))

kpl_ma_set = set()
with open(KPL_PLATES_PATH) as f:
    for line in f:
        d = json.loads(line)
        dt = d['date']
        if dt < '2021-05-01': continue
        for p in d.get('plates', []):
            p_name = p.get('plate', '')
            if TAPE_MA_PAT.search(p_name):
                for stk in p.get('stocks', []):
                    c6 = stk[0]
                    kpl_ma_set.add((dt, c6))

# 4. Prices
print("[3/5] Loading Price Data...")
cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'amount', 'volume', 'turn', 'oshare']
df_act = ds.dataset(A_DAILY_PATH, format='parquet').scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2020-06-01'))).to_table().to_pandas()
df_del = ds.dataset(A_DELISTED_PATH, format='parquet').scanner(columns=cols, filter=(ds.field('date') >= pd.Timestamp('2020-06-01'))).to_table().to_pandas()
df = pd.concat([df_act, df_del], ignore_index=True)
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
df['mcap'] = df['close'] * df['oshare'] / 1e8
df['name'] = df['c6'].map(name_map).fillna(df['c6'])

# 10cm limits
df['zt_px'] = np.floor(df['pre_c'] * 1.10 * 100.0 + 0.5) / 100.0
df['dt_px'] = np.floor(df['pre_c'] * 0.90 * 100.0 + 0.5) / 100.0
df['is_zt'] = (df['close'] >= df['zt_px'] - 0.01) & (df['pct'] >= 0.065) & (df['pre_c'] > 0)
df['is_yizi'] = df['is_zt'] & (df['open'] >= df['zt_px'] - 0.01) & (df['low'] >= df['zt_px'] - 0.01)

# ST check: name has ST / *ST / 退, or true ST (pct < 0.065)
df['is_st_name'] = df['name'].str.startswith(('ST', '*ST', '退')) | df['name'].str.contains('退')
df['is_true_st'] = (df['close'] >= df['zt_px'] - 0.01) & (df['pct'] < 0.065)

# Streak
s = df['is_zt'].astype(int)
df['zt_streak'] = s.groupby((~df['is_zt']).cumsum()).cumsum()

# Past 20 days zt count (prior to today)
df['past20_zt_cnt'] = g['is_zt'].transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum()).fillna(0).astype(int)

# Past 5 days yizi zt count
df['past5_yizi_cnt'] = g['is_yizi'].transform(lambda s: s.rolling(5, min_periods=1).sum()).fillna(0).astype(int)

# Next day
df['d1_open'] = g['open'].shift(-1)
df['d1_close'] = g['close'].shift(-1)
df['d1_zt_px'] = np.floor(df['close'] * 1.10 * 100.0 + 0.5) / 100.0
df['d1_dt'] = g['dt_str'].shift(-1)

print("[4/5] Filtering Candidate Pool...")
SEASONS = [
    ('2021/22', '2021-10-15', '2022-01-15', '2022-01-20'),
    ('2022/23', '2022-10-15', '2023-01-15', '2023-01-20'),
    ('2023/24', '2023-10-15', '2024-01-15', '2024-01-20'),
    ('2024/25', '2024-10-15', '2025-01-15', '2025-01-20'),
    ('2025/26', '2025-10-15', '2026-01-15', '2026-01-20'),
]

cands = []
for s_name, s_dt, e_dt_15, e_dt_20 in SEASONS:
    # We take up to e_dt_15 as strict candidate pool per Section II.3
    sub = df[(df['dt_str'] >= s_dt) & (df['dt_str'] <= e_dt_15)].copy()
    
    # 1. Mainboard, not IPO < 60 days, not ST
    mask_basic = (
        (sub['trade_num'] >= 60) &
        (~sub['is_st_name']) &
        (~sub['is_true_st']) &
        (sub['mcap'] >= 20.0) &
        (sub['is_zt']) &
        (~sub['is_yizi']) &
        (sub['d1_dt'].notna()) &
        (sub['d1_open'] > 0) &
        (sub['d1_open'] < sub['d1_zt_px'] - 0.01) & # d1 non-yizi purchasable
        (sub['past5_yizi_cnt'] < 2) # not continuous yizi
    )
    
    # Forms
    mask_type1 = mask_basic & (sub['zt_streak'].isin([2, 3, 4, 5]))
    mask_type2 = mask_basic & (sub['zt_streak'] == 1) & (sub['past20_zt_cnt'] >= 2)
    sub_cands = sub[mask_type1 | mask_type2].copy()
    sub_cands['cand_type'] = np.where(sub_cands['zt_streak'].isin([2, 3, 4, 5]), 'T1_streak_leader', 'T2_rebound_wave')
    sub_cands['season'] = s_name
    
    for idx_row, row in sub_cands.iterrows():
        c6 = row['c6']
        sig_dt = row['dt_str']
        
        # M&A Notice Check: 120 days prior
        sig_t = pd.to_datetime(sig_dt)
        lookback_120 = (sig_t - pd.Timedelta(days=120)).strftime('%Y-%m-%d')
        has_ma_notice = False
        if c6 in ma_notices:
            for n_dt in ma_notices[c6]:
                if lookback_120 <= n_dt <= sig_dt:
                    has_ma_notice = True
                    break
        if has_ma_notice:
            continue
            
        # Tape & KPL MA theme check on sig_dt
        if (sig_dt, c6) in tape_ma_set or (sig_dt, c6) in kpl_ma_set:
            continue
            
        cands.append({
            'season': s_name,
            'sig_dt': sig_dt,
            'buy_dt': row['d1_dt'],
            'c6': c6,
            'name': row['name'],
            'cand_type': row['cand_type'],
            'zt_streak': int(row['zt_streak']),
            'past20_zt_cnt': int(row['past20_zt_cnt']),
            'close': float(row['close']),
            'd1_open': float(row['d1_open']),
            'mcap': float(row['mcap']),
        })

df_cand = pd.DataFrame(cands)
df_cand.sort_values(['sig_dt', 'c6'], inplace=True)
df_cand.reset_index(drop=True, inplace=True)
print(f"[5/5] Total Candidates Generated: {len(df_cand):,}")
print("By season:")
print(df_cand['season'].value_counts().sort_index())

# Save candidate universe for Subagent B and both of us!
df_cand.to_parquet(f"{OUT_DIR}/candidate_universe.parquet", index=False)
df_cand[['season', 'sig_dt', 'buy_dt', 'c6', 'name', 'cand_type']].to_csv(f"{OUT_DIR}/candidate_universe.csv", index=False)
print("Saved candidate universe to:")
print(f"  {OUT_DIR}/candidate_universe.parquet")
print(f"  {OUT_DIR}/candidate_universe.csv")

# Check benchmark stocks
benchmarks = ['000592', '000547', '603778', '603366', '000759']
sub_b = df_cand[df_cand['c6'].isin(benchmarks)]
print("\nBenchmark stocks in candidate universe:")
for _, r in sub_b.iterrows():
    print(f"  {r['season']} {r['sig_dt']} (buy {r['buy_dt']}) {r['c6']} {r['name']:6s} {r['cand_type']} streak={r['zt_streak']} mcap={r['mcap']:.1f}亿")

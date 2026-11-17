import os, sys, re, json, sqlite3, time
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock2/rd011_v4_100factors_20261116"
os.makedirs(OUT_DIR, exist_ok=True)

A_DAILY_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"
INDEX_CACHE_PATH = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
PIT_TOP10_PATH = f"{PROJECT_ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
ZT_TAPE_DB = f"{PROJECT_ROOT}/sim-portfolio/data/zt_micro_tape_5y_pit.db"
LHB_BUY_PATH = f"{PROJECT_ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL_PATH = f"{PROJECT_ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_sell.parquet"
SEVERE_HIS_PATH = f"{PROJECT_ROOT}/sim-portfolio/data/kpl/severe_his.json"
CAND_UNIVERSE_PATH = f"{OUT_DIR}/candidate_universe.parquet"

t0 = time.time()
print("================================================================================")
print("RD011-V4 Part 1: 55 Factors & Dual Severe Abnormal Volatility Detour Engine")
print("================================================================================")

# 1. Load Candidate Universe
print("\n[1/7] Loading candidate universe...")
df_cand = pd.read_parquet(CAND_UNIVERSE_PATH)
print(f"      Total candidates: {len(df_cand):,}")

# 2. Load Indices
print("\n[2/7] Loading benchmark index series...")
with open(INDEX_CACHE_PATH) as f:
    idx_d = json.load(f)
sh_idx = dict(idx_d['sh000002']) # 上证A股指数
sz_idx = dict(idx_d['sz399107']) # 深证A指
hs300 = dict(idx_d['sh000300'])  # 沪深300

# 3. Load PIT Top 10 Holders
print("\n[3/7] Loading PIT top 10 holders...")
with open(PIT_TOP10_PATH) as f:
    top10_d = json.load(f)

# 4. Load ZT Micro Tape
print("\n[4/7] Loading ZT micro tape database...")
conn_tape = sqlite3.connect(f"file:{ZT_TAPE_DB}?mode=ro", uri=True)
cur = conn_tape.cursor()
rows = cur.execute("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape WHERE trade_date >= '2021-09-01'").fetchall()
conn_tape.close()
tape_dict = {}
for dt, c6, s_time, s_amt, ob_cnt in rows:
    tape_dict[(dt, c6)] = {
        'first_seal_time': s_time or '',
        'seal_amount': float(s_amt or 0.0),
        'open_board_count': int(ob_cnt or 0)
    }
print(f"      Loaded {len(tape_dict):,} tape records.")

# 5. Load LHB (Dragon Tiger) Vectorized
print("\n[5/7] Loading Dragon-Tiger data (LHB vectorized)...")
df_lhb_b = pd.read_parquet(LHB_BUY_PATH)
df_lhb_s = pd.read_parquet(LHB_SELL_PATH)
df_lhb_b['dt_str'] = pd.to_datetime(df_lhb_b['TRADE_DATE']).dt.strftime('%Y-%m-%d')
df_lhb_s['dt_str'] = pd.to_datetime(df_lhb_s['TRADE_DATE']).dt.strftime('%Y-%m-%d')
df_lhb_b['c6'] = df_lhb_b['SECURITY_CODE'].astype(str).str[:6]
df_lhb_s['c6'] = df_lhb_s['SECURITY_CODE'].astype(str).str[:6]

TOP_YOUZI_PAT = r"六一中路|大连金马路|江苏路|朱雀大街|北京呼家楼"
QUANT_PAT = r"上海分公司|华泰证券股份有限公司总部"
DAY_SURF_PAT = r"上塘路|绿景路"
LHASA_PAT = r"拉萨"

# Vectorized flags
df_lhb_b['is_inst'] = df_lhb_b['OPERATEDEPT_NAME'].str.contains('机构专用', na=False)
df_lhb_b['is_top_yz'] = df_lhb_b['OPERATEDEPT_NAME'].str.contains(TOP_YOUZI_PAT, na=False)
df_lhb_b['is_quant'] = df_lhb_b['OPERATEDEPT_NAME'].str.contains(QUANT_PAT, na=False)
df_lhb_b['is_surf'] = df_lhb_b['OPERATEDEPT_NAME'].str.contains(DAY_SURF_PAT, na=False)
df_lhb_b['is_lhasa'] = df_lhb_b['OPERATEDEPT_NAME'].str.contains(LHASA_PAT, na=False)

df_lhb_b['inst_buy'] = np.where(df_lhb_b['is_inst'], df_lhb_b['BUY'], 0.0)
df_lhb_b['top_yz_buy'] = np.where(df_lhb_b['is_top_yz'], df_lhb_b['BUY'], 0.0)
df_lhb_b['lhasa_buy'] = np.where(df_lhb_b['is_lhasa'], df_lhb_b['BUY'], 0.0)

agg_b = df_lhb_b.groupby(['dt_str', 'c6']).agg(
    tot_buy=('BUY', 'sum'),
    inst_buy_cnt=('is_inst', 'sum'),
    inst_buy_amt=('inst_buy', 'sum'),
    has_top_yz=('is_top_yz', 'any'),
    top_yz_buy=('top_yz_buy', 'sum'),
    has_quant=('is_quant', 'any'),
    has_surf=('is_surf', 'any'),
    lhasa_cnt=('is_lhasa', 'sum'),
    lhasa_buy=('lhasa_buy', 'sum')
).reset_index()

df_lhb_s['is_inst'] = df_lhb_s['OPERATEDEPT_NAME'].str.contains('机构专用', na=False)
df_lhb_s['is_top_yz'] = df_lhb_s['OPERATEDEPT_NAME'].str.contains(TOP_YOUZI_PAT, na=False)
df_lhb_s['inst_sell'] = np.where(df_lhb_s['is_inst'], df_lhb_s['SELL'], 0.0)
df_lhb_s['top_yz_sell'] = np.where(df_lhb_s['is_top_yz'], df_lhb_s['SELL'], 0.0)

agg_s = df_lhb_s.groupby(['dt_str', 'c6']).agg(
    tot_sell=('SELL', 'sum'),
    inst_sell_amt=('inst_sell', 'sum'),
    top_yz_sell=('top_yz_sell', 'sum'),
).reset_index()

lhb_merged = pd.merge(agg_b, agg_s, on=['dt_str', 'c6'], how='outer').fillna(0.0)
lhb_map = {}
for r in lhb_merged.itertuples(index=False):
    lhb_map[(r.dt_str, r.c6)] = {
        'tot_buy': float(r.tot_buy),
        'tot_sell': float(r.tot_sell),
        'inst_buy_cnt': int(r.inst_buy_cnt),
        'inst_buy_amt': float(r.inst_buy_amt),
        'inst_sell_amt': float(r.inst_sell_amt),
        'has_top_yz': int(bool(r.has_top_yz)),
        'top_yz_buy': float(r.top_yz_buy),
        'top_yz_sell': float(r.top_yz_sell),
        'has_quant': int(bool(r.has_quant)),
        'has_surf': int(bool(r.has_surf)),
        'lhasa_cnt': int(r.lhasa_cnt),
        'lhasa_buy': float(r.lhasa_buy),
    }
print(f"      Aggregated {len(lhb_map):,} LHB day-stock records in vectorized form.")

# 6. Load Severe History
with open(SEVERE_HIS_PATH) as f:
    sev_d = json.load(f)
sev_records = defaultdict(list)
for r in sev_d.get('rows', []):
    c6 = str(r[0])
    dt = str(r[18])
    if dt != '0000-00-00':
        sev_records[c6].append(dt)

# 7. Load Prices and build per-stock bar arrays
print("\n[6/7] Loading price arrays and building bar structures...")
cand_codes = set(df_cand['c6'].unique())
benchmarks = {'000592', '000547', '603778', '603366', '000759'}
needed_codes = cand_codes | benchmarks

cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'amount', 'volume', 'turn', 'oshare']
flt_cond = (ds.field('date') >= pd.Timestamp('2020-01-01'))
df_act = ds.dataset(A_DAILY_PATH, format='parquet').scanner(columns=cols, filter=flt_cond).to_table().to_pandas()
df_del = ds.dataset(A_DELISTED_PATH, format='parquet').scanner(columns=cols, filter=flt_cond).to_table().to_pandas()
df_all = pd.concat([df_act, df_del], ignore_index=True)
df_all['c6'] = df_all['ticker'].astype(str).str[:6]
df_all = df_all[df_all['c6'].isin(needed_codes)].copy()
df_all['dt_str'] = df_all['date'].dt.strftime('%Y-%m-%d')
df_all.sort_values(['c6', 'dt_str'], inplace=True)
df_all.drop_duplicates(subset=['c6', 'dt_str'], keep='first', inplace=True)
df_all.reset_index(drop=True, inplace=True)

stock_bars = {}
g_all = df_all.groupby('c6')

for c6, group in g_all:
    dts = group['dt_str'].values
    dt_to_idx = {d: i for i, d in enumerate(dts)}
    closes = group['close'].values.astype(float)
    opens = group['open'].values.astype(float)
    highs = group['high'].values.astype(float)
    lows = group['low'].values.astype(float)
    amounts = group['amount'].values.astype(float)
    volumes = group['volume'].values.astype(float)
    turns = group['turn'].values.astype(float)
    oshares = group['oshare'].values.astype(float)
    mcaps = closes * oshares / 1e8
    
    n = len(closes)
    pre_c = np.empty(n, dtype=float)
    pre_c[0] = closes[0]
    pre_c[1:] = closes[:-1]
    
    zt_px = np.floor(pre_c * 1.10 * 100.0 + 0.5) / 100.0
    pct = closes / np.maximum(1e-4, pre_c) - 1.0
    is_zt = (closes >= zt_px - 0.01) & (pct >= 0.065) & (pre_c > 0)
    is_yizi = is_zt & (opens >= zt_px - 0.01) & (lows >= zt_px - 0.01)
    
    s_close = pd.Series(closes)
    ma5 = s_close.rolling(5, min_periods=1).mean().values
    ma10 = s_close.rolling(10, min_periods=1).mean().values
    ma20 = s_close.rolling(20, min_periods=1).mean().values
    vol_ma5 = pd.Series(volumes).rolling(5, min_periods=1).mean().values
    amt_ma5 = pd.Series(amounts).rolling(5, min_periods=1).mean().values
    
    min_3y = s_close.rolling(750, min_periods=30).min().values
    max_3y = s_close.rolling(750, min_periods=30).max().values
    max_60 = s_close.shift(1).rolling(60, min_periods=10).max().values
    max_250 = s_close.shift(1).rolling(250, min_periods=30).max().values
    
    s_int = is_zt.astype(int)
    streak = pd.Series(s_int).groupby((~pd.Series(is_zt)).cumsum()).cumsum().values
    
    idx_dict = sh_idx if c6.startswith('60') else sz_idx
    
    dev_10d_arr = np.zeros(n, dtype=float)
    dev_30d_arr = np.zeros(n, dtype=float)
    ord_abn_arr = np.zeros(n, dtype=int)
    p_max_10d_arr = np.full(n, 999999.0, dtype=float)
    p_max_30d_arr = np.full(n, 999999.0, dtype=float)
    
    for i in range(n):
        cur_d = dts[i]
        c_i = closes[i]
        i_cur = idx_dict.get(cur_d, None)
        if i_cur is None or i_cur <= 0 or c_i <= 0:
            continue
            
        max_d10 = -9.99
        min_p10 = 999999.0
        for w in range(1, min(11, i + 1)):
            b_idx = i - w
            b_d = dts[b_idx]
            b_c = closes[b_idx]
            i_b = idx_dict.get(b_d, None)
            if i_b is None or i_b <= 0 or b_c <= 0:
                continue
            idx_chg = i_cur / i_b - 1.0
            stk_chg = c_i / b_c - 1.0
            dev = stk_chg - idx_chg
            if dev > max_d10:
                max_d10 = dev
            p_trig10 = b_c * (2.0 + idx_chg)
            if p_trig10 < min_p10:
                min_p10 = p_trig10
        dev_10d_arr[i] = max_d10 if max_d10 > -9.0 else 0.0
        p_max_10d_arr[i] = min_p10
        
        max_d30 = -9.99
        min_p30 = 999999.0
        for w in range(1, min(31, i + 1)):
            b_idx = i - w
            b_d = dts[b_idx]
            b_c = closes[b_idx]
            i_b = idx_dict.get(b_d, None)
            if i_b is None or i_b <= 0 or b_c <= 0:
                continue
            idx_chg = i_cur / i_b - 1.0
            stk_chg = c_i / b_c - 1.0
            dev = stk_chg - idx_chg
            if dev > max_d30:
                max_d30 = dev
            p_trig30 = b_c * (3.0 + idx_chg)
            if p_trig30 < min_p30:
                min_p30 = p_trig30
        dev_30d_arr[i] = max_d30 if max_d30 > -9.0 else 0.0
        p_max_30d_arr[i] = min_p30
        
        if i >= 3:
            b_idx = i - 3
            b_d = dts[b_idx]
            b_c = closes[b_idx]
            i_b = idx_dict.get(b_d, None)
            if i_b and i_b > 0 and b_c > 0:
                dev3 = (c_i / b_c - 1.0) - (i_cur / i_b - 1.0)
                if dev3 >= 0.20:
                    ord_abn_arr[i] = 1
                    
    stock_bars[c6] = {
        'dts': dts,
        'dt_to_idx': dt_to_idx,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': closes,
        'amount': amounts,
        'volume': volumes,
        'turn': turns,
        'oshare': oshares,
        'mcap': mcaps,
        'pre_c': pre_c,
        'zt_px': zt_px,
        'pct': pct,
        'is_zt': is_zt,
        'is_yizi': is_yizi,
        'streak': streak,
        'ma5': ma5,
        'ma10': ma10,
        'ma20': ma20,
        'vol_ma5': vol_ma5,
        'amt_ma5': amt_ma5,
        'min_3y': min_3y,
        'max_3y': max_3y,
        'max_60': max_60,
        'max_250': max_250,
        'dev_10d': dev_10d_arr,
        'dev_30d': dev_30d_arr,
        'ord_abn': ord_abn_arr,
        'p_max_10d': p_max_10d_arr,
        'p_max_30d': p_max_30d_arr,
    }
print(f"      Built bar structures for {len(stock_bars):,} stocks.")

# 8. Compute all 55 factors and 4 returns
print("\n[7/7] Computing 55 factors and 4 exits for all candidates...")
results = []
FEE_RATE = 0.0020

def get_top10_info(c6, sig_dt):
    records = top10_d.get(c6, [])
    valid = [r for r in records if r[0] <= sig_dt]
    if not valid:
        return 0.38, 0.20, 0.29, 0.0
    latest = valid[-1]
    top10_ratio = float(latest[2]) / 100.0
    top1_ratio = float(latest[3]) / 100.0
    top5_ratio = min(top10_ratio, top1_ratio * 1.5 + (top10_ratio - top1_ratio) * 0.5)
    chg_qoq = 0.0
    if len(valid) >= 2:
        chg_qoq = float(latest[2]) - float(valid[-2][2])
    return top10_ratio, top1_ratio, top5_ratio, chg_qoq

trading_dts_all = sorted(list(hs300.keys()))

for cand in df_cand.itertuples(index=False):
    c6 = cand.c6
    sig_dt = cand.sig_dt
    buy_dt = cand.buy_dt
    season = cand.season
    name = cand.name
    cand_type = cand.cand_type
    cand_streak = int(cand.zt_streak)
    cand_past20 = int(cand.past20_zt_cnt)
    
    sb = stock_bars.get(c6)
    if not sb or sig_dt not in sb['dt_to_idx']:
        continue
    pos = sb['dt_to_idx'][sig_dt]
    if pos + 1 >= len(sb['dts']):
        continue
        
    c_sig = sb['close'][pos]
    o_sig = sb['open'][pos]
    h_sig = sb['high'][pos]
    l_sig = sb['low'][pos]
    pre_c_sig = sb['pre_c'][pos]
    mcap_sig = sb['mcap'][pos]
    amt_sig = sb['amount'][pos] / 1e8 # 亿元
    turn_sig = sb['turn'][pos] * 100.0 # %
    vol_ratio_5d = sb['volume'][pos] / max(1.0, sb['vol_ma5'][pos])
    
    d1_pos = pos + 1
    d1_open = sb['open'][d1_pos]
    d1_zt_px = sb['zt_px'][d1_pos]
    d1_open_pct = d1_open / c_sig - 1.0
    
    # Group 1: 双严重异动与绕异动微观因子 (18个)
    dev_10d = float(sb['dev_10d'][pos])
    dev_30d = float(sb['dev_30d'][pos])
    p_max_10d = float(sb['p_max_10d'][pos])
    p_max_30d = float(sb['p_max_30d'][pos])
    headroom_10d = (p_max_10d / d1_open) - 1.0 if d1_open > 0 and p_max_10d < 999990.0 else 9.99
    headroom_30d = (p_max_30d / d1_open) - 1.0 if d1_open > 0 and p_max_30d < 999990.0 else 9.99
    tight_headroom = min(headroom_10d, headroom_30d)
    
    p15_start = max(0, pos - 14)
    past15_max_dev10 = float(np.max(sb['dev_10d'][p15_start:pos+1]))
    is_detour_10d = int((past15_max_dev10 >= 0.65) and (past15_max_dev10 <= 0.99) and 
                        (dev_10d < 0.55) and (headroom_10d >= 0.30) and (headroom_30d >= 0.35))
    
    if dev_30d >= 1.95:
        is_near_30d_200 = 2
    elif dev_30d >= 1.20:
        is_near_30d_200 = 1
    else:
        is_near_30d_200 = 0
        
    p10_start = max(0, pos - 9)
    ord_abn_cnt_10d = int(np.sum(sb['ord_abn'][p10_start:pos+1]))
    
    dev_10d_3d_ago = float(sb['dev_10d'][pos - 3]) if pos >= 3 else dev_10d
    dev_10d_slope_3d = dev_10d - dev_10d_3d_ago
    dev_30d_ratio = dev_30d / 2.0
    
    days_since_last_ord_abn = 15
    for k in range(min(10, pos + 1)):
        if sb['ord_abn'][pos - k] == 1:
            days_since_last_ord_abn = k
            break
            
    is_ord_abn_warning = int(ord_abn_cnt_10d >= 3)
    is_detour_active = int(is_detour_10d == 1 and cand_streak == 1)
    
    sev_list = sev_records.get(c6, [])
    severe_his_has_flag = int(any(0 <= (pd.to_datetime(sig_dt) - pd.to_datetime(d)).days <= 60 for d in sev_list))
    is_severely_constrained = int(tight_headroom < 0.10)
    
    # Group 2: 量价形态与大周期位置因子 (15个)
    clean_brk60 = int(pos >= 1 and c_sig >= sb['max_60'][pos])
    clean_brk250 = int(pos >= 1 and not np.isnan(sb['max_250'][pos]) and c_sig >= sb['max_250'][pos])
    
    min_3y_val = sb['min_3y'][pos] if not np.isnan(sb['min_3y'][pos]) else c_sig * 0.5
    max_3y_val = sb['max_3y'][pos] if not np.isnan(sb['max_3y'][pos]) else c_sig * 1.5
    pos_3y = float((c_sig - min_3y_val) / max(1e-4, (max_3y_val - min_3y_val)))
    
    ma10_val = sb['ma10'][pos]
    ma10_5d = sb['ma10'][pos - 5] if pos >= 5 else ma10_val
    ma10_slope = float((ma10_val - ma10_5d) / max(1e-4, ma10_5d))
    
    ma20_val = sb['ma20'][pos]
    ma20_dist = float(c_sig / max(1e-4, ma20_val) - 1.0)
    
    p250_start = max(0, pos - 250)
    kpl_dragon_mem_1y = int(np.max(sb['streak'][p250_start:pos+1]) >= 5)
    
    upper_shadow_d0 = float((h_sig - max(o_sig, c_sig)) / max(1e-4, pre_c_sig))
    amplitude_d0 = float((h_sig - l_sig) / max(1e-4, pre_c_sig))
    
    # Group 3: 十大股东筹码锁仓因子 (8个)
    lock_top10, top1_ratio, top5_ratio, lock_chg_qoq = get_top10_info(c6, sig_dt)
    real_free_mcap = float(mcap_sig * (1.0 - lock_top10))
    real_turn = float(turn_sig / max(0.05, 1.0 - lock_top10))
    is_high_lock_midcap = int((lock_top10 >= 0.45) and (45.0 <= mcap_sig <= 250.0))
    holder_num_chg_qoq = float(lock_top10 / max(1e-4, top1_ratio))
    
    # Group 4: 微观盘口与龙虎榜席位因子 (14个)
    tape_rec = tape_dict.get((sig_dt, c6), {})
    s_time = tape_rec.get('first_seal_time', '')
    if s_time and len(s_time) >= 5:
        try:
            parts = [float(x) for x in s_time.split(':')]
            hh, mm, ss = parts[0], parts[1], parts[2] if len(parts) > 2 else 0.0
            if hh < 12:
                first_seal_mins = (hh - 9) * 60.0 + (mm - 30) + ss / 60.0
            else:
                first_seal_mins = 120.0 + (hh - 13) * 60.0 + mm + ss / 60.0
            first_seal_mins = float(np.clip(first_seal_mins, 0.0, 240.0))
        except:
            first_seal_mins = 180.0
    else:
        first_seal_mins = 180.0
        
    open_board_count = int(tape_rec.get('open_board_count', 0))
    seal_amt = float(tape_rec.get('seal_amount', 0.0)) / 1e8
    seal_to_free_mcap = float(seal_amt / max(0.1, real_free_mcap))
    
    l_pct = float(l_sig / max(1e-4, pre_c_sig) - 1.0)
    vol_ma5_val = float(sb['amt_ma5'][pos])
    is_top_sealed = 30.0 if (c_sig == h_sig) else 0.0
    low_bonus = float(np.clip(l_pct * 100.0, -10.0, 10.0) * 1.5)
    body_bonus = float((c_sig - o_sig) / max(1e-4, pre_c_sig) * 100.0 * 2.0)
    vol_pen = 15.0 if (amt_sig / max(1.0, vol_ma5_val / 1e8) > 4.0) else 0.0
    d0_tightness = float(is_top_sealed + low_bonus + body_bonus - vol_pen)
    
    lhb_rec = lhb_map.get((sig_dt, c6), {})
    tot_lhb_buy = float(lhb_rec.get('tot_buy', 0.0)) / 1e8
    tot_lhb_sell = float(lhb_rec.get('tot_sell', 0.0)) / 1e8
    tot_lhb_net = tot_lhb_buy - tot_lhb_sell
    
    lhb_has_top_youzi = int(lhb_rec.get('has_top_yz', 0))
    top_yz_b = float(lhb_rec.get('top_yz_buy', 0.0))
    top_yz_s = float(lhb_rec.get('top_yz_sell', 0.0))
    lhb_top_youzi_locked = int(lhb_has_top_youzi == 1 and top_yz_b > 0 and (top_yz_s == 0 or (top_yz_b - top_yz_s)/top_yz_b >= 0.70))
    
    lhb_inst_buy_cnt = int(lhb_rec.get('inst_buy_cnt', 0))
    lhb_inst_net_yi = float((lhb_rec.get('inst_buy_amt', 0.0) - lhb_rec.get('inst_sell_amt', 0.0)) / 1e8)
    lhb_quant_present = int(lhb_rec.get('has_quant', 0))
    lhb_day_surf_present = int(lhb_rec.get('has_surf', 0))
    lhb_lhasa_cnt = int(lhb_rec.get('lhasa_cnt', 0))
    lhb_lhasa_buy_ratio = float(lhb_rec.get('lhasa_buy', 0.0) / max(1.0, lhb_rec.get('tot_buy', 0.0)))
    lhb_net_buy_to_amt = float(tot_lhb_net / max(0.1, amt_sig))
    
    sig_t = pd.to_datetime(sig_dt)
    is_mon = (sig_t.weekday() == 0)
    is_post_holiday = False
    try:
        dt_idx = trading_dts_all.index(sig_dt)
        if dt_idx > 0:
            prev_dt = trading_dts_all[dt_idx - 1]
            if (sig_t - pd.to_datetime(prev_dt)).days >= 3:
                is_post_holiday = True
    except:
        pass
    is_monday_or_post_holiday = int(is_mon or is_post_holiday)
    
    # Returns
    buy_px = d1_open
    
    # 1. ret_5d
    exit_p5_pos = min(len(sb['dts']) - 1, d1_pos + 4)
    exit_px_5d = sb['close'][exit_p5_pos]
    ret_5d = float((exit_px_5d * (1.0 - FEE_RATE)) / (buy_px * (1.0 + FEE_RATE)) - 1.0)
    
    # 2. ret_10d
    exit_p10_pos = min(len(sb['dts']) - 1, d1_pos + 9)
    exit_px_10d = sb['close'][exit_p10_pos]
    ret_10d = float((exit_px_10d * (1.0 - FEE_RATE)) / (buy_px * (1.0 + FEE_RATE)) - 1.0)
    
    hs_buy = hs300.get(buy_dt, None)
    hs_5d = hs300.get(sb['dts'][exit_p5_pos], None)
    hs_10d = hs300.get(sb['dts'][exit_p10_pos], None)
    hs300_ret_5d = float(hs_5d / hs_buy - 1.0) if hs_buy and hs_5d else 0.0
    hs300_ret_10d = float(hs_10d / hs_buy - 1.0) if hs_buy and hs_10d else 0.0
    excess_5d = ret_5d - hs300_ret_5d
    excess_10d = ret_10d - hs300_ret_10d
    
    # 3. ret_2stage_ma10
    exit_px_ma10 = None
    exit_pos_ma10 = None
    d1_close = sb['close'][d1_pos]
    d1_is_zt = sb['is_zt'][d1_pos]
    d1_ret_pct = d1_close / buy_px - 1.0
    
    if (not d1_is_zt) and (d1_ret_pct < 0.01):
        if d1_pos + 1 < len(sb['dts']):
            exit_pos_ma10 = d1_pos + 1
            exit_px_ma10 = sb['open'][exit_pos_ma10]
        else:
            exit_pos_ma10 = d1_pos
            exit_px_ma10 = d1_close
    else:
        max_fwd = min(30, len(sb['dts']) - d1_pos - 1)
        triggered = False
        ever_reached_9pct = (sb['high'][d1_pos] / buy_px - 1.0 >= 0.09) or d1_is_zt
        
        for k in range(1, max_fwd + 1):
            curr_pos = d1_pos + k
            c_curr = sb['close'][curr_pos]
            h_curr = sb['high'][curr_pos]
            ma10_curr = sb['ma10'][curr_pos]
            if (h_curr / buy_px - 1.0) >= 0.09:
                ever_reached_9pct = True
            guard_line = max(ma10_curr * 0.985, buy_px * 1.005) if ever_reached_9pct else (ma10_curr * 0.985)
            if c_curr < guard_line:
                if curr_pos + 1 < len(sb['dts']):
                    exit_pos_ma10 = curr_pos + 1
                    exit_px_ma10 = sb['open'][exit_pos_ma10]
                else:
                    exit_pos_ma10 = curr_pos
                    exit_px_ma10 = c_curr
                triggered = True
                break
        if not triggered:
            exit_pos_ma10 = min(len(sb['dts']) - 1, d1_pos + max_fwd)
            exit_px_ma10 = sb['close'][exit_pos_ma10]
            
    ret_2stage_ma10 = float((exit_px_ma10 * (1.0 - FEE_RATE)) / (buy_px * (1.0 + FEE_RATE)) - 1.0)
    hs_ma10 = hs300.get(sb['dts'][exit_pos_ma10], None)
    hs300_ret_ma10 = float(hs_ma10 / hs_buy - 1.0) if hs_buy and hs_ma10 else 0.0
    excess_2stage_ma10 = ret_2stage_ma10 - hs300_ret_ma10
    
    # 4. ret_smart_dev30_ma10
    exit_px_smart = None
    exit_pos_smart = None
    
    if (not d1_is_zt) and (d1_ret_pct < 0.01):
        if d1_pos + 1 < len(sb['dts']):
            exit_pos_smart = d1_pos + 1
            exit_px_smart = sb['open'][exit_pos_smart]
        else:
            exit_pos_smart = d1_pos
            exit_px_smart = d1_close
    else:
        max_fwd = min(30, len(sb['dts']) - d1_pos - 1)
        triggered = False
        ever_reached_9pct = (sb['high'][d1_pos] / buy_px - 1.0 >= 0.09) or d1_is_zt
        
        for k in range(1, max_fwd + 1):
            curr_pos = d1_pos + k
            c_curr = sb['close'][curr_pos]
            h_curr = sb['high'][curr_pos]
            ma10_curr = sb['ma10'][curr_pos]
            dev30_curr = sb['dev_30d'][curr_pos]
            
            if dev30_curr >= 1.93:
                if curr_pos + 1 < len(sb['dts']):
                    exit_pos_smart = curr_pos + 1
                    exit_px_smart = sb['open'][exit_pos_smart]
                else:
                    exit_pos_smart = curr_pos
                    exit_px_smart = c_curr
                triggered = True
                break
                
            if (h_curr / buy_px - 1.0) >= 0.09:
                ever_reached_9pct = True
            guard_line = max(ma10_curr * 0.985, buy_px * 1.005) if ever_reached_9pct else (ma10_curr * 0.985)
            if c_curr < guard_line:
                if curr_pos + 1 < len(sb['dts']):
                    exit_pos_smart = curr_pos + 1
                    exit_px_smart = sb['open'][exit_pos_smart]
                else:
                    exit_pos_smart = curr_pos
                    exit_px_smart = c_curr
                triggered = True
                break
        if not triggered:
            exit_pos_smart = min(len(sb['dts']) - 1, d1_pos + max_fwd)
            exit_px_smart = sb['close'][exit_pos_smart]
            
    ret_smart_dev30_ma10 = float((exit_px_smart * (1.0 - FEE_RATE)) / (buy_px * (1.0 + FEE_RATE)) - 1.0)
    hs_smart = hs300.get(sb['dts'][exit_pos_smart], None)
    hs300_ret_smart = float(hs_smart / hs_buy - 1.0) if hs_buy and hs_smart else 0.0
    excess_smart_dev30 = ret_smart_dev30_ma10 - hs300_ret_smart
    
    results.append({
        'season': season,
        'sig_dt': sig_dt,
        'buy_dt': buy_dt,
        'c6': c6,
        'name': name,
        'cand_type': cand_type,
        'zt_streak': cand_streak,
        'close_px': float(c_sig),
        'd1_open': float(d1_open),
        
        # 18 factors
        'dev_10d': dev_10d,
        'headroom_10d': headroom_10d,
        'dev_30d': dev_30d,
        'headroom_30d': headroom_30d,
        'tight_headroom': tight_headroom,
        'past15_max_dev10': past15_max_dev10,
        'is_detour_10d': is_detour_10d,
        'is_near_30d_200': is_near_30d_200,
        'ord_abn_cnt_10d': ord_abn_cnt_10d,
        'dev_10d_slope_3d': dev_10d_slope_3d,
        'dev_30d_ratio': dev_30d_ratio,
        'days_since_last_ord_abn': days_since_last_ord_abn,
        'is_ord_abn_warning': is_ord_abn_warning,
        'is_detour_active': is_detour_active,
        'headroom_10d_pct_rank': 0.5,
        'headroom_30d_pct_rank': 0.5,
        'severe_his_has_flag': severe_his_has_flag,
        'is_severely_constrained': is_severely_constrained,
        
        # 15 factors
        'mcap': float(mcap_sig),
        'amt_yi': float(amt_sig),
        'turn_pct': float(turn_sig),
        'vol_ratio_5d': float(vol_ratio_5d),
        'clean_brk60': clean_brk60,
        'clean_brk250': clean_brk250,
        'pos_3y': pos_3y,
        'ma10_slope': ma10_slope,
        'ma20_dist': ma20_dist,
        'past20_zt_cnt': cand_past20,
        'kpl_dragon_mem_1y': kpl_dragon_mem_1y,
        'd1_open_pct': float(d1_open_pct),
        'upper_shadow_d0': upper_shadow_d0,
        'amplitude_d0': amplitude_d0,
        
        # 8 factors
        'lock_top10': float(lock_top10),
        'real_free_mcap': float(real_free_mcap),
        'real_turn': float(real_turn),
        'lock_chg_qoq': float(lock_chg_qoq),
        'is_high_lock_midcap': is_high_lock_midcap,
        'top1_ratio': float(top1_ratio),
        'top5_ratio': float(top5_ratio),
        'holder_num_chg_qoq': float(holder_num_chg_qoq),
        
        # 14 factors
        'first_seal_mins': first_seal_mins,
        'open_board_count': open_board_count,
        'seal_to_free_mcap': seal_to_free_mcap,
        'd0_tightness': d0_tightness,
        'lhb_has_top_youzi': lhb_has_top_youzi,
        'lhb_top_youzi_locked': lhb_top_youzi_locked,
        'lhb_inst_buy_cnt': lhb_inst_buy_cnt,
        'lhb_inst_net_yi': lhb_inst_net_yi,
        'lhb_quant_present': lhb_quant_present,
        'lhb_day_surf_present': lhb_day_surf_present,
        'lhb_lhasa_cnt': lhb_lhasa_cnt,
        'lhb_lhasa_buy_ratio': lhb_lhasa_buy_ratio,
        'lhb_net_buy_to_amt': lhb_net_buy_to_amt,
        'is_monday_or_post_holiday': is_monday_or_post_holiday,
        
        # Returns
        'ret_5d': ret_5d,
        'ret_10d': ret_10d,
        'ret_2stage_ma10': ret_2stage_ma10,
        'ret_smart_dev30_ma10': ret_smart_dev30_ma10,
        'hs300_ret_5d': hs300_ret_5d,
        'hs300_ret_10d': hs300_ret_10d,
        'hs300_ret_ma10': hs300_ret_ma10,
        'hs300_ret_smart': hs300_ret_smart,
        'excess_5d': excess_5d,
        'excess_10d': excess_10d,
        'excess_2stage_ma10': excess_2stage_ma10,
        'excess_smart_dev30': excess_smart_dev30,
    })

df_res = pd.DataFrame(results)

# Rank cross-sectionally
g_dt = df_res.groupby('sig_dt')
df_res['headroom_10d_pct_rank'] = g_dt['headroom_10d'].rank(pct=True).values
df_res['headroom_30d_pct_rank'] = g_dt['headroom_30d'].rank(pct=True).values

print(f"\nFinal enriched factor matrix size: {df_res.shape}")
print(f"Total rows: {len(df_res):,}, Columns: {len(df_res.columns)}")

pq_path = f"{OUT_DIR}/part1_dev_micro_55f.parquet"
df_res.to_parquet(pq_path, index=False)
print(f"Saved to: {pq_path} (size: {os.path.getsize(pq_path)/1024:.1f} KB)")
print(f"Total elapsed time: {time.time()-t0:.1f}s")

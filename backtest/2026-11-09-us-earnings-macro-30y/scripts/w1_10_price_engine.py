"""
W1_10 Price Engine: 30-Year Unified US Stock Price, Benchmark & Feature Vectorization Base
(1990-01-02 / 1995-01-01 to 2026-11-06)

Strict Rules:
- Output parquet: /tmp/us_earn_macro_bt_20261109/unified_prices_and_bench.parquet
- Cache npz: /tmp/us_earn_macro_bt_20261109/price_engine_cache.npz
- Anomaly CSV: /tmp/us_earn_macro_bt_20261109/split_spinoff_anomaly_audit.csv
- Chinese ADRs strictly excluded.
- Deduplication priority: main > extra_survivorship > fallen_angels
- Seamless SPY + GSPC total return splice from 1990 to 2026
"""

import os
import sys
import time
import json
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

t0 = time.time()
print("=" * 80)
print("[W1_10] Initializing 30-Year Unified US Price Engine & Feature Vectorization Base...")
print("=" * 80)

DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db"
TMP_XUANGU = "/tmp/us_xuangu_20261109"
OUT_DIR = "/tmp/us_earn_macro_bt_20261109"
SCRIPTS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/scripts"

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(SCRIPTS_DIR, exist_ok=True)

# -------------------------------------------------------------------------------------------------
# 1. Load Universe, Sectors, and Build Clean US Stock Ticker List (Excluding China ADRs)
# -------------------------------------------------------------------------------------------------
print("\n[Step 1/6] Loading Universe & Sector/Industry Mappings...")
univ = pd.read_csv(os.path.join(DATA_DIR, "universe.csv"))

CN_ADR_LIST = {
    'BABA', 'PDD', 'JD', 'BIDU', 'NTES', 'TCOM', 'BEKE', 'LI', 'NIO', 'XPEV',
    'YUMC', 'ZTO', 'FUTU', 'TIGR', 'BILI', 'TME', 'IQ', 'VIPS', 'EDU', 'TAL',
    'HTHT', 'BGNE', 'ONC', 'ZLAB', 'HCM', 'KC', 'WB', 'MNSO', 'ATAT', 'QFIN',
    'FINV', 'DIDI', 'BZ', 'ATHM', 'GDS', 'VNET', 'DQ', 'JKS', 'LU', 'YMM',
    'DAO', 'GOTU', 'ZH', 'DIDIY', 'LKNCY', 'TCEHY', 'BYDDY', 'RLX', 'TUYA',
    'SOHU', 'SINA', 'NOAH', 'CBPO', 'HSAI', 'ZK', 'LOT', 'DDL', 'LEGN'
}

# Tickers with explicit Chinese names
cn_name_mask = univ['name'].str.contains('China|Hong Kong|Macau|Beijing|Shanghai|Shenzhen|Cayman', case=False, na=False)
cn_detected = set(univ[univ['ticker'].isin(CN_ADR_LIST) | cn_name_mask]['ticker'].tolist()) | CN_ADR_LIST
print(f"  Explicit Chinese ADR / CN-domiciled filter: {len(cn_detected)} tickers flagged for exclusion.")

# Sector mapping dict from universe
univ_clean = univ[~univ['ticker'].isin(cn_detected)].copy()
sector_map = dict(zip(univ_clean['ticker'], univ_clean['sector'].fillna('Unknown_or_Historical')))
industry_map = dict(zip(univ_clean['ticker'], univ_clean['industry'].fillna('Unknown_or_Historical')))

# Manual fallback sectors for historical / fallen / delisted stocks not in universe.csv
FALLBACK_SECTORS = {
    'AIV': ('Real Estate', 'Equity Real Estate Investment Trusts (REITs)'),
    'APC': ('Energy', 'Oil & Gas Exploration & Production'),
    'BBT': ('Finance', 'Major Banks'),
    'BF-B': ('Consumer Staples', 'Beverages: Alcoholic'),
    'CAM': ('Energy', 'Oilfield Services/Equipment'),
    'DXC': ('Technology', 'IT Services: Consulting & Other Services'),
    'EMC': ('Technology', 'Computer Storage Devices'),
    'FB': ('Technology', 'Internet Content & Information'),
    'FMC': ('Basic Materials', 'Agricultural Chemicals'),
    'FOSL': ('Consumer Discretionary', 'Apparel, Footwear & Accessories'),
    'GNW': ('Finance', 'Life Insurance'),
    'GT': ('Consumer Discretionary', 'Auto Parts: OEM'),
    'HOG': ('Consumer Discretionary', 'Motorcycles'),
    'HP': ('Energy', 'Oil & Gas Drilling'),
    'KSS': ('Consumer Discretionary', 'Department Stores'),
    'MAT': ('Consumer Discretionary', 'Toys & Children\'s Products'),
    'NAVI': ('Finance', 'Consumer Finance'),
    'NBR': ('Energy', 'Oil & Gas Drilling'),
    'NWL': ('Consumer Discretionary', 'Household & Personal Products'),
    'OI': ('Basic Materials', 'Packaging & Containers'),
    'PBI': ('Industrials', 'Commercial Printing'),
    'PCL': ('Real Estate', 'Real Estate Operations'),
    'POM': ('Utilities', 'Electric Utilities: Regulated'),
    'PRGO': ('Health Care', 'Pharmaceuticals: Generic'),
    'PVH': ('Consumer Discretionary', 'Apparel, Footwear & Accessories'),
    'RHI': ('Industrials', 'Staffing & Employment Services'),
    'SPLS': ('Consumer Discretionary', 'Specialty Retail'),
    'STI': ('Finance', 'Major Banks'),
    'TDC': ('Technology', 'Computer Software: Prepackaged Software'),
    'TE': ('Utilities', 'Gas Distribution'),
    'TRIP': ('Consumer Discretionary', 'Internet Content & Information'),
    'UAA': ('Consumer Discretionary', 'Apparel, Footwear & Accessories'),
    'WHR': ('Consumer Discretionary', 'Consumer Electronics/Appliances'),
    'WU': ('Finance', 'Consumer Finance'),
    'XRAY': ('Health Care', 'Medical Devices & Equipment'),
    'XRX': ('Technology', 'Office Equipment'),
    'AAP': ('Consumer Discretionary', 'Auto Parts: Retailer'),
    'ALK': ('Industrials', 'Airlines'),
    'AMTM': ('Industrials', 'Aerospace & Defense'),
    'BBWI': ('Consumer Discretionary', 'Apparel Retail'),
    'BHF': ('Finance', 'Life Insurance'),
    'CE': ('Basic Materials', 'Chemicals: Specialty'),
    'COTY': ('Consumer Staples', 'Personal Care Products'),
    'CPRI': ('Consumer Discretionary', 'Luxury Goods'),
    'EP': ('Energy', 'Oil & Gas Midstream'),
    'FCPT': ('Real Estate', 'REITs: Commercial'),
    'GHC': ('Consumer Discretionary', 'Education & Training Services'),
    'IPGP': ('Technology', 'Semiconductors & Electronic Components'),
    'NKTR': ('Health Care', 'Biotechnology: Pharmaceutical Preparations'),
    'OGN': ('Health Care', 'Pharmaceuticals: Major'),
    'PARA': ('Consumer Discretionary', 'Broadcasting'),
    'PENN': ('Consumer Discretionary', 'Casinos & Gaming'),
    'SEDG': ('Technology', 'Solar Energy Equipment'),
    'SIG': ('Consumer Discretionary', 'Jewelry Stores'),
    'SLG': ('Real Estate', 'REITs: Office'),
    'UA': ('Consumer Discretionary', 'Apparel, Footwear & Accessories'),
    'VNT': ('Industrials', 'Electronic Equipment & Instruments'),
    'VMW': ('Technology', 'Software: Infrastructure'),
    'SIVB': ('Finance', 'Regional Banks'),
    'BBBY': ('Consumer Discretionary', 'Specialty Retail'),
    'SAVE': ('Industrials', 'Airlines'),
    'CTXS': ('Technology', 'Software: Infrastructure'),
    'CERN': ('Health Care', 'Health Information Services'),
    'XLNX': ('Technology', 'Semiconductors'),
    'RHT': ('Technology', 'Software: Infrastructure'),
    'TIF': ('Consumer Discretionary', 'Luxury Goods'),
    'MON': ('Basic Materials', 'Agricultural Chemicals'),
    'RTN': ('Industrials', 'Aerospace & Defense'),
    'KSU': ('Industrials', 'Railroads'),
    'INFO': ('Industrials', 'Information Services'),
    'VAR': ('Health Care', 'Medical Instruments'),
    'PBCT': ('Finance', 'Regional Banks'),
    'JNPR': ('Technology', 'Networking Equipment'),
    'HES': ('Energy', 'Oil & Gas E&P'),
    'MRO': ('Energy', 'Oil & Gas E&P'),
    'K': ('Consumer Staples', 'Packaged Foods'),
    'WRK': ('Basic Materials', 'Packaging & Containers'),
    'CTLT': ('Health Care', 'Pharmaceutical Contract Manufacturing'),
}

for tk, (sec, ind) in FALLBACK_SECTORS.items():
    if tk not in sector_map or sector_map[tk] in ('Unknown_or_Historical', '未分类', ''):
        sector_map[tk] = sec
        industry_map[tk] = ind

# -------------------------------------------------------------------------------------------------
# 2. Build Seamless Benchmark (SPY + GSPC Splice) and 11 SPDR Sector Benchmarks
# -------------------------------------------------------------------------------------------------
print("\n[Step 2/6] Building Master Trading Calendar & Spliced SPY+GSPC Total Return Benchmark...")
gspc_df = pd.read_parquet(os.path.join(DATA_DIR, "benchmarks/GSPC.parquet"))
spy_df = pd.read_parquet(os.path.join(DATA_DIR, "benchmarks/SPY.parquet"))

gspc_df.index = pd.to_datetime(gspc_df.index).tz_localize(None).normalize()
spy_df.index = pd.to_datetime(spy_df.index).tz_localize(None).normalize()

gspc_df = gspc_df[~gspc_df.index.duplicated(keep='last')].sort_index()
spy_df = spy_df[~spy_df.index.duplicated(keep='last')].sort_index()

# Calendar dates from 1990-01-02 to 2026-11-06
cal_dates = gspc_df.index
n_cal_days = len(cal_dates)
date_to_idx = pd.Series(np.arange(n_cal_days), index=cal_dates)

# Splice SPY (from 1993-01-29) backwards with GSPC daily returns
spy_adj = spy_df['adj_close'].reindex(cal_dates)
gspc_adj = gspc_df['adj_close'].reindex(cal_dates)

spy_start_dt = spy_df.index.min() # 1993-01-29
spy_start_idx = date_to_idx.loc[spy_start_dt]
scale_factor = spy_adj.iloc[spy_start_idx] / gspc_adj.iloc[spy_start_idx]

spy_tr_series = spy_adj.copy()
spy_tr_series.iloc[:spy_start_idx] = gspc_adj.iloc[:spy_start_idx] * scale_factor
spy_tr_series = spy_tr_series.ffill().bfill()
spy_daily_ret = spy_tr_series.pct_change().fillna(0.0)

print(f"  Calendar trading days: {n_cal_days} ({cal_dates.min().strftime('%Y-%m-%d')} to {cal_dates.max().strftime('%Y-%m-%d')})")
print(f"  SPY start: {spy_start_dt.strftime('%Y-%m-%d')} | Splice scale factor: {scale_factor:.6f}")

# SPDR 11 Sectors
SPDR_SECTORS = ['XLB', 'XLC', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLRE', 'XLU', 'XLV', 'XLY']
sector_px_matrix = np.full((n_cal_days, len(SPDR_SECTORS)), np.nan, dtype=np.float32)

for s_idx, sec_tk in enumerate(SPDR_SECTORS):
    sec_path = os.path.join(DATA_DIR, f"sectors/{sec_tk}.parquet")
    if os.path.exists(sec_path):
        sec_df = pd.read_parquet(sec_path)
        sec_df.index = pd.to_datetime(sec_df.index).tz_localize(None).normalize()
        sec_re = sec_df['adj_close'].reindex(cal_dates)
        sector_px_matrix[:, s_idx] = sec_re.values

# -------------------------------------------------------------------------------------------------
# 3. Load & Deduplicate Daily Price Sources (Priority: Main > Extra > Fallen Angels)
# -------------------------------------------------------------------------------------------------
print("\n[Step 3/6] Merging Price Sources (Main > Extra Survivorship > Fallen Angels)...")
# A. Main Library
df_main = pd.read_parquet(os.path.join(DATA_DIR, "all_daily.parquet"))
df_main['date'] = pd.to_datetime(df_main['date']).dt.tz_localize(None).dt.normalize()
df_main = df_main[~df_main['ticker'].isin(cn_detected)].copy()
df_main['data_source'] = 'main'

main_tickers = set(df_main['ticker'].unique())
print(f"  Main library rows: {len(df_main):,} | Clean US tickers: {len(main_tickers)}")

# B. Extra Survivorship
extra_pq = os.path.join(TMP_XUANGU, "w1_a3/extra_survivorship_daily.parquet")
df_extra = pd.read_parquet(extra_pq)
df_extra['date'] = pd.to_datetime(df_extra['date']).dt.tz_localize(None).dt.normalize()
df_extra = df_extra[~df_extra['ticker'].isin(cn_detected)].copy()
df_extra['data_source'] = 'extra_survivor'

# Deduplicate tickers against main
extra_new_tickers = set(df_extra['ticker'].unique()) - main_tickers
df_extra_clean = df_extra[df_extra['ticker'].isin(extra_new_tickers)].copy()
print(f"  Extra survivorship rows: {len(df_extra_clean):,} | Tickers added: {len(extra_new_tickers)}")

# C. Fallen Angels (47 tickers)
fallen_pq = os.path.join(TMP_XUANGU, "w1_a1/sp500_fallen_angels.parquet")
df_fallen = pd.read_parquet(fallen_pq)
df_fallen['date'] = pd.to_datetime(df_fallen['date']).dt.tz_localize(None).dt.normalize()
df_fallen = df_fallen[~df_fallen['ticker'].isin(cn_detected)].copy()
df_fallen['data_source'] = 'fallen_angel'

for col in ['open', 'high', 'low', 'volume']:
    df_fallen[col] = np.nan

# Deduplication priority:
# 1) If ticker is already in main -> drop from fallen
# 2) If ticker is in extra_clean -> fallen provides earlier dates (< 2005) where extra is missing!
fallen_raw_tickers = set(df_fallen['ticker'].unique()) - main_tickers
fallen_rows = []

extra_tk_min_date = df_extra_clean.groupby('ticker')['date'].min().to_dict()

for tk in fallen_raw_tickers:
    sub_f = df_fallen[df_fallen['ticker'] == tk]
    if tk in extra_tk_min_date:
        # Augment pre-2005 historical depth
        min_dt = extra_tk_min_date[tk]
        sub_pre = sub_f[sub_f['date'] < min_dt].copy()
        if len(sub_pre) > 0:
            fallen_rows.append(sub_pre)
    else:
        # Ticker completely new from fallen angels
        fallen_rows.append(sub_f)

if fallen_rows:
    df_fallen_clean = pd.concat(fallen_rows, ignore_index=True)
else:
    df_fallen_clean = pd.DataFrame(columns=df_fallen.columns)

print(f"  Fallen Angels rows added (historical + new tickers): {len(df_fallen_clean):,}")

# Combine all daily records
align_cols = ['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'volume', 'data_source']
df_all = pd.concat([
    df_main[align_cols],
    df_extra_clean[align_cols],
    df_fallen_clean[align_cols]
], ignore_index=True)

# Add sector and industry
df_all['sector'] = df_all['ticker'].map(sector_map).fillna('Unknown_or_Historical')
df_all['industry'] = df_all['ticker'].map(industry_map).fillna('Unknown_or_Historical')

# Filter to valid calendar trading days
df_all = df_all[df_all['date'].isin(date_to_idx.index)].copy()

# Attach seamless benchmark price and return
df_all['spy_adj_close'] = df_all['date'].map(spy_tr_series).astype(np.float32)
df_all['spy_ret'] = df_all['date'].map(spy_daily_ret).astype(np.float32)

all_unique_tickers = sorted(df_all['ticker'].unique().tolist())
n_stocks = len(all_unique_tickers)
print(f"  Total unified rows: {len(df_all):,} | Total clean US stocks: {n_stocks}")

# -------------------------------------------------------------------------------------------------
# 4. Split / Spinoff / Reverse-Split Anomaly Audit & Segment Break Tracking
# -------------------------------------------------------------------------------------------------
print("\n[Step 4/6] Auditing Unadjusted Discontinuities (>+400% / <-85% or Manifest 10)...")

# Known manifest 10 dates + verified reverse-split/shell discontinuities
MANIFEST_10 = [
    ('BCE', '2000-05-09', 'Nortel spin-off unadjusted in close (adj correct)'),
    ('EXPE', '2011-12-21', 'TripAdvisor spin-off residual jump in adj_close'),
    ('HST', '1993-10-12', 'Host Marriott spin-off unadjusted in close (adj correct)'),
    ('HUM', '1993-03-08', 'Galen Health spin-off unadjusted in close (adj correct)'),
    ('JCI', '2007-07-02', '3:1 split unadjusted residual jump in adj_close'),
    ('KDP', '2018-07-10', 'Special dividend $103.75 unadjusted in close (adj correct)'),
    ('LEN', '1997-11-03', 'LNR Property spin-off unadjusted in close (adj correct)'),
    ('MO', '2008-03-31', 'Philip Morris Int spin-off unadjusted in close (adj correct)'),
    ('ROK', '2001-07-02', 'Rockwell Collins spin-off unadjusted in close (adj correct)'),
    ('WY', '2010-07-20', 'REIT conversion special dividend unadjusted in close (adj correct)')
]

df_sorted = df_all.sort_values(['ticker', 'date']).reset_index(drop=True)
df_sorted['ret_adj'] = df_sorted.groupby('ticker')['adj_close'].pct_change()
df_sorted['ret_cls'] = df_sorted.groupby('ticker')['close'].pct_change()

# Detect extreme jumps
extreme_mask = (df_sorted['ret_adj'] > 4.0) | (df_sorted['ret_adj'] < -0.85)
df_extreme = df_sorted[extreme_mask].copy()

audit_rows = []
for tk, dt_str, desc in MANIFEST_10:
    m_sub = df_sorted[(df_sorted['ticker'] == tk) & (df_sorted['date'] == dt_str)]
    if len(m_sub) > 0:
        r = m_sub.iloc[0]
        audit_rows.append({
            'ticker': tk, 'date': dt_str, 'anomaly_type': 'manifest_10_spinoff_split',
            'ret_cls': float(r['ret_cls']), 'ret_adj': float(r['ret_adj']),
            'close': float(r['close']), 'adj_close': float(r['adj_close']),
            'description': desc
        })

for _, r in df_extreme.iterrows():
    tk = r['ticker']
    dt_str = r['date'].strftime('%Y-%m-%d')
    # Avoid duplicate with manifest 10
    if not any(x['ticker'] == tk and x['date'] == dt_str for x in audit_rows):
        audit_rows.append({
            'ticker': tk, 'date': dt_str, 'anomaly_type': 'extreme_jump_discontinuity',
            'ret_cls': float(r['ret_cls']), 'ret_adj': float(r['ret_adj']),
            'close': float(r['close']), 'adj_close': float(r['adj_close']),
            'description': f"1-day return jump: adj={r['ret_adj']:.2%}, close={r['ret_cls']:.2%}"
        })

df_audit = pd.DataFrame(audit_rows)
audit_path_tmp = os.path.join(OUT_DIR, "split_spinoff_anomaly_audit.csv")
audit_path_scripts = os.path.join(SCRIPTS_DIR, "split_spinoff_anomaly_audit.csv")
df_audit.to_csv(audit_path_tmp, index=False)
df_audit.to_csv(audit_path_scripts, index=False)
print(f"  Anomaly audit records written: {len(df_audit)} entries -> {audit_path_tmp}")

# Build anomaly break indicator array
tk_to_col = {tk: i for i, tk in enumerate(all_unique_tickers)}
seg_breaks = np.zeros((n_cal_days, n_stocks), dtype=np.uint8)

for _, r in df_audit.iterrows():
    tk = r['ticker']
    if tk in tk_to_col:
        c = tk_to_col[tk]
        dt = pd.Timestamp(r['date'])
        if dt in date_to_idx:
            idx = date_to_idx.loc[dt]
            # Flag days within +/- 5 trading days around break as contaminated
            idx_start = max(0, idx - 5)
            idx_end = min(n_cal_days, idx + 6)
            seg_breaks[idx_start:idx_end, c] = 1

# -------------------------------------------------------------------------------------------------
# 5. Save Master Unified Parquet to /tmp/us_earn_macro_bt_20261109/unified_prices_and_bench.parquet
# -------------------------------------------------------------------------------------------------
print("\n[Step 5/6] Writing Unified Parquet Base...")
out_parquet_path = os.path.join(OUT_DIR, "unified_prices_and_bench.parquet")

# Cast types for compact storage
df_all['open'] = df_all['open'].astype(np.float32)
df_all['high'] = df_all['high'].astype(np.float32)
df_all['low'] = df_all['low'].astype(np.float32)
df_all['close'] = df_all['close'].astype(np.float32)
df_all['adj_close'] = df_all['adj_close'].astype(np.float32)
df_all['volume'] = df_all['volume'].astype(np.float32)

table = pa.Table.from_pandas(df_all)
pq.write_table(table, out_parquet_path, compression='snappy')
pq_size_mb = os.path.getsize(out_parquet_path) / (1024 * 1024)
print(f"  Saved unified parquet: {out_parquet_path} ({pq_size_mb:.1f} MB, {len(df_all):,} rows)")

# -------------------------------------------------------------------------------------------------
# 6. Precompute 2D Vectorized Feature Matrices & Cache for Instant Event Lookup
# -------------------------------------------------------------------------------------------------
print("\n[Step 6/6] Precomputing Vectorized 2D Feature Matrices (8000 days x 1427 stocks)...")

# Populate 2D aligned price grid
day_idx_arr = date_to_idx.loc[df_all['date']].values
col_idx_arr = df_all['ticker'].map(tk_to_col).values

P_adj = np.full((n_cal_days, n_stocks), np.nan, dtype=np.float32)
P_cls = np.full((n_cal_days, n_stocks), np.nan, dtype=np.float32)
VOL = np.full((n_cal_days, n_stocks), np.nan, dtype=np.float32)

P_adj[day_idx_arr, col_idx_arr] = df_all['adj_close'].values
P_cls[day_idx_arr, col_idx_arr] = df_all['close'].values
VOL[day_idx_arr, col_idx_arr] = df_all['volume'].values

# Forward fill up to 5 trading days for isolated missing calendar days (e.g. holiday/maintenance)
# between first and last valid price of each stock
last_valid_idx = np.full(n_stocks, -1, dtype=np.int32)
first_valid_idx = np.full(n_stocks, -1, dtype=np.int32)

for c in range(n_stocks):
    valid_mask = ~np.isnan(P_adj[:, c])
    if np.any(valid_mask):
        indices = np.where(valid_mask)[0]
        first_valid_idx[c] = indices[0]
        last_valid_idx[c] = indices[-1]

P_adj_df = pd.DataFrame(P_adj)
P_adj = P_adj_df.ffill(limit=5).values
del P_adj_df

# Guard zero / negative prices
P_adj[P_adj <= 0] = np.nan

# A. Past Returns Matrix: pre_ret_21d, 63d, 126d, 252d, 504d, 756d, 1260d
HORIZONS = [21, 63, 126, 252, 504, 756, 1260]
PRE_RETS = {}
for h in HORIZONS:
    ret_mat = np.full((n_cal_days, n_stocks), np.nan, dtype=np.float32)
    ret_mat[h:, :] = P_adj[h:, :] / P_adj[:-h, :] - 1.0
    PRE_RETS[h] = ret_mat

# B. Monthly Positive Windows: pos_21d_win_12m (12 windows) & pos_21d_win_24m (24 windows)
print("  Computing pos_21d_win_12m and pos_21d_win_24m...")
POS_12M = np.zeros((n_cal_days, n_stocks), dtype=np.float32)
for k in range(1, 13):
    start_lag = (k - 1) * 21
    end_lag = k * 21
    ret_k = P_adj[end_lag:, :] / P_adj[:-end_lag, :] - 1.0 if start_lag == 0 else \
            P_adj[end_lag - start_lag : n_cal_days - start_lag, :] / P_adj[:-end_lag, :] - 1.0
    POS_12M[end_lag:, :] += (ret_k > 0).astype(np.float32)

POS_12M[:252, :] = np.nan
POS_12M /= 12.0

POS_24M = np.zeros((n_cal_days, n_stocks), dtype=np.float32)
for k in range(1, 25):
    start_lag = (k - 1) * 21
    end_lag = k * 21
    ret_k = P_adj[end_lag:, :] / P_adj[:-end_lag, :] - 1.0 if start_lag == 0 else \
            P_adj[end_lag - start_lag : n_cal_days - start_lag, :] / P_adj[:-end_lag, :] - 1.0
    POS_24M[end_lag:, :] += (ret_k > 0).astype(np.float32)

POS_24M[:504, :] = np.nan
POS_24M /= 24.0

# C. Rolling Max, Min, Drawdown, Volatility, MAs
print("  Computing rolling extremes, drawdowns, and technical tags...")
P_df = pd.DataFrame(P_adj)

ROLL_MAX_252 = P_df.rolling(252, min_periods=21).max().values.astype(np.float32)
ROLL_MIN_126 = P_df.rolling(126, min_periods=21).min().values.astype(np.float32)
ROLL_MAX_126 = P_df.rolling(126, min_periods=21).max().values.astype(np.float32)
ROLL_MAX_504 = P_df.rolling(504, min_periods=42).max().values.astype(np.float32)

# Distance to high
DIST_52W_HIGH = (P_adj / ROLL_MAX_252 - 1.0).astype(np.float32)
DIST_2Y_HIGH = (P_adj / ROLL_MAX_504 - 1.0).astype(np.float32)

# Max Drawdown past 252d and past 126d
dd_curr_252 = P_df / ROLL_MAX_252 - 1.0
MAX_DD_252 = dd_curr_252.rolling(252, min_periods=21).min().values.astype(np.float32)

dd_curr_126 = P_df / ROLL_MIN_126 - 1.0 # wait: dd is from max
dd_curr_126_proper = P_df / ROLL_MAX_126 - 1.0
MAX_DD_126 = dd_curr_126_proper.rolling(126, min_periods=21).min().values.astype(np.float32)

# Realized Volatility 252d (annualized)
ret_1d_df = P_df.pct_change()
REALIZED_VOL_252 = (ret_1d_df.rolling(252, min_periods=63).std() * np.sqrt(252)).values.astype(np.float32)

# Moving Averages: MA50 and MA200
MA50 = P_df.rolling(50, min_periods=25).mean().values.astype(np.float32)
MA200 = P_df.rolling(200, min_periods=100).mean().values.astype(np.float32)
MA50_ABOVE_MA200 = (MA50 > MA200).astype(np.uint8)

# 6-State Slow Uptrend Tag Classification:
# 1: SlowUp_2to5Y
# 2: SlowUp_6Mto2Y
# 3: TightBase_6M
# 4: HighFlyer_Parabolic
# 5: DeepDrawdown_Left
# 0: Other_Neutral
print("  Vectorizing 6-State Slow Uptrend Regime Classification...")

# Condition 1: SlowUp_2to5Y
cond_1 = (
    ((PRE_RETS[504] > 0.40) | (PRE_RETS[756] > 0.40)) &
    (REALIZED_VOL_252 < 0.38) &
    (MAX_DD_252 > -0.25) &
    (DIST_52W_HIGH > -0.15)
)

# Condition 2: SlowUp_6Mto2Y
cond_2 = (
    ~cond_1 &
    (((PRE_RETS[126] >= 0.15) & (PRE_RETS[126] <= 0.80)) | ((PRE_RETS[252] >= 0.15) & (PRE_RETS[252] <= 0.80))) &
    (MAX_DD_126 > -0.20) &
    (MA50_ABOVE_MA200 == 1)
)

# Condition 4: HighFlyer_Parabolic
cond_4 = (PRE_RETS[126] > 0.80) | (REALIZED_VOL_252 > 0.65) | (PRE_RETS[63] > 0.50)

# Condition 3: TightBase_6M
amp_126 = ROLL_MAX_126 / np.where(ROLL_MIN_126 > 0, ROLL_MIN_126, np.nan) - 1.0
cond_3 = amp_126 < 0.28

# Condition 5: DeepDrawdown_Left
cond_5 = (DIST_52W_HIGH <= -0.35) | (DIST_2Y_HIGH <= -0.35)

SLOW_TAG = np.zeros((n_cal_days, n_stocks), dtype=np.int8)
# Priority assignment
SLOW_TAG[cond_5] = 5
SLOW_TAG[cond_3] = 3
SLOW_TAG[cond_4] = 4
SLOW_TAG[cond_2] = 2
SLOW_TAG[cond_1] = 1

# Delisted / Exit Metadata Lookup
exit_types = []
terminal_rets = []

# Known bankruptcies from project research
KNOWN_BANKRUPT = {
    'SIVB', 'BBBY', 'SAVE', 'ENDP', 'MNK', 'FTR_PRE', 'RAD', 'CHK_PRE',
    'HTZ_PRE', 'JCP', 'TUP', 'NVTA', 'VVUS'
}

for tk in all_unique_tickers:
    c = tk_to_col[tk]
    l_idx = last_valid_idx[c]
    if l_idx < n_cal_days - 15: # Ceased trading before 2026-10-15
        if tk in KNOWN_BANKRUPT:
            exit_types.append('bankrupt')
            terminal_rets.append(-0.95)
        else:
            exit_types.append('ma')
            terminal_rets.append(0.0)
    else:
        exit_types.append('active')
        terminal_rets.append(0.0)

exit_types = np.array(exit_types)
terminal_rets = np.array(terminal_rets, dtype=np.float32)

# Save Precomputed Cache NPZ
cache_file = os.path.join(OUT_DIR, "price_engine_cache.npz")
print(f"  Saving feature cache -> {cache_file}...")

np.savez_compressed(
    cache_file,
    dates=cal_dates.values.astype('datetime64[D]'),
    tickers=np.array(all_unique_tickers),
    P_adj=P_adj,
    P_cls=P_cls,
    VOL=VOL,
    spy_tr=spy_tr_series.values.astype(np.float32),
    spy_ret=spy_daily_ret.values.astype(np.float32),
    sector_px=sector_px_matrix,
    pre_ret_21d=PRE_RETS[21],
    pre_ret_63d=PRE_RETS[63],
    pre_ret_126d=PRE_RETS[126],
    pre_ret_252d=PRE_RETS[252],
    pre_ret_504d=PRE_RETS[504],
    pre_ret_756d=PRE_RETS[756],
    pre_ret_1260d=PRE_RETS[1260],
    pos_21d_win_12m=POS_12M,
    pos_21d_win_24m=POS_24M,
    max_dd_252d=MAX_DD_252,
    max_dd_126d=MAX_DD_126,
    realized_vol_252d=REALIZED_VOL_252,
    dist_52w_high=DIST_52W_HIGH,
    dist_2y_high=DIST_2Y_HIGH,
    ma50_above_ma200=MA50_ABOVE_MA200,
    slow_tag=SLOW_TAG,
    seg_breaks=seg_breaks,
    first_valid_idx=first_valid_idx,
    last_valid_idx=last_valid_idx,
    exit_types=exit_types,
    terminal_rets=terminal_rets
)

cache_size_mb = os.path.getsize(cache_file) / (1024 * 1024)
print(f"  Feature cache saved successfully: {cache_size_mb:.1f} MB!")

t_done = time.time()
print(f"\n[W1_10] Price Engine Build Complete! Total elapsed time: {t_done - t0:.2f} seconds.")
print("=" * 80)

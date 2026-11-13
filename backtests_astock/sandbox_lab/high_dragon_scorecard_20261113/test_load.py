import sys, os, time, pickle, json
import pandas as pd
import numpy as np

SANDBOX = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab'
GRAND_DIR = f'{SANDBOX}/grand_factor_matrix_20261112'
sys.path.insert(0, GRAND_DIR)
from d15_eval_helper import _sim_single_slot, _sim_daily_eq, evaluate_d15_full, FEE_RATE

print('Loading code_bars and high_dragon parquet...')
t0 = time.time()
with open(f'{GRAND_DIR}/code_bars_5y.pkl', 'rb') as f:
    pkg = pickle.load(f)
cbs, idx_klines = pkg['code_bars'], pkg['idx_klines']
df_hd = pd.read_parquet(f'{GRAND_DIR}/cand_high_dragon.parquet')
print(f'Loaded {len(df_hd):,} cands, {len(cbs):,} stock bars in {time.time()-t0:.2f}s')
import sys, os, time, pickle, json
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
BACKTEST_CLEAN_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
BACKTEST_ASTOCK_DIR = f"{SIM_DIR}/backtests_astock"

sys.path.insert(0, "/tmp")
sys.path.insert(0, BACKTEST_CLEAN_DIR)
sys.path.insert(0, BACKTEST_ASTOCK_DIR)
sys.path.insert(0, f"{BACKTEST_ASTOCK_DIR}/_archive/20261116_pre_clean_rebacktest")

from clean_wf_1to2_v14_ironclad_master import load_full_prices, FEE_RATE
from exp1_fake_theme_purifier import build_8y_purified_theme_metadata, compute_purifier_auction_scores
from master_5y_zero_lookahead_walkforward import evaluate_strategy_master

print("1to2 Candidate Extractor starting...")
t0 = time.time()
df_daily, all_dts, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = load_full_prices()
stock_theme_5y, pioneer_word_history = build_8y_purified_theme_metadata(df_daily)
print(f"Loaded prices and themes in {time.time()-t0:.2f}s")

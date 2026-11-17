#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
test_base_calibration.py
验证三大基础策略候选提取与基准 181 笔合体总账的 100% 严格复现
"""
import os, sys, json, pickle, math
import pandas as pd
import numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
CLEAN = f"{ROOT}/sim-portfolio/backtests_astock/clean_rebacktest_20261116"

# 1. 载入既有基准总账
ledger_base = pd.read_csv(f"{CLEAN}/ledger_base_combined_3main.csv")
print(f"既有基准合体总账: {len(ledger_base)} 笔")
print(ledger_base["strategy"].value_counts().to_dict())

# 2. 检查既有三独立账本
df_h = pd.read_csv(f"{CLEAN}/partA_high_3to4/ledger_base_high_v51.csv")
df_3 = pd.read_csv(f"{CLEAN}/partA_high_3to4/ledger_base_3to4_v34.csv")
df_1 = pd.read_csv(f"{CLEAN}/partB_1to2/ledger_base_1to2_v18.csv")
print(f"既有三策略独立账本: 高标={len(df_h)}, 三进四={len(df_3)}, 一进二={len(df_1)}")

# 3. 运行 synthesize_master_clean_20261116 的合体逻辑
from synthesize_master_clean_20261116 import standardize_ledger, run_1slot
b_h = standardize_ledger(f"{CLEAN}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴_V51", 1)
b_3 = standardize_ledger(f"{CLEAN}/partA_high_3to4/ledger_base_3to4_v34.csv", "三进四_V34", 2)
b_1 = standardize_ledger(f"{CLEAN}/partB_1to2/ledger_base_1to2_v18.csv", "一进二_V18", 3)

pool = pd.concat([b_h, b_3, b_1], ignore_index=True)
slot = run_1slot(pool)
print(f"重新跑 1slot 合体: {len(slot)} 笔")
assert len(slot) == len(ledger_base), f"笔数不符: {len(slot)} vs {len(ledger_base)}"
diff_rets = np.abs(slot["net_ret"].values - ledger_base["net_ret"].values).max()
print(f"与基准总账最大收益误差: {diff_rets:.8f}")
assert diff_rets < 1e-6, "合体收益率未 100% 对齐!"
print("✅ 合体机制 100% 复现核对成功！")

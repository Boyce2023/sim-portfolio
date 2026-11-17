#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import glob, os, pickle, pandas as pd, numpy as np

ROOT = "/Users/huaichuaibeimeng/claude-projects"
HD_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
MAT = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"

files = sorted(glob.glob(f"{HD_DIR}/*"), key=os.path.getmtime)
print("HD_DIR latest files:", [os.path.basename(f) for f in files[-12:]])
csvs = sorted(glob.glob(f"{HD_DIR}/*.csv") + glob.glob(f"{ROOT}/sim-portfolio/backtests_astock/*high*.csv"))
print("High dragon CSVs:", [os.path.basename(f) for f in csvs])

# Read latest V5 script or ledger if exists
v5_py = [f for f in files if "v5" in f.lower() or "22" in f.lower() or "scheme" in f.lower() or f.endswith(".py")]
print("Recent py in HD_DIR:", [os.path.basename(f) for f in v5_py[-8:]])

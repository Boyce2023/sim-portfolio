#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
p2_test_step1.py: Build unified 5m lookup and verify M1, M2, M3 simulation on Pool A, B, C, D.
"""
import os, sys, time, json, pickle, sqlite3
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SANDBOX = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab"
MATRIX = f"{SANDBOX}/grand_factor_matrix_20261112"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p4_pry_board"
FEE_RATE = 0.0020

print("[+] Loading code_bars_5y.pkl...")
t0 = time.time()
with open(f"{MATRIX}/code_bars_5y.pkl", "rb") as f:
    cb_data = pickle.load(f)
cb = cb_data["code_bars"]
all_dts = cb_data["all_dts"]
print(f"Loaded {len(cb)} codes in {time.time()-t0:.2f}s")

# Load ST codes
with open(f"{ROOT}/sim-portfolio/data/st_universe.json") as f:
    st_codes = set(json.load(f).get("codes", []))
csrc_df = pd.read_csv(f"{ROOT}/sim-portfolio/data/csrc_industry_l2.csv")
csrc_df["c6"] = csrc_df["code"].astype(str).str[-6:]
st_names = set(csrc_df[csrc_df["code_name"].str.contains("ST|退", case=False, na=False)]["c6"])
all_st_codes = st_codes | st_names

# Load CSI300 benchmark map
with open(f"{SANDBOX}/index_klines_5y_cache.json", "r") as f:
    csi_map = json.load(f)["sh000300"]
csi_dts = sorted(csi_map.keys())

def csi_ret(d_start, d_end):
    d_list = [d for d in csi_dts if d_start <= d <= d_end]
    if len(d_list) < 2: return 0.0
    p0 = max(0, csi_dts.index(d_list[0]) - 1)
    return float(csi_map[d_list[-1]] / csi_map[csi_dts[p0]] - 1.0)

csi_bench_5y = csi_ret("2022-01-04", "2026-11-10")

print(f"ST codes: {len(all_st_codes)}, CSI300 5y: {csi_bench_5y*100:.2f}%")

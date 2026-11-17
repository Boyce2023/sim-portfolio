#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import os, sys, glob, json, numpy as np, pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path: sys.path.insert(0, CUR_DIR)
ROOT = "/Users/huaichuaibeimeng/claude-projects"

# Check kpl_plates_2018_2026_merged.jsonl exact keys
kpl_files = glob.glob(f"{ROOT}/sim-portfolio/**/kpl_plates_2018_2026_merged.jsonl", recursive=True)
print("kpl_files:", kpl_files)
if kpl_files:
    with open(kpl_files[0], "r", encoding="utf-8") as f:
        for _ in range(2): print("sample kpl:", f.readline().strip()[:180])

# Test combining ONLY the 4 verified true upgrades from astock's 9 items:
# Gem 1: 首次断板真阳免死一次 (3b: PO 2.03 -> 2.29, 24-26 PO 2.48 -> 2.87, 5Y NAV 38.86x -> 55.16x!)
# Gem 2: D4未封板弱斩强留博反包 (2: cut_weak, PO 1.52 -> 1.79 on 90f, 2.03 -> 2.32 on 98f, MDD -4%!)
# Gem 3: 上塘路/佛山/消闲派/苏南帮一日游砸盘席位扣分/拦截 (8c: 5Y WR -20.0%, 24-26 WR -22.3%, Mean -6.30%!!)
# Gem 4: 同日三板竞价第一名强排他 + 八年题材热度 p_elo >= 115 加分 (6a & 6b: 24-26 Mean +3.83% & +4.15%!)
from audit_astock_9items_on_3to4 import df, skel, sc_v31, sim_pool_custom, eval_pool

p_2gems_exit = sim_pool_custom(use_dev93=False, d4_mode="cut_weak", hold_mode="pm1345", use_yang_imm=True)
sc_v32 = sc_v31.copy()
sc_v32 += np.where(df["surf_yz_buy"], -12.0, 0.0)        # 一日游砸盘席位重扣12分
sc_v32 += np.where(df["p_elo"] >= 115.0, 5.0, 0.0)       # 八年动态题材高热度加5分
sc_v32_top1 = np.where(df["is_top1_3b_open"], sc_v32, -999.0)  # 同日三板竞价头名强排他

print("\n=== 只采纳实测真有效的 4 项精华 vs 现版基准 ===")
for th in [78, 90, 98]:
    print(f"\n--- 门槛 >= {th} 分 ---")
    eval_pool(f"A.三进四现版 V3.1>={th}", sc_v31 >= th, sim_pool_custom(False, "reb2", "pm1345", False), sc_v31)
    eval_pool(f"B.仅升级2项卖点(弱斩强留+真阳免死)", sc_v31 >= th, p_2gems_exit, sc_v31)
    eval_pool(f"C.升级2卖点+一日游席位+题材热度", sc_v32 >= th, p_2gems_exit, sc_v32)
    eval_pool(f"D.升级2卖点+一日游+热度+头名强排他", sc_v32_top1 >= th, p_2gems_exit, sc_v32_top1)

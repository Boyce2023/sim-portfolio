#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step2_diagnose_is_trades.py
只读诊断：统计 V4.0 baseline (std90 & strict102) 在 IS(2022-2023) 和 全周期中
各卖出分支的真实触发分布，检查基础物理特征。
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_opt_20261118/s1_3to4_exit"
CACHE_PKL = f"{OUT_DIR}/cache_3to4_exit.pkl"
UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, UPG_DIR)
import upgrade_3to4_pit as u34


def classify_baseline_trade(entry, cb, bars_5m_map):
    c6 = entry["code"]
    pos = entry["pos"]
    n = len(cb["dts"])
    orig = entry["orig_p1030"]
    d4_sealed = bool(cb["is_zt"][pos])
    o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])

    branch = ""
    max_streak = 4 if d4_sealed else 3
    if not d4_sealed:
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        k = min(k, n - 1)
        if k > pos + 1:
            branch = "A_yizi_dt_delay"
        else:
            o5, p5 = float(cb["open"][k]), float(cb["pre_c"][k])
            if not ((c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)):
                branch = "A_d5_open_cut"
            elif bool(cb["is_zt"][k]):
                branch = "A_d5_rebound_zt"
            else:
                branch = "A_d5_hold_eod"
    else:
        if orig["exit_hhmm"] == 925:
            branch = "B_yizi_dt_delay"
        elif orig["exit_hhmm"] == 1500:
            branch = "D_eod_break"
        else:
            branch = "C_pm1345_5m"

    # 统计实际持仓期间达到最高连板与是否触及双异动
    ex_pos = cb["date_to_pos"].get(orig["exit_date"], pos + 1)
    for p in range(pos, ex_pos + 1):
        if p > pos and bool(cb["is_zt"][p]):
            max_streak += 1
    return {
        "code": c6,
        "name": entry["name"],
        "buy_date": entry["buy_date"],
        "exit_date": orig["exit_date"],
        "exit_hhmm": orig["exit_hhmm"],
        "net_ret": orig["net_ret"],
        "d4_sealed": d4_sealed,
        "branch": branch,
        "hold_days": ex_pos - pos,
        "max_streak": max_streak,
        "is_IS": entry["buy_date"] <= "2023-12-31",
        "score": int(round(entry["sc_v40"])),
    }


def main():
    with open(CACHE_PKL, "rb") as f:
        cache = pickle.load(f)
    code_bars = cache["code_bars_ext"]
    bars_5m_map = cache["bars_5m_map"]

    # 提取 std90 raw & slot
    recs = []
    for e in cache["buy_entries"]:
        if e["skel"] and e["sc_v40"] >= 90.0 and e["orig_p1030"] is not None:
            rec = dict(e["orig_p1030"])
            rec["score"] = int(round(e["sc_v40"]))
            rec["priority_score"] = e["priority_score"]
            rec["entry_ref"] = e
            recs.append(rec)
    raw_df = pd.DataFrame(recs)
    slot_df = u34.sim_single_slot(raw_df)

    diag_rows = []
    for r in slot_df.itertuples(index=False):
        e = next(x for x in cache["buy_entries"] if x["code"] == r.code and x["buy_date"] == r.buy_date)
        diag_rows.append(classify_baseline_trade(e, code_bars[r.code], bars_5m_map))
    ddf = pd.DataFrame(diag_rows)

    for scope, sub in [("ALL_95", ddf), ("IS_22_23", ddf[ddf["is_IS"]]), ("OOS_24_26", ddf[~ddf["is_IS"]])]:
        print(f"\n=== {scope} (N={len(sub)}, WR={(sub['net_ret']>0).mean()*100:.1f}%, Mean={sub['net_ret'].mean()*100:.2f}%) ===")
        grp = sub.groupby("branch").agg(
            n=("net_ret", "count"),
            wr=("net_ret", lambda s: (s > 0).mean() * 100),
            mean_pct=("net_ret", lambda s: s.mean() * 100),
            med_pct=("net_ret", lambda s: s.median() * 100),
            min_pct=("net_ret", lambda s: s.min() * 100),
            max_pct=("net_ret", lambda s: s.max() * 100),
        )
        print(grp.to_string())
        print("D4 sealed count:", int(sub["d4_sealed"].sum()), "/ unsealed:", int((~sub["d4_sealed"]).sum()))
        print("Max streak dist:", sub["max_streak"].value_counts().sort_index().to_dict())

    # 额外查验：raw_df (115笔) 中在 IS (2022-2023) 的分布
    diag_raw = []
    for r in raw_df.itertuples(index=False):
        e = next(x for x in cache["buy_entries"] if x["code"] == r.code and x["buy_date"] == r.buy_date)
        diag_raw.append(classify_baseline_trade(e, code_bars[r.code], bars_5m_map))
    dr = pd.DataFrame(diag_raw)
    print(f"\n=== RAW_IS (N={len(dr[dr['is_IS']])}) ===")
    print(dr[dr["is_IS"]].groupby("branch")["net_ret"].agg(["count", lambda s: (s > 0).mean() * 100, lambda s: s.mean() * 100]))


if __name__ == "__main__":
    main()

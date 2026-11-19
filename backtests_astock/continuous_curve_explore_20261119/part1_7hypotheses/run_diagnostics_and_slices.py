#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Phase 2: 物理亏钱根因拆解 (D1盘中 vs T+1/T+2路径) + 核心自然过滤切片 + D15 全指标审计
"""

import json
import os
import numpy as np
import pandas as pd
import sys

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part1_7hypotheses"
sys.path.insert(0, OUT_DIR)
import run_7hypotheses_backtest as r7

def decompose_path_and_filters():
    df, all_mkt_dts, mkt_zt, mkt_dt, csi_above_ma20, csi300 = r7.load_data()

    # 构建 (c6, dt_str) -> (open, close, adjf) 极速查找表以拆解 D1盘中 / T+1 / T+2 收益
    c6_arr = df["c6"].to_numpy()
    dt_arr = df["dt_str"].to_numpy()
    open_arr = df["open"].to_numpy()
    close_arr = df["close"].to_numpy()
    adjf_arr = df["adjf"].to_numpy()
    is_zt_arr = df["is_zt"].to_numpy()
    ret_arr = df["ret"].to_numpy()

    idx_map = {(c6_arr[i], dt_arr[i]): i for i in range(len(df))}

    csi_5y = r7.csi_window_ret(csi300, "2021-11-15", "2026-11-18")
    csi_is = r7.csi_window_ret(csi300, "2021-11-15", "2023-12-29")
    csi_oos = r7.csi_window_ret(csi300, "2024-01-01"[:-2] + "12-29" if False else "2023-12-29", "2026-11-18")
    csi_3y = r7.csi_window_ret(csi300, "2023-11-15", "2026-11-18")
    csi_26 = r7.csi_window_ret(csi300, "2025-12-31", "2026-11-18")
    WINDOWS = [
        ("5Y", "2021-11-15", "2026-11-18", csi_5y),
        ("IS", "2021-11-15", "2023-12-29", csi_is),
        ("OOS", "2024-01-01", "2026-11-18", csi_oos),
        ("3Y", "2023-11-16", "2026-11-18", csi_3y),
        ("2026", "2026-01-01", "2026-11-18", csi_26),
    ]

    print("\n================ 1. 亏钱/赚钱物理路径拆解 (09:25买入 -> D1收盘 -> T+1收盘 -> E1离场) ================")
    for h in [f"C{i}" for i in range(1, 8)]:
        ldf = pd.read_csv(f"{OUT_DIR}/ledger_{h}_raw.csv", dtype={"c6": str})
        d1_intra = []
        d1_to_e1 = []
        sig_zt = []
        sig_ret = []
        for r in ldf.itertuples(index=False):
            bi = idx_map[(r.c6.zfill(6), r.buy_date)]
            si = idx_map[(r.c6.zfill(6), r.sig_date)]
            ei = idx_map[(r.c6.zfill(6), r.exit_date_e1)]
            b_adj = open_arr[bi] * adjf_arr[bi]
            c1_adj = close_arr[bi] * adjf_arr[bi]
            e1_adj = close_arr[ei] * adjf_arr[ei]
            d1_intra.append((c1_adj / b_adj - 1.0) * 10000.0)
            d1_to_e1.append((e1_adj / c1_adj - 1.0) * 10000.0)
            sig_zt.append(int(is_zt_arr[si]))
            sig_ret.append(float(ret_arr[si]))
        ldf["d1_intra_bps"] = d1_intra
        ldf["d1_to_e1_bps"] = d1_to_e1
        ldf["sig_is_zt"] = sig_zt
        ldf["sig_ret"] = sig_ret
        ldf.to_csv(f"{OUT_DIR}/ledger_{h}_raw.csv", index=False)

        # 按天等权求 D1盘中 vs D1尾盘至E1 贡献 (扣30bps前毛收益 vs 净收益)
        dm = ldf.groupby("buy_date")[["d1_intra_bps", "d1_to_e1_bps", "ret_e1"]].mean()
        is_m = dm[dm.index <= "2023-12-29"]
        oos_m = dm[dm.index >= "2024-01-01"]
        y26_m = dm[dm.index >= "2026-01-01"]
        print(
            f"{h}: D1盘中={dm['d1_intra_bps'].mean():+6.1f}bps (IS={is_m['d1_intra_bps'].mean():+6.1f}, OOS={oos_m['d1_intra_bps'].mean():+6.1f}, 26={y26_m['d1_intra_bps'].mean():+6.1f}) | "
            f"D1尾盘至E1={dm['d1_to_e1_bps'].mean():+6.1f}bps | 净E1={dm['ret_e1'].mean()*10000:+6.1f}bps"
        )

    print("\n================ 2. 重点假说自然过滤切片 (检查 IS / OOS / 2026 是否同向正期望) ================")
    def eval_slice(ldf, mask, label, rcol="ret_e1", ecol="exit_date_e1", rank_col="rank_score", asc=False):
        sub = ldf[mask].copy()
        if len(sub) < 20:
            return None
        # 允许自定义简单排序规则测试单仓
        sub["rank_tmp"] = sub[rank_col] if not asc else -sub[rank_col]
        df_s = sub.sort_values(["buy_date", "rank_tmp", "c6"], ascending=[True, False, True])
        picked = []
        cur_exit = ""
        for r in df_s.itertuples(index=False):
            if not cur_exit or r.buy_date > cur_exit:
                picked.append(r._asdict())
                cur_exit = getattr(r, ecol)
        slot_df = pd.DataFrame(picked)
        res = {}
        for wn, d0, d1, csi_p in WINDOWS:
            res[wn] = r7.eval_window(sub, slot_df, rcol, d0, d1, csi_p)
        # 检查 5 个自然年同向性
        yrs = {}
        for yr in ["2022", "2023", "2024", "2025", "2026"]:
            yrs[yr] = r7.eval_window(sub, slot_df, rcol, f"{yr}-01-01", f"{yr}-12-31", 0.0)["ew_bps"]
        w5, wis, woos, w3, w26 = res["5Y"], res["IS"], res["OOS"], res["3Y"], res["2026"]
        print(
            f"  [{label:<30s}] n={w5['n_all']:4d}({w5['ew_days']:3d}d) "
            f"EW_bps(5Y/IS/OOS/26)={w5['ew_bps']:+5.1f}/{wis['ew_bps']:+5.1f}/{woos['ew_bps']:+5.1f}/{w26['ew_bps']:+5.1f} (t={w5['ew_t']:+.2f}) | "
            f"1Slot(n={w5['n_slot']:3d},WR={w5['slot_wr']:4.1f}%,PLR={w5['slot_plr']:4.2f},5Y={w5['slot_nav']:4.2f}x/MDD{w5['slot_mdd']:4.1f}%,3Y={w3['slot_nav']:4.2f}x,26={w26['slot_nav']:4.2f}x) | "
            f"yrs={yrs['2022']:+.0f}/{yrs['2023']:+.0f}/{yrs['2024']:+.0f}/{yrs['2025']:+.0f}/{yrs['2026']:+.0f}"
        )
        return {"label": label, "windows": res, "years": yrs}

    slice_summary = {}

    # 逐一检验 C1~C7 关键物理切片 (只测最自然、有理论依据的 4~6 个单切片或双切片)
    for h in ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]:
        ldf = pd.read_csv(f"{OUT_DIR}/ledger_{h}_raw.csv", dtype={"c6": str})
        print(f"\n--- {h} 关键切片 ---")
        s_list = []
        # 1. 市值对比: 20-250 vs >100 vs >250
        for name, msk in [
            ("RAW_E1", np.ones(len(ldf), dtype=bool)),
            ("mcap 20~250", (ldf["mcap_yi"] >= 20) & (ldf["mcap_yi"] <= 250)),
            ("mcap >= 100", ldf["mcap_yi"] >= 100),
            ("mcap > 250", ldf["mcap_yi"] > 250),
            ("turn 3~20%", (ldf["turn_sig"] >= 0.03) & (ldf["turn_sig"] <= 0.20)),
            ("csi_ok (CSI>=MA20)", ldf["csi_ok"] == True),
            ("mkt_non_ice (zt>=30,dt<=20)", (ldf["mkt_zt"] >= 30) & (ldf["mkt_dt"] <= 20)),
            ("sig_no_zt (当日未封板)", ldf["sig_is_zt"] == 0),
            ("no_zt_10d (10日零涨停纯曲线)", ldf["had_zt_10"] == 0),
            ("mcap>=100 + csi_ok", (ldf["mcap_yi"] >= 100) & (ldf["csi_ok"] == True)),
            ("mcap>250 + csi_ok", (ldf["mcap_yi"] > 250) & (ldf["csi_ok"] == True)),
            ("mcap 20~250 + turn3~20 + nonIce", (ldf["mcap_yi"] >= 20) & (ldf["mcap_yi"] <= 250) & (ldf["turn_sig"] >= 0.03) & (ldf["turn_sig"] <= 0.20) & (ldf["mkt_zt"] >= 30) & (ldf["mkt_dt"] <= 20)),
            ("turn3~20 + csi_ok", (ldf["turn_sig"] >= 0.03) & (ldf["turn_sig"] <= 0.20) & (ldf["csi_ok"] == True)),
        ]:
            out = eval_slice(ldf, msk, name, "ret_e1", "exit_date_e1")
            if out:
                s_list.append(out)
        # 针对 E2 也检查 mcap>250, csi_ok, sig_no_zt
        for name, msk in [
            ("E2: csi_ok", ldf["csi_ok"] == True),
            ("E2: mcap > 250", ldf["mcap_yi"] > 250),
            ("E2: mcap>=100 + csi_ok", (ldf["mcap_yi"] >= 100) & (ldf["csi_ok"] == True)),
        ]:
            out = eval_slice(ldf, msk, name, "ret_e2", "exit_date_e2")
            if out:
                s_list.append(out)
        slice_summary[h] = s_list

    with open(f"{OUT_DIR}/summary_slices_7hypotheses.json", "w", encoding="utf-8") as f:
        json.dump(slice_summary, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    decompose_path_and_filters()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Phase 3: 排名机制诊断 + C2 T+1 物理验证 + C1/C4 重叠度 + 物理截断 <=2024-12-31 PIT 零穿越校验
"""
import json, os, sys
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part1_7hypotheses"
sys.path.insert(0, OUT_DIR)
import run_7hypotheses_backtest as r7

def check_ranking_and_overlap():
    print("=== 1. C1 / C4 排名因子诊断 (检查 IS vs OOS 单仓排序鲁棒性) ===")
    df, all_mkt_dts, mkt_zt, mkt_dt, csi_above_ma20, csi300 = r7.load_data()
    # 补取 sig_date 特征 (ret10_p, er10, pos60, amount) 关联到 C1/C4 ledger
    feat_map = {}
    for row in df[["c6", "dt_str", "open", "close", "adjf", "amount", "ret"]].itertuples(index=False):
        feat_map[(row.c6, row.dt_str)] = row

    for h, msk_fn, rcol, ecol in [
        ("C1 (csi_ok)", lambda d: d["csi_ok"] == True, "ret_e1", "exit_date_e1"),
        ("C1 (turn3~20+csi_ok)", lambda d: (d["turn_sig"]>=0.03)&(d["turn_sig"]<=0.20)&(d["csi_ok"]==True), "ret_e1", "exit_date_e1"),
        ("C4 (mcap>=100+csi_ok, E1)", lambda d: (d["mcap_yi"]>=100)&(d["csi_ok"]==True), "ret_e1", "exit_date_e1"),
        ("C4 (mcap>=100+csi_ok, E2)", lambda d: (d["mcap_yi"]>=100)&(d["csi_ok"]==True), "ret_e2", "exit_date_e2"),
    ]:
        base_h = h[:2]
        ldf = pd.read_csv(f"{OUT_DIR}/ledger_{base_h}_raw.csv", dtype={"c6": str})
        sub = ldf[msk_fn(ldf)].copy()
        print(f"\n[{h}] n={len(sub)}, days={sub['buy_date'].nunique()}")
        for rname, rcol_sort, asc in [
            ("default_rank", "rank_score", False),
            ("mcap_desc(大市值优先)", "mcap_yi", False),
            ("pos60_asc(低位优先)", "pos60", True),
            ("turn_asc(低换手优先)", "turn_sig", True),
            ("open_gap_desc(强高开优先)", "open_gap", False),
            ("open_gap_asc(低高开优先)", "open_gap", True),
        ]:
            s_df = sub.sort_values(["buy_date", rcol_sort, "c6"], ascending=[True, asc, True])
            picked = []
            ce = ""
            for r in s_df.itertuples(index=False):
                if not ce or r.buy_date > ce:
                    picked.append(r._asdict())
                    ce = getattr(r, ecol)
            p = pd.DataFrame(picked)
            def st(x):
                if len(x)==0: return "n=0"
                nav = np.prod(1.0 + x[rcol].to_numpy())
                wr = (x[rcol]>0).mean()*100
                return f"n={len(x):3d} WR={wr:4.1f}% NAV={nav:5.2f}x"
            print(f"  {rname:<24s}: 5Y[{st(p)}] | IS[{st(p[p['buy_date']<='2023-12-29'])}] | OOS[{st(p[p['buy_date']>='2024-01-01'])}] | 26[{st(p[p['buy_date']>='2026-01-01'])}]")

    print("\n=== 2. C2 持有期物理衰减校验 (D1收盘卖 vs T+2收盘卖 vs T+3/MA5) ===")
    c2 = pd.read_csv(f"{OUT_DIR}/ledger_C2_raw.csv", dtype={"c6": str})
    c2["ret_d1_close"] = c2["d1_intra_bps"] / 10000.0 - 0.0030
    for name, msk in [
        ("C2 RAW", np.ones(len(c2), dtype=bool)),
        ("C2 turn 3~20%", (c2["turn_sig"]>=0.03)&(c2["turn_sig"]<=0.20)),
        ("C2 turn >20%", c2["turn_sig"]>0.20),
    ]:
        s = c2[msk]
        dm_d1 = s.groupby("buy_date")["ret_d1_close"].mean()
        dm_e1 = s.groupby("buy_date")["ret_e1"].mean()
        dm_e2 = s.groupby("buy_date")["ret_e2"].mean()
        print(
            f"  {name:<15s}: n={len(s):4d} | T+1(D1盘中扣30bps)={dm_d1.mean()*10000:+5.1f}bps (IS={dm_d1[dm_d1.index<='2023-12-29'].mean()*10000:+5.1f}, OOS={dm_d1[dm_d1.index>='2024-01-01'].mean()*10000:+5.1f}, 26={dm_d1[dm_d1.index>='2026-01-01'].mean()*10000:+5.1f}) | "
            f"E1(T+2)={dm_e1.mean()*10000:+5.1f} | E2(T+3/MA5)={dm_e2.mean()*10000:+5.1f}"
        )

    print("\n=== 3. C1 与 C4 信号重叠度 & 2026年C1回撤物理原因 ===")
    c1 = pd.read_csv(f"{OUT_DIR}/ledger_C1_raw.csv", dtype={"c6": str})
    c4 = pd.read_csv(f"{OUT_DIR}/ledger_C4_raw.csv", dtype={"c6": str})
    k1 = set(zip(c1["buy_date"], c1["c6"]))
    k4 = set(zip(c4["buy_date"], c4["c6"]))
    print(f"  C1={len(k1)}, C4={len(k4)}, overlap={len(k1 & k4)} ({len(k1 & k4)/min(len(k1),len(k4))*100:.1f}%)")
    c1_26 = c1[(c1["buy_date"]>="2026-01-01") & (c1["csi_ok"]==True)]
    c1_25 = c1[(c1["buy_date"]>="2025-01-01") & (c1["buy_date"]<="2025-12-31") & (c1["csi_ok"]==True)]
    print(f"  C1(csi_ok) 2025: n={len(c1_25)}, mean_gap={c1_25['open_gap'].mean()*100:.2f}%, d1_intra={c1_25['d1_intra_bps'].mean():.1f}, e1={c1_25['ret_e1'].mean()*10000:.1f}")
    print(f"  C1(csi_ok) 2026: n={len(c1_26)}, mean_gap={c1_26['open_gap'].mean()*100:.2f}%, d1_intra={c1_26['d1_intra_bps'].mean():.1f}, e1={c1_26['ret_e1'].mean()*10000:.1f}")

    print("\n=== 4. Q8 物理截断测试 (<= 2024-12-31 数据重跑 C1/C4 并比对 2021-11-15~2024-12-20 逐笔收益) ===")
    # 物理截断原始 parquet 到 <= 2024-12-31
    orig_bt_end = r7.BT_END
    r7.BT_END = "2024-12-31"
    df_t, _, mz_t, md_t, csi_t, _ = r7.load_data()
    sm_t, ss_t = r7.compute_features_and_signals(df_t, mz_t, md_t, csi_t)
    led_t = r7.extract_trades(df_t, sm_t, ss_t)
    r7.BT_END = orig_bt_end

    for h in ["C1", "C4"]:
        full_df = pd.read_csv(f"{OUT_DIR}/ledger_{h}_raw.csv", dtype={"c6": str})
        f_sub = full_df[full_df["buy_date"] <= "2024-12-20"].sort_values(["buy_date", "c6"]).reset_index(drop=True)
        t_sub = led_t[h][led_t[h]["buy_date"] <= "2024-12-20"].sort_values(["buy_date", "c6"]).reset_index(drop=True)
        assert len(f_sub) == len(t_sub), f"{h} len mismatch: {len(f_sub)} vs {len(t_sub)}"
        assert (f_sub["c6"] == t_sub["c6"]).all() and (f_sub["buy_date"] == t_sub["buy_date"]).all()
        diff_e1 = np.max(np.abs(f_sub["ret_e1"].to_numpy() - t_sub["ret_e1"].to_numpy()))
        diff_e2 = np.max(np.abs(f_sub["ret_e2"].to_numpy() - t_sub["ret_e2"].to_numpy()))
        print(f"  [{h} PIT Truncation <=2024-12-31] matched={len(f_sub)} trades, max_abs_diff(E1)={diff_e1:.2e}, max_abs_diff(E2)={diff_e2:.2e}")

if __name__ == "__main__":
    check_ranking_and_overlap()

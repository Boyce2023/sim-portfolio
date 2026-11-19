#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fetch_gt60_5m_patch.py
补齐 close > 60 候选与持仓窗口内缺失的 5 分钟真实 K 线（Baostock adjustflag="3" 不复权），
并与 a_daily.parquet 日线 OHLC/Volume 做逐日严格物理一致性核验。
"""

import datetime
import os
import sys

import baostock as bs
import numpy as np
import pandas as pd

ABL_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/ablation_1to2_price60_20261119"
UPG_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, ABL_DIR)
sys.path.insert(0, UPG_DIR)

import upgrade_1to2_pit as u
from pit_signal_base import build_base_ctx_pit, apply_variant_v19

PATCH_PATH = f"{ABL_DIR}/gt60_5m_patch.parquet"


def to_bs_code(c6: str) -> str:
    return f"sh.{c6}" if c6.startswith(("60", "68")) else f"sz.{c6}"


def main():
    base_ctx = build_base_ctx_pit(u.DATA_END_DT)
    # 收集所有消融变体下通过 mask_v19 且 close > 60 的 (c6, d2_dt)
    ctx_nc = apply_variant_v19(base_ctx, price_cap=None, soft_pen_gt60=0.0)
    hist = ctx_nc["hist_fb"]
    # 为防止任何边界遗漏，直接取所有 gate_no_price & close > 60 & d2_dt >= CANON_5Y_START 且 score_active >= 270
    sub = hist[
        (hist["d2_dt"] >= u.CANON_5Y_START)
        & (hist["close"] > 60.0)
        & (hist["gate_no_price"])
        & ((ctx_nc["mask_v19"]) | (hist["score_active"] >= 280.0))
    ][["c6", "name", "d2_dt", "close", "mcap", "score_active"]].drop_duplicates()
    print(f"Target gt60 candidate-days to cover 5m (+20 calendar days window): {len(sub)}")

    bs.common.contants.BAOSTOCK_SERVER_IP = "114.94.20.42"
    lg = bs.login()
    assert lg.error_code == "0", f"Baostock login failed: {lg.error_msg}"

    bars = base_ctx["bars_5m_map"]
    pl = base_ctx["price_lookup"]
    all_dts = base_ctx["all_dts"]
    dt_to_idx = base_ctx["dt_to_idx"]

    records = []
    seen_req = set()
    for r in sub.itertuples(index=False):
        c6 = str(r.c6).zfill(6)
        idx2 = dt_to_idx.get(r.d2_dt, -1)
        if idx2 < 0:
            continue
        idx_end = min(len(all_dts) - 1, idx2 + 15)
        s_dt = all_dts[idx2]
        e_dt = all_dts[idx_end]
        # 检查需要抓取的区间是否已有缺失
        need_dates = [all_dts[i] for i in range(idx2, idx_end + 1) if (c6, all_dts[i]) not in bars and (c6, all_dts[i]) in pl]
        if not need_dates:
            continue
        req_key = (c6, s_dt, e_dt)
        if req_key in seen_req:
            continue
        seen_req.add(req_key)

        rs = bs.query_history_k_data_plus(
            to_bs_code(c6),
            "date,time,code,open,high,low,close,volume,amount",
            start_date=s_dt,
            end_date=e_dt,
            frequency="5",
            adjustflag="3",
        )
        assert rs.error_code == "0", f"Baostock query failed for {c6} {s_dt}~{e_dt}: {rs.error_msg}"
        cnt = 0
        while rs.next():
            row = rs.get_row_data()
            dt_v, tm_v = row[0], row[1]
            if (c6, dt_v) in bars:
                continue
            hhmm = tm_v[8:12]
            records.append({
                "c6": c6,
                "date": dt_v,
                "time": tm_v,
                "open": float(row[3]),
                "high": float(row[4]),
                "low": float(row[5]),
                "close": float(row[6]),
                "volume": float(row[7]),
                "amount": float(row[8]),
                "hhmm": hhmm,
                "hhmm_int": int(hhmm),
            })
            cnt += 1
        print(f"  fetched {c6} ({r.name}) {s_dt}~{e_dt}: {cnt} bars")

    bs.logout()
    df_patch = pd.DataFrame(records).drop_duplicates(subset=["c6", "date", "hhmm_int"])

    # 逐日与 a_daily 核对收盘价口径一致(允许沪市尾盘加权收盘价微差<=1%，防复权错)且 5m 高低包络不越界
    auc_diff_cnt = 0
    close_diff_notes = []
    for (c6, dt), grp in df_patch.groupby(["c6", "date"]):
        bar_d = pl.get((c6, dt))
        if bar_d is None:
            continue
        o_d, h_d, l_d, c_d = bar_d[0], bar_d[1], bar_d[2], bar_d[3]
        h_5, l_5, c_5 = grp["high"].max(), grp["low"].min(), grp.sort_values("hhmm_int")["close"].iloc[-1]
        rel_c = abs(c_5 - c_d) / c_d if c_d > 0 else 0.0
        assert rel_c <= 0.015, f"5m vs daily CLOSE mismatch (>1.5%) {c6} {dt}: 5m={c_5} vs daily={c_d}"
        assert h_5 <= h_d + 0.02 and l_5 >= l_d - 0.02, (
            f"5m vs daily bounds violation {c6} {dt}: 5m=({h_5},{l_5}) vs daily=({h_d},{l_d})"
        )
        if abs(h_5 - h_d) > 0.02 or abs(l_5 - l_d) > 0.02:
            auc_diff_cnt += 1
        if abs(c_5 - c_d) > 0.02:
            close_diff_notes.append((c6, dt, c_5, c_d))
    print(f"[Verify OK] close rel_diff<=1.5% (notes={len(close_diff_notes)}: {close_diff_notes[:5]}), auc_extrema_diff={auc_diff_cnt}")

    df_patch.to_parquet(PATCH_PATH, index=False)
    print(f"[Saved & Verified] {PATCH_PATH}, total_rows={len(df_patch)}")


if __name__ == "__main__":
    main()

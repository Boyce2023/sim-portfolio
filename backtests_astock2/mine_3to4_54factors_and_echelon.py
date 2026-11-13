#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三进四 54 因子全量构建与「早期市场(2022-2023) vs 近期量化市场(2024-2026 / 2025-2026)」双期检验
重点检验：
  1. 题材内其他首板/二板梯队是否重要？（同题材当日首板数、同题材首板次日竞价高开数/均值、3-2-1完整梯队、同行业首板数）
  2. 高标/龙虎榜/异动空间原生因子（前三板换手板数、绝对股价、拉萨散户席位、量化席位、机构席位、异动100%剩余空间、监管函）
  3. 大盘与情绪压回撤因子在近期市场的真实权重
"""
import os
import sys
import re
import json
import pickle
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
HD_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"

from core_3to4_5m_engine import load_3to4_universe_and_5m
from bt_3to4_step1_clean_5m_master import build_clean_5m_pool


def build_enriched_3to4_dataset():
    df, code_bars, bars_5m_map = load_3to4_universe_and_5m()
    with open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json", "r") as f:
        idx_k = json.load(f)
    sh_map, sz_map, csi_map = idx_k["sh000002"], idx_k["sz399107"], idx_k["sh000300"]

    # 1. Load 1-board & 2-board tables to build STRICTLY CAUSAL PIT intra-theme 1st-board & 2nd-board echelon!
    # In cand_0to1_firstboard, `buy_date` is the day a 0-streak stock surged; `is_zt_today==True` means it sealed 1st board ON `buy_date`.
    # Therefore, 1st-board siblings of a 3-board stock (whose 3rd board is `r.sig_date`) are rows where `df_1b.buy_date == r.sig_date` & `is_zt_today == True`!
    # Then on Day 4 (`r.buy_date`) at 09:25, we read each Day-3 1st-board stock's exact 09:25 open_pct from `code_bars`!
    df_1b = pd.read_parquet(
        f"{MAT_DIR}/cand_0to1_firstboard.parquet",
        columns=["code", "buy_date", "plate", "csrc_ind", "open_pct", "is_yizi_open", "is_zt_today"],
    )
    df_1b_zt = df_1b[df_1b["is_zt_today"] == True].copy()
    # Map each Day-3 1st-board stock to its next trading day 09:25 open_pct from code_bars (100% known at 09:25!)
    nxt_op_list = []
    for r1 in df_1b_zt.itertuples(index=False):
        c1 = str(r1.code).zfill(6)
        cb1 = code_bars.get(c1)
        p1 = cb1["date_to_pos"].get(str(r1.buy_date), -1) if cb1 else -1
        if cb1 and 0 <= p1 < len(cb1["dts"]) - 1 and cb1["pre_c"][p1 + 1] > 0:
            op_n = float(cb1["open"][p1 + 1] / cb1["pre_c"][p1 + 1] - 1.0)
            yz_n = bool(cb1["open"][p1 + 1] >= cb1["zt_px"][p1 + 1] - 0.005)
        else:
            op_n, yz_n = 0.0, False
        nxt_op_list.append((op_n, yz_n))
    df_1b_zt["d4_op"] = [x[0] for x in nxt_op_list]
    df_1b_zt["d4_yz"] = [x[1] for x in nxt_op_list]

    # Also 09:25 fresh 0->1 stocks opening >= +5% on Day 4 (`r.buy_date`): since open >= +5% guarantees high >= +4%, zero intraday bias!
    df_01_d4_hi = df_1b[df_1b["open_pct"] >= 0.05].copy()
    fresh01_plate_hi = df_01_d4_hi[df_01_d4_hi["plate"].notna() & (df_01_d4_hi["plate"] != "")].groupby(["buy_date", "plate"]).size().to_dict()

    df_2b = pd.read_parquet(
        f"{MAT_DIR}/cand_2to3.parquet",
        columns=["code", "sig_date", "buy_date", "plate", "csrc_ind", "open_pct"],
    )

    # Keyed by (`sig_date` = Day 3, `plate` / `csrc_ind`)!
    fb_plate_stats = {}
    for (sd_k, pl), g in df_1b_zt[df_1b_zt["plate"].notna() & (df_1b_zt["plate"] != "")].groupby(["buy_date", "plate"], sort=False):
        ops = g["d4_op"].to_numpy()
        fb_plate_stats[(sd_k, pl)] = (
            len(g),
            float(ops.mean()) if len(ops) else 0.0,
            int((ops >= 0.03).sum()),
            int(g["d4_yz"].sum()),
        )

    fb_csrc_stats = {}
    for (sd_k, cs), g in df_1b_zt[df_1b_zt["csrc_ind"].notna() & (df_1b_zt["csrc_ind"] != "")].groupby(["buy_date", "csrc_ind"], sort=False):
        ops = g["d4_op"].to_numpy()
        fb_csrc_stats[(sd_k, cs)] = (len(g), float(ops.mean()) if len(ops) else 0.0, int((ops >= 0.03).sum()))

    b2_plate_cnt = df_2b[df_2b["plate"].notna() & (df_2b["plate"] != "")].groupby(["buy_date", "plate"]).size().to_dict()
    b2_csrc_cnt = df_2b[df_2b["csrc_ind"].notna() & (df_2b["csrc_ind"] != "")].groupby(["buy_date", "csrc_ind"]).size().to_dict()

    # Same-day 3-board competition
    b3_clean = df[(~df["prev_is_yizi"]) & df["buyable_open"] & df["is_10cm_non_st"]]
    b3_day_cnt = b3_clean.groupby("buy_date").size().to_dict()
    b3_day_max_op = b3_clean.groupby("buy_date")["open_pct"].max().to_dict()

    # 2. Load LHB seats (Lhasa, Quant, Institution) strictly on sig_date (Day3)!
    Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
    lb = pd.read_parquet(
        f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet",
        columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"],
    )
    lb["dt"] = lb["TRADE_DATE"].astype(str).str[:10]
    lb["c6"] = lb["SECURITY_CODE"].astype(str).str[:6]
    g_seat = lb[lb["dt"] >= "2021-12-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
    lhb_map = {}
    for (d, c), gl in g_seat.groupby(["dt", "c6"], sort=False):
        tb = float(gl["BUY"].sum())
        ns = gl["OPERATEDEPT_NAME"].astype(str)
        lm = ns.str.contains("拉萨", na=False)
        lhb_map[(d, c)] = (
            int(lm.sum()),
            float(gl.loc[lm, "BUY"].sum()) / tb if tb > 0 else 0.0,
            int(ns.str.contains(Q_RE, na=False).sum()),
            int(ns.str.contains("机构专用", na=False).sum()),
        )

    # 3. Load clean regulatory / true bad notice map from high_dragon_scorecard cache (strictly < buy_date!)
    stock_reg, ex_reg, tox_dates = {}, {}, {}
    if os.path.exists(f"{HD_DIR}/part1_cache.pkl"):
        with open(f"{HD_DIR}/part1_cache.pkl", "rb") as f:
            pkg = pickle.load(f)
            if len(pkg) > 12:
                stock_reg = pkg[10] if isinstance(pkg[10], dict) else {}
                ex_reg = pkg[11] if isinstance(pkg[11], dict) else {}
                tox_dates = pkg[12] if isinstance(pkg[12], dict) else {}

    csi_dts = sorted(csi_map.keys())
    csi_pos = {d: i for i, d in enumerate(csi_dts)}

    # Compute row-level enriched columns
    cols_new = {
        "plate_fb_cnt": [], "plate_fb_op_avg": [], "plate_fb_ho_cnt": [], "plate_fb_yz_cnt": [],
        "plate_fresh01_hi_cnt": [],
        "csrc_fb_cnt": [], "csrc_fb_op_avg": [], "csrc_fb_ho_cnt": [],
        "plate_2b_cnt": [], "csrc_2b_cnt": [], "has_321_plate": [], "has_321_any": [],
        "b3_rival_cnt": [], "is_top1_3b_open": [],
        "px_d3": [], "turn_boards_3d": [], "headroom_100": [],
        "lhb_lh_cnt": [], "lhb_lh_share": [], "lhb_quant_cnt": [], "lhb_inst_cnt": [],
        "has_stock_reg": [], "has_ex_reg": [], "has_tox_notice": [],
        "csi_5d_prev": [], "csi_20d_prev": [],
        "weekday": [],
    }

    for r in df.itertuples(index=False):
        c6, sd, bd, pl, cs = str(r.code).zfill(6), str(r.sig_date), str(r.buy_date), str(r.plate), str(r.csrc_ind)
        fp = fb_plate_stats.get((sd, pl), (0, 0.0, 0, 0))
        fc = fb_csrc_stats.get((sd, cs), (0, 0.0, 0))
        p2 = int(b2_plate_cnt.get((bd, pl), 0))
        c2 = int(b2_csrc_cnt.get((bd, cs), 0))

        cols_new["plate_fb_cnt"].append(fp[0])
        cols_new["plate_fb_op_avg"].append(fp[1])
        cols_new["plate_fb_ho_cnt"].append(fp[2])
        cols_new["plate_fb_yz_cnt"].append(fp[3])
        cols_new["plate_fresh01_hi_cnt"].append(int(fresh01_plate_hi.get((bd, pl), 0)))
        cols_new["csrc_fb_cnt"].append(fc[0])
        cols_new["csrc_fb_op_avg"].append(fc[1])
        cols_new["csrc_fb_ho_cnt"].append(fc[2])
        cols_new["plate_2b_cnt"].append(p2)
        cols_new["csrc_2b_cnt"].append(c2)
        cols_new["has_321_plate"].append((p2 >= 1) and (fp[0] >= 2))
        cols_new["has_321_any"].append(((p2 >= 1) and (fp[0] >= 2)) or ((c2 >= 1) and (fc[0] >= 2)))
        cols_new["b3_rival_cnt"].append(int(b3_day_cnt.get(bd, 1)))
        cols_new["is_top1_3b_open"].append(float(r.open_pct) >= float(b3_day_max_op.get(bd, 9.9)) - 1e-5)

        cb = code_bars.get(c6)
        pos = cb["date_to_pos"].get(bd, -1) if cb else -1
        if cb and pos >= 3:
            px3 = float(cb["pre_c"][pos])
            # Count true non-yizi boards in [pos-3, pos-2, pos-1]
            tb3 = 0
            for p_prev in (pos - 3, pos - 2, pos - 1):
                if p_prev >= 0 and cb["is_zt"][p_prev] and (cb["low"][p_prev] < cb["zt_px"][p_prev] - 0.01):
                    tb3 += 1
            imap = sh_map if c6.startswith("60") else sz_map
            ir = imap.get(bd)
            p100 = 99999.0
            if ir:
                for k in range(1, min(10, pos) + 1):
                    bi = imap.get(cb["dts"][pos - k])
                    bc = cb["close"][pos - k] * cb["adjf"][pos - k] / cb["adjf"][pos]
                    if bi and bc > 0:
                        p100 = min(p100, bc * (2.0 + (ir / bi - 1.0)))
            hr = (p100 / float(cb["open"][pos]) - 1.0) if (p100 < 90000 and cb["open"][pos] > 0) else 0.50
        else:
            px3, tb3, hr = 15.0, 2, 0.50

        cols_new["px_d3"].append(px3)
        cols_new["turn_boards_3d"].append(tb3)
        cols_new["headroom_100"].append(hr)

        lh = lhb_map.get((sd, c6), (int(r.lhasa_seats_prev), float(r.lhasa_buy_share_prev), 0, 0))
        cols_new["lhb_lh_cnt"].append(lh[0])
        cols_new["lhb_lh_share"].append(lh[1])
        cols_new["lhb_quant_cnt"].append(lh[2])
        cols_new["lhb_inst_cnt"].append(lh[3])

        ci = csi_pos.get(sd, -1)
        d_m10 = csi_dts[max(0, ci - 10)] if ci >= 0 else "1990-01-01"
        d_m5 = csi_dts[max(0, ci - 5)] if ci >= 0 else "1990-01-01"
        ex_key = "SH" if c6.startswith("60") else "SZ"
        cols_new["has_stock_reg"].append(any(d_m10 <= x <= sd for x in stock_reg.get(c6, ())))
        cols_new["has_ex_reg"].append(any(d_m5 <= x <= sd for x in ex_reg.get(ex_key, ())))
        cols_new["has_tox_notice"].append(any(d_m10 <= x <= sd for x in tox_dates.get(c6, ())))
        cols_new["csi_5d_prev"].append((csi_map[sd] / csi_map[csi_dts[ci - 5]] - 1.0) if ci >= 5 else 0.0)
        cols_new["csi_20d_prev"].append((csi_map[sd] / csi_map[csi_dts[ci - 20]] - 1.0) if ci >= 20 else 0.0)
        cols_new["weekday"].append(pd.Timestamp(bd).weekday())

    for k, v in cols_new.items():
        df[k] = v
    return df, code_bars, bars_5m_map


if __name__ == "__main__":
    df, code_bars, bars_5m_map = build_enriched_3to4_dataset()
    out_pq = f"{CUR_DIR}/data_5y/cand_3to4_enriched54.parquet"
    df.to_parquet(out_pq, index=False)
    print(f"[+] Saved enriched 3to4 table: {df.shape} -> {out_pq}")

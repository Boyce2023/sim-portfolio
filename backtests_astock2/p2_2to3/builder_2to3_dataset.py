#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
builder_2to3_dataset.py: 二进三 5 年全量 PIT 候选清洗、>=36因子衍生与零未来函数时序模拟
"""
import os, sys, re, json, pickle
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p2_2to3"
os.makedirs(OUT_DIR, exist_ok=True)

SURF_RE = re.compile(r"(?:上塘路|财通.*杭州上塘|佛山|绿景路|消闲派|苏南)")
TOP_RE = re.compile(r"(?:章盟主|国泰君安.*上海江苏路|陈小群|中国银河.*大连金马路|六一中路|呼家楼|中信建投.*北京东城)")
Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")

def load_and_enrich():
    df = pd.read_parquet(f"{MAT_DIR}/cand_2to3.parquet")
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f:
        cb_map = pickle.load(f)["code_bars"]
    with open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json", "r") as f:
        idx_k = json.load(f)
    csi_map, sh_map, sz_map = idx_k["sh000300"], idx_k["sh000002"], idx_k["sz399107"]
    with open("/tmp/reg_tox_small.pkl", "rb") as f:
        reg_pkg = pickle.load(f)
    stock_reg, ex_reg, tox_dates = reg_pkg["stock_reg"], reg_pkg["ex_reg"], reg_pkg["tox_dates"]

    clean_mask = []
    for r in df.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        if not c6.startswith(("00", "60")) or "ST" in str(r.name).upper() or not bool(r.buyable_open):
            clean_mask.append(False); continue
        cb = cb_map.get(c6)
        if not cb: clean_mask.append(False); continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or cb["pre_c"][pos] <= 0 or (cb["zt_px"][pos] / cb["pre_c"][pos] < 1.085):
            clean_mask.append(False); continue
        clean_mask.append(True)
    df = df[clean_mask].copy().reset_index(drop=True)

    # 1. 1st-board intra-theme
    df_1b = pd.read_parquet(f"{MAT_DIR}/cand_0to1_firstboard.parquet", columns=["code", "buy_date", "plate", "open_pct", "is_zt_today"])
    df_1b_zt = df_1b[df_1b["is_zt_today"] == True].copy()
    op_n_list = []
    for r1 in df_1b_zt.itertuples(index=False):
        cb1 = cb_map.get(str(r1.code).zfill(6))
        p1 = cb1["date_to_pos"].get(str(r1.buy_date), -1) if cb1 else -1
        op_n = float(cb1["open"][p1 + 1] / cb1["pre_c"][p1 + 1] - 1.0) if cb1 and 0 <= p1 < len(cb1["dts"]) - 1 and cb1["pre_c"][p1 + 1] > 0 else 0.0
        op_n_list.append(op_n)
    df_1b_zt["d4_op"] = op_n_list
    fb_stats = {}
    for (sd_k, pl), g in df_1b_zt[df_1b_zt["plate"].notna() & (df_1b_zt["plate"] != "")].groupby(["buy_date", "plate"], sort=False):
        ops = g["d4_op"].to_numpy()
        fb_stats[(sd_k, pl)] = (len(g), int((ops >= 0.02).sum()))

    fresh01_hi = df_1b[df_1b["open_pct"] >= 0.05].groupby(["buy_date", "plate"]).size().to_dict()

    # 2. LHB seats on sig_date
    lb = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
    lb["dt"] = lb["TRADE_DATE"].astype(str).str[:10]
    lb["c6"] = lb["SECURITY_CODE"].astype(str).str[:6]
    ns = lb["OPERATEDEPT_NAME"].astype(str)
    lb["is_inst"] = ns.str.contains("机构专用", na=False).astype(int)
    lb["is_q"] = ns.str.contains(Q_RE, na=False).astype(int)
    lb["is_surf"] = ns.str.contains(SURF_RE, na=False).astype(int)
    lb["is_top"] = ns.str.contains(TOP_RE, na=False).astype(int)
    lhb_agg = lb.groupby(["dt", "c6"])[["is_inst", "is_q", "is_surf", "is_top"]].sum()
    lhb_map = lhb_agg.to_dict("index")

    # 3. Same-day 2b competitive dynamics
    b2_clean = df[(~df["prev_is_yizi"]) & (df["open_pct"] >= -0.04)]
    b2_day_cnt = b2_clean.groupby("buy_date").size().to_dict()
    b2_day_max_op = b2_clean.groupby("buy_date")["open_pct"].max().to_dict()
    plate_groups = {}
    for (bd, pl), g in b2_clean[b2_clean["plate"].notna() & (b2_clean["plate"] != "")].groupby(["buy_date", "plate"]):
        ops = sorted(g["open_pct"].tolist(), reverse=True)
        plate_groups[(bd, pl)] = ops

    csi_dts = sorted(csi_map.keys())
    csi_pos = {d: i for i, d in enumerate(csi_dts)}

    f_dict = {k: [] for k in [
        "to_ratio_d2_d1", "d2_amp", "px_d2", "is_top1_2b_open", "is_plate_top1_2b", "open_lead_plate_rk2",
        "day_2b_cnt", "plate_fb_cnt", "plate_fb_ho_cnt", "plate_fresh01_hi_cnt", "is_mkt_highest_2b",
        "csi_1d_prev", "headroom_100", "lhb_quant_cnt", "lhb_inst_cnt", "surf_yz_buy", "top_yz_buy",
        "has_stock_reg", "has_ex_reg", "has_tox_notice", "is_post_holiday_or_mon", "is_earn_blackout_month"
    ]}

    for r in df.itertuples(index=False):
        c6, sd, bd, pl = str(r.code).zfill(6), str(r.sig_date), str(r.buy_date), str(r.plate)
        cb = cb_map[c6]
        pos = cb["date_to_pos"][bd]
        p_d2, p_d1 = pos - 1, pos - 2
        to_d2 = cb["to"][p_d2] if p_d2 >= 0 else float(r.prev_to)
        to_d1 = cb["to"][p_d1] if p_d1 >= 0 else 1.0
        f_dict["to_ratio_d2_d1"].append(float(to_d2 / to_d1) if to_d1 > 0 else 1.0)
        f_dict["d2_amp"].append(float((cb["high"][p_d2] - cb["low"][p_d2]) / cb["pre_c"][p_d2]) if p_d2 >= 0 and cb["pre_c"][p_d2] > 0 else 0.05)
        f_dict["px_d2"].append(float(cb["close"][p_d2]) if p_d2 >= 0 else 10.0)
        f_dict["is_top1_2b_open"].append(float(r.open_pct) >= float(b2_day_max_op.get(bd, 9.9)) - 1e-5)
        p_ops = plate_groups.get((bd, pl), [float(r.open_pct)])
        f_dict["is_plate_top1_2b"].append(float(r.open_pct) >= p_ops[0] - 1e-5)
        f_dict["open_lead_plate_rk2"].append(float(p_ops[0] - p_ops[1]) if len(p_ops) >= 2 and float(r.open_pct) >= p_ops[0] - 1e-5 else 0.0)
        f_dict["day_2b_cnt"].append(int(b2_day_cnt.get(bd, 1)))

        fb = fb_stats.get((sd, pl), (0, 0))
        f_dict["plate_fb_cnt"].append(fb[0]); f_dict["plate_fb_ho_cnt"].append(fb[1])
        f_dict["plate_fresh01_hi_cnt"].append(int(fresh01_hi.get((bd, pl), 0)))
        f_dict["is_mkt_highest_2b"].append(bool(r.mkt_max_board_prev == 2))

        ci = csi_pos.get(sd, -1)
        f_dict["csi_1d_prev"].append((csi_map[sd] / csi_map[csi_dts[ci - 1]] - 1.0) if ci >= 1 else 0.0)

        imap = sh_map if c6.startswith("60") else sz_map
        ir = imap.get(bd)
        p100 = 99999.0
        if ir and pos >= 1:
            for k in range(1, min(10, pos) + 1):
                bi = imap.get(cb["dts"][pos - k])
                bc = cb["close"][pos - k] * cb["adjf"][pos - k] / cb["adjf"][pos]
                if bi and bc > 0: p100 = min(p100, bc * (2.0 + (ir / bi - 1.0)))
        f_dict["headroom_100"].append((p100 / float(cb["open"][pos]) - 1.0) if (p100 < 90000 and cb["open"][pos] > 0) else 0.50)

        lh = lhb_map.get((sd, c6), {"is_inst": 0, "is_q": 0, "is_surf": 0, "is_top": 0})
        f_dict["lhb_inst_cnt"].append(lh["is_inst"]); f_dict["lhb_quant_cnt"].append(lh["is_q"]); f_dict["surf_yz_buy"].append(lh["is_surf"]); f_dict["top_yz_buy"].append(lh["is_top"])

        d_m10 = csi_dts[max(0, ci - 10)] if ci >= 0 else "1990-01-01"
        d_m5 = csi_dts[max(0, ci - 5)] if ci >= 0 else "1990-01-01"
        ex_k = "SH" if c6.startswith("60") else "SZ"
        f_dict["has_stock_reg"].append(any(d_m10 <= x <= sd for x in stock_reg.get(c6, ())))
        f_dict["has_ex_reg"].append(any(d_m5 <= x <= sd for x in ex_reg.get(ex_k, ())))
        f_dict["has_tox_notice"].append(any(d_m10 <= x <= sd for x in tox_dates.get(c6, ())))
        f_dict["is_post_holiday_or_mon"].append(int(r.gap_days) >= 3)
        b_dt = pd.Timestamp(bd)
        f_dict["is_earn_blackout_month"].append(b_dt.month in (4, 7, 10) and b_dt.day >= 15)

    for k, v in f_dict.items(): df[k] = v
    out_path = f"{OUT_DIR}/cand_2to3_enriched.parquet"
    df.to_parquet(out_path, index=False)
    print(f"[+] Enriched 2to3 dataset saved: {df.shape} -> {out_path}")
    return df

if __name__ == "__main__":
    load_and_enrich()

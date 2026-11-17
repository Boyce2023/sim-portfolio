#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四进五 36+ 因子特征工程构建 (严格 PIT, <=150 行)"""
import os, sys, json, pickle, re, numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p2_4to5"
OUT_PARQUET = f"{OUT_DIR}/cand_4to5_enriched.parquet"

def build_features():
    df = pd.read_parquet(f"{MAT_DIR}/cand_high_dragon.parquet")
    d4 = df[df["prev_streak"] == 4].copy()
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f: cb_map = pickle.load(f)["code_bars"]
    with open(f"{MAT_DIR}/../index_klines_5y_cache.json", "r") as f: idx_k = json.load(f)
    sh_map, sz_map, csi_map = idx_k["sh000002"], idx_k["sz399107"], idx_k["sh000300"]
    csi_dts = sorted(csi_map.keys()); csi_pos = {d: i for i, d in enumerate(csi_dts)}
    with open("/tmp/reg_tox_small.pkl", "rb") as f: reg_pkg = pickle.load(f)
    s_reg, e_reg, tox_d = reg_pkg["stock_reg"], reg_pkg["ex_reg"], reg_pkg["tox_dates"]
    Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
    SURF_RE = re.compile(r"(?:上塘路|佛山|消闲派|苏南)")
    TOP_RE = re.compile(r"(?:章盟主|陈小群|六一中路|呼家楼|中关村|作手新一)")
    lb = pd.read_parquet(f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
    lb["dt"] = lb["TRADE_DATE"].astype(str).str[:10]; lb["c6"] = lb["SECURITY_CODE"].astype(str).str[:6]
    lhb_g = lb[lb["dt"] >= "2021-12-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
    lhb_map = {}
    for (d, c), gl in lhb_g.groupby(["dt", "c6"], sort=False):
        tb = float(gl["BUY"].sum()); ns = gl["OPERATEDEPT_NAME"].astype(str)
        lm = ns.str.contains("拉萨", na=False)
        lhb_map[(d, c)] = (int(lm.sum()), float(gl.loc[lm, "BUY"].sum())/tb if tb>0 else 0.0, int(ns.str.contains(Q_RE, na=False).sum()), int(ns.str.contains("机构专用", na=False).sum()), int(ns.str.contains(SURF_RE, na=False).sum()), int(ns.str.contains(TOP_RE, na=False).sum()))
    df_1b = pd.read_parquet(f"{MAT_DIR}/cand_0to1_firstboard.parquet", columns=["code", "buy_date", "plate", "csrc_ind", "open_pct", "is_zt_today"])
    df_1b_zt = df_1b[df_1b["is_zt_today"] == True].copy()
    fb_plate_cnt = df_1b_zt.groupby(["buy_date", "plate"]).size().to_dict()
    df_2b = pd.read_parquet(f"{MAT_DIR}/cand_2to3.parquet", columns=["buy_date", "plate", "csrc_ind"])
    b2_plate_cnt = df_2b.groupby(["buy_date", "plate"]).size().to_dict()
    df_3b = pd.read_parquet(f"{MAT_DIR}/cand_3to4.parquet", columns=["buy_date", "plate", "csrc_ind"])
    b3_plate_cnt = df_3b.groupby(["buy_date", "plate"]).size().to_dict()

    # Filter mainboard 10cm
    keep, is_main_10cm = [], []
    for r in d4.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6)
        if not c6.startswith(("00", "60")) or "ST" in str(r.name).upper() or cb is None: is_main_10cm.append(False); continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or cb["pre_c"][pos] <= 0 or (cb["zt_px"][pos] / cb["pre_c"][pos] < 1.085): is_main_10cm.append(False); continue
        is_main_10cm.append(True)
    d4["is_main_10cm"] = is_main_10cm
    d4 = d4[d4["is_main_10cm"]].copy()

    # Day-level 4-board rivals
    b4_clean = d4[d4["buyable_open"]]
    b4_day_cnt = b4_clean.groupby("buy_date").size().to_dict()
    b4_day_max_op = b4_clean.groupby("buy_date")["open_pct"].max().to_dict()
    b4_day_ranks = b4_clean.groupby("buy_date")["open_pct"].rank(ascending=False, method="min").to_dict()

    feats = defaultdict(list)
    for r in d4.itertuples(index=False):
        c6, sd, bd, pl, cs = str(r.code).zfill(6), str(r.sig_date), str(r.buy_date), str(r.plate), str(r.csrc_ind)
        cb = cb_map.get(c6); pos = cb["date_to_pos"].get(bd, -1)
        # Proposition 1
        feats["is_mkt_highest_4b"].append(int(r.mkt_max_board_prev == 4))
        feats["is_mkt_max_le5"].append(int(r.mkt_max_board_prev <= 5))
        feats["is_mkt_max_ge6"].append(int(r.mkt_max_board_prev >= 6))
        rcnt = int(b4_day_cnt.get(bd, 1))
        feats["b4_rival_cnt"].append(rcnt)
        feats["is_sole_4b"].append(int(rcnt == 1))
        feats["is_top1_4b_open"].append(int(float(r.open_pct) >= float(b4_day_max_op.get(bd, 9.9)) - 1e-5))
        # Proposition 2: headroom
        op = float(cb["open"][pos]); imap = sh_map if c6.startswith("60") else sz_map; ir = imap.get(bd)
        p100, p200 = 99999.0, 99999.0
        if ir and pos >= 1:
            for k in range(1, min(10, pos) + 1):
                bi = imap.get(cb["dts"][pos - k]); bc = cb["close"][pos - k] * cb["adjf"][pos - k] / cb["adjf"][pos]
                if bi and bc > 0: p100 = min(p100, bc * (2.0 + (ir / bi - 1.0)))
            for k in range(1, min(30, pos) + 1):
                bi = imap.get(cb["dts"][pos - k]); bc = cb["close"][pos - k] * cb["adjf"][pos - k] / cb["adjf"][pos]
                if bi and bc > 0: p200 = min(p200, bc * (3.0 + (ir / bi - 1.0)))
        hr100 = (p100 / op - 1.0) if op > 0 else 0.0
        hr200 = (p200 / op - 1.0) if op > 0 else 0.0
        feats["headroom_100"].append(hr100); feats["headroom_200"].append(hr200)
        feats["is_headroom_safe"].append(int(hr100 >= 0.22)); feats["is_headroom_tight"].append(int(hr100 < 0.12))
        # Proposition 3: D4 divergence & foundation
        px4 = float(cb["pre_c"][pos]); feats["px_d4"].append(px4)
        tb4 = 0
        for p_prev in range(max(0, pos - 4), pos):
            if cb["is_zt"][p_prev] and (cb["low"][p_prev] < cb["zt_px"][p_prev] - 0.01): tb4 += 1
        feats["turn_boards_4d"].append(tb4)
        feats["d4_intraday_dip"].append(float(cb["low"][pos-1] / cb["pre_c"][pos-1] - 1.0) if pos>=1 and cb["pre_c"][pos-1]>0 else 0.0)
        feats["d4_amp"].append(float((cb["high"][pos-1] - cb["low"][pos-1]) / cb["pre_c"][pos-1]) if pos>=1 and cb["pre_c"][pos-1]>0 else 0.0)
        t_d4 = float(cb["to"][pos-1]) if pos>=1 else 0.0; t_d3 = float(cb["to"][pos-2]) if pos>=2 else 0.0
        feats["to_ratio_d4_d3"].append(float(t_d4 / t_d3) if t_d3 > 0.01 else 1.0)
        # Proposition 5: echelon, lhb, reg
        p3_c = int(b3_plate_cnt.get((bd, pl), 0)); p2_c = int(b2_plate_cnt.get((bd, pl), 0)); p1_c = int(fb_plate_cnt.get((sd, pl), 0))
        feats["has_4321_echelon"].append(int((p3_c >= 1 or p2_c >= 1) and p1_c >= 1))
        feats["plate_fb_cnt"].append(p1_c); feats["plate_2b_cnt"].append(p2_c)
        lm_c, lm_s, q_c, inst_c, surf_c, top_c = lhb_map.get((sd, c6), (0, 0.0, 0, 0, 0, 0))
        feats["lhb_lh_cnt"].append(lm_c); feats["lhb_lh_share"].append(lm_s); feats["lhb_quant_cnt"].append(q_c); feats["lhb_inst_cnt"].append(inst_c); feats["surf_yz_buy"].append(surf_c); feats["top_yz_buy"].append(top_c)
        feats["has_stock_reg"].append(int(c6 in s_reg and any(x < bd for x in s_reg[c6])))
        feats["has_ex_reg"].append(int(any(x < bd for x in e_reg.get(c6, []))))
        feats["has_tox_notice"].append(int(c6 in tox_d and any(x < bd for x in tox_d[c6])))
        cp = csi_pos.get(bd, -1)
        feats["csi_1d_prev"].append(float(csi_map[bd]/csi_map[csi_dts[cp-1]] - 1.0) if cp>=1 else 0.0)
        dt_obj = pd.to_datetime(bd)
        feats["is_post_holiday_or_mon"].append(int(dt_obj.weekday() == 0))
        feats["is_earn_blackout_month"].append(int(dt_obj.month in (4, 8, 10) and dt_obj.day >= 15))

    for k, v in feats.items(): d4[k] = v
    d4.to_parquet(OUT_PARQUET, index=False)
    print(f"[Done] Enriched 4to5 dataset saved: {len(d4)} rows, {len(d4.columns)} cols -> {OUT_PARQUET}")

if __name__ == "__main__":
    from collections import defaultdict
    build_features()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_b4_2to3_right_handoff.py — 二进三专项因子回测工程师 B4
逐项精确实现并挨个回测《三进四 V3.4》右端买点基因前移与无缝出场移交 F19–F34（共15项编号机制）。

严格遵守：
1. 零 yfinance（D12 铁律）
2. 所有 SQLite 使用 file:...?mode=ro (uri=True)
3. 统一评测底座 common_eval_harness.py + core_3to4_5m_engine.py
4. 只写专属输出文件：run_b4_2to3_right_handoff.py / b4_2to3_right_genes_and_handoff_F19_F34.csv / b4_summary.json
"""
import os
import sys
import json
import time
import pickle
import sqlite3
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
AST2 = f"{SIM_DIR}/backtests_astock2"
MAT_DIR = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
P23_DIR = f"{AST2}/p2_2to3"
OUT_DIR = f"{AST2}/p3_deep_100"

for p in (AST2, OUT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from common_eval_harness import eval_factor_slice, load_production_3_ledgers, CSI_BENCH, FEE
from core_3to4_5m_engine import sim_buy_5m, sim_exit_5m, _slice_metrics_chrono
from score_3to4_v31_card import score_single_3to4_row
from p2_2to3.rd_clean_2to3_master import build_clean_score_2to3


def load_all_local_5m(needed_codes: set) -> dict:
    """加载全部本地 5 分钟 K 线缓存（3 个 parquet + 2 个只读 SQLite db）。"""
    bars = {}
    for pq in [
        f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet",
        f"{AST2}/data_5y/cand_3to4_5m_bars.parquet",
        f"{AST2}/p2_4to5/cand_4to5_5m_bars.parquet",
    ]:
        if not os.path.exists(pq):
            continue
        d5 = pd.read_parquet(pq, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
        d5["c6"] = d5["c6"].astype(str).str.zfill(6)
        d5 = d5[d5["c6"].isin(needed_codes)].sort_values(["c6", "date", "hhmm_int"])
        for (c, dt_s), g in d5.groupby(["c6", "date"], sort=False):
            key = (c, str(dt_s)[:10])
            if key not in bars:
                bars[key] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    # 2021-2023 PIT firstboard 5m sqlite (493MB)
    db_pit = f"{AST2}/data_5y/firstboard_5m_5y_pit.db"
    if os.path.exists(db_pit):
        con = sqlite3.connect(f"file:{db_pit}?mode=ro", uri=True)
        q_codes = sorted(needed_codes)
        for i in range(0, len(q_codes), 400):
            sub_c = q_codes[i:i + 400]
            qm = ",".join(["?"] * len(sub_c))
            sql = (
                "SELECT sec_code, trade_date, "
                "CAST(substr(bar_time,12,2)||substr(bar_time,15,2) AS INT) AS hhmm_int, "
                "open, high, low, close, volume, amount "
                f"FROM firstboard_5m_kline WHERE sec_code IN ({qm})"
            )
            dfb = pd.read_sql_query(sql, con, params=sub_c)
            if not dfb.empty:
                dfb["c6"] = dfb["sec_code"].astype(str).str.zfill(6)
                dfb["dt"] = dfb["trade_date"].astype(str).str[:10]
                dfb.sort_values(["c6", "dt", "hhmm_int"], inplace=True)
                for (c, dt_s), g in dfb.groupby(["c6", "dt"], sort=False):
                    if (c, dt_s) not in bars:
                        bars[(c, dt_s)] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        con.close()

    # Legacy 2021 sqlite (only if any needed code/date falls there)
    db_old = f"{SIM_DIR}/data/firstboard_5m_5y_pit.db"
    if os.path.exists(db_old):
        con = sqlite3.connect(f"file:{db_old}?mode=ro", uri=True)
        q_codes = sorted(needed_codes)
        for i in range(0, len(q_codes), 400):
            sub_c = q_codes[i:i + 400]
            qm = ",".join(["?"] * len(sub_c))
            sql = (
                "SELECT sec_code, substr(bar_time,1,10) AS dt, "
                "CAST(substr(bar_time,12,2)||substr(bar_time,15,2) AS INT) AS hhmm_int, "
                "open, high, low, close, volume, amount "
                f"FROM firstboard_5m_bars WHERE sec_code IN ({qm})"
            )
            dfb = pd.read_sql_query(sql, con, params=sub_c)
            if not dfb.empty:
                dfb["c6"] = dfb["sec_code"].astype(str).str.zfill(6)
                dfb.sort_values(["c6", "dt", "hhmm_int"], inplace=True)
                for (c, dt_s), g in dfb.groupby(["c6", "dt"], sort=False):
                    if (c, dt_s) not in bars:
                        bars[(c, dt_s)] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        con.close()
    return bars


def enrich_missing_factors(df: pd.DataFrame, cb_map: dict) -> pd.DataFrame:
    """精确补算 F23(plate_fb_ho_cnt/yz_cnt)、F26(day_plate_2b_cnt/mkt_open_rk_buyable)、F27(cum_real_to_2d)、F33(seal_amt_ratio)、F34(mon_jan_may/weekday)。"""
    df = df.copy()

    # 1. F23: 从 cand_0to1_firstboard.parquet + code_bars_5y.pkl 精确提取 Day2 首板群在 Day3 09:25 的高开与一字数
    df_1b = pd.read_parquet(
        f"{MAT_DIR}/cand_0to1_firstboard.parquet",
        columns=["code", "buy_date", "plate", "is_zt_today"],
    )
    df_1b_zt = df_1b[df_1b["is_zt_today"] == True].copy()
    d3_ops, d3_yzs = [], []
    for r1 in df_1b_zt.itertuples(index=False):
        cb1 = cb_map.get(str(r1.code).zfill(6))
        p1 = cb1["date_to_pos"].get(str(r1.buy_date), -1) if cb1 else -1
        if cb1 and 0 <= p1 < len(cb1["dts"]) - 1 and cb1["pre_c"][p1 + 1] > 0:
            op_n = float(cb1["open"][p1 + 1] / cb1["pre_c"][p1 + 1] - 1.0)
            yz_n = bool(cb1["open"][p1 + 1] >= cb1["zt_px"][p1 + 1] - 0.005)
        else:
            op_n, yz_n = 0.0, False
        d3_ops.append(op_n)
        d3_yzs.append(yz_n)
    df_1b_zt["d3_op"] = d3_ops
    df_1b_zt["d3_yz"] = d3_yzs

    # Exclude "其他" / empty plate for genuine intra-theme co-movement
    fb_valid = df_1b_zt[df_1b_zt["plate"].notna() & (df_1b_zt["plate"] != "") & (df_1b_zt["plate"] != "其他")]
    fb_map = {}
    for (sd_k, pl), g in fb_valid.groupby(["buy_date", "plate"], sort=False):
        ops = g["d3_op"].to_numpy()
        yzs = g["d3_yz"].to_numpy()
        fb_map[(sd_k, pl)] = (
            len(g),
            int((ops >= 0.02).sum()),       # >=+2% 高开（含一字，供对照）
            int(((ops >= 0.02) & (~yzs)).sum()),  # 纯换手高开 >=+2%
            int((ops >= 0.03).sum()),       # >=+3% 高开（三进四口径）
            int(yzs.sum()),                 # 09:25 顶一字数
        )

    fb_tot, fb_ho2, fb_ho2_nyz, fb_ho3, fb_yz = [], [], [], [], []
    for r in df.itertuples(index=False):
        rec = fb_map.get((str(r.sig_date), str(r.plate)), (0, 0, 0, 0, 0))
        fb_tot.append(rec[0])
        fb_ho2.append(rec[1])
        fb_ho2_nyz.append(rec[2])
        fb_ho3.append(rec[3])
        fb_yz.append(rec[4])
    df["f23_fb_cnt"] = fb_tot
    df["f23_fb_ho2_cnt"] = fb_ho2
    df["f23_fb_ho2_nyz_cnt"] = fb_ho2_nyz
    df["f23_fb_ho3_cnt"] = fb_ho3
    df["f23_fb_yz_cnt"] = fb_yz

    # 2. F26: 同题材唯一二板活口 × 全场可买二板竞价前2名
    # 严格按可买非一字二板（~prev_is_yizi & buyable_open）当日竞价降序排名
    b2_buyable = df[(~df["prev_is_yizi"]) & (df["buyable_open"])].copy()
    b2_buyable["mkt_open_rk_buyable"] = (
        b2_buyable.groupby("buy_date")["open_pct"]
        .rank(ascending=False, method="min")
        .astype(int)
    )
    df["mkt_open_rk_buyable"] = 999
    df.loc[b2_buyable.index, "mkt_open_rk_buyable"] = b2_buyable["mkt_open_rk_buyable"]

    plate_2b_cnt_buyable = b2_buyable[b2_buyable["plate"] != "其他"].groupby(["buy_date", "plate"]).size().to_dict()
    plate_2b_cnt_all = df[df["plate"] != "其他"].groupby(["buy_date", "plate"]).size().to_dict()
    df["day_plate_2b_cnt_buyable"] = [
        int(plate_2b_cnt_buyable.get((str(r.buy_date), str(r.plate)), 99)) if str(r.plate) != "其他" else 99
        for r in df.itertuples(index=False)
    ]
    df["day_plate_2b_cnt_all"] = [
        int(plate_2b_cnt_all.get((str(r.buy_date), str(r.plate)), 99)) if str(r.plate) != "其他" else 99
        for r in df.itertuples(index=False)
    ]

    # 3. F27: 首板+二板两日累计真实自由流通换手率（从 code_bars_5y.pkl 取 Day1 turn + Day2 turn）
    cum_to_raw, cum_to_real = [], []
    for r in df.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6)
        pos = cb["date_to_pos"].get(bd, -1) if cb else -1
        if cb and pos >= 2:
            t_d2 = float(cb["to"][pos - 1])
            t_d1 = float(cb["to"][pos - 2])
            t_sum = t_d1 + t_d2
        else:
            t_sum = float(r.prev_to) * 1.5
        free_ratio = max(0.05, 1.0 - float(r.lock_top10) / 100.0)
        cum_to_raw.append(t_sum)
        cum_to_real.append(t_sum / free_ratio)
    df["cum_to_2d_raw"] = cum_to_raw
    df["cum_real_to_2d"] = cum_to_real

    # 4. F33: 二板封单占成交额比
    df["seal_amt_ratio"] = np.where(df["prev_amt"] > 0, df["seal_amount"] / df["prev_amt"], 0.0)

    # 5. F34: 1月与5月退潮窗 + weekday
    b_ts = pd.to_datetime(df["buy_date"])
    df["buy_month"] = b_ts.dt.month
    df["buy_weekday"] = b_ts.dt.weekday  # 0=Mon, 3=Thu, 4=Fri
    df["is_jan_may_blackout"] = df["buy_month"].isin([1, 5])
    df["is_thu_fri"] = df["buy_weekday"].isin([3, 4])
    df["is_mon"] = df["buy_weekday"] == 0

    return df


def sim_buy_custom(c6: str, bd: str, cb: dict, pos: int, bars_5m_map: dict, buy_mode: str):
    """
    支持 4 种买法的精细撮合，返回 (buy_px, buy_hhmm, is_5m_exact, daily_trig_flag)。
    """
    op = float(cb["open"][pos])
    pc = float(cb["pre_c"][pos])
    hi = float(cb["high"][pos])
    zt = float(cb["zt_px"][pos])
    has_5m = (c6, bd) in bars_5m_map

    if op >= zt - 0.005:
        return None, None, has_5m, False

    if buy_mode == "open":
        return op, 925, True, True

    cfg = {
        "touch65_1130": (1.065, 1.000, 1130),
        "f29_1030": (1.065, 1.015, 1030),
        "dyn65_12_1130": (1.065, 1.012, 1130),
    }[buy_mode]
    trig = max(pc * cfg[0], op * cfg[1])
    max_hhmm = cfg[2]
    daily_hit = bool((trig < zt - 0.005) and (hi >= trig))

    if trig >= zt - 0.005:
        return None, None, has_5m, False
    if op >= trig:
        return op, 925, True, True

    if has_5m:
        arr = bars_5m_map[(c6, bd)]
        for row in arr:
            hhmm = int(row[0])
            if hhmm > max_hhmm:
                break
            bo, bh, bl = float(row[1]), float(row[2]), float(row[3])
            if bl >= zt - 0.005:
                continue
            if bh >= trig:
                fill_px = max(bo, trig)
                if fill_px < zt - 0.005:
                    return float(fill_px), hhmm, True, daily_hit
        return None, None, True, daily_hit
    else:
        if daily_hit:
            return float(max(op, trig)), 1000, False, True
        return None, None, False, False


def _sim_v18_1030_1430_day(arr, ok: float, clk: float, ztk: float, dtk: float, is_zt_eod: bool):
    """一进二式：10:30 均线定格（未封板且破分时均线立即走）+ 14:30 炸板抢跑。"""
    if arr is not None and len(arr) >= 4:
        cv, ca, locked1030 = 0.0, 0.0, False
        n_bar = len(arr)
        for i in range(n_bar - 1):
            hh, bc, bv, ba = int(arr[i, 0]), float(arr[i, 4]), float(arr[i, 5]), float(arr[i, 6])
            cv += bv
            ca += ba
            vwap = (ca / cv) if cv > 0 else bc
            if hh == 1030:
                if bc >= ztk - 0.01:
                    locked1030 = True
                elif bc < vwap:
                    nxo = float(arr[i + 1, 1])
                    if nxo > dtk + 0.005:
                        return True, nxo, int(arr[i + 1, 0])
            if locked1030 and hh >= 1430 and bc < ztk - 0.01:
                nxo = float(arr[i + 1, 1])
                if nxo > dtk + 0.005:
                    return True, nxo, int(arr[i + 1, 0])
    if is_zt_eod:
        return False, 0.0, 0
    return True, float(clk), 1500


def sim_exit_custom(c6: str, cb: dict, pos: int, bars_5m_map: dict, mode: str):
    """
    F30 多种出场模式精确对比：
    - A_reb2_noimm: 旧版 reb2 无免死（Day3未封->次日冲高+2%/收盘；Day3封->pm1345_5m 无免死）
    - A2_eod_reb2: 旧版 reb2 + 纯断板收盘无免死
    - B_v18_1030_1430: 一进二式 10:30 均线定格 + 14:30 炸板抢跑（Day3未封用reb2以公平隔离Day4+差距；另测B2带弱斩）
    - C1_f30_pm: PM建议 F30 无缝交接（Day3未封->Day4 open<pre_c*1.005 竞价弱斩，否则次日冲高+2%/收盘出；Day3封死->100%切三进四V3.4）
    - C2_f30_v34: 100% 原装三进四 V3.4 sim_exit_5m(pm1345_5m, cut_weak, use_yang_imm=True)
    - C3_hybrid_reb2_v34: Day3未封保留旧版reb2，一旦Day3封死三板则Day4起100%切三进四V3.4(pm1345+真阳免死)
    """
    if mode == "A_reb2_noimm":
        return sim_exit_5m(c6, cb, pos, bars_5m_map, exit_mode="pm1345_5m", day5_unsealed_mode="reb2", use_yang_imm=False)
    if mode == "A2_eod_reb2":
        return sim_exit_5m(c6, cb, pos, bars_5m_map, exit_mode="eod_break_5m", day5_unsealed_mode="reb2", use_yang_imm=False)
    if mode == "C2_f30_v34":
        return sim_exit_5m(c6, cb, pos, bars_5m_map, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True)
    if mode == "C3_hybrid_reb2_v34":
        return sim_exit_5m(c6, cb, pos, bars_5m_map, exit_mode="pm1345_5m", day5_unsealed_mode="reb2", use_yang_imm=True)

    n = len(cb["dts"])
    is_zt_d3 = bool(cb["is_zt"][pos])

    if not is_zt_d3:
        k = pos + 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            k += 1
        if k >= n:
            k = n - 1
            return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500
        if k > pos + 1:
            return cb["dts"][k], float(cb["open"][k]), float(cb["adjf"][k]), k - pos, 925
        dt_s = cb["dts"][k]
        o4, p4, c4 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
        dt4 = round(p4 * 0.90, 2)
        arr = bars_5m_map.get((c6, dt_s))

        if mode == "C1_f30_pm":
            # Day3 未封板则 Day4 竞价弱斩(open < pre_c*1.005 竞价出，否则冲高/收盘出)
            if o4 < p4 * 1.005:
                return dt_s, o4, float(cb["adjf"][k]), 1, 925
            if o4 >= p4 * 1.02:
                return dt_s, o4, float(cb["adjf"][k]), 1, 925
            if arr is not None and len(arr) > 0:
                for row in arr:
                    hhmm, bo, bh = int(row[0]), float(row[1]), float(row[2])
                    if bh <= dt4 + 0.005:
                        continue
                    if bh >= p4 * 1.02:
                        return dt_s, float(max(bo, p4 * 1.02)), float(cb["adjf"][k]), 1, hhmm
            return dt_s, c4, float(cb["adjf"][k]), 1, 1500

        # mode == "B_v18_1030_1430" (unsealed uses reb2 to match A)
        if o4 >= p4 * 1.02:
            return dt_s, o4, float(cb["adjf"][k]), 1, 925
        if arr is not None and len(arr) > 0:
            for row in arr:
                hhmm, bo, bh = int(row[0]), float(row[1]), float(row[2])
                if bh <= dt4 + 0.005:
                    continue
                if bh >= p4 * 1.02:
                    return dt_s, float(max(bo, p4 * 1.02)), float(cb["adjf"][k]), 1, hhmm
        return dt_s, c4, float(cb["adjf"][k]), 1, 1500

    # Day3 sealed 3rd board -> Day4+ simulation
    if mode == "C1_f30_pm":
        return sim_exit_5m(c6, cb, pos, bars_5m_map, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True)

    # B_v18_1030_1430 Day4+ loop
    k = pos + 1
    while k < n:
        if bool(cb["is_yizi_dt"][k]):
            k += 1
            continue
        dt_s = cb["dts"][k]
        ok, pck, clk, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
        dtk = round(pck * 0.90, 2)
        if k > pos + 1 and bool(cb["is_yizi_dt"][k - 1]):
            return dt_s, ok, float(cb["adjf"][k]), k - pos, 925
        arr = bars_5m_map.get((c6, dt_s))
        did_ex, spx, shhmm = _sim_v18_1030_1430_day(arr, ok, clk, ztk, dtk, bool(cb["is_zt"][k]))
        if did_ex:
            return dt_s, spx, float(cb["adjf"][k]), max(1, k - pos), shhmm
        k += 1
    k = n - 1
    return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500


def sim_pool_for_mode(df: pd.DataFrame, cb_map: dict, bars_5m_map: dict, buy_mode: str, exit_mode: str):
    """对 df 全集按指定 buy_mode x exit_mode 生成逐笔轨迹列表。"""
    rows = []
    for idx, r in enumerate(df.itertuples(index=False)):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6)
        if cb is None:
            rows.append(None)
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1:
            rows.append(None)
            continue
        bpx, bhh, is_5m_b, d_hit = sim_buy_custom(c6, bd, cb, pos, bars_5m_map, buy_mode)
        if bpx is None:
            rows.append(None)
            continue
        ex_dt, spx, adjs, hb, shh = sim_exit_custom(c6, cb, pos, bars_5m_map, exit_mode)
        nr = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        has_d4_5m = (pos + 1 < len(cb["dts"])) and ((c6, cb["dts"][pos + 1]) in bars_5m_map)
        rows.append({
            "idx": idx,
            "code": c6,
            "name": r.name,
            "buy_date": bd,
            "buy_hhmm": int(bhh),
            "buy_px": float(bpx),
            "exit_date": ex_dt,
            "exit_hhmm": int(shh),
            "hold_bars": int(hb),
            "net_ret": float(nr),
            "sealed_3b": bool(cb["is_zt"][pos]),
            "is_5m_buy": bool(is_5m_b),
            "has_d4_5m": bool(has_d4_5m),
            "open_pct": float(r.open_pct),
            "priority_score": float(r.open_pct),
        })
    return rows


def pick_daily_top1(df_sub: pd.DataFrame, score_col: str = "score") -> pd.DataFrame:
    """每日多只符合条件时，按得分→高开幅度→锁仓择优取 Top1，再喂入单仓严格时序轮动。"""
    if df_sub.empty:
        return df_sub
    sort_cols = ["buy_date"]
    asc = [True]
    if score_col in df_sub.columns:
        sort_cols.append(score_col)
        asc.append(False)
    sort_cols.extend(["open_pct", "lock_top10"])
    asc.extend([False, False])
    return df_sub.sort_values(sort_cols, ascending=asc).groupby("buy_date", as_index=False).first()


def record_factor_row(rows_out: list, fid: str, fname: str, slice_name: str, df_sub: pd.DataFrame, base_mean: float, base_mean_reb2: float = None):
    m = eval_factor_slice(df_sub, ret_col="net_ret", exit_col="exit_date", rank_col="open_pct", base_mean=base_mean)
    rec = {"factor_id": fid, "factor_name": fname, "slice": slice_name}
    rec.update(m)
    if base_mean_reb2 is not None and "net_ret_reb2" in df_sub.columns:
        m_r = eval_factor_slice(df_sub, ret_col="net_ret_reb2", exit_col="exit_date_reb2", rank_col="open_pct", base_mean=base_mean_reb2)
        rec["reb2_avg_ret"] = m_r["avg_ret"]
        rec["reb2_delta_vs_base"] = m_r["delta_vs_base"]
        rec["reb2_dual_same_sign"] = m_r["dual_same_sign"]
        rec["reb2_ss_nav"] = m_r["ss_nav"]
    rows_out.append(rec)
    return rec


def main():
    t0 = time.time()
    print("[B4] Loading datasets & 5m bars...")
    df = pd.read_parquet(f"{P23_DIR}/cand_2to3_enriched.parquet")
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f:
        cb_map = pickle.load(f)["code_bars"]

    df = enrich_missing_factors(df, cb_map)
    codes = set(df["code"].astype(str).str.zfill(6))
    bars_5m = load_all_local_5m(codes)
    print(f"[B4] Loaded {len(df)} 2to3 rows, {len(bars_5m)} (code,date) 5m blocks in {time.time()-t0:.1f}s")

    # Simulate two base daily trajectories across entire 2to3 table:
    # 1) Primary: open + C1_f30_pm (PM建议无缝交接)
    # 2) Reference: open + A_reb2_noimm (旧版reb2无免死基准)
    tr_f30 = sim_pool_for_mode(df, cb_map, bars_5m, "open", "C1_f30_pm")
    tr_reb2 = sim_pool_for_mode(df, cb_map, bars_5m, "open", "A_reb2_noimm")

    df["net_ret"] = [x["net_ret"] if x else np.nan for x in tr_f30]
    df["exit_date"] = [x["exit_date"] if x else "" for x in tr_f30]
    df["exit_hhmm"] = [x["exit_hhmm"] if x else 0 for x in tr_f30]
    df["hold_bars"] = [x["hold_bars"] if x else 0 for x in tr_f30]
    df["sealed_3b_sim"] = [x["sealed_3b"] if x else False for x in tr_f30]
    df["has_d4_5m"] = [x["has_d4_5m"] if x else False for x in tr_f30]
    df["is_5m_d3"] = [(str(r.code).zfill(6), str(r.buy_date)) in bars_5m for r in df.itertuples(index=False)]

    df["net_ret_reb2"] = [x["net_ret"] if x else np.nan for x in tr_reb2]
    df["exit_date_reb2"] = [x["exit_date"] if x else "" for x in tr_reb2]

    # Clean base pool for single-factor ablation (F19-F27, F33, F34)
    pool = df[(~df["prev_is_yizi"]) & (df["buyable_open"]) & (df["open_pct"] >= -0.04) & df["net_ret"].notna()].copy()
    base_mean = float(pool["net_ret"].mean())
    base_mean_reb2 = float(pool["net_ret_reb2"].mean())
    print(f"[B4] Clean non-yizi pool n={len(pool)} | F30-Open avg={base_mean*100:+.2f}% | Reb2-Open avg={base_mean_reb2*100:+.2f}%")

    csv_rows = []
    summary = {
        "pool_meta": {
            "total_rows": int(len(df)),
            "clean_non_yizi_n": int(len(pool)),
            "d3_5m_cov_n": int(pool["is_5m_d3"].sum()),
            "d4_5m_cov_when_d3_zt": int(pool[pool["sealed_3b_sim"]]["has_d4_5m"].sum()),
            "d3_zt_n_in_pool": int(pool["sealed_3b_sim"].sum()),
            "base_f30_open_avg_pct": round(base_mean * 100, 3),
            "base_reb2_open_avg_pct": round(base_mean_reb2 * 100, 3),
            "csi300_5y_pct": round(CSI_BENCH["5y"] * 100, 2),
        },
        "factors": {},
    }

    record_factor_row(csv_rows, "BASE", "清洁非一字底池(open+F30)", "ALL_CLEAN", pool, base_mean, base_mean_reb2)

    # =========================================================================
    # F19 - F27, F33, F34: 逐项因子单变量 + 双期 + 单仓 + 等权全量测试
    # =========================================================================
    single_factor_specs = [
        ("F19", "Day2收盘价区间", [
            ("px_d2<=15", pool["px_d2"] <= 15.0),
            ("px_d2<=18 (黄金带前移)", pool["px_d2"] <= 18.0),
            ("18<px_d2<=30", (pool["px_d2"] > 18.0) & (pool["px_d2"] <= 30.0)),
            ("px_d2>30", pool["px_d2"] > 30.0),
        ]),
        ("F20", "前一日全场最高连板空间窗", [
            ("max_board_prev==2", pool["mkt_max_board_prev"] == 2),
            ("max_board_prev in (3,4) 破局窗", pool["mkt_max_board_prev"].isin([3, 4])),
            ("max_board_prev==5", pool["mkt_max_board_prev"] == 5),
            ("max_board_prev>=6", pool["mkt_max_board_prev"] >= 6),
        ]),
        ("F21", "前一日全场涨停家数温热vs过热", [
            ("mkt_zt_prev<35 冰点", pool["mkt_zt_prev"] < 35),
            ("35<=mkt_zt_prev<=85 温热区", pool["mkt_zt_prev"].between(35, 85)),
            ("86<=mkt_zt_prev<95 偏热", (pool["mkt_zt_prev"] >= 86) & (pool["mkt_zt_prev"] < 95)),
            ("mkt_zt_prev>=95 百股过热", pool["mkt_zt_prev"] >= 95),
        ]),
        ("F22", "前十锁仓45%或真实自由流通45亿双45门", [
            ("dual45: lock>=45 | rfm>=45", (pool["lock_top10"] >= 45.0) | (pool["real_free_mcap"] >= 45.0)),
            ("dual_low: lock<45 & rfm<45 (双低微盘)", (pool["lock_top10"] < 45.0) & (pool["real_free_mcap"] < 45.0)),
            ("lock_top10>=45", pool["lock_top10"] >= 45.0),
            ("real_free_mcap>=45", pool["real_free_mcap"] >= 45.0),
            ("both>=45", (pool["lock_top10"] >= 45.0) & (pool["real_free_mcap"] >= 45.0)),
        ]),
        ("F23", "同题材Day2首板群Day3 09:25助攻vs顶一字抽血", [
            ("fb_ho>=2 & fb_yz==0 (纯换手高开>=2%助攻)", (pool["f23_fb_ho2_cnt"] >= 2) & (pool["f23_fb_yz_cnt"] == 0)),
            ("fb_ho3>=2 & fb_yz==0 (高开>=3%助攻)", (pool["f23_fb_ho3_cnt"] >= 2) & (pool["f23_fb_yz_cnt"] == 0)),
            ("fb_yz>=1 (首板顶一字抽血)", pool["f23_fb_yz_cnt"] >= 1),
            ("fb_yz==0 & fb_ho<2 (无一字中性)", (pool["f23_fb_yz_cnt"] == 0) & (pool["f23_fb_ho2_cnt"] < 2)),
            ("plate==其他(无明确题材)", pool["plate"] == "其他"),
        ]),
        ("F24", "同题材涨停队友今早竞价均值连坐排雷", [
            ("plate_peers_open_avg<-1.5% (连坐排雷)", pool["plate_peers_open_avg"] < -0.015),
            ("-1.5%<=peers_open<+2.0%", (pool["plate_peers_open_avg"] >= -0.015) & (pool["plate_peers_open_avg"] < 0.020)),
            ("peers_open>=+2.0% (板块高开共振)", pool["plate_peers_open_avg"] >= 0.020),
        ]),
        ("F25", "监管监控/一日游席位/拉萨散户/3板跌停排雷", [
            ("has_ex_reg==True (近5日交易所重点监控)", pool["has_ex_reg"] == True),
            ("has_ex_reg==False", pool["has_ex_reg"] == False),
            ("surf_yz_buy>=1 (一日游砸盘席位)", pool["surf_yz_buy"] >= 1),
            ("surf_yz_buy==0", pool["surf_yz_buy"] == 0),
            ("lhasa_seats_prev==0 (零拉萨)", pool["lhasa_seats_prev"] == 0),
            ("lhasa_seats_prev in 1..2", pool["lhasa_seats_prev"].between(1, 2)),
            ("lhasa_seats_prev>=3 (拉萨扎堆)", pool["lhasa_seats_prev"] >= 3),
            ("prev_3b_dt_cnt==0 (前日3板零跌停)", pool["prev_3b_dt_cnt"] == 0),
            ("prev_3b_dt_cnt>=2 (前日3板>=2跌停)", pool["prev_3b_dt_cnt"] >= 2),
        ]),
        ("F26", "同题材唯一二板活口x全场可买二板竞价前2名", [
            ("sole_2b(buyable) & mkt_open_rk_buy<=2", (pool["day_plate_2b_cnt_buyable"] == 1) & (pool["mkt_open_rk_buyable"] <= 2)),
            ("sole_2b(all) & mkt_open_rk<=2", (pool["day_plate_2b_cnt_all"] == 1) & (pool["mkt_open_rk"] <= 2)),
            ("sole_2b(buyable) only", pool["day_plate_2b_cnt_buyable"] == 1),
            ("mkt_open_rk_buy<=2 only", pool["mkt_open_rk_buyable"] <= 2),
            ("non_sole_2b (day_plate_2b_cnt>=2)", (pool["day_plate_2b_cnt_buyable"] >= 2) & (pool["plate"] != "其他")),
        ]),
        ("F27", "首板+二板两日累计真实自由流通换手率", [
            ("cum_real_to_2d<22% (极缩量庄股)", pool["cum_real_to_2d"] < 22.0),
            ("22%<=cum_real_to_2d<=50% (充分洗盘)", pool["cum_real_to_2d"].between(22.0, 50.0)),
            ("50%<cum_real_to_2d<=55% (过渡)", (pool["cum_real_to_2d"] > 50.0) & (pool["cum_real_to_2d"] <= 55.0)),
            ("cum_real_to_2d>55% (筹码涣散)", pool["cum_real_to_2d"] > 55.0),
        ]),
        ("F33", "二板封单占成交额比", [
            ("seal_amount/prev_amt>=0.08", pool["seal_amt_ratio"] >= 0.08),
            ("seal_amount/prev_amt<0.08", pool["seal_amt_ratio"] < 0.08),
            ("seal_amount/prev_amt>=0.15", pool["seal_amt_ratio"] >= 0.15),
            ("seal_amount/prev_amt<0.04", pool["seal_amt_ratio"] < 0.04),
        ]),
        ("F34", "日历效应(1/5月退潮+周四五跨周末+周一溢价)", [
            ("month in (1,5) 退潮扣分窗", pool["is_jan_may_blackout"] == True),
            ("month not in (1,5)", pool["is_jan_may_blackout"] == False),
            ("is_earn_blackout_month (旧4/7/10下半月)", pool["is_earn_blackout_month"] == True),
            ("weekday in (3,4) 周四五跨周末", pool["is_thu_fri"] == True),
            ("is_post_holiday_or_mon 节后或周一", pool["is_post_holiday_or_mon"] == True),
            ("weekday==0 纯周一", pool["is_mon"] == True),
            ("weekday in (1,2) 周二周三", pool["buy_weekday"].isin([1, 2])),
        ]),
    ]

    for fid, fname, slices in single_factor_specs:
        summary["factors"][fid] = {"name": fname, "slices": []}
        print(f"\n=== {fid}: {fname} ===")
        for s_lbl, mask in slices:
            sub = pool[mask]
            rec = record_factor_row(csv_rows, fid, fname, s_lbl, sub, base_mean, base_mean_reb2)
            summary["factors"][fid]["slices"].append(rec)
            print(
                f"  {s_lbl:42s} | n={rec['n_raw']:4d} WR={rec['wr_raw']:5.1f}% PO={rec['payoff_raw']:4.2f} "
                f"avg={rec['avg_ret']:+5.2f}% (d={rec['delta_vs_base']:+5.2f}%) "
                f"[22-23:{rec['early_22_23_avg']:+5.2f}%, 24-26:{rec['recent_24_26_avg']:+5.2f}%, dual={rec['dual_same_sign']}] "
                f"| SS: {rec['ss_n']:3d}笔 NAV={rec['ss_nav']:6.2f}x(ex3={rec['ss_ex_top3_nav']:5.2f}x) MDD={rec['ss_mdd']:4.1f}% EQ={rec['eq_nav']:6.2f}x"
            )

    # =========================================================================
    # Build High-Potential Leader Pool (for F29, F30, F31, F32 coupled tests)
    # =========================================================================
    sc_v1 = build_clean_score_2to3(df)
    df["sc_v1"] = sc_v1
    hi_mask_100 = df["sc_v1"] >= 100
    hi_mask_108 = df["sc_v1"] >= 108
    # Broader skeleton pool (open_pct in [-1.5%, +7.0%], non-yizi, no tox/reg, open_board>=1, px_d2<=28)
    skel_mask = (
        (~df["prev_is_yizi"]) & (df["buyable_open"]) &
        (df["open_pct"].between(-0.015, 0.070)) &
        (~df["has_tox_notice"]) & (~df["has_stock_reg"]) & (~df["has_ex_reg"]) &
        (df["open_board_count"] >= 1) & (df["px_d2"] <= 28.0) &
        (df["to_ratio_d2_d1"] >= 0.55) & (df["prev_break_dt_rate_10d"] <= 0.30)
    )
    print(f"\n[B4] Pools for F29/F30: Skeleton n={skel_mask.sum()}, V1_sc>=100 n={hi_mask_100.sum()}, V1_sc>=108 n={hi_mask_108.sum()}")

    # =========================================================================
    # F29: 买点触发精细对比实验 (4种买法 × 同池 + 100% 5m子集一致率)
    # =========================================================================
    print("\n=== F29: 买点触发精细对比实验 (统一配 C1_f30_pm 出场) ===")
    buy_modes = [
        ("B1_open", "open"),
        ("B2_touch65_1130", "touch65_1130"),
        ("B3_f29_1030", "f29_1030"),
        ("B4_dyn65_12_1130", "dyn65_12_1130"),
    ]
    f29_res = {"pools": {}, "d3_5m_consistency": {}}

    # Consistency audit on 100% Day3-5m subset across full clean pool
    d3_5m_pool = pool[pool["is_5m_d3"] == True].copy()
    for b_lbl, b_mode in buy_modes[1:]:
        agree_cnt, hit_5m_cnt, hit_daily_cnt = 0, 0, 0
        for r in d3_5m_pool.itertuples(index=False):
            c6, bd = str(r.code).zfill(6), str(r.buy_date)
            cb = cb_map[c6]
            pos = cb["date_to_pos"][bd]
            bpx, _, _, d_hit = sim_buy_custom(c6, bd, cb, pos, bars_5m, b_mode)
            m_hit = bpx is not None
            if m_hit:
                hit_5m_cnt += 1
            if d_hit:
                hit_daily_cnt += 1
            if m_hit == d_hit:
                agree_cnt += 1
        tot_5m = len(d3_5m_pool)
        f29_res["d3_5m_consistency"][b_lbl] = {
            "d3_5m_n": int(tot_5m),
            "hit_5m_n": int(hit_5m_cnt),
            "hit_daily_n": int(hit_daily_cnt),
            "agree_n": int(agree_cnt),
            "agree_rate_pct": round(agree_cnt / max(1, tot_5m) * 100, 2),
        }
        print(f"  [Day3 5m一致率 {b_lbl}] 5m样本={tot_5m}, 5m触发={hit_5m_cnt}, 日线触发={hit_daily_cnt}, 一致率={agree_cnt}/{tot_5m} ({agree_cnt/max(1,tot_5m)*100:.1f}%)")

    for p_name, p_mask in [("V1_sc>=100高潜池", hi_mask_100), ("V1_sc>=108精选池", hi_mask_108), ("骨架池", skel_mask)]:
        f29_res["pools"][p_name] = []
        print(f"  -- Pool: {p_name} (candidates={int(p_mask.sum())}) --")
        for b_lbl, b_mode in buy_modes:
            tr_b = sim_pool_for_mode(df[p_mask], cb_map, bars_5m, b_mode, "C1_f30_pm")
            sub_df = df[p_mask].copy().reset_index(drop=True)
            valid_rows = []
            for i_row, t_rec in enumerate(tr_b):
                if t_rec is not None:
                    row_dict = sub_df.iloc[i_row].to_dict()
                    row_dict.update({
                        "net_ret": t_rec["net_ret"],
                        "exit_date": t_rec["exit_date"],
                        "buy_hhmm": t_rec["buy_hhmm"],
                        "is_5m_buy": t_rec["is_5m_buy"],
                    })
                    valid_rows.append(row_dict)
            vdf = pd.DataFrame(valid_rows)
            vdf_top1 = pick_daily_top1(vdf, "sc_v1")
            m_all = eval_factor_slice(vdf, "net_ret", "exit_date", "sc_v1", base_mean=0.0)
            m_top1 = eval_factor_slice(vdf_top1, "net_ret", "exit_date", "sc_v1", base_mean=0.0)
            m_5m = eval_factor_slice(vdf[vdf["is_5m_buy"] == True], "net_ret", "exit_date", "sc_v1", base_mean=0.0) if not vdf.empty else {}
            item = {
                "buy_mode": b_lbl,
                "raw_n": m_all["n_raw"],
                "raw_wr": m_all["wr_raw"],
                "raw_payoff": m_all["payoff_raw"],
                "raw_avg_ret": m_all["avg_ret"],
                "eq_nav": m_all["eq_nav"],
                "top1_ss_n": m_top1["ss_n"],
                "top1_ss_wr": m_top1["ss_wr"],
                "top1_ss_payoff": m_top1["ss_payoff"],
                "top1_ss_nav": m_top1["ss_nav"],
                "top1_ss_mdd": m_top1["ss_mdd"],
                "top1_ss_ex3": m_top1["ss_ex_top3_nav"],
                "d3_5m_exact_n": m_5m.get("n_raw", 0),
                "d3_5m_exact_avg": m_5m.get("avg_ret", 0.0),
            }
            f29_res["pools"][p_name].append(item)
            record_factor_row(csv_rows, "F29", f"买点对比_{p_name}", b_lbl, vdf_top1, base_mean=0.0)
            print(
                f"    {b_lbl:18s} | 全池{m_all['n_raw']:4d}笔 WR={m_all['wr_raw']:4.1f}% PO={m_all['payoff_raw']:4.2f} avg={m_all['avg_ret']:+5.2f}% EQ={m_all['eq_nav']:6.2f}x "
                f"| Top1单仓:{m_top1['ss_n']:3d}笔 WR={m_top1['ss_wr']:4.1f}% PO={m_top1['ss_payoff']:4.2f} NAV={m_top1['ss_nav']:6.2f}x(ex3={m_top1['ss_ex_top3_nav']:5.2f}x) MDD={m_top1['ss_mdd']:4.1f}%"
            )
    summary["factors"]["F29"] = f29_res

    # =========================================================================
    # F30: 封死三板后「Day4起无缝切换三进四V3.4出场规则」对比实验
    # =========================================================================
    print("\n=== F30: 出场规则无缝交接对比实验 ===")
    exit_modes = [
        ("A_reb2_noimm", "旧版reb2无免死"),
        ("A2_eod_reb2", "旧版纯断板收盘+reb2无免死"),
        ("B_v18_1030_1430", "一进二式10:30均线+14:30抢跑"),
        ("C1_f30_pm", "PM建议F30无缝交接(未封open<0.5%斩+封三板切V3.4)"),
        ("C2_f30_v34", "原装三进四V3.4(cut_weak+pm1345+真阳免死)"),
        ("C3_hybrid_reb2_v34", "混合最优对照(未封用reb2+封三板切V3.4真阳免死)"),
    ]
    f30_res = {}
    for p_name, p_mask in [("V1_sc>=100高潜池_open", hi_mask_100), ("V1_sc>=108精选池_open", hi_mask_108), ("清洁底池_open", (df["code"].isin(pool["code"])) & (df.index.isin(pool.index)))]:
        f30_res[p_name] = []
        print(f"  -- Pool: {p_name} (n={int(p_mask.sum())}) --")
        sub_df = df[p_mask].copy().reset_index(drop=True)
        for e_code, e_desc in exit_modes:
            tr_e = sim_pool_for_mode(sub_df, cb_map, bars_5m, "open", e_code)
            valid_rows = []
            for i_row, t_rec in enumerate(tr_e):
                if t_rec is not None:
                    rd = sub_df.iloc[i_row].to_dict()
                    rd.update({"net_ret": t_rec["net_ret"], "exit_date": t_rec["exit_date"], "sealed_3b_sim": t_rec["sealed_3b"]})
                    valid_rows.append(rd)
            vdf = pd.DataFrame(valid_rows)
            vdf_top1 = pick_daily_top1(vdf, "sc_v1")
            m_all = eval_factor_slice(vdf, "net_ret", "exit_date", "sc_v1", base_mean=0.0)
            m_top1 = eval_factor_slice(vdf_top1, "net_ret", "exit_date", "sc_v1", base_mean=0.0)
            v_seal = vdf[vdf["sealed_3b_sim"] == True]
            v_unseal = vdf[vdf["sealed_3b_sim"] == False]
            m_seal = eval_factor_slice(v_seal, "net_ret", "exit_date", "sc_v1", base_mean=0.0)
            m_unseal = eval_factor_slice(v_unseal, "net_ret", "exit_date", "sc_v1", base_mean=0.0)
            rec = {
                "exit_mode": e_code,
                "desc": e_desc,
                "raw_n": m_all["n_raw"],
                "raw_wr": m_all["wr_raw"],
                "raw_payoff": m_all["payoff_raw"],
                "raw_avg_ret": m_all["avg_ret"],
                "sealed_3b_n": m_seal["n_raw"],
                "sealed_3b_avg": m_seal["avg_ret"],
                "sealed_3b_eq_nav": m_seal["eq_nav"],
                "unsealed_3b_n": m_unseal["n_raw"],
                "unsealed_3b_avg": m_unseal["avg_ret"],
                "top1_ss_n": m_top1["ss_n"],
                "top1_ss_wr": m_top1["ss_wr"],
                "top1_ss_payoff": m_top1["ss_payoff"],
                "top1_ss_nav": m_top1["ss_nav"],
                "top1_ss_mdd": m_top1["ss_mdd"],
                "top1_ss_ex3": m_top1["ss_ex_top3_nav"],
                "eq_nav": m_all["eq_nav"],
            }
            f30_res[p_name].append(rec)
            record_factor_row(csv_rows, "F30", f"出场对比_{p_name}", e_code, vdf_top1, base_mean=0.0)
            print(
                f"    {e_code:16s} | 全池均={m_all['avg_ret']:+5.2f}% WR={m_all['wr_raw']:4.1f}% PO={m_all['payoff_raw']:4.2f} "
                f"(封3板n={m_seal['n_raw']}均={m_seal['avg_ret']:+5.2f}% | 未封n={m_unseal['n_raw']}均={m_unseal['avg_ret']:+5.2f}%) "
                f"| Top1单仓:{m_top1['ss_n']:3d}笔 NAV={m_top1['ss_nav']:6.2f}x(ex3={m_top1['ss_ex_top3_nav']:5.2f}x) MDD={m_top1['ss_mdd']:4.1f}%"
            )
    summary["factors"]["F30"] = f30_res

    # =========================================================================
    # F31: 三大主力全空仓日专属「补缺位门」
    # =========================================================================
    print("\n=== F31: 三大主力全空仓日专属补缺位门 ===")
    ledgers = load_production_3_ledgers()
    l1, l34, lh = ledgers["1to2"], ledgers["3to4"], ledgers["high"]
    any_buy_dates = ledgers["any_main_buy_dates"]

    all_tdts = sorted(cb_map["000002"]["dts"]) if "000002" in cb_map else sorted(df["buy_date"].unique())
    all_tdts = [d for d in all_tdts if "2022-01-01" <= d <= "2026-11-15"]

    # Build occupied date sets across 3 main production strategies
    occ_inclusive = set()
    occ_strict_open = set()  # if exit_at_open==True on exit_date, slot is occupied [buy_date, exit_date) at 09:25? Let's track [buy_date, exit_date] inclusive first!
    for ldf in (l1, l34, lh):
        for r in ldf.itertuples(index=False):
            bd_s, ed_s = str(r.buy_date)[:10], str(r.exit_date)[:10]
            for d in all_tdts:
                if bd_s <= d <= ed_s:
                    occ_inclusive.add(d)
                if bd_s <= d < ed_s:
                    occ_strict_open.add(d)

    # Combined 3-main single-slot / independent ledger baseline
    main_all = pd.concat([
        l1[["buy_date", "exit_date", "net_ret"]].assign(strat="1to2"),
        l34[["buy_date", "exit_date", "net_ret"]].assign(strat="3to4"),
        lh[["buy_date", "exit_date", "net_ret"]].assign(strat="high"),
    ], ignore_index=True)

    # 3-main combined strict single-slot priority (3to4 > high > 1to2) vs additive equal-split
    def eval_combined_nav(trades_list):
        if not trades_list:
            return {"n": 0, "wr": 0.0, "payoff": 0.0, "nav": 1.0, "mdd": 0.0}
        srt = sorted(trades_list, key=lambda x: (x["buy_date"], x.get("prio", 0)))
        free_dt = ""
        nav, pk, mdd = 1.0, 1.0, 0.0
        rets = []
        for t in srt:
            if free_dt == "" or t["buy_date"] > free_dt:
                nav *= (1.0 + t["net_ret"])
                pk = max(pk, nav)
                mdd = max(mdd, (pk - nav) / pk)
                free_dt = max(t["buy_date"], t["exit_date"])
                rets.append(t["net_ret"])
        arr = np.array(rets, dtype=float)
        w, l = arr[arr > 0], arr[arr <= 0]
        wr = float((arr > 0).mean() * 100) if len(arr) else 0.0
        po = float(w.mean() / abs(l.mean())) if len(w) and len(l) and l.mean() < 0 else 0.0
        return {"n": len(arr), "wr": round(wr, 2), "payoff": round(po, 2), "nav": round(nav, 3), "mdd": round(mdd * 100, 2)}

    # Also test 3-main parallel-sleeve daily compounding (when multiple mains trade same day, average daily return; on empty days 2to3 fills!)
    def eval_3main_plus_2to3_parallel(df_23_top1, label):
        # Baseline 3-main active trades by buy_date
        base_by_d = {}
        for r in main_all.itertuples(index=False):
            base_by_d.setdefault(str(r.buy_date)[:10], []).append(float(r.net_ret))
        nav_base, pk_b, mdd_b = 1.0, 1.0, 0.0
        for d in sorted(base_by_d.keys()):
            r_d = float(np.mean(base_by_d[d]))
            nav_base *= (1.0 + r_d)
            pk_b = max(pk_b, nav_base)
            mdd_b = max(mdd_b, (pk_b - nav_base) / pk_b)

        comb_by_d = {k: list(v) for k, v in base_by_d.items()}
        for r in df_23_top1.itertuples(index=False):
            comb_by_d.setdefault(str(r.buy_date)[:10], []).append(float(r.net_ret))
        nav_c, pk_c, mdd_c = 1.0, 1.0, 0.0
        for d in sorted(comb_by_d.keys()):
            r_d = float(np.mean(comb_by_d[d]))
            nav_c *= (1.0 + r_d)
            pk_c = max(pk_c, nav_c)
            mdd_c = max(mdd_c, (pk_c - nav_c) / pk_c)
        return {
            "label": label,
            "base_3main_days": len(base_by_d),
            "base_3main_nav": round(nav_base, 3),
            "base_3main_mdd": round(mdd_b * 100, 2),
            "plus_2to3_days": len(comb_by_d),
            "plus_2to3_nav": round(nav_c, 3),
            "plus_2to3_mdd": round(mdd_c * 100, 2),
            "nav_lift_ratio": round(nav_c / max(1e-9, nav_base), 3),
        }

    # Test on V1_sc>=100 and V1_sc>=108 (with F30 exit)
    f31_res = {
        "main_ledger_counts": {"1to2": len(l1), "3to4": len(l34), "high": len(lh), "any_buy_dates": len(any_buy_dates), "occ_inclusive_days": len(occ_inclusive)},
        "experiments": [],
    }
    main_trades_list = [
        {"buy_date": str(r.buy_date)[:10], "exit_date": str(r.exit_date)[:10], "net_ret": float(r.net_ret), "prio": 0}
        for r in main_all.itertuples(index=False)
    ]
    base_comb_ss = eval_combined_nav(main_trades_list)
    f31_res["base_3main_single_slot"] = base_comb_ss
    print(f"  [三大主力底座] 1to2={len(l1)}笔, 3to4={len(l34)}笔, high={len(lh)}笔 | 买日并集={len(any_buy_dates)}天 | 持仓占用={len(occ_inclusive)}天 | 3主力单仓={base_comb_ss}")

    for p_name, p_mask in [("V1_sc>=100", hi_mask_100), ("V1_sc>=108", hi_mask_108)]:
        cand_23 = pick_daily_top1(df[p_mask & df["net_ret"].notna()], "sc_v1")
        for gate_name, gate_mask in [
            ("0_全量二进三(不设空仓门)", pd.Series(True, index=cand_23.index)),
            ("1_三大主力当日均未开仓(not in any_buy_dates)", ~cand_23["buy_date"].isin(any_buy_dates)),
            ("2_三大主力完全空槽日(not in occ_inclusive)", ~cand_23["buy_date"].isin(occ_inclusive)),
            ("3_三大主力非持仓且不跨占用(strict_slot)", ~cand_23["buy_date"].isin(occ_inclusive)),
        ]:
            sub_g = cand_23[gate_mask].copy()
            m_g = eval_factor_slice(sub_g, "net_ret", "exit_date", "sc_v1", base_mean=0.0)
            # Strict non-overlapping incremental single-slot with 3-main
            # If gate_name == 3_..., only take 2to3 when neither buy_date nor exit_date collides with main_trades? No, single-slot simulation naturally enforces non-overlap when mains have higher priority on buy_date, OR mains block if 2to3 is open; let's measure pure additive incremental trades that do NOT block any main trade!
            if "完全空槽" in gate_name or "strict_slot" in gate_name:
                # Filter 2to3 trades whose [buy_date, exit_date] doesn't collide with any main buy_date if strict_slot
                if "strict_slot" in gate_name:
                    keep = []
                    for r in sub_g.itertuples(index=False):
                        bd_s, ed_s = str(r.buy_date)[:10], str(r.exit_date)[:10]
                        collides = any(bd_s < mbd <= ed_s for mbd in any_buy_dates)
                        keep.append(not collides)
                    sub_g = sub_g[keep].copy()
                    m_g = eval_factor_slice(sub_g, "net_ret", "exit_date", "sc_v1", base_mean=0.0)
            par_stats = eval_3main_plus_2to3_parallel(sub_g, f"{p_name}_{gate_name}")
            comb_with_23 = eval_combined_nav(
                main_trades_list + [
                    {"buy_date": str(r.buy_date)[:10], "exit_date": str(r.exit_date)[:10], "net_ret": float(r.net_ret), "prio": 1}
                    for r in sub_g.itertuples(index=False)
                ]
            )
            exp_rec = {
                "pool": p_name,
                "gate": gate_name,
                "inc_raw_n": m_g["n_raw"],
                "inc_ss_n": m_g["ss_n"],
                "inc_ss_wr": m_g["ss_wr"],
                "inc_ss_payoff": m_g["ss_payoff"],
                "inc_ss_avg": m_g["avg_ret"],
                "inc_ss_nav": m_g["ss_nav"],
                "comb_ss": comb_with_23,
                "parallel_compounding": par_stats,
            }
            f31_res["experiments"].append(exp_rec)
            record_factor_row(csv_rows, "F31", f"补缺位门_{p_name}", gate_name, sub_g, base_mean=0.0)
            print(
                f"  [{p_name} | {gate_name:36s}] 增量单仓={m_g['ss_n']:3d}笔 WR={m_g['ss_wr']:4.1f}% PO={m_g['ss_payoff']:4.2f} "
                f"增量NAV={m_g['ss_nav']:5.2f}x | 三主力单仓合成:{base_comb_ss['nav']:.2f}x->{comb_with_23['nav']:.2f}x "
                f"| 并行日复合:{par_stats['base_3main_nav']:.2f}x->{par_stats['plus_2to3_nav']:.2f}x ({par_stats['nav_lift_ratio']:.2f}x)"
            )
    summary["factors"]["F31"] = f31_res

    # =========================================================================
    # F32: 未封三板弱持仓遇次日三进四 >=98分高确信信号时 09:25 腾笼换鸟
    # =========================================================================
    print("\n=== F32: 未封三板弱持仓遇次日三进四>=98分 09:25腾笼换鸟 ===")
    df34 = pd.read_parquet(f"{AST2}/data_5y/cand_3to4_enriched54.parquet")
    df34["v34_score"] = [score_single_3to4_row(row)["score"] for row in df34.to_dict("records")]
    df34_hc = df34[df34["v34_score"] >= 98].sort_values(["buy_date", "v34_score", "open_pct"], ascending=[True, False, False])
    # Map each buy_date to its >=98 3to4 candidate(s) and check 5m touch65_1130 fillability
    hc34_dates_signal = set(df34_hc["buy_date"].astype(str).str[:10])
    # Also simulate exact 3to4 >=98 trade for each date
    hc34_best_trade = {}
    for bd34, g34 in df34_hc.groupby("buy_date", sort=True):
        bd_s = str(bd34)[:10]
        for r34 in g34.itertuples(index=False):
            c34 = str(r34.code).zfill(6)
            cb34 = cb_map.get(c34)
            p34 = cb34["date_to_pos"].get(bd_s, -1) if cb34 else -1
            if not cb34 or p34 < 0:
                continue
            bpx34, bhh34 = sim_buy_5m(c34, bd_s, cb34, p34, bars_5m, "touch65_1130")
            if bpx34 is None:
                continue
            ex34, spx34, adjs34, hb34, shh34 = sim_exit_5m(
                c34, cb34, p34, bars_5m, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True
            )
            nr34 = (spx34 * adjs34) / (bpx34 * float(cb34["adjf"][p34])) * (1.0 - FEE) - 1.0
            hc34_best_trade[bd_s] = {
                "code": c34, "name": r34.name, "buy_date": bd_s, "exit_date": ex34,
                "net_ret": float(nr34), "v34_score": int(r34.v34_score),
            }
            break

    f32_res = {"hc34_signal_days": len(hc34_dates_signal), "hc34_filled_days": len(hc34_best_trade), "pools": {}}
    for p_name, p_mask in [("V1_sc>=100", hi_mask_100), ("清洁非一字池", df.index.isin(pool.index))]:
        # Examine all 2-to-3 unsealed Day3 positions under A_reb2 vs C1_f30_pm
        sub23 = df[p_mask & (~df["sealed_3b_sim"]) & df["net_ret"].notna()].copy()
        tr_reb2_sub = sim_pool_for_mode(sub23, cb_map, bars_5m, "open", "A_reb2_noimm")
        sub23["ret_reb2"] = [x["net_ret"] if x else np.nan for x in tr_reb2_sub]
        swap_rows = []
        for idx_s, r in enumerate(sub23.itertuples(index=False)):
            c6, bd = str(r.code).zfill(6), str(r.buy_date)
            cb = cb_map[c6]
            pos = cb["date_to_pos"][bd]
            if pos + 1 >= len(cb["dts"]):
                continue
            d4_dt = cb["dts"][pos + 1]
            if d4_dt in hc34_dates_signal and not bool(cb["is_yizi_dt"][pos + 1]):
                op3 = float(cb["open"][pos])
                op4 = float(cb["open"][pos + 1])
                ret_open4 = (op4 * float(cb["adjf"][pos + 1])) / (op3 * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
                hc_tr = hc34_best_trade.get(d4_dt)
                swap_rows.append({
                    "c6": c6, "buy_date": bd, "d4_dt": d4_dt,
                    "ret_hold_f30": float(r.net_ret),
                    "ret_hold_reb2": float(r.ret_reb2) if pd.notna(r.ret_reb2) else float(r.net_ret),
                    "ret_0925_swap": float(ret_open4),
                    "hc34_filled": hc_tr is not None,
                    "hc34_ret": float(hc_tr["net_ret"]) if hc_tr else np.nan,
                    "comb_swap_and_3to4": ((1.0 + ret_open4) * (1.0 + hc_tr["net_ret"]) - 1.0) if hc_tr else ret_open4,
                })
        sdf = pd.DataFrame(swap_rows)
        if not sdf.empty:
            stat = {
                "n_unsealed_2to3_total": int(len(sub23)),
                "n_collide_hc34_signal": int(len(sdf)),
                "n_hc34_filled": int(sdf["hc34_filled"].sum()),
                "hold_f30_avg_pct": round(float(sdf["ret_hold_f30"].mean() * 100), 2),
                "hold_reb2_avg_pct": round(float(sdf["ret_hold_reb2"].mean() * 100), 2),
                "cut_0925_avg_pct": round(float(sdf["ret_0925_swap"].mean() * 100), 2),
                "hc34_filled_avg_pct": round(float(sdf.loc[sdf["hc34_filled"], "hc34_ret"].mean() * 100), 2) if sdf["hc34_filled"].any() else 0.0,
                "comb_swap_3to4_avg_pct": round(float(sdf["comb_swap_and_3to4"].mean() * 100), 2),
                "comb_hold_miss_3to4_avg_pct": round(float(sdf["ret_hold_f30"].mean() * 100), 2),
            }
        else:
            stat = {"n_unsealed_2to3_total": int(len(sub23)), "n_collide_hc34_signal": 0}
        f32_res["pools"][p_name] = stat
        print(f"  [{p_name}] {stat}")
    summary["factors"]["F32"] = f32_res

    # Save CSV & JSON
    out_csv = f"{OUT_DIR}/b4_2to3_right_genes_and_handoff_F19_F34.csv"
    out_json = f"{OUT_DIR}/b4_summary.json"
    pd.DataFrame(csv_rows).to_csv(out_csv, index=False, encoding="utf-8-sig")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n[B4 DONE] Saved CSV ({len(csv_rows)} rows) -> {out_csv}")
    print(f"[B4 DONE] Saved JSON -> {out_json}")
    print(f"[B4 DONE] Elapsed: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

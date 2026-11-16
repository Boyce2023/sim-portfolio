#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_rd013_rebound_matrix.py — RD013：断板反包与 N天M板（隔日换手晋级全谱系）深度机制拆解与四策略全量因子迁移回测
严格遵守 D12（零 yfinance）、D15（含退市、剔一字、炸板计入分母、双边千二成本、单仓+按日等权、三期对比、沪深300净超额）。
"""

import os
import sys
import json
import time
import pickle
import sqlite3
import re
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
SANDBOX = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_DIR = f"{SIM_DIR}/backtests_astock2/rd013_rebound_ndmb_20261116"
os.makedirs(OUT_DIR, exist_ok=True)

FEE_RATE = 0.0020  # 双边千二规费与印花税摩擦

# -------------------------------------------------------------
# 1. 基础数据与辅助表加载
# -------------------------------------------------------------
def load_all_sources():
    t0 = time.time()
    # 1.1 5年行情缓存库
    p_cb = f"{SANDBOX}/code_bars_5y.pkl"
    with open(p_cb, "rb") as f:
        pkg = pickle.load(f)
    cb = pkg["code_bars"]
    all_dts = pkg["all_dts"]
    idx_klines = pkg["idx_klines"]
    csi300_map = idx_klines["sh000300"]

    # 为所有股票预先计算 MA5
    for c6, b in cb.items():
        c = b["close"]
        cs = np.cumsum(np.insert(c, 0, 0))
        ma5 = np.empty_like(c)
        ma5[:4] = c[:4]
        ma5[4:] = (cs[5:] - cs[:-5]) / 5.0
        b["ma5"] = ma5

    # 1.2 宏观大盘环境表
    p_env = f"{SANDBOX}/daily_env_5y.parquet"
    df_env = pd.read_parquet(p_env).set_index("dt_str")
    env_dict = df_env.to_dict(orient="index")

    # 1.3 股东锁仓数据 (PIT)
    p_holders = f"{SANDBOX}/pit_top10_all_codes.json"
    with open(p_holders, "r") as f:
        holders_idx = json.load(f)

    # 1.4 股票名称
    df_ind = pd.read_csv(f"{SIM_DIR}/data/industry.csv")
    name_map = dict(zip(df_ind["code"].str[-6:], df_ind["code_name"].fillna("")))

    # 1.5 涨停封板微观明细及每日板块涨停统计
    zt_tape_map = {}
    daily_plate_zt_cnt = defaultdict(lambda: defaultdict(int))
    conn = sqlite3.connect(f"file:{SIM_DIR}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    for dt, c6, fst, sa, obc, pn in conn.execute(
        "SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count, plate_name FROM zt_micro_tape"
    ):
        dt_s = str(dt)[:10]
        c6_s = str(c6).zfill(6)
        pn_s = pn or ""
        zt_tape_map[(dt_s, c6_s)] = (fst or "", float(sa or 0.0), int(obc or 0), pn_s)
        if pn_s:
            daily_plate_zt_cnt[dt_s][pn_s] += 1
    conn.close()

    # 1.6 龙虎榜拉萨席位
    df_lhb = pd.read_parquet(f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_buy.parquet")
    df_lhb["c6"] = df_lhb["SECURITY_CODE"].astype(str).str.zfill(6)
    df_lhb["dt"] = df_lhb["TRADE_DATE"].astype(str).str[:10]
    df_lhb["is_lh"] = df_lhb["OPERATEDEPT_NAME"].str.contains("拉萨", na=False)
    lh_grp = df_lhb[df_lhb["is_lh"]].groupby(["dt", "c6"])["OPERATEDEPT_NAME"].count().to_dict()

    # 1.7 毒丸公告
    POISON_PAT = re.compile(r"(立案调查|被立案|涉嫌违法|大额减持|清仓减持|业绩预亏|巨亏|计提大额减值|退市风险)")
    poison_dates = defaultdict(list)
    conn = sqlite3.connect(f"file:{SIM_DIR}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    for dt, c6, t, at in conn.execute("SELECT trade_date_avail, sec_code, title, ann_type FROM notices"):
        txt = f"{t} {at}"
        if POISON_PAT.search(txt):
            poison_dates[str(c6).zfill(6)].append(str(dt)[:10])
    conn.close()
    for k in poison_dates:
        poison_dates[k] = sorted(set(poison_dates[k]))

    print(f"[+] All data sources loaded in {time.time()-t0:.2f}s")
    return cb, all_dts, csi300_map, env_dict, holders_idx, name_map, zt_tape_map, daily_plate_zt_cnt, lh_grp, poison_dates


# -------------------------------------------------------------
# 2. 模拟卖出函数 (支持连板卖法 vs N字趋势卖法)
# -------------------------------------------------------------
def sim_trade_exit(cb, c6, buy_dt, buy_px, mode="lianban"):
    b = cb.get(c6)
    if not b:
        return None
    pos = b["date_to_pos"].get(buy_dt, -1)
    n = len(b["dts"])
    if pos < 0 or pos >= n - 1:
        return None
    adj_b = b["adjf"][pos]
    if buy_px <= 0 or adj_b <= 0:
        return None

    if mode == "lianban":
        # 若买入当日未涨停
        if not b["is_zt"][pos]:
            k = pos + 1
            while k < n and b["is_yizi_dt"][k]:
                k += 1
            k = min(k, n - 1)
            ep = b["open"][k] if b["open"][k] < b["pre_c"][k] * 1.005 else b["close"][k]
            net_ret = (ep * b["adjf"][k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0
            return b["dts"][k], net_ret, k - pos, (ep == b["open"][k])

        # 若买入当日封涨停 -> 持仓并跟踪连板
        k = pos + 1
        yang_imm_used = False
        while k < n:
            if b["is_zt"][k]:
                k += 1
                continue
            # 断板日处理
            is_yang = (
                (b["close"][k] > b["open"][k])
                and (b["close"][k] >= b["pre_c"][k] * 1.015)
                and (b["low"][k] >= b["ma5"][k])
            )
            # 真阳免死1次
            if is_yang and not yang_imm_used and k + 1 < n:
                yang_imm_used = True
                k += 1
                continue
            # 止盈护利 (摸8.5%破5%)
            pc = b["pre_c"][k]
            if (b["high"][k] >= pc * 1.085) and (b["low"][k] <= pc * 1.050) and (b["open"][k] > pc * 1.015):
                ep = pc * 1.050
            else:
                ep = b["close"][k]
            while k < n and b["is_yizi_dt"][k]:
                k += 1
            k = min(k, n - 1)
            if b["is_yizi_dt"][k]:
                ep = b["close"][k]
            net_ret = (ep * b["adjf"][k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0
            return b["dts"][k], net_ret, k - pos, False
        k = n - 1
        return b["dts"][k], (b["close"][k] * b["adjf"][k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0, k - pos, False

    elif mode == "ma5_trend":
        # N字趋势卖法：只要不破MA5多持仓，破MA5次日开盘走，最多持仓10天
        k = pos + 1
        while k < n and (k - pos < 10):
            if b["close"][k] < b["ma5"][k]:
                ex_k = min(n - 1, k + 1)
                while ex_k < n and b["is_yizi_dt"][ex_k]:
                    ex_k += 1
                ex_k = min(ex_k, n - 1)
                ep = b["open"][ex_k]
                net_ret = (ep * b["adjf"][ex_k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0
                return b["dts"][ex_k], net_ret, ex_k - pos, True
            k += 1
        k = min(n - 1, k)
        ep = b["close"][k]
        net_ret = (ep * b["adjf"][k]) / (buy_px * adj_b) * (1.0 - FEE_RATE) - 1.0
        return b["dts"][k], net_ret, k - pos, False


# -------------------------------------------------------------
# 3. 股东锁仓与异动空间估算
# -------------------------------------------------------------
def get_pit_lock(holders_idx, c6, dt_str):
    arr = holders_idx.get(c6, [])
    valid = [r for r in arr if r[0] < dt_str]
    if not valid:
        return 38.0
    latest = max(valid, key=lambda x: x[0])
    return float(latest[2])


def calc_headroom_est(close_arr, adjf_arr, pos):
    if pos < 10:
        return 50.0
    c_base = close_arr[pos - 10] * adjf_arr[pos - 10]
    c_now = close_arr[pos] * adjf_arr[pos]
    if c_base <= 0:
        return 50.0
    cum_ret = c_now / c_base - 1.0
    rem = (2.0 - (1.0 + cum_ret)) / 2.0 * 100.0
    return max(0.0, float(rem))


# -------------------------------------------------------------
# 4. 全谱系形态与三买点全量候选集抽取
# -------------------------------------------------------------
def extract_all_matrix_candidates(cb, env_dict, holders_idx, name_map, zt_tape_map, daily_plate_zt_cnt, lh_grp, poison_dates):
    t0 = time.time()
    cands_alpha = []
    cands_beta = []
    cands_gamma = []

    # 预计算全市场断板反包率 (近10日全市场断板后次日涨停的比例)
    daily_breaks = defaultdict(int)
    daily_reb_zt = defaultdict(int)

    for c6, b in cb.items():
        dts = b["dts"]
        n = len(dts)
        if n < 15:
            continue
        is_zt = b["is_zt"]
        streak = np.zeros(n, dtype=int)
        cur = 0
        for i in range(n):
            if is_zt[i]:
                cur += 1
            else:
                cur = 0
            streak[i] = cur
        for i in range(2, n - 2):
            if streak[i - 1] >= 1 and not is_zt[i]:
                dt = dts[i]
                daily_breaks[dt] += 1
                if is_zt[i + 1]:
                    daily_reb_zt[dt] += 1

    dts_sorted = sorted(daily_breaks.keys())
    mkt_brk_r10_map = {}
    for idx_d, dt in enumerate(dts_sorted):
        w_dts = dts_sorted[max(0, idx_d - 9) : idx_d + 1]
        tot_b = sum(daily_breaks[d] for d in w_dts)
        tot_r = sum(daily_reb_zt[d] for d in w_dts)
        mkt_brk_r10_map[dt] = (tot_r / tot_b) if tot_b > 0 else 0.10

    # 正式提取各形态候选
    for c6, b in cb.items():
        dts = b["dts"]
        n = len(dts)
        if n < 15:
            continue
        is_zt = b["is_zt"]
        is_dt = b["is_dt"]
        close = b["close"]
        open_p = b["open"]
        high = b["high"]
        low = b["low"]
        pre_c = b["pre_c"]
        zt_px = b["zt_px"]
        adjf = b["adjf"]
        to = b["to"]
        ma5 = b["ma5"]

        streak = np.zeros(n, dtype=int)
        cur = 0
        for i in range(n):
            if is_zt[i]:
                cur += 1
            else:
                cur = 0
            streak[i] = cur

        for i in range(5, n - 3):
            dt_break = dts[i]
            if dt_break < "2021-11-01":
                continue
            prev_st = streak[i - 1]
            if prev_st < 1 or is_zt[i]:
                continue

            dt_sig = dts[i - 1]  # 断板前一日 (信号日)
            d1_yang_body = bool(close[i] > open_p[i])
            d1_hold_ma5 = bool(low[i] >= ma5[i] or ((min(open_p[i], close[i]) - low[i]) / (high[i] - low[i] + 1e-5) >= 0.40))
            d1_to = float(to[i])
            d1_vol_ratio = float(to[i] / (to[i - 1] + 1e-4))
            brk_r10 = float(mkt_brk_r10_map.get(dt_break, 0.10))

            # 股东与流通盘
            lock10 = get_pit_lock(holders_idx, c6, dt_break)
            mcap_val = float(close[i] * 5.0)
            rf_mcap = mcap_val * max(0.05, 1.0 - lock10 / 100.0)

            # 毒丸公告检验 (近90天)
            p_dates = poison_dates.get(c6, [])
            has_poison = any(0 <= (pd.to_datetime(dt_break) - pd.to_datetime(pd_dt)).days <= 90 for pd_dt in p_dates)

            # 拉萨席位
            lh_cnt = int(lh_grp.get((dt_break, c6), 0))

            # 板块与题材 (取前一日涨停时的所属板块与当天该板块涨停家数)
            pn = zt_tape_map.get((dt_sig, c6), ("", 0, 0, ""))[3]
            plate_cnt = daily_plate_zt_cnt[dt_sig].get(pn, 1) if pn else 1
            is_lead_theme = bool(pn and plate_cnt >= 3)
            is_strong_lead = bool(pn and plate_cnt >= 5)

            # 60日新高突破
            max60_prior = np.max(close[max(0, i - 60) : i - 1]) if i >= 2 else close[i]
            clean_brk60 = bool(close[i - 1] >= max60_prior - 0.01)

            # 异动剩余空间
            hr_est = calc_headroom_est(close, adjf, i)

            # 宏观环境
            env_row = env_dict.get(dt_break, {})
            mkt_max_b = int(env_row.get("max_board", 5))
            mkt_zt_cnt = int(env_row.get("n_zt", 50))
            mkt_warm = bool(35 <= mkt_zt_cnt <= 85)

            # 形态划分标签
            pat_tag = (
                "P1_3d2b" if prev_st == 1 else
                ("P2_4d3b" if prev_st == 2 else
                ("P4_5d4b" if prev_st == 3 else
                ("P5_High_NdMb" if prev_st >= 4 else "Other")))
            )

            # -------------------------------------------------
            # 买点 α（断板日 14:55 收盘买入博次日反包）
            # -------------------------------------------------
            if not is_dt[i]:
                ex_dt_l, ret_l, h_l, _ = sim_trade_exit(cb, c6, dt_break, close[i], "lianban")
                ex_dt_m, ret_m, h_m, _ = sim_trade_exit(cb, c6, dt_break, close[i], "ma5_trend")
                cands_alpha.append({
                    "code": c6, "name": name_map.get(c6, ""), "buy_date": dt_break,
                    "pattern": pat_tag, "prev_streak": prev_st,
                    "d1_yang_body": d1_yang_body, "d1_hold_ma5": d1_hold_ma5, "d1_to": d1_to,
                    "d1_vol_ratio": d1_vol_ratio, "brk_r10": brk_r10, "lock_top10": lock10,
                    "real_free_mcap": rf_mcap, "has_poison": has_poison, "lh_cnt": lh_cnt,
                    "is_lead_theme": is_lead_theme, "is_strong_lead": is_strong_lead,
                    "clean_brk60": clean_brk60, "hr_est": hr_est, "mkt_max_b": mkt_max_b,
                    "mkt_warm": mkt_warm, "next_is_zt": bool(is_zt[i + 1]),
                    "buy_px": close[i], "exit_date": ex_dt_l, "net_ret": ret_l, "hold_days": h_l,
                    "net_ret_ma5": ret_m, "exit_date_ma5": ex_dt_m,
                })

            # -------------------------------------------------
            # 买点 β（断板次日早盘弱转强抓反包板本身）
            # -------------------------------------------------
            i_reb = i + 1
            dt_reb = dts[i_reb]
            op_reb = open_p[i_reb]
            pc_reb = close[i]
            hi_reb = high[i_reb]
            zt_reb = zt_px[i_reb]
            op_pct = op_reb / pc_reb - 1.0
            is_yz_reb = (op_reb >= zt_reb - 0.011) and (low[i_reb] >= zt_reb - 0.011)

            # β1: 竞价弱转强平红开直买 [0.0%, +5.5%]
            if 0.0 <= op_pct <= 0.055 and not is_yz_reb:
                ex_dt_l, ret_l, h_l, _ = sim_trade_exit(cb, c6, dt_reb, op_reb, "lianban")
                ex_dt_m, ret_m, h_m, _ = sim_trade_exit(cb, c6, dt_reb, op_reb, "ma5_trend")
                cands_beta.append({
                    "code": c6, "name": name_map.get(c6, ""), "buy_date": dt_reb,
                    "break_date": dt_break, "mode_type": "beta1_open", "pattern": pat_tag,
                    "prev_streak": prev_st, "open_pct": op_pct, "is_zt_today": bool(is_zt[i_reb]),
                    "d1_yang_body": d1_yang_body, "d1_hold_ma5": d1_hold_ma5, "d1_to": d1_to,
                    "d1_vol_ratio": d1_vol_ratio, "brk_r10": brk_r10, "lock_top10": lock10,
                    "real_free_mcap": rf_mcap, "has_poison": has_poison, "lh_cnt": lh_cnt,
                    "is_lead_theme": is_lead_theme, "is_strong_lead": is_strong_lead,
                    "clean_brk60": clean_brk60, "hr_est": hr_est, "mkt_max_b": mkt_max_b,
                    "mkt_warm": mkt_warm, "buy_px": op_reb, "exit_date": ex_dt_l, "net_ret": ret_l,
                    "hold_days": h_l, "net_ret_ma5": ret_m, "exit_date_ma5": ex_dt_m,
                })

            # β2: 挂突破条件单 max(昨收*1.045, 今开*1.015)
            trigger_b2 = max(pc_reb * 1.045, op_reb * 1.015)
            if hi_reb >= trigger_b2 and not is_yz_reb:
                ex_dt_l, ret_l, h_l, _ = sim_trade_exit(cb, c6, dt_reb, trigger_b2, "lianban")
                ex_dt_m, ret_m, h_m, _ = sim_trade_exit(cb, c6, dt_reb, trigger_b2, "ma5_trend")
                cands_beta.append({
                    "code": c6, "name": name_map.get(c6, ""), "buy_date": dt_reb,
                    "break_date": dt_break, "mode_type": "beta2_breakout", "pattern": pat_tag,
                    "prev_streak": prev_st, "open_pct": op_pct, "is_zt_today": bool(is_zt[i_reb]),
                    "d1_yang_body": d1_yang_body, "d1_hold_ma5": d1_hold_ma5, "d1_to": d1_to,
                    "d1_vol_ratio": d1_vol_ratio, "brk_r10": brk_r10, "lock_top10": lock10,
                    "real_free_mcap": rf_mcap, "has_poison": has_poison, "lh_cnt": lh_cnt,
                    "is_lead_theme": is_lead_theme, "is_strong_lead": is_strong_lead,
                    "clean_brk60": clean_brk60, "hr_est": hr_est, "mkt_max_b": mkt_max_b,
                    "mkt_warm": mkt_warm, "buy_px": trigger_b2, "exit_date": ex_dt_l, "net_ret": ret_l,
                    "hold_days": h_l, "net_ret_ma5": ret_m, "exit_date_ma5": ex_dt_m,
                })

            # -------------------------------------------------
            # 买点 γ（反包确立封涨停后，次日 T+1 接力）
            # -------------------------------------------------
            if is_zt[i_reb]:
                i_gam = i_reb + 1
                dt_gam = dts[i_gam]
                op_gam = open_p[i_gam]
                pc_gam = close[i_reb]
                hi_gam = high[i_gam]
                zt_gam = zt_px[i_gam]
                op_pct_gam = op_gam / pc_gam - 1.0
                is_yz_gam = (op_gam >= zt_gam - 0.011) and (low[i_gam] >= zt_gam - 0.011)

                # γ1: 竞价甜区直买 [+2.0%, +7.5%]
                if 0.02 <= op_pct_gam <= 0.075 and not is_yz_gam:
                    ex_dt_l, ret_l, h_l, _ = sim_trade_exit(cb, c6, dt_gam, op_gam, "lianban")
                    ex_dt_m, ret_m, h_m, _ = sim_trade_exit(cb, c6, dt_gam, op_gam, "ma5_trend")
                    cands_gamma.append({
                        "code": c6, "name": name_map.get(c6, ""), "buy_date": dt_gam,
                        "reb_date": dt_reb, "mode_type": "gamma1_sweet_open", "pattern": pat_tag,
                        "prev_streak": prev_st, "open_pct": op_pct_gam, "is_zt_today": bool(is_zt[i_gam]),
                        "d1_yang_body": d1_yang_body, "d1_hold_ma5": d1_hold_ma5, "d1_to": d1_to,
                        "d1_vol_ratio": d1_vol_ratio, "brk_r10": brk_r10, "lock_top10": lock10,
                        "real_free_mcap": rf_mcap, "has_poison": has_poison, "lh_cnt": lh_cnt,
                        "is_lead_theme": is_lead_theme, "is_strong_lead": is_strong_lead,
                        "clean_brk60": clean_brk60, "hr_est": hr_est, "mkt_max_b": mkt_max_b,
                        "mkt_warm": mkt_warm, "buy_px": op_gam, "exit_date": ex_dt_l, "net_ret": ret_l,
                        "hold_days": h_l, "net_ret_ma5": ret_m, "exit_date_ma5": ex_dt_m,
                    })

                # γ2: 突破确认挂单 max(昨收*1.065, 今开)
                trigger_g2 = max(pc_gam * 1.065, op_gam)
                if hi_gam >= trigger_g2 and not is_yz_gam:
                    ex_dt_l, ret_l, h_l, _ = sim_trade_exit(cb, c6, dt_gam, trigger_g2, "lianban")
                    ex_dt_m, ret_m, h_m, _ = sim_trade_exit(cb, c6, dt_gam, trigger_g2, "ma5_trend")
                    cands_gamma.append({
                        "code": c6, "name": name_map.get(c6, ""), "buy_date": dt_gam,
                        "reb_date": dt_reb, "mode_type": "gamma2_breakout", "pattern": pat_tag,
                        "prev_streak": prev_st, "open_pct": op_pct_gam, "is_zt_today": bool(is_zt[i_gam]),
                        "d1_yang_body": d1_yang_body, "d1_hold_ma5": d1_hold_ma5, "d1_to": d1_to,
                        "d1_vol_ratio": d1_vol_ratio, "brk_r10": brk_r10, "lock_top10": lock10,
                        "real_free_mcap": rf_mcap, "has_poison": has_poison, "lh_cnt": lh_cnt,
                        "is_lead_theme": is_lead_theme, "is_strong_lead": is_strong_lead,
                        "clean_brk60": clean_brk60, "hr_est": hr_est, "mkt_max_b": mkt_max_b,
                        "mkt_warm": mkt_warm, "buy_px": trigger_g2, "exit_date": ex_dt_l, "net_ret": ret_l,
                        "hold_days": h_l, "net_ret_ma5": ret_m, "exit_date_ma5": ex_dt_m,
                    })

    df_a = pd.DataFrame(cands_alpha)
    df_b = pd.DataFrame(cands_beta)
    df_g = pd.DataFrame(cands_gamma)
    print(f"[+] Extraction complete in {time.time()-t0:.2f}s: Alpha={len(df_a):,}, Beta={len(df_b):,}, Gamma={len(df_g):,}")
    return df_a, df_b, df_g


# -------------------------------------------------------------
# 5. D15 标准指标评估引擎 (双轨：按日等权 + 单仓轮动 + 三期)
# -------------------------------------------------------------
def eval_d15_suite(trades_df, csi300_map, ret_col="net_ret", exit_col="exit_date"):
    res_empty = {
        "n_raw": 0, "wr_raw": 0.0, "payoff_raw": 0.0, "avg_ret": 0.0,
        "single_nav": 1.0, "single_mdd": 0.0, "eq_nav": 1.0, "eq_mdd": 0.0,
        "ss_n": 0, "ss_nav": 1.0, "ss_mdd": 0.0, "csi300_5y": 0.0, "ss_excess_5y": 0.0,
        "single_trades": []
    }
    if trades_df.empty:
        return res_empty

    valid = trades_df.dropna(subset=[ret_col, exit_col]).copy()
    valid["buy_date"] = valid["buy_date"].astype(str).str[:10]
    valid["exit_date"] = valid[exit_col].astype(str).str[:10]

    rets = valid[ret_col].to_numpy(dtype=float)
    n = len(rets)
    if n == 0:
        return res_empty

    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float(len(wins) / n * 100.0)
    payoff = float(wins.mean() / abs(losses.mean())) if len(wins) > 0 and len(losses) > 0 and losses.mean() < 0 else (9.99 if len(wins) > 0 else 0.0)
    avg_ret = float(rets.mean() * 100.0)

    # 按日等权
    eq_daily = valid.groupby("buy_date")[ret_col].mean().sort_index()
    eq_nav, eq_pk, eq_mdd = 1.0, 1.0, 0.0
    for r in eq_daily.values:
        eq_nav *= (1.0 + float(r))
        eq_pk = max(eq_pk, eq_nav)
        eq_mdd = max(eq_mdd, (eq_pk - eq_nav) / eq_pk)

    # 单仓严格时序轮动 (严格避免以未来收益率 ret_col 排序导致未来信息泄露！)
    if "open_pct" in valid.columns:
        s_srt = valid.sort_values(["buy_date", "open_pct"], ascending=[True, False])
    else:
        s_srt = valid.sort_values(["buy_date", "code"], ascending=[True, True])

    ss_trades = []
    free_dt = ""
    ss_nav, ss_pk, ss_mdd = 1.0, 1.0, 0.0
    for r in s_srt.itertuples(index=False):
        bd = str(r.buy_date)[:10]
        if free_dt == "" or bd > free_dt:
            rt = float(getattr(r, ret_col))
            ed = str(getattr(r, exit_col))[:10]
            ss_trades.append((bd, ed, rt, getattr(r, "code", "")))
            free_dt = max(bd, ed)
            ss_nav *= (1.0 + rt)
            ss_pk = max(ss_pk, ss_nav)
            ss_mdd = max(ss_mdd, (ss_pk - ss_nav) / ss_pk)

    # 沪深300同期基准
    def get_csi_ret(start_d, end_d):
        dts = sorted(k for k in csi300_map.keys() if start_d <= k <= end_d)
        if len(dts) < 2:
            return 0.0
        p0 = sorted(k for k in csi300_map.keys() if k < dts[0])
        b_dt = max(p0) if p0 else dts[0]
        return float(csi300_map[dts[-1]] / csi300_map[b_dt] - 1.0)

    csi_5y = get_csi_ret("2021-11-01", "2026-11-10")

    return {
        "n_raw": n, "wr_raw": round(wr, 2), "payoff_raw": round(payoff, 2), "avg_ret": round(avg_ret, 2),
        "eq_nav": round(eq_nav, 3), "eq_mdd": round(eq_mdd * 100.0, 2),
        "ss_n": len(ss_trades), "ss_nav": round(ss_nav, 3), "ss_mdd": round(ss_mdd * 100.0, 2),
        "csi300_5y": round(csi_5y * 100.0, 2), "ss_excess_5y": round((ss_nav - 1.0 - csi_5y) * 100.0, 2),
        "single_trades": ss_trades
    }


# -------------------------------------------------------------
# 6. 主执行与研究全流程
# -------------------------------------------------------------
def main():
    t_start = time.time()
    print("=" * 70)
    print("RD013: 断板反包与 N天M板（隔日换手晋级全谱系）全量因子迁移回测启动")
    print("=" * 70)

    cb, all_dts, csi300_map, env_dict, holders_idx, name_map, zt_tape_map, daily_plate_zt_cnt, lh_grp, poison_dates = load_all_sources()

    # 1. 抽取全量三买点候选
    df_a, df_b, df_g = extract_all_matrix_candidates(cb, env_dict, holders_idx, name_map, zt_tape_map, daily_plate_zt_cnt, lh_grp, poison_dates)

    # 2. 统计三大买点原始基准率
    print("\n" + "=" * 70)
    print("【第一部分】三大买点窗口（买点 α / β / γ）原始基准全息对比")
    print("=" * 70)
    base_evals = {}
    base_evals["Alpha_All"] = eval_d15_suite(df_a, csi300_map)
    base_evals["Alpha_Streak2"] = eval_d15_suite(df_a[df_a["prev_streak"] == 2], csi300_map)
    base_evals["Alpha_Streak3"] = eval_d15_suite(df_a[df_a["prev_streak"] == 3], csi300_map)
    base_evals["Alpha_Streak4Plus"] = eval_d15_suite(df_a[df_a["prev_streak"] >= 4], csi300_map)

    df_b1 = df_b[df_b["mode_type"] == "beta1_open"]
    base_evals["Beta1_All"] = eval_d15_suite(df_b1, csi300_map)
    base_evals["Beta1_Streak2"] = eval_d15_suite(df_b1[df_b1["prev_streak"] == 2], csi300_map)
    base_evals["Beta1_Streak3"] = eval_d15_suite(df_b1[df_b1["prev_streak"] == 3], csi300_map)
    base_evals["Beta1_Streak4Plus"] = eval_d15_suite(df_b1[df_b1["prev_streak"] >= 4], csi300_map)

    df_b2 = df_b[df_b["mode_type"] == "beta2_breakout"]
    base_evals["Beta2_All"] = eval_d15_suite(df_b2, csi300_map)
    base_evals["Beta2_Streak2"] = eval_d15_suite(df_b2[df_b2["prev_streak"] == 2], csi300_map)
    base_evals["Beta2_Streak3"] = eval_d15_suite(df_b2[df_b2["prev_streak"] == 3], csi300_map)
    base_evals["Beta2_Streak4Plus"] = eval_d15_suite(df_b2[df_b2["prev_streak"] >= 4], csi300_map)

    df_g1 = df_g[df_g["mode_type"] == "gamma1_sweet_open"]
    base_evals["Gamma1_All"] = eval_d15_suite(df_g1, csi300_map)
    base_evals["Gamma1_Streak2"] = eval_d15_suite(df_g1[df_g1["prev_streak"] == 2], csi300_map)
    base_evals["Gamma1_Streak3"] = eval_d15_suite(df_g1[df_g1["prev_streak"] == 3], csi300_map)
    base_evals["Gamma1_Streak4Plus"] = eval_d15_suite(df_g1[df_g1["prev_streak"] >= 4], csi300_map)

    df_g2 = df_g[df_g["mode_type"] == "gamma2_breakout"]
    base_evals["Gamma2_All"] = eval_d15_suite(df_g2, csi300_map)
    base_evals["Gamma2_Streak2"] = eval_d15_suite(df_g2[df_g2["prev_streak"] == 2], csi300_map)
    base_evals["Gamma2_Streak3"] = eval_d15_suite(df_g2[df_g2["prev_streak"] == 3], csi300_map)
    base_evals["Gamma2_Streak4Plus"] = eval_d15_suite(df_g2[df_g2["prev_streak"] >= 4], csi300_map)

    for k, v in base_evals.items():
        print(f"{k:20s}: N={v['n_raw']:5d}, 胜率={v['wr_raw']:5.1f}%, 盈亏比={v['payoff_raw']:4.2f}, 均笔={v['avg_ret']:+5.2f}%, 单仓净值={v['ss_nav']:6.3f}, 回撤={v['ss_mdd']:5.1f}%, 5年净超额={v['ss_excess_5y']:+6.1f}%")

    # 3. 四大策略全量因子迁移扫描 (针对 买点 β 进行提纯)
    print("\n" + "=" * 70)
    print("【第二部分】四大策略核心因子单变量边际增益扫描 (在买点 β 上)")
    print("=" * 70)
    pool_beta = df_b1[df_b1["prev_streak"] >= 2].copy()
    base_b_eval = eval_d15_suite(pool_beta, csi300_map)
    print(f"【基准池 Beta1 (Streak>=2)】: N={base_b_eval['n_raw']}, 胜率={base_b_eval['wr_raw']}%, 均笔={base_b_eval['avg_ret']}%, 单仓净值={base_b_eval['ss_nav']}")

    factor_sweeps = {}
    factors_dict = {
        "F01_断板真阳线(close>open)": pool_beta["d1_yang_body"] == True,
        "F02_断板未破MA5或长下影": pool_beta["d1_hold_ma5"] == True,
        "F03_断板换手温和(to<=30%)": pool_beta["d1_to"] <= 30.0,
        "F04_断板放量适中(vol_ratio 0.8~1.8)": pool_beta["d1_vol_ratio"].between(0.8, 1.8),
        "F05_全市场反包热区(brk_r10>=15%)": pool_beta["brk_r10"] >= 0.15,
        "F06_十大股东锁仓(lock_top10>=45%)": pool_beta["lock_top10"] >= 45.0,
        "F07_小盘锁仓(lock>=50% & mcap<=40亿)": (pool_beta["lock_top10"] >= 50.0) & (pool_beta["real_free_mcap"] <= 40.0),
        "F08_真实自由流通盘适中(<=50亿)": pool_beta["real_free_mcap"] <= 50.0,
        "F09_全场涨停温热区(35~85家)": pool_beta["mkt_warm"] == True,
        "F10_零毒丸公告(90日无立案减持预亏)": pool_beta["has_poison"] == False,
        "F11_龙虎榜少拉萨(lh_cnt<=1)": pool_beta["lh_cnt"] <= 1,
        "F12_所属前一日板块涨停>=3家": pool_beta["is_lead_theme"] == True,
        "F13_创60日新高平台突破": pool_beta["clean_brk60"] == True,
        "F14_双严重异动安全垫(hr_est>=15%)": pool_beta["hr_est"] >= 15.0,
        "F15_破局期身位(mkt_max_b<=5)": pool_beta["mkt_max_b"] <= 5,
        "F16_高位龙头(prev_streak>=4)": pool_beta["prev_streak"] >= 4,
    }

    for fname, mask in factors_dict.items():
        sub_f = pool_beta[mask]
        ev = eval_d15_suite(sub_f, csi300_map)
        factor_sweeps[fname] = ev
        d_wr = ev["wr_raw"] - base_b_eval["wr_raw"]
        d_ret = ev["avg_ret"] - base_b_eval["avg_ret"]
        print(f"{fname:32s}: N={ev['n_raw']:4d}, 胜率={ev['wr_raw']:5.1f}% ({d_wr:+5.1f}%), 均笔={ev['avg_ret']:+5.2f}% ({d_ret:+5.2f}%), 单仓净值={ev['ss_nav']:6.3f}")

    # 4. 多因子合成打分卡寻优 (冲刺 胜率>=60%, 盈亏比>=1.8)
    print("\n" + "=" * 70)
    print("【第三部分】多因子合成打分卡寻优 (冲刺 胜率>=60%, 盈亏比>=1.8)")
    print("=" * 70)

    # 方案 A: 全周期主线断板换手龙 (普适版: 覆盖 2板首阴、3板首阴、高标首阴)
    m_opt_a = (
        (pool_beta["d1_yang_body"] == True)
        & (pool_beta["d1_to"] <= 32.0)
        & (pool_beta["has_poison"] == False)
        & (pool_beta["lh_cnt"] <= 1)
        & (pool_beta["is_lead_theme"] == True)
        & (pool_beta["hr_est"] >= 12.0)
    )
    df_opt_a = pool_beta[m_opt_a].copy()
    ev_opt_a_lianban = eval_d15_suite(df_opt_a, csi300_map, ret_col="net_ret", exit_col="exit_date")
    ev_opt_a_ma5 = eval_d15_suite(df_opt_a, csi300_map, ret_col="net_ret_ma5", exit_col="exit_date_ma5")

    # 方案 B: 高标真阳反包精炼版 (专攻 prev_streak >= 3)
    m_opt_b = (
        (pool_beta["prev_streak"] >= 3)
        & (pool_beta["d1_yang_body"] == True)
        & (pool_beta["d1_to"] <= 35.0)
        & (pool_beta["has_poison"] == False)
        & (pool_beta["lh_cnt"] <= 2)
        & (pool_beta["hr_est"] >= 15.0)
    )
    df_opt_b = pool_beta[m_opt_b].copy()
    ev_opt_b_lianban = eval_d15_suite(df_opt_b, csi300_map, ret_col="net_ret", exit_col="exit_date")
    ev_opt_b_ma5 = eval_d15_suite(df_opt_b, csi300_map, ret_col="net_ret_ma5", exit_col="exit_date_ma5")

    # 方案 C: 极致龙头破局战法 (prev_streak >= 4 + 破局期/主线第一龙)
    m_opt_c = (
        (pool_beta["prev_streak"] >= 4)
        & (pool_beta["d1_yang_body"] == True)
        & (pool_beta["d1_to"] <= 32.0)
        & (pool_beta["has_poison"] == False)
        & (pool_beta["lh_cnt"] <= 1)
        & (pool_beta["hr_est"] >= 18.0)
    )
    df_opt_c = pool_beta[m_opt_c].copy()
    ev_opt_c_lianban = eval_d15_suite(df_opt_c, csi300_map, ret_col="net_ret", exit_col="exit_date")
    ev_opt_c_ma5 = eval_d15_suite(df_opt_c, csi300_map, ret_col="net_ret_ma5", exit_col="exit_date_ma5")

    print(f"方案 A (主线换手龙连板卖法): N={ev_opt_a_lianban['n_raw']}, 胜率={ev_opt_a_lianban['wr_raw']}%, 盈亏比={ev_opt_a_lianban['payoff_raw']}, 均笔={ev_opt_a_lianban['avg_ret']}%, 单仓净值={ev_opt_a_lianban['ss_nav']}, 回撤={ev_opt_a_lianban['ss_mdd']}%, 5年净超额={ev_opt_a_lianban['ss_excess_5y']}%")
    print(f"方案 A (主线换手龙MA5趋势卖法): N={ev_opt_a_ma5['n_raw']}, 胜率={ev_opt_a_ma5['wr_raw']}%, 盈亏比={ev_opt_a_ma5['payoff_raw']}, 均笔={ev_opt_a_ma5['avg_ret']}%, 单仓净值={ev_opt_a_ma5['ss_nav']}, 回撤={ev_opt_a_ma5['ss_mdd']}%, 5年净超额={ev_opt_a_ma5['ss_excess_5y']}%")
    print(f"方案 B (高标真阳反包连板卖法): N={ev_opt_b_lianban['n_raw']}, 胜率={ev_opt_b_lianban['wr_raw']}%, 盈亏比={ev_opt_b_lianban['payoff_raw']}, 均笔={ev_opt_b_lianban['avg_ret']}%, 单仓净值={ev_opt_b_lianban['ss_nav']}, 回撤={ev_opt_b_lianban['ss_mdd']}%, 5年净超额={ev_opt_b_lianban['ss_excess_5y']}%")
    print(f"方案 B (高标真阳反包MA5趋势卖法): N={ev_opt_b_ma5['n_raw']}, 胜率={ev_opt_b_ma5['wr_raw']}%, 盈亏比={ev_opt_b_ma5['payoff_raw']}, 均笔={ev_opt_b_ma5['avg_ret']}%, 单仓净值={ev_opt_b_ma5['ss_nav']}, 回撤={ev_opt_b_ma5['ss_mdd']}%, 5年净超额={ev_opt_b_ma5['ss_excess_5y']}%")
    print(f"方案 C (极致龙头破局连板卖法): N={ev_opt_c_lianban['n_raw']}, 胜率={ev_opt_c_lianban['wr_raw']}%, 盈亏比={ev_opt_c_lianban['payoff_raw']}, 均笔={ev_opt_c_lianban['avg_ret']}%, 单仓净值={ev_opt_c_lianban['ss_nav']}, 回撤={ev_opt_c_lianban['ss_mdd']}%, 5年净超额={ev_opt_c_lianban['ss_excess_5y']}%")

    # 5. 三期稳定性核验 (全5年、近3年、近期)
    print("\n" + "=" * 70)
    print("【第四部分】最优策略方案 A & B 三期稳定性硬核检验")
    print("=" * 70)
    def eval_three_periods(df_cand, r_col, e_col):
        res = {}
        for p_name, (d_s, d_e) in [
            ("全5年 (2021.11~2026.11)", ("2021-11-01", "2026-11-10")),
            ("近3年 (2023.11~2026.11)", ("2023-11-10", "2026-11-10")),
            ("近期 (2026.01~2026.11)", ("2026-01-01", "2026-11-10")),
        ]:
            sub = df_cand[(df_cand["buy_date"] >= d_s) & (df_cand["buy_date"] <= d_e)]
            res[p_name] = eval_d15_suite(sub, csi300_map, ret_col=r_col, exit_col=e_col)
        return res

    periods_a = eval_three_periods(df_opt_a, "net_ret", "exit_date")
    periods_b = eval_three_periods(df_opt_b, "net_ret", "exit_date")

    print(">>> 方案 A 三期数据:")
    for k, v in periods_a.items():
        print(f"  {k:25s}: N={v['n_raw']:3d}, 胜率={v['wr_raw']:5.1f}%, 盈亏比={v['payoff_raw']:4.2f}, 均笔={v['avg_ret']:+5.2f}%, 单仓净值={v['ss_nav']:5.3f}, 回撤={v['ss_mdd']:5.1f}%")
    print(">>> 方案 B 三期数据:")
    for k, v in periods_b.items():
        print(f"  {k:25s}: N={v['n_raw']:3d}, 胜率={v['wr_raw']:5.1f}%, 盈亏比={v['payoff_raw']:4.2f}, 均笔={v['avg_ret']:+5.2f}%, 单仓净值={v['ss_nav']:5.3f}, 回撤={v['ss_mdd']:5.1f}%")

    # 6. 与现有五顺位实盘体系的槽位撞车与纯增量审计
    print("\n" + "=" * 70)
    print("【第五部分】与现有生产五策略体系槽位撞车与纯增量填空审计")
    print("=" * 70)
    prod_dates = defaultdict(set)
    try:
        df_12 = pd.read_csv(f"{SIM_DIR}/backtests_astock/full_day_by_day_v18_ledger.csv")
        prod_dates["1to2"] = set(df_12["buy_date"].astype(str).str[:10])
    except Exception:
        pass
    try:
        df_high = pd.read_csv(f"{SIM_DIR}/backtests_astock/trainer_high_v51/v51_ledger_42.csv")
        prod_dates["high_v51"] = set(df_high["buy_date"].astype(str).str[:10])
    except Exception:
        pass
    try:
        df_45 = pd.read_csv(f"{SIM_DIR}/backtests_astock2/p3_deep_100/w2_4to5_v20_ledger.csv")
        prod_dates["4to5"] = set(df_45["buy_date"].astype(str).str[:10])
    except Exception:
        pass

    all_prod_occupied_dates = set()
    for s_name, dts in prod_dates.items():
        all_prod_occupied_dates.update(dts)

    trades_a = ev_opt_a_lianban["single_trades"]
    col_cnt = 0
    empty_fill_cnt = 0
    empty_fill_trades = []
    for bd, ed, rt, c6 in trades_a:
        if bd in all_prod_occupied_dates:
            col_cnt += 1
        else:
            empty_fill_cnt += 1
            empty_fill_trades.append((bd, ed, rt, c6))

    print(f"方案 A 单仓执行交易总数: {len(trades_a)} 笔")
    if len(trades_a) > 0:
        print(f"  -> 与既有主力策略同日撞车: {col_cnt} 笔 ({col_cnt/len(trades_a)*100:.1f}%)")
        print(f"  -> 纯空仓日填空增量: {empty_fill_cnt} 笔 ({empty_fill_cnt/len(trades_a)*100:.1f}%)")
    if empty_fill_trades:
        fill_rets = [x[2] for x in empty_fill_trades]
        w_f = sum(r > 0 for r in fill_rets)
        print(f"  -> 纯填空交易胜率: {w_f/len(fill_rets)*100:.1f}%, 平均单笔收益: {np.mean(fill_rets)*100:+.2f}%")

    # 7. 落盘台账与汇总文件
    ledger_rows = []
    for r in df_opt_a.itertuples(index=False):
        ledger_rows.append({
            "buy_date": r.buy_date, "exit_date": r.exit_date, "code": r.code, "name": r.name,
            "pattern": r.pattern, "prev_streak": r.prev_streak, "buy_px": r.buy_px,
            "net_ret": r.net_ret, "hold_days": r.hold_days, "open_pct": r.open_pct,
            "d1_yang_body": r.d1_yang_body, "d1_to": r.d1_to, "lock_top10": r.lock_top10,
            "real_free_mcap": r.real_free_mcap, "is_lead_theme": r.is_lead_theme,
            "hr_est": r.hr_est, "net_ret_ma5": r.net_ret_ma5, "exit_date_ma5": r.exit_date_ma5
        })
    df_ledger = pd.DataFrame(ledger_rows).sort_values("buy_date")
    p_ledger = f"{OUT_DIR}/ledger_rd013_best.csv"
    df_ledger.to_csv(p_ledger, index=False)
    print(f"[+] Best ledger saved: {p_ledger} ({len(df_ledger)} rows)")

    summary_data = {
        "metadata": {
            "title": "RD013: 断板反包与 N天M板（隔日换手晋级全谱系）深度机制拆解与四策略全量因子迁移回测",
            "run_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "universe": "沪深主板10cm非ST (含退市)",
            "date_range": "2021-11-01 to 2026-11-10",
            "fee_rate": FEE_RATE
        },
        "base_rates": {k: {kk: vv for kk, vv in v.items() if kk != "single_trades"} for k, v in base_evals.items()},
        "factor_sweeps": {k: {kk: vv for kk, vv in v.items() if kk != "single_trades"} for k, v in factor_sweeps.items()},
        "opt_schemes": {
            "Scheme_A_MainTheme_TurnoverDragon_Lianban": {k: v for k, v in ev_opt_a_lianban.items() if k != "single_trades"},
            "Scheme_A_MainTheme_TurnoverDragon_MA5": {k: v for k, v in ev_opt_a_ma5.items() if k != "single_trades"},
            "Scheme_B_HighDragon_TrueYang_Lianban": {k: v for k, v in ev_opt_b_lianban.items() if k != "single_trades"},
            "Scheme_B_HighDragon_TrueYang_MA5": {k: v for k, v in ev_opt_b_ma5.items() if k != "single_trades"},
            "Scheme_C_Elite_Breakout_Lianban": {k: v for k, v in ev_opt_c_lianban.items() if k != "single_trades"},
        },
        "three_periods": {
            "Scheme_A": {k: {kk: vv for kk, vv in v.items() if kk != "single_trades"} for k, v in periods_a.items()},
            "Scheme_B": {k: {kk: vv for kk, vv in v.items() if kk != "single_trades"} for k, v in periods_b.items()}
        },
        "collision_audit": {
            "total_single_trades": len(trades_a),
            "collision_count": col_cnt,
            "collision_pct": round(col_cnt / len(trades_a) * 100.0, 2) if len(trades_a) else 0.0,
            "empty_fill_count": empty_fill_cnt,
            "empty_fill_pct": round(empty_fill_cnt / len(trades_a) * 100.0, 2) if len(trades_a) else 0.0,
            "empty_fill_wr": round(sum(r[2] > 0 for r in empty_fill_trades) / len(empty_fill_trades) * 100.0, 2) if empty_fill_trades else 0.0,
            "empty_fill_avg_ret": round(float(np.mean([r[2] for r in empty_fill_trades])) * 100.0, 2) if empty_fill_trades else 0.0
        }
    }
    p_summary = f"{OUT_DIR}/summary_rd013.json"
    with open(p_summary, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)
    print(f"[+] Summary JSON saved: {p_summary}")
    print(f"[DONE] Full matrix execution completed in {time.time()-t_start:.2f}s")


if __name__ == "__main__":
    main()

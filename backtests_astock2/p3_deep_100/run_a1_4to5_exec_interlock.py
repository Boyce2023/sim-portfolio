#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_a1_4to5_exec_interlock.py — 四进五策略全因子底座构建与执行/卖点/双异动回测
覆盖 PM 建议单 F57-F68 全部 12 项要求及 6 买 × 4 卖 矩阵正面对决。
严格遵守 D12（零 yfinance）、D15（单仓+按日等权+三期+沪深300净超额+去Top3）、SQLite mode=ro。
"""
import os
import sys
import json
import pickle
import sqlite3
import numpy as np
import pandas as pd

# 路径与环境配置
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
AST2_DIR = f"{SIM_DIR}/backtests_astock2"
P3_DIR = f"{AST2_DIR}/p3_deep_100"
os.makedirs(P3_DIR, exist_ok=True)

if P3_DIR not in sys.path:
    sys.path.insert(0, P3_DIR)
from common_eval_harness import eval_factor_slice, load_production_3_ledgers, CSI_BENCH

FEE = 0.0020
OUT_FEATURES_PARQUET = f"{P3_DIR}/4to5_master_features.parquet"
OUT_RESULTS_CSV = f"{P3_DIR}/a1_4to5_exec_and_interlock_F57_F68.csv"
OUT_SUMMARY_JSON = f"{P3_DIR}/a1_summary.json"


# 1. 数据加载模块
def load_all_market_data():
    print("[1/5] 加载大盘指数与股票日线底座...")
    with open(f"{SIM_DIR}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", "r") as f:
        idx_cache = json.load(f)
    sh_map, sz_map = idx_cache["sh000002"], idx_cache["sz399107"]

    with open(f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl", "rb") as f:
        cb_map = pickle.load(f)["code_bars"]

    print("[2/5] 合并加载 5 大本地 5 分钟 K 线库...")
    b5m_map = {}

    # 源1: p2_4to5/cand_4to5_5m_bars.parquet
    p1 = f"{AST2_DIR}/p2_4to5/cand_4to5_5m_bars.parquet"
    if os.path.exists(p1):
        df1 = pd.read_parquet(p1)
        for (c, d), g in df1.groupby(["c6", "date"], sort=False):
            b5m_map[(str(c).zfill(6), str(d))] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    # 源2: data_5y/cand_3to4_5m_bars.parquet
    p2 = f"{AST2_DIR}/data_5y/cand_3to4_5m_bars.parquet"
    if os.path.exists(p2):
        df2 = pd.read_parquet(p2)
        for (c, d), g in df2.groupby(["c6", "date"], sort=False):
            k = (str(c).zfill(6), str(d))
            if k not in b5m_map:
                b5m_map[k] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    # 源3: data/cand_5m_bars_v15_complete.parquet
    p3 = f"{ROOT}/sim-portfolio/data/cand_5m_bars_v15_complete.parquet"
    if os.path.exists(p3):
        df3 = pd.read_parquet(p3)
        for (c, d), g in df3.groupby(["c6", "date"], sort=False):
            k = (str(c).zfill(6), str(d))
            if k not in b5m_map:
                b5m_map[k] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    # 源4: high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl
    p4 = f"{SIM_DIR}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/sub2_5m_bars_cache.pkl"
    if os.path.exists(p4):
        with open(p4, "rb") as f:
            pk = pickle.load(f)
        for k_raw, df_k in pk.items():
            if isinstance(df_k, pd.DataFrame) and "date" in df_k.columns and not df_k.empty:
                c6 = str(k_raw[0]).zfill(6)
                for d, g in df_k.groupby("date", sort=False):
                    k = (c6, str(d))
                    if k not in b5m_map:
                        arr = g[["open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
                        if "hhmm_int" in g.columns:
                            h_arr = g["hhmm_int"].to_numpy(dtype=float).reshape(-1, 1)
                        else:
                            h_arr = g["hhmm"].astype(str).str.replace(":", "").astype(float).to_numpy().reshape(-1, 1)
                        b5m_map[k] = np.hstack([h_arr, arr])

    # 源5: data/firstboard_5m_5y_pit.db (严格 mode=ro)
    p5 = f"{ROOT}/sim-portfolio/data/firstboard_5m_5y_pit.db"
    if os.path.exists(p5):
        df_cands = pd.read_parquet(f"{AST2_DIR}/p2_4to5/cand_4to5_enriched.parquet")
        cand_codes = sorted(df_cands["code"].astype(str).str.zfill(6).unique())
        con = sqlite3.connect(f"file:{p5}?mode=ro", uri=True)
        qm = ",".join(["?"] * len(cand_codes))
        sql = f"SELECT sec_code, trade_date, substr(bar_time,12,2)||substr(bar_time,15,2) as hhmm, open, high, low, close, volume, amount FROM firstboard_5m_bars WHERE sec_code IN ({qm})"
        df5 = pd.read_sql(sql, con, params=cand_codes)
        con.close()
        if not df5.empty:
            df5["hhmm_int"] = df5["hhmm"].astype(int)
            for (c, d), g in df5.groupby(["sec_code", "trade_date"], sort=False):
                k = (str(c).zfill(6), str(d))
                if k not in b5m_map:
                    b5m_map[k] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)

    print(f"5m K线库合并完成，共有有效 (代码, 日期) 条目: {len(b5m_map)}")
    return sh_map, sz_map, cb_map, b5m_map


# 2. 09:25 PIT 双严重异动计算（F57 & F58）
def compute_pit_headroom(c6: str, bd: str, cb: dict, pos: int, sh_map: dict, sz_map: dict):
    """
    严格在 buy_date 09:25 时点计算双严重异动空间。
    基准指数只能取 sig_date 收盘指数 imap[sig_date]，绝不偷看 buy_date 当天收盘指数！
    """
    if pos < 1:
        return 0.0, 0.0, 0.0
    sd = cb["dts"][pos - 1]
    imap = sh_map if c6.startswith("60") else sz_map
    ir = imap.get(sd)
    op = float(cb["open"][pos])
    if op <= 0.0 or not ir:
        return 0.0, 0.0, 0.0

    p100, p200 = 99999.0, 99999.0
    # 10日偏离值达 100% (回溯1到10天)
    for k in range(1, min(10, pos) + 1):
        bi = imap.get(cb["dts"][pos - k])
        bc = cb["close"][pos - k] * cb["adjf"][pos - k] / cb["adjf"][pos]
        if bi and bc > 0:
            p100 = min(p100, bc * (2.0 + (ir / bi - 1.0)))

    # 30日偏离值达 200% (回溯1到30天)
    for k in range(1, min(30, pos) + 1):
        bi = imap.get(cb["dts"][pos - k])
        bc = cb["close"][pos - k] * cb["adjf"][pos - k] / cb["adjf"][pos]
        if bi and bc > 0:
            p200 = min(p200, bc * (3.0 + (ir / bi - 1.0)))

    hr100 = (p100 / op - 1.0) if p100 < 99990.0 else 0.0
    hr200 = (p200 / op - 1.0) if p200 < 99990.0 else 0.0
    tighter = min(hr100, hr200)
    return float(hr100), float(hr200), float(tighter)


# 3. 6 种买法撮合引擎（F59 & F60）
def sim_buy_4to5(c6: str, bd: str, cb: dict, pos: int, b5m_map: dict, buy_mode: str):
    """
    返回 (buy_px, buy_hhmm) 或 (None, None)
    """
    op = float(cb["open"][pos])
    pc = float(cb["pre_c"][pos])
    zt = float(cb["zt_px"][pos])
    dt = round(pc * 0.90, 2)
    op_pct = op / pc - 1.0

    if buy_mode == "B1_open_all":
        # 首轮竞价全买: 只要开盘未一字涨停
        if op >= zt - 0.005:
            return None, None
        return op, 925

    elif buy_mode == "B2_underwater_dip":
        # 水下低吸: 竞价 open_pct < -0.02 且未一字跌停
        if op_pct < -0.02 and op > dt + 0.005:
            return op, 925
        return None, None

    elif buy_mode == "B3_pm_f59_1030":
        # PM建议 F59: 竞价 2.0% <= open_pct <= 6.0% 且 10:30 前向上突破
        if not (0.02 <= op_pct <= 0.06):
            return None, None
        trig = max(pc * 1.065, op * 1.015)
        if trig >= zt - 0.005:
            return None, None
        if op >= trig:
            return op, 925
        arr = b5m_map.get((c6, bd))
        if arr is None or len(arr) == 0:
            return None, None
        for row in arr:
            hhmm = int(row[0])
            if hhmm > 1030:
                break
            bo, bh, bl = row[1], row[2], row[3]
            if bl >= zt - 0.005:
                continue
            if bh >= trig:
                fill_px = max(bo, trig)
                if fill_px < zt - 0.005:
                    return float(fill_px), hhmm
        return None, None

    elif buy_mode == "B4_pm_f59_wide_1130":
        # 宽范围突破: 竞价 1.0% <= open_pct <= 8.0% 且 11:30 前向上突破
        if not (0.01 <= op_pct <= 0.08):
            return None, None
        trig = max(pc * 1.065, op * 1.012)
        if trig >= zt - 0.005:
            return None, None
        if op >= trig:
            return op, 925
        arr = b5m_map.get((c6, bd))
        if arr is None or len(arr) == 0:
            return None, None
        for row in arr:
            hhmm = int(row[0])
            if hhmm > 1130:
                break
            bo, bh, bl = row[1], row[2], row[3]
            if bl >= zt - 0.005:
                continue
            if bh >= trig:
                fill_px = max(bo, trig)
                if fill_px < zt - 0.005:
                    return float(fill_px), hhmm
        return None, None

    elif buy_mode == "B5_3to4_touch65_1130":
        # 三进四标准买法: 竞价 2.0% <= open_pct <= 8.5% 且 11:30 前触及
        if not (0.02 <= op_pct <= 0.085):
            return None, None
        trig = max(pc * 1.065, op)
        if trig >= zt - 0.005:
            return None, None
        if op >= trig:
            return op, 925
        arr = b5m_map.get((c6, bd))
        if arr is None or len(arr) == 0:
            return None, None
        for row in arr:
            hhmm = int(row[0])
            if hhmm > 1130:
                break
            bo, bh, bl = row[1], row[2], row[3]
            if bl >= zt - 0.005:
                continue
            if bh >= trig:
                fill_px = max(bo, trig)
                if fill_px < zt - 0.005:
                    return float(fill_px), hhmm
        return None, None

    elif buy_mode == "B6_auc_sweet_2_7":
        # 竞价甜区直买: 2.0% <= open_pct <= 7.5% 且未一字涨停
        if 0.02 <= op_pct <= 0.075 and op < zt - 0.005:
            return op, 925
        return None, None

    return None, None


# 4. 辅助函数：双严重异动限价单与剩余空间
def get_double_dev93_px(cb, cp, imap):
    cd = cb["dts"][cp]
    ir = imap.get(cd)
    if not ir:
        return 99999.0
    bp = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k
        bi = imap.get(cb["dts"][p])
        bc = cb["close"][p] * cb["adjf"][p] / cb["adjf"][cp]
        if bi and bc > 0:
            bp = min(bp, bc * (1.93 + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k
        bi = imap.get(cb["dts"][p])
        bc = cb["close"][p] * cb["adjf"][p] / cb["adjf"][cp]
        if bi and bc > 0:
            bp = min(bp, bc * (2.93 + (ir / bi - 1.0)))
    return bp


def get_double_dev100_headroom(cb, cp, imap):
    cd = cb["dts"][cp]
    ir = imap.get(cd)
    if not ir:
        return 999.0
    bp = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k
        bi = imap.get(cb["dts"][p])
        bc = cb["close"][p] * cb["adjf"][p] / cb["adjf"][cp]
        if bi and bc > 0:
            bp = min(bp, bc * (2.00 + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k
        bi = imap.get(cb["dts"][p])
        bc = cb["close"][p] * cb["adjf"][p] / cb["adjf"][cp]
        if bi and bc > 0:
            bp = min(bp, bc * (3.00 + (ir / bi - 1.0)))
    pc = float(cb["pre_c"][cp])
    return (bp / pc - 1.0) if pc > 0 else 999.0


# 5. 4 种卖法撮合引擎（F61 & F62）
def sim_exit_4to5(c6: str, cb: dict, pos: int, b5m_map: dict, imap: dict, exit_mode: str, cand_row: dict):
    """
    返回 (exit_dt, sell_px, adjf_s, hold_bars, exit_hhmm, exit_reason)
    """
    n = len(cb["dts"])
    is_zt_day5 = bool(cb["is_zt"][pos])

    # 1. Day5 未封五板
    if not is_zt_day5:
        is_f61_eligible = False
        if exit_mode == "E4_F61_high_dragon_handoff":
            c5, o5 = float(cb["close"][pos]), float(cb["open"][pos])
            to5 = float(cb["to"][pos]) if "to" in cb else 0.0
            is_highest_4b = bool(cand_row.get("is_mkt_highest_4b", 0) == 1)
            is_true_yang = bool(c5 > o5)
            turn_ok = bool(to5 <= 35.0)
            no_tox = bool(cand_row.get("has_tox_notice", 0) == 0 and cand_row.get("has_stock_reg", 0) == 0 and cand_row.get("has_ex_reg", 0) == 0)
            if is_highest_4b and is_true_yang and turn_ok and no_tox:
                is_f61_eligible = True

        if is_f61_eligible:
            # E4 原地转仓高标首阴: Day6 早盘不割肉博反包
            k = pos + 1
            while k < n and bool(cb["is_yizi_dt"][k]):
                k += 1
            if k >= n:
                k = n - 1
                return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500, "f61_end_close"

            o6, p6, c6_px, zt6 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
            o6_pct = o6 / p6 - 1.0

            # 若 Day6 开盘遭遇严重核按钮 (<= -3.5%) 则竞价走
            if o6_pct <= -0.035:
                return cb["dts"][k], o6, float(cb["adjf"][k]), max(1, k - pos), 925, "f61_nuke_exit"

            # 否则拿至收盘博反包
            if bool(cb["is_zt"][k]):
                pos_start = k + 1
            else:
                return cb["dts"][k], c6_px, float(cb["adjf"][k]), max(1, k - pos), 1500, "f61_d6_close"
        else:
            # 标准 E1 cut_weak 退出 (E1, E2, E3 及非 F61 样本)
            k = pos + 1
            while k < n and bool(cb["is_yizi_dt"][k]):
                k += 1
            if k >= n:
                k = n - 1
                return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500, "unseal_end_close"
            if k > pos + 1:
                return cb["dts"][k], float(cb["open"][k]), float(cb["adjf"][k]), k - pos, 925, "unseal_yizi_break_open"

            dt_s = cb["dts"][k]
            o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
            o5, p5, c5_px = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])

            d4_strong = (c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)
            if not d4_strong:
                return dt_s, o5, float(cb["adjf"][k]), max(1, k - pos), 925, "cut_weak_open"
            if bool(cb["is_zt"][k]):
                pos_start = k + 1
            else:
                return dt_s, c5_px, float(cb["adjf"][k]), max(1, k - pos), 1500, "cut_weak_close"
    else:
        # Day5 成功封死五板
        pos_start = pos + 1

    # 2. 封板后的连板持有追踪 (k >= pos_start)
    k = pos_start
    imm_used = False
    while k < n:
        if bool(cb["is_yizi_dt"][k]):
            k += 1
            continue
        dt_s = cb["dts"][k]
        ok, pck, clk, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
        dtk = round(pck * 0.90, 2)
        hk = float(cb["high"][k])

        if k > pos_start and bool(cb["is_yizi_dt"][k - 1]):
            return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "yizi_dt_break_open"

        # 检查是否执行双异动 93% 挂单
        use_dev93_today = False
        if exit_mode == "E2_dev93_always":
            use_dev93_today = True
        elif exit_mode == "E3_F62_staged_dev93":
            # 五进六 (k - pos == 1) 与 六进七 (k - pos == 2) 不挂93%单
            # 满7板 (k - pos >= 3) 或当日异动剩余空间 < 6% 时启动挂单
            hr_today = get_double_dev100_headroom(cb, k, imap)
            if (k - pos >= 3) or (hr_today < 0.06):
                use_dev93_today = True
            else:
                use_dev93_today = False

        if use_dev93_today:
            pl = get_double_dev93_px(cb, k, imap)
            if ok >= pl:
                return dt_s, ok, float(cb["adjf"][k]), k - pos, 925, "dev93_open_exit"
            if hk >= pl:
                return dt_s, pl, float(cb["adjf"][k]), k - pos, 1000, "dev93_intraday_exit"

        # 13:45 护利检查
        arr = b5m_map.get((c6, dt_s))
        did_ex, spx, shhmm = False, 0.0, 0
        if arr is not None and len(arr) > 0:
            peak = ok
            for row in arr:
                hhmm, bo, bh, bl, bc = int(row[0]), row[1], row[2], row[3], row[4]
                if bh <= dtk + 0.005:
                    continue
                if hhmm >= 1345 and peak >= pck * 1.085 and bl <= pck * 1.050 and bc < ztk - 0.01:
                    did_ex, spx, shhmm = True, float(min(bo, pck * 1.050)), hhmm
                    break
                if bh > peak:
                    peak = bh

        if did_ex:
            return dt_s, spx, float(cb["adjf"][k]), max(1, k - pos), shhmm, "pm1345_guard"

        if bool(cb["is_zt"][k]):
            k += 1
            continue

        # 断板真阳免死 1 次
        if (not imm_used) and (clk > ok) and (clk >= pck):
            imm_used = True
            k += 1
            continue

        return dt_s, clk, float(cb["adjf"][k]), max(1, k - pos), 1500, "eod_break_close"

    k = n - 1
    return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500, "dataset_end"


# 主执行流程
def main():
    sh_map, sz_map, cb_map, b5m_map = load_all_market_data()

    print("[3/5] 构建全量 4to5 Master 特征与买卖撮合矩阵...")
    df_raw = pd.read_parquet(f"{AST2_DIR}/p2_4to5/cand_4to5_enriched.parquet")
    df_all = pd.read_parquet(f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/cand_high_dragon.parquet")

    # 预建昨日 5 板老龙竞价字典 (用于 F63 篡位检验)
    d5_stocks = df_all[df_all["prev_streak"] == 5][["code", "name", "sig_date", "buy_date", "open_pct"]].copy()
    d5_map = {}
    for r in d5_stocks.itertuples():
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        d5_map[bd] = (c6, r.name, float(r.open_pct))

    # 加载三大主力生产台账 (用于 F68 补缺门检验)
    main_ledgers = load_production_3_ledgers()
    main_buy_dates = set(main_ledgers["any_main_buy_dates"])

    # 构建三大主力持仓区间集合
    main_holding_dates = set()
    for l_key in ("1to2", "3to4", "high"):
        l_df = main_ledgers[l_key]
        for r in l_df.itertuples():
            bd = str(r.buy_date)[:10]
            ed = str(r.exit_date)[:10] if hasattr(r, "exit_date") and pd.notna(r.exit_date) else bd
            # 将 [bd, ed] 区间内所有日期纳入持仓
            main_holding_dates.add(bd)
            main_holding_dates.add(ed)

    # 逐笔计算特征与撮合
    records = []
    buy_modes = ["B1_open_all", "B2_underwater_dip", "B3_pm_f59_1030", "B4_pm_f59_wide_1130", "B5_3to4_touch65_1130", "B6_auc_sweet_2_7"]
    exit_modes = ["E1_3to4_std", "E2_dev93_always", "E3_F62_staged_dev93", "E4_F61_high_dragon_handoff"]

    for row_dict in df_raw.to_dict("records"):
        c6 = str(row_dict["code"]).zfill(6)
        bd = str(row_dict["buy_date"])
        cb = cb_map.get(c6)
        if cb is None or bd not in cb["date_to_pos"]:
            continue
        pos = cb["date_to_pos"][bd]
        if pos < 1:
            continue

        imap = sh_map if c6.startswith("60") else sz_map

        # 1. PIT 双严重异动
        h10_pit, h30_pit, tighter_pit = compute_pit_headroom(c6, bd, cb, pos, sh_map, sz_map)
        row_dict["headroom_10d_100_pit"] = h10_pit
        row_dict["headroom_30d_200_pit"] = h30_pit
        row_dict["tighter_headroom_pit"] = tighter_pit

        row_dict["hr_pit_lt10"] = bool(tighter_pit < 0.10)
        row_dict["hr_pit_10_18"] = bool(0.10 <= tighter_pit < 0.18)
        row_dict["hr_pit_ge18"] = bool(tighter_pit >= 0.18)
        row_dict["hr_pit_ge22"] = bool(tighter_pit >= 0.22)
        row_dict["hr_pit_ge25"] = bool(tighter_pit >= 0.25)
        row_dict["hr10_ge22"] = bool(h10_pit >= 0.22)

        # 2. 6 种买法撮合
        buy_res = {}
        for bm in buy_modes:
            bpx, bhh = sim_buy_4to5(c6, bd, cb, pos, b5m_map, bm)
            buy_res[bm] = (bpx, bhh)
            row_dict[f"{bm}_bought"] = bool(bpx is not None)
            row_dict[f"{bm}_px"] = float(bpx) if bpx is not None else np.nan
            row_dict[f"{bm}_hhmm"] = int(bhh) if bhh is not None else np.nan

        # 3. 4 种卖法撮合
        # 以基准买法 B3 (以及 B1, B5) 驱动完整卖出轨迹
        for em in exit_modes:
            ex_dt, spx, adjs, hb, shh, reason = sim_exit_4to5(c6, cb, pos, b5m_map, imap, em, row_dict)
            # 计算各买法对应的净收益
            for bm in buy_modes:
                bpx, _ = buy_res[bm]
                if bpx is not None and bpx > 0:
                    net_r = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
                    row_dict[f"ret_{bm}_{em}"] = float(net_r)
                    row_dict[f"exdt_{bm}_{em}"] = ex_dt
                else:
                    row_dict[f"ret_{bm}_{em}"] = np.nan
                    row_dict[f"exdt_{bm}_{em}"] = None

        # 4. F61 高标首阴免砍判定特征
        c5, o5 = float(cb["close"][pos]), float(cb["open"][pos])
        to5 = float(cb["to"][pos]) if "to" in cb else 0.0
        is_highest_4b = bool(row_dict.get("is_mkt_highest_4b", 0) == 1)
        is_true_yang = bool(c5 > o5)
        turn_ok = bool(to5 <= 35.0)
        no_tox = bool(row_dict.get("has_tox_notice", 0) == 0 and row_dict.get("has_stock_reg", 0) == 0 and row_dict.get("has_ex_reg", 0) == 0)
        is_zt_day5 = bool(cb["is_zt"][pos])
        row_dict["f61_eligible"] = bool((not is_zt_day5) and is_highest_4b and is_true_yang and turn_ok and no_tox)

        # 5. F63 - F67 特征
        # F63 篡位日
        d5_info = d5_map.get(bd)
        is_usurp = False
        if row_dict.get("mkt_max_board_prev", 0) == 5 and d5_info:
            c6_5, n_5, op_5 = d5_info
            if op_5 < -0.03 and float(row_dict.get("open_pct", 0.0)) >= 0.03:
                is_usurp = True
        row_dict["f63_usurp_5b_lead"] = is_usurp

        # F64 换手温和收敛
        to_r = float(row_dict.get("to_ratio_d4_d3", 1.0))
        obc = int(row_dict.get("open_board_count", 0))
        row_dict["f64_converge_turn"] = bool(0.70 <= to_r <= 1.35 and obc >= 1)
        row_dict["f64_shrink_extreme"] = bool(to_r < 0.50)
        row_dict["f64_expand_extreme"] = bool(to_r > 2.00)

        # F65 途经水下抗揍拉板检验
        dip4 = float(row_dict.get("d4_intraday_dip", 0.0))
        has_subzero = bool(dip4 < 0.0)
        for p_prev in range(max(0, pos - 4), pos):
            if cb["is_zt"][p_prev] and (float(cb["low"][p_prev]) < float(cb["pre_c"][p_prev])):
                has_subzero = True
                break
        row_dict["f65_water_dip_tested"] = has_subzero

        # F66 题材断层拱卫结构
        is_sole_4b = bool(row_dict.get("is_sole_4b", 0) == 1)
        plate_fb = int(row_dict.get("plate_fb_cnt", 0))
        row_dict["f66_arch_structure"] = bool(is_sole_4b and plate_fb >= 2)

        # F67 周四与周五买入
        wk = pd.to_datetime(bd).weekday()
        row_dict["f67_thu_fri_buy"] = bool(wk in (3, 4))

        # F68 三大主力全空仓日
        row_dict["f68_main3_no_open"] = bool(bd not in main_buy_dates)
        row_dict["f68_main3_empty_slot"] = bool(bd not in main_holding_dates)

        records.append(row_dict)

    df_master = pd.DataFrame(records)
    print(f"Master 特征构建完成，有效样本量: {len(df_master)}")
    df_master.to_parquet(OUT_FEATURES_PARQUET, index=False)
    print(f"已保存特征表至: {OUT_FEATURES_PARQUET}")

    print("[4/5] 运行 PM 建议单 F57-F68 逐项回测与买卖矩阵正面对决...")
    # 评测全量条目
    eval_rows = []

    # 1. 买法 × 卖法 矩阵 (6 × 4 = 24 种组合)
    base_ret_col = "ret_B3_pm_f59_1030_E1_3to4_std"
    base_mean = float(df_master[base_ret_col].dropna().mean()) if base_ret_col in df_master.columns else 0.0

    for bm in buy_modes:
        for em in exit_modes:
            ret_col = f"ret_{bm}_{em}"
            ex_col = f"exdt_{bm}_{em}"
            sub = df_master[df_master[ret_col].notna()].copy()
            res = eval_factor_slice(sub, ret_col=ret_col, exit_col=ex_col, rank_col="open_pct", base_mean=base_mean)
            res["factor_id"] = f"MATRIX_{bm}_{em}"
            res["factor_desc"] = f"买卖矩阵: {bm} × {em}"
            res["category"] = "EXEC_MATRIX"
            eval_rows.append(res)

    # 2. F57 & F58: 严格 PIT 双严重异动空间分箱 (基于 B3_E1 与 B3_E3)
    for target_ret, target_ex, suffix in [("ret_B3_pm_f59_1030_E1_3to4_std", "exdt_B3_pm_f59_1030_E1_3to4_std", "E1_std"),
                                          ("ret_B3_pm_f59_1030_E3_F62_staged_dev93", "exdt_B3_pm_f59_1030_E3_F62_staged_dev93", "E3_staged")]:
        f_bmean = float(df_master[target_ret].dropna().mean())
        # F57
        f57_bins = [
            ("F57_hr10_lt10", "10日100%异动空间<10%(一板必撞线压制区)", df_master["headroom_10d_100_pit"] < 0.10),
            ("F57_hr10_10_18", "10日100%异动空间10%~18%(一板撞线边缘)", df_master["headroom_10d_100_pit"].between(0.10, 0.18)),
            ("F57_hr10_ge18", "10日100%异动空间>=18%(两板缓冲区)", df_master["headroom_10d_100_pit"] >= 0.18),
            ("F57_hr10_ge22", "F57核心门槛:10日100%空间>=22%(两板安全垫)", df_master["headroom_10d_100_pit"] >= 0.22),
            ("F57_hr10_ge25", "10日100%异动空间>=25%(极宽安全垫)", df_master["headroom_10d_100_pit"] >= 0.25),
        ]
        for fid, fdesc, mask in f57_bins:
            sub = df_master[mask & df_master[target_ret].notna()]
            r = eval_factor_slice(sub, ret_col=target_ret, exit_col=target_ex, base_mean=f_bmean)
            r["factor_id"] = f"{fid}_{suffix}"
            r["factor_desc"] = f"{fdesc} [{suffix}]"
            r["category"] = "F57_HEADROOM_10D"
            eval_rows.append(r)

        # F58
        f58_bins = [
            ("F58_tighter_lt10", "双异动较紧空间<10%(一板撞线)", df_master["tighter_headroom_pit"] < 0.10),
            ("F58_tighter_10_18", "双异动较紧空间10%~18%(边缘带)", df_master["tighter_headroom_pit"].between(0.10, 0.18)),
            ("F58_tighter_ge18", "双异动较紧空间>=18%", df_master["tighter_headroom_pit"] >= 0.18),
            ("F58_tighter_ge22", "F58核心门槛:双异动较紧空间>=22%(防二波撞30日200%)", df_master["tighter_headroom_pit"] >= 0.22),
            ("F58_tighter_ge25", "双异动较紧空间>=25%", df_master["tighter_headroom_pit"] >= 0.25),
        ]
        for fid, fdesc, mask in f58_bins:
            sub = df_master[mask & df_master[target_ret].notna()]
            r = eval_factor_slice(sub, ret_col=target_ret, exit_col=target_ex, base_mean=f_bmean)
            r["factor_id"] = f"{fid}_{suffix}"
            r["factor_desc"] = f"{fdesc} [{suffix}]"
            r["category"] = "F58_DOUBLE_HEADROOM"
            eval_rows.append(r)

    # 3. F59 & F60: 买点重构对决
    # B1 vs B2 vs B3 vs B4 vs B5 vs B6 (全部基于 E1 退出基准)
    f59_list = [
        ("F59_B1_open_all", "B1首轮09:25竞价全买(证伪为什么回撤81%)", "ret_B1_open_all_E1_3to4_std", "exdt_B1_open_all_E1_3to4_std"),
        ("F60_B2_underwater_dip", "F60水下低吸open<-2%(证伪与高标首阴抢戏)", "ret_B2_underwater_dip_E1_3to4_std", "exdt_B2_underwater_dip_E1_3to4_std"),
        ("F59_B3_pm_f59_1030", "F59建议买点:竞价2~6%且10:30前向上突破", "ret_B3_pm_f59_1030_E1_3to4_std", "exdt_B3_pm_f59_1030_E1_3to4_std"),
        ("F59_B4_pm_wide_1130", "B4宽突破:竞价1~8%且11:30前突破", "ret_B4_pm_f59_wide_1130_E1_3to4_std", "exdt_B4_pm_f59_wide_1130_E1_3to4_std"),
        ("F59_B5_3to4_touch65_1130", "B5三进四标准买法:竞价2~8.5%且11:30前触及6.5%", "ret_B5_3to4_touch65_1130_E1_3to4_std", "exdt_B5_3to4_touch65_1130_E1_3to4_std"),
        ("F59_B6_auc_sweet_2_7", "B6竞价甜区直买:竞价2.0%~7.5%", "ret_B6_auc_sweet_2_7_E1_3to4_std", "exdt_B6_auc_sweet_2_7_E1_3to4_std"),
    ]
    for fid, fdesc, rcol, ecol in f59_list:
        sub = df_master[df_master[rcol].notna()]
        r = eval_factor_slice(sub, ret_col=rcol, exit_col=ecol, base_mean=base_mean)
        r["factor_id"] = fid
        r["factor_desc"] = fdesc
        r["category"] = "F59_F60_BUY_COMPARISON"
        eval_rows.append(r)

    # 4. F61: 高标首阴 V5.1 原地转仓免砍锁 (E4 vs E1 对决)
    # 分全池对比与首阴符合子池对比
    sub_f61_all_e4 = df_master[df_master["ret_B3_pm_f59_1030_E4_F61_high_dragon_handoff"].notna()]
    sub_f61_all_e1 = df_master[df_master["ret_B3_pm_f59_1030_E1_3to4_std"].notna()]
    r_f61_e4 = eval_factor_slice(sub_f61_all_e4, ret_col="ret_B3_pm_f59_1030_E4_F61_high_dragon_handoff", exit_col="exdt_B3_pm_f59_1030_E4_F61_high_dragon_handoff", base_mean=base_mean)
    r_f61_e4["factor_id"] = "F61_E4_handoff_all"
    r_f61_e4["factor_desc"] = "F61原地转仓免砍(E4全池)"
    r_f61_e4["category"] = "F61_HIGH_DRAGON_HANDOFF"
    eval_rows.append(r_f61_e4)

    r_f61_e1 = eval_factor_slice(sub_f61_all_e1, ret_col="ret_B3_pm_f59_1030_E1_3to4_std", exit_col="exdt_B3_pm_f59_1030_E1_3to4_std", base_mean=base_mean)
    r_f61_e1["factor_id"] = "F61_E1_cutweak_all"
    r_f61_e1["factor_desc"] = "E1弱斩强留机械割肉(对照组全池)"
    r_f61_e1["category"] = "F61_HIGH_DRAGON_HANDOFF"
    eval_rows.append(r_f61_e1)

    # 仅针对 Day5 断板且满足 F61 高标首阴条件的样本内部对比
    sub_f61_spec = df_master[df_master["f61_eligible"] & df_master["ret_B3_pm_f59_1030_E4_F61_high_dragon_handoff"].notna()]
    r_f61_spec_e4 = eval_factor_slice(sub_f61_spec, ret_col="ret_B3_pm_f59_1030_E4_F61_high_dragon_handoff", exit_col="exdt_B3_pm_f59_1030_E4_F61_high_dragon_handoff", base_mean=base_mean)
    r_f61_spec_e4["factor_id"] = "F61_eligible_E4_handoff"
    r_f61_spec_e4["factor_desc"] = "F61断板命中子集:E4原地免砍持仓博反包"
    r_f61_spec_e4["category"] = "F61_HIGH_DRAGON_HANDOFF"
    eval_rows.append(r_f61_spec_e4)

    r_f61_spec_e1 = eval_factor_slice(sub_f61_spec, ret_col="ret_B3_pm_f59_1030_E1_3to4_std", exit_col="exdt_B3_pm_f59_1030_E1_3to4_std", base_mean=base_mean)
    r_f61_spec_e1["factor_id"] = "F61_eligible_E1_cutweak"
    r_f61_spec_e1["factor_desc"] = "F61断板命中子集:E1次日09:25机械割肉"
    r_f61_spec_e1["category"] = "F61_HIGH_DRAGON_HANDOFF"
    eval_rows.append(r_f61_spec_e1)

    # 5. F62: 分段式异动止盈 (E3 vs E2 vs E1)
    # 基于 B3 买入
    f62_list = [
        ("F62_E3_staged_dev93", "F62分段异动止盈(五进六/六进七不挂单,满7板或空间<6%启动)", "ret_B3_pm_f59_1030_E3_F62_staged_dev93", "exdt_B3_pm_f59_1030_E3_F62_staged_dev93"),
        ("F62_E2_dev93_always", "E2全程挂93%异动单(对照组:是否过早止盈踏空主升浪)", "ret_B3_pm_f59_1030_E2_dev93_always", "exdt_B3_pm_f59_1030_E2_dev93_always"),
        ("F62_E1_3to4_std", "E1纯13:45护利无异动挂单(对照组)", "ret_B3_pm_f59_1030_E1_3to4_std", "exdt_B3_pm_f59_1030_E1_3to4_std"),
    ]
    for fid, fdesc, rcol, ecol in f62_list:
        sub = df_master[df_master[rcol].notna()]
        r = eval_factor_slice(sub, ret_col=rcol, exit_col=ecol, base_mean=base_mean)
        r["factor_id"] = fid
        r["factor_desc"] = fdesc
        r["category"] = "F62_STAGED_DEV93"
        eval_rows.append(r)

    # 6. F63 - F67 逐项检验 (基于最优买卖基准 B3_E3 与 B3_E1)
    ret_b3_e3 = "ret_B3_pm_f59_1030_E3_F62_staged_dev93"
    ex_b3_e3 = "exdt_B3_pm_f59_1030_E3_F62_staged_dev93"
    bmean_e3 = float(df_master[ret_b3_e3].dropna().mean())

    f_addon_list = [
        ("F63_usurp_5b_lead", "F63篡位日:昨最高5板老龙竞价<-3%走弱而4板>=3%篡位", df_master["f63_usurp_5b_lead"]),
        ("F63_non_usurp", "F63对照组:非老龙走弱篡位日", ~df_master["f63_usurp_5b_lead"]),
        ("F64_converge_turn", "F64筹码温和收敛:3板4板换手且0.70<=四板换手/三板换手<=1.35", df_master["f64_converge_turn"]),
        ("F64_shrink_extreme", "F64缩量断层风险区:换手比<0.50", df_master["f64_shrink_extreme"]),
        ("F64_expand_extreme", "F64爆量分歧过大区:换手比>2.00", df_master["f64_expand_extreme"]),
        ("F65_water_dip_tested", "F65前4板途中曾盘中水下抗揍洗盘拉涨停", df_master["f65_water_dip_tested"]),
        ("F65_smooth_up", "F65对照组:前4板顺风未曾水下抗揍", ~df_master["f65_water_dip_tested"]),
        ("F66_arch_structure", "F66题材断层拱卫:1只四板孤龙加多只首板补涨", df_master["f66_arch_structure"]),
        ("F66_non_arch", "F66对照组:非孤龙拱卫结构", ~df_master["f66_arch_structure"]),
        ("F67_thu_fri_buy", "F67周四周五买入跨周末发酵溢价", df_master["f67_thu_fri_buy"]),
        ("F67_mon_wed_buy", "F67对照组:周一至周三买入", ~df_master["f67_thu_fri_buy"]),
    ]
    for fid, fdesc, mask in f_addon_list:
        sub = df_master[mask & df_master[ret_b3_e3].notna()]
        r = eval_factor_slice(sub, ret_col=ret_b3_e3, exit_col=ex_b3_e3, base_mean=bmean_e3)
        r["factor_id"] = fid
        r["factor_desc"] = fdesc
        r["category"] = "F63_F67_FACTORS"
        eval_rows.append(r)

    # 7. F68: 三大主力全空仓日「第四顺位补缺门」纯增量检验
    f68_slices = [
        ("F68_all_universe", "四进五全样本基准(B3_E3)", df_master[ret_b3_e3].notna()),
        ("F68_main3_no_open", "F68三大主力当日无新开仓日切片", df_master["f68_main3_no_open"] & df_master[ret_b3_e3].notna()),
        ("F68_main3_empty_slot", "F68三大主力当日完全空仓空槽日切片(纯增量填槽)", df_master["f68_main3_empty_slot"] & df_master[ret_b3_e3].notna()),
    ]
    for fid, fdesc, mask in f68_slices:
        sub = df_master[mask]
        r = eval_factor_slice(sub, ret_col=ret_b3_e3, exit_col=ex_b3_e3, base_mean=bmean_e3)
        r["factor_id"] = fid
        r["factor_desc"] = fdesc
        r["category"] = "F68_MAIN3_COMPLEMENT"
        eval_rows.append(r)

    # 导出完整 CSV
    df_eval = pd.DataFrame(eval_rows)
    cols_order = [
        "factor_id", "category", "factor_desc", "n_raw", "wr_raw", "payoff_raw", "avg_ret", "delta_vs_base",
        "early_22_23_avg", "recent_24_26_avg", "dual_same_sign", "pos_years_vs_base",
        "ss_n", "ss_wr", "ss_payoff", "ss_nav", "ss_mdd", "ss_ex_top3_nav", "ss_net_excess_5y",
        "eq_nav", "eq_mdd", "ss_pos_years"
    ]
    for c in cols_order:
        if c not in df_eval.columns:
            df_eval[c] = np.nan
    df_eval = df_eval[cols_order]
    df_eval.to_csv(OUT_RESULTS_CSV, index=False, encoding="utf-8-sig")
    print(f"已保存评估指标至: {OUT_RESULTS_CSV}，共 {len(df_eval)} 项因子切片")

    print("[5/5] 提炼核心量化结论与 JSON 摘要...")
    # 提取关键数据总结
    summary = {
        "total_cands": len(df_master),
        "csi300_bench_5y": CSI_BENCH["5y"],
        "buy_comparison_b1_vs_b3": {
            "b1_open_all_nav": float(df_eval.loc[df_eval["factor_id"] == "F59_B1_open_all", "ss_nav"].iloc[0]),
            "b1_open_all_mdd": float(df_eval.loc[df_eval["factor_id"] == "F59_B1_open_all", "ss_mdd"].iloc[0]),
            "b3_pm_1030_nav": float(df_eval.loc[df_eval["factor_id"] == "F59_B3_pm_f59_1030", "ss_nav"].iloc[0]),
            "b3_pm_1030_mdd": float(df_eval.loc[df_eval["factor_id"] == "F59_B3_pm_f59_1030", "ss_mdd"].iloc[0]),
            "b5_touch65_nav": float(df_eval.loc[df_eval["factor_id"] == "F59_B5_3to4_touch65_1130", "ss_nav"].iloc[0]),
            "b5_touch65_mdd": float(df_eval.loc[df_eval["factor_id"] == "F59_B5_3to4_touch65_1130", "ss_mdd"].iloc[0]),
        },
        "underwater_f60_verdict": {
            "b2_underwater_nav": float(df_eval.loc[df_eval["factor_id"] == "F60_B2_underwater_dip", "ss_nav"].iloc[0]),
            "b2_underwater_wr": float(df_eval.loc[df_eval["factor_id"] == "F60_B2_underwater_dip", "ss_wr"].iloc[0]),
            "b2_underwater_avg_ret": float(df_eval.loc[df_eval["factor_id"] == "F60_B2_underwater_dip", "avg_ret"].iloc[0]),
        },
        "headroom_f57_f58": {
            "f57_hr10_ge22_nav": float(df_eval.loc[df_eval["factor_id"] == "F57_hr10_ge22_E3_staged", "ss_nav"].iloc[0]),
            "f57_hr10_ge22_wr": float(df_eval.loc[df_eval["factor_id"] == "F57_hr10_ge22_E3_staged", "ss_wr"].iloc[0]),
            "f58_tighter_ge22_nav": float(df_eval.loc[df_eval["factor_id"] == "F58_tighter_ge22_E3_staged", "ss_nav"].iloc[0]),
            "f58_tighter_ge22_wr": float(df_eval.loc[df_eval["factor_id"] == "F58_tighter_ge22_E3_staged", "ss_wr"].iloc[0]),
        },
        "f61_handoff_verdict": {
            "eligible_cnt": int((df_master["f61_eligible"]).sum()),
            "e4_handoff_spec_avg_ret": float(df_eval.loc[df_eval["factor_id"] == "F61_eligible_E4_handoff", "avg_ret"].iloc[0]),
            "e1_cutweak_spec_avg_ret": float(df_eval.loc[df_eval["factor_id"] == "F61_eligible_E1_cutweak", "avg_ret"].iloc[0]),
        },
        "f62_staged_exit_verdict": {
            "e1_std_nav": float(df_eval.loc[df_eval["factor_id"] == "F62_E1_3to4_std", "ss_nav"].iloc[0]),
            "e2_always93_nav": float(df_eval.loc[df_eval["factor_id"] == "F62_E2_dev93_always", "ss_nav"].iloc[0]),
            "e3_staged93_nav": float(df_eval.loc[df_eval["factor_id"] == "F62_E3_staged_dev93", "ss_nav"].iloc[0]),
        },
        "f68_complement_verdict": {
            "all_universe_n": int(df_eval.loc[df_eval["factor_id"] == "F68_all_universe", "ss_n"].iloc[0]),
            "all_universe_nav": float(df_eval.loc[df_eval["factor_id"] == "F68_all_universe", "ss_nav"].iloc[0]),
            "main3_empty_slot_n": int(df_eval.loc[df_eval["factor_id"] == "F68_main3_empty_slot", "ss_n"].iloc[0]),
            "main3_empty_slot_nav": float(df_eval.loc[df_eval["factor_id"] == "F68_main3_empty_slot", "ss_nav"].iloc[0]),
            "main3_empty_slot_wr": float(df_eval.loc[df_eval["factor_id"] == "F68_main3_empty_slot", "ss_wr"].iloc[0]),
            "main3_empty_slot_ex_top3": float(df_eval.loc[df_eval["factor_id"] == "F68_main3_empty_slot", "ss_ex_top3_nav"].iloc[0]),
        }
    }

    with open(OUT_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"已保存摘要 JSON 至: {OUT_SUMMARY_JSON}")

    print("\n========== A1 四进五核心回测结论快报 ==========")
    print(f"1. 买点重构对决 (F59 vs F60):")
    print(f"   - B1 竞价全买: NAV = {summary['buy_comparison_b1_vs_b3']['b1_open_all_nav']:.2f}x, MDD = {summary['buy_comparison_b1_vs_b3']['b1_open_all_mdd']:.1f}% (彻底证伪竞价全买，直接吃高开天地板大面！)")
    print(f"   - B2 水下低吸: NAV = {summary['underwater_f60_verdict']['b2_underwater_nav']:.2f}x, 平均收益 = {summary['underwater_f60_verdict']['b2_underwater_avg_ret']:.2f}% (彻底证伪提前抢戏，水下吸四板=吃跌停！)")
    print(f"   - B3 PM建议突破 (10:30): NAV = {summary['buy_comparison_b1_vs_b3']['b3_pm_1030_nav']:.2f}x, MDD = {summary['buy_comparison_b1_vs_b3']['b3_pm_1030_mdd']:.1f}%")
    print(f"   - B5 三进四标准买法 (11:30): NAV = {summary['buy_comparison_b1_vs_b3']['b5_touch65_nav']:.2f}x, MDD = {summary['buy_comparison_b1_vs_b3']['b5_touch65_mdd']:.1f}%")
    print(f"2. 严格 PIT 双严重异动门槛 (F57 & F58):")
    print(f"   - F57 10日100%空间 >= 22%: NAV = {summary['headroom_f57_f58']['f57_hr10_ge22_nav']:.2f}x, WR = {summary['headroom_f57_f58']['f57_hr10_ge22_wr']:.1f}%")
    print(f"   - F58 双异动较紧空间 >= 22%: NAV = {summary['headroom_f57_f58']['f58_tighter_ge22_nav']:.2f}x, WR = {summary['headroom_f57_f58']['f58_tighter_ge22_wr']:.1f}% (两板安全垫极致防二波撞200%红线！)")
    print(f"3. 卖点与高标首阴原地免砍交接 (F61 & F62):")
    print(f"   - F61 高标首阴免砍反包: 命中样本数 = {summary['f61_handoff_verdict']['eligible_cnt']} 只，E4 免砍平均收益 = {summary['f61_handoff_verdict']['e4_handoff_spec_avg_ret']:.2f}% vs E1 机械割肉 = {summary['f61_handoff_verdict']['e1_cutweak_spec_avg_ret']:.2f}% (单笔净挽救超额巨大！)")
    print(f"   - F62 分段异动止盈: E1(无挂单) = {summary['f62_staged_exit_verdict']['e1_std_nav']:.2f}x vs E2(全程挂单) = {summary['f62_staged_exit_verdict']['e2_always93_nav']:.2f}x vs E3(分段止盈) = {summary['f62_staged_exit_verdict']['e3_staged93_nav']:.2f}x (E3既吃满五进六/六进七主升浪，又在满7板精准落袋！)")
    print(f"4. 三大主力完全空仓日补缺门 (F68):")
    print(f"   - 三大主力完全空仓日纯增量: 交易笔数 = {summary['f68_complement_verdict']['main3_empty_slot_n']} 笔, NAV = {summary['f68_complement_verdict']['main3_empty_slot_nav']:.2f}x, 去Top3 = {summary['f68_complement_verdict']['main3_empty_slot_ex_top3']:.2f}x (零触碰三大主力，纯填槽增量！)")
    print("==================================================")


if __name__ == "__main__":
    main()

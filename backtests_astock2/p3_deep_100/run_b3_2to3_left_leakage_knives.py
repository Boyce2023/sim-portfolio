#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_b3_2to3_left_leakage_knives.py — 二进三策略专项因子回测 (F01-F18 全量实测)
涵盖：
- 左端不重复捕捞一进二漏网真龙 (F01-F09)
- 借一进二卖点避飞刀与硬排雷 (F10-F18)
双买法评测：
1. 右侧突破: touch65_1130 + Day4起转13:45护利+真阳免死 (pm1345_5m, cut_weak, use_yang_imm=True)
2. 竞价开盘: 09:25 open + Day4起转13:45护利+真阳免死
严格遵守 D12 (零 yfinance), D15 (单仓+按日等权+三期+沪深300净超额+去Top3), SQLite mode=ro。
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
AST2 = f"{ROOT}/sim-portfolio/backtests_astock2"
OUT_ROOT = f"{AST2}/p3_deep_100"
os.makedirs(OUT_ROOT, exist_ok=True)

if AST2 not in sys.path:
    sys.path.insert(0, AST2)
if OUT_ROOT not in sys.path:
    sys.path.insert(0, OUT_ROOT)

from common_eval_harness import eval_factor_slice, load_production_3_ledgers, CSI_BENCH
from core_3to4_5m_engine import sim_buy_5m, sim_exit_5m
from p2_2to3.rd_true5m_2to3_audit import load_all_local_5m

FEE = 0.0020


def sim_pool_trajectories(df, cb_map, bars_5m, buy_mode):
    """
    计算二进三全量样本在指定买法下的真实成交与退出轨迹
    买入模式: touch65_1130 或 open
    退出模式: pm1345_5m + cut_weak + use_yang_imm=True (Day4起转13:45护利+真阳免死)
    """
    out = [None] * len(df)
    for idx, r in enumerate(df.itertuples(index=False)):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)[:10]
        cb = cb_map.get(c6)
        if cb is None:
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1:
            continue
        has_b5 = (c6, bd) in bars_5m
        if buy_mode == "open":
            op, zt = float(cb["open"][pos]), float(cb["zt_px"][pos])
            if op >= zt - 0.005:
                continue
            bpx, bhh = op, 925
        else:
            if has_b5:
                bpx, bhh = sim_buy_5m(c6, bd, cb, pos, bars_5m, buy_mode)
            else:
                op, pc, hi, zt = float(cb["open"][pos]), float(cb["pre_c"][pos]), float(cb["high"][pos]), float(cb["zt_px"][pos])
                trig = max(pc * 1.065, op)
                if op >= zt - 0.005 or trig >= zt - 0.005 or hi < trig:
                    continue
                bpx, bhh = max(op, trig), 1000
            if bpx is None:
                continue

        ex_dt, spx, adjs, hb, shh = sim_exit_5m(
            c6, cb, pos, bars_5m,
            exit_mode="pm1345_5m",
            day5_unsealed_mode="cut_weak",
            use_yang_imm=True
        )
        net_r = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        out[idx] = {
            "code": c6,
            "name": r.name,
            "buy_date": bd,
            "buy_hhmm": bhh,
            "exit_date": ex_dt,
            "exit_hhmm": shh,
            "hold_bars": hb,
            "net_ret": float(net_r),
            "is_zt_buy": bool(cb["is_zt"][pos])
        }
    return out


def main():
    t_start = time.time()
    print("[1/5] 加载二进三母表与生产台账...")
    df23 = pd.read_parquet(f"{AST2}/p2_2to3/cand_2to3_enriched.parquet")
    df23["c6"] = df23["code"].astype(str).str.zfill(6)
    df23["buy_date"] = df23["buy_date"].astype(str).str[:10]
    df23["sig_date"] = df23["sig_date"].astype(str).str[:10]

    with open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl", "rb") as f:
        cb_map = pickle.load(f)["code_bars"]

    codes = set(df23["c6"])
    bars_5m = load_all_local_5m(codes)
    prod_ledgers = load_production_3_ledgers()
    v18_ledger = prod_ledgers["1to2"]
    print(f"  cand_2to3 样本数: {len(df23)}, 5m 对数: {len(bars_5m)}, V18 笔数: {len(v18_ledger)}")

    print("[2/5] 预计算全样本双买法退出轨迹 (Day4起13:45护利+真阳免死)...")
    trajs_t65 = sim_pool_trajectories(df23, cb_map, bars_5m, "touch65_1130")
    trajs_opn = sim_pool_trajectories(df23, cb_map, bars_5m, "open")

    df_t65 = df23.copy()
    df_t65["net_ret"] = [x["net_ret"] if x else np.nan for x in trajs_t65]
    df_t65["exit_date"] = [x["exit_date"] if x else "" for x in trajs_t65]

    df_opn = df23.copy()
    df_opn["net_ret"] = [x["net_ret"] if x else np.nan for x in trajs_opn]
    df_opn["exit_date"] = [x["exit_date"] if x else "" for x in trajs_opn]

    base_t65_mean = float(df_t65["net_ret"].dropna().mean())
    base_opn_mean = float(df_opn["net_ret"].dropna().mean())
    print(f"  基准均值: touch65_1130={base_t65_mean*100:+.2f}%, open={base_opn_mean*100:+.2f}%")

    print("[3/5] 构建首板、同题材竞价与 5m 盘口关联特征...")
    # 3.1 首板日与二板日特征 (Day1 & Day2)
    n = len(df23)
    d1_is_yizi = np.zeros(n, dtype=bool)
    d2_open_pct = np.zeros(n, dtype=float)
    d1_tightness = np.zeros(n, dtype=float)

    for i, r in enumerate(df23.itertuples(index=False)):
        c6, bd = r.c6, r.buy_date
        cb = cb_map.get(c6)
        if not cb:
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 2:
            continue
        p_d2, p_d1 = pos - 1, pos - 2
        d1_is_yizi[i] = bool(cb["is_yizi"][p_d1])
        d2_open_pct[i] = float(cb["open"][p_d2] / cb["pre_c"][p_d2] - 1.0) if cb["pre_c"][p_d2] > 0 else 0.0

        cl1, hi1, op1, pc1 = float(cb["close"][p_d1]), float(cb["high"][p_d1]), float(cb["open"][p_d1]), float(cb["pre_c"][p_d1])
        lo1 = float(cb["low"][p_d1])
        l_pct1 = (lo1 / pc1 - 1.0) if pc1 > 0 else 0.0
        body1 = (cl1 - op1) / pc1 if pc1 > 0 else 0.0
        d1_tightness[i] = (
            (30.0 if cl1 >= hi1 - 0.005 else 0.0)
            + np.clip(l_pct1 * 100.0, -10.0, 10.0) * 1.5
            + np.clip(body1 * 100.0, 0.0, 10.0) * 2.0
        )

    # 3.2 同题材老二卡位 (F06) 与冲二板失败股连坐 (F12)
    df01 = pd.read_parquet(
        f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/cand_0to1_firstboard.parquet",
        columns=["code", "buy_date", "plate", "is_zt_today"]
    )
    df1_zt = df01[df01["is_zt_today"] == True].copy()
    df1_zt["c6"] = df1_zt["code"].astype(str).str.zfill(6)
    df1_zt["d1_dt"] = df1_zt["buy_date"].astype(str).str[:10]

    d2_records = []
    for r in df1_zt.itertuples(index=False):
        c6 = r.c6
        cb = cb_map.get(c6)
        if not cb:
            continue
        pos1 = cb["date_to_pos"].get(r.d1_dt, -1)
        if pos1 < 0 or pos1 >= len(cb["dts"]) - 1:
            continue
        pos2 = pos1 + 1
        d2_dt = cb["dts"][pos2]
        d2_op = float(cb["open"][pos2] / cb["pre_c"][pos2] - 1.0) if cb["pre_c"][pos2] > 0 else 0.0
        d2_zt = bool(cb["is_zt"][pos2])
        d2_touch = bool(cb["high"][pos2] >= cb["zt_px"][pos2] - 0.005)
        d3_dt = cb["dts"][pos2 + 1] if pos2 + 1 < len(cb["dts"]) else ""
        d3_op = float(cb["open"][pos2 + 1] / cb["pre_c"][pos2 + 1] - 1.0) if pos2 + 1 < len(cb["dts"]) and cb["pre_c"][pos2 + 1] > 0 else 0.0
        d2_records.append({
            "c6": c6, "plate": str(r.plate), "d1_dt": r.d1_dt, "d2_dt": d2_dt, "d2_op": d2_op,
            "d2_is_zt": d2_zt, "d2_touch": d2_touch, "d3_dt": d3_dt, "d3_op": d3_op
        })
    df_d2_all = pd.DataFrame(d2_records)

    usurp_pairs = set()
    for (d2, pl), g in df_d2_all[(df_d2_all["plate"] != "") & (df_d2_all["plate"] != "其他")].groupby(["d2_dt", "plate"]):
        if len(g) >= 2:
            g_srt = g.sort_values("d2_op", ascending=False)
            top1 = g_srt.iloc[0]
            if not top1["d2_is_zt"]:
                for r_k in range(1, min(3, len(g_srt))):
                    sub = g_srt.iloc[r_k]
                    if sub["d2_is_zt"]:
                        usurp_pairs.add((sub["c6"], d2))

    nuke_plate_days = set()
    for (d3, pl), g in df_d2_all[(df_d2_all["plate"] != "") & (df_d2_all["plate"] != "其他") & (df_d2_all["d3_dt"] != "")].groupby(["d3_dt", "plate"]):
        fails = g[g["d2_touch"] & (~g["d2_is_zt"])]
        if len(fails) >= 1:
            avg_op3 = fails["d3_op"].mean()
            if avg_op3 < -0.03:
                nuke_plate_days.add((d3, pl))

    # 3.3 数据库提取 Day2 14:30 尾盘炸板 (F11)
    db_p = f"{AST2}/data_5y/firstboard_5m_5y_pit.db"
    con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
    sql_late = """
    SELECT sec_code, substr(bar_time,1,10) as dt, min(low) as min_lo, max(close) as max_cl
    FROM firstboard_5m_kline
    WHERE day_type="D2" AND substr(bar_time,12,5) >= "14:30"
    GROUP BY sec_code, substr(bar_time,1,10)
    """
    df_d2_late = pd.read_sql_query(sql_late, con)
    con.close()

    late_blown_map = {}
    for r in df_d2_late.itertuples(index=False):
        c6, dt = str(r.sec_code).zfill(6), str(r.dt)
        cb = cb_map.get(c6)
        if not cb:
            continue
        pos = cb["date_to_pos"].get(dt, -1)
        if pos < 0:
            continue
        zt = float(cb["zt_px"][pos])
        late_blown_map[(c6, dt)] = bool(r.min_lo < zt - 0.01)

    # 3.4 Day3 5m 均价线站稳门 (F10)
    f10_stand_firm_map = {}
    f10_trap_map = {}
    for r in df23.itertuples(index=False):
        c6, bd = r.c6, r.buy_date
        arr = bars_5m.get((c6, bd))
        if arr is None or len(arr) < 2:
            continue
        cb = cb_map.get(c6)
        if not cb:
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0:
            continue
        pc = float(cb["pre_c"][pos])
        op = float(cb["open"][pos])
        zt = float(cb["zt_px"][pos])
        trig = max(pc * 1.065, op)
        if trig >= zt - 0.005:
            continue

        cum_v, cum_a = 0.0, 0.0
        for i in range(len(arr)):
            hhmm = int(arr[i, 0])
            if hhmm > 1130:
                break
            bo, bh, bl, bc, bv, ba = arr[i, 1], arr[i, 2], arr[i, 3], arr[i, 4], arr[i, 5], arr[i, 6]
            cum_v += bv
            cum_a += ba
            vwap = cum_a / cum_v if cum_v > 0 else bc
            if bh >= trig:
                fill_px = max(bo, trig)
                lead_vwap = fill_px / vwap - 1.0
                prior_diffs = [(arr[k, 3] / (np.sum(arr[:k+1, 6]) / max(1.0, np.sum(arr[:k+1, 5]))) - 1.0) for k in range(i+1)]
                min_diff = min(prior_diffs)
                # 站稳门: 站稳 VWAP 上方 >= 0.8% 且此前跌破未超 2.5%
                if lead_vwap >= 0.008 and min_diff >= -0.025:
                    f10_stand_firm_map[(c6, bd)] = True
                else:
                    f10_trap_map[(c6, bd)] = True
                break

    # 3.5 滚动 20 日二进三高开封板率传感器 (F18)
    daily_ho = df23[df23["open_pct"] >= 0.02].groupby("buy_date").agg(
        n_ho=("code", "count"),
        n_ho_zt=("is_zt_today", lambda s: int(s.sum()))
    ).reset_index()
    all_dts = sorted(df23["buy_date"].unique())
    daily_full = pd.DataFrame({"buy_date": all_dts}).merge(daily_ho, on="buy_date", how="left").fillna(0)
    daily_full["roll_ho"] = daily_full["n_ho"].rolling(20, min_periods=5).sum().shift(1).fillna(0)
    daily_full["roll_ho_zt"] = daily_full["n_ho_zt"].rolling(20, min_periods=5).sum().shift(1).fillna(0)
    daily_full["sensor_20d"] = np.where(daily_full["roll_ho"] > 0, daily_full["roll_ho_zt"] / daily_full["roll_ho"], 0.35)
    f18_sensor_map = dict(zip(daily_full["buy_date"], daily_full["sensor_20d"]))

    # 3.6 中军反超伴生一字 (F09)
    yizi_peers = df23[df23["prev_is_yizi"] & (df23["mcap"] < 90.0) & (df23["plate"] != "") & (df23["plate"] != "其他")]
    peer_max_op = yizi_peers.groupby(["buy_date", "plate"])["open_pct"].max().to_dict()

    print("[4/5] 逐项精确构造 F01 至 F18 因子掩码...")
    # 构造因子掩码字典
    # F01: V18 持仓互斥
    v18_holding_tuples = set()
    for _, row in v18_ledger.iterrows():
        v18_holding_tuples.add((str(row["c6"]).zfill(6), str(row["buy_date"])[:10]))
    in_v18_mask = df23.apply(lambda r: (r["c6"], r["sig_date"]) in v18_holding_tuples, axis=1)

    # F02: 首板一字但二板爆量换手 10%~25% 回封
    f02_mask = (d1_is_yizi == True) & (df23["prev_is_yizi"] == False) & (df23["prev_to"].between(10.0, 25.0))
    f02_ctrl = (d1_is_yizi == True) & (~f02_mask)

    # F03: 二板超抢漏买 Day3 分歧 2%~6%
    is_mon = (df23["gap_days"] >= 3)
    d2_rush = np.where(is_mon, d2_open_pct > 0.088, d2_open_pct > 0.078)
    d3_diverg = df23["open_pct"].between(0.020, 0.060)
    f03_a_mask = d2_rush & (df23["prev_is_yizi"] == False) & d3_diverg
    f03_b_mask = d2_rush & (df23["prev_is_yizi"] == True) & d3_diverg
    f03_all_mask = d2_rush & d3_diverg

    # F04: 午后 11:30 后首封
    f04_all_mask = (df23["first_seal_time"].astype(str) > "11:30:00")
    f04_pm_true5m = []
    for r in df23.itertuples(index=False):
        c6, sd = r.c6, r.sig_date
        has_late = (c6, sd) in late_blown_map
        f04_pm_true5m.append(has_late and (str(r.first_seal_time) >= "13:00:00"))
    f04_pm_true5m = np.array(f04_pm_true5m, dtype=bool)

    # F05: 小微盘 (15<=mcap<40亿) 唯一连板活口 vs 跟风杂毛
    same_plate_2b_cnt = df23.groupby(["sig_date", "plate"])["code"].transform("count")
    is_micro = df23["mcap"].between(15.0, 40.0) & (df23["plate"] != "") & (df23["plate"] != "其他")
    f05_solo = is_micro & (same_plate_2b_cnt == 1)
    f05_cluster = is_micro & (same_plate_2b_cnt >= 2)

    # F06: 篡位卡位老二
    f06_mask = df23.apply(lambda r: (r["c6"], r["sig_date"]) in usurp_pairs, axis=1)

    # F07: 一进二熔断日逆市换手二板活口 + Day3 回暖
    d2_melt = (df23["mkt_fb_open_avg"] < 0) | (df23["mkt_promo_1to2_5d"] < 0.13)
    f07_mask = d2_melt & (df23["prev_is_yizi"] == False) & (df23["mkt_fb_open_avg"] >= 0)

    # F08: 首板紧密度 <37 烂板，二板紧密度跃迁 >=45
    f08_jump = (d1_tightness < 37.0) & (df23["seal_tightness"] >= 45.0)
    f08_ctrl = (d1_tightness >= 45.0) & (df23["seal_tightness"] < 37.0)

    # F09: 中军伴生反超
    f09_mask = []
    for r in df23.itertuples(index=False):
        bd, pl, mc, op = r.buy_date, str(r.plate), float(r.mcap), float(r.open_pct)
        if mc >= 90.0 and (bd, pl) in peer_max_op:
            f09_mask.append(op > peer_max_op[(bd, pl)])
        else:
            f09_mask.append(False)
    f09_mask = np.array(f09_mask, dtype=bool)

    # F10: Day3 5m 均价线站稳门
    f10_stand = df23.apply(lambda r: (r["c6"], r["buy_date"]) in f10_stand_firm_map, axis=1)
    f10_trap = df23.apply(lambda r: (r["c6"], r["buy_date"]) in f10_trap_map, axis=1)

    # F11: 二板 14:30 尾盘炸板排雷
    f11_blown_true5m = df23.apply(lambda r: late_blown_map.get((r["c6"], r["sig_date"]), False) is True, axis=1)
    f11_firm_true5m = df23.apply(lambda r: (r["c6"], r["sig_date"]) in late_blown_map and not late_blown_map[(r["c6"], r["sig_date"])], axis=1)
    f11_proxy = (df23["first_seal_time"].astype(str) >= "14:15:00") & (df23["open_board_count"] >= 1)

    # F12: 同题材昨日冲二板失败股 Day3 竞价均值 <-3% 连坐
    f12_nuke = df23.apply(lambda r: (r["buy_date"], str(r["plate"])) in nuke_plate_days, axis=1)

    # F13: 昨日一进二封板率 >=75% 且同日二板 >=12家 (大高潮次日分歧)
    f13_climax = (df23["mkt_seal_rate_prev"] >= 0.75) & (df23["day_2b_cnt"] >= 12)

    # F14: 纯外行硬蹭
    f14_outsider = (df23["is_pure_outsider"] == True)

    # F15: 退潮脉冲无4板护航 (最高板<4 或 is_dying_pulse)
    f15_dying = (df23["is_dying_pulse"] == True) | (df23["mkt_max_board_prev"] < 4)

    # F16: 8日内互动易 / 重组硬公告
    f16_notice_ir = (df23["has_ir_8d"] == True) | (df23["notice_hard"] == True)

    # F17: 老庄反抽 (前20日涨停>=4)
    f17_old_zhuang = (df23["zt_cnt_pre20"] >= 4)

    # F18: 滚动20日二进三高开封板率传感器
    s_val_col = df23["buy_date"].map(f18_sensor_map).fillna(0.35)
    f18_cold = (s_val_col < 0.28)
    f18_hot = (s_val_col >= 0.45)
    f18_mid = (s_val_col.between(0.28, 0.45))

    factor_catalog = [
        # 基准
        ("BASE_Touch65", "全量基准", np.ones(n, dtype=bool)),
        # 左端漏网真龙 (F01-F09)
        ("F01_all", "F01 一进二V18母表全量", np.ones(n, dtype=bool)),
        ("F01_in_v18_locked", "F01_in: V18持仓锁仓 (重叠捕捞)", in_v18_mask),
        ("F01_ex_v18_clean", "F01_ex: 物理剔除V18持仓 (独立捕捞)", ~in_v18_mask),
        ("F02_yizi1b_heavyto2b", "F02: 首板一字+二板换手10-25%回封龙", f02_mask),
        ("F02_ctrl_other", "F02_ctrl: 首板一字但二板换手非10-25%", f02_ctrl),
        ("F03_A_turnover_rush", "F03A: 二板换手超抢+Day3分歧2-6%", f03_a_mask),
        ("F03_B_yizi_rush", "F03B: 二板一字超抢+Day3分歧2-6%", f03_b_mask),
        ("F03_all_rush_diverg", "F03_all: 二板超抢总集+Day3分歧2-6%", f03_all_mask),
        ("F04_pm_seal_all", "F04_all: 二板午后11:30后首封 (全量)", f04_all_mask),
        ("F04_pm_seal_true5m", "F04_5m: 二板上午未点火午后首封 (真实5m)", f04_pm_true5m),
        ("F05_micro_solo", "F05_solo: 15-40亿小微盘同题材唯一活口", f05_solo),
        ("F05_micro_cluster", "F05_cluster: 15-40亿小微盘同题材多股跟风", f05_cluster),
        ("F06_usurp_leader", "F06: 同题材老二卡位篡位龙", f06_mask),
        ("F07_ice_break", "F07: 一进二熔断日逆市换手活口+次日回暖", f07_mask),
        ("F08_tight_jump", "F08: 首板紧密度<37烂板跃迁二板>=45弱转强", f08_jump),
        ("F08_ctrl_decay", "F08_ctrl: 首板紧密度高二板衰减", f08_ctrl),
        ("F09_heavy_lead", "F09: >90亿中军早盘竞价反超一字小弟领涨", f09_mask),
        # 右端避飞刀与硬排雷 (F10-F18)
        ("F10_vwap_stand", "F10_stand: Day3站稳VWAP+0.8%且未破位 (真实5m)", f10_stand),
        ("F10_vwap_trap", "F10_trap: Day3破均线诱多/VWAP下方 (真实5m)", f10_trap),
        ("F11_late_blown_true5m", "F11_blown: 二板14:30尾盘炸板勉强回封 (真实5m)", f11_blown_true5m),
        ("F11_late_firm_true5m", "F11_firm: 二板14:30尾盘坚决封死 (真实5m)", f11_firm_true5m),
        ("F11_proxy_late_blown", "F11_proxy: 全量代理尾盘炸板 (首封>=14:15且开板)", f11_proxy),
        ("F12_peer_nuke", "F12: 同题材昨日冲板失败股竞价<-3%连坐排雷", f12_nuke),
        ("F13_climax_ex", "F13: 昨日封板率>=75%且二板>=12家大高潮排雷", f13_climax),
        ("F14_pure_outsider", "F14: 纯外行硬蹭硬科技排雷", f14_outsider),
        ("F15_dying_pulse", "F15: 退潮脉冲无4板护航排雷", f15_dying),
        ("F16_notice_ir", "F16: 8日内互动易/重组硬公告排雷", f16_notice_ir),
        ("F17_old_zhuang", "F17: 前20日涨停>=4老庄反抽排雷", f17_old_zhuang),
        ("F18_sensor_cold", "F18_cold: 滚动20日二进三高开封板率冰点 (<28%)", f18_cold),
        ("F18_sensor_hot", "F18_hot: 滚动20日二进三高开封板率过热 (>=45%)", f18_hot),
        ("F18_sensor_mid", "F18_mid: 滚动20日二进三高开封板率平稳 (28-45%)", f18_mid),
    ]

    print("[5/5] 执行两套买法全因子矩阵高颗粒度回测...")
    records = []
    summary_dict = {}

    for fid, name, mask in factor_catalog:
        sub_t65 = df_t65[mask]
        sub_opn = df_opn[mask]

        m_t65 = eval_factor_slice(sub_t65, ret_col="net_ret", exit_col="exit_date", rank_col="open_pct", base_mean=base_t65_mean)
        m_opn = eval_factor_slice(sub_opn, ret_col="net_ret", exit_col="exit_date", rank_col="open_pct", base_mean=base_opn_mean)

        row_t65 = {
            "factor_id": fid,
            "factor_name": name,
            "buy_mode": "touch65_1130_pm1345_yang",
            "base_mean_pct": round(base_t65_mean * 100, 2),
            **m_t65
        }
        row_opn = {
            "factor_id": fid,
            "factor_name": name,
            "buy_mode": "open0925_pm1345_yang",
            "base_mean_pct": round(base_opn_mean * 100, 2),
            **m_opn
        }
        records.append(row_t65)
        records.append(row_opn)

        summary_dict[fid] = {
            "name": name,
            "n_matched": int(mask.sum()),
            "touch65": {
                "n_raw": m_t65["n_raw"],
                "avg_ret": m_t65["avg_ret"],
                "delta_vs_base": m_t65["delta_vs_base"],
                "wr_raw": m_t65["wr_raw"],
                "payoff_raw": m_t65["payoff_raw"],
                "ss_nav": m_t65["ss_nav"],
                "ss_mdd": m_t65["ss_mdd"],
                "ss_excess_5y": m_t65["ss_net_excess_5y"],
                "dual_same_sign": m_t65["dual_same_sign"],
                "pos_years": m_t65.get("pos_years_vs_base", m_t65.get("pos_years_raw", 0)),
            },
            "open": {
                "n_raw": m_opn["n_raw"],
                "avg_ret": m_opn["avg_ret"],
                "delta_vs_base": m_opn["delta_vs_base"],
                "wr_raw": m_opn["wr_raw"],
                "payoff_raw": m_opn["payoff_raw"],
                "ss_nav": m_opn["ss_nav"],
                "ss_mdd": m_opn["ss_mdd"],
                "ss_excess_5y": m_opn["ss_net_excess_5y"],
                "dual_same_sign": m_opn["dual_same_sign"],
                "pos_years": m_opn.get("pos_years_vs_base", m_opn.get("pos_years_raw", 0)),
            }
        }
        print(f"  [{fid:24s}] n={mask.sum():4d} | Touch65: n={m_t65['n_raw']:4d} avg={m_t65['avg_ret']:+5.2f}% (d={m_t65['delta_vs_base']:+5.2f}%) ssNAV={m_t65['ss_nav']:5.2f}x | Open: n={m_opn['n_raw']:4d} avg={m_opn['avg_ret']:+5.2f}% (d={m_opn['delta_vs_base']:+5.2f}%) ssNAV={m_opn['ss_nav']:5.2f}x")

    # 落盘 CSV
    csv_df = pd.DataFrame(records)
    csv_path = f"{OUT_ROOT}/b3_2to3_left_leakage_and_knives_F01_F18.csv"
    csv_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n[+] 结果 CSV 落盘: {csv_path} (行数: {len(csv_df)})")

    # 落盘 JSON
    json_path = f"{OUT_ROOT}/b3_summary.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "base_means": {"touch65": round(base_t65_mean * 100, 2), "open": round(base_opn_mean * 100, 2)},
            "csi_bench": CSI_BENCH,
            "factors": summary_dict,
            "elapsed_sec": round(time.time() - t_start, 2)
        }, f, ensure_ascii=False, indent=2)
    print(f"[+] 结果 JSON 落盘: {json_path}")
    print(f"[DONE] 全部回测完成，耗时: {time.time()-t_start:.2f}s")


if __name__ == "__main__":
    main()

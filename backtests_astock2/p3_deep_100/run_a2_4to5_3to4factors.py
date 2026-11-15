#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
A2 专项回测：把《三进四 V3.4》全部骨架、打分项与梯队日历因子在四进五（10cm主板非ST buyable_open）上逐个挨个回测。
输出模式A（右侧突破 open_pct>=0.01 & touch65_1130 + pm1345_5m + yang_imm）与模式B（竞价 09:25 open + pm1345_5m + yang_imm），
以及在 mkt_max_board_prev <= 5 骨架上的边际增减消融。
"""
import os
import sys
import json
import pickle
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
ASTOCK2_DIR = f"{SIM_DIR}/backtests_astock2"
P3_DIR = f"{ASTOCK2_DIR}/p3_deep_100"
MAT_DIR = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
HD_DIR = f"{SIM_DIR}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"

if ASTOCK2_DIR not in sys.path:
    sys.path.insert(0, ASTOCK2_DIR)
if P3_DIR not in sys.path:
    sys.path.insert(0, P3_DIR)

from common_eval_harness import eval_factor_slice, CSI_BENCH, CSI_MAP, ALL_CSI_DTS
from core_3to4_5m_engine import sim_buy_5m, sim_exit_5m

FEE = 0.0020
OUT_CSV = f"{P3_DIR}/a2_4to5_all_3to4_factors.csv"
OUT_JSON = f"{P3_DIR}/a2_summary.json"


def load_merged_5m_bars(needed_keys: set) -> dict:
    """加载三份 5m K 线源文件并合并为 (c6, date) -> ndarray。"""
    paths = [
        f"{ASTOCK2_DIR}/p2_4to5/cand_4to5_5m_bars.parquet",
        f"{ASTOCK2_DIR}/data_5y/cand_3to4_5m_bars.parquet",
        f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet",
    ]
    bars_map = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        d = pd.read_parquet(p, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
        d["c6"] = d["c6"].astype(str).str.zfill(6)
        d["date"] = d["date"].astype(str).str[:10]
        rem = needed_keys - set(bars_map.keys())
        if not rem:
            break
        mask = pd.MultiIndex.from_frame(d[["c6", "date"]]).isin(rem)
        sub = d.loc[mask].sort_values(["c6", "date", "hhmm_int"])
        for (c6, dt_s), grp in sub.groupby(["c6", "date"], sort=False):
            if (c6, dt_s) not in bars_map:
                bars_map[(c6, dt_s)] = grp[
                    ["hhmm_int", "open", "high", "low", "close", "volume", "amount"]
                ].to_numpy(dtype=float)
    return bars_map


def enrich_pit_features(df: pd.DataFrame, cb_map: dict) -> pd.DataFrame:
    """补算/纠偏严格 PIT 特征：has_ex_reg/stock_reg/tox、F42、F44、F63、csi_1d_prev、日历星期与月份。"""
    df = df.copy()
    # 1. 补算同题材 Day4 首板在 Day5 09:25 的 plate_fb_ho_cnt 与 plate_fb_yz_cnt (F42)
    df_1b = pd.read_parquet(
        f"{MAT_DIR}/cand_0to1_firstboard.parquet",
        columns=["code", "buy_date", "plate", "is_zt_today"],
    )
    df_1b_zt = df_1b[df_1b["is_zt_today"] == True].copy()
    d5_ops, d5_yzs = [], []
    for r1 in df_1b_zt.itertuples(index=False):
        c1 = str(r1.code).zfill(6)
        cb1 = cb_map.get(c1)
        p1 = cb1["date_to_pos"].get(str(r1.buy_date), -1) if cb1 else -1
        if cb1 and 0 <= p1 < len(cb1["dts"]) - 1 and cb1["pre_c"][p1 + 1] > 0:
            op_n = float(cb1["open"][p1 + 1] / cb1["pre_c"][p1 + 1] - 1.0)
            yz_n = bool(cb1["open"][p1 + 1] >= cb1["zt_px"][p1 + 1] - 0.005)
        else:
            op_n, yz_n = 0.0, False
        d5_ops.append(op_n)
        d5_yzs.append(yz_n)
    df_1b_zt["d5_op"] = d5_ops
    df_1b_zt["d5_yz"] = d5_yzs

    fb_plate_stats = {}
    valid_1b = df_1b_zt[df_1b_zt["plate"].notna() & (df_1b_zt["plate"] != "")]
    for (sd_k, pl), grp in valid_1b.groupby(["buy_date", "plate"], sort=False):
        ops = grp["d5_op"].to_numpy()
        fb_plate_stats[(str(sd_k), str(pl))] = (int((ops >= 0.03).sum()), int(grp["d5_yz"].sum()))

    # 2. 补算 F44 (prev_4b_plus_dt_cnt: 前一日4板及以上高标跌停数)
    dt_b4_dt = defaultdict(int)
    for cb in cb_map.values():
        dts, is_zt, is_dt = cb["dts"], cb["is_zt"], cb["is_dt"]
        cur_stk = 0
        for i in range(len(dts)):
            if cur_stk >= 4 and bool(is_dt[i]):
                dt_b4_dt[str(dts[i])] += 1
            cur_stk = (cur_stk + 1) if bool(is_zt[i]) else 0

    # 3. 补算 F63 昨日5板老龙在 Day5 竞价最小开盘涨幅
    hd = pd.read_parquet(f"{MAT_DIR}/cand_high_dragon.parquet", columns=["buy_date", "prev_streak", "open_pct"])
    b5_min_open = hd[hd["prev_streak"] == 5].groupby("buy_date")["open_pct"].min().to_dict()

    # 4. 监管函/重点监控/恶毒公告 (严格 PIT <= sig_date，修正 ex_reg SH/SZ 键值 bug)
    with open(f"{HD_DIR}/part1_cache.pkl", "rb") as f:
        pkg = pickle.load(f)
    stock_reg, ex_reg, tox_dates = pkg[10], pkg[11], pkg[12]

    # 5. CSI300 交易日历与严格 PIT csi_1d_prev (基于 sig_date)
    csi_pos = {d: i for i, d in enumerate(ALL_CSI_DTS)}

    ho_cnts, yz_cnts, b4_dt_cnts, b5_op_mins = [], [], [], []
    s_reg_pit, e_reg_pit, tox_pit, csi1d_pit = [], [], [], []
    post_hol_mon, pre_hol_fri = [], []

    for r in df.itertuples(index=False):
        c6, sd, bd, pl = str(r.code).zfill(6), str(r.sig_date), str(r.buy_date), str(r.plate)
        fb = fb_plate_stats.get((sd, pl), (0, 0))
        ho_cnts.append(fb[0])
        yz_cnts.append(fb[1])
        b4_dt_cnts.append(int(dt_b4_dt.get(sd, 0)))
        b5_op_mins.append(float(b5_min_open.get(bd, 9.9)))

        ci = csi_pos.get(sd, -1)
        d_m10 = ALL_CSI_DTS[max(0, ci - 10)] if ci >= 0 else "1990-01-01"
        d_m5 = ALL_CSI_DTS[max(0, ci - 5)] if ci >= 0 else "1990-01-01"
        ex_k = "SH" if c6.startswith("60") else "SZ"
        s_reg_pit.append(int(any(d_m10 <= x <= sd for x in stock_reg.get(c6, ()))))
        e_reg_pit.append(int(any(d_m5 <= x <= sd for x in ex_reg.get(ex_k, ()))))
        tox_pit.append(int(any(d_m10 <= x <= sd for x in tox_dates.get(c6, ()))))
        csi1d_pit.append(float(CSI_MAP[sd] / CSI_MAP[ALL_CSI_DTS[ci - 1]] - 1.0) if ci >= 1 else 0.0)

        bi = csi_pos.get(bd, -1)
        gp = (pd.Timestamp(bd) - pd.Timestamp(ALL_CSI_DTS[bi - 1])).days if bi > 0 else 1
        gn = (pd.Timestamp(ALL_CSI_DTS[bi + 1]) - pd.Timestamp(bd)).days if (0 <= bi < len(ALL_CSI_DTS) - 1) else (
            3 if pd.Timestamp(bd).weekday() == 4 else 1
        )
        post_hol_mon.append(gp >= 3)
        pre_hol_fri.append(gn >= 3)

    df["plate_fb_ho_cnt"] = ho_cnts
    df["plate_fb_yz_cnt"] = yz_cnts
    df["prev_4b_plus_dt_cnt"] = b4_dt_cnts
    df["prev_5b_min_open"] = b5_op_mins
    df["has_stock_reg_pit"] = s_reg_pit
    df["has_ex_reg_pit"] = e_reg_pit
    df["has_tox_notice_pit"] = tox_pit
    df["csi_1d_prev_pit"] = csi1d_pit
    df["is_post_holiday_or_mon_pit"] = post_hol_mon
    df["is_pre_holiday_or_fri_pit"] = pre_hol_fri
    dt_obj = pd.to_datetime(df["buy_date"])
    df["dow"] = dt_obj.dt.dayofweek + 1
    df["buy_month"] = dt_obj.dt.month
    return df


def sim_one_trade(c6: str, bd: str, cb: dict, bars_5m_map: dict, mode: str):
    """
    模拟单笔交易：
      mode='A': open_pct >= 0.01 & touch65_1130 + pm1345_5m + cut_weak + yang_imm=True
      mode='B': 09:25 open + pm1345_5m + cut_weak + yang_imm=True
    无 5m K 线时使用 code_bars_5y.pkl 真实日线高低开收精确回退，并记录 5m 覆盖标记。
    """
    if cb is None:
        return None
    pos = cb["date_to_pos"].get(bd, -1)
    if pos < 0 or pos >= len(cb["dts"]) - 1:
        return None
    op = float(cb["open"][pos])
    pc = float(cb["pre_c"][pos])
    zt = float(cb["zt_px"][pos])
    if pc <= 0 or op >= zt - 0.005:
        return None

    used_buy_5m = False
    if mode == "A":
        if (op / pc - 1.0) < 0.01:
            return None
        trig = pc * 1.065
        if trig >= zt - 0.005:
            return None
        if op >= trig:
            bpx, bhh = op, 925
            used_buy_5m = (c6, bd) in bars_5m_map
        elif (c6, bd) in bars_5m_map:
            used_buy_5m = True
            bpx, bhh = sim_buy_5m(c6, bd, cb, pos, bars_5m_map, "touch65_1130")
        else:
            # 日线精确回退：未触及 +6.5% 或一字涨停不成交；触及则按 max(open, +6.5%) 成交
            if float(cb["low"][pos]) >= zt - 0.005 or float(cb["high"][pos]) < trig:
                return None
            bpx, bhh = float(max(op, trig)), 1030
    else:
        bpx, bhh = sim_buy_5m(c6, bd, cb, pos, bars_5m_map, "open")
        used_buy_5m = (c6, bd) in bars_5m_map

    if bpx is None:
        return None

    ex_dt, spx, adjs, hb, shh = sim_exit_5m(
        c6, cb, pos, bars_5m_map, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True
    )
    pos_ex = cb["date_to_pos"].get(ex_dt, pos + 1)
    used_hold_5m = any((c6, str(cb["dts"][k])) in bars_5m_map for k in range(pos + 1, min(len(cb["dts"]), pos_ex + 1)))
    net_ret = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
    return {
        "net_ret": float(net_ret),
        "exit_date": str(ex_dt),
        "buy_hhmm": int(bhh),
        "exit_hhmm": int(shh),
        "hold_bars": int(hb),
        "buy_5m_cov": bool(used_buy_5m),
        "hold_5m_cov": bool(used_hold_5m),
    }


def build_factor_specs(df: pd.DataFrame):
    """构造全部 30 个《三进四 V3.4》因子（23 组共 75 个细分条件与正反对比）。"""
    fst = df["first_seal_time"].astype(str)
    tox_reg = (df["has_tox_notice_pit"] == 1) | (df["has_stock_reg_pit"] == 1)
    dual45 = (df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0)
    f63 = (df["mkt_max_board_prev"] == 5) & (df["prev_5b_min_open"] < -0.03) & (df["open_pct"] >= 0.025)
    csi_kill = (df["csi_1d_prev_pit"] <= -0.020) | (df["csi300_ret5"] <= -0.030)

    specs = [
        ("01_prev_is_yizi", "F01a_prev_is_yizi_False (四板换手)", df["prev_is_yizi"] == False, "pos"),
        ("01_prev_is_yizi", "F01b_prev_is_yizi_True (四板一字)", df["prev_is_yizi"] == True, "neg"),
        ("02_open_board_count", "F02a_open_board_ge1 (四板曾开板换手)", df["open_board_count"] >= 1, "pos"),
        ("02_open_board_count", "F02b_open_board_eq0 (四板未开板死封)", df["open_board_count"] == 0, "neg"),
        ("03_tox_or_reg", "F03a_has_tox_or_reg (立案减持或个股监管函)", tox_reg, "neg"),
        ("03_tox_or_reg", "F03b_no_tox_no_reg (零立案减持零个股监管)", ~tox_reg, "pos"),
        ("04_open_pct_bins", "F04_1_open_lt_neg3 (竞价<-3%)", df["open_pct"] < -0.03, "neg"),
        ("04_open_pct_bins", "F04_2_open_neg3_to_0 (竞价-3%~0%)", (df["open_pct"] >= -0.03) & (df["open_pct"] < 0.0), "neg"),
        ("04_open_pct_bins", "F04_3_open_0_to_2 (竞价0%~2%)", (df["open_pct"] >= 0.0) & (df["open_pct"] < 0.02), "bin"),
        ("04_open_pct_bins", "F04_4_open_2_to_3 (竞价2%~3%)", (df["open_pct"] >= 0.02) & (df["open_pct"] < 0.03), "bin"),
        ("04_open_pct_bins", "F04_5_open_3_to_6 (竞价3%~6%)", (df["open_pct"] >= 0.03) & (df["open_pct"] < 0.06), "pos"),
        ("04_open_pct_bins", "F04_6_open_6_to_85 (竞价6%~8.5%)", (df["open_pct"] >= 0.06) & (df["open_pct"] < 0.085), "bin"),
        ("04_open_pct_bins", "F04_7_open_85_to_92 (竞价8.5%~9.2%)", (df["open_pct"] >= 0.085) & (df["open_pct"] <= 0.092), "bin"),
        ("04_open_pct_bins", "F04_8_open_gt_92 (竞价>9.2%逼一字)", df["open_pct"] > 0.092, "neg"),
        ("04_open_pct_zone", "F04_A_open_20_85 (竞价2.0%~8.5%)", df["open_pct"].between(0.020, 0.085), "pos"),
        ("04_open_pct_zone", "F04_B_open_30_92 (竞价3.0%~9.2%)", df["open_pct"].between(0.030, 0.092), "pos"),
        ("05_top1_4b_open", "F05a_is_top1_4b_open_True (四板竞价头名)", df["is_top1_4b_open"] == 1, "pos"),
        ("05_top1_4b_open", "F05b_is_top1_4b_open_False (非竞价头名)", df["is_top1_4b_open"] == 0, "neg"),
        ("06_sole_vs_rival", "F06a_is_sole_4b_True (全场唯一四板独苗)", df["is_sole_4b"] == 1, "pos"),
        ("06_sole_vs_rival", "F06b_b4_rival_cnt_ge2 (多只四板同台互掐)", df["b4_rival_cnt"] >= 2, "neg"),
        ("07_dual45_gate", "F07a_dual45_pass (lock>=45或real_free>=45)", dual45, "pos"),
        ("07_dual45_gate", "F07b_dual45_fail (双45均不达标)", ~dual45, "neg"),
        ("07_lock_top10", "F07c_lock_top10_ge50 (前十锁仓>=50%)", df["lock_top10"] >= 50.0, "pos"),
        ("07_lock_top10", "F07d_lock_top10_ge55 (前十锁仓>=55%)", df["lock_top10"] >= 55.0, "pos"),
        ("07_real_free_mcap", "F07e_rfmcap_lt15 (真流通<15亿)", df["real_free_mcap"] < 15.0, "bin"),
        ("07_real_free_mcap", "F07f_rfmcap_15_35 (真流通15~35亿)", (df["real_free_mcap"] >= 15.0) & (df["real_free_mcap"] < 35.0), "bin"),
        ("07_real_free_mcap", "F07g_rfmcap_35_80 (真流通35~80亿)", (df["real_free_mcap"] >= 35.0) & (df["real_free_mcap"] <= 80.0), "bin"),
        ("07_real_free_mcap", "F07h_rfmcap_gt80 (真流通>80亿)", df["real_free_mcap"] > 80.0, "neg"),
        ("08_prev_to", "F08a_prev_to_lt85 (昨日换手<8.5%)", df["prev_to"] < 8.5, "neg"),
        ("08_prev_to", "F08b_prev_to_85_18 (昨日换手8.5%~18%)", (df["prev_to"] >= 8.5) & (df["prev_to"] < 18.0), "pos"),
        ("08_prev_to", "F08c_prev_to_18_28 (昨日换手18%~28%)", (df["prev_to"] >= 18.0) & (df["prev_to"] <= 28.0), "pos"),
        ("08_prev_to", "F08d_prev_to_85_31 (昨日换手8.5%~31%)", df["prev_to"].between(8.5, 31.0), "pos"),
        ("08_prev_to", "F08e_prev_to_gt31 (昨日换手>31%过热)", df["prev_to"] > 31.0, "neg"),
        ("09_first_seal_time", "F09a_fst_le_0935 (<=09:35秒封过热)", fst <= "09:35:00", "neg"),
        ("09_first_seal_time", "F09b_fst_0936_1030 (09:36~10:30早盘换手回封)", (fst > "09:35:00") & (fst <= "10:30:00"), "pos"),
        ("09_first_seal_time", "F09c_fst_1031_1130 (10:31~11:30上午封板)", (fst > "10:30:00") & (fst <= "11:30:00"), "bin"),
        ("09_first_seal_time", "F09d_fst_gt_1130 (>11:30午后逆势封板)", fst > "11:30:00", "bin"),
        ("10_px_d4", "F10a_px_d4_le15 (四板股价<=15元)", df["px_d4"] <= 15.0, "pos"),
        ("10_px_d4", "F10b_px_d4_le20 (四板股价<=20元)", df["px_d4"] <= 20.0, "pos"),
        ("10_px_d4", "F10c_px_d4_20_32 (四板股价20~32元)", (df["px_d4"] > 20.0) & (df["px_d4"] <= 32.0), "bin"),
        ("10_px_d4", "F10d_px_d4_gt32 (四板股价>32元)", df["px_d4"] > 32.0, "neg"),
        ("11_mkt_max_board", "F11a_mkt_max_eq4 (昨日最高板==4即自身空间龙)", df["mkt_max_board_prev"] == 4, "pos"),
        ("11_mkt_max_board", "F11b_mkt_max_le5 (昨日最高板<=5破局窗)", df["mkt_max_board_prev"] <= 5, "pos"),
        ("11_mkt_max_board", "F11c_mkt_max_ge6 (头顶>=6板老龙压制)", df["mkt_max_board_prev"] >= 6, "neg"),
        ("12_F63_usurp", "F12_F63_gaodi_usurp (5板老龙低开<-3%且4板高开>=2.5%)", f63, "pos"),
        ("13_p_elo", "F13a_p_elo_ge115 (题材强度p_elo>=115)", df["p_elo"] >= 115.0, "pos"),
        ("13_p_elo", "F13b_p_elo_ge105 (题材强度p_elo>=105)", df["p_elo"] >= 105.0, "pos"),
        ("13_p_elo", "F13c_p_elo_le95 (题材强度p_elo<=95)", df["p_elo"] <= 95.0, "neg"),
        ("14_mkt_zt_prev", "F14a_mkt_zt_lt35 (昨涨停<35冰点)", df["mkt_zt_prev"] < 35, "bin"),
        ("14_mkt_zt_prev", "F14b_mkt_zt_35_65 (昨涨停35~65缩量抱团温区)", df["mkt_zt_prev"].between(35, 65), "pos"),
        ("14_mkt_zt_prev", "F14c_mkt_zt_35_85 (昨涨停35~85温热区)", df["mkt_zt_prev"].between(35, 85), "pos"),
        ("14_mkt_zt_prev", "F14d_mkt_zt_ge95 (昨涨停>=95百股高潮分流)", df["mkt_zt_prev"] >= 95, "neg"),
        ("15_has_ex_reg", "F15a_has_ex_reg_True (交易所近5日重点监控密集期)", df["has_ex_reg_pit"] == 1, "neg"),
        ("15_has_ex_reg", "F15b_has_ex_reg_False (非交易所重点监控密集期)", df["has_ex_reg_pit"] == 0, "pos"),
        ("16_surf_yz_buy", "F16a_surf_yz_buy_ge1 (一日游砸盘席位买入)", df["surf_yz_buy"] >= 1, "neg"),
        ("16_surf_yz_buy", "F16b_surf_yz_buy_eq0 (无一日游砸盘席位)", df["surf_yz_buy"] == 0, "pos"),
        ("17_lhb_lh_cnt", "F17a_lhb_lh_eq0 (拉萨席位==0)", df["lhb_lh_cnt"] == 0, "pos"),
        ("17_lhb_lh_cnt", "F17b_lhb_lh_1_2 (拉萨席位1~2个)", df["lhb_lh_cnt"].between(1, 2), "bin"),
        ("17_lhb_lh_cnt", "F17c_lhb_lh_ge3 (拉萨席位>=3散户扎堆)", df["lhb_lh_cnt"] >= 3, "neg"),
        ("18_F42_fb_echelon", "F18a_F42_ho_ge2_yz0 (同题材首板高开>=2且0一字)", (df["plate_fb_ho_cnt"] >= 2) & (df["plate_fb_yz_cnt"] == 0), "pos"),
        ("18_F42_fb_echelon", "F18b_F42_yz_ge1 (同题材首板顶一字>=1抽血)", df["plate_fb_yz_cnt"] >= 1, "neg"),
        ("19_F43_peers_nuke", "F19a_F43_peers_lt_neg15 (同题材队友竞价<-1.5%)", df["plate_peers_open_avg"] < -0.015, "neg"),
        ("19_F43_peers_nuke", "F19b_F43_peers_ge_0 (同题材队友竞价>=0%)", df["plate_peers_open_avg"] >= 0.0, "pos"),
        ("20_prev_high_dt", "F20a_prev_3b_dt_eq0 (昨3板+零跌停)", df["prev_3b_dt_cnt"] == 0, "pos"),
        ("20_prev_high_dt", "F20b_prev_3b_dt_ge2 (昨3板+跌停>=2)", df["prev_3b_dt_cnt"] >= 2, "neg"),
        ("20_prev_high_dt", "F20c_F44_prev_4b_plus_dt_ge1 (昨4板+高标跌停>=1)", df["prev_4b_plus_dt_cnt"] >= 1, "neg"),
        ("20_prev_high_dt", "F20d_F44_prev_4b_plus_dt_eq0 (昨4板+高标零跌停)", df["prev_4b_plus_dt_cnt"] == 0, "pos"),
        ("21_csi_kill", "F21a_csi_kill_True (沪深300急杀破位)", csi_kill, "neg"),
        ("21_csi_kill", "F21b_csi_kill_False (沪深300未急杀)", ~csi_kill, "pos"),
        ("22_calendar_week", "F22a_post_holiday_or_mon_True (周一或节后首日)", df["is_post_holiday_or_mon_pit"] == True, "pos"),
        ("22_calendar_week", "F22b_post_holiday_or_mon_False (非周一/节后首日)", df["is_post_holiday_or_mon_pit"] == False, "bin"),
        ("22_calendar_week", "F22c_F67_thu_fri (周四或周五买入)", df["dow"].isin([4, 5]), "pos"),
        ("22_calendar_week", "F22d_F67_fri_or_pre_hol (周五或节前末日跨周末)", df["is_pre_holiday_or_fri_pit"] == True, "pos"),
        ("23_buy_month", "F23a_buy_month_1_or_5 (1月或5月退潮业绩窗)", df["buy_month"].isin([1, 5]), "neg"),
        ("23_buy_month", "F23b_buy_month_1 (1月业绩雷窗)", df["buy_month"] == 1, "neg"),
        ("23_buy_month", "F23c_buy_month_5 (5月退潮窗)", df["buy_month"] == 5, "neg"),
    ]
    return specs


def eval_with_prefix(df_sub: pd.DataFrame, ret_col: str, exit_col: str, base_mean: float, prefix: str) -> dict:
    m = eval_factor_slice(df_sub, ret_col=ret_col, exit_col=exit_col, rank_col="open_pct", base_mean=base_mean)
    return {f"{prefix}_{k}": v for k, v in m.items()}


def main():
    df_raw = pd.read_parquet(f"{ASTOCK2_DIR}/p2_4to5/cand_4to5_enriched.parquet")
    df = df_raw[df_raw["is_main_10cm"] & df_raw["buyable_open"]].copy().reset_index(drop=True)
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f:
        cb_map = pickle.load(f)["code_bars"]

    df = enrich_pit_features(df, cb_map)

    # 收集所有需要的 (c6, date) 5m 键
    needed_5m = set()
    for r in df.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6)
        if cb is None:
            continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0:
            continue
        needed_5m.add((c6, bd))
        k = pos + 1
        n = len(cb["dts"])
        while k < n and bool(cb["is_zt"][k]):
            needed_5m.add((c6, str(cb["dts"][k])))
            k += 1
        while k < n and bool(cb["is_yizi_dt"][k]):
            needed_5m.add((c6, str(cb["dts"][k])))
            k += 1
        if k < n:
            needed_5m.add((c6, str(cb["dts"][k])))

    bars_5m_map = load_merged_5m_bars(needed_5m)

    # 模拟模式 A 和模式 B
    for mode in ("A", "B"):
        rets, ex_dts, b5m_flags, h5m_flags = [], [], [], []
        for r in df.itertuples(index=False):
            res = sim_one_trade(str(r.code).zfill(6), str(r.buy_date), cb_map.get(str(r.code).zfill(6)), bars_5m_map, mode)
            if res is None:
                rets.append(np.nan)
                ex_dts.append("")
                b5m_flags.append(False)
                h5m_flags.append(False)
            else:
                rets.append(res["net_ret"])
                ex_dts.append(res["exit_date"])
                b5m_flags.append(res["buy_5m_cov"])
                h5m_flags.append(res["hold_5m_cov"])
        df[f"net_ret_{mode}"] = rets
        df[f"exit_date_{mode}"] = ex_dts
        df[f"buy_5m_cov_{mode}"] = b5m_flags
        df[f"hold_5m_cov_{mode}"] = h5m_flags

    # 基准统计与 5m 覆盖率
    valid_A = df[df["net_ret_A"].notna()]
    valid_B = df[df["net_ret_B"].notna()]
    skel_mask = df["mkt_max_board_prev"] <= 5
    skel_A = df[skel_mask & df["net_ret_A"].notna()]
    skel_B = df[skel_mask & df["net_ret_B"].notna()]

    base_mean_A = float(valid_A["net_ret_A"].mean())
    base_mean_B = float(valid_B["net_ret_B"].mean())
    skel_mean_A = float(skel_A["net_ret_A"].mean())
    skel_mean_B = float(skel_B["net_ret_B"].mean())

    base_eval_A = eval_factor_slice(valid_A, "net_ret_A", "exit_date_A", "open_pct", base_mean_A)
    base_eval_B = eval_factor_slice(valid_B, "net_ret_B", "exit_date_B", "open_pct", base_mean_B)
    skel_eval_A = eval_factor_slice(skel_A, "net_ret_A", "exit_date_A", "open_pct", skel_mean_A)
    skel_eval_B = eval_factor_slice(skel_B, "net_ret_B", "exit_date_B", "open_pct", skel_mean_B)

    cov_stats = {
        "pool_buyable_10cm_n": int(len(df)),
        "pool_open_ge_1pct_n": int((df["open_pct"] >= 0.01).sum()),
        "modeA_trades_n": int(len(valid_A)),
        "modeA_buy_5m_cov_pct": round(float(valid_A["buy_5m_cov_A"].mean()) * 100, 2),
        "modeA_hold_5m_cov_pct": round(float(valid_A["hold_5m_cov_A"].mean()) * 100, 2),
        "modeB_trades_n": int(len(valid_B)),
        "modeB_buy_5m_cov_pct": round(float(valid_B["buy_5m_cov_B"].mean()) * 100, 2),
        "modeB_hold_5m_cov_pct": round(float(valid_B["hold_5m_cov_B"].mean()) * 100, 2),
        "csi_bench_5y_pct": round(CSI_BENCH["5y"] * 100, 2),
    }

    specs = build_factor_specs(df)
    rows = []
    # 先写入 4 条基准行
    for bname, mA, mB in [
        ("BASE_FULL_POOL (10cm非ST buyable_open全池)", base_eval_A, base_eval_B),
        ("BASE_SKEL_LE5 (mkt_max_board_prev<=5骨架基准)", skel_eval_A, skel_eval_B),
    ]:
        row = {"group": "00_BASE", "factor_name": bname, "expected_dir": "base", "raw_pool_cnt": int(len(df) if "FULL" in bname else skel_mask.sum())}
        row.update({f"A_{k}": v for k, v in mA.items()})
        row.update({f"B_{k}": v for k, v in mB.items()})
        row.update({f"SKEL_A_{k}": v for k, v in skel_eval_A.items()})
        row.update({f"SKEL_B_{k}": v for k, v in skel_eval_B.items()})
        row.update({
            "SKEL_A_keep_d_avg": 0.0, "SKEL_A_keep_d_nav": 0.0, "SKEL_A_excl_d_avg": 0.0, "SKEL_A_excl_d_nav": 0.0,
            "SKEL_B_keep_d_avg": 0.0, "SKEL_B_keep_d_nav": 0.0, "SKEL_B_excl_d_avg": 0.0, "SKEL_B_excl_d_nav": 0.0,
        })
        rows.append(row)

    for grp, fname, mask, exp_dir in specs:
        m_bool = mask.fillna(False).astype(bool)
        row = {
            "group": grp,
            "factor_name": fname,
            "expected_dir": exp_dir,
            "raw_pool_cnt": int(m_bool.sum()),
        }
        row.update(eval_with_prefix(df[m_bool], "net_ret_A", "exit_date_A", base_mean_A, "A"))
        row.update(eval_with_prefix(df[m_bool], "net_ret_B", "exit_date_B", base_mean_B, "B"))

        # mkt_max_board_prev <= 5 骨架上的边际增减消融 (keep = skel & mask, excl = skel & ~mask)
        sk_keep_A = eval_with_prefix(df[skel_mask & m_bool], "net_ret_A", "exit_date_A", skel_mean_A, "SKEL_A")
        sk_keep_B = eval_with_prefix(df[skel_mask & m_bool], "net_ret_B", "exit_date_B", skel_mean_B, "SKEL_B")
        sk_excl_A = eval_factor_slice(df[skel_mask & (~m_bool)], "net_ret_A", "exit_date_A", "open_pct", skel_mean_A)
        sk_excl_B = eval_factor_slice(df[skel_mask & (~m_bool)], "net_ret_B", "exit_date_B", "open_pct", skel_mean_B)

        row.update(sk_keep_A)
        row.update(sk_keep_B)
        row["SKEL_A_keep_d_avg"] = round(sk_keep_A["SKEL_A_avg_ret"] - skel_eval_A["avg_ret"], 2) if sk_keep_A["SKEL_A_n_raw"] > 0 else np.nan
        row["SKEL_A_keep_d_nav"] = round(sk_keep_A["SKEL_A_ss_nav"] - skel_eval_A["ss_nav"], 3) if sk_keep_A["SKEL_A_n_raw"] > 0 else np.nan
        row["SKEL_A_excl_d_avg"] = round(sk_excl_A["avg_ret"] - skel_eval_A["avg_ret"], 2) if sk_excl_A["n_raw"] > 0 else np.nan
        row["SKEL_A_excl_d_nav"] = round(sk_excl_A["ss_nav"] - skel_eval_A["ss_nav"], 3) if sk_excl_A["n_raw"] > 0 else np.nan
        row["SKEL_A_excl_n"] = sk_excl_A["n_raw"]
        row["SKEL_A_excl_wr"] = sk_excl_A["wr_raw"]
        row["SKEL_A_excl_ss_nav"] = sk_excl_A["ss_nav"]
        row["SKEL_A_excl_ss_mdd"] = sk_excl_A["ss_mdd"]

        row["SKEL_B_keep_d_avg"] = round(sk_keep_B["SKEL_B_avg_ret"] - skel_eval_B["avg_ret"], 2) if sk_keep_B["SKEL_B_n_raw"] > 0 else np.nan
        row["SKEL_B_keep_d_nav"] = round(sk_keep_B["SKEL_B_ss_nav"] - skel_eval_B["ss_nav"], 3) if sk_keep_B["SKEL_B_n_raw"] > 0 else np.nan
        row["SKEL_B_excl_d_avg"] = round(sk_excl_B["avg_ret"] - skel_eval_B["avg_ret"], 2) if sk_excl_B["n_raw"] > 0 else np.nan
        row["SKEL_B_excl_d_nav"] = round(sk_excl_B["ss_nav"] - skel_eval_B["ss_nav"], 3) if sk_excl_B["n_raw"] > 0 else np.nan
        row["SKEL_B_excl_n"] = sk_excl_B["n_raw"]
        row["SKEL_B_excl_wr"] = sk_excl_B["wr_raw"]
        row["SKEL_B_excl_ss_nav"] = sk_excl_B["ss_nav"]
        row["SKEL_B_excl_ss_mdd"] = sk_excl_B["ss_mdd"]
        rows.append(row)

    out_df = pd.DataFrame(rows)
    out_df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # 筛选双期同向最强正因子与最强排雷负因子 Top 15 (按模式B全样与模式A综合排序)
    fac_df = out_df[out_df["group"] != "00_BASE"].copy()
    pos_B = fac_df[fac_df["B_dual_same_sign"] & (fac_df["B_delta_vs_base"] > 0) & (fac_df["B_n_raw"] >= 15)].sort_values(
        ["B_delta_vs_base", "B_ss_nav"], ascending=[False, False]
    )
    neg_B = fac_df[fac_df["B_dual_same_sign"] & (fac_df["B_delta_vs_base"] < 0) & (fac_df["B_n_raw"] >= 15)].sort_values(
        ["B_delta_vs_base", "B_wr_raw"], ascending=[True, True]
    )
    pos_A = fac_df[fac_df["A_dual_same_sign"] & (fac_df["A_delta_vs_base"] > 0) & (fac_df["A_n_raw"] >= 10)].sort_values(
        ["A_delta_vs_base", "A_ss_nav"], ascending=[False, False]
    )
    neg_A = fac_df[fac_df["A_dual_same_sign"] & (fac_df["A_delta_vs_base"] < 0) & (fac_df["A_n_raw"] >= 10)].sort_values(
        ["A_delta_vs_base", "A_wr_raw"], ascending=[True, True]
    )

    cols_brief = [
        "factor_name", "A_n_raw", "A_wr_raw", "A_avg_ret", "A_delta_vs_base", "A_early_22_23_avg", "A_recent_24_26_avg", "A_dual_same_sign", "A_ss_nav", "A_ss_mdd",
        "B_n_raw", "B_wr_raw", "B_avg_ret", "B_delta_vs_base", "B_early_22_23_avg", "B_recent_24_26_avg", "B_dual_same_sign", "B_ss_nav", "B_ss_mdd",
        "SKEL_B_keep_d_avg", "SKEL_B_excl_d_avg", "SKEL_B_excl_ss_nav",
    ]
    summary = {
        "coverage": cov_stats,
        "base_modeA": base_eval_A,
        "base_modeB": base_eval_B,
        "skel_le5_modeA": skel_eval_A,
        "skel_le5_modeB": skel_eval_B,
        "top15_pos_dual_modeB": pos_B.head(15)[cols_brief].to_dict(orient="records"),
        "top15_neg_dual_modeB": neg_B.head(15)[cols_brief].to_dict(orient="records"),
        "top15_pos_dual_modeA": pos_A.head(15)[cols_brief].to_dict(orient="records"),
        "top15_neg_dual_modeA": neg_A.head(15)[cols_brief].to_dict(orient="records"),
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("=== 5m K线覆盖与基准统计 ===")
    print(json.dumps(cov_stats, ensure_ascii=False))
    print(f"Base Mode A (右侧突破): n={base_eval_A['n_raw']}, WR={base_eval_A['wr_raw']}%, Avg={base_eval_A['avg_ret']}%, SS_NAV={base_eval_A['ss_nav']}x, MDD={base_eval_A['ss_mdd']}%")
    print(f"Base Mode B (竞价开盘): n={base_eval_B['n_raw']}, WR={base_eval_B['wr_raw']}%, Avg={base_eval_B['avg_ret']}%, SS_NAV={base_eval_B['ss_nav']}x, MDD={base_eval_B['ss_mdd']}%")
    print(f"Skel<=5 Mode A: n={skel_eval_A['n_raw']}, WR={skel_eval_A['wr_raw']}%, Avg={skel_eval_A['avg_ret']}%, SS_NAV={skel_eval_A['ss_nav']}x, MDD={skel_eval_A['ss_mdd']}%")
    print(f"Skel<=5 Mode B: n={skel_eval_B['n_raw']}, WR={skel_eval_B['wr_raw']}%, Avg={skel_eval_B['avg_ret']}%, SS_NAV={skel_eval_B['ss_nav']}x, MDD={skel_eval_B['ss_mdd']}%")

    print("\n=== Top 15 双期同向最强正因子 (模式B 竞价全池, n>=15) ===")
    for i, r in enumerate(pos_B.head(15).itertuples(index=False), 1):
        print(f"{i:2d}. {r.factor_name} | B:n={r.B_n_raw} WR={r.B_wr_raw}% Δ={r.B_delta_vs_base:+.2f}% (22-23:{r.B_early_22_23_avg:+.2f}%/24-26:{r.B_recent_24_26_avg:+.2f}%) SS={r.B_ss_nav}x | A:n={r.A_n_raw} WR={r.A_wr_raw}% Δ={r.A_delta_vs_base:+.2f}% DualA={r.A_dual_same_sign}")

    print("\n=== Top 15 双期同向最强排雷负因子 (模式B 竞价全池, n>=15) ===")
    for i, r in enumerate(neg_B.head(15).itertuples(index=False), 1):
        print(f"{i:2d}. {r.factor_name} | B:n={r.B_n_raw} WR={r.B_wr_raw}% Δ={r.B_delta_vs_base:+.2f}% (22-23:{r.B_early_22_23_avg:+.2f}%/24-26:{r.B_recent_24_26_avg:+.2f}%) | SkelB剔除Δ={r.SKEL_B_excl_d_avg:+.2f}% NAV={r.SKEL_B_excl_ss_nav}x | A:n={r.A_n_raw} Δ={r.A_delta_vs_base:+.2f}% DualA={r.A_dual_same_sign}")

    print("\n=== Top 15 双期同向最强正因子 (模式A 右侧突破, n>=10) ===")
    for i, r in enumerate(pos_A.head(15).itertuples(index=False), 1):
        print(f"{i:2d}. {r.factor_name} | A:n={r.A_n_raw} WR={r.A_wr_raw}% Δ={r.A_delta_vs_base:+.2f}% (22-23:{r.A_early_22_23_avg:+.2f}%/24-26:{r.A_recent_24_26_avg:+.2f}%) SS={r.A_ss_nav}x | SkelA保留Δ={r.SKEL_A_keep_d_avg:+.2f}%")

    print("\n=== Top 15 双期同向最强排雷负因子 (模式A 右侧突破, n>=10) ===")
    for i, r in enumerate(neg_A.head(15).itertuples(index=False), 1):
        print(f"{i:2d}. {r.factor_name} | A:n={r.A_n_raw} WR={r.A_wr_raw}% Δ={r.A_delta_vs_base:+.2f}% (22-23:{r.A_early_22_23_avg:+.2f}%/24-26:{r.A_recent_24_26_avg:+.2f}%) | SkelA剔除Δ={r.SKEL_A_excl_d_avg:+.2f}% NAV={r.SKEL_A_excl_ss_nav}x")


if __name__ == "__main__":
    main()

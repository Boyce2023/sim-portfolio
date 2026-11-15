#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_a3_4to5_highfactors.py — 四进五专项因子回测工程师 A3
把《高标首阴 V5.1》32个游资席位、老妖股性记忆、情绪反包温度计与微盘择时因子 F45-F56
严格 09:25 PIT 构造并在【右侧突破】与【09:25 open】+【mkt_max_board_prev<=5】上逐一评测。
"""
import os
import sys
import json
import pickle
import re
import sqlite3
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
AST2_DIR = f"{SIM_DIR}/backtests_astock2"
P3_DIR = f"{AST2_DIR}/p3_deep_100"
MAT_DIR = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
HD_DIR = f"{SIM_DIR}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"

if AST2_DIR not in sys.path:
    sys.path.insert(0, AST2_DIR)
if P3_DIR not in sys.path:
    sys.path.insert(0, P3_DIR)

from core_3to4_5m_engine import sim_buy_5m, sim_exit_5m
from common_eval_harness import eval_factor_slice, FEE

OUT_CSV = f"{P3_DIR}/a3_4to5_all_highdragon_factors.csv"
OUT_JSON = f"{P3_DIR}/a3_summary.json"

# 严格对齐 fast_high_dragon_today.py 第88-100行正则
Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
RE_TOP_YOUZI = re.compile(
    r"(?:大连金马路|大连黄河路|六一中路|天津东丽开发区二纬路|北京东直门南大街|北京广渠门内大街|"
    r"上海江苏路|上海建国西路|杭州延安路|兴业证券.*陕西分公司|西安朱雀大街|"
    r"南京太平南路|宁波桑田路|上海宛平南路|上海红宝石路|上海茅台路|宁波和源路|北京长椿街)"
)
RE_DAY_SURF = re.compile(
    r"(?:杭州上塘路|宜昌沿江大道|宜昌珍珠路|佛山绿景路|佛山季华六路|佛山季华五路|江阴.*营业部|苏州.*营业部)"
)
RE_LHASA = re.compile(r"(?:拉萨|东方财富证券.*拉萨)")
RE_INST = re.compile(r"机构专用")
TECH_RE = re.compile(r"(?:算力|芯片|半导体|机器人|人工智能|AI|华为|低空|固态电池)")


def load_5m_bars_map():
    """加载并合并三份现成 5 分钟 K 线数据。"""
    cols = ["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"]
    b1 = pd.read_parquet(f"{AST2_DIR}/p2_4to5/cand_4to5_5m_bars.parquet", columns=cols)
    b2 = pd.read_parquet(f"{AST2_DIR}/data_5y/cand_3to4_5m_bars.parquet", columns=cols)
    b3 = pd.read_parquet(f"{SIM_DIR}/data/cand_5m_bars_v15_complete.parquet", columns=cols)
    d5 = pd.concat([b1, b2, b3], ignore_index=True)
    d5["c6"] = d5["c6"].astype(str).str.zfill(6)
    d5["date"] = d5["date"].astype(str).str[:10]
    d5 = d5.drop_duplicates(["c6", "date", "hhmm_int"]).sort_values(["c6", "date", "hhmm_int"])
    return {
        (c6, dt): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, dt), grp in d5.groupby(["c6", "date"], sort=False)
    }


def load_kpl_memory():
    """加载开盘啦 2018-2026 历史涨停与题材库。"""
    kpl_stock_zt_days = defaultdict(list)
    kpl_day_plate = {}
    kpl_day_reason = {}
    jl_path = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
    with open(jl_path, "r", encoding="utf-8") as f:
        for line in f:
            item = json.loads(line)
            d = item["date"]
            for pl in item.get("plates", []):
                pname = pl["plate"]
                for st in pl.get("stocks", []):
                    c6 = str(st[0]).zfill(6)
                    r1 = st[2] if len(st) > 2 else ""
                    r2 = st[3] if len(st) > 3 else ""
                    reason = f"{r1} {r2}".strip()
                    kpl_stock_zt_days[c6].append((d, pname))
                    kpl_day_plate[(d, c6)] = pname
                    if reason and reason != "无 无":
                        kpl_day_reason[(d, c6)] = reason
    for c6 in kpl_stock_zt_days:
        kpl_stock_zt_days[c6].sort(key=lambda x: x[0])
    return kpl_stock_zt_days, kpl_day_plate, kpl_day_reason


def load_lhb_maps():
    """加载龙虎榜买卖并按单日取 min 去重（防1日榜与3日榜双计）。"""
    lb = pd.read_parquet(
        f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_buy.parquet",
        columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"],
    )
    ls = pd.read_parquet(
        f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_sell.parquet",
        columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "SELL"],
    )
    lb["dt"] = lb["TRADE_DATE"].astype(str).str[:10]
    lb["c6"] = lb["SECURITY_CODE"].astype(str).str.zfill(6)
    ls["dt"] = ls["TRADE_DATE"].astype(str).str[:10]
    ls["c6"] = ls["SECURITY_CODE"].astype(str).str.zfill(6)

    gb = lb[lb["dt"] >= "2021-10-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
    gs = ls[ls["dt"] >= "2021-10-01"].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["SELL"].min()

    buy_map = defaultdict(list)
    for r in gb.itertuples(index=False):
        buy_map[(r.dt, r.c6)].append((str(r.OPERATEDEPT_NAME), float(r.BUY)))
    sell_map = defaultdict(list)
    for r in gs.itertuples(index=False):
        sell_map[(r.dt, r.c6)].append((str(r.OPERATEDEPT_NAME), float(r.SELL)))
    return buy_map, sell_map


def load_zt_micro_tape():
    """只读方式加载 zt_micro_tape_5y_pit.db 的原因与微观字段。"""
    db_path = f"{SIM_DIR}/data/zt_micro_tape_5y_pit.db"
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT trade_date, sec_code, plate_name, reason_desc, first_seal_time, open_board_count FROM zt_micro_tape"
    ).fetchall()
    con.close()
    return {
        (str(td)[:10], str(sc).zfill(6)): {
            "plate_name": str(pn or ""),
            "reason_desc": str(rd or ""),
            "first_seal_time": str(fst or "99:99:99"),
            "open_board_count": int(obc or 0),
        }
        for td, sc, pn, rd, fst, obc in rows
    }


def build_micro_and_reb_maps(all_dts, by_dt):
    """按 verify_timing_regime_and_94factors.py 构造微盘股400只等权指数 + 近10日>=4板断板次日反包率。"""
    micro_lvl = 1.0
    micro_hist = []
    micro_map = {}
    reb_hist = []
    reb_map = {}

    for i, d in enumerate(all_dts):
        grp = by_dt[d]
        sml = grp[grp["mcap"].notna() & grp["pct"].notna()].nsmallest(400, "mcap")
        mr = float(sml["pct"].mean()) if len(sml) else 0.0
        micro_lvl *= (1.0 + mr)
        micro_hist.append(micro_lvl)
        ma20 = float(np.mean(micro_hist[max(0, i - 19):i + 1]))
        micro_map[d] = {
            "mc_r10": micro_lvl / micro_hist[max(0, i - 10)] - 1.0,
            "mc_gt_ma20": micro_lvl >= ma20,
        }

        if i == 0:
            reb_map[d] = 0.0
            continue
        prev_grp = by_dt[all_dts[i - 1]]
        broken_prev = set(prev_grp[(prev_grp["prev_streak"] >= 4) & (~prev_grp["is_zt"])]["c6"])
        if broken_prev:
            sub_cur = grp[grp["c6"].isin(broken_prev)]
            zt_reb = int(sub_cur["is_zt"].sum())
            reb_hist.append((zt_reb, len(broken_prev)))
        else:
            reb_hist.append((0, 0))
        w10 = reb_hist[-10:]
        tot_b = sum(x[1] for x in w10)
        reb_map[d] = (sum(x[0] for x in w10) / tot_b) if tot_b > 0 else 0.0

    return micro_map, reb_map


def build_all_features(df, cb_map, part1, kpl_data, lhb_maps, tape_map):
    """为 cand_4to5_enriched 构造全部 32+ 《高标 V5.1》严格 09:25 PIT 因子。"""
    (
        all_dts, dt_to_idx, by_dt, _, env_stats, _, _, _, _, _,
        stock_reg, ex_reg, tox_dates, _, _, _
    ) = part1
    kpl_stock_zt_days, kpl_day_plate, kpl_day_reason = kpl_data
    buy_map, sell_map = lhb_maps
    micro_map, reb_map = build_micro_and_reb_maps(all_dts, by_dt)

    feats = defaultdict(list)
    for r in df.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)[:10]
        sd = str(r.sig_date)[:10]
        cb = cb_map[c6]
        pos = cb["date_to_pos"][bd]

        # 确定本轮连板起点（严格剔除本轮连板）
        sp = pos - 1
        while sp > 0 and bool(cb["is_zt"][sp - 1]):
            sp -= 1
        streak_start_dt = str(cb["dts"][sp])

        def max_streak_win(win_len):
            st = max(0, sp - win_len)
            ms, cs = 0, 0
            for p in range(st, sp):
                if bool(cb["is_zt"][p]):
                    cs += 1
                    if cs > ms:
                        ms = cs
                else:
                    cs = 0
            return ms

        # F45 历史妖股记忆
        s1y = max_streak_win(250)
        s3y = max_streak_win(750)
        feats["f45_max_s_1y"].append(s1y)
        feats["f45_max_s_3y"].append(s3y)

        # F46 老票原主线二波 vs 老票硬蹭陌生新概念（对齐 fast_high_dragon_today.py 第765-778行）
        sd_ts = pd.Timestamp(sd)
        past_zts = [x for x in kpl_stock_zt_days.get(c6, []) if x[0] < streak_start_dt]
        zt_1y = [x for x in past_zts if (sd_ts - pd.Timestamp(x[0])).days <= 365]
        is_new_face = (len(zt_1y) == 0)
        hist_45_500 = set(x[1] for x in past_zts if 45 <= (sd_ts - pd.Timestamp(x[0])).days <= 500)
        curr_th = kpl_day_plate.get((sd, c6), str(r.plate) if pd.notna(r.plate) else "")
        feats["f46_is_new_face"].append(is_new_face)
        feats["f46_old_native_theme"].append((not is_new_face) and bool(curr_th) and (curr_th in hist_45_500))
        feats["f46_old_fake_new_concept"].append((not is_new_face) and bool(curr_th) and (curr_th not in hist_45_500))

        # F47 近10日高标（>=4板）断板反包率 & 断板跌停率温度计
        feats["f47_reb_zt_r10"].append(float(reb_map.get(sd, 0.0)))
        feats["f47_env_brk_dt_r10"].append(float(env_stats.get(sd, {}).get("brk_r10", 0.0)))

        # F50/F51/F52/量化/净买/一日游（二板 pos-3, 三板 pos-2, 四板 pos-1=sd）
        d2 = str(cb["dts"][pos - 3]) if pos >= 3 else ""
        d3 = str(cb["dts"][pos - 2]) if pos >= 2 else ""
        b23 = buy_map.get((d2, c6), []) + buy_map.get((d3, c6), [])
        b4 = buy_map.get((sd, c6), [])
        s4 = sell_map.get((sd, c6), [])

        top23_names = [dept for dept, _ in b23 if RE_TOP_YOUZI.search(dept)]
        s4_names = [dept for dept, _ in s4]
        d23_locked = bool(top23_names) and (not any(any(tn in sn for tn in top23_names) for sn in s4_names))
        feats["f50_d2d3_top_yz_locked_d4"].append(d23_locked)
        feats["f50_d4_top_yz_new_buy"].append(any(RE_TOP_YOUZI.search(dept) for dept, _ in b4))
        feats["f50_top_yz_dump_d4"].append(any(RE_TOP_YOUZI.search(dept) for dept, _ in s4))

        tot_b = sum(amt for _, amt in b4)
        tot_s = sum(amt for _, amt in s4)
        lh_cnt = sum(1 for dept, _ in b4 if RE_LHASA.search(dept))
        lh_amt = sum(amt for dept, amt in b4 if RE_LHASA.search(dept))
        lh_share = (lh_amt / tot_b) if tot_b > 0 else 0.0
        feats["f51_d4_lh_cnt"].append(lh_cnt)
        feats["f51_d4_lh_share"].append(lh_share)

        inst_b = sum(1 for dept, _ in b4 if RE_INST.search(dept))
        inst_s = sum(1 for dept, _ in s4 if RE_INST.search(dept))
        feats["f52_d4_inst_buy"].append(inst_b)
        feats["f52_d4_inst_sell"].append(inst_s)

        q_b = sum(1 for dept, _ in b4 if Q_RE.search(dept))
        q_s = sum(1 for dept, _ in s4 if Q_RE.search(dept))
        feats["f_d4_quant_buy"].append(q_b)
        feats["f_d4_quant_sell"].append(q_s)

        feats["f_d4_has_lhb"].append((len(b4) > 0) or (len(s4) > 0))
        feats["f_d4_lhb_net_buy"].append(tot_b - tot_s)
        feats["f_d4_day_surf_buy"].append(any(RE_DAY_SURF.search(dept) for dept, _ in b4))

        # F53 硬科技热词高位抛压
        t_rec = tape_map.get((sd, c6), {})
        txt = f"{r.plate or ''} {t_rec.get('plate_name', '')} {t_rec.get('reason_desc', '')} {kpl_day_reason.get((sd, c6), '')}"
        feats["f53_tech_hotword"].append(bool(TECH_RE.search(txt)))

        # F54 交易所近5日监管函密集度 & 个股10日监管函 & 90日毒丸
        i1 = dt_to_idx.get(sd, -1)
        w5 = all_dts[max(0, i1 - 5)] if i1 >= 0 else sd
        ex = "SH" if c6.startswith("60") else "SZ"
        ex_cnt = sum(1 for x in ex_reg.get(ex, []) if w5 <= x <= sd)
        feats["f54_ex_reg5"].append(ex_cnt)
        feats["f_s_reg_10d"].append(any(0 <= (sd_ts - pd.Timestamp(x)).days <= 10 for x in stock_reg.get(c6, [])))
        feats["f_tox_90d"].append(any(0 <= (sd_ts - pd.Timestamp(x)).days <= 90 for x in tox_dates.get(c6, [])))

        # 微盘股择时（sig_date 收盘已知）
        mc_info = micro_map.get(sd, {"mc_r10": 0.0, "mc_gt_ma20": True})
        feats["f_mc_gt_ma20"].append(bool(mc_info["mc_gt_ma20"]))
        feats["f_mc_r10"].append(float(mc_info["mc_r10"]))

        # F65 前四板抗揍基因：前4板中至少1次盘中最低价绿盘 (low < pre_c)
        p_start = max(0, pos - 4)
        green_dip = any(
            float(cb["low"][p]) < float(cb["pre_c"][p]) - 1e-6
            for p in range(p_start, pos)
            if float(cb["pre_c"][p]) > 0
        )
        feats["f65_green_dip_4d"].append(green_dip)

    out = df.copy()
    for k, v in feats.items():
        out[k] = v
    return out


def simulate_regime_returns(df, cb_map, b5m, buy_mode: str):
    """使用 core_3to4_5m_engine 模拟收益（严格 zero-lookahead 5m撮合）。"""
    rets, ex_dts = [], []
    for r in df.itertuples(index=False):
        if not bool(r.buyable_open):
            rets.append(np.nan)
            ex_dts.append(None)
            continue
        if buy_mode == "touch65_1130" and float(r.open_pct) < 0.01:
            rets.append(np.nan)
            ex_dts.append(None)
            continue
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)[:10]
        cb = cb_map[c6]
        pos = cb["date_to_pos"][bd]
        bpx, _ = sim_buy_5m(c6, bd, cb, pos, b5m, buy_mode)
        if bpx is None:
            rets.append(np.nan)
            ex_dts.append(None)
            continue
        ex_dt, spx, adjs, _, _ = sim_exit_5m(
            c6, cb, pos, b5m, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True
        )
        nr = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        rets.append(float(nr))
        ex_dts.append(str(ex_dt)[:10])
    return pd.Series(rets, index=df.index), pd.Series(ex_dts, index=df.index)


def define_factor_specs(d):
    """全部 18 组 / 32+ 《高标 V5.1》因子切片定义（含对照切片）。"""
    fst = d["first_seal_time"].astype(str)
    return [
        # 1. F45 历史妖股记忆
        ("F45_历史妖股记忆", "F45_max_s_1y_ge5", "近1年最高连板>=5板", d["f45_max_s_1y"] >= 5),
        ("F45_历史妖股记忆", "F45_max_s_3y_ge5", "近3年最高连板>=5板", d["f45_max_s_3y"] >= 5),
        ("F45_历史妖股记忆", "F45_max_s_1y_ge4", "近1年最高连板>=4板", d["f45_max_s_1y"] >= 4),
        ("F45_历史妖股记忆", "F45_pure_new_face_no4b", "近3年从未4板纯生面孔", d["f45_max_s_3y"] < 4),
        # 2. F46 老票原主线二波 vs 蹭新概念
        ("F46_老票题材记忆", "F46_is_new_face", "过去1年无涨停新面孔", d["f46_is_new_face"]),
        ("F46_老票题材记忆", "F46_old_native_theme", "老熟票在45~500日原主线内", d["f46_old_native_theme"]),
        ("F46_老票题材记忆", "F46_old_fake_new_concept", "老熟票硬蹭陌生新概念", d["f46_old_fake_new_concept"]),
        # 3. F47 近10日高标断板反包/跌停温度计
        ("F47_反包温度计", "F47_reb_zt_r10_ge20", "近10日>=4板断板次日反包涨停率>=20%", d["f47_reb_zt_r10"] >= 0.20),
        ("F47_反包温度计", "F47_reb_zt_r10_ge15", "近10日>=4板断板次日反包涨停率>=15%", d["f47_reb_zt_r10"] >= 0.15),
        ("F47_反包温度计", "F47_reb_zt_r10_eq0", "近10日>=4板断板反包涨停率==0%(冰点)", d["f47_reb_zt_r10"] == 0.0),
        ("F47_反包温度计", "F47_env_brk_dt_r10_ge20", "V5.1环境brk_r10(>=4板断板跌停率)>=20%", d["f47_env_brk_dt_r10"] >= 0.20),
        ("F47_反包温度计", "F47_env_brk_dt_r10_ge15", "V5.1环境brk_r10>=15%", d["f47_env_brk_dt_r10"] >= 0.15),
        ("F47_反包温度计", "F47_env_brk_dt_r10_eq0", "V5.1环境brk_r10==0%", d["f47_env_brk_dt_r10"] == 0.0),
        # 4. F48 涨停家数抱团温区
        ("F48_涨停抱团温区", "F48_mkt_zt_lt70", "昨日涨停家数<70", d["mkt_zt_prev"] < 70),
        ("F48_涨停抱团温区", "F48_mkt_zt_30_65", "昨日涨停30~65家(缩量抱团黄金期)", d["mkt_zt_prev"].between(30, 65)),
        ("F48_涨停抱团温区", "F48_mkt_zt_ge95", "昨日涨停>=95家(普涨分流)", d["mkt_zt_prev"] >= 95),
        # 5. F49 高锁仓×轻盈真流通乘积交互
        ("F49_锁仓真流通交互", "F49_lock50_rfmcap_12_35", "lock_top10>=50 & 12<=real_free_mcap<=35", (d["lock_top10"] >= 50.0) & d["real_free_mcap"].between(12.0, 35.0)),
        ("F49_锁仓真流通交互", "F49_not_lock50_rfmcap_12_35", "非(lock>=50 & 12<=真流通<=35)", ~((d["lock_top10"] >= 50.0) & d["real_free_mcap"].between(12.0, 35.0))),
        ("F49_锁仓真流通交互", "F49_v51_lock45_or_rfmcap45", "V5.1标准: lock_top10>=45 | real_free_mcap>=45", (d["lock_top10"] >= 45.0) | (d["real_free_mcap"] >= 45.0)),
        ("F49_锁仓真流通交互", "F49_v51_fail", "不满足V5.1标准(lock<45 & 真流通<45)", ~((d["lock_top10"] >= 45.0) | (d["real_free_mcap"] >= 45.0))),
        # 6. F50 顶级格局游资锁仓 vs 四板明牌新买
        ("F50_顶级游资行为", "F50_d2d3_top_yz_locked_d4", "二/三板顶级游资买入且四板未出(锁仓)", d["f50_d2d3_top_yz_locked_d4"]),
        ("F50_顶级游资行为", "F50_d4_top_yz_new_buy", "四板当日顶级游资明牌大买上榜", d["f50_d4_top_yz_new_buy"]),
        ("F50_顶级游资行为", "F50_top_yz_dump_d4", "顶级游资在四板卖出榜出逃", d["f50_top_yz_dump_d4"]),
        # 7. F51 四板拉萨散户化见顶
        ("F51_四板拉萨散户化", "F51_lhb_lh_cnt_eq0", "四板买榜拉萨席位==0", d["f51_d4_lh_cnt"] == 0),
        ("F51_四板拉萨散户化", "F51_lhb_lh_cnt_eq2", "四板买榜拉萨席位==2", d["f51_d4_lh_cnt"] == 2),
        ("F51_四板拉萨散户化", "F51_lhb_lh_cnt_ge3", "四板买榜拉萨席位>=3", d["f51_d4_lh_cnt"] >= 3),
        ("F51_四板拉萨散户化", "F51_lhb_lh_share_ge20", "四板买榜拉萨买入占比>=20%", d["f51_d4_lh_share"] >= 0.20),
        ("F51_四板拉萨散户化", "F51_lhb_lh_cnt2_share20", "拉萨>=2家且占比>=20%", (d["f51_d4_lh_cnt"] >= 2) & (d["f51_d4_lh_share"] >= 0.20)),
        # 8. F52 四板机构席位出逃/马甲
        ("F52_四板机构席位", "F52_d4_inst_buy_ge1", "四板买榜机构席位>=1", d["f52_d4_inst_buy"] >= 1),
        ("F52_四板机构席位", "F52_d4_inst_sell_ge1", "四板卖榜机构席位>=1", d["f52_d4_inst_sell"] >= 1),
        ("F52_四板机构席位", "F52_d4_inst_any_ge1", "四板买卖榜任一含机构>=1", (d["f52_d4_inst_buy"] + d["f52_d4_inst_sell"]) >= 1),
        # 9. 量化席位做T因子
        ("F_量化席位", "F_quant_buy_low_lh", "四板量化买>=1且拉萨<=1", (d["f_d4_quant_buy"] >= 1) & (d["f51_d4_lh_cnt"] <= 1)),
        ("F_量化席位", "F_quant_sell_ge1", "四板卖榜含量化>=1", d["f_d4_quant_sell"] >= 1),
        # 10. 龙虎榜净买入方向
        ("F_龙虎榜净买", "F_d4_lhb_net_pos", "四板上榜且龙虎榜净买入>0", d["f_d4_has_lhb"] & (d["f_d4_lhb_net_buy"] > 0)),
        ("F_龙虎榜净买", "F_d4_lhb_net_le0", "四板上榜且龙虎榜净买入<=0", d["f_d4_has_lhb"] & (d["f_d4_lhb_net_buy"] <= 0)),
        # 11. 一日游砸盘席位
        ("F_一日游席位", "F_d4_day_surf_buy", "四板买榜含上塘路/佛山等一日游", d["f_d4_day_surf_buy"]),
        # 12. F53 硬科技热词高位抛压
        ("F53_科技热词", "F53_tech_hotword", "四板题材或原因命中TECH_RE", d["f53_tech_hotword"]),
        ("F53_科技热词", "F53_non_tech", "非科技传统/消费/周期题材", ~d["f53_tech_hotword"]),
        # 13. F54 交易所近5日监管函密集度
        ("F54_交易所监管密集", "F54_ex_reg5_ge2", "同交易所近5日监管函股票数>=2", d["f54_ex_reg5"] >= 2),
        ("F54_交易所监管密集", "F54_ex_reg5_ge1", "同交易所近5日监管函股票数>=1", d["f54_ex_reg5"] >= 1),
        ("F54_交易所监管密集", "F54_ex_reg5_eq0", "同交易所近5日零监管函", d["f54_ex_reg5"] == 0),
        # 14. 个股10日监管函与90日毒丸
        ("F_个股监管毒丸", "F_s_reg_10d", "个股近10日有监管函/重点监控", d["f_s_reg_10d"]),
        ("F_个股监管毒丸", "F_tox_90d", "个股近90日有减持/立案/退市毒丸", d["f_tox_90d"]),
        ("F_个股监管毒丸", "F_clean_no_reg_no_tox", "无10日监管函且无90日毒丸", (~d["f_s_reg_10d"]) & (~d["f_tox_90d"])),
        # 15. F55 四板封板时间与紧密度
        ("F55_封板时间紧密度", "F55_fst_le_0935", "四板首次封板<=09:35:00(秒封顶死)", fst <= "09:35:00"),
        ("F55_封板时间紧密度", "F55_fst_0936_1045", "四板首次封板09:36~10:45(分歧回封)", (fst >= "09:36:00") & (fst <= "10:45:00")),
        ("F55_封板时间紧密度", "F55_obc0_tight_ge35", "零开板且seal_tightness>=35", (d["open_board_count"] == 0) & (d["seal_tightness"] >= 35.0)),
        # 16. F56 沪深300横盘抱团带
        ("F56_沪深300横盘带", "F56_csi_r5_ge_m05", "csi300_ret5>=-0.5%", d["csi300_ret5"] >= -0.005),
        ("F56_沪深300横盘带", "F56_csi_r5_band", "-1.5%<=csi300_ret5<=+2.0%(窄幅震荡)", d["csi300_ret5"].between(-0.015, 0.020)),
        ("F56_沪深300横盘带", "F56_csi_r5_lt_m25", "csi300_ret5<-2.5%(大盘急跌)", d["csi300_ret5"] < -0.025),
        ("F56_沪深300横盘带", "F56_csi_r20_gt_m40", "csi300_ret20>-4%", d["csi300_ret20"] > -0.04),
        # 17. 微盘股等权指数择时
        ("F_微盘择时", "F_mc_gt_ma20", "微盘400等权站上MA20", d["f_mc_gt_ma20"]),
        ("F_微盘择时", "F_mc_r10_gt_m5", "微盘400近10日跌幅不超-5%", d["f_mc_r10"] > -0.05),
        ("F_微盘择时", "F_R6_regime", "R6抱团黄金择时(csi20>-4%&mc10>-5%&zt<80)", (d["csi300_ret20"] > -0.04) & (d["f_mc_r10"] > -0.05) & (d["mkt_zt_prev"] < 80)),
        # 18. 换手成龙连板数与抗揍基因 F65
        ("F_换手与F65抗揍", "F_turn_boards_eq4", "前4板全为非一字换手板(==4)", d["turn_boards_4d"] == 4),
        ("F_换手与F65抗揍", "F_turn_boards_ge3", "前4板非一字换手板>=3", d["turn_boards_4d"] >= 3),
        ("F_换手与F65抗揍", "F_turn_boards_le2", "前4板非一字换手板<=2(一字虚高)", d["turn_boards_4d"] <= 2),
        ("F_换手与F65抗揍", "F65_green_dip_4d", "F65前4板至少1次盘中绿盘(low<pre_c)抗揍封板", d["f65_green_dip_4d"]),
        ("F_换手与F65抗揍", "F65_greenhouse_all_red", "前4板全程水上温室四板(无绿盘)", ~d["f65_green_dip_4d"]),
    ]


def eval_regime(d_feat, regime_name: str, ret_col: str, exit_col: str, extra_mask: pd.Series):
    """在指定买法+骨架边际下，对全部因子逐个执行 eval_factor_slice。"""
    pool = d_feat[d_feat[ret_col].notna() & extra_mask].copy()
    pool["net_ret"] = pool[ret_col]
    pool["exit_date"] = pool[exit_col]
    base_mean = float(pool["net_ret"].mean())
    base_metrics = eval_factor_slice(pool, ret_col="net_ret", exit_col="exit_date", base_mean=base_mean)
    base_big_loss = float((pool["net_ret"] <= -0.08).mean() * 100)

    rows = []
    # Baseline row
    rows.append({
        "regime": regime_name,
        "factor_group": "00_BASELINE",
        "factor_name": "BASELINE",
        "factor_desc": f"{regime_name} 基准池",
        "base_n": base_metrics["n_raw"],
        "base_avg_ret": base_metrics["avg_ret"],
        "base_wr": base_metrics["wr_raw"],
        "base_payoff": base_metrics["payoff_raw"],
        "base_big_loss_pct": round(base_big_loss, 2),
        "hit_rate_pct": 100.0,
        "big_loss_pct": round(base_big_loss, 2),
        "delta_big_loss_pct": 0.0,
        **base_metrics,
    })

    for grp, fname, fdesc, mask in define_factor_specs(pool):
        sub = pool[mask]
        m = eval_factor_slice(sub, ret_col="net_ret", exit_col="exit_date", base_mean=base_mean)
        bl_pct = float((sub["net_ret"] <= -0.08).mean() * 100) if len(sub) > 0 else 0.0
        rows.append({
            "regime": regime_name,
            "factor_group": grp,
            "factor_name": fname,
            "factor_desc": fdesc,
            "base_n": base_metrics["n_raw"],
            "base_avg_ret": base_metrics["avg_ret"],
            "base_wr": base_metrics["wr_raw"],
            "base_payoff": base_metrics["payoff_raw"],
            "base_big_loss_pct": round(base_big_loss, 2),
            "hit_rate_pct": round(len(sub) / len(pool) * 100, 2) if len(pool) else 0.0,
            "big_loss_pct": round(bl_pct, 2),
            "delta_big_loss_pct": round(bl_pct - base_big_loss, 2),
            **m,
        })
    return rows


def main():
    print("[A3] Loading raw datasets (zero-yfinance, SQLite mode=ro)...")
    df = pd.read_parquet(f"{AST2_DIR}/p2_4to5/cand_4to5_enriched.parquet")
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f:
        cb_map = pickle.load(f)["code_bars"]
    with open(f"{HD_DIR}/part1_cache.pkl", "rb") as f:
        part1 = pickle.load(f)

    b5m = load_5m_bars_map()
    kpl_data = load_kpl_memory()
    lhb_maps = load_lhb_maps()
    tape_map = load_zt_micro_tape()

    print("[A3] Building all 32+ High-Dragon V5.1 PIT features...")
    d_feat = build_all_features(df, cb_map, part1, kpl_data, lhb_maps, tape_map)

    print("[A3] Simulating 09:25 open & touch65_1130 (pm1345_5m + cut_weak + yang_imm)...")
    d_feat["ret_open"], d_feat["ex_open"] = simulate_regime_returns(d_feat, cb_map, b5m, "open")
    d_feat["ret_right"], d_feat["ex_right"] = simulate_regime_returns(d_feat, cb_map, b5m, "touch65_1130")

    le5_mask = d_feat["mkt_max_board_prev"] <= 5
    all_mask = pd.Series(True, index=d_feat.index)

    regimes = [
        ("right_all", "ret_right", "ex_right", all_mask),
        ("right_le5", "ret_right", "ex_right", le5_mask),
        ("open_all", "ret_open", "ex_open", all_mask),
        ("open_le5", "ret_open", "ex_open", le5_mask),
    ]

    all_rows = []
    for rname, rcol, ecol, emask in regimes:
        all_rows.extend(eval_regime(d_feat, rname, rcol, ecol, emask))

    res_df = pd.DataFrame(all_rows)
    res_df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    # 构建结构化 JSON 摘要（含各买法双期同向真因子 & 毒丸剔除因子）
    summary = {"baselines": {}, "dual_consistent_top": {}, "regime_factor_counts": {}}
    for rname, _, _, _ in regimes:
        sub_r = res_df[res_df["regime"] == rname]
        b_row = sub_r[sub_r["factor_name"] == "BASELINE"].iloc[0].to_dict()
        summary["baselines"][rname] = b_row
        facs = sub_r[(sub_r["factor_name"] != "BASELINE") & (sub_r["n_raw"] >= 10)].copy()
        dual = facs[facs["dual_same_sign"] == True].sort_values("delta_vs_base", ascending=False)
        summary["regime_factor_counts"][rname] = {
            "total_tested": int(len(sub_r) - 1),
            "n_ge_10": int(len(facs)),
            "dual_same_sign_cnt": int(len(dual)),
        }
        summary["dual_consistent_top"][rname] = dual[[
            "factor_name", "factor_desc", "n_raw", "wr_raw", "payoff_raw",
            "avg_ret", "delta_vs_base", "early_22_23_avg", "recent_24_26_avg",
            "big_loss_pct", "delta_big_loss_pct", "ss_n", "ss_nav", "ss_mdd", "eq_nav"
        ]].to_dict("records")

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[A3] Saved CSV ({len(res_df)} rows) -> {OUT_CSV}")
    print(f"[A3] Saved JSON -> {OUT_JSON}")

    # 打印完整统计摘要
    for rname, _, _, _ in regimes:
        b = summary["baselines"][rname]
        print(f"\n=== [{rname}] Base: n={b['n_raw']} WR={b['wr_raw']}% PO={b['payoff_raw']} Avg={b['avg_ret']:+.2f}% BigLoss={b['big_loss_pct']}% SS_NAV={b['ss_nav']}x ===")
        sub_r = res_df[(res_df["regime"] == rname) & (res_df["factor_name"] != "BASELINE")]
        dual_pos = sub_r[sub_r["dual_same_sign"] & (sub_r["delta_vs_base"] > 0)].sort_values("delta_vs_base", ascending=False)
        dual_neg = sub_r[sub_r["dual_same_sign"] & (sub_r["delta_vs_base"] < 0)].sort_values("delta_vs_base", ascending=True)
        print("  [+] 双期同向正向因子:")
        for x in dual_pos.itertuples(index=False):
            print(f"      {x.factor_name:28s} | n={x.n_raw:3d} WR={x.wr_raw:5.1f}% PO={x.payoff_raw:4.2f} Avg={x.avg_ret:+6.2f}% (d={x.delta_vs_base:+6.2f}%) | 22-23={x.early_22_23_avg:+6.2f}% 24-26={x.recent_24_26_avg:+6.2f}% | 大面={x.big_loss_pct:4.1f}%({x.delta_big_loss_pct:+5.1f}%) | ss={x.ss_n:3d}/{x.ss_nav:.3f}x")
        print("  [-] 双期同向负向/避坑因子:")
        for x in dual_neg.itertuples(index=False):
            print(f"      {x.factor_name:28s} | n={x.n_raw:3d} WR={x.wr_raw:5.1f}% PO={x.payoff_raw:4.2f} Avg={x.avg_ret:+6.2f}% (d={x.delta_vs_base:+6.2f}%) | 22-23={x.early_22_23_avg:+6.2f}% 24-26={x.recent_24_26_avg:+6.2f}% | 大面={x.big_loss_pct:4.1f}%({x.delta_big_loss_pct:+5.1f}%)")


if __name__ == "__main__":
    main()

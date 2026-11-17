#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
A5 专项普查：四进五全维度无死角分箱 (125+ 特征 Q1-Q5 单调性扫描) 与 2D 物理正交交互挖掘。
严格遵守：零 yfinance、SQLite mode=ro、零未来函数 (09:25 PIT)、不改 portfolio_state.json。
"""
import os
import sys
import json
import pickle
import re
import sqlite3
import datetime
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

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

from common_eval_harness import eval_factor_slice, CSI_BENCH, CSI_MAP, ALL_CSI_DTS, FEE
from core_3to4_5m_engine import sim_buy_5m, sim_exit_5m

OUT_Q_CSV = f"{P3_DIR}/a5_4to5_all125_quantiles.csv"
OUT_I_CSV = f"{P3_DIR}/a5_4to5_2way_interactions.csv"
OUT_JSON = f"{P3_DIR}/a5_summary.json"

Q_RE = re.compile(r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|摩根大通)")
RE_TOP_YOUZI = re.compile(
    r"(?:大连金马路|大连黄河路|六一中路|天津东丽开发区二纬路|北京东直门南大街|北京广渠门内大街|"
    r"上海江苏路|上海建国西路|杭州延安路|兴业证券.*陕西分公司|西安朱雀大街|"
    r"南京太平南路|宁波桑田路|上海宛平南路|上海红宝石路|上海茅台路|宁波和源路|北京长椿街)"
)
RE_LHASA = re.compile(r"(?:拉萨|东方财富证券.*拉萨)")
NEG_NOTICE_PAT = re.compile(r"(?:减持|立案|调查|警示函|监管函|退市风险|ST|问询函|关注函|风险提示|异动|停牌核查|业绩预亏|亏损|违规|处罚|诉讼|仲裁|质押|冻结)")
GOOD_NOTICE_PAT = re.compile(r"(?:中标|签合同|战略合作|并购|重组|收购|增资|股权激励|回购|业绩预增|预盈|扭亏|获批|专利|首发)")

# 当日未来列与非特征元数据列，严禁进入因子扫描
FUTURE_COLS = {
    "h_pct", "l_pct", "pct", "is_zt_today", "touch_zt_today", "touch_dt_today",
    "csi_1d_prev",  # step2_build_features.py 使用了 bd 当日收盘，已用 csi_1d_prev_pit 替换
    "has_ex_reg",   # step2_build_features.py 因 key bug 全0，已用 has_ex_reg_pit 替换
}
META_STR_COLS = {
    "code", "name", "sig_date", "buy_date", "plate", "r_short", "csrc_ind", "first_seal_time",
}


def load_merged_5m_bars(needed_keys: set) -> dict:
    """加载三份 5m K 线源文件并合并为 (c6, date) -> ndarray。"""
    paths = [
        f"{AST2_DIR}/p2_4to5/cand_4to5_5m_bars.parquet",
        f"{AST2_DIR}/data_5y/cand_3to4_5m_bars.parquet",
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


def sim_one_trade(c6: str, bd: str, cb: dict, bars_5m_map: dict, mode: str):
    """
    mode='open': 09:25 竞价买 + pm1345_5m + cut_weak + yang_imm=True
    mode='t65':  open_pct>=0.01 & touch65_1130 + pm1345_5m + cut_weak + yang_imm=True
    """
    if cb is None:
        return None
    pos = cb["date_to_pos"].get(bd, -1)
    if pos < 0 or pos >= len(cb["dts"]) - 1:
        return None
    op, pc, zt = float(cb["open"][pos]), float(cb["pre_c"][pos]), float(cb["zt_px"][pos])
    if pc <= 0 or op >= zt - 0.005:
        return None

    used_buy_5m = False
    if mode == "t65":
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
        "buy_5m_cov": bool(used_buy_5m),
        "hold_5m_cov": bool(used_hold_5m),
    }


def fst_to_mins(s: str) -> float:
    """将 HH:MM:SS 封板时间转为开盘起算交易分钟数 (09:30=0, 11:30=120, 13:00=120, 15:00=240)。"""
    s = str(s or "").strip()
    if len(s) < 5 or s.startswith("99"):
        return np.nan
    try:
        hh, mm = int(s[:2]), int(s[3:5])
        t = hh * 60 + mm
        if t <= 9 * 60 + 30:
            return 0.0
        if t <= 11 * 60 + 30:
            return float(t - (9 * 60 + 30))
        if t <= 13 * 60:
            return 120.0
        return float(120 + min(120, t - 13 * 60))
    except Exception:
        return np.nan


def build_supplemental_pit_features(df: pd.DataFrame, cb_map: dict) -> pd.DataFrame:
    """严格 09:25 PIT 补充构造机构调研、社区帖子、公告、连板历史、龙虎榜、微盘择时与日历特征。"""
    df = df.copy()
    codes_set = set(df["code"].astype(str).str.zfill(6))
    placeholders = ",".join("?" for _ in codes_set)
    codes_list = sorted(codes_set)

    # 1. 机构调研 (cninfo_ir_qa_5y_pit.db)
    ir_map = defaultdict(list)
    ir_p = f"{AST2_DIR}/data_5y/cninfo_ir_qa_5y_pit.db"
    if os.path.exists(ir_p):
        con = sqlite3.connect(f"file:{ir_p}?mode=ro", uri=True)
        for sc, pdt in con.execute("SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst >= '2021-09-01'"):
            c6 = str(sc)[:6].zfill(6)
            if c6 in codes_set and pdt:
                ir_map[c6].append(str(pdt)[:19])
        con.close()
        for c6 in ir_map:
            ir_map[c6].sort()

    # 2. 社区帖子 (astock_community_5y_pit.db + xueqiu_guba_5y_pit.db)
    comm_map = defaultdict(list)
    cp_path = f"{SIM_DIR}/data/astock_community_5y_pit.db"
    if os.path.exists(cp_path):
        con = sqlite3.connect(f"file:{cp_path}?mode=ro", uri=True)
        for sym, pdt in con.execute("SELECT symbol, pub_datetime_cst FROM community_posts WHERE pub_datetime_cst >= '2021-12-01'"):
            c6 = str(sym)[-6:].zfill(6)
            if c6 in codes_set and pdt:
                comm_map[c6].append(str(pdt)[:19])
        con.close()
        for c6 in comm_map:
            comm_map[c6].sort()

    guba_map = defaultdict(list)
    xq_map = defaultdict(list)
    xg_path = f"{SIM_DIR}/data/xueqiu_guba_5y_pit.db"
    if os.path.exists(xg_path):
        con = sqlite3.connect(f"file:{xg_path}?mode=ro", uri=True)
        q_guba = f"SELECT sec_code, pub_time, read_cnt, comment_cnt FROM guba_posts WHERE sec_code IN ({placeholders}) AND pub_time >= '2021-12-01'"
        for sc, pt, rc, cc in con.execute(q_guba, codes_list):
            if pt:
                guba_map[str(sc).zfill(6)].append((str(pt)[:19], int(rc or 0), int(cc or 0)))
        for sym, cts in con.execute("SELECT symbol, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2021-12-01'"):
            c6 = str(sym)[-6:].zfill(6)
            if c6 in codes_set and cts:
                xq_map[c6].append(str(cts)[:19])
        con.close()
        for c6 in guba_map:
            guba_map[c6].sort(key=lambda x: x[0])
        for c6 in xq_map:
            xq_map[c6].sort()

    # 3. 公告 (cninfo_notices_5y_pit.db)
    not_map = defaultdict(list)
    not_p = f"{SIM_DIR}/data/cninfo_notices_5y_pit.db"
    if os.path.exists(not_p):
        con = sqlite3.connect(f"file:{not_p}?mode=ro", uri=True)
        for sc, pdt, title in con.execute("SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= '2021-11-01'"):
            c6 = str(sc)[:6].zfill(6)
            if c6 in codes_set and pdt:
                ts = str(title or "")
                is_bad = int(bool(NEG_NOTICE_PAT.search(ts)))
                is_good = int((not is_bad) and bool(GOOD_NOTICE_PAT.search(ts)))
                not_map[c6].append((str(pdt)[:19], is_bad, is_good))
        con.close()
        for c6 in not_map:
            not_map[c6].sort(key=lambda x: x[0])

    # 4. 开盘啦历史涨停记忆 (kpl_plates_2018_2026_merged.jsonl)
    kpl_zt_days = defaultdict(list)
    kpl_day_plate = {}
    jl_path = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"
    if os.path.exists(jl_path):
        with open(jl_path, "r", encoding="utf-8") as f:
            for line in f:
                item = json.loads(line)
                d = item["date"]
                for pl in item.get("plates", []):
                    pname = pl["plate"]
                    for st in pl.get("stocks", []):
                        c6 = str(st[0]).zfill(6)
                        if c6 in codes_set:
                            kpl_zt_days[c6].append((d, pname))
                            kpl_day_plate[(d, c6)] = pname
        for c6 in kpl_zt_days:
            kpl_zt_days[c6].sort(key=lambda x: x[0])

    # 5. part1_cache.pkl: 监管函/恶毒公告/微盘择时/大盘反包温度计
    with open(f"{HD_DIR}/part1_cache.pkl", "rb") as f:
        part1 = pickle.load(f)
    all_dts, _, by_dt, _, env_stats, _, _, _, _, _, stock_reg, ex_reg, tox_dates, _, _, _ = part1

    micro_lvl = 1.0
    micro_hist, reb_hist = [], []
    micro_map, reb_map = {}, {}
    for i, d in enumerate(all_dts):
        grp = by_dt[d]
        sml = grp[grp["mcap"].notna() & grp["pct"].notna()].nsmallest(400, "mcap")
        mr = float(sml["pct"].mean()) if len(sml) else 0.0
        micro_lvl *= (1.0 + mr)
        micro_hist.append(micro_lvl)
        ma20 = float(np.mean(micro_hist[max(0, i - 19):i + 1]))
        micro_map[d] = (micro_lvl / micro_hist[max(0, i - 10)] - 1.0, micro_lvl >= ma20)
        if i == 0:
            reb_map[d] = 0.0
        else:
            prev_grp = by_dt[all_dts[i - 1]]
            broken_prev = set(prev_grp[(prev_grp["prev_streak"] >= 4) & (~prev_grp["is_zt"])]["c6"])
            if broken_prev:
                zt_reb = int(grp[grp["c6"].isin(broken_prev)]["is_zt"].sum())
                reb_hist.append((zt_reb, len(broken_prev)))
            else:
                reb_hist.append((0, 0))
            w10 = reb_hist[-10:]
            tot_b = sum(x[1] for x in w10)
            reb_map[d] = (sum(x[0] for x in w10) / tot_b) if tot_b > 0 else 0.0

    # 6. 龙虎榜买卖净额/游资/拉萨卖出
    lb = pd.read_parquet(f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
    ls = pd.read_parquet(f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_sell.parquet", columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "SELL"])
    lb["dt"] = lb["TRADE_DATE"].astype(str).str[:10]
    lb["c6"] = lb["SECURITY_CODE"].astype(str).str.zfill(6)
    ls["dt"] = ls["TRADE_DATE"].astype(str).str[:10]
    ls["c6"] = ls["SECURITY_CODE"].astype(str).str.zfill(6)
    gb = lb[(lb["dt"] >= "2021-10-01") & (lb["c6"].isin(codes_set))].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["BUY"].min()
    gs = ls[(ls["dt"] >= "2021-10-01") & (ls["c6"].isin(codes_set))].groupby(["dt", "c6", "OPERATEDEPT_NAME"], as_index=False)["SELL"].min()
    buy_map, sell_map = defaultdict(list), defaultdict(list)
    for r in gb.itertuples(index=False):
        buy_map[(r.dt, r.c6)].append((str(r.OPERATEDEPT_NAME), float(r.BUY)))
    for r in gs.itertuples(index=False):
        sell_map[(r.dt, r.c6)].append((str(r.OPERATEDEPT_NAME), float(r.SELL)))

    # 7. 同题材 Day4 首板 09:25 高开数 & 昨日>=4板跌停数 & 昨日5板09:25最小开盘
    df_1b = pd.read_parquet(f"{MAT_DIR}/cand_0to1_firstboard.parquet", columns=["code", "buy_date", "plate", "is_zt_today"])
    df_1b_zt = df_1b[df_1b["is_zt_today"] == True].copy()
    d5_ops = []
    for r1 in df_1b_zt.itertuples(index=False):
        cb1 = cb_map.get(str(r1.code).zfill(6))
        p1 = cb1["date_to_pos"].get(str(r1.buy_date), -1) if cb1 else -1
        if cb1 and 0 <= p1 < len(cb1["dts"]) - 1 and cb1["pre_c"][p1 + 1] > 0:
            d5_ops.append(float(cb1["open"][p1 + 1] / cb1["pre_c"][p1 + 1] - 1.0))
        else:
            d5_ops.append(0.0)
    df_1b_zt["d5_op"] = d5_ops
    fb_ho_map = {}
    for (sd_k, pl), grp in df_1b_zt[df_1b_zt["plate"].notna() & (df_1b_zt["plate"] != "")].groupby(["buy_date", "plate"], sort=False):
        fb_ho_map[(str(sd_k), str(pl))] = int((grp["d5_op"].to_numpy() >= 0.03).sum())

    dt_b4_dt = defaultdict(int)
    for cb in cb_map.values():
        cur_stk = 0
        for i in range(len(cb["dts"])):
            if cur_stk >= 4 and bool(cb["is_dt"][i]):
                dt_b4_dt[str(cb["dts"][i])] += 1
            cur_stk = (cur_stk + 1) if bool(cb["is_zt"][i]) else 0

    hd = pd.read_parquet(f"{MAT_DIR}/cand_high_dragon.parquet", columns=["buy_date", "prev_streak", "open_pct"])
    b5_min_open = hd[hd["prev_streak"] == 5].groupby("buy_date")["open_pct"].min().to_dict()

    csi_pos = {d: i for i, d in enumerate(ALL_CSI_DTS)}
    import bisect

    feats = defaultdict(list)
    for r in df.itertuples(index=False):
        c6, sd, bd = str(r.code).zfill(6), str(r.sig_date)[:10], str(r.buy_date)[:10]
        pl = str(r.plate) if pd.notna(r.plate) else ""
        cb = cb_map[c6]
        pos = cb["date_to_pos"][bd]
        end_cut = f"{bd} 09:25:00"
        bd_d = datetime.date.fromisoformat(bd)
        sd_d = datetime.date.fromisoformat(sd)
        c7 = f"{(bd_d - datetime.timedelta(days=7)).isoformat()} 09:25:00"
        c30 = f"{(bd_d - datetime.timedelta(days=30)).isoformat()} 09:25:00"
        c90 = f"{(bd_d - datetime.timedelta(days=90)).isoformat()} 09:25:00"
        c24 = f"{sd} 09:25:00"

        # IR
        irl = ir_map.get(c6, [])
        i_hi = bisect.bisect_left(irl, end_cut)
        i_30 = bisect.bisect_left(irl, c30)
        i_90 = bisect.bisect_left(irl, c90)
        ir30, ir90 = max(0, i_hi - i_30), max(0, i_hi - i_90)
        feats["ir_cnt_30d"].append(ir30)
        feats["ir_cnt_90d"].append(ir90)
        feats["has_ir_30d"].append(ir30 >= 1)
        feats["has_ir_90d"].append(ir90 >= 1)

        # Community + Guba + Xueqiu
        cml = comm_map.get(c6, [])
        c_hi = bisect.bisect_left(cml, end_cut)
        c_7 = bisect.bisect_left(cml, c7)
        cp7 = max(0, c_hi - c_7)
        feats["comm_posts_7d"].append(cp7)
        feats["comm_posts_accel"].append(float(r.comm_posts_24h) / max(1.0, cp7 / 7.0))

        gbl = guba_map.get(c6, [])
        g_ts = [x[0] for x in gbl]
        g_hi = bisect.bisect_left(g_ts, end_cut)
        g_24 = bisect.bisect_left(g_ts, c24)
        g_7 = bisect.bisect_left(g_ts, c7)
        feats["guba_posts_24h"].append(max(0, g_hi - g_24))
        feats["guba_posts_7d"].append(max(0, g_hi - g_7))
        feats["guba_reads_24h"].append(sum(x[1] for x in gbl[g_24:g_hi]))
        feats["guba_comments_24h"].append(sum(x[2] for x in gbl[g_24:g_hi]))

        xql = xq_map.get(c6, [])
        x_hi = bisect.bisect_left(xql, end_cut)
        x_7 = bisect.bisect_left(xql, c7)
        feats["xq_posts_7d"].append(max(0, x_hi - x_7))

        # Notices
        ntl = not_map.get(c6, [])
        n_ts = [x[0] for x in ntl]
        n_hi = bisect.bisect_left(n_ts, end_cut)
        n_30 = bisect.bisect_left(n_ts, c30)
        feats["notice_cnt_30d"].append(max(0, n_hi - n_30))
        feats["notice_bad_30d"].append(sum(x[1] for x in ntl[n_30:n_hi]))
        feats["notice_good_30d"].append(sum(x[2] for x in ntl[n_30:n_hi]))

        # Strict PIT Reg & Tox
        ci = csi_pos.get(sd, -1)
        d_m10 = ALL_CSI_DTS[max(0, ci - 10)] if ci >= 0 else "1990-01-01"
        d_m5 = ALL_CSI_DTS[max(0, ci - 5)] if ci >= 0 else "1990-01-01"
        ex_k = "SH" if c6.startswith("60") else "SZ"
        feats["has_stock_reg_pit"].append(any(d_m10 <= x <= sd for x in stock_reg.get(c6, ())))
        feats["has_ex_reg_pit"].append(any(d_m5 <= x <= sd for x in ex_reg.get(ex_k, ())))
        feats["has_tox_notice_pit"].append(any(d_m10 <= x <= sd for x in tox_dates.get(c6, ())))

        # Streak history & technicals before buy_date
        sp = pos - 1
        while sp > 0 and bool(cb["is_zt"][sp - 1]):
            sp -= 1
        streak_start_dt = str(cb["dts"][sp])

        def max_stk(wlen):
            st = max(0, sp - wlen)
            ms = cs = 0
            for p in range(st, sp):
                if bool(cb["is_zt"][p]):
                    cs += 1
                    ms = max(ms, cs)
                else:
                    cs = 0
            return ms

        feats["max_streak_1y"].append(max_stk(250))
        feats["max_streak_3y"].append(max_stk(750))
        feats["zt_cnt_60d"].append(int(np.sum(cb["is_zt"][max(0, pos - 60):pos])))
        feats["zt_cnt_250d"].append(int(np.sum(cb["is_zt"][max(0, pos - 250):pos])))

        prev_zt_gap = 999
        for p in range(sp - 1, max(-1, sp - 251), -1):
            if bool(cb["is_zt"][p]):
                prev_zt_gap = sp - p
                break
        feats["days_since_prev_zt_wave"].append(prev_zt_gap)

        past_kpl = [x for x in kpl_zt_days.get(c6, []) if x[0] < streak_start_dt]
        zt_1y = [x for x in past_kpl if (sd_d - datetime.date.fromisoformat(x[0])).days <= 365]
        is_nf = (len(zt_1y) == 0)
        hist_45_500 = {x[1] for x in past_kpl if 45 <= (sd_d - datetime.date.fromisoformat(x[0])).days <= 500}
        curr_th = kpl_day_plate.get((sd, c6), pl)
        feats["is_new_face_1y"].append(is_nf)
        feats["is_old_native_theme"].append((not is_nf) and bool(curr_th) and (curr_th in hist_45_500))
        feats["is_old_fake_new_concept"].append((not is_nf) and bool(curr_th) and (curr_th not in hist_45_500))

        feats["fst_mins"].append(fst_to_mins(r.first_seal_time))
        d3_p = pos - 2
        d4_p = pos - 1
        feats["d3_open_board"].append(bool(d3_p >= 0 and cb["low"][d3_p] < cb["zt_px"][d3_p] - 0.01))
        feats["d3_to"].append(float(cb["to"][d3_p]) if d3_p >= 0 else np.nan)
        avg_to20 = float(np.mean(cb["to"][max(0, d4_p - 20):d4_p])) if d4_p > 0 else float(cb["to"][d4_p])
        feats["d4_to_vs_ma20"].append(float(cb["to"][d4_p] / avg_to20) if avg_to20 > 0.01 else 1.0)

        adj_c = cb["close"][:pos] * cb["adjf"][:pos] / cb["adjf"][d4_p]
        ma20_c = float(np.mean(adj_c[max(0, len(adj_c) - 20):]))
        ma60_c = float(np.mean(adj_c[max(0, len(adj_c) - 60):]))
        feats["d4_close_vs_ma20"].append(float(adj_c[-1] / ma20_c - 1.0) if ma20_c > 0 else 0.0)
        feats["d4_close_vs_ma60"].append(float(adj_c[-1] / ma60_c - 1.0) if ma60_c > 0 else 0.0)
        feats["d4_body_pct"].append(float((cb["close"][d4_p] - cb["open"][d4_p]) / cb["pre_c"][d4_p]) if cb["pre_c"][d4_p] > 0 else 0.0)
        feats["ret_pre20"].append(float(adj_c[-1] / adj_c[max(0, len(adj_c) - 21)] - 1.0) if len(adj_c) >= 2 else 0.0)
        feats["ret_pre60"].append(float(adj_c[-1] / adj_c[max(0, len(adj_c) - 61)] - 1.0) if len(adj_c) >= 2 else 0.0)

        # Market / Micro / LHB
        feats["csi_1d_prev_pit"].append(float(CSI_MAP[sd] / CSI_MAP[ALL_CSI_DTS[ci - 1]] - 1.0) if ci >= 1 else 0.0)
        feats["reb_zt_r10_pit"].append(float(reb_map.get(sd, 0.0)))
        mc_r10, mc_ma20 = micro_map.get(sd, (0.0, True))
        feats["micro_mc_r10_pit"].append(float(mc_r10))
        feats["micro_gt_ma20_pit"].append(bool(mc_ma20))
        feats["prev_4b_plus_dt_cnt"].append(int(dt_b4_dt.get(sd, 0)))
        feats["prev_5b_min_open"].append(float(b5_min_open.get(bd, np.nan)))
        feats["plate_fb_ho_cnt"].append(int(fb_ho_map.get((sd, pl), 0)))

        b4 = buy_map.get((sd, c6), [])
        s4 = sell_map.get((sd, c6), [])
        tot_b = sum(x[1] for x in b4)
        tot_s = sum(x[1] for x in s4)
        amt_d4 = float(r.prev_amt) if pd.notna(r.prev_amt) and float(r.prev_amt) > 0 else 1.0
        feats["lhb_net_buy_ratio"].append((tot_b - tot_s) / amt_d4)
        feats["lhb_sell_lhasa_cnt"].append(sum(1 for dept, _ in s4 if RE_LHASA.search(dept)))

        d2 = str(cb["dts"][pos - 3]) if pos >= 3 else ""
        d3 = str(cb["dts"][pos - 2]) if pos >= 2 else ""
        b23 = buy_map.get((d2, c6), []) + buy_map.get((d3, c6), [])
        top23_names = [dept for dept, _ in b23 if RE_TOP_YOUZI.search(dept)]
        s4_names = [dept for dept, _ in s4]
        feats["lhb_d2d3_top_yz_locked"].append(bool(top23_names) and (not any(any(tn in sn for tn in top23_names) for sn in s4_names)))

        # Calendar PIT
        dow = bd_d.isoweekday()
        bm = bd_d.month
        feats["dow"].append(dow)
        feats["buy_month"].append(bm)
        feats["is_avoid_jan_may"].append(bm not in (1, 5))
        feats["is_avoid_thu_fri"].append(dow not in (4, 5))
        feats["is_clean_calendar"].append((bm not in (1, 5)) and (dow not in (4, 5)))

    for k, v in feats.items():
        df[k] = v
    return df


def eval_period_split(df_sub: pd.DataFrame, ret_col: str, exit_col: str, base_mean: float) -> dict:
    """对子集计算全期 + 2022-2023 + 2024-2026 三段完整单仓/等权/去Top3指标。"""
    m_all = eval_factor_slice(df_sub, ret_col=ret_col, exit_col=exit_col, rank_col="open_pct", base_mean=base_mean)
    m_e = eval_factor_slice(df_sub[df_sub["buy_date"] < "2024-01-01"], ret_col=ret_col, exit_col=exit_col, rank_col="open_pct", base_mean=base_mean)
    m_r = eval_factor_slice(df_sub[df_sub["buy_date"] >= "2024-01-01"], ret_col=ret_col, exit_col=exit_col, rank_col="open_pct", base_mean=base_mean)
    return {"all": m_all, "early": m_e, "recent": m_r}


def scan_boolean_feature(df: pd.DataFrame, col: str, ret_col: str, exit_col: str, base_mean: float) -> dict:
    """扫描布尔/二值特征 True vs False。"""
    valid = df[df[ret_col].notna() & df[col].notna()].copy()
    mask_t = valid[col].astype(float) > 0.5
    df_t = valid[mask_t]
    df_f = valid[~mask_t]

    mt = eval_factor_slice(df_t, ret_col=ret_col, exit_col=exit_col, rank_col="open_pct", base_mean=base_mean)
    mf = eval_factor_slice(df_f, ret_col=ret_col, exit_col=exit_col, rank_col="open_pct", base_mean=base_mean)

    mean_diff = mt["avg_ret"] - mf["avg_ret"]
    e_t = df_t[df_t["buy_date"] < "2024-01-01"][ret_col]
    e_f = df_f[df_f["buy_date"] < "2024-01-01"][ret_col]
    r_t = df_t[df_t["buy_date"] >= "2024-01-01"][ret_col]
    r_f = df_f[df_f["buy_date"] >= "2024-01-01"][ret_col]

    diff_e = (float(e_t.mean() - e_f.mean()) * 100) if (len(e_t) >= 2 and len(e_f) >= 2) else 0.0
    diff_r = (float(r_t.mean() - r_f.mean()) * 100) if (len(r_t) >= 2 and len(r_f) >= 2) else 0.0
    dual_same = bool(diff_e * diff_r > 0)

    yr_same = 0
    for yr in ("2022", "2023", "2024", "2025", "2026"):
        yt = df_t[df_t["buy_date"].str.startswith(yr)][ret_col]
        yf = df_f[df_f["buy_date"].str.startswith(yr)][ret_col]
        if len(yt) >= 1 and len(yf) >= 1:
            yd = float(yt.mean() - yf.mean())
            if yd * mean_diff > 0:
                yr_same += 1

    best_is_true = (mt["avg_ret"] >= mf["avg_ret"])
    best_m = mt if best_is_true else mf
    best_df = df_t if best_is_true else df_f
    best_split = eval_period_split(best_df, ret_col, exit_col, base_mean)

    return {
        "feature": col,
        "mode": ret_col,
        "feat_type": "bool",
        "n_valid": int(len(valid)),
        "n_bins": 2,
        "n_q1_or_false": mf["n_raw"],
        "n_q5_or_true": mt["n_raw"],
        "wr_q1_or_false": mf["wr_raw"],
        "wr_q5_or_true": mt["wr_raw"],
        "po_q1_or_false": mf["payoff_raw"],
        "po_q5_or_true": mt["payoff_raw"],
        "avg_q1_or_false": mf["avg_ret"],
        "avg_q2": np.nan,
        "avg_q3": np.nan,
        "avg_q4": np.nan,
        "avg_q5_or_true": mt["avg_ret"],
        "spread_q5_q1_or_tf": round(mean_diff, 2),
        "spread_22_23": round(diff_e, 2),
        "spread_24_26": round(diff_r, 2),
        "spearman_ic": np.nan,
        "spearman_ic_22_23": np.nan,
        "spearman_ic_24_26": np.nan,
        "dual_same_sign": dual_same,
        "pos_years_same_dir": yr_same,
        "best_side": "True" if best_is_true else "False",
        "best_n_raw": best_m["n_raw"],
        "best_wr_raw": best_m["wr_raw"],
        "best_payoff_raw": best_m["payoff_raw"],
        "best_ss_n": best_m["ss_n"],
        "best_ss_wr": best_m["ss_wr"],
        "best_ss_payoff": best_m["ss_payoff"],
        "best_ss_nav": best_m["ss_nav"],
        "best_ss_mdd": best_m["ss_mdd"],
        "best_ss_ex_top3_nav": best_m["ss_ex_top3_nav"],
        "best_eq_nav": best_m["eq_nav"],
        "best_ss_net_excess_5y": best_m["ss_net_excess_5y"],
        "best_ss_pos_years": best_m["ss_pos_years"],
        "best_early_ss_nav": best_split["early"]["ss_nav"],
        "best_early_ex_top3": best_split["early"]["ss_ex_top3_nav"],
        "best_recent_ss_nav": best_split["recent"]["ss_nav"],
        "best_recent_ex_top3": best_split["recent"]["ss_ex_top3_nav"],
    }


def scan_continuous_feature(df: pd.DataFrame, col: str, ret_col: str, exit_col: str, base_mean: float) -> dict:
    """按 2022-2023 训练集分位点切 Q1-Q5，测试单调性、IC、双期同向与单边最优分位净值。"""
    valid = df[df[ret_col].notna() & df[col].notna()].copy()
    vals = valid[col].to_numpy(dtype=float)
    rets = valid[ret_col].to_numpy(dtype=float)

    train_mask = valid["buy_date"] < "2024-01-01"
    train_vals = valid.loc[train_mask, col].to_numpy(dtype=float)
    if len(train_vals) < 10:
        train_vals = vals

    qs = np.nanquantile(train_vals, [0.2, 0.4, 0.6, 0.8])
    v_min, v_max = float(np.nanmin(vals)), float(np.nanmax(vals))
    edges = [float(e) for e in np.unique(qs) if v_min <= float(e) < v_max]
    # 确保每个分箱在全样本上至少有样本，避免上限截断导致 Q5 为空
    kept_edges = []
    prev_cut = -np.inf
    for e in edges:
        if np.sum((vals > prev_cut) & (vals <= e)) >= 3 and np.sum(vals > e) >= 3:
            kept_edges.append(e)
            prev_cut = e
    bins = np.concatenate(([-np.inf], kept_edges, [np.inf]))
    if len(bins) < 3:
        # 若零膨胀导致分位点坍缩，按中位数/众数二分
        med = float(np.nanmedian(train_vals))
        if np.sum(vals > med) >= 3 and np.sum(vals <= med) >= 3:
            bins = np.array([-np.inf, med, np.inf])
        else:
            cut = v_min + 1e-9 if np.sum(vals == v_min) > len(vals) * 0.5 else (v_min + v_max) / 2.0
            bins = np.array([-np.inf, cut, np.inf])

    n_bins = len(bins) - 1
    b_idx = pd.cut(valid[col].astype(float), bins=bins, labels=False, include_lowest=True)
    valid["_bin"] = b_idx

    bin_means = {}
    bin_counts = {}
    for b in range(n_bins):
        sub_b = valid[valid["_bin"] == b][ret_col]
        bin_means[b] = round(float(sub_b.mean()) * 100, 2) if len(sub_b) > 0 else np.nan
        bin_counts[b] = int(len(sub_b))

    q1_df = valid[valid["_bin"] == 0]
    q5_df = valid[valid["_bin"] == (n_bins - 1)]
    m_q1 = eval_factor_slice(q1_df, ret_col=ret_col, exit_col=exit_col, rank_col="open_pct", base_mean=base_mean)
    m_q5 = eval_factor_slice(q5_df, ret_col=ret_col, exit_col=exit_col, rank_col="open_pct", base_mean=base_mean)

    spread_all = m_q5["avg_ret"] - m_q1["avg_ret"]

    e_q1 = q1_df[q1_df["buy_date"] < "2024-01-01"][ret_col]
    e_q5 = q5_df[q5_df["buy_date"] < "2024-01-01"][ret_col]
    r_q1 = q1_df[q1_df["buy_date"] >= "2024-01-01"][ret_col]
    r_q5 = q5_df[q5_df["buy_date"] >= "2024-01-01"][ret_col]
    spread_e = (float(e_q5.mean() - e_q1.mean()) * 100) if (len(e_q1) >= 2 and len(e_q5) >= 2) else 0.0
    spread_r = (float(r_q5.mean() - r_q1.mean()) * 100) if (len(r_q1) >= 2 and len(r_q5) >= 2) else 0.0

    ic_all, _ = spearmanr(vals, rets)
    e_df = valid[valid["buy_date"] < "2024-01-01"]
    r_df = valid[valid["buy_date"] >= "2024-01-01"]
    ic_e = spearmanr(e_df[col].to_numpy(dtype=float), e_df[ret_col].to_numpy(dtype=float))[0] if len(e_df) >= 10 else 0.0
    ic_r = spearmanr(r_df[col].to_numpy(dtype=float), r_df[ret_col].to_numpy(dtype=float))[0] if len(r_df) >= 10 else 0.0
    ic_all = 0.0 if np.isnan(ic_all) else float(ic_all)
    ic_e = 0.0 if np.isnan(ic_e) else float(ic_e)
    ic_r = 0.0 if np.isnan(ic_r) else float(ic_r)

    dual_same = bool((spread_e * spread_r > 0) and (ic_e * ic_r > 0))
    yr_same = 0
    for yr in ("2022", "2023", "2024", "2025", "2026"):
        y1 = q1_df[q1_df["buy_date"].str.startswith(yr)][ret_col]
        y5 = q5_df[q5_df["buy_date"].str.startswith(yr)][ret_col]
        if len(y1) >= 1 and len(y5) >= 1:
            if float(y5.mean() - y1.mean()) * spread_all > 0:
                yr_same += 1

    best_is_q5 = (m_q5["avg_ret"] >= m_q1["avg_ret"])
    best_m = m_q5 if best_is_q5 else m_q1
    best_df = q5_df if best_is_q5 else q1_df
    best_split = eval_period_split(best_df, ret_col, exit_col, base_mean)

    q2_val = bin_means.get(1, np.nan) if n_bins >= 3 else np.nan
    q3_val = bin_means.get(2, np.nan) if n_bins >= 4 else np.nan
    q4_val = bin_means.get(3, np.nan) if n_bins >= 5 else np.nan

    return {
        "feature": col,
        "mode": ret_col,
        "feat_type": "cont",
        "n_valid": int(len(valid)),
        "n_bins": int(n_bins),
        "n_q1_or_false": m_q1["n_raw"],
        "n_q5_or_true": m_q5["n_raw"],
        "wr_q1_or_false": m_q1["wr_raw"],
        "wr_q5_or_true": m_q5["wr_raw"],
        "po_q1_or_false": m_q1["payoff_raw"],
        "po_q5_or_true": m_q5["payoff_raw"],
        "avg_q1_or_false": m_q1["avg_ret"],
        "avg_q2": q2_val,
        "avg_q3": q3_val,
        "avg_q4": q4_val,
        "avg_q5_or_true": m_q5["avg_ret"],
        "spread_q5_q1_or_tf": round(spread_all, 2),
        "spread_22_23": round(spread_e, 2),
        "spread_24_26": round(spread_r, 2),
        "spearman_ic": round(ic_all, 4),
        "spearman_ic_22_23": round(ic_e, 4),
        "spearman_ic_24_26": round(ic_r, 4),
        "dual_same_sign": dual_same,
        "pos_years_same_dir": yr_same,
        "best_side": "Q5" if best_is_q5 else "Q1",
        "best_n_raw": best_m["n_raw"],
        "best_wr_raw": best_m["wr_raw"],
        "best_payoff_raw": best_m["payoff_raw"],
        "best_ss_n": best_m["ss_n"],
        "best_ss_wr": best_m["ss_wr"],
        "best_ss_payoff": best_m["ss_payoff"],
        "best_ss_nav": best_m["ss_nav"],
        "best_ss_mdd": best_m["ss_mdd"],
        "best_ss_ex_top3_nav": best_m["ss_ex_top3_nav"],
        "best_eq_nav": best_m["eq_nav"],
        "best_ss_net_excess_5y": best_m["ss_net_excess_5y"],
        "best_ss_pos_years": best_m["ss_pos_years"],
        "best_early_ss_nav": best_split["early"]["ss_nav"],
        "best_early_ex_top3": best_split["early"]["ss_ex_top3_nav"],
        "best_recent_ss_nav": best_split["recent"]["ss_nav"],
        "best_recent_ex_top3": best_split["recent"]["ss_ex_top3_nav"],
    }


def build_2way_interactions(df: pd.DataFrame):
    """构造 30 组物理第一性原理双因子正交交互条件。"""
    tox_reg = (df["has_tox_notice_pit"] == True) | (df["has_stock_reg_pit"] == True)
    le5 = df["mkt_max_board_prev"] <= 5
    sole = df["is_sole_4b"] == 1
    lock50 = df["lock_top10"] >= 50.0
    rfm_12_35 = df["real_free_mcap"].between(12.0, 35.0)
    op_2_65 = df["open_pct"].between(0.020, 0.065)
    clean_cal = df["is_clean_calendar"] == True
    to_85_25 = df["prev_to"].between(8.5, 25.0)
    zero_lh = df["lhasa_seats_prev"] == 0
    hr_safe = df["headroom_100"] >= 0.22
    ice_50 = df["mkt_zt_prev"] < 50
    op_brk = df["open_board_count"] >= 1
    px_le20 = df["px_d4"] <= 20.0
    ech = df["has_4321_echelon"] == 1
    q_ge1 = df["lhb_quant_cnt"] >= 1
    p_elo105 = df["p_elo"] >= 105.0
    brk60 = df["clean_brk60"] == True

    return [
        ("I01_maxle5_x_lock50", "最高板<=5 × 锁仓>=50%", le5 & lock50),
        ("I02_maxle5_x_rfm12_35", "最高板<=5 × 轻盈真流通12-35亿", le5 & rfm_12_35),
        ("I03_sole4b_x_open2_65", "唯一4板独苗 × 竞价2%-6.5%", sole & op_2_65),
        ("I04_cleancal_x_maxle5", "非1/5月非周四五 × 最高板<=5", clean_cal & le5),
        ("I05_to85_25_x_zerolh", "四板换手8.5-25% × 零拉萨", to_85_25 & zero_lh),
        ("I06_ice50_x_sole4b", "冰点涨停<50家 × 唯一4板独苗", ice_50 & sole),
        ("I07_maxle5_x_sole4b", "最高板<=5 × 唯一4板独苗", le5 & sole),
        ("I08_maxle5_x_open2_65", "最高板<=5 × 竞价2%-6.5%", le5 & op_2_65),
        ("I09_maxle5_x_hrsafe", "最高板<=5 × 净空头顶>=22%", le5 & hr_safe),
        ("I10_maxle5_x_to85_25", "最高板<=5 × 四板换手8.5-25%", le5 & to_85_25),
        ("I11_maxle5_x_zerolh", "最高板<=5 × 零拉萨", le5 & zero_lh),
        ("I12_maxle5_x_notoxreg", "最高板<=5 × 无毒无监管", le5 & (~tox_reg)),
        ("I13_maxle5_x_openbrk", "最高板<=5 × 曾开板换手>=1", le5 & op_brk),
        ("I14_maxle5_x_pxle20", "最高板<=5 × 四板股价<=20元", le5 & px_le20),
        ("I15_maxle5_x_ech4321", "最高板<=5 × 4321完整梯队", le5 & ech),
        ("I16_maxle5_x_quant", "最高板<=5 × 量化席位>=1", le5 & q_ge1),
        ("I17_sole4b_x_lock50", "唯一4板独苗 × 锁仓>=50%", sole & lock50),
        ("I18_sole4b_x_rfm12_35", "唯一4板独苗 × 轻盈真流通12-35亿", sole & rfm_12_35),
        ("I19_sole4b_x_notoxreg", "唯一4板独苗 × 无毒无监管", sole & (~tox_reg)),
        ("I20_sole4b_x_cleancal", "唯一4板独苗 × 非1/5月非周四五", sole & clean_cal),
        ("I21_lock50_x_rfm12_35", "锁仓>=50% × 轻盈真流通12-35亿", lock50 & rfm_12_35),
        ("I22_lock50_x_open2_65", "锁仓>=50% × 竞价2%-6.5%", lock50 & op_2_65),
        ("I23_rfm12_35_x_open2_65", "轻盈真流通12-35亿 × 竞价2%-6.5%", rfm_12_35 & op_2_65),
        ("I24_cleancal_x_lock50", "非1/5月非周四五 × 锁仓>=50%", clean_cal & lock50),
        ("I25_cleancal_x_open2_65", "非1/5月非周四五 × 竞价2%-6.5%", clean_cal & op_2_65),
        ("I26_openbrk_x_open2_65", "曾开板换手>=1 × 竞价2%-6.5%", op_brk & op_2_65),
        ("I27_notoxreg_x_to85_25", "无毒无监管 × 四板换手8.5-25%", (~tox_reg) & to_85_25),
        ("I28_hrsafe_x_rfm12_35", "净空头顶>=22% × 轻盈真流通12-35亿", hr_safe & rfm_12_35),
        ("I29_pelo105_x_maxle5", "题材强度>=105 × 最高板<=5", p_elo105 & le5),
        ("I30_brk60_x_maxle5", "60日干净突破 × 最高板<=5", brk60 & le5),
    ]


def main():
    df_raw = pd.read_parquet(f"{AST2_DIR}/p2_4to5/cand_4to5_enriched.parquet")
    df = df_raw[df_raw["is_main_10cm"] & df_raw["buyable_open"]].copy().reset_index(drop=True)
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f:
        cb_map = pickle.load(f)["code_bars"]

    df = build_supplemental_pit_features(df, cb_map)

    needed_5m = set()
    for r in df.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)[:10]
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

    # 计算两套真实收益序列：ret_open_v34 与 ret_t65_v34
    for mode_key, ret_col, exit_col in [
        ("open", "ret_open_v34", "exit_open_v34"),
        ("t65", "ret_t65_v34", "exit_t65_v34"),
    ]:
        rets, ex_dts, b5m, h5m = [], [], [], []
        for r in df.itertuples(index=False):
            res = sim_one_trade(str(r.code).zfill(6), str(r.buy_date)[:10], cb_map.get(str(r.code).zfill(6)), bars_5m_map, mode_key)
            if res is None:
                rets.append(np.nan); ex_dts.append(""); b5m.append(False); h5m.append(False)
            else:
                rets.append(res["net_ret"]); ex_dts.append(res["exit_date"]); b5m.append(res["buy_5m_cov"]); h5m.append(res["hold_5m_cov"])
        df[ret_col] = rets
        df[exit_col] = ex_dts
        df[f"buy5m_{mode_key}"] = b5m
        df[f"hold5m_{mode_key}"] = h5m

    # 识别全部有效数值与布尔特征列
    exclude_cols = FUTURE_COLS | META_STR_COLS | {
        "ret_open_v34", "exit_open_v34", "buy5m_open", "hold5m_open",
        "ret_t65_v34", "exit_t65_v34", "buy5m_t65", "hold5m_t65",
    }
    feat_cols, const_skipped = [], []
    for c in df.columns:
        if c in exclude_cols:
            continue
        if df[c].dtype == object:
            continue
        nu = df[c].dropna().nunique()
        if nu <= 1:
            const_skipped.append(c)
            continue
        feat_cols.append(c)

    # 任务 A：全列单调性扫描
    q_rows = []
    for ret_col, exit_col in [("ret_open_v34", "exit_open_v34"), ("ret_t65_v34", "exit_t65_v34")]:
        base_m = float(df[ret_col].dropna().mean())
        for c in feat_cols:
            s_val = df[c].dropna()
            uniq_vals = set(s_val.unique())
            is_bin = (df[c].dtype == bool) or (len(uniq_vals) == 2 and uniq_vals.issubset({0, 1, 0.0, 1.0, False, True}))
            if is_bin:
                q_rows.append(scan_boolean_feature(df, c, ret_col, exit_col, base_m))
            else:
                q_rows.append(scan_continuous_feature(df, c, ret_col, exit_col, base_m))

    q_df = pd.DataFrame(q_rows)
    q_df.to_csv(OUT_Q_CSV, index=False, encoding="utf-8-sig")

    # 任务 B：30 组双因子物理正交交互扫描
    inter_specs = build_2way_interactions(df)
    i_rows = []
    for ret_col, exit_col in [("ret_open_v34", "exit_open_v34"), ("ret_t65_v34", "exit_t65_v34")]:
        base_m = float(df[ret_col].dropna().mean())
        for name_id, desc, mask in inter_specs:
            sub = df[mask & df[ret_col].notna()].copy()
            sp = eval_period_split(sub, ret_col, exit_col, base_m)
            ma, me, mr = sp["all"], sp["early"], sp["recent"]
            dual_ex13 = bool(me["ss_ex_top3_nav"] > 1.30 and mr["ss_ex_top3_nav"] > 1.30)
            dual_gold = bool(dual_ex13 and me["ss_wr"] >= 55.0 and mr["ss_wr"] >= 55.0 and me["ss_payoff"] >= 1.20 and mr["ss_payoff"] >= 1.20)
            i_rows.append({
                "interaction_id": name_id,
                "desc": desc,
                "mode": ret_col,
                "n_raw": ma["n_raw"],
                "wr_raw": ma["wr_raw"],
                "payoff_raw": ma["payoff_raw"],
                "avg_ret": ma["avg_ret"],
                "delta_vs_base": ma["delta_vs_base"],
                "ss_n": ma["ss_n"],
                "ss_wr": ma["ss_wr"],
                "ss_payoff": ma["ss_payoff"],
                "ss_nav": ma["ss_nav"],
                "ss_mdd": ma["ss_mdd"],
                "ss_ex_top3_nav": ma["ss_ex_top3_nav"],
                "eq_nav": ma["eq_nav"],
                "ss_net_excess_5y": ma["ss_net_excess_5y"],
                "ss_pos_years": ma["ss_pos_years"],
                "e_n_raw": me["n_raw"],
                "e_ss_n": me["ss_n"],
                "e_ss_wr": me["ss_wr"],
                "e_ss_payoff": me["ss_payoff"],
                "e_ss_nav": me["ss_nav"],
                "e_ss_ex_top3_nav": me["ss_ex_top3_nav"],
                "r_n_raw": mr["n_raw"],
                "r_ss_n": mr["ss_n"],
                "r_ss_wr": mr["ss_wr"],
                "r_ss_payoff": mr["ss_payoff"],
                "r_ss_nav": mr["ss_nav"],
                "r_ss_ex_top3_nav": mr["ss_ex_top3_nav"],
                "dual_ex_top3_gt_130": dual_ex13,
                "dual_gold_flag": dual_gold,
            })

    i_df = pd.DataFrame(i_rows)
    i_df.to_csv(OUT_I_CSV, index=False, encoding="utf-8-sig")

    # 汇总 JSON
    base_open = eval_period_split(df[df["ret_open_v34"].notna()], "ret_open_v34", "exit_open_v34", 0.0)
    base_t65 = eval_period_split(df[df["ret_t65_v34"].notna()], "ret_t65_v34", "exit_t65_v34", 0.0)

    top_open_feats = q_df[(q_df["mode"] == "ret_open_v34") & (q_df["dual_same_sign"]) & (q_df["best_ss_n"] >= 30)].sort_values("best_ss_ex_top3_nav", ascending=False).head(15)
    top_t65_feats = q_df[(q_df["mode"] == "ret_t65_v34") & (q_df["dual_same_sign"]) & (q_df["best_ss_n"] >= 20)].sort_values("best_ss_ex_top3_nav", ascending=False).head(15)
    gold_inter_open = i_df[(i_df["mode"] == "ret_open_v34") & (i_df["dual_ex_top3_gt_130"])].sort_values("ss_ex_top3_nav", ascending=False)
    gold_inter_t65 = i_df[(i_df["mode"] == "ret_t65_v34") & (i_df["dual_ex_top3_gt_130"])].sort_values("ss_ex_top3_nav", ascending=False)

    summary = {
        "pool_n": int(len(df)),
        "scanned_features_n": int(len(feat_cols)),
        "const_skipped": const_skipped,
        "excluded_future_cols": sorted(FUTURE_COLS),
        "coverage": {
            "open_trades": int(df["ret_open_v34"].notna().sum()),
            "open_buy5m_pct": round(float(df.loc[df["ret_open_v34"].notna(), "buy5m_open"].mean()) * 100, 2),
            "open_hold5m_pct": round(float(df.loc[df["ret_open_v34"].notna(), "hold5m_open"].mean()) * 100, 2),
            "t65_trades": int(df["ret_t65_v34"].notna().sum()),
            "t65_buy5m_pct": round(float(df.loc[df["ret_t65_v34"].notna(), "buy5m_t65"].mean()) * 100, 2),
            "t65_hold5m_pct": round(float(df.loc[df["ret_t65_v34"].notna(), "hold5m_t65"].mean()) * 100, 2),
        },
        "baseline_ret_open_v34": base_open,
        "baseline_ret_t65_v34": base_t65,
        "dual_same_sign_counts": {
            "ret_open_v34": int(q_df[(q_df["mode"] == "ret_open_v34") & (q_df["dual_same_sign"])].shape[0]),
            "ret_t65_v34": int(q_df[(q_df["mode"] == "ret_t65_v34") & (q_df["dual_same_sign"])].shape[0]),
        },
        "top15_dual_features_open": top_open_feats[["feature", "feat_type", "best_side", "best_ss_n", "best_ss_wr", "best_ss_payoff", "best_ss_nav", "best_ss_ex_top3_nav", "spread_22_23", "spread_24_26", "pos_years_same_dir"]].to_dict("records"),
        "top15_dual_features_t65": top_t65_feats[["feature", "feat_type", "best_side", "best_ss_n", "best_ss_wr", "best_ss_payoff", "best_ss_nav", "best_ss_ex_top3_nav", "spread_22_23", "spread_24_26", "pos_years_same_dir"]].to_dict("records"),
        "dual_ex130_interactions_open": gold_inter_open.to_dict("records"),
        "dual_ex130_interactions_t65": gold_inter_t65.to_dict("records"),
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[A5 Done] pool={len(df)}, scanned_features={len(feat_cols)}, const_skipped={const_skipped}")
    print(f"Baseline open: n={base_open['all']['n_raw']}, ss_n={base_open['all']['ss_n']}, wr={base_open['all']['ss_wr']}%, po={base_open['all']['ss_payoff']}, nav={base_open['all']['ss_nav']}x, ex3={base_open['all']['ss_ex_top3_nav']}x")
    print(f"Baseline t65 : n={base_t65['all']['n_raw']}, ss_n={base_t65['all']['ss_n']}, wr={base_t65['all']['ss_wr']}%, po={base_t65['all']['ss_payoff']}, nav={base_t65['all']['ss_nav']}x, ex3={base_t65['all']['ss_ex_top3_nav']}x")
    print(f"Dual same-sign features: open={summary['dual_same_sign_counts']['ret_open_v34']}/{len(feat_cols)}, t65={summary['dual_same_sign_counts']['ret_t65_v34']}/{len(feat_cols)}")
    print(f"Dual exTop3>1.3x interactions: open={len(gold_inter_open)}/30, t65={len(gold_inter_t65)}/30")


if __name__ == "__main__":
    main()

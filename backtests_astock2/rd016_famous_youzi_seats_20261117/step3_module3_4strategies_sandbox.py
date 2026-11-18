#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD016 Module 3: 4 Strategies Independent Sandbox LHB Scoring Backtests (30bps, IS->OOS Blind, Physical Truncation)."""

import json
import os
import pickle
import re
import time
from collections import defaultdict

import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
SANDBOX = f"{SIM}/backtests_astock2/rd016_famous_youzi_seats_20261117"
HIGH_DIR = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
IDX_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"

FEE_30BPS = 0.0030

# Strict IS-only (2021-2023) selected seat codes & icons
IS_GOOD_CODES = {
    "10430845", "10102873", "10046704", "10023415", "10026767", "10142874",
    "10122927", "10045035", "10025390", "10147201", "10318896",
    "10434470", "10634757", "10000100571", "10000399618", "10110478",
}
IS_GOOD_ICONS = {"涪陵广场路", "北京帮", "上海超短", "招商深南东", "徐留胜", "交易猿", "古北路", "小鳄鱼"}

IS_BAD_CODES = {
    "10063083", "10000147202", "10050414", "10115140", "10023543", "10046458",
    "10046604", "10485003", "10028577", "10547746", "10456237", "10027014",
    "10143030", "10477736", "10023559", "10026729",
}
IS_BAD_ICONS = {"上塘路", "宁波和源路", "成泉系", "北京中关村", "赵老哥", "新生代", "N周二", "金田路", "玉兰路", "苏州帮", "苏南帮", "湖州劳动路"}

# Pure day-surfing codes (removing 开源西安西大街, adding normalized code for 宜昌珍珠/沿江)
PURE_SURF_CODES = {"10063083", "10026729", "10477736", "10023559", "10026897", "10342919"}
XIAN_XIDAJIE = "10046745"


def to_30bps(r_20bps: float) -> float:
    return (1.0 + float(r_20bps)) / 0.9980 * 0.9970 - 1.0


def build_lhb_features(lhb: pd.DataFrame, ths: pd.DataFrame, bayes_df: pd.DataFrame) -> tuple:
    dept_names = lhb[lhb["dept_code"] != "0"][["dept_code", "dept_name"]].drop_duplicates()
    lhasa_pure = set(dept_names[dept_names["dept_name"].str.contains("拉萨", na=False) & (~dept_names["dept_name"].str.contains("东亚", na=False))]["dept_code"])
    foshan_codes = set(dept_names[dept_names["dept_name"].str.contains("佛山绿景路|光大证券.*佛山", regex=True, na=False)]["dept_code"])
    surf_fixed_codes = PURE_SURF_CODES | foshan_codes

    b_map = {}
    for (dt, sc), g in bayes_df.groupby(["date", "stock_code"], sort=False):
        w = np.maximum(g["NET"].to_numpy(dtype=float), 1.0)
        b_map[(dt, sc)] = (
            float(np.sum(w * g["b_c"].to_numpy()) / np.sum(w)),
            float(np.sum(w * g["b_t2"].to_numpy()) / np.sum(w)),
        )

    ths_map = {}
    for r in ths.itertuples(index=False):
        ths_map[(r.date, r.stock_code, int(r.is_three))] = (
            set(str(r.capital_icons_str or "").split("|")) - {""},
            float(r.org_inflow) if pd.notna(r.org_inflow) else 0.0,
        )

    feat = {}
    for (dt, sc, is3), grp in lhb.groupby(["date", "stock_code", "is_three"], sort=False):
        b_rows = grp[grp["side"] == "B"]
        tot_b = float(b_rows["BUY"].sum())
        b_pos = b_rows[b_rows["NET"] > 0]
        b_pos_codes = set(b_pos["dept_code"])
        all_b_codes = set(b_rows["dept_code"])

        lh_all_cnt = len(all_b_codes & lhasa_pure)
        lh_buy_amt = float(b_rows[b_rows["dept_code"].isin(lhasa_pure)]["BUY"].sum())
        lh_share = (lh_buy_amt / tot_b) if tot_b > 0 else 0.0
        lh_net_pos = float(b_rows[b_rows["dept_code"].isin(lhasa_pure)]["NET"].sum()) > 0

        t_info = ths_map.get((dt, sc, int(is3)), (set(), 0.0))
        icons = t_info[0]
        org_net = t_info[1]
        n_org_b = int((b_rows["dept_code"] == "0").sum())

        bc, bt2 = b_map.get((dt, sc), (0.0, 0.0)) if is3 == 0 else (0.0, 0.0)
        feat[(dt, sc, int(is3))] = {
            "has_lhb": 1,
            "lh_cnt": lh_all_cnt,
            "lh_share": lh_share,
            "lh_net_pos": int(lh_net_pos),
            "lh_pure_bad": int(lh_net_pos and (lh_share >= 0.15 or lh_all_cnt >= 2)),
            "has_is_good": int(bool((b_pos_codes & IS_GOOD_CODES) or (icons & IS_GOOD_ICONS))),
            "has_is_bad": int(bool((b_pos_codes & IS_BAD_CODES) or (icons & IS_BAD_ICONS))),
            "has_surf_fixed": int(bool(all_b_codes & surf_fixed_codes)),
            "has_xian": int(XIAN_XIDAJIE in b_pos_codes),
            "pure_org": int((n_org_b >= 2) and (org_net > 1e7) and (lh_all_cnt == 0)),
            "bayes_c": bc,
            "bayes_t2": bt2,
        }
    return feat


def calc_d15_metrics(slot_df: pd.DataFrame, raw_df: pd.DataFrame, sh300: dict, windows: list) -> dict:
    all_dts = sorted(sh300.keys())

    def bench_ret(s_dt: str, e_dt: str) -> float:
        prevs = [d for d in all_dts if d < s_dt]
        posts = [d for d in all_dts if d <= e_dt]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_dts[0]]
        p1 = sh300[posts[-1]]
        return float(p1 / p0 - 1.0)

    out = {}
    for wname, sdt, edt in windows:
        ss = slot_df[(slot_df["buy_date"] >= sdt) & (slot_df["buy_date"] <= edt)] if not slot_df.empty else slot_df
        sr = raw_df[(raw_df["buy_date"] >= sdt) & (raw_df["buy_date"] <= edt)] if not raw_df.empty else raw_df
        csi_p = round(bench_ret(sdt, edt) * 100.0, 2)
        if ss.empty:
            out[wname] = {
                "raw_n": int(len(sr)), "n": 0, "wr_pct": 0.0, "plr": 0.0, "nav_1s": 1.0,
                "cap10m_mult": 1.0, "eq_nav": 1.0, "mdd_pct": 0.0, "csi300_pct": csi_p,
                "excess_pp": round(-csi_p, 2), "hlz_t": 0.0,
            }
            continue
        rets = ss["net_ret"].to_numpy(dtype=float)
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        wr = float((rets > 0).mean() * 100.0)
        plr = float(wins.mean() / abs(losses.mean())) if (len(wins) and len(losses) and losses.mean() < 0) else 99.0
        nav = 1.0; pk = 1.0; mdd = 0.0; cap1m = 100.0
        for r in rets:
            nav *= (1.0 + float(r))
            pk = max(pk, nav)
            mdd = max(mdd, (pk - nav) / pk)
            cap1m += min(cap1m, 1000.0) * float(r)
        eq_nav = float(np.prod(1.0 + sr.groupby("buy_date")["net_ret"].mean().to_numpy(dtype=float))) if not sr.empty else 1.0
        ex_arr = np.array([float(r.net_ret) - bench_ret(str(r.buy_date), str(r.exit_date)) for r in ss.itertuples(index=False)], dtype=float)
        hlz_t = float((ex_arr.mean() / ex_arr.std(ddof=1)) * np.sqrt(len(ex_arr))) if (len(ex_arr) > 1 and ex_arr.std(ddof=1) > 0) else 0.0
        out[wname] = {
            "raw_n": int(len(sr)),
            "n": int(len(rets)),
            "wr_pct": round(wr, 2),
            "plr": round(plr, 2),
            "mean_pct": round(float(rets.mean() * 100.0), 2),
            "nav_1s": round(nav, 2),
            "cap10m_mult": round(cap1m / 100.0, 2),
            "eq_nav": round(eq_nav, 2),
            "mdd_pct": round(mdd * 100.0, 2),
            "csi300_pct": csi_p,
            "excess_pp": round((nav - 1.0) * 100.0 - csi_p, 2),
            "hlz_t": round(hlz_t, 2),
        }
    return out


def sim_slot_generic(raw_df: pd.DataFrame, sort_cols: list, asc: list, strict_open_gt: bool = True) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame()
    srt = raw_df.sort_values(sort_cols, ascending=asc)
    taken, free_dt, free_hh = [], "", 0
    for r in srt.itertuples(index=False):
        bd = str(r.buy_date)
        bh = int(r.buy_hhmm)
        if (not free_dt) or (bd > free_dt) or (bd == free_dt and (bh > free_hh if strict_open_gt else bh >= free_hh)):
            taken.append(r._asdict())
            free_dt = str(r.exit_date)
            free_hh = int(r.exit_hhmm)
    return pd.DataFrame(taken)


def run_1to2_sandbox(cache, feat, sh300, wins):
    fb = cache["fb_cand"].copy()
    fb = fb[fb["d2_dt"] >= "2021-11-15"].copy().reset_index(drop=True)
    fb["buy_date"] = fb["d2_dt"]
    fb["code"] = fb["c6"]

    f_d1 = [feat.get((d, c, 0), {"has_lhb": 0, "lh_cnt": 0, "lh_net_pos": 0, "has_is_good": 0, "has_is_bad": 0, "bayes_t2": 0.0, "has_surf_fixed": 0})
            for d, c in zip(fb["dt_str"], fb["c6"])]
    fb["has_lhb"] = [x["has_lhb"] for x in f_d1]
    fb["has_is_good"] = [x["has_is_good"] for x in f_d1]
    fb["has_is_bad"] = [x["has_is_bad"] for x in f_d1]
    fb["lh_net_pos"] = [x["lh_net_pos"] for x in f_d1]
    fb["bayes_t2"] = [x["bayes_t2"] for x in f_d1]
    fb["has_surf_fixed"] = [x["has_surf_fixed"] for x in f_d1]

    def eval_12_exact(mask_vec, sv_vec):
        sub = fb[mask_vec].copy()
        sub["sv_use"] = sv_vec[mask_vec]
        srt = sub.sort_values(["d2_dt", "sv_use"], ascending=[True, False])
        taken, raw_list, free_dt, free_open = [], [], "", False
        for d2, grp in srt.groupby("d2_dt", sort=True):
            if free_dt == "" or d2 > free_dt or (d2 == free_dt and free_open):
                tr1 = grp.iloc[0]["sim_tr"]
                if isinstance(tr1, dict):
                    t_c = dict(tr1, net_ret=to_30bps(tr1["net_ret"]))
                    free_dt, free_open = t_c["exit_date"], bool(t_c["exit_at_open"])
                    taken.append(t_c)
            for tr in grp["sim_tr"]:
                if isinstance(tr, dict):
                    raw_list.append(dict(tr, net_ret=to_30bps(tr["net_ret"])))
        slot = pd.DataFrame(taken)
        raw_df = pd.DataFrame(raw_list)
        return calc_d15_metrics(slot, raw_df, sh300, wins), slot

    m_base = fb["mask_v19"].to_numpy()
    sv_base = fb["_sv_v19"].to_numpy()

    # S1: Re-rank + slight gate: within V19_pass, give priority +10 to D1 has_lhb & not bad, -10 to lh_net_pos/is_bad
    # S2: Unlock near-threshold (score_active >= 295 on main track pass_l1/l2/l3? wait, just test delta on V19_pass vs filtering out bad LHB!)
    m_nolh_bad = m_base & (~((fb["lh_net_pos"] == 1) | (fb["has_is_bad"] == 1)).to_numpy())
    sv_good_prio = sv_base + np.where(fb["has_is_good"] == 1, 15.0, 0.0) - np.where(fb["has_is_bad"] == 1, 15.0, 0.0)
    sv_bayes_prio = sv_base + np.clip(fb["bayes_t2"].to_numpy() * 1000.0, -15.0, 15.0)

    # Also test: filter V19_pass by bayes_t2 < -0.005
    m_no_bayes_neg = m_base & (fb["bayes_t2"].to_numpy() >= -0.005)

    res = {}
    res["A0_V19_基准(30bps)"], _ = eval_12_exact(m_base, sv_base)
    res["A1_V19_剔除D1拉萨净买或毒药"], _ = eval_12_exact(m_nolh_bad, sv_base)
    res["A2_V19_好坏游资调排序(+-15)"], _ = eval_12_exact(m_base, sv_good_prio)
    res["A3_V19_贝叶斯滚动排序(+-15)"], _ = eval_12_exact(m_base, sv_bayes_prio)
    res["A4_V19_剔除贝叶斯差席位(<-0.5%)"], _ = eval_12_exact(m_no_bayes_neg, sv_base)
    return res


def run_2to3_sandbox(cache, feat, sh300, wins):
    g23 = cache["g23_5y"].copy()
    g23["c6"] = g23["code"].astype(str).str.zfill(6)
    g23["net_ret"] = g23["ret_v2"].apply(to_30bps)
    g23["exit_date"] = g23["ed_v2"]
    g23["exit_hhmm"] = g23["eh_v2"]
    g23["buy_hhmm"] = 925

    f_s = [feat.get((d, c, 0), {"has_lhb": 0}) for d, c in zip(g23["sig_date"], g23["c6"])]
    f_3 = [feat.get((d, c, 1), {"has_lhb": 0}) for d, c in zip(g23["sig_date"], g23["c6"])]
    f_use = [a if a["has_lhb"] else b for a, b in zip(f_s, f_3)]
    empty_f = {"has_lhb": 0, "lh_cnt": 0, "lh_share": 0.0, "lh_net_pos": 0, "lh_pure_bad": 0, "has_is_good": 0, "has_is_bad": 0, "pure_org": 0, "bayes_t2": 0.0}
    f_use = [x if x["has_lhb"] else empty_f for x in f_use]

    for k in ["has_lhb", "lh_cnt", "lh_net_pos", "lh_pure_bad", "has_is_good", "has_is_bad", "pure_org", "bayes_t2"]:
        g23[k] = [x[k] for x in f_use]

    def eval_23(sc_vec, thr=90.0):
        sub = g23[sc_vec >= thr].copy()
        sub["sc_use"] = sc_vec[sc_vec >= thr]
        slot = sim_slot_generic(sub, ["buy_date", "sc_use", "open_pct", "plate_sz", "c6"], [True, False, True, True, True], strict_open_gt=True)
        return calc_d15_metrics(slot, sub, sh300, wins)

    sc_base = g23["score_v2"].to_numpy()
    # B1: Naive full-market positive/negative leaderboard (+6 good, -8 bad/lhasa)
    sc_naive = sc_base + np.where(g23["has_is_good"] == 1, 6.0, 0.0) - np.where((g23["has_is_bad"] == 1) | (g23["lh_net_pos"] == 1), 8.0, 0.0)
    # B2: Strict IS-discovered PureOrg penalty (-10)
    sc_org_pen = sc_base - np.where(g23["pure_org"] == 1, 10.0, 0.0)
    # B3: Bayes rolling 250d (+6 if >+0.5%, -6 if <-0.5%)
    sc_bayes = sc_base + np.where(g23["bayes_t2"] > 0.005, 6.0, np.where(g23["bayes_t2"] < -0.005, -6.0, 0.0))
    # B4: Reverse hypothesis (if low-open washout by Lhasa/bad actually helps 2to3, penalize good+org -6, bonus washout +4)
    sc_wash_only = sc_base - np.where((g23["pure_org"] == 1) | (g23["has_is_good"] == 1), 6.0, 0.0)

    return {
        "B0_V20_基准(30bps_零LHB)": eval_23(sc_base, 90.0),
        "B1_套用全市场正负榜(+6/-8)": eval_23(sc_naive, 90.0),
        "B2_仅IS发现纯机构弱开排雷(-10)": eval_23(sc_org_pen, 90.0),
        "B3_贝叶斯滚动口碑(+6/-6)": eval_23(sc_bayes, 90.0),
        "B4_IS验证好席位机构弱开陷阱扣分(-6)": eval_23(sc_wash_only, 90.0),
    }


def run_3to4_sandbox(cache, feat, sh300, wins):
    c34 = cache["c34_sk"].copy()
    c34 = c34[c34["p_1030"].notna()].copy().reset_index(drop=True)
    p_df = pd.DataFrame([dict(x, net_ret=to_30bps(x["net_ret"])) for x in c34["p_1030"]])
    c34["buy_hhmm"] = p_df["buy_hhmm"]
    c34["exit_date"] = p_df["exit_date"]
    c34["exit_hhmm"] = p_df["exit_hhmm"]
    c34["net_ret"] = p_df["net_ret"]
    c34["c6"] = c34["code"].astype(str).str.zfill(6)

    f_s = [feat.get((d, c, 0), {"has_lhb": 0}) for d, c in zip(c34["sig_date"], c34["c6"])]
    f_3 = [feat.get((d, c, 1), {"has_lhb": 0}) for d, c in zip(c34["sig_date"], c34["c6"])]
    empty_f = {"has_lhb": 0, "lh_cnt": 0, "lh_share": 0.0, "lh_net_pos": 0, "lh_pure_bad": 0, "has_is_good": 0, "has_is_bad": 0, "has_surf_fixed": 0, "bayes_t2": 0.0}
    f_use = [a if a["has_lhb"] else (b if b["has_lhb"] else empty_f) for a, b in zip(f_s, f_3)]
    for k in empty_f:
        c34[k] = [x[k] for x in f_use]

    # Existing V40 LHB components in c34:
    # T05: +4 if lhb_lh_cnt == 0; T12: -12 if surf_yz_buy; T21: -5 if lhb_lh_cnt >= 3
    old_lhb_pts = (
        np.where(c34["lhb_lh_cnt"] == 0, 4.0, 0.0)
        + np.where(c34["surf_yz_buy"], -12.0, 0.0)
        + np.where(c34["lhb_lh_cnt"] >= 3, -5.0, 0.0)
    )
    sc_base = c34["sc_v40"].to_numpy()
    sc_no_lhb = sc_base - old_lhb_pts

    # C2: Fix T12 (remove 开源西安西大街, add 国泰海通宜昌沿江 via code) + Pure Buy-side Lhasa
    fixed_lhb_pts = (
        np.where(c34["lh_cnt"] == 0, 4.0, 0.0)
        + np.where(c34["has_surf_fixed"] == 1, -12.0, 0.0)
        + np.where(c34["lh_pure_bad"] == 1, -5.0, 0.0)
    )
    sc_fixed = sc_no_lhb + fixed_lhb_pts

    # C3: V40 + IS good/bad fine adjustment (+4 good, -6 bad)
    sc_fine = sc_base + np.where(c34["has_is_good"] == 1, 4.0, 0.0) - np.where(c34["has_is_bad"] == 1, 6.0, 0.0)
    # C4: V40 + Bayes rolling 250d (+4 / -6)
    sc_bayes = sc_base + np.where(c34["bayes_t2"] > 0.005, 4.0, np.where(c34["bayes_t2"] < -0.005, -6.0, 0.0))

    def eval_34(sc_vec, thr=90.0):
        sub = c34[sc_vec >= thr].copy()
        sub["sc_use"] = sc_vec[sc_vec >= thr]
        sub["priority_score"] = sub["sc_use"] * 10.0 + sub["prio_3to4"] * 0.1
        slot = sim_slot_generic(sub, ["buy_date", "buy_hhmm", "priority_score", "c6"], [True, True, False, True], strict_open_gt=True)
        return calc_d15_metrics(slot, sub, sh300, wins)

    return {
        "C0_V40_基准(30bps)": eval_34(sc_base, 90.0),
        "C1_消融_剥离全部现行LHB因子": eval_34(sc_no_lhb, 90.0),
        "C2_修正T12误杀西安西+补宜昌沿江": eval_34(sc_fixed, 90.0),
        "C3_V40+IS精选游资(+4/-6)": eval_34(sc_fine, 90.0),
        "C4_V40+贝叶斯滚动口碑(+4/-6)": eval_34(sc_bayes, 90.0),
    }


def run_high_dragon_sandbox(cache, feat, sh300, wins):
    v5 = cache["v5_119"].copy()
    v5["c6"] = v5["code"].astype(str).str.zfill(6)
    part1_cache = pickle.load(open(f"{HIGH_DIR}/part1_cache.pkl", "rb"))
    bars_5m_sub2 = pickle.load(open(f"{HIGH_DIR}/sub2_5m_bars_cache.pkl", "rb"))
    df_5m_pit = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
    df_5m_pit.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_pit_map = {(c6, d): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float) for (c6, d), g in df_5m_pit.groupby(["c6", "date"], sort=False)}
    idx_cache = json.load(open(IDX_JSON))
    (_, _, _, code_bars, _, _, _, _, _, _, _, _, _, _, SH_MAP, SZ_MAP) = part1_cache
    idx_5m_sub2 = {(k[0], k[2]): v for k, v in bars_5m_sub2.items()}

    def get_bars_5m(c6, dt):
        arr = bars_5m_pit_map.get((c6, dt))
        if arr is not None and len(arr) > 0:
            return arr
        v = idx_5m_sub2.get((c6, dt))
        if isinstance(v, pd.DataFrame) and not v.empty:
            sub = v[v["date"] == dt]
            if not sub.empty:
                hh = sub["hhmm"].str.replace(":", "").astype(int).values
                return np.column_stack([hh, sub["open"].values, sub["high"].values, sub["low"].values, sub["close"].values, sub["volume"].values, sub["amount"].values])
        return None

    def get_double_dev_px(bars, cp, imap, disc=0.07):
        cd = bars["dts"][cp]; ir = imap.get(cd)
        if not ir: return 99999.0
        bp = 99999.0
        for k in range(1, min(11, cp + 1)):
            p = cp - k; bi = imap.get(bars["dts"][p]); bc = bars["close"][p]
            if bi and bc > 0: bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
        for k in range(1, min(31, cp + 1)):
            p = cp - k; bi = imap.get(bars["dts"][p]); bc = bars["close"][p]
            if bi and bc > 0: bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
        return bp

    # Simulate all 119 candidates using exact S_hold_d3 + build_partA 5m exit refinement at 30bps
    sim_rows = []
    for r in v5.itertuples():
        c6 = r.c6
        bars = code_bars[c6]
        d2p = bars["p"][r.buy_date]
        b_op = float(bars["open"][d2p]); zt_px = float(bars["zt_px"][d2p])
        imap = SH_MAP if r.ex == "SH" else SZ_MAP
        arr_b = get_bars_5m(c6, r.buy_date)
        if r.op2 >= 0.0:
            if r.op2 > 0.045 or b_op >= zt_px - 0.011:
                sim_rows.append(None); continue
            b_px, b_hhmm, is_auc = b_op, 925, True
        else:
            ipx = round(b_op * 1.015, 2)
            if ipx >= zt_px - 0.011 or arr_b is None:
                sim_rows.append(None); continue
            hit_b = False
            for row in arr_b:
                if int(row[0]) > 1130: break
                if row[2] >= ipx:
                    b_hhmm = int(row[0]); b_px = float(max(row[1], ipx)); hit_b = True; break
            if not hit_b:
                sim_rows.append(None); continue
            is_auc = False

        n = len(bars["dts"])
        def run_zt_loop(start_p):
            imm = False
            for step in range(1, 8):
                p = start_p + step
                if p >= n: break
                pl = get_double_dev_px(bars, p, imap, 0.07)
                if bars["open"][p] >= pl: return p, float(bars["open"][p]), True, 925
                if bars["high"][p] >= pl: return p, float(pl), False, 1030
                if not bars["is_zt"][p]:
                    if (not imm) and (bars["close"][p] > bars["open"][p]):
                        imm = True; continue
                    while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
                    return p, float(bars["close"][p]), False, 1500
            pe = min(start_p + 5, n - 1)
            return pe, float(bars["close"][pe]), False, 1500

        if bars["is_zt"][d2p]:
            ep, epx, eo, ehh = run_zt_loop(d2p)
        else:
            p = min(d2p + 1, n - 1)
            while p < n - 1 and bars["is_yizi_dt"][p]: p += 1
            if bars["is_zt"][p]:
                ep, epx, eo, ehh = run_zt_loop(p)
            else:
                pl = get_double_dev_px(bars, p, imap, 0.07)
                if bars["open"][p] >= pl:
                    ep, epx, eo, ehh = p, float(bars["open"][p]), True, 925
                elif bars["high"][p] >= pl:
                    ep, epx, eo, ehh = p, float(pl), False, 1030
                else:
                    ep, epx, eo, ehh = p, float(bars["close"][p]), False, 1500

        if not eo and ehh == 1030:
            arr_e = get_bars_5m(c6, bars["dts"][ep])
            pl = get_double_dev_px(bars, ep, imap, 0.07)
            if arr_e is not None:
                for row in arr_e:
                    if row[2] >= pl:
                        ehh = int(row[0]); epx = float(max(row[1], pl)); break

        nr = (epx * bars["adjf"][ep]) / (b_px * bars["adjf"][d2p]) * (1.0 - FEE_30BPS) - 1.0
        sim_rows.append({
            "code": c6, "name": r.name, "buy_date": r.buy_date, "buy_hhmm": b_hhmm,
            "exit_date": bars["dts"][ep], "exit_hhmm": ehh, "net_ret": float(nr), "b_open_h": is_auc, "eo": eo,
        })

    v5["sim"] = sim_rows
    v5_ok = v5[v5["sim"].notna()].copy().reset_index(drop=True)
    s_df = pd.DataFrame(v5_ok["sim"].tolist())
    for c in ["buy_hhmm", "exit_date", "exit_hhmm", "net_ret", "b_open_h", "eo"]:
        v5_ok[c] = s_df[c]

    f_d1 = [feat.get((d, c, 0), {"has_lhb": 0, "lh_cnt": 0, "lh_net_pos": 0, "lh_pure_bad": 0, "has_is_good": 0, "has_is_bad": 0, "has_surf_fixed": 0, "bayes_t2": 0.0})
            for d, c in zip(v5_ok["d1"], v5_ok["c6"])]
    f_d0 = [feat.get((d, c, 0), {"has_lhb": 0, "has_is_good": 0, "has_is_bad": 0, "has_surf_fixed": 0})
            for d, c in zip(v5_ok["d0"], v5_ok["c6"])]
    for k in ["has_is_good", "has_is_bad", "lh_net_pos", "bayes_t2"]:
        v5_ok[k] = [x[k] for x in f_d1]
    v5_ok["d0_bad"] = [x["has_is_bad"] for x in f_d0]

    # Existing LHB points in V5.1 sc4:
    # lh1 (6 if 0 else -10 if 2, note lh1>=3 hard vetoed), in1 (-6 if >=1), qu1 (+4 if qu1>=1 and lh1<=1),
    # lhb_d0_top_locked (+5), lhb_d1_lhasa_heavy (-10), lhb_d1_net_positive (-5), lhb_d0_day_surf_buy (-6)
    old_lhb_pts = (
        np.where(v5_ok["lh1"] == 0, 6.0, np.where(v5_ok["lh1"] == 2, -10.0, 0.0))
        + np.where(v5_ok["in1"] >= 1, -6.0, 0.0)
        + np.where((v5_ok["qu1"] >= 1) & (v5_ok["lh1"] <= 1), 4.0, 0.0)
        + np.where(v5_ok["lhb_d0_top_locked"], 5.0, 0.0)
        + np.where(v5_ok["lhb_d1_lhasa_heavy"], -10.0, 0.0)
        + np.where(v5_ok["lhb_d1_net_positive"], -5.0, 0.0)
        + np.where(v5_ok["lhb_d0_day_surf_buy"], -6.0, 0.0)
    )
    sc_base = v5_ok["sc4"].to_numpy(dtype=float)
    sc_no_lhb = sc_base - old_lhb_pts
    # Restore lh1>=3? No, keep hard gate from sc4 >= 0 check
    sc_no_lhb = np.where(sc_base < 0, -999.0, sc_no_lhb)
    sc_plus_is = np.where(sc_base < 0, -999.0, sc_base + np.where(v5_ok["has_is_good"] == 1, 4.0, 0.0) - np.where(v5_ok["has_is_bad"] == 1, 6.0, 0.0))
    sc_plus_bayes = np.where(sc_base < 0, -999.0, sc_base + np.where(v5_ok["bayes_t2"] > 0.005, 4.0, np.where(v5_ok["bayes_t2"] < -0.005, -6.0, 0.0)))

    def eval_high(sc_vec, thr=88.0, use_cb=False):
        sub = v5_ok[sc_vec >= thr].copy()
        sub["score"] = sc_vec[sc_vec >= thr]
        srt = sub.sort_values(["buy_date", "score"], ascending=[True, False])
        taken, fd, peo, cl, sk = [], "", False, 0, False
        for r in srt.itertuples(index=False):
            if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
                if use_cb and sk:
                    fd, peo = r.exit_date, r.eo
                    if r.net_ret > 0: sk, cl = False, 0
                    continue
                taken.append(r._asdict())
                fd, peo = r.exit_date, r.eo
                if r.net_ret < -0.02:
                    cl += 1
                    if cl >= 2: sk = True
                elif r.net_ret > 0:
                    cl = 0
        slot = pd.DataFrame(taken)
        return calc_d15_metrics(slot, sub, sh300, wins)

    return {
        "D0_V51_基准_NoCB(30bps)": eval_high(sc_base, 88.0, False),
        "D0b_V51_基准_CB(30bps)": eval_high(sc_base, 88.0, True),
        "D1_消融_剥离全部现行LHB因子_NoCB": eval_high(sc_no_lhb, 88.0, False),
        "D2_V51+IS精选正负席位(+4/-6)_NoCB": eval_high(sc_plus_is, 88.0, False),
        "D3_V51+贝叶斯滚动口碑(+4/-6)_NoCB": eval_high(sc_plus_bayes, 88.0, False),
    }


def verify_bayes_physical_truncation(cutoff: str = "2024-12-31"):
    """Verify rolling 250d Bayesian scores for dates <= 2024-12-31 are 100% identical after deleting >= 2025-01-01."""
    zt_all = pd.read_parquet(f"{SANDBOX}/zt_market_5y.parquet")
    lhb = pd.read_parquet(f"{SANDBOX}/clean_lhb_5y.parquet")
    b_full = pd.read_parquet(f"{SANDBOX}/bayes_seat_scores_d1_5y.parquet")

    # Recompute rolling 250d strictly from <= cutoff data
    zt10 = zt_all[(~zt_all["is_20cm"]) & (~zt_all["is_st_pit"]) & zt_all["is_zt"] & (zt_all["date"] <= cutoff)].copy()
    # Note: d1_t2_tradable_net for date <= cutoff where T+2 > cutoff must be masked as NaN!
    # In fact, for physical truncation, any date whose d1_date > cutoff or T+2 > cutoff wasn't settled by cutoff!
    all_tdts = sorted(zt_all[zt_all["date"] <= cutoff]["date"].unique().tolist())
    lhb_d1_all = lhb[(lhb["is_three"] == 0) & (lhb["date"] <= cutoff)].copy()
    lhb_d1 = lhb_d1_all[(lhb_d1_all["NET"] > 0) & (lhb_d1_all["dept_code"] != "0")].copy()

    zt10 = zt10.rename(columns={"c6": "stock_code"})
    base = zt10.merge(lhb_d1_all[["date", "stock_code"]].drop_duplicates(), on=["date", "stock_code"], how="inner")
    dept_ev = lhb_d1.drop_duplicates(["date", "stock_code", "dept_code"]).merge(
        base[["date", "stock_code", "d1_t2_tradable_net"]], on=["date", "stock_code"], how="inner"
    )
    day_dept = defaultdict(list)
    for r in dept_ev.itertuples(index=False):
        if pd.notna(r.d1_t2_tradable_net):
            day_dept[r.date].append((r.dept_code, float(r.d1_t2_tradable_net)))
    day_base = defaultdict(list)
    for r in base.itertuples(index=False):
        if pd.notna(r.d1_t2_tradable_net):
            day_base[r.date].append(float(r.d1_t2_tradable_net))

    d_sum, d_cnt = defaultdict(float), defaultdict(int)
    b_sum, b_cnt = 0.0, 0
    qa, qr = 0, 0
    trunc_map = {}
    for ci, dt in enumerate(all_tdts):
        while qa <= ci - 2:
            da = all_tdts[qa]
            for dc, v in day_dept.get(da, []):
                d_sum[dc] += v; d_cnt[dc] += 1
            for v in day_base.get(da, []):
                b_sum += v; b_cnt += 1
            qa += 1
        while qr < max(0, ci - 252):
            dr = all_tdts[qr]
            for dc, v in day_dept.get(dr, []):
                d_sum[dc] -= v; d_cnt[dc] -= 1
            for v in day_base.get(dr, []):
                b_sum -= v; b_cnt -= 1
            qr += 1
        mu0 = b_sum / b_cnt if b_cnt > 0 else 0.0
        for dc, cnt in d_cnt.items():
            if cnt >= 15:
                trunc_map[(dt, dc)] = (cnt / (cnt + 15.0)) * ((d_sum[dc] / cnt) - mu0)

    b_pre25 = b_full[b_full["date"] <= cutoff].copy()
    t_vals = [trunc_map.get((d, c), 0.0) for d, c in zip(b_pre25["date"], b_pre25["dept_code"])]
    max_diff = float(np.max(np.abs(b_pre25["b_t2"].to_numpy() - np.array(t_vals))))
    return {"cutoff": cutoff, "checked_rows": int(len(b_pre25)), "max_abs_diff": max_diff}


def main():
    t0 = time.time()
    cache = pickle.load(open(f"{SANDBOX}/strat_pools_cache.pkl", "rb"))
    lhb = pd.read_parquet(f"{SANDBOX}/clean_lhb_5y.parquet")
    ths = pd.read_parquet(f"{SANDBOX}/ths_pit_youzi_5y.parquet")
    bayes_df = pd.read_parquet(f"{SANDBOX}/bayes_seat_scores_d1_5y.parquet")
    sh300 = json.load(open(IDX_JSON))["sh000300"]

    feat = build_lhb_features(lhb, ths, bayes_df)

    wins_12_23 = [
        ("全五年", "2021-11-16", "2026-11-16"),
        ("近三年", "2023-11-16", "2026-11-16"),
        ("2026年内", "2026-01-01", "2026-11-16"),
        ("IS_21_23", "2021-11-16", "2023-12-31"),
        ("OOS_24_26", "2024-01-01", "2026-11-16"),
    ]
    wins_34_high = [
        ("全五年", "2021-11-16", "2026-11-16"),
        ("近三年", "2023-11-16", "2026-11-16"),
        ("2026年内", "2026-01-01", "2026-11-16"),
        ("IS_22_23", "2022-01-04", "2023-12-31"),
        ("OOS_24_26", "2024-01-01", "2026-11-16"),
    ]

    r12 = run_1to2_sandbox(cache, feat, sh300, wins_12_23)
    r23 = run_2to3_sandbox(cache, feat, sh300, wins_12_23)
    r34 = run_3to4_sandbox(cache, feat, sh300, wins_34_high)
    rh = run_high_dragon_sandbox(cache, feat, sh300, wins_34_high)
    trunc_audit = verify_bayes_physical_truncation("2024-12-31")

    # Coverage stats from cache
    fb_c = cache["fb_cand"]
    fb_m19 = fb_c[fb_c["mask_v19"]]
    g23 = cache["g23_5y"]
    g23_90 = g23[g23["score_v2"] >= 90]
    c34 = cache["c34_sk"]
    c34_90 = c34[c34["sc_v40"] >= 90]
    v5 = cache["v5_119"]
    v5_88 = v5[v5["sc4"] >= 88]

    coverage_audit = {
        "一进二_V19": {
            "全候选数": cache["fb_all5y_cov"]["N"],
            "全候选D1单日榜覆盖%": cache["fb_all5y_cov"]["d1_single_cov_pct"],
            "全候选D1含三日榜覆盖%": cache["fb_all5y_cov"]["d1_any_cov_pct"],
            "达标触发池N": int(len(fb_m19)),
            "达标池D1单日榜覆盖%": round(float(fb_m19["has_d1_single"].mean() * 100.0), 2),
            "达标池D1含三日榜覆盖%": round(float(fb_m19["has_d1_any"].mean() * 100.0), 2),
        },
        "二进三_V20": {
            "全门限池N": int(len(g23)),
            "全门限D2单日榜%": round(float(g23["has_d2_s"].mean() * 100.0), 2),
            "全门限D2含三日榜%": round(float(g23["has_d2_any"].mean() * 100.0), 2),
            "全门限D1或D2任一%": round(float(g23["has_d1_or_d2_any"].mean() * 100.0), 2),
            "达标>=90池N": int(len(g23_90)),
            "达标池D2单日榜%": round(float(g23_90["has_d2_s"].mean() * 100.0), 2),
            "达标池D2含三日榜%": round(float(g23_90["has_d2_any"].mean() * 100.0), 2),
            "达标池D1或D2任一%": round(float(g23_90["has_d1_or_d2_any"].mean() * 100.0), 2),
        },
        "三进四_V40": {
            "骨架池N": int(len(c34)),
            "骨架D3单日榜%": round(float(c34["has_d3_s"].mean() * 100.0), 2),
            "骨架D3含三日榜%": round(float(c34["has_d3_any"].mean() * 100.0), 2),
            "骨架D1~D3任一%": round(float(c34["has_d123_any"].mean() * 100.0), 2),
            "达标>=90池N": int(len(c34_90)),
            "达标池D3单日榜%": round(float(c34_90["has_d3_s"].mean() * 100.0), 2),
            "达标池D3含三日榜%": round(float(c34_90["has_d3_any"].mean() * 100.0), 2),
            "达标池D1~D3任一%": round(float(c34_90["has_d123_any"].mean() * 100.0), 2),
        },
        "高标首阴_V51": {
            "全候选池N": int(len(v5)),
            "全池D1单日榜%": round(float(v5["has_d1_s"].mean() * 100.0), 2),
            "全池D1含三日榜%": round(float(v5["has_d1_any"].mean() * 100.0), 2),
            "全池D0或D1任一%": round(float(v5["has_d0_or_d1"].mean() * 100.0), 2),
            "达标>=88池N": int(len(v5_88)),
            "达标池D1单日榜%": round(float(v5_88["has_d1_s"].mean() * 100.0), 2),
            "达标池D0或D1任一%": round(float(v5_88["has_d0_or_d1"].mean() * 100.0), 2),
        },
    }

    out = {
        "meta": {"fee_roundtrip": "30 bps (0.30%)", "truncation_audit": trunc_audit, "elapsed_sec": round(time.time() - t0, 1)},
        "coverage_audit": coverage_audit,
        "1to2_V19": r12,
        "2to3_V20": r23,
        "3to4_V40": r34,
        "HighDragon_V51": rh,
    }
    with open(f"{SANDBOX}/sandbox_4strategies_seat_backtest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Saved sandbox_4strategies_seat_backtest.json in {time.time()-t0:.1f}s | trunc_max_diff={trunc_audit['max_abs_diff']}")


if __name__ == "__main__":
    main()

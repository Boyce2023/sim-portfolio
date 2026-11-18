#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Step 3a: Baseline 20bps vs 30bps reproduction + STRICT IS-only (<= 2023-12-31) LHB factor diagnostics."""

import importlib.util
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
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
HIGH_DIR = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"

# Strict IS-calibrated seat sets (selected ONLY from 2021-2023 data in Module 2!)
# IS positive seats (ex_t2_IS >= +1.0pp and nuke_IS < 18%):
IS_GOOD_CODES = {
    "10430845",  # 上海超短/新闸路 (+2.20pp, nuke 2.5%)
    "10102873",  # 章盟主建国中路 (+2.03pp, nuke 1.9%)
    "10046704",  # 章盟主杭州延安路
    "10023415",  # 章盟主宁波广福街
    "10026767",  # 华鑫上海东大名路 (+3.16pp, nuke 11.1%)
    "10142874",  # 徐留胜荣超 (+1.20pp)
    "10122927",  # 招商深南东 (+1.55pp, nuke 8.7%)
    "10045035",  # 呼家楼 (+2.10pp, nuke 11.1%)
    "10025390",  # 国泰北京知春路 (+4.23pp)
    "10147201",  # 交易猿/二纬路 (+3.74pp)
    "10318896",  # 福州六一中路
    "10434470", "10634757",  # 沪深股通 (+0.80pp, nuke 9.9%)
    "10000100571", "10000399618", "10110478",  # 摩根/高盛/瑞银
}
IS_GOOD_ICONS = {"涪陵广场路", "北京帮", "上海超短", "招商深南东", "徐留胜", "交易猿", "古北路", "小鳄鱼"}

# IS toxic seats (ex_t2_IS <= -0.5pp or high nuke):
IS_BAD_CODES = {
    "10063083",  # 上塘路
    "10000147202",  # 宁波和源路/余哥 (-3.59pp)
    "10050414",  # 成泉系建国门外 (-0.94pp)
    "10115140",  # 北京中关村 (-0.46pp, nuke 26.3%)
    "10023543",  # 赵老哥绍兴 (-0.89pp)
    "10046458",  # 新生代海宁路 (-1.20pp)
    "10046604",  # N周二凤起路 (-0.98pp)
    "10485003",  # 玉兰路 (-3.43pp)
    "10028577",  # 苏州帮 (-0.97pp)
    "10547746",  # 上证苏南分 (-3.22pp, nuke 40.3%)
    "10456237",  # 财通九和路 (-3.08pp)
    "10027014",  # 兴业金陵东路 (-2.77pp)
    "10143030",  # 东吴西藏南路 (-2.69pp)
    "10477736", "10023559",  # 苏南帮
    "10026729",  # 消闲派宜昌珍珠/沿江
}
IS_BAD_ICONS = {"上塘路", "宁波和源路", "成泉系", "北京中关村", "赵老哥", "新生代", "N周二", "金田路", "玉兰路", "苏州帮", "苏南帮", "湖州劳动路"}
XIAN_XIDAJIE = "10046745"


def to_30bps(r_20bps: float) -> float:
    return (1.0 + float(r_20bps)) / 0.9980 * 0.9970 - 1.0


def load_mod(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_lhb_feature_lookup(lhb: pd.DataFrame, ths: pd.DataFrame, bayes_df: pd.DataFrame):
    """Build exact per-(date, stock_code, is_three) & combined LHB features for strategy lookup."""
    dept_names = lhb[lhb["dept_code"] != "0"][["dept_code", "dept_name"]].drop_duplicates()
    lhasa_codes = set(dept_names[dept_names["dept_name"].str.contains("拉萨|昌都|山南", na=False) & (~dept_names["dept_name"].str.contains("东亚", na=False))]["dept_code"])
    lhasa_pure = set(dept_names[dept_names["dept_name"].str.contains("拉萨", na=False) & (~dept_names["dept_name"].str.contains("东亚", na=False))]["dept_code"])

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
            float(r.cap_inflow) if pd.notna(r.cap_inflow) else 0.0,
            float(r.org_inflow) if pd.notna(r.org_inflow) else 0.0,
        )

    feat = {}  # (date, stock_code, is_three) -> dict
    for (dt, sc, is3), grp in lhb.groupby(["date", "stock_code", "is_three"], sort=False):
        b_rows = grp[grp["side"] == "B"]
        s_rows = grp[grp["side"] == "S"]
        tot_b = float(b_rows["BUY"].sum())
        tot_s = float(s_rows["SELL"].sum())
        b_pos = b_rows[b_rows["NET"] > 0]
        b_codes = set(b_pos["dept_code"])
        all_b_codes = set(b_rows["dept_code"])
        s_neg_codes = set(s_rows[s_rows["NET"] < -1e6]["dept_code"])

        lh_all_cnt = len(all_b_codes & lhasa_pure)
        lh_buy_amt = float(b_rows[b_rows["dept_code"].isin(lhasa_pure)]["BUY"].sum())
        lh_buy_share = (lh_buy_amt / tot_b) if tot_b > 0 else 0.0
        lh_net_amt = float(b_rows[b_rows["dept_code"].isin(lhasa_pure)]["NET"].sum())

        t_info = ths_map.get((dt, sc, int(is3)), (set(), 0.0, 0.0))
        icons = t_info[0]
        has_is_good = bool((b_codes & IS_GOOD_CODES) or (icons & IS_GOOD_ICONS))
        has_is_bad = bool((b_codes & IS_BAD_CODES) or (icons & IS_BAD_ICONS))
        has_xian = XIAN_XIDAJIE in b_codes
        n_org_b = int((b_rows["dept_code"] == "0").sum())
        org_net = t_info[2]

        bc, bt2 = b_map.get((dt, sc), (0.0, 0.0)) if is3 == 0 else (0.0, 0.0)
        feat[(dt, sc, int(is3))] = {
            "has_lhb": 1,
            "tot_b": tot_b,
            "net_tot": tot_b - tot_s,
            "lh_cnt": lh_all_cnt,
            "lh_share": lh_buy_share,
            "lh_net_pos": lh_net_amt > 0,
            "has_is_good": int(has_is_good),
            "has_is_bad": int(has_is_bad),
            "has_xian": int(has_xian),
            "pure_org": int((n_org_b >= 2) and (org_net > 1e7) and (lh_all_cnt == 0)),
            "bayes_c": bc,
            "bayes_t2": bt2,
        }
    return feat


def sim_high_v51_exact(v5_df: pd.DataFrame, part1_cache, bars_5m_pit_map, bars_5m_sub2, idx_cache, sc_col="sc4", th=88, fee=0.0030):
    """Exact replica of build_partA_rebacktest.py + master_v5_kpl_hand_exec.py 5m execution on 119 candidates."""
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

    rows = []
    for r in v5_df[v5_df[sc_col] >= th].itertuples():
        c6 = str(r.code).zfill(6)
        bars = code_bars[c6]
        d2p = bars["p"][r.buy_date]
        b_op = float(bars["open"][d2p]); zt_px = float(bars["zt_px"][d2p])
        imap = SH_MAP if r.ex == "SH" else SZ_MAP
        arr_b = get_bars_5m(c6, r.buy_date)
        if r.op2 >= 0.0:
            if r.op2 > 0.045 or b_op >= zt_px - 0.011: continue
            b_px, b_hhmm, is_auc = b_op, 925, True
        else:
            ipx = round(b_op * 1.015, 2)
            if ipx >= zt_px - 0.011: continue
            if arr_b is None: continue
            hit_b = False
            for row in arr_b:
                if int(row[0]) > 1130: break
                if row[2] >= ipx:
                    b_hhmm = int(row[0])
                    b_px = float(max(row[1], ipx))
                    hit_b = True
                    break
            if not hit_b: continue
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
            d2_c = float(bars["close"][d2p]); d2_ret = d2_c / b_px - 1.0
            d3_op_pct = float(bars["open"][p]) / float(bars["pre_c"][p]) - 1.0
            if d2_ret <= -0.02 or (d2_c < b_op and d2_ret < 0) or d3_op_pct <= -0.035:
                ep, epx, eo, ehh = p, float(bars["open"][p]), True, 925
            elif bars["is_zt"][p]:
                ep, epx, eo, ehh = run_zt_loop(p)
            else:
                ep, epx, eo, ehh = p, float(bars["close"][p]), False, 1500

        if not eo and ehh == 1030:
            arr_e = get_bars_5m(c6, bars["dts"][ep])
            pl = get_double_dev_px(bars, ep, imap, 0.07)
            if arr_e is not None:
                for row in arr_e:
                    if row[2] >= pl:
                        ehh = int(row[0]); epx = float(max(row[1], pl)); break

        nr = (epx * bars["adjf"][ep]) / (b_px * bars["adjf"][d2p]) * (1.0 - fee) - 1.0
        rows.append({
            "code": c6, "name": r.name, "buy_date": r.buy_date, "buy_hhmm": b_hhmm,
            "buy_price": round(b_px, 2), "exit_date": bars["dts"][ep], "exit_hhmm": ehh,
            "exit_price": round(epx, 2), "net_ret": float(nr), "score": float(getattr(r, sc_col)), "b_open_h": is_auc, "eo": eo,
        })
    if not rows:
        return pd.DataFrame(), pd.DataFrame()
    raw = pd.DataFrame(rows).sort_values(["buy_date", "score"], ascending=[True, False])
    taken, fd, peo = [], "", False
    for r in raw.itertuples(index=False):
        if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not r.b_open_h)):
            taken.append(r._asdict())
            fd, peo = r.exit_date, r.eo
    return raw, pd.DataFrame(taken)


def main():
    t0 = time.time()
    cache = pickle.load(open(f"{SANDBOX}/strat_pools_cache.pkl", "rb"))
    lhb = pd.read_parquet(f"{SANDBOX}/clean_lhb_5y.parquet")
    ths = pd.read_parquet(f"{SANDBOX}/ths_pit_youzi_5y.parquet")
    bayes_df = pd.read_parquet(f"{SANDBOX}/bayes_seat_scores_d1_5y.parquet")
    feat = build_lhb_feature_lookup(lhb, ths, bayes_df)

    # Verify V5.1 42 trades exact reproduction
    part1_cache = pickle.load(open(f"{HIGH_DIR}/part1_cache.pkl", "rb"))
    bars_5m_sub2 = pickle.load(open(f"{HIGH_DIR}/sub2_5m_bars_cache.pkl", "rb"))
    df_5m_pit = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
    df_5m_pit.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_pit_map = {(c6, d): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float) for (c6, d), g in df_5m_pit.groupby(["c6", "date"], sort=False)}
    idx_cache = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))

    v5_119 = cache["v5_119"].copy()
    _, led_v5_20 = sim_high_v51_exact(v5_119, part1_cache, bars_5m_pit_map, bars_5m_sub2, idx_cache, "sc4", 88, 0.0020)
    ref_v5 = pd.read_csv(f"{SIM}/backtests_astock/clean_rebacktest_20261116/partA_high_3to4/ledger_base_high_v51.csv", dtype={"code": str})
    ref_v5["code"] = ref_v5["code"].str.zfill(6)
    # Compare overlap on the 42 canonical trades
    m_ov = led_v5_20.merge(ref_v5[["buy_date", "code", "net_ret"]], on=["buy_date", "code"], suffixes=("", "_ref"))
    max_d = np.max(np.abs(m_ov["net_ret"].to_numpy() - m_ov["net_ret_ref"].to_numpy())) if not m_ov.empty else 0.0
    print(f"[High V5.1 Reproduction] full_5m_n={len(led_v5_20)}, overlap_with_ref42={len(m_ov)}/42, max_ret_diff={max_d:.6f}")

    # Strict IS (<= 2023-12-31) diagnostics on all 4 strategy pools!
    def check_is_split(df_sub, ret_col, name):
        is_df = df_sub[df_sub["buy_date"] <= "2023-12-31"].copy()
        print(f"\n=== IS DIAGNOSTIC (<=2023-12-31) [{name}] N_IS={len(is_df)} ===")
        for col in ["has_lhb", "has_is_good", "has_is_bad", "has_xian", "lh_ge1", "lh_net_pos", "pure_org", "bayes_pos", "bayes_neg"]:
            if col not in is_df.columns:
                continue
            g1 = is_df[is_df[col] == 1][ret_col]
            g0 = is_df[is_df[col] == 0][ret_col]
            if len(g1) >= 3 and len(g0) >= 3:
                print(f"  {col:<12}: Y(N={len(g1):>3}, mean={g1.mean()*100:+.2f}%, wr={(g1>0).mean()*100:4.1f}%) vs N(N={len(g0):>4}, mean={g0.mean()*100:+.2f}%, wr={(g0>0).mean()*100:4.1f}%)")

    # Attach LHB features to each pool
    def get_f(dt, c6, is3=0):
        return feat.get((dt, c6, is3), {"has_lhb": 0, "lh_cnt": 0, "lh_share": 0.0, "lh_net_pos": False, "has_is_good": 0, "has_is_bad": 0, "has_xian": 0, "pure_org": 0, "bayes_c": 0.0, "bayes_t2": 0.0})

    # 1. 1to2 (check V19 triggered pool + near-threshold sc>=285)
    fb = cache["fb_cand"].copy()
    fb_ok = fb[fb["sim_tr"].notna()].copy()
    fb_ok["buy_date"] = fb_ok["d2_dt"]
    fb_ok["ret_30"] = [to_30bps(x["net_ret"]) for x in fb_ok["sim_tr"]]
    f12 = [get_f(d, c, 0) for d, c in zip(fb_ok["dt_str"], fb_ok["c6"])]
    for k in ["has_lhb", "has_is_good", "has_is_bad", "has_xian", "pure_org", "bayes_t2"]:
        fb_ok[k] = [x[k] for x in f12]
    fb_ok["lh_ge1"] = [x["lh_cnt"] >= 1 for x in f12]
    fb_ok["lh_net_pos"] = [int(x["lh_net_pos"]) for x in f12]
    fb_ok["bayes_pos"] = (fb_ok["bayes_t2"] > 0.003).astype(int)
    fb_ok["bayes_neg"] = (fb_ok["bayes_t2"] < -0.003).astype(int)
    check_is_split(fb_ok[fb_ok["mask_v19"]], "ret_30", "1to2_V19_pass")
    check_is_split(fb_ok[fb_ok["score_active"] >= 285.0], "ret_30", "1to2_near285")

    # 2. 2to3 (check gated>=80 and >=90, checking BOTH D2 single-day & D2 any/3-day)
    g23 = cache["g23_5y"].copy()
    g23["ret_30"] = g23["ret_v2"].apply(to_30bps)
    # Check D2 single-day (is3=0) and fallback to D2 3-day (is3=1)
    f23_s = [get_f(d, c, 0) for d, c in zip(g23["sig_date"], g23["c6"])]
    f23_3 = [get_f(d, c, 1) for d, c in zip(g23["sig_date"], g23["c6"])]
    f23 = [a if a["has_lhb"] else b for a, b in zip(f23_s, f23_3)]
    for k in ["has_lhb", "has_is_good", "has_is_bad", "has_xian", "pure_org", "bayes_t2"]:
        g23[k] = [x[k] for x in f23]
    g23["lh_ge1"] = [x["lh_cnt"] >= 1 for x in f23]
    g23["lh_net_pos"] = [int(x["lh_net_pos"]) for x in f23]
    g23["bayes_pos"] = (g23["bayes_t2"] > 0.003).astype(int)
    g23["bayes_neg"] = (g23["bayes_t2"] < -0.003).astype(int)
    check_is_split(g23[g23["score_v2"] >= 82], "ret_30", "2to3_sc>=82")
    check_is_split(g23[g23["score_v2"] >= 90], "ret_30", "2to3_V20>=90")

    # 3. 3to4 (check skel & >=90, checking D3 single-day & 3-day)
    c34 = cache["c34_sk"][cache["c34_sk"]["p_1030"].notna()].copy()
    c34["ret_30"] = [to_30bps(x["net_ret"]) for x in c34["p_1030"]]
    f34_s = [get_f(d, c, 0) for d, c in zip(c34["sig_date"], c34["c6"])]
    f34_3 = [get_f(d, c, 1) for d, c in zip(c34["sig_date"], c34["c6"])]
    f34 = [a if a["has_lhb"] else b for a, b in zip(f34_s, f34_3)]
    for k in ["has_lhb", "has_is_good", "has_is_bad", "has_xian", "pure_org", "bayes_t2"]:
        c34[k] = [x[k] for x in f34]
    c34["lh_ge1"] = [x["lh_cnt"] >= 1 for x in f34]
    c34["lh_net_pos"] = [int(x["lh_net_pos"]) for x in f34]
    c34["bayes_pos"] = (c34["bayes_t2"] > 0.003).astype(int)
    c34["bayes_neg"] = (c34["bayes_t2"] < -0.003).astype(int)
    check_is_split(c34[c34["sc_v40"] >= 80], "ret_30", "3to4_sc>=80")
    check_is_split(c34[c34["sc_v40"] >= 90], "ret_30", "3to4_V40>=90")

    # 4. High Dragon (check all 119 simulated with sc4 >= 0)
    raw_h, _ = sim_high_v51_exact(v5_119, part1_cache, bars_5m_pit_map, bars_5m_sub2, idx_cache, "sc4", -999, 0.0030)
    v5_sim = v5_119.merge(raw_h[["buy_date", "code", "net_ret"]], on=["buy_date", "code"], how="inner")
    f_h1 = [get_f(d, c, 0) for d, c in zip(v5_sim["d1"], v5_sim["c6"])]
    f_h0 = [get_f(d, c, 0) for d, c in zip(v5_sim["d0"], v5_sim["c6"])]
    for k in ["has_lhb", "has_is_good", "has_is_bad", "has_xian", "pure_org", "bayes_t2"]:
        v5_sim[k] = [x[k] for x in f_h1]
    v5_sim["lh_ge1"] = [x["lh_cnt"] >= 1 for x in f_h1]
    v5_sim["lh_net_pos"] = [int(x["lh_net_pos"]) for x in f_h1]
    v5_sim["bayes_pos"] = (v5_sim["bayes_t2"] > 0.003).astype(int)
    v5_sim["bayes_neg"] = (v5_sim["bayes_t2"] < -0.003).astype(int)
    v5_sim["d0_good"] = [x["has_is_good"] for x in f_h0]
    check_is_split(v5_sim, "net_ret", "HighDragon_AllBuyable")
    check_is_split(v5_sim[v5_sim["sc4"] >= 88], "net_ret", "HighDragon_sc>=88")
    print(f"\nDone IS scan in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

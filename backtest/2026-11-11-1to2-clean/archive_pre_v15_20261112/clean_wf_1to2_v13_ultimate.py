import os
import sys
import re
import json
import time
from collections import defaultdict, Counter

import numpy as np
import pandas as pd

from v10_core_features import (
    load_full_5y_prices, build_5y_elo_and_candidates, split_terms, norm_term, NON_THEME, SIM_DIR,
    MA_PAT, TECH_PAT_ORIG, TECH_PAT_TIMELESS, EARN_PAT,
    HARD_NOTICE_PAT, HARD_NOTICE_ORIG_PAT, MA_NOTICE_PAT, EARN_NOTICE_PAT, BAD_NOTICE_PAT
)
from v10_pit_and_sim import CSI300_ANNUAL, CSI300_5Y_CUM, FEE_RATE, PIT_NOTICES_DB, attach_pit_notices_and_scores
from v10_backtest_eval import compute_d2_auction_scores, simulate_single_trade
from clean_wf_1to2_v10_elo_absorbed_master import eval_scheme_d15, summarize_trades

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean"
OUT_JSON = f"{OUT_DIR}/clean_wf_1to2_v13_ultimate_results.json"
OUT_CSV = f"{OUT_DIR}/clean_wf_1to2_v13_ultimate_ledger.csv"
KPL_MERGED_PATH = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"

NEG_NOTICE_PAT = re.compile(
    r"(不存在|不涉及|未筹划|未发现|无应披露|股票交易异常波动|异常波动公告|风险提示|占比极小|敬请广大投资者注意)"
)


def run_v13():
    t0 = time.time()
    print("[1/5] Loading prices...")
    df = load_full_5y_prices()

    print("[2/5] Building Elo & 8Y vocabulary preheating...")
    pioneer_word_history = defaultdict(set)
    term_seen_days = Counter()
    term_first_dt = {}

    if os.path.exists(KPL_MERGED_PATH):
        for ln in open(KPL_MERGED_PATH, encoding="utf-8"):
            if ln.strip():
                try:
                    d = json.loads(ln)
                    dt = d.get("date", "")
                    for p in d.get("plates", []):
                        pname = p.get("plate", "")
                        if pname not in NON_THEME:
                            for t in split_terms(pname):
                                term_seen_days[t] += 1
                                if t not in term_first_dt:
                                    term_first_dt[t] = dt
                        for s in p.get("stocks", []):
                            r_sh = str(s[2]).strip() if len(s) > 2 else ""
                            r_lg = str(s[3]).strip() if len(s) > 3 else ""
                            for t in split_terms(r_sh):
                                term_seen_days[t] += 1
                                if t not in term_first_dt:
                                    term_first_dt[t] = dt
                            txt = f"{pname} {r_sh} {r_lg}"
                            for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", txt):
                                w = norm_term(m.group(0))
                                if len(w) >= 3 and w not in NON_THEME:
                                    pioneer_word_history[w].add(dt)
                except Exception:
                    pass

    df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map = build_5y_elo_and_candidates(df)

    g = df.groupby("c6")
    df["d1_dip"] = (df["low"] - df["pre_c"]) / (df["pre_c"] + 1e-6)
    df["d1_entity"] = (df["close"] - df["open"]) / (df["pre_c"] + 1e-6)
    vol_ma5 = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["d1_vol_ratio"] = df["amount"] / (vol_ma5 + 1e-6)
    df["d1_seal_tightness"] = (
        (df["close"] == df["high"]).astype(int) * 30.0
        + np.clip(df["d1_dip"] * 100.0, -10.0, 10.0) * 1.5
        + np.clip(df["d1_entity"] * 100.0, 0.0, 10.0) * 2.0
        - np.where(df["d1_vol_ratio"] > 4.0, 15.0, 0.0)
    )
    tight_map = {
        (r.c6, r.dt_str): float(r.d1_seal_tightness)
        for r in df[["c6", "dt_str", "d1_seal_tightness"]].itertuples(index=False)
    }

    print("[3/5] Attaching PIT notices & auction scores...")
    fb_all = attach_pit_notices_and_scores(df, stock_theme_5y, zt_cnt_map, dt_cnt_map, seal_rate_map, promo_ma5_map)
    hist_fb = fb_all[fb_all["d2_dt"].notna() & (fb_all["d2_dt"] <= "2026-11-10")].copy()
    hist_fb = compute_d2_auction_scores(hist_fb)

    # 漏洞 3 修复：真可买全场竞价排头兵 buyable_mkt_open_rk
    buy_mkt_o = np.where(hist_fb["is_buyable_open"], hist_fb["d2_o_pct"], -9.99)
    hist_fb["_buy_mkt_o"] = buy_mkt_o
    hist_fb["buyable_mkt_open_rk"] = hist_fb.groupby("d2_dt")["_buy_mkt_o"].rank(ascending=False, method="min")
    mkt_p2_buy = hist_fb.groupby("d2_dt")["_buy_mkt_o"].transform(
        lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05
    )
    hist_fb["mkt_buy_open_lead"] = np.where(hist_fb["buyable_mkt_open_rk"] == 1, hist_fb["d2_o_pct"] - mkt_p2_buy, 0.0)

    all_dts = sorted(df["dt_str"].unique())
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    price_lookup = {
        (r.c6, r.dt_str): (r.open, r.high, r.low, r.close, r.zt_price, r.dt_price, r.is_zt, r.is_yizi_dt)
        for r in df[["c6", "dt_str", "open", "high", "low", "close", "zt_price", "dt_price", "is_zt", "is_yizi_dt"]].itertuples(index=False)
    }

    hist_fb["d1_seal_tightness"] = [
        tight_map.get((r.c6, r.dt_str), 20.0) for r in hist_fb.itertuples(index=False)
    ]

    is_pioneer_list = []
    for r in hist_fb.itertuples(index=False):
        dt = r.dt_str
        ti = stock_theme_5y.get((dt, r.c6), {})
        r_txt = str(ti.get("r_short", "")) + " " + str(ti.get("name", ""))
        hit = False
        for m in re.finditer(r"[\u4e00-\u9fa5A-Za-z0-9]{2,8}(?:技术|材料|产品|装备|芯片|器件|电池|系统|模块|平台|光模块|算法|模型|协议)", r_txt):
            w = norm_term(m.group(0))
            if w in pioneer_word_history:
                prior = [d_seen for d_seen in pioneer_word_history[w] if d_seen <= dt]
                if 1 <= len(prior) <= 3:
                    hit = True
                    break
        is_pioneer_list.append(hit)
    hist_fb["is_pioneer_word"] = is_pioneer_list

    # Alpha 2.1: 双主线杂交识别
    hist_fb["is_dual_theme"] = (hist_fb["s_elo"] >= 102.0) & (hist_fb["p_sz"] >= 5) & (hist_fb["r_short"] != hist_fb["plate"])

    hist_fb["d2_yr"] = hist_fb["d2_dt"].str[:4].astype(int)
    common_ok = hist_fb["is_buyable_open"] & (~hist_fb["nuclear_halt"]) & (~hist_fb["promo_freeze"])
    fb_2021 = hist_fb[(hist_fb["d2_yr"] == 2021) & common_ok]
    n_s1a_2021 = int((fb_2021["d2_o_pct"].between(0.030, 0.082) & (fb_2021["s_prior_orig"] >= 35.0) & (fb_2021["s_quant_orig"] >= 140.0) & (fb_2021["tot_orig"] >= fb_2021["tot_thr"])).sum())
    pool_2021_dual = fb_2021[fb_2021["d2_o_pct"].between(0.022, 0.078) & (fb_2021["s_prior_dual"] >= 45.0) & (fb_2021["s_quant_dual"] >= 150.0)]["tot_dual"].values
    target_2021_k = max(15, int(n_s1a_2021 * 0.65))
    s1b_base_thr = float(np.sort(pool_2021_dual)[-target_2021_k]) if len(pool_2021_dual) > target_2021_k else 280.0
    s1b_base_thr = round(s1b_base_thr, 1)
    s1b_thr_vec = np.where(hist_fb["mkt_seal_rate"] > 0.75, s1b_base_thr + 25.0, s1b_base_thr)

    # Track 1
    has_distinct_sub = (hist_fb["p_sz"] >= 10) & (hist_fb["s_elo"] >= 102.0) & (hist_fb["subbranch_rk"] == 1)
    m_s1b = (
        common_ok
        & hist_fb["d2_o_pct"].between(0.022, 0.078)
        & (hist_fb["s_prior_dual"] >= 45.0)
        & (hist_fb["s_quant_dual"] >= 145.0)
        & ((hist_fb["tot_dual"] >= s1b_thr_vec) | (has_distinct_sub & (hist_fb["buyable_plate_rk"] <= 2) & (hist_fb["tot_dual"] >= s1b_thr_vec - 15.0)))
    )
    hist_fb["track1_s1b"] = m_s1b

    # Track 2
    m_track2_pioneer = (
        common_ok
        & (hist_fb["p_sz"] <= 3)
        & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"])
        & hist_fb["d2_o_pct"].between(0.028, 0.076)
        & ((hist_fb["buyable_mkt_open_rk"] <= 6) | (hist_fb["buyable_plate_rk"] == 1))
        & (hist_fb["d1_seal_tightness"] >= 15.0)
        & ((hist_fb["f_dd20_d0"] <= 0.92) | (hist_fb["clean_brk60"] == 1))
    )
    hist_fb["track2_pioneer"] = m_track2_pioneer

    # Track 3
    m_track3_survivor = (
        common_ok
        & (hist_fb["mkt_seal_rate"] < 0.55)
        & (hist_fb["buyable_mkt_open_rk"] <= 2)
        & (hist_fb["mkt_buy_open_lead"] >= 0.015)
        & hist_fb["d2_o_pct"].between(0.035, 0.075)
        & (hist_fb["f_dd20_d0"] <= 0.88)
        & (hist_fb["d1_seal_tightness"] >= 15.0)
    )
    hist_fb["track3_survivor"] = m_track3_survivor

    # Track 4
    m_track4_hybrid = (
        common_ok
        & hist_fb["is_dual_theme"]
        & (hist_fb["buyable_plate_rk"] == 1)
        & hist_fb["d2_o_pct"].between(0.028, 0.076)
        & ((hist_fb["f_dd20_d0"] <= 0.90) | (hist_fb["clean_brk60"] == 1))
        & (hist_fb["d1_seal_tightness"] >= 12.0)
    )
    hist_fb["track4_hybrid"] = m_track4_hybrid

    hist_fb["v13_quad_track"] = m_s1b | m_track2_pioneer | m_track3_survivor | m_track4_hybrid
    hist_fb["v13_tot_score"] = (
        hist_fb["tot_dual"]
        + np.where(hist_fb["track2_pioneer"], 40.0, 0.0)
        + np.where(hist_fb["track3_survivor"], 35.0, 0.0)
        + np.where(hist_fb["track4_hybrid"], 30.0, 0.0)
    )

    print("[4/5] Running ablation and evaluation...")
    ablation_configs = [
        ("Track1_Only_B1", "tot_dual", m_s1b, "trig", "B1"),
        ("Track2_Only_B1", "v13_tot_score", m_track2_pioneer, "trig", "B1"),
        ("Track3_Only_B1", "v13_tot_score", m_track3_survivor, "trig", "B1"),
        ("Track4_Only_B1", "v13_tot_score", m_track4_hybrid, "trig", "B1"),
        ("QuadTrack_T1_T2_B1", "v13_tot_score", m_s1b | m_track2_pioneer, "trig", "B1"),
        ("QuadTrack_T1_T2_T3_B1", "v13_tot_score", m_s1b | m_track2_pioneer | m_track3_survivor, "trig", "B1"),
        ("QuadTrack_Full_V13_B1", "v13_tot_score", hist_fb["v13_quad_track"], "trig", "B1"),
        ("QuadTrack_Full_V13_E4", "v13_tot_score", hist_fb["v13_quad_track"], "trig", "E4"),
    ]

    results = {
        "meta": {
            "period": "2022-01-01 to 2026-11-10",
            "fee_rate": FEE_RATE,
            "s1b_base_thr": s1b_base_thr,
            "csi300_annual": CSI300_ANNUAL,
            "csi300_5y_cum": round(CSI300_5Y_CUM, 4),
        },
        "schemes": {},
        "perturbation_grid": {}
    }

    best_trades = []
    for name, scol, msk, em, xm in ablation_configs:
        res = eval_scheme_d15(hist_fb, scol, msk, price_lookup, all_dts, dt_to_idx, em, xm, FEE_RATE)
        results["schemes"][name] = {k: v for k, v in res.items() if k != "trades"}
        if name == "QuadTrack_Full_V13_B1":
            best_trades = res["trades"]
        tr_cnt = res["total_trades_1slot"]
        wr_val = res["win_rate_5y"] * 100
        po_val = res["payoff_5y"]
        nav_val = res["cum_nav_1slot"]
        mdd_val = res["mdd_1slot"] * 100
        print(f"{name:<24s} | N={tr_cnt:3d} | WR={wr_val:4.1f}% | Payoff={po_val:4.2f} | NAV={nav_val:6.2f}x | MDD={mdd_val:4.1f}%")

    print("[5/5] Running 9-grid perturbation test on QuadTrack_Full_V13_B1...")
    for td in [-10.0, -5.0, 0.0, 5.0, 10.0]:
        for od in [-0.003, 0.0, 0.003]:
            pert_thr_vec = s1b_thr_vec + td
            pert_open_cap = 0.078 + od
            m_t1_p = common_ok & hist_fb["d2_o_pct"].between(0.022, pert_open_cap) & (hist_fb["s_prior_dual"] >= 45.0) & (hist_fb["s_quant_dual"] >= 145.0) & ((hist_fb["tot_dual"] >= pert_thr_vec) | (has_distinct_sub & (hist_fb["buyable_plate_rk"] <= 2) & (hist_fb["tot_dual"] >= pert_thr_vec - 15.0)))
            m_t2_p = common_ok & (hist_fb["p_sz"] <= 3) & (hist_fb["is_pioneer_word"] | hist_fb["notice_hard"] | hist_fb["is_ma"]) & hist_fb["d2_o_pct"].between(0.028, pert_open_cap) & ((hist_fb["buyable_mkt_open_rk"] <= 6) | (hist_fb["buyable_plate_rk"] == 1)) & (hist_fb["d1_seal_tightness"] >= 15.0) & ((hist_fb["f_dd20_d0"] <= 0.92) | (hist_fb["clean_brk60"] == 1))
            m_t3_p = common_ok & (hist_fb["mkt_seal_rate"] < 0.55) & (hist_fb["buyable_mkt_open_rk"] <= 2) & (hist_fb["mkt_buy_open_lead"] >= 0.015) & hist_fb["d2_o_pct"].between(0.035, min(0.075, pert_open_cap)) & (hist_fb["f_dd20_d0"] <= 0.88) & (hist_fb["d1_seal_tightness"] >= 15.0)
            m_t4_p = common_ok & hist_fb["is_dual_theme"] & (hist_fb["buyable_plate_rk"] == 1) & hist_fb["d2_o_pct"].between(0.028, pert_open_cap) & ((hist_fb["f_dd20_d0"] <= 0.90) | (hist_fb["clean_brk60"] == 1)) & (hist_fb["d1_seal_tightness"] >= 12.0)
            m_quad_p = m_t1_p | m_t2_p | m_t3_p | m_t4_p
            res_p = eval_scheme_d15(hist_fb, "v13_tot_score", m_quad_p, price_lookup, all_dts, dt_to_idx, "trig", "B1", FEE_RATE)
            grid_k = f"thr_{td:+0.0f}_open_{od:+0.3f}"
            results["perturbation_grid"][grid_k] = {
                "thr_delta": td, "open_delta": od,
                "trades": res_p["total_trades_1slot"], "wr": res_p["win_rate_5y"],
                "payoff": res_p["payoff_5y"], "nav": res_p["cum_nav_1slot"], "mdd": res_p["mdd_1slot"]
            }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    pd.DataFrame(best_trades).to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"SUCCESS: Saved {OUT_JSON} & {OUT_CSV} in {time.time()-t0:.2f}s")


if __name__ == "__main__":
    run_v13()

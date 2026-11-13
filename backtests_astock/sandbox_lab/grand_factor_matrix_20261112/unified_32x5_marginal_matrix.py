#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Run Unified 32-Factor x 5-Strategy Marginal Impact Table & Save Ground-Truth JSON."""
import os, sys, json, time
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)

from unified_sim_core import CODE_BARS, _exit_after_unsealed_or_hold

FACTORS_32 = [
    ("G1_首板竞价均值>=0%", lambda d: d["mkt_fb_open_avg"] >= 0.0),
    ("G2_5日晋级率>=13%", lambda d: d["mkt_promo_1to2_5d"] >= 0.13),
    ("G3_昨封板率<=75%防高潮", lambda d: d["mkt_seal_rate_prev"] <= 0.75),
    ("G4_高开封板传感器>=40%", lambda d: d["roll20_ho_zt"] >= 0.40),
    ("G5_全场最高标>=5板", lambda d: d["mkt_max_board_prev"] >= 5),
    ("G6_昨高标跌停<2只", lambda d: d["prev_3b_dt_cnt"] < 2),
    ("G7_沪深300非单边阴跌(20日>=-3%)", lambda d: d["csi300_ret20"] >= -0.03),
    ("G8_沪深300窄幅横盘(振幅<=8%)", lambda d: d["csi300_amp20"] <= 0.08),
    ("T1_题材先验高分(s_prior>=50)", lambda d: d["s_prior"] >= 50.0),
    ("T2_Elo天梯强势(p_elo>=104)", lambda d: d["p_elo"] >= 104.0),
    ("T3_题材排名前3(rk_theme<=3)", lambda d: d["rk_theme"] <= 3),
    ("T4_板块涨停梯队>=3家", lambda d: d["p_sz"] >= 3),
    ("T5_L1a剔除事件大筐", lambda d: ~d["is_event_basket"]),
    ("T6_L1b剔除退潮脉冲", lambda d: ~d["is_dying_pulse"]),
    ("T7_细分新词先锋(is_granularity)", lambda d: d["is_granularity"]),
    ("T8_证监会同业涨停>=2家", lambda d: d["csrc_zt_cnt"] >= 2),
    ("T9_剔除硬科技纯外行", lambda d: ~d["is_pure_outsider"]),
    ("T10_非三大题材混战日", lambda d: ~d["is_melee_day"]),
    ("C1_中小流通市值(<=90亿)", lambda d: d["mcap"] <= 90.0),
    ("C2_前十股东锁仓>=50%", lambda d: d["lock_top10"] >= 50.0),
    ("C3_真实自由流通盘<=35亿", lambda d: d["real_free_mcap"] <= 35.0),
    ("C4_昨换手适中(9%~25%)", lambda d: d["prev_to"].between(9.0, 25.0)),
    ("C5_20日超跌(dd20<=0.86)", lambda d: d["dd20"] <= 0.86),
    ("C6_60日平台首突(clean_brk60)", lambda d: d["clean_brk60"]),
    ("C7_封单紧密度>=35", lambda d: d["seal_tightness"] >= 35.0),
    ("C8_10:30前早封或硬换手", lambda d: d["first_seal_time"] <= "10:30:00"),
    ("C9_拉萨席位<=1个(无散户扎堆)", lambda d: d["lhasa_seats_prev"] <= 1),
    ("C10_8日内有机构调研", lambda d: d["has_ir_8d"]),
    ("C11_巨潮硬催化公告", lambda d: d["notice_hard"] | d["notice_ma"]),
    ("C12_剔除减持问询风险雷公告", lambda d: ~d["notice_bad"]),
    ("C13_首轮新龙(30日内无老连板)", lambda d: d["prior_mb_gap"] > 30),
    ("A1_同题材可买排第1(true_buy_rk==1)", lambda d: d["true_buy_rk"] == 1),
    ("A2_同板块前排一字助攻(plate_yizi==1)", lambda d: d["plate_yizi_cnt"] == 1),
    ("A3_全场一字1~2只黄金共振", lambda d: d["mkt_yizi_cnt"].isin([1, 2])),
]


def attach_base_returns(df: pd.DataFrame, buy_kind: str, exit_mode: str) -> pd.DataFrame:
    df = df.copy()
    rets, exdts, hbars = [], [], []
    keep = []
    for idx, r in enumerate(df.itertuples(index=False)):
        cb = CODE_BARS.get(r.code)
        if cb is None:
            continue
        pos = cb["date_to_pos"].get(r.buy_date, -1)
        if pos < 0:
            continue
        o, h, zt, dt_p, pc = cb["open"][pos], cb["high"][pos], cb["zt_px"][pos], cb["dt_px"][pos], cb["pre_c"][pos]
        if buy_kind == "open":
            if o >= zt - 0.011 or o <= dt_p + 0.011:
                continue
            bpx = o
        elif buy_kind == "ign_1065":
            if o >= zt - 0.011 or o <= dt_p + 0.011:
                continue
            trig = max(pc * 1.065, o * 1.012)
            if trig >= zt - 0.011 or h < trig:
                continue
            bpx = trig
        elif buy_kind == "seal_zt":
            if o >= zt - 0.011 or h < zt - 0.011:
                continue
            bpx = zt
        else:
            continue
        sim = _exit_after_unsealed_or_hold(r.code, r.buy_date, bpx, exit_mode)
        if sim is None:
            continue
        keep.append(idx)
        exdts.append(sim[0]); rets.append(sim[1]); hbars.append(sim[2])
    out = df.iloc[keep].copy().reset_index(drop=True)
    out["exit_date"] = exdts
    out["net_ret"] = rets
    out["hold_bars"] = hbars
    return out


def main():
    t0 = time.time()
    c_hd = pd.read_parquet(f"{CUR_DIR}/cand_high_dragon.parquet")
    c_34 = pd.read_parquet(f"{CUR_DIR}/cand_3to4.parquet")
    c_23 = pd.read_parquet(f"{CUR_DIR}/cand_2to3.parquet")
    c_01 = pd.read_parquet(f"{CUR_DIR}/cand_0to1_firstboard.parquet")
    c_pr = pd.read_parquet(f"{CUR_DIR}/cand_pry_limitdown.parquet")

    pools = {
        "5ban_day6_open_le55": attach_base_returns(c_hd[(c_hd["prev_streak"] == 5) & (c_hd["open_pct"] <= 0.055)], "open", "5ban_feishu"),
        "top_dragon_4b_open": attach_base_returns(c_hd[(c_hd["prev_streak"] >= 4) & (c_hd["prev_streak"] == c_hd["mkt_max_board_prev"]) & (c_hd["mkt_top_cnt_prev"] <= 2) & (c_hd["open_pct"] <= 0.055)], "open", "5ban_feishu"),
        "3to4_open_3_to_85": attach_base_returns(c_34[(~c_34["prev_is_yizi"]) & c_34["open_pct"].between(0.03, 0.085)], "open", "3to4_feishu"),
        "2to3_open_2_to_80": attach_base_returns(c_23[(~c_23["prev_is_yizi"]) & c_23["open_pct"].between(0.02, 0.080)], "open", "relay_std"),
        "2to3_ign_1065": attach_base_returns(c_23[(~c_23["prev_is_yizi"]) & c_23["open_pct"].between(0.02, 0.078)], "ign_1065", "relay_std"),
        "0to1_ign_1065": attach_base_returns(c_01[c_01["open_pct"].between(0.015, 0.060)], "ign_1065", "relay_std"),
        "pry_3dt_open": attach_base_returns(c_pr[c_pr["prev_dt_streak"] >= 3], "open", "pry_5pct_5d"),
    }

    summary = {}
    for pname, pdf in pools.items():
        if pdf.empty:
            continue
        base_wr = float((pdf["net_ret"] > 0).mean() * 100.0)
        base_mn = float(pdf["net_ret"].mean() * 100.0)
        f_list = []
        for fname, fn in FACTORS_32:
            m = fn(pdf)
            sub = pdf[m]
            if len(sub) < 5:
                continue
            wr = float((sub["net_ret"] > 0).mean() * 100.0)
            mn = float(sub["net_ret"].mean() * 100.0)
            jul = sub[sub["buy_date"] >= "2026-07-01"]
            j_wr = float((jul["net_ret"] > 0).mean() * 100.0) if len(jul) > 0 else 0.0
            j_mn = float(jul["net_ret"].mean() * 100.0) if len(jul) > 0 else 0.0
            f_list.append({
                "factor": fname, "n": int(len(sub)), "keep_pct": round(len(sub)/len(pdf)*100, 1),
                "wr": round(wr, 2), "d_wr": round(wr - base_wr, 2),
                "mean_pct": round(mn, 2), "d_mean": round(mn - base_mn, 2),
                "jul26_n": int(len(jul)), "jul26_wr": round(j_wr, 1), "jul26_mean": round(j_mn, 2),
            })
        f_list.sort(key=lambda x: (x["d_mean"], x["d_wr"]), reverse=True)
        summary[pname] = {"base_n": int(len(pdf)), "base_wr": round(base_wr, 2), "base_mean_pct": round(base_mn, 2), "factors": f_list}
        print(f"[{pname}] base N={len(pdf)}, WR={base_wr:.1f}%, Mean={base_mn:+.2f}% | Top3 lift: {[(x['factor'], x['n'], x['wr'], x['mean_pct']) for x in f_list[:3]]}")

    json.dump(summary, open(f"{CUR_DIR}/unified_34x7_marginal_matrix.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[+] Saved unified_34x7_marginal_matrix.json in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

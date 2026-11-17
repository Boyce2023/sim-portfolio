#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RD 终审定版：四进五 40 因子修正检验 + 零穿越时序引擎 (含一字跌停锁死/严格次日开仓) + 纯整数打分卡审计"""
import os, sys, json, pickle
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
AST2 = f"{ROOT}/sim-portfolio/backtests_astock2"
sys.path.insert(0, AST2)
from core_3to4_5m_engine import sim_buy_5m, sim_exit_5m, _slice_metrics_chrono, csi300_ret

OUT_DIR = f"{AST2}/p2_4to5"
MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
FEE = 0.0020

def get_dev93_px(cb, cp, imap):
    cd = cb["dts"][cp]; ir = imap.get(cd)
    if not ir: return 99999.0
    bp = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k; bi = imap.get(cb["dts"][p]); bc = cb["close"][p] * cb["adjf"][p] / cb["adjf"][cp]
        if bi and bc > 0: bp = min(bp, bc * (1.93 + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k; bi = imap.get(cb["dts"][p]); bc = cb["close"][p] * cb["adjf"][p] / cb["adjf"][cp]
        if bi and bc > 0: bp = min(bp, bc * (2.93 + (ir / bi - 1.0)))
    return bp

def sim_4to5_pool(df, cb_map, b5m, sh_map, sz_map, buy_mode="open", d_unseal="reb2", use_dev93=False):
    out = [None] * len(df)
    for idx, r in enumerate(df.itertuples(index=False)):
        if not bool(r.buyable_open): continue
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6)
        if cb is None: continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1: continue
        bpx, bhh = sim_buy_5m(c6, bd, cb, pos, b5m, buy_mode)
        if bpx is None: continue
        ex_dt, spx, adjs, hb, shh = sim_exit_5m(c6, cb, pos, b5m, exit_mode="pm1345_5m", day5_unsealed_mode=d_unseal, use_yang_imm=False)
        if use_dev93 and bool(cb["is_zt"][pos]):
            imap = sh_map if c6.startswith("60") else sz_map
            pos_ex = cb["date_to_pos"].get(ex_dt, pos + 1)
            for k in range(pos + 1, pos_ex + 1):
                if bool(cb["is_yizi_dt"][k]): continue
                pl = get_dev93_px(cb, k, imap)
                if float(cb["high"][k]) >= pl:
                    ex_dt, spx, adjs, hb, shh = cb["dts"][k], float(max(cb["open"][k], pl)), float(cb["adjf"][k]), k - pos, 1000
                    break
        net_r = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        out[idx] = {"code": c6, "name": r.name, "buy_date": bd, "buy_hhmm": int(bhh), "exit_date": ex_dt, "exit_hhmm": int(shh), "hold_bars": int(hb), "net_ret": float(net_r), "sealed_5b": bool(cb["is_zt"][pos])}
    return out

def build_clean_score_4to5(df):
    sc = np.zeros(len(df), dtype=int)
    veto = (
        (df["prev_is_yizi"] == True) |
        (df["mkt_max_board_prev"] >= 6) |
        (df["has_tox_notice"] == 1) | (df["has_stock_reg"] == 1) |
        (df["headroom_100"] < 0.12) |
        (df["real_free_mcap"] >= 45.0) |
        (df["open_pct"] < -0.02) | (df["open_pct"] >= 0.068) |
        (df["prev_break_dt_rate_10d"] > 0.32)
    )
    sc += np.where(df["is_mkt_highest_4b"] == 1, 18, 0)
    sc += np.where(df["mkt_max_board_prev"] == 5, 6, 0)
    sc += np.where(df["is_sole_4b"] == 1, 14, np.where(df["b4_rival_cnt"] >= 3, -12, 0))
    sc += np.where(df["is_top1_4b_open"] == 1, 10, 0)
    sc += np.where(df["open_pct"].between(0.015, 0.055), 14, 0)
    sc += np.where(df["lock_top10"] >= 50.0, 14, np.where(df["lock_top10"] < 35.0, -8, 0))
    sc += np.where(df["open_board_count"] >= 1, 12, -10)
    sc += np.where(df["turn_boards_4d"] >= 3, 10, -8)
    sc += np.where(df["to_ratio_d4_d3"].between(0.65, 1.75), 8, np.where(df["to_ratio_d4_d3"] < 0.5, -10, 0))
    sc += np.where(df["px_d4"].between(8.0, 22.0), 10, np.where(df["px_d4"] >= 30.0, -10, 0))
    sc += np.where(df["real_free_mcap"] < 25.0, 8, 0)
    sc += np.where(df["headroom_100"] >= 0.22, 8, 0)
    sc += np.where(df["lhb_quant_cnt"] >= 1, 10, 0)
    sc += np.where(df["surf_yz_buy"] >= 1, -15, 0)
    sc += np.where(df["top_yz_buy"] >= 1, -10, 0)
    sc += np.where(df["prev_3b_dt_cnt"] == 0, 8, -6)
    sc += np.where(df["mkt_seal_rate_prev"] >= 0.65, 8, 0)
    sc += np.where(df["dd60"] <= 0.85, 8, 0)
    return np.where(veto, -999, sc)

def strict_top1_eval(df, traj, sc, thr):
    c = df[sc >= thr].assign(sc=sc[sc >= thr], idx=np.where(sc >= thr)[0])
    top_rows = []
    for bd, g in c.groupby("buy_date", sort=True):
        g_s = g.sort_values(["sc", "open_pct", "lock_top10"], ascending=[False, False, False])
        i0 = int(g_s["idx"].iloc[0])
        if traj[i0] is not None:
            top_rows.append(dict(traj[i0], priority_score=float(g_s["sc"].iloc[0]), score=int(g_s["sc"].iloc[0])))
    tdf = pd.DataFrame(top_rows)
    all_rows = [dict(traj[i], priority_score=float(sc[i]), score=int(sc[i])) for i in np.where(sc >= thr)[0] if traj[i] is not None]
    tdf_all = pd.DataFrame(all_rows)
    return tdf, tdf_all

def main():
    df = pd.read_parquet(f"{OUT_DIR}/cand_4to5_enriched.parquet")
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f: cb_map = pickle.load(f)["code_bars"]
    with open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json") as f: idx_k = json.load(f)
    d5 = pd.read_parquet(f"{OUT_DIR}/cand_4to5_5m_bars.parquet")
    b5m = {(str(c).zfill(6), str(d)): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float) for (c, d), g in d5.groupby(["c6", "date"], sort=False)}

    for bm in ["open", "touch65_1130"]:
        for du in ["reb2", "cut_weak"]:
            for dev in [False, True]:
                tr = sim_4to5_pool(df, cb_map, b5m, idx_k["sh000002"], idx_k["sz399107"], bm, du, dev)
                sc = build_clean_score_4to5(df)
                t_top, _ = strict_top1_eval(df, tr, sc, 72)
                if not t_top.empty:
                    m5 = _slice_metrics_chrono(t_top, "2022-01-04", "2026-11-10")
                    print(f"[{bm:12s}|{du:8s}|dev93={str(dev):5s}] thr72: n={m5['single_n']:3d} WR={m5['wr']:4.1f}% PO={m5['payoff']:4.2f} NAV={m5['single_nav']:6.2f}x MDD={m5['single_mdd_pct']:4.1f}% EQ={m5['eq_nav']:6.2f}x")

    # Best physical mode: open + reb2 + dev93=False (also compare touch65_1130)
    tr_best = sim_4to5_pool(df, cb_map, b5m, idx_k["sh000002"], idx_k["sz399107"], "open", "reb2", False)
    df["ret_clean"] = [x["net_ret"] if x else np.nan for x in tr_best]
    # Screen 40 clean factors (with corrected lock_top10 & dd60!)
    pool = df[(~df["prev_is_yizi"]) & df["buyable_open"] & df["ret_clean"].notna()].copy()
    pool["yr"] = pd.to_datetime(pool["buy_date"]).dt.year
    b_avg = float(pool["ret_clean"].mean())
    f40 = [
        ("prev_is_yizi(第四板一字)", df["prev_is_yizi"] == True, True),
        ("is_mkt_highest_4b(昨日最高4板争空间龙)", pool["is_mkt_highest_4b"] == 1, False),
        ("mkt_max_ge6(头顶>=6板老龙压制坟场)", pool["mkt_max_board_prev"] >= 6, False),
        ("mkt_max_eq5(头顶仅5板)", pool["mkt_max_board_prev"] == 5, False),
        ("is_sole_4b(全场唯一4板独苗)", pool["is_sole_4b"] == 1, False),
        ("b4_rival_ge2(同日>=2只4板PK)", pool["b4_rival_cnt"] >= 2, False),
        ("is_top1_4b_open(同日4板竞价第1)", pool["is_top1_4b_open"] == 1, False),
        ("open_1.5_5.5%(竞价温和高开1.5~5.5%)", pool["open_pct"].between(0.015, 0.055), False),
        ("open_gt_6.5%(竞价抢筹>6.5%天地板区)", pool["open_pct"] > 0.065, False),
        ("open_lt_m2%(竞价核按钮<-2%)", pool["open_pct"] < -0.02, False),
        ("lock_top10_ge50%(前十锁仓>=50%修正)", pool["lock_top10"] >= 50.0, False),
        ("lock_top10_ge55%(前十锁仓>=55%修正)", pool["lock_top10"] >= 55.0, False),
        ("lock_top10_lt35%(前十锁仓<35%散乱)", pool["lock_top10"] < 35.0, False),
        ("dd60_le_0.85(60日超跌黄金坑修正)", pool["dd60"] <= 0.85, False),
        ("open_board_ge1(第4板曾开板换手)", pool["open_board_count"] >= 1, False),
        ("open_board_eq0(第4板硬封0开板)", pool["open_board_count"] == 0, False),
        ("turn_boards_4d_ge3(前4板>=3换手板)", pool["turn_boards_4d"] >= 3, False),
        ("turn_boards_4d_le2(前4板<=2换手虚高)", pool["turn_boards_4d"] <= 2, False),
        ("to_ratio_0.65_1.75(4/3板换手良性)", pool["to_ratio_d4_d3"].between(0.65, 1.75), False),
        ("to_ratio_lt0.5(4/3板缩量断层)", pool["to_ratio_d4_d3"] < 0.5, False),
        ("d4_dip_subzero(第4板曾水下洗盘)", pool["d4_intraday_dip"] < 0.0, False),
        ("d4_amp_ge7%(第4板振幅>=7%)", pool["d4_amp"] >= 0.07, False),
        ("first_seal_le1000(第4板10点前封板)", pool["first_seal_time"].astype(str) <= "10:00:00", False),
        ("seal_tightness_ge45(封单紧密度>=45)", pool["seal_tightness"] >= 45.0, False),
        ("px_d4_8_22(股价8~22元黄金带)", pool["px_d4"].between(8.0, 22.0), False),
        ("px_d4_ge30(股价>=30元高价)", pool["px_d4"] >= 30.0, False),
        ("real_free_mcap_lt25(自由流通<25亿)", pool["real_free_mcap"] < 25.0, False),
        ("real_free_mcap_ge45(自由流通>=45亿天花板)", pool["real_free_mcap"] >= 45.0, False),
        ("headroom_100_ge22%(10日异动空间>=22%)", pool["headroom_100"] >= 0.22, False),
        ("headroom_100_lt12%(10日异动空间<12%撞线)", pool["headroom_100"] < 0.12, False),
        ("headroom_200_ge35%(30日异动空间>=35%)", pool["headroom_200"] >= 0.35, False),
        ("lhb_quant_ge1(龙虎榜量化席位>=1)", pool["lhb_quant_cnt"] >= 1, False),
        ("surf_yz_ge1(一日游砸盘席位>=1)", pool["surf_yz_buy"] >= 1, False),
        ("top_yz_ge1(顶级游资明牌上榜)", pool["top_yz_buy"] >= 1, False),
        ("lhasa_eq0(零拉萨散户席位)", pool["lhasa_seats_prev"] == 0, False),
        ("has_tox_or_reg(减持暴雷或监管函)", (pool["has_tox_notice"] == 1) | (pool["has_stock_reg"] == 1), False),
        ("has_4321_echelon(同题材4321完整梯队)", pool["has_4321_echelon"] == 1, False),
        ("s_elo_ge100(细分题材Elo>=100)", pool["s_elo"] >= 100.0, False),
        ("prev_break_dt_gt32%(近10日炸板核按钮率>32%)", pool["prev_break_dt_rate_10d"] > 0.32, False),
        ("prev_3b_dt_eq0(昨日零3板跌停)", pool["prev_3b_dt_cnt"] == 0, False),
        ("mkt_seal_ge65%(昨日封板率>=65%)", pool["mkt_seal_rate_prev"] >= 0.65, False),
        ("csi300_ret20_ge_m3%(大盘20日未崩盘)", pool["csi300_ret20"] >= -0.03, False),
    ]
    rows_f = []
    for nm, msk, use_full in f40:
        s = (df.loc[msk & df["ret_clean"].notna()] if use_full else pool.loc[msk])
        if len(s) == 0: continue
        r = s["ret_clean"]; pos, neg = r[r > 0], r[r <= 0]
        po = float(pos.mean() / abs(neg.mean())) if len(neg) else 99.0
        e_m = float(s.loc[s["buy_date"] < "2024-01-01", "ret_clean"].mean()) if (s["buy_date"] < "2024-01-01").any() else np.nan
        l_m = float(s.loc[s["buy_date"] >= "2024-01-01", "ret_clean"].mean()) if (s["buy_date"] >= "2024-01-01").any() else np.nan
        rows_f.append({"factor": nm, "n": len(s), "wr": round(float((r > 0).mean()), 4), "payoff": round(po, 2), "mean_ret": round(float(r.mean()), 4), "alpha_vs_base": round(float(r.mean() - b_avg), 4), "early_22_23": round(e_m, 4) if not np.isnan(e_m) else None, "late_24_26": round(l_m, 4) if not np.isnan(l_m) else None})
    pd.DataFrame(rows_f).sort_values("alpha_vs_base", ascending=False).to_csv(f"{OUT_DIR}/rd_factor_42_clean.csv", index=False, encoding="utf-8-sig")

    sc = build_clean_score_4to5(df)
    print("\n=== 四进五 V1.0 分数线平原 (严格每日只挂第1名 + 严禁同日尾盘卖早盘买 + 一字跌停锁仓计入) ===")
    for thr in [60, 64, 68, 72, 76, 80, 84, 88]:
        t_top, t_all = strict_top1_eval(df, tr_best, sc, thr)
        if t_top.empty: continue
        m5 = _slice_metrics_chrono(t_top, "2022-01-04", "2026-11-10")
        m_eq = _slice_metrics_chrono(t_all, "2022-01-04", "2026-11-10")
        m3 = _slice_metrics_chrono(t_top[t_top.buy_date >= "2024-01-02"], "2024-01-02", "2026-11-10")
        mj = _slice_metrics_chrono(t_top[t_top.buy_date >= "2026-07-01"], "2026-07-01", "2026-11-10")
        yrs = [(_slice_metrics_chrono(t_top[t_top.buy_date.str.startswith(str(y))], f"{y}-01-01", f"{y}-12-31")["single_nav"] - 1.0) * 100 for y in [2022,2023,2024,2025,2026]]
        pos_y = sum(1 for x in yrs if x > 0)
        print(f"thr>={thr:2d} | 单仓{m5['single_n']:3d}笔 WR={m5['wr']:4.1f}% PO={m5['payoff']:4.2f} 均={m5['mean_pct']:+5.2f}% NAV={m5['single_nav']:6.2f}x MDD={m5['single_mdd_pct']:4.1f}% 等权={m_eq['eq_nav']:6.2f}x | 近3年={m3['single_nav']:5.2f}x | 7月起={mj['single_n']}笔/{mj['single_nav']:.2f}x | 正年={pos_y}/5 {[round(x,1) for x in yrs]}")

if __name__ == "__main__":
    main()

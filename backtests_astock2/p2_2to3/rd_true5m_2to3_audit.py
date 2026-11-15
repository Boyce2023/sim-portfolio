#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RD 独立复核：修正 lock_top10 百分制口径 + 接入真实 5 分钟 K 线检验二进三 (Open vs Touch65_1130)"""
import os, sys, json, pickle, sqlite3
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
sys.path.insert(0, f"{ROOT}/sim-portfolio/backtests_astock2")
from core_3to4_5m_engine import sim_buy_5m, sim_exit_5m, _slice_metrics_chrono, csi300_ret

MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p2_2to3"
FEE = 0.0020

def load_all_local_5m(needed_codes):
    bars = {}
    for pq in [
        f"{ROOT}/sim-portfolio/data/cand_5m_bars_v15_complete.parquet",
        f"{ROOT}/sim-portfolio/backtests_astock2/data_5y/cand_3to4_5m_bars.parquet",
        f"{ROOT}/sim-portfolio/backtests_astock2/p2_4to5/cand_4to5_5m_bars.parquet",
    ]:
        if os.path.exists(pq):
            d5 = pd.read_parquet(pq, columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"])
            d5["c6"] = d5["c6"].astype(str).str.zfill(6)
            d5 = d5[d5["c6"].isin(needed_codes)].sort_values(["c6", "date", "hhmm_int"])
            for (c, dt_s), g in d5.groupby(["c6", "date"], sort=False):
                if (c, dt_s) not in bars:
                    bars[(c, dt_s)] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
    db_p = f"{ROOT}/sim-portfolio/data/firstboard_5m_5y_pit.db"
    if os.path.exists(db_p):
        con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
        q_codes = sorted(needed_codes)
        for i in range(0, len(q_codes), 400):
            sub_c = q_codes[i:i+400]
            qm = ",".join(["?"] * len(sub_c))
            sql = f"SELECT sec_code, substr(bar_time,1,10) as dt, CAST(substr(bar_time,12,2)||substr(bar_time,15,2) AS INT) as hhmm_int, open, high, low, close, volume, amount FROM firstboard_5m_bars WHERE sec_code IN ({qm})"
            dfb = pd.read_sql_query(sql, con, params=sub_c)
            if not dfb.empty:
                dfb["c6"] = dfb["sec_code"].astype(str).str.zfill(6)
                dfb.sort_values(["c6", "dt", "hhmm_int"], inplace=True)
                for (c, dt_s), g in dfb.groupby(["c6", "dt"], sort=False):
                    if (c, dt_s) not in bars:
                        bars[(c, dt_s)] = g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        con.close()
    return bars

def sim_pool_5m(df, cb_map, bars_5m, buy_mode="touch65_1130", exit_mode="pm1345_5m", d_unseal="reb2"):
    out = [None] * len(df)
    cov_5m, tot_chk = 0, 0
    for idx, r in enumerate(df.itertuples(index=False)):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6)
        if cb is None: continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1: continue
        tot_chk += 1
        has_b5 = (c6, bd) in bars_5m
        if has_b5: cov_5m += 1
        if buy_mode == "open":
            op, zt = float(cb["open"][pos]), float(cb["zt_px"][pos])
            if op >= zt - 0.005: continue
            bpx, bhh = op, 925
        else:
            if has_b5:
                bpx, bhh = sim_buy_5m(c6, bd, cb, pos, bars_5m, buy_mode)
            else:
                op, pc, hi, zt = float(cb["open"][pos]), float(cb["pre_c"][pos]), float(cb["high"][pos]), float(cb["zt_px"][pos])
                trig = max(pc * 1.065, op) if "65" in buy_mode else max(pc * 1.055, op)
                if op >= zt - 0.005 or trig >= zt - 0.005 or hi < trig: continue
                bpx, bhh = max(op, trig), 1000
            if bpx is None: continue
        ex_dt, spx, adjs, hb, shh = sim_exit_5m(c6, cb, pos, bars_5m, exit_mode=exit_mode, day5_unsealed_mode=d_unseal, use_yang_imm=False)
        net_r = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        out[idx] = {"code": c6, "name": r.name, "buy_date": bd, "buy_hhmm": bhh, "exit_date": ex_dt, "exit_hhmm": shh, "hold_bars": hb, "net_ret": float(net_r), "is_zt_buy": bool(cb["is_zt"][pos])}
    return out, cov_5m, tot_chk

def main():
    df = pd.read_parquet(f"{OUT_DIR}/cand_2to3_enriched.parquet")
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f: cb_map = pickle.load(f)["code_bars"]
    codes = set(df["code"].astype(str).str.zfill(6))
    bars_5m = load_all_local_5m(codes)
    print(f"Loaded local 5m pairs: {len(bars_5m)} for {len(codes)} codes")
    print("lock_top10 quantiles:", df["lock_top10"].quantile([0.1, 0.3, 0.5, 0.7, 0.9]).to_dict())

    for bm in ["open", "touch65_1130"]:
        for d_un in ["reb2", "cut_weak"]:
            out, cov, tot = sim_pool_5m(df, cb_map, bars_5m, bm, "pm1345_5m", d_un)
            rets = np.array([x["net_ret"] for i, x in enumerate(out) if x is not None and not df["prev_is_yizi"].iloc[i] and df["open_pct"].iloc[i] >= -0.04])
            wr = float((rets > 0).mean()) if len(rets) else 0
            po = float(rets[rets > 0].mean() / abs(rets[rets <= 0].mean())) if (rets <= 0).any() else 0
            print(f"Base [{bm} | {d_un}] 5m_cov={cov}/{tot} ({cov/max(1,tot)*100:.1f}%) | n={len(rets)} WR={wr*100:.1f}% PO={po:.2f} avg={rets.mean()*100:+.2f}%")

    # Save trajectory under touch65_1130 + reb2 and open + cut_weak for factor comparison
    out_t65, _, _ = sim_pool_5m(df, cb_map, bars_5m, "touch65_1130", "pm1345_5m", "reb2")
    out_opn, _, _ = sim_pool_5m(df, cb_map, bars_5m, "open", "pm1345_5m", "reb2")
    with open(f"{OUT_DIR}/rd_trajectories_5m.pkl", "wb") as f:
        pickle.dump({"touch65_reb2": out_t65, "open_reb2": out_opn}, f)

    # Check corrected lock_top10 & top dual-period factors on touch65_reb2
    df["ret_t65"] = [x["net_ret"] if x else np.nan for x in out_t65]
    df["ret_opn"] = [x["net_ret"] if x else np.nan for x in out_opn]
    sub = df[(~df["prev_is_yizi"]) & (df["open_pct"].between(-0.02, 0.075))].copy()
    for col_tag, cond in [
        ("lock_top10>=50%", sub["lock_top10"] >= 50.0),
        ("lock_top10>=55%", sub["lock_top10"] >= 55.0),
        ("dd60<=-0.25(黄金坑)", sub["dd60"] <= -0.25),
        ("rk_theme==1", sub["rk_theme"] == 1),
        ("s_elo>=100", sub["s_elo"] >= 100.0),
        ("open_board>=1", sub["open_board_count"] >= 1),
        ("to_ratio_0.8~1.6", sub["to_ratio_d2_d1"].between(0.8, 1.6)),
        ("seal_0936_1030", sub["first_seal_time"].astype(str).between("09:36:00", "10:30:00")),
        ("open_pct_2~6.5%", sub["open_pct"].between(0.02, 0.065)),
        ("is_top1_2b_open", sub["is_top1_2b_open"] == True),
        ("plate_fresh01_hi>=1", sub["plate_fresh01_hi_cnt"] >= 1),
        ("mkt_promo>=0.18", sub["mkt_promo_1to2_5d"] >= 0.18),
        ("prev_3b_dt==0", sub["prev_3b_dt_cnt"] == 0),
        ("no_lhasa", sub["lhasa_seats_prev"] == 0),
    ]:
        s_t = sub.loc[cond & sub["ret_t65"].notna(), ["buy_date", "ret_t65"]]
        s_o = sub.loc[cond & sub["ret_opn"].notna(), ["buy_date", "ret_opn"]]
        e_t = s_t[s_t["buy_date"] < "2024-01-01"]["ret_t65"].mean() * 100
        l_t = s_t[s_t["buy_date"] >= "2024-01-01"]["ret_t65"].mean() * 100
        wr_t = (s_t["ret_t65"] > 0).mean() * 100
        wr_o = (s_o["ret_opn"] > 0).mean() * 100
        print(f"{col_tag:22s} | T65: n={len(s_t):4d} WR={wr_t:4.1f}% avg={s_t['ret_t65'].mean()*100:+5.2f}% (22-23:{e_t:+5.2f}%, 24-26:{l_t:+5.2f}%) | OPN: n={len(s_o):4d} WR={wr_o:4.1f}% avg={s_o['ret_opn'].mean()*100:+5.2f}%")

if __name__ == "__main__":
    main()

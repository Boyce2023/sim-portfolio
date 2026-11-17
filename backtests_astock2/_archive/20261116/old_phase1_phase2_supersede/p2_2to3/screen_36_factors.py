#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""screen_36_factors.py: 二进三买卖机制矩阵实测与 36+ 因子双期边际检验"""
import os, sys, json, pickle
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/p2_2to3"
FEE = 0.0020

def sim_cand_trajectory(df, cb_map, buy_mode="open", exit_mode="pm1345"):
    rets, exit_dts, is_zts = [], [], []
    for r in df.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = cb_map.get(c6)
        if not cb: rets.append(np.nan); exit_dts.append(""); is_zts.append(False); continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1: rets.append(np.nan); exit_dts.append(""); is_zts.append(False); continue
        op, pc, zt = float(cb["open"][pos]), float(cb["pre_c"][pos]), float(cb["zt_px"][pos])
        if op >= zt - 0.005: rets.append(np.nan); exit_dts.append(""); is_zts.append(False); continue

        if buy_mode == "open": buy_px = op
        elif buy_mode == "touch65_1130":
            trig = max(pc * 1.065, op)
            if float(cb["high"][pos]) < trig or trig >= zt - 0.005: rets.append(np.nan); exit_dts.append(""); is_zts.append(False); continue
            buy_px = max(op, trig)
        elif buy_mode == "touch55_1130":
            trig = max(pc * 1.055, op)
            if float(cb["high"][pos]) < trig or trig >= zt - 0.005: rets.append(np.nan); exit_dts.append(""); is_zts.append(False); continue
            buy_px = max(op, trig)
        elif buy_mode == "dyn60_08_1130":
            trig = max(pc * 1.060, op * 1.008)
            if float(cb["high"][pos]) < trig or trig >= zt - 0.005: rets.append(np.nan); exit_dts.append(""); is_zts.append(False); continue
            buy_px = max(op, trig)

        n, is_zt_day, adj_buy = len(cb["dts"]), bool(cb["is_zt"][pos]), float(cb["adjf"][pos])
        if exit_mode == "fixed_next_day":
            k = pos + 1
            rets.append((float(cb["close"][k]) * float(cb["adjf"][k])) / (buy_px * adj_buy) * (1.0 - FEE) - 1.0); exit_dts.append(cb["dts"][k]); is_zts.append(is_zt_day); continue

        if not is_zt_day:
            k = pos + 1
            while k < n and bool(cb["is_yizi_dt"][k]): k += 1
            if k >= n: k = n - 1
            o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
            d_strong = (float(cb["close"][pos]) >= op) and (float(cb["close"][pos]) >= pc) and (o5 >= p5 * 1.005)
            if not d_strong or k > pos + 1:
                rets.append((o5 * float(cb["adjf"][k])) / (buy_px * adj_buy) * (1.0 - FEE) - 1.0); exit_dts.append(cb["dts"][k]); is_zts.append(False); continue
            if not bool(cb["is_zt"][k]):
                rets.append((c5 * float(cb["adjf"][k])) / (buy_px * adj_buy) * (1.0 - FEE) - 1.0); exit_dts.append(cb["dts"][k]); is_zts.append(False); continue
            pos_start = k + 1
        else: pos_start = pos + 1

        k, exited = pos_start, False
        while k < n:
            if bool(cb["is_yizi_dt"][k]): k += 1; continue
            if k > pos_start and bool(cb["is_yizi_dt"][k - 1]):
                rets.append((float(cb["open"][k]) * float(cb["adjf"][k])) / (buy_px * adj_buy) * (1.0 - FEE) - 1.0); exit_dts.append(cb["dts"][k]); is_zts.append(True); exited = True; break
            if bool(cb["is_zt"][k]): k += 1; continue
            spx = float(cb["close"][k])
            if exit_mode in ("pm1345_5m", "vwap1030_blast_5m") and float(cb["high"][k]) >= float(cb["pre_c"][k]) * 1.085 and float(cb["close"][k]) < float(cb["zt_px"][k]) - 0.01:
                spx = max(float(cb["close"][k]), float(cb["pre_c"][k]) * 1.050)
            rets.append((spx * float(cb["adjf"][k])) / (buy_px * adj_buy) * (1.0 - FEE) - 1.0); exit_dts.append(cb["dts"][k]); is_zts.append(True); exited = True; break
        if not exited:
            k = n - 1
            rets.append((float(cb["close"][k]) * float(cb["adjf"][k])) / (buy_px * adj_buy) * (1.0 - FEE) - 1.0); exit_dts.append(cb["dts"][k]); is_zts.append(is_zt_day)
    return pd.Series(rets, index=df.index), pd.Series(exit_dts, index=df.index), pd.Series(is_zts, index=df.index)

def run_factor_screen():
    df = pd.read_parquet(f"{OUT_DIR}/cand_2to3_enriched.parquet")
    with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f: cb_map = pickle.load(f)["code_bars"]
    matrix_res = {}
    for bm in ["open", "touch65_1130", "touch55_1130", "dyn60_08_1130"]:
        for em in ["pm1345_5m", "vwap1030_blast_5m", "eod_break_5m", "fixed_next_day"]:
            r_s, _, _ = sim_cand_trajectory(df[(~df["prev_is_yizi"]) & (df["open_pct"] >= -0.04)], cb_map, bm, em)
            v = r_s.dropna(); pos, neg = v[v > 0], v[v <= 0]
            odds = (pos.mean() / abs(neg.mean())) if len(neg) and abs(neg.mean()) > 0 else 0.0
            matrix_res[f"{bm} x {em}"] = {"n": len(v), "win_rate": round(float((v > 0).mean()), 4), "odds": round(float(odds), 2), "avg_ret": round(float(v.mean()), 4)}
    with open(f"{OUT_DIR}/buy_exit_matrix.json", "w") as f: json.dump(matrix_res, f, indent=2)

    df["net_ret"], df["exit_dt"], df["sealed_3b"] = sim_cand_trajectory(df, cb_map, "open", "pm1345_5m")
    df["year"] = pd.to_datetime(df["buy_date"]).dt.year
    df.to_parquet(f"{OUT_DIR}/cand_2to3_enriched.parquet", index=False)

    pool = df[(~df["prev_is_yizi"]) & (df["open_pct"] >= -0.04) & df["net_ret"].notna()].copy()
    bench_avg = pool["net_ret"].mean()

    f_masks = {
        "prev_is_yizi (2板一字巨坑)": df["prev_is_yizi"] == True,
        "to_ratio_0.8~1.6 (良性换手)": (pool["to_ratio_d2_d1"] >= 0.8) & (pool["to_ratio_d2_d1"] <= 1.6),
        "to_ratio_<0.5 (缩量断层暗一字)": pool["to_ratio_d2_d1"] < 0.5, "to_ratio_>2.0 (爆量分歧大坑)": pool["to_ratio_d2_d1"] > 2.0,
        "open_board_count_ge1 (二板曾开板)": pool["open_board_count"] >= 1, "seal_time_early (<=09:35秒板)": pool["first_seal_time"] <= "09:35:00",
        "seal_time_mid (09:36~10:30换手封)": (pool["first_seal_time"] >= "09:36:00") & (pool["first_seal_time"] <= "10:30:00"),
        "seal_time_late (>=14:00尾盘偷袭)": pool["first_seal_time"] >= "14:00:00", "seal_tightness_ge50 (封板硬度高)": pool["seal_tightness"] >= 50.0,
        "seal_amount_ge5000 (二板封单>=5千万)": pool["seal_amount"] >= 5000, "prev_real_to_ge15 (自由流通换手>=15%)": pool["prev_real_to"] >= 15.0,
        "d2_amp_ge5 (二板振幅>=5%充分博弈)": pool["d2_amp"] >= 0.05, "open_pct_0~3% (微幅平开高开)": (pool["open_pct"] >= 0.0) & (pool["open_pct"] < 0.03),
        "open_pct_2~6% (竞价黄金起爆带)": (pool["open_pct"] >= 0.02) & (pool["open_pct"] <= 0.06), "open_pct_3~7% (强势竞价带)": (pool["open_pct"] >= 0.03) & (pool["open_pct"] <= 0.07),
        "open_pct_ge7% (竞价超抢高位顶)": pool["open_pct"] >= 0.07, "open_pct_<0% (竞价低开抢水)": pool["open_pct"] < 0.0,
        "is_top1_2b_open (全场二板竞价第1)": pool["is_top1_2b_open"] == True, "is_plate_top1_2b (同题材二板竞价第1)": pool["is_plate_top1_2b"] == True,
        "open_lead_ge2.5% (领先同题材老二>=2.5%)": pool["open_lead_plate_rk2"] >= 0.025, "day_2b_cnt_le8 (同日二板家数<=8家)": pool["day_2b_cnt"] <= 8,
        "rk_theme_1 (同日最强题材龙头)": pool["rk_theme"] == 1, "rk_theme_le3 (前三大题材前三甲)": pool["rk_theme"] <= 3,
        "s_elo_ge100 (细分概念Elo合格)": pool["s_elo"] >= 100.0, "p_elo_ge100 (大概念Elo合格)": pool["p_elo"] >= 100.0,
        "not_event_basket (排除事件大筐)": pool["is_event_basket"] == False, "csrc_zt_cnt_ge4 (行业涨停潮>=4只)": pool["csrc_zt_cnt"] >= 4,
        "plate_fb_cnt_ge3 (同题材首板小弟>=3只)": pool["plate_fb_cnt"] >= 3, "plate_fb_ho_cnt_ge2 (小弟次日高开>=2只)": pool["plate_fb_ho_cnt"] >= 2,
        "plate_fresh01_hi_ge1 (题材新首板高开助攻)": pool["plate_fresh01_hi_cnt"] >= 1, "lock_top10_ge45 (前十大锁仓>=45%)": pool["lock_top10"] >= 0.45,
        "lock_top10_ge50 (前十大锁仓>=50%)": pool["lock_top10"] >= 0.50, "real_free_mcap_lt25 (自由流通市值<25亿)": pool["real_free_mcap"] < 25.0,
        "real_free_mcap_lt40 (自由流通市值<40亿)": pool["real_free_mcap"] < 40.0, "mcap_lt80 (总市值<80亿轻盈标)": pool["mcap"] < 80.0,
        "px_d2_lt8 (二板股价<8元低价)": pool["px_d2"] < 8.0, "px_d2_lt20 (二板股价<20元)": pool["px_d2"] < 20.0, "px_d2_ge30 (二板股价>=30元高价)": pool["px_d2"] >= 30.0,
        "dd60_le_m25 (60日超跌回撤<=-25%)": pool["dd60"] <= -0.25, "clean_brk60 (60日干净突破形态)": pool["clean_brk60"] == True,
        "prior_mb_gap_gt60 (首发新面孔无老妖套牢)": pool["prior_mb_gap"] > 60, "is_mkt_highest_2b (冰点2板破局空间龙)": pool["is_mkt_highest_2b"] == True,
        "mkt_max_board_ge5 (市场存在>=5板高标压制)": pool["mkt_max_board_prev"] >= 5, "mkt_promo_ge18 (5日晋级率情绪暖>=18%)": pool["mkt_promo_1to2_5d"] >= 0.18,
        "mkt_seal_ge65 (昨日涨停封板率>=65%)": pool["mkt_seal_rate_prev"] >= 0.65, "break_dt_le25 (近10日炸板跌停率<=25%)": pool["prev_break_dt_rate_10d"] <= 0.25,
        "prev_3b_dt_0 (近3日零3板大面闷杀)": pool["prev_3b_dt_cnt"] == 0, "csi_ret5_lt0 (大盘5日阴跌逆市妖股)": pool["csi300_ret5"] < 0,
        "csi_ret5_ge_m02 (大盘5日平稳>=-2%)": pool["csi300_ret5"] >= -0.02, "csi300_ret20_ge0 (大盘20日月线顺势)": pool["csi300_ret20"] >= 0,
        "csi_1d_prev_ge0 (隔夜大盘收红)": pool["csi_1d_prev"] >= 0, "lhasa_seats_0 (二板零拉萨席位)": pool["lhasa_seats_prev"] == 0,
        "lhb_quant_cnt_0 (二板零量化席位)": pool["lhb_quant_cnt"] == 0, "lhb_inst_cnt_ge1 (机构席位现身二板)": pool["lhb_inst_cnt"] >= 1,
        "surf_yz_buy_0 (避开一日游砸盘席位)": pool["surf_yz_buy"] == 0, "top_yz_buy_ge1 (顶级格局游资进场)": pool["top_yz_buy"] >= 1,
        "headroom_100_ge30 (10日异动剩余空间>=30%)": pool["headroom_100"] >= 0.30,
        "no_tox_no_reg (零监管零暴雷公告)": (~pool["has_tox_notice"]) & (~pool["has_stock_reg"]) & (~pool["has_ex_reg"]),
        "is_post_holiday_or_mon (周一或长假后首日)": pool["is_post_holiday_or_mon"] == True,
        "not_earn_blackout (避开4/7/10月业绩雷期)": pool["is_earn_blackout_month"] == False,
    }

    records = []
    for fname, m in f_masks.items():
        sub = (df[m] if "prev_is_yizi" in fname else pool[m])[lambda s: s["net_ret"].notna()]
        n = len(sub)
        if n == 0: continue
        wr = float((sub["net_ret"] > 0).mean())
        pos, neg = sub.loc[sub["net_ret"] > 0, "net_ret"], sub.loc[sub["net_ret"] <= 0, "net_ret"]
        odds = float(pos.mean() / abs(neg.mean())) if len(neg) and abs(neg.mean()) > 0 else 0.0
        avg_r = float(sub["net_ret"].mean())
        r_22_23 = float(sub.loc[sub["buy_date"] < "2024-01-01", "net_ret"].mean()) if len(sub[sub["buy_date"] < "2024-01-01"]) else np.nan
        r_24_26 = float(sub.loc[sub["buy_date"] >= "2024-01-01", "net_ret"].mean()) if len(sub[sub["buy_date"] >= "2024-01-01"]) else np.nan
        pos_yrs = sum(sub.loc[sub["year"] == y, "net_ret"].mean() > 0 for y in [2022, 2023, 2024, 2025, 2026] if len(sub[sub["year"] == y]) >= 5)
        records.append({"因子名称": fname, "样本笔数": n, "胜率": round(wr, 4), "盈亏比": round(odds, 2), "单笔净均值": round(avg_r, 4), "基准组净均值": round(bench_avg, 4), "净差值(Alpha)": round(avg_r - bench_avg, 4), "2022-2023均值": round(r_22_23, 4) if not np.isnan(r_22_23) else None, "2024-2026均值": round(r_24_26, 4) if not np.isnan(r_24_26) else None, "5年正收益年数": int(pos_yrs)})

    pd.DataFrame(records).sort_values("净差值(Alpha)", ascending=False).to_csv(f"{OUT_DIR}/factor_36_screen.csv", index=False, encoding="utf-8-sig")
    with open(f"{OUT_DIR}/factor_36_screen.json", "w", encoding="utf-8") as f: json.dump(records, f, ensure_ascii=False, indent=2)
    print(f"[+] Screened {len(records)} factors saved to {OUT_DIR}/factor_36_screen.csv")

if __name__ == "__main__":
    run_factor_screen()

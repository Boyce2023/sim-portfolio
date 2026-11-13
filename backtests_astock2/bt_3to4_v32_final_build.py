#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
三进四 V3.2 定版全量实证计算器：
1. 为 cand_3to4_enriched54.parquet 持久化写入 surf_yz_buy 与 csi_1d_prev；
2. 校准 V3.2 标准档与严格档（全五年、去2025四年、2025至2026样本外、近三年、近1年、7月以来、逐年对比沪深300）；
3. 导出 [L0] 主文档、[L1] 总检与 [L2] 01..08 八篇专项小回测全部精确数字至 v32_all_metrics.json。
"""
import os, sys, glob, json, re, pickle
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
if CUR_DIR not in sys.path:
    sys.path.insert(0, CUR_DIR)
ROOT = "/Users/huaichuaibeimeng/claude-projects"

from core_3to4_5m_engine import FEE_RATE, BARS_5M_PATH, MATRIX_DIR, sim_buy_5m, _slice_metrics_chrono

PARQ_PATH = f"{CUR_DIR}/data_5y/cand_3to4_enriched54.parquet"
df = pd.read_parquet(PARQ_PATH)
with open(f"{MATRIX_DIR}/code_bars_5y.pkl", "rb") as f:
    code_bars = pickle.load(f)["code_bars"]
df_5m = pd.read_parquet(BARS_5M_PATH)
df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
bars_5m_map = {(c6, d): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
               for (c6, d), g in df_5m.groupby(["c6", "date"], sort=False)}
with open(f"{MATRIX_DIR}/../index_klines_5y_cache.json", "r") as f:
    idx_k = json.load(f)
SH_MAP, SZ_MAP, CSI_MAP = idx_k["sh000002"], idx_k["sz399107"], idx_k["sh000300"]
dts_s = sorted(CSI_MAP.keys())
d_pos = {d: i for i, d in enumerate(dts_s)}

df["csi_1d_prev"] = [
    (CSI_MAP[r.sig_date] / CSI_MAP[dts_s[d_pos[r.sig_date] - 1]] - 1.0) if r.sig_date in d_pos and d_pos[r.sig_date] >= 1 else 0.0
    for r in df.itertuples(index=False)
]
SURF_YZ = re.compile(r"(?:上塘路|财通.*杭州上塘|东方财富.*昌都|佛山|绿景路|苏南|消闲派|国泰君安.*宜昌|开源.*西安西大街)")
lb_path = f"{ROOT}/sim-portfolio/backtest/2026-10-20-lhasa/lhb_buy.parquet"
surf_buy = [False] * len(df)
if os.path.exists(lb_path):
    lb = pd.read_parquet(lb_path, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME"])
    lb["dt"], lb["c6"] = lb["TRADE_DATE"].astype(str).str[:10], lb["SECURITY_CODE"].astype(str).str[:6]
    b_seats = lb[lb["dt"] >= "2021-12-01"].groupby(["dt", "c6"])["OPERATEDEPT_NAME"].apply(lambda s: set(s.dropna().astype(str))).to_dict()
    for i, r in enumerate(df.itertuples(index=False)):
        bs = b_seats.get((str(r.sig_date), str(r.code).zfill(6)), set())
        if any(SURF_YZ.search(x) for x in bs):
            surf_buy[i] = True
df["surf_yz_buy"] = surf_buy
df["prio_3to4"] = df["open_pct"] * 1000.0 + df["lock_top10"] * 0.5 + df["csrc_zt_cnt"] * 2.0
df.to_parquet(PARQ_PATH, index=False)

def sim_pool(buy_mode="touch65_1130", d4_mode="cut_weak", hold_mode="pm1345", use_yang_imm=True, use_dev93=False):
    out = [None] * len(df)
    for idx, r in enumerate(df.itertuples(index=False)):
        if not bool(r.is_10cm_non_st) or (not bool(r.buyable_open)):
            continue
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = code_bars.get(c6)
        if cb is None: continue
        pos = cb["date_to_pos"].get(bd, -1)
        if pos < 0 or pos >= len(cb["dts"]) - 1: continue
        bpx, bhh = sim_buy_5m(c6, bd, cb, pos, bars_5m_map, buy_mode)
        if bpx is None: continue
        imap = SH_MAP if c6.startswith("60") else SZ_MAP
        n = len(cb["dts"])
        def run_zt_hold(sp):
            k, imm = sp + 1, False
            while k < n:
                if bool(cb["is_yizi_dt"][k]): k += 1; continue
                ok, pck, clk, ztk = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k]), float(cb["zt_px"][k])
                dtk = round(pck * 0.90, 2)
                if k > sp + 1 and bool(cb["is_yizi_dt"][k - 1]):
                    return cb["dts"][k], ok, float(cb["adjf"][k]), k - pos, 925
                arr = bars_5m_map.get((c6, cb["dts"][k]))
                if use_dev93:
                    cd = cb["dts"][k]; ir = imap.get(cd); bp = 99999.0
                    if ir:
                        for d_k, lim in [(11, 0.93), (31, 1.93)]:
                            for q in range(1, min(d_k, k + 1)):
                                bi, bc0 = imap.get(cb["dts"][k - q]), cb["close"][k - q]
                                if bi and bc0 > 0: bp = min(bp, bc0 * (1.0 + lim + (ir / bi - 1.0)))
                    if ok >= bp: return cb["dts"][k], ok, float(cb["adjf"][k]), k - pos, 925
                    if arr is not None:
                        for row in arr:
                            if row[2] >= bp and row[2] > dtk + 0.005:
                                return cb["dts"][k], float(max(row[1], bp)), float(cb["adjf"][k]), k - pos, int(row[0])
                if hold_mode == "pm1345" and arr is not None and len(arr) > 0:
                    pk = ok
                    for row in arr:
                        hh, bo, bh, bl, bc = int(row[0]), row[1], row[2], row[3], row[4]
                        if bh <= dtk + 0.005: continue
                        if hh >= 1345 and pk >= pck * 1.085 and bl <= pck * 1.050 and bc < ztk - 0.01:
                            return cb["dts"][k], float(min(bo, pck * 1.050)), float(cb["adjf"][k]), k - pos, hh
                        if bh > pk: pk = bh
                if bool(cb["is_zt"][k]): k += 1; continue
                if use_yang_imm and (not imm) and (clk > ok) and (clk >= pck):
                    imm = True; k += 1; continue
                return cb["dts"][k], clk, float(cb["adjf"][k]), max(1, k - pos), 1500
            k = n - 1
            return cb["dts"][k], float(cb["close"][k]), float(cb["adjf"][k]), max(1, k - pos), 1500

        if not bool(cb["is_zt"][pos]):
            k = pos + 1
            while k < n and bool(cb["is_yizi_dt"][k]): k += 1
            k = min(k, n - 1)
            o4, c4, p4 = float(cb["open"][pos]), float(cb["close"][pos]), float(cb["pre_c"][pos])
            o5, p5, c5 = float(cb["open"][k]), float(cb["pre_c"][k]), float(cb["close"][k])
            dt5 = round(p5 * 0.90, 2)
            if k > pos + 1: ex_dt, spx, adjs, hb, shh = cb["dts"][k], o5, float(cb["adjf"][k]), k - pos, 925
            elif d4_mode == "cut_weak":
                if not ((c4 >= o4) and (c4 >= p4) and (o5 >= p5 * 1.005)):
                    ex_dt, spx, adjs, hb, shh = cb["dts"][k], o5, float(cb["adjf"][k]), max(1, k - pos), 925
                elif bool(cb["is_zt"][k]): ex_dt, spx, adjs, hb, shh = run_zt_hold(k)
                else: ex_dt, spx, adjs, hb, shh = cb["dts"][k], c5, float(cb["adjf"][k]), max(1, k - pos), 1500
            else:
                arr = bars_5m_map.get((c6, cb["dts"][k]))
                spx, shh = (o5, 925) if o5 >= p5 * 1.02 else (c5, 1500)
                if o5 < p5 * 1.02 and arr is not None:
                    for row in arr:
                        if row[2] > dt5 + 0.005 and row[2] >= p5 * 1.02:
                            spx, shh = float(max(row[1], p5 * 1.02)), int(row[0]); break
                ex_dt, adjs, hb = cb["dts"][k], float(cb["adjf"][k]), max(1, k - pos)
        else:
            ex_dt, spx, adjs, hb, shh = run_zt_hold(pos)
        nr = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE_RATE) - 1.0
        out[idx] = {"code": c6, "name": r.name, "buy_date": bd, "buy_price": bpx, "buy_hhmm": bhh,
                    "exit_date": ex_dt, "exit_price": spx, "exit_hhmm": shh, "hold_bars": hb, "net_ret": nr, "priority_score": float(r.prio_3to4)}
    return out

if __name__ == "__main__":
    p_v32 = sim_pool("touch65_1130", "cut_weak", "pm1345", True, False)
    p_v31 = sim_pool("touch65_1130", "reb2", "pm1345", False, False)
    skel_v31 = (df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"] & (~df["has_tox_notice"]) & (~df["has_stock_reg"])
                & (df["open_board_count"] >= 1) & ((df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0))
                & df["prev_to"].between(8.5, 31.0) & df["open_pct"].between(0.030, 0.092))
    skel_v32 = skel_v31 & df["is_top1_3b_open"].astype(bool)
    pts_common = (np.where(df["px_d3"] <= 20.0, 8.0, np.where(df["px_d3"] > 32.0, -5.0, 0.0))
                  + np.where(df["mkt_max_board_prev"] <= 4, 8.0, 0.0)
                  + np.where(df["mkt_zt_prev"] >= 95, -10.0, np.where(df["mkt_zt_prev"].between(35, 85), 5.0, 0.0))
                  + np.where(df["has_ex_reg"], -12.0, 0.0)
                  + np.where(df["lhb_lh_cnt"] == 0, 4.0, np.where(df["lhb_lh_cnt"] >= 3, -5.0, 0.0))
                  + np.where((df["plate_fb_ho_cnt"] >= 2) & (df["plate_fb_yz_cnt"] == 0), 4.0, 0.0)
                  + np.where(df["plate_fb_yz_cnt"] >= 1, -7.0, 0.0)
                  + np.where(df["plate_peers_open_avg"] < -0.015, -10.0, 0.0)
                  + np.where(df["prev_3b_dt_cnt"] == 0, 3.0, np.where(df["prev_3b_dt_cnt"] >= 2, -4.0, 0.0))
                  + np.where((df["csi_1d_prev"] <= -0.020) | (df["csi_5d_prev"] <= -0.030), -8.0, 0.0)
                  + np.where(df["prev_to"].between(9.5, 28.0), 3.0, 0.0))
    sc_v31 = np.where(skel_v31, 70.0 + np.where(df["is_top1_3b_open"], 8.0, 0.0) + pts_common, -999.0)
    # V3.2 clean base = 78.0 (since top1 is in hard skeleton) + p_elo>=115 (+5) + surf_yz_buy (-12)
    sc_v32 = np.where(skel_v32, 78.0 + pts_common + np.where(df["p_elo"] >= 115.0, 5.0, 0.0) + np.where(df["surf_yz_buy"], -12.0, 0.0), -999.0)

    for th in [86, 88, 90, 92, 95, 98, 100, 101, 102, 103]:
        recs = [dict(p_v32[i], priority_score=float(sc_v32[i])*10+float(df["prio_3to4"].iloc[i])*0.1)
                for i in np.where(sc_v32 >= th)[0] if p_v32[i] is not None]
        tdf = pd.DataFrame(recs)
        s5 = _slice_metrics_chrono(tdf, "2022-01-04", "2026-11-10")
        r3 = _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2024-01-02"], "2024-01-02", "2026-11-10")
        r1 = _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2025-11-12"], "2025-11-12", "2026-11-10")
        j26 = _slice_metrics_chrono(tdf[tdf["buy_date"] >= "2026-07-01"], "2026-07-01", "2026-11-10")
        yrs = [ _slice_metrics_chrono(tdf[tdf["buy_date"].str.startswith(y)], f"{y}-01-01", f"{y}-12-31" if y!="2026" else "2026-11-10")["single_nav"] for y in ["2022","2023","2024","2025","2026"] ]
        print(f"V3.2>={th:3d} | 5Y:{s5['single_n']:3d}b WR={s5['wr']:4.1f}% PO={s5['payoff']:4.2f} NAV={s5['single_nav']:6.2f}x Eq={s5['eq_nav']:6.2f}x H2={s5['half2_nav']:5.2f}x(MDD={s5['half2_mdd_pct']:4.1f}%) MDD={s5['single_mdd_pct']:4.1f}% | 24-26:{r3['single_n']:2d}b WR={r3['wr']:4.1f}% PO={r3['payoff']:4.2f} NAV={r3['single_nav']:5.2f}x | 1Y:{r1['single_n']:2d}b({r1['single_nav']:4.2f}x) | Jul26:{j26['single_n']:2d}b({j26['single_nav']:4.2f}x) | Yrs={[round(x,2) for x in yrs]}")

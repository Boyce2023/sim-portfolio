#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 2a: Granular 150+ factor scan (IS + OOS + 2026) across P1 (S1_DeepOpen), P2 (S3_BrokenYang), P3 (S4_ZhabanAntiNuke), P4 (S6_IRBreak)."""
import pickle, time
import numpy as np
import pandas as pd
from backtest_utils import simulate_fixed_hold

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def eval_slice(tr: pd.DataFrame, mask: np.ndarray) -> dict:
    sub = tr[mask]
    res = {}
    for w, sdt, edt in [("IS", "2021-01-04", "2024-08-31"), ("OOS", "2024-09-01", "2026-11-23"), ("2026", "2026-01-01", "2026-11-23")]:
        s = sub[(sub["buy_date"] >= sdt) & (sub["buy_date"] <= edt)]
        r = s["net_ret"].to_numpy(dtype=float)
        if len(r) == 0:
            res[w] = (0, 0.0, 0.0, 0.0, 1.0)
        else:
            wr = float((r > 0).mean() * 100.0)
            mn = float(r.mean() * 100.0)
            t = float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if (len(r) > 1 and r.std(ddof=1) > 0) else 0.0
            ew = float(np.prod(1.0 + s.groupby("buy_date")["net_ret"].mean().to_numpy(dtype=float)))
            res[w] = (int(len(r)), round(wr, 2), round(mn, 2), round(t, 2), round(ew, 3))
    return res


def factor_specs(proto: str) -> list:
    specs = [
        # Layer 1: Microstructure & Price/Position
        ("L1_open", "open<-8%", lambda d: d["f1_o_pct"] < -0.08),
        ("L1_open", "open[-8%,-5%)", lambda d: d["f1_o_pct"].between(-0.08, -0.050001)),
        ("L1_open", "open[-5%,-3%)", lambda d: d["f1_o_pct"].between(-0.05, -0.030001)),
        ("L1_open", "open[-3%,0%)", lambda d: d["f1_o_pct"].between(-0.03, -0.000001)),
        ("L1_open", "open[0%,+3%)", lambda d: d["f1_o_pct"].between(0.0, 0.029999)),
        ("L1_open", "open>=+3%", lambda d: d["f1_o_pct"] >= 0.03),
        ("L1_to", "to<8%", lambda d: d["to"] < 8.0),
        ("L1_to", "to[8%,15%)", lambda d: d["to"].between(8.0, 14.999)),
        ("L1_to", "to[15%,25%)", lambda d: d["to"].between(15.0, 24.999)),
        ("L1_to", "to[25%,35%)", lambda d: d["to"].between(25.0, 35.0)),
        ("L1_to", "to>35%", lambda d: d["to"] > 35.0),
        ("L1_volr5", "vol_ratio5<1.2", lambda d: d["vol_ratio5"] < 1.2),
        ("L1_volr5", "vol_ratio5[1.2,2.5)", lambda d: d["vol_ratio5"].between(1.2, 2.499)),
        ("L1_volr5", "vol_ratio5[2.5,4.5)", lambda d: d["vol_ratio5"].between(2.5, 4.499)),
        ("L1_volr5", "vol_ratio5>=4.5", lambda d: d["vol_ratio5"] >= 4.5),
        ("L1_pos20", "pos20<=0.40", lambda d: d["pos20"] <= 0.40),
        ("L1_pos20", "pos20(0.40,0.75]", lambda d: (d["pos20"] > 0.40) & (d["pos20"] <= 0.75)),
        ("L1_pos20", "pos20>0.75", lambda d: d["pos20"] > 0.75),
        ("L1_prev_pos20", "prev_pos20<=0.40", lambda d: d["prev_pos20"] <= 0.40),
        ("L1_prev_pos20", "prev_pos20(0.40,0.75]", lambda d: (d["prev_pos20"] > 0.40) & (d["prev_pos20"] <= 0.75)),
        ("L1_prev_pos20", "prev_pos20>0.75", lambda d: d["prev_pos20"] > 0.75),
        ("L1_pos60", "pos60<=0.45", lambda d: d["pos60"] <= 0.45),
        ("L1_pos60", "pos60>0.75", lambda d: d["pos60"] > 0.75),
        ("L1_bias20", "bias20<=0", lambda d: d["bias20"] <= 0),
        ("L1_bias20", "bias20(0,0.15]", lambda d: (d["bias20"] > 0) & (d["bias20"] <= 0.15)),
        ("L1_bias20", "bias20>0.15", lambda d: d["bias20"] > 0.15),
        ("L1_px", "close<=15", lambda d: d["close"] <= 15.0),
        ("L1_px", "close(15,35]", lambda d: (d["close"] > 15.0) & (d["close"] <= 35.0)),
        ("L1_px", "close>35", lambda d: d["close"] > 35.0),
        ("L1_candle", "true_yang=1", lambda d: d["is_true_yang"]),
        ("L1_candle", "true_yang=0", lambda d: ~d["is_true_yang"]),
        ("L1_candle", "close_pos>=0.70", lambda d: d["close_pos"] >= 0.70),
        ("L1_candle", "close_pos<=0.35", lambda d: d["close_pos"] <= 0.35),
        ("L1_candle", "upper_shad>0.05", lambda d: d["upper_shad"] > 0.05),
        ("L1_candle", "lower_shad>=0.03", lambda d: d["lower_shad"] >= 0.03),
        ("L1_candle", "amp>=0.15", lambda d: d["amp"] >= 0.15),
        ("L1_candle", "amp<0.08", lambda d: d["amp"] < 0.08),
        ("L1_prev", "prev_ret5<=0", lambda d: d["prev_ret5"] <= 0),
        ("L1_prev", "prev_ret5>0.15", lambda d: d["prev_ret5"] > 0.15),
        ("L1_prev", "zt_cnt_20d<=1", lambda d: d["zt_cnt_20d"] <= 1),
        ("L1_prev", "zt_cnt_20d>=2", lambda d: d["zt_cnt_20d"] >= 2),
        ("L1_prev", "zt_cnt_60d>=3", lambda d: d["zt_cnt_60d"] >= 3),
        ("L1_abn", "dist_3d30>=0.10(安全)", lambda d: d["dist_3d30"] >= 0.10),
        ("L1_abn", "dist_3d30<0.10(近异动)", lambda d: d["dist_3d30"] < 0.10),
        ("L1_abn", "dist_10d100<0.50(高异动)", lambda d: d["dist_10d100"] < 0.50),
        # Layer 2: Cap & Real Free Float
        ("L2_mcap", "mcap<=25亿", lambda d: d["mcap"] <= 25.0),
        ("L2_mcap", "mcap(25,60亿]", lambda d: (d["mcap"] > 25.0) & (d["mcap"] <= 60.0)),
        ("L2_mcap", "mcap(60,150亿]", lambda d: (d["mcap"] > 60.0) & (d["mcap"] <= 150.0)),
        ("L2_mcap", "mcap>150亿(大中军)", lambda d: d["mcap"] > 150.0),
        ("L2_lock", "lock_top10<35%", lambda d: d["lock_top10"] < 35.0),
        ("L2_lock", "lock_top10[35%,55%)", lambda d: d["lock_top10"].between(35.0, 54.999)),
        ("L2_lock", "lock_top10>=55%", lambda d: d["lock_top10"] >= 55.0),
        ("L2_rf_mcap", "rf_mcap<=20亿", lambda d: d["real_free_mcap"] <= 20.0),
        ("L2_rf_mcap", "rf_mcap(20,45亿]", lambda d: (d["real_free_mcap"] > 20.0) & (d["real_free_mcap"] <= 45.0)),
        ("L2_rf_mcap", "rf_mcap>80亿", lambda d: d["real_free_mcap"] > 80.0),
        ("L2_rf_to", "real_to<20%", lambda d: d["real_to"] < 20.0),
        ("L2_rf_to", "real_to[20%,45%)", lambda d: d["real_to"].between(20.0, 44.999)),
        ("L2_rf_to", "real_to>=45%", lambda d: d["real_to"] >= 45.0),
        # Layer 3: ZT Micro Tape
        ("L3_zt", "zt_hhmm<=1000", lambda d: d["zt_hhmm"] <= 1000),
        ("L3_zt", "zt_hhmm(1000,1130]", lambda d: (d["zt_hhmm"] > 1000) & (d["zt_hhmm"] <= 1130)),
        ("L3_zt", "zt_hhmm(1300,1430)", lambda d: (d["zt_hhmm"] >= 1300) & (d["zt_hhmm"] < 1430)),
        ("L3_zt", "zt_hhmm>=1430(尾盘)", lambda d: (d["zt_hhmm"] >= 1430) & (d["zt_hhmm"] < 9999)),
        ("L3_zt", "zt_obc==0(零炸)", lambda d: d["zt_obc"] == 0),
        ("L3_zt", "zt_obc>=1(回封)", lambda d: d["zt_obc"] >= 1),
        ("L3_zt", "zt_seal_ratio>=0.15", lambda d: d["zt_seal_ratio"] >= 0.15),
        ("L3_zt", "zt_seal_ratio<0.05", lambda d: (d["zt_seal_ratio"] > 0) & (d["zt_seal_ratio"] < 0.05)),
        # Layer 4: KPL & 10cm Synergy
        ("L4_kpl", "kpl_in==1", lambda d: d["kpl_in"] == 1),
        ("L4_kpl", "kpl_in==0", lambda d: d["kpl_in"] == 0),
        ("L4_kpl", "kpl_sz>=6(大主线)", lambda d: d["kpl_sz"] >= 6),
        ("L4_kpl", "kpl_hist_10zt>=4", lambda d: d["kpl_hist_10zt_max"] >= 4),
        ("L4_kpl", "kpl_hist_10yz>=1", lambda d: d["kpl_hist_10yz_max"] >= 1),
        ("L4_kpl", "kpl_20zt>=2", lambda d: d["kpl_20zt"] >= 2),
        ("L4_kpl", "kpl_elo>=115", lambda d: d["kpl_elo"] >= 115.0),
        ("L4_kpl", "kpl_peers_f1o<-1.5%", lambda d: d["kpl_peers_f1o"] < -0.015),
        ("L4_kpl", "kpl_peers_f1o>=+1.0%", lambda d: d["kpl_peers_f1o"] >= 0.01),
        # Layer 5: LHB / Inst / Lhasa / Youzi / Quant / Bayes
        ("L5_lhb", "lhb_has==1", lambda d: d["lhb_has"] == 1),
        ("L5_lhb", "lhb_has==0", lambda d: d["lhb_has"] == 0),
        ("L5_lhb", "lhb_inst_net>0", lambda d: d["lhb_inst_net"] > 0),
        ("L5_lhb", "lhb_inst_net>=2000w", lambda d: d["lhb_inst_net"] >= 2000),
        ("L5_lhb", "lhb_inst_net<0(机构卖)", lambda d: d["lhb_inst_net"] < 0),
        ("L5_lhb", "lhb_lh_cnt==0(零拉萨)", lambda d: (d["lhb_has"] == 1) & (d["lhb_lh_cnt"] == 0)),
        ("L5_lhb", "lhb_lh_cnt>=2(拉萨扎堆)", lambda d: d["lhb_lh_cnt"] >= 2),
        ("L5_lhb", "lhb_lh_share>=0.15", lambda d: d["lhb_lh_share"] >= 0.15),
        ("L5_lhb", "lhb_lh_net_pos==1", lambda d: d["lhb_lh_net_pos"] == 1),
        ("L5_lhb", "lhb_good_yz==1", lambda d: d["lhb_good_yz"] == 1),
        ("L5_lhb", "lhb_surf==1(一日游)", lambda d: d["lhb_surf"] == 1),
        ("L5_lhb", "lhb_quant>=1", lambda d: d["lhb_quant"] >= 1),
        ("L5_lhb", "lhb_north>0", lambda d: d["lhb_north"] > 0),
        ("L5_lhb", "bayes_t2>0.005", lambda d: d["bayes_t2"] > 0.005),
        ("L5_lhb", "bayes_t2<-0.005", lambda d: d["bayes_t2"] < -0.005),
        # Layer 6: Community Heat (Xueqiu & Guba)
        ("L6_comm", "xq_t1_pre==0(纯暗牌)", lambda d: d["xq_t1_pre"] == 0),
        ("L6_comm", "xq_t1_pre<4(暗牌)", lambda d: d["xq_t1_pre"] < 4),
        ("L6_comm", "xq_t1_pre>=4(过热)", lambda d: d["xq_t1_pre"] >= 4),
        ("L6_comm", "xq_3d_t1>=8", lambda d: d["xq_3d_t1"] >= 8),
        ("L6_comm", "gb_surge<1.5", lambda d: d["gb_surge"] < 1.5),
        ("L6_comm", "gb_surge>=3.5(人气暴增)", lambda d: d["gb_surge"] >= 3.5),
        # Layer 7: Cninfo Catalysts / Reg / IR / Tech
        ("L7_info", "reg_10d==1(监管函)", lambda d: d["reg_10d"] == 1),
        ("L7_info", "cat_earn_3d==1", lambda d: d["cat_earn_3d"] == 1),
        ("L7_info", "cat_any==1", lambda d: d["cat_any"] == 1),
        ("L7_info", "ir_10d>=1", lambda d: d["ir_10d"] >= 1),
        ("L7_info", "ir_30d>=2", lambda d: d["ir_30d"] >= 2),
        ("L7_info", "is_tech==1(硬科技)", lambda d: d["is_tech"] == 1),
        ("L7_info", "is_tech==0(非科技)", lambda d: d["is_tech"] == 0),
        # Layer 8: Market Regime & Calendar
        ("L8_mkt", "mkt20_zt<=5(20cm冰点)", lambda d: d["mkt20_zt_cnt"] <= 5),
        ("L8_mkt", "mkt20_zt[6,15](温热)", lambda d: d["mkt20_zt_cnt"].between(6, 15)),
        ("L8_mkt", "mkt20_zt>=16(过热)", lambda d: d["mkt20_zt_cnt"] >= 16),
        ("L8_mkt", "mkt10_zt<35", lambda d: d["mkt10_zt_cnt"] < 35),
        ("L8_mkt", "mkt10_zt[35,75]", lambda d: d["mkt10_zt_cnt"].between(35, 75)),
        ("L8_mkt", "mkt10_zt>75(高潮)", lambda d: d["mkt10_zt_cnt"] > 75),
        ("L8_mkt", "mkt10_dt>=15(恐慌)", lambda d: d["mkt10_dt_cnt"] >= 15),
        ("L8_mkt", "mkt20_ew<-1.5%", lambda d: d["mkt20_ew_ret"] < -0.015),
        ("L8_mkt", "mkt20_ew>=+1.5%", lambda d: d["mkt20_ew_ret"] >= 0.015),
        ("L8_mkt", "f1_0925_zt<10(竞价冰)", lambda d: d["f1_mkt10_0925_zt"] < 10),
        ("L8_mkt", "f1_0925_zt>=25(竞价热)", lambda d: d["f1_mkt10_0925_zt"] >= 25),
        ("L8_mkt", "f1_prev1b_open<0%", lambda d: d["f1_mkt10_prev1b_open"] < 0.0),
        ("L8_mkt", "f1_prev1b_open>=+1%", lambda d: d["f1_mkt10_prev1b_open"] >= 0.01),
        ("L8_mkt", "csi_5d<=-2%", lambda d: d["csi_5d"] <= -0.02),
        ("L8_mkt", "csi_5d>=+2%", lambda d: d["csi_5d"] >= 0.02),
        ("L8_cal", "weekday==Mon", lambda d: pd.to_datetime(d["f1_dt"]).dt.dayofweek == 0),
        ("L8_cal", "weekday==Fri", lambda d: pd.to_datetime(d["f1_dt"]).dt.dayofweek == 4),
        ("L8_cal", "month in (1,4)", lambda d: d["f1_dt"].str.slice(5, 7).isin(["01", "04"])),
        ("L8_cal", "month==5", lambda d: d["f1_dt"].str.slice(5, 7) == "05"),
    ]
    if proto == "P2_S3":
        specs.extend([
            ("L1_S3", "prev_streak==1", lambda d: d["prev_streak"] == 1),
            ("L1_S3", "prev_streak>=2", lambda d: d["prev_streak"] >= 2),
            ("L1_S3", "ret_d0<0(阴/假阴)", lambda d: d["ret"] < 0),
            ("L1_S3", "ret_d0[0,8%)", lambda d: d["ret"].between(0.0, 0.07999)),
            ("L1_S3", "ret_d0>=8%", lambda d: d["ret"] >= 0.08),
            ("L3_S3", "prev_zt_hhmm<=1030", lambda d: d["prev_zt_hhmm"] <= 1030),
            ("L3_S3", "prev_zt_obc==0", lambda d: d["prev_zt_obc"] == 0),
            ("L5_S3", "prev_lhb_lh_cnt==0", lambda d: d["prev_lhb_lh_cnt"] == 0),
        ])
    elif proto == "P3_S4":
        specs.extend([
            ("L1_S4", "ret_d0<0%", lambda d: d["ret"] < 0),
            ("L1_S4", "ret_d0[0%,+5%)", lambda d: d["ret"].between(0.0, 0.04999)),
            ("L1_S4", "ret_d0[+5%,+10%)", lambda d: d["ret"].between(0.05, 0.09999)),
            ("L1_S4", "ret_d0[+10%,+15%)", lambda d: d["ret"].between(0.10, 0.14999)),
        ])
    return specs


def run_proto_scan(all_rows: list, proto: str, pool: pd.DataFrame, hold: int):
    pool = pool.copy().reset_index(drop=True)
    pool["score"] = 0.0
    # Attach trade outcome aligned 1-to-1 with pool
    tr_list = []
    valid_idx = []
    for idx, r in enumerate(pool.itertuples(index=False)):
        if not r.f1_buyable or not r.f1_dt or np.isnan(r.f1_ao) or r.f1_ao <= 0:
            continue
        k = hold
        while k < 11 and not getattr(r, f"f{k}_sellable", False):
            k += 1
        while k >= 2 and np.isnan(getattr(r, f"f{k}_ac", np.nan)):
            k -= 1
        if k < 2:
            continue
        s_px = float(getattr(r, f"f{k}_ac"))
        s_dt = getattr(r, f"f{k}_dt")
        if not s_dt or np.isnan(s_px) or s_px <= 0:
            continue
        net = (s_px / float(r.f1_ao)) * 0.9970 - 1.0
        valid_idx.append(idx)
        tr_list.append({"sig_date": r.dt, "buy_date": r.f1_dt, "exit_date": s_dt, "c6": r.c6, "net_ret": net})

    sub_df = pool.iloc[valid_idx].reset_index(drop=True)
    tr_df = pd.DataFrame(tr_list)
    base_res = eval_slice(tr_df, np.ones(len(sub_df), dtype=bool))
    print(f"\n=== {proto} BASELINE: N_IS={base_res['IS'][0]} WR={base_res['IS'][1]}% mean={base_res['IS'][2]:+.2f}% t={base_res['IS'][3]:.2f} ew={base_res['IS'][4]:.3f}x | "
          f"OOS N={base_res['OOS'][0]} WR={base_res['OOS'][1]}% mean={base_res['OOS'][2]:+.2f}% t={base_res['OOS'][3]:.2f} ew={base_res['OOS'][4]:.3f}x | 2026 ew={base_res['2026'][4]:.3f}x ===")

    for grp, fname, fn in factor_specs(proto):
        m = np.asarray(fn(sub_df), dtype=bool)
        r = eval_slice(tr_df, m)
        is_n, is_wr, is_mn, is_t, is_ew = r["IS"]
        oos_n, oos_wr, oos_mn, oos_t, oos_ew = r["OOS"]
        y26_n, y26_wr, y26_mn, y26_t, y26_ew = r["2026"]
        all_rows.append({
            "proto": proto, "layer": grp, "factor": fname,
            "IS_N": is_n, "IS_WR": is_wr, "IS_mean": is_mn, "IS_t": is_t, "IS_ew": is_ew,
            "OOS_N": oos_n, "OOS_WR": oos_wr, "OOS_mean": oos_mn, "OOS_t": oos_t, "OOS_ew": oos_ew,
            "Y26_N": y26_n, "Y26_WR": y26_wr, "Y26_mean": y26_mn, "Y26_ew": y26_ew,
        })
        if is_n >= 20 and ((is_mn - base_res["IS"][2] >= 0.80) or (is_mn - base_res["IS"][2] <= -0.80)):
            print(f"  [{grp:9s}] {fname:24s} | IS: N={is_n:4d} WR={is_wr:5.1f}% mn={is_mn:+5.2f}% t={is_t:+5.2f} | OOS: N={oos_n:4d} WR={oos_wr:5.1f}% mn={oos_mn:+5.2f}% t={oos_t:+5.2f}")


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    # Attach prev day's zt & lhb fields for P2 (S3)
    g = df.groupby("c6", sort=False)
    df["prev_zt_hhmm"] = g["zt_hhmm"].shift(1).fillna(9999).astype(int)
    df["prev_zt_obc"] = g["zt_obc"].shift(1).fillna(-1).astype(int)
    df["prev_lhb_lh_cnt"] = g["lhb_lh_cnt"].shift(1).fillna(0).astype(int)
    import pickle
    aux = pickle.load(open(f"{OUT_DIR}/cache_20cm_aux.pkl", "rb"))
    mkt10 = aux["mkt10"]
    df["mkt10_dt_cnt"] = df["dt"].map({k: v["mkt10_dt_cnt"] for k, v in mkt10.items()}).fillna(0).astype(int)

    base = df[df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0) & (df["tox_90d"] == 0)].copy()
    all_rows = []

    # P1: S1 Deep Open First Board (T0 first ZT non-yizi, T+1 open < -2.0%)
    p1 = base[base["is_zt"] & (base["streak"] == 1) & (~base["is_yizi_zt"]) & (base["f1_o_pct"] < -0.02)]
    run_proto_scan(all_rows, "P1_S1", p1, hold=2)

    # P2: S3 Broken Board after ZT (T0 broken board after prev_streak>=1, T+1 open [-0.08, +0.04])
    p2 = base[(base["prev_streak"] >= 1) & (~base["is_zt"]) & (base["f1_o_pct"].between(-0.08, 0.04))]
    run_proto_scan(all_rows, "P2_S3", p2, hold=2)

    # P3: S4 Zhaban Anti-Nuke (T0 touched ZT & broke, ret < 0.15, T+1 open < -0.02)
    p3 = base[base["is_touch_zt"] & (~base["is_zt"]) & (base["ret"] < 0.15) & (base["f1_o_pct"] < -0.02)]
    run_proto_scan(all_rows, "P3_S4", p3, hold=2)

    # P4: S6 IR Break quick check (ir_10d >= 2, vol_ratio5 >= 1.5, bias20 > 0, T+1 open [-0.04, 0.03], hold T+3)
    p4 = base[(base["ir_10d"] >= 2) & (base["vol_ratio5"] >= 1.5) & (base["bias20"] > 0) & (base["f1_o_pct"].between(-0.04, 0.03))]
    run_proto_scan(all_rows, "P4_S6", p4, hold=3)

    out = pd.DataFrame(all_rows)
    out.to_csv(f"{OUT_DIR}/factor_scan_part2.csv", index=False)
    print(f"\n[DONE] Saved factor_scan_part2.csv ({len(out)} factor slices across 4 pools) in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

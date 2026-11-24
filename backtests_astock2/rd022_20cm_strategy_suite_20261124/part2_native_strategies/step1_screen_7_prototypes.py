#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Step 1: Screen all 7 native 20cm prototypes (S1-S7) across IS/OOS/2026/FULL with D15 metrics."""
import json, pickle, time
import numpy as np
import pandas as pd
from backtest_utils import calc_d15_suite, simulate_fixed_hold

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"


def run_case(cases_out: list, proto: str, name: str, sub: pd.DataFrame, entry: str, hold: int,
             sh300: dict, ew20_daily: dict, exit_rule: str = "fixed", score_col: str = "score"):
    if sub.empty:
        cases_out.append({"proto": proto, "variant": name, "entry": entry, "hold": hold, "raw_n": 0})
        return
    tr = simulate_fixed_hold(sub, entry, hold, fee=0.0030, exit_rule=exit_rule, score_col=score_col)
    m = calc_d15_suite(tr, sh300, ew20_daily)
    row = {"proto": proto, "variant": name, "entry": entry, "hold": hold, "exit_rule": exit_rule}
    for w in ("FULL", "IS", "OOS", "2026"):
        mw = m[w]
        row[f"{w}_rawN"] = mw.get("raw_n", 0)
        row[f"{w}_1sN"] = mw.get("n_1s", 0)
        row[f"{w}_1sWR"] = mw.get("wr_1s", 0.0)
        row[f"{w}_1sPO"] = mw.get("po_1s", 0.0)
        row[f"{w}_1sNAV"] = mw.get("nav_1s", 1.0)
        row[f"{w}_1sMDD"] = mw.get("mdd_1s", 0.0)
        row[f"{w}_3sNAV"] = mw.get("nav_3s", 1.0)
        row[f"{w}_ewNAV"] = mw.get("ew_nav", 1.0)
        row[f"{w}_exHS"] = mw.get("ex_hs300_1s", 0.0)
        row[f"{w}_exEW"] = mw.get("ex_ew20_1s", 0.0)
        row[f"{w}_ex5_1s"] = mw.get("ex5_1s", 1.0)
        row[f"{w}_fee50_1s"] = mw.get("fee50_1s", 1.0)
    cases_out.append(row)
    print(f"[{proto}] {name:38s} | IS: N={row['IS_1sN']:3d} WR={row['IS_1sWR']:5.1f}% 1s={row['IS_1sNAV']:6.2f}x 3s={row['IS_3sNAV']:5.2f}x | "
          f"OOS: N={row['OOS_1sN']:3d} WR={row['OOS_1sWR']:5.1f}% 1s={row['OOS_1sNAV']:6.2f}x 3s={row['OOS_3sNAV']:5.2f}x | "
          f"26: {row['2026_1sNAV']:5.2f}x")


def main():
    t0 = time.time()
    df = pd.read_parquet(f"{OUT_DIR}/cache_20cm_panel.parquet")
    aux = pickle.load(open(f"{OUT_DIR}/cache_20cm_aux.pkl", "rb"))
    sh300, ew20_daily = aux["sh300"], aux["ew20_daily"]
    base = df[df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0)].copy()
    base["score"] = base["ret"] * 100.0
    from backtest_utils import WINDOWS, bench_return, ew20_bench_return
    for wn, sdt, edt in WINDOWS:
        print(f"[BENCH {wn}] HS300={bench_return(sh300, sdt, edt)*100:+.2f}% | 20cm_EW={ew20_bench_return(ew20_daily, sdt, edt)*100:+.2f}%")
    cases = []

    # S1: 20cm 首板次日接力/弱转强 + 打板含炸板分母
    s1_zt = base[base["is_zt"] & (base["streak"] == 1) & (~base["is_yizi_zt"])].copy()
    s1_zt["score"] = (1000 - s1_zt["zt_hhmm"]) * 0.1 + s1_zt["kpl_10zt"] * 2.0
    run_case(cases, "S1", "S1_首板全部_T1开_持T2", s1_zt, "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S1", "S1_首板全部_T1开_持T3", s1_zt, "T1_open", 3, sh300, ew20_daily)
    for lbl, lo, hi in [("<-4%", -1, -0.04), ("-4~+2%", -0.04, 0.02), ("+2~+6%", 0.02, 0.06), ("+6~+12%", 0.06, 0.12), (">+12%", 0.12, 0.25)]:
        run_case(cases, "S1", f"S1_开盘{lbl}_T2", s1_zt[(s1_zt["f1_o_pct"] >= lo) & (s1_zt["f1_o_pct"] < hi)], "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S1", "S1_早盘封<1030_零炸_T2", s1_zt[(s1_zt["zt_hhmm"] <= 1030) & (s1_zt["zt_obc"] == 0)], "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S1", "S1_尾盘偷袭>=1430_T2", s1_zt[s1_zt["zt_hhmm"] >= 1430], "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S1", "S1_KPL主线+机构净买+无拉萨_T2", s1_zt[(s1_zt["kpl_in"] == 1) & (s1_zt["lhb_inst_net"] > 0) & (s1_zt["lhb_lh_cnt"] == 0)], "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S1", "S1_暗牌XQ<4+早封+弱转强0~6%_T2", s1_zt[(s1_zt["xq_t1_pre"] < 4) & (s1_zt["zt_hhmm"] <= 1130) & (s1_zt["f1_o_pct"].between(0.0, 0.06)) & (s1_zt["tox_90d"] == 0)], "T1_open", 2, sh300, ew20_daily)
    s1_hit = base[base["is_touch_zt"] & (base["prev_streak"] == 0) & (~base["is_yizi_zt"])].copy()
    s1_hit["score"] = s1_hit["kpl_10zt"] * 2.0 - s1_hit["pos20"] * 10.0
    run_case(cases, "S1", "S1_打板含炸板分母_持T1", s1_hit, "T0_hit_zt", 1, sh300, ew20_daily)
    run_case(cases, "S1", "S1_打板含炸板分母_持T2", s1_hit, "T0_hit_zt", 2, sh300, ew20_daily)

    # S2: 10cm 主线涨停潮 20cm 套利
    s2_t0_4 = base[(base["kpl_10zt"] >= 4) & (~base["is_zt"]) & (base["ret"].between(0.05, 0.15)) & (base["tox_t0_90d"] == 0)].copy()
    s2_t0_4["score"] = s2_t0_4["kpl_10zt"] * 5 + s2_t0_4["ret"] * 50
    run_case(cases, "S2", "S2_T0尾盘_10cm>=4_大阳5~15_T1", s2_t0_4, "T0_close", 1, sh300, ew20_daily)
    run_case(cases, "S2", "S2_T0尾盘_10cm>=4_大阳5~15_T2", s2_t0_4, "T0_close", 2, sh300, ew20_daily)
    s2_t0_6 = s2_t0_4[s2_t0_4["kpl_10zt"] >= 6]
    run_case(cases, "S2", "S2_T0尾盘_10cm>=6_大阳5~15_T2", s2_t0_6, "T0_close", 2, sh300, ew20_daily)
    s2_peer = base[(base["kpl_hist_10zt_max"] >= 4) & (~base["is_zt"]) & (base["ret"].between(0.03, 0.12)) & (base["pos20"] <= 0.60) & (base["tox_t0_90d"] == 0)].copy()
    s2_peer["score"] = s2_peer["kpl_hist_10zt_max"] * 5 - s2_peer["pos20"] * 20
    run_case(cases, "S2", "S2_T0尾盘_历史同题材10cm>=4低位_T2", s2_peer, "T0_close", 2, sh300, ew20_daily)
    s2_zt4 = s1_zt[s1_zt["kpl_10zt"] >= 4]
    run_case(cases, "S2", "S2_20cm首板_10cm>=4_T1开_T2", s2_zt4, "T1_open", 2, sh300, ew20_daily)
    s2_yz = s1_zt[(s1_zt["kpl_10yz"] >= 1) & (s1_zt["f1_o_pct"].between(-0.02, 0.06)) & (s1_zt["pos20"] <= 0.60)]
    run_case(cases, "S2", "S2_20cm首板_10cm一字>=1低位分歧_T2", s2_yz, "T1_open", 2, sh300, ew20_daily)
    s2_pm = base[(base["kpl_10yz"] >= 2) & (base["ret"].between(0.04, 0.19)) & (base["pos20"] <= 0.50) & (base["f1_o_pct"].between(-0.04, 0.05)) & (base["tox_90d"] == 0)].copy()
    s2_pm["score"] = s2_pm["kpl_10yz"] * 10 - s2_pm["pos20"] * 20
    run_case(cases, "S2", "S2_10cm一字>=2_低位20cm次日分歧_T2", s2_pm, "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S2", "S2_10cm一字>=2_低位20cm次日分歧_T3", s2_pm, "T1_open", 3, sh300, ew20_daily)

    # S3: 20cm 首板断板真阳首阴反包
    s3_all = base[(base["prev_streak"] >= 1) & (~base["is_zt"]) & (base["tox_90d"] == 0)].copy()
    s3_all["score"] = s3_all["prev_streak"] * 10 - s3_all["to"] * 0.2
    s3_ty = s3_all[s3_all["is_true_yang"] & (s3_all["to"] <= 35.0)]
    s3_1b_ty = s3_ty[s3_ty["prev_streak"] == 1]
    run_case(cases, "S3", "S3_断板真阳_全部T1开_T2", s3_ty, "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S3", "S3_首板真阳_平红开-2~+3%_T2", s3_1b_ty[s3_1b_ty["f1_o_pct"].between(-0.02, 0.03)], "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S3", "S3_首板真阳_绿开-6~0%_T2", s3_1b_ty[s3_1b_ty["f1_o_pct"].between(-0.06, 0.0)], "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S3", "S3_首板真阳_绿开-6~0%_T3", s3_1b_ty[s3_1b_ty["f1_o_pct"].between(-0.06, 0.0)], "T1_open", 3, sh300, ew20_daily)
    run_case(cases, "S3", "S3_断板真阳_红开0~5%_T2", s3_ty[s3_ty["f1_o_pct"].between(0.0, 0.05)], "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S3", "S3_断板真阳_绿开-6~0%_T2", s3_ty[s3_ty["f1_o_pct"].between(-0.06, 0.0)], "T1_open", 2, sh300, ew20_daily)
    s3_yin = s3_all[(~s3_all["is_true_yang"]) & (s3_all["ret"] > -0.08) & (s3_all["vol_ratio5"] < 1.5)]
    run_case(cases, "S3", "S3_断板缩量小阴_弱转强-3~+4%_T2", s3_yin[s3_yin["f1_o_pct"].between(-0.03, 0.04)], "T1_open", 2, sh300, ew20_daily)

    # S4: 20cm 炸板大振幅次日反核
    s4 = base[base["is_touch_zt"] & (~base["is_zt"]) & (base["tox_t0_90d"] == 0)].copy()
    s4["score"] = s4["ret"] * 100.0
    s4_hi = s4[s4["ret"] >= 0.10]
    s4_lo = s4[s4["ret"] < 0.10]
    run_case(cases, "S4", "S4_强炸10~19%_T0尾盘_T1", s4_hi, "T0_close", 1, sh300, ew20_daily)
    run_case(cases, "S4", "S4_强炸10~19%_T1开_T2", s4_hi, "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S4", "S4_弱炸<10%_T0尾盘_T1", s4_lo, "T0_close", 1, sh300, ew20_daily)
    run_case(cases, "S4", "S4_弱炸<10%_T1低开<-3%_T2", s4_lo[s4_lo["f1_o_pct"] < -0.03], "T1_open", 2, sh300, ew20_daily)
    run_case(cases, "S4", "S4_强炸_T1弱转强0~6%_T2", s4_hi[s4_hi["f1_o_pct"].between(0.0, 0.06)], "T1_open", 2, sh300, ew20_daily)

    # S5: 20cm 机构龙虎榜大买 + 趋势突破加速
    s5_base = base[(base["lhb_inst_net"] >= 3000) & (base["lhb_lh_cnt"] <= 1) & (base["tox_90d"] == 0)].copy()
    s5_base["score"] = s5_base["lhb_inst_net"] / 1000.0 + s5_base["vol_ratio5"]
    run_case(cases, "S5", "S5_机构>=3kw_无条件_T3", s5_base, "T1_open", 3, sh300, ew20_daily)
    run_case(cases, "S5", "S5_机构>=3kw_无条件_T5", s5_base, "T1_open", 5, sh300, ew20_daily)
    s5_brk = s5_base[(s5_base["bias20"] > 0) & (s5_base["high"] >= s5_base["high20_prev"]) & (s5_base["vol_ratio5"] >= 1.5)]
    run_case(cases, "S5", "S5_机构>=3kw+20日突破放量_T3", s5_brk, "T1_open", 3, sh300, ew20_daily)
    run_case(cases, "S5", "S5_机构>=3kw+20日突破放量_T5", s5_brk, "T1_open", 5, sh300, ew20_daily)
    run_case(cases, "S5", "S5_机构>=3kw+20日突破放量_T10", s5_brk, "T1_open", 10, sh300, ew20_daily)
    run_case(cases, "S5", "S5_机构>=3kw+20日突破_破MA5卖", s5_brk, "T1_open", 10, sh300, ew20_daily, exit_rule="ma5_break")
    s5_5k = s5_base[(s5_base["lhb_inst_net"] >= 5000) & (s5_base["bias20"] > 0) & (s5_base["high"] >= s5_base["high60_prev"])]
    run_case(cases, "S5", "S5_机构>=5kw+60日新高_T5", s5_5k, "T1_open", 5, sh300, ew20_daily)

    # S6: 20cm 公告/业绩预增/重大合同/机构调研事件驱动
    s6_base = base[(base["tox_90d"] == 0) & (base["reg_10d"] == 0)].copy()
    s6_base["score"] = s6_base["vol_ratio5"] + s6_base["ret"] * 20.0
    run_case(cases, "S6", "S6_业绩预增扭亏+放量站MA20_T5", s6_base[(s6_base["cat_earn_3d"] == 1) & (s6_base["vol_ratio5"] >= 1.5) & (s6_base["bias20"] > 0)], "T1_open", 5, sh300, ew20_daily)
    run_case(cases, "S6", "S6_重大合同+放量站MA20_T5", s6_base[(s6_base["cat_cont_3d"] == 1) & (s6_base["vol_ratio5"] >= 1.5) & (s6_base["bias20"] > 0)], "T1_open", 5, sh300, ew20_daily)
    run_case(cases, "S6", "S6_并购重组+放量_T5", s6_base[(s6_base["cat_ma_5d"] == 1) & (s6_base["vol_ratio5"] >= 1.5)], "T1_open", 5, sh300, ew20_daily)
    run_case(cases, "S6", "S6_硬催化任一+放量站MA20_T3", s6_base[(s6_base["cat_any"] == 1) & (s6_base["vol_ratio5"] >= 1.5) & (s6_base["bias20"] > 0)], "T1_open", 3, sh300, ew20_daily)
    run_case(cases, "S6", "S6_硬催化任一+放量站MA20_T10", s6_base[(s6_base["cat_any"] == 1) & (s6_base["vol_ratio5"] >= 1.5) & (s6_base["bias20"] > 0)], "T1_open", 10, sh300, ew20_daily)
    run_case(cases, "S6", "S6_机构调研10d>=2+放量突破_T5", s6_base[(s6_base["ir_10d"] >= 2) & (s6_base["vol_ratio5"] >= 1.8) & (s6_base["bias20"] > 0)], "T1_open", 5, sh300, ew20_daily)

    # S7: 20cm 急跌超跌强修复 (严格避开 DF022 连续跌停撬板!)
    s7_crash = base[(base["prev_ret5"] <= -0.20) | (base["prev_ret10"] <= -0.20)].copy()
    s7_crash = s7_crash[(s7_crash["prev_dt_streak"] < 2) & (~s7_crash["prev_is_yizi_dt"]) & (~s7_crash["is_dt"]) & (s7_crash["tox_t0_90d"] == 0)].copy()
    s7_reb = s7_crash[(s7_crash["ret"].between(0.05, 0.15)) & (s7_crash["vol_ratio5"] >= 1.3) & (s7_crash["is_true_yang"])].copy()
    s7_reb["score"] = -s7_reb["prev_ret10"].fillna(-0.2) * 50 + s7_reb["ret"] * 30
    run_case(cases, "S7", "S7_急跌20%后放量真阳5~15_T0尾_T2", s7_reb, "T0_close", 2, sh300, ew20_daily)
    run_case(cases, "S7", "S7_急跌20%后放量真阳5~15_T1开_T3", s7_reb, "T1_open", 3, sh300, ew20_daily)
    s7_inst = s7_crash[(s7_crash["ret"] > 0.03) & (s7_crash["lhb_inst_net"] >= 1000) & (s7_crash["tox_90d"] == 0)].copy()
    s7_inst["score"] = s7_inst["lhb_inst_net"] / 1000.0
    run_case(cases, "S7", "S7_急跌20%后机构龙虎榜>=1kw_T1开_T3", s7_inst, "T1_open", 3, sh300, ew20_daily)
    run_case(cases, "S7", "S7_急跌20%后机构龙虎榜>=1kw_T1开_T5", s7_inst, "T1_open", 5, sh300, ew20_daily)

    out_df = pd.DataFrame(cases)
    out_df.to_csv(f"{OUT_DIR}/part2_step1_screen_table.csv", index=False)
    with open(f"{OUT_DIR}/part2_step1_screen_summary.json", "w", encoding="utf-8") as f:
        json.dump(cases, f, ensure_ascii=False, indent=2)
    print(f"\n[DONE] Step 1 screened {len(cases)} variants in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

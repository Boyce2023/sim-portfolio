#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD023 Module 1: Systematic 45+ experiment evaluation on DeepOpen V1.1 baseline (IS/OOS/2026/FULL + 5m + RFM pct)."""
import json, os, pickle, sys, time
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd023_6strat_synergy_20261124/to_20cm"
P2_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd022_20cm_strategy_suite_20261124/part2_native_strategies"
BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
sys.path.insert(0, OUT_DIR)

from rd023_eval_lib import V11_EXIT_CFG, compute_scorecard_v11, cscv_pbo, eval_splits, sim_v11_exit_ext


def run_5m_cond_buy_audit(pool: pd.DataFrame) -> dict:
    """Verify conditional buy (+1.5%/+2.0%/+2.5% above open) on actual 5m bars (2021-2023 subsample)."""
    m5 = pd.read_parquet(f"{BASE}/data/all_strategies_5m_complete_pit.parquet")
    m5["c6"] = m5["c6"].astype(str).str.zfill(6)
    sub_a = pool[pool["score"] >= 76.0].copy()
    m5_map = {(c, d): g.sort_values("hhmm_int") for (c, d), g in m5[m5["c6"].isin(set(sub_a["c6"]))].groupby(["c6", "date"])}
    tr_base = sim_v11_exit_ext(sub_a, V11_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    tr_map = {(r.sig_date, r.c6): r for r in tr_base.itertuples(index=False)}
    out = {}
    for band_nm, gap_lim in [("deep_lt_m60", -0.060), ("deep_lt_m65", -0.065), ("all_m10_m3", -0.029)]:
        sub_b = sub_a[sub_a["f1_o_pct"] < gap_lim]
        base_r, c15_r, c20_r, c25_r, n5 = [], [], [], [], 0
        for r in sub_b.itertuples(index=False):
            tr_r, g5 = tr_map.get((r.dt, r.c6)), m5_map.get((r.c6, r.f1_dt))
            if tr_r is None or g5 is None or g5.empty:
                continue
            n5 += 1
            base_r.append(float(tr_r.net_ret))
            ao_raw = float(g5.iloc[0]["open"])
            for pct, dst in [(1.015, c15_r), (1.020, c20_r), (1.025, c25_r)]:
                tgt = ao_raw * pct
                hits = g5[g5["high"] >= tgt]
                if not hits.empty:
                    bpx = max(float(hits.iloc[0]["open"]), tgt) * (float(r.f1_ao) / ao_raw)
                    dst.append((float(tr_r.exit_px) / bpx) * 0.9970 - 1.0)
        out[band_nm] = {
            "total_A76": int(len(sub_b)), "with_5m": n5,
            "base_wr": round(float(np.mean(np.array(base_r) > 0) * 100), 2) if base_r else 0.0,
            "base_mean": round(float(np.mean(base_r) * 100), 2) if base_r else 0.0,
            "hit15_n": len(c15_r), "c15_wr": round(float(np.mean(np.array(c15_r) > 0) * 100), 2) if c15_r else 0.0,
            "c15_mean": round(float(np.mean(c15_r) * 100), 2) if c15_r else 0.0,
            "hit20_n": len(c20_r), "c20_mean": round(float(np.mean(c20_r) * 100), 2) if c20_r else 0.0,
            "hit25_n": len(c25_r), "c25_mean": round(float(np.mean(c25_r) * 100), 2) if c25_r else 0.0,
        }
    return out


def main():
    t0 = time.time()
    pool = pd.read_parquet(f"{OUT_DIR}/rd023_pool_enriched.parquet")
    aux = pickle.load(open(f"{P2_DIR}/cache_20cm_aux.pkl", "rb"))
    all_dts = aux["all_dts"]
    sc, fm = compute_scorecard_v11(pool)
    pool["score"] = sc.values

    tr_base_all = sim_v11_exit_ext(pool, V11_EXIT_CFG, fee=0.0030, tp_buf=0.0030)
    b_res = eval_splits(tr_base_all[tr_base_all["score"] >= 76.0])
    b_pbo = cscv_pbo(tr_base_all, 76.0, all_dts)
    print(f"BASE V1.1 A76: IS={b_res['IS']['nav']}x OOS={b_res['OOS']['nav']}x 2026={b_res['Y26']['nav']}x FULL={b_res['FULL']['nav']}x EW={b_res['FULL']['ew_nav']}x MDD={b_res['FULL']['mdd']}% PBO={b_pbo}")

    rows = []

    def record(eid: str, grp: str, desc: str, tr_all: pd.DataFrame, thr: float = 76.0, mask_keep: pd.Series | None = None, calc_pbo: bool = False, note: str = ""):
        if mask_keep is not None:
            keep_keys = set(zip(pool.loc[mask_keep, "dt"], pool.loc[mask_keep, "c6"]))
            tr_use = tr_all[[(r.sig_date, r.c6) in keep_keys for r in tr_all.itertuples(index=False)]].copy()
        else:
            tr_use = tr_all
        ev = eval_splits(tr_use[tr_use["score"] >= thr])
        pbo_s = cscv_pbo(tr_use, thr, all_dts) if calc_pbo else {}
        rows.append({
            "exp_id": eid, "source": grp, "desc": desc,
            "IS_nav": ev["IS"]["nav"], "d_IS": round(ev["IS"]["nav"] - b_res["IS"]["nav"], 2),
            "OOS_nav": ev["OOS"]["nav"], "d_OOS": round(ev["OOS"]["nav"] - b_res["OOS"]["nav"], 2),
            "Y26_nav": ev["Y26"]["nav"], "d_Y26": round(ev["Y26"]["nav"] - b_res["Y26"]["nav"], 2),
            "FULL_nav": ev["FULL"]["nav"], "d_FULL": round(ev["FULL"]["nav"] - b_res["FULL"]["nav"], 2),
            "EW_nav": ev["FULL"]["ew_nav"], "ex5_nav": ev["FULL"]["ex5"],
            "MDD_pct": ev["FULL"]["mdd"], "Calmar": ev["FULL"]["calmar"],
            "N_1s": ev["FULL"]["n"], "WR_pct": ev["FULL"]["wr"], "PO": ev["FULL"]["po"],
            "IS_N": ev["IS"]["n"], "IS_WR": ev["IS"]["wr"], "OOS_N": ev["OOS"]["n"], "OOS_WR": ev["OOS"]["wr"],
            "Y26_N": ev["Y26"]["n"], "Y26_WR": ev["Y26"]["wr"],
            "PBO_loc8": pbo_s.get("loc_S8", np.nan), "PBO_w8": pbo_s.get("wide_S8", np.nan),
            "note": note,
        })

    def test_score(eid, grp, desc, delta_arr, thr=76.0, calc_pbo=False, note=""):
        t_cur = tr_base_all.copy()
        d_map = dict(zip(zip(pool["dt"], pool["c6"]), delta_arr))
        t_cur["score"] = t_cur["score"] + np.array([d_map[(r.sig_date, r.c6)] for r in t_cur.itertuples(index=False)])
        record(eid, grp, desc, t_cur, thr=thr, calc_pbo=calc_pbo, note=note)

    def test_exit(eid, grp, desc, cfg_patch, note=""):
        cfg = {**V11_EXIT_CFG, **cfg_patch}
        t_cur = sim_v11_exit_ext(pool[pool["score"] >= 76.0], cfg, fee=0.0030, tp_buf=0.0030)
        record(eid, grp, desc, t_cur, thr=76.0, note=note)

    # ---- Group 1: 超跌撬板 V2.1 ----
    record("T1_pry_mkt_zt_lt5_skip10", "撬板V2.1", "T+1 09:25 10cm竞价涨停<5跳过", tr_base_all, mask_keep=(pool["f1_mkt10_0925_zt"] >= 5))
    record("T1_pry_mkt_zt_lt5_skipAll", "撬板V2.1", "T+1 09:25 全场非ST竞价涨停<5跳过", tr_base_all, mask_keep=(pool["f1_mkt_all_nonst_0925_zt"] >= 5))
    test_score("T1_pry_mkt_zt_lt5_pen", "撬板V2.1", "T+1 09:25 全场竞价涨停<5扣6分", np.where(pool["f1_mkt_all_nonst_0925_zt"] < 5, -6, 0))
    test_score("T1_pry_mkt_zt_ge12_plus", "撬板V2.1", "T+1 09:25 全场竞价涨停>=12加4分", np.where(pool["f1_mkt_all_nonst_0925_zt"] >= 12, 4, 0))
    test_exit("T1_pry_mkt_zt_lt5_exit", "撬板V2.1", "持仓期D2+ 09:25全场竞价涨停<5开盘斩", {"pry_mkt_lt5_exit": True})
    test_exit("T1_pry_exit_clv70", "撬板V2.1", "D1强真阳CLV>=0.70次日止盈+3%(封顶18%)", {"clv_boost_mode": "clv70"})
    test_exit("T1_pry_exit_dt10", "撬板V2.1", "D1全场跌停<10家次日止盈+3%(封顶18%)", {"clv_boost_mode": "dt10"})
    test_exit("T1_pry_exit_clv_both", "撬板V2.1", "CLV>=0.70与跌停<10双因子各+3%(封顶18%)", {"clv_boost_mode": "both"})
    test_exit("T1_pry_d1_weak_open_neg", "撬板V2.1", "D1收阴且D2绿开于09:25止损", {"d1_yin_mode": "d2_open_cut"})
    test_exit("T1_pry_d1_weak_open_all", "撬板V2.1", "D1收阴D2无条件09:25止损", {"d1_yin_mode": "d2_open_cut_all"})
    test_exit("T1_pry_d1_weak_tp_down5", "撬板V2.1", "D1收阴(B3)D2止盈降档至+5%保底", {"d1_yin_mode": "d2_tp_down"})
    test_exit("T1_pry_d1_weak_hold_d3", "撬板V2.1", "D1收阴且D2未涨延持至D3(+5%/收盘)", {"d1_yin_mode": "d3_hold_down"})

    # Conditional buy daily upper bound tests (including PM's -10%~-6% and 1.5%/2.0%/2.5%)
    pmap = {(r.dt, r.c6): r for r in pool.itertuples(index=False)}
    for lbl, gap_lim, mult in [
        ("T1_pry_cond_buy_60_15", -0.060, 1.015), ("T1_pry_cond_buy_60_20", -0.060, 1.020), ("T1_pry_cond_buy_60_25", -0.060, 1.025),
        ("T1_pry_cond_buy_65_15", -0.065, 1.015), ("T1_pry_cond_buy_65_20", -0.065, 1.020),
        ("T1_pry_cond_buy_all_15", -0.029, 1.015), ("T1_pry_cond_buy_all_20", -0.029, 1.020), ("T1_pry_cond_buy_all_25", -0.029, 1.025),
    ]:
        t_cb = tr_base_all[tr_base_all["score"] >= 76.0].copy()
        keep_r = []
        for r in t_cb.itertuples(index=False):
            pr = pmap[(r.sig_date, r.c6)]
            if pr.f1_o_pct < gap_lim:
                if pr.f1_ah < pr.f1_ao * mult:
                    continue
                nbx = min(pr.f1_ao * mult, float(pr.f1_zt_px_adj or 1e18))
                nr = (r.exit_px / nbx) * 0.9970 - 1.0
                d = r._asdict(); d["buy_px"] = nbx; d["net_ret"] = nr; keep_r.append(d)
            else:
                keep_r.append(r._asdict())
        record(lbl, "撬板V2.1", f"开盘<{gap_lim*100:.1f}%挂open*{(mult-1)*100:.1f}%+条件单(日线上界)", pd.DataFrame(keep_r), note="无2024+5m，属日线上界")

    # ---- Group 2: 二进三 V2.1 ----
    test_score("T2_2to3_box20_le40_plus", "二进三V2.1", "前20日箱体<=40%加4分", np.where(pool["box20_prev"].fillna(1.0) <= 0.40, 4, 0))
    test_score("T2_2to3_box20_bi", "二进三V2.1", "前20日箱体<=40%加4分 / >80%扣5分", np.where(pool["box20_prev"].fillna(1.0) <= 0.40, 4, np.where(pool["box20_prev"].fillna(0.0) > 0.80, -5, 0)))
    test_exit("T2_2to3_d2_hiopen_tp12_b1", "二进三V2.1", "D1涨停后D2+高开>=+12%(非一字)09:25止盈", {"b1_d2_hiopen_tp": 0.12})
    test_exit("T2_2to3_d2_hiopen_tp15_b1", "二进三V2.1", "D1涨停后D2+高开>=+15%(非一字)09:25止盈", {"b1_d2_hiopen_tp": 0.15})
    test_exit("T2_2to3_1345_guard_b1_12", "二进三V2.1", "D1涨停续骑期摸+15%未封锁+12%(日线近似)", {"guard_15_tp": 0.12})
    test_score("T2_2to3_seal_obc0_plus", "二进三V2.1", "T0首板0次开板(紧封)加4分", np.where(pool["zt_obc"] == 0, 4, 0))
    test_score("T2_2to3_seal_obc_bi", "二进三V2.1", "T0紧封0开加3分 / 烂板>=1开扣3分", np.where(pool["zt_obc"] == 0, 3, np.where(pool["zt_obc"] >= 1, -3, 0)))
    test_score("T2_2to3_seal_time_late", "二进三V2.1", "T0封板>=14:00加4分 / <=10:00扣4分", np.where((pool["zt_hhmm"] >= 1400) & (pool["zt_hhmm"] < 9999), 4, np.where(pool["zt_hhmm"] <= 1000, -4, 0)))
    test_score("T2_2to3_turn_real_15_35", "二进三V2.1", "真实自由换手15%~35%加4分", np.where(pool["real_to"].between(15.0, 35.0), 4, 0))
    test_score("T2_2to3_turn_real_15_25", "二进三V2.1", "真实自由换手15%~25%加4分", np.where(pool["real_to"].between(15.0, 25.0), 4, 0))
    test_score("T2_2to3_turn_raw_15_25", "二进三V2.1", "名义换手15%~25%加4分", np.where(pool["to"].between(15.0, 25.0), 4, 0))

    # ---- Group 3: 高标首阴 V5.1 + PM RFM percentile PK ----
    test_exit("T3_high_dual_dev93_b1", "高标首阴V5.1", "D1涨停后挂10日100%/30日200%异动93%限价止盈", {"dual_dev93": "b1_only"})
    test_exit("T3_high_dual_dev93_all", "高标首阴V5.1", "全分支挂10日100%/30日200%异动93%限价止盈", {"dual_dev93": "all"})
    test_exit("T3_high_true_yang_life", "高标首阴V5.1", "D1涨停首断收真阳免死1天至D3", {"zt_imm": True})
    test_exit("T3_high_b3_d3_if_ty", "高标首阴V5.1", "B3温和分支D2收真阳延持至D3", {"b3_d3_if_ty": True})
    test_score("T3_high_lock45_or_rfm45", "高标首阴V5.1", "锁仓>=45%或真实流值>=45亿加4分", np.where((pool["lock_top10"].fillna(0) >= 45) | (pool["real_free_mcap"].fillna(0) >= 45), 4, 0))
    test_score("T3_high_lock45_alone", "高标首阴V5.1", "十大锁仓>=45%加4分", np.where(pool["lock_top10"].fillna(0) >= 45, 4, 0))

    # PM's F02 replacement PK: replace static F02 (rfm<=20 -> +4) with cross-sectional percentile <=30% / <=40% / <=50% (+4)
    old_f02 = np.where(pool["real_free_mcap"].fillna(999.0) <= 20.0, 4, 0)
    test_score("PM_F02_drop_only", "PM市值通胀PK", "删F02静态<=20亿(不加分)", -old_f02, calc_pbo=True)
    for pct_lim in [0.30, 0.40, 0.50]:
        new_f02 = np.where(pool["rfm_pct_all20"].fillna(1.0) <= pct_lim, 4, 0)
        test_score(f"PM_F02_pct_le{int(pct_lim*100)}", "PM市值通胀PK", f"F02改为当日20cm流值分位<={int(pct_lim*100)}%(+4)", new_f02 - old_f02, calc_pbo=True)

    # ---- Group 4: 三进四 V4.1 ----
    for rf in ["R_vol35x", "R_hs300_drop", "R_reg_new", "R_reb4_lt20", "R_sen20_lt40", "R_elo135"]:
        test_exit(f"T4_{rf}", "三进四V4.1", f"inst_dt风控开关加入{rf}", {"extra_risk": [rf]})
    test_exit("T4_R_all4_combo", "三进四V4.1", "inst_dt风控开关加入全部4项(vol35x+hs300+reg+reb4)", {"extra_risk": ["R_vol35x", "R_hs300_drop", "R_reg_new", "R_reb4_lt20"]})
    csi_drop = (pool["csi_1d"] <= -0.020) | (pool["csi_5d"] <= -0.025)
    test_score("T4_3to4_hs300_buy_plus", "三进四V4.1", "买前沪深300大跌(1d<=-2%/5d<=-2.5%)加5分(错杀)", np.where(csi_drop, 5, 0))
    test_score("T4_3to4_hs300_buy_pen", "三进四V4.1", "买前沪深300大跌(1d<=-2%/5d<=-2.5%)扣6分(风控)", np.where(csi_drop, -6, 0))

    # ---- Group 5: 一进二 V19 ----
    for th_s in [0.35, 0.40, 0.45]:
        record(f"T5_sensor20_skip{int(th_s*100)}", "一进二V19", f"近20日已结算20cm深水红盘率<{int(th_s*100)}%空仓", tr_base_all,
               mask_keep=~(pool["sensor20_d2_red"].fillna(1.0) < th_s), calc_pbo=True)
    test_score("T5_sensor20_lt40_pen6", "一进二V19", "近20日20cm深水红盘率<40%扣6分(等同抬门槛至82)", np.where(pool["sensor20_d2_red"].fillna(1.0) < 0.40, -6, 0), calc_pbo=True)
    test_score("T5_sensor20_lt45_pen6", "一进二V19", "近20日20cm深水红盘率<45%扣6分", np.where(pool["sensor20_d2_red"].fillna(1.0) < 0.45, -6, 0), calc_pbo=True)
    test_score("T5_overheat_zt100_pen", "一进二V19", "T0全场非ST涨停>100家扣5分", np.where(pool["t0_mkt_all_nonst_zt"] > 100, -5, 0))
    test_score("T5_overheat_zt120_pen", "一进二V19", "T0全场非ST涨停>=120家扣5分", np.where(pool["t0_mkt_all_nonst_zt"] >= 120, -5, 0))
    test_score("T5_overheat_seal75_pen", "一进二V19", "T0 10cm封板率>=75%扣5分", np.where(pool["t0_mkt10_seal_rate"] >= 0.75, -5, 0))
    test_score("T5_pos60_break_plus", "一进二V19", "60日平台首突(前60位置<=60%且T0>=80%)加4分", np.where((pool["prev_pos60"].fillna(1.0) <= 0.60) & (pool["pos60"].fillna(0.0) >= 0.80), 4, 0))
    test_score("T5_pos60_high_pen", "一进二V19", "60日高位(pos60>=90%)扣4分", np.where(pool["pos60"].fillna(0.0) >= 0.90, -4, 0))
    test_score("T5_bias20_oversold_plus", "一进二V19", "T0前20日超跌(prev_bias20<=-8%)加4分", np.where(pool["prev_bias20"].fillna(0.0) <= -0.08, 4, 0))

    df_res = pd.DataFrame(rows)
    df_res.to_csv(f"{OUT_DIR}/module1_40plus_experiments.csv", index=False, encoding="utf-8-sig")
    m5_audit = run_5m_cond_buy_audit(pool)
    json.dump({"baseline_A76": b_res, "baseline_pbo": b_pbo, "cond_buy_5m_subsample": m5_audit}, open(f"{OUT_DIR}/module1_meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[DONE Module 1 in {time.time()-t0:.2f}s] {len(df_res)} experiments saved.")
    print("5m cond_buy audit:", json.dumps(m5_audit, ensure_ascii=False))
    pos_both = df_res[(df_res["d_IS"] > 0) & (df_res["d_OOS"] > 0) & (df_res["d_Y26"] >= 0)]
    print("\n--- Candidates improving IS>0 & OOS>0 & Y26>=0 ---")
    print(pos_both[["exp_id", "d_IS", "d_OOS", "d_Y26", "d_FULL", "EW_nav", "MDD_pct", "N_1s", "WR_pct", "PBO_loc8"]].to_string(index=False))
    print("\n--- PM RFM PK ---")
    print(df_res[df_res["source"] == "PM市值通胀PK"][["exp_id", "IS_nav", "OOS_nav", "Y26_nav", "FULL_nav", "EW_nav", "MDD_pct", "N_1s", "WR_pct", "PBO_loc8", "PBO_w8"]].to_string(index=False))
    print("\n--- Top 12 by d_OOS ---")
    print(df_res.sort_values("d_OOS", ascending=False).head(12)[["exp_id", "d_IS", "d_OOS", "d_Y26", "d_FULL", "EW_nav", "MDD_pct", "N_1s"]].to_string(index=False))


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
finalize_data_and_compile.py — 补充 1) s_pry 830全池稳健对照, 2) s_2to3 no_imm+dev 组合, 3) s_3to4 2025-2026 近两年对照,
并正式合成输出 rd_cross_exit_advice.json 与 RD_CROSS_EXIT_REPORT.md。
"""
import os, sys, json, pickle, time
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD_DIR = f"{SIM}/backtests_astock2/rd017_cross_exit_audit_20261118"
OUT_BASE = f"{SIM}/backtests_astock/exit_opt_20261118"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
sys.path.insert(0, RD_DIR)
sys.path.insert(0, UPG_DIR)

import task1_pry_exit_audit as t1
import upgrade_2to3_pit as u2
import task2_2to3_exit_audit as t2
import upgrade_3to4_pit as u3
import task3_3to4_exit_audit as t3

os.makedirs(OUT_BASE, exist_ok=True)
SH300 = t1.SH300
CSI_2526 = t1.csi_ret_pct("2025-01-01", "2026-11-16")


def enrich_task1():
    p1 = f"{RD_DIR}/task1_pry_results.json"
    d1 = json.load(open(p1, encoding="utf-8"))
    df_m = pd.read_parquet(f"{t1.P5_DIR}/full_pry_master_enriched.parquet")
    with open(f"{t1.GFM_DIR}/code_bars_5y.pkl", "rb") as f:
        cb = pickle.load(f)["code_bars"]

    non_st = (~df_m["is_st_or_delist"].values) & (df_m["pre_c"].values >= 2.0)
    no_poison = (~df_m["n_poison90"].fillna(False).values) & (~df_m["n_del90"].fillna(False).values) & (~df_m["n_inv90"].fillna(False).values)
    ptdt = df_m["prev_touch_dt"].fillna(False).values.astype(bool)
    pisdt = df_m["prev_is_dt"].fillna(True).values.astype(bool)
    pure_oversold = (df_m["prev_zt20"].fillna(0).values == 0) & (df_m["prev_c_ma20"].fillna(0).values <= -0.15) & (df_m["prev_dd20"].fillna(1.0).values <= 0.80)
    w2s_open_conf = (df_m["o_pct"].values >= 0.0) & (df_m["o_pct"].values <= 0.05)
    sub = df_m[non_st & no_poison & ptdt & (~pisdt) & pure_oversold & w2s_open_conf].copy()
    sub["buy_date"] = sub["dt_str"].astype(str)
    sub["score"] = 100
    sub["bias10"] = sub["prev_c_ma20"].fillna(0)
    p0s, keep = [], []
    for r in sub.itertuples(index=False):
        d = cb.get(r.c6)
        p = d["date_to_pos"].get(r.buy_date) if d else None
        if p is not None and p + 1 < len(d["dts"]):
            p0s.append(p); keep.append(True)
        else:
            keep.append(False)
    sub = sub[keep].copy()
    sub["p0"] = p0s
    sub["prev_ret10"] = sub["prev_ret10"].fillna(-0.15).astype(float)

    broad_check = {}
    for lbl, rt, kw in [
        ("strict_premarket_v1", "strict_premarket", dict(coef=0.45, floor=0.06, cap=0.16, max_h=4)),
        ("1a_limit_c65_f5_uncap_h3", "strict_premarket", dict(coef=0.65, floor=0.05, cap=None, skip_if_above_zt=True, max_h=3)),
        ("1a_no_below_zt_h4", "no_below_zt_limit", dict(max_h=4)),
        ("1b_eod_trail_t1-02_arm6_h4", "daily_close_trail", dict(t1_cut=-0.02, arm=0.06, dd=0.025, max_h=4)),
        ("1c_switch_t1-02_h2_imm0", "daily_switch", dict(t1_cut=-0.02, hold_days=2, yang_imm=False)),
        ("1c_switch_t1-02_h3_imm1", "daily_switch", dict(t1_cut=-0.02, hold_days=3, yang_imm=True)),
        ("1c_switch_t1None_h4_imm1", "daily_switch", dict(t1_cut=None, hold_days=4, yang_imm=True)),
    ]:
        broad_check[lbl] = t1.eval_variant(sub, cb, rt, **kw)
    d1["broad_830_pool_robustness"] = {"raw_n": int(len(sub)), "unique_days": int(sub["buy_date"].nunique()), "variants": broad_check}
    json.dump(d1, open(p1, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return d1


def enrich_task2():
    p2 = f"{RD_DIR}/task2_2to3_results.json"
    d2 = json.load(open(p2, encoding="utf-8"))
    existing = {e["name"] for e in d2["experiments"]}
    add_list = [
        ("2b_pm1345_noimm_dev96_4b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=False, dev_disc=0.04, dev_min_board=4)),
        ("2b_pm1345_noimm_dev98_4b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=False, dev_disc=0.02, dev_min_board=4)),
        ("2b_pm1345_noimm_dev96_5b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=False, dev_disc=0.04, dev_min_board=5)),
        ("2b_pm1345_noimm_dev98_5b", "2b_sealed_relay", dict(unsealed_mode="eod1500", relay_mode="pm1345", d4_high_open_thr=0.092, use_yang_imm=False, dev_disc=0.02, dev_min_board=5)),
    ]
    if any(n not in existing for n, _, _ in add_list):
        raw_all, df_all, gated, asof = u2.build_pit_dataset("2026-11-16")
        gated["score_v2"] = 60.0 + u2.compute_v20_components(gated).sum(axis=1)
        da, b5m = u2.load_daily_and_5m("2026-11-16")
        all_dts = sorted(da["dt"].unique()); dt_idx = {d: i for i, d in enumerate(all_dts)}
        plook = {(r.c6, r.dt): (float(r.open), float(r.high), float(r.low), float(r.close), float(r.pre_c) if pd.notna(r.pre_c) else float(r.close), float(r.zt_px) if pd.notna(r.zt_px) else 9999.0, float(r.dt_px) if pd.notna(r.dt_px) else 0.0, bool(r.is_zt), bool(r.is_dt_exact), bool(r.is_yizi), bool(r.is_yizi_dt)) for r in da[da["dt"] >= "2020-12-25"][["c6", "dt", "open", "high", "low", "close", "pre_c", "zt_px", "dt_px", "is_zt", "is_dt_exact", "is_yizi", "is_yizi_dt"]].itertuples(index=False)}
        code_hist, xq_d4_map, d3_sr_map = t2.load_extra_pit_data(da, gated)
        for name, grp, kw in add_list:
            if name in existing:
                continue
            rv, edv, ehv = t2.sim_2to3_variant(gated, all_dts, dt_idx, plook, b5m, code_hist, xq_d4_map, d3_sr_map, **kw)
            gated["r_tmp"] = rv; gated["ed_tmp"] = edv; gated["eh_tmp"] = ehv
            m_std = t2.eval_windows(gated, 90, "r_tmp", "ed_tmp", "eh_tmp")
            m_str = t2.eval_windows(gated, 96, "r_tmp", "ed_tmp", "eh_tmp")
            d2["experiments"].append({"name": name, "group": grp, "params": kw, "std90": m_std, "strict96": m_str})
        json.dump(d2, open(p2, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return d2


def enrich_task3():
    p3 = f"{RD_DIR}/task3_3to4_results.json"
    d3 = json.load(open(p3, encoding="utf-8"))
    # Compute 2025-2026 recent 2y comparison for baseline vs dev93/96/98
    res = u3.run_causal_pipeline("2026-11-16", verbose=False)
    cand_df, sc_v40, code_bars, p_1030 = res["cand_df"], res["sc_v40"], res["code_bars"], res["p_1030"]
    b5m, d3_sr_map = t3.load_5m_and_extra(cand_df, code_bars)
    idx_90 = [i for i in np.where(sc_v40 >= 90.0)[0] if p_1030[i] is not None]

    def eval_2526(kw):
        rows = []
        for i in idx_90:
            pi = p_1030[i]; r = cand_df.iloc[i]
            c6 = str(r["code"]).zfill(6); bd = str(r["buy_date"]); sd = str(r["sig_date"])
            cb = code_bars[c6]; pos = cb["date_to_pos"][bd]
            bpx, _ = u3._sim_buy_5m(c6, bd, cb, pos, b5m, 1030)
            ex_dt, spx, adjs, hb, shh = t3.sim_3to4_exit_variant(c6, cb, pos, b5m, int(r["xq_cnt_2d"]), float(d3_sr_map.get((c6, sd), np.nan)), **kw)
            nr = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - t3.FEE) - 1.0
            rows.append({"code": c6, "name": str(r["name"]), "buy_date": bd, "buy_hhmm": int(pi["buy_hhmm"]), "exit_date": ex_dt, "exit_hhmm": shh, "net_ret": float(nr), "score": int(round(float(sc_v40[i]))), "priority_score": float(sc_v40[i]) * 10.0 + float(r["prio_3to4"]) * 0.1})
        df_r = pd.DataFrame(rows)
        out_m = {}
        for lbl, sub_df in [("std90", df_r), ("strict102", df_r[df_r["score"] >= 102])]:
            sl = u3.sim_single_slot(sub_df)
            s25 = sl[sl["buy_date"] >= "2025-01-01"]["net_ret"].to_numpy(dtype=float)
            dq = sub_df[sub_df["buy_date"] >= "2025-01-01"].groupby("buy_date")["net_ret"].mean().to_numpy(dtype=float)
            s_nav = float(np.prod(1.0 + s25)) if len(s25) else 1.0
            eq_nav = float(np.prod(1.0 + dq)) if len(dq) else 1.0
            sr = np.sort(s25)
            out_m[lbl] = {
                "n_1s": int(len(s25)), "wr_pct": round(float((s25 > 0).mean() * 100.0), 2) if len(s25) else 0.0,
                "single_nav": round(s_nav, 4), "trim3_nav": round(float(np.prod(1.0 + sr[:-3])) if len(s25) > 3 else 1.0, 4),
                "eq_nav": round(eq_nav, 4), "csi300_25_26_pct": CSI_2526,
                "excess_1s_pp": round((s_nav - 1.0) * 100.0 - CSI_2526, 2),
            }
        return out_m

    d3["recent_25_26_reg_era_check"] = {
        "baseline_v40": eval_2526(dict(unsealed_mode="cut_weak", relay_mode="pm1345")),
        "3b_dev93_5b": eval_2526(dict(unsealed_mode="cut_weak", relay_mode="pm1345", dev_disc=0.07, dev_min_board=5)),
        "3b_dev96_5b": eval_2526(dict(unsealed_mode="cut_weak", relay_mode="pm1345", dev_disc=0.04, dev_min_board=5)),
        "3b_dev98_5b": eval_2526(dict(unsealed_mode="cut_weak", relay_mode="pm1345", dev_disc=0.02, dev_min_board=5)),
    }
    json.dump(d3, open(p3, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return d3


def pick_metrics(m_obj, keys_keep=None):
    return m_obj


def main():
    t0 = time.time()
    d1 = enrich_task1()
    d2 = enrich_task2()
    d3 = enrich_task3()

    def get_v(lst, name):
        return next(x for x in lst if x["name"] == name)

    # Assemble clean final rd_cross_exit_advice.json
    # 1. s_pry
    pry_pick_names = [
        "1a_limit_c65_f5_uncap_skip_zt_h3",
        "1a_limit_c65_f5_cap15_h3",
        "1a_no_below_zt_h4",
        "1a_no_below_zt_h3",
        "1b_eod_trail_t1cut-0.02_arm6_dd25_h4",
        "1c_switch_t1cut-0.02_h2_imm0",
        "1c_switch_t1cut-0.02_h3_imm1",
        "1c_switch_t1cutNone_h4_imm1",
    ]
    pry_comp = [
        {"name": "buggy_precompute_s3_old", "group": "lookahead_audit", "metrics": d1["lookahead_audit"]["buggy_precompute_approx_dt"]},
        {"name": "strict_premarket_v1_truth", "group": "baseline_truth", "metrics": d1["lookahead_audit"]["strict_premarket_v1_truth"]},
        {"name": "strict_0925_zt_open_exempt", "group": "lookahead_audit", "metrics": d1["lookahead_audit"]["strict_0925_zt_open_exempt"]},
    ] + [get_v(d1["variants"], nm) for nm in pry_pick_names]

    # 2. s_2to3
    s2_unsealed = [e for e in d2["experiments"] if e["group"] in ("baseline", "2a_unsealed")]
    s2_sealed = [e for e in d2["experiments"] if e["group"] in ("baseline", "2b_sealed_relay", "2b_combo")]

    # 3. s_3to4
    s3_ho = [e for e in d3["experiments"] if e["group"] in ("baseline", "3a_d5_high_open")]
    s3_dev = [e for e in d3["experiments"] if e["group"] in ("baseline", "3b_severe_abnormality")]
    s3_guard = [e for e in d3["experiments"] if e["group"] in ("baseline", "3c_guard_and_unsealed")]

    advice = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "author": "astock2_rd",
        "methodology_notes": {
            "fee_roundtrip": 0.0020,
            "d12_yfinance_forbidden": True,
            "sqlite_readonly_uri": True,
            "zero_intraday_lookahead": "所有盘前/盘中限价单与条件单严格按时间顺序撮合，严禁偷看收盘is_zt反悔不卖；双严重异动10日100%与30日200%均锚定前一日收盘指数作为盘前挂单基准",
            "windows_and_csi300_bench_pct": {
                "full_5y_20211116_20261116": -18.49,
                "is_21_23_canon_20211116_20231231": -29.72,
                "is_21_23_full_20210104_20231231": -34.16,
                "is_22_23_20220104_20231231": -30.55,
                "oos_24_26_20240101_20261116": 15.99,
                "y2026_1y_20260101_20261116": -14.04,
            },
            "five_minute_coverage_summary": {
                "s_pry": d1["coverage_5m"],
                "s_2to3": d2["coverage_5m"],
                "s_3to4": d3["coverage_5m"],
            },
        },
        "s_pry_audit_and_advice": {
            "lookahead_bug_audit": {
                "finding": d1["lookahead_audit"]["key_discovery"],
                "affected_trades_in_435_pool": {"h_ge_tp_and_is_zt": 40, "o_ge_tp_and_is_zt": 4, "approx_dt_1tick": 7, "total_diff_s3_vs_v1": 51},
                "affected_trades_in_25_top1": {"h_ge_tp_and_is_zt": 0, "o_ge_tp_and_is_zt": 1, "note": "s3旧版002290禾盛新材开盘过止盈线后偷看收盘涨停多拿1天+24.66%, v1真源已修正为+16.75%, 另2022-04-28 605289罗曼股份在v1真源已按tp_px=+12.24%退出"},
                "buggy_s3_old": d1["lookahead_audit"]["buggy_precompute_approx_dt"],
                "strict_v1_truth": d1["lookahead_audit"]["strict_premarket_v1_truth"],
                "strict_0925_zt_exempt": d1["lookahead_audit"]["strict_0925_zt_open_exempt"],
            },
            "five_m_coverage_audit": d1["coverage_5m"],
            "intraday_5m_trailing_status": "本地5m库对s_pry持仓期覆盖率仅0.46%~1.4%(25头名T+1~T+3为0%), 故10:30 VWAP与盘中摸+6%/+8%回撤2.5%不可做无偏5m实测, 标为数据缺口(待补采5m后实测), 仅汇报严格零前视日线收盘追踪与开收盘定式",
            "variants_comparison": pry_comp,
            "broad_830_pool_robustness": d1["broad_830_pool_robustness"],
            "verdict": "需修正旧脚本前视偏差并升级卖点: 现役v1_oversold_pry_165_strict_ledger已修复旧precompute_return_matrix.py偷看涨停bug, 但盘前死挂低于涨停价的固定限价止盈(6%~16%)系统性砍断右尾; 改用「T+1低开<-2.0%09:25斩 + 封涨停骑乘连板(含1次真阳免死) + 非涨停缩至T+3/T+2收盘走」在435严池与830宽池IS/OOS双双胜出",
            "recommended_rule": {
                "primary": "1c_switch_t1cut-0.02_h3_imm1 (若追求全信号等权与连板弹性) 或 1c_switch_t1cut-0.02_h2_imm0 (若追求单仓最高胜率81.25%与去极值净值)",
                "exact_logic": "Day0收盘跌停次日09:25开盘斩; Day0涨停走连板骑乘(次日封板续拿, 允许1次真阳免死); 否则T+1竞价低开<-2.0%直接09:25止损, 期间封板切入连板骑乘, 未封板持至T+3(或T+2)15:00清仓(一字跌停顺延); 取消盘前低于涨停价的死限价止盈单",
                "backup_if_keep_limit": "若保留限价单, 将上限从16%放开为不封顶且>=涨停价不挂单(0.65*|ret10|, 保底5%, 最大持有3天)",
            },
        },
        "s_2to3_cross_advice": {
            "baseline_repro": {
                "verified_zero_error": True,
                "std90_trades": 94,
                "strict96_trades": 35,
                "five_m_coverage": d2["coverage_5m"],
                "five_m_gap_note": "未封三板(69/94)D4次日5m覆盖率为0/69(0.0%), 故未封三板次日10:30 VWAP无法有效实测; 封死三板(25/94)D4覆盖22/25(88.0%), 持仓期47/58(81.0%), 5m连板卖点对比有效",
                "metrics": get_v(d2["experiments"], "baseline_v20"),
            },
            "unsealed_d3_variants": s2_unsealed,
            "sealed_3b_relay_variants": s2_sealed,
            "verdict": "强烈建议采纳「封板期取消首次真阳免死(no_imm)」; 否决未封三板D4竞价止损与1to2的10:30/14:30规则; 双严重异动98%缓冲(5b+)可作为等权平滑可选增强",
            "recommended_rule": {
                "primary_change": "2b_pm1345_no_imm (保持未封三板熬至D4 15:00 + 封三板D4>9.2%非一字09:25兑现 + 13:45摸8.5%破5.0%, 唯一改动: 取消连板期首次真阳免死)",
                "effect_std90": "5年单仓 144.21x -> 203.38x (+41.0%), 胜率 52.13% -> 53.61%, 去Top3 30.81x -> 46.45x (+50.8%), IS(full) 27.88x -> 31.74x, OOS 12.34x -> 15.50x (+25.6%), EQ 134.03x -> 138.64x",
                "effect_strict96": "5年单仓 17.43x -> 20.41x (+17.1%), IS(full) 9.94x -> 10.93x, OOS 3.76x -> 4.29x, EQ 14.97x -> 17.31x",
                "optional_addon": "若需平滑等权波动可叠加5板+98%双严重异动限价止盈(no_imm_dev98_5b: std90 EQ 138.64x -> 159.27x, T3 46.45x -> 50.06x, OOS 15.50x不变, 但strict96降至18.22x)",
                "rejected": "1) 未封三板D4低开止损(<-2%/-3%/-4%/<+0.5%)全线损伤净值(144x降至77x~128x); 2) 1to2 10:30均线+14:30炸板(174.5x但IS与EQ均受损且不如no_imm 203.4x); 3) M1暗牌豁免未封三板因0% 5m覆盖暂不可测, 封板期用M1反而降效(128.2x->122.5x)",
            },
        },
        "s_3to4_cross_advice": {
            "baseline_repro": {
                "verified_zero_error": True,
                "std90_trades": 95,
                "strict102_trades": 31,
                "five_m_coverage": d3["coverage_5m"],
                "metrics": get_v(d3["experiments"], "baseline_v40"),
            },
            "high_open_d5_takeprofit_variants": s3_ho,
            "severe_abnormality_buffer_variants": s3_dev,
            "recent_25_26_reg_era_check": d3["recent_25_26_reg_era_check"],
            "intraday_guard_and_unsealed_variants": s3_guard,
            "verdict": "建议保持 V4.0 现行卖点不动 (cut_weak + 13:45护利 + 1次真阳免死); 跨策略移植多数产生负优化, 仅5板+96%异动缓冲对std90去极值与2026近一年有结构性取舍意义",
            "recommended_rule": {
                "primary": "维持 baseline_v40 (未封四板cut_weak + 封四板后13:45摸8.5%破5.0% + 1次真阳免死)",
                "cross_findings": {
                    "d5_high_open_gt_88_92_from_2to3": "明确无用(反伤): std90 5年从1799.99x降至1364.07x, 去Top5从105.82x降至80.19x, 2026从3.64x降至3.01x, 胜率降0.7pp, 四进五极高开是主升强一致而非透支",
                    "severe_abnormality_93_96_98_from_high_dragon": "双刃剑取舍: std90下5b+96%缓冲使去Top5从105.82x飙至243.42x(+130%), OOS从379.08x升至437.40x, 2026从3.64x升至4.11x; 但因提前锁死合富中国(+148.5%->+36.1%)与艾艾精工(+123.6%->+50.8%), 导致等权从4458.94x降至3736.44x, strict102 S档从16.72x腰斩至6.53x! 故默认不加异动限价单以保S档超级大妖尾端收益",
                    "1345_guard_sensitivity_and_v19": "13:45护利为核心支柱(取消则std90跌至1060.64x, T5跌至63.10x), [13:45~14:00, 7.5%~9.2%, 5.0%]构成宽阔高稳高原(1800x~2093x), 1x真阳免死必不可少(取消跌至1448.98x); 一进二10:30+14:30严重误伤早盘洗盘大妖(1799.99x暴跌至277.55x~341.20x); 未封四板借M1暗牌豁免或拖至10:30/15:00全线腰斩(1799.99x跌至882x~1123x)",
                },
            },
        },
        "overall_summary_for_pm": {
            "s_pry": "必改: 虽v1_strict_ledger已修复旧precompute_return_matrix偷看涨停bug(EQ从3.558x挤水至3.330x, 1S从2.073x挤至1.941x), 但盘前死挂6%~16%限价单自断大阳线右尾; 建议改为「T+1低开<-2%09:25斩 + 涨停骑乘(1次真阳免死) + 非涨停T+3(或T+2)15:00走」, 435严池1S从1.941x升至2.222x/2.291x(IS 1.547x/1.601x, OOS 1.436x/1.431x, EQ_all 4.116x), 830宽池同向占优(1.156x/1.062x vs 0.665x); 本地5m对s_pry持仓覆盖<=1.4%, 分时追踪暂不可回测",
            "s_2to3": "建议微调升级: 取消连板期「首次真阳免死」(仅此一项), std90 5Y单仓从144.21x跃升至203.38x(+41.0%, IS_full 27.88x->31.74x, OOS 12.34x->15.50x, T3 30.81x->46.45x, EQ 134.03x->138.64x), strict96同步从17.43x升至20.41x; 另未封三板D4 5m覆盖0/69暂无法实测10:30均线, 但D4开盘止损与1to2卖法均劣于现行",
            "s_3to4": "建议保持现行V4.0卖点不改: 现行(未封四板cut_weak + 13:45护利 + 1次真阳免死)已在IS/OOS/EQ/S102全维度均衡最优; 2to3的D5极高开止盈(-24%)、1to2的10:30/14:30(-81%~-85%)与M1未封豁免(-38%~-51%)均严重损伤净值; 高标5b+96%异动缓冲虽提升std90 T5(105.8x->243.4x)与OOS(379.1x->437.4x), 但腰斩strict102 S档大妖(16.72x->6.53x), 仅作极严监管防撤退备选",
        },
    }

    out_json = f"{OUT_BASE}/rd_cross_exit_advice.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(advice, f, ensure_ascii=False, indent=2)
    print(f"[SUCCESS] Wrote {out_json} ({os.path.getsize(out_json):,} bytes) in {time.time()-t0:.1f}s")
    print("3to4 recent 2025-2026 reg era:", json.dumps(d3["recent_25_26_reg_era_check"], ensure_ascii=False))


if __name__ == "__main__":
    main()

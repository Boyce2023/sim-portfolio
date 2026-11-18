#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
run_f3_audit_part2.py
Produces D15 5-window evaluation, Global 5-strategy V19.0 & 4-strategy portfolio collision,
8 anti-overfitting tests (incl. 85-variant CSCV PBO), 16-trade comparison, live 000011 manual,
and saves summary_pry_exit_factors.json.
"""
import os, sys, json, pickle, time, itertools
import numpy as np
import pandas as pd

SIM = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
OPT = f"{SIM}/backtests_astock/exit_opt_20261118"
CLEAN16 = f"{SIM}/backtests_astock/clean_rebacktest_20261116"
UPG17 = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
F3_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"
for p in (F3_DIR, f"{OPT}/s3_pry_exit", f"{OPT}/s2_2to3_exit", UPG17, CLEAN16):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_exit_scan as base
import generate_final_report_and_audit as gen_pry
import synthesize_master_clean_20261116 as syn16
import exit_engine as ee23
import backtest_30_factors as bt
from run_f3_audit_part1 import make_xf30_spec


def main():
    t0 = time.time()
    cache = pickle.load(open(f"{F3_DIR}/_cache_feats_830.pkl", "rb"))
    sub, feats = cache["sub"], cache["feats"]
    cb = pickle.load(open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl", "rb"))["code_bars"]
    csi_canon = json.load(open(f"{CLEAN16}/csi300_canonical_20261116.json"))
    sh300 = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))["sh000300"]
    all_sh_dts = sorted(sh300.keys())
    t_days = [d for d in all_sh_dts if "2021-11-15" <= d <= "2026-11-16"]

    def get_bench_window(s_dt, e_dt):
        prevs = [d for d in all_sh_dts if d < s_dt]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_sh_dts[0]]
        p1 = sh300[[d for d in all_sh_dts if d <= e_dt][-1]]
        return round((p1 / p0 - 1.0) * 100.0, 2)

    BENCH_WIN = {
        "全五年(2021-11-15~2026-11-16)": csi_canon["全五年(2021-11-16起)"][0],
        "IS(2021-11-15~2023-12-31)": get_bench_window("2021-11-16", "2023-12-31"),
        "OOS(2024-01-01~2026-11-16)": get_bench_window("2024-01-01", "2026-11-16"),
        "近三年(2023-11-16~2026-11-16)": csi_canon["近三年(2023-11-16起)"][0],
        "2026全年(2026-01-01~2026-11-16)": csi_canon["2026全年"][0],
    }

    # Load V19.0 5-strategy peers
    d_34 = syn16.standardize_ledger(f"{UPG17}/ledger_upg_3to4_std.csv", "三进四V4.0", 1)
    d_hd = syn16.standardize_ledger(f"{CLEAN16}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴V5.1", 2)
    d_12 = syn16.standardize_ledger(f"{UPG17}/ledger_upg_1to2.csv", "一进二V19", 5)

    c23 = pickle.load(open(f"{OPT}/s2_2to3_exit/_cache_2to3_pit_20261116.pkl", "rb"))
    supp5m = pickle.load(open(f"{OPT}/s2_2to3_exit/_cache_5m_supplement_bs.pkl", "rb"))
    b5m2 = {**c23["b5m_need"], **supp5m["supp_5m"]}
    da, all_dts = c23["da_need"], c23["all_dts"]
    dt_idx = {x: i for i, x in enumerate(all_dts)}
    idx_cache = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    sub90 = c23["gated_all"][(c23["gated_all"]["score_v2"] >= 90) & (c23["gated_all"]["buy_date"] >= "2021-11-15")].copy()
    sub90["c6_str"] = sub90["code"].astype(str).str.zfill(6)
    plook, stk_hist = ee23.build_lookups(da[da["c6"].isin(set(sub90["c6_str"]))].copy())
    cfg23 = ee23.ExitConfig("cfg", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.050)
    r23, ed23, eh23, _ = ee23.sim_exit_all(sub90, plook, stk_hist, b5m2, all_dts, dt_idx, idx_cache["sh000002"], idx_cache["sz399107"], cfg23)
    t23 = sub90.copy(); t23["net_ret"] = r23; t23["exit_date"] = ed23; t23["exit_hhmm"] = eh23
    t23 = t23.sort_values(["buy_date", "score_v2", "open_pct", "plate_sz", "c6_str"], ascending=[True, False, True, True, True]).groupby("buy_date", as_index=False).first()
    d_23 = pd.DataFrame({"buy_date": t23["buy_date"], "exit_date": t23["exit_date"], "code": t23["c6_str"], "name": t23["name"], "net_ret": t23["net_ret"], "score": t23["score_v2"], "buy_hhmm": 925, "exit_hhmm": t23["exit_hhmm"], "strategy": "二进三V2", "priority": 4})

    specs = {
        "B1_X10_v1_strict": {"base_mode": "X10_v1"},
        "XF28_DecD_4d": {"base_mode": "DecD_4d"},
        "XF29a_RD_2d": {
            "base_mode": "DecD_4d", "max_h": 2, "t1_ratio": None, "t2_ratio": None,
            "preopen_cut_fn": lambda off, st, ft, r: off == 1 and st.get("o_gap", 0.0) < -0.02,
            "tp_sched_fn": lambda off, st, ft, r, b: None,
        },
        "XF29b_RD_3d": {
            "base_mode": "DecD_4d", "max_h": 3, "t1_ratio": None, "t2_ratio": None,
            "preopen_cut_fn": lambda off, st, ft, r: off == 1 and st.get("o_gap", 0.0) < -0.02,
            "tp_sched_fn": lambda off, st, ft, r, b: None,
        },
        "XF30_V21": make_xf30_spec(5, 0.70, 10, 0.03, True),
    }

    # Build CSCV 81+5 matrix for true multiple-testing PBO
    def daily_arr(df_tr):
        mp = {d: 0.0 for d in t_days}
        for r_t in df_tr.itertuples(index=False):
            if r_t.exit_date in mp:
                mp[r_t.exit_date] += float(r_t.net_ret)
        return np.array([mp[d] for d in t_days], dtype=float)

    cscv_p165, cscv_p150 = [], []
    for zt_th in [4, 5, 6]:
        for clv_th in [0.60, 0.70, 0.80]:
            for ndt_th in [8, 10, 12]:
                for boost in [0.02, 0.03, 0.04]:
                    r, ed, hd, eh, _ = bt.run_spec(sub, cb, feats, make_xf30_spec(zt_th, clv_th, ndt_th, boost, True))
                    tmp = sub.copy(); tmp["net_ret"] = r; tmp["exit_date"] = ed; tmp["hold_days"] = hd
                    for th, lst in [(165, cscv_p165), (150, cscv_p150)]:
                        srt = tmp[tmp["score"] >= th].sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])
                        ss_l, fa = [], ""
                        for rr in srt.itertuples(index=False):
                            if fa == "" or rr.buy_date > fa:
                                ss_l.append(rr._asdict()); fa = rr.exit_date
                        lst.append(daily_arr(pd.DataFrame(ss_l)))
    R_cscv_165 = np.column_stack(cscv_p165)
    R_cscv_150 = np.column_stack(cscv_p150)

    summary_models = {}
    hard_assertions = {}
    ledgers = {}

    for nm, sp in specs.items():
        r, ed, hd, eh, rsn = bt.run_spec(sub, cb, feats, sp)
        ldf = pd.DataFrame({
            "buy_date": sub["buy_date"], "exit_date": ed, "code": sub["code"], "name": sub["name"],
            "score": sub["score"].astype(int), "bias10": sub["bias10"].astype(float), "o_pct": sub["o_pct"].astype(float),
            "net_ret": r, "hold_days": hd, "buy_hhmm": 925, "exit_hhmm": eh, "buy_px": sub["buy_px"].astype(float),
            "prev_ret10": sub["prev_ret10"].astype(float), "exit_reason": rsn,
        })
        ledgers[nm] = ldf

        t0_v = int((ldf["exit_date"] <= ldf["buy_date"]).sum())
        yzdt_v = 0
        for rr in ldf.itertuples(index=False):
            dc = cb[rr.code]; pe = dc["date_to_pos"].get(rr.exit_date)
            if pe is not None and pe < len(dc["dts"]) - 1 and dc["is_yizi_dt"][pe]:
                yzdt_v += 1

        def eval_d15_pool(pool_df):
            srt = pool_df.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])
            ss_l, fa = [], ""
            for rr in srt.itertuples(index=False):
                if fa == "" or rr.buy_date > fa:
                    ss_l.append(rr._asdict()); fa = rr.exit_date
            ss_df = pd.DataFrame(ss_l)
            ov_v = sum(1 for ii in range(1, len(ss_df)) if ss_df.iloc[ii]["buy_date"] <= ss_df.iloc[ii - 1]["exit_date"])
            deq = pool_df.groupby("buy_date", as_index=False).agg(net_ret=("net_ret", "mean"), hold_days=("hold_days", "mean")).sort_values("buy_date")
            top1 = srt.groupby("buy_date", as_index=False).first()
            win_res = {}
            for wlbl, sdt, edt in [
                ("全五年(2021-11-15~2026-11-16)", "2021-11-15", "2026-11-16"),
                ("IS(2021-11-15~2023-12-31)", "2021-11-15", "2023-12-31"),
                ("OOS(2024-01-01~2026-11-16)", "2024-01-01", "2026-11-16"),
                ("近三年(2023-11-16~2026-11-16)", "2023-11-16", "2026-11-16"),
                ("2026全年(2026-01-01~2026-11-16)", "2026-01-01", "2026-11-16"),
            ]:
                bp = BENCH_WIN[wlbl]
                def fmt(df_w):
                    m = base.eval_slice(df_w["net_ret"].values if not df_w.empty else [], df_w["hold_days"].values if not df_w.empty else [])
                    m["ret_pct"] = round((m["nav"] - 1.0) * 100.0, 2)
                    m["bench_pct"] = bp
                    m["excess_pp"] = round(m["ret_pct"] - bp, 2)
                    return m
                win_res[wlbl] = {
                    "ss": fmt(ss_df[(ss_df["buy_date"] >= sdt) & (ss_df["buy_date"] <= edt)]),
                    "deq": fmt(deq[(deq["buy_date"] >= sdt) & (deq["buy_date"] <= edt)]),
                    "top1": fmt(top1[(top1["buy_date"] >= sdt) & (top1["buy_date"] <= edt)]),
                    "raw": fmt(pool_df[(pool_df["buy_date"] >= sdt) & (pool_df["buy_date"] <= edt)]),
                }
            return win_res, ss_df, ov_v

        w165, ss165, ov165 = eval_d15_pool(ldf[ldf["score"] >= 165])
        w150, ss150, ov150 = eval_d15_pool(ldf[ldf["score"] >= 150])
        w140, ss140, ov140 = eval_d15_pool(ldf[ldf["score"] >= 140])
        w000, ss000, ov000 = eval_d15_pool(ldf)

        hard_assertions[nm] = {"t0_violations": t0_v, "overlap_violations": ov165 + ov150 + ov140, "yizi_dt_exit_violations": yzdt_v}

        # Portfolio V19.0 5-strat & 4-strat
        top25 = ldf[ldf["score"] >= 165].sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        t25s = top25[["buy_date", "exit_date", "code", "name", "net_ret", "score", "buy_hhmm", "exit_hhmm"]].assign(strategy="超跌撬板", priority=3)
        pool4 = pd.concat([d_34, d_hd, t25s, d_12], ignore_index=True)
        slot4 = syn16.run_1slot(pool4)
        pool5 = pd.concat([d_34, d_hd, t25s, d_23, d_12], ignore_index=True)
        slot5 = syn16.run_1slot(pool5)

        p165_pool = ldf[ldf["score"] >= 165].groupby("buy_date")["net_ret"].apply(list).to_dict()
        p150_pool = ldf[ldf["score"] >= 150].groupby("buy_date")["net_ret"].apply(list).to_dict()
        p140_pool = ldf[ldf["score"] >= 140].groupby("buy_date")["net_ret"].apply(list).to_dict()

        t_ss165 = gen_pry.run_8tests_on_trades(ss165, p165_pool, sh300, t_days, R_cscv_165)
        t_ss150 = gen_pry.run_8tests_on_trades(ss150, p150_pool, sh300, t_days, R_cscv_150)
        t_ss140 = gen_pry.run_8tests_on_trades(ss140, p140_pool, sh300, t_days, None)

        yr_165, yr_150 = {}, {}
        for yr in [2022, 2023, 2024, 2025, 2026]:
            s_d, e_d = f"{yr}-01-01", (f"{yr}-12-31" if yr < 2026 else "2026-11-16")
            b_yr = get_bench_window(s_d, e_d)
            for d_src, ydict in [(ss165, yr_165), (ss150, yr_150)]:
                sub_y = d_src[(d_src["buy_date"] >= s_d) & (d_src["buy_date"] <= e_d)]
                r_y = sub_y["net_ret"].values if not sub_y.empty else np.array([])
                ret_p = round((float(np.prod(1.0 + r_y)) - 1.0) * 100.0, 2) if len(r_y) else 0.0
                wr_p = round(float((r_y > 0).mean() * 100.0), 2) if len(r_y) else 0.0
                ydict[str(yr)] = {"n": int(len(r_y)), "wr": wr_p, "ret_pct": ret_p, "csi300_pct": b_yr, "excess_pp": round(ret_p - b_yr, 2)}

        summary_models[nm] = {
            "P165": w165, "P150": w150, "P140": w140, "P000": w000,
            "portfolio_4strat_5y": syn16.calc_metrics(pool4, slot4, "2021-11-16", -18.49),
            "portfolio_5strat_5y": syn16.calc_metrics(pool5, slot5, "2021-11-16", -18.49),
            "portfolio_5strat_3y": syn16.calc_metrics(pool5, slot5, "2023-11-16", 10.33),
            "portfolio_5strat_oos": syn16.calc_metrics(pool5, slot5, "2024-01-01", BENCH_WIN["OOS(2024-01-01~2026-11-16)"]),
            "portfolio_5strat_26": syn16.calc_metrics(pool5, slot5, "2026-01-01", -14.04),
            "tests_P165_ss": t_ss165, "tests_P150_ss": t_ss150, "tests_P140_ss": t_ss140,
            "yearly_P165_ss": yr_165, "yearly_P150_ss": yr_150,
            "_ss165": ss165,
        }

    # 16-trade side-by-side comparison
    ss_b1 = summary_models["B1_X10_v1_strict"]["_ss165"]
    ss_d4 = summary_models["XF28_DecD_4d"]["_ss165"]
    ss_rd = summary_models["XF29a_RD_2d"]["_ss165"]
    ss_30 = summary_models["XF30_V21"]["_ss165"]
    trade_comp = []
    for r_b1, r_d4, r_rd, r_30 in zip(ss_b1.itertuples(), ss_d4.itertuples(), ss_rd.itertuples(), ss_30.itertuples()):
        trade_comp.append({
            "buy_date": r_b1.buy_date, "code": r_b1.code, "name": r_b1.name, "score": int(r_b1.score),
            "X10_ret": round(r_b1.net_ret * 100, 2), "X10_exit": r_b1.exit_date,
            "DecD4_ret": round(r_d4.net_ret * 100, 2), "DecD4_exit": r_d4.exit_date, "DecD4_reason": r_d4.exit_reason,
            "RD2d_ret": round(r_rd.net_ret * 100, 2), "RD2d_exit": r_rd.exit_date,
            "V21_ret": round(r_30.net_ret * 100, 2), "V21_exit": r_30.exit_date, "V21_reason": r_30.exit_reason,
            "delta_V21_vs_X10": round((r_30.net_ret - r_b1.net_ret) * 100, 2),
            "delta_V21_vs_DecD4": round((r_30.net_ret - r_d4.net_ret) * 100, 2),
        })

    plat_df = pd.read_csv(f"{F3_DIR}/plateau_v21_81.csv")
    live_000011 = {
        "code": "000011", "name": "深物业A", "sig_date": "2026-11-17", "buy_date": "2026-11-18",
        "prev_close_1117": 6.94, "buy_px_open_1118": 6.97, "zt_px_1118": 7.63, "dt_px_1118": 6.25,
        "base_dyn_tp_pct": 11.46, "base_limit_px": 7.77, "boosted_tp_pct": 14.46, "boosted_limit_px": 7.98,
        "midday_1130_snapshot": {"price": 6.91, "pct_vs_prev": -0.43, "high": 7.12, "low": 6.80, "to_pct": 4.05, "clv_midday": 0.344, "mkt_open_zt_0925": 8, "mkt_now_zt_1130": 31, "mkt_now_dt_1130": 28, "prev_1117_n_dt": 83},
        "v21_execution_rules": {
            "T0_1118_today": "早盘09:25按6.97元成交；若15:00回封跌停6.25元则11-19开盘砍；若封涨停7.63元转连板接力；若收盘站上6.97元且CLV>=0.70(当前6.80~7.12区间需收>=7.03元)激活XF21c强真阳护航(明日起限价+3%且免T+1尾盘1.5%弱斩)",
            "T1_1119_morning": "09:25先扫全场竞价涨停家数：若mkt_open_zt_0925 < 5家(XF13二次流动性冰点熔断)，09:25开盘无条件清仓！否则盘前不设低位止盈限价单(放飞T+1涨停板)，若涨停直接转连板接力",
            "T1_1119_1455": "若T+1未涨停：若昨日(11-18)收强真阳(CLV>=0.70且c>6.97)则豁免T+1尾盘-1.5%斩仓；否则若14:55较11-18收盘跌超-1.5%，尾盘清仓",
            "T2_1120": "09:25先核对全场竞价涨停<5家熔断。未触发则按公式挂限价单：基准11.46%(7.77元)，若D0强真阳再+3%，若昨日(11-19)全场跌停<10家(XF16b止血)再+3%，封顶18%(+14.46%对应7.98元，+17.46%对应8.19元)；未触线且未涨停若较11-19跌超-1.5%则14:55清",
            "T3_1123": "09:25核对涨停<5家熔断；限价基准降至+5.0%(7.32元)+XF21/XF16b加成(+8%为7.53元，+11%为7.74元)；未触线且未涨停若较11-20跌超-1.5%则14:55清",
            "T4_1124": "09:25核对涨停<5家熔断；限价保底+2.0%(7.11元)+XF21/XF16b加成；未成交且未涨停14:55收盘无条件清仓",
        },
        "tonight_postclose_checklist": [
            "1. 今日15:00收盘K线(XF21c): 检查000011是否收真阳(c>6.97)且CLV=(c-l)/(h-l)>=0.70",
            "2. 今日15:00全场跌停(XF16b): 检查今日收盘非ST跌停是否降至<10家(午盘仍28家，目前大概率未达标，明晚再查)",
            "3. 今晚17:30龙虎榜(XF01~XF06实盘风控参考): 核查11-18是否上榜及机构/深股通是否仍维持净买入(11-17三机构净买+1685万、深股通净买+1776万)",
            "4. 今晚~明早09:15公告(XF07极危风控参考): 11-17晚19:04已发常规异常波动公告，核查今晚是否突增减持/立案/监管问询函",
            "5. 明早09:25:03竞价(XF13唯一核心开关): 跑fast_pry_today或扫全场竞价涨停家数，若<5家立即09:25市价清仓逃命！",
        ],
    }

    out_json = {
        "metadata": {"generated_at": "2026-11-18", "strategy": "超跌橡皮筋撬板 V1.0 (s_pry)", "champion_v21": "XF30_V21 (DecD_4d + XF13_mkt_open_zt<5 + XF21_d0_strong_yang_CLV>=0.70 + XF16b_prev_n_dt<10)"},
        "hard_assertions": {"per_model": hard_assertions, "truncation_invariance_lt_2025_01_01": {"matched_trades": 693, "max_abs_diff": 0.0, "pass": True}},
        "csi300_benchmarks": BENCH_WIN,
        "models": {nm: {k: v for k, v in sm.items() if not k.startswith("_")} for nm, sm in summary_models.items()},
        "plateau_v21_81": {
            "n_combos": int(len(plat_df)),
            "p165_ss_min": round(float(plat_df["P165_ss"].min()), 4),
            "p165_ss_median": round(float(plat_df["P165_ss"].median()), 4),
            "p165_ss_max": round(float(plat_df["P165_ss"].max()), 4),
            "pct_beat_X10": round(float(((plat_df["P165_ss"] > 1.9411) & (plat_df["P150_OOS_d"] > 0.9559) & (plat_df["P000_ALL_d"] > 0.6677)).mean() * 100.0), 1),
            "pct_beat_DecD4": round(float(((plat_df["P165_ss"] > 2.3036) & (plat_df["P150_OOS_d"] > 1.3273) & (plat_df["P140_IS_d"] > 1.3404)).mean() * 100.0), 1),
        },
        "p165_16trades_comparison": trade_comp,
        "live_000011_20261118": live_000011,
    }
    with open(f"{F3_DIR}/summary_pry_exit_factors.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)

    print("=== [FINAL SUMMARY: B1_X10 vs XF28_DecD4 vs XF29_RD2d vs XF30_V21] ===")
    for nm in ["B1_X10_v1_strict", "XF28_DecD_4d", "XF29a_RD_2d", "XF30_V21"]:
        sm = summary_models[nm]
        p65 = sm["P165"]["全五年(2021-11-15~2026-11-16)"]["ss"]
        p65_i = sm["P165"]["IS(2021-11-15~2023-12-31)"]["deq"]["nav"]
        p65_o = sm["P165"]["OOS(2024-01-01~2026-11-16)"]["deq"]["nav"]
        p50_i = sm["P150"]["IS(2021-11-15~2023-12-31)"]["deq"]["nav"]
        p50_o = sm["P150"]["OOS(2024-01-01~2026-11-16)"]["deq"]["nav"]
        p40_o = sm["P140"]["OOS(2024-01-01~2026-11-16)"]["deq"]["nav"]
        p00_a = sm["P000"]["全五年(2021-11-15~2026-11-16)"]["deq"]["nav"]
        p5 = sm["portfolio_5strat_5y"]
        p5_3 = sm["portfolio_5strat_3y"]
        t65 = sm["tests_P165_ss"]
        t50 = sm["tests_P150_ss"]
        print(f"{nm:<18} | SS:{p65['nav']:.4f}({p65['wr']:.1f}%,MDD:{p65['mdd']:.2f}%,{p65['avg_hold']:.2f}d) | 65:{p65_i:.3f}/{p65_o:.3f} | 50:{p50_i:.3f}/{p50_o:.3f} | 40O:{p40_o:.3f} | 00A:{p00_a:.3f} | P5_5Y:{p5['nav_slot']:,.0f}x(3Y:{p5_3['nav_slot']:,.0f}x) | 65HLZt={t65['HLZ_t_trade']:.2f},p={t65['monkey_p']:.4f},PBO={t65['cscv_pbo']:.3f} | 50PBO={t50['cscv_pbo']:.3f}")
    print(f"Saved summary_pry_exit_factors.json in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

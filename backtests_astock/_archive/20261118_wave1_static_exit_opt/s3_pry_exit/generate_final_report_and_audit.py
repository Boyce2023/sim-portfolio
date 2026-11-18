#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
generate_final_report_and_audit.py
执行 Q8 Gate 2 全套八大防过拟合统计学检验、四大硬断言 (含 >=2025-01-01 截断不变性)、
D15 五大窗口与全局五顺位组合对比、逐笔交易明细、000011 实盘对比，并产出:
  - summary_pry_exit_opt.json
  - report_pry_exit_opt.md
"""
import os, sys, json, math, time, pickle, itertools
import numpy as np
import pandas as pd
import scipy.stats as stats
import pyarrow.dataset as ds

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s3_pry_exit"
CLEAN16 = f"{SIM}/backtests_astock/clean_rebacktest_20261116"
OUT23 = f"{SIM}/backtests_astock/clean_2to3_v10_20261117"

for p in (OUT_DIR, CLEAN16):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_exit_scan as base
import run_synthesis_scan as syn_mod
import synthesize_master_clean_20261116 as syn16


def make_dec_985(mh, t1_ratio=0.985, t2_ratio=0.985, t1_no_tp=True, sched_fn=None):
    def fn(d, p0, bpx, r):
        L = len(d["dts"])
        if p0 + 1 >= L or bpx <= 0:
            return np.nan, "", 0, 1455, "invalid"
        if d["is_zt"][p0]:
            rv, ed, hd = base.hold_zt_relay(d, p0, p0, bpx)
            return rv, ed, hd, 1455, "D0地天板连板接力"
        if d["close"][p0] <= d["dt_px"][p0] + 0.005:
            ps = base.first_sellable_day(d, p0 + 1)
            s_px = d["open"][ps] if d["open"][ps] > d["dt_px"][ps] + 0.005 else d["close"][ps]
            rv, ed, hd = base.ret_from_px(d, p0, ps, s_px, bpx)
            return rv, ed, hd, 925, "D0回封跌停T+1开盘砍仓"
        if sched_fn is not None:
            sched = sched_fn(r)
        else:
            tp2 = float(np.clip(0.45 * abs(r.prev_ret10), 0.06, 0.16))
            sched = [None if t1_no_tp else tp2, tp2, 0.05, 0.02]
        end_p = min(L - 1, p0 + mh)
        for si, k in enumerate(range(p0 + 1, end_p + 1), 1):
            if d["is_yizi_dt"][k]:
                continue
            tp_r = sched[min(si - 1, len(sched) - 1)]
            if tp_r is not None:
                tp_px = round(bpx * (1.0 + tp_r) * (d["adjf"][p0] / d["adjf"][k]), 2)
                if d["open"][k] >= tp_px:
                    rv, ed, hd = base.ret_from_px(d, p0, k, d["open"][k], bpx)
                    return rv, ed, hd, 925, f"T+{si}高开越过限价({tp_r*100:.1f}%)开盘成交"
                if d["high"][k] >= tp_px:
                    rv, ed, hd = base.ret_from_px(d, p0, k, tp_px, bpx)
                    return rv, ed, hd, 1455, f"T+{si}盘中触及限价({tp_r*100:.1f}%)止盈"
            if d["is_zt"][k]:
                rv, ed, hd = base.hold_zt_relay(d, p0, k, bpx)
                return rv, ed, hd, 1455, f"T+{si}封涨停未破限价转连板接力"
            if k < end_p:
                ck = d["close"][k] * d["adjf"][k] / d["adjf"][p0]
                cp = d["close"][k - 1] * d["adjf"][k - 1] / d["adjf"][p0]
                thr = t1_ratio if si == 1 else t2_ratio
                if thr is not None and ck < cp * thr:
                    if d["close"][k] > d["dt_px"][k] + 0.005:
                        rv, ed, hd = base.ret_from_px(d, p0, k, d["close"][k], bpx)
                        return rv, ed, hd, 1455, f"T+{si}收盘跌超{(1-thr)*100:.1f}%去弱清仓"
                    ps = base.first_sellable_day(d, k + 1)
                    s_px = d["open"][ps] if d["open"][ps] > d["dt_px"][ps] + 0.005 else d["close"][ps]
                    rv, ed, hd = base.ret_from_px(d, p0, ps, s_px, bpx)
                    return rv, ed, hd, 925, f"T+{si}跌停顺延次日开盘清仓"
        ps = base.first_sellable_day(d, end_p)
        if d["is_zt"][ps]:
            rv, ed, hd = base.hold_zt_relay(d, p0, ps, bpx)
            return rv, ed, hd, 1455, f"T+{mh}封涨停转连板接力"
        rv, ed, hd = base.ret_from_px(d, p0, ps, d["close"][ps], bpx)
        return rv, ed, hd, 1455, f"T+{mh}到期收盘清仓"
    return fn


def make_v1_strict():
    def fn(d, p0, bpx, r):
        L = len(d["dts"])
        if d["is_zt"][p0]:
            rv, ed, hd = base.hold_zt_relay(d, p0, p0, bpx)
            return rv, ed, hd, 1455, "D0地天板连板接力"
        if d["close"][p0] <= d["dt_px"][p0] + 0.005:
            ps = base.first_sellable_day(d, p0 + 1)
            s_px = d["open"][ps] if d["open"][ps] > d["dt_px"][ps] + 0.005 else d["close"][ps]
            rv, ed, hd = base.ret_from_px(d, p0, ps, s_px, bpx)
            return rv, ed, hd, 925, "D0回封跌停T+1开盘砍仓"
        dyn_tp = float(np.clip(0.45 * abs(r.prev_ret10), 0.06, 0.16))
        tp_px = round(bpx * (1.0 + dyn_tp), 2)
        end_p = min(L - 1, p0 + 4)
        for si, k in enumerate(range(p0 + 1, end_p + 1), 1):
            if d["is_yizi_dt"][k]:
                continue
            if d["open"][k] >= tp_px:
                rv, ed, hd = base.ret_from_px(d, p0, k, d["open"][k], bpx)
                return rv, ed, hd, 925, f"T+{si}高开越过X10限价({dyn_tp*100:.1f}%)开盘卖"
            if d["high"][k] >= tp_px:
                rv, ed, hd = base.ret_from_px(d, p0, k, tp_px, bpx)
                return rv, ed, hd, 1455, f"T+{si}盘中摸X10限价({dyn_tp*100:.1f}%)止盈"
        ps = base.first_sellable_day(d, end_p)
        rv, ed, hd = base.ret_from_px(d, p0, ps, d["close"][ps], bpx)
        return rv, ed, hd, 1455, "T+4到期收盘清仓"
    return fn


def make_phantom():
    def fn(d, p0, bpx, r):
        dyn_tp = float(np.clip(0.45 * abs(r.prev_ret10), 0.06, 0.16))
        rv, ed, hd = base.sim_limit_tp(d, p0, bpx, dyn_tp, 4, match_mode="phantom_s3_bug", use_adjf=False)
        return rv, ed, hd, 1455, "旧穿板幻觉口径"
    return fn


def make_x7():
    def fn(d, p0, bpx, r):
        rv, ed, hd = base.sim_x7_relay(d, p0, bpx)
        return rv, ed, hd, 1455, "X7涨停接力+弱斩"
    return fn


def make_ma10():
    def fn(d, p0, bpx, r):
        rv, ed, hd = base.sim_ma_regress(d, p0, bpx, ma_len=10, mult=0.95, min_protect=1.05, max_h=4)
        return rv, ed, hd, 1455, "MA10*0.95保底5%"
    return fn


def make_trail(bnd):
    def fn(d, p0, bpx, r):
        dyn_tp = float(np.clip(0.45 * abs(r.prev_ret10), 0.06, 0.16))
        rv, ed, hd = base.sim_trailing_pullback(d, p0, bpx, dyn_tp, 0.025, 4, bound=bnd)
        return rv, ed, hd, 1455, f"动态回落2.5%({bnd})"
    return fn


def calc_bailey_dsr(x: np.ndarray, M: int = 150) -> dict:
    T = len(x)
    if T <= 3:
        return {"SR_hat": 0.0, "SR_0": 0.0, "DSR_prob": 0.0}
    mean_v = float(np.mean(x))
    std_v = float(np.std(x, ddof=1))
    if std_v < 1e-12:
        return {"SR_hat": 0.0, "SR_0": 0.0, "DSR_prob": 0.0}
    SR_hat = mean_v / std_v
    skew_v = float(stats.skew(x, bias=False))
    kurt_p = float(stats.kurtosis(x, fisher=False, bias=False))
    if math.isnan(kurt_p) or kurt_p < 1.0:
        kurt_p = 3.0
    sigma_SR = 1.0 / np.sqrt(T - 1)
    gamma = 0.5772156649
    q1 = stats.norm.ppf(1.0 - 1.0 / max(M, 2))
    q2 = stats.norm.ppf(1.0 - 1.0 / (max(M, 2) * np.e))
    SR_0 = float(sigma_SR * ((1.0 - gamma) * q1 + gamma * q2))
    denom_sq = max(1e-12, 1.0 - skew_v * SR_hat + ((kurt_p - 1.0) / 4.0) * (SR_hat ** 2))
    z = (SR_hat - SR_0) * np.sqrt(T - 1) / np.sqrt(denom_sq)
    return {"SR_hat": round(SR_hat, 4), "SR_0": round(SR_0, 4), "DSR_prob": round(float(stats.norm.cdf(z)), 4)}


def run_8tests_on_trades(df_tr, pool_by_date, sh300, t_days, R_cscv_matrix=None, target_col_idx=0):
    """Run HLZ t, DSR, Monkey p, Bootstrap, CSCV PBO, Outlier removal, 2x/3x slip, Yearly."""
    all_sh_dts = sorted(sh300.keys())

    def bench_ret(bd, ed):
        prevs = [d for d in all_sh_dts if d < bd]
        if not prevs:
            return 0.0
        p0 = sh300[prevs[-1]]
        p1 = sh300.get(ed, sh300[all_sh_dts[-1]])
        return float(p1 / p0 - 1.0)

    if df_tr.empty:
        return {}
    rets = df_tr["net_ret"].to_numpy(dtype=float)
    ex_arr = np.array([float(r.net_ret) - bench_ret(str(r.buy_date), str(r.exit_date)) for r in df_tr.itertuples(index=False)], dtype=float)
    n = len(rets)
    mean_ex = float(np.mean(ex_arr))
    std_ex = float(np.std(ex_arr, ddof=1)) if n > 1 else 0.0
    t_trade = float((mean_ex / std_ex) * np.sqrt(n)) if std_ex > 1e-12 else 0.0
    dsr30 = calc_bailey_dsr(ex_arr, 30)
    dsr150 = calc_bailey_dsr(ex_arr, 150)

    # Daily series across 1213 days
    daily_map = {d: 0.0 for d in t_days}
    for r in df_tr.itertuples(index=False):
        ed = str(r.exit_date)
        if ed in daily_map:
            daily_map[ed] += float(r.net_ret)
    d_ser = np.array([daily_map[d] for d in t_days], dtype=float)
    t_daily = float(np.mean(d_ser) / np.std(d_ser, ddof=1) * np.sqrt(len(d_ser))) if np.std(d_ser, ddof=1) > 1e-12 else 0.0
    dsr150_d = calc_bailey_dsr(d_ser, 150)

    # Monkey permutation (5000x)
    rng = np.random.default_rng(20261118)
    cands_list = [np.array(pool_by_date.get(str(r.buy_date), [float(r.net_ret)]), dtype=float) for r in df_tr.itertuples(index=False)]
    mat = np.zeros((n, 5000), dtype=float)
    for i, c_arr in enumerate(cands_list):
        mat[i, :] = c_arr[rng.integers(0, len(c_arr), size=5000)]
    sim_means = np.mean(mat, axis=0)
    p_monkey = float((np.sum(sim_means >= np.mean(rets)) + 1) / 5001)

    # Bootstrap 5% CI (5000x)
    boot_m = np.array([np.mean(ex_arr[rng.integers(0, n, size=n)]) for _ in range(5000)], dtype=float)
    ci5 = float(np.percentile(boot_m, 5))

    # Outlier removal (ex-top3)
    s_sorted = np.sort(rets)
    ex3_nav = float(np.prod(1.0 + (s_sorted[:-3] if n > 3 else s_sorted)))

    # 2x / 3x slip
    nav_2x = float(np.prod(1.0 + rets - 0.0030))
    nav_3x = float(np.prod(1.0 + rets - 0.0060))

    # CSCV PBO if matrix provided
    pbo = None
    if R_cscv_matrix is not None:
        n_days = len(t_days)
        n_grp = 8
        gs = n_days // n_grp
        grps = [list(range(i * gs, (i + 1) * gs if i < n_grp - 1 else n_days)) for i in range(n_grp)]
        omegas = []
        for t_grps in itertools.combinations(range(n_grp), 4):
            tr_grps = [g for g in range(n_grp) if g not in t_grps]
            tr_i = [x for g in tr_grps for x in grps[g]]
            te_i = [x for g in t_grps for x in grps[g]]
            Rt, Re = R_cscv_matrix[tr_i, :], R_cscv_matrix[te_i, :]
            st_tr = np.std(Rt, axis=0, ddof=1)
            sr_tr = np.where(st_tr > 1e-12, np.mean(Rt, axis=0) / st_tr, 0.0)
            bv = int(np.argmax(sr_tr))
            st_te = np.std(Re, axis=0, ddof=1)
            sr_te = np.where(st_te > 1e-12, np.mean(Re, axis=0) / st_te, 0.0)
            omegas.append(float(np.mean(sr_te > sr_te[bv])))
        pbo = round(float(np.mean(np.array(omegas) > 0.50)), 4)

    return {
        "N": int(n),
        "sample_red_flag_lt30": bool(n < 30),
        "mean_excess_pct": round(mean_ex * 100.0, 2),
        "HLZ_t_trade": round(t_trade, 3),
        "HLZ_t_daily": round(t_daily, 3),
        "DSR_M30_trade": dsr30["DSR_prob"],
        "DSR_M150_trade": dsr150["DSR_prob"],
        "DSR_M150_daily": dsr150_d["DSR_prob"],
        "monkey_p": round(p_monkey, 5),
        "bootstrap_5pct_ci_pct": round(ci5 * 100.0, 2),
        "ex_top3_nav": round(ex3_nav, 4),
        "nav_2x_slip": round(nav_2x, 4),
        "nav_3x_slip": round(nav_3x, 4),
        "cscv_pbo": pbo,
    }


def main():
    t0 = time.time()
    df, cb, v1_ref, s3_ref, csi_canon, sh300, m5_map = base.load_all_data()
    sub = base.build_base_candidates(df, cb)
    all_sh_dts = sorted(sh300.keys())
    t_days = [d for d in all_sh_dts if "2021-11-15" <= d <= "2026-11-16"]

    def get_bench_window(s_dt, e_dt):
        prevs = [d for d in all_sh_dts if d < s_dt]
        p0 = sh300[prevs[-1]] if prevs else sh300[all_sh_dts[0]]
        sub_d = [d for d in all_sh_dts if d <= e_dt]
        p1 = sh300[sub_d[-1]]
        return round((p1 / p0 - 1.0) * 100.0, 2)

    BENCH_WIN = {
        "全五年(2021-11-15~2026-11-16)": csi_canon["全五年(2021-11-16起)"][0],
        "IS(2021-11-15~2023-12-31)": get_bench_window("2021-11-16", "2023-12-31"),
        "OOS(2024-01-01~2026-11-16)": get_bench_window("2024-01-01", "2026-11-16"),
        "近三年(2023-11-16~2026-11-16)": csi_canon["近三年(2023-11-16起)"][0],
        "2026全年(2026-01-01~2026-11-16)": csi_canon["2026全年"][0],
    }

    # Define core comparison models
    models = {
        "B0_X10_phantom_bug": make_phantom(),
        "B1_X10_v1_strict": make_v1_strict(),
        "S01_X7_exact_3d": make_x7(),
        "A_mh_x10_2d_ztr": make_dec_985(2, t1_ratio=None, t2_ratio=None, t1_no_tp=False),
        "D_MA10_m95_p105": make_ma10(),
        "B_trail_armDyn_pb25_neutral": make_trail("neutral"),
        "B_trail_armDyn_pb25_pess": make_trail("pess"),
        "DecD_2d_none": make_dec_985(2, t1_ratio=None, t2_ratio=None, t1_no_tp=True),
        "DecD_3d_t1_985_t2_985": make_dec_985(3, t1_ratio=0.985, t2_ratio=0.985, t1_no_tp=True),
        "DecD_4d_t1_985_t2_985": make_dec_985(4, t1_ratio=0.985, t2_ratio=0.985, t1_no_tp=True),
    }

    # Load 4 other strategies
    d_hd = syn16.standardize_ledger(f"{CLEAN16}/partA_high_3to4/ledger_base_high_v51.csv", "高标首阴", 1)
    d_34 = syn16.standardize_ledger(f"{CLEAN16}/partA_high_3to4/ledger_base_3to4_v34.csv", "三进四", 2)
    d_12 = syn16.standardize_ledger(f"{CLEAN16}/partB_1to2/ledger_base_1to2_v18.csv", "一进二", 4)
    d_23 = syn16.standardize_ledger(f"{OUT23}/candidates_2to3_v10_all_raw90.csv", "二进三90", 5)

    ledgers = {}
    summary_models = {}
    hard_assertions = {}

    # Build CSCV variant matrix across the 10 models + 6 perturbations of DecD
    cscv_variants_p150_ss = []
    cscv_variants_p165_ss = []

    for mname, mfn in models.items():
        rows = []
        for r in sub.itertuples(index=False):
            rv, ed, hd, eh, reason = mfn(cb[r.c6], r.p0, r.buy_px, r)
            rows.append({
                "buy_date": r.buy_date, "exit_date": ed, "code": r.code, "name": r.name,
                "score": int(r.score), "bias10": float(r.bias10), "o_pct": float(r.o_pct),
                "net_ret": float(rv), "hold_days": int(hd), "buy_hhmm": 925, "exit_hhmm": int(eh),
                "buy_px": float(r.buy_px), "prev_ret10": float(r.prev_ret10), "exit_reason": reason,
            })
        ldf = pd.DataFrame(rows)
        ledgers[mname] = ldf

        # Hard assertions per model
        t0_v = int((ldf["exit_date"] <= ldf["buy_date"]).sum())
        yzdt_v = 0
        for r_l in ldf.itertuples(index=False):
            d_c = cb[r_l.code]
            pe = d_c["date_to_pos"].get(r_l.exit_date)
            if pe is not None and pe < len(d_c["dts"]) - 1 and d_c["is_yizi_dt"][pe]:
                yzdt_v += 1

        # Evaluate P165, P150, P140 across D15 5 windows
        p165 = ldf[ldf["score"] >= 165].copy()
        p150 = ldf[ldf["score"] >= 150].copy()
        p140 = ldf[ldf["score"] >= 140].copy()

        def eval_d15_pool(pool_df):
            srt = pool_df.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])
            ss_list, free_after = [], ""
            for rr in srt.itertuples(index=False):
                if free_after == "" or rr.buy_date > free_after:
                    ss_list.append(rr._asdict())
                    free_after = rr.exit_date
            ss_df = pd.DataFrame(ss_list)
            ov_v = 0
            for ii in range(1, len(ss_df)):
                if ss_df.iloc[ii]["buy_date"] <= ss_df.iloc[ii - 1]["exit_date"]:
                    ov_v += 1

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
                b_pct = BENCH_WIN[wlbl]
                ss_w = ss_df[(ss_df["buy_date"] >= sdt) & (ss_df["buy_date"] <= edt)] if not ss_df.empty else ss_df
                deq_w = deq[(deq["buy_date"] >= sdt) & (deq["buy_date"] <= edt)]
                top1_w = top1[(top1["buy_date"] >= sdt) & (top1["buy_date"] <= edt)]
                raw_w = pool_df[(pool_df["buy_date"] >= sdt) & (pool_df["buy_date"] <= edt)]

                def fmt(df_w):
                    m = base.eval_slice(df_w["net_ret"].values if not df_w.empty else [], df_w["hold_days"].values if not df_w.empty else [])
                    m["ret_pct"] = round((m["nav"] - 1.0) * 100.0, 2)
                    m["bench_pct"] = b_pct
                    m["excess_pp"] = round(m["ret_pct"] - b_pct, 2)
                    return m

                win_res[wlbl] = {"ss": fmt(ss_w), "deq": fmt(deq_w), "top1": fmt(top1_w), "raw": fmt(raw_w)}
            return win_res, ss_df, deq, ov_v

        w165, ss165, deq165, ov165 = eval_d15_pool(p165)
        w150, ss150, deq150, ov150 = eval_d15_pool(p150)
        w140, ss140, deq140, ov140 = eval_d15_pool(p140)
        w000, ss000, deq000, ov000 = eval_d15_pool(ldf)

        hard_assertions[mname] = {
            "t0_violations": t0_v,
            "overlap_violations": ov165 + ov150 + ov140,
            "yizi_dt_exit_violations": yzdt_v,
        }

        # Portfolio impact (4-strat & 5-strat)
        top25 = p165.sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
        t25s = top25[["buy_date", "exit_date", "code", "name", "net_ret", "score", "buy_hhmm", "exit_hhmm"]].assign(strategy="超跌撬板", priority=3)
        pool4 = pd.concat([d_hd.assign(priority=1), d_34.assign(priority=2), t25s, d_12.assign(priority=4)], ignore_index=True)
        slot4 = syn16.run_1slot(pool4)
        m4_5y = syn16.calc_metrics(pool4, slot4, "2021-11-16", -18.49)

        pool5 = pd.concat([d_hd.assign(priority=1), d_34.assign(priority=2), t25s, d_12.assign(priority=4), d_23.assign(priority=5)], ignore_index=True)
        slot5 = syn16.run_1slot(pool5)
        m5_5y = syn16.calc_metrics(pool5, slot5, "2021-11-16", -18.49)
        m5_3y = syn16.calc_metrics(pool5, slot5, "2023-11-16", 10.33)
        m5_26 = syn16.calc_metrics(pool5, slot5, "2026-01-01", -14.04)

        # Build daily series for CSCV
        def daily_arr(df_tr):
            mp = {d: 0.0 for d in t_days}
            for r_t in df_tr.itertuples(index=False):
                if r_t.exit_date in mp:
                    mp[r_t.exit_date] += float(r_t.net_ret)
            return np.array([mp[d] for d in t_days], dtype=float)

        cscv_variants_p165_ss.append(daily_arr(ss165))
        cscv_variants_p150_ss.append(daily_arr(ss150))

        summary_models[mname] = {
            "P165": w165,
            "P150": w150,
            "P140": w140,
            "P000": w000,
            "portfolio_4strat": m4_5y,
            "portfolio_5strat_5y": m5_5y,
            "portfolio_5strat_3y": m5_3y,
            "portfolio_5strat_26": m5_26,
            "_ss165": ss165,
            "_ss150": ss150,
            "_deq150": deq150,
            "_ss140": ss140,
        }

    # Build pool dicts for monkey permutation
    R_cscv_165 = np.column_stack(cscv_variants_p165_ss)
    R_cscv_150 = np.column_stack(cscv_variants_p150_ss)

    for mname in models:
        ldf = ledgers[mname]
        pool165 = ldf[ldf["score"] >= 165].groupby("buy_date")["net_ret"].apply(list).to_dict()
        pool150 = ldf[ldf["score"] >= 150].groupby("buy_date")["net_ret"].apply(list).to_dict()
        pool140 = ldf[ldf["score"] >= 140].groupby("buy_date")["net_ret"].apply(list).to_dict()
        sm = summary_models[mname]
        t_ss165 = run_8tests_on_trades(sm["_ss165"], pool165, sh300, t_days, R_cscv_165)
        t_ss150 = run_8tests_on_trades(sm["_ss150"], pool150, sh300, t_days, R_cscv_150)
        t_ss140 = run_8tests_on_trades(sm["_ss140"], pool140, sh300, t_days, None)

        # Yearly breakdown on P165_ss and P150_ss
        yr_165, yr_150 = {}, {}
        for yr in [2022, 2023, 2024, 2025, 2026]:
            s_d, e_d = f"{yr}-01-01", (f"{yr}-12-31" if yr < 2026 else "2026-11-16")
            b_yr = get_bench_window(s_d, e_d)
            for tag, d_src, ydict in [("165", sm["_ss165"], yr_165), ("150", sm["_ss150"], yr_150)]:
                sub_y = d_src[(d_src["buy_date"] >= s_d) & (d_src["buy_date"] <= e_d)]
                r_y = sub_y["net_ret"].values if not sub_y.empty else np.array([])
                ret_p = round((float(np.prod(1.0 + r_y)) - 1.0) * 100.0, 2) if len(r_y) else 0.0
                wr_p = round(float((r_y > 0).mean() * 100.0), 2) if len(r_y) else 0.0
                ydict[str(yr)] = {"n": int(len(r_y)), "wr": wr_p, "ret_pct": ret_p, "csi300_pct": b_yr, "excess_pp": round(ret_p - b_yr, 2)}

        sm["tests_P165_ss"] = t_ss165
        sm["tests_P150_ss"] = t_ss150
        sm["tests_P140_ss"] = t_ss140
        sm["yearly_P165_ss"] = yr_165
        sm["yearly_P150_ss"] = yr_150

    # 3. Hard Truncation Invariance Test (Truncate strictly < 2025-01-01)
    print("[Hard Assertion] Running >= 2025-01-01 truncation invariance test...")
    cb_trunc = {}
    for c6, d_orig in cb.items():
        dts = d_orig["dts"]
        cut_len = 0
        for dt_s in dts:
            if dt_s < "2025-01-01":
                cut_len += 1
            else:
                break
        if cut_len == 0:
            continue
        d_new = {}
        for k, v in d_orig.items():
            if k == "date_to_pos":
                d_new[k] = {dt_s: idx for idx, dt_s in enumerate(dts[:cut_len])}
            elif isinstance(v, (np.ndarray, list)):
                d_new[k] = v[:cut_len]
            else:
                d_new[k] = v
        cb_trunc[c6] = d_new

    df_trunc = df[df["dt_str"] < "2025-01-01"].copy().reset_index(drop=True)
    sub_trunc = base.build_base_candidates(df_trunc, cb_trunc)
    fn_champ = models["DecD_4d_t1_985_t2_985"]
    ldf_full = ledgers["DecD_4d_t1_985_t2_985"]
    ldf_full_pre = ldf_full[ldf_full["exit_date"] < "2025-01-01"].copy()

    trunc_rows = []
    for r in sub_trunc.itertuples(index=False):
        rv, ed, hd, eh, _ = fn_champ(cb_trunc[r.c6], r.p0, r.buy_px, r)
        if ed and ed < "2025-01-01":
            trunc_rows.append({"buy_date": r.buy_date, "code": r.code, "net_ret_trunc": float(rv), "exit_date_trunc": ed})
    ldf_tr_pre = pd.DataFrame(trunc_rows)
    m_tr = ldf_full_pre.merge(ldf_tr_pre, on=["buy_date", "code"], how="outer")
    max_trunc_diff = float((m_tr["net_ret"] - m_tr["net_ret_trunc"]).abs().max())
    assert len(m_tr) == len(ldf_full_pre) and max_trunc_diff == 0.0, f"Truncation mismatch! {max_trunc_diff}"
    print(f"  [PASS] Truncation invariance (<2025-01-01): {len(m_tr)} rows matched, max_abs_diff = {max_trunc_diff}")

    # 4. Trade-by-trade 16 single-slot comparison (B1 vs DecD_4d vs DecD_2d vs X7)
    ss_b1 = summary_models["B1_X10_v1_strict"]["_ss165"]
    ss_champ = summary_models["DecD_4d_t1_985_t2_985"]["_ss165"]
    ss_2d = summary_models["DecD_2d_none"]["_ss165"]
    ss_x7 = summary_models["S01_X7_exact_3d"]["_ss165"]

    trade_comp = []
    for r_b1, r_ch in zip(ss_b1.itertuples(index=False), ss_champ.itertuples(index=False)):
        # Also look up same (buy_date, code) in DecD_2d and X7
        row_2d = ledgers["DecD_2d_none"][(ledgers["DecD_2d_none"]["buy_date"] == r_b1.buy_date) & (ledgers["DecD_2d_none"]["code"] == r_b1.code)].iloc[0]
        row_x7 = ledgers["S01_X7_exact_3d"][(ledgers["S01_X7_exact_3d"]["buy_date"] == r_b1.buy_date) & (ledgers["S01_X7_exact_3d"]["code"] == r_b1.code)].iloc[0]
        trade_comp.append({
            "buy_date": r_b1.buy_date, "code": r_b1.code, "name": r_b1.name, "score": int(r_b1.score), "buy_px": round(float(r_b1.buy_px), 2),
            "old_exit": r_b1.exit_date, "old_ret_pct": round(r_b1.net_ret * 100.0, 2), "old_hold": int(r_b1.hold_days), "old_reason": r_b1.exit_reason,
            "new_exit": r_ch.exit_date, "new_ret_pct": round(r_ch.net_ret * 100.0, 2), "new_hold": int(r_ch.hold_days), "new_reason": r_ch.exit_reason,
            "delta_pp": round((r_ch.net_ret - r_b1.net_ret) * 100.0, 2),
            "dec2d_ret_pct": round(float(row_2d["net_ret"]) * 100.0, 2), "dec2d_exit": str(row_2d["exit_date"]),
            "x7_ret_pct": round(float(row_x7["net_ret"]) * 100.0, 2), "x7_exit": str(row_x7["exit_date"]),
        })

    # 5. Live position 000011 (2026-11-18 open=6.97)
    df_11 = ds.dataset(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(
        columns=["date", "ticker", "close"],
        filter=(ds.field("date") >= pd.Timestamp("2026-09-15")) & (ds.field("ticker") == "000011.SZ")
    ).to_table().to_pandas().sort_values("date")
    c_arr = df_11["close"].values
    c_1117 = float(c_arr[-1])
    ret10_11 = c_1117 / float(c_arr[-11]) - 1.0
    ma5_1117 = float(np.mean(c_arr[-5:]))
    ma10_1117 = float(np.mean(c_arr[-10:]))
    bpx_11 = 6.97
    dyn_tp_11 = float(np.clip(0.45 * abs(ret10_11), 0.06, 0.16))
    tp_px_old = round(bpx_11 * (1.0 + dyn_tp_11), 2)
    zt_1118 = round(c_1117 * 1.10, 2)
    dt_1118 = round(c_1117 * 0.90, 2)
    live_000011 = {
        "code": "000011", "name": "深物业A", "sig_date": "2026-11-17", "buy_date": "2026-11-18",
        "prev_close_1117": c_1117, "buy_px_open_1118": bpx_11, "o_pct_1118": round((bpx_11 / c_1117 - 1.0) * 100.0, 2),
        "zt_px_1118": zt_1118, "dt_px_1118": dt_1118, "ret10_pct": round(ret10_11 * 100.0, 2),
        "old_X10_dyn_tp_pct": round(dyn_tp_11 * 100.0, 2), "old_X10_limit_px": tp_px_old,
        "old_X10_action": f"今日(11-18)若封涨停则接力；否则明日(11-19)盘前挂死限价卖单 {tp_px_old:.2f} 元(+11.46%)，连挂T+1~T+4最多4天，未摸线则第4天(11-24)收盘清仓",
        "new_DecD4_action": {
            "T0_1118": f"开盘{bpx_11:.2f}买入；若收盘跌停({dt_1118:.2f})则T+1开盘砍；若收盘涨停({zt_1118:.2f})转连板接力；否则持仓过夜",
            "T1_1119": f"盘前不挂低位限价单(放飞T+1涨停板！若T+1涨停则直接转连板接力直至断板)；若未涨停且14:55跌破11-18收盘价的98.5%(即跌超-1.5%)，尾盘14:55去弱清仓",
            "T2_1120": f"若前日未出，盘前挂动态限价卖单 {tp_px_old:.2f} 元(+11.46%)；若未成交且封涨停转连板，否则若14:55较前日跌超-1.5%清仓",
            "T3_1123": f"若仍持有，盘前挂阶梯限价卖单 {round(bpx_11*1.05, 2):.2f} 元(+5.00%)；若14:55较前日跌超-1.5%清仓",
            "T4_1124": f"若仍持有，盘前挂保底限价卖单 {round(bpx_11*1.02, 2):.2f} 元(+2.00%)；未成交则14:55收盘无条件清仓(封涨停除外)",
        },
        "alt_DecD2_action": f"T+1(11-19)不设上限(涨停接力)，T+2(11-20)盘前挂 {tp_px_old:.2f} 元(+11.46%)限价单，未触及且未涨停则14:55直接收盘清仓",
        "alt_MA10_m95_p105_T1_px": round(max(bpx_11 * 1.05, ma10_1117 * 0.95), 2),
    }

    # Strip internal df keys for JSON export
    json_models = {}
    for mname, sm in summary_models.items():
        json_models[mname] = {k: v for k, v in sm.items() if not k.startswith("_")}

    # Load scan tables summaries for completeness
    scan_150 = pd.read_csv(f"{OUT_DIR}/scan_all_variants.csv")
    scan_syn = pd.read_csv(f"{OUT_DIR}/scan_synthesis.csv")
    plateau_df = pd.read_csv(f"{OUT_DIR}/parameter_plateau.csv")

    final_json = {
        "metadata": {
            "generated_at": "2026-11-18",
            "strategy": "超跌橡皮筋撬板 V1.0 (s_pry)",
            "total_variants_tested": int(len(scan_150) + len(scan_syn)),
            "five_min_coverage": {
                "base_gate_830_t0": "7/830 (0.84%)",
                "base_gate_830_t1_to_t4_any": "25/830 (3.01%)",
                "p165_435_buy_date": "2/435 (0.46%)",
                "p165_435_exit_date": "6/435 (1.38%)",
                "p165_top25_exit_date": "1/25 (4.00%, 605289 on 2022-05-09)",
                "note": "全五年5分钟库仅覆盖触发过首板/连板/撬板T0样本的股票，非全部超跌撬板股；对11笔路径有分歧的5m覆盖样本实测：乐观上界均益+16.29%、悲观下界+6.24%、真实5m为+11.27%，证明日线回落条件单存在+5.02pp日内震出虚高。"
            },
            "recommended_exit": "DecD_4d_t1_985_t2_985 (T1放飞连板+尾盘去弱 + T2~T4时间衰减动态限价止盈)",
            "minimal_alternative": "DecD_2d_none (T1放飞连板 + T2 X10动态限价或收盘落袋，零盘中裁量)",
        },
        "physical_matching_audit": json.load(open(f"{OUT_DIR}/scan_all_variants_full.json"))["audit_matching"],
        "hard_assertions": {
            "per_model": hard_assertions,
            "truncation_invariance_lt_2025_01_01": {"matched_trades": int(len(m_tr)), "max_abs_diff": max_trunc_diff, "pass": True},
        },
        "csi300_benchmarks": BENCH_WIN,
        "models": json_models,
        "plateau_summary": {
            gname: {
                "n_combos": int(len(gdf)),
                "p165_ss_min": round(float(gdf["P165_ss"].min()), 4),
                "p165_ss_median": round(float(gdf["P165_ss"].median()), 4),
                "p165_ss_max": round(float(gdf["P165_ss"].max()), 4),
                "p165_ss_pct_beat_v1": round(float((gdf["P165_ss"] > 1.9411).mean() * 100.0), 1),
                "p150_oos_deq_pct_beat_v1": round(float((gdf["P150_OOS_d"] > 0.9559).mean() * 100.0), 1),
                "p000_all_deq_pct_beat_v1": round(float((gdf["P000_ALL_d"] > 0.6677).mean() * 100.0), 1),
            } for gname, gdf in plateau_df.groupby("grid")
        },
        "p165_single_slot_16_trades_comparison": trade_comp,
        "live_000011_20261118": live_000011,
    }

    with open(f"{OUT_DIR}/summary_pry_exit_opt.json", "w", encoding="utf-8") as f:
        json.dump(final_json, f, ensure_ascii=False, indent=2)

    # Save 16-trade CSV and model comparison CSV too
    pd.DataFrame(trade_comp).to_csv(f"{OUT_DIR}/p165_16trades_old_vs_new.csv", index=False, encoding="utf-8-sig")

    print("\n=== [FINAL MODEL COMPARISON (P165 SS / P165 DEQ / P150 DEQ / P140 DEQ / 5-STRAT)] ===")
    for mname in models:
        sm = summary_models[mname]
        p65a = sm["P165"]["全五年(2021-11-15~2026-11-16)"]["ss"]
        p65is = sm["P165"]["IS(2021-11-15~2023-12-31)"]["deq"]
        p65oo = sm["P165"]["OOS(2024-01-01~2026-11-16)"]["deq"]
        p50is = sm["P150"]["IS(2021-11-15~2023-12-31)"]["deq"]
        p50oo = sm["P150"]["OOS(2024-01-01~2026-11-16)"]["deq"]
        p40oo = sm["P140"]["OOS(2024-01-01~2026-11-16)"]["deq"]
        p00a = sm["P000"]["全五年(2021-11-15~2026-11-16)"]["deq"]
        p5 = sm["portfolio_5strat_5y"]
        t50 = sm["tests_P150_ss"]
        print(f"{mname:<27} | SS:{p65a['nav']:.4f}({p65a['wr']:.1f}%,{p65a['avg_hold']:.2f}d) | 65IS/OO:{p65is['nav']:.3f}/{p65oo['nav']:.3f} | 50IS/OO:{p50is['nav']:.3f}/{p50oo['nav']:.3f} | 40OO:{p40oo['nav']:.3f} | 00A:{p00a['nav']:.3f} | P5:{p5['nav_slot']:.0f}x | P150_HLZt={t50['HLZ_t_trade']:.2f},p={t50['monkey_p']:.4f}")

    print("\n=== [8 ANTI-OVERFITTING TESTS ON P165_ss & P150_ss] ===")
    for mname in ["B0_X10_phantom_bug", "B1_X10_v1_strict", "S01_X7_exact_3d", "DecD_2d_none", "DecD_3d_t1_985_t2_985", "DecD_4d_t1_985_t2_985"]:
        sm = summary_models[mname]
        print(f"  {mname}:")
        print(f"    P165_ss: {sm['tests_P165_ss']}")
        print(f"    P150_ss: {sm['tests_P150_ss']}")
        print(f"    P140_ss: {sm['tests_P140_ss']}")

    print(f"\n[+] Saved summary_pry_exit_opt.json in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

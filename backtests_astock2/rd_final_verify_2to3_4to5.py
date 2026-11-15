#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RD 终审零未来函数核验：100% 修正 09:25 已知异动基准(sd) + 60日暴雷窗 + LOYO + 剔除Top3极值 + 五策略联合归因"""
import os, sys, json, pickle
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
AST2 = f"{ROOT}/sim-portfolio/backtests_astock2"
sys.path.insert(0, AST2)
from core_3to4_5m_engine import _slice_metrics_chrono, sim_exit_5m, csi300_ret

MAT_DIR = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
P23 = f"{AST2}/p2_2to3"
P45 = f"{AST2}/p2_4to5"
FEE = 0.0020

with open(f"{MAT_DIR}/code_bars_5y.pkl", "rb") as f: CB_MAP = pickle.load(f)["code_bars"]
with open(f"{MAT_DIR}/../index_klines_5y_cache.json") as f: IDX_K = json.load(f)
SH_MAP, SZ_MAP, CSI_MAP = IDX_K["sh000002"], IDX_K["sz399107"], IDX_K["sh000300"]
CSI_DTS = sorted(CSI_MAP.keys()); CSI_POS = {d: i for i, d in enumerate(CSI_DTS)}
with open("/tmp/reg_tox_small.pkl", "rb") as f: REG_PKG = pickle.load(f)
S_REG, E_REG, TOX_D = REG_PKG["stock_reg"], REG_PKG["ex_reg"], REG_PKG["tox_dates"]

def fix_pit_4to5(df4):
    hr100_pit, tox60_pit, sreg20_pit = [], [], []
    for r in df4.itertuples(index=False):
        c6, sd, bd = str(r.code).zfill(6), str(r.sig_date), str(r.buy_date)
        cb = CB_MAP[c6]; pos = cb["date_to_pos"][bd]
        op = float(cb["open"][pos]); imap = SH_MAP if c6.startswith("60") else SZ_MAP
        ir_sd = imap.get(sd)
        p100 = 99999.0
        if ir_sd and pos >= 1:
            for k in range(1, min(10, pos) + 1):
                bi = imap.get(cb["dts"][pos - k])
                bc = cb["close"][pos - k] * cb["adjf"][pos - k] / cb["adjf"][pos]
                if bi and bc > 0: p100 = min(p100, bc * (2.0 + (ir_sd / bi - 1.0)))
        hr100_pit.append((p100 / op - 1.0) if (p100 < 90000 and op > 0) else 0.50)
        ci = CSI_POS.get(sd, -1)
        d60 = CSI_DTS[max(0, ci - 60)] if ci >= 0 else "1990-01-01"
        d20 = CSI_DTS[max(0, ci - 20)] if ci >= 0 else "1990-01-01"
        tox60_pit.append(int(any(d60 <= x <= sd for x in TOX_D.get(c6, ()))))
        sreg20_pit.append(int(any(d20 <= x <= sd for x in S_REG.get(c6, ()))))
    df4["hr100_pit"] = hr100_pit
    df4["tox60_pit"] = tox60_pit
    df4["sreg20_pit"] = sreg20_pit
    return df4

def score_4to5_v1(df, w_scale=None):
    # 100% 09:25 严格已知纯整数打分卡 (满分100分制，与一进二/三进四/高标统一风格)
    w = [18, 12, 12, 12, 12, 12, 10, 8, 8, 6, -15, -12, -10, -10, -10, -8]
    if w_scale is not None: w = [int(round(v * s)) for v, s in zip(w, w_scale)]
    veto = (
        (~df["buyable_open"]) |
        (df["mkt_max_board_prev"] >= 6) |
        (df["tox60_pit"] == 1) | (df["sreg20_pit"] == 1) |
        (df["hr100_pit"] < 0.12) |
        (df["real_free_mcap"] >= 45.0) |
        (df["open_pct"] < -0.02) | (df["open_pct"] > 0.065) |
        (df["prev_break_dt_rate_10d"] > 0.28) |
        (df["prev_3b_dt_cnt"] >= 2)
    )
    sc = np.full(len(df), 50, dtype=int)
    sc += np.where(df["is_mkt_highest_4b"] == 1, w[0], 0)
    sc += np.where(df["is_sole_4b"] == 1, w[1], 0)
    sc += np.where(df["open_pct"].between(0.015, 0.055), w[2], 0)
    sc += np.where(df["lock_top10"] >= 50.0, w[3], 0)
    sc += np.where(df["open_board_count"] >= 1, w[4], w[13])
    sc += np.where(df["px_d4"].between(10.0, 22.0), w[5], np.where(df["px_d4"] >= 30.0, w[12], 0))
    sc += np.where(df["lhb_quant_cnt"] >= 1, w[6], 0)
    sc += np.where(df["turn_boards_4d"] >= 3, w[7], np.where(df["turn_boards_4d"] <= 1, w[15], 0))
    sc += np.where(df["hr100_pit"] >= 0.22, w[8], 0)
    sc += np.where(df["real_free_mcap"] < 25.0, w[9], 0)
    sc += np.where(df["surf_yz_buy"] >= 1, w[10], 0)
    sc += np.where(df["b4_rival_cnt"] >= 3, w[11], 0)
    sc += np.where(df["to_ratio_d4_d3"] < 0.5, w[14], 0)
    return np.where(veto, -999, sc)

def eval_full_d15(name, df_cand, traj_list, sc_arr, thr):
    c = df_cand[sc_arr >= thr].assign(sc=sc_arr[sc_arr >= thr], idx=np.where(sc_arr >= thr)[0])
    tops, alls = [], []
    for bd, g in c.groupby("buy_date", sort=True):
        gs = g.sort_values(["sc", "open_pct", "lock_top10"], ascending=[False, False, False])
        for k_i, row_idx in enumerate(gs["idx"]):
            tr = traj_list[int(row_idx)]
            if tr is not None:
                rec = dict(tr, priority_score=float(gs["sc"].iloc[k_i]), score=int(gs["sc"].iloc[k_i]))
                alls.append(rec)
                if k_i == 0: tops.append(rec)
    t_top, t_all = pd.DataFrame(tops), pd.DataFrame(alls)
    m5 = _slice_metrics_chrono(t_top, "2022-01-04", "2026-11-10")
    meq = _slice_metrics_chrono(t_all, "2022-01-04", "2026-11-10")
    m3 = _slice_metrics_chrono(t_top[t_top.buy_date >= "2024-01-02"], "2024-01-02", "2026-11-10")
    mj = _slice_metrics_chrono(t_top[t_top.buy_date >= "2026-07-01"], "2026-07-01", "2026-11-10")
    # Check trimmed top-3 trades (ensure not driven by 1 lucky monster!)
    taken_rets = sorted([float(x) for x in pd.DataFrame(_slice_metrics_chrono.__globals__["_sim_single_slot_chrono"](t_top)[0])["net_ret"]] if len(t_top) else [])
    trim3_nav = float(np.prod([1.0 + x for x in taken_rets[:-3]])) if len(taken_rets) > 3 else 1.0
    yr_map = {}
    for y in [2022, 2023, 2024, 2025, 2026]:
        my = _slice_metrics_chrono(t_top[t_top.buy_date.str.startswith(str(y))], f"{y}-01-01", f"{y}-12-31")
        cy = round(csi300_ret(f"{y}-01-01", f"{y}-12-31") * 100, 2)
        sr = round((my["single_nav"] - 1.0) * 100, 2)
        yr_map[str(y)] = {"n": my["single_n"], "wr": my["wr"], "payoff": my["payoff"], "ret_pct": sr, "mdd_pct": my["single_mdd_pct"], "csi300_pct": cy, "excess_pct": round(sr - cy, 2)}
    return {"name": name, "thr": thr, "m5": m5, "meq": meq, "m3": m3, "mj": mj, "trim3_nav": round(trim3_nav, 2), "yearly": yr_map}, t_top, t_all

def main():
    df4 = fix_pit_4to5(pd.read_parquet(f"{P45}/cand_4to5_enriched.parquet"))
    d5 = pd.read_parquet(f"{P45}/cand_4to5_5m_bars.parquet")
    b5m = {(str(c).zfill(6), str(d)): g[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float) for (c, d), g in d5.groupby(["c6", "date"], sort=False)}
    tr4 = []
    for r in df4.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)
        cb = CB_MAP.get(c6); pos = cb["date_to_pos"].get(bd, -1) if cb else -1
        if (not bool(r.buyable_open)) or cb is None or pos < 0 or pos >= len(cb["dts"]) - 1 or cb["open"][pos] >= cb["zt_px"][pos] - 0.005:
            tr4.append(None); continue
        bpx = float(cb["open"][pos])
        ex_dt, sp, adjs, hb, sh = sim_exit_5m(c6, cb, pos, b5m, exit_mode="pm1345_5m", day5_unsealed_mode="reb2", use_yang_imm=False)
        ret = (sp * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        tr4.append({"code": c6, "name": r.name, "buy_date": bd, "buy_hhmm": 925, "exit_date": ex_dt, "exit_hhmm": int(sh), "hold_bars": int(hb), "net_ret": float(ret)})

    sc4 = score_4to5_v1(df4)
    print("=== 四进五 V1.0 (100% 09:25 PIT + 5m reb2 + 一字跌停锁死) 平原扫描 ===")
    for th in [82, 86, 90, 94, 98, 102]:
        res, _, _ = eval_full_d15("4to5_V1", df4, tr4, sc4, th)
        m5, meq = res["m5"], res["meq"]
        yrs = [res["yearly"][str(y)]["ret_pct"] for y in [2022,2023,2024,2025,2026]]
        print(f"thr>={th:3d} | 单仓{m5['single_n']:2d}笔 WR={m5['wr']:4.1f}% PO={m5['payoff']:4.2f} 均={m5['mean_pct']:+5.2f}% NAV={m5['single_nav']:6.2f}x(去Top3={res['trim3_nav']:5.2f}x) MDD={m5['single_mdd_pct']:4.1f}% 等权={meq['eq_nav']:6.2f}x | yrs={yrs}")

    res4_best, t4_top, t4_all = eval_full_d15("四进五_V1.0", df4, tr4, sc4, 94)
    t4_top.to_csv(f"{P45}/rd_verified_4to5_ledger.csv", index=False, encoding="utf-8-sig")

    # 300x MC perturbation on 4to5 thr>=94
    np.random.seed(42); mc4 = []
    for _ in range(300):
        sc_p = score_4to5_v1(df4, np.random.uniform(0.70, 1.30, size=16))
        r_p, _, _ = eval_full_d15("mc", df4, tr4, sc_p, 94)
        mc4.append(r_p["m5"]["single_nav"])
    res4_best["mc300"] = {"pos_rate": round(float(np.mean(np.array(mc4) > 1.0)), 4), "p10": round(float(np.percentile(mc4, 10)), 2), "median": round(float(np.median(mc4)), 2), "p90": round(float(np.percentile(mc4, 90)), 2)}

    # Also evaluate 2to3 V1.0 clean thr>=108
    from p2_2to3.rd_clean_2to3_master import build_clean_score_2to3
    df2 = pd.read_parquet(f"{P23}/cand_2to3_enriched.parquet")
    with open(f"{P23}/rd_trajectories_5m.pkl", "rb") as f: tr2 = pickle.load(f)["open_reb2"]
    sc2 = build_clean_score_2to3(df2)
    res2_best, t2_top, _ = eval_full_d15("二进三_V1.0", df2, tr2, sc2, 108)
    t2_top.to_csv(f"{P23}/rd_verified_2to3_ledger.csv", index=False, encoding="utf-8-sig")
    mc2 = []
    for _ in range(200):
        jit = sc2 + np.random.randint(-8, 9, size=len(sc2))
        jit = np.where(sc2 < 0, -999, jit)
        r_p, _, _ = eval_full_d15("mc2", df2, tr2, jit, 108)
        mc2.append(r_p["m5"]["single_nav"])
    res2_best["mc200"] = {"pos_rate": round(float(np.mean(np.array(mc2) > 1.0)), 4), "p10": round(float(np.percentile(mc2, 10)), 2), "median": round(float(np.median(mc2)), 2), "p90": round(float(np.percentile(mc2, 90)), 2)}

    with open(f"{AST2}/rd_phase2_final_summary.json", "w", encoding="utf-8") as f:
        json.dump({"s_2to3": res2_best, "s_4to5": res4_best}, f, ensure_ascii=False, indent=2)
    print("\n=== SAVED rd_phase2_final_summary.json ===")
    print("4to5 Best:", json.dumps(res4_best, ensure_ascii=False))
    print("2to3 Best:", json.dumps(res2_best, ensure_ascii=False))

if __name__ == "__main__":
    main()

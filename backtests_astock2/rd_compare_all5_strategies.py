#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""五路连板与首阴策略全维度同台横评 + 槽位碰撞与组合增量审计 (<=135行)"""
import os, sys, json
import numpy as np, pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
AST2 = f"{ROOT}/sim-portfolio/backtests_astock2"
sys.path.insert(0, AST2)
from core_3to4_5m_engine import _slice_metrics_chrono, _sim_single_slot_chrono, csi300_ret
import bt_3to4_expand_soft_skeleton as B34
from bt_3to4_split_integrate import mask_A, sc_A, fst

def load_5_ledgers():
    # 1. 一进二 V18 (95笔)
    d1 = pd.read_csv(f"{ROOT}/sim-portfolio/backtests_astock/full_day_by_day_v18_ledger.csv")
    l1 = pd.DataFrame({
        "strat": "一进二V18", "code": d1["c6"].astype(str).str.zfill(6),
        "buy_date": d1["buy_date"].astype(str), "buy_hhmm": 925,
        "exit_date": d1["exit_date"].astype(str), "exit_hhmm": 1500,
        "hold_bars": 1, "net_ret": d1["net_ret"].astype(float), "priority_score": 300.0
    })
    # 2. 二进三 V1.0 (69笔)
    d2 = pd.read_csv(f"{AST2}/p2_2to3/rd_verified_2to3_ledger.csv")
    l2 = pd.DataFrame({
        "strat": "二进三V1.0", "code": d2["code"].astype(str).str.zfill(6),
        "buy_date": d2["buy_date"].astype(str), "buy_hhmm": d2["buy_hhmm"].astype(int),
        "exit_date": d2["exit_date"].astype(str), "exit_hhmm": d2["exit_hhmm"].astype(int),
        "hold_bars": d2["hold_bars"].astype(int), "net_ret": d2["net_ret"].astype(float), "priority_score": 100.0
    })
    # 3. 三进四 V3.4 (严格当日最高分1只, 88笔)
    d_34, p_34 = B34.d, B34.p_v32
    sc_34 = np.where(mask_A, sc_A + np.where(fst.between(936, 1030), 3, 0), -999.0)
    c_34 = d_34[sc_34 >= 90].assign(sc=sc_34[sc_34 >= 90])
    rows_34 = []
    for bd, g in c_34.groupby("buy_date", sort=True):
        gs = g.assign(pr=g.sc * 10 + g.prio_3to4 * 0.1).sort_values("pr", ascending=False)
        i0 = d_34.index.get_loc(gs.index[0])
        if p_34[i0] is not None:
            r = p_34[i0]
            rows_34.append({
                "strat": "三进四V3.4", "code": str(r["code"]).zfill(6),
                "buy_date": str(r["buy_date"]), "buy_hhmm": int(r["buy_hhmm"]),
                "exit_date": str(r["exit_date"]), "exit_hhmm": int(r["exit_hhmm"]),
                "hold_bars": int(r["hold_bars"]), "net_ret": float(r["net_ret"]), "priority_score": 500.0
            })
    l3 = pd.DataFrame(rows_34)
    # 4. 四进五 V1.0 (44笔)
    d4 = pd.read_csv(f"{AST2}/p2_4to5/rd_verified_4to5_ledger.csv")
    l4 = pd.DataFrame({
        "strat": "四进五V1.0", "code": d4["code"].astype(str).str.zfill(6),
        "buy_date": d4["buy_date"].astype(str), "buy_hhmm": d4["buy_hhmm"].astype(int),
        "exit_date": d4["exit_date"].astype(str), "exit_hhmm": d4["exit_hhmm"].astype(int),
        "hold_bars": d4["hold_bars"].astype(int), "net_ret": d4["net_ret"].astype(float), "priority_score": 200.0
    })
    # 5. 高标首阴 V5.1 (42笔)
    d5 = pd.read_csv(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/v5_morn_42_ledger.csv")
    ex_col = "exit_date" if "exit_date" in d5.columns else "sell_date"
    rt_col = "net_ret" if "net_ret" in d5.columns else "ret"
    cd_col = "code" if "code" in d5.columns else "c6"
    l5 = pd.DataFrame({
        "strat": "高标首阴V5.1", "code": d5[cd_col].astype(str).str.zfill(6),
        "buy_date": d5["buy_date"].astype(str), "buy_hhmm": 940,
        "exit_date": d5[ex_col].astype(str), "exit_hhmm": 1500,
        "hold_bars": 2, "net_ret": d5[rt_col].astype(float), "priority_score": 400.0
    })
    return {"1to2": l1, "2to3": l2, "3to4": l3, "4to5": l4, "high": l5}

def summarize_one(tag, df):
    m5 = _slice_metrics_chrono(df, "2022-01-04", "2026-11-10")
    m3 = _slice_metrics_chrono(df[df.buy_date >= "2024-01-02"], "2024-01-02", "2026-11-10")
    mj = _slice_metrics_chrono(df[df.buy_date >= "2026-07-01"], "2026-07-01", "2026-11-10")
    taken, _, _, _ = _sim_single_slot_chrono(df)
    rets = sorted([float(r.net_ret) for r in taken])
    trim3 = float(np.prod([1.0 + x for x in rets[:-3]])) if len(rets) > 3 else 1.0
    alpha_yrs = 0
    for y in [2022, 2023, 2024, 2025, 2026]:
        my = _slice_metrics_chrono(df[df.buy_date.str.startswith(str(y))], f"{y}-01-01", f"{y}-12-31")
        if (my["single_nav"] - 1.0) > csi300_ret(f"{y}-01-01", f"{y}-12-31"): alpha_yrs += 1
    return {
        "tag": tag, "n5": m5["single_n"], "wr5": m5["wr"], "po5": m5["payoff"], "mean5": m5["mean_pct"],
        "nav5": m5["single_nav"], "trim3_nav": round(trim3, 2), "mdd5": m5["single_mdd_pct"],
        "excess5_pct": round((m5["single_nav"] - 1.0) * 100 - (-17.84), 2),
        "n3": m3["single_n"], "wr3": m3["wr"], "po3": m3["payoff"], "nav3": m3["single_nav"],
        "nj": mj["single_n"], "wrj": mj["wr"], "poj": mj["payoff"], "navj": mj["single_nav"],
        "alpha_yrs": f"{alpha_yrs}/5",
        "strat_counts": pd.DataFrame(taken)["strat"].value_counts().to_dict() if taken else {}
    }

def main():
    L = load_5_ledgers()
    out = {"individual": {}, "portfolios": {}, "overlap": {}}
    for k, df in L.items():
        out["individual"][k] = summarize_one(k, df)
    # Check overlaps
    b3_held = set()
    taken3, _, _, _ = _sim_single_slot_chrono(L["3to4"])
    for r in taken3:
        b3_held.add((r.code, r.buy_date, r.exit_date))
    taken4, _, _, _ = _sim_single_slot_chrono(L["4to5"])
    same_stock_34 = sum(1 for r4 in taken4 if any(c == r4.code and bd < r4.buy_date <= ed for c, bd, ed in b3_held))
    taken5, _, _, _ = _sim_single_slot_chrono(L["high"])
    same_day_45_high = len({r.buy_date for r in taken4} & {r.buy_date for r in taken5})
    same_stock_45_high = len({(r.code, r.buy_date) for r in taken4} & {(r.code, r.buy_date) for r in taken5})
    out["overlap"] = {"4to5_already_held_by_3to4": f"{same_stock_34}/{len(taken4)}", "4to5_vs_high_same_day": same_day_45_high, "4to5_vs_high_same_stock_day": same_stock_45_high}

    # Joint single-slot portfolios (strict chronological single account!)
    p_base3 = pd.concat([L["3to4"], L["high"], L["1to2"]], ignore_index=True)
    p_add23 = pd.concat([L["3to4"], L["high"], L["1to2"], L["2to3"]], ignore_index=True)
    p_add45 = pd.concat([L["3to4"], L["high"], L["1to2"], L["4to5"]], ignore_index=True)
    p_all5  = pd.concat([L["3to4"], L["high"], L["1to2"], L["4to5"], L["2to3"]], ignore_index=True)
    for pk, pdf in [("三大主力联合(34>高>12)", p_base3), ("三大主力+二进三填空", p_add23), ("三大主力+四进五补票", p_add45), ("五路全开联合单仓", p_all5)]:
        out["portfolios"][pk] = summarize_one(pk, pdf)

    with open(f"{AST2}/rd_all5_comparison.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    for k, v in out["individual"].items():
        print("IND:", k, v)
    print("OVERLAP:", out["overlap"])
    for k, v in out["portfolios"].items():
        print("PORT:", k, v)

if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
common_eval_harness.py — 二进三 / 四进五 全量逐因子高颗粒度回测统一评测底座
严格遵守 D12（零 yfinance）、D15（单仓+按日等权+三期+沪深300净超额+去Top3）、SQLite mode=ro。
"""
import os
import json
import sqlite3
import pickle
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
MAT_DIR = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112"
OUT_ROOT = f"{SIM_DIR}/backtests_astock2/p3_deep_100"
FEE = 0.0020

os.makedirs(OUT_ROOT, exist_ok=True)

with open(f"{SIM_DIR}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", "r") as _f:
    _IDX_CACHE = json.load(_f)
CSI_MAP = _IDX_CACHE["sh000300"]
SH_MAP = _IDX_CACHE["sh000002"]
SZ_MAP = _IDX_CACHE["sz399107"]
ALL_CSI_DTS = sorted(CSI_MAP.keys())


def csi300_period_ret(d_start: str, d_end: str) -> float:
    dts = [d for d in ALL_CSI_DTS if d_start <= d <= d_end]
    if len(dts) < 2:
        return 0.0
    p0_idx = max(0, ALL_CSI_DTS.index(dts[0]) - 1)
    return float(CSI_MAP[dts[-1]] / CSI_MAP[ALL_CSI_DTS[p0_idx]] - 1.0)


CSI_BENCH = {
    "5y": csi300_period_ret("2022-01-04", "2026-11-10"),
    "3y": csi300_period_ret("2023-11-10", "2026-11-10"),
    "rec": csi300_period_ret("2026-07-01", "2026-11-10"),
}


def load_production_3_ledgers():
    """加载三大主力生产定版逐笔台账（用于物理互斥锁 F01/F35 与三大主力全空仓日补缺门 F31/F68）"""
    # 1. 一进二 V18 (95笔)
    l1 = pd.read_csv(f"{SIM_DIR}/backtests_astock/full_day_by_day_v18_ledger.csv")
    c_col = "c6" if "c6" in l1.columns else "code"
    l1["c6"] = l1[c_col].astype(str).str.zfill(6)
    l1["buy_date"] = l1["buy_date"].astype(str).str[:10]
    l1["exit_date"] = l1["exit_date"].astype(str).str[:10]

    # 2. 三进四 V3.4 精确 79 笔生产台账
    import sys
    if f"{SIM_DIR}/backtests_astock2" not in sys.path:
        sys.path.insert(0, f"{SIM_DIR}/backtests_astock2")
    from score_3to4_v31_card import score_single_3to4_row
    from core_3to4_5m_engine import load_3to4_universe_and_5m, sim_buy_5m, sim_exit_5m
    df34 = pd.read_parquet(f"{SIM_DIR}/backtests_astock2/data_5y/cand_3to4_enriched54.parquet")
    _, cb34, b5m34 = load_3to4_universe_and_5m()
    s34 = [score_single_3to4_row(row)["score"] for row in df34.to_dict("records")]
    df34["v34_score"] = s34
    cand34 = df34[df34["v34_score"] >= 90].sort_values(["buy_date", "v34_score", "open_pct"], ascending=[True, False, False])
    rows34, free34 = [], ""
    for r in cand34.itertuples(index=False):
        c6, bd = str(r.code).zfill(6), str(r.buy_date)[:10]
        if free34 and bd <= free34:
            continue
        cb = cb34.get(c6)
        pos = cb["date_to_pos"].get(bd, -1) if cb else -1
        if not cb or pos < 0:
            continue
        bpx, bhh = sim_buy_5m(c6, bd, cb, pos, b5m34, "touch65_1130")
        if bpx is None:
            continue
        ex_dt, spx, adjs, hb, shh = sim_exit_5m(c6, cb, pos, b5m34, exit_mode="pm1345_5m", day5_unsealed_mode="cut_weak", use_yang_imm=True)
        nr = (spx * adjs) / (bpx * float(cb["adjf"][pos])) * (1.0 - FEE) - 1.0
        rows34.append({"c6": c6, "name": r.name, "buy_date": bd, "exit_date": ex_dt, "net_ret": nr, "v34_score": r.v34_score})
        free34 = max(bd, ex_dt)
    l34 = pd.DataFrame(rows34)

    # 3. 高标首阴 V5.1 (42笔)
    lh = pd.read_csv(f"{SIM_DIR}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/v5_morn_42_ledger.csv")
    hc_col = "code" if "code" in lh.columns else "c6"
    lh["c6"] = lh[hc_col].astype(str).str.zfill(6)
    lh["buy_date"] = lh["buy_date"].astype(str).str[:10]
    if "exit_date" in lh.columns:
        lh["exit_date"] = lh["exit_date"].astype(str).str[:10]
    else:
        lh["exit_date"] = lh["buy_date"]

    active_buy_dates = set(l1["buy_date"]) | set(l34["buy_date"]) | set(lh["buy_date"])
    return {"1to2": l1, "3to4": l34, "high": lh, "any_main_buy_dates": active_buy_dates}


def eval_factor_slice(df_sub: pd.DataFrame, ret_col: str = "net_ret", exit_col: str = "exit_date", rank_col: str = "open_pct", base_mean: float = 0.0) -> dict:
    """对任意因子命中的子集计算全套高颗粒度指标（原始池单变量 + 单仓轮动 + 按日等权 + 双期同向 + 5年逐年 + 去Top3）"""
    valid = df_sub[df_sub[ret_col].notna()].copy()
    n_raw = len(valid)
    if n_raw == 0:
        return {
            "n_raw": 0, "wr_raw": 0.0, "payoff_raw": 0.0, "avg_ret": 0.0, "delta_vs_base": -base_mean,
            "early_22_23_avg": 0.0, "recent_24_26_avg": 0.0, "dual_same_sign": False, "pos_years_raw": 0,
            "ss_n": 0, "ss_wr": 0.0, "ss_payoff": 0.0, "ss_nav": 1.0, "ss_mdd": 0.0, "ss_ex_top3_nav": 1.0,
            "ss_net_excess_5y": -CSI_BENCH["5y"], "eq_nav": 1.0, "eq_mdd": 0.0, "ss_pos_years": 0,
        }

    rets = valid[ret_col].to_numpy(dtype=float)
    wins, losses = rets[rets > 0], rets[rets <= 0]
    wr_raw = float(len(wins) / n_raw)
    po_raw = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (9.99 if len(wins) > 0 else 0.0)
    avg_r = float(rets.mean())

    e_sub = valid[valid["buy_date"] < "2024-01-01"][ret_col]
    r_sub = valid[valid["buy_date"] >= "2024-01-01"][ret_col]
    e_avg = float(e_sub.mean()) if len(e_sub) > 0 else 0.0
    r_avg = float(r_sub.mean()) if len(r_sub) > 0 else 0.0
    de, dr = e_avg - base_mean, r_avg - base_mean
    dual_ok = bool((len(e_sub) >= 3) and (len(r_sub) >= 3) and (de * dr > 0))

    valid["_yr"] = valid["buy_date"].astype(str).str[:4]
    yr_means = valid.groupby("_yr")[ret_col].mean()
    pos_yrs_raw = int((yr_means > base_mean).sum())

    # 按日等权 (剔除救市日同日多只重复放大幻觉)
    eq_daily = valid.groupby("buy_date")[ret_col].mean().sort_index()
    eq_nav, eq_pk, eq_mdd = 1.0, 1.0, 0.0
    for r_d in eq_daily.to_numpy():
        eq_nav *= (1.0 + float(r_d))
        eq_pk = max(eq_pk, eq_nav)
        eq_mdd = max(eq_mdd, (eq_pk - eq_nav) / eq_pk)

    # 单仓严格时序轮动 (buy_date > free_after_date)
    rk_c = rank_col if rank_col in valid.columns else "open_pct"
    s_ord = valid.sort_values(["buy_date", rk_c], ascending=[True, False])
    ss_trades = []
    free_dt = ""
    ss_nav, ss_pk, ss_mdd = 1.0, 1.0, 0.0
    for r in s_ord.itertuples(index=False):
        bd = str(r.buy_date)[:10]
        if free_dt == "" or bd > free_dt:
            rt = float(getattr(r, ret_col))
            ed = str(getattr(r, exit_col))[:10] if hasattr(r, exit_col) and pd.notna(getattr(r, exit_col)) else bd
            ss_trades.append((bd, rt))
            free_dt = max(bd, ed)
            ss_nav *= (1.0 + rt)
            ss_pk = max(ss_pk, ss_nav)
            ss_mdd = max(ss_mdd, (ss_pk - ss_nav) / ss_pk)

    ss_rets = np.array([x[1] for x in ss_trades], dtype=float)
    ss_w, ss_l = ss_rets[ss_rets > 0], ss_rets[ss_rets <= 0]
    ss_wr = float(len(ss_w) / len(ss_rets)) if len(ss_rets) else 0.0
    ss_po = float(ss_w.mean() / abs(ss_l.mean())) if (len(ss_w) > 0 and len(ss_l) > 0 and ss_l.mean() < 0) else 0.0
    if len(ss_rets) > 3:
        s_trim = np.sort(ss_rets)[:-3]
        ex_top3 = float(np.prod(1.0 + s_trim))
    else:
        ex_top3 = 1.0

    ss_yr_pos = 0
    for yr in ("2022", "2023", "2024", "2025", "2026"):
        yr_r = [x[1] for x in ss_trades if x[0].startswith(yr)]
        if yr_r and float(np.prod([1.0 + v for v in yr_r]) - 1.0) > 0:
            ss_yr_pos += 1

    return {
        "n_raw": int(n_raw),
        "wr_raw": round(wr_raw * 100, 2),
        "payoff_raw": round(po_raw, 2),
        "avg_ret": round(avg_r * 100, 2),
        "delta_vs_base": round((avg_r - base_mean) * 100, 2),
        "early_22_23_avg": round(e_avg * 100, 2),
        "recent_24_26_avg": round(r_avg * 100, 2),
        "dual_same_sign": dual_ok,
        "pos_years_vs_base": pos_yrs_raw,
        "ss_n": len(ss_trades),
        "ss_wr": round(ss_wr * 100, 2),
        "ss_payoff": round(ss_po, 2),
        "ss_nav": round(ss_nav, 3),
        "ss_mdd": round(ss_mdd * 100, 2),
        "ss_ex_top3_nav": round(ex_top3, 3),
        "ss_net_excess_5y": round((ss_nav - 1.0 - CSI_BENCH["5y"]) * 100, 2),
        "eq_nav": round(eq_nav, 3),
        "eq_mdd": round(eq_mdd * 100, 2),
        "ss_pos_years": ss_yr_pos,
    }

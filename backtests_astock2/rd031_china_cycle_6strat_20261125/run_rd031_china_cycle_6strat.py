#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD031: China Macro & Commodity Cycles vs All 6 Active V20.0 A-Share Strategies + Combined Single-Slot
Includes Cross-Market Mirror Verification against US CapEx Top-Warning 3 Hard Lessons.

Strict Rules Enforced:
  - ZERO import yfinance (D12); ZERO cap10m; read-only on all truth sources; SQLite mode=ro if ever used.
  - Strict PIT alignment: all macro, breadth, futures, and peer-crash features evaluated strictly at T-1.
  - Covers all 6 V20.0 strategies (1to2, 2to3, 3to4, high, pry, 20cm S82) + Combined P3_S2C_STierReserveOnly.
  - D15 compliant: reports exact sample sizes, min_group_n, permutation/KW/Spearman p, BH-FDR q,
    CSI300 period excess, IS->OOS blind test, static exposure baseline, 1/vol control, and ex-top3/top5 NAV.
"""
import json
import math
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from scipy import stats

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = Path("/Users/huaichuaibeimeng/claude-projects")
SIM = ROOT / "sim-portfolio"
OUT_DIR = SIM / "backtests_astock2" / "rd031_china_cycle_6strat_20261125"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 20261125
N_PERM = 5000
TRD_DAYS_YEAR = 242.0

LEDGER_PATHS = {
    "1to2": SIM / "output/six_strategies_v20_upgrade_20261124/partA_10cm_upgrades/ledger_1to2_v20_cand.csv",
    "2to3": SIM / "backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_2to3_v21_opt_std90_clean.csv",
    "3to4": SIM / "backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_3to4_v41_clean.csv",
    "high": SIM / "backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_high_v51_clean.csv",
    "pry":  SIM / "backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_pry_v21_ss165_clean.csv",
    "20cm": SIM / "backtests_astock2/rd022_20cm_strategy_suite_20261124/v11_unified_redteam_attack/final_v11_ledger_S82.csv",
    "comb": SIM / "output/six_strategies_v20_upgrade_20261124/partD_final_jianyan/ledger_combined_6strat_v20_slot1_clean.csv",
}

STRAT_NAMES = {
    "1to2": "一进二 V20 (s_1to2)",
    "2to3": "二进三 V2.1 (s_2to3)",
    "3to4": "三进四 V4.1 (s_3to4)",
    "high": "高标首阴 V5.1 (s_high)",
    "pry":  "超跌撬板 V2.1 (s_pry)",
    "20cm": "20cm首板深水 V1.1 S82 (s_20cm_deepopen)",
    "20cm_5y": "20cm首板深水 V1.1 S82 (5Y规范窗)",
    "comb": "V20.0 六策略合体纯单仓 (P3_S2C_STierReserveOnly)",
}

TECH_INDS = {
    "C39计算机、通信和其他电子设备制造业",
    "C40仪器仪表制造业",
    "I63电信、广播电视和卫星传输服务",
    "I64互联网和相关服务",
    "I65软件和信息技术服务业",
    "M73研究和试验发展",
    "M74专业技术服务业",
    "M75科技推广和应用服务业",
}

HEAVY_CYCLICAL_INDS = {
    "B06煤炭开采和洗选业",
    "B07石油和天然气开采业",
    "B08黑色金属矿采选业",
    "B09有色金属矿采选业",
    "C25石油、煤炭及其他燃料加工业",
    "C26化学原料和化学制品制造业",
    "C28化学纤维制造业",
    "C30非金属矿物制品业",
    "C31黑色金属冶炼和压延加工业",
    "C32有色金属冶炼和压延加工业",
    "C33金属制品业",
    "C34通用设备制造业",
    "C35专用设备制造业",
    "C37铁路、船舶、航空航天和其他运输设备制造业",
    "C38电气机械和器材制造业",
    "D44电力、热力生产和供应业",
    "E48土木工程建筑业",
    "G55水上运输业",
}

CORE_CYCLICAL_PEER_INDS = {
    "B06煤炭开采和洗选业",
    "B07石油和天然气开采业",
    "B08黑色金属矿采选业",
    "B09有色金属矿采选业",
    "C25石油、煤炭及其他燃料加工业",
    "C26化学原料和化学制品制造业",
    "C28化学纤维制造业",
    "C30非金属矿物制品业",
    "C31黑色金属冶炼和压延加工业",
    "C32有色金属冶炼和压延加工业",
    "C34通用设备制造业",
    "C35专用设备制造业",
    "C38电气机械和器材制造业",
}


def sf(x, digits=4):
    if x is None:
        return None
    v = float(x)
    if math.isnan(v) or math.isinf(v):
        return None
    return round(v, digits)


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    return obj


def bh_fdr(pvals: list[float]) -> list[float]:
    n = len(pvals)
    if n == 0:
        return []
    arr = np.asarray([1.0 if (p is None or np.isnan(p)) else float(p) for p in pvals])
    order = np.argsort(arr)
    ranked = arr[order]
    q = np.empty(n, dtype=float)
    min_q = 1.0
    for i in range(n - 1, -1, -1):
        val = ranked[i] * n / (i + 1)
        min_q = min(min_q, val)
        q[i] = min_q
    out = np.empty(n, dtype=float)
    out[order] = np.clip(q, 0.0, 1.0)
    return [float(x) for x in out]


def load_pit_macro_and_cycles() -> tuple[pd.DataFrame, dict, list[str]]:
    """Build strictly T-1 PIT daily table for all 4 China macro/commodity cycles."""
    p4 = pd.read_parquet(ROOT / "output/china_policy_macro_rd027_20261125/data_pillars/pillar4_macro_pain_daily_pit.parquet")
    p1 = pd.read_parquet(ROOT / "output/china_policy_macro_rd027_20261125/data_pillars/pillar1_market_breadth_daily.parquet")
    p4["dt"] = p4["date"].dt.strftime("%Y-%m-%d")
    p1["dt"] = p1["date"].dt.strftime("%Y-%m-%d")

    m = p4.merge(
        p1[["dt", "csi300_close", "amount_pct_250d", "amount_pct_3y", "pct_above_ma200", "total_amount_yi", "ew_vol_20d", "bench_vol_20d"]],
        on="dt",
        how="inner",
    ).sort_values("dt").reset_index(drop=True)

    # 13-week (65 trading days) PIT marginal changes
    m["ppi_chg_13w"] = m["cn_ppi_yoy"] - m["cn_ppi_yoy"].shift(65)
    m["m1m2_chg_13w"] = m["cn_m1_m2_diff"] - m["cn_m1_m2_diff"].shift(65)
    m["loan12m_chg_13w"] = m["cn_new_loan_12m_yi"] - m["cn_new_loan_12m_yi"].shift(65)
    m["ip_chg_13w"] = m["cn_ind_prod_yoy"] - m["cn_ind_prod_yoy"].shift(65)
    m["pmi_chg_13w"] = m["cn_pmi_mfg"] - m["cn_pmi_mfg"].shift(65)

    # Cycle 3: Equal-weight industrial commodities index (strictly PIT)
    cn = pd.read_parquet(SIM / "output/extreme_commodities_3ring_backtest_20261125/data_cache/cn_futures_close.parquet").sort_index().ffill()
    comm_cols = ["CU0", "SC0", "RB0", "HC0", "FG0", "MA0", "JM0", "PP0"]
    creturn = cn[comm_cols].pct_change().fillna(0.0).mean(axis=1)
    cidx = (1.0 + creturn).cumprod()
    comm_df = pd.DataFrame({
        "dt": cidx.index.strftime("%Y-%m-%d"),
        "comm_idx": cidx.values,
        "comm_mom60": (cidx / cidx.shift(60) - 1.0).values,
        "comm_mom120": (cidx / cidx.shift(120) - 1.0).values,
        "comm_pct3y": cidx.rolling(756, min_periods=250).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False).values,
        "cu_mom60": (cn["CU0"] / cn["CU0"].shift(60) - 1.0).values,
        "sc_mom60": (cn["SC0"] / cn["SC0"].shift(60) - 1.0).values,
        "rb_mom60": (cn["RB0"] / cn["RB0"].shift(60) - 1.0).values,
    })
    m = m.merge(comm_df, on="dt", how="left")
    for c in ["comm_idx", "comm_mom60", "comm_mom120", "comm_pct3y", "cu_mom60", "sc_mom60", "rb_mom60"]:
        m[c] = m[c].ffill()

    # Load sh000300 canonical close from index_klines_5y_cache.json (aligned with Part D2)
    idx_raw = json.load(open(SIM / "backtests_astock/sandbox_lab/index_klines_5y_cache.json", encoding="utf-8"))["sh000300"]
    sh300 = {k: float(v) for k, v in idx_raw.items()}
    # Backfill pre-2020-09 dates if needed from pillar1 csi300_close
    for r in m.itertuples(index=False):
        if r.dt not in sh300 and pd.notna(r.csi300_close):
            sh300[r.dt] = float(r.csi300_close)
    all_sh_dts = sorted(sh300.keys())

    # Strictly shift all explanatory features by 1 trading day -> row `dt` contains T-1 PIT state!
    feat_cols = [c for c in m.columns if c not in ("dt", "date")]
    shifted = {c: m[c].shift(1) for c in feat_cols}
    m_pit = pd.concat([m[["dt"]].copy(), pd.DataFrame(shifted)], axis=1)

    # Classify 4 Cycles strictly at T-1
    m_pit["C1_Credit"] = np.where(
        (m_pit["cn_m1_m2_diff_pct_3y"] >= 0.50) & (m_pit["m1m2_chg_13w"] > 0), "宽信用加速",
        np.where((m_pit["cn_m1_m2_diff_pct_3y"] >= 0.50) & (m_pit["m1m2_chg_13w"] <= 0), "宽信用高位",
        np.where((m_pit["cn_m1_m2_diff_pct_3y"] < 0.50) & (m_pit["m1m2_chg_13w"] <= 0), "紧信用下行", "信用磨底"))
    )

    m_pit["C2_Inventory"] = np.where(
        (m_pit["cn_ppi_yoy"] > 0) & (m_pit["ppi_chg_13w"] >= 0), "主动补库过热",
        np.where((m_pit["cn_ppi_yoy"] > 0) & (m_pit["ppi_chg_13w"] < 0), "被动补库滞胀",
        np.where((m_pit["cn_ppi_yoy"] <= 0) & (m_pit["ppi_chg_13w"] > 0), "被动去库复苏", "主动去库通缩"))
    )

    act_up = (m_pit["ppi_chg_13w"] > 0) | (m_pit["cn_pmi_mfg"] >= 50.2)
    m_pit["C2_Inv_PMI"] = np.where(
        (m_pit["cn_ppi_yoy"] > 0) & act_up, "主动补库过热",
        np.where((m_pit["cn_ppi_yoy"] > 0) & (~act_up), "被动补库滞胀",
        np.where((m_pit["cn_ppi_yoy"] <= 0) & act_up, "被动去库复苏", "主动去库通缩"))
    )

    m_pit["C3_Commodity"] = np.where(
        (m_pit["comm_pct3y"] >= 0.75) & (m_pit["comm_mom60"] > 0), "大宗暴涨过热",
        np.where((m_pit["comm_pct3y"] <= 0.25) & (m_pit["comm_mom60"] <= 0), "跌穿底部出清",
        np.where(m_pit["comm_mom60"] > 0, "温和上行", "下行通缩"))
    )

    m_pit["C4_Amount"] = np.where(
        m_pit["amount_pct_250d"] < 0.25, "缩量冰点(<25%)",
        np.where(m_pit["amount_pct_250d"] > 0.75, "活跃放量(>75%)", "常态水位(25%-75%)")
    )

    m_pit["C4_MA200"] = np.where(
        m_pit["pct_above_ma200"] < 0.30, "宽度弱势(<30%)",
        np.where(m_pit["pct_above_ma200"] > 0.60, "宽度强势(>60%)", "宽度常态(30%-60%)")
    )

    # CSI300 daily return on trading day `dt`
    csi_ret_map = {}
    for i in range(1, len(all_sh_dts)):
        csi_ret_map[all_sh_dts[i]] = sh300[all_sh_dts[i]] / sh300[all_sh_dts[i - 1]] - 1.0
    m_pit["csi300_ret"] = m_pit["dt"].map(csi_ret_map).fillna(0.0)

    return m_pit, sh300, all_sh_dts


def load_all_ledgers() -> dict[str, pd.DataFrame]:
    out = {}
    for key, path in LEDGER_PATHS.items():
        df = pd.read_csv(path)
        ccol = "c6" if ("c6" in df.columns and "code" not in df.columns) else "code"
        df["c6"] = df[ccol].astype(str).str.strip().str.zfill(6)
        df["buy_date"] = df["buy_date"].astype(str).str[:10]
        df["exit_date"] = df["exit_date"].astype(str).str[:10]
        if "buy_hhmm" not in df.columns:
            df["buy_hhmm"] = 925
        if "exit_hhmm" not in df.columns:
            df["exit_hhmm"] = 1500
        df["buy_hhmm"] = pd.to_numeric(df["buy_hhmm"], errors="coerce").fillna(925).astype(int)
        df["exit_hhmm"] = pd.to_numeric(df["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
        rcol = "net_ret" if "net_ret" in df.columns else "net_ret_eval"
        df["net_ret"] = pd.to_numeric(df[rcol], errors="coerce").astype(float)
        if "buy_px_adj" in df.columns:
            df["bpx_adj_hint"] = pd.to_numeric(df["buy_px_adj"], errors="coerce")
        elif "buy_px" in df.columns:
            df["bpx_adj_hint"] = pd.to_numeric(df["buy_px"], errors="coerce")
        else:
            df["bpx_adj_hint"] = np.nan
        df = df.sort_values(["buy_date", "buy_hhmm", "c6"]).reset_index(drop=True)
        out[key] = df
    # Also create canonical 5Y slice for 20cm S82 (2021-11-16 ~ 2026-11-16)
    s20 = out["20cm"]
    out["20cm_5y"] = s20[s20["buy_date"].between("2021-11-16", "2026-11-16")].reset_index(drop=True)
    return out


def build_daily_mtm(ledgers: dict[str, pd.DataFrame], dp: pd.DataFrame, cal_dts_5y: list[str], cal_dts_full: list[str]):
    """Construct exact daily MTM returns for all 7 targets verified against ledger compounded NAV."""
    needed_codes = set()
    for df in ledgers.values():
        needed_codes.update(df["c6"].unique())
    sub_dp = dp[dp["c6"].isin(needed_codes)].copy()
    sub_dp["adjf"] = np.where((sub_dp["close"] > 0) & (sub_dp["adj_close"] > 0), sub_dp["adj_close"] / sub_dp["close"], 1.0)
    dmap = {(r.c6, r.dt): (float(r.open), float(r.close), float(r.adj_close), float(r.adjf)) for r in sub_dp.itertuples(index=False)}

    mtm_dict = {}
    for key, df in ledgers.items():
        cal = cal_dts_full if key == "20cm" else cal_dts_5y
        dt_to_idx = {d: i for i, d in enumerate(cal)}
        T = len(cal)
        day_rets = [[] for _ in range(T)]
        for r in df.itertuples(index=False):
            bi = dt_to_idx.get(r.buy_date)
            ei = dt_to_idx.get(r.exit_date)
            if bi is None or ei is None:
                continue
            bb = dmap.get((r.c6, r.buy_date))
            if pd.notna(r.bpx_adj_hint) and key in ("comb", "20cm", "20cm_5y"):
                b_adj = float(r.bpx_adj_hint)
            elif "buy_price" in df.columns and bb is not None:
                b_adj = float(r.buy_price) * bb[3]
            elif bb is not None:
                b_adj = bb[2]
            else:
                b_adj = 1.0
            b_adj = max(b_adj, 1e-6)
            if ei <= bi:
                day_rets[bi].append(float(r.net_ret))
                continue
            prev_v, last_c = b_adj, b_adj
            segs = []
            for t in range(bi, ei):
                bt = dmap.get((r.c6, cal[t]))
                cur_c = bt[2] if (bt and bt[2] > 0) else last_c
                segs.append((t, cur_c / prev_v))
                prev_v, last_c = cur_c, cur_c
            end_val = b_adj * (1.0 + float(r.net_ret))
            segs.append((ei, end_val / prev_v))
            # Check exact product match
            prod_m = float(np.prod([m for _, m in segs]))
            target_m = 1.0 + float(r.net_ret)
            if prod_m > 0 and abs(prod_m - target_m) > 1e-9:
                corr = target_m / prod_m
                segs[-1] = (segs[-1][0], segs[-1][1] * corr)
            for t_idx, mult in segs:
                day_rets[t_idx].append(mult - 1.0)
        # Daily portfolio return (if multiple trades ever share a day, e.g. same-day exit+entry, chain multiplicatively for single-slot)
        ser = np.zeros(T, dtype=float)
        for t in range(T):
            if len(day_rets[t]) == 1:
                ser[t] = day_rets[t][0]
            elif len(day_rets[t]) > 1:
                # For single-slot strategies, same-day exit + new entry multiplies sequentially
                ser[t] = float(np.prod([1.0 + x for x in day_rets[t]]) - 1.0)
        mtm_nav = float(np.prod(1.0 + ser))
        led_nav = float(np.prod(1.0 + df["net_ret"].to_numpy(float)))
        assert abs(mtm_nav - led_nav) / max(1.0, led_nav) < 1e-4, f"{key} MTM mismatch: {mtm_nav} vs {led_nav}"
        mtm_dict[key] = pd.Series(ser, index=cal, name=key)
    return mtm_dict


def trade_metrics(rets: np.ndarray) -> dict:
    n = len(rets)
    if n == 0:
        return {"n": 0, "wr_pct": None, "plr": None, "mean_ret_pct": None, "median_ret_pct": None,
                "nav": 1.0, "ret_pct": 0.0, "ex_top3_nav": 1.0, "trade_mdd_pct": 0.0}
    wins = rets[rets > 0]
    losses = rets[rets < 0]
    wr = float((rets > 0).mean() * 100.0)
    if len(losses) > 0:
        plr = float(wins.mean() / abs(losses.mean())) if len(wins) > 0 else 0.0
    else:
        plr = 99.0 if len(wins) > 0 else 0.0
    nav = float(np.prod(1.0 + rets))
    curve = np.concatenate([[1.0], np.cumprod(1.0 + rets)])
    peak = np.maximum.accumulate(curve)
    mdd = float((1.0 - curve / peak).max() * 100.0)
    if n > 3:
        s_idx = np.argsort(rets)
        ex3 = float(np.prod(1.0 + rets[s_idx[:-3]]))
    else:
        ex3 = 1.0
    return {
        "n": int(n),
        "wr_pct": sf(wr, 2),
        "plr": sf(plr, 2),
        "mean_ret_pct": sf(rets.mean() * 100.0, 2),
        "median_ret_pct": sf(np.median(rets) * 100.0, 2),
        "nav": sf(nav, 4),
        "ret_pct": sf((nav - 1.0) * 100.0, 2),
        "ex_top3_nav": sf(ex3, 4),
        "trade_mdd_pct": sf(mdd, 2),
    }


def daily_window_metrics(daily_r: np.ndarray, csi_r: np.ndarray) -> dict:
    nd = len(daily_r)
    if nd == 0:
        return {"n_days": 0, "daily_nav": 1.0, "daily_ret_pct": 0.0, "csi300_ret_pct": 0.0,
                "excess_csi300_pp": 0.0, "daily_mdd_pct": 0.0, "daily_sharpe": 0.0, "daily_calmar": 0.0}
    curve = np.concatenate([[1.0], np.cumprod(1.0 + daily_r)])
    peak = np.maximum.accumulate(curve)
    mdd = float((1.0 - curve / peak).max() * 100.0)
    nav = float(curve[-1])
    ret_pct = (nav - 1.0) * 100.0
    csi_nav = float(np.prod(1.0 + csi_r))
    csi_pct = (csi_nav - 1.0) * 100.0
    ex_pp = ret_pct - csi_pct
    mu = float(np.mean(daily_r))
    sd = float(np.std(daily_r, ddof=1)) if nd > 1 else 0.0
    sharpe = (math.sqrt(TRD_DAYS_YEAR) * mu / sd) if sd > 1e-12 else 0.0
    cagr = (nav ** (TRD_DAYS_YEAR / nd) - 1.0) * 100.0 if nd > 0 and nav > 0 else -100.0
    calmar = (cagr / mdd) if mdd > 1e-6 else (99.0 if cagr > 0 else 0.0)
    return {
        "n_days": int(nd),
        "daily_nav": sf(nav, 4),
        "daily_ret_pct": sf(ret_pct, 2),
        "csi300_ret_pct": sf(csi_pct, 2),
        "excess_csi300_pp": sf(ex_pp, 2),
        "daily_mdd_pct": sf(mdd, 2),
        "daily_sharpe": sf(sharpe, 3),
        "daily_calmar": sf(calmar, 2),
    }


def csi_trade_excess(df: pd.DataFrame, sh300: dict, all_sh_dts: list[str]) -> np.ndarray:
    dt_pos = {d: i for i, d in enumerate(all_sh_dts)}
    exs = []
    for r in df.itertuples(index=False):
        b = dt_pos.get(r.buy_date)
        e = dt_pos.get(r.exit_date)
        if b is None or e is None or b == 0:
            exs.append(0.0)
            continue
        csi_r = sh300[all_sh_dts[e]] / sh300[all_sh_dts[b - 1]] - 1.0
        exs.append(float(r.net_ret) - csi_r)
    return np.asarray(exs, dtype=float)


def permutation_kw_and_spread(rets: np.ndarray, labels: np.ndarray, rng: np.random.Generator, n_perm: int = N_PERM):
    uniq = np.unique(labels)
    if len(uniq) < 2 or len(rets) < 5:
        return None, None, None
    groups = [rets[labels == u] for u in uniq]
    if any(len(g) < 2 for g in groups):
        # Fallback if a group has 1 obs
        groups_valid = [g for g in groups if len(g) >= 1]
        if len(groups_valid) < 2:
            return None, None, None
    try:
        kw_h, kw_p = stats.kruskal(*groups)
    except Exception:
        kw_h, kw_p = 0.0, 1.0
    means = [float(g.mean()) for g in groups]
    obs_spread = max(means) - min(means)

    # Permutation test
    cnt_kw = 0
    cnt_sp = 0
    idx_groups = [np.where(labels == u)[0] for u in uniq]
    sizes = [len(ix) for ix in idx_groups]
    for _ in range(n_perm):
        perm = rng.permutation(rets)
        pos = 0
        pg = []
        for sz in sizes:
            pg.append(perm[pos:pos + sz])
            pos += sz
        pm = [float(g.mean()) for g in pg]
        if max(pm) - min(pm) >= obs_spread - 1e-12:
            cnt_sp += 1
        try:
            ph, _ = stats.kruskal(*pg)
            if ph >= kw_h - 1e-12:
                cnt_kw += 1
        except Exception:
            pass
    return float(kw_p), (cnt_kw + 1) / (n_perm + 1), (cnt_sp + 1) / (n_perm + 1)


def run_module1(ledgers: dict[str, pd.DataFrame], mtm_dict: dict, m_pit: pd.DataFrame, sh300: dict, all_sh_dts: list[str]):
    print("[Module 1] Running 4 China Cycles x 7 Targets (strict T-1 PIT)...")
    rng = np.random.default_rng(SEED)
    pit_idx = m_pit.set_index("dt")

    cycles = [
        ("C1_Credit", "信贷与流动性周期", "cn_m1_m2_diff"),
        ("C2_Inventory", "PPI与工业库存周期", "cn_ppi_yoy"),
        ("C3_Commodity", "大宗工业品价格周期", "comm_mom60"),
        ("C4_Amount", "市场成交水位周期", "amount_pct_250d"),
        ("C4_MA200", "市场MA200宽度周期", "pct_above_ma200"),
    ]
    targets = ["comb", "1to2", "2to3", "3to4", "high", "pry", "20cm_5y"]

    tests = []
    breakdown_rows = []
    m1_results = {"tests": [], "robustness_c2_pmi": [], "continuous_spearman": []}

    for tkey in targets:
        df = ledgers[tkey].copy()
        df = df.merge(m_pit, left_on="buy_date", right_on="dt", how="left")
        df["trade_csi_ex"] = csi_trade_excess(df, sh300, all_sh_dts)
        mtm_s = mtm_dict[tkey]
        cal = mtm_s.index.tolist()
        daily_df = pd.DataFrame({
            "dt": cal,
            "r_strat": mtm_s.to_numpy(float),
            "r_csi": [float(pit_idx.loc[d, "csi300_ret"]) if d in pit_idx.index else 0.0 for d in cal],
        })
        for cyc_col, _, _ in cycles + [("C2_Inv_PMI", "", "")]:
            daily_df[cyc_col] = [str(pit_idx.loc[d, cyc_col]) if d in pit_idx.index else "NA" for d in cal]

        for cyc_col, cyc_cn, cont_col in cycles:
            rets = df["net_ret"].to_numpy(float)
            labels = df[cyc_col].astype(str).to_numpy()
            kw_p, perm_kw_p, perm_sp_p = permutation_kw_and_spread(rets, labels, rng)

            # Continuous Spearman test
            cvals = pd.to_numeric(df[cont_col], errors="coerce").to_numpy(float)
            valid_c = ~np.isnan(cvals)
            if valid_c.sum() >= 5:
                sp_rho, sp_p = stats.spearmanr(cvals[valid_c], rets[valid_c])
            else:
                sp_rho, sp_p = np.nan, 1.0

            grp_stats = []
            min_n = 10**9
            for state_val, grp in df.groupby(cyc_col, sort=True):
                tm = trade_metrics(grp["net_ret"].to_numpy(float))
                min_n = min(min_n, tm["n"])
                dsub = daily_df[daily_df[cyc_col] == state_val]
                dm = daily_window_metrics(dsub["r_strat"].to_numpy(float), dsub["r_csi"].to_numpy(float))
                ex_mean = float(grp["trade_csi_ex"].mean() * 100.0) if len(grp) > 0 else 0.0
                row = {
                    "module": "M1_Cycle",
                    "target": tkey,
                    "target_cn": STRAT_NAMES[tkey],
                    "cycle": cyc_col,
                    "cycle_cn": cyc_cn,
                    "state": str(state_val),
                    "n_days": dm["n_days"],
                    "days_share_pct": sf(dm["n_days"] / len(daily_df) * 100.0, 1),
                    "trades_per_100d": sf(tm["n"] / max(1, dm["n_days"]) * 100.0, 2),
                    "n_trades": tm["n"],
                    "wr_pct": tm["wr_pct"],
                    "plr": tm["plr"],
                    "mean_ret_pct": tm["mean_ret_pct"],
                    "median_ret_pct": tm["median_ret_pct"],
                    "stage_trade_nav": tm["nav"],
                    "stage_trade_ret_pct": tm["ret_pct"],
                    "trade_mdd_pct": tm["trade_mdd_pct"],
                    "trade_csi_excess_mean_pp": sf(ex_mean, 2),
                    "daily_regime_ret_pct": dm["daily_ret_pct"],
                    "daily_regime_csi_pct": dm["csi300_ret_pct"],
                    "daily_regime_excess_pp": dm["excess_csi300_pp"],
                    "daily_regime_mdd_pct": dm["daily_mdd_pct"],
                    "ex_top3_nav": tm["ex_top3_nav"],
                }
                grp_stats.append(row)
                breakdown_rows.append(row)

            tests.append({
                "target": tkey,
                "target_cn": STRAT_NAMES[tkey],
                "cycle": cyc_col,
                "cycle_cn": cyc_cn,
                "n_total": int(len(df)),
                "min_group_n": int(min_n if min_n < 10**9 else 0),
                "min_group_n_ge_30": bool(min_n >= 30),
                "kw_p": sf(kw_p, 5),
                "perm_kw_p": sf(perm_kw_p, 5),
                "perm_spread_p": sf(perm_sp_p, 5),
                "cont_var": cont_col,
                "spearman_rho": sf(sp_rho, 4),
                "spearman_p": sf(sp_p, 5),
                "groups": grp_stats,
            })

        # Robustness: C2_Inv_PMI & continuous macro probes
        kw_pmi, perm_pmi, _ = permutation_kw_and_spread(df["net_ret"].to_numpy(float), df["C2_Inv_PMI"].astype(str).to_numpy(), rng, n_perm=2000)
        m1_results["robustness_c2_pmi"].append({
            "target": tkey,
            "kw_p": sf(kw_pmi, 5),
            "perm_kw_p": sf(perm_pmi, 5),
            "counts": df["C2_Inv_PMI"].value_counts().to_dict(),
            "means_pct": {k: sf(v * 100, 2) for k, v in df.groupby("C2_Inv_PMI")["net_ret"].mean().items()},
            "wrs_pct": {k: sf(v * 100, 1) for k, v in df.groupby("C2_Inv_PMI")["net_ret"].apply(lambda x: (x > 0).mean()).items()},
        })

        for cvar in ["m1m2_chg_13w", "cn_new_loan_yoy", "loan12m_chg_13w", "cn_tsf_yoy_diff", "ppi_chg_13w", "cn_pmi_mfg", "cn_ind_prod_yoy", "comm_pct3y", "comm_mom120", "cu_mom60", "sc_mom60", "rb_mom60"]:
            vals = pd.to_numeric(df[cvar], errors="coerce").to_numpy(float)
            mask = ~np.isnan(vals)
            if mask.sum() >= 10:
                rho, pv = stats.spearmanr(vals[mask], df["net_ret"].to_numpy(float)[mask])
                m1_results["continuous_spearman"].append({
                    "target": tkey, "var": cvar, "n": int(mask.sum()), "rho": sf(rho, 4), "p": sf(pv, 5)
                })

    # Apply BH-FDR across the 35 primary tests (and separately across continuous spearman tests)
    qs_kw = bh_fdr([t["perm_kw_p"] if t["perm_kw_p"] is not None else 1.0 for t in tests])
    qs_sp = bh_fdr([t["spearman_p"] if t["spearman_p"] is not None else 1.0 for t in tests])
    for t, qk, qs in zip(tests, qs_kw, qs_sp):
        t["bh_fdr_q_kw"] = sf(qk, 5)
        t["bh_fdr_q_spearman"] = sf(qs, 5)

    qs_cont = bh_fdr([c["p"] for c in m1_results["continuous_spearman"]])
    for c, qc in zip(m1_results["continuous_spearman"], qs_cont):
        c["bh_fdr_q"] = sf(qc, 5)

    m1_results["tests"] = tests
    return m1_results, breakdown_rows


def run_module2(ledgers: dict[str, pd.DataFrame], mtm_dict: dict, m_pit: pd.DataFrame):
    print("[Module 2] Running 4 Real Chinese Macro Eras + 2026 Audit...")
    pit_idx = m_pit.set_index("dt")
    eras = [
        ("Era1_2021", "年代1 (2021景气顶+碳中和大宗牛)", "2021-01-04", "2021-12-31"),
        ("Era2_2022_23H1", "年代2 (2022~2023.06地产出清+外资流出)", "2022-01-01", "2023-06-30"),
        ("Era3_23H2_240923", "年代3 (2023.07~2024.09.23通缩磨底+微盘危机)", "2023-07-01", "2024-09-23"),
        ("Era4_924_2026", "年代4 (2024.09.24~2026.11两万亿活跃新体制)", "2024-09-24", "2026-11-16"),
        ("Y2026", "2026全年单列 (2026-01-01~2026-11-16)", "2026-01-01", "2026-11-16"),
    ]
    targets = ["comb", "1to2", "2to3", "3to4", "high", "pry", "20cm"]
    era_rows = []
    era_summary = {}

    for tkey in targets:
        df = ledgers[tkey]
        mtm_s = mtm_dict[tkey]
        cal = mtm_s.index.tolist()
        r_csi_all = pd.Series([float(pit_idx.loc[d, "csi300_ret"]) if d in pit_idx.index else 0.0 for d in cal], index=cal)
        era_summary[tkey] = []
        for eid, ecn, sdt, edt in eras:
            # Note: 10cm/comb canonical window starts 2021-11-16
            eff_start = sdt if (tkey == "20cm" or sdt >= "2021-11-16") else "2021-11-16"
            sub_t = df[df["buy_date"].between(sdt, edt)]
            tm = trade_metrics(sub_t["net_ret"].to_numpy(float))
            dmask = (mtm_s.index >= eff_start) & (mtm_s.index <= edt)
            dm = daily_window_metrics(mtm_s.to_numpy(float)[dmask], r_csi_all.to_numpy(float)[dmask])
            row = {
                "module": "M2_Era",
                "target": tkey,
                "target_cn": STRAT_NAMES[tkey],
                "era_id": eid,
                "era_cn": ecn,
                "window_effective": f"{eff_start}..{edt}",
                "n_days": dm["n_days"],
                "n_trades": tm["n"],
                "wr_pct": tm["wr_pct"],
                "plr": tm["plr"],
                "mean_ret_pct": tm["mean_ret_pct"],
                "era_nav": dm["daily_nav"],
                "era_ret_pct": dm["daily_ret_pct"],
                "ex_top3_nav": tm["ex_top3_nav"],
                "daily_mdd_pct": dm["daily_mdd_pct"],
                "trade_mdd_pct": tm["trade_mdd_pct"],
                "csi300_ret_pct": dm["csi300_ret_pct"],
                "excess_csi300_pp": dm["excess_csi300_pp"],
                "daily_sharpe": dm["daily_sharpe"],
                "daily_calmar": dm["daily_calmar"],
            }
            era_summary[tkey].append(row)
            era_rows.append(row)
    return era_summary, era_rows


def run_module3(ledgers: dict[str, pd.DataFrame], m_pit: pd.DataFrame, dp_all: pd.DataFrame, csrc_map: dict, sh300: dict, all_sh_dts: list[str]):
    print("[Module 3] Running US 3-Lesson Mirror Verification on A-Share Cyclicals & 6 Strategies...")
    # 1. Compute trailing 250d peak drawdown (adj_close) & industry peer DD30/DD40 shares across A-shares (2015-2026)
    dp = dp_all.sort_values(["c6", "dt"]).copy()
    dp["ind"] = dp["c6"].map(csrc_map)
    dp["adj_open"] = np.where(dp["close"] > 0, dp["open"] * dp["adj_close"] / dp["close"], np.nan)
    dp["prev_adj_close"] = dp.groupby("c6")["adj_close"].shift(1)
    dp["roll_max_250"] = dp.groupby("c6")["adj_close"].transform(lambda s: s.rolling(250, min_periods=120).max())
    dp["dd250"] = dp["adj_close"] / dp["roll_max_250"] - 1.0
    dp["is_dd30"] = (dp["dd250"] <= -0.30).astype(float)
    dp["is_dd40"] = (dp["dd250"] <= -0.40).astype(float)

    # Industry daily peer crash fractions (require >= 10 valid stocks in industry that day)
    valid_ind = dp[dp["ind"].notna() & dp["dd250"].notna()]
    ind_daily = valid_ind.groupby(["dt", "ind"], as_index=False).agg(
        ind_n=("c6", "count"),
        peer_dd30_share=("is_dd30", "mean"),
        peer_dd40_share=("is_dd40", "mean"),
    )
    ind_daily = ind_daily[ind_daily["ind_n"] >= 10].copy()

    # Strictly shift T-1 for strategy trade matching
    all_dts_sorted = sorted(dp["dt"].unique())
    next_dt_map = {all_dts_sorted[i]: all_dts_sorted[i + 1] for i in range(len(all_dts_sorted) - 1)}
    ind_daily_t1 = ind_daily.copy()
    ind_daily_t1["buy_date"] = ind_daily_t1["dt"].map(next_dt_map)
    ind_daily_t1 = ind_daily_t1.dropna(subset=["buy_date"])

    self_t1 = dp[["c6", "dt", "dd250"]].copy()
    self_t1["buy_date"] = self_t1["dt"].map(next_dt_map)
    self_t1 = self_t1.dropna(subset=["buy_date"]).rename(columns={"dd250": "self_dd250_t1"})

    # --- Mirror 3A-1: All A-Share Core Cyclical Stocks (2016-2026 & 2021-2026) non-overlapping monthly rebalance ---
    cyc_dp = dp[dp["ind"].isin(CORE_CYCLICAL_PEER_INDS) & dp["dd250"].notna() & (dp["close"] >= 2.0) & (dp["volume"] > 0)].copy()
    cyc_dp = cyc_dp.merge(ind_daily, on=["dt", "ind"], how="inner")
    # Forward returns: buy at T+1 adj_open (skipping one-word limit-up: open/prev_close >= 1.095 and close==open or volume<=0), hold h days to adj_close[T+1+h]
    cyc_dp["buy_open_t1"] = cyc_dp.groupby("c6")["adj_open"].shift(-1)
    cyc_dp["buy_ret_open_t1"] = cyc_dp["buy_open_t1"] / cyc_dp["adj_close"] - 1.0
    cyc_dp["vol_t1"] = cyc_dp.groupby("c6")["volume"].shift(-1)
    cyc_dp["buy_dt_t1"] = cyc_dp.groupby("c6")["dt"].shift(-1)

    dt_pos = {d: i for i, d in enumerate(all_sh_dts)}
    for h in (20, 60, 120, 250):
        cyc_dp[f"exit_close_{h}"] = cyc_dp.groupby("c6")["adj_close"].shift(-(1 + h))
        cyc_dp[f"exit_dt_{h}"] = cyc_dp.groupby("c6")["dt"].shift(-(1 + h))
        cyc_dp[f"ret_{h}"] = (cyc_dp[f"exit_close_{h}"] / cyc_dp["buy_open_t1"]) * (1.0 - 0.0030) - 1.0

    # Sample every 20 trading days from 2016-01-04 to 2026-09-01
    sample_dts = [d for d in all_dts_sorted if "2016-01-04" <= d <= "2026-09-01"][::20]
    samp = cyc_dp[cyc_dp["dt"].isin(set(sample_dts)) & cyc_dp["buy_open_t1"].notna() & (cyc_dp["vol_t1"] > 0) & (cyc_dp["buy_ret_open_t1"] < 0.095)].copy()

    # Vectorized CSI300 excess on each horizon
    for h in (20, 60, 120, 250):
        csi_b = samp["dt"].map(sh300)
        csi_e = samp[f"exit_dt_{h}"].map(sh300)
        samp[f"ex_{h}"] = samp[f"ret_{h}"] - (csi_e / csi_b - 1.0)

    def _summarize_peer_bucket(sub_df: pd.DataFrame, label: str) -> dict:
        out = {"bucket": label, "n_obs": int(len(sub_df)), "n_dates": int(sub_df["dt"].nunique())}
        for h in (20, 60, 120, 250):
            v = sub_df[f"ex_{h}"].dropna()
            vr = sub_df[f"ret_{h}"].dropna()
            # Date-clustered mean and SE (prevent cross-sectional inflation!)
            dt_means = sub_df.dropna(subset=[f"ex_{h}"]).groupby("dt")[f"ex_{h}"].mean()
            c_mean = float(dt_means.mean() * 100.0) if len(dt_means) > 0 else None
            c_se = float(dt_means.std(ddof=1) / math.sqrt(len(dt_means)) * 100.0) if len(dt_means) > 1 else None
            c_t = (c_mean / c_se) if (c_mean is not None and c_se is not None and c_se > 1e-9) else None
            c_p = float(2 * (1 - stats.t.cdf(abs(c_t), df=max(1, len(dt_means) - 1)))) if c_t is not None else None
            out[f"T+{h}"] = {
                "n_obs": int(len(v)),
                "n_dates": int(len(dt_means)),
                "raw_mean_ret_pct": sf(vr.mean() * 100.0, 2) if len(vr) else None,
                "obs_excess_mean_pp": sf(v.mean() * 100.0, 2) if len(v) else None,
                "date_clustered_excess_pp": sf(c_mean, 2),
                "date_clustered_t": sf(c_t, 2),
                "date_clustered_p": sf(c_p, 5),
                "win_excess_pct": sf((v > 0).mean() * 100.0, 1) if len(v) else None,
            }
        return out

    peer_3a_all = []
    for win_lbl, min_dt in [("2016_2026_10Y", "2016-01-04"), ("2021_2026_5Y", "2021-01-04")]:
        sw = samp[samp["dt"] >= min_dt]
        buckets = [
            (f"{win_lbl}_Baseline_DD30_lt50", sw[sw["peer_dd30_share"] < 0.50]),
            (f"{win_lbl}_Peer_DD30_ge50", sw[sw["peer_dd30_share"] >= 0.50]),
            (f"{win_lbl}_Peer_DD40_ge50", sw[sw["peer_dd40_share"] >= 0.50]),
            (f"{win_lbl}_Peer_Div_DD40ge40_Selfgt_m35", sw[(sw["peer_dd40_share"] >= 0.40) & (sw["dd250"] > -0.35)]),
        ]
        for blbl, bdf in buckets:
            peer_3a_all.append(_summarize_peer_bucket(bdf, blbl))

    # --- Mirror 3A-2 & 3B: Across 6 Short-Term Strategies + Combined ---
    pit_idx = m_pit.set_index("dt")
    strat_mirror_3a = []
    strat_mirror_3b_frames = []

    for tkey in ["comb", "1to2", "2to3", "3to4", "high", "pry", "20cm"]:
        df = ledgers[tkey].copy()
        df["ind"] = df["c6"].map(csrc_map)
        df = df.merge(ind_daily_t1[["buy_date", "ind", "peer_dd30_share", "peer_dd40_share"]], on=["buy_date", "ind"], how="left")
        df = df.merge(self_t1[["buy_date", "c6", "self_dd250_t1"]], on=["buy_date", "c6"], how="left")
        df["cn_ppi_yoy"] = df["buy_date"].map(pit_idx["cn_ppi_yoy"])
        df["comm_pct3y"] = df["buy_date"].map(pit_idx["comm_pct3y"])
        df["C2_Inventory"] = df["buy_date"].map(pit_idx["C2_Inventory"])
        df["C3_Commodity"] = df["buy_date"].map(pit_idx["C3_Commodity"])
        df["sector_type"] = np.where(
            df["ind"].isin(TECH_INDS), "短周期科技",
            np.where(df["ind"].isin(HEAVY_CYCLICAL_INDS), "长周期重资产",
            np.where(df["ind"].notna(), "消费医药金融等其他", "未知行业"))
        )
        df["strategy_key"] = tkey

        # 3A-2: Peer crash >=50% vs <50% on strategy trades
        v30 = df[df["peer_dd30_share"].notna()]
        g_hi30 = v30[v30["peer_dd30_share"] >= 0.50]["net_ret"].to_numpy(float)
        g_lo30 = v30[v30["peer_dd30_share"] < 0.50]["net_ret"].to_numpy(float)
        g_hi40 = v30[v30["peer_dd40_share"] >= 0.50]["net_ret"].to_numpy(float)
        g_lo40 = v30[v30["peer_dd40_share"] < 0.50]["net_ret"].to_numpy(float)
        p_mw30 = float(stats.mannwhitneyu(g_hi30, g_lo30, alternative="two-sided").pvalue) if (len(g_hi30) >= 3 and len(g_lo30) >= 3) else None
        p_mw40 = float(stats.mannwhitneyu(g_hi40, g_lo40, alternative="two-sided").pvalue) if (len(g_hi40) >= 3 and len(g_lo40) >= 3) else None
        strat_mirror_3a.append({
            "target": tkey,
            "target_cn": STRAT_NAMES[tkey],
            "n_covered": int(len(v30)),
            "dd30_ge50": trade_metrics(g_hi30),
            "dd30_lt50": trade_metrics(g_lo30),
            "mw_p_dd30": sf(p_mw30, 5),
            "dd40_ge50": trade_metrics(g_hi40),
            "dd40_lt50": trade_metrics(g_lo40),
            "mw_p_dd40": sf(p_mw40, 5),
        })
        if tkey != "comb":
            strat_mirror_3b_frames.append(df)

    # 3B: Sector Cycle Type x PPI Regime (both Combined N=278 and Pooled 6 Strategies N=539)
    comb_df = ledgers["comb"].copy()
    comb_df["ind"] = comb_df["c6"].map(csrc_map)
    comb_df["cn_ppi_yoy"] = comb_df["buy_date"].map(pit_idx["cn_ppi_yoy"])
    comb_df["comm_pct3y"] = comb_df["buy_date"].map(pit_idx["comm_pct3y"])
    comb_df["C2_Inventory"] = comb_df["buy_date"].map(pit_idx["C2_Inventory"])
    comb_df["sector_type"] = np.where(
        comb_df["ind"].isin(TECH_INDS), "短周期科技",
        np.where(comb_df["ind"].isin(HEAVY_CYCLICAL_INDS), "长周期重资产",
        np.where(comb_df["ind"].notna(), "消费医药金融等其他", "未知行业"))
    )
    pooled_6 = pd.concat(strat_mirror_3b_frames, ignore_index=True)

    def _run_3b_crosstab(dframe: pd.DataFrame, name: str) -> dict:
        d = dframe[dframe["sector_type"] != "未知行业"].copy()
        d["ppi_regime"] = np.where(d["cn_ppi_yoy"] > 0, "PPI正值扩张(>0%)", "PPI负值通缩(<=0%)")
        cells = []
        for (stype, preg), grp in d.groupby(["sector_type", "ppi_regime"]):
            tm = trade_metrics(grp["net_ret"].to_numpy(float))
            cells.append({"sector_type": stype, "ppi_regime": preg, **tm})
        # Also test PPI > 0 vs <= 0 specifically within 短周期科技 and within 长周期重资产
        within = {}
        for stype in ["短周期科技", "长周期重资产", "消费医药金融等其他"]:
            s = d[d["sector_type"] == stype]
            pos = s[s["cn_ppi_yoy"] > 0]["net_ret"].to_numpy(float)
            neg = s[s["cn_ppi_yoy"] <= 0]["net_ret"].to_numpy(float)
            p_mw = float(stats.mannwhitneyu(pos, neg).pvalue) if (len(pos) >= 3 and len(neg) >= 3) else None
            within[stype] = {"ppi_pos": trade_metrics(pos), "ppi_neg": trade_metrics(neg), "mw_p": sf(p_mw, 5)}
        # Also check Tech vs Heavy overall
        t_rets = d[d["sector_type"] == "短周期科技"]["net_ret"].to_numpy(float)
        h_rets = d[d["sector_type"] == "长周期重资产"]["net_ret"].to_numpy(float)
        p_th = float(stats.mannwhitneyu(t_rets, h_rets).pvalue) if (len(t_rets) >= 3 and len(h_rets) >= 3) else None
        return {
            "dataset": name,
            "n_classified": int(len(d)),
            "tech_vs_heavy_mw_p": sf(p_th, 5),
            "cells": cells,
            "within_sector_ppi_split": within,
        }

    return {
        "mirror_3A1_all_ashare_cyclicals": peer_3a_all,
        "mirror_3A2_short_term_strategies": strat_mirror_3a,
        "mirror_3B_sector_ppi_combined": _run_3b_crosstab(comb_df, "V20.0合体纯单仓(N=278)"),
        "mirror_3B_sector_ppi_pooled6": _run_3b_crosstab(pooled_6, "六策略合池(N=539)"),
    }


def run_module4(ledgers: dict[str, pd.DataFrame], mtm_dict: dict, m_pit: pd.DataFrame):
    print("[Module 4] Running IS -> OOS China Cycle Position Switch & Control Audit on V20.0 Combined...")
    comb = ledgers["comb"].copy()
    pit_idx = m_pit.set_index("dt")
    mtm_s = mtm_dict["comb"]
    cal = mtm_s.index.tolist()
    r_csi_all = pd.Series([float(pit_idx.loc[d, "csi300_ret"]) if d in pit_idx.index else 0.0 for d in cal], index=cal)

    # 20d realized CSI300 volatility strictly at T-1 for 1/vol risk control baseline
    csi_vol20 = pd.Series([float(pit_idx.loc[d, "bench_vol_20d"]) if (d in pit_idx.index and pd.notna(pit_idx.loc[d, "bench_vol_20d"]) and pit_idx.loc[d, "bench_vol_20d"] > 0) else np.nan for d in cal], index=cal).ffill().bfill()

    cycle_cols = ["C1_Credit", "C2_Inventory", "C3_Commodity", "C4_Amount", "C4_MA200"]
    for c in cycle_cols:
        comb[c] = comb["buy_date"].map(pit_idx[c])

    is_mask_t = comb["buy_date"] <= "2024-06-30"
    oos_mask_t = comb["buy_date"] >= "2024-07-01"
    y26_mask_t = comb["buy_date"] >= "2026-01-01"

    # Scan every single cycle state in IS ONLY (2021-11-16 ~ 2024-06-30)
    is_scan = []
    comb_is = comb[is_mask_t]
    is_base_mean = float(comb_is["net_ret"].mean())
    for c in cycle_cols:
        for state_val, grp in comb_is.groupby(c):
            rets_in = grp["net_ret"].to_numpy(float)
            rets_out = comb_is[comb_is[c] != state_val]["net_ret"].to_numpy(float)
            p_mw = float(stats.mannwhitneyu(rets_in, rets_out, alternative="two-sided").pvalue) if (len(rets_in) >= 5 and len(rets_out) >= 5) else 1.0
            is_scan.append({
                "cycle": c,
                "state": str(state_val),
                "is_n": int(len(rets_in)),
                "is_wr_pct": sf((rets_in > 0).mean() * 100.0, 1),
                "is_mean_ret_pct": sf(rets_in.mean() * 100.0, 2),
                "is_diff_vs_rest_pp": sf((rets_in.mean() - rets_out.mean()) * 100.0, 2),
                "is_mw_p": sf(p_mw, 5),
            })
    is_scan.sort(key=lambda x: (x["is_mean_ret_pct"] if x["is_mean_ret_pct"] is not None else 999.0))

    # Build helper to evaluate any weighting policy across FULL, IS, OOS, Y2026
    # A policy gives weight w_trade in [0, 1] per trade on buy_date, and scales each trade's MTM days by w_trade!
    # Wait: mathematically exact daily return of holding fraction `w` of strategy and `(1-w)` cash (0%):
    # Within trade i, daily portfolio multiplier is `(1 - w) + w * trade_cum_path_at_t / trade_cum_path_at_t-1`?
    # Even cleaner & standard: scale trade `i` daily return contribution by `w_i`? No, wait: if w=0.5 static or dynamic,
    # scaling trade return `r_trade_net` at entry so `w * r_trade_net` is earned, we can compute daily MTM of each trade scaled by `w_i` on its active days (so `prod(1 + w_i * r_seg)`? Wait: if trade drops -10%, 0.5*position loses -5% — exact path on trade i is `mult_i_scaled(t) = (1 - w_i + w_i * V_i(t)) / (1 - w_i + w_i * V_i(t-1))`!).
    # Let's implement exact `1 - w + w * V_i(t)` MTM path scaling!

    # Precompute per-trade MTM day multipliers from `mtm_dict["comb"]` or directly from dp
    # Actually `comb` trades are strictly non-overlapping single-slot! Let's verify zero overlap on dates (except exit_date == next_buy_date where exit happens before buy).
    # For each trade i, we know buy_date and exit_date; let's compute exact scaled daily return series!
    d_idx_map = {d: i for i, d in enumerate(cal)}
    dp_comb = dp_lookup_cache(comb, cal)

    def eval_weight_policy(weights: np.ndarray, label: str) -> dict:
        ser = np.zeros(len(cal), dtype=float)
        t_scaled_rets = comb["net_ret"].to_numpy(float) * weights
        for idx_t, r in enumerate(comb.itertuples(index=False)):
            w = float(weights[idx_t])
            if w <= 0.0:
                continue
            segs = dp_comb[idx_t]
            # Cumulative value path of trade relative to 1.0
            v_prev = 1.0
            cum_v = 1.0
            for t_i, mult_raw in segs:
                cum_v *= mult_raw
                p_prev = (1.0 - w) + w * v_prev
                p_cur = (1.0 - w) + w * cum_v
                seg_r = p_cur / p_prev - 1.0
                if abs(ser[t_i]) > 1e-15:
                    ser[t_i] = (1.0 + ser[t_i]) * (1.0 + seg_r) - 1.0
                else:
                    ser[t_i] = seg_r
                v_prev = cum_v

        res = {"policy": label, "avg_weight": sf(float(weights.mean()), 4), "active_trades": int((weights > 0).sum())}
        wins = [
            ("FULL", "2021-11-16", "2026-11-16", np.ones(len(comb), dtype=bool)),
            ("IS",   "2021-11-16", "2024-06-30", is_mask_t.to_numpy()),
            ("OOS",  "2024-07-01", "2026-11-16", oos_mask_t.to_numpy()),
            ("Y2026","2026-01-01", "2026-11-16", y26_mask_t.to_numpy()),
        ]
        for wname, s, e, tmask in wins:
            dmask = np.array([(s <= d <= e) for d in cal], dtype=bool)
            dm = daily_window_metrics(ser[dmask], r_csi_all.to_numpy(float)[dmask])
            sub_r = t_scaled_rets[tmask & (weights > 0)]
            if len(sub_r) > 5:
                s_ix = np.argsort(sub_r)
                ex5 = float(np.prod(1.0 + sub_r[s_ix[:-5]]))
            else:
                ex5 = float(np.prod(1.0 + sub_r)) if len(sub_r) > 0 else 1.0
            cagr = (dm["daily_nav"] ** (TRD_DAYS_YEAR / max(1, dm["n_days"])) - 1.0) * 100.0
            res[wname] = {**dm, "cagr_pct": sf(cagr, 2), "ex_top5_nav": sf(ex5, 4), "n_trades_taken": int(len(sub_r))}
        return res

    # Candidate switches to test in OOS horse race:
    # 1. Baseline 100%
    # 2. Worst IS state (with n >= 15 in IS)
    worst_is_candidates = [x for x in is_scan if x["is_n"] >= 15]
    top_cand = worst_is_candidates[0]
    policies = [eval_weight_policy(np.ones(len(comb), dtype=float), "Baseline_100pct_Full")]

    # Test top worst IS candidate AND key textbook adverse states (紧信用下行, 主动去库通缩, 大宗暴涨过热, 缩量冰点)
    test_specs = [(top_cand["cycle"], top_cand["state"], "Worst_IS_State")]
    for c_col, st_val, tag in [
        ("C1_Credit", "紧信用下行", "TightCredit"),
        ("C2_Inventory", "主动去库通缩", "DeflationDestock"),
        ("C3_Commodity", "大宗暴涨过热", "CommOverheat"),
        ("C4_Amount", "缩量冰点(<25%)", "LowAmtFreeze"),
    ]:
        if (c_col, st_val) != (top_cand["cycle"], top_cand["state"]):
            test_specs.append((c_col, st_val, tag))

    for c_col, st_val, tag in test_specs:
        is_adv = (comb[c_col] == st_val).to_numpy()
        w_half = np.where(is_adv, 0.5, 1.0)
        w_zero = np.where(is_adv, 0.0, 1.0)
        avg_half = float(w_half.mean())
        avg_zero = float(w_zero.mean())
        policies.append(eval_weight_policy(w_half, f"Switch_{tag}_Half50 ({c_col}={st_val})"))
        policies.append(eval_weight_policy(w_zero, f"Switch_{tag}_Stop0 ({c_col}={st_val})"))
        policies.append(eval_weight_policy(np.full(len(comb), avg_half), f"Static_SameAvgExp_{avg_half:.2f} ({tag}_Half)"))
        policies.append(eval_weight_policy(np.full(len(comb), avg_zero), f"Static_SameAvgExp_{avg_zero:.2f} ({tag}_Stop)"))

    # Pure 1/vol control normalized to same average exposure as Half50 & Stop0 of top_cand
    t_vols = np.array([float(csi_vol20.loc[d]) for d in comb["buy_date"]], dtype=float)
    raw_inv_vol = (1.0 / np.maximum(t_vols, 1e-4))
    raw_inv_vol = raw_inv_vol / np.mean(raw_inv_vol[is_mask_t])  # normalized on IS only!
    for target_avg, lbl in [(float(np.where(comb[top_cand["cycle"]] == top_cand["state"], 0.5, 1.0).mean()), "Half50"),
                            (float(np.where(comb[top_cand["cycle"]] == top_cand["state"], 0.0, 1.0).mean()), "Stop0")]:
        w_vol = np.clip(raw_inv_vol * target_avg, 0.0, 1.0)
        policies.append(eval_weight_policy(w_vol, f"Control_1overVol_Matched_{lbl} (avg={w_vol.mean():.2f})"))

    return {"is_scan_all_states": is_scan, "worst_is_candidate_ge15": top_cand, "oos_horse_race": policies}


_DP_CACHE_FOR_M4 = None


def dp_lookup_cache(comb: pd.DataFrame, cal: list[str]):
    return _DP_CACHE_FOR_M4


def build_comb_segments(comb: pd.DataFrame, dp: pd.DataFrame, cal: list[str]):
    needed = set(comb["c6"].unique())
    sub_dp = dp[dp["c6"].isin(needed)].copy()
    sub_dp["adjf"] = np.where((sub_dp["close"] > 0) & (sub_dp["adj_close"] > 0), sub_dp["adj_close"] / sub_dp["close"], 1.0)
    dmap = {(r.c6, r.dt): (float(r.adj_close), float(r.adjf)) for r in sub_dp.itertuples(index=False)}
    dt_to_idx = {d: i for i, d in enumerate(cal)}
    all_segs = []
    for r in comb.itertuples(index=False):
        bi = dt_to_idx[r.buy_date]
        ei = dt_to_idx[r.exit_date]
        b_adj = float(r.buy_px_adj)
        prev_v, last_c = b_adj, b_adj
        segs = []
        for t in range(bi, ei):
            bt = dmap.get((r.c6, cal[t]))
            cur_c = bt[0] if (bt and bt[0] > 0) else last_c
            segs.append((t, cur_c / prev_v))
            prev_v, last_c = cur_c, cur_c
        segs.append((ei, (b_adj * (1.0 + float(r.net_ret))) / prev_v))
        prod_m = float(np.prod([m for _, m in segs]))
        target_m = 1.0 + float(r.net_ret)
        if prod_m > 0 and abs(prod_m - target_m) > 1e-9:
            segs[-1] = (segs[-1][0], segs[-1][1] * (target_m / prod_m))
        all_segs.append(segs)
    return all_segs


def main():
    t0 = time.time()
    m_pit, sh300, all_sh_dts = load_pit_macro_and_cycles()
    ledgers = load_all_ledgers()

    # Load CSRC industry map (PIT clean)
    csrc = pd.read_csv(SIM / "data/csrc_industry_pit_clean.csv")
    csrc["c6"] = csrc["sec_code"].astype(str).str.zfill(6)
    csrc_map = csrc[csrc["industry"].notna()].drop_duplicates("c6", keep="first").set_index("c6")["industry"].to_dict()

    # Load all A-share daily data (2015-01-01 ~ 2026-11-24) once for both MTM & Module 3
    print("[Data] Loading A-share daily price DB (2015-2026)...")
    cols = ["date", "ticker", "open", "close", "adj_close", "volume"]
    flt = ds.field("date") >= pd.Timestamp("2015-01-01")
    da = ds.dataset(str(SIM / "data/cn_hk_price_db/a_daily.parquet")).scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(str(SIM / "data/cn_hk_price_db/a_delisted_daily.parquet")).scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    dp_all = pd.concat([da, dd], ignore_index=True)
    dp_all["c6"] = dp_all["ticker"].astype(str).str[:6]
    dp_all = dp_all[dp_all["ticker"].astype(str).str.endswith((".SH", ".SZ"))].copy()
    dp_all["dt"] = dp_all["date"].dt.strftime("%Y-%m-%d")
    dp_all = dp_all.sort_values(["c6", "dt", "dl"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    cal_5y = sorted([d for d in m_pit["dt"] if "2021-11-16" <= d <= "2026-11-16"])
    cal_full = sorted([d for d in m_pit["dt"] if "2021-01-04" <= d <= "2026-11-16"])
    mtm_dict = build_daily_mtm(ledgers, dp_all[dp_all["dt"] >= "2020-12-01"], cal_5y, cal_full)

    global _DP_CACHE_FOR_M4
    _DP_CACHE_FOR_M4 = build_comb_segments(ledgers["comb"], dp_all[dp_all["dt"] >= "2021-11-01"], cal_5y)

    m1_res, m1_rows = run_module1(ledgers, mtm_dict, m_pit, sh300, all_sh_dts)
    m2_res, m2_rows = run_module2(ledgers, mtm_dict, m_pit)
    m3_res = run_module3(ledgers, m_pit, dp_all, csrc_map, sh300, all_sh_dts)
    m4_res = run_module4(ledgers, mtm_dict, m_pit)

    # Save breakdown CSV
    df_csv = pd.DataFrame(m1_rows + m2_rows)
    csv_path = OUT_DIR / "rd031_cycle_breakdown_tables.csv"
    df_csv.to_csv(csv_path, index=False, encoding="utf-8-sig")

    # Save audit JSON
    audit = {
        "meta": {
            "task": "RD031_China_Macro_Commodity_Cycle_vs_6_Strategies",
            "audit_date": "2026-11-25",
            "data_as_of_date": "2026-11-24",
            "d12_yfinance_imported": "yfinance" in sys.modules,
            "pit_alignment": "strict_T_minus_1_after_official_release_lag",
            "n_perm": N_PERM,
            "elapsed_sec": round(time.time() - t0, 2),
            "targets_summary": {
                k: {
                    "name_cn": STRAT_NAMES[k],
                    "n_trades": int(len(df)),
                    "date_range": f"{df['buy_date'].min()}..{df['buy_date'].max()}",
                    **trade_metrics(df["net_ret"].to_numpy(float)),
                }
                for k, df in ledgers.items()
            },
        },
        "module1_four_cycles": m1_res,
        "module2_four_eras": m2_res,
        "module3_us_mirror": m3_res,
        "module4_oos_switch_verdict": m4_res,
    }
    json_path = OUT_DIR / "rd031_china_cycle_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(sanitize_json(audit), f, ensure_ascii=False, indent=2)

    print(f"[DONE] Saved {json_path} and {csv_path} in {time.time() - t0:.2f}s")
    # Print concise executive readout
    print("\n=== MODULE 1: BH-FDR Survivors (q < 0.15) ===")
    for t in m1_res["tests"]:
        if (t["bh_fdr_q_kw"] is not None and t["bh_fdr_q_kw"] < 0.15) or (t["perm_kw_p"] is not None and t["perm_kw_p"] < 0.05):
            print(f"  {t['target']:7s} x {t['cycle']:13s} | min_n={t['min_group_n']:2d} | perm_p={t['perm_kw_p']:.4f} | FDR_q={t['bh_fdr_q_kw']:.4f} | sp_p={t['spearman_p']:.4f}")
    print("  Min FDR q across all 35 KW tests:", min(t["bh_fdr_q_kw"] for t in m1_res["tests"]))
    print("  Min FDR q across all 35 Spearman tests:", min(t["bh_fdr_q_spearman"] for t in m1_res["tests"]))

    print("\n=== MODULE 2: Combined Era Summary ===")
    for r in m2_res["comb"]:
        print(f"  {r['era_id']:17s} | n={r['n_trades']:3d} | wr={r['wr_pct']}% | plr={r['plr']} | nav={r['era_nav']} | mdd={r['daily_mdd_pct']}% | csi={r['csi300_ret_pct']}% | ex={r['excess_csi300_pp']}pp")

    print("\n=== MODULE 3A-1: A-Share Cyclicals Peer Crash ===")
    for b in m3_res["mirror_3A1_all_ashare_cyclicals"]:
        print(f"  {b['bucket']:42s} | T+60={b['T+60']['date_clustered_excess_pp']}pp (p={b['T+60']['date_clustered_p']}) | T+250={b['T+250']['date_clustered_excess_pp']}pp (p={b['T+250']['date_clustered_p']})")

    print("\n=== MODULE 4: OOS Horse Race ===")
    print("  Worst IS candidate (n>=15):", m4_res["worst_is_candidate_ge15"])
    for p in m4_res["oos_horse_race"][:9]:
        print(f"  {p['policy'][:42]:42s} | OOS nav={p['OOS']['daily_nav']} cagr={p['OOS']['cagr_pct']}% mdd={p['OOS']['daily_mdd_pct']}% sh={p['OOS']['daily_sharpe']} cal={p['OOS']['daily_calmar']} ex5={p['OOS']['ex_top5_nav']}")


if __name__ == "__main__":
    main()

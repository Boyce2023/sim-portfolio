#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Track B2 Evaluation Utilities: D15 Multi-Window, Daily MTM, BH-FDR, Diff Tests, CSCV PBO. Pure compounding only."""
import itertools, math, sys
import numpy as np
import pandas as pd
from scipy import stats

assert "yfinance" not in sys.modules, "D12 violation"
TRD_DAYS_YEAR = 242.0

WINDOWS_20CM = [
    ("FULL", "2021-01-04", "2026-11-23"),
    ("Near3Y", "2023-11-24", "2026-11-23"),
    ("IS", "2021-01-04", "2024-06-30"),
    ("OOS_BLIND", "2024-07-04", "2026-11-23"),
    ("OOS_RT", "2024-09-01", "2026-11-23"),
    ("Y26", "2026-01-01", "2026-11-23"),
]

WINDOWS_V20 = [
    ("FULL", "2021-11-16", "2026-11-16"),
    ("Near3Y", "2023-11-24", "2026-11-16"),
    ("IS", "2021-11-16", "2024-06-30"),
    ("OOS_BLIND", "2024-07-04", "2026-11-16"),
    ("OOS_RT", "2024-09-01", "2026-11-16"),
    ("Y26", "2026-01-01", "2026-11-16"),
]


def sf(x, d=4):
    if x is None:
        return None
    v = float(x)
    return None if (math.isnan(v) or math.isinf(v)) else round(v, d)


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
    arr = np.array([1.0 if (p is None or np.isnan(p)) else float(p) for p in pvals], dtype=float)
    m = len(arr)
    if m == 0:
        return []
    order = np.argsort(arr)
    q = np.empty(m, dtype=float)
    prev = 1.0
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        val = min(prev, arr[idx] * m / rank)
        q[idx] = min(1.0, val)
        prev = q[idx]
    return [round(float(x), 6) for x in q]


def get_csi_ret(sh300: dict, all_sh_dts: list[str], sdt: str, edt: str) -> float:
    prevs = [d for d in all_sh_dts if d < sdt]
    posts = [d for d in all_sh_dts if d <= edt]
    if not posts:
        return 0.0
    p0 = sh300[prevs[-1]] if prevs else sh300[all_sh_dts[0]]
    p1 = sh300[posts[-1]]
    return float((p1 / p0 - 1.0) * 100.0)


def build_20cm_slot1_mtm(tr_slot1: pd.DataFrame, cal_dts: list[str], dt_idx: dict, bar_lu: dict, tpe_mod) -> np.ndarray:
    if tr_slot1.empty:
        return np.zeros(len(cal_dts), dtype=float)
    d = tr_slot1.copy()
    d["code"] = d["c6"].astype(str).str.zfill(6)
    d["buy_price_val"] = d["buy_px"].astype(float)
    d["is_adj_px"] = True
    d["net_ret"] = d["net_ret_eval"].astype(float) if "net_ret_eval" in d.columns else d["net_ret"].astype(float)
    dr, _ = tpe_mod.build_daily_mtm_series(d, cal_dts, dt_idx, bar_lu)
    return dr


def calc_window_d15(
    slot_df: pd.DataFrame, raw_df: pd.DataFrame, daily_r: np.ndarray,
    cal_dts: list[str], dt_idx: dict, sh300: dict, all_sh_dts: list[str],
    sdt: str, edt: str,
) -> dict:
    csi_pct = get_csi_ret(sh300, all_sh_dts, sdt, edt)
    sub = slot_df[(slot_df["buy_date"] >= sdt) & (slot_df["buy_date"] <= edt)] if not slot_df.empty else pd.DataFrame()
    raw_sub = raw_df[(raw_df["buy_date"] >= sdt) & (raw_df["buy_date"] <= edt)] if not raw_df.empty else pd.DataFrame()
    win_idx = [dt_idx[d] for d in cal_dts if sdt <= d <= edt]
    dr = daily_r[win_idx] if win_idx else np.zeros(1)
    T = len(dr)
    mtm_nav = float(np.prod(1.0 + dr))
    cum_d = np.cumprod(1.0 + dr)
    pk_d = np.maximum.accumulate(np.insert(cum_d, 0, 1.0))[1:]
    d_mdd = float(np.max((pk_d - cum_d) / pk_d) * 100.0) if T > 0 else 0.0
    sd = float(np.std(dr, ddof=1)) if T > 1 else 0.0
    sharpe = float(np.mean(dr) / sd * math.sqrt(TRD_DAYS_YEAR)) if sd > 1e-12 else 0.0
    cagr = (mtm_nav ** (TRD_DAYS_YEAR / T) - 1.0) * 100.0 if (T > 0 and mtm_nav > 0) else -100.0
    calmar = (cagr / d_mdd) if d_mdd > 1e-6 else 0.0

    ew_nav = 1.0
    if not raw_sub.empty:
        ew_r = raw_sub.groupby("buy_date")["net_ret"].mean().to_numpy(dtype=float)
        ew_nav = float(np.prod(1.0 + ew_r))

    if sub.empty:
        return {
            "raw_n": int(len(raw_sub)), "n": 0, "wr_pct": 0.0, "plr": 0.0, "mean_pct": 0.0,
            "nav": 1.0, "ew_nav": round(ew_nav, 4), "mtm_nav": round(mtm_nav, 4),
            "ex_top5_nav": 1.0, "trade_mdd_pct": 0.0, "daily_mdd_pct": round(d_mdd, 2),
            "daily_sharpe": round(sharpe, 3), "daily_calmar": round(calmar, 2),
            "csi300_pct": round(csi_pct, 2), "excess_csi300_pp": round(-csi_pct, 2),
        }

    ret_col = "net_ret_eval" if "net_ret_eval" in sub.columns else "net_ret"
    rets = sub[ret_col].to_numpy(dtype=float)
    w, l = rets[rets > 0], rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    plr = float(w.mean() / abs(l.mean())) if (len(w) and len(l) and l.mean() < 0) else (99.0 if len(w) else 0.0)
    tr_nav = float(np.prod(1.0 + rets))
    ex5 = float(np.prod(1.0 + np.sort(rets)[:-5])) if len(rets) > 5 else 1.0
    cum_t = np.cumprod(1.0 + rets)
    pk_t = np.maximum.accumulate(np.insert(cum_t, 0, 1.0))[1:]
    t_mdd = float(np.max((pk_t - cum_t) / pk_t) * 100.0)
    return {
        "raw_n": int(len(raw_sub)), "n": int(len(rets)),
        "wr_pct": round(wr, 2), "plr": round(plr, 2), "mean_pct": round(float(rets.mean() * 100.0), 2),
        "nav": round(tr_nav, 4), "ew_nav": round(ew_nav, 4), "mtm_nav": round(mtm_nav, 4),
        "ex_top5_nav": round(ex5, 4), "trade_mdd_pct": round(t_mdd, 2), "daily_mdd_pct": round(d_mdd, 2),
        "daily_sharpe": round(sharpe, 3), "daily_calmar": round(calmar, 2),
        "csi300_pct": round(csi_pct, 2), "excess_csi300_pp": round((tr_nav - 1.0) * 100.0 - csi_pct, 2),
    }


def eval_all_windows(slot_df, raw_df, daily_r, cal_dts, dt_idx, sh300, all_sh_dts, windows):
    return {lbl: calc_window_d15(slot_df, raw_df, daily_r, cal_dts, dt_idx, sh300, all_sh_dts, sdt, edt)
            for lbl, sdt, edt in windows}


def cscv_pbo_matrix(R: np.ndarray, ng_list=(8, 10)) -> dict:
    if R.ndim != 2 or R.shape[1] < 2 or R.shape[0] < 40:
        return {f"S{ng}": {"pbo_pct": None, "mean_rank_oos": None} for ng in ng_list}
    out = {}
    T = R.shape[0]
    for ng in ng_list:
        gs = T // ng
        gidx = [list(range(i * gs, (i + 1) * gs if i < ng - 1 else T)) for i in range(ng)]
        omegas = []
        for te in itertools.combinations(range(ng), ng // 2):
            trg = [k for k in range(ng) if k not in te]
            rt = R[[x for k in trg for x in gidx[k]]]
            re_ = R[[x for k in te for x in gidx[k]]]
            sdt, sde = rt.std(0, ddof=1), re_.std(0, ddof=1)
            st = np.divide(rt.mean(0), sdt, out=np.full(R.shape[1], -1e9), where=sdt > 1e-12)
            se = np.divide(re_.mean(0), sde, out=np.full(R.shape[1], -1e9), where=sde > 1e-12)
            b = int(np.argmax(st))
            omegas.append(float(np.mean(se > se[b])))
        out[f"S{ng}"] = {"pbo_pct": round(float(np.mean(np.array(omegas) > 0.50) * 100.0), 2),
                         "mean_rank_oos": round(float(np.mean(omegas)), 4)}
    return out


def paired_daily_pval(dr_new: np.ndarray, dr_base: np.ndarray) -> float:
    diff = np.log1p(dr_new) - np.log1p(dr_base)
    nz = np.abs(diff) > 1e-12
    if nz.sum() < 3:
        return 1.0
    sd = float(np.std(diff, ddof=1))
    if sd < 1e-12:
        return 1.0
    t_val = float(np.mean(diff) / sd * math.sqrt(len(diff)))
    return float(2.0 * (1.0 - stats.t.cdf(abs(t_val), df=len(diff) - 1)))

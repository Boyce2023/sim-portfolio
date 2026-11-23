#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Part B2: Red-Team Independent Ledger & Stress Audit (Read-Only)
Audits the 5 active V19.1 strategies + 5-strategy combined V19.1 single-slot ledger
against raw daily bars (a_daily.parquet + a_delisted_daily.parquet) and CSI 300 cache.
Never modifies any active ledger or production script.
"""
import os
import sys
import json
import math
import pickle
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance must never be imported"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock/redteam_full_audit_20261123/partB2_ledger_stress_audit"
os.makedirs(OUT_DIR, exist_ok=True)

PATHS = {
    "3to4_v41": f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4/ledger_3to4_xf30_std.csv",
    "high_v51_partA": f"{SIM}/backtests_astock/clean_rebacktest_20261116/partA_high_3to4/ledger_base_high_v51.csv",
    "high_v51_morn42": f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113/v5_morn_42_ledger.csv",
    "high_v51_trainer42": f"{SIM}/backtests_astock/trainer_high_v51/v51_ledger_42.csv",
    "high_v51_sub2base43": f"{SIM}/backtests_astock/sandbox_lab/golden_regime_20261113/sub2_baseline_v5_1_ledger.csv",
    "2to3_xf30_t2": f"{SIM}/backtests_astock/exit_factors_v2_20261118/f2_2to3/ledger_xf30_t2_std90.csv",
    "2to3_opt_v21_t2": f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/ledger_opt_t2_std90.csv",
    "1to2_v19": f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117/ledger_upg_1to2.csv",
    "combined_v191": f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117/ledger_combined_5strat_v191_slot1.csv",
}


def reconstruct_pry_v21() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reconstruct Pry V2.1 (XF30_V21, score >= 165) ss165 (16 trades) and daily top1 (25 trades)."""
    f3_dir = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"
    s3_dir = f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s3_pry_exit"
    for d in (s3_dir, f3_dir):
        if d not in sys.path:
            sys.path.insert(0, d)
    import backtest_30_factors as bt
    from run_f3_audit_part1 import make_xf30_spec

    cache = pickle.load(open(f"{f3_dir}/_cache_feats_830.pkl", "rb"))
    sub, feats = cache["sub"], cache["feats"]
    cb = pickle.load(open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl", "rb"))["code_bars"]
    r, ed, hd, eh, rsn = bt.run_spec(sub, cb, feats, make_xf30_spec(5, 0.70, 10, 0.03, True))

    rows = []
    for i, row in enumerate(sub.itertuples(index=False)):
        d = cb[row.c6]
        p0 = int(row.p0)
        pe = d["date_to_pos"].get(ed[i])
        bpx = float(row.buy_px)
        af = float(d["adjf"][pe] / d["adjf"][p0]) if pe is not None else 1.0
        epx = (float(r[i]) + 1.0) / 0.9980 * bpx / af if not np.isnan(r[i]) else np.nan
        rows.append({
            "code": str(row.code).zfill(6),
            "name": str(row.name),
            "buy_date": str(row.buy_date),
            "buy_hhmm": 925,
            "buy_price": round(bpx, 2),
            "exit_date": str(ed[i]),
            "exit_hhmm": int(eh[i]),
            "exit_price": round(epx, 2),
            "net_ret": float(r[i]),
            "score": int(row.score),
            "bias10": float(row.bias10),
            "hold_days": int(hd[i]),
            "exit_reason": str(rsn[i]),
        })
    ldf = pd.DataFrame(rows)
    p165 = ldf[ldf["score"] >= 165].sort_values(["buy_date", "score", "bias10"], ascending=[True, False, True])

    ss_l, fa = [], ""
    for rr in p165.itertuples(index=False):
        if fa == "" or rr.buy_date > fa:
            ss_l.append(rr._asdict())
            fa = rr.exit_date
    ss165 = pd.DataFrame(ss_l)
    top1 = p165.groupby("buy_date", as_index=False).first()
    ss165.to_csv(f"{OUT_DIR}/reconstructed_pry_v21_ss165.csv", index=False, encoding="utf-8-sig")
    top1.to_csv(f"{OUT_DIR}/reconstructed_pry_v21_top1.csv", index=False, encoding="utf-8-sig")
    return ss165, top1


def load_daily_truth(codes_needed: set[str]) -> tuple[dict, pd.DataFrame]:
    """Load raw unadjusted OHLC + prev_close + qfq_factor from a_daily & a_delisted_daily."""
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    dt_cut = pd.Timestamp("2021-09-01")
    da = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", columns=cols, filters=[("date", ">=", dt_cut)])
    dd = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols, filters=[("date", ">=", dt_cut)])
    da["c6"] = da["ticker"].str[:6]
    dd["c6"] = dd["ticker"].str[:6]
    da = da[da["c6"].isin(codes_needed)].copy()
    dd = dd[dd["c6"].isin(codes_needed)].copy()
    all_df = pd.concat([da, dd], ignore_index=True)
    all_df["dt"] = all_df["date"].dt.strftime("%Y-%m-%d")
    all_df.sort_values(["c6", "dt"], inplace=True)
    all_df.drop_duplicates(subset=["c6", "dt"], keep="first", inplace=True)
    all_df["prev_close"] = all_df.groupby("c6")["close"].shift(1)
    all_df["prev_qfq"] = all_df.groupby("c6")["qfq_factor"].shift(1)

    bar_map = {}
    for r in all_df.itertuples(index=False):
        bar_map[(r.c6, r.dt)] = {
            "open": float(r.open),
            "high": float(r.high),
            "low": float(r.low),
            "close": float(r.close),
            "adj_close": float(r.adj_close),
            "qfq_factor": float(r.qfq_factor),
            "prev_close": float(r.prev_close) if pd.notna(r.prev_close) else np.nan,
            "prev_qfq": float(r.prev_qfq) if pd.notna(r.prev_qfq) else np.nan,
        }
    return bar_map, all_df


def limit_prices(c6: str, prev_close: float, bar: dict) -> tuple[float, float, float]:
    """Return (pct_limit, zt_px, dt_px). Detect 20% ChiNext/STAR vs 10% main board (and check if 5% ST)."""
    if np.isnan(prev_close) or prev_close <= 0:
        return 0.10, np.nan, np.nan
    if c6.startswith(("300", "301", "688", "689")):
        pct = 0.20
    elif c6.startswith(("8", "4", "92")):
        pct = 0.30
    else:
        pct = 0.10
        # Check if price moved inside 5% ST cap if high/low strictly bounded near 5% (heuristic flag only)
    zt = round(prev_close * (1.0 + pct) + 1e-8, 2)
    dt = round(prev_close * (1.0 - pct) + 1e-8, 2)
    return pct, zt, dt


def norm_ledger(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["code"] = d["code"].astype(str).str.strip().str.zfill(6)
    d["buy_date"] = d["buy_date"].astype(str).str[:10]
    d["exit_date"] = d["exit_date"].astype(str).str[:10]
    if "buy_hhmm" not in d.columns:
        d["buy_hhmm"] = 925
    if "exit_hhmm" not in d.columns:
        d["exit_hhmm"] = 1500
    d["buy_hhmm"] = pd.to_numeric(d["buy_hhmm"], errors="coerce").fillna(925).astype(int)
    d["exit_hhmm"] = pd.to_numeric(d["exit_hhmm"], errors="coerce").fillna(1500).astype(int)
    d["net_ret"] = pd.to_numeric(d["net_ret"], errors="coerce").astype(float)
    d.sort_values(["buy_date", "buy_hhmm", "code"], inplace=True)
    d.reset_index(drop=True, inplace=True)
    return d


def audit_physical_integrity(name: str, df: pd.DataFrame, bar_map: dict) -> dict:
    """Test 1: Full-ledger anti-cheat + Top 5 Q8 raw bar verification."""
    d = norm_ledger(df)
    has_px = ("buy_price" in d.columns) and ("exit_price" in d.columns)

    t0_viol = int((d["exit_date"] <= d["buy_date"]).sum())

    # Single-slot overlap check
    overlap_strict = []
    same_day_reentry = []
    for i in range(1, len(d)):
        p, c = d.iloc[i - 1], d.iloc[i]
        if c["buy_date"] < p["exit_date"]:
            overlap_strict.append((i, p["buy_date"], p["exit_date"], p["code"], c["buy_date"], c["code"]))
        elif c["buy_date"] == p["exit_date"]:
            same_day_reentry.append((i, p["code"], int(p["exit_hhmm"]), c["code"], int(c["buy_hhmm"])))
            if int(c["buy_hhmm"]) <= int(p["exit_hhmm"]):
                overlap_strict.append((i, p["buy_date"], p["exit_date"], p["code"], c["buy_date"], c["code"]))

    missing_buy, missing_exit = 0, 0
    buy_oob, exit_oob = [], []
    yizi_zt_buy, open_zt_buy, px_at_zt_buy = [], [], []
    yizi_dt_exit, open_dt_925_exit, close_dt_1500_exit = [], [], []
    ex_div_trades, ret_mismatch = [], []
    board_20cm = []

    top5_idx = set(d.sort_values("net_ret", ascending=False).head(5).index.tolist())
    top5_records = []

    for idx, r in d.iterrows():
        c6 = r["code"]
        if c6.startswith(("300", "301", "688")):
            board_20cm.append((r["buy_date"], c6, r["name"]))
        bb = bar_map.get((c6, r["buy_date"]))
        eb = bar_map.get((c6, r["exit_date"]))
        if bb is None:
            missing_buy += 1
        if eb is None:
            missing_exit += 1
        if bb is None or eb is None:
            if idx in top5_idx:
                top5_records.append({"buy_date": r["buy_date"], "code": c6, "name": r["name"], "status": "MISSING_BAR"})
            continue

        _, b_zt, b_dt = limit_prices(c6, bb["prev_close"], bb)
        _, e_zt, e_dt = limit_prices(c6, eb["prev_close"], eb)

        # True one-word limit-up buy check
        is_yizi_zt_b = (not np.isnan(b_zt)) and (bb["low"] >= b_zt - 0.015) and (bb["open"] >= b_zt - 0.015)
        is_open_zt_b = (not np.isnan(b_zt)) and (bb["open"] >= b_zt - 0.015)
        if is_yizi_zt_b:
            yizi_zt_buy.append((r["buy_date"], c6, r["name"], bb["open"], bb["low"], b_zt))
        if is_open_zt_b:
            open_zt_buy.append((r["buy_date"], c6, r["name"], int(r["buy_hhmm"]), bb["open"], bb["low"], b_zt))

        # True locked limit-down exit check
        is_yizi_dt_e = (not np.isnan(e_dt)) and (eb["high"] <= e_dt + 0.015) and (eb["close"] <= e_dt + 0.015)
        is_open_dt_925_e = (not np.isnan(e_dt)) and (eb["open"] <= e_dt + 0.015) and (int(r["exit_hhmm"]) == 925)
        is_close_dt_1500_e = (not np.isnan(e_dt)) and (eb["close"] <= e_dt + 0.015) and (int(r["exit_hhmm"]) >= 1455)
        if is_yizi_dt_e:
            yizi_dt_exit.append((r["exit_date"], c6, r["name"], eb["open"], eb["high"], eb["close"], e_dt))
        if is_open_dt_925_e and not is_yizi_dt_e:
            open_dt_925_exit.append((r["exit_date"], c6, r["name"], eb["open"], eb["high"], e_dt))
        if is_close_dt_1500_e and not is_yizi_dt_e:
            close_dt_1500_exit.append((r["exit_date"], c6, r["name"], eb["close"], eb["high"], e_dt))

        # Ex-div / split check across holding window
        qfq_ratio = bb["qfq_factor"] / eb["qfq_factor"] if eb["qfq_factor"] > 0 else 1.0
        div_changed = abs(qfq_ratio - 1.0) > 1e-4

        bpx_oob_flag, epx_oob_flag, px_zt_flag, ret_err_val = False, False, False, np.nan
        if has_px:
            bp = float(r["buy_price"])
            ep = float(r["exit_price"])
            if bp < bb["low"] - 0.015 or bp > bb["high"] + 0.015:
                bpx_oob_flag = True
                buy_oob.append((r["buy_date"], c6, r["name"], bp, bb["low"], bb["high"]))
            if ep < eb["low"] - 0.015 or ep > eb["high"] + 0.015:
                epx_oob_flag = True
                exit_oob.append((r["exit_date"], c6, r["name"], ep, eb["low"], eb["high"]))
            if (not np.isnan(b_zt)) and (bp >= b_zt - 0.015):
                px_zt_flag = True
                px_at_zt_buy.append((r["buy_date"], c6, r["name"], int(r["buy_hhmm"]), bp, bb["open"], bb["low"], b_zt))

            exp_ret_adj = (ep / bp) * qfq_ratio * 0.9980 - 1.0
            exp_ret_raw = (ep / bp) * 0.9980 - 1.0
            ret_err_val = abs(exp_ret_adj - float(r["net_ret"]))
            if div_changed:
                ex_div_trades.append({
                    "buy_date": r["buy_date"], "exit_date": r["exit_date"], "code": c6, "name": r["name"],
                    "bp": bp, "ep": ep, "qfq_b": bb["qfq_factor"], "qfq_e": eb["qfq_factor"],
                    "exp_adj": round(exp_ret_adj, 5), "exp_raw": round(exp_ret_raw, 5), "ledger_ret": round(float(r["net_ret"]), 5),
                })
            if ret_err_val > 0.005:
                ret_mismatch.append({
                    "buy_date": r["buy_date"], "exit_date": r["exit_date"], "code": c6, "name": r["name"],
                    "bp": bp, "ep": ep, "exp_adj": round(exp_ret_adj, 5), "ledger_ret": round(float(r["net_ret"]), 5),
                    "diff": round(ret_err_val, 5),
                })
        else:
            if div_changed:
                ex_div_trades.append({
                    "buy_date": r["buy_date"], "exit_date": r["exit_date"], "code": c6, "name": r["name"],
                    "qfq_b": bb["qfq_factor"], "qfq_e": eb["qfq_factor"], "ledger_ret": round(float(r["net_ret"]), 5),
                })

        if idx in top5_idx:
            top5_records.append({
                "buy_date": r["buy_date"], "buy_hhmm": int(r["buy_hhmm"]),
                "exit_date": r["exit_date"], "exit_hhmm": int(r["exit_hhmm"]),
                "code": c6, "name": r["name"],
                "net_ret_pct": round(float(r["net_ret"]) * 100.0, 2),
                "buy_price": float(r["buy_price"]) if has_px else None,
                "exit_price": float(r["exit_price"]) if has_px else None,
                "raw_b_ohlc": [bb["open"], bb["high"], bb["low"], bb["close"]],
                "raw_b_prev_c": bb["prev_close"], "b_zt_px": b_zt,
                "raw_e_ohlc": [eb["open"], eb["high"], eb["low"], eb["close"]],
                "raw_e_prev_c": eb["prev_close"], "e_dt_px": e_dt,
                "qfq_b": bb["qfq_factor"], "qfq_e": eb["qfq_factor"], "div_changed": div_changed,
                "buy_in_bar": not bpx_oob_flag, "exit_in_bar": not epx_oob_flag,
                "yizi_zt_buy": is_yizi_zt_b, "open_zt_buy": is_open_zt_b,
                "yizi_dt_exit": is_yizi_dt_e,
                "ret_err": round(ret_err_val, 5) if not np.isnan(ret_err_val) else None,
            })

    top5_records.sort(key=lambda x: x.get("net_ret_pct", -999), reverse=True)
    return {
        "n": int(len(d)),
        "has_px": has_px,
        "t0_violations": t0_viol,
        "overlap_strict_count": len(overlap_strict),
        "overlap_strict_examples": overlap_strict[:5],
        "same_day_reentry_count": len(same_day_reentry),
        "same_day_reentry_examples": same_day_reentry[:5],
        "missing_buy_bar": missing_buy,
        "missing_exit_bar": missing_exit,
        "buy_oob_count": len(buy_oob),
        "buy_oob_examples": buy_oob[:5],
        "exit_oob_count": len(exit_oob),
        "exit_oob_examples": exit_oob[:5],
        "yizi_zt_buy_count": len(yizi_zt_buy),
        "yizi_zt_buy_examples": yizi_zt_buy[:5],
        "open_zt_buy_count": len(open_zt_buy),
        "open_zt_buy_examples": open_zt_buy[:5],
        "px_at_zt_buy_count": len(px_at_zt_buy),
        "yizi_dt_exit_count": len(yizi_dt_exit),
        "yizi_dt_exit_examples": yizi_dt_exit[:5],
        "open_dt_925_exit_count": len(open_dt_925_exit),
        "open_dt_925_exit_examples": open_dt_925_exit[:5],
        "close_dt_1500_exit_count": len(close_dt_1500_exit),
        "close_dt_1500_exit_examples": close_dt_1500_exit[:5],
        "ex_div_trades_count": len(ex_div_trades),
        "ex_div_trades": ex_div_trades,
        "ret_mismatch_gt50bps_count": len(ret_mismatch),
        "ret_mismatch_examples": ret_mismatch[:5],
        "board_20cm_count": len(board_20cm),
        "top5_audit": top5_records,
    }


def wilson_ci_95(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    z = 1.959963984540054
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = (z * math.sqrt((p * (1.0 - p) + z * z / (4.0 * n)) / n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def calc_cap_nav(rets: np.ndarray, init_w: float = 100.0, cap_w: float = 1000.0) -> float:
    cap = init_w
    for r in rets:
        bet = min(cap, cap_w)
        cap += bet * float(r)
    return cap / init_w


def get_csi_ret(sh300: dict, s_dt: str, e_dt: str) -> float:
    all_dts = sorted(sh300.keys())
    prevs = [d for d in all_dts if d < s_dt]
    p0 = sh300[prevs[-1]] if prevs else sh300[all_dts[0]]
    p1s = [d for d in all_dts if d <= e_dt]
    p1 = sh300[p1s[-1]]
    return (p1 / p0 - 1.0) * 100.0


def calc_core_metrics(rets: np.ndarray, csi_pct: float = -18.49) -> dict:
    n = len(rets)
    if n == 0:
        return {
            "n": 0, "wr": 0.0, "plr": 0.0, "mean": 0.0, "median": 0.0,
            "nav": 1.0, "ret_pct": 0.0, "mdd": 0.0, "cap10m": 1.0, "cap1m": 1.0,
            "csi300_pct": round(csi_pct, 2), "excess_pp": round(-csi_pct, 2),
        }
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float(len(wins) / n * 100.0)
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else (99.0 if len(wins) > 0 else 0.0)
    cum = np.cumprod(1.0 + rets)
    peaks = np.maximum.accumulate(np.insert(cum, 0, 1.0))[1:]
    mdd = float(np.max((peaks - cum) / peaks) * 100.0)
    nav = float(cum[-1])
    ret_pct = (nav - 1.0) * 100.0
    cap10m = calc_cap_nav(rets, 100.0, 1000.0)
    cap1m = calc_cap_nav(rets, 100.0, 100.0)
    return {
        "n": int(n),
        "wr": round(wr, 2),
        "plr": round(plr, 2),
        "mean": round(float(rets.mean() * 100.0), 2),
        "median": round(float(np.median(rets) * 100.0), 2),
        "nav": round(nav, 4),
        "ret_pct": round(ret_pct, 2),
        "mdd": round(mdd, 2),
        "cap10m": round(cap10m, 2),
        "cap1m": round(cap1m, 2),
        "csi300_pct": round(csi_pct, 2),
        "excess_pp": round(ret_pct - csi_pct, 2),
        "excess_cap1m_pp": round((cap1m - 1.0) * 100.0 - csi_pct, 2),
    }


def slippage_stress(df: pd.DataFrame, sh300: dict) -> dict:
    """Test 2: +0bps, +20bps, +50bps, +80bps, +160bps round-trip friction shock."""
    d = norm_ledger(df)
    rets = d["net_ret"].to_numpy()
    csi_5y = get_csi_ret(sh300, "2021-11-15", "2026-11-16")
    levels_bps = [0, 20, 50, 80, 160]
    res = {}
    for bps in levels_bps:
        s = bps / 10000.0
        r_s = (1.0 + rets) / (1.0 + s) - 1.0
        m = calc_core_metrics(r_s, csi_5y)
        m["extra_rt_bps"] = bps
        res[f"+{bps}bps"] = m

    # Solve exact break-even extra round-trip bps where NAV == 1.0 and NAV == CSI300 (0.8151)
    # sum(log(1+r)) - n*log(1+s) = log(target) => s = exp((sum(log(1+r)) - log(target))/n) - 1
    n = len(rets)
    log_sum = float(np.sum(np.log(np.maximum(1e-9, 1.0 + rets))))
    be_1x_bps = (math.exp(log_sum / n) - 1.0) * 10000.0 if n > 0 else 0.0
    be_csi_bps = (math.exp((log_sum - math.log(1.0 + csi_5y / 100.0)) / n) - 1.0) * 10000.0 if n > 0 else 0.0
    nav0 = res["+0bps"]["nav"]
    nav80 = res["+80bps"]["nav"]
    retention_80 = nav80 / nav0 * 100.0 if nav0 > 0 else 0.0
    cap1m_ret_drop_80 = (res["+0bps"]["cap1m"] - res["+80bps"]["cap1m"]) / max(res["+0bps"]["cap1m"] - 1.0, 1e-9) * 100.0

    return {
        "levels": res,
        "breakeven_nav1x_bps": round(be_1x_bps, 1),
        "breakeven_csi300_bps": round(be_csi_bps, 1),
        "nav_retention_at_80bps_pct": round(retention_80, 2),
        "cap1m_profit_erosion_at_80bps_pct": round(cap1m_ret_drop_80, 2),
    }


def fragility_audit(df: pd.DataFrame, all_dts: list[str]) -> dict:
    """Test 3: Outlier removal, consecutive losses, underwater duration, Wilson 95% CI."""
    d = norm_ledger(df)
    rets = d["net_ret"].to_numpy()
    n = len(rets)
    sr = np.sort(rets)
    nav_all = float(np.prod(1.0 + rets))
    nav_ex1 = float(np.prod(1.0 + sr[:-1])) if n > 1 else 1.0
    nav_ex3 = float(np.prod(1.0 + sr[:-3])) if n > 3 else 1.0
    nav_ex5 = float(np.prod(1.0 + sr[:-5])) if n > 5 else 1.0

    log_rets = np.log(np.maximum(1e-9, 1.0 + rets))
    tot_log = float(np.sum(log_rets))
    sr_log = np.sort(log_rets)
    top1_log_share = float(sr_log[-1] / tot_log * 100.0) if tot_log > 0 else 0.0
    top3_log_share = float(np.sum(sr_log[-3:]) / tot_log * 100.0) if (tot_log > 0 and n >= 3) else 0.0
    top5_log_share = float(np.sum(sr_log[-5:]) / tot_log * 100.0) if (tot_log > 0 and n >= 5) else 0.0

    # Max consecutive losses
    max_streak, cur_streak = 0, 0
    max_streak_ret, cur_streak_prod = 0.0, 1.0
    cur_start, best_span = None, ("", "")
    for i, r in enumerate(rets):
        if r <= 0:
            if cur_streak == 0:
                cur_start = d.iloc[i]["buy_date"]
            cur_streak += 1
            cur_streak_prod *= (1.0 + r)
            if cur_streak > max_streak:
                max_streak = cur_streak
                max_streak_ret = (cur_streak_prod - 1.0) * 100.0
                best_span = (cur_start, d.iloc[i]["exit_date"])
        else:
            cur_streak = 0
            cur_streak_prod = 1.0

    # Underwater recovery days (from peak exit_date to recovery exit_date, or to 2026-11-16 if still underwater)
    cum = np.cumprod(1.0 + rets)
    peak_val = 1.0
    peak_date = d.iloc[0]["buy_date"] if n > 0 else "2021-11-15"
    peak_idx = -1
    max_uw_cal_days = 0
    max_uw_trd_days = 0
    max_uw_trades = 0
    max_uw_span = ("", "", False)
    mdd_pct = 0.0
    mdd_span = ("", "")

    dt_to_trd_pos = {dt: i for i, dt in enumerate(all_dts)}

    def trd_days_between(d1: str, d2: str) -> int:
        p1 = dt_to_trd_pos.get(d1)
        p2 = dt_to_trd_pos.get(d2)
        if p1 is None:
            p1 = next((i for i, dt in enumerate(all_dts) if dt >= d1), 0)
        if p2 is None:
            p2 = next((i for i in range(len(all_dts) - 1, -1, -1) if all_dts[i] <= d2), len(all_dts) - 1)
        return max(0, p2 - p1)

    for i, val in enumerate(cum):
        ed = d.iloc[i]["exit_date"]
        dd = (peak_val - val) / peak_val * 100.0
        if dd > mdd_pct:
            mdd_pct = dd
            mdd_span = (peak_date, ed)
        if val >= peak_val - 1e-12:
            if peak_idx >= 0 and (i - peak_idx) > 1:
                cal_d = (pd.Timestamp(ed) - pd.Timestamp(peak_date)).days
                trd_d = trd_days_between(peak_date, ed)
                if cal_d > max_uw_cal_days:
                    max_uw_cal_days = cal_d
                    max_uw_trd_days = trd_d
                    max_uw_trades = i - peak_idx - 1
                    max_uw_span = (peak_date, ed, True)
            peak_val = val
            peak_date = ed
            peak_idx = i

    # Check trailing unrecovered underwater period up to 2026-11-16
    end_ref = "2026-11-16"
    still_underwater = False
    if n > 0 and cum[-1] < peak_val - 1e-12:
        still_underwater = True
        cal_d = (pd.Timestamp(end_ref) - pd.Timestamp(peak_date)).days
        trd_d = trd_days_between(peak_date, end_ref)
        if cal_d > max_uw_cal_days:
            max_uw_cal_days = cal_d
            max_uw_trd_days = trd_d
            max_uw_trades = n - 1 - peak_idx
            max_uw_span = (peak_date, end_ref, False)

    wins_cnt = int((rets > 0).sum())
    ci_low, ci_high = wilson_ci_95(wins_cnt, n)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    plr = float(wins.mean() / abs(losses.mean())) if (len(wins) > 0 and len(losses) > 0 and losses.mean() < 0) else 99.0
    breakeven_wr = 1.0 / (1.0 + plr) * 100.0 if plr > 0 else 100.0
    hlz_t = float(rets.mean() / (rets.std(ddof=1) / math.sqrt(n))) if (n > 1 and rets.std(ddof=1) > 0) else 0.0

    return {
        "n": int(n),
        "wins": wins_cnt,
        "wr_pct": round(wins_cnt / n * 100.0, 2) if n else 0.0,
        "wr_wilson95_low_pct": round(ci_low * 100.0, 2),
        "wr_wilson95_high_pct": round(ci_high * 100.0, 2),
        "plr": round(plr, 2),
        "breakeven_wr_pct": round(breakeven_wr, 2),
        "ci_low_above_breakeven": bool(ci_low * 100.0 > breakeven_wr),
        "hlz_t": round(hlz_t, 2),
        "full_nav": round(nav_all, 4),
        "ex_top1_nav": round(nav_ex1, 4),
        "ex_top3_nav": round(nav_ex3, 4),
        "ex_top5_nav": round(nav_ex5, 4),
        "top1_log_share_pct": round(top1_log_share, 2),
        "top3_log_share_pct": round(top3_log_share, 2),
        "top5_log_share_pct": round(top5_log_share, 2),
        "max_consec_losses": int(max_streak),
        "max_consec_loss_ret_pct": round(max_streak_ret, 2),
        "max_consec_loss_span": best_span,
        "mdd_pct": round(mdd_pct, 2),
        "mdd_span": mdd_span,
        "max_underwater_cal_days": int(max_uw_cal_days),
        "max_underwater_trd_days": int(max_uw_trd_days),
        "max_underwater_trades": int(max_uw_trades),
        "max_underwater_span": max_uw_span,
        "currently_underwater": still_underwater,
    }


def regime_decay_audit(df: pd.DataFrame, sh300: dict) -> dict:
    """Test 4: 2021-2023 vs 2024 vs 2025 vs 2026H1 vs 2026H2 (Jul-Nov)."""
    d = norm_ledger(df)
    slices = [
        ("2021-2023", "2021-11-15", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025", "2025-01-01", "2025-12-31"),
        ("2026H1", "2026-01-01", "2026-06-30"),
        ("2026H2", "2026-07-01", "2026-11-16"),
    ]
    out = {}
    for lbl, sdt, edt in slices:
        sub = d[(d["buy_date"] >= sdt) & (d["buy_date"] <= edt)]
        csi_p = get_csi_ret(sh300, sdt, edt)
        m = calc_core_metrics(sub["net_ret"].to_numpy(), csi_p)
        months = (pd.Timestamp(edt) - pd.Timestamp(sdt)).days / 30.4375
        m["trades_per_month"] = round(len(sub) / months, 2) if months > 0 else 0.0
        out[lbl] = m
    return out


def run_1slot_sim(pool_df: pd.DataFrame) -> pd.DataFrame:
    """Exact replica of synthesize_master_clean_20261116.run_1slot priority rules."""
    df_s = pool_df.sort_values(
        ["buy_date", "priority", "score", "buy_hhmm"],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)
    picked = []
    cur_exit_dt = ""
    cur_exit_hhmm = 0
    for row in df_s.itertuples(index=False):
        if not cur_exit_dt or row.buy_date > cur_exit_dt or (row.buy_date == cur_exit_dt and row.buy_hhmm > cur_exit_hhmm):
            picked.append(row._asdict())
            cur_exit_dt = row.exit_date
            cur_exit_hhmm = row.exit_hhmm
    return pd.DataFrame(picked)


def high_v51_investigation(bar_map: dict, sh300: dict) -> dict:
    """Test 5: Uncover the exact 10-trade 93% bug in partA vs v5_morn_42 / v51_ledger_42 & test combined impact."""
    pa = norm_ledger(pd.read_csv(PATHS["high_v51_partA"]))
    m42 = norm_ledger(pd.read_csv(PATHS["high_v51_morn42"]))
    t42 = norm_ledger(pd.read_csv(PATHS["high_v51_trainer42"]))
    s43 = norm_ledger(pd.read_csv(PATHS["high_v51_sub2base43"]))

    # Compare partA vs morn42
    mg_pa_m42 = pa.merge(m42, on=["buy_date", "code"], how="outer", suffixes=("_partA", "_morn42"))
    diff_pa_m42 = mg_pa_m42[(mg_pa_m42["net_ret_partA"] - mg_pa_m42["net_ret_morn42"]).abs() > 1e-4]

    # Compare morn42 vs trainer42
    mg_m42_t42 = m42.merge(t42, on=["buy_date"], how="outer", suffixes=("_morn42", "_t42"))
    diff_m42_t42 = mg_m42_t42[
        (mg_m42_t42["code_morn42"] != mg_m42_t42["code_t42"])
        | ((mg_m42_t42["net_ret_morn42"] - mg_m42_t42["net_ret_t42"]).abs() > 1e-5)
    ]

    # Check whether the 10 diff trades in partA sealed limit-up on buy_date!
    ten_details = []
    for _, r in diff_pa_m42.iterrows():
        c6 = r["code"]
        bb = bar_map.get((c6, r["buy_date"]))
        sealed_buy_day = False
        if bb is not None and not np.isnan(bb["prev_close"]):
            _, zt_b, _ = limit_prices(c6, bb["prev_close"], bb)
            sealed_buy_day = bb["close"] >= zt_b - 0.015
        ten_details.append({
            "buy_date": r["buy_date"], "code": c6, "name": r["name_partA"],
            "buy_day_sealed_zt": sealed_buy_day,
            "partA_exit": f"{r['exit_date_partA']} {int(r['exit_hhmm_partA'])}@{r['exit_price']}",
            "partA_ret_pct": round(float(r["net_ret_partA"]) * 100.0, 2),
            "orig_exit": f"{r['exit_date_morn42']} eo={bool(r['eo'])}",
            "orig_ret_pct": round(float(r["net_ret_morn42"]) * 100.0, 2),
            "delta_pp": round((float(r["net_ret_partA"]) - float(r["net_ret_morn42"])) * 100.0, 2),
        })

    # Re-run 5-strategy V19.1 combination swapping High V5.1 (partA vs morn42 vs trainer42)
    # Use the exact 4 other streams inside combined_v191 OR rebuild from full pools
    comb_orig = norm_ledger(pd.read_csv(PATHS["combined_v191"]))
    d34 = norm_ledger(pd.read_csv(PATHS["3to4_v41"])).assign(strategy="三进四V4.1", priority=1)
    d12 = norm_ledger(pd.read_csv(PATHS["1to2_v19"])).assign(strategy="一进二V19", priority=5)
    d23_opt = norm_ledger(pd.read_csv(PATHS["2to3_opt_v21_t2"])).assign(strategy="二进三V2.1", priority=4)
    d_pry_top1 = norm_ledger(pd.read_csv(f"{OUT_DIR}/reconstructed_pry_v21_top1.csv")).assign(strategy="超跌撬板V2.1", priority=3)

    # Check if d34 + partA + d_pry_top1 + d23_opt + d12 reproduces comb_orig!
    pa_p = pa.assign(strategy="高标首阴V5.1", priority=2)
    m42_p = m42.assign(strategy="高标首阴V5.1", priority=2)
    m42_p["buy_hhmm"] = np.where(m42_p["b_open_h"], 925, 935)
    m42_p["exit_hhmm"] = np.where(m42_p["eo"], 925, 1500)
    if "sc" in m42_p.columns:
        m42_p["score"] = m42_p["sc"]
    t42_p = t42.assign(strategy="高标首阴V5.1", priority=2)
    t42_p["buy_hhmm"] = np.where(t42_p["b_open_h"], 925, 935)
    t42_p["exit_hhmm"] = np.where(t42_p["eo"], 925, 1500)
    if "sc" in t42_p.columns:
        t42_p["score"] = t42_p["sc"]

    cols_keep = ["buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name", "strategy", "priority", "score", "net_ret"]
    comb_tests = {}
    for lbl, h_df in [("with_partA_bug_13.41x", pa_p), ("with_morn42_15.13x", m42_p), ("with_trainer42_16.39x", t42_p)]:
        pool = pd.concat([d34[cols_keep], h_df[cols_keep], d_pry_top1[cols_keep], d23_opt[cols_keep], d12[cols_keep]], ignore_index=True)
        slot = run_1slot_sim(pool)
        m5 = calc_core_metrics(slot["net_ret"].to_numpy(), get_csi_ret(sh300, "2021-11-15", "2026-11-16"))
        m3 = calc_core_metrics(slot[slot["buy_date"] >= "2023-11-16"]["net_ret"].to_numpy(), get_csi_ret(sh300, "2023-11-16", "2026-11-16"))
        m26 = calc_core_metrics(slot[slot["buy_date"] >= "2026-01-01"]["net_ret"].to_numpy(), get_csi_ret(sh300, "2026-01-01", "2026-11-16"))
        m26h2 = calc_core_metrics(slot[slot["buy_date"] >= "2026-07-01"]["net_ret"].to_numpy(), get_csi_ret(sh300, "2026-07-01", "2026-11-16"))
        comb_tests[lbl] = {
            "5y": m5, "3y": m3, "2026": m26, "2026H2": m26h2,
            "by_strat": slot["strategy"].value_counts().to_dict(),
        }

    return {
        "solo_versions": {
            "partA_ledger_base_high_v51": calc_core_metrics(pa["net_ret"].to_numpy(), get_csi_ret(sh300, "2021-11-15", "2026-11-16")),
            "orig_v5_morn_42_ledger": calc_core_metrics(m42["net_ret"].to_numpy(), get_csi_ret(sh300, "2021-11-15", "2026-11-16")),
            "trainer_v51_ledger_42": calc_core_metrics(t42["net_ret"].to_numpy(), get_csi_ret(sh300, "2021-11-15", "2026-11-16")),
            "sub2_baseline_v5_1_43": calc_core_metrics(s43["net_ret"].to_numpy(), get_csi_ret(sh300, "2021-11-15", "2026-11-16")),
        },
        "ten_bug_trades": ten_details,
        "morn42_vs_trainer42_diff_count": len(diff_m42_t42),
        "morn42_vs_trainer42_diffs": diff_m42_t42[["buy_date", "code_morn42", "name_morn42", "net_ret_morn42", "code_t42", "name_t42", "net_ret_t42"]].to_dict("records"),
        "combined_v191_official_row_count": len(comb_orig),
        "combined_v191_official_nav": round(float(np.prod(1.0 + comb_orig["net_ret"].to_numpy())), 4),
        "combined_rebuilt_sensitivity": comb_tests,
    }


def main():
    print("[1/5] Reconstructing Pry V2.1 & loading all ledgers...")
    pry_ss16, pry_top1 = reconstruct_pry_v21()
    ledgers = {
        "3to4_v41": pd.read_csv(PATHS["3to4_v41"]),
        "high_v51_partA": pd.read_csv(PATHS["high_v51_partA"]),
        "high_v51_trainer42": pd.read_csv(PATHS["high_v51_trainer42"]),
        "pry_v21_ss16": pry_ss16,
        "2to3_xf30_t2": pd.read_csv(PATHS["2to3_xf30_t2"]),
        "2to3_opt_v21_t2": pd.read_csv(PATHS["2to3_opt_v21_t2"]),
        "1to2_v19": pd.read_csv(PATHS["1to2_v19"]),
        "combined_v191": pd.read_csv(PATHS["combined_v191"]),
    }

    codes_needed = set()
    for df in ledgers.values():
        codes_needed.update(df["code"].astype(str).str.strip().str.zfill(6).unique())
    codes_needed.update(pd.read_csv(PATHS["high_v51_morn42"])["code"].astype(str).str.strip().str.zfill(6).unique())
    codes_needed.update(pry_top1["code"].astype(str).str.strip().str.zfill(6).unique())

    print(f"[2/5] Loading raw daily bars for {len(codes_needed)} unique tickers...")
    bar_map, all_df = load_daily_truth(codes_needed)

    with open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json", "r", encoding="utf-8") as f:
        idx_cache = json.load(f)
    sh300 = idx_cache["sh000300"]
    all_dts = sorted(sh300.keys())

    print("[3/5] Running Test 1 (Q8 Top-5 & Full Physical Integrity)...")
    test1 = {k: audit_physical_integrity(k, df, bar_map) for k, df in ledgers.items()}

    print("[4/5] Running Test 2 (Slippage), Test 3 (Fragility), Test 4 (Regime Decay)...")
    test2 = {k: slippage_stress(df, sh300) for k, df in ledgers.items()}
    test3 = {k: fragility_audit(df, all_dts) for k, df in ledgers.items()}
    test4 = {k: regime_decay_audit(df, sh300) for k, df in ledgers.items()}

    print("[5/5] Running Test 5 (High V5.1 Mystery & Combined Impact)...")
    test5 = high_v51_investigation(bar_map, sh300)

    out = {
        "csi300_refs": {
            "5Y_211115_261116": round(get_csi_ret(sh300, "2021-11-15", "2026-11-16"), 2),
            "2021_2023": round(get_csi_ret(sh300, "2021-11-15", "2023-12-31"), 2),
            "2024": round(get_csi_ret(sh300, "2024-01-01", "2024-12-31"), 2),
            "2025": round(get_csi_ret(sh300, "2025-01-01", "2025-12-31"), 2),
            "2026H1": round(get_csi_ret(sh300, "2026-01-01", "2026-06-30"), 2),
            "2026H2_to_1116": round(get_csi_ret(sh300, "2026-07-01", "2026-11-16"), 2),
            "2026H2_to_1120": round(get_csi_ret(sh300, "2026-07-01", "2026-11-20"), 2),
            "2026_YTD_1116": round(get_csi_ret(sh300, "2026-01-01", "2026-11-16"), 2),
        },
        "test1_physical_and_top5": test1,
        "test2_slippage_stress": test2,
        "test3_fragility": test3,
        "test4_regime_decay": test4,
        "test5_high_v51_mystery": test5,
    }
    out_json = f"{OUT_DIR}/redteam_stress_audit_results.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Audit JSON saved to {out_json}")


if __name__ == "__main__":
    main()

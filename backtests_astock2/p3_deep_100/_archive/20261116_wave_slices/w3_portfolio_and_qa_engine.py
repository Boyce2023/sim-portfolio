#!/usr/bin/env python3
"""Independent Raw-Bar QA & 5-Strategy Portfolio Synergy Engine (Wave 3)."""
import json, os, pickle
import numpy as np
import pandas as pd
from common_eval_harness import CSI_BENCH, load_production_3_ledgers

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/p3_deep_100"
PKL_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl"


def normalize_ledger(df: pd.DataFrame, strat_name: str, priority: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    ccol = "code" if "code" in df.columns else "c6"
    bcol = "buy_date" if "buy_date" in df.columns else "entry_date"
    ecol = [c for c in ["exit_dt", "exit_date", "sell_date"] if c in df.columns][0]
    rcol = [c for c in ["net_ret", "ret", "net_ret_pct", "trade_ret"] if c in df.columns][0]
    scol = next((c for c in ["v20_score", "score", "v34_score", "sc", "total_score"] if c in df.columns), None)
    out["code"] = df[ccol].astype(str).str.zfill(6)
    out["name"] = df["name"].astype(str) if "name" in df.columns else ""
    out["buy_date"] = df[bcol].astype(str).str[:10]
    out["exit_dt"] = df[ecol].astype(str).str[:10]
    vals = pd.to_numeric(df[rcol], errors="coerce").fillna(0.0)
    if vals.abs().quantile(0.9) > 0.85:
        vals = vals / 100.0
    out["net_ret"] = vals
    out["strategy"] = strat_name
    out["priority"] = priority
    out["score"] = pd.to_numeric(df[scol], errors="coerce").fillna(100.0) if scol else 100.0
    for ov_col in ["is_held_3to4", "is_held_1to2", "in_v18_holding", "is_overlap_v18", "is_overlap_3to4"]:
        if ov_col in df.columns:
            out[ov_col] = df[ov_col].astype(bool)
    return out[(out["buy_date"] >= "2022-01-01") & (out["buy_date"] <= "2026-11-14")].copy()


def simulate_multi_slot_portfolio(trades: pd.DataFrame, n_slots: int = 2, csi: dict = None) -> dict:
    if trades.empty:
        return {"n_executed": 0, "portfolio_nav": 1.0, "mdd_pct": 0.0}
    tr = trades.sort_values(["buy_date", "priority", "score"], ascending=[True, True, False]).reset_index(drop=True)
    slot_free = ["1900-01-01"] * n_slots
    slot_nav = [1.0 / n_slots] * n_slots
    taken = []
    skipped_collision = 0
    held_codes = {}
    for r in tr.to_dict("records"):
        bd, ed, cd = r["buy_date"], r["exit_dt"], r["code"]
        held_codes = {k: v for k, v in held_codes.items() if v >= bd}
        if cd in held_codes:
            skipped_collision += 1
            continue
        avail = [i for i in range(n_slots) if slot_free[i] < bd]
        if not avail:
            skipped_collision += 1
            continue
        si = avail[0]
        slot_nav[si] *= (1.0 + float(r["net_ret"]))
        slot_free[si] = max(bd, ed)
        held_codes[cd] = max(bd, ed)
        taken.append({**r, "slot": si, "total_nav_after": sum(slot_nav)})
    if not taken:
        return {"n_executed": 0, "portfolio_nav": 1.0, "mdd_pct": 0.0}
    tdf = pd.DataFrame(taken)
    rets = tdf["net_ret"].to_numpy()
    eq = tdf["total_nav_after"].to_numpy()
    peaks = np.maximum.accumulate(np.insert(eq, 0, 1.0))[1:]
    mdd = float(np.max((peaks - eq) / peaks) * 100.0)
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = float((rets > 0).mean() * 100.0)
    po = float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) and losses.mean() < 0 else 9.99
    # Ex-top3 trades across auxiliary strategies or overall
    s_rets = np.sort(rets)
    ex3_single_equiv = float(np.prod(1.0 + (s_rets[:-3] if len(s_rets) > 3 else s_rets) / n_slots))
    nav_val = float(sum(slot_nav))
    c5 = (csi or {}).get("ret_5y_pct", -17.84)
    return {
        "n_slots": n_slots,
        "n_candidates": int(len(tr)),
        "n_executed": int(len(tdf)),
        "skipped_collision": int(skipped_collision),
        "collision_rate_pct": round(skipped_collision / max(1, len(tr)) * 100.0, 2),
        "wr_pct": round(wr, 2),
        "payoff": round(po, 2),
        "mean_trade_pct": round(float(rets.mean() * 100.0), 2),
        "portfolio_nav": round(nav_val, 4),
        "net_excess_5y_pct": round((nav_val - 1.0) * 100.0 - c5, 2),
        "ex_top3_approx_nav": round(ex3_single_equiv, 4),
        "mdd_pct": round(mdd, 2),
        "by_strategy_counts": tdf["strategy"].value_counts().to_dict(),
    }


def qa_verify_raw_bars(ledger: pd.DataFrame, tag: str, code_bars: dict) -> dict:
    errs = []
    checked = 0
    for r in ledger.to_dict("records"):
        cd, bd, ed = str(r["code"]).zfill(6), str(r["buy_date"])[:10], str(r["exit_dt"])[:10]
        if ed < bd:
            errs.append(f"{tag}:{cd}@{bd} exit {ed} < buy {bd}")
        cb = code_bars.get(cd)
        if cb is not None:
            pos = cb["date_to_pos"].get(bd, -1)
            if pos >= 0:
                checked += 1
                op, hi, lo, zt = float(cb["open"][pos]), float(cb["high"][pos]), float(cb["low"][pos]), float(cb["zt_px"][pos])
                if abs(op - zt) < 1e-3 and abs(lo - zt) < 1e-3 and abs(hi - zt) < 1e-3:
                    errs.append(f"{tag}:{cd}@{bd} UNBUYABLE YIZI IN LEDGER!")
    return {"tag": tag, "rows": int(len(ledger)), "raw_bar_checked": checked, "error_count": len(errs), "errors": errs[:10]}


def main():
    csi = {"ret_5y_pct": round(CSI_BENCH["5y"] * 100.0, 2), "ret_3y_pct": round(CSI_BENCH["3y"] * 100.0, 2), "ret_rec_pct": round(CSI_BENCH["rec"] * 100.0, 2)}
    main_l = load_production_3_ledgers()
    with open(PKL_PATH, "rb") as f:
        raw = pickle.load(f)
    code_bars = raw["code_bars"] if isinstance(raw, dict) and "code_bars" in raw else raw

    l_1to2 = normalize_ledger(main_l["1to2"], "1to2_V18", priority=3)
    l_3to4 = normalize_ledger(main_l["3to4"], "3to4_V34", priority=2)
    l_high = normalize_ledger(main_l["high"], "High_V51", priority=1)

    p45 = os.path.join(BASE_DIR, "w2_4to5_v20_ledger.csv")
    p23 = os.path.join(BASE_DIR, "w2_2to3_v20_ledger.csv")
    df45_raw = pd.read_csv(p45) if os.path.exists(p45) else pd.DataFrame()
    df23_raw = pd.read_csv(p23) if os.path.exists(p23) else pd.DataFrame()
    l_4to5 = normalize_ledger(df45_raw, "4to5_V20", priority=4)
    l_2to3 = normalize_ledger(df23_raw, "2to3_V20", priority=5)
    # Pure incremental clean subsets
    l_4to5_inc = l_4to5[~l_4to5["is_held_3to4"]].copy() if "is_held_3to4" in l_4to5.columns else l_4to5
    ov23_col = next((c for c in ["is_held_1to2", "in_v18_holding", "is_overlap_v18"] if c in l_2to3.columns), None)
    l_2to3_inc = l_2to3[~l_2to3[ov23_col]].copy() if ov23_col else l_2to3

    qa = {
        "4to5_qa": qa_verify_raw_bars(l_4to5, "4to5_V20", code_bars) if not l_4to5.empty else None,
        "2to3_qa": qa_verify_raw_bars(l_2to3, "2to3_V20", code_bars) if not l_2to3.empty else None,
    }
    base3 = pd.concat([l_high, l_3to4, l_1to2], ignore_index=True)
    combos = {"Base3_MainOnly": base3}
    if not l_4to5_inc.empty:
        combos["Base3_plus_4to5_Inc"] = pd.concat([base3, l_4to5_inc], ignore_index=True)
        combos["Base3_plus_4to5_Strict116"] = pd.concat([base3, l_4to5_inc[l_4to5_inc["score"] >= 116]], ignore_index=True)
    if not l_2to3_inc.empty:
        combos["Base3_plus_2to3_Inc"] = pd.concat([base3, l_2to3_inc], ignore_index=True)
    if not l_4to5_inc.empty and not l_2to3_inc.empty:
        combos["Full5_Inc_Matrix"] = pd.concat([base3, l_4to5_inc, l_2to3_inc], ignore_index=True)

    res = {"csi300_bench": csi, "qa": qa, "portfolios": {}}
    for cname, cdf in combos.items():
        res["portfolios"][cname] = {
            f"slots_{k}": simulate_multi_slot_portfolio(cdf, n_slots=k, csi=csi) for k in (1, 2, 3)
        }
    out_p = os.path.join(BASE_DIR, "w3_5strategy_portfolio_and_qa.json")
    with open(out_p, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2)[:2900])


if __name__ == "__main__":
    main()

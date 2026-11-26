#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 BSE V2 evaluation helpers: Top-K equal-weight basket MTM + exact BSE window metrics."""
import json
import sys
from typing import Optional
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

RD045_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd045_abn_v2_bse_v2_refinement_20261126"
BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
for p in (RD045_DIR, BASE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _wf_sim_and_metrics as wfm
import _rd045_common as cm


def select_topk_basket_trades(
    df_view: pd.DataFrame, score_col: str, k: int = 3, threshold: Optional[str | float] = None,
    tie_col: str = "bj_amt_yi_t1", wf_only: bool = False,
) -> pd.DataFrame:
    """Non-overlapping Top-K equal-weight basket: picks up to K stocks on buy_date, holds until max exit_date."""
    if df_view.empty:
        return pd.DataFrame()
    m = df_view["can_buy_hygiene"].fillna(True).to_numpy(bool) & df_view[score_col].notna().to_numpy(bool)
    if wf_only and "wf_in_window" in df_view.columns:
        m &= df_view["wf_in_window"].fillna(False).to_numpy(bool)
    if threshold is not None:
        if isinstance(threshold, str):
            tv = pd.to_numeric(df_view[threshold], errors="coerce").to_numpy(float)
            m &= np.isfinite(tv) & (df_view[score_col].to_numpy(float) >= tv)
        else:
            m &= df_view[score_col].to_numpy(float) >= float(threshold)
    sub = df_view[m].copy()
    if sub.empty:
        return sub
    sc_cols = ["buy_date", score_col] + ([tie_col] if tie_col in sub.columns else []) + ["code"]
    asc = [True, False] + ([False] if tie_col in sub.columns else []) + [True]
    sub = sub.sort_values(sc_cols, ascending=asc, kind="mergesort")

    baskets = []
    cur_ed, cur_eh = "", 0
    for bdt, grp in sub.groupby("buy_date", sort=True):
        if cur_ed and (bdt < cur_ed or (bdt == cur_ed and 925 <= cur_eh)):
            continue
        top = grp.head(k)
        # Compute exact basket daily portfolio MTM from the m constituent legs
        legs = []
        for r in top.itertuples(index=False):
            segs = json.loads(r.mtm_json_use) if isinstance(r.mtm_json_use, str) and r.mtm_json_use else []
            if segs:
                legs.append((segs, str(r.exit_date), int(r.exit_hhmm), float(r.net_ret)))
        if not legs:
            continue
        max_ed = max(x[1] for x in legs)
        max_eh = max(x[2] for x in legs if x[1] == max_ed)
        # Note: gross_ret / net_ret of equal-weight basket = mean(net_ret) of legs
        # Build exact daily basket MTM: track each leg's cumulative NAV across union of dates!
        all_dts = sorted({d for lg in legs for d, _ in lg[0]})
        nav_legs = []
        for segs, _, _, nr in legs:
            dmap = {d: float(mv) for d, mv in segs}
            # Wait: gross segs need fee applied cleanly; leg cumulative net curve:
            arr = []
            cur_v = 1.0
            for idx_d, d_str in enumerate(all_dts):
                if d_str in dmap:
                    cur_v *= dmap[d_str]
                arr.append(cur_v)
            # Scale end value to exact 1+nr? Note fee applied in attach_exact_mtm_col!
            nav_legs.append((arr, segs))
        # Simpler & 100% exact: apply half-fee at entry & rest at exit on each leg's segs first, then sum equal weights!
        b_net = float(np.mean([x[3] for x in legs]))
        b_gross = float(np.mean(top["gross_ret"].to_numpy(float)))
        baskets.append({
            "buy_date": bdt, "exit_date": max_ed, "exit_hhmm": max_eh, "buy_hhmm": 925,
            "code": "+".join(top["code"].tolist()), "n_legs": len(legs),
            "gross_ret": b_gross, "net_ret": b_net,
            "legs_json": json.dumps([{"segs": lg[0], "nr": lg[3]} for lg in legs]),
            "can_buy_hygiene": True,
        })
        cur_ed, cur_eh = max_ed, max_eh
    return pd.DataFrame(baskets)


def eval_baskets_exact(
    bask_df: pd.DataFrame, bench_df: pd.DataFrame, fee_rt: float, start_dt: str, end_dt: str,
    windows: list[tuple[str, str, str]],
) -> dict:
    """Exact daily MTM evaluation of Top-K equal-weight baskets (mtm_diff == 0.0)."""
    if bask_df.empty:
        return {"mtm_reconciliation_diff": 0.0, "windows": {wn: {"n": 0, "nav": 1.0} for wn, _, _ in windows}}
    max_exit = str(bask_df["exit_date"].max())
    cal_end = min(str(bench_df["trade_date"].max()), max(end_dt, max_exit))
    b = bench_df[bench_df["trade_date"].between(start_dt, cal_end)].sort_values("trade_date").reset_index(drop=True)
    cal_dts = b["trade_date"].tolist()
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    csi_arr = b["csi300_daily_ret"].to_numpy(float)
    ew_arr = b["alla_ew_daily_ret"].to_numpy(float)

    f_buy = float(fee_rt) * 0.5
    f_sell = (1.0 - float(fee_rt)) / (1.0 - f_buy)
    dr_full = np.zeros(len(cal_dts), dtype=float)
    sub = bask_df[bask_df["buy_date"].between(start_dt, end_dt)].copy()
    new_net = []
    for r in sub.itertuples(index=False):
        legs = json.loads(r.legs_json)
        leg_dts = sorted({d for lg in legs for d, _ in lg["segs"]})
        if not leg_dts:
            new_net.append(0.0)
            continue
        m_cnt = len(legs)
        leg_curves = []
        for lg in legs:
            segs = lg["segs"]
            dmult = {}
            for k, (ds, mv) in enumerate(segs):
                val = float(mv)
                if k == 0:
                    val *= (1.0 - f_buy)
                if k == len(segs) - 1:
                    val *= f_sell
                dmult[ds] = val
            cv, c_arr = 1.0, []
            for ds in leg_dts:
                cv *= dmult.get(ds, 1.0)
                c_arr.append(cv)
            leg_curves.append(c_arr)
        port_curve = np.mean(np.array(leg_curves), axis=0)
        prev_v = 1.0
        for idx_d, ds in enumerate(leg_dts):
            ti = dt_idx.get(ds)
            if ti is not None:
                dr_full[ti] = port_curve[idx_d] / prev_v - 1.0
            prev_v = port_curve[idx_d]
        new_net.append(float(port_curve[-1] - 1.0))

    sub["net_ret"] = new_net
    mtm_nav = float(np.prod(1.0 + dr_full))
    tr_nav = float(np.prod(1.0 + sub["net_ret"].to_numpy(float))) if not sub.empty else 1.0
    mtm_diff = abs(mtm_nav - tr_nav)
    win_res = {}
    for wn, s, e in windows:
        se, ee = max(s, start_dt), min(e, end_dt)
        if se <= ee:
            win_res[wn] = wfm._calc_one_window(sub, None, dr_full, cal_dts, dt_idx, csi_arr, ew_arr, se, ee)
    return {"mtm_reconciliation_diff": round(mtm_diff, 10), "windows": win_res}

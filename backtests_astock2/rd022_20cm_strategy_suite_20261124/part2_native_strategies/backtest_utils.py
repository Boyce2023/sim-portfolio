#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D15-compliant trade execution and portfolio metrics (IS/OOS/2026/FULL, 1-slot, 3-slot, EW, ex-top5, 50bps)."""
import numpy as np
import pandas as pd

WINDOWS = [
    ("FULL", "2021-01-04", "2026-11-23"),
    ("IS", "2021-01-04", "2024-08-31"),
    ("OOS", "2024-09-01", "2026-11-23"),
    ("2026", "2026-01-01", "2026-11-23"),
]


def bench_return(nav_or_px: dict, sdt: str, edt: str) -> float:
    dts = sorted(nav_or_px.keys())
    prevs = [d for d in dts if d < sdt]
    posts = [d for d in dts if d <= edt]
    if not posts:
        return 0.0
    p0 = nav_or_px[prevs[-1]] if prevs else nav_or_px[dts[0]]
    p1 = nav_or_px[posts[-1]]
    return float(p1 / p0 - 1.0)


def ew20_bench_return(ew20_daily: dict, sdt: str, edt: str) -> float:
    rets = [v for d, v in ew20_daily.items() if sdt <= d <= edt]
    return float(np.prod(1.0 + np.array(rets, dtype=float)) - 1.0) if rets else 0.0


def simulate_fixed_hold(df_cand: pd.DataFrame, entry_mode: str, hold_days: int, fee: float = 0.0030,
                        exit_rule: str = "fixed", score_col: str = "score") -> pd.DataFrame:
    """
    entry_mode:
      - 'T0_close': enter at T0 ac (if sellable/tradable, close < zt_px - 0.011 so buyable at 14:55), exit T+hold_days close
      - 'T1_open': enter at T+1 ao (requires f1_buyable), exit T+(1+hold_days) close (or hold_days=1 => T+1 close or T+2? Let's standardize!)
    Convention: hold_days=1 on T1_open means buy T+1 09:25 open, sell T+2 close (1 overnight hold), wait:
      let's make exit_k explicit:
      - T0_close, hold_days=k -> exit at fk_ac (T+k close)
      - T1_open, hold_days=k -> buy at f1_ao (T+1 open), exit at f{1+k}_ac (e.g. k=1 => T+2 close, k=0 => T+1 close!)
      Let's double check: in A-share T+1, buying at T+1 open CAN sell at T+2 close (1 overnight) — wait can't sell T+1 close because T+1! So min k for T1_open is k>=1 (sell at f{1+k}_ac? Wait: T+1 open -> T+2 close is f2_ac, i.e., offset=2 = 1+1! Wait: prompt says "于T+1开盘买入，测试持有T+2/T+3/T+5/T+10", where T+2 means sell at T+2 close = f2_ac!).
      So let's define `exit_offset` directly:
      - For T0_close: exit_offset = 1 means T+1 close (`f1_ac`), 2 means T+2 close (`f2_ac`).
      - For T1_open: exit_offset = 2 means T+2 close (`f2_ac`), 3 means T+3 close (`f3_ac`), 5 means T+5 close (`f5_ac`), 10 means T+10 close (`f10_ac`)!
    """
    rows = []
    if df_cand.empty:
        return pd.DataFrame()
    sc_vals = df_cand[score_col].to_numpy(dtype=float) if score_col in df_cand.columns else np.zeros(len(df_cand))
    has_name = "c6" in df_cand.columns
    for idx, r in enumerate(df_cand.itertuples(index=False)):
        if entry_mode == "T0_close":
            if r.is_zt or not r.tradable or not r.sellable_close:
                continue
            b_dt, b_px, start_k = r.dt, float(r.ac), 1
        elif entry_mode == "T0_hit_zt":
            if not r.is_touch_zt or r.is_yizi_zt or not r.tradable:
                continue
            b_dt, b_px, start_k = r.dt, float(r.zt_px_adj), 1
        elif entry_mode == "T1_open":
            if not getattr(r, "f1_buyable", False) or not r.f1_dt or np.isnan(r.f1_ao) or r.f1_ao <= 0:
                continue
            b_dt, b_px, start_k = r.f1_dt, float(r.f1_ao), 2
        else:
            raise ValueError(entry_mode)

        target_k = hold_days if entry_mode.startswith("T0_") else max(2, hold_days)
        sell_k = target_k
        if exit_rule == "ma5_break":
            sell_k = 10
            for k in range(start_k, 11):
                ac_k = getattr(r, f"f{k}_ac", np.nan)
                ma5_k = getattr(r, f"f{k}_ma5", np.nan)
                sell_ok = getattr(r, f"f{k}_sellable", False)
                if np.isnan(ac_k):
                    sell_k = max(start_k, k - 1)
                    break
                if sell_ok and not np.isnan(ma5_k) and ac_k < ma5_k and not getattr(r, f"f{k}_zt", False):
                    sell_k = k
                    break
        elif exit_rule == "zt_ride_then_close":
            # Hold if ZT at exit_k (or true-yang immunity once)
            k = target_k
            while k < 10 and getattr(r, f"f{k}_zt", False):
                k += 1
            sell_k = k

        # Defer if sealed 20cm limit-down at sell_k
        while sell_k < 11 and not getattr(r, f"f{sell_k}_sellable", False):
            sell_k += 1
        while sell_k >= start_k and np.isnan(getattr(r, f"f{sell_k}_ac", np.nan)):
            sell_k -= 1
        if sell_k < start_k:
            continue
        s_px = float(getattr(r, f"f{sell_k}_ac"))
        s_dt = getattr(r, f"f{sell_k}_dt")
        if not s_dt or np.isnan(s_px) or s_px <= 0:
            continue
        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - fee) - 1.0
        rows.append({
            "sig_date": r.dt, "buy_date": b_dt, "exit_date": s_dt,
            "c6": r.c6, "score": float(sc_vals[idx]),
            "buy_px": b_px, "exit_px": s_px,
            "gross_ret": gross, "net_ret": net,
            "hold_bars": sell_k - (0 if entry_mode.startswith("T0_") else 1),
        })
    return pd.DataFrame(rows)


def _sim_k_slots(trades: pd.DataFrame, k_slots: int, fee_override: float | None = None) -> tuple[pd.DataFrame, float, float]:
    if trades.empty:
        return pd.DataFrame(), 1.0, 0.0
    srt = trades.sort_values(["buy_date", "score", "c6"], ascending=[True, False, True])
    # Group by buy_date for deterministic slot allocation
    free_dts = [""] * k_slots
    taken = []
    # For k-slot equity curve, track realized trade contributions or daily mark?
    # Standard slot model: each slot gets 1/k capital; when a slot closes at exit_date, apply (1 + net/k)?
    # Even cleaner: track k independent slot NAVs, then portfolio NAV = mean(slot_navs) or sequential 1/k compounding!
    slot_navs = [1.0] * k_slots
    slot_trades = [[] for _ in range(k_slots)]
    for bdt, grp in srt.groupby("buy_date", sort=True):
        # Free slots where bdt > free_dt (strictly no same-day close->open conflict since we buy at open/close)
        avail = [s for s in range(k_slots) if free_dts[s] == "" or bdt > free_dts[s]]
        for s, (_, row) in zip(avail, grp.iterrows()):
            r = float(row["net_ret"])
            if fee_override is not None:
                r = (1.0 + float(row["gross_ret"])) * (1.0 - fee_override) - 1.0
            slot_navs[s] *= (1.0 + r)
            free_dts[s] = str(row["exit_date"])
            d = row.to_dict()
            d["net_ret_eval"] = r
            d["slot_id"] = s
            taken.append(d)
            slot_trades[s].append(d)
    if not taken:
        return pd.DataFrame(), 1.0, 0.0
    tdf = pd.DataFrame(taken).sort_values(["exit_date", "buy_date"]).reset_index(drop=True)
    if k_slots == 1:
        nav, pk, mdd = 1.0, 1.0, 0.0
        for r in tdf["net_ret_eval"]:
            nav *= (1.0 + float(r))
            pk = max(pk, nav)
            mdd = max(mdd, (pk - nav) / pk)
        return tdf, nav, mdd
    # For k_slots > 1, track exact portfolio NAV on all exit dates assuming each slot has 1/k initial capital
    # (no rebalancing across slots vs equal compounding: sum(slot_navs)/k is exact!)
    s_cur = [1.0 / k_slots] * k_slots
    nav, pk, mdd = 1.0, 1.0, 0.0
    for r_row in tdf.itertuples(index=False):
        sid = int(r_row.slot_id)
        s_cur[sid] *= (1.0 + float(r_row.net_ret_eval))
        nav = sum(s_cur)
        pk = max(pk, nav)
        mdd = max(mdd, (pk - nav) / pk)
    return tdf, nav, mdd


def calc_d15_suite(trades: pd.DataFrame, sh300: dict, ew20_daily: dict) -> dict:
    out = {}
    for wname, sdt, edt in WINDOWS:
        sub = trades[(trades["buy_date"] >= sdt) & (trades["buy_date"] <= edt)].copy() if not trades.empty else pd.DataFrame()
        hs_r = bench_return(sh300, sdt, edt)
        ew20_r = ew20_bench_return(ew20_daily, sdt, edt)
        if sub.empty:
            out[wname] = {"raw_n": 0, "nav_1s": 1.0, "nav_3s": 1.0, "ew_nav": 1.0, "hs300_ret": round(hs_r * 100, 2), "ew20_ret": round(ew20_r * 100, 2)}
            continue
        rets = sub["net_ret"].to_numpy(dtype=float)
        ew_day = sub.groupby("buy_date")["net_ret"].mean().to_numpy(dtype=float)
        ew_nav = float(np.prod(1.0 + ew_day))
        t1, nav1, mdd1 = _sim_k_slots(sub, 1)
        t3, nav3, mdd3 = _sim_k_slots(sub, 3)
        _, nav1_50, _ = _sim_k_slots(sub, 1, fee_override=0.0050)
        _, nav3_50, _ = _sim_k_slots(sub, 3, fee_override=0.0050)

        # Ex-top5 outliers
        if len(t1) > 5:
            top5_idx = t1["net_ret_eval"].nlargest(5).index
            ex5_1 = float(np.prod(1.0 + t1.drop(top5_idx)["net_ret_eval"].to_numpy()))
        else:
            ex5_1 = 1.0
        if len(t3) > 5:
            s_cur = [1.0 / 3] * 3
            drop_i = set(t3["net_ret_eval"].nlargest(5).index)
            for idx, r_row in enumerate(t3.itertuples(index=False)):
                if idx not in drop_i:
                    s_cur[int(r_row.slot_id)] *= (1.0 + float(r_row.net_ret_eval))
            ex5_3 = sum(s_cur)
        else:
            ex5_3 = 1.0

        r1 = t1["net_ret_eval"].to_numpy(dtype=float) if not t1.empty else np.array([0.0])
        w1, l1 = r1[r1 > 0], r1[r1 <= 0]
        po1 = float(w1.mean() / abs(l1.mean())) if (len(w1) and len(l1) and l1.mean() < 0) else (99.0 if len(w1) else 0.0)
        r3 = t3["net_ret_eval"].to_numpy(dtype=float) if not t3.empty else np.array([0.0])
        w3, l3 = r3[r3 > 0], r3[r3 <= 0]
        po3 = float(w3.mean() / abs(l3.mean())) if (len(w3) and len(l3) and l3.mean() < 0) else (99.0 if len(w3) else 0.0)
        hlz_t = float(r1.mean() / r1.std(ddof=1) * np.sqrt(len(r1))) if (len(r1) > 1 and r1.std(ddof=1) > 0) else 0.0

        out[wname] = {
            "raw_n": int(len(sub)), "days": int(len(ew_day)),
            "raw_wr": round(float((rets > 0).mean() * 100), 2),
            "raw_mean": round(float(rets.mean() * 100), 2),
            "ew_nav": round(ew_nav, 3),
            "n_1s": int(len(t1)), "wr_1s": round(float((r1 > 0).mean() * 100), 2), "po_1s": round(po1, 2),
            "nav_1s": round(nav1, 3), "mdd_1s": round(mdd1 * 100, 2), "ex5_1s": round(ex5_1, 3), "fee50_1s": round(nav1_50, 3),
            "n_3s": int(len(t3)), "wr_3s": round(float((r3 > 0).mean() * 100), 2), "po_3s": round(po3, 2),
            "nav_3s": round(nav3, 3), "mdd_3s": round(mdd3 * 100, 2), "ex5_3s": round(ex5_3, 3), "fee50_3s": round(nav3_50, 3),
            "hs300_ret": round(hs_r * 100, 2), "ew20_ret": round(ew20_r * 100, 2),
            "ex_hs300_1s": round((nav1 - 1.0 - hs_r) * 100, 2),
            "ex_ew20_1s": round((nav1 - 1.0 - ew20_r) * 100, 2),
            "ex_hs300_3s": round((nav3 - 1.0 - hs_r) * 100, 2),
            "ex_ew20_3s": round((nav3 - 1.0 - ew20_r) * 100, 2),
            "hlz_t": round(hlz_t, 2),
        }
    return out

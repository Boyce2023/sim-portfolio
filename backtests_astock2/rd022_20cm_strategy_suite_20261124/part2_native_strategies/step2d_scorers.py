#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IS-calibrated soft scoring cards and dynamic exit simulator for Top 3 20cm native strategies."""
import numpy as np
import pandas as pd


def score_p1_s1(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """P1: 20cm First-Board Deep-Open Reversal (T0 non-yizi first ZT, T+1 open -10% ~ -3.5%)."""
    skel = (
        df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0)
        & (df["tox_90d"] == 0) & (df["reg_10d"] == 0)
        & df["is_zt"] & (df["streak"] == 1) & (~df["is_yizi_zt"])
        & df["f1_buyable"] & df["f1_o_pct"].between(-0.10, -0.035)
    )
    sc = np.full(len(df), 70.0)
    sc += np.where(df["zt_hhmm"] <= 1000, -10.0, 0.0)
    sc += np.where((df["zt_hhmm"] >= 1430) & (df["zt_hhmm"] < 9999), 6.0, 0.0)
    sc += np.where(df["lhb_inst_net"] > 0, 10.0, 0.0)
    sc += np.where(df["lhb_lh_net_pos"] == 1, 8.0, 0.0)
    sc += np.where(df["real_free_mcap"] <= 30.0, 6.0, 0.0)
    sc += np.where(df["lock_top10"].fillna(0) >= 45.0, 5.0, 0.0)
    sc += np.where(df["dist_3d30"] >= 0.10, 6.0, 0.0)
    sc += np.where(df["zt_cnt_60d"] >= 2, 5.0, 0.0)
    sc += np.where(df["bias20"] <= 0.10, 5.0, 0.0)
    sc += np.where(df["f1_o_pct"].between(-0.08, -0.045), 4.0, 0.0)
    wd = pd.to_datetime(df["f1_dt"], errors="coerce").dt.dayofweek.fillna(-1)
    mon = df["f1_dt"].astype(str).str.slice(5, 7)
    sc += np.where(wd == 0, -10.0, 0.0)
    sc += np.where(mon.isin(["01", "04"]), -6.0, 0.0)
    sc += np.where(df["mkt20_zt_cnt"] >= 16, -12.0, 0.0)
    sc += np.where((df["lhb_quant"] >= 1) & (df["lhb_inst_net"] <= 0), -5.0, 0.0)
    return skel, pd.Series(sc, index=df.index)


def score_p2_s3(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """P2: 20cm Broken-Board True-Yang Rebound (prev_streak>=1, ~is_zt, true_yang, to<=35%, T+1 open -7% ~ +2%)."""
    skel = (
        df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0)
        & (df["tox_90d"] == 0) & (df["reg_10d"] == 0)
        & (df["prev_streak"] >= 1) & (~df["is_zt"]) & df["is_true_yang"] & (df["to"] <= 35.0)
        & df["f1_buyable"] & df["f1_o_pct"].between(-0.07, 0.02)
    )
    sc = np.full(len(df), 70.0)
    sc += np.where(df["pos60"] <= 0.50, 12.0, 0.0)
    sc += np.where(df["prev_pos20"] <= 0.45, 10.0, 0.0)
    sc += np.where(df["bias20"] <= 0.10, 8.0, 0.0)
    sc += np.where(df["close"] <= 25.0, 6.0, 0.0)
    sc += np.where(df["zt_cnt_60d"] >= 2, 5.0, 0.0)
    sc += np.where(df["dist_3d30"] >= 0.10, 6.0, 0.0)
    sc += np.where(df["prev_zt_obc"] == 0, 4.0, 0.0)
    sc += np.where(df["kpl_hist_10zt_max"] >= 4, 4.0, 0.0)
    sc += np.where(df["lhb_lh_net_pos"] == 1, 5.0, 0.0)
    mon = df["f1_dt"].astype(str).str.slice(5, 7)
    sc += np.where(mon.isin(["01", "04"]), -8.0, 0.0)
    sc += np.where(df["f1_o_pct"] > 0.0, -4.0, 0.0)
    sc += np.where((df["is_tech"] == 1) & (df["pos60"] > 0.75), -5.0, 0.0)
    return skel, pd.Series(sc, index=df.index)


def score_p3_s4(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """P3: 20cm Low-Turnover Zhaban Anti-Nuke (touch ZT & broke, ret<12%, to<=30%, T+1 open -10% ~ -2.5%)."""
    skel = (
        df["tradable"] & (df["is_st_pit"] == 0) & (df["close"] >= 2.0)
        & (df["tox_90d"] == 0) & (df["reg_10d"] == 0)
        & df["is_touch_zt"] & (~df["is_zt"]) & (df["ret"] < 0.12) & (df["to"] <= 30.0)
        & df["f1_buyable"] & df["f1_o_pct"].between(-0.10, -0.025)
    )
    sc = np.full(len(df), 70.0)
    sc += np.where(df["real_to"] < 20.0, 10.0, 0.0)
    sc += np.where(df["pos60"] <= 0.50, 8.0, 0.0)
    sc += np.where(df["bias20"] <= 0.10, 6.0, 0.0)
    sc += np.where(df["close"] <= 25.0, 6.0, 0.0)
    sc += np.where(df["dist_3d30"] >= 0.10, 5.0, 0.0)
    sc += np.where(df["is_true_yang"], 4.0, 0.0)
    sc += np.where(df["lock_top10"].fillna(0) >= 45.0, 4.0, 0.0)
    sc += np.where(df["close"] > 40.0, -10.0, 0.0)
    sc += np.where(df["prev_pos20"] > 0.75, -8.0, 0.0)
    mon = df["f1_dt"].astype(str).str.slice(5, 7)
    sc += np.where(mon.isin(["01", "04"]), -6.0, 0.0)
    sc += np.where(df["lhb_has"] == 1, -8.0, 0.0)
    sc += np.where(df["mkt20_zt_cnt"] >= 16, -8.0, 0.0)
    return skel, pd.Series(sc, index=df.index)


def sim_exit_v2(pool: pd.DataFrame, rule: str, fee: float = 0.0030) -> pd.DataFrame:
    rows = []
    for r in pool.itertuples(index=False):
        if not r.f1_buyable or not r.f1_dt or np.isnan(r.f1_ao) or r.f1_ao <= 0:
            continue
        b_px, b_dt = float(r.f1_ao), r.f1_dt
        sell_k, s_px = 2, np.nan
        if rule == "T2_close":
            sell_k = 2
        elif rule == "T2_zt_ride":
            k = 2
            if r.f1_zt:
                while k < 10 and getattr(r, f"f{k}_zt", False):
                    k += 1
            sell_k = k
        elif rule == "T2_zt_tp10":
            if r.f1_zt:
                k = 2
                while k < 10 and getattr(r, f"f{k}_zt", False):
                    k += 1
                sell_k = k
            else:
                lim = float(r.f1_ac) * 1.10
                if not np.isnan(r.f2_ah) and float(r.f2_ah) >= lim and r.f2_sellable:
                    s_px, sell_k = max(float(r.f2_ao), lim), 2
                else:
                    sell_k = 2
        elif rule == "T2_gap_cut_only":
            if r.f1_zt:
                k = 2
                while k < 10 and getattr(r, f"f{k}_zt", False):
                    k += 1
                sell_k = k
            else:
                f2_op = float(r.f2_o_pct) if not np.isnan(r.f2_o_pct) else 0.0
                if (float(r.f1_ac) < float(r.f1_ao) * 0.98 and f2_op < 0.0) or (f2_op >= 0.06):
                    s_px, sell_k = float(r.f2_ao), 2
                else:
                    sell_k = 2
        if np.isnan(s_px):
            while sell_k < 11 and not getattr(r, f"f{sell_k}_sellable", False):
                sell_k += 1
            while sell_k >= 2 and np.isnan(getattr(r, f"f{sell_k}_ac", np.nan)):
                sell_k -= 1
            if sell_k < 2:
                continue
            s_px = float(getattr(r, f"f{sell_k}_ac"))
        s_dt = getattr(r, f"f{sell_k}_dt")
        if not s_dt or np.isnan(s_px) or s_px <= 0:
            continue
        gross = s_px / b_px - 1.0
        net = (1.0 + gross) * (1.0 - fee) - 1.0
        rows.append({
            "sig_date": r.dt, "buy_date": b_dt, "exit_date": s_dt,
            "c6": r.c6, "score": float(r.score), "open_pct": round(float(r.f1_o_pct) * 100, 2),
            "buy_px": round(b_px, 4), "exit_px": round(s_px, 4),
            "gross_ret": gross, "net_ret": net, "hold_bars": sell_k - 1,
        })
    return pd.DataFrame(rows)

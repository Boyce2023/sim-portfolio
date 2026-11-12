#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
v10_backtest_eval.py — 09:25 Auction Rank, Intraday trig_p Execution, 4 Exits, Hybrid WF & D15 Evaluator
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from v10_pit_and_sim import CSI300_ANNUAL, CSI300_5Y_CUM, FEE_RATE


def compute_d2_auction_scores(sub_df: pd.DataFrame) -> pd.DataFrame:
    df = sub_df.copy()
    # Nuclear button halt: average D2 open of yesterday's turnover first-boards < 0%
    auc_mean = df.groupby("d2_dt")["d2_o_pct"].transform("mean")
    df["prev_zt_auc_avg"] = auc_mean
    df["nuclear_halt"] = auc_mean < 0.0
    df["promo_freeze"] = df["mkt_promo_ma5"] < 0.13

    # 1. Exact M2_Clean auction rank (ranks across all D1 turnover first-boards on D2)
    df["mkt_open_rk"] = df.groupby("d2_dt")["d2_o_pct"].rank(ascending=False, method="min")
    df["theme_open_rk"] = df.groupby(["d2_dt", "plate"])["d2_o_pct"].rank(ascending=False, method="min")
    p2_map = df.groupby(["d2_dt", "plate"])["d2_o_pct"].transform(
        lambda s: s.nlargest(2).iloc[-1] if len(s) >= 2 else -0.05
    )
    df["open_lead"] = np.where(df["theme_open_rk"] == 1, df["d2_o_pct"] - p2_map, 0.0)
    auc_orig = (
        np.where(df["theme_open_rk"] == 1, 35.0, np.where(df["theme_open_rk"] == 2, 5.0, -25.0))
        + np.where(df["mkt_open_rk"] <= 3, 20.0, np.where(df["mkt_open_rk"] <= 6, 12.0, 0.0))
        + np.where(df["open_lead"] >= 0.020, 22.0, np.where(df["open_lead"] >= 0.010, 12.0, 0.0))
        + np.where(df["d2_o_pct"].between(0.040, 0.082), 20.0, np.where(df["d2_o_pct"].between(0.030, 0.040), 10.0, 0.0))
    )
    df["s_quant_orig"] = df["s_q_base_orig"] + auc_orig
    df["tot_orig"] = df["s_prior_orig"] + df["s_quant_orig"]

    # 2. Upgraded Buyable Rank + Sub-Branch Leader + Yizi Windvane
    df["is_buyable_open"] = (df["d2_open"] < df["d2_zt_p"] - 0.005) & df["gate_ok"]
    df["plate_d2_yizi_cnt"] = df.groupby(["d2_dt", "plate"])["d2_is_yizi"].transform("sum")
    buy_o = np.where(df["is_buyable_open"], df["d2_o_pct"], -9.99)
    df["_buy_o"] = buy_o
    df["buyable_plate_rk"] = df.groupby(["d2_dt", "plate"])["_buy_o"].rank(ascending=False, method="min")
    df["subbranch_rk"] = df.groupby(["d2_dt", "plate", "r_short"])["_buy_o"].rank(ascending=False, method="min")
    p2_buy = df.groupby(["d2_dt", "plate"])["_buy_o"].transform(
        lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05
    )
    df["buy_open_lead"] = np.where(df["buyable_plate_rk"] == 1, df["d2_o_pct"] - p2_buy, 0.0)

    has_distinct_sub = (df["p_sz"] >= 8) & (df["r_short"] != df["plate"]) & (df["r_short"] != "其他") & (df["r_short"] != "")
    rk_bonus_dual = np.where(
        df["buyable_plate_rk"] == 1, 35.0,
        np.where(
            has_distinct_sub & (df["subbranch_rk"] == 1), 24.0,
            np.where(df["buyable_plate_rk"] == 2, 8.0, -25.0)
        )
    )
    auc_dual = (
        rk_bonus_dual
        + np.where(df["mkt_open_rk"] <= 3, 20.0, np.where(df["mkt_open_rk"] <= 6, 12.0, 0.0))
        + np.where(df["buy_open_lead"] >= 0.020, 22.0, np.where(df["buy_open_lead"] >= 0.010, 12.0, 0.0))
        + np.where(df["plate_d2_yizi_cnt"] >= 1, 10.0, 0.0)
        + np.where(df["d2_o_pct"].between(0.040, 0.082), 20.0, np.where(df["d2_o_pct"].between(0.018, 0.040), 12.0, 0.0))
    )
    df["s_quant_dual"] = df["s_q_base_dual"] + auc_dual
    df["tot_dual"] = df["s_prior_dual"] + df["s_quant_dual"]

    # Intraday upward ignition conditional trigger price trig_p
    df["trig_p"] = np.minimum(
        df["d2_zt_p"],
        np.maximum(np.round(df["d2_open"] * 1.012, 2), np.round(df["close"] * 1.065, 2))
    )
    return df


def simulate_single_trade(row, price_lookup, all_dts, dt_to_idx, entry_mode="trig", exit_mode="E4", fee=FEE_RATE):
    c6, d2 = row["c6"], row["d2_dt"]
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0:
        return None
    d2_bar = price_lookup.get((c6, d2))
    if not d2_bar:
        return None
    o2, h2, l2, c2, zt2, dt2, is_zt2, is_yz_dt2 = d2_bar
    if o2 >= zt2 - 0.005 or o2 <= 0:
        return None  # Unbuyable D2 yizi open strictly excluded

    if entry_mode == "trig":
        trig_p = float(row["trig_p"])
        if trig_p >= zt2 - 0.005:
            return None  # Never queue at limit-up price
        if h2 < trig_p:
            return None  # Conditional stop-buy never triggered intraday
        buy_px = trig_p
    else:
        buy_px = o2

    curr_idx = idx2 + 1
    prev_c = c2
    exit_px, exit_dt, exit_open = None, None, False

    if not is_zt2:
        # Unsealed on D2 -> exit at D3 open (unless locked in yizi limit-down)
        while curr_idx < len(all_dts):
            dc = all_dts[curr_idx]
            bar = price_lookup.get((c6, dc))
            if not bar:
                exit_px, exit_dt = prev_c, dc; break
            o, h, l, c, zt, dt_p, izt, iyz_dt = bar
            if iyz_dt:
                prev_c = c; curr_idx += 1; continue
            exit_px, exit_dt, exit_open = o, dc, True; break
    else:
        # Sealed 2nd board on D2!
        while curr_idx < len(all_dts):
            dc = all_dts[curr_idx]
            bar = price_lookup.get((c6, dc))
            if not bar:
                exit_px, exit_dt = prev_c, dc; break
            o, h, l, c, zt, dt_p, izt, iyz_dt = bar
            if iyz_dt:
                prev_c = c; curr_idx += 1; continue

            if exit_mode == "E4":  # Classic Broken-Board Close Exit
                if izt and (curr_idx - idx2 < 10):
                    prev_c = c; curr_idx += 1; continue
                exit_px, exit_dt = c, dc; break
            elif exit_mode == "E7":  # Bull Ride (ZT or True Yang > prev_c)
                if (izt or (c >= o and c > prev_c)) and (curr_idx - idx2 < 10):
                    prev_c = c; curr_idx += 1; continue
                exit_px, exit_dt = c, dc; break
            elif exit_mode == "P2":  # Non-ZT Open Exit + ZT Open -2% Stop
                if o < zt - 0.01:
                    exit_px, exit_dt, exit_open = o, dc, True; break
                stop_p = round(zt * 0.98, 2)
                if l <= stop_p:
                    exit_px, exit_dt = stop_p, dc; break
                if curr_idx - idx2 >= 10:
                    exit_px, exit_dt = c, dc; break
                prev_c = c; curr_idx += 1; continue
            elif exit_mode == "B1":  # D3 50% Open Lock if non-ZT strong + 50% Ride
                if curr_idx == idx2 + 1 and (prev_c * 1.015 <= o < zt - 0.01):
                    p1 = o
                    st_p = round(min(o * 0.96, prev_c * 0.985), 2)
                    if l <= st_p:
                        exit_px, exit_dt = 0.5 * p1 + 0.5 * st_p, dc; break
                    if not izt:
                        exit_px, exit_dt = 0.5 * p1 + 0.5 * c, dc; break
                    # 50% rides further via E4
                    curr_idx += 1; prev_c = c
                    p2 = prev_c
                    while curr_idx < len(all_dts):
                        dc2 = all_dts[curr_idx]
                        b2 = price_lookup.get((c6, dc2))
                        if not b2: p2, exit_dt = prev_c, dc2; break
                        if b2[7]: prev_c = b2[3]; curr_idx += 1; continue
                        if b2[6] and (curr_idx - idx2 < 10): prev_c = b2[3]; curr_idx += 1; continue
                        p2, exit_dt = b2[3], dc2; break
                    exit_px = 0.5 * p1 + 0.5 * p2; break
                else:
                    if izt and (curr_idx - idx2 < 10):
                        prev_c = c; curr_idx += 1; continue
                    exit_px, exit_dt = c, dc; break

    if exit_px is None:
        exit_px = prev_c
        exit_dt = all_dts[min(curr_idx, len(all_dts) - 1)]

    gross = exit_px / buy_px - 1.0
    net = (1.0 + gross) * (1.0 - fee) - 1.0
    return {
        "c6": c6, "name": row["name"], "plate": row["plate"], "r_short": row["r_short"],
        "d1_dt": row["dt_str"], "buy_date": d2, "exit_date": exit_dt, "exit_at_open": exit_open,
        "o_pct": round(float(row["d2_o_pct"]), 4), "buy_price": round(float(buy_px), 2),
        "exit_price": round(float(exit_px), 2), "sealed_2b": int(is_zt2),
        "gross_ret": round(float(gross), 4), "net_ret": round(float(net), 4),
    }

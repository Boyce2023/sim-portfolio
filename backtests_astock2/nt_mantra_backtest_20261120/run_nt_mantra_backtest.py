#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
A股量化研究：大哥护盘五句口诀十年实证回测（2017-01-17 至 2026-11-19，叠加 2011~2026 纯ETF 15年对照）
严格零未来函数（PIT）：
  1) 量比一律采用 shift(1) 过去20日滚动中位数；
  2) 均线与20日高点回撤采用当日及之前闭集数据；
  3) 同时评估【T日尾盘买入】与【T+1日开盘买入(shift(1)次日开盘执行)】双口径；
  4) 调仓扣单边 0.15%（双边 0.30%）交易成本；
  5) 排查股指期货交割日（每月第三个周五）移仓爆量干扰与高位/低位语境混杂变量；
  6) 严格执行 D15 跨时期/去极值/等仓位基准对比与 TEI 评分。
"""
import os
import sys
import json
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

TEI_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/theory_backtest_15y_20261119"
sys.path.insert(0, TEI_DIR)
from tei_metrics import compute_period_metrics

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/nt_mantra_backtest_20261120"
PANEL_PATH = f"{OUT_DIR}/data_cache/nt_mantra_daily_panel.parquet"
COST_ONE_WAY = 0.0015  # 单边 0.15%


def add_forward_columns(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy().reset_index(drop=True)
    for prefix in ["c300", "c500"]:
        c = d[f"{prefix}_close"].to_numpy(dtype=float)
        o = d[f"{prefix}_open"].to_numpy(dtype=float)
        l = d[f"{prefix}_low"].to_numpy(dtype=float)
        n = len(d)

        for k in [1, 3, 5, 10, 20]:
            tail_r = np.full(n, np.nan)
            tail_r[: n - k] = c[k:] / c[: n - k] - 1.0
            d[f"{prefix}_tail_fwd_{k}d"] = tail_r

            open_r = np.full(n, np.nan)
            if k == 1:
                open_r[: n - 1] = c[1:] / o[1:] - 1.0
            else:
                open_r[: n - k] = c[k:] / o[1 : n - k + 1] - 1.0
            d[f"{prefix}_open_fwd_{k}d"] = open_r

        tail_mae_low = np.full(n, np.nan)
        open_mae_low = np.full(n, np.nan)
        for i in range(n - 20):
            min_low = np.min(l[i + 1 : i + 21])
            tail_mae_low[i] = min_low / c[i] - 1.0
            open_mae_low[i] = min_low / o[i + 1] - 1.0
        d[f"{prefix}_tail_mae20_low"] = tail_mae_low
        d[f"{prefix}_open_mae20_low"] = open_mae_low
    return d


def decluster_mask(mask: pd.Series, cooldown: int = 5) -> pd.Series:
    arr = mask.to_numpy(dtype=bool)
    out = np.zeros_like(arr)
    last_idx = -9999
    for i, flag in enumerate(arr):
        if flag and (i - last_idx >= cooldown):
            out[i] = True
            last_idx = i
    return pd.Series(out, index=mask.index)


def define_signals(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["c300_ma60"] = d["c300_close"].rolling(60, min_periods=60).mean()
    d["weak"] = (d["c300_close"] < d["c300_ma20"]) | (d["c300_dd20"] <= -0.03)
    d["high_pos"] = (d["c300_close"] > d["c300_ma20"]) & (d["c300_ret20"] >= 0.05)

    hl_rng = (d["c300_high"] - d["c300_low"]).replace(0.0, np.nan)
    lower_shd_ratio = (np.minimum(d["c300_open"], d["c300_close"]) - d["c300_low"]) / hl_rng
    d["pulse"] = (d["c300_pullup"] >= 0.008) & ((d["c300_close"] > d["c300_open"]) | (lower_shd_ratio >= 0.40))
    d["pulse_strict"] = (d["c300_pullup"] >= 0.008) & (d["c300_close"] > d["c300_open"])

    # Mantra 1: 脉冲但不放量 (<1.2x)
    d["m1_weak"] = d["weak"] & d["pulse"] & (d["etf_amt_spike_20d"] < 1.2)
    d["m1_weak_strict"] = d["weak"] & d["pulse_strict"] & (d["etf_amt_spike_20d"] < 1.2)
    d["m1_all"] = d["pulse"] & (d["etf_amt_spike_20d"] < 1.2)

    # Mantra 2: 脉冲同时放量 (1.2x ~ 2.0x)
    d["m2_weak"] = d["weak"] & d["pulse"] & (d["etf_amt_spike_20d"] >= 1.2) & (d["etf_amt_spike_20d"] < 2.0)
    d["m2_weak_strict"] = d["weak"] & d["pulse_strict"] & (d["etf_amt_spike_20d"] >= 1.2) & (d["etf_amt_spike_20d"] < 2.0)
    d["m2_all"] = d["pulse"] & (d["etf_amt_spike_20d"] >= 1.2) & (d["etf_amt_spike_20d"] < 2.0)

    # Mantra 3: 宽基爆量
    d["m3_weak_20"] = d["weak"] & (d["etf_amt_spike_20d"] >= 2.0)
    d["m3_weak_20_posflow"] = d["weak"] & (d["etf_amt_spike_20d"] >= 2.0) & (d["etf_net_flow_yi"] > 0.0)
    d["m3_weak_20_pulse"] = d["weak"] & d["pulse"] & (d["etf_amt_spike_20d"] >= 2.0)
    d["m3_weak_25"] = d["weak"] & (d["etf_amt_spike_20d"] >= 2.5)
    d["m3_weak_510300_25"] = d["weak"] & (d["etf510300_amt_spike"] >= 2.5)
    d["m3_all_20"] = (d["etf_amt_spike_20d"] >= 2.0)
    d["m3_high_20"] = d["high_pos"] & (d["etf_amt_spike_20d"] >= 2.0)

    # Mantra 4: 期现双爆量 vs 单宽基爆量
    fut_ok = d["fut3_spike_20d"].notna()
    d["m4_weak_18_all"] = fut_ok & d["weak"] & (d["etf_amt_spike_20d"] >= 1.8) & (d["fut3_spike_20d"] >= 1.5)
    d["m4_weak_18_nodeliv"] = d["m4_weak_18_all"] & (~d["is_delivery_day"])
    d["m4_weak_18_nowin"] = d["m4_weak_18_all"] & (~d["is_delivery_win"])
    d["m4_weak_20_all"] = fut_ok & d["weak"] & (d["etf_amt_spike_20d"] >= 2.0) & (d["fut3_spike_20d"] >= 1.5)
    d["m4_weak_20_nodeliv"] = d["m4_weak_20_all"] & (~d["is_delivery_day"])
    d["m4_weak_20_nowin"] = d["m4_weak_20_all"] & (~d["is_delivery_win"])
    d["m4_allw_18_all"] = fut_ok & (d["etf_amt_spike_20d"] >= 1.8) & (d["fut3_spike_20d"] >= 1.5)
    d["m4_allw_18_nodeliv"] = d["m4_allw_18_all"] & (~d["is_delivery_day"])

    d["m3_only_18_nodeliv"] = fut_ok & d["weak"] & (d["etf_amt_spike_20d"] >= 1.8) & (d["fut3_spike_20d"] < 1.5) & (~d["is_delivery_day"])
    d["m3_only_20_nodeliv"] = fut_ok & d["weak"] & (d["etf_amt_spike_20d"] >= 2.0) & (d["fut3_spike_20d"] < 1.5) & (~d["is_delivery_day"])
    d["m3_only_allw_18_nodeliv"] = fut_ok & (d["etf_amt_spike_20d"] >= 1.8) & (d["fut3_spike_20d"] < 1.5) & (~d["is_delivery_day"])

    # Mantra 5: 远古巨阳
    d["any_rescue_sig"] = d["m2_weak"] | d["m3_weak_20"] | d["m4_weak_18_nodeliv"]
    d["rescue_recent_15d"] = d["any_rescue_sig"].rolling(15, min_periods=1).max().shift(1).fillna(0).astype(bool)
    d["m5_25_after_rescue"] = d["rescue_recent_15d"] & (d["c300_ret"] >= 0.025)
    d["m5_30_after_rescue"] = d["rescue_recent_15d"] & (d["c300_ret"] >= 0.030)
    d["m5_35_after_rescue"] = d["rescue_recent_15d"] & (d["c300_ret"] >= 0.035)
    d["m5_25_ex924"] = d["m5_25_after_rescue"] & (~d["date"].isin(["2024-09-24", "2024-09-26", "2024-09-27"]))
    d["m5_25_flow_ge50"] = d["m5_25_after_rescue"] & (d["etf_net_flow_yi"] >= 50.0)
    d["m5_25_flow_lt50"] = d["m5_25_after_rescue"] & (d["etf_net_flow_yi"] < 50.0)
    d["m5_25_bear18"] = d["m5_25_after_rescue"] & (d["date"] <= "2019-06-01")
    return d


def summarize_event_set(df: pd.DataFrame, mask: pd.Series, name: str, include_dates: bool = False) -> dict:
    sub = df[mask].copy()
    n = len(sub)
    if n == 0:
        return {"name": name, "n": 0}

    dc_mask = mask & decluster_mask(mask, 5)
    res = {
        "name": name,
        "n": int(n),
        "n_decluster_5d": int(dc_mask.sum()),
        "same_day_c300_mean_pct": round(float(sub["c300_ret"].mean() * 100), 2),
        "same_day_c500_mean_pct": round(float(sub["c500_ret"].mean() * 100), 2),
        "etf_spike_mean": round(float(sub["etf_amt_spike_20d"].mean()), 2),
        "etf_net_flow_mean_yi": round(float(sub["etf_net_flow_yi"].mean()), 2),
        "etf_net_flow_med_yi": round(float(sub["etf_net_flow_yi"].median()), 2),
        "etf_net_flow_pos_pct": round(float((sub["etf_net_flow_yi"] > 0).mean() * 100), 1),
        "etf_net_flow_gt20_pct": round(float((sub["etf_net_flow_yi"] >= 20.0).mean() * 100), 1),
        "horizons": {},
        "decluster_5d_c300_tail": {},
    }

    for idx_pfx in ["c300", "c500"]:
        for entry in ["tail", "open"]:
            key_blk = f"{idx_pfx}_{entry}"
            res["horizons"][key_blk] = {}
            for k in [1, 3, 5, 10, 20]:
                col = f"{idx_pfx}_{entry}_fwd_{k}d"
                s = sub[col].dropna()
                base = df[col].dropna()
                if len(s) == 0:
                    continue
                wins = s[s > 0]
                losses = s[s < 0]
                avg_w = float(wins.mean()) if len(wins) > 0 else 0.0
                avg_l = abs(float(losses.mean())) if len(losses) > 0 else 1e-9
                plr = avg_w / avg_l if avg_l > 1e-9 else np.nan
                mean_pct = float(s.mean() * 100)
                base_pct = float(base.mean() * 100)
                res["horizons"][key_blk][f"T+{k}"] = {
                    "n_valid": int(len(s)),
                    "mean_pct": round(mean_pct, 2),
                    "med_pct": round(float(s.median() * 100), 2),
                    "win_rate": round(float((s > 0).mean() * 100), 1),
                    "plr": round(float(plr), 2) if np.isfinite(plr) else None,
                    "excess_vs_uncond_pct": round(mean_pct - base_pct, 2),
                    "p25_pct": round(float(s.quantile(0.25) * 100), 2),
                    "p75_pct": round(float(s.quantile(0.75) * 100), 2),
                    "min_pct": round(float(s.min() * 100), 2),
                    "max_pct": round(float(s.max() * 100), 2),
                }
            mae_col = f"{idx_pfx}_{entry}_mae20_low"
            m_s = sub[mae_col].dropna()
            if len(m_s) > 0:
                res["horizons"][key_blk]["MAE20_low_mean_pct"] = round(float(m_s.mean() * 100), 2)
                res["horizons"][key_blk]["MAE20_low_med_pct"] = round(float(m_s.median() * 100), 2)
                res["horizons"][key_blk]["MAE20_low_p10_pct"] = round(float(m_s.quantile(0.10) * 100), 2)

    sub_dc = df[dc_mask]
    for k in [5, 10, 20]:
        s_dc = sub_dc[f"c300_tail_fwd_{k}d"].dropna()
        if len(s_dc) > 0:
            res["decluster_5d_c300_tail"][f"T+{k}"] = {
                "n": int(len(s_dc)),
                "mean_pct": round(float(s_dc.mean() * 100), 2),
                "win_rate": round(float((s_dc > 0).mean() * 100), 1),
            }

    if include_dates:
        cols_keep = ["date", "c300_ret", "etf_amt_spike_20d", "etf_net_flow_yi", "fut3_spike_20d",
                     "is_delivery_day", "c300_tail_fwd_5d", "c300_tail_fwd_10d", "c300_tail_fwd_20d", "c300_tail_mae20_low"]
        res["events"] = [
            {
                "date": r["date"],
                "c300_ret_pct": round(float(r["c300_ret"] * 100), 2),
                "etf_spike": round(float(r["etf_amt_spike_20d"]), 2),
                "etf_flow_yi": round(float(r["etf_net_flow_yi"]), 1),
                "fut3_spike": round(float(r["fut3_spike_20d"]), 2) if pd.notna(r["fut3_spike_20d"]) else None,
                "is_deliv": bool(r["is_delivery_day"]),
                "fwd5_pct": round(float(r["c300_tail_fwd_5d"] * 100), 2) if pd.notna(r["c300_tail_fwd_5d"]) else None,
                "fwd10_pct": round(float(r["c300_tail_fwd_10d"] * 100), 2) if pd.notna(r["c300_tail_fwd_10d"]) else None,
                "fwd20_pct": round(float(r["c300_tail_fwd_20d"] * 100), 2) if pd.notna(r["c300_tail_fwd_20d"]) else None,
                "mae20_pct": round(float(r["c300_tail_mae20_low"] * 100), 2) if pd.notna(r["c300_tail_mae20_low"]) else None,
            }
            for _, r in sub[cols_keep].iterrows()
        ]
    return res


def simulate_strategy(
    df: pd.DataFrame,
    use_m2: bool = True,
    use_m4: bool = True,
    m5_mode: str = "orthodox_flat",
    require_pos_flow: bool = False,
    weak_only: bool = True,
    scale: float = 1.0,
    max_hold_days: int = 20,
    exec_timing: str = "tail",
    asset: str = "c300",
) -> pd.DataFrame:
    """
    PIT-strict daily state machine simulation.
    m5_mode:
      - 'orthodox_flat': exit to 0% on Giant Yang (>= +2.5%)
      - 'half_trail': cut in half on Giant Yang, trail remaining half while close >= MA20 (max 40d)
      - 'hold20': skip Giant Yang clearing; hold rescue tier for 20 trading days (reset on new rescue)
    """
    n = len(df)
    w_arr = np.zeros(n)
    pos, hold, in_r, last_r = 0.0, 0, False, -999

    wk = df["weak"].to_numpy(bool)
    pl = df["pulse"].to_numpy(bool)
    es = df["etf_amt_spike_20d"].to_numpy(float)
    fs = df["fut3_spike_20d"].fillna(0.0).to_numpy(float)
    dl = df["is_delivery_day"].to_numpy(bool)
    fl = df["etf_net_flow_yi"].fillna(0.0).to_numpy(float)
    rt = df["c300_ret"].fillna(0.0).to_numpy(float)
    cl = df["c300_close"].to_numpy(float)
    ma = df["c300_ma20"].to_numpy(float)

    for i in range(n):
        ok_reg = wk[i] if weak_only else True
        ok_fl = (fl[i] > 0.0) if require_pos_flow else True
        tier = 0.0
        if ok_reg and ok_fl:
            if use_m4 and es[i] >= 1.8 and fs[i] >= 1.5 and (not dl[i]):
                tier = min(1.0, 0.50 * scale)
            elif es[i] >= 2.0:
                tier = min(1.0, 0.30 * scale)
            elif use_m2 and pl[i] and (1.2 <= es[i] < 2.0):
                tier = min(1.0, 0.10 * scale)

        is_gy = (rt[i] >= 0.025) and (in_r or (i - last_r <= 15))
        if m5_mode == "orthodox_flat" and is_gy and pos > 0.0:
            pos, in_r, hold = 0.0, False, 0
        elif m5_mode == "half_trail" and is_gy and pos > 0.0:
            pos = pos * 0.5
            in_r = False
            hold = 0
        elif tier > 0.0:
            pos = max(pos, tier)
            in_r = True
            hold = 0
            last_r = i
        else:
            if pos > 0.0:
                hold += 1
                if m5_mode in ("hold20", "orthodox_flat") and in_r and hold >= max_hold_days:
                    pos = 0.0
                    in_r = False
                elif m5_mode == "half_trail":
                    if in_r and hold >= max_hold_days:
                        pos = 0.0
                        in_r = False
                    elif (not in_r) and ((cl[i] < ma[i] and hold >= 3) or hold >= 40):
                        pos = 0.0
        w_arr[i] = pos

    out = pd.DataFrame({
        "date": df["date"],
        "w_target_close": w_arr,
        "c300_ret": df["c300_ret"],
        "c500_ret": df["c500_ret"],
    })
    wp = out["w_target_close"].shift(1).fillna(0.0)
    wp2 = out["w_target_close"].shift(2).fillna(0.0)
    to = (wp - wp2).abs()
    ret_s = df[f"{asset}_ret"].fillna(0.0)
    ov_s = df[f"{asset}_overnight"].fillna(0.0)
    in_s = df[f"{asset}_intraday"].fillna(0.0)
    if exec_timing == "tail":
        out["strat_ret"] = wp * ret_s - COST_ONE_WAY * to
    else:
        out["strat_ret"] = (1.0 + wp2 * ov_s) * (1.0 + wp * in_s) - 1.0 - COST_ONE_WAY * to
    out["w_eff"] = wp
    out["turnover"] = to
    return out


def eval_strategy_d15(sim_df: pd.DataFrame, start_date: str, end_date: str, name: str) -> dict:
    s = sim_df[(sim_df["date"] >= start_date) & (sim_df["date"] <= end_date)].copy()
    s["dt"] = pd.to_datetime(s["date"])
    s = s.set_index("dt")

    def _pack(sub_df, label):
        if len(sub_df) < 20:
            return None
        sub_w = float(sub_df["w_eff"].mean())
        act = (sub_df["w_eff"] > 0.001).astype(float)
        m_full = compute_period_metrics(sub_df["strat_ret"], sub_df["c300_ret"], act)
        m_same = compute_period_metrics(sub_df["strat_ret"], sub_w * sub_df["c300_ret"], act)
        m_500 = compute_period_metrics(sub_df["strat_ret"], sub_df["c500_ret"], act)
        ann_to = float(sub_df["turnover"].sum()) / (len(sub_df) / 242.0)
        return {
            "window": label,
            "n_days": m_full["n_days"],
            "avg_weight_pct": round(sub_w * 100, 1),
            "ann_turnover_x": round(ann_to, 2),
            "ann_ret": m_full["ann_ret"],
            "total_ret_pct": round((m_full["total_mult"] - 1.0) * 100, 2),
            "total_mult": m_full["total_mult"],
            "mdd": m_full["mdd"],
            "sharpe": m_full["sharpe"],
            "calmar": m_full["calmar"],
            "bench300_ann": m_full["bench_ann_ret"],
            "bench300_tot_pct": round((m_full["bench_mult"] - 1.0) * 100, 2),
            "bench300_mdd": m_full["bench_mdd"],
            "excess300_ann": m_full["excess_ann"],
            "ir_300": m_full["ir"],
            "tei_vs_300": m_full["tei"],
            "same_exp_ann": m_same["bench_ann_ret"],
            "same_exp_tot_pct": round((m_same["bench_mult"] - 1.0) * 100, 2),
            "same_exp_mdd": m_same["bench_mdd"],
            "excess_same_exp_ann": m_same["excess_ann"],
            "ir_same_exp": m_same["ir"],
            "t_stat_same_exp": m_same["t_stat"],
            "q_win_same_exp": m_same["q_win_rate"],
            "tei_vs_same_exp": m_same["tei"],
            "bench500_ann": m_500["bench_ann_ret"],
            "excess500_ann": m_500["excess_ann"],
            "tei_vs_500": m_500["tei"],
        }

    top5_idx = s["strat_ret"].nlargest(5).index
    return {
        "name": name,
        "full": _pack(s, f"{start_date}~{end_date}"),
        "recent_3y": _pack(s[s["date"] >= "2023-11-20"], "近3年(2023-11~2026-11)"),
        "y2024_2026": _pack(s[s["date"] >= "2024-01-01"], "2024~2026"),
        "ex_924": _pack(s[~((s["date"] >= "2024-09-24") & (s["date"] <= "2024-10-08"))], "剔除924(09.24~10.08)"),
        "ex_top5": _pack(s.drop(top5_idx), "剔除极值前5日"),
    }


def main():
    raw = pd.read_parquet(PANEL_PATH)
    df_all = define_signals(add_forward_columns(raw))
    df10 = df_all[df_all["date"] >= "2017-01-17"].copy().reset_index(drop=True)
    df15 = df_all[df_all["date"] >= "2011-01-04"].copy().reset_index(drop=True)

    # Event Studies (10Y Core)
    ev10 = {
        "uncond_10y": summarize_event_set(df10, pd.Series(True, index=df10.index), "无条件全样本基准(10Y)"),
        "M1_weak": summarize_event_set(df10, df10["m1_weak"], "①弱势脉冲不放量(吃瓜 <1.2x)"),
        "M1_weak_strict": summarize_event_set(df10, df10["m1_weak_strict"], "①弱势收阳脉冲不放量"),
        "M1_all": summarize_event_set(df10, df10["m1_all"], "①全天候脉冲不放量"),
        "M2_weak": summarize_event_set(df10, df10["m2_weak"], "②弱势脉冲放量(底仓 1.2x~2.0x)"),
        "M2_weak_true_inflow": summarize_event_set(df10, df10["m2_weak"] & (df10["etf_net_flow_yi"] > 10.0), "②放量底仓+真净申购>10亿"),
        "M2_weak_no_inflow": summarize_event_set(df10, df10["m2_weak"] & (df10["etf_net_flow_yi"] <= 0.0), "②放量底仓+净流出<=0"),
        "M2_all": summarize_event_set(df10, df10["m2_all"], "②全天候脉冲放量"),
        "M3_weak_20": summarize_event_set(df10, df10["m3_weak_20"], "③弱势宽基爆量(>=2.0x)", include_dates=True),
        "M3_weak_20_posflow": summarize_event_set(df10, df10["m3_weak_20_posflow"], "③弱势爆量(>=2.0x)+真净申购>0"),
        "M3_weak_20_pulse": summarize_event_set(df10, df10["m3_weak_20_pulse"], "③弱势脉冲+爆量(>=2.0x)"),
        "M3_weak_25": summarize_event_set(df10, df10["m3_weak_25"], "③弱势宽基超爆(>=2.5x)"),
        "M3_weak_510300_25": summarize_event_set(df10, df10["m3_weak_510300_25"], "③弱势510300单爆(>=2.5x)"),
        "M3_all_20": summarize_event_set(df10, df10["m3_all_20"], "③全天候宽基爆量(>=2.0x)"),
        "M3_high_20": summarize_event_set(df10, df10["m3_high_20"], "③高位连涨爆量(MA20上+20日>=5%)"),
        "M4_weak_18_incl": summarize_event_set(df10, df10["m4_weak_18_all"], "④弱势期现双爆(>=1.8x&1.5x 含交割)", include_dates=True),
        "M4_weak_18_excl": summarize_event_set(df10, df10["m4_weak_18_nodeliv"], "④弱势期现双爆(>=1.8x&1.5x 剔交割)", include_dates=True),
        "M4_weak_18_nowin": summarize_event_set(df10, df10["m4_weak_18_nowin"], "④弱势期现双爆(>=1.8x&1.5x 剔移仓窗)"),
        "M4_weak_20_incl": summarize_event_set(df10, df10["m4_weak_20_all"], "④弱势期现双爆(>=2.0x&1.5x 含交割)"),
        "M4_weak_20_excl": summarize_event_set(df10, df10["m4_weak_20_nodeliv"], "④弱势期现双爆(>=2.0x&1.5x 剔交割)"),
        "M4_weak_20_nowin": summarize_event_set(df10, df10["m4_weak_20_nowin"], "④弱势期现双爆(>=2.0x&1.5x 剔移仓窗)"),
        "M4_only_etf_18": summarize_event_set(df10, df10["m3_only_18_nodeliv"], "PK: 单宽基爆量(>=1.8x 期<1.5x)"),
        "M4_only_etf_20": summarize_event_set(df10, df10["m3_only_20_nodeliv"], "PK: 单宽基爆量(>=2.0x 期<1.5x)"),
        "M4_allw_18_incl": summarize_event_set(df10, df10["m4_allw_18_all"], "④全天候期现双爆(含交割)"),
        "M4_allw_18_excl": summarize_event_set(df10, df10["m4_allw_18_nodeliv"], "④全天候期现双爆(剔交割)"),
        "M4_allw_only_etf_18": summarize_event_set(df10, df10["m3_only_allw_18_nodeliv"], "PK: 全天候单宽基(>=1.8x 期<1.5x)"),
        "M5_25": summarize_event_set(df10, df10["m5_25_after_rescue"], "⑤护盘后巨阳(>=+2.5%)", include_dates=True),
        "M5_30": summarize_event_set(df10, df10["m5_30_after_rescue"], "⑤护盘后巨阳(>=+3.0%)"),
        "M5_35": summarize_event_set(df10, df10["m5_35_after_rescue"], "⑤护盘后巨阳(>=+3.5%)"),
        "M5_25_ex924": summarize_event_set(df10, df10["m5_25_ex924"], "⑤护盘后巨阳(>=+2.5% 剔924三连阳)"),
        "M5_25_flow_ge50": summarize_event_set(df10, df10["m5_25_flow_ge50"], "⑤巨阳+大哥仍扫货(净申购>=50亿)"),
        "M5_25_flow_lt50": summarize_event_set(df10, df10["m5_25_flow_lt50"], "⑤巨阳+无续买(净申购<50亿)"),
        "M5_25_bear18": summarize_event_set(df10, df10["m5_25_bear18"], "⑤熊市反抽巨阳(2018~2019.05)"),
    }

    ev15 = {
        "M1_weak_15y": summarize_event_set(df15, df15["m1_weak"], "15Y: ①弱势吃瓜"),
        "M2_weak_15y": summarize_event_set(df15, df15["m2_weak"], "15Y: ②放量底仓"),
        "M3_weak_20_15y": summarize_event_set(df15, df15["m3_weak_20"], "15Y: ③弱势爆量>=2.0x"),
        "M3_high_20_15y": summarize_event_set(df15, df15["m3_high_20"], "15Y: ③高位爆量>=2.0x"),
        "M5_25_15y": summarize_event_set(df15, df15["m5_25_after_rescue"], "15Y: ⑤护盘后巨阳>=+2.5%"),
        "M5_30_15y": summarize_event_set(df15, df15["m5_30_after_rescue"], "15Y: ⑤护盘后巨阳>=+3.0%"),
    }

    # Portfolio Simulation Matrix
    port_specs = [
        ("S1_10Y_原教旨五句合体_尾盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=True, use_m4=True, m5_mode="orthodox_flat", exec_timing="tail")),
        ("S1b_10Y_原教旨五句合体_次日开盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=True, use_m4=True, m5_mode="orthodox_flat", exec_timing="open")),
        ("S2_10Y_改良巨阳减半留底_尾盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=True, use_m4=True, m5_mode="half_trail", exec_timing="tail")),
        ("S2b_10Y_改良巨阳减半留底_次日开盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=True, use_m4=True, m5_mode="half_trail", exec_timing="open")),
        ("S3_10Y_纯ETF五句合体_尾盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=True, use_m4=False, m5_mode="orthodox_flat", exec_timing="tail")),
        ("S4_10Y_全天候减半留底_尾盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=True, use_m4=True, m5_mode="half_trail", weak_only=False, exec_timing="tail")),
        ("S5_10Y_去伪存真_纯③爆量30%_尾盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=False, use_m4=False, m5_mode="hold20", exec_timing="tail")),
        ("S5b_10Y_去伪存真_纯③爆量30%_开盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=False, use_m4=False, m5_mode="hold20", exec_timing="open")),
        ("S6_10Y_纯③爆量+正净申购30%_开盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=False, use_m4=False, m5_mode="hold20", require_pos_flow=True, exec_timing="open")),
        ("S7_10Y_纯③爆量100%单仓_尾盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=False, use_m4=False, m5_mode="hold20", scale=10.0/3.0, exec_timing="tail")),
        ("S7b_10Y_纯③+正净申购100%单仓_开盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=False, use_m4=False, m5_mode="hold20", require_pos_flow=True, scale=10.0/3.0, exec_timing="open")),
        ("S8_10Y_纯③爆量30%买中证500_尾盘", df10, "2017-01-17", "2026-11-19", dict(use_m2=False, use_m4=False, m5_mode="hold20", exec_timing="tail", asset="c500")),
        ("S9_15Y_纯ETF原教旨_尾盘", df15, "2011-01-04", "2026-11-19", dict(use_m2=True, use_m4=False, m5_mode="orthodox_flat", exec_timing="tail")),
        ("S10_15Y_纯ETF去伪存真_纯③30%_尾盘", df15, "2011-01-04", "2026-11-19", dict(use_m2=False, use_m4=False, m5_mode="hold20", exec_timing="tail")),
        ("S11_15Y_纯ETF去伪存真+正净申购30%_开盘", df15, "2011-01-04", "2026-11-19", dict(use_m2=False, use_m4=False, m5_mode="hold20", require_pos_flow=True, exec_timing="open")),
        ("S12_15Y_纯ETF去伪存真100%单仓_尾盘", df15, "2011-01-04", "2026-11-19", dict(use_m2=False, use_m4=False, m5_mode="hold20", scale=10.0/3.0, exec_timing="tail")),
    ]

    port_results = {}
    curve_10y = df10[["date", "c300_close", "c300_ret", "c500_ret", "etf_amt_spike_20d", "etf_net_flow_yi", "fut3_spike_20d"]].copy()
    curve_15y = df15[["date", "c300_close", "c300_ret", "c500_ret"]].copy()

    for pname, d_in, sd, ed, kw in port_specs:
        sim = simulate_strategy(d_in, **kw)
        ev = eval_strategy_d15(sim, sd, ed, pname)
        port_results[pname] = ev
        if sd == "2017-01-17":
            curve_10y[f"{pname}_ret"] = sim["strat_ret"].values
            curve_10y[f"{pname}_w"] = sim["w_eff"].values
        else:
            curve_15y[f"{pname}_ret"] = sim["strat_ret"].values
            curve_15y[f"{pname}_w"] = sim["w_eff"].values

    out_json = {
        "meta": {
            "window_10y": "2017-01-17 ~ 2026-11-19",
            "window_15y": "2011-01-04 ~ 2026-11-19",
            "n_days_10y": int(len(df10)),
            "n_days_15y": int(len(df15)),
            "cost_one_way_pct": 0.15,
            "data_as_of_date": str(df10["date"].max()),
        },
        "events_10y": ev10,
        "events_15y": ev15,
        "portfolios": port_results,
    }
    with open(f"{OUT_DIR}/nt_mantra_backtest_result.json", "w", encoding="utf-8") as f:
        json.dump(out_json, f, ensure_ascii=False, indent=2)
    curve_10y.to_parquet(f"{OUT_DIR}/data_cache/sim_curves_10y.parquet", index=False)
    curve_15y.to_parquet(f"{OUT_DIR}/data_cache/sim_curves_15y.parquet", index=False)
    print("Full backtest completed cleanly. Summary:")
    for pname, ev in port_results.items():
        f = ev["full"]; r3 = ev["recent_3y"]; ex9 = ev["ex_924"]; ex5 = ev["ex_top5"]
        print(f"  {pname:32s} | w={f['avg_weight_pct']:4.1f}% | ann={f['ann_ret']:+5.2f}% (tot{f['total_ret_pct']:+5.1f}%) | MDD={f['mdd']:6.2f}% | ex300={f['excess300_ann']:+5.2f}% | exSame={f['excess_same_exp_ann']:+5.2f}% (IR={f['ir_same_exp']:+.2f}, TEI={f['tei_vs_same_exp']:4.1f}) | 3Yex={r3['excess_same_exp_ann']:+5.2f}% | ex924={ex9['excess_same_exp_ann']:+5.2f}% | exTop5={ex5['excess_same_exp_ann']:+5.2f}%")


if __name__ == "__main__":
    main()

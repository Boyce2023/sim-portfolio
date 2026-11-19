#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step1_compute_features.py — C8 现有四大主战账本严格 PIT 连续曲线轨迹特征提取器
截断点：每笔交易 buy_date 前一交易日收盘 (signal_date)，全量合并活跃+退市日线，严格前复权至 signal_date。
同时提取 D0 (启动前，剔除当前连板/首阴) 与 D_sig (signal_date) 双锚点，以及现有筹码基准因子 pos20/dd20/dd60。
"""
import os
import numpy as np
import pandas as pd

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/continuous_curve_explore_20261119/part2_existing4_curve_audit"
os.makedirs(OUT_DIR, exist_ok=True)

LEDGERS = {
    "3to4": "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_factors_v2_20261118/f1_3to4/ledger_3to4_xf30_std.csv",
    "high": "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_rebacktest_20261116/partA_high_3to4/ledger_base_high_v51.csv",
    "2to3": "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/exit_factors_v2_20261118/f2_2to3/ledger_xf30_t2_std90.csv",
    "1to2": "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117/ledger_upg_1to2.csv",
}
PQ_ACT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet"
PQ_DEL = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet"


def load_pit_prices(target_c6: set[str]) -> dict[str, pd.DataFrame]:
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "qfq_factor"]
    d1 = pd.read_parquet(PQ_ACT, columns=cols)
    d1["c6"] = d1["ticker"].astype(str).str[:6]
    d1 = d1[d1["c6"].isin(target_c6)].copy()
    d1["src"] = 0

    d2 = pd.read_parquet(PQ_DEL, columns=cols)
    d2["c6"] = d2["ticker"].astype(str).str[:6]
    d2 = d2[d2["c6"].isin(target_c6)].copy()
    d2["src"] = 1

    px = pd.concat([d1, d2], ignore_index=True)
    px = px[px["c6"].str.startswith(("00", "60")) & (~px["ticker"].astype(str).str.endswith(".BJ"))].copy()
    px["dt"] = px["date"].dt.strftime("%Y-%m-%d")
    px.sort_values(["c6", "dt", "src"], inplace=True)
    px.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    return {c6: g.reset_index(drop=True) for c6, g in px.groupby("c6")}


def calc_curve_features_at(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray, v: np.ndarray, t: int, prefix: str) -> dict:
    """Strictly uses bars <= t (no lookahead beyond t)."""
    ret = np.empty(len(c), dtype=float)
    ret[0] = np.nan
    ret[1:] = c[1:] / c[:-1] - 1.0

    # F1: 10d Efficiency Ratio (unsigned and signed)
    dc = np.abs(np.diff(c[t - 10 : t + 1]))
    denom_er = float(np.sum(dc))
    f1_er10 = float(abs(c[t] - c[t - 10]) / denom_er) if denom_er > 1e-12 else 0.0
    f1_er10_signed = float((c[t] - c[t - 10]) / denom_er) if denom_er > 1e-12 else 0.0

    # F2: VCP volatility contraction ratio std(ret, 5d) / std(ret, 20d)
    s5 = float(np.std(ret[t - 4 : t + 1], ddof=1))
    s20 = float(np.std(ret[t - 19 : t + 1], ddof=1))
    f2_vcp = s5 / s20 if s20 > 1e-12 else 1.0

    # F3: MA alignment (MA5 > MA10 > MA20 > MA60 score 0~3) & MA20 5d slope
    ma5_series = pd.Series(c).rolling(5).mean().to_numpy()
    ma10_series = pd.Series(c).rolling(10).mean().to_numpy()
    ma20_series = pd.Series(c).rolling(20).mean().to_numpy()
    ma60_series = pd.Series(c).rolling(60).mean().to_numpy()
    ma5_t, ma10_t, ma20_t, ma60_t = ma5_series[t], ma10_series[t], ma20_series[t], ma60_series[t]
    f3_score = int(ma5_t > ma10_t) + int(ma10_t > ma20_t) + int(ma20_t > ma60_t)
    f3_slope = float(ma20_t / ma20_series[t - 5] - 1.0) if ma20_series[t - 5] > 0 else 0.0

    # F4: Volume build-up (recent 10d / prior 20~60d, and recent 15d / prior 15~60d)
    v_base = float(np.nanmean(v[t - 59 : t - 19]))
    v_10 = float(np.nanmean(v[t - 9 : t + 1]))
    f4_vol_10_40 = v_10 / v_base if v_base > 1e-12 else 1.0
    v_base15 = float(np.nanmean(v[t - 59 : t - 14]))
    v_15 = float(np.nanmean(v[t - 14 : t + 1]))
    f4_vol_15_45 = v_15 / v_base15 if v_base15 > 1e-12 else 1.0

    # F5: N-wave memory in [t-45 .. t]: >=25% rally before >=10% contracting-vol pullback
    n_wave = 0
    max_runup = 0.0
    lo_idx = max(0, t - 45)
    for p in range(t - 35, t - 2):
        if p <= lo_idx:
            continue
        runup = float(np.max(h[lo_idx : p + 1]) / np.min(l[lo_idx:p]) - 1.0) if p > lo_idx else 0.0
        # Best sequential trough->peak inside [lo_idx..p]
        sub_l = l[lo_idx : p + 1]
        sub_c = c[lo_idx : p + 1]
        sub_h = h[lo_idx : p + 1]
        cum_min = np.minimum.accumulate(sub_l)
        seq_gain = float(np.max(sub_h / cum_min - 1.0))
        if seq_gain > max_runup:
            max_runup = seq_gain
        if seq_gain >= 0.25:
            # Peak bar k where seq_gain achieved or max(h) in [lo_idx..p]
            pk_rel = int(np.argmax(sub_h))
            pk_abs = lo_idx + pk_rel
            if pk_abs <= t - 2:
                pb_min = float(np.min(l[pk_abs + 1 : t + 1]))
                pb_dd = pb_min / float(h[pk_abs]) - 1.0
                if pb_dd <= -0.10:
                    # Volume contraction check: pullback avg vol < rally/peak avg vol
                    rally_start = max(lo_idx, pk_abs - 9)
                    v_rally = float(np.nanmean(v[rally_start : pk_abs + 1]))
                    v_pb = float(np.nanmean(v[pk_abs + 1 : t + 1]))
                    if v_rally > 0 and v_pb < v_rally:
                        n_wave = 1
                        break

    # F6: Days in last 10 bars where close >= MA5
    f6_hug = int(np.sum(c[t - 9 : t + 1] >= ma5_series[t - 9 : t + 1]))

    # F7: Yang candle ratio in last 10 bars (close > open)
    f7_yang = float(np.mean(c[t - 9 : t + 1] > o[t - 9 : t + 1]))

    # F8: Close / 120d High
    hi120 = float(np.max(h[max(0, t - 119) : t + 1]))
    f8_hi120 = float(c[t] / hi120) if hi120 > 0 else 1.0

    # Baseline chip/position factors at anchor t (pos20, dd20, dd60)
    min20 = float(np.min(l[t - 19 : t + 1]))
    max20 = float(np.max(h[t - 19 : t + 1]))
    max60 = float(np.max(h[t - 59 : t + 1]))
    pos20 = float((c[t] - min20) / (max20 - min20 + 1e-8))
    dd20 = float(c[t] / (max20 + 1e-8))
    dd60 = float(c[t] / (max60 + 1e-8))

    return {
        f"{prefix}F1_ER10": round(f1_er10, 6),
        f"{prefix}F1_ER10_SIGNED": round(f1_er10_signed, 6),
        f"{prefix}F2_VCP": round(f2_vcp, 6),
        f"{prefix}F3_MA_SCORE": f3_score,
        f"{prefix}F3_MA20_SLOPE": round(f3_slope, 6),
        f"{prefix}F4_VOL_BUILD": round(f4_vol_10_40, 6),
        f"{prefix}F4_VOL_BUILD15": round(f4_vol_15_45, 6),
        f"{prefix}F5_N_WAVE": n_wave,
        f"{prefix}F5_RUNUP45": round(max_runup, 6),
        f"{prefix}F6_MA5_HUG": f6_hug,
        f"{prefix}F7_YANG_RATIO": round(f7_yang, 6),
        f"{prefix}F8_DIST_HI120": round(f8_hi120, 6),
        f"{prefix}pos20": round(pos20, 6),
        f"{prefix}dd20": round(dd20, 6),
        f"{prefix}dd60": round(dd60, 6),
    }


def main():
    dfs = {}
    all_c6 = set()
    for k, p in LEDGERS.items():
        df = pd.read_csv(p)
        df["c6"] = df["code"].astype(str).str.zfill(6)
        df["buy_date"] = df["buy_date"].astype(str).str[:10]
        df["exit_date"] = df["exit_date"].astype(str).str[:10]
        dfs[k] = df
        all_c6.update(df["c6"].tolist())

    by_c6 = load_pit_prices(all_c6)
    out_rows = []

    for strat, df in dfs.items():
        for row in df.itertuples(index=False):
            g = by_c6[row.c6]
            buy_matches = g.index[g["dt"] == row.buy_date].tolist()
            assert len(buy_matches) == 1, f"Missing/dup buy_date {row.c6} {row.buy_date}"
            buy_idx = buy_matches[0]
            sig_idx = buy_idx - 1
            assert sig_idx >= 130, f"Insufficient history {row.c6} {row.buy_date}: {sig_idx}"

            # Strictly truncate to <= sig_idx (zero future leak!)
            sub = g.iloc[: sig_idx + 1].copy()
            qfq_sig = float(sub["qfq_factor"].iloc[sig_idx])
            scale = qfq_sig / sub["qfq_factor"].to_numpy(dtype=float)
            o = sub["open"].to_numpy(dtype=float) * scale
            h = sub["high"].to_numpy(dtype=float) * scale
            l = sub["low"].to_numpy(dtype=float) * scale
            c = sub["close"].to_numpy(dtype=float) * scale
            # Use turnover rate if valid in lookback, else amount (split-invariant)
            turn = sub["turn"].to_numpy(dtype=float)
            amt = sub["amount"].to_numpy(dtype=float)
            v = turn if not np.isnan(turn[max(0, sig_idx - 75) :]).any() else amt

            # Determine D0 (pre-launch anchor before board streak)
            if strat == "1to2":
                d0_idx = sig_idx - 1
            elif strat == "2to3":
                d0_idx = sig_idx - 2
            elif strat == "3to4":
                d0_idx = sig_idx - 3
            else:  # high: sig_idx is first yin day; strip consecutive >=9.5% boards ending at sig_idx-1
                pct = np.empty_like(c)
                pct[0] = np.nan
                pct[1:] = c[1:] / c[:-1] - 1.0
                st = 0
                for j in range(sig_idx - 1, 0, -1):
                    if pct[j] >= 0.095:
                        st += 1
                    else:
                        break
                d0_idx = sig_idx - 1 - st

            rec = {
                "strategy": strat,
                "c6": row.c6,
                "name": row.name,
                "buy_date": row.buy_date,
                "signal_date": str(sub["dt"].iloc[sig_idx]),
                "d0_date": str(sub["dt"].iloc[d0_idx]),
                "exit_date": row.exit_date,
                "buy_hhmm": int(row.buy_hhmm),
                "exit_hhmm": int(row.exit_hhmm),
                "net_ret": float(row.net_ret),
                "score": float(row.score),
                "is_oos": int(row.buy_date >= "2024-01-01"),
            }
            rec.update(calc_curve_features_at(o, h, l, c, v, d0_idx, prefix=""))
            rec.update(calc_curve_features_at(o, h, l, c, v, sig_idx, prefix="sig_"))
            out_rows.append(rec)

    out_df = pd.DataFrame(out_rows)
    out_csv = os.path.join(OUT_DIR, "all_trades_curve_features_pit.csv")
    out_df.to_csv(out_csv, index=False)
    print(f"Saved {len(out_df)} trades with {len(out_df.columns)} cols to {out_csv}")
    print("Strategy counts:", out_df["strategy"].value_counts().to_dict())
    print("Any NaN in feature cols:", int(out_df.isna().sum().sum()))


if __name__ == "__main__":
    main()

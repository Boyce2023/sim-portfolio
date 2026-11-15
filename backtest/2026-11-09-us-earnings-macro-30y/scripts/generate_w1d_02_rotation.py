#!/usr/bin/env python3
"""
generate_w1d_02_rotation.py
Builds w1d_02_sector_etf_rotation_and_macro_shield_30y.csv
Tests 1998-2026 official SPDR Sector ETF rotation strategies with Macro Credit & MA200 Shields.
Quantifies crisis drawdown suppression (2000-2002 and 2008 GFC) and multi-horizon rolling holding performance.
"""

import os
import numpy as np
import pandas as pd

OUTPUT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/us_quant_value_scorecard_30y_20261115/lab_w1d_survivorship_clean_30y"
SECTORS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/sectors"
BENCHMARKS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/benchmarks"
MACRO_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/data/macro_pit_daily_1990_2026.parquet"

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 1. Load Sector ETFs (9 core SPDR ETFs)
sectors = ["XLK", "XLV", "XLF", "XLI", "XLY", "XLP", "XLE", "XLU", "XLB"]
df_list = []
for s in sectors:
    p = os.path.join(SECTORS_DIR, f"{s}.parquet")
    df = pd.read_parquet(p)
    if isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
    if "date" not in df.columns and "index" in df.columns:
        df.rename(columns={"index": "date"}, inplace=True)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    sub = df[["date", "adj_close"]].rename(columns={"adj_close": s})
    df_list.append(sub.set_index("date"))

prices = pd.concat(df_list, axis=1).sort_index()

# 2. Load SPY Benchmark
spy_df = pd.read_parquet(os.path.join(BENCHMARKS_DIR, "SPY.parquet"))
if isinstance(spy_df.index, pd.DatetimeIndex):
    spy_df = spy_df.reset_index()
if "date" not in spy_df.columns and "index" in spy_df.columns:
    spy_df.rename(columns={"index": "date"}, inplace=True)
spy_df["date"] = pd.to_datetime(spy_df["date"]).dt.tz_localize(None).dt.normalize()
spy = spy_df[["date", "adj_close"]].rename(columns={"adj_close": "SPY"}).sort_values("date").drop_duplicates("date").set_index("date")

# 3. Load Macro Conditioning
macro = pd.read_parquet(MACRO_PATH, columns=["date", "sp500_above_ma200", "baa10y", "credit_regime", "era_regime"]).sort_values("date")
macro["date"] = pd.to_datetime(macro["date"]).dt.tz_localize(None).dt.normalize()
macro = macro.drop_duplicates("date").set_index("date")

# Combine
data = pd.concat([prices, spy, macro], axis=1, join="inner").sort_index()
dates = data.index

# Identify monthly rebalance dates (last trading day of month)
data["ym"] = data.index.to_period("M")
rebal_dates = set(data.groupby("ym").apply(lambda x: x.index[-1], include_groups=False).values)

returns_daily = prices.pct_change().fillna(0.0)
spy_daily = data["SPY"].pct_change().fillna(0.0)

cash_daily_ret = 0.02 / 252.0 # 2.0% risk free cash yield

# Crises windows
CRISES = {
    "mdd_2000_dotcom": ("2000-03-24", "2002-10-09"),
    "mdd_2008_gfc": ("2007-10-09", "2009-03-09"),
    "mdd_2020_covid": ("2020-02-19", "2020-03-23"),
    "mdd_2022_hike": ("2022-01-03", "2022-10-12"),
}

def calc_sub_mdd(cum_series, start_d, end_d):
    sub = cum_series.loc[start_d:end_d]
    if len(sub) < 5:
        return np.nan
    dd = (sub - sub.cummax()) / sub.cummax()
    return float(dd.min())

# Run Strategy Simulation Function
def simulate_strategy(strat_type):
    port_rets = []
    current_weights = {s: 1.0 / len(sectors) for s in sectors}
    current_weights["CASH"] = 0.0

    for i, d in enumerate(dates):
        if i == 0:
            port_rets.append(0.0)
            continue

        if d in rebal_dates and i >= 126:
            # 6-month trailing momentum (126 trading days)
            moms = (data[sectors].iloc[i] / data[sectors].iloc[i-126]) - 1.0
            top3 = moms.nlargest(3).index.tolist()
            top2 = moms.nlargest(2).index.tolist()

            ma200 = bool(data["sp500_above_ma200"].iloc[i])
            cred = str(data["credit_regime"].iloc[i])
            baa = float(data["baa10y"].iloc[i])

            if strat_type == "Benchmark_SPY":
                current_weights = {s: 0.0 for s in sectors}
                current_weights["CASH"] = 0.0
            elif strat_type == "Sector_EW_BuyHold":
                current_weights = {s: 1.0 / len(sectors) for s in sectors}
                current_weights["CASH"] = 0.0
            elif strat_type == "Sector_Mom_Top3_NoShield":
                current_weights = {s: (1.0 / 3.0 if s in top3 else 0.0) for s in sectors}
                current_weights["CASH"] = 0.0
            elif strat_type == "Sector_Mom_Top2_NoShield":
                current_weights = {s: (1.0 / 2.0 if s in top2 else 0.0) for s in sectors}
                current_weights["CASH"] = 0.0
            elif strat_type == "Sector_Mom_Top3_MA200_Shield":
                if not ma200:
                    current_weights = {s: 0.0 for s in sectors}
                    current_weights["CASH"] = 1.0
                else:
                    current_weights = {s: (1.0 / 3.0 if s in top3 else 0.0) for s in sectors}
                    current_weights["CASH"] = 0.0
            elif strat_type == "Sector_Mom_Top3_Credit_Shield":
                # Static BAA > 2.8% or Credit Crisis
                if cred == "Credit_Crisis" or baa >= 2.8:
                    # Shift to defensive basket: XLU, XLP, XLV
                    current_weights = {s: (1.0 / 3.0 if s in ["XLU", "XLP", "XLV"] else 0.0) for s in sectors}
                    current_weights["CASH"] = 0.0
                else:
                    current_weights = {s: (1.0 / 3.0 if s in top3 else 0.0) for s in sectors}
                    current_weights["CASH"] = 0.0
            elif strat_type == "Sector_Mom_Top3_Dual_Shield_Optimal":
                # Dual Shield: MA200 Trend + Credit Spread Strain
                if (not ma200) and (cred == "Credit_Crisis" or baa >= 3.0):
                    # Severe crisis: 100% Cash preservation
                    current_weights = {s: 0.0 for s in sectors}
                    current_weights["CASH"] = 1.0
                elif (not ma200) or (cred in ["Tightening_Stress", "Credit_Crisis"]):
                    # Stress regime: 50% Defensive sectors (XLU, XLP, XLV) + 50% Cash
                    current_weights = {s: (0.5 / 3.0 if s in ["XLU", "XLP", "XLV"] else 0.0) for s in sectors}
                    current_weights["CASH"] = 0.5
                else:
                    # Healthy bull regime: 100% Top 3 Momentum
                    current_weights = {s: (1.0 / 3.0 if s in top3 else 0.0) for s in sectors}
                    current_weights["CASH"] = 0.0

        if strat_type == "Benchmark_SPY":
            day_ret = float(spy_daily.loc[d])
        else:
            day_ret = sum(current_weights.get(s, 0.0) * float(returns_daily.loc[d, s]) for s in sectors) + current_weights.get("CASH", 0.0) * cash_daily_ret

        port_rets.append(day_ret)

    ret_series = pd.Series(port_rets, index=dates)
    cum_series = (1.0 + ret_series).cumprod()
    return ret_series, cum_series

strategies = [
    ("Benchmark_SPY", "SPDR S&P 500 ETF (Buy & Hold Benchmark)"),
    ("Sector_EW_BuyHold", "9 Major Sector SPDR ETFs Equal-Weight (Buy & Hold)"),
    ("Sector_Mom_Top3_NoShield", "Top 3 Sector Momentum (6M Trailing Return, Monthly Rebalance, No Shield)"),
    ("Sector_Mom_Top2_NoShield", "Top 2 Sector Momentum (6M Trailing Return, Monthly Rebalance, No Shield)"),
    ("Sector_Mom_Top3_MA200_Shield", "Top 3 Sector Momentum + MA200 Shield (SP500<MA200 -> 100% Cash)"),
    ("Sector_Mom_Top3_Credit_Shield", "Top 3 Sector Momentum + Credit Shield (BAA>2.8%/Crisis -> Defensive XLU/XLP/XLV)"),
    ("Sector_Mom_Top3_Dual_Shield_Optimal", "Top 3 Sector Momentum + Dual Shield (MA200 + Credit Stress -> 50% Def/50% Cash; Crisis -> 100% Cash)"),
]

# Run simulations
sim_results = {}
for code, desc in strategies:
    r_ser, c_ser = simulate_strategy(code)
    sim_results[code] = (r_ser, c_ser, desc)

spy_ret_ser, spy_cum_ser, _ = sim_results["Benchmark_SPY"]
spy_cagr = float(spy_cum_ser.iloc[-1] ** (252.0 / len(dates)) - 1.0)

rows = []
n_total_days = len(dates)
years_total = n_total_days / 252.0

for code, desc in strategies:
    r_ser, c_ser, _ = sim_results[code]

    # Full period metrics
    tot_ret = float(c_ser.iloc[-1] - 1.0)
    cagr = float(c_ser.iloc[-1] ** (252.0 / n_total_days) - 1.0)
    vol = float(r_ser.std() * np.sqrt(252.0))
    sharpe = float((cagr - 0.02) / vol) if vol > 0 else np.nan
    dd_ser = (c_ser - c_ser.cummax()) / c_ser.cummax()
    max_dd = float(dd_ser.min())
    calmar = float(cagr / abs(max_dd)) if abs(max_dd) > 0 else np.nan
    excess_cagr = float(cagr - spy_cagr)

    # Crisis drawdowns
    mdd_dotcom = calc_sub_mdd(c_ser, CRISES["mdd_2000_dotcom"][0], CRISES["mdd_2000_dotcom"][1])
    mdd_gfc = calc_sub_mdd(c_ser, CRISES["mdd_2008_gfc"][0], CRISES["mdd_2008_gfc"][1])
    mdd_covid = calc_sub_mdd(c_ser, CRISES["mdd_2020_covid"][0], CRISES["mdd_2020_covid"][1])
    mdd_hike = calc_sub_mdd(c_ser, CRISES["mdd_2022_hike"][0], CRISES["mdd_2022_hike"][1])

    # Rolling holding horizons (1Y=252d, 2Y=504d, 3Y=756d)
    # Rolling 1Y
    roll_1y = (c_ser / c_ser.shift(252) - 1.0).dropna()
    spy_roll_1y = (spy_cum_ser / spy_cum_ser.shift(252) - 1.0).dropna()
    common_1y = roll_1y.index.intersection(spy_roll_1y.index)
    win_1y = float((roll_1y.loc[common_1y] > spy_roll_1y.loc[common_1y]).mean())
    med_ret_1y = float(roll_1y.median())
    worst_1y = float(roll_1y.min())
    prob_loss_gt20_1y = float((roll_1y < -0.20).mean())

    # Rolling 2Y
    roll_2y = ((c_ser / c_ser.shift(504)) ** 0.5 - 1.0).dropna()
    spy_roll_2y = ((spy_cum_ser / spy_cum_ser.shift(504)) ** 0.5 - 1.0).dropna()
    common_2y = roll_2y.index.intersection(spy_roll_2y.index)
    win_2y = float((roll_2y.loc[common_2y] > spy_roll_2y.loc[common_2y]).mean())
    med_ret_2y = float(roll_2y.median())
    worst_2y = float(roll_2y.min())

    # Rolling 3Y
    roll_3y = ((c_ser / c_ser.shift(756)) ** (1.0 / 3.0) - 1.0).dropna()
    spy_roll_3y = ((spy_cum_ser / spy_cum_ser.shift(756)) ** (1.0 / 3.0) - 1.0).dropna()
    common_3y = roll_3y.index.intersection(spy_roll_3y.index)
    win_3y = float((roll_3y.loc[common_3y] > spy_roll_3y.loc[common_3y]).mean())
    med_ret_3y = float(roll_3y.median())
    worst_3y = float(roll_3y.min())

    rows.append({
        "strategy_code": code,
        "strategy_description": desc,
        "start_date": dates[0].strftime("%Y-%m-%d"),
        "end_date": dates[-1].strftime("%Y-%m-%d"),
        "trading_days": n_total_days,
        "years": round(years_total, 2),
        "total_return_pct": round(tot_ret * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "excess_vs_spy_cagr_pct": round(excess_cagr * 100.0, 2),
        "volatility_ann_pct": round(vol * 100.0, 2),
        "sharpe_rf2pct": round(sharpe, 2),
        "max_drawdown_28y_pct": round(max_dd * 100.0, 2),
        "calmar_ratio": round(calmar, 2),
        "mdd_2000_dotcom_pct": round(mdd_dotcom * 100.0, 2),
        "mdd_2008_gfc_pct": round(mdd_gfc * 100.0, 2),
        "mdd_2020_covid_pct": round(mdd_covid * 100.0, 2),
        "mdd_2022_hike_pct": round(mdd_hike * 100.0, 2),
        "win_rate_vs_spy_1y_pct": round(win_1y * 100.0, 1),
        "median_1y_return_pct": round(med_ret_1y * 100.0, 1),
        "worst_1y_return_pct": round(worst_1y * 100.0, 1),
        "prob_1y_loss_gt20pct": round(prob_loss_gt20_1y * 100.0, 2),
        "win_rate_vs_spy_2y_pct": round(win_2y * 100.0, 1),
        "median_2y_cagr_pct": round(med_ret_2y * 100.0, 1),
        "worst_2y_cagr_pct": round(worst_2y * 100.0, 1),
        "win_rate_vs_spy_3y_pct": round(win_3y * 100.0, 1),
        "median_3y_cagr_pct": round(med_ret_3y * 100.0, 1),
        "worst_3y_cagr_pct": round(worst_3y * 100.0, 1),
        "crisis_drawdown_under_20pct_verified": (mdd_dotcom > -0.20) and (mdd_gfc > -0.20),
    })

res_df = pd.DataFrame(rows)
out_csv = os.path.join(OUTPUT_DIR, "w1d_02_sector_etf_rotation_and_macro_shield_30y.csv")
res_df.to_csv(out_csv, index=False)
print(f"Successfully generated {out_csv} with {len(res_df)} strategy configurations.")

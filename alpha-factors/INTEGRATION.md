# Backtest Integration Guide

## Overview

This document describes how to connect the Alpha Factor Library (`factors.py` + `ic_tracker.py`) to a standard backtesting loop. The library is framework-agnostic: it works with Zipline, Backtrader, bt, or a custom vectorized loop. The examples below use a vectorized pandas approach, which is the fastest for pure research and IC analysis.

---

## Architecture Diagram

```
Market Data (price, fundamentals)
         |
         v
  FactorEngine.run()          <-- factors.py
         |
         v
  FactorResult per factor
  (values / rank / z_score)
         |
    +---------+----------+
    |                    |
    v                    v
  Portfolio            ICTracker.record_ic()   <-- ic_tracker.py
  Construction         (runs after forward
  (quintile sort,       returns realized)
   composite score)         |
    |                       v
    v                  FactorStats
  Returns                   |
  (forward realized)        v
    |               generate_report()
    +----> ICTracker.record_ic()   (feedback loop)
```

---

## Step-by-Step Integration

### 1. Data preparation

```python
import pandas as pd
from pathlib import Path

# price_data: DatetimeIndex x tickers, daily close prices (adjusted)
# fundamental_data: MultiIndex (metric, date) x tickers, or wide with metric rows
price_data = pd.read_parquet("data/prices.parquet")
fundamental_data = pd.read_parquet("data/fundamentals.parquet")

# sector_map: dict {ticker -> GICS sector}
sector_map = pd.read_csv("data/sector_map.csv", index_col=0)["sector"].to_dict()
```

### 2. Define rebalance dates

```python
# Monthly rebalance on the last trading day of each month
rebalance_dates = price_data.resample("ME").last().index
```

### 3. Factor computation loop

```python
from datetime import datetime
from factors import FactorEngine, FactorResult
from ic_tracker import ICTracker

factor_ids = [
    "MOM_1M", "MOM_3M", "MOM_6M", "MOM_12M", "MOM_52W_HIGH",
    "VAL_TRAILING_PE", "VAL_FCF_YIELD",
    "QUAL_ROE", "QUAL_ACCRUALS",
    "RISK_RVOL_60D",
    "GROWTH_REV_YOY",
]

engine = FactorEngine(factor_ids)
tracker = ICTracker(storage_path="./ic_store/")
tracker.load()

# Store results keyed by date for later IC computation
factor_results_by_date: dict[pd.Timestamp, dict[str, FactorResult]] = {}

for date in rebalance_dates:
    # Slice price data up to (and including) rebalance date
    price_slice = price_data.loc[:date]
    # Slice fundamentals to latest available as of date (point-in-time)
    fund_slice = fundamental_data.loc[fundamental_data.index.get_level_values("date") <= date]

    results = engine.run(
        as_of_date=date.to_pydatetime(),
        price_data=price_slice,
        fundamental_data=fund_slice,
        sector_map=sector_map,
        sector_neutral=True,       # neutralize sector bets
    )
    factor_results_by_date[date] = results

print(f"Computed factors for {len(factor_results_by_date)} dates")
```

### 4. Portfolio construction (quintile sort)

```python
portfolios_by_date = {}

for date, results in factor_results_by_date.items():
    factor_df = FactorEngine.to_dataframe(results, use="z_score")

    # Equal-weight composite score
    composite = FactorEngine.composite_score(factor_df)

    # Quintile 5 = top 20% (long), Quintile 1 = bottom 20% (short)
    n = len(composite)
    quintiles = pd.qcut(composite.rank(method="first"), q=5, labels=[1, 2, 3, 4, 5])

    portfolios_by_date[date] = quintiles

# Long-short portfolio: Q5 long / Q1 short (equal weight within each leg)
```

### 5. IC computation (after forward returns are realized)

```python
# Shift factor values by one period to align with forward returns
dates_list = sorted(factor_results_by_date.keys())

for i, date in enumerate(dates_list[:-1]):
    next_date = dates_list[i + 1]

    # Forward returns: close-to-close from date to next_date
    forward_ret = (
        price_data.loc[next_date] / price_data.loc[date] - 1
    )

    for factor_id, result in factor_results_by_date[date].items():
        factor_series = result.to_zscore_series()

        tracker.record_ic(
            factor_id=factor_id,
            category=result.category,
            as_of_date=date.to_pydatetime(),
            factor_values=factor_series,
            forward_returns=forward_ret,
            holding_period_days=21,
            horizon_label="1m",
        )

        # Turnover
        if i > 0:
            prev_date = dates_list[i - 1]
            prev_result = factor_results_by_date[prev_date].get(factor_id)
            if prev_result:
                tracker.record_turnover(
                    factor_id=factor_id,
                    prev_ranks=prev_result.to_rank_series(),
                    curr_ranks=result.to_rank_series(),
                    as_of_date=date.to_pydatetime(),
                )

# Update statuses and save
tracker.update_all_statuses()
tracker.save()
```

### 6. IC decay analysis (multiple holding periods)

```python
# For decay, repeat IC computation with different forward return windows
holding_periods = {
    "1m": 21,
    "2m": 42,
    "3m": 63,
    "6m": 126,
    "12m": 252,
}

for horizon_label, n_days in holding_periods.items():
    for i, date in enumerate(dates_list):
        # Find the date approximately n_days forward
        future_idx = price_data.index.searchsorted(date + pd.Timedelta(days=n_days))
        if future_idx >= len(price_data.index):
            continue
        future_date = price_data.index[future_idx]

        forward_ret = price_data.loc[future_date] / price_data.loc[date] - 1

        for factor_id, result in factor_results_by_date[date].items():
            tracker.record_ic(
                factor_id=factor_id,
                category=result.category,
                as_of_date=date.to_pydatetime(),
                factor_values=result.to_zscore_series(),
                forward_returns=forward_ret,
                holding_period_days=n_days,
                horizon_label=horizon_label,
            )

# View decay table for a specific factor
decay_table = tracker.compute_decay_table("MOM_6M")
print(decay_table)
```

---

## Integration with Zipline (Quantopian-style)

```python
from zipline.api import (
    schedule_function, date_rules, time_rules,
    order_target_percent, get_datetime
)
from factors import FactorEngine, FactorResult
from ic_tracker import ICTracker

engine = FactorEngine(["MOM_1M", "VAL_TRAILING_PE", "QUAL_ROE"])
tracker = ICTracker("./ic_store/")

def initialize(context):
    tracker.load()
    context.factor_history = {}
    schedule_function(
        rebalance,
        date_rules.month_end(),
        time_rules.market_open(minutes=30),
    )

def rebalance(context, data):
    as_of_date = get_datetime()
    price_data = data.history(context.asset_finder.retrieve_all(), "price", 300, "1d")

    results = engine.run(
        as_of_date=as_of_date,
        price_data=price_data,
    )
    factor_df = FactorEngine.to_dataframe(results, use="z_score")
    composite = FactorEngine.composite_score(factor_df)

    # Long top quintile, short bottom quintile
    n = len(composite)
    long_cutoff = composite.quantile(0.80)
    short_cutoff = composite.quantile(0.20)

    for asset in context.portfolio.positions:
        if composite.get(asset.symbol, 0) < short_cutoff:
            order_target_percent(asset, -1.0 / n)
        elif composite.get(asset.symbol, 0) > long_cutoff:
            order_target_percent(asset, 1.0 / n)
        else:
            order_target_percent(asset, 0)

    context.factor_history[as_of_date] = results
```

---

## Factor Status Integration

```python
# Before running production models, filter to alive factors only
report = tracker.generate_report()
alive = tracker.alive_factors()
dead = tracker.dead_factors()
reversed_f = tracker.reversed_factors()

print(f"Alive: {alive}")
print(f"Dead (excluded): {dead}")
print(f"Reversed (excluded or flipped): {reversed_f}")

# Use only alive factors in composite
engine_active = FactorEngine(alive)
```

---

## Correlation Check (before combining factors)

High IC correlation between factors = redundant; low correlation = diversification value.

```python
corr_matrix = tracker.factor_correlation_matrix()
print(corr_matrix.round(2))

# Rule of thumb: if two factors have IC correlation > 0.7, use only the one with higher IC IR
# Typical category-level correlations:
#   Momentum factors: 0.5-0.8 intra-category
#   Value factors: 0.3-0.6 intra-category
#   Quality vs Value: often negative (-0.1 to -0.3)
#   Momentum vs Volatility: moderately negative (-0.2 to -0.4)
```

---

## Key Implementation Notes

### Point-in-time (PIT) correctness
Always slice data `<= rebalance_date`. Never use fundamentals published after the rebalance date. Use fiscal period end date + reporting lag (typically 45-75 days for US equities) to determine true availability date.

### Sector neutralization
Strongly recommended for value and quality factors. Momentum factors are often left unneutralized to preserve cross-sector information.

### Universe definition
- Remove penny stocks (price < $5), illiquid stocks (ADV < $1M), very small caps (mktcap < $300M)
- Apply universe filter consistently before factor computation
- Survivorship bias: always use a point-in-time universe that includes delisted stocks

### Transaction cost modeling
Factor turnover directly determines trading costs. Target turnover:
- Momentum: 40-60% monthly (acceptable, higher alpha)
- Value: 10-20% monthly (low turnover, long holding)
- Quality: 5-10% monthly (very stable ranks)

At 10bps one-way cost, monthly turnover of 50% = ~120bps/year in costs. Verify net-of-cost IC before live deployment.

### Minimum data requirements
- Momentum factors: 252 trading days of price history
- Fundamental factors: 8+ quarters
- IC computation: minimum 30 observations for reliable IR estimate
- Status classification: 36-month window recommended (minimum 18)

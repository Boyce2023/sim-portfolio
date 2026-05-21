"""
Alpha Factor Library - Core computation framework.

Architecture:
    BaseFactor (abstract base) -> concrete factor classes
    FactorResult: standardized output container
    FactorEngine: orchestrates computation, cross-sectional ranking, and persistence

Design principles:
    - All factors return cross-sectional z-scores by default (sector-neutral optional)
    - Missing data handled explicitly (not silently filled)
    - Vectorized operations via pandas/numpy throughout
    - Each factor owns its data requirements (no god-object fetcher)
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output container
# ---------------------------------------------------------------------------

@dataclass
class FactorResult:
    """Standardized output for a single factor computation on a single date."""

    name: str
    category: str                          # momentum / value / quality / volatility / growth / sentiment
    as_of_date: datetime

    # Cross-sectional data (index = ticker)
    values: Dict[str, float]               # raw factor value per ticker
    rank: Dict[str, int]                   # cross-sectional rank (1 = best / highest signal)
    z_score: Dict[str, float]              # standardized cross-sectional z-score

    # IC history (populated by ICTracker, not by the factor itself)
    ic_history: List[float] = field(default_factory=list)
    current_ic: Optional[float] = None    # IC vs next-period returns (set after realization)
    ic_ir: Optional[float] = None         # mean(IC) / std(IC) over trailing window

    status: str = "alive"                  # alive / reversed / dead
    last_computed: datetime = field(default_factory=datetime.utcnow)

    # Diagnostics
    coverage: int = 0                      # number of tickers with non-null values
    universe_size: int = 0                 # total tickers in input universe

    def to_series(self) -> pd.Series:
        """Return raw values as a pd.Series for downstream use."""
        return pd.Series(self.values)

    def to_rank_series(self) -> pd.Series:
        return pd.Series(self.rank)

    def to_zscore_series(self) -> pd.Series:
        return pd.Series(self.z_score)

    def summary(self) -> str:
        lines = [
            f"Factor   : {self.name}  [{self.category}]",
            f"Date     : {self.as_of_date.date()}",
            f"Coverage : {self.coverage}/{self.universe_size}",
            f"IC (cur) : {self.current_ic:.4f}" if self.current_ic is not None else "IC (cur) : n/a",
            f"IC IR    : {self.ic_ir:.4f}" if self.ic_ir is not None else "IC IR    : n/a",
            f"Status   : {self.status}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _winsorize(s: pd.Series, lower: float = 0.01, upper: float = 0.99) -> pd.Series:
    """Winsorize at given quantile bounds."""
    lo = s.quantile(lower)
    hi = s.quantile(upper)
    return s.clip(lo, hi)


def _cross_sectional_zscore(s: pd.Series) -> pd.Series:
    """Demean and scale by std. Returns NaN where std == 0."""
    m = s.mean()
    sd = s.std()
    if sd == 0 or np.isnan(sd):
        return pd.Series(np.nan, index=s.index)
    return (s - m) / sd


def _rank_ascending(s: pd.Series) -> pd.Series:
    """Rank so that rank 1 = lowest value (used when 'direction' is long_low)."""
    return s.rank(method="average", ascending=True, na_option="bottom")


def _rank_descending(s: pd.Series) -> pd.Series:
    """Rank so that rank 1 = highest value (used when 'direction' is long_high)."""
    return s.rank(method="average", ascending=False, na_option="bottom")


def _make_factor_result(
    name: str,
    category: str,
    as_of_date: datetime,
    raw: pd.Series,
    direction: str = "long_high",
    winsorize: bool = True,
    universe: Optional[pd.Index] = None,
) -> FactorResult:
    """
    Shared post-processing: winsorize -> rank -> z-score -> pack into FactorResult.

    Args:
        raw: raw factor values indexed by ticker, may contain NaN.
        direction: 'long_high' (rank 1 = best = highest) or 'long_low' (rank 1 = best = lowest).
        winsorize: whether to winsorize raw values before z-scoring.
        universe: full ticker universe; used to compute coverage vs universe_size.
    """
    clean = raw.dropna()

    if winsorize and len(clean) >= 10:
        clean = _winsorize(clean)

    if direction == "long_low":
        rank_series = _rank_ascending(clean)
    else:
        rank_series = _rank_descending(clean)

    z_series = _cross_sectional_zscore(clean)
    # Flip z-score sign for long_low factors so positive z = better signal
    if direction == "long_low":
        z_series = -z_series

    return FactorResult(
        name=name,
        category=category,
        as_of_date=as_of_date,
        values=clean.to_dict(),
        rank=rank_series.astype(int).to_dict(),
        z_score=z_series.to_dict(),
        coverage=len(clean),
        universe_size=len(universe) if universe is not None else len(raw),
    )


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------

class BaseFactor(abc.ABC):
    """
    Abstract base for all alpha factors.

    Subclass contract:
        1. Set class-level attributes: FACTOR_ID, CATEGORY, DIRECTION, COMPUTE_FREQ
        2. Implement `_compute_raw(price_data, fundamental_data)` returning pd.Series (ticker -> value)
        3. Call `self.compute(...)` for standardized post-processing
    """

    FACTOR_ID: str = ""
    CATEGORY: str = ""
    DIRECTION: str = "long_high"       # long_high | long_low
    COMPUTE_FREQ: str = "monthly"      # daily | monthly | quarterly | annual
    WINSORIZE: bool = True

    def compute(
        self,
        as_of_date: datetime,
        price_data: pd.DataFrame,        # shape: (dates, tickers), daily close prices
        fundamental_data: Optional[pd.DataFrame] = None,
        universe: Optional[List[str]] = None,
        sector_map: Optional[Dict[str, str]] = None,
        sector_neutral: bool = False,
    ) -> FactorResult:
        """
        Public entry point. Calls _compute_raw(), applies sector-neutralization if requested,
        then standardizes and returns a FactorResult.

        Args:
            price_data: wide-format DataFrame with DatetimeIndex, columns = tickers.
            fundamental_data: optional wide or panel DataFrame for fundamental factors.
            universe: list of tickers to include; if None uses all columns in price_data.
            sector_map: dict {ticker -> sector_name}; required if sector_neutral=True.
            sector_neutral: if True, z-score within sector before cross-sectional standardization.
        """
        if universe is not None:
            price_data = price_data.reindex(columns=universe)
            if fundamental_data is not None:
                fundamental_data = fundamental_data.reindex(columns=universe)

        raw = self._compute_raw(price_data, fundamental_data)

        if sector_neutral and sector_map:
            raw = self._sector_neutralize(raw, sector_map)

        result = _make_factor_result(
            name=self.FACTOR_ID,
            category=self.CATEGORY,
            as_of_date=as_of_date,
            raw=raw,
            direction=self.DIRECTION,
            winsorize=self.WINSORIZE,
            universe=price_data.columns,
        )
        return result

    @abc.abstractmethod
    def _compute_raw(
        self,
        price_data: pd.DataFrame,
        fundamental_data: Optional[pd.DataFrame],
    ) -> pd.Series:
        """
        Return raw factor values as pd.Series indexed by ticker.
        NaN is acceptable for tickers with insufficient data.
        """

    def _sector_neutralize(self, raw: pd.Series, sector_map: Dict[str, str]) -> pd.Series:
        """
        Demean within each sector so the factor is orthogonal to sector membership.
        Tickers not in sector_map are left in a synthetic 'Unknown' sector.
        """
        df = raw.rename("value").to_frame()
        df["sector"] = df.index.map(lambda t: sector_map.get(t, "Unknown"))
        df["value"] = df.groupby("sector")["value"].transform(
            lambda g: (g - g.mean()) / (g.std() + 1e-9)
        )
        return df["value"]


# ---------------------------------------------------------------------------
# IMPLEMENTATION 1: Momentum 1-Month
# ---------------------------------------------------------------------------

class Momentum1M(BaseFactor):
    """
    1-Month price momentum: total return over trailing 21 trading days.

    Signal interpretation: long recent winners, short recent losers.
    Known issue: susceptible to mean-reversion at very short horizons (< 5 days).
    """

    FACTOR_ID = "MOM_1M"
    CATEGORY = "momentum"
    DIRECTION = "long_high"
    COMPUTE_FREQ = "monthly"
    LOOKBACK_DAYS = 21

    def _compute_raw(
        self,
        price_data: pd.DataFrame,
        fundamental_data: Optional[pd.DataFrame] = None,
    ) -> pd.Series:
        if len(price_data) < self.LOOKBACK_DAYS + 1:
            logger.warning(
                "MOM_1M: price_data has only %d rows, need >= %d",
                len(price_data), self.LOOKBACK_DAYS + 1,
            )
            return pd.Series(dtype=float)

        # Use last available row as t, row at -LOOKBACK_DAYS as t-lookback
        price_now = price_data.iloc[-1]
        price_past = price_data.iloc[-self.LOOKBACK_DAYS - 1]

        momentum = (price_now - price_past) / price_past
        return momentum.replace([np.inf, -np.inf], np.nan)


# ---------------------------------------------------------------------------
# IMPLEMENTATION 2: Trailing P/E (as earnings yield = E/P)
# ---------------------------------------------------------------------------

class TrailingPE(BaseFactor):
    """
    Trailing earnings yield: earnings_ttm / market_cap (i.e. E/P, the inverse of P/E).

    We use E/P rather than P/E so the signal is linear and well-behaved:
        - high E/P  = cheap = long signal
        - negative EPS stocks are set to NaN (excluded from ranking)

    fundamental_data expected columns (MultiIndex or dict):
        'earnings_ttm': trailing 12-month net income (same currency as market cap)
        'market_cap'  : current market capitalization

    If price_data-derived market cap is preferred, pass it as a column in fundamental_data
    named 'market_cap'.
    """

    FACTOR_ID = "VAL_TRAILING_PE"
    CATEGORY = "value"
    DIRECTION = "long_high"
    COMPUTE_FREQ = "monthly"

    REQUIRED_COLUMNS = {"earnings_ttm", "market_cap"}

    def _compute_raw(
        self,
        price_data: pd.DataFrame,
        fundamental_data: Optional[pd.DataFrame] = None,
    ) -> pd.Series:
        if fundamental_data is None:
            raise ValueError("TrailingPE requires fundamental_data with 'earnings_ttm' and 'market_cap'.")

        missing = self.REQUIRED_COLUMNS - set(fundamental_data.index)
        if missing:
            raise KeyError(f"TrailingPE: fundamental_data missing rows: {missing}")

        earnings = fundamental_data.loc["earnings_ttm"].astype(float)
        mktcap = fundamental_data.loc["market_cap"].astype(float)

        # Exclude negative earners (undefined P/E direction)
        earnings = earnings.where(earnings > 0, other=np.nan)

        earnings_yield = earnings / mktcap
        return earnings_yield.replace([np.inf, -np.inf], np.nan)


# ---------------------------------------------------------------------------
# IMPLEMENTATION 3: ROE (Quality)
# ---------------------------------------------------------------------------

class ReturnOnEquity(BaseFactor):
    """
    Return on Equity: net_income_ttm / average_equity.

    Uses average of beginning and ending equity to reduce point-in-time noise.
    Negative equity firms are excluded (ROE undefined / misleading).

    fundamental_data expected rows:
        'net_income_ttm'    : trailing 12-month net income
        'equity_current'    : total shareholders' equity at period end
        'equity_prior'      : total shareholders' equity at prior period end (for averaging)

    If equity_prior is unavailable, equity_current alone is used.
    """

    FACTOR_ID = "QUAL_ROE"
    CATEGORY = "quality"
    DIRECTION = "long_high"
    COMPUTE_FREQ = "quarterly"

    def _compute_raw(
        self,
        price_data: pd.DataFrame,
        fundamental_data: Optional[pd.DataFrame] = None,
    ) -> pd.Series:
        if fundamental_data is None:
            raise ValueError("ROE requires fundamental_data with net_income_ttm and equity fields.")

        net_income = fundamental_data.loc["net_income_ttm"].astype(float)
        equity_current = fundamental_data.loc["equity_current"].astype(float)

        if "equity_prior" in fundamental_data.index:
            equity_prior = fundamental_data.loc["equity_prior"].astype(float)
            avg_equity = (equity_current + equity_prior) / 2.0
        else:
            avg_equity = equity_current

        # Exclude firms with negative equity (financial distress signal, not quality)
        avg_equity = avg_equity.where(avg_equity > 0, other=np.nan)

        roe = net_income / avg_equity
        return roe.replace([np.inf, -np.inf], np.nan)


# ---------------------------------------------------------------------------
# Factor Registry
# ---------------------------------------------------------------------------

FACTOR_REGISTRY: Dict[str, type[BaseFactor]] = {
    "MOM_1M": Momentum1M,
    "VAL_TRAILING_PE": TrailingPE,
    "QUAL_ROE": ReturnOnEquity,
    # Additional factors: register here as they are implemented
}


def get_factor(factor_id: str) -> BaseFactor:
    """Instantiate a factor by ID from the registry."""
    if factor_id not in FACTOR_REGISTRY:
        raise KeyError(
            f"Factor '{factor_id}' not found. Available: {list(FACTOR_REGISTRY.keys())}"
        )
    return FACTOR_REGISTRY[factor_id]()


# ---------------------------------------------------------------------------
# FactorEngine: orchestrates multi-factor computation
# ---------------------------------------------------------------------------

class FactorEngine:
    """
    Runs multiple factors on a given date and returns a combined factor matrix.

    Usage:
        engine = FactorEngine(factor_ids=["MOM_1M", "MOM_6M", "QUAL_ROE"])
        results = engine.run(
            as_of_date=datetime(2026, 5, 21),
            price_data=price_df,
            fundamental_data=fund_df,
            universe=tickers,
        )
        factor_matrix = engine.to_dataframe(results)
    """

    def __init__(self, factor_ids: List[str]):
        self.factors = {fid: get_factor(fid) for fid in factor_ids}

    def run(
        self,
        as_of_date: datetime,
        price_data: pd.DataFrame,
        fundamental_data: Optional[pd.DataFrame] = None,
        universe: Optional[List[str]] = None,
        sector_map: Optional[Dict[str, str]] = None,
        sector_neutral: bool = False,
    ) -> Dict[str, FactorResult]:
        """
        Compute all registered factors and return dict {factor_id -> FactorResult}.
        Factors that raise exceptions are logged and excluded (no silent failures).
        """
        results: Dict[str, FactorResult] = {}
        for fid, factor in self.factors.items():
            try:
                result = factor.compute(
                    as_of_date=as_of_date,
                    price_data=price_data,
                    fundamental_data=fundamental_data,
                    universe=universe,
                    sector_map=sector_map,
                    sector_neutral=sector_neutral,
                )
                results[fid] = result
                logger.info("Computed %s: coverage %d/%d", fid, result.coverage, result.universe_size)
            except Exception as exc:
                logger.error("Factor %s failed: %s", fid, exc, exc_info=True)
        return results

    @staticmethod
    def to_dataframe(results: Dict[str, FactorResult], use: str = "z_score") -> pd.DataFrame:
        """
        Stack factor results into a DataFrame.
        Shape: (tickers, factors).
        use: 'z_score' | 'rank' | 'values'
        """
        frames = {}
        for fid, res in results.items():
            if use == "z_score":
                frames[fid] = pd.Series(res.z_score)
            elif use == "rank":
                frames[fid] = pd.Series(res.rank)
            else:
                frames[fid] = pd.Series(res.values)
        return pd.DataFrame(frames)

    @staticmethod
    def composite_score(
        factor_df: pd.DataFrame,
        weights: Optional[Dict[str, float]] = None,
    ) -> pd.Series:
        """
        Equal-weight (or custom-weight) composite alpha score.
        Input: DataFrame from to_dataframe(use='z_score').
        Returns: pd.Series (ticker -> composite z-score).
        """
        if weights is None:
            score = factor_df.mean(axis=1, skipna=True)
        else:
            w = pd.Series(weights).reindex(factor_df.columns).fillna(0.0)
            w = w / w.sum()
            score = factor_df.mul(w).sum(axis=1, skipna=True)
        return score.rename("composite_alpha")


# ---------------------------------------------------------------------------
# Quick smoke test (run directly: python factors.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    rng = np.random.default_rng(42)

    # --- synthetic price data: 300 trading days x 50 tickers ---
    tickers = [f"TICK{i:03d}" for i in range(50)]
    dates = pd.date_range("2025-01-01", periods=300, freq="B")
    prices = pd.DataFrame(
        rng.lognormal(mean=0, sigma=0.01, size=(300, 50)).cumprod(axis=0) * 100,
        index=dates,
        columns=tickers,
    )

    # --- synthetic fundamental data: rows = metrics, cols = tickers ---
    fundamentals = pd.DataFrame(
        {
            "earnings_ttm": rng.uniform(50e6, 5e9, size=50),
            "market_cap": rng.uniform(500e6, 50e9, size=50),
            "net_income_ttm": rng.uniform(30e6, 3e9, size=50),
            "equity_current": rng.uniform(200e6, 20e9, size=50),
            "equity_prior": rng.uniform(180e6, 19e9, size=50),
        },
        index=tickers,
    ).T  # shape: (metrics, tickers)

    engine = FactorEngine(["MOM_1M", "VAL_TRAILING_PE", "QUAL_ROE"])
    results = engine.run(
        as_of_date=datetime(2026, 5, 21),
        price_data=prices,
        fundamental_data=fundamentals,
        universe=tickers,
    )

    factor_df = FactorEngine.to_dataframe(results, use="z_score")
    composite = FactorEngine.composite_score(factor_df)

    print("\n=== Factor Matrix (first 5 tickers) ===")
    print(factor_df.head())
    print("\n=== Top 10 Composite Alpha ===")
    print(composite.nlargest(10))
    for fid, res in results.items():
        print(f"\n{res.summary()}")

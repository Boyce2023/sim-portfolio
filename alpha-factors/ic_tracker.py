"""
IC/IR Tracking System for Alpha Factors.

Tracks Information Coefficient (IC) and Information Ratio (IC IR) across time,
provides factor status classification (alive/reversed/dead), decay analysis,
and turnover measurement.

Definitions:
    IC       = Spearman rank correlation between factor z-scores at t and forward returns at t+h
    IC IR    = mean(IC_series) / std(IC_series)  -- annualized if monthly IC
    Turnover = fraction of universe that changes quintile rank between adjacent periods
    Decay    = IC as a function of holding period h (1m, 2m, 3m, 6m, 12m)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IC record (one observation = one factor x one date x one holding period)
# ---------------------------------------------------------------------------

@dataclass
class ICRecord:
    factor_id: str
    as_of_date: str                    # ISO format: "2026-05-21"
    holding_period_days: int           # 21, 63, 126, 252
    ic: float                          # Spearman IC [-1, +1]
    n_stocks: int                      # sample size used in correlation
    p_value: Optional[float] = None   # two-tailed p-value for IC != 0
    forward_return_label: str = ""    # e.g. "1m", "3m"

    @property
    def is_significant(self) -> bool:
        """IC is statistically significant at 5% level."""
        return self.p_value is not None and self.p_value < 0.05


# ---------------------------------------------------------------------------
# Factor status tracker (stateful, per factor)
# ---------------------------------------------------------------------------

@dataclass
class FactorStats:
    factor_id: str
    category: str

    # Rolling IC series (monthly, primary holding period)
    ic_series: List[float] = field(default_factory=list)
    ic_dates: List[str] = field(default_factory=list)

    # IC by holding period for decay analysis
    ic_by_horizon: Dict[str, List[float]] = field(default_factory=dict)
    # keys: "1m", "2m", "3m", "6m", "12m"

    # Turnover history
    turnover_series: List[float] = field(default_factory=list)
    turnover_dates: List[str] = field(default_factory=list)

    # Derived metrics (recomputed on access)
    mean_ic: Optional[float] = None
    ic_std: Optional[float] = None
    ic_ir: Optional[float] = None
    hit_rate: Optional[float] = None   # fraction of IC > 0 observations
    status: str = "alive"
    status_updated_at: Optional[str] = None

    # Status thresholds (can be overridden per factor)
    alive_ic_threshold: float = 0.02
    alive_ir_threshold: float = 0.30
    dead_ic_threshold: float = 0.01
    dead_ir_threshold: float = 0.10
    trailing_window: int = 36          # months for status classification

    def update_derived(self) -> None:
        """Recompute mean_ic, ic_std, ic_ir, hit_rate from ic_series."""
        if len(self.ic_series) == 0:
            return
        arr = np.array(self.ic_series[-self.trailing_window :])
        self.mean_ic = float(np.mean(arr))
        self.ic_std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        self.ic_ir = (self.mean_ic / self.ic_std) if self.ic_std > 0 else 0.0
        self.hit_rate = float(np.mean(arr > 0))

    def classify_status(self) -> str:
        """
        Classify factor status based on trailing IC statistics.

        Rules:
            alive    : |mean_ic| > alive_ic_threshold AND |ic_ir| > alive_ir_threshold
            reversed : mean_ic < -alive_ic_threshold (signal direction flipped)
            dead     : |mean_ic| <= dead_ic_threshold OR |ic_ir| <= dead_ir_threshold
        """
        self.update_derived()
        if self.mean_ic is None or self.ic_ir is None:
            return "alive"  # insufficient data

        if self.mean_ic < -self.alive_ic_threshold and abs(self.ic_ir) > self.alive_ir_threshold:
            new_status = "reversed"
        elif abs(self.mean_ic) <= self.dead_ic_threshold or abs(self.ic_ir) <= self.dead_ir_threshold:
            new_status = "dead"
        else:
            new_status = "alive"

        if new_status != self.status:
            logger.warning(
                "Factor %s status changed: %s -> %s  (IC=%.4f, IR=%.4f)",
                self.factor_id, self.status, new_status, self.mean_ic, self.ic_ir,
            )
            self.status = new_status
            self.status_updated_at = datetime.utcnow().isoformat()

        return self.status

    def mean_turnover(self, window: int = 12) -> Optional[float]:
        if len(self.turnover_series) == 0:
            return None
        return float(np.mean(self.turnover_series[-window:]))

    def summary(self) -> str:
        self.update_derived()
        lines = [
            f"Factor   : {self.factor_id}  [{self.category}]",
            f"Status   : {self.status}",
            f"N obs    : {len(self.ic_series)} monthly IC records",
            f"Mean IC  : {self.mean_ic:.4f}" if self.mean_ic is not None else "Mean IC  : n/a",
            f"IC Std   : {self.ic_std:.4f}" if self.ic_std is not None else "IC Std   : n/a",
            f"IC IR    : {self.ic_ir:.4f}" if self.ic_ir is not None else "IC IR    : n/a",
            f"Hit Rate : {self.hit_rate:.1%}" if self.hit_rate is not None else "Hit Rate : n/a",
            f"Turnover : {self.mean_turnover():.1%}" if self.mean_turnover() is not None else "Turnover : n/a",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# IC Tracker (main class)
# ---------------------------------------------------------------------------

class ICTracker:
    """
    Computes and persists IC/IR history for a library of alpha factors.

    Typical workflow:
        tracker = ICTracker(storage_path="./ic_store/")
        tracker.load()

        # After each period end when forward returns are realized:
        tracker.record_ic(
            factor_id="MOM_1M",
            category="momentum",
            as_of_date=period_end,
            factor_values=factor_result.to_series(),
            forward_returns=next_month_returns,
            holding_period_days=21,
        )
        tracker.record_turnover(
            factor_id="MOM_1M",
            prev_ranks=prev_factor_result.to_rank_series(),
            curr_ranks=curr_factor_result.to_rank_series(),
            as_of_date=period_end,
            n_quintiles=5,
        )
        tracker.update_all_statuses()
        tracker.save()

        # Query
        stats = tracker.get_stats("MOM_1M")
        decay_table = tracker.compute_decay_table("MOM_1M")
        report = tracker.generate_report()
    """

    def __init__(self, storage_path: str = "./ic_store/"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._stats: Dict[str, FactorStats] = {}      # factor_id -> FactorStats
        self._records: List[ICRecord] = []             # all raw IC records (append-only)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist stats and records to JSON files."""
        stats_path = self.storage_path / "factor_stats.json"
        records_path = self.storage_path / "ic_records.json"

        stats_payload = {fid: asdict(s) for fid, s in self._stats.items()}
        with open(stats_path, "w") as f:
            json.dump(stats_payload, f, indent=2)

        records_payload = [asdict(r) for r in self._records]
        with open(records_path, "w") as f:
            json.dump(records_payload, f, indent=2)

        logger.info("ICTracker saved: %d factor stats, %d records", len(self._stats), len(self._records))

    def load(self) -> None:
        """Load persisted stats and records from storage."""
        stats_path = self.storage_path / "factor_stats.json"
        records_path = self.storage_path / "ic_records.json"

        if stats_path.exists():
            with open(stats_path) as f:
                raw = json.load(f)
            for fid, d in raw.items():
                self._stats[fid] = FactorStats(**d)
            logger.info("Loaded %d factor stats from %s", len(self._stats), stats_path)

        if records_path.exists():
            with open(records_path) as f:
                raw = json.load(f)
            self._records = [ICRecord(**r) for r in raw]
            logger.info("Loaded %d IC records from %s", len(self._records), records_path)

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    @staticmethod
    def _spearman_ic(
        factor_values: pd.Series,
        forward_returns: pd.Series,
    ) -> Tuple[float, float, int]:
        """
        Compute Spearman rank IC between factor values and forward returns.

        Args:
            factor_values: factor scores indexed by ticker.
            forward_returns: realized returns indexed by ticker.

        Returns:
            (ic, p_value, n_stocks)
        """
        aligned = pd.concat([factor_values.rename("factor"), forward_returns.rename("ret")], axis=1).dropna()
        if len(aligned) < 10:
            logger.warning("Too few observations (%d) for IC calculation.", len(aligned))
            return np.nan, np.nan, len(aligned)

        ic, p_value = stats.spearmanr(aligned["factor"], aligned["ret"])
        return float(ic), float(p_value), len(aligned)

    def record_ic(
        self,
        factor_id: str,
        category: str,
        as_of_date: datetime,
        factor_values: pd.Series,      # factor z-scores or raw values at t
        forward_returns: pd.Series,    # total return from t to t+h
        holding_period_days: int = 21,
        horizon_label: str = "1m",
    ) -> ICRecord:
        """
        Compute IC for one factor on one date and store the record.

        The as_of_date is the date the factor was computed (formation date).
        forward_returns are realized returns from as_of_date to as_of_date + holding_period_days.
        """
        ic, p_value, n = self._spearman_ic(factor_values, forward_returns)

        record = ICRecord(
            factor_id=factor_id,
            as_of_date=as_of_date.strftime("%Y-%m-%d"),
            holding_period_days=holding_period_days,
            ic=ic,
            n_stocks=n,
            p_value=p_value,
            forward_return_label=horizon_label,
        )
        self._records.append(record)

        # Update stats (primary horizon only for ic_series; all horizons in ic_by_horizon)
        if factor_id not in self._stats:
            self._stats[factor_id] = FactorStats(factor_id=factor_id, category=category)

        stats_obj = self._stats[factor_id]

        # Primary IC series (used for IR and status)
        if horizon_label == "1m" or len(stats_obj.ic_series) == 0:
            if not np.isnan(ic):
                stats_obj.ic_series.append(ic)
                stats_obj.ic_dates.append(record.as_of_date)

        # Multi-horizon IC for decay analysis
        if horizon_label not in stats_obj.ic_by_horizon:
            stats_obj.ic_by_horizon[horizon_label] = []
        if not np.isnan(ic):
            stats_obj.ic_by_horizon[horizon_label].append(ic)

        return record

    def record_turnover(
        self,
        factor_id: str,
        prev_ranks: pd.Series,
        curr_ranks: pd.Series,
        as_of_date: datetime,
        n_quintiles: int = 5,
    ) -> float:
        """
        Compute and record monthly factor turnover.

        Turnover = fraction of universe that changed quintile bucket between prev and curr.

        Args:
            prev_ranks: factor ranks at t-1 (higher rank = better factor value).
            curr_ranks: factor ranks at t.
            n_quintiles: number of buckets for quintile classification.

        Returns:
            turnover fraction [0, 1].
        """
        aligned = pd.concat([prev_ranks.rename("prev"), curr_ranks.rename("curr")], axis=1).dropna()
        if len(aligned) == 0:
            return np.nan

        n = len(aligned)
        quintile_size = n / n_quintiles
        prev_quintile = (aligned["prev"] / quintile_size).clip(0, n_quintiles - 1).astype(int)
        curr_quintile = (aligned["curr"] / quintile_size).clip(0, n_quintiles - 1).astype(int)

        changed = (prev_quintile != curr_quintile).sum()
        turnover = changed / n

        if factor_id in self._stats:
            self._stats[factor_id].turnover_series.append(float(turnover))
            self._stats[factor_id].turnover_dates.append(as_of_date.strftime("%Y-%m-%d"))

        return float(turnover)

    # ------------------------------------------------------------------
    # Status and analytics
    # ------------------------------------------------------------------

    def update_all_statuses(self) -> Dict[str, str]:
        """Recompute status for all tracked factors. Returns {factor_id: status}."""
        return {fid: s.classify_status() for fid, s in self._stats.items()}

    def get_stats(self, factor_id: str) -> Optional[FactorStats]:
        return self._stats.get(factor_id)

    def compute_decay_table(self, factor_id: str) -> pd.DataFrame:
        """
        Return IC decay table across holding periods.

        Shape: (horizons x [mean_ic, ic_ir, n_obs])
        """
        if factor_id not in self._stats:
            raise KeyError(f"No IC data for factor '{factor_id}'")

        stats_obj = self._stats[factor_id]
        rows = []
        for horizon_label, ic_list in sorted(stats_obj.ic_by_horizon.items()):
            arr = np.array(ic_list)
            if len(arr) == 0:
                continue
            mean_ic = np.mean(arr)
            ic_std = np.std(arr, ddof=1) if len(arr) > 1 else 0.0
            ir = mean_ic / ic_std if ic_std > 0 else np.nan
            rows.append({
                "horizon": horizon_label,
                "mean_ic": round(float(mean_ic), 4),
                "ic_ir": round(float(ir), 4) if not np.isnan(ir) else None,
                "n_obs": len(arr),
                "hit_rate": round(float(np.mean(arr > 0)), 4),
            })
        return pd.DataFrame(rows).set_index("horizon") if rows else pd.DataFrame()

    def ic_timeseries(self, factor_id: str) -> pd.Series:
        """Return IC time series as pd.Series with DatetimeIndex."""
        if factor_id not in self._stats:
            return pd.Series(dtype=float)
        s = self._stats[factor_id]
        if not s.ic_series:
            return pd.Series(dtype=float)
        idx = pd.to_datetime(s.ic_dates)
        return pd.Series(s.ic_series, index=idx, name=factor_id)

    def cumulative_ic(self, factor_id: str) -> pd.Series:
        """Cumulative sum of IC (useful for visualizing persistent alpha)."""
        return self.ic_timeseries(factor_id).cumsum()

    # ------------------------------------------------------------------
    # Cross-factor report
    # ------------------------------------------------------------------

    def generate_report(self, top_n: int = 10) -> pd.DataFrame:
        """
        Summary table across all tracked factors.

        Returns DataFrame with columns:
            factor_id, category, n_obs, mean_ic, ic_std, ic_ir, hit_rate, mean_turnover, status
        """
        rows = []
        for fid, s in self._stats.items():
            s.update_derived()
            rows.append({
                "factor_id": fid,
                "category": s.category,
                "n_obs": len(s.ic_series),
                "mean_ic": round(s.mean_ic, 4) if s.mean_ic is not None else None,
                "ic_std": round(s.ic_std, 4) if s.ic_std is not None else None,
                "ic_ir": round(s.ic_ir, 4) if s.ic_ir is not None else None,
                "hit_rate": round(s.hit_rate, 4) if s.hit_rate is not None else None,
                "mean_turnover_12m": round(s.mean_turnover(), 4) if s.mean_turnover() is not None else None,
                "status": s.status,
            })

        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return df.sort_values("ic_ir", ascending=False, na_position="last").reset_index(drop=True)

    def alive_factors(self) -> List[str]:
        return [fid for fid, s in self._stats.items() if s.status == "alive"]

    def dead_factors(self) -> List[str]:
        return [fid for fid, s in self._stats.items() if s.status == "dead"]

    def reversed_factors(self) -> List[str]:
        return [fid for fid, s in self._stats.items() if s.status == "reversed"]

    def factor_correlation_matrix(self, use_raw_ic: bool = True) -> pd.DataFrame:
        """
        Compute pairwise correlation of IC time series across factors.
        High correlation = redundant signals; low correlation = diversification value.
        """
        series_dict = {}
        for fid in self._stats:
            ts = self.ic_timeseries(fid)
            if len(ts) >= 6:
                series_dict[fid] = ts
        if not series_dict:
            return pd.DataFrame()
        df = pd.DataFrame(series_dict)
        return df.corr(method="pearson")


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    rng = np.random.default_rng(0)

    tracker = ICTracker(storage_path="/tmp/ic_store_test/")

    tickers = [f"T{i:03d}" for i in range(100)]
    n_periods = 24  # simulate 24 monthly observations

    for t in range(n_periods):
        date = pd.Timestamp("2024-06-01") + pd.DateOffset(months=t)

        # Simulate factor values with true alpha embedded
        factor_values = pd.Series(rng.normal(0, 1, 100), index=tickers)
        true_alpha = 0.03  # signal-to-noise ratio
        noise = rng.normal(0, 1, 100)
        forward_returns = pd.Series(true_alpha * factor_values.values + noise, index=tickers)

        tracker.record_ic(
            factor_id="MOM_1M",
            category="momentum",
            as_of_date=date,
            factor_values=factor_values,
            forward_returns=forward_returns,
            holding_period_days=21,
            horizon_label="1m",
        )
        # Also record 3-month IC (use same factor, different fwd returns for illustration)
        forward_returns_3m = pd.Series(true_alpha * factor_values.values + rng.normal(0, 1.2, 100), index=tickers)
        tracker.record_ic(
            factor_id="MOM_1M",
            category="momentum",
            as_of_date=date,
            factor_values=factor_values,
            forward_returns=forward_returns_3m,
            holding_period_days=63,
            horizon_label="3m",
        )

        if t > 0:
            prev_ranks = pd.Series(rng.permutation(100) + 1, index=tickers)
            curr_ranks = pd.Series(rng.permutation(100) + 1, index=tickers)
            tracker.record_turnover("MOM_1M", prev_ranks, curr_ranks, date)

    tracker.update_all_statuses()

    stats = tracker.get_stats("MOM_1M")
    print(stats.summary())

    print("\n=== Decay Table ===")
    print(tracker.compute_decay_table("MOM_1M"))

    print("\n=== Cross-Factor Report ===")
    print(tracker.generate_report())

    tracker.save()
    print("\nPersisted to /tmp/ic_store_test/")

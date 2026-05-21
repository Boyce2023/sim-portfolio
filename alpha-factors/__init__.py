"""
Alpha Factor Library — sim-portfolio integration package.

Provides:
    - BaseFactor: abstract base class for all alpha factors
    - FactorResult: standardized output container
    - FactorEngine: multi-factor orchestrator (compute, rank, z-score, composite)
    - Momentum1M, TrailingPE, ReturnOnEquity: 3 implemented factors
    - get_factor(factor_id): instantiate by ID from FACTOR_REGISTRY
    - FACTOR_REGISTRY: dict of all registered factor classes

    - ICTracker: computes and persists IC/IR history
    - ICRecord: single IC observation dataclass
    - FactorStats: per-factor rolling stats and status classification

Usage:
    from alpha_factors import FactorEngine, ICTracker

    engine = FactorEngine(["MOM_1M", "VAL_TRAILING_PE", "QUAL_ROE"])
    results = engine.run(as_of_date=..., price_data=..., fundamental_data=...)
    factor_df = FactorEngine.to_dataframe(results, use="z_score")
    composite = FactorEngine.composite_score(factor_df)

    tracker = ICTracker(storage_path="./ic_store/")
    tracker.load()
    tracker.record_ic(factor_id="MOM_1M", ...)
    tracker.save()

See INTEGRATION.md for full backtest wiring guide.
Factor definitions (all 30): factor_zoo.json
"""

from .factors import (
    BaseFactor,
    FactorResult,
    FactorEngine,
    Momentum1M,
    TrailingPE,
    ReturnOnEquity,
    FACTOR_REGISTRY,
    get_factor,
)

from .ic_tracker import (
    ICTracker,
    ICRecord,
    FactorStats,
)

__all__ = [
    # factors.py
    "BaseFactor",
    "FactorResult",
    "FactorEngine",
    "Momentum1M",
    "TrailingPE",
    "ReturnOnEquity",
    "FACTOR_REGISTRY",
    "get_factor",
    # ic_tracker.py
    "ICTracker",
    "ICRecord",
    "FactorStats",
]

"""
Nexus API Layer — Pydantic Models
Mirrors on-disk JSON schemas for Truth Store and Signal Bus.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class SignalPriority(str, Enum):
    critical = "critical"   # 3-day TTL
    high = "high"           # 7-day TTL
    medium = "medium"       # 14-day TTL
    low = "low"             # 30-day TTL


class SignalLifecycle(str, Enum):
    pending = "pending"
    read = "read"
    acted_on = "acted_on"
    expired = "expired"
    superseded = "superseded"


class SignalType(str, Enum):
    system_sync = "system_sync"
    research_update = "research_update"
    data_staleness = "data_staleness"
    trading_alert = "trading_alert"
    contradiction = "contradiction"
    architecture_change = "architecture_change"
    task_assignment = "task_assignment"
    quality_alert = "quality_alert"


class WorkstreamID(str, Enum):
    research = "research"
    trading = "trading"
    tracking = "tracking"
    events = "events"
    interviews = "interviews"
    nexus = "nexus"


class Direction(str, Enum):
    long = "long"
    short = "short"


class PositionStatus(str, Enum):
    active = "active"
    closed = "closed"
    watch = "watch"


class Quadrant(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    Q1_pending = "Q1_pending"
    Q3_pending = "Q3_pending"


# ---------------------------------------------------------------------------
# Truth Store — Key Fact (used inside company / macro entries)
# ---------------------------------------------------------------------------

class KeyFact(BaseModel):
    claim: str
    source: Optional[str] = None
    source_date: Optional[str] = None          # YYYY-MM-DD
    confidence: Confidence = Confidence.low
    verified: bool = False
    tags: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Truth Store — Company
# ---------------------------------------------------------------------------

class Holding(BaseModel):
    shares: float
    avg_cost: float
    entry_date: Optional[str] = None           # YYYY-MM-DD


class CompanyTruth(BaseModel):
    entity: str                                # ticker or 6-digit A-share code
    name: str
    market: str                                # "US" | "CN" | "HK"
    exchange: Optional[str] = None
    sector: Optional[str] = None
    position_status: Optional[str] = None     # "active_holding" | "watchlist" | "excluded"
    holding: Optional[Holding] = None
    key_facts: List[KeyFact] = Field(default_factory=list)
    thesis: Optional[str] = None
    last_updated: Optional[datetime] = None


class CompanySummary(BaseModel):
    """Lightweight list item — returned by GET /api/truth/companies"""
    entity: str
    name: str
    market: str
    sector: Optional[str] = None
    position_status: Optional[str] = None
    fact_count: int = 0
    verified_count: int = 0
    high_confidence_count: int = 0
    last_updated: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Truth Store — Macro Indicators
# ---------------------------------------------------------------------------

class MacroIndicator(BaseModel):
    id: str
    entity: str                                # "VIX", "DXY", etc.
    category: str
    claim: str
    value: Optional[float] = None
    unit: Optional[str] = None
    source: Optional[str] = None
    source_date: Optional[str] = None
    last_refreshed: Optional[datetime] = None
    confidence: Confidence = Confidence.low
    verified: bool = False
    stale_after_days: int = 1
    yf_command: Optional[str] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    tags: List[str] = Field(default_factory=list)

    @property
    def is_stale(self) -> bool:
        if self.last_refreshed is None:
            return True
        from datetime import timezone, timedelta
        age = datetime.now(timezone.utc) - self.last_refreshed.replace(
            tzinfo=self.last_refreshed.tzinfo or timezone.utc
        )
        return age.days >= self.stale_after_days


class MacroIndicatorsResponse(BaseModel):
    metadata: Dict[str, Any]
    indicators: List[MacroIndicator]


# ---------------------------------------------------------------------------
# Truth Store — Portfolio
# ---------------------------------------------------------------------------

class Position(BaseModel):
    id: str
    entity: str
    name: str
    category: str = "position"
    direction: Direction = Direction.long
    status: PositionStatus = PositionStatus.active
    market: str
    quantity: Optional[float] = None
    entry_price: Optional[float] = None
    entry_date: Optional[str] = None
    target_price_ref: Optional[str] = None
    bear_case_ref: Optional[str] = None
    stop_loss_ref: Optional[str] = None
    next_catalyst: Optional[str] = None
    key_edge: Optional[str] = None
    source: Optional[str] = None
    confidence: Confidence = Confidence.low
    verified: bool = False
    thesis: Optional[str] = None
    claim: Optional[str] = None


class PortfolioMetadata(BaseModel):
    description: str
    ssot_path: Optional[str] = None
    ssot_note: Optional[str] = None
    last_updated: Optional[datetime] = None
    staleness_warning: Optional[Dict[str, Any]] = None
    account_info: Optional[Dict[str, Any]] = None


class PortfolioPositionsResponse(BaseModel):
    metadata: PortfolioMetadata
    positions: List[Position]


# ---------------------------------------------------------------------------
# Portfolio — Performance / State (read from portfolio_state.json)
# ---------------------------------------------------------------------------

class PerformanceMetrics(BaseModel):
    total_return_pct: Optional[float] = None
    ytd_return_pct: Optional[float] = None
    realized_pnl: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    total_equity_usd: Optional[float] = None
    total_equity_cny: Optional[float] = None
    cash_usd: Optional[float] = None
    cash_cny: Optional[float] = None
    as_of_date: Optional[str] = None
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# Portfolio — Trade Outcomes (Scorecard)
# ---------------------------------------------------------------------------

class TradeOutcome(BaseModel):
    trade_id: str
    ticker: str
    market: str
    direction: Direction
    entry_date: Optional[str] = None
    entry_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    quantity: Optional[float] = None
    realized_pnl_usd: Optional[float] = None
    status: str                                # "closed" | "open"
    rules_relevant: List[str] = Field(default_factory=list)
    rules_complied: List[str] = Field(default_factory=list)
    rules_violated: List[str] = Field(default_factory=list)
    compliance_note: Optional[str] = None
    quadrant: Optional[Quadrant] = None
    quadrant_rationale: Optional[str] = None
    shadow_portfolio_note: Optional[str] = None
    pre_nexus: bool = False
    notes: Optional[str] = None


class TradeOutcomesResponse(BaseModel):
    meta: Dict[str, Any]
    trades: List[TradeOutcome]


# ---------------------------------------------------------------------------
# Signal Bus
# ---------------------------------------------------------------------------

class SignalPayload(BaseModel):
    """Freeform payload — validated loosely, structure varies by signal type."""
    action: Optional[str] = None
    message: Optional[str] = None
    bulletin_version: Optional[str] = None
    files_to_reread: Optional[List[str]] = None
    files_to_reread_all: Optional[List[str]] = None
    data: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"


class Signal(BaseModel):
    id: str
    from_workstream: str = Field(alias="from")
    to: List[str]
    priority: SignalPriority
    type: SignalType
    created_at: datetime
    expires_at: Optional[datetime] = None
    payload: SignalPayload = Field(default_factory=SignalPayload)
    lifecycle: SignalLifecycle = SignalLifecycle.pending
    read_by: Optional[str] = None
    read_at: Optional[datetime] = None
    acted_on_at: Optional[datetime] = None
    action_result: Optional[str] = None
    superseded_by: Optional[str] = None

    class Config:
        populate_by_name = True


class SignalCreateRequest(BaseModel):
    """Body for POST /api/signals"""
    from_workstream: str = Field(alias="from", description="Sender workstream or external agent ID")
    to: List[str] = Field(description="Target workstream IDs; use ['all'] for broadcast")
    priority: SignalPriority
    type: SignalType
    payload: SignalPayload
    expires_in_hours: Optional[int] = Field(
        None,
        description="TTL override. Defaults: critical=72h, high=168h, medium=336h, low=720h"
    )

    class Config:
        populate_by_name = True


class SignalAckRequest(BaseModel):
    read_by: str = Field(description="Workstream or agent ID acknowledging the signal")


class SignalActedRequest(BaseModel):
    acted_by: str
    action_result: str = Field(description="Summary of action taken")


class SignalListResponse(BaseModel):
    total: int
    signals: List[Signal]


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

class RiskMetrics(BaseModel):
    total_positions: int
    active_long_count: int
    active_short_count: int
    concentration_top3_pct: Optional[float] = None
    bear_case_breach_count: int = Field(
        0, description="Positions where bear case downside > 20% (rule S2)"
    )
    stale_truth_count: int = Field(
        0, description="Truth Store entries older than 30 days"
    )
    pending_signal_count: int
    quality_alert: bool = Field(
        False, description="True when pending signals >= 10"
    )
    scorecard_q4_pct: Optional[float] = Field(
        None, description="% trades in Q4 quadrant (target < 15%)"
    )
    scorecard_q1_pct: Optional[float] = Field(
        None, description="% trades in Q1 quadrant (target > 50%)"
    )
    as_of: datetime


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str                                # "ok" | "degraded" | "error"
    version: str
    truth_store_files: int
    signals_pending: int
    signals_processed: int
    stale_indicators: List[str]
    timestamp: datetime


class SyncBulletin(BaseModel):
    version: str
    released_at: Optional[datetime] = None
    summary: Optional[str] = None
    files_updated: List[str] = Field(default_factory=list)
    breaking_changes: List[str] = Field(default_factory=list)
    migration_steps: List[str] = Field(default_factory=list)
    raw: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Error envelope
# ---------------------------------------------------------------------------

class APIError(BaseModel):
    error: str
    detail: Optional[str] = None
    code: Optional[str] = None

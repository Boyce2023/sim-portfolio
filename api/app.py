"""
Nexus API Layer — FastAPI Application
Signal Bus + Truth Store REST/WebSocket API

Usage:
    uvicorn app:app --host 0.0.0.0 --port 8000 --reload

Environment variables (see .env.example):
    NEXUS_ROOT          Path to ~/.claude/nexus           (required)
    PORTFOLIO_STATE     Path to portfolio_state.json       (required for /portfolio)
    API_WRITE_KEY       Secret key for write endpoints     (required)
    API_ADMIN_KEY       Secret key for admin endpoints     (optional, default=API_WRITE_KEY)
    HOST                Bind host                          (default: 0.0.0.0)
    PORT                Bind port                          (default: 8000)
    CORS_ORIGINS        Comma-separated allowed origins    (default: *)
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Security,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader

from models import (
    APIError,
    CompanySummary,
    CompanyTruth,
    HealthResponse,
    MacroIndicatorsResponse,
    PerformanceMetrics,
    PortfolioPositionsResponse,
    RiskMetrics,
    Signal,
    SignalAckRequest,
    SignalActedRequest,
    SignalCreateRequest,
    SignalListResponse,
    SignalLifecycle,
    SyncBulletin,
    TradeOutcomesResponse,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NEXUS_ROOT = Path(os.environ.get("NEXUS_ROOT", Path.home() / ".claude" / "nexus"))
PORTFOLIO_STATE_PATH = Path(
    os.environ.get(
        "PORTFOLIO_STATE",
        Path.home() / "claude-projects" / "sim-portfolio" / "portfolio_state.json",
    )
)
API_WRITE_KEY = os.environ.get("API_WRITE_KEY", "")
API_ADMIN_KEY = os.environ.get("API_ADMIN_KEY", API_WRITE_KEY)
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",")]

# Derived paths
TRUTH_ROOT = NEXUS_ROOT / "truth"
SIGNALS_PENDING = NEXUS_ROOT / "signals" / "pending"
SIGNALS_PROCESSED = NEXUS_ROOT / "signals" / "processed"
SYNC_BULLETIN = NEXUS_ROOT / "sync" / "update-bulletin.json"

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Nexus API",
    description=(
        "REST + WebSocket API for the Nexus multi-agent operating system. "
        "Exposes the Signal Bus and Truth Store for external agents and tools.\n\n"
        "**Authentication**: Write and admin endpoints require `X-API-Key` header. "
        "Read-only portfolio/risk endpoints are public."
    ),
    version="1.0.0",
    contact={"name": "Nexus System"},
    license_info={"name": "Private"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _require_write_key(key: Optional[str] = Security(api_key_header)):
    if not API_WRITE_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_WRITE_KEY not configured on server.",
        )
    if key != API_WRITE_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key.",
        )


def _require_admin_key(key: Optional[str] = Security(api_key_header)):
    if not API_ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_ADMIN_KEY not configured on server.",
        )
    if key != API_ADMIN_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin key required.",
        )


# ---------------------------------------------------------------------------
# File-system helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict:
    """Read a JSON file; raise 404 if missing."""
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {path.name}",
        )
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: dict) -> None:
    """Atomically write JSON (write to .tmp then rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _list_json_files(directory: Path) -> List[Path]:
    """Return all .json files in a directory, excluding _ prefixed index files."""
    if not directory.exists():
        return []
    return sorted(
        p for p in directory.glob("*.json") if not p.name.startswith("_")
    )


def _signal_path(signal_id: str) -> Optional[Path]:
    """Find a signal file in pending or processed by id."""
    for directory in (SIGNALS_PENDING, SIGNALS_PROCESSED):
        for p in directory.glob("*.json"):
            if p.stem == signal_id or p.name.startswith(signal_id):
                return p
    return None


# ---------------------------------------------------------------------------
# WebSocket connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self) -> None:
        self.active: Dict[str, List[WebSocket]] = {
            "signals": [],
            "prices": [],
        }

    async def connect(self, channel: str, ws: WebSocket) -> None:
        await ws.accept()
        self.active.setdefault(channel, []).append(ws)

    def disconnect(self, channel: str, ws: WebSocket) -> None:
        try:
            self.active[channel].remove(ws)
        except (KeyError, ValueError):
            pass

    async def broadcast(self, channel: str, message: dict) -> None:
        dead = []
        for ws in self.active.get(channel, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(channel, ws)


manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Truth Store — Companies
# ---------------------------------------------------------------------------

@app.get(
    "/api/truth/companies",
    response_model=List[CompanySummary],
    tags=["Truth Store"],
    summary="List all company truth entries",
)
def list_companies():
    """
    Returns a summary list of every company JSON in
    `{NEXUS_ROOT}/truth/companies/`.
    Reads the `_index.json` when available for efficient fact-count metadata;
    falls back to reading each file individually.
    """
    index_path = TRUTH_ROOT / "_index.json"
    summaries: List[CompanySummary] = []

    if index_path.exists():
        index = _read_json(index_path)
        for entry in index.get("files", []):
            path_str = entry.get("path", "")
            if not path_str.startswith("companies/"):
                continue
            summaries.append(
                CompanySummary(
                    entity=entry.get("entity", ""),
                    name=entry.get("entity", ""),   # full name resolved below
                    market="",
                    fact_count=entry.get("fact_count", 0),
                    verified_count=entry.get("verified", 0),
                    high_confidence_count=entry.get("high_confidence", 0),
                )
            )
        # Enrich names and market from individual files (best-effort)
        for s in summaries:
            fpath = TRUTH_ROOT / "companies" / f"{s.entity}.json"
            if fpath.exists():
                try:
                    raw = json.loads(fpath.read_text(encoding="utf-8"))
                    s.name = raw.get("name", s.entity)
                    s.market = raw.get("market", "")
                    s.sector = raw.get("sector")
                    s.position_status = raw.get("position_status")
                    raw_lu = raw.get("last_updated")
                    if raw_lu:
                        try:
                            s.last_updated = datetime.fromisoformat(raw_lu)
                        except ValueError:
                            pass
                except Exception:
                    pass
    else:
        for fpath in _list_json_files(TRUTH_ROOT / "companies"):
            try:
                raw = json.loads(fpath.read_text(encoding="utf-8"))
                facts = raw.get("key_facts", [])
                raw_lu = raw.get("last_updated")
                lu = None
                if raw_lu:
                    try:
                        lu = datetime.fromisoformat(raw_lu)
                    except ValueError:
                        pass
                summaries.append(
                    CompanySummary(
                        entity=raw.get("entity", fpath.stem),
                        name=raw.get("name", fpath.stem),
                        market=raw.get("market", ""),
                        sector=raw.get("sector"),
                        position_status=raw.get("position_status"),
                        fact_count=len(facts),
                        verified_count=sum(1 for f in facts if f.get("verified")),
                        high_confidence_count=sum(
                            1 for f in facts if f.get("confidence") == "high"
                        ),
                        last_updated=lu,
                    )
                )
            except Exception:
                continue

    return summaries


@app.get(
    "/api/truth/companies/{ticker}",
    response_model=CompanyTruth,
    tags=["Truth Store"],
    summary="Get full truth entry for a single company",
)
def get_company(ticker: str):
    """
    Reads `{NEXUS_ROOT}/truth/companies/{ticker}.json`.
    Ticker is case-sensitive (use uppercase for US, 6-digit codes for A-shares).
    """
    fpath = TRUTH_ROOT / "companies" / f"{ticker}.json"
    raw = _read_json(fpath)
    return CompanyTruth(**raw)


# ---------------------------------------------------------------------------
# Truth Store — Macro
# ---------------------------------------------------------------------------

@app.get(
    "/api/truth/macro/indicators",
    response_model=MacroIndicatorsResponse,
    tags=["Truth Store"],
    summary="Get all macro indicators",
)
def get_macro_indicators(
    stale_only: bool = Query(False, description="Return only stale indicators"),
    tag: Optional[str] = Query(None, description="Filter by tag (e.g. 'volatility', 'fx')"),
):
    """
    Reads `{NEXUS_ROOT}/truth/macro/indicators.json`.
    Optionally filter by staleness or tag.
    Note: values reflect last `yf` refresh — check `last_refreshed` before trusting numbers.
    """
    raw = _read_json(TRUTH_ROOT / "macro" / "indicators.json")
    indicators = raw.get("indicators", [])

    if tag:
        indicators = [i for i in indicators if tag in i.get("tags", [])]

    if stale_only:
        now = datetime.now(timezone.utc)
        filtered = []
        for i in indicators:
            lr = i.get("last_refreshed")
            sad = i.get("stale_after_days", 1)
            if lr is None:
                filtered.append(i)
                continue
            try:
                lr_dt = datetime.fromisoformat(lr)
                if lr_dt.tzinfo is None:
                    lr_dt = lr_dt.replace(tzinfo=timezone.utc)
                if (now - lr_dt).days >= sad:
                    filtered.append(i)
            except ValueError:
                filtered.append(i)
        indicators = filtered

    return {"metadata": raw.get("metadata", {}), "indicators": indicators}


# ---------------------------------------------------------------------------
# Truth Store — Portfolio
# ---------------------------------------------------------------------------

@app.get(
    "/api/truth/portfolio/positions",
    response_model=PortfolioPositionsResponse,
    tags=["Truth Store"],
    summary="Get portfolio positions from Truth Store (reference layer)",
)
def get_truth_portfolio():
    """
    Reads the Truth Store reference layer at
    `{NEXUS_ROOT}/truth/portfolio/positions.json`.

    **Important**: this is NOT the SSOT. For trading calculations use
    `GET /api/portfolio/state` which reads from `portfolio_state.json`.
    The Truth Store copy may be up to several days stale — check
    `metadata.staleness_warning` in the response.
    """
    raw = _read_json(TRUTH_ROOT / "portfolio" / "positions.json")
    return raw


# ---------------------------------------------------------------------------
# Portfolio — SSOT reads
# ---------------------------------------------------------------------------

@app.get(
    "/api/portfolio/state",
    tags=["Portfolio"],
    summary="Current portfolio state (SSOT)",
)
def get_portfolio_state():
    """
    Reads the real SSOT: `portfolio_state.json`.
    Returns raw JSON — schema varies by version.
    Use `GET /api/portfolio/performance` for structured metrics.
    """
    raw = _read_json(PORTFOLIO_STATE_PATH)
    return raw


@app.get(
    "/api/portfolio/performance",
    response_model=PerformanceMetrics,
    tags=["Portfolio"],
    summary="Structured performance metrics derived from portfolio_state.json",
)
def get_performance():
    """
    Extracts top-level performance metrics from portfolio_state.json.
    Fields may be null when the SSOT lacks that key.
    """
    raw = _read_json(PORTFOLIO_STATE_PATH)
    # Attempt common key names across portfolio_state versions
    perf = raw.get("performance", raw.get("metrics", raw.get("summary", {})))
    return PerformanceMetrics(
        total_return_pct=perf.get("total_return_pct") or perf.get("total_return"),
        ytd_return_pct=perf.get("ytd_return_pct") or perf.get("ytd_return"),
        realized_pnl=perf.get("realized_pnl") or perf.get("realized_pnl_usd"),
        unrealized_pnl=perf.get("unrealized_pnl") or perf.get("unrealized_pnl_usd"),
        total_equity_usd=perf.get("total_equity_usd") or perf.get("nav_usd"),
        total_equity_cny=perf.get("total_equity_cny") or perf.get("nav_cny"),
        cash_usd=perf.get("cash_usd"),
        cash_cny=perf.get("cash_cny"),
        as_of_date=raw.get("as_of") or raw.get("last_updated"),
        note=(
            "Derived from portfolio_state.json. "
            "Check staleness_warning in /api/truth/portfolio/positions for sync status."
        ),
    )


@app.get(
    "/api/portfolio/trades",
    response_model=TradeOutcomesResponse,
    tags=["Portfolio"],
    summary="Closed trade outcomes with Nexus scorecard quadrant",
)
def get_trades(
    quadrant: Optional[str] = Query(None, description="Filter by quadrant: Q1 Q2 Q3 Q4"),
    ticker: Optional[str] = Query(None, description="Filter by ticker"),
    market: Optional[str] = Query(None, description="Filter by market: US CN HK"),
    include_pre_nexus: bool = Query(True, description="Include trades logged before Nexus"),
):
    """
    Reads `{NEXUS_ROOT}/truth/portfolio/trade-outcomes.json`.
    Supports filtering by quadrant, ticker, market, and pre-Nexus flag.
    """
    raw = _read_json(TRUTH_ROOT / "portfolio" / "trade-outcomes.json")
    trades = raw.get("trades", [])

    if quadrant:
        trades = [t for t in trades if t.get("quadrant") == quadrant]
    if ticker:
        trades = [t for t in trades if t.get("ticker", "").upper() == ticker.upper()]
    if market:
        trades = [t for t in trades if t.get("market", "").upper() == market.upper()]
    if not include_pre_nexus:
        trades = [t for t in trades if not t.get("pre_nexus", False)]

    return {"meta": raw.get("_meta", {}), "trades": trades}


@app.get(
    "/api/portfolio/trades.csv",
    tags=["Portfolio"],
    summary="Download trade outcomes as CSV",
    response_class=StreamingResponse,
)
def get_trades_csv():
    """
    Same data as `GET /api/portfolio/trades` but streamed as `text/csv`.
    Useful for importing into Excel / Google Sheets.
    """
    raw = _read_json(TRUTH_ROOT / "portfolio" / "trade-outcomes.json")
    trades = raw.get("trades", [])

    fields = [
        "trade_id", "ticker", "market", "direction",
        "entry_date", "entry_price", "exit_date", "exit_price",
        "quantity", "realized_pnl_usd", "status",
        "quadrant", "compliance_note", "pre_nexus",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for t in trades:
        writer.writerow({k: t.get(k, "") for k in fields})

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=nexus-trades.csv"},
    )


# ---------------------------------------------------------------------------
# Risk
# ---------------------------------------------------------------------------

@app.get(
    "/api/risk/metrics",
    response_model=RiskMetrics,
    tags=["Risk"],
    summary="Computed risk metrics across portfolio and signal bus",
)
def get_risk_metrics():
    """
    Aggregates risk signals from Truth Store, Signal Bus, and trade outcomes.
    All computations are read-only — no writes.
    """
    # Positions
    try:
        pos_raw = _read_json(TRUTH_ROOT / "portfolio" / "positions.json")
        positions = pos_raw.get("positions", [])
    except HTTPException:
        positions = []

    active_longs = [p for p in positions if p.get("status") == "active" and p.get("direction") != "short"]
    active_shorts = [p for p in positions if p.get("status") == "active" and p.get("direction") == "short"]

    # Bear case breach: positions where bear_case_ref contains downside implied > 20%
    # Heuristic: if bear_case_ref string contains "$" and entry_price, compare
    # This is approximate — a full parse would need to resolve the ref string
    bear_breach = 0
    for p in positions:
        bc_ref = p.get("bear_case_ref", "")
        ep = p.get("entry_price")
        if bc_ref and ep and isinstance(ep, (int, float)):
            import re
            prices = re.findall(r"\$(\d+(?:\.\d+)?)", bc_ref)
            if prices:
                try:
                    bear_price = float(prices[0])
                    if (ep - bear_price) / ep > 0.20:
                        bear_breach += 1
                except ValueError:
                    pass

    # Stale truth entries
    now = datetime.now(timezone.utc)
    stale_count = 0
    for fpath in _list_json_files(TRUTH_ROOT / "companies"):
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
            lu = raw.get("last_updated")
            if lu:
                lu_dt = datetime.fromisoformat(lu)
                if lu_dt.tzinfo is None:
                    lu_dt = lu_dt.replace(tzinfo=timezone.utc)
                if (now - lu_dt).days > 30:
                    stale_count += 1
            else:
                stale_count += 1
        except Exception:
            pass

    # Pending signals
    pending_files = _list_json_files(SIGNALS_PENDING)
    pending_count = len([
        p for p in pending_files if not p.name.startswith("_")
    ])

    # Scorecard
    try:
        to_raw = _read_json(TRUTH_ROOT / "portfolio" / "trade-outcomes.json")
        closed = [t for t in to_raw.get("trades", []) if t.get("status") == "closed"]
        q4_count = sum(1 for t in closed if t.get("quadrant") == "Q4")
        q1_count = sum(1 for t in closed if t.get("quadrant") == "Q1")
        total_closed = len(closed)
        q4_pct = round(q4_count / total_closed * 100, 1) if total_closed else None
        q1_pct = round(q1_count / total_closed * 100, 1) if total_closed else None
    except HTTPException:
        q4_pct = q1_pct = None

    return RiskMetrics(
        total_positions=len(positions),
        active_long_count=len(active_longs),
        active_short_count=len(active_shorts),
        bear_case_breach_count=bear_breach,
        stale_truth_count=stale_count,
        pending_signal_count=pending_count,
        quality_alert=pending_count >= 10,
        scorecard_q4_pct=q4_pct,
        scorecard_q1_pct=q1_pct,
        as_of=now,
    )


@app.get(
    "/api/risk/dashboard",
    tags=["Risk"],
    summary="Composite dashboard payload for UI rendering",
)
def get_risk_dashboard():
    """
    Bundles risk metrics + top pending signals + top positions into one
    response — designed to power a single-page risk dashboard with
    one network round-trip.
    """
    metrics = get_risk_metrics()

    # Top 3 pending signals by priority
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sig_files = sorted(
        _list_json_files(SIGNALS_PENDING),
        key=lambda p: priority_order.get(
            _safe_read_priority(p), 99
        ),
    )[:3]
    top_signals = []
    for sf in sig_files:
        try:
            top_signals.append(json.loads(sf.read_text(encoding="utf-8")))
        except Exception:
            pass

    # Active positions (first 5)
    try:
        pos_raw = _read_json(TRUTH_ROOT / "portfolio" / "positions.json")
        top_positions = [
            p for p in pos_raw.get("positions", []) if p.get("status") == "active"
        ][:5]
    except HTTPException:
        top_positions = []

    return {
        "metrics": metrics.model_dump(),
        "top_signals": top_signals,
        "top_positions": top_positions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _safe_read_priority(path: Path) -> str:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw.get("priority", "low")
    except Exception:
        return "low"


# ---------------------------------------------------------------------------
# Signal Bus
# ---------------------------------------------------------------------------

@app.get(
    "/api/signals/pending",
    response_model=SignalListResponse,
    tags=["Signals"],
    summary="List pending signals",
)
def list_pending_signals(
    to: Optional[str] = Query(None, description="Filter by recipient workstream ID"),
    priority: Optional[str] = Query(None, description="Filter by priority: critical high medium low"),
    type: Optional[str] = Query(None, description="Filter by signal type"),
):
    """
    Reads all non-index JSON files from `{NEXUS_ROOT}/signals/pending/`.
    Supports filtering by recipient, priority, and type.
    """
    signals = []
    for fpath in _list_json_files(SIGNALS_PENDING):
        try:
            raw = json.loads(fpath.read_text(encoding="utf-8"))
        except Exception:
            continue

        if to and to not in raw.get("to", []):
            continue
        if priority and raw.get("priority") != priority:
            continue
        if type and raw.get("type") != type:
            continue

        # Normalise field alias "from" → pydantic alias
        if "from" in raw and "from_workstream" not in raw:
            raw["from_workstream"] = raw["from"]

        try:
            signals.append(Signal(**raw))
        except Exception:
            continue

    return SignalListResponse(total=len(signals), signals=signals)


@app.post(
    "/api/signals",
    response_model=Signal,
    status_code=status.HTTP_201_CREATED,
    tags=["Signals"],
    summary="Post a new signal to the bus",
    dependencies=[Depends(_require_write_key)],
)
async def create_signal(body: SignalCreateRequest):
    """
    Creates a new signal JSON in `{NEXUS_ROOT}/signals/pending/`.
    Filename format: `sig-{YYYYMMDD}-{HHMMSS}-{from}-{type}.json`

    Requires `X-API-Key` header with the write key.
    Broadcasts the new signal to WebSocket subscribers on `/ws/signals`.
    """
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    from_id = body.from_workstream.lower().replace(" ", "-")
    sig_id = f"sig-{ts}-{from_id}-{body.type.value}"

    # TTL defaults by priority
    ttl_hours = body.expires_in_hours or {
        "critical": 72, "high": 168, "medium": 336, "low": 720,
    }.get(body.priority.value, 168)

    from datetime import timedelta
    expires_at = now + timedelta(hours=ttl_hours)

    data = {
        "id": sig_id,
        "from": body.from_workstream,
        "to": body.to,
        "priority": body.priority.value,
        "type": body.type.value,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "payload": body.payload.model_dump(exclude_none=True),
        "lifecycle": "pending",
    }

    fpath = SIGNALS_PENDING / f"{sig_id}.json"
    _write_json(fpath, data)

    # Broadcast
    await manager.broadcast("signals", {"event": "new_signal", "signal": data})

    return Signal(**{**data, "from_workstream": data["from"]})


@app.put(
    "/api/signals/{signal_id}/ack",
    response_model=Signal,
    tags=["Signals"],
    summary="Acknowledge (mark as read) a pending signal",
    dependencies=[Depends(_require_write_key)],
)
def ack_signal(signal_id: str, body: SignalAckRequest):
    """
    Marks a signal as `read` by setting `read_by` and `read_at`.
    Signal remains in `pending/` — call `/acted` to complete the lifecycle.

    Requires `X-API-Key` header with the write key.
    """
    fpath = _signal_path(signal_id)
    if fpath is None:
        raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")

    raw = json.loads(fpath.read_text(encoding="utf-8"))
    raw["lifecycle"] = "read"
    raw["read_by"] = body.read_by
    raw["read_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(fpath, raw)

    return Signal(**{**raw, "from_workstream": raw.get("from", "")})


@app.put(
    "/api/signals/{signal_id}/acted",
    response_model=Signal,
    tags=["Signals"],
    summary="Mark a signal as acted on and move to processed/",
    dependencies=[Depends(_require_write_key)],
)
def acted_signal(signal_id: str, body: SignalActedRequest):
    """
    Completes the signal lifecycle:
    1. Sets `lifecycle=acted_on`, `acted_on_at`, `action_result`.
    2. Moves the file from `signals/pending/` → `signals/processed/`.

    Requires `X-API-Key` header with the write key.
    """
    fpath = _signal_path(signal_id)
    if fpath is None:
        raise HTTPException(status_code=404, detail=f"Signal not found: {signal_id}")
    if str(fpath).startswith(str(SIGNALS_PROCESSED)):
        raise HTTPException(status_code=409, detail="Signal already in processed/")

    raw = json.loads(fpath.read_text(encoding="utf-8"))
    raw["lifecycle"] = "acted_on"
    raw["acted_on_at"] = datetime.now(timezone.utc).isoformat()
    raw["action_result"] = body.action_result

    dest = SIGNALS_PROCESSED / fpath.name
    SIGNALS_PROCESSED.mkdir(parents=True, exist_ok=True)
    _write_json(dest, raw)
    fpath.unlink(missing_ok=True)

    return Signal(**{**raw, "from_workstream": raw.get("from", "")})


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@app.get(
    "/api/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="System health check",
)
def health():
    """
    Returns Truth Store file count, pending signal count, and a list of
    stale macro indicators. Does not write anything.
    """
    now = datetime.now(timezone.utc)

    truth_files = len(
        list(TRUTH_ROOT.rglob("*.json"))
    ) if TRUTH_ROOT.exists() else 0

    pending_files = _list_json_files(SIGNALS_PENDING)
    pending_count = len(pending_files)

    processed_count = (
        len(_list_json_files(SIGNALS_PROCESSED))
        if SIGNALS_PROCESSED.exists()
        else 0
    )

    # Stale macro indicators
    stale: List[str] = []
    try:
        macro = _read_json(TRUTH_ROOT / "macro" / "indicators.json")
        for ind in macro.get("indicators", []):
            lr = ind.get("last_refreshed")
            sad = ind.get("stale_after_days", 1)
            if lr is None:
                stale.append(ind.get("entity", "unknown"))
                continue
            try:
                lr_dt = datetime.fromisoformat(lr)
                if lr_dt.tzinfo is None:
                    lr_dt = lr_dt.replace(tzinfo=timezone.utc)
                if (now - lr_dt).days >= sad:
                    stale.append(ind.get("entity", "unknown"))
            except ValueError:
                stale.append(ind.get("entity", "unknown"))
    except HTTPException:
        pass

    overall = "ok"
    if pending_count >= 10:
        overall = "degraded"   # quality_alert threshold
    if not NEXUS_ROOT.exists():
        overall = "error"

    return HealthResponse(
        status=overall,
        version="1.0.0",
        truth_store_files=truth_files,
        signals_pending=pending_count,
        signals_processed=processed_count,
        stale_indicators=stale,
        timestamp=now,
    )


@app.get(
    "/api/sync/bulletin",
    response_model=SyncBulletin,
    tags=["System"],
    summary="Latest Nexus update bulletin",
)
def get_bulletin():
    """
    Reads `{NEXUS_ROOT}/sync/update-bulletin.json` and returns the
    current system version, recent changes, and any migration steps
    external agents need to follow.
    """
    raw = _read_json(SYNC_BULLETIN)
    return SyncBulletin(
        version=raw.get("version", "unknown"),
        released_at=raw.get("released_at"),
        summary=raw.get("summary"),
        files_updated=raw.get("files_updated", []),
        breaking_changes=raw.get("breaking_changes", []),
        migration_steps=raw.get("migration_steps", []),
        raw=raw,
    )


# ---------------------------------------------------------------------------
# WebSocket — Signals
# ---------------------------------------------------------------------------

@app.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    """
    Real-time signal feed. Clients receive a JSON message whenever a new
    signal is posted via `POST /api/signals`.

    Send `{"action": "ping"}` to check liveness; server replies with
    `{"action": "pong"}`.

    No authentication on this channel — signals are filtered by recipient
    on the client side. Deploy behind a reverse proxy with TLS + IP allowlist
    for sensitive environments.
    """
    await manager.connect("signals", websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "ping":
                await websocket.send_json({"action": "pong"})
    except WebSocketDisconnect:
        manager.disconnect("signals", websocket)


# ---------------------------------------------------------------------------
# WebSocket — Prices
# ---------------------------------------------------------------------------

@app.websocket("/ws/prices")
async def ws_prices(websocket: WebSocket):
    """
    Price update feed. External price producers (e.g. a yf polling script)
    publish updates via the `/api/prices/push` admin endpoint; this channel
    fans out to all connected subscribers.

    Message format:
        {"ticker": "NVDA", "price": 132.50, "change_pct": 1.23, "ts": "..."}
    """
    await manager.connect("prices", websocket)
    try:
        while True:
            # Keep connection alive — prices are server-pushed, not request-response
            await asyncio.sleep(30)
            await websocket.send_json({"action": "heartbeat"})
    except WebSocketDisconnect:
        manager.disconnect("prices", websocket)


@app.post(
    "/api/prices/push",
    tags=["System"],
    summary="Push a price update to all /ws/prices subscribers (admin)",
    dependencies=[Depends(_require_admin_key)],
)
async def push_price(
    ticker: str = Query(..., description="Ticker symbol"),
    price: float = Query(..., description="Current price"),
    change_pct: Optional[float] = Query(None, description="% change"),
):
    """
    Used by the `yf` polling script to fan out price ticks to all
    WebSocket price subscribers.

    Requires `X-API-Key` header with the admin key.
    """
    msg = {
        "ticker": ticker,
        "price": price,
        "change_pct": change_pct,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    await manager.broadcast("prices", msg)
    return {"ok": True, "subscribers": len(manager.active.get("prices", []))}


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.exception_handler(404)
async def not_found_handler(request, exc):
    return JSONResponse(
        status_code=404,
        content=APIError(error="not_found", detail=str(exc.detail)).model_dump(),
    )


@app.exception_handler(403)
async def forbidden_handler(request, exc):
    return JSONResponse(
        status_code=403,
        content=APIError(error="forbidden", detail=str(exc.detail)).model_dump(),
    )

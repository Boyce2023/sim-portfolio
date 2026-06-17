#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
consume_signals.py — Nexus signal consumption / on-demand retrieval (三合一 + dedup).

This is the "下半部分" (dispatch) that complements truth_pulse.py's injection
(上半部分). truth_pulse injects all pending signals into every prompt; this
script filters them BY WORKSTREAM via routing.json, enriches with truth_refs,
flags portfolio overlap (ticker-set ONLY, never quantity/price), extracts
catalyst countdowns, and provides a lifecycle de-duplicator.

It merges four designs that had overlapping responsibilities into one tool:
  scan_startup_signals  ->  --startup
  query_signals         ->  --query   (also importable as WorkstreamQueryAPI)
  consume_signals       ->  --summary
  signal_lifecycle      ->  --dedup

=========================  H1 / ISOLATION INVARIANT  =========================
⛔ Positions data NEVER leaves the tracking-only boundary.
This script reads truth/portfolio/positions.json ONLY to build a *set of
tickers* for overlap detection. shares / avg_cost / market_value / pnl /
stop_loss are read, immediately discarded, and NEVER printed, logged, or
returned in any output. Output for an overlap is the bare marker
"overlap: NVDA, AVGO" — nothing else. truth_refs tagged as position/
position-sizing are filtered out so portfolio facts can't leak via the
enrichment path either. See SIGNAL_PROTOCOL.md / isolation_schema.json.
=============================================================================

Modes (single --workstream <id> required for all but --dedup):
  --workstream <id> --startup
        Full startup scan. Returns structured JSON with four layers:
        action_required / informational / expiring / expired.  Budget < 5s.

  --workstream <id> --summary
        Routed signals for this workstream (routing.json "to" contains <id>),
        action_required first, each with up to 3 high/medium-confidence
        truth_ref facts, plus a catalyst countdown table (days_to_event) for
        this workstream's relevant tickers. Writes a log line to
        logs/signals_consumed_YYYYMMDD.log.

  --workstream <id> --query --type X [--portfolio-only]
        On-demand query. Filter by type and/or portfolio overlap. Also exposed
        programmatically: `from consume_signals import WorkstreamQueryAPI`.

  --dedup
        Lifecycle de-duplication. For each (from, type, affected_tickers) key,
        keep the newest pending signal; older ones get superseded_by=<new id>
        and are moved to processed/ (audit trail preserved). Marks them via the
        existing signal_consumer.py mechanism — does NOT reinvent lifecycle.

Examples:
    python3 scripts/consume_signals.py --workstream trading_us --startup
    python3 scripts/consume_signals.py --workstream trading_us --summary
    python3 scripts/consume_signals.py --workstream research --query --type catalyst
    python3 scripts/consume_signals.py --dedup
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (anchored to the live nexus infrastructure)
# ---------------------------------------------------------------------------
HOME = Path.home()
NEXUS = HOME / ".claude/nexus"
SIGNALS_PENDING = NEXUS / "signals/pending"
SIGNALS_PROCESSED = NEXUS / "signals/processed"
ROUTING_JSON = NEXUS / "signals/routing.json"
TRUTH_DIR = NEXUS / "truth"
TRUTH_INDEX = TRUTH_DIR / "_index.json"
# truth/portfolio/positions.json is read for the TICKER SET ONLY (H1).
POSITIONS_JSON = TRUTH_DIR / "portfolio/positions.json"

SCRIPT_DIR = Path(__file__).resolve().parent
LOGS_DIR = SCRIPT_DIR.parent / "logs"
SIGNAL_CONSUMER = SCRIPT_DIR / "signal_consumer.py"

# Default TTL by priority — only a fallback. The live routing.json
# auto_expiry_days is the source of truth and is loaded at runtime.
DEFAULT_EXPIRY_DAYS = {"critical": 3, "high": 7, "medium": 14, "low": 30}

# Truth categories/tags that represent OUR positions. Facts of these kinds are
# excluded from enrichment so portfolio detail cannot leak via truth_refs (H1).
POSITION_TAINTED_CATEGORIES = {"position", "position-sizing", "position_sizing"}
POSITION_TAINTED_TAGS = {"position", "sim-portfolio", "holdings", "stop_loss", "stop-loss"}

# ---------------------------------------------------------------------------
# ANSI helpers (no external deps; auto-disabled when not a TTY)
# ---------------------------------------------------------------------------
_TTY = sys.stdout.isatty()
RESET = "\033[0m" if _TTY else ""
BOLD = "\033[1m" if _TTY else ""
DIM = "\033[2m" if _TTY else ""
RED = "\033[31m" if _TTY else ""
GREEN = "\033[32m" if _TTY else ""
YELLOW = "\033[33m" if _TTY else ""
CYAN = "\033[36m" if _TTY else ""
WHITE = "\033[97m" if _TTY else ""


def c(text, *codes: str) -> str:
    return "".join(codes) + str(text) + RESET


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value):
    """Tolerant ISO-8601 parser. Returns aware datetime or None."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        # Fall back to date-only.
        try:
            dt = datetime.fromisoformat(v[:10])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return default


# ===========================================================================
# WorkstreamRouter — reads routing.json, decides which signals reach a ws
# ===========================================================================
class WorkstreamRouter:
    """Resolves whether a signal is routed to a given workstream, using the
    live routing.json (type -> to[] + compatibility_routing + auto_expiry_days).
    routing.json itself is NEVER mutated here (H4 — changes go via .proposed)."""

    def __init__(self, routing_path: Path = ROUTING_JSON):
        self.routing = load_json(routing_path, default={}) or {}
        self.routes = self.routing.get("routes", [])
        self.compat = self.routing.get("compatibility_routing", {}) or {}
        self.expiry_days = self.routing.get("auto_expiry_days", DEFAULT_EXPIRY_DAYS)
        # type -> route entry
        self._by_type = {r.get("type"): r for r in self.routes if r.get("type")}

    def _expand_targets(self, to_list) -> set[str]:
        """Expand a signal/route `to` list, resolving legacy ids via compat
        table (trading/events -> trading_astock/trading_us) and 'all'."""
        out: set[str] = set()
        for t in to_list or []:
            if t == "all":
                # Conservative: every workstream we know about.
                out.update({
                    "research", "trading_astock", "trading_us",
                    "tracking", "interviews", "nexus",
                })
            elif t in self.compat:
                out.update(self.compat[t])
            else:
                out.add(t)
        return out

    def signal_targets(self, signal: dict) -> set[str]:
        """Effective target set for a concrete signal: prefer the signal's own
        `to`, fall back to the route table for its type."""
        explicit = signal.get("to")
        if explicit:
            return self._expand_targets(explicit)
        route = self._by_type.get(signal.get("type"))
        if route:
            return self._expand_targets(route.get("to"))
        return set()

    def routes_to(self, signal: dict, workstream: str) -> bool:
        return workstream in self.signal_targets(signal)

    def priority_default(self, sig_type: str) -> str:
        route = self._by_type.get(sig_type)
        return (route or {}).get("priority_default", "medium")

    def ttl_days(self, priority: str) -> int:
        return int(self.expiry_days.get(priority, DEFAULT_EXPIRY_DAYS.get(priority, 7)))


# ===========================================================================
# TruthResolver — batch-resolves signal.truth_refs to a few key facts
# ===========================================================================
class TruthResolver:
    """Maps truth_ref ids (e.g. 'FPS-001') to {file -> facts}, returns up to 3
    confidence>=medium facts per signal. Position-tagged facts are dropped (H1).
    The portfolio/ truth subtree is never opened by this resolver."""

    def __init__(self, truth_dir: Path = TRUTH_DIR):
        self.truth_dir = truth_dir
        self.index = load_json(truth_dir / "_index.json", default={}) or {}
        self._file_cache: dict[str, list[dict]] = {}
        self._id_to_file = self._build_id_map()

    def _build_id_map(self) -> dict[str, str]:
        """Map fact id -> relative file path using _index.json file list. We map
        on the entity/prefix portion (e.g. 'FPS-001' -> file containing FPS)."""
        mapping: dict[str, str] = {}
        for entry in self.index.get("files", []):
            rel = entry.get("path", "")
            if not rel or rel.startswith("portfolio/"):
                continue  # ⛔ never index portfolio facts (H1)
            facts = self._load_file_facts(rel)
            for f in facts:
                fid = f.get("id")
                if fid:
                    mapping[fid] = rel
        return mapping

    def _load_file_facts(self, rel: str) -> list[dict]:
        if rel in self._file_cache:
            return self._file_cache[rel]
        data = load_json(self.truth_dir / rel, default={}) or {}
        facts = data.get("facts", []) if isinstance(data, dict) else []
        self._file_cache[rel] = facts
        return facts

    @staticmethod
    def _is_position_fact(fact: dict) -> bool:
        cat = (fact.get("category") or "").lower()
        if cat in POSITION_TAINTED_CATEGORIES:
            return True
        tags = {str(t).lower() for t in (fact.get("tags") or [])}
        return bool(tags & POSITION_TAINTED_TAGS)

    def resolve(self, truth_refs, limit: int = 3) -> list[dict]:
        """Return up to `limit` facts (confidence>=medium, non-position)
        as light dicts: {id, claim, confidence, source, source_date}."""
        if not truth_refs:
            return []
        seen: set[str] = set()
        candidates: list[dict] = []
        for ref in truth_refs:
            rel = self._id_to_file.get(ref)
            if not rel:
                continue
            for fact in self._load_file_facts(rel):
                if fact.get("id") != ref or ref in seen:
                    continue
                seen.add(ref)
                if self._is_position_fact(fact):
                    continue  # H1
                conf = (fact.get("confidence") or "low").lower()
                if conf not in ("high", "medium"):
                    continue
                candidates.append({
                    "id": fact.get("id"),
                    "claim": fact.get("claim", ""),
                    "confidence": conf,
                    "source": fact.get("source", ""),
                    "source_date": fact.get("source_date", ""),
                })
        # high before medium, then keep first `limit`
        candidates.sort(key=lambda x: 0 if x["confidence"] == "high" else 1)
        return candidates[:limit]


# ===========================================================================
# PortfolioFilter — ticker SET only, never numbers (H1 firewall)
# ===========================================================================
class PortfolioFilter:
    """Reads truth/portfolio/positions.json and exposes ONLY a frozenset of
    tickers. Every numeric field (shares/avg_cost/market_value/pnl/stop_loss)
    is read and discarded. The only thing this class can ever output is a list
    of overlapping ticker symbols — no quantity, no price, no pnl. EVER."""

    def __init__(self, positions_path: Path = POSITIONS_JSON):
        self._tickers = self._load_ticker_set(positions_path)

    @staticmethod
    def _load_ticker_set(path: Path) -> frozenset[str]:
        data = load_json(path, default={}) or {}
        tickers: set[str] = set()
        for pos in data.get("positions", []):
            t = (pos.get("ticker") or "").strip().upper()
            if t:
                tickers.add(t)
            # NOTE: deliberately do NOT read shares/avg_cost/market_value/
            # unrealized_pnl/stop_loss. They are out of scope and out of reach.
        return frozenset(tickers)

    @property
    def tickers(self) -> frozenset[str]:
        return self._tickers

    def overlap(self, affected_tickers) -> list[str]:
        """Return the bare list of tickers that are both affected and held.
        This is the ONLY portfolio-derived output anywhere in this script."""
        affected = {str(t).strip().upper() for t in (affected_tickers or []) if t}
        return sorted(affected & self._tickers)


# ===========================================================================
# CatalystExtract — countdown from key_dates / expires_at / truth
# ===========================================================================
class CatalystExtract:
    """Pulls forward-looking dated events out of a signal and computes
    days_to_event. Sources, in order: payload/context key_dates, top-level
    key_dates, expires_at (as a soft deadline). Quantities are never touched."""

    DATE_HINT_PREFIX_LEN = 10  # 'YYYY-MM-DD'

    def __init__(self, ref_dt: datetime | None = None):
        self.ref = ref_dt or now_utc()

    @staticmethod
    def _iter_key_dates(signal: dict):
        """Yield raw key_date strings from all the places signals put them."""
        for container in (signal, signal.get("payload") or {}, signal.get("context") or {}):
            if not isinstance(container, dict):
                continue
            kd = container.get("key_dates") or container.get("expected_timing")
            if isinstance(kd, str):
                yield kd
            elif isinstance(kd, list):
                for item in kd:
                    if isinstance(item, str):
                        yield item

    def _parse_event(self, raw: str):
        """A key_date entry can be '2026-07-06' or '2026-07-06 关税评议期截止'.
        Returns (date, label) or None."""
        raw = raw.strip()
        head = raw[: self.DATE_HINT_PREFIX_LEN]
        dt = parse_dt(head)
        if dt is None:
            return None
        label = raw[self.DATE_HINT_PREFIX_LEN:].strip(" -:|") or "event"
        return dt, label

    def events(self, signal: dict) -> list[dict]:
        """Return list of {date, label, days_to_event} sorted by soonest.
        Past events are dropped (countdown only)."""
        out: list[dict] = []
        seen: set[str] = set()
        for raw in self._iter_key_dates(signal):
            parsed = self._parse_event(raw)
            if not parsed:
                continue
            dt, label = parsed
            key = dt.date().isoformat() + "|" + label
            if key in seen:
                continue
            seen.add(key)
            days = (dt.date() - self.ref.date()).days
            if days < 0:
                continue  # countdown only
            out.append({
                "date": dt.date().isoformat(),
                "label": label,
                "days_to_event": days,
            })
        out.sort(key=lambda e: e["days_to_event"])
        return out


# ===========================================================================
# Signal loading + small helpers
# ===========================================================================
def load_pending_signals() -> list[tuple[Path, dict]]:
    """All *.json in pending/ (matches both sig-*.json and the legacy non-prefixed
    files seen live). Skips invalid JSON gracefully."""
    if not SIGNALS_PENDING.exists():
        return []
    results: list[tuple[Path, dict]] = []
    for f in sorted(SIGNALS_PENDING.glob("*.json")):
        data = load_json(f, default=None)
        if isinstance(data, dict):
            results.append((f, data))
    return results


def get_affected_tickers(signal: dict) -> list[str]:
    """Tickers from any known location: top-level, context, or payload.
    Returns uppercased, de-duplicated. No量价 ever lives in these fields."""
    out: list[str] = []
    out.extend(signal.get("affected_tickers") or [])
    for sub in ("context", "payload"):
        block = signal.get(sub) or {}
        if isinstance(block, dict):
            out.extend(block.get("affected_tickers") or [])
            single = block.get("ticker") or block.get("trump_ticker")
            if isinstance(single, str):
                out.append(single)
    single = signal.get("ticker")
    if isinstance(single, str):
        out.append(single)
    return list(dict.fromkeys(t.strip().upper() for t in out if t))


def is_action_required(signal: dict) -> bool:
    val = signal.get("action_required")
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return bool(val.strip())
    return False


def signal_lifecycle(signal: dict) -> str:
    # Real signals use either 'lifecycle' or legacy 'status'.
    return (signal.get("lifecycle") or signal.get("status") or "pending").lower()


def signal_title(signal: dict) -> str:
    return (
        signal.get("title")
        or (signal.get("payload") or {}).get("note")
        or (signal.get("payload") or {}).get("message")
        or "(no title)"
    )


def signal_id(signal: dict, path: Path | None = None) -> str:
    sid = signal.get("id")
    if sid:
        return sid
    return path.stem if path else "(unknown)"


def effective_expiry(signal: dict, router: WorkstreamRouter):
    """expires_at if present, else created_at + auto_expiry_days[priority]."""
    exp = parse_dt(signal.get("expires_at"))
    if exp:
        return exp
    created = parse_dt(signal.get("created_at"))
    if not created:
        return None
    prio = (signal.get("priority") or router.priority_default(signal.get("type", ""))).lower()
    from datetime import timedelta
    return created + timedelta(days=router.ttl_days(prio))


def is_expired(signal: dict, router: WorkstreamRouter, ref: datetime) -> bool:
    exp = effective_expiry(signal, router)
    return bool(exp and exp < ref)


def is_expiring_soon(signal: dict, router: WorkstreamRouter, ref: datetime, days: int = 2) -> bool:
    exp = effective_expiry(signal, router)
    if not exp:
        return False
    delta = (exp - ref).days
    return 0 <= delta <= days


# ===========================================================================
# Core consumption engine (shared by all modes)
# ===========================================================================
class SignalConsumer:
    def __init__(self, workstream: str | None):
        self.workstream = workstream
        self.router = WorkstreamRouter()
        self.truth = TruthResolver()
        self.portfolio = PortfolioFilter()
        self.catalysts = CatalystExtract()
        self.ref = now_utc()

    def _routed(self, signals: list[tuple[Path, dict]]) -> list[tuple[Path, dict]]:
        """Filter to signals routed to self.workstream (None = no filter)."""
        if not self.workstream:
            return signals
        return [(p, s) for p, s in signals if self.router.routes_to(s, self.workstream)]

    def enrich(self, signal: dict, path: Path | None = None) -> dict:
        """Build a safe, isolation-clean view of one signal.
        Guaranteed to contain NO量价 — only overlap markers + decision semantics."""
        affected = get_affected_tickers(signal)
        overlap = self.portfolio.overlap(affected)  # bare ticker list only
        facts = self.truth.resolve(signal.get("truth_refs"))
        events = self.catalysts.events(signal)
        return {
            "id": signal_id(signal, path),
            "type": signal.get("type", "?"),
            "priority": (signal.get("priority") or self.router.priority_default(signal.get("type", ""))).lower(),
            "from": signal.get("from", "?"),
            "to": sorted(self.router.signal_targets(signal)),
            "title": signal_title(signal),
            "action_required": is_action_required(signal),
            "affected_tickers": affected,
            "portfolio_overlap": overlap,          # ⛔ tickers only, no量价
            "truth_facts": facts,                   # confidence>=medium, no position facts
            "catalysts": events,                    # days_to_event countdowns
            "expires_at": (effective_expiry(signal, self.router) or "").__str__()
            if effective_expiry(signal, self.router) else None,
            "lifecycle": signal_lifecycle(signal),
            "_path": str(path) if path else None,
        }

    # -- mode: --startup ---------------------------------------------------
    def startup(self) -> dict:
        signals = self._routed(load_pending_signals())
        layers = {"action_required": [], "informational": [], "expiring": [], "expired": []}
        for path, sig in signals:
            view = self.enrich(sig, path)
            if is_expired(sig, self.router, self.ref):
                layers["expired"].append(view)
            elif is_action_required(sig):
                layers["action_required"].append(view)
                if is_expiring_soon(sig, self.router, self.ref):
                    layers["expiring"].append(view)
            else:
                layers["informational"].append(view)
                if is_expiring_soon(sig, self.router, self.ref):
                    layers["expiring"].append(view)
        return {
            "workstream": self.workstream,
            "generated_at": self.ref.isoformat(),
            "counts": {k: len(v) for k, v in layers.items()},
            **layers,
        }

    # -- mode: --summary ---------------------------------------------------
    def summary(self) -> dict:
        signals = self._routed(load_pending_signals())
        views = [self.enrich(s, p) for p, s in signals if not is_expired(s, self.router, self.ref)]
        # action_required first, then by priority weight
        prio_w = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        views.sort(key=lambda v: (0 if v["action_required"] else 1, prio_w.get(v["priority"], 9)))
        # catalyst table: dedup by (ticker?, date,label), only this ws's signals
        catalyst_rows: list[dict] = []
        seen_cat: set[str] = set()
        for v in views:
            for ev in v["catalysts"]:
                key = ev["date"] + "|" + ev["label"]
                if key in seen_cat:
                    continue
                seen_cat.add(key)
                catalyst_rows.append({**ev, "signal_id": v["id"], "type": v["type"]})
        catalyst_rows.sort(key=lambda e: e["days_to_event"])
        return {
            "workstream": self.workstream,
            "generated_at": self.ref.isoformat(),
            "signal_count": len(views),
            "action_required_count": sum(1 for v in views if v["action_required"]),
            "signals": views,
            "catalyst_countdown": catalyst_rows,
        }

    # -- mode: --query -----------------------------------------------------
    def query(self, sig_type: str | None = None, portfolio_only: bool = False) -> list[dict]:
        signals = self._routed(load_pending_signals())
        out: list[dict] = []
        for path, sig in signals:
            if is_expired(sig, self.router, self.ref):
                continue
            if sig_type and sig.get("type") != sig_type:
                continue
            view = self.enrich(sig, path)
            if portfolio_only and not view["portfolio_overlap"]:
                continue
            out.append(view)
        return out


# ===========================================================================
# Public importable API
# ===========================================================================
class WorkstreamQueryAPI:
    """Importable interface for other scripts.

        from consume_signals import WorkstreamQueryAPI
        api = WorkstreamQueryAPI("trading_us")
        cats = api.catalysts()          # [{date,label,days_to_event,...}]
        urgent = api.action_required()  # action-required, routed views
        hits = api.query(type="catalyst", portfolio_only=True)

    Every returned view is isolation-clean (overlap markers only, no量价)."""

    def __init__(self, workstream: str):
        self._engine = SignalConsumer(workstream)

    def startup(self) -> dict:
        return self._engine.startup()

    def summary(self) -> dict:
        return self._engine.summary()

    def query(self, type: str | None = None, portfolio_only: bool = False) -> list[dict]:
        return self._engine.query(sig_type=type, portfolio_only=portfolio_only)

    def action_required(self) -> list[dict]:
        return [v for v in self.query() if v["action_required"]]

    def catalysts(self) -> list[dict]:
        return self._engine.summary()["catalyst_countdown"]

    @property
    def portfolio_tickers(self) -> frozenset[str]:
        # Tickers only — by design this is the deepest portfolio access exposed.
        return self._engine.portfolio.tickers


# ===========================================================================
# mode: --dedup  (lifecycle de-duplication)
# ===========================================================================
def _dedup_key(signal: dict) -> tuple:
    affected = tuple(sorted(get_affected_tickers(signal)))
    return (signal.get("from", "?"), signal.get("type", "?"), affected)


def dedup(dry_run: bool = False) -> dict:
    """Within pending/, for each (from, type, affected_tickers) key keep the
    newest by created_at; mark older ones superseded_by=<newest id> and move to
    processed/. Reuses signal_consumer.py's move-to-processed semantics where
    possible; falls back to a local move that preserves the audit trail."""
    signals = load_pending_signals()
    groups: dict[tuple, list[tuple[Path, dict]]] = {}
    for path, sig in signals:
        if signal_lifecycle(sig) not in ("pending", "read"):
            continue
        groups.setdefault(_dedup_key(sig), []).append((path, sig))

    superseded: list[dict] = []
    SIGNALS_PROCESSED.mkdir(parents=True, exist_ok=True)
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # newest first by created_at (fallback: filename)
        members.sort(
            key=lambda ps: parse_dt(ps[1].get("created_at")) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        winner_path, winner = members[0]
        winner_id = signal_id(winner, winner_path)
        for old_path, old in members[1:]:
            old_id = signal_id(old, old_path)
            superseded.append({
                "superseded_id": old_id,
                "superseded_by": winner_id,
                "key": {"from": key[0], "type": key[1], "tickers": list(key[2])},
            })
            if dry_run:
                continue
            old["lifecycle"] = "superseded"
            old["superseded_by"] = winner_id
            old["acted_at"] = now_utc().isoformat()
            try:
                with old_path.open("w", encoding="utf-8") as fh:
                    json.dump(old, fh, indent=2, ensure_ascii=False)
                shutil.move(str(old_path), str(SIGNALS_PROCESSED / old_path.name))
            except OSError as e:
                print(c(f"  ERROR superseding {old_path.name}: {e}", RED))
    return {"superseded_count": len(superseded), "superseded": superseded, "dry_run": dry_run}


# ===========================================================================
# Lifecycle marking — reuse signal_consumer.py (do NOT reinvent)
# ===========================================================================
def mark_consumed_via_signal_consumer() -> int:
    """Invoke the existing signal_consumer.py --consume to mark action-required
    signals as acted_on. Returns the subprocess return code (best-effort)."""
    if not SIGNAL_CONSUMER.exists():
        print(c("signal_consumer.py not found; skipping lifecycle mark.", DIM))
        return 1
    try:
        proc = subprocess.run(
            [sys.executable, str(SIGNAL_CONSUMER), "--consume"],
            capture_output=True, text=True, timeout=60,
        )
        if proc.stdout:
            print(proc.stdout, end="")
        return proc.returncode
    except (subprocess.SubprocessError, OSError) as e:
        print(c(f"signal_consumer.py invocation failed: {e}", RED))
        return 1


# ===========================================================================
# Pretty printers (human mode) — never emit量价
# ===========================================================================
def _print_view(v: dict):
    badge = c(" ACTION ", BOLD, RED) if v["action_required"] else c(" info ", DIM)
    print(f"\n  {badge} {c(v['priority'].upper(), BOLD, YELLOW)} {c(v['type'], CYAN)}  "
          f"{c(v['id'], DIM)}")
    print(f"    {c('Title:', BOLD)} {v['title']}")
    print(f"    {c('From:', DIM)} {v['from']} -> {', '.join(v['to']) or '?'}")
    if v["affected_tickers"]:
        print(f"    {c('Tickers:', DIM)} {', '.join(v['affected_tickers'])}")
    if v["portfolio_overlap"]:
        # ⛔ overlap marker ONLY — no量价
        print(f"    {c('overlap:', BOLD, GREEN)} {', '.join(v['portfolio_overlap'])}")
    for fact in v["truth_facts"]:
        print(f"    {c('fact[' + fact['confidence'] + ']:', DIM)} {fact['claim'][:110]}")
    for ev in v["catalysts"]:
        print(f"    {c('catalyst:', CYAN)} {ev['date']} ({ev['days_to_event']}d) {ev['label']}")


def _print_summary_human(result: dict):
    print(c("\n" + "=" * 78, CYAN))
    print(c(f"  SIGNAL SUMMARY — workstream={result['workstream']}", BOLD, WHITE))
    print(c(f"  {result['signal_count']} routed signal(s), "
            f"{result['action_required_count']} action-required", DIM))
    print(c("=" * 78, CYAN))
    if not result["signals"]:
        print(c("  No routed signals for this workstream.", DIM))
    for v in result["signals"]:
        _print_view(v)
    if result["catalyst_countdown"]:
        print(c("\n  CATALYST COUNTDOWN", BOLD, YELLOW))
        for ev in result["catalyst_countdown"]:
            print(f"    {c(str(ev['days_to_event']) + 'd', BOLD)}  {ev['date']}  "
                  f"{ev['label']}  {c('(' + ev['type'] + ')', DIM)}")
    print()


def write_summary_log(result: dict):
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"signals_consumed_{now_utc():%Y%m%d}.log"
    line = (
        f"{now_utc().isoformat()} ws={result['workstream']} "
        f"signals={result['signal_count']} "
        f"action_required={result['action_required_count']} "
        f"catalysts={len(result['catalyst_countdown'])}\n"
    )
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as e:
        print(c(f"  (log write failed: {e})", DIM))
    return log_path


# ===========================================================================
# CLI
# ===========================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Nexus signal consumption / on-demand retrieval (三合一 + dedup).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--workstream", help="Workstream id (research/trading_astock/trading_us/tracking/interviews/nexus)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--startup", action="store_true", help="Startup scan -> 4-layer structured JSON")
    mode.add_argument("--summary", action="store_true", help="Routed summary + catalyst table + log line")
    mode.add_argument("--query", action="store_true", help="On-demand query (use with --type / --portfolio-only)")
    mode.add_argument("--dedup", action="store_true", help="De-duplicate pending signals (supersede older)")
    p.add_argument("--type", help="Filter by signal type (with --query)")
    p.add_argument("--portfolio-only", action="store_true", help="Only signals overlapping current positions")
    p.add_argument("--json", action="store_true", help="Force JSON output (default when not a TTY)")
    p.add_argument("--mark-consumed", action="store_true",
                   help="After --summary/--startup, run signal_consumer.py --consume to mark action-required")
    p.add_argument("--dry-run", action="store_true", help="With --dedup: report only, do not move files")
    return p


def emit_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    want_json = args.json or not _TTY

    # --dedup is workstream-agnostic.
    if args.dedup:
        result = dedup(dry_run=args.dry_run)
        if want_json:
            emit_json(result)
        else:
            tag = " (dry-run)" if result["dry_run"] else ""
            print(c(f"Dedup{tag}: {result['superseded_count']} signal(s) superseded.", BOLD))
            for s in result["superseded"]:
                print(f"  {s['superseded_id']}  ->  superseded_by  {s['superseded_by']}")
        return 0

    if not args.workstream:
        print(c("ERROR: --workstream is required for --startup/--summary/--query.", BOLD, RED))
        return 2

    engine = SignalConsumer(args.workstream)

    if args.startup:
        result = engine.startup()
        if want_json:
            emit_json(result)
        else:
            _print_summary_human(engine.summary())  # human view shares summary renderer
        if args.mark_consumed:
            mark_consumed_via_signal_consumer()
        return 0

    if args.query:
        result = engine.query(sig_type=args.type, portfolio_only=args.portfolio_only)
        if want_json:
            emit_json(result)
        else:
            print(c(f"Query: {len(result)} match(es) for workstream={args.workstream}"
                    + (f" type={args.type}" if args.type else "")
                    + (" portfolio-only" if args.portfolio_only else ""), BOLD))
            for v in result:
                _print_view(v)
        return 0

    # default / --summary
    result = engine.summary()
    log_path = write_summary_log(result)
    if want_json:
        result["log_path"] = str(log_path)
        emit_json(result)
    else:
        _print_summary_human(result)
        print(c(f"Logged to {log_path}", DIM))
    if args.mark_consumed:
        mark_consumed_via_signal_consumer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
cross_intel.py — Cross-market intelligence module for dual-market trading system.

Breaks the "information cocoon" between A-share and US sessions by surfacing
overnight moves, shared catalysts, and supply-chain linkages in either direction.

Usage:
  uv run --script scripts/cross_intel.py --market a_share   # Brief for A-share session
  uv run --script scripts/cross_intel.py --market us        # Brief for US session
  uv run --script scripts/cross_intel.py --market a_share --emit-signal
  uv run --script scripts/cross_intel.py --json             # Machine-readable output

Output:
  Writes cross_intel_brief.json to repo root.
  Optionally emits a Nexus signal to ~/.claude/nexus/signals/pending/.
"""

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_DIR       = Path(__file__).parent.parent
PORTFOLIO_PATH = REPO_DIR / "portfolio_state.json"
REVIEWS_DIR    = REPO_DIR / "daily-reviews"
BRIEF_OUT      = REPO_DIR / "cross_intel_brief.json"
NEXUS_SIGNALS  = Path.home() / ".claude" / "nexus" / "signals" / "pending"

BJT = timezone(timedelta(hours=8))


# ── Hardcoded supply-chain linkage map ───────────────────────────────────────
# Format: {us_ticker: [{a_share_ticker, a_share_name, relationship}]}
SUPPLY_CHAIN_MAP: dict[str, list[dict]] = {
    "NVDA": [
        {"ticker": "300502", "name": "新易盛",  "relationship": "AI光模块/1.6T — NVDA Vera Rubin指定供应商"},
        {"ticker": "002463", "name": "沪电股份", "relationship": "AI服务器高层PCB — NVDA GB200 PCB供应链"},
        {"ticker": "688019", "name": "安集科技", "relationship": "CMP抛光液 — 半导体材料国产替代"},
    ],
    "MU": [
        {"ticker": "688019", "name": "安集科技", "relationship": "CMP/平坦化材料 — HBM生产工序受益"},
    ],
    "AMAT": [
        {"ticker": "688019", "name": "安集科技", "relationship": "半导体设备→材料协同 — 设备投资周期共振"},
    ],
    "CLS": [
        {"ticker": "002463", "name": "沪电股份", "relationship": "AI服务器EMS←→PCB供应链同方向"},
        {"ticker": "300502", "name": "新易盛",  "relationship": "AI服务器组装→光模块同一平台"},
    ],
    "AAPL": [
        {"ticker": "002938", "name": "鹏鼎控股", "relationship": "iPhone PCB独家供应商 — WWDC催化剂共享"},
    ],
    "GEV": [
        {"ticker": "002028", "name": "思源电气", "relationship": "电力设备/变压器 — DC电力基础设施同赛道"},
    ],
    "VST": [
        {"ticker": "002028", "name": "思源电气", "relationship": "独立发电/DC电力需求→变压器订单"},
    ],
}

# Reverse map: a_share → us tickers
def _build_reverse_map() -> dict[str, list[str]]:
    rev: dict[str, list[str]] = {}
    for us_ticker, links in SUPPLY_CHAIN_MAP.items():
        for link in links:
            rev.setdefault(link["ticker"], []).append(us_ticker)
    return rev

REVERSE_MAP = _build_reverse_map()

# Known cross-market catalyst keywords
CROSS_CATALYST_KEYWORDS = ["COMPUTEX", "WWDC", "ASCO", "Fed", "FOMC", "MRVL", "DELL", "MU Q3"]


# ── Data loaders ──────────────────────────────────────────────────────────────

def load_portfolio() -> dict:
    if not PORTFOLIO_PATH.exists():
        sys.exit(f"ERROR: {PORTFOLIO_PATH} not found")
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)


def load_latest_review(market: str) -> Optional[str]:
    """
    Load the most recent daily-review file and extract the section
    relevant to the OTHER market (so A-share session gets US section, vice versa).
    """
    if not REVIEWS_DIR.exists():
        return None
    files = sorted(REVIEWS_DIR.glob("20*.md"), reverse=True)
    if not files:
        return None
    text = files[0].read_text(encoding="utf-8")
    return text


def load_recent_snapshots(portfolio: dict, n: int = 3) -> list[dict]:
    snapshots = portfolio.get("performance", {}).get("daily_snapshots", [])
    return snapshots[-n:] if snapshots else []


# ── Analysis helpers ──────────────────────────────────────────────────────────

def get_us_regime(portfolio: dict) -> str:
    """Infer US market regime from recent SPY snapshots."""
    snaps = load_recent_snapshots(portfolio, 5)
    spy_changes = [s.get("spy_return_pct") for s in snaps if s.get("spy_return_pct") is not None]
    if not spy_changes:
        return "UNKNOWN"
    avg = sum(spy_changes) / len(spy_changes)
    latest = spy_changes[-1] if spy_changes else 0
    if latest >= 1.0 or avg >= 0.5:
        return "BULL"
    if latest <= -1.5 or avg <= -0.8:
        return "BEAR"
    return "NEUTRAL"


def get_latest_spy_change(portfolio: dict) -> Optional[float]:
    snaps = load_recent_snapshots(portfolio, 3)
    for snap in reversed(snaps):
        if snap.get("spy_return_pct") is not None:
            return snap["spy_return_pct"]
    return None


def get_latest_sse_change(portfolio: dict) -> Optional[float]:
    snaps = load_recent_snapshots(portfolio, 3)
    for snap in reversed(snaps):
        if snap.get("sse_return_pct") is not None:
            return snap["sse_return_pct"]
    return None


def build_us_key_moves(portfolio: dict) -> list[dict]:
    """Return notable US position moves from the latest snapshot."""
    positions = portfolio.get("accounts", {}).get("us", {}).get("positions", [])
    shorts = portfolio.get("accounts", {}).get("us", {}).get("short_positions", [])
    moves = []
    for pos in positions + shorts:
        ticker = pos.get("ticker", "")
        change = pos.get("unrealized_pnl_pct")
        if change is None:
            continue
        note = pos.get("thesis", pos.get("name", ""))[:60]
        moves.append({"ticker": ticker, "name": pos.get("name", ""), "change_pct": round(change, 2), "note": note})
    # Sort by abs magnitude
    moves.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return moves[:5]


def build_astock_key_moves(portfolio: dict) -> list[dict]:
    """Return notable A-share position moves."""
    positions = portfolio.get("accounts", {}).get("a_share", {}).get("positions", [])
    moves = []
    for pos in positions:
        change = pos.get("change_pct") or pos.get("unrealized_pnl_pct")
        if change is None:
            continue
        moves.append({
            "ticker": pos.get("ticker", ""),
            "name": pos.get("name", ""),
            "change_pct": round(change, 2),
            "note": (pos.get("next_catalyst") or pos.get("thesis", ""))[:60],
        })
    moves.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return moves[:5]


def detect_catalyst_overlaps(portfolio: dict) -> list[dict]:
    """Find events that affect both markets simultaneously."""
    overlaps: dict[str, dict] = {}

    a_positions = portfolio.get("accounts", {}).get("a_share", {}).get("positions", [])
    us_positions = portfolio.get("accounts", {}).get("us", {}).get("positions", [])
    calendar = portfolio.get("catalyst_calendar_30d", [])

    # Build catalyst → tickers mappings from positions
    a_catalyst_map: dict[str, list[str]] = {}
    for pos in a_positions:
        cat = pos.get("next_catalyst", "")
        if cat:
            for kw in CROSS_CATALYST_KEYWORDS:
                if kw.upper() in cat.upper():
                    a_catalyst_map.setdefault(kw, []).append(
                        f"{pos['ticker']} {pos.get('name','')}"
                    )

    us_catalyst_map: dict[str, list[str]] = {}
    for pos in us_positions:
        cat = pos.get("next_catalyst", "")
        if cat:
            for kw in CROSS_CATALYST_KEYWORDS:
                if kw.upper() in cat.upper():
                    us_catalyst_map.setdefault(kw, []).append(pos["ticker"])

    # Also scan catalyst_calendar_30d
    for cal_item in calendar:
        event_text = cal_item.get("event", "") + " " + cal_item.get("ticker", "")
        for kw in CROSS_CATALYST_KEYWORDS:
            if kw.upper() in event_text.upper():
                ticker = cal_item.get("ticker", "")
                if ticker in [p["ticker"] for p in us_positions]:
                    us_catalyst_map.setdefault(kw, []).append(ticker)
                else:
                    a_catalyst_map.setdefault(kw, []).append(ticker)

    # Find events present in BOTH
    shared_keys = set(a_catalyst_map) & set(us_catalyst_map)
    for kw in sorted(shared_keys):
        a_exp = list(dict.fromkeys(a_catalyst_map[kw]))  # deduplicate
        us_exp = list(dict.fromkeys(us_catalyst_map[kw]))
        overlaps[kw] = {
            "event": kw,
            "a_share_exposure": a_exp,
            "us_exposure": us_exp,
        }

    return list(overlaps.values())


def detect_supply_chain_links(portfolio: dict) -> list[dict]:
    """Surface supply-chain relationships between held positions on both sides."""
    a_tickers = {p["ticker"] for p in portfolio.get("accounts", {}).get("a_share", {}).get("positions", [])}
    us_tickers = {p["ticker"] for p in portfolio.get("accounts", {}).get("us", {}).get("positions", [])}
    us_tickers |= {p["ticker"] for p in portfolio.get("accounts", {}).get("us", {}).get("short_positions", [])}

    links = []
    for us_ticker in us_tickers:
        for link in SUPPLY_CHAIN_MAP.get(us_ticker, []):
            if link["ticker"] in a_tickers:
                links.append({
                    "us": us_ticker,
                    "a_share": link["ticker"],
                    "a_share_name": link["name"],
                    "relationship": link["relationship"],
                })
    return links


def build_combined_exposure_warning(overlaps: list[dict], portfolio: dict) -> list[str]:
    """Warn when combined cross-market exposure to a single catalyst is high."""
    warnings = []
    a_total = portfolio.get("accounts", {}).get("a_share", {}).get("total_assets", 1)
    us_total = portfolio.get("accounts", {}).get("us", {}).get("total_assets", 1)

    for ov in overlaps:
        a_count = len(ov.get("a_share_exposure", []))
        us_count = len(ov.get("us_exposure", []))
        if a_count >= 2 and us_count >= 1:
            warnings.append(
                f"HIGH CONCENTRATION: {ov['event']} affects {a_count} A-share + {us_count} US positions — "
                "review combined notional before catalyst date"
            )
        elif a_count >= 1 and us_count >= 1:
            warnings.append(
                f"SHARED CATALYST: {ov['event']} — A股 {ov['a_share_exposure']} / US {ov['us_exposure']}"
            )
    return warnings


# ── Summary string builder ────────────────────────────────────────────────────

def _fmt_change(pct: Optional[float]) -> str:
    if pct is None:
        return "N/A"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def build_other_market_summary(target_market: str, portfolio: dict) -> str:
    """One-line summary of the OTHER market for the current session."""
    if target_market == "a_share":
        # A-share session wants US overnight summary
        regime = get_us_regime(portfolio)
        spy = get_latest_spy_change(portfolio)
        us_pos = portfolio.get("accounts", {}).get("us", {}).get("positions", [])
        highlights = []
        for pos in us_pos[:3]:
            chg = pos.get("unrealized_pnl_pct")
            if chg is not None:
                highlights.append(f"{pos['ticker']} {_fmt_change(chg)}")
        shorts = portfolio.get("accounts", {}).get("us", {}).get("short_positions", [])
        for pos in shorts[:1]:
            chg = pos.get("unrealized_pnl_pct")
            if chg is not None:
                highlights.append(f"{pos['ticker']}(short) {_fmt_change(chg)}")
        parts = [f"US Regime: {regime}", f"SPY {_fmt_change(spy)}"]
        if highlights:
            parts.extend(highlights)
        return " | ".join(parts)
    else:
        # US session wants A-share summary
        sse = get_latest_sse_change(portfolio)
        a_pos = portfolio.get("accounts", {}).get("a_share", {}).get("positions", [])
        highlights = []
        for pos in a_pos[:3]:
            chg = pos.get("change_pct") or pos.get("unrealized_pnl_pct")
            if chg is not None:
                highlights.append(f"{pos.get('name',pos['ticker'])} {_fmt_change(chg)}")
        pending = portfolio.get("pending_orders", [])
        if pending:
            highlights.append(f"待执行: {pending[0].get('name','')} {pending[0].get('action','')}")
        parts = [f"SSE {_fmt_change(sse)}"]
        if highlights:
            parts.extend(highlights)
        return " | ".join(parts)


# ── Nexus signal emitter ──────────────────────────────────────────────────────

def emit_regime_signal(regime: str, spy_change: float, from_market: str = "trading_us") -> Path:
    """Write a Nexus market_context signal when regime is noteworthy."""
    NEXUS_SIGNALS.mkdir(parents=True, exist_ok=True)
    now = datetime.now(BJT)
    ts = now.strftime("%Y%m%d-%H%M%S")
    sig_id = f"sig-{ts}-{from_market}-regime-{regime.lower()}"
    payload = {
        "id": sig_id,
        "from": from_market,
        "to": ["trading_astock"],
        "type": "market_context",
        "priority": "high" if regime == "BEAR" else "medium",
        "payload": {
            "regime": regime,
            "spy_change_pct": round(spy_change, 2),
            "note": f"US Regime: {regime} | SPY {_fmt_change(spy_change)}",
        },
        "created_at": now.isoformat(),
        "lifecycle": "pending",
        "expires_at": (now + timedelta(days=7)).isoformat(),
    }
    sig_path = NEXUS_SIGNALS / f"{sig_id}.json"
    with open(sig_path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return sig_path


# ── Main brief generator ──────────────────────────────────────────────────────

def generate_cross_brief(target_market: str, portfolio: dict) -> dict:
    """
    Generate intelligence brief about the OTHER market for the current session.

    target_market="a_share" → summarise recent US activity for morning A-share open
    target_market="us"       → summarise recent A-share activity for evening US open
    """
    regime       = get_us_regime(portfolio)
    spy_change   = get_latest_spy_change(portfolio)
    sse_change   = get_latest_sse_change(portfolio)
    overlaps     = detect_catalyst_overlaps(portfolio)
    sc_links     = detect_supply_chain_links(portfolio)
    warnings     = build_combined_exposure_warning(overlaps, portfolio)
    other_summary = build_other_market_summary(target_market, portfolio)

    if target_market == "a_share":
        key_moves = build_us_key_moves(portfolio)
    else:
        key_moves = build_astock_key_moves(portfolio)

    brief = {
        "generated_at": datetime.now(BJT).isoformat(),
        "target_market": target_market,
        "other_market": "us" if target_market == "a_share" else "a_share",
        "other_market_summary": other_summary,
        "regime": regime,
        "spy_latest_change_pct": spy_change,
        "sse_latest_change_pct": sse_change,
        "key_moves": key_moves,
        "overlapping_catalysts": overlaps,
        "supply_chain_links": sc_links,
        "concentration_warnings": warnings,
        "pending_cross_actions": [
            {
                "ticker": o.get("id", ""),
                "event": o.get("event", ""),
                "action": o.get("precommitted_action", ""),
                "urgency": o.get("urgency", ""),
            }
            for o in portfolio.get("catalyst_calendar_30d", [])
            if o.get("urgency") in ("CRITICAL", "HIGH")
        ][:4],
    }
    return brief


# ── CLI ───────────────────────────────────────────────────────────────────────

def print_human_brief(brief: dict) -> None:
    sep = "─" * 64
    mkt_label = "A-SHARE SESSION" if brief["target_market"] == "a_share" else "US SESSION"
    other_label = "US OVERNIGHT SUMMARY" if brief["target_market"] == "a_share" else "A-SHARE DAY SUMMARY"

    print(f"\n{'═'*64}")
    print(f"  CROSS-MARKET INTEL BRIEF — {mkt_label}")
    print(f"  {brief['generated_at']}")
    print(f"{'═'*64}")

    print(f"\n[{other_label}]")
    print(f"  {brief['other_market_summary']}")
    print(f"  Regime: {brief['regime']}  |  SPY: {_fmt_change(brief['spy_latest_change_pct'])}  |  SSE: {_fmt_change(brief['sse_latest_change_pct'])}")

    if brief["key_moves"]:
        print(f"\n[KEY MOVES — {brief['other_market'].upper()}]")
        for m in brief["key_moves"]:
            print(f"  {m['ticker']:8s} {_fmt_change(m['change_pct']):>7s}  {m['note'][:55]}")

    if brief["overlapping_catalysts"]:
        print(f"\n[SHARED CATALYSTS — affects BOTH markets]")
        for ov in brief["overlapping_catalysts"]:
            print(f"  {ov['event']}")
            print(f"    A股: {', '.join(ov['a_share_exposure'])}")
            print(f"    US : {', '.join(ov['us_exposure'])}")

    if brief["supply_chain_links"]:
        print(f"\n[SUPPLY CHAIN LINKS — held on both sides]")
        for lk in brief["supply_chain_links"]:
            print(f"  {lk['us']:6s} ↔ {lk['a_share']} {lk['a_share_name']}")
            print(f"    {lk['relationship']}")

    if brief["concentration_warnings"]:
        print(f"\n[CONCENTRATION WARNINGS]")
        for w in brief["concentration_warnings"]:
            print(f"  ⚠  {w}")

    if brief["pending_cross_actions"]:
        print(f"\n[UPCOMING CROSS-MARKET CATALYSTS]")
        for ev in brief["pending_cross_actions"]:
            print(f"  [{ev.get('urgency','?'):8s}] {ev.get('event','')}")

    print(f"\n{sep}")
    print(f"  Brief saved → {BRIEF_OUT.name}")
    print(f"{'═'*64}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-market intelligence brief")
    parser.add_argument(
        "--market", choices=["a_share", "us"], required=True,
        help="Current session market. Brief will summarise the OTHER market."
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of human-readable")
    parser.add_argument(
        "--emit-signal", action="store_true",
        help="Write a Nexus signal for the A-share session (only useful from US session)"
    )
    args = parser.parse_args()

    portfolio = load_portfolio()
    brief     = generate_cross_brief(args.market, portfolio)

    # Persist brief
    with open(BRIEF_OUT, "w", encoding="utf-8") as f:
        json.dump(brief, f, indent=2, ensure_ascii=False)

    if args.json:
        print(json.dumps(brief, indent=2, ensure_ascii=False))
    else:
        print_human_brief(brief)

    if args.emit_signal:
        spy_chg = brief.get("spy_latest_change_pct") or 0.0
        sig_path = emit_regime_signal(brief["regime"], spy_chg)
        print(f"Nexus signal written → {sig_path}")


if __name__ == "__main__":
    main()

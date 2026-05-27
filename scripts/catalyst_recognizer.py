#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""
catalyst_recognizer.py — Intelligent Catalyst Recognition Engine

Reads latest_news.json + portfolio_state.json + pending_actions.json and produces
actionable alerts when news matches held positions, watchlist, or If-Then pre-commitments.

Usage:
    uv run --script scripts/catalyst_recognizer.py            # process + write catalyst_alerts.json
    uv run --script scripts/catalyst_recognizer.py --dry-run  # print matches, don't write
"""

import json
import sys
import re
from pathlib import Path
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.parent
PORTFOLIO_FILE = BASE_DIR / "portfolio_state.json"
NEWS_FILE = BASE_DIR / "latest_news.json"
PENDING_FILE = BASE_DIR / "pending_actions.json"
OUTPUT_FILE = BASE_DIR / "catalyst_alerts.json"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    if not path.exists():
        print(f"[WARN] {path.name} not found — skipping", file=sys.stderr)
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Position extraction
# ---------------------------------------------------------------------------

def extract_positions(portfolio: dict) -> list[dict]:
    """Return flat list of all held long positions (both accounts)."""
    positions = []
    accounts = portfolio.get("accounts", {})

    # A-share longs
    for pos in accounts.get("a_share", {}).get("positions", []):
        positions.append({
            "ticker": pos.get("ticker", ""),
            "name": pos.get("name", ""),
            "account": "a_share",
            "market": "cn",
            "next_catalyst": pos.get("next_catalyst", ""),
            "catalyst_action": pos.get("catalyst_action", ""),
            "current_pct": pos.get("portfolio_pct", 0) * 100,
            "thesis": pos.get("thesis", ""),
        })

    # US longs
    for pos in accounts.get("us", {}).get("positions", []):
        positions.append({
            "ticker": pos.get("ticker", ""),
            "name": pos.get("name", ""),
            "account": "us",
            "market": "us",
            "next_catalyst": pos.get("next_catalyst", ""),
            "catalyst_action": pos.get("catalyst_action", ""),
            "current_pct": pos.get("portfolio_pct", 0) * 100,
            "thesis": pos.get("thesis", ""),
        })

    # US shorts
    for pos in accounts.get("us", {}).get("short_positions", []):
        positions.append({
            "ticker": pos.get("ticker", ""),
            "name": pos.get("name", ""),
            "account": "us_short",
            "market": "us",
            "next_catalyst": pos.get("next_catalyst", ""),
            "catalyst_action": pos.get("catalyst_action", ""),
            "current_pct": abs(pos.get("market_value", 0)) / max(
                accounts.get("us", {}).get("total_assets", 1), 1
            ) * 100,
            "thesis": pos.get("thesis", ""),
        })

    return positions


def extract_watchlist_tickers(portfolio: dict) -> dict[str, str]:
    """Return {ticker: name} for catalyst_calendar tickers not already in positions."""
    result = {}
    for item in portfolio.get("catalyst_calendar_30d", []):
        ticker = item.get("ticker", "").strip()
        if ticker and ticker != "COMPUTEX":  # COMPUTEX is an event, not a ticker
            result[ticker] = ticker
    return result


def extract_pending_actions(pending: dict) -> list[dict]:
    """Return only 'pending' status actions (not resolved/completed)."""
    actions = []
    for item in pending.get("pending", []):
        if item.get("status", "") == "pending":
            actions.append(item)
    return actions


# ---------------------------------------------------------------------------
# News extraction
# ---------------------------------------------------------------------------

def flatten_news(news_data: dict) -> list[dict]:
    """
    latest_news.json has structure: {tickers: {TICKER: {items: [...], ...}}}
    Flatten into a list of news items, deduplicating by link.
    """
    seen_links = set()
    items = []
    for ticker_key, ticker_data in news_data.get("tickers", {}).items():
        ticker_meta = {
            "source_ticker": ticker_key,
            "source_ticker_name": ticker_data.get("name", ticker_key),
            "source_next_catalyst": ticker_data.get("next_catalyst", ""),
        }
        for item in ticker_data.get("items", []):
            link = item.get("link", "")
            if link in seen_links:
                continue
            seen_links.add(link)
            items.append({
                "headline": item.get("title", ""),
                "source": item.get("publisher", ""),
                "time": item.get("published", ""),
                "link": link,
                "urgency": item.get("urgency", "normal"),
                **ticker_meta,
            })
    return items


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------

# A-share company name fragments for fuzzy matching
CN_FUZZY_MAP = {
    "思源": "002028",
    "鹏鼎": "002938",
    "安集": "688019",
    "恒瑞": "600276",
    "沪电": "002463",
    "新易盛": "300502",
}


def _ticker_keywords(position: dict) -> list[str]:
    """Build keyword list for a position (ticker + name fragments)."""
    keywords = [position["ticker"].upper()]
    name = position.get("name", "")
    if name:
        keywords.append(name)
        # Add first 2 chars of Chinese name as fuzzy keyword
        if len(name) >= 2:
            keywords.append(name[:2])
    return keywords


def _text_for_matching(news_item: dict) -> str:
    """Combine headline and source ticker name for keyword matching."""
    return (
        news_item.get("headline", "")
        + " "
        + news_item.get("source_ticker_name", "")
        + " "
        + news_item.get("source_next_catalyst", "")
    ).upper()


def _cn_ticker_in_text(text: str, position: dict) -> bool:
    """A-share fuzzy match: '思源' matches '思源电气 002028'."""
    ticker = position["ticker"]
    name = position.get("name", "")
    # Direct ticker match
    if ticker in text:
        return True
    # Full name match
    if name and name.upper() in text:
        return True
    # Fuzzy 2-char fragment match
    for fragment, mapped_ticker in CN_FUZZY_MAP.items():
        if mapped_ticker == ticker and fragment in text:
            return True
    return False


def match_position_to_news(news_item: dict, position: dict) -> bool:
    """Return True if this news item matches this position."""
    text = _text_for_matching(news_item)
    ticker = position["ticker"].upper()
    market = position["market"]

    if market == "us":
        # US: direct ticker match
        return bool(re.search(r"\b" + re.escape(ticker) + r"\b", text))
    else:
        # A-share: fuzzy match
        return _cn_ticker_in_text(text, position)


def match_watchlist_to_news(news_item: dict, watchlist: dict[str, str]) -> list[str]:
    """Return list of watchlist tickers matching this news item."""
    text = _text_for_matching(news_item)
    matched = []
    for ticker, name in watchlist.items():
        if re.search(r"\b" + re.escape(ticker.upper()) + r"\b", text):
            matched.append(ticker)
    return matched


def detect_catalyst_match(news_item: dict, position: dict) -> str | None:
    """
    Check if news headline contains keywords from the position's next_catalyst.
    Returns a description string if matched, else None.
    """
    next_cat = position.get("next_catalyst", "")
    if not next_cat:
        return None

    headline = news_item.get("headline", "").upper()
    # Extract meaningful words (≥4 chars) from the catalyst description
    cat_words = [
        w.upper() for w in re.findall(r"[A-Za-z一-鿿]{3,}", next_cat)
        if len(w) >= 3
    ]
    # Common stopwords to skip
    stopwords = {"THE", "AND", "FOR", "FROM", "WITH", "THAT", "THIS", "WILL", "ARE", "HAS"}
    cat_words = [w for w in cat_words if w not in stopwords]

    if not cat_words:
        return None

    matched_words = [w for w in cat_words if w in headline]
    # Require at least 1 keyword match OR source_ticker aligns
    if matched_words or position["ticker"].upper() == news_item.get("source_ticker", "").upper():
        return f"{next_cat} (next_catalyst for {position['ticker']})"
    return None


def detect_if_then_trigger(news_item: dict, pending_actions: list[dict]) -> tuple[str | None, str | None]:
    """
    Check if news satisfies any pending action's trigger condition.
    Returns (action_id, description) or (None, None).
    """
    headline = news_item.get("headline", "").upper()
    for action in pending_actions:
        condition = action.get("trigger_condition", "")
        pre_commitment = action.get("pre_commitment", "")
        if not condition:
            continue

        # Extract keywords from condition
        keywords = [
            w.upper() for w in re.findall(r"[A-Za-z一-鿿]{4,}", condition)
        ]
        stopwords = {"FROM", "THAT", "THIS", "WILL", "HAVE", "AFTER", "WHEN", "UPON"}
        keywords = [w for w in keywords if w not in stopwords]

        if not keywords:
            continue

        # Also check ticker match
        ticker = action.get("ticker", "")
        ticker_hit = ticker and ticker.upper() in headline

        matched = [k for k in keywords[:8] if k in headline]  # check first 8 keywords
        if len(matched) >= 2 or ticker_hit:
            desc = f"[{action['id']}] {action.get('name', ticker)}: {pre_commitment[:120]}"
            return action["id"], desc

    return None, None


# ---------------------------------------------------------------------------
# Urgency logic
# ---------------------------------------------------------------------------

def compute_urgency(
    news_item: dict,
    matched_positions: list[dict],
    if_then_triggered: str | None,
) -> str:
    base_urgency = news_item.get("urgency", "normal")

    # If it matches a held position + is breaking → critical
    if matched_positions and base_urgency in ("breaking", "high"):
        return "critical"
    # If-Then trigger always → critical
    if if_then_triggered:
        return "critical"
    # Matched position with normal urgency → important
    if matched_positions:
        return "important"
    return base_urgency


def build_recommended_action(
    matched_positions: list[dict],
    catalyst_match: str | None,
    if_then_triggered: str | None,
) -> str:
    if if_then_triggered:
        return f"If-Then pre-commitment triggered: review and execute action {if_then_triggered}"
    if catalyst_match and matched_positions:
        tickers = ", ".join(p["ticker"] for p in matched_positions)
        return f"Review {tickers} position — catalyst materializing: {catalyst_match.split('(')[0].strip()}"
    if matched_positions:
        tickers = ", ".join(p["ticker"] for p in matched_positions)
        return f"Monitor {tickers} — news coverage detected"
    return "Watchlist match — no immediate action required"


def infer_markets(matched_positions: list[dict], matched_watchlist: list[str]) -> list[str]:
    markets = set()
    for p in matched_positions:
        if p["account"] == "a_share":
            markets.add("cn")
        else:
            markets.add("us")
    # Watchlist items default to 'us' unless obvious
    if matched_watchlist:
        markets.add("us")
    return sorted(markets) if markets else ["us"]


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process(dry_run: bool = False) -> None:
    # Load data
    portfolio = load_json(PORTFOLIO_FILE)
    news_data = load_json(NEWS_FILE)
    pending_data = load_json(PENDING_FILE)

    positions = extract_positions(portfolio)
    watchlist = extract_watchlist_tickers(portfolio)
    pending_actions = extract_pending_actions(pending_data)
    all_news = flatten_news(news_data)

    alerts = []
    total_news = len(all_news)

    for news_item in all_news:
        # 1. Match positions
        matched_positions = []
        for pos in positions:
            if match_position_to_news(news_item, pos):
                matched_positions.append({
                    "ticker": pos["ticker"],
                    "name": pos.get("name", ""),
                    "account": pos["account"],
                    "current_pct": round(pos["current_pct"], 1),
                })

        # 2. Match watchlist
        matched_watchlist = match_watchlist_to_news(news_item, watchlist)

        # Skip if no matches at all
        if not matched_positions and not matched_watchlist:
            continue

        # 3. Catalyst match detection (only for held positions)
        catalyst_match = None
        if matched_positions:
            for pos in positions:
                if any(m["ticker"] == pos["ticker"] for m in matched_positions):
                    result = detect_catalyst_match(news_item, pos)
                    if result:
                        catalyst_match = result
                        break

        # 4. If-Then trigger check
        if_then_id, if_then_desc = detect_if_then_trigger(news_item, pending_actions)

        # 5. Compute urgency
        urgency = compute_urgency(news_item, matched_positions, if_then_id)

        # 6. Build recommended action
        recommended_action = build_recommended_action(
            matched_positions, catalyst_match, if_then_id
        )

        alert = {
            "news_headline": news_item.get("headline", ""),
            "news_source": news_item.get("source", ""),
            "news_time": news_item.get("time", ""),
            "news_link": news_item.get("link", ""),
            "matched_positions": matched_positions,
            "matched_watchlist": matched_watchlist,
            "catalyst_match": catalyst_match,
            "if_then_triggered": if_then_desc,
            "urgency": urgency,
            "recommended_action": recommended_action,
            "markets": infer_markets(matched_positions, matched_watchlist),
        }
        alerts.append(alert)

    # Sort: critical first, then by time desc
    urgency_order = {"critical": 0, "breaking": 1, "high": 2, "important": 3, "normal": 4}
    alerts.sort(key=lambda a: (urgency_order.get(a["urgency"], 9), a["news_time"] or ""))
    # Re-reverse time within same urgency level (newest first)
    alerts.sort(key=lambda a: (urgency_order.get(a["urgency"], 9), -(ord(a["news_time"][0]) if a["news_time"] else 0)))

    # Build summary
    summary = {
        "total_news": total_news,
        "matched": len(alerts),
        "critical": sum(1 for a in alerts if a["urgency"] == "critical"),
        "breaking": sum(1 for a in alerts if a["urgency"] == "breaking"),
        "high": sum(1 for a in alerts if a["urgency"] == "high"),
        "important": sum(1 for a in alerts if a["urgency"] == "important"),
        "catalyst_matches": sum(1 for a in alerts if a["catalyst_match"]),
        "if_then_triggered": sum(1 for a in alerts if a["if_then_triggered"]),
    }

    output = {
        "generated_at": datetime.now(tz=timezone.utc).astimezone().isoformat(),
        "news_source_file": NEWS_FILE.name,
        "portfolio_source_file": PORTFOLIO_FILE.name,
        "alerts": alerts,
        "summary": summary,
    }

    if dry_run:
        _print_dry_run(output)
    else:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"[catalyst_recognizer] Written {len(alerts)} alerts to {OUTPUT_FILE}")
        _print_summary(summary)


def _print_summary(summary: dict) -> None:
    print(
        f"  Total news: {summary['total_news']} | "
        f"Matched: {summary['matched']} | "
        f"Critical: {summary['critical']} | "
        f"Catalyst hits: {summary['catalyst_matches']} | "
        f"If-Then triggers: {summary['if_then_triggered']}"
    )


def _print_dry_run(output: dict) -> None:
    summary = output["summary"]
    print(f"\n=== CATALYST RECOGNIZER DRY RUN ===")
    print(f"Generated at: {output['generated_at']}")
    _print_summary(summary)
    print()

    if not output["alerts"]:
        print("No matches found.")
        return

    for i, alert in enumerate(output["alerts"], 1):
        urgency_label = alert["urgency"].upper()
        print(f"[{urgency_label}] #{i} — {alert['news_headline']}")
        print(f"         Source: {alert['news_source']} | Time: {alert['news_time']}")
        if alert["matched_positions"]:
            pos_str = ", ".join(
                f"{p['ticker']}({p['account']},{p['current_pct']}%)"
                for p in alert["matched_positions"]
            )
            print(f"         Positions: {pos_str}")
        if alert["matched_watchlist"]:
            print(f"         Watchlist: {', '.join(alert['matched_watchlist'])}")
        if alert["catalyst_match"]:
            print(f"         Catalyst: {alert['catalyst_match']}")
        if alert["if_then_triggered"]:
            print(f"         If-Then: {alert['if_then_triggered']}")
        print(f"         Action: {alert['recommended_action']}")
        print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    process(dry_run=dry_run)

# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""
新闻扫描脚本 — Claude模拟盘
为持仓标的提供新闻查询模板。远程agent负责实际新闻搜索(WebSearch)，
此脚本生成结构化输出模板供agent填充。

用法:
  uv run --script scripts/news_scan.py
  python scripts/news_scan.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = REPO_ROOT / "portfolio_state.json"
NEWS_OUTPUT = REPO_ROOT / "latest_news.json"

TZ_BEIJING = timezone(timedelta(hours=8))

# OTC ticker mapping
YF_TICKER_MAP = {"SPUT": "SRUUF"}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def cn_ticker_to_yf(ticker: str) -> str:
    return ticker + ".SS" if ticker.startswith("6") else ticker + ".SZ"


def us_ticker_to_yf(ticker: str) -> str:
    return YF_TICKER_MAP.get(ticker.upper(), ticker.upper())


def get_news_template(ticker: str, name: str, is_cn: bool) -> dict:
    """
    Generate a news query template for the remote agent.
    The agent should fill in actual news via WebSearch.
    """
    if is_cn:
        search_terms = [
            f"{name} {ticker} 最新消息",
            f"{name} 股票 财经新闻",
            f"{ticker} 公告",
        ]
    else:
        search_terms = [
            f"{ticker} stock news",
            f"{name} latest earnings analyst",
            f"{ticker} price target",
        ]

    return {
        "ticker": ticker,
        "name": name,
        "market": "CN" if is_cn else "US",
        "search_terms": search_terms,
        "items": [],  # Agent fills this via WebSearch
        "scanned_at": None,  # Agent fills this
        "status": "pending",
    }


def scan_news_yf(tickers_with_meta: list[dict], max_per_ticker: int = 3) -> dict:
    """
    Try fetching news from yfinance as best-effort.
    Returns dict keyed by original ticker.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {}

    results = {}
    for item in tickers_with_meta:
        ticker = item["ticker"]
        yf_sym = item["yf_sym"]
        try:
            t = yf.Ticker(yf_sym)
            news = t.news or []
            items = []
            for n in news[:max_per_ticker]:
                content = n.get("content", {})
                items.append({
                    "title": content.get("title", n.get("title", "")),
                    "publisher": content.get("provider", {}).get("displayName", n.get("publisher", "")),
                    "link": content.get("canonicalUrl", {}).get("url", n.get("link", "")),
                    "published": content.get("pubDate", n.get("providerPublishTime", "")),
                })
            results[ticker] = {
                **item,
                "items": items,
                "scanned_at": datetime.now(TZ_BEIJING).isoformat(),
                "status": "ok" if items else "no_news",
            }
        except Exception as e:
            results[ticker] = {
                **item,
                "items": [],
                "error": str(e),
                "status": "error",
            }
    return results


# ─── Atomic Save ──────────────────────────────────────────────────────────────

def save_atomic(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".news_tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ─── Main ─────────────────────────────────────────────────────────────────────

def build_ticker_list(state: dict) -> list[dict]:
    """Build list of all tickers with metadata for news scanning."""
    items = []

    for pos in state["accounts"]["us"]["positions"]:
        if pos.get("instrument_type") == "call_option":
            continue
        ticker = pos["ticker"]
        items.append({
            "ticker": ticker,
            "yf_sym": us_ticker_to_yf(ticker),
            "name": pos.get("name", ticker),
            "market": "US",
            "is_cn": False,
            "thesis": pos.get("thesis", ""),
            "next_catalyst": pos.get("next_catalyst", ""),
        })

    for pos in state["accounts"]["a_share"]["positions"]:
        ticker = pos["ticker"]
        items.append({
            "ticker": ticker,
            "yf_sym": cn_ticker_to_yf(ticker),
            "name": pos.get("name", ticker),
            "market": "CN",
            "is_cn": True,
            "thesis": pos.get("thesis", ""),
            "next_catalyst": pos.get("next_catalyst", ""),
        })

    return items


def main() -> int:
    if not PORTFOLIO_PATH.exists():
        print(f"[ERROR] portfolio_state.json not found at {PORTFOLIO_PATH}", file=sys.stderr)
        return 1

    try:
        with open(PORTFOLIO_PATH, encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load portfolio_state.json: {e}", file=sys.stderr)
        return 1

    ticker_list = build_ticker_list(state)
    print(f"扫描新闻: {len(ticker_list)} 个持仓标的...")

    # Try yfinance news (best-effort)
    news_results = scan_news_yf(ticker_list)

    # Print results
    print()
    for item in ticker_list:
        ticker = item["ticker"]
        result = news_results.get(ticker, {})
        status = result.get("status", "pending")
        items = result.get("items", [])
        name = item.get("name", ticker)
        mkt = item.get("market", "")

        print(f"--- [{mkt}] {ticker} {name} (status: {status}) ---")
        if items:
            for n in items:
                print(f"  • {n.get('title', '(无标题)')}")
                if n.get("publisher"):
                    print(f"    来源: {n['publisher']}")
        elif status == "pending":
            print(f"  待agent通过WebSearch搜索: {item.get('search_terms', [])}")
        elif result.get("error"):
            print(f"  ERROR: {result['error']}")
        else:
            print("  暂无新闻")
        print()

    # Save output
    output = {
        "fetched_at": datetime.now(TZ_BEIJING).isoformat(),
        "tickers": news_results if news_results else {
            item["ticker"]: {**item, "items": [], "status": "pending"}
            for item in ticker_list
        },
        "agent_instructions": (
            "上方 'search_terms' 是建议的搜索词。"
            "请用 WebSearch 搜索每个标的的最新新闻，"
            "将结果填入对应 ticker 的 items 字段。"
        ),
    }

    try:
        save_atomic(output, NEWS_OUTPUT)
        print(f"[OK] 新闻数据已保存到 {NEWS_OUTPUT}")
    except Exception as e:
        print(f"[ERROR] 保存失败: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40"]
# ///
"""Scan recent news for portfolio holdings. Used by remote agent."""

import json
import sys
import yfinance as yf
from datetime import datetime

def scan_news(tickers: list[str], max_per_ticker: int = 3) -> dict:
    results = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            news = t.news or []
            results[ticker] = [
                {
                    "title": item.get("title", ""),
                    "publisher": item.get("publisher", ""),
                    "link": item.get("link", ""),
                    "published": item.get("providerPublishTime", ""),
                }
                for item in news[:max_per_ticker]
            ]
        except Exception as e:
            results[ticker] = [{"error": str(e)}]
    return results


if __name__ == "__main__":
    with open("portfolio_state.json") as f:
        state = json.load(f)

    us_tickers = [p["ticker"] for p in state["accounts"]["us"]["positions"]
                  if p.get("instrument_type") != "call_option"]
    cn_tickers_yf = []
    for p in state["accounts"]["a_share"]["positions"]:
        t = p["ticker"]
        suffix = ".SS" if t.startswith("6") else ".SZ"
        cn_tickers_yf.append(t + suffix)

    all_tickers = us_tickers + cn_tickers_yf
    print(f"Scanning news for {len(all_tickers)} tickers...")

    news = scan_news(all_tickers)
    for ticker, items in news.items():
        print(f"\n--- {ticker} ---")
        for item in items:
            if "error" in item:
                print(f"  ERROR: {item['error']}")
            else:
                print(f"  {item['title']} ({item['publisher']})")

    with open("latest_news.json", "w") as f:
        json.dump(news, f, indent=2, ensure_ascii=False)
    print(f"\nNews saved to latest_news.json")

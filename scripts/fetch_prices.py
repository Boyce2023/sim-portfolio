# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "requests>=2.31"]
# ///
"""Fetch latest prices for portfolio holdings. Used by remote agent."""

import json
import sys
import yfinance as yf
from datetime import datetime

def fetch_prices(tickers: list[str]) -> dict:
    results = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            results[ticker] = {
                "price": round(float(info.last_price), 2) if info.last_price else None,
                "prev_close": round(float(info.previous_close), 2) if info.previous_close else None,
                "change_pct": round((float(info.last_price) / float(info.previous_close) - 1) * 100, 2)
                    if info.last_price and info.previous_close else None,
                "market_cap": int(info.market_cap) if hasattr(info, 'market_cap') and info.market_cap else None,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            results[ticker] = {"error": str(e), "price": None}
    return results


def fetch_cn_prices(tickers: list[str]) -> dict:
    results = {}
    for ticker in tickers:
        try:
            suffix = ".SS" if ticker.startswith("6") else ".SZ"
            yf_ticker = ticker + suffix
            t = yf.Ticker(yf_ticker)
            info = t.fast_info
            results[ticker] = {
                "price": round(float(info.last_price), 2) if info.last_price else None,
                "prev_close": round(float(info.previous_close), 2) if info.previous_close else None,
                "change_pct": round((float(info.last_price) / float(info.previous_close) - 1) * 100, 2)
                    if info.last_price and info.previous_close else None,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            results[ticker] = {"error": str(e), "price": None}
    return results


if __name__ == "__main__":
    with open("portfolio_state.json") as f:
        state = json.load(f)

    us_tickers = [p["ticker"] for p in state["accounts"]["us"]["positions"]
                  if p.get("instrument_type") != "call_option"]
    cn_tickers = [p["ticker"] for p in state["accounts"]["a_share"]["positions"]]

    print("=== US Prices ===")
    us_prices = fetch_prices(us_tickers)
    for t, d in us_prices.items():
        if d.get("price"):
            print(f"  {t}: ${d['price']} ({d['change_pct']:+.2f}%)")
        else:
            print(f"  {t}: ERROR - {d.get('error', 'no data')}")

    print("\n=== A-Share Prices ===")
    cn_prices = fetch_cn_prices(cn_tickers)
    for t, d in cn_prices.items():
        if d.get("price"):
            print(f"  {t}: ¥{d['price']} ({d['change_pct']:+.2f}%)")
        else:
            print(f"  {t}: ERROR - {d.get('error', 'no data')}")

    all_prices = {"us": us_prices, "cn": cn_prices, "fetched_at": datetime.now().isoformat()}
    with open("latest_prices.json", "w") as f:
        json.dump(all_prices, f, indent=2, ensure_ascii=False)
    print(f"\nPrices saved to latest_prices.json")

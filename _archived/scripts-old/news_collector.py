# /// script
# requires-python = ">=3.11"
# dependencies = ["feedparser"]
# ///
"""
Multi-source news collection engine — Claude模拟盘
Three-layer architecture:
  Layer 1: Google News RSS + CNBC/Reuters RSS (5-15min delay)
  Layer 2: 财联社 CLS telegraph API (1-5min delay, primary for A-shares)
  Layer 3: Placeholder interface for CDP deep scraping (manual via web-access skill)

Usage:
  uv run --script scripts/news_collector.py              # collect all sources
  uv run --script scripts/news_collector.py --source rss  # RSS only
  uv run --script scripts/news_collector.py --source cls  # 财联社 only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PORTFOLIO_PATH = REPO_ROOT / "portfolio_state.json"
NEWS_OUTPUT = REPO_ROOT / "latest_news.json"

TZ_BEIJING = timezone(timedelta(hours=8))
REQUEST_TIMEOUT = 10  # seconds
MAX_ITEMS = 200

# ─── Breaking / urgency keywords ──────────────────────────────────────────────
BREAKING_KEYWORDS_CN = ["突发", "紧急", "停牌", "涨停", "跌停", "制裁", "重大", "退市"]
BREAKING_KEYWORDS_EN = ["breaking", "halt", "fda approval", "sanction", "emergency",
                         "recall", "bankruptcy", "merger", "acquisition"]
IMPORTANT_KEYWORDS_CN = ["业绩", "财报", "公告", "降息", "降准", "利好", "利空", "监管",
                          "中标", "获批", "诉讼", "重组"]
IMPORTANT_KEYWORDS_EN = ["earnings", "beat", "miss", "guidance", "upgrade", "downgrade",
                          "analyst", "price target", "ipo", "dividend"]


# ─── Portfolio loading ─────────────────────────────────────────────────────────

def load_portfolio(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_tickers(state: dict) -> dict[str, dict]:
    """
    Return {ticker: {name, market, is_cn, search_terms}} for all active positions.
    Includes both long and short positions.
    """
    tickers: dict[str, dict] = {}

    for pos in state["accounts"]["us"].get("positions", []):
        if pos.get("instrument_type") == "call_option":
            continue
        ticker = pos["ticker"].upper()
        name = pos.get("name", ticker)
        tickers[ticker] = {
            "name": name,
            "market": "US",
            "is_cn": False,
            "search_terms": [f"{ticker} stock", f"{name} earnings", f"{ticker} news"],
        }

    for pos in state["accounts"]["us"].get("short_positions", []):
        ticker = pos["ticker"].upper()
        name = pos.get("name", ticker)
        tickers[ticker] = {
            "name": name,
            "market": "US",
            "is_cn": False,
            "search_terms": [f"{ticker} stock", f"{name} earnings", f"{ticker} news"],
        }

    for pos in state["accounts"]["a_share"].get("positions", []):
        ticker = pos["ticker"]
        name = pos.get("name", ticker)
        tickers[ticker] = {
            "name": name,
            "market": "CN",
            "is_cn": True,
            "search_terms": [f"{name}", f"{name} {ticker}", f"{ticker} 公告"],
        }

    return tickers


# ─── Urgency classification ───────────────────────────────────────────────────

def classify_urgency(headline: str, summary: str, held_tickers: dict[str, dict]) -> str:
    text = (headline + " " + (summary or "")).lower()

    # Check breaking keywords
    for kw in BREAKING_KEYWORDS_CN + BREAKING_KEYWORDS_EN:
        if kw in text:
            return "breaking"

    # Check if mentions a held ticker name directly
    for ticker, meta in held_tickers.items():
        name = meta.get("name", "")
        if ticker.lower() in text or (name and name in text):
            return "important"

    # Check major index moves pattern (e.g. "+3%", "-2.5%")
    import re
    if re.search(r"[+\-][2-9]\d*\.?\d*\s*%", headline):
        return "important"

    # Check important keywords
    for kw in IMPORTANT_KEYWORDS_CN + IMPORTANT_KEYWORDS_EN:
        if kw in text:
            return "important"

    return "routine"


def infer_affected_markets(headline: str, summary: str, source: str) -> list[str]:
    text = (headline + " " + (summary or "")).lower()
    markets = []
    cn_signals = ["a股", "沪深", "港股", "人民币", "央行", "证监会", "上交所", "深交所",
                  "沪指", "创业板", "北向"]
    us_signals = ["nasdaq", "nyse", "s&p", "dow", "federal reserve", "fed", "sec",
                  "wall street", "earnings per share"]
    if source in ("cls", "eastmoney"):
        markets.append("a_share")
    for sig in cn_signals:
        if sig in text:
            if "a_share" not in markets:
                markets.append("a_share")
            break
    for sig in us_signals:
        if sig in text:
            if "us" not in markets:
                markets.append("us")
            break
    if not markets:
        markets = ["a_share"] if source in ("cls", "eastmoney") else ["us"]
    return markets


# ─── HTTP helper ──────────────────────────────────────────────────────────────

def http_get(url: str, headers: dict | None = None, timeout: int = REQUEST_TIMEOUT) -> bytes:
    req = Request(url)
    req.add_header("User-Agent",
                   "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36")
    req.add_header("Accept", "application/json, text/html, application/xml, */*")
    req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.8")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ─── Layer 1: RSS / Google News ───────────────────────────────────────────────

def parse_rss_feed(xml_bytes: bytes, source_label: str,
                   held_tickers: dict[str, dict]) -> list[dict]:
    """Parse RSS XML and return normalized news items."""
    items = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return items

    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # Standard RSS 2.0
    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        pub_el = item.find("pubDate")

        headline = title_el.text.strip() if title_el is not None and title_el.text else ""
        url = link_el.text.strip() if link_el is not None and link_el.text else ""
        summary = desc_el.text.strip() if desc_el is not None and desc_el.text else ""
        pub_raw = pub_el.text.strip() if pub_el is not None and pub_el.text else ""

        # Strip HTML tags from summary
        import re
        summary = re.sub(r"<[^>]+>", "", summary)[:400]

        timestamp = parse_rss_date(pub_raw)

        if not headline or not url:
            continue

        urgency = classify_urgency(headline, summary, held_tickers)
        markets = infer_affected_markets(headline, summary, source_label)

        items.append({
            "timestamp": timestamp,
            "source": source_label,
            "headline": headline,
            "summary": summary,
            "tickers": extract_mentioned_tickers(headline + " " + summary, held_tickers),
            "url": url,
            "urgency": urgency,
            "markets_affected": markets,
        })

    return items


def parse_rss_date(raw: str) -> str:
    """Parse RFC 822 date string into ISO 8601 with Beijing timezone."""
    if not raw:
        return datetime.now(TZ_BEIJING).isoformat()
    import email.utils
    try:
        ts = email.utils.parsedate_to_datetime(raw)
        return ts.astimezone(TZ_BEIJING).isoformat()
    except Exception:
        return datetime.now(TZ_BEIJING).isoformat()


def extract_mentioned_tickers(text: str, held_tickers: dict[str, dict]) -> list[str]:
    """Return list of held tickers mentioned in text."""
    mentioned = []
    text_lower = text.lower()
    for ticker, meta in held_tickers.items():
        name = meta.get("name", "")
        if ticker.lower() in text_lower or (name and name in text):
            mentioned.append(ticker)
    return mentioned


def fetch_google_news_rss(ticker_meta: dict, is_cn: bool) -> tuple[str, str]:
    """Return (url, query) for Google News RSS for a given ticker."""
    if is_cn:
        name = ticker_meta["name"]
        query = quote(name)
        url = f"https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    else:
        ticker = ticker_meta.get("ticker_key", "")
        name = ticker_meta["name"]
        query = quote(f"{ticker} stock")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    return url, query


GENERAL_RSS_FEEDS = [
    ("cnbc_markets", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("reuters_business", "https://feeds.reuters.com/reuters/businessNews"),
]


def collect_rss(held_tickers: dict[str, dict], verbose: bool = True) -> list[dict]:
    """Layer 1: Collect news from RSS / Google News."""
    all_items: list[dict] = []
    seen_urls: set[str] = set()

    # Per-ticker Google News RSS
    for ticker_key, meta in held_tickers.items():
        meta_with_key = {**meta, "ticker_key": ticker_key}
        url, query = fetch_google_news_rss(meta_with_key, meta["is_cn"])
        source_label = "google_news_cn" if meta["is_cn"] else "google_news_us"
        try:
            raw = http_get(url)
            items = parse_rss_feed(raw, source_label, held_tickers)
            new_count = 0
            for item in items:
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    all_items.append(item)
                    new_count += 1
            if verbose:
                print(f"  [RSS] {ticker_key} ({meta['name']}): {new_count} items")
        except (URLError, OSError, Exception) as e:
            if verbose:
                print(f"  [RSS] {ticker_key}: FAILED — {e}")

    # General market RSS feeds
    for feed_name, feed_url in GENERAL_RSS_FEEDS:
        try:
            raw = http_get(feed_url)
            items = parse_rss_feed(raw, feed_name, held_tickers)
            new_count = 0
            for item in items:
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    all_items.append(item)
                    new_count += 1
            if verbose:
                print(f"  [RSS] {feed_name}: {new_count} items")
        except (URLError, OSError, Exception) as e:
            if verbose:
                print(f"  [RSS] {feed_name}: FAILED — {e}")

    return all_items


# ─── Layer 2: Chinese financial APIs ─────────────────────────────────────────

CLS_TELEGRAPH_URL = "https://www.cls.cn/api/telegraph/list"
CLS_PARAMS = "app=CailianpressWeb&os=web&sv=8.4.6"


def fetch_cls_telegraph(held_tickers: dict[str, dict],
                        verbose: bool = True) -> list[dict]:
    """
    财联社 7x24 电报 API.
    Returns normalized news items.
    """
    url = f"{CLS_TELEGRAPH_URL}?{CLS_PARAMS}&refresh_type=1&last_time=0"
    items: list[dict] = []

    try:
        raw = http_get(url, headers={
            "Referer": "https://www.cls.cn/telegraph",
            "Origin": "https://www.cls.cn",
        })
        data = json.loads(raw.decode("utf-8"))
    except (URLError, OSError, json.JSONDecodeError, Exception) as e:
        if verbose:
            print(f"  [CLS] 财联社 API: FAILED — {e}")
        return items

    telegraphs = data.get("data", {})
    if isinstance(telegraphs, dict):
        telegraphs = telegraphs.get("telegram_list", telegraphs.get("roll_data", []))
    if not isinstance(telegraphs, list):
        if verbose:
            print(f"  [CLS] 财联社: unexpected response shape, keys={list(data.get('data', {}).keys()) if isinstance(data.get('data'), dict) else type(telegraphs)}")
        return items

    for entry in telegraphs:
        content = entry.get("content", entry.get("brief", ""))
        title = entry.get("title", content[:80] if content else "")
        ctime = entry.get("ctime", entry.get("time", 0))
        article_id = entry.get("id", entry.get("article_id", ""))
        url_link = f"https://www.cls.cn/telegraph/{article_id}" if article_id else "https://www.cls.cn/telegraph"

        try:
            ts = datetime.fromtimestamp(int(ctime), tz=TZ_BEIJING).isoformat()
        except (ValueError, TypeError, OSError):
            ts = datetime.now(TZ_BEIJING).isoformat()

        if not title and not content:
            continue

        headline = title or content[:100]
        summary = content[:400] if content != headline else ""

        urgency = classify_urgency(headline, summary, held_tickers)
        mentioned = extract_mentioned_tickers(headline + " " + summary, held_tickers)

        items.append({
            "timestamp": ts,
            "source": "cls",
            "headline": headline,
            "summary": summary,
            "tickers": mentioned,
            "url": url_link,
            "urgency": urgency,
            "markets_affected": ["a_share"],
        })

    if verbose:
        print(f"  [CLS] 财联社: {len(items)} items")

    return items


def fetch_eastmoney_news(held_tickers: dict[str, dict],
                         verbose: bool = True) -> list[dict]:
    """
    东方财富 快讯 API (public endpoint, best-effort).
    Falls back silently if endpoint changes.
    """
    # Public fast-news endpoint (may require user-agent spoofing)
    url = ("https://np-anotice-stock.eastmoney.com/api/security/ann"
           "?sr=-1&page_size=20&page_index=1&ann_type=A&client_source=web")
    items: list[dict] = []

    try:
        raw = http_get(url, headers={
            "Referer": "https://www.eastmoney.com/",
            "Origin": "https://www.eastmoney.com",
        })
        data = json.loads(raw.decode("utf-8"))
    except (URLError, OSError, json.JSONDecodeError, Exception) as e:
        if verbose:
            print(f"  [EASTMONEY] 东方财富: FAILED — {e}")
        return items

    announcements = data.get("data", {})
    if isinstance(announcements, dict):
        announcements = announcements.get("list", [])
    if not isinstance(announcements, list):
        if verbose:
            print(f"  [EASTMONEY] 东方财富: unexpected shape")
        return items

    for entry in announcements:
        title = entry.get("NOTICE_TITLE", entry.get("title", ""))
        stock_code = entry.get("SECURITY_CODE", entry.get("code", ""))
        stock_name = entry.get("SECURITY_NAME_ABBR", entry.get("name", ""))
        notice_time = entry.get("NOTICE_DATE", entry.get("time", ""))
        art_code = entry.get("ART_CODE", entry.get("id", ""))
        url_link = (f"https://data.eastmoney.com/notices/detail/{stock_code}/{art_code}.html"
                    if stock_code and art_code else "https://www.eastmoney.com/")

        ts = datetime.now(TZ_BEIJING).isoformat()
        if notice_time:
            try:
                # Format like "2026-05-27 15:00:00" or "20260527"
                if len(str(notice_time)) == 8:
                    dt = datetime.strptime(str(notice_time), "%Y%m%d")
                else:
                    dt = datetime.fromisoformat(str(notice_time))
                ts = dt.replace(tzinfo=TZ_BEIJING).isoformat()
            except ValueError:
                pass

        if not title:
            continue

        headline = f"[{stock_name or stock_code}] {title}" if stock_name or stock_code else title
        summary = ""

        tickers = []
        if stock_code and stock_code in held_tickers:
            tickers.append(stock_code)
        urgency = classify_urgency(headline, summary, held_tickers)
        if tickers:
            urgency = max(urgency, "important",
                          key=lambda x: {"breaking": 2, "important": 1, "routine": 0}[x])

        items.append({
            "timestamp": ts,
            "source": "eastmoney",
            "headline": headline,
            "summary": summary,
            "tickers": tickers,
            "url": url_link,
            "urgency": urgency,
            "markets_affected": ["a_share"],
        })

    if verbose:
        print(f"  [EASTMONEY] 东方财富: {len(items)} items")

    return items


# ─── Layer 3: Deep scraping placeholder ───────────────────────────────────────

def deep_scrape(url: str) -> dict:
    """
    TODO: Implement browser-based deep scraping via the web-access skill.
    This function is intentionally left as a placeholder. Call it manually
    from the web-access skill when needed for paywalled or JS-rendered pages.

    Expected return format:
    {
        "timestamp": "<ISO8601>",
        "source": "deep_scrape",
        "headline": "...",
        "summary": "...",
        "tickers": [],
        "url": url,
        "urgency": "routine",
        "markets_affected": [],
    }
    """
    raise NotImplementedError(
        "deep_scrape() is a placeholder. "
        "Invoke the web-access skill manually for browser-based scraping."
    )


# ─── Dedup + sort + trim ──────────────────────────────────────────────────────

def dedup_and_sort(items: list[dict], max_items: int = MAX_ITEMS) -> list[dict]:
    """Dedup by URL, sort newest first, keep top max_items."""
    seen: set[str] = set()
    unique: list[dict] = []
    for item in items:
        url = item.get("url", "")
        if url and url in seen:
            continue
        seen.add(url)
        unique.append(item)

    # Sort by timestamp descending (ISO strings sort correctly)
    unique.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return unique[:max_items]


# ─── Atomic save ──────────────────────────────────────────────────────────────

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


# ─── Summary stats ────────────────────────────────────────────────────────────

def print_summary(items: list[dict], held_tickers: dict[str, dict]) -> None:
    breaking = [i for i in items if i["urgency"] == "breaking"]
    important = [i for i in items if i["urgency"] == "important"]
    routine = [i for i in items if i["urgency"] == "routine"]

    sources: dict[str, int] = {}
    for item in items:
        sources[item["source"]] = sources.get(item["source"], 0) + 1

    print(f"\n{'=' * 60}")
    print(f"新闻收集完成: {len(items)} 条 (保留最新 {MAX_ITEMS} 条)")
    print(f"  突发 (breaking):  {len(breaking)}")
    print(f"  重要 (important): {len(important)}")
    print(f"  常规 (routine):   {len(routine)}")
    print(f"\n来源分布:")
    for src, cnt in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"  {src}: {cnt}")

    # Show breaking items
    if breaking:
        print(f"\n突发新闻:")
        for item in breaking[:5]:
            ts = item["timestamp"][:16].replace("T", " ")
            print(f"  [{ts}] {item['headline'][:80]}")
            if item["tickers"]:
                print(f"          -> 涉及持仓: {', '.join(item['tickers'])}")

    # Show items affecting held tickers
    held_relevant = [i for i in important if i.get("tickers")]
    if held_relevant:
        print(f"\n涉及持仓的重要新闻:")
        for item in held_relevant[:5]:
            ts = item["timestamp"][:16].replace("T", " ")
            print(f"  [{ts}] [{', '.join(item['tickers'])}] {item['headline'][:70]}")
    print(f"{'=' * 60}\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="多源新闻收集引擎 — Claude模拟盘",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=["all", "rss", "cls", "eastmoney"],
        default="all",
        help="数据源 (default: all)",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="减少输出",
    )
    args = parser.parse_args()

    verbose = not args.quiet

    # Load portfolio
    if not PORTFOLIO_PATH.exists():
        print(f"[ERROR] portfolio_state.json not found: {PORTFOLIO_PATH}", file=sys.stderr)
        return 1

    try:
        state = load_portfolio(PORTFOLIO_PATH)
    except Exception as e:
        print(f"[ERROR] Failed to load portfolio_state.json: {e}", file=sys.stderr)
        return 1

    held_tickers = extract_tickers(state)

    if verbose:
        print(f"监控标的: {len(held_tickers)} 个持仓")
        cn_count = sum(1 for m in held_tickers.values() if m["is_cn"])
        us_count = len(held_tickers) - cn_count
        print(f"  A股: {cn_count} 个  |  美股: {us_count} 个")
        print(f"  标的: {', '.join(held_tickers.keys())}\n")

    all_items: list[dict] = []

    # Layer 1: RSS
    if args.source in ("all", "rss"):
        if verbose:
            print("=== Layer 1: RSS / Google News ===")
        rss_items = collect_rss(held_tickers, verbose=verbose)
        all_items.extend(rss_items)
        if verbose:
            print(f"  Layer 1 小计: {len(rss_items)} 条\n")

    # Layer 2a: 财联社
    if args.source in ("all", "cls"):
        if verbose:
            print("=== Layer 2a: 财联社 CLS 电报 ===")
        cls_items = fetch_cls_telegraph(held_tickers, verbose=verbose)
        all_items.extend(cls_items)
        if verbose:
            print(f"  Layer 2a 小计: {len(cls_items)} 条\n")

    # Layer 2b: 东方财富
    if args.source in ("all", "eastmoney"):
        if verbose:
            print("=== Layer 2b: 东方财富公告 ===")
        em_items = fetch_eastmoney_news(held_tickers, verbose=verbose)
        all_items.extend(em_items)
        if verbose:
            print(f"  Layer 2b 小计: {len(em_items)} 条\n")

    # Dedup, sort, trim
    final_items = dedup_and_sort(all_items)

    # Build output
    output = {
        "collected_at": datetime.now(TZ_BEIJING).isoformat(),
        "source_filter": args.source,
        "tickers_monitored": list(held_tickers.keys()),
        "total_count": len(final_items),
        "breaking_count": sum(1 for i in final_items if i["urgency"] == "breaking"),
        "important_count": sum(1 for i in final_items if i["urgency"] == "important"),
        "items": final_items,
    }

    # Save
    try:
        save_atomic(output, NEWS_OUTPUT)
    except Exception as e:
        print(f"[ERROR] 保存失败: {e}", file=sys.stderr)
        return 1

    if verbose:
        print_summary(final_items, held_tickers)
        print(f"[OK] 新闻已写入: {NEWS_OUTPUT}")
    else:
        print(f"[OK] {len(final_items)} items → {NEWS_OUTPUT}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

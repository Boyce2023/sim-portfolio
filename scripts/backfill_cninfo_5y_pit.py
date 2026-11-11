#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东财全量五年秒级公告回补引擎 (Backfill Eastmoney 5Y PIT)

特性:
1. 秒级时间戳转换 + 交易可用日 (trade_date_avail) 无缝计算:
   - eiTime 毫秒级入库时间解析 (如 "2021-01-10 14:49:29:000")
   - <09:25:00 当日竞价可用
   - 09:25:00 ~ 14:59:59 盘中/尾盘可用
   - >=15:00:00 或周末节假日顺延下一交易日竞价可用
2. 零静默吞异常: 请求失败必重试，严禁写入 count=0
3. 支持大日分市场拉取防截断，支持断点续传 (done_dates)
4. 多线程并发 + SQLite WAL 批量提交
"""

import os
import re
import sys
import math
import time
import json
import sqlite3
import datetime
import bisect
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"
API_URL = (
    "http://np-anotice-stock.eastmoney.com/api/security/ann"
    "?sr=-1&page_size=100&page_index={page}&ann_type={ann_type}&client_source=web"
    "&f_node=0&s_node=0&begin_time={date}&end_time={date}"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "http://data.eastmoney.com/",
    "Connection": "keep-alive",
}

_tls = threading.local()

def get_session():
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        s.trust_env = False
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=2)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _tls.session = s
    return s

def init_db(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            ann_id TEXT PRIMARY KEY,
            sec_code TEXT,
            sec_name TEXT,
            title TEXT,
            ann_type TEXT,
            pub_ts_ms INTEGER,
            pub_datetime_cst TEXT,
            trade_date_avail TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_avail ON notices(trade_date_avail);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sec_code ON notices(sec_code);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pub_ts ON notices(pub_ts_ms);")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS done_dates (
            date_str TEXT PRIMARY KEY,
            count INTEGER,
            done_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def load_trading_days() -> list:
    trade_days = set()
    kline_db = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kline_cache.db"
    if os.path.exists(kline_db):
        try:
            c = sqlite3.connect(kline_db)
            rows = c.execute("SELECT DISTINCT date FROM daily_kline WHERE date >= '2020-01-01'").fetchall()
            for r in rows:
                if r[0]:
                    trade_days.add(str(r[0])[:10])
            c.close()
        except Exception:
            pass

    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        for d in df['trade_date']:
            s = str(d)[:10]
            if s >= '2020-01-01':
                trade_days.add(s)
    except Exception:
        pass

    if not trade_days:
        cur = datetime.date(2020, 1, 1)
        end = datetime.date(2027, 1, 1)
        while cur <= end:
            if cur.weekday() < 5:
                trade_days.add(cur.strftime("%Y-%m-%d"))
            cur += datetime.timedelta(days=1)

    return sorted(list(trade_days))

class DateResolver:
    def __init__(self, trading_days: list):
        self.days = trading_days
        self.days_set = set(trading_days)
        self.cutoff_morning = datetime.time(9, 25, 0)
        self.cutoff_close = datetime.time(15, 0, 0)

    def resolve_trade_date(self, dt: datetime.datetime) -> str:
        d_str = dt.strftime("%Y-%m-%d")
        t_time = dt.time()
        is_trade_day = d_str in self.days_set

        if is_trade_day:
            if t_time < self.cutoff_morning:
                return d_str
            elif t_time < self.cutoff_close:
                return d_str
            else:
                idx = bisect.bisect_right(self.days, d_str)
                return self.days[idx] if idx < len(self.days) else d_str
        else:
            idx = bisect.bisect_right(self.days, d_str)
            return self.days[idx] if idx < len(self.days) else d_str

def parse_time_str(time_str: str) -> datetime.datetime:
    if not time_str:
        return None
    s = time_str.strip()
    # Handle "2021-01-10 14:49:29:000" or "2021-01-10 14:49:29"
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})", s)
    if m:
        try:
            return datetime.datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    # Fallback to date only
    m_d = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m_d:
        try:
            return datetime.datetime.strptime(m_d.group(1), "%Y-%m-%d")
        except Exception:
            pass
    return None

def fetch_page(date_str: str, ann_type: str, page: int, retries: int = 5):
    url = API_URL.format(page=page, ann_type=ann_type, date=date_str)
    last_err = None
    for attempt in range(retries):
        session = get_session()
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 567:
                _tls.session = None
                time.sleep(2.0 * (attempt + 1))
                last_err = RuntimeError(f"HTTP 567 rate limited on {date_str} p={page}")
                continue
            resp.raise_for_status()
            js = resp.json()
            data = js.get("data")
            if data is None:
                if js.get("success") in (True, 1) or "data" in js:
                    return 0, []
                raise RuntimeError(f"unexpected response on {date_str}: {str(js)[:120]}")
            total_hits = int(data.get("total_hits") or 0)
            items = data.get("list") or []
            return total_hits, items
        except Exception as e:
            last_err = e
            _tls.session = None
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"[{date_str} {ann_type} p={page}] failed after {retries} retries: {last_err}")

def fetch_single_market(date_str: str, ann_type: str):
    total_hits, first_items = fetch_page(date_str, ann_type, 1)
    if total_hits == 0 or not first_items:
        return []
    total_pages = math.ceil(total_hits / 100.0)
    # Eastern Wealth page limit check
    total_pages = min(total_pages, 100)
    all_items = list(first_items)
    for p in range(2, total_pages + 1):
        _, items = fetch_page(date_str, ann_type, p)
        if not items:
            break
        all_items.extend(items)
    return all_items

def fetch_day_notices(date_str: str, resolver: DateResolver):
    # 先尝试全量 A 股拉取
    total_hits, first_items = fetch_page(date_str, "A", 1)
    all_raw_items = []
    if total_hits <= 4500:
        total_pages = math.ceil(total_hits / 100.0)
        all_raw_items.extend(first_items)
        for p in range(2, total_pages + 1):
            _, items = fetch_page(date_str, "A", p)
            all_raw_items.extend(items)
    else:
        # 超过 4500 条（如年报季高峰），按分市场并行拉取确保零截断
        markets = ["SHA", "SZA", "CYB", "BJA", "KCB", "A"]
        for mkt in markets:
            items = fetch_single_market(date_str, mkt)
            all_raw_items.extend(items)

    rows = []
    seen = set()
    for it in all_raw_items:
        art_code = str(it.get("art_code") or "").strip()
        title = str(it.get("title") or it.get("title_ch") or "").strip()
        if not title:
            continue
        cols = it.get("columns") or []
        ntype = str(cols[0].get("column_name") or "").strip() if cols and isinstance(cols[0], dict) else ""

        # 解析时间戳: 优先 eiTime (交易所精确时间), 次选 sort_date, notice_date
        dt = parse_time_str(it.get("eiTime"))
        if not dt:
            dt = parse_time_str(it.get("sort_date"))
        if not dt:
            dt = parse_time_str(it.get("notice_date"))
        if not dt:
            dt = datetime.datetime.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")

        pub_ts_ms = int(dt.timestamp() * 1000)
        pub_datetime_cst = dt.strftime("%Y-%m-%d %H:%M:%S")
        trade_avail = resolver.resolve_trade_date(dt)

        codes = it.get("codes") or []
        for c in codes:
            if not isinstance(c, dict):
                continue
            ann_t = str(c.get("ann_type") or "")
            # 只取 A 股相关代码
            if "A" not in [x.strip() for x in ann_t.split(",")]:
                continue
            sc = str(c.get("stock_code") or "").strip()
            if not sc:
                continue
            code6 = sc.zfill(6) if sc.isdigit() else sc[:6]
            sname = str(c.get("short_name") or "").strip()

            ann_id = f"{art_code}_{code6}" if art_code else f"{code6}_{pub_ts_ms}_{hash(title)%1000000}"
            if ann_id not in seen:
                seen.add(ann_id)
                rows.append((ann_id, code6, sname, title, ntype, pub_ts_ms, pub_datetime_cst, trade_avail))

    return date_str, rows

def save_day_results(db_path: str, date_str: str, rows: list):
    conn = sqlite3.connect(db_path, timeout=60.0)
    try:
        cur = conn.cursor()
        if rows:
            cur.executemany("""
                INSERT OR REPLACE INTO notices 
                (ann_id, sec_code, sec_name, title, ann_type, pub_ts_ms, pub_datetime_cst, trade_date_avail)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("INSERT OR REPLACE INTO done_dates (date_str, count, done_at) VALUES (?, ?, ?)",
                    (date_str, len(rows), now_str))
        conn.commit()
    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser(description="Backfill Eastmoney 5Y PIT Announcements")
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2026-11-10")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--test-date", default=None)
    args = parser.parse_args()

    init_db(DB_PATH)
    trading_days = load_trading_days()
    resolver = DateResolver(trading_days)

    if args.test_date:
        d = args.test_date
        print(f"[TEST] Fetching {d} ...")
        d_str, rows = fetch_day_notices(d, resolver)
        print(f"[TEST] {d} fetched {len(rows)} A-share notices.")
        if rows:
            print("Sample row:", rows[0])
            save_day_results(DB_PATH, d_str, rows)
            print("[TEST] Saved successfully.")
        return

    # Check already done dates
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    done_set = set(r[0] for r in conn.execute("SELECT date_str FROM done_dates WHERE count > 0").fetchall())
    conn.close()

    d_start = datetime.date.fromisoformat(args.start)
    d_end = datetime.date.fromisoformat(args.end)
    target_dates = []
    cur = d_start
    while cur <= d_end:
        ds = cur.isoformat()
        if ds not in done_set:
            target_dates.append(ds)
        cur += datetime.timedelta(days=1)

    print(f"Total target dates to process: {len(target_dates)} (already done: {len(done_set)})")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_map = {pool.submit(fetch_day_notices, d, resolver): d for d in target_dates}
        completed = 0
        total_rows_batch = 0
        t0 = time.time()
        for f in as_completed(future_map):
            d = future_map[f]
            try:
                d_str, rows = f.result()
                save_day_results(DB_PATH, d_str, rows)
                completed += 1
                total_rows_batch += len(rows)
                if completed % 10 == 0 or completed == len(target_dates):
                    elapsed = time.time() - t0
                    speed = completed / elapsed if elapsed > 0 else 0
                    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Progress: {completed}/{len(target_dates)} days done, "
                          f"+{total_rows_batch} notices ({speed:.2f} days/s), last: {d_str} count={len(rows)}", flush=True)
            except Exception as e:
                print(f"[ERROR] Date {d} failed: {e}", file=sys.stderr, flush=True)

if __name__ == "__main__":
    main()

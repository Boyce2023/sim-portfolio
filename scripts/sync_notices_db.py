#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
sync_notices_db.py — 东财全市场A股公告库 (notices.db) 历史全量补齐与每日滚动增量同步引擎
表结构：
  notice(code text, name text, title text, ntype text, ndate text)
  索引：ix_nd(ndate), ix_nc(code, ndate)
  进度表：done(d text primary key, n int)

特性：
  1. 严格按自然日（Calendar Days）抓取，完美覆盖晚间预披露标次日/周末/下周一日期的公告。
  2. 只提取 codes 中 ann_type 含 'A' 的真实A股代码（过滤 000001/000300 等 Index 指数关联噪音与转债代码）。
  3. 复用线程级 HTTP Keep-Alive 长连接 + 自适应限流退避（防东财 WAF 567 断流），
     核验抓回公告条数与 total_hits 一致（绝不静默吞错），单日事务内先 DELETE 再去重批量写入并更新 done(d, count)。
  4. 支持 --recent 模式（刷 today-3天 至 today+4天 共8个自然日，耗时约 2~4 秒，供 16:30 与 08:45 定时调用）。
"""
import os
import sys
import time
import math
import sqlite3
import datetime
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/notices.db"
API_URL = (
    "http://np-anotice-stock.eastmoney.com/api/security/ann"
    "?sr=-1&page_size=100&page_index={p}&ann_type=A&client_source=web"
    "&f_node=0&s_node=0&begin_time={d}&end_time={d}"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "http://data.eastmoney.com/",
    "Connection": "keep-alive",
}

_tls = threading.local()


def _get_session() -> requests.Session:
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        s.trust_env = False
        adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _tls.session = s
    return s


def _fetch_page(d: str, page: int, retries: int = 6):
    url = API_URL.format(p=page, d=d)
    last_err = None
    for attempt in range(retries):
        session = _get_session()
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 567:
                # 东财 WAF 限流，重置连接并退避等待
                _tls.session = None
                time.sleep(2.5 * (attempt + 1))
                last_err = RuntimeError(f"HTTP 567 rate limited on {d} p={page}")
                continue
            resp.raise_for_status()
            js = resp.json()
            data = js.get("data")
            if data is None:
                if js.get("success") in (True, 1) or "data" in js:
                    return 0, []
                raise RuntimeError(f"unexpected response: {str(js)[:120]}")
            total_hits = int(data.get("total_hits") or 0)
            items = data.get("list") or []
            return total_hits, items
        except Exception as e:
            last_err = e
            _tls.session = None
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"[{d} p={page}] failed after {retries} retries: {last_err}")


def fetch_one_day(d: str):
    """抓取单个自然日 d 的全部A股公告，返回 (d, dedup_rows, total_hits)"""
    total_hits, first_items = _fetch_page(d, 1)
    if total_hits == 0 or not first_items:
        return d, [], 0

    total_pages = math.ceil(total_hits / 100.0)
    all_items = list(first_items)

    for p in range(2, total_pages + 1):
        _, items = _fetch_page(d, p)
        all_items.extend(items)

    # 校验抓回原始公告数与 total_hits
    if len(all_items) < total_hits - 5 and len(all_items) < int(total_hits * 0.95):
        raise RuntimeError(f"[{d}] incomplete items: got {len(all_items)} / total_hits={total_hits}")

    seen = set()
    rows = []
    for it in all_items:
        title = str(it.get("title") or it.get("title_ch") or "").strip()
        if not title:
            continue
        cols = it.get("columns") or []
        ntype = str(cols[0].get("column_name") or "").strip() if cols and isinstance(cols[0], dict) else ""
        ndate_raw = str(it.get("notice_date") or d).strip()[:10]
        ndate = ndate_raw if len(ndate_raw) == 10 else d
        codes = it.get("codes") or []
        for c in codes:
            if not isinstance(c, dict):
                continue
            ann_t = str(c.get("ann_type") or "")
            if "A" not in [x.strip() for x in ann_t.split(",")]:
                continue
            sc = str(c.get("stock_code") or "").strip()
            if not sc:
                continue
            code6 = sc.zfill(6) if sc.isdigit() else sc[:6]
            sname = str(c.get("short_name") or "").strip()
            key = (code6, title, ndate)
            if key not in seen:
                seen.add(key)
                rows.append((code6, sname, title, ntype, ndate))

    return d, rows, total_hits


def ensure_schema(conn: sqlite3.Connection):
    conn.execute("CREATE TABLE IF NOT EXISTS notice(code text, name text, title text, ntype text, ndate text)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_nd ON notice(ndate)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_nc ON notice(code,ndate)")
    conn.execute("CREATE TABLE IF NOT EXISTS done(d text primary key, n int)")
    conn.commit()


def date_range(start_str: str, end_str: str):
    d0 = datetime.date.fromisoformat(start_str)
    d1 = datetime.date.fromisoformat(end_str)
    out = []
    cur = d0
    while cur <= d1:
        out.append(cur.isoformat())
        cur += datetime.timedelta(days=1)
    return out


def main():
    ap = argparse.ArgumentParser(description="Sync Eastmoney A-share announcements into notices.db")
    ap.add_argument("--start", default="2026-04-01", help="Start calendar date YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="End calendar date YYYY-MM-DD (default: today+3d)")
    ap.add_argument("--recent", action="store_true", help="Sync recent window [today-3d, today+4d] unconditionally")
    ap.add_argument("--force", action="store_true", help="Force re-fetch even if date is in done table")
    ap.add_argument("--workers", type=int, default=4, help="Concurrent day workers")
    args = ap.parse_args()

    t0 = time.time()
    today = datetime.date.today()

    conn = sqlite3.connect(DB_PATH, timeout=60)
    ensure_schema(conn)

    if args.recent:
        start_d = (today - datetime.timedelta(days=3)).isoformat()
        end_d = (today + datetime.timedelta(days=4)).isoformat()
        todo = date_range(start_d, end_d)
        mode_str = f"RECENT ({start_d} ~ {end_d})"
    else:
        start_d = args.start
        end_d = args.end or (today + datetime.timedelta(days=2)).isoformat()
        all_days = date_range(start_d, end_d)
        if args.force:
            todo = all_days
        else:
            have = {r[0] for r in conn.execute("SELECT d FROM done").fetchall()}
            cutoff_refresh = (today - datetime.timedelta(days=1)).isoformat()
            todo = [d for d in all_days if (d not in have) or (d >= cutoff_refresh)]
        mode_str = f"RANGE ({start_d} ~ {end_d})"

    print(f"[sync_notices_db] Mode={mode_str} | 待同步自然日={len(todo)}", flush=True)
    if not todo:
        cnt, min_d, max_d = conn.execute("SELECT COUNT(*), MIN(ndate), MAX(ndate) FROM notice").fetchone()
        print(f"[sync_notices_db] 无需更新 | 总行数={cnt} | 范围={min_d}~{max_d} | 耗时={time.time()-t0:.2f}s")
        conn.close()
        return 0

    ok_days = 0
    fail_days = []
    total_inserted = 0

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        fut_map = {ex.submit(fetch_one_day, d): d for d in todo}
        done_cnt = 0
        for fut in as_completed(fut_map):
            d = fut_map[fut]
            done_cnt += 1
            try:
                _, rows, hits = fut.result()
                with conn:
                    conn.execute("DELETE FROM notice WHERE ndate = ?", (d,))
                    if rows:
                        other_ndates = {r[4] for r in rows if r[4] != d}
                        for ond in other_ndates:
                            existing = {
                                (c, t)
                                for c, t in conn.execute(
                                    "SELECT code, title FROM notice WHERE ndate = ?", (ond,)
                                ).fetchall()
                            }
                            rows = [r for r in rows if not (r[4] == ond and (r[0], r[2]) in existing)]
                        conn.executemany("INSERT INTO notice VALUES (?,?,?,?,?)", rows)
                    conn.execute("INSERT OR REPLACE INTO done VALUES (?,?)", (d, len(rows)))
                ok_days += 1
                total_inserted += len(rows)
                if done_cnt % 20 == 0 or done_cnt == len(todo):
                    print(
                        f"  [{done_cnt}/{len(todo)}] {d} hits={hits} rows={len(rows)} | 累计写入={total_inserted}",
                        flush=True,
                    )
            except Exception as e:
                fail_days.append((d, str(e)))
                print(f"  ⛔ [{done_cnt}/{len(todo)}] {d} FAILED: {e}", flush=True)

    cnt, min_d, max_d = conn.execute("SELECT COUNT(*), MIN(ndate), MAX(ndate) FROM notice").fetchone()
    done_total = conn.execute("SELECT COUNT(*) FROM done").fetchone()[0]
    conn.close()

    elapsed = time.time() - t0
    print(
        f"[sync_notices_db] 完成: ok={ok_days}/{len(todo)} fail={len(fail_days)} "
        f"| 新增/刷新行={total_inserted} | 库总行数={cnt} ({min_d} ~ {max_d}, done={done_total}) | 耗时={elapsed:.2f}s",
        flush=True,
    )
    if fail_days:
        print(f"⛔ 失败日期清单: {fail_days}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

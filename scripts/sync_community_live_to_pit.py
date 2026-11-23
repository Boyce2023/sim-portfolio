#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Idempotent Incremental Sync -> sim-portfolio/data/astock_community_5y_pit.db (community_posts)
Sources:
  1. sim-portfolio/data/xueqiu_guba_5y_pit.db (mode=ro, incremental rows >= 2026-11-11)
  2. news-dashboard/output/astock_community.json (live 5-platform stream: 雪球/东财股吧/淘股吧/韭研公社/集思录)
PIT-safe: clamps any dirty future timestamp > now or > seen+5m back to seen/now.
Hooked into rd_master_trading_data_sync.py for zero-lag daily maintenance.
"""
import os, re, json, sqlite3, datetime, hashlib

ROOT = "/Users/huaichuaibeimeng/claude-projects"
DATA = f"{ROOT}/sim-portfolio/data"
DST_DB = f"{DATA}/astock_community_5y_pit.db"
SRC_DB = f"{DATA}/xueqiu_guba_5y_pit.db"
LIVE_JSON = f"{ROOT}/news-dashboard/output/astock_community.json"
IND_CSV = f"{DATA}/industry.csv"

SRC_MAP = {
    "雪球": "xueqiu",
    "东财股吧": "eastmoney_guba",
    "淘股吧": "taoguba",
    "韭研公社": "jiuyangongshe",
    "集思录": "jisilu",
}


def _to_int(v):
    if v is None:
        return 0
    s = str(v).strip().replace(",", "")
    if not s:
        return 0
    mult = 1
    if s.endswith("万"):
        mult = 10000
        s = s[:-1]
    elif s.endswith("亿"):
        mult = 100000000
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except Exception:
        return 0


def _parse_dt(s: str, fallback: str = "") -> tuple[str, int]:
    now = datetime.datetime.now()
    for cand in (s, fallback):
        c = str(cand or "").strip()
        if not c:
            continue
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.datetime.strptime(c[:19], fmt)
                if dt > now + datetime.timedelta(minutes=5):
                    continue
                return dt.strftime("%Y-%m-%d %H:%M:%S"), int(dt.timestamp() * 1000)
            except Exception:
                pass
    return now.strftime("%Y-%m-%d %H:%M:%S"), int(now.timestamp() * 1000)


def _extract_symbol(url: str, title: str, text: str) -> str:
    u = str(url or "")
    for pat in (r"news,(?:sz|sh|bj)?(\d{6}),", r"xueqiu\.com/S/(?:SH|SZ|BJ)?(\d{6})", r"\b([036]\d{5})\b"):
        m = re.search(pat, u, re.I)
        if m:
            return m.group(1)
    m2 = re.search(r"\b((?:00|30|60|68)\d{4})\b", f"{title} {text[:200]}")
    return m2.group(1) if m2 else ""


def main():
    dst = sqlite3.connect(DST_DB, timeout=60.0)
    cur = dst.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    before_cnt = cur.execute("SELECT COUNT(*) FROM community_posts").fetchone()[0]
    before_max = cur.execute("SELECT MAX(pub_datetime_cst) FROM community_posts").fetchone()[0]

    # 1. Catch up any post-2026-11-11 rows from xueqiu_guba_5y_pit.db (mode=ro)
    added_src = 0
    if os.path.exists(SRC_DB):
        scon = sqlite3.connect(f"file:{SRC_DB}?mode=ro", uri=True)
        scur = scon.cursor()
        # 1a. xueqiu_posts (small table ~123k rows)
        xq_rows = scur.execute(
            "SELECT post_id, symbol, created_at, created_time_str, text, reply_count, retweet_count, fav_count "
            "FROM xueqiu_posts WHERE created_time_str >= '2026-11-11 00:00:00'"
        ).fetchall()
        batch = []
        for r in xq_rows:
            code = str(r[1] or "").zfill(6)
            pub_dt, ts_ms = _parse_dt(r[3] or "")
            if r[2]:
                ts_ms = int(r[2])
            text = r[4] or ""
            title = text[:40].replace("\n", " ").strip()
            batch.append((
                f"xueqiu_{r[0]}", "xueqiu", code, ts_ms, pub_dt, title, text, "",
                f"https://xueqiu.com/S/{code}/{r[0]}", r[5] or 0, r[7] or 0, r[6] or 0, pub_dt
            ))
        if batch:
            cur.executemany(
                "INSERT OR IGNORE INTO community_posts "
                "(post_id, source, symbol, pub_ts_ms, pub_datetime_cst, title, text, author, url, reply_count, like_count, retweet_count, created_at_iso) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", batch
            )
            dst.commit()
            added_src += len(batch)
        # 1b. guba_posts recent (>= 2026-11-11, fast via index or rowid tail)
        gb_rows = scur.execute(
            "SELECT post_id, sec_code, title, author, pub_time, read_cnt, comment_cnt "
            "FROM guba_posts WHERE pub_time >= '2026-11-11 00:00:00'"
        ).fetchall()
        gbatch = []
        for r in gb_rows:
            code = str(r[1] or "").zfill(6)
            pub_dt, ts_ms = _parse_dt(r[4] or "")
            title = r[2] or ""
            gbatch.append((
                f"guba_{r[0]}", "eastmoney_guba", code, ts_ms, pub_dt, title, title, r[3] or "",
                f"https://guba.eastmoney.com/news,{code},{r[0]}.html", r[6] or 0, r[5] or 0, 0, pub_dt
            ))
        if gbatch:
            cur.executemany(
                "INSERT OR IGNORE INTO community_posts "
                "(post_id, source, symbol, pub_ts_ms, pub_datetime_cst, title, text, author, url, reply_count, like_count, retweet_count, created_at_iso) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", gbatch
            )
            dst.commit()
            added_src += len(gbatch)
        scon.close()

    # 2. Ingest live rolling stream from news-dashboard/output/astock_community.json
    live_batch = []
    if os.path.exists(LIVE_JSON):
        items = json.load(open(LIVE_JSON, encoding="utf-8"))
        for it in items:
            raw_id = str(it.get("id") or it.get("url") or "").strip()
            src_cn = str(it.get("src") or "")
            source = SRC_MAP.get(src_cn, src_cn or "live_community")
            if not raw_id:
                raw_id = hashlib.md5(f"{source}|{it.get('time')}|{it.get('title')}|{str(it.get('text',''))[:60]}".encode()).hexdigest()[:16]
            # Normalize post_id cleanly without clashing with historical guba_/xueqiu_ numeric IDs
            if raw_id.startswith("xq") and raw_id[2:].isdigit():
                pid = f"xueqiu_{raw_id[2:]}"
            else:
                pid = f"live_{source}_{raw_id}"[:120]
            url = str(it.get("url") or "")
            title = str(it.get("title") or "").strip()
            text = str(it.get("text") or "").strip()
            if not title and text:
                title = text[:48].replace("\n", " ").strip()
            if not text and title:
                text = title
            author = str(it.get("user") or "").strip()
            pub_dt, ts_ms = _parse_dt(it.get("time") or "", it.get("seen") or "")
            sym = _extract_symbol(url, title, text)
            heat = it.get("heat") if isinstance(it.get("heat"), dict) else {}
            reply_cnt = _to_int(heat.get("评") or heat.get("回复") or heat.get("帖"))
            like_cnt = _to_int(heat.get("赞") or heat.get("读"))
            retw_cnt = _to_int(heat.get("转"))
            live_batch.append((
                pid, source, sym, ts_ms, pub_dt, title, text, author, url,
                reply_cnt, like_cnt, retw_cnt, pub_dt
            ))
        if live_batch:
            cur.executemany(
                "INSERT OR IGNORE INTO community_posts "
                "(post_id, source, symbol, pub_ts_ms, pub_datetime_cst, title, text, author, url, reply_count, like_count, retweet_count, created_at_iso) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", live_batch
            )
            dst.commit()

    after_cnt = cur.execute("SELECT COUNT(*) FROM community_posts").fetchone()[0]
    after_max = cur.execute("SELECT MAX(pub_datetime_cst) FROM community_posts WHERE pub_datetime_cst != ''").fetchone()[0]
    by_day = cur.execute(
        "SELECT substr(pub_datetime_cst,1,10) d, COUNT(*) FROM community_posts "
        "WHERE pub_datetime_cst >= '2026-11-11' GROUP BY d ORDER BY d"
    ).fetchall()
    dst.close()
    print(f"[COMMUNITY_PIT_SYNC] before={before_cnt:,} ({before_max}) -> after={after_cnt:,} ({after_max}) | net_added={after_cnt - before_cnt:,}")
    print("  recent daily counts:", by_day)


if __name__ == "__main__":
    main()

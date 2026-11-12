#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全流式同步脚本: 将五年补齐的东财股吧、雪球原帖与 7x24 财经快讯增量同步至主库
源库:
  - /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/xueqiu_guba_5y_pit.db (只读 mode=ro)
  - /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/flash_news_5y_pit.db (只读 mode=ro)
目标库:
  - /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/astock_community_5y_pit.db (community_posts)
  - /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/astock_news_5y_pit.db (news_pit)
"""
import os
import sys
import time
import json
import bisect
import sqlite3
import datetime

SRC_COMMUNITY = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/xueqiu_guba_5y_pit.db"
SRC_NEWS = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/flash_news_5y_pit.db"
DST_COMMUNITY = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/astock_community_5y_pit.db"
DST_NEWS = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/astock_news_5y_pit.db"
KPL_JSONL = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"

def load_trading_days():
    days = []
    with open(KPL_JSONL, "r") as f:
        for line in f:
            if line.strip():
                try:
                    days.append(json.loads(line)["date"])
                except Exception:
                    pass
    days = sorted(list(set(days)))
    days_set = set(days)
    return days, days_set

TRADING_DAYS, TRADING_DAYS_SET = load_trading_days()

def calc_avail_trade_date(pub_dt_str: str) -> str:
    """计算 PIT 可用交易日:
    若在交易日且时间 < 09:25:00，当日可用；
    若时间 >= 09:25:00 或在非交易日/周末，下一个交易日可用。
    """
    if len(pub_dt_str) < 10:
        return "2026-11-10"
    pdate = pub_dt_str[:10]
    ptime = pub_dt_str[11:19] if len(pub_dt_str) >= 19 else "00:00:00"
    
    if pdate in TRADING_DAYS_SET and ptime < "09:25:00":
        return pdate
        
    idx = bisect.bisect_right(TRADING_DAYS, pdate)
    if idx < len(TRADING_DAYS):
        return TRADING_DAYS[idx]
    return TRADING_DAYS[-1]

def sync_community():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 开始同步社区帖子至 {DST_COMMUNITY}...")
    dst_conn = sqlite3.connect(DST_COMMUNITY, timeout=60.0)
    dst_cur = dst_conn.cursor()
    dst_cur.execute("PRAGMA journal_mode = WAL;")
    dst_cur.execute("PRAGMA synchronous = NORMAL;")
    
    # 统计同步前条数
    before_cnt = dst_cur.execute("SELECT count(*) FROM community_posts").fetchone()[0]
    
    src_conn = sqlite3.connect(f"file:{SRC_COMMUNITY}?mode=ro", uri=True)
    src_cur = src_conn.cursor()
    
    # 1. 同步东财股吧 guba_posts
    print("正在分批读取 guba_posts...")
    src_cur.execute("SELECT post_id, sec_code, title, author, pub_time, read_cnt, comment_cnt FROM guba_posts")
    
    batch = []
    total_guba_synced = 0
    while True:
        rows = src_cur.fetchmany(10000)
        if not rows:
            break
        for r in rows:
            pid = f"guba_{r[0]}"
            code = str(r[1]).zfill(6)
            title = r[2] or ""
            author = r[3] or ""
            pub_dt = r[4] or ""
            ts_ms = 0
            if pub_dt:
                try:
                    dt = datetime.datetime.strptime(pub_dt[:19], "%Y-%m-%d %H:%M:%S")
                    ts_ms = int(dt.timestamp() * 1000)
                except Exception:
                    pass
            read_cnt = r[5] or 0
            reply_cnt = r[6] or 0
            url = f"https://guba.eastmoney.com/news,{code},{r[0]}.html"
            
            batch.append((
                pid, "eastmoney_guba", code, ts_ms, pub_dt, title, title, author, url,
                reply_cnt, read_cnt, 0, pub_dt
            ))
            
        dst_cur.executemany("""
        INSERT OR IGNORE INTO community_posts
        (post_id, source, symbol, pub_ts_ms, pub_datetime_cst, title, text, author, url, reply_count, like_count, retweet_count, created_at_iso)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        dst_conn.commit()
        total_guba_synced += len(batch)
        print(f"  已流式同步 guba_posts: {total_guba_synced:,} 条...", end="\r", flush=True)
        batch.clear()
        
    print(f"\n  [Guba 完成] 累计流式同步 guba_posts: {total_guba_synced:,} 条")
    
    # 2. 同步雪球 xueqiu_posts
    print("正在分批读取 xueqiu_posts...")
    src_cur.execute("SELECT post_id, symbol, created_at, created_time_str, text, reply_count, retweet_count, fav_count FROM xueqiu_posts")
    total_xq_synced = 0
    while True:
        rows = src_cur.fetchmany(5000)
        if not rows:
            break
        for r in rows:
            pid = f"xueqiu_{r[0]}"
            code = str(r[1]).zfill(6)
            ts_ms = r[2] or 0
            pub_dt = r[3] or ""
            text = r[4] or ""
            title = text[:40].replace("\n", " ").strip()
            reply_cnt = r[5] or 0
            retweet_cnt = r[6] or 0
            like_cnt = r[7] or 0
            url = f"https://xueqiu.com/S/{code}/{r[0]}"
            
            batch.append((
                pid, "xueqiu", code, ts_ms, pub_dt, title, text, "", url,
                reply_cnt, like_cnt, retweet_cnt, pub_dt
            ))
            
        dst_cur.executemany("""
        INSERT OR IGNORE INTO community_posts
        (post_id, source, symbol, pub_ts_ms, pub_datetime_cst, title, text, author, url, reply_count, like_count, retweet_count, created_at_iso)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        dst_conn.commit()
        total_xq_synced += len(batch)
        batch.clear()
        
    print(f"  [Xueqiu 完成] 累计流式同步 xueqiu_posts: {total_xq_synced:,} 条")
    
    src_conn.close()
    
    after_cnt = dst_cur.execute("SELECT count(*) FROM community_posts").fetchone()[0]
    min_d, max_d = dst_cur.execute("SELECT min(pub_datetime_cst), max(pub_datetime_cst) FROM community_posts WHERE pub_datetime_cst != ''").fetchone()
    dst_conn.close()
    
    print(f"=== 社区库同步完成 ===")
    print(f"同步前: {before_cnt:,} 行 -> 同步后: {after_cnt:,} 行 (新增 {after_cnt - before_cnt:,} 行)")
    print(f"时间跨度: [{min_d} ~ {max_d}]")

def sync_news():
    print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] 开始同步 7x24 快讯至 {DST_NEWS}...")
    dst_conn = sqlite3.connect(DST_NEWS, timeout=60.0)
    dst_cur = dst_conn.cursor()
    dst_cur.execute("PRAGMA journal_mode = WAL;")
    dst_cur.execute("PRAGMA synchronous = NORMAL;")
    
    before_cnt = dst_cur.execute("SELECT count(*) FROM news_pit").fetchone()[0]
    
    src_conn = sqlite3.connect(f"file:{SRC_NEWS}?mode=ro", uri=True)
    src_cur = src_conn.cursor()
    
    src_cur.execute("SELECT news_id, source, pub_datetime_cst, pub_ts_ms, is_weekend, title, content, raw_json FROM flash_news")
    
    batch = []
    total_news_synced = 0
    while True:
        rows = src_cur.fetchmany(10000)
        if not rows:
            break
        for r in rows:
            nid = r[0]
            source = r[1] or "sina_724"
            pub_dt = r[2] or ""
            ts_ms = r[3] or 0
            is_wk = r[4] or 0
            title = r[5] or ""
            content = r[6] or ""
            url = f"https://finance.sina.com.cn/7x24/{nid}"
            avail_date = calc_avail_trade_date(pub_dt)
            extra_json = json.dumps({"is_weekend": is_wk, "news_id": nid}, ensure_ascii=False)
            
            batch.append((
                source, pub_dt, ts_ms, avail_date, title, content, url, extra_json
            ))
            
        dst_cur.executemany("""
        INSERT OR IGNORE INTO news_pit
        (source, pub_datetime_cst, pub_ts_ms, avail_trade_date, title, content, url, extra)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, batch)
        dst_conn.commit()
        total_news_synced += len(batch)
        print(f"  已流式同步 flash_news: {total_news_synced:,} 条...", end="\r", flush=True)
        batch.clear()
        
    print(f"\n  [News 完成] 累计流式同步 flash_news: {total_news_synced:,} 条")
    src_conn.close()
    
    after_cnt = dst_cur.execute("SELECT count(*) FROM news_pit").fetchone()[0]
    min_d, max_d = dst_cur.execute("SELECT min(pub_datetime_cst), max(pub_datetime_cst) FROM news_pit").fetchone()
    dst_conn.close()
    
    print(f"=== 新闻总库同步完成 ===")
    print(f"同步前: {before_cnt:,} 行 -> 同步后: {after_cnt:,} 行 (新增 {after_cnt - before_cnt:,} 行)")
    print(f"时间跨度: [{min_d} ~ {max_d}]")

if __name__ == "__main__":
    t0 = time.time()
    sync_community()
    sync_news()
    print(f"\n全部同步完成，总耗时 {time.time() - t0:.1f} 秒。")

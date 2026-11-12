#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缺口 4: 投资者关系活动记录表 (调研纪要全文) 极速回补
数据源: 东财静态 CDN (pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf) + PyMuPDF(fitz) 极速正文解析
无 WAF/567 风控, 0.05秒直连, 16 线程高并发
目标库: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/ir_survey_fulltext_5y_pit.db
"""
import os
import sys
import time
import json
import sqlite3
import urllib.request
import datetime
import fitz
from concurrent.futures import ThreadPoolExecutor, as_completed

CNINFO_DB = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cninfo_notices_5y_pit.db"
TARGET_DB = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/ir_survey_fulltext_5y_pit.db"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

def init_target_db():
    conn = sqlite3.connect(TARGET_DB, timeout=60.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ir_surveys (
        art_code TEXT PRIMARY KEY,
        ann_id TEXT,
        sec_code TEXT,
        sec_name TEXT,
        title TEXT,
        pub_datetime_cst TEXT,
        notice_content TEXT,
        attach_url TEXT,
        page_size INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ir_sec_code ON ir_surveys(sec_code);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ir_pub_dt ON ir_surveys(pub_datetime_cst);")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS crawl_progress (
        art_code TEXT PRIMARY KEY,
        status TEXT,
        char_count INTEGER,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

def fetch_and_parse_pdf(task):
    ann_id, sec_code, sec_name, title, pub_datetime_cst = task
    art_code = ann_id.split("_")[0]
    pdf_url = f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf"
    req = urllib.request.Request(pdf_url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw_pdf = resp.read()
            doc = fitz.open(stream=raw_pdf, filetype="pdf")
            content = ""
            for p in doc:
                content += p.get_text()
            page_count = len(doc)
            return {
                "art_code": art_code,
                "ann_id": ann_id,
                "sec_code": sec_code,
                "sec_name": sec_name,
                "title": title,
                "pub_datetime_cst": pub_datetime_cst,
                "notice_content": content.strip(),
                "attach_url": pdf_url,
                "page_size": page_count,
                "status": "OK" if len(content.strip()) > 0 else "EMPTY"
            }
    except Exception as e:
        return {"art_code": art_code, "status": "FAIL", "error": str(e)}

def main():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 启动缺口4 投资者关系活动记录表极速解析引擎...")
    init_target_db()
    
    t_conn = sqlite3.connect(TARGET_DB)
    t_cur = t_conn.cursor()
    done_codes = set(r[0] for r in t_cur.execute("SELECT art_code FROM crawl_progress WHERE status='OK'").fetchall())
    t_conn.close()
    print(f"已完成篇数: {len(done_codes)}")
    
    s_conn = sqlite3.connect(f"file:{CNINFO_DB}?mode=ro", uri=True)
    s_cur = s_conn.cursor()
    query = """
    SELECT ann_id, sec_code, sec_name, title, pub_datetime_cst 
    FROM notices 
    WHERE (title LIKE '%活动记录%' OR title LIKE '%调研%')
      AND ann_id LIKE 'AN%'
    ORDER BY pub_datetime_cst DESC
    """
    all_notices = s_cur.execute(query).fetchall()
    s_conn.close()
    
    tasks = [n for n in all_notices if n[0].split("_")[0] not in done_codes]
    print(f"总计调研条目: {len(all_notices)}, 剩余待拉取: {len(tasks)}")
    
    if not tasks:
        print("所有调研纪要已全部拉齐!")
        return

    batch_size = 50
    db_conn = sqlite3.connect(TARGET_DB, timeout=60.0)
    db_cur = db_conn.cursor()
    
    total_pulled = 0
    t0 = time.time()
    
    with ThreadPoolExecutor(max_workers=16) as executor:
        for i in range(0, len(tasks), batch_size):
            chunk = tasks[i:i+batch_size]
            futures = [executor.submit(fetch_and_parse_pdf, t) for t in chunk]
            
            for f in as_completed(futures):
                res = f.result()
                art_code = res["art_code"]
                status = res["status"]
                if status == "OK":
                    content = res.get("notice_content", "")
                    db_cur.execute("""
                    INSERT OR REPLACE INTO ir_surveys 
                    (art_code, ann_id, sec_code, sec_name, title, pub_datetime_cst, notice_content, attach_url, page_size)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        art_code, res["ann_id"], res["sec_code"], res["sec_name"],
                        res["title"], res["pub_datetime_cst"], content, res["attach_url"], res["page_size"]
                    ))
                    db_cur.execute("""
                    INSERT OR REPLACE INTO crawl_progress (art_code, status, char_count, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    """, (art_code, status, len(content)))
                    total_pulled += 1
                else:
                    db_cur.execute("""
                    INSERT OR REPLACE INTO crawl_progress (art_code, status, char_count, updated_at)
                    VALUES (?, ?, 0, CURRENT_TIMESTAMP)
                    """, (art_code, status))
            
            db_conn.commit()
            elapsed = time.time() - t0
            rate = total_pulled / (elapsed + 0.001)
            eta = (len(tasks) - total_pulled) / (rate + 0.001) / 60
            if total_pulled % 100 == 0 or i + batch_size >= len(tasks):
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 调研纪要已回补 {total_pulled}/{len(tasks)} 篇, 速率: {rate:.1f}篇/秒, 预计剩余: {eta:.1f}分钟", flush=True)

    db_conn.close()
    print("缺口4 回补全部圆满完成!")

if __name__ == "__main__":
    main()

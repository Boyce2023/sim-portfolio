#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缺口 6: 五年沪深主板首板股真实 5 分钟历史 K 线与微观盘口落地引擎 (Baostock 直连 114.94.20.42)
目标库: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/firstboard_5m_5y_pit.db
"""
import os
import sys
import time
import datetime
import sqlite3
import baostock as bs

# 绕过 macOS FakeIP DNS，直连官方真实公网 IP
bs.common.contants.BAOSTOCK_SERVER_IP = "114.94.20.42"

DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/firstboard_5m_5y_pit.db"
ZT_DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db"

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS firstboard_5m_bars (
        sec_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        bar_time TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        volume REAL NOT NULL,
        amount REAL NOT NULL,
        PRIMARY KEY (sec_code, bar_time)
    );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fb_date ON firstboard_5m_bars(trade_date);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fb_code ON firstboard_5m_bars(sec_code);")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS crawl_progress (
        task_key TEXT PRIMARY KEY,
        sec_code TEXT NOT NULL,
        d1_date TEXT NOT NULL,
        bar_count INTEGER DEFAULT 0,
        status TEXT NOT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

def to_bs_code(code: str) -> str:
    c = str(code).strip().zfill(6)
    if c.startswith(('60', '68')):
        return f"sh.{c}"
    return f"sz.{c}"

def get_target_tasks():
    """从涨停盘口库加载所有首板任务 (sec_code, trade_date)"""
    conn = sqlite3.connect(f"file:{ZT_DB_PATH}?mode=ro", uri=True)
    cur = conn.cursor()
    # 筛选主板首板股 (00, 60开头)
    rows = cur.execute("""
        SELECT DISTINCT sec_code, trade_date 
        FROM zt_micro_tape 
        WHERE (sec_code LIKE '00%' OR sec_code LIKE '60%')
        ORDER BY trade_date ASC, sec_code ASC
    """).fetchall()
    conn.close()
    return rows

def main():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 启动缺口6 真实 5 分钟历史 K 线回补引擎 (Baostock)...")
    init_db()
    
    tasks = get_target_tasks()
    print(f"加载目标首板股票-日期对共 {len(tasks)} 组")
    
    # 获取已完成
    conn_self = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    done_keys = set(r[0] for r in conn_self.execute("SELECT task_key FROM crawl_progress WHERE status='DONE'").fetchall())
    conn_self.close()
    print(f"已完成: {len(done_keys)} 组，待抓取: {len(tasks) - len(done_keys)} 组")
    
    lg = bs.login()
    if lg.error_code != '0':
        print(f"Baostock 登录失败: {lg.error_msg}")
        return
        
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    batch_bars = []
    batch_progress = []
    total_bars = 0
    t0 = time.time()
    
    try:
        for idx, (code, d1) in enumerate(tasks, 1):
            key = f"{code}_{d1}"
            if key in done_keys:
                continue
                
            bs_code = to_bs_code(code)
            # 拉取 D1 当日 5 分钟线
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,time,code,open,high,low,close,volume,amount",
                start_date=d1,
                end_date=d1,
                frequency="5",
                adjustflag="3"
            )
            
            bars_for_stock = 0
            if rs.error_code == '0':
                while rs.next():
                    row = rs.get_row_data()
                    # row: [date, time, code, open, high, low, close, volume, amount]
                    # time 格式: YYYYMMDDHHMMSS000
                    b_time = row[1][:14]
                    bar_time_str = f"{b_time[:4]}-{b_time[4:6]}-{b_time[6:8]} {b_time[8:10]}:{b_time[10:12]}:{b_time[12:14]}"
                    batch_bars.append((
                        code,
                        d1,
                        bar_time_str,
                        float(row[3] or 0.0),
                        float(row[4] or 0.0),
                        float(row[5] or 0.0),
                        float(row[6] or 0.0),
                        float(row[7] or 0.0),
                        float(row[8] or 0.0)
                    ))
                    bars_for_stock += 1
                    
            batch_progress.append((key, code, d1, bars_for_stock, "DONE"))
            total_bars += bars_for_stock
            
            if len(batch_progress) >= 20:
                cur = conn.cursor()
                if batch_bars:
                    cur.executemany("""
                    INSERT OR REPLACE INTO firstboard_5m_bars (sec_code, trade_date, bar_time, open, high, low, close, volume, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, batch_bars)
                cur.executemany("""
                INSERT OR REPLACE INTO crawl_progress (task_key, sec_code, d1_date, bar_count, status)
                VALUES (?, ?, ?, ?, ?);
                """, batch_progress)
                conn.commit()
                batch_bars.clear()
                batch_progress.clear()
                
                speed = total_bars / max(time.time() - t0, 1.0)
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 进度: [{idx}/{len(tasks)}] 累计 5 分钟 K 线入库: {total_bars} 条 (速度: {speed:.1f} 条/秒)")
                
        # 刷尾批
        if batch_progress:
            cur = conn.cursor()
            if batch_bars:
                cur.executemany("""
                INSERT OR REPLACE INTO firstboard_5m_bars (sec_code, trade_date, bar_time, open, high, low, close, volume, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, batch_bars)
            cur.executemany("""
            INSERT OR REPLACE INTO crawl_progress (task_key, sec_code, d1_date, bar_count, status)
            VALUES (?, ?, ?, ?, ?);
            """, batch_progress)
            conn.commit()
            
    finally:
        conn.close()
        bs.logout()
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 缺口 6 回补进程退出，累计入库 {total_bars} 条 5 分钟线。")

if __name__ == "__main__":
    main()

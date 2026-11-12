#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缺口 5: 五年涨停池微观盘口历史回补 (开盘啦直连 API, 2021-01-04 至 2026-11-11)
提取字段: 首次封板时间戳/时间(秒级)、连板标签、连板数、封单资金、开板/炸板状态、原因题材
目标库: /Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db
"""
import os
import sys
import time
import json
import sqlite3
import datetime
import importlib.util

DB_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/zt_micro_tape_5y_pit.db"
KPL_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/kpl_archive.py"

def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS zt_micro_tape (
        trade_date TEXT NOT NULL,
        sec_code TEXT NOT NULL,
        sec_name TEXT NOT NULL,
        first_seal_time TEXT,
        first_seal_ts INTEGER,
        seal_amount REAL,
        continuous_plate_tag TEXT,
        board_count INTEGER DEFAULT 1,
        open_board_count INTEGER DEFAULT 0,
        plate_name TEXT,
        reason_desc TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (trade_date, sec_code)
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_zt_date ON zt_micro_tape(trade_date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_zt_code ON zt_micro_tape(sec_code);")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS crawl_progress (
        trade_date TEXT PRIMARY KEY,
        stock_count INTEGER,
        status TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

def load_kpl_client():
    spec = importlib.util.spec_from_file_location("kpl_archive", KPL_PATH)
    kpl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kpl)
    kpl.alert = lambda m: None
    return kpl

def fetch_day_tape(kpl, date_str):
    records = {}
    idx = 0
    while idx < 90:
        try:
            d = kpl.get("apphis", {"c": "HisLimitResumption", "a": "GetPlateInfo_w38", "Date": date_str, "Index": idx})
        except Exception:
            break
        L = (d.get("list") if isinstance(d, dict) else None) or []
        if not L:
            break
        for p in L:
            plate_name = p.get("ZSName", "")
            for s in p.get("StockList", []):
                sym = s[0] if len(s) > 0 else ""
                name = s[1] if len(s) > 1 else ""
                if not sym or not (len(sym) == 6 and sym.isdigit()):
                    continue
                if sym in records:
                    continue
                    
                # s[6] 为首次封板秒级时间戳
                ts = s[6] if len(s) > 6 else 0
                fst_str = ""
                if ts and str(ts).isdigit() and int(ts) > 1000000000:
                    try:
                        fst_str = datetime.datetime.fromtimestamp(int(ts)).strftime("%H:%M:%S")
                    except Exception:
                        fst_str = ""
                        
                seal_amt = s[8] if len(s) > 8 else 0
                tag = s[9] if len(s) > 9 else ""
                b_cnt = s[10] if len(s) > 10 else 1
                reason = s[17] if len(s) > 17 else ""
                open_cnt = s[18] if len(s) > 18 else 0
                
                records[sym] = {
                    "trade_date": date_str,
                    "sec_code": sym,
                    "sec_name": name,
                    "first_seal_time": fst_str,
                    "first_seal_ts": ts,
                    "seal_amount": seal_amt,
                    "continuous_plate_tag": tag,
                    "board_count": b_cnt,
                    "open_board_count": open_cnt,
                    "plate_name": plate_name,
                    "reason_desc": str(reason)[:300]
                }
        idx += 3
        time.sleep(0.1)
    return list(records.values())

def main():
    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 启动缺口5 五年涨停微观盘口回补引擎...")
    init_db()
    kpl = load_kpl_client()
    
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    cur = conn.cursor()
    done_dates = set(r[0] for r in cur.execute("SELECT trade_date FROM crawl_progress WHERE status='OK'").fetchall())
    
    # 构建 2021-01-04 至 2026-11-11 的全部交易日
    # 从已有 complete jsonl 取真实交易日序列
    kpl_jsonl = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/kpl_plates_5y_2021_2026_complete.jsonl"
    all_dates = []
    with open(kpl_jsonl, "r") as f:
        for line in f:
            if line.strip():
                try:
                    obj = json.loads(line)
                    dt = obj.get("date")
                    if dt and dt not in done_dates:
                        all_dates.append(dt)
                except Exception:
                    pass
                    
    print(f"总计交易日: {len(all_dates) + len(done_dates)}, 剩余待拉取: {len(all_dates)}")
    if not all_dates:
        print("所有交易日微观盘口已全部回补完毕!")
        conn.close()
        return

    total_inserted = 0
    t0 = time.time()
    
    for i, dt in enumerate(all_dates):
        try:
            records = fetch_day_tape(kpl, dt)
            inserted_day = 0
            for r in records:
                cur.execute("""
                INSERT OR REPLACE INTO zt_micro_tape 
                (trade_date, sec_code, sec_name, first_seal_time, first_seal_ts, seal_amount, continuous_plate_tag, board_count, open_board_count, plate_name, reason_desc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["trade_date"], r["sec_code"], r["sec_name"], r["first_seal_time"],
                    r["first_seal_ts"], r["seal_amount"], r["continuous_plate_tag"],
                    r["board_count"], r["open_board_count"], r["plate_name"], r["reason_desc"]
                ))
                inserted_day += 1
                
            cur.execute("""
            INSERT OR REPLACE INTO crawl_progress (trade_date, stock_count, status, updated_at)
            VALUES (?, ?, 'OK', CURRENT_TIMESTAMP)
            """, (dt, inserted_day))
            conn.commit()
            total_inserted += inserted_day
            
            elapsed = time.time() - t0
            rate = (i + 1) / (elapsed + 0.001)
            eta = (len(all_dates) - (i + 1)) / (rate + 0.001) / 60
            if (i + 1) % 10 == 0 or i + 1 == len(all_dates):
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 进度: {i+1}/{len(all_dates)} 天, 当日涨停股: {inserted_day}, 累计入库: {total_inserted}, 速度: {rate:.1f}天/秒, 预计剩余: {eta:.1f}分钟", flush=True)
        except Exception as e:
            print(f"[{dt}] 异常: {e}")
        time.sleep(0.15)
        
    conn.close()
    print("缺口5 回补完成!")

if __name__ == "__main__":
    main()

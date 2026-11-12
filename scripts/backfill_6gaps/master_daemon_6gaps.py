#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
五年六大历史数据缺口全量探针与高并发回补 · 总控调度与实时监控守护引擎
输出进度报告: /tmp/astock_6gaps_backfill_plan_and_live_progress.json
"""
import os
import sys
import time
import json
import sqlite3
import subprocess
import datetime

SCRIPTS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/backfill_6gaps"
DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data"
LOGS_DIR = "/tmp/astock_6gaps_logs"
STATUS_FILE = "/tmp/astock_6gaps_backfill_plan_and_live_progress.json"

os.makedirs(LOGS_DIR, exist_ok=True)

GAPS_CONFIG = {
    "gap1_xueqiu": {
        "name": "雪球五年历史个股原帖(CDP 3456穿透)",
        "script": os.path.join(SCRIPTS_DIR, "backfill_gap1_xueqiu.py"),
        "db": os.path.join(DATA_DIR, "xueqiu_guba_5y_pit.db"),
        "table": "xueqiu_posts",
        "total_estimate": 45000,
        "log": os.path.join(LOGS_DIR, "gap1_xueqiu.log")
    },
    "gap2_guba": {
        "name": "东财股吧五年首板隔夜/周末讨论帖(二分查找)",
        "script": os.path.join(SCRIPTS_DIR, "backfill_gap2_guba.py"),
        "db": os.path.join(DATA_DIR, "xueqiu_guba_5y_pit.db"),
        "table": "guba_posts",
        "total_estimate": 35000,
        "log": os.path.join(LOGS_DIR, "gap2_guba.log")
    },
    "gap3_flash_news": {
        "name": "7x24小时五年财经快讯库(新浪7x24倒序)",
        "script": os.path.join(SCRIPTS_DIR, "backfill_gap3_flash_news.py"),
        "db": os.path.join(DATA_DIR, "flash_news_5y_pit.db"),
        "table": "flash_news",
        "total_estimate": 250000,
        "log": os.path.join(LOGS_DIR, "gap3_flash_news.log")
    },
    "gap4_ir_surveys": {
        "name": "巨潮投资者关系活动记录表调研纪要全文",
        "script": os.path.join(SCRIPTS_DIR, "backfill_gap4_ir_surveys.py"),
        "db": os.path.join(DATA_DIR, "ir_survey_fulltext_5y_pit.db"),
        "table": "ir_surveys",
        "total_estimate": 17795,
        "log": os.path.join(LOGS_DIR, "gap4_ir_surveys.log")
    },
    "gap5_zt_micro_tape": {
        "name": "五年涨停池微观盘口明细(秒级封板/炸板/封单)",
        "script": os.path.join(SCRIPTS_DIR, "backfill_gap5_zt_micro_tape.py"),
        "db": os.path.join(DATA_DIR, "zt_micro_tape_5y_pit.db"),
        "table": "zt_micro_tape",
        "total_estimate": 75000,
        "log": os.path.join(LOGS_DIR, "gap5_zt_micro_tape.log")
    },
    "gap6_kline_5m": {
        "name": "五年首板股分时分钟线历史库",
        "script": os.path.join(SCRIPTS_DIR, "backfill_gap6_kline_5m.py"),
        "db": os.path.join(DATA_DIR, "first_board_5min_kline_5y.db"),
        "table": "kline_minute",
        "total_estimate": 500000,
        "log": os.path.join(LOGS_DIR, "gap6_kline_5m.log")
    }
}

def is_pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def get_db_stats(db_path, table_name):
    if not os.path.exists(db_path):
        return 0, []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
        cur = conn.cursor()
        cur.execute(f"SELECT count(*) FROM {table_name}")
        cnt = cur.fetchone()[0]
        cur.execute(f"SELECT * FROM {table_name} ORDER BY rowid DESC LIMIT 1")
        sample = cur.fetchone()
        conn.close()
        return cnt, sample
    except Exception as e:
        return 0, []

def launch_workers():
    pids = {}
    for gap_id, conf in GAPS_CONFIG.items():
        log_f = open(conf["log"], "a", encoding="utf-8")
        cmd = [sys.executable, "-u", conf["script"]]
        p = subprocess.Popen(cmd, stdout=log_f, stderr=log_f, close_fds=True)
        pids[gap_id] = p.pid
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 启动守护进程: {conf['name']} (PID: {p.pid}) -> {conf['log']}")
    return pids

def collect_status(pids, start_time):
    now = datetime.datetime.now()
    now_ts = time.time()
    elapsed_sec = max(1.0, now_ts - start_time)
    
    report = {
        "title": "五年六大历史数据缺口全量回补实时监控",
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": int(elapsed_sec),
        "all_workers_running": True,
        "gaps": {}
    }
    
    total_rows = 0
    
    for gap_id, conf in GAPS_CONFIG.items():
        pid = pids.get(gap_id)
        alive = is_pid_alive(pid) if pid else False
        if not alive:
            report["all_workers_running"] = False
            
        rows_cnt, sample = get_db_stats(conf["db"], conf["table"])
        total_rows += rows_cnt
        
        rate_per_sec = rows_cnt / elapsed_sec
        rem = max(0, conf["total_estimate"] - rows_cnt)
        eta_min = round(rem / (rate_per_sec + 0.001) / 60, 1) if rate_per_sec > 0 else 999.0
        
        # 读最后 3 行日志
        tail_logs = []
        if os.path.exists(conf["log"]):
            try:
                with open(conf["log"], "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    tail_logs = [l.strip() for l in lines[-3:] if l.strip()]
            except Exception:
                pass
                
        report["gaps"][gap_id] = {
            "name": conf["name"],
            "pid": pid,
            "status": "RUNNING" if alive else "FINISHED_OR_STOPPED",
            "db_path": conf["db"],
            "table": conf["table"],
            "rows_saved": rows_cnt,
            "total_estimate": conf["total_estimate"],
            "progress_pct": round(min(100.0, rows_cnt / conf["total_estimate"] * 100), 2),
            "rate_per_sec": round(rate_per_sec, 2),
            "eta_minutes": eta_min,
            "latest_log": tail_logs[-1] if tail_logs else "启动中..."
        }
        
    report["total_rows_saved"] = total_rows
    report["overall_rate_per_sec"] = round(total_rows / elapsed_sec, 2)
    
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        
    return report

if __name__ == "__main__":
    t0 = time.time()
    pids = launch_workers()
    # 等待 8 秒让各路完成初次写入
    time.sleep(8)
    rep = collect_status(pids, t0)
    print("\n=== 初次落盘进度统计 ===")
    print(f"累计已落盘总行数: {rep['total_rows_saved']}")
    for gid, ginfo in rep["gaps"].items():
        print(f"  [{ginfo['status']}] {ginfo['name']}: 已落盘 {ginfo['rows_saved']} 行, 速度 {ginfo['rate_per_sec']} 行/秒, 日志: {ginfo['latest_log']}")

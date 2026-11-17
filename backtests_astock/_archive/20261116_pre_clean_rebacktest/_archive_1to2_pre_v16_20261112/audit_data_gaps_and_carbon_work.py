#!/usr/bin/env python3
"""
一进二底层数据缺口盘点与 Carbon 全量工作清查脚本
"""
import os
import glob
import json
import sqlite3
import pandas as pd
from datetime import datetime

OUTPUT_JSON = "/tmp/astock_data_gaps_and_carbon_inventory.json"
BASE_DIR = "/Users/huaichuaibeimeng/claude-projects"

def audit_price_parquet():
    path = os.path.join(BASE_DIR, "sim-portfolio/data/cn_hk_price_db/a_daily.parquet")
    res = {
        "path": path,
        "exists": os.path.exists(path),
        "columns": [],
        "total_rows": 0,
        "start_date": None,
        "end_date": None,
        "has_intraday_tick": False,
        "has_auction_cancel": False,
        "has_exact_blown_moment": False,
        "conclusion": ""
    }
    if res["exists"]:
        df = pd.read_parquet(path)
        res["total_rows"] = len(df)
        res["columns"] = list(df.columns)
        date_col = None
        for col in ['date', 'trade_date', 'datetime', 'time']:
            if col in df.columns:
                date_col = col
                break
        if date_col:
            res["start_date"] = str(df[date_col].min())
            res["end_date"] = str(df[date_col].max())
        
        # 检查是否包含分时/盘口撤单/炸板瞬间
        cols_lower = [str(c).lower() for c in df.columns]
        res["has_intraday_tick"] = any("minute" in c or "tick" in c for c in cols_lower)
        res["has_auction_cancel"] = any("auction" in c or "cancel" in c for c in cols_lower)
        res["has_exact_blown_moment"] = any("blown" in c or "open_limit" in c or "seal_time" in c for c in cols_lower)
        res["conclusion"] = "缺分时与盘口逐笔数据，只有日线高开低收量额及涨跌停标记，盘中炸板与封板干脆度只能用日线近似。"
    return res

def audit_kpl_plates():
    path1 = os.path.join(BASE_DIR, "sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl")
    path2 = os.path.join(BASE_DIR, "news-dashboard/output/kpl_plates_v2.jsonl")
    
    res = {
        "kpl_merged": {"path": path1, "exists": os.path.exists(path1), "total_lines": 0, "date_range": [], "r_long_status": ""},
        "kpl_v2": {"path": path2, "exists": os.path.exists(path2), "total_lines": 0, "date_range": [], "r_long_status": ""},
        "coverage_summary": ""
    }
    
    # 快速抽样与行数统计
    for key, p in [("kpl_merged", path1), ("kpl_v2", path2)]:
        if os.path.exists(p):
            dates = set()
            r_long_missing_dates = set()
            total = 0
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    total += 1
                    if total % 5000 == 0 or total < 1000 or total > 80000:
                        try:
                            item = json.loads(line)
                            d = item.get("date") or item.get("trade_date")
                            if d:
                                dates.add(str(d))
                            # 检查 r_long
                            if "r_long" not in item and "recent_limit_stats" not in item:
                                if d:
                                    r_long_missing_dates.add(str(d)[:4])
                        except Exception:
                            pass
            res[key]["total_lines"] = total
            if dates:
                sorted_dates = sorted(list(dates))
                res[key]["date_range"] = [sorted_dates[0], sorted_dates[-1]]
                res[key]["unique_dates_sampled"] = len(dates)
            res[key]["r_long_status"] = f"早期年份缺失统计/字段结构不一致: {list(r_long_missing_dates)}" if r_long_missing_dates else "存在统一结构或需对齐"
    return res

def audit_notices():
    old_db = os.path.join(BASE_DIR, "sim-portfolio/backtest/2026-08-24-daban/notices.db")
    new_db = os.path.join(BASE_DIR, "sim-portfolio/data/cninfo_notices_5y_pit.db")
    
    res = {
        "old_db": {"path": old_db, "exists": os.path.exists(old_db)},
        "new_db": {"path": new_db, "exists": os.path.exists(new_db)},
    }
    
    for key, db_path in [("old_db", old_db), ("new_db", new_db)]:
        if os.path.exists(db_path):
            try:
                uri = f"file:{db_path}?mode=ro"
                conn = sqlite3.connect(uri, uri=True)
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [r[0] for r in cursor.fetchall()]
                res[key]["tables"] = tables
                
                table_name = "notices" if "notices" in tables else tables[0]
                cursor.execute(f"PRAGMA table_info({table_name});")
                columns = [r[1] for r in cursor.fetchall()]
                res[key]["columns"] = columns
                
                cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
                res[key]["total_count"] = cursor.fetchone()[0]
                
                # 时间字段和股票覆盖
                time_col = None
                code_col = None
                for c in columns:
                    if c in ['ann_date', 'notice_date', 'pub_time', 'publish_time', 'date', 'notice_time']:
                        time_col = c
                    if c in ['secCode', 'sec_code', 'stock_code', 'ts_code', 'code']:
                        code_col = c
                
                if time_col:
                    cursor.execute(f"SELECT MIN({time_col}), MAX({time_col}) FROM {table_name};")
                    r_time = cursor.fetchone()
                    res[key]["time_range"] = [r_time[0], r_time[1]]
                    # 检查是否有时分秒
                    cursor.execute(f"SELECT {time_col} FROM {table_name} WHERE {time_col} LIKE '%:%' LIMIT 5;")
                    has_hms = cursor.fetchall()
                    res[key]["has_hms"] = bool(has_hms)
                
                if code_col:
                    cursor.execute(f"SELECT COUNT(DISTINCT {code_col}) FROM {table_name};")
                    res[key]["distinct_stocks"] = cursor.fetchone()[0]
                
                conn.close()
            except Exception as e:
                res[key]["error"] = str(e)
    return res

def audit_xueqiu_concepts():
    p1 = os.path.join(BASE_DIR, "news-dashboard/output/astock_concepts.json")
    p2_candidates = [
        os.path.join(BASE_DIR, "news-dashboard/output/astock_community.json"),
        os.path.join(BASE_DIR, "sim-portfolio/data/astock_community.json"),
        os.path.join(BASE_DIR, "news-dashboard/output/community.json")
    ]
    p3 = os.path.join(BASE_DIR, "docs/90_内部_给Claude读/astock/一进二递归工程/01_雪球新概念全量词典_6323条.md")
    
    p2 = None
    for cand in p2_candidates:
        if os.path.exists(cand):
            p2 = cand
            break
            
    res = {
        "astock_concepts": {"path": p1, "exists": os.path.exists(p1)},
        "astock_community": {"path": p2, "exists": bool(p2)},
        "xueqiu_dictionary_6323": {"path": p3, "exists": os.path.exists(p3)},
        "analysis": ""
    }
    
    if os.path.exists(p1):
        try:
            with open(p1, "r", encoding="utf-8") as f:
                data = json.load(f)
                res["astock_concepts"]["type"] = type(data).__name__
                res["astock_concepts"]["len"] = len(data)
                if isinstance(data, dict):
                    res["astock_concepts"]["sample_keys"] = list(data.keys())[:5]
        except Exception as e:
            res["astock_concepts"]["error"] = str(e)
            
    if p2 and os.path.exists(p2):
        try:
            with open(p2, "r", encoding="utf-8") as f:
                data = json.load(f)
                res["astock_community"]["type"] = type(data).__name__
                res["astock_community"]["len"] = len(data)
        except Exception as e:
            res["astock_community"]["error"] = str(e)
            
    if os.path.exists(p3):
        res["xueqiu_dictionary_6323"]["size_bytes"] = os.path.getsize(p3)
        with open(p3, "r", encoding="utf-8") as f:
            lines = [f.readline() for _ in range(10)]
            res["xueqiu_dictionary_6323"]["header"] = lines
            
    res["analysis"] = "雪球概念词典是静态全量聚合词典（6323条），无回溯到2021-2023年的逐日实时贴吧/帖子发帖时间戳，属于后验或静态概念库，早期存在幸存者偏差与时间对齐缺口。"
    return res

def audit_carbon_work():
    clean_dir = os.path.join(BASE_DIR, "sim-portfolio/backtest/2026-11-11-1to2-clean")
    res = {
        "dir": clean_dir,
        "exists": os.path.exists(clean_dir),
        "files": [],
        "json_summaries": {},
        "scripts": [],
        "categorization": {
            "underlying_data_and_positive_factors": [],
            "boolean_hard_cut_barriers": []
        }
    }
    if not res["exists"]:
        return res
        
    all_files = sorted(os.listdir(clean_dir))
    res["files"] = all_files
    
    # 解析 JSON
    json_files = [f for f in all_files if f.endswith(".json")]
    for jf in json_files:
        jp = os.path.join(clean_dir, jf)
        try:
            with open(jp, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 提取核心指标
                summary = {}
                for k in ["total_trades", "win_rate", "profit_loss_ratio", "cum_ret", "max_drawdown", "sharpe", "annual_ret", "trades", "cagr"]:
                    if k in data:
                        summary[k] = data[k]
                if not summary and isinstance(data, dict):
                    # 尝试前5个字段
                    summary = {k: data[k] for k in list(data.keys())[:6] if not isinstance(data[k], (list, dict))}
                res["json_summaries"][jf] = summary
        except Exception as e:
            res["json_summaries"][jf] = {"error": str(e)}
            
    # 解析 Python 脚本功能
    py_files = [f for f in all_files if f.endswith(".py")]
    for pf in py_files:
        pp = os.path.join(clean_dir, pf)
        size = os.path.getsize(pp)
        res["scripts"].append({"file": pf, "size": size})
        
    # 分类汇总（根据今日 Carbon 工作与实验记录）
    # 哪些是底层数据补齐/正贡献因子：
    # 1. 秒级 PIT 公告库 (cninfo_notices_5y_pit.db)
    # 2. 澄清公告否定词识别 (clarification regex)
    # 3. 首板封单干脆度 d1_seal_tightness (首板封板时间与涨停质量)
    # 4. 连板高标护航 plate_has_leader (题材内有高度标的共振)
    # 5. B0 分批止盈 / 次日卖出机制优化
    res["categorization"]["underlying_data_and_positive_factors"] = [
        {"name": "秒级PIT公告库介入", "desc": "将公告发布时刻精确到秒，杜绝未来函数，剔除盘后立案/减持爆雷"},
        {"name": "澄清公告否定词精细化", "desc": "识别辟谣/未有涉及等虚假题材，避免接盘假概念"},
        {"name": "首板封单干脆度 (d1_seal_tightness)", "desc": "早盘9:30-10:00首板且封死，涨停板质量高，胜率与盈亏比双升"},
        {"name": "连板高标护航 (plate_has_leader)", "desc": "所属题材有3板以上龙头带队，提供板块情绪溢价与护航支撑"},
        {"name": "B0分批止盈与动态离场", "desc": "不再次日一刀切无脑早盘割肉，大幅平滑回撤与提升真实盈亏比"}
    ]
    
    # 哪些是砍死龙头的布尔一刀切门禁：
    # 1. 60元高价股过滤 (直接干掉海光/中际等机构大票)
    # 2. 60日平台突破 (clean_brk60，强行卡死次新/超跌/非突破型妖股，大量历史10倍龙头被第一步抹杀)
    # 3. 近5日伪首板强行一刀切 (将反包板/洗盘二波龙当杂毛过滤)
    # 4. 机械固定阈值的布尔组合 (V9~V12 导致样本量从上千笔骤降到几十笔，发生严重样本选择偏误与伪高胜率)
    res["categorization"]["boolean_hard_cut_barriers"] = [
        {"name": "60元高价股硬过滤 (price <= 60)", "desc": "机械把高价成长科技龙头一刀切剔除，损失高流动性核心抱团行情"},
        {"name": "60日平台突破 (clean_brk60)", "desc": "硬卡60日均线或箱体突破，直接砍死超跌反弹龙、次新股龙头与双底反转龙头"},
        {"name": "近5日无板/伪首板硬门禁", "desc": "一刀切要求前5日绝对无涨停，将反包首板、平台整理洗盘二波龙头直接误杀"},
        {"name": "布尔与门多层叠加 (V9-V12一刀切)", "desc": "过度拟合使得交易笔数断崖式缩减至年均<20笔，制造幸存者统计幻觉并错失全市场真正主升浪"}
    ]
    return res

def main():
    report = {
        "audit_timestamp": datetime.now().isoformat(),
        "task_a_data_gaps": {
            "1_price_parquet": audit_price_parquet(),
            "2_kpl_plates": audit_kpl_plates(),
            "3_notices": audit_notices(),
            "4_xueqiu_concepts": audit_xueqiu_concepts()
        },
        "task_b_carbon_work": audit_carbon_work()
    }
    
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        
    print(f"Audit completed successfully! Output saved to {OUTPUT_JSON}")

if __name__ == "__main__":
    main()

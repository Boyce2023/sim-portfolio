#!/usr/bin/env python3
"""
Pre-extract point-in-time regulatory, speech, Politburo, CSRC, and Exchange surveillance events
from local astock_news_5y_pit.db (107,599 timestamped items, 2022-03 to 2026-11).
"""
import json
import os
import re
import sqlite3

DB_PATH = "file:/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/astock_news_5y_pit.db?mode=ro"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/shards/raw_pit_slices"
os.makedirs(OUT_DIR, exist_ok=True)

con = sqlite3.connect(DB_PATH, uri=True)
cur = con.cursor()

# High-signal regulatory / speech keywords
HIGH_SIGNAL_RE = re.compile(
    r"(证监会|吴清|易会满|李超|方星海|政治局会议|中央政治局|中央经济工作会议|中央金融工作会议|"
    r"国新办.*发布会|国务院常务会议|国常会|新国九条|国九条|金融委|刘鹤|何立峰|潘功胜|"
    r"中央汇金|汇金公司|中国国新|中国诚通|互换便利|回购增持再贷款|印花税|暂停转融券|转融通|"
    r"量化交易|程序化交易|违规减持|减持新规|减持管理|并购六条|科创板八条|市值管理指引|"
    r"陆家嘴论坛|金融街论坛|资本市场学术年会)"
)

EXCHANGE_SURV_RE = re.compile(
    r"(重点监控|停牌核查|严重异动|异常交易.*监管措施|采取自律监管|上交所.*监管动态|深交所.*监管动态|北交所.*监管动态)"
)

rows = cur.execute(
    "SELECT id, pub_datetime_cst, avail_trade_date, title, content FROM news_pit ORDER BY pub_datetime_cst ASC"
).fetchall()

high_22_23 = []
high_24 = []
high_25_26 = []
exch_surv = []

for rid, dt_str, avail_td, title, content in rows:
    text = f"{title or ''} {content or ''}"
    rec = {
        "id": rid,
        "pub_datetime_cst": dt_str,
        "avail_trade_date": avail_td,
        "title": (title or "")[:120],
        "snippet": (content or "")[:380],
    }
    if EXCHANGE_SURV_RE.search(text):
        exch_surv.append(rec)
    if HIGH_SIGNAL_RE.search(text):
        yr = (dt_str or "")[:4]
        if yr in ("2022", "2023"):
            high_22_23.append(rec)
        elif yr == "2024":
            high_24.append(rec)
        else:
            high_25_26.append(rec)

for name, arr in [
    ("pit_high_2022_2023.json", high_22_23),
    ("pit_high_2024.json", high_24),
    ("pit_high_2025_2026.json", high_25_26),
    ("pit_exchange_surveillance_2022_2026.json", exch_surv),
]:
    p = os.path.join(OUT_DIR, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(arr, f, ensure_ascii=False, indent=2)
    print(f"Wrote {name}: {len(arr)} records")

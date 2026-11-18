#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Extract National Team & Window-Guidance (Not Sell) candidate events
strictly from read-only local SQLite DBs (flash_news, astock_news, cninfo_notices).
"""
import os, json, re, sqlite3

DATA_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data"
OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/national_team"
os.makedirs(OUT_DIR, exist_ok=True)


def ro_conn(name):
    p = os.path.join(DATA_DIR, name)
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def extract_flash():
    con = ro_conn("flash_news_5y_pit.db")
    sql = """
    SELECT news_id, source, pub_datetime_cst, title, content
    FROM flash_news
    WHERE title LIKE '%窗口指导%' OR content LIKE '%窗口指导%'
       OR title LIKE '%限制卖出%' OR content LIKE '%限制卖出%'
       OR title LIKE '%禁止卖出%' OR content LIKE '%禁止卖出%'
       OR title LIKE '%不准卖%' OR content LIKE '%不准卖%'
       OR title LIKE '%不得净卖%' OR content LIKE '%不得净卖%'
       OR title LIKE '%净卖出%' OR content LIKE '%净卖出%'
       OR title LIKE '%灵均%' OR content LIKE '%灵均%'
       OR title LIKE '%DMA%' OR content LIKE '%DMA%'
       OR title LIKE '%转融券%' OR content LIKE '%转融券%'
       OR title LIKE '%汇金%' OR content LIKE '%汇金%'
       OR title LIKE '%证金%' OR content LIKE '%证金%'
       OR title LIKE '%国新%' OR content LIKE '%国新%'
       OR title LIKE '%诚通%' OR content LIKE '%诚通%'
       OR title LIKE '%国家队%' OR content LIKE '%国家队%'
       OR title LIKE '%互换便利%' OR content LIKE '%互换便利%'
    ORDER BY pub_datetime_cst ASC
    """
    rows = con.execute(sql).fetchall()
    con.close()

    # Keep high-signal subset for Not Sell & National Team
    pat_ns = re.compile(
        r"(窗口指导.*(卖|净|基金|券商|险资|公募|私募|量化|股市|A股)|"
        r"(不得|禁止|限制|暂停|不准|停止).{0,10}(净卖出|卖出|减持|转融券|做空|融券)|"
        r"(公募|基金|券商|自营|险资|保险|机构|量化|私募).{0,12}(净买入|净卖出|开盘|收盘|30分钟|不得卖出)|"
        r"灵均|DMA.*(限制|暂停|压降|清退)|暂停.*转融券|限制.*卖出)"
    )
    pat_nt = re.compile(
        r"(中央汇金|汇金公司|汇金.*(ETF|增持|减持|卖出|买入|护盘|四大行)|"
        r"中国国新|国新投资|中国诚通|诚通.*增持|证金公司|"
        r"国家队.*(进场|入场|出手|护盘|买|卖|减持|退出|ETF)|"
        r"平准基金|互换便利.*(操作|落地|批复|招标|启动)|股票回购增持再贷款)"
    )
    ns_list, nt_list = [], []
    for nid, src, dt, ttl, txt in rows:
        full = f"{ttl or ''} || {txt or ''}"
        rec = {"id": nid, "source": src, "dt": dt, "title": ttl or "", "content": (txt or "")[:500]}
        if pat_ns.search(full):
            ns_list.append(rec)
        if pat_nt.search(full):
            nt_list.append(rec)
    return ns_list, nt_list


def extract_astock_and_cninfo():
    con2 = ro_conn("astock_news_5y_pit.db")
    rows2 = con2.execute(
        "SELECT id, source, pub_datetime_cst, avail_trade_date, title, content FROM news_pit "
        "WHERE title LIKE '%汇金%' OR content LIKE '%汇金%' OR title LIKE '%窗口指导%' OR content LIKE '%窗口指导%' "
        "OR title LIKE '%净卖出%' OR content LIKE '%限制卖出%' OR title LIKE '%转融券%' OR content LIKE '%转融券%' "
        "OR title LIKE '%国家队%' OR content LIKE '%国家队%' OR title LIKE '%诚通%' OR title LIKE '%国新投资%' "
        "ORDER BY pub_datetime_cst ASC"
    ).fetchall()
    con2.close()
    news_hits = [{"id": r[0], "source": r[1], "dt": r[2], "avail_td": r[3], "title": r[4], "content": (r[5] or "")[:400]} for r in rows2]

    con3 = ro_conn("cninfo_notices_5y_pit.db")
    rows3 = con3.execute(
        "SELECT ann_id, sec_code, sec_name, title, ann_type, pub_datetime_cst, trade_date_avail FROM notices "
        "WHERE title LIKE '%中央汇金%' OR title LIKE '%中国国新%' OR title LIKE '%中国诚通%' OR title LIKE '%证金%' "
        "ORDER BY pub_datetime_cst ASC"
    ).fetchall()
    con3.close()
    cn_hits = [{"id": r[0], "code": r[1], "name": r[2], "title": r[3], "type": r[4], "dt": r[5], "avail_td": r[6]} for r in rows3]
    return news_hits, cn_hits


if __name__ == "__main__":
    ns, nt = extract_flash()
    ah, ch = extract_astock_and_cninfo()
    out = {
        "flash_not_sell_cnt": len(ns), "flash_not_sell": ns,
        "flash_national_team_cnt": len(nt), "flash_national_team": nt,
        "astock_news_cnt": len(ah), "astock_news": ah,
        "cninfo_cnt": len(ch), "cninfo": ch,
    }
    p = os.path.join(OUT_DIR, "raw_db_candidates.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"DONE -> {p}: not_sell={len(ns)}, nat_team={len(nt)}, astock_news={len(ah)}, cninfo={len(ch)}")

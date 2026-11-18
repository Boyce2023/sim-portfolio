#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
pit_data_loaders.py
Strict PIT (zero-lookahead) data loaders for all external databases used in s_pry 30-factor exit mining.
All SQLite connections use ?mode=ro. Zero yfinance (D12).
"""
import os, re, json, glob, sqlite3, datetime
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"

RE_LHASA = re.compile(r"拉萨")
RE_DAYSURF = re.compile(
    r"(?:杭州上塘路|上塘路|宜昌沿江大道|宜昌珍珠路|佛山绿景路|佛山季华六路|佛山季华五路|"
    r"江阴.*营业部|苏州.*营业部|消闲派|苏南帮|财通.*杭州上塘路)"
)
RE_TOP_YOUZI = re.compile(
    r"(?:章建平|国泰君安.*江苏路|中信.*东阳|中信.*西安朱雀|华泰.*总部|国盛.*慈溪|"
    r"中国银河.*大连金马路|联储.*宁波|六一中路|呼家楼|中信建投.*北京朝外|陈小群|"
    r"东亚前海.*苏州留园|大连金马路|大连黄河路|上海江苏路|上海建国西路|杭州延安路|"
    r"西安朱雀大街|南京太平南路|宁波桑田路|上海宛平南路|上海红宝石路|上海茅台路|"
    r"宁波和源路|北京长椿街)"
)
RE_QUANT = re.compile(
    r"(?:华鑫.*上海分公司|中金.*上海分公司|国际金融.*上海分公司|东亚前海.*上海分公司|"
    r"瑞银证券|高盛|摩根大通|中信.*上海分公司|开源.*西安西大街|国泰君安.*总部)"
)
RE_INST = re.compile(r"机构专用")
RE_NORTH = re.compile(r"股通专用")

EVENT_BASKET_PLATES = {
    "并购重组", "股权转让", "资产注入", "国企改革", "央企改革",
    "地方国资改革", "业绩增长", "预盈预增", "摘帽", "回购",
    "增持", "次新股", "高送转", "参股新股"
}
NON_THEME = {"其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长", "年报增长", "一季报增长", "中报增长", "次新股"}

BAD_NOTICE_RE = re.compile(
    r"(?:减持|清仓|平仓|立案|调查|违法|违规|处罚|留置|逮捕|刑拘|退市|终止上市|风险警示|"
    r"预亏|亏损|大幅下降|下修|计提.*减值|逾期|违约|冻结|监管函|监管工作函|关注函|警示函|"
    r"问询函|停牌核查|风险提示|澄清|不存在|不涉及|未筹划|异常波动|严重异常波动)"
)
HARD_BAD_NOTICE_RE = re.compile(
    r"(?:减持|立案|调查|违法|违规|处罚|退市|终止上市|预亏|下修|监管函|监管工作函|关注函|警示函|问询函|停牌核查|澄清)"
)
GOOD_NOTICE_RE = re.compile(r"(?:回购|增持|不减持|预增|扭亏|大幅增长|中标|重大合同|重组|收购|控制权变更)")
REG_INC_WORDS = ("监管工作函", "监管函", "关注函", "重点监控", "停牌核查")
REG_EXC_WORDS = ("ST", "回复", "回函", "延期", "核查意见", "复牌", "募集资金", "监事", "独立董事", "保荐")


def load_lhb_pit(target_codes: set) -> dict:
    """Load deduped LHB seat summary per (dt, c6), preferring 1-day board over 3-day board."""
    lb = pd.read_parquet(f"{SIM}/backtest/2026-10-20-lhasa/lhb_buy.parquet")
    ls = pd.read_parquet(f"{SIM}/backtest/2026-10-20-lhasa/lhb_sell.parquet")
    for d in (lb, ls):
        d["dt"] = d["TRADE_DATE"].astype(str).str[:10]
        d["c6"] = d["SECURITY_CODE"].astype(str).str[:6]
    lb = lb[(lb["dt"] >= "2021-10-01") & lb["c6"].isin(target_codes)].copy()
    ls = ls[(ls["dt"] >= "2021-10-01") & ls["c6"].isin(target_codes)].copy()

    by_k_buy = defaultdict(list)
    for r in lb.itertuples(index=False):
        by_k_buy[(r.dt, r.c6)].append(r)
    by_k_sell = defaultdict(list)
    for r in ls.itertuples(index=False):
        by_k_sell[(r.dt, r.c6)].append(r)

    lhb_map = {}
    for k in set(by_k_buy.keys()) | set(by_k_sell.keys()):
        b_rows = by_k_buy.get(k, [])
        s_rows = by_k_sell.get(k, [])
        all_rows = b_rows + s_rows
        # Pick 1-day TRADE_ID if present, else latest TRADE_ID
        tid_1d = [r.TRADE_ID for r in all_rows if "三个交易日" not in str(r.EXPLANATION) and "连续" not in str(r.EXPLANATION)]
        chosen_tid = max(tid_1d) if tid_1d else max(r.TRADE_ID for r in all_rows)
        b_tid = [r for r in b_rows if r.TRADE_ID == chosen_tid]
        s_tid = [r for r in s_rows if r.TRADE_ID == chosen_tid]

        # Dedup seats appearing on both top-5 buy and top-5 sell of same TRADE_ID
        seen_seats = {}
        buy_side_names = []
        buy_side_tot = 0.0
        buy_side_lhasa = 0.0
        lhasa_buy_cnt = 0
        daysurf_buy = False
        top_yz_buy = False
        top_yz_sell = False
        quant_cnt = 0

        for r in b_tid:
            nm = str(r.OPERATEDEPT_NAME or "")
            bv = float(r.BUY or 0.0)
            sv = float(r.SELL or 0.0)
            buy_side_names.append(nm)
            buy_side_tot += bv
            if RE_LHASA.search(nm):
                lhasa_buy_cnt += 1
                buy_side_lhasa += bv
            if RE_DAYSURF.search(nm):
                daysurf_buy = True
            if RE_TOP_YOUZI.search(nm):
                top_yz_buy = True
            seen_seats[(nm, round(bv, 1), round(sv, 1))] = (nm, bv, sv)

        for r in s_tid:
            nm = str(r.OPERATEDEPT_NAME or "")
            bv = float(r.BUY or 0.0)
            sv = float(r.SELL or 0.0)
            if RE_TOP_YOUZI.search(nm) and sv > bv:
                top_yz_sell = True
            seen_seats[(nm, round(bv, 1), round(sv, 1))] = (nm, bv, sv)

        inst_buy = inst_sell = north_net = tot_buy = tot_sell = 0.0
        lhasa_all_cnt = 0
        for nm, bv, sv in seen_seats.values():
            tot_buy += bv
            tot_sell += sv
            if RE_INST.search(nm):
                inst_buy += bv
                inst_sell += sv
            if RE_NORTH.search(nm):
                north_net += (bv - sv)
            if RE_QUANT.search(nm):
                quant_cnt += 1
            if RE_LHASA.search(nm):
                lhasa_all_cnt += 1

        lhb_map[k] = {
            "lhasa_buy_cnt": lhasa_buy_cnt,
            "lhasa_all_cnt": lhasa_all_cnt,
            "lhasa_buy_sh": (buy_side_lhasa / buy_side_tot) if buy_side_tot > 0 else 0.0,
            "daysurf_buy": daysurf_buy,
            "inst_buy": inst_buy,
            "inst_sell": inst_sell,
            "inst_net": inst_buy - inst_sell,
            "top_yz_buy": top_yz_buy,
            "top_yz_sell": top_yz_sell,
            "quant_cnt": quant_cnt,
            "north_net": north_net,
            "tot_buy": tot_buy,
            "tot_sell": tot_sell,
            "lhb_net": tot_buy - tot_sell,
        }
    return lhb_map


def load_notices_and_reg_pit(target_codes: set) -> tuple[dict, dict]:
    """Load stock notices with exact pub_datetime_cst and exchange-level reg letters."""
    stock_notices = defaultdict(list)
    ex_reg = {"SH": [], "SZ": []}
    seen_title = defaultdict(set)

    def _add_notice(c6, pdt, title):
        if not pdt or c6 not in target_codes:
            return
        t = str(title or "").strip()
        k = (pdt[:16], t[:40])
        if k in seen_title[c6]:
            return
        seen_title[c6].add(k)
        is_bad = bool(BAD_NOTICE_RE.search(t))
        is_hard_bad = bool(HARD_BAD_NOTICE_RE.search(t))
        is_good = (not is_bad) and bool(GOOD_NOTICE_RE.search(t))
        if is_bad or is_hard_bad or is_good:
            stock_notices[c6].append((str(pdt), is_bad, is_hard_bad, is_good, t))

    def _add_ex_reg(c6, dt_s, title):
        t = str(title or "")
        if any(w in t for w in REG_EXC_WORDS):
            return
        if any(w in t for w in REG_INC_WORDS) and c6.startswith(("00", "60")):
            ex = "SH" if c6.startswith("60") else "SZ"
            ex_reg[ex].append((dt_s[:10], c6))

    # 1. cninfo_notices_5y_pit.db
    con_c = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    ph = ",".join(["?"] * len(target_codes))
    for sc, pdt, ti in con_c.execute(
        f"SELECT sec_code, pub_datetime_cst, title FROM notices WHERE sec_code IN ({ph}) AND pub_datetime_cst >= '2021-09-01'",
        sorted(target_codes),
    ):
        _add_notice(str(sc)[:6].zfill(6), str(pdt), ti)
    for sc, pdt, ti in con_c.execute(
        "SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= '2021-09-01' "
        "AND (title LIKE '%监管%' OR title LIKE '%关注函%' OR title LIKE '%停牌核查%' OR title LIKE '%重点监控%')"
    ):
        _add_ex_reg(str(sc)[:6].zfill(6), str(pdt), ti)
    con_c.close()

    # 2. pit_reg_tox_notices_5y_complete.parquet
    tox = pd.read_parquet(f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet")
    for r in tox.itertuples(index=False):
        c6 = str(r.sec_code)[:6].zfill(6)
        pdt = str(r.pub_datetime_cst)
        ti = str(r.title or "")
        _add_notice(c6, pdt, ti)
        _add_ex_reg(c6, pdt, ti)

    # 3. notices.db (strictly ndate + ' 18:00:00' conservative timestamp if not already in cninfo, so only < dt_k 09:25 when ndate < dt_k!)
    con_d = sqlite3.connect(f"file:{SIM}/backtest/2026-08-24-daban/notices.db?mode=ro", uri=True)
    for sc, nd, ti in con_d.execute(
        f"SELECT code, ndate, title FROM notice WHERE code IN ({ph}) AND ndate >= '2025-01-01'",
        sorted(target_codes),
    ):
        _add_notice(str(sc)[:6].zfill(6), f"{str(nd)[:10]} 20:00:00", ti)
    for sc, nd, ti in con_d.execute(
        "SELECT code, ndate, title FROM notice WHERE ndate >= '2025-01-01' "
        "AND (title LIKE '%监管%' OR title LIKE '%关注函%' OR title LIKE '%停牌核查%' OR title LIKE '%重点监控%')"
    ):
        _add_ex_reg(str(sc)[:6].zfill(6), str(nd)[:10], ti)
    con_d.close()

    # 4. zdjk files
    for zf in glob.glob(f"{SIM}/data/kpl/zdjk/*.json"):
        try:
            for it in json.load(open(zf, "r", encoding="utf-8")).get("List", []):
                c6 = str(it[0]).zfill(6)
                d_s = str(it[2])[:10]
                if c6.startswith(("00", "60")):
                    ex_reg["SH" if c6.startswith("60") else "SZ"].append((d_s, c6))
                _add_notice(c6, f"{d_s} 18:00:00", f"重点监控 {it[1]}")
        except Exception:
            pass

    for c6 in stock_notices:
        stock_notices[c6].sort(key=lambda x: x[0])

    # Dedup exchange reg letters within 7 calendar days per stock (matching fast_high_dragon_today.py)
    for ex in ("SH", "SZ"):
        ded, seen = [], {}
        for dt_s, c6 in sorted(set(ex_reg[ex])):
            dt_obj = datetime.date.fromisoformat(dt_s)
            if c6 not in seen or (dt_obj - seen[c6]).days > 7:
                seen[c6] = dt_obj
                ded.append((dt_s, c6))
        ex_reg[ex] = ded

    return stock_notices, ex_reg

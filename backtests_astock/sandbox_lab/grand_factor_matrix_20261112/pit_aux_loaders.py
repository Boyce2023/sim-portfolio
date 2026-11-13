#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Helper loaders (LHB Lhasa, Cninfo Notices, IR Surveys, Community Posts, Theme Elo) for Grand Factor Matrix."""
import os, sys, re, json, bisect, sqlite3, datetime
from collections import defaultdict
import numpy as np
import pandas as pd

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
CLEAN_DIR = f"{BASE}/backtest/2026-11-11-1to2-clean"
if CLEAN_DIR not in sys.path:
    sys.path.insert(0, CLEAN_DIR)

from exp1_fake_theme_purifier import (
    build_8y_purified_theme_metadata,
    HARD_NOTICE_PAT, MA_NOTICE_PAT, EARN_NOTICE_PAT, BAD_NOTICE_PAT, NEG_NOTICE_PAT
)

CSRC_PURE_OUTSIDER = {
    "A01","A02","A03","A04","A05","D44","D45","D46","E47","E48","E49","E50",
    "F51","F52","G53","G54","G55","G56","G58","G59","H61","H62","K70","L72","N77","N78",
    "C13","C14","C15","C17","C18","C19","C20","C21","C22"
}
HARD_TECH_RE = re.compile(
    r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)"
)


def load_aux_pit_sources(target_codes_set):
    # 1. CSRC Industry & Stock Names
    csrc_p = f"{BASE}/data/csrc_industry_l2.csv"
    if not os.path.exists(csrc_p):
        csrc_p = f"{BASE}/backtest/2026-10-15-review2022/industry.csv"
    ind_df = pd.read_csv(csrc_p)
    ind_df["c6"] = ind_df["code"].astype(str).str[-6:]
    ind_map = dict(zip(ind_df["c6"], ind_df["industry"].fillna("")))
    name_col = "code_name" if "code_name" in ind_df.columns else ("name" if "name" in ind_df.columns else None)
    name_map = dict(zip(ind_df["c6"], ind_df[name_col].fillna(""))) if name_col else {}

    # 2. Micro-Tape
    conn_t = sqlite3.connect(f"file:{BASE}/data/zt_micro_tape_5y_pit.db?mode=ro", uri=True)
    df_tape = pd.read_sql_query("SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape WHERE trade_date >= '2021-10-01'", conn_t)
    conn_t.close()
    tape_map = {(r.trade_date, str(r.sec_code)[:6]): (str(r.first_seal_time or "99:99:99"), float(r.seal_amount or 0.0), int(r.open_board_count or 0))
                for r in df_tape.itertuples(index=False)}

    # 3. LHB Lhasa Retail Seats
    lhasa_map = {}
    lhb_p = f"{BASE}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
    if os.path.exists(lhb_p):
        lhb = pd.read_parquet(lhb_p, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY"])
        lhb["dt"] = lhb["TRADE_DATE"].astype(str).str[:10]
        lhb = lhb[lhb["dt"] >= "2021-10-01"].copy()
        lhb["c6"] = lhb["SECURITY_CODE"].astype(str).str[:6]
        lhb["is_lhasa"] = lhb["OPERATEDEPT_NAME"].astype(str).str.contains("拉萨", na=False).astype(int)
        grp = lhb.groupby(["dt", "c6"], as_index=False).agg(
            lhasa_cnt=("is_lhasa", "sum"),
            tot_buy=("BUY", "sum"),
            lhasa_buy=("BUY", lambda s: s[lhb.loc[s.index, "is_lhasa"] == 1].sum())
        )
        for r in grp.itertuples(index=False):
            sh = float(r.lhasa_buy / r.tot_buy) if r.tot_buy and r.tot_buy > 0 else 0.0
            lhasa_map[(r.dt, r.c6)] = (int(r.lhasa_cnt), round(sh, 4))

    # 4. Cninfo PIT Notices (< T 09:25:00)
    notice_by_c6 = defaultdict(list)
    not_p = f"{BASE}/data/cninfo_notices_5y_pit.db"
    if os.path.exists(not_p):
        conn_n = sqlite3.connect(f"file:{not_p}?mode=ro", uri=True)
        for sec_code, pub_dt, avail_dt, title in conn_n.execute(
            "SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= '2021-12-20'"
        ):
            c6 = str(sec_code)[:6].zfill(6)
            if c6 not in target_codes_set or not pub_dt:
                continue
            ts = str(title or "")
            is_bad = bool(NEG_NOTICE_PAT.search(ts)) or bool(BAD_NOTICE_PAT.search(ts))
            is_earn = bool(EARN_NOTICE_PAT.search(ts))
            is_hard = (not is_bad) and bool(HARD_NOTICE_PAT.search(ts))
            is_ma = (not is_bad) and bool(MA_NOTICE_PAT.search(ts))
            if is_bad or is_earn or is_hard or is_ma:
                notice_by_c6[c6].append((str(pub_dt), str(avail_dt or ""), (is_hard, is_ma, is_earn, is_bad)))
        conn_n.close()
        for c6 in notice_by_c6:
            notice_by_c6[c6].sort(key=lambda x: x[0])

    # 5. Institutional Surveys (IR QA)
    ir_grp = {}
    ir_p = f"{BASE}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db"
    if os.path.exists(ir_p):
        conn_ir = sqlite3.connect(f"file:{ir_p}?mode=ro", uri=True)
        ir_df = pd.read_sql_query("SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE pub_datetime_cst >= '2021-12-01'", conn_ir)
        conn_ir.close()
        ir_df["c6"] = ir_df["sec_code"].astype(str).str[:6]
        ir_grp = ir_df.groupby("c6")["pub_datetime_cst"].apply(lambda s: np.sort(s.unique())).to_dict()

    # 6. Community Retail Heat (Xueqiu/Guba posts)
    comm_grp = {}
    comm_p = f"{BASE}/data/astock_community_5y_pit.db"
    if os.path.exists(comm_p):
        conn_c = sqlite3.connect(f"file:{comm_p}?mode=ro", uri=True)
        cdf = pd.read_sql_query("SELECT symbol, pub_datetime_cst FROM community_posts WHERE pub_datetime_cst >= '2021-12-25'", conn_c)
        conn_c.close()
        cdf["c6"] = cdf["symbol"].astype(str).str[-6:]
        cdf = cdf[cdf["c6"].isin(target_codes_set)]
        comm_grp = cdf.groupby("c6")["pub_datetime_cst"].apply(lambda s: np.sort(s.values)).to_dict()

    return ind_map, name_map, tape_map, lhasa_map, notice_by_c6, ir_grp, comm_grp, build_8y_purified_theme_metadata

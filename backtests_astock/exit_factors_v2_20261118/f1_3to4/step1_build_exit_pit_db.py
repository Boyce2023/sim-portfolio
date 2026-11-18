#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
step1_build_exit_pit_db.py
构建三进四 V4.0 持仓期跨策略动态卖点因子 (XF01~XF30) 的完全前视 (PIT) 数据底座。
支持任意物理截断日期 max_date（如 2026-11-16 全量 与 2024-12-31 截断硬测试）。
⛔ 严禁 import yfinance (D12)；所有 SQLite 使用 file:...?mode=ro 只读。
"""

import bisect
from collections import Counter, defaultdict
import datetime
import glob
import json
import os
import pickle
import re
import sqlite3
import sys
import time

sys.dont_write_bytecode = True

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 VIOLATION"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
S1_DIR = f"{SIM}/backtests_astock/exit_opt_20261118/s1_3to4_exit"
OUT_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4"
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, UPG_DIR)
import upgrade_3to4_pit as u34

# 龙虎榜营业部正则（合并高标 V5.1 + 三进四 V4.0，兼容 2025 国泰海通更名且防误伤江苏南京）
RE_LHASA = re.compile(r"拉萨")
RE_INST = re.compile(r"机构专用")
RE_DAY_SURF = re.compile(
    r"(?:杭州上塘路|宜昌沿江大道|宜昌珍珠路|国泰.*宜昌|佛山绿景路|佛山季华六路|佛山季华五路|"
    r"佛山.*路|江阴.*营业部|东吴证券.*苏州|华泰证券.*苏州|国盛.*苏南|苏南分公司|开源.*西安西大街)"
)
RE_TOP_YOUZI = re.compile(
    r"(?:大连金马路|大连黄河路|六一中路|天津东丽开发区二纬路|北京东直门南大街|北京广渠门内大街|"
    r"上海江苏路|上海建国西路|杭州延安路|兴业证券.*陕西分公司|西安朱雀大街|"
    r"南京太平南路|宁波桑田路|上海宛平南路|上海红宝石路|上海茅台路|宁波和源路|北京长椿街)"
)
RE_QUANT = re.compile(
    r"(?:华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|"
    r"开源.*西安西大街|国泰(?:君安|海通).*总部|摩根大通)"
)

LHB_CAT_EXPLAIN_RE = re.compile(r"(?:10个交易日|30个交易日|严重异常)")
LHB_CAT_NAMES = {"自然人", "中小投资者", "其他自然人", "机构投资者", "深股通投资者", "机构", "沪股通", "投资者分类"}

# 公告识别正则（PIT < target_dt 09:25:00）
RE_ABN_NOTICE = re.compile(r"(?:股票交易异常波动|异常波动公告)")
RE_CLARIFY = re.compile(r"澄清")
RE_HALT_WARN = re.compile(r"(?:严重异常波动|停牌核查|击鼓传花|脱离基本面|交易风险提示)")
RE_REDUCE_TOX = re.compile(r"(?:减持计划|股东减持|减持股份预披露|立案调查|收到立案|退市风险)")
RE_TECH_KPL = re.compile(r"(?:算力|芯片|半导体|机器人|人工智能|AI|华为|低空|固态电池)")


def _build_lhb_pit_map(max_date: str, target_codes: set, daily_amt_map: dict, all_dts: list) -> dict:
    """加载并清洗 lhb_buy & lhb_sell（剔除10/30日投资者分类统计，优选单日主榜防重复累计）。"""
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}
    cols = ["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL", "EXPLANATION", "TRADE_ID"]
    lb = pd.read_parquet(f"{SIM}/backtest/2026-10-20-lhasa/lhb_buy.parquet", columns=cols)
    ls = pd.read_parquet(f"{SIM}/backtest/2026-10-20-lhasa/lhb_sell.parquet", columns=cols)

    def _clean(df_in: pd.DataFrame) -> pd.DataFrame:
        df_in["dt"] = df_in["TRADE_DATE"].astype(str).str[:10]
        df_in["c6"] = df_in["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
        m = (
            (df_in["dt"] >= "2021-10-01")
            & (df_in["dt"] <= max_date)
            & df_in["c6"].isin(target_codes)
            & (~df_in["EXPLANATION"].astype(str).str.contains(LHB_CAT_EXPLAIN_RE, na=False))
            & (~df_in["OPERATEDEPT_NAME"].astype(str).isin(LHB_CAT_NAMES))
        )
        out = df_in[m].copy()
        out["is_3day"] = out["EXPLANATION"].astype(str).str.contains("连续", na=False)
        out["tid"] = out["TRADE_ID"].astype(str)
        return out

    lb = _clean(lb)
    ls = _clean(ls)

    # 对每个 (dt, c6) 选定单一主 TRADE_ID（优先单日榜，按买卖总金额降序选主榜）
    buy_by_tid = defaultdict(list)
    tid_meta = {}
    for r in lb.itertuples(index=False):
        k = (r.dt, r.c6, r.tid)
        b_v = float(r.BUY or 0.0)
        s_v = float(r.SELL or 0.0)
        buy_by_tid[k].append((str(r.OPERATEDEPT_NAME), b_v, s_v))
        cur = tid_meta.get(k)
        if cur is None:
            tid_meta[k] = [bool(r.is_3day), b_v + s_v]
        else:
            cur[1] += b_v + s_v

    sell_by_tid = defaultdict(list)
    for r in ls.itertuples(index=False):
        k = (r.dt, r.c6, r.tid)
        b_v = float(r.BUY or 0.0)
        s_v = float(r.SELL or 0.0)
        sell_by_tid[k].append((str(r.OPERATEDEPT_NAME), b_v, s_v))
        if k not in tid_meta:
            tid_meta[k] = [bool(r.is_3day), b_v + s_v]
        else:
            tid_meta[k][1] += b_v + s_v

    best_tid = {}
    for (dt, c6, tid), (is3, vol) in tid_meta.items():
        prev = best_tid.get((dt, c6))
        cand_key = (0 if not is3 else 1, -vol, tid)
        if prev is None or cand_key < prev[0]:
            best_tid[(dt, c6)] = (cand_key, tid, is3)

    lhb_map = {}
    for (dt, c6), (_, tid, is3) in best_tid.items():
        b_list = buy_by_tid.get((dt, c6, tid), [])
        s_list = sell_by_tid.get((dt, c6, tid), [])

        lh_cnt = sum(1 for nm, _, _ in b_list if RE_LHASA.search(nm))
        tot_b = sum(b for _, b, _ in b_list)
        tot_s = sum(s for _, _, s in s_list)
        lh_b = sum(b for nm, b, _ in b_list if RE_LHASA.search(nm))
        lh_ratio = (lh_b / tot_b) if tot_b > 0 else 0.0

        daysurf_buy = any(RE_DAY_SURF.search(nm) for nm, _, _ in b_list)
        inst_buy_amt = sum(b for nm, b, _ in b_list if RE_INST.search(nm))
        inst_sell_amt = sum(s for nm, _, s in s_list if RE_INST.search(nm))
        inst_buy_cnt = sum(1 for nm, _, _ in b_list if RE_INST.search(nm))
        inst_sell_cnt = sum(1 for nm, _, _ in s_list if RE_INST.search(nm))

        # 量化席位：区分买卖双边做T/纯买
        qu_buy_names = {nm for nm, _, _ in b_list if RE_QUANT.search(nm)}
        qu_sell_names = {nm for nm, _, _ in s_list if RE_QUANT.search(nm)}
        qu_buy_amt = sum(b for nm, b, _ in b_list if RE_QUANT.search(nm))
        qu_sell_amt = sum(s for nm, _, s in s_list if RE_QUANT.search(nm))

        top_yz_buys = {nm for nm, _, _ in b_list if RE_TOP_YOUZI.search(nm)}
        top_yz_sells = {nm for nm, _, _ in s_list if RE_TOP_YOUZI.search(nm)}
        # 注意同席位当日买入与卖出净额：若某席位同时在buy/sell出现，以sell-buy判断净卖出
        sell_amt_by_name = defaultdict(float)
        buy_amt_by_name = defaultdict(float)
        for nm, b, _ in b_list:
            buy_amt_by_name[nm] += b
        for nm, _, s in s_list:
            sell_amt_by_name[nm] += s

        # 净买额占成交额比（3日榜则用近3日累计成交额作分母，单日榜用当日成交额）
        di = dt_to_idx.get(dt, -1)
        if is3 and di >= 2:
            denom_amt = sum(daily_amt_map.get((c6, all_dts[di - off]), 0.0) for off in (0, 1, 2))
        else:
            denom_amt = daily_amt_map.get((c6, dt), 0.0)
        net_buy_amt_ratio = ((tot_b - tot_s) / denom_amt) if denom_amt > 0 else 0.0

        lhb_map[(dt, c6)] = {
            "is_3day": is3,
            "lh_cnt": int(lh_cnt),
            "lh_ratio": float(lh_ratio),
            "tot_b": float(tot_b),
            "tot_s": float(tot_s),
            "daysurf_buy": bool(daysurf_buy),
            "inst_buy_cnt": int(inst_buy_cnt),
            "inst_sell_cnt": int(inst_sell_cnt),
            "inst_net_sell": float(inst_sell_amt - inst_buy_amt),
            "inst_sell_amt": float(inst_sell_amt),
            "qu_buy_cnt": len(qu_buy_names),
            "qu_sell_cnt": len(qu_sell_names),
            "qu_two_way": bool((qu_buy_names & qu_sell_names) or (qu_buy_amt > 0 and qu_sell_amt > 0)),
            "qu_net_sell": float(qu_sell_amt - qu_buy_amt),
            "top_yz_buys": top_yz_buys,
            "top_yz_sells": top_yz_sells,
            "buy_amt_by_name": dict(buy_amt_by_name),
            "sell_amt_by_name": dict(sell_amt_by_name),
            "net_buy_amt_ratio": float(net_buy_amt_ratio),
        }
    return lhb_map


def _build_notices_and_community_pit(max_date: str, target_codes: set) -> dict:
    """加载监管/澄清/减持/异常波动/机构调研/雪球/股吧全部时间戳（严格 <= max_date 23:59:59）。"""
    # 1. 个股监管 & 交易所监管 & 毒丸
    stk_reg, ex_reg, tox_reg_base = u34._load_reg_tox_sources(max_date)

    # 补充全量 ex_reg 按 (dt, c6) 记录用于准确计算近5日交易所监管函封数
    ex_reg_events = {"SH": [], "SZ": []}
    # 从 part1_cache + pit_reg_tox + cninfo_notices 合并计算更细粒度公告事件
    with open(u34.PART1_PKL, "rb") as f:
        pkg = pickle.load(f)
    raw_ereg = pkg[11]
    for ex_k in ("SH", "SZ"):
        for d in raw_ereg.get(ex_k, []):
            ds_s = str(d)[:10]
            if ds_s <= max_date:
                ex_reg_events[ex_k].append(ds_s)

    if os.path.exists(u34.PQ_REG_TOX):
        rt = pd.read_parquet(u34.PQ_REG_TOX, columns=["sec_code", "pub_datetime_cst", "title"])
        rt["dt10"] = rt["pub_datetime_cst"].astype(str).str[:10]
        rt = rt[(rt["dt10"] > "2026-11-12") & (rt["dt10"] <= max_date)]
        for sc, pdt, ti in zip(rt["sec_code"], rt["pub_datetime_cst"], rt["title"]):
            c6 = str(sc)[:6].zfill(6)
            if c6.startswith(("00", "60")) and u34.REG_INC_RE.search(str(ti)) and (not u34.REG_EXC_RE.search(str(ti))):
                ex_reg_events["SH" if c6.startswith("60") else "SZ"].append(str(pdt)[:10])
    for zf in glob.glob(u34.ZDJK_GLOB):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            c6 = str(it[0]).zfill(6)
            dt_z = str(it[2])[:10]
            if dt_z > "2026-11-12" and dt_z <= max_date and c6.startswith(("00", "60")):
                ex_reg_events["SH" if c6.startswith("60") else "SZ"].append(dt_z)
    for ex_k in ("SH", "SZ"):
        ex_reg_events[ex_k].sort()

    # 补充全五年 pit_reg_tox_notices_5y_complete 全量监管函按7日去重
    ex_reg_full_raw = {"SH": [], "SZ": []}
    if os.path.exists(u34.PQ_REG_TOX):
        rt_all = pd.read_parquet(u34.PQ_REG_TOX, columns=["sec_code", "pub_datetime_cst", "title"])
        rt_all["dt10"] = rt_all["pub_datetime_cst"].astype(str).str[:10]
        rt_all["c6"] = rt_all["sec_code"].astype(str).str[:6].str.zfill(6)
        rt_all = rt_all[(rt_all["dt10"] >= "2021-10-01") & (rt_all["dt10"] <= max_date) & rt_all["c6"].str.startswith(("00", "60"))].copy()
        for r_t in rt_all.itertuples(index=False):
            ti_s = str(r_t.title or "")
            if u34.REG_INC_RE.search(ti_s) and (not u34.REG_EXC_RE.search(ti_s)):
                ex_reg_full_raw["SH" if r_t.c6.startswith("60") else "SZ"].append((r_t.dt10, r_t.c6))
    for zf in glob.glob(u34.ZDJK_GLOB):
        for it in json.load(open(zf, encoding="utf-8")).get("List", []):
            c6 = str(it[0]).zfill(6)
            dt_z = str(it[2])[:10]
            if dt_z <= max_date and c6.startswith(("00", "60")):
                ex_reg_full_raw["SH" if c6.startswith("60") else "SZ"].append((dt_z, c6))
    ex_reg_full = {}
    for ex_k in ("SH", "SZ"):
        ded, seen = [], {}
        for d, c in sorted(set(ex_reg_full_raw[ex_k])):
            if c not in seen or (pd.Timestamp(d) - seen[c]).days > 7:
                seen[c] = pd.Timestamp(d)
                ded.append(d)
        ex_reg_full[ex_k] = sorted(ded)

    # 2. 个股全五年公告时间戳（合并 cninfo_notices_5y_pit.db 与 pit_reg_tox_notices_5y_complete.parquet）
    clarify_map = defaultdict(list)
    halt_warn_map = defaultdict(list)
    reduce_tox_map = defaultdict(list)
    abn_notice_map = defaultdict(dict)  # c6 -> {dt10: earliest_pdt_s} 防跨库同日重复计数
    cn_reg_map = defaultdict(list)

    def _ingest_notice(c6: str, pdt_s: str, t: str):
        if u34.REG_INC_RE.search(t) and (not u34.REG_EXC_RE.search(t)):
            cn_reg_map[c6].append(pdt_s)
        if RE_CLARIFY.search(t):
            clarify_map[c6].append(pdt_s)
        if RE_HALT_WARN.search(t) and ("复牌" not in t):
            halt_warn_map[c6].append(pdt_s)
        if RE_REDUCE_TOX.search(t):
            reduce_tox_map[c6].append(pdt_s)
        if RE_ABN_NOTICE.search(t):
            d10 = pdt_s[:10]
            prev = abn_notice_map[c6].get(d10)
            if prev is None or pdt_s < prev:
                abn_notice_map[c6][d10] = pdt_s

    q_codes = ",".join(f"'{c}'" for c in sorted(target_codes))
    con_cn = sqlite3.connect(f"file:{u34.DB_NOTICES}?mode=ro", uri=True)
    for sc, pdt, ti in con_cn.execute(
        f"SELECT sec_code, pub_datetime_cst, title FROM notices WHERE sec_code IN ({q_codes}) AND pub_datetime_cst >= '2021-10-01' AND pub_datetime_cst <= ?",
        (f"{max_date} 23:59:59",),
    ):
        _ingest_notice(str(sc)[:6].zfill(6), str(pdt), str(ti or ""))
    con_cn.close()

    if os.path.exists(u34.PQ_REG_TOX):
        rt_sub = rt_all[rt_all["c6"].isin(target_codes) & (rt_all["pub_datetime_cst"].astype(str) <= f"{max_date} 23:59:59")]
        for r_t in rt_sub.itertuples(index=False):
            _ingest_notice(r_t.c6, str(r_t.pub_datetime_cst), str(r_t.title or ""))

    abn_notice_lists = {k: sorted(v.values()) for k, v in abn_notice_map.items()}
    abn_notice_map = abn_notice_lists

    # 合并 stk_reg 与 cn_reg_map 并排序
    all_sreg_map = defaultdict(list)
    for c6 in target_codes:
        s = set(stk_reg.get(c6, [])) | set(cn_reg_map.get(c6, []))
        if s:
            all_sreg_map[c6] = sorted(s)

    # 3. 机构调研 cninfo_ir_qa_5y_pit.db
    ir_map = defaultdict(list)
    con_ir = sqlite3.connect(f"file:{SIM}/data/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    for sc, pdt in con_ir.execute(
        f"SELECT sec_code, pub_datetime_cst FROM ir_qa WHERE sec_code IN ({q_codes}) AND pub_datetime_cst IS NOT NULL AND pub_datetime_cst <= ?",
        (f"{max_date} 23:59:59",),
    ):
        ir_map[str(sc)[:6].zfill(6)].append(str(pdt))
    con_ir.close()
    ir_arr_map = {c6: np.sort(np.array(sorted(set(v)), dtype=str)) for c6, v in ir_map.items()}

    # 4. 雪球 & 股吧（严格 mode=ro, <= max_date 23:59:59）
    xq_seen, xq_posts = defaultdict(set), defaultdict(list)
    gb_seen, gb_posts = defaultdict(set), defaultdict(list)

    con_xq = sqlite3.connect(f"file:{u34.DB_XQ_GB}?mode=ro", uri=True)
    for sym, pid, cts in con_xq.execute(
        "SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE created_time_str >= '2021-10-01' AND created_time_str <= ?",
        (f"{max_date} 23:59:59",),
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 in target_codes and cts:
            pid_c = str(pid).replace("xq_", "")
            if pid_c not in xq_seen[c6]:
                xq_seen[c6].add(pid_c)
                xq_posts[c6].append(str(cts))

    for sc, pid, pt in con_xq.execute(
        f"SELECT sec_code, post_id, pub_time FROM guba_posts WHERE sec_code IN ({q_codes}) AND pub_time >= '2021-10-01' AND pub_time <= ?",
        (f"{max_date} 23:59:59",),
    ):
        c6 = str(sc)[:6].zfill(6)
        if pt:
            pid_c = str(pid)
            if pid_c not in gb_seen[c6]:
                gb_seen[c6].add(pid_c)
                gb_posts[c6].append(str(pt))
    con_xq.close()

    con_cm = sqlite3.connect(f"file:{u34.DB_COMM}?mode=ro", uri=True)
    for src, sym, pid, cts in con_cm.execute(
        "SELECT source, symbol, post_id, pub_datetime_cst FROM community_posts WHERE pub_datetime_cst >= '2021-10-01' AND pub_datetime_cst <= ?",
        (f"{max_date} 23:59:59",),
    ):
        c6 = str(sym)[:6].zfill(6)
        if c6 not in target_codes or not cts:
            continue
        if src == "xueqiu":
            pid_c = str(pid).replace("xq_", "")
            if pid_c not in xq_seen[c6]:
                xq_seen[c6].add(pid_c)
                xq_posts[c6].append(str(cts))
        elif src in ("eastmoney_guba", "guba"):
            pid_c = str(pid)
            if pid_c not in gb_seen[c6]:
                gb_seen[c6].add(pid_c)
                gb_posts[c6].append(str(cts))
    con_cm.close()

    return {
        "sreg_map": {k: np.sort(np.array(v, dtype=str)) for k, v in all_sreg_map.items()},
        "ex_reg_events": ex_reg_events,
        "ex_reg_full": ex_reg_full,
        "clarify_map": {k: np.sort(np.array(sorted(set(v)), dtype=str)) for k, v in clarify_map.items()},
        "halt_warn_map": {k: np.sort(np.array(sorted(set(v)), dtype=str)) for k, v in halt_warn_map.items()},
        "reduce_tox_map": {k: np.sort(np.array(sorted(set(v)), dtype=str)) for k, v in reduce_tox_map.items()},
        "abn_notice_map": {k: np.sort(np.array(sorted(set(v)), dtype=str)) for k, v in abn_notice_map.items()},
        "ir_arr_map": ir_arr_map,
        "xq_arr_map": {k: np.sort(np.array(v, dtype=str)) for k, v in xq_posts.items()},
        "gb_arr_map": {k: np.sort(np.array(v, dtype=str)) for k, v in gb_posts.items()},
    }


def build_exit_pit_data(max_date: str = "2026-11-16", verbose: bool = True) -> dict:
    """从零因果构建全套持仓期跨策略卖点因子 PIT 缓存，物理截断 <= max_date。"""
    t0 = time.time()
    if verbose:
        print(f"[Step1 max_date={max_date}] Running base 3to4 causal pipeline...")

    res_u34 = u34.run_causal_pipeline(max_date, verbose=verbose)
    cand_df = res_u34["cand_df"].copy()
    skel = res_u34["skel"]
    sc_v40 = res_u34["sc_v40"]
    target_codes = set(cand_df["code"].unique())

    # 1. 加载主板全量日线 (2021-01-01 .. max_date) 构建全场生态 + 同板块队友 09:25 竞价 + 扩展 code_bars
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "turn", "oshare"]
    dt_cap = pd.Timestamp(max_date)
    d1 = ds.dataset(u34.A_DAILY_PQ, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2021-01-01")) & (ds.field("date") <= dt_cap)
    ).to_table().to_pandas()
    d2 = ds.dataset(u34.A_DELIST_PQ, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2021-01-01")) & (ds.field("date") <= dt_cap)
    ).to_table().to_pandas()
    df = pd.concat([d1, d2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["ticker"].astype(str).str.endswith((".SH", ".SZ")) & df["c6"].str.startswith(("00", "60"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt_str"], inplace=True)
    df.drop_duplicates(["c6", "dt_str"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    ind_l2 = pd.read_csv(u34.CSRC_L2_CSV)
    ind_l2["c6"] = ind_l2["code"].astype(str).str[-6:].str.zfill(6)
    name_map = dict(zip(ind_l2["c6"], ind_l2["code_name"].fillna("")))
    df["is_st_name"] = df["c6"].map(name_map).fillna("").str.upper().str.contains("ST")

    g = df.groupby("c6")
    df = df[g.cumcount() >= 10].copy().reset_index(drop=True)
    g = df.groupby("c6")
    df["adjf"] = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    df["pre_c"] = g["close"].shift(1) * g["adjf"].shift(1) / df["adjf"]
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["o_pct"] = df["open"] / df["pre_c"] - 1.0
    df["h_pct"] = df["high"] / df["pre_c"] - 1.0
    df["l_pct"] = df["low"] / df["pre_c"] - 1.0
    df["to"] = df["turn"] * u34.UNIT_PCT_DIV
    df["mcap"] = df["close"] * df["oshare"] / u34.UNIT_YI_DIV
    df["zt_price"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["dt_price"] = np.floor(df["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (~df["is_st_name"]) & (df["close"] >= df["zt_price"] - 0.011) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    df["is_dt"] = (~df["is_st_name"]) & (df["close"] <= df["dt_price"] + 0.011) & (df["pct"] <= -0.095) & (df["pre_c"] > 0)
    df["is_dt_exact"] = (df["close"] <= df["dt_price"] + 0.005) & (df["pre_c"] > 0)
    df["touch_zt"] = (~df["is_st_name"]) & ((df["high"] >= df["zt_price"] - 0.011) | (df["h_pct"] >= 0.098)) & (df["pre_c"] > 0)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= df["zt_price"] - 0.011) & (df["low"] >= df["zt_price"] - 0.011)
    df["is_yizi_dt"] = df["is_dt"] & (df["open"] <= df["dt_price"] + 0.011) & (df["high"] <= df["dt_price"] + 0.011)
    df["open_yizi"] = (~df["is_st_name"]) & (df["open"] >= df["zt_price"] - 0.011) & (df["pre_c"] > 0)
    df["open_dt"] = (~df["is_st_name"]) & (df["open"] <= df["dt_price"] + 0.011) & (df["pre_c"] > 0)

    s_zt = df["is_zt"].astype(int)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != g["is_zt"].shift().fillna(False)).cumsum()]).cumsum() * s_zt
    df["prev_streak"] = g["streak"].shift(1).fillna(0).astype(int)
    df["prev_close_raw"] = g["close"].shift(1)
    df["vol_ma5"] = g["amount"].transform(lambda s: s.shift(1).rolling(5, min_periods=2).mean())
    df["vol_ratio"] = df["amount"] / (df["vol_ma5"] + 1e-6)

    # 构建全市场每日因果环境（严格按日期顺推）
    all_dts = sorted(df["dt_str"].unique())
    dt_to_idx = {d: i for i, d in enumerate(all_dts)}

    # 只针对需要做同板块/昨涨停竞价查表的日期索引
    prev_zt_open_map = defaultdict(list)  # dt -> list of (c6, o_pct, open_yizi, open_dt, prev_streak)
    for r in df[df["prev_streak"] >= 1][["dt_str", "c6", "o_pct", "open_yizi", "open_dt", "prev_streak"]].itertuples(index=False):
        if pd.notna(r.o_pct):
            prev_zt_open_map[r.dt_str].append((r.c6, float(r.o_pct), bool(r.open_yizi), bool(r.open_dt), int(r.prev_streak)))

    mkt_env = {}
    promo_1to2_hist = []
    promo_2p_hist = []
    brk_dt_hist = []       # 高标 V5.1 原义: (dt_cnt, broken_cnt)
    brk_reb_hist = []      # 实际次日反包正收益比例: (reb_cnt, prev_broken_cnt)
    prev_broken_ge4 = set()

    for dt, grp in df.groupby("dt_str", sort=True):
        non_st = grp[~grp["is_st_name"]]
        n_zt = int(non_st["is_zt"].sum())
        n_touch = int(non_st["touch_zt"].sum())
        seal_rate = float(n_zt / n_touch) if n_touch > 0 else 0.55

        zt_g = non_st[non_st["is_zt"]]
        max_board = int(zt_g["streak"].max()) if len(zt_g) > 0 else 0
        # 全场第2高板（用于 dom 判断）
        s_sorted = sorted(zt_g["streak"].tolist(), reverse=True)
        top2_board = int(s_sorted[1]) if len(s_sorted) > 1 else 0

        # 1进2晋级率 & 2+板晋级率
        fb_y = non_st[non_st["prev_streak"] == 1]
        p12 = float(fb_y["is_zt"].sum() / len(fb_y)) if len(fb_y) > 0 else 0.20
        promo_1to2_hist.append(p12)
        p2p_g = non_st[non_st["prev_streak"] >= 2]
        p2p = float(p2p_g["is_zt"].sum() / len(p2p_g)) if len(p2p_g) > 0 else 0.35
        promo_2p_hist.append(p2p)

        # >=4板断板跌停率 & 次日反包率
        if prev_broken_ge4:
            sub_reb = non_st[non_st["c6"].isin(prev_broken_ge4)]
            reb_ok = int((sub_reb["pct"] > 0).sum())
            brk_reb_hist.append((reb_ok, len(prev_broken_ge4)))
        else:
            brk_reb_hist.append((0, 0))

        ge4_brk = non_st[(non_st["prev_streak"] >= 4) & (~non_st["is_zt"])]
        brk_dt_hist.append((int(ge4_brk["is_dt"].sum()), int(len(ge4_brk))))
        prev_broken_ge4 = set(ge4_brk["c6"].tolist())

        # 昨涨停 / 昨首板今日 09:25 竞价均值
        prev_zt_rows = non_st[non_st["prev_streak"] >= 1]
        mkt_zt_open_avg = float(prev_zt_rows["o_pct"].mean()) if len(prev_zt_rows) > 0 else 0.0
        mkt_fb_open_avg = float(fb_y["o_pct"].mean()) if len(fb_y) > 0 else 0.0

        w10_dt = brk_dt_hist[-10:]
        w10_rb = brk_reb_hist[-10:]
        brk_dt_r10 = sum(x[0] for x in w10_dt) / max(1, sum(x[1] for x in w10_dt))
        brk_reb_r10 = sum(x[0] for x in w10_rb) / max(1, sum(x[1] for x in w10_rb))

        mkt_env[dt] = {
            "n_zt": n_zt,
            "seal_rate": round(seal_rate, 4),
            "max_board": max_board,
            "top2_board": top2_board,
            "promo_1to2_ma5": round(float(np.mean(promo_1to2_hist[-5:])), 4),
            "promo_2p_ma5": round(float(np.mean(promo_2p_hist[-5:])), 4),
            "mkt_zt_open_avg": round(mkt_zt_open_avg, 5),
            "mkt_fb_open_avg": round(mkt_fb_open_avg, 5),
            "brk_dt_r10": round(float(brk_dt_r10), 4),
            "brk_reb_r10": round(float(brk_reb_r10), 4),
        }

    # 2. 8年因果 KPL 板块与个股题材记录 (<= max_date)
    stock_theme_5y = u34._build_kpl_8y_metadata(df, max_date)
    # 同步读取每日 KPL 板块涨停归属用于同题材队友竞价查表与老票新炒/冷饭识别
    kpl_days_map = {}
    for p_path in [u34.KPL_MERGED, f"{SIM}/data/kpl_plates_5y_2021_2026_complete.jsonl"]:
        if os.path.exists(p_path):
            with open(p_path, encoding="utf-8") as f:
                for ln in f:
                    if not ln.strip():
                        continue
                    d_obj = json.loads(ln)
                    dt_k = d_obj.get("date", "")
                    if dt_k and dt_k <= max_date:
                        if p_path == u34.KPL_MERGED and dt_k < "2021-01-01":
                            kpl_days_map[dt_k] = d_obj
                        elif p_path != u34.KPL_MERGED and dt_k >= "2021-01-01":
                            kpl_days_map[dt_k] = d_obj
                        elif dt_k not in kpl_days_map:
                            kpl_days_map[dt_k] = d_obj

    kpl_plate_zt_stocks = defaultdict(set)  # (dt, plate) -> set of c6
    kpl_stock_zt_hist = defaultdict(list)   # c6 -> [(dt, plate, reason_desc)]
    for dt_k in sorted(kpl_days_map.keys()):
        for pl in kpl_days_map[dt_k].get("plates", []):
            pname = pl.get("plate", "")
            if pname in u34.NON_THEME:
                continue
            for st in pl.get("stocks", []):
                c6 = str(st[0]).strip()[:6].zfill(6)
                r1 = str(st[2]).strip() if len(st) > 2 else ""
                r2 = str(st[3]).strip() if len(st) > 3 else ""
                if dt_k >= "2021-01-01":
                    kpl_plate_zt_stocks[(dt_k, pname)].add(c6)
                if c6 in target_codes:
                    kpl_stock_zt_hist[c6].append((dt_k, pname, f"{r1} {r2}".strip()))

    # 补充同日涨停股的开盘竞价查表（仅 target_codes 持有期间所需的日期）
    open_lookup_by_dt = defaultdict(dict)  # dt -> {c6: (o_pct, open_yizi, open_dt, prev_streak)}
    for dt_k, lst in prev_zt_open_map.items():
        if dt_k >= "2021-11-01":
            open_lookup_by_dt[dt_k] = {x[0]: (x[1], x[2], x[3], x[4]) for x in lst}

    # 3. target_codes 的扩展日线数组（含 streak, to, vol_ratio, vol_ma5, is_zt, is_dt_exact, mcap 等）
    sub_t = df[(df["c6"].isin(target_codes)) & (df["dt_str"] >= "2021-08-01")].copy()
    code_bars_ext = {}
    daily_amt_map = {}
    for c6, gc in sub_t.groupby("c6", sort=False):
        dts_arr = gc["dt_str"].values
        amt_arr = gc["amount"].values.astype(float)
        for d_i, a_i in zip(dts_arr, amt_arr):
            daily_amt_map[(c6, d_i)] = float(a_i)
        code_bars_ext[c6] = {
            "dts": dts_arr,
            "date_to_pos": {d: i for i, d in enumerate(dts_arr)},
            "open": gc["open"].values.astype(float),
            "high": gc["high"].values.astype(float),
            "low": gc["low"].values.astype(float),
            "close": gc["close"].values.astype(float),
            "adjf": gc["adjf"].values.astype(float),
            "pre_c": gc["pre_c"].values.astype(float),
            "zt_px": gc["zt_price"].values.astype(float),
            "dt_px": gc["dt_price"].values.astype(float),
            "to": gc["to"].values.astype(float),
            "amount": amt_arr,
            "volume": gc["volume"].values.astype(float),
            "mcap": gc["mcap"].values.astype(float),
            "vol_ratio": gc["vol_ratio"].fillna(1.0).values.astype(float),
            "streak": gc["streak"].values.astype(int),
            "is_zt": gc["is_zt"].values.astype(bool),
            "is_dt": gc["is_dt"].values.astype(bool),
            "is_dt_exact": gc["is_dt_exact"].values.astype(bool),
            "is_yizi": gc["is_yizi"].values.astype(bool),
            "is_yizi_dt": gc["is_yizi_dt"].values.astype(bool),
        }

    # 4. 指数映射
    with open(u34.IDX_JSON, "r", encoding="utf-8") as f:
        idx_raw = json.load(f)
    sh_map = {k: float(v) for k, v in idx_raw["sh000002"].items() if k <= max_date}
    sz_map = {k: float(v) for k, v in idx_raw["sz399107"].items() if k <= max_date}
    csi_map = {k: float(v) for k, v in idx_raw["sh000300"].items() if k <= max_date}
    all_csi_dts = sorted(csi_map.keys())

    # 5. 5m K 线（仅 target_codes, <= max_date）
    df_5m_a = ds.dataset(u34.BARS_ALL_5M, format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=(ds.field("date") <= max_date),
    ).to_table().to_pandas()
    df_5m_b = ds.dataset(u34.BARS_34_5M, format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=(ds.field("date") <= max_date),
    ).to_table().to_pandas()
    df_5m = pd.concat([df_5m_a, df_5m_b], ignore_index=True)
    df_5m = df_5m[df_5m["c6"].isin(target_codes)].copy()
    df_5m.drop_duplicates(["c6", "date", "hhmm_int"], keep="first", inplace=True)
    df_5m.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    bars_5m_map = {
        (c6, d): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, d), grp in df_5m.groupby(["c6", "date"], sort=False)
    }

    # 6. 涨停微观封单全库 (<= max_date)
    con_tp = sqlite3.connect(f"file:{u34.DB_ZT_TAPE}?mode=ro", uri=True)
    df_tape = pd.read_sql_query(
        "SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count, plate_name, reason_desc "
        "FROM zt_micro_tape WHERE trade_date >= '2021-10-01' AND trade_date <= ?",
        con_tp,
        params=(max_date,),
    )
    con_tp.close()
    df_tape["c6"] = df_tape["sec_code"].astype(str).str[:6].str.zfill(6)
    df_tape = df_tape[df_tape["c6"].isin(target_codes)].drop_duplicates(["trade_date", "c6"])
    tape_ext_map = {
        (str(r.trade_date), r.c6): {
            "first_seal_time": str(r.first_seal_time or "99:99:99"),
            "seal_amount": float(r.seal_amount or 0.0),
            "open_board_count": int(r.open_board_count if pd.notna(r.open_board_count) else 0),
            "plate_name": str(r.plate_name or ""),
            "reason_desc": str(r.reason_desc or ""),
        }
        for r in df_tape.itertuples(index=False)
    }

    # 7. 龙虎榜、公告、社区、十大股东锁仓 (<= max_date)
    lhb_map = _build_lhb_pit_map(max_date, target_codes, daily_amt_map, all_dts)
    comm_notices = _build_notices_and_community_pit(max_date, target_codes)

    with open(u34.HOLDERS_JSON, "r", encoding="utf-8") as f:
        holders_raw = json.load(f)
    holders_map = {
        c6: [rec for rec in holders_raw.get(c6, []) if str(rec[0])[:10] <= max_date]
        for c6 in target_codes
    }

    # 8. 构建 buy_entries (完全对齐 V4.0 买点)
    buy_entries = []
    for i, r in enumerate(cand_df.itertuples(index=False)):
        c6 = str(r.code)
        bd = str(r.buy_date)
        cb = code_bars_ext.get(c6)
        pos = cb["date_to_pos"].get(bd, -1) if cb else -1
        bpx, bhh = None, None
        if bool(r.is_10cm_non_st) and bool(r.buyable_open) and cb is not None and 0 <= pos < len(cb["dts"]) - 1:
            bpx, bhh = u34._sim_buy_5m(c6, bd, cb, pos, bars_5m_map, 1030)
        orig = res_u34["p_1030"][i]
        if orig is not None:
            assert bpx is not None and round(bpx, 2) == orig["buy_price"] and bhh == orig["buy_hhmm"]
        else:
            assert bpx is None
        buy_entries.append({
            "idx": i,
            "code": c6,
            "name": str(r.name),
            "sig_date": str(r.sig_date),
            "buy_date": bd,
            "d1_date": str(cb["dts"][max(0, pos - 3)]) if (cb and pos >= 3) else str(r.sig_date),
            "pos": pos,
            "buy_px": bpx,
            "buy_hhmm": bhh,
            "skel": bool(skel[i]),
            "sc_v40": float(sc_v40[i]),
            "priority_score": float(sc_v40[i]) * 10.0 + float(r.prio_3to4) * 0.1,
            "open_pct": float(r.open_pct),
            "pos20_d0": float(r.pos20_d0),
            "xq_cnt_2d": int(r.xq_cnt_2d),
            "plate": str(r.plate),
            "lock_top10": float(r.lock_top10),
        })

    cache = {
        "max_date": max_date,
        "cand_df": cand_df,
        "skel": skel,
        "sc_v40": sc_v40,
        "comp_v40": res_u34["comp_v40"],
        "buy_entries": buy_entries,
        "code_bars_ext": code_bars_ext,
        "bars_5m_map": bars_5m_map,
        "all_dts": all_dts,
        "dt_to_idx": dt_to_idx,
        "mkt_env": mkt_env,
        "open_lookup_by_dt": dict(open_lookup_by_dt),
        "stock_theme_5y": stock_theme_5y,
        "kpl_plate_zt_stocks": {k: sorted(v) for k, v in kpl_plate_zt_stocks.items()},
        "kpl_stock_zt_hist": dict(kpl_stock_zt_hist),
        "tape_ext_map": tape_ext_map,
        "lhb_map": lhb_map,
        "holders_map": holders_map,
        "sh_map": sh_map,
        "sz_map": sz_map,
        "csi_map": csi_map,
        "all_csi_dts": all_csi_dts,
        **comm_notices,
    }
    if verbose:
        print(f"[Step1 max_date={max_date}] Completed in {time.time()-t0:.1f}s (entries={len(buy_entries)}, lhb={len(lhb_map)}, tape={len(tape_ext_map)})")
    return cache


if __name__ == "__main__":
    cache_full = build_exit_pit_data("2026-11-16", verbose=True)
    out_pkl = f"{OUT_DIR}/pit_exit_cache_full.pkl"
    with open(out_pkl, "wb") as f:
        pickle.dump(cache_full, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"[SAVED] {out_pkl} ({os.path.getsize(out_pkl)/1024/1024:.2f} MB)")

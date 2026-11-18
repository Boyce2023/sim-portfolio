#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
live_3to4_v40_engine.py — 三进四 V4.0 (互学瘦身升级正式版) 唯一生产核心引擎
严格对齐研发真源: sim-portfolio/backtests_astock/clean_3strategies_mutual_upgrade_20261117/upgrade_3to4_pit.py
核心规则 (底分 78, 22 项打分因子, 标准 >=90 分, S档 >=102 分):
  1. 剪除 V3.4 3项冗余噪音: T10(周一+2), T14(涨停>=95家-10), T20(股价>32元-5)
  2. 新增跨策略互学 2 因子:
     - U01: 启动前20日箱体低位 pos20_d0 <= 0.40 (+5分)
     - U02: 雪球盘前高热 xq_cnt_2d >= 4帖 (-15分, 只读库叠加 astock_community.json 实时增量, 严卡 < buy_date 09:25:00)
  3. 买点撤单窗收紧: 09:30 至 10:30 有效, 10:30 未触发立即撤单
  4. 保持 3to4_premarket_cache.json 字段超集向后兼容; 严禁 import yfinance (D12); SQLite 全程 mode=ro 只读。
"""
from __future__ import annotations

import datetime
import glob
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"
ND_DIR = f"{ROOT}/news-dashboard"

CACHE_FILE = f"{DATA_DIR}/3to4_premarket_cache.json"
A_DAILY = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
THS_DIR = f"{DATA_DIR}/ths_limit_up_daily"
HOLDERS_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
HOLDERS_FREE_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/pit_top10_freeholders_cache.json"
IDX_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
DB_NOTICES = f"{SIM_DIR}/backtest/2026-08-24-daban/notices.db"
DB_PIT_NOTICES = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
DB_ZT_TAPE = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"
DB_XQ_GB = f"{DATA_DIR}/xueqiu_guba_5y_pit.db"
DB_COMM = f"{DATA_DIR}/astock_community_5y_pit.db"
PQ_REG_TOX = f"{DATA_DIR}/pit_reg_tox_notices_5y_complete.parquet"
ZDJK_GLOB = f"{DATA_DIR}/kpl/zdjk/*.json"
COMM_JSON = f"{ND_DIR}/output/astock_community.json"
KPL_MERGED = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
KPL_5Y = f"{DATA_DIR}/kpl_plates_5y_2021_2026_complete.jsonl"
KPL_V2 = f"{ND_DIR}/output/kpl_plates_v2.jsonl"
LHB_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_buy.parquet"

UPG_DIR = f"{SIM_DIR}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
LEDGER_V40_STD = f"{UPG_DIR}/ledger_upg_3to4_std.csv"
LEDGER_V40_STR = f"{UPG_DIR}/ledger_upg_3to4_strict.csv"
SUMMARY_V40_JSON = f"{UPG_DIR}/summary_upg_3to4.json"
ENRICHED_PARQUET = f"{SIM_DIR}/backtests_astock2/data_5y/cand_3to4_enriched54.parquet"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
SURF_YZ = re.compile(
    r"(?:上塘路|财通.*杭州上塘|东方财富.*昌都|佛山|绿景路|苏南|消闲派|国泰君安.*宜昌|开源.*西安西大街)"
)
REG_INC = ("监管工作函", "监管函", "关注函", "重点监控", "停牌核查")
REG_EXC = ("ST", "回复", "回函", "延期", "核查意见", "复牌", "募集资金", "监事", "独立董事", "保荐")
TOX_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险)")
SECTOR_SYNONYMS = {
    "半导体": {"半导体", "芯片", "光刻胶", "集成电路", "玻璃基", "玻璃基板", "存储器", "GPU"},
    "芯片": {"半导体", "芯片", "光刻胶", "集成电路", "玻璃基", "玻璃基板", "存储器", "GPU"},
    "光伏": {"光伏", "光伏设备", "储能", "风光储", "逆变器"},
    "机器人": {"机器人", "人形机器人", "减速器", "四足机器人", "伺服", "电机"},
    "游戏": {"游戏", "AI游戏", "手游", "短剧", "传媒", "影视"},
}


def _extract_keywords(reason: str) -> set[str]:
    kws: set[str] = set()
    skip = {"国企", "央企", "回购", "股份回购", "股权转让", "摘帽", "预重整", "扭亏", "三季报增长", "业绩增长"}
    for w in str(reason).split("+"):
        w = w.strip()
        if w and w not in skip:
            kws.add(w)
            for syn_set in SECTOR_SYNONYMS.values():
                if any(s in w for s in syn_set):
                    kws.update(syn_set)
    return kws


def score_single_3to4_v40_row(r: dict) -> dict:
    """三进四 V4.0 22项打分卡（底分78，标准>=90，S档>=102）。"""
    veto: list[str] = []
    if not bool(r.get("is_10cm_non_st", True)):
        veto.append("非主板10厘米或ST")
    if bool(r.get("prev_is_yizi", False)):
        veto.append("三板一字缩量")
    if not bool(r.get("buyable_open", True)):
        veto.append("四板一字不可买")
    if bool(r.get("has_tox_notice", False)) or bool(r.get("has_stock_reg", False)):
        veto.append("真立案减持或个股监管函")
    if int(r.get("open_board_count", 0)) < 1:
        veto.append("三板未开板死封")

    to = float(r.get("prev_to", 0.0))
    op = float(r.get("open_pct", 0.0))
    if not (0.030 <= op <= 0.092):
        veto.append(f"四板竞价越界({op*100:.1f}%)")

    if veto:
        return {
            "passed_skeleton": False,
            "score": -999,
            "tier": "淘汰（未过硬骨架）",
            "veto_reasons": veto,
            "breakdown_str": "未过硬骨架：" + "、".join(veto),
            "components": {},
        }

    sc = 78
    items = ["V4.0底分78"]
    comps: dict[str, int] = {}

    def _add(key: str, pts: int, desc: str) -> None:
        nonlocal sc
        sc += pts
        comps[key] = pts
        items.append(desc)

    if not bool(r.get("is_top1_3b_open", True)):
        _add("T13", -12, "非同日可买三板竞价头名扣12")
    lock_ok = float(r.get("lock_top10", 0.0)) >= 45.0 or float(r.get("real_free_mcap", 0.0)) >= 45.0
    if not lock_ok:
        _add("T16", -10, "锁仓与自由流通盘双低扣10")
    if not (8.5 <= to <= 31.0):
        _add("T17", -10, f"三板换手越界({to:.1f}%)扣10")
    elif 9.5 <= to <= 28.0:
        _add("T08", 3, "换手黄金带加3")

    fs_raw = str(r.get("first_seal_time", "")).replace(":", "")[:4]
    fs = int(fs_raw) if fs_raw.isdigit() else 9999
    if 936 <= fs <= 1030:
        _add("T09", 3, "三板09:36至10:30换手后封板加3")

    px = float(r.get("px_d3", 25.0))
    if px <= 20.0:
        _add("T01", 8, "20元内低中价加8")

    if int(r.get("mkt_max_board_prev", 5)) <= 4:
        _add("T02", 8, "最高板不超4板破局加8")

    if float(r.get("p_elo", 100.0)) >= 115.0:
        _add("T06", 3, "八年题材高热度加3")

    mzt = int(r.get("mkt_zt_prev", 50))
    if 35 <= mzt <= 85:
        _add("T03", 5, "涨停温热区加5")

    if bool(r.get("has_ex_reg", False)):
        _add("T11", -12, "交易所重点监控期扣12")
    if bool(r.get("surf_yz_buy", False)):
        _add("T12", -12, "三板一日游砸盘席位买入扣12")

    lh = int(r.get("lhb_lh_cnt", 0))
    if lh == 0:
        _add("T05", 4, "零拉萨席位加4")
    elif lh >= 3:
        _add("T21", -5, "拉萨扎堆扣5")

    fb_ho = int(r.get("plate_fb_ho_cnt", 0))
    fb_yz = int(r.get("plate_fb_yz_cnt", 0))
    if fb_ho >= 2 and fb_yz == 0:
        _add("T04", 4, "同题材首板换手高开助攻加4")
    if fb_yz >= 1:
        _add("T19", -7, "同题材首板顶一字兑现扣7")

    if float(r.get("plate_peers_open_avg", 0.0)) < -0.015:
        _add("T15", -10, "同题材队友核按钮扣10")

    dt3 = int(r.get("prev_3b_dt_cnt", 0))
    if dt3 == 0:
        _add("T07", 3, "前日三板零跌停加3")
    elif dt3 >= 2:
        _add("T22", -4, "前日三板多股跌停扣4")

    if float(r.get("csi_1d_prev", 0.0)) <= -0.020 or float(r.get("csi_5d_prev", 0.0)) <= -0.030:
        _add("T18", -8, "前日沪深300急杀或5日破位扣8")

    bd_str = str(r.get("buy_date", ""))
    b_mon = int(bd_str[5:7]) if len(bd_str) >= 7 and bd_str[5:7].isdigit() else 0
    if b_mon in (1, 5):
        _add("T23", -4, "1月年报预告或5月退潮窗扣4")

    pos20_raw = r.get("pos20_d0")
    pos20 = float(pos20_raw) if (pos20_raw is not None and pd.notna(pos20_raw)) else 0.50
    if pos20 <= 0.40:
        _add("U01", 5, f"U01启动前20日低位({pos20:.2f}<=0.40)加5")

    xq_cnt = int(r.get("xq_cnt_2d") or 0)
    if xq_cnt >= 4:
        _add("U02", -15, f"U02雪球盘前高热({xq_cnt}帖>=4)扣15")

    if sc >= 102:
        tier = "S档极严防守单（满102分）"
    elif sc >= 98:
        tier = "严格高确信单（98至101分）"
    elif sc >= 90:
        tier = "标准主力单（90至97分）"
    else:
        tier = "总分未达90分放弃"

    return {
        "passed_skeleton": True,
        "score": int(sc),
        "tier": tier,
        "veto_reasons": [],
        "breakdown_str": "，".join(items),
        "components": comps,
    }


def _norm_xq_pid(raw_pid: object) -> str:
    s = str(raw_pid or "").strip()
    if s.startswith("xq_"):
        s = s[3:]
    elif s.startswith("xq") and s[2:].isdigit():
        s = s[2:]
    return s


def _match_comm_stock(title: str, text: str, c6: str, name: str) -> bool:
    blob = f"{title}\n{text}"
    if not blob.strip():
        return False
    blob_u = blob.upper()
    if name and (f"${name}(" in blob or name in title):
        return True
    if f"({c6})" in blob or f"SH{c6}" in blob_u or f"SZ{c6}" in blob_u:
        return True
    if name and name in blob and re.search(rf"(?<![0-9.]){c6}(?![0-9])", blob):
        return True
    return False


def load_xq_counts_2d(
    cand_items: list[tuple[str, str, str]],
    buy_date: str,
    include_live_json: bool = True,
) -> tuple[dict[str, dict], str, str]:
    """
    严格 PIT 计算每只三板候选的雪球帖数 [d1_date 00:00:00, buy_date 09:25:00):
    1) xueqiu_guba_5y_pit.db (mode=ro)
    2) astock_community_5y_pit.db source='xueqiu' (mode=ro)
    3) news-dashboard/output/astock_community.json 实时增量叠加去重
    """
    out = {c6: {"total": 0, "db": 0, "live_json": 0} for c6, _, _ in cand_items}
    if not cand_items:
        return out, "", ""

    codes = sorted({c6 for c6, _, _ in cand_items})
    name_map = {c6: nm for c6, nm, _ in cand_items}
    d1_map = {c6: d1 for c6, _, d1 in cand_items}
    d1_min = min(d1_map.values())
    end_cut = f"{buy_date} 09:25:00"
    ph = ",".join(["?"] * len(codes))

    seen_db: dict[str, set[str]] = defaultdict(set)
    seen_all: dict[str, set[str]] = defaultdict(set)
    xq_db_max = ""
    xq_json_max = ""

    if os.path.exists(DB_XQ_GB):
        con = sqlite3.connect(f"file:{DB_XQ_GB}?mode=ro", uri=True)
        try:
            xq_db_max = str(con.execute("SELECT max(created_time_str) FROM xueqiu_posts").fetchone()[0] or "")[:19]
            for sym, pid, ts in con.execute(
                f"SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE symbol IN ({ph}) AND created_time_str >= ? AND created_time_str < ?",
                (*codes, f"{d1_min} 00:00:00", end_cut),
            ):
                c6 = str(sym)[:6].zfill(6)
                ts_s = str(ts or "")
                assert ts_s < end_cut, f"PIT violation in xueqiu_guba_5y_pit: {ts_s} >= {end_cut}"
                if c6 in d1_map and ts_s >= f"{d1_map[c6]} 00:00:00":
                    pid_c = _norm_xq_pid(pid)
                    seen_db[c6].add(pid_c)
                    seen_all[c6].add(pid_c)
        finally:
            con.close()

    if os.path.exists(DB_COMM):
        con = sqlite3.connect(f"file:{DB_COMM}?mode=ro", uri=True)
        try:
            for sym, pid, ts in con.execute(
                f"SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND symbol IN ({ph}) AND pub_datetime_cst >= ? AND pub_datetime_cst < ?",
                (*codes, f"{d1_min} 00:00:00", end_cut),
            ):
                c6 = str(sym)[:6].zfill(6)
                ts_s = str(ts or "")
                assert ts_s < end_cut, f"PIT violation in astock_community_5y_pit: {ts_s} >= {end_cut}"
                if c6 in d1_map and ts_s >= f"{d1_map[c6]} 00:00:00":
                    pid_c = _norm_xq_pid(pid)
                    seen_db[c6].add(pid_c)
                    seen_all[c6].add(pid_c)
        finally:
            con.close()

    if include_live_json and os.path.exists(COMM_JSON):
        try:
            with open(COMM_JSON, "r", encoding="utf-8") as f:
                comm_items = json.load(f)
            for it in comm_items:
                if it.get("src") != "雪球":
                    continue
                pid_raw = str(it.get("id") or "").strip()
                if not pid_raw or pid_raw.startswith("xqev"):
                    continue
                ts_raw = str(it.get("time") or "").strip()
                if len(ts_raw) == 16:
                    ts_raw += ":00"
                if len(ts_raw) < 19 or not ts_raw[:4].isdigit():
                    continue
                if ts_raw > xq_json_max and ts_raw < end_cut:
                    xq_json_max = ts_raw
                if not (f"{d1_min} 00:00:00" <= ts_raw < end_cut):
                    continue
                assert ts_raw < end_cut, f"PIT violation in astock_community.json: {ts_raw} >= {end_cut}"
                ttl = str(it.get("title") or "")
                txt = str(it.get("text") or "")
                pid_c = _norm_xq_pid(pid_raw)
                for c6 in codes:
                    if ts_raw >= f"{d1_map[c6]} 00:00:00" and _match_comm_stock(ttl, txt, c6, name_map.get(c6, "")):
                        seen_all[c6].add(pid_c)
        except Exception as e:
            print(f"[WARN] live astock_community.json overlay error: {e}", file=sys.stderr)

    for c6 in codes:
        db_n = len(seen_db[c6])
        tot_n = len(seen_all[c6])
        out[c6] = {"total": tot_n, "db": db_n, "live_json": max(0, tot_n - db_n)}
    return out, xq_db_max, xq_json_max


def _fetch_ths_pool_online(sig_date: str) -> list[dict]:
    ymd = sig_date.replace("-", "")
    url = (
        "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&"
        "field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004&"
        f"filter=HS,GEM2STAR&order_field=330324&order_type=0&date={ymd}"
    )
    try:
        req = urllib.request.Request(url, headers=UA)
        js = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8", "ignore"))
        return js.get("data", {}).get("info", []) or []
    except Exception:
        return []


def _load_holders_merged() -> dict:
    p_all = json.load(open(HOLDERS_PATH, "r", encoding="utf-8")) if os.path.exists(HOLDERS_PATH) else {}
    if os.path.exists(HOLDERS_FREE_PATH):
        p_free = json.load(open(HOLDERS_FREE_PATH, "r", encoding="utf-8"))
        for c6, lst in p_free.items():
            if lst and c6 not in p_all:
                by_ed = {}
                for it in lst:
                    nd = str(it.get("NOTICE_DATE") or "")[:10]
                    ed = str(it.get("END_DATE") or "")[:10]
                    rt = float(it.get("FREE_HOLDNUM_RATIO") or 0.0)
                    if nd and ed and rt > 0:
                        rec = by_ed.setdefault(ed, [nd, 0.0, 0.0])
                        rec[0] = min(rec[0], nd)
                        rec[1] += rt
                        if rt >= 5.0:
                            rec[2] += rt
                if by_ed:
                    p_all[c6] = sorted([[v[0], ed, round(min(95.0, v[1]), 2), round(min(95.0, v[2]), 2)] for ed, v in by_ed.items()])
    return p_all


def _compute_plate_elo_fallback(df_act: pd.DataFrame, d3_date: str) -> dict[str, float]:
    kpl_days_map: dict[str, dict] = {}
    if os.path.exists(KPL_MERGED):
        with open(KPL_MERGED, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    try:
                        d = json.loads(ln)
                        dt = d.get("date", "")
                        if dt and dt < "2021-01-01":
                            kpl_days_map[dt] = d
                    except Exception:
                        pass
    if os.path.exists(KPL_5Y):
        with open(KPL_5Y, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    try:
                        d = json.loads(ln)
                        dt = d.get("date", "")
                        if dt and dt >= "2021-01-01":
                            kpl_days_map[dt] = d
                    except Exception:
                        pass
    if os.path.exists(KPL_V2):
        with open(KPL_V2, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    try:
                        d = json.loads(ln)
                        dt = d.get("date", "")
                        pls = d.get("plates", [])
                        if dt and pls and (dt not in kpl_days_map or len(pls) >= len(kpl_days_map[dt].get("plates", []))):
                            kpl_days_map[dt] = d
                    except Exception:
                        pass

    sub_act = df_act[["dt_str", "c6", "is_zt", "touch_zt", "is_yizi", "pct"]]
    d_stk_map = {(r.dt_str, r.c6): (r.is_zt, r.touch_zt, r.is_yizi, r.pct) for r in sub_act.itertuples(index=False)}
    r_elo: dict[str, float] = defaultdict(lambda: 100.0)
    p_last_idx: dict[str, int] = {}
    prev_p_stks: dict[str, list[str]] = {}
    sorted_days = [kpl_days_map[k] for k in sorted(kpl_days_map.keys()) if k <= d3_date]
    for day_idx, d_entry in enumerate(sorted_days):
        dt = d_entry["date"]
        for pname, c6_list in prev_p_stks.items():
            touches = seals = 0
            rets = []
            for sc6 in c6_list:
                st = d_stk_map.get((dt, sc6))
                if st is not None:
                    rets.append(st[3])
                    touches += int(st[1])
                    seals += int(st[0])
            if touches >= 2 and (seals / touches) < 0.50:
                r_elo[pname] -= 12.0 * ((touches - seals) / touches)
            elif rets and np.mean(rets) < -0.025:
                r_elo[pname] -= 10.0
            elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                r_elo[pname] += min(10.0, 5.0 + seals * 1.2)
            elif rets and np.mean(rets) > 0.025:
                r_elo[pname] += 6.0
        for p_k in list(r_elo.keys()):
            if day_idx - p_last_idx.get(p_k, day_idx) > 3:
                r_elo[p_k] = 100.0 + (r_elo[p_k] - 100.0) * 0.85
        new_p = {}
        for p in d_entry.get("plates", []):
            pname = p.get("plate", "")
            stocks = p.get("stocks", [])
            if pname and stocks:
                new_p[pname] = [str(s[0]).strip()[:6].zfill(6) for s in stocks]
                p_last_idx[pname] = day_idx
        prev_p_stks = new_p
    return dict(r_elo)


def build_premarket_cache(verbose: bool = True, as_of_date: str = "") -> dict:
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "turn", "oshare", "amount"]
    anchor_dt = pd.Timestamp(as_of_date) if as_of_date else pd.Timestamp.today()
    min_dt = anchor_dt - pd.Timedelta(days=120)
    flt = ds.field("date") >= min_dt
    if as_of_date:
        flt = flt & (ds.field("date") <= anchor_dt)

    df_act = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    df_act["c6"] = df_act["ticker"].astype(str).str[:6]
    df_act = df_act[df_act["c6"].str.startswith(("00", "60")) & (~df_act["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df_act["dt_str"] = df_act["date"].dt.strftime("%Y-%m-%d")
    max_p_date = df_act["dt_str"].max()

    patched_today = False
    live_csi_close = None
    if not as_of_date:
        try:
            idx_raw = urllib.request.urlopen("http://qt.gtimg.cn/q=sh000300", timeout=3).read().decode("gbk", errors="ignore")
            idx_p = idx_raw.split("~")
            dt14 = str(idx_p[30]).strip() if len(idx_p) > 30 else ""
            q_dt = f"{dt14[:4]}-{dt14[4:6]}-{dt14[6:8]}" if len(dt14) >= 8 and dt14[:8].isdigit() else ""
            q_hhmm = int(dt14[8:12]) if len(dt14) >= 12 and dt14[8:12].isdigit() else 0
            if q_dt > max_p_date and q_hhmm >= 1500:
                if len(idx_p) > 3 and float(idx_p[3] or 0) > 0:
                    live_csi_close = (q_dt, float(idx_p[3]))
                last_sub = df_act[df_act["dt_str"] == max_p_date]
                t_list = last_sub["ticker"].tolist()
                osh_map = dict(zip(last_sub["ticker"], last_sub["oshare"]))

                def _fetch_ch(ch):
                    ql = [f"{'sh' if x[:6].startswith('60') else 'sz'}{x[:6]}" for x in ch]
                    out = {}
                    try:
                        raw = urllib.request.urlopen(f"http://qt.gtimg.cn/q={','.join(ql)}", timeout=3).read().decode("gbk", errors="ignore")
                        for ln in raw.strip().split(";"):
                            if "~" not in ln:
                                continue
                            p = ln.split("~")
                            if len(p) > 38 and str(p[30]).strip()[:8] == dt14[:8] and float(p[3] or 0) > 0:
                                out[p[2].strip()] = (
                                    float(p[5] or p[3]), float(p[33] or p[3]), float(p[34] or p[3]),
                                    float(p[3]), float(p[38] or 0) / 100.0, float(p[37] or 0) * 10000.0,
                                )
                    except Exception:
                        pass
                    return out

                live_q = {}
                with ThreadPoolExecutor(max_workers=16) as ex:
                    for fq in as_completed([ex.submit(_fetch_ch, t_list[i : i + 80]) for i in range(0, len(t_list), 80)]):
                        live_q.update(fq.result())
                patch_rows = [
                    {
                        "date": pd.Timestamp(q_dt), "ticker": tk, "open": v[0], "high": v[1],
                        "low": v[2], "close": v[3], "turn": v[4], "oshare": osh_map.get(tk, np.nan),
                        "amount": v[5], "c6": tk[:6], "dt_str": q_dt,
                    }
                    for tk in t_list if (v := live_q.get(tk[:6])) is not None
                ]
                if len(patch_rows) >= 2000:
                    df_act = pd.concat([df_act, pd.DataFrame(patch_rows)], ignore_index=True)
                    df_act.drop_duplicates(subset=["c6", "dt_str"], keep="last", inplace=True)
                    patched_today = True
        except Exception as e:
            print(f"[WARN] live_3to4_v40 close patch skipped: {e}", file=sys.stderr)

    df_act.sort_values(["c6", "dt_str"], inplace=True)
    df_act.reset_index(drop=True, inplace=True)
    g = df_act.groupby("c6")
    df_act["pre_c"] = g["close"].shift(1)
    df_act["pct"] = df_act["close"] / df_act["pre_c"] - 1.0
    df_act["zt_px"] = np.floor(df_act["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df_act["is_zt"] = (df_act["close"] >= df_act["zt_px"] - 0.011) & (df_act["pct"] >= 0.095) & (df_act["pre_c"] > 0)
    df_act["touch_zt"] = (df_act["high"] >= df_act["zt_px"] - 0.011) & (df_act["pre_c"] > 0)
    df_act["is_yizi"] = df_act["is_zt"] & (df_act["open"] >= df_act["zt_px"] - 0.011) & (df_act["low"] >= df_act["zt_px"] - 0.011)
    df_act["is_dt"] = (df_act["close"] <= np.floor(df_act["pre_c"] * 0.90 * 100.0 + 0.5) / 100.0 + 0.011) & (df_act["pct"] <= -0.095)
    s_zt = df_act["is_zt"].astype(int)
    s_shift = g["is_zt"].shift(fill_value=False).astype(bool)
    df_act["streak"] = s_zt.groupby([df_act["c6"], (s_zt != s_shift).cumsum()]).cumsum() * s_zt

    # V4.0 U01: 启动前20日箱体低位 pos20_d0 (严格对齐 upgrade_3to4_pit.py lines 532-534)
    df_act["min20"] = g["low"].transform(lambda s: s.rolling(20, min_periods=10).min())
    df_act["max20"] = g["high"].transform(lambda s: s.rolling(20, min_periods=10).max())
    df_act["pos20_today"] = (df_act["close"] - df_act["min20"]) / (df_act["max20"] - df_act["min20"] + 1e-6)

    d_list = sorted(df_act["dt_str"].unique())
    d3_date, prev_d = d_list[-1], (d_list[-2] if len(d_list) >= 2 else d_list[-1])
    d3_ts = pd.Timestamp(d3_date)
    nxt_buy_date = (d3_ts + pd.Timedelta(days=(3 if d3_ts.weekday() == 4 else 1))).strftime("%Y-%m-%d")

    d3_df = df_act[df_act["dt_str"] == d3_date]
    mkt_max_b = int(d3_df["streak"].max()) if not d3_df.empty else 4
    prev_3b = set(df_act[(df_act["dt_str"] == prev_d) & (df_act["streak"] == 3)]["c6"])
    dt3_cnt = int(d3_df[d3_df["c6"].isin(prev_3b) & d3_df["is_dt"]]["c6"].nunique())

    csi_1d, csi_5d = -0.0068, -0.010
    if os.path.exists(IDX_PATH):
        try:
            csi_m = dict(json.load(open(IDX_PATH, "r", encoding="utf-8"))["sh000300"])
            if live_csi_close and live_csi_close[0] == d3_date:
                csi_m[d3_date] = live_csi_close[1]
            d_idx = sorted(k for k in csi_m if k <= d3_date)
            if d_idx:
                pos_idx = d_idx.index(d3_date) if d3_date in d_idx else len(d_idx) - 1
                if pos_idx >= 1:
                    csi_1d = float(csi_m[d_idx[pos_idx]] / csi_m[d_idx[pos_idx - 1]] - 1.0)
                if pos_idx >= 5:
                    csi_5d = float(csi_m[d_idx[pos_idx]] / csi_m[d_idx[pos_idx - 5]] - 1.0)
        except Exception:
            pass

    ths_path = f"{THS_DIR}/{d3_date}.json"
    ths_stocks = json.load(open(ths_path, "r", encoding="utf-8")).get("stocks", []) if os.path.exists(ths_path) else _fetch_ths_pool_online(d3_date)
    ths_map = {str(s.get("code"))[:6].zfill(6): s for s in ths_stocks}
    mkt_zt_prev = len(ths_stocks) if ths_stocks else int(d3_df["is_zt"].sum())

    csrc_name_map: dict[str, str] = {}
    csrc_l2_p = f"{DATA_DIR}/csrc_industry_l2.csv"
    if os.path.exists(csrc_l2_p):
        try:
            _df_nm = pd.read_csv(csrc_l2_p, usecols=["code", "code_name"])
            _df_nm["c6"] = _df_nm["code"].astype(str).str[-6:].str.zfill(6)
            csrc_name_map = dict(zip(_df_nm["c6"], _df_nm["code_name"].fillna("")))
        except Exception:
            pass

    tape_map = {}
    if os.path.exists(DB_ZT_TAPE):
        con_tp = sqlite3.connect(f"file:{DB_ZT_TAPE}?mode=ro", uri=True)
        try:
            for sc, fst, obc in con_tp.execute(
                "SELECT sec_code, first_seal_time, open_board_count FROM zt_micro_tape WHERE trade_date = ?",
                (d3_date,),
            ):
                tape_map[str(sc)[:6].zfill(6)] = (
                    str(fst or ""),
                    int(obc) if obc is not None else -1,
                )
        finally:
            con_tp.close()

    holders = _load_holders_merged()
    cut_tox = (d3_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    cut_reg = (d3_ts - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    d_m5 = d_list[max(0, len(d_list) - 5)]
    stk_reg, tox_stk = set(), set()
    ex_reg_stocks = {"SH": set(), "SZ": set()}

    for db_p in (DB_NOTICES, DB_PIT_NOTICES):
        if not os.path.exists(db_p):
            continue
        con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
        try:
            col_c = "sec_code" if "cninfo" in db_p else "code"
            col_d = "pub_datetime_cst" if "cninfo" in db_p else "ndate"
            tbl = "notices" if "cninfo" in db_p else "notice"
            for c_raw, pdt, ti in con.execute(
                f"SELECT {col_c}, {col_d}, title FROM {tbl} WHERE {col_d} >= ? AND {col_d} <= ?",
                (cut_tox, f"{d3_date} 23:59:59"),
            ):
                c6_s, dt_s, t_str = str(c_raw)[:6].zfill(6), str(pdt)[:10], str(ti or "")
                if dt_s >= cut_reg and any(w in t_str for w in REG_INC) and not any(w in t_str for w in REG_EXC):
                    stk_reg.add(c6_s)
                if d_m5 <= dt_s <= d3_date and any(w in t_str for w in REG_INC) and not any(w in t_str for w in REG_EXC):
                    if c6_s.startswith("60"):
                        ex_reg_stocks["SH"].add(c6_s)
                    elif c6_s.startswith("00"):
                        ex_reg_stocks["SZ"].add(c6_s)
                if TOX_RE.search(t_str):
                    tox_stk.add(c6_s)
        except Exception as e:
            print(f"[WARN] live_3to4_v40 notices DB error in {db_p}: {e}", file=sys.stderr)
        finally:
            con.close()

    if os.path.exists(PQ_REG_TOX):
        try:
            rt = pd.read_parquet(PQ_REG_TOX, columns=["sec_code", "pub_datetime_cst", "title"])
            rt["dt10"] = rt["pub_datetime_cst"].astype(str).str[:10]
            rt = rt[(rt["dt10"] >= cut_tox) & (rt["dt10"] <= d3_date)]
            for sc, dt_s, ti in zip(rt["sec_code"].astype(str).str[:6].str.zfill(6), rt["dt10"], rt["title"].astype(str)):
                if TOX_RE.search(ti):
                    tox_stk.add(sc)
                if dt_s >= cut_reg and any(w in ti for w in REG_INC) and not any(w in ti for w in REG_EXC):
                    stk_reg.add(sc)
        except Exception:
            pass

    for zf in glob.glob(ZDJK_GLOB):
        try:
            for it in json.load(open(zf, "r", encoding="utf-8")).get("List", []):
                dt_z = str(it[2])[:10]
                if cut_reg <= dt_z <= d3_date:
                    stk_reg.add(str(it[0]).zfill(6))
        except Exception:
            pass

    plate_elo_map = {}
    c1_path = f"{DATA_DIR}/1to2_premarket_cache.json"
    if os.path.exists(c1_path):
        try:
            c1_data = json.load(open(c1_path, "r", encoding="utf-8"))
            if c1_data.get("d1_date") == d3_date and c1_data.get("theme_board"):
                for tb in c1_data["theme_board"]:
                    plate_elo_map[tb["plate"]] = float(tb["elo"])
        except Exception:
            pass
    if not plate_elo_map:
        plate_elo_map = _compute_plate_elo_fallback(df_act, d3_date)

    lh_map, surf_map, lhb_has_d3 = {}, {}, False
    if os.path.exists(LHB_PATH):
        try:
            lb = pd.read_parquet(LHB_PATH, columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME"])
            lb_d3 = lb[lb["TRADE_DATE"].astype(str).str[:10] == d3_date]
            if not lb_d3.empty:
                lhb_has_d3 = True
                for c6_u, grp in lb_d3.groupby(lb_d3["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)):
                    seats = grp["OPERATEDEPT_NAME"].astype(str).tolist()
                    lh_map[c6_u] = sum(1 for s in seats if "拉萨" in s)
                    surf_map[c6_u] = any(SURF_YZ.search(s) for s in seats)
        except Exception as e:
            print(f"[WARN] live_3to4_v40 LHB parquet error: {e}", file=sys.stderr)

    cands_b3 = sorted(d3_df[d3_df["streak"] == 3]["c6"].tolist())
    if not lhb_has_d3 and cands_b3:
        for c6_u in cands_b3:
            seats_buy = []
            try:
                url = (
                    "https://datacenter-web.eastmoney.com/api/data/v1/get?"
                    "reportName=RPT_BILLBOARD_DAILYDETAILSBUY&columns=TRADE_DATE,SECURITY_CODE,OPERATEDEPT_NAME&"
                    f"filter=(SECURITY_CODE%3D%22{c6_u}%22)&sortColumns=TRADE_DATE&sortTypes=-1&pageNumber=1&pageSize=50&source=WEB&client=WEB"
                )
                req = urllib.request.Request(url, headers=UA)
                with urllib.request.urlopen(req, timeout=4) as resp:
                    js = json.loads(resp.read().decode("utf-8", "ignore"))
                    for r_item in (js.get("result") or {}).get("data") or []:
                        if str(r_item.get("TRADE_DATE", ""))[:10] == d3_date:
                            seats_buy.append(str(r_item.get("OPERATEDEPT_NAME", "")))
            except Exception:
                pass
            if seats_buy:
                lh_map[c6_u] = sum(1 for s in seats_buy if "拉萨" in s)
                surf_map[c6_u] = any(SURF_YZ.search(s) for s in seats_buy)

    cand_bars_map: dict[str, pd.DataFrame] = {
        c6: df_act[df_act["c6"] == c6].sort_values("dt_str").reset_index(drop=True)
        for c6 in cands_b3
    }
    xq_items: list[tuple[str, str, str]] = []
    for c6 in cands_b3:
        ts = ths_map.get(c6, {})
        nm = str(ts.get("name") or csrc_name_map.get(c6) or "")
        if "ST" in nm.upper():
            continue
        sb = cand_bars_map[c6]
        d1_dt = str(sb.iloc[-3]["dt_str"]) if len(sb) >= 3 else d3_date
        xq_items.append((c6, nm, d1_dt))

    xq_map, xq_db_max, xq_json_max = load_xq_counts_2d(xq_items, nxt_buy_date, include_live_json=True)

    candidates = []
    for c6 in cands_b3:
        sb = cand_bars_map[c6]
        r = sb.iloc[-1]
        ts = ths_map.get(c6, {})
        name = str(ts.get("name") or csrc_name_map.get(c6) or c6)
        if "ST" in name.upper():
            continue

        prev_is_yizi = bool(r["open"] >= r["zt_px"] - 0.011 and r["low"] >= r["zt_px"] - 0.011)
        tp = tape_map.get(c6)
        if tp and tp[0]:
            fst = tp[0]
            opn_cnt = tp[1] if tp[1] >= 0 else int(ts.get("open_num") or 0)
        else:
            opn_cnt = int(ts.get("open_num") or 0)
            fst = (
                datetime.datetime.fromtimestamp(int(ts["first_limit_up_time"])).strftime("%H:%M:%S")
                if ts.get("first_limit_up_time")
                else "09:30:00"
            )

        valid_holders = [
            x for x in holders.get(c6, []) if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= d3_date
        ]
        if valid_holders:
            lock10 = float(max(valid_holders, key=lambda x: (str(x[1]), str(x[0])))[2])
            lock_missing = False
        else:
            lock10 = 38.0
            lock_missing = True
            print(f"[WARN] 标的 {c6} ({name}) 缺失截至 {d3_date} 的 PIT 锁仓数据，标记 lock_missing=True 按 38.0% 兜底！", file=sys.stderr)

        osh = float(r.get("oshare", 0.0) or 0.0)
        mcap = (float(r["close"]) * osh / 1e8) if osh > 0 else (
            float(r["amount"]) / float(r["turn"]) / 1e8 if r["turn"] > 0 else 50.0
        )
        reason = str(ts.get("reason_type", ""))
        my_kws = _extract_keywords(reason)
        plate_fb, plate_zt = [], []
        for s in ths_stocks:
            sc6 = str(s.get("code"))[:6].zfill(6)
            if sc6 != c6 and (my_kws & _extract_keywords(s.get("reason_type", ""))):
                plate_zt.append(sc6)
                if "首板" in str(s.get("high_days", "")):
                    plate_fb.append(sc6)

        matched_elos = [float(pv) for pn, pv in plate_elo_map.items() if (pn in reason) or any((kw in pn or pn in kw) for kw in my_kws)]
        p_elo_cand = round(max(matched_elos, default=100.0), 2)
        ex_key = "SH" if c6.startswith("60") else "SZ"
        has_ex_reg = len(ex_reg_stocks[ex_key]) >= 2

        d1_dt = str(sb.iloc[-3]["dt_str"]) if len(sb) >= 3 else d3_date
        d0_dt = str(sb.iloc[-4]["dt_str"]) if len(sb) >= 4 else d1_dt
        pos20_val = round(float(sb.iloc[-4]["pos20_today"]), 4) if (len(sb) >= 4 and pd.notna(sb.iloc[-4]["pos20_today"])) else 0.50
        xq_info = xq_map.get(c6, {"total": 0, "db": 0, "live_json": 0})

        cand_dict = {
            "code": c6, "name": name, "sig_date": d3_date, "d1_date": d1_dt, "d0_date": d0_dt, "buy_date": nxt_buy_date,
            "is_10cm_non_st": True, "prev_is_yizi": prev_is_yizi, "open_board_count": opn_cnt,
            "prev_to": round(float(r["turn"] * 100.0 if r["turn"] < 1.0 else r["turn"]), 2),
            "px_d3": round(float(r["close"]), 2), "lock_top10": round(lock10, 2), "lock_missing": lock_missing,
            "real_free_mcap": round(mcap * max(0.05, 1.0 - lock10 / 100.0), 2), "first_seal_time": fst,
            "mkt_max_board_prev": mkt_max_b, "p_elo": p_elo_cand,
            "plate": reason or "主线题材", "reason_type": reason,
            "has_tox_notice": c6 in tox_stk, "has_stock_reg": c6 in stk_reg, "has_ex_reg": has_ex_reg,
            "ex_reg_cnt": len(ex_reg_stocks[ex_key]),
            "surf_yz_buy": surf_map.get(c6, False), "lhb_lh_cnt": lh_map.get(c6, 0),
            "plate_fb_codes": plate_fb, "plate_zt_codes": plate_zt,
            "pos20_d0": pos20_val,
            "xq_cnt_2d": int(xq_info["total"]),
            "xq_cnt_db": int(xq_info["db"]),
            "xq_cnt_live_json": int(xq_info["live_json"]),
        }
        candidates.append(cand_dict)

    env = {
        "mkt_max_board_prev": mkt_max_b,
        "mkt_zt_prev": mkt_zt_prev,
        "prev_3b_dt_cnt": dt3_cnt,
        "csi_1d_prev": round(csi_1d, 4),
        "csi_5d_prev": round(csi_5d, 4),
    }
    cache = {
        "version": "3TO4_V40_PROD_20261117",
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_as_of_date": d3_date,
        "d3_date": d3_date,
        "buy_date": nxt_buy_date,
        "patched_today": patched_today,
        "xq_db_max_date": xq_db_max,
        "xq_comm_json_max_time": xq_json_max,
        "candidates": candidates,
        "env": env,
    }
    if not as_of_date:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CACHE_FILE)
    if verbose:
        print(f"[+] V4.0 Premarket cache built in {time.time()-t0:.2f}s -> {CACHE_FILE} | {len(candidates)} candidates on {d3_date} (patched={patched_today})")
    return cache


def fetch_tencent_batch(codes: list[str]) -> dict[str, dict]:
    if not codes:
        return {}
    clist = sorted(set(str(c).zfill(6) for c in codes))
    res: dict[str, dict] = {}
    for i in range(0, len(clist), 80):
        chunk = clist[i : i + 80]
        q_list = [f"{'sh' if c.startswith('60') else 'sz'}{c}" for c in chunk]
        url = f"http://qt.gtimg.cn/q={','.join(q_list)}"
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                content = resp.read().decode("gbk", errors="ignore")
                for line in content.strip().split(";"):
                    if not line.strip() or "~" not in line:
                        continue
                    parts = line.split("~")
                    if len(parts) > 30:
                        c6 = parts[2].strip()
                        px = float(parts[3]) if parts[3] else 0.0
                        pc = float(parts[4]) if parts[4] else 0.0
                        op = float(parts[5]) if parts[5] else 0.0
                        b1_v = float(parts[10]) if len(parts) > 10 and parts[10] else 0.0
                        s1_v = float(parts[20]) if len(parts) > 20 and parts[20] else 0.0
                        dt8 = str(parts[30]).strip()[:8]
                        q_dt = f"{dt8[:4]}-{dt8[4:6]}-{dt8[6:8]}" if len(dt8) == 8 and dt8.isdigit() else ""
                        op_px = op if op > 0.0 else px
                        op_pct = (op_px / pc - 1.0) if pc > 0 else 0.0
                        zt_px = float(np.floor(pc * 1.10 * 100.0 + 0.5) / 100.0) if pc > 0 else 999.0
                        is_yz = bool(op_px >= zt_px - 0.005 or (b1_v > 0 and s1_v == 0 and op_pct >= 0.090))
                        res[c6] = {
                            "name": parts[1], "code": c6, "price": px, "pre_c": pc,
                            "open": op_px, "open_pct": op_pct, "zt_px": zt_px, "is_yizi": is_yz, "q_dt": q_dt,
                        }
        except Exception:
            pass
    return res


def run_premarket(cache: dict) -> None:
    env = cache.get("env", {})
    cands = cache.get("candidates", [])
    d3, bd = cache.get("d3_date", ""), cache.get("buy_date", "")
    print("=" * 90)
    print(f"【三进四主战策略 V4.0 (互学瘦身正式版) 盘前环境与推演面板】 信号日: {d3} -> 竞价日: {bd}")
    print(
        f"大盘情绪: 最高连板={env.get('mkt_max_board_prev')}板 | 全市场涨停={env.get('mkt_zt_prev')}家 | "
        f"三板跌停={env.get('prev_3b_dt_cnt')}家 | 沪深300 1日={env.get('csi_1d_prev', 0)*100:+.2f}%, 5日={env.get('csi_5d_prev', 0)*100:+.2f}%"
    )
    print("V4.0规则: 底分78 · 22项打分(删T10周一/T14百股过热/T20高价32元; 增U01低位<=0.40+5 / U02雪球>=4帖-15) | 撤单窗: 09:30至10:30")
    print("=" * 90)

    if not cands:
        print("  今日无 10cm 非ST 三连板候选标的。")
        return

    for c in cands:
        c6, name = c["code"], c["name"]
        px3, to = c["px_d3"], c["prev_to"]
        lock, rfm = c["lock_top10"], c["real_free_mcap"]
        opn, fst = c["open_board_count"], c["first_seal_time"]
        pos20, xq2 = float(c.get("pos20_d0", 0.50)), int(c.get("xq_cnt_2d", 0))
        base_r = dict(
            c, open_pct=0.055, buyable_open=True, is_top1_3b_open=True,
            plate_fb_ho_cnt=0, plate_fb_yz_cnt=0, plate_peers_open_avg=0.01,
            prev_3b_dt_cnt=env.get("prev_3b_dt_cnt", 0), csi_1d_prev=env.get("csi_1d_prev", 0.0),
            csi_5d_prev=env.get("csi_5d_prev", 0.0), mkt_zt_prev=env.get("mkt_zt_prev", 50),
        )
        res_base = score_single_3to4_v40_row(base_r)
        trig = max(round(px3 * 1.065, 2), round(px3 * 1.055, 2))
        print(
            f"\n标的: {c6} {name} | 三板收盘: {px3:.2f}元 | 换手: {to:.2f}% | 锁仓: {lock:.1f}% | 自由盘: {rfm:.1f}亿 | "
            f"封板: {fst} (开板{opn}次) | U01低位pos20_d0={pos20:.2f} | U02雪球2日={xq2}帖(库{c.get('xq_cnt_db',0)}+实时{c.get('xq_cnt_live_json',0)})"
        )
        if not res_base["passed_skeleton"]:
            print(f"  ❌ 硬骨架否决: {res_base['breakdown_str']}")
            continue
        print(f"  ✅ V4.0静态基准预评分: {res_base['score']}分 ({res_base['tier']})")
        print(f"  📝 V4.0加减分细目: {res_base['breakdown_str']}")
        print("  🎯 09:25 竞价过线推演:")
        print(f"     - 标准主力单 (>=90分): 竞价 +3.0% 至 +9.2% 且为可买三板头名即得 {res_base['score']}分")
        print(f"     - 严格高确信 (>=98分): 需同题材前日首板队友换手高开(>=3%)助攻 >=2 只 (+4分 -> {res_base['score']+4}分)")
        print(f"     - S档极严防守 (>=102分): 同题材助攻+题材热度>=115 ({res_base['score']+7}分)")
        print(f"  ⚡ 09:26 突破条件单触发价公式: max(昨收*1.065, 今开价) = {trig:.2f}元 (卖五价扫入，09:30至10:30有效，10:30未触发立即撤单)")


def run_live_mode(cache: dict, mock_open_map: dict | None = None) -> list[dict]:
    t0 = time.time()
    env = cache.get("env", {})
    cands = cache.get("candidates", [])
    buy_date = cache.get("buy_date", "")
    all_codes = {c["code"] for c in cands}
    for c in cands:
        all_codes.update(c.get("plate_fb_codes", []))
        all_codes.update(c.get("plate_zt_codes", []))

    quotes = fetch_tencent_batch(list(all_codes))
    now = datetime.datetime.now()
    in_trading_hhmm = now.weekday() < 5 and ((now.hour == 9 and now.minute >= 25) or (10 <= now.hour < 15))
    any_buy_day_live = any(q.get("q_dt") == buy_date and q.get("open", 0) > 0 for q in quotes.values())
    is_live = bool(any_buy_day_live or (in_trading_hhmm and any(q.get("open", 0) > 0 for q in quotes.values())))

    cand_inputs = []
    for c in cands:
        c6 = c["code"]
        q = quotes.get(c6, {})
        op_pct = 0.055
        if mock_open_map and c6 in mock_open_map:
            op_pct = float(mock_open_map[c6])
            buyable = bool(op_pct < 0.098)
        elif is_live and q.get("open", 0) > 0 and q.get("pre_c", 0) > 0 and (not buy_date or q.get("q_dt") == buy_date):
            op_pct = float(q["open"] / q["pre_c"] - 1.0)
            buyable = bool(op_pct < 0.098 and (not q.get("is_yizi", False)))
        else:
            buyable = bool(op_pct < 0.098)
        cand_inputs.append({"c": c, "q": q, "op_pct": op_pct, "buyable": buyable})

    max_op = max([ci["op_pct"] for ci in cand_inputs if ci["buyable"]], default=-9.99)
    results = []
    mode_lbl = "模拟竞价" if mock_open_map else ("实盘开盘竞价" if (is_live and any_buy_day_live) else "盘前/盘后快照（默认+5.5%基准场景）")

    print("=" * 90)
    print(f"【三进四主战策略 V4.0 极速决策引擎】 信号日={cache.get('d3_date','')} -> 买日={buy_date} | 耗时: {time.time()-t0:.3f}s | 时段: {mode_lbl}")
    print("=" * 90)

    if not cand_inputs:
        print("  今日无 10cm 非ST 三连板候选标的，三进四空仓。")
        return []

    for ci in cand_inputs:
        c = ci["c"]
        c6, name, px3 = c["code"], c["name"], c["px_d3"]
        op_pct, buyable = ci["op_pct"], ci["buyable"]
        is_top1 = bool(buyable and op_pct >= max_op - 1e-5)

        fb_ho, fb_yz, peer_ops = 0, 0, []
        for s6 in c.get("plate_fb_codes", []):
            sq = quotes.get(s6, {})
            if mock_open_map and s6 in mock_open_map:
                so_pct = float(mock_open_map[s6])
                syz = bool(so_pct >= 0.098)
            elif is_live and sq.get("q_dt") == buy_date:
                so_pct = sq.get("open_pct", 0.0)
                syz = sq.get("is_yizi", False)
            else:
                so_pct, syz = 0.015, False
            if so_pct >= 0.03 and not syz:
                fb_ho += 1
            if syz:
                fb_yz += 1

        for z6 in c.get("plate_zt_codes", []):
            if mock_open_map and z6 in mock_open_map:
                peer_ops.append(float(mock_open_map[z6]))
            elif is_live and z6 in quotes and quotes[z6].get("q_dt") == buy_date:
                peer_ops.append(quotes[z6]["open_pct"])
        peers_avg = float(sum(peer_ops) / len(peer_ops)) if peer_ops else 0.01

        row = dict(
            c, open_pct=op_pct, buyable_open=buyable, is_top1_3b_open=is_top1,
            plate_fb_ho_cnt=fb_ho, plate_fb_yz_cnt=fb_yz, plate_peers_open_avg=peers_avg,
            prev_3b_dt_cnt=env.get("prev_3b_dt_cnt", 0), csi_1d_prev=env.get("csi_1d_prev", 0.0),
            csi_5d_prev=env.get("csi_5d_prev", 0.0), mkt_zt_prev=env.get("mkt_zt_prev", 50),
        )
        sc_res = score_single_3to4_v40_row(row)
        trig = max(round(px3 * 1.065, 2), round(px3 * (1.0 + op_pct), 2))
        results.append({
            "code": c6, "name": name, "open_pct": op_pct, "score": sc_res["score"],
            "tier": sc_res["tier"], "trig_px": trig, "breakdown": sc_res["breakdown_str"],
            "passed": sc_res["passed_skeleton"], "pos20_d0": c.get("pos20_d0", 0.50),
            "xq_cnt_2d": c.get("xq_cnt_2d", 0),
        })

        status_tag = "🚀 [S档>=102]" if sc_res["score"] >= 102 else ("🚀 [达标主力>=90]" if sc_res["score"] >= 90 else "⛔ [未达标]")
        print(
            f"\n{status_tag} {c6} {name:6s} | 竞价: {op_pct*100:+.2f}% (头名={is_top1}) | "
            f"V4.0总分: {sc_res['score']:4d} | 分档: {sc_res['tier']} | pos20={c.get('pos20_d0',0.5):.2f} xq={c.get('xq_cnt_2d',0)}帖"
        )
        print(f"  触发价: {trig:6.2f}元 (max(昨收*1.065, 今开)) | 执行: 09:26挂突破条件单，卖五价扫入，09:30至10:30有效，10:30未触立即撤单")
        print(f"  细目: {sc_res['breakdown_str']}")
    return results


def _enrich_history_v40(rows: pd.DataFrame) -> dict[tuple[str, str], dict]:
    """为历史台账查询补充 pos20_d0, xq_cnt_2d 与 V4.0 评分明细（只读）。"""
    if rows.empty or not os.path.exists(ENRICHED_PARQUET):
        return {}
    enr = pd.read_parquet(ENRICHED_PARQUET)
    enr["code"] = enr["code"].astype(str).str.zfill(6)
    keys = {(str(r["buy_date"]), str(r["code"]).zfill(6)) for _, r in rows.iterrows()}
    sub_e = enr[enr.apply(lambda x: (str(x["buy_date"]), x["code"]) in keys, axis=1)].copy()
    if sub_e.empty:
        return {}

    codes = sorted(sub_e["code"].unique().tolist())
    min_bd = str(sub_e["buy_date"].min())
    max_bd = str(sub_e["buy_date"].max())
    min_dt = (pd.Timestamp(min_bd) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    max_dt = max_bd

    px_frames = []
    for pq in (A_DAILY, A_DELISTED):
        if os.path.exists(pq):
            t = ds.dataset(pq, format="parquet").scanner(
                columns=["date", "ticker", "high", "low", "close"],
                filter=(ds.field("date") >= pd.Timestamp(min_dt)) & (ds.field("date") <= pd.Timestamp(max_dt)),
            ).to_table().to_pandas()
            t["c6"] = t["ticker"].astype(str).str[:6]
            px_frames.append(t[t["c6"].isin(codes)])
    px_df = pd.concat(px_frames, ignore_index=True) if px_frames else pd.DataFrame()
    pos20_map: dict[tuple[str, str], float] = {}
    d1_map: dict[tuple[str, str], str] = {}
    if not px_df.empty:
        px_df["dt_str"] = px_df["date"].dt.strftime("%Y-%m-%d")
        px_df.sort_values(["c6", "dt_str"], inplace=True)
        px_df.drop_duplicates(["c6", "dt_str"], keep="first", inplace=True)
        g = px_df.groupby("c6")
        px_df["min20"] = g["low"].transform(lambda s: s.rolling(20, min_periods=10).min())
        px_df["max20"] = g["high"].transform(lambda s: s.rolling(20, min_periods=10).max())
        px_df["pos20_today"] = (px_df["close"] - px_df["min20"]) / (px_df["max20"] - px_df["min20"] + 1e-6)
        px_df["pos20_d0"] = g["pos20_today"].shift(4)
        px_df["d1_dt"] = g["dt_str"].shift(3)
        for rr in px_df.itertuples(index=False):
            if (rr.dt_str, rr.c6) in keys:
                pos20_map[(rr.dt_str, rr.c6)] = round(float(rr.pos20_d0), 4) if pd.notna(rr.pos20_d0) else 0.50
                d1_map[(rr.dt_str, rr.c6)] = str(rr.d1_dt) if pd.notna(rr.d1_dt) else rr.dt_str

    details: dict[tuple[str, str], dict] = {}
    for _, r in sub_e.iterrows():
        bd, c6 = str(r["buy_date"]), str(r["code"]).zfill(6)
        d1_dt = d1_map.get((bd, c6), str(r.get("sig_date", bd)))
        xq_res, _, _ = load_xq_counts_2d([(c6, str(r.get("name", "")), d1_dt)], bd, include_live_json=False)
        rd = r.to_dict()
        rd["pos20_d0"] = pos20_map.get((bd, c6), 0.50)
        rd["xq_cnt_2d"] = xq_res.get(c6, {}).get("total", 0)
        sc = score_single_3to4_v40_row(rd)
        details[(bd, c6)] = {
            "px_d3": float(r.get("px_d3", 0.0)),
            "open_pct": float(r.get("open_pct", 0.0)),
            "pos20_d0": rd["pos20_d0"],
            "xq_cnt_2d": rd["xq_cnt_2d"],
            "v40_calc": sc,
        }
    return details


def query_history(date_str: str = "", recent_n: int = 0) -> None:
    """查询 V4.0 官方台账 ledger_upg_3to4_std.csv 与 V4.0 评分明细。"""
    if not os.path.exists(LEDGER_V40_STD):
        print(f"[ERR] 未找到 V4.0 历史台账: {LEDGER_V40_STD}", file=sys.stderr)
        return
    df_l = pd.read_csv(LEDGER_V40_STD, dtype={"code": str})
    df_l["code"] = df_l["code"].str.zfill(6)

    if date_str:
        sub = df_l[df_l["buy_date"] == date_str].copy()
        print(f"=== 三进四 V4.0 历史台账查询 (buy_date={date_str}, 来源=ledger_upg_3to4_std.csv) ===")
        if sub.empty and os.path.exists(SUMMARY_V40_JSON):
            sm = json.load(open(SUMMARY_V40_JSON, "r", encoding="utf-8"))
            tails = sm.get("zero_lookahead_and_5m_audit", {}).get("five_minute_coverage", {}).get("period_2026_11_11_to_16", {}).get("detail_scores", [])
            hits = [x for x in tails if x.get("buy_date") == date_str]
            if hits:
                print("  当日无 >=90 分成交单，以下为 V4.0 核心池落选明细:")
                for h in hits:
                    print(f"    [{h['buy_date']}] {str(h['code']).zfill(6)} | V4.0总分={h['v40_score']} | xq_cnt_2d={h['xq_cnt_2d']}帖 (<90分放弃)")
                return
        if sub.empty:
            print(f"  {date_str} 在 V4.0 标准90分台账中无成交记录。")
            return
    else:
        n = recent_n if recent_n > 0 else 10
        sub = df_l.sort_values(["buy_date", "buy_hhmm"]).tail(n).copy()
        print(f"=== 三进四 V4.0 最近 {len(sub)} 笔实盘台账与评分明细 (全五年95笔 / 胜率68.42% / 单仓1799.99x / DSR 0.9818) ===")

    enr_details = _enrich_history_v40(sub)
    for _, r in sub.iterrows():
        c6, bd = r["code"], r["buy_date"]
        sc_ledger = int(r["score"])
        tier_tag = "S档(>=102)" if sc_ledger >= 102 else "标准(>=90)"
        edet = enr_details.get((bd, c6))
        trig_s = ""
        detail_s = ""
        if edet:
            trig_px = max(round(edet["px_d3"] * 1.065, 2), round(edet["px_d3"] * (1.0 + edet["open_pct"]), 2))
            trig_s = f" | 触发价={trig_px:.2f} | pos20={edet['pos20_d0']:.2f} xq={edet['xq_cnt_2d']}帖"
            detail_s = f"\n    V4.0细目: {edet['v40_calc']['breakdown_str']}"
        print(
            f"[{bd}] {c6} {r['name']:6s} | V4.0得分={sc_ledger:3d} [{tier_tag}] | "
            f"买={int(r['buy_hhmm']):04d}@{r['buy_price']:.2f} -> 卖={r['exit_date']} {int(r['exit_hhmm']):04d}@{r['exit_price']:.2f} | "
            f"净收益={r['net_ret']*100:+.2f}%{trig_s}{detail_s}"
        )

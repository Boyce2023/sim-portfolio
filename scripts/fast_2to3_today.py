#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_2to3_today.py — 二进三 V2.1 (V2.0互学买点 + 13:45破+6.5%护利, s_2to3, 底分60, 标准满90分第4顺位[T2完备5m: 95笔/52.63%/313.87x/MDD 28.68%], 满96分高严档[35笔/54.29%/23.36x/MDD 15.87%])
模式:
  1. --build-cache : 读取只读 PIT 库 + 腾讯实时收盘补丁构建 data/2to3_premarket_cache.json
  2. --premarket   : 早盘 09:15 前秒读缓存输出候选池、静态预评分与竞价情景推演
  3. 默认盘中秒跑  : 09:25:03 秒读缓存并拉取腾讯实时竞价，输出标准过线 (>=90) 与满96分单独重点提醒
  4. --hold <CODE> : 拉取腾讯实时行情，打印当日 +9.2% 竞价止盈价、+8.5% 摸高激活价与 +6.5% 午后护利锁利价
  5. --date / --recent [--strict] : 查询五年干净回测台账 ledger_upg_2to3_std.csv / ledger_upg_2to3_strict.csv
严格遵守 D12 铁律（严禁 import yfinance），SQLite 全程 file:...?mode=ro 只读。
"""
import os
import sys
import re
import json
import time
import bisect
import sqlite3
import datetime
import argparse
import urllib.request
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM}/data"
ND_DIR = f"{ROOT}/news-dashboard"

CACHE_FILE = f"{DATA_DIR}/2to3_premarket_cache.json"
A_DAILY = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
KPL_MERGED = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
KPL_V2 = f"{ND_DIR}/output/kpl_plates_v2.jsonl"
THS_DIR = f"{DATA_DIR}/ths_limit_up_daily"
ST_UNIVERSE = f"{DATA_DIR}/st_universe.json"
REG_TOX_PQ = f"{DATA_DIR}/pit_reg_tox_notices_5y_complete.parquet"
CSRC_PIT_CSV = f"{DATA_DIR}/csrc_industry_pit_clean.csv"
CSRC_L2_CSV = f"{DATA_DIR}/csrc_industry_l2.csv"
HOLDERS_ALL = f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
HOLDERS_FREE = f"{SIM}/backtests_astock/sandbox_lab/pit_top10_freeholders_cache.json"

DB_NOTICES = f"{SIM}/backtest/2026-08-24-daban/notices.db"
DB_PIT_NOTICES = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
DB_ZT_TAPE = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"
DB_FB_5M = f"{SIM}/backtests_astock2/data_5y/firstboard_5m_5y_pit.db"
DB_IR_QA = f"{SIM}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db"
DB_IR_QA_ALT = f"{DATA_DIR}/cninfo_ir_qa_5y_pit.db"
DB_XQ_GB = f"{DATA_DIR}/xueqiu_guba_5y_pit.db"
DB_COMM = f"{DATA_DIR}/astock_community_5y_pit.db"
LEDGER_CSV = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117/ledger_upg_2to3_std.csv"
LEDGER_STRICT_CSV = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117/ledger_upg_2to3_strict.csv"

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
NON_THEME = {
    "其他", "公告", "ST板块", "三季报增长", "业绩增长", "半年报增长",
    "年报增长", "一季报增长", "中报增长", "次新股",
}
EVENT_BASKET = {
    "并购重组", "股权转让", "资产注入", "国企改革", "央企改革",
    "地方国资改革", "业绩增长", "预盈预增", "摘帽", "回购",
    "增持", "次新股", "高送转", "参股新股", "三季报增长",
    "半年报增长", "年报增长", "一季报增长", "中报增长",
}
HARD_TECH_RE = re.compile(
    r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)"
)
CSRC_PURE_OUTSIDER = {
    "A01", "A02", "A03", "A04", "A05",
    "D44", "D45", "D46",
    "E47", "E48", "E49", "E50",
    "F51", "F52",
    "G53", "G54", "G55", "G56", "G58", "G59",
    "H61", "H62",
    "K70", "L72", "N77", "N78",
    "C13", "C14", "C15", "C17", "C18", "C19", "C20", "C21", "C22",
}
MA_PAT = re.compile(r"(重组|收购|股权转让|实控人变更|控制权变更|资产注入|借壳|控股|整合|中标|重大合同)")
HARD_NOTICE_PAT = re.compile(r"(重组|收购|股权转让|控制权|实控人变更|资产注入|借壳|重大合同|中标|战略合作|框架协议|投资设立)")
BAD_NOTICE_PAT = re.compile(
    r"(减持|问询函|监管函|警示函|立案|风险提示|业绩预亏|亏损|计提资产减值|退市风险|终止上市|违规|质押|冻结)"
)
NEG_NOTICE_PAT = re.compile(
    r"(不存在|不涉及|未筹划|未发现|无应披露|股票交易异常波动|异常波动公告|风险提示|占比极小|敬请广大投资者注意)"
)
TOX_RE = re.compile(r"(?:减持计划|股东减持|立案调查|收到立案|退市风险|违法违规|终止上市|风险提示|问询函|监管函|关注函|警示函|停牌核查)")
REG_RE = re.compile(r"(?:监管工作函|监管函|关注函|重点监控|停牌核查|问询函|警示函|风险提示)")
REG_BENIGN_EXC = re.compile(r"(?:回复|回函|核查意见|延期的|不涉及)")


def split_terms(s: str) -> set[str]:
    out = set()
    for part in re.split(r"[+、,，/；;]", s or ""):
        part = part.strip()
        if not part:
            continue
        out.add(part)
        for x in re.split(r"[()（）]", part):
            x = x.strip()
            if x:
                out.add(x)
    return {t for t in out if 2 <= len(t) <= 20 and t not in NON_THEME}


def _time_to_sec(tstr: str) -> float | None:
    if not tstr or len(tstr) < 5 or str(tstr).startswith("99"):
        return None
    parts = str(tstr).strip().split(":")
    try:
        hh, mm = int(parts[0]), int(parts[1])
        ss = int(parts[2]) if len(parts) > 2 else 0
        if hh < 9 or (hh == 9 and mm < 30):
            return 0.0
        if hh < 12:
            return float((hh - 9) * 3600 + (mm - 30) * 60 + ss)
        return float(7200 + (hh - 13) * 3600 + mm * 60 + ss)
    except Exception:
        return None


def fetch_tencent_quotes(codes: list[str], batch_size: int = 80, max_workers: int = 16) -> dict[str, dict]:
    if not codes:
        return {}
    clist = sorted(set(str(c).zfill(6) for c in codes))

    def _chunk(ch: list[str]) -> dict[str, dict]:
        ql = [f"{'sh' if c.startswith('6') else 'sz'}{c}" for c in ch]
        req = urllib.request.Request("http://qt.gtimg.cn/q=" + ",".join(ql), headers=UA)
        out = {}
        for _ in range(3):
            try:
                raw = urllib.request.urlopen(req, timeout=3.0).read().decode("gbk", errors="ignore")
                for ln in raw.strip().split(";"):
                    if "~" not in ln:
                        continue
                    p = ln.split("~")
                    if len(p) > 38:
                        c6 = p[2].strip()
                        px = float(p[3] or 0.0)
                        pc = float(p[4] or 0.0)
                        op = float(p[5] or 0.0)
                        hi = float(p[33] or 0.0) or px
                        lo = float(p[34] or 0.0) or px
                        amt = float(p[37] or 0.0) * 10000.0
                        trn = float(p[38] or 0.0) / 100.0
                        b1 = float(p[10] or 0.0) if len(p) > 10 else 0.0
                        s1 = float(p[20] or 0.0) if len(p) > 20 else 0.0
                        dt8 = str(p[30]).strip()[:8] if len(p) > 30 else ""
                        q_dt = f"{dt8[:4]}-{dt8[4:6]}-{dt8[6:8]}" if len(dt8) == 8 and dt8.isdigit() else ""
                        op_px = op if op > 0 else px
                        op_pct = (op_px / pc - 1.0) if pc > 0 else -1.0
                        cur_pct = (px / pc - 1.0) if pc > 0 else 0.0
                        zt_px = float(np.floor(pc * 1.10 * 100.0 + 0.5) / 100.0) if pc > 0 else 999.0
                        is_yz = bool(op_px >= zt_px - 0.005 or (b1 > 0 and s1 == 0 and op_pct >= 0.095))
                        out[c6] = {
                            "code": c6, "name": p[1].strip(), "open": op_px, "close": px,
                            "high": hi, "low": lo, "pre_c": pc, "amount": amt, "turn": trn,
                            "q_dt": q_dt, "open_pct": op_pct, "cur_pct": cur_pct,
                            "zt_px": zt_px, "is_yizi": is_yz,
                            "buyable_open": bool((not is_yz) and (0 < op_px < zt_px - 0.005)),
                        }
                if out:
                    return out
            except Exception:
                pass
        return out

    chunks = [clist[i:i + batch_size] for i in range(0, len(clist), batch_size)]
    res = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for f in as_completed([ex.submit(_chunk, ch) for ch in chunks]):
            res.update(f.result())
    return res


def _get_latest_parquet_date() -> str:
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=20)
    tbl = ds.dataset(A_DAILY, format="parquet").scanner(
        columns=["date"], filter=(ds.field("date") >= cutoff)
    ).to_table()
    dts = [d for d in tbl.column("date").to_pylist() if d is not None]
    return max(dts).strftime("%Y-%m-%d") if dts else ""


def _check_tencent_close_date() -> tuple[str, int]:
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request("http://qt.gtimg.cn/q=sh000300", headers=UA), timeout=2.5
        ).read().decode("gbk", errors="ignore")
        p = raw.split("~")
        dt14 = str(p[30]).strip() if len(p) > 30 else ""
        q_dt = f"{dt14[:4]}-{dt14[4:6]}-{dt14[6:8]}" if len(dt14) >= 8 and dt14[:8].isdigit() else ""
        q_hhmm = int(dt14[8:12]) if len(dt14) >= 12 and dt14[8:12].isdigit() else 0
        return q_dt, q_hhmm
    except Exception:
        return "", 0


def _fetch_ths_limit_up_pool(sig_date: str) -> list:
    ymd = sig_date.replace("-", "")
    url = (
        "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&"
        "field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004&"
        f"filter=HS,GEM2STAR&order_field=330324&order_type=0&date={ymd}"
    )
    try:
        return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=8).read().decode("utf-8")).get("data", {}).get("info", []) or []
    except Exception:
        return []


def _fetch_today_plates_fallback(sig_date: str, ths_info: list | None = None) -> list:
    info = ths_info if ths_info is not None else _fetch_ths_limit_up_pool(sig_date)
    plate_dict = defaultdict(list)
    for item in info:
        c6 = str(item.get("code", "")).strip()[:6]
        nm = str(item.get("name", "")).strip()
        rt = str(item.get("reason_type", "")).strip()
        if not c6 or not nm:
            continue
        parts = [p.strip() for p in re.split(r"[+、,，/]", rt) if p.strip()]
        p0 = parts[0] if parts else "其他"
        if p0 in NON_THEME or "增长" in p0 or "扭亏" in p0:
            p0 = parts[1] if len(parts) > 1 else "其他"
        plate_dict[p0].append([c6, nm, p0, rt])
    return sorted([{"plate": k, "stocks": v} for k, v in plate_dict.items()], key=lambda x: len(x["stocks"]), reverse=True)


def evaluate_2to3_candidate(cand: dict, open_pct: float, buyable_open: bool) -> dict:
    """
    严格对齐 upgrade_2to3_pit.py (V2.0) 的 5 条硬门禁与底分 60 + 18 项纯整数打分。
    同时被 fast_2to3_today.py 与 daily_3strategies_score_report.py 调用，保持老字典缺新键安全向后兼容。
    """
    veto_reasons = []
    hd_tag = str(cand.get("ths_tag") or cand.get("high_days") or "2天2板").strip()
    if hd_tag not in ("2天2板", "2连板"):
        veto_reasons.append(f"跨天反包非纯2连板({hd_tag})")
    if cand.get("prev_is_yizi", False):
        veto_reasons.append("前日二板一字")
    if not buyable_open:
        veto_reasons.append("今日09:25一字/不可买")
    if not (-0.065 <= open_pct <= 0.025):
        veto_reasons.append(f"开盘{open_pct*100:+.2f}%出[-6.5%,+2.5%]")
    if cand.get("has_tox_90d", False):
        veto_reasons.append("近90日毒丸公告")
    if cand.get("has_reg_10d", False):
        veto_reasons.append("近10日监管/风险公告")
    psz = int(cand.get("plate_sz", 0))
    if psz >= 15:
        veto_reasons.append(f"板块涨停{psz}>=15过热")

    b01 = int(cand.get("b01_hhi_low_q25", 0))
    top1_sh = float(cand.get("raw_top1_share", 0.0))
    p12 = float(cand.get("mkt_p12_prev", 0.5))
    p23 = float(cand.get("mkt_p23_prev", 0.5))
    maxb = int(cand.get("mkt_maxb_prev", 9))
    rk_noev = int(cand.get("plate_rk_noev", 99))
    a22 = int(cand.get("a22_elo_ice_lt95", 0))
    s_elo = float(cand.get("d2_s_elo", 100.0))
    p3b = int(cand.get("plate_3b_cnt_sd", 0))
    xq_cnt = int(cand.get("xq_cnt_tot", 0))
    ir20 = int(cand.get("ir_has_20d", 0))
    d2_lp = float(cand.get("d2_low_pct", 0.0))
    d2_sar = cand.get("d2_seal_amt_ratio")
    d2_sec = cand.get("d2_seal_sec")
    d2_ocnt = cand.get("d2_open_cnt_tape")
    pos20 = cand.get("pos_20d_d0")
    d2_rturn = cand.get("d2_real_turn")
    lock10 = cand.get("lock_top10")

    # V2.0 新增 5 项因子安全读取 (向后兼容旧缓存)
    u1_outsider = bool(cand.get("is_pure_outsider_causal", False))
    u2_own_new = bool(cand.get("d2_own_new_term", False))
    u3_dying = bool(cand.get("d1_is_dying_pulse", False))
    u5_d1_yizi = bool(cand.get("d1_is_yizi", False))

    elo_ice = (a22 == 1) or (s_elo <= 95.0)
    mid_warm = (3 <= rk_noev <= 7) or (2 <= psz <= 6)
    hot_crowd = ((rk_noev <= 2) and (psz >= 7)) or (psz >= 12)
    both_low = (p12 < 0.18) and (p23 < 0.28)

    ocnt_i = -1 if d2_ocnt is None else int(d2_ocnt)
    sec_fast = 99999.0 if d2_sec is None else float(d2_sec)
    sec_late = 0.0 if d2_sec is None else float(d2_sec)
    sar_hi = 0.0 if d2_sar is None else float(d2_sar)
    sar_lo = 1.0 if d2_sar is None else float(d2_sar)
    d2_weak_late = (ocnt_i >= 1) and ((sec_late >= 1800.0) or (sar_lo < 0.05))
    d2_fast_zero = (ocnt_i == 0) and (sec_fast <= 300.0)

    pos20_v = 0.5 if pos20 is None else float(pos20)
    rturn_lt15 = 30.0 if d2_rturn is None else float(d2_rturn)
    rturn_v = 0.0 if d2_rturn is None else float(d2_rturn)
    lock_v = 0.0 if lock10 is None else float(lock10)

    p4_4 = (
        -8 if rturn_lt15 < 15.0
        else (8 if (lock_v >= 50.0 and 25.0 <= rturn_v <= 65.0)
              else (5 if (lock_v >= 50.0 and 15.0 <= rturn_v < 25.0) else 0))
    )
    u4_late_bad = -6 if (d2_sec is not None and float(d2_sec) >= 12600.0) else 0
    p5_1 = 5 if open_pct < 0.0 else 0

    pts = [
        6 if b01 == 1 else (-10 if top1_sh >= 0.30 else 0),
        8 if both_low else (5 if p23 < 0.28 else 0),
        6 if maxb <= 3 else 0,
        -10 if hot_crowd else (5 if mid_warm else 0),
        8 if elo_ice else 0,
        -8 if p3b >= 1 else 0,
        0 if xq_cnt == 0 else (-18 if xq_cnt >= 4 else -10),
        -10 if ir20 == 1 else 0,
        6 if d2_lp <= -0.02 else 0,
        -16 if sar_hi >= 0.25 else (-8 if d2_fast_zero else (6 if d2_weak_late else 0)),
        6 if pos20_v <= 0.40 else 0,
        p4_4,
        4 if u1_outsider else 0,
        4 if u2_own_new else 0,
        -8 if u3_dying else 0,
        u4_late_bad,
        -6 if u5_d1_yizi else 0,
        p5_1,
    ]
    labels = [
        "P1_1主线离散", "P1_2晋级分歧", "P1_3高度压制",
        "P2_1板块温热", "P2_2极寒破冰", "P2_4老大哥压制",
        "P3_1雪球暗牌", "P3_2机构调研",
        "P4_1深水洗盘", "P4_2弱封vs秒板", "P4_3低位<=0.4", "P4_4锁仓换手",
        "U1跨界硬科技", "U2细分新词", "U3退潮脉冲", "U4尾盘烂板", "U5首板一字",
        "P5_1绿开承接",
    ]
    raw_score = 60 + sum(pts)
    static_score = 60 + sum(pts[:-1])
    passed_gates = len(veto_reasons) == 0
    passed_std90 = passed_gates and (raw_score >= 90)
    passed_strict96 = passed_gates and (raw_score >= 96)
    bd_parts = [f"{lb}({p:+d})" for lb, p in zip(labels, pts) if p != 0]

    return {
        "score": int(raw_score),
        "static_score": int(static_score),
        "passed_gates": passed_gates,
        "passed_std90": passed_std90,
        "passed_strict96": passed_strict96,
        "veto_reasons": veto_reasons,
        "breakdown_str": " ".join(bd_parts) if bd_parts else "全0项(仅底分60)",
        "components": dict(zip(labels, pts)),
    }


def _load_csrc_ind_map(target_dt: str = "") -> dict:
    ind_map = {}
    if os.path.exists(CSRC_PIT_CSV):
        try:
            df_pit = pd.read_csv(CSRC_PIT_CSV, dtype=str).fillna("")
            col_code = "sec_code" if "sec_code" in df_pit.columns else "code"
            df_pit["c6"] = df_pit[col_code].astype(str).str[-6:].str.zfill(6)
            lookup = defaultdict(list)
            for r in df_pit[["c6", "start_date", "end_date", "industry"]].itertuples(index=False):
                sd_s, ed_s = str(r.start_date)[:10], str(r.end_date)[:10]
                if target_dt and sd_s and sd_s > target_dt:
                    continue
                lookup[r.c6].append((sd_s, ed_s, str(r.industry)))
            for c6_k, ivs in lookup.items():
                ivs.sort(key=lambda x: (x[0], x[1]))
                chosen = ivs[-1][2]
                if target_dt:
                    for s_d, e_d, ind_v in ivs:
                        if s_d <= target_dt <= e_d:
                            chosen = ind_v
                ind_map[c6_k] = chosen
        except Exception as e:
            sys.stderr.write(f"[WARN] 读取 PIT 证监会行业 ({CSRC_PIT_CSV}) 异常: {e}\n")
    if os.path.exists(CSRC_L2_CSV):
        try:
            df_l2 = pd.read_csv(CSRC_L2_CSV, dtype=str).fillna("")
            col_code = "sec_code" if "sec_code" in df_l2.columns else "code"
            df_l2["c6"] = df_l2[col_code].astype(str).str[-6:].str.zfill(6)
            for c6_k, ind_v in zip(df_l2["c6"], df_l2["industry"]):
                if c6_k not in ind_map:
                    ind_map[c6_k] = str(ind_v)
        except Exception as e:
            sys.stderr.write(f"[WARN] 读取证监会行业兜底 ({CSRC_L2_CSV}) 异常: {e}\n")
    return ind_map


def _load_notice_hard_set(cand_d1_pairs: list[tuple[str, str]], buy_date: str, sig_date: str, is_hist: bool = False) -> set[str]:
    hard_set = set()
    if not cand_d1_pairs:
        return hard_set
    codes = sorted(set(c for c, _ in cand_d1_pairs))
    d1_map = dict(cand_d1_pairs)
    d1_min = min(d1 for _, d1 in cand_d1_pairs)
    start_cut = (datetime.date.fromisoformat(d1_min) - datetime.timedelta(days=4)).isoformat()
    end_cut = f"{buy_date} 09:25:00"
    ndate_hi = sig_date if is_hist else buy_date
    ph = ",".join(["?"] * len(codes))

    if os.path.exists(DB_NOTICES):
        con = sqlite3.connect(f"file:{DB_NOTICES}?mode=ro", uri=True)
        try:
            for c_raw, nd, ti in con.execute(
                f"SELECT code, ndate, title FROM notice WHERE ndate >= ? AND ndate <= ? AND code IN ({ph})",
                (start_cut, ndate_hi, *codes),
            ):
                c6 = str(c_raw)[:6].zfill(6)
                d1_s = d1_map.get(c6, d1_min)
                s_c = (datetime.date.fromisoformat(d1_s) - datetime.timedelta(days=4)).isoformat()
                if str(nd)[:10] < s_c:
                    continue
                t = str(ti or "")
                is_neg = bool(NEG_NOTICE_PAT.search(t)) or bool(BAD_NOTICE_PAT.search(t)) or bool(re.search(r"(澄清|辟谣|不涉及|不存在相关)", t))
                if (not is_neg) and HARD_NOTICE_PAT.search(t):
                    hard_set.add(c6)
        finally:
            con.close()

    if os.path.exists(DB_PIT_NOTICES):
        con = sqlite3.connect(f"file:{DB_PIT_NOTICES}?mode=ro", uri=True)
        try:
            for c_raw, pdt, avdt, ti in con.execute(
                f"SELECT sec_code, pub_datetime_cst, trade_date_avail, title FROM notices WHERE pub_datetime_cst >= ? AND pub_datetime_cst < ? AND sec_code IN ({ph})",
                (start_cut, end_cut, *codes),
            ):
                c6 = str(c_raw)[:6].zfill(6)
                d1_s = d1_map.get(c6, d1_min)
                s_c = (datetime.date.fromisoformat(d1_s) - datetime.timedelta(days=4)).isoformat()
                if str(pdt) < s_c:
                    continue
                if avdt and str(avdt) > buy_date:
                    continue
                t = str(ti or "")
                is_neg = bool(NEG_NOTICE_PAT.search(t)) or bool(BAD_NOTICE_PAT.search(t)) or bool(re.search(r"(澄清|辟谣|不涉及|不存在相关)", t))
                if (not is_neg) and HARD_NOTICE_PAT.search(t):
                    hard_set.add(c6)
        finally:
            con.close()
    return hard_set


def _load_holders_map() -> dict:
    p_all = json.load(open(HOLDERS_ALL, encoding="utf-8")) if os.path.exists(HOLDERS_ALL) else {}
    p_free = json.load(open(HOLDERS_FREE, encoding="utf-8")) if os.path.exists(HOLDERS_FREE) else {}
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


def _load_reg_tox_maps(codes: list[str], sig_date: str, buy_date: str) -> tuple[set, set]:
    cset = set(codes)
    sig_ts = pd.Timestamp(buy_date)
    d90 = (sig_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    d10 = (sig_ts - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    cutoff = f"{buy_date} 09:25:00"
    tox_set, reg_set = set(), set()

    if os.path.exists(REG_TOX_PQ):
        rt = pd.read_parquet(REG_TOX_PQ, columns=["sec_code", "pub_datetime_cst"])
        rt["c6"] = rt["sec_code"].astype(str).str[:6].str.zfill(6)
        rt = rt[rt["c6"].isin(cset)]
        for c6, pdt in zip(rt["c6"], rt["pub_datetime_cst"].astype(str)):
            if d90 <= pdt[:10] and pdt < cutoff and pdt[:10] < buy_date:
                tox_set.add(c6)
            if d10 <= pdt[:10] and pdt <= cutoff:
                reg_set.add(c6)

    if cset:
        ph = ",".join(["?"] * len(cset))
        clist = sorted(cset)
        if os.path.exists(DB_NOTICES):
            con = sqlite3.connect(f"file:{DB_NOTICES}?mode=ro", uri=True)
            try:
                for c_raw, nd, ti in con.execute(
                    f"SELECT code, ndate, title FROM notice WHERE ndate >= ? AND ndate <= ? AND code IN ({ph})",
                    (d90, buy_date, *clist),
                ):
                    c6, t = str(c_raw)[:6].zfill(6), str(ti or "")
                    if REG_BENIGN_EXC.search(t):
                        continue
                    if TOX_RE.search(t) and nd < buy_date:
                        tox_set.add(c6)
                    if nd >= d10 and REG_RE.search(t):
                        reg_set.add(c6)
            finally:
                con.close()
        if os.path.exists(DB_PIT_NOTICES):
            con = sqlite3.connect(f"file:{DB_PIT_NOTICES}?mode=ro", uri=True)
            try:
                for c_raw, pdt, ti in con.execute(
                    f"SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst >= ? AND pub_datetime_cst <= ? AND sec_code IN ({ph})",
                    (d90, cutoff, *clist),
                ):
                    c6, t, pd_s = str(c_raw)[:6].zfill(6), str(ti or ""), str(pdt)
                    if REG_BENIGN_EXC.search(t):
                        continue
                    if TOX_RE.search(t) and pd_s[:10] < buy_date:
                        tox_set.add(c6)
                    if pd_s[:10] >= d10 and REG_RE.search(t):
                        reg_set.add(c6)
            finally:
                con.close()
    return tox_set, reg_set


def _load_xq_ir_counts(cand_info: list[tuple[str, str]], buy_date: str) -> tuple[dict[str, int], set[str], str]:
    xq_cnt = defaultdict(int)
    ir_set = set()
    if not cand_info:
        return xq_cnt, ir_set, ""

    codes = sorted(set(c for c, _ in cand_info))
    d1_min = min(d1 for _, d1 in cand_info)
    d1_map = dict(cand_info)
    cutoff = f"{buy_date} 09:25:00"
    ph = ",".join(["?"] * len(codes))
    seen_pids = defaultdict(set)
    xq_max_dt = ""

    if os.path.exists(DB_XQ_GB):
        con = sqlite3.connect(f"file:{DB_XQ_GB}?mode=ro", uri=True)
        try:
            xq_max_dt = str(con.execute("SELECT max(created_time_str) FROM xueqiu_posts").fetchone()[0] or "")[:10]
            for sym, pid, ts in con.execute(
                f"SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE symbol IN ({ph}) AND created_time_str >= ? AND created_time_str < ?",
                (*codes, f"{d1_min} 00:00:00", cutoff),
            ):
                c6 = str(sym)[:6].zfill(6)
                if str(ts) >= f"{d1_map[c6]} 00:00:00":
                    seen_pids[c6].add(str(pid).replace("xq_", ""))
        finally:
            con.close()

    if os.path.exists(DB_COMM):
        con = sqlite3.connect(f"file:{DB_COMM}?mode=ro", uri=True)
        try:
            for sym, pid, ts in con.execute(
                f"SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND symbol IN ({ph}) AND pub_datetime_cst >= ? AND pub_datetime_cst < ?",
                (*codes, f"{d1_min} 00:00:00", cutoff),
            ):
                c6 = str(sym)[:6].zfill(6)
                if str(ts) >= f"{d1_map[c6]} 00:00:00":
                    seen_pids[c6].add(str(pid).replace("xq_", ""))
        finally:
            con.close()

    for c6, pset in seen_pids.items():
        xq_cnt[c6] = len(pset)

    ir_start = (datetime.date.fromisoformat(buy_date) - datetime.timedelta(days=20)).isoformat()
    for p_ir in (DB_IR_QA, DB_IR_QA_ALT):
        if os.path.exists(p_ir):
            con = sqlite3.connect(f"file:{p_ir}?mode=ro", uri=True)
            try:
                for (sc,) in con.execute(
                    f"SELECT DISTINCT sec_code FROM ir_qa WHERE sec_code IN ({ph}) AND trade_date_avail <= ? AND pub_datetime_cst < ? AND substr(pub_datetime_cst,1,10) >= ?",
                    (*codes, buy_date, cutoff, ir_start),
                ):
                    ir_set.add(str(sc)[:6].zfill(6))
            finally:
                con.close()
            break

    if os.path.exists(DB_PIT_NOTICES):
        con = sqlite3.connect(f"file:{DB_PIT_NOTICES}?mode=ro", uri=True)
        try:
            for (sc,) in con.execute(
                f"SELECT DISTINCT sec_code FROM notices WHERE sec_code IN ({ph}) AND pub_datetime_cst >= ? AND pub_datetime_cst < ? AND title LIKE '%活动记录%'",
                (*codes, ir_start, cutoff),
            ):
                ir_set.add(str(sc)[:6].zfill(6))
        finally:
            con.close()

    return xq_cnt, ir_set, xq_max_dt


def build_premarket_cache(verbose: bool = True, as_of_date: str = "") -> dict:
    t0 = time.time()
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "turn", "oshare"]
    d1 = ds.dataset(A_DAILY, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2018-01-01"))
    ).to_table().to_pandas()
    d2 = ds.dataset(A_DELISTED, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2018-01-01"))
    ).to_table().to_pandas()
    df = pd.concat([d1, d2], ignore_index=True)
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60")) & (~df["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df["dt"] = df["date"].dt.strftime("%Y-%m-%d")
    if as_of_date:
        df = df[df["dt"] <= as_of_date].copy()
    df.sort_values(["c6", "dt"], inplace=True)
    df.drop_duplicates(subset=["c6", "dt"], keep="first", inplace=True)

    max_p_date = df["dt"].max()
    patched_today = False
    if not as_of_date:
        now = datetime.datetime.now()
        q_dt, q_hhmm = _check_tencent_close_date()
        if q_dt > max_p_date and q_hhmm >= 1500:
            last_sub = df[df["dt"] == max_p_date]
            c_list = last_sub["c6"].tolist()
            tk_map = dict(zip(last_sub["c6"], last_sub["ticker"]))
            osh_map = dict(zip(last_sub["c6"], last_sub["oshare"]))
            live_q = fetch_tencent_quotes(c_list, batch_size=80, max_workers=24)
            patch_rows = []
            for c in c_list:
                q = live_q.get(c)
                if q and q.get("q_dt") == q_dt and q.get("close", 0) > 0:
                    osh = float(osh_map.get(c, 0.0) or 0.0)
                    px = float(q["close"])
                    turn_v = float(q["turn"]) if q.get("turn", 0) > 0 else ((q["amount"] / (px * osh)) if osh > 0 else 0.0)
                    patch_rows.append({
                        "date": pd.Timestamp(q_dt), "ticker": tk_map[c],
                        "open": q["open"], "high": q["high"], "low": q["low"], "close": px,
                        "adj_close": px, "amount": q["amount"], "turn": turn_v, "oshare": osh,
                        "c6": c, "dt": q_dt,
                    })
            if len(patch_rows) >= 2000:
                df = pd.concat([df, pd.DataFrame(patch_rows)], ignore_index=True)
                df.drop_duplicates(subset=["c6", "dt"], keep="last", inplace=True)
                patched_today = True
        elif now.weekday() < 5 and (now.hour > 15 or (now.hour == 15 and now.minute >= 5)) and q_dt > max_p_date and q_hhmm < 1500:
            pass

    df.sort_values(["c6", "dt"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    df["adjf"] = np.where(df["close"] > 0, df["adj_close"] / df["close"], 1.0)
    g = df.groupby("c6")
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["l_pct"] = df["low"] / df["pre_c"] - 1.0
    df["zt_10"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["is_zt10"] = (df["pre_c"] > 0) & (df["close"] >= df["zt_10"] - 0.01) & (df["pct"] >= 0.095)
    df["touch_zt10"] = (df["pre_c"] > 0) & (df["high"] >= df["zt_10"] - 0.01)
    df["is_yizi10"] = df["is_zt10"] & (df["open"] >= df["zt_10"] - 0.01) & (df["low"] >= df["zt_10"] - 0.01)

    stks = np.zeros(len(df), dtype=int)
    cur_c, cur_s = "", 0
    for i, (c, z) in enumerate(zip(df["c6"].values, df["is_zt10"].values)):
        if c != cur_c:
            cur_c, cur_s = c, 0
        cur_s = cur_s + 1 if z else 0
        stks[i] = cur_s
    df["streak"] = stks
    df["prev_streak"] = df.groupby("c6")["streak"].shift(1).fillna(0).astype(int)

    all_dts = sorted(df["dt"].unique())
    sig_date = all_dts[-1]
    sig_ts = pd.Timestamp(sig_date)
    nxt_buy_date = (sig_ts + pd.Timedelta(days=(3 if sig_ts.weekday() == 4 else 1))).strftime("%Y-%m-%d")

    st_2026 = set(json.load(open(ST_UNIVERSE))["codes"]) if os.path.exists(ST_UNIVERSE) else set()
    ths_path = f"{THS_DIR}/{sig_date}.json"
    if os.path.exists(ths_path):
        ths_stocks = json.load(open(ths_path, encoding="utf-8")).get("stocks", [])
    else:
        ths_stocks = _fetch_ths_limit_up_pool(sig_date) if not as_of_date else []
    ths_map = {str(s.get("code", ""))[:6].zfill(6): s for s in ths_stocks}

    tape_map = {}
    if os.path.exists(DB_ZT_TAPE):
        con = sqlite3.connect(f"file:{DB_ZT_TAPE}?mode=ro", uri=True)
        try:
            for r in con.execute(
                "SELECT sec_code, sec_name, first_seal_time, seal_amount, continuous_plate_tag, open_board_count, plate_name "
                "FROM zt_micro_tape WHERE trade_date = ?", (sig_date,)
            ):
                tape_map[str(r[0])[:6].zfill(6)] = {
                    "sec_name": str(r[1] or ""), "first_seal_time": str(r[2] or ""),
                    "seal_amount": float(r[3] or 0.0), "tag": str(r[4] or ""),
                    "open_board_count": int(r[5] if r[5] is not None else -1), "plate_name": str(r[6] or ""),
                }
        finally:
            con.close()

    # KPL 8年动态题材与 HHI / Elo / 新词破冰 / 退潮脉冲计算
    kpl_by_dt = {}
    if os.path.exists(KPL_MERGED):
        with open(KPL_MERGED, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    d = json.loads(ln)
                    dt_k = d.get("date", "")
                    if dt_k and dt_k <= sig_date and sum(len(p.get("stocks", [])) for p in d.get("plates", [])) > 0:
                        kpl_by_dt[dt_k] = d.get("plates", [])
    if os.path.exists(KPL_V2):
        with open(KPL_V2, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    d = json.loads(ln)
                    dt_k = d.get("date", "")
                    pls = d.get("plates", [])
                    if dt_k and dt_k <= sig_date and sum(len(p.get("stocks", [])) for p in pls) > 0:
                        if dt_k not in kpl_by_dt or len(pls) >= len(kpl_by_dt[dt_k]):
                            kpl_by_dt[dt_k] = pls
    if sig_date not in kpl_by_dt:
        if not as_of_date:
            raise RuntimeError(f"[工程真源硬锁] 今日 {sig_date} 开盘啦官方涨停题材尚未落地入库，拒绝用非标临时数据写入 2to3_premarket_cache.json！")
        fb_pls = _fetch_today_plates_fallback(sig_date, ths_info=ths_stocks if ths_stocks else None)
        if fb_pls:
            kpl_by_dt[sig_date] = fb_pls

    kpl_dates = sorted(kpl_by_dt.keys())
    kpl_dt_set = set(kpl_dates)
    sub_stat = df[df["dt"].isin(kpl_dt_set)][["dt", "c6", "pct", "is_zt10", "touch_zt10", "streak"]]
    stat_map = {
        (r.dt, r.c6): (float(r.pct), bool(r.is_zt10), bool(r.touch_zt10), int(r.streak) >= 2)
        for r in sub_stat.itertuples(index=False) if pd.notna(r.pct)
    }

    elo = defaultdict(lambda: 100.0)
    sub_elo = defaultdict(lambda: 100.0)
    plate_last_idx, sub_last_idx = {}, {}
    prev_p, prev_sub = {}, {}
    plate_sz_by_idx = defaultdict(dict)
    plate_recent_zts = defaultdict(list)
    hist_hhi = []
    term_seen = Counter()
    term_first = {}
    b01_hhi_low_q25 = 0
    sig_plate_metrics = {}
    sig_stk_plates = defaultdict(list)
    sig_stk_s2 = {}
    sig_stk_ma = {}
    sig_st_codes = set(st_2026)
    sig_all_plate_stocks = {}
    sig_top1_sz = 0
    sig_plate_rk_noev = {}
    rec_own, rec_dying = {}, {}
    dying_track_start_idx = max(0, len(kpl_dates) - 30)

    for idx, dt in enumerate(kpl_dates):
        cut15 = (datetime.date.fromisoformat(dt) - datetime.timedelta(days=15)).isoformat()
        plates = kpl_by_dt[dt]
        for pname, c6_list in prev_p.items():
            touches = seals = 0
            rets = []
            for c6 in c6_list:
                st = stat_map.get((dt, c6))
                if st is not None:
                    rets.append(st[0]); seals += int(st[1]); touches += int(st[2])
            if touches >= 2 and (seals / touches) < 0.50:
                elo[pname] -= 12.0 * ((touches - seals) / touches)
            elif rets and float(np.mean(rets)) < -0.025:
                elo[pname] -= 10.0
            elif seals >= 2 and (seals / max(touches, 1)) >= 0.70:
                elo[pname] += min(10.0, 5.0 + seals * 1.2)
            elif rets and float(np.mean(rets)) > 0.025:
                elo[pname] += 6.0
        for sname, c6_list in prev_sub.items():
            touches = seals = 0
            rets = []
            for c6 in c6_list:
                st = stat_map.get((dt, c6))
                if st is not None:
                    rets.append(st[0]); seals += int(st[1]); touches += int(st[2])
            if touches >= 2 and (seals / touches) < 0.50:
                sub_elo[sname] -= 10.0 * ((touches - seals) / touches)
            elif rets and float(np.mean(rets)) < -0.025:
                sub_elo[sname] -= 8.0
            elif seals >= 1 and (seals / max(touches, 1)) >= 0.70:
                sub_elo[sname] += min(9.0, 4.0 + seals * 1.5)
            elif rets and float(np.mean(rets)) > 0.025:
                sub_elo[sname] += 5.0
        for pk in list(elo.keys()):
            if idx - plate_last_idx.get(pk, idx) > 3:
                elo[pk] = 100.0 + (elo[pk] - 100.0) * 0.85
        for sk in list(sub_elo.keys()):
            if idx - sub_last_idx.get(sk, idx) > 3:
                sub_elo[sk] = 100.0 + (sub_elo[sk] - 100.0) * 0.85

        new_prev_p, new_prev_sub = {}, defaultdict(list)
        sz_all, cur_day_sz, noev_list = [], {}, []
        day_terms = set()
        for p in plates:
            pname = p.get("plate", "")
            stks_p = p.get("stocks", [])
            sz = len(stks_p)
            if dt == sig_date:
                for s in stks_p:
                    c6 = str(s[0]).strip()[:6].zfill(6)
                    nm = str(s[1]) if len(s) > 1 else ""
                    if "ST" in nm.upper() or pname == "ST板块":
                        sig_st_codes.add(c6)
            if sz == 0 or pname in NON_THEME:
                continue
            cur_day_sz[pname] = sz
            sz_all.append(sz)
            if pname not in EVENT_BASKET:
                noev_list.append((pname, sz))
            plate_sz_by_idx[pname][idx] = sz
            plate_last_idx[pname] = idx
            c6_l = []
            n2 = 0
            for s in stks_p:
                c6 = str(s[0]).strip()[:6].zfill(6)
                c6_l.append(c6)
                st_i = stat_map.get((dt, c6))
                if st_i is not None and st_i[3]:
                    n2 += 1
                s2 = str(s[2]).strip() if len(s) > 2 else ""
                r_lg = str(s[3]).strip() if len(s) > 3 else ""
                if s2 and s2 not in NON_THEME and s2 != "无":
                    new_prev_sub[s2].append(c6)
                    sub_last_idx[s2] = idx
                    if dt == sig_date and c6 not in sig_stk_s2:
                        sig_stk_s2[c6] = s2
                for t in (split_terms(pname) | split_terms(s2)):
                    day_terms.add(t)
                if dt == sig_date:
                    sig_stk_plates[c6].append((pname, sz))
                    sig_stk_ma[(c6, pname)] = bool(MA_PAT.search(f"{pname} {s2} {r_lg}"))
                    if (dt, c6) not in rec_own:
                        rec_own[(dt, c6)] = any(
                            (term_seen[t] == 0 or term_first.get(t, dt) >= cut15)
                            for t in split_terms(s2 + "+" + r_lg)
                        )
            dyp = bool(any(z >= 5 for pi, z in plate_recent_zts[pname] if (idx - 8 <= pi <= idx - 3)) and n2 == 0)
            plate_recent_zts[pname].append((idx, sz))
            if idx >= dying_track_start_idx:
                for c6_d in c6_l:
                    if (dt, c6_d) not in rec_dying:
                        rec_dying[(dt, c6_d)] = dyp
            new_prev_p[pname] = c6_l
            if dt == sig_date:
                sig_all_plate_stocks[pname] = c6_l

        tot_s = sum(sz_all)
        hhi_all = sum((x / tot_s) ** 2 for x in sz_all) if tot_s > 0 else 1.0
        if dt >= "2019-12-01":
            win = hist_hhi[-250:]
            hhi_pct = float(np.mean([1.0 if x <= hhi_all else 0.0 for x in win])) if len(win) >= 20 else 0.5
            hist_hhi.append(hhi_all)
            if dt == sig_date:
                b01_hhi_low_q25 = int(hhi_pct <= 0.25)

        if dt == sig_date:
            noev_list.sort(key=lambda x: x[1], reverse=True)
            sig_top1_sz = noev_list[0][1] if noev_list else 0
            sig_plate_rk_noev = {pn: i + 1 for i, (pn, _) in enumerate(noev_list)}
            for pname, sz0 in cur_day_sz.items():
                pdict = plate_sz_by_idx[pname]
                arr65 = np.array([pdict.get(idx - 64 + k, 0) for k in range(65)], dtype=int)
                max_far_20 = int(arr65[65 - 20:65 - 2].max())
                run_ge2 = 0
                for v in arr65[::-1]:
                    if v >= 2:
                        run_ge2 += 1
                    else:
                        break
                pre_end = 65 - run_ge2
                pre_max = int(arr65[max(0, pre_end - 20):pre_end].max()) if pre_end > 0 else 0
                w1_day = run_ge2 if (run_ge2 >= 1 and pre_max < 6) else 0

                def _has_w2(win_d: int) -> bool:
                    if sz0 < 4:
                        return False
                    sub_a = arr65[65 - win_d:64]
                    for k in range(len(sub_a) - 2):
                        if sub_a[k] >= 6 and (sub_a[k + 1:] <= 3).sum() >= 2:
                            return True
                    return False

                sig_plate_metrics[pname] = {
                    "elo": float(elo[pname]),
                    "w1_day1_3": int(1 <= w1_day <= 3),
                    "w1_fresh20": int(sz0 >= 3 and max_far_20 < 4),
                    "w2_20": int(_has_w2(20)),
                    "w2_30": int(_has_w2(30)),
                }
            for c6_k, s2_nm in list(sig_stk_s2.items()):
                sig_stk_s2[c6_k] = (s2_nm, float(sub_elo[s2_nm]))

        for t in day_terms:
            term_seen[t] += 1
            if t not in term_first:
                term_first[t] = dt
        prev_p, prev_sub = new_prev_p, new_prev_sub

    for c6_t, rec_t in tape_map.items():
        if "ST" in rec_t["sec_name"].upper() or rec_t["plate_name"] == "ST板块":
            sig_st_codes.add(c6_t)
    for c6_t, rec_t in ths_map.items():
        if "ST" in str(rec_t.get("name", "")).upper():
            sig_st_codes.add(c6_t)

    df_sig = df[df["dt"] == sig_date].copy()
    sig_clean = df_sig[~df_sig["c6"].isin(sig_st_codes)]
    sig_stk_map = dict(zip(sig_clean["c6"], sig_clean["streak"]))
    mkt_zt_prev = int(sig_clean["is_zt10"].sum())
    s1 = sig_clean[sig_clean["prev_streak"] == 1]
    s2 = sig_clean[sig_clean["prev_streak"] == 2]
    mkt_p12_prev = float(s1["is_zt10"].mean()) if len(s1) else 0.0
    mkt_p23_prev = float(s2["is_zt10"].mean()) if len(s2) else 0.0
    mkt_maxb_prev = int(sig_clean["streak"].max()) if len(sig_clean) else 0
    raw_top1_share = sig_top1_sz / max(mkt_zt_prev, 1)

    cands_df = sig_clean[sig_clean["streak"] == 2].sort_values("c6").reset_index(drop=True)
    cand_codes = cands_df["c6"].tolist()
    holders_map = _load_holders_map()
    tox_set, reg_set = _load_reg_tox_maps(cand_codes, sig_date, nxt_buy_date)

    # Firstboard 5m fallback events (D1/D2)
    fb_ev = {}
    if os.path.exists(DB_FB_5M) and cand_codes:
        con_fb = sqlite3.connect(f"file:{DB_FB_5M}?mode=ro", uri=True)
        try:
            ph = ",".join(["?"] * len(cand_codes))
            for td, sc, fst, sa, obc in con_fb.execute(
                f"SELECT trade_date, sec_code, first_seal_time, seal_amount, open_board_count FROM firstboard_events WHERE trade_date = ? AND sec_code IN ({ph})",
                (sig_date, *cand_codes),
            ):
                fb_ev[str(sc)[:6].zfill(6)] = (str(fst or ""), float(sa or 0.0), int(obc if obc is not None else -1))
        finally:
            con_fb.close()

    cand_d1_pairs = []
    stock_bars = {c: g_c.reset_index(drop=True) for c, g_c in df[df["c6"].isin(cand_codes)].groupby("c6")}
    for c6 in cand_codes:
        sb = stock_bars[c6]
        d1_dt = str(sb.iloc[-2]["dt"]) if len(sb) >= 2 else sig_date
        cand_d1_pairs.append((c6, d1_dt))

    xq_cnt_map, ir_set, xq_max_dt = _load_xq_ir_counts(cand_d1_pairs, nxt_buy_date)
    notice_hard_set = _load_notice_hard_set(cand_d1_pairs, nxt_buy_date, sig_date, is_hist=bool(as_of_date))
    csrc_map = _load_csrc_ind_map(target_dt=sig_date)

    candidates = []
    for r in cands_df.itertuples(index=False):
        c6 = r.c6
        sb = stock_bars[c6]
        i2 = len(sb) - 1
        i1 = i2 - 1
        i0 = i1 - 1
        d1_dt = str(sb.iloc[i1]["dt"]) if i1 >= 0 else sig_date
        d1_is_yizi = bool(sb.iloc[i1]["is_yizi10"]) if i1 >= 0 else False

        pos_20d_d0 = None
        if i1 >= 5:
            lo = max(0, i1 - 20)
            adj_h = sb["high"].iloc[lo:i1] * sb["adjf"].iloc[lo:i1]
            adj_l = sb["low"].iloc[lo:i1] * sb["adjf"].iloc[lo:i1]
            adj_c0 = float(sb["adj_close"].iloc[i0]) if i0 >= 0 else float(sb["close"].iloc[i1])
            hi_v, lo_v = float(adj_h.max()), float(adj_l.min())
            pos_20d_d0 = float((adj_c0 - lo_v) / (hi_v - lo_v)) if hi_v > lo_v else 0.5

        pls = sig_stk_plates.get(c6, [])
        tp_rec = tape_map.get(c6, {})
        ths_rec = ths_map.get(c6, {})
        if pls:
            pls_sorted = sorted(pls, key=lambda x: (-x[1], sig_plate_rk_noev.get(x[0], 99)))
            best_plate, best_psz = pls_sorted[0]
            plate_rk_noev = sig_plate_rk_noev.get(best_plate, 99)
        else:
            raw_tp = str(tp_rec.get("plate_name", "") or "其他").split("(")[0]
            best_plate = raw_tp if raw_tp else "其他"
            best_psz = len(sig_all_plate_stocks.get(best_plate, [])) if best_plate != "其他" else 0
            plate_rk_noev = sig_plate_rk_noev.get(best_plate, 99)

        pm = sig_plate_metrics.get(best_plate)
        a22 = int(pm["elo"] < 95.0) if pm else 0
        s2_tup = sig_stk_s2.get(c6)
        d2_s_elo = float(s2_tup[1]) if isinstance(s2_tup, tuple) else (float(pm["elo"]) if pm else 100.0)
        p_stks = sig_all_plate_stocks.get(best_plate, [])
        plate_3b_cnt = sum(1 for sc in p_stks if sig_stk_map.get(sc, 1) >= 3) if best_plate not in ("其他", "") else 0

        # D2 tape: zt_micro_tape -> ths_limit_up_daily -> firstboard_events
        d2_fs = tp_rec.get("first_seal_time", "")
        d2_sa = float(tp_rec.get("seal_amount", 0.0) or 0.0)
        d2_oc = int(tp_rec.get("open_board_count", -1)) if tp_rec else -1
        if not d2_fs and ths_rec:
            fts = ths_rec.get("first_limit_up_time")
            d2_fs = datetime.datetime.fromtimestamp(int(fts)).strftime("%H:%M:%S") if fts else ""
            d2_sa = d2_sa or float(ths_rec.get("order_amount") or 0.0)
            if d2_oc < 0 and ths_rec.get("open_num") is not None:
                d2_oc = int(ths_rec["open_num"])
        if not d2_fs and c6 in fb_ev:
            d2_fs, d2_sa_fb, d2_oc_fb = fb_ev[c6]
            d2_sa = d2_sa or d2_sa_fb
            if d2_oc < 0:
                d2_oc = d2_oc_fb

        d2_sec = _time_to_sec(d2_fs)
        d2_amt = float(r.amount or 0.0)
        d2_sar = round(d2_sa / d2_amt, 6) if (d2_sa > 0 and d2_amt > 0) else None

        recs = holders_map.get(c6, [])
        valid_h = [x for x in recs if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= sig_date]
        lock_t10 = float(max(valid_h, key=lambda x: (str(x[1]), str(x[0])))[2]) if valid_h else None
        d2_real_turn = round(float(r.turn) * 100.0 / (1.0 - lock_t10 / 100.0), 4) if (lock_t10 is not None and lock_t10 < 98.0 and pd.notna(r.turn)) else None

        nm = str(ths_rec.get("name") or tp_rec.get("sec_name") or c6)
        ths_tag = str(ths_rec.get("high_days") or tp_rec.get("tag") or "2连板")

        # V2.0 U1..U5 特征
        csrc_ind = str(csrc_map.get(c6, ""))
        csrc_sec = csrc_ind[:3] if csrc_ind else "UNK"
        d2_is_ma = sig_stk_ma.get(
            (c6, best_plate),
            bool(MA_PAT.search(f"{best_plate} {ths_rec.get('reason_type', '')}")),
        )
        notice_hard = c6 in notice_hard_set
        is_pure_outsider_causal = bool(
            HARD_TECH_RE.search(str(best_plate))
            and (csrc_sec in CSRC_PURE_OUTSIDER)
            and (not (notice_hard or d2_is_ma))
        )
        d2_own_new_term = bool(rec_own.get((sig_date, c6), False))
        d1_is_dying_pulse = bool(rec_dying.get((d1_dt, c6), False))

        cand_obj = {
            "code": c6, "name": nm, "ths_tag": ths_tag,
            "sig_date": sig_date, "d1_date": d1_dt, "buy_date": nxt_buy_date,
            "prev_close": round(float(r.close), 2),
            "prev_is_yizi": bool(r.is_yizi10),
            "has_tox_90d": c6 in tox_set,
            "has_reg_10d": c6 in reg_set,
            "plate": best_plate,
            "plate_sz": int(best_psz),
            "plate_rk_noev": int(plate_rk_noev),
            "b01_hhi_low_q25": int(b01_hhi_low_q25),
            "raw_top1_share": round(float(raw_top1_share), 6),
            "mkt_p12_prev": round(float(mkt_p12_prev), 6),
            "mkt_p23_prev": round(float(mkt_p23_prev), 6),
            "mkt_maxb_prev": int(mkt_maxb_prev),
            "a22_elo_ice_lt95": a22,
            "d2_s_elo": round(d2_s_elo, 4),
            "c15_w1_day1_3": int(pm["w1_day1_3"]) if pm else 0,
            "c02_w1_fresh_20d_lt4_ge3": int(pm["w1_fresh20"]) if pm else 0,
            "c21_w2_reb_20d_ge6": int(pm["w2_20"]) if pm else 0,
            "c22_w2_reb_30d_ge6": int(pm["w2_30"]) if pm else 0,
            "plate_3b_cnt_sd": int(plate_3b_cnt),
            "xq_cnt_tot": int(xq_cnt_map.get(c6, 0)),
            "ir_has_20d": int(c6 in ir_set),
            "d2_low_pct": round(float(r.l_pct), 6) if pd.notna(r.l_pct) else 0.0,
            "d2_seal_amt_ratio": d2_sar,
            "d2_seal_sec": d2_sec,
            "d2_open_cnt_tape": d2_oc if d2_oc >= 0 else None,
            "pos_20d_d0": round(pos_20d_d0, 6) if pos_20d_d0 is not None else None,
            "d2_real_turn": d2_real_turn,
            "lock_top10": round(lock_t10, 2) if lock_t10 is not None else None,
            "csrc_ind": csrc_ind,
            "notice_hard": notice_hard,
            "d2_is_ma": d2_is_ma,
            "is_pure_outsider_causal": is_pure_outsider_causal,
            "d2_own_new_term": d2_own_new_term,
            "d1_is_dying_pulse": d1_is_dying_pulse,
            "d1_is_yizi": d1_is_yizi,
        }
        ev_green = evaluate_2to3_candidate(cand_obj, -0.01, True)
        ev_flat = evaluate_2to3_candidate(cand_obj, 0.01, True)
        cand_obj["static_score"] = ev_flat["static_score"]
        cand_obj["pre_score_green"] = ev_green["score"]
        cand_obj["pre_score_flat"] = ev_flat["score"]
        candidates.append(cand_obj)

    candidates.sort(key=lambda x: (-x["pre_score_green"], x["plate_sz"], x["code"]))
    cache = {
        "version": "2TO3_V20_PROD_20261117",
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_as_of_date": sig_date,
        "sig_date": sig_date,
        "buy_date": nxt_buy_date,
        "patched_today": patched_today,
        "xq_db_max_date": xq_max_dt,
        "env": {
            "mkt_zt_prev": mkt_zt_prev,
            "mkt_p12_prev": round(mkt_p12_prev, 4),
            "mkt_p23_prev": round(mkt_p23_prev, 4),
            "mkt_maxb_prev": mkt_maxb_prev,
            "b01_hhi_low_q25": b01_hhi_low_q25,
            "raw_top1_share": round(raw_top1_share, 4),
        },
        "candidates": candidates,
    }
    if not as_of_date:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = CACHE_FILE + ".tmp"
        json.dump(cache, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.replace(tmp, CACHE_FILE)
    if verbose:
        print(f"[+] 二进三 V2.0 盘前缓存已生成 (data_as_of_date={sig_date}, 耗时{time.time()-t0:.2f}s): {len(candidates)} 只二板候选")
    return cache


def assert_data_as_of_date(cache: dict) -> None:
    c_dt = cache.get("data_as_of_date") or cache.get("sig_date") or ""
    assert c_dt, "[ASSERT FAIL] 缓存缺失 data_as_of_date"
    p_max = _get_latest_parquet_date()
    now = datetime.datetime.now()
    q_dt, q_hhmm = _check_tencent_close_date()
    expected_dt = q_dt if (now.weekday() < 5 and q_dt > p_max and q_hhmm >= 1500) else p_max
    assert c_dt == expected_dt, f"[ASSERT FAIL] data_as_of_date ({c_dt}) != 最新收盘日 ({expected_dt})，请先跑 --build-cache"


def print_premarket(cache: dict, strict_only: bool = False) -> None:
    env = cache.get("env", {})
    cands = cache.get("candidates", [])
    tier_note = "仅高严>=96档" if strict_only else "标准>=90 / 高严>=96"
    print("=" * 92)
    print(f"【二进三 V2.1 (V2.0买点+6.5%护利) · 盘前预案 (s_2to3, 底分60, 第4顺位, {tier_note})】")
    print(f"基准收盘日: {cache.get('data_as_of_date')} -> 竞价日: {cache.get('buy_date')} | 涨停={env.get('mkt_zt_prev')}家 | "
          f"1进2={env.get('mkt_p12_prev',0)*100:.1f}% | 2进3={env.get('mkt_p23_prev',0)*100:.1f}% | 最高={env.get('mkt_maxb_prev')}板 | HHI低位={env.get('b01_hhi_low_q25')}")
    print("=" * 92)
    if not cands:
        print("  今日全市场无 10cm 非ST 二连板候选。")
    else:
        for i, c in enumerate(cands, 1):
            ev = evaluate_2to3_candidate(c, -0.01, True)
            pre_veto = [v for v in ev["veto_reasons"] if "开盘" not in v and "09:25" not in v]
            tag_s = "⛔硬否决:" + "；".join(pre_veto) if pre_veto else (
                "★可冲96+" if c["pre_score_green"] >= 96 else ("✅绿开可过90" if (not strict_only and c["pre_score_green"] >= 90) else "观察(<96)" if strict_only else "观察(<90)")
            )
            print(f"  {i:02d}|{c['code']} {c['name']:<6s}({c['ths_tag']})|{c['plate'][:8]}(sz={c['plate_sz']},rk={c['plate_rk_noev']})|"
                  f"底分{c['static_score']}|绿开{c['pre_score_green']}分/红开{c['pre_score_flat']}分|{tag_s}")
            print(f"     细目: {ev['breakdown_str']}")

    print("\n【二进三 V2.1 现行定版离场铁律】")
    print("  1. 买入日未封三板：取消次日 <+0.5% 竞价割地板，统一持有过早盘抛压至次日 14:55/15:00 清仓；若次日反包封死四板则无缝切入连板骑乘链！")
    print("  2. 买入日封死三板/反包连板期：若次日极高开 >+9.2% 且非一字板，09:25 竞价直接止盈兑现；否则走 13:45 后摸 +8.5% 回落破 +6.5% 护利与 1 次真阳免死。")


def run_live(cache: dict, mock_map: dict | None = None, strict_only: bool = False) -> list[dict]:
    t0 = time.time()
    assert_data_as_of_date(cache)
    cands = cache.get("candidates", [])
    quotes = fetch_tencent_quotes([c["code"] for c in cands]) if cands else {}

    results = []
    for c in cands:
        c6 = c["code"]
        q = quotes.get(c6, {})
        if mock_map and c6 in mock_map:
            op_pct = float(mock_map[c6])
            op_px = round(c["prev_close"] * (1.0 + op_pct), 2)
            zt_px = float(np.floor(c["prev_close"] * 1.10 * 100.0 + 0.5) / 100.0)
            buyable = bool(op_px < zt_px - 0.005)
            cur_px, cur_pct = op_px, op_pct
        elif q and q.get("pre_c", 0) > 0:
            op_px, op_pct = q["open"], q["open_pct"]
            buyable = q["buyable_open"]
            cur_px, cur_pct = q["close"], q["cur_pct"]
        else:
            op_px, op_pct, buyable = c["prev_close"], 0.0, True
            cur_px, cur_pct = c["prev_close"], 0.0

        ev = evaluate_2to3_candidate(c, op_pct, buyable)
        tier = (
            "★满96分高严档" if ev["passed_strict96"]
            else ("✅标准过线(第4顺位)" if ev["passed_std90"] else "⛔未过线/否决")
        )
        results.append({
            **c, **ev, "open_px": round(op_px, 2), "open_pct": op_pct,
            "cur_px": round(cur_px, 2), "cur_pct": cur_pct,
            "buyable_open": buyable, "tier_label": tier,
        })

    results.sort(key=lambda x: (-int(x["passed_std90"]), -x["score"], x["open_pct"], x["plate_sz"], x["code"]))
    passed90 = [r for r in results if r["passed_std90"]]
    passed96 = [r for r in results if r["passed_strict96"]]

    print("=" * 92)
    print(f"【二进三 V2.1 (s_2to3, 底分60, 第4顺位) · 09:25 实时算分 | data_as_of_date={cache['data_as_of_date']} | 耗时 {time.time()-t0:.2f}s】")
    if passed96:
        s96 = "，".join(f"{r['code']} {r['name']} {r['score']}分(今开{r['open_pct']*100:+.2f}%)" for r in passed96)
        print(f"`★满96分高严档单独重点提醒：{s96} — 09:25 竞价直买单（5年35笔/胜率54.29%/单仓17.43x/回撤15.87%）`")
    if passed90 and not strict_only:
        w = passed90[0]
        print(f"`✅标准档过线 (>=90分, 第4顺位补位)：头名 {w['code']} {w['name']} {w['score']}分 | 09:25开盘 {w['open_px']:.2f}元 ({w['open_pct']*100:+.2f}%) | 未封3板持有至次日14:55/15:00清(反包转连板); 封3板>+9.2%非一字09:25止盈,否则13:45摸+8.5%破+6.5%护利+1次真阳免死`")
    elif strict_only and not passed96:
        print("`⛔[s_2to3 高严>=96档] 今日无>=96分标的，高严档空仓。`")
    elif not passed90:
        print("`⛔[s_2to3 第4顺位] 今日无>=90分过线标的，二进三空仓。`")
    print("=" * 92)
    for i, r in enumerate(results, 1):
        v_str = "；".join(r["veto_reasons"]) if r["veto_reasons"] else "门禁全过"
        print(f"  {i:02d}|{r['code']}|{r['name']}|{r['ths_tag']}|{r['plate'][:6]}(sz={r['plate_sz']})|"
              f"总分{r['score']:3d}|今开{r['open_pct']*100:+.2f}%|现{r['cur_pct']*100:+.2f}%|{r['tier_label']}|{v_str}")
        print(f"     {r['breakdown_str']}")
    if not results:
        print("  今日全市场无二连板候选。")
    print("\n【二进三 V2.1 现行定版离场铁律】")
    print("  1. 未封三板：取消次日 <+0.5% 竞价割地板，统一持有过早盘抛压至次日 14:55/15:00 清仓（若次日反包封四板则转入连板骑乘）。")
    print("  2. 封死三板/反包连板期：次日极高开 >+9.2% 且非一字则在 09:25 止盈兑现；否则走 13:45 摸 +8.5% 回落破 +6.5% 护利与 1 次真阳免死。")
    return results


def run_hold_check_2to3(raw_code: str) -> None:
    c6 = str(raw_code).strip().zfill(6)
    quotes = fetch_tencent_quotes([c6])
    q = quotes.get(c6)
    if not q or q.get("pre_c", 0) <= 0:
        print(f"[ERR] 未获取到 {c6} 的腾讯实时行情", file=sys.stderr)
        return
    pre_c = float(q["pre_c"])
    op_px = float(q["open"])
    now_px = float(q["close"])
    hi_px = float(q["high"])
    zt_px = float(q["zt_px"])
    p92 = round(pre_c * 1.092, 2)
    p85 = round(pre_c * 1.085, 2)
    p65 = round(pre_c * 1.065, 2)
    hi_armed = hi_px >= p85
    trig_92 = (q["open_pct"] > 0.092) and (not q["is_yizi"])
    trig_65_now = hi_armed and (now_px <= p65) and (now_px < zt_px - 0.005)
    print("=" * 92)
    print(f"【二进三 V2.1 持仓离场精准定价面板 (第4顺位)】 {c6} {q['name']} | 报价日={q.get('q_dt', '')}")
    print(f"昨收: {pre_c:.2f}元 | 今开: {op_px:.2f}元 ({q['open_pct']*100:+.2f}%) | 最高: {hi_px:.2f}元 | 现价: {now_px:.2f}元 ({q['cur_pct']*100:+.2f}%) | 涨停价: {zt_px:.2f}元")
    print("-" * 92)
    print(f"  1. +9.2% 极高开竞价止盈价 : {p92:.2f}元 -> {'⚠️已触发(今开>+9.2%非一字，09:25直接止盈!)' if trig_92 else '未触发(仅封死三板次日09:25检查)'}")
    print(f"  2. +8.5% 午后摸高激活价   : {p85:.2f}元 -> {'✅今日盘中最高已摸过+8.5%，13:45后进入+6.5%监控!' if hi_armed else '未触及(13:45后需曾摸此价才激活回落护利)'}")
    print(f"  3. +6.5% 午后护利锁利价   : {p65:.2f}元 -> {'🚨已触发(摸+8.5%后回落破+6.5%且未封死)!' if trig_65_now else '13:45后摸+8.5%回落破此价且未封板立即止盈'}")
    print("-" * 92)
    print("  离场总则: 未封三板持有至次日 14:55/15:00 清仓(反包涨停转连板); 封三板/连板期走 >+9.2%非一字止盈 + 13:45摸+8.5%破+6.5%护利 + 首次真阳(收>开且>=昨收)免死1次。")
    print("=" * 92)


def main():
    ap = argparse.ArgumentParser(description="二进三 V2.1 (V2.0买点+6.5%护利) 实时打分与持仓核查引擎 (底分60 / 标准>=90 / 高严>=96)")
    ap.add_argument("--build-cache", action="store_true", help="构建盘前缓存")
    ap.add_argument("--premarket", action="store_true", help="早盘盘前推演面板")
    ap.add_argument("--hold", type=str, default="", help="核查持仓股当日+9.2%/+8.5%/+6.5%精确止盈与护利价")
    ap.add_argument("--strict", action="store_true", help="仅按满96分高严档展示/查询台账")
    ap.add_argument("--mock-open", type=str, default="", help="模拟竞价涨幅，如 '002748=-0.008'")
    ap.add_argument("--as-of", type=str, default="", help="仅用于历史指定收盘日内存验算")
    ap.add_argument("--date", type=str, default="", help="查询历史台账指定买日")
    ap.add_argument("--recent", type=int, default=0, help="查询历史台账最近 N 笔")
    args = ap.parse_args()

    if args.hold:
        run_hold_check_2to3(args.hold)
        return

    if args.date or args.recent > 0:
        csv_p = LEDGER_STRICT_CSV if args.strict else LEDGER_CSV
        df_l = pd.read_csv(csv_p, dtype={"code": str})
        df_l["code"] = df_l["code"].str.zfill(6)
        sub = df_l[df_l["buy_date"] == args.date] if args.date else df_l.sort_values("buy_date").tail(args.recent)
        print(sub[["buy_date", "exit_date", "code", "name", "score", "open_pct", "net_ret", "sealed_3b"]].to_string(index=False))
        return

    if args.as_of:
        cache = build_premarket_cache(verbose=True, as_of_date=args.as_of)
        print_premarket(cache, strict_only=args.strict)
        return

    if args.build_cache or not os.path.exists(CACHE_FILE):
        cache = build_premarket_cache(verbose=True)
        if args.build_cache:
            return
    else:
        cache = json.load(open(CACHE_FILE, "r", encoding="utf-8"))

    if args.premarket:
        assert_data_as_of_date(cache)
        print_premarket(cache, strict_only=args.strict)
        return

    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                mock_map[k.strip()] = float(v.strip())
    run_live(cache, mock_map=mock_map, strict_only=args.strict)


if __name__ == "__main__":
    main()

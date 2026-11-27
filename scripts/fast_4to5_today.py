#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_4to5_today.py — 四进五接力策略 V22.0 生产级实盘引擎 (RD048 SJ114 + E4_DtDefer)
======================================================================================
⛔ 核心红线：
  1. 零 yfinance（D12），腾讯直连强制走 urllib.request.ProxyHandler({})，SQLite 强制 ?mode=ro。
  2. 代码级硬锁：MIN_4TO5_THRESHOLD = 110（默认实盘 114），任何传参 < 110 直接抛 ValueError。
  3. 完整补齐 Pillar 7 全部缺口：
     - TOX_STRICT_RE（严格减持预披露/风险提示补漏正则）+ 10日监管函 + 30日内KPL重点监控；
     - Bug-fixed 互斥 rival_open、真 left_gene（废弃伪3to4缓存85分回退）；
     - 完整 LHB TRADE_ID 去重 / 1日榜优先3日游资排重 / 机构净卖>1000万 / 量化卖出 / 拉萨计数；
     - 完整 KPL 同板块3板+数量（非 THS）、f47 近10日>=4板断板反包率、d4 全市场核按钮数；
     - 兼容兜底补全旧版 `4to5_premarket_cache.json`，确保零崩溃；
     - 完整 `--hold CODE [BUY_PX]` E4 持仓卖点监控（含跌停封死不可卖 `DtDefer` 顺延次日提醒）。
"""
import os
for _k in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
):
    os.environ[_k] = "1"
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import argparse
import datetime
import glob
import json
import re
import sqlite3
import ssl
import sys
import urllib.request
from typing import Any, Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"
CACHE_FILE = f"{DATA_DIR}/4to5_premarket_cache.json"
A_DAILY = f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet"
HOLDERS_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
IDX_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
DB_NOTICES = f"{SIM_DIR}/backtest/2026-08-24-daban/notices.db"
DB_PIT_NOTICES = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
DB_ZT_TAPE = f"{DATA_DIR}/zt_micro_tape_5y_pit.db"
LHB_BUY_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_buy.parquet"
LHB_SELL_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_sell.parquet"
KPL_JSONL = f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
ZDJK_DIR = f"{DATA_DIR}/kpl/zdjk"
LEDGER_CSV = f"{SIM_DIR}/backtests_astock2/p3_deep_100/w2_4to5_v20_ledger.csv"
V21_LEDGER_JSONL = f"{DATA_DIR}/shadow_4piece_2w_ledger.jsonl"

# 代码级硬锁：绝不允许将门槛下调至 <= 108 悬崖区
MIN_4TO5_THRESHOLD = 110
DEFAULT_4TO5_THRESHOLD = 114

# RD048 & Pillar 1B 严格正则（零改动）
TOX_STRICT_RE = re.compile(
    r"(?:减持.*(?:计划|预披露|公告)|(?:计划|预披露).*减持|立案调查|收到立案|退市风险|违法违规|股票交易风险提示)"
)
REG_INC = ("监管函", "关注函", "问询函", "监管工作函", "通报批评", "公开谴责", "立案", "风险提示")
REG_EXC = ("回复", "取消", "撤销", "解除", "不予")

Q_RE = re.compile(r"(?:量化|华鑫.*上海分公司|国际金融.*上海分公司|中信.*上海分公司|高盛|瑞银|开源.*西安西大街|国泰君安.*总部|国泰海通.*总部|摩根大通)")
RE_TOP_YOUZI = re.compile(
    r"(?:大连金马路|大连黄河路|六一中路|天津东丽开发区二纬路|北京东直门南大街|北京广渠门内大街|"
    r"上海江苏路|长宁区江苏路|上海建国西路|杭州延安路|兴业证券.*陕西分公司|西安朱雀大街|"
    r"南京太平南路|宁波桑田路|上海宛平南路|上海红宝石路|上海茅台路|宁波和源路|北京长椿街)"
)
RE_LHASA = re.compile(r"(?:拉萨|山南|昌都)")
RE_INST = re.compile(r"机构专用")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def validate_4to5_threshold(threshold: int | float) -> int:
    """代码级门槛硬锁：严禁传入 < 110（防 <=108 硬悬崖崩溃）."""
    t = int(threshold)
    if t < MIN_4TO5_THRESHOLD:
        raise ValueError(
            f"4to5 阈值硬锁拦截: threshold={threshold} < MIN_4TO5_THRESHOLD={MIN_4TO5_THRESHOLD}，严禁下调！"
        )
    return t


def _http_get_text(url: str, headers: Optional[dict] = None, timeout: float = 2.5) -> str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=SSL_CTX))
    hdr = {"User-Agent": "Mozilla/5.0"}
    if headers:
        hdr.update(headers)
    req = urllib.request.Request(url, headers=hdr)
    with opener.open(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _load_st_set() -> set[str]:
    p = f"{DATA_DIR}/st_universe.json"
    if not os.path.exists(p):
        return set()
    d = json.load(open(p, encoding="utf-8"))
    codes = d.get("codes", d) if isinstance(d, dict) else d
    return {str(x)[-6:].zfill(6) for x in codes}


def _next_weekday(dt_s: str) -> str:
    d = datetime.date.fromisoformat(dt_s) + datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d.isoformat()


def fetch_tencent_batch(codes: list[str]) -> dict[str, dict[str, Any]]:
    """腾讯实时行情批量抓取（ProxyHandler({}) 绕过代理，零 yfinance）."""
    uniq = sorted({str(c).zfill(6) for c in codes if c})
    if not uniq:
        return {}
    res: dict[str, dict[str, Any]] = {}
    for i in range(0, len(uniq), 60):
        ch = uniq[i : i + 60]
        q_list = [f"{'sh' if c.startswith(('6', '9')) else 'sz'}{c}" for c in ch]
        try:
            txt = _http_get_text(f"http://qt.gtimg.cn/q={','.join(q_list)}", timeout=2.5)
            for line in txt.strip().split(";"):
                if "~" not in line:
                    continue
                p = line.split("~")
                if len(p) <= 38:
                    continue
                c6 = p[2].strip().zfill(6)
                nm = p[1].strip()
                cur = float(p[3] or 0.0)
                pc = float(p[4] or 0.0)
                opn = float(p[5] or 0.0)
                hi = float(p[33] or 0.0)
                lo = float(p[34] or 0.0)
                amt_yi = float(p[37] or 0.0) / 10000.0
                b1 = float(p[10] or 0.0)
                s1 = float(p[20] or 0.0)
                dt14 = str(p[30]).strip()
                q_dt = f"{dt14[:4]}-{dt14[4:6]}-{dt14[6:8]}" if len(dt14) >= 8 and dt14[:8].isdigit() else ""
                op_px = opn if opn > 0 else cur
                op_pct = (op_px / pc - 1.0) if (pc > 0 and op_px > 0) else -1.0
                cur_pct = (cur / pc - 1.0) if (pc > 0 and cur > 0) else 0.0
                is20 = c6.startswith(("30", "688", "689"))
                lim = 1.20 if is20 else 1.10
                zt_px = float(np.floor(pc * lim * 100.0 + 0.5) / 100.0) if pc > 0 else 999.0
                dt_px = float(np.floor(pc * (0.80 if is20 else 0.90) * 100.0 + 0.5) / 100.0) if pc > 0 else 0.0
                is_yz = bool(
                    pc > 0 and op_px > 0
                    and (op_px >= zt_px - 0.011 or (b1 > 0 and s1 == 0 and op_pct >= 0.090))
                )
                res[c6] = {
                    "name": nm,
                    "open": op_px,
                    "raw_open": opn,
                    "cur": cur,
                    "high": hi,
                    "low": lo,
                    "pre_c": pc,
                    "open_pct": op_pct,
                    "cur_pct": cur_pct,
                    "amt_yi": amt_yi,
                    "b1": b1,
                    "s1": s1,
                    "zt_px": zt_px,
                    "dt_px": dt_px,
                    "is_zt_open": bool(pc > 0 and op_px >= zt_px - 0.011),
                    "is_zt_cur": bool(pc > 0 and cur >= zt_px - 0.011),
                    "is_dt_cur": bool(pc > 0 and cur <= dt_px + 0.011),
                    "is_yizi": is_yz,
                    "q_dt": q_dt,
                }
        except Exception:
            pass
    return res


def _fetch_tencent_kline_stock(c6: str, limit: int = 30) -> list[dict[str, Any]]:
    sym = f"{'sh' if c6.startswith(('6', '9')) else 'sz'}{c6}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{limit},qfq"
    try:
        js = json.loads(_http_get_text(url, timeout=2.0))
        d_obj = (js.get("data") or {}).get(sym) or {}
        rows = d_obj.get("qfqday") or d_obj.get("day") or []
        out = []
        for r in rows:
            if len(r) >= 6:
                out.append({
                    "dt": str(r[0])[:10],
                    "open": float(r[1]),
                    "close": float(r[2]),
                    "high": float(r[3]),
                    "low": float(r[4]),
                    "vol": float(r[5]),
                })
        return out
    except Exception:
        return []


def _fetch_live_index_map() -> tuple[dict[str, float], dict[str, float]]:
    sh_map, sz_map = {}, {}
    if os.path.exists(IDX_PATH):
        try:
            idx_data = json.load(open(IDX_PATH, encoding="utf-8"))
            sh_map = {str(k)[:10]: float(v) for k, v in (idx_data.get("sh000002") or idx_data.get("sh000001") or {}).items()}
            sz_map = {str(k)[:10]: float(v) for k, v in (idx_data.get("sz399107") or idx_data.get("sz399001") or {}).items()}
        except Exception:
            pass
    for secid, mp in (("sh000002", sh_map), ("sz399107", sz_map)):
        try:
            js = json.loads(_http_get_text(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={secid},day,,,45,", timeout=1.8))
            for r in ((js.get("data") or {}).get(secid) or {}).get("day") or []:
                if len(r) >= 3:
                    mp[str(r[0])[:10]] = float(r[2])
        except Exception:
            pass
    return sh_map, sz_map


def _check_notices_pit_and_live(
    c6: str, sig_date: str, buy_date: str, allow_online: bool = True
) -> tuple[bool, bool, list[str], list[str]]:
    """
    严格按 < buy_date 09:25:00 检查：
      1) 90 日 TOX_STRICT_RE 毒丸公告；
      2) 10 日个股监管函（含风险提示、问询函等 REG_INC 排除 REG_EXC）及近10日 zdjk；
      3) 可选补查东方财富线上最新公告（实盘默认开启，历史回测对账可关闭）。
    注：`notices.db` 仅有日期 `ndate` 无精确时分，必须强制 `ndate < buy_date`，严防盘后公告未来函数！
    """
    d90 = (pd.Timestamp(buy_date) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    d10 = (pd.Timestamp(buy_date) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    cut_ts = f"{buy_date} 09:25:00"

    tox_hits, reg_hits = [], []

    for db_p in (DB_PIT_NOTICES, DB_NOTICES):
        if not os.path.exists(db_p):
            continue
        con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
        try:
            is_cn = "cninfo" in db_p
            col_c = "sec_code" if is_cn else "code"
            col_d = "pub_datetime_cst" if is_cn else "ndate"
            tbl = "notices" if is_cn else "notice"
            rows = con.execute(
                f"SELECT {col_d}, title FROM {tbl} WHERE {col_c}=? AND {col_d}>=? AND {col_d}<=?",
                (c6, d90, cut_ts if is_cn else sig_date),
            ).fetchall()
            for pdt, ti in rows:
                pdt_raw = str(pdt or "")
                if not is_cn:
                    if pdt_raw[:10] >= buy_date:
                        continue
                    pdt_s = f"{pdt_raw[:10]} 18:00:00"
                else:
                    pdt_s = pdt_raw[:19]
                    if len(pdt_s) == 10:
                        pdt_s += " 00:00:00"
                    if pdt_s > cut_ts:
                        continue
                ti_s = str(ti or "")
                if TOX_STRICT_RE.search(ti_s):
                    tox_hits.append(f"{pdt_s[:16]} {ti_s[:36]}")
                if pdt_s[:10] >= d10 and any(w in ti_s for w in REG_INC) and not any(w in ti_s for w in REG_EXC):
                    reg_hits.append(f"{pdt_s[:16]} {ti_s[:36]}")
        except Exception:
            pass
        finally:
            con.close()

    # Check KPL 重点监控 strictly within [d10 .. sig_date]
    d10_ymd = d10.replace("-", "")
    sig_ymd = sig_date.replace("-", "")
    for zf in glob.glob(f"{ZDJK_DIR}/*.json"):
        bname = os.path.splitext(os.path.basename(zf))[0]
        if bname.isdigit() and len(bname) == 8 and (d10_ymd <= bname <= sig_ymd):
            try:
                zd = json.load(open(zf, "r", encoding="utf-8"))
                for it in zd.get("List", []):
                    if str(it[0]).zfill(6) == c6:
                        reg_hits.append(f"{bname} 交易所重点监控")
            except Exception:
                pass

    # Online Eastmoney announcement check (< buy_date 09:25:00)
    if allow_online:
        try:
            ann_url = (
                f"https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=20&page_index=1"
                f"&ann_type=SHA,SZA,BJA&stock_list={c6}"
            )
            js = json.loads(_http_get_text(ann_url, timeout=2.0))
            for it in (js.get("data") or {}).get("list") or []:
                nd = str(it.get("notice_date") or "")[:19]
                disp = str(it.get("display_time") or "")[:19]
                ts_s = disp if len(disp) >= 19 else (f"{nd[:10]} 18:00:00" if nd else "")
                ti_s = str(it.get("title") or "")
                if ts_s and d90 <= ts_s[:10] and ts_s <= cut_ts:
                    if TOX_STRICT_RE.search(ti_s):
                        tox_hits.append(f"{ts_s[:16]} {ti_s[:36]}")
                    if ts_s[:10] >= d10 and any(w in ti_s for w in REG_INC) and not any(w in ti_s for w in REG_EXC):
                        reg_hits.append(f"{ts_s[:16]} {ti_s[:36]}")
        except Exception:
            pass

    tox_hits = sorted(set(tox_hits))
    reg_hits = sorted(set(reg_hits))
    return bool(tox_hits), bool(reg_hits), tox_hits, reg_hits


def _query_em_lhb_dedup(c6: str, sig_date: str) -> dict[str, Any]:
    """线上东方财富龙虎榜按 TRADE_ID 去重 + 1日优先3日游资排重."""
    rows_all = []
    for side in ("BUY", "SELL"):
        url = (
            "https://datacenter-web.eastmoney.com/api/data/v1/get?"
            f"reportName=RPT_BILLBOARD_DAILYDETAILS{side}&columns=TRADE_DATE,TRADE_ID,SECURITY_CODE,OPERATEDEPT_CODE,OPERATEDEPT_NAME,BUY,SELL,NET,EXPLANATION&"
            f"filter=(SECURITY_CODE%3D%22{c6}%22)&sortColumns=TRADE_DATE&sortTypes=-1&pageNumber=1&pageSize=60&source=WEB&client=WEB"
        )
        try:
            js = json.loads(_http_get_text(url, timeout=3.0))
            for r in (js.get("result") or {}).get("data") or []:
                if str(r.get("TRADE_DATE", ""))[:10] == sig_date:
                    rows_all.append({**r, "side": "B" if side == "BUY" else "S"})
        except Exception:
            pass
    return _aggregate_clean_lhb_rows(pd.DataFrame(rows_all), {c6}).get(c6, {})


def _aggregate_clean_lhb_rows(raw: pd.DataFrame, target_codes: set[str]) -> dict[str, dict[str, Any]]:
    """
    精确复现 RD016 `load_clean_lhb` TRADE_ID 去重 + RD048 机构净卖>1000万 + 3日游资排重：
      1) 对每个 (c6, is_three) 只取 min(TRADE_ID)（消除同日多理由重复记录）；
      2) 非机构营业部按 dept_code/dept_name 去重；机构专用按 (is_three, side, BUY, SELL) 去重；
      3) 若当日既有 1 日榜(is_three=0) 也有 3 日榜(is_three=1)，优先 1 日榜判定 D4 机构/游资/量化/拉萨，防 D2/D3 历史游资混入 D4 新买！
    """
    if raw is None or raw.empty:
        return {}
    df = raw.copy()
    df["c6"] = df["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
    df = df[df["c6"].isin(target_codes)].copy()
    if df.empty:
        return {}
    df["is_three"] = df["EXPLANATION"].astype(str).str.contains("三个交易日|3个交易日").astype(int)
    df["TRADE_ID_STR"] = df["TRADE_ID"].astype(str)
    canon = df.groupby(["c6", "is_three"], as_index=False)["TRADE_ID_STR"].min()
    df = df.merge(canon, on=["c6", "is_three", "TRADE_ID_STR"], how="inner")

    df["dept_code"] = df.get("OPERATEDEPT_CODE", pd.Series("", index=df.index)).astype(str).str.strip()
    df["dept_name"] = df["OPERATEDEPT_NAME"].astype(str).str.strip()
    df["BUY"] = pd.to_numeric(df.get("BUY", 0.0), errors="coerce").fillna(0.0)
    df["SELL"] = pd.to_numeric(df.get("SELL", 0.0), errors="coerce").fillna(0.0)

    out: dict[str, dict[str, Any]] = {}
    for c6, g_c6 in df.groupby("c6"):
        # 若既有 1 日榜也有 3 日榜，3日榜游资不重复算作 D4 新买（仅在无1日榜时退回3日榜）
        has_1d = bool((g_c6["is_three"] == 0).any())
        g_use = g_c6[g_c6["is_three"] == 0].copy() if has_1d else g_c6.copy()

        non_org = g_use[~g_use["dept_name"].str.contains("机构专用", na=False) & (g_use["dept_code"] != "0")]
        non_org = non_org.drop_duplicates(["side", "dept_name", "BUY", "SELL"])
        org = g_use[g_use["dept_name"].str.contains("机构专用", na=False) | (g_use["dept_code"] == "0")]
        org = org.drop_duplicates(["side", "BUY", "SELL"])
        clean = pd.concat([non_org, org], ignore_index=True)

        buys = clean[clean["side"] == "B"]
        sells = clean[clean["side"] == "S"]

        b_names = buys["dept_name"].tolist()
        s_names = sells["dept_name"].tolist()

        # 量化卖出数量
        q_sell = int(sum(1 for nm in s_names if Q_RE.search(nm)))
        # 机构净卖（SELL - BUY > 1000万 => net_yi < -0.10）
        inst_b = float(buys[buys["dept_name"].str.contains("机构专用", na=False)]["BUY"].sum())
        inst_s = float(sells[sells["dept_name"].str.contains("机构专用", na=False)]["SELL"].sum())
        inst_net_yi = (inst_b - inst_s) / 1e8
        f52_inst_sell = 1 if (inst_net_yi < -0.10) else 0

        # 顶级游资新买（3日游资排重：优先使用 1 日榜；若仅 3 日榜且同游资也在卖榜则不计新买）
        b_yz = [nm for nm in b_names if RE_TOP_YOUZI.search(nm)]
        s_set = set(s_names)
        top_yz_new = any(nm not in s_set for nm in b_yz)

        # 拉萨买席数
        lh_cnt = int(len({nm for nm in b_names if RE_LHASA.search(nm)}))

        out[c6] = {
            "f_d4_quant_sell": q_sell,
            "f52_d4_inst_sell": f52_inst_sell,
            "lhb_inst_net_yi": round(inst_net_yi, 4),
            "f50_d4_top_yz_new_buy": bool(top_yz_new),
            "f51_d4_lh_cnt": lh_cnt,
            "lhb_used_1d": has_1d,
        }
    return out


def _load_lhb_features(codes: set[str], sig_date: str) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    frames = []
    for path, side in ((LHB_BUY_PATH, "B"), (LHB_SELL_PATH, "S")):
        if not os.path.exists(path):
            continue
        try:
            d = pd.read_parquet(
                path,
                columns=["TRADE_DATE", "TRADE_ID", "SECURITY_CODE", "OPERATEDEPT_CODE", "OPERATEDEPT_NAME", "BUY", "SELL", "EXPLANATION"],
            )
            d = d[(d["TRADE_DATE"].astype(str).str[:10] == sig_date) & (d["SECURITY_CODE"].astype(str).str[:6].str.zfill(6).isin(codes))].copy()
            if not d.empty:
                d["side"] = side
                frames.append(d)
        except Exception:
            pass
    out = _aggregate_clean_lhb_rows(pd.concat(frames, ignore_index=True), codes) if frames else {}
    # 若本地 parquet 尚无当日龙虎榜，线上东财 API 兜底
    missing = [c for c in codes if c not in out]
    for c6 in missing:
        em = _query_em_lhb_dedup(c6, sig_date)
        if em:
            out[c6] = em
    return out


def _compute_env_and_bars_slice(sig_date: str) -> dict[str, Any]:
    """扫描近 ~45 天 a_daily，计算连板、f47 反包率、d4 全市场核按钮数与当日 3 板股池."""
    st_set = _load_st_set()
    end_d = datetime.date.fromisoformat(sig_date)
    start_d = end_d - datetime.timedelta(days=50)
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "turn", "oshare", "amount"]
    df = (
        ds.dataset(A_DAILY, format="parquet")
        .scanner(columns=cols, filter=(ds.field("date") >= ds.scalar(start_d)) & (ds.field("date") <= ds.scalar(end_d)))
        .to_table()
        .to_pandas()
    )
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df["c6"] = df["ticker"].astype(str).str[:6]
    suf = df["ticker"].astype(str).str[-3:]
    df = df[df["c6"].str.startswith(("00", "60", "30", "688", "689")) & suf.isin([".SH", ".SZ"]) & (df["close"] > 0)].copy()
    df = df.sort_values(["c6", "dt_str"]).drop_duplicates(["c6", "dt_str"], keep="first").reset_index(drop=True)

    g = df.groupby("c6", sort=False)
    pa = g["adj_close"].shift(1)
    pc = pa * (df["close"] / df["adj_close"])
    df["pre_c"] = pc
    df["pct"] = df["adj_close"] / pa - 1.0
    df["open_pct"] = (df["open"] / pc - 1.0)
    is20 = df["c6"].str.startswith(("30", "688", "689"))
    is_st = df["c6"].isin(st_set)
    lim = np.where(is20, 0.20, np.where(is_st & (df["dt_str"] < "2026-07-06"), 0.05, 0.10))
    r_th = np.where(is20, 0.195, 0.095)
    zt_px = np.floor(pc * (1.0 + lim) * 100.0 + 0.5) / 100.0
    dt_px = np.floor(pc * (1.0 - lim) * 100.0 + 0.5) / 100.0
    vp = pc.notna() & (pc > 0) & (df["volume"].fillna(0.0) > 0)
    df["zt_px"] = zt_px
    df["is_zt"] = vp & (~is_st) & (df["close"] >= zt_px - 0.011) & (df["pct"] >= r_th)
    df["is_dt"] = vp & (~is_st) & (df["close"] <= dt_px + 0.011) & (df["pct"] <= -r_th)
    df["is_yizi"] = df["is_zt"] & (df["open"] >= zt_px - 0.011) & (df["low"] >= zt_px - 0.011)
    df["is_20cm"] = is20
    df["is_st"] = is_st

    c6_v = df["c6"].to_numpy()
    zt_v = df["is_zt"].to_numpy()
    stk = np.zeros(len(df), dtype=np.int16)
    cur = 0
    pt = ""
    for i in range(len(df)):
        if c6_v[i] != pt:
            cur = 0
            pt = c6_v[i]
        cur = (cur + 1) if zt_v[i] else 0
        stk[i] = cur
    df["streak"] = stk
    df["prev_streak"] = df.groupby("c6", sort=False)["streak"].shift(1).fillna(0).astype(np.int16)

    # f47: 10d broken >=4b rebound ZT rate strictly <= sig_date
    sc_10cm = df[(~df["is_st"]) & (~df["is_20cm"])].copy()
    dts = sorted(sc_10cm["dt_str"].unique())
    reb_pairs = []
    for idx in range(1, len(dts)):
        d_prev, d_cur = dts[idx - 1], dts[idx]
        brk_c = set(sc_10cm[(sc_10cm["dt_str"] == d_prev) & (sc_10cm["prev_streak"] >= 4) & (~sc_10cm["is_zt"])]["c6"])
        if brk_c:
            sub_cur = sc_10cm[(sc_10cm["dt_str"] == d_cur) & (sc_10cm["c6"].isin(brk_c))]
            reb_pairs.append((int(sub_cur["is_zt"].sum()), len(brk_c)))
        else:
            reb_pairs.append((0, 0))
    w10 = reb_pairs[-10:]
    f47_reb = float(sum(x[0] for x in w10) / max(1, sum(x[1] for x in w10))) if sum(x[1] for x in w10) > 0 else 0.0

    sig_df = df[(df["dt_str"] == sig_date) & (~df["is_st"])]
    sig_10 = sig_df[~sig_df["is_20cm"]]
    d4_mkt_nuke_cnt = int(len(sig_df[(sig_df["prev_streak"] >= 2) & sig_df["is_dt"]]))
    mkt_max_b = int(sig_10["streak"].max()) if not sig_10.empty else 4
    s3_codes = set(sig_10[sig_10["streak"] == 3]["c6"].tolist())

    return {
        "df": df,
        "sig_df": sig_10,
        "mkt_max_b": mkt_max_b,
        "f47_reb_zt_r10": round(f47_reb, 6),
        "d4_mkt_nuke_cnt": d4_mkt_nuke_cnt,
        "s3_codes": s3_codes,
        "st_set": st_set,
    }


def _load_kpl_plate_3b_map(sig_date: str, s3_codes: set[str], target_codes: set[str]) -> dict[str, int]:
    """用 KPL 同日真实板块计算同题材 3 板数量（彻底淘汰旧版 THS 代理）."""
    out = {c: 0 for c in target_codes}
    if not os.path.exists(KPL_JSONL) or not target_codes:
        return out
    try:
        with open(KPL_JSONL, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                obj = json.loads(ln)
                if str(obj.get("date", ""))[:10] == sig_date:
                    for pl in obj.get("plates", []):
                        pcs = {str(s[0])[:6].zfill(6) for s in pl.get("stocks", [])}
                        cnt_3b = len(pcs & s3_codes)
                        for c in pcs & target_codes:
                            out[c] = max(out[c], cnt_3b)
    except Exception:
        pass
    return out


def _check_is_held_3to4(c6: str, sig_date: str) -> tuple[bool, float]:
    """只读检查历史影子/实盘是否已在 sig_date 持有该票三进四（废除 85 分伪缓存回退）."""
    is_held = False
    d4_v34 = -999.0
    if os.path.exists(V21_LEDGER_JSONL):
        try:
            with open(V21_LEDGER_JSONL, encoding="utf-8") as f:
                for ln in f:
                    if not ln.strip():
                        continue
                    o = json.loads(ln)
                    if str(o.get("date", "")) == sig_date:
                        pk = o.get("shadow_pick_obj") or o.get("v20_pick_obj") or {}
                        if pk.get("strategy") == "3to4" and str(pk.get("code", "")).zfill(6) == c6:
                            is_held = True
                            if pk.get("score") is not None:
                                d4_v34 = float(pk["score"])
        except Exception:
            pass
    return is_held, d4_v34


def score_fixed_4to5_row(
    cand: dict[str, Any],
    open_px: Optional[float] = None,
    open_pct: Optional[float] = None,
    is_yizi_open: bool = False,
    is_top1_4b_open: Optional[bool] = None,
    b4_rival_cnt: Optional[int] = None,
    threshold: int = DEFAULT_4TO5_THRESHOLD,
) -> dict[str, Any]:
    """
    严格对齐 RD048 `step1_gem1_4to5_polish.py::score_fixed_4to5` 整数打分卡与硬前提门。
    ⛔ 硬锁：threshold < 110 直接抛出 ValueError！
    """
    thr = validate_4to5_threshold(threshold)

    is_premarket = open_pct is None or open_px is None
    if not is_premarket:
        if is_yizi_open or float(open_pct) >= 0.098 or float(open_px) <= 0.0:
            return {"score": -999, "passed": False, "gate_status": "fail_not_buyable", "breakdown": {}, "hr_pit": 0.0}
    if bool(cand.get("has_tox_strict", cand.get("has_tox_notice", False))):
        return {"score": -999, "passed": False, "gate_status": "fail_tox_notice", "breakdown": {}, "hr_pit": 0.0}
    if bool(cand.get("has_stock_reg", False)):
        return {"score": -999, "passed": False, "gate_status": "fail_stock_reg", "breakdown": {}, "hr_pit": 0.0}
    if bool(cand.get("d4_blown_pm", False)):
        return {"score": -999, "passed": False, "gate_status": "fail_d4_blown_pm", "breakdown": {}, "hr_pit": 0.0}

    tight_px = float(cand.get("tight_px", 99999.0))
    px_d4 = float(cand.get("px_d4", cand.get("close", 0.0)) or 0.0)
    op_use = float(open_px) if not is_premarket else (px_d4 * 1.045)
    op_pct_use = float(open_pct) if not is_premarket else 0.045
    hr_pit = (tight_px / op_use - 1.0) if op_use > 0 else 0.0

    if hr_pit < 0.12:
        return {"score": -999, "passed": False, "gate_status": "fail_headroom_lt12", "breakdown": {}, "hr_pit": hr_pit}
    if not is_premarket and (op_pct_use < 0.020 or op_pct_use > 0.075):
        return {"score": -999, "passed": False, "gate_status": "fail_open_not_sweet", "breakdown": {}, "hr_pit": hr_pit}

    score = 100
    bd: dict[str, int] = {}

    # 1. F49 筹码
    lock_top10 = float(cand.get("lock_top10", 0.0) or 0.0)
    real_mcap = float(cand.get("real_free_mcap", 20.0) or 20.0)
    f49 = 0
    if (lock_top10 >= 50.0) and (12.0 <= real_mcap <= 35.0):
        f49 = 8
    elif (lock_top10 >= 45.0) or (real_mcap >= 45.0):
        f49 = 3
    elif (lock_top10 < 45.0) and (real_mcap < 45.0):
        f49 = -8
    score += f49
    bd["f49_chip"] = f49

    # 2. F58 异动空间
    f58 = 6 if hr_pit >= 0.25 else (4 if hr_pit >= 0.22 else 0)
    score += f58
    bd["f58_headroom"] = f58

    # 3. 身位周期
    max_b = int(cand.get("mkt_max_board_prev", 4) or 4)
    st_sc = 5 if max_b == 4 else (2 if max_b == 5 else (-5 if max_b >= 6 else 0))
    score += st_sc
    bd["status_lead"] = st_sc

    # 4. 四板竞争格局（互斥不叠加）
    rival_cnt = int(cand.get("b4_rival_cnt", 1) if b4_rival_cnt is None else b4_rival_cnt)
    is_sole = (rival_cnt <= 1) if is_top1_4b_open is not None else bool(cand.get("is_sole_4b", False))
    top1_flag = bool(cand.get("is_top1_4b_open", True)) if is_top1_4b_open is None else bool(is_top1_4b_open)
    if is_sole:
        rv_sc = 6
    elif top1_flag and rival_cnt < 2:
        rv_sc = 3
    else:
        rv_sc = -5
    score += rv_sc
    bd["rival_open"] = rv_sc

    # 5. 左端基因（完全对齐 score_fixed_4to5，绝不用假 85 分）
    left_sc = 0
    d4_s34 = float(cand.get("d4_v34_score", -999.0) or -999.0)
    if (82.0 <= d4_s34 <= 89.0) and is_sole:
        left_sc += 5
    if bool(cand.get("is_held_3to4", False)):
        left_sc += 4
    d4_op = float(cand.get("d4_open_pct", 0.0) or 0.0)
    d4_buy = bool(cand.get("d4_buyable_open", True))
    d3_yz = bool(cand.get("d3_prev_is_yizi", False))
    if ((d4_op > 0.092) or (not d4_buy) or d3_yz) and (0.020 <= op_pct_use <= 0.060):
        left_sc += 3
    obc = int(cand.get("open_board_count", 0) or 0)
    d3_obc = int(cand.get("d3_open_board_count", 0) or 0)
    to_r = float(cand.get("to_ratio_d4_d3", 1.0) or 1.0)
    if (obc >= 1) and (d3_obc >= 1) and (0.70 <= to_r <= 1.35):
        left_sc += 3
    score += left_sc
    bd["left_gene"] = left_sc

    # 6. 席位博弈
    lhb_sc = 0
    if int(cand.get("f_d4_quant_sell", 0) or 0) >= 1:
        lhb_sc -= 5
    if int(cand.get("f52_d4_inst_sell", 0) or 0) >= 1:
        lhb_sc -= 3
    if bool(cand.get("f50_d4_top_yz_new_buy", False)):
        lhb_sc -= 3
    if int(cand.get("f51_d4_lh_cnt", 0) or 0) >= 3:
        lhb_sc -= 6
    score += lhb_sc
    bd["lhb_seat"] = lhb_sc

    # 7. 题材与日历节律
    env_sc = 0
    if int(cand.get("plate_3b_cnt", 0) or 0) >= 1:
        env_sc -= 6
    if px_d4 > 20.0:
        env_sc -= 6
    if int(cand.get("d4_mkt_nuke_cnt", 0) or 0) >= 1:
        env_sc -= 3
    if float(cand.get("f47_reb_zt_r10", 0.0) or 0.0) >= 0.20:
        env_sc += 6
    dow = int(cand.get("dow", 2) or 2)
    if dow == 1 or bool(cand.get("is_post_holiday_or_mon_pit", False)):
        env_sc += 6
    elif dow in (4, 5):
        env_sc -= 3
    mo = int(cand.get("buy_month", 0) or 0)
    if mo in (1, 5):
        env_sc -= 6
    score += env_sc
    bd["theme_calendar"] = env_sc

    passed = (not is_premarket) and (score >= thr)
    return {
        "score": int(score),
        "passed": bool(passed),
        "gate_status": "pass" if (is_premarket or passed) else f"score_lt_{thr}",
        "breakdown": bd,
        "hr_pit": round(hr_pit, 4),
    }


def enrich_4to5_cache_if_needed(cache: dict[str, Any], allow_online: bool = True) -> dict[str, Any]:
    """
    内存兜底补全：若磁盘上的 `4to5_premarket_cache.json` 缺少 RD048 SJ114 新字段，
    立即基于 `a_daily.parquet` + `zt_micro_tape_5y_pit.db?mode=ro` + `cninfo_notices_5y_pit.db?mode=ro`
    + `lhb_buy/sell` + `kpl` 补全全部特征，保证零崩溃与零口径漂移！
    """
    cands = cache.get("candidates") or []
    req_keys = ("f47_reb_zt_r10", "d4_mkt_nuke_cnt", "plate_3b_cnt", "has_tox_strict", "d4_open_pct", "to_ratio_d4_d3", "f52_d4_inst_sell", "f_d4_quant_sell")
    if cache.get("schema_v") == 2 and all(all(k in c for k in req_keys) for c in cands):
        return cache

    sig_date = str(cache.get("sig_date", ""))[:10]
    buy_date = str(cache.get("buy_date") or (_next_weekday(sig_date) if sig_date else ""))[:10]
    if not sig_date or not cands:
        cache["schema_v"] = 2
        return cache

    env = _compute_env_and_bars_slice(sig_date)
    df = env["df"]
    cset = {str(c["code"]).zfill(6) for c in cands}
    lhb_map = _load_lhb_features(cset, sig_date)
    plate_3b_map = _load_kpl_plate_3b_map(sig_date, env["s3_codes"], cset)

    # Read zt_micro_tape valid columns ONLY (no last_seal_time!)
    zt_info: dict[tuple[str, str], tuple[str, int]] = {}
    if os.path.exists(DB_ZT_TAPE):
        con_z = sqlite3.connect(f"file:{DB_ZT_TAPE}?mode=ro", uri=True)
        try:
            ph = ",".join("?" for _ in cset)
            for td, sc, fst, obc in con_z.execute(
                f"SELECT trade_date, sec_code, first_seal_time, open_board_count FROM zt_micro_tape WHERE sec_code IN ({ph}) AND trade_date<=? AND trade_date>=?",
                (*sorted(cset), sig_date, (pd.Timestamp(sig_date) - pd.Timedelta(days=15)).strftime("%Y-%m-%d")),
            ).fetchall():
                zt_info[(str(td)[:10], str(sc).zfill(6))] = (str(fst or ""), int(obc or 0))
        finally:
            con_z.close()

    sig_ts = pd.Timestamp(sig_date)
    buy_ts = pd.Timestamp(buy_date)
    is_post_hol = (buy_ts.weekday() == 0) or ((buy_ts - sig_ts).days >= 4)

    new_cands = []
    for c in cands:
        c6 = str(c["code"]).zfill(6)
        sub = df[df["c6"] == c6].sort_values("dt_str")
        r4 = sub[sub["dt_str"] == sig_date].iloc[-1] if not sub[sub["dt_str"] == sig_date].empty else None
        r3 = sub[sub["dt_str"] < sig_date].iloc[-1] if not sub[sub["dt_str"] < sig_date].empty else None
        r2 = sub[sub["dt_str"] < sig_date].iloc[-2] if len(sub[sub["dt_str"] < sig_date]) >= 2 else None
        d3_dt = str(r3["dt_str"]) if r3 is not None else ""

        tox_strict, reg_10, tox_list, reg_list = _check_notices_pit_and_live(c6, sig_date, buy_date, allow_online=allow_online)
        fst4, obc4 = zt_info.get((sig_date, c6), ("", 0))
        _, obc3 = zt_info.get((d3_dt, c6), ("", 0)) if d3_dt else ("", 0)
        blown_pm = bool(c.get("d4_blown_pm", False)) or (fst4 > "13:45:00" and obc4 >= 1)

        t4 = float(r4["turn"]) if (r4 is not None and pd.notna(r4["turn"])) else 1.0
        t3 = float(r3["turn"]) if (r3 is not None and pd.notna(r3["turn"]) and float(r3["turn"]) > 0) else t4
        to_ratio = float(t4 / max(1e-6, t3)) if t3 > 0 else 1.0

        d4_op = float(r4["open_pct"]) if (r4 is not None and pd.notna(r4["open_pct"])) else 0.0
        d4_buy = bool(not bool(r4["is_yizi"])) if r4 is not None else True
        d3_yz = bool(r3["is_yizi"]) if r3 is not None else False
        is_held_34, d4_v34 = _check_is_held_3to4(c6, sig_date)

        lh_d = lhb_map.get(c6, {})
        c_new = dict(c)
        c_new.update({
            "px_d4": round(float(c.get("px_d4") or c.get("close") or (float(r4["close"]) if r4 is not None else 0.0)), 2),
            "sig_date": sig_date,
            "buy_date": buy_date,
            "has_tox_strict": tox_strict,
            "has_tox_notice": tox_strict,
            "tox_hits": tox_list,
            "has_stock_reg": reg_10,
            "reg_hits": reg_list,
            "d4_blown_pm": blown_pm,
            "f47_reb_zt_r10": env["f47_reb_zt_r10"],
            "d4_mkt_nuke_cnt": env["d4_mkt_nuke_cnt"],
            "mkt_max_board_prev": int(c.get("mkt_max_board_prev") or env["mkt_max_b"]),
            "plate_3b_cnt": plate_3b_map.get(c6, 0),
            "f_d4_quant_sell": int(lh_d.get("f_d4_quant_sell", 0)),
            "f52_d4_inst_sell": int(lh_d.get("f52_d4_inst_sell", 0)),
            "lhb_inst_net_yi": float(lh_d.get("lhb_inst_net_yi", 0.0)),
            "f50_d4_top_yz_new_buy": bool(lh_d.get("f50_d4_top_yz_new_buy", False)),
            "f51_d4_lh_cnt": int(lh_d.get("f51_d4_lh_cnt", 0)),
            "open_board_count": obc4,
            "d3_open_board_count": obc3,
            "to_ratio_d4_d3": round(to_ratio, 4),
            "d4_open_pct": round(d4_op, 5),
            "d4_buyable_open": d4_buy,
            "d3_prev_is_yizi": d3_yz,
            "is_held_3to4": is_held_34,
            "d4_v34_score": d4_v34,
            "dow": int(buy_ts.weekday() + 1),
            "buy_month": int(buy_ts.month),
            "is_post_holiday_or_mon_pit": is_post_hol,
            "b4_rival_cnt": int(len(cands)),
            "is_sole_4b": bool(len(cands) <= 1),
        })
        pre_sc = score_fixed_4to5_row(c_new, threshold=DEFAULT_4TO5_THRESHOLD)
        c_new["static_score"] = int(pre_sc["score"])
        c_new["breakdown"] = pre_sc["breakdown"]
        c_new["hr_est"] = round(float(pre_sc["hr_pit"]), 4)
        c_new["static_gate"] = pre_sc["gate_status"]
        new_cands.append(c_new)

    out = dict(cache)
    out["schema_v"] = 2
    out["buy_date"] = buy_date
    out["f47_reb_zt_r10"] = env["f47_reb_zt_r10"]
    out["d4_mkt_nuke_cnt"] = env["d4_mkt_nuke_cnt"]
    out["candidates"] = new_cands
    return out


def build_premarket_cache(verbose: bool = True, as_of: Optional[str] = None, allow_online: Optional[bool] = None) -> dict[str, Any]:
    """盘后/盘前构建完整 RD048 SJ114 4to5 盘前缓存（零 yfinance）."""
    t0 = pd.Timestamp.now()
    ad_tbl = ds.dataset(A_DAILY, format="parquet").scanner(
        columns=["date"], filter=ds.field("date") >= pd.Timestamp("2026-10-15")
    ).to_table().to_pandas()
    ad_dts = sorted(ad_tbl["date"].dt.strftime("%Y-%m-%d").unique().tolist())
    sig_date = as_of or ad_dts[-1]
    buy_date = _next_weekday(sig_date)

    env = _compute_env_and_bars_slice(sig_date)
    df = env["df"]
    sig_10 = env["sig_df"]
    b4_df = sig_10[sig_10["streak"] == 4].copy()
    b4_codes = sorted(b4_df["c6"].tolist())

    holders = json.load(open(HOLDERS_PATH, encoding="utf-8")) if os.path.exists(HOLDERS_PATH) else {}
    sh_map, sz_map = _fetch_live_index_map()

    # Query names via Tencent if available
    q_names = fetch_tencent_batch(b4_codes) if b4_codes else {}

    base_cands = []
    for c6 in b4_codes:
        sub = df[df["c6"] == c6].sort_values("dt_str")
        r4 = sub[sub["dt_str"] == sig_date].iloc[-1]
        px_d4 = float(r4["close"])
        osh = float(r4["oshare"]) if pd.notna(r4["oshare"]) and float(r4["oshare"]) > 0 else 0.0

        h_recs = [x for x in holders.get(c6, []) if isinstance(x, (list, tuple)) and len(x) > 2 and str(x[0]) <= sig_date]
        lock = float(max(h_recs, key=lambda x: str(x[1]))[2]) if h_recs else 38.0
        fmcap = float(px_d4 * osh * (1.0 - lock / 100.0) / 1e8) if osh > 0 else 25.0

        imap = sh_map if c6.startswith("60") else sz_map
        ir = imap.get(sig_date, 1.0)
        p100, p200 = 99999.0, 99999.0
        dts_s = sub["dt_str"].tolist()
        cls_s = sub["close"].tolist()
        pos = len(sub) - 1
        for k in range(1, min(10, pos) + 1):
            bi = imap.get(dts_s[pos - k])
            bc = cls_s[pos - k]
            if bi and bc > 0:
                p100 = min(p100, bc * (2.0 + (ir / bi - 1.0)))
        for k in range(1, min(30, pos) + 1):
            bi = imap.get(dts_s[pos - k])
            bc = cls_s[pos - k]
            if bi and bc > 0:
                p200 = min(p200, bc * (3.0 + (ir / bi - 1.0)))
        tight_px = min(p100, p200)

        base_cands.append({
            "code": c6,
            "name": q_names.get(c6, {}).get("name", c6),
            "close": round(px_d4, 2),
            "px_d4": round(px_d4, 2),
            "tight_px": round(tight_px, 2),
            "lock_top10": round(lock, 2),
            "real_free_mcap": round(fmcap, 2),
        })

    skeleton = {
        "schema_v": 1,
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sig_date": sig_date,
        "buy_date": buy_date,
        "mkt_max_board": env["mkt_max_b"],
        "candidates": base_cands,
    }
    on_flag = (not bool(as_of)) if allow_online is None else bool(allow_online)
    enriched = enrich_4to5_cache_if_needed(skeleton, allow_online=on_flag)
    enriched["build_time_sec"] = round((pd.Timestamp.now() - t0).total_seconds(), 3)

    if not as_of:
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(enriched, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CACHE_FILE)
    if verbose:
        print(f"[+] 四进五 RD048 SJ114 盘前缓存已生成 ({sig_date} -> {buy_date}): 4连板候选 {len(base_cands)} 只 (最高连板={env['mkt_max_b']}板, f47={env['f47_reb_zt_r10']*100:.1f}%, nuke={env['d4_mkt_nuke_cnt']}, 耗时 {enriched['build_time_sec']}s)")
    return enriched


def evaluate_4to5_candidates(
    cache: dict[str, Any],
    q_map: Optional[dict[str, dict[str, Any]]] = None,
    threshold: int = DEFAULT_4TO5_THRESHOLD,
    premarket: bool = False,
    mock_map: Optional[dict[str, float]] = None,
    allow_live_qq: bool = True,
) -> dict[str, Any]:
    """统一评估四进五候选池（供 CLI 与 fast_v22_shadow_today.py 共用，门槛硬锁 >=110）."""
    thr = validate_4to5_threshold(threshold)
    enriched = enrich_4to5_cache_if_needed(cache, allow_online=allow_live_qq)
    cands = enriched.get("candidates") or []
    sig_date = str(enriched.get("sig_date", ""))
    mock_map = mock_map or {}

    if not cands:
        return {"sig_date": sig_date, "buy_date": enriched.get("buy_date", ""), "threshold": thr, "cands": [], "passed": [], "evaluated": []}

    codes = [str(c["code"]).zfill(6) for c in cands]
    if q_map is None and (not premarket) and allow_live_qq:
        q_map = fetch_tencent_batch(codes)
    q_map = q_map or {}

    # Compute 09:25 non-yizi rivals cleanly across 4-board peers
    live_rows: dict[str, dict[str, Any]] = {}
    for c in cands:
        c6 = str(c["code"]).zfill(6)
        if c6 in mock_map:
            pre_m = float(c.get("px_d4") or c.get("close") or q_map.get(c6, {}).get("pre_c") or 10.0)
            opv = float(mock_map[c6])
            op_m = round(pre_m * (1.0 + opv), 2)
            zt_m = float(np.floor(pre_m * 1.10 * 100.0 + 0.5) / 100.0)
            live_rows[c6] = {
                "is_live": True,
                "name": q_map.get(c6, {}).get("name", c.get("name", c6)),
                "open": op_m,
                "open_pct": opv,
                "is_yizi": bool(op_m >= zt_m - 0.011 or opv >= 0.098),
            }
        elif not premarket:
            rq = q_map.get(c6, {})
            ilv = bool(rq and ((not sig_date) or rq.get("q_dt", "") > sig_date))
            live_rows[c6] = {
                "is_live": ilv,
                "name": rq.get("name", c.get("name", c6)),
                "open": float(rq.get("open", 0.0)) if ilv else None,
                "open_pct": float(rq.get("open_pct", -1.0)) if ilv else None,
                "is_yizi": bool(rq.get("is_yizi", False)) if ilv else False,
            }
        else:
            live_rows[c6] = {"is_live": False, "name": c.get("name", c6), "open": None, "open_pct": None, "is_yizi": False}

    non_yizi_rivals = [
        (c6, lr["open_pct"]) for c6, lr in live_rows.items()
        if lr["is_live"] and (not lr["is_yizi"]) and float(lr["open_pct"]) < 0.098
    ]
    b4_cnt = len(non_yizi_rivals) if non_yizi_rivals else len(cands)
    top_op = max((op for _, op in non_yizi_rivals), default=None)

    evaluated, passed = [], []
    for c in cands:
        c6 = str(c["code"]).zfill(6)
        lr = live_rows[c6]
        is_top1 = (bool(abs(float(lr["open_pct"]) - top_op) < 1e-6) if (lr["is_live"] and top_op is not None) else None)
        sc_res = score_fixed_4to5_row(
            c,
            open_px=lr["open"],
            open_pct=lr["open_pct"],
            is_yizi_open=lr["is_yizi"],
            is_top1_4b_open=is_top1,
            b4_rival_cnt=b4_cnt if lr["is_live"] else len(cands),
            threshold=thr,
        )
        rec = {
            "code": c6,
            "name": lr["name"],
            "px_d4": float(c.get("px_d4") or c.get("close") or 0.0),
            "open": lr["open"],
            "open_pct": lr["open_pct"],
            "score": int(sc_res["score"]),
            "passed": bool(sc_res["passed"]),
            "gate_status": sc_res["gate_status"],
            "hr_pit": float(sc_res["hr_pit"]),
            "breakdown": sc_res["breakdown"],
            "has_tox_strict": bool(c.get("has_tox_strict", False)),
            "has_stock_reg": bool(c.get("has_stock_reg", False)),
            "d4_blown_pm": bool(c.get("d4_blown_pm", False)),
            "tox_hits": c.get("tox_hits", []),
            "reg_hits": c.get("reg_hits", []),
            "lock_top10": c.get("lock_top10"),
            "real_free_mcap": c.get("real_free_mcap"),
            "f47_reb_zt_r10": c.get("f47_reb_zt_r10"),
            "d4_mkt_nuke_cnt": c.get("d4_mkt_nuke_cnt"),
            "plate_3b_cnt": c.get("plate_3b_cnt"),
        }
        evaluated.append(rec)
        if rec["passed"]:
            passed.append(rec)

    passed.sort(key=lambda x: (-x["score"], x["code"]))
    return {
        "sig_date": sig_date,
        "buy_date": enriched.get("buy_date", ""),
        "threshold": thr,
        "cands": cands,
        "evaluated": evaluated,
        "passed": passed,
    }


def run_hold_check_4to5(code: str, buy_px_arg: Optional[float] = None, buy_date_arg: str = "") -> int:
    """
    完整 `--hold CODE [BUY_PX]` E4_DtDefer 持仓卖点引擎：
      - 覆盖 Day0（买入当日）封板失败复盘（提示次日需 +0.5% 且收盘翻强，或 F61 接力）；
      - 覆盖 D+1 起连板持仓 + 首次真阳（收>开且收>=昨收）免死 1 次；
      - 显式检测跌停封死不可卖（`DtDefer`），提示顺延至下一非一字跌停开盘卖出！
    """
    c6 = str(code).strip().zfill(6)
    q = fetch_tencent_batch([c6]).get(c6)
    if not q or float(q.get("cur", 0.0)) <= 0:
        print(f"[ERROR] 腾讯行情获取失败: {c6}")
        return 1

    name = q["name"]
    cur = float(q["cur"])
    op = float(q["open"])
    pre_c = float(q["pre_c"])
    zt_px = float(q["zt_px"])
    dt_px = float(q["dt_px"])
    today_s = q["q_dt"] or datetime.date.today().isoformat()

    # Build recent daily bar trajectory (a_daily + Tencent qfq kline tail + today's quote)
    tkr = f"{c6}.SH" if c6.startswith("6") else f"{c6}.SZ"
    hist = (
        ds.dataset(A_DAILY, format="parquet")
        .scanner(columns=["date", "open", "high", "low", "close"], filter=(ds.field("ticker") == tkr) & (ds.field("date") >= pd.Timestamp("2026-10-15")))
        .to_table()
        .to_pandas()
    )
    bars_map: dict[str, dict[str, float]] = {}
    for r in hist.itertuples(index=False):
        bars_map[r.date.strftime("%Y-%m-%d")] = {
            "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close)
        }
    for kb in _fetch_tencent_kline_stock(c6, 20):
        bars_map.setdefault(kb["dt"], {k: kb[k] for k in ("open", "high", "low", "close")})
    bars_map[today_s] = {"open": op, "high": float(q["high"]), "low": float(q["low"]), "close": cur}

    dts = sorted(bars_map.keys())
    bars = []
    for i, d in enumerate(dts):
        b = bars_map[d]
        pc_i = bars_map[dts[i - 1]]["close"] if i > 0 else b["open"]
        zt_i = float(np.floor(pc_i * 1.10 * 100.0 + 0.5) / 100.0) if pc_i > 0 else 999.0
        dt_i = float(np.floor(pc_i * 0.90 * 100.0 + 0.5) / 100.0) if pc_i > 0 else 0.0
        is_zt_i = bool(pc_i > 0 and b["close"] >= zt_i - 0.011 and b["close"] / pc_i - 1.0 >= 0.095)
        is_dt_i = bool(pc_i > 0 and b["close"] <= dt_i + 0.011 and b["close"] / pc_i - 1.0 <= -0.095)
        is_yz_dt_i = bool(is_dt_i and b["open"] <= dt_i + 0.011 and b["high"] <= dt_i + 0.011)
        bars.append({
            "dt": d, **b, "pre_c": pc_i, "zt_px": zt_i, "dt_px": dt_i,
            "is_zt": is_zt_i, "is_dt": is_dt_i, "is_yizi_dt": is_yz_dt_i,
        })

    dt_idx = {b["dt"]: i for i, b in enumerate(bars)}
    if buy_date_arg and buy_date_arg in dt_idx:
        b_pos = dt_idx[buy_date_arg]
    elif buy_date_arg:
        b_pos = len(bars) - 1
    else:
        b_pos = len(bars) - 1

    b_rec = bars[b_pos]
    buy_px = float(buy_px_arg) if buy_px_arg else float(b_rec["open"])
    pnl_pct = (cur / buy_px - 1.0) * 100.0 if buy_px > 0 else 0.0

    # Walk E4_DtDefer state from b_pos to today
    is_locked_dt_today = bool(q["is_dt_cur"] or (q["b1"] == 0 and q["s1"] > 0 and cur <= dt_px + 0.011))
    is_zt_today = bool(q["is_zt_cur"])
    imm_used = False
    action_msg = ""

    if b_pos == len(bars) - 1:
        # 买入当日 Day 0
        if is_zt_today:
            action_msg = "持仓状态: 买入当日涨停封板，继续持有至次日观察。"
        elif is_locked_dt_today:
            action_msg = "持仓状态: 今日买入（T+1 锁仓），当前触及跌停价，留意次日开盘承接与 DtDefer 顺延。"
        else:
            d4_str = (cur >= op) and (cur >= pre_c)
            if d4_str:
                action_msg = "持仓状态: 买入当日断板但收阳强承接（收>=开且收>=昨收），次日若竞价>=+0.5%则继续观察冲板，否则09:25直接卖出。"
            else:
                action_msg = "持仓状态: 买入当日断板偏弱（未满足强承接），按 E4 规则次日 09:25 开盘直接清仓（若明日一字跌停则 DtDefer 顺延）。"
    else:
        # D+1 或更晚持仓日
        pos0 = b_pos
        b0 = bars[pos0]
        idx_k = pos0 + 1
        settled_done = False

        if not b0["is_zt"]:
            # Day 0 未涨停，核对 Day 1
            while idx_k < len(bars) - 1 and bars[idx_k]["is_yizi_dt"]:
                idx_k += 1
            if idx_k == len(bars) - 1:
                if is_locked_dt_today:
                    action_msg = "卖出指令: 【DtDefer 跌停不可卖顺延】今日跌停封死无法成交，顺延至下一非一字跌停交易日开盘清仓！"
                    settled_done = True
                elif idx_k > pos0 + 1:
                    action_msg = "卖出指令: 前日跌停顺延至今打开，立即在 09:25 开盘全部清仓！"
                    settled_done = True
                else:
                    d0_strong = (b0["close"] >= b0["open"]) and (b0["close"] >= b0["pre_c"]) and (op >= pre_c * 1.005)
                    if not d0_strong:
                        action_msg = f"卖出指令: Day0 未封板且今开不满足(昨强+今开>=+0.5%={pre_c*1.005:.2f})，按 E4 立即 09:25 清仓！"
                        settled_done = True
                    elif is_zt_today:
                        action_msg = "持仓状态: Day0 断板反包涨停，继续锁仓持有！"
                        settled_done = True
                    else:
                        action_msg = "卖出指令: Day1 反包未封涨停，按 E4 于 15:00 收盘清仓（若收盘封死跌停则 DtDefer 顺延次日开盘）！"
                        settled_done = True
            else:
                idx_k += 1

        if not settled_done:
            while idx_k < len(bars) - 1:
                bk = bars[idx_k]
                if bk["is_yizi_dt"] or bk["is_zt"]:
                    idx_k += 1
                    continue
                if (not imm_used) and (bk["close"] > bk["open"]) and (bk["close"] >= bk["pre_c"]):
                    imm_used = True
                    idx_k += 1
                    continue
                idx_k += 1
            # Inspect today (len(bars) - 1)
            prev_b = bars[-2] if len(bars) >= 2 else b0
            if is_locked_dt_today:
                action_msg = "卖出指令: 【DtDefer 跌停不可卖顺延】今日跌停封死不可成交，卖单顺延至下一可成交交易日开盘卖出！"
            elif prev_b["is_yizi_dt"]:
                action_msg = "卖出指令: 昨日跌停无法卖出今日顺延开板，按 DtDefer 规则于今日 09:25 开盘立刻清仓！"
            elif is_zt_today:
                action_msg = f"持仓状态: 涨停封板中（{cur:.2f}元 = 涨停 {zt_px:.2f}元），继续持有（真阳免死剩余 {'0次' if imm_used else '1次'}）。"
            elif (not imm_used) and (cur > op) and (cur >= pre_c):
                action_msg = f"持仓状态: 未封板但触发首次真阳免死（现价 {cur:.2f} > 开 {op:.2f} 且 >= 昨收 {pre_c:.2f}），若收盘保持真阳则免死持有 1 天；若转阴或破昨收则 15:00 清仓。"
            else:
                imm_txt = "首次真阳免死已用尽" if imm_used else "今日未满足真阳免死(需收>开且>=昨收)"
                action_msg = f"卖出指令: 连板断开且{imm_txt}，按 E4 规则于今日尾盘 15:00 前清仓（若封死跌停 {dt_px:.2f} 元则 DtDefer 顺延次日开盘）！"

    print(f"【四进五 E4_DtDefer 持仓核查】{c6} {name} | 核查日={today_s.replace('-', '/')} | 买日={b_rec['dt'].replace('-', '/')}")
    print(f"买入参考价: {buy_px:.2f}元 | 昨收: {pre_c:.2f}元 | 今开: {op:.2f}元 | 现价: {cur:.2f}元 (浮盈 {pnl_pct:+.2f}%) | 涨停 {zt_px:.2f}元 / 跌停 {dt_px:.2f}元")
    print(f"`{action_msg}`")
    return 0


def format_cli_report(eval_res: dict[str, Any], premarket: bool) -> str:
    thr = eval_res["threshold"]
    sd_s = str(eval_res.get("sig_date", "")).replace("-", "/")
    bd_s = str(eval_res.get("buy_date", "")).replace("-", "/")
    ev = eval_res["evaluated"]
    passed = eval_res["passed"]
    lines = [f"【四进五 V22.0 RD048 SJ114】{bd_s} (信号基准日 {sd_s} | 门槛 {thr} 分 / 硬锁 {MIN_4TO5_THRESHOLD} 分 | {'盘前预检' if premarket else '09:25实时'})"]
    if not ev:
        lines.append("结论: 今日全市场无 10cm 非 ST 四连板候选标的。")
        return "\n".join(lines)
    if passed:
        top = passed[0]
        lines.append(f"结论: 过线 {len(passed)} 只，第 5 顺位空仓补位优选 {top['code']} {top['name']}（{top['score']}分 | 高开 {top['open_pct']*100:+.2f}% | 异动空间 {top['hr_pit']*100:.1f}%）。")
    elif premarket:
        n_wait = sum(1 for r in ev if r["score"] > -500)
        if n_wait == 0:
            lines.append(f"结论: 盘前扫出 {len(ev)} 只四连板候选但已全部被前置门否决（无待竞价候选）。")
        else:
            lines.append(f"结论: 盘前扫出 {len(ev)} 只四连板候选（{n_wait}只待 09:25 甜区开盘 2.0%至7.5% 定分）。")
    else:
        lines.append(f"结论: 今日 {len(ev)} 只四连板候选全部未过线（或门禁否决 / 分数低于 {thr} 分）。")

    for r in ev:
        tox_tag = "毒丸否决" if r["has_tox_strict"] else "毒丸正常"
        reg_tag = "监管否决" if r["has_stock_reg"] else "监管正常"
        pm_tag = "午后炸板否决" if r["d4_blown_pm"] else "封板正常"
        op_txt = f"今开 {r['open_pct']*100:+.2f}%" if r["open_pct"] is not None else "待09:25"
        lines.append(
            f"  {r['code']} {r['name']} | 昨收 {r['px_d4']:.2f} | {op_txt} | 总分 {r['score']} | 状态 {r['gate_status']} | 空间 {r['hr_pit']*100:.1f}% | {tox_tag} / {reg_tag} / {pm_tag} | f47={float(r.get('f47_reb_zt_r10') or 0)*100:.1f}% | 核={int(r.get('d4_mkt_nuke_cnt') or 0)} | 同板3板={int(r.get('plate_3b_cnt') or 0)}"
        )
        if r.get("tox_hits"):
            lines.append(f"    毒丸触发: {r['tox_hits'][0]}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="四进五接力策略 V22.0 (RD048 SJ114 + E4_DtDefer) 实盘极速引擎")
    ap.add_argument("--build-cache", action="store_true", help="构建/刷新 RD048 SJ114 盘前缓存")
    ap.add_argument("--premarket", action="store_true", help="早盘盘前推演模式")
    ap.add_argument("--threshold", type=int, default=DEFAULT_4TO5_THRESHOLD, help="入围门槛（默认 114，代码级硬锁 >= 110）")
    ap.add_argument("--hold", nargs="+", metavar=("CODE", "BUY_PX"), help="持仓卖点核查：--hold CODE [BUY_PX]")
    ap.add_argument("--buy-date", type=str, default="", help="配合 --hold 指定买入日期 YYYY-MM-DD")
    ap.add_argument("--mock-open", type=str, default="", help="测试模拟开盘涨幅，如 '600814=0.045'")
    ap.add_argument("--json-only", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--date", type=str, default="", help="查询历史台账指定日期")
    ap.add_argument("--recent", type=int, default=0, help="查询历史台账最近 N 笔")
    args = ap.parse_args()

    # 最前置门槛硬锁校验
    validate_4to5_threshold(args.threshold)

    if args.hold:
        code_h = args.hold[0]
        bpx_h = float(args.hold[1]) if len(args.hold) >= 2 else None
        return run_hold_check_4to5(code_h, buy_px_arg=bpx_h, buy_date_arg=args.buy_date)

    if args.date or args.recent > 0:
        if not os.path.exists(LEDGER_CSV):
            print(f"[-] 历史台账不存在: {LEDGER_CSV}")
            return 1
        df = pd.read_csv(LEDGER_CSV)
        sub = df[df["buy_date"] == args.date] if args.date else df.sort_values("buy_date").tail(args.recent)
        cols_show = [c for c in ("buy_date", "code", "name", "buy_px", "exit_date", "net_ret", "v20_score", "is_held_3to4") if c in sub.columns]
        print(sub[cols_show].to_string(index=False))
        return 0

    if args.build_cache or not os.path.exists(CACHE_FILE):
        cache = build_premarket_cache(verbose=(not args.json_only))
        if args.build_cache:
            return 0
    else:
        cache = json.load(open(CACHE_FILE, encoding="utf-8"))

    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                k_m, v_m = pair.split("=", 1)
                mock_map[k_m.strip().zfill(6)] = float(v_m.strip())

    eval_res = evaluate_4to5_candidates(
        cache,
        threshold=args.threshold,
        premarket=args.premarket,
        mock_map=mock_map,
    )
    if args.json_only:
        print(json.dumps(eval_res, ensure_ascii=False, indent=2))
    else:
        print(format_cli_report(eval_res, premarket=args.premarket))
    return 0


if __name__ == "__main__":
    sys.exit(main())

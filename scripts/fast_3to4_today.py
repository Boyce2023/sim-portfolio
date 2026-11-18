#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_3to4_today.py — 三进四主战策略 V4.1 (V4.0买点 + XF30_7f_ge1 动态风险护利) 实盘极速决策引擎
五年零穿越验证基准 (ledger_3to4_xf30_std.csv / f1_3to4):
  标准 >=90分: 95笔 / 胜率 68.42% / 盈亏比 2.19 / 单仓 2319.09x / Cap10M 79.02x / 等权 5644.80x / 回撤 29.23% / DSR 0.9869
  S档 >=102分: 31笔 / 胜率 64.52% / 盈亏比 3.13 / 单仓 17.73x / 回撤 34.97%
V4.1 离场核心规则 (买点/22项打分/10:30突破撤单窗 100% 沿用 V4.0 不变):
  - 连板期 7 项持仓动态风险因子 (①主概念动态Elo>=135 ②昨龙虎榜机构卖出>2000万 ③昨成交额>5日均量3.5倍
    ④昨一日游席位买入 ⑤持仓新增个股监管函 ⑥沪深300昨跌>=2%或5日跌>=2.5% ⑦近10日4板+断板反包率<20%)
  - 命中 >= 1 项: 当天 13:45 后摸 +8.5% 回落护利线收紧至 +7.0%；0 命中: 保持 +5.0%
  - 未封四板弱斩与首次真阳断板免死 1 次保持不变
模式:
  1. --build-cache : 读取只读 PIT 库 + astock_community.json 构建 data/3to4_premarket_cache.json
  2. --premarket   : 早盘 09:15 前秒读盘前缓存，输出预评分、U01/U02 明细与 10:30 撤单触发价
  3. 无参默认实时  : 09:25:03 秒读缓存并发抓腾讯实时竞价，输出总分与 09:26 突破条件单指令 (10:30 撤单)
  4. --hold <CODE> : [--buy-date YYYY-MM-DD] 核查持仓股当日 7 项风险因子并打印 +8.5% 摸高价与 +7.0%/+5.0% 护利触发价
  5. --mock-open   : 模拟竞价开盘涨幅，如 '603396=0.055,002148=0.040'
  6. --date / --recent N : 查询 V4.0 历史台账 ledger_upg_3to4_std.csv 与评分明细
严禁 import yfinance (D12); SQLite 全程 file:...?mode=ro 只读; 严禁触碰 portfolio_state.json。
"""
import argparse
import contextlib
import datetime
import glob
import io
import json
import os
import re
import sqlite3
import ssl
import sys
import urllib.request
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from live_3to4_v40_engine import (
    A_DAILY,
    CACHE_FILE,
    DATA_DIR,
    DB_NOTICES,
    DB_PIT_NOTICES,
    IDX_PATH,
    KPL_5Y,
    KPL_V2,
    LHB_PATH,
    PQ_REG_TOX,
    REG_EXC,
    REG_INC,
    SIM_DIR,
    THS_DIR,
    UA,
    ZDJK_GLOB,
    _compute_plate_elo_fallback,
    build_premarket_cache,
    fetch_tencent_batch,
    query_history,
    run_live_mode,
    run_premarket,
)

LHB_SELL_PATH = f"{SIM_DIR}/backtest/2026-10-20-lhasa/lhb_sell.parquet"
RE_DAY_SURF_V41 = re.compile(
    r"(?:杭州上塘路|宜昌沿江大道|宜昌珍珠路|国泰.*宜昌|佛山绿景路|佛山季华六路|佛山季华五路|"
    r"佛山.*路|江阴.*营业部|东吴证券.*苏州|华泰证券.*苏州|国盛.*苏南|苏南分公司|开源.*西安西大街|"
    r"财通.*杭州上塘|东方财富.*昌都|消闲派)"
)
LHB_CAT_EXPLAIN_RE = re.compile(r"(?:10个交易日|30个交易日|严重异常)")
LHB_CAT_NAMES = {"自然人", "中小投资者", "其他自然人", "机构投资者", "深股通投资者", "机构", "沪股通", "投资者分类"}
SSL_CTX = ssl._create_unverified_context()


def _print_v41_exit_banner() -> None:
    print("\n【三进四 V4.1 现行定版离场铁律 (XF30_7f_ge1)】")
    print("  1. 未封四板：沿用 V4.0 规则，仅当买日收阳不跌且次日高开 >= +0.5% 留至收盘，否则次日 09:25 斩仓。")
    print("  2. 封死四板连板期：13:45 后曾摸 +8.5% 时触发回落护利监控；首次真阳（收>开且收>=昨收）断板免死 1 次不变。")
    print("  3. 7项持仓动态风险因子开关（满足 >= 1 项收紧至 +7.0%，0 命中保持 +5.0%）：")
    print("     ①主概念动态Elo>=135 | ②昨龙虎榜机构卖出>2000万 | ③昨成交额>5日均量3.5倍 | ④昨一日游席位买入")
    print("     ⑤持仓新增个股监管函 | ⑥沪深300昨跌>=2%或5日跌>=2.5% | ⑦近10日4板+断板反包率<20%")
    print("  4. 实盘持仓复核：python3.13 sim-portfolio/scripts/fast_3to4_today.py --hold <CODE> [--buy-date YYYY-MM-DD]")


def _fetch_sina_kline(symbol: str, datalen: int = 25) -> list[dict]:
    url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
    try:
        txt = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=3, context=SSL_CTX).read().decode("utf-8", "ignore")
        i, j = txt.find("["), txt.rfind("]")
        if i >= 0 and j > i:
            return [{"day": str(r["day"])[:10], "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]), "close": float(r["close"]), "vol": float(r.get("volume", 0) or 0)} for r in json.loads(txt[i : j + 1])]
    except Exception:
        pass
    return []


def _query_lhb_prev(c6: str, d_prev: str) -> tuple[float, float, list[str], str]:
    """返回 (inst_sell_amt, inst_buy_amt, buy_seats, source_tag)，严格对齐单日主榜。"""
    def _pick_tid(rows: list[tuple]) -> tuple[list[tuple], list[tuple]]:
        by_tid = defaultdict(list)
        meta = {}
        for tid, exp, dept, b_v, s_v in rows:
            exp_s, dept_s = str(exp or ""), str(dept or "").strip()
            if LHB_CAT_EXPLAIN_RE.search(exp_s) or dept_s in LHB_CAT_NAMES:
                continue
            tid_s = str(tid or "")
            is3 = "连续" in exp_s
            by_tid[tid_s].append((dept_s, float(b_v or 0.0), float(s_v or 0.0)))
            cur = meta.get(tid_s)
            if cur is None:
                meta[tid_s] = [is3, float(b_v or 0.0) + float(s_v or 0.0)]
            else:
                cur[1] += float(b_v or 0.0) + float(s_v or 0.0)
        if not meta:
            return [], []
        best_tid = min(meta.items(), key=lambda kv: (1 if kv[1][0] else 0, -kv[1][1], kv[0]))[0]
        return by_tid[best_tid], []

    rows_all = []
    for p_pq, side_col in [(LHB_PATH, "BUY"), (LHB_SELL_PATH, "SELL")]:
        if os.path.exists(p_pq):
            try:
                cols = ["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL", "EXPLANATION", "TRADE_ID"]
                df_l = pd.read_parquet(p_pq, columns=cols)
                sub = df_l[(df_l["TRADE_DATE"].astype(str).str[:10] == d_prev) & (df_l["SECURITY_CODE"].astype(str).str[:6].str.zfill(6) == c6)]
                for r in sub.itertuples(index=False):
                    rows_all.append((r.TRADE_ID, r.EXPLANATION, r.OPERATEDEPT_NAME, r.BUY, r.SELL))
            except Exception:
                pass
    if rows_all:
        chosen, _ = _pick_tid(rows_all)
        inst_s = sum(s for nm, _, s in chosen if "机构专用" in nm)
        inst_b = sum(b for nm, b, _ in chosen if "机构专用" in nm)
        b_seats = [nm for nm, b, _ in chosen if b > 0]
        return inst_s, inst_b, b_seats, "local_parquet"

    onl_rows = []
    for side in ("BUY", "SELL"):
        url = (
            f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_BILLBOARD_DAILYDETAILS{side}"
            f"&columns=TRADE_DATE,SECURITY_CODE,OPERATEDEPT_NAME,BUY,SELL,EXPLANATION,TRADE_ID"
            f"&filter=(SECURITY_CODE%3D%22{c6}%22)&sortColumns=TRADE_DATE&sortTypes=-1&pageNumber=1&pageSize=60&source=WEB&client=WEB"
        )
        try:
            js = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=4, context=SSL_CTX).read().decode("utf-8", "ignore"))
            for it in (js.get("result") or {}).get("data") or []:
                if str(it.get("TRADE_DATE", ""))[:10] == d_prev:
                    onl_rows.append((it.get("TRADE_ID", ""), it.get("EXPLANATION", ""), it.get("OPERATEDEPT_NAME", ""), it.get("BUY", 0), it.get("SELL", 0)))
        except Exception:
            pass
    if onl_rows:
        chosen, _ = _pick_tid(onl_rows)
        inst_s = sum(s for nm, _, s in chosen if "机构专用" in nm)
        inst_b = sum(b for nm, b, _ in chosen if "机构专用" in nm)
        b_seats = [nm for nm, b, _ in chosen if b > 0]
        return inst_s, inst_b, b_seats, "eastmoney_api"
    return 0.0, 0.0, [], "none"


def run_hold_check_3to4(raw_code: str, buy_date: str = "") -> None:
    c6 = str(raw_code).strip().zfill(6)
    sym = ("sh" if c6.startswith("6") else "sz") + c6
    quotes = fetch_tencent_batch([c6])
    q = quotes.get(c6, {})
    stk_kl = _fetch_sina_kline(sym, datalen=25)
    csi_kl = _fetch_sina_kline("sh000300", datalen=20)

    today_str = datetime.date.today().isoformat()
    q_dt = q.get("q_dt", "")
    target_dt = q_dt if (q_dt and q.get("price", 0) > 0) else today_str
    past_bars = [b for b in stk_kl if b["day"] < target_dt]
    d_prev = past_bars[-1]["day"] if past_bars else (stk_kl[-1]["day"] if stk_kl else "")
    pre_c = float(q.get("pre_c") or 0.0) if q_dt == target_dt else float(q.get("price") or 0.0)
    if pre_c <= 0 and past_bars:
        pre_c = past_bars[-1]["close"]
    name = q.get("name", c6)

    # 加载近50天A股非ST日线（供因子①③⑦）
    cutoff = (pd.Timestamp(target_dt) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    df_a = ds.dataset(A_DAILY, format="parquet").scanner(
        columns=["date", "ticker", "open", "high", "low", "close", "amount"],
        filter=(ds.field("date") >= pd.Timestamp(cutoff)) & (ds.field("date") <= pd.Timestamp(d_prev or target_dt)),
    ).to_table().to_pandas()
    df_a["c6"] = df_a["ticker"].astype(str).str[:6]
    df_a = df_a[df_a["c6"].str.startswith(("00", "60")) & (~df_a["ticker"].astype(str).str.endswith(".BJ"))].copy()
    df_a["dt_str"] = df_a["date"].dt.strftime("%Y-%m-%d")
    df_a.sort_values(["c6", "dt_str"], inplace=True)
    df_a.drop_duplicates(["c6", "dt_str"], keep="first", inplace=True)
    g = df_a.groupby("c6")
    df_a["pre_c"] = g["close"].shift(1)
    df_a["pct"] = df_a["close"] / df_a["pre_c"] - 1.0
    df_a["zt_px"] = np.floor(df_a["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df_a["is_zt"] = (df_a["close"] >= df_a["zt_px"] - 0.011) & (df_a["pct"] >= 0.095) & (df_a["pre_c"] > 0)
    df_a["touch_zt"] = (df_a["high"] >= df_a["zt_px"] - 0.011) & (df_a["pre_c"] > 0)
    df_a["is_yizi"] = df_a["is_zt"] & (df_a["open"] >= df_a["zt_px"] - 0.011) & (df_a["low"] >= df_a["zt_px"] - 0.011)
    s_zt = df_a["is_zt"].astype(int)
    df_a["streak"] = s_zt.groupby([df_a["c6"], (s_zt != g["is_zt"].shift(fill_value=False)).cumsum()]).cumsum() * s_zt
    max_a_dt = df_a["dt_str"].max() if not df_a.empty else ""

    # 1) 主概念动态 Elo >= 135
    plate_elo_map = {}
    c1_p = f"{DATA_DIR}/1to2_premarket_cache.json"
    if os.path.exists(c1_p):
        try:
            c1 = json.load(open(c1_p, encoding="utf-8"))
            if c1.get("d1_date") == d_prev and c1.get("theme_board"):
                plate_elo_map = {tb["plate"]: float(tb["elo"]) for tb in c1["theme_board"]}
        except Exception:
            pass
    if not plate_elo_map and d_prev:
        plate_elo_map = _compute_plate_elo_fallback(df_a, d_prev)

    stock_plates = []
    for kp in (KPL_5Y, KPL_V2):
        if os.path.exists(kp):
            with open(kp, encoding="utf-8") as f:
                for ln in f:
                    if not ln.strip():
                        continue
                    try:
                        obj = json.loads(ln)
                        dt_k = obj.get("date", "")
                        if dt_k and dt_k <= d_prev:
                            for pl in obj.get("plates", []):
                                pn = pl.get("plate", "")
                                if pn and any(str(s[0]).strip()[:6].zfill(6) == c6 for s in pl.get("stocks", [])):
                                    stock_plates.append((dt_k, pn))
                    except Exception:
                        pass
    latest_plate = max(stock_plates, key=lambda x: x[0])[1] if stock_plates else ""
    if not latest_plate and os.path.exists(f"{THS_DIR}/{d_prev}.json"):
        for s in json.load(open(f"{THS_DIR}/{d_prev}.json", encoding="utf-8")).get("stocks", []):
            if str(s.get("code", "")).zfill(6) == c6:
                latest_plate = str(s.get("reason_type", "")).split("+")[0].strip()
                break
    elo_val = float(plate_elo_map.get(latest_plate, 100.0)) if latest_plate else 100.0
    f1_hit = elo_val >= 135.0

    # 2) & 4) 昨龙虎榜机构卖出 > 2000万 / 一日游买入
    inst_sell, inst_buy, b_seats, lhb_src = _query_lhb_prev(c6, d_prev)
    f2_hit = (inst_sell > 2e7) or ((inst_sell - inst_buy) > 2e7)
    surf_hits = [s for s in b_seats if RE_DAY_SURF_V41.search(s)]
    f4_hit = len(surf_hits) > 0

    # 3) 昨成交额 > 5日均量 3.5 倍
    sub_c = df_a[df_a["c6"] == c6].sort_values("dt_str")
    vr_val, vr_src = 1.0, "none"
    if not sub_c.empty and sub_c.iloc[-1]["dt_str"] == d_prev and len(sub_c) >= 3:
        amt_prev = float(sub_c.iloc[-1]["amount"])
        ma5_amt = float(sub_c.iloc[-6:-1]["amount"].mean())
        vr_val = amt_prev / max(1.0, ma5_amt)
        vr_src = "a_daily_amt"
    elif len(past_bars) >= 3:
        v_prev = float(past_bars[-1]["vol"])
        v_ma5 = float(np.mean([b["vol"] for b in past_bars[-6:-1]]))
        vr_val = v_prev / max(1.0, v_ma5)
        vr_src = "sina_vol_fallback"
    f3_hit = vr_val > 3.5

    # 5) 持仓新增个股监管函
    win_lo = f"{buy_date} 09:25:00" if buy_date else (pd.Timestamp(target_dt) - pd.Timedelta(days=7)).strftime("%Y-%m-%d 09:25:00")
    win_hi = f"{target_dt} 09:25:00"
    reg_hits = []
    for db_p in (DB_NOTICES, DB_PIT_NOTICES):
        if os.path.exists(db_p):
            con = sqlite3.connect(f"file:{db_p}?mode=ro", uri=True)
            try:
                cc, cd, tb = ("sec_code", "pub_datetime_cst", "notices") if "cninfo" in db_p else ("code", "ndate", "notice")
                for pdt, ti in con.execute(f"SELECT {cd}, title FROM {tb} WHERE {cc} = ? AND {cd} >= ? AND {cd} < ?", (c6, win_lo[:10], win_hi)):
                    ts_s, ti_s = str(pdt), str(ti or "")
                    if len(ts_s) == 10:
                        ts_s += " 00:00:00"
                    if win_lo <= ts_s < win_hi and any(w in ti_s for w in REG_INC) and not any(w in ti_s for w in REG_EXC):
                        reg_hits.append(f"{ts_s[:16]} {ti_s[:28]}")
            finally:
                con.close()
    if os.path.exists(PQ_REG_TOX):
        try:
            rt = pd.read_parquet(PQ_REG_TOX, columns=["sec_code", "pub_datetime_cst", "title"])
            rt = rt[rt["sec_code"].astype(str).str[:6].str.zfill(6) == c6]
            for pdt, ti in zip(rt["pub_datetime_cst"].astype(str), rt["title"].astype(str)):
                if win_lo <= pdt < win_hi and any(w in ti for w in REG_INC) and not any(w in ti for w in REG_EXC):
                    reg_hits.append(f"{pdt[:16]} {ti[:28]}")
        except Exception:
            pass
    for zf in glob.glob(ZDJK_GLOB):
        try:
            for it in json.load(open(zf, encoding="utf-8")).get("List", []):
                dt_z = str(it[2])[:10]
                if str(it[0]).zfill(6) == c6 and win_lo[:10] <= dt_z < win_hi[:10]:
                    reg_hits.append(f"{dt_z} 重点监控")
        except Exception:
            pass
    try:
        ann_url = f"https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=20&page_index=1&ann_type=A&stock_list={c6}"
        ann_js = json.loads(urllib.request.urlopen(urllib.request.Request(ann_url, headers=UA), timeout=3, context=SSL_CTX).read().decode("utf-8", "ignore"))
        for it in (ann_js.get("data") or {}).get("list") or []:
            nd = str(it.get("notice_date") or "")[:19]
            ti_s = str(it.get("title") or "")
            if win_lo[:10] <= nd[:10] <= win_hi[:10] and any(w in ti_s for w in REG_INC) and not any(w in ti_s for w in REG_EXC):
                reg_hits.append(f"{nd[:10]} {ti_s[:28]}")
    except Exception:
        pass
    reg_hits = sorted(set(reg_hits))
    f5_hit = len(reg_hits) > 0

    # 6) 沪深300昨跌 >= 2% 或 5日跌 >= 2.5%
    csi_bars = [b for b in csi_kl if b["day"] <= d_prev]
    if len(csi_bars) < 6 and os.path.exists(IDX_PATH):
        cm = json.load(open(IDX_PATH, encoding="utf-8")).get("sh000300", {})
        csi_bars = [{"day": k, "close": float(v)} for k, v in sorted(cm.items()) if k <= d_prev][-15:]
    csi_1d = (csi_bars[-1]["close"] / csi_bars[-2]["close"] - 1.0) if len(csi_bars) >= 2 else 0.0
    csi_5d = (csi_bars[-1]["close"] / csi_bars[-6]["close"] - 1.0) if len(csi_bars) >= 6 else 0.0
    f6_hit = (csi_1d <= -0.020) or (csi_5d <= -0.025)

    # 7) 近10日4板+断板反包率 < 20%
    st_set = set()
    if os.path.exists(f"{DATA_DIR}/st_universe.json"):
        st_set = {str(x)[:6].zfill(6) for x in json.load(open(f"{DATA_DIR}/st_universe.json", encoding="utf-8")).get("codes", [])}
    df_nonst = df_a[~df_a["c6"].isin(st_set)].copy()
    df_nonst["prev_streak"] = df_nonst.groupby("c6")["streak"].shift(1).fillna(0).astype(int)
    prev_brk = set()
    reb_hist = []
    for _, grp in df_nonst.groupby("dt_str", sort=True):
        if prev_brk:
            sub_r = grp[grp["c6"].isin(prev_brk)]
            reb_hist.append((int((sub_r["pct"] > 0).sum()), len(prev_brk)))
        else:
            reb_hist.append((0, 0))
        ge4_brk = grp[(grp["prev_streak"] >= 4) & (~grp["is_zt"])]
        prev_brk = set(ge4_brk["c6"].tolist())
    w10 = reb_hist[-10:]
    reb_n, reb_d = sum(x[0] for x in w10), sum(x[1] for x in w10)
    reb_r10 = reb_n / max(1, reb_d)
    f7_hit = reb_r10 < 0.20

    hits = [f1_hit, f2_hit, f3_hit, f4_hit, f5_hit, f6_hit, f7_hit]
    risk_pts = sum(int(x) for x in hits)
    guard_pct = 0.070 if risk_pts >= 1 else 0.050
    p_arm = round(pre_c * 1.085, 2)
    p_70 = round(pre_c * 1.070, 2)
    p_50 = round(pre_c * 1.050, 2)
    p_guard = p_70 if risk_pts >= 1 else p_50
    zt_p = float(q.get("zt_px") or np.floor(pre_c * 1.10 * 100.0 + 0.5) / 100.0)

    print("=" * 90)
    print(f"【三进四 V4.1 持仓动态风险因子与护利触发价核查】 {c6} {name} | 核查日={target_dt} (前收日={d_prev})")
    print(f"昨收: {pre_c:.2f}元 | 今开: {q.get('open', 0):.2f}元 ({q.get('open_pct', 0)*100:+.2f}%) | 现价: {q.get('price', 0):.2f}元 | 涨停价: {zt_p:.2f}元")
    print("-" * 90)
    print(f"  ① 主概念动态Elo>=135       : [{'HIT' if f1_hit else 'OK '}] 板块={latest_plate or '未匹配'} | Elo={elo_val:.1f}")
    print(f"  ② 昨龙虎榜机构卖出>2000万   : [{'HIT' if f2_hit else 'OK '}] 机构卖={inst_sell/1e4:.1f}万 净卖={(inst_sell-inst_buy)/1e4:.1f}万 (源:{lhb_src})")
    print(f"  ③ 昨成交额>5日均量3.5倍    : [{'HIT' if f3_hit else 'OK '}] 量比={vr_val:.2f}x (源:{vr_src})")
    print(f"  ④ 昨一日游席位买入         : [{'HIT' if f4_hit else 'OK '}] 命中={len(surf_hits)}家 {surf_hits[:2]}")
    print(f"  ⑤ 持仓新增个股监管函       : [{'HIT' if f5_hit else 'OK '}] 窗[{win_lo[:10]}~{win_hi[:10]}) 命中={len(reg_hits)}条 {reg_hits[:1]}")
    print(f"  ⑥ 沪深300昨跌>=2%/5日>=2.5%: [{'HIT' if f6_hit else 'OK '}] 1日={csi_1d*100:+.2f}% | 5日={csi_5d*100:+.2f}%")
    print(f"  ⑦ 近10日4板+断板反包率<20% : [{'HIT' if f7_hit else 'OK '}] {reb_n}/{reb_d}={reb_r10*100:.1f}% (库截止={max_a_dt})")
    print("-" * 90)
    print(f"`风险分={risk_pts}/7 | 今日13:45后摸 +8.5% ({p_arm:.2f}元) 激活，回落跌破 {'+7.0%收紧线' if risk_pts>=1 else '+5.0%宽松线'} ({p_guard:.2f}元) 且未封板立即止盈！`")
    print(f"对照参考: +8.5%激活={p_arm:.2f}元 | +7.0%收紧={p_70:.2f}元 | +5.0%宽松={p_50:.2f}元 | 首次真阳(收>开且>={pre_c:.2f})断板免死1次不变")
    print("=" * 90)


def main():
    parser = argparse.ArgumentParser(description="三进四主战策略 V4.1 (V4.0买点+7因子护利) 实盘极速决策引擎")
    parser.add_argument("--build-cache", action="store_true", help="构建/刷新盘前特征缓存")
    parser.add_argument("--premarket", action="store_true", help="输出早盘盘前 V4.1 推演面板")
    parser.add_argument("--hold", type=str, default="", help="核查持仓股当日7项风险因子与+8.5%/+7.0%/+5.0%护利价")
    parser.add_argument("--buy-date", type=str, default="", help="可选：配合--hold指定买入日期 (YYYY-MM-DD)")
    parser.add_argument("--mock-open", type=str, default="", help="模拟竞价开盘涨幅，如 '603396=0.055,002148=0.040'")
    parser.add_argument("--date", type=str, default="", help="查询历史台账指定买日 (YYYY-MM-DD)")
    parser.add_argument("--recent", type=int, default=0, help="查询历史台账最近 N 笔")
    args = parser.parse_args()

    if args.hold:
        run_hold_check_3to4(args.hold, buy_date=args.buy_date)
        return

    if args.date or args.recent > 0:
        query_history(date_str=args.date, recent_n=args.recent)
        return

    if args.build_cache:
        build_premarket_cache(verbose=True)
        return

    if not os.path.exists(CACHE_FILE):
        print("[*] 盘前缓存不存在，自动触发构建...")
        build_premarket_cache(verbose=True)

    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)

    if args.premarket:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            run_premarket(cache)
        out = buf.getvalue().replace("【三进四主战策略 V4.0 (互学瘦身正式版)", "【三进四主战策略 V4.1 (V4.0买点 + XF30_7f_ge1动态护利)")
        print(out, end="")
        _print_v41_exit_banner()
        return

    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                mock_map[k.strip()] = float(v.strip())

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        run_live_mode(cache, mock_open_map=mock_map)
    out = buf.getvalue().replace("【三进四主战策略 V4.0 极速决策引擎】", "【三进四主战策略 V4.1 极速决策引擎】")
    print(out, end="")
    _print_v41_exit_banner()


if __name__ == "__main__":
    main()

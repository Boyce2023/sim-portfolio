#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
live_daily_question_builder.py
A股「一进二」每日实时实战真题双阶段极速生成器（盘前预制底座 + 09:25:03 秒级出题）
- Stage 1 (--premarket): 16:35 / 08:50 读取 1to2_premarket_cache.json + 本地日线/微盘口/上证指数，
  预制「待 09:25 竞价补齐」题干 HTML，并把全部静态 K 线与候选池打包进 live_premarket_bundle.json。
- Stage 2 (--auction): 09:25:03 零 Parquet / 零 SQLite，仅读 live_premarket_bundle.json + 1 次腾讯批量 HTTP
  拉取 09:25 真实集合竞价开盘价，100% 复刻 fast_1to2_today.py V19 生产打分（含空仓低位候补轨、规则 α/β/γ 与 11:30 午休撤单触发价），
  0.5 秒内原子刷新「今日实时实战题」免密版与口令版 HTML！
安全红线：严禁 import yfinance；所有 SQLite 连接强制 mode=ro (uri=True)；绝不触碰 portfolio_state.json。
"""
import os
import sys
import re
import json
import time
import random
import sqlite3
import datetime
import argparse
import urllib.request
from collections import defaultdict, Counter

import numpy as np
import pandas as pd

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

CURR_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{PROJECT_ROOT}/sim-portfolio"
CLEAN_DIR = f"{SIM_DIR}/backtest/2026-11-11-1to2-clean"
if CLEAN_DIR not in sys.path:
    sys.path.insert(0, CLEAN_DIR)
from clean_wf_1to2_v14_ironclad_master import A_DAILY_PATH

ASSETS_DIR = os.path.join(CURR_DIR, "assets")
DATA_5Y_DIR = os.path.join(CURR_DIR, "data_5y")
DELIVERY_DIR = os.path.join(CURR_DIR, "最新交付题库")

CACHE_PATH = f"{SIM_DIR}/data/1to2_premarket_cache.json"
PARQUET_8Y_PATH = A_DAILY_PATH
TAPE_DB_PATH = f"{SIM_DIR}/data/zt_micro_tape_5y_pit.db"
KPL_5Y_PATH = f"{SIM_DIR}/data/kpl_plates_5y_2021_2026_complete.jsonl"
SH_PKL_PATH = os.path.join(ASSETS_DIR, "astock2_sh_daily.pkl")
SH_JS_PATH = os.path.join(ASSETS_DIR, "astock2_sh_series.js")

BUNDLE_PATH = os.path.join(DATA_5Y_DIR, "live_premarket_bundle.json")
LIVE_CASE_JSON = os.path.join(DATA_5Y_DIR, "trainer_live_today.json")
DESKTOP_QUIZ_DIR = "/Users/huaichuaibeimeng/Desktop/短线/题目"
OUT_HTML_UNLOCKED = os.path.join(DELIVERY_DIR, "今日题.html")

if ASSETS_DIR not in sys.path:
    sys.path.insert(0, ASSETS_DIR)

from trainer_assembler_v16 import (
    MAIN_CONTAINER_HTML,
    load_static_assets,
    customize_for_live_today,
    build_unlocked_html_content,
)
from live_daily_tiers_builder import build_extra_premarket_static
from live_daily_tiers_scorer import assemble_extra_live_sections

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
EARN_PAT = re.compile(r"(业绩|预增|扭亏|季报|年报|半年报|分红)")
NON_THEME = {
    "年报增长", "业绩增长", "中报增长", "ST板块", "其他",
    "次新股", "半年报增长", "三季报增长", "公告", "一季报增长",
}


def fetch_tencent_daily_klines(q_symbol: str, count: int = 40) -> list:
    """用腾讯日线接口补齐最新日 K 线（优先 HTTPS 直连免代理，防 HTTP 501）"""
    for proto in ("https", "http"):
        url = f"{proto}://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={q_symbol},day,,,{count},qfq"
        for attempt in range(2):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                raw = _DIRECT_OPENER.open(req, timeout=5).read().decode("utf-8", errors="ignore")
                j = json.loads(raw)
                dat = j.get("data", {}).get(q_symbol, {})
                rows = dat.get("qfqday") or dat.get("day") or []
                out = []
                for r in rows:
                    if len(r) >= 6:
                        dt_s = str(r[0])[:10]
                        o, c, h, l, v = float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])
                        out.append((dt_s, o, h, l, c, v))
                if out:
                    return out
            except Exception as e:
                if proto == "http" and attempt == 1:
                    print(f"  [warn] Tencent kline fetch failed for {q_symbol}: {e}")
                time.sleep(0.15)
    return []


def fetch_sina_daily_klines(q_symbol: str, count: int = 40) -> list:
    """新浪日线直连兜底接口（当腾讯日线单票抖动或未结账时瞬时补位）"""
    url = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/var/"
        f"CN_MarketDataService.getKLineData?symbol={q_symbol}&scale=240&ma=no&datalen={count}"
    )
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            txt = _DIRECT_OPENER.open(req, timeout=4).read().decode("utf-8", errors="ignore")
            i, j = txt.find("["), txt.rfind("]")
            if i >= 0 and j > i:
                rows = json.loads(txt[i:j + 1])
                out = []
                for r in rows:
                    dt_s = str(r["day"])[:10]
                    o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
                    v_shares = float(r.get("volume", 0.0))
                    out.append((dt_s, o, h, l, c, v_shares))
                if out:
                    return out
        except Exception:
            time.sleep(0.2)
    return []


def fetch_tencent_rt_d1_bar(q_symbol: str, d1_date: str):
    """盘后16:40若日线接口尚未结转D1首板蜡烛，用腾讯实时快照精准补齐D1真实K线"""
    try:
        url = f"http://qt.gtimg.cn/q={q_symbol}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = _DIRECT_OPENER.open(req, timeout=3).read().decode("gbk", errors="ignore")
        if '="' not in raw:
            return None
        f = raw.split('="', 1)[1].strip('";\n').split("~")
        if len(f) > 35:
            ts = str(f[30])[:8]
            dt_s = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) == 8 else ""
            c, o, h, l = float(f[3] or 0), float(f[5] or 0), float(f[33] or 0), float(f[34] or 0)
            v_shares = float(f[36] or 0) * 100.0
            if dt_s == d1_date and c > 0 and o > 0 and h >= max(o, c) - 0.01 and 0 < l <= min(o, c) + 0.01:
                return (dt_s, round(o, 2), round(h, 2), round(l, 2), round(c, 2), round(v_shares, 0))
    except Exception:
        pass
    return None


def validate_single_kline(kl: list, expected_close_d1: float, c6: str, name: str) -> tuple[bool, str]:
    """六维数学硬门禁：根数、非平线、OHLC几何合法性、非零成交量、以及最后一根收盘价对齐D1首板昨收"""
    if not kl or len(kl) < 5:
        return False, f"{c6} {name} K线不足5根(仅{len(kl) if kl else 0}根)"
    lows, highs = [], []
    for idx, b in enumerate(kl):
        if len(b) < 5:
            return False, f"{c6} {name} 第{idx}根字段残缺"
        o, h, l, c, v = float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4])
        if l <= 0 or c <= 0 or o <= 0 or h < max(o, c) - 0.02 or l > min(o, c) + 0.02:
            return False, f"{c6} {name} 第{idx}根OHLC几何越界({b})"
        lows.append(l)
        highs.append(h)
    if max(highs) <= min(lows) and len(kl) >= 3:
        return False, f"{c6} {name} 退化为假平线"
    if expected_close_d1 > 0:
        last_c = float(kl[-1][3])
        if abs(last_c - expected_close_d1) / expected_close_d1 > 0.018:
            return False, f"{c6} {name} 末根K线收盘({last_c})与D1首板收盘({expected_close_d1})错位(漏D1蜡烛或复权错乱)"
    return True, "OK"


def update_sh_index_up_to(d1_date: str):
    """确保 astock2_sh_daily.pkl 与 astock2_sh_series.js 100% 包含 d1_date"""
    df_sh = pd.read_pickle(SH_PKL_PATH)
    df_sh["date_str"] = df_sh["date"].dt.strftime("%Y-%m-%d")
    df_sh = df_sh.sort_values("date").drop_duplicates("date_str", keep="last").reset_index(drop=True)
    max_dt = df_sh["date_str"].iloc[-1]

    if max_dt < d1_date:
        tc_rows = fetch_tencent_daily_klines("sh000001", count=30)
        new_recs = []
        for dt_s, o, h, l, c, v_shou in tc_rows:
            if max_dt < dt_s <= d1_date:
                new_recs.append({
                    "date": pd.Timestamp(dt_s),
                    "open": o, "high": h, "low": l, "close": c,
                    "volume": v_shou * 100.0, "date_str": dt_s,
                })
        if not any(r["date_str"] == d1_date for r in new_recs):
            rt_sh = fetch_tencent_rt_d1_bar("sh000001", d1_date)
            if rt_sh:
                new_recs.append({
                    "date": pd.Timestamp(rt_sh[0]),
                    "open": rt_sh[1], "high": rt_sh[2], "low": rt_sh[3], "close": rt_sh[4],
                    "volume": rt_sh[5], "date_str": rt_sh[0],
                })
        if new_recs:
            df_add = pd.DataFrame(new_recs)
            df_sh = pd.concat([df_sh, df_add], ignore_index=True)
            df_sh = df_sh.sort_values("date").drop_duplicates("date_str", keep="last").reset_index(drop=True)
            df_sh.drop(columns=["date_str"]).to_pickle(SH_PKL_PATH)

    closes = df_sh["close"].astype(float)
    ma5 = closes.rolling(5, min_periods=1).mean()
    ma20 = closes.rolling(20, min_periods=1).mean()
    ma60 = closes.rolling(60, min_periods=1).mean()

    series_arr, sh_rows_5, sh_date_to_idx = [], [], {}
    for idx, r in enumerate(df_sh.itertuples()):
        dt_s = r.date_str
        sh_date_to_idx[dt_s] = idx
        vol_yi = round(float(r.volume) / 1e8, 1)
        series_arr.append([
            dt_s, round(float(r.open), 1), round(float(r.high), 1),
            round(float(r.low), 1), round(float(r.close), 1), vol_yi,
            round(float(ma5.iloc[idx]), 1), round(float(ma20.iloc[idx]), 1), round(float(ma60.iloc[idx]), 1),
        ])
        sh_rows_5.append([
            round(float(r.open), 2), round(float(r.high), 2),
            round(float(r.low), 2), round(float(r.close), 2), vol_yi,
        ])

    need_js_sync = (max_dt < d1_date) or (not os.path.exists(SH_JS_PATH))
    if not need_js_sync:
        with open(SH_JS_PATH, "r", encoding="utf-8") as f_chk:
            if f'"{d1_date}"' not in f_chk.read():
                need_js_sync = True
    if need_js_sync:
        js_txt = (
            "// Auto-synced SH_INDEX_SERIES up to " + df_sh["date_str"].iloc[-1] + "\n"
            "const SH_INDEX_SERIES = " + json.dumps(series_arr, ensure_ascii=False, separators=(",", ":")) + ";\n"
            "const SH_DATE_INDEX = {};\n"
            "for (let i = 0; i < SH_INDEX_SERIES.length; i++) {\n"
            "    SH_DATE_INDEX[SH_INDEX_SERIES[i][0]] = i;\n"
            "}\n"
        )
        tmp_js = SH_JS_PATH + ".tmp"
        with open(tmp_js, "w", encoding="utf-8") as f:
            f.write(js_txt)
        os.replace(tmp_js, SH_JS_PATH)

    d1_idx = sh_date_to_idx.get(d1_date, len(sh_rows_5) - 1)
    idx_bars = sh_rows_5[max(0, d1_idx - 29): d1_idx + 1]
    return idx_bars, series_arr[-1][0]


def select_top3_live_themes(cands: list, theme_board: list, next_dt: str):
    """从盘前候选池选出今日最具实战代表性的 3 个题材（优先 >=2 只非一字首板，不足则按主线规模/纯洁分补齐）"""
    tb_map = {t["plate"]: t for t in theme_board}
    valid_cands = [
        c for c in cands
        if (not c.get("is_st"))
        and (not c.get("is_yizi"))
        and (c.get("plate") not in NON_THEME)
        and (not c.get("is_event_basket"))
        and (not EARN_PAT.search(str(c.get("plate", ""))))
    ]
    if len(valid_cands) < 3:
        # 极端兜底：放宽事件筐过滤以保证至少能出题
        valid_cands = [c for c in cands if (not c.get("is_st")) and (not c.get("is_yizi")) and c.get("plate") != "其他"]

    plate_cands = defaultdict(list)
    for c in valid_cands:
        plate_cands[c["plate"]].append(c)

    def _plate_sort_key(p: str):
        cl = plate_cands[p]
        tb = tb_map.get(p, {})
        has_high_pot = any(x.get("purifier_ok") and x.get("static_tot", 0) >= 200.0 for x in cl)
        has_multi = len(cl) >= 2
        rk_th = min(int(x.get("rk_theme", 99)) for x in cl)
        p_sz = max(int(x.get("p_sz", 1)) for x in cl)
        best_static = max(float(x.get("static_tot", 0.0)) for x in cl)
        t_sc = float(tb.get("score", max(float(x.get("theme_score", 100.0)) for x in cl)))
        return (
            1 if has_high_pot else 0,
            1 if has_multi else 0,
            1 if rk_th <= 3 else 0,
            p_sz >= 2,
            best_static if len(cl) == 1 else t_sc,
            t_sc,
        )

    sorted_plates = sorted(plate_cands.keys(), key=_plate_sort_key, reverse=True)
    chosen_plates = sorted_plates[:3]

    rng = random.Random(f"astock2_live_{next_dt}")
    rng.shuffle(chosen_plates)

    chosen_map = {}
    for p in chosen_plates:
        pool = sorted(plate_cands[p], key=lambda x: float(x.get("static_tot", 0.0)), reverse=True)
        if len(pool) > 4:
            picked = pool[:3] + [pool[-1]]
        else:
            picked = pool
        picked_shuffled = list(picked)
        rng.shuffle(picked_shuffled)
        chosen_map[p] = picked_shuffled

    return chosen_plates, chosen_map, plate_cands


def load_static_enrichment(d1_date: str, chosen_plates: list, chosen_c6s: list, cache_cands_ref: list = ()):
    """在盘前阶段一次性读取 K 线、首封炸板封单、KPL 涨停原因与 10 日题材热度、D1 最高连板高度"""
    # 1. D1 首封、炸板、封单额（只读 SQLite + 同花顺当日涨停池归档）
    tape_info = {}
    if chosen_c6s and os.path.exists(TAPE_DB_PATH):
        try:
            conn = sqlite3.connect(f"file:{TAPE_DB_PATH}?mode=ro", uri=True)
            ph = ",".join(["?"] * len(chosen_c6s))
            rows = conn.execute(
                f"SELECT sec_code, first_seal_time, seal_amount, open_board_count FROM zt_micro_tape WHERE trade_date = ? AND sec_code IN ({ph})",
                (d1_date, *chosen_c6s),
            ).fetchall()
            conn.close()
            for sc, fst, samt, obc in rows:
                tape_info[str(sc)[:6]] = {
                    "first_seal_time": str(fst or ""),
                    "seal_amount": float(samt or 0.0),
                    "open_board_count": int(obc) if obc is not None else -1,
                }
        except Exception as e:
            print(f"  [warn] tape db read error: {e}")

    max_height_d1 = 2
    ths_p = f"{SIM_DIR}/data/ths_limit_up_daily/{d1_date}.json"
    if os.path.exists(ths_p):
        try:
            ths_j = json.load(open(ths_p, encoding="utf-8"))
            for it in ths_j.get("stocks", []):
                c6_t = str(it.get("code", ""))[:6]
                ht_txt = str(it.get("high_days", "") or "")
                m_ht = re.findall(r"(\d+)\s*板", ht_txt)
                if m_ht:
                    max_height_d1 = max(max_height_d1, int(m_ht[-1]))
                if c6_t in chosen_c6s and c6_t not in tape_info:
                    fts = it.get("first_limit_up_time")
                    fstr = datetime.datetime.fromtimestamp(int(fts)).strftime("%H:%M:%S") if fts else ""
                    samt = float(it.get("order_amount") or it.get("limit_up_order_amount") or 0.0)
                    obc = int(it.get("open_num") or 0)
                    tape_info[c6_t] = {
                        "first_seal_time": fstr,
                        "seal_amount": samt,
                        "open_board_count": obc,
                    }
        except Exception as e:
            print(f"  [warn] ths json read error: {e}")

    # 2. KPL 10 日题材热度与涨停细分逻辑 r_long
    r_long_map = {}
    plate_daily_sz = defaultdict(dict)
    kpl_dates = []
    if os.path.exists(KPL_5Y_PATH):
        try:
            with open(KPL_5Y_PATH, "r", encoding="utf-8") as f:
                for ln in f:
                    if not ln.strip():
                        continue
                    d = json.loads(ln)
                    dt = d.get("date", "")
                    if dt <= d1_date:
                        kpl_dates.append(dt)
                        for p in d.get("plates", []):
                            pname = p.get("plate", "")
                            stks = p.get("stocks", [])
                            plate_daily_sz[dt][pname] = len(stks)
                            if dt == d1_date:
                                for s in stks:
                                    c6_s = str(s[0]).strip()[:6].zfill(6)
                                    rl = str(s[3]).strip() if len(s) > 3 else ""
                                    r_long_map[c6_s] = rl
        except Exception as e:
            print(f"  [warn] kpl read error: {e}")

    # 补充检查 news-dashboard 当日 KPL 快照（若 KPL_5Y 尚未合并 d1_date）
    kpl_daily_dir = f"{PROJECT_ROOT}/news-dashboard/data/kpl_daily"
    kpl_d1_file = os.path.join(kpl_daily_dir, f"{d1_date}.json")
    if d1_date not in plate_daily_sz and os.path.exists(kpl_d1_file):
        try:
            kd = json.load(open(kpl_d1_file, encoding="utf-8"))
            kpl_dates.append(d1_date)
            for p in kd.get("plates", []):
                pname = p.get("plate", "")
                stks = p.get("stocks", [])
                plate_daily_sz[d1_date][pname] = len(stks)
                for s in stks:
                    c6_s = str(s[0]).strip()[:6].zfill(6)
                    rl = str(s[3]).strip() if len(s) > 3 else ""
                    r_long_map[c6_s] = rl
        except Exception:
            pass

    kpl_dates = sorted(set(kpl_dates))
    heat_bars_map = {}
    for p in chosen_plates:
        if kpl_dates:
            recent_dts = kpl_dates[-10:]
            hb = [int(plate_daily_sz[dt].get(p, 0)) for dt in recent_dts]
            if len(hb) < 10:
                hb = [0] * (10 - len(hb)) + hb
            heat_bars_map[p] = hb
        else:
            heat_bars_map[p] = [1] * 10

    # 3. 候选股前 20 日 K 线（优先 0.2s 本地 PyArrow 日线库 -> 缺失才走新浪/腾讯日线 + D1实时快照补齐 + 六维硬校验）
    cand_close_map = {str(c.get("c6", "")): float(c.get("pre_c", 0.0)) for c in cache_cands_ref}
    klines_map = {}
    if chosen_c6s and os.path.exists(PARQUET_8Y_PATH):
        import pyarrow.dataset as _ds
        tks = [f"{c}.SH" if c.startswith("6") else f"{c}.SZ" for c in chosen_c6s] + [f"{c}.SS" for c in chosen_c6s if c.startswith("6")]
        d_lo = pd.Timestamp(d1_date) - pd.Timedelta(days=65)
        df_p = _ds.dataset(PARQUET_8Y_PATH, format="parquet").scanner(
            columns=["ticker", "date", "open", "high", "low", "close", "volume"],
            filter=(_ds.field("ticker").isin(tks)) & (_ds.field("date") >= d_lo) & (_ds.field("date") <= pd.Timestamp(d1_date)),
        ).to_table().to_pandas()
        if not df_p.empty:
            df_p["c6"] = df_p["ticker"].astype(str).str[:6]
            df_p["dt_str"] = pd.to_datetime(df_p["date"]).dt.strftime("%Y-%m-%d")
            df_p = df_p.sort_values(["c6", "dt_str"]).drop_duplicates(["c6", "dt_str"], keep="last")
            for c6, grp in df_p.groupby("c6"):
                if grp["dt_str"].iloc[-1] == d1_date and len(grp) >= 5:
                    rows_kl = [
                        [round(float(r.open), 2), round(float(r.high), 2), round(float(r.low), 2), round(float(r.close), 2), round(float(r.volume), 0)]
                        for r in grp.tail(20).itertuples()
                    ]
                    ok_kl, _ = validate_single_kline(rows_kl, cand_close_map.get(c6, 0.0), c6, c6)
                    if ok_kl:
                        klines_map[c6] = rows_kl

    for c6 in [x for x in chosen_c6s if x not in klines_map]:
        q_sym = ("sh" if c6.startswith("6") else "sz") + c6
        exp_c = cand_close_map.get(c6, 0.0)
        bars_raw = [b for b in fetch_sina_daily_klines(q_sym, count=35) if b[0] <= d1_date]
        is_sh_unit = False
        if not bars_raw or bars_raw[-1][0] < d1_date:
            tc_bars = [b for b in fetch_tencent_daily_klines(q_sym, count=35) if b[0] <= d1_date]
            if tc_bars and (not bars_raw or tc_bars[-1][0] >= bars_raw[-1][0]):
                bars_raw = tc_bars
                is_sh_unit = True
        if bars_raw and bars_raw[-1][0] < d1_date:
            rt_b = fetch_tencent_rt_d1_bar(q_sym, d1_date)
            if rt_b:
                conv = [
                    (b[0], b[1], b[2], b[3], b[4], b[5] * 100.0 if is_sh_unit else b[5])
                    for b in bars_raw
                ]
                conv.append(rt_b)
                bars_raw = conv
                is_sh_unit = False
        if len(bars_raw) >= 5 and bars_raw[-1][0] == d1_date:
            cand_kl = [
                [round(b[1], 2), round(b[2], 2), round(b[3], 2), round(b[4], 2), round(b[5] * (100.0 if is_sh_unit else 1.0), 0)]
                for b in bars_raw[-20:]
            ]
            ok_kl, _ = validate_single_kline(cand_kl, exp_c, c6, c6)
            if ok_kl:
                klines_map[c6] = cand_kl

    # 4. 板块历史成分股在 D1 的平均涨跌幅（PyArrow 仅扫近 15 日切片，毫秒级完成）
    plate_members = defaultdict(set)
    if os.path.exists(KPL_5Y_PATH):
        try:
            with open(KPL_5Y_PATH, "r", encoding="utf-8") as f:
                for ln in f:
                    if not ln.strip():
                        continue
                    d = json.loads(ln)
                    dt = d.get("date", "")
                    if dt <= d1_date:
                        for p in d.get("plates", []):
                            pname = p.get("plate", "")
                            if pname in chosen_plates:
                                for s in p.get("stocks", []):
                                    plate_members[pname].add(str(s[0]).strip()[:6].zfill(6))
        except Exception:
            pass

    d1_plate_avg = {}
    all_mem_c6 = sorted({c6 for s in plate_members.values() for c6 in s})
    mem_d1_ret = {}
    if all_mem_c6 and os.path.exists(PARQUET_8Y_PATH):
        try:
            import pyarrow.dataset as _ds2
            d_m_lo = pd.Timestamp(d1_date) - pd.Timedelta(days=15)
            df_m = _ds2.dataset(PARQUET_8Y_PATH, format="parquet").scanner(
                columns=["ticker", "date", "close"],
                filter=(_ds2.field("date") >= d_m_lo) & (_ds2.field("date") <= pd.Timestamp(d1_date)),
            ).to_table().to_pandas()
            df_m["c6"] = df_m["ticker"].astype(str).str[:6]
            df_m = df_m[df_m["c6"].isin(all_mem_c6)].copy()
            df_m["dt_str"] = pd.to_datetime(df_m["date"]).dt.strftime("%Y-%m-%d")
            df_m = df_m.sort_values(["c6", "dt_str"]).drop_duplicates(["c6", "dt_str"], keep="last")
            df_m["prev_c"] = df_m.groupby("c6")["close"].shift(1)
            df_d1 = df_m[df_m["dt_str"] == d1_date]
            for r in df_d1.itertuples():
                if pd.notna(r.prev_c) and r.prev_c > 0:
                    mem_d1_ret[r.c6] = (float(r.close) / float(r.prev_c) - 1.0) * 100.0
        except Exception:
            pass
    if not mem_d1_ret and all_mem_c6:
        try:
            q_syms = [("sh" if c.startswith("6") else "sz") + c for c in all_mem_c6[:450]]
            for idx_q in range(0, len(q_syms), 65):
                u_q = "http://qt.gtimg.cn/q=" + ",".join(q_syms[idx_q:idx_q + 65])
                raw_q = _DIRECT_OPENER.open(urllib.request.Request(u_q, headers={"User-Agent": "Mozilla/5.0"}), timeout=3).read().decode("gbk", "ignore")
                for ln_q in raw_q.strip().splitlines():
                    if '="' not in ln_q: continue
                    pq = ln_q.split('="', 1)[1].split("~")
                    if len(pq) > 35 and str(pq[30])[:8] == d1_date.replace("-", ""):
                        mem_d1_ret[pq[2].strip()[:6]] = float(pq[32] or 0.0)
        except Exception:
            pass

    for p in chosen_plates:
        mems = list(plate_members.get(p, []))
        vals = [mem_d1_ret[c6] for c6 in mems if c6 in mem_d1_ret]
        if vals:
            avg_v = round(float(np.mean(vals)), 2)
            d1_plate_avg[p] = {
                "pct": avg_v,
                "cnt": len(vals),
                "str": f"{avg_v:+.2f}% ({len(vals)}只成分股)",
            }
        else:
            d1_plate_avg[p] = {
                "pct": 10.0,
                "cnt": 0,
                "str": "昨日首板涨停梯队",
            }

    return {
        "tape_info": tape_info,
        "r_long_map": r_long_map,
        "heat_bars_map": heat_bars_map,
        "klines_map": klines_map,
        "d1_plate_avg": d1_plate_avg,
        "max_height_d1": max_height_d1,
    }


def score_auction_candidates(cache_obj: dict, live_quotes: dict | None):
    """
    若 live_quotes 为 None，返回盘前预制态 (premarket)；
    若提供 live_quotes ({c6: {pre, open, high, low, cur}})，100% 复刻 fast_1to2_today.py V19 裁决！
    """
    cands = [dict(c) for c in cache_obj.get("candidates", [])]
    mkt = cache_obj.get("mkt_sentiment", {})
    theme_struct = cache_obj.get("theme_structure", {})

    d1_seal_rate = float(mkt.get("d1_1to2_seal_rate", 0.55))
    promo_ma5 = float(mkt.get("d1_1to2_promo_ma5", 0.20))
    d1_zt_cnt = int(mkt.get("d1_zt_cnt", 50))
    fallback_climax_pen = (-15.0 if d1_zt_cnt >= 100 else (-10.0 if d1_zt_cnt >= 95 else 0.0)) - (10.0 if d1_seal_rate >= 0.80 else 0.0)
    sc_climax_pen = float(mkt.get("climax_pen", fallback_climax_pen))
    tot_thr = float(mkt.get("tot_thr", 329.8 if d1_seal_rate > 0.75 else 304.8))
    roll20_ho_zt = float(mkt.get("roll20_ho_zt", 0.45))
    is_monday = bool(cache_obj.get("is_monday", False))
    promo_freeze = promo_ma5 < 0.13

    if live_quotes is None:
        for c in cands:
            pre = float(c.get("pre_c", 0.0))
            zt_p = float(np.floor(pre * 1.10 * 100 + 0.5) / 100)
            c["zt_p"] = zt_p
            c["open_p"] = 0.0
            c["o_pct"] = 0.0
            c["d2_is_yizi"] = False
            c["is_buyable_open"] = bool(c.get("gate_ok", False))
            c["trig_p"] = min(zt_p, round(pre * 1.065, 2))
            c["tot"] = float(c.get("static_tot", 0.0))
            c["s_quant"] = float(c.get("s_q_base", 0.0))
            c["ok"] = False
            c["rank_sv"] = float(c.get("static_tot", 0.0))
            c["true_buy_rk"] = 99
            c["theme_open_rk"] = 99
            c["mkt_open_rk"] = 99
            c["open_lead"] = 0.0
            c["front_lock_cnt"] = 0
            c["plate_d2_yizi_cnt"] = 0
        return cands, {
            "prev_zt_auc_avg": 0.0,
            "nuclear_halt": False,
            "promo_freeze": promo_freeze,
            "mkt_yizi_cnt": 0,
            "tot_thr": tot_thr,
            "roll20_ho_zt": roll20_ho_zt,
            "is_monday": is_monday,
        }

    scripts_dir = f"{SIM_DIR}/scripts"
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from fast_1to2_today import evaluate_1to2_v19_df

    df, meta_out = evaluate_1to2_v19_df(cache_obj, live_quotes)
    if df.empty:
        return [], {
            "prev_zt_auc_avg": 0.0,
            "nuclear_halt": False,
            "promo_freeze": promo_freeze,
            "mkt_yizi_cnt": 0,
            "tot_thr": tot_thr,
            "roll20_ho_zt": roll20_ho_zt,
            "is_monday": is_monday,
        }
    df["is_fallback_track"] = df["fb_dom295"].astype(bool)
    df["track_label"] = np.where(df["track_label"] == "V19暗牌候补fb_dom295", "V19暗牌低位候补轨", df["track_label"])
    scored_list = df.to_dict(orient="records")
    return scored_list, {
        "prev_zt_auc_avg": float(meta_out["prev_zt_auc_avg"]),
        "nuclear_halt": bool(meta_out["nuclear_halt"]),
        "promo_freeze": bool(meta_out["promo_freeze"]),
        "mkt_yizi_cnt": int(df["d2_is_yizi"].sum()),
        "tot_thr": float(meta_out["tot_thr"]),
        "roll20_ho_zt": roll20_ho_zt,
        "is_monday": bool(meta_out["is_monday"]),
    }

def assemble_live_case_dict(cache_obj: dict, bundle: dict, scored_cands: list, auc_meta: dict, live_stage: str, live_quotes: dict | None = None):
    """将打分结果组装为与 trainer_frontend_v16.js 100% 兼容的单个实时关卡 JSON"""
    d1_date = cache_obj["d1_date"]
    next_dt = cache_obj["next_dt"]
    d1_w = WEEKDAYS[datetime.date.fromisoformat(d1_date).weekday()]
    d2_w = WEEKDAYS[datetime.date.fromisoformat(next_dt).weekday()]
    is_mon = bool(auc_meta["is_monday"])
    win_hi = 0.088 if is_mon else 0.078
    win_lo = 0.020 if is_mon else 0.022

    cand_by_c6 = {c["c6"]: c for c in scored_cands}
    plate_all_map = defaultdict(list)
    for c in scored_cands:
        if not c.get("is_st"):
            plate_all_map[c["plate"]].append(c)

    chosen_plates = bundle["chosen_plates"]
    chosen_c6_by_plate = bundle["chosen_c6_by_plate"]
    enrich = bundle["enrichment"]
    tape_info = enrich["tape_info"]
    r_long_map = enrich["r_long_map"]
    heat_bars_map = enrich["heat_bars_map"]
    klines_map = enrich["klines_map"]
    d1_plate_avg = enrich["d1_plate_avg"]
    tb_map = {t["plate"]: t for t in cache_obj.get("theme_board", [])}

    # 计算题面全部入选候选股的 sys_rank
    flat_case_cands = []
    for p in chosen_plates:
        for c6 in chosen_c6_by_plate[p]:
            if c6 in cand_by_c6:
                flat_case_cands.append(cand_by_c6[c6])

    flat_sorted = sorted(
        flat_case_cands,
        key=lambda x: (1 if x.get("ok") else 0, float(x.get("rank_sv", x.get("tot", 0.0)))),
        reverse=True,
    )
    cand_to_sysrank = {x["c6"]: idx + 1 for idx, x in enumerate(flat_sorted)}

    # 全市场 V19 最终唯一头名（即使不在当前选中的某张卡，也在揭晓卡完整展示）
    all_winners = sorted(
        [x for x in scored_cands if x.get("ok")],
        key=lambda x: float(x.get("rank_sv", x.get("tot", 0.0))),
        reverse=True,
    )
    global_winner = all_winners[0] if all_winners else None

    themes_json = []
    all_built_cands = []
    opt_letters = ["A", "B", "C", "D"]

    for p_idx, p in enumerate(chosen_plates):
        full_p = plate_all_map.get(p, [])
        non_yz_p = sorted([x for x in full_p if not x.get("d2_is_yizi")], key=lambda x: float(x.get("o_pct", -0.99)), reverse=True)
        in_win_p = sorted(
            [x for x in non_yz_p if x.get("is_buyable_open") and (win_lo <= float(x.get("o_pct", -0.99)) <= win_hi)],
            key=lambda x: float(x.get("o_pct", -0.99)),
            reverse=True,
        )

        # 该卡候选内部竞价排名（raw_rk[0]）
        card_cands = [cand_by_c6[c6] for c6 in chosen_c6_by_plate[p] if c6 in cand_by_c6]
        card_sorted_open = sorted(card_cands, key=lambda x: float(x.get("o_pct", -0.99)), reverse=True)
        card_rk_map = {x["c6"]: i + 1 for i, x in enumerate(card_sorted_open)}
        card_top1_o = float(card_sorted_open[0]["o_pct"]) if card_sorted_open else 0.0
        card_top2_o = float(card_sorted_open[1]["o_pct"]) if len(card_sorted_open) >= 2 else None

        built_cands = []
        for opt_i, c in enumerate(card_cands):
            opt = opt_letters[opt_i]
            c6 = c["c6"]
            code_full = c.get("ticker") or (f"{c6}.SH" if c6.startswith("6") else f"{c6}.SZ")
            csrc_raw = str(c.get("csrc_ind", ""))
            csrc_clean = re.sub(r"^[A-Z]\d+", "", csrc_raw).strip()[:8] or "精选行业"
            r_sh = str(c.get("r_short") or p)
            r_lg = str(r_long_map.get(c6, ""))
            base_logic = f"{r_sh} · {r_lg}" if (r_lg and r_lg != r_sh and len(r_lg) <= 42) else r_sh
            notice_Brief = ""
            if c.get("notice_titles"):
                notice_Brief = f" | 公告:{str(c['notice_titles'][0])[:22]}"

            raw_desc = f"{base_logic} [主业:{csrc_clean}]{notice_Brief}"
            desc = raw_desc
            if c.get("is_pure_outsider"):
                desc += " 【硬科技题材配传统主业：扣20分】"
            if c.get("notice_hard") or c.get("is_ma"):
                desc += " 【盘前合同或并购公告：先验+18分】"
            if c.get("has_ir"):
                desc += " 【近8日披露机构调研：+5分】"
            if c.get("is_pioneer_word") or c.get("has_new_term") or c.get("own_new"):
                desc += " 【近15日首现细分词：+15分】"
            if c.get("clean_brk60"):
                desc += " 【创60日新高首板】"
            if c.get("notice_bad"):
                desc += " 【盘前业绩或风险提示公告：扣35分并拦截】"
            if c.get("lhb_bad_seat"):
                desc += " 【龙虎榜含拉萨或一日游席位】"
            if int(c.get("xq_cnt_pre", 0) or 0) >= 4:
                desc += f" 【盘前雪球热帖过热({int(c.get('xq_cnt_pre', 0))}帖)】"
            if c.get("is_fallback_track"):
                desc += " 【触发V19低位暗牌候补轨】"

            blind_desc = desc.replace(c["name"], "该司")
            raw_blind_desc = raw_desc.replace(c["name"], "该司")

            tp = tape_info.get(c6, {})
            b_cnt = int(tp.get("open_board_count", -1))
            fst = str(tp.get("first_seal_time", ""))
            fst_hhmm = fst[:5] if (fst and fst != "99:99:99" and len(fst) >= 5) else "日线封板"
            amt_wan = int(round(float(tp.get("seal_amount", 0.0)) / 10000.0))
            tight = round(float(c.get("d1_tightness", 45.0)), 1)
            vr_val = float(c.get("vol_ratio", 1.5))
            seal_str = "缩量硬板" if vr_val <= 1.8 else ("放量换手板" if vr_val >= 2.6 else "震荡封板")

            if b_cnt < 0:
                raw_d1_board = f"{seal_str} · 紧密度{tight:.0f}分"
            else:
                b_txt = "0次炸板" if b_cnt == 0 else f"开板{b_cnt}次"
                raw_d1_board = f"{fst_hhmm}首封 · {b_txt}"
            raw_d1_seal = f"封单{amt_wan}万 · {seal_str}" if amt_wan > 0 else f"紧密度{tight:.0f}分 · {seal_str}"

            o_pct_dec = float(c.get("o_pct", 0.0))
            o_pct_val = round(o_pct_dec * 100.0, 2)
            pre_c = float(c.get("pre_c", 0.0))
            trig_p = float(c.get("trig_p", round(pre_c * 1.065, 2)))

            if live_stage == "premarket":
                front_yz_cnt, front_ov_cnt, yz_peers = 0, 0, []
                rk_arr = [0, 0]
                raw_rk_str = "待09:25排位"
                raw_lead = 0.0
                raw_lead_str = "待09:25"
                raw_trig_str = f"保底{round(pre_c*1.065,2):.2f}元(+6.5%) · 待竞价定"
            else:
                ahead_lim = max(win_hi, o_pct_dec)
                yz_peers = [x["name"] for x in full_p if x.get("d2_is_yizi") and x["c6"] != c6]
                ov_peers = [x["name"] for x in full_p if (not x.get("d2_is_yizi")) and float(x.get("o_pct", -0.99)) > ahead_lim and x["c6"] != c6]
                front_yz_cnt = len(yz_peers)
                front_ov_cnt = len(ov_peers)

                c_rk = card_rk_map.get(c6, 1)
                m_rk = int(c.get("mkt_open_rk", 99)) if np.isfinite(c.get("mkt_open_rk", 99)) else 99
                rk_arr = [c_rk, m_rk]
                if c.get("d2_is_yizi"):
                    raw_rk_str = "一字涨停开盘(不可买)"
                else:
                    raw_rk_str = f"同卡竞价第{c_rk}名 / 全场第{m_rk}名"

                if len(card_cands) == 1:
                    if len(non_yz_p) >= 2:
                        peer_o = [float(x["o_pct"]) for x in non_yz_p if x["c6"] != c6][0]
                        raw_lead = round((o_pct_dec - peer_o) * 100.0, 2)
                        raw_lead_str = f"较同题材次席 {raw_lead:+.2f}%"
                    else:
                        raw_lead = 0.0
                        raw_lead_str = "板块唯一非一字首板"
                elif c_rk == 1 and card_top2_o is not None:
                    raw_lead = round((o_pct_dec - card_top2_o) * 100.0, 2)
                    raw_lead_str = f"领先第2名 +{raw_lead:.2f}%"
                else:
                    raw_lead = round((o_pct_dec - card_top1_o) * 100.0, 2)
                    raw_lead_str = f"较第1名 {raw_lead:.2f}%"

                do_direct = is_mon and float(c.get("tot", 0.0)) >= 310.0 and float(c.get("open_lead", 0.0)) >= 0.025
                if c.get("d2_is_yizi"):
                    raw_trig_str = f"{c.get('open_p', trig_p):.2f}元 · 一字封死无买点"
                elif do_direct:
                    raw_trig_str = f"{c.get('open_p', trig_p):.2f}元 ({o_pct_val:+.1f}%) · 周一竞价直买"
                else:
                    trig_gain = (trig_p / pre_c - 1.0) * 100.0 if pre_c > 0 else 6.5
                    raw_trig_str = f"{trig_p:.2f}元 (+{trig_gain:.1f}%) · 11:30前条件单"

            kl = klines_map.get(c6)
            ok_kl, msg_kl = validate_single_kline(kl, pre_c, c6, c["name"])
            if not ok_kl:
                raise RuntimeError(f"K-line gate blocked output: {msg_kl} (flat/stale dummy fallback strictly forbidden)")
            is_winner_stock = bool(global_winner and global_winner["c6"] == c6)

            cd_obj = {
                "opt": opt,
                "code": code_full,
                "name": c["name"],
                "theme": p,
                "desc": desc,
                "blind_desc": blind_desc,
                "raw_desc": raw_desc,
                "raw_blind_desc": raw_blind_desc,
                "mcap": round(float(c.get("mcap", 0.0)), 1),
                "d1_turn": round(float(c.get("to", 0.0)), 2),
                "d1_amt": round(float(c.get("amount_yi", 0.0)), 2),
                "vr": f"{vr_val:.2f}倍",
                "seal": seal_str,
                "dd20": round((float(c.get("dd20_d0", 1.0)) - 1.0) * 100.0, 1),
                "zt20": int(c.get("zt_cnt_pre20", 0)),
                "pre_d1": round(float(c.get("d0_pct", 0.0)) * 100.0, 2),
                "o_pct": o_pct_val,
                "close_d1": round(pre_c, 2),
                "csrc_ind": csrc_clean,
                "is_outsider_pen": bool(c.get("is_pure_outsider", False)),
                "blast_count": b_cnt,
                "first_seal_hhmm": fst_hhmm,
                "seal_amt_wan": amt_wan,
                "tightness": tight,
                "is_hard_turnover": bool(c.get("is_ht", False)),
                "d1_board_detail": raw_d1_board,
                "d1_seal_detail": raw_d1_seal,
                "raw_d1_board": raw_d1_board,
                "raw_d1_seal": raw_d1_seal,
                "pos20_pct": int(np.clip(round(float(c.get("pos20_d0", 0.5)) * 100.0), 0, 100)),
                "in_buy_window": bool(win_lo <= o_pct_dec <= win_hi) if live_stage != "premarket" else False,
                "rk": rk_arr,
                "raw_rk": rk_arr,
                "rk_detail_str": raw_rk_str,
                "raw_rk_str": raw_rk_str,
                "lead": raw_lead,
                "raw_lead": raw_lead,
                "lead_detail_str": raw_lead_str,
                "raw_lead_str": raw_lead_str,
                "trig_str": raw_trig_str,
                "raw_trig_str": raw_trig_str,
                "front_yizi_cnt": front_yz_cnt,
                "front_over_cnt": front_ov_cnt,
                "front_lock_cnt": front_yz_cnt + front_ov_cnt,
                "front_yizi_names": yz_peers,
                "v16_tot_score": round(float(c.get("tot", c.get("static_tot", 0.0))), 1),
                "s_prior_wk": round(float(c.get("s_prior_wk", 0.0)), 1),
                "s_quant": round(float(c.get("s_quant", c.get("s_q_base", 0.0))), 1),
                "static_tot": round(float(c.get("static_tot", 0.0)), 1),
                "need_auc": int(c.get("need_auc", 0)),
                "purifier_ok": bool(c.get("purifier_ok", False)),
                "buy_price": round(trig_p, 2),
                "sell_price": round(trig_p, 2),
                "exit_date": next_dt,
                "exit_reason": "盘中实时跟踪中（15:05 收盘后揭晓二板封板结果）",
                "net_ret": 0.0,
                "executed": False,
                "is_sealed": False,
                "final_height": 1,
                "sys_rank": cand_to_sysrank.get(c6, 99),
                "sys_pass": is_winner_stock,
                "cand_ok": bool(c.get("ok", False)),
                "gate_ok": bool(c.get("gate_ok", False)),
                "pm_comment": "",
                "klines": kl,
                "d2": None,
                "d3": None,
                "theme_idx": p_idx,
            }
            built_cands.append(cd_obj)
            all_built_cands.append(cd_obj)

        tb = tb_map.get(p, {})
        sample_c = card_cands[0]
        rk_th = int(sample_c.get("rk_theme", 99))
        elo_rk = rk_th if rk_th < 99 else int(tb.get("elo_rk", p_idx + 1))
        elo_sc = round(float(sample_c.get("p_theme_med") or sample_c.get("s_prior_dual") or tb.get("score", 100.0)), 1)
        p_sz = int(tb.get("sz") or sample_c.get("p_sz", len(full_p)))
        sub_cnt = max([int(x.get("sub_cluster_cnt", 1)) for x in card_cands] or [1])

        if live_stage == "premarket":
            flc_th, yz_th, hi_th = 0, 0, 0
            raw_escort = "待 09:25 竞价生成"
            avg_open_str = "待 09:25 竞价生成"
        else:
            yz_th = sum(1 for x in full_p if x.get("d2_is_yizi"))
            flc_th = sum(1 for x in full_p if x.get("d2_is_yizi") or float(x.get("o_pct", -0.99)) > win_hi)
            hi_th = sum(1 for x in full_p if float(x.get("o_pct", -0.99)) >= 0.020)
            avg_o = (np.mean([float(x.get("o_pct", 0.0)) for x in full_p]) * 100.0) if full_p else 0.0
            over_cnt = max(0, flc_th - yz_th)
            raw_escort = f"今一字 {yz_th} 只 · 高开超{win_hi*100:.1f}%共 {over_cnt} 只"
            avg_open_str = f"{avg_o:+.2f}% (高开>=2%共{hi_th}只)"

        p_avg_info = d1_plate_avg.get(p, {"pct": 0.0, "cnt": 0, "str": "--"})
        themes_json.append({
            "idx": p_idx,
            "name": p,
            "elo_rank": elo_rk,
            "elo_score": elo_sc,
            "first_boards": p_sz,
            "p_sz": p_sz,
            "sub_cluster_cnt": sub_cnt,
            "front_lock_cnt": flc_th,
            "plate_yizi_cnt": yz_th,
            "high_open_cnt": hi_th,
            "term_type": f"同细分分支最多 {sub_cnt} 只涨停",
            "raw_term_type": f"同细分分支最多 {sub_cnt} 只涨停",
            "escort": raw_escort,
            "raw_escort": raw_escort,
            "avg_open": avg_open_str,
            "purifier_warn": "",
            "heat_bars": heat_bars_map.get(p, [1] * 10),
            "d1_plate_avg_pct": p_avg_info["pct"],
            "d1_plate_mem_cnt": p_avg_info["cnt"],
            "d1_plate_avg_str": p_avg_info["str"],
            "cands": built_cands,
        })

    # 汇总量化定式最终拍板结论
    if live_stage == "premarket":
        top_pre = max(all_built_cands, key=lambda x: x["static_tot"])
        sys_cand_code = ""
        sys_cand_opt = ""
        sys_cand_theme_idx = -1
        sys_cand_name = f"待 09:25 竞价裁决（盘前静态最高：{top_pre['name']} {top_pre['static_tot']:.0f}分，需竞价补 {top_pre['need_auc']}分）"
    elif global_winner is not None:
        w_c6 = global_winner["c6"]
        matched_ui = next((x for x in all_built_cands if x["code"][:6] == w_c6), None)
        sys_cand_code = global_winner.get("ticker") or (f"{w_c6}.SH" if w_c6.startswith("6") else f"{w_c6}.SZ")
        sys_cand_opt = matched_ui["opt"] if matched_ui else ""
        sys_cand_theme_idx = matched_ui["theme_idx"] if matched_ui else -1
        trk_note = f" · {global_winner['track_label']}" if global_winner.get("track_label") == "V19暗牌低位候补轨" else ""
        sys_cand_name = (
            f"{global_winner['name']}（{global_winner['plate']}{trk_note} · 总分 {global_winner['tot']:.1f} >= {auc_meta['tot_thr']:.1f} · "
            f"触发11:30前点火挂单 {global_winner['trig_p']:.2f}元）"
        )
    else:
        top1_live = max(scored_cands, key=lambda x: float(x.get("tot", -999.0)))
        sys_cand_code = ""
        sys_cand_opt = ""
        sys_cand_theme_idx = -1
        reason_extra = ""
        if auc_meta["nuclear_halt"]:
            reason_extra = "，昨首板竞价均幅为负触发核按钮空仓"
        elif auc_meta["promo_freeze"]:
            reason_extra = "，近5日晋级率<13%触发冰点熔断"
        if float(top1_live["tot"]) >= float(auc_meta["tot_thr"]):
            o_p = float(top1_live.get("o_pct", 0.0)) * 100.0
            veto_why = f"竞价 {o_p:+.2f}% 未进 2.2%~7.8% 标准买窗或板块承接未过硬门槛"
            sys_cand_name = f"今日量化空仓休息（最高分 {top1_live['name']} {top1_live['tot']:.1f}分虽过分值线，但因{veto_why}拦截）"
        else:
            sys_cand_name = f"今日量化空仓休息（最高分 {top1_live['name']} {top1_live['tot']:.1f}分 < 门槛 {auc_meta['tot_thr']:.1f}分{reason_extra}）"

    mkt_s = cache_obj.get("mkt_sentiment", {})
    sent_zt = int(mkt_s.get("d1_zt_cnt", 50))
    sent_dt = int(mkt_s.get("d1_dt_cnt", 5))
    sent_first = sum(1 for c in cache_obj.get("candidates", []) if not c.get("is_yizi"))
    sent_promo = f"{float(mkt_s.get('d1_1to2_seal_rate', 0.55)) * 100.0:.1f}%"
    sent_height = f"{int(enrich.get('max_height_d1', 2))} 连板"
    sent_open = "待09:25竞价" if live_stage == "premarket" else f"{auc_meta['prev_zt_auc_avg'] * 100.0:+.2f}%"
    promo_ma5_raw = f"{float(mkt_s.get('d1_1to2_promo_ma5', 0.20)) * 100.0:.1f}%"

    ts = cache_obj.get("theme_structure", {})
    rule_notes = []
    if ts.get("is_dominant_t1"):
        rule_notes.append(f"规则α：断层主线【{ts.get('dom_t1_plate')}】无过线头名时禁退选第3题材")
    if ts.get("is_melee"):
        rule_notes.append("规则β：三题材混战日须卡全场竞价前二或硬催化")
    if auc_meta["roll20_ho_zt"] < 0.45 and not is_mon:
        rule_notes.append("规则γ：近20日高开封板偏冷(<3.5%扣25分)")

    extra_sections = None
    if bundle.get("extra_static"):
        extra_sections = assemble_extra_live_sections(bundle["extra_static"], live_quotes, live_stage)

    return {
        "id": 1,
        "is_live_case": True,
        "has_eod_result": False,
        "live_stage": live_stage,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": next_dt,
        "d1_date": d1_date,
        "title": f"{next_dt} {d2_w} 实时「一进二」早盘决战局（战区一 · V19）",
        "type": "live",
        "market_ans": "PENDING",
        "market_best_theme_idx": -1,
        "market_best_ret": 0.0,
        "best_stock_code": "",
        "best_stock_name": "待今日收盘揭晓",
        "sys_cand_code": sys_cand_code,
        "sys_cand_name": sys_cand_name,
        "sys_cand_opt": sys_cand_opt,
        "sys_cand_theme_idx": sys_cand_theme_idx,
        "sys_ret": 0.0,
        "sys_beat": False,
        "sent": [sent_zt, sent_dt, sent_first, sent_promo, sent_height, sent_open],
        "promo_ma5_raw": promo_ma5_raw,
        "promo_ma5_str": promo_ma5_raw,
        "idx_bars": bundle["idx_bars"],
        "idx_d2": None,
        "themes": themes_json,
        "weekday_str": d2_w,
        "d1_weekday_str": d1_w,
        "gap_days": int(cache_obj.get("gap_days", 1)),
        "is_mon_window": is_mon,
        "window_rule_str": (" · ".join(rule_notes) if rule_notes else "常规工作日窗口 2.2%~7.8% · 11:30午休撤单") + " · V19空仓低位候补轨与M1弱斩豁免",
        "tot_thr": auc_meta["tot_thr"],
        "thr_reason_str": "高潮次日提门槛至329.8分" if auc_meta["tot_thr"] > 310 else "标准出手门槛304.8分",
        "nuclear_halt": auc_meta["nuclear_halt"],
        "promo_freeze": auc_meta["promo_freeze"],
        "mkt_yizi_cnt": auc_meta["mkt_yizi_cnt"],
        "mkt_yizi_str": f"{auc_meta['mkt_yizi_cnt']} 家",
        "extra_live_sections": extra_sections,
    }


def write_live_htmls(case_obj: dict):
    os.makedirs(DATA_5Y_DIR, exist_ok=True)
    os.makedirs(DELIVERY_DIR, exist_ok=True)

    data_arr = [case_obj]
    data_str = json.dumps(data_arr, ensure_ascii=False, separators=(",", ":"))

    tmp_json = LIVE_CASE_JSON + ".tmp"
    with open(tmp_json, "w", encoding="utf-8") as f:
        json.dump(data_arr, f, ensure_ascii=False, indent=2)
    os.replace(tmp_json, LIVE_CASE_JSON)

    fe_js, _, sh_js = load_static_assets()
    stats_key = f"astock2_live_{case_obj['date'].replace('-', '')}"
    cur_html, cur_fe = customize_for_live_today(MAIN_CONTAINER_HTML, fe_js, stats_key=stats_key)
    page_title = f"A股今日实时实战题（{case_obj['date']} {case_obj['weekday_str']} · V19.1 关注池+一进二+二进三+三进四+高标）"

    unlocked_html = build_unlocked_html_content(data_str, cur_html, cur_fe, sh_js, page_title)
    tmp_u = OUT_HTML_UNLOCKED + ".tmp"
    with open(tmp_u, "w", encoding="utf-8") as f:
        f.write(unlocked_html)
    os.replace(tmp_u, OUT_HTML_UNLOCKED)

    try:
        os.makedirs(DESKTOP_QUIZ_DIR, exist_ok=True)
        d_u = os.path.join(DESKTOP_QUIZ_DIR, "今日题.html")
        with open(d_u + ".tmp", "w", encoding="utf-8") as f:
            f.write(unlocked_html)
        os.replace(d_u + ".tmp", d_u)
    except Exception as e:
        print(f"[WARN] Desktop quiz sync skipped: {e}")


def build_premarket_bundle():
    t0 = time.time()
    if not os.path.exists(CACHE_PATH):
        raise FileNotFoundError(f"Missing premarket cache: {CACHE_PATH}")

    cache_obj = json.load(open(CACHE_PATH, encoding="utf-8"))
    d1_date = cache_obj["d1_date"]
    next_dt = cache_obj["next_dt"]
    cands = cache_obj.get("candidates", [])
    theme_board = cache_obj.get("theme_board", [])

    idx_bars, sh_latest = update_sh_index_up_to(d1_date)
    chosen_plates, chosen_map, _ = select_top3_live_themes(cands, theme_board, next_dt)
    chosen_c6_by_plate = {p: [x["c6"] for x in chosen_map[p]] for p in chosen_plates}
    all_chosen_c6s = [c6 for p in chosen_plates for c6 in chosen_c6_by_plate[p]]

    enrichment = load_static_enrichment(d1_date, chosen_plates, all_chosen_c6s, cache_cands_ref=cands)
    extra_static = build_extra_premarket_static(d1_date)
    base_q_codes = [("sh" + c["c6"] if c["c6"].startswith("6") else "sz" + c["c6"]) for c in cands]
    q_codes = sorted(set(base_q_codes) | set(extra_static.get("extra_q_codes", [])))

    bundle = {
        "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "d1_date": d1_date,
        "next_dt": next_dt,
        "chosen_plates": chosen_plates,
        "chosen_c6_by_plate": chosen_c6_by_plate,
        "q_codes": q_codes,
        "idx_bars": idx_bars,
        "sh_latest": sh_latest,
        "enrichment": enrichment,
        "extra_static": extra_static,
        "cache_obj": cache_obj,
    }

    os.makedirs(DATA_5Y_DIR, exist_ok=True)
    tmp_b = BUNDLE_PATH + ".tmp"
    with open(tmp_b, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False)
    os.replace(tmp_b, BUNDLE_PATH)

    scored_cands, auc_meta = score_auction_candidates(cache_obj, live_quotes=None)
    case_obj = assemble_live_case_dict(cache_obj, bundle, scored_cands, auc_meta, live_stage="premarket", live_quotes=None)
    write_live_htmls(case_obj)

    elapsed = time.time() - t0
    print(
        f"[premarket] OK | D1={d1_date} -> D2={next_dt} | SH_latest={sh_latest} | "
        f"Themes={chosen_plates} | Stocks={len(all_chosen_c6s)} | Elapsed={elapsed:.3f}s"
    )
    return bundle


def fetch_tencent_batch_quotes(q_codes: list) -> dict:
    if not q_codes:
        return {}
    live = {}
    for idx in range(0, len(q_codes), 65):
        chunk = q_codes[idx: idx + 65]
        url = "http://qt.gtimg.cn/q=" + ",".join(chunk)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        txt = _DIRECT_OPENER.open(req, timeout=3).read().decode("gbk", errors="ignore")
        for ln in txt.strip().splitlines():
            if '="' not in ln:
                continue
            k, v = ln.split('="', 1)
            p = v.strip('";').split("~")
            if len(p) > 45:
                op = float(p[5] or 0) or float(p[9] or 0) or float(p[3] or 0)
                lp = float(p[34] or 0) or op
                b1, s1 = float(p[10] or 0), float(p[20] or 0)
                pc = float(p[4] or 0)
                op_pct = (op / pc - 1.0) if pc > 0 else 0.0
                live[k[-6:]] = {
                    "name": p[1],
                    "pre": pc,
                    "open": op,
                    "high": float(p[33] or 0) or op,
                    "low": lp,
                    "cur": float(p[3] or 0) or op,
                    "turn": float(p[38] or 0),
                    "fmcap": float(p[44] or 0),
                    "tmcap": float(p[45] or 0),
                    "is_yizi": bool(op_pct >= 0.098 or (b1 > 0 and s1 == 0 and op_pct >= 0.090)),
                }
    return live


def run_auction_fast_complete(dry_run_bench: bool = False):
    t0 = time.time()
    cache_disk = json.load(open(CACHE_PATH, encoding="utf-8"))
    if (not os.path.exists(BUNDLE_PATH)):
        bundle = build_premarket_bundle()
    else:
        bundle = json.load(open(BUNDLE_PATH, encoding="utf-8"))
        if (bundle.get("next_dt") != cache_disk.get("next_dt")
                or bundle.get("d1_date") != cache_disk.get("d1_date")
                or ("extra_static" not in bundle)
                or ("heat_2to3" not in bundle.get("extra_static", {}))):
            bundle = build_premarket_bundle()
        else:
            bundle["cache_obj"] = cache_disk
            kl_map_chk = bundle.get("enrichment", {}).get("klines_map", {})
            c_ref_map = {str(x.get("c6", "")): float(x.get("pre_c", 0.0)) for x in cache_disk.get("candidates", [])}
            all_c6_chk = [c6 for p in bundle.get("chosen_plates", []) for c6 in bundle.get("chosen_c6_by_plate", {}).get(p, [])]
            if not all_c6_chk or any(not validate_single_kline(kl_map_chk.get(c6), c_ref_map.get(c6, 0.0), c6, c6)[0] for c6 in all_c6_chk):
                bundle = build_premarket_bundle()

    from ths_watchlist_sync import load_and_sync_watchlist
    wl_state, _ = load_and_sync_watchlist()
    wl_q = [("sh" if c.startswith("6") else "sz") + c for c in wl_state.get("codes", [])]
    q_codes = sorted(set(bundle.get("q_codes", [])) | set(wl_q))

    t_net0 = time.time()
    live_quotes = fetch_tencent_batch_quotes(q_codes)
    t_net = time.time() - t_net0

    if dry_run_bench:
        rng = random.Random(20261113)
        sim_quotes = dict(live_quotes)
        for c in bundle["cache_obj"]["candidates"]:
            pre = float(c["pre_c"])
            sim_op = round(pre * (1.0 + rng.uniform(-0.015, 0.068)), 2)
            sim_quotes[c["c6"]] = {"name": c["name"], "pre": pre, "open": sim_op, "high": sim_op, "low": sim_op, "cur": sim_op}
        scored_cands, auc_meta = score_auction_candidates(bundle["cache_obj"], sim_quotes)
        case_obj = assemble_live_case_dict(bundle["cache_obj"], bundle, scored_cands, auc_meta, live_stage="auction_ready", live_quotes=sim_quotes)
        data_str = json.dumps([case_obj], ensure_ascii=False, separators=(",", ":"))
        fe_js, _, sh_js = load_static_assets()
        cur_html, cur_fe = customize_for_live_today(MAIN_CONTAINER_HTML, fe_js, stats_key="astock2_bench")
        u_html = build_unlocked_html_content(data_str, cur_html, cur_fe, sh_js, "压测")
        with open("/tmp/live_question_bench_unlocked.html", "w", encoding="utf-8") as f:
            f.write(u_html)
        elapsed = time.time() - t0
        print(
            f"[benchmark-auction] TOTAL={elapsed:.3f}s (Tencent HTTP={t_net:.3f}s | Score+HTML={elapsed - t_net:.3f}s) | "
            f"sys_decision={case_obj['sys_cand_name']}"
        )
        return elapsed

    non_zero_opens = sum(1 for v in live_quotes.values() if v.get("open", 0) > 0)
    if len(q_codes) > 0 and non_zero_opens < max(1, len(q_codes) // 2):
        time.sleep(0.8)
        live_quotes = fetch_tencent_batch_quotes(q_codes)

    scored_cands, auc_meta = score_auction_candidates(bundle["cache_obj"], live_quotes)
    case_obj = assemble_live_case_dict(bundle["cache_obj"], bundle, scored_cands, auc_meta, live_stage="auction_ready", live_quotes=live_quotes)
    write_live_htmls(case_obj)

    elapsed = time.time() - t0
    print(
        f"[auction-live] OK | D2={case_obj['date']} | Quotes={non_zero_opens}/{len(q_codes)} | "
        f"HTTP={t_net:.3f}s | TOTAL={elapsed:.3f}s | Decision={case_obj['sys_cand_name']}"
    )
    return elapsed


def run_scheduled_0925_burst():
    """供 launchd 09:25:00 触发：精确等到 09:25:03.2 首轮生成，09:25:07.5 二次校验刷新确保零漏单"""
    now = datetime.datetime.now()
    # 周末直接跳过
    if now.weekday() >= 5:
        print("[scheduled-0925] Weekend, skip.")
        return
    target_1 = now.replace(hour=9, minute=25, second=3, microsecond=200000)
    wait_1 = (target_1 - datetime.datetime.now()).total_seconds()
    if 0 < wait_1 <= 15:
        time.sleep(wait_1)
    run_auction_fast_complete(dry_run_bench=False)

    target_2 = now.replace(hour=9, minute=25, second=7, microsecond=500000)
    wait_2 = (target_2 - datetime.datetime.now()).total_seconds()
    if 0 < wait_2 <= 10:
        time.sleep(wait_2)
        run_auction_fast_complete(dry_run_bench=False)


def repack_premarket_from_bundle():
    """直接读取已生成的 live_premarket_bundle.json 与最新 premarket cache 重新渲染盘前 HTML（秒级）"""
    t0 = time.time()
    if not os.path.exists(BUNDLE_PATH):
        return build_premarket_bundle()
    bundle = json.load(open(BUNDLE_PATH, encoding="utf-8"))
    cache_obj = json.load(open(CACHE_PATH, encoding="utf-8")) if os.path.exists(CACHE_PATH) else bundle["cache_obj"]
    bundle["cache_obj"] = cache_obj
    scored_cands, auc_meta = score_auction_candidates(cache_obj, live_quotes=None)
    case_obj = assemble_live_case_dict(cache_obj, bundle, scored_cands, auc_meta, live_stage="premarket", live_quotes=None)
    write_live_htmls(case_obj)
    elapsed = time.time() - t0
    print(f"[repack-premarket] OK | D1={cache_obj.get('d1_date')} -> D2={cache_obj.get('next_dt')} | Elapsed={elapsed:.3f}s")
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="一进二每日实时实战题双阶段极速生成器")
    parser.add_argument("--premarket", action="store_true", help="盘后16:35 / 盘前08:50 生成预制底座与待开奖 HTML")
    parser.add_argument("--repack-premarket", action="store_true", help="复用既有 live_premarket_bundle.json 秒级重生成盘前 HTML")
    parser.add_argument("--auction", action="store_true", help="09:25:03 极速拉取腾讯竞价并原地补齐今日真题 HTML")
    parser.add_argument("--auction-scheduled", action="store_true", help="09:25:00 定时唤醒，精确在 09:25:03 与 09:25:07 双重刷新")
    parser.add_argument("--benchmark", action="store_true", help="夜间端到端真实网络+评分+HTML生成耗时压测（不污染盘前HTML）")
    args = parser.parse_args()

    if args.premarket:
        build_premarket_bundle()
    elif args.repack_premarket:
        repack_premarket_from_bundle()
    elif args.auction:
        run_auction_fast_complete(dry_run_bench=False)
    elif args.auction_scheduled:
        run_scheduled_0925_burst()
    elif args.benchmark:
        run_auction_fast_complete(dry_run_bench=True)
    else:
        build_premarket_bundle()

# -*- coding: utf-8 -*-
"""
live_daily_tiers_builder.py
当日题目专属：组装「置顶关注池」「二进三(题材分卡V2.0)」「三进四(全量V4.0)」「高标(唯一第一名)」静态包
严格仅注入今日题，零触碰历史50题与5关题库。
"""
import os
import sys
import json
import subprocess
from collections import defaultdict
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ASSETS_DIR = os.path.dirname(os.path.abspath(__file__))
BACKTESTS_DIR = os.path.dirname(ASSETS_DIR)
SIM_DIR = os.path.dirname(BACKTESTS_DIR)

for _p in (BACKTESTS_DIR, ASSETS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ths_watchlist_sync import load_and_sync_watchlist
from live_daily_watchlist_builder import load_stock_static_profiles

CACHE_2TO3 = os.path.join(SIM_DIR, "data", "2to3_premarket_cache.json")
CACHE_3TO4 = os.path.join(SIM_DIR, "data", "3to4_premarket_cache.json")
CACHE_4TO5 = os.path.join(SIM_DIR, "data", "4to5_premarket_cache.json")
CACHE_HIGH_V51 = os.path.join(SIM_DIR, "data", "high_dragon_premarket_cache.json")
KPL_5Y_PATH = os.path.join(SIM_DIR, "data", "kpl_plates_5y_2021_2026_complete.jsonl")
A_DAILY = os.path.join(SIM_DIR, "data", "cn_hk_price_db", "a_daily.parquet")


def load_plate_heat_10d(d1_date: str, plate_names: list[str]) -> dict[str, list[int]]:
    """提取指定题材近10个交易日每日涨停家数柱，与一进二题材热度图同源"""
    targets = {p for p in plate_names if p and p != "独立暗牌组"}
    if not targets or not os.path.exists(KPL_5Y_PATH):
        return {p: [1] * 10 for p in plate_names}
    day_counts = []
    with open(KPL_5Y_PATH, "r", encoding="utf-8") as f:
        for ln in f:
            it = json.loads(ln)
            dt = it.get("date", "")
            if dt <= d1_date:
                mp = {}
                for pl in it.get("plates", it.get("themes", [])):
                    pn = str(pl.get("plate") or pl.get("plate_name") or "").strip()
                    if pn in targets:
                        mp[pn] = len(pl.get("stocks", []))
                day_counts.append((dt, mp))
    last10 = day_counts[-10:]
    out = {}
    for p in plate_names:
        if p == "独立暗牌组" or not last10:
            out[p] = [1] * 10
        else:
            out[p] = [int(mp.get(p, 0)) for _, mp in last10]
    return out


def discover_top1_space_dragon_fallback(d1_date: str) -> dict | None:
    """当高标首阴V5.1当日无候选、且4进5无候选时，查找>=5连板全场唯一第一名高标（严格只取第1名）"""
    cols = ["date", "ticker", "open", "high", "low", "close", "turn"]
    df = ds.dataset(A_DAILY, format="parquet").scanner(
        columns=cols, filter=(ds.field("date") >= pd.Timestamp("2026-09-15"))
    ).to_table().to_pandas()
    df["c6"] = df["ticker"].astype(str).str[:6]
    df = df[df["c6"].str.startswith(("00", "60"))].copy()
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df[df["dt_str"] <= d1_date].sort_values(["c6", "dt_str"])
    if df.empty:
        return None
    g = df.groupby("c6")
    df["pre_c"] = g["close"].shift(1)
    df["pct"] = df["close"] / df["pre_c"] - 1.0
    df["zt_px"] = np.floor(df["pre_c"] * 1.10 * 100.0 + 0.5) / 100.0
    df["is_zt"] = (df["close"] >= df["zt_px"] - 0.011) & (df["pct"] >= 0.095) & (df["pre_c"] > 0)
    s_zt = df["is_zt"].astype(int)
    s_shift = g["is_zt"].shift().eq(True)
    df["streak"] = s_zt.groupby([df["c6"], (s_zt != s_shift).cumsum()]).cumsum() * s_zt
    sub = df[df["dt_str"] == d1_date]
    hi5 = sub[sub["streak"] >= 5].sort_values(["streak", "turn"], ascending=[False, True])
    if hi5.empty:
        return None
    r = hi5.iloc[0]
    return {"code": str(r.c6), "streak": int(r.streak), "close": float(r.close)}


def build_extra_premarket_static(d1_date: str) -> dict:
    """盘前阶段构建关注名单、二进三(题材分卡)、三进四(全量)、高标(唯一第一名)静态底座"""
    wl_state, _ = load_and_sync_watchlist()
    wl_codes = wl_state["codes"]
    scripts_dir = os.path.join(SIM_DIR, "scripts")

    if (not os.path.exists(CACHE_2TO3)) or json.load(open(CACHE_2TO3)).get("sig_date") != d1_date:
        subprocess.run([sys.executable, os.path.join(scripts_dir, "fast_2to3_today.py"), "--build-cache"], check=False, timeout=45)
    if (not os.path.exists(CACHE_3TO4)) or json.load(open(CACHE_3TO4)).get("d3_date") != d1_date:
        subprocess.run([sys.executable, os.path.join(scripts_dir, "fast_3to4_today.py"), "--build-cache"], check=False, timeout=45)
    if (not os.path.exists(CACHE_4TO5)) or json.load(open(CACHE_4TO5)).get("sig_date") != d1_date:
        subprocess.run([sys.executable, os.path.join(BACKTESTS_DIR, "fast_4to5_today.py"), "--build-cache"], check=False, timeout=35)
    if (not os.path.exists(CACHE_HIGH_V51)) or json.load(open(CACHE_HIGH_V51)).get("as_of_d1") != d1_date:
        subprocess.run([sys.executable, os.path.join(scripts_dir, "fast_high_dragon_today.py"), "--build-cache"], check=False, timeout=45)

    c23_obj = json.load(open(CACHE_2TO3, "r", encoding="utf-8")) if os.path.exists(CACHE_2TO3) else {"candidates": [], "env": {}}
    c34_obj = json.load(open(CACHE_3TO4, "r", encoding="utf-8")) if os.path.exists(CACHE_3TO4) else {"candidates": [], "env": {}}
    c45_obj = json.load(open(CACHE_4TO5, "r", encoding="utf-8")) if os.path.exists(CACHE_4TO5) else {"candidates": []}
    ch51_obj = json.load(open(CACHE_HIGH_V51, "r", encoding="utf-8")) if os.path.exists(CACHE_HIGH_V51) else {"candidates": []}
    hi5_top1 = discover_top1_space_dragon_fallback(d1_date)

    p23_plates = sorted({(c.get("plate") if c.get("plate") and c.get("plate") != "其他" else "独立暗牌组") for c in c23_obj.get("candidates", [])})
    heat_2to3 = load_plate_heat_10d(d1_date, p23_plates)

    all_need_profile = set(wl_codes)
    q_extra = set(wl_codes)
    for c in c23_obj.get("candidates", []):
        all_need_profile.add(c["code"])
        q_extra.add(c["code"])
    for c in c34_obj.get("candidates", []):
        all_need_profile.add(c["code"])
        q_extra.add(c["code"])
        q_extra.update(c.get("plate_fb_codes", []))
        q_extra.update(c.get("plate_zt_codes", []))
    for c in c45_obj.get("candidates", []):
        all_need_profile.add(c["code"])
        q_extra.add(c["code"])
    for c in ch51_obj.get("candidates", []):
        all_need_profile.add(c["code"])
        q_extra.add(c["code"])
    if hi5_top1:
        all_need_profile.add(hi5_top1["code"])
        q_extra.add(hi5_top1["code"])

    profiles = load_stock_static_profiles(list(all_need_profile), d1_date)
    q_syms = sorted([("sh" if x.startswith("6") else "sz") + x for x in q_extra if len(str(x)) == 6])
    return {
        "d1_date": d1_date,
        "wl_state": wl_state,
        "c23_obj": c23_obj,
        "heat_2to3": heat_2to3,
        "c34_obj": c34_obj,
        "c45_obj": c45_obj,
        "ch51_obj": ch51_obj,
        "hi5_top1": hi5_top1,
        "profiles": profiles,
        "extra_q_codes": q_syms,
    }

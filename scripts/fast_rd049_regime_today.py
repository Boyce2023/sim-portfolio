#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
fast_rd049_regime_today.py — RD049 五档市场物理红绿灯极速实盘/盘前引擎
========================================================================
严格对齐 `rd049_traffic_light_granular_20261126/_rd049_common.py` 与
`step0_build_regime_cache.py` 口径（零 yfinance D12，腾讯直连走 ProxyHandler({})）：
  1. 腾讯实时直连拉取 `sz399303`（国证2000）、`sh000300`（沪深300）、`sh000852`（中证1000）近 90 日日线 + 收盘快照。
  2. 结合 `a_daily.parquet`（近 65 日）计算严格 T-1 收盘微观四指标 + 全市场含 20cm 非 ST `zt_cnt_t1` 与 `dt_cnt_t1`。
  3. 输出五档灯色：`L1_纯绿畅通 / L2_绿灯内杀 / L3_浅黄预警 / L4_深黄主跌 / L5_红灯地板`。
  4. 支持 `--premarket`、`--json-only`、`--as-of YYYY-MM-DD`、`--buy-date YYYY-MM-DD`，耗时 < 1.5s。
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
import bisect
import datetime
import json
import pickle
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"
RD049_CACHE_DIR = f"{SIM_DIR}/backtests_astock2/rd049_traffic_light_granular_20261126/_cache"
IDX_CACHE_JSON = f"{DATA_DIR}/rd049_index_kline_cache.json"
REG_TODAY_CACHE = f"{DATA_DIR}/rd049_regime_today_cache.json"
CAUSAL_CACHE_PKL = f"{DATA_DIR}/shadow_4piece_causal_cache.pkl"

LIGHT_PARAMS = {
    "y_cut": 42.0,
    "x_sh": 20.0,
    "x_dp": 42.0,
    "d_l4": 12.0,
    "d_l3": 9.0,
    "d_l2": 9.0,
}

LIGHT_POLICY = {
    "L1_纯绿畅通": {"3to4_min_score": 90.0, "delta": 0.0, "af03_req": False},
    "L2_绿灯内杀": {"3to4_min_score": 99.0, "delta": 9.0, "af03_req": True},
    "L3_浅黄预警": {"3to4_min_score": 99.0, "delta": 9.0, "af03_req": True},
    "L4_深黄主跌": {"3to4_min_score": 102.0, "delta": 12.0, "af03_req": True},
    "L5_红灯地板": {"3to4_min_score": 90.0, "delta": 0.0, "af03_req": False},
}


def _http_get_text(url: str, timeout: float = 2.0) -> str:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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


def _load_pit_st_tl() -> Optional[dict]:
    if not os.path.exists(CAUSAL_CACHE_PKL):
        return None
    try:
        with open(CAUSAL_CACHE_PKL, "rb") as f:
            obj = pickle.load(f)
        return (obj.get("refs") or {}).get("pit_st_tl")
    except Exception:
        return None


def _is_pit_st(pit_tl: Optional[dict], c6: str, dt_s: str, st_set: set[str]) -> bool:
    if c6 not in st_set:
        return False
    if pit_tl:
        tl = pit_tl.get(c6)
        if tl:
            cut_ts = f"{dt_s} 15:00:00"
            pos = bisect.bisect_right(tl[0], cut_ts)
            if pos > 0 and tl[1][pos - 1] == 0 and any(st == 1 for st in tl[1][pos:]):
                return False
    return True


def _fetch_tencent_kline_one(secid: str, limit: int = 90) -> list[tuple[str, float]]:
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={secid},day,,,{limit},"
    try:
        raw = json.loads(_http_get_text(url, timeout=2.0))
        days = ((raw.get("data") or {}).get(secid) or {}).get("day") or []
        out = []
        for r in days:
            if len(r) >= 3:
                dt_s = str(r[0])[:10]
                cl_v = float(r[2])
                if dt_s and cl_v > 0:
                    out.append((dt_s, cl_v))
        return out
    except Exception:
        return []


def _fetch_tencent_idx_live() -> dict[str, tuple[str, int, float]]:
    url = "http://qt.gtimg.cn/q=sz399303,sh000300,sh000852"
    out: dict[str, tuple[str, int, float]] = {}
    try:
        txt = _http_get_text(url, timeout=1.8)
        for ln in txt.strip().split(";"):
            if "~" not in ln:
                continue
            lhs, _, rhs = ln.partition("=")
            p = rhs.split("~")
            if len(p) > 31:
                secid = lhs.strip().split("_")[-1]
                cl_v = float(p[3] or 0.0)
                dt14 = str(p[30]).strip()
                q_dt = f"{dt14[:4]}-{dt14[4:6]}-{dt14[6:8]}" if len(dt14) >= 8 and dt14[:8].isdigit() else ""
                hhmm = int(dt14[8:12]) if len(dt14) >= 12 and dt14[8:12].isdigit() else 0
                if secid and cl_v > 0 and q_dt:
                    out[secid] = (q_dt, hhmm, cl_v)
    except Exception:
        pass
    return out


def fetch_index_series_fast(allow_net: bool = True) -> dict[str, dict[str, float]]:
    """Load/refresh sz399303, sh000300, sh000852 closes (<0.4s) strictly without yfinance."""
    secids = ("sz399303", "sh000300", "sh000852")
    series: dict[str, dict[str, float]] = {s: {} for s in secids}

    # 1. Seed from local cache or RD049 parquet
    if os.path.exists(IDX_CACHE_JSON):
        try:
            old = json.load(open(IDX_CACHE_JSON, encoding="utf-8"))
            for s in secids:
                if isinstance(old.get(s), dict):
                    series[s].update({str(k)[:10]: float(v) for k, v in old[s].items()})
        except Exception:
            pass

    for s in secids:
        if len(series[s]) < 65:
            pq_p = f"{RD049_CACHE_DIR}/raw_idx_{s}.parquet"
            if os.path.exists(pq_p):
                try:
                    df_p = pd.read_parquet(pq_p, columns=["trade_date", "close"]).tail(180)
                    for r in df_p.itertuples(index=False):
                        series[s][str(r.trade_date)[:10]] = float(r.close)
                except Exception:
                    pass

    # 2. Fetch fresh 90-day daily klines + live quote via Tencent ProxyHandler({})
    if allow_net:
        with ThreadPoolExecutor(max_workers=4) as ex:
            f_kl = {s: ex.submit(_fetch_tencent_kline_one, s, 90) for s in secids}
            f_lv = ex.submit(_fetch_tencent_idx_live)
            for s, fut in f_kl.items():
                for dt_s, cl_v in fut.result():
                    series[s][dt_s] = cl_v
            lv = f_lv.result()
            now_hm = int(datetime.datetime.now().strftime("%H%M"))
            today_s = datetime.date.today().isoformat()
            for s, (q_dt, q_hm, cl_v) in lv.items():
                if s in series and (q_hm >= 1500 or (q_dt < today_s) or (now_hm >= 1500 and q_dt == today_s)):
                    series[s][q_dt] = cl_v

        # Keep latest 180 bars compactly in local cache
        trimmed = {
            s: {k: series[s][k] for k in sorted(series[s].keys())[-180:]}
            for s in secids
        }
        try:
            tmp = IDX_CACHE_JSON + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(trimmed, f, ensure_ascii=False)
            os.replace(tmp, IDX_CACHE_JSON)
        except Exception:
            pass
        return trimmed

    return {s: {k: series[s][k] for k in sorted(series[s].keys())} for s in secids}


def compute_index_t1_row(series: dict[str, dict[str, float]], sig_date: str) -> dict[str, float]:
    """Compute exact index T-1 close metrics as of sig_date (matching step0_build_regime_cache.py)."""
    out: dict[str, float] = {}
    for secid, pfx in (("sz399303", "gz"), ("sh000300", "hs"), ("sh000852", "zz")):
        mp = series.get(secid, {})
        dts = [d for d in sorted(mp.keys()) if d <= sig_date]
        vals = np.array([float(mp[d]) for d in dts], dtype=np.float64)
        n = len(vals)
        if n == 0:
            continue
        c = vals[-1]
        out[f"{pfx}_r1_t1"] = float((c / vals[-2] - 1.0) * 100.0) if n >= 2 else np.nan
        out[f"{pfx}_r5_t1"] = float((c / vals[-6] - 1.0) * 100.0) if n >= 6 else np.nan
        out[f"{pfx}_r10_t1"] = float((c / vals[-11] - 1.0) * 100.0) if n >= 11 else np.nan
        out[f"{pfx}_r20_t1"] = float((c / vals[-21] - 1.0) * 100.0) if n >= 21 else np.nan
        out[f"{pfx}_vs_ma20_t1"] = float((c / float(np.mean(vals[-20:])) - 1.0) * 100.0) if n >= 20 else np.nan
        out[f"{pfx}_dd20_t1"] = float((c / float(np.max(vals[-21:])) - 1.0) * 100.0) if n >= 2 else np.nan
    return out


def compute_micro_t1_from_adaily(
    sig_date: str,
    st_set: Optional[set[str]] = None,
    pit_tl: Optional[dict] = None,
) -> dict[str, Any]:
    """Compute strict T-1 micro metrics + all-market non-ST zt/dt counts as of sig_date."""
    if st_set is None:
        st_set = _load_st_set()
    if pit_tl is None:
        pit_tl = _load_pit_st_tl()

    end_d = datetime.date.fromisoformat(sig_date)
    start_d = end_d - datetime.timedelta(days=65)
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "volume"]

    parts = [
        ds.dataset(f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", format="parquet")
        .scanner(columns=cols, filter=(ds.field("date") >= ds.scalar(start_d)) & (ds.field("date") <= ds.scalar(end_d)))
        .to_table()
        .to_pandas()
    ]
    if sig_date <= "2026-11-25":
        dl_p = f"{DATA_DIR}/cn_hk_price_db/a_delisted_daily.parquet"
        if os.path.exists(dl_p):
            dp = (
                ds.dataset(dl_p, format="parquet")
                .scanner(columns=cols, filter=(ds.field("date") >= ds.scalar(start_d)) & (ds.field("date") <= ds.scalar(end_d)))
                .to_table()
                .to_pandas()
            )
            if not dp.empty:
                parts.append(dp)

    df = pd.concat(parts, ignore_index=True)
    df["dt"] = df["date"].dt.strftime("%Y-%m-%d")
    df["c6"] = df["ticker"].astype(str).str[:6]
    suf = df["ticker"].astype(str).str[-3:]
    valid_u = df["c6"].str.startswith(("00", "60", "30", "688", "689")) & suf.isin([".SH", ".SZ"])
    df = df[valid_u & (df["close"] > 0) & (df["adj_close"] > 0)].copy()
    df = df.sort_values(["ticker", "dt"]).drop_duplicates(["ticker", "dt"], keep="first").reset_index(drop=True)

    g = df.groupby("ticker", sort=False)
    prev_adj = g["adj_close"].shift(1)
    prev_close_raw = prev_adj * (df["close"] / df["adj_close"])
    prev_vol = g["volume"].shift(1).fillna(0.0)
    df["ret_dec"] = df["adj_close"] / prev_adj - 1.0
    df["ret_1d"] = df["ret_dec"] * 100.0
    df["open_pct"] = (df["open"] / prev_close_raw - 1.0) * 100.0

    if pit_tl:
        c6_v = df["c6"].to_numpy()
        dt_v = df["dt"].to_numpy()
        st_arr = np.zeros(len(df), dtype=bool)
        for i in range(len(df)):
            st_arr[i] = _is_pit_st(pit_tl, c6_v[i], dt_v[i], st_set)
        is_st = pd.Series(st_arr, index=df.index)
    else:
        is_st = df["c6"].isin(st_set)

    is20 = df["c6"].str.startswith(("30", "688", "689"))
    lim = np.where(is20, 0.20, np.where(is_st & (df["dt"] < "2026-07-06"), 0.05, 0.10))
    zt_px = np.round(prev_close_raw * (1.0 + lim), 2)
    dt_px = np.round(prev_close_raw * (1.0 - lim), 2)
    r_th = np.where(is20, 0.195, 0.095)
    abn = df["ret_dec"].abs() > np.where(is20, 0.22, 0.12)
    vp = prev_close_raw.notna() & (prev_close_raw > 0) & (df["volume"].fillna(0.0) > 0)

    raw_zt = vp & (~is_st) & (df["close"] >= zt_px - 1e-4) & (df["close"] >= df["high"] - 1e-4)
    raw_hit = vp & (~is_st) & (df["high"] >= zt_px - 1e-4)
    raw_dt = vp & (~is_st) & (df["close"] <= dt_px + 1e-4) & (df["close"] <= df["low"] + 1e-4)

    # list_age > 20 guard matching step1_build_3layer_cycles_pit.py
    bar_rank = g.cumcount() + 1
    short_mask = (raw_hit | raw_dt) & (bar_rank <= 20)
    age_ok = np.ones(len(df), dtype=bool)
    if short_mask.any():
        short_tkrs = sorted(df.loc[short_mask, "ticker"].unique().tolist())
        hist_cnt = (
            ds.dataset(f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", format="parquet")
            .scanner(columns=["date", "ticker"], filter=(ds.field("ticker").isin(short_tkrs)) & (ds.field("date") < ds.scalar(start_d)))
            .to_table()
            .to_pandas()
        )
        pre_cnt = hist_cnt.groupby("ticker").size().to_dict() if not hist_cnt.empty else {}
        true_age = bar_rank + df["ticker"].map(pre_cnt).fillna(0).astype(int)
        age_ok = (true_age > 20).to_numpy()
        raw_zt &= age_ok
        raw_hit &= age_ok
        raw_dt &= age_ok

    df["is_zt"] = raw_zt
    df["hit_zt"] = raw_hit
    df["is_dt"] = raw_dt
    df["is_st"] = is_st
    df["is_20cm"] = is20 & (~is_st)
    df["age_ok"] = age_ok

    tkr_v = df["ticker"].to_numpy()
    zt_v = df["is_zt"].to_numpy()
    stk = np.zeros(len(df), dtype=np.int16)
    cur = 0
    pt = ""
    for i in range(len(df)):
        tk = tkr_v[i]
        if tk != pt:
            cur = 0
            pt = tk
        cur = (cur + 1) if zt_v[i] else 0
        stk[i] = cur
    df["streak"] = stk

    g2 = df.groupby("ticker", sort=False)
    df["prev_zt"] = g2["is_zt"].shift(1, fill_value=False).astype(bool)
    df["prev_streak"] = g2["streak"].shift(1).fillna(0).astype(np.int16)
    df["streak_m2"] = g2["streak"].shift(2).fillna(0).astype(np.int16)
    df["st_m1"] = g2["is_st"].shift(1, fill_value=False).astype(bool)
    df["pvol"] = prev_vol

    dts = sorted(df["dt"].unique())
    dts_le = [d for d in dts if d <= sig_date]
    t1_dt = dts_le[-1] if dts_le else sig_date
    prev_t1_dt = dts_le[-2] if len(dts_le) >= 2 else None

    nonst = df[(~df["is_st"]) & (df["volume"] > 0) & df["age_ok"]].copy()
    sub_t1 = nonst[nonst["dt"] == t1_dt]
    zt_cnt = int(sub_t1["is_zt"].sum())
    hit_cnt = int(sub_t1["hit_zt"].sum())
    zt20_cnt = int((sub_t1["is_zt"] & sub_t1["is_20cm"]).sum())
    zt10_cnt = zt_cnt - zt20_cnt
    dt_cnt = int(sub_t1["is_dt"].sum())
    dt20_cnt = int((sub_t1["is_dt"] & sub_t1["is_20cm"]).sum())
    dt10_cnt = dt_cnt - dt20_cnt
    zb_rate = float((hit_cnt - zt_cnt) / hit_cnt * 100.0) if hit_cnt > 0 else np.nan

    hb2_t1 = sub_t1[sub_t1["prev_streak"] >= 2]
    hb2_promo = float(hb2_t1["is_zt"].mean()) if len(hb2_t1) > 0 else np.nan

    # L1_duanban_damian_t1: step1_build_3layer_cycles_pit.py line 376
    trad_t1 = (
        (~df["is_st"]) & (~df["st_m1"]) & (df["dt"] == t1_dt)
        & (df["volume"] > 0) & (df["pvol"] > 0) & df["age_ok"]
        & df["ret_dec"].notna() & (df["ret_dec"].abs() <= 0.22)
    )
    db_df = df[trad_t1 & (df["streak_m2"] >= 1) & (~df["prev_zt"])]
    db_damian = float((db_df["ret_dec"] <= -0.05).mean() * 100.0) if len(db_df) > 0 else 0.0

    # pb_hb2_fail_open_t1: mean open_pct on t1_dt of prev_t1_dt's failed hb2
    pb_open = np.nan
    if prev_t1_dt is not None:
        fail_codes = set(
            nonst[(nonst["dt"] == prev_t1_dt) & (nonst["prev_streak"] >= 2) & (~nonst["is_zt"])]["c6"].tolist()
        )
        if fail_codes:
            nxt_rows = sub_t1[sub_t1["c6"].isin(fail_codes) & sub_t1["open_pct"].notna()]
            if len(nxt_rows) > 0:
                pb_open = float(nxt_rows["open_pct"].mean())

    # alla_med_r5_t1: 5d compounded daily median of non-ST stocks
    last5_dts = dts_le[-5:]
    med_r5 = np.nan
    if len(last5_dts) >= 5:
        med_s = nonst[nonst["dt"].isin(last5_dts)].groupby("dt")["ret_dec"].median().reindex(last5_dts).fillna(0.0)
        med_r5 = float((np.prod(1.0 + med_s.to_numpy(float)) - 1.0) * 100.0)

    return {
        "t1_dt": t1_dt,
        "zt_cnt_t1": float(zt_cnt),
        "mkt20_zt_cnt_t1": float(zt20_cnt),
        "mkt10_zt_cnt_t1": float(zt10_cnt),
        "dt_cnt_t1": float(dt_cnt),
        "dt10_cnt_t1": float(dt10_cnt),
        "dt20_cnt_t1": float(dt20_cnt),
        "hit_zt_cnt_t1": float(hit_cnt),
        "zb_rate_t1": zb_rate,
        "hb2_promo_t1": hb2_promo,
        "hb2_cnt_t1": int(len(hb2_t1)),
        "L1_duanban_damian_t1": db_damian,
        "pb_hb2_fail_open_t1": pb_open,
        "alla_med_r5_t1": med_r5,
    }


def classify_rd049_light(row: dict[str, Any]) -> dict[str, Any]:
    """Exact 100% parity implementation of _rd049_common.py::build_2d_states."""
    def _nz(k: str, fill: float) -> float:
        v = row.get(k)
        return float(v) if (v is not None and np.isfinite(float(v))) else float(fill)

    gz_ma20 = _nz("gz_vs_ma20_t1", 0.0)
    gz_dd20 = _nz("gz_dd20_t1", 0.0)
    gz_r5 = _nz("gz_r5_t1", 0.0)
    gz_r10 = _nz("gz_r10_t1", 0.0)
    alla_med5 = _nz("alla_med_r5_t1", 0.0)

    x_ma20 = float(np.clip((-1.0 - gz_ma20) / 5.5, 0.0, 1.0))
    x_dd20 = float(np.clip((-3.0 - gz_dd20) / 8.5, 0.0, 1.0))
    x_r5 = float(np.clip((-1.5 - gz_r5) / 5.5, 0.0, 1.0))
    x_r10 = float(np.clip((-2.0 - gz_r10) / 7.5, 0.0, 1.0))
    x_med5 = float(np.clip((-1.5 - alla_med5) / 5.0, 0.0, 1.0))
    x_score = (0.25 * x_ma20 + 0.25 * x_dd20 + 0.20 * x_r5 + 0.15 * x_r10 + 0.15 * x_med5) * 100.0

    hb2_p = _nz("hb2_promo_t1", 0.40)
    dbm = _nz("L1_duanban_damian_t1", 15.0)
    pb_f = _nz("pb_hb2_fail_open_t1", -2.0)
    zb_r = _nz("zb_rate_t1", 30.0)
    dt_c = _nz("dt_cnt_t1", 5.0)

    y_prm = float(np.clip((0.40 - hb2_p) / 0.22, 0.0, 1.0))
    y_dbm = float(np.clip((dbm - 15.0) / 25.0, 0.0, 1.0))
    y_pb = float(np.clip((-2.0 - pb_f) / 4.0, 0.0, 1.0))
    y_zb = float(np.clip((zb_r - 30.0) / 16.0, 0.0, 1.0))
    y_dt = float(np.clip((dt_c - 5.0) / 15.0, 0.0, 1.0))
    y_score = (0.20 * y_prm + 0.20 * y_dbm + 0.20 * y_pb + 0.20 * y_zb + 0.20 * y_dt) * 100.0

    is_red_floor = bool((gz_dd20 <= -13.5) or (gz_r10 <= -11.5) or (gz_r5 <= -8.5))
    r_lin = 0.55 * x_score + 0.45 * y_score
    r_union = 100.0 * (1.0 - (1.0 - x_score / 100.0) * (1.0 - y_score / 100.0))

    if is_red_floor:
        light_5 = "L5_红灯地板"
    elif x_score >= LIGHT_PARAMS["x_dp"]:
        light_5 = "L4_深黄主跌"
    elif x_score >= LIGHT_PARAMS["x_sh"]:
        light_5 = "L3_浅黄预警"
    elif y_score >= LIGHT_PARAMS["y_cut"]:
        light_5 = "L2_绿灯内杀"
    else:
        light_5 = "L1_纯绿畅通"

    pol = LIGHT_POLICY[light_5]
    return {
        **row,
        "X_score": round(x_score, 4),
        "Y_score": round(y_score, 4),
        "R_lin": round(r_lin, 4),
        "R_union": round(r_union, 4),
        "is_red_floor": is_red_floor,
        "light_5": light_5,
        "rd049_3to4_min_score": pol["3to4_min_score"],
        "rd049_3to4_delta": pol["delta"],
        "rd049_af03_weak_req": pol["af03_req"],
    }


def _next_weekday(dt_s: str) -> str:
    d = datetime.date.fromisoformat(dt_s) + datetime.timedelta(days=1)
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d.isoformat()


def compute_rd049_regime(
    sig_date: Optional[str] = None,
    buy_date: Optional[str] = None,
    premarket: bool = False,
    allow_net: bool = True,
) -> dict[str, Any]:
    """Unified RD049 regime snapshot entry point (runtime < 1.5s)."""
    t0 = time.time()
    series = fetch_index_series_fast(allow_net=allow_net)
    hs_dts = sorted(series.get("sh000300", {}).keys())

    # Get a_daily max date quickly from parquet metadata
    ad_tbl = ds.dataset(f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(
        columns=["date"], filter=ds.field("date") >= pd.Timestamp("2026-11-01")
    ).to_table().to_pandas()
    ad_dts = sorted(ad_tbl["date"].dt.strftime("%Y-%m-%d").unique().tolist())

    if buy_date:
        cand_le = [d for d in ad_dts if d < buy_date]
        sig_use = sig_date or (cand_le[-1] if cand_le else ad_dts[-1])
        buy_use = buy_date
    elif sig_date:
        sig_use = sig_date
        nxt_idx = [d for d in hs_dts if d > sig_use]
        buy_use = nxt_idx[0] if nxt_idx else _next_weekday(sig_use)
    else:
        now = datetime.datetime.now()
        today_s = now.strftime("%Y-%m-%d")
        hm = now.hour * 100 + now.minute
        cutoff_d = today_s if (now.weekday() >= 5 or hm >= 1500) else (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        closed_ad = [d for d in ad_dts if d <= cutoff_d]
        sig_use = closed_ad[-1] if closed_ad else ad_dts[-1]
        buy_use = today_s if (now.weekday() < 5 and hm < 1500) else _next_weekday(sig_use)

    idx_f = compute_index_t1_row(series, sig_use)
    micro_f = compute_micro_t1_from_adaily(sig_use)
    merged = {
        "sig_date": sig_use,
        "buy_date": buy_use,
        "mode": "premarket" if premarket else "live",
        **idx_f,
        **micro_f,
    }
    res = classify_rd049_light(merged)
    res["elapsed_sec"] = round(time.time() - t0, 3)

    # Save lightweight today snapshot
    if not sig_date and not buy_date:
        try:
            tmp = REG_TODAY_CACHE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
            os.replace(tmp, REG_TODAY_CACHE)
        except Exception:
            pass
    return res


def format_regime_card(res: dict[str, Any]) -> str:
    """Format concise Chinese output (ZERO '-' hyphens)."""
    bd_s = str(res["buy_date"]).replace("-", "/")
    sd_s = str(res["sig_date"]).replace("-", "/")
    pb_v = res.get("pb_hb2_fail_open_t1")
    pb_str = f"{pb_v:+.2f}%" if (pb_v is not None and np.isfinite(pb_v)) else "空值(默认按跌2%)"
    hp_v = res.get("hb2_promo_t1")
    hp_str = f"{hp_v*100:.1f}%" if (hp_v is not None and np.isfinite(hp_v)) else "空值(默认40%)"
    af_req = "需同题材首板助攻(+4)" if res["rd049_af03_weak_req"] else "无af03加严"
    lines = [
        f"结论: {bd_s} RD049 五档红绿灯为【{res['light_5']}】，三进四常规门槛 {res['rd049_3to4_min_score']:.0f} 分（{af_req}，P2 低位 pos750<0.50 可豁免），耗时 {res['elapsed_sec']:.2f}s。",
        f"宏观 X={res['X_score']:.1f} (国证2000较MA20 {res.get('gz_vs_ma20_t1',0):+.2f}% / 20日回撤 {res.get('gz_dd20_t1',0):+.2f}% / 5日 {res.get('gz_r5_t1',0):+.2f}% / 10日 {res.get('gz_r10_t1',0):+.2f}% / 全A中位5日 {res.get('alla_med_r5_t1',0):+.2f}%)",
        f"微观 Y={res['Y_score']:.1f} (高标晋级 {hp_str} / 断板大面 {res.get('L1_duanban_damian_t1',0):.1f}% / 高标断板次日开盘 {pb_str} / 炸板率 {res.get('zb_rate_t1',0):.1f}%)",
        f"全市场(含20cm非ST) T减1基准日 {sd_s}: 涨停 {int(res['zt_cnt_t1'])} 家 (10cm {int(res['mkt10_zt_cnt_t1'])} / 20cm {int(res['mkt20_zt_cnt_t1'])}) | 跌停 {int(res['dt_cnt_t1'])} 家 (10cm {int(res['dt10_cnt_t1'])} / 20cm {int(res['dt20_cnt_t1'])})",
    ]
    return "\n".join(lines).replace("-", "负") if False else "\n".join(lines)


def _format_clean_card(res: dict[str, Any]) -> str:
    txt = format_regime_card(res)
    # Remove literal ASCII '-' hyphens safely (replace numeric negative signs in prose only if needed, keep clean)
    out_lines = []
    for ln in txt.splitlines():
        # Convert negative numbers like -5.00% -> 跌5.00% / 负5.00% so zero '-' in prose
        import re as _re
        ln_clean = _re.sub(r"-(\d+(?:\.\d+)?)", r"负\1", ln).replace("-", "至")
        out_lines.append(ln_clean)
    return "\n".join(out_lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="RD049 五档市场物理红绿灯极速实盘/盘前引擎")
    ap.add_argument("--premarket", action="store_true", help="盘前模式")
    ap.add_argument("--json-only", action="store_true", help="仅输出 JSON")
    ap.add_argument("--as-of", type=str, default="", help="指定 T-1 信号基准日 YYYY-MM-DD")
    ap.add_argument("--buy-date", type=str, default="", help="指定目标交易日 YYYY-MM-DD")
    ap.add_argument("--offline", action="store_true", help="跳过网络直连仅读本地")
    args = ap.parse_args()

    res = compute_rd049_regime(
        sig_date=args.as_of or None,
        buy_date=args.buy_date or None,
        premarket=args.premarket,
        allow_net=not args.offline,
    )
    if args.json_only:
        clean_res = {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in res.items()}
        print(json.dumps(clean_res, ensure_ascii=False, indent=2))
    else:
        print(_format_clean_card(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

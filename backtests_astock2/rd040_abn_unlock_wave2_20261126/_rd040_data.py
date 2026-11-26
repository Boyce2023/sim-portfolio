#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD040 PIT data loaders: index cache, strict PIT ST state machine, CNINFO notices & 10d dev."""
import json
import os
import re
import sqlite3
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1_BASE = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{SIM}/backtests_astock2/rd040_abn_unlock_wave2_20261126"

STOCK_DAY_PQ = f"{WAVE1_BASE}/stock_day_core_features_pit.parquet"
MKT_DAILY_PQ = f"{WAVE1_BASE}/market_daily_all_new_factors_pit.parquet"
A_DAILY_PQ = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELIST_PQ = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
IDX_SRC_JSON = f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"
IDX_OUT_JSON = f"{OUT_DIR}/index_klines_cache.json"
KPL_JSONL = f"{SIM}/data/kpl_plates_2018_2026_merged.jsonl"
CNINFO_DB = f"{SIM}/data/cninfo_notices_5y_pit.db"


def ensure_index_cache(max_dt: Optional[str] = None) -> tuple[dict, dict, dict, list[str]]:
    """Verify & save 2020-10-01~2026-11-25 000002/399107/000300 index cache in RD040 output dir."""
    with open(IDX_SRC_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for k in ("sh000002", "sz399107", "sh000300"):
        d = {
            dt: float(v["close"] if isinstance(v, dict) else v)
            for dt, v in raw[k].items()
            if dt >= "2020-09-02" and (max_dt is None or dt <= max_dt)
        }
        out[k] = dict(sorted(d.items()))
    if max_dt is None:
        with open(IDX_OUT_JSON, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    all_dts = sorted(out["sh000002"].keys())
    return out["sh000002"], out["sz399107"], out["sh000300"], all_dts


def load_pit_st_and_notices(all_dts: list[str], max_dt: Optional[str] = None) -> dict:
    """Build strictly causal (eff_dt <= max_dt) KPL ST timeline, CNINFO ST timeline & severe/resume dates."""
    cutoff = max_dt or "2099-12-31"
    cal_arr = np.array(all_dts)

    def _eff_dt(pub_ts: str) -> str:
        dt_s, hm_s = pub_ts[:10], pub_ts[11:19]
        pos = int(np.searchsorted(cal_arr, dt_s, side="left"))
        if pos < len(cal_arr) and cal_arr[pos] == dt_s and hm_s >= "09:25:00":
            pos += 1
        return str(cal_arr[pos]) if pos < len(cal_arr) else "2099-12-31"

    kpl_hist = defaultdict(list)  # c6 -> [(dt, is_st_bool)]
    with open(KPL_JSONL, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            obj = json.loads(ln)
            dt = str(obj.get("date", ""))[:10]
            if dt < "2020-01-01" or dt > cutoff:
                continue
            day_seen = {}
            for pl in obj.get("plates", []):
                pname = str(pl.get("plate", ""))
                for st in pl.get("stocks", []):
                    if isinstance(st, dict):
                        c6, nm = str(st.get("code", ""))[:6].zfill(6), str(st.get("name", ""))
                    elif isinstance(st, list) and len(st) >= 2:
                        c6, nm = str(st[0])[:6].zfill(6), str(st[1])
                    else:
                        continue
                    flag = ("ST" in nm.upper()) or (pname == "ST板块")
                    day_seen[c6] = day_seen.get(c6, False) or flag
            for c6, flag in day_seen.items():
                kpl_hist[c6].append((dt, flag))
    # Prune stocks that NEVER had any ST tag to save ~800MB RAM (identical logic!)
    kpl_hist = defaultdict(list, {c: lst for c, lst in kpl_hist.items() if any(f for _, f in lst)})

    con = sqlite3.connect(f"file:{CNINFO_DB}?mode=ro", uri=True)
    cn_st = defaultdict(list)
    title_st_re = re.compile(r"^(?:【[^】]*】)?\s*\*?ST|(?::|：)\s*\*?ST")
    apply_re = re.compile(r"(实施(?:退市|其他)?风险警示|被实施.*风险警示|股票简称变更为\*?ST)")
    revoke_re = re.compile(r"(撤销(?:退市|其他)?风险警示|申请撤销.*风险警示.*获准|股票简称.*变更为(?!\*?ST))")
    q_st = "SELECT sec_code, pub_datetime_cst, title FROM notices WHERE (title LIKE '%ST%' OR title LIKE '%风险警示%') ORDER BY pub_datetime_cst"
    for c6, pub_ts, ttl in con.execute(q_st):
        edt = _eff_dt(str(pub_ts))
        if edt > cutoff:
            continue
        c6s = str(c6)[:6].zfill(6)
        t = str(ttl or "")
        if revoke_re.search(t) and "不予" not in t and "未能" not in t and "提示性" not in t:
            cn_st[c6s].append((edt, False))
        elif title_st_re.match(t) or apply_re.search(t):
            cn_st[c6s].append((edt, True))

    cn_sev = defaultdict(set)
    for c6, pub_ts, ttl in con.execute("SELECT sec_code, pub_datetime_cst, title FROM notices WHERE title LIKE '%严重异常波动%'"):
        t = str(ttl or "")
        if "可转换公司债券" in t or "可转债" in t:
            continue
        edt = _eff_dt(str(pub_ts))
        if edt <= cutoff:
            cn_sev[str(c6)[:6].zfill(6)].add(edt)
    con.close()
    return {"kpl_hist": kpl_hist, "cn_st": cn_st, "cn_sev": cn_sev}


def compute_strict_pit_st_mask(c6: str, dts: np.ndarray, cl: np.ndarray, hi: np.ndarray, lo: np.ndarray, pc_raw: np.ndarray, pit_info: dict) -> np.ndarray:
    """Strictly causal daily ST boolean array (KPL state + CNINFO state + exact 5% band)."""
    n = len(dts)
    st_mask = np.zeros(n, dtype=bool)
    k_list = pit_info["kpl_hist"].get(c6, [])
    c_list = pit_info["cn_st"].get(c6, [])
    ki, ci = 0, 0
    k_state, c_state = False, False

    # 5% exact limit band check
    zt5 = np.floor(pc_raw * 1.05 * 100.0 + 0.5) / 100.0
    dt5 = np.floor(pc_raw * 0.95 * 100.0 + 0.5) / 100.0
    r1 = np.where(pc_raw > 0, (cl / pc_raw - 1.0) * 100.0, 0.0)
    hit5 = (pc_raw > 0) & (((cl >= zt5 - 0.005) & (cl >= hi - 0.005)) | ((cl <= dt5 + 0.005) & (cl <= lo + 0.005))) & (np.abs(r1) <= 5.65)
    gt58 = (np.abs(r1) > 5.8)

    band_st = np.zeros(n, dtype=bool)
    for i in range(n):
        lo_w = max(0, i - 19)
        if np.sum(hit5[lo_w:i + 1]) >= 2 and not np.any(gt58[lo_w:i + 1]):
            band_st[i] = True

    for i in range(n):
        dt = str(dts[i])
        while ki < len(k_list) and k_list[ki][0] <= dt:
            k_state = k_list[ki][1]
            ki += 1
        while ci < len(c_list) and c_list[ci][0] <= dt:
            c_state = c_list[ci][1]
            ci += 1
        st_mask[i] = k_state or c_state or band_st[i]
    return st_mask


def compute_official_10d_dev_series(
    c6: str, dts: np.ndarray, op: np.ndarray, hi: np.ndarray, cl: np.ndarray, af: np.ndarray,
    imap: dict, all_dts: list[str], mkt_pos: dict, cn_sev_dts: set[str]
) -> dict:
    """Exact audit.md 10d deviation series with suspension index-chain exclusion & >=100% next-day reset."""
    n = len(dts)
    ac = cl * af
    ah = hi * af
    ao = op * af
    mi = np.array([mkt_pos[str(d)] for d in dts], dtype=np.int32)
    chain = np.ones(n, dtype=np.float64)
    for t in range(1, n):
        d_cur = str(dts[t])
        d_prev_mkt = all_dts[mi[t] - 1]
        chain[t] = chain[t - 1] * (imap[d_cur] / imap[d_prev_mkt])

    dev_c = np.zeros(n, dtype=np.float64)
    dev_h = np.zeros(n, dtype=np.float64)
    proj_flat = np.zeros(n, dtype=np.float64)
    open_dev = np.zeros(n, dtype=np.float64)
    floor_arr = np.zeros(n, dtype=np.int32)

    floor_idx = 0
    for t in range(1, n):
        if mi[t] - mi[t - 1] > 1:
            floor_idx = max(floor_idx, t - 1)
        floor_arr[t] = floor_idx

        # Strictly pre-09:25 proj_flat_dev10 for day t (if t trades flat vs index)
        lo_proj = max(floor_idx, t - 9)
        if lo_proj <= t - 1:
            p_devs = ((ac[t - 1] / ac[lo_proj:t] - 1.0) - (chain[t - 1] / chain[lo_proj:t] - 1.0)) * 100.0
            proj_flat[t] = max(0.0, float(np.max(p_devs)))
        else:
            proj_flat[t] = 0.0

        # Open deviation at 09:25 (comparing ao[t] vs ac[b] and chain[t-1]/chain[b])
        lo_b = max(floor_idx, t - 10)
        if lo_b <= t - 1:
            o_devs = ((ao[t] / ac[lo_b:t] - 1.0) - (chain[t - 1] / chain[lo_b:t] - 1.0)) * 100.0
            open_dev[t] = float(np.max(o_devs))
            c_devs = ((ac[t] / ac[lo_b:t] - 1.0) - (chain[t] / chain[lo_b:t] - 1.0)) * 100.0
            h_devs = ((ah[t] / ac[lo_b:t] - 1.0) - (chain[t] / chain[lo_b:t] - 1.0)) * 100.0
            dev_c[t] = float(np.max(c_devs))
            dev_h[t] = float(np.max(h_devs))

        # Severe event reset for NEXT trading day (audit.md: day of event still counts, reset next day)
        if dev_c[t] >= 100.0 or (str(dts[t]) in cn_sev_dts and dev_c[t] >= 95.0):
            floor_idx = max(floor_idx, t)

    return {
        "ac": ac, "ah": ah, "ao": ao, "mi": mi, "chain": chain,
        "dev_c": dev_c, "dev_h": dev_h, "proj_flat": proj_flat, "open_dev": open_dev, "floor_arr": floor_arr,
    }

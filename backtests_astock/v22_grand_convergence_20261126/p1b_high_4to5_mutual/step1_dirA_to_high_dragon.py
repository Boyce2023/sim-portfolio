#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
V22.0 Pillar 1B Direction A: 4to5 + 3to4 Genes -> High-Dragon V5.1 & V21 ColdDrop40.
Strict PIT causality (<= buy_date 09:25:00), zero yfinance (D12), SQLite ?mode=ro.
Tests:
  1. Exact baseline parity: High_V51_Base_t42 (42t, 20bps=14.7494x), V21_ColdDrop40 (41t), m42 ref (42t, 13.6156x),
     plus post-2026-10-27..2026-11-24 scan confirming 0 missed qualified trades.
  2. Strictly causal feature mapping from 4to5 + 3to4 onto High-Dragon candidates & univariate IS/OOS screen.
  3. Low-DOF (1-2 rule) entry filters & score tweaks + 3to4/4to5 exit transplants (5m exact parity simulator):
       - XF30 7-factor hold risk guard (ge1 / ge2) revoking true-yang immunity / weak open cut
       - 13:45 broken-ZT check (+7%/+5% and +8.5%)
       - 3to4 V4.2 T+1 ZT-hold 5m stop (prevc_tp1_m6_1000)
       - CutWeak & 4to5 d4_strong rule
  4. D15 metrics @ 30bps + 50bps stress across IS(21-23), OOS(24-26), 25-26, 2026, 2026H2, ex_top2,
     10,000x bootstrap, paired daily MTM t-test, and IS/OOS consistency audit.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import argparse
import bisect
import gc
import json
import math
import pickle
import sqlite3
import sys
import time
from collections import defaultdict
from typing import Optional

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
assert "yfinance" not in sys.modules, "D12 VIOLATION"

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)
import _p1b_common as cm


def load_5m_bars(codes: set[str], max_dt: str = "2026-11-25") -> dict[tuple[str, str], np.ndarray]:
    """Load 5m bars from all_strategies_5m_complete_pit.parquet + sub2_5m_bars_cache.pkl, truncated at `max_dt`."""
    bars = {}
    tks = sorted(codes)
    sc = ds.dataset(f"{cm.SIM}/data/all_strategies_5m_complete_pit.parquet", format="parquet").scanner(
        columns=["c6", "date", "hhmm_int", "open", "high", "low", "close", "volume", "amount"],
        filter=ds.field("c6").isin(tks),
        batch_size=65536,
        use_threads=False,
    )
    frames = []
    for batch in sc.to_batches():
        d = batch.to_pandas()
        if not d.empty:
            d["date"] = d["date"].astype(str).str[:10]
            d = d[d["date"] <= max_dt]
            if not d.empty:
                frames.append(d)
    if frames:
        df5 = pd.concat(frames, ignore_index=True)
        df5["c6"] = df5["c6"].astype(str).str.zfill(6)
        df5.sort_values(["c6", "date", "hhmm_int"], inplace=True)
        for (c6, dt), grp in df5.groupby(["c6", "date"], sort=False):
            bars[(c6, str(dt))] = grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        del df5
    del frames

    with open(f"{cm.HIGH_SBX}/sub2_5m_bars_cache.pkl", "rb") as f:
        sub2 = pickle.load(f)
    for k, v in sub2.items():
        c6 = str(k[0]).zfill(6)
        dt = str(k[2])[:10]
        if c6 in codes and dt <= max_dt and (c6, dt) not in bars and isinstance(v, pd.DataFrame) and not v.empty:
            sub = v[v["date"] == dt]
            if not sub.empty:
                hh = sub["hhmm"].astype(str).str.replace(":", "").astype(int).to_numpy(float)
                bars[(c6, dt)] = np.column_stack([
                    hh, sub["open"].to_numpy(float), sub["high"].to_numpy(float),
                    sub["low"].to_numpy(float), sub["close"].to_numpy(float),
                    sub["volume"].to_numpy(float), sub["amount"].to_numpy(float),
                ])
    del sub2
    pa.default_memory_pool().release_unused()
    gc.collect()
    return bars


def load_rich_daily_bars(codes: set[str], max_dt: str = "2026-11-25") -> dict[str, dict]:
    """Load exact daily OHLCV, adjf, pre_c, zt_px, dt_px, is_zt, is_dt, is_yizi_dt, ma5_amt_prev."""
    tks = sorted({f"{c}.SH" for c in codes} | {f"{c}.SZ" for c in codes})
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "volume"]
    flt = (ds.field("date") >= pd.Timestamp("2020-12-01")) & (ds.field("date") <= pd.Timestamp(max_dt)) & ds.field("ticker").isin(tks)
    frames = []
    for pq_path, dl_flag in [
        (f"{cm.SIM}/data/cn_hk_price_db/a_daily.parquet", 0),
        (f"{cm.SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", 1),
    ]:
        sc_p = ds.dataset(pq_path, format="parquet").scanner(columns=cols, filter=flt, batch_size=65536, use_threads=False)
        for batch in sc_p.to_batches():
            dfb = batch.to_pandas()
            if not dfb.empty:
                dfb = dfb[dfb["volume"] > 0].copy()
                if not dfb.empty:
                    dfb["dl_flag"] = dl_flag
                    frames.append(dfb)
    pa.default_memory_pool().release_unused()
    if not frames:
        return {}
    df = pd.concat(frames, ignore_index=True)
    del frames
    df["c6"] = df["ticker"].astype(str).str[:6]
    df["dt"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["c6", "dt", "dl_flag"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)

    out = {}
    for c6, g in df.groupby("c6", sort=False):
        g = g.sort_values("dt").reset_index(drop=True)
        dts = g["dt"].tolist()
        op = g["open"].to_numpy(float)
        hi = g["high"].to_numpy(float)
        lo = g["low"].to_numpy(float)
        cl = g["close"].to_numpy(float)
        acl = g["adj_close"].to_numpy(float)
        amt = g["amount"].to_numpy(float)
        adjf = np.where((cl > 0) & np.isfinite(acl) & (acl > 0), acl / cl, 1.0)
        n = len(dts)
        pre_c = np.zeros(n, dtype=float)
        pre_c[0] = cl[0]
        if n > 1:
            pre_c[1:] = cl[:-1] * adjf[:-1] / adjf[1:]
        zt_px = np.floor(pre_c * 1.10 * 100.0 + 0.5) / 100.0
        dt_px = np.floor(pre_c * 0.90 * 100.0 + 0.5) / 100.0
        pct = np.where(pre_c > 0, cl / pre_c - 1.0, 0.0)
        is_zt = (cl >= zt_px - 0.011) & (pct >= 0.095) & (pre_c > 0)
        is_dt = (cl <= dt_px + 0.011) & (pct <= -0.095) & (pre_c > 0)
        is_dt_exact = (cl <= dt_px + 0.005) & (pre_c > 0)
        is_yizi_dt = is_dt_exact & (op <= dt_px + 0.005) & (hi <= dt_px + 0.005)
        ma5_amt = pd.Series(amt).rolling(5, min_periods=1).mean().to_numpy(float)
        out[c6] = {
            "dts": dts, "dt_idx": {d: i for i, d in enumerate(dts)},
            "open": op, "high": hi, "low": lo, "close": cl, "adjf": adjf,
            "pre_c": pre_c, "zt_px": zt_px, "dt_px": dt_px,
            "is_zt": is_zt, "is_dt": is_dt, "is_dt_exact": is_dt_exact, "is_yizi_dt": is_yizi_dt,
            "amt": amt, "ma5_amt_prev": np.concatenate([[amt[0]], ma5_amt[:-1]]),
        }
    return out


def build_7f_hold_context(codes: set[str], max_dt: str = "2026-11-25") -> dict:
    """Strictly causal t-1 risk lookup tables for 3to4 V4.1 7 hold-risk factors truncated at `max_dt`."""
    # 1. KPL plate Elo
    kpl_stock_elo = {}
    plate_elo = {}
    kpl_recs = []
    with open(f"{cm.SIM}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            o = json.loads(ln)
            dt_k = str(o.get("date", ""))[:10]
            if dt_k <= max_dt:
                kpl_recs.append((dt_k, [(pl.get("plate", ""), [str(s[0])[:6].zfill(6) for s in pl.get("stocks", [])]) for pl in o.get("plates", [])]))
    kpl_recs.sort(key=lambda x: x[0])
    for dt_k, pls in kpl_recs:
        seen = set()
        for rk, (pn, stks) in enumerate(pls):
            seen.add(pn)
            cur = plate_elo.get(pn, 100.0)
            target = 145.0 if rk == 0 else (130.0 if rk <= 2 else 110.0)
            plate_elo[pn] = cur * 0.8 + target * 0.2
            for sc6 in stks:
                if sc6 in codes:
                    kpl_stock_elo[(sc6, dt_k)] = max(kpl_stock_elo.get((sc6, dt_k), 100.0), plate_elo[pn])
        for pn in list(plate_elo.keys()):
            if pn not in seen:
                plate_elo[pn] = 100.0 + (plate_elo[pn] - 100.0) * 0.85
    del kpl_recs

    # 2. LHB inst sell > 20M & day-surf buyer by (c6, dt)
    lhb_risk = {}
    tks_lhb = sorted(codes)
    for fn, is_buy in [("lhb_buy.parquet", True), ("lhb_sell.parquet", False)]:
        sc_lhb = ds.dataset(f"{cm.SIM}/backtest/2026-10-20-lhasa/{fn}", format="parquet").scanner(
            columns=["TRADE_DATE", "SECURITY_CODE", "OPERATEDEPT_NAME", "BUY", "SELL"],
            filter=ds.field("SECURITY_CODE").isin(tks_lhb),
            batch_size=65536,
            use_threads=False,
        )
        for batch in sc_lhb.to_batches():
            d = batch.to_pandas()
            if d.empty:
                continue
            d["c6"] = d["SECURITY_CODE"].astype(str).str[:6].str.zfill(6)
            d["dt"] = d["TRADE_DATE"].astype(str).str[:10]
            d = d[(d["c6"].isin(codes)) & (d["dt"] <= max_dt)]
            for r in d.itertuples(index=False):
                k = (r.c6, r.dt)
                cur = lhb_risk.setdefault(k, [0.0, 0.0, False])
                nm = str(r.OPERATEDEPT_NAME or "")
                if "机构专用" in nm:
                    cur[0] += float(r.SELL or 0.0)
                    cur[1] += float(r.BUY or 0.0)
                if is_buy and cm.DAY_SURF_RE.search(nm):
                    cur[2] = True

    # 3. Stock reg notices
    reg_dates = defaultdict(list)
    con_cn = sqlite3.connect(f"file:{cm.SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    ph = ",".join("?" for _ in codes)
    for sc, pdt, ti in con_cn.execute(
        f"SELECT sec_code, pub_datetime_cst, title FROM notices WHERE sec_code IN ({ph}) AND pub_datetime_cst <= ?",
        (*sorted(codes), max_dt + " 23:59:59"),
    ):
        ti_s = str(ti or "")
        if any(w in ti_s for w in cm.REG_INC_WORDS) and not any(w in ti_s for w in cm.REG_EXC_LITE):
            reg_dates[str(sc).zfill(6)].append(str(pdt)[:19])
    con_cn.close()

    # 4. CSI300 & 4b+ reb_r10
    df_mk = pd.read_parquet(f"{cm.WAVE1_BASE}/market_daily_all_new_factors_pit.parquet")
    df_mk["trade_date"] = df_mk["trade_date"].astype(str).str[:10]
    df_mk = df_mk[df_mk["trade_date"] <= max_dt].copy()
    mk_map = df_mk.set_index("trade_date").to_dict("index")

    sc_ds = ds.dataset(f"{cm.WAVE1_BASE}/stock_day_core_features_pit.parquet", format="parquet")
    flt_sc = (ds.field("prev_streak") >= 4) & (ds.field("dt") <= max_dt)
    chunks = [b.to_pandas() for b in sc_ds.scanner(columns=["dt", "c6", "prev_streak", "is_zt", "is_st_pit", "is_20cm"], filter=flt_sc, batch_size=65536, use_threads=False).to_batches()]
    df_4b = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    del chunks
    df_4b["dt"] = df_4b["dt"].astype(str).str[:10]
    df_4b["c6"] = df_4b["c6"].astype(str).str.zfill(6)

    # Load all zt rows for next-day check
    flt_zt = (ds.field("is_zt") == 1) & (ds.field("dt") <= max_dt)
    chunks_z = [b.to_pandas() for b in sc_ds.scanner(columns=["dt", "c6"], filter=flt_zt, batch_size=65536, use_threads=False).to_batches()]
    df_zt = pd.concat(chunks_z, ignore_index=True) if chunks_z else pd.DataFrame()
    del chunks_z
    zt_set = set(zip(df_zt["dt"].astype(str).str[:10], df_zt["c6"].astype(str).str.zfill(6)))
    del df_zt

    dts_sc = sorted(df_mk["trade_date"].tolist())
    dt_nxt = {dts_sc[i]: dts_sc[i + 1] for i in range(len(dts_sc) - 1)}
    brk4 = df_4b[(df_4b["is_zt"] == 0) & (df_4b["is_st_pit"] == 0) & (df_4b["is_20cm"] == 0)].copy()
    brk4["ndt"] = brk4["dt"].map(dt_nxt)
    brk4 = brk4.dropna(subset=["ndt"])
    brk4["reb_zt"] = [1 if (r.ndt, r.c6) in zt_set else 0 for r in brk4.itertuples(index=False)]
    reb_by_dt = brk4.groupby("ndt")["reb_zt"].agg(["sum", "count"]).to_dict("index")
    del df_4b, brk4, zt_set
    pa.default_memory_pool().release_unused()
    gc.collect()

    f7_by_dt = {}
    q_hist = []
    for dt_v in dts_sc:
        if q_hist:
            w10 = q_hist[-10:]
            sn, sd = sum(x[0] for x in w10), sum(x[1] for x in w10)
            f7_by_dt[dt_v] = (sn / max(1, sd)) < 0.20 if sd > 0 else False
        else:
            f7_by_dt[dt_v] = False
        st = reb_by_dt.get(dt_v)
        q_hist.append((int(st["sum"]), int(st["count"])) if st else (0, 0))

    return {
        "kpl_elo": kpl_stock_elo,
        "lhb_risk": lhb_risk,
        "reg_dates": dict(reg_dates),
        "mk_map": mk_map,
        "f7_by_dt": f7_by_dt,
    }


def _double_dev_px(cb: dict, cp: int, idx_map: dict, disc: float = 0.07) -> float:
    cd = cb["dts"][cp]
    ir = idx_map.get(cd)
    if not ir:
        return 99999.0
    bp = 99999.0
    for k in range(1, min(11, cp + 1)):
        p = cp - k
        bi = idx_map.get(cb["dts"][p])
        bc = float(cb["close"][p])
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (1.0 - disc) + (ir / bi - 1.0)))
    for k in range(1, min(31, cp + 1)):
        p = cp - k
        bi = idx_map.get(cb["dts"][p])
        bc = float(cb["close"][p])
        if bi and bc > 0:
            bp = min(bp, bc * (1.0 + (2.0 - disc) + (ir / bi - 1.0)))
    return float(bp)


def _calc_7risk(c6: str, bd: str, cb: dict, k: int, risk_ctx: dict) -> int:
    dt_k = cb["dts"][k]
    dt_prev = cb["dts"][k - 1]
    pts = 0
    if risk_ctx["kpl_elo"].get((c6, dt_prev), 100.0) >= 135.0:
        pts += 1
    lr = risk_ctx["lhb_risk"].get((c6, dt_prev))
    if lr is not None:
        if lr[0] > 2e7 or (lr[0] - lr[1]) > 2e7:
            pts += 1
        if lr[2]:
            pts += 1
    if cb["amt"][k - 1] > 3.5 * max(1.0, cb["ma5_amt_prev"][k - 1]):
        pts += 1
    lo_ts, hi_ts = f"{bd} 09:25:00", f"{dt_k} 09:25:00"
    if any(lo_ts <= ts < hi_ts for ts in risk_ctx["reg_dates"].get(c6, [])):
        pts += 1
    if risk_ctx["mk_map"].get(dt_k, {}).get("mkt_csi300_ret1d_t1", 0.0) <= -2.0:
        pts += 1
    if risk_ctx["f7_by_dt"].get(dt_k, False):
        pts += 1
    return pts


def sim_high_trade_exit(
    c6: str,
    bd: str,
    buy_px: float,
    b_open_h: bool,
    cb: dict,
    bars_5m: dict,
    sh2: dict,
    sz2: dict,
    risk_ctx: dict,
    exit_mode: str = "Base_V51",
    fee: float = 0.0020,
) -> Optional[dict]:
    """
    Exact 5m + daily exit simulator for High-Dragon.
    `Base_V51` reproduces `ledger_high_v51_clean.csv` (42t, 14.7494x @ 20bps) to < 1e-6.
    Transplanted exit modes strictly zero intraday lookahead & strictly T+1.
    """
    if cb is None or bd not in cb["dt_idx"]:
        return None
    d2p = cb["dt_idx"][bd]
    n = len(cb["dts"])
    if d2p + 1 >= n:
        return None
    imap = sh2 if c6.startswith("60") else sz2
    a0 = float(cb["adjf"][d2p])

    def _finish(ep: int, ehh: int, epx: float, eo: bool, tag: str) -> dict:
        pre_def_ret = (float(epx) * float(cb["adjf"][ep])) / (buy_px * a0) * (1.0 - fee) - 1.0
        ed = cb["dts"][ep]
        # V19.1 EOD limit-down deferral
        if ehh >= 1455 and bool(cb["is_dt_exact"][ep]):
            kk = ep + 1
            while kk < n - 1 and bool(cb["is_yizi_dt"][kk]):
                kk += 1
            if kk < n:
                ed = cb["dts"][kk]
                ehh = 925
                epx = round(float(cb["open"][kk]), 2)
                eo = True
                nret = (float(cb["open"][kk]) * float(cb["adjf"][kk])) / (buy_px * a0) * (1.0 - fee) - 1.0
                return {"exit_date": ed, "exit_hhmm": ehh, "exit_price": epx, "eo": eo, "net_ret": float(nret), "pre_defer_ret": float(pre_def_ret), "exit_reason": f"{tag}_dt_defer"}
        nret = (float(epx) * float(cb["adjf"][ep])) / (buy_px * a0) * (1.0 - fee) - 1.0
        return {"exit_date": ed, "exit_hhmm": ehh, "exit_price": round(float(epx), 2), "eo": eo, "net_ret": float(nret), "pre_defer_ret": float(pre_def_ret), "exit_reason": tag}

    def _resolve_5m_day(p: int, pl: float, use_1345: bool, thr_1345: float) -> tuple[int, float]:
        arr_e = bars_5m.get((c6, cb["dts"][p]))
        if use_1345 and arr_e is not None and len(arr_e) > 0:
            # Check 93% dev before 1345, and 1345 ZT-break rule
            pck = float(cb["pre_c"][p])
            ztk = float(cb["zt_px"][p])
            for row_e in arr_e:
                hh = int(row_e[0])
                if pl < 99990.0 and float(row_e[2]) >= pl:
                    return hh, float(max(row_e[1], pl))
                if hh == 1345 and float(row_e[4]) < ztk - 0.011:
                    if float(row_e[4]) >= pck * (1.0 + thr_1345):
                        return 1345, float(row_e[4])
        if pl < 99990.0 and arr_e is not None and len(arr_e) > 0:
            for row_e in arr_e:
                if float(row_e[2]) >= pl:
                    return int(row_e[0]), float(max(row_e[1], pl))
        if pl < 99990.0 and float(cb["high"][p]) >= pl:
            return 1030, float(pl)
        return 1500, float(cb["close"][p])

    def _check_tp1_m6_1000(p: int, arr_p: Optional[np.ndarray]) -> Optional[tuple[int, float]]:
        if arr_p is None or len(arr_p) == 0:
            return None
        pck = float(cb["pre_c"][p])
        dtk = round(pck * 0.90, 2)
        for bi in range(len(arr_p)):
            hh = int(arr_p[bi, 0])
            bc = float(arr_p[bi, 4])
            if bc <= dtk + 0.005:
                continue
            if hh >= 1000 and bc <= pck * 0.94:
                if bi + 1 < len(arr_p):
                    nx_o = float(arr_p[bi + 1, 1])
                    if nx_o > dtk + 0.005:
                        return int(arr_p[bi + 1, 0]), nx_o
                else:
                    return hh, bc
        return None

    def _run_zt_loop(start_p: int, zt_entry_mode: str) -> tuple[int, int, float, bool, str]:
        imm = False
        max_steps = 8 if exit_mode != "XF30_Full" else 13
        for step in range(1, max_steps):
            p = start_p + step
            if p >= n:
                break
            dt_p = cb["dts"][p]
            arr_p = bars_5m.get((c6, dt_p))
            rpts = _calc_7risk(c6, bd, cb, p, risk_ctx)

            # Option: 7f >= 1 or >= 2 revokes weak open < pre_c
            if exit_mode in ("7f_NoImm_ge1", "7f_NoImm_ge2") and not bool(cb["is_yizi_dt"][p]):
                thr_pts = 1 if exit_mode == "7f_NoImm_ge1" else 2
                if rpts >= thr_pts and float(cb["open"][p]) < float(cb["pre_c"][p]):
                    return p, 925, float(cb["open"][p]), True, f"7f_ge{thr_pts}_open_cut"

            # Option: T+1 ZT-hold 5m stop (3to4 V4.2 prevc_tp1_m6_1000 or all ZT days)
            if exit_mode == "TP1_m6_1000" and step == 1 and (not bool(cb["is_yizi_dt"][p])):
                hit_sl = _check_tp1_m6_1000(p, arr_p)
                if hit_sl is not None:
                    return p, hit_sl[0], hit_sl[1], False, "tp1_m6_1000"
            if exit_mode == "All_m6_1000" and (not bool(cb["is_yizi_dt"][p])):
                hit_sl = _check_tp1_m6_1000(p, arr_p)
                if hit_sl is not None:
                    return p, hit_sl[0], hit_sl[1], False, "all_m6_1000"

            # Native 93% double-dev (only when buy-day sealed ZT or chained ZT — checked via zt_entry_mode)
            if exit_mode != "XF30_Full":
                pl = _double_dev_px(cb, p, imap, 0.07)
                if float(cb["open"][p]) >= pl:
                    return p, 925, float(cb["open"][p]), True, "dev93_open"
                if float(cb["high"][p]) >= pl:
                    ehh, epx = _resolve_5m_day(p, pl, False, 0.07)
                    return p, ehh, epx, False, "dev93_5m"

            # 13:45 ZT-break rule from 3to4 XF30
            if exit_mode in ("XF30_1345_7f", "XF30_1345_85", "XF30_Full") and arr_p is not None and len(arr_p) > 0 and (not bool(cb["is_yizi_dt"][p])):
                ztk = float(cb["zt_px"][p])
                pck = float(cb["pre_c"][p])
                thr1345 = (0.070 if rpts >= 1 else 0.050) if exit_mode != "XF30_1345_85" else 0.085
                for bi in range(len(arr_p)):
                    if int(arr_p[bi, 0]) == 1345:
                        bc1345 = float(arr_p[bi, 4])
                        if bc1345 < ztk - 0.011 and bc1345 >= pck * (1.0 + thr1345):
                            return p, 1345, bc1345, False, "xf30_1345"
                        break

            if not bool(cb["is_zt"][p]):
                # Broken day
                if exit_mode == "XF30_Full":
                    allow_imm = (not imm) and (float(cb["close"][p]) >= float(cb["pre_c"][p]) * 1.02) and (rpts < 2)
                elif exit_mode == "7f_NoImm_ge1":
                    allow_imm = (not imm) and (float(cb["close"][p]) > float(cb["open"][p])) and (rpts < 1)
                elif exit_mode == "7f_NoImm_ge2":
                    allow_imm = (not imm) and (float(cb["close"][p]) > float(cb["open"][p])) and (rpts < 2)
                else:
                    allow_imm = (not imm) and (float(cb["close"][p]) > float(cb["open"][p]))
                if allow_imm:
                    imm = True
                    continue
                while p < n - 1 and bool(cb["is_yizi_dt"][p]):
                    p += 1
                ehh, epx = _resolve_5m_day(p, 99999.0 if exit_mode == "XF30_Full" else _double_dev_px(cb, p, imap, 0.07), False, 0.07)
                return p, ehh, epx, False, "broken_zt_exit"

        p_end = min(start_p + 5, n - 1)
        return p_end, 1500, float(cb["close"][p_end]), False, "max_steps_exit"

    is_zt0 = bool(cb["is_zt"][d2p])
    if is_zt0:
        ep, ehh, epx, eo, tag = _run_zt_loop(d2p, "d2_zt")
        return _finish(ep, ehh, epx, eo, tag)

    # D2 did NOT seal ZT
    p = min(d2p + 1, n - 1)
    while p < n - 1 and bool(cb["is_yizi_dt"][p]):
        p += 1

    d2_c = float(cb["close"][d2p])
    d2_o = float(cb["open"][d2p])
    d2_p = float(cb["pre_c"][d2p])
    d2_ret = d2_c / buy_px - 1.0
    d3_o = float(cb["open"][p])
    d3_p = float(cb["pre_c"][p])
    d3_op_pct = (d3_o / d3_p - 1.0) if d3_p > 0 else 0.0

    # Optional D3 morning weak cut rules
    if exit_mode == "CutWeak_V51":
        if d2_ret <= -0.02 or (d2_c < float(cb["open"][d2p]) and d2_ret < 0) or d3_op_pct <= -0.035:
            return _finish(p, 925, d3_o, True, "cut_weak_v51")
    elif exit_mode in ("D4Strong_4to5", "XF30_Full"):
        d2_strong = (d2_c >= d2_o) and (d2_c >= d2_p) and (d3_o >= d3_p * 1.005)
        if not d2_strong:
            return _finish(p, 925, d3_o, True, "cut_not_strong")

    # Optional unconditional 93% dev on D3 even if D2 unsealed
    if exit_mode == "Dev93_Uncond":
        pl3 = _double_dev_px(cb, p, imap, 0.07)
        if d3_o >= pl3:
            return _finish(p, 925, d3_o, True, "dev93_d3_open")
        if float(cb["high"][p]) >= pl3:
            ehh, epx = _resolve_5m_day(p, pl3, False, 0.07)
            return _finish(p, ehh, epx, False, "dev93_d3_5m")

    if bool(cb["is_zt"][p]):
        ep, ehh, epx, eo, tag = _run_zt_loop(p, "chained_zt")
        return _finish(ep, ehh, epx, eo, tag)
    return _finish(p, 1500, float(cb["close"][p]), False, "d3_eod_close")


def eval_high_variants(trunc_date: Optional[str] = None) -> dict:
    t0 = time.time()
    max_dt = trunc_date or "2026-11-25"
    eval_end = trunc_date or "2026-11-16"

    bench, sh2, sz2, csi, all_dts = cm.load_bench_and_index(max_dt=max_dt)
    cal_dts = bench["trade_date"].tolist()
    cal_idx = {d: i for i, d in enumerate(cal_dts)}
    nmap = cm.load_pit_notice_maps(max_dt=max_dt)

    # Load rd038 pool + v5_enriched_119 + reference ledgers
    with open(f"{cm.RD038_DIR}/_cache/rd038_master_cache.pkl", "rb") as f:
        c38 = pickle.load(f)
    dh = c38["pools_ext"]["high"].copy()
    v21_cfg = c38["other5_variants"]["high"]["m1_causal_cold_drop40_t0"]
    dh["v21_score"] = np.asarray(v21_cfg["score"], dtype=float)
    del c38

    dh["buy_date"] = dh["buy_date"].astype(str).str[:10]
    dh["code"] = dh["code"].astype(str).str.zfill(6)
    dh["exit_date"] = dh["exit_date"].astype(str).str[:10]
    if trunc_date:
        dh = dh[dh["exit_date"] <= trunc_date].copy().reset_index(drop=True)
    else:
        dh = dh[dh["buy_date"] <= "2026-11-16"].copy().reset_index(drop=True)

    v5_all = pd.read_pickle(f"{cm.HIGH_SBX}/v5_enriched_119.pkl").copy()
    v5_all["buy_date"] = v5_all["buy_date"].astype(str).str[:10]
    v5_all["code"] = v5_all["code"].astype(str).str.zfill(6)
    if trunc_date:
        v5_all = v5_all[v5_all["buy_date"] <= trunc_date].copy()

    # Load post-2026-10-27 high-dragon scan directly from stock_day_core_features_pit (strictly truncated)
    sc_ds = ds.dataset(f"{cm.WAVE1_BASE}/stock_day_core_features_pit.parquet", format="parquet")
    codes_hi = set(dh["code"]) | set(v5_all["code"])
    sc_cols = [
        "dt", "c6", "open", "high", "low", "close", "open_pct", "ret_1d", "is_zt", "is_yizi_zt",
        "is_dt", "is_st_pit", "is_20cm", "prev_streak", "streak", "turn_pct", "real_turn_pct_t1",
        "lock_top10_pct_pre", "free_mcap_yi_t1", "hr10d_space_t1", "hr30d_space_t1",
        "pos_20d_t1", "pos_60d_t1", "vol_ratio5_t1", "amount_yi_t1",
        "d1_open_board_cnt_t1", "d1_first_seal_hhmm_t1", "lhb_on_t1",
        "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1", "lhb_has_quant_t1", "lhb_has_surf_yz_t1",
        "kpl_in_t1", "kpl_zt1_t1", "kpl_zt3_t1",
    ]
    flt_hi = ds.field("c6").isin(sorted(codes_hi))
    if trunc_date:
        flt_hi = flt_hi & (ds.field("dt") <= trunc_date)
    chunks_h = [b.to_pandas() for b in sc_ds.scanner(columns=sc_cols, filter=flt_hi, batch_size=65536, use_threads=False).to_batches()]
    df_sc_hi = pd.concat(chunks_h, ignore_index=True) if chunks_h else pd.DataFrame(columns=sc_cols)
    del chunks_h
    df_sc_hi["dt"] = df_sc_hi["dt"].astype(str).str[:10]
    df_sc_hi["c6"] = df_sc_hi["c6"].astype(str).str.zfill(6)

    # Check post-2026-10-27..max_dt broken >=4b candidates
    post_audit = []
    if not trunc_date:
        flt_post = (ds.field("dt") >= "2026-10-27") & (ds.field("dt") <= "2026-11-24") & (ds.field("prev_streak") >= 4) & (ds.field("is_zt") == 0)
        df_post = pd.concat([b.to_pandas() for b in sc_ds.scanner(columns=["dt", "c6", "prev_streak", "open", "close", "open_pct", "turn_pct", "is_st_pit", "is_20cm"], filter=flt_post, use_threads=False).to_batches()], ignore_index=True)
        df_post["dt"] = df_post["dt"].astype(str).str[:10]
        df_post["c6"] = df_post["c6"].astype(str).str.zfill(6)
        for r in df_post[(df_post["is_st_pit"] == 0) & (df_post["is_20cm"] == 0) & (df_post["close"] > df_post["open"])].itertuples(index=False):
            di = bisect.bisect_right(cal_dts, r.dt)
            bd_nxt = cal_dts[di] if di < len(cal_dts) else ""
            nf = cm.query_notice_flags(r.c6, bd_nxt, cal_dts, cal_idx, nmap) if bd_nxt else {}
            post_audit.append({
                "d1_break_dt": r.dt, "buy_date_nxt": bd_nxt, "code": r.c6,
                "prev_streak": int(r.prev_streak), "d1_turn_pct": round(float(r.turn_pct), 2),
                "veto_to35": bool(r.turn_pct > 35.0),
                "sreg_10d_union": bool(nf.get("sreg_10d_union", False)),
                "sreg_titles": nf.get("sreg_titles", []),
            })

    # Load 4to5 master & 3to4 cache (truncated at max_dt) for historical cross-strategy tags & features
    df_45 = pd.read_parquet(f"{cm.P3_DEEP}/w2_4to5_enriched_master.parquet", columns=[
        "buy_date", "code", "open_pct", "B6_auc_sweet_2_7_bought",
        "exdt_B6_auc_sweet_2_7_E4_F61_high_dragon_handoff",
        "f47_reb_zt_r10", "f47_env_brk_dt_r10", "plate_3b_cnt", "d4_mkt_nuke_cnt",
        "tighter_headroom_pit", "f50_d4_top_yz_new_buy",
    ])
    df_45["buy_date"] = df_45["buy_date"].astype(str).str[:10]
    df_45["code"] = df_45["code"].astype(str).str.zfill(6)
    if trunc_date:
        df_45 = df_45[df_45["buy_date"] <= trunc_date].copy()
    g1_st = pd.read_parquet(f"{cm.RD048_DIR}/_cache_g1_strict_jianchi_raw.parquet", columns=["buy_date", "exit_date", "code"])
    g1_st["buy_date"] = g1_st["buy_date"].astype(str).str[:10]
    g1_st["exit_date"] = g1_st["exit_date"].astype(str).str[:10]
    g1_st["code"] = g1_st["code"].astype(str).str.zfill(6)
    if trunc_date:
        g1_st = g1_st[g1_st["exit_date"] <= trunc_date].copy()

    with open(f"{cm.F1_3TO4}/pit_exit_cache_full.pkl", "rb") as f:
        c34 = pickle.load(f)
    cdf34 = c34["cand_df"].copy()
    cdf34["buy_date"] = cdf34["buy_date"].astype(str).str[:10]
    cdf34["code"] = cdf34["code"].astype(str).str.zfill(6)
    if trunc_date:
        cdf34 = cdf34[cdf34["buy_date"] <= trunc_date].copy()
    del c34

    # Load Xueqiu pre-market post timestamps for High-Dragon codes (both xueqiu_guba & astock_community)
    xq_seen = defaultdict(set)
    xq_ts = defaultdict(list)
    ph_x = ",".join("?" for _ in codes_hi)
    con_xq = sqlite3.connect(f"file:{cm.SIM}/data/xueqiu_guba_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_xq.execute(
        f"SELECT symbol, post_id, created_time_str FROM xueqiu_posts WHERE symbol IN ({ph_x}) AND created_time_str <= ?",
        (*sorted(codes_hi), max_dt + " 23:59:59"),
    ):
        c6 = str(sym)[:6].zfill(6)
        pid_c = str(pid).replace("xq_", "")
        if pid_c not in xq_seen[c6]:
            xq_seen[c6].add(pid_c)
            xq_ts[c6].append(str(cts)[:19])
    con_xq.close()
    con_cm = sqlite3.connect(f"file:{cm.SIM}/data/astock_community_5y_pit.db?mode=ro", uri=True)
    for sym, pid, cts in con_cm.execute(
        f"SELECT symbol, post_id, pub_datetime_cst FROM community_posts WHERE source='xueqiu' AND symbol IN ({ph_x}) AND pub_datetime_cst <= ?",
        (*sorted(codes_hi), max_dt + " 23:59:59"),
    ):
        c6 = str(sym)[:6].zfill(6)
        pid_c = str(pid).replace("xq_", "")
        if pid_c not in xq_seen[c6]:
            xq_seen[c6].add(pid_c)
            xq_ts[c6].append(str(cts)[:19])
    con_cm.close()
    for c6 in xq_ts:
        xq_ts[c6].sort()

    # Load daily bars & 5m bars for High-Dragon simulation & exact MTM
    rich_bars = load_rich_daily_bars(codes_hi, max_dt=max_dt)
    bar_lu = {
        (c6, cb["dts"][i]): (float(cb["open"][i]), float(cb["close"][i]), float(cb["adjf"][i]))
        for c6, cb in rich_bars.items()
        for i in range(len(cb["dts"]))
    }
    bars_5m = load_5m_bars(codes_hi, max_dt=max_dt)
    risk_ctx = build_7f_hold_context(codes_hi, max_dt=max_dt)

    # Load market_daily & 1st-board peers at 09:25 for T04/T19 & f47_reb_zt_r10 on buy_date
    df_mk = risk_ctx["mk_map"]
    flt_st1 = (ds.field("streak") == 1) & (ds.field("is_zt") == 1) & (ds.field("dt") <= max_dt)
    df_fb_d1 = pd.concat([b.to_pandas() for b in sc_ds.scanner(columns=["dt", "c6", "is_st_pit", "is_20cm"], filter=flt_st1, use_threads=False).to_batches()], ignore_index=True)
    df_fb_d1["dt"] = df_fb_d1["dt"].astype(str).str[:10]
    df_fb_d1["c6"] = df_fb_d1["c6"].astype(str).str.zfill(6)
    fb_set_d1 = set(zip(df_fb_d1.loc[(df_fb_d1["is_st_pit"] == 0) & (df_fb_d1["is_20cm"] == 0), "dt"],
                        df_fb_d1.loc[(df_fb_d1["is_st_pit"] == 0) & (df_fb_d1["is_20cm"] == 0), "c6"]))
    del df_fb_d1

    flt_op1 = (ds.field("prev_streak") == 1) & (ds.field("dt") <= max_dt)
    df_1b = pd.concat([b.to_pandas() for b in sc_ds.scanner(columns=["dt", "c6", "open_pct", "open", "prev_close_raw", "is_yizi_zt", "is_st_pit", "is_20cm"], filter=flt_op1, use_threads=False).to_batches()], ignore_index=True)
    df_1b["dt"] = df_1b["dt"].astype(str).str[:10]
    df_1b["c6"] = df_1b["c6"].astype(str).str.zfill(6)
    kpl_d1_plates = {}
    with open(f"{cm.SIM}/data/kpl_plates_2018_2026_merged.jsonl", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            o = json.loads(ln)
            dt_k = str(o.get("date", ""))[:10]
            if dt_k <= max_dt:
                kpl_d1_plates[dt_k] = o.get("plates", [])

    b1_map = {}
    for r in df_1b[(df_1b["is_st_pit"] == 0) & (df_1b["is_20cm"] == 0)].itertuples(index=False):
        b1_map.setdefault(r.dt, {})[r.c6] = (float(r.open_pct) / 100.0, bool(r.open_pct >= 9.90 or r.is_yizi_zt))
    del df_1b

    # Attach strictly causal features (<= bd 09:25:00) to `dh` (62 rows)
    v5_map = {(r["buy_date"], r["code"]): r for _, r in v5_all.iterrows()}
    sc_map = {(r.dt, r.c6): r for r in df_sc_hi.itertuples(index=False)}
    sc_by_c = {c6: grp.sort_values("dt").reset_index(drop=True) for c6, grp in df_sc_hi.groupby("c6")}

    feat_rows = []
    for r in dh.itertuples(index=False):
        bd = r.buy_date
        sd = str(r.sig_date)[:10] if hasattr(r, "sig_date") and pd.notna(r.sig_date) else cal_dts[max(0, cal_idx[bd] - 1)]
        c6 = r.code
        v5r = v5_map.get((bd, c6), {})
        scr = sc_map.get((bd, c6))
        nf = cm.query_notice_flags(c6, bd, cal_dts, cal_idx, nmap)

        # Headroom & lock/fmcap
        hr10 = float(getattr(scr, "hr10d_space_t1", getattr(r, "sd_hr10d_space_t1", 25.0)) or 25.0) / 100.0
        hr30 = float(getattr(scr, "hr30d_space_t1", getattr(r, "sd_hr30d_space_t1", 25.0)) or 25.0) / 100.0
        tight_hr = min(hr10, hr30)
        lock10 = float(v5r.get("lock", getattr(r, "sd_lock_top10_pct_pre", 38.0)) or 38.0)
        fmcap = float(v5r.get("fmcap", getattr(r, "sd_free_mcap_yi_t1", 40.0)) or 40.0)
        real_to = float(getattr(scr, "real_turn_pct_t1", getattr(r, "sd_real_turn_pct_t1", 20.0)) or 20.0)
        d1_to = float(v5r.get("d1_to", real_to) or real_to)

        # Pre-streak pos20_d0 (3to4 U01): bar strictly before streak launched
        st0 = int(v5r.get("st0", 4) or 4)
        sc_c = sc_by_c.get(c6)
        pos20_pre = 0.5
        if sc_c is not None and bd in set(sc_c["dt"]):
            pos_bd = int(sc_c.index[sc_c["dt"] == bd][0])
            # On bd, D1 is pos_bd-1, D0 is pos_bd-2, streak start is pos_bd-1-st0; strictly before start = pos_bd-2-st0
            pre_idx = max(0, pos_bd - 1 - st0)
            pos20_pre = float(sc_c.loc[pre_idx, "pos_20d_t1"]) if pd.notna(sc_c.loc[pre_idx, "pos_20d_t1"]) else 0.5

        # Xueqiu 2d pre-market count [d1_dt 00:00:00, bd 09:25:00) (3to4 U02)
        bi_c = cal_idx.get(bd, 1)
        d1_dt = cal_dts[max(0, bi_c - 1)]
        arr_xq = xq_ts.get(c6, [])
        lo_x = bisect.bisect_left(arr_xq, f"{d1_dt} 00:00:00")
        hi_x = bisect.bisect_left(arr_xq, f"{bd} 09:25:00")
        xq_cnt_2d = int(hi_x - lo_x)

        # Same-theme 1st-board gap >=2% & 0 yizi (T04 / T19) at bd 09:25
        # Find stock's theme plates on D0 (streak top) or D1, then inspect D1 1st-board stocks in same plate opening on bd
        t04_ok, t19_yizi = 0, 0
        d0_dt = cal_dts[max(0, bi_c - 2)]
        my_plates = set()
        for dt_pl in (d1_dt, d0_dt):
            for pl in kpl_d1_plates.get(dt_pl, []):
                pcs = {str(s[0])[:6].zfill(6) for s in pl.get("stocks", [])}
                if c6 in pcs:
                    my_plates.add(pl.get("plate", ""))
        if not my_plates and hasattr(r, "plate") and pd.notna(r.plate):
            my_plates.add(str(r.plate))
        peers_1b = set()
        for pl in kpl_d1_plates.get(d1_dt, []):
            if pl.get("plate", "") in my_plates:
                pcs = {str(s[0])[:6].zfill(6) for s in pl.get("stocks", [])}
                peers_1b |= {pc for pc in pcs if pc != c6 and (d1_dt, pc) in fb_set_d1}
        b1_today = b1_map.get(bd, {})
        if peers_1b:
            op_list, yz_cnt = [], 0
            for pc in peers_1b:
                if pc in b1_today:
                    op_p, yz_p = b1_today[pc]
                    op_list.append(op_p)
                    if yz_p:
                        yz_cnt += 1
            if op_list:
                if max(op_list) >= 0.02 and yz_cnt == 0:
                    t04_ok = 1
                if yz_cnt >= 1:
                    t19_yizi = 1

        # Prior 4to5 & 3to4 overlap
        p45_sub = df_45[(df_45["code"] == c6) & (df_45["buy_date"] < bd) & (df_45["buy_date"] >= (pd.Timestamp(bd) - pd.Timedelta(days=10)).strftime("%Y-%m-%d"))]
        was_45_b6 = bool((p45_sub["B6_auc_sweet_2_7_bought"] == 1).any()) if not p45_sub.empty else False
        g1_sub = g1_st[(g1_st["code"] == c6) & (g1_st["buy_date"] < bd) & (g1_st["buy_date"] >= (pd.Timestamp(bd) - pd.Timedelta(days=10)).strftime("%Y-%m-%d"))]
        was_45_strict = bool(not g1_sub.empty)
        held_45_strict = bool((g1_sub["exit_date"] >= bd).any()) if not g1_sub.empty else False

        p34_sub = cdf34[(cdf34["code"] == c6) & (cdf34["buy_date"] < bd) & (cdf34["buy_date"] >= (pd.Timestamp(bd) - pd.Timedelta(days=12)).strftime("%Y-%m-%d"))]
        was_34_cand = bool(not p34_sub.empty)

        dow = pd.Timestamp(bd).weekday() + 1
        mo = pd.Timestamp(bd).month
        feat_rows.append({
            "buy_date": bd, "code": c6,
            "tighter_hr": tight_hr, "lock10": lock10, "fmcap": fmcap,
            "lock50_small35": (lock10 >= 50.0) and (12.0 <= fmcap <= 35.0),
            "d1_to": d1_to, "real_to": real_to,
            "pos20_pre_le40": pos20_pre <= 0.40,
            "pos20_pre_val": round(pos20_pre, 3),
            "xq_cnt_2d": xq_cnt_2d,
            "xq_ge4": xq_cnt_2d >= 4,
            "t04_ok": bool(t04_ok),
            "t19_yizi": bool(t19_yizi),
            "was_45_b6": was_45_b6,
            "was_45_strict": was_45_strict,
            "held_45_strict": held_45_strict,
            "was_34_cand": was_34_cand,
            "dow_mon": dow == 1,
            "mo_15": mo in (1, 5),
            "lhb_d1_quant": bool(getattr(scr, "lhb_has_quant_t1", 0) or v5r.get("qu1", 0)),
            "lhb_d1_inst_sell": bool(pd.notna(getattr(scr, "lhb_inst_net_yi_t1", np.nan)) and float(getattr(scr, "lhb_inst_net_yi_t1", 0.0)) < -0.1),
            "lhb_d1_day_surf": bool(getattr(scr, "lhb_has_surf_yz_t1", 0) or v5r.get("lhb_d0_day_surf_buy", False)),
            "n_zt_prev": float(getattr(r, "L1_zt_cnt_t1", v5r.get("n_zt", 50.0)) or 50.0),
            "reb_zt_r10_inv": bool(risk_ctx["f7_by_dt"].get(bd, False)),  # reb_zt_r10 < 0.20
            "brk_r10_val": float(v5r.get("brk_r10", 0.25) or 0.25),
            "jianchi_only": nf["jianchi_only_pq"] or nf["jianchi_only_union"],
            "tox_strict": nf["tox_strict_pq"] or nf["tox_strict_union"],
            "f_kpl_in": bool(len(my_plates) > 0),
            "f_kpl_zt3": int(getattr(scr, "kpl_zt3_t1", 0) or 0),
        })
    df_feat = pd.DataFrame(feat_rows)
    dh = dh.merge(df_feat, on=["buy_date", "code"], how="left")

    # 1. Re-simulate baseline exit & verify 42/42 parity vs ledger_high_v51_clean.csv!
    t42_ref = pd.read_csv(f"{cm.PARTC_V191}/ledger_high_v51_clean.csv", dtype={"code": str})
    t42_ref["code"] = t42_ref["code"].str.zfill(6)
    if trunc_date:
        t42_ref = t42_ref[t42_ref["exit_date"] <= trunc_date].copy().reset_index(drop=True)

    # Pre-simulate exit modes across all rows of `dh`
    exit_modes = [
        "Base_V51", "7f_NoImm_ge1", "7f_NoImm_ge2",
        "XF30_1345_7f", "XF30_1345_85", "XF30_Full",
        "TP1_m6_1000", "All_m6_1000", "CutWeak_V51", "D4Strong_4to5", "Dev93_Uncond",
    ]
    exit_cache = {em: [] for em in exit_modes}
    for r in dh.itertuples(index=False):
        cb = rich_bars.get(r.code)
        bpx = float(r.buy_price)
        boh = bool(r.b_open_h)
        for em in exit_modes:
            res_ex = sim_high_trade_exit(r.code, r.buy_date, bpx, boh, cb, bars_5m, sh2, sz2, risk_ctx, exit_mode=em, fee=0.0020)
            if res_ex is None or (trunc_date and res_ex["exit_date"] > trunc_date):
                exit_cache[em].append({
                    "exit_date": r.exit_date, "exit_hhmm": int(r.exit_hhmm), "exit_price": float(r.exit_price),
                    "eo": bool(r.eo), "net_ret_020": float(r.net_ret_020), "pre_defer_ret": float(r.net_ret_020),
                    "exit_reason": "fallback",
                })
            else:
                res_ex["net_ret_020"] = res_ex.pop("net_ret")
                exit_cache[em].append(res_ex)

    def _run_high_slot(score_vec: np.ndarray, exit_mode: str = "Base_V51", cb_mode: str = "Matched42CB", thr: float = 88.0) -> tuple[pd.DataFrame, pd.DataFrame]:
        ex_rows = exit_cache[exit_mode]
        rows = []
        for idx, r in enumerate(dh.itertuples(index=False)):
            sc = float(score_vec[idx])
            if sc < thr:
                continue
            ex = ex_rows[idx]
            r20 = float(ex["net_ret_020"])
            r30 = float(cm.convert_fee(r20, 0.0020, 0.0030))
            r50 = float(cm.convert_fee(r20, 0.0020, 0.0050))
            rows.append({
                "buy_date": r.buy_date, "buy_hhmm": int(r.buy_hhmm),
                "exit_date": ex["exit_date"], "exit_hhmm": int(ex["exit_hhmm"]),
                "code": r.code, "name": r.name,
                "score": sc, "buy_price_val": float(r.buy_price), "exit_price": float(ex["exit_price"]),
                "b_open_h": bool(r.b_open_h), "eo": bool(ex["eo"]),
                "net_ret": r30, "net_ret_020": r20, "net_ret_030": r30, "net_ret_050": r50,
                "pre_defer_ret": float(ex["pre_defer_ret"]),
                "v51_cb_loss": bool(getattr(r, "v51_cb_loss", ex["pre_defer_ret"] < -0.02)),
                "exit_reason": ex["exit_reason"],
            })
        if not rows:
            return pd.DataFrame(), pd.DataFrame()
        pass_df = pd.DataFrame(rows).sort_values(["buy_date", "score", "code"], ascending=[True, False, True], kind="mergesort").reset_index(drop=True)
        pass_df["mtm_pairs_json"] = cm.build_mtm_pairs_for_trades(pass_df, cal_dts, bar_lu, ret_col="net_ret_030")

        taken, fd, peo, cl, sk = [], "", False, 0, False
        for r in pass_df.itertuples(index=False):
            if fd == "" or r.buy_date > fd or (r.buy_date == fd and peo and (not bool(r.b_open_h))):
                if cb_mode != "None" and sk:
                    fd, peo = str(r.exit_date), bool(r.eo)
                    if float(r.net_ret_020) > 0.0:
                        sk, cl = False, 0
                    continue
                taken.append(r._asdict())
                fd, peo = str(r.exit_date), bool(r.eo)
                if cb_mode != "None":
                    is_cb = bool(r.v51_cb_loss) if cb_mode == "Matched42CB" else (float(r.net_ret_020) < -0.02)
                    if is_cb:
                        cl += 1
                        sk = (cl >= 2)
                    elif float(r.net_ret_020) > 0.0:
                        cl = 0
        slot_df = pd.DataFrame(taken).reset_index(drop=True)
        return pass_df, slot_df

    # Parity verification on Base_V51
    p_base, s_base = _run_high_slot(dh["orig_score"].to_numpy(float), "Base_V51", "Matched42CB", 88.0)
    parity_ok = (len(s_base) == len(t42_ref)) and (list(zip(s_base["buy_date"], s_base["code"])) == list(zip(t42_ref["buy_date"], t42_ref["code"])))
    max_ret_diff = float(np.max(np.abs(s_base["net_ret_020"].to_numpy(float) - t42_ref["net_ret"].to_numpy(float)))) if parity_ok else 999.0
    assert parity_ok and max_ret_diff < 1e-6, f"Parity failed! ok={parity_ok}, diff={max_ret_diff}"

    # Also build m42 ref evaluation for explicit transparency
    m42_df = pd.read_csv(f"{cm.PARTC_V191}/ledger_high_v51_m42_clean_ref.csv", dtype={"code": str})
    m42_df["code"] = m42_df["code"].str.zfill(6)
    if trunc_date:
        m42_df = m42_df[m42_df["exit_date"] <= trunc_date].copy().reset_index(drop=True)
    m42_df["net_ret_020"] = m42_df["net_ret"].astype(float)
    m42_df["net_ret_030"] = cm.convert_fee(m42_df["net_ret_020"], 0.0020, 0.0030)
    m42_df["net_ret"] = m42_df["net_ret_030"]
    m42_df["buy_price_val"] = m42_df["buy_price"].astype(float)
    m42_df["mtm_pairs_json"] = cm.build_mtm_pairs_for_trades(m42_df, cal_dts, bar_lu, ret_col="net_ret_030")

    base_dr_full, _ = cm.daily_mtm_series(s_base, cal_dts, ret_col="net_ret_030")
    _, s_v21 = _run_high_slot(dh["v21_score"].to_numpy(float), "Base_V51", "Matched42CB", 88.0)
    v21_dr_full, _ = cm.daily_mtm_series(s_v21, cal_dts, ret_col="net_ret_030")

    # 2. Univariate IS vs OOS screen across 4to5 + 3to4 features on official V5.1 >= 88 passing pool (n=46)
    m_pass = dh["orig_score"].to_numpy(float) >= 88.0
    univariate_rows = []
    screen_cols = [
        "jianchi_only", "tox_strict", "lock50_small35", "pos20_pre_le40", "xq_ge4",
        "t04_ok", "t19_yizi", "was_45_b6", "was_45_strict", "held_45_strict", "was_34_cand",
        "dow_mon", "mo_15", "lhb_d1_quant", "lhb_d1_inst_sell", "lhb_d1_day_surf",
        "reb_zt_r10_inv", "f_kpl_in",
    ]
    # Also continuous thresholds
    dh["hr_lt12"] = dh["tighter_hr"] < 0.12
    dh["hr_ge22"] = dh["tighter_hr"] >= 0.22
    dh["real_to_gt30"] = dh["real_to"] > 30.0
    dh["real_to_le20"] = dh["real_to"] <= 20.0
    dh["n_zt_lt40"] = dh["n_zt_prev"] < 40.0
    screen_cols += ["hr_lt12", "hr_ge22", "real_to_gt30", "real_to_le20", "n_zt_lt40"]

    sub_p = dh[m_pass].copy()
    is_m = (sub_p["buy_date"] <= "2023-12-31").to_numpy(bool)
    oos_m = (sub_p["buy_date"] >= "2024-01-01").to_numpy(bool)
    r30_p = sub_p["net_ret_030"].to_numpy(float)
    for col in screen_cols:
        fv = sub_p[col].fillna(False).to_numpy(bool)
        n1, n0 = int(fv.sum()), int((~fv).sum())
        n1_is, n0_is = int((fv & is_m).sum()), int(((~fv) & is_m).sum())
        n1_oos, n0_oos = int((fv & oos_m).sum()), int(((~fv) & oos_m).sum())
        mu1 = float(r30_p[fv].mean() * 100.0) if n1 else 0.0
        mu0 = float(r30_p[~fv].mean() * 100.0) if n0 else 0.0
        mu1_is = float(r30_p[fv & is_m].mean() * 100.0) if n1_is else None
        mu0_is = float(r30_p[(~fv) & is_m].mean() * 100.0) if n0_is else None
        mu1_oos = float(r30_p[fv & oos_m].mean() * 100.0) if n1_oos else None
        mu0_oos = float(r30_p[(~fv) & oos_m].mean() * 100.0) if n0_oos else None
        univariate_rows.append({
            "feature": col, "n_true": n1, "n_false": n0,
            "mean_true_pct": round(mu1, 2), "mean_false_pct": round(mu0, 2), "diff_pp": round(mu1 - mu0, 2),
            "is_n_true": n1_is, "is_diff_pp": round(mu1_is - mu0_is, 2) if (mu1_is is not None and mu0_is is not None) else None,
            "oos_n_true": n1_oos, "oos_diff_pp": round(mu1_oos - mu0_oos, 2) if (mu1_oos is not None and mu0_oos is not None) else None,
            "dual_same_sign": bool((mu1_is is not None and mu0_is is not None and mu1_oos is not None and mu0_oos is not None) and ((mu1_is - mu0_is) * (mu1_oos - mu0_oos) > 0)),
        })

    # 3. Evaluate all Direction A Baselines, Entry Transfers (low-DOF 1-2 rules), and Exit Transplants
    sc_base = dh["orig_score"].to_numpy(float)
    sc_v21 = dh["v21_score"].to_numpy(float)

    variants_spec = [
        # Baselines
        ("Base_V51_t42", sc_base, "Base_V51", "Matched42CB", 88.0),
        ("Base_V21_ColdDrop40", sc_v21, "Base_V51", "Matched42CB", 88.0),
        ("Base_V51_NoCB", sc_base, "Base_V51", "None", 88.0),
        ("Base_V51_CausalCB", sc_base, "Base_V51", "CausalCB", 88.0),
        # Entry transfers (Low-DOF 1-2 rules from 4to5 + 3to4) onto V5.1 and V21
        ("A_Veto_JianchiOnly", np.where(dh["jianchi_only"].to_numpy(bool), -999.0, sc_base), "Base_V51", "Matched42CB", 88.0),
        ("A_Veto_ToxStrict", np.where(dh["tox_strict"].to_numpy(bool), -999.0, sc_base), "Base_V51", "Matched42CB", 88.0),
        ("A_Veto_HeadroomLt12", np.where(dh["hr_lt12"].to_numpy(bool), -999.0, sc_base), "Base_V51", "Matched42CB", 88.0),
        ("A_Veto_LhbDaySurf", np.where(dh["lhb_d1_day_surf"].to_numpy(bool), -999.0, sc_base), "Base_V51", "Matched42CB", 88.0),
        ("A_Veto_XqGe4_U02", np.where(dh["xq_ge4"].to_numpy(bool), -999.0, sc_base), "Base_V51", "Matched42CB", 88.0),
        ("A_Score_Pos20Pre_p6", sc_base + np.where(dh["pos20_pre_le40"].to_numpy(bool), 6.0, 0.0), "Base_V51", "Matched42CB", 88.0),
        ("A_Score_Lock50Sm35_p6", sc_base + np.where(dh["lock50_small35"].to_numpy(bool), 6.0, 0.0), "Base_V51", "Matched42CB", 88.0),
        ("A_Score_XqGe4_m10", sc_base + np.where(dh["xq_ge4"].to_numpy(bool), -10.0, 0.0), "Base_V51", "Matched42CB", 88.0),
        ("A_Score_T04_p5_T19_m6", sc_base + np.where(dh["t04_ok"].to_numpy(bool), 5.0, 0.0) + np.where(dh["t19_yizi"].to_numpy(bool), -6.0, 0.0), "Base_V51", "Matched42CB", 88.0),
        ("A_Score_RebZtR10_p6", sc_base + np.where(~dh["reb_zt_r10_inv"].to_numpy(bool), 6.0, -4.0), "Base_V51", "Matched42CB", 88.0),
        ("A_V21_plus_JianchiVeto", np.where(dh["jianchi_only"].to_numpy(bool), -999.0, sc_v21), "Base_V51", "Matched42CB", 88.0),
        ("A_V21_plus_XqGe4_m10", sc_v21 + np.where(dh["xq_ge4"].to_numpy(bool), -10.0, 0.0), "Base_V51", "Matched42CB", 88.0),
        ("A_V21_SkipPrev45Held", np.where(dh["held_45_strict"].to_numpy(bool), -999.0, sc_v21), "Base_V51", "Matched42CB", 88.0),
        ("A_V51_OnlyPrev45Pass", np.where(dh["was_45_b6"].to_numpy(bool), sc_base, -999.0), "Base_V51", "Matched42CB", 88.0),
        ("A_V51_SkipPrev45Pass", np.where(dh["was_45_b6"].to_numpy(bool), -999.0, sc_base), "Base_V51", "Matched42CB", 88.0),
        # Exit transplants onto V5.1 & V21
        ("E_7f_NoImm_ge1", sc_base, "7f_NoImm_ge1", "Matched42CB", 88.0),
        ("E_7f_NoImm_ge2", sc_base, "7f_NoImm_ge2", "Matched42CB", 88.0),
        ("E_XF30_1345_7f", sc_base, "XF30_1345_7f", "Matched42CB", 88.0),
        ("E_XF30_1345_85", sc_base, "XF30_1345_85", "Matched42CB", 88.0),
        ("E_XF30_Full_3to4", sc_base, "XF30_Full", "Matched42CB", 88.0),
        ("E_V42_TP1_m6_1000", sc_base, "TP1_m6_1000", "Matched42CB", 88.0),
        ("E_V42_All_m6_1000", sc_base, "All_m6_1000", "Matched42CB", 88.0),
        ("E_CutWeak_V51", sc_base, "CutWeak_V51", "Matched42CB", 88.0),
        ("E_D4Strong_4to5", sc_base, "D4Strong_4to5", "Matched42CB", 88.0),
        ("E_Dev93_Uncond", sc_base, "Dev93_Uncond", "Matched42CB", 88.0),
        ("E_V21_7f_NoImm_ge2", sc_v21, "7f_NoImm_ge2", "Matched42CB", 88.0),
        ("E_V21_TP1_m6_1000", sc_v21, "TP1_m6_1000", "Matched42CB", 88.0),
        ("E_V21_D4Strong_4to5", sc_v21, "D4Strong_4to5", "Matched42CB", 88.0),
    ]

    wins_use = cm.WINDOWS_1116 if not trunc_date else [("FULL_5Y", "2021-11-16", trunc_date), ("IS_2123", "2021-11-16", "2023-12-31"), ("OOS_2426", "2024-01-01", trunc_date)]
    eval_results = {}
    ledgers = {}

    # Evaluate m42 ref separately
    d15_m42 = cm.evaluate_d15_windows(m42_df, m42_df, bench, wins_use, base_fee=0.0030, ret_col="net_ret_030")
    eval_results["Ref_V51_m42"] = {
        "d15": d15_m42,
        "boot_10k_30bps": cm.bootstrap_10k(m42_df["net_ret_030"].to_numpy(float)),
        "nav_20bps_ref": round(float(np.prod(1.0 + m42_df["net_ret_020"].to_numpy(float))), 4),
    }

    for vid, sc_vec, ex_m, cbm, thr in variants_spec:
        p_df, s_df = _run_high_slot(sc_vec, ex_m, cbm, thr)
        d15 = cm.evaluate_d15_windows(s_df, p_df, bench, wins_use, base_fee=0.0030, ret_col="net_ret_030")
        rets30 = s_df["net_ret_030"].to_numpy(float) if not s_df.empty else np.array([], dtype=float)
        rets20 = s_df["net_ret_020"].to_numpy(float) if not s_df.empty else np.array([], dtype=float)
        boot = cm.bootstrap_10k(rets30, n_boot=10000, seed=42)
        dr_v, mtm_diff = cm.daily_mtm_series(s_df, cal_dts, ret_col="net_ret_030")
        pt_vs_t42 = cm.paired_daily_ttest(dr_v, base_dr_full)
        pt_vs_v21 = cm.paired_daily_ttest(dr_v, v21_dr_full)

        # Dual-period lift vs Base_V51_t42 (or Base_V21)
        is_base = (vid.startswith("A_V21") or vid.startswith("E_V21"))
        ref_key = "Base_V21_ColdDrop40" if is_base else "Base_V51_t42"
        eval_results[vid] = {
            "exit_mode": ex_m,
            "cb_mode": cbm,
            "raw_n": int(len(p_df)),
            "ss_n": int(len(s_df)),
            "mtm_diff": round(float(mtm_diff), 10),
            "nav_20bps_ref": round(float(np.prod(1.0 + rets20)), 4) if len(rets20) else 1.0,
            "d15": d15,
            "boot_10k_30bps": boot,
            "paired_vs_t42": pt_vs_t42,
            "paired_vs_v21": pt_vs_v21,
            "ref_base": ref_key,
        }
        ledgers[vid] = (p_df, s_df)

    # Check dual-period gate on all non-baseline variants
    for vid, vd in eval_results.items():
        if vid.startswith(("Base_", "Ref_")):
            continue
        rb = eval_results[vd["ref_base"]]
        w_cur = vd["d15"]
        w_ref = rb["d15"]
        is_nav_ok = w_cur["IS_2123"]["nav"] > w_ref["IS_2123"]["nav"]
        oos_nav_ok = w_cur["OOS_2426"]["nav"] > w_ref["OOS_2426"]["nav"]
        is_sh_ok = w_cur["IS_2123"]["daily_sharpe"] >= w_ref["IS_2123"]["daily_sharpe"]
        oos_sh_ok = w_cur["OOS_2426"]["daily_sharpe"] >= w_ref["OOS_2426"]["daily_sharpe"]
        ex2_ok = w_cur["FULL_5Y"]["ex2_nav"] > w_ref["FULL_5Y"]["ex2_nav"]
        boot_ok = vd["boot_10k_30bps"]["mean_p05_pct"] >= rb["boot_10k_30bps"]["mean_p05_pct"]
        vd["promotion_check"] = {
            "is_nav_lift": is_nav_ok, "oos_nav_lift": oos_nav_ok,
            "is_sharpe_ge": is_sh_ok, "oos_sharpe_ge": oos_sh_ok,
            "ex2_lift": ex2_ok, "boot_p05_ge": boot_ok,
            "passes_strict_gate": bool(is_nav_ok and oos_nav_ok and is_sh_ok and oos_sh_ok and ex2_ok and boot_ok),
        }

    return {
        "parity_check": {
            "t42_parity_ok": parity_ok, "t42_max_ret_diff": round(max_ret_diff, 10),
            "t42_nav_20bps": round(float(np.prod(1.0 + s_base["net_ret_020"])), 4),
            "post_20261027_audit": post_audit,
        },
        "univariate_screen_46": univariate_rows,
        "variants": eval_results,
        "ledgers": ledgers,
        "feature_df": dh,
        "elapsed_sec": round(time.time() - t0, 2),
        "rss_mb": cm.rss_mb(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trunc-date", default="")
    parser.add_argument("--out-json", default="")
    args = parser.parse_args()

    trunc = args.trunc_date.strip() or None
    out = eval_high_variants(trunc_date=trunc)
    ledgers = out.pop("ledgers")
    feat_df = out.pop("feature_df")

    if args.out_json:
        with open(args.out_json, "w", encoding="utf-8") as f:
            json.dump(cm.sanitize_json(out), f, ensure_ascii=False)
        return

    with open(f"{cm.OUT_DIR}/dirA_results.json", "w", encoding="utf-8") as f:
        json.dump(cm.sanitize_json(out), f, ensure_ascii=False, indent=2)
    with open(f"{cm.OUT_DIR}/_cache_dirA_ledgers.pkl", "wb") as f:
        pickle.dump({"ledgers": ledgers, "feature_df": feat_df}, f)

    print(f"[DirA DONE in {out['elapsed_sec']}s] RSS={out['rss_mb']} MB | Parity={out['parity_check']['t42_parity_ok']} diff={out['parity_check']['t42_max_ret_diff']}")
    print("Post-2026-10-27 broken>=4b true-yang scan:", json.dumps(out["parity_check"]["post_20261027_audit"], ensure_ascii=False))
    print("\n=== Univariate Screen on High V5.1 (n=46 passing, 30bps) ===")
    udf = pd.DataFrame(out["univariate_screen_46"]).sort_values("diff_pp", ascending=False)
    print(udf.to_string(index=False))

    print("\n=== Direction A Variants Summary (30bps primary & 50bps stress) ===")
    rows = []
    for vid, vd in out["variants"].items():
        w5 = vd["d15"]["FULL_5Y"]
        wis = vd["d15"]["IS_2123"]
        woos = vd["d15"]["OOS_2426"]
        w25 = vd["d15"]["Y2025_2026"]
        w26 = vd["d15"]["Y2026"]
        wh2 = vd["d15"]["Y2026_H2"]
        bt = vd["boot_10k_30bps"]
        pc = vd.get("promotion_check", {}).get("passes_strict_gate", "-")
        rows.append({
            "vid": vid, "n": w5["ss_n"], "wr": w5["wr_pct"], "plr": w5["plr"],
            "nav5y": w5["nav"], "ex2": w5["ex2_nav"], "sh": w5["daily_sharpe"], "mdd": w5["daily_mdd_pct"],
            "xs300": w5["excess_csi300_pp"], "nav50b": w5["nav_50bps"],
            "is_n": wis["ss_n"], "is_nav": wis["nav"], "is_sh": wis["daily_sharpe"],
            "oos_n": woos["ss_n"], "oos_nav": woos["nav"], "oos_sh": woos["daily_sharpe"],
            "y2526": w25["nav"], "y26": w26["nav"], "y26h2": wh2["nav"],
            "bp05": bt["mean_p05_pct"], "gate": pc,
        })
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()

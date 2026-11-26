#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD046 Stage 2A: Real 5-Minute Intraday Replay for Prototype CB2
(Stock seals limit-up intraday -> buy CB 5m after first_seal_time -> T+0 15:00 / Stock-Break Cut / T+1 Open).
Fetches Sina 5m bars (datalen=20000, ~104 trading days) for:
  1. Unbiased 2026-06-25..2026-11-25 full cross-section (BOTH stock 5m & CB 5m, incl. delisted CBs in window!)
  2. Near-delist 2021-2026 CB2 events (<=130 cal days before eff_end_dt, CB 5m available for entry->15:00).
Zero yfinance (D12). Zero lookahead.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_k] = "1"
os.environ["NO_PROXY"] = "*"

import concurrent.futures as cf
import json
import sqlite3
import sys
import threading
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import requests

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd046_convertible_bond_t0_20261126"
STOCK_PARQUET = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base/stock_day_core_features_pit.parquet"
ZT_DB = f"{ROOT}/sim-portfolio/data/zt_micro_tape_5y_pit.db"

_tls = threading.local()


def _sess() -> requests.Session:
    if not hasattr(_tls, "s"):
        s = requests.Session()
        s.trust_env = False
        s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
        _tls.s = s
    return _tls.s


def fetch_sina_5m(sym: str) -> pd.DataFrame:
    s = _sess()
    for att in range(3):
        try:
            r = s.get(
                "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
                params={"symbol": sym, "scale": "5", "ma": "no", "datalen": "20000"},
                timeout=15,
            )
            txt = r.text.strip()
            if not txt or not txt.startswith("["):
                return pd.DataFrame()
            arr = json.loads(txt)
            if not arr:
                return pd.DataFrame()
            df = pd.DataFrame(arr)
            df["dt"] = df["day"].str[:10]
            df["hhmm"] = df["day"].str[11:13] + df["day"].str[14:16]
            for c in ("open", "high", "low", "close"):
                df[c] = pd.to_numeric(df[c], errors="coerce")
            return df[["dt", "hhmm", "open", "high", "low", "close"]]
        except Exception:
            time.sleep(0.35 * (att + 1))
    return pd.DataFrame()


def _stk_sym(c6: str) -> str:
    if c6.startswith(("60", "68", "90")):
        return f"sh{c6}"
    if c6.startswith(("00", "30")):
        return f"sz{c6}"
    return f"bj{c6}"


def main():
    t0 = time.time()
    cb = pd.read_parquet(f"{OUT_DIR}/cb_daily_all_pit.parquet")
    cb = cb.sort_values(["cb_code", "dt"]).reset_index(drop=True)
    g = cb.groupby("cb_code")
    cb["cb_prev_close"] = g["close"].shift(1)
    cb["cb_open_pct"] = cb["open"] / cb["cb_prev_close"] - 1.0
    cb["cb_next_open"] = g["open"].shift(-1)
    cb["cb_next_close"] = g["close"].shift(-1)
    cb["cb_prem_t1"] = g["conv_prem_pct"].shift(1)
    cb["cb_amt_t1"] = g["amount_yi"].shift(1)
    cb["cb_amt_5d_t1"] = g["amount_yi"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
    cb["cb_is_halt"] = (cb["vol_shou"] <= 0) | (cb["open"] <= 0)
    cb["cb_is_yizi"] = (
        ((cb["dt"] >= "2022-08-01") & (cb["cb_open_pct"] >= 0.195) & (cb["low"] >= cb["open"] * 0.999))
        | ((cb["open"] == cb["high"]) & (cb["open"] == cb["low"]) & (cb["open"] == cb["close"]) & (cb["cb_open_pct"] > 0.09))
    )

    stk = pq.read_table(
        STOCK_PARQUET,
        columns=["dt", "c6", "open", "close", "prev_close_raw", "open_pct", "is_zt", "hit_zt", "is_yizi_zt", "is_st_pit", "is_20cm", "list_age", "streak", "prev_streak", "amount_yi"],
    ).to_pandas()
    stk = stk.rename(columns={"c6": "stock_code", "open": "stk_open", "close": "stk_close", "amount_yi": "stk_amt_yi"})
    lim_rate = np.where(stk["is_st_pit"] == 1, 0.05, np.where(stk["is_20cm"] == 1, 0.20, 0.10))
    stk["zt_px_est"] = np.round(stk["prev_close_raw"] * (1.0 + lim_rate) + 1e-9, 2)
    stk["stk_open_at_zt"] = (stk["stk_open"] >= stk["zt_px_est"] - 0.011) & (stk["prev_close_raw"] > 0) & (stk["is_st_pit"] == 0) & (stk["list_age"] > 10)

    conn = sqlite3.connect(ZT_DB)
    zt_tape = pd.read_sql_query("SELECT trade_date as dt, sec_code as stock_code, first_seal_time, board_count, open_board_count, seal_amount FROM zt_micro_tape", conn)
    conn.close()

    m = cb[(cb["dt"] >= "2021-01-04") & (cb["dt"] <= "2026-11-24")].merge(stk, on=["dt", "stock_code"], how="inner")
    m = m.merge(zt_tape, on=["dt", "stock_code"], how="inner")
    m = m[(~m["cb_is_halt"]) & (~m["cb_is_yizi"]) & (m["cb_prev_close"].notna()) & (m["is_st_pit"] == 0) & (m["list_age"] > 10) & (~m["stk_open_at_zt"])].copy()
    m["seal_hhmm"] = m["first_seal_time"].astype(str).str.replace(":", "").str[:4]
    m = m[m["seal_hhmm"].str.match(r"^\d{4}$", na=False)].copy()
    m["is_unbiased_26h2"] = m["dt"] >= "2026-06-25"
    dt_ts = pd.to_datetime(m["dt"])
    end_ts = pd.to_datetime(m["eff_end_dt"])
    m["in_5m_cand"] = m["is_unbiased_26h2"] | ((end_ts - dt_ts).dt.days <= 135)
    cands = m[m["in_5m_cand"]].copy().reset_index(drop=True)
    print(f"[CB2] Candidate events in 5m window: {len(cands)} (unbiased 26H2={int(cands['is_unbiased_26h2'].sum())})")

    cb_syms = sorted(cands["cb_sym"].unique().tolist())
    stk_codes_26 = sorted(cands.loc[cands["is_unbiased_26h2"], "stock_code"].unique().tolist())
    stk_syms_26 = [_stk_sym(c) for c in stk_codes_26]
    all_syms = [(s, "cb") for s in cb_syms] + [(s, "stk") for s in stk_syms_26]
    print(f"[CB2] Fetching Sina 5m for {len(cb_syms)} CBs + {len(stk_syms_26)} 26H2 stocks...")

    cache_5m = {}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(fetch_sina_5m, sym): (sym, kind) for sym, kind in all_syms}
        for idx, fu in enumerate(cf.as_completed(futs), 1):
            sym, kind = futs[fu]
            df5 = fu.result()
            if not df5.empty:
                cache_5m[sym] = df5
            if idx % 150 == 0 or idx == len(all_syms):
                print(f"  5m progress {idx}/{len(all_syms)} ({time.time()-t0:.1f}s)")

    # Index by (sym, dt) for O(1) lookup
    by_sym_dt = {}
    for sym, df5 in cache_5m.items():
        for dt_v, grp in df5.groupby("dt"):
            by_sym_dt[(sym, dt_v)] = grp.sort_values("hhmm").reset_index(drop=True)

    rows_out = []
    for r in cands.itertuples(index=False):
        cb5 = by_sym_dt.get((r.cb_sym, r.dt))
        if cb5 is None or cb5.empty:
            continue
        # Seal bar ends at bar hhmm >= seal_hhmm (WAIT: Sina 5m bar hhmm is bar END time! e.g. 09:35 bar covers 09:30-09:35!)
        # To guarantee 100% zero lookahead, entry bar must start AFTER seal_hhmm:
        # i.e. bar hhmm > seal_hhmm + 5 min? Wait: if seal_hhmm == 0942, the 0945 bar covers 09:40-09:45.
        # So the NEXT bar (0950 bar, covering 09:45-09:50) starts strictly AFTER 09:45 (>= seal_hhmm)!
        # Let's check strict bar start: bar_end_hhmm > seal_hhmm -> that bar ends in (seal, seal+5m],
        # so its CLOSE is 0-5m after seal, and the NEXT bar's OPEN/CLOSE is strictly 0-5m / 5-10m AFTER that bar finishes!
        seal_i = int(r.seal_hhmm)
        hh_arr = cb5["hhmm"].astype(int).to_numpy()
        # First bar whose END time > seal_i (so seal happened inside or before this bar)
        idx_cands = np.where(hh_arr > seal_i)[0]
        if len(idx_cands) < 2:
            continue
        b_seal = int(idx_cands[0])
        b_next = b_seal + 1  # Strictly starts AFTER seal bar closed -> zero-lookahead!
        if b_next >= len(cb5):
            continue
        # Also ignore if entry bar is already 14:55 or 15:00 (too late for T+0)
        if int(cb5.iloc[b_next]["hhmm"]) >= 1455:
            continue

        # Check if CB already locked at 20% limit-up on b_next bar (unbuyable)
        px_b_next_open = float(cb5.iloc[b_next]["open"])
        px_b_next_close = float(cb5.iloc[b_next]["close"])
        if r.dt >= "2022-08-01":
            lim_20 = round(float(r.cb_prev_close) * 1.20, 3)
            if px_b_next_open >= lim_20 * 0.998 and float(cb5.iloc[b_next]["low"]) >= px_b_next_open * 0.999:
                continue  # CB locked at 20% limit-up at entry bar!

        px_1500 = float(cb5.iloc[-1]["close"])  # Actual 15:00 close from 5m (or daily close)
        # Verify px_1500 matches daily close closely
        if abs(px_1500 - float(r.close)) / max(1e-6, float(r.close)) > 0.01:
            px_1500 = float(r.close)

        # Stock-break cut in 26H2: check stock 5m after b_next
        px_brk_cut = px_1500
        did_break_cut = False
        stk5 = by_sym_dt.get((_stk_sym(r.stock_code), r.dt))
        if stk5 is not None and not stk5.empty:
            # Find bars after b_next's hhmm where stk_close < zt_px_est - 0.011
            entry_hhmm = int(cb5.iloc[b_next]["hhmm"])
            stk_after = stk5[stk5["hhmm"].astype(int) >= entry_hhmm]
            brk_bars = stk_after[stk_after["close"] < float(r.zt_px_est) - 0.011]
            if not brk_bars.empty:
                brk_hhmm = int(brk_bars.iloc[0]["hhmm"])
                # Cut CB at strictly NEXT 5m bar after brk_hhmm
                cb_cut = cb5[cb5["hhmm"].astype(int) > brk_hhmm]
                if not cb_cut.empty:
                    px_brk_cut = float(cb_cut.iloc[0]["open"])
                    did_break_cut = True

        ret_day_oc = float(r.close) / float(r.open) - 1.0
        ret_5m_open_t0 = px_1500 / px_b_next_open - 1.0
        ret_5m_close_t0 = px_1500 / px_b_next_close - 1.0
        ret_5m_brkcut_t0 = px_brk_cut / px_b_next_open - 1.0
        ret_5m_t1o = (float(r.cb_next_open) / px_b_next_open - 1.0) if pd.notna(r.cb_next_open) else np.nan
        ret_5m_t1c = (float(r.cb_next_close) / px_b_next_open - 1.0) if pd.notna(r.cb_next_close) else np.nan
        cb_pre_run = px_b_next_open / float(r.cb_prev_close) - 1.0

        rows_out.append({
            "dt": r.dt,
            "cb_code": r.cb_code,
            "cb_name": r.cb_name,
            "stock_code": r.stock_code,
            "is_delisted": bool(r.is_delisted),
            "is_unbiased_26h2": bool(r.is_unbiased_26h2),
            "seal_hhmm": int(r.seal_hhmm),
            "entry_bar_hhmm": int(cb5.iloc[b_next]["hhmm"]),
            "is_zt": int(r.is_zt),
            "is_20cm": int(r.is_20cm),
            "streak": int(r.streak),
            "open_board_count": int(r.open_board_count) if pd.notna(r.open_board_count) else 0,
            "cb_prev_close": float(r.cb_prev_close),
            "cb_prem_t1": float(r.cb_prem_t1) if pd.notna(r.cb_prem_t1) else np.nan,
            "cb_amt_t1": float(r.cb_amt_t1) if pd.notna(r.cb_amt_t1) else np.nan,
            "cb_amt_5d_t1": float(r.cb_amt_5d_t1) if pd.notna(r.cb_amt_5d_t1) else np.nan,
            "cb_pre_run_pct": round(cb_pre_run * 100.0, 2),
            "ret_day_oc_peek": ret_day_oc,
            "ret_5m_open_t0": ret_5m_open_t0,
            "ret_5m_close_t0": ret_5m_close_t0,
            "ret_5m_brkcut_t0": ret_5m_brkcut_t0,
            "did_break_cut": did_break_cut,
            "ret_5m_t1o": ret_5m_t1o,
            "ret_5m_t1c": ret_5m_t1c,
        })

    res_df = pd.DataFrame(rows_out)
    res_df.to_parquet(f"{OUT_DIR}/cb2_5m_replay.parquet", index=False)

    def _s(sub, col):
        s = sub[col].dropna()
        if len(s) == 0:
            return {"n": 0}
        return {
            "n": int(len(s)),
            "wr_pct": round(float((s > 0).mean() * 100.0), 2),
            "mean_pct": round(float(s.mean() * 100.0), 2),
            "med_pct": round(float(s.median() * 100.0), 2),
        }

    u26 = res_df[res_df["is_unbiased_26h2"]]
    summary = {
        "total_5m_replayed": int(len(res_df)),
        "unbiased_26h2_count": int(len(u26)),
        "unbiased_26h2": {
            "all_day_oc_peek": _s(u26, "ret_day_oc_peek"),
            "all_5m_open_t0": _s(u26, "ret_5m_open_t0"),
            "all_5m_close_t0": _s(u26, "ret_5m_close_t0"),
            "all_5m_brkcut_t0": _s(u26, "ret_5m_brkcut_t0"),
            "all_5m_t1o": _s(u26, "ret_5m_t1o"),
            "seal_le_0945_t0": _s(u26[u26["seal_hhmm"] <= 945], "ret_5m_open_t0"),
            "seal_le_1030_t0": _s(u26[u26["seal_hhmm"] <= 1030], "ret_5m_open_t0"),
            "prem_lt15_t0": _s(u26[u26["cb_prem_t1"] < 15], "ret_5m_open_t0"),
            "prem_lt15_brkcut_t0": _s(u26[u26["cb_prem_t1"] < 15], "ret_5m_brkcut_t0"),
            "held_zt_5m_t0": _s(u26[u26["is_zt"] == 1], "ret_5m_open_t0"),
            "broken_zt_5m_t0": _s(u26[u26["is_zt"] == 0], "ret_5m_open_t0"),
            "broken_zt_brkcut_t0": _s(u26[u26["is_zt"] == 0], "ret_5m_brkcut_t0"),
            "mean_pre_run_pct": round(float(u26["cb_pre_run_pct"].mean()), 2) if len(u26) else 0.0,
        },
        "all_5m_sample_incl_neardelist": {
            "all_day_oc_peek": _s(res_df, "ret_day_oc_peek"),
            "all_5m_open_t0": _s(res_df, "ret_5m_open_t0"),
            "all_5m_close_t0": _s(res_df, "ret_5m_close_t0"),
            "all_5m_t1o": _s(res_df, "ret_5m_t1o"),
            "seal_le_0945_t0": _s(res_df[res_df["seal_hhmm"] <= 945], "ret_5m_open_t0"),
            "seal_le_1030_t0": _s(res_df[res_df["seal_hhmm"] <= 1030], "ret_5m_open_t0"),
            "prem_lt10_t0": _s(res_df[res_df["cb_prem_t1"] < 10], "ret_5m_open_t0"),
            "prem_lt15_t0": _s(res_df[res_df["cb_prem_t1"] < 15], "ret_5m_open_t0"),
            "px_lt120_t0": _s(res_df[res_df["cb_prev_close"] < 120], "ret_5m_open_t0"),
            "px_120_150_t0": _s(res_df[res_df["cb_prev_close"].between(120, 150)], "ret_5m_open_t0"),
            "px_gt150_t0": _s(res_df[res_df["cb_prev_close"] > 150], "ret_5m_open_t0"),
            "mean_pre_run_pct": round(float(res_df["cb_pre_run_pct"].mean()), 2) if len(res_df) else 0.0,
        },
        "elapsed_sec": round(time.time() - t0, 2),
    }
    with open(f"{OUT_DIR}/cb2_5m_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

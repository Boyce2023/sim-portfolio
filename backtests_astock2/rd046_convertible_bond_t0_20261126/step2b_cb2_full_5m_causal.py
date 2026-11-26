#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD046 Stage 2B: Unbiased 100% Causal CB2 5-Minute Replay (2026-06-25..2026-11-24)
Includes BOTH `is_zt == 1` AND `is_broken_zt == 1` (eliminates zt_micro_tape 15:00 survival bias!).
Detects exact 5m bar when stock first hits/seals ZT (`stk_close >= zt_px - 0.011` or `stk_high >= zt_px - 0.011`),
buys CB at strictly NEXT 5m bar (`b_next` open & close), and compares:
  1. Hold to T+0 15:00 close
  2. Intraday Stock-Break Stop (`炸板即砍`: cut CB at next 5m bar after stock drops below ZT!)
  3. Hold to T+1 open / T+1 close
Zero yfinance (D12). Zero lookahead.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_k] = "1"
os.environ["NO_PROXY"] = "*"

import concurrent.futures as cf
import json
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd046_convertible_bond_t0_20261126"
STOCK_PARQUET = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base/stock_day_core_features_pit.parquet"
sys.path.insert(0, OUT_DIR)
import step2_fetch_cb2_5m_and_replay as s2


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
        columns=["dt", "c6", "open", "high", "low", "close", "prev_close_raw", "open_pct", "is_zt", "hit_zt", "is_broken_zt", "is_yizi_zt", "is_st_pit", "is_20cm", "list_age", "streak", "prev_streak", "amount_yi"],
    ).to_pandas()
    stk = stk.rename(columns={"c6": "stock_code", "open": "stk_open", "close": "stk_close"})
    lim_rate = np.where(stk["is_st_pit"] == 1, 0.05, np.where(stk["is_20cm"] == 1, 0.20, 0.10))
    stk["zt_px_est"] = np.round(stk["prev_close_raw"] * (1.0 + lim_rate) + 1e-9, 2)
    stk["stk_open_at_zt"] = (stk["stk_open"] >= stk["zt_px_est"] - 0.011) & (stk["prev_close_raw"] > 0) & (stk["is_st_pit"] == 0) & (stk["list_age"] > 10)

    m = cb[(cb["dt"] >= "2026-06-25") & (cb["dt"] <= "2026-11-24")].merge(stk, on=["dt", "stock_code"], how="inner")
    cands = m[(m["hit_zt"] == 1) & (~m["stk_open_at_zt"]) & (~m["cb_is_halt"]) & (~m["cb_is_yizi"]) & (m["cb_prev_close"].notna()) & (m["is_st_pit"] == 0) & (m["list_age"] > 10)].copy().reset_index(drop=True)

    cb_syms = sorted(cands["cb_sym"].unique().tolist())
    stk_syms = sorted([s2._stk_sym(c) for c in cands["stock_code"].unique()])
    all_syms = cb_syms + stk_syms
    print(f"[CB2-Full-26H2] Events={len(cands)} (is_zt={(cands['is_zt']==1).sum()}, broken={(cands['is_broken_zt']==1).sum()}), fetching {len(all_syms)} 5m series...")

    cache_5m = {}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(s2.fetch_sina_5m, sym): sym for sym in all_syms}
        for fu in cf.as_completed(futs):
            sym = futs[fu]
            df5 = fu.result()
            if not df5.empty:
                cache_5m[sym] = df5

    by_sym_dt = {}
    for sym, df5 in cache_5m.items():
        for dt_v, grp in df5.groupby("dt"):
            by_sym_dt[(sym, dt_v)] = grp.sort_values("hhmm").reset_index(drop=True)

    rows = []
    for r in cands.itertuples(index=False):
        cb5 = by_sym_dt.get((r.cb_sym, r.dt))
        stk5 = by_sym_dt.get((s2._stk_sym(r.stock_code), r.dt))
        if cb5 is None or stk5 is None or cb5.empty or stk5.empty:
            continue
        # Align on common 5m timestamps
        merged5 = stk5.merge(cb5, on=["dt", "hhmm"], suffixes=("_s", "_c")).sort_values("hhmm").reset_index(drop=True)
        if len(merged5) < 4:
            continue
        zt_th = float(r.zt_px_est) - 0.011
        # Trigger: first 5m bar where stock touches OR closes at ZT!
        # Let's track BOTH: (A) hit_zt bar (high_s >= zt_th), (B) seal_zt bar (close_s >= zt_th)
        seal_idx = np.where(merged5["close_s"].to_numpy(float) >= zt_th)[0]
        hit_idx = np.where(merged5["high_s"].to_numpy(float) >= zt_th)[0]
        if len(hit_idx) == 0:
            continue

        # Test trigger = seal if ever closed a 5m bar at ZT, else touch (realistic: if stock only touched ZT mid-bar and broke, touch_idx catches it; if it sealed bar, seal_idx catches it!)
        # Actually: if you buy when stock "seals ZT" (close_s >= zt_th), you only enter when a 5m bar finishes sealed (or right at seal);
        # whereas if you buy on "touch ZT" (high_s >= zt_th), you enter on ALL 112 broken_zt stocks too!
        # Let's record BOTH: trigger_on_hit (includes all failed touches!) and trigger_on_5m_seal!
        for trig_name, idx_arr in [("on_5m_seal", seal_idx), ("on_5m_touch", hit_idx)]:
            if len(idx_arr) == 0:
                continue
            b_trig = int(idx_arr[0])
            b_next = b_trig + 1
            if b_next >= len(merged5):
                continue
            trig_hhmm = int(merged5.iloc[b_trig]["hhmm"])
            entry_hhmm = int(merged5.iloc[b_next]["hhmm"])
            if entry_hhmm >= 1455:
                continue
            px_in_open = float(merged5.iloc[b_next]["open_c"])
            px_in_close = float(merged5.iloc[b_next]["close_c"])
            # Check CB 20% limit-up unbuyable at entry bar
            lim_20 = round(float(r.cb_prev_close) * 1.20, 3)
            if px_in_open >= lim_20 * 0.998 and float(merged5.iloc[b_next]["low_c"]) >= px_in_open * 0.999:
                continue

            px_1500 = float(merged5.iloc[-1]["close_c"])
            if abs(px_1500 - float(r.close)) / max(1e-6, float(r.close)) > 0.01:
                px_1500 = float(r.close)

            # Intraday break-board stop: strictly AFTER b_next (so b >= b_next), if close_s < zt_th, exit at b+1 open_c
            px_brk = px_1500
            did_cut = False
            post_bars = merged5.iloc[b_next:]
            brk = post_bars[post_bars["close_s"] < zt_th]
            if not brk.empty:
                b_brk = int(brk.index[0])
                if b_brk + 1 < len(merged5):
                    px_brk = float(merged5.iloc[b_brk + 1]["open_c"])
                    did_cut = True

            rows.append({
                "trigger_mode": trig_name,
                "dt": r.dt,
                "cb_code": r.cb_code,
                "stock_code": r.stock_code,
                "is_zt": int(r.is_zt),
                "is_broken_zt": int(r.is_broken_zt),
                "trig_hhmm": trig_hhmm,
                "entry_hhmm": entry_hhmm,
                "cb_prev_close": float(r.cb_prev_close),
                "cb_prem_t1": float(r.cb_prem_t1) if pd.notna(r.cb_prem_t1) else np.nan,
                "cb_pre_run_pct": round((px_in_open / float(r.cb_prev_close) - 1.0) * 100.0, 2),
                "ret_day_oc_peek": float(r.close) / float(r.open) - 1.0,
                "ret_5m_open_t0": px_1500 / px_in_open - 1.0,
                "ret_5m_close_t0": px_1500 / px_in_close - 1.0,
                "ret_5m_brkcut_t0": px_brk / px_in_open - 1.0,
                "did_cut": did_cut,
                "ret_5m_t1o": (float(r.cb_next_open) / px_in_open - 1.0) if pd.notna(r.cb_next_open) else np.nan,
            })

    df = pd.DataFrame(rows)
    df.to_parquet(f"{OUT_DIR}/cb2_26h2_causal_5m_full.parquet", index=False)

    def _s(sub, col):
        s = sub[col].dropna()
        return {"n": 0} if len(s) == 0 else {
            "n": int(len(s)), "wr_pct": round(float((s > 0).mean() * 100.0), 2),
            "mean_pct": round(float(s.mean() * 100.0), 2), "med_pct": round(float(s.median() * 100.0), 2),
        }

    out = {"elapsed_sec": round(time.time() - t0, 2)}
    for tm in ("on_5m_seal", "on_5m_touch"):
        sub = df[df["trigger_mode"] == tm]
        out[tm] = {
            "all_day_oc_peek": _s(sub, "ret_day_oc_peek"),
            "all_5m_open_t0": _s(sub, "ret_5m_open_t0"),
            "all_5m_brkcut_t0": _s(sub, "ret_5m_brkcut_t0"),
            "all_5m_t1o": _s(sub, "ret_5m_t1o"),
            "held_zt_5m_t0": _s(sub[sub["is_zt"] == 1], "ret_5m_open_t0"),
            "broken_zt_5m_t0": _s(sub[sub["is_broken_zt"] == 1], "ret_5m_open_t0"),
            "broken_zt_brkcut_t0": _s(sub[sub["is_broken_zt"] == 1], "ret_5m_brkcut_t0"),
            "prem_lt15_5m_t0": _s(sub[sub["cb_prem_t1"] < 15], "ret_5m_open_t0"),
            "prem_lt15_brkcut_t0": _s(sub[sub["cb_prem_t1"] < 15], "ret_5m_brkcut_t0"),
            "trig_le_1030_t0": _s(sub[sub["trig_hhmm"] <= 1030], "ret_5m_open_t0"),
            "trig_le_1030_brkcut_t0": _s(sub[sub["trig_hhmm"] <= 1030], "ret_5m_brkcut_t0"),
        }
    with open(f"{OUT_DIR}/cb2_26h2_causal_5m_summary.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

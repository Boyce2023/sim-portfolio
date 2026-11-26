#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD035 Wave 1-B Deliverable 1:
  1. 100% exact reproduction of V20.0 6 standalone strategies + combined single-slot (278 trades, 69,134,091.51x).
  2. Daily slot calendar `v20_daily_slot_calendar_5y.parquet` (2021-11-16..2026-11-16, 1,212 trading days)
     + `v20_daily_slot_calendar_to_20261125.parquet` (1,219 days) + `v20_daily_bench_20210104_20261125.parquet`.
  3. Empty-slot statistics & regime breakdown into `v20_baseline_parity.json`.

Zero yfinance (D12). Zero cap10m. Read-only on production scripts and strategy_astock.md.
"""
import bisect
import json
import os
import re
import sqlite3
import sys
import time
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True
warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
RD028_DIR = f"{SIM}/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
RD034_DIR = f"{SIM}/backtests_astock2/rd034_ashare_3layer_cycles_6strat_20261125"
OUT_DIR = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
os.makedirs(OUT_DIR, exist_ok=True)

if RD028_DIR not in sys.path:
    sys.path.insert(0, RD028_DIR)
import step4_mod_rules_and_sim as m1

A_DAILY = f"{SIM}/data/cn_hk_price_db/a_daily.parquet"
A_DELISTED = f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet"
DB_ZT = f"{SIM}/data/zt_micro_tape_5y_pit.db"
REG_TOX_PQ = f"{SIM}/data/pit_reg_tox_notices_5y_complete.parquet"
MKT_PIT_PQ = f"{RD034_DIR}/rd034_market_daily_pit.parquet"

ST_ON_RE = re.compile(r"(?:^(?:\*?ST|S\*?ST)|(?:股票交易|股票)(?:被)?实施(?:退市|其他)风险警示|进入退市整理期|作出.*终止上市)")
ST_EXC_RE = re.compile(r"(?:可能被实施|不实施|未实施|免于实施|申请撤销|撤销.*风险警示)")
ST_REV_RE = re.compile(r"(?:撤销(?:退市|其他)风险警示|股票交易撤销.*风险警示)")
SENT_NAME = {1: "1_冰点", 2: "2_修复", 3: "3_主升", 4: "4_高潮", 5: "5_退潮"}
REG3_MAP = {1: "冰点", 2: "震荡", 5: "震荡", 3: "主升", 4: "主升"}


def build_alla_ew_series(cal_dts: list[str]) -> dict[str, float]:
    """Compute tradable non-ST All-A equal-weight daily return across cal_dts (strictly <= 2026-11-25)."""
    st_ev = defaultdict(list)
    con_z = sqlite3.connect(f"file:{DB_ZT}?mode=ro", uri=True)
    for td, sc6, nm in con_z.execute("SELECT trade_date, sec_code, sec_name FROM zt_micro_tape WHERE trade_date <= '2026-11-25'"):
        s = str(nm or "").strip()
        if s:
            st_ev[str(sc6).zfill(6)].append((f"{td} 15:00:00", 1 if ("ST" in s.upper() or "退" in s) else 0))
    con_z.close()
    rt = pd.read_parquet(REG_TOX_PQ, columns=["sec_code", "pub_datetime_cst", "title"])
    rt["ts"] = rt["pub_datetime_cst"].astype(str).str[:19]
    rt = rt[rt["ts"] <= "2026-11-25 23:59:59"]
    for r in rt.itertuples(index=False):
        t_s = str(r.title or "")
        c6 = str(r.sec_code)[:6].zfill(6)
        if ST_REV_RE.search(t_s):
            st_ev[c6].append((r.ts, 0))
        elif ST_ON_RE.search(t_s) and not ST_EXC_RE.search(t_s):
            st_ev[c6].append((r.ts, 1))
    st_tl = {k: ([x[0] for x in sorted(v)], [x[1] for x in sorted(v)]) for k, v in st_ev.items()}

    cols = ["date", "ticker", "adj_close", "volume"]
    flt = (ds.field("date") >= pd.Timestamp("2020-10-01")) & (ds.field("date") <= pd.Timestamp("2026-11-25"))
    da = ds.dataset(A_DAILY, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    dd = ds.dataset(A_DELISTED, format="parquet").scanner(columns=cols, filter=flt).to_table().to_pandas()
    da["dl"], dd["dl"] = 0, 1
    df = pd.concat([da, dd], ignore_index=True)
    del da, dd
    tk = df["ticker"].astype(str)
    df["c6"] = tk.str[:6]
    df = df[tk.str.endswith((".SH", ".SZ")) & df["c6"].str.startswith(("00", "60", "30", "688", "689")) & (df["adj_close"] > 0)].copy()
    df["dt"] = df["date"].dt.strftime("%Y-%m-%d")
    df.sort_values(["c6", "dt", "dl"], inplace=True)
    df.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df.reset_index(drop=True, inplace=True)

    c6_arr = df["c6"].to_numpy()
    dt_arr = df["dt"].to_numpy()
    same_c6 = np.empty(len(df), dtype=bool)
    same_c6[0] = False
    same_c6[1:] = c6_arr[1:] == c6_arr[:-1]
    ac = df["adj_close"].to_numpy(float)
    vol = df["volume"].fillna(0.0).to_numpy(float)
    pac = np.empty(len(df), dtype=float); pac[0] = np.nan; pac[1:] = np.where(same_c6[1:], ac[:-1], np.nan)
    pvol = np.empty(len(df), dtype=float); pvol[0] = 0.0; pvol[1:] = np.where(same_c6[1:], vol[:-1], 0.0)
    ret = np.where((pac > 0) & (vol > 0) & (pvol > 0), ac / pac - 1.0, np.nan)
    age = (df.groupby("c6", sort=False).cumcount() + 1).to_numpy()

    st_arr = np.zeros(len(df), dtype=bool)
    i, n_tot = 0, len(df)
    while i < n_tot:
        c = c6_arr[i]
        j = i + 1
        while j < n_tot and c6_arr[j] == c:
            j += 1
        tl = st_tl.get(c)
        if tl:
            ts_l, val_l = tl
            for k in range(i, j):
                idx = bisect.bisect_left(ts_l, f"{dt_arr[k]} 15:00:00")
                if idx > 0 and val_l[idx - 1] == 1:
                    st_arr[k] = True
        i = j

    ok = (~st_arr) & (age > 20) & np.isfinite(ret) & (np.abs(ret) <= 0.22)
    ew = df.loc[ok, ["dt"]].assign(ret=ret[ok]).groupby("dt")["ret"].mean().reindex(cal_dts).fillna(0.0)
    return {str(d): float(v) for d, v in ew.items()}


def build_slot_calendar(
    cal_dts: list[str],
    tr_c: pd.DataFrame,
    waits: list[dict],
    dr_v20: np.ndarray,
    sh300: dict[str, float],
    all_sh_dts: list[str],
    alla_ew_map: dict[str, float],
    mkt_pit: pd.DataFrame,
) -> pd.DataFrame:
    T = len(cal_dts)
    dt_idx = {d: i for i, d in enumerate(cal_dts)}
    occ = np.zeros(T, dtype=bool)
    strat_arr = np.empty(T, dtype=object); strat_arr[:] = None
    code_arr = np.empty(T, dtype=object); code_arr[:] = None
    ent_arr = np.empty(T, dtype=object); ent_arr[:] = None
    ext_arr = np.empty(T, dtype=object); ext_arr[:] = None
    bhh_arr = [None] * T
    ehh_arr = [None] * T

    for r in tr_c.itertuples(index=False):
        bi = dt_idx.get(str(r.buy_date))
        ei = dt_idx.get(str(r.exit_date))
        if bi is None or ei is None:
            continue
        for k in range(bi, ei + 1):
            occ[k] = True
            strat_arr[k] = r.strategy
            code_arr[k] = r.code
            ent_arr[k] = r.buy_date
            ext_arr[k] = r.exit_date
            bhh_arr[k] = int(r.buy_hhmm)
            ehh_arr[k] = int(r.exit_hhmm)

    wait_dts = {w["buy_date"] for w in waits}
    stier_wait_dts = {w["buy_date"] for w in waits if w["wait_tier"] in ("3to4_S(>=102)", "high_S(>=96)")}
    has_wait = np.array([d in wait_dts for d in cal_dts], dtype=bool)
    has_stier_wait = np.array([d in stier_wait_dts for d in cal_dts], dtype=bool)
    empty = ~occ

    empty_streak = np.zeros(T, dtype=np.int32)
    cur = 0
    for i in range(T):
        cur = (cur + 1) if empty[i] else 0
        empty_streak[i] = cur
    prior_streak = np.zeros(T, dtype=np.int32)
    prior_streak[1:] = empty_streak[:-1]

    future_free = np.zeros(T, dtype=np.int32)
    nxt = 0
    for i in range(T - 1, -1, -1):
        nxt = (nxt + 1) if empty[i] else 0
        future_free[i] = nxt

    sh_pos = {d: i for i, d in enumerate(all_sh_dts)}
    csi_r = np.array([sh300[d] / sh300[all_sh_dts[sh_pos[d] - 1]] - 1.0 for d in cal_dts], dtype=float)
    ew_r = np.array([alla_ew_map.get(d, 0.0) for d in cal_dts], dtype=float)

    mp = mkt_pit.set_index("dt")
    ph = mp.reindex(cal_dts)["L1_sent_phase_t1"].fillna(3).astype(int).to_numpy()
    zt_t1 = mp.reindex(cal_dts)["L1_zt_cnt_t1"].fillna(0.0).to_numpy(float)

    return pd.DataFrame({
        "trade_date": cal_dts,
        "v20_occupied": occ,
        "v20_empty_slot": empty,
        "v20_has_wait": has_wait,
        "v20_has_stier_wait": has_stier_wait,
        "v20_empty_strict_no_stier_wait": empty & (~has_stier_wait),
        "empty_streak_len": empty_streak,
        "prior_empty_streak_len": prior_streak,
        "future_free_days": future_free,
        "v20_strat": strat_arr,
        "v20_code": code_arr,
        "v20_entry_date": ent_arr,
        "v20_exit_date": ext_arr,
        "v20_buy_hhmm": pd.array(bhh_arr, dtype="Int32"),
        "v20_exit_hhmm": pd.array(ehh_arr, dtype="Int32"),
        "v20_daily_ret": dr_v20,
        "csi300_daily_ret": csi_r,
        "alla_ew_daily_ret": ew_r,
        "sent_phase_t1": ph,
        "sent_phase_name_t1": [SENT_NAME.get(int(x), "3_主升") for x in ph],
        "regime_3bucket_t1": [REG3_MAP.get(int(x), "震荡") for x in ph],
        "zt_cnt_t1": zt_t1,
    })


def summarize_empty_slots(cal_df: pd.DataFrame, windows: list[tuple[str, str, str]]) -> dict:
    out = {}
    for wname, sdt, edt in windows:
        sub = cal_df[cal_df["trade_date"].between(sdt, edt)]
        n_tot = int(len(sub))
        emp = sub[sub["v20_empty_slot"]]
        n_emp = int(len(emp))
        n_occ = n_tot - n_emp
        r3 = emp["regime_3bucket_t1"].value_counts().to_dict()
        r5 = emp["sent_phase_name_t1"].value_counts().to_dict()
        r3_all = sub["regime_3bucket_t1"].value_counts().to_dict()
        out[wname] = {
            "window": f"{sdt} ~ {edt}",
            "n_trading_days": n_tot,
            "v20_occupied_days": n_occ,
            "v20_occupied_pct": round(n_occ / max(1, n_tot) * 100.0, 2),
            "v20_empty_days": n_emp,
            "v20_empty_pct": round(n_emp / max(1, n_tot) * 100.0, 2),
            "v20_empty_strict_no_stier_wait_days": int(sub["v20_empty_strict_no_stier_wait"].sum()),
            "empty_days_regime_3bucket": {k: int(r3.get(k, 0)) for k in ("冰点", "震荡", "主升")},
            "empty_days_regime_3bucket_pct": {k: round(r3.get(k, 0) / max(1, n_emp) * 100.0, 2) for k in ("冰点", "震荡", "主升")},
            "empty_days_sent_phase_5state": {k: int(r5.get(k, 0)) for k in ("1_冰点", "2_修复", "3_主升", "4_高潮", "5_退潮")},
            "all_days_regime_3bucket": {k: int(r3_all.get(k, 0)) for k in ("冰点", "震荡", "主升")},
            "empty_streak_mean_days": round(float(emp.loc[emp["future_free_days"] > 0, "empty_streak_len"].mean()) if n_emp else 0.0, 2),
            "empty_streak_max_days": int(emp["empty_streak_len"].max()) if n_emp else 0,
        }
    return out


def main():
    t0 = time.time()
    codes = set()
    for st in m1.STRAT_ORDER:
        d = pd.read_parquet(f"{RD028_DIR}/pool_{st}_oldhot.parquet")
        codes.update(d["code"].astype(str).str.zfill(6))
    sh300, all_sh_dts, cal_full, cal_5y, bar_lu = m1.load_calendars_and_bars(codes)
    pools = m1.load_pools_oldhot(cal_full, cal_5y, bar_lu)
    untrig = m1.load_untrig_with_oldhot()
    parity_rep = m1.verify_all_baselines(pools, untrig)
    tr_c, waits = m1.run_combined_v20(pools, untrig, {})
    dr_5y, mtm_diff_5y = m1.daily_mtm_from_segs(tr_c, len(cal_5y), "mtm_5y")
    assert mtm_diff_5y < 1e-3, f"MTM diff={mtm_diff_5y}"

    cal_to_25 = [d for d in all_sh_dts if "2021-11-16" <= d <= "2026-11-25"]
    cal_bench = [d for d in all_sh_dts if "2021-01-04" <= d <= "2026-11-25"]
    alla_ew_map = build_alla_ew_series(cal_bench)
    mkt_pit = pd.read_parquet(MKT_PIT_PQ)

    cal_df_5y = build_slot_calendar(cal_5y, tr_c, waits, dr_5y, sh300, all_sh_dts, alla_ew_map, mkt_pit)
    dr_to_25 = np.zeros(len(cal_to_25), dtype=float)
    dr_to_25[:len(cal_5y)] = dr_5y
    cal_df_ext = build_slot_calendar(cal_to_25, tr_c, waits, dr_to_25, sh300, all_sh_dts, alla_ew_map, mkt_pit)
    cal_df_ext["in_v20_5y_1212"] = cal_df_ext["trade_date"] <= "2026-11-16"

    sh_pos = {d: i for i, d in enumerate(all_sh_dts)}
    mp = mkt_pit.set_index("dt")
    ph_b = mp.reindex(cal_bench)["L1_sent_phase_t1"].fillna(3).astype(int).to_numpy()
    bench_df = pd.DataFrame({
        "trade_date": cal_bench,
        "csi300_daily_ret": [sh300[d] / sh300[all_sh_dts[sh_pos[d] - 1]] - 1.0 for d in cal_bench],
        "alla_ew_daily_ret": [alla_ew_map.get(d, 0.0) for d in cal_bench],
        "sent_phase_t1": ph_b,
        "regime_3bucket_t1": [REG3_MAP.get(int(x), "震荡") for x in ph_b],
    })

    # Serialize V20.0 278-trade ledger with MTM date-mult pairs for instant zero-I/O Wave2 collision sim
    tr_save = tr_c.drop(columns=["mtm_full", "mtm_5y"]).copy()
    tr_save["mtm_pairs_json"] = [
        json.dumps([[cal_5y[t_i], round(float(mult), 10)] for t_i, mult in segs])
        for segs in tr_c["mtm_5y"]
    ]
    tr_save.to_parquet(f"{OUT_DIR}/v20_baseline_ledger_278.parquet", index=False)
    cal_df_5y.to_parquet(f"{OUT_DIR}/v20_daily_slot_calendar_5y.parquet", index=False)
    cal_df_ext.to_parquet(f"{OUT_DIR}/v20_daily_slot_calendar_to_20261125.parquet", index=False)
    bench_df.to_parquet(f"{OUT_DIR}/v20_daily_bench_20210104_20261125.parquet", index=False)
    with open(f"{OUT_DIR}/v20_waits_41.json", "w", encoding="utf-8") as f:
        json.dump(waits, f, ensure_ascii=False, indent=2)

    empty_stats_5y = summarize_empty_slots(cal_df_5y, [
        ("5y_canonical_1212d", "2021-11-16", "2026-11-16"),
        ("wf_2023_2026", "2023-01-03", "2026-11-16"),
        ("y2025_2026", "2025-01-01", "2026-11-16"),
        ("y2026", "2026-01-01", "2026-11-16"),
    ])
    empty_stats_to25 = summarize_empty_slots(cal_df_ext, [
        ("ext_to_20261125_1219d", "2021-11-16", "2026-11-25"),
        ("wf_2023_20261125", "2023-01-03", "2026-11-25"),
        ("y2025_20261125", "2025-01-01", "2026-11-25"),
        ("y2026_to_1125", "2026-01-01", "2026-11-25"),
    ])

    parity_out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "d12_yfinance_imported": "yfinance" in sys.modules,
        "calendar_note": (
            "Canonical V20.0 5-year calendar `v20_daily_slot_calendar_5y.parquet` spans 2021-11-16..2026-11-16 (exact 1,212 trading days). "
            "Extended file `v20_daily_slot_calendar_to_20261125.parquet` covers 2021-11-16..2026-11-25 (1,219 trading days); "
            "2021-05-06..2026-11-25 has 1,349 trading days where 2021-05-06..2021-11-15 precedes V20.0 start."
        ),
        "baseline_parity": {
            **parity_rep,
            "combined_v20_exact_nav_unrounded": round(float(np.prod(1.0 + tr_c["net_ret"].to_numpy(float))), 4),
            "combined_v20_mtm_diff_5y": mtm_diff_5y,
        },
        "empty_slot_stats_canonical_5y": empty_stats_5y,
        "empty_slot_stats_to_20261125": empty_stats_to25,
    }
    with open(f"{OUT_DIR}/v20_baseline_parity.json", "w", encoding="utf-8") as f:
        json.dump(parity_out, f, ensure_ascii=False, indent=2)
    print(f"[DONE in {time.time()-t0:.2f}s] V20 parity & slot calendar saved -> {OUT_DIR}")
    print("Combined:", parity_out["baseline_parity"]["combined_v20_exact_nav_unrounded"], "n=", len(tr_c))
    print("Empty 5Y (1212d):", empty_stats_5y["5y_canonical_1212d"]["v20_empty_days"], "/", empty_stats_5y["5y_canonical_1212d"]["n_trading_days"], f"({empty_stats_5y['5y_canonical_1212d']['v20_empty_pct']}%)")


if __name__ == "__main__":
    main()

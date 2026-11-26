#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Step 1A: Scan Track 1 events (V2_A/V2_B/V2_C), hydrate PIT + Theme Continuity, 2024-12-31 trunc proof."""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
import gc, json, resource, sqlite3, subprocess, sys, time
from typing import Optional
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
pa.set_memory_pool(pa.system_memory_pool())
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
RD040_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd040_abn_unlock_wave2_20261126"
RD045_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd045_abn_v2_bse_v2_refinement_20261126"
for p in (RD040_DIR, RD045_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rd040_data as rd_dat
import step1_build_abn10d_and_events_pit as rd40_s1
import _rd045_abn_extract as abn_ex

SCAN_COLS = rd40_s1.SCAN_COLS


def scan_events(max_dt: Optional[str] = None) -> pd.DataFrame:
    idx_sh, idx_sz, _, all_dts = rd_dat.ensure_index_cache(max_dt=max_dt)
    mkt_pos = {d: i for i, d in enumerate(all_dts)}
    pit_info = rd_dat.load_pit_st_and_notices(all_dts, max_dt=max_dt)
    warm = rd40_s1._load_2020_warmup()

    pf = pq.ParquetFile(rd_dat.STOCK_DAY_PQ)
    all_events = []
    for prefs in (("000", "001"), ("002", "003", "004", "005", "006", "007", "008", "009"),
                  ("600", "601"), ("602", "603", "604", "605", "606", "607", "608", "609")):
        tabs = []
        for batch in pf.iter_batches(batch_size=65_536, columns=SCAN_COLS, use_threads=False):
            m = pc.equal(batch.column("is_20cm"), 0)
            if max_dt is not None:
                m = pc.and_(m, pc.less_equal(pc.utf8_slice_codeunits(pc.cast(batch.column("dt"), pa.string()), 0, 10), max_dt))
            sub = batch.filter(m)
            if sub.num_rows == 0:
                continue
            p3 = pc.utf8_slice_codeunits(pc.cast(sub.column("c6"), pa.string()), 0, 3)
            g_t = sub.filter(pc.is_in(p3, value_set=pa.array(prefs)))
            if g_t.num_rows > 0:
                tabs.append(g_t)
        pa.default_memory_pool().release_unused()
        w_sub = warm[warm["c6"].str.startswith(prefs)].copy()
        if tabs:
            mb_p = pa.Table.from_batches(tabs).to_pandas()
            del tabs
            mb_p["c6"] = mb_p["c6"].astype(str).str.zfill(6)
            mb_p["dt"] = mb_p["dt"].astype(str).str[:10]
            mb = pd.concat([w_sub, mb_p], ignore_index=True)
            del mb_p
        else:
            mb = w_sub
        mb = mb.sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"], keep="last").reset_index(drop=True)
        gc.collect()
        for c6, g in mb.groupby("c6", sort=False):
            if len(g) < 25:
                continue
            dts = g["dt"].to_numpy()
            op, hi, lo, cl = g["open"].to_numpy(float), g["high"].to_numpy(float), g["low"].to_numpy(float), g["close"].to_numpy(float)
            af, r1, opct = g["adj_factor"].to_numpy(float), g["ret_1d"].to_numpy(float), g["open_pct"].to_numpy(float)
            pc_raw, amt, trn, age = g["prev_close_raw"].to_numpy(float), g["amount_yi"].to_numpy(float), g["turn_pct"].to_numpy(float), g["list_age"].to_numpy(int)
            st_mask = rd_dat.compute_strict_pit_st_mask(c6, dts, cl, hi, lo, pc_raw, pit_info)
            vp = np.isfinite(pc_raw) & (pc_raw > 0) & (~st_mask)
            zt_px = np.floor(pc_raw * 1.10 * 100.0 + 0.5) / 100.0
            dt_px = np.floor(pc_raw * 0.90 * 100.0 + 0.5) / 100.0
            zt = vp & (cl >= zt_px - 0.005) & (cl >= hi - 0.005)
            dt_f = vp & (cl <= dt_px + 0.005) & (cl <= lo + 0.005)
            yzz = zt & (op >= zt_px - 0.005) & (lo >= zt_px - 0.005)
            yzd = dt_f & (op <= dt_px + 0.005) & (hi <= dt_px + 0.005)
            stk = np.zeros(len(dts), dtype=np.int16)
            cs = 0
            for i in range(len(dts)):
                cs = cs + 1 if zt[i] else 0
                stk[i] = cs
            imap = idx_sh if c6.startswith("6") else idx_sz
            cn_sev_s = pit_info["cn_sev"].get(c6, set())
            dev_d = rd_dat.compute_official_10d_dev_series(c6, dts, op, hi, cl, af, imap, all_dts, mkt_pos, cn_sev_s)
            g_arr = {"dts": dts, "op": op, "hi": hi, "lo": lo, "cl": cl, "af": af, "r1": r1, "opct": opct,
                     "amt": amt, "trn": trn, "zt": zt, "dt_f": dt_f, "yzz": yzz, "yzd": yzd, "age": age, "pc_raw": pc_raw, "stk": stk}
            all_events.extend(abn_ex.extract_v2_stock_events(c6, g_arr, st_mask, dev_d, cn_sev_s))
        del mb
        gc.collect()
        pa.default_memory_pool().release_unused()

    ev = pd.DataFrame(all_events)
    if not ev.empty:
        ev = ev.sort_values(["entry_type", "buy_date", "code"]).reset_index(drop=True)
    print(f"[Track1 Scan max_dt={max_dt}] {len(ev)} events | {ev['entry_type'].value_counts().to_dict() if not ev.empty else {}}")
    return ev


def main():
    import _rd045_theme_hydrate as thm
    t0 = time.time()
    if "--trunc-sub" in sys.argv:
        ev_t = scan_events(max_dt="2024-12-31")
        df_t = thm.hydrate_track1(ev_t, max_dt="2024-12-31")
        df_t.to_parquet(f"{RD045_DIR}/_tmp_t1_trunc.parquet", index=False)
        return

    ev_full = scan_events(max_dt=None)
    df_full = thm.hydrate_track1(ev_full, max_dt=None)
    del ev_full
    gc.collect()

    subprocess.check_call([sys.executable, __file__, "--trunc-sub"])
    df_tr = pd.read_parquet(f"{RD045_DIR}/_tmp_t1_trunc.parquet")
    os.remove(f"{RD045_DIR}/_tmp_t1_trunc.parquet")

    # Physical truncation proof across settled events (S5_ma5_trail has up to b+10 exit)
    ed_f = df_full["S5_ma5_trail_exit_date"].astype(str)
    ed_t = df_tr["S5_ma5_trail_exit_date"].astype(str)
    f_sub = df_full[df_full["S5_ma5_trail_exit_date"].notna() & (ed_f != "") & (ed_f <= "2024-12-31")].sort_values(["entry_type", "buy_date", "code"]).reset_index(drop=True)
    t_sub = df_tr[df_tr["S5_ma5_trail_exit_date"].notna() & (ed_t != "") & (ed_t <= "2024-12-31")].sort_values(["entry_type", "buy_date", "code"]).reset_index(drop=True)
    assert len(f_sub) == len(t_sub), f"Trunc len mismatch: {len(f_sub)} vs {len(t_sub)}"
    assert list(zip(f_sub["entry_type"], f_sub["buy_date"], f_sub["code"])) == list(zip(t_sub["entry_type"], t_sub["buy_date"], t_sub["code"]))
    num_cols = [c for c in t_sub.columns if pd.api.types.is_numeric_dtype(t_sub[c]) and c in f_sub.columns]
    max_diff = 0.0
    for c in num_cols:
        va = pd.to_numeric(f_sub[c], errors="coerce").fillna(-99999.0).to_numpy(float)
        vb = pd.to_numeric(t_sub[c], errors="coerce").fillna(-99999.0).to_numpy(float)
        d = float(np.max(np.abs(va - vb))) if len(va) else 0.0
        if d > 1e-12:
            print(f"  [WARN diff] {c}: {d}")
        max_diff = max(max_diff, d)
    assert max_diff == 0.0, f"Track 1 truncation diff != 0: {max_diff}"

    df_full.to_parquet(f"{RD045_DIR}/track1_abn_v2_events_pit.parquet", index=False)
    rss = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)
    au = {"elapsed_sec": round(time.time() - t0, 1), "peak_rss_mb": rss, "total_events": int(len(df_full)),
          "entry_counts": df_full["entry_type"].value_counts().to_dict(),
          "trunc_20241231_settled_n": int(len(f_sub)), "trunc_20241231_max_abs_diff": max_diff}
    with open(f"{RD045_DIR}/_t1_build_audit.json", "w", encoding="utf-8") as f:
        json.dump(au, f, ensure_ascii=False, indent=2)
    print(json.dumps(au, ensure_ascii=False, indent=2))
    assert rss < 2000.0, f"RSS >= 2GB: {rss}"


if __name__ == "__main__":
    main()

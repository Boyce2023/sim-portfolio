#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD040 Step 1: 5Y exact 10d-dev scan, 4-entry x 7-exit event pool, PIT hydration & 2024-12-31 proof."""
import gc, json, os, resource, sys, time
from typing import Optional
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
pa.set_memory_pool(pa.system_memory_pool())
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd040_abn_unlock_wave2_20261126"
sys.path.insert(0, OUT_DIR)
import _rd040_data as rd_dat
import _rd040_sim as rd_sim

SCAN_COLS = ["dt", "c6", "open", "high", "low", "close", "adj_factor", "ret_1d", "open_pct", "is_20cm", "list_age", "prev_close_raw", "amount_yi", "turn_pct"]
CORE_PIT_COLS = [
    "dt", "c6", "open_pct", "is_20cm", "prev_close_raw", "mcap_yi_t1", "amount_yi_t1", "ret_1d_t1", "d1_open_pct",
    "prev_clv", "prev_streak", "prev_is_broken_zt", "prev_is_yizi_zt", "overhang_pct_t1", "hr10d_space_t1", "hr30d_space_t1",
    "down_streak_t1", "pos_20d_t1", "pos_60d_t1", "pos_250d_t1", "dd_20d_t1", "amp_20d_t1", "bias10_t1", "bias20_t1",
    "ret_5d_t1", "ret_20d_t1", "vol_ratio5_t1", "turn_5_20_t1", "amp_comp_20v60_t1", "lhb_on_t1", "lhb_bayes_t2_t1",
    "lhb_inst_net_yi_t1", "lhb_lhasa_share_t1", "lhb_has_good_yz_t1", "lhb_has_surf_yz_t1", "lhb_has_quant_t1", "lhb_cnt_5d_t1",
    "lock_top10_pct_pre", "free_mcap_yi_t1", "real_turn_pct_t1", "d1_first_seal_hhmm_t1", "d1_open_board_cnt_t1", "d1_seal_ratio_t1",
    "list_age", "waves_3y_g15_t1", "zt_cnt_1y_t1", "max_streak_3y", "cum_turnover_1y", "trap_waves_3y", "dd_from_3y_high",
    "cool_days_since_last_zt", "cool_days_since_last_2b", "comm_posts_1y_pct", "xq_posts_1y_pct", "kpl_unique_plates_3y",
    "kpl_top_plate_share", "kpl_zt3_t1", "kpl_days_30d_t1", "kpl_in_t1", "kpl_rank_t1", "kpl_zt1_t1", "kpl_streak_t1",
    "csrc_ind_id", "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1", "csrc_ind_zt_share5_t1", "csrc_ind_amt_pct250_t1",
    "tox_reg_30d_pre", "abn_notice_30d_pre", "ir_cnt_30d_pre", "comm_ring_tier", "comm_driver_ret20_t1", "comm_driver_pct5y_t1",
]
BENCH_TARGETS = [("603137", "2026-07-10", 109.1275), ("600825", "2026-10-08", 117.0645), ("000993", "2026-09-22", 100.0157),
                 ("002242", "2026-10-16", 99.54), ("002242", "2026-10-19", 88.08), ("002724", "2026-10-30", 100.02),
                 ("002343", "2026-10-21", 96.70), ("603278", "2026-10-30", 100.11)]


def _load_2020_warmup() -> pd.DataFrame:
    import pyarrow.compute as pc
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "amount", "turn"]
    chunks = []
    t_lo, t_hi = pd.Timestamp("2020-12-01"), pd.Timestamp("2021-01-04")
    for p_pq in (rd_dat.A_DAILY_PQ, rd_dat.A_DELIST_PQ):
        pf_a = pq.ParquetFile(p_pq)
        for rg_i in range(pf_a.num_row_groups):
            rg_meta = pf_a.metadata.row_group(rg_i)
            dt_col_idx = next((j for j in range(rg_meta.num_columns) if rg_meta.column(j).path_in_schema == "date"), None)
            if dt_col_idx is not None:
                st = rg_meta.column(dt_col_idx).statistics
                if st and st.has_min_max and (pd.Timestamp(st.max) < t_lo or pd.Timestamp(st.min) >= t_hi):
                    continue
            tab = pf_a.read_row_group(rg_i, columns=cols, use_threads=False)
            m = pc.and_(pc.greater_equal(tab.column("date"), t_lo), pc.less(tab.column("date"), t_hi))
            sub = tab.filter(m)
            if sub.num_rows > 0:
                chunks.append(sub.to_pandas())
    pa.default_memory_pool().release_unused()
    w = pd.concat(chunks, ignore_index=True)
    del chunks
    w["c6"] = w["ticker"].astype(str).str[:6]
    suf = w["ticker"].astype(str).str[-3:]
    w = w[w["c6"].str.startswith(("00", "60")) & suf.isin([".SH", ".SZ"]) & (w["close"] > 0) & (w["adj_close"] > 0)].copy()
    w["dt"] = pd.to_datetime(w["date"]).dt.strftime("%Y-%m-%d")
    w = w.sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"], keep="first").reset_index(drop=True)
    w["adj_factor"] = (w["adj_close"] / w["close"]).astype(np.float32)
    g = w.groupby("c6", sort=False)
    pa_c = g["adj_close"].shift(1)
    w["prev_close_raw"] = (pa_c * (w["close"] / w["adj_close"])).astype(np.float32)
    w["ret_1d"] = ((w["adj_close"] / pa_c - 1.0) * 100.0).astype(np.float32)
    w["open_pct"] = ((w["open"] / w["prev_close_raw"] - 1.0) * 100.0).astype(np.float32)
    w["amount_yi"] = (w["amount"] / 1e8).astype(np.float32)
    w["turn_pct"] = (w["turn"] * 100.0).astype(np.float32)
    w["is_20cm"] = np.int8(0)
    w["list_age"] = np.int16(100)
    for fc in ("open", "high", "low", "close"):
        w[fc] = w[fc].astype(np.float32)
    res = w[SCAN_COLS].copy()
    del w
    gc.collect()
    pa.default_memory_pool().release_unused()
    return res


def scan_events(max_dt: Optional[str] = None) -> tuple[pd.DataFrame, dict]:
    t0 = time.time()
    idx_sh, idx_sz, _, all_dts = rd_dat.ensure_index_cache(max_dt=max_dt)
    mkt_pos = {d: i for i, d in enumerate(all_dts)}
    pit_info = rd_dat.load_pit_st_and_notices(all_dts, max_dt=max_dt)
    warm = _load_2020_warmup()

    pf = pq.ParquetFile(rd_dat.STOCK_DAY_PQ)
    all_events, bench_audit, st_excluded_cnt = [], {}, 0
    # Process 4 prefix buckets by scanning lightweight 14 cols per pair of buckets (max 2 passes, <=350MB peak!)
    import pyarrow.compute as pc
    for grp_pair in [(("000", "001"), ("002", "003", "004", "005", "006", "007", "008", "009")),
                     (("600", "601"), ("602", "603", "604", "605", "606", "607", "608", "609"))]:
        grp_tabs = [[], []]
        for batch in pf.iter_batches(batch_size=65_536, columns=SCAN_COLS, use_threads=False):
            m_main = pc.equal(batch.column("is_20cm"), 0)
            if max_dt is not None:
                dt_str = pc.utf8_slice_codeunits(pc.cast(batch.column("dt"), pa.string()), 0, 10)
                m_main = pc.and_(m_main, pc.less_equal(dt_str, max_dt))
            sub_t = batch.filter(m_main)
            if sub_t.num_rows == 0:
                continue
            c6_s = pc.cast(sub_t.column("c6"), pa.string())
            p3 = pc.utf8_slice_codeunits(c6_s, 0, 3)
            for gi, prefs in enumerate(grp_pair):
                g_t = sub_t.filter(pc.is_in(p3, value_set=pa.array(prefs)))
                if g_t.num_rows > 0:
                    grp_tabs[gi].append(g_t)
        pa.default_memory_pool().release_unused()

        for gi, prefs in enumerate(grp_pair):
            w_sub = warm[warm["c6"].str.startswith(prefs)].copy()
            if grp_tabs[gi]:
                mb_p = pa.Table.from_batches(grp_tabs[gi]).to_pandas()
                grp_tabs[gi] = None
                mb_p["c6"] = mb_p["c6"].astype(str).str.zfill(6)
                mb_p["dt"] = mb_p["dt"].astype(str).str[:10]
                mb = pd.concat([w_sub, mb_p], ignore_index=True)
                del mb_p
            else:
                mb = w_sub
            mb = mb.sort_values(["c6", "dt"]).drop_duplicates(["c6", "dt"], keep="last").reset_index(drop=True)
            gc.collect()
            for c6, g in mb.groupby("c6", sort=False):
                dts = g["dt"].to_numpy()
                op, hi, lo, cl = g["open"].to_numpy(float), g["high"].to_numpy(float), g["low"].to_numpy(float), g["close"].to_numpy(float)
                af, r1, opct = g["adj_factor"].to_numpy(float), g["ret_1d"].to_numpy(float), g["open_pct"].to_numpy(float)
                pc_raw, amt, trn, age = g["prev_close_raw"].to_numpy(float), g["amount_yi"].to_numpy(float), g["turn_pct"].to_numpy(float), g["list_age"].to_numpy(int)
                if len(dts) < 25:
                    continue

                st_mask = rd_dat.compute_strict_pit_st_mask(c6, dts, cl, hi, lo, pc_raw, pit_info)
                vp = np.isfinite(pc_raw) & (pc_raw > 0) & (~st_mask)
                zt_px = np.floor(pc_raw * 1.10 * 100.0 + 0.5) / 100.0
                dt_px = np.floor(pc_raw * 0.90 * 100.0 + 0.5) / 100.0
                zt = vp & (cl >= zt_px - 0.005) & (cl >= hi - 0.005)
                dt_f = vp & (cl <= dt_px + 0.005) & (cl <= lo + 0.005)
                yzz = zt & (op >= zt_px - 0.005) & (lo >= zt_px - 0.005)
                yzd = dt_f & (op <= dt_px + 0.005) & (hi <= dt_px + 0.005)

                imap = idx_sh if c6.startswith("6") else idx_sz
                dev_d = rd_dat.compute_official_10d_dev_series(c6, dts, op, hi, cl, af, imap, all_dts, mkt_pos, pit_info["cn_sev"].get(c6, set()))
                if max_dt is None:
                    for bc, bd, bval in BENCH_TARGETS:
                        if bc == c6:
                            hits = np.where(dts == bd)[0]
                            if len(hits):
                                calc_v = float(dev_d["dev_c"][hits[0]])
                                bench_audit[f"{bc}_{bd}"] = {"official_ref": bval, "computed": round(calc_v, 4), "abs_err_pp": round(abs(calc_v - bval), 4)}
                st_excluded_cnt += int(np.sum(st_mask & (dev_d["dev_c"] >= 85.0)))
                g_arr = {"dts": dts, "op": op, "hi": hi, "lo": lo, "cl": cl, "af": af, "r1": r1, "opct": opct, "amt": amt, "trn": trn,
                         "zt": zt, "dt_f": dt_f, "yzz": yzz, "yzd": yzd, "age": age, "pc_raw": pc_raw}
                all_events.extend(rd_sim.extract_stock_events(c6, g_arr, st_mask, dev_d, imap))
            del mb
            gc.collect()
            pa.default_memory_pool().release_unused()

    ev_df = pd.DataFrame(all_events)
    if not ev_df.empty:
        ev_df = ev_df.sort_values(["entry_type", "buy_date", "code"]).reset_index(drop=True)
    print(f"[Scan max_dt={max_dt}] {len(ev_df)} events in {time.time()-t0:.1f}s | counts={ev_df['entry_type'].value_counts().to_dict() if not ev_df.empty else {}}")
    return ev_df, {"bench_calibration": bench_audit, "st_high_dev_excluded": st_excluded_cnt}


def hydrate_features(ev_df: pd.DataFrame, max_dt: Optional[str] = None) -> pd.DataFrame:
    t0 = time.time()
    need_keys = set(zip(ev_df["buy_date"].astype(str), ev_df["code"].astype(str)))
    need_dts, need_c6s = {k[0] for k in need_keys}, {k[1] for k in need_keys}
    pf = pq.ParquetFile(rd_dat.STOCK_DAY_PQ)
    feat_cols = [c for c in CORE_PIT_COLS if c not in ("dt", "c6")]
    core = None
    for c_start in range(0, len(feat_cols), 25):
        sub_cols = ["dt", "c6"] + feat_cols[c_start:c_start + 25]
        chunks = []
        for batch in pf.iter_batches(batch_size=65_536, columns=sub_cols, use_threads=False):
            b = batch.to_pandas()
            b["dt"] = b["dt"].astype(str).str[:10]
            b["c6"] = b["c6"].astype(str).str.zfill(6)
            if max_dt is not None:
                b = b[b["dt"] <= max_dt]
            b = b[b["dt"].isin(need_dts) & b["c6"].isin(need_c6s)]
            if not b.empty:
                b = b[[((d, c) in need_keys) for d, c in zip(b["dt"].values, b["c6"].values)]]
                if not b.empty:
                    chunks.append(b)
        part = pd.concat(chunks, ignore_index=True).drop_duplicates(["dt", "c6"], keep="first")
        del chunks
        core = part if core is None else core.merge(part, on=["dt", "c6"], how="outer")
        gc.collect()
        pa.default_memory_pool().release_unused()

    mkt = pd.read_parquet(rd_dat.MKT_DAILY_PQ)
    mkt["trade_date"] = mkt["trade_date"].astype(str).str[:10]
    if max_dt is not None:
        mkt = mkt[mkt["trade_date"] <= max_dt].copy()

    m = ev_df.merge(core, left_on=["buy_date", "code"], right_on=["dt", "c6"], how="left").drop(columns=["dt", "c6"])
    m = m.merge(mkt, left_on="buy_date", right_on="trade_date", how="left").drop(columns=["trade_date"])

    # Derived causal & minefield flags (两步排雷分家)
    m["drv_open_minus_ret_t1"] = pd.to_numeric(m["open_pct"], errors="coerce") - pd.to_numeric(m["ret_1d_t1"], errors="coerce")
    m["drv_lhb_inst_minus_lhasa"] = pd.to_numeric(m["lhb_inst_net_yi_t1"], errors="coerce") - pd.to_numeric(m["lhb_lhasa_share_t1"], errors="coerce")
    m["drv_ind_rel5_t1"] = pd.to_numeric(m["ret_5d_t1"], errors="coerce") - pd.to_numeric(m["csrc_ind_ex5_t1"], errors="coerce")
    m["drv_ind_rel20_t1"] = pd.to_numeric(m["ret_20d_t1"], errors="coerce") - pd.to_numeric(m["csrc_ind_ex20_t1"], errors="coerce")
    m["mine_tox_reg"] = (pd.to_numeric(m["tox_reg_30d_pre"], errors="coerce").fillna(0) > 0).astype(float)
    m["mine_prev_dt"] = ((pd.to_numeric(m["ret_1d_t1"], errors="coerce").fillna(0) <= -9.4) & (pd.to_numeric(m["prev_clv"], errors="coerce").fillna(0.5) <= 0.05)).astype(float)
    m["mine_hit_100"] = m["abn_was_hit_100"].astype(float)
    m["mine_lhasa_heavy"] = (pd.to_numeric(m["lhb_lhasa_share_t1"], errors="coerce").fillna(0) > 0.25).astype(float)
    m["mine_deep_break"] = (m["abn_dd_peak_t1_pct"] < -15.0).astype(float)
    m["mine_nuclear_open"] = (m["abn_open_pct"] <= -5.0).astype(float)
    m["mine_any_cnt"] = m[["mine_tox_reg", "mine_prev_dt", "mine_hit_100", "mine_lhasa_heavy", "mine_deep_break", "mine_nuclear_open"]].sum(axis=1)
    m["is_mine_cleared"] = (m["mine_any_cnt"] == 0).astype(int)
    print(f"[Hydrate] shape={m.shape} in {time.time()-t0:.1f}s")
    return m


def main():
    import subprocess
    t0 = time.time()
    if "--trunc-sub" in sys.argv:
        ev_trunc, _ = scan_events(max_dt="2024-12-31")
        df_trunc = hydrate_features(ev_trunc, max_dt="2024-12-31")
        df_trunc.to_parquet(f"{OUT_DIR}/_tmp_trunc_20241231.parquet", index=False)
        rss_t = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)
        assert rss_t < 2000.0, f"Trunc Peak RSS >= 2GB: {rss_t}"
        return

    ev_full, audit_scan = scan_events(max_dt=None)
    df_full = hydrate_features(ev_full, max_dt=None)
    del ev_full
    gc.collect()
    pa.default_memory_pool().release_unused()

    subprocess.check_call([sys.executable, __file__, "--trunc-sub"])
    df_trunc = pd.read_parquet(f"{OUT_DIR}/_tmp_trunc_20241231.parquet")
    os.remove(f"{OUT_DIR}/_tmp_trunc_20241231.parquet")

    # Physical truncation proof on all settled trades (S4_hold5c has longest exit_date)
    s4_f = df_full["S4_hold5c_exit_date"].astype(str)
    s4_t = df_trunc["S4_hold5c_exit_date"].astype(str)
    f_sub = df_full[df_full["S4_hold5c_exit_date"].notna() & (s4_f != "") & (s4_f <= "2024-12-31")].sort_values(["entry_type", "buy_date", "code"]).reset_index(drop=True)
    t_sub = df_trunc[df_trunc["S4_hold5c_exit_date"].notna() & (s4_t != "") & (s4_t <= "2024-12-31")].sort_values(["entry_type", "buy_date", "code"]).reset_index(drop=True)
    assert len(f_sub) == len(t_sub), f"Trunc count mismatch: {len(f_sub)} vs {len(t_sub)}"
    assert list(zip(f_sub["entry_type"], f_sub["buy_date"], f_sub["code"])) == list(zip(t_sub["entry_type"], t_sub["buy_date"], t_sub["code"]))
    num_cols = [c for c in t_sub.columns if pd.api.types.is_numeric_dtype(t_sub[c]) and c in f_sub.columns]
    max_diff = 0.0
    for c in num_cols:
        va = pd.to_numeric(f_sub[c], errors="coerce").fillna(-99999.0).to_numpy(float)
        vb = pd.to_numeric(t_sub[c], errors="coerce").fillna(-99999.0).to_numpy(float)
        d = float(np.max(np.abs(va - vb))) if len(va) else 0.0
        max_diff = max(max_diff, d)
    assert max_diff == 0.0, f"Pool truncation diff != 0: {max_diff}"

    df_full.to_parquet(f"{OUT_DIR}/rd040_events_pit.parquet", index=False)
    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)
    bench_max_err = max((v["abs_err_pp"] for v in audit_scan["bench_calibration"].values()), default=0.0)
    res = {"elapsed_sec": round(time.time() - t0, 1), "peak_rss_mb": rss_mb, "total_events": int(len(df_full)),
           "entry_counts": df_full["entry_type"].value_counts().to_dict(), "bench_max_err_pp": bench_max_err,
           "bench_calibration": audit_scan["bench_calibration"], "st_high_dev_excluded": audit_scan["st_high_dev_excluded"],
           "trunc_20241231_settled_n": int(len(f_sub)), "trunc_20241231_max_abs_diff": max_diff}
    with open(f"{OUT_DIR}/_step1_audit.json", "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    assert rss_mb < 2000.0, f"Peak RSS >= 2GB: {rss_mb}"

if __name__ == "__main__":
    main()

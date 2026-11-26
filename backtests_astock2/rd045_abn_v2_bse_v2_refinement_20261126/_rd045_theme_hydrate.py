#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Track 1 hydration: CORE_PIT_COLS + MKT_DAILY + Wave-1 vs Unlock Theme Strength."""
import gc, json, sqlite3, sys, time
from collections import defaultdict
from typing import Optional
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

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

CORE_PIT_COLS = rd40_s1.CORE_PIT_COLS


def _calc_theme_score(ind_zt_3d: float, ind_max_stk: float, ind_amt_sh: float, ind_zt_sh: float,
                      kp_3d: float, kp_cnt: float, kp_sh: float, comm_p: float, xq_p: float) -> tuple[float, float]:
    """Fixed 0-100 causal Theme Strength (abs & mkt-normalized) with zero fitted weights."""
    p_kpl = min(35.0, kp_3d * 1.1 + min(15.0, kp_cnt * 2.5))
    p_ind = min(20.0, ind_zt_3d * 1.4) + min(15.0, max(0.0, ind_max_stk - 1.0) * 3.0)
    p_amt = min(15.0, ind_amt_sh * 2.5)
    p_com = 15.0 * (0.5 * comm_p + 0.5 * xq_p)
    raw_sc = p_kpl + p_ind + p_amt + p_com

    # Market-normalized version: KPL share + Ind ZT share + Ind Amt share + Streak + Comm
    r_kpl = min(35.0, kp_sh * 1.1)
    r_ind = min(20.0, ind_zt_sh * 1.2) + min(15.0, max(0.0, ind_max_stk - 1.0) * 3.0)
    rel_sc = r_kpl + r_ind + p_amt + p_com
    return round(raw_sc, 3), round(rel_sc, 3)


def hydrate_track1(ev_df: pd.DataFrame, max_dt: Optional[str] = None) -> pd.DataFrame:
    if ev_df.empty:
        return ev_df
    need_dates = set(ev_df["buy_date"].astype(str)) | set(ev_df["sig_date"].astype(str)) | set(ev_df["wave1_peak_dt"].astype(str))
    need_c6s = set(ev_df["code"].astype(str))
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
            b = b[b["dt"].isin(need_dates) & b["c6"].isin(need_c6s)]
            if not b.empty:
                chunks.append(b)
        part = pd.concat(chunks, ignore_index=True).drop_duplicates(["dt", "c6"], keep="first")
        del chunks
        core = part if core is None else core.merge(part, on=["dt", "c6"], how="outer")
        gc.collect()
        pa.default_memory_pool().release_unused()

    # Join full CORE_PIT_COLS on buy_date (for _t1 features), plus comm_posts/xq_posts at wave1_peak_dt
    m = ev_df.merge(core, left_on=["buy_date", "code"], right_on=["dt", "c6"], how="left").drop(columns=["dt", "c6"])
    core_t0 = core[["dt", "c6", "comm_posts_1y_pct", "xq_posts_1y_pct"]].rename(
        columns={"comm_posts_1y_pct": "t0_comm_pct", "xq_posts_1y_pct": "t0_xq_pct"}
    )
    m = m.merge(core_t0, left_on=["wave1_peak_dt", "code"], right_on=["dt", "c6"], how="left").drop(columns=["dt", "c6"])
    del core, core_t0
    gc.collect()

    mkt = pd.read_parquet(rd_dat.MKT_DAILY_PQ)
    mkt["trade_date"] = mkt["trade_date"].astype(str).str[:10]
    if max_dt is not None:
        mkt = mkt[mkt["trade_date"] <= max_dt].copy()
    m = m.merge(mkt, left_on="buy_date", right_on="trade_date", how="left").drop(columns=["trade_date"])

    # Load CSRC Industry Daily & KPL Plate Tables (filtered strictly <= max_dt)
    ind = pd.read_parquet(f"{RD045_DIR}/csrc_ind_daily.parquet")
    kp = pd.read_parquet(f"{RD045_DIR}/kpl_plate_daily.parquet")
    sp = pd.read_parquet(f"{RD045_DIR}/kpl_stock_plates.parquet")
    if max_dt is not None:
        ind = ind[ind["dt"] <= max_dt]
        kp = kp[kp["dt"] <= max_dt]
        sp = sp[sp["dt"] <= max_dt]

    ind_lu = {(r.dt, int(r.csrc_ind_id)): (float(r.ind_zt_cnt), float(r.ind_zt_3d), float(r.ind_max_streak), float(r.ind_amt_share_pct), float(r.ind_zt_share_pct), float(r.mkt_zt_cnt))
              for r in ind.itertuples(index=False)}
    kp_lu = {(r.dt, r.base_plate): (float(r.kp_cnt), float(r.kp_3d_cnt), float(r.kp_share_pct), float(r.kp_rank))
             for r in kp.itertuples(index=False)}
    sp_by_c6 = defaultdict(list)
    for r in sp.itertuples(index=False):
        sp_by_c6[r.c6].append((r.dt, r.base_plate))

    # News mentions of Wave-1 KPL plate name in [dt-3d..dt] strictly <= sig_date
    con_n = sqlite3.connect(f"file:{ROOT}/sim-portfolio/data/astock_news_5y_pit.db?mode=ro", uri=True)
    news_q = "SELECT avail_trade_date, title FROM news_pit WHERE avail_trade_date <= ?"
    news_rows = con_n.execute(news_q, (max_dt or "2099-12-31",)).fetchall()
    con_n.close()
    news_by_dt = defaultdict(list)
    for ndt, nttl in news_rows:
        news_by_dt[str(ndt)[:10]].append(str(nttl or ""))
    all_mkt_dts = sorted(mkt["trade_date"].unique())
    dt_pos = {d: i for i, d in enumerate(all_mkt_dts)}

    th_cols = defaultdict(list)
    for r in m.itertuples(index=False):
        c6 = str(r.code)
        cid = int(r.csrc_ind_id) if pd.notna(r.csrc_ind_id) else -1
        t0_dt, sig_dt, wstart = str(r.wave1_peak_dt), str(r.sig_date), str(r.wave1_start_dt)

        # Find Wave-1 KPL plates in [wstart .. sig_dt] (or [wstart .. t0_dt]!)
        w1_plates = [bp for d_s, bp in sp_by_c6.get(c6, []) if wstart <= d_s <= t0_dt]
        if not w1_plates:
            w1_plates = [bp for d_s, bp in sp_by_c6.get(c6, []) if wstart <= d_s <= sig_dt]
        # Also plates on sig_dt itself
        cur_plates = [bp for d_s, bp in sp_by_c6.get(c6, []) if d_s == sig_dt]

        def _best_kp(plates_list, d_q):
            best = (0.0, 0.0, 0.0, 99.0, "")
            best_key = (-1.0, -1.0, -99.0, "")
            for bp in sorted(set(plates_list)):
                v = kp_lu.get((d_q, bp))
                if v:
                    k_cmp = (v[0], v[1], -v[3], bp)
                    if k_cmp > best_key:
                        best_key = k_cmp
                        best = (v[0], v[1], v[2], v[3], bp)
            return best

        kp_t0 = _best_kp(w1_plates, t0_dt)
        kp_sig = _best_kp(w1_plates, sig_dt)
        kp_cur = _best_kp(cur_plates, sig_dt)
        # Active KPL strength at sig_dt uses max(wave1_plate_at_sig, cur_plate_at_sig)
        sig_kp_cnt = max(kp_sig[0], kp_cur[0])
        sig_kp_3d = max(kp_sig[1], kp_cur[1])
        sig_kp_sh = max(kp_sig[2], kp_cur[2])
        sig_kp_rk = min(kp_sig[3], kp_cur[3])

        ind_t0 = ind_lu.get((t0_dt, cid), (0.0, 0.0, 0.0, 0.0, 0.0, 40.0))
        ind_sig = ind_lu.get((sig_dt, cid), (0.0, 0.0, 0.0, 0.0, 0.0, 40.0))

        c_p = float(r.comm_posts_1y_pct) if pd.notna(r.comm_posts_1y_pct) else 0.5
        x_p = float(r.xq_posts_1y_pct) if pd.notna(r.xq_posts_1y_pct) else 0.5
        t0_cp = float(r.t0_comm_pct) if pd.notna(r.t0_comm_pct) else c_p
        t0_xp = float(r.t0_xq_pct) if pd.notna(r.t0_xq_pct) else x_p

        sc_t0, rsc_t0 = _calc_theme_score(ind_t0[1], ind_t0[2], ind_t0[3], ind_t0[4], kp_t0[1], kp_t0[0], kp_t0[2], t0_cp, t0_xp)
        sc_sig, rsc_sig = _calc_theme_score(ind_sig[1], ind_sig[2], ind_sig[3], ind_sig[4], sig_kp_3d, sig_kp_cnt, sig_kp_sh, c_p, x_p)

        # News mentions of wave1 plate over last 3 trading days up to d_q
        def _news_3d(bp_name, d_q):
            if not bp_name or d_q not in dt_pos:
                return np.nan
            pos = dt_pos[d_q]
            if d_q < "2022-03-25":
                return np.nan
            cnt = 0
            for j in range(max(0, pos - 2), pos + 1):
                for ttl in news_by_dt.get(all_mkt_dts[j], []):
                    if bp_name in ttl:
                        cnt += 1
            return float(cnt)

        w1_bp_name = kp_t0[4] or (w1_plates[0] if w1_plates else "")
        n_t0 = _news_3d(w1_bp_name, t0_dt)
        n_sig = _news_3d(w1_bp_name, sig_dt)

        th_cols["thm_has_kpl_w1"].append(1 if w1_plates else 0)
        th_cols["thm_kp_cnt_t0"].append(kp_t0[0])
        th_cols["thm_kp_cnt_sig"].append(sig_kp_cnt)
        th_cols["thm_kp_w1only_cnt_sig"].append(kp_sig[0])
        th_cols["thm_kp_rank_sig"].append(sig_kp_rk)
        th_cols["thm_ind_zt_t0"].append(ind_t0[0])
        th_cols["thm_ind_zt_sig"].append(ind_sig[0])
        th_cols["thm_ind_zt3d_t0"].append(ind_t0[1])
        th_cols["thm_ind_zt3d_sig"].append(ind_sig[1])
        th_cols["thm_ind_stk_t0"].append(ind_t0[2])
        th_cols["thm_ind_stk_sig"].append(ind_sig[2])
        th_cols["thm_ind_amtsh_sig"].append(ind_sig[3])
        th_cols["thm_score_t0"].append(sc_t0)
        th_cols["thm_score_sig"].append(sc_sig)
        th_cols["thm_delta"].append(round(sc_sig - sc_t0, 3))
        th_cols["thm_ratio"].append(round(sc_sig / max(1.0, sc_t0), 4))
        th_cols["thm_rel_t0"].append(rsc_t0)
        th_cols["thm_rel_sig"].append(rsc_sig)
        th_cols["thm_rel_delta"].append(round(rsc_sig - rsc_t0, 3))
        th_cols["thm_rel_ratio"].append(round(rsc_sig / max(1.0, rsc_t0), 4))
        th_cols["thm_news3d_t0"].append(n_t0)
        th_cols["thm_news3d_sig"].append(n_sig)

    for k, v in th_cols.items():
        m[k] = v
    return m

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD037 Step 1: Strictly PIT (< T0) Anchor & 4-Class Peer Leader Pool Builder (Peak RSS < 1.5 GB).

Memory discipline:
  - Pass 1 reads compact price/tradability arrays (~230 MB) and computes rolling T-1 metrics
    extracting ONLY anchor-date rows.
  - Pass 2 reads ONLY the 10 peer-ranking columns for anchor-date rows (~120 MB), selects
    unique peer rows (~10k rows), frees the 3.3M table immediately, then streams the
    remaining 27 scorecard features ONLY for those ~10k selected row indices (< 5 MB!).
  - Zero yfinance (D12). Zero cap10m. Threads <= 1.
"""
import gc
import json
import os
import resource
import sys
import time
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

warnings.filterwarnings("ignore")

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
pa.set_cpu_count(1)
pa.set_io_thread_count(1)

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
RD028_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125"
RD016_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd016_famous_youzi_seats_20261117"
DATA_DIR = f"{ROOT}/sim-portfolio/data"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd037_1to2_peer_leaders_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

CORE_PQ = f"{BASE_DIR}/stock_day_core_features_pit.parquet"
OH_PQ = f"{RD028_DIR}/old_hot_6dim_stock_day_pit.parquet"
MKT_PQ = f"{BASE_DIR}/market_daily_all_new_factors_pit.parquet"
P1_PQ = f"{BASE_DIR}/pool_1to2_master_pit.parquet"
HF_PQ = f"{CACHE_DIR}/hist_fb_ge250_pit.parquet"


def _read_cols_numpy(cols: list[str], keep_mask: np.ndarray | None = None) -> dict[str, np.ndarray]:
    pf = pq.ParquetFile(CORE_PQ)
    n_tot = pf.metadata.num_rows
    n_out = int(keep_mask.sum()) if keep_mask is not None else n_tot
    schema = pf.schema_arrow
    out = {}
    for c in cols:
        pa_t = schema.field(c).type
        np_dt = np.float32 if pa.types.is_floating(pa_t) else (np.int8 if pa.types.is_int8(pa_t) else (np.int16 if pa.types.is_int16(pa_t) else np.int32))
        out[c] = np.empty(n_out, dtype=np_dt)
    src_pos = dst_pos = 0
    for rg in range(pf.num_row_groups):
        tbl = pf.read_row_group(rg, columns=cols)
        m_rg = tbl.num_rows
        if keep_mask is not None:
            km_rg = keep_mask[src_pos : src_pos + m_rg]
            cnt = int(km_rg.sum())
            if cnt > 0:
                for c in cols:
                    out[c][dst_pos : dst_pos + cnt] = tbl.column(c).to_numpy(zero_copy_only=False)[km_rg]
                dst_pos += cnt
        else:
            for c in cols:
                out[c][dst_pos : dst_pos + m_rg] = tbl.column(c).to_numpy(zero_copy_only=False)
            dst_pos += m_rg
        src_pos += m_rg
        del tbl
    pa.default_memory_pool().release_unused()
    return out


def build_anchors() -> tuple[pd.DataFrame, dict]:
    p1 = pd.read_parquet(
        P1_PQ,
        columns=[
            "buy_date", "code", "name", "plate", "sd_csrc_ind_id",
            "base_score", "v20_score", "orig_pass", "is_standalone_slot1", "is_v20_slot1",
            "pool_layer", "sim_ok", "buy_hhmm", "open_pct",
            "s12_p_sz", "s12_d1_seal_tightness", "s12_s_prior_wk", "s12_s_quant_dual",
        ],
    )
    p1["buy_date"] = p1["buy_date"].astype(str).str[:10]
    p1["code"] = p1["code"].astype(str).str.zfill(6)

    hf = pd.read_parquet(HF_PQ)
    hf["buy_date"] = hf["buy_date"].astype(str).str[:10]
    hf["code"] = hf["code"].astype(str).str.zfill(6)

    audit2 = json.load(open(f"{BASE_DIR}/_audit_step2_stockday.json"))
    ind_to_id = audit2["csrc_ind_id_map"]
    p1_pen_dts = set(p1.loc[(p1["v20_score"] - p1["base_score"]).abs() > 1.0, "buy_date"])
    hf["v20_score"] = hf["score_active"] + np.where(hf["buy_date"].isin(p1_pen_dts), -25.0, 0.0)
    hf["csrc_ind_id"] = hf["csrc_ind"].map(lambda x: ind_to_id.get(str(x) if x else "UNKNOWN", ind_to_id["UNKNOWN"])).astype(np.int16)

    pools = {}

    s92 = p1[p1["is_standalone_slot1"] == 1].sort_values("buy_date").reset_index(drop=True)
    s92["anchor_pool"] = "Anchor_Live92"
    s92["is_0925_known"] = (s92["buy_hhmm"] == 925).astype(np.int8)
    s92["anchor_score"] = s92["v20_score"].astype(float)
    s92["anchor_open_pct"] = (s92["open_pct"] * 100.0).astype(float)
    pools["Anchor_Live92"] = s92

    op = p1[p1["orig_pass"] == 1].sort_values(["buy_date", "v20_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    op["anchor_pool"] = "Anchor_OrigPass"
    op["is_0925_known"] = (op["buy_hhmm"] == 925).astype(np.int8)
    op["anchor_score"] = op["v20_score"].astype(float)
    op["anchor_open_pct"] = (op["open_pct"] * 100.0).astype(float)
    pools["Anchor_OrigPass"] = op

    wp_hi = p1[p1["v20_score"] >= 304.8].sort_values(["buy_date", "v20_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    wp_hi["anchor_pool"] = "Anchor_Wide_P1_Ge305"
    wp_hi["is_0925_known"] = np.int8(1)
    wp_hi["anchor_score"] = wp_hi["v20_score"].astype(float)
    wp_hi["anchor_open_pct"] = (wp_hi["open_pct"] * 100.0).astype(float)
    pools["Anchor_Wide_P1_Ge305"] = wp_hi

    wp_all = p1.sort_values(["buy_date", "v20_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    wp_all["anchor_pool"] = "Anchor_Wide_P1_All"
    wp_all["is_0925_known"] = np.int8(1)
    wp_all["anchor_score"] = wp_all["v20_score"].astype(float)
    wp_all["anchor_open_pct"] = (wp_all["open_pct"] * 100.0).astype(float)
    pools["Anchor_Wide_P1_All"] = wp_all

    hf_clean = hf[(~hf["nuclear_halt"]) & (~hf["promo_freeze"]) & (~hf["is_event_basket"]) & (hf["plate"] != "其他")].copy()
    hf_305 = hf_clean[hf_clean["score_active"] >= 304.8].sort_values(["buy_date", "score_active", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    hf_305["sd_csrc_ind_id"] = hf_305["csrc_ind_id"]
    hf_305["anchor_pool"] = "Anchor_Wide_HF_Ge305"
    hf_305["is_0925_known"] = np.int8(1)
    hf_305["anchor_score"] = hf_305["score_active"].astype(float)
    hf_305["anchor_open_pct"] = (hf_305["d2_o_pct"] * 100.0).astype(float)
    pools["Anchor_Wide_HF_Ge305"] = hf_305

    hf_275 = hf_clean[hf_clean["score_active"] >= 275.0].sort_values(["buy_date", "score_active", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    hf_275["sd_csrc_ind_id"] = hf_275["csrc_ind_id"]
    hf_275["anchor_pool"] = "Anchor_Wide_HF_Ge275"
    hf_275["is_0925_known"] = np.int8(1)
    hf_275["anchor_score"] = hf_275["score_active"].astype(float)
    hf_275["anchor_open_pct"] = (hf_275["d2_o_pct"] * 100.0).astype(float)
    pools["Anchor_Wide_HF_Ge275"] = hf_275

    orig_dts = set(p1.loc[p1["orig_pass"] == 1, "buy_date"])
    ms_yz = hf_clean[(hf_clean["score_active"] >= 290.0) & hf_clean["is_yizi_or_over"] & (~hf_clean["buy_date"].isin(orig_dts))].copy()
    ms_yz = ms_yz.sort_values(["buy_date", "score_active", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    ms_yz["sd_csrc_ind_id"] = ms_yz["csrc_ind_id"]
    ms_yz["anchor_pool"] = "Anchor_Missed_YiziOver"
    ms_yz["is_0925_known"] = np.int8(1)
    ms_yz["anchor_score"] = ms_yz["score_active"].astype(float)
    ms_yz["anchor_open_pct"] = (ms_yz["d2_o_pct"] * 100.0).astype(float)
    pools["Anchor_Missed_YiziOver"] = ms_yz

    ms_ut = p1[(p1["pool_layer"] == "untrig") & (p1["v20_score"] >= 304.8) & (~p1["buy_date"].isin(orig_dts))].copy()
    ms_ut = ms_ut.sort_values(["buy_date", "v20_score", "code"], ascending=[True, False, True]).groupby("buy_date", as_index=False).first()
    ms_ut["anchor_pool"] = "Anchor_Missed_Untrig"
    ms_ut["is_0925_known"] = np.int8(0)
    ms_ut["anchor_score"] = ms_ut["v20_score"].astype(float)
    ms_ut["anchor_open_pct"] = (ms_ut["open_pct"] * 100.0).astype(float)
    pools["Anchor_Missed_Untrig"] = ms_ut

    keep_anchor_cols = ["buy_date", "code", "name", "plate", "sd_csrc_ind_id", "anchor_score", "anchor_open_pct", "is_0925_known", "anchor_pool"]
    all_anc = pd.concat([df[keep_anchor_cols] for df in pools.values()], ignore_index=True)
    return all_anc, pools


def main():
    t0 = time.time()
    all_anc, anchor_pools = build_anchors()

    raw_idx = json.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))
    all_cal = sorted(raw_idx["sh000300"].keys())
    cal_5y = [d for d in all_cal if "2021-01-04" <= d <= "2026-11-25"]
    cal_idx = {d: i for i, d in enumerate(cal_5y)}

    anc_dts = sorted(all_anc["buy_date"].unique())
    anc_di_set = {cal_idx[d] for d in anc_dts if d in cal_idx}

    kpl_plate_recs = defaultdict(list)
    seen_kpl_dts = set()
    for path_k, min_dt in [(f"{DATA_DIR}/kpl_plates_5y_2021_2026_complete.jsonl", "2021-01-04"),
                           (f"{DATA_DIR}/kpl_plates_2018_2026_merged.jsonl", "2026-11-11")]:
        with open(path_k, encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                d = str(o["date"])[:10]
                if d < min_dt or d in seen_kpl_dts:
                    continue
                di = cal_idx.get(d, -1)
                if di < 0:
                    continue
                seen_kpl_dts.add(d)
                for pl in o.get("plates", []):
                    pn = str(pl.get("plate", ""))
                    if not pn or pn in ("其他", "ST板块"):
                        continue
                    base = pn.split("(")[0].strip()
                    for s in pl.get("stocks", []):
                        c6 = str(s[0]).strip()[:6].zfill(6)
                        kpl_plate_recs[pn].append((di, c6))
                        if base and base != pn:
                            kpl_plate_recs[base].append((di, c6))

    sys.path.insert(0, RD016_DIR)
    import step2_module2_leaderboard as rd16_m2
    famous_yz_codes = set()
    for k, v in rd16_m2.SEAT_GROUPS.items():
        if any(x in k for x in ("拉萨", "外资", "机构", "山南", "昌都", "瑞银", "高盛", "摩根", "量化", "国信浙江")):
            continue
        famous_yz_codes |= set(v)

    bs = pd.read_parquet(f"{RD016_DIR}/bayes_seat_scores_d1_5y.parquet")
    bs["c6"] = bs["stock_code"].astype(str).str.zfill(6)
    bs["di"] = bs["date"].astype(str).str[:10].map(cal_idx).fillna(-1).astype(np.int32)
    bs["is_fam_yz"] = bs["dept_code"].astype(str).isin(famous_yz_codes).astype(np.int8)
    bs = bs[bs["di"] >= 0].copy()
    bs_day = bs.groupby(["c6", "di"], as_index=False).agg(n_fam=("is_fam_yz", "sum"), n_seats=("dept_code", "count"))
    yz_by_c6 = {c6: (g["di"].to_numpy(np.int32), g["n_fam"].to_numpy(np.int32), g["n_seats"].to_numpy(np.int32))
                for c6, g in bs_day.sort_values("di").groupby("c6", sort=False)}
    del bs, bs_day
    gc.collect()

    csrc_raw = pd.read_csv(f"{DATA_DIR}/csrc_industry_pit_clean.csv", usecols=["code", "code_name"])
    csrc_raw["c6"] = csrc_raw["code"].astype(str).str[-6:]
    name_map = dict(zip(csrc_raw["c6"], csrc_raw["code_name"].astype(str)))
    del csrc_raw

    # Pass 1: Metadata + slim price/tradability arrays
    meta = pd.read_parquet(CORE_PQ, columns=["dt", "c6"])
    pa.default_memory_pool().release_unused()
    dt_cats = meta["dt"].cat.categories.astype(str).tolist()
    c6_cats = meta["c6"].cat.categories.astype(str).tolist()
    c6_to_int = {c: i for i, c in enumerate(c6_cats)}
    dt_code_to_cal = np.array([cal_idx.get(d, -1) for d in dt_cats], dtype=np.int16)
    d_idx_arr = dt_code_to_cal[meta["dt"].cat.codes.values]
    c_codes = meta["c6"].cat.codes.values.astype(np.int16)
    del meta
    gc.collect()

    n = len(c_codes)
    brk = np.flatnonzero(c_codes[1:] != c_codes[:-1]) + 1
    starts = np.concatenate(([0], brk))
    ends = np.concatenate((brk, [n]))

    is_anc_row = np.isin(d_idx_arr, list(anc_di_set))
    anc_pos = np.flatnonzero(is_anc_row)
    n_anc_rows = len(anc_pos)

    d1 = _read_cols_numpy(["open", "close", "adj_factor", "prev_close_raw", "amount_yi", "turn_pct", "open_pct", "ret_1d"])
    ao_all = (d1["open"] * d1["adj_factor"]).astype(np.float32)
    ac_all = (d1["close"] * d1["adj_factor"]).astype(np.float32)
    open_raw = d1["open"]
    prev_c_raw = d1["prev_close_raw"]
    amt_all = d1["amount_yi"]
    trn_all = d1["turn_pct"]
    op_all = d1["open_pct"]
    r1_all = d1["ret_1d"]
    del d1
    gc.collect()

    d2 = _read_cols_numpy(["is_zt", "is_yizi_zt", "is_dt", "is_yizi_dt", "is_st_pit", "is_20cm"])
    iz_all = d2["is_zt"]
    iyz_all = d2["is_yizi_zt"]
    idt_all = d2["is_dt"]
    iydt_all = d2["is_yizi_dt"]
    ist_all = d2["is_st_pit"]
    i20_all = d2["is_20cm"]
    del d2
    gc.collect()

    lim_arr = np.where(i20_all == 1, 0.20, 0.10)
    zt_px_all = np.round(prev_c_raw * (1.0 + lim_arr), 2)
    can_buy_open_all = (
        (ist_all == 0) & (amt_all > 0.05) & (iyz_all == 0) & (iydt_all == 0)
        & (ao_all > 0) & (open_raw < zt_px_all - 0.005) & (op_all < lim_arr * 100.0 - 0.15)
    ).astype(np.int8)
    can_buy_close_all = ((ist_all == 0) & (amt_all > 0.05) & (iz_all == 0) & (idt_all == 0) & (ac_all > 0)).astype(np.int8)
    del open_raw, prev_c_raw, lim_arr, zt_px_all, iydt_all
    gc.collect()

    stock_slices = {int(c_codes[s]): (int(s), int(e)) for s, e in zip(starts, ends)}

    # Rolling T-1 arrays extracted ONLY at anc_pos
    anc_map_pos = np.full(n, -1, dtype=np.int32)
    anc_map_pos[anc_pos] = np.arange(n_anc_rows, dtype=np.int32)

    zt20_anc = np.zeros(n_anc_rows, dtype=np.int16)
    zt60_anc = np.zeros(n_anc_rows, dtype=np.int16)
    amt20_anc = np.full(n_anc_rows, np.nan, dtype=np.float32)
    trn20_anc = np.full(n_anc_rows, np.nan, dtype=np.float32)
    yz1y_anc = np.zeros(n_anc_rows, dtype=np.int16)
    yz3y_anc = np.zeros(n_anc_rows, dtype=np.int16)

    for s, e in zip(starts, ends):
        ap = anc_map_pos[s:e]
        mask_has = ap >= 0
        if not mask_has.any():
            continue
        cs_z = np.concatenate(([0], np.cumsum(iz_all[s:e].astype(np.int32))))
        cs_a = np.concatenate(([0.0], np.cumsum(np.nan_to_num(amt_all[s:e].astype(np.float64), nan=0.0))))
        cs_t = np.concatenate(([0.0], np.cumsum(np.nan_to_num(trn_all[s:e].astype(np.float64), nan=0.0))))

        loc_i = np.flatnonzero(mask_has)
        out_i = ap[loc_i]
        lo20 = np.maximum(0, loc_i - 20)
        lo60 = np.maximum(0, loc_i - 60)
        cnt20 = np.maximum(1, loc_i - lo20)
        zt20_anc[out_i] = (cs_z[loc_i] - cs_z[lo20]).astype(np.int16)
        zt60_anc[out_i] = (cs_z[loc_i] - cs_z[lo60]).astype(np.int16)
        ok1 = loc_i > 0
        amt20_anc[out_i[ok1]] = ((cs_a[loc_i[ok1]] - cs_a[lo20[ok1]]) / cnt20[ok1]).astype(np.float32)
        trn20_anc[out_i[ok1]] = ((cs_t[loc_i[ok1]] - cs_t[lo20[ok1]]) / cnt20[ok1]).astype(np.float32)

        tup = yz_by_c6.get(c6_cats[int(c_codes[s])])
        if tup is not None:
            yd, yf, _ = tup
            p_arr = d_idx_arr[s + loc_i].astype(np.int32) - 1
            cs_yf = np.concatenate(([0], np.cumsum(yf)))
            rp = np.searchsorted(yd, p_arr, side="right")
            lp1 = np.searchsorted(yd, p_arr - 250, side="left")
            lp3 = np.searchsorted(yd, p_arr - 750, side="left")
            yz1y_anc[out_i] = (cs_yf[rp] - cs_yf[lp1]).astype(np.int16)
            yz3y_anc[out_i] = (cs_yf[rp] - cs_yf[lp3]).astype(np.int16)

    del anc_map_pos, trn_all, amt_all, yz_by_c6
    gc.collect()

    # Pass 2A: Read ONLY the 7 peer-ranking columns for anchor-date rows (< 120 MB!)
    rank_cols = ["free_mcap_yi_t1", "ret_20d_t1", "list_age", "waves_3y_g15_t1", "csrc_ind_id"]
    d_rk = _read_cols_numpy(rank_cols, keep_mask=is_anc_row)

    # Read zt_cnt_3y_t1 from old_hot ONLY on anc_dts via compact lookup (no string merge!)
    oh = pd.read_parquet(OH_PQ, columns=["c6", "dt", "zt_cnt_3y_t1"], filters=[("dt", "in", anc_dts)])
    oh_c = oh["c6"].astype(str).map(c6_to_int).fillna(-1).to_numpy(np.int32)
    oh_d = oh["dt"].astype(str).map(cal_idx).fillna(-1).to_numpy(np.int32)
    oh_z = oh["zt_cnt_3y_t1"].fillna(0).to_numpy(np.int16)
    del oh
    gc.collect()
    oh_key = oh_c.astype(np.int64) * 10000 + oh_d.astype(np.int64)
    oh_map = dict(zip(oh_key.tolist(), oh_z.tolist()))
    del oh_c, oh_d, oh_z, oh_key

    anc_keys = c_codes[anc_pos].astype(np.int64) * 10000 + d_idx_arr[anc_pos].astype(np.int64)
    zt3y_anc = np.array([oh_map.get(int(k), 0) for k in anc_keys], dtype=np.int16)
    del oh_map, anc_keys

    # Compact slim dataframe (18 columns, ~200 MB!)
    slim = pd.DataFrame({
        "row_idx": anc_pos.astype(np.int32),
        "c_code": c_codes[anc_pos],
        "di": d_idx_arr[anc_pos],
        "c6": [c6_cats[i] for i in c_codes[anc_pos]],
        "is_st_pit": ist_all[anc_pos],
        "is_20cm": i20_all[anc_pos],
        "is_zt_t0": iz_all[anc_pos],
        "open_pct_t0": op_all[anc_pos],
        "ret_1d_t0": r1_all[anc_pos],
        "zt20_t1": zt20_anc,
        "zt60_t1": zt60_anc,
        "amt20_t1": amt20_anc,
        "trn20_t1": trn20_anc,
        "yz1y_t1": yz1y_anc,
        "yz3y_t1": yz3y_anc,
        "zt_cnt_3y_t1": zt3y_anc,
        "free_mcap_yi_t1": d_rk["free_mcap_yi_t1"],
        "ret_20d_t1": d_rk["ret_20d_t1"],
        "list_age": d_rk["list_age"],
        "waves_3y_g15_t1": d_rk["waves_3y_g15_t1"],
        "csrc_ind_id": d_rk["csrc_ind_id"],
    })
    del d_rk, zt20_anc, zt60_anc, amt20_anc, trn20_anc, yz1y_anc, yz3y_anc, zt3y_anc
    gc.collect()

    print(f"[Pass2A] slim shape={slim.shape} | RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9:.3f}GB")

    day_groups = {int(di_v): g.reset_index(drop=True) for di_v, g in slim.groupby("di", sort=False)}
    del slim
    gc.collect()

    def eval_forward(c_code: int, di_anchor: int, entry_mode: str):
        sl = stock_slices.get(int(c_code))
        if sl is None:
            return None
        s, e = sl
        d_sub = d_idx_arr[s:e]
        target_buy_di = di_anchor if entry_mode in ("T0_Open", "T0_Close") else (di_anchor + 1)
        pos_b = int(np.searchsorted(d_sub, target_buy_di))
        if pos_b >= len(d_sub) or d_sub[pos_b] != target_buy_di:
            return None
        bi = s + pos_b
        if entry_mode in ("T0_Open", "T1_Open"):
            can_buy = bool(can_buy_open_all[bi] == 1)
            buy_px_adj = float(ao_all[bi])
            buy_hhmm = 925
        else:
            can_buy = bool(can_buy_close_all[bi] == 1)
            buy_px_adj = float(ac_all[bi])
            buy_hhmm = 1500
        if buy_px_adj <= 0.0:
            return None
        buy_dt = cal_5y[int(d_idx_arr[bi])]
        open_pct_entry = float(op_all[bi])
        out = {"buy_date": buy_dt, "buy_hhmm": buy_hhmm, "can_buy": can_buy, "open_pct_entry": open_pct_entry, "ex": {}}
        for h in (1, 2, 3, 5):
            target_ex_di = target_buy_di + h
            ep = min(bi + h, e - 1)
            while ep > bi and d_idx_arr[ep - 1] >= target_ex_di:
                ep -= 1
            while ep < e and d_idx_arr[ep] < target_ex_di:
                ep += 1
            if ep >= e or ep <= bi:
                continue
            lim_d = 0
            while ep < e - 1 and lim_d < 5 and idt_all[ep] == 1:
                ep += 1
                lim_d += 1
            ace = float(ac_all[ep])
            if idt_all[ep] == 1 or ace <= 0.0:
                continue
            gr = ace / buy_px_adj - 1.0
            ex_dt = cal_5y[int(d_idx_arr[ep])]
            segs = []
            if entry_mode in ("T0_Open", "T1_Open"):
                segs.append((int(d_idx_arr[bi]), float(ac_all[bi]) / buy_px_adj))
                for k in range(bi + 1, ep + 1):
                    segs.append((int(d_idx_arr[k]), float(ac_all[k]) / float(ac_all[k - 1])))
            else:
                for k in range(bi + 1, ep + 1):
                    segs.append((int(d_idx_arr[k]), float(ac_all[k]) / float(ac_all[k - 1])))
            out["ex"][h] = (ex_dt, float(gr), segs)
        return out

    # Anchor T0 close status
    anc_zt_t0_map = {}
    for r in all_anc[["buy_date", "code"]].drop_duplicates().itertuples(index=False):
        di_a = cal_idx.get(r.buy_date)
        gdf = day_groups.get(di_a) if di_a is not None else None
        if gdf is not None:
            ma = gdf[gdf["c6"] == r.code]
            if not ma.empty:
                anc_zt_t0_map[(r.buy_date, r.code)] = (int(ma.iloc[0]["is_zt_t0"]), float(ma.iloc[0]["ret_1d_t0"]))

    # Select Peer Top-5 per unique (buy_date, anchor_code, plate, csrc_ind_id)
    uniq_anc_keys = all_anc[["buy_date", "code", "plate", "sd_csrc_ind_id"]].drop_duplicates().reset_index(drop=True)
    peer_cache = {}
    selected_row_idxs = set()

    for r in uniq_anc_keys.itertuples(index=False):
        dt = r.buy_date
        di = cal_idx.get(dt)
        if di is None or di not in day_groups:
            continue
        gdf = day_groups[di]
        cand = gdf[(gdf["c6"] != r.code) & (gdf["is_st_pit"] == 0) & (gdf["list_age"] > 20) & (gdf["free_mcap_yi_t1"] > 0)].copy()
        if cand.empty:
            continue

        pl = str(r.plate)
        base_pl = pl.split("(")[0].strip()
        recs_exact = kpl_plate_recs.get(pl, [])
        recs_base = kpl_plate_recs.get(base_pl, [])

        def _count_kpl(recs):
            c3y, c1y, c60, ct1 = defaultdict(int), defaultdict(int), defaultdict(int), set()
            for d_i, c6 in recs:
                if d_i < di:
                    if d_i >= di - 750: c3y[c6] += 1
                    if d_i >= di - 250: c1y[c6] += 1
                    if d_i >= di - 60: c60[c6] += 1
                    if d_i == di - 1: ct1.add(c6)
            return c3y, c1y, c60, ct1

        c3y, c1y, c60, ct1 = _count_kpl(recs_exact)
        if len(c3y) < 3 and recs_base:
            c3y, c1y, c60, ct1 = _count_kpl(recs_base)
        c3y_b, _, _, _ = _count_kpl(recs_base if recs_base else recs_exact)

        cand["kpl_3y"] = cand["c6"].map(c3y).fillna(0).astype(np.int16)
        cand["kpl_1y"] = cand["c6"].map(c1y).fillna(0).astype(np.int16)
        cand["kpl_60"] = cand["c6"].map(c60).fillna(0).astype(np.int16)
        cand["kpl_on_t1"] = cand["c6"].isin(ct1).astype(np.int8)
        cand["kpl_3y_base"] = cand["c6"].map(c3y_b).fillna(0).astype(np.int16)

        cid = int(r.sd_csrc_ind_id) if pd.notna(r.sd_csrc_ind_id) else -1
        csrc_pool = cand[cand["csrc_ind_id"] == cid] if cid >= 0 else cand.iloc[:0]

        kpl_3y_pool = cand[cand["kpl_3y"] >= 2]
        if len(kpl_3y_pool) < 3:
            kpl_3y_pool = cand[cand["kpl_3y"] >= 1]
        kpl_60_pool = cand[cand["kpl_60"] >= 1]
        if len(kpl_60_pool) < 3:
            kpl_60_pool = kpl_3y_pool

        picks = {}
        if not kpl_3y_pool.empty:
            p1a = kpl_3y_pool.copy()
            p1a["_sc"] = (p1a["waves_3y_g15_t1"].rank(pct=True) * 0.30 + p1a["zt_cnt_3y_t1"].rank(pct=True) * 0.30 +
                          p1a["yz3y_t1"].rank(pct=True) * 0.25 + p1a["kpl_3y"].rank(pct=True) * 0.15)
            picks["Peer1A_OldYouzi_KPL"] = p1a.sort_values(["_sc", "zt_cnt_3y_t1", "c6"], ascending=[False, False, True]).head(5)
            p1b = p1a[p1a["free_mcap_yi_t1"] <= 150.0]
            if not p1b.empty:
                picks["Peer1B_OldYouzi_SmallMid"] = p1b.sort_values(["_sc", "zt_cnt_3y_t1", "c6"], ascending=[False, False, True]).head(5)

        if not csrc_pool.empty:
            p1c = csrc_pool.copy()
            p1c["_sc"] = p1c["waves_3y_g15_t1"].rank(pct=True) * 0.35 + p1c["zt_cnt_3y_t1"].rank(pct=True) * 0.35 + p1c["yz3y_t1"].rank(pct=True) * 0.30
            picks["Peer1C_OldYouzi_CSRC"] = p1c.sort_values(["_sc", "zt_cnt_3y_t1", "c6"], ascending=[False, False, True]).head(5)

        if not kpl_60_pool.empty:
            p2 = kpl_60_pool.copy()
            p2["_sc"] = (p2["zt60_t1"].rank(pct=True) * 0.35 + p2["zt20_t1"].rank(pct=True) * 0.30 +
                         p2["trn20_t1"].fillna(0).rank(pct=True) * 0.20 + p2["ret_20d_t1"].fillna(0).rank(pct=True) * 0.15)
            picks["Peer2_RecentActive_KPL"] = p2.sort_values(["_sc", "zt60_t1", "c6"], ascending=[False, False, True]).head(5)

        if not csrc_pool.empty:
            p2c = csrc_pool.copy()
            p2c["_sc"] = (p2c["zt60_t1"].rank(pct=True) * 0.35 + p2c["zt20_t1"].rank(pct=True) * 0.30 +
                          p2c["trn20_t1"].fillna(0).rank(pct=True) * 0.20 + p2c["ret_20d_t1"].fillna(0).rank(pct=True) * 0.15)
            picks["Peer2B_RecentActive_CSRC"] = p2c.sort_values(["_sc", "zt60_t1", "c6"], ascending=[False, False, True]).head(5)

        tp_inst = cand[cand["kpl_1y"] >= 1]
        if (tp_inst["free_mcap_yi_t1"] >= 100.0).sum() == 0:
            tp_inst = cand[cand["kpl_3y"] >= 1]
        if (tp_inst["free_mcap_yi_t1"] >= 100.0).sum() == 0:
            tp_inst = cand[cand["kpl_3y_base"] >= 1]
        if not tp_inst.empty:
            q80 = float(tp_inst["free_mcap_yi_t1"].quantile(0.80))
            p3a = tp_inst[tp_inst["free_mcap_yi_t1"] >= max(100.0, q80)]
            if p3a.empty:
                p3a = tp_inst[tp_inst["free_mcap_yi_t1"] >= 100.0]
            if not p3a.empty:
                picks["Peer3A_InstBigCap_KPL100"] = p3a.sort_values(["amt20_t1", "free_mcap_yi_t1", "c6"], ascending=[False, False, True]).head(5)
            p3b = tp_inst[tp_inst["free_mcap_yi_t1"] >= max(150.0, q80)]
            if p3b.empty:
                p3b = tp_inst[tp_inst["free_mcap_yi_t1"] >= 150.0]
            if not p3b.empty:
                picks["Peer3B_InstBigCap_KPL150"] = p3b.sort_values(["amt20_t1", "free_mcap_yi_t1", "c6"], ascending=[False, False, True]).head(5)

        if not csrc_pool.empty:
            q80_c = float(csrc_pool["free_mcap_yi_t1"].quantile(0.80))
            p3c = csrc_pool[csrc_pool["free_mcap_yi_t1"] >= max(100.0, q80_c)]
            if p3c.empty:
                p3c = csrc_pool[csrc_pool["free_mcap_yi_t1"] >= 100.0]
            if not p3c.empty:
                picks["Peer3C_InstBigCap_CSRC100"] = p3c.sort_values(["amt20_t1", "free_mcap_yi_t1", "c6"], ascending=[False, False, True]).head(5)
            p4 = csrc_pool.copy()
            p4["_sc"] = p4["free_mcap_yi_t1"].rank(pct=True) * 0.50 + p4["amt20_t1"].fillna(0).rank(pct=True) * 0.50
            picks["Peer4_IndLeader1"] = p4.sort_values(["_sc", "free_mcap_yi_t1", "c6"], ascending=[False, False, True]).head(5)

        for _, pdf in picks.items():
            selected_row_idxs.update(pdf["row_idx"].tolist())
        peer_cache[(dt, r.code, pl)] = picks

    del day_groups, kpl_plate_recs
    gc.collect()

    # Pass 2B: Read remaining 27 scorecard features ONLY for the ~10k selected_row_idxs (< 5 MB!)
    sel_mask = np.zeros(n, dtype=bool)
    sel_arr = np.array(sorted(selected_row_idxs), dtype=np.int64)
    sel_mask[sel_arr] = True
    extra_cols = [
        "ret_1d_t1", "ret_5d_t1", "real_turn_pct_t1", "pos_20d_t1", "pos_60d_t1", "pos_250d_t1",
        "dd_20d_t1", "bias10_t1", "bias20_t1", "vol_ratio5_t1", "turn_5_20_t1", "amp_20d_t1", "overhang_pct_t1",
        "lhb_bayes_t2_t1", "lhb_inst_net_yi_t1", "lhb_has_good_yz_t1",
        "cool_days_since_last_zt", "comm_posts_1y_pct", "xq_posts_1y_pct",
        "csrc_ind_ex5_t1", "csrc_ind_ex20_t1", "csrc_ind_rank20_t1", "csrc_ind_zt_share5_t1",
    ]
    d_ext = _read_cols_numpy(extra_cols, keep_mask=sel_mask)
    ext_map = {int(sel_arr[i]): {c: float(d_ext[c][i]) for c in extra_cols} for i in range(len(sel_arr))}
    del d_ext, sel_mask, sel_arr
    gc.collect()

    mkt_cols = [
        "trade_date", "L1_zt_cnt_t1", "L1_zb_rate_t1", "L1_zt_prem_t1", "L1_amt_ratio20_t1",
        "L1_ew_bias20_t1", "mkt_pct_above_ma20_t1", "mkt_0925_avg_gap_pct", "us_ixic_ret1d_on", "nt_v3_score_eod_t1",
    ]
    mkt_map = pd.read_parquet(MKT_PQ, columns=mkt_cols).set_index("trade_date").to_dict(orient="index")

    needed_fwd = set()
    for ar in all_anc.itertuples(index=False):
        di_a = cal_idx.get(ar.buy_date)
        if di_a is None:
            continue
        pdict = peer_cache.get((ar.buy_date, ar.code, str(ar.plate)), {})
        for _, pdf in pdict.items():
            for pr in pdf.itertuples(index=False):
                needed_fwd.add((int(pr.c_code), di_a))

    # Free Pass1/Pass2A temporary index arrays before building Output 1
    del is_anc_row, anc_pos
    gc.collect()

    fwd_cache = {(cc, di_a, em): eval_forward(cc, di_a, em) for cc, di_a in needed_fwd for em in ("T0_Open", "T0_Close", "T1_Open")}
    # Free large 7M arrays now that fwd_cache is materialized!
    del ao_all, ac_all, op_all, r1_all, iz_all, iyz_all, idt_all, ist_all, i20_all, can_buy_open_all, can_buy_close_all
    del d_idx_arr, c_codes, brk, starts, ends, stock_slices
    gc.collect()

    # Save Output 1 flushing every 20,000 rows using ParquetWriter so peak RSS stays < 1.85 GB
    pk_pq_path = f"{CACHE_DIR}/anchor_peer_1to1_all.parquet"
    writer = None
    tot_pk_rows = 0
    pk_rows = []

    def _flush_pk():
        nonlocal writer, tot_pk_rows, pk_rows
        if not pk_rows:
            return
        chunk_df = pd.DataFrame(pk_rows)
        tbl = pa.Table.from_pandas(chunk_df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(pk_pq_path, tbl.schema, compression="snappy")
        writer.write_table(tbl)
        tot_pk_rows += len(chunk_df)
        pk_rows = []
        del chunk_df, tbl
        gc.collect()

    for pool_name, pool_df in anchor_pools.items():
        for ar in pool_df.itertuples(index=False):
            dt = ar.buy_date
            di_a = cal_idx.get(dt)
            if di_a is None:
                continue
            pdict = peer_cache.get((dt, ar.code, str(ar.plate)), {})
            for p_cls, pdf in pdict.items():
                for em in ("T0_Open", "T0_Close", "T1_Open"):
                    is_causal = 1 if (em != "T0_Open" or int(ar.is_0925_known) == 1) else 0
                    top_fwds = [(rk_i, pr, fwd_cache.get((int(pr.c_code), di_a, em)))
                                for rk_i, pr in enumerate(pdf.itertuples(index=False))]
                    top_fwds = [(rk_i, pr, fw) for rk_i, pr, fw in top_fwds if fw is not None]
                    if not top_fwds:
                        continue

                    rk0, pr0, fw0 = top_fwds[0]
                    if rk0 == 0:
                        for h in (1, 2, 3, 5):
                            if h in fw0["ex"]:
                                ex_dt, gr, segs = fw0["ex"][h]
                                pk_rows.append({
                                    "anchor_pool": pool_name, "peer_class": p_cls, "agg_mode": "Top1_Raw",
                                    "entry_mode": em, "hold_h": int(h), "is_causal": int(is_causal), "is_0925_known": int(ar.is_0925_known),
                                    "anchor_date": dt, "anchor_code": ar.code, "anchor_plate": str(ar.plate), "anchor_score": float(ar.anchor_score),
                                    "buy_date": fw0["buy_date"], "buy_hhmm": int(fw0["buy_hhmm"]), "exit_date": ex_dt, "exit_hhmm": 1500,
                                    "code": pr0.c6, "name": name_map.get(pr0.c6, ""),
                                    "can_buy": int(fw0["can_buy"]), "is_yizi": int(not fw0["can_buy"]),
                                    "gross_ret": float(gr), "mtm_segs_json": json.dumps(segs),
                                    "free_mcap_yi_t1": float(pr0.free_mcap_yi_t1),
                                    "amt20_t1": float(pr0.amt20_t1) if pd.notna(pr0.amt20_t1) else np.nan,
                                    "ret_20d_t1": float(pr0.ret_20d_t1) if pd.notna(pr0.ret_20d_t1) else np.nan,
                                    "is_20cm": int(pr0.is_20cm),
                                })

                    buyables = [(rk_i, pr_i, fw_i) for rk_i, pr_i, fw_i in top_fwds if fw_i["can_buy"]]
                    if buyables:
                        _, pr_c, fw_c = buyables[0]
                        for h in (1, 2, 3, 5):
                            if h in fw_c["ex"]:
                                ex_dt, gr, segs = fw_c["ex"][h]
                                pk_rows.append({
                                    "anchor_pool": pool_name, "peer_class": p_cls, "agg_mode": "Top1_Cascade",
                                    "entry_mode": em, "hold_h": int(h), "is_causal": int(is_causal), "is_0925_known": int(ar.is_0925_known),
                                    "anchor_date": dt, "anchor_code": ar.code, "anchor_plate": str(ar.plate), "anchor_score": float(ar.anchor_score),
                                    "buy_date": fw_c["buy_date"], "buy_hhmm": int(fw_c["buy_hhmm"]), "exit_date": ex_dt, "exit_hhmm": 1500,
                                    "code": pr_c.c6, "name": name_map.get(pr_c.c6, ""),
                                    "can_buy": 1, "is_yizi": 0, "gross_ret": float(gr), "mtm_segs_json": json.dumps(segs),
                                    "free_mcap_yi_t1": float(pr_c.free_mcap_yi_t1),
                                    "amt20_t1": float(pr_c.amt20_t1) if pd.notna(pr_c.amt20_t1) else np.nan,
                                    "ret_20d_t1": float(pr_c.ret_20d_t1) if pd.notna(pr_c.ret_20d_t1) else np.nan,
                                    "is_20cm": int(pr_c.is_20cm),
                                })

                    top3_buy = [(rk_i, pr_i, fw_i) for rk_i, pr_i, fw_i in top_fwds if rk_i < 3 and fw_i["can_buy"]]
                    if top3_buy:
                        for h in (1, 2, 3, 5):
                            sub_h = [(pr_i, fw_i["ex"][h]) for _, pr_i, fw_i in top3_buy if h in fw_i["ex"]]
                            if not sub_h:
                                continue
                            gr_ew = float(np.mean([x[1][1] for x in sub_h]))
                            all_di_set = sorted({di_k for _, (_, _, segs_i) in sub_h for di_k, _ in segs_i})
                            n_sub = len(sub_h)
                            stock_val = [1.0 / n_sub] * n_sub
                            stock_seg_map = [{di_k: m_k for di_k, m_k in segs_i} for _, (_, _, segs_i) in sub_h]
                            ew_segs = []
                            prev_tot = 1.0
                            for di_k in all_di_set:
                                for si_idx in range(n_sub):
                                    if di_k in stock_seg_map[si_idx]:
                                        stock_val[si_idx] *= stock_seg_map[si_idx][di_k]
                                cur_tot = float(sum(stock_val))
                                ew_segs.append([int(di_k), cur_tot / prev_tot])
                                prev_tot = cur_tot
                            max_ex = max(x[1][0] for x in sub_h)
                            pk_rows.append({
                                "anchor_pool": pool_name, "peer_class": p_cls, "agg_mode": "Top3_EW",
                                "entry_mode": em, "hold_h": int(h), "is_causal": int(is_causal), "is_0925_known": int(ar.is_0925_known),
                                "anchor_date": dt, "anchor_code": ar.code, "anchor_plate": str(ar.plate), "anchor_score": float(ar.anchor_score),
                                "buy_date": top3_buy[0][2]["buy_date"], "buy_hhmm": int(top3_buy[0][2]["buy_hhmm"]), "exit_date": max_ex, "exit_hhmm": 1500,
                                "code": ",".join(x[0].c6 for x in sub_h), "name": ",".join(name_map.get(x[0].c6, "") for x in sub_h),
                                "can_buy": 1, "is_yizi": 0, "gross_ret": gr_ew, "mtm_segs_json": json.dumps(ew_segs),
                                "free_mcap_yi_t1": float(np.mean([x[0].free_mcap_yi_t1 for x in sub_h])),
                                "amt20_t1": float(np.nanmean([x[0].amt20_t1 for x in sub_h])),
                                "ret_20d_t1": float(np.nanmean([x[0].ret_20d_t1 for x in sub_h])),
                                "is_20cm": int(any(x[0].is_20cm == 1 for x in sub_h)),
                            })
            if len(pk_rows) >= 10000:
                _flush_pk()
                pa.default_memory_pool().release_unused()
    _flush_pk()
    if writer is not None:
        writer.close()
    pa.default_memory_pool().release_unused()
    print(f"[Output1] Saved anchor_peer_1to1_all.parquet | rows={tot_pk_rows:,} | RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9:.3f}GB")

    # Save Output 2: WF multi-factor candidate pool
    p1_all_dts = set(anchor_pools["Anchor_Wide_P1_All"]["buy_date"])
    p1_305_dts = set(anchor_pools["Anchor_Wide_P1_Ge305"]["buy_date"])
    hf_305_dts = set(anchor_pools["Anchor_Wide_HF_Ge305"]["buy_date"])
    base_wf_anc = anchor_pools["Anchor_Wide_HF_Ge275"].copy()

    target_classes = ["Peer1A_OldYouzi_KPL", "Peer1B_OldYouzi_SmallMid", "Peer2_RecentActive_KPL", "Peer3A_InstBigCap_KPL100", "Peer4_IndLeader1"]
    wf_rows = []
    for ar in base_wf_anc.itertuples(index=False):
        dt = ar.buy_date
        di_a = cal_idx.get(dt)
        if di_a is None:
            continue
        pdict = peer_cache.get((dt, ar.code, str(ar.plate)), {})
        mkt_r = mkt_map.get(dt, {})
        anc_zt_t0, anc_ret_t0 = anc_zt_t0_map.get((dt, ar.code), (0, np.nan))

        by_peer = {}
        for p_cls in target_classes:
            pdf = pdict.get(p_cls)
            if pdf is None or pdf.empty:
                continue
            for rk_i, pr in enumerate(pdf.head(3).itertuples(index=False)):
                rec = by_peer.get(pr.c6)
                if rec is None:
                    rec = {"pr": pr, "roles": set(), "min_rk": rk_i + 1}
                    by_peer[pr.c6] = rec
                rec["roles"].add(p_cls)
                rec["min_rk"] = min(rec["min_rk"], rk_i + 1)

        for c6, info in by_peer.items():
            pr = info["pr"]
            roles = info["roles"]
            ef = ext_map.get(int(pr.row_idx), {})
            row_base = {
                "anchor_date": dt, "anchor_code": ar.code, "anchor_plate": str(ar.plate),
                "anchor_score": float(ar.anchor_score),
                "anchor_s_prior": float(ar.s_prior_dual) if hasattr(ar, "s_prior_dual") else np.nan,
                "anchor_s_quant": float(ar.s_q_base_dual) if hasattr(ar, "s_q_base_dual") else np.nan,
                "anchor_open_pct": float(ar.anchor_open_pct),
                "anchor_p_sz": float(ar.p_sz) if hasattr(ar, "p_sz") else np.nan,
                "anchor_rk_theme": float(ar.rk_theme) if hasattr(ar, "rk_theme") and pd.notna(ar.rk_theme) else 99.0,
                "anchor_d1_tight": float(ar.d1_seal_tightness) if hasattr(ar, "d1_seal_tightness") else np.nan,
                "anchor_front_lock": float(ar.front_lock_cnt) if hasattr(ar, "front_lock_cnt") else 0.0,
                "anchor_yizi_cnt": float(ar.mkt_yizi_cnt) if hasattr(ar, "mkt_yizi_cnt") else 0.0,
                "anchor_zt_t0": int(anc_zt_t0), "anchor_ret_t0": float(anc_ret_t0),
                "in_p1_all": int(dt in p1_all_dts), "in_p1_ge305": int(dt in p1_305_dts), "in_hf_ge305": int(dt in hf_305_dts),
                "code": c6, "name": name_map.get(c6, ""), "c_code": int(pr.c_code),
                "role_oldyz": int(("Peer1A_OldYouzi_KPL" in roles) or ("Peer1B_OldYouzi_SmallMid" in roles)),
                "role_oldyz_sm": int("Peer1B_OldYouzi_SmallMid" in roles),
                "role_recact": int("Peer2_RecentActive_KPL" in roles),
                "role_inst": int("Peer3A_InstBigCap_KPL100" in roles),
                "role_ind1": int("Peer4_IndLeader1" in roles),
                "min_peer_rk": int(info["min_rk"]), "is_20cm": int(pr.is_20cm),
                "peer_kpl_on_t1": int(pr.kpl_on_t1), "peer_kpl_60": int(pr.kpl_60),
                "peer_kpl_1y": int(pr.kpl_1y), "peer_kpl_3y": int(pr.kpl_3y),
                "peer_free_mcap_log": float(np.log1p(max(0.0, float(pr.free_mcap_yi_t1)))),
                "peer_amt20_log": float(np.log1p(max(0.0, float(pr.amt20_t1)))) if pd.notna(pr.amt20_t1) else np.nan,
                "peer_ret_1d_t1": ef.get("ret_1d_t1", np.nan), "peer_ret_5d_t1": ef.get("ret_5d_t1", np.nan),
                "peer_ret_20d_t1": float(pr.ret_20d_t1),
                "peer_pos_20d_t1": ef.get("pos_20d_t1", np.nan), "peer_pos_60d_t1": ef.get("pos_60d_t1", np.nan),
                "peer_pos_250d_t1": ef.get("pos_250d_t1", np.nan), "peer_dd_20d_t1": ef.get("dd_20d_t1", np.nan),
                "peer_bias10_t1": ef.get("bias10_t1", np.nan), "peer_bias20_t1": ef.get("bias20_t1", np.nan),
                "peer_vol_ratio5_t1": ef.get("vol_ratio5_t1", np.nan), "peer_turn_5_20_t1": ef.get("turn_5_20_t1", np.nan),
                "peer_real_turn_t1": ef.get("real_turn_pct_t1", np.nan), "peer_amp_20d_t1": ef.get("amp_20d_t1", np.nan),
                "peer_overhang_t1": ef.get("overhang_pct_t1", np.nan),
                "peer_zt20_t1": int(pr.zt20_t1), "peer_zt60_t1": int(pr.zt60_t1),
                "peer_zt_3y_t1": int(pr.zt_cnt_3y_t1), "peer_waves_3y_t1": int(pr.waves_3y_g15_t1),
                "peer_yz3y_t1": int(pr.yz3y_t1), "peer_yz1y_t1": int(pr.yz1y_t1),
                "peer_cool_days_zt": ef.get("cool_days_since_last_zt", np.nan),
                "peer_comm_pct": ef.get("comm_posts_1y_pct", np.nan), "peer_xq_pct": ef.get("xq_posts_1y_pct", np.nan),
                "peer_lhb_bayes_t1": ef.get("lhb_bayes_t2_t1", np.nan), "peer_lhb_inst_t1": ef.get("lhb_inst_net_yi_t1", np.nan),
                "peer_lhb_goodyz_t1": int(ef.get("lhb_has_good_yz_t1", 0)),
                "peer_ind_ex5_t1": ef.get("csrc_ind_ex5_t1", np.nan), "peer_ind_ex20_t1": ef.get("csrc_ind_ex20_t1", np.nan),
                "peer_ind_rk20_t1": ef.get("csrc_ind_rank20_t1", np.nan), "peer_ind_zt_sh5_t1": ef.get("csrc_ind_zt_share5_t1", np.nan),
                "peer_open_pct_t0": float(pr.open_pct_t0), "peer_open_minus_anc": float(pr.open_pct_t0) - float(ar.anchor_open_pct),
                "peer_ret_1d_t0": float(pr.ret_1d_t0), "peer_is_zt_t0": int(pr.is_zt_t0),
                "mkt_zt_cnt_t1": float(mkt_r.get("L1_zt_cnt_t1", np.nan)), "mkt_zb_rate_t1": float(mkt_r.get("L1_zb_rate_t1", np.nan)),
                "mkt_zt_prem_t1": float(mkt_r.get("L1_zt_prem_t1", np.nan)), "mkt_amt_ratio20_t1": float(mkt_r.get("L1_amt_ratio20_t1", np.nan)),
                "mkt_ew_bias20_t1": float(mkt_r.get("L1_ew_bias20_t1", np.nan)), "mkt_abv_ma20_t1": float(mkt_r.get("mkt_pct_above_ma20_t1", np.nan)),
                "mkt_0925_gap": float(mkt_r.get("mkt_0925_avg_gap_pct", np.nan)), "us_ixic_1d_on": float(mkt_r.get("us_ixic_ret1d_on", np.nan)),
                "nt_v3_eod_t1": float(mkt_r.get("nt_v3_score_eod_t1", np.nan)),
            }
            for em in ("T0_Open", "T0_Close", "T1_Open"):
                fw = fwd_cache.get((int(pr.c_code), di_a, em))
                if fw is None or not fw["can_buy"]:
                    continue
                row_em = dict(row_base)
                row_em["entry_mode"] = em
                row_em["buy_date"] = fw["buy_date"]
                row_em["buy_hhmm"] = fw["buy_hhmm"]
                row_em["entry_open_pct"] = fw["open_pct_entry"]
                for h in (1, 2, 3, 5):
                    if h in fw["ex"]:
                        ex_dt, gr, segs = fw["ex"][h]
                        row_em[f"exit_date_H{h}"] = ex_dt
                        row_em[f"gross_ret_H{h}"] = gr
                        row_em[f"mtm_segs_H{h}"] = json.dumps(segs)
                    else:
                        row_em[f"exit_date_H{h}"] = None
                        row_em[f"gross_ret_H{h}"] = np.nan
                        row_em[f"mtm_segs_H{h}"] = ""
                wf_rows.append(row_em)

    wf_df = pd.DataFrame(wf_rows)
    wf_df.to_parquet(f"{CACHE_DIR}/wf_peer_candidates_all.parquet", index=False)
    rss_gb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9
    print(f"[Output2] Saved wf_peer_candidates_all.parquet | rows={len(wf_df):,} | elapsed={time.time()-t0:.1f}s | Peak RSS={rss_gb:.3f} GB")
    assert rss_gb < 2.0, f"Peak RSS {rss_gb:.3f} GB >= 2.0 GB!"


if __name__ == "__main__":
    main()

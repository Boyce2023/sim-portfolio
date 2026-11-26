#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD047 Step 0: Build Strictly Causal PIT Dense Panel & Dual-Layer Theme Taxonomy Cache.
- Zero yfinance (D12).
- Column-by-column streaming read (zero full-table pandas allocation -> Peak RSS < 1.6 GB).
- Strictly filters ALL sources <= end_dt (supports physical truncation proof at 2024-12-31).
"""
import argparse
import gc
import json
import os
import re
import sys
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

RD047_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd047_main_theme_beta_wave2_20261126"
if RD047_DIR not in sys.path:
    sys.path.insert(0, RD047_DIR)

import _rd047_common as cm

NON_THEME = {
    "其他", "ST板块", "ST摘帽", "公告", "次新股", "超跌", "回购", "高送转",
    "业绩增长", "一季报增长", "半年报增长", "中报增长", "三季报增长", "年报增长",
    "预增", "扭亏", "摘帽", "复牌", "股权转让", "实控人变更", "定增", "解禁",
    "科创板", "昨日涨停", "昨日连板", "连板", "首板", "反包", "无",
}


def build_causal_sw3_matrix(cal_dts: list[str], stocks: list[str], csrc_id_mat: np.ndarray, end_dt: str) -> tuple[np.ndarray, list[str], dict]:
    """Strictly causal [N_D, N_S] industry ID matrix using Shenwan L3 (计入日期 <= dt) with CSRC fallback."""
    N_D, N_S = len(cal_dts), len(stocks)
    stk_map = {c: i for i, c in enumerate(stocks)}

    sw_c = pd.read_excel(f"{cm.ROOT}/sim-portfolio/backtest/2026-10-08-sector/sw_code.xls", dtype=str)
    sw_s = pd.read_excel(f"{cm.ROOT}/sim-portfolio/backtest/2026-10-08-sector/sw_stock.xls", dtype=str)
    sw_s["c6"] = sw_s["股票代码"].astype(str).str.zfill(6)
    sw_s["in_dt"] = sw_s["计入日期"].astype(str).str[:10]
    sw_m = sw_s.merge(sw_c, on="行业代码", how="left")
    sw_m = sw_m[(sw_m["in_dt"] <= end_dt) & sw_m["三级行业名称"].notna()].sort_values(["c6", "in_dt"]).reset_index(drop=True)

    csrc_csv = pd.read_csv(f"{cm.DATA_DIR}/csrc_industry_pit_clean.csv")
    csrc_csv["c6"] = csrc_csv["sec_code"].astype(str).str.zfill(6)
    csrc_csv = csrc_csv[csrc_csv["start_date"].astype(str).str[:10] <= end_dt]

    sw_l3_names = sorted(sw_m["三级行业名称"].unique().tolist())
    csrc_ids_present = sorted(set(int(x) for x in np.unique(csrc_id_mat) if x >= 0))
    c6_to_csrc_nm = csrc_csv.sort_values("start_date").drop_duplicates("c6", keep="last").set_index("c6")["industry"].to_dict()
    csrc_id_to_nm = {}
    last_d = N_D - 1
    for s_i, c6 in enumerate(stocks):
        cid = int(csrc_id_mat[last_d, s_i])
        if cid < 0:
            col = csrc_id_mat[:, s_i]
            v = col[col >= 0]
            cid = int(v[-1]) if len(v) else -1
        if cid >= 0 and cid not in csrc_id_to_nm and c6 in c6_to_csrc_nm and pd.notna(c6_to_csrc_nm[c6]):
            csrc_id_to_nm[cid] = str(c6_to_csrc_nm[c6])

    theme_names = [f"SW3:{nm}" for nm in sw_l3_names] + [f"CSRC:{csrc_id_to_nm.get(cid, f'ID{cid}')}" for cid in csrc_ids_present]
    name_to_id = {nm: idx for idx, nm in enumerate(theme_names)}
    cal_arr = np.array(cal_dts)

    ind_mat = np.full((N_D, N_S), -1, dtype=np.int16)
    for cid in csrc_ids_present:
        tid = name_to_id[f"CSRC:{csrc_id_to_nm.get(cid, f'ID{cid}')}"]
        ind_mat[csrc_id_mat == cid] = tid

    for c6, g in sw_m.groupby("c6", sort=False):
        s_i = stk_map.get(c6)
        if s_i is None:
            continue
        in_dts = g["in_dt"].tolist()
        l3s = g["三级行业名称"].tolist()
        for k, (idt, l3nm) in enumerate(zip(in_dts, l3s)):
            d_start = int(np.searchsorted(cal_arr, idt, side="left"))
            d_end = int(np.searchsorted(cal_arr, in_dts[k + 1], side="left")) if (k + 1 < len(in_dts)) else N_D
            if d_start < d_end and d_start < N_D:
                ind_mat[d_start:min(N_D, d_end), s_i] = name_to_id[f"SW3:{l3nm}"]

    l3_to_l1 = sw_c.dropna(subset=["三级行业名称"]).drop_duplicates("三级行业名称").set_index("三级行业名称")["一级行业名称"].to_dict()
    return ind_mat, theme_names, {"l3_to_l1": l3_to_l1}


def parse_kpl_events(cal_dts: list[str], stocks: list[str], end_dt: str) -> tuple[pd.DataFrame, list[str]]:
    dt_map = {d: i for i, d in enumerate(cal_dts)}
    stk_map = {c: i for i, c in enumerate(stocks)}
    seen_plates: set[str] = set()
    rows = []

    kpl_path = f"{cm.DATA_DIR}/kpl_plates_2018_2026_merged.jsonl"
    with open(kpl_path, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            o = json.loads(ln)
            dt = str(o.get("date", ""))[:10]
            if dt < cal_dts[0] or dt > end_dt:
                continue
            di = dt_map.get(dt)
            if di is None:
                continue

            day_direct_pairs: set[tuple[int, str]] = set()
            day_sub_pairs: set[tuple[int, str]] = set()
            for pl in o.get("plates", []):
                raw_p = str(pl.get("plate", "")).split("(")[0].strip()
                parts_p = [x.strip() for x in re.split(r"[,，/]", raw_p) if x.strip()]
                valid_p = [p for p in parts_p if p not in NON_THEME and len(p) >= 2]
                for p in valid_p:
                    seen_plates.add(p)
                for st in pl.get("stocks", []):
                    c6 = str(st[0]).zfill(6) if isinstance(st, list) else str(st.get("code", "")).zfill(6)
                    si = stk_map.get(c6)
                    if si is None:
                        continue
                    for p in valid_p:
                        day_direct_pairs.add((si, p))
                    if isinstance(st, list):
                        for seg_idx in (2, 3):
                            if len(st) > seg_idx and st[seg_idx]:
                                for tok in re.split(r"[+()（）,，/]", str(st[seg_idx])):
                                    tok = tok.strip()
                                    if tok and tok not in NON_THEME and tok in seen_plates:
                                        day_sub_pairs.add((si, tok))

            for si, p in day_direct_pairs:
                rows.append((di, si, p, 1))
            for si, p in day_sub_pairs:
                if (si, p) not in day_direct_pairs:
                    rows.append((di, si, p, 0))

    df = pd.DataFrame(rows, columns=["di", "si", "plate", "is_direct"])
    plate_names = sorted(df["plate"].unique().tolist()) if not df.empty else []
    p_map = {p: i for i, p in enumerate(plate_names)}
    if not df.empty:
        df["pid"] = df["plate"].map(p_map).astype(np.int16)
        df["di"] = df["di"].astype(np.int16)
        df["si"] = df["si"].astype(np.int16)
        df["is_direct"] = df["is_direct"].astype(np.int8)
        df = df[["di", "si", "pid", "is_direct"]].sort_values(["di", "pid", "si"]).reset_index(drop=True)
    return df, plate_names


def build_cache(end_dt: str = "2026-11-25", tag: str = "full") -> str:
    t0 = time.time()
    os.makedirs(cm.CACHE_DIR, exist_ok=True)
    pq_path = f"{cm.BASE_DIR}/stock_day_core_features_pit.parquet"

    def _read_col(col: str):
        tbl = pq.read_table(pq_path, columns=[col], filters=[("dt", "<=", end_dt)])
        arr = tbl.column(0).to_pandas()
        del tbl
        return arr

    s_dt = _read_col("dt")
    dt_strs = s_dt.astype(str).str[:10]
    cal_dts = sorted(dt_strs.unique().tolist())
    dt_arr = np.array(cal_dts)
    di = np.searchsorted(dt_arr, dt_strs.to_numpy()).astype(np.int32)
    del s_dt, dt_strs

    s_c6 = _read_col("c6")
    c6_strs = s_c6.astype(str).str.zfill(6)
    stocks = sorted(c6_strs.unique().tolist())
    stk_arr = np.array(stocks)
    si = np.searchsorted(stk_arr, c6_strs.to_numpy()).astype(np.int32)
    del s_c6, c6_strs
    gc.collect()
    pa.default_memory_pool().release_unused()

    N_D, N_S = len(cal_dts), len(stocks)

    def _mat(col: str, dtype=np.float32, fill=np.nan) -> np.ndarray:
        vals = _read_col(col).to_numpy(dtype=dtype, copy=False)
        m = np.full((N_D, N_S), fill, dtype=dtype)
        m[di, si] = vals
        del vals
        pa.default_memory_pool().release_unused()
        return m

    open_raw = _mat("open", np.float32, np.nan)
    close_raw = _mat("close", np.float32, np.nan)
    adj_f = _mat("adj_factor", np.float32, np.nan)
    amount_yi = np.nan_to_num(_mat("amount_yi", np.float32, 0.0), nan=0.0)
    valid_px = (open_raw > 0) & (close_raw > 0) & (amount_yi > 0) & np.isfinite(adj_f)
    adj_close = np.where(valid_px, close_raw * adj_f, np.nan).astype(np.float32)
    adj_open = np.where(valid_px, open_raw * adj_f, np.nan).astype(np.float32)
    del open_raw, close_raw, adj_f
    gc.collect()

    ret_1d = (_mat("ret_1d", np.float32, np.nan) / 100.0).astype(np.float32)
    open_pct = (_mat("open_pct", np.float32, np.nan) / 100.0).astype(np.float32)
    mcap_yi_t1 = _mat("mcap_yi_t1", np.float32, np.nan)
    list_age = _mat("list_age", np.int16, -1)
    is_st = _mat("is_st_pit", np.int8, 0) == 1
    is_20cm = _mat("is_20cm", np.int8, 0) == 1
    is_zt = _mat("is_zt", np.int8, 0) == 1
    is_yizi_zt = _mat("is_yizi_zt", np.int8, 0) == 1
    is_dt = _mat("is_dt", np.int8, 0) == 1
    is_yizi_dt = _mat("is_yizi_dt", np.int8, 0) == 1
    is_broken_zt = _mat("is_broken_zt", np.int8, 0) == 1
    streak = _mat("streak", np.int8, 0)
    csrc_id_mat = _mat("csrc_ind_id", np.int16, -1)

    ch1 = np.nan_to_num(_mat("comm_posts_1y_pct", np.float32, 0.5), nan=0.5)
    ch2 = np.nan_to_num(_mat("xq_posts_1y_pct", np.float32, 0.5), nan=0.5)
    comm_heat = (0.5 * ch1 + 0.5 * ch2).astype(np.float32)
    del ch1, ch2, di, si
    gc.collect()

    def _roll_mean(arr: np.ndarray, w: int) -> np.ndarray:
        valid = np.isfinite(arr)
        vals = np.where(valid, arr, 0.0).astype(np.float64)
        cs_v = np.vstack([np.zeros((1, N_S), dtype=np.float64), np.cumsum(vals, axis=0)])
        cs_c = np.vstack([np.zeros((1, N_S), dtype=np.int32), np.cumsum(valid.astype(np.int32), axis=0)])
        del valid, vals
        out = np.full((N_D, N_S), np.nan, dtype=np.float32)
        for d in range(N_D):
            lo = max(0, d - w + 1)
            cnt = cs_c[d + 1] - cs_c[lo]
            ok = cnt >= max(1, min(w // 2, d + 1))
            out[d, ok] = ((cs_v[d + 1, ok] - cs_v[lo, ok]) / cnt[ok]).astype(np.float32)
        return out

    amt20 = _roll_mean(np.where(valid_px, amount_yi, np.nan).astype(np.float32), 20)
    gc.collect()

    out_px = f"{cm.CACHE_DIR}/panel_px_{tag}.npz"
    out_tech = f"{cm.CACHE_DIR}/panel_tech_{tag}.npz"
    out_meta = f"{cm.CACHE_DIR}/meta_{tag}.json"
    out_kpl = f"{cm.CACHE_DIR}/kpl_events_{tag}.parquet"

    np.savez(
        out_px,
        adj_close=adj_close, adj_open=adj_open,
        ret_1d=ret_1d, open_pct=open_pct,
        amount_yi=amount_yi, amt20=amt20, mcap_yi_t1=mcap_yi_t1, list_age=list_age,
        is_st=is_st, is_20cm=is_20cm, is_zt=is_zt, is_yizi_zt=is_yizi_zt,
        is_dt=is_dt, is_yizi_dt=is_yizi_dt, is_broken_zt=is_broken_zt,
        streak=streak, valid_px=valid_px, comm_heat=comm_heat,
    )
    del adj_open, ret_1d, open_pct, amount_yi, amt20, mcap_yi_t1, list_age
    del is_st, is_20cm, is_zt, is_yizi_zt, is_dt, is_yizi_dt, is_broken_zt, valid_px, comm_heat
    gc.collect()

    # Strictly causal forward-fill of adj_close for rolling indicators
    adj_close_ff = adj_close
    for d in range(1, N_D):
        miss = ~np.isfinite(adj_close_ff[d])
        adj_close_ff[d, miss] = adj_close_ff[d - 1, miss]

    ma5 = _roll_mean(adj_close_ff, 5)
    ma10 = _roll_mean(adj_close_ff, 10)
    ma20 = _roll_mean(adj_close_ff, 20)

    hi20 = np.full((N_D, N_S), np.nan, dtype=np.float32)
    for d in range(N_D):
        lo = max(0, d - 19)
        sl = adj_close_ff[lo:d + 1]
        has_v = np.any(np.isfinite(sl), axis=0)
        hi20[d, has_v] = np.nanmax(sl[:, has_v], axis=0)

    ret_3d = np.full((N_D, N_S), np.nan, dtype=np.float32)
    ret_5d = np.full((N_D, N_S), np.nan, dtype=np.float32)
    ret_20d = np.full((N_D, N_S), np.nan, dtype=np.float32)
    if N_D > 3:
        ret_3d[3:] = adj_close_ff[3:] / adj_close_ff[:-3] - 1.0
    if N_D > 5:
        ret_5d[5:] = adj_close_ff[5:] / adj_close_ff[:-5] - 1.0
    if N_D > 20:
        ret_20d[20:] = adj_close_ff[20:] / adj_close_ff[:-20] - 1.0
    del adj_close_ff
    gc.collect()

    max_stk_25d = np.zeros((N_D, N_S), dtype=np.int8)
    max_r20_25d = np.full((N_D, N_S), -1.0, dtype=np.float32)
    for d in range(N_D):
        lo = max(0, d - 24)
        hi = max(0, d - 2)
        if hi > lo:
            max_stk_25d[d] = np.max(streak[lo:hi], axis=0)
            r_sl = ret_20d[lo:hi]
            max_r20_25d[d] = np.nanmax(np.where(np.isfinite(r_sl), r_sl, -1.0), axis=0)
    del streak
    gc.collect()

    sw3_mat, sw3_names, sw3_meta = build_causal_sw3_matrix(cal_dts, stocks, csrc_id_mat, end_dt=end_dt)
    del csrc_id_mat
    gc.collect()

    kpl_df, kpl_names = parse_kpl_events(cal_dts, stocks, end_dt=end_dt)

    np.savez(
        out_tech,
        ma5=ma5, ma10=ma10, ma20=ma20, hi20=hi20,
        ret_3d=ret_3d, ret_5d=ret_5d, ret_20d=ret_20d,
        max_stk_25d=max_stk_25d, max_r20_25d=max_r20_25d,
        sw3_mat=sw3_mat,
    )
    del ma5, ma10, ma20, hi20, ret_3d, ret_5d, ret_20d, max_stk_25d, max_r20_25d, sw3_mat
    gc.collect()

    kpl_df.to_parquet(out_kpl, index=False)
    with open(out_meta, "w", encoding="utf-8") as f:
        json.dump(
            {
                "end_dt": end_dt,
                "cal_dts": cal_dts,
                "stocks": stocks,
                "sw3_names": sw3_names,
                "kpl_names": kpl_names,
                "l3_to_l1": sw3_meta["l3_to_l1"],
            },
            f,
            ensure_ascii=False,
        )

    print(f"[Step0 {tag} DONE in {time.time()-t0:.1f}s | RSS={cm.rss_mb()}MB] N_D={N_D}, N_S={N_S}, SW3={len(sw3_names)}, KPL={len(kpl_names)}, kpl_rows={len(kpl_df)}")
    return out_px


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--end-dt", default="2026-11-25")
    ap.add_argument("--tag", default="full")
    args = ap.parse_args()
    build_cache(end_dt=args.end_dt, tag=args.tag)

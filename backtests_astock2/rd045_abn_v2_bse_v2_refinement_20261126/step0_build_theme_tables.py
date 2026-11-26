#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""RD045 Step 0: Build causal CSRC industry & KPL concept plate daily tables (<=2026-11-25)."""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"
import gc, json, resource, sys, time
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

pa.set_cpu_count(1)
pa.set_io_thread_count(1)
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
BASE = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd045_abn_v2_bse_v2_refinement_20261126"
STOCK_DAY_PQ = f"{BASE}/stock_day_core_features_pit.parquet"
KPL_JSONL = f"{ROOT}/sim-portfolio/data/kpl_plates_2018_2026_merged.jsonl"


def build_csrc_ind_daily() -> pd.DataFrame:
    cols = ["dt", "c6", "csrc_ind_id", "is_zt", "streak", "amount_yi", "ret_1d", "is_st_pit"]
    chunks = []
    pf = pq.ParquetFile(STOCK_DAY_PQ)
    for b in pf.iter_batches(batch_size=131_072, columns=cols, use_threads=False):
        d = b.to_pandas()
        d["dt"] = d["dt"].astype(str).str[:10]
        d = d[d["is_st_pit"] == 0]
        if not d.empty:
            chunks.append(d[["dt", "csrc_ind_id", "is_zt", "streak", "amount_yi", "ret_1d"]])
    df = pd.concat(chunks, ignore_index=True)
    del chunks
    gc.collect()

    df["is_zt"] = pd.to_numeric(df["is_zt"], errors="coerce").fillna(0).astype(np.int32)
    df["streak"] = pd.to_numeric(df["streak"], errors="coerce").fillna(0).astype(np.int32)
    df["amount_yi"] = pd.to_numeric(df["amount_yi"], errors="coerce").fillna(0.0).astype(np.float64)
    df["ret_1d"] = pd.to_numeric(df["ret_1d"], errors="coerce").astype(np.float64)
    df["csrc_ind_id"] = pd.to_numeric(df["csrc_ind_id"], errors="coerce").fillna(-1).astype(np.int32)

    mkt = df.groupby("dt", as_index=False).agg(
        mkt_zt_cnt=("is_zt", "sum"),
        mkt_amt_yi=("amount_yi", "sum"),
        mkt_max_streak=("streak", "max"),
    )
    ind = df.groupby(["dt", "csrc_ind_id"], as_index=False).agg(
        ind_zt_cnt=("is_zt", "sum"),
        ind_max_streak=("streak", "max"),
        ind_amt_yi=("amount_yi", "sum"),
        ind_ret_mean=("ret_1d", "mean"),
        ind_n=("is_zt", "count"),
    )
    del df
    gc.collect()
    ind = ind.merge(mkt, on="dt", how="left").sort_values(["csrc_ind_id", "dt"]).reset_index(drop=True)
    ind["ind_zt_3d"] = ind.groupby("csrc_ind_id")["ind_zt_cnt"].transform(lambda s: s.rolling(3, min_periods=1).sum())
    ind["ind_amt_share_pct"] = ind["ind_amt_yi"] / ind["mkt_amt_yi"].clip(lower=1.0) * 100.0
    ind["ind_zt_share_pct"] = ind["ind_zt_cnt"] / ind["mkt_zt_cnt"].clip(lower=1.0) * 100.0
    ind.to_parquet(f"{OUT_DIR}/csrc_ind_daily.parquet", index=False)
    return ind


def build_kpl_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    plate_rows, stock_rows = [], []
    with open(KPL_JSONL, encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            o = json.loads(ln)
            dt = str(o.get("date", ""))[:10]
            if dt < "2020-12-01" or dt > "2026-11-25":
                continue
            p_cnts = {}
            day_pairs = set()
            for pl in o.get("plates", []):
                raw_p = str(pl.get("plate", "")).strip()
                base_p = raw_p.split("(")[0].strip()
                if not base_p or base_p in ("其他", "ST板块"):
                    continue
                sts = pl.get("stocks", [])
                p_cnts[base_p] = p_cnts.get(base_p, 0) + len(sts)
                for st in sts:
                    c6 = str(st[0])[:6].zfill(6) if isinstance(st, list) else str(st.get("code", ""))[:6].zfill(6)
                    day_pairs.add((dt, c6, base_p))
            tot_day = max(1, sum(p_cnts.values()))
            srt_p = sorted(p_cnts.items(), key=lambda x: (-x[1], x[0]))
            for rk, (bp, cnt) in enumerate(srt_p, start=1):
                plate_rows.append({"dt": dt, "base_plate": bp, "kp_cnt": cnt, "kp_share_pct": round(cnt / tot_day * 100.0, 3), "kp_rank": rk})
            for d_i, c_i, b_i in day_pairs:
                stock_rows.append({"dt": d_i, "c6": c_i, "base_plate": b_i})

    kp_df = pd.DataFrame(plate_rows).sort_values(["base_plate", "dt"]).reset_index(drop=True)
    # Use market calendar spacing: rolling 3 active observations or calendar-aligned 3d?
    # Better: map dt -> mkt_idx and sum over [t-2..t] market days!
    all_dts = sorted(kp_df["dt"].unique())
    dt_pos = {d: i for i, d in enumerate(all_dts)}
    kp_df["mi"] = kp_df["dt"].map(dt_pos)
    kp_3d = {}
    for bp, g in kp_df.groupby("base_plate", sort=False):
        mis = g["mi"].to_numpy()
        cnts = g["kp_cnt"].to_numpy()
        for idx in range(len(mis)):
            lo = mis[idx] - 2
            s3 = int(sum(cnts[j] for j in range(max(0, idx - 5), idx + 1) if mis[j] >= lo))
            kp_3d[(bp, int(mis[idx]))] = s3
    kp_df["kp_3d_cnt"] = [kp_3d[(r.base_plate, int(r.mi))] for r in kp_df.itertuples(index=False)]
    kp_df = kp_df.drop(columns=["mi"]).sort_values(["dt", "kp_rank"]).reset_index(drop=True)
    sp_df = pd.DataFrame(stock_rows).sort_values(["dt", "c6", "base_plate"]).reset_index(drop=True)

    kp_df.to_parquet(f"{OUT_DIR}/kpl_plate_daily.parquet", index=False)
    sp_df.to_parquet(f"{OUT_DIR}/kpl_stock_plates.parquet", index=False)
    return kp_df, sp_df


def main():
    t0 = time.time()
    ind = build_csrc_ind_daily()
    kp, sp = build_kpl_tables()
    rss = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)
    print(f"[Step0 DONE {time.time()-t0:.1f}s | RSS={rss}MB] ind_rows={len(ind)}, kpl_plate_rows={len(kp)}, kpl_stock_rows={len(sp)}")


if __name__ == "__main__":
    main()

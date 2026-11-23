#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Build strictly red-team clean, untruncated candidate pools for:
  1. 二进三 V2.1 (base_score >= 65, canonical 5Y 2021-11-16 ~ 2026-11-16)
  2. 超跌撬板 V2.1 (base_score >= 120, 2022-01-21 ~ 2026-11-16)
Aligned strictly with T-1 market water factors from astock_mkt_water_chart.py.
Zero yfinance (D12), read-only external data, outputs only inside part2_2to3_pry/.
"""
import os
import sys
import json
import pickle
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation: yfinance forbidden!"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
OUT_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part2_2to3_pry"
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, f"{SIM}/scripts")
import astock_mkt_water_chart as mwc

sys.path.insert(0, f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit")
import exit_engine as ee23

sys.path.insert(0, f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s3_pry_exit")
sys.path.insert(0, f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry")
import run_exit_scan as pry_base
import backtest_30_factors as pry_bt
from run_f3_audit_part1 import make_xf30_spec

sys.path.insert(0, f"{SIM}/backtests_astock/redteam_full_audit_20261123/partB2_ledger_stress_audit")
import run_ledger_stress_audit as rta


def half_up_round2(x: pd.Series | np.ndarray) -> np.ndarray:
    return np.floor(np.asarray(x, dtype=float) * 100.0 + 0.5 + 1e-9) / 100.0


def build_water_t1_table() -> pd.DataFrame:
    """Compute exact daily market water from astock_mkt_water_chart and strictly shift(1) for T-1."""
    mkt = mwc.compute_daily_water().sort_index()
    zb = mkt["zb_rate"].to_numpy(dtype=float)
    d3 = mkt["dt_3d"].fillna(0.0).to_numpy(dtype=float)
    p3 = mkt["prem_3d"].fillna(1.5).to_numpy(dtype=float)
    mbd = mkt["max_b_drop5"].fillna(0.0).to_numpy(dtype=float)

    s_zb = np.where((zb >= 25) & (zb <= 40), 70 + 30 * (1 - np.abs(zb - 32.5) / 7.5),
           np.where(zb > 40, np.clip(70 * (1 - (zb - 40) / 20.0), 0, 70),
                    np.clip(70 * (1 - (25 - zb) / 15.0), 0, 70)))
    s_dt = np.clip(d3 / 60.0 * 100.0, 0, 100)
    s_p3 = np.where(p3 <= 1.0, np.clip(70 + np.maximum(0, 1.0 - p3) / 2.0 * 30.0, 70, 100),
           np.where(p3 <= 3.0, 70 - (p3 - 1.0) / 2.0 * 40.0,
                    np.clip(30 * (1 - (p3 - 3.0) / 2.0), 0, 30)))
    s_mb = np.clip(25.0 + mbd * 25.0, 0, 100)

    # Check exact match to v2_idx
    v2_chk = 0.25 * (s_zb + s_dt + s_p3 + s_mb)
    assert float(np.max(np.abs(v2_chk - mkt["v2_idx"].to_numpy()))) < 1e-9

    wt = pd.DataFrame({
        "sig_date_water": mkt.index,
        "zb_rate": zb,
        "max_b_drop5": mbd,
        "dt_3d": d3,
        "prem_3d": p3,
        "v2_idx": mkt["v2_idx"].to_numpy(dtype=float),
        "s_zb": s_zb,
        "s_mb": s_mb,
        "s_dt": s_dt,
        "s_p3": s_p3,
    }, index=mkt.index)

    out = pd.DataFrame(index=mkt.index)
    out["water_ref_date"] = wt["sig_date_water"].shift(1)
    for col in ["zb_rate", "max_b_drop5", "dt_3d", "prem_3d", "v2_idx", "s_zb", "s_mb", "s_dt", "s_p3"]:
        out[f"{col}_t1"] = wt[col].shift(1)
    out["buy_date"] = out.index
    return out.reset_index(drop=True)


def load_ground_truth_daily():
    cols = ["date", "ticker", "open", "high", "low", "close", "volume", "adj_close", "qfq_factor"]
    da = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", columns=cols, filters=[("date", ">=", pd.Timestamp("2020-12-01"))])
    dd = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols, filters=[("date", ">=", pd.Timestamp("2020-12-01"))])
    df_d = pd.concat([da, dd], ignore_index=True)
    df_d["c6"] = df_d["ticker"].str[:6]
    df_d = df_d[df_d["c6"].str.startswith(("00", "60")) & (~df_d["ticker"].str.endswith(".BJ"))].copy()
    df_d["dt"] = df_d["date"].dt.strftime("%Y-%m-%d")
    df_d.sort_values(["c6", "dt"], inplace=True)
    df_d.drop_duplicates(["c6", "dt"], keep="first", inplace=True)
    df_d.reset_index(drop=True, inplace=True)

    df_d["adjf"] = np.where((df_d["close"] > 0) & df_d["adj_close"].notna() & (df_d["adj_close"] > 0), df_d["adj_close"] / df_d["close"], 1.0)
    g = df_d.groupby("c6")
    df_d["prev_c_adj"] = g["close"].shift(1) * g["adjf"].shift(1) / df_d["adjf"]
    df_d["pre_c"] = df_d["prev_c_adj"]
    df_d["zt_px"] = half_up_round2(df_d["prev_c_adj"] * 1.10)
    df_d["dt_px"] = half_up_round2(df_d["prev_c_adj"] * 0.90)
    df_d["pct"] = df_d["close"] / df_d["pre_c"] - 1.0
    df_d["is_zt"] = (df_d["pre_c"] > 0) & (df_d["close"] >= df_d["zt_px"] - 0.011) & (df_d["pct"] >= 0.095)
    df_d["touch_zt"] = (df_d["pre_c"] > 0) & (df_d["high"] >= df_d["zt_px"] - 0.011)
    df_d["is_dt_exact"] = (df_d["pre_c"] > 0) & (df_d["close"] <= df_d["dt_px"] + 0.005)
    df_d["is_yizi"] = df_d["is_zt"] & (df_d["open"] >= df_d["zt_px"] - 0.011) & (df_d["low"] >= df_d["zt_px"] - 0.011)
    df_d["is_yizi_dt"] = df_d["is_dt_exact"] & (df_d["open"] <= df_d["dt_px"] + 0.005) & (df_d["high"] <= df_d["dt_px"] + 0.005)
    s_zt = df_d["is_zt"].astype(int)
    s_sh = g["is_zt"].shift(1).fillna(False).infer_objects(copy=False).astype(bool)
    df_d["streak"] = s_zt.groupby([df_d["c6"], (s_zt != s_sh).cumsum()]).cumsum() * s_zt
    df_d["is_2b_plus"] = df_d["streak"] >= 2
    return df_d


def build_2to3_pool(df_d: pd.DataFrame, dmap: dict, water_t1: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    c23 = pickle.load(open(f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_2to3_pit_20261116.pkl", "rb"))
    supp5m = pickle.load(open(f"{SIM}/backtests_astock/_archive/20261118_wave1_static_exit_opt/s2_2to3_exit/_cache_5m_supplement_bs.pkl", "rb"))
    b5m = {**c23["b5m_need"], **supp5m["supp_5m"]}
    idx_cache = json.load(open(f"{SIM}/backtests_astock/sandbox_lab/index_klines_5y_cache.json"))

    g23 = c23["gated_all"]
    sub = g23[(g23["score_v2"] >= 65) & (g23["buy_date"] >= "2021-11-16")].copy().reset_index(drop=True)
    codes = set(sub["code"].astype(str).str.zfill(6))
    da_need = df_d[df_d["c6"].isin(codes)].copy()
    plook, stkh = ee23.build_lookups(da_need)

    all_dts = sorted(df_d["dt"].unique())
    dt_idx = {d: i for i, d in enumerate(all_dts)}
    cfg_opt = ee23.ExitConfig("opt", c_start_hhmm=1345, c_peak_th=0.085, c_drop_th=0.065)
    rets_s, eds_s, ehs_s, _ = ee23.sim_exit_all(
        sub, plook, stkh, b5m, all_dts, dt_idx, idx_cache["sh000002"], idx_cache["sz399107"], cfg_opt, strict_assert=True
    )

    sub["code"] = sub["code"].astype(str).str.zfill(6)
    sub["buy_date"] = sub["buy_date"].astype(str).str[:10]
    sub["buy_hhmm"] = 925
    sub["buy_price"] = np.round(sub["prev_close"].astype(float) * (1.0 + sub["open_pct"].astype(float)), 2)

    adj_rets, adj_ep = [], []
    for i, r in sub.iterrows():
        c6, bd, ed, bp = r["code"], r["buy_date"], str(eds_s[i]), float(r["buy_price"])
        nr = float(rets_s[i])
        bb, eb = dmap.get((c6, bd)), dmap.get((c6, ed))
        if bb and eb and eb.qfq_factor > 0:
            nr = (1.0 + nr) * (bb.qfq_factor / eb.qfq_factor) - 1.0
            ep = round(bp * (1.0 + nr) / 0.9980 * (eb.qfq_factor / bb.qfq_factor), 2)
        else:
            ep = round(bp * (1.0 + nr) / 0.9980, 2)
        adj_rets.append(nr)
        adj_ep.append(ep)

    sub["exit_date"] = eds_s
    sub["exit_hhmm"] = ehs_s
    sub["exit_price"] = adj_ep
    sub["net_ret"] = adj_rets
    sub["base_score"] = sub["score_v2"].astype(int)

    keep_cols = [
        "buy_date", "buy_hhmm", "exit_date", "exit_hhmm", "code", "name",
        "base_score", "buy_price", "exit_price", "net_ret",
        "open_pct", "plate_sz", "sealed_3b", "plate", "prev_close",
        "buyable_open", "prev_is_yizi", "sig_date",
    ]
    pool = sub[keep_cols].merge(water_t1, on="buy_date", how="left")
    assert pool["v2_idx_t1"].notna().all(), "Missing T-1 water in 2to3!"
    assert (pool["water_ref_date"] < pool["buy_date"]).all(), "Lookahead water date in 2to3!"

    # Red-team audit across entire pool
    bar_map = {
        (r.c6, r.dt): {
            "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close),
            "adj_close": float(r.adj_close), "qfq_factor": float(r.qfq_factor),
            "prev_close": float(r.prev_c_adj) if pd.notna(r.prev_c_adj) else np.nan, "prev_qfq": np.nan,
        }
        for r in da_need.itertuples(index=False)
    }
    aud = rta.audit_physical_integrity("2to3_full65", pool, bar_map)
    dt_exact_1500 = sum(1 for r in pool.itertuples(index=False) if int(r.exit_hhmm) >= 1455 and bool(dmap[(r.code, r.exit_date)].is_dt_exact))
    assert aud["t0_violations"] == 0 and aud["yizi_zt_buy_count"] == 0 and aud["yizi_dt_exit_count"] == 0
    assert aud["buy_oob_count"] == 0 and aud["exit_oob_count"] == 0 and aud["ret_mismatch_gt50bps_count"] == 0
    assert dt_exact_1500 == 0, f"2to3 dt_exact_1500={dt_exact_1500}"

    # Verify exact single-slot alignment vs ledger_v21_opt_std90.csv
    led = ee23.sim_single_slot(pool[pool["base_score"] >= 90], "base_score", "net_ret", "exit_date", "exit_hhmm")
    bench = pd.read_csv(f"{SIM}/backtests_astock/exit_factors_v2_20261118/f2_2to3/ledger_v21_opt_std90.csv")
    bench["code"] = bench["code"].astype(str).str.zfill(6)
    assert len(led) == len(bench) == 95
    assert (led["code"] == bench["code"]).all() and (led["buy_date"] == bench["buy_date"]).all()
    assert (led["exit_date"] == bench["exit_date"]).all()
    max_diff = float(np.max(np.abs(led["net_ret"].to_numpy() - bench["net_ret"].to_numpy())))
    nav_led = float(np.prod(1.0 + led["net_ret"]))
    nav_bench = float(np.prod(1.0 + bench["net_ret"]))
    assert max_diff < 1e-7, f"2to3 max_diff={max_diff}"

    return pool, {
        "pool_rows": int(len(pool)),
        "pool_days": int(pool["buy_date"].nunique()),
        "bench_trades": int(len(led)),
        "bench_nav": round(nav_led, 4),
        "ref_nav": round(nav_bench, 4),
        "max_ret_diff": max_diff,
        "dt_exact_1500": dt_exact_1500,
    }


def _patch_cb_dt_px(cb: dict, df_d: pd.DataFrame) -> None:
    """Align dt_px in cb to exact half-up rounding so 15:00 exact limit-downs are caught."""
    by_c6 = {c6: dict(zip(grp["dt"], grp["dt_px"])) for c6, grp in df_d.groupby("c6")}
    for c6, d in cb.items():
        m = by_c6.get(c6)
        if not m:
            continue
        for i, dt_s in enumerate(d["dts"]):
            if dt_s in m and pd.notna(m[dt_s]):
                d["dt_px"][i] = float(m[dt_s])


def build_pry_pool(df_d: pd.DataFrame, dmap: dict, water_t1: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    f3_dir = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f3_pry"
    fp = pickle.load(open(f"{f3_dir}/_cache_feats_830.pkl", "rb"))
    cb = pickle.load(open(f"{SIM}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/code_bars_5y.pkl", "rb"))["code_bars"]
    _patch_cb_dt_px(cb, df_d)

    sub, feats = fp["sub"], fp["feats"]
    spec = make_xf30_spec(5, 0.70, 10, 0.03, True)
    rp, edp, hdp, ehp, rsnp = pry_bt.run_spec(sub, cb, feats, spec)

    rows = []
    deferred_1500 = []
    for i, row in enumerate(sub.itertuples(index=False)):
        c6 = str(row.code).zfill(6)
        bd = str(row.buy_date)
        ed = str(edp[i])
        eh = int(ehp[i])
        hd = int(hdp[i])
        nr = float(rp[i])
        rsn = str(rsnp[i])

        d = cb[row.c6]
        p0 = int(row.p0)
        bpx = float(row.buy_px)
        pe = d["date_to_pos"].get(ed)

        # Red-team physical fix: if selling at 14:55/15:00 on exact locked limit-down, defer to next sellable 09:25 open
        eb_gt = dmap.get((c6, ed))
        if eh >= 1455 and eb_gt is not None and bool(eb_gt.is_dt_exact) and pe is not None and pe + 1 < len(d["dts"]):
            ps = pry_base.first_sellable_day(d, pe + 1)
            s_px = float(d["open"][ps]) if float(d["open"][ps]) > float(d["dt_px"][ps]) + 0.005 else float(d["close"][ps])
            nr_new, ed_new, hd_new = pry_base.ret_from_px(d, p0, ps, s_px, bpx)
            deferred_1500.append((c6, bd, ed, eh, round(nr * 100, 2), ed_new, 925, round(nr_new * 100, 2)))
            nr, ed, hd, eh, rsn = nr_new, ed_new, hd_new, 925, f"{rsn}|1500跌停顺延"
            pe = ps

        af = float(d["adjf"][pe] / d["adjf"][p0]) if pe is not None else 1.0
        epx = (nr + 1.0) / 0.9980 * bpx / af if not np.isnan(nr) else np.nan
        rows.append({
            "buy_date": bd,
            "buy_hhmm": 925,
            "exit_date": ed,
            "exit_hhmm": eh,
            "code": c6,
            "name": str(row.name),
            "base_score": int(row.score),
            "buy_price": round(bpx, 2),
            "exit_price": round(epx, 2),
            "net_ret": float(nr),
            "bias10": float(row.bias10),
            "hold_days": hd,
            "exit_reason": rsn,
            "sig_date": str(row.sig_date),
        })

    pool_all = pd.DataFrame(rows)
    pool = pool_all[pool_all["base_score"] >= 120].copy().reset_index(drop=True)
    pool = pool.merge(water_t1, on="buy_date", how="left")
    assert pool["v2_idx_t1"].notna().all(), "Missing T-1 water in Pry!"
    assert (pool["water_ref_date"] < pool["buy_date"]).all(), "Lookahead water date in Pry!"

    codes = set(pool["code"])
    da_need = df_d[df_d["c6"].isin(codes)]
    bar_map = {
        (r.c6, r.dt): {
            "open": float(r.open), "high": float(r.high), "low": float(r.low), "close": float(r.close),
            "adj_close": float(r.adj_close), "qfq_factor": float(r.qfq_factor),
            "prev_close": float(r.prev_c_adj) if pd.notna(r.prev_c_adj) else np.nan, "prev_qfq": np.nan,
        }
        for r in da_need.itertuples(index=False)
    }
    aud = rta.audit_physical_integrity("pry_full120", pool, bar_map)
    dt_exact_1500 = sum(1 for r in pool.itertuples(index=False) if int(r.exit_hhmm) >= 1455 and bool(dmap[(r.code, r.exit_date)].is_dt_exact))
    assert aud["t0_violations"] == 0 and aud["yizi_zt_buy_count"] == 0 and aud["yizi_dt_exit_count"] == 0
    assert aud["buy_oob_count"] == 0 and aud["exit_oob_count"] == 0 and aud["ret_mismatch_gt50bps_count"] == 0
    assert dt_exact_1500 == 0, f"Pry dt_exact_1500={dt_exact_1500}"

    # Verify exact single-slot alignment vs ledger_pry_v21_ss165_clean.csv
    p165 = pool[pool["base_score"] >= 165].sort_values(["buy_date", "base_score", "bias10", "code"], ascending=[True, False, True, True])
    ss_rows, fa = [], ""
    for r in p165.itertuples(index=False):
        if fa == "" or r.buy_date > fa:
            ss_rows.append(r._asdict())
            fa = r.exit_date
    led = pd.DataFrame(ss_rows)
    bench = pd.read_csv(f"{SIM}/backtests_astock/redteam_full_audit_20261123/partC_clean_ledgers_v191/ledger_pry_v21_ss165_clean.csv")
    bench["code"] = bench["code"].astype(str).str.zfill(6)
    assert len(led) == len(bench) == 16
    assert (led["code"] == bench["code"]).all() and (led["buy_date"] == bench["buy_date"]).all()
    assert (led["exit_date"] == bench["exit_date"]).all()
    max_diff = float(np.max(np.abs(led["net_ret"].to_numpy() - bench["net_ret"].to_numpy())))
    nav_led = float(np.prod(1.0 + led["net_ret"]))
    nav_bench = float(np.prod(1.0 + bench["net_ret"]))
    assert max_diff < 1e-7, f"Pry max_diff={max_diff}"

    return pool, {
        "pool_rows": int(len(pool)),
        "pool_days": int(pool["buy_date"].nunique()),
        "deferred_1500_fixes": deferred_1500,
        "bench_trades": int(len(led)),
        "bench_nav": round(nav_led, 4),
        "ref_nav": round(nav_bench, 4),
        "max_ret_diff": max_diff,
        "dt_exact_1500": dt_exact_1500,
    }


def main():
    water_t1 = build_water_t1_table()
    df_d = load_ground_truth_daily()
    dmap = {(r.c6, r.dt): r for r in df_d.itertuples(index=False)}

    pool_2to3, info_2to3 = build_2to3_pool(df_d, dmap, water_t1)
    pool_pry, info_pry = build_pry_pool(df_d, dmap, water_t1)

    pool_2to3.to_csv(f"{OUT_DIR}/pool_2to3_full_clean.csv", index=False, encoding="utf-8-sig")
    pool_pry.to_csv(f"{OUT_DIR}/pool_pry_full_clean.csv", index=False, encoding="utf-8-sig")
    water_t1.to_csv(f"{OUT_DIR}/water_t1_daily.csv", index=False, encoding="utf-8-sig")

    print("2TO3_CLEAN_POOL:", json.dumps(info_2to3, ensure_ascii=False))
    print("PRY_CLEAN_POOL:", json.dumps(info_pry, ensure_ascii=False))


if __name__ == "__main__":
    main()

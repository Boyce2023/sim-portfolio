#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
build_clean_pools.py
构建三进四 V4.1（base_score >= 65）与高标首阴 V5.1（base_score >= 60）全量洁净候选池，
严格挂载 T-1 市场水温因子并执行红队物理洁净校验与基准核对。
"""
import os
import sys
import json
import pickle
import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance forbidden"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WORK_DIR = f"{SIM}/backtests_astock/mkt_water_scoring_audit_20261123/part1_3to4_high"
F1_DIR = f"{SIM}/backtests_astock/exit_factors_v2_20261118/f1_3to4"
UPG_DIR = f"{SIM}/backtests_astock/clean_3strategies_mutual_upgrade_20261117"
HD_DIR = f"{SIM}/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
GOLD_DIR = f"{SIM}/backtests_astock/sandbox_lab/golden_regime_20261113"
A2_ASSETS = f"{SIM}/backtests_astock2/assets"

for p in (F1_DIR, UPG_DIR, A2_ASSETS, f"{SIM}/scripts"):
    if p not in sys.path:
        sys.path.insert(0, p)

from astock_mkt_water_chart import compute_daily_water
from v191_dt_defer_helper import load_dt_defer_tables, defer_eod_limit_down, calc_adj_net_ret
import upgrade_3to4_pit as u34
import exit_factor_engine as efe
import step4_audit_trunc_and_report as s4


def build_t1_water_table() -> pd.DataFrame:
    mkt = compute_daily_water()
    zb = mkt["zb_rate"].values
    d3 = mkt["dt_3d"].fillna(0.0).values
    p3 = mkt["prem_3d"].fillna(1.5).values
    mbd = mkt["max_b_drop5"].fillna(0.0).values

    mkt["s_zb"] = np.where(
        (zb >= 25) & (zb <= 40),
        70.0 + 30.0 * (1.0 - np.abs(zb - 32.5) / 7.5),
        np.where(zb > 40, np.clip(70.0 * (1.0 - (zb - 40.0) / 20.0), 0.0, 70.0), np.clip(70.0 * (1.0 - (25.0 - zb) / 15.0), 0.0, 70.0)),
    )
    mkt["s_dt"] = np.clip(d3 / 60.0 * 100.0, 0.0, 100.0)
    mkt["s_p3"] = np.where(
        p3 <= 1.0,
        np.clip(70.0 + np.maximum(0.0, 1.0 - p3) / 2.0 * 30.0, 70.0, 100.0),
        np.where(p3 <= 3.0, 70.0 - (p3 - 1.0) / 2.0 * 40.0, np.clip(30.0 * (1.0 - (p3 - 3.0) / 2.0), 0.0, 30.0)),
    )
    mkt["s_mb"] = np.clip(25.0 + mbd * 25.0, 0.0, 100.0)
    assert np.max(np.abs(0.25 * (mkt["s_zb"] + mkt["s_dt"] + mkt["s_p3"] + mkt["s_mb"]) - mkt["v2_idx"])) < 1e-12

    mkt["t1_date"] = mkt.index.to_series().shift(1)
    raw_cols = ["zb_rate", "max_b_drop5", "dt_3d", "prem_3d", "v2_idx", "s_zb", "s_mb", "s_dt", "s_p3"]
    out = pd.DataFrame({"t1_date": mkt["t1_date"]}, index=mkt.index)
    for c in raw_cols:
        out[f"{c}_t1"] = mkt[c].shift(1)
    return out


def verify_physical_integrity(df: pd.DataFrame, dt_tables: dict, by_c: dict, is_high: bool = False) -> None:
    dmap = dt_tables["dmap"]
    cols = ["date", "ticker", "open", "high", "low", "close", "adj_close", "qfq_factor"]
    da = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_daily.parquet", columns=cols, filters=[("date", ">=", pd.Timestamp("2021-09-01"))])
    dd = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=cols, filters=[("date", ">=", pd.Timestamp("2021-09-01"))])
    df_all = pd.concat([da, dd], ignore_index=True)
    df_all["c6"] = df_all["ticker"].astype(str).str[:6]
    df_all["dt_s"] = df_all["date"].dt.strftime("%Y-%m-%d")
    df_all = df_all[df_all["c6"].isin(set(df["code"]))].sort_values(["c6", "dt_s"]).drop_duplicates(["c6", "dt_s"])
    df_all["prev_c"] = df_all.groupby("c6")["close"].shift(1) * df_all.groupby("c6")["adj_close"].shift(1) / df_all.groupby("c6")["close"].shift(1)
    bar_raw = {(r.c6, r.dt_s): r for r in df_all.itertuples(index=False)}

    assert (df["t1_date"] < df["buy_date"]).all(), "PIT lookahead breach in t1_date!"
    assert (df["exit_date"] > df["buy_date"]).all(), "T+0 violation!"

    for r in df.itertuples(index=False):
        c6 = str(r.code).zfill(6)
        bb = dmap[(c6, r.buy_date)]
        eb = dmap[(c6, r.exit_date)]
        br_b = bar_raw[(c6, r.buy_date)]
        br_e = bar_raw[(c6, r.exit_date)]

        zt_b = float(np.floor(bb.prev_c_adj * 1.10 * 100.0 + 0.5) / 100.0) if pd.notna(bb.prev_c_adj) else 99999.0
        assert not (br_b.open >= zt_b - 0.011 and br_b.low >= zt_b - 0.011), f"Yizi buy: {r}"
        assert r.buy_price < zt_b - 0.005, f"Buy at ZT price: {r}"
        assert br_b.low - 0.015 <= r.buy_price <= br_b.high + 0.015, f"Buy OOB: {r}"
        assert br_e.low - 0.015 <= r.exit_price <= br_e.high + 0.015, f"Exit OOB: {r}"
        assert not bool(eb.is_yizi_dt), f"Yizi DT exit: {r}"
        if int(r.exit_hhmm) >= 1455:
            assert not bool(eb.is_dt_exact), f"15:00 locked DT sell: {r}"
        exp_ret = (r.exit_price / r.buy_price) * (float(br_b.qfq_factor) / float(br_e.qfq_factor)) * 0.9980 - 1.0
        assert abs(exp_ret - r.net_ret) <= 0.005, f"Ex-div/ret mismatch {c6} {r.buy_date}: {exp_ret} vs {r.net_ret}"

        if is_high:
            is_b_zt = (br_b.close >= zt_b - 0.011) and (br_b.close / bb.prev_c_adj - 1.0 >= 0.095)
            if (not is_b_zt) and int(r.exit_hhmm) not in (925, 1500):
                gc = by_c[c6]
                p0 = int(gc.index[gc["dt_s"] == r.buy_date][0])
                pe = int(gc.index[gc["dt_s"] == r.exit_date][0])
                assert any(
                    (float(gc.loc[m, "close"]) >= float(np.floor(float(gc.loc[m, "prev_c_adj"]) * 1.10 * 100 + 0.5) / 100) - 0.011)
                    and (float(gc.loc[m, "close"]) / float(gc.loc[m, "prev_c_adj"]) - 1.0 >= 0.095)
                    for m in range(p0 + 1, pe)
                ), f"Misapplied 93% dev on non-sealed high dragon: {r}"


def build_3to4_pool(mkt_t1: pd.DataFrame, dt_tables: dict) -> pd.DataFrame:
    print("[1/2] Building 3to4 V4.1 clean full candidate pool (base_score >= 65)...")
    with open(f"{F1_DIR}/pit_exit_cache_full.pkl", "rb") as f:
        cache = pickle.load(f)
    states = efe.precompute_trade_day_states(cache, min_score=65.0)
    rfn_v41 = lambda st, ctx: {"tight_1345_thr": 0.070 if s4.risk7_score(st) >= 1 else 0.050}

    code_bars = cache["code_bars_ext"]
    cand_df = cache["cand_df"]
    rows = []
    for e in cache["buy_entries"]:
        if (not e["skel"]) or (e["buy_px"] is None) or (e["sc_v40"] < 65.0):
            continue
        bd = str(e["buy_date"])
        if bd > "2026-11-12":
            continue
        c6 = str(e["code"]).zfill(6)
        pos = e["pos"]
        cb = code_bars[c6]
        ex_dt, spx, adjs, hb, shh, rsn = efe.sim_exit_with_rule(e, cache, states.get(e["idx"], {}), rfn_v41)
        bpx_r = round(float(e["buy_px"]), 2)
        spx_r = round(float(spx), 2)
        nr = (float(spx) * float(adjs)) / (float(e["buy_px"]) * float(cb["adjf"][pos])) * (1.0 - efe.FEE_RATE) - 1.0

        ned, neh, nep, nret_def, dt_def = defer_eod_limit_down(c6, bd, bpx_r, ex_dt, shh, spx_r, nr, dt_tables, efe.FEE_RATE)
        final_ret = nret_def if dt_def else nr
        rows.append({
            "buy_date": bd,
            "buy_hhmm": int(e["buy_hhmm"]),
            "exit_date": ned,
            "exit_hhmm": int(neh),
            "code": c6,
            "name": str(e["name"]),
            "base_score": int(round(e["sc_v40"])),
            "buy_price": bpx_r,
            "exit_price": round(float(nep), 2),
            "net_ret": round(float(final_ret), 6),
            "prio_tie": float(cand_df["prio_3to4"].iloc[e["idx"]]),
            "open_pct": float(e["open_pct"]),
            "hold_bars": int(hb),
            "exit_reason": rsn,
            "dt_deferred": bool(dt_def),
        })

    df = pd.DataFrame(rows)
    for c in mkt_t1.columns:
        df[c] = df["buy_date"].map(mkt_t1[c])

    # Verify exact benchmark match vs ledger_3to4_xf30_std.csv (95 trades / 616.1818x)
    sub90 = df[df["base_score"] >= 90].copy()
    sub90["priority_score"] = sub90["base_score"] * 10.0 + sub90["prio_tie"] * 0.1
    slot90 = u34.sim_single_slot(sub90)
    off34 = pd.read_csv(f"{F1_DIR}/ledger_3to4_xf30_std.csv", dtype={"code": str})
    off34["code"] = off34["code"].str.zfill(6)
    assert len(slot90) == len(off34) == 95, f"Len mismatch: {len(slot90)}"
    assert list(zip(slot90["buy_date"], slot90["code"])) == list(zip(off34["buy_date"], off34["code"]))
    max_d = float(np.max(np.abs(slot90["net_ret"].to_numpy() - off34["net_ret"].to_numpy())))
    nav_calc = float(np.prod(1.0 + slot90["net_ret"].to_numpy()))
    nav_off = float(np.prod(1.0 + off34["net_ret"].to_numpy()))
    print(f"  [3to4 Benchmark Match] N={len(slot90)}, NAV={nav_calc:.4f}x vs off={nav_off:.4f}x, max_ret_diff={max_d:.2e}")
    assert max_d <= 1e-6 and abs(nav_calc - 616.1818) < 0.01

    return df.sort_values(["buy_date", "buy_hhmm", "base_score", "code"], ascending=[True, True, False, True]).reset_index(drop=True)


def build_high_pool(mkt_t1: pd.DataFrame, dt_tables: dict) -> pd.DataFrame:
    print("[2/2] Building High Dragon V5.1 clean full candidate pool (base_score >= 60)...")
    src = "\n".join(open(f"{GOLD_DIR}/sub2_03_golden_relaxation_backtest.py", encoding="utf-8").read().splitlines()[:192])
    src = src.replace('r["d1_to"] > 38.0', 'r["d1_to"] > 35.0')
    G = {"__name__": "eng"}
    exec(src, G)
    dfr, code_bars, SH_MAP, SZ_MAP, get_double_dev_px = G["dfr"], G["code_bars"], G["SH_MAP"], G["SZ_MAP"], G["get_double_dev_px"]

    df5 = pd.read_parquet(f"{SIM}/data/all_strategies_5m_complete_pit.parquet")
    df5["c6"] = df5["c6"].astype(str).str.zfill(6)
    df5.sort_values(["c6", "date", "hhmm_int"], inplace=True)
    pit_5m = {
        (c6, str(dt)): grp[["hhmm_int", "open", "high", "low", "close", "volume", "amount"]].to_numpy(dtype=float)
        for (c6, dt), grp in df5.groupby(["c6", "date"], sort=False)
    }
    sub2_5m = pickle.load(open(f"{HD_DIR}/sub2_5m_bars_cache.pkl", "rb"))
    idx_5m_sub2 = {(k[0], k[2]): v for k, v in sub2_5m.items()}

    def get_bars_5m(c6: str, dt: str):
        arr = pit_5m.get((c6, dt))
        if arr is not None and len(arr) > 0:
            return arr
        v = idx_5m_sub2.get((c6, dt))
        if isinstance(v, pd.DataFrame) and not v.empty:
            sub = v[v["date"] == dt]
            if not sub.empty:
                hh = sub["hhmm"].str.replace(":", "").astype(int).values
                return np.column_stack([hh, sub["open"].values, sub["high"].values, sub["low"].values, sub["close"].values, sub["volume"].values, sub["amount"].values])
        return None

    rows = []
    for r in dfr[dfr["sc5_1"] >= 60].itertuples():
        c6 = str(r.code).zfill(6)
        bd = str(r.buy_date)
        if bd > "2026-11-12":
            continue
        bars = code_bars[c6]
        d2p = bars["p"][bd]
        b_op = float(bars["open"][d2p])
        zt_px = float(bars["zt_px"][d2p])
        imap = SH_MAP if c6.startswith("60") else SZ_MAP
        arr_b = get_bars_5m(c6, bd)

        if r.op2 >= 0.0:
            if r.op2 > 0.045 or b_op >= zt_px - 0.011:
                continue
            b_hhmm, b_px, b_open_h = 925, b_op, True
        else:
            ipx = round(b_op * 1.015, 2)
            if ipx >= zt_px - 0.011 or arr_b is None or len(arr_b) == 0:
                continue
            hit_b = False
            for row in arr_b:
                if int(row[0]) > 1130:
                    break
                if row[2] >= ipx:
                    b_hhmm = int(row[0])
                    b_px = float(max(row[1], ipx))
                    hit_b = True
                    break
            if not hit_b:
                continue
            b_open_h = False

        n = len(bars["dts"])

        def run_zt_loop(start_p):
            imm = False
            for step in range(1, 8):
                p = start_p + step
                if p >= n:
                    break
                pl = get_double_dev_px(bars, p, imap, 0.07)
                if bars["open"][p] >= pl:
                    return p, float(bars["open"][p]), True
                if bars["high"][p] >= pl:
                    return p, float(pl), False
                if not bars["is_zt"][p]:
                    if (not imm) and (bars["close"][p] > bars["open"][p]):
                        imm = True
                        continue
                    while p < n - 1 and bars["is_yizi_dt"][p]:
                        p += 1
                    return p, float(bars["close"][p]), False
            p_end = min(start_p + 5, n - 1)
            return p_end, float(bars["close"][p_end]), False

        if bars["is_zt"][d2p]:
            ep, _, eo = run_zt_loop(d2p)
        else:
            p = min(d2p + 1, n - 1)
            while p < n - 1 and bars["is_yizi_dt"][p]:
                p += 1
            if bars["is_zt"][p]:
                ep, _, eo = run_zt_loop(p)
            else:
                ep, _, eo = p, float(bars["close"][p]), False

        e_dt = str(bars["dts"][ep])
        arr_e = get_bars_5m(c6, e_dt)
        sealed_b = bool(bars["is_zt"][d2p])
        chained_zt = (not sealed_b) and (ep > d2p + 1) and any(bool(bars["is_zt"][mid]) for mid in range(d2p + 1, ep))
        pl = get_double_dev_px(bars, ep, imap, 0.07) if (sealed_b or chained_zt) else 99999.0

        if eo:
            e_hhmm, e_px = 925, float(bars["open"][ep])
        else:
            hit_dev = False
            if pl < 99990.0 and arr_e is not None and len(arr_e) > 0:
                for row in arr_e:
                    if row[2] >= pl:
                        e_hhmm = int(row[0])
                        e_px = float(max(row[1], pl))
                        hit_dev = True
                        break
            if not hit_dev:
                if pl < 99990.0 and float(bars["high"][ep]) >= pl:
                    e_hhmm, e_px = 1030, float(pl)
                else:
                    e_hhmm, e_px = 1500, float(bars["close"][ep])

        adj_nr = calc_adj_net_ret(c6, bd, b_px, e_dt, e_px, dt_tables, 0.0020)
        nr = adj_nr if adj_nr is not None else ((e_px * bars["adjf"][ep]) / (b_px * bars["adjf"][d2p]) * 0.9980 - 1.0)
        ned, neh, nep, nret, dt_def = defer_eod_limit_down(c6, bd, b_px, e_dt, e_hhmm, e_px, nr, dt_tables, 0.0020)

        rows.append({
            "buy_date": bd,
            "buy_hhmm": int(b_hhmm),
            "exit_date": ned,
            "exit_hhmm": int(neh),
            "code": c6,
            "name": str(r.name),
            "base_score": int(r.sc5_1),
            "buy_price": round(b_px, 2),
            "exit_price": round(float(nep), 2),
            "net_ret": round(float(nret), 6),
            "b_open_h": bool(b_open_h),
            "eo": bool(neh == 925),
            "open_pct": float(r.op2),
            "hold_bars": int(max(1, ep - d2p)),
            "is_sealed_buy": sealed_b,
            "chained_zt": chained_zt,
            "dt_deferred": bool(dt_def),
        })

    df = pd.DataFrame(rows)
    for c in mkt_t1.columns:
        df[c] = df["buy_date"].map(mkt_t1[c])

    # Verify exact row-level match with ledger_base_high_v51.csv (42 trades / 14.7494x)
    off_h = pd.read_csv(f"{SIM}/backtests_astock/clean_rebacktest_20261116/partA_high_3to4/ledger_base_high_v51.csv", dtype={"code": str})
    off_h["code"] = off_h["code"].str.zfill(6)
    m = pd.merge(off_h, df, on=["buy_date", "code"], suffixes=("_off", "_pool"))
    assert len(m) == 42, f"Matched {len(m)} != 42"
    max_d = float(np.max(np.abs(m["net_ret_off"] - m["net_ret_pool"])))
    assert max_d == 0.0 and (m["buy_hhmm_off"] == m["buy_hhmm_pool"]).all() and (m["exit_hhmm_off"] == m["exit_hhmm_pool"]).all() and (m["exit_date_off"] == m["exit_date_pool"]).all()
    print(f"  [High V5.1 Match] 42/42 official clean rows exact match (max_ret_diff={max_d:.1e}, off_nav={np.prod(1+off_h['net_ret']):.4f}x)")

    return df.sort_values(["buy_date", "buy_hhmm", "base_score", "code"], ascending=[True, True, False, True]).reset_index(drop=True)


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    mkt_t1 = build_t1_water_table()
    dt_tables = load_dt_defer_tables()

    p34 = build_3to4_pool(mkt_t1, dt_tables)
    phigh = build_high_pool(mkt_t1, dt_tables)

    verify_physical_integrity(p34, dt_tables, dt_tables["by_c"], is_high=False)
    print(f"  [Red-Team Integrity 3to4] All {len(p34)} rows passed 100%!")
    verify_physical_integrity(phigh, dt_tables, dt_tables["by_c"], is_high=True)
    print(f"  [Red-Team Integrity High] All {len(phigh)} rows passed 100%!")

    p34.to_csv(f"{WORK_DIR}/pool_3to4_full_clean.csv", index=False, encoding="utf-8-sig")
    phigh.to_csv(f"{WORK_DIR}/pool_high_full_clean.csv", index=False, encoding="utf-8-sig")
    print(f"[SAVED] pool_3to4_full_clean.csv ({len(p34)} rows) & pool_high_full_clean.csv ({len(phigh)} rows)")


if __name__ == "__main__":
    main()

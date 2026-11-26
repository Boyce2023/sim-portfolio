#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Gate 1, Gate 2, Gate 4 forensics, slippage, liquidity & concentration checks."""
import json, sqlite3, sys
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
WAVE1 = f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"


def build_ref_context(ledgers: dict[str, pd.DataFrame]) -> dict:
    codes = set()
    for df in ledgers.values():
        if not df.empty:
            codes.update(df["code"].astype(str).str.zfill(6).unique())
    codes_l = sorted(codes)

    with open(f"{SIM}/data/st_universe.json") as f:
        st_static = set(str(x)[-6:] for x in json.load(f)["codes"])

    # Delisted codes set
    dl_df = pd.read_parquet(f"{SIM}/data/cn_hk_price_db/a_delisted_daily.parquet", columns=["ticker", "date"])
    dl_df["c6"] = dl_df["ticker"].astype(str).str[:6]
    dl_df["dt"] = pd.to_datetime(dl_df["date"]).dt.strftime("%Y-%m-%d")
    dl_last = dl_df.groupby("c6")["dt"].max().to_dict()
    del dl_df

    # Names from pools + sqlite DBs
    names = {}
    for st in ("1to2", "2to3", "3to4", "high", "pry", "20cm"):
        p = pd.read_parquet(f"{WAVE1}/pool_{st}_master_pit.parquet", columns=["code", "name"])
        for c, nm in zip(p["code"].astype(str).str.zfill(6), p["name"].astype(str)):
            if nm and nm != "nan":
                names[c] = nm
    for dbp, sql in [
        (f"{SIM}/data/zt_micro_tape_5y_pit.db", "SELECT DISTINCT sec_code, sec_name FROM zt_micro_tape"),
        (f"{SIM}/data/cninfo_notices_5y_pit.db", "SELECT DISTINCT sec_code, sec_name FROM notices"),
    ]:
        con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
        for c, nm in con.execute(sql):
            c6 = str(c).zfill(6)
            if c6 in codes and c6 not in names and nm:
                names[c6] = str(nm)
        con.close()

    # Dynamic ST / delisting notices for audited codes
    con_n = sqlite3.connect(f"file:{SIM}/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    tox_n = pd.read_sql_query(
        "SELECT sec_code, sec_name, substr(pub_datetime_cst,1,10) as dt, title FROM notices "
        "WHERE title LIKE '%ST%' OR title LIKE '%退市%' OR title LIKE '%终止上市%'",
        con_n,
    )
    con_n.close()
    tox_n["c6"] = tox_n["sec_code"].astype(str).str.zfill(6)
    tox_n = tox_n[tox_n["c6"].isin(codes)]
    dyn_st = {}
    for c6, grp in tox_n.groupby("c6"):
        dyn_st[c6] = str(grp["dt"].min())

    # Stream stock_day_core_features_pit ONLY for audited codes
    cols_sd = ["dt", "c6", "open", "close", "adj_factor", "open_pct", "ret_1d", "amount_yi", "amount_yi_t1", "is_st_pit", "is_yizi_zt", "is_yizi_dt", "is_zt", "is_dt", "list_age"]
    sd = ds.dataset(f"{WAVE1}/stock_day_core_features_pit.parquet").scanner(
        columns=cols_sd,
        filter=ds.field("c6").isin(codes_l),
    ).to_table().to_pandas()
    sd["dt"] = sd["dt"].astype(str).str[:10]
    sd["c6"] = sd["c6"].astype(str).str.zfill(6)
    bar_lu = {}
    for r in sd.itertuples(index=False):
        bar_lu[(r.c6, r.dt)] = (
            float(r.open), float(r.close), float(r.adj_factor),
            float(r.open_pct) if np.isfinite(r.open_pct) else np.nan,
            float(r.ret_1d) if np.isfinite(r.ret_1d) else np.nan,
            float(r.amount_yi) if np.isfinite(r.amount_yi) else np.nan,
            float(r.amount_yi_t1) if np.isfinite(r.amount_yi_t1) else np.nan,
            int(r.is_st_pit), int(r.is_yizi_zt), int(r.is_yizi_dt), int(r.list_age),
        )
    del sd
    # ETF 512100/510300 bar lookup
    etf_lu = {}
    etf = pd.read_parquet(f"{SIM}/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave2b/w2b5_event_crossmarket_lowcorr_scorecard/cache/w2b5_etf_clean_2020_20261125.parquet")
    for r in etf.itertuples(index=False):
        etf_lu[(str(r.code).zfill(6), str(r.date)[:10])] = (float(r.open), float(r.close), float(r.amount) / 1e8, str(r.name))

    return {"st_static": st_static, "dl_last": dl_last, "names": names, "dyn_st": dyn_st, "bar_lu": bar_lu, "etf_lu": etf_lu}


def _nav(rets: np.ndarray) -> float:
    return float(np.prod(1.0 + rets)) if len(rets) else 1.0


def _ex_top_k(rets: np.ndarray, k: int) -> float:
    if len(rets) <= k:
        return 1.0
    sr = np.sort(rets)
    return float(np.prod(1.0 + sr[:-k]))


def _mdd_trade(rets: np.ndarray) -> float:
    if not len(rets):
        return 0.0
    c = np.concatenate([[1.0], np.cumprod(1.0 + rets)])
    pk = np.maximum.accumulate(c)
    return float(np.max((pk - c) / pk) * 100.0)


def enrich_and_audit_ledger(name: str, df: pd.DataFrame, ref: dict, is_etf: bool = False) -> tuple[dict, list[dict]]:
    if df.empty:
        return {"variant": name, "n_trades": 0}, []
    d = df.sort_values(["buy_date", "code"]).reset_index(drop=True).copy()

    rows_enr = []
    for r in d.itertuples(index=False):
        c6, bd, ed = r.code, r.buy_date, r.exit_date
        if is_etf:
            eb = ref["etf_lu"].get((c6, bd), (np.nan, np.nan, np.nan, "ETF"))
            ee = ref["etf_lu"].get((c6, ed), (np.nan, np.nan, np.nan, "ETF"))
            bpx = float(getattr(r, "buy_px", np.nan)) if np.isfinite(getattr(r, "buy_px", np.nan)) else eb[0]
            epx = float(getattr(r, "exit_px", np.nan)) if np.isfinite(getattr(r, "exit_px", np.nan)) else ee[1]
            rows_enr.append({
                "name": eb[3], "buy_px_chk": bpx, "exit_px_chk": epx,
                "buy_amt_yi": eb[2], "t1_amt_yi": np.nan, "open_pct_chk": np.nan,
                "is_st": 0, "is_yizi_zt": 0, "is_yizi_dt": 0, "list_age": 999,
                "adj_ratio": 1.0, "delisted_dt": "", "dyn_st_dt": "",
            })
        else:
            b = ref["bar_lu"].get((c6, bd))
            e = ref["bar_lu"].get((c6, ed))
            bpx = float(getattr(r, "buy_px", getattr(r, "buy_price", getattr(r, "buy_price_val", np.nan))))
            epx = float(getattr(r, "exit_px", getattr(r, "exit_price", np.nan)))
            if (not np.isfinite(bpx)) and b:
                bpx = b[0] * b[2]
            if (not np.isfinite(epx)) and e:
                epx = e[1] * e[2]
            adj_r = (e[2] / b[2]) if (b and e and b[2] > 0) else 1.0
            rows_enr.append({
                "name": getattr(r, "name", "") or ref["names"].get(c6, ""),
                "buy_px_chk": bpx, "exit_px_chk": epx,
                "buy_amt_yi": b[5] if b else np.nan, "t1_amt_yi": b[6] if b else np.nan,
                "open_pct_chk": b[3] if b else np.nan,
                "is_st": b[7] if b else (1 if c6 in ref["st_static"] else 0),
                "is_yizi_zt": b[8] if b else 0, "is_yizi_dt": b[9] if b else 0,
                "list_age": b[10] if b else 999, "adj_ratio": adj_r,
                "delisted_dt": ref["dl_last"].get(c6, ""), "dyn_st_dt": ref["dyn_st"].get(c6, ""),
            })
    enr = pd.DataFrame(rows_enr)
    for col in enr.columns:
        d[col] = enr[col].values

    gr = d["gross_ret"].to_numpy(float)
    nr = d["net_ret"].to_numpy(float)

    # Gate 2: Slippage stress
    fees = (0.0005, 0.0015, 0.0030) if is_etf else (0.0030, 0.0050, 0.0080)
    slip = {}
    for f in fees:
        rf = (1.0 + gr) * (1.0 - f) - 1.0
        lbl = f"{int(round(f*10000))}bps"
        slip[lbl] = {
            "nav": round(_nav(rf), 4),
            "ex5_nav": round(_ex_top_k(rf, 5), 4),
            "ex10_nav": round(_ex_top_k(rf, 10), 4),
            "wr_pct": round(float((rf > 0).mean() * 100.0), 2),
            "mean_pct": round(float(rf.mean() * 100.0), 2),
            "trade_mdd_pct": round(_mdd_trade(rf), 2),
        }

    # Gate 2b: Buy-day & T-1 liquidity capacity filter (at standard 30bps for stocks, 5bps for ETF)
    r30 = (1.0 + gr) * (1.0 - (0.0005 if is_etf else 0.0030)) - 1.0
    d["ret_std"] = r30
    ba = d["buy_amt_yi"].to_numpy(float)
    ta = d["t1_amt_yi"].to_numpy(float)
    liq = {
        "n_buy_amt_lt_1yi": int(np.sum(np.isfinite(ba) & (ba < 1.0))),
        "n_buy_amt_lt_2yi": int(np.sum(np.isfinite(ba) & (ba < 2.0))),
        "n_t1_amt_lt_1yi": int(np.sum(np.isfinite(ta) & (ta < 1.0))),
        "min_buy_amt_yi": round(float(np.nanmin(ba)), 3) if np.isfinite(ba).any() else None,
        "median_buy_amt_yi": round(float(np.nanmedian(ba)), 3) if np.isfinite(ba).any() else None,
        "ge_1yi_buy_amt": {
            "n": int(np.sum(~np.isfinite(ba) | (ba >= 1.0))),
            "nav_30bps": round(_nav(r30[~np.isfinite(ba) | (ba >= 1.0)]), 4),
            "ex5_30bps": round(_ex_top_k(r30[~np.isfinite(ba) | (ba >= 1.0)], 5), 4),
        },
        "ge_2yi_buy_amt": {
            "n": int(np.sum(~np.isfinite(ba) | (ba >= 2.0))),
            "nav_30bps": round(_nav(r30[~np.isfinite(ba) | (ba >= 2.0)]), 4),
            "ex5_30bps": round(_ex_top_k(r30[~np.isfinite(ba) | (ba >= 2.0)], 5), 4),
        },
    }

    # Gate 4: Concentration, clustering, year breakdown
    d["ym"] = d["buy_date"].str[:7]
    day_cnt = d["buy_date"].value_counts()
    ym_cnt = d["ym"].value_counts()
    tot_log = float(np.sum(np.log1p(r30)))
    top5_log = float(np.sum(np.log1p(np.sort(r30)[-5:]))) if len(r30) >= 5 else tot_log
    yr_brk = {}
    for ylbl, m in [("Y2023", d["buy_date"].str[:4] == "2023"), ("Y2024", d["buy_date"].str[:4] == "2024"),
                    ("Y2025", d["buy_date"].str[:4] == "2025"), ("Y2026", d["buy_date"].str[:4] == "2026"),
                    ("Y2526", d["buy_date"] >= "2025-01-01"), ("Y26H2", d["buy_date"] >= "2026-07-01")]:
        sub_r = r30[m.to_numpy(bool)]
        yr_brk[ylbl] = {"n": int(len(sub_r)), "nav": round(_nav(sub_r), 4), "wr": round(float((sub_r > 0).mean() * 100.0), 2) if len(sub_r) else 0.0}

    # Gate 1: Anomaly scan + Top 5 Best / Worst
    anomalies = {
        "n_st_static": int((d["is_st"] == 1).sum()),
        "n_delisted_ever": int((d["delisted_dt"] != "").sum()),
        "delisted_codes": sorted(set(zip(d.loc[d["delisted_dt"] != "", "code"], d.loc[d["delisted_dt"] != "", "buy_date"], d.loc[d["delisted_dt"] != "", "delisted_dt"]))),
        "n_yizi_zt_buy": int((d["is_yizi_zt"] == 1).sum()),
        "n_yizi_dt_buy": int((d["is_yizi_dt"] == 1).sum()),
        "n_open_ge_95_non20": int(((~d["code"].str.startswith(("30", "688", "689"))) & (d["open_pct_chk"] >= 9.5)).sum()) if not is_etf else 0,
        "n_open_ge_195_20cm": int((d["code"].str.startswith(("30", "688", "689")) & (d["open_pct_chk"] >= 19.5)).sum()) if not is_etf else 0,
        "n_list_age_le_10": int((d["list_age"] <= 10).sum()),
        "n_split_adj_gt_1_2": int(((d["adj_ratio"] > 1.2) | (d["adj_ratio"] < 0.83)).sum()),
    }

    forensics_rows = []
    srt_desc = d.sort_values("net_ret", ascending=False)
    srt_asc = d.sort_values("net_ret", ascending=True)
    for bucket, sub_f in [("TOP5_BEST", srt_desc.head(5)), ("TOP5_WORST", srt_asc.head(5))]:
        for rk, r in enumerate(sub_f.itertuples(index=False), start=1):
            forensics_rows.append({
                "variant": name, "bucket": bucket, "rank": rk,
                "code": r.code, "name": r.name, "buy_date": r.buy_date, "exit_date": r.exit_date,
                "buy_px": round(float(r.buy_px_chk), 4) if np.isfinite(r.buy_px_chk) else None,
                "exit_px": round(float(r.exit_px_chk), 4) if np.isfinite(r.exit_px_chk) else None,
                "gross_ret_pct": round(float(r.gross_ret) * 100.0, 2),
                "net_ret_pct": round(float(r.net_ret) * 100.0, 2),
                "open_pct": round(float(r.open_pct_chk), 2) if np.isfinite(r.open_pct_chk) else None,
                "buy_amt_yi": round(float(r.buy_amt_yi), 2) if np.isfinite(r.buy_amt_yi) else None,
                "t1_amt_yi": round(float(r.t1_amt_yi), 2) if np.isfinite(r.t1_amt_yi) else None,
                "is_st": int(r.is_st), "is_yizi_zt": int(r.is_yizi_zt), "delisted_dt": r.delisted_dt,
            })

    summary = {
        "variant": name, "n_trades": int(len(d)),
        "base_fee_bps": int(round(float(d["base_fee"].iloc[0]) * 10000)),
        "raw_nav": round(_nav(nr), 4),
        "slippage_stress": slip,
        "liquidity_capacity": liq,
        "clustering": {
            "max_trades_single_day": int(day_cnt.iloc[0]), "max_day": str(day_cnt.index[0]),
            "max_trades_single_month": int(ym_cnt.iloc[0]), "max_month": str(ym_cnt.index[0]),
            "top5_log_ret_share_pct": round(top5_log / tot_log * 100.0, 1) if abs(tot_log) > 1e-6 else None,
        },
        "windows": yr_brk,
        "anomalies": anomalies,
    }
    return summary, forensics_rows

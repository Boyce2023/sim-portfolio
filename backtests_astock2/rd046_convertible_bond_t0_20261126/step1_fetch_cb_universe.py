#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD046 Stage 1: Full-Market A-Share Convertible Bond Universe (Active + Delisted/Redeemed, 2021-2026)
Strict Q8 Completeness Gate:
  1. Fetch complete CB master list from Eastmoney RPT_BOND_CB_LIST + THS cross-check (recovering 5 .NQ defaulted codes).
  2. Fetch daily OHLCV (2020-12-01..2026-11-26) via Tencent web.ifzq.gtimg.cn (+ Sina ak.bond_zh_hs_cov_daily fallback & parity audit).
  3. Fetch daily PIT conversion value, conversion premium rate, PIT conversion price, remaining balance via Eastmoney RPTA_WEB_KZZ_LS.
  4. Verify underlying stock coverage in stock_day_core_features_pit.parquet and emit cb_data_audit.json.
Zero yfinance (D12). Peak memory < 2.2 GB.
"""
import os
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_k] = "1"
os.environ["NO_PROXY"] = "*"

import concurrent.futures as cf
import json
import sys
import threading
import time
import warnings

import akshare as ak
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import requests

warnings.filterwarnings("ignore")
assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd046_convertible_bond_t0_20261126"
STOCK_PARQUET = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base/stock_day_core_features_pit.parquet"

NQ_RECOVER = {
    "404001": ("123015", "sz", "300297", "蓝盾退债"),
    "404002": ("128100", "sz", "002503", "搜特退债"),
    "404003": ("128085", "sz", "002002", "鸿达退债"),
    "404004": ("110072", "sh", "600297", "广汇转债"),
    "404005": ("123099", "sz", "300630", "普利退债"),
}

_tls = threading.local()


def _get_sess() -> requests.Session:
    if not hasattr(_tls, "sess"):
        s = requests.Session()
        s.trust_env = False
        s.headers.update({"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        _tls.sess = s
    return _tls.sess


def fetch_master_list() -> tuple[pd.DataFrame, dict]:
    s = _get_sess()
    rows = []
    for p in range(1, 10):
        r = s.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params={
                "reportName": "RPT_BOND_CB_LIST",
                "columns": (
                    "SECURITY_CODE,SECUCODE,TRADE_MARKET,SECURITY_NAME_ABBR,DELIST_DATE,LISTING_DATE,"
                    "CEASE_DATE,EXPIRE_DATE,CONVERT_STOCK_CODE,SECURITY_SHORT_NAME,ACTUAL_ISSUE_SCALE,"
                    "INITIAL_TRANSFER_PRICE,TRANSFER_PRICE,TRANSFER_START_DATE,TRANSFER_END_DATE,"
                    "REDEEM_TYPE,IS_REDEEM,IS_CONVERT_STOCK,IS_SELLBACK,PUBLIC_START_DATE,RATING"
                ),
                "pageSize": 500,
                "pageNumber": p,
                "sortColumns": "PUBLIC_START_DATE",
                "sortTypes": "-1",
            },
            timeout=20,
        ).json()
        res = r.get("result") or {}
        batch = res.get("data") or []
        if not batch:
            break
        rows.extend(batch)
        if len(rows) >= int(res.get("count") or 0):
            break

    em = pd.DataFrame(rows)
    em["orig_code"] = em["SECURITY_CODE"].astype(str).str.zfill(6)
    em["cb_code"] = em["orig_code"]
    em["cb_name"] = em["SECURITY_NAME_ABBR"].astype(str)
    em["stock_code"] = em["CONVERT_STOCK_CODE"].astype(str).str.zfill(6)
    em["list_dt"] = pd.to_datetime(em["LISTING_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")
    em["delist_dt"] = pd.to_datetime(em["DELIST_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")
    em["cease_dt"] = pd.to_datetime(em["CEASE_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")
    em["transfer_start_dt"] = pd.to_datetime(em["TRANSFER_START_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")
    em["pub_dt"] = pd.to_datetime(em["PUBLIC_START_DATE"], errors="coerce").dt.strftime("%Y-%m-%d")
    em["cb_mkt"] = np.where(em["SECUCODE"].astype(str).str.endswith(".SH"), "sh", "sz")

    # Recover 5 delisted-to-NQ defaulted CBs to original A-share codes
    for nq_c, (cb_c, mkt, stk_c, nm) in NQ_RECOVER.items():
        mask = em["orig_code"] == nq_c
        if mask.any():
            em.loc[mask, "cb_code"] = cb_c
            em.loc[mask, "cb_mkt"] = mkt
            em.loc[mask, "stock_code"] = stk_c
            em.loc[mask, "cb_name"] = nm
            if nq_c == "404005":
                em.loc[mask, "list_dt"] = "2021-03-08"
                em.loc[mask, "delist_dt"] = "2025-05-01"
            elif nq_c == "404002":
                em.loc[mask, "list_dt"] = "2020-04-03"
                em.loc[mask, "delist_dt"] = "2023-06-01"
            else:
                # For 404001/404003/404004, EM DELIST_DATE was NQ delist; A-share delist was earlier
                pass

    # Cross-check with THS & JSL
    ths = ak.bond_zh_cov_info_ths()
    ths_listed = ths[ths["上市日期"].notna()].copy()
    ths_listed["cb_code"] = ths_listed["债券代码"].astype(str).str.zfill(6)
    # Fix list_dt for NQ recovered CBs from THS where available
    ths_map = ths_listed.set_index("cb_code")["上市日期"].astype(str).to_dict()
    for nq_c, (cb_c, _, _, _) in NQ_RECOVER.items():
        if cb_c in ths_map and ths_map[cb_c] not in ("NaT", "None", "nan"):
            em.loc[em["orig_code"] == nq_c, "list_dt"] = ths_map[cb_c][:10]

    em["cb_sym"] = em["cb_mkt"] + em["cb_code"]
    em["is_delisted"] = (
        em["delist_dt"].notna()
        | (em["cease_dt"].notna() & (em["cease_dt"] < "2026-11-26"))
        | em["orig_code"].isin(NQ_RECOVER.keys())
    )
    # Effective end date in A-share market
    em["eff_end_dt"] = np.where(
        em["delist_dt"].notna(),
        em["delist_dt"],
        np.where(em["cease_dt"].notna() & (em["cease_dt"] < "2026-11-26"), em["cease_dt"], "2026-11-26"),
    )
    em["in_win_2021_2026"] = (
        em["list_dt"].notna()
        & (em["list_dt"] <= "2026-11-26")
        & (em["eff_end_dt"] >= "2021-01-01")
    )

    em_codes = set(em["cb_code"])
    ths_missing = sorted(set(ths_listed["cb_code"]) - em_codes)
    meta_audit = {
        "em_total_rows": int(len(em)),
        "ths_listed_rows": int(len(ths_listed)),
        "ths_listed_not_in_em": ths_missing,
        "nq_recovered_codes": list(NQ_RECOVER.keys()),
    }
    keep_cols = [
        "cb_code", "orig_code", "cb_mkt", "cb_sym", "cb_name", "stock_code",
        "SECURITY_SHORT_NAME", "list_dt", "delist_dt", "cease_dt", "eff_end_dt",
        "transfer_start_dt", "pub_dt", "ACTUAL_ISSUE_SCALE", "INITIAL_TRANSFER_PRICE",
        "TRANSFER_PRICE", "REDEEM_TYPE", "IS_REDEEM", "RATING", "is_delisted", "in_win_2021_2026",
    ]
    out = em[keep_cols].drop_duplicates("cb_code").reset_index(drop=True)
    out = out.rename(columns={
        "SECURITY_SHORT_NAME": "stock_name",
        "ACTUAL_ISSUE_SCALE": "issue_scale_yi",
        "INITIAL_TRANSFER_PRICE": "init_conv_px",
        "TRANSFER_PRICE": "latest_conv_px",
        "REDEEM_TYPE": "redeem_type",
        "IS_REDEEM": "is_redeem",
        "RATING": "rating",
    })
    for nc in ("issue_scale_yi", "init_conv_px", "latest_conv_px"):
        out[nc] = pd.to_numeric(out[nc], errors="coerce")
    return out, meta_audit


def _fetch_tx_kline(sym: str) -> list:
    s = _get_sess()
    for att in range(3):
        try:
            r = s.get(
                "https://web.ifzq.gtimg.cn/appstock/app/kline/kline",
                params={"param": f"{sym},day,2020-12-01,2026-11-26,2000"},
                timeout=12,
            ).json()
            bars = ((r.get("data") or {}).get(sym) or {}).get("day") or []
            return bars
        except Exception:
            time.sleep(0.4 * (att + 1))
    return []


def _fetch_sina_kline(sym: str) -> pd.DataFrame:
    for att in range(2):
        try:
            df = ak.bond_zh_hs_cov_daily(symbol=sym)
            if df is not None and not df.empty:
                return df
        except Exception:
            time.sleep(0.5 * (att + 1))
    return pd.DataFrame()


def _fetch_em_value_analysis(cb_code: str) -> pd.DataFrame:
    s = _get_sess()
    for att in range(3):
        try:
            r = s.get(
                "https://datacenter-web.eastmoney.com/api/data/get",
                params={
                    "sty": "ALL",
                    "token": "894050c76af8597a853f5b408b759f5d",
                    "st": "date",
                    "sr": "1",
                    "source": "WEB",
                    "type": "RPTA_WEB_KZZ_LS",
                    "filter": f'(zcode="{cb_code}")',
                    "p": "1",
                    "ps": "8000",
                },
                timeout=15,
            ).json()
            rows = (r.get("result") or {}).get("data") or []
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(rows)
            df["dt"] = pd.to_datetime(df["DATE"], errors="coerce").dt.strftime("%Y-%m-%d")
            df = df[(df["dt"] >= "2020-12-01") & (df["dt"] <= "2026-11-26")].copy()
            if df.empty:
                return pd.DataFrame()
            out = pd.DataFrame({
                "dt": df["dt"].values,
                "swap_value": pd.to_numeric(df.get("SWAPVALUE"), errors="coerce").values,
                "pure_bond_value": pd.to_numeric(df.get("PUREBONDVALUE"), errors="coerce").values,
                "pure_bond_prem_pct": pd.to_numeric(df.get("PUREBONDOR"), errors="coerce").values,
                "conv_prem_pct": pd.to_numeric(df.get("SWAPOR"), errors="coerce").values,
                "conv_px_pit": pd.to_numeric(df.get("SWAPPRICE"), errors="coerce").values,
                "remain_scale_yi": pd.to_numeric(df.get("SYFE"), errors="coerce").values / 1e8,
                "unconverted_pct": pd.to_numeric(df.get("USWAPTRATE"), errors="coerce").values,
            })
            return out.drop_duplicates("dt")
        except Exception:
            time.sleep(0.4 * (att + 1))
    return pd.DataFrame()


def fetch_one_cb(row_dict: dict) -> tuple[dict, pd.DataFrame]:
    cb_code = row_dict["cb_code"]
    sym = row_dict["cb_sym"]
    orig_code = row_dict["orig_code"]

    bars = _fetch_tx_kline(sym)
    ksrc = "tencent"
    if not bars:
        sdf = _fetch_sina_kline(sym)
        if not sdf.empty:
            ksrc = "sina"
            sdf["dt"] = pd.to_datetime(sdf["date"]).dt.strftime("%Y-%m-%d")
            sdf = sdf[(sdf["dt"] >= "2020-12-01") & (sdf["dt"] <= "2026-11-26")].copy()
            kdf = pd.DataFrame({
                "dt": sdf["dt"].values,
                "open": pd.to_numeric(sdf["open"], errors="coerce").values,
                "close": pd.to_numeric(sdf["close"], errors="coerce").values,
                "high": pd.to_numeric(sdf["high"], errors="coerce").values,
                "low": pd.to_numeric(sdf["low"], errors="coerce").values,
                "vol_shou": pd.to_numeric(sdf["volume"], errors="coerce").values / 10.0,
            })
        else:
            kdf = pd.DataFrame()
            ksrc = "missing"
    else:
        parsed = []
        for b in bars:
            if len(b) >= 6:
                parsed.append((str(b[0])[:10], float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5])))
        kdf = pd.DataFrame(parsed, columns=["dt", "open", "close", "high", "low", "vol_shou"])
        kdf = kdf[(kdf["dt"] >= "2020-12-01") & (kdf["dt"] <= "2026-11-26")].drop_duplicates("dt")

    if kdf.empty:
        return {"cb_code": cb_code, "ksrc": "missing", "n_days": 0, "va_days": 0}, pd.DataFrame()

    typ = (kdf["open"] + kdf["high"] + kdf["low"] + kdf["close"]) / 4.0
    kdf["amount_yi"] = kdf["vol_shou"] * 10.0 * typ / 1e8
    kdf["kline_src"] = ksrc

    # Value analysis (try cb_code first, if empty and NQ recovered try orig_code)
    va = _fetch_em_value_analysis(cb_code)
    if va.empty and orig_code != cb_code:
        va = _fetch_em_value_analysis(orig_code)
    va_days = int(len(va)) if not va.empty else 0

    if not va.empty:
        merged = kdf.merge(va, on="dt", how="left")
    else:
        merged = kdf.copy()
        for c in ("swap_value", "pure_bond_value", "pure_bond_prem_pct", "conv_prem_pct", "conv_px_pit", "remain_scale_yi", "unconverted_pct"):
            merged[c] = np.nan

    merged["cb_code"] = cb_code
    merged["cb_sym"] = sym
    merged["cb_name"] = row_dict["cb_name"]
    merged["stock_code"] = row_dict["stock_code"]
    merged["is_delisted"] = bool(row_dict["is_delisted"])
    return {"cb_code": cb_code, "ksrc": ksrc, "n_days": int(len(merged)), "va_days": va_days}, merged


def main():
    t0 = time.time()
    print("[Step 1] Fetching CB master list...")
    master, meta_audit = fetch_master_list()
    master.to_parquet(f"{OUT_DIR}/cb_master_list.parquet", index=False)

    win = master[master["in_win_2021_2026"]].copy().reset_index(drop=True)
    n_tot = len(win)
    n_act = int((~win["is_delisted"]).sum())
    n_del = int(win["is_delisted"].sum())
    print(f"[Step 1] In 2021-2026 window: total={n_tot}, active={n_act}, delisted/redeemed={n_del}")

    rows_dict = win.to_dict("records")
    stats = []
    dfs = []
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(fetch_one_cb, r) for r in rows_dict]
        for idx, fu in enumerate(cf.as_completed(futs), 1):
            st, df_one = fu.result()
            stats.append(st)
            if not df_one.empty:
                dfs.append(df_one)
            if idx % 150 == 0 or idx == n_tot:
                print(f"  progress {idx}/{n_tot} ({time.time()-t0:.1f}s)")

    st_df = pd.DataFrame(stats)
    win_aud = win.merge(st_df, on="cb_code", how="left")
    win_aud["has_kline"] = win_aud["n_days"].fillna(0) > 0
    win_aud["has_va"] = win_aud["va_days"].fillna(0) > 0

    act_df = win_aud[~win_aud["is_delisted"]]
    del_df = win_aud[win_aud["is_delisted"]]
    act_ok = int(act_df["has_kline"].sum())
    del_ok = int(del_df["has_kline"].sum())
    act_miss_pct = round((1.0 - act_ok / max(1, len(act_df))) * 100.0, 2)
    del_miss_pct = round((1.0 - del_ok / max(1, len(del_df))) * 100.0, 2)

    del_by_yr = {}
    del_df_yr = del_df.copy()
    del_df_yr["yr"] = del_df_yr["eff_end_dt"].str[:4]
    for yr, grp in del_df_yr.groupby("yr"):
        ok_y = int(grp["has_kline"].sum())
        del_by_yr[str(yr)] = {
            "total": int(len(grp)),
            "kline_ok": ok_y,
            "coverage_pct": round(ok_y / len(grp) * 100.0, 2),
        }

    # Combine panel
    full_cb = pd.concat(dfs, ignore_index=True)
    full_cb = full_cb.sort_values(["cb_code", "dt"]).reset_index(drop=True)

    # Supplement metadata columns onto full_cb for PIT calculations
    meta_cols = win[["cb_code", "list_dt", "eff_end_dt", "transfer_start_dt", "issue_scale_yi", "init_conv_px", "latest_conv_px"]].copy()
    full_cb = full_cb.merge(meta_cols, on="cb_code", how="left")

    # Verify underlying stock coverage in stock_day_core_features_pit.parquet
    stk_tbl = pq.read_table(STOCK_PARQUET, columns=["dt", "c6", "open", "close", "is_zt", "is_yizi_zt", "is_broken_zt", "is_st_pit", "is_20cm"])
    stk_df = stk_tbl.to_pandas()
    stk_codes_set = set(stk_df["c6"].astype(str).unique())
    cb_stk_codes = set(win["stock_code"].astype(str).unique())
    mapped_stks = len(cb_stk_codes & stk_codes_set)

    # Cross-check Tencent vs Sina on 20 random CBs (10 active + 10 delisted)
    rng = np.random.default_rng(20261126)
    samp_act = act_df[act_df["has_kline"]].sample(min(10, act_ok), random_state=42)
    samp_del = del_df[del_df["has_kline"]].sample(min(10, del_ok), random_state=42)
    parity_diffs = []
    for _, sr in pd.concat([samp_act, samp_del]).iterrows():
        sdf = _fetch_sina_kline(sr["cb_sym"])
        if sdf.empty:
            continue
        sdf["dt"] = pd.to_datetime(sdf["date"]).dt.strftime("%Y-%m-%d")
        sdf["s_close"] = pd.to_numeric(sdf["close"], errors="coerce")
        sub = full_cb[full_cb["cb_code"] == sr["cb_code"]][["dt", "close"]].merge(sdf[["dt", "s_close"]], on="dt")
        if not sub.empty:
            max_d = float((sub["close"] - sub["s_close"]).abs().max())
            parity_diffs.append({"cb_sym": sr["cb_sym"], "is_delisted": bool(sr["is_delisted"]), "overlap_days": int(len(sub)), "max_close_diff": round(max_d, 4)})

    # Check stock join hit rate on CB trading days in 2021-01-04..2026-11-25
    cb_2126 = full_cb[(full_cb["dt"] >= "2021-01-04") & (full_cb["dt"] <= "2026-11-25")].copy()
    cb_2126_j = cb_2126.merge(stk_df[["dt", "c6", "close"]].rename(columns={"c6": "stock_code", "close": "stk_close"}), on=["dt", "stock_code"], how="left")
    stk_day_hit_pct = round(float(cb_2126_j["stk_close"].notna().mean() * 100.0), 2)

    # Save parquet
    full_cb.to_parquet(f"{OUT_DIR}/cb_daily_all_pit.parquet", index=False)

    q8_pass = del_miss_pct <= 15.0
    missing_del_list = del_df[~del_df["has_kline"]][["cb_code", "cb_name", "stock_code", "list_dt", "eff_end_dt"]].to_dict("records")

    audit = {
        "meta_audit": meta_audit,
        "universe_2021_2026": {
            "total_cbs": n_tot,
            "active_cbs": n_act,
            "delisted_redeemed_cbs": n_del,
            "active_kline_ok": act_ok,
            "active_missing_rate_pct": act_miss_pct,
            "delisted_kline_ok": del_ok,
            "delisted_missing_rate_pct": del_miss_pct,
            "delisted_by_year": del_by_yr,
            "missing_delisted_sample": missing_del_list[:20],
        },
        "panel_coverage": {
            "total_cb_rows_202012_202611": int(len(full_cb)),
            "total_cb_rows_202101_202611": int(len(cb_2126)),
            "kline_sources": st_df["ksrc"].value_counts().to_dict(),
            "va_cb_coverage_pct": round(float(win_aud["has_va"].mean() * 100.0), 2),
            "conv_prem_nonnull_pct": round(float(cb_2126["conv_prem_pct"].notna().mean() * 100.0), 2),
            "conv_px_pit_nonnull_pct": round(float(cb_2126["conv_px_pit"].notna().mean() * 100.0), 2),
            "remain_scale_nonnull_pct": round(float(cb_2126["remain_scale_yi"].notna().mean() * 100.0), 2),
            "underlying_stock_code_match_pct": round(mapped_stks / max(1, len(cb_stk_codes)) * 100.0, 2),
            "cb_stock_day_join_hit_pct": stk_day_hit_pct,
        },
        "tencent_vs_sina_parity": {
            "n_checked": len(parity_diffs),
            "max_abs_close_diff": round(max((x["max_close_diff"] for x in parity_diffs), default=0.0), 4),
            "samples": parity_diffs,
        },
        "q8_completeness_gate": {
            "threshold_max_delisted_missing_pct": 15.0,
            "actual_delisted_missing_pct": del_miss_pct,
            "verdict": "PASS" if q8_pass else "FAIL",
        },
        "elapsed_sec": round(time.time() - t0, 2),
    }
    with open(f"{OUT_DIR}/cb_data_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "q8_verdict": audit["q8_completeness_gate"]["verdict"],
        "total_cbs": n_tot,
        "active_ok": f"{act_ok}/{n_act} ({100-act_miss_pct:.2f}%)",
        "delisted_ok": f"{del_ok}/{n_del} ({100-del_miss_pct:.2f}%)",
        "delisted_by_yr": del_by_yr,
        "panel_rows": len(full_cb),
        "conv_prem_nonnull_pct": audit["panel_coverage"]["conv_prem_nonnull_pct"],
        "stk_day_hit_pct": stk_day_hit_pct,
        "parity_max_diff": audit["tencent_vs_sina_parity"]["max_abs_close_diff"],
        "elapsed_sec": audit["elapsed_sec"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

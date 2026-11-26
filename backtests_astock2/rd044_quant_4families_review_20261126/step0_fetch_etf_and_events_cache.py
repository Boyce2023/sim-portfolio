#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD044 Step 0:
  1. Fetch & stitch 19 core A-share ETFs (2020-06-01 .. 2026-11-25) via Tencent QFQ API -> etf_daily_qfq_cache.parquet.
  2. Fetch full 5Y CNINFO Repurchase Plans/Reports, Shareholder Increases, and Perf Express (2021-01-01 .. 2026-11-25) -> _cache/cninfo_ext_notices_5y.parquet.
  3. Build strict-PIT event caches (E_PERF, E_BUYBACK, E_IRQA) + strict 20d toxic notice cache (tox_20d_pit.parquet).
Zero yfinance (D12).
"""
import concurrent.futures
import datetime
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

ROOT = "/Users/huaichuaibeimeng/claude-projects"
OUT_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd044_quant_4families_review_20261126"
CACHE_DIR = f"{OUT_DIR}/_cache"
BASE_DIR = f"{ROOT}/sim-portfolio/backtests_astock2/rd035_grand_wf_scorecard_20261125/wave1_base"
os.makedirs(CACHE_DIR, exist_ok=True)

ETF_POOL = [
    # Broad base (T+1)
    ("510300", "sh510300", "沪深300ETF", "broad", False),
    ("510500", "sh510500", "中证500ETF", "broad", False),
    ("512100", "sh512100", "中证1000ETF", "broad", False),
    ("159915", "sz159915", "创业板ETF", "broad", False),
    ("588000", "sh588000", "科创50ETF", "broad", False),
    # Style & Hedge (Note Gold/Bond/Nasdaq/HSTECH/HSInternet are T+0 in A-shares)
    ("510880", "sh510880", "红利ETF", "style", False),
    ("518880", "sh518880", "黄金ETF", "hedge", True),
    ("511010", "sh511010", "国债ETF", "bond", True),
    ("513100", "sh513100", "纳指ETF", "qdii", True),
    ("513180", "sh513180", "恒生科技ETF", "qdii", True),
    ("513330", "sh513330", "恒生互联ETF", "qdii", True),
    # Sector mainlines (T+1)
    ("512480", "sh512480", "半导体ETF", "sector", False),
    ("512880", "sh512880", "证券ETF", "sector", False),
    ("512660", "sh512660", "军工ETF", "sector", False),
    ("512010", "sh512010", "医药ETF", "sector", False),
    ("516160", "sh516160", "新能源ETF", "sector", False),
    ("512800", "sh512800", "银行ETF", "sector", False),
    ("515220", "sh515220", "煤炭ETF", "sector", False),
    ("512400", "sh512400", "有色金属ETF", "sector", False),
]


def _http_get_json(url: str, retries: int = 4) -> dict:
    for att in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            time.sleep(0.4 * (att + 1))
    raise RuntimeError(f"GET failed: {url}")


def _fetch_one_etf(item: tuple) -> pd.DataFrame:
    code, sym, name, cat, is_t0 = item
    slices = [
        ("2020-01-01", "2021-12-31"),
        ("2021-07-01", "2023-06-30"),
        ("2023-01-01", "2024-12-31"),
        ("2024-07-01", "2026-11-25"),
    ]
    by_dt = {}
    overlap_max_diff = 0.0
    for s_dt, e_dt in slices:
        u = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,{s_dt},{e_dt},640,qfq"
        d = _http_get_json(u)["data"][sym]
        kd = d.get("qfqday") or d.get("day") or []
        for row in kd:
            dt_s = str(row[0])[:10]
            if dt_s > "2026-11-25":
                continue
            rec = (float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))
            if dt_s in by_dt:
                # verify continuous QFQ stitch across slices
                old_c = by_dt[dt_s][1]
                if old_c > 0:
                    overlap_max_diff = max(overlap_max_diff, abs(rec[1] / old_c - 1.0))
            by_dt[dt_s] = rec

    rows = []
    for dt_s in sorted(by_dt):
        o, c, h, l, v = by_dt[dt_s]
        rows.append((dt_s, code, name, cat, bool(is_t0), o, h, l, c, v))
    df = pd.DataFrame(rows, columns=["dt", "code", "name", "category", "is_t0", "open", "high", "low", "close", "volume"])
    assert overlap_max_diff < 1e-3, f"QFQ slice mismatch for {code}: {overlap_max_diff}"
    return df


def build_etf_cache() -> pd.DataFrame:
    out_p = f"{OUT_DIR}/etf_daily_qfq_cache.parquet"
    print("[Step0] Fetching 19 ETFs QFQ bars (2020-06..2026-11-25) via Tencent API...")
    dfs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for df in ex.map(_fetch_one_etf, ETF_POOL):
            dfs.append(df)
    all_df = pd.concat(dfs, ignore_index=True).sort_values(["code", "dt"]).reset_index(drop=True)
    all_df = all_df[all_df["dt"] >= "2020-06-01"].reset_index(drop=True)
    all_df.to_parquet(out_p, index=False)
    summ = all_df.groupby(["code", "name", "is_t0"], as_index=False).agg(n=("dt", "count"), min_dt=("dt", "min"), max_dt=("dt", "max"))
    print(summ.to_string(index=False))
    print(f"[Step0] Saved {out_p} ({len(all_df)} rows)")
    return all_df


def _cninfo_post(payload: dict, retries: int = 5) -> dict:
    url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    for att in range(retries):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            time.sleep(0.5 * (att + 1))
    return {}


def _fetch_cninfo_keyword_range(kw: str, s_date: str, e_date: str) -> list[dict]:
    base_p = {
        "pageNum": 1, "pageSize": 30, "column": "szse", "tabName": "fulltext",
        "plate": "", "stock": "", "searchkey": kw, "secid": "", "category": "",
        "trade": "", "seDate": f"{s_date}~{e_date}", "sortName": "", "sortType": "", "isHLtitle": "false",
    }
    res0 = _cninfo_post(base_p)
    tot = int(res0.get("totalAnnouncement") or 0)
    out = list(res0.get("announcements") or [])
    if tot <= 30:
        return out
    n_pages = min((tot + 29) // 30, 100)  # CNINFO caps at 3000 (100 pages) per query
    for pg in range(2, n_pages + 1):
        p = dict(base_p)
        p["pageNum"] = pg
        r = _cninfo_post(p)
        anns = r.get("announcements") or []
        if not anns:
            break
        out.extend(anns)
    return out


def fetch_cninfo_ext_notices() -> pd.DataFrame:
    cache_p = f"{CACHE_DIR}/cninfo_ext_notices_5y.parquet"
    if os.path.exists(cache_p):
        df = pd.read_parquet(cache_p)
        if len(df) > 10000:
            print(f"[Step0] Reusing cached {cache_p} ({len(df)} rows)")
            return df

    print("[Step0] Querying CNINFO official API (2021-01-01..2026-11-25) for 回购方案/回购报告书/增持计划/业绩快报...")
    # Split into half-year windows so every query < 3000 items
    windows = [
        ("2021-01-01", "2021-06-30"), ("2021-07-01", "2021-12-31"),
        ("2022-01-01", "2022-06-30"), ("2022-07-01", "2022-12-31"),
        ("2023-01-01", "2023-06-30"), ("2023-07-01", "2023-12-31"),
        ("2024-01-01", "2024-06-30"), ("2024-07-01", "2024-12-31"),
        ("2025-01-01", "2025-06-30"), ("2025-07-01", "2025-12-31"),
        ("2026-01-01", "2026-06-30"), ("2026-07-01", "2026-11-25"),
    ]
    tasks = []
    for kw in ["回购方案", "回购报告书", "增持计划", "业绩快报"]:
        for s_d, e_d in windows:
            tasks.append((kw, s_d, e_d))

    records = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        fut_map = {ex.submit(_fetch_cninfo_keyword_range, kw, sd, ed): (kw, sd, ed) for kw, sd, ed in tasks}
        for fut in concurrent.futures.as_completed(fut_map):
            kw, sd, ed = fut_map[fut]
            anns = fut.result()
            for x in anns:
                ts_ms = int(x.get("announcementTime") or 0)
                dt_cst = datetime.datetime.fromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d %H:%M:%S") if ts_ms > 0 else ""
                records.append((
                    str(x.get("announcementId", "")),
                    str(x.get("secCode", "")).zfill(6),
                    str(x.get("secName", "")),
                    str(x.get("announcementTitle", "")),
                    kw,
                    ts_ms,
                    dt_cst,
                ))

    df = pd.DataFrame(records, columns=["ann_id", "sec_code", "sec_name", "title", "query_kw", "pub_ts_ms", "pub_datetime_cst"])
    df = df.sort_values(["pub_ts_ms", "sec_code"]).drop_duplicates(subset=["ann_id", "query_kw"], keep="first").reset_index(drop=True)
    df.to_parquet(cache_p, index=False)
    print(f"[Step0] Saved {cache_p} ({len(df)} rows)")
    print(df.groupby([df["pub_datetime_cst"].str[:4], "query_kw"]).size().unstack(fill_value=0))
    return df


def _map_pub_to_buy_date(pub_dt_series: pd.Series, cal_arr: np.ndarray) -> np.ndarray:
    """
    Strictly causal mapping from CST publication timestamp to earliest tradable 09:25 open trading day:
      - If time == '00:00:00' (date-only SSE/EM record -> evening release): strictly NEXT trading day > pub_date.
      - If time >= '09:15:00': intraday/after-close -> strictly NEXT trading day > pub_date.
      - If 00:00:01 <= time < 09:15:00: if pub_date is trading day, tradable at pub_date open; else next trading day.
    """
    pub_s = pub_dt_series.astype(str)
    p_dt = pub_s.str[:10].values
    p_tm = pub_s.str[11:19].values
    pos = np.searchsorted(cal_arr, p_dt, side="left")
    n_cal = len(cal_arr)
    on_same = (pos < n_cal) & (cal_arr[np.minimum(pos, n_cal - 1)] == p_dt)
    must_next = (p_tm == "00:00:00") | (p_tm >= "09:15:00") | (p_tm == "")
    eff = np.where(on_same & must_next, pos + 1, pos)
    out = np.where(eff < n_cal, cal_arr[np.minimum(eff, n_cal - 1)], "")
    return out


def build_strict_pit_event_and_tox_caches(ext_df: pd.DataFrame):
    bench = pd.read_parquet(f"{BASE_DIR}/v20_daily_bench_20210104_20261125.parquet")
    cal_arr = np.array(sorted(bench["trade_date"].astype(str).unique()))

    # 1. Toxic 20d PIT cache (exact 20 trading days window strictly causal prior to T 09:25)
    tox = pd.read_parquet(f"{ROOT}/sim-portfolio/data/pit_reg_tox_notices_5y_complete.parquet", columns=["sec_code", "pub_datetime_cst", "title"])
    con_n = sqlite3.connect(f"file:{ROOT}/sim-portfolio/data/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    extra_n = pd.read_sql_query(
        "SELECT sec_code, pub_datetime_cst, title FROM notices WHERE pub_datetime_cst > '2026-11-17 19:00:00' AND (title LIKE '%立案%' OR title LIKE '%退市%' OR title LIKE '%监管%' OR title LIKE '%警示%' OR title LIKE '%风险提示%')",
        con_n,
    )
    if len(extra_n):
        tox = pd.concat([tox, extra_n], ignore_index=True)
    tox["c6"] = tox["sec_code"].astype(str).str.zfill(6)
    tox["buy_date"] = _map_pub_to_buy_date(tox["pub_datetime_cst"], cal_arr)
    tox = tox[(tox["buy_date"] != "") & (~tox["title"].astype(str).str.contains("异常波动", regex=False))].copy()
    tox = tox[["c6", "buy_date", "pub_datetime_cst", "title"]].drop_duplicates(subset=["c6", "buy_date"]).reset_index(drop=True)
    tox.to_parquet(f"{CACHE_DIR}/tox_notices_pit.parquet", index=False)
    print(f"[Step0] Saved tox_notices_pit.parquet ({len(tox)} stock-day reg-tox events)")

    # 2. E_PERF: Earnings Forecast (预增/扭亏/略增) + Express (业绩快报)
    perf_db = pd.read_sql_query(
        """
        SELECT sec_code, ann_type, pub_datetime_cst, title
        FROM notices
        WHERE ann_type IN ('业绩预告:预增', '业绩预告:略增', '业绩预告:扭亏', '业绩快报')
        """,
        con_n,
    )
    con_n.close()
    perf_db["c6"] = perf_db["sec_code"].astype(str).str.zfill(6)
    perf_db["src"] = "db_notices"

    kb_ext = ext_df[ext_df["query_kw"] == "业绩快报"].copy()
    kb_ext = kb_ext[~kb_ext["title"].str.contains("更正|补充|取消|修订|英文", regex=True, na=False)].copy()
    kb_ext["c6"] = kb_ext["sec_code"].astype(str).str.zfill(6)
    kb_ext["ann_type"] = "业绩快报"
    kb_ext["src"] = "cninfo_kb"

    perf = pd.concat([perf_db[["c6", "ann_type", "pub_datetime_cst", "title", "src"]], kb_ext[["c6", "ann_type", "pub_datetime_cst", "title", "src"]]], ignore_index=True)
    perf["buy_date"] = _map_pub_to_buy_date(perf["pub_datetime_cst"], cal_arr)
    perf = perf[perf["buy_date"].between("2021-01-04", "2026-11-25")].copy()

    # Extract growth % from Eastmoney structured title e.g. 净利润变动 80.52%~92.56%
    def _parse_perf_meta(row):
        ttl = str(row["title"])
        at = str(row["ann_type"])
        m = re.search(r"净利润变动\s*([+-]?\d+(?:\.\d+)?)%~([+-]?\d+(?:\.\d+)?)%", ttl)
        g_low = float(m.group(1)) if m else np.nan
        g_high = float(m.group(2)) if m else np.nan
        g_mid = 0.5 * (g_low + g_high) if np.isfinite(g_low) else np.nan
        is_nk = 1 if ("扭亏" in at or "扭亏" in ttl) else 0
        is_yz = 1 if ("预增" in at or "预增" in ttl) else 0
        is_kb = 1 if ("快报" in at or "快报" in ttl) else 0
        is_kf = 1 if "扣除非经常性损益" in ttl else 0
        return pd.Series([g_low, g_high, g_mid, is_nk, is_yz, is_kb, is_kf])

    perf[["g_low", "g_high", "g_mid", "is_nk", "is_yz", "is_kb", "is_kf"]] = perf.apply(_parse_perf_meta, axis=1)
    # Deduplicate same (c6, buy_date): prefer 扣非 or highest growth, keeping record
    perf = perf.sort_values(["c6", "buy_date", "is_yz", "is_nk", "is_kf", "g_mid"], ascending=[True, True, False, False, False, False], na_position="last")
    perf = perf.drop_duplicates(subset=["c6", "buy_date"], keep="first").reset_index(drop=True)
    perf.to_parquet(f"{CACHE_DIR}/events_perf_pit.parquet", index=False)
    print(f"[Step0] Saved events_perf_pit.parquet ({len(perf)} stock-day events)")
    print("  E_PERF by year:", perf.groupby(perf["buy_date"].str[:4]).size().to_dict())

    # 3. E_BUYBACK: Repurchase plans/reports & Shareholder/Exec increase plans (pure initial/action events)
    bb_raw = ext_df[ext_df["query_kw"].isin(["回购方案", "回购报告书", "增持计划"])].copy()
    ttl_s = bb_raw["title"].astype(str)
    # Exclude equity-incentive cancellation, legal/independent opinions, completion/progress notices, decreases
    bad_pat = r"注销|激励|限制性股票|法律意见|独立意见|核查意见|进展|实施完毕|实施结果|完成|届满|误操作|减持|终止|取消|问询"
    keep_bb = (bb_raw["query_kw"].isin(["回购方案", "回购报告书"])) & (~ttl_s.str.contains(bad_pat, regex=True)) & ttl_s.str.contains(r"方案|报告书|提议", regex=True)
    keep_inc = (bb_raw["query_kw"] == "增持计划") & (~ttl_s.str.contains(bad_pat, regex=True)) & ttl_s.str.contains(r"增持计划|拟增持|首次增持", regex=True)
    bb = bb_raw[keep_bb | keep_inc].copy()
    bb["event_sub"] = np.where(keep_bb[keep_bb | keep_inc], "repurchase", "shareholder_inc")
    bb["c6"] = bb["sec_code"].astype(str).str.zfill(6)
    bb["buy_date"] = _map_pub_to_buy_date(bb["pub_datetime_cst"], cal_arr)
    bb = bb[bb["buy_date"].between("2021-01-04", "2026-11-25")].copy()
    bb = bb.sort_values(["c6", "buy_date", "event_sub"]).drop_duplicates(subset=["c6", "buy_date"], keep="first").reset_index(drop=True)
    bb[["c6", "buy_date", "pub_datetime_cst", "event_sub", "title"]].to_parquet(f"{CACHE_DIR}/events_buyback_pit.parquet", index=False)
    print(f"[Step0] Saved events_buyback_pit.parquet ({len(bb)} stock-day events)")
    print("  E_BUYBACK by year:", bb.groupby([bb["buy_date"].str[:4], "event_sub"]).size().unstack(fill_value=0).to_dict())

    # 4. E_IRQA: Strictly causal IR Q&A counts & question surge (fixing DB 3361 intraday lookahead!)
    con_ir = sqlite3.connect(f"file:{ROOT}/sim-portfolio/data/cninfo_ir_qa_5y_pit.db?mode=ro", uri=True)
    ir = pd.read_sql_query("SELECT sec_code, pub_datetime_cst, title, full_text, text_len FROM ir_qa", con_ir)
    con_ir.close()
    ir["c6"] = ir["sec_code"].astype(str).str.zfill(6)
    ir["buy_date"] = _map_pub_to_buy_date(ir["pub_datetime_cst"], cal_arr)
    ir = ir[ir["buy_date"].between("2021-01-04", "2026-11-25")].copy()
    # Count Q&A questions inside full_text
    ir["q_cnt"] = ir["full_text"].fillna("").str.count(r"(?:\n\s*(?:Q|问|问题)\s*[:：]|\d+[、\.．].{2,40}[？?])").clip(lower=1).astype(np.int16)
    ir_day = ir.groupby(["c6", "buy_date"], as_index=False).agg(
        ir_rec_cnt=("title", "count"),
        ir_q_cnt=("q_cnt", "sum"),
        ir_text_len=("text_len", "sum"),
        pub_datetime_cst=("pub_datetime_cst", "max"),
    )
    ir_day.to_parquet(f"{CACHE_DIR}/events_irqa_pit.parquet", index=False)
    print(f"[Step0] Saved events_irqa_pit.parquet ({len(ir_day)} stock-day IR records)")
    print("  E_IRQA by year:", ir_day.groupby(ir_day["buy_date"].str[:4]).size().to_dict())


def main():
    t0 = time.time()
    build_etf_cache()
    ext_df = fetch_cninfo_ext_notices()
    build_strict_pit_event_and_tox_caches(ext_df)
    print(f"[Step0] Complete in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()

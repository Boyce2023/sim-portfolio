#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD050 Step 1: Q8 Data Foundation — 100% PIT A-Share Sector/Theme & Broad Benchmark ETF 09:25 Auction Database.
- Fetches 81 Sector/Theme ETFs + 5 Broad Benchmark ETFs (2020-01-01 .. 2026-11-27) via Tencent API
  (both QFQ stitched across overlapping slices AND RAW unadjusted for corporate-action cross-validation).
- Strictly clears proxy env vars & uses ProxyHandler({}). Zero yfinance (D12).
- Audits QFQ vs RAW divergences & |open_pct| > 10% (splits/dividends), enforces strict PIT list_date + 5 trd days.
- Also pulls Eastmoney SW2 f100 current snapshot (strictly labeled as current snapshot for bias comparison ONLY).
"""
import os
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_k] = "1"

import concurrent.futures
import json
import resource
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"
sys.dont_write_bytecode = True

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd050_etf_auction_6strat_20261127"
os.makedirs(OUT_DIR, exist_ok=True)

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# (code, tencent_sym, name, group, fallback_code_if_unlisted)
ETF_UNIVERSE = [
    # Broad Benchmarks (5)
    ("510300", "sh510300", "沪深300ETF", "broad", None),
    ("510500", "sh510500", "中证500ETF", "broad", None),
    ("512100", "sh512100", "中证1000ETF", "broad", None),
    ("159915", "sz159915", "创业板ETF", "broad", None),
    ("588000", "sh588000", "科创50ETF", "broad", "512100"),
    # Tech Hardware / Semi / Comms (11)
    ("512480", "sh512480", "半导体ETF", "tech", "515000"),
    ("159995", "sz159995", "芯片ETF", "tech", "512480"),
    ("588200", "sh588200", "科创芯片ETF", "tech", "512480"),
    ("159516", "sz159516", "半导体设备ETF国泰", "tech", "512480"),
    ("561980", "sh561980", "半导体设备ETF招商", "tech", "512480"),
    ("159732", "sz159732", "消费电子ETF", "tech", "515260"),
    ("515260", "sh515260", "电子ETF华宝", "tech", "515000"),
    ("159997", "sz159997", "电子ETF天弘", "tech", "515000"),
    ("515880", "sh515880", "通信ETF国泰", "tech", "515050"),
    ("515050", "sh515050", "5G通信ETF", "tech", "515000"),
    ("515000", "sh515000", "科技ETF", "tech", "512100"),
    # AI / Software / Media / Robotics / Auto Tech (15)
    ("159819", "sz159819", "人工智能ETF易方达", "ai_sw", "515070"),
    ("515070", "sh515070", "人工智能ETF华夏", "ai_sw", "512720"),
    ("512720", "sh512720", "计算机ETF", "ai_sw", "515000"),
    ("515230", "sh515230", "软件ETF国泰", "ai_sw", "512720"),
    ("159852", "sz159852", "软件ETF嘉实", "ai_sw", "512720"),
    ("516510", "sh516510", "云计算ETF", "ai_sw", "512720"),
    ("515400", "sh515400", "大数据ETF", "ai_sw", "512720"),
    ("159851", "sz159851", "金融科技ETF", "ai_sw", "512720"),
    ("159540", "sz159540", "信创ETF", "ai_sw", "512720"),
    ("512980", "sh512980", "传媒ETF", "media", "510500"),
    ("159869", "sz159869", "游戏ETF", "media", "512980"),
    ("516620", "sh516620", "影视ETF", "media", "512980"),
    ("562500", "sh562500", "机器人ETF华夏", "robot", "515070"),
    ("159770", "sz159770", "机器人ETF天弘", "robot", "515070"),
    ("515250", "sh515250", "智能汽车ETF", "auto", "515030"),
    # Manufacturing / Defense / New Energy / Power (17)
    ("512660", "sh512660", "军工ETF国泰", "mfg_ne", "510500"),
    ("512710", "sh512710", "军工龙头ETF", "mfg_ne", "512660"),
    ("516320", "sh516320", "高端装备ETF", "mfg_ne", "512660"),
    ("159638", "sz159638", "航空航天ETF", "mfg_ne", "512660"),
    ("159378", "sz159378", "通用航空ETF", "mfg_ne", "512660"),
    ("159206", "sz159206", "卫星ETF", "mfg_ne", "512660"),
    ("159667", "sz159667", "工业母机ETF", "mfg_ne", "516320"),
    ("560280", "sh560280", "工程机械ETF", "mfg_ne", "516320"),
    ("516110", "sh516110", "汽车ETF", "auto", "515030"),
    ("515030", "sh515030", "新能源车ETF", "auto", "510500"),
    ("159755", "sz159755", "电池ETF", "mfg_ne", "515030"),
    ("159566", "sz159566", "储能电池ETF", "mfg_ne", "516160"),
    ("515790", "sh515790", "光伏ETF", "mfg_ne", "515030"),
    ("516160", "sh516160", "新能源ETF", "mfg_ne", "515790"),
    ("159611", "sz159611", "电力ETF", "mfg_ne", "516160"),
    ("562550", "sh562550", "绿电ETF", "mfg_ne", "159611"),
    ("159326", "sz159326", "电网设备ETF", "mfg_ne", "159611"),
    # Cyclicals / Resources / Materials / Infra / Transport (17)
    ("512400", "sh512400", "有色金属ETF", "cyc", "510500"),
    ("560860", "sh560860", "工业有色ETF", "cyc", "512400"),
    ("517520", "sh517520", "黄金股ETF", "cyc", "512400"),
    ("516150", "sh516150", "稀土ETF", "cyc", "512400"),
    ("515220", "sh515220", "煤炭ETF", "cyc", "510500"),
    ("515210", "sh515210", "钢铁ETF", "cyc", "510500"),
    ("561360", "sh561360", "石油ETF国泰", "cyc", "515220"),
    ("159697", "sz159697", "石油ETF鹏华", "cyc", "515220"),
    ("516020", "sh516020", "化工ETF华宝", "cyc", "512400"),
    ("159870", "sz159870", "化工ETF鹏华", "cyc", "512400"),
    ("516710", "sh516710", "新材料ETF", "cyc", "512400"),
    ("159745", "sz159745", "建材ETF", "cyc", "512200"),
    ("512200", "sh512200", "房地产ETF", "cyc", "510300"),
    ("516950", "sh516950", "基建ETF", "cyc", "512200"),
    ("512580", "sh512580", "环保ETF", "cyc", "510500"),
    ("561320", "sh561320", "交运ETF", "cyc", "516950"),
    ("516910", "sh516910", "物流ETF", "cyc", "516950"),
    # Consumer / Healthcare / Agri / Education (14)
    ("515170", "sh515170", "食品饮料ETF", "cons", "159928"),
    ("512690", "sh512690", "酒ETF", "cons", "159928"),
    ("159928", "sz159928", "消费ETF", "cons", "510300"),
    ("159996", "sz159996", "家电ETF", "cons", "159928"),
    ("159766", "sz159766", "旅游ETF", "cons", "159928"),
    ("515730", "sh515730", "家居家电ETF", "cons", "159996"),
    ("513360", "sh513360", "教育ETF", "cons", "512980"),
    ("512010", "sh512010", "医药ETF", "med", "510500"),
    ("512170", "sh512170", "医疗ETF", "med", "512010"),
    ("159992", "sz159992", "创新药ETF", "med", "512010"),
    ("560080", "sh560080", "中药ETF", "med", "512010"),
    ("159883", "sz159883", "医疗器械ETF", "med", "512170"),
    ("159865", "sz159865", "养殖ETF", "agri", "159825"),
    ("159825", "sz159825", "农业ETF", "agri", "159928"),
    # Financials / Dividend / SOE (7)
    ("512000", "sh512000", "券商ETF", "fin", "512880"),
    ("512880", "sh512880", "证券ETF", "fin", "512070"),
    ("512800", "sh512800", "银行ETF", "fin", "510300"),
    ("512070", "sh512070", "证券保险ETF", "fin", "510300"),
    ("515080", "sh515080", "中证红利ETF", "fin", "510880"),
    ("510880", "sh510880", "红利ETF", "fin", "510300"),
    ("512950", "sh512950", "央企改革ETF", "fin", "510300"),
]

SLICES = [
    ("2020-01-01", "2021-12-31"),
    ("2021-07-01", "2023-06-30"),
    ("2023-01-01", "2024-12-31"),
    ("2024-07-01", "2026-11-27"),
]


def _get_json(url: str, retries: int = 5) -> dict:
    for att in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with OPENER.open(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            time.sleep(0.35 * (att + 1))
    raise RuntimeError(f"Failed GET: {url}")


def _fetch_one_etf(item: tuple) -> tuple[pd.DataFrame, dict]:
    code, sym, name, grp, fb = item
    by_dt_qfq = {}
    by_dt_raw = {}
    overlap_qfq_diff = 0.0
    for fq_flag, target in [("qfq", by_dt_qfq), ("", by_dt_raw)]:
        for s_dt, e_dt in SLICES:
            u = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,{s_dt},{e_dt},640,{fq_flag}"
            js = _get_json(u)
            node = (js.get("data") or {}).get(sym) or {}
            kd = node.get("qfqday") if fq_flag == "qfq" else node.get("day")
            if kd is None:
                kd = node.get("day") or []
            for row in kd:
                dt_s = str(row[0])[:10]
                if dt_s > "2026-11-26":
                    continue
                rec = (float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))
                if fq_flag == "qfq" and dt_s in target and target[dt_s][1] > 0:
                    overlap_qfq_diff = max(overlap_qfq_diff, abs(rec[1] / target[dt_s][1] - 1.0))
                target[dt_s] = rec

    all_dts = sorted(set(by_dt_qfq) | set(by_dt_raw))
    rows = []
    for dt_s in all_dts:
        q = by_dt_qfq.get(dt_s)
        r = by_dt_raw.get(dt_s)
        if q is None or r is None:
            continue
        rows.append((dt_s, code, name, grp, fb or "", q[0], q[2], q[3], q[1], q[4], r[0], r[1]))
    df = pd.DataFrame(rows, columns=[
        "dt", "code", "name", "grp", "fallback_code",
        "open_qfq", "high_qfq", "low_qfq", "close_qfq", "volume",
        "open_raw", "close_raw",
    ])
    df = df[df["volume"] > 0].sort_values("dt").reset_index(drop=True)
    df["prev_close_qfq"] = df["close_qfq"].shift(1)
    df["prev_close_raw"] = df["close_raw"].shift(1)
    df["etf_open_pct_qfq"] = df["open_qfq"] / df["prev_close_qfq"] - 1.0
    df["etf_open_pct_raw"] = df["open_raw"] / df["prev_close_raw"] - 1.0
    df["etf_intraday_ret"] = df["close_qfq"] / df["open_qfq"] - 1.0
    df["etf_ret_t1"] = df["close_qfq"].shift(1) / df["close_qfq"].shift(2) - 1.0
    df["etf_ret_5d"] = df["close_qfq"].shift(1) / df["close_qfq"].shift(6) - 1.0
    df["bar_idx"] = np.arange(len(df), dtype=int)
    list_dt = df["dt"].iloc[0] if not df.empty else ""
    df["list_dt"] = list_dt
    df["pit_eligible"] = df["bar_idx"] >= 5

    # Detect corporate actions / anomalies where raw and qfq diverge or |open_pct| > 10%
    div_mask = (df["etf_open_pct_qfq"] - df["etf_open_pct_raw"]).abs() > 0.005
    big_qfq = df["etf_open_pct_qfq"].abs() > 0.105
    big_raw = df["etf_open_pct_raw"].abs() > 0.105
    anom = df[div_mask | big_qfq | big_raw].copy()
    anom_rows = anom[["dt", "code", "name", "open_qfq", "prev_close_qfq", "open_raw", "prev_close_raw", "etf_open_pct_qfq", "etf_open_pct_raw"]].to_dict("records")

    meta = {
        "code": code,
        "name": name,
        "grp": grp,
        "fallback_code": fb or "",
        "list_dt": list_dt,
        "max_dt": df["dt"].iloc[-1] if not df.empty else "",
        "n_bars": int(len(df)),
        "is_pre2021_11": bool(list_dt <= "2021-11-01"),
        "is_pre2020_12": bool(list_dt <= "2020-12-31"),
        "overlap_qfq_max_diff": round(float(overlap_qfq_diff), 6),
        "n_qfq_raw_div_gt50bps": int(div_mask.sum()),
        "n_qfq_open_gt105": int(big_qfq.sum()),
        "n_raw_open_gt105": int(big_raw.sum()),
        "max_abs_qfq_open_pct": round(float(df["etf_open_pct_qfq"].abs().max()), 5) if len(df) > 1 else 0.0,
    }
    return df, meta, anom_rows


def fetch_em_industry_snapshot() -> pd.DataFrame:
    """Fetch current Eastmoney SW2 f100 across all A-shares (paginated, strictly snapshot for bias check ONLY)."""
    all_rows = []
    for pn in range(1, 70):
        u = (
            f"https://82.push2.eastmoney.com/api/qt/clist/get?pn={pn}&pz=100&po=1&np=1"
            "&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f100"
        )
        js = _get_json(u)
        diff = (js.get("data") or {}).get("diff") or []
        if not diff:
            break
        all_rows.extend(diff)
        if len(diff) < 100:
            break
    df = pd.DataFrame(all_rows).drop_duplicates(subset=["f12"])
    df = df.rename(columns={"f12": "c6", "f14": "em_name", "f100": "em_sw2"})
    df["c6"] = df["c6"].astype(str).str.zfill(6)
    return df[["c6", "em_name", "em_sw2"]].reset_index(drop=True)


def main():
    t0 = time.time()
    print(f"[Step1] Fetching {len(ETF_UNIVERSE)} ETFs (QFQ + RAW) from Tencent API...")
    dfs, metas, anoms = [], [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for df, meta, anom in ex.map(_fetch_one_etf, ETF_UNIVERSE):
            dfs.append(df)
            metas.append(meta)
            anoms.extend(anom)

    etf_all = pd.concat(dfs, ignore_index=True)
    # Attach CSI1000 (512100) & CSI300 (510300) open_pct for excess auction gap
    b1000 = etf_all[etf_all["code"] == "512100"][["dt", "etf_open_pct_qfq"]].rename(columns={"etf_open_pct_qfq": "csi1000_open_pct"})
    b300 = etf_all[etf_all["code"] == "510300"][["dt", "etf_open_pct_qfq"]].rename(columns={"etf_open_pct_qfq": "csi300_open_pct"})
    etf_all = etf_all.merge(b1000, on="dt", how="left").merge(b300, on="dt", how="left")
    etf_all["etf_open_ex_1000"] = etf_all["etf_open_pct_qfq"] - etf_all["csi1000_open_pct"]
    etf_all["etf_open_ex_300"] = etf_all["etf_open_pct_qfq"] - etf_all["csi300_open_pct"]

    etf_all.to_parquet(f"{OUT_DIR}/etf_pit_daily.parquet", index=False)
    meta_df = pd.DataFrame(metas).sort_values(["grp", "code"])
    meta_df.to_csv(f"{OUT_DIR}/etf_metadata_audit.csv", index=False, encoding="utf-8-sig")
    anom_df = pd.DataFrame(anoms)
    anom_df.to_csv(f"{OUT_DIR}/etf_anomalies_audit.csv", index=False, encoding="utf-8-sig")

    em_df = fetch_em_industry_snapshot()
    em_df.to_parquet(f"{OUT_DIR}/em_industry_snapshot_20261127.parquet", index=False)

    rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1)
    audit = {
        "n_total_etfs": len(ETF_UNIVERSE),
        "n_broad": int((meta_df["grp"] == "broad").sum()),
        "n_sector_theme": int((meta_df["grp"] != "broad").sum()),
        "n_pre2021_11": int(meta_df["is_pre2021_11"].sum()),
        "n_pre2020_12": int(meta_df["is_pre2020_12"].sum()),
        "max_overlap_qfq_diff": float(meta_df["overlap_qfq_max_diff"].max()),
        "n_qfq_open_gt105_events": int(meta_df["n_qfq_open_gt105"].sum()),
        "n_raw_open_gt105_events": int(meta_df["n_raw_open_gt105"].sum()),
        "n_qfq_raw_div_gt50bps": int(meta_df["n_qfq_raw_div_gt50bps"].sum()),
        "em_snapshot_rows": int(len(em_df)),
        "rss_mb": rss_mb,
        "elapsed_sec": round(time.time() - t0, 2),
    }
    with open(f"{OUT_DIR}/q8_step1_audit.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
    print("[Step1 AUDIT]", json.dumps(audit, ensure_ascii=False))
    if not anom_df.empty:
        print("Anomalies sample (|open_qfq|>10.5% or div>50bps):\n", anom_df[anom_df["etf_open_pct_qfq"].abs() > 0.105].to_string(index=False))
        print("Total div/anom rows:", len(anom_df))


if __name__ == "__main__":
    main()

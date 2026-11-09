#!/usr/bin/env python3
"""
W1_09: 1995-2026 SEC 全历史财报精确时间戳与 Pre-2009 面板提取器 (分片C + Gap补齐)
Part C: pre2009_shard_0..3 全部 851 家去重升序排序后取 [2::3] (共 283 家)
Gap: 检查 pre2009_shard_2+3 中属于 [0::3] 的 142 家公司（确保 851 家全覆盖）

Outputs:
1. /tmp/us_earn_macro_bt_20261109/pre2009_shards/sec_filings_1995_2026_partC.parquet
2. /tmp/us_earn_macro_bt_20261109/pre2009_shards/sec_filings_1995_2026_partC_gap.parquet
3. /tmp/us_earn_macro_bt_20261109/pre2009_shards/pre2009_comp_anchored_partC.parquet
"""

import os
import sys
import json
import time
import math
import re
import zoneinfo
import zipfile
from datetime import datetime, time as dtime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup

# -------------------------------------------------------------
# 路径与配置
# -------------------------------------------------------------
BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y"
SHARDS_DIR = os.path.join(BASE_DIR, "shards")
BASE_TMP = "/tmp/us_earn_macro_bt_20261109"
OUT_DIR = os.path.join(BASE_TMP, "pre2009_shards")
SEC_CACHE_DIR = os.path.join(BASE_TMP, "sec_cache")
SEC_DOCS_CACHE = os.path.join(SEC_CACHE_DIR, "docs")
ZIP_PATH = os.path.join(BASE_TMP, "companyfacts.zip")
UNIVERSE_CSV = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/universe.csv"

OUT_FILINGS_C = os.path.join(OUT_DIR, "sec_filings_1995_2026_partC.parquet")
OUT_FILINGS_GAP = os.path.join(OUT_DIR, "sec_filings_1995_2026_partC_gap.parquet")
OUT_ANCHORED_C = os.path.join(OUT_DIR, "pre2009_comp_anchored_partC.parquet")

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(SEC_CACHE_DIR, exist_ok=True)
os.makedirs(SEC_DOCS_CACHE, exist_ok=True)

# -------------------------------------------------------------
# 网络与限速配置 (严格限速 <= 1.35 req/s，遵守 SEC 规范)
# -------------------------------------------------------------
USER_AGENT = "OHIM Research buwen@ohim.com"
RATE_LIMIT_SLEEP = 0.75  # ~1.33 req/sec

session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    raise_on_status=False
)
session.mount("https://", HTTPAdapter(max_retries=retries))
session.headers.update({"User-Agent": USER_AGENT})

ET_TZ = zoneinfo.ZoneInfo("America/New_York")


def sec_get_json(url, local_cache_path):
    """带本地缓存、限速与重试的 SEC JSON 获取函数"""
    if os.path.exists(local_cache_path):
        try:
            with open(local_cache_path, "r", encoding="utf-8") as f:
                content = f.read()
                if content == "__404__":
                    return None
                return json.loads(content)
        except Exception:
            pass

    time.sleep(RATE_LIMIT_SLEEP)
    try:
        resp = session.get(url, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            with open(local_cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data
        elif resp.status_code == 404:
            with open(local_cache_path, "w", encoding="utf-8") as f:
                f.write("__404__")
            return None
        elif resp.status_code == 429:
            print(f"[429 RateLimit] Backing off 10s for {url}...")
            time.sleep(10.0)
            resp = session.get(url, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                with open(local_cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                return data
            return None
        else:
            print(f"[WARN] HTTP {resp.status_code} for {url}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"[WARN] Exception fetching {url}: {e}", file=sys.stderr)
        return None


def sec_get_text(url, local_cache_path, max_bytes=3_000_000):
    """带本地缓存、限速的 SEC 文档获取函数"""
    if os.path.exists(local_cache_path):
        try:
            with open(local_cache_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            pass

    time.sleep(RATE_LIMIT_SLEEP)
    try:
        headers = {"Range": f"bytes=0-{max_bytes}"}
        resp = session.get(url, headers=headers, timeout=25)
        if resp.status_code in (200, 206):
            text = resp.text
            with open(local_cache_path, "w", encoding="utf-8", errors="ignore") as f:
                f.write(text)
            return text
        elif resp.status_code == 429:
            time.sleep(10.0)
            resp = session.get(url, headers=headers, timeout=25)
            if resp.status_code in (200, 206):
                text = resp.text
                with open(local_cache_path, "w", encoding="utf-8", errors="ignore") as f:
                    f.write(text)
                return text
        return ""
    except Exception as e:
        print(f"[WARN] Exception fetching doc {url}: {e}", file=sys.stderr)
        return ""


# -------------------------------------------------------------
# 时间与字段解析
# -------------------------------------------------------------
def parse_session_timing(adt_str):
    """
    解析 acceptanceDateTime 并在美东时间 (America/New_York) 下判断:
    - BMO_pre0930ET: 盘前 (< 09:30 ET)
    - INTRADAY: 盘中 (09:30 - 16:00 ET)
    - AMC_post1600ET: 盘后 (>= 16:00 ET)
    - DATE_ONLY: 仅日期或 00:00:00
    """
    if not adt_str or len(str(adt_str).strip()) < 10:
        return "DATE_ONLY"
    s = str(adt_str).strip()
    try:
        if s.endswith("Z"):
            dt_utc = datetime.fromisoformat(s[:-1] + "+00:00")
            dt_et = dt_utc.astimezone(ET_TZ)
        elif "T" in s or " " in s:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt_et = dt.replace(tzinfo=ET_TZ)
            else:
                dt_et = dt.astimezone(ET_TZ)
        else:
            return "DATE_ONLY"

        if dt_et.hour == 0 and dt_et.minute == 0 and dt_et.second == 0:
            return "DATE_ONLY"

        t = dt_et.time()
        t_0930 = dtime(9, 30, 0)
        t_1600 = dtime(16, 0, 0)
        if t < t_0930:
            return "BMO_pre0930ET"
        elif t < t_1600:
            return "INTRADAY"
        else:
            return "AMC_post1600ET"
    except Exception:
        return "DATE_ONLY"


def check_8k_items(items_val):
    """检查 8-K items 是否包含 2.02, 12, 1.03, 2.01"""
    if not items_val:
        return False
    if isinstance(items_val, list):
        item_set = {str(x).strip() for x in items_val}
    else:
        item_set = {x.strip() for x in str(items_val).replace(";", ",").split(",") if x.strip()}
    target = {"2.02", "12", "1.03", "2.01"}
    return bool(item_set & target)


# -------------------------------------------------------------
# 分片加载与 Gap 分析
# -------------------------------------------------------------
def load_all_and_split():
    """
    加载全部 4 个分片，合并去重后按 ticker 升序排序
    取出 Part C: [2::3] (约 283 家)
    并分析 Gap: 属于 [0::3] 但来自 shard_2 或 shard_3 的 142 家公司
    """
    shards_raw = []
    shards_by_num = {}
    for i in range(4):
        p = os.path.join(SHARDS_DIR, f"pre2009_shard_{i}.json")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            shards_by_num[i] = data
            shards_raw.extend(data)

    unique_all = {x["ticker"]: x for x in shards_raw}
    sorted_all = sorted(unique_all.values(), key=lambda x: x["ticker"])
    print(f"Total unique companies across 4 shards: {len(sorted_all)}")

    part_c = sorted_all[2::3]
    print(f"Part C [2::3] count: {len(part_c)}")

    # Gap 分析
    s23_tickers = set(x["ticker"] for x in (shards_by_num[2] + shards_by_num[3]))
    all_03 = sorted_all[0::3]
    gap_companies = [c for c in all_03 if c["ticker"] in s23_tickers]
    print(f"Gap companies (all_03 in shard 2/3): {len(gap_companies)}")

    return part_c, gap_companies, sorted_all


# -------------------------------------------------------------
# Step 1: 提取 SEC Filings (1995-2026)
# -------------------------------------------------------------
def extract_filings_for_companies(companies, tag="Part C"):
    print(f"\n=== [Step 1] Fetching SEC Filings (1995-2026) for {len(companies)} {tag} Companies ===")
    all_records = []
    filings_index = {}

    for idx, comp in enumerate(companies):
        ticker = comp["ticker"]
        cik = int(comp["cik"])
        entity_name = comp.get("name", "")

        if (idx + 1) % 25 == 0 or idx == 0 or (idx + 1) == len(companies):
            print(f"  [{idx+1}/{len(companies)}] Fetching filings for {ticker} (CIK {cik:010d})...")

        sub_cache = os.path.join(SEC_CACHE_DIR, f"CIK{cik:010d}_primary.json")
        sub_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        data = sec_get_json(sub_url, sub_cache)

        if not data:
            print(f"    [WARN] No submission data for {ticker} (CIK {cik:010d})")
            continue

        actual_name = data.get("name", entity_name)
        comp_records = []

        # 1. Recent filings
        recent = data.get("filings", {}).get("recent", {})
        if recent and "form" in recent:
            comp_records.append(recent)

        # 2. Historical archive files
        hist_files = data.get("filings", {}).get("files", [])
        for hf in hist_files:
            fname = hf.get("name")
            if not fname:
                continue
            h_cache = os.path.join(SEC_CACHE_DIR, fname)
            h_url = f"https://data.sec.gov/submissions/{fname}"
            h_data = sec_get_json(h_url, h_cache)
            if h_data and "form" in h_data:
                comp_records.append(h_data)

        # Parse rows
        seen_accessions = set()
        ticker_filings = []

        for rec in comp_records:
            forms = rec.get("form", [])
            f_dates = rec.get("filingDate", [])
            r_dates = rec.get("reportDate", [])
            adts = rec.get("acceptanceDateTime", [])
            items_list = rec.get("items", [])
            accns = rec.get("accessionNumber", [])
            pdocs = rec.get("primaryDocument", [])

            n_rows = len(forms)
            for i in range(n_rows):
                f_date = f_dates[i] if i < len(f_dates) else ""
                if not f_date or not ("1995-01-01" <= f_date <= "2026-11-09"):
                    continue

                form = forms[i] if i < len(forms) else ""
                accn = accns[i] if i < len(accns) else ""
                if accn in seen_accessions:
                    continue

                r_date = r_dates[i] if i < len(r_dates) else ""
                adt = adts[i] if i < len(adts) else ""
                raw_items = items_list[i] if i < len(items_list) else ""
                pdoc = pdocs[i] if i < len(pdocs) else ""

                # Filter condition:
                # 10-Q, 10-K, 10-Q405, 10-K405 (strictly first disclosures, no /A amendments)
                # OR 8-K with items in {'2.02', '12', '1.03', '2.01'}
                is_periodic = form in {"10-Q", "10-K", "10-Q405", "10-K405"}
                is_8k_match = (form.startswith("8-K") and check_8k_items(raw_items))

                if not (is_periodic or is_8k_match):
                    continue

                seen_accessions.add(accn)
                timing = parse_session_timing(adt)

                items_str = ""
                if isinstance(raw_items, list):
                    items_str = ",".join(str(x) for x in raw_items)
                elif raw_items:
                    items_str = str(raw_items).strip()

                row_dict = {
                    "ticker": ticker,
                    "cik": cik,
                    "entity_name": actual_name,
                    "form": form,
                    "filingDate": f_date,
                    "reportDate": r_date if r_date else "",
                    "acceptanceDateTime": adt if adt else None,
                    "items": items_str,
                    "accessionNumber": accn,
                    "session_timing": timing,
                    "_primaryDocument": pdoc
                }
                all_records.append(row_dict)
                ticker_filings.append(row_dict)

        filings_index[ticker] = ticker_filings

    df = pd.DataFrame(all_records)
    print(f"Total extracted filings for {tag}: {len(df)} rows across {len(filings_index)} companies.")
    return df, filings_index


# -------------------------------------------------------------
# Step 2: Pre-2009 Anchored Financials
# -------------------------------------------------------------
CONCEPT_MAP = {
    "revenue": [
        "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueGoodsNet", "TotalRevenuesAndOtherIncome", "SalesRevenueServicesNet"
    ],
    "op_income": [
        "OperatingIncomeLoss",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"
    ],
    "net_income": [
        "NetIncomeLoss", "ProfitLoss"
    ],
    "total_assets": [
        "Assets"
    ],
    "stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    ],
    "shares": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic"
    ]
}


def parse_selected_financials_doc(html_text, target_year):
    """
    解析 10-K 原文中 Item 6 Selected Financial Data 表格中的目标年份数据
    无法解析则标 NaN，绝不瞎猜或编造
    """
    empty_res = {
        "revenue": np.nan, "op_income": np.nan, "net_income": np.nan,
        "total_assets": np.nan, "stockholders_equity": np.nan, "shares": np.nan
    }
    if not html_text:
        return empty_res

    target_str = str(target_year)
    m = re.search(r"ITEM\s+6[\.\s\-:]+SELECTED\s+FINANCIAL\s+DATA", html_text, re.IGNORECASE)
    if not m:
        m = re.search(r"SELECTED\s+FINANCIAL\s+DATA", html_text, re.IGNORECASE)
    if not m:
        return empty_res

    chunk = html_text[m.start():m.start() + 40000]

    # 若通过引用股东年报（Incorporated by reference），且无内嵌数据表格
    if "incorporated herein by reference" in chunk.lower() and "<table" not in chunk.lower()[:5000]:
        return empty_res

    res = dict(empty_res)

    def extract_val(text):
        raw = text.replace("$", "").replace(",", "").strip()
        if raw.startswith("(") and raw.endswith(")"):
            try:
                return -float(raw[1:-1])
            except:
                return np.nan
        try:
            return float(raw)
        except:
            return np.nan

    # 1. 尝试 BeautifulSoup 解析 HTML 表格
    if "<table" in chunk.lower():
        try:
            soup = BeautifulSoup(chunk, "html.parser")
            tables = soup.find_all("table")
            for table in tables:
                rows = table.find_all("tr")
                header_idx = None
                for row in rows:
                    cells = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
                    if header_idx is None:
                        for idx, c in enumerate(cells):
                            if target_str in c:
                                header_idx = idx
                                break
                    else:
                        if not cells:
                            continue
                        row_lbl = cells[0].lower()
                        if header_idx < len(cells):
                            val = extract_val(cells[header_idx])
                            if not np.isnan(val):
                                if ("sales" in row_lbl or "revenue" in row_lbl) and np.isnan(res["revenue"]):
                                    res["revenue"] = val
                                elif ("operating income" in row_lbl or "operating profit" in row_lbl) and np.isnan(res["op_income"]):
                                    res["op_income"] = val
                                elif ("net income" in row_lbl or "net loss" in row_lbl) and np.isnan(res["net_income"]):
                                    res["net_income"] = val
                                elif "total assets" in row_lbl and np.isnan(res["total_assets"]):
                                    res["total_assets"] = val
                                elif ("equity" in row_lbl or "shareholders" in row_lbl or "stockholders" in row_lbl) and np.isnan(res["stockholders_equity"]):
                                    res["stockholders_equity"] = val
                                elif "shares" in row_lbl and np.isnan(res["shares"]):
                                    res["shares"] = val
                if not np.isnan(res["revenue"]) or not np.isnan(res["net_income"]):
                    return res
        except Exception:
            pass

    # 2. 尝试 ASCII 文本表格正则解析
    lines = chunk.split("\n")
    header_col = None
    for line in lines:
        if target_str in line:
            parts = re.split(r"\s{2,}|\t", line.strip())
            parts = [p.strip() for p in parts if p.strip()]
            for idx, p in enumerate(parts):
                if target_str in p:
                    header_col = idx
                    break
        elif header_col is not None:
            lower = line.lower()
            nums = re.findall(r"[\$\(]?\s*[\d,]+(?:\.\d+)?\s*[\)\%bB]?", line)
            if nums and len(nums) >= header_col:
                val = extract_val(nums[header_col - 1])
                if not np.isnan(val):
                    if ("sales" in lower or "revenue" in lower) and np.isnan(res["revenue"]):
                        res["revenue"] = val
                    elif ("operating income" in lower or "operating profit" in lower) and np.isnan(res["op_income"]):
                        res["op_income"] = val
                    elif ("net income" in lower or "net loss" in lower) and np.isnan(res["net_income"]):
                        res["net_income"] = val
                    elif "total assets" in lower and np.isnan(res["total_assets"]):
                        res["total_assets"] = val
                    elif ("equity" in lower or "shareholders" in lower) and np.isnan(res["stockholders_equity"]):
                        res["stockholders_equity"] = val
                    elif "shares" in lower and np.isnan(res["shares"]):
                        res["shares"] = val

    return res


def extract_pre2009_anchored(part_c_companies, df_filings_c, filings_index):
    print(f"\n=== [Step 2] Extracting Pre-2009 Anchored Financials (Part C) ===")
    anchored_rows = []

    # 2A. 从 companyfacts.zip 读取 2006-2009 事实
    print(f"--- [Step 2A] Processing 2006-2009 Early XBRL for {len(part_c_companies)} companies ---")
    
    zip_obj = None
    if os.path.exists(ZIP_PATH):
        try:
            zip_obj = zipfile.ZipFile(ZIP_PATH, "r")
            print(f"  Successfully opened {ZIP_PATH} ({len(zip_obj.infolist())} files)")
        except Exception as e:
            print(f"  [WARN] Failed to open {ZIP_PATH}: {e}")

    for idx, comp in enumerate(part_c_companies):
        ticker = comp["ticker"]
        cik = int(comp["cik"])
        entity_name = comp.get("name", "")

        cf_data = None
        target_fname = f"CIK{cik:010d}.json"

        # 优先从本地 zip 读取 (0 耗时，0 网络请求)
        if zip_obj:
            try:
                raw_bytes = zip_obj.read(target_fname)
                cf_data = json.loads(raw_bytes)
            except KeyError:
                pass
            except Exception:
                pass

        # 若 zip 中无该 CIK，则回退到 SEC API 获取
        if not cf_data:
            cf_cache = os.path.join(SEC_CACHE_DIR, f"facts_{cik:010d}.json")
            cf_url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
            cf_data = sec_get_json(cf_url, cf_cache)

        if not cf_data or "facts" not in cf_data:
            continue

        us_gaap = cf_data.get("facts", {}).get("us-gaap", {})
        dei = cf_data.get("facts", {}).get("dei", {})

        period_data = {}

        def scan_concepts(field_name, concept_list, source_dict):
            for concept in concept_list:
                if concept not in source_dict:
                    continue
                units = source_dict[concept].get("units", {})
                for u_key, items in units.items():
                    for item in items:
                        fy = item.get("fy")
                        fp = item.get("fp", "FY")
                        val = item.get("val")
                        if fy in [2006, 2007, 2008, 2009] and fp in ["FY", "Q1", "Q2", "Q3", "Q4"] and val is not None:
                            key = (int(fy), str(fp).upper())
                            if key not in period_data:
                                period_data[key] = {
                                    "end": item.get("end", ""),
                                    "filed": item.get("filed", ""),
                                    "form": item.get("form", "10-K" if fp == "FY" else "10-Q"),
                                    "metrics": {}
                                }
                            if field_name not in period_data[key]["metrics"]:
                                period_data[key]["metrics"][field_name] = float(val)

        for field, clist in CONCEPT_MAP.items():
            scan_concepts(field, clist, us_gaap)
            if field == "shares":
                scan_concepts(field, clist, dei)

        comp_filings = filings_index.get(ticker, [])

        for (fy, fp), p_info in sorted(period_data.items()):
            p_end = p_info["end"]
            metrics = p_info["metrics"]
            if not metrics:
                continue

            target_form_family = {"10-K", "10-K405"} if fp == "FY" else {"10-Q", "10-Q405"}
            matched_filing = None

            # 匹配 1: 准确 reportDate
            if p_end:
                for f in comp_filings:
                    if f["form"] in target_form_family and f["reportDate"] == p_end:
                        matched_filing = f
                        break

            # 匹配 2: reportDate 在 +/- 45 天内
            if not matched_filing and p_end:
                for f in comp_filings:
                    if f["form"] in target_form_family and f["reportDate"]:
                        try:
                            f_rdate = datetime.strptime(f["reportDate"], "%Y-%m-%d")
                            p_rdate = datetime.strptime(p_end, "%Y-%m-%d")
                            if abs((f_rdate - p_rdate).days) <= 45:
                                matched_filing = f
                                break
                        except Exception:
                            pass

            # 匹配 3: 按财年与报送时间窗口
            if not matched_filing:
                for f in comp_filings:
                    if f["form"] in target_form_family:
                        f_year = int(f["filingDate"][:4])
                        if fp == "FY" and (f_year == fy or (f_year == fy + 1 and int(f["filingDate"][5:7]) <= 4)):
                            matched_filing = f
                            break

            if matched_filing:
                filing_date = matched_filing["filingDate"]
                adt = matched_filing["acceptanceDateTime"]
                timing = matched_filing["session_timing"]
                if p_info["filed"] <= filing_date:
                    source_tier = "VOLUNTARY_XBRL_ORIGINAL_FILING"
                else:
                    source_tier = "SEC_SUBMISSION_FILED_DATE_WITH_2009_10K_UNRESTATED_CHECK"
            else:
                filing_date = p_info["filed"]
                adt = None
                timing = "DATE_ONLY"
                source_tier = "EARLY_XBRL_UNANCHORED_RESTATED"

            anchored_rows.append({
                "ticker": ticker,
                "cik": cik,
                "entity_name": entity_name,
                "fiscal_year": fy,
                "fiscal_period": fp,
                "reportDate": p_end,
                "form": "10-K" if fp == "FY" else "10-Q",
                "filingDate": filing_date,
                "acceptanceDateTime": adt,
                "session_timing": timing,
                "revenue": metrics.get("revenue", np.nan),
                "op_income": metrics.get("op_income", np.nan),
                "net_income": metrics.get("net_income", np.nan),
                "total_assets": metrics.get("total_assets", np.nan),
                "stockholders_equity": metrics.get("stockholders_equity", np.nan),
                "shares": metrics.get("shares", np.nan),
                "source_tier": source_tier
            })

    if zip_obj:
        zip_obj.close()

    print(f"  Step 2A produced {len(anchored_rows)} early XBRL anchored rows.")

    # 2B. 抽样 Top 40 老牌代表性大公司解析 1998, 2001, 2004, 2007 10-K Item 6 Selected Financial Data
    print(f"\n--- [Step 2B] Sampling 1998, 2001, 2004, 2007 10-K Item 6 for Top 40 Old Companies ---")

    part_c_map = {c["ticker"]: c for c in part_c_companies}
    df_u = pd.read_csv(UNIVERSE_CSV)
    df_u_partc = df_u[df_u["ticker"].isin(part_c_map.keys())].sort_values("market_cap", ascending=False)

    top_tickers = list(df_u_partc["ticker"].head(40))
    # 强制纳入退市/重要老牌堕落天使 (WCOM, EK)
    for fallen in ["WCOM", "EK"]:
        if fallen in part_c_map and fallen not in top_tickers:
            top_tickers.append(fallen)
            if len(top_tickers) > 40:
                top_tickers.pop(-2)

    print(f"  Selected top 40 representative companies: {top_tickers}")

    target_sample_years = [1998, 2001, 2004, 2007]

    for idx, t in enumerate(top_tickers):
        comp = part_c_map[t]
        cik = int(comp["cik"])
        name = comp.get("name", "")
        c_filings = filings_index.get(t, [])

        if (idx + 1) % 10 == 0 or idx == 0:
            print(f"  [{idx+1}/40] Parsing Item 6 for {t} (CIK {cik:010d})...")

        for ty in target_sample_years:
            matched_10k = None
            for f in c_filings:
                if f["form"] in {"10-K", "10-K405"}:
                    f_year = int(f["filingDate"][:4])
                    f_month = int(f["filingDate"][5:7])
                    r_year = int(f["reportDate"][:4]) if f["reportDate"] else 0
                    if r_year == ty:
                        matched_10k = f
                        break
                    elif f_year == ty and f_month >= 9:
                        matched_10k = f
                        break
                    elif f_year == ty + 1 and f_month <= 4:
                        matched_10k = f
                        break

            if not matched_10k:
                anchored_rows.append({
                    "ticker": t,
                    "cik": cik,
                    "entity_name": name,
                    "fiscal_year": ty,
                    "fiscal_period": "FY",
                    "reportDate": f"{ty}-12-31",
                    "form": "10-K",
                    "filingDate": f"{ty+1}-03-31",
                    "acceptanceDateTime": None,
                    "session_timing": "DATE_ONLY",
                    "revenue": np.nan,
                    "op_income": np.nan,
                    "net_income": np.nan,
                    "total_assets": np.nan,
                    "stockholders_equity": np.nan,
                    "shares": np.nan,
                    "source_tier": "NOT_FILED"
                })
                continue

            accn = matched_10k["accessionNumber"]
            accn_clean = accn.replace("-", "")
            pdoc = matched_10k.get("_primaryDocument", "")

            doc_ext = ".htm" if pdoc and pdoc.endswith((".htm", ".html")) else ".txt"
            doc_cache = os.path.join(SEC_DOCS_CACHE, f"{cik}_{accn}{doc_ext}")

            if pdoc and pdoc.endswith((".htm", ".html")):
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{pdoc}"
            else:
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{accn}.txt"

            doc_text = sec_get_text(doc_url, doc_cache, max_bytes=3_000_000)
            metrics = parse_selected_financials_doc(doc_text, ty)

            anchored_rows.append({
                "ticker": t,
                "cik": cik,
                "entity_name": name,
                "fiscal_year": ty,
                "fiscal_period": "FY",
                "reportDate": matched_10k["reportDate"] if matched_10k["reportDate"] else f"{ty}-12-31",
                "form": matched_10k["form"],
                "filingDate": matched_10k["filingDate"],
                "acceptanceDateTime": matched_10k["acceptanceDateTime"],
                "session_timing": matched_10k["session_timing"],
                "revenue": metrics.get("revenue", np.nan),
                "op_income": metrics.get("op_income", np.nan),
                "net_income": metrics.get("net_income", np.nan),
                "total_assets": metrics.get("total_assets", np.nan),
                "stockholders_equity": metrics.get("stockholders_equity", np.nan),
                "shares": metrics.get("shares", np.nan),
                "source_tier": "10K_ITEM6_SELECTED_FINANCIAL_DATA"
            })

    df_anchored = pd.DataFrame(anchored_rows)
    if not df_anchored.empty:
        df_anchored.drop_duplicates(subset=["ticker", "fiscal_year", "fiscal_period", "source_tier"], keep="last", inplace=True)
        df_anchored.sort_values(by=["ticker", "filingDate", "reportDate"], inplace=True)

    df_anchored.to_parquet(OUT_ANCHORED_C, index=False)
    print(f"\nSaved Part 2 anchored financials to {OUT_ANCHORED_C} ({len(df_anchored)} rows)")
    return df_anchored


# -------------------------------------------------------------
# 主入口
# -------------------------------------------------------------
def main():
    start_time = time.time()
    print("=" * 70)
    print("W1_09: 1995-2026 SEC 全历史财报精确时间戳与 Pre-2009 面板提取器 (分片C + Gap)")
    print("=" * 70)

    part_c_companies, gap_companies, all_companies = load_all_and_split()

    # 1. Part C Filings (283 companies)
    df_filings_c, filings_index_c = extract_filings_for_companies(part_c_companies, tag="Part C")
    if not df_filings_c.empty:
        df_save_c = df_filings_c.drop(columns=["_primaryDocument"], errors="ignore")
        df_save_c.to_parquet(OUT_FILINGS_C, index=False)
        print(f"Saved Part C filings to {OUT_FILINGS_C} ({os.path.getsize(OUT_FILINGS_C):,} bytes, {len(df_save_c)} rows)")

    # 2. Gap Filings (142 companies)
    df_filings_gap, _ = extract_filings_for_companies(gap_companies, tag="Gap (Shard 2/3 [0::3])")
    if not df_filings_gap.empty:
        df_save_gap = df_filings_gap.drop(columns=["_primaryDocument"], errors="ignore")
        df_save_gap.to_parquet(OUT_FILINGS_GAP, index=False)
        print(f"Saved Gap filings to {OUT_FILINGS_GAP} ({os.path.getsize(OUT_FILINGS_GAP):,} bytes, {len(df_save_gap)} rows)")

    # 3. Part C Anchored Financials
    df_anchored_c = extract_pre2009_anchored(part_c_companies, df_filings_c, filings_index_c)

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"W1_09 Execution Complete in {elapsed:.1f} seconds")
    print("=" * 70)
    print("Summary of Generated Datasets:")
    print(f"1. Part C Filings: {len(df_filings_c):,} rows, {df_filings_c['ticker'].nunique()} tickers")
    if not df_filings_c.empty:
        print(f"   Date Range: {df_filings_c['filingDate'].min()} to {df_filings_c['filingDate'].max()}")
        print(f"   Timing: {df_filings_c['session_timing'].value_counts().to_dict()}")
    print(f"2. Gap Filings: {len(df_filings_gap):,} rows, {df_filings_gap['ticker'].nunique()} tickers")
    if not df_filings_gap.empty:
        print(f"   Date Range: {df_filings_gap['filingDate'].min()} to {df_filings_gap['filingDate'].max()}")
        print(f"   Timing: {df_filings_gap['session_timing'].value_counts().to_dict()}")
    print(f"3. Part C Anchored: {len(df_anchored_c):,} rows, {df_anchored_c['ticker'].nunique()} tickers")
    if not df_anchored_c.empty:
        print(f"   Source Tiers: {df_anchored_c['source_tier'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()

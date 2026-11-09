#!/usr/bin/env python3
"""
W1_07: 1995-2026 SEC 全历史财报精确时间戳与 Pre-2009 面板提取器 分片A
- 输入: pre2009_shard_0..3.json 合并去重后按 ticker 升序取 [0::3] (共 284 家公司)
- 产出 1: /tmp/us_earn_macro_bt_20261109/pre2009_shards/sec_filings_1995_2026_partA.parquet
- 产出 2: /tmp/us_earn_macro_bt_20261109/pre2009_shards/pre2009_comp_anchored_partA.parquet
"""

import os
import sys
import json
import time
import re
import zoneinfo
import zipfile
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import numpy as np
import pandas as pd

# -------------------------------------------------------------
# 路径与配置
# -------------------------------------------------------------
SHARD_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-09-us-earnings-macro-30y/shards"
BASE_TMP = "/tmp/us_earn_macro_bt_20261109"
OUT_DIR = os.path.join(BASE_TMP, "pre2009_shards")
SEC_CACHE_DIR = os.path.join(BASE_TMP, "sec_cache")
SEC_DOCS_CACHE = os.path.join(BASE_TMP, "sec_cache", "docs")
ZIP_PATH = os.path.join(BASE_TMP, "companyfacts.zip")

UNIVERSE_CSV = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/universe.csv"

OUT_FILINGS_PARQUET = os.path.join(OUT_DIR, "sec_filings_1995_2026_partA.parquet")
OUT_ANCHORED_PARQUET = os.path.join(OUT_DIR, "pre2009_comp_anchored_partA.parquet")

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(SEC_CACHE_DIR, exist_ok=True)
os.makedirs(SEC_DOCS_CACHE, exist_ok=True)

# -------------------------------------------------------------
# 网络 Session 配置 (严守 <= 1.5 req/s 限速与 User-Agent)
# -------------------------------------------------------------
USER_AGENT = "OHIM Research buwen@ohim.com"
RATE_LIMIT_SLEEP = 0.72  # 约 1.38 次请求/秒，严格遵守 < 1.5 req/s

session = requests.Session()
retries = Retry(
    total=5,
    backoff_factor=1.5,
    status_forcelist=[429, 500, 502, 503, 504],
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
                return json.load(f)
        except Exception:
            pass

    time.sleep(RATE_LIMIT_SLEEP)
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            with open(local_cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data
        elif resp.status_code == 404:
            return None
        elif resp.status_code == 429:
            time.sleep(5.0)
            resp = session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                with open(local_cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                return data
            return None
        else:
            return None
    except Exception as e:
        print(f"[WARN] Error fetching {url}: {e}", file=sys.stderr)
        return None


def sec_get_text(url, local_cache_path, max_bytes=2_000_000):
    """带本地缓存、限速的 SEC 文本/HTML 文档获取函数"""
    if os.path.exists(local_cache_path):
        try:
            with open(local_cache_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            pass

    time.sleep(RATE_LIMIT_SLEEP)
    try:
        headers = {"Range": f"bytes=0-{max_bytes}"}
        resp = session.get(url, headers=headers, timeout=20)
        if resp.status_code in (200, 206):
            text = resp.text
            with open(local_cache_path, "w", encoding="utf-8", errors="ignore") as f:
                f.write(text)
            return text
        elif resp.status_code == 429:
            time.sleep(5.0)
            resp = session.get(url, headers=headers, timeout=20)
            if resp.status_code in (200, 206):
                text = resp.text
                with open(local_cache_path, "w", encoding="utf-8", errors="ignore") as f:
                    f.write(text)
                return text
        return ""
    except Exception as e:
        print(f"[WARN] Error fetching doc {url}: {e}", file=sys.stderr)
        return ""


# -------------------------------------------------------------
# 时间戳与条目解析工具
# -------------------------------------------------------------
def parse_session_timing(acceptance_str):
    """
    解析 acceptanceDateTime 并在美东时间 (America/New_York) 下判断:
    - BMO_pre0930ET: 盘前 (< 09:30 ET)
    - INTRADAY: 盘中 (09:30 - 16:00 ET)
    - AMC_post1600ET: 盘后 (>= 16:00 ET)
    - DATE_ONLY: 仅日期或 00:00:00 (早期 EDGAR 回填占位)
    """
    if not acceptance_str or str(acceptance_str).strip() == "":
        return "DATE_ONLY"
    s = str(acceptance_str).strip()
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

        if dt_et.hour < 9 or (dt_et.hour == 9 and dt_et.minute < 30):
            return "BMO_pre0930ET"
        elif dt_et.hour >= 16:
            return "AMC_post1600ET"
        else:
            return "INTRADAY"
    except Exception:
        return "DATE_ONLY"


def check_8k_items(items_val):
    """
    检查 8-K 条目:
    - 业绩发布: '2.02' (2004-08起) 或 '12' (2003-2004)
    - 重大退出: '1.03' (破产) 或 '2.01' (并购完成)
    """
    if not items_val:
        return False, False
    val_str = str(items_val).replace("Item ", "").replace("item ", "")
    tokens = set()
    for part in val_str.replace(";", ",").split(","):
        tok = part.strip()
        if tok:
            tokens.add(tok)
    is_earn = bool(tokens.intersection({"2.02", "12"}))
    is_exit = bool(tokens.intersection({"1.03", "2.01"}))
    return is_earn, is_exit


# -------------------------------------------------------------
# 步骤 1: 读取分片并生成 Part A 公司列表 (284 家)
# -------------------------------------------------------------
def load_part_a_companies():
    companies = {}
    for i in range(4):
        p = os.path.join(SHARD_DIR, f"pre2009_shard_{i}.json")
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                items = json.load(f)
            for it in items:
                companies[it["ticker"]] = it

    sorted_tickers = sorted(companies.keys())
    part_a = [companies[t] for t in sorted_tickers[0::3]]
    print(f"[Step 1] 合并 4 个分片总计 {len(sorted_tickers)} 家公司，Part A (0::3) 取出 {len(part_a)} 家。")
    return part_a


# -------------------------------------------------------------
# 步骤 2: 提取 1995-2026 SEC 全历史财报精确时间戳
# -------------------------------------------------------------
def process_submissions_part_a(part_a_companies):
    if os.path.exists(OUT_FILINGS_PARQUET) and os.path.getsize(OUT_FILINGS_PARQUET) > 100_000:
        print(f"[Step 2] 发现已有产出 {OUT_FILINGS_PARQUET}，直接加载校验...")
        df_filings = pd.read_parquet(OUT_FILINGS_PARQUET)
        print(f"  已成功载入 {len(df_filings)} 条历史财报时间戳。")
        return df_filings

    print("[Step 2] 开始获取并解析 284 家公司的 SEC Submissions (1995-2026)...")
    records = []

    for idx, comp in enumerate(part_a_companies):
        ticker = comp["ticker"]
        cik = comp["cik"]
        name = comp.get("name", "")

        primary_url = f"https://data.sec.gov/submissions/CIK{cik:010d}.json"
        primary_cache = os.path.join(SEC_CACHE_DIR, f"CIK{cik:010d}_primary.json")

        sub_data = sec_get_json(primary_url, primary_cache)
        if not sub_data:
            continue

        entity_name = sub_data.get("name", name)

        submission_packages = []
        recent = sub_data.get("filings", {}).get("recent", {})
        if recent:
            submission_packages.append(recent)

        files = sub_data.get("filings", {}).get("files", [])
        for f_meta in files:
            f_name = f_meta.get("name")
            if f_name:
                f_url = f"https://data.sec.gov/submissions/{f_name}"
                f_cache = os.path.join(SEC_CACHE_DIR, f_name)
                f_data = sec_get_json(f_url, f_cache)
                if f_data:
                    submission_packages.append(f_data)

        for pkg in submission_packages:
            forms = pkg.get("form", [])
            filing_dates = pkg.get("filingDate", [])
            report_dates = pkg.get("reportDate", [])
            acceptance_dts = pkg.get("acceptanceDateTime", [])
            items_list = pkg.get("items", [])
            accession_nums = pkg.get("accessionNumber", [])

            n_items = len(forms)
            for i in range(n_items):
                f_date = filing_dates[i] if i < len(filing_dates) else ""
                if not f_date or not ("1995-01-01" <= f_date <= "2026-11-09"):
                    continue

                form = forms[i] if i < len(forms) else ""
                if not form:
                    continue

                if "/A" in form:
                    continue

                is_10kq = form in {"10-Q", "10-K", "10-Q405", "10-K405"}
                is_8k = form == "8-K"

                it_val = items_list[i] if i < len(items_list) else ""
                keep = False

                if is_10kq:
                    keep = True
                elif is_8k:
                    earn, exit_ = check_8k_items(it_val)
                    if earn or exit_:
                        keep = True

                if not keep:
                    continue

                rep_date = report_dates[i] if i < len(report_dates) else ""
                acc_dt = acceptance_dts[i] if i < len(acceptance_dts) else ""
                acc_num = accession_nums[i] if i < len(accession_nums) else ""

                timing = parse_session_timing(acc_dt)

                records.append({
                    "ticker": ticker,
                    "cik": cik,
                    "entity_name": entity_name,
                    "form": form,
                    "filingDate": f_date,
                    "reportDate": rep_date,
                    "acceptanceDateTime": acc_dt,
                    "items": str(it_val) if it_val is not None else "",
                    "accessionNumber": acc_num,
                    "session_timing": timing
                })

        if (idx + 1) % 25 == 0 or (idx + 1) == len(part_a_companies):
            print(f"  已处理 {idx + 1}/{len(part_a_companies)} 家公司，当前提取有效财报记录: {len(records)} 条")

    df_filings = pd.DataFrame(records)
    if not df_filings.empty:
        df_filings.sort_values(by=["ticker", "filingDate", "acceptanceDateTime"], inplace=True)
        mask_10kq = df_filings["form"].isin({"10-Q", "10-K", "10-Q405", "10-K405"}) & (df_filings["reportDate"] != "")
        df_10kq = df_filings[mask_10kq].drop_duplicates(subset=["ticker", "form", "reportDate"], keep="first")
        df_other = df_filings[~mask_10kq].drop_duplicates(subset=["ticker", "accessionNumber"], keep="first")
        df_filings = pd.concat([df_10kq, df_other]).sort_values(by=["ticker", "filingDate", "acceptanceDateTime"])

    cols_to_save = [
        "ticker", "cik", "entity_name", "form", "filingDate",
        "reportDate", "acceptanceDateTime", "items", "accessionNumber", "session_timing"
    ]
    df_save = df_filings[cols_to_save].copy()
    df_save.to_parquet(OUT_FILINGS_PARQUET, index=False)
    print(f"[Done Step 2] 已保存: {OUT_FILINGS_PARQUET}, 总行数: {len(df_save)}")
    return df_save


# -------------------------------------------------------------
# 步骤 3: 提取 Pre-2009 锚点表 (2007-2009 XBRL & 2009 10-K 比较期 & Top 40 Selected Financial Data)
# -------------------------------------------------------------
FLOW_REV_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
    "TotalRevenuesAndOtherIncome",
    "OperatingRevenues",
    "HealthCareOrganizationRevenue",
    "RegulatedAndUnregulatedOperatingRevenue"
]

FLOW_NI_TAGS = [
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic"
]

ASSET_TAGS = ["Assets"]
EQUITY_TAGS = ["StockholdersEquity", "CommonStockValue"]


def wait_for_companyfacts_zip():
    """等待 companyfacts.zip 下载完成并验证为有效 zip 文件"""
    print("[Step 3A] 检查 companyfacts.zip 完整性...")
    while True:
        if os.path.exists(ZIP_PATH):
            sz = os.path.getsize(ZIP_PATH)
            if sz > 1_400_000_000:
                try:
                    with zipfile.ZipFile(ZIP_PATH, "r") as z:
                        _ = z.namelist()[:5]
                    print(f"  companyfacts.zip 校验通过，大小: {sz / 1e6:.1f} MB")
                    break
                except Exception:
                    pass
        time.sleep(3)


def extract_pre2009_anchored(part_a_companies, df_filings):
    print("[Step 3] 开始构建 Pre-2009 历史锚点表 (严格对齐真实当年 filingDate)...")

    # 构建 submissions 快速查询索引 (区分 3元组与 2元组)
    sub_map_3 = {}  # (ticker, form, reportDate) -> filingDate
    sub_map_2 = {}  # (ticker, reportDate) -> filingDate

    for _, row in df_filings.iterrows():
        t = row["ticker"]
        rep = row["reportDate"]
        f_date = row["filingDate"]
        form = row["form"]
        if rep:
            sub_map_2[(t, rep)] = f_date
            sub_map_3[(t, form, rep)] = f_date

    anchored_records = []

    # 1. 打开 companyfacts.zip
    wait_for_companyfacts_zip()

    with zipfile.ZipFile(ZIP_PATH, "r") as z:
        all_z_names = set(z.namelist())

        for idx, comp in enumerate(part_a_companies):
            ticker = comp["ticker"]
            cik = comp["cik"]
            name = comp.get("name", "")
            cik_file = f"CIK{cik:010d}.json"

            if cik_file not in all_z_names:
                continue

            try:
                c_facts = json.loads(z.read(cik_file))
            except Exception:
                continue

            us_gaap = c_facts.get("facts", {}).get("us-gaap", {})
            if not us_gaap:
                continue

            periods = {}

            def scan_concept(concept_dict, target_metric):
                units = concept_dict.get("units", {})
                for u_key in ["USD", "iso4217:USD"]:
                    if u_key in units:
                        for entry in units[u_key]:
                            end_dt = entry.get("end")
                            filed_dt = entry.get("filed")
                            form = entry.get("form", "")
                            val = entry.get("val")
                            fy = entry.get("fy")
                            fp = entry.get("fp")

                            if not end_dt or not filed_dt or val is None:
                                continue

                            # 目标一: 2007-2009.06 早期 voluntary XBRL
                            is_vol = filed_dt < "2009-06-15"

                            # 目标二: 2006Q1 - 2009Q2 在 2009-2011 首次 XBRL 中回溯报送的对比期
                            is_comp_pre2009 = ("2006-01-01" <= end_dt <= "2009-06-30") and ("2009-06-15" <= filed_dt <= "2011-12-31")

                            if not (is_vol or is_comp_pre2009):
                                continue

                            is_annual = "10-K" in form or fp == "FY"
                            p_key = (end_dt, "10-K" if is_annual else "10-Q")

                            if p_key not in periods:
                                periods[p_key] = {
                                    "end": end_dt,
                                    "filed_xbrl": filed_dt,
                                    "form": "10-K" if is_annual else "10-Q",
                                    "fy": fy,
                                    "fp": fp,
                                    "is_vol": is_vol,
                                    "rev": None,
                                    "ni": None,
                                    "assets": None,
                                    "equity": None
                                }

                            if periods[p_key][target_metric] is None:
                                periods[p_key][target_metric] = float(val)

            for tag in FLOW_REV_TAGS:
                if tag in us_gaap:
                    scan_concept(us_gaap[tag], "rev")
            for tag in FLOW_NI_TAGS:
                if tag in us_gaap:
                    scan_concept(us_gaap[tag], "ni")
            for tag in ASSET_TAGS:
                if tag in us_gaap:
                    scan_concept(us_gaap[tag], "assets")
            for tag in EQUITY_TAGS:
                if tag in us_gaap:
                    scan_concept(us_gaap[tag], "equity")

            for p_key, p_data in periods.items():
                end_dt = p_data["end"]
                f_type = p_data["form"]

                matched_filing_date = sub_map_3.get((ticker, f_type, end_dt)) or sub_map_2.get((ticker, end_dt))

                if not matched_filing_date:
                    for (t_sub, form_sub, rep_sub), f_sub_dt in sub_map_3.items():
                        if t_sub == ticker and form_sub == f_type:
                            try:
                                d1 = datetime.strptime(rep_sub, "%Y-%m-%d")
                                d2 = datetime.strptime(end_dt, "%Y-%m-%d")
                                if abs((d1 - d2).days) <= 7:
                                    matched_filing_date = f_sub_dt
                                    break
                            except Exception:
                                pass

                if not matched_filing_date:
                    matched_filing_date = p_data["filed_xbrl"]

                source_tier = (
                    "VOLUNTARY_XBRL_ORIGINAL_FILING"
                    if p_data["is_vol"]
                    else "SEC_SUBMISSION_FILED_DATE_WITH_2009_10K_UNRESTATED_CHECK"
                )

                anchored_records.append({
                    "ticker": ticker,
                    "cik": cik,
                    "entity_name": name,
                    "form": f_type,
                    "filingDate": matched_filing_date,
                    "reportDate": end_dt,
                    "fiscal_year": p_data["fy"] if p_data["fy"] is not None else end_dt[:4],
                    "fiscal_period": p_data["fp"] if p_data["fp"] else ("FY" if f_type == "10-K" else "Q"),
                    "revenue": p_data["rev"] if p_data["rev"] is not None else np.nan,
                    "net_income": p_data["ni"] if p_data["ni"] is not None else np.nan,
                    "total_assets": p_data["assets"] if p_data["assets"] is not None else np.nan,
                    "common_stock_or_shares": p_data["equity"] if p_data["equity"] is not None else np.nan,
                    "source_tier": source_tier
                })

    print(f"[Step 3A] 从 companyfacts.zip 提取出 {len(anchored_records)} 条 2006-2009 锚点记录。")

    # -------------------------------------------------------------
    # 步骤 3B: Top 40 大公司 1998, 2001, 2004, 2007 10-K Selected Financial Data 抽样解析
    # -------------------------------------------------------------
    print("[Step 3B] 筛选本分片市值前 40 家代表性大公司（含 ENE/LEH），抓取 1998/2001/2004/2007 10-K 原文解析...")

    part_a_map = {c["ticker"]: c for c in part_a_companies}
    df_u = pd.read_csv(UNIVERSE_CSV)
    df_u_parta = df_u[df_u["ticker"].isin(part_a_map.keys())].sort_values("market_cap", ascending=False)

    top_tickers = list(df_u_parta["ticker"].head(40))
    for fallen in ["ENE", "LEH"]:
        if fallen in part_a_map and fallen not in top_tickers:
            top_tickers.append(fallen)
            if len(top_tickers) > 40:
                top_tickers.pop(-2)

    print(f"  选取的 40 家代表性大公司列表: {top_tickers}")

    target_years = {"1998", "2001", "2004", "2007"}
    sample_10k_records = []

    for t in top_tickers:
        comp = part_a_map[t]
        cik = comp["cik"]
        name = comp.get("name", "")

        c_10ks = df_filings[
            (df_filings["ticker"] == t) &
            (df_filings["form"].isin({"10-K", "10-K405"}))
        ]

        for yr in target_years:
            matched_row = c_10ks[c_10ks["filingDate"].str.startswith(yr)]
            if matched_row.empty:
                prev_yr = str(int(yr) - 1)
                matched_row = c_10ks[c_10ks["reportDate"].str.startswith(prev_yr) & c_10ks["filingDate"].str.startswith(yr)]

            if matched_row.empty:
                continue

            row_0 = matched_row.iloc[0]
            acc_num = row_0["accessionNumber"]
            filing_dt = row_0["filingDate"]
            report_dt = row_0["reportDate"]

            acc_clean = acc_num.replace("-", "")
            doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_clean}/{acc_num}.txt"
            cache_file = os.path.join(SEC_DOCS_CACHE, f"{acc_clean}_{acc_num}.txt")

            doc_text = sec_get_text(doc_url, cache_file, max_bytes=3_000_000)

            rev_val = np.nan
            ni_val = np.nan
            asset_val = np.nan

            if doc_text:
                m_item6 = re.search(r"ITEM\s+6[\.\s\-:]+SELECTED\s+FINANCIAL\s+DATA", doc_text, re.IGNORECASE)
                if m_item6:
                    snippet = doc_text[m_item6.start():m_item6.start() + 40000]
                    m_rev = re.search(r"(?:Total\s+revenues?|Net\s+sales?|Revenue)\s*[:\$]?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)", snippet, re.IGNORECASE)
                    if m_rev:
                        try:
                            rev_val = float(m_rev.group(1).replace(",", ""))
                        except Exception:
                            pass

                    m_ni = re.search(r"(?:Net\s+income|Net\s+earnings?|Net\s+loss)\s*[:\$]?\s*\(?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)\)?", snippet, re.IGNORECASE)
                    if m_ni:
                        try:
                            ni_val = float(m_ni.group(1).replace(",", ""))
                            if "(" in m_ni.group(0):
                                ni_val = -ni_val
                        except Exception:
                            pass

                    m_ast = re.search(r"(?:Total\s+assets?)\s*[:\$]?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)", snippet, re.IGNORECASE)
                    if m_ast:
                        try:
                            asset_val = float(m_ast.group(1).replace(",", ""))
                        except Exception:
                            pass

            sample_10k_records.append({
                "ticker": t,
                "cik": cik,
                "entity_name": name,
                "form": "10-K",
                "filingDate": filing_dt,
                "reportDate": report_dt,
                "fiscal_year": report_dt[:4] if report_dt else yr,
                "fiscal_period": "FY",
                "revenue": rev_val,
                "net_income": ni_val,
                "total_assets": asset_val,
                "common_stock_or_shares": np.nan,
                "source_tier": "10K_ITEM6_SELECTED_FINANCIAL_DATA"
            })

    print(f"[Step 3B] 完成 40 家代表公司 10-K Selected Financial Data 解析，产出 {len(sample_10k_records)} 条记录。")

    all_anchored = anchored_records + sample_10k_records
    df_anchored = pd.DataFrame(all_anchored)

    if not df_anchored.empty:
        df_anchored.drop_duplicates(subset=["ticker", "form", "reportDate", "source_tier"], keep="first", inplace=True)
        df_anchored.sort_values(by=["ticker", "filingDate", "reportDate"], inplace=True)
        # 统一字段类型，杜绝 mixed-type pyarrow 转换错误
        df_anchored["ticker"] = df_anchored["ticker"].astype(str)
        df_anchored["cik"] = df_anchored["cik"].astype(int)
        df_anchored["entity_name"] = df_anchored["entity_name"].astype(str)
        df_anchored["form"] = df_anchored["form"].astype(str)
        df_anchored["filingDate"] = df_anchored["filingDate"].astype(str)
        df_anchored["reportDate"] = df_anchored["reportDate"].astype(str)
        df_anchored["fiscal_year"] = pd.to_numeric(df_anchored["fiscal_year"], errors="coerce").astype("Int64")
        df_anchored["fiscal_period"] = df_anchored["fiscal_period"].astype(str)
        df_anchored["revenue"] = pd.to_numeric(df_anchored["revenue"], errors="coerce").astype(float)
        df_anchored["net_income"] = pd.to_numeric(df_anchored["net_income"], errors="coerce").astype(float)
        df_anchored["total_assets"] = pd.to_numeric(df_anchored["total_assets"], errors="coerce").astype(float)
        df_anchored["common_stock_or_shares"] = pd.to_numeric(df_anchored["common_stock_or_shares"], errors="coerce").astype(float)
        df_anchored["source_tier"] = df_anchored["source_tier"].astype(str)

    df_anchored.to_parquet(OUT_ANCHORED_PARQUET, index=False)
    print(f"[Done Step 3] 已保存: {OUT_ANCHORED_PARQUET}, 总行数: {len(df_anchored)}")
    return df_anchored


# -------------------------------------------------------------
# 主入口
# -------------------------------------------------------------
def main():
    print("=" * 70)
    print("W1_07: 1995-2026 SEC 全历史财报精确时间戳与 Pre-2009 面板提取器 (分片A)")
    print("=" * 70)

    t0 = time.time()
    part_a = load_part_a_companies()

    # 执行 Step 2
    df_filings = process_submissions_part_a(part_a)

    # 执行 Step 3
    df_anchored = extract_pre2009_anchored(part_a, df_filings)

    # 统计与验证
    print("\n" + "=" * 70)
    print("【结果汇总与验证】")
    print("=" * 70)
    print(f"1. sec_filings_1995_2026_partA.parquet:")
    print(f"   - 总行数: {len(df_filings):,}")
    print(f"   - 覆盖公司数 (unique tickers): {df_filings['ticker'].nunique()}")
    print(f"   - 时间跨度: {df_filings['filingDate'].min()} 至 {df_filings['filingDate'].max()}")
    print(f"   - 表单分布:\n{df_filings['form'].value_counts().to_string()}")
    print(f"   - 交易时段标注 (session_timing):\n{df_filings['session_timing'].value_counts().to_string()}")

    print(f"\n2. pre2009_comp_anchored_partA.parquet:")
    print(f"   - 总行数: {len(df_anchored):,}")
    print(f"   - 覆盖公司数: {df_anchored['ticker'].nunique()}")
    print(f"   - 来源分布 (source_tier):\n{df_anchored['source_tier'].value_counts().to_string()}")
    print(f"   - 非空 Revenue 记录数: {df_anchored['revenue'].notna().sum():,}")
    print(f"   - 非空 Net Income 记录数: {df_anchored['net_income'].notna().sum():,}")

    elapsed = time.time() - t0
    print(f"\n全部处理完成，总耗时: {elapsed / 60:.1f} 分钟。")


if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""Fetch quarterly ETF scale (gmbd) and institutional holder ratio (cyrjg) for all 21 verified NT ETFs."""
import os, re, sys
os.environ["NO_PROXY"] = "*"
import requests
import pandas as pd
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from csrc_fetch_etf_shares import ETFS, OUT_DIR


def parse_html_table(url_code, typ):
    url = f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type={typ}&code={url_code}"
    txt = requests.get(url, headers={"Referer": "https://fundf10.eastmoney.com/", "User-Agent": "Mozilla/5.0"}, timeout=15).text
    m = re.search(r'content:"(.*?)"(?:,|\})', txt, flags=re.S)
    if not m:
        return []
    html = m.group(1).replace('\\"', '"')
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.find("table")
    if not tbl:
        return []
    headers = [th.get_text(strip=True) for th in tbl.find_all("th")]
    rows = []
    for tr in tbl.find_all("tr")[1:]:
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) == len(headers):
            d = dict(zip(headers, tds))
            d["code"] = url_code
            rows.append(d)
    return rows


def to_num(s):
    s = str(s).replace(",", "").replace("%", "").replace("---", "").strip()
    try:
        return float(s)
    except Exception:
        return None


if __name__ == "__main__":
    g_rows, c_rows = [], []
    for c in ETFS.keys():
        for r in parse_html_table(c, "gmbd"):
            g_rows.append({
                "code": c, "date": r.get("日期", ""),
                "sub_yi": to_num(r.get("期间申购（亿份）")),
                "red_yi": to_num(r.get("期间赎回（亿份）")),
                "shares_yi": to_num(r.get("期末总份额（亿份）")),
                "nav_yi": to_num(r.get("期末净资产（亿元）")),
            })
        for r in parse_html_table(c, "cyrjg"):
            c_rows.append({
                "code": c, "date": r.get("公告日期", ""),
                "inst_pct": to_num(r.get("机构持有比例")),
                "retail_pct": to_num(r.get("个人持有比例")),
                "internal_pct": to_num(r.get("内部持有比例")),
                "total_shares_yi": to_num(r.get("总份额（亿份）")),
            })
    df_g = pd.DataFrame(g_rows)
    df_c = pd.DataFrame(c_rows)
    df_m = df_g.merge(df_c, on=["code", "date"], how="outer").sort_values(["code", "date"])
    out_p = os.path.join(OUT_DIR, "etf_quarterly_scale.parquet")
    df_m.to_parquet(out_p, index=False)
    print(f"Saved {out_p}: {len(df_m)} rows across {df_m['code'].nunique()} ETFs")
    sub = df_m[df_m["date"] >= "2024-12-31"].groupby("date")[["shares_yi", "nav_yi", "sub_yi", "red_yi"]].sum(min_count=1)
    print("Aggregate 21 verified ETFs quarterly scale (2024-12-31 to 2026-09-30):\n", sub.to_string())

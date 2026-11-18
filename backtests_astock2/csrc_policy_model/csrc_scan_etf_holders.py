#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Penetrate Official 2025 Annual Reports & 2026 Semi-Annual Reports (PDF) for 30 candidate ETFs:
Extract exact top-10 holder holdings of Central Huijin Investment, Huijin Asset Mgmt, Guoxin, Chengtong, Social Security!
"""
import os, re, json
from concurrent.futures import ThreadPoolExecutor, as_completed
os.environ["NO_PROXY"] = "*"
import requests, fitz, pandas as pd

NT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/national_team"
os.makedirs(NT_DIR, exist_ok=True)

CANDIDATES = {
    # Team 1 Large-cap candidates
    "510300": ("华泰柏瑞沪深300ETF", "一队_大盘蓝筹"), "510310": ("易方达沪深300ETF", "一队_大盘蓝筹"),
    "510330": ("华夏沪深300ETF", "一队_大盘蓝筹"), "159919": ("嘉实沪深300ETF", "一队_大盘蓝筹"),
    "510050": ("华夏上证50ETF", "一队_大盘蓝筹"), "510180": ("华安上证180ETF", "一队_大盘蓝筹"),
    "510880": ("华泰柏瑞红利ETF", "一队_大盘蓝筹"), "510350": ("工银沪深300ETF", "一队_大盘蓝筹"),
    "510100": ("易方达上证50ETF", "一队_大盘蓝筹"),
    # Team 2 Mid/Small/Growth candidates
    "510500": ("南方中证500ETF", "二队_中小创扩散"), "512500": ("华夏中证500ETF", "二队_中小创扩散"),
    "159922": ("嘉实中证500ETF", "二队_中小创扩散"), "512100": ("南方中证1000ETF", "二队_中小创扩散"),
    "159845": ("华夏中证1000ETF", "二队_中小创扩散"), "560010": ("广发中证1000ETF", "二队_中小创扩散"),
    "159629": ("富国中证1000ETF", "二队_中小创扩散"), "159915": ("易方达创业板ETF", "二队_中小创扩散"),
    "159949": ("华安创业板50ETF", "二队_中小创扩散"), "588000": ("华夏科创50ETF", "二队_中小创扩散"),
    "588080": ("易方达科创50ETF", "二队_中小创扩散"),
    # Team 3 Central SOE & A500 candidates
    "560170": ("南方央企科技引领ETF", "三队_央企专买"), "560070": ("汇添富央企股东回报ETF", "三队_央企专买"),
    "560280": ("易方达央企科技50ETF", "三队_央企专买"), "515900": ("博时央企创新驱动ETF", "三队_央企专买"),
    "515600": ("广发央企创新驱动ETF", "三队_央企专买"), "512960": ("博时央企结构调整ETF", "三队_央企专买"),
    "517090": ("国泰富时国企开放共赢ETF", "三队_央企专买"), "512050": ("华夏中证A500ETF", "三队_央企专买"),
    "159338": ("国泰中证A500ETF", "三队_央企专买"), "159352": ("南方中证A500ETF", "三队_央企专买"),
}

NT_HOLDER_PAT = re.compile(r"(中央汇金|汇金资管|国新投资|诚通|中国证券金融|社保基金|全国社会保障)")


def parse_one_etf(code):
    name, grp = CANDIDATES[code]
    res = {"code": code, "name": name, "team": grp, "ar2025_nt_pct": 0.0, "ar2025_nt_shares_yi": 0.0,
           "ar2025_holders": [], "ar2025_inst_pct": None, "sr2026_inst_pct": None, "sr2026_tot_yi": None}
    try:
        r = requests.get(f"https://api.fund.eastmoney.com/f10/jjgg?fundcode={code}&pageIndex=1&pageSize=30&type=3",
                         headers={"Referer": "https://fundf10.eastmoney.com/", "User-Agent": "Mozilla/5.0"}, timeout=12)
        items = r.json().get("Data") or []
    except Exception as e:
        res["err"] = str(e)
        return res

    ar_id, sr_id = None, None
    for it in items:
        t = it.get("TITLE", "")
        if "摘要" in t:
            continue
        if "2025年年度报告" in t and not ar_id:
            ar_id = it["ID"]
        elif "2026年中期报告" in t and not sr_id:
            sr_id = it["ID"]

    if ar_id:
        try:
            pdf_b = requests.get(f"https://pdf.dfcfw.com/pdf/H2_{ar_id}_1.pdf", timeout=25).content
            doc = fitz.open(stream=pdf_b, filetype="pdf")
            txt_sec = ""
            found = False
            for idx_pg, pg in enumerate(doc):
                t = pg.get_text()
                if idx_pg < 6 or "......" in t or "····" in t:  # Skip TOC / cover pages!
                    continue
                if "期末上市基金前十名持有人" in t or "持有人名称" in t:
                    found = True
                if found:
                    txt_sec += "\n" + t
                    if ("开放式基金份额变动" in t or "期末基金管理人的从业人员" in t) and len(txt_sec) > 400:
                        break
            # Clean line breaks inside holder table
            clean = re.sub(r"\s+", " ", txt_sec)
            m_blk = re.search(r"前十名持有人(.*?)(?:注：|期末基金管理人|开放式基金份额变动|$)", clean)
            blk = m_blk.group(1) if m_blk else clean
            # Find numbers after holder names (supports spaces/newlines inside company names)
            rows = re.findall(r"(?:\d+\s+)([A-Za-z\u4e00-\u9fa5（）()·－\-—\s]{3,55}?)\s+([\d,]+\.\d{2})\s+(\d+\.\d{2})", blk)
            nt_list, pct_sum, sh_sum = [], 0.0, 0.0
            for hname, sh_s, pct_s in rows:
                h_clean = re.sub(r"\s+", "", hname)
                if NT_HOLDER_PAT.search(h_clean):
                    sh_yi = float(sh_s.replace(",", "")) / 1e8
                    pct_v = float(pct_s)
                    nt_list.append(f"{h_clean}:{sh_yi:.2f}亿({pct_v:.2f}%)")
                    pct_sum += pct_v
                    sh_sum += sh_yi
            res["ar2025_holders"] = nt_list
            res["ar2025_nt_pct"] = round(pct_sum, 2)
            res["ar2025_nt_shares_yi"] = round(sh_sum, 2)
            res["raw_blk_preview"] = blk[:400]
        except Exception as e:
            res["ar_err"] = str(e)

    # Also pull Eastmoney cyrjg for exact inst_pct & total_shares at 2025-12-31 & 2026-06-30
    try:
        t_c = requests.get(f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=cyrjg&code={code}",
                           headers={"Referer": "https://fundf10.eastmoney.com/"}, timeout=10).text
        for dt_k, col_i, col_t in [("2025-12-31", "ar2025_inst_pct", "ar2025_tot_yi"), ("2026-06-30", "sr2026_inst_pct", "sr2026_tot_yi")]:
            m_dt = re.search(rf"<td>{dt_k}</td>.*?<td[^>]*>([\d.]+)%</td>.*?<td[^>]*>([\d,.]+)</td>", t_c, flags=re.S)
            if m_dt:
                res[col_i] = float(m_dt.group(1))
                res[col_t] = float(m_dt.group(2).replace(",", ""))
    except Exception:
        pass
    return res


if __name__ == "__main__":
    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(parse_one_etf, c) for c in CANDIDATES]
        for fut in as_completed(futs):
            results.append(fut.result())
    df = pd.DataFrame(results).sort_values(["team", "ar2025_nt_pct"], ascending=[True, False])
    p_js = os.path.join(NT_DIR, "etf_holders_scan_30.json")
    json.dump(results, open(p_js, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(df[["code", "name", "team", "ar2025_nt_shares_yi", "ar2025_nt_pct", "ar2025_inst_pct", "sr2026_inst_pct", "ar2025_holders"]].to_string(index=False))

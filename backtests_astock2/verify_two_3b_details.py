#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import os, json, sqlite3, urllib.request
import pandas as pd

ROOT = "/Users/huaichuaibeimeng/claude-projects"
holders = json.load(open(f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"))
print("holders keys sample:", list(holders.keys())[:5])
for c in ["603396", "002148", "605255"]:
    print(c, "in holders:", holders.get(c, "MISSING")[-2:] if c in holders else "MISSING")

# Check cand_3to4.parquet historical rows for 603396 / 002148 or open_board_count definition
df0 = pd.read_parquet(f"{ROOT}/sim-portfolio/backtests_astock2/data_5y/cand_3to4_enriched54.parquet",
                      columns=["code", "name", "sig_date", "lock_top10", "real_free_mcap", "open_board_count", "first_seal_time"])
print("\nSample open_board_count==0 vs >=1 in cand_3to4:")
print(df0[df0["open_board_count"] == 0][["code", "name", "sig_date", "first_seal_time", "open_board_count"]].tail(5))
print(df0[df0["open_board_count"] >= 1][["code", "name", "sig_date", "first_seal_time", "open_board_count"]].tail(5))

# Fetch exact Tencent quote (total mcap, circ mcap, turnover) + Eastmoney F10 top10 share ratio for 603396 & 002148
for pfx, c in [("sh", "603396"), ("sz", "002148"), ("sh", "605255")]:
    q = urllib.request.urlopen(f"https://qt.gtimg.cn/q={pfx}{c}", timeout=6).read().decode("gbk").split("~")
    print(f"\nTencent {c} {q[1]}: close={q[3]} open={q[5]} high={q[33]} low={q[34]} to={q[38]}% circ_mcap={q[44]}亿 tot_mcap={q[45]}亿 zt={q[47]}")
    try:
        em_u = f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_F10_EH_FREEHOLDERS&columns=END_DATE,HOLDER_NAME,HOLD_RATIO&filter=(SECUCODE%3D%22{c}.{'SH' if pfx=='sh' else 'SZ'}%22)&pageNumber=1&pageSize=15&sortTypes=-1&sortColumns=END_DATE"
        rj = json.loads(urllib.request.urlopen(em_u, timeout=6).read().decode("utf-8"))
        rows = (rj.get("result") or {}).get("data") or []
        if rows:
            latest_dt = rows[0]["END_DATE"]
            s_ratio = sum(float(x.get("HOLD_RATIO") or 0) for x in rows if x["END_DATE"] == latest_dt)
            print(f"  EM FreeHolders ({latest_dt}): sum={s_ratio:.2f}%")
        em_u2 = f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_DMSK_HOLDERS&columns=END_DATE,HOLDER_NAME,HOLD_NUM_RATIO&filter=(SECUCODE%3D%22{c}.{'SH' if pfx=='sh' else 'SZ'}%22)&pageNumber=1&pageSize=15&sortTypes=-1&sortColumns=END_DATE"
        rj2 = json.loads(urllib.request.urlopen(em_u2, timeout=6).read().decode("utf-8"))
        rows2 = (rj2.get("result") or {}).get("data") or []
        if rows2:
            latest_dt2 = rows2[0]["END_DATE"]
            s_ratio2 = sum(float(x.get("HOLD_NUM_RATIO") or 0) for x in rows2 if x["END_DATE"] == latest_dt2)
            print(f"  EM Top10 Holders ({latest_dt2}): sum={s_ratio2:.2f}%")
    except Exception as e:
        print("  EM err:", e)

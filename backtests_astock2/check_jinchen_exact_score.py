#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
import json, re, urllib.request

# 1. Check 603396 recent 90d announcements from Eastmoney
u_ann = "https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=25&page_index=1&ann_type=A&stock_list=603396"
ann_j = json.loads(urllib.request.urlopen(u_ann, timeout=6).read().decode("utf-8"))
anns = (ann_j.get("data") or {}).get("list") or []
print("=== 603396 最近公告 ===")
for a in anns[:12]:
    print(" ", a.get("notice_date", "")[:10], a.get("title", ""))

# 2. Check 603396 LHB on 2026-11-13 (or 11-12 / 11-11) from Eastmoney datacenter
u_lhb = "https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_BILLBOARD_DAILYDETAILSBUY&columns=TRADE_DATE,OPERATEDEPT_NAME,BUY,NET&filter=(SECURITY_CODE%3D%22603396%22)&pageNumber=1&pageSize=30&sortTypes=-1&sortColumns=TRADE_DATE"
try:
    lj = json.loads(urllib.request.urlopen(u_lhb, timeout=6).read().decode("utf-8"))
    lrows = (lj.get("result") or {}).get("data") or []
    print("\n=== 603396 最近龙虎榜买席 ===")
    for r in lrows[:12]:
        print(" ", str(r.get("TRADE_DATE"))[:10], r.get("OPERATEDEPT_NAME"), "BUY=", r.get("BUY"))
except Exception as e:
    print("LHB err:", e)

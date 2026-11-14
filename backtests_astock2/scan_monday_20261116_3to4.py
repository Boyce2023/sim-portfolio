#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""精准扫描 2026-11-13（周五收盘）全场 3连板及以上梯队，逐只核验下周一（2026-11-16）三进四 V3.2 硬骨架与预估打分"""
import os, sys, json, re, sqlite3, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = "/Users/huaichuaibeimeng/claude-projects"
sys.path.insert(0, f"{ROOT}/sim-portfolio/scripts")
import astock_data_layer as adl

lu = adl.get_limit_up_stocks()
lu10 = [s for s in lu.get("10cm", []) if str(s["code"]).startswith(("00", "60")) and "ST" not in str(s["name"]).upper()]

def fetch_tx_kline(c6, n_bars=12):
    pfx = "sh" if c6.startswith("60") else "sz"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={pfx}{c6},day,,,{n_bars},qfq"
    raw = json.loads(urllib.request.urlopen(url, timeout=8).read().decode("utf-8"))
    d = raw["data"][f"{pfx}{c6}"]
    return d.get("qfqday") or d.get("day") or []

def fetch_tx_min_open_cnt(c6):
    """用腾讯今日1分钟分时精确数三板当日盘中开板次数（曾封涨停后跌破涨停的次数，或非一字首次封板前换手）"""
    pfx = "sh" if c6.startswith("60") else "sz"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={pfx}{c6}"
    raw = json.loads(urllib.request.urlopen(url, timeout=8).read().decode("utf-8"))
    d = raw["data"][f"{pfx}{c6}"]
    qt = d["qt"][f"{pfx}{c6}"]
    pre_c = float(qt[4])
    zt_px = float(qt[47]) if float(qt[47]) > 0 else round(pre_c * 1.10 + 1e-6, 2)
    mins = d["data"]["data"]  # "0930 12.34 12345 ..."
    pxs = [float(m.split()[1]) for m in mins if m.strip()]
    if not pxs:
        return 0, "99:99"
    first_seal = "未封"
    open_cnt = 0
    in_seal = (pxs[0] >= zt_px - 0.005)
    if in_seal:
        first_seal = mins[0].split()[0]
    for idx, p in enumerate(pxs[1:], 1):
        sealed = (p >= zt_px - 0.005)
        if sealed and not in_seal and first_seal == "未封":
            first_seal = mins[idx].split()[0]
        if in_seal and not sealed:
            open_cnt += 1
        in_seal = sealed
    return open_cnt, first_seal

holders_path = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
holders = json.load(open(holders_path, "r")) if os.path.exists(holders_path) else {}

csi_bars = json.loads(urllib.request.urlopen("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000300,day,,,10,", timeout=8).read().decode("utf-8"))["data"]["sh000300"]["day"]
c_now, c_1d, c_5d = float(csi_bars[-1][2]), float(csi_bars[-2][2]), float(csi_bars[-6][2])
csi_1d_chg, csi_5d_chg = c_now / c_1d - 1.0, c_now / c_5d - 1.0

def check_one(s):
    c6 = str(s["code"]).zfill(6)
    try:
        kb = fetch_tx_kline(c6, 12)
    except Exception:
        return None
    if len(kb) < 5: return None
    cnt = 0
    for j in range(len(kb) - 1, 0, -1):
        cl, pcl = float(kb[j][2]), float(kb[j-1][2])
        zt_px = round(pcl * 1.10 + 1e-6, 2)
        if cl >= zt_px - 0.015 or (cl / pcl >= 1.095):
            cnt += 1
        else:
            break
    if cnt < 2: return None
    last = kb[-1]
    op, cl, hi, lo = float(last[1]), float(last[2]), float(last[3]), float(last[4])
    is_yizi = (abs(op - cl) < 0.005) and (abs(lo - cl) < 0.005)
    h_list = holders.get(c6, [])
    lock10 = float(h_list[-1][-1]) if h_list else 0.0
    circ = float(s.get("circulating_cap") or s.get("market_cap") or 0.0)
    free_mc = circ * (1.0 - min(lock10, 95.0) / 100.0)
    open_cnt, f_seal = fetch_tx_min_open_cnt(c6) if cnt == 3 else (0, "")
    return {
        "code": c6, "name": s["name"], "boards": cnt, "date": last[0],
        "close": cl, "open": op, "low": lo, "to": round(float(s.get("turnover_rate") or 0.0), 2),
        "circ_cap": round(circ, 1), "lock10": round(lock10, 1), "free_mc": round(free_mc, 1),
        "is_yizi": is_yizi, "open_board_cnt": open_cnt, "first_seal": f_seal,
        "industry": s.get("industry", ""),
    }

with ThreadPoolExecutor(max_workers=12) as ex:
    res = [r for r in ex.map(check_one, lu10) if r is not None]

max_b = max((x["boards"] for x in res), default=1)
print(f"=== 今日({csi_bars[-1][0]}) 收盘梯队全景 ===")
print(f"10cm非ST主板涨停家数 = {len(lu10)} | 全场最高连板 = {max_b}板 | 沪深300今涨跌 = {csi_1d_chg*100:+.2f}% | 5日涨跌 = {csi_5d_chg*100:+.2f}%")
print("\n--- 4板及以上高标 ---")
for x in sorted([r for r in res if r["boards"] >= 4], key=lambda z: (-z["boards"], -z["to"])):
    print(" ", x)
print("\n--- 今日收盘正好 3 连板（下周一 11月16日 3进4 全部潜在候选池）---")
for x in sorted([r for r in res if r["boards"] == 3], key=lambda z: (-z["to"])):
    print(" ", x)

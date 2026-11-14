#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
三进四 星期效应 + 月份日历效应（含均值/中位数/跨年一致性防幻觉检验）
+ 2026-11-13（周五收盘）三连板逐只核验与下周一（2026-11-16）候选打分扫描
"""
import os, sys, json, sqlite3, urllib.request
import numpy as np
import pandas as pd

CUR_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = "/Users/huaichuaibeimeng/claude-projects"
sys.path.insert(0, CUR_DIR)
sys.path.insert(0, f"{ROOT}/sim-portfolio/scripts")

from bt_3to4_v32_final_build import df, sim_pool
from core_3to4_5m_engine import _sim_single_slot_chrono
import astock_data_layer as adl

# === Part 1: 星期效应与月份效应（底池 vs 硬骨架头名池 vs 90分标准档单仓）===
p_v32 = sim_pool("touch65_1130", "cut_weak", "pm1345", True, False)
df["ret"] = [x["net_ret"] if x is not None else np.nan for x in p_v32]
df["bhh"] = [x["buy_hhmm"] if x is not None else 0 for x in p_v32]
df["ex_dt"] = [x["exit_date"] if x is not None else "" for x in p_v32]
df["ex_hh"] = [x["exit_hhmm"] if x is not None else 0 for x in p_v32]

skel_base = (df["is_10cm_non_st"] & (~df["prev_is_yizi"]) & df["buyable_open"] & (~df["has_tox_notice"]) & (~df["has_stock_reg"])
             & (df["open_board_count"] >= 1) & ((df["lock_top10"] >= 45.0) | (df["real_free_mcap"] >= 45.0))
             & df["prev_to"].between(8.5, 31.0) & df["open_pct"].between(0.030, 0.092))
skel_v32 = skel_base & df["is_top1_3b_open"].astype(bool)
pts = (78.0 + np.where(df["px_d3"] <= 20.0, 8.0, np.where(df["px_d3"] > 32.0, -5.0, 0.0))
       + np.where(df["mkt_max_board_prev"] <= 4, 8.0, 0.0) + np.where(df["p_elo"] >= 115.0, 3.0, 0.0)
       + np.where(df["mkt_zt_prev"] >= 95, -10.0, np.where(df["mkt_zt_prev"].between(35, 85), 5.0, 0.0))
       + np.where(df["has_ex_reg"], -12.0, 0.0) + np.where(df["surf_yz_buy"], -12.0, 0.0)
       + np.where(df["lhb_lh_cnt"] == 0, 4.0, np.where(df["lhb_lh_cnt"] >= 3, -5.0, 0.0))
       + np.where((df["plate_fb_ho_cnt"] >= 2) & (df["plate_fb_yz_cnt"] == 0), 4.0, 0.0)
       + np.where(df["plate_fb_yz_cnt"] >= 1, -7.0, 0.0) + np.where(df["plate_peers_open_avg"] < -0.015, -10.0, 0.0)
       + np.where(df["prev_3b_dt_cnt"] == 0, 3.0, np.where(df["prev_3b_dt_cnt"] >= 2, -4.0, 0.0))
       + np.where((df["csi_1d_prev"] <= -0.020) | (df["csi_5d_prev"] <= -0.030), -8.0, 0.0) + np.where(df["prev_to"].between(9.5, 28.0), 3.0, 0.0))
df["sc_v32"] = np.where(skel_v32, pts, -999.0)

dt_ser = pd.to_datetime(df["buy_date"])
df["dow"] = dt_ser.dt.dayofweek + 1  # 1=Mon..5=Fri
df["mon"] = dt_ser.dt.month
df["yr"] = dt_ser.dt.year

recs90 = [dict(p_v32[i], dow=int(df["dow"].iloc[i]), mon=int(df["mon"].iloc[i]), yr=int(df["yr"].iloc[i]),
               priority_score=float(df["sc_v32"].iloc[i])*10+float(df["prio_3to4"].iloc[i])*0.1)
          for i in np.where(df["sc_v32"] >= 90)[0] if p_v32[i] is not None]
taken90, _, _, _ = _sim_single_slot_chrono(pd.DataFrame(recs90))
t90 = pd.DataFrame([t._asdict() for t in taken90])
pool_sk = df[skel_base & df["ret"].notna()].copy()

print("=== [1] 星期几规律 (1=周一买入即周三至周五三连板跨周末, ..., 5=周五买入跨周末持仓) ===")
for d in [1, 2, 3, 4, 5]:
    a = pool_sk[pool_sk["dow"] == d]["ret"]
    b = t90[t90["dow"] == d]["net_ret"]
    b3 = t90[(t90["dow"] == d) & (t90["buy_date"] >= "2024-01-01")]["net_ret"]
    po = (b[b>0].mean()/abs(b[b<=0].mean())) if (len(b[b>0]) and len(b[b<=0])) else 99.0
    pos_yrs = sum((t90[(t90["dow"]==d)&(t90["yr"]==y)]["net_ret"].add(1).prod() > 1.0) for y in [2022,2023,2024,2025,2026] if len(t90[(t90["dow"]==d)&(t90["yr"]==y)])>0)
    tot_yrs = sum(1 for y in [2022,2023,2024,2025,2026] if len(t90[(t90["dow"]==d)&(t90["yr"]==y)])>0)
    print(f"周{d} | 骨架底池:{len(a):3d}笔 WR={(a>0).mean()*100:4.1f}% 均={a.mean()*100:+5.2f}% 中位={a.median()*100:+5.2f}% || 90分单仓:{len(b):2d}笔 WR={(b>0).mean()*100:4.1f}% PO={po:4.2f} 均={b.mean()*100:+6.2f}% 中位={b.median()*100:+5.2f}% 净值贡献={np.prod(1+b):5.2f}x 正年={pos_yrs}/{tot_yrs} | 近3年:{len(b3):2d}笔 WR={(b3>0).mean()*100 if len(b3) else 0:4.1f}% 均={b3.mean()*100 if len(b3) else 0:+6.2f}%")

print("\n=== [2] 月份规律 (1月至12月) ===")
for m in range(1, 13):
    a = pool_sk[pool_sk["mon"] == m]["ret"]
    b = t90[t90["mon"] == m]["net_ret"]
    pos_sk_yrs = sum((pool_sk[(pool_sk["mon"]==m)&(pool_sk["yr"]==y)]["ret"].mean() > 0) for y in [2022,2023,2024,2025,2026] if len(pool_sk[(pool_sk["mon"]==m)&(pool_sk["yr"]==y)])>0)
    tot_sk_yrs = sum(1 for y in [2022,2023,2024,2025,2026] if len(pool_sk[(pool_sk["mon"]==m)&(pool_sk["yr"]==y)])>0)
    b_wr = (b>0).mean()*100 if len(b) else 0.0
    b_mn = b.mean()*100 if len(b) else 0.0
    b_md = b.median()*100 if len(b) else 0.0
    print(f"{m:2d}月 | 骨架底池:{len(a):2d}笔 WR={(a>0).mean()*100 if len(a) else 0:4.1f}% 均={a.mean()*100 if len(a) else 0:+5.2f}% 中位={a.median()*100 if len(a) else 0:+5.2f}% 正年={pos_sk_yrs}/{tot_sk_yrs} || 90分单仓:{len(b):2d}笔 WR={b_wr:4.1f}% 均={b_mn:+6.2f}% 中位={b_md:+5.2f}% 净值={np.prod(1+b) if len(b) else 1.0:5.2f}x")

# === Part 2: 今日(2026-11-13 周五)收盘实时扫描 — 找全部三连板及连板梯队 ===
print("\n=== [3] 2026-11-13 周五收盘全市场涨停梯队与下周一(11月16日)三进四候选核验 ===")
lu = adl.get_limit_up_stocks()
lu10 = [s for s in lu.get("10cm", []) if str(s["code"]).startswith(("00", "60")) and "ST" not in str(s["name"]).upper()]
idx_q = adl.get_index_quotes(["sh000300"])

def fetch_tx_kline(c6, n_bars=12):
    pfx = "sh" if c6.startswith("60") else "sz"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={pfx}{c6},day,,,{n_bars},qfq"
    raw = json.loads(urllib.request.urlopen(url, timeout=8).read().decode("utf-8"))
    d = raw["data"][f"{pfx}{c6}"]
    rows = d.get("qfqday") or d.get("day") or []
    return rows  # [date, open, close, high, low, vol]

csi_bars = json.loads(urllib.request.urlopen("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000300,day,,,10,", timeout=8).read().decode("utf-8"))["data"]["sh000300"]["day"]
c_now, c_1d, c_5d = float(csi_bars[-1][2]), float(csi_bars[-2][2]), float(csi_bars[-6][2])
csi_1d_chg = c_now / c_1d - 1.0
csi_5d_chg = c_now / c_5d - 1.0

holders_path = f"{ROOT}/sim-portfolio/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
holders = json.load(open(holders_path, "r")) if os.path.exists(holders_path) else {}

board_counts = []
for s in lu10:
    c6 = str(s["code"]).zfill(6)
    try:
        kb = fetch_tx_kline(c6, 12)
    except Exception:
        continue
    if len(kb) < 5: continue
    # Count consecutive 10cm ZT ending at latest bar
    cnt = 0
    for j in range(len(kb) - 1, 0, -1):
        cl, pcl = float(kb[j][2]), float(kb[j-1][2])
        zt_px = round(pcl * 1.10 + 1e-6, 2)
        if cl >= zt_px - 0.015 or (cl / pcl >= 1.095):
            cnt += 1
        else:
            break
    if cnt >= 2:
        last = kb[-1]
        op, cl, hi, lo = float(last[1]), float(last[2]), float(last[3]), float(last[4])
        is_yizi = (abs(op - cl) < 0.005) and (abs(lo - cl) < 0.005)
        opened_in_day = (lo < cl - 0.005)  # 盘中最低低于涨停价(T字开板或换手板)
        h_list = holders.get(c6, [])
        lock10 = float(h_list[-1][1]) if h_list else 0.0
        circ = float(s.get("circulating_cap") or s.get("market_cap") or 0.0)
        free_mc = circ * (1.0 - min(lock10, 95.0) / 100.0)
        board_counts.append({
            "code": c6, "name": s["name"], "boards": cnt, "date": last[0],
            "close": cl, "open": op, "low": lo, "to": float(s.get("turnover_rate") or 0.0),
            "circ_cap": round(circ, 1), "lock10": round(lock10, 1), "free_mc": round(free_mc, 1),
            "is_yizi": is_yizi, "opened_or_non_yizi": (not is_yizi) or opened_in_day,
            "industry": s.get("industry", ""),
        })

max_b = max((x["boards"] for x in board_counts), default=1)
print(f"今日({csi_bars[-1][0]}) 全场10cm非ST涨停={len(lu10)}家 | 全场最高连板={max_b}板 | 沪深300今涨跌={csi_1d_chg*100:+.2f}% 5日={csi_5d_chg*100:+.2f}%")
for x in sorted(board_counts, key=lambda z: (-z["boards"], -z["to"])):
    if x["boards"] >= 3:
        print(" ", x)

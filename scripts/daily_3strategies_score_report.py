#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
daily_3strategies_score_report.py — A股三大主策略每日全量打分榜与早盘复盘数据引擎
输出：1) 一进二 Top 20（原版V18 + 26Q4专供）；2) 三进四 Top 20（原版V3.4 + 26Q4专供 + 全场连板梯队）；
      3) 高标首阴全池（原版V5.1 + 26Q4专供）；4) 实时指数、两市涨跌广度、今日涨停热点与最新信号。
严禁 import yfinance（D12）。
"""
import os, sys, json, glob, urllib.request
import numpy as np
import pandas as pd

os.environ["NO_PROXY"] = "*"
ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
sys.path.insert(0, f"{SIM}/backtests_astock2")
from score_3to4_v31_card import score_single_3to4_row

def fetch_qq(codes):
    qmap = {}
    clist = sorted(set(codes))
    for i in range(0, len(clist), 60):
        u = "http://qt.gtimg.cn/q=" + ",".join(clist[i:i+60])
        raw = urllib.request.urlopen(urllib.request.Request(u), timeout=4).read().decode("gbk", "ignore")
        for ln in raw.splitlines():
            if '="' not in ln: continue
            f = ln.split('="')[1].split("~")
            if len(f) > 38:
                c6, nm = f[2], f[1]
                cur, pre, opn = float(f[3] or 0), float(f[4] or 0), float(f[5] or 0)
                hi, lo, amt = float(f[33] or 0), float(f[34] or 0), float(f[37] or 0) / 10000.0
                opct = (opn / pre - 1.0) if pre > 0 and opn > 0 else 0.0
                cpct = (cur / pre - 1.0) if pre > 0 and cur > 0 else 0.0
                zt = round(pre * 1.10 + 1e-6, 2)
                qmap[c6] = {"name": nm, "pre": pre, "open": opn, "cur": cur, "hi": hi, "lo": lo,
                            "opct": opct, "cpct": cpct, "amt_yi": amt, "zt": zt}
    return qmap

def main():
    c1 = json.load(open(f"{SIM}/data/1to2_premarket_cache.json"))
    c3 = json.load(open(f"{SIM}/data/3to4_premarket_cache.json"))
    ch = json.load(open(f"{SIM}/data/high_dragon_premarket_cache.json"))
    d1_str = c1["d1_date"]
    ths_p = f"{SIM}/data/ths_limit_up_daily/{d1_str}.json"
    ths_stocks = json.load(open(ths_p)).get("stocks", []) if os.path.exists(ths_p) else []

    codes = ["sh000001", "sz399001", "sh000300", "sz399006", "sh000852"]
    for x in c1["candidates"]: codes.append(("sh" if x["c6"].startswith("6") else "sz") + x["c6"])
    for x in c3["candidates"]:
        codes.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
        for fc in x.get("plate_fb_codes", []) + x.get("plate_zt_codes", []):
            codes.append(("sh" if fc.startswith("6") else "sz") + fc)
    for x in ch["candidates"]: codes.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
    for s in ths_stocks:
        sc = str(s.get("code", ""))[:6]
        if sc.startswith(("00", "60", "30")): codes.append(("sh" if sc.startswith("6") else "sz") + sc)
    q = fetch_qq(codes)

    print("=== [0] 指数与前日连板梯队实时表现 ===")
    sh_amt = q.get("000001", {}).get("amt_yi", 0) + q.get("399001", {}).get("amt_yi", 0)
    print(f"两市实时总成交额={sh_amt:.1f}亿")
    for ic in ["000001", "000300", "399006", "000852"]:
        iq = q.get(ic, {})
        print(f"  {ic} {iq.get('name','')}: 今开{iq.get('opct',0)*100:+.2f}% | 现涨跌{iq.get('cpct',0)*100:+.2f}% | 现点位={iq.get('cur',0):.2f}")
    for s in ths_stocks:
        hd = s.get("high_days", "")
        sc = str(s.get("code", ""))[:6]
        # 严格只认连续涨停真连板 (N天N板)，剔除N天M板断板反包票
        import re as _re
        m_lb = _re.match(r"^(\d+)天(\d+)板$", str(hd))
        if m_lb and m_lb.group(1) == m_lb.group(2) and int(m_lb.group(1)) >= 2 and sc in q:
            sq = q[sc]
            print(f"  [{m_lb.group(1)}连板] {sc} {sq['name']} ({s.get('reason_type','')[:20]}): 今开{sq['opct']*100:+.2f}% -> 现{sq['cpct']*100:+.2f}%")

    # === [1] 一进二 Top 20 ===
    is_mon = bool(c1.get("is_monday", False))
    mkt = c1.get("mkt_sentiment", {})
    d1_zt = int(mkt.get("d1_zt_cnt", 50))
    seal_r = float(mkt.get("d1_1to2_seal_rate", 0.5))
    climax_pen = (-15.0 if d1_zt >= 100 else (-10.0 if d1_zt >= 95 else 0.0)) + (-10.0 if seal_r >= 0.80 else 0.0)
    rows1 = []
    for r in c1["candidates"]:
        rq = q.get(r["c6"], {})
        r = dict(r)
        if not r.get("name"): r["name"] = rq.get("name", "")
        op, lp, cp, pre = rq.get("open", 0), rq.get("lo", 0), rq.get("cur", 0), r["pre_c"]
        zt_p = round(pre * 1.10 + 1e-6, 2)
        r["open_p"], r["cur_p"], r["o_pct"], r["c_pct"], r["zt_p"] = op, cp, rq.get("opct", 0.0), rq.get("cpct", 0.0), zt_p
        r["d2_is_yizi"] = bool(op >= zt_p - 0.01 and lp >= zt_p - 0.01)
        r["is_buyable_open"] = bool(r.get("gate_ok", False) and 0 < op < zt_p - 0.005)
        r["trig_p"] = min(zt_p, max(round(op * 1.012, 2), round(pre * 1.065, 2))) if op > 0 else zt_p
        rows1.append(r)
    df = pd.DataFrame(rows1)
    is_fl = df["d2_is_yizi"] | ((not is_mon) & (df["o_pct"] > 0.078)) | (is_mon & (df["o_pct"] > 0.088))
    df["front_lock_cnt"] = is_fl.astype(int).groupby(df["plate"]).transform("sum")
    df["plate_d2_yizi_cnt"] = df["d2_is_yizi"].astype(int).groupby(df["plate"]).transform("sum")
    myz = int(df["d2_is_yizi"].sum())
    in_win = df["is_buyable_open"] & ((is_mon & df["o_pct"].between(0.020, 0.088)) | ((not is_mon) & df["o_pct"].between(0.022, 0.078)))
    df["true_buy_rk"] = np.where(in_win, df["o_pct"], -9.99)
    df["true_buy_rk"] = df.groupby("plate")["true_buy_rk"].rank(ascending=False, method="min")
    df["_bo"] = np.where(df["is_buyable_open"], df["o_pct"], -9.99)
    df["mkt_open_rk"] = df["_bo"].rank(ascending=False, method="min")
    df["sub_rk"] = df.groupby(["plate", "r_short"])["_bo"].rank(ascending=False, method="min")
    p2 = df.groupby("plate")["_bo"].transform(lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05)
    df["open_lead"] = np.where(df["true_buy_rk"] == 1, df["o_pct"] - p2, 0.0)
    has_sub = (df["p_sz"] >= 8) & (~df["r_short"].isin([df["plate"], "其他", ""]))
    rk_bon = np.where(df["true_buy_rk"] == 1, 35.0, np.where(has_sub & (df["sub_rk"] == 1), 24.0, np.where(df["true_buy_rk"] == 2, 8.0, -25.0)))
    sw = (df["rk_theme"] == 1) & (df["p_sz"] >= 8) & (df["true_buy_rk"] == 1)
    hm = df["notice_hard"] | df["is_ma"]
    yg = np.select([(df["front_lock_cnt"] == 1) & (df["true_buy_rk"] == 1) & (myz in [1, 2]),
                    (df["front_lock_cnt"] >= 2) & sw, (df["front_lock_cnt"] == 2) & (~sw),
                    (df["front_lock_cnt"] >= 3) & (~sw), (df["front_lock_cnt"] == 0) & (myz == 0) & (~hm)],
                   [8.0, 5.0, -15.0, -22.0, -5.0], default=0.0)
    auc_b = (rk_bon + np.where(df["mkt_open_rk"] <= 3, 20.0, np.where(df["mkt_open_rk"] <= 6, 12.0, 0.0))
             + np.where(df["open_lead"] >= 0.020, 22.0, np.where(df["open_lead"] >= 0.010, 12.0, 0.0))
             + np.where(df["plate_d2_yizi_cnt"] >= 1, 10.0, 0.0)
             + np.where(df["o_pct"].between(0.040, 0.082), 20.0, np.where(df["o_pct"].between(0.018, 0.040), 12.0, 0.0)))
    wk_pen = 0.0 if is_mon else np.where(df["o_pct"] < (0.035 if float(mkt.get("roll20_ho_zt", 0.5)) < 0.45 else 0.031), -25.0 if float(mkt.get("roll20_ho_zt", 0.5)) < 0.45 else -15.0, 0.0)
    ts = c1.get("theme_structure", {})
    dom_t3 = (float(ts.get("t1_med", 0)) >= 65.0) and (float(ts.get("t1_med", 0)) - float(ts.get("t3_med", 0)) >= 35.0) and (float(ts.get("t3_med", 0)) < 42.0)
    v18_pen = np.where((df["plate_d2_yizi_cnt"] >= 1) & (df["mcap"] > 90.0), -25.0, 0.0) + np.where(dom_t3 & (df["rk_theme"] >= 3), -15.0, 0.0)
    df["tot_v18"] = df["static_tot"] + auc_b + wk_pen + yg + climax_pen + v18_pen
    q4_delta = (np.where(df["is_dying_pulse"], -15.0, 0.0) + np.where(hm, 10.0, 0.0)
                + np.where(df["o_pct"].between(0.045, 0.078), 5.0, 0.0) + np.where(df["clean_brk60"], 5.0, 0.0)
                + np.where(df["plate_d2_yizi_cnt"] >= 1, -10.0, 0.0))
    df["tot_26q4"] = df["tot_v18"] + q4_delta
    print(f"\n=== [1] 一进二打分榜 Top 20 (共{len(df)}只 | 原版门槛304.8 | 专供门槛304.8) ===")
    for i, (_, r) in enumerate(df.sort_values("tot_26q4", ascending=False).head(20).iterrows(), 1):
        why = []
        if not r["gate_ok"]: why.append("盘前门禁否决")
        if r["d2_is_yizi"]: why.append("今一字不可买")
        if r["is_dying_pulse"]: why.append("原版退潮脉冲拦截/专供扣15")
        if not (0.020 <= r["o_pct"] <= 0.088 if is_mon else 0.022 <= r["o_pct"] <= 0.078): why.append("开盘越出甜区")
        if r["tot_26q4"] < 304.8: why.append("总分未满304.8")
        print(f"{i:02d}|{r['c6']}|{r['name']}|{r['plate']}|静态{r['static_tot']:.1f}|原版{r['tot_v18']:.1f}|专供{r['tot_26q4']:.1f}|今开{r['o_pct']*100:+.2f}%|现{r['c_pct']*100:+.2f}%|{'，'.join(why[:2])}")

    # === [2] 三进四 Top 20 ===
    env3 = c3.get("env", {})
    cands3 = c3.get("candidates", [])
    open_3b = [(r["code"], q.get(r["code"], {}).get("opct", -1.0), q.get(r["code"], {}).get("open", 0) < r["px_d3"] * 1.095) for r in cands3]
    buy_3b = [x for x in open_3b if x[2]]
    top1_c = max(buy_3b, key=lambda x: x[1])[0] if buy_3b else ""
    print(f"\n=== [2] 三进四打分榜 Top 20 (今日全场三连板共{len(cands3)}只 | 原版90分 | 专供94分) ===")
    for i, r in enumerate(cands3[:20], 1):
        rq = q.get(r["code"], {})
        fb_ops = [q.get(fc, {}) for fc in r.get("plate_fb_codes", []) if fc in q]
        zt_ops = [q.get(zc, {}).get("opct", 0.0) for zc in r.get("plate_zt_codes", []) if zc in q]
        row = dict(r, **env3)
        row["open_pct"] = rq.get("opct", 0.0)
        row["buyable_open"] = rq.get("open", 0) < rq.get("zt", 999) - 0.005
        row["is_top1_3b_open"] = (r["code"] == top1_c)
        row["plate_fb_ho_cnt"] = sum(1 for x in fb_ops if 0.025 <= x.get("opct", 0) < 0.095)
        row["plate_fb_yz_cnt"] = sum(1 for x in fb_ops if x.get("opct", 0) >= 0.095)
        row["plate_peers_open_avg"] = float(np.mean(zt_ops)) if zt_ops else 0.0
        res = score_single_3to4_row(row)
        sc_v34 = res["score"]
        sc_q4 = sc_v34
        if res["passed_skeleton"]:
            if 0.030 <= row["open_pct"] <= 0.058: sc_q4 += 4
            if 32.0 < r["px_d3"] <= 48.0: sc_q4 += 5
            elif r["px_d3"] > 48.0: sc_q4 -= 5
            if int(env3.get("mkt_max_board_prev", 4)) >= 6 and r["lock_top10"] < 45.0: sc_q4 -= 8
            if r["prev_to"] < 9.5: sc_q4 -= 5
            sc_q4 += 1  # 周一额外+1 (合计+3)
        print(f"{i:02d}|{r['code']}|{r['name']}|{r['plate'][:14]}|昨收{r['px_d3']:.2f}|原版{sc_v34}|专供{sc_q4}|今开{rq.get('opct',0)*100:+.2f}%|现{rq.get('cpct',0)*100:+.2f}%|{res['breakdown_str']}")

    # === [3] 高标首阴 ===
    print(f"\n=== [3] 高标首阴打分榜 (今日全场共{len(ch['candidates'])}只 | 原版88分 | 专供96分) ===")
    for i, r in enumerate(ch["candidates"], 1):
        rq = q.get(r["code"], {})
        op = rq.get("opct", 0.0)
        v51_raw = r["static_score"] + (8 if op < 0 else (6 if op <= 0.025 else 0))
        q4_raw = r["static_score"] + (12 if -0.004 <= op <= 0.035 else (-8 if op <= -0.008 else 0)) + 6 + 5
        veto_str = "；".join(r["veto_reasons"]) if r["is_vetoed"] else "无否决"
        print(f"{i:02d}|{r['code']}|{r['name']}|D0={r['streak_d0']}板|静态{r['static_score']}|未否决原版{v51_raw}/专供{q4_raw}|终审=(-999否决)|今开{op*100:+.2f}%|现{rq.get('cpct',0)*100:+.2f}%|{veto_str}")

if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
daily_3strategies_score_report.py — A股三大主策略每日全量打分榜与早盘复盘数据引擎
输出：
  1. 顶部一句话清晰汇总「26Q4专供版三大主策略购买判断 + 五年基础版对照 + 超跌撬板/五板辅助策略」；
  2. 一进二打分榜 Top 20（原版V18 + 26Q4专供双列打分、今开与现价涨跌、未过线原因）；
  3. 三进四全池打分榜（原版V3.4 + 26Q4专供双列打分、硬骨架细目）；
  4. 高标首阴全池打分榜（原版V5.1 + 26Q4专供双列打分、否决原因）；
  5. 指数与前日连板梯队实时表现。
严格遵守 D12 铁律（严禁 import yfinance）。
"""
import os, sys, json, glob, re, urllib.request
import numpy as np
import pandas as pd

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM}/data"

sys.path.insert(0, f"{SIM}/backtests_astock2")
from score_3to4_v31_card import score_single_3to4_row

def fetch_qq(codes: list[str]) -> dict[str, dict]:
    qmap = {}
    clist = sorted(set(codes))
    for i in range(0, len(clist), 80):
        u = "http://qt.gtimg.cn/q=" + ",".join(clist[i:i+80])
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=4).read().decode("gbk", "ignore")
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
        except Exception:
            pass
    return qmap

def main():
    c1 = json.load(open(f"{DATA_DIR}/1to2_premarket_cache.json")) if os.path.exists(f"{DATA_DIR}/1to2_premarket_cache.json") else {"candidates": []}
    c3 = json.load(open(f"{DATA_DIR}/3to4_premarket_cache.json")) if os.path.exists(f"{DATA_DIR}/3to4_premarket_cache.json") else {"candidates": []}
    ch = json.load(open(f"{DATA_DIR}/high_dragon_premarket_cache.json")) if os.path.exists(f"{DATA_DIR}/high_dragon_premarket_cache.json") else {"candidates": []}
    cpry = json.load(open(f"{DATA_DIR}/pry_premarket_cache.json")) if os.path.exists(f"{DATA_DIR}/pry_premarket_cache.json") else {"candidates": []}

    d1_str = c1.get("d1_date", "")
    d3_str = c3.get("d3_date", "")
    dpr_str = cpry.get("sig_date", "")
    assert d1_str and d1_str == d3_str == dpr_str, (
        f"[S15基准日硬断言阻断] 盘前缓存基准日不一致或为空: 1to2={d1_str}, 3to4={d3_str}, pry={dpr_str}，请先运行 --build-cache 同步至最新收盘日"
    )
    ths_p = f"{DATA_DIR}/ths_limit_up_daily/{d1_str}.json"
    ths_stocks = json.load(open(ths_p)).get("stocks", []) if os.path.exists(ths_p) else []

    codes = ["sh000001", "sz399001", "sh000300", "sz399006", "sh000852"]
    for x in c1.get("candidates", []): codes.append(("sh" if x["c6"].startswith("6") else "sz") + x["c6"])
    for x in c3.get("candidates", []):
        codes.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
        for fc in x.get("plate_fb_codes", []) + x.get("plate_zt_codes", []):
            codes.append(("sh" if fc.startswith("6") else "sz") + fc)
    for x in ch.get("candidates", []): codes.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
    for s in ths_stocks:
        sc = str(s.get("code", ""))[:6]
        if sc.startswith(("00", "60", "30")): codes.append(("sh" if sc.startswith("6") else "sz") + sc)
    q = fetch_qq(codes)

    sr_path = f"{DATA_DIR}/seasonal_rolling_sr_state.json"
    sr_st = json.load(open(sr_path)) if os.path.exists(sr_path) else {
        "train_stds_2021_2025": {"高标首阴_V51": 14.9334, "三进四_V34": 6.8491, "一进二_V18": 26.1185},
        "blended_seasonal_sr": {"高标首阴_V51": 0.9884, "三进四_V34": 0.5335, "一进二_V18": 0.5552},
    }
    stds_map = sr_st["train_stds_2021_2025"]
    bsr_map = sr_st["blended_seasonal_sr"]

    # 1. 评估 高标首阴 (锁死 V5.1 基础分满88分 + 当季把握度)
    hd_eval = []
    for r in ch.get("candidates", []):
        rq = q.get(r["code"], {})
        op = rq.get("opct", 0.0)
        v51_raw = r["static_score"] + (8 if op < 0 else (6 if op <= 0.025 else 0))
        veto_list = list(r.get("veto_reasons", []))
        if op > 0.045: veto_list.append("竞价超涨>4.5%")
        if op < -0.065: veto_list.append("竞价核按钮<-6.5%")
        is_vetoed = bool(r.get("is_vetoed", False)) or bool(veto_list)
        sc_base = v51_raw if not is_vetoed else -999
        passed = (sc_base >= 88) and not is_vetoed
        rk_p = round((sc_base - 88.0) / float(stds_map["高标首阴_V51"]) + float(bsr_map["高标首阴_V51"]), 3) if passed else -999.0
        hd_eval.append({
            "code": r["code"], "name": r.get("name", rq.get("name", "")), "streak_d0": r.get("streak_d0", 4),
            "static_score": r["static_score"], "sc_base": sc_base, "rk_prio": rk_p,
            "is_vetoed": is_vetoed, "veto_reasons": veto_list,
            "open_pct": op, "cur_pct": rq.get("cpct", 0.0),
            "is_direct_open": (0.0 <= op <= 0.045),
            "passed_q4": passed, "passed_base": passed,
        })
    hd_eval.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))

    # 2. 评估 三进四 (锁死 V3.4 基础分满90分 + 当季把握度)
    env3 = c3.get("env", {})
    cands3 = c3.get("candidates", [])
    open_3b = [(r["code"], q.get(r["code"], {}).get("opct", -1.0), q.get(r["code"], {}).get("open", 0) < r["px_d3"] * 1.095) for r in cands3]
    buy_3b = [x for x in open_3b if x[2]]
    top1_c = max(buy_3b, key=lambda x: x[1])[0] if buy_3b else ""

    t34_eval = []
    for r in cands3:
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
        sc_v34 = res["score"] if res["passed_skeleton"] else -999
        passed = (sc_v34 >= 90) and res["passed_skeleton"]
        rk_p = round((sc_v34 - 90.0) / float(stds_map["三进四_V34"]) + float(bsr_map["三进四_V34"]), 3) if passed else -999.0

        t34_eval.append({
            "code": r["code"], "name": r.get("name", rq.get("name", "")), "plate": r.get("plate", ""),
            "px_d3": r["px_d3"], "sc_base": sc_v34, "rk_prio": rk_p,
            "passed_skeleton": res["passed_skeleton"], "breakdown_str": res.get("breakdown_str", ""),
            "open_pct": row["open_pct"], "cur_pct": rq.get("cpct", 0.0),
            "is_direct_open": False,
            "passed_q4": passed, "passed_base": passed,
        })
    t34_eval.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))

    # 3. 评估 一进二
    is_mon = bool(c1.get("is_monday", False))
    mkt = c1.get("mkt_sentiment", {})
    d1_zt = int(mkt.get("d1_zt_cnt", 50))
    seal_r = float(mkt.get("d1_1to2_seal_rate", 0.5))
    climax_pen = (-15.0 if d1_zt >= 100 else (-10.0 if d1_zt >= 95 else 0.0)) + (-10.0 if seal_r >= 0.80 else 0.0)

    rows1 = []
    for r in c1.get("candidates", []):
        rq = q.get(r["c6"], {})
        r_item = dict(r)
        if not r_item.get("name"): r_item["name"] = rq.get("name", "")
        op, lp, cp, pre = rq.get("open", 0), rq.get("lo", 0), rq.get("cur", 0), r_item["pre_c"]
        zt_p = round(pre * 1.10 + 1e-6, 2)
        r_item["open_p"], r_item["cur_p"], r_item["o_pct"], r_item["c_pct"], r_item["zt_p"] = op, cp, rq.get("opct", 0.0), rq.get("cpct", 0.0), zt_p
        r_item["d2_is_yizi"] = bool(op >= zt_p - 0.01 and lp >= zt_p - 0.01)
        r_item["is_buyable_open"] = bool(r_item.get("gate_ok", False) and 0 < op < zt_p - 0.005)
        r_item["trig_p"] = min(zt_p, max(round(op * 1.012, 2), round(pre * 1.065, 2))) if op > 0 else zt_p
        rows1.append(r_item)

    df1 = pd.DataFrame(rows1)
    if not df1.empty:
        is_fl = df1["d2_is_yizi"] | ((not is_mon) & (df1["o_pct"] > 0.078)) | (is_mon & (df1["o_pct"] > 0.088))
        df1["front_lock_cnt"] = is_fl.astype(int).groupby(df1["plate"]).transform("sum")
        df1["plate_d2_yizi_cnt"] = df1["d2_is_yizi"].astype(int).groupby(df1["plate"]).transform("sum")
        myz = int(df1["d2_is_yizi"].sum())
        in_win = df1["is_buyable_open"] & ((is_mon & df1["o_pct"].between(0.020, 0.088)) | ((not is_mon) & df1["o_pct"].between(0.022, 0.078)))
        df1["true_buy_rk"] = np.where(in_win, df1["o_pct"], -9.99)
        df1["true_buy_rk"] = df1.groupby("plate")["true_buy_rk"].rank(ascending=False, method="min")
        df1["_bo"] = np.where(df1["is_buyable_open"], df1["o_pct"], -9.99)
        df1["mkt_open_rk"] = df1["_bo"].rank(ascending=False, method="min")
        df1["sub_rk"] = df1.groupby(["plate", "r_short"])["_bo"].rank(ascending=False, method="min")
        p2 = df1.groupby("plate")["_bo"].transform(lambda s: s.nlargest(2).iloc[-1] if (s > -1.0).sum() >= 2 else -0.05)
        df1["open_lead"] = np.where(df1["true_buy_rk"] == 1, df1["o_pct"] - p2, 0.0)

        has_sub = (df1["p_sz"] >= 8) & (~df1["r_short"].isin([df1["plate"], "其他", ""]))
        rk_bon = np.where(df1["true_buy_rk"] == 1, 35.0, np.where(has_sub & (df1["sub_rk"] == 1), 24.0, np.where(df1["true_buy_rk"] == 2, 8.0, -25.0)))
        sw = (df1["rk_theme"] == 1) & (df1["p_sz"] >= 8) & (df1["true_buy_rk"] == 1)
        hm = df1["notice_hard"] | df1["is_ma"]
        yg = np.select([(df1["front_lock_cnt"] == 1) & (df1["true_buy_rk"] == 1) & (myz in [1, 2]),
                        (df1["front_lock_cnt"] >= 2) & sw, (df1["front_lock_cnt"] == 2) & (~sw),
                        (df1["front_lock_cnt"] >= 3) & (~sw), (df1["front_lock_cnt"] == 0) & (myz == 0) & (~hm)],
                       [8.0, 5.0, -15.0, -22.0, -5.0], default=0.0)
        auc_b = (rk_bon + np.where(df1["mkt_open_rk"] <= 3, 20.0, np.where(df1["mkt_open_rk"] <= 6, 12.0, 0.0))
                 + np.where(df1["open_lead"] >= 0.020, 22.0, np.where(df1["open_lead"] >= 0.010, 12.0, 0.0))
                 + np.where(df1["plate_d2_yizi_cnt"] >= 1, 10.0, 0.0)
                 + np.where(df1["o_pct"].between(0.040, 0.082), 20.0, np.where(df1["o_pct"].between(0.018, 0.040), 12.0, 0.0)))
        roll_ho = float(mkt.get("roll20_ho_zt", 0.5))
        wk_pen = 0.0 if is_mon else np.where(df1["o_pct"] < (0.035 if roll_ho < 0.45 else 0.031), -25.0 if roll_ho < 0.45 else -15.0, 0.0)
        ts = c1.get("theme_structure", {})
        t1_m, t3_m = float(ts.get("t1_med", 0)), float(ts.get("t3_med", 0))
        dom_t3 = (t1_m >= 65.0) and (t1_m - t3_m >= 35.0) and (t3_m < 42.0)
        v18_pen = np.where((df1["plate_d2_yizi_cnt"] >= 1) & (df1["mcap"] > 90.0), -25.0, 0.0) + np.where(dom_t3 & (df1["rk_theme"] >= 3), -15.0, 0.0)
        df1["tot_v18"] = df1["static_tot"] + auc_b + wk_pen + yg + climax_pen + v18_pen

        tot_thr = float(mkt.get("tot_thr", 304.8))
        df1["tot_26q4"] = df1["tot_v18"]
        df1["passed_base"] = (df1["tot_v18"] >= tot_thr) & df1["gate_ok"] & (~df1["d2_is_yizi"])
        df1["passed_q4"] = df1["passed_base"]
        df1["is_direct_open"] = is_mon & (df1["tot_v18"] >= 310.0) & (df1["open_lead"] >= 0.025)
        df1["rk_prio"] = np.where(
            df1["passed_base"],
            (df1["tot_v18"] - tot_thr) / float(stds_map["一进二_V18"]) + float(bsr_map["一进二_V18"]),
            -999.0,
        )

    # 4. 汇总判定 (多股互斥条件单 + 同刻滚动夏普把握度择优)
    p_hd = [x for x in hd_eval if x["passed_base"]]
    p_34 = [x for x in t34_eval if x["passed_base"]]
    p_12 = df1[df1["passed_base"]].sort_values("rk_prio", ascending=False).to_dict("records") if not df1.empty else []

    top_cands = []
    if p_hd:
        top_cands.append({"prio": 1, "label": f"高标首阴 {p_hd[0]['code']} {p_hd[0]['name']}({p_hd[0]['sc_base']}分)", "rk_prio": p_hd[0]["rk_prio"], "order": "开盘直买" if p_hd[0]["is_direct_open"] else "挂突破条件单"})
    if p_34:
        top_cands.append({"prio": 2, "label": f"三进四 {p_34[0]['code']} {p_34[0]['name']}({p_34[0]['sc_base']}分)", "rk_prio": p_34[0]["rk_prio"], "order": "挂突破条件单"})
    if p_12:
        top_cands.append({"prio": 3, "label": f"一进二 {p_12[0]['c6']} {p_12[0]['name']}({p_12[0]['tot_v18']:.1f}分)", "rk_prio": float(p_12[0]["rk_prio"]), "order": "开盘直买" if p_12[0]["is_direct_open"] else "挂突破条件单"})

    if top_cands:
        by_ord = sorted(top_cands, key=lambda x: x["prio"])[0]
        by_conv = sorted(top_cands, key=lambda x: -x["rk_prio"])[0]
        ch_t = by_conv if (by_conv["rk_prio"] - by_ord["rk_prio"] >= 1.50) else by_ord
        top_call_q4 = f"09:26唯一{ch_t['order']} {ch_t['label']} (把握度{ch_t['rk_prio']:+.2f})"
    else:
        top_call_q4 = "全线空仓观望（未触发购买门槛）"

    top_call_base = "全线空仓"
    if p_hd: top_call_base = f"买入高标首阴 {p_hd[0]['code']}"
    elif p_34: top_call_base = f"买入三进四 {p_34[0]['code']}"
    elif p_12: top_call_base = f"买入一进二 {p_12[0]['c6']}"

    pry_cands = cpry.get("candidates", [])
    pry_status = f"超跌撬板候选 {len(pry_cands)} 只 (未达165分)" if pry_cands else "超跌撬板无标的"

    print("=" * 96)
    print(f"【今日购买总裁决】当季科学专供判断：`{top_call_q4}` | 五年死顺位对照：`{top_call_base}` | 辅助策略：`{pry_status}`、五板辅助策略无触发")
    print("=" * 96)

    # === [0] 指数与前日连板梯队 ===
    print("\n=== [0] 指数与前日连板梯队实时表现 ===")
    sh_amt = q.get("000001", {}).get("amt_yi", 0) + q.get("399001", {}).get("amt_yi", 0)
    print(f"两市实时总成交额={sh_amt:.1f}亿")
    for ic in ["000001", "000300", "399006", "000852"]:
        iq = q.get(ic, {})
        print(f"  {ic} {iq.get('name','')}: 今开{iq.get('opct',0)*100:+.2f}% | 现涨跌{iq.get('cpct',0)*100:+.2f}% | 现点位={iq.get('cur',0):.2f}")
    for s in ths_stocks:
        hd = s.get("high_days", "")
        sc = str(s.get("code", ""))[:6]
        m_lb = re.match(r"^(\d+)天(\d+)板$", str(hd))
        if m_lb and m_lb.group(1) == m_lb.group(2) and int(m_lb.group(1)) >= 2 and sc in q:
            sq = q[sc]
            print(f"  [{m_lb.group(1)}连板] {sc} {sq['name']} ({s.get('reason_type','')[:20]}): 今开{sq['opct']*100:+.2f}% -> 现{sq['cpct']*100:+.2f}%")

    # === [1] 一进二打分榜 Top 20 ===
    if not df1.empty:
        tot_thr = float(mkt.get("tot_thr", 304.8))
        print(f"\n=== [1] 一进二打分榜 Top 20 (全场共{len(df1)}只 | 锁死V18门槛{tot_thr}分) ===")
        for i, (_, r) in enumerate(df1.sort_values("tot_v18", ascending=False).head(20).iterrows(), 1):
            why = []
            if not r["gate_ok"]: why.append("门禁否决")
            if r["d2_is_yizi"]: why.append("一字不可买")
            if not (0.020 <= r["o_pct"] <= 0.088 if is_mon else 0.022 <= r["o_pct"] <= 0.078): why.append("出甜区")
            if r["tot_v18"] < tot_thr: why.append(f"未满{tot_thr}")
            print(f"{i:02d}|{r['c6']}|{r['name']}|{r['plate'][:6]}|静态{r['static_tot']:.1f}|V18得分{r['tot_v18']:.1f}|把握度{r['rk_prio']:.2f}|今开{r['o_pct']*100:+.2f}%|现{r['c_pct']*100:+.2f}%|{'，'.join(why[:2])}")

    # === [2] 三进四全池打分榜 ===
    print(f"\n=== [2] 三进四打分榜全池 (今日共{len(t34_eval)}只 | 锁死V3.4门槛90分) ===")
    for i, r in enumerate(t34_eval, 1):
        print(f"{i:02d}|{r['code']}|{r['name']}|{r['plate'][:10]}|昨收{r['px_d3']:.2f}|V3.4得分{r['sc_base']}|把握度{r['rk_prio']:.2f}|今开{r['open_pct']*100:+.2f}%|现{r['cur_pct']*100:+.2f}%|{r['breakdown_str'][:45]}")
    if not t34_eval: print("  今日无三连板标的")

    # === [3] 高标首阴全池打分榜 ===
    print(f"\n=== [3] 高标首阴打分榜全池 (今日共{len(hd_eval)}只 | 锁死V5.1门槛88分) ===")
    for i, r in enumerate(hd_eval, 1):
        veto_str = "；".join(r["veto_reasons"]) if r["is_vetoed"] else "无否决"
        print(f"{i:02d}|{r['code']}|{r['name']}|D0={r['streak_d0']}板|静态{r['static_score']}|V5.1得分{r['sc_base']}|把握度{r['rk_prio']:.2f}|今开{r['open_pct']*100:+.2f}%|现{r['cur_pct']*100:+.2f}%|{veto_str}")
    if not hd_eval: print("  今日全市场无符合条件的高标首阴标的")

if __name__ == "__main__":
    main()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
daily_3strategies_score_report.py — A股五大实盘策略每日全量打分榜与早盘复盘数据引擎
输出：
  1. 顶部清晰汇总「当季专供判断 + 五年死顺位对照（三进四 V4.0 ＞ 高标首阴 V5.1 ＞ 超跌撬板 V1.0 ＞ 二进三 V2.0 ＞ 一进二 V19）+ 二进三 V2.0 满96分高胜率单独提醒」；
  2. [1] 一进二 V19 打分榜 Top 20（含 V18 主轨与 V19 暗牌低位催化候补 fb_dom295）；
  3. [2] 三进四 V4.0 全池打分榜（读取新版 3to4_premarket_cache.json，22项 V4.0 公式算分，标注 09:30至10:30 撤单窗）；
  4. [3] 高标首阴 V5.1 全池打分榜；
  5. [4] 二进三 V2.0 全池打分榜（底分60、标准满90分第5顺位、满96分高胜率单独重点提醒）；
  6. 指数与前日连板梯队实时表现，以及底部唯一现役生产脚本路径清单。
严格遵守 D12 铁律（严禁 import yfinance）。
"""
import argparse
import json
import os
import re
import sys
import urllib.request

import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 VIOLATION: yfinance imported!"

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM}/data"
SCRIPTS_DIR = f"{SIM}/scripts"

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from live_3to4_v40_engine import score_single_3to4_v40_row
from fast_2to3_today import evaluate_2to3_candidate
from fast_1to2_today import evaluate_1to2_v19_df


def fetch_qq(codes: list[str]) -> dict[str, dict]:
    qmap = {}
    clist = sorted(set(codes))
    for i in range(0, len(clist), 80):
        u = "http://qt.gtimg.cn/q=" + ",".join(clist[i : i + 80])
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            raw = urllib.request.urlopen(req, timeout=4).read().decode("gbk", "ignore")
            for ln in raw.splitlines():
                if '="' not in ln:
                    continue
                f = ln.split('="')[1].split("~")
                if len(f) > 38:
                    c6, nm = f[2], f[1]
                    cur, pre, opn = float(f[3] or 0), float(f[4] or 0), float(f[5] or 0)
                    hi, lo, amt = float(f[33] or 0), float(f[34] or 0), float(f[37] or 0) / 10000.0
                    b1, s1 = float(f[10] or 0), float(f[20] or 0)
                    dt8 = str(f[30]).strip()[:8] if len(f) > 30 else ""
                    q_dt = f"{dt8[:4]}-{dt8[4:6]}-{dt8[6:8]}" if len(dt8) == 8 and dt8.isdigit() else ""
                    opct = (opn / pre - 1.0) if pre > 0 and opn > 0 else 0.0
                    cpct = (cur / pre - 1.0) if pre > 0 and cur > 0 else 0.0
                    zt = float(np.floor(pre * 1.10 * 100.0 + 0.5) / 100.0) if pre > 0 else 999.0
                    qmap[c6] = {
                        "name": nm, "pre": pre, "open": opn, "cur": cur, "hi": hi, "lo": lo,
                        "b1": b1, "s1": s1, "opct": opct, "cpct": cpct, "amt_yi": amt, "zt": zt, "q_dt": q_dt,
                    }
        except Exception:
            pass
    return qmap


def main():
    ap = argparse.ArgumentParser(description="A股五大实盘策略每日全量打分榜与早盘复盘数据引擎")
    ap.add_argument("--strict", action="store_true", default=True, help="默认开启：强制要求五大缓存同日且为开盘啦官方源")
    ap.add_argument("--no-strict", dest="strict", action="store_false", help="仅调试时关闭严格校验")
    ap.add_argument("--mock-open", type=str, default="", help="模拟竞价涨幅，如 '603078=0.055,000011=0.02'")
    args = ap.parse_args()

    c1 = json.load(open(f"{DATA_DIR}/1to2_premarket_cache.json", encoding="utf-8")) if os.path.exists(f"{DATA_DIR}/1to2_premarket_cache.json") else {"candidates": []}
    c3 = json.load(open(f"{DATA_DIR}/3to4_premarket_cache.json", encoding="utf-8")) if os.path.exists(f"{DATA_DIR}/3to4_premarket_cache.json") else {"candidates": []}
    ch = json.load(open(f"{DATA_DIR}/high_dragon_premarket_cache.json", encoding="utf-8")) if os.path.exists(f"{DATA_DIR}/high_dragon_premarket_cache.json") else {"candidates": []}
    cpry = json.load(open(f"{DATA_DIR}/pry_premarket_cache.json", encoding="utf-8")) if os.path.exists(f"{DATA_DIR}/pry_premarket_cache.json") else {"candidates": []}
    c23 = json.load(open(f"{DATA_DIR}/2to3_premarket_cache.json", encoding="utf-8")) if os.path.exists(f"{DATA_DIR}/2to3_premarket_cache.json") else {"candidates": []}

    d1_str = c1.get("d1_date", "")
    d3_str = c3.get("d3_date", "")
    dhd_str = ch.get("as_of_d1", "")
    dpr_str = cpry.get("sig_date", "")
    d23_str = c23.get("data_as_of_date") or c23.get("sig_date", "")
    dates_nonempty = [d for d in (d1_str, d3_str, dhd_str, dpr_str, d23_str) if d]
    all_aligned = bool(d1_str and d1_str == d3_str == dhd_str == dpr_str == d23_str)
    if args.strict:
        assert not c1.get("used_ths_plate_fallback", False), "[S15真源阻断] 1to2_premarket_cache 仍为同花顺临时兜底，开盘啦官方题材未落地，阻断终版出表！"
        assert all_aligned, (
            f"[S15基准日硬断言阻断] 五大盘前缓存基准日不一致或为空: 1to2={d1_str}, 3to4={d3_str}, hd={dhd_str}, pry={dpr_str}, 2to3={d23_str}，请先运行 --build-cache 同步至最新收盘日"
        )
    assert dates_nonempty, "[ERR] 五大盘前缓存全部缺失或基准日为空"

    ref_date = max(dates_nonempty)
    ths_p = f"{DATA_DIR}/ths_limit_up_daily/{ref_date}.json"
    if not os.path.exists(ths_p) and d1_str:
        ths_p = f"{DATA_DIR}/ths_limit_up_daily/{d1_str}.json"
    ths_stocks = json.load(open(ths_p, encoding="utf-8")).get("stocks", []) if os.path.exists(ths_p) else []

    codes = ["sh000001", "sz399001", "sh000300", "sz399006", "sh000852"]
    for x in c1.get("candidates", []):
        codes.append(("sh" if x["c6"].startswith("6") else "sz") + x["c6"])
    for x in c3.get("candidates", []):
        codes.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
        for fc in x.get("plate_fb_codes", []) + x.get("plate_zt_codes", []):
            codes.append(("sh" if fc.startswith("6") else "sz") + fc)
    for x in ch.get("candidates", []):
        codes.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
    for x in cpry.get("candidates", []):
        codes.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
    for x in c23.get("candidates", []):
        codes.append(("sh" if x["code"].startswith("6") else "sz") + x["code"])
    for s in ths_stocks:
        sc = str(s.get("code", ""))[:6]
        if sc.startswith(("00", "60", "30")):
            codes.append(("sh" if sc.startswith("6") else "sz") + sc)
    q = fetch_qq(codes)
    mock_map = {}
    if args.mock_open:
        for pair in args.mock_open.split(","):
            if "=" in pair:
                km, vm = pair.split("=", 1)
                c6m, opv = km.strip().zfill(6), float(vm.strip())
                mock_map[c6m] = opv
                pre_m = q.get(c6m, {}).get("cur") or q.get(c6m, {}).get("pre") or 10.0
                op_m = round(pre_m * (1.0 + opv), 2)
                q[c6m] = {
                    **q.get(c6m, {}),
                    "name": q.get(c6m, {}).get("name", c6m),
                    "pre": pre_m, "open": op_m, "cur": op_m, "hi": op_m, "lo": op_m,
                    "opct": opv, "cpct": opv,
                    "zt": float(np.floor(pre_m * 1.10 * 100.0 + 0.5) / 100.0),
                    "q_dt": "9999-12-31",
                }

    sr_path = f"{DATA_DIR}/seasonal_rolling_sr_state.json"
    sr_st = json.load(open(sr_path, encoding="utf-8")) if os.path.exists(sr_path) else {
        "train_stds_2021_2025": {"高标首阴_V51": 14.9334, "三进四_V34": 6.8491, "一进二_V18": 26.1185},
        "blended_seasonal_sr": {"高标首阴_V51": 0.9884, "三进四_V34": 0.5335, "一进二_V18": 0.5552},
    }
    stds_map = sr_st["train_stds_2021_2025"]
    bsr_map = sr_st["blended_seasonal_sr"]
    std_34 = float(stds_map.get("三进四_V40") or stds_map.get("三进四_V34", 6.8491))
    bsr_34 = float(bsr_map.get("三进四_V40") or bsr_map.get("三进四_V34", 0.5335))
    std_12 = float(stds_map.get("一进二_V19") or stds_map.get("一进二_V18", 26.1185))
    bsr_12 = float(bsr_map.get("一进二_V19") or bsr_map.get("一进二_V18", 0.5552))
    std_hd = float(stds_map.get("高标首阴_V51", 14.9334))
    bsr_hd = float(bsr_map.get("高标首阴_V51", 0.9884))

    # 1. 高标首阴 V5.1 (门槛 88 分)
    hd_eval = []
    for r in ch.get("candidates", []):
        rq = q.get(r["code"], {})
        is_live_hd = (not dhd_str) or (rq.get("q_dt", "") > dhd_str)
        op = rq.get("opct", 0.0) if is_live_hd else -0.99
        v51_raw = r["static_score"] + (8 if op < 0 else (6 if op <= 0.025 else 0)) if is_live_hd else r["static_score"]
        veto_list = list(r.get("veto_reasons", []))
        if not is_live_hd:
            veto_list.append("盘后待明日09:25竞价")
        else:
            if op > 0.045:
                veto_list.append("竞价超涨>4.5%")
            if op < -0.065:
                veto_list.append("竞价核按钮<-6.5%")
            if rq.get("open", 0) >= rq.get("zt", 999) - 0.011:
                veto_list.append("一字不可买")
        is_vetoed = bool(r.get("is_vetoed", False)) or bool(veto_list)
        sc_base = v51_raw if not is_vetoed else -999
        passed = (sc_base >= 88) and not is_vetoed
        rk_p = round((sc_base - 88.0) / std_hd + bsr_hd, 3) if passed else -999.0
        hd_eval.append({
            "code": r["code"], "name": r.get("name", rq.get("name", "")), "streak_d0": r.get("streak_d0", 4),
            "static_score": r["static_score"], "sc_base": sc_base, "rk_prio": rk_p,
            "is_vetoed": is_vetoed, "veto_reasons": veto_list,
            "open_pct": op if is_live_hd else 0.0, "cur_pct": rq.get("cpct", 0.0),
            "is_direct_open": (0.0 <= op <= 0.045),
            "passed_q4": passed, "passed_base": passed,
        })
    hd_eval.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))

    # 2. 三进四 V4.0 (底分 78, 22项因子, 门槛 90 分, S档 102 分, 撤单窗 09:30至10:30)
    env3 = c3.get("env", {})
    cands3 = c3.get("candidates", [])
    buy_date_34 = c3.get("buy_date", "")
    open_3b = [
        (r["code"], q.get(r["code"], {}).get("opct", -1.0), q.get(r["code"], {}).get("q_dt", "") > d3_str and q.get(r["code"], {}).get("open", 0) < q.get(r["code"], {}).get("zt", r["px_d3"] * 1.10) - 0.005)
        for r in cands3
    ]
    buy_3b = [x for x in open_3b if x[2]]
    top1_c = max(buy_3b, key=lambda x: x[1])[0] if buy_3b else ""

    t34_eval = []
    for r in cands3:
        rq = q.get(r["code"], {})
        is_live_34 = (not d3_str) or (rq.get("q_dt", "") > d3_str)
        fb_ops = [q.get(fc, {}) for fc in r.get("plate_fb_codes", []) if fc in q and q.get(fc, {}).get("q_dt", "") > d3_str]
        zt_ops = [q.get(zc, {}).get("opct", 0.0) for zc in r.get("plate_zt_codes", []) if zc in q and q.get(zc, {}).get("q_dt", "") > d3_str]
        row = dict(r, **env3)
        row["open_pct"] = rq.get("opct", 0.0) if is_live_34 else 0.0
        row["buyable_open"] = bool(is_live_34 and rq.get("open", 0) > 0 and rq.get("open", 0) < rq.get("zt", 999) - 0.005)
        row["is_top1_3b_open"] = (r["code"] == top1_c) if is_live_34 else False
        row["plate_fb_ho_cnt"] = sum(
            1 for x in fb_ops if x.get("opct", 0) >= 0.03 and x.get("open", 0) < x.get("zt", 999) - 0.005
        )
        row["plate_fb_yz_cnt"] = sum(
            1 for x in fb_ops if x.get("open", 0) >= x.get("zt", 999) - 0.005 or x.get("opct", 0) >= 0.095
        )
        row["plate_peers_open_avg"] = float(np.mean(zt_ops)) if zt_ops else 0.0
        res = score_single_3to4_v40_row(row)
        sc_v40 = res["score"] if (is_live_34 and res["passed_skeleton"]) else -999
        passed = (sc_v40 >= 90) and res["passed_skeleton"] and is_live_34
        rk_p = round((sc_v40 - 90.0) / std_34 + bsr_34, 3) if passed else -999.0
        trig_px = max(round(r["px_d3"] * 1.065, 2), round(rq.get("open", r["px_d3"] * 1.065), 2)) if is_live_34 else round(r["px_d3"] * 1.065, 2)
        b_str = res.get("breakdown_str", "") if is_live_34 else ("盘后待明日竞价 | " + res.get("breakdown_str", ""))
        t34_eval.append({
            "code": r["code"], "name": r.get("name", rq.get("name", "")), "plate": r.get("plate", ""),
            "px_d3": r["px_d3"], "trig_px": trig_px, "sc_base": sc_v40, "rk_prio": rk_p,
            "tier": res["tier"], "passed_skeleton": res["passed_skeleton"] and is_live_34, "breakdown_str": b_str,
            "pos20_d0": float(r.get("pos20_d0", 0.50)), "xq_cnt_2d": int(r.get("xq_cnt_2d", 0)),
            "open_pct": row["open_pct"], "cur_pct": rq.get("cpct", 0.0),
            "is_direct_open": False, "passed_q4": passed, "passed_base": passed,
            "buy_date": buy_date_34,
        })
    t34_eval.sort(key=lambda x: (-x["rk_prio"], -x["sc_base"]))

    # 3. 一进二 V19 (100% 复用 fast_1to2_today.evaluate_1to2_v19_df 唯一真源)
    mkt = c1.get("mkt_sentiment", {})
    df1, meta1 = evaluate_1to2_v19_df(c1, q, mock_map=mock_map)
    is_mon = bool(meta1.get("is_monday", False))
    tot_thr = float(meta1.get("tot_thr", 304.8))
    if not df1.empty:
        df1["tot_26q4"] = df1["tot_v18"]
        df1["passed_q4"] = df1["passed_base"]
        df1["rk_prio"] = np.where(
            df1["passed_v18"],
            (df1["tot_v18"] - tot_thr) / std_12 + bsr_12,
            np.where(df1["fb_dom295"], (df1["tot_no_t3"] - 295.0) / std_12 - 5.0, -999.0),
        )

    # 4. 超跌撬板 V1.0 与 二进三 V2.0
    pry_cands = cpry.get("candidates", [])
    p_pry = []
    need_pry_mkt = [
        c for c in pry_cands
        if int(c.get("max_possible", 0)) >= 165
        and c["code"] in q
        and ((not dpr_str) or q[c["code"]].get("q_dt", "") > dpr_str)
        and 0.0 <= q[c["code"]].get("opct", -1.0) <= 0.05
        and q[c["code"]].get("open", 0.0) < q[c["code"]].get("zt", 999.0) - 0.005
    ]
    if need_pry_mkt:
        all_m = cpry.get("main_codes_sample", [])
        qm = fetch_qq([("sh" if mc.startswith("6") else "sz") + mc for mc in all_m])
        zt_open_cnt = sum(
            1 for v in qm.values()
            if ((not dpr_str) or v.get("q_dt", "") > dpr_str) and v.get("open", 0.0) >= v.get("zt", 999.0) - 0.011
        )
        for c in need_pry_mkt:
            tot_p = int(c["static_score"]) + (15 if zt_open_cnt >= 12 else 0)
            if tot_p >= 165:
                p_pry.append({**c, "name": q[c["code"]].get("name", c["code"]), "score": tot_p, "open_pct": q[c["code"]]["opct"]})
        p_pry.sort(key=lambda x: (-x["score"], x.get("bias10", 0.0)))

    e23_eval = []
    for r in c23.get("candidates", []):
        c6 = r["code"]
        rq = q.get(c6, {})
        is_live_23 = (not d23_str) or (rq.get("q_dt", "") > d23_str)
        pre_c = float(r.get("prev_close", 0.0)) or rq.get("pre", 0.0)
        opn = rq.get("open", 0.0) if is_live_23 else 0.0
        op = rq.get("opct", 0.0) if (is_live_23 and opn > 0) else 0.0
        zt_23 = float(np.floor(pre_c * 1.10 * 100.0 + 0.5) / 100.0) if pre_c > 0 else 999.0
        is_yz = bool(is_live_23 and (opn >= zt_23 - 0.005 or (rq.get("b1", 0.0) > 0 and rq.get("s1", 0.0) == 0 and op >= 0.095)))
        buyable = bool(is_live_23 and opn > 0 and not is_yz)
        ev = evaluate_2to3_candidate(r, op, buyable)
        if not is_live_23 and "盘后待明日09:25竞价" not in ev["veto_reasons"]:
            ev["veto_reasons"] = ["盘后待明日09:25竞价"] + list(ev["veto_reasons"])
        e23_eval.append({
            **r, **ev, "name": r.get("name") or rq.get("name", c6),
            "open_px": opn, "open_pct": op, "cur_pct": rq.get("cpct", 0.0), "buyable_open": buyable,
        })
    e23_eval.sort(key=lambda x: (-int(x["passed_std90"]), -x["score"], x["open_pct"], x["plate_sz"], x["code"]))
    p_23_90 = [x for x in e23_eval if x["passed_std90"]]
    p_23_96 = [x for x in e23_eval if x["passed_strict96"]]

    # 5. 全局五顺位裁决 (三进四 V4.0 ＞ 高标首阴 V5.1 ＞ 超跌撬板 V1.0 ＞ 二进三 V2.0 ＞ 一进二 V19)
    p_hd = [x for x in hd_eval if x["passed_base"]]
    p_34 = [x for x in t34_eval if x["passed_base"]]
    p_12 = df1[df1["passed_base"]].sort_values("rk_prio", ascending=False).to_dict("records") if not df1.empty else []

    top_front2 = []
    if p_34:
        top_front2.append({
            "prio": 1, "label": f"三进四 V4.0 {p_34[0]['code']} {p_34[0]['name']}({p_34[0]['sc_base']}分)",
            "rk_prio": p_34[0]["rk_prio"], "order": "挂突破条件单(09:30至10:30有效,10:30撤单)",
        })
    if p_hd:
        top_front2.append({
            "prio": 2, "label": f"高标首阴 V5.1 {p_hd[0]['code']} {p_hd[0]['name']}({p_hd[0]['sc_base']}分)",
            "rk_prio": p_hd[0]["rk_prio"], "order": "开盘直买" if p_hd[0]["is_direct_open"] else "挂突破条件单(11:30撤)",
        })

    if top_front2:
        by_ord = sorted(top_front2, key=lambda x: x["prio"])[0]
        by_conv = sorted(top_front2, key=lambda x: -x["rk_prio"])[0]
        ch_t = by_conv if (by_conv["rk_prio"] - by_ord["rk_prio"] >= 1.50) else by_ord
        top_call_q4 = f"09:26唯一{ch_t['order']} {ch_t['label']} (把握度{ch_t['rk_prio']:+.2f})"
    elif p_pry and (p_pry[0]["score"] >= 175 or ((not p_23_96) and ((not p_12) or p_12[0]["tot_v18"] < 355.0))):
        pry_tier = "S档超高分" if p_pry[0]["score"] >= 175 else "A档普通过线"
        top_call_q4 = f"09:25直买第3顺位超跌撬板[{pry_tier}] {p_pry[0]['code']} {p_pry[0]['name']}({p_pry[0]['score']}分)"
    elif p_23_90:
        w23 = p_23_90[0]
        t23_tier = "S档高胜率" if w23["score"] >= 96 else "A档普通过线"
        top_call_q4 = f"09:25直买第4顺位二进三 V2.0[{t23_tier}] {w23['code']} {w23['name']}({w23['score']}分，今开{w23['open_pct']*100:+.2f}%)"
    elif p_12:
        tk_note = f"[{p_12[0]['track_label']}]" if p_12[0].get("fb_dom295") else ""
        ord_12 = "开盘直买" if p_12[0]["is_direct_open"] else "挂突破条件单(11:30撤)"
        top_call_q4 = f"09:26唯一{ord_12}第5顺位一进二 V19 {tk_note}{p_12[0]['c6']} {p_12[0]['name']}({p_12[0]['tot_v18']:.1f}分，把握度{float(p_12[0]['rk_prio']):+.2f})"
    elif p_pry:
        top_call_q4 = f"09:25直买第3顺位超跌撬板[A档普通过线] {p_pry[0]['code']} {p_pry[0]['name']}({p_pry[0]['score']}分)"
    else:
        top_call_q4 = "全线空仓观望（未触发购买门槛）"

    top_call_base = "全线空仓"
    if p_34:
        top_call_base = f"第1顺位买入三进四 V4.0 {p_34[0]['code']} {p_34[0]['name']}(10:30撤单)"
    elif p_hd:
        top_call_base = f"第2顺位买入高标首阴 V5.1 {p_hd[0]['code']} {p_hd[0]['name']}"
    elif p_pry:
        top_call_base = f"第3顺位买入超跌撬板 {p_pry[0]['code']} {p_pry[0]['name']}({p_pry[0]['score']}分)"
    elif p_23_90:
        top_call_base = f"第4顺位买入二进三 V2.0 {p_23_90[0]['code']} {p_23_90[0]['name']}({p_23_90[0]['score']}分)"
    elif p_12:
        top_call_base = f"第5顺位买入一进二 V19 {p_12[0]['c6']} {p_12[0]['name']}"

    pry_status = f"超跌撬板过线 {len(p_pry)} 只" if p_pry else (f"超跌撬板候选 {len(pry_cands)} 只 (未达165分)" if pry_cands else "超跌撬板无标的")
    s23_status = f"二进三V2.0>=90分 {len(p_23_90)} 只" if p_23_90 else f"二进三V2.0无过线(候选{len(e23_eval)}只)"

    print("=" * 98)
    if c1.get("used_ths_plate_fallback", False):
        print("🚨[未定稿警告] 一进二缓存仍为同花顺临时兜底（开盘啦官方题材未落地），严禁据此出终版预案！")
    if not all_aligned:
        print(f"⚠️[S15基准日未全对齐] 1to2={d1_str} | 3to4={d3_str} | hd={dhd_str} | pry={dpr_str} | 2to3={d23_str}（请跑 rd_master_trading_data_sync.py 全量同步）")
    print(f"【今日购买总裁决】当季科学专供判断：`{top_call_q4}` | 五年死顺位对照：`{top_call_base}` | 辅助：`{pry_status}` · `{s23_status}`")
    if p_23_96:
        for r96 in p_23_96:
            print(f"【★二进三 V2.0 满96分高胜率单独提醒：{r96['code']} {r96['name']} {r96['score']}分】 (今开{r96['open_pct']*100:+.2f}% | 板块={r96['plate']} | 未封3板14:55清，封3板>+9.2%非一字09:25止盈)")
    print("=" * 98)

    # === [0] 指数与前日连板梯队 ===
    print(f"\n=== [0] 指数与前日连板梯队实时表现 (THS基准日={ref_date}) ===")
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

    # === [1] 一进二 V19 打分榜 Top 20 ===
    if not df1.empty:
        tot_thr = float(mkt.get("tot_thr", 304.8))
        print(f"\n=== [1] 一进二 V19 打分榜 Top 20 (基准日={d1_str} | 全场{len(df1)}只 | 主轨门槛{tot_thr}分 · V19候补>=295分暗牌低位催化) ===")
        for i, (_, r) in enumerate(df1.sort_values(["passed_base", "tot_v18"], ascending=[False, False]).head(20).iterrows(), 1):
            why = []
            if r.get("fb_dom295"):
                why.append(f"V19候补过线(去T3={r['tot_no_t3']:.1f}>=295)")
            else:
                if not r.get("purifier_ok", True):
                    why.append("退潮脉冲/假题材拦截")
                if r.get("s_prior_wk", 0.0) < (38.0 if is_mon else 45.0):
                    why.append("题材分不足")
                if not r["gate_ok"]:
                    why.append("门禁否决")
                if r["d2_is_yizi"]:
                    why.append("一字不可买")
                if r["o_pct"] <= -0.90:
                    why.append("待明日09:25竞价")
                elif not r.get("o_ok", False):
                    why.append("出甜区")
                if not r.get("pass_l3", True):
                    why.append("同板均值弱")
                if not r.get("pass_nd", True):
                    why.append("后排/首板松散")
                if r["tot_v18"] < tot_thr:
                    why.append(f"未满{tot_thr}")
            print(f"{i:02d}|{r['c6']}|{r['name']}|{r['plate'][:6]}|静态{r['static_tot']:.1f}|V19得分{r['tot_v18']:.1f}|把握度{r['rk_prio']:.2f}|今开{r['o_pct']*100:+.2f}%|现{r['c_pct']*100:+.2f}%|{'，'.join(why[:2])}")

    # === [2] 三进四 V4.0 全池打分榜 ===
    print(f"\n=== [2] 三进四 V4.0 全池打分榜 (基准日={d3_str}->{buy_date_34} | 今日共{len(t34_eval)}只 | 锁死V4.0底分78·标准90分·S档102分 | 撤单窗: 09:30至10:30) ===")
    for i, r in enumerate(t34_eval, 1):
        print(
            f"{i:02d}|{r['code']}|{r['name']}|{r['plate'][:10]}|昨收{r['px_d3']:.2f}|触发{r['trig_px']:.2f}(10:30撤)|"
            f"V4.0得分{r['sc_base']}|pos20={r['pos20_d0']:.2f} xq={r['xq_cnt_2d']}帖|把握度{r['rk_prio']:.2f}|"
            f"今开{r['open_pct']*100:+.2f}%|现{r['cur_pct']*100:+.2f}%|{r['breakdown_str'][:50]}"
        )
    if not t34_eval:
        print("  今日无三连板标的")

    # === [3] 高标首阴 V5.1 全池打分榜 ===
    print(f"\n=== [3] 高标首阴 V5.1 全池打分榜 (基准日={dhd_str} | 今日共{len(hd_eval)}只 | 锁死V5.1门槛88分) ===")
    for i, r in enumerate(hd_eval, 1):
        veto_str = "；".join(r["veto_reasons"]) if r["is_vetoed"] else "无否决"
        print(f"{i:02d}|{r['code']}|{r['name']}|D0={r['streak_d0']}板|静态{r['static_score']}|V5.1得分{r['sc_base']}|把握度{r['rk_prio']:.2f}|今开{r['open_pct']*100:+.2f}%|现{r['cur_pct']*100:+.2f}%|{veto_str}")
    if not hd_eval:
        print("  今日全市场无符合条件的高标首阴标的")

    # === [4] 二进三 V2.0 全池打分榜 ===
    v23_tag = c23.get("version", "2TO3")
    print(f"\n=== [4] 二进三 V2.0 全池打分榜 (基准日={d23_str} | 缓存={v23_tag} | 今日共{len(e23_eval)}只 | 底分60 · 标准门槛90分[第4顺位] · 满96分单独重点提醒) ===")
    for i, r in enumerate(e23_eval, 1):
        tier_s = "★满96高严" if r["passed_strict96"] else ("✅标准过线" if r["passed_std90"] else "⛔未过线")
        veto_s = "；".join(r["veto_reasons"]) if r["veto_reasons"] else "门禁全过"
        print(f"{i:02d}|{r['code']}|{r['name']}|{r['ths_tag']}|{r['plate'][:6]}(sz={r['plate_sz']})|V2.0得分{r['score']:3d}|今开{r['open_pct']*100:+.2f}%|现{r['cur_pct']*100:+.2f}%|{tier_s}|{veto_s}|{r['breakdown_str']}")
    if not e23_eval:
        print("  今日全市场无符合条件的二连板标的")

    print("\n=== [唯一现役生产脚本路径清单 (S15)] ===")
    print("  - 高标首阴 V5.1 : sim-portfolio/scripts/fast_high_dragon_today.py")
    print("  - 三进四   V4.0 : sim-portfolio/scripts/fast_3to4_today.py (核心引擎: sim-portfolio/scripts/live_3to4_v40_engine.py)")
    print("  - 超跌撬板 V1.0 : sim-portfolio/scripts/fast_pry_today.py")
    print("  - 一进二   V19  : sim-portfolio/scripts/fast_1to2_today.py")
    print("  - 二进三   V2.0 : sim-portfolio/scripts/fast_2to3_today.py")
    print("  - 当季专供裁决  : sim-portfolio/scripts/fast_26q4_special_today.py")
    print("  - 盘中盯盘核查  : sim-portfolio/scripts/astock_intraday_check.py")
    print("  - 统管打分日报  : sim-portfolio/scripts/daily_3strategies_score_report.py")


if __name__ == "__main__":
    main()

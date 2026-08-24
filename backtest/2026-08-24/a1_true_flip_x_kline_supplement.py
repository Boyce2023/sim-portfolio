#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补充验证: 用"真A1"信号(扣非/净利润由正转负的flip事件, 与主2x2脚本
cross_fundamental_kline_2x2.py里用的"YoY增速方向变化"quasi-A2信号不同)
x K线状态(降降/抬抬/混合), 检验主任务问题①"双向下到底是最好还是最差"
在真A1定义下是否依然成立。

数据来源: kfjlr_flip_returns_full_a_disclosed.csv 里 group=='treatment_turn_negative'
且 ret_5d 非空的14条(即用户给定"A1 5日 treatment n=14"那批, 20d/40d全部右截断
n=0, 故本补充脚本只做5日)。

只14个标的, 串行请求(不用线程池), 每请求timeout=8, 失败立即换新浪源不重试,
不构成WAF风险。

K线状态分类算法与cross_fundamental_kline_2x2.py完全一致(30日切3个10日子窗口,
高点/低点序列各自降降=down, 抬抬=up, 其余=mixed), 取"signal_date当天"分类。

落盘: 本文件路径 + a1_true_flip_x_kline_result.json
"""

import json
import subprocess
import time
import urllib.request

import pandas as pd

WORKDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"
AK_CLI = "/Users/huaichuaibeimeng/.claude/skills/akshare-china/scripts/ak"
FETCH_START = "2026-04-01"
FETCH_END = "2026-08-24"
TIMEOUT = 8


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def tencent_prefix(code):
    return "sh" if code.startswith("6") else "sz"


def fetch_tencent(code):
    pref = tencent_prefix(code)
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="
           f"{pref}{code},day,{FETCH_START},{FETCH_END},320,qfq")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=TIMEOUT).read().decode("utf-8")
    d = json.loads(raw)
    if d.get("code") != 0:
        raise RuntimeError(f"tencent code={d.get('code')}")
    key = pref + code
    node = d["data"][key]
    rows = node.get("qfqday") or node.get("day")
    if not rows:
        raise RuntimeError("empty rows")
    bars = [{"d": r[0], "o": float(r[1]), "c": float(r[2]), "h": float(r[3]),
              "l": float(r[4]), "v": float(r[5])} for r in rows]
    bars.sort(key=lambda x: x["d"])
    return bars


def fetch_ak_fallback(code):
    out = subprocess.run([AK_CLI, "kline", code, "140", "--json"],
                          capture_output=True, text=True, timeout=TIMEOUT).stdout
    data = json.loads(out)
    bars = []
    for r in data:
        try:
            bars.append({"d": r["day"], "o": float(r["open"]), "c": float(r["close"]),
                         "h": float(r["high"]), "l": float(r["low"]), "v": float(r["volume"])})
        except Exception:
            continue
    bars.sort(key=lambda x: x["d"])
    return [b for b in bars if FETCH_START <= b["d"] <= FETCH_END]


def fetch_one_serial(code):
    try:
        bars = fetch_tencent(code)
        if len(bars) >= 30:
            return bars, "tencent_qfq", None
        raise RuntimeError(f"tencent too short n={len(bars)}")
    except Exception as e1:
        try:
            bars = fetch_ak_fallback(code)
            if len(bars) < 30:
                raise RuntimeError(f"fallback too short n={len(bars)}")
            return bars, "ak_sina_noqfq_fallback", None
        except Exception as e2:
            return None, None, f"tencent_fail={e1} | ak_fallback_fail={e2}"


def classify_seq(vals):
    if vals[0] > vals[1] > vals[2]:
        return "降"
    if vals[0] < vals[1] < vals[2]:
        return "抬"
    return "混合"


def kline_label_for(hi_seq, lo_seq):
    if hi_seq == "降" and lo_seq == "降":
        return "down"
    if hi_seq == "抬" and lo_seq == "抬":
        return "up"
    return "mixed"


def kline_state_at(bars, target_date):
    """找 <=target_date 的最后一根bar, 用其前29根+自身共30根算状态。返回 (label, bar_date) 或 (None, None)"""
    idxs = [i for i, b in enumerate(bars) if b["d"] <= target_date]
    if not idxs:
        return None, None
    i = idxs[-1]
    if i < 29:
        return None, None
    window = bars[i - 29: i + 1]
    w1, w2, w3 = window[0:10], window[10:20], window[20:30]
    hi_seq = classify_seq([max(b["h"] for b in w) for w in (w1, w2, w3)])
    lo_seq = classify_seq([min(b["l"] for b in w) for w in (w1, w2, w3)])
    return kline_label_for(hi_seq, lo_seq), bars[i]["d"]


def main():
    t0 = time.time()
    df = pd.read_csv(f"{WORKDIR}/kfjlr_flip_returns_full_a_disclosed.csv", dtype={"code": str})
    df["code"] = df["code"].str.zfill(6)
    t = df[(df.group == "treatment_turn_negative") & df.ret_5d.notna()].copy()
    log(f"真A1(扣非/净利润由正转负) 5日有效treatment样本 n={len(t)}")
    assert len(t) == 14, f"期望n=14, 实际n={len(t)} —— 与已知批次结果不符, 停止"

    results = []
    src_count = {}
    for _, row in t.iterrows():
        code = row["code"]
        sig_date = row["t0_date"] if isinstance(row["t0_date"], str) else row["signal_date"]
        bars, src, err = fetch_one_serial(code)
        time.sleep(0.3)  # 串行节流, 避免任何WAF触发风险
        if bars is None:
            log(f"  {code} 价格拉取失败: {err}")
            results.append({"code": code, "signal_date": sig_date, "kline": None,
                             "ret_5d": row["ret_5d"], "fetch_err": err})
            continue
        src_count[src] = src_count.get(src, 0) + 1
        label, bar_date = kline_state_at(bars, sig_date)
        results.append({"code": code, "signal_date": sig_date, "kline_bar_date": bar_date,
                         "kline": label, "ret_5d": row["ret_5d"]})
        log(f"  {code} @ {sig_date} -> kline={label} (bar={bar_date}, src={src}) ret_5d={row['ret_5d']:+.4f}")

    log(f"价格来源分布: {src_count}, 耗时{time.time()-t0:.1f}s")

    rdf = pd.DataFrame(results)
    rdf.to_csv(f"{WORKDIR}/a1_true_flip_x_kline_detail.csv", index=False)

    out = {"n_total": len(rdf), "by_kline": {}}
    for label in ["down", "up", "mixed", None]:
        sub = rdf[rdf.kline == label] if label is not None else rdf[rdf.kline.isna()]
        vals = sub["ret_5d"].dropna().tolist()
        key = label if label is not None else "unknown(fetch_or_window_fail)"
        out["by_kline"][key] = {
            "n": len(vals),
            "mean_pct": round(sum(vals) / len(vals) * 100, 2) if vals else None,
            "median_pct": round(pd.Series(vals).median() * 100, 2) if vals else None,
            "win_rate_pct": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1) if vals else None,
            "codes": sub["code"].tolist(),
        }

    with open(f"{WORKDIR}/a1_true_flip_x_kline_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 70)
    print("真A1(扣非由正转负) x K线状态, 5日前瞻收益 (n=14全量, 逐格列出)")
    print("=" * 70)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    log(f"落盘: a1_true_flip_x_kline_detail.csv, a1_true_flip_x_kline_result.json")
    return out


if __name__ == "__main__":
    main()

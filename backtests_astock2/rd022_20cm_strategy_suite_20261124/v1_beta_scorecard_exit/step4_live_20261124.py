#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Step 4: Live Scoring Demonstration on 2026-11-23 (Beta Day) -> 2026-11-24 09:25 Open
using Tencent qt.gtimg.cn real-time quotes + finalized V1.0 Pure Integer Scorecard.
"""
import json, urllib.request
import numpy as np
import pandas as pd
from step3_full_d15_eval import compute_score_beta_v1, OUT_DIR


def fetch_tencent_quotes(c6_list: list[str]) -> dict:
    out = {}
    for i in range(0, len(c6_list), 80):
        batch = c6_list[i:i + 80]
        qs = ",".join((f"sh{c}" if c.startswith("68") else f"sz{c}") for c in batch)
        url = f"http://qt.gtimg.cn/q={qs}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        txt = urllib.request.urlopen(req, timeout=8).read().decode("gbk", errors="ignore")
        for ln in txt.strip().split(";"):
            if "~" not in ln:
                continue
            p = ln.split("~")
            if len(p) < 39:
                continue
            c6 = p[2].strip()
            try:
                now = float(p[3]); ycl = float(p[4]); op = float(p[5])
                hi = float(p[33]); lo = float(p[34]); vol = float(p[36]); amt_w = float(p[37])
                out[c6] = {
                    "name": p[1].strip(), "now": now, "yclose": ycl, "open": op,
                    "high": hi, "low": lo, "vol": vol, "amt_yi": amt_w / 10000.0,
                    "pct": float(p[32]), "ts": p[30],
                }
            except Exception:
                continue
    return out


def main():
    base = pd.read_parquet(f"{OUT_DIR}/v1_beta_base_pool.parquet")
    c23 = base[base["dt"] == "2026-11-23"].copy().reset_index(drop=True)
    if c23.empty:
        print("[!] No 2026-11-23 rows found!")
        return

    quotes = fetch_tencent_quotes(c23["c6"].tolist())
    op_list, ycl_list, now_list, hi_list, lo_list, nm_list, buy_list, ts_list = [], [], [], [], [], [], [], []
    for r in c23.itertuples(index=False):
        q = quotes.get(r.c6)
        if not q or q["yclose"] <= 0 or q["open"] <= 0 or q["vol"] <= 0:
            op_list.append(np.nan); ycl_list.append(np.nan); now_list.append(np.nan)
            hi_list.append(np.nan); lo_list.append(np.nan); nm_list.append(r.sec_name_pit)
            buy_list.append(False); ts_list.append("")
            continue
        zt_px = round(q["yclose"] * 1.20, 2)
        buy_ok = (q["open"] < zt_px - 0.011) and ("ST" not in q["name"].upper()) and ("退" not in q["name"])
        op_list.append(q["open"]); ycl_list.append(q["yclose"]); now_list.append(q["now"])
        hi_list.append(q["high"]); lo_list.append(q["low"]); nm_list.append(q["name"])
        buy_list.append(buy_ok); ts_list.append(q["ts"])

    c23["live_name"] = nm_list
    c23["t1_yclose"] = ycl_list
    c23["t1_open"] = op_list
    c23["t1_now"] = now_list
    c23["t1_high"] = hi_list
    c23["t1_low"] = lo_list
    c23["buyable_today"] = buy_list
    c23["t1_open_gap"] = c23["t1_open"] / c23["t1_yclose"] - 1.0
    c23["today_ret_from_open_pct"] = (c23["t1_now"] / c23["t1_open"] - 1.0) * 100.0
    c23["today_high_from_open_pct"] = (c23["t1_high"] / c23["t1_open"] - 1.0) * 100.0
    c23["today_low_from_open_pct"] = (c23["t1_low"] / c23["t1_open"] - 1.0) * 100.0
    c23["quote_ts"] = ts_list

    live = c23[c23["buyable_today"]].copy().reset_index(drop=True)
    sc, comps = compute_score_beta_v1(live)
    live["score_v1"] = sc
    for col in comps.columns:
        live[f"pt_{col}"] = comps[col].values
    live = live.sort_values(["score_v1", "circ_mcap", "c6"], ascending=[False, True, True]).reset_index(drop=True)
    live["rank_in_day"] = np.arange(1, len(live) + 1)
    live["pass_A"] = (live["score_v1"] >= 85) & (live["rank_in_day"] <= 3)
    live["pass_S"] = (live["score_v1"] >= 94) & (live["rank_in_day"] <= 3)

    out_cols = [
        "rank_in_day", "c6", "live_name", "score_v1", "pass_A", "pass_S",
        "ret", "t1_open_gap", "today_ret_from_open_pct", "today_high_from_open_pct", "today_low_from_open_pct",
        "pos20_pre", "dist_ma60_pre", "circ_mcap", "lock_top10", "real_free_mcap", "real_to",
        "clv", "big7_cnt_20d_pre", "kpl_hist180_allzt_max", "kpl_hist180_elo_max",
        "earn_pos_t0_post_B", "comm_posts_3d_pit", "t1_open", "t1_now", "quote_ts",
    ] + [f"pt_{c}" for c in comps.columns]
    live[out_cols].to_csv(f"{OUT_DIR}/today_20261124_scores.csv", index=False, encoding="utf-8-sig")

    print(f"\n=== LIVE 2026-11-23 -> 2026-11-24 SCORING ({len(live)} buyable 20cm candidates, quote_ts={live['quote_ts'].iloc[0] if len(live) else ''}) ===")
    print(f"Pass score>=85 count: {(live['score_v1']>=85).sum()} | Pass score>=94 count: {(live['score_v1']>=94).sum()} | max_score={live['score_v1'].max() if len(live) else 0}")
    show_c = ["rank_in_day", "c6", "live_name", "score_v1", "pass_A", "pass_S", "ret", "t1_open_gap", "today_ret_from_open_pct", "pos20_pre", "dist_ma60_pre", "real_free_mcap", "lock_top10", "kpl_hist180_allzt_max"]
    top12 = live.head(12)[show_c].copy()
    top12["ret"] = (top12["ret"] * 100).round(2)
    top12["t1_open_gap"] = (top12["t1_open_gap"] * 100).round(2)
    top12["today_ret_from_open_pct"] = top12["today_ret_from_open_pct"].round(2)
    top12["pos20_pre"] = top12["pos20_pre"].round(2)
    top12["dist_ma60_pre"] = (top12["dist_ma60_pre"] * 100).round(1)
    top12["real_free_mcap"] = top12["real_free_mcap"].round(1)
    print(top12.to_string(index=False))

    # Update beta_v1_summary.json with live info
    sum_path = f"{OUT_DIR}/beta_v1_summary.json"
    with open(sum_path, "r", encoding="utf-8") as f:
        sm = json.load(f)
    sm["live_20261124"] = {
        "n_candidates": int(len(live)),
        "n_ge85": int((live["score_v1"] >= 85).sum()),
        "n_ge94": int((live["score_v1"] >= 94).sum()),
        "top5": top12.head(5).to_dict("records"),
    }
    with open(sum_path, "w", encoding="utf-8") as f:
        json.dump(sm, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

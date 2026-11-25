#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Daily Pure National Team 21-ETF Entry/Exit Monitor Radar (RD010).
Outputs Team 1/2/3 aggregates, purity-weighted vs raw flows, and per-ETF table topped by 510300.
Usage:
  python3.13 csrc_national_team_monitor.py --today
  python3.13 csrc_national_team_monitor.py --recent 30
"""
import argparse, json, os, sys
from datetime import datetime
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from csrc_fetch_etf_shares import ETFS
from csrc_monitor_lib import NT_DIR, fetch_recent_etf_and_update_shares, fetch_sina_realtime_quotes, fetch_intraday_5m_pulses, scan_recent_nt_news
from csrc_v2_radar import fetch_v2_1m_sync_radar, fetch_institutional_redemption_radar
from csrc_v3_rescue_scorer import run_v3_scoring, print_v3_report, _fetch_qt_batch


def trading_elapsed_fraction(now: datetime) -> float:
    m = now.hour * 60 + now.minute
    if m < 9 * 60 + 30:
        return 1.0
    if m <= 11 * 60 + 30:
        mins = m - (9 * 60 + 30)
    elif m < 13 * 60:
        mins = 120
    elif m <= 15 * 60:
        mins = 120 + (m - 13 * 60)
    else:
        mins = 240
    return max(0.05, min(1.0, mins / 240.0))


def run_monitor(recent_n: int = 20, today_only: bool = False):
    now = datetime.now()
    df = fetch_recent_etf_and_update_shares(lookback_days=max(60, recent_n + 25))
    quotes = fetch_sina_realtime_quotes()
    # Patch today's live intraday quotes for all 21 ETFs from qt.gtimg.cn so partial EM daily bars never cause 0.00/NaN
    etf_qt_syms = [("sh" if v[1] == "SSE" else "sz") + c for c, v in ETFS.items()]
    etf_qt = _fetch_qt_batch(etf_qt_syms + ["sh000300"])
    live_dt = etf_qt.get("sh000300", {}).get("date") or now.strftime("%Y-%m-%d")
    if live_dt >= df["date"].max():
        patch_rows = []
        for code, (name, exch, grp, team, nt_w) in ETFS.items():
            q = etf_qt.get(("sh" if exch == "SSE" else "sz") + code)
            if not q or pd.isna(q.get("now")) or pd.isna(q.get("amt_yi")):
                continue
            mask = (df["code"] == code) & (df["date"] == live_dt)
            if mask.any():
                df.loc[mask, ["open", "high", "low", "close", "amount", "pct_chg"]] = [
                    q["open"], q["high"], q["low"], q["now"], q["amt_yi"] * 1e8, q["pct"]
                ]
            else:
                patch_rows.append({
                    "date": live_dt, "code": code, "name": name, "exch": exch, "idx_grp": grp,
                    "team": team, "nt_w": nt_w, "open": q["open"], "high": q["high"], "low": q["low"],
                    "close": q["now"], "amount": q["amt_yi"] * 1e8, "pct_chg": q["pct"],
                    "shares_wan": np.nan, "prev_sh": np.nan, "net_flow_yi": np.nan, "nt_w_flow_yi": np.nan,
                })
        if patch_rows:
            df = pd.concat([df, pd.DataFrame(patch_rows)], ignore_index=True).sort_values(["code", "date"]).reset_index(drop=True)
    pulses_5m = fetch_intraday_5m_pulses(live_dt)
    news = scan_recent_nt_news(days=30)

    def gsum(col, cond_col, val):
        return (col, lambda s: s[df.loc[s.index, cond_col] == val].sum())

    agg = df.groupby("date").agg(
        tot_amt_yi=("amount", lambda s: s.sum() / 1e8),
        tot_flow_yi=("net_flow_yi", "sum"),
        nt_w_flow_yi=("nt_w_flow_yi", "sum"),
        t1_flow=("net_flow_yi", lambda s: s[df.loc[s.index, "team"] == "T1"].sum()),
        t2_flow=("net_flow_yi", lambda s: s[df.loc[s.index, "team"] == "T2"].sum()),
        t3_flow=("net_flow_yi", lambda s: s[df.loc[s.index, "team"] == "T3"].sum()),
        n_sh=("shares_wan", lambda s: int(s.notna().sum())),
    ).reset_index().sort_values("date")
    agg["med20_amt"] = agg["tot_amt_yi"].rolling(20, min_periods=5).median().shift(1)
    agg["amt_spike"] = agg["tot_amt_yi"] / agg["med20_amt"].replace(0, np.nan)

    latest_dt = agg["date"].iloc[-1]
    settled = agg[agg["n_sh"] > 0]
    last_settled = settled.iloc[-1]
    last_sh_dt = str(last_settled["date"])
    s5_raw, s20_raw = float(settled.tail(5)["tot_flow_yi"].sum()), float(settled.tail(20)["tot_flow_yi"].sum())
    s5_w, s20_w = float(settled.tail(5)["nt_w_flow_yi"].sum()), float(settled.tail(20)["nt_w_flow_yi"].sum())
    s5_t1, s5_t2, s5_t3 = float(settled.tail(5)["t1_flow"].sum()), float(settled.tail(5)["t2_flow"].sum()), float(settled.tail(5)["t3_flow"].sum())

    frac = trading_elapsed_fraction(now) if latest_dt == now.strftime("%Y-%m-%d") else 1.0
    cur_amt = float(agg["tot_amt_yi"].iloc[-1])
    proj_amt = cur_amt / frac
    med20_cur = float(agg["med20_amt"].iloc[-1])
    proj_spike = proj_amt / med20_cur if med20_cur > 0 else np.nan

    # Per-ETF details (with 510300 pinned at #1)
    per_rows = []
    settled_dates_20 = set(settled.tail(20)["date"])
    settled_dates_5 = set(settled.tail(5)["date"])
    for code, (name, exch, grp, team, nt_w) in ETFS.items():
        sub = df[df["code"] == code].sort_values("date")
        sub_today = sub[sub["date"] == latest_dt]
        cur_e_amt = float(sub_today["amount"].iloc[0] / 1e8) if len(sub_today) else 0.0
        cur_e_pct = float(sub_today["pct_chg"].iloc[0]) if len(sub_today) else np.nan
        med20_e = float(sub[sub["date"] < latest_dt].tail(20)["amount"].median() / 1e8) if len(sub) > 5 else np.nan
        e_spike = (cur_e_amt / frac) / med20_e if (med20_e and med20_e > 0) else np.nan
        sub_s = sub[sub["shares_wan"].notna()]
        last_f = float(sub_s[sub_s["date"] == last_sh_dt]["net_flow_yi"].sum())
        f5 = float(sub_s[sub_s["date"].isin(settled_dates_5)]["net_flow_yi"].sum())
        f20 = float(sub_s[sub_s["date"].isin(settled_dates_20)]["net_flow_yi"].sum())
        per_rows.append({
            "code": code, "name": name, "team": team, "nt_pct": round(nt_w * 100, 2),
            "pct_chg": round(cur_e_pct, 2), "cur_amt_yi": round(cur_e_amt, 2),
            "proj_spike": round(e_spike, 2) if pd.notna(e_spike) else np.nan,
            "last_flow_yi": round(last_f, 2), "flow_5d_yi": round(f5, 2), "flow_20d_yi": round(f20, 2),
        })
    per_df = pd.DataFrame(per_rows)
    r300 = per_df[per_df["code"] == "510300"].iloc[0]

    big4_pct = float(np.mean([quotes[k]["pct"] for k in ("sh601398", "sh601939", "sh601288", "sh601988") if k in quotes]))
    c300_pct = quotes.get("sh000300", {}).get("pct", np.nan)
    c1000_pct = quotes.get("sh000852", {}).get("pct", np.nan)
    c300_lvl = quotes.get("sh000300", {}).get("now", np.nan)

    if last_settled["t1_flow"] >= 75 and last_settled["t2_flow"] < 15:
        regime = "一队偏心护盘期（300/50买盘集中但中小创未跟进，小盘相对承压）"
    elif last_settled["t1_flow"] >= 50 and last_settled["t2_flow"] >= 25:
        regime = "一二队全面共振托底（大盘蓝筹与中证500/1000/双创同步净申购）"
    elif s5_w <= -250:
        regime = "高位连续退场降温期（近5日纯净加权大额净赎回，注意20日压盘）"
    elif s5_w >= 150:
        regime = "温和连续托底（近5日纯净加权净申购>=150亿）"
    else:
        regime = "按兵不动常规震荡（无百亿级净申赎触发）"

    print(f"=== 国家队21只重仓宽基ETF进退场实时雷达 ({now.strftime('%Y-%m-%d %H:%M:%S')}) ===")
    print(f"【实时行情 ({latest_dt})】沪深300={c300_lvl:.2f} ({c300_pct:+.2f}%) | 中证1000={c1000_pct:+.2f}% | 四大行={big4_pct:+.2f}% (四大行-1000={big4_pct-c1000_pct:+.2f}%)")
    print(f"【头号标杆 510300 华泰柏瑞300ETF】纯度82.96% | 盘中{r300['pct_chg']:+.2f}% 成交{r300['cur_amt_yi']:.1f}亿(量比{r300['proj_spike']:.2f}x) | 上日({last_sh_dt}){r300['last_flow_yi']:+.1f}亿 | 5日{r300['flow_5d_yi']:+.1f}亿 | 20日{r300['flow_20d_yi']:+.1f}亿")
    print(f"【21只池成交脉冲】实时{cur_amt:.1f}亿(进度{frac*100:.0f}%, 折算{proj_amt:.1f}亿 vs 20日中位{med20_cur:.1f}亿, 预计量比={proj_spike:.2f}x)")
    print(f"【最新已披露 ({last_sh_dt})】原始净流={last_settled['tot_flow_yi']:+.1f}亿 | 纯净加权={last_settled['nt_w_flow_yi']:+.1f}亿 | 一队={last_settled['t1_flow']:+.1f}亿 / 二队={last_settled['t2_flow']:+.1f}亿 / 三队={last_settled['t3_flow']:+.1f}亿")
    print(f"【阶段累计净流】5日原始={s5_raw:+.1f}亿(纯净{s5_w:+.1f}亿 | 一队{s5_t1:+.1f}/二队{s5_t2:+.1f}/三队{s5_t3:+.1f}) | 20日原始={s20_raw:+.1f}亿(纯净{s20_w:+.1f}亿)")
    sh_q = quotes.get("sh000001", {})
    sh_reb = ((sh_q.get("now", 0) - sh_q.get("low", 0)) / sh_q["prev"] * 100) if sh_q.get("prev", 0) > 0 else 0.0
    p510300 = pulses_5m.get("510300", {})
    sync_cnt = sum(1 for v in pulses_5m.values() if v.get("max_5m_mult", 0) >= 3.0)
    if p510300.get("max_5m_mult", 0) >= 5.0 or (sync_cnt >= 3 and sh_reb >= 0.5):
        intraday_raid = f"盘中脉冲进场实锤！{len(pulses_5m)}只核心ETF全部爆发>=3倍5分钟巨量（华泰510300于 {p510300.get('peak_hhmm')} 单根5m爆量 {p510300.get('max_5m_mult')}x / {p510300.get('peak_5m_amt_yi')}亿），上证自低点拉起 +{sh_reb:.2f}%"
    else:
        intraday_raid = f"盘中暂无多ETF同步>=3倍5分钟脉冲（上证较日低 +{sh_reb:.2f}%）"
    print(f"【上证与权重】上证={sh_q.get('now',0):.2f} ({sh_q.get('pct',0):+.2f}%, 较日低拉起 +{sh_reb:.2f}%) | 中国石油={quotes.get('sh601857',{}).get('pct',0):+.2f}% | 中国移动={quotes.get('sh600941',{}).get('pct',0):+.2f}%")
    print(f"【盘中5分钟突击监测】{intraday_raid}")
    if pulses_5m:
        p_line = " | ".join(f"{k}@{v['peak_hhmm']}({v['max_5m_mult']}x/{v['peak_5m_amt_yi']}亿)" for k, v in pulses_5m.items())
        print(f"  -> 主力5m爆量点: {p_line}")
    print(f"【昨日收盘份额状态】{regime}")

    # === V2.0 Upgrade: 1-Minute Cross-Asset Sync Radar & 3-Layer Institutional Redemption Radar ===
    v2_sync = fetch_v2_1m_sync_radar(proj_spike=proj_spike, csi300_pct=c300_pct)
    inst_red = fetch_institutional_redemption_radar(settled["date"].tolist())
    print("\n=== V2.0 跨资产1分钟同步脉冲雷达（10核心ETF + 16大国家队权重） ===")
    if v2_sync.get("ok"):
        bw = v2_sync["best_window"]
        print(f"【V2.0 盘中定性】{v2_sync['regime']} | 警报等级：{v2_sync['alert_level']} (截至 {v2_sync['latest_hhmm']})")
        print(f"【最强5分钟共振窗 ({bw['window']})】ETF5m合计={bw['etf_burst_yi']:.1f}亿(一队{bw['t1_yi']:.1f}亿 / 二队{bw['t2_yi']:.1f}亿) | 16权重5m={bw['hw_yi']:.1f}亿")
        if bw["t1_hits"]:
            print("  -> 一队ETF爆发(>=4x): " + " | ".join(f"{n}({m}x/{a}亿)" for n, m, a in bw["t1_hits"]))
        if bw["t2_hits"]:
            print("  -> 二队ETF爆发(>=4x): " + " | ".join(f"{n}({m}x/{a}亿)" for n, m, a in bw["t2_hits"]))
        if bw["hw_hits"]:
            print("  -> 国家队权重同步(>=2.5x): " + " | ".join(f"{n}({m}x/{r:+.2f}%)" for n, m, r in bw["hw_hits"][:6]))

    print("\n=== V2.0 机构与ETF赎回压力三层雷达 ===")
    print(f"【机构赎回总判】{inst_red['verdict']}")
    print(f"  -> 边界说明: {inst_red['boundary_note']}")
    print(f"【Layer 1 · 盘后官宣】十大非国家队行业/主题ETF(上交所): 上日={inst_red['sector_1d_yi']:+.1f}亿 | 近5日={inst_red['sector_5d_yi']:+.1f}亿")
    if inst_red["sector_etf_flows"]:
        top_out = sorted(inst_red["sector_etf_flows"], key=lambda x: x["flow_5d_yi"])[:4]
        top_in = sorted(inst_red["sector_etf_flows"], key=lambda x: -x["flow_5d_yi"])[:3]
        print("  -> 近5日净赎回靠前: " + " | ".join(f"{r['name']}({r['flow_5d_yi']:+.1f}亿, 上日{r['flow_1d_yi']:+.1f}亿)" for r in top_out))
        print("  -> 近5日净申购靠前: " + " | ".join(f"{r['name']}({r['flow_5d_yi']:+.1f}亿, 上日{r['flow_1d_yi']:+.1f}亿)" for r in top_in))
    print(f"【Layer 2 · 盘中代理】14只ETF实时IOPV折溢价中位={inst_red['med_disc_pct']:+.2f}% (深折价<=-0.25%家数={inst_red['deep_disc_cnt']}) | 公募八大重仓14:00后放量砸盘家数={inst_red['dump_hw_cnt']}/8")
    if inst_red["iopv_rows"]:
        worst_d = sorted([r for r in inst_red["iopv_rows"] if pd.notna(r["disc_pct"])], key=lambda x: x["disc_pct"])[:5]
        print("  -> 实时折价最深5只: " + " | ".join(f"{r['name']}({r['disc_pct']:+.2f}%, 日内{r['pct']:+.2f}%)" for r in worst_d))
    if inst_red["fund_hw_rows"]:
        print("  -> 公募重仓14:00后: " + " | ".join(f"{r['name']}({r['pm14_pct']:+.2f}%/{r['pm14_vol_ratio']:.2f}x)" for r in inst_red["fund_hw_rows"]))
    if inst_red["lhb_org_5d"]:
        l_str = " | ".join(f"{r['date'][5:]}({r['net_yi']:+.1f}亿)" for r in inst_red["lhb_org_5d"])
        print(f"【Layer 3 · 龙虎榜机构】近5日机构专用席位净买入={inst_red['lhb_5d_net_yi']:+.1f}亿 -> {l_str}")

    # === V3.0 Upgrade: 5-Dimension Pure-Integer Rescue & Institutional Hedge Scorecard ===
    v3_score = run_v3_scoring(settled_df_21=df, settled_agg_21=agg)
    print_v3_report(v3_score)
    print("")
    print("--- 21只国家队重仓ETF逐只明细（510300置顶）---")
    print(per_df.to_string(index=False))

    if not today_only:
        print(f"\n--- 最近 {recent_n} 个交易日21只ETF汇总资金流明细 ---")
        sub = agg.tail(recent_n)[["date", "tot_amt_yi", "amt_spike", "tot_flow_yi", "nt_w_flow_yi", "t1_flow", "t2_flow", "t3_flow", "n_sh"]].copy()
        for c in ("tot_amt_yi", "tot_flow_yi", "nt_w_flow_yi", "t1_flow", "t2_flow", "t3_flow"):
            sub[c] = sub[c].round(1)
        sub["amt_spike"] = sub["amt_spike"].round(2)
        print(sub.to_string(index=False))

    print(f"\n--- 近30天官方国家队（汇金/国新/诚通/社保/互换便利）动态扫描 (命中{len(news)}条) ---")
    for h in news[:12]:
        print(f"  {h['dt']} | {h['src']} | {h['title']}")

    snap = {
        "run_at": now.strftime("%Y-%m-%d %H:%M:%S"), "latest_date": latest_dt, "last_settled_date": last_sh_dt,
        "csi300_lvl": round(c300_lvl, 2), "csi300_pct": round(c300_pct, 2), "csi1000_pct": round(c1000_pct, 2),
        "big4_pct": round(big4_pct, 2), "cur_etf_amt_yi": round(cur_amt, 1), "proj_etf_amt_yi": round(proj_amt, 1),
        "proj_spike": round(proj_spike, 2), "last_day_flow_yi": round(float(last_settled["tot_flow_yi"]), 1),
        "last_day_wflow_yi": round(float(last_settled["nt_w_flow_yi"]), 1),
        "last_day_t1_yi": round(float(last_settled["t1_flow"]), 1), "last_day_t2_yi": round(float(last_settled["t2_flow"]), 1),
        "last_day_t3_yi": round(float(last_settled["t3_flow"]), 1),
        "flow_5d_yi": round(s5_raw, 1), "wflow_5d_yi": round(s5_w, 1),
        "flow_20d_yi": round(s20_raw, 1), "wflow_20d_yi": round(s20_w, 1),
        "regime": regime, "v2_sync_radar": v2_sync, "inst_redemption": inst_red,
        "v3_rescue_score": v3_score, "per_etf": per_rows, "news_hits": news[:12],
    }
    json.dump(snap, open(os.path.join(NT_DIR, "latest_monitor_snapshot.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", action="store_true")
    ap.add_argument("--recent", type=int, default=20)
    args = ap.parse_args()
    run_monitor(recent_n=args.recent, today_only=args.today)

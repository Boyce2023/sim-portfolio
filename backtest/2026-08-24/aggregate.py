#!/usr/bin/env python3
import json, statistics as stats

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24"

def pctile(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    f = int(k); c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)

def main():
    d = json.load(open(f"{BASE}/simulation_results.json"))
    n = len(d)
    print(f"n = {n} closed a_share episodes, exit >= 2026-06-24 (through 2026-08-24)\n")

    rules = ["R1_disaster", "R2_ma20", "R2b_ma20_excl_today", "R3_low10", "R4_hold"]
    labels = {"R1_disaster": "①灾难线-12%(实际执行规则)", "R2_ma20": "②破20日均线(含当日)",
              "R2b_ma20_excl_today": "②b破20日均线(不含当日,禁T+0出)",
              "R3_low10": "③破前10日低", "R4_hold": "④不设止损持有到今天"}

    summary = {}
    for rk in rules:
        rets = []
        pnls = []
        triggers = 0
        false_kills = 0
        false_kill_evaluable = 0
        rows = []
        for row in d:
            ep = row["episode"]; r = row["sim"][rk]
            pnl = ep["shares"] * (r["exit_price"] - r["entry_cost"])
            rets.append(r["ret"])
            pnls.append(pnl)
            if r["triggered"]:
                triggers += 1
                if r.get("false_kill") is not None:
                    false_kill_evaluable += 1
                    if r["false_kill"]:
                        false_kills += 1
            rows.append((ep["ticker"], ep["name"], r["ret"], pnl, r["triggered"], r["exit_date"]))
        wins = sum(1 for x in rets if x > 0)
        summary[rk] = dict(
            n=n, total_pnl=sum(pnls), mean_ret=stats.mean(rets), median_ret=stats.median(rets),
            win_rate=wins / n, p5=pctile(rets, 0.05), p95=pctile(rets, 0.95),
            stdev=stats.pstdev(rets), max_loss_pnl=min(pnls), max_loss_ticker=min(rows, key=lambda x: x[3])[1],
            triggers=triggers, false_kills=false_kills, false_kill_evaluable=false_kill_evaluable,
        )

    print(f"{'规则':30s} {'总PnL(元)':>14s} {'均值%':>8s} {'中位数%':>8s} {'胜率':>7s} {'p5%':>8s} {'p95%':>8s} {'触发次数':>8s} {'误杀':>10s} {'最大单笔亏损':>14s}")
    for rk in rules:
        s = summary[rk]
        fk = f"{s['false_kills']}/{s['false_kill_evaluable']}" if s['false_kill_evaluable'] else "n/a(数据不足)"
        print(f"{labels[rk]:30s} {s['total_pnl']:>14,.0f} {s['mean_ret']*100:>7.2f}% {s['median_ret']*100:>7.2f}% "
              f"{s['win_rate']*100:>6.1f}% {s['p5']*100:>7.2f}% {s['p95']*100:>7.2f}% {s['triggers']:>7d}/{n} "
              f"{fk:>10s} {s['max_loss_pnl']:>14,.0f}({s['max_loss_ticker']})")

    print("\n--- 三环集团(300408) / 生益科技(600183) 专项对比 ---")
    for row in d:
        ep = row["episode"]
        if ep["ticker"] not in ("300408", "600183"):
            continue
        print(f"\n{ep['ticker']} {ep['name']}  entry={ep['entry_date']}@{ep['avg_entry_price']:.2f}  "
              f"actual_exit={ep['exit_date']}@{ep['avg_exit_price']:.2f}  actual_pnl={ep['actual_pnl']:,.0f}元  shares={ep['shares']:.0f}")
        for rk in rules:
            r = row["sim"][rk]
            pnl = ep["shares"] * (r["exit_price"] - r["entry_cost"])
            trig = "触发" if r["triggered"] else "未触发(持有至今)"
            fk = {True: "是", False: "否", None: "N/A(数据不足)"}[r.get("false_kill")]
            print(f"  {labels[rk]:30s} 出场日={r['exit_date']} 出场价={r['exit_price']:.2f} "
                  f"return={r['ret']*100:+.2f}% pnl={pnl:,.0f}元 [{trig}] 误杀={fk}")

    print("\n--- 全部53笔明细 ---")
    hdr = f"{'ticker':8s}{'name':10s}{'entry':11s}{'avg_in':>8s} | "
    hdr += " | ".join(f"{labels[rk][:8]:>20s}" for rk in rules)
    print(hdr)
    for row in d:
        ep = row["episode"]
        line = f"{ep['ticker']:8s}{ep['name'][:8]:10s}{ep['entry_date']:11s}{ep['avg_entry_price']:>8.2f} | "
        parts = []
        for rk in rules:
            r = row["sim"][rk]
            parts.append(f"{r['exit_date']}@{r['exit_price']:>7.2f}({r['ret']*100:+6.1f}%)")
        print(line + " | ".join(parts))

    with open(f"{BASE}/summary_stats.json", "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()

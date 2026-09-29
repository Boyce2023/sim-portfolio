#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股盘后摘要自动推送 (2026-08-27 自动化普查落地, Buwen令"以后不用他提醒")

⛔缘起: 对话史里"咋样了/持仓怎么样/收益率呢"类手动询问30+次。此脚本每天US收盘后
由daily_run自动跑, 把持仓/门/宏观哨兵值压成一条飞书(2026-08-27迁移: Buwen令telegram退役), 不再等他问。
纯机械零agent, 交易决策仍归session内的完整扫描流程。
"""
import json, os, subprocess, sys, warnings
warnings.filterwarnings('ignore')
R = os.path.expanduser("~/claude-projects/sim-portfolio")

def main():
    st = json.load(open(f"{R}/portfolio_state.json"))["accounts"]["us"]
    pos = st["positions"]
    items = list(pos.values()) if isinstance(pos, dict) else pos

    # ⛔ NAV 必须按收盘市价重算, 不用 state 里存的 total_assets/current_price
    #    (2026-08-29 修: 存值是上次交易时写入的静态数, 收盘后已过期,
    #     曾导致本摘要报 $1,513,778 而实际收盘 $1,500,805, 且此数会进 main 晨报)
    import yfinance as yf, time as _t
    tk = [p["ticker"] for p in items]
    try:
        d = yf.download(tk, period="5d", progress=False, auto_adjust=True, threads=True)["Close"]
    except Exception:
        d = None
    if d is not None:
        for t in tk:                      # 批量偶发失败 → 单只重取
            if t not in d.columns or d[t].dropna().empty:
                for _ in range(3):
                    h = yf.Ticker(t).history(period="5d")["Close"].dropna()
                    if not h.empty:
                        d[t] = h; break
                    _t.sleep(2)
    live = {}
    for p in items:
        t = p["ticker"]
        try:
            live[t] = float(d[t].dropna().iloc[-1])
        except Exception:
            live[t] = p["current_price"]   # 兜底: 取不到才用存值
    stale = [t for t in tk if live[t] == p.get("current_price") and (d is None or t not in d.columns)]
    mv = sum(p["shares"] * live[p["ticker"]] for p in items)
    nav = mv + st["cash"]
    for p in items:                        # 让下游用同一套价
        p["current_price"] = live[p["ticker"]]
    rows = []
    for p in items:
        t = p["ticker"]; chg = None
        try:
            s = d[t].dropna(); chg = (float(s.iloc[-1]) / float(s.iloc[-2]) - 1) * 100
        except Exception: pass
        cb = p.get("cost_basis", 0) / p["shares"] if p.get("cost_basis") else p.get("avg_cost", 0)
        rows.append((chg if chg is not None else 0, t,
                     p["shares"] * p["current_price"] / nav * 100,
                     (p["current_price"] / cb - 1) * 100 if cb else 0))
    rows.sort()
    worst = " ".join(f"{t}{c:+.1f}%" for c, t, _, _ in rows[:3])
    best = " ".join(f"{t}{c:+.1f}%" for c, t, _, _ in rows[-3:])

    # T18门(只取判定行)
    doors = []
    try:
        r = subprocess.run(["python3", f"{R}/scripts/portfolio_trend_check.py", "--market", "us"],
                           capture_output=True, text=True, timeout=240)
        for ln in r.stdout.splitlines():
            if "【清/减】" in ln:
                doors.append(ln.strip()[:70])
    except Exception as e:
        doors.append(f"门检查失败:{str(e)[:40]}")

    # 宏观哨兵值
    macro = ""
    try:
        vals = {}
        for t in ["DX-Y.NYB", "GDX", "^TNX"]:
            h = yf.Ticker(t).history(period="2d")["Close"].dropna()
            vals[t] = (float(h.iloc[-1]), (float(h.iloc[-1])/float(h.iloc[-2])-1)*100 if len(h)>1 else 0)
        macro = (f"美元{vals['DX-Y.NYB'][0]:.2f}({vals['DX-Y.NYB'][1]:+.2f}%) "
                 f"GDX{vals['GDX'][0]:.1f}({vals['GDX'][1]:+.2f}%) 10Y{vals['^TNX'][0]:.2f}%")
    except Exception: macro = "宏观取数失败"

    init = 1_500_000
    # ⛔2026-09-29 送达自检: "[美股·盘后自动摘要]"开头会被 fs-reply 白名单静默, 门响的日子告警随之被吞。
    #   有门响 → 首行加 ⛔ 强制进群; 无门响的日常摘要维持静默(那是白名单的本意, 防刷屏)。
    msg = (("⛔ " if doors else "") + f"[美股·盘后自动摘要] NAV ${nav:,.0f} ({(nav/init-1)*100:+.2f}%) 杠杆{mv/nav:.2f}x {len(items)}只\n"
           f"最弱: {worst}\n最强: {best}\n"
           f"门: {('; '.join(doors) if doors else '全守, 无门响')}\n"
           f"宏观: {macro}\n"
           f"(自动产出, 完整扫描+调仓由session按日程执行)")
    print(msg)

    # 2026-08-27 晨报工程(main): 结构化落盘供每日7:30飞书晨报"隔夜美股"block只读引用
    import datetime
    brief = {
        "date": datetime.date.today().isoformat(),
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "nav": round(nav, 2), "nav_ret_pct": round((nav/init-1)*100, 2),
        "leverage": round(mv/nav, 3), "n_positions": len(items),
        "highlights": [f"最弱 {worst}", f"最强 {best}", f"宏观 {macro}"],
        "positions_delta": [
            {"ticker": t, "day_pct": round(c, 2), "weight_pct": round(w, 1), "unreal_pct": round(u, 1)}
            for c, t, w, u in sorted(rows, key=lambda x: x[0])
        ],
        "alerts": doors if doors else [],
    }
    with open(f"{R}/output/us_daily_brief.json", "w") as f:
        json.dump(brief, f, ensure_ascii=False, indent=1)
    subprocess.run(["bash", os.path.expanduser("~/.claude/session-remote/fs-reply.sh"), msg],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   start_new_session=True, timeout=30)
    return 0

if __name__ == "__main__":
    sys.exit(main())

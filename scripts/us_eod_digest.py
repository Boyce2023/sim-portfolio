#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股盘后慢账摘要自动推送 (2026-08-27 建, 2026-10-29 慢账纯化版)

职责:
1. 每日美股收盘后由 daily_run.sh 自动调用, 按实时/收盘行情重算 NAV 与持仓单日表现。
2. 2026-10-29 清理: 彻底移除旧版 portfolio_trend_check.py 技术面【清/减】卖出提示(美股慢账禁用技术门),
   改为输出慢账基本面复核提示:
   - 行情新鲜度校验(标记回退静态存值或日线滞后的持仓, 绝不静默伪装成最新收盘)
   - 论点覆盖率与近7日催化剂窗口提醒(读取 config/us_thesis_invalidation.json)
   - 破 -12% 慢账论点三问复核提醒(仅提示审视论点, 非自动卖出指令)
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time as _t
import warnings

warnings.filterwarnings('ignore')

R = os.path.expanduser("~/claude-projects/sim-portfolio")
DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


def _load_thesis_status(held_tickers: list[str], today: datetime.date):
    """返回 (漏配标的列表, 近7日催化列表)。"""
    cfg_path = f"{R}/config/us_thesis_invalidation.json"
    try:
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.load(f).get("positions", {})
    except Exception:
        return ["<失效条件配置读取失败>"], []

    uncovered = [t for t in held_tickers if t not in cfg]
    upcoming = []
    for t in held_tickers:
        wd = (cfg.get(t) or {}).get("watch_date", "")
        m = DATE_RE.search(wd)
        if m:
            try:
                dt = datetime.date.fromisoformat(m.group(1))
                delta = (dt - today).days
                if -1 <= delta <= 7:
                    upcoming.append(f"{t}({m.group(1)})")
            except ValueError:
                pass
    return uncovered, upcoming


def main():
    ap = argparse.ArgumentParser(description="美股盘后慢账摘要推送")
    ap.add_argument("--dry-run", action="store_true", help="仅打印摘要与JSON预览, 不写文件不发飞书")
    args = ap.parse_args()

    with open(f"{R}/portfolio_state.json", encoding="utf-8") as f:
        st = json.load(f)["accounts"]["us"]
    pos = st["positions"]
    items = list(pos.values()) if isinstance(pos, dict) else pos

    import yfinance as yf
    tk = [p["ticker"] for p in items]
    try:
        raw = yf.download(tk, period="5d", progress=False, auto_adjust=True, threads=True)
        d = raw["Close"] if raw is not None and not raw.empty and "Close" in raw else None
    except Exception:
        d = None

    if d is not None:
        for t in tk:
            if t not in d.columns or d[t].dropna().empty:
                for _ in range(3):
                    try:
                        h = yf.Ticker(t).history(period="5d")["Close"].dropna()
                        if not h.empty:
                            d[t] = h
                            break
                    except Exception:
                        pass
                    _t.sleep(2)

    live = {}
    bar_dates = {}
    fallback_tickers = []
    for p in items:
        t = p["ticker"]
        try:
            s = d[t].dropna()
            live[t] = float(s.iloc[-1])
            bar_dates[t] = str(s.index[-1].date())
        except Exception:
            live[t] = p["current_price"]
            fallback_tickers.append(t)

    latest_bar_date = max(bar_dates.values()) if bar_dates else None
    lagging_tickers = [t for t, dt in bar_dates.items() if latest_bar_date and dt < latest_bar_date]

    mv = sum(p["shares"] * live[p["ticker"]] for p in items)
    nav = mv + st["cash"]
    for p in items:
        p["current_price"] = live[p["ticker"]]

    rows = []
    for p in items:
        t = p["ticker"]
        chg = None
        try:
            s = d[t].dropna()
            if len(s) >= 2:
                chg = (float(s.iloc[-1]) / float(s.iloc[-2]) - 1) * 100
        except Exception:
            pass
        cb = p.get("cost_basis", 0) / p["shares"] if p.get("cost_basis") else p.get("avg_cost", 0)
        unreal_pct = (p["current_price"] / cb - 1) * 100 if cb else 0.0
        rows.append((chg if chg is not None else 0.0, t, p["shares"] * p["current_price"] / nav * 100, unreal_pct))

    rows.sort()
    worst = " ".join(f"{t}{c:+.1f}%" for c, t, _, _ in rows[:3])
    best = " ".join(f"{t}{c:+.1f}%" for c, t, _, _ in rows[-3:])

    # 慢账复核提示(取代已废止的旧技术面卖出提示)
    today = datetime.date.today()
    uncovered, upcoming = _load_thesis_status(tk, today)
    deep_drawdown = [f"{t}({u:+.1f}%)" for _, t, _, u in rows if u <= -12.0]

    hard_alerts = []
    if fallback_tickers:
        hard_alerts.append(f"行情回退静态存值:{','.join(fallback_tickers)}")
    if lagging_tickers:
        hard_alerts.append(f"日线滞后于{latest_bar_date}:{','.join(lagging_tickers)}")
    if uncovered:
        hard_alerts.append(f"论点漏配:{','.join(uncovered)}")
    if deep_drawdown:
        hard_alerts.append(f"破-12%慢账复核线(只审论点不自动卖):{' '.join(deep_drawdown)}")

    review_parts = list(hard_alerts)
    if upcoming:
        review_parts.append(f"7日内催化:{' '.join(upcoming)}")
    review_line = "; ".join(review_parts) if review_parts else "13只论点全覆盖, 无破-12%复核项"

    # 宏观观察值
    macro = ""
    try:
        vals = {}
        for t in ["DX-Y.NYB", "GDX", "^TNX"]:
            h = yf.Ticker(t).history(period="5d")["Close"].dropna()
            vals[t] = (
                float(h.iloc[-1]),
                (float(h.iloc[-1]) / float(h.iloc[-2]) - 1) * 100 if len(h) > 1 else 0.0,
            )
        macro = (
            f"美元{vals['DX-Y.NYB'][0]:.2f}({vals['DX-Y.NYB'][1]:+.2f}%) "
            f"GDX{vals['GDX'][0]:.1f}({vals['GDX'][1]:+.2f}%) "
            f"10Y{vals['^TNX'][0]:.2f}%"
        )
    except Exception:
        macro = "宏观取数失败"

    init = 1_500_000
    date_tag = f" 收盘日{latest_bar_date}" if latest_bar_date else ""
    msg = (
        ("⛔ " if hard_alerts else "")
        + f"[美股·盘后自动摘要]{date_tag} NAV ${nav:,.0f} ({(nav/init-1)*100:+.2f}%) 杠杆{mv/nav:.2f}x {len(items)}只\n"
        f"最弱: {worst}\n"
        f"最强: {best}\n"
        f"慢账复核: {review_line}\n"
        f"宏观: {macro}\n"
        f"(慢账规则: 仅按基本面证伪或更优替代调仓, 无自动止损)"
    )
    print(msg)

    brief = {
        "date": today.isoformat(),
        "latest_bar_date": latest_bar_date,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "nav": round(nav, 2),
        "nav_ret_pct": round((nav / init - 1) * 100, 2),
        "leverage": round(mv / nav, 3),
        "n_positions": len(items),
        "fallback_tickers": fallback_tickers,
        "lagging_tickers": lagging_tickers,
        "highlights": [f"最弱 {worst}", f"最强 {best}", f"宏观 {macro}"],
        "positions_delta": [
            {"ticker": t, "day_pct": round(c, 2), "weight_pct": round(w, 1), "unreal_pct": round(u, 1)}
            for c, t, w, u in sorted(rows, key=lambda x: x[0])
        ],
        "alerts": hard_alerts,
        "upcoming_catalysts": upcoming,
    }

    if args.dry_run:
        print("\n[dry-run] brief preview:", json.dumps(brief, ensure_ascii=False))
        return 0

    os.makedirs(f"{R}/output", exist_ok=True)
    with open(f"{R}/output/us_daily_brief.json", "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=1)
    subprocess.run(
        ["bash", os.path.expanduser("~/.claude/session-remote/fs-reply.sh"), msg],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        timeout=30,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

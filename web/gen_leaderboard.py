#!/usr/bin/env python3
"""Generate leaderboard.html from portfolio_state.json.

一体化流程: sync_summary() 先从 positions 重算汇总字段写回 JSON，
再 generate() 生成 HTML。一条命令保证数据一致。

NAV:
  A-stock = cash + sum(market_value)
  US      = cash + long_MV + short_unrealized_PnL
"""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = ROOT / "portfolio_state.json"
OUTPUT = ROOT / "web" / "leaderboard.html"

EXCHANGE_RATE = 7.2  # CNY per USD


def load():
    with open(PORTFOLIO) as f:
        return json.load(f)


def save(data):
    with open(PORTFOLIO, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def sync_summary(data):
    """从 positions 重算所有汇总字段，写回 data dict（不落盘）。"""
    changes = []

    for market_key in ("a_share", "us"):
        acct = data["accounts"][market_key]
        positions = acct.get("positions", [])
        cash = float(acct.get("cash", 0))
        initial = float(acct.get("initial_capital", 0))
        is_us = market_key == "us"

        long_mv = 0.0
        short_pnl = 0.0
        total_unrealized = 0.0
        total_cost = 0.0

        for p in positions:
            shares = p.get("shares", 0)
            price = float(p.get("current_price", p.get("avg_cost", 0)))
            avg = float(p.get("avg_cost", price))
            abs_shares = abs(shares)

            if shares >= 0:
                mv = price * shares
                p["market_value"] = round(mv, 2)
                pnl = (price - avg) * shares
                pnl_pct = (price - avg) / avg * 100 if avg else 0
                long_mv += mv
            else:
                mv = price * abs_shares
                p["market_value"] = round(-mv, 2)
                pnl = (avg - price) * abs_shares
                pnl_pct = (avg - price) / avg * 100 if avg else 0
                short_pnl += pnl

            p["unrealized_pnl"] = round(pnl, 2)
            p["unrealized_pnl_pct"] = round(pnl_pct, 2)
            p["cost_basis"] = round(avg * abs_shares, 2)
            total_unrealized += pnl
            total_cost += avg * abs_shares

        nav = cash + long_mv + short_pnl if is_us else cash + long_mv

        old_ta = acct.get("total_assets")
        acct["total_invested"] = round(long_mv, 2)
        acct["total_assets"] = round(nav, 2)
        acct["unrealized_pnl"] = round(total_unrealized, 2)

        if old_ta and abs(nav - old_ta) > 0.01:
            label = "美股" if is_us else "A股"
            changes.append(f"{label} total_assets: {old_ta} → {round(nav, 2)}")

        ret_pct = round((nav / initial - 1) * 100, 2) if initial else 0
        perf_key = "total_return_pct_usd" if is_us else "total_return_pct_cny"
        data["performance"][perf_key] = ret_pct

    return changes


def calc_nav(acct_data, market="us"):
    cash = float(acct_data.get("cash", 0))
    positions = acct_data.get("positions", [])

    if market == "a_share":
        mv = sum(float(p.get("market_value", 0)) for p in positions)
        return cash + mv

    long_mv = 0.0
    short_pnl = 0.0
    for p in positions:
        shares = p.get("shares", 0)
        price = float(p.get("current_price", p.get("avg_cost", 0)))
        if shares >= 0:
            long_mv += price * shares
        else:
            avg = float(p.get("avg_cost", price))
            short_pnl += (avg - price) * abs(shares)
    return cash + long_mv + short_pnl


def calc_combined_returns(data):
    perf = data["performance"]["daily_snapshots"]
    a_initial = data["accounts"]["a_share"]["initial_capital"]
    u_initial = data["accounts"]["us"]["initial_capital"]
    a_weight = (a_initial / EXCHANGE_RATE) / (a_initial / EXCHANGE_RATE + u_initial)
    u_weight = 1 - a_weight

    dates, combined, spy_rets = [], [], []
    spy_start = data["performance"]["benchmark"]["spy_start"]

    for s in perf:
        dates.append(s["date"])
        a_ret = s.get("a_share_return_pct", 0)
        u_ret = s.get("us_return_pct", 0)
        combined.append(round(a_ret * a_weight + u_ret * u_weight, 2))
        spy_close = s.get("spy_close")
        if spy_close and spy_start:
            spy_rets.append(round((spy_close / spy_start - 1) * 100, 2))
        else:
            spy_rets.append(spy_rets[-1] if spy_rets else 0)

    return dates, combined, spy_rets, a_weight, u_weight


def build_positions_html(data, combined_nav_usd):
    rows = []
    all_positions = []

    for pos in data["accounts"]["a_share"].get("positions", []):
        pos["_acct"] = "A股"
        pos["_currency"] = "¥"
        mv_usd = abs(float(pos.get("market_value", 0))) / EXCHANGE_RATE
        pos["_combined_weight"] = mv_usd / combined_nav_usd if combined_nav_usd else 0
        all_positions.append(pos)

    for pos in data["accounts"]["us"].get("positions", []):
        pos["_acct"] = "美股"
        pos["_currency"] = "$"
        shares = pos.get("shares", 0)
        price = float(pos.get("current_price", pos.get("avg_cost", 0)))
        mv_usd = abs(shares) * price
        pos["_combined_weight"] = mv_usd / combined_nav_usd if combined_nav_usd else 0
        all_positions.append(pos)

    all_positions.sort(key=lambda p: p["_combined_weight"], reverse=True)

    for pos in all_positions[:12]:
        ticker = pos["ticker"]
        name = pos.get("name", ticker)
        sector = pos.get("sector", "")
        acct = pos["_acct"]
        shares = pos.get("shares", 0)
        is_short = shares < 0
        avg_cost = float(pos.get("avg_cost", 0))
        price = float(pos.get("current_price", avg_cost))
        if is_short:
            pnl_pct = (avg_cost - price) / avg_cost * 100 if avg_cost else 0
        else:
            pnl_pct = (price - avg_cost) / avg_cost * 100 if avg_cost else 0
        weight = pos["_combined_weight"] * 100
        stop = float(pos.get("stop_loss", 0) or 0)
        if stop and price:
            if is_short:
                stop_dist = (stop - price) / price * 100
            else:
                stop_dist = (price - stop) / price * 100
        else:
            stop_dist = 0

        color = "#3fb950" if pnl_pct >= 0 else "#f85149"
        bar_pct = min(max(abs(stop_dist) * 6, 2), 100)
        direction = " [空]" if is_short else ""

        rows.append(f"""      <tr>
        <td><span class="badge">{acct}</span></td>
        <td><span class="ticker-tag">{ticker}</span><br><small>{name}{direction}</small></td>
        <td>{sector}</td>
        <td style="text-align:right">{weight:.1f}%</td>
        <td style="color:{color};text-align:right;font-weight:700">{pnl_pct:+.2f}%</td>
        <td><div class="stop-bar-bg"><div class="stop-bar-fill" style="width:{bar_pct:.0f}%;background:{color}"></div></div></td>
      </tr>""")
    return "\n".join(rows)


def build_trades_js(data):
    trades = data.get("trade_log", [])
    lines = []
    for t in trades:
        acct_label = "A股" if t.get("account") == "a_share" else "美股"
        action = t.get("action", "buy")
        cn_map = {"buy": "买入", "sell": "卖出", "short": "做空", "cover": "平空"}
        cn = cn_map.get(action, action)
        cur = "¥" if t.get("currency") == "CNY" else "$"
        reason = t.get("reason", "").replace('"', '\\"').replace("'", "\\'")[:80]
        ts = t.get("timestamp", "")[:10]
        lines.append(
            f'  {{ts:"{ts}",acct:"{acct_label}",action:"{action}",cn:"{cn}",'
            f'ticker:"{t["ticker"]}",shares:{t.get("shares",0)},'
            f'price:{t.get("price",0)},val:{t.get("value",0):.2f},'
            f'cur:"{cur}",rationale:"{reason}"}}'
        )
    return ",\n".join(lines)


def build_pie(data, combined_nav_usd):
    colors_pool = [
        '#58a6ff', '#3fb950', '#d29922', '#f85149', '#a371f7',
        '#39d353', '#e3b341', '#ff7b72', '#79c0ff', '#f0883e',
        '#56d364', '#db61a2', '#f778ba', '#8b949e',
    ]
    slices = []

    for p in data["accounts"]["a_share"].get("positions", []):
        suffix = ".SZ" if p["ticker"].startswith("0") else ".SS"
        mv_usd = abs(float(p.get("market_value", 0))) / EXCHANGE_RATE
        weight = mv_usd / combined_nav_usd * 100 if combined_nav_usd else 0
        slices.append((p["ticker"] + suffix, round(weight, 1)))

    for p in data["accounts"]["us"].get("positions", []):
        shares = p.get("shares", 0)
        price = float(p.get("current_price", p.get("avg_cost", 0)))
        mv_usd = abs(shares) * price
        weight = mv_usd / combined_nav_usd * 100 if combined_nav_usd else 0
        label = p["ticker"] + (" [空]" if shares < 0 else "")
        slices.append((label, round(weight, 1)))

    a_cash_usd = float(data["accounts"]["a_share"].get("cash", 0)) / EXCHANGE_RATE
    us_cash_usd = float(data["accounts"]["us"].get("cash", 0))
    total_cash_usd = a_cash_usd + us_cash_usd
    cash_weight = total_cash_usd / combined_nav_usd * 100 if combined_nav_usd else 0
    slices.append(("现金", round(cash_weight, 1)))

    slices.sort(key=lambda x: x[1], reverse=True)
    labels = [s[0] for s in slices]
    values = [s[1] for s in slices]
    colors = colors_pool[:len(labels)]
    return labels, values, colors


def generate():
    data = load()

    # 一体化: 先从positions重算汇总字段，写回JSON
    changes = sync_summary(data)
    if changes:
        save(data)
        for c in changes:
            print(f"  [sync] {c}")

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    dates, combined, spy_rets, a_w, u_w = calc_combined_returns(data)

    a_nav = calc_nav(data["accounts"]["a_share"], "a_share")
    us_nav = calc_nav(data["accounts"]["us"], "us")
    combined_nav_usd = a_nav / EXCHANGE_RATE + us_nav

    a_initial = data["accounts"]["a_share"]["initial_capital"]
    us_initial = data["accounts"]["us"]["initial_capital"]
    a_return = (a_nav / a_initial - 1) * 100
    us_return = (us_nav / us_initial - 1) * 100

    latest_combined = combined[-1] if combined else 0
    latest_spy = spy_rets[-1] if spy_rets else 0
    alpha = round(latest_combined - latest_spy, 2)

    peak = 0
    max_dd = 0
    for c in combined:
        if c > peak:
            peak = c
        dd = c - peak
        if dd < max_dd:
            max_dd = dd
    max_dd = round(max_dd, 2)

    hit_days = sum(1 for i in range(len(combined)) if combined[i] > spy_rets[i])
    hit_rate = round(hit_days / len(combined) * 100, 1) if combined else 0

    pie_labels, pie_values, pie_colors = build_pie(data, combined_nav_usd)
    positions_html = build_positions_html(data, combined_nav_usd)
    trades_js = build_trades_js(data)

    n_days = len(dates)

    # US exposure breakdown
    us_positions = data["accounts"]["us"].get("positions", [])
    us_long_mv = sum(
        float(p.get("current_price", 0)) * p.get("shares", 0)
        for p in us_positions if p.get("shares", 0) > 0
    )
    us_short_mv = sum(
        float(p.get("current_price", 0)) * abs(p.get("shares", 0))
        for p in us_positions if p.get("shares", 0) < 0
    )
    us_cash = float(data["accounts"]["us"].get("cash", 0))
    us_long_pct = us_long_mv / us_nav * 100 if us_nav else 0
    us_short_pct = us_short_mv / us_nav * 100 if us_nav else 0
    us_cash_pct = us_cash / us_nav * 100 if us_nav else 0
    us_net_pct = us_long_pct - us_short_pct

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Performance Leaderboard — Nexus AI 模拟盘</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
:root {{
  --bg: #0d1117; --card: #161b22; --border: #30363d;
  --text: #c9d1d9; --muted: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --red: #f85149; --yellow: #d29922;
  --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: var(--font); background: var(--bg); color: var(--text); line-height: 1.6; }}
.page {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }}
header.lb-header {{ text-align: center; padding: 32px 0 24px; border-bottom: 1px solid var(--border); margin-bottom: 32px; }}
header.lb-header h1 {{ font-size: 1.75rem; color: #fff; margin-bottom: 6px; }}
header.lb-header .subtitle {{ color: var(--muted); font-size: 0.85rem; }}
header.lb-header .updated {{ color: var(--muted); font-size: 0.75rem; margin-top: 8px; }}
.section {{ margin-bottom: 32px; }}
.section-title {{ font-size: 0.8rem; color: var(--muted); text-transform: uppercase;
  letter-spacing: 0.08em; margin-bottom: 14px; padding-bottom: 8px;
  border-bottom: 1px solid var(--border); }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 32px; }}
.kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px 20px; text-align: center; }}
.kpi .val {{ font-size: 1.6rem; font-weight: 700; line-height: 1.2; }}
.kpi .lbl {{ font-size: 0.72rem; color: var(--muted); margin-top: 4px; }}
.kpi .sublbl {{ font-size: 0.65rem; color: var(--muted); opacity: 0.7; margin-top: 2px; }}
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
.card h3 {{ font-size: 0.9rem; color: #fff; margin-bottom: 14px; }}
.hm-grid {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.hm-cell {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  padding: 10px 14px; min-width: 100px; text-align: center; }}
.hm-label {{ font-size: 0.7rem; color: var(--muted); }}
.hm-val {{ font-size: 1.1rem; font-weight: 700; margin-top: 2px; }}
.risk-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media (max-width: 640px) {{ .risk-grid {{ grid-template-columns: 1fr; }} }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
th {{ text-align: left; color: var(--muted); font-weight: 500; padding: 8px 10px;
  border-bottom: 1px solid var(--border); white-space: nowrap; }}
td {{ padding: 9px 10px; border-bottom: 1px solid #21262d; vertical-align: middle; }}
tr:last-child td {{ border-bottom: none; }}
.rationale-cell {{ color: var(--muted); font-size: 0.75rem; max-width: 260px; }}
.badge {{ display: inline-block; font-size: 0.65rem; padding: 1px 6px; border-radius: 3px;
  background: #21262d; color: var(--muted); white-space: nowrap; }}
.ticker-tag {{ font-family: monospace; color: var(--accent); font-size: 0.82rem; }}
.mono {{ font-family: monospace; font-size: 0.78rem; }}
.stop-bar-bg {{ background: #21262d; border-radius: 2px; height: 6px; width: 80px; }}
.stop-bar-fill {{ height: 6px; border-radius: 2px; }}
.audit-banner {{ display: flex; align-items: center; gap: 12px; background: #1b2a1b;
  border: 1px solid #2d4a2d; border-radius: 6px; padding: 10px 14px;
  text-align: center; font-size: 0.8rem; color: #7ee787; }}
.btn-csv {{ display: inline-flex; align-items: center; gap: 6px;
  background: #21262d; border: 1px solid var(--border); border-radius: 6px;
  color: var(--text); font-size: 0.8rem; padding: 7px 14px; cursor: pointer;
  text-decoration: none; margin-bottom: 14px; }}
.btn-csv:hover {{ background: #30363d; }}
.sub-kpi {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }}
.sub-kpi .item {{ background: #0d1117; border-radius: 6px; padding: 10px 14px; text-align: center; }}
.sub-kpi .item .val {{ font-size: 1.1rem; font-weight: 700; }}
.sub-kpi .item .lbl {{ font-size: 0.65rem; color: var(--muted); margin-top: 2px; }}
.exposure-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 10px; }}
.exposure-grid .item {{ background: #0d1117; border-radius: 6px; padding: 8px 10px; text-align: center; }}
.exposure-grid .item .val {{ font-size: 0.95rem; font-weight: 700; }}
.exposure-grid .item .lbl {{ font-size: 0.6rem; color: var(--muted); margin-top: 2px; }}
.disclaimer {{ font-size: 0.72rem; color: #484f58; text-align: center;
  margin-top: 32px; padding-top: 20px; border-top: 1px solid #21262d; }}
@media (max-width: 600px) {{
  .kpi .val {{ font-size: 1.25rem; }}
  table {{ font-size: 0.75rem; }}
  td, th {{ padding: 6px 6px; }}
  .rationale-cell {{ display: none; }}
  .exposure-grid {{ grid-template-columns: repeat(2, 1fr); }}
}}
</style>
</head>
<body>
<div class="page">

<header class="lb-header">
  <h1>Public Performance Leaderboard</h1>
  <div class="subtitle">Nexus AI 模拟盘 &middot; Claude AI独立管理 &middot; 2026-05-18 启动 &middot; Day {n_days}</div>
  <div class="updated">数据同步: {now}</div>
</header>

<div class="kpi-grid">
  <div class="kpi">
    <div class="val" style="color:{"#3fb950" if latest_combined >= 0 else "#f85149"}">{latest_combined:+.2f}%</div>
    <div class="lbl">综合收益率</div>
    <div class="sublbl">加权 (A股{a_w*100:.0f}% + US{u_w*100:.0f}%)</div>
  </div>
  <div class="kpi">
    <div class="val" style="color:{"#3fb950" if alpha >= 0 else "#f85149"}">{alpha:+.2f}%</div>
    <div class="lbl">Alpha vs SPY</div>
    <div class="sublbl">超额收益</div>
  </div>
  <div class="kpi">
    <div class="val" style="color:#58a6ff">N/A*</div>
    <div class="lbl">Sharpe (年化)</div>
    <div class="sublbl">*样本量&lt;30天时不可靠</div>
  </div>
  <div class="kpi">
    <div class="val" style="color:#f85149">{max_dd:+.2f}%</div>
    <div class="lbl">Max Drawdown</div>
    <div class="sublbl">综合峰谷回撤</div>
  </div>
  <div class="kpi">
    <div class="val" style="color:#58a6ff">{hit_rate:.0f}%</div>
    <div class="lbl">Hit Rate vs SPY</div>
    <div class="sublbl">日度跑赢比例 ({hit_days}/{len(combined)}天)</div>
  </div>
  <div class="kpi">
    <div class="val" style="color:#d29922">{len(data.get("trade_log",[]))}笔</div>
    <div class="lbl">总交易笔数</div>
    <div class="sublbl">Day 1 ~ Day {n_days}</div>
  </div>
</div>

<div class="card" style="margin-bottom:32px">
  <div class="sub-kpi">
    <div class="item">
      <div class="val" style="color:{"#3fb950" if a_return >= 0 else "#f85149"}">{a_return:+.2f}%</div>
      <div class="lbl">A股 (&#165;{a_initial:,.0f})</div>
    </div>
    <div class="item">
      <div class="val" style="color:{"#3fb950" if us_return >= 0 else "#f85149"}">{us_return:+.2f}%</div>
      <div class="lbl">美股 (${us_initial:,.0f})</div>
    </div>
  </div>
  <div class="exposure-grid">
    <div class="item">
      <div class="val" style="color:#3fb950">{us_long_pct:.1f}%</div>
      <div class="lbl">多头暴露</div>
    </div>
    <div class="item">
      <div class="val" style="color:#f85149">{us_short_pct:.1f}%</div>
      <div class="lbl">空头暴露</div>
    </div>
    <div class="item">
      <div class="val" style="color:{"#3fb950" if us_net_pct >= 0 else "#f85149"}">{us_net_pct:.1f}%</div>
      <div class="lbl">净暴露</div>
    </div>
    <div class="item">
      <div class="val" style="color:var(--accent)">{us_cash_pct:.1f}%</div>
      <div class="lbl">现金</div>
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">累计收益率 vs 基准</div>
  <div class="card">
    <div style="position:relative"><canvas id="returnChart" height="220"></canvas></div>
  </div>
</div>

<div class="section">
  <div class="section-title">月度收益热力图</div>
  <div class="card">
    <div class="hm-grid">
      <div class="hm-cell" style="background:{"#1b3d2a" if latest_combined >= 0 else "#3d1b1b"}">
        <div class="hm-label">2026-05</div>
        <div class="hm-val" style="color:{"#3fb950" if latest_combined >= 0 else "#f85149"}">{latest_combined:+.2f}%</div>
      </div>
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">风险仪表盘</div>
  <div class="risk-grid">
    <div class="card">
      <h3>收益率 vs 基准 (最新)</h3>
      <canvas id="benchChart" height="200"></canvas>
    </div>
    <div class="card">
      <h3>仓位集中度 (合并组合)</h3>
      <canvas id="pieChart" height="200"></canvas>
    </div>
  </div>
</div>

<div class="section">
  <div class="section-title">当前持仓 + 止损距离 (占合并组合%)</div>
  <div class="card">
    <table>
    <thead><tr>
      <th>账户</th><th>标的</th><th>板块</th>
      <th style="text-align:right">仓位%</th>
      <th style="text-align:right">浮盈/亏</th>
      <th>止损空间</th>
    </tr></thead>
    <tbody>
{positions_html}
    </tbody>
    </table>
  </div>
</div>

<div class="section">
  <div class="section-title">完整交易记录 (Immutable Audit Log)</div>
  <div class="audit-banner">
    <svg width="16" height="16" viewBox="0 0 16 16" fill="#7ee787">
      <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm.25 3.5a.75.75 0 0 0-1.5 0v5.19L4.22 7.16a.75.75 0 1 0-1.07 1.06l3.25 3.25a.75.75 0 0 0 1.06 0l3.25-3.25a.75.75 0 0 0-1.06-1.06l-2.47 2.47V3.5z"/>
    </svg>
    每笔交易在执行时写入 portfolio_state.json 并通过 git commit 固化时间戳，不可追溯修改。共 {len(data.get("trade_log",[]))} 笔。
  </div>
  <a class="btn-csv" href="#" onclick="downloadCSV()">
    <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
      <path d="M2.75 14A1.75 1.75 0 0 1 1 12.25v-2.5a.75.75 0 0 1 1.5 0v2.5c0 .138.112.25.25.25h10.5a.25.25 0 0 0 .25-.25v-2.5a.75.75 0 0 1 1.5 0v2.5A1.75 1.75 0 0 1 13.25 14Z"/>
      <path d="M7.25 7.689V2a.75.75 0 0 1 1.5 0v5.689l1.97-1.97a.749.749 0 1 1 1.06 1.06l-3.25 3.25a.749.749 0 0 1-1.06 0L4.22 6.78a.749.749 0 1 1 1.06-1.06l1.97 1.969Z"/>
    </svg>
    下载完整交易历史 CSV
  </a>
  <div class="card" style="padding: 0; overflow-x: auto;">
    <table>
    <thead><tr>
      <th>时间戳</th><th>账户</th><th>操作</th><th>标的</th>
      <th style="text-align:right">股数</th>
      <th style="text-align:right">价格</th>
      <th style="text-align:right">金额</th>
      <th>决策依据</th>
    </tr></thead>
    <tbody id="tradeBody"></tbody>
    </table>
  </div>
</div>

<div class="disclaimer">
  此为AI系统模拟投资组合，仅用于研究验证。不构成投资建议。<br>
  Sharpe与VaR在启动初期（样本&lt;30天）仅为方向性参考，不具统计意义。<br>
  NAV计算: A股=现金+市值; 美股=现金+多头市值+空头浮盈亏; 仓位%=个股市值/合并NAV(USD)<br>
  Nexus Research System &middot; Powered by Claude AI
</div>

</div>

<script>
const DATES    = {json.dumps(dates)};
const COMBINED = {json.dumps(combined)};
const SPY      = {json.dumps(spy_rets)};

const PIE_LABELS = {json.dumps(pie_labels)};
const PIE_VALUES = {json.dumps(pie_values)};
const PIE_COLORS = {json.dumps(pie_colors)};

const TRADES = [
{trades_js}
];

const tbody = document.getElementById('tradeBody');
TRADES.forEach(t => {{
  const ac = (t.action === 'buy' || t.action === 'cover') ? '#3fb950' : '#f85149';
  tbody.innerHTML += `<tr>
    <td class="mono">${{t.ts}}</td>
    <td><span class="badge">${{t.acct}}</span></td>
    <td style="color:${{ac}};font-weight:600">${{t.cn}}</td>
    <td><span class="ticker-tag">${{t.ticker}}</span></td>
    <td style="text-align:right" class="mono">${{t.shares}}</td>
    <td style="text-align:right" class="mono">${{t.cur}}${{t.price.toFixed(2)}}</td>
    <td style="text-align:right" class="mono">${{t.cur}}${{t.val.toLocaleString()}}</td>
    <td class="rationale-cell">${{t.rationale}}</td>
  </tr>`;
}});

new Chart(document.getElementById('returnChart'), {{
  type: 'line',
  data: {{
    labels: DATES,
    datasets:[
      {{label:'Nexus综合', data:COMBINED, borderColor:'#3fb950', borderWidth:2.5, pointRadius:5, tension:0.3, fill:false}},
      {{label:'SPY',       data:SPY,      borderColor:'#58a6ff', borderWidth:1.5, pointRadius:4, tension:0.3, fill:false, borderDash:[5,3]}},
    ]
  }},
  options:{{
    plugins:{{legend:{{labels:{{color:'#8b949e',font:{{size:11}}}}}}}},
    scales:{{
      x:{{ticks:{{color:'#8b949e',font:{{size:10}}}},grid:{{color:'#21262d'}}}},
      y:{{ticks:{{color:'#8b949e',callback:v=>v+'%'}},grid:{{color:'#21262d'}}}}
    }}
  }}
}});

new Chart(document.getElementById('benchChart'), {{
  type: 'bar',
  data:{{
    labels:['Nexus综合','SPY'],
    datasets:[{{data:[COMBINED.at(-1), SPY.at(-1)],
      backgroundColor:['#3fb950','#58a6ff'],borderRadius:4}}]
  }},
  options:{{
    plugins:{{legend:{{display:false}}}},
    scales:{{
      x:{{ticks:{{color:'#8b949e'}},grid:{{display:false}}}},
      y:{{ticks:{{color:'#8b949e',callback:v=>v+'%'}},grid:{{color:'#21262d'}}}}
    }}
  }}
}});

new Chart(document.getElementById('pieChart'), {{
  type:'doughnut',
  data:{{
    labels:PIE_LABELS,
    datasets:[{{data:PIE_VALUES, backgroundColor:PIE_COLORS, borderWidth:1, borderColor:'#161b22'}}]
  }},
  options:{{
    plugins:{{legend:{{position:'right',labels:{{color:'#8b949e',font:{{size:10}},boxWidth:10,padding:6}}}}}}
  }}
}});

function downloadCSV() {{
  const rows = ["timestamp,account,action,ticker,shares,price,value,currency,rationale"];
  TRADES.forEach(t => rows.push(`${{t.ts}},${{t.acct}},${{t.action}},${{t.ticker}},${{t.shares}},${{t.price}},${{t.val}},${{t.cur}},"${{t.rationale}}"`));
  const blob = new Blob([rows.join('\\n')], {{type:'text/csv'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'nexus_trade_history.csv';
  a.click();
}}
</script>
</body>
</html>"""

    with open(OUTPUT, "w") as f:
        f.write(html)

    print(f"[OK] leaderboard.html generated — {len(dates)} days, {len(data.get('trade_log',[]))} trades")
    print(f"  A股 NAV: ¥{a_nav:,.0f} ({a_return:+.2f}%)")
    print(f"  美股 NAV: ${us_nav:,.2f} ({us_return:+.2f}%)")
    print(f"  合并 NAV: ${combined_nav_usd:,.2f}")
    print(f"  美股暴露: Long {us_long_pct:.1f}% / Short {us_short_pct:.1f}% / Net {us_net_pct:.1f}% / Cash {us_cash_pct:.1f}%")

    # 同步到 nexus-package (Railway 部署源)
    sync_website(data, a_nav, us_nav, a_return, us_return)


def sync_website(data, a_nav, us_nav, a_return, us_return):
    """从 portfolio_state.json 生成 nexus-package/sim-portfolio.json 并 git push。"""
    NEXUS_PKG = Path.home() / "claude-projects" / "nexus-package"
    SIM_JSON = NEXUS_PKG / "output-buffer" / "sim-portfolio.json"
    if not SIM_JSON.parent.exists():
        print("  [website] nexus-package not found, skip")
        return

    now = datetime.now().astimezone().isoformat()

    def export_positions(acct_data, market):
        out = []
        for p in acct_data.get("positions", []):
            shares = p.get("shares", 0)
            ticker = p["ticker"]
            if market == "a_share":
                if ticker.startswith("0") or ticker.startswith("3"):
                    ticker += ".SZ"
                else:
                    ticker += ".SS"
            ep = {
                "ticker": ticker,
                "name": p.get("name", ticker),
                "shares": shares,
                "avg_cost": p.get("avg_cost"),
                "current_price": p.get("current_price"),
                "market_value": p.get("market_value"),
                "unrealized_pnl_pct": p.get("unrealized_pnl_pct"),
                "portfolio_pct": p.get("portfolio_pct"),
                "entry_date": p.get("entry_date"),
                "type": p.get("type", "short_position" if shares < 0 else "trading_position"),
                "sector": p.get("sector", ""),
            }
            out.append(ep)
        return out

    def build_snapshots(data):
        snaps = []
        a_init = data["accounts"]["a_share"]["initial_capital"]
        us_init = data["accounts"]["us"]["initial_capital"]
        a_w = (a_init / EXCHANGE_RATE) / (a_init / EXCHANGE_RATE + us_init)
        u_w = 1 - a_w
        for s in data.get("performance", {}).get("daily_snapshots", []):
            a_ret = s.get("a_share_return_pct", 0)
            u_ret = s.get("us_return_pct", 0)
            snaps.append({
                "date": s["date"],
                "a_share": {
                    "total_assets": s.get("a_share_nav", a_init),
                    "return_pct": a_ret,
                },
                "us": {
                    "total_assets": s.get("us_nav", us_init),
                    "return_pct": u_ret,
                },
                "combined_return_pct": round(a_ret * a_w + u_ret * u_w, 2),
            })
        return snaps

    def build_trade_log(data):
        out = []
        for t in data.get("trade_log", []):
            entry = {
                "date": t.get("timestamp", "")[:10],
                "account": t.get("account", "us"),
                "action": t.get("action", "buy"),
                "ticker": t.get("ticker"),
                "shares": t.get("shares", 0),
                "price": t.get("price", 0),
            }
            if t.get("realized_pnl"):
                entry["realized_pnl"] = t["realized_pnl"]
            out.append(entry)
        return out

    sim = {
        "meta": {
            "type": "sim_portfolio",
            "description": "Claude AI模拟盘 — ¥10M A股 + $1.5M 美股",
            "start_date": data.get("_meta", {}).get("start_date", "2026-05-18"),
            "end_date": data.get("_meta", {}).get("end_date", "2026-06-18"),
            "last_updated": now,
            "benchmark": {"a_share": "CSI300", "us": "SPY"},
            "disclaimer": "模拟盘，非真实交易。仅供研究参考。",
        },
        "accounts": {
            "a_share": {
                "currency": "CNY",
                "initial_capital": data["accounts"]["a_share"]["initial_capital"],
                "total_assets": round(a_nav, 2),
                "cash": data["accounts"]["a_share"]["cash"],
                "realized_pnl": data["accounts"]["a_share"].get("realized_pnl", 0),
                "return_pct": round(a_return, 2),
                "positions": export_positions(data["accounts"]["a_share"], "a_share"),
            },
            "us": {
                "currency": "USD",
                "initial_capital": data["accounts"]["us"]["initial_capital"],
                "total_assets": round(us_nav, 2),
                "cash": data["accounts"]["us"]["cash"],
                "realized_pnl": data["accounts"]["us"].get("realized_pnl", 0),
                "return_pct": round(us_return, 2),
                "positions": export_positions(data["accounts"]["us"], "us"),
            },
        },
        "daily_snapshots": build_snapshots(data),
        "trade_log": build_trade_log(data),
    }

    with open(SIM_JSON, "w") as f:
        json.dump(sim, f, indent=2, ensure_ascii=False)

    print(f"  [website] sim-portfolio.json synced → US ${us_nav:,.2f} ({us_return:+.2f}%)")


if __name__ == "__main__":
    generate()

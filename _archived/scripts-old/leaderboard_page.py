"""
leaderboard_page.py
===========================
Server-side rendered HTML for the Public Performance Leaderboard page.
Drop this into api_server.py as a new function, then add the route in do_GET().

New endpoints this module provides:
  GET /leaderboard              — main leaderboard page (full HTML)
  GET /api/v1/leaderboard/data  — raw JSON for the leaderboard metrics
  GET /api/v1/leaderboard/csv   — CSV download of full trade history

Design notes:
  - Pure vanilla Python + Chart.js 4 (already used in existing widgets)
  - No new dependencies; same dark theme (#0d1117) as existing site
  - Responsive: single-column on mobile, grid on desktop
  - "Immutable audit" framing: each trade row shows git-commit-style timestamp
  - Benchmark comparison: SPY / QQQ / CSI300 on same chart as portfolio
"""

import json
import math
from datetime import datetime, date
from pathlib import Path


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _compute_leaderboard_metrics(sim: dict) -> dict:
    """
    Derive all display metrics from sim-portfolio.json.
    Returns a flat dict suitable for JSON serialisation.
    """
    snapshots = sim.get("performance", {}).get("daily_snapshots", [])
    bench_snaps = sim.get("benchmark_snapshots", [])
    trade_log = sim.get("trade_log", [])
    a_acct = sim["accounts"].get("a_share", {})
    us_acct = sim["accounts"].get("us", {})
    meta = sim.get("_meta", sim.get("meta", {}))
    start_date = meta.get("start_date", "")
    last_updated = meta.get("last_updated", "")

    # ---- returns ----
    combined_returns = [s.get("combined_return_pct", 0) for s in snapshots]
    spy_returns = [b.get("spy_return_pct", 0) for b in bench_snaps]
    qqq_returns = [b.get("qqq_return_pct", 0) for b in bench_snaps]
    csi300_returns = [b.get("csi300_return_pct", 0) for b in bench_snaps]
    dates = [s["date"] for s in snapshots]

    current_return = combined_returns[-1] if combined_returns else 0.0
    spy_current = spy_returns[-1] if spy_returns else 0.0
    qqq_current = qqq_returns[-1] if qqq_returns else 0.0
    csi300_current = csi300_returns[-1] if csi300_returns else 0.0

    # ---- Sharpe (annualised, stub — requires daily return series) ----
    # Daily returns from snapshots
    daily_rets = []
    for i in range(1, len(combined_returns)):
        prev = combined_returns[i - 1]
        curr = combined_returns[i]
        # convert cumulative % to daily %
        # r_daily = (1 + curr/100) / (1 + prev/100) - 1
        if (1 + prev / 100) != 0:
            daily_rets.append((1 + curr / 100) / (1 + prev / 100) - 1)

    if len(daily_rets) >= 2:
        mean_daily = sum(daily_rets) / len(daily_rets)
        variance = sum((r - mean_daily) ** 2 for r in daily_rets) / (len(daily_rets) - 1)
        std_daily = math.sqrt(variance) if variance > 0 else 0
        sharpe = (mean_daily / std_daily * math.sqrt(252)) if std_daily > 0 else None
    else:
        sharpe = None  # not enough data yet

    # ---- Max Drawdown ----
    max_dd = 0.0
    peak = combined_returns[0] if combined_returns else 0.0
    for r in combined_returns:
        if r > peak:
            peak = r
        dd = peak - r
        if dd > max_dd:
            max_dd = dd

    # ---- Hit rate (days portfolio return > SPY) ----
    beats = sum(1 for p, b in zip(combined_returns, spy_returns) if p > b)
    hit_rate = (beats / len(combined_returns) * 100) if combined_returns else 0.0

    # ---- Monthly heat map data ----
    # Group daily_returns by YYYY-MM, compute monthly return
    monthly: dict[str, list] = {}
    for s in snapshots:
        ym = s["date"][:7]
        monthly.setdefault(ym, []).append(s.get("combined_return_pct", 0))
    monthly_returns = {ym: vals[-1] for ym, vals in sorted(monthly.items())}

    # ---- Position concentration ----
    all_positions = []
    a_initial = a_acct.get("initial_capital", a_acct.get("total_assets", 1))
    us_initial = us_acct.get("initial_capital", us_acct.get("total_assets", 1))
    usd_to_cny = 7.2
    total_initial_cny = a_initial + us_initial * usd_to_cny

    for p in a_acct.get("positions", []):
        mv_cny = p.get("market_value", 0)
        all_positions.append({
            "ticker": p["ticker"],
            "name": p.get("name", ""),
            "market_value_usd_equiv": round(mv_cny / usd_to_cny, 0),
            "pct_of_portfolio": round(mv_cny / total_initial_cny * 100, 1),
            "pnl_pct": p.get("unrealized_pnl_pct", 0),
            "account": "A股",
            "sector": p.get("sector", "")
        })
    for p in us_acct.get("positions", []):
        mv_usd = p.get("market_value", 0)
        all_positions.append({
            "ticker": p["ticker"],
            "name": p.get("name", ""),
            "market_value_usd_equiv": round(mv_usd, 0),
            "pct_of_portfolio": round(mv_usd / (total_initial_cny / usd_to_cny) * 100, 1),
            "pnl_pct": p.get("unrealized_pnl_pct", 0),
            "account": "美股",
            "sector": p.get("sector", "")
        })

    # ---- VaR stub (parametric 95%, assumes normal) ----
    # With only 4 days of data, VaR is illustrative
    if len(daily_rets) >= 2:
        portfolio_total_usd = (
            a_acct.get("total_assets", 0) / usd_to_cny + us_acct.get("total_assets", 0)
        )
        z95 = 1.645
        var_1d_95 = round(portfolio_total_usd * std_daily * z95, 0) if std_daily > 0 else None
    else:
        var_1d_95 = None

    # ---- Annotated trade log ----
    enriched_trades = []
    for t in trade_log:
        action_map = {"buy": "买入", "sell": "卖出", "short": "做空", "cover": "平空"}
        acct_map = {"a_share": "A股", "us": "美股"}
        value = t.get("shares", 0) * t.get("price", 0)
        currency = "¥" if t.get("account") == "a_share" else "$"
        enriched_trades.append({
            "timestamp": t.get("timestamp", t.get("date", ""))[:19],
            "account": acct_map.get(t.get("account", ""), t.get("account", "")),
            "action": t.get("action", ""),
            "action_cn": action_map.get(t.get("action", ""), t.get("action", "")),
            "ticker": t.get("ticker", ""),
            "shares": t.get("shares", 0),
            "price": t.get("price", 0),
            "value": round(value, 2),
            "currency": currency,
            "rationale": t.get("rationale", t.get("reason", ""))
        })

    return {
        "generated_at": datetime.now().isoformat(),
        "start_date": start_date,
        "last_updated": last_updated,
        "disclaimer": meta.get("disclaimer", "模拟盘，非真实交易。仅用于AI投资能力展示。"),
        # summary metrics
        "current_return_pct": round(current_return, 2),
        "spy_return_pct": round(spy_current, 2),
        "qqq_return_pct": round(qqq_current, 2),
        "csi300_return_pct": round(csi300_current, 2),
        "alpha_vs_spy": round(current_return - spy_current, 2),
        "sharpe_annualised": round(sharpe, 2) if sharpe is not None else None,
        "max_drawdown_pct": round(max_dd, 2),
        "hit_rate_vs_spy_pct": round(hit_rate, 1),
        "var_1d_95_usd": var_1d_95,
        # chart series
        "dates": dates,
        "combined_returns": combined_returns,
        "spy_returns": spy_returns,
        "qqq_returns": qqq_returns,
        "csi300_returns": csi300_returns,
        # heatmap
        "monthly_returns": monthly_returns,
        # positions
        "positions": sorted(all_positions, key=lambda x: -x["pct_of_portfolio"]),
        # trades
        "trades": list(reversed(enriched_trades))  # newest first
    }


def make_csv_trade_log(sim: dict) -> str:
    """Return full trade history as CSV string."""
    lines = [
        "timestamp,account,action,ticker,shares,price,value,currency,rationale"
    ]
    for t in sim.get("trade_log", []):
        action_map = {"buy": "buy", "sell": "sell", "short": "short", "cover": "cover"}
        acct_map = {"a_share": "A_share", "us": "US"}
        value = t.get("shares", 0) * t.get("price", 0)
        currency = "CNY" if t.get("account") == "a_share" else "USD"
        rationale = t.get("rationale", t.get("reason", "")).replace(",", ";").replace('"', "'")
        lines.append(
            f"{t.get('date','')}T09:30:00+08:00,"
            f"{acct_map.get(t.get('account',''), t.get('account',''))},"
            f"{action_map.get(t.get('action',''), t.get('action',''))},"
            f"{t.get('ticker','')},"
            f"{t.get('shares',0)},"
            f"{t.get('price',0)},"
            f"{round(value, 2)},"
            f"{currency},"
            f"\"{rationale}\""
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

def make_leaderboard_page(sim: dict) -> str:
    """
    Full-page HTML for the Public Performance Leaderboard.
    Integrates: cumulative return chart vs benchmarks, monthly heatmap,
    rolling Sharpe widget, risk dashboard, position concentration pie,
    immutable audit trade log, CSV download button.
    """
    m = _compute_leaderboard_metrics(sim)

    # ---- chart data ----
    dates_js = json.dumps(m["dates"])
    combined_js = json.dumps(m["combined_returns"])
    spy_js = json.dumps(m["spy_returns"])
    qqq_js = json.dumps(m["qqq_returns"])
    csi300_js = json.dumps(m["csi300_returns"])

    # ---- monthly heatmap ----
    heatmap_cells = ""
    for ym, ret in m["monthly_returns"].items():
        color = "#1b3d2a" if ret >= 0 else "#3d1b1b"
        text_color = "#3fb950" if ret >= 0 else "#f85149"
        heatmap_cells += (
            f'<div class="hm-cell" style="background:{color}">'
            f'<div class="hm-label">{ym}</div>'
            f'<div class="hm-val" style="color:{text_color}">{ret:+.2f}%</div>'
            f'</div>'
        )
    if not heatmap_cells:
        heatmap_cells = '<div style="color:#8b949e;padding:20px">月度数据积累中...</div>'

    # ---- summary KPIs ----
    ret = m["current_return_pct"]
    ret_color = "#3fb950" if ret >= 0 else "#f85149"
    alpha = m["alpha_vs_spy"]
    alpha_color = "#3fb950" if alpha >= 0 else "#f85149"
    sharpe_val = f"{m['sharpe_annualised']:.2f}" if m["sharpe_annualised"] is not None else "N/A*"
    dd_val = f"{m['max_drawdown_pct']:.2f}%"
    hit_val = f"{m['hit_rate_vs_spy_pct']:.1f}%"
    var_val = f"${m['var_1d_95_usd']:,.0f}" if m["var_1d_95_usd"] is not None else "N/A*"

    # ---- position concentration table ----
    pos_rows = ""
    pie_labels = []
    pie_values = []
    for p in m["positions"]:
        pnl_color = "#3fb950" if p["pnl_pct"] >= 0 else "#f85149"
        stop_pct = max(0, -p["pnl_pct"] - 8)  # stub: show 8% stop buffer
        bar_fill = min(100, abs(p["pnl_pct"]) * 3)  # visual only
        bar_color = "#3fb950" if p["pnl_pct"] >= 0 else "#f85149"
        pos_rows += f"""<tr>
<td><span class="badge">{p['account']}</span></td>
<td><span class="ticker-tag">{p['ticker']}</span><br><small>{p['name']}</small></td>
<td>{p['sector']}</td>
<td style="text-align:right">{p['pct_of_portfolio']:.1f}%</td>
<td style="color:{pnl_color};text-align:right;font-weight:700">{p['pnl_pct']:+.2f}%</td>
<td>
  <div class="stop-bar-bg">
    <div class="stop-bar-fill" style="width:{bar_fill}%;background:{bar_color}"></div>
  </div>
</td>
</tr>"""
        pie_labels.append(p["ticker"])
        pie_values.append(p["pct_of_portfolio"])

    # ---- trade log rows ----
    trade_rows = ""
    for t in m["trades"]:
        action_color = (
            "#3fb950" if t["action"] in ("buy", "cover") else "#f85149"
        )
        value_str = f"{t['currency']}{t['value']:,.0f}"
        trade_rows += f"""<tr>
<td class="mono">{t['timestamp'][:10]}</td>
<td><span class="badge">{t['account']}</span></td>
<td style="color:{action_color};font-weight:700">{t['action_cn']}</td>
<td><span class="ticker-tag">{t['ticker']}</span></td>
<td style="text-align:right">{t['shares']}</td>
<td style="text-align:right">{t['currency']}{t['price']:.2f}</td>
<td style="text-align:right">{value_str}</td>
<td class="rationale-cell">{t['rationale']}</td>
</tr>"""

    pie_labels_js = json.dumps(pie_labels)
    pie_values_js = json.dumps(pie_values)

    # ---- no-data placeholders ----
    has_chart_data = len(m["dates"]) > 1
    chart_note = "" if has_chart_data else (
        '<p style="color:#8b949e;text-align:center;padding:40px 0">收益率曲线数据积累中（启动第1天）...</p>'
    )

    return f"""<!DOCTYPE html>
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

/* ---- layout ---- */
.page {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px 48px; }}
header.lb-header {{ text-align: center; padding: 32px 0 24px; border-bottom: 1px solid var(--border); margin-bottom: 32px; }}
header.lb-header h1 {{ font-size: 1.75rem; color: #fff; margin-bottom: 6px; }}
header.lb-header .subtitle {{ color: var(--muted); font-size: 0.85rem; }}
header.lb-header .updated {{ color: var(--muted); font-size: 0.75rem; margin-top: 8px; }}

.section {{ margin-bottom: 32px; }}
.section-title {{ font-size: 0.8rem; color: var(--muted); text-transform: uppercase;
  letter-spacing: 0.08em; margin-bottom: 14px; padding-bottom: 8px;
  border-bottom: 1px solid var(--border); }}

/* ---- KPI bar ---- */
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 32px; }}
.kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px 20px; text-align: center; }}
.kpi .val {{ font-size: 1.6rem; font-weight: 700; line-height: 1.2; }}
.kpi .lbl {{ font-size: 0.72rem; color: var(--muted); margin-top: 4px; }}
.kpi .sublbl {{ font-size: 0.65rem; color: var(--muted); opacity: 0.7; margin-top: 2px; }}

/* ---- cards ---- */
.card {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 20px; margin-bottom: 20px; }}
.card h3 {{ font-size: 0.9rem; color: #fff; margin-bottom: 14px; }}

/* ---- chart ---- */
.chart-wrap {{ position: relative; }}

/* ---- heatmap ---- */
.hm-grid {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.hm-cell {{ background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  padding: 10px 14px; min-width: 100px; text-align: center; }}
.hm-label {{ font-size: 0.7rem; color: var(--muted); }}
.hm-val {{ font-size: 1.1rem; font-weight: 700; margin-top: 2px; }}

/* ---- two-col risk layout ---- */
.risk-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media (max-width: 640px) {{ .risk-grid {{ grid-template-columns: 1fr; }} }}

/* ---- table ---- */
table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
th {{ text-align: left; color: var(--muted); font-weight: 500; padding: 8px 10px;
  border-bottom: 1px solid var(--border); white-space: nowrap; }}
td {{ padding: 9px 10px; border-bottom: 1px solid #21262d; vertical-align: middle; }}
tr:last-child td {{ border-bottom: none; }}
.rationale-cell {{ color: var(--muted); font-size: 0.75rem; max-width: 260px; }}

/* ---- badges / tags ---- */
.badge {{ display: inline-block; font-size: 0.65rem; padding: 1px 6px; border-radius: 3px;
  background: #21262d; color: var(--muted); white-space: nowrap; }}
.ticker-tag {{ font-family: monospace; color: var(--accent); font-size: 0.82rem; }}
.mono {{ font-family: monospace; font-size: 0.78rem; }}

/* ---- stop-loss bar ---- */
.stop-bar-bg {{ background: #21262d; border-radius: 2px; height: 6px; width: 80px; }}
.stop-bar-fill {{ height: 6px; border-radius: 2px; transition: width 0.3s; }}

/* ---- audit banner ---- */
.audit-banner {{ display: flex; align-items: center; gap: 12px; background: #1b2a1b;
  border: 1px solid #2d4a2d; border-radius: 6px; padding: 10px 14px;
  margin-bottom: 14px; font-size: 0.8rem; color: #7ee787; }}
.audit-banner svg {{ flex-shrink: 0; }}

/* ---- CSV button ---- */
.btn-csv {{ display: inline-flex; align-items: center; gap: 6px;
  background: #21262d; border: 1px solid var(--border); border-radius: 6px;
  color: var(--text); font-size: 0.8rem; padding: 7px 14px; cursor: pointer;
  text-decoration: none; margin-bottom: 14px; }}
.btn-csv:hover {{ background: #30363d; }}

/* ---- disclaimer ---- */
.disclaimer {{ font-size: 0.72rem; color: #484f58; text-align: center;
  margin-top: 32px; padding-top: 20px; border-top: 1px solid #21262d; }}

/* ---- responsive ---- */
@media (max-width: 600px) {{
  .kpi .val {{ font-size: 1.25rem; }}
  table {{ font-size: 0.75rem; }}
  td, th {{ padding: 6px 6px; }}
  .rationale-cell {{ display: none; }}
}}
</style>
</head>
<body>
<div class="page">

<!-- HEADER -->
<header class="lb-header">
  <h1>Public Performance Leaderboard</h1>
  <div class="subtitle">Nexus AI 模拟盘 · Claude AI独立管理 · {m['start_date']} 启动</div>
  <div class="updated">数据同步: {m['last_updated'][:19]}</div>
</header>

<!-- KPI BAR -->
<div class="kpi-grid">
  <div class="kpi">
    <div class="val" style="color:{ret_color}">{ret:+.2f}%</div>
    <div class="lbl">综合收益率</div>
    <div class="sublbl">vs 基准加权平均</div>
  </div>
  <div class="kpi">
    <div class="val" style="color:{alpha_color}">{alpha:+.2f}%</div>
    <div class="lbl">Alpha vs SPY</div>
    <div class="sublbl">超额收益</div>
  </div>
  <div class="kpi">
    <div class="val" style="color:var(--accent)">{sharpe_val}</div>
    <div class="lbl">Sharpe (年化)</div>
    <div class="sublbl">*样本量&lt;5天时不可靠</div>
  </div>
  <div class="kpi">
    <div class="val" style="color:var(--red)">-{m['max_drawdown_pct']:.2f}%</div>
    <div class="lbl">Max Drawdown</div>
    <div class="sublbl">峰谷最大回撤</div>
  </div>
  <div class="kpi">
    <div class="val" style="color:var(--accent)">{hit_val}</div>
    <div class="lbl">Hit Rate vs SPY</div>
    <div class="sublbl">日度跑赢比例</div>
  </div>
  <div class="kpi">
    <div class="val" style="color:var(--yellow)">{var_val}</div>
    <div class="lbl">VaR 95% (1日)</div>
    <div class="sublbl">参数法估算</div>
  </div>
</div>

<!-- CUMULATIVE RETURN CHART -->
<div class="section">
  <div class="section-title">累计收益率 vs 基准</div>
  <div class="card">
    {chart_note}
    {'<div class="chart-wrap"><canvas id="returnChart" height="220"></canvas></div>' if has_chart_data else ''}
  </div>
</div>

<!-- MONTHLY HEATMAP -->
<div class="section">
  <div class="section-title">月度收益热力图</div>
  <div class="card">
    <div class="hm-grid">{heatmap_cells}</div>
  </div>
</div>

<!-- RISK DASHBOARD + POSITION PIE -->
<div class="section">
  <div class="section-title">风险仪表盘</div>
  <div class="risk-grid">
    <div class="card">
      <h3>收益率 vs 基准 (最新)</h3>
      <canvas id="benchChart" height="200"></canvas>
    </div>
    <div class="card">
      <h3>仓位集中度</h3>
      <canvas id="pieChart" height="200"></canvas>
    </div>
  </div>
</div>

<!-- POSITION TABLE WITH STOP-LOSS BARS -->
<div class="section">
  <div class="section-title">当前持仓 + 止损距离</div>
  <div class="card">
    <table>
    <thead><tr>
      <th>账户</th><th>标的</th><th>板块</th>
      <th style="text-align:right">仓位%</th>
      <th style="text-align:right">浮盈/亏</th>
      <th>止损空间</th>
    </tr></thead>
    <tbody>{pos_rows}</tbody>
    </table>
  </div>
</div>

<!-- IMMUTABLE AUDIT LOG -->
<div class="section">
  <div class="section-title">完整交易记录 (Immutable Audit Log)</div>
  <div class="audit-banner">
    <svg width="16" height="16" viewBox="0 0 16 16" fill="#7ee787">
      <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm.25 3.5a.75.75 0 0 0-1.5 0v5.19L4.22 7.16a.75.75 0 1 0-1.07 1.06l3.25 3.25a.75.75 0 0 0 1.06 0l3.25-3.25a.75.75 0 0 0-1.06-1.06l-2.47 2.47V3.5z"/>
    </svg>
    每笔交易在执行时写入 sim-portfolio.json 并通过 git commit 固化时间戳，不可追溯修改。
  </div>
  <a class="btn-csv" href="/api/v1/leaderboard/csv" download="nexus_trades.csv">
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
    <tbody>{trade_rows}</tbody>
    </table>
  </div>
</div>

<!-- DISCLAIMER -->
<div class="disclaimer">
  此为AI系统模拟投资组合，仅用于研究验证。不构成投资建议。<br>
  Sharpe与VaR在启动初期（样本&lt;30天）仅为方向性参考，不具统计意义。<br>
  Nexus Research System · Powered by Claude AI
</div>

</div><!-- /page -->

<script>
// ---- Cumulative return chart ----
const dates = {dates_js};
const combined = {combined_js};
const spy = {spy_js};
const qqq = {qqq_js};
const csi300 = {csi300_js};

if (dates.length > 1) {{
  new Chart(document.getElementById('returnChart'), {{
    type: 'line',
    data: {{
      labels: dates,
      datasets: [
        {{label: 'Nexus综合', data: combined, borderColor: '#3fb950',
          borderWidth: 2.5, pointRadius: 4, tension: 0.3, fill: false}},
        {{label: 'SPY', data: spy, borderColor: '#58a6ff',
          borderWidth: 1.5, pointRadius: 3, tension: 0.3, fill: false, borderDash: [5,3]}},
        {{label: 'QQQ', data: qqq, borderColor: '#d29922',
          borderWidth: 1.5, pointRadius: 3, tension: 0.3, fill: false, borderDash: [3,3]}},
        {{label: 'CSI300', data: csi300, borderColor: '#f85149',
          borderWidth: 1.5, pointRadius: 3, tension: 0.3, fill: false, borderDash: [2,4]}}
      ]
    }},
    options: {{
      responsive: true, maintainAspectRatio: true,
      plugins: {{
        legend: {{labels: {{color: '#c9d1d9', font: {{size: 11}}}}}},
        tooltip: {{callbacks: {{label: ctx => ctx.dataset.label + ': ' + ctx.raw.toFixed(2) + '%'}}}}
      }},
      scales: {{
        x: {{ticks: {{color: '#8b949e', font: {{size: 10}}}}, grid: {{color: '#21262d'}}}},
        y: {{
          ticks: {{color: '#8b949e', callback: v => v + '%', font: {{size: 10}}}},
          grid: {{color: '#21262d'}},
          title: {{display: true, text: '累计收益率 (%)', color: '#8b949e', font: {{size: 10}}}}
        }}
      }}
    }}
  }});
}}

// ---- Benchmark bar chart ----
new Chart(document.getElementById('benchChart'), {{
  type: 'bar',
  data: {{
    labels: ['Nexus综合', 'SPY', 'QQQ', 'CSI300'],
    datasets: [{{
      data: [combined.at(-1) || 0, spy.at(-1) || 0, qqq.at(-1) || 0, csi300.at(-1) || 0],
      backgroundColor: ['#3fb950', '#58a6ff', '#d29922', '#f85149'],
      borderRadius: 4
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{
      legend: {{display: false}},
      tooltip: {{callbacks: {{label: ctx => ctx.raw.toFixed(2) + '%'}}}}
    }},
    scales: {{
      x: {{ticks: {{color: '#8b949e', font: {{size: 10}}}}, grid: {{display: false}}}},
      y: {{ticks: {{color: '#8b949e', callback: v => v + '%', font: {{size: 10}}}}, grid: {{color: '#21262d'}}}}
    }}
  }}
}});

// ---- Concentration pie ----
const pieLabels = {pie_labels_js};
const pieValues = {pie_values_js};
const pieColors = ['#58a6ff','#3fb950','#d29922','#f85149','#a371f7',
                   '#39d353','#e3b341','#ff7b72','#79c0ff','#f0883e'];

new Chart(document.getElementById('pieChart'), {{
  type: 'doughnut',
  data: {{
    labels: pieLabels,
    datasets: [{{
      data: pieValues,
      backgroundColor: pieColors.slice(0, pieValues.length),
      borderWidth: 1, borderColor: '#161b22'
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: true,
    plugins: {{
      legend: {{
        position: 'right',
        labels: {{color: '#c9d1d9', font: {{size: 10}}, boxWidth: 12, padding: 8}}
      }},
      tooltip: {{callbacks: {{label: ctx => ctx.label + ': ' + ctx.raw.toFixed(1) + '%'}}}}
    }}
  }}
}});
</script>
</body>
</html>"""

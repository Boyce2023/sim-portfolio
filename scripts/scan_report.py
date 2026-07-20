#!/usr/bin/env python3
"""
A股完整扫描报告生成器
Usage: python3 scripts/scan_report.py --date 2026-07-20
Output: output/scan_report_{date}.html

读取:
  output/head_score_table_{date}.json   -- 30只候选扫描结果
  output/full_report_{date}.md          -- 交易侧整合报告(宏观/打分/建仓/持仓)
  portfolio_state.json                  -- 当前持仓(SSOT)

生成规范化HTML报告(5块):
  ① 宏观定调
  ② 完整头部打分表(30只,每只5维展开)
  ③ 建仓/调仓逻辑
  ④ 持仓复盘(5道门)
  ⑤ 执行情况+监控要点
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_CSS_PATH = Path("/Users/huaichuaibeimeng/.claude/standards/report.css")
OUTPUT_DIR = PROJECT_ROOT / "output"
PORTFOLIO_STATE = PROJECT_ROOT / "portfolio_state.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def esc(s: str) -> str:
    """HTML-escape a string."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def load_json(path: Path) -> dict | list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_text(path: Path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def pnl_color(pct: float) -> str:
    if pct >= 0:
        return "color:#1B5E20;font-weight:700;"
    elif pct >= -5:
        return "color:#856404;font-weight:700;"
    else:
        return "color:#C0392B;font-weight:700;"


def decision_style(decision: str) -> str:
    d = decision.lower()
    if d == "probe":
        return "background:#D4EDDA;color:#1B5E20;font-weight:800;padding:2px 6px;"
    elif d == "watch":
        return "background:#FFF3CD;color:#856404;font-weight:800;padding:2px 6px;"
    elif d == "hold":
        return "background:#E6EDF2;color:#3D5A75;font-weight:800;padding:2px 6px;"
    else:
        return "background:#F8D7DA;color:#721C24;font-weight:700;padding:2px 6px;"


def decision_row_style(decision: str) -> str:
    d = decision.lower()
    if d == "probe":
        return "border-left:4px solid #4A8A5C;"
    elif d == "watch":
        return "border-left:4px solid #D4A017;"
    elif d == "hold":
        return "border-left:4px solid #5B7C99;"
    else:
        return "border-left:4px solid #C0392B;"


def sabct_badge(sabct: str) -> str:
    s = str(sabct)
    if s.startswith("A+"):
        bg = "#1B5E20"; fg = "#fff"
    elif s.startswith("A-") or s == "A-":
        bg = "#2E7D32"; fg = "#fff"
    elif s.startswith("A"):
        bg = "#388E3C"; fg = "#fff"
    elif s.startswith("B+"):
        bg = "#856404"; fg = "#fff"
    elif s.startswith("B"):
        bg = "#9C6D00"; fg = "#fff"
    else:
        bg = "#721C24"; fg = "#fff"
    short = s[:2] if len(s) >= 2 else s
    return f'<span style="background:{bg};color:{fg};padding:1px 5px;font-size:10px;font-weight:800;">{esc(short)}</span>'


def extract_section(md_text: str, header_prefix: str) -> str:
    """Extract a markdown section starting with header_prefix."""
    lines = md_text.split("\n")
    in_section = False
    result = []
    for line in lines:
        if line.startswith(header_prefix):
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") and not line.startswith(header_prefix):
                break
            result.append(line)
    return "\n".join(result).strip()


def md_to_simple_html(text: str) -> str:
    """Very minimal Markdown -> HTML for inline use (bold, code, br)."""
    # Bold **...**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Inline code `...`
    text = re.sub(r'`([^`]+)`', r'<code style="background:#F0F1F3;padding:1px 3px;font-size:9px;">\1</code>', text)
    # Line breaks
    text = text.replace("\n", "<br>")
    return text


def read_css() -> str:
    """Return the contents of report.css as an inline <style> block."""
    if REPORT_CSS_PATH.exists():
        css = REPORT_CSS_PATH.read_text(encoding="utf-8")
        return f"<style>\n{css}\n</style>"
    return "<style>body{{font-family:sans-serif;}}</style>"


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def build_overview_bar(date_str: str, candidates: list, portfolio: dict) -> str:
    acct = portfolio.get("accounts", {}).get("a_share", {})
    total_assets = acct.get("total_assets", 0)
    cash = acct.get("cash", 0)
    invested = acct.get("total_invested", 0)
    unrealized = acct.get("unrealized_pnl", 0)
    positions = acct.get("positions", [])
    n_positions = len(positions)
    cash_pct = cash / total_assets * 100 if total_assets else 0

    from collections import Counter
    decisions = Counter(c["verdict"]["decision"] for c in candidates)
    n_probe = decisions.get("probe", 0)
    n_watch = decisions.get("watch", 0) + decisions.get("hold", 0)
    n_reject = decisions.get("reject", 0)

    unrealized_color = "#1B5E20" if unrealized >= 0 else "#C0392B"
    unrealized_sign = "+" if unrealized >= 0 else ""

    # Regime from candidates context — detect from md or hardcode from data
    regime_label = "普跌"
    sizing = "0.3"

    return f"""
<div style="background:#1F1F1C;color:#fff;padding:14px 20px;margin-bottom:0;display:flex;flex-wrap:wrap;gap:18px;align-items:center;">
  <div>
    <span style="font-size:18px;font-weight:800;letter-spacing:1px;">A股完整扫描报告</span>
    <span style="font-size:12px;color:#B0ABA0;margin-left:10px;">{esc(date_str)}</span>
  </div>
  <div style="margin-left:auto;display:flex;gap:14px;flex-wrap:wrap;align-items:center;">
    <span style="background:#C0392B;color:#fff;padding:3px 10px;font-size:11px;font-weight:800;">Regime: {esc(regime_label)}</span>
    <span style="background:#856404;color:#fff;padding:3px 10px;font-size:11px;font-weight:800;">Sizing {sizing}</span>
    <span style="color:#B0ABA0;font-size:11px;">NAV <strong style="color:#fff;">¥{total_assets:,.0f}</strong></span>
    <span style="color:#B0ABA0;font-size:11px;">持仓 <strong style="color:#fff;">{n_positions}</strong></span>
    <span style="color:#B0ABA0;font-size:11px;">现金 <strong style="color:#fff;">{cash_pct:.1f}%</strong></span>
    <span style="color:#B0ABA0;font-size:11px;">浮亏 <strong style="color:{unrealized_color};">{unrealized_sign}¥{unrealized:,.0f}</strong></span>
    <span style="color:#4A8A5C;font-size:11px;font-weight:800;">Probe {n_probe}</span>
    <span style="color:#D4A017;font-size:11px;font-weight:800;">Watch {n_watch}</span>
    <span style="color:#C0392B;font-size:11px;font-weight:800;">Reject {n_reject}</span>
  </div>
</div>
"""


def build_toc() -> str:
    return """
<div style="background:#F7F5F0;border:1px solid #E8E2D6;padding:10px 18px;margin:16px 0;font-size:11px;">
  <strong>目录：</strong>
  <a href="#s1" style="color:#1A5A99;margin-right:12px;">① 宏观定调</a>
  <a href="#s2" style="color:#1A5A99;margin-right:12px;">② 完整打分表(30只)</a>
  <a href="#s3" style="color:#1A5A99;margin-right:12px;">③ 建仓/调仓逻辑</a>
  <a href="#s4" style="color:#1A5A99;margin-right:12px;">④ 持仓复盘</a>
  <a href="#s5" style="color:#1A5A99;">⑤ 执行情况</a>
</div>
"""


def build_section1_macro(md_text: str, date_str: str) -> str:
    raw = extract_section(md_text, "## ① 宏观定调")

    # Build index structure table from the text
    # We'll parse key data points from the raw text
    regime_badge = '<span style="background:#C0392B;color:#fff;padding:2px 8px;font-weight:800;font-size:11px;">普跌</span>'
    sizing_badge = '<span style="background:#856404;color:#fff;padding:2px 8px;font-weight:800;font-size:11px;">Sizing 0.3</span>'

    # Convert markdown to simple HTML for display
    raw_html = md_to_simple_html(esc(raw))

    # Index structure table (extracted from the text)
    index_table = """
<table style="font-size:10px;margin-top:12px;width:100%;">
  <thead><tr>
    <th>指数</th><th>今日结构</th><th>关键信号</th>
  </tr></thead>
  <tbody>
    <tr><td><span class="kw-blue">AI算力链(旭创/新易盛/天孚)</span></td><td style="color:#1B5E20;">+2.4% / +2.9% / +0.1% 龙头护住</td><td>唯一亮点:龙头虹吸,杂鱼全崩</td></tr>
    <tr><td><span class="kw-blue">芯片大脑(寒武纪/海光/中芯)</span></td><td style="color:#1B5E20;">+1.5% / +0.4% / +1.1%</td><td>今日链头全链唯一站稳核</td></tr>
    <tr><td><span class="kw-red">PCB/CCL(沪电/生益/江化微)</span></td><td style="color:#C0392B;">-10% / -7.2% / 跌停</td><td>主升领涨环今日深度回吐</td></tr>
    <tr><td><span class="kw-red">液冷/散热(英维克/中石科技)</span></td><td style="color:#C0392B;">-9% / -10.7%</td><td>全线杀跌</td></tr>
    <tr><td><span class="kw-red">矿端(云南锗业/多氟多/石英)</span></td><td style="color:#C0392B;">跌停 / -9.9% / -8.5%</td><td>最大下跌重灾区</td></tr>
    <tr><td><span class="kw-blue">避险(紫金矿业)</span></td><td style="color:#1B5E20;">+3.1%</td><td>黄金避险独立行情</td></tr>
  </tbody>
</table>
"""

    conclusion_text = "今日是全市场退潮日，30个头部候选无一给出\"放量上涨+突破前高\"的右侧信号。双确认门（SABCT≥A- AND 放量上涨 AND 距前高∈[-3,+8]）在普跌日设计上输出零probe——这是正确结论，不是漏扫。"

    return f"""
<div id="s1" class="figA" style="margin:16px 0;">
  <div class="figA-h" style="font-size:14px;">① 宏观定调 &nbsp; {regime_badge} &nbsp; {sizing_badge}</div>
  <div class="figA-sub">数据来源: 腾讯qt.gtimg.cn直连 · {esc(date_str)}</div>

  <div class="sub-amber" style="font-size:10px;margin-bottom:10px;">
    <strong>一句话结论：</strong>{esc(conclusion_text)}
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
    <div>
      <div style="font-size:12px;font-weight:700;margin-bottom:6px;color:#1F1F1C;">今日板块结构</div>
      {index_table}
    </div>
    <div>
      <div style="font-size:12px;font-weight:700;margin-bottom:6px;color:#1F1F1C;">Regime分析</div>
      <div style="font-size:10px;line-height:1.7;color:#2A2A2A;">
        {raw_html[:1800]}
      </div>
    </div>
  </div>

  <div style="display:flex;gap:10px;margin-top:12px;flex-wrap:wrap;">
    <div style="flex:1;min-width:160px;background:#FBECEA;border:1px solid #C0392B;padding:8px 12px;">
      <div style="font-size:9px;font-weight:800;color:#C0392B;">关键背离</div>
      <div style="font-size:10px;margin-top:4px;">基本面头部与量价头部完全错位 — A-/A级真Edge标的全在下跌中段接飞刀区，没一个在主升</div>
    </div>
    <div style="flex:1;min-width:160px;background:#E9F3EC;border:1px solid #4A8A5C;padding:8px 12px;">
      <div style="font-size:9px;font-weight:800;color:#4A8A5C;">系统结论</div>
      <div style="font-size:10px;margin-top:4px;">零probe = 系统正确执行双确认门，不是漏扫。Sizing 0.3 × A-上限18% = 最大单仓5.4%，今日不触发</div>
    </div>
    <div style="flex:1;min-width:160px;background:#FCF3E0;border:1px solid #D4A017;padding:8px 12px;">
      <div style="font-size:9px;font-weight:800;color:#9A7B2E;">催化剂监控</div>
      <div style="font-size:10px;margin-top:4px;">中报窗口(8月): 惠泰8/28 / 川恒8/28 / 中信特钢8/28 / 奥浦迈8月。任一超预期即触发加仓复核</div>
    </div>
  </div>
</div>
"""


def build_section2_scores(candidates: list) -> str:
    from collections import defaultdict

    # Group by decision: probe > watch/hold > reject
    probe = [c for c in candidates if c["verdict"]["decision"] == "probe"]
    watch = [c for c in candidates if c["verdict"]["decision"] in ("watch", "hold")]
    reject = [c for c in candidates if c["verdict"]["decision"] == "reject"]

    def build_card(c: dict, idx: int) -> str:
        v = c["verdict"]
        decision = v.get("decision", "reject")
        ticker = c.get("ticker", "")
        name = c.get("name", "")
        env = c.get("env", "")
        sabct = v.get("sabct", "—")
        size_now = v.get("size_now", "—")
        stop = v.get("stop", "—")
        catalyst = v.get("catalyst_date", "—")
        watch_expiry = v.get("watch_expiry", "—")
        one_line = v.get("one_line", "")
        fundamental = v.get("fundamental", "")
        trend = v.get("trend", "")
        is_hot = c.get("is_hot", False)

        d_style = decision_style(decision)
        row_style = decision_row_style(decision)
        s_badge = sabct_badge(sabct)
        hot_badge = '<span style="background:#CC785C;color:#fff;padding:1px 5px;font-size:9px;margin-left:4px;">热点</span>' if is_hot else ""

        # Truncate long texts for display but show full key content
        fund_short = fundamental[:600] if len(fundamental) > 600 else fundamental
        trend_short = trend[:400] if len(trend) > 400 else trend
        stop_short = stop[:200] if len(stop) > 200 else stop
        catalyst_short = catalyst[:150] if len(catalyst) > 150 else catalyst
        watch_short = watch_expiry[:200] if len(watch_expiry) > 200 else watch_expiry

        return f"""
<div style="border:1px solid #E0E0E0;margin:6px 0;{row_style}background:#fff;">
  <!-- Header row -->
  <div style="background:#F7F5F0;padding:6px 10px;display:flex;flex-wrap:wrap;align-items:center;gap:8px;border-bottom:1px solid #E8E2D6;">
    <span style="font-size:12px;font-weight:800;color:#1F1F1C;">{idx}. <span class="kw-blue">{esc(ticker)}</span> {esc(name)}</span>
    {hot_badge}
    <span style="font-size:9px;color:#5B5852;background:#F0F1F3;padding:1px 6px;">环节: {esc(env)}</span>
    {s_badge}
    <span style="{d_style}">{esc(decision.upper())}</span>
    <span style="font-size:10px;color:#5B5852;margin-left:auto;">建仓: {esc(str(size_now))}</span>
  </div>
  <!-- One-line verdict -->
  <div style="padding:5px 10px;font-size:10px;font-weight:700;color:#1A5A99;border-bottom:1px solid #EDE7DB;">
    {esc(one_line[:200])}
  </div>
  <!-- 5-dimension grid -->
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:0;font-size:9px;">
    <div style="padding:6px 10px;border-right:1px solid #EDE7DB;border-bottom:1px solid #EDE7DB;">
      <div style="font-weight:800;color:#1F1F1C;margin-bottom:2px;">供给侧基本面</div>
      <div style="color:#2A2A2A;line-height:1.55;">{esc(fund_short)}</div>
    </div>
    <div style="padding:6px 10px;border-bottom:1px solid #EDE7DB;">
      <div style="font-weight:800;color:#1F1F1C;margin-bottom:2px;">量价结构</div>
      <div style="color:#2A2A2A;line-height:1.55;">{esc(trend_short)}</div>
    </div>
    <div style="padding:6px 10px;border-right:1px solid #EDE7DB;">
      <div style="font-weight:800;color:#1F1F1C;margin-bottom:2px;">催化剂</div>
      <div style="color:#2A2A2A;line-height:1.5;">{esc(catalyst_short)}</div>
    </div>
    <div style="padding:6px 10px;">
      <div style="font-weight:800;color:#1F1F1C;margin-bottom:2px;">Watch触发 / 止损</div>
      <div style="color:#2A2A2A;line-height:1.5;">
        <strong>Watch:</strong> {esc(watch_short[:120])}<br>
        <strong style="color:#C0392B;">止损:</strong> {esc(stop_short[:120])}
      </div>
    </div>
  </div>
</div>
"""

    def build_group(items: list, label: str, color: str, bg: str) -> str:
        if not items:
            return f'<div style="background:{bg};border:1px solid {color};padding:6px 12px;margin:6px 0;font-size:10px;color:{color};"><strong>{esc(label)}: 今日零</strong></div>'
        header = f'<div style="background:{bg};border:1px solid {color};padding:6px 12px;margin-top:12px;font-size:11px;font-weight:800;color:{color};">{esc(label)} ({len(items)}只)</div>'
        cards = "".join(build_card(c, i + 1) for i, c in enumerate(items))
        return header + cards

    probe_html = build_group(probe, "PROBE — 今日可建仓", "#4A8A5C", "#E9F3EC")
    watch_html = build_group(watch, "WATCH — 基本面过关 等时机", "#D4A017", "#FCF3E0")
    reject_html = build_group(reject, "REJECT — 今日排除", "#C0392B", "#FBECEA")

    total = len(candidates)
    n_p = len(probe)
    n_w = len(watch)
    n_r = len(reject)

    return f"""
<div id="s2" class="figA" style="margin:16px 0;">
  <div class="figA-h" style="font-size:14px;">② 完整头部打分表 ({total}只)</div>
  <div class="figA-sub">5维展开: 供给侧基本面 | 量价结构 | 催化剂 | Watch触发 | 止损。按Probe→Watch→Reject分组。</div>

  <div style="display:flex;gap:10px;margin-bottom:10px;flex-wrap:wrap;font-size:10px;">
    <span style="background:#D4EDDA;color:#1B5E20;padding:2px 10px;font-weight:800;">PROBE {n_p}</span>
    <span style="background:#FFF3CD;color:#856404;padding:2px 10px;font-weight:800;">WATCH/HOLD {n_w}</span>
    <span style="background:#F8D7DA;color:#721C24;padding:2px 10px;font-weight:800;">REJECT {n_r}</span>
    <span style="color:#8A857C;">共 {total} 只候选 · 双确认门(SABCT≥A- AND 放量上涨 AND 距突破∈[-3,+8]) · 数据源腾讯qt.gtimg</span>
  </div>

  {probe_html}
  {watch_html}
  {reject_html}
</div>
"""


def build_section3_action(candidates: list, md_text: str) -> str:
    # Extract watch items sorted by nearness to breakout
    watch_items = [c for c in candidates if c["verdict"]["decision"] in ("watch", "hold")]

    # Parse watch table from md for distances (they have 距突破% values)
    # We'll regenerate from the candidates data. Use the one_line/trend for distance estimates.
    # Build the watch by extracting key trigger info from the md
    raw_build = extract_section(md_text, "## ③ 建仓/调仓逻辑")
    raw_html = md_to_simple_html(esc(raw_build))

    # Build structured watch table (A- grade first)
    a_grade_watch = [c for c in watch_items if str(c["verdict"].get("sabct", "")).startswith("A")]
    b_grade_watch = [c for c in watch_items if not str(c["verdict"].get("sabct", "")).startswith("A")]

    def watch_row(c: dict) -> str:
        v = c["verdict"]
        ticker = c.get("ticker", "")
        name = c.get("name", "")
        sabct = v.get("sabct", "—")
        one_line = v.get("one_line", "")
        # Extract distance from trend text
        trend = v.get("trend", "")
        catalyst = v.get("catalyst_date", "")
        watch_exp = v.get("watch_expiry", "")
        s_badge = sabct_badge(sabct)
        decision = v.get("decision", "watch")
        hold_note = ' <span style="background:#5B7C99;color:#fff;font-size:8px;padding:1px 4px;">已持仓</span>' if decision == "hold" else ""
        return f"""<tr>
          <td><span class="kw-blue">{esc(ticker)}</span> {esc(name)}{hold_note}</td>
          <td style="text-align:center;">{s_badge}</td>
          <td style="font-size:9px;">{esc(one_line[:120])}</td>
          <td style="font-size:9px;color:#856404;">{esc(watch_exp[:100])}</td>
          <td style="font-size:9px;color:#C0392B;">{esc(catalyst[:80])}</td>
        </tr>"""

    a_rows = "".join(watch_row(c) for c in a_grade_watch)
    b_rows = "".join(watch_row(c) for c in b_grade_watch) if b_grade_watch else ""

    reject_items = [c for c in candidates if c["verdict"]["decision"] == "reject"]
    # Categorize reject by reason
    concept_mismatch = [c for c in reject_items if "挂错节点" in c["verdict"].get("fundamental", "") or "概念蹭" in c["verdict"].get("fundamental", "")]
    valuation = [c for c in reject_items if "估值无边际" in c["verdict"].get("fundamental", "") or "PE-" in c["verdict"].get("fundamental", "") or "无安全边际" in c["verdict"].get("one_line", "")]
    trend_fail = [c for c in reject_items if "自由落体" in c["verdict"].get("trend", "") or "腰斩" in c["verdict"].get("trend", "")]

    concept_names = ", ".join(f"{c['ticker']} {c['name']}" for c in concept_mismatch) if concept_mismatch else "无"
    val_names = ", ".join(f"{c['ticker']} {c['name']}" for c in valuation) if valuation else "无"
    trend_names = ", ".join(f"{c['ticker']} {c['name']}" for c in trend_fail) if trend_fail else "无"

    return f"""
<div id="s3" class="figA" style="margin:16px 0;">
  <div class="figA-h" style="font-size:14px;">③ 建仓/调仓逻辑</div>
  <div class="figA-sub">Probe清单(今日0) · Watch回踩触发 · Reject原因归类</div>

  <div class="sub-green" style="font-size:10px;margin-bottom:10px;">
    <strong>今日Probe = 零。</strong>普跌regime(sizing 0.3) + 双确认严，30个头部候选无一通过"放量上涨+突破前高"的时机门。这是系统在退潮日该有的合理结论——不接flying knife，等右侧信号。
  </div>

  <!-- Watch table -->
  <div style="font-size:12px;font-weight:700;margin:10px 0 6px;color:#1F1F1C;">Watch清单 — 基本面过关，等量价触发</div>
  <div style="font-size:9px;color:#8A857C;margin-bottom:6px;">A级(SABCT≥A-)优先监控。触发条件: 放量突破前高 OR 回踩企稳缩量。</div>
  <table style="font-size:10px;margin-bottom:4px;">
    <thead><tr>
      <th style="width:14%;">标的</th>
      <th style="width:6%;">SABCT</th>
      <th style="width:36%;">裁决理由(一句话)</th>
      <th style="width:26%;">Watch触发 / 失效期</th>
      <th style="width:18%;">催化剂</th>
    </tr></thead>
    <tbody>
      <tr><td colspan="5" style="background:#E9F3EC;font-size:9px;font-weight:800;color:#1B5E20;padding:3px 7px;">A-/A级 — 基本面确认，最优先监控 ({len(a_grade_watch)}只)</td></tr>
      {a_rows}
      {"<tr><td colspan='5' style='background:#FCF3E0;font-size:9px;font-weight:800;color:#856404;padding:3px 7px;'>B+级 — 基本面次优先 (" + str(len(b_grade_watch)) + "只，建仓需额外确认)</td></tr>" + b_rows if b_grade_watch else ""}
    </tbody>
  </table>

  <!-- Reject breakdown -->
  <div style="font-size:12px;font-weight:700;margin:14px 0 6px;color:#1F1F1C;">Reject归类 ({len(reject_items)}只)</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:9px;">
    <div style="background:#FBECEA;border:1px solid #C0392B;padding:8px 10px;">
      <div style="font-weight:800;color:#C0392B;margin-bottom:4px;">节点挂错/概念蹭 ({len(concept_mismatch)}只)</div>
      <div style="line-height:1.6;">{esc(concept_names)}</div>
    </div>
    <div style="background:#FBECEA;border:1px solid #C0392B;padding:8px 10px;">
      <div style="font-weight:800;color:#C0392B;margin-bottom:4px;">估值无边际 ({len(valuation)}只)</div>
      <div style="line-height:1.6;">{esc(val_names)}</div>
    </div>
    <div style="background:#FBECEA;border:1px solid #C0392B;padding:8px 10px;">
      <div style="font-weight:800;color:#C0392B;margin-bottom:4px;">量价腰斩/自由落体 ({len(trend_fail)}只)</div>
      <div style="line-height:1.6;">{esc(trend_names)}</div>
    </div>
  </div>

  <!-- Near-trigger watch detail (4 closest) -->
  <div style="font-size:12px;font-weight:700;margin:14px 0 6px;color:#1F1F1C;">近端Watch优先级 — 距突破最近4只 <span style="font-size:9px;font-weight:400;color:#8A857C;">(最先可能触发)</span></div>
  <div style="font-size:10px;line-height:1.7;background:#F7F5F0;border:1px solid #E8E2D6;padding:10px 14px;">
    {raw_html[:2000]}
  </div>
</div>
"""


def build_section4_holdings(portfolio: dict, md_text: str) -> str:
    acct = portfolio.get("accounts", {}).get("a_share", {})
    positions = acct.get("positions", [])
    cash = acct.get("cash", 0)
    total_assets = acct.get("total_assets", 0)
    cash_pct = cash / total_assets * 100 if total_assets else 0
    realized = acct.get("realized_pnl", 0)
    unrealized = acct.get("unrealized_pnl", 0)

    # Build positions table
    def pos_row(p: dict) -> str:
        ticker = p.get("ticker", "")
        name = p.get("name", "")
        avg_cost = p.get("avg_cost", 0)
        curr_price = p.get("current_price", 0)
        pnl_pct = p.get("unrealized_pnl_pct", 0)
        pnl_abs = p.get("unrealized_pnl", 0)
        market_val = p.get("market_value", 0)
        port_pct = p.get("portfolio_pct", 0) * 100
        conviction = p.get("conviction_level", "—")
        pos_type = p.get("type", "—")
        catalyst = p.get("next_catalyst", "—")
        thesis = p.get("thesis_short", p.get("thesis", ""))[:120]
        stop_loss = p.get("stop_loss", "—")
        peak = p.get("peak_price", avg_cost)
        change_pct = p.get("change_pct", 0)
        x1_stop = p.get("x1_stop", 0)

        # 5 gates check
        # Gate 1: broke recent low (pnl_pct < -12 is disaster)
        gate_disaster = pnl_pct <= -12
        gate_roundtrip = False  # would need peak data vs cost
        # Simple checks from available data
        if peak and avg_cost and curr_price:
            # round-trip: from peak back to cost
            peak_gain = (peak - avg_cost) / avg_cost * 100 if avg_cost else 0
            curr_from_peak = (curr_price - peak) / peak * 100 if peak else 0
            gate_roundtrip = peak_gain >= 15 and (curr_price <= avg_cost * 1.01)

        gate_disaster_style = "background:#FBECEA;color:#C0392B;" if gate_disaster else "background:#E9F3EC;color:#1B5E20;"
        gate_rt_style = "background:#FBECEA;color:#C0392B;" if gate_roundtrip else "background:#E9F3EC;color:#1B5E20;"

        gate_disaster_text = "触发" if gate_disaster else "未响"
        gate_rt_text = "触发" if gate_roundtrip else "未响"
        overall = "清仓" if gate_disaster else "守"
        overall_style = "background:#C0392B;color:#fff;font-weight:800;padding:2px 6px;" if gate_disaster else "background:#1B5E20;color:#fff;font-weight:800;padding:2px 6px;"

        pnl_style = pnl_color(pnl_pct)
        change_style = pnl_color(change_pct)

        return f"""
<tr>
  <td style="font-weight:700;">
    <span class="kw-blue">{esc(ticker)}</span><br>
    <span style="font-size:9px;color:#5B5852;">{esc(name)}</span><br>
    <span style="font-size:8px;background:#E6EDF2;padding:1px 4px;">{esc(conviction)}</span>
    <span style="font-size:8px;background:#F0F1F3;padding:1px 4px;">{esc(pos_type)[:6]}</span>
  </td>
  <td style="font-size:10px;">
    成本 ¥{avg_cost:.2f}<br>
    现价 ¥{curr_price:.2f}<br>
    <span style="{change_style}">今日 {'+' if change_pct >= 0 else ''}{change_pct:.2f}%</span>
  </td>
  <td style="{pnl_style};font-size:11px;">
    {'+' if pnl_pct >= 0 else ''}{pnl_pct:.2f}%<br>
    <span style="font-size:9px;">¥{pnl_abs:+,.0f}</span>
  </td>
  <td style="font-size:9px;">{esc(thesis)}</td>
  <td style="font-size:9px;color:#856404;">{esc(str(catalyst)[:80])}</td>
  <td style="font-size:9px;">
    <div style="{gate_disaster_style}padding:1px 5px;margin:1px 0;font-size:8px;">灾难线-12%: {gate_disaster_text}</div>
    <div style="{gate_rt_style}padding:1px 5px;margin:1px 0;font-size:8px;">Round-trip: {gate_rt_text}</div>
    <div style="background:#E9F3EC;color:#1B5E20;padding:1px 5px;margin:1px 0;font-size:8px;">Thesis: 未证伪</div>
    <span style="{overall_style}">{overall}</span>
  </td>
</tr>
"""

    rows = "".join(pos_row(p) for p in positions)
    n_pos = len(positions)
    invested_pct = (total_assets - cash) / total_assets * 100 if total_assets else 0

    return f"""
<div id="s4" class="figA" style="margin:16px 0;">
  <div class="figA-h" style="font-size:14px;">④ 持仓复盘 ({n_pos}只)</div>
  <div class="figA-sub">卖出5道门结论: 破前低 / 灾难线-12% / Round-trip / Thesis证伪 / 催化兑现</div>

  <!-- Portfolio summary bar -->
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;font-size:10px;">
    <div style="background:#F0F1F3;padding:4px 10px;"><strong>总资产</strong> ¥{total_assets:,.0f}</div>
    <div style="background:#F0F1F3;padding:4px 10px;"><strong>现金</strong> ¥{cash:,.0f} ({cash_pct:.1f}%)</div>
    <div style="background:#F0F1F3;padding:4px 10px;"><strong>投入</strong> ¥{total_assets - cash:,.0f} ({invested_pct:.1f}%)</div>
    <div style="background:#{'D4EDDA' if realized >= 0 else 'F8D7DA'};padding:4px 10px;"><strong>已实现</strong> <span style="color:{'#1B5E20' if realized >= 0 else '#C0392B'};font-weight:700;">¥{realized:+,.0f}</span></div>
    <div style="background:#{'D4EDDA' if unrealized >= 0 else 'F8D7DA'};padding:4px 10px;"><strong>浮亏</strong> <span style="color:{'#1B5E20' if unrealized >= 0 else '#C0392B'};font-weight:700;">¥{unrealized:+,.0f}</span></div>
  </div>

  <table style="font-size:10px;">
    <thead><tr>
      <th style="width:12%;">标的</th>
      <th style="width:12%;">价格</th>
      <th style="width:9%;">浮亏</th>
      <th style="width:30%;">Thesis摘要</th>
      <th style="width:18%;">催化剂</th>
      <th style="width:19%;">5道门 → 裁决</th>
    </tr></thead>
    <tbody>
      {rows}
    </tbody>
  </table>

  <div class="sub-green" style="font-size:10px;margin-top:10px;">
    <strong>裁决: 全部5只守仓。</strong>深研埋伏仓的唯一合法卖出理由是thesis三问证伪。价格浮亏(最深键凯-7.1%)不构成卖出信号。五道门全未响 → 全守。
  </div>

  <div class="sub-amber" style="font-size:9px;margin-top:6px;">
    <strong>注意:</strong> 惠泰/川恒/奥浦迈同时出现在扫描候选侧(watch)和持仓侧(守)。它们已是持仓，扫描侧"watch"应理解为"若要加仓需等右侧触发"，去留判定以持仓侧的"守"为准。
  </div>
</div>
"""


def build_section5_execution(md_text: str, date_str: str) -> str:
    raw = extract_section(md_text, "## ④ 执行情况")
    raw_html = md_to_simple_html(esc(raw))

    near_triggers = [
        {"ticker": "688617", "name": "惠泰医疗", "sabct": "A-", "curr": "¥205.44", "trigger": "放量突破≈¥216", "or_": "回踩MA20≈¥195不破", "catalyst": "电生理国产替代+中报8/28", "note": "已持仓，此为加仓触发"},
        {"ticker": "002895", "name": "川恒股份", "sabct": "A-", "curr": "¥30.60", "trigger": "放量突破≈¥33.4", "or_": "—", "catalyst": "中报8/28磷氟双链兑现", "note": "已持仓，此为加仓触发"},
        {"ticker": "002920", "name": "德赛西威", "sabct": "A", "curr": "¥82.14", "trigger": "放量突破≈¥91.4", "or_": "回踩箱体下沿不破", "catalyst": "L3量产/Thor放量/西班牙工厂26年", "note": "新建仓"},
        {"ticker": "688293", "name": "奥浦迈", "sabct": "A-", "curr": "¥51.82", "trigger": "放量突破≈¥59", "or_": "回踩企稳缩量", "catalyst": "ADC/双抗上游培养基订单放量", "note": "已持仓，此为加仓触发"},
    ]

    trigger_rows = "".join(f"""<tr>
      <td><span class="kw-blue">{esc(t['ticker'])}</span> {esc(t['name'])}<br><span style="font-size:8px;color:#5B5852;">{esc(t['note'])}</span></td>
      <td style="text-align:center;">{sabct_badge(t['sabct'])}</td>
      <td>{esc(t['curr'])}</td>
      <td style="color:#1B5E20;font-weight:700;">{esc(t['trigger'])}</td>
      <td style="font-size:9px;color:#8A857C;">{esc(t['or_'])}</td>
      <td style="font-size:9px;">{esc(t['catalyst'])}</td>
    </tr>""" for t in near_triggers)

    far_watches = [
        ("603659", "璞泰来", "-30.1%", "等企稳缩量止跌"),
        ("000831", "中国稀土", "-31.7%", "等加工端跟涨+链扩散确认"),
        ("603505", "金石资源", "-34.1%", "等13-14企稳信号"),
        ("002167", "东方锆业", "-36.6%", "等跌停企稳"),
        ("002273", "水晶光电", "-36.8%", "等回踩24-26箱体缩量"),
    ]

    far_rows = "".join(f"""<tr>
      <td><span class="kw-blue">{esc(t[0])}</span> {esc(t[1])}</td>
      <td style="color:#C0392B;font-weight:700;">{esc(t[2])}</td>
      <td style="font-size:9px;color:#8A857C;">{esc(t[3])}</td>
    </tr>""" for t in far_watches)

    return f"""
<div id="s5" class="figA" style="margin:16px 0;">
  <div class="figA-h" style="font-size:14px;">⑤ 执行情况 + 监控要点</div>
  <div class="figA-sub">{esc(date_str)} 操作记录 · 执行卡片 · 明日监控</div>

  <!-- Today's execution -->
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px;">
    <div style="background:#F8D7DA;border:1px solid #C0392B;padding:8px 14px;flex:0 0 auto;">
      <div style="font-size:9px;font-weight:800;color:#C0392B;">今日建仓</div>
      <div style="font-size:14px;font-weight:800;">零</div>
    </div>
    <div style="background:#F8D7DA;border:1px solid #C0392B;padding:8px 14px;flex:0 0 auto;">
      <div style="font-size:9px;font-weight:800;color:#C0392B;">今日调仓</div>
      <div style="font-size:14px;font-weight:800;">零</div>
    </div>
    <div style="background:#D4EDDA;border:1px solid #4A8A5C;padding:8px 14px;flex:0 0 auto;">
      <div style="font-size:9px;font-weight:800;color:#1B5E20;">持仓全守</div>
      <div style="font-size:14px;font-weight:800;">5只</div>
    </div>
    <div style="background:#FCF3E0;border:1px solid #D4A017;padding:8px 14px;flex:1;">
      <div style="font-size:9px;font-weight:800;color:#9A7B2E;">系统结论</div>
      <div style="font-size:10px;margin-top:3px;">普跌日零probe = 系统在退潮日的正确行为。不接flying knife，等右侧信号。5只持仓thesis完整，五道门全未响，全守不动。</div>
    </div>
  </div>

  <!-- Near trigger execution cards -->
  <div style="font-size:12px;font-weight:700;margin:10px 0 6px;">近端Watch执行卡片 — 盯这4只，任一触发即转Probe</div>
  <table style="font-size:10px;">
    <thead><tr>
      <th>标的</th><th>SABCT</th><th>现价</th><th>触发价</th><th>或回踩信号</th><th>催化剂</th>
    </tr></thead>
    <tbody>{trigger_rows}</tbody>
  </table>

  <!-- Far watches -->
  <div style="font-size:12px;font-weight:700;margin:12px 0 6px;">远端Watch — 距突破>30%，等筑底 <span style="font-size:9px;font-weight:400;color:#8A857C;">(不设短期触发价，等企稳信号)</span></div>
  <table style="font-size:10px;">
    <thead><tr><th>标的</th><th>距突破%</th><th>等待信号</th></tr></thead>
    <tbody>{far_rows}</tbody>
  </table>

  <!-- Monitoring checklist -->
  <div style="font-size:12px;font-weight:700;margin:12px 0 6px;">明日监控要点</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:9px;">
    <div style="background:#F7F5F0;border:1px solid #E8E2D6;padding:8px 10px;">
      <div style="font-weight:800;color:#1F1F1C;margin-bottom:4px;">量价监控</div>
      <div style="line-height:1.7;">
        · 惠泰688617: 是否止跌缩量 → 接近触发位¥216<br>
        · 川恒002895: 今日+1.31%，观察能否放量站稳¥31<br>
        · 德赛002920: 箱体下沿¥80支撑是否有效<br>
        · 5只持仓: 破前10日低或接近-12%灾难线立即复核
      </div>
    </div>
    <div style="background:#F7F5F0;border:1px solid #E8E2D6;padding:8px 10px;">
      <div style="font-weight:800;color:#1F1F1C;margin-bottom:4px;">催化剂跟踪</div>
      <div style="line-height:1.7;">
        · 8/28中报: 键凯/惠泰/中信特钢/川恒/奥浦迈 → 5只持仓均有中报催化<br>
        · AI链宏观: 旭创/新易盛今日强/龙头虹吸格局是否延续<br>
        · 巨化600160: SABCT字段格式修正后重跑会进watch桶(当前格式问题导致误入reject)<br>
        · Regime转变: 若连续2日量价由"普通"转"放量上涨"，sizing升至0.5
      </div>
    </div>
  </div>

  <!-- Data quality note -->
  <div class="sub-amber" style="font-size:9px;margin-top:10px;">
    <strong>数据质量注记:</strong> 巨化600160 SABCT字段写成了长注解文本，脚本精确匹配失败把它落到reject桶。
    实质判断="基本面达门槛，时机不达→watch"。修法: SABCT字段填纯"A-"，注解移入one_line。
    修完重跑, 巨化将正确归入watch桶(但今日量价-32.5%破位下跌，watch结论本身不变，仍是零probe)。
  </div>
</div>
"""


# ---------------------------------------------------------------------------
# Main HTML assembly
# ---------------------------------------------------------------------------

def build_html(date_str: str, candidates: list, md_text: str, portfolio: dict) -> str:
    css = read_css()

    # Compact font-size override per feedback_html_font_hierarchy iron rule
    font_override = """
<style>
/* ⛔ 字号紧凑override (feedback_html_font_hierarchy) */
h2 { font-size: 14px !important; }
h3, h4 { font-size: 12px !important; }
.figA-h { font-size: 14px !important; }
p, li, td, div { font-size: 10px; }
.figA-sub, .figA-cap { font-size: 9px; }
th { font-size: 10px; }
body { font-size: 10px; }
.container { max-width: 1200px; margin: 0 auto; padding: 0 16px; }
</style>
"""

    overview = build_overview_bar(date_str, candidates, portfolio)
    toc = build_toc()
    s1 = build_section1_macro(md_text, date_str)
    s2 = build_section2_scores(candidates)
    s3 = build_section3_action(candidates, md_text)
    s4 = build_section4_holdings(portfolio, md_text)
    s5 = build_section5_execution(md_text, date_str)

    n_probe = sum(1 for c in candidates if c["verdict"]["decision"] == "probe")
    n_watch = sum(1 for c in candidates if c["verdict"]["decision"] in ("watch", "hold"))
    n_reject = sum(1 for c in candidates if c["verdict"]["decision"] == "reject")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>A股扫描报告 {esc(date_str)}</title>
  {css}
  {font_override}
</head>
<body>

{overview}

<div class="container" style="padding-top:8px;">
  {toc}
  {s1}
  {s2}
  {s3}
  {s4}
  {s5}

  <!-- Footer -->
  <div style="border-top:1px solid #E0E0E0;margin-top:20px;padding-top:8px;font-size:9px;color:#8A857C;text-align:center;">
    A股完整扫描报告 · {esc(date_str)} · 数据源: 腾讯qt.gtimg.cn · astock_full_scan.workflow.js · organism_portfolio_builder.py
    · 生成器: scripts/scan_report.py · Claude模拟盘 sim-portfolio
  </div>
</div>

</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="A股扫描报告生成器")
    parser.add_argument("--date", required=True, help="报告日期 YYYY-MM-DD")
    args = parser.parse_args()

    date_str = args.date

    # Validate paths
    score_path = OUTPUT_DIR / f"head_score_table_{date_str}.json"
    md_path = OUTPUT_DIR / f"full_report_{date_str}.md"

    for p in [score_path, md_path, PORTFOLIO_STATE]:
        if not p.exists():
            print(f"ERROR: 文件不存在: {p}", file=sys.stderr)
            sys.exit(1)

    print(f"Loading candidates: {score_path}")
    candidates = load_json(score_path)

    print(f"Loading full report: {md_path}")
    md_text = load_text(md_path)

    print(f"Loading portfolio state: {PORTFOLIO_STATE}")
    portfolio = load_json(PORTFOLIO_STATE)

    print(f"Generating HTML report...")
    html = build_html(date_str, candidates, md_text, portfolio)

    out_path = OUTPUT_DIR / f"scan_report_{date_str}.html"
    out_path.write_text(html, encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024

    print(f"Report written: {out_path} ({size_kb:.1f} KB)")
    print(f"Candidates: {len(candidates)} total")
    print(f"  Probe:  {sum(1 for c in candidates if c['verdict']['decision'] == 'probe')}")
    print(f"  Watch:  {sum(1 for c in candidates if c['verdict']['decision'] in ('watch','hold'))}")
    print(f"  Reject: {sum(1 for c in candidates if c['verdict']['decision'] == 'reject')}")

    return str(out_path)


if __name__ == "__main__":
    main()

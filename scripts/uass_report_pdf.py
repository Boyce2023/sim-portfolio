#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["weasyprint>=62"]
# ///
"""UASS v3.0 — PDF: 白底专业研报风格"""

from __future__ import annotations
import argparse, json, sys
from datetime import datetime
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCAN_JSON = REPO / "uass_scan_output.json"
PORTFOLIO_JSON = REPO / "portfolio_state.json"
OUTPUT_DIR = REPO / "reports"
STAGE_PRIORITY = {"启动(首日)": 1, "主升早": 2, "主升中": 3, "高潮/退潮风险": 5, "高潮分歧": 4, "退潮": 6}

def _e(v): return escape(str(v)) if v is not None else ""
def _f20(n):
    if n >= 80: return "吸气"
    if n >= 60: return "偏吸气"
    if n >= 40: return "中性"
    if n >= 20: return "偏呼气"
    return "呼气"

CSS = """
@page { size:A4 landscape; margin:12mm 14mm; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'PingFang SC','Microsoft YaHei','Helvetica Neue',sans-serif;
  color:#1a1a1a; font-size:9.5pt; line-height:1.4; }

.hdr { border-bottom:2px solid #111; padding-bottom:6px; margin-bottom:10px; }
.hdr h1 { font-size:14pt; font-weight:700; display:inline; }
.hdr .meta { float:right; font-size:8pt; color:#666; padding-top:4px; }

.pt { font-size:11pt; font-weight:700; margin:12px 0 5px; padding-bottom:3px;
  border-bottom:1.5px solid #333; }

.sec { font-size:8pt; color:#888; margin:8px 0 3px; padding-bottom:2px;
  border-bottom:1px solid #ddd; letter-spacing:0.04em; }

/* tables */
table { width:100%; border-collapse:collapse; font-size:8.5pt; margin-bottom:6px; }
th { text-align:left; font-weight:600; color:#555; padding:3px 5px;
  border-bottom:1.5px solid #ccc; font-size:7.5pt; }
td { padding:3px 5px; border-bottom:1px solid #eee; }
tr:last-child td { border-bottom:none; }

/* RED = actionable/buyable */
tr.buy { background:#fff5f5; }
tr.buy td { color:#cc0000; font-weight:600; }
.red { color:#cc0000; font-weight:600; }
.grn { color:#00802b; }
.gray { color:#999; }
.tk { font-family:'SF Mono','Menlo',monospace; font-size:8pt; }

/* mainline blocks */
.ml { margin-bottom:5px; page-break-inside:avoid; }
.ml-h { font-size:9pt; font-weight:700; margin-bottom:1px; }
.ml-h .stg { font-size:7.5pt; font-weight:400; padding:1px 4px; border-radius:2px; margin:0 3px; }
.stg-go { background:#e8f5e9; color:#2e7d32; }
.stg-mid { background:#fff8e1; color:#f57f17; }
.stg-bad { background:#ffebee; color:#c62828; }
.ml-sig { font-size:7pt; color:#888; margin-bottom:2px; }
.ml-note { font-size:7.5pt; color:#aaa; font-style:italic; }

/* hero box */
.hero { border:1.5px solid #cc0000; padding:6px 8px; margin-bottom:10px; }
.hero h3 { font-size:9pt; color:#cc0000; margin-bottom:4px; }

/* 2-col */
.cols { display:flex; gap:14px; }
.cols > div { flex:1; }

/* risk */
.risk-r td:first-child { color:#cc0000; font-weight:600; }

.foot { font-size:6.5pt; color:#bbb; text-align:center; margin-top:10px;
  padding-top:6px; border-top:1px solid #ddd; }
"""

def build_html(data):
    ms = data.get("market_summary", {})
    zt = ms.get("涨停数", 0); strong = ms.get("强势非涨停数", 0)
    nb = ms.get("北向净买_亿", 0) or 0
    date_str = data.get("scan_date", "")
    scored = data.get("trackb_scored", [])
    mainlines = data.get("d8_mainline_sorted", [])
    bigcap = data.get("bigcap_watch", [])
    sector_flow = data.get("sector_flow_top10", [])
    streaks_raw = data.get("d8_mainline_streaks", {}) or {}

    zt_by_sector = {}
    for s in scored:
        if s.get("涨停"):
            zt_by_sector.setdefault(s.get("行业", ""), []).append(s)

    # Identify all green picks (buyable)
    green_codes = set()
    for s in scored:
        if (s.get("数据源") == "push2delay" and not s.get("涨停") and not s.get("veto")
            and "HEALTHY" in s.get("D6_flags", []) and (s.get("D5分", 0) or 0) >= 5
            and 3.0 <= (s.get("涨跌幅", 0) or 0) <= 9.5):
            sec = s.get("行业", "")
            if any(m["sector"] == sec for m in mainlines):
                green_codes.add(s.get("代码", ""))

    h = [f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">'
         f'<title>UASS {_e(date_str)}</title><style>{CSS}</style></head><body>']

    # Header
    h.append(f'<div class="hdr"><h1>UASS v3.0 | {_e(date_str)}</h1>'
             f'<div class="meta">F20: {_f20(zt)} | 涨停 {zt} | 强势 {strong} | 北向 {nb:+.1f}亿 | {len(mainlines)}条主线</div></div>')

    # HERO: top picks in RED
    green_list = []
    for s in scored:
        if s.get("代码", "") in green_codes:
            sec = s.get("行业", "")
            ml = next((m for m in mainlines if m["sector"] == sec), None)
            if ml:
                s["_ml"] = ml["sector"]; s["_stage"] = ml.get("stage_auto", "")
                green_list.append(s)
    green_list.sort(key=lambda x: (STAGE_PRIORITY.get(x.get("_stage", ""), 99), -(x.get("TB总分", 0))))

    h.append('<div class="hero">')
    h.append(f'<h3>可建仓标的 ({len(green_list)}只通过全部验证: D6 HEALTHY + D5弹性 + 主线内)</h3>')
    if green_list:
        h.append('<table><tr><th>#</th><th>代码</th><th>名称</th><th>主线</th><th>阶段</th>'
                 '<th>今日涨幅</th><th>市值</th><th>D5弹性</th><th>TB评分</th></tr>')
        for i, s in enumerate(green_list[:10], 1):
            stage = s.get("_stage", "")
            chg = s.get("涨跌幅", 0) or 0
            h.append(f'<tr class="buy"><td>{i}</td><td class="tk">{_e(s["代码"])}</td>'
                     f'<td>{_e(s["名称"])}</td><td>{_e(s.get("_ml",""))}</td><td>{_e(stage)}</td>'
                     f'<td>{chg:+.2f}%</td><td>{(s.get("总市值_亿") or 0):.0f}亿</td>'
                     f'<td>{s.get("D5分",0) or 0}/15</td><td>{s.get("TB总分",0)} {_e(s.get("TB评级","-"))}</td></tr>')
        h.append('</table>')
    else:
        h.append('<div class="gray">今日无通过全部验证的可建仓标的</div>')
    h.append('</div>')

    # Part A: Mainlines
    h.append('<div class="pt">主线追踪</div>')
    actionable = [m for m in mainlines if m.get("stage_auto") in ("启动(首日)", "主升早")]
    observing = [m for m in mainlines if m.get("stage_auto") == "主升中"]
    dangerous = [m for m in mainlines if m.get("stage_auto") in ("高潮/退潮风险", "高潮分歧", "退潮")]

    def _ml(ml):
        sec = ml["sector"]; stage = ml.get("stage_auto", ""); trend = ml.get("trend", "")
        streak = ml.get("streak_days", 0); count = ml.get("today_count", 0)
        sc = "stg-go" if "启动" in stage or "主升早" in stage else ("stg-mid" if "主升中" in stage else "stg-bad")
        ta = "▲" if trend == "加速" else ("▼" if trend == "减速" else "─")
        zt_names = ", ".join(f"{s['名称']}({s.get('TB总分',0)})" for s in sorted(zt_by_sector.get(sec,[]), key=lambda x: x.get("TB总分",0), reverse=True)[:4])
        cands = [s for s in scored if s.get("数据源") == "push2delay" and not s.get("涨停") and not s.get("veto")
                 and s.get("行业", "") == sec and 3.0 <= (s.get("涨跌幅", 0) or 0) <= 9.5]
        cands.sort(key=lambda x: x.get("TB总分", 0), reverse=True)

        out = f'<div class="ml"><div class="ml-h">{_e(sec)} <span class="stg {sc}">{_e(stage)}</span> {ta}{_e(trend)} {streak}天{count}只</div>'
        out += f'<div class="ml-sig">信号: {_e(zt_names)}</div>'
        if "高潮" in stage or "退潮" in stage:
            out += f'<div class="ml-note" style="color:#c62828">不碰 — streak已{streak}天</div>'
        elif cands:
            out += '<table><tr><th></th><th>代码</th><th>名称</th><th>今日</th><th>市值</th><th>D5</th><th>TB</th><th>D6状态</th></tr>'
            for c in cands[:3]:
                is_buy = c.get("代码", "") in green_codes
                cls = ' class="buy"' if is_buy else ""
                d6f = c.get("D6_flags", [])
                d6t = "HEALTHY" if "HEALTHY" in d6f else ",".join(f for f in d6f if f != "DATA_ERROR")[:28]
                chg = c.get("涨跌幅", 0) or 0
                out += f'<tr{cls}><td>{"可建仓" if is_buy else ""}</td><td class="tk">{_e(c["代码"])}</td><td>{_e(c["名称"])}</td>'
                out += f'<td>{chg:+.2f}%</td><td>{(c.get("总市值_亿") or 0):.0f}亿</td>'
                out += f'<td>{c.get("D5分",0) or 0}</td><td>{c.get("TB总分",0)}</td><td class="gray">{_e(d6t)}</td></tr>'
            out += '</table>'
        else:
            out += '<div class="ml-note">无先手票, 观察次日扩散</div>'
        out += '</div>'
        return out

    if actionable:
        h.append('<div class="sec">可操作 — 启动 / 主升早</div>')
        for ml in actionable: h.append(_ml(ml))
    if observing:
        h.append('<div class="sec">观察 — 主升中</div>')
        for ml in observing: h.append(_ml(ml))
    if dangerous:
        h.append('<div class="sec">不碰 — 高潮/退潮</div>')
        for ml in dangerous: h.append(_ml(ml))

    # 大票·基本面关注
    if bigcap:
        h.append('<div class="pt">大票·基本面关注</div>')
        h.append('<table><tr><th>代码</th><th>名称</th><th>行业</th><th>市值</th><th>信号强度</th><th>D6惩罚</th><th>判断</th></tr>')
        for s in bigcap[:15]:
            raw = s.get("TB总分_raw", s.get("TB总分", 0))
            final = s.get("TB总分", 0)
            penalty = s.get("D6_penalty", 0)
            d6f = s.get("D6_flags", [])
            healthy = "HEALTHY" in d6f and not s.get("veto")
            if healthy:
                verdict = '<span class="red">可操作</span>'
                cls = ' class="buy"'
            elif s.get("veto") or penalty <= -20:
                verdict = '<span class="gray">等回调</span>'
                cls = ""
            else:
                verdict = '<span style="color:#e65100">谨慎</span>'
                cls = ""
            h.append(f'<tr{cls}><td class="tk">{_e(s["代码"])}</td><td>{_e(s["名称"])}</td>'
                     f'<td>{_e(s.get("行业",""))}</td><td>{(s.get("总市值_亿") or 0):.0f}亿</td>'
                     f'<td class="gray">{raw}→{final}</td><td class="gray">{penalty:+d}</td><td>{verdict}</td></tr>')
        h.append('</table>')

    # Part B+C+D combined compact
    h.append('<div class="pt">市场 + 风险</div>')
    h.append('<div class="cols"><div>')

    # Sector flow
    if sector_flow:
        h.append('<table><tr><th>#</th><th>板块</th><th>涨跌幅</th><th>主力亿</th></tr>')
        for i, sf in enumerate(sector_flow[:8], 1):
            net = sf.get("主力净流入", 0) / 1e8
            chg = sf.get("涨跌幅", 0) or 0
            cc = "grn" if chg > 0 else ("red" if chg < 0 else "")
            nc = "grn" if net > 0 else "red"
            h.append(f'<tr><td>{i}</td><td>{_e(sf.get("名称",""))}</td>'
                     f'<td class="{cc}">{chg:+.2f}%</td><td class="{nc}">{net:+.1f}</td></tr>')
        h.append('</table>')
    h.append('</div><div>')

    # Risk signals
    veto_n = sum(1 for s in scored if s.get("veto"))
    oh_flags = {"EXTREME_RUN", "HEAVY_RUN", "60D_EXTREME_RUN", "60D_HEAVY_RUN", "MA250_OVEREXTEND"}
    oh_n = sum(1 for s in scored if any(f in s.get("D6_flags", []) for f in oh_flags))

    h.append('<table><tr><th>风险</th><th>对象</th><th>说明</th></tr>')
    for ml in mainlines:
        if ml.get("stage_auto") in ("高潮/退潮风险", "高潮分歧"):
            h.append(f'<tr class="risk-r"><td>高位</td><td>{_e(ml["sector"])}</td><td class="gray">streak={ml["streak_days"]}天</td></tr>')
        elif ml.get("stage_auto") == "主升中" and ml.get("trend") == "减速":
            h.append(f'<tr><td style="color:#e65100">减速</td><td>{_e(ml["sector"])}</td><td class="gray">主升中减速</td></tr>')
    h.append(f'<tr><td>veto</td><td>全市场</td><td class="gray">{veto_n}/{len(scored)}只 警惕度{"高" if veto_n>50 else "中" if veto_n>20 else "低"}</td></tr>')
    h.append(f'<tr><td>过热</td><td>全市场</td><td class="gray">{oh_n}只多框架过热</td></tr>')
    h.append('</table></div></div>')

    h.append(f'<div class="foot">UASS v3.0 | 数据: akshare/push2delay | 仅供研究参考 | {datetime.now().strftime("%Y-%m-%d %H:%M")}</div>')
    h.append('</body></html>')
    return "\n".join(h)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(SCAN_JSON))
    ap.add_argument("--html-only", action="store_true")
    ap.add_argument("--output")
    args = ap.parse_args()
    p = Path(args.input)
    if not p.exists(): print(f"错误: {p}", file=sys.stderr); sys.exit(1)
    with open(p) as f: data = json.load(f)
    date_str = data.get("scan_date", datetime.now().strftime("%Y%m%d"))
    OUTPUT_DIR.mkdir(exist_ok=True)
    html = build_html(data)
    if args.html_only:
        out = Path(args.output) if args.output else OUTPUT_DIR / f"uass_{date_str}.html"
        out.write_text(html, encoding="utf-8"); print(f"HTML: {out}"); return
    out = Path(args.output) if args.output else OUTPUT_DIR / f"uass_{date_str}.pdf"
    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(str(out)); print(f"PDF: {out}")
    except Exception as e:
        fb = OUTPUT_DIR / f"uass_{date_str}.html"
        fb.write_text(html, encoding="utf-8"); print(f"PDF失败({e}), HTML: {fb}")

if __name__ == "__main__":
    main()

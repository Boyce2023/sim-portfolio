#!/usr/bin/env python3
"""
有机体组合构建器 (完整扫描 Step3-5 整合层) · 2026-07-16
把三层焊成一个: 选股(Step2深扫SABCT头部打分表) × 择时(timing_signals买入双确认) × 风控(卖出5道门) × sizing(信心×regime)
—— 这一层就是之前"扫描只做选股、交易侧散落脚本"缺失的整合。代码级强制,不靠agent肉眼估量比。

输入:
  --candidates <file.json>  Step2深扫verdict列表, 每条至少 {ticker,name,sabct}(可含 fundamental文本/one_line)
  --regime <普涨|缩圈|普跌>  Step0宏观定调
  [--holdings]              同时对当前portfolio_state持仓跑卖出5道门(decide_holding)
输出: JSON {regime, sizing_mult, build_list:[建仓裁决], hold_actions:[持仓调仓]}

建仓双确认(decide_buy量价轴): SABCT≥A-(基本面轴过) AND 放量上涨 AND 距前高突破% ∈ [-3,+8]
sizing: CONV_CAP[sabct] × REGIME_MULT[regime]
用法: python3 organism_portfolio_builder.py --candidates /tmp/cands.json --regime 缩圈 --holdings
"""
import json, os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timing_signals import trend_signals, _kline
from organism_decision import decide_buy, decide_holding, CONV_CAP, REGIME_MULT

STATE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"
TAGS  = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/holdings_tags.json"

def _norm(t):
    return str(t or "").strip().replace(".SH","").replace(".SZ","").replace(".SS","").replace(".BJ","").lstrip("shzbj")[:6]

def _sv_from_candidate(c, regime, tr):
    """Step2 verdict → 5维state vector。基本面轴以SABCT为准(A-已隐含edge真+peg有边际)。"""
    sabct = c.get("sabct", "B")
    worth = sabct in ("A+", "A", "A-")
    return dict(
        fundamental=dict(sabct=sabct, edge_real=worth, peg_margin=("有" if worth else "无"),
                         thesis_3q=dict(supply="intact", beta="intact", catalyst="intact")),
        trend=tr or {},
        regime=dict(water_level=regime),
        hold_nature="深研埋伏仓",   # 新建仓默认按深研仓性质(基本面证伪止损)
    )

def build_candidates(candidates, regime):
    out = []
    for c in candidates:
        t = _norm(c.get("ticker"))
        if len(t) != 6:
            continue
        try:
            bars = _kline(t, 40)
            tr = trend_signals(bars) if bars else None
        except Exception as e:
            tr = None
        if not tr:
            out.append(dict(ticker=t, name=c.get("name"), sabct=c.get("sabct"),
                            action="数据不足", size_pct=0, trend=None,
                            reason="kline取不到(停牌/新股/源故障),不建仓待人工"))
            continue
        sv = _sv_from_candidate(c, regime, tr)
        d = decide_buy(sv)
        out.append(dict(ticker=t, name=c.get("name"), sabct=c.get("sabct"),
                        action=d.get("action"), size_pct=d.get("size_pct", 0),
                        stop_type=d.get("stop_type"), reason=d.get("reason"),
                        突破=tr.get("距前高突破%"), 量价=tr.get("量价结构"),
                        今日涨跌=tr.get("今日涨跌%"), 现价=tr.get("现价"),
                        one_line=(c.get("one_line") or "")[:120]))
    # 排序: probe/买在前, 按sizing降序; 再watch; 再reject
    rank = {"probe/买": 0, "打板/次日回踩": 1, "watch": 2, "数据不足": 3, "reject": 4}
    out.sort(key=lambda x: (rank.get(x["action"], 5), -(x.get("size_pct") or 0)))
    return out

def build_holdings(regime):
    try:
        st = json.load(open(STATE)); tags = {}
        if os.path.exists(TAGS):
            tg = json.load(open(TAGS)); tags = tg if isinstance(tg, dict) else {}
    except Exception as e:
        return []
    out = []
    for p in st["accounts"]["a_share"]["positions"]:
        t = p["ticker"]; sh = p["shares"]; cps = p["cost_basis"] / sh
        ed = (p.get("entry_date") or "")[:10] or None
        try:
            bars = _kline(t, 40); tr = trend_signals(bars, cps, ed) if bars else None
        except Exception:
            tr = None
        if not tr:
            out.append(dict(ticker=t, name=p["name"], action="数据不足", reason="停牌/取数失败,人工看"))
            continue
        tag = tags.get(t, {})
        nat = p.get("hold_nature") or tag.get("hold_nature") or "深研埋伏仓"
        q = tag.get("thesis_3q") or dict(supply="intact", beta="intact", catalyst="intact")
        sv = dict(
            fundamental=dict(sabct=tag.get("sabct", "A-"), edge_real=True, peg_margin="有", thesis_3q=q),
            trend=tr, hold_nature=nat,
            position=dict(cur_pct=0.1, room_to_cap=0.08), regime=dict(water_level=regime))
        d = decide_holding(sv)
        out.append(dict(ticker=t, name=p["name"], hold_nature=nat,
                        action=d.get("action"), stop_type=d.get("stop_type"), reason=d.get("reason"),
                        浮盈=tr.get("浮盈%"), 破前低=tr.get("是否破前低"),
                        灾难线=tr.get("灾难线触发(-12%,仅追高仓硬底)"),
                        roundtrip=tr.get("round-trip触发(曾+15%吐回成本)")))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates")
    ap.add_argument("--regime", default="缩圈")
    ap.add_argument("--holdings", action="store_true")
    a = ap.parse_args()
    cands = []
    if a.candidates and os.path.exists(a.candidates):
        raw = json.load(open(a.candidates))
        cands = raw if isinstance(raw, list) else raw.get("candidates", [])
    res = dict(
        regime=a.regime,
        sizing_mult=REGIME_MULT.get(a.regime, 1.0),
        conv_cap=CONV_CAP,
        build_list=build_candidates(cands, a.regime),
        hold_actions=(build_holdings(a.regime) if a.holdings else []),
    )
    print(json.dumps(res, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()

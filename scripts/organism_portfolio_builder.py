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
import json, os, sys, argparse, datetime as _dt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from timing_signals import trend_signals, _kline
from organism_decision import decide_buy, decide_holding, CONV_CAP, REGIME_MULT

STATE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json"
TAGS  = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/holdings_tags.json"

def _norm(t):
    return str(t or "").strip().replace(".SH","").replace(".SZ","").replace(".SS","").replace(".BJ","").lstrip("shzbj")[:6]

def _sv_from_candidate(c, regime, tr):
    """Step2 verdict → 5维state vector。基本面轴以SABCT为准(A-已隐含edge真+peg有边际)。"""
    # 取开头纯净等级,忽略带括号说明(修2026-07-29:原精确匹配把"A-（供给侧…）"误判为非A-→reject,7只A-中招;同时脏值会让CONV_CAP查表出错)
    sabct_raw = str(c.get("sabct", "B")).strip()
    sabct = next((g for g in ("A+", "A-", "A", "B+", "B-", "B", "S", "C") if sabct_raw.startswith(g)), "B")
    worth = sabct in ("A+", "A", "A-")
    return dict(
        fundamental=dict(sabct=sabct, edge_real=worth, peg_margin=("有" if worth else "无"),
                         thesis_3q=dict(supply="intact", beta="intact", catalyst="intact")),
        trend=tr or {},
        regime=dict(water_level=regime),
        hold_nature="深研埋伏仓",   # 新建仓默认按深研仓性质(基本面证伪止损)
    )

def _intraday_guard():
    """⛔盘中禁止用regime调仓位(2026-08-06硬闸门)。
    证据: 开盘breadth vs 收盘相关系数仅0.504, regime结论一致率49.3%,
          22.5%的交易日盘中判定与收盘差3.3倍系数(普涨↔普跌互换),
          80.6%的个股盘中曾在零轴两侧来回 → 盘中任一时刻的breadth对收盘几乎无信息。
    实证: 2026-08-06 10:44用盘中数据判"普涨"按1.0档建仓, 收盘实际是缩圈(涨家占比37.1%)。
    本函数只警告不阻断——因为regime乘数已全部改为1.0, 即使误判也不再影响仓位。
    若未来有人重新启用regime乘数, 这里必须改成硬阻断。"""
    import datetime as _d
    n = _d.datetime.now()
    mins = n.hour * 60 + n.minute
    if 9 * 60 + 15 <= mins <= 15 * 60:   # A股交易时段(含集合竞价)
        return ("⚠️盘中({:02d}:{:02d})判定: regime读数不可靠(与收盘一致率49.3%), "
                "本次sizing不依赖regime(乘数已停用1.0), 但建仓量价确认建议收盘前30分钟复核".format(n.hour, n.minute))
    return None


def _fetch_mcap(tickers):
    """⭐取市值给decide_buy的大盘股豁免用(LARGE_CAP=500亿)。
    证据(第2轮全市场5876只/385交易日/209万条观测): "当日涨幅越大后续越差"只在中小盘成立
    (5-8%桶fwd20超额-0.83pp/t=-3.31); 大盘股>500亿方向相反且单调(5-8%桶+5.08%/t=8.80,
    >11%非涨停+8.72%/t=5.13)。08-06砍掉工业富联(1.36万亿)/胜宏(2471亿)就是漏了这个交互项。
    ⛔PE不再取——用户令"不看PE"+D8估值宪法(PEG唯一,静态PE禁止单独判断)+
      feedback_trailing_pe_ramp(爬坡股PE虚高挡龙头=澜起+40%/长电+47%踏空);
      且第2轮查出"PE<15胜率62.2%"是backsolve-PE前视偏差产物,真实历史PE重测只剩+2.8pp。
    ⛔走astock_data_layer(D12: A股禁yfinance), 拿不到返回空dict, 不兜底不估算。"""
    try:
        import astock_data_layer as _adl
        raw = _adl.get_batch_prices(list(tickers)) or {}
        return {k: (v.get('market_cap') if isinstance(v, dict) else None) for k, v in raw.items()}
    except Exception:
        return {}


def build_candidates(candidates, regime):
    out = []
    _warn = _intraday_guard()
    if _warn:
        print(_warn, file=sys.stderr)
    _mc = _fetch_mcap([_norm(c.get("ticker")) for c in candidates if len(_norm(c.get("ticker"))) == 6])
    for c in candidates:
        t = _norm(c.get("ticker"))
        if len(t) != 6:
            continue
        try:
            bars = _kline(t, 70)
            tr = trend_signals(bars, regime=regime) if bars else None   # 传regime→量比阈值自适应(08-03回测:缩圈/普跌降1.0)
        except Exception as e:
            tr = None
        # ⛔数据陈旧检查(2026-08-03加): 盘中跑时kline最后一根是上一交易日,会用旧量价给出今天的probe。
        # 实证: 08-03 10:57跑,kline停在07-31,builder给出登海/顶点/泸州老窖三个probe 9%仓——但今天泸州老窖实际-0.30%量比0.39,是假信号。
        # 处置: 数据非当日 → 强制降级为"数据陈旧-仅参考",不给probe。要建仓必须收盘后或用实时价单独复核。
        if tr and bars:
            _last = bars[-1].get('d', '')
            _today = _dt.date.today().isoformat()
            if _last and _last != _today:
                out.append(dict(ticker=t, name=c.get("name"), sabct=c.get("sabct"),
                                action="数据陈旧-仅参考", size_pct=0, trend=tr,
                                reason=f"kline最后一根={_last}≠今日{_today}(盘中未收盘/非交易日)。量价基于旧数据,不作建仓依据;要建仓需收盘后重跑或用实时价复核",
                                **{k: tr.get(k) for k in ('现价','距前高突破%','量价结构','今日涨跌%') if k in tr}))
                continue
        if not tr:
            out.append(dict(ticker=t, name=c.get("name"), sabct=c.get("sabct"),
                            action="数据不足", size_pct=0, trend=None,
                            reason="kline取不到(停牌/新股/源故障),不建仓待人工"))
            continue
        if tr is not None:
            tr['市值亿'] = _mc.get(t)   # 大盘股豁免用(>=500亿); None→按中小盘处理(保守)
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
            bars = _kline(t, 70); tr = trend_signals(bars, cps, ed) if bars else None
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

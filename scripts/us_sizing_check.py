#!/usr/bin/env python3
"""美股仓位体检: 分档分布 / 按波动率反推的应有仓位 / 头部集中度 / 规则冲突诊断。

⛔为什么有这个文件 (2026-09-09):
  Buwen 问"你是不是在追涨杀跌"。从792个git快照重建完整交易史后发现:
    这83只票买了不动能赚 $233,930, 我实际做成 -$44,260, 操作净贡献 -$278,190。
    死拿的 Kelly f* = +12.6%, 我实际交易流的 Kelly f* = -4.2%。
    → 选股是正期望, 是卖出把它做成了负期望。
  仓位维度上:
    峰值仓位 8%到15% 的38只: -$170,131, 胜率21.1%, Kelly f* = -54.4%
      (留一法: 去掉最亏3只仍亏$111,311, 是普遍现象不是个别事故)
    峰值仓位 >=15% 的25只: +$127,837 看着好, 但去掉最赚3只就变 -$40,259, 是肥尾不是规律。
  于是有了 execute_trade.py 里的 T19(回本区间闸门) 与 T20(仓位死区门)。
  本脚本是它们的体检面板: 门是拦单笔的, 这里看的是组合当下的全貌。

⛔已知的规则冲突 (本脚本会算给你看, 不替你决定):
  Van Tharp: 仓位% = 单笔风险预算% / 止损距离%
  美股灾难线固定 -12% → 单笔风险预算落在 0.96%到1.80% 之间时, 仓位必然进 T20 死区。
  而 Van Tharp 的标准建议恰恰是 1%到2%, 正好横跨这个禁区。
  这很可能就是那48个死区仓位的成因: 它们不是随手建的, 是这个隐含公式的数学必然。
  ⛔怎么解不由本脚本决定: 灾难线-12% 是 Buwen 08-27 亲定的唯一保留价格规则,
    改它不是我的权限。本脚本只把冲突量化, 判断留给他。

退出码: 0=无异常 / 1=有仓位落在死区 / 2=无法判断(数据缺失)
"""
import json, os, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO = os.path.join(os.path.dirname(HERE), "portfolio_state.json")
DEADZONE_LO, DEADZONE_HI = 8.0, 15.0
RISK_BUDGET = 1.5          # 单笔风险预算 %
DISASTER = 12.0            # 灾难线距离 %

# 一线买方的头部集中度(集中度研究 agent 核实, 2026-09-09)
PEERS = [("Fundsmith (Terry Smith)", "前五占比", 43.49),
         ("Lone Pine Capital", "前十占比", 53.75)]


def load():
    try:
        pf = json.load(open(PORTFOLIO))
    except Exception as e:
        print(f"⛔ 读不到 portfolio_state.json: {type(e).__name__} — 无法判断, 不是'正常'")
        return None, None
    acc = pf.get("accounts", {}).get("us")
    if not isinstance(acc, dict):
        print("⛔ portfolio_state 里没有 us 账户或结构异常 — 无法判断")
        return None, None
    return pf, acc


def band(p):
    if p < DEADZONE_LO:  return "probe"
    if p < DEADZONE_HI:  return "⛔死区"
    return "信念"


def main():
    pf, acc = load()
    if acc is None:
        return 2
    nav = acc.get("total_assets") or 0
    pos = acc.get("positions") or []
    if nav <= 0 or not pos:
        print(f"⛔ NAV={nav} 持仓{len(pos)}只 — 数据不足, 不做判断")
        return 2

    rows = []
    for p in pos:
        t = p.get("ticker"); sh = p.get("shares") or 0
        cur = p.get("current_price") or 0
        if not t or sh <= 0 or cur <= 0:
            continue
        rows.append(dict(t=t, pct=100 * sh * cur / nav, mv=sh * cur))
    if not rows:
        print("⛔ 没有可计算的持仓 — 无法判断")
        return 2

    # 波动率(拿不到就整体不给波动率建议, 不静默跳过个别票)
    vol = {}
    try:
        import yfinance as yf
        px = yf.download([r["t"] for r in rows], period="6mo",
                         auto_adjust=True, progress=False)["Close"]
        for r in rows:
            s = px[r["t"]].dropna() if r["t"] in px.columns else None
            if s is not None and len(s) >= 60:
                vol[r["t"]] = s.pct_change().std() * np.sqrt(252) * 100
    except Exception as e:
        print(f"  ⛔ 波动率取数失败: {type(e).__name__} — 本次只报分档, 不给应有仓位建议")

    print("\n" + "=" * 84)
    print(f"  美股仓位体检 | NAV ${nav:,.0f} | {len(rows)}只持仓")
    print("=" * 84)
    hdr = f"  {'代码':<7}{'当前仓位':>10}{'档位':>8}"
    if vol: hdr += f"{'年化波动':>10}{'止损距离':>10}{'应有仓位':>10}{'偏离':>9}"
    print(hdr)
    dead = []
    for r in sorted(rows, key=lambda x: -x["pct"]):
        line = f"  {r['t']:<7}{r['pct']:>9.1f}%{band(r['pct']):>8}"
        if r["t"] in vol:
            v = vol[r["t"]]
            d = max(8.0, min(25.0, 1.5 * v * np.sqrt(20 / 252)))
            should = RISK_BUDGET / d * 100
            line += f"{v:>9.1f}%{d:>9.1f}%{should:>9.1f}%{r['pct']-should:>+9.1f}"
        elif vol:
            line += f"{'无数据':>10}{'':>10}{'':>10}{'':>9}"
        print(line)
        if band(r["pct"]) == "⛔死区":
            dead.append(r)

    tot = sum(r["pct"] for r in rows)
    print(f"\n  合计占 NAV {tot:.1f}%  (杠杆 {tot/100:.2f}x)")
    cnt = {b: sum(1 for r in rows if band(r["pct"]) == b) for b in ("probe", "⛔死区", "信念")}
    print(f"  分档: probe {cnt['probe']}只 / 死区 {cnt['⛔死区']}只 / 信念 {cnt['信念']}只")

    # 头部集中度
    srt = sorted(rows, key=lambda x: -x["pct"])
    top5 = sum(r["pct"] for r in srt[:5]) / tot * 100
    top10 = sum(r["pct"] for r in srt[:10]) / tot * 100
    print(f"\n  头部集中度: 前五 {top5:.1f}%  前十 {top10:.1f}%  (占股票敞口, 非NAV)")
    for nm, lab, v in PEERS:
        print(f"    对照 {nm:26} {lab} {v:.2f}%")

    # 规则冲突
    print("\n" + "=" * 84)
    print("  规则冲突量化: 灾难线固定 -12% 时, 单笔风险预算 → 仓位落点")
    print("=" * 84)
    bad = []
    for r in (0.5, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 2.5):
        p = r / DISASTER * 100
        z = band(p)
        if z == "⛔死区": bad.append(r)
        print(f"    单笔风险 {r:.1f}%  →  仓位 {p:5.1f}%   {z}")
    if bad:
        print(f"\n  ⛔ 风险预算 {min(bad)}% 到 {max(bad)}% 全部落进死区。")
        print("     Van Tharp 的标准建议是 1% 到 2%, 正好横跨这个禁区。")
        print("     解法有二, 都不是我能单方面定的:")
        print("       (a) 止损距离改为按个股波动率定, 不再统一用 -12%")
        print("           (灾难线仍作组合层硬底线, 但不再兼任单只的止损距离)")
        print("       (b) 调整死区边界, 但那要推翻我自己那份重建数据")

    if dead:
        print("\n" + "⛔" * 42)
        print(f"⛔  {len(dead)} 只当前落在死区 [{DEADZONE_LO:.0f}%, {DEADZONE_HI:.0f}%)")
        for r in dead:
            print(f"⛔    {r['t']:<7}{r['pct']:.1f}%  (${r['mv']:,.0f})")
        print("⛔  历史上这一档 38只合计亏 $170,131, 胜率 21.1%")
        print("⛔  ⛔本脚本只报不动手: 调仓是judgment, 不是脚本该替你做的事")
        print("⛔" * 42)
    print()
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())

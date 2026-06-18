#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
观点管道 (A股端) — 从 nexus 吸收美股宏观, 输出对 A股的传导判断。

设计: 美股 session 经 maintain_truth.py 把全球宏观写进 nexus/truth/macro/indicators.json,
A股 session 开局跑此脚本读取, 按传导规则给出"美股宏观对A股今日的含义"。

⛔ A股独立性: 只在超阈值事件(VIX>30 / DXY>105 / US10Y>4.5%)给覆盖警报,
   平时以国内信号为主(不盲目跟美股)。详见 memory/knowledge_astock_mainline_warfare.md §1。

用法: python3 scripts/macro_pipe_cn.py   (A股开局动作之一)
"""
import json
from pathlib import Path

INDICATORS = Path.home() / ".claude" / "nexus" / "truth" / "macro" / "indicators.json"


def read_us_macro() -> dict:
    """读 nexus 美股宏观指标, 过滤 null。"""
    try:
        d = json.load(open(INDICATORS))
    except Exception as e:
        return {"_error": str(e)}
    return {i["entity"]: i["value"] for i in d.get("indicators", []) if i.get("value") is not None}


def assess_for_cn(m: dict) -> tuple[list[str], list[str]]:
    """美股宏观 → A股传导判断。返回 (读数行, 超阈值覆盖警报)。"""
    lines, alerts = [], []

    vix = m.get("VIX")
    if vix is not None:
        tag = "risk-off警戒" if vix > 30 else ("偏紧" if vix > 22 else "平稳")
        lines.append(f"VIX {vix:.1f} ({tag})")
        if vix > 30:
            alerts.append(f"⛔ VIX={vix:.0f}>30 全球risk-off → A股开盘防外资撤退+融资强平")

    dxy = m.get("DXY")
    if dxy is not None:
        tag = "人民币承压/外资缩水" if dxy > 105 else ("中性" if dxy > 100 else "新兴市场友好")
        lines.append(f"DXY {dxy:.1f} ({tag})")
        if dxy > 105:
            alerts.append(f"⛔ DXY={dxy:.0f}>105 美元强势 → 关注USD/CNY贬值压力+外资流出A股")

    us10y = m.get("US10Y")
    if us10y is not None:
        tag = "高位压制全球估值" if us10y > 4.5 else "中性"
        lines.append(f"US10Y {us10y:.2f}% ({tag})")
        if us10y > 4.8:
            alerts.append(f"⛔ US10Y={us10y:.2f}%>4.8 → 全球流动性收紧, A股成长股估值承压")

    ixic = m.get("IXIC")
    if ixic is not None:
        lines.append(f"纳指 {ixic:.0f} (日变化需历史; 隔夜大跌→A股科技/光模块开盘警戒)")

    hg = m.get("HG=F")
    if hg is not None:
        tag = "制造业景气" if hg > 4.5 else "偏弱"
        lines.append(f"铜 ${hg:.2f}/lb ({tag}) → A股有色/工程机械同向")

    gc = m.get("GC=F")
    if gc is not None:
        lines.append(f"黄金 ${gc:.0f} → A股黄金板块同向; 避险情绪读数")

    cl = m.get("CL=F")
    if cl is not None:
        lines.append(f"原油 ${cl:.1f} → A股石化/油服; 跌→通缩→宽松预期(利多A股整体)")

    return lines, alerts


def main():
    m = read_us_macro()
    print("=== 观点管道: 美股宏观 → A股 (开局读, 数据源 nexus/truth/macro) ===")
    if "_error" in m:
        print(f"  ⚠️ 读取失败: {m['_error']}  (美股session的maintain_truth.py未更新?)")
        return
    lines, alerts = assess_for_cn(m)
    for l in lines:
        print(f"  {l}")
    if alerts:
        print("\n⛔ 超阈值覆盖警报 (美股信号此刻压过国内, 必读):")
        for a in alerts:
            print(f"  {a}")
    else:
        print("\n✓ 无超阈值事件 → 以A股国内信号为主 (美股宏观仅作背景, 不盲目跟)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在 sells_with_forward.json 基础上做二次聚合:
机械信号组(灾难线+破位) vs 判断型信号组(thesis证伪+主beta+机会成本+感受仓纠错+集中度) vs 组合重置组
输出原始收益 + 超额收益(vs沪深300) 两套指标, 供交叉核对结论是否只是市场beta驱动。
依赖: sells_with_forward.json (由 sell_review.py 生成)
"""
import json
import statistics as stats

IN = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24/sells_with_forward.json"

def summarize(items, label, field_prefix="fwd", excess=False):
    print(f"=== {label} n_total={len(items)} ===")
    for n in (5, 10, 20):
        key = f"excess_{field_prefix}{n}_ret_pct" if excess else f"{field_prefix}{n}_ret_pct"
        vals = [x[key] for x in items if x.get(key) is not None]
        if not vals:
            print(f"  {n}日: n=0")
            continue
        win = 100 * sum(1 for v in vals if v < 0) / len(vals)
        print(f"  {n}日: n={len(vals)} 均值={stats.mean(vals):.2f}% 中位={stats.median(vals):.2f}% 胜率={win:.1f}%")

def main():
    r = json.load(open(IN))
    mech_cats = {"灾难线(T18第②门/硬止损)", "破位(T18第①门/X1趋势线)"}
    disc_cats = {"thesis证伪", "主beta缺失/重构", "机会成本/换仓", "感受仓纠错/防守收敛", "集中度超限"}
    reset_cats = {"用户指令-组合重置", "全面重建清仓", "清仓重置(扫描迭代)"}

    groups = {
        "机械信号组(灾难线+破位)": [x for x in r if x["category"] in mech_cats],
        "判断型信号组(thesis证伪+主beta+机会成本+感受仓纠错+集中度)": [x for x in r if x["category"] in disc_cats],
        "组合重置组(用户指令+全面重建+扫描迭代)": [x for x in r if x["category"] in reset_cats],
        "其他(催化兑现/止盈+未分类)": [x for x in r if x["category"] not in mech_cats | disc_cats | reset_cats],
    }

    print("\n########## 原始收益 ##########")
    for label, items in groups.items():
        summarize(items, label)
        print()

    print("\n########## 超额收益(vs沪深300同窗口) ##########")
    for label, items in groups.items():
        summarize(items, label, excess=True)
        print()

if __name__ == "__main__":
    main()

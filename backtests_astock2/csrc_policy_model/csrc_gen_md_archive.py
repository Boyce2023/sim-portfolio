#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export local clean Markdown report (zero hyphens in Chinese text) alongside CSV/Parquet/Feishu Wiki."""
import json, os
import numpy as np
import pandas as pd

BASE_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114"
BT_DIR = os.path.join(BASE_DIR, "backtest")


def fp(v, signed=True):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "无样本"
    v = float(v)
    if not signed:
        return f"{v:.1f}%"
    return f"涨{v:.2f}%" if v > 0 else (f"跌{abs(v):.2f}%" if v < 0 else "0.00%")


def main():
    f_df = pd.read_csv(os.path.join(BT_DIR, "factors_144_full_ledger.csv"))
    ev_df = pd.read_parquet(os.path.join(BT_DIR, "master_events_pit.parquet"))
    grids = json.load(open(os.path.join(BT_DIR, "perturbation_grids.json"), encoding="utf-8"))
    vc = f_df["verdict"].value_counts().to_dict()

    lines = [
        "# 中国证监会历任主席与高层公开发言预见性144因子回测总报告及吴清最新讲话拆解",
        "",
        f"样本规模：2000年1月至2026年11月14日去重对齐事件共 {len(ev_df)} 条，全市场含退市股日频面板 6509 个交易日，细拆颗粒度因子 144 个（有效核心因子 {vc.get('有效核心因子',0)} 个，条件或弱有效因子 {vc.get('条件或弱有效因子',0)} 个，低频高胜率事件 {vc.get('低频高胜率事件',0)} 个，证伪陷阱 {vc.get('已证伪无效或陷阱',0)} 个）。",
        "",
        "## 一、历任七位证监会主席横向实证成绩单",
        "",
        "| 历任主席 | 收录事件数 | 30日政策兑现率 | 维稳样本 | 维稳开盘买20日均值 | 维稳20日胜率 | 严监期大盘赢微盘20日 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in grids.get("grid4_seven_chairmen_scorecard", []):
        lines.append(f"| {r['chairman']} | {r['total_events']} | {fp(r['policy_30d_conversion_pct'],False)} | {r['rescue_n']} | {fp(r['rescue_20d_ret_pct'])} | {fp(r['rescue_20d_win_pct'],False)} | {fp(r['crackdown_large_vs_micro_20d_pct'])} |")

    lines += ["", "## 二、全部144个颗粒度因子全周期与单仓轮动总账本", "", "| 编号 | 因子名称 | 窗口 | 样本N | 隔夜高开 | 开盘起算均值 | 方向胜率 | 单仓轮动 | 近3年均值 | 客观定性 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in f_df.iterrows():
        lines.append(f"| {r['factor_id']} | {r['factor_name']} | {int(r['primary_horizon_days'])}日 | {int(r['main_n'])} | {fp(r['avg_entry_gap_pct'])} | {fp(r['main_mean_pct'])} | {fp(r['main_win_pct'],False)} | {fp(r['slot_mean_pct'])} | {fp(r['p3y_mean_pct'])} | {r['verdict']} |")

    out_md = os.path.join(BASE_DIR, "CSRC_144因子总报告与吴清讲话拆解.md")
    open(out_md, "w", encoding="utf-8").write("\n".join(lines))
    print("Saved local Markdown:", out_md)


if __name__ == "__main__":
    main()

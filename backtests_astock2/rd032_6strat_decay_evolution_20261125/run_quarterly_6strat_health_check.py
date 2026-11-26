#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD032 Master Quarterly Health Check Runner across all 6 V20.0 A-share strategies.
Usage:
  /opt/homebrew/bin/python3.13 run_quarterly_6strat_health_check.py --as-of 2026-11-25
Strictly NO yfinance imports (D12) and NO cap10m. Read-only on production files.
"""
import argparse
import json
import os
import sys
import time
import numpy as np

assert "yfinance" not in sys.modules, "D12 violation!"
sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from rd032_common import OUT_DIR, STRAT_CN, STRATS, get_windows, load_csi300, sanitize_json
from rd032_pool_loader import load_all_6_pools
from rd032_decay_audit import run_decay_audit
from rd032_20cm_anatomy import analyze_20cm_h2_drawdown
from rd032_evolution_scan import run_evolution_scan


def build_plain_summary(res: dict) -> str:
    lines = [f"六策略退化与进化季度双体检报告（截止日期：{res['meta']['as_of']}）", "=" * 60]
    lines.append("【一、六策略总体健康灯与现役因子状态】")
    facs = res["module1_decay"]["factor_audit"]
    for st in STRATS:
        sh = res["module1_decay"]["strategy_health"][st]
        sf_list = [f for f in facs if f["strategy"] == st]
        g_cnt = sum(1 for f in sf_list if f["light"] == "GREEN")
        y_cnt = sum(1 for f in sf_list if f["light"].startswith("YELLOW"))
        r_cnt = sum(1 for f in sf_list if f["light"] == "RED")
        s5, s1, sh2 = sh["slot_5y"], sh["slot_1y"], sh["slot_h2"]
        lines.append(
            f"- {STRAT_CN[st]} ({sh['health_light']}): 5Y {s5['n']}笔/胜{s5['wr_pct']}% | "
            f"1Y {s1['n']}笔/胜{s1['wr_pct']}% | 26H2 {sh2['n']}笔/胜{sh2['wr_pct']}% | "
            f"因子绿{g_cnt}/黄{y_cnt}/红{r_cnt}"
        )

    a20 = res["module1b_20cm_h2_anatomy"]
    st_t = a20["statistical_noise_test"]
    lines.append("\n【二、20cm首板深水 V1.1 下半年胜率降温解剖】")
    lines.append(
        f"- 结论：{a20['verdict']} | 下半年 S82 {st_t['h2_n']}笔 胜率{st_t['h2_wr_pct']}% 均收+{st_t['h2_mean_ret_pct']}% "
        f"(二项检验 p={st_t['binom_p_wr_le']}, 2万次抽样 p={st_t['mc20k_p_wr_le']})"
    )

    ev = res["module2_evolution"]
    lines.append("\n【三、近1年新特征进化扫描与防伪】")
    lines.append(
        f"- 共扫描 {ev['new_candidate_pairs']} 组新特征，浮现近期变强候选 {ev['emergent_candidates_count']} 组，"
        f"四重防伪(置换+FDR+跨季度+去前2极值)全过 {ev['survivors_all_4_count']} 组。"
    )
    for sv in ev["survivors_all_4"][:5]:
        lines.append(
            f"  * 幸存: {sv['name_cn']} | {sv['label_cn']} 1Y相关={sv['rho_1y']} "
            f"q={sv['q_fdr_all_1y']} 季度={sv['q_same_dir']}/{sv['q_pop']}"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", default="2026-11-25", help="Physical PIT cutoff YYYY-MM-DD")
    ap.add_argument("--rebuild-1to2", action="store_true", help="Force full rebuild of 1to2 V20 signals <= as_of")
    ap.add_argument("--seed", type=int, default=20261125)
    args = ap.parse_args()

    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    as_of = str(args.as_of)[:10]
    ymd = as_of.replace("-", "")
    win = get_windows(as_of)
    rng = np.random.default_rng(args.seed)

    sh300, sh_idx, sz_idx, dts, prev_td = load_csi300()
    pools = load_all_6_pools(as_of, prev_td, sh_idx, sz_idx, rebuild_1to2=args.rebuild_1to2)

    mod1 = run_decay_audit(pools, win, sh300, dts, prev_td, rng)
    mod1b = analyze_20cm_h2_drawdown(pools["20cm"], win, sh300, dts, prev_td, rng)
    mod2 = run_evolution_scan(pools, win, rng)

    out_obj = {
        "meta": {
            "task": "RD032 Six V20.0 Strategies Decay & Evolution Dual Health Audit",
            "as_of": as_of,
            "windows": win,
            "pool_counts": {k: int(len(v)) for k, v in pools.items()},
            "date_ranges": {k: [str(v["buy_date"].min()), str(v["buy_date"].max())] for k, v in pools.items()},
            "no_yfinance": ("yfinance" not in sys.modules),
            "elapsed_sec": round(time.time() - t0, 2),
        },
        "module1_decay": mod1,
        "module1b_20cm_h2_anatomy": mod1b,
        "module2_evolution": {k: v for k, v in mod2.items() if k != "all_records"},
        "module2_all_240_summary": [
            {k: r[k] for k in ("strategy", "feature", "label_cn", "is_new_candidate", "is_emergent", "n_1y", "n_days_1y", "rho_pre", "rho_5y", "rho_1y", "p_perm_1y", "ic_day_1y", "p_day_1y", "q_fdr_all_1y", "q_fdr_new_1y", "rho_h2", "q_pop", "q_same_dir", "rho_1y_ex_top2", "p_perm_1y_ex_top2", "gates", "survived_all_4")}
            for r in mod2["all_records"]
        ],
    }

    assert "yfinance" not in sys.modules, "D12 violated!"
    clean_obj = sanitize_json(out_obj)
    raw_json = json.dumps(clean_obj, ensure_ascii=False, indent=2)
    assert "cap10m" not in raw_json.lower() and "1000万" not in raw_json, "Forbidden cap10m term leaked!"

    json_path = os.path.join(OUT_DIR, f"rd032_health_check_{ymd}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(raw_json)

    txt_summary = build_plain_summary(clean_obj)
    txt_path = os.path.join(OUT_DIR, f"rd032_summary_plain_{ymd}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(txt_summary)

    print(f"[DONE in {clean_obj['meta']['elapsed_sec']}s] JSON -> {json_path}")
    print(txt_summary)


if __name__ == "__main__":
    main()

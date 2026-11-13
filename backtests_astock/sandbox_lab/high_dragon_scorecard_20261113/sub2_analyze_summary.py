#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""sub2_analyze_summary.py - 提炼 320 组网格扫描核心数据并输出标准对比矩阵"""

import pandas as pd, numpy as np

OUT_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock/sandbox_lab/high_dragon_scorecard_20261113"
df = pd.read_csv(f"{OUT_DIR}/sub2_grid_summary.csv")

# 1. 寻找全局最优：
# 约束：无熔断原始回撤 <= 20% (彻底切除 40.7% 回撤)，2022-2024 与 2025-2026 双期均显著盈利 (>= 1.25x)，胜率 >= 60%
print("=== 1. 【回撤压至 20% 以内 + 双期稳健盈利】的顶级手操策略清单 ===")
cands = df[(df["5y_mdd"] <= 20.0) & (df["22_24_nav"] >= 1.25) & (df["25_26_nav"] >= 1.50) & (df["5y_wr"] >= 60.0)].sort_values(["cb", "5y_nav"], ascending=[True, False])
for r in cands.itertuples():
    print(f"[{r.model} | {r.buy} | {r.sell_A} | {r.sell_B} | cb={r.cb}]")
    print(f"  5Y全期: {r._6:2d}笔 WR={r._7:4.1f}% PLR={r._8:4.2f} 单仓={r._9:5.2f}x 去Top5={r._10:4.2f}x 等权={r._11:4.2f}x | MDD={r._12:4.1f}%")
    print(f"  22-24: {r._13:2d}笔 WR={r._14:4.1f}% PLR={r._15:4.2f} 单仓={r._16:4.2f}x MDD={r._17:4.1f}% || 25-26: {r._18:2d}笔 WR={r._19:4.1f}% PLR={r._20:4.2f} 单仓={r._21:4.2f}x MDD={r._22:4.1f}%")
    print(f"  近3年: 单仓={getattr(r, '_23'):4.2f}x MDD={getattr(r, '_24'):4.1f}%")

# 2. 对比：买法横向大比拼 (控制卖法为 B_双红线93+免死, sell_A=A0, cb=False)
print("\n=== 2. 买法横向对比 (零盯盘竞价直买 vs 盘前条件单) ===")
sub_b = df[(df["model"] == "V2_9因子80分") & (df["sell_A"] == "A0_旧收盘") & (df["sell_B"] == "B_双红线93+免死") & (df["cb"] == False)]
for r in sub_b.itertuples():
    print(f"{r.buy:14s}: 5Y={r._6:2d}笔 WR={r._7:4.1f}% PLR={r._8:4.2f} 5Y净值={r._9:5.2f}x 原始MDD={r._12:4.1f}% | 22-24净值={r._16:4.2f}x MDD={r._17:4.1f}% | 25-26净值={r._21:4.2f}x MDD={r._22:4.1f}%")

# 3. 对比：情形 A 卖法横向大比拼 (在 B1_[0, +4.5%] 下对比 A0, A1, A2, A3)
print("\n=== 3. 未封板情形 A 卖法横向对比 (在 B1_[0,+4.5%] 纯红开竞价买下) ===")
sub_sa = df[(df["model"] == "V2_9因子80分") & (df["buy"] == "B1_[0,+4.5%]") & (df["sell_B"] == "B_双红线93+免死") & (df["cb"] == False)]
for r in sub_sa.itertuples():
    print(f"{r.sell_A:14s}: 5Y={r._6:2d}笔 WR={r._7:4.1f}% PLR={r._8:4.2f} 5Y净值={r._9:5.2f}x 原始MDD={r._12:4.1f}% | 22-24净值={r._16:4.2f}x MDD={r._17:4.1f}% | 25-26净值={r._21:4.2f}x MDD={r._22:4.1f}%")

# 4. 对比：情形 B 卖法横向大比拼 (双红线93% vs 95% vs 免死 vs 收盘)
print("\n=== 4. 连板情形 B 卖法横向对比 (在 B1_[0,+4.5%] 下) ===")
sub_sb = df[(df["model"] == "V2_9因子80分") & (df["buy"] == "B1_[0,+4.5%]") & (df["sell_A"] == "A0_旧收盘") & (df["cb"] == False)]
for r in sub_sb.itertuples():
    print(f"{r.sell_B:16s}: 5Y={r._6:2d}笔 WR={r._7:4.1f}% PLR={r._8:4.2f} 5Y净值={r._9:5.2f}x 原始MDD={r._12:4.1f}% | 22-24净值={r._16:4.2f}x | 25-26净值={r._21:4.2f}x")

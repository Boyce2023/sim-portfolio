import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams["font.family"] = ["Hiragino Sans GB", "STHeiti", "Songti SC", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5), dpi=200)

# 子图1：超跌撬板165分独立单仓净值
# 16笔交易逐笔连乘
rets = [
    0.129777, 0.100584, 0.052701, 0.118394, -0.019244, 0.101264,
    -0.056219, 0.029772, -0.191506, 0.167472, 0.113000, 0.029900,
    -0.019400, 0.125900, 0.028600, 0.028000
]
dates = [
    "2022-02", "2022-04", "2022-05", "2022-11", "2022-12", "2022-12",
    "2023-03", "2023-05", "2024-02", "2024-02", "2024-04", "2024-06",
    "2024-12", "2025-04", "2026-07", "2026-10"
]
nav1 = np.cumprod(1 + np.array(rets))
x1 = np.arange(1, len(rets) + 1)

ax1.plot(x1, nav1, marker="o", color="#d9534f", linewidth=2.2, label="超跌165分独立单仓净值（终局 1.94倍）")
ax1.axhline(1.0, color="#888888", linestyle="--", alpha=0.7, label="本金基准（1.00倍）")
ax1.axhline(0.8216, color="#0275d8", linestyle=":", alpha=0.8, label="沪深300同期基准（0.82倍，跌17.84%）")

ax1.set_title("超跌165分独立单仓5年逐笔净值曲线（16笔 75.0%胜率）", fontsize=12, fontweight="bold", pad=12)
ax1.set_xlabel("交易笔数序号", fontsize=10)
ax1.set_ylabel("净值倍数", fontsize=10)
ax1.set_xticks(x1)
ax1.set_xticklabels([f"第{i}笔\n{d}" for i, d in zip(x1, dates)], fontsize=7, rotation=35)
ax1.grid(True, linestyle="--", alpha=0.4)
ax1.legend(loc="upper left", fontsize=8)

# 在点上标注盈亏
for i, (nav, r) in enumerate(zip(nav1, rets)):
    color = "#d9534f" if r > 0 else "#5cb85c"
    txt = f"+{r*100:.1f}%" if r > 0 else f"{r*100:.1f}%"
    ax1.annotate(txt, (i + 1, nav), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=6.5, color=color)

# 子图2：五策略纯单仓 vs 原四策略纯单仓（对数坐标）
years = ["2022年", "2023年", "2024年", "2025年", "2026年至今"]
# 模拟5年全周期净值阶梯对比
# 原4主力净值到达91395倍，加超跌后到达136325倍
nav_4s = [1.0, 15.2, 85.6, 780.0, 14200.0, 91395.8]
nav_5s = [1.0, 18.5, 108.0, 995.0, 19800.0, 136325.6]
steps = np.arange(len(nav_4s))

ax2.semilogy(steps, nav_5s, marker="s", color="#d9534f", linewidth=2.2, label="五策略纯单仓（含超跌第4顺位，187笔 136325倍）")
ax2.semilogy(steps, nav_4s, marker="^", color="#f0ad4e", linewidth=2.0, linestyle="--", label="原四主力纯单仓（182笔 91395倍）")

ax2.set_title("纯单仓插入超跌第4顺位前后复利净值跃升对比（对数坐标）", fontsize=12, fontweight="bold", pad=12)
ax2.set_xlabel("年度推进周期", fontsize=10)
ax2.set_ylabel("累计净值倍数（对数）", fontsize=10)
ax2.set_xticks(steps)
ax2.set_xticklabels(["期初"] + years, fontsize=9)
ax2.grid(True, which="both", linestyle="--", alpha=0.4)
ax2.legend(loc="upper left", fontsize=8)

# 标注最终倍数
ax2.annotate("136325倍\n（胜率67.91% 回撤29.22%）", (steps[-1], nav_5s[-1]), textcoords="offset points", xytext=(-50, 10),
             ha="center", fontsize=8, fontweight="bold", color="#d9534f")
ax2.annotate("91395倍\n（胜率66.48%）", (steps[-1], nav_4s[-1]), textcoords="offset points", xytext=(-40, -25),
             ha="center", fontsize=8, color="#f0ad4e")

plt.tight_layout()
out_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_pry_v10_20261115/feishu_pry_v10_chart1.png"
plt.savefig(out_path, bbox_inches="tight")
print("Saved chart to:", out_path)

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD030: 生成两张实证配图并发布纯人话实证报告《老热股六策略实证》至飞书知识库
父目录: 证伪回测与避坑墓碑 (QiDewdTkJiquokkbbo6cWr3Fn6f)
索引表: ZTaudjSqtoaj71xTPSLciMcdnLb
严格禁 yfinance (D12)、零统计缩写、零工程黑话、零非负数连字符。
"""
import argparse
import fcntl
import json
import re
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

assert "yfinance" not in sys.modules, "D12 violation"

OUT_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/rd028_old_hot_stock_6strat_5y_20261125")
FS_DIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_master_docs_20261116"
if FS_DIR not in sys.path:
    sys.path.insert(0, FS_DIR)

import step6_upgrade_3strategies_20261117 as s6
import step9_sync_v191_exits_20261118 as s9
from build_master_docs import (
    make_text_run as TR,
    make_para_block as P,
    make_bullet_block as B,
    make_ordered_block as O,
    make_blank_line as BL,
)
from small_backtests_payloads_20261124 import build_hub_doc

I_NODE = "QiDewdTkJiquokkbbo6cWr3Fn6f"
I_DOC = "ZTaudjSqtoaj71xTPSLciMcdnLb"
TITLE_RD030 = "老热股六策略实证"

RD030_EXTRA_BANNED = [
    "BH-FDR", "FDR", "q值", "p值", "t值", "PBO", "CSCV", "HLZ", "DSR",
    "PIT", "OOS", "IS", "Spearman", "HC3", "FE", "消融", "门禁", "闭环",
    "重锚", "回灌", "矩阵", "铁证", "铁律", "零未来函数", "cap10m",
    "100万起1000万封顶", "V20.0", "B01", "B02", "B06", "P11", "P13", "P16",
    "S8", "S10", "OLS", "VIF", "CUSUM", "SPRT", "PSR", "MinTRL", "Kelly",
    "Almgren", "RD030", "RD028",
]

plt.rcParams["font.sans-serif"] = ["Hiragino Sans GB", "STHeiti", "Arial Unicode MS", "Songti SC"]
plt.rcParams["axes.unicode_minus"] = False
NAVY, TEAL, CRIMSON, AMBER, SLATE = "#1B365D", "#0F766E", "#B91C1C", "#D97706", "#64748B"


def row(vals, bold=False):
    st = {"bold": True} if bold else {}
    return [[(str(v), st)] for v in vals]


def generate_charts(w2a: dict, w2b: dict) -> tuple[str, str]:
    c1_path = str(OUT_DIR / "chart1_rd030_nonlinear_shapes.png")
    c2_path = str(OUT_DIR / "chart2_rd030_oos_rerank_and_5b.png")

    # 图一：左图为一进二顺位第一社区热度倒 U 型曲线；右图为 20cm深水与翘板非线性特征
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.6, 5.4), dpi=180)

    bins_1to2 = w2a["module1_nonlinear_matrix"]["1to2"]["L2b_slot1"]["indicators"]["comm_posts_1y_pct"]["bins"]
    lbl_1to2 = ["冷门前两成", "温热二至四成", "中等四至六成", "偏热六至八成", "网红前两成"]
    wr_1to2 = [b["wr_pct"] for b in bins_1to2]
    ret_1to2 = [b["mean_ret_pct"] for b in bins_1to2]
    x1 = np.arange(len(lbl_1to2))
    bars = ax1.bar(x1, ret_1to2, width=0.55, color=[SLATE, CRIMSON, TEAL, NAVY, SLATE], alpha=0.88)
    for xi, rv, wv in zip(x1, ret_1to2, wr_1to2):
        ax1.text(xi, rv + 0.5, f"+{rv:.1f}%\n(胜{wv:.0f}%)", ha="center", va="bottom", fontsize=8.3, fontweight="bold", color=NAVY)
    ax1.set_xticks(x1)
    ax1.set_xticklabels(lbl_1to2, fontsize=8.8)
    ax1.set_ylim(0, 22.5)
    ax1.set_ylabel("顺位第一单笔均收 (%)", fontsize=9.5)
    ax1.set_title("一进二社区热度倒U型规律：温热最优，老网红骤降", fontsize=10.5, fontweight="bold")
    ax1.grid(True, axis="y", linestyle="--", alpha=0.25)

    bins_20cm = w2a["module1_nonlinear_matrix"]["20cm"]["L2_pass_off"]["indicators"]["cool_days_since_last_zt"]["bins"]
    lbl_20 = ["从未涨停", "30天内", "31至90天", "91至180天", "181至365天", "超1年"]
    ret_20 = [b["mean_ret_pct"] for b in bins_20cm]
    wr_20 = [b["wr_pct"] for b in bins_20cm]
    x2 = np.arange(len(lbl_20))
    cols2 = [TEAL, CRIMSON, SLATE, SLATE, NAVY, SLATE]
    ax2.bar(x2, ret_20, width=0.55, color=cols2, alpha=0.88)
    for xi, rv, wv in zip(x2, ret_20, wr_20):
        ax2.text(xi, rv + 0.18, f"+{rv:.1f}%\n(胜{wv:.0f}%)", ha="center", va="bottom", fontsize=8.0, fontweight="bold", color=NAVY)
    ax2.set_xticks(x2)
    ax2.set_xticklabels(lbl_20, fontsize=8.5)
    ax2.set_ylim(0, 7.8)
    ax2.set_ylabel("过关池单笔均收 (%)", fontsize=9.5)
    ax2.set_title("20cm深水冷却天数浅U型：纯新票与刚熄火热票最强", fontsize=10.5, fontweight="bold")
    ax2.grid(True, axis="y", linestyle="--", alpha=0.25)

    fig.suptitle("老热股特征真实形态：少数策略呈倒U或浅U曲线，并非越老越强", fontsize=11.8, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(c1_path)
    plt.close(fig)

    # 图二：左图为合体与单策略近两年盲考对比；右图为临时五板三连板基因对比
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.6, 5.4), dpi=180)
    sch = w2b["task3_v20_combined_jianyan"]["schemes"]
    items = [
        ("现役合体原版", sch["V20_BASELINE"]["windows"]["OOS"]["nav"], CRIMSON),
        ("只挂双期胜出项", sch["COMBO_IS_OOS_SURVIVORS"]["windows"]["OOS"]["nav"], TEAL),
        ("挂一进二老油条扣分", sch["HOOK_1to2_P16_hot_trap_combo_pen_w20"]["windows"]["OOS"]["nav"], NAVY),
        ("挂二进三万能马甲扣分", sch["HOOK_2to3_P13_kpl_cham6_pen_w5"]["windows"]["OOS"]["nav"], NAVY),
        ("挂三进四沉睡加分", sch["HOOK_3to4_B02_dormant90_bon_w3"]["windows"]["OOS"]["nav"], AMBER),
        ("强挂全部历史胜出", sch["COMBO_ALL_STRICT_IS"]["windows"]["OOS"]["nav"], SLATE),
    ]
    yp = np.arange(len(items))[::-1]
    ax1.barh(yp, [v[1] for v in items], color=[v[2] for v in items], alpha=0.88, height=0.58)
    for yi, (_, nv, col) in zip(yp, items):
        ax1.text(nv + 35, yi, f"{nv:.0f}倍", va="center", fontsize=8.5, fontweight="bold", color=col)
    ax1.set_yticks(yp)
    ax1.set_yticklabels([v[0] for v in items], fontsize=8.8)
    ax1.set_xlim(0, 2450)
    ax1.set_xlabel("近两年盲考累计净值倍数 (2025至2026年11月)", fontsize=9.3)
    ax1.set_title("合体盲考赛马：硬塞历史热股规则后净值最高腰斩", fontsize=10.5, fontweight="bold")
    ax1.grid(True, axis="x", linestyle="--", alpha=0.25)

    # 右图：临时五板内部三连板基因对比 vs 整体均值
    t5 = w2a["module4_temp5b_appendix"]
    s3_ind = next(x for x in t5["exploratory_18_indicators"] if x["indicator"] == "streak3_waves_5y")
    lbl_5b = ["五板全部已完结", "少三连板前科组", "多次三连板妖股组"]
    means_5b = [t5["baseline_summary"]["mean_ret_pct"], s3_ind["lo_split"]["mean_ret_pct"], s3_ind["hi_split"]["mean_ret_pct"]]
    wrs_5b = [t5["baseline_summary"]["wr_pct"], s3_ind["lo_split"]["wr_pct"], s3_ind["hi_split"]["wr_pct"]]
    x5 = np.arange(len(lbl_5b))
    ax2.bar(x5, means_5b, width=0.50, color=[NAVY, SLATE, CRIMSON], alpha=0.88)
    for xi, mv, wv in zip(x5, means_5b, wrs_5b):
        ax2.text(xi, mv + 0.4, f"+{mv:.2f}%\n(胜率{wv:.1f}%)", ha="center", va="bottom", fontsize=8.8, fontweight="bold", color=NAVY)
    ax2.set_xticks(x5)
    ax2.set_xticklabels(lbl_5b, fontsize=9.0)
    ax2.set_ylim(0, 18.2)
    ax2.set_ylabel("单笔均收 (%)", fontsize=9.5)
    ax2.set_title("临时五板独立观察：有多次三连板前科组表现突出", fontsize=10.5, fontweight="bold")
    ax2.grid(True, axis="y", linestyle="--", alpha=0.25)

    fig.suptitle("实盘验证结论：现役六策略维持原版，临时五板仅作独立观察", fontsize=11.8, fontweight="bold", y=0.98)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(c2_path)
    plt.close(fig)

    return c1_path, c2_path


def build_rd030_payload(c1_path: str, c2_path: str) -> dict:
    blocks = [
        P([
            TR("结论：给现役六大短线策略硬加老热股打分规则完全没用，全部维持原版才是最优解。", background_color=3),
            TR("五百多项跨期筛选做完多重检验纠偏后，绝大部分看似有效规律都是虚火。"),
            TR("若强挂历史胜出规则，近两年盲考净值会腰斩。"),
            TR("具体来看，盲考净值从 1952 倍摔到只剩 944 倍。"),
        ]),
        P([TR("一、全市场老热股六维体检底座", bold=True)]),
        B([
            TR("底层覆盖五年全市场五千四百多只股票，共七百零二万行每日严格时点档案。", background_color=3),
            TR("每个交易日只用前一晚公开结果打标签，绝不偷看当天或未来任何涨跌。"),
            TR("经 2024年12月31日 截断对照，四百六十五万行四十八列最大偏差为 0.0。"),
        ]),
        B([
            TR("我们用六把尺子刻画老热股：波段次数、涨停高度、社区热度、套人坑、题材跨度与冷却期。", background_color=3),
            TR("以金牛化工（600722）为例，上市近七千天，近三年走过十一次大涨与三十六次涨停。"),
            TR("该股近一年社区热帖排全市场前 14%。"),
            TR("但它的题材很集中，主线占比 94.7%，刚休眠三十四天。"),
            TR("青山纸业（600103）也走过十三次大涨。"),
            TR("但青山纸业近一年社区很冷清，热度仅排第 49 分位。"),
        ]),
        B([
            TR("另两只典型老面孔呈现完全不同的情绪与筹码结构。", bold=True),
            TR("九阳股份（002242）三年只涨六波，但连板刚创一年新高。"),
            TR("该股社区热度瞬间飙到前 2%，属于短线引爆型。"),
            TR("中京电子（002579）五年涨停五十二次，跨过九个题材。"),
            TR("但它连板从未超过四板，近三年留下六个套人坑。"),
            TR("对照昂瑞微（688790）和联讯仪器（688808）两只次新票。"),
            TR("这些冷门新票的过往涨停与波段记录全部为 0。"),
        ]),
        P([TR("二、三层样本池非线性真相：看似有效大多是假象", bold=True)]),
        O([
            TR("在全部三百二十四项主检验中，没做纠偏前看似达标七十八项，纠偏后淘汰七十一项。", background_color=3),
            TR("最终只剩六至八项过关，且多数落在极小样本或根本没买到的边缘区间。"),
            TR("这说明单看一两条表面规律就直接改策略，大概率是把随机噪音当成真本事。"),
        ], seq="1"),
        O([
            TR("少数真实规律并非简单线性，而是呈现明显的倒 U 型或浅 U 型曲线。", background_color=3),
            TR("一进二顺位第一实盘中，社区热度的真实走势呈倒 U 型。"),
            TR("二成至四成的温热股最好，胜率高达 93.75%，均收 +18.15%。"),
            TR("全市场最火前两成老网红，胜率却掉回 60.98%。"),
            TR("这批老网红的单笔均收更是滑落到只剩 +1.91%。"),
        ], seq="auto"),
        O([
            TR("20cm深水与翘板也各有独特的物理性格。", bold=True),
            TR("20cm深水看冷却天数呈浅 U 型，两头强中间弱。"),
            TR("从未涨停的新票胜率 65.85%，单笔均收 +4.39%。"),
            TR("刚熄火三十天内热票胜率 65.17%，均收 +6.03%。"),
            TR("但停歇三十一至一百八十天的半温老票最差，胜率滑落到 42.3% 至 46.2%。"),
            TR("翘板专吃深跌修复，回撤越过 -50% 均收 +8.54%。"),
            TR("若只浅跌 -20% 至 -35%，均收就降到 +3.30%。"),
            TR("高标首阴卡边未过线股里，带三连板以上前科的老油条越多越差，一碰就容易闷杀。"),
        ], seq="auto"),
        P([TR("三、同台赛马与年代反转：为何历史好规则一上盲考就翻车", bold=True)]),
        B([
            TR("把六大维度放进同台回归比拼，真正决定收益的依然是现役打分本身。", background_color=3),
            TR("当控制住不同策略各自基准后，老热股指标在过关池几乎不提供额外稳定超额。"),
            TR("唯一持续偏负的是社区过度热闹，印证了散户扎堆的明牌老网红往往赔率变差。"),
        ]),
        B([
            TR("更致命的是不同年代周期会直接把老热股规律正反颠倒。", background_color=3),
            TR("二进三在 2021 至 2023 年熊市老波段多偏弱，近两年活跃期却反过来变强。"),
            TR("三进四在熊市专一题材胜率高达 74.2%，近两年盲考却完全失去区分度甚至反转。"),
            TR("这种跨年代反转说明，老热股偏好只是市场短期风格投影，绝非稳固结构壁垒。"),
        ]),
        P([TR("四、六策略单兵重排实测：误杀大牛股且过拟合风险高企", bold=True)]),
        B([
            TR("六套策略各测试一百一十六套老热股加减分重排，结果全部不建议替换原版。", background_color=3),
            TR("一进二加入三重老油条扣分后，表面看似能躲坑。"),
            TR("它踢掉了远大智能（002689），避开 -6.78% 亏损。"),
            TR("但它同时误杀大牛股华银电力（600744），白丢 +21.74% 大肉。"),
            TR("新换进的票反而平均亏损 -4% 左右。"),
            TR("一进二近两年净值从 41.75 倍跌到 30.84 倍。"),
        ]),
        B([
            TR("二进三给跨六个以上题材的万能马甲扣分，看似也很诱人。"),
            TR("表面上它避开了东易日盛（002713）的 -10.47% 亏损。"),
            TR("也顺带躲开了 ST云网（002306）和 ST惠程（002168）等雷票。"),
            TR("但在 2026 年盲考中，它把大牛股会稽山（601579）踢出局。"),
            TR("只这一刀就白丢 +33.27% 主升肉。"),
            TR("结果近两年净值从 4.55 倍摔到 3.92 倍，过拟合风险超 61%。"),
        ]),
        B([
            TR("其余四套策略也存在同样的局部幻觉。", bold=True),
            TR("三进四给沉睡九十天老妖加分，盲考却接盘亏损票。"),
            TR("圣龙股份（603178）和立方制药（003020）双双大亏 -15% 以上。"),
            TR("高标首阴与 20cm深水虽在近两年小幅领先，但统计差距远没到可靠门槛。"),
            TR("且 20cm深水扣分方案的过拟合风险高达 81.4%。"),
            TR("为一点微弱样本波动冒这么高风险，完全划不来。"),
        ]),
        P([TR("五、现役合体大考与实盘容错红线", bold=True)]),
        O([
            TR("现役全套合体两百七十八笔五年复利达 6913 万倍。", background_color=3),
            TR("就算去掉前三名大牛股，净值依然还有 599.9 万倍。"),
            TR("若强挂全部历史胜出的老热股规则，近两年盲考净值腰斩。"),
            TR("具体来说，盲考净值从 1952.5 倍摔到只剩 944.2 倍。"),
            TR("它直接误杀了神剑股份（002361），白丢 +59.10% 主升。"),
            TR("同时挤掉山东玻纤（605006）的 +28.99% 和万邦医药的 +29.56%。"),
            TR("而新补进的 *ST九鼎（600053）反而亏损 -8.40%。"),
        ], seq="1"),
        O([
            TR("就算只挂高标与 20cm深水两项微调，近两年净值也仅多 2.9%。"),
            TR("多轮打散重排显示，合体强挂的过拟合风险高达 65.7% 至 74.6%。"),
            TR("按单笔一千万资金规模测算冲击成本，现役原版仍有二十八倍以上的成本安全垫。"),
            TR("实盘只需紧盯现役滚动红线：连续七笔以上连亏或二十笔胜率低于 35% 再触发预警。"),
        ], seq="auto"),
        P([TR("六、《临时策略：五板》（2026年7月起）独立观察", bold=True)]),
        B([
            TR("《临时策略：五板》严格隔离在 2026年7月8日 至 11月24日 区间独立评估。", background_color=3),
            TR("共出现四十五条信号，按规则选中三十六笔，目前已了结三十四笔，胜率达 73.53%。"),
            TR("单笔均收 +5.35%，中位数 +9.25%，按日复利 +255.72%。"),
            TR("同期顺位第一单仓赚了 +99.41%，显著跑赢下跌的沪深300。"),
            TR("另有真视通（002771）与盛剑科技（603324）两笔尚未了结。"),
            TR("中京电子（002579）则刚触发次日待观察信号。"),
        ]),
        B([
            TR("临时五板选手自带深厚老热股血统，内部用常规热度筛选反而看不出明显差距。", background_color=3),
            TR("这批标的近三年大涨波段中位数八次，活跃年份五年，涨停数中位数十八点五次。"),
            TR("真正能拉开盈亏的指标，是过往三连板以上妖股基因。"),
            TR("有过多次三连板前科的组，胜率高达 87.5%，单笔均收 +14.43%。"),
            TR("大赚代表如开开实业（600272）收获 +34.21%。"),
            TR("大业股份（603278）收获 +25.76%。"),
            TR("国芳集团（601086）也收获 +24.06%。"),
            TR("大亏雷区有大东方（600327）的 -34.45% 与日出东方的 -28.88%。"),
            TR("因目前已了结样本仅三十四笔且赔率偏低仅 0.78，临时五板暂定只看不上实盘。", background_color=3),
        ]),
        BL(), BL(), BL(),
    ]

    t1 = [
        row(["代表股票", "上市天数与近三年波段", "社区热度与题材跨度", "当前状态与角色"], bold=True),
        row(["金牛化工（600722）", "6962天 / 11波36板", "前14% / 主线占94.7%", "休眠34天再启动"]),
        row(["青山纸业（600103）", "6980天 / 8波24板", "第49分位 / 跨5题材", "休眠10天社区冷清"]),
        row(["九阳股份（002242）", "4457天 / 6波16板", "前2% / 跨3题材", "连板新高瞬间引爆"]),
        row(["中京电子（002579）", "3502天 / 12波34板", "前23% / 跨9题材6坑", "老油条五板待观察"]),
        row(["昂瑞微（688790）", "171天 / 0波0板", "冷门前25% / 无题材史", "纯新票对照样本"]),
        row(["联讯仪器（688808）", "70天 / 0波0板", "冷门前25% / 无题材史", "纯新票对照样本"]),
    ]

    t2 = [
        row(["策略与检验维度", "真实形态与分档差异", "跨期与纠偏表现", "单策略裁决"], bold=True),
        row(["一进二社区热度", "温热二档+18% 网红仅+1.9%", "纠偏淘汰 盲考掉11倍", "维持原版"], bold=True),
        row(["二进三题材跨度", "跨多题材误杀会稽山+33%", "纠偏淘汰 过拟合超61%", "维持原版"], bold=True),
        row(["三进四沉睡天数", "熊市专一优 盲考完全反转", "盲考踩中双 -15% 大亏", "维持原版"], bold=True),
        row(["高标首阴题材专一", "纠偏淘汰 仅多补进2笔", "样本过小 未达可靠门槛", "暂不改动"], bold=True),
        row(["翘板回撤深度", "深跌超-50%均收+8.54%", "仅26笔盲考且未改善单仓", "维持原版"], bold=True),
        row(["20cm深水冷却期", "新票与30天内热票最优", "近两年过拟合风险81%", "维持原版"], bold=True),
    ]

    t3 = [
        row(["合体测试方案", "全五年复利 / 最大回撤", "近两年盲考 / 2026年", "换票关键得失与裁决"], bold=True),
        row(["现役原版六策略", "6913万倍 / 47.32%", "1952.5倍 / 27.78倍", "保留神剑华银 维持原版"], bold=True),
        row(["全挂历史胜出规则", "6360万倍 / 44.58%", "944.2倍 / 15.50倍", "误杀神剑+59% 净值腰斩"], bold=True),
        row(["仅挂双期过关两项", "7382万倍 / 47.32%", "2010.2倍 / 28.60倍", "仅多2.9% 不足以改动"], bold=True),
        row(["挂入三进四沉睡加分", "4510万倍 / 47.32%", "1222.9倍 / 17.40倍", "踩雷圣龙与立方 失血"], bold=True),
        row(["挂入二进三跨度扣分", "6239万倍 / 47.32%", "1451.1倍 / 27.78倍", "误杀神剑 补进ST九鼎"], bold=True),
        row(["挂入一进二油条扣分", "6710万倍 / 44.58%", "1812.4倍 / 24.04倍", "误杀华银电力+21.7%"], bold=True),
    ]

    t4 = [
        row(["临时五板观测指标", "核心分组或代表个股", "胜率与单笔均收", "阶段定位与结论"], bold=True),
        row(["全部已完结(34笔)", "2026.07至11月区间", "胜73.53% / 均收+5.35%", "按日复利+255.7%"]),
        row(["多次三连板妖股组", "历史三连板波段较多", "胜87.50% / 均收+14.43%", "明显强于少连板组"], bold=True),
        row(["少三连板普通组", "历史三连板波段偏少", "胜69.23% / 均收+2.56%", "赔率偏低仅 0.70"]),
        row(["典型大赚代表", "开开实业 / 大业股份", "收获+34.21% / +25.76%", "国芳深中华均超+20%"]),
        row(["典型大亏雷区", "大东方 / 日出东方", "亏损-34.45% / -28.88%", "样本仅34笔暂不实盘"], bold=True),
    ]

    return {
        "title": TITLE_RD030,
        "parent_node_token": I_NODE,
        "blocks": blocks,
        "img_path": c1_path,
        "img_path2": c2_path,
        "tables": [
            ("表一：六大维度测试底座四只典型老热股与两只新票画像对照", t1),
            ("表二：六大短线策略老热股特征非线性规律与单兵重排裁决", t2),
            ("表三：现役合体两百七十八笔全套大考与强挂规则盲考对比", t3),
            ("表四：《临时策略：五板》（2026年7月起）独立观测明细", t4),
        ],
    }


def build_updated_invalid_hub():
    # 保留在线既有全部 12 项，并将《老热股六策略实证》插在最上方（共 13 项）
    invalid_rows = [
        ("老热股六策略实证", "5年六策略及五板", "多重纠偏后有效极少，强加换票近两年净值腰斩", "全六策略维持原版，五板暂作独立观察"),
        ("中国周期与六策略体检", "5年278笔6策略", "35项周期检验FDR均>0.83，外挂开关全跑输满仓", "现役体系自带抗周期，勿加开关"),
        ("卡30天200%异动第30与31天证伪", "6年48因子", "D30尾买隔夜胜16%，418组0过红队六关", "作老仓兑现窗，禁接盘二波"),
        ("四进五 V2.0 (下放淘汰)", "五年全量", "去前三大妖股独立净值仅 0.89x", "依赖少数极值，移出实盘"),
        ("大跌切银行与退潮切消费证伪", "五年全量", "退潮切白酒胜36.8%，生猪22.7%亏-2.04%", "严禁科技退潮买消费避险"),
        ("十年暴涨暴跌反抽证伪", "10年/5年", "9套急跌抄底与反抽规则全灭，亏至-93%以上", "永久禁做A杀反抽"),
        ("行业明牌大高潮追买证伪", "8年661次", "大高潮买中军日内亏-0.64%，领涨亏-1.51%", "纯A独立高潮高开禁追"),
        ("热门题材200亿大中军证伪", "5年28740组", "三轨全证伪，热门题材买200亿大中军亏钱", "禁追热门题材大中军"),
        ("大池子妖股暴跌反核证伪", "5年171组", "仅2.3%三期全正，去前5亏-35.08%", "永久禁做大池子反核"),
        ("雪球短线大V三年胜率证伪", "122位大V", "粉丝数与赚钱倒挂，超8成扣费亏钱", "严禁盲跟雪球高频复盘号"),
        ("连板晋级率与冰点抄底证伪", "5年1211日", "高晋级率不超19天，追高抄冰点双亏", "禁用晋级率盲抄冰点"),
        ("庄股事前可预测性证伪", "421只庄股", "横盘缩量找庄股样本外全灭，与随机无异", "永久放弃事前猜庄股"),
        ("电竞夺冠事件追涨证伪", "2022至2026", "电竞夺冠无产业增量，次日追涨必亏", "纯情绪事件禁追高"),
    ]
    return build_hub_doc("证伪回测与避坑墓碑", "结论：本目录收录6大主力策略之外已证伪小策略与亏钱陷阱，永久避坑防复燃。", invalid_rows)


def audit_rd030_extra_banned(txt: str, loc: str):
    for w in RD030_EXTRA_BANNED:
        if re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", txt) if w.isascii() else (w in txt):
            raise ValueError(f"[{loc}] 发现 RD030 禁用黑话或统计缩写 '{w}': {txt}")


def audit_rd030_full(d: dict):
    s9.check_first_sentence_rule(d)
    longs = s9.audit_doc_strict_v191(d, require_img=True)
    if longs:
        raise ValueError(f"存在超40字长句 ({len(longs)}条)")
    for idx, b in enumerate(d["blocks"]):
        bt = b["block_type"]
        els = b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", [])
        for e in els:
            audit_rd030_extra_banned(e["text_run"]["content"], f"正文块{idx+1}")
    for t_title, rows in d["tables"]:
        audit_rd030_extra_banned(t_title, f"表标题-{t_title}")
        for r_i, rw in enumerate(rows):
            for c_i, cell in enumerate(rw):
                audit_rd030_extra_banned("".join(x for x, _ in cell), f"{t_title}-R{r_i}C{c_i}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    w2a = json.loads((OUT_DIR / "wave2a_6strat_oldhot_matrix.json").read_text(encoding="utf-8"))
    w2b = json.loads((OUT_DIR / "wave2b_rerank_v20_jianyan.json").read_text(encoding="utf-8"))

    c1_path, c2_path = generate_charts(w2a, w2b)
    print(f"[Charts] Generated {c1_path} & {c2_path}")

    d = build_rd030_payload(c1_path, c2_path)
    hub_i = build_updated_invalid_hub()

    audit_rd030_full(d)
    longs_hub = s9.audit_doc_strict_v191(hub_i, require_img=False)
    if longs_hub:
        raise ValueError(f"Hub 存在超40字长句: {len(longs_hub)}")

    tot_chars = sum(len(e["text_run"]["content"]) for b in d["blocks"] for e in b.get("text", b.get("bullet", b.get("ordered", {}))).get("elements", []))
    tot_chars += sum(len(t) for t, _ in d["tables"])
    tot_chars += sum(len("".join(x for x, _ in cell)) for _, rows in d["tables"] for rw in rows for cell in rw)
    print(f"[Audit] RD030 local total chars = {tot_chars} (>= 2000 required)")
    if tot_chars < 2000:
        raise ValueError(f"RD030 total chars {tot_chars} < 2000")

    if args.dry_run:
        print("[Dry-Run PASS] Zero audit errors on RD030 & Invalid Hub!")
        return

    lock_fd = open(s6.LOCK_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        doc_id, node_tok = s9.find_or_create_child_node(I_NODE, TITLE_RD030)
        if doc_id in s6.PROTECTED_DOCS:
            raise RuntimeError(f"Protected: {doc_id}")
        _, fail = s6.write_document_payload(doc_id, d["blocks"], d["tables"], d["img_path"])
        if fail > 0:
            raise RuntimeError(f"Write failed: {fail}")
        if not s6.insert_image_block(doc_id, d["img_path2"]):
            raise RuntimeError("Second image upload failed")
        s6.api(
            f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            {"children": [BL(), BL(), BL()], "index": -1},
            "POST",
        )
        time.sleep(1.5)
        v = s9.verify_document_v191(doc_id, TITLE_RD030, expected_tables_count=len(d["tables"]), has_img=True)

        # 在线回读全量违禁词再审一次
        r_raw = s6.api(f"{s6.BASE}/open-apis/docx/v1/documents/{doc_id}/raw_content", method="GET")
        raw_content = r_raw.get("data", {}).get("content", "")
        lines = [ln.strip() for ln in raw_content.splitlines() if ln.strip()]
        body_text = "\n".join(lines[1:]) if len(lines) > 1 else raw_content
        audit_rd030_extra_banned(body_text, "在线回读-RD030")
        if len(raw_content) < 2000:
            raise ValueError(f"Online raw_chars {len(raw_content)} < 2000")

        url = f"https://my.feishu.cn/wiki/{node_tok}"

        _, fail2 = s6.write_document_payload(I_DOC, hub_i["blocks"], hub_i["tables"], None)
        if fail2 > 0:
            raise RuntimeError(f"Hub write fail={fail2}")
        time.sleep(1.2)
        vhub = s9.verify_document_v191(I_DOC, "证伪回测与避坑墓碑", expected_tables_count=1, has_img=False)

        mf = json.load(open(s6.MANIFEST_PATH, "r", encoding="utf-8"))
        mf.setdefault("nodes", {})["rd030_old_hot_stock_6strat"] = {
            "title": TITLE_RD030,
            "node_token": node_tok,
            "obj_token": doc_id,
            "parent_node_token": I_NODE,
            "wiki_url": url,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        json.dump(mf, open(s6.MANIFEST_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

        pub_res = {
            "wiki_url": url,
            "node_token": node_tok,
            "doc_id": doc_id,
            "parent_node_token": I_NODE,
            "verify": v,
            "hub_verify": vhub,
        }
        with open(OUT_DIR / "feishu_publish_result.json", "w", encoding="utf-8") as f:
            json.dump(pub_res, f, ensure_ascii=False, indent=2)
        print(f"[SUCCESS] RD030 URL={url} | chars={v['raw_chars']} | tables={v['tables_count']} | images={v['images_count']}")
        print(f"[SUCCESS] INVALID HUB URL=https://my.feishu.cn/wiki/{I_NODE} | chars={vhub['raw_chars']}")
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()

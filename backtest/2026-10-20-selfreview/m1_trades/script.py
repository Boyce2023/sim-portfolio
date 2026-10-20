#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股模拟盘自我复盘 — 2026-10-20
只读分析脚本: 不写 portfolio_state.json / 不下单 / 不改 sim-portfolio 任何既有文件。
输出: round_trips.csv, summary.md (均在本脚本同目录)

数据源:
  - portfolio_state.json: trade_log(account=a_share), accounts.a_share
  - data/cn_hk_price_db/a_daily.parquet: 本地A股日线(2026-10-19收盘前覆盖)
  - market_calendar.json: 交易日历

口径说明见 summary.md 开头"方法与口径"一节。
"""
import json
import os
import sys
import datetime
from collections import defaultdict

import pandas as pd
import numpy as np

BASE = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio"
OUT = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-10-20-selfreview/m1_trades"
sys.path.insert(0, os.path.join(BASE, "scripts"))
import astock_rules as R  # noqa: E402  (项目既有规则模块, 只读使用, 取 board()/exchange())

PARQUET = os.path.join(BASE, "data", "cn_hk_price_db", "a_daily.parquet")

# ══════════════════════════════════════════════════════════════
# 0. 基础数据加载
# ══════════════════════════════════════════════════════════════
with open(os.path.join(BASE, "portfolio_state.json")) as f:
    PS = json.load(f)

with open(os.path.join(BASE, "market_calendar.json")) as f:
    MC = json.load(f)
CLOSED_DATES = set(MC["trading_days_by_market"]["cn_closed_dates"])

trade_log = PS["trade_log"]
a_share_all = [t for t in trade_log if t.get("account") == "a_share"]
print(f"[诊断] trade_log 总条数 {len(trade_log)}, account=a_share 条数 {len(a_share_all)}")

# --- 剔除非决策条目 ---
# TRD-0497(单测:不会真执行,只看价格路径) + TRD-0498(冲销误执行,恢复至误操作前的13700股)
# 二者是09-07同一笔"验证新通道时误用真实持仓下单→用反向单冲销"的操作, 净效果是仓位不变
# 但留下一笔-394.18元的真实已实现亏损(100股北方稀土 38.67卖/38.59买回, 含手续费)。
# 这394.18元已经算在 accounts.a_share.realized_pnl 里, 但不代表任何投资判断, 从决策分析中剔除,
# 在对账里单独注明。
WASH_IDS = {"TRD-0497", "TRD-0498"}
decision_trades = [t for t in a_share_all if t["id"] not in WASH_IDS]
decision_trades.sort(key=lambda x: x["timestamp"])
print(f"[诊断] 剔除单测/冲销误执行(TRD-0497/0498)后决策条目 {len(decision_trades)} 条")

# --- B策略专户(丁组): 只认reason含"B策略专户"的两笔 ---
B_IDS = {t["id"] for t in decision_trades if "B策略专户" in (t.get("reason") or "")}
print(f"[诊断] B策略专户(丁组)交易: {sorted(B_IDS)}")

# --- 09-17 Buwen清仓重建令(乙组): reason含"策略体系变更清仓"的sell ---
LIQ_IDS = {t["id"] for t in decision_trades if "策略体系变更清仓" in (t.get("reason") or "")}
print(f"[诊断] 09-17清仓重建(乙组)交易: {sorted(LIQ_IDS)} 共{len(LIQ_IDS)}笔")

MAIN_TRADES = [t for t in decision_trades if t["id"] not in B_IDS]
B_TRADES = [t for t in decision_trades if t["id"] in B_IDS]

# ══════════════════════════════════════════════════════════════
# 1. 交易日历: 以本地价格库000001.SZ的实际bar日期为准(已核对与market_calendar一致)
# ══════════════════════════════════════════════════════════════
_cal_df = pd.read_parquet(PARQUET, filters=[("ticker", "=", "000001.SZ")])
TRADING_DAYS = sorted(_cal_df["date"].dt.strftime("%Y-%m-%d").tolist())
TRADING_DAYS = [d for d in TRADING_DAYS if d >= "2026-04-01"]  # 截取够用的区间, 省内存
TD_INDEX = {d: i for i, d in enumerate(TRADING_DAYS)}
print(f"[诊断] 交易日历 {TRADING_DAYS[0]} 至 {TRADING_DAYS[-1]}, 共{len(TRADING_DAYS)}个交易日")


def td_offset(date_str, n):
    """date_str往后数n个交易日的日期字符串; 超出已知范围返回None"""
    if date_str not in TD_INDEX:
        # 找到 date_str 当天或之后最近的交易日作为基准(处理非交易日挂的单)
        later = [d for d in TRADING_DAYS if d >= date_str]
        if not later:
            return None
        base_i = TD_INDEX[later[0]]
    else:
        base_i = TD_INDEX[date_str]
    j = base_i + n
    if j < 0 or j >= len(TRADING_DAYS):
        return None
    return TRADING_DAYS[j]


def td_count_between(d0, d1):
    """d0到d1之间的交易日步数(d1的索引-d0的索引), d0/d1须在TD_INDEX中"""
    if d0 not in TD_INDEX or d1 not in TD_INDEX:
        return None
    return TD_INDEX[d1] - TD_INDEX[d0]


# ══════════════════════════════════════════════════════════════
# 2. 价格读取: ticker(裸代码) -> DataFrame(date,open,high,low,close,adj_close,amount,turn)
# ══════════════════════════════════════════════════════════════
_price_cache = {}


def exch_ticker(bare):
    """裸代码 -> 价格库格式代码(加.SH/.SZ/.BJ后缀), 用项目既有astock_rules.exchange()判断"""
    ex = R.exchange(bare)
    suf = {"sh": ".SH", "sz": ".SZ", "bj": ".BJ"}[ex]
    return f"{bare}{suf}"


def get_price_df(bare_ticker):
    if bare_ticker in _price_cache:
        return _price_cache[bare_ticker]
    full = exch_ticker(bare_ticker)
    df = pd.read_parquet(PARQUET, filters=[("ticker", "=", full)])
    df = df.sort_values("date").reset_index(drop=True)
    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df.set_index("date_str")
    _price_cache[bare_ticker] = df
    return df


def close_on(bare_ticker, date_str, col="close"):
    df = get_price_df(bare_ticker)
    if date_str in df.index:
        v = df.loc[date_str, col]
        return float(v) if pd.notna(v) else None
    return None


print("[诊断] 价格读取函数就绪, 准备处理的ticker数(主账户+B):",
      len(set(t["ticker"] for t in MAIN_TRADES)) + len(set(t["ticker"] for t in B_TRADES)))

# ══════════════════════════════════════════════════════════════
# 3. 卖出理由分类
#    人工逐条读了全部135笔主账户非强制清仓sell的reason原文后定的关键词与例外名单,
#    不是单靠关键词正则——几处关键词会命中但语义不对的, 用显式ID名单纠正(见下方注释)。
# ══════════════════════════════════════════════════════════════

# --- Buwen明确下令的清仓/卖出(按原文逐条核实, 非仅因提到"Buwen"字样) ---
# 09-17 "直接把现在的仓位重建掉"(乙组,9笔) 已在LIQ_IDS
# 07-24 Buwen令当日清仓(按07-24收盘价), 实际记录在07-29(4笔): 688617/000708/002895/688293
BUWEN_0729_IDS = {"TRD-0338", "TRD-0339", "TRD-0340", "TRD-0341"}
# 08-07 11:07 Buwen直接指令"把所有股都卖了,重新选股买入"(8笔)
BUWEN_0807_IDS = {"TRD-0378", "TRD-0379", "TRD-0380", "TRD-0381",
                   "TRD-0382", "TRD-0383", "TRD-0384", "TRD-0385"}
# 10-08 Buwen指出我09-29自加"拆半试验"偏离他的T+5规则, 当场纠正执行全额清仓(2笔)
BUWEN_1008_IDS = {"TRD-0534", "TRD-0535"}
BUWEN_SELL_IDS = LIQ_IDS | BUWEN_0729_IDS | BUWEN_0807_IDS | BUWEN_1008_IDS
# 注意: TRD-0491(药明康德,09-03)原文提到"Buwen 09-03令: 划30%NAV给B", 但那条令是"给B账户
# 划多少钱"的资金量指令, 不是"卖药明康德"的指令——卖哪只股票是我的判断, 故不计入BUWEN_SELL_IDS。

MECH_STOP_KEYS = ["灾难线", "T18", "破X1", r"X1\(", "X1=", "硬止损", "止损触发",
                  "跌破.*7%", "破前10日低", "strategy1_exit", "7%到8%收盘止损",
                  "跌破买价", "破位", "预设扳机", "预设线", "链级扳机", "跌破stop_loss",
                  "破自主扳机线"]
TIME_EXPIRY_KEYS = ["T+5", "T+4", "T+3", "到期", "Day3卖出", "持有期到期"]
# 判断型(默认桶): 只要不是机械价格触发/不是时间到期/不是Buwen直接下令/不是B的量价规则,
# 就属于"我的主观判断"——下面的子标签只是给这个大桶里细分"哪一种判断", 不改变大类归属。
JUDGMENT_SUB_KEYS = [
    ("thesis证伪/三问/主beta", ["thesis证伪", "thesis三问", "主beta", "三问", "基本面拐点",
                                "铁律1", "铁律2", "大beta重构", "thesis错误", "thesis根本性错误",
                                "证伪", "竞争加剧", "个股利空", "用户确认彻底错误"]),
    ("催化剂已兑现/已过", ["催化剂已过", "催化剂兑现", "催化剂落地"]),
    ("T11动量止盈(非止损,主观决定减多少)", ["T11"]),
    ("机会成本/资金腾挪", ["机会成本", "龙头滞涨", "资金流失", "仓位错配", "簇预设失效",
                          "释放资金"]),
    ("仓位/集中度合规", ["集中度", "仓位限制", "合规水位", "超配", r"超.*上限"]),
    ("自主组合重建(非Buwen令)", ["全面重建", "重置到周五白纸", "清仓重置"]),
    ("建仓错误问责(承认sizing错误)", ["收敛感受仓纠错", "对建仓决策错误负责", "防守收敛"]),
    ("非核心持仓清理", ["清非核心", "不在产品树"]),
    ("扫描未重现/Agent未入围(T14铁律生效前的旧理由)", ["扫描未重现", "扫描未入围", "降2档", "降档"]),
    ("其他主观判断(未细分)", []),  # 兜底, 永远匹配
]


def classify_sell(t):
    """返回 (大类, 子标签). 大类=机械止损/时限到期/判断型/Buwen命令清仓/B规则卖出(5类无"其他")。
    判断型是默认桶: 排除掉机械/到期/Buwen令/B规则之后剩下的全部归入判断型, 用子标签区分哪种判断。"""
    tid = t["id"]
    r = t.get("reason") or ""
    if tid in BUWEN_SELL_IDS:
        return ("Buwen命令清仓", "")
    if tid in B_IDS:
        return ("B规则卖出", "")
    import re
    for k in MECH_STOP_KEYS:
        if re.search(k, r):
            return ("机械止损", k)
    for k in TIME_EXPIRY_KEYS:
        if k in r:
            return ("时限到期", k)
    for label, keys in JUDGMENT_SUB_KEYS:
        if not keys:
            return ("判断型", label)
        for k in keys:
            if re.search(k, r):
                return ("判断型", label)
    return ("判断型", "其他主观判断(未细分)")


# ══════════════════════════════════════════════════════════════
# 4. FIFO episode(round trip)构建: ticker -> 从0到0的完整持有周期
# ══════════════════════════════════════════════════════════════
def build_episodes(trades, tag_fn=None):
    by_ticker = defaultdict(list)
    for t in trades:
        by_ticker[t["ticker"]].append(t)
    episodes = []
    for tk, tks in by_ticker.items():
        tks = sorted(tks, key=lambda x: x["timestamp"])
        name = tk
        for t in tks:
            nm = t.get("name")
            if nm and not str(nm).isdigit() and nm != tk:
                name = nm
        pos = 0.0
        cur = None
        for t in tks:
            if t["action"] not in ("buy", "sell"):
                continue
            sh = float(t["shares"])
            if t["action"] == "buy":
                if pos == 0:
                    cur = {"ticker": tk, "name": name, "buys": [], "sells": []}
                cur["buys"].append(t)
                pos += sh
            else:
                if cur is None:
                    print(f"[警告] {tk} {t['id']} 卖出但找不到对应买入episode, 跳过")
                    continue
                cur["sells"].append(t)
                pos -= sh
            if cur is not None and abs(pos) < 1e-6 and (cur["buys"] or cur["sells"]):
                cur["is_open"] = False
                episodes.append(cur)
                cur = None
        if cur is not None:
            cur["is_open"] = True
            episodes.append(cur)
    return episodes


def fee_of(t):
    return float(t.get("fee", 0) or 0)


def enrich_episode(ep):
    buys, sells = ep["buys"], ep["sells"]
    shares_buy = sum(b["shares"] for b in buys)
    shares_sell = sum(s["shares"] for s in sells)
    cost = sum(b["shares"] * b["price"] + fee_of(b) for b in buys)
    proceeds = sum(s["shares"] * s["price"] - fee_of(s) for s in sells)
    ep["shares_buy"] = shares_buy
    ep["shares_sell"] = shares_sell
    ep["cost"] = cost
    ep["proceeds"] = proceeds
    ep["avg_buy_price"] = sum(b["shares"] * b["price"] for b in buys) / shares_buy if shares_buy else None
    ep["avg_sell_price"] = sum(s["shares"] * s["price"] for s in sells) / shares_sell if shares_sell else None
    ep["first_buy_date"] = buys[0]["date"] if buys else None
    ep["last_buy_date"] = buys[-1]["date"] if buys else None
    ep["last_sell_date"] = sells[-1]["date"] if sells else None
    ep["sum_logged_realized_pnl"] = sum(s.get("realized_pnl", 0) or 0 for s in sells)
    if ep["is_open"]:
        cur_px = close_on(ep["ticker"], TRADING_DAYS[-1], "close")
        ep["pnl"] = (shares_buy - shares_sell) * (cur_px if cur_px else ep["avg_buy_price"]) + proceeds - cost
        ep["holding_days"] = td_count_between(ep["first_buy_date"], TRADING_DAYS[-1])
    else:
        ep["pnl"] = proceeds - cost
        ep["holding_days"] = td_count_between(ep["first_buy_date"], ep["last_sell_date"])
    ep["return_pct"] = ep["pnl"] / cost * 100 if cost else None
    # 卖出理由分类: 取episode里"主导"的那一笔卖出分类(多数episode只有1-2笔sell;
    #   若跨多类, 记录全部并以金额最大的那笔卖出作为episode主分类)
    if sells:
        classified = [(s, *classify_sell(s)) for s in sells]
        classified.sort(key=lambda x: -(x[0]["shares"] * x[0]["price"]))
        ep["sell_category"] = classified[0][1]
        ep["sell_subtag"] = classified[0][2]
        ep["sell_categories_all"] = sorted(set(c[1] for c in classified))
    else:
        ep["sell_category"] = "未平仓"
        ep["sell_subtag"] = ""
        ep["sell_categories_all"] = []
    return ep


MAIN_EPISODES = [enrich_episode(e) for e in build_episodes(MAIN_TRADES)]
B_EPISODES = [enrich_episode(e) for e in build_episodes(B_TRADES)]
print(f"[诊断] 主账户episode(round trip)数 = {len(MAIN_EPISODES)} (含未平仓)")
print(f"[诊断] B账户(丁组)episode数 = {len(B_EPISODES)}")

# --- 期别归类 ---
def period_of(ep):
    if ep["is_open"]:
        return "持仓中"
    sell_ids = {s["id"] for s in ep["sells"]}
    if sell_ids & LIQ_IDS:
        return "乙"
    if ep["first_buy_date"] and ep["first_buy_date"] >= "2026-09-21":
        return "丙"
    return "甲"


for ep in MAIN_EPISODES:
    ep["period"] = period_of(ep)
for ep in B_EPISODES:
    ep["period"] = "丁"

from collections import Counter
print("[诊断] 期别分布:", Counter(ep["period"] for ep in MAIN_EPISODES))

# --- 对账: 我的FIFO/episode算出的已实现盈亏 vs SSOT realized_pnl ---
closed_main = [e for e in MAIN_EPISODES if not e["is_open"]]
my_realized_main = sum(e["pnl"] for e in closed_main)
logged_realized_main = sum(e["sum_logged_realized_pnl"] for e in closed_main)
b_realized = sum(e["pnl"] for e in B_EPISODES if not e["is_open"])
wash_pnl = sum((t.get("realized_pnl", 0) or 0) for t in a_share_all if t["id"] in WASH_IDS)
ssot_realized = PS["accounts"]["a_share"]["realized_pnl"]

print()
print("=" * 70)
print("[对账] 我的episode法已实现盈亏(主账户,不含B不含wash) =", round(my_realized_main, 2))
print("[对账] trade_log里sell.realized_pnl字段之和(同范围)     =", round(logged_realized_main, 2))
print("[对账] B账户(丁组)已实现盈亏                              =", round(b_realized, 2))
print("[对账] 单测/冲销误执行(wash,已剔除出决策分析)已实现盈亏   =", round(wash_pnl, 2))
print("[对账] 三者相加                                           =",
      round(my_realized_main + b_realized + wash_pnl, 2))
print("[对账] SSOT accounts.a_share.realized_pnl                =", round(ssot_realized, 2))
print("[对账] 差额(SSOT - 三者相加)                              =",
      round(ssot_realized - (my_realized_main + b_realized + wash_pnl), 2))
print("=" * 70)

# --- 诊断: 找出我的episode pnl 与 logged realized_pnl 差异最大的几笔, 排查原因 ---
diag = []
for e in closed_main:
    diff = e["pnl"] - e["sum_logged_realized_pnl"]
    diag.append((abs(diff), diff, e["ticker"], e["name"], e["period"],
                 e["pnl"], e["sum_logged_realized_pnl"],
                 [s["id"] for s in e["sells"]], [b["id"] for b in e["buys"]]))
diag.sort(key=lambda x: -x[0])
print("[诊断] 差异最大的10个episode (我的pnl vs logged realized_pnl之和):")
for row in diag[:10]:
    print(f"  {row[2]} {row[3]} period={row[4]} 我的pnl={row[5]:.1f} logged={row[6]:.1f} diff={row[1]:.1f} sells={row[7]} buys={row[8]}")

# --- 检查有没有sell完全缺realized_pnl字段 ---
no_rpnl = [t for t in MAIN_TRADES if t["action"] == "sell" and "realized_pnl" not in t]
print(f"[诊断] 主账户sell交易中完全没有realized_pnl字段的: {len(no_rpnl)}笔")
for t in no_rpnl[:20]:
    print("   ", t["id"], t["date"], t["ticker"], t.get("name"), t["shares"], t["price"])

print()
print("[诊断] 全部97个episode按|diff|排序(确认002025是否是唯一异常):")
print(f"  episode总数={len(diag)}, |diff|>100的episode数={sum(1 for d in diag if d[0]>100)}")
s_all = sum(d[1] for d in diag)
s_ex_002025 = sum(d[1] for d in diag if d[2] != '002025')
print(f"  全部diff求和={s_all:.1f}; 剔除002025后diff求和={s_ex_002025:.1f}")
total_buy_fee = sum(fee_of(b) for e in closed_main for b in e['buys'])
total_sell_fee = sum(fee_of(s) for e in closed_main for s in e['sells'])
print(f"  closed_main全部买入fee合计={total_buy_fee:.1f}; 卖出fee合计={total_sell_fee:.1f}")
print(f"  剔除002025后diff求和 的绝对值 应约等于 全部买入fee合计(若logged口径的成本不含买入fee): "
      f"{s_ex_002025:.1f} vs {-total_buy_fee:.1f}")

# --- 更细: 对"仅一笔买入"的episode, 逐笔sell的implied cost basis必须严格等于那一笔买入价
#     (无FIFO/加权平均歧义, 任何偏离都是系统记账问题, 不是口径差异) ---
print()
print("[诊断] 单一买入批次episode的逐笔implied cost basis核对(偏离说明记账异常, 非口径差异):")
anomaly_total = 0.0
for e in closed_main:
    if len(e["buys"]) != 1:
        continue
    buy_px = e["buys"][0]["price"]
    for s in e["sells"]:
        implied_cost = (s["shares"] * s["price"] - fee_of(s) - (s.get("realized_pnl", 0) or 0)) / s["shares"]
        gap = implied_cost - buy_px
        if abs(gap) > 0.02:  # 容忍2分钱的四舍五入
            extra_pnl = gap * s["shares"]  # 这一笔因implied cost偏离买入价而"多出"的pnl(正=虚增盈利)
            anomaly_total += extra_pnl
            print(f"  {e['ticker']}{e['name']} 买入价{buy_px} sell={s['id']}({s['date']}) "
                  f"implied_cost={implied_cost:.3f} 偏离={gap:.3f}/股 "
                  f"虚增pnl≈{extra_pnl:.1f}")
print(f"  单一买入批次episode里, 因implied cost偏离买入价而虚增的pnl合计 ≈ {anomaly_total:.1f}")

# ══════════════════════════════════════════════════════════════
# 5. 期别(甲/乙/丙/丁)汇总统计
# ══════════════════════════════════════════════════════════════
ALL_CLOSED = closed_main + [e for e in B_EPISODES if not e["is_open"]]


def period_stats(eps):
    n = len(eps)
    if n == 0:
        return None
    wins = [e for e in eps if e["pnl"] > 0]
    rets = [e["return_pct"] for e in eps if e["return_pct"] is not None]
    pnls = [e["pnl"] for e in eps]
    worst5 = sorted(eps, key=lambda e: e["pnl"])[:5]
    return {
        "n": n,
        "win_rate": len(wins) / n * 100,
        "mean_ret_pct": float(np.mean(rets)) if rets else None,
        "median_ret_pct": float(np.median(rets)) if rets else None,
        "total_pnl": sum(pnls),
        "mean_pnl": float(np.mean(pnls)),
        "worst5": [(e["ticker"], e["name"], e["pnl"], e["return_pct"],
                    e["first_buy_date"], e["last_sell_date"],
                    e["sell_category"]) for e in worst5],
    }


print()
print("=" * 70)
print("[分期统计] 甲(05-18~09-16旧体系) / 乙(09-17清仓重建) / 丙(09-21起v14.0策略一) / 丁(B策略专户)")
for pname, eps in [("甲", [e for e in closed_main if e["period"] == "甲"]),
                    ("乙", [e for e in closed_main if e["period"] == "乙"]),
                    ("丙", [e for e in closed_main if e["period"] == "丙"]),
                    ("丁", [e for e in B_EPISODES if not e["is_open"]])]:
    st = period_stats(eps)
    print(f"\n--- {pname}组 n={st['n'] if st else 0} ---")
    if st is None:
        continue
    print(f"  胜率={st['win_rate']:.1f}%  均值收益率={st['mean_ret_pct']:.2f}%  中位收益率={st['median_ret_pct']:.2f}%")
    print(f"  盈亏合计={st['total_pnl']:.1f}元  单笔均值={st['mean_pnl']:.1f}元")
    print("  最大亏损5笔:")
    for w in st["worst5"]:
        print(f"    {w[0]} {w[1]} pnl={w[2]:.1f} ret={w[3]:.2f}% 买{w[4]}~卖{w[5]} 分类={w[6]}")

print()
print("[持仓中] 当前未平仓(以10-19收盘价估值, 浮动盈亏):")
for e in [x for x in MAIN_EPISODES if x["is_open"]]:
    print(f"  {e['ticker']} {e['name']} 买入{e['first_buy_date']} 浮动pnl≈{e['pnl']:.1f} ret≈{e['return_pct']:.2f}%")

# ══════════════════════════════════════════════════════════════
# 6. 卖出理由分类(逐笔, 不是逐episode) + 卖出后price drift
#    (每一笔sell单独分类+单独看drift, 一个episode可能有多笔不同理由的sell,
#     episode层面的"主导分类"只用于round_trips.csv展示, 这里才是point3的权威统计口径)
# ══════════════════════════════════════════════════════════════
ALL_MAIN_SELLS = [t for t in MAIN_TRADES if t["action"] == "sell"]
ALL_B_SELLS = [t for t in B_TRADES if t["action"] == "sell"]
print(f"\n[诊断] 主账户sell总数(含乙组)={len(ALL_MAIN_SELLS)}, B组sell数={len(ALL_B_SELLS)}")

sell_rows = []
for t in ALL_MAIN_SELLS:
    cat, sub = classify_sell(t)
    sell_rows.append({**t, "category": cat, "subtag": sub, "book": "主账户"})
for t in ALL_B_SELLS:
    sell_rows.append({**t, "category": "B规则卖出", "subtag": "", "book": "B专户"})

cat_counter = Counter(r["category"] for r in sell_rows)
print("[诊断] 卖出理由分类分布(逐笔, 含乙含B):", dict(cat_counter))

# 判断型子标签分布 + 未细分兜底的全部明细(人工复核用, 确认没有该归到机械/时限但被判断型兜底吞掉的)
judgment_sub_counter = Counter(r["subtag"] for r in sell_rows if r["category"] == "判断型")
print("\n[诊断] 判断型子标签分布:", dict(judgment_sub_counter))
print("\n[诊断] 判断型/'其他主观判断(未细分)'全部明细(人工复核, 确认不是漏判的机械/时限信号):")
for r in sell_rows:
    if r["category"] == "判断型" and r["subtag"] == "其他主观判断(未细分)":
        print(f"  {r['id']} {r['date']} {r['ticker']}{r.get('name')} | {(r.get('reason') or '')[:60]}")


def drift_for_sell(t):
    """返回 dict: d5,d10,d20 (相对卖出日adj_close的百分比变化), 数据不足处为None"""
    tk = t["ticker"]
    sdate = t["date"]
    base = close_on(tk, sdate, "adj_close")
    out = {}
    for n, key in [(5, "d5"), (10, "d10"), (20, "d20")]:
        fdate = td_offset(sdate, n)
        if base is None or fdate is None:
            out[key] = None
            continue
        fpx = close_on(tk, fdate, "adj_close")
        out[key] = (fpx / base - 1) * 100 if (fpx is not None and base) else None
    return out


for r in sell_rows:
    r["drift"] = drift_for_sell(r)

print("\n[分类x drift] 各类卖出后第5/10/20交易日相对卖出价涨跌(adj_close), 均值/中位/n, 以及'卖早了'(drift>0)占比:")
by_cat = defaultdict(list)
for r in sell_rows:
    by_cat[r["category"]].append(r)
for cat, rows in sorted(by_cat.items(), key=lambda x: -len(x[1])):
    for key in ["d5", "d10", "d20"]:
        vals = [r["drift"][key] for r in rows if r["drift"][key] is not None]
        if not vals:
            print(f"  [{cat}] {key}: 无数据(n=0, 可能是近期卖出数据不足)")
            continue
        mean_v = float(np.mean(vals))
        med_v = float(np.median(vals))
        pct_early = sum(1 for v in vals if v > 0) / len(vals) * 100
        print(f"  [{cat}] {key}: 均值={mean_v:+.2f}% 中位={med_v:+.2f}% n={len(vals)} 卖早了(涨)占比={pct_early:.0f}%")

# ══════════════════════════════════════════════════════════════
# 7. 反事实: 若按现行策略一规则(T=首次买入日, 买入价=当日实际买入价,
#    第4个交易日收盘卖; 期间任一日收盘跌破买价7%则当日收盘卖)执行, 收益是多少
#    只对主账户(甲/乙/丙)做, B账户(丁)是完全不同的量价规则不适用此反事实。
# ══════════════════════════════════════════════════════════════
def counterfactual_t4_stop7(ep):
    tk = ep["ticker"]
    t0 = ep["buys"][0]["date"]
    entry_px = ep["buys"][0]["price"]
    stop_px = entry_px * 0.93
    for n in range(1, 5):  # T+1..T+4
        d = td_offset(t0, n)
        if d is None:
            return {"status": "数据不足", "exit_date": None, "exit_price": None,
                    "ret_pct": None, "exit_reason": None}
        px = close_on(tk, d, "close")
        if px is None:
            return {"status": "数据不足", "exit_date": None, "exit_price": None,
                    "ret_pct": None, "exit_reason": None}
        if px <= stop_px:
            return {"status": "ok", "exit_date": d, "exit_price": px,
                    "ret_pct": (px / entry_px - 1) * 100, "exit_reason": f"T+{n}跌破7%止损"}
        if n == 4:
            return {"status": "ok", "exit_date": d, "exit_price": px,
                    "ret_pct": (px / entry_px - 1) * 100, "exit_reason": "T+4到期"}
    return {"status": "数据不足", "exit_date": None, "exit_price": None, "ret_pct": None, "exit_reason": None}


for e in MAIN_EPISODES:
    e["cf"] = counterfactual_t4_stop7(e)

cf_rows = [e for e in closed_main if e["cf"]["status"] == "ok"]
cf_insufficient = [e for e in closed_main if e["cf"]["status"] != "ok"]
print(f"\n[诊断] 反事实可计算的round trip数={len(cf_rows)}, 数据不足无法算的={len(cf_insufficient)}")

print("\n[反事实 vs 实际] 分期汇总(用实际cost basis套用反事实收益率算可比的CNY数, 不代表真实可执行仓位):")
for pname in ["甲", "乙", "丙"]:
    eps = [e for e in cf_rows if e["period"] == pname]
    if not eps:
        print(f"  {pname}组: 无可算样本")
        continue
    actual_pnl = sum(e["pnl"] for e in eps)
    actual_ret = float(np.mean([e["return_pct"] for e in eps]))
    cf_pnl = sum(e["cost"] * e["cf"]["ret_pct"] / 100 for e in eps)
    cf_ret = float(np.mean([e["cf"]["ret_pct"] for e in eps]))
    n_exit_stop = sum(1 for e in eps if "止损" in e["cf"]["exit_reason"])
    n_exit_t4 = sum(1 for e in eps if "到期" in e["cf"]["exit_reason"])
    print(f"  {pname}组 n={len(eps)}: 实际均值收益={actual_ret:+.2f}%(合计{actual_pnl:+.0f}元) | "
          f"反事实(T+4/7%止损)均值收益={cf_ret:+.2f}%(合计{cf_pnl:+.0f}元) | "
          f"反事实中{n_exit_stop}笔因7%止损提前出/{n_exit_t4}笔撑到T+4")
print(f"  数据不足无法计算反事实的round trip: {len(cf_insufficient)}笔 "
      f"({', '.join(e['ticker']+e['name'] for e in cf_insufficient[:8])}{'...' if len(cf_insufficient)>8 else ''})")

# ══════════════════════════════════════════════════════════════
# 8. 账户净值 vs 全市场等权中位 累计超额, 分期给
# ══════════════════════════════════════════════════════════════
print("\n[市场中位基准] 计算全市场个股日收益中位数...")
mkt = pd.read_parquet(PARQUET, filters=[("date", ">=", pd.Timestamp("2026-05-15")),
                                         ("date", "<=", pd.Timestamp("2026-10-19"))],
                       columns=["date", "ticker", "adj_close"])
mkt = mkt.sort_values(["ticker", "date"])
mkt["ret"] = mkt.groupby("ticker")["adj_close"].pct_change()
mkt_daily_median = mkt.groupby("date")["ret"].median()
mkt_daily_median.index = mkt_daily_median.index.strftime("%Y-%m-%d")
print(f"[诊断] 市场中位日收益序列长度={len(mkt_daily_median)}, 覆盖{mkt['ticker'].nunique()}只股票")

with open(os.path.join(BASE, "portfolio_state.json")) as f:
    _ps2 = json.load(f)  # 重读一次确保daily_snapshots是最新(只读, 不改)
daily_snaps = {x["date"]: x for x in PS["performance"]["daily_snapshots"]}


def nav_on(date_str):
    x = daily_snaps.get(date_str)
    return x["a_share_nav"] if x else None


def mkt_cum_return(d0, d1):
    """d0到d1(含d1,不含d0当天, 即从d0收盘到d1收盘)市场中位累计收益, d0/d1均为交易日字符串"""
    days = [d for d in TRADING_DAYS if d0 < d <= d1]
    cum = 1.0
    n_have = 0
    for d in days:
        r = mkt_daily_median.get(d)
        if r is not None and pd.notna(r):
            cum *= (1 + r)
            n_have += 1
    return (cum - 1) * 100, n_have, len(days)


PERIOD_RANGES = {
    "甲": ("2026-05-17", "2026-09-16"),   # 05-17收盘(=initial_capital基准日)到09-16收盘
    "乙": ("2026-09-16", "2026-09-17"),
    "丙": ("2026-09-20", "2026-10-19"),   # 09-20(乙结束后最后一个空仓交易日)到10-19(最新数据)
}
print("\n[账户 vs 市场中位] 累计超额, 分期:")
for pname, (d0, d1) in PERIOD_RANGES.items():
    if pname == "甲":
        nav0 = PS["accounts"]["a_share"]["initial_capital"]  # 10,000,000, 05-18开盘前
    else:
        nav0 = nav_on(d0)
    nav1 = nav_on(d1)
    if nav0 is None or nav1 is None:
        print(f"  {pname}组: NAV数据缺失(d0={d0}:{nav0}, d1={d1}:{nav1})")
        continue
    acct_ret = (nav1 / nav0 - 1) * 100
    mkt_ret, n_have, n_days = mkt_cum_return(d0, d1)
    print(f"  {pname}组 [{d0}收盘 → {d1}收盘, {n_days}个交易日(中位数据覆盖{n_have}天)]: "
          f"账户={acct_ret:+.2f}%  市场中位={mkt_ret:+.2f}%  超额={acct_ret - mkt_ret:+.2f}pp")

print(f"\n[诊断] 丁组(B策略专户)说明: daily_snapshots只有a_share账户整体NAV, 没有拆分B子账户的独立NAV序列,"
      f"故丁组不计算累计超额, 只用其单笔round trip的-3.11%与同期(09-04~09-07)市场中位对比:")
_r, _n, _ = mkt_cum_return("2026-09-03", "2026-09-07")
print(f"  B账户唯一round trip收益=-3.11%, 同期(09-03→09-07,{_n}个交易日)市场中位累计={_r:+.2f}%")

# 全程累计超额(05-17到10-19), 作为一个总览数
_full_acct = (nav_on("2026-10-19") / PS["accounts"]["a_share"]["initial_capital"] - 1) * 100
_full_mkt, _fn, _ = mkt_cum_return("2026-05-17", "2026-10-19")
print(f"\n[全程05-17→10-19] 账户={_full_acct:+.2f}%  市场中位={_full_mkt:+.2f}%  "
      f"超额={_full_acct - _full_mkt:+.2f}pp ({_fn}个交易日)")

# ══════════════════════════════════════════════════════════════
# 9. 输出 round_trips.csv
# ══════════════════════════════════════════════════════════════
import csv

csv_path = os.path.join(OUT, "round_trips.csv")
fields = ["episode_id", "period", "ticker", "name", "status",
          "first_buy_date", "last_sell_date", "holding_trading_days",
          "shares_buy", "shares_sell", "avg_buy_price", "avg_sell_price",
          "cost", "proceeds", "pnl", "return_pct",
          "sell_category_main", "sell_categories_all", "buy_ids", "sell_ids",
          "cf_exit_date", "cf_exit_reason", "cf_ret_pct", "cf_pnl_equiv"]

with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    eid = 0
    for e in MAIN_EPISODES + B_EPISODES:
        eid += 1
        cf = e.get("cf", {"exit_date": None, "exit_reason": None, "ret_pct": None})
        w.writerow({
            "episode_id": f"EP{eid:03d}",
            "period": e["period"],
            "ticker": e["ticker"],
            "name": e["name"],
            "status": "持仓中" if e["is_open"] else "已平仓",
            "first_buy_date": e["first_buy_date"],
            "last_sell_date": e["last_sell_date"] or "",
            "holding_trading_days": e["holding_days"],
            "shares_buy": e["shares_buy"],
            "shares_sell": e["shares_sell"],
            "avg_buy_price": round(e["avg_buy_price"], 4) if e["avg_buy_price"] else "",
            "avg_sell_price": round(e["avg_sell_price"], 4) if e["avg_sell_price"] else "",
            "cost": round(e["cost"], 2),
            "proceeds": round(e["proceeds"], 2),
            "pnl": round(e["pnl"], 2),
            "return_pct": round(e["return_pct"], 2) if e["return_pct"] is not None else "",
            "sell_category_main": e["sell_category"],
            "sell_categories_all": "|".join(e["sell_categories_all"]),
            "buy_ids": "|".join(b["id"] for b in e["buys"]),
            "sell_ids": "|".join(s["id"] for s in e["sells"]),
            "cf_exit_date": cf.get("exit_date") or "",
            "cf_exit_reason": cf.get("exit_reason") or "",
            "cf_ret_pct": round(cf["ret_pct"], 2) if cf.get("ret_pct") is not None else "",
            "cf_pnl_equiv": round(e["cost"] * cf["ret_pct"] / 100, 2) if cf.get("ret_pct") is not None else "",
        })
print(f"\n[输出] round_trips.csv 已写入: {csv_path} ({eid}行)")

# ══════════════════════════════════════════════════════════════
# 10. 逐笔sell分类表也单独存一份(给summary.md引用用)
# ══════════════════════════════════════════════════════════════
sell_csv_path = os.path.join(OUT, "sell_classification.csv")
with open(sell_csv_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["id", "date", "ticker", "name", "shares", "price",
                                       "category", "subtag", "book", "d5", "d10", "d20", "reason"])
    w.writeheader()
    for r in sell_rows:
        w.writerow({"id": r["id"], "date": r["date"], "ticker": r["ticker"], "name": r.get("name"),
                    "shares": r["shares"], "price": r["price"], "category": r["category"],
                    "subtag": r["subtag"], "book": r["book"],
                    "d5": round(r["drift"]["d5"], 2) if r["drift"]["d5"] is not None else "",
                    "d10": round(r["drift"]["d10"], 2) if r["drift"]["d10"] is not None else "",
                    "d20": round(r["drift"]["d20"], 2) if r["drift"]["d20"] is not None else "",
                    "reason": r.get("reason")})
print(f"[输出] sell_classification.csv 已写入: {sell_csv_path} ({len(sell_rows)}行)")

# ══════════════════════════════════════════════════════════════
# 11. 按卖出理由大类汇总"已实现盈亏贡献"(逐笔realized_pnl字段求和, 002025那笔用更正值)
# ══════════════════════════════════════════════════════════════
print("\n[按卖出理由大类的已实现盈亏贡献] (逐笔realized_pnl字段求和, TRD-0319用更正值-34383代替原始+272217):")
CORRECTIONS = {"TRD-0319": -34383.0}
cat_pnl = defaultdict(float)
cat_n = defaultdict(int)
for r in sell_rows:
    v = CORRECTIONS.get(r["id"], r.get("realized_pnl", 0) or 0)
    cat_pnl[r["category"]] += v
    cat_n[r["category"]] += 1
for cat in sorted(cat_pnl, key=lambda c: cat_pnl[c]):
    print(f"  {cat}: n={cat_n[cat]}  合计已实现盈亏={cat_pnl[cat]:+.1f}元")
print(f"  合计(校正002025后) = {sum(cat_pnl.values()):+.1f}元")
print(f"  (对比: wash剔除-394.18元未计入上表; 加总后应≈my_realized_main+b_realized = "
      f"{my_realized_main + b_realized:+.1f})")

print("\n[完成] 全部计算结束。")






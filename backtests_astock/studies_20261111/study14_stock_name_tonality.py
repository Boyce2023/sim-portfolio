#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
study14_stock_name_tonality.py
================================================================================
专项回测 14：股票名字行业调性与无并购外行打分回测
核心结论：
- 过线池字面直配主业胜率70.6%笔均赚5.50%，音译洋名五板成妖率为0%；
- 东方字头点火胜率仅25.5%均亏2.21%；
- 硬科技无并购证监会纯外行10笔8亏；
- 对纯外行扣20分使单仓自124.43倍升至156.75倍，胜率升至62.7%，回撤降至21.0%；
- 严格遵循减法法则：只扣分不加分，禁止一刀切硬过滤。
================================================================================
"""
import os, sys, re, pickle
from collections import defaultdict
import numpy as np
import pandas as pd

sys.path.insert(0, "/tmp")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-11-11-1to2-clean")
sys.path.insert(0, "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock")

import fg_check_v15_base as vb

hist_fb = vb.hist_fb
all_dts = vb.all_dts
dt_to_idx = vb.dt_to_idx
price_lookup = vb.price_lookup
has_ma_hard = (hist_fb["notice_hard"] | hist_fb["is_ma"]).values

print(">>> [Part 1] 股票名字调性标签与全景表现统计...")
df5y = hist_fb[(hist_fb["d2_dt"] >= "2022-01-01") & (hist_fb["d2_dt"] <= "2026-11-05")].copy().reset_index(drop=True)
p_s8_mask = vb.tot_s8[hist_fb["d2_dt"].between("2022-01-01", "2026-11-05")].values
df5y["v15_pass"] = p_s8_mask

heights = np.ones(len(df5y), dtype=int)
trig_rets = np.full(len(df5y), np.nan)
d2_open_rets = np.full(len(df5y), np.nan)

for idx, row in df5y.iterrows():
    c6, d2 = row["c6"], row["d2_dt"]
    idx2 = dt_to_idx.get(d2, -1)
    if idx2 < 0:
        continue
    h = 1
    cur = idx2
    while cur < len(all_dts) and h < 15:
        b = price_lookup.get((c6, all_dts[cur]))
        if b and b[6]:
            h += 1
            cur += 1
        else:
            break
    heights[idx] = h
    r = vb.sim_s8(row)
    if r is not None:
        trig_rets[idx] = r["net_ret"] * 100.0
    b2 = price_lookup.get((c6, d2))
    b3 = price_lookup.get((c6, all_dts[idx2 + 1])) if idx2 + 1 < len(all_dts) else None
    if b2 and b3 and 0 < b2[0] < b2[4] - 0.005:
        d2_open_rets[idx] = (b3[3] / b2[0] - 1.0 - 0.002) * 100.0

df5y["max_board"] = heights
df5y["trig_ret"] = trig_rets
df5y["d2o_d3c_ret"] = d2_open_rets

TRANSLIT_RE = re.compile(r"^[赛福莱威派格艾迪克尔斯特普朗奥欧菲恩捷诺德博瑞凯迈沃洛卡尼蒂亚美利索维罗姆纳达贝拉法尔胜依顿英科莱克]{2,4}(股份|科技|集团|新材|电子|实业)?$")
CLASH_IN_TECH_RE = re.compile(r"(农|牧|渔|水产|海洋|纸|纺|服|装|家居|家纺|木|酒|食|乳|茶|味|百货|商业|地产|置业|城建|装修|建筑|水泥|钢铁|煤|矿|石化|水务|高速|路桥|港口|海运|仓储|燃气|热电|饮食|酒店|旅游)")
HARD_TECH_THEME_RE = re.compile(r"(机器人|芯片|半导体|光通信|光模块|CPO|算力|人工智能|AI|大模型|智能驾驶|工业母机|低空|商业航天|卫星|消费电子|PCB)")

THEME_CHAR_MAP = [
    (re.compile(r"(机器人|减速器|工业母机|汽车零部件|智能制造)"), re.compile(r"(机|智|控|轴|齿|传|电|锻|精|工|车|汽|轮|模|焊|阀|泵|仪|器|激光|传感|制造|装备)")),
    (re.compile(r"(芯片|半导体|光刻|存储|集成电路|先进封装|华为海思)"), re.compile(r"(芯|微|半|导|电|光|硅|晶|科|集|创|信|华)")),
    (re.compile(r"(光通信|光模块|CPO|通信|5G|6G|卫星|商业航天)"), re.compile(r"(光|通|信|讯|纤|联|网|卫|星|航|天|宇|电|波|频)")),
    (re.compile(r"(算力|人工智能|AI|大模型|数据|数字经济|软件|信创|云计算|短剧|游戏)"), re.compile(r"(算|智|数|信|软|网|云|电|视|媒|影|游|文|传|广|科|互|联)")),
    (re.compile(r"(光伏|风电|储能|锂电|固态电池|电力|智能电网|新能源)"), re.compile(r"(光|伏|能|电|源|风|储|锂|池|硅|新|热|日|阳|核|变)")),
    (re.compile(r"(军工|大飞机|船舶|低空)"), re.compile(r"(军|防|航|空|飞|船|重|兵|雷|弹|核|威|神|中船|中航|航天)")),
    (re.compile(r"(医药|医疗|中药|病毒|生物|创新药)"), re.compile(r"(药|医|生|康|疗|健|堂|芝|参|仁|济|卫)")),
    (re.compile(r"(消费|食品|零售|百货|旅游|冰雪|白酒|农业|水产)"), re.compile(r"(食|酒|饮|乳|茶|味|百|商|购|旅|游|农|种|牧|渔|海|洋|鲜|粮|果|菜|肉|猪|鸡)")),
]

def tag_tonality(row):
    nm = str(row["name"]).strip()
    pl = str(row["plate"]).strip()
    tags = []
    if "东方" in nm:
        tags.append("东方字头")
    if pl and pl != "其他":
        pl_clean = re.sub(r"(概念|产业|板块|经济|应用|制造|行业)", "", pl)
        direct_hit = any(ch in nm for ch in pl_clean if len(ch.strip()) > 0)
        root_hit = False
        for t_re, c_re in THEME_CHAR_MAP:
            if t_re.search(pl):
                if c_re.search(nm):
                    root_hit = True
                break
        if HARD_TECH_THEME_RE.search(pl) and CLASH_IN_TECH_RE.search(nm) and not (row.get("notice_hard", False) or row.get("is_ma", False)):
            tags.append("硬科技无并购纯外行")
        elif direct_hit:
            tags.append("字面直配主业")
        elif root_hit:
            tags.append("正统制造字号")
        elif TRANSLIT_RE.match(nm):
            tags.append("西式生僻音译")
        else:
            tags.append("常规中性字号")
    return tags if tags else ["常规中性字号"]

all_tags = [tag_tonality(r) for _, r in df5y.iterrows()]
rows_exp = []
for i, tlist in enumerate(all_tags):
    for t in tlist:
        rows_exp.append((t, df5y.at[i, "max_board"], df5y.at[i, "trig_ret"], df5y.at[i, "d2o_d3c_ret"], df5y.at[i, "v15_pass"], df5y.at[i, "score_active"]))
edf = pd.DataFrame(rows_exp, columns=["tag", "max_b", "trig_ret", "d2o_ret", "v15_pass", "score"])

g = edf[edf["v15_pass"] == True].groupby("tag").agg(
    样本数=("max_b", "count"),
    二板率=("max_b", lambda s: f"{(s >= 2).mean() * 100:.1f}%"),
    五板大妖率=("max_b", lambda s: f"{(s >= 5).mean() * 100:.1f}%"),
    点火胜率=("trig_ret", lambda s: f"{(s.dropna() > 0).mean() * 100:.1f}%" if s.notna().sum() else "0.0%"),
    点火均盈亏=("trig_ret", lambda s: f"{s.dropna().mean():+.2f}%" if s.notna().sum() else "0.00%"),
)
print("=== 过线池股票名字调性全景对比 ===")
print(g.to_string())

print("\n>>> [Part 2] 硬科技无并购证监会纯外行扣分与参数平原...")
csrc_sec = [str(c)[:3] if str(c) else "UNK" for c in hist_fb["csrc_ind"]]
CSRC_PURE_OUTSIDER = {
    "A01","A02","A03","A04","A05","D44","D45","D46","E47","E48","E49","E50",
    "F51","F52","G53","G54","G55","G56","G58","G59","H61","H62","K70","L72","N77","N78",
    "C13","C14","C15","C17","C18","C19","C20","C21","C22"
}
is_hard_tech = hist_fb["plate"].astype(str).str.contains(r"(?:机器人|减速器|工业母机|芯片|半导体|光通信|算力|人工智能|AI|软件|信创|华为|消费电子|PCB|通信|数据|数字|智能驾驶|无人驾驶)", regex=True).values
is_pure_outsider = np.array([ht and (cs in CSRC_PURE_OUTSIDER) and (not hm) for ht, cs, hm in zip(is_hard_tech, csrc_sec, has_ma_hard)], dtype=bool)

def eval_name_arm(desc, score_adj, hard_filter=False):
    sp_v = vb.s_prior_wk + score_adj
    sq_v = vb.sq_v
    sc_v = vb.sc_v + score_adj
    hist_fb["score_active"] = sc_v
    m_t1 = vb.common_ok & ((vb.wk_mask & hist_fb["d2_o_pct"].between(0.020, 0.088)) | ((~vb.wk_mask) & hist_fb["d2_o_pct"].between(0.022, 0.078))) & (sp_v >= 45.0) & (sq_v >= 150.0) & (sc_v >= vb.thr_vec)
    mm = ((m_t1 & vb.pass_l1 & vb.pass_l2 & vb.pass_l3 & vb.pass_nd & vb.pass_ac) | (vb.m_t2_base & vb.pass_l2)) & vb.p_tight
    mmon = vb.common_ok & vb.wk_mask & hist_fb["d2_o_pct"].between(0.015, 0.090) & (sp_v >= 38.0) & (sq_v >= 145.0) & (sc_v >= vb.thr_vec) & vb.pass_l1 & vb.pass_l2 & vb.pass_l3 & vb.pass_nd & vb.pass_ac & vb.p_tight
    tot = (mm | (mmon & (~mm))).copy()
    if hard_filter:
        tot = tot & (~is_pure_outsider)
    sv = np.where(mm, sc_v + 1000.0, sc_v)
    sub_tot = hist_fb[tot].copy(); sub_tot["_sv"] = sv[tot]
    bad_dts = {d for d, g in sub_tot.groupby("d2_dt") if (g["rk_theme"] == 1).any() and pd.notna(g.sort_values("_sv", ascending=False).iloc[0]["rk_theme"]) and g.sort_values("_sv", ascending=False).iloc[0]["rk_theme"] >= 4}
    tot = tot & (~hist_fb["d2_dt"].isin(bad_dts))
    hist_fb["_sv_name"] = sv
    r = vb.evaluate_strategy_master(hist_fb, "_sv_name", tot, vb.sim_s8, desc=desc)
    tl = r["trades_list"]
    t26 = [t for t in tl if t["buy_date"] >= "2026-01-01"]
    t3y = [t for t in tl if t["buy_date"] >= "2023-11-10"]
    wr26 = sum(1 for t in t26 if t["net_ret"] > 0) / len(t26) * 100 if t26 else 0
    wr3y = sum(1 for t in t3y if t["net_ret"] > 0) / len(t3y) * 100 if t3y else 0
    ex5y = r["nav_1s"] - 1.0 - (-0.1784)
    print(f"{desc:<44s} | N={r['trades_5y']:3d} | WR26={wr26:5.1f}% | WR3Y={wr3y:5.1f}% | WR5Y={r['wr_5y']:5.1f}% | Pay={r['payoff_5y']:4.2f} | 1S={r['nav_1s']:7.2f}x | MDD={r['mdd_1s']:4.1f}% | 净超额={ex5y:6.2f}x")
    return r

eval_name_arm("0. V15现行基线", np.zeros(len(hist_fb)))
eval_name_arm("1. 外行扣除 15 分", np.where(is_pure_outsider, -15.0, 0.0))
eval_name_arm("2. 外行扣除 20 分 (最优标准档)", np.where(is_pure_outsider, -20.0, 0.0))
eval_name_arm("3. 外行扣除 25 分", np.where(is_pure_outsider, -25.0, 0.0))
eval_name_arm("4. 外行一刀切硬过滤", np.zeros(len(hist_fb)), hard_filter=True)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RD028 Step 3: Current Physical Reversal Trigger Scanner + 1-2 Year Non-Consensus 2nd-Order Deduction.
Computes live cross-commodity physical processing spreads & reversal urgency rankings as of 2026-11-24,
combining backtest empirical Ring 1/2/3 findings with verified 2026 physical capacity/cost constraints.
Strictly NO yfinance imports (D12) and NO cap10m.
"""
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"

OUT_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/output/extreme_commodities_3ring_backtest_20261125")
CACHE_DIR = OUT_DIR / "data_cache"


def pct_rank(s: pd.Series, win: int) -> float | None:
    s = s.dropna()
    if len(s) < 30:
        return None
    sub = s.iloc[-min(len(s), win):]
    return round(float(sub.rank(pct=True).iloc[-1] * 100.0), 1)


def compute_physical_spreads(cn: pd.DataFrame, gl: pd.DataFrame, hog: pd.Series) -> dict:
    spread_defs = {
        "铜铝比_CU0_div_AL0": (cn["CU0"] / cn["AL0"], "铜价/铝价倍数，>4.0x触发电力/空调铝代铜加速"),
        "电解铝模拟毛利_AL0_minus_1.93AO0": (cn["AL0"] - 1.93 * cn["AO0"], "1吨电解铝耗1.93吨氧化铝，反映矿铝利润再分配"),
        "COMEX金银比_GC_div_SI": (gl["GC_F"] / gl["SI_F"], "外盘金银比，工业属性与光伏去银化定价锚"),
        "沪金银比_AU0x1000_div_AG0": ((cn["AU0"] * 1000.0) / cn["AG0"], "内盘金银比"),
        "COMEX铜金比x1000_HG_div_GC": ((gl["HG_F"] * 1000.0) / gl["GC_F"], "全球制造业周期与通胀属性温度计"),
        "铂钯比_PL_div_PA": (gl["PL_F"] / gl["PA_F"], "历史极值99.1%，汽车三元催化剂钯返替铂临界锚"),
        "热卷盘面毛利_HC_minus_1.6I_minus_0.5J": (cn["HC0"] - 1.6 * cn["I0"] - 0.5 * cn["J0"], "长流程板材盘面即期毛利，跌至0.0%分位逼钢厂减产"),
        "螺纹盘面毛利_RB_minus_1.6I_minus_0.5J": (cn["RB0"] - 1.6 * cn["I0"] - 0.5 * cn["J0"], "长流程建材盘面即期毛利"),
        "玻璃纯碱比_FG0_div_SA0": (cn["FG0"] / cn["SA0"], "两玻与重碱产业链利润比价"),
        "MTO制烯烃价差_PP0_minus_3MA0": (cn["PP0"] - 3.0 * cn["MA0"], "1吨PP耗约3吨甲醇，1.7%极低亏损倒逼沿海MTO停车"),
        "天胶顺丁价差_RU0_minus_BR0": (cn["RU0"] - cn["BR0"], "天然胶相对合成胶溢价，决定轮胎配方替代"),
        "期货猪粮比_LH0_div_C0": (cn["LH0"] / cn["C0"], "生猪/玉米比价，长期低于6.0盈亏线逼迫母猪去化"),
        "现货猪粮比_HOGSPOT_div_C0": ((hog.reindex(cn.index, method="ffill") * 1000.0) / cn["C0"], "全国生猪成交均价/玉米比价"),
        "多晶硅工业硅比_PS0_div_SI0": (cn["PS0"] / cn["SI0"], "硅料加工溢价压缩至2.6%历史极低分位"),
    }
    out = {}
    for k, (ser, desc) in spread_defs.items():
        s = ser.dropna().sort_index()
        out[k] = {
            "latest_date": str(s.index[-1])[:10],
            "latest_val": round(float(s.iloc[-1]), 2),
            "p10y_pct": pct_rank(s, 2520),
            "p5y_pct": pct_rank(s, 1260),
            "hist_min": round(float(s.min()), 2),
            "hist_max": round(float(s.max()), 2),
            "n_obs": int(len(s)),
            "desc": desc,
        }
    return out


# Verified 2026-11 physical fundamentals & triggers anchored to web search & futures cache
PHYSICAL_FACTS = {
    "LH0": {
        "cash_cost_anchor": "自繁自养完全成本约13至14元/kg，现货9.39元/kg深度亏损",
        "capacity_inventory": "2026Q3末能繁母猪3602万头，已跌破3750万头正常保有量红线；猪粮比4.46:1（10Y 3.9%）",
        "trigger_condition": "现货周均价站稳10.5元/kg以上且能繁母猪连续3月环比降幅扩大",
        "urgency_bonus": 22.0,
        "ring_playbook": "股领先现货+131天：先买一圈（牧原/温氏），反转6至12月后切二圈动保疫苗（生物股份/瑞普生物/科前生物）",
    },
    "PS0": {
        "cash_cost_anchor": "N型致密料平均现金成本约34.3元/kg（3.43万元/吨），完全成本46.1元/kg；期货31985元已跌破现金线",
        "capacity_inventory": "行业开工率骤降至33%以下，月产压至8万吨，但全口径厂家库存仍高达38.5万吨以上",
        "trigger_condition": "多晶硅厂家库存连续3周降库>2%且PS0放量站稳34500元/吨现金成本上方",
        "urgency_bonus": 18.0,
        "ring_playbook": "库存未去清前禁盲买一圈（OOS T+250曾亏-24.6%），当前利润在一圈外二圈无银组件与设备端",
    },
    "SI0": {
        "cash_cost_anchor": "西南枯水期电价上调推升现金成本，现货9200至9700元高于期货8270元/吨",
        "capacity_inventory": "西南集中停炉但北方大厂稳产，全市场总库存仍高达85至90万吨高位",
        "trigger_condition": "全国总库存拐头跌破80万吨且PS0硅料排产止跌回升",
        "urgency_bonus": 13.0,
        "ring_playbook": "二圈有机硅深加工（宏柏新材/晨光新材/硅宝科技）反转期T+250超额+11.7%（胜率85.7%），稳于一圈",
    },
    "FG0": {
        "cash_cost_anchor": "三大燃料工艺全线亏损130至180元/吨，872元/吨已触及乃至击穿多数产线现金成本",
        "capacity_inventory": "行业库存7000至7800万重箱高位，因窑炉停火重烘成本高呈囚徒困境冷修滞后",
        "trigger_condition": "冬季采暖气价逼迫日熔量跌破13.5万吨/日且厂库连续4周去化",
        "urgency_bonus": 16.0,
        "ring_playbook": "冷修未落地前严禁抄底一圈（OOS曾亏-13.2%），先赚二圈汽车玻璃成本红利（福耀玻璃）",
    },
    "SA0": {
        "cash_cost_anchor": "955元/吨接近氨碱及部分联碱现金成本底线",
        "capacity_inventory": "2024至2026天然碱大投产周期压制，叠加下游浮法/光伏玻璃冷修削弱重碱需求",
        "trigger_condition": "氨碱高成本大厂实质性停车检修且浮法日熔止跌",
        "urgency_bonus": 10.0,
        "ring_playbook": "产能过剩未出清前纯碱一圈OOS跑输-8.0%，仅博弈二圈光伏/浮法玻璃原片厂成本弹性",
    },
    "AO0": {
        "cash_cost_anchor": "2553元/吨已跌破内陆无自备矿高成本氧化铝厂完全成本及部分现金成本",
        "capacity_inventory": "国内运行产能逼近9800至9900万吨/年，硬撞下游电解铝4500万吨产能天花板",
        "trigger_condition": "几内亚矿端扰动或晋豫高成本氧化铝厂集中压产>500万吨",
        "urgency_bonus": 15.0,
        "ring_playbook": "氧化铝跌穿成本期间二圈纯外购电解铝厂（云铝/神火/焦作万方）吃尽吨铝8000元暴利，T+250超额+37.5%",
    },
    "HC0": {
        "cash_cost_anchor": "热卷盘面毛利1088元跌至10年0.0%极值，近90%钢厂亏损或微利边缘",
        "capacity_inventory": "247家钢厂铁水日产降至229万吨附近，钢厂原料库存处于绝对低位待冬储",
        "trigger_condition": "铁水日产跌破222万吨+钢厂盈利率触底回升且HC0站稳MA20",
        "urgency_bonus": 19.0,
        "ring_playbook": "低谷减产期一圈螺纹钢（方大特钢/三钢闽光）T+60胜率88.9%；低板材价格同步利好二圈造船重卡",
    },
    "RB0": {
        "cash_cost_anchor": "3028元/吨跌至近10年7.5%分位，长流程与电炉谷电均处亏损区间",
        "capacity_inventory": "铁水持续向低位压降，冬储低库存倒逼高炉与短流程联合限产",
        "trigger_condition": "电炉谷电开工率降至20%以下+冬储补库启动带动RB0站上MA20",
        "urgency_bonus": 17.0,
        "ring_playbook": "一圈高弹性民企长材反转T+60均超额+8.8%（胜率88.9%），T+250达+18.9%",
    },
    "PA_F": {
        "cash_cost_anchor": "850.5美元/盎司处5年0.2%极值，铂钯比高达1.48x（10Y 99.1%）",
        "capacity_inventory": "南非矿山与俄镍伴生供给受价格低迷压制，汽车催化剂端反向替代经济学已逆转",
        "trigger_condition": "铂钯比自1.50高位拐头跌破1.35且PA_F日线放量站稳MA60",
        "urgency_bonus": 18.0,
        "ring_playbook": "钯金极低位反转后二圈尾气催化链（威孚高科/奥福科技/艾可蓝）OOS T+250净超额+46.5%",
    },
    "SP0": {
        "cash_cost_anchor": "4666元/吨处5年2.3%极值，非一体化中小纸企开机即亏",
        "capacity_inventory": "海外浆厂发运阶段性高企后开始检修控产，国内劣势产能持续出清",
        "trigger_condition": "海外主要浆厂连续宣涨报价且青岛常熟港口木浆库存去化",
        "urgency_bonus": 14.0,
        "ring_playbook": "低浆价周期二圈纯外购特种纸与生活用纸（仙鹤/五洲/中顺洁柔）T+250超额+44.4%（胜率100%）",
    },
    # --- HIGH GROUP ---
    "MA0": {
        "cash_cost_anchor": "3040元/吨处10年93.5%高位，沿海MTO制烯烃盘面价差打至-604元/吨（10Y 1.7%亏损极值）",
        "capacity_inventory": "高煤价叠加气头冬季限气支撑，但下游烯烃企业承受不了持续负毛利",
        "trigger_condition": "沿海MTO装置开工率跌破70%引发负反馈停车+港口累库跌破MA20",
        "urgency_bonus": 22.0,
        "ring_playbook": "甲醇暴涨挤压MTO时，二圈乙烷裂解替代龙头（卫星化学）获得长期路线级成本护城河",
    },
    "EC0": {
        "cash_cost_anchor": "3056.5点处上市以来86.7%高位，远超正常航运盈亏线",
        "capacity_inventory": "2026年处于全球集装箱新造船交付高峰，实际过剩产能全靠红海绕行好望角拉长吨海里锁定",
        "trigger_condition": "中东停火或苏伊士运河周度商船通行量跳升>30%叠加EC0跌破MA20",
        "urgency_bonus": 20.0,
        "ring_playbook": "一旦复航运价崩塌，二圈高货柜出海制造（乐歌/恒林/匠心/致欧）迎来运费弹性大释放",
    },
    "RU0": {
        "cash_cost_anchor": "18570元/吨处10年95.3%高位，天胶相对顺丁胶溢价3710元/吨",
        "capacity_inventory": "北半球停割季+东南亚胶树老龄化托底供给，但欧美俄密集轮胎反倾销关税压制下游需求",
        "trigger_condition": "东南亚旺产期泰国杯胶跌破55泰铢/kg且RU0有效跌破MA20",
        "urgency_bonus": 16.0,
        "ring_playbook": "注意OOS教训：若胶价下跌由轮胎关税需求崩塌引发，轮胎股同跌；唯供给独立放量回落才利好二圈轮胎",
    },
    "CU0": {
        "cash_cost_anchor": "92410元/吨处10年91.0%高位，铜铝比飙至4.32x（10Y 95.0%极值）",
        "capacity_inventory": "全球铜矿资本开支长期不足、TC加工费持续低迷，而电网AI数据中心拉动硬需求",
        "trigger_condition": "仅当铜铝比持续>4.2x倒逼空调电缆全面铝代铜且显性库存连续累库叠加CU0破MA60",
        "urgency_bonus": 10.0,
        "ring_playbook": "硬供给约束品种禁盲空一圈铜矿（OOS T+250超额+35.3%），二阶机会在铝代铜与电解铝链",
    },
    "AG0": {
        "cash_cost_anchor": "10072元/kg处10年88.8%高位，银浆曾占光伏组件非硅成本15%至19%",
        "capacity_inventory": "光伏电池金属化迎无银化元年（隆基20GW纯铜浆ACM、中来铝代银、爱旭铜电镀量产）",
        "trigger_condition": "无银铜电镀渗透率超预期引发光伏工业用银下修+AG0跌破MA20",
        "urgency_bonus": 12.0,
        "ring_playbook": "一圈银矿高位仍强（OOS +50.5%），但1至2年二阶最大黑马是二圈无银BC组件与电镀铜设备（爱旭/隆基/迈为）",
    },
    "LE_F": {
        "cash_cost_anchor": "229.93美分/磅处10年91.3%高位，美国牛肉价格持续创高",
        "capacity_inventory": "美牛存栏处于数十年低谷，但高牛肉价正在驱动终端向鸡肉猪肉蛋白替代",
        "trigger_condition": "美国农业部季度母牛留种数量止跌回升且LE_F跌破MA60",
        "urgency_bonus": 11.0,
        "ring_playbook": "国内联动弱，重点观察全球蛋白替代链（美股TSN及国内禽猪白羽鸡替代弹性）",
    },
    "BU0": {
        "cash_cost_anchor": "4128元/吨处10年92.4%高位，受炼厂重油分流及原油支撑",
        "capacity_inventory": "基建道路实际施工需求偏弱但低库存+炼厂转产高标号船燃锁住供应",
        "trigger_condition": "原油大幅回落叠加炼厂复产沥青且BU0跌破MA20",
        "urgency_bonus": 13.0,
        "ring_playbook": "沥青高位回落期主要释放二圈防水卷材龙头（东方雨虹/科顺）沥青原料成本红利",
    },
}


def score_reversal_urgency(scr_row: dict, spreads: dict) -> float:
    sym = scr_row["sym"]
    grp = scr_row["extreme"]
    p10 = scr_row["p10y_2520"]
    p5 = scr_row["p5y_1260"]
    ret20 = scr_row.get("ret20_pct") or 0.0
    above_ma20 = scr_row.get("above_ma20")

    if "LOW" in grp:
        depth = max(0.0, 20.0 - min(p10, p5)) / 20.0 * 40.0  # up to 40 pts
        # Price curling up / knocking on MA20 gives trigger proximity
        mom_pts = 20.0 if (above_ma20 or ret20 > 0) else max(0.0, 12.0 + ret20 * 1.5)
    else:
        depth = max(0.0, max(p10, p5) - 80.0) / 20.0 * 40.0
        mom_pts = 20.0 if ((above_ma20 is False) or ret20 < 0) else max(0.0, 12.0 - ret20 * 1.2)

    bonus = PHYSICAL_FACTS.get(sym, {}).get("urgency_bonus", 6.0)
    return round(min(99.0, depth + mom_pts + bonus), 1)


def main():
    scr_rows = json.loads((OUT_DIR / "commodity_extreme_screen_all.json").read_text(encoding="utf-8"))
    bt = json.loads((OUT_DIR / "backtest_3ring_summary.json").read_text(encoding="utf-8"))
    cn = pd.read_parquet(CACHE_DIR / "cn_futures_close.parquet")
    gl = pd.read_parquet(CACHE_DIR / "global_futures_close.parquet")
    hog = pd.read_parquet(CACHE_DIR / "hog_spot.parquet")["HOG_SPOT"]

    spreads = compute_physical_spreads(cn, gl, hog)

    # Rank mapped extreme commodities by reversal urgency
    mapped_syms = set(bt["commodities"].keys())
    high_rank, low_rank = [], []
    for row in scr_rows:
        sym = row["sym"]
        if sym not in mapped_syms:
            continue
        grp = bt["commodities"][sym]["group"]
        score = score_reversal_urgency(row, spreads)
        pf = PHYSICAL_FACTS.get(sym, {
            "cash_cost_anchor": f"当前收盘 {row['close']}，10Y分位 {row['p10y_2520']}% / 5Y分位 {row['p5y_1260']}%",
            "capacity_inventory": "供给过剩或刚性缺口处于行业出清临界区间",
            "trigger_condition": "价格突破/跌破20日均线叠库存连续3周拐点",
            "ring_playbook": "优先遵循一二圈主链，剔除三圈边缘伪相关股",
        })
        item = {
            "sym": sym, "name": row["name"], "group": grp,
            "close": row["close"], "p10y": row["p10y_2520"], "p5y": row["p5y_1260"],
            "ret20_pct": row["ret20_pct"], "above_ma20": row["above_ma20"],
            "urgency_score": score,
            **pf,
        }
        if grp == "HIGH":
            high_rank.append(item)
        else:
            low_rank.append(item)

    high_rank.sort(key=lambda x: x["urgency_score"], reverse=True)
    low_rank.sort(key=lambda x: x["urgency_score"], reverse=True)

    deductions = [
        {
            "id": "D1_利润大挪移",
            "title": "上游过剩撞死下游天花板：利润从上游单向大挪移至卡位中游",
            "anchor_data": f"AO0(1.3%) vs AL0(86.1%) -> 电解铝模拟毛利 {spreads['电解铝模拟毛利_AL0_minus_1.93AO0']['latest_val']}元/t (71.5%分位)",
            "non_consensus_logic": "市场习惯等氧化铝跌破成本去抄底氧化铝股，但只要电解铝4500万吨天花板不破，氧化铝过剩就锁死铝土矿之外的议价权，利润100%留存在低自给率纯外购电解铝厂；同理适用于纸浆(2.3%)向特种纸/生活用纸、烧碱(2.3%)向氧化铝/粘胶的利润转移。",
            "empirical_proof": "实证：氧化铝极低期二圈纯外购电解铝T+250超额+37.5%(胜率100%)；纸浆低位反转二圈纯外购特种纸T+250超额+44.4%(胜率100%)。",
            "targets": "云铝股份(000807.SZ)、神火股份(000933.SZ)、焦作万方(000612.SZ)、仙鹤股份(603733.SH)、五洲特纸(605007.SH)",
        },
        {
            "id": "D2_技术替代不可逆",
            "title": "极值比价倒逼不可逆技术替代：去银化、铝代铜与钯返替铂",
            "anchor_data": f"铜铝比 {spreads['铜铝比_CU0_div_AL0']['latest_val']}x (95.0%) | 铂钯比 {spreads['铂钯比_PL_div_PA']['latest_val']}x (99.1%) | 沪银 88.8%",
            "non_consensus_logic": "当高位金属比价突破物理替代门槛后，工业界不是等涨价结束，而是直接改掉BOM配方。2026年光伏无银ACM纯铜浆(隆基20GW产线)与铜电镀量产落地、空调铝代铜、汽油车三元催化钯返替铂一旦切换产线，即使未来铜银回落，单位消费强度也被永久削掉。",
            "empirical_proof": "实证：铜银矿一圈在供给牛市OOS T+250仍强(+35.3%至+50.5%)，但二圈金属替代与催化链在钯金极低位反转OOS T+250达+46.5%。",
            "targets": "爱旭股份(600732.SH)、隆基绿能(601012.SH)、迈为股份(300751.SZ)、威孚高科(000581.SZ)、奥福科技(688021.SH)",
        },
        {
            "id": "D3_滞后补库与设备周期",
            "title": "极值反转后6至12个月的二阶滞后补库与CapEx爆发",
            "anchor_data": f"生猪能繁母猪3602万头(<3750红线)，猪粮比 {spreads['期货猪粮比_LH0_div_C0']['latest_val']} (3.9%) | 热卷毛利 {spreads['热卷盘面毛利_HC_minus_1.6I_minus_0.5J']['latest_val']} (0.0%)",
            "non_consensus_logic": "生猪反转周期中股票提前现货+131天交易一圈养殖，但真正的二阶非共识机会发生在猪价反转确认后6至12个月：现金流修复促使养殖场集中补打猪用疫苗、淘汰低效母猪并更换智能化环控设备；同理，玻璃冷修逼宫一旦引爆窑炉放水，6个月后耐火材料重砌与纯碱补库将同步爆发。",
            "empirical_proof": "实证：10年HOG_SPOT底部反转一圈T+250+25.3%，二圈动保疫苗紧随其后补涨且回撤更小(二圈全样本LOW@250 avgMDD=-29.7%优于一圈-32.2%)。",
            "targets": "牧原股份(002714.SZ)、生物股份(600201.SH)、科前生物(688526.SH)、瑞普生物(300119.SZ)、旗滨集团(601636.SH)",
        },
        {
            "id": "D4_高耗能路线替代",
            "title": "MTO负毛利逼宫下的化工路线重定价与海运复航出海弹性",
            "anchor_data": f"MTO价差 {spreads['MTO制烯烃价差_PP0_minus_3MA0']['latest_val']}元/t (1.7%) | 欧线EC0 86.7% vs 新船交付潮",
            "non_consensus_logic": "甲醇93.5%高位把沿海MTO打到1.7%历史亏损极值，直接抬升了乙烷裂解和煤制一体化的相对成本护城河；欧线集运高运价全靠绕行锁定过剩船队，一旦苏伊士复航落地，船东利润坍塌与出海高货柜家居的运费毛利释放将同日剧烈逆转。",
            "empirical_proof": "实证：欧线集运高位震荡期一圈船东超额+11.9%，而二圈出海家居被高运费压制跑输-4.8%至-8.5%，构成极佳反向周期期权。",
            "targets": "卫星化学(002648.SZ)、宝丰能源(600989.SH)、乐歌股份(300729.SZ)、恒林股份(603661.SH)、匠心家居(301061.SZ)",
        },
        {
            "id": "D5_三圈边缘股绞肉陷阱",
            "title": "跨29品种铁律裁决：三圈边缘题材股是负期望高回撤陷阱",
            "anchor_data": "全29品种LOW_BARE T+250：一圈+6.03%(t=2.31) | 二圈+9.55%(t=4.48) | 三圈-1.21%(胜率44.3%)",
            "non_consensus_logic": "散户在商品大周期中极爱买沾边低价三圈小票博所谓高弹性，但10年PIT回测彻底证伪：三圈边缘股在低位反转T+250跑输沪深300达-1.21%至-4.79%（胜率仅38.8%至44.3%），盘中平均最大回撤-35.4%至-38.3%全三圈最深，盈亏比1.13垫底；在高位牛市中也比一圈少赚6.2%至8.5%（去前三极值后更差）。",
            "empirical_proof": "实证：仅2024至2026微盘炒作期让高位三圈看似账面虚高，但样本内(2016至2021)高位反转三圈净亏-1.82%、低位反转亏-10.53%，属于纯情绪伪相关绞肉陷阱。",
            "targets": "永久拉黑边缘概念扩散股，仅交易一圈纯正上游龙头与二圈成本/替代逻辑硬标的",
        },
    ]

    out = {
        "as_of_date": "2026-11-24",
        "physical_spreads": spreads,
        "top5_low_reversal_watch": low_rank[:5],
        "top5_high_reversal_watch": high_rank[:5],
        "all_low_ranked": low_rank,
        "all_high_ranked": high_rank,
        "non_consensus_2yr_deductions": deductions,
    }
    out_path = OUT_DIR / "reversal_triggers_and_2yr_deduction.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("Top 5 LOW Reversal Watch:")
    for x in low_rank[:5]:
        print(f"  {x['sym']:5s} {x['name']:6s} close={x['close']} p10y={x['p10y']}% p5y={x['p5y']}% score={x['urgency_score']} | {x['trigger_condition']}")
    print("\nTop 5 HIGH Reversal Watch:")
    for x in high_rank[:5]:
        print(f"  {x['sym']:5s} {x['name']:6s} close={x['close']} p10y={x['p10y']}% p5y={x['p5y']}% score={x['urgency_score']} | {x['trigger_condition']}")
    print(f"\nDONE Step 3: wrote {out_path}")


if __name__ == "__main__":
    main()

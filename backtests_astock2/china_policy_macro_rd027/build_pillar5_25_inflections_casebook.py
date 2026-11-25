#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Pillar 5: 1999-2026 25 Epic Policy Inflections Casebook
(10 True Policy Bottoms vs 7 False Policy Bottom Traps vs 8 Policy Valuation-Kill Tops).
Computes pre-event state, 4-gate physical policy scorecard, and post-event T+5/20/60/120/250 trajectories
plus 120d leading/lagging sectors 100% from local market truth sources (zero yfinance).
"""
import json
import os
import sys
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import akshare as ak

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import rd027_common as cm

OUT_JSON = os.path.join(cm.OUT_PILLAR_DIR, "pillar5_25_inflections_casebook.json")
A_DAILY_PQ = os.path.join(cm.ROOT, "sim-portfolio/data/cn_hk_price_db/a_daily.parquet")
A_DELIST_PQ = os.path.join(cm.ROOT, "sim-portfolio/data/cn_hk_price_db/a_delisted_daily.parquet")

SECTOR_UNIVERSE = [
    ("new_energy", "新能源"),
    ("semi_etf", "半导体"),
    ("tmt_info", "TMT信息"),
    ("media_ai", "传媒AI"),
    ("pharma", "医药"),
    ("defense", "军工"),
    ("real_estate", "地产"),
    ("baijiu", "白酒"),
    ("cons_opt", "可选消费"),
    ("bank_idx", "银行"),
    ("brokerage", "券商"),
    ("central_soe", "央企"),
    ("soe_reform", "国企改革"),
    ("csi_div", "中证红利"),
    ("chinext", "创业板"),
    ("star50", "科创50"),
    ("csi500", "中证500"),
    ("csi1000", "中证1000"),
    ("sse50", "上证50"),
    ("tech_board", "硬科技板(创+科)"),
    ("micro30", "微盘30"),
    ("large10", "大盘10"),
]

# 25 verified epic policy inflection cases:
# (case_id, category, event_date, release_slot, case_name, authority_body, policy_trigger,
#  g1_bleed_valve, g2_real_bs, g3_top_breakthrough, g4_note_or_override, gate_rationale)
# Note: gate4 (extreme low-volume / deep-drawdown freeze) is computed PURELY quantitatively from PIT data!
#       (prior_amt_pct_250d <= 0.25 OR prior_dd_60d <= -0.15 OR prior_dd_250d <= -0.25)
CASES = [
    # === 10 TRUE POLICY BOTTOMS ===
    ("CASE_01", "TRUE_POLICY_BOTTOM", "1999-05-16", "WEEKEND_HOLIDAY",
     "1999.05 五一九行情(国务院批复六大政策)", "国务院/中国证监会",
     "国务院批准证监会稳定和发展证券市场六条政策(允许险资与长期基金入市/券商增资/高新企业上市),5月19日井喷启动",
     1, 1, 1, "停发抽血重整+机构增量资金准入+最高层批复", "1999-05-16周末国务院批复六条(先导至5·19全面爆发)"),
    ("CASE_02", "TRUE_POLICY_BOTTOM", "2005-04-29", "AMC",
     "2005.04 股权分置改革试点启动(998世纪大底前夜)", "国务院/中国证监会",
     "经国务院批准发布《关于上市公司股权分置改革试点有关问题的通知》,彻底解决非流通股悬顶制度抽血宿疾",
     1, 1, 1, "从制度根源化解全流通抽血预期(流通股东获对价补偿)+国务院批准", "master_M0039"),
    ("CASE_03", "TRUE_POLICY_BOTTOM", "2008-11-09", "WEEKEND_HOLIDAY",
     "2008.11 国常会四万亿与适度宽松转向", "国务院常务会议",
     "出台扩内需十项措施(4万亿财政投资),货币政策转向适度宽松并取消银行信贷规模限制(接力918三箭齐发)",
     1, 1, 1, "918已停IPO且单边印花税+4万亿财政与信贷取消限制真扩表+国务院破格转向", "master_M0085"),
    ("CASE_04", "TRUE_POLICY_BOTTOM", "2014-11-21", "AMC",
     "2014.11 央行时隔两年首次降息+沪港通启航", "中国人民银行/证监会",
     "周五盘后央行意外宣布非对称降息(一年贷款下调40bp/存款下调25bp),叠加11·17沪港通开通引爆全面重估",
     1, 1, 1, "无新股抽血压力+央行正式启动降息宽松周期+沪港通外资通道开启", "pboc_20141121"),
    ("CASE_05", "TRUE_POLICY_BOTTOM", "2015-08-25", "AMC",
     "2015.08 二次探底8·25双降+养老金入市", "中国人民银行/国务院",
     "沪指跌破3000点后央行盘后降息25bp并全面降准50bp,叠加8·23养老金入市办法落地,2850点次日见大底",
     1, 1, 1, "7月已暂停IPO并限减持+央行全面双降真放水+场外配资出清尾声", "master_M0215"),
    ("CASE_06", "TRUE_POLICY_BOTTOM", "2018-10-19", "BMO",
     "2018.10 副总理一行两会联合发声+10.31政治局", "国务院副总理/一行两会/政治局",
     "沪指跌破2500次日早盘前刘鹤与一行两会四巨头罕见联合采访纾困股权质押,10·31政治局专段激发资本市场活力",
     1, 1, 1, "地方国资与险资专项产品化解质押爆仓抽血+民企债股融资工具+政治局破格定调", "master_M0301"),
    ("CASE_07", "TRUE_POLICY_BOTTOM", "2020-03-27", "AMC",
     "2020.03 非常规政治局定调提高赤字与特别国债", "中共中央政治局",
     "海外熔断尾声非常规政治局会议首次明确提高赤字率/发特别国债/增专项债,随后4月降准降息全面托底",
     1, 1, 1, "财政赤字与特别国债真扩表+央行降准降息+最高层破格对冲疫情", "xinhua_20200327"),
    ("CASE_08", "TRUE_POLICY_BOTTOM", "2022-11-11", "AMC",
     "2022.11 防疫二十条+地产金融十六条", "国务院联防联控/央行/银保监会",
     "同日出台优化防疫二十条与金融支持地产十六条(接续11·28地产第三支箭),同时解除封控与地产信用枯竭双压",
     1, 1, 1, "解除经济停摆与房企信用踩踏两大抽血阀+央行开发贷保交楼借款+国务院重大转向", "pboc_nhc_20221111"),
    ("CASE_09", "TRUE_POLICY_BOTTOM", "2024-09-24", "AMC",
     "2024.09 924一行一局一会SFISF+926政治局", "央行/金融监管总局/证监会/政治局",
     "央行首创5000亿SFISF互换便利与3000亿回购增持再贷款(可扩期),9·26政治局罕见加开首提努力提振资本市场与地产止跌回稳",
     1, 1, 1, "严限IPO/减持早已落地+央行史无前例直通股市资产负债表+926政治局破格定调", "master_M0540"),
    ("CASE_10", "TRUE_POLICY_BOTTOM", "2025-04-08", "BMO",
     "2025.04 汇金类平准基金+央行再贷款抗击关税冲击", "央行/中央汇金/金融监管总局/国资委",
     "对等关税黑天鹅暴跌次日盘前汇金明确类平准基金定位,央行承诺充足再贷款支持,金规12号上调险资权益上限",
     1, 1, 1, "汇金盘前实质买入ETF承接恐慌盘+央行再贷款无限弹药+险资与央企回购增持", "master_M0579"),

    # === 7 FALSE POLICY BOTTOM TRAPS ===
    ("CASE_11", "FALSE_BOTTOM_TRAP", "2008-04-23", "AMC",
     "2008.04 4·24印花税由3‰下调至1‰", "财政部/税务总局",
     "6124暴跌半腰后财政部下调印花税至1‰,但IPO未停、大小非解禁洪峰未堵、宏观从紧未改,暴涨后半年再腰斩至1664",
     0, 0, 0, "仅降交易摩擦税(未停IPO也未止大小非减持)+未动用央行财政扩表+部委单兵", "master_M0074"),
    ("CASE_12", "FALSE_BOTTOM_TRAP", "2012-05-23", "AMC",
     "2012.05 降准与国常会稳增长口号陷阱", "国务院常务会议/央行",
     "5·12降准与5·23国常会强调把稳增长放在更重要位置,但地产严控未松、强刺激未出、IPO继续扩容,指数阴跌破2000至1949",
     0, 0, 0, "IPO抽血未停+未启动地产信用扩表+温和降准对冲外汇占款流失而非强刺激", "gov_20120523"),
    ("CASE_13", "FALSE_BOTTOM_TRAP", "2015-07-04", "WEEKEND_HOLIDAY",
     "2015.07 股灾救市一浪(21券商1200亿+暂缓IPO)", "国务院救市会议/证监会",
     "21家券商凑1200亿买蓝筹ETF+28家新股暂缓,但场外配资与两融踩踏强平链未清零且8月汇率突贬,反弹两周即二次暴跌",
     1, 0, 0, "暂缓IPO但场外配资强平链仍在+初期仅券商凑钱1200亿尚未央行无限流动性兜底", "master_M0204"),
    ("CASE_14", "FALSE_BOTTOM_TRAP", "2016-01-07", "AMC",
     "2016.01 熔断叫停与减持新规", "中国证监会/交易所",
     "元旦四天两次触发指数熔断引发流动性踩踏,1·7连夜叫停熔断机制并限制大股东减持,但汇率与高估值压力下继续跌至2638",
     1, 0, 0, "虽叫停熔断与限减持但无任何央行/财政新增扩表资金进场", "master_M0227"),
    ("CASE_15", "FALSE_BOTTOM_TRAP", "2022-03-16", "INTRADAY",
     "2022.03 3·16金融委专题会议维稳一浪", "国务院金融稳定发展委员会",
     "港股中概股暴跌之际金融委盘中喊话慎重出台收缩性政策与欢迎长钱,但国内疫情封控叠加美联储加息无真金工具,4月底再破3000至2863",
     0, 0, 1, "副总理高规格喊话但未解除封控也未出央行股市工具/财政真扩张", "master_M0402"),
    ("CASE_16", "FALSE_BOTTOM_TRAP", "2023-07-24", "AMC",
     "2023.07 7·24政治局首提活跃资本市场", "中共中央政治局",
     "政治局会议首提要活跃资本市场提振投资者信心,但当日无停IPO、无降税、无央行增持工具配套,两周冲高回落开启半年阴跌",
     0, 0, 1, "最高层口号突破但抽血阀(IPO/减持)与真金白银资产负债表工具双缺位", "master_M0447"),
    ("CASE_17", "FALSE_BOTTOM_TRAP", "2023-08-27", "WEEKEND_HOLIDAY",
     "2023.08 活跃资本市场四箭齐发(印花税减半)", "财政部/证监会/交易所",
     "印花税减半+阶段收紧IPO+破发破净限减持+降保证金,但未动用央行/汇金真资产负债表接盘且地产通缩未止,次日高开低走半年跌至2635",
     1, 0, 0, "虽堵住部分IPO减持抽血并降税,但无央行/平准真扩表资金承接外资流出", "master_M0452"),

    # === 8 POLICY VALUATION-KILL TOPS ===
    ("CASE_18", "POLICY_VALUATION_TOP", "2001-06-12", "AMC",
     "2001.06 国有股减持暂行办法(2245大顶)", "国务院/财政部/证监会",
     "正式公布《减持国有股筹集社会保障资金管理暂行办法》按融资额10%市价出售国有股,开启长达4年跌至998点的超级熊市",
     0, 0, 0, "反向制度级天量抽血阀开启(国有股按市价减持)+高估值泡沫顶", "master_M0009"),
    ("CASE_19", "POLICY_VALUATION_TOP", "2007-05-30", "BMO",
     "2007.05 5·30半夜鸡叫上调印花税至3‰", "财政部(经国务院批准)",
     "深夜突发上调证券交易印花税3倍至3‰给全民炒股降温,沪指单日暴跌6.5%,低价题材股开启40%级结构杀跌",
     0, 0, 0, "行政税收加码打击交易热度+紧缩预热(虽然蓝筹晚4个月见顶)", "master_M0063"),
    ("CASE_20", "POLICY_VALUATION_TOP", "2007-12-05", "AMC",
     "2007.12 中央经济工作会议十年首次从紧货币", "中央经济工作会议",
     "定调双防(防过热防通胀)并将货币政策由稳健改为从紧,严控信贷投放彻底锁死6124牛市估值顶部触发70%熊市",
     0, 0, 0, "顶层货币总量硬紧缩(从紧)+全球次贷共振击穿高估值", "master_M0066"),
    ("CASE_21", "POLICY_VALUATION_TOP", "2010-12-03", "AMC",
     "2010.12 政治局退出适度宽松转向稳健", "中共中央政治局",
     "政治局会议决定货币政策由适度宽松转向稳健并把控通胀放突出位置(叠加地产新国十条),终结四万亿后流动性牛市",
     0, 0, 0, "货币政策正式退出危机宽松进入2011加息紧缩周期", "xinhua_20101203"),
    ("CASE_22", "POLICY_VALUATION_TOP", "2015-06-12", "AMC",
     "2015.06 5178见顶日清理场外配资接口", "中国证监会",
     "沪指摸高5178点当日证监会明确两融不得超净资本4倍并严禁券商为场外配资提供网上接口,刺破高杠杆泡沫引发股灾",
     0, 0, 0, "硬切断场外杠杆增量资金链触发多杀多强平负反馈", "master_M0199"),
    ("CASE_23", "POLICY_VALUATION_TOP", "2017-04-07", "AMC",
     "2017.04 银监6号文三三四+证监会严打高送转", "银监会/证监会/政治局",
     "银监会启动三三四同业空转检查+04·08证监会痛批铁公鸡高送转+04·25政治局金融安全,开启2017-2018金融去杠杆与小盘杀估值",
     0, 0, 0, "跨部门金融严监管收紧表外信用+严打题材炒作压死中小创估值", "cbrc_20170407"),
    ("CASE_24", "POLICY_VALUATION_TOP", "2020-11-03", "AMC",
     "2020.11 蚂蚁集团暂缓上市+反垄断防无序扩张", "上交所/四部门/政治局",
     "四部门约谈次日晚蚂蚁集团暂缓科创板上市,紧接11·10平台反垄断指南与12月中央经济工作会议防止资本无序扩张开启互联网下行",
     0, 0, 0, "平台经济与金融科技商业模式重构估值天花板下移", "sse_20201103"),
    ("CASE_25", "POLICY_VALUATION_TOP", "2021-07-24", "WEEKEND_HOLIDAY",
     "2021.07 双减意见+730政治局反垄断(叠加三道红线)", "中共中央办公厅/国务院办公厅/政治局",
     "双减文件严禁K12培训资本化,叠加7·30政治局严管平台与境外上市及前期地产三道红线集中暴雷,重创成长与地产权重",
     0, 0, 0, "多行业合法性与商业模式行政重塑引发外资减配与估值中枢下移", "gov_20210724"),
]


def build_pre2000_bridge() -> pd.DataFrame:
    """Build exact sh000001 + survivorship-free equal-weight 1998-05 ~ 2000-06 bridge for CASE_01 (1999.05)."""
    sh = ak.stock_zh_index_daily_tx(symbol="sh000001")
    sh["date"] = pd.to_datetime(sh["date"]).dt.strftime("%Y-%m-%d")
    sh = sh[(sh["date"] >= "1998-04-01") & (sh["date"] <= "2000-08-01")].sort_values("date").drop_duplicates("date")
    for c in ["open", "high", "low", "close"]:
        sh[f"sh_comp_{c}"] = sh[c].astype(float)
    sh["sh_comp_prev_close"] = sh["sh_comp_close"].shift(1)
    sh["sh_comp_cc_ret"] = sh["sh_comp_close"] / sh["sh_comp_prev_close"] - 1.0
    sh["sh_comp_gap_ret"] = sh["sh_comp_open"] / sh["sh_comp_prev_close"] - 1.0

    t1 = pq.read_table(A_DAILY_PQ, columns=["date", "ticker", "open", "close", "adj_close", "amount"],
                       filters=[("date", ">=", pd.Timestamp("1998-04-01")), ("date", "<=", pd.Timestamp("2000-08-01"))]).to_pandas()
    t2 = pq.read_table(A_DELIST_PQ, columns=["date", "ticker", "open", "close", "adj_close", "amount"],
                       filters=[("date", ">=", pd.Timestamp("1998-04-01")), ("date", "<=", pd.Timestamp("2000-08-01"))]).to_pandas()
    stk = pd.concat([t1, t2], ignore_index=True)
    stk["date"] = pd.to_datetime(stk["date"]).dt.strftime("%Y-%m-%d")
    stk = stk.drop_duplicates(["date", "ticker"]).sort_values(["ticker", "date"]).reset_index(drop=True)
    ratio = np.where(stk["close"] > 0, stk["adj_close"] / stk["close"], 1.0)
    stk["open_adj"] = stk["open"] * ratio
    stk["prev_adj_close"] = stk.groupby("ticker")["adj_close"].shift(1)
    valid = (stk["prev_adj_close"] > 0) & (stk["open_adj"] > 0) & (stk["adj_close"] > 0) & (stk["amount"] > 0)
    stk = stk[valid].copy()
    stk["cc_ret"] = (stk["adj_close"] / stk["prev_adj_close"] - 1.0).clip(-0.30, 0.30)
    stk["gap_ret"] = (stk["open_adj"] / stk["prev_adj_close"] - 1.0).clip(-0.20, 0.20)
    g = stk.groupby("date")
    daily = pd.DataFrame({
        "total_amount_yi": g["amount"].sum() / 1e8,
        "ew_cc_ret": g["cc_ret"].mean(),
        "ew_gap_ret": g["gap_ret"].mean(),
    }).reset_index()

    b = sh.merge(daily, on="date", how="left").sort_values("date").reset_index(drop=True)
    b["bench_cc_ret"] = b["sh_comp_cc_ret"]
    b["bench_gap_ret"] = b["sh_comp_gap_ret"]
    b["bench_level"] = (1.0 + b["bench_cc_ret"].fillna(0.0)).cumprod()
    b["bench_open"] = b["bench_level"].shift(1).fillna(1.0) * (1.0 + b["bench_gap_ret"].fillna(0.0))
    b["bench_close"] = b["bench_level"]
    ew_cl = (1.0 + b["ew_cc_ret"].fillna(0.0)).cumprod()
    b["ew_open"] = ew_cl.shift(1).fillna(1.0) * (1.0 + b["ew_gap_ret"].fillna(0.0))
    b["ew_close"] = ew_cl
    b["bench_ret_20d"] = b["bench_level"] / b["bench_level"].shift(20) - 1.0
    b["bench_dd_60d"] = b["bench_level"] / b["bench_level"].rolling(60, min_periods=10).max() - 1.0
    b["bench_dd_250d"] = b["bench_level"] / b["bench_level"].rolling(250, min_periods=30).max() - 1.0
    b["bench_vol_20d"] = b["bench_cc_ret"].rolling(20, min_periods=10).std() * np.sqrt(242)
    b["amount_pct_250d"] = b["total_amount_yi"].rolling(250, min_periods=30).rank(pct=True)
    return b


def build_pillar5():
    panel, dates, date_to_idx = cm.load_market_panel()
    pre_bridge = build_pre2000_bridge()
    pre_dates = pre_bridge["date"].tolist()
    pre_d2i = {d: i for i, d in enumerate(pre_dates)}

    horizons = [5, 20, 60, 120, 250]
    case_records = []

    for item in CASES:
        cid, cat, dt, slot, cname, body, trig, g1, g2, g3, g_note, src_ref = item
        use_pre = dt < dates[1]
        active_panel = pre_bridge if use_pre else panel
        active_dates = pre_dates if use_pre else dates
        active_d2i = pre_d2i if use_pre else date_to_idx

        t_entry, t_prior, trad_dt = cm.align_event_pit(dt, slot, active_dates, active_d2i)
        pr = active_panel.iloc[t_prior]

        p_dd60 = float(pr["bench_dd_60d"]) if pd.notna(pr.get("bench_dd_60d")) else np.nan
        p_dd250 = float(pr["bench_dd_250d"]) if pd.notna(pr.get("bench_dd_250d")) else np.nan
        p_amt_pct = float(pr["amount_pct_250d"]) if pd.notna(pr.get("amount_pct_250d")) else np.nan
        p_ret20 = float(pr["bench_ret_20d"]) if pd.notna(pr.get("bench_ret_20d")) else np.nan
        p_vol20 = float(pr["bench_vol_20d"]) if pd.notna(pr.get("bench_vol_20d")) else np.nan
        p_amt_yi = float(pr["total_amount_yi"]) if pd.notna(pr.get("total_amount_yi")) else np.nan

        # Gate 4: Pure quantitative extreme freeze / deep drawdown check
        g4_freeze = int(
            (pd.notna(p_amt_pct) and p_amt_pct <= 0.25) or
            (pd.notna(p_dd60) and p_dd60 <= -0.15) or
            (pd.notna(p_dd250) and p_dd250 <= -0.25)
        )
        four_gates_score = int(g1 + g2 + g3 + g4_freeze)

        rec = {
            "case_id": cid,
            "category": cat,
            "case_name": cname,
            "event_date": dt,
            "release_slot": slot,
            "tradable_date": trad_dt,
            "authority_body": body,
            "policy_trigger": trig,
            "source_ref": src_ref,
            "data_source": "sh000001_tx + cn_hk_price_db_pre2000_spliced" if use_pre else "daily_market_panel_v2_20261124",
            "pre_event_state": {
                "prior_dd_60d_pct": round(p_dd60 * 100, 2) if pd.notna(p_dd60) else None,
                "prior_dd_250d_pct": round(p_dd250 * 100, 2) if pd.notna(p_dd250) else None,
                "prior_amt_pct_250d": round(p_amt_pct, 3) if pd.notna(p_amt_pct) else None,
                "prior_ret_20d_pct": round(p_ret20 * 100, 2) if pd.notna(p_ret20) else None,
                "prior_vol_20d_pct": round(p_vol20 * 100, 2) if pd.notna(p_vol20) else None,
                "prior_amt_yi": round(p_amt_yi, 1) if pd.notna(p_amt_yi) else None,
            },
            "policy_four_gates": {
                "gate1_bleed_valve_stopped": int(g1),
                "gate2_real_balance_sheet": int(g2),
                "gate3_top_level_breakthrough": int(g3),
                "gate4_extreme_freeze_or_dd": int(g4_freeze),
                "four_gates_score": four_gates_score,
                "gate_rationale": g_note,
            },
            "post_event_trajectory": {},
            "post_120d_sector_dispersion": {},
        }

        traj = {}
        for h in horizons:
            b_r = cm.calc_fwd_return(active_panel, t_entry, h, "bench")
            c3_r = cm.calc_fwd_return(active_panel, t_entry, h, "csi300") if not use_pre else np.nan
            sh_r = cm.calc_fwd_return(active_panel, t_entry, h, "sh_comp")
            ew_r = cm.calc_fwd_return(active_panel, t_entry, h, "ew")
            mdd_b = cm.calc_fwd_max_drawdown(active_panel, t_entry, h, "bench")
            mdd_e = cm.calc_fwd_max_drawdown(active_panel, t_entry, h, "ew")
            traj[f"T+{h}"] = {
                "bench_ret_pct": round(b_r * 100, 2) if pd.notna(b_r) else None,
                "csi300_ret_pct": round(c3_r * 100, 2) if pd.notna(c3_r) else None,
                "sh_comp_ret_pct": round(sh_r * 100, 2) if pd.notna(sh_r) else None,
                "ew_ret_pct": round(ew_r * 100, 2) if pd.notna(ew_r) else None,
                "bench_mdd_pct": round(mdd_b * 100, 2) if pd.notna(mdd_b) else None,
                "ew_mdd_pct": round(mdd_e * 100, 2) if pd.notna(mdd_e) else None,
            }
        rec["post_event_trajectory"] = traj

        # Post-120d leading Top 2 & lagging Bottom 2 sectors across all available columns in active_panel
        sec_perf = []
        b120 = cm.calc_fwd_return(active_panel, t_entry, 120, "bench")
        if not use_pre:
            for s_col, s_name in SECTOR_UNIVERSE:
                sr = cm.calc_fwd_return(active_panel, t_entry, 120, s_col)
                if pd.notna(sr):
                    sec_perf.append({
                        "sector_col": s_col,
                        "sector_name": s_name,
                        "ret_120d_pct": round(sr * 100, 2),
                        "excess_vs_bench_120d_pct": round((sr - b120) * 100, 2) if pd.notna(b120) else None,
                    })
        else:
            ew120 = cm.calc_fwd_return(active_panel, t_entry, 120, "ew")
            sh120 = cm.calc_fwd_return(active_panel, t_entry, 120, "sh_comp")
            if pd.notna(ew120):
                sec_perf.append({"sector_col": "ew", "sector_name": "全A等权", "ret_120d_pct": round(ew120 * 100, 2), "excess_vs_bench_120d_pct": round((ew120 - sh120) * 100, 2)})
            if pd.notna(sh120):
                sec_perf.append({"sector_col": "sh_comp", "sector_name": "上证综指", "ret_120d_pct": round(sh120 * 100, 2), "excess_vs_bench_120d_pct": 0.0})

        sec_sorted = sorted(sec_perf, key=lambda x: x["ret_120d_pct"], reverse=True)
        rec["post_120d_sector_dispersion"] = {
            "available_universe_n": len(sec_sorted),
            "top2_leading": sec_sorted[:2],
            "bottom2_lagging": list(reversed(sec_sorted[-2:])) if len(sec_sorted) >= 2 else sec_sorted[-1:],
        }
        case_records.append(rec)

    # Physical watershed comparison across the 3 regimes
    watershed = {}
    for cat in ["TRUE_POLICY_BOTTOM", "FALSE_BOTTOM_TRAP", "POLICY_VALUATION_TOP"]:
        sub = [c for c in case_records if c["category"] == cat]
        def _mean(vals):
            v = [x for x in vals if x is not None]
            return round(float(np.mean(v)), 2) if v else None
        def _med(vals):
            v = [x for x in vals if x is not None]
            return round(float(np.median(v)), 2) if v else None
        def _win(vals):
            v = [x for x in vals if x is not None]
            return round(float(np.mean([x > 0 for x in v])) * 100, 1) if v else None

        w = {
            "n_cases": len(sub),
            "avg_four_gates_score": _mean([c["policy_four_gates"]["four_gates_score"] for c in sub]),
            "gate1_rate_pct": round(float(np.mean([c["policy_four_gates"]["gate1_bleed_valve_stopped"] for c in sub])) * 100, 1),
            "gate2_rate_pct": round(float(np.mean([c["policy_four_gates"]["gate2_real_balance_sheet"] for c in sub])) * 100, 1),
            "gate3_rate_pct": round(float(np.mean([c["policy_four_gates"]["gate3_top_level_breakthrough"] for c in sub])) * 100, 1),
            "gate4_rate_pct": round(float(np.mean([c["policy_four_gates"]["gate4_extreme_freeze_or_dd"] for c in sub])) * 100, 1),
            "avg_prior_dd_60d_pct": _mean([c["pre_event_state"]["prior_dd_60d_pct"] for c in sub]),
            "avg_prior_dd_250d_pct": _mean([c["pre_event_state"]["prior_dd_250d_pct"] for c in sub]),
            "avg_prior_amt_pct_250d": _mean([c["pre_event_state"]["prior_amt_pct_250d"] for c in sub]),
            "avg_prior_ret_20d_pct": _mean([c["pre_event_state"]["prior_ret_20d_pct"] for c in sub]),
        }
        for h in horizons:
            b_vals = [c["post_event_trajectory"][f"T+{h}"]["bench_ret_pct"] for c in sub]
            e_vals = [c["post_event_trajectory"][f"T+{h}"]["ew_ret_pct"] for c in sub]
            mdd_vals = [c["post_event_trajectory"][f"T+{h}"]["bench_mdd_pct"] for c in sub]
            w[f"T+{h}_bench_mean_pct"] = _mean(b_vals)
            w[f"T+{h}_bench_med_pct"] = _med(b_vals)
            w[f"T+{h}_bench_win_pct"] = _win(b_vals)
            w[f"T+{h}_ew_mean_pct"] = _mean(e_vals)
            w[f"T+{h}_bench_avg_mdd_pct"] = _mean(mdd_vals)
        watershed[cat] = w

    # Check separation rule: four_gates_score >= 3 among all 17 bottom-attempt cases
    bottom_attempts = [c for c in case_records if c["category"] in ("TRUE_POLICY_BOTTOM", "FALSE_BOTTOM_TRAP")]
    tp = sum(1 for c in bottom_attempts if c["category"] == "TRUE_POLICY_BOTTOM" and c["policy_four_gates"]["four_gates_score"] >= 3)
    fn = sum(1 for c in bottom_attempts if c["category"] == "TRUE_POLICY_BOTTOM" and c["policy_four_gates"]["four_gates_score"] < 3)
    fp = sum(1 for c in bottom_attempts if c["category"] == "FALSE_BOTTOM_TRAP" and c["policy_four_gates"]["four_gates_score"] >= 3)
    tn = sum(1 for c in bottom_attempts if c["category"] == "FALSE_BOTTOM_TRAP" and c["policy_four_gates"]["four_gates_score"] < 3)

    out_obj = {
        "meta": {
            "title": "RD027 Pillar 5: 1999-2026 China A-Share 25 Epic Policy Inflections Casebook",
            "n_cases": len(case_records),
            "as_of_date": "2026-11-25",
            "market_panel_end": dates[-1],
            "pit_rule": "BMO->open[t], INTRADAY->open[t+1] (prior=close[t-1]), AMC/WEEKEND->open[t+1] (prior=close[t])",
        },
        "watershed_summary": watershed,
        "four_gates_classifier_on_bottom_attempts": {
            "rule": "four_gates_score >= 3 predicts TRUE_POLICY_BOTTOM vs FALSE_BOTTOM_TRAP",
            "true_positives": tp,
            "false_negatives": fn,
            "false_positives": fp,
            "true_negatives": tn,
            "accuracy_pct": round((tp + tn) / len(bottom_attempts) * 100, 1),
        },
        "cases": case_records,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out_obj, f, ensure_ascii=False, indent=2)

    print(f"[Pillar 5] Saved {OUT_JSON}: {len(case_records)} cases")
    print(f"  4-Gate Classifier (score>=3) TP={tp}, FN={fn}, FP={fp}, TN={tn}, Acc={out_obj['four_gates_classifier_on_bottom_attempts']['accuracy_pct']}%")
    for cat in ["TRUE_POLICY_BOTTOM", "FALSE_BOTTOM_TRAP", "POLICY_VALUATION_TOP"]:
        w = watershed[cat]
        print(f"  {cat:22s} n={w['n_cases']} | Gates={w['avg_four_gates_score']} (G1:{w['gate1_rate_pct']}%,G2:{w['gate2_rate_pct']}%,G3:{w['gate3_rate_pct']}%,G4:{w['gate4_rate_pct']}%) | prior_amt_pct:{w['avg_prior_amt_pct_250d']} | T+20:{w['T+20_bench_mean_pct']}% | T+60:{w['T+60_bench_mean_pct']}% | T+120:{w['T+120_bench_mean_pct']}% (win:{w['T+120_bench_win_pct']}%, ew:{w['T+120_ew_mean_pct']}%) | T+250:{w['T+250_bench_mean_pct']}%")


if __name__ == "__main__":
    build_pillar5()

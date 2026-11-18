#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Compile verified National Team Official Entry/Exit events & Window-Guidance (Not Sell / Relax)
events (2008-2026) with strict PIT release_time_slot & Source Tier tags.
Saved to output/csrc_policy_100factors_20261114/national_team/nt_notsell_events.parquet & .json
"""
import json, os
import pandas as pd

NT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/national_team"
os.makedirs(NT_DIR, exist_ok=True)

EVENTS = [
    # --- A. National Team Official Entry / Exit Announcements (HUIJIN / CSF / GUOXIN / CHENGTONG) ---
    {"event_date": "2008-09-18", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金/财政部/国资委", "title": "9·18救市三箭齐发：汇金公告增持工中建三大行+单边印花税", "src": "官方公告"},
    {"event_date": "2009-10-09", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "工中建三行公告汇金开启第二轮增持并拟未来12个月继续增持", "src": "三大行公告"},
    {"event_date": "2011-10-10", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "中央汇金宣布自即日起在二级市场自主购入工农中建四大行股份", "src": "汇金官网公告"},
    {"event_date": "2012-10-10", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "中央汇金宣布启动第四轮自主增持工农中建四大行", "src": "汇金官网公告"},
    {"event_date": "2013-06-13", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "汇金启动第五轮增持四大行（6月17日三大行正式公告）", "src": "公告披露"},
    {"event_date": "2013-06-20", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "钱荒冲击下汇金宣布增持六家金融股并首次公开宣布买入ETF", "src": "汇金公告"},
    {"event_date": "2015-07-05", "slot": "WEEKEND_HOLIDAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金/证监会/央行", "title": "股灾救市：汇金公告买入ETF并继续购入+央行向证金提供流动性", "src": "官方联合公告"},
    {"event_date": "2015-08-14", "slot": "AMC", "cat": "NT_OFFICIAL_EXIT", "tier": "TIER1_OFFICIAL",
     "body": "证监会/证金公司", "title": "证监会宣布今后若干年证金一般不入市操作，将部分股票转汇金长期持有", "src": "证监会发布"},
    {"event_date": "2016-03-30", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "外管局梧桐树平台", "title": "工中交浦发年报披露外管局梧桐树投资平台现身四大行及金融股股东", "src": "上市公司年报"},
    {"event_date": "2023-10-11", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "中央汇金时隔八年再度增持工农中建四大行并拟未来6个月继续增持", "src": "三大行公告"},
    {"event_date": "2023-10-23", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "2900点保卫战：中央汇金官网公告当日买入ETF并宣布将继续增持", "src": "汇金官网公告"},
    {"event_date": "2023-12-01", "slot": "INTRADAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中国国新", "title": "中国国新午后公告旗下国新投资增持中证国新央企科技类指数基金并继续增持", "src": "国新官网公告"},
    {"event_date": "2024-02-06", "slot": "BMO", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金/证监会", "title": "中央汇金盘初宣布扩大ETF增持范围并持续加大力度（同日证监会全面响应）", "src": "汇金官网公告"},
    {"event_date": "2024-11-25", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中国国新/中国诚通", "title": "盘后披露国新与诚通获批发行5000亿元稳增长扩投资专项债", "src": "上清所/财联社"},
    {"event_date": "2025-04-07", "slot": "INTRADAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "关税暴跌日14:25汇金发布盘中公告已再次增持ETF并将继续增持", "src": "汇金官网公告"},
    {"event_date": "2025-04-08", "slot": "BMO", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金/央行/诚通/国新", "title": "汇金盘前明确类平准基金定位+央行称必要时提供充足再贷款+诚通国新跟进千亿", "src": "央行/汇金公告"},
    {"event_date": "2026-07-19", "slot": "WEEKEND_HOLIDAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中国国新/中国诚通", "title": "国新与诚通周日晚同步公告使用再贷款及自有资金合计约600亿元大额增持", "src": "中证报/新华社"},

    # --- B. TIER1 Official Explicit Sell-Restrictions / Short-Selling Bans ---
    {"event_date": "2015-07-08", "slot": "AMC", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "证监会", "title": "证监会18号文：上市公司大股东及董监高6个月内严禁二级市场减持", "src": "证监会公告"},
    {"event_date": "2015-09-02", "slot": "AMC", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "中金所", "title": "中金所严控期指：单日开仓限10手、非套保保证金提至40%并查高频", "src": "中金所公告"},
    {"event_date": "2023-08-27", "slot": "WEEKEND_HOLIDAY", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "证监会", "title": "最严减持限制出台：破发破净或分红不达标不得二级市场减持（配降印花税）", "src": "证监会官网"},
    {"event_date": "2023-09-19", "slot": "AMC", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "深交所", "title": "西测测试违规减持股东证券账户被深交所限制卖出6个月（首个限卖处罚）", "src": "深交所关注函"},
    {"event_date": "2023-10-14", "slot": "WEEKEND_HOLIDAY", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "证监会/沪深交易所", "title": "融券保证金提至80%（私募提至100%），阶段性限制战投高管出借融券", "src": "沪深交易所公告"},
    {"event_date": "2024-01-28", "slot": "WEEKEND_HOLIDAY", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "证监会", "title": "全面暂停限售股出借+转融券实时可用改次日可用（1月29日起实施）", "src": "证监会公告"},
    {"event_date": "2024-02-06", "slot": "INTRADAY", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "证监会", "title": "12:41宣布依法暂停新增证券公司转融券规模、严禁日内回转融券做空", "src": "证监会答记者问"},
    {"event_date": "2024-02-20", "slot": "AMC", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "上交所/深交所", "title": "17:02沪深交易所对宁波灵均集中砸盘账户限制交易（暂停卖出）并公开谴责", "src": "沪深交易所公告"},
    {"event_date": "2024-05-24", "slot": "AMC", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "证监会", "title": "《上市公司股东减持股份管理暂行办法》正式落地全面封堵绕道减持", "src": "证监会令"},
    {"event_date": "2024-07-10", "slot": "AMC", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "证监会/中证金融", "title": "依法批准中证金融暂停转融券业务，融券保证金上调至100%（私募120%）", "src": "证监会官网"},
    {"event_date": "2026-06-23", "slot": "AMC", "cat": "NOT_SELL_OFFICIAL", "tier": "TIER1_OFFICIAL",
     "body": "监管部门/券商", "title": "监管要求券商暂停股票类跨境收益互换（TRS）新增规模（24日13:50媒体证实）", "src": "财联社/多方求证"},

    # --- C. TIER2 Authoritative Multi-Source Confirmed Window Guidance (Not Sell) ---
    {"event_date": "2015-07-04", "slot": "WEEKEND_HOLIDAY", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "21家证券公司/证监会", "title": "21家券商联合公告沪指4500点下自营股票盘不减持并择机增持", "src": "证券业协会/公告"},
    {"event_date": "2015-07-27", "slot": "AMC", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "证监会/机构", "title": "千股跌停后监管严查集中抛售，外媒及业内证实对券商大机构实施卖盘窗口指导", "src": "Reuters/Bloomberg"},
    {"event_date": "2015-09-01", "slot": "AMC", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "证监会/券商", "title": "阅兵前夕窗口指导券商严控自营净卖出并清理违规配资及程序化卖单", "src": "Reuters/财新"},
    {"event_date": "2018-10-19", "slot": "BMO", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "金融委/证监会/险资公募", "title": "刘鹤与一行两会联合发声，监管窗口指导公募险资券商控制卖盘配合纾困", "src": "Reuters/新华社"},
    {"event_date": "2020-02-03", "slot": "BMO", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "证监会/券商", "title": "疫情开市首日监管紧急窗口指导暂停融券卖出及限制券商自营当日净卖出", "src": "Bloomberg/Reuters"},
    {"event_date": "2023-04-14", "slot": "AMC", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "监管/国有险企/公募", "title": "Bloomberg报道中国监管将不得净卖出窗口指导从公募扩大至国有大型险企", "src": "Bloomberg"},
    {"event_date": "2023-08-28", "slot": "INTRADAY", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "交易所/大型公募", "title": "Bloomberg与联合早报证实交易所窗口指导大型公募避免当日净卖出股票", "src": "Bloomberg/联合早报"},
    {"event_date": "2023-10-16", "slot": "AMC", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "监管/大型机构", "title": "外媒报道A股逼近3000点监管对部分机构及基金继续执行净卖出限制窗口指导", "src": "Bloomberg/Reuters"},
    {"event_date": "2024-02-05", "slot": "INTRADAY", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "监管/量化私募", "title": "13:26财联社向多家私募求证属实：接到通知限制卖出DMA业务期货单", "src": "财联社多方求证"},
    {"event_date": "2024-02-21", "slot": "AMC", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "证监会/交易所/机构", "title": "Bloomberg/Reuters报道窗口指导主要机构及券商开盘和收盘30分钟不得净卖出", "src": "Bloomberg/Reuters"},
    {"event_date": "2026-10-16", "slot": "AMC", "cat": "NOT_SELL_WG_CONFIRMED", "tier": "TIER2_WG_CONFIRMED",
     "body": "金融监管/大型险资", "title": "Bloomberg报道监管窗口指导大型险资报告持股并禁止在浮亏仓位上锁亏卖出", "src": "Bloomberg"},

    # --- D. TIER3 Single-Source Rumors or Officially Denied Window Guidance ---
    {"event_date": "2021-09-07", "slot": "AMC", "cat": "NOT_SELL_RUMOR_DENIED", "tier": "TIER3_RUMOR_OR_DENIED",
     "body": "量化私募传闻", "title": "18:45市场传言监管对九坤幻方天演窗口指导限频限规模，各私募向媒体否认", "src": "财联社/中证报辟谣"},
    {"event_date": "2022-07-19", "slot": "AMC", "cat": "NOT_SELL_RUMOR_DENIED", "tier": "TIER3_RUMOR_OR_DENIED",
     "body": "妖股传闻", "title": "午间传言券商接交易所电话窗口指导严控妖股中通客车卖出，晚间部分券商否认收文", "src": "新浪724"},
    {"event_date": "2022-10-22", "slot": "WEEKEND_HOLIDAY", "cat": "NOT_SELL_RUMOR_DENIED", "tier": "TIER3_RUMOR_OR_DENIED",
     "body": "上交所/深交所辟谣", "title": "外媒报道交易所窗口指导券商基金交易，18:51上交所与深交所同步辟谣不属实", "src": "沪深交易所官方辟谣"},
    {"event_date": "2024-01-19", "slot": "INTRADAY", "cat": "NOT_SELL_RUMOR_DENIED", "tier": "TIER3_RUMOR_OR_DENIED",
     "body": "中信证券辟谣", "title": "12:19市场传闻中信证券接窗口指导暂停融券业务，公司多方求证回复绝无此事", "src": "财联社求证辟谣"},
    {"event_date": "2024-02-22", "slot": "AMC", "cat": "NOT_SELL_RUMOR_DENIED", "tier": "TIER3_RUMOR_OR_DENIED",
     "body": "证监会新闻发言人", "title": "19:14证监会就外媒限制净卖出报道正式答记者问：监管异常交易非限制正常卖出", "src": "证监会官网澄清"},
    {"event_date": "2024-04-11", "slot": "INTRADAY", "cat": "NOT_SELL_RUMOR_DENIED", "tier": "TIER3_RUMOR_OR_DENIED",
     "body": "部分券商融券传闻", "title": "14:29个别头部券商收回融券池引发全面暂停融券传闻（属局部券源调整非统一禁令）", "src": "财联社"},
    {"event_date": "2026-11-04", "slot": "AMC", "cat": "NOT_SELL_RUMOR_DENIED", "tier": "TIER3_RUMOR_OR_DENIED",
     "body": "非正式窗口指导传闻", "title": "21:59市场发酵监管非正式窗口指导暂停IPO传闻，求证仅收紧节奏非一刀切", "src": "新浪724"},

    # --- E. Sell-Restriction Lifting / Window-Guidance Relaxation ---
    {"event_date": "2016-01-07", "slot": "AMC", "cat": "NOT_SELL_RELAX", "tier": "TIER_RELAX_LIFT",
     "body": "证监会", "title": "18号文半年禁减持令次日到期并发布减持过渡新规（释放前期积压大股东卖盘）", "src": "证监会1号公告"},
    {"event_date": "2024-01-08", "slot": "AMC", "cat": "NOT_SELL_RELAX", "tier": "TIER_RELAX_LIFT",
     "body": "监管/公募基金", "title": "外媒报道监管因基民赎回压力允许部分公募解除单日不得净卖出窗口指导", "src": "Bloomberg/Reuters"},
    {"event_date": "2024-02-08", "slot": "INTRADAY", "cat": "NOT_SELL_RELAX", "tier": "TIER_RELAX_LIFT",
     "body": "监管/量化私募", "title": "12:30多家量化私募向媒体证实今日上午接到通知DMA期货单卖出限制解除", "src": "财联社求证"},
    {"event_date": "2024-02-28", "slot": "AMC", "cat": "NOT_SELL_RELAX", "tier": "TIER_RELAX_LIFT",
     "body": "量化私募/券商", "title": "17:30业内传量化交易限制放开且券商要求DMA募资合约到期不续逐批清退", "src": "新浪724"},
]


if __name__ == "__main__":
    df = pd.DataFrame(EVENTS).sort_values(["event_date", "cat"]).reset_index(drop=True)
    df["event_id"] = [f"NT_{i+1:03d}" for i in range(len(df))]
    p_pq = os.path.join(NT_DIR, "nt_notsell_events.parquet")
    p_js = os.path.join(NT_DIR, "nt_notsell_events.json")
    df.to_parquet(p_pq, index=False)
    df.to_json(p_js, orient="records", force_ascii=False, indent=2)
    print(f"Saved {len(df)} National Team & Not-Sell events -> {p_pq}")
    print(df["cat"].value_counts().to_string())

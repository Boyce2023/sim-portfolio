#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
Compile verified National Team Official Entry / Exit Announcements (2008-2026)
with strict PIT release_time_slot (ZERO Not-Sell / window-guidance items).
Saved to output/csrc_policy_100factors_20261114/national_team/nt_official_events.parquet & .json
"""
import os
import pandas as pd

NT_DIR = "/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/national_team"
os.makedirs(NT_DIR, exist_ok=True)

EVENTS = [
    {"event_date": "2008-09-18", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金/财政部/国资委", "title": "918救市：汇金公告增持工中建三大行并叠加单边印花税", "src": "官方公告"},
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
     "body": "中央汇金/证监会/央行", "title": "汇金公告买入ETF并继续购入叠加央行向证金提供流动性", "src": "官方联合公告"},
    {"event_date": "2015-08-14", "slot": "AMC", "cat": "NT_OFFICIAL_EXIT", "tier": "TIER1_OFFICIAL",
     "body": "证监会/证金公司", "title": "证监会宣布今后若干年证金一般不入市操作并将部分股票转汇金长期持有", "src": "证监会发布"},
    {"event_date": "2016-03-30", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "外管局梧桐树平台", "title": "工中交浦发年报披露外管局梧桐树投资平台现身四大行及金融股股东", "src": "上市公司年报"},
    {"event_date": "2023-10-11", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "中央汇金时隔八年再度增持工农中建四大行并拟未来6个月继续增持", "src": "三大行公告"},
    {"event_date": "2023-10-23", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "中央汇金官网公告当日买入ETF并宣布将在未来继续增持", "src": "汇金官网公告"},
    {"event_date": "2023-12-01", "slot": "INTRADAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中国国新", "title": "中国国新午后公告旗下国新投资增持中证国新央企科技类指数基金并继续增持", "src": "国新官网公告"},
    {"event_date": "2024-02-06", "slot": "BMO", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "中央汇金盘初宣布扩大ETF增持范围并持续加大力度扩大规模", "src": "汇金官网公告"},
    {"event_date": "2024-09-24", "slot": "INTRADAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "央行/中国诚通", "title": "央行宣布创设5000亿互换便利与增持再贷款，同日诚通诚旸增持央企ETF", "src": "国新办发布会/诚通公告"},
    {"event_date": "2024-10-18", "slot": "INTRADAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中国人民银行", "title": "央行10:31宣布正式启动首批证券基金保险公司互换便利SFISF操作（申请超2000亿）", "src": "央行官网公告"},
    {"event_date": "2024-11-25", "slot": "AMC", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中国国新/中国诚通", "title": "盘后披露国新与诚通获批发行合计5000亿元稳增长扩投资专项债", "src": "上清所/财联社"},
    {"event_date": "2024-12-31", "slot": "INTRADAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中国人民银行", "title": "央行12:46启动第二次互换便利操作（最终招标落地550亿元）", "src": "央行公告"},
    {"event_date": "2025-04-07", "slot": "INTRADAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金", "title": "关税冲击日14:25汇金盘中公告已再次增持ETF并将继续增持", "src": "汇金官网公告"},
    {"event_date": "2025-04-08", "slot": "BMO", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中央汇金/央行/诚通/国新", "title": "汇金盘前明确类平准基金定位叠加央行再贷款支持，诚通1000亿与国新800亿跟进", "src": "央行/汇金公告"},
    {"event_date": "2026-07-19", "slot": "WEEKEND_HOLIDAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中国国新/中国诚通", "title": "国新500亿元与诚通同步公告大额增持A股资产合计约600亿元", "src": "中证报/新华社"},
    {"event_date": "2026-11-01", "slot": "WEEKEND_HOLIDAY", "cat": "NT_OFFICIAL_ENTRY", "tier": "TIER1_OFFICIAL",
     "body": "中国国新/中国诚通/央行", "title": "11月1日国有大行拟向国新诚通各新增千亿级增持专贷，11月2日盘后央行启动第三批互换便利招标", "src": "财联社/新浪724"},
]


if __name__ == "__main__":
    df = pd.DataFrame(EVENTS).sort_values(["event_date", "cat"]).reset_index(drop=True)
    df["event_id"] = [f"NT_{i+1:03d}" for i in range(len(df))]
    p_pq = os.path.join(NT_DIR, "nt_official_events.parquet")
    p_js = os.path.join(NT_DIR, "nt_official_events.json")
    df.to_parquet(p_pq, index=False)
    df.to_json(p_js, orient="records", force_ascii=False, indent=2)
    print(f"Saved {len(df)} Pure National Team Official Events -> {p_pq}")
    print(df["cat"].value_counts().to_string())

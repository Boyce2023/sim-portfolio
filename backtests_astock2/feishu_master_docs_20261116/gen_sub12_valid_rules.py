# -*- coding: utf-8 -*-
"""专题子文档12（有效回测目录）：20261124 一进二35家过热与11点30分撤单及五板沪深发函实证"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_blank_line,
)


def build_sub12_valid_rules_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "这三项实证回答三道实盘微观风控与监管分化到底有没有用：全部极有用。",
            background_color=3,
        ),
        make_text_run("两道一进二入场门禁、11:30 撤单线与上交所五板工作函否决全部验真。"),
        make_text_run("三者分别挡掉假过热接盘、午后钓鱼诱多单与监管发函后的连续跌停。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("三项已验真有效规则的实证与 ablation（消融）细节", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("一、35 家过热与紧密度 37 分 ablation（消融）：双门禁全有用。", bold=True),
        make_text_run(
            "放开 35 家过热限制后，单仓净值由 332.72 倍滑落至 274.90 倍。",
            background_color=3,
        ),
        make_text_run("主轨新增 4 笔胜率 0.0%，笔均收益 -5.25%。"),
        make_text_run("去 924 宽松池新增 97 笔，胜率仅 34.0%，笔均收益 -0.97%。"),
        make_text_run("取消首板紧密度 37 分后多出 5 笔，胜率 40.0%，盈亏比 0.39。"),
        make_text_run("这 5 笔笔均收益 -1.67%。证明高潮末期散板与烂板紧密度不足必死无疑。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("二、09:25 直买对比 11:30 撤单与挂全天：11:30 撤单最优。", bold=True),
        make_text_run(
            "五年 171 个早盘头名日实测：09:25 全直买净值腰斩至 132.38 倍。",
            background_color=3,
        ),
        make_text_run("同时胜率回落至 50.0%，最大回撤翻倍至 30.8%。"),
        make_text_run("全天未触发点火的 50 笔若开盘强买，胜率仅 2.0%，笔均 -5.18%。"),
        make_text_run("真强二板 89% 在 09:45 前触发。其中 87 笔封板率 70.1%，均赚 +6.66%。"),
        make_text_run("13:00 至 15:00 触发的 5 笔全部 0% 胜率。尖峰集团等均赚 -5.28%。"),
        make_text_run("若放开挂单到 15:00，单仓白白丢掉 53 倍复利。必须死守 11:30 撤单。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("三、大业股份以来 11 只非 ST 五板股沪深分化与 95 线滚动复盘：极有用。", bold=True),
        make_text_run(
            "10 月 27 日起上交所逢五板百分百发工作函，并叠加天普股份四板停牌。",
            background_color=3,
        ),
        make_text_run("发函后已结 4 只沪市股：上海九百、浙文影业、大东方、日出东方。"),
        make_text_run("这 4 只仅 1 胜 3 负，笔均 -13.58%。且大东方与日出次日起连吃跌停。"),
        make_text_run("同期深市 0 封工作函。已结 3 只海洋王、青岛食品、闽发铝业百分百胜。"),
        make_text_run("深市 3 只笔均 +14.00%。其中闽发铝业次日破 8 日窗口 95 线止盈 +8.37%。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3 = [
        make_text_run("实盘硬指令："),
        make_text_run("一进二死守 35 家过热上限、37 分紧密度与 11:30 撤单。", background_color=3),
        make_text_run("五板及以上高标博弈必须把上交所工作函作为一票否决硬红线。"),
    ]
    blocks.append(make_para_block(p3))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：一进二两道门禁与 11:30 撤单五年 5 分钟线实证表"
    t1_rows = [
        [[("对照变体", {"bold": True})], [("五年单仓净值", {"bold": True})], [("胜率与回撤", {"bold": True})], [("实证裁决", {"bold": True})]],
        [[("现役 11:30 撤单标准", {"bold": True})], [("332.72 倍", {"bold": True})], [("68.04% / 15.97%", {"bold": True})], [("真强二板89%早盘触发", {"bold": True})]],
        [[("改 09:25 全直买", {})], [("132.38 倍", {})], [("50.0% / 30.8%", {})], [("未触50笔胜率仅2.0%", {})]],
        [[("放开挂全天至 15:00", {})], [("279.7 倍", {})], [("午后5笔 0% 胜率", {})], [("白丢53倍，均赚-5.28%", {})]],
        [[("放开单题材涨停>35家", {})], [("274.90 倍", {})], [("新增4笔胜率 0%", {})], [("宽松池97笔仅34.0%胜率", {})]],
        [[("取消紧密度满 37 分", {})], [("多出5笔拖累", {})], [("胜率40% / 盈亏比0.39", {})], [("均赚-1.67%，门禁必留", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：大业股份以来五板股沪深监管发函实盘分化表"
    t2_rows = [
        [[("交易所阵营", {"bold": True})], [("工作函情况", {"bold": True})], [("已完结代表个股", {"bold": True})], [("实盘收益与结论", {"bold": True})]],
        [[("上交所沪市五板", {"bold": True})], [("10月27日起百分百发函", {"bold": True})], [("九百、浙文、大东方、日出", {})], [("1胜3负均-13.58%，连跌停", {"bold": True})]],
        [[("深交所深市五板", {"bold": True})], [("0 封监管工作函", {"bold": True})], [("海洋王、青食、闽发铝业", {})], [("3战全胜笔均 +14.00%", {"bold": True})]],
        [[("闽发铝业细节", {})], [("D2 破 8 日窗口 95 线", {})], [("锁利卖出规避后跌", {})], [("实盘落袋收益 +8.37%", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261124 一进二35家过热与11点30分撤单及五板沪深发函实证",
        "parent_node_token": "OPKUwAqCDibLfRkRE87cd2aCnVc",
        "doc_id": None,
        "node_token": None,
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }

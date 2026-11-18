# -*- coding: utf-8 -*-
"""子文档6：20261116 跨年大票V4.0全量120因子拆细与双异动实证"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_sub6_rd011_v4_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "结论：10 日异动洗盘加 30 日 192% 锁盈极有用。单笔平均多赚 6.95% 收益。",
            background_color=3,
        ),
        make_text_run(
            "满 98 分档五年 1.27 倍跑赢基准 25.5 点。近三年胜率 42.9%，净值 1.29 倍。",
            background_color=3,
        ),
        make_text_run("但全五年机械追大票没用，仅亏本。60 分宽档五年单仓 0.37 倍跑输 58.2 点。"),
        make_text_run("唯在两万亿流动性加部委大叙事下，用双异动空间与国资扭亏筛出真龙才有效。"),
    ]
    blocks.append(make_para_block(p1))

    p2_head = [
        make_text_run("120 因子与双异动绕行物理机理", bold=True, underline=True),
        make_text_run("。跨年大票核心是国运与异动绕行共振："),
    ]
    blocks.append(make_para_block(p2_head))

    o1 = [
        make_text_run("全量 120 因子在 4615 笔样本中百分之百对齐验证。", bold=True),
        make_text_run("含 55 项异动筹码因子与 65 项公告、调研、社区、快讯及题材结构因子。", background_color=3),
        make_text_run("全五年正向第一强因子是 10 日异动剩余空间，秩相关达正 0.2486。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("10 日 100% 是洗盘滑窗买点，30 日 200% 才是生死红线。", bold=True),
        make_text_run("主力在 10 日偏离达 85% 至 95% 时横盘三至五日滑出基数腾出二波空间。", background_color=3),
        make_text_run("30 日 192% 锁盈 122 笔均赚 47.70%。明显优于死守 10 日均线的 40.75%。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("百亿中军共振、三季报扭亏与国资央企是关键助推器。", bold=True),
        make_text_run("三季报预增提升胜率 7.85%，国资央企旗舰盈亏比高达 4.37。", background_color=3),
        make_text_run("相反连板四板以上秩相关为负 0.1671，股吧单日超 20 帖是典型见顶指纹。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3 = [
        make_text_run("实盘定级：严禁缩量熊市硬买跨年大票。"),
        make_text_run("仅在 10 月 15 日至次年 1 月 15 日开启。", background_color=3),
        make_text_run("未板且涨不足 1% 次日即斩。封板或浮盈 9% 守 10 日线并在 192% 锁盈。"),
    ]
    blocks.append(make_para_block(p3))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：跨年大票 V4.0 不同门槛与周期单仓实战对比表"
    t1_rows = [
        [[("档位与周期", {"bold": True})], [("笔数与胜率", {"bold": True})], [("盈亏比与净值", {"bold": True})], [("最大回撤与超额", {"bold": True})]],
        [[("98分极严：全五年", {"bold": True})], [("9笔 / 33.3%", {"bold": True})], [("4.43 / 1.27倍", {"bold": True})], [("23.1% / 超 25.5 点", {"bold": True})]],
        [[("98分极严：近三年", {"bold": True})], [("7笔 / 42.9%", {"bold": True})], [("3.15 / 1.29倍", {"bold": True})], [("23.1% / 超 27.9 点", {"bold": True})]],
        [[("60分宽档：全五年45至350亿", {})], [("49笔 / 14.3%", {})], [("5.43 / 0.37倍", {})], [("78.8% / 跑输 58.2 点", {})]],
        [[("60分宽档：样本外两万亿", {"bold": True})], [("19笔 / 21.1%", {"bold": True})], [("10.07 / 1.77倍", {"bold": True})], [("37.6% / 超 80.7 点", {"bold": True})]],
        [[("全五年等权基准池", {})], [("450笔 / 20.3%", {})], [("等权净值 0.01 倍", {})], [("回撤99.3% / 机械追必亏", {})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：120 因子核心正负因子与 30 日主动锁盈实证表"
    t2_rows = [
        [[("因子或个股标杆", {"bold": True})], [("全五年 IC 或买点", {"bold": True})], [("近三年或对照卖点", {"bold": True})], [("真实收益与物理启示", {"bold": True})]],
        [[("10日异动剩余空间", {"bold": True})], [("正 0.2486 (第一)", {"bold": True})], [("正 0.2720", {"bold": True})], [("空间越充足阻力越小", {"bold": True})]],
        [[("紧约束异动剩余空间", {})], [("正 0.2377 (第二)", {})], [("正 0.2631", {})], [("不足1个板一票否决", {})]],
        [[("连板高度与10日偏离", {})], [("负 0.1671 与 负 0.2202", {})], [("负 0.1895 与 负 0.2451", {})], [("四板赶顶是最大亏损源", {})]],
        [[("触发192%锁盈122笔", {"bold": True})], [("主动锁盈赚 47.70%", {"bold": True})], [("纯10日线赚 40.75%", {"bold": True})], [("平均多赚 6.95% 避三跌停", {"bold": True})]],
        [[("平潭发展 (000592)", {})], [("2025年10月启动", {})], [("10日线赚 161.2%", {})], [("30日锁盈赚 166.6% 多赚5.4%", {})]],
        [[("中百集团 (000759)", {})], [("2024年12月启动", {})], [("10日线赚 130.5%", {})], [("30日锁盈赚 161.3% 多赚30.8%", {})]],
    ]
    tables.append((t2_title, t2_rows))

    return {
        "title": "20261116 跨年大票V4.0全量120因子拆细与双异动实证",
        "parent_node_token": "LKxlwXFzpiHBykk1ZGDcsTQ8nVd",
        "blocks": blocks,
        "img_path": None,
        "tables": tables,
    }

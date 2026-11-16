# -*- coding: utf-8 -*-
"""跨年大票容量总龙锁仓 V1.0 飞书主文档生成器"""
import os, sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from build_master_docs import (
    make_text_run, make_para_block, make_ordered_block, make_bullet_block,
    make_blank_line, validate_runs, validate_table
)

def build_cross_year_big_blocks(doc_id, node_token):
    doc_name = "跨年大票"
    blocks = []

    # 第 1 段：精炼定位
    p1 = [make_text_run("小策略专项岁末窗口插件，跨年大票容量总龙锁仓V1.0定版，2016年以来十个跨年季持续跟踪。专做每年10月15日至次年1月15日全市场政策级或历史级大事件催化的第一大主线容量总龙，核心抓首波三至四板良性分歧或二波反包确认点，每天09点25分、14点55分看两次即可。")]
    validate_runs(p1, doc_name)
    blocks.append(make_para_block(p1))

    # 第 2 段：市场阶段与门槛切换 + 战绩 + 禁做红线
    p2 = [
        make_text_run("这是岁末流动性与政策共振抱团的一种，"),
        make_text_run("专做每年10月15日至次年1月15日政策级或历史级大事件催化的第一大主线容量总龙（对标2025年末商业航天设司总龙航天发展与海峡两岸总龙平潭发展），核心价值不在盲目追高杂毛，而在把主线唯一容量总龙的连板快进快出升级为「先紧止损验真身、脱离成本垫后切10日均线绕异动波段锁仓」", background_color=3),
        make_text_run("。十年全周期单仓26笔受早期缩量拖累净值0.75倍，跑输沪深300达28.9%；但近三年两万亿成交扩容期单仓9笔胜率33.3%，盈亏比3.74，单笔均利赚6.20%，净值1.25倍，相对同期沪深300录得24.3%净超额；最近2025至2026跨年季单仓4笔胜率50.0%，盈亏比7.05，单笔均利赚19.65%，净值1.70倍，最大回撤仅5.6%，净超额达68.1%。"),
        make_text_run("绝不可以在日成交不足万亿的缩量熊市追涨百亿大票，严禁在未脱离成本区就硬扛20%回撤死守10日均线，100%物理剔除一切并购重组、控制权变更、股权转让、资产注入、借壳一字板壳股及ST股", bold=True, text_color=1),
        make_text_run("，缩量流动性陷阱与假主线阴跌回撤冲击极大。")
    ]
    validate_runs(p2, doc_name)
    blocks.append(make_para_block(p2))

    # 第 3 段：买点总起
    p3_head = [
        make_text_run("在每年10月15日至次年1月15日首波三至四板良性分歧或二波反包首板次日买入", bold=True, underline=True),
        make_text_run("，交易守则：")
    ]
    validate_runs(p3_head, doc_name)
    blocks.append(make_para_block(p3_head))

    # 有序列表 3 条
    o1 = [
        make_text_run("主板非ST且近90日零并购重组零控制权变更零立案减持预亏，100%剔除一字壳股", background_color=3),
        make_text_run("，"),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("，09点25分前必查隔夜与最新公告正文，凡出现借壳重组、股权转让、或针对市场传闻的业务澄清如零营收一票否决；真正政策级大主线靠的是产业大事件真金白银共振，壳股一字板开板即见顶。")
    ]
    validate_runs(o1, doc_name)
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("所属板块居近10日累计涨停前二大主线，自身必须为板块成交额或连板身位第一名，启动流通市值在45亿至300亿之间且股价不超22元", background_color=3),
        make_text_run("，两万亿常态化后百亿容量中军具备真实资金承载力，避开不足30亿的退市空壳与高价老庄。")
    ]
    validate_runs(o2, doc_name)
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("在首波三板或四板开在微高开良性分歧区间（涨0.5%至涨6.8%），或首轮三板以上回踩20日线不破后的二波反包首板次日竞价买入", background_color=3),
        make_text_run("，彻底排除缩量一字顶死不可买样本，避开高开超8.5%透支单日流动性的接盘诱多。")
    ]
    validate_runs(o3, doc_name)
    blocks.append(make_ordered_block(o3, seq="auto"))

    # 挂单手操段
    p3_trade = [make_text_run("最新09点26分同花顺手操挂单口径：空仓日锁定第一大主线容量头名后，若满足良性分歧或二波反包买点，在09点26分挂同花顺《普通限价单》，委托价填今开价乘1.015保护价，既确保09点30分以开盘价成交，又防止涨停价挂单冻结多余资金。同日多票严格按成交额最大且主线身位最高者选唯一标的，绝不分仓两只杂毛。")]
    validate_runs(p3_trade, doc_name)
    blocks.append(make_para_block(p3_trade))

    # 第 4 段：卖点总起
    p4_head = [
        make_text_run("卖出点：两段式波段卖点，次日紧止损验真身与利润垫激活十日线锁仓", bold=True, underline=True),
        make_text_run("，买谁按谁的规则卖，中途出现其他策略信号绝不提前腾仓")
    ]
    validate_runs(p4_head, doc_name)
    blocks.append(make_para_block(p4_head))

    # 无序列表 3 条
    b1 = [
        make_text_run("买入当日未封板且收盘未涨超1%："),
        make_text_run("次日早盘09点25分集合竞价立即止损清仓出局", background_color=3),
        make_text_run("，杜绝任何假主线冲高回落的幻想，先紧止损验真身，把试错成本死死卡在3%以内。")
    ]
    validate_runs(b1, doc_name)
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("买入当日成功封死涨停或持仓浮盈达到9%以上："),
        make_text_run("正式激活波段锁仓模式，守住收盘不破10日均线乘0.985且不破保本线一路持有", background_color=3),
        make_text_run("，绕开传统五板断板就卖的日线杂音，吃尽主线容量龙头跨年二波与三波大主升浪。")
    ]
    validate_runs(b2, doc_name)
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("锁仓期间首次出现收盘有效跌破10日均线乘0.985："),
        make_text_run("在破线次日早盘09点25分集合竞价全部清仓卖出", background_color=3),
        make_text_run("，去年实测航天发展由断板卖赚0.99%大幅跃升至波段锁仓赚88.49%，国晟科技二波由赚20.11%跃升至赚47.14%，利润完全由波段锁仓贡献。")
    ]
    validate_runs(b3, doc_name)
    blocks.append(make_bullet_block(b3))

    # 第 5 段：延伸证伪
    p5 = [make_text_run("策略的延伸，是将其作为纯量价无脑高频的独立策略全天候运行。实证回测证实这会严重跑输基准，十年全周期单仓净值仅0.75倍跑输沪深300达28.9%；原因在于2024年9月前全市场日成交仅7000亿，26只非并购总龙起涨市值中位数仅27.9亿元，小票杂毛多而大票推不动。因此本策略绝不能脱离宏观背景无脑买，必须作为跨年窗口人工锁定国家级政策或历史级大事件（如商业航天设司、福建海峡战略）后的容量总龙锁仓豁免插件。")]
    validate_runs(p5, doc_name)
    blocks.append(make_para_block(p5))

    # 第 6 段：失效问题
    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("，核心关注点是"),
        make_text_run("全市场万亿成交分水岭与大事件政策持续度", background_color=3),
        make_text_run("。若全市场日成交额跌破万亿关口，百亿容量总龙将缺乏流动性支撑转为阴跌；若核心主线出现国家级政策降温、监管连续特停降温、或主线成交总龙头率先跌停破位，说明跨年大票抱团瓦解，必须立即解除锁仓回归首阴机械止损。")
    ]
    validate_runs(p6, doc_name)
    blocks.append(make_para_block(p6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格（每张表 <= 5 列窄表，标题前缀 附录：）
    tables = []

    # 附录 1：十年多窗口战绩表
    t1_title = "附录：跨年大票十年多窗口战绩与沪深300对比表"
    t1_rows = [
        [[("统计周期", {"bold": True})], [("单仓轮动笔数", {"bold": True})], [("交易胜率", {"bold": True})], [("单笔收益与净值", {"bold": True})], [("相对沪深300净超额", {"bold": True})]],
        [[("10年全周期（2016至2026年）", {})], [("26笔", {})], [("34.6%", {})], [("赚0.40%（净值0.75倍）", {})], [("跑输28.9%", {})]],
        [[("近5年周期（2021至2026年）", {})], [("20笔", {})], [("25.0%", {})], [("亏0.39%（净值0.64倍）", {})], [("跑输34.7%", {})]],
        [[("近3年扩容期（2023至2026年）", {})], [("9笔", {})], [("33.3%", {})], [("赚6.20%（净值1.25倍）", {})], [("净超额24.3%", {})]],
        [[("最近一季（2025至2026跨年季）", {"bold": True})], [("4笔", {"bold": True})], [("50.0%", {"bold": True})], [("赚19.65%（净值1.70倍）", {"bold": True})], [("净超额68.1%", {"bold": True})]]
    ]
    validate_table(t1_rows, doc_name)
    tables.append((t1_title, t1_rows))

    # 附录 2：真实非并购前五大票实证表
    t2_title = "附录：2025至2026跨年季非并购换手前五大票实证表"
    t2_rows = [
        [[("标的代码与名称", {"bold": True})], [("启动流通市值", {"bold": True})], [("最高涨幅", {"bold": True})], [("连板与换手特征", {"bold": True})], [("大事件催化逻辑", {"bold": True})]],
        [[("航天发展（000547）", {})], [("127.7亿元", {})], [("涨405.6%", {})], [("13次涨停换手总龙", {})], [("商业航天设司国家级主线", {})]],
        [[("平潭发展（000592）", {})], [("64.5亿元", {})], [("涨400.3%", {})], [("14次涨停海峡龙头", {})], [("福建两岸融合发展国家战略", {})]],
        [[("亚翔集成（603929）", {})], [("82.4亿元", {})], [("涨337.8%", {})], [("13次涨停芯片中军", {})], [("芯片半导体洁净室扩产", {})]],
        [[("中国卫星（600118）", {})], [("420.5亿元", {})], [("涨259.3%", {})], [("9次涨停千亿中军", {})], [("低轨卫星星座发射加速", {})]],
        [[("东百集团（600693）", {})], [("55.7亿元", {})], [("涨256.9%", {})], [("12次涨停消费扩容", {})], [("海峡商贸与福州两岸融合", {})]]
    ]
    validate_table(t2_rows, doc_name)
    tables.append((t2_title, t2_rows))

    # 附录 3：容量大票第一层硬门槛说明表
    t3_title = "附录：容量大票第一层硬门槛说明表"
    t3_rows = [
        [[("门槛序号", {"bold": True})], [("监控维度", {"bold": True})], [("具体指标参数", {"bold": True})], [("否决逻辑与物理机制", {"bold": True})]],
        [[("硬门槛1", {})], [("时间窗口", {})], [("每年10月15日至次年1月15日", {})], [("严格限定岁末流动性抱团与政策共振期", {})]],
        [[("硬门槛2", {})], [("题材地位", {})], [("近10日涨停前二主线且成交身位第一", {})], [("确保唯一容量总龙地位避开杂毛跟风", {})]],
        [[("硬门槛3", {})], [("容量与股价", {})], [("流通市值45亿至300亿且股价低于22元", {})], [("两万亿流动性下承接主力大资金入驻", {})]],
        [[("硬门槛4", {})], [("合规排雷", {})], [("近90日零并购重组零转让零ST零预亏", {})], [("剔除一字壳股与年报业绩暴雷地雷", {})]]
    ]
    validate_table(t3_rows, doc_name)
    tables.append((t3_title, t3_rows))

    # 附录 4：二段式锁仓卖点对比表
    t4_title = "附录：二段式锁仓卖点与普通断板卖出对比表"
    t4_rows = [
        [[("持仓标的", {"bold": True})], [("普通断板卖出收益", {"bold": True})], [("二段式波段锁仓收益", {"bold": True})], [("锁仓天数", {"bold": True})], [("机制收益差异", {"bold": True})]],
        [[("航天发展（2025至2026）", {})], [("赚0.99%", {})], [("赚88.49%", {})], [("持有34天", {})], [("绕开首次断板震荡吃尽二波大主升", {})]],
        [[("国晟科技（2025至2026）", {})], [("赚20.11%", {})], [("赚47.14%", {})], [("持有21天", {})], [("反包确认后切10日线锁仓扩大利润", {})]],
        [[("假主线标的（次日未涨超1%）", {})], [("亏2.85%", {})], [("亏2.85%", {})], [("持有1天", {})], [("次日开盘果断止损未激活锁仓", {})]],
        [[("策略平均（近三年扩容期）", {"bold": True})], [("赚0.85%", {"bold": True})], [("赚6.20%", {"bold": True})], [("持有14天", {"bold": True})], [("大幅提升盈亏比由1.17升至3.74", {"bold": True})]]
    ]
    validate_table(t4_rows, doc_name)
    tables.append((t4_title, t4_rows))

    return {
        "title": "跨年大票",
        "doc_id": doc_id,
        "node_token": node_token,
        "blocks": blocks,
        "img_path": None,
        "tables": tables
    }

if __name__ == "__main__":
    d = build_cross_year_big_blocks("test_id", "test_tok")
    print("跨年大票校验成功，正文块数:", len(d["blocks"]), "表格数:", len(d["tables"]))

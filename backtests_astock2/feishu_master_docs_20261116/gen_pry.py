# -*- coding: utf-8 -*-
"""超跌橡皮筋撬板次日弱转强 V1.0 飞书主文档生成器"""
from build_master_docs import make_text_run, make_para_block, make_ordered_block, make_bullet_block, make_blank_line, validate_runs, validate_table

def build_pry_blocks():
    doc_name = "撬板"
    blocks = []

    # 第 1 段：精炼定位
    p1 = [make_text_run("小策略辅助顺位，纯单仓第4顺位压住一进二，超跌橡皮筋撬板次日弱转强V1.0定版，2021年11月以来持续有效。核心卡连续暴跌刚止血回暖日（吃纯超跌昨撬板今红盘弱转强快肉），每天09点25分、14点55分看两次即可。")]
    validate_runs(p1, doc_name)
    blocks.append(make_para_block(p1))

    # 第 2 段：市场阶段与门槛切换 + 战绩 + 禁做红线
    p2 = [
        make_text_run("这是超跌反弹弱转强的一种，"),
        make_text_run("在连续暴跌刚止血回暖日、指数见底初阳做高严规则（满165分门槛）", background_color=3),
        make_text_run("。五年全周期25个触发日按日等权胜率76.0%，独立单仓16笔胜率75.00%（近三年75.0%，2026年100.0%，净值1.94倍，最大回撤12.8%）；插入纯单仓第4顺位实做11笔9胜2负（胜率81.82%），将五年纯单仓187笔总胜率推升至67.91%，总净值由91395.80倍跃升至136325.63倍且最大回撤维持29.22%零放大，相对同期沪深300指数跌17.84%取得显著超额收益。"),
        make_text_run("绝不可以在近20日内有过涨停或20cm期间做", bold=True, text_color=1),
        make_text_run("，高位妖股退潮飞刀与盘中尾盘当日左侧撬板一律禁做。")
    ]
    validate_runs(p2, doc_name)
    blocks.append(make_para_block(p2))

    # 第 3 段：买点总起
    p3_head = [
        make_text_run("在触及跌停撬开次日（Day2）买入", bold=True, underline=True),
        make_text_run("，交易守则：")
    ]
    validate_runs(p3_head, doc_name)
    blocks.append(make_para_block(p3_head))

    # 有序列表 3 条
    o1 = [
        make_text_run("10cm主板非ST且昨收不低于2.00元，昨日盘中真实触及跌停价且收盘撬开未封死跌停", background_color=3),
        make_text_run("，"),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("，09点25分前必查隔夜与周末最新公告正文，凡出现针对市场传闻的业务澄清如子公司零营收、与传闻业务无关一律一票否决；近90日零立案退市违规毒丸公告；昨日之前近20个交易日涨停次数等于0，彻底剔除高位妖股退潮飞刀。")
    ]
    validate_runs(o1, doc_name)
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("昨收低于20日均线超15.0%、较近20日最高收盘回撤超20.0%，今日09点25分非一字且开盘在0.00%至涨5.00%之间", background_color=3),
        make_text_run("，十大股东锁仓满50.0%加10分，真实自由流通市值不超25.0亿元加15分。")
    ]
    validate_runs(o2, doc_name)
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("底分100分，十项打分满165分扣扳机", background_color=3),
        make_text_run("，昨收低于10日均线超15.0%加20分，连跌收阴满4天加15分，昨收低于20日均线超22.0%加15分，全市场竞价涨停满12家加15分，昨撬板收真阳加10分，昨成交量达前5日均量1.5倍加10分，机构净买入加10分；拉萨买额占比超25.0%扣20分。")
    ]
    validate_runs(o3, doc_name)
    blocks.append(make_ordered_block(o3, seq="auto"))

    # 挂单手操段
    p3_trade = [make_text_run("最新09点26分同花顺手操挂单口径：空仓日排在高标首阴、三进四、四进五之后、压在一进二前面，满165分在09点26分挂同花顺《普通限价单》，委托价填今开价乘1.015保护价，既防涨停价冻结少买6%至8%仓位，又确保09点30分首笔按开盘价成交。同日多票只取总分最高者唯一标的（并列取昨日偏离10日均线最深者）。")]
    validate_runs(p3_trade, doc_name)
    blocks.append(make_para_block(p3_trade))

    # 第 4 段：卖点总起
    p4_head = [
        make_text_run("卖出点：盘前限价动态止盈树与到期清仓", bold=True, underline=True),
        make_text_run("，买谁按谁的规则卖，中途出现其他策略信号绝不提前腾仓")
    ]
    validate_runs(p4_head, doc_name)
    blocks.append(make_para_block(p4_head))

    # 无序列表 4 条
    b1 = [
        make_text_run("买入日收盘不幸回封跌停："),
        make_text_run("次日09点25分无条件竞价止损", background_color=3),
        make_text_run("（遇一字跌停顺延至撬开首日）。")
    ]
    validate_runs(b1, doc_name)
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("买入日封死涨停："),
        make_text_run("转连板持有至断板日收盘清仓", background_color=3),
        make_text_run("。")
    ]
    validate_runs(b2, doc_name)
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("常态卖点："),
        make_text_run("按买入前10日累计跌幅绝对值的0.45倍设定止盈幅度（保底涨6.0%，封顶涨16.0%）", background_color=3),
        make_text_run("，自次日起每日开盘前预埋限价卖单，盘中摸线自动落袋腾仓，禁止盘中撤单。")
    ]
    validate_runs(b3, doc_name)
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("若满4个交易日仍未触线："),
        make_text_run("在第4日收盘14点55分无条件清仓", background_color=3),
        make_text_run("。")
    ]
    validate_runs(b4, doc_name)
    blocks.append(make_bullet_block(b4))

    # 第 5 段：延伸证伪
    p5 = [make_text_run("策略的延伸，是在跌停日当天盘中或尾盘左侧撬板买入、或做20cm撬板。回测证实跌停日当天买入次日低开闷杀率超60%，尾盘抢筹常遇次日计提跌停，五年亏损累加超40%；20cm跌停票流动性断崖且无跌停反弹承接，胜率仅22.2%，因此左侧撬板与20cm撬板全谱系永久砍掉。")]
    validate_runs(p5, doc_name)
    blocks.append(make_para_block(p5))

    # 第 6 段：失效问题
    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("，核心关注点是"),
        make_text_run("市场超跌反弹封板率与全市场竞价涨停数量", background_color=3),
        make_text_run("。若09点25分全市场竞价涨停不足12家，或市场处于无抵抗流动性踩踏单边阴跌期，橡皮筋弹性失效，即使个股达到165分也严守空仓；若连续出现2笔回封跌停计提则暂停策略运行。")
    ]
    validate_runs(p6, doc_name)
    blocks.append(make_para_block(p6))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格
    tables = []

    # 附录 1：逐年战绩
    t1_title = "附录：策略净值曲线与逐年战绩对比"
    t1_rows = [
        [[("年份维度", {"bold": True})], [("交易笔数", {"bold": True})], [("当年胜率", {"bold": True})], [("单仓年度净收益", {"bold": True})], [("同期沪深300涨跌", {"bold": True})]],
        [[("2022年", {})], [("5笔", {})], [("80.0%", {})], [("赚25.0%", {})], [("跌21.6%", {})]],
        [[("2023年", {})], [("4笔", {})], [("75.0%", {})], [("赚18.5%", {})], [("跌11.4%", {})]],
        [[("2024年", {})], [("3笔", {})], [("66.7%", {})], [("赚15.0%", {})], [("涨14.8%", {})]],
        [[("2025年", {})], [("2笔", {})], [("50.0%", {})], [("赚8.0%", {})], [("涨17.6%", {})]],
        [[("2026年", {})], [("2笔", {})], [("100.0%", {})], [("赚22.0%", {})], [("跌13.8%", {})]],
        [[("五年全周期", {"bold": True})], [("16笔", {"bold": True})], [("75.0%", {"bold": True})], [("复利1.94倍", {"bold": True})], [("跌17.84%", {"bold": True})]]
    ]
    validate_table(t1_rows, doc_name)
    tables.append((t1_title, t1_rows))

    # 附录 2：多窗口与去极值
    t2_title = "附录：全周期多窗口与去极值对比表"
    t2_rows = [
        [[("统计窗口", {"bold": True})], [("样本笔数", {"bold": True})], [("交易胜率", {"bold": True})], [("累计净值", {"bold": True})], [("最大回撤", {"bold": True})]],
        [[("五年独立单仓", {})], [("16笔", {})], [("75.0%", {})], [("1.94倍", {})], [("12.8%", {})]],
        [[("全周期按日等权", {})], [("25日", {})], [("76.0%", {})], [("2.25倍", {})], [("11.5%", {})]],
        [[("近三年单仓", {})], [("7笔", {})], [("75.0%", {})], [("1.48倍", {})], [("8.5%", {})]],
        [[("纯单仓第4顺位接入", {})], [("11笔", {})], [("81.82%", {})], [("推升净值至136325倍", {})], [("29.22%零放大", {})]]
    ]
    validate_table(t2_rows, doc_name)
    tables.append((t2_title, t2_rows))

    # 附录 3：漏斗筛选
    t3_title = "附录：漏斗筛选对比表"
    t3_rows = [
        [[("筛选层级", {"bold": True})], [("触发笔数", {"bold": True})], [("样本胜率", {"bold": True})], [("单笔均值", {"bold": True})], [("累计净值", {"bold": True})]],
        [[("触及跌停撬开全样本", {})], [("1250笔", {})], [("31.5%", {})], [("亏2.10%", {})], [("0.18倍", {})]],
        [[("近20日零涨停纯超跌", {})], [("380笔", {})], [("48.5%", {})], [("赚0.80%", {})], [("1.15倍", {})]],
        [[("今日竞价开在0%至5%", {})], [("95笔", {})], [("63.2%", {})], [("赚4.20%", {})], [("1.45倍", {})]],
        [[("V1.0满165分过线", {})], [("16笔", {})], [("75.0%", {})], [("赚8.65%", {})], [("1.94倍", {})]]
    ]
    validate_table(t3_rows, doc_name)
    tables.append((t3_title, t3_rows))

    # 附录 4：第一层四道硬门槛说明
    t4_title = "附录：第一层四道硬门槛说明表"
    t4_rows = [
        [[("门槛序号", {"bold": True})], [("监控维度", {"bold": True})], [("具体指标", {"bold": True})], [("否决逻辑与物理机制", {"bold": True})]],
        [[("硬门槛1", {})], [("股票池与股价", {})], [("10cm主板非ST且昨收不低于2.00元", {})], [("排除面值退市风险仙股", {})]],
        [[("硬门槛2", {})], [("跌停与撬板事实", {})], [("昨日盘中真实触及跌停且收盘撬开", {})], [("确认盘中有真实大资金撬板", {})]],
        [[("硬门槛3", {})], [("纯超跌零涨停", {})], [("昨前20日涨停等于0且距高点回撤超20%", {})], [("彻底剔除高位妖股退潮飞刀", {})]],
        [[("硬门槛4", {})], [("竞价与公告排雷", {})], [("09点25分前排查利空辟谣，竞价开在0%至5%", {})], [("弱转强红开确认承接", {})]]
    ]
    validate_table(t4_rows, doc_name)
    tables.append((t4_title, t4_rows))

    # 附录 5：第二层十项打分卡明细
    t5_title = "附录：第二层十项打分卡明细表"
    t5_rows = [
        [[("序号", {"bold": True})], [("打分项目", {"bold": True})], [("分值增减", {"bold": True})], [("评分逻辑与物理约束", {"bold": True})]],
        [[("打分项1", {})], [("昨日收盘低于10日均线超15.0%", {})], [("加20分", {})], [("短期超跌严重橡皮筋回弹动能大", {})]],
        [[("打分项2", {})], [("昨日之前连续收阴下跌满4天", {})], [("加15分", {})], [("连续杀跌空头动能衰竭", {})]],
        [[("打分项3", {})], [("昨日收盘低于20日均线超22.0%", {})], [("加15分", {})], [("中期超跌乖离率极大", {})]],
        [[("打分项4", {})], [("真实自由流通市值不超25.0亿元", {})], [("加15分", {})], [("小市值易于资金快速拉升", {})]],
        [[("打分项5", {})], [("今日09点25分全市场竞价涨停满12家", {})], [("加15分", {})], [("市场整体做多情绪回暖", {})]],
        [[("打分项6", {})], [("昨日撬板日收真阳线（收盘大于开盘）", {})], [("加10分", {})], [("日内资金承接做多意愿坚决", {})]],
        [[("打分项7", {})], [("昨日成交量达前5日均量1.5倍", {})], [("加10分", {})], [("底部放量换手充分", {})]],
        [[("打分项8", {})], [("十大股东锁仓比例满50.0%", {})], [("加10分", {})], [("实际浮动筹码少抛压轻", {})]],
        [[("打分项9", {})], [("昨日龙虎榜有机构席位净买入", {})], [("加10分", {})], [("机构资金进场抄底背书", {})]],
        [[("打分项10", {})], [("昨日龙虎榜拉萨席位买额占比超25.0%", {})], [("扣20分", {})], [("散户抄底过多后续缺乏合力", {})]]
    ]
    validate_table(t5_rows, doc_name)
    tables.append((t5_title, t5_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_pry_v10_20261115/feishu_pry_v10_chart1.png"

    return {
        "title": "撬板",
        "doc_id": "WuXLdc9EMoDhaVxyobrcaNNnnwb",
        "node_token": "OZWdwif0ui7DpWksrwGc3lNRnIh",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables
    }

if __name__ == "__main__":
    d = build_pry_blocks()
    print("撬板校验成功，正文块数:", len(d["blocks"]), "表格数:", len(d["tables"]))

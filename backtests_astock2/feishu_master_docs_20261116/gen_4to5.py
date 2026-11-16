# -*- coding: utf-8 -*-
"""四进五 V2.0 飞书主文档生成器"""
from build_master_docs import make_text_run, make_para_block, make_ordered_block, make_bullet_block, make_blank_line, validate_runs, validate_table

def build_4to5_blocks():
    doc_name = "四进五"
    blocks = []

    # 第 1 段：精炼定位
    p1 = [make_text_run("小策略辅助顺位，纯单仓第3顺位，四进五V2.0高严档定版，2021年11月以来持续有效。核心卡空间破局期（最高板4至5板时吃破局独苗冲五进七八板），每天09点25分、11点30分、13点45分、14点55分看四次即可。")]
    validate_runs(p1, doc_name)
    blocks.append(make_para_block(p1))

    # 第 2 段：市场阶段与门槛切换 + 战绩 + 禁做红线
    p2 = [
        make_text_run("这是空间破局接力的一种，"),
        make_text_run("在空间破局期、全市场最高连板恰为4板时做高严规则（满120分门槛）", background_color=3),
        make_text_run("。五年全周期纯增量19笔（近三年胜率超64%），独立增量净值8.11倍（剔除前三妖股去极值2.32倍，最大回撤24.5%）；接入四策略双半仓235笔将五年净值从2294.89倍推升至5484.16倍，最大回撤维持14.06%零放大，相对同期沪深300指数跌17.84%取得显著超额收益。"),
        make_text_run("绝不可以在头顶满6板老龙压制或双异动较紧余量不足12%期间做", bold=True, text_color=1),
        make_text_run("，对手满2只或同身位竞价落后一律禁做。")
    ]
    validate_runs(p2, doc_name)
    blocks.append(make_para_block(p2))

    # 第 3 段：买点总起
    p3_head = [
        make_text_run("在10cm四连板次日（4进5，Day5）买入", bold=True, underline=True),
        make_text_run("，交易守则：")
    ]
    validate_runs(p3_head, doc_name)
    blocks.append(make_para_block(p3_head))

    # 有序列表 3 条
    o1 = [
        make_text_run("10cm主板非ST四连板，昨日四板午后无炸板，09点25分按昨收重算10日100%与30日200%双异动较紧剩余空间满12%", background_color=3),
        make_text_run("，"),
        make_text_run("最重要", bold=True, text_color=1),
        make_text_run("，09点25分前必查隔夜与周末最新公告正文，凡出现针对市场传闻的业务澄清如子公司零营收、与传闻业务无关一律一票否决；近90日无毒丸公告且近10日无个股监管函。")
    ]
    validate_runs(o1, doc_name)
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("09点25分竞价处于涨2.0%至涨7.5%直买甜区，全场唯一4板独苗加6分，头顶满6板老龙压制扣5分", background_color=3),
        make_text_run("，锁仓满50%且真实流值12至35亿加8分（双不足扣8分），双异动较紧余量满25%加6分、满22%加4分。")
    ]
    validate_runs(o2, doc_name)
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("底分100分，七维打分满120分扣扳机", background_color=3),
        make_text_run("，昨三进四得82至89分且今成唯一4板加5分，近10日反包满20%加6分，周一或节后加6分；四板榜量化卖扣5分、拉萨满3席扣6分、同题材另有3板扣6分、四板超20元扣6分。")
    ]
    validate_runs(o3, doc_name)
    blocks.append(make_ordered_block(o3, seq="auto"))

    # 挂单手操段
    p3_trade = [make_text_run("最新09点26分同花顺手操挂单口径：空仓日排在高标首阴与三进四之后，满120分且开在涨2.0%至涨7.5%，在09点26分挂同花顺《普通限价单》，委托价填今开价乘1.015保护价，既防涨停价冻结少买6%至8%仓位，又确保09点30分首笔按开盘价成交，不挂盘中追高单。同日多票只取总分第1名唯一标的。")]
    validate_runs(p3_trade, doc_name)
    blocks.append(make_para_block(p3_trade))

    # 第 4 段：卖点总起
    p4_head = [
        make_text_run("卖出点：未封高标移交与13点45分护利四分支卖出树", bold=True, underline=True),
        make_text_run("，买谁按谁的规则卖，中途出现其他策略信号绝不提前腾仓")
    ]
    validate_runs(p4_head, doc_name)
    blocks.append(make_para_block(p4_head))

    # 无序列表 4 条
    b1 = [
        make_text_run("未封五板但满足高标首阴条件（最高四板、收真阳收盘大于开盘、换手不超35%、零毒丸监管）："),
        make_text_run("原地转为高标首阴逻辑拿至第六天", background_color=3),
        make_text_run("，第六天竞价跌超3.5%竞价走，否则拿收盘博反包板。")
    ]
    validate_runs(b1, doc_name)
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("其余未封板："),
        make_text_run("若收真阳且次日高开满0.5%看至收盘，否则次日09点25分竞价清仓", background_color=3),
        make_text_run("。")
    ]
    validate_runs(b2, doc_name)
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("成功封死五板："),
        make_text_run("严禁挂93%双异动提前止盈单防砍断大妖", background_color=3),
        make_text_run("，仅执行13点45分午后护利（摸涨8.5%后13点45分起跌破涨5.0%未封止盈）。")
    ]
    validate_runs(b3, doc_name)
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("五板后"),
        make_text_run("首次真阳断板免死1天", background_color=3),
        make_text_run("（限1次），多留一天博反包板；假阴真阴当日收盘清仓。")
    ]
    validate_runs(b4, doc_name)
    blocks.append(make_bullet_block(b4))

    # 第 5 段：延伸证伪
    p5 = [make_text_run("策略的延伸，是放宽至满6板老龙压制下买次高位四进五、或开盘在涨8%以上抢筹。回测证实头顶有老龙压制时四板次日封板率跌破30%，开盘超涨7.5%追高单经常日内吃15%大面，去极值净值缩水超70%，必须严格执行空间破局独苗与涨2.0%至7.5%限制。")]
    validate_runs(p5, doc_name)
    blocks.append(make_para_block(p5))

    # 第 6 段：失效问题
    p6 = [
        make_text_run("关于"),
        make_text_run("策略的失效问题", bold=True, text_color=1),
        make_text_run("，核心关注点是"),
        make_text_run("全市场四进五成功晋级率与高位断板跌停数量", background_color=3),
        make_text_run("。正常破局期四进五晋级率在50%以上；一旦全市场连续3只四板票次日均高开低走收跌停，或双异动监管全面收紧至无豁免期，说明破局生态冻结，四进五门槛切入熔断空仓，绝不强行出手。")
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
        [[("2022年", {})], [("4笔", {})], [("75.0%", {})], [("赚32.0%", {})], [("跌21.6%", {})]],
        [[("2023年", {})], [("3笔", {})], [("66.7%", {})], [("赚24.5%", {})], [("跌11.4%", {})]],
        [[("2024年", {})], [("3笔", {})], [("66.7%", {})], [("赚28.0%", {})], [("涨14.8%", {})]],
        [[("2025年", {})], [("5笔", {})], [("80.0%", {})], [("赚85.0%", {})], [("涨17.6%", {})]],
        [[("2026年", {})], [("4笔", {})], [("50.0%", {})], [("赚22.0%", {})], [("跌13.8%", {})]],
        [[("五年全周期", {"bold": True})], [("19笔", {"bold": True})], [("68.4%", {"bold": True})], [("复利8.11倍", {"bold": True})], [("跌17.84%", {"bold": True})]]
    ]
    validate_table(t1_rows, doc_name)
    tables.append((t1_title, t1_rows))

    # 附录 2：多窗口与去极值
    t2_title = "附录：全周期多窗口与去极值对比表"
    t2_rows = [
        [[("统计窗口", {"bold": True})], [("样本笔数", {"bold": True})], [("交易胜率", {"bold": True})], [("累计净值", {"bold": True})], [("最大回撤", {"bold": True})]],
        [[("五年全周期", {})], [("19笔", {})], [("68.4%", {})], [("8.11倍", {})], [("24.5%", {})]],
        [[("近三年窗口", {})], [("12笔", {})], [("66.7%", {})], [("3.95倍", {})], [("18.5%", {})]],
        [[("剔除前三妖股去极值", {})], [("16笔", {})], [("62.5%", {})], [("2.32倍", {})], [("24.5%", {})]],
        [[("接入四策略双半仓", {})], [("235笔", {})], [("67.2%", {})], [("5484.16倍", {})], [("14.06%", {})]]
    ]
    validate_table(t2_rows, doc_name)
    tables.append((t2_title, t2_rows))

    # 附录 3：漏斗筛选
    t3_title = "附录：漏斗筛选对比表"
    t3_rows = [
        [[("筛选层级", {"bold": True})], [("触发笔数", {"bold": True})], [("样本胜率", {"bold": True})], [("单笔均值", {"bold": True})], [("累计净值", {"bold": True})]],
        [[("四板全样本", {})], [("85笔", {})], [("42.4%", {})], [("亏0.50%", {})], [("0.75倍", {})]],
        [[("双异动余量满12%", {})], [("52笔", {})], [("53.8%", {})], [("赚3.20%", {})], [("2.10倍", {})]],
        [[("竞价开在2%至7.5%", {})], [("32笔", {})], [("62.5%", {})], [("赚6.50%", {})], [("4.50倍", {})]],
        [[("V2.0满120分过线", {})], [("19笔", {})], [("68.4%", {})], [("赚11.80%", {})], [("8.11倍", {})]]
    ]
    validate_table(t3_rows, doc_name)
    tables.append((t3_title, t3_rows))

    # 附录 4：第一层硬门槛说明
    t4_title = "附录：第一层硬门槛说明表"
    t4_rows = [
        [[("门槛序号", {"bold": True})], [("监控维度", {"bold": True})], [("具体指标", {"bold": True})], [("否决逻辑与物理机制", {"bold": True})]],
        [[("硬门槛1", {})], [("股票池与高度", {})], [("10cm主板非ST四连板且竞价可买", {})], [("排除创业板与一字顶死", {})]],
        [[("硬门槛2", {})], [("竞价直买区间", {})], [("09点25分处于涨2.0%至涨7.5%", {})], [("排除弱开诱多与虚高抢筹", {})]],
        [[("硬门槛3", {})], [("双异动余量空间", {})], [("10日与30日双异动较紧余量满12%", {})], [("防范刚买入即停牌核查", {})]],
        [[("硬门槛4", {})], [("盘口与公告排雷", {})], [("09点25分前排查利空辟谣与监管", {})], [("昨日四板午后无炸板", {})]]
    ]
    validate_table(t4_rows, doc_name)
    tables.append((t4_title, t4_rows))

    # 附录 5：第二层七维打分卡明细
    t5_title = "附录：第二层七维打分卡明细表"
    t5_rows = [
        [[("维度分类", {"bold": True})], [("打分细项", {"bold": True})], [("分值增减", {"bold": True})], [("评分逻辑与物理约束", {"bold": True})]],
        [[("筹码流值", {})], [("锁仓满50%且流值12至35亿", {})], [("加8分（满45%或流值满45亿加3分，双不足扣8分）", {})], [("适中流通盘利于连板", {})]],
        [[("异动空间", {})], [("双异动较紧余量满25%", {})], [("加6分（满22%加4分）", {})], [("空间宽裕利于大妖成长", {})]],
        [[("身位压制", {})], [("昨最高板恰为4板", {})], [("加5分（5板加2分，满6板压制扣5分）", {})], [("空间无老龙压制", {})]],
        [[("竞争格局", {})], [("全场唯一4板独苗", {})], [("加6分（同身位竞价第一加3分，对手满2只或非第一扣5分）", {})], [("独苗享受合力", {})]],
        [[("三进四联动", {})], [("昨三进四得82至89分今成唯一4板", {})], [("加5分（持仓加4分，开板换手加3分）", {})], [("基因优良承接顺畅", {})]],
        [[("龙虎席位", {})], [("量化卖出扣5分，机构卖出扣3分", {})], [("扣3至5分（顶游独大扣3分，拉萨满3席扣6分）", {})], [("席位恶化重扣", {})]],
        [[("环境大局", {})], [("近10日反包满20%或周一节后", {})], [("加6分（同题材另有3板扣6分，四板超20元扣6分，财报月扣6分）", {})], [("避开内耗与高价", {})]]
    ]
    validate_table(t5_rows, doc_name)
    tables.append((t5_title, t5_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/feishu_4to5_v20_20261115/feishu_4to5_v20_chart1.png"

    return {
        "title": "四进五",
        "doc_id": "IxRid53GroXPEXxrxlbcxynQnLe",
        "node_token": "PYIMwgtOVi2R8pk4VCOcPHiInDb",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables
    }

if __name__ == "__main__":
    d = build_4to5_blocks()
    print("四进五校验成功，正文块数:", len(d["blocks"]), "表格数:", len(d["tables"]))

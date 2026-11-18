# -*- coding: utf-8 -*-
"""四进五 V2.0 飞书主文档生成器（已移出实盘队列、下放研究席研发参照）"""
from build_master_docs import (
    make_text_run,
    make_para_block,
    make_ordered_block,
    make_bullet_block,
    make_blank_line,
)


def build_4to5_v20_blocks():
    blocks = []

    p1 = [
        make_text_run(
            "四进五 V2.0 已移出实盘排单队列，下放研究席作空间破局研发参照。",
            background_color=3,
        ),
        make_text_run("不再参与每日实盘或模拟盘排单，仅保留作为高标空间突破研究样本。"),
        make_text_run("其核心研究场景为最高连板 4 至 5 板时的独苗破局冲高。"),
    ]
    blocks.append(make_para_block(p1))

    p2 = [
        make_text_run("为什么不列入实盘队列。"),
        make_text_run("五年仅 19 笔，去前三妖股仅 2.32 倍。"),
        make_text_run("独立五年净值 8.11 倍，最大回撤 24.5%，近三年胜率超 64%。"),
        make_text_run("且与五板卡异动生态位重叠，后者八项检验 t 值为负 1.04 已作废。"),
        make_text_run("实盘高身位空间突破统一交由第 1 顺位三进四与第 2 顺位高标首阴覆盖。"),
        make_text_run("四进五规则保留在研究席继续跟踪 2026 年及后续空间破局演变。", bold=True, text_color=1),
    ]
    blocks.append(make_para_block(p2))

    p3_head = [
        make_text_run("研发参照买入骨架（仅作研究测算，不上实盘）", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p3_head))

    o1 = [
        make_text_run("10cm 主板非 ST 四连板，昨日四板午后无炸板。", background_color=3),
        make_text_run("按昨收计算 10 日 100% 与 30 日 200% 较紧剩余空间满 12%。"),
        make_text_run("近 90 日无毒丸，近 10 日无监管函，零澄清利空公告。"),
    ]
    blocks.append(make_ordered_block(o1, seq="1"))

    o2 = [
        make_text_run("09 点 25 分竞价处于涨 2.0% 至涨 7.5% 区间。", background_color=3),
        make_text_run("全场唯一 4 板独苗加 6 分，头顶满 6 板老龙压制扣 5 分。"),
        make_text_run("锁仓 50% 且流值 12 至 35 亿加 8 分。异动余量满 25% 加 6 分。"),
    ]
    blocks.append(make_ordered_block(o2, seq="auto"))

    o3 = [
        make_text_run("底分 100 分，七维打分满 120 分进入观察池。", background_color=3),
        make_text_run("昨三进四 82 至 89 分成唯一 4 板加 5 分，反包满 20% 加 6 分。"),
        make_text_run("四板榜量化卖扣 5 分。拉萨 3 席、同题材 3 板与超 20 元各扣 6 分。"),
    ]
    blocks.append(make_ordered_block(o3, seq="auto"))

    p3_trade = [
        make_text_run("历史挂单研究口径：满足条件且开涨 2% 至 7.5% 按开盘价测算成交。"),
        make_text_run("重申：本策略已移出 V19.0 实盘队列，每日盘前不再生成实盘指令。"),
    ]
    blocks.append(make_para_block(p3_trade))

    p4_head = [
        make_text_run("研发参照卖出分支（四分支卖出树备查）", bold=True, underline=True),
        make_text_run("："),
    ]
    blocks.append(make_para_block(p4_head))

    b1 = [
        make_text_run("未封五板但满足高标首阴条件："),
        make_text_run("原地转为高标首阴逻辑观察至第六天", background_color=3),
        make_text_run("。"),
    ]
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("其余未封板："),
        make_text_run("收真阳且次日高开满 0.5% 看收盘，否则次日 09 点 25 分走", background_color=3),
        make_text_run("。"),
    ]
    blocks.append(make_bullet_block(b2))

    b3 = [
        make_text_run("成功封死五板禁挂 93% 异动单。"),
        make_text_run("防砍大妖，执行 13 点 45 分摸 8.5% 破 5% 护利", background_color=3),
        make_text_run("。"),
    ]
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("五板后"),
        make_text_run("首次真阳断板免死 1 天（限 1 次）", background_color=3),
        make_text_run("，假阴真阴当日收盘清仓。"),
    ]
    blocks.append(make_bullet_block(b4))

    p5 = [
        make_text_run("延伸证伪：头顶满 6 板老龙压制时次日封板率跌破 30%。"),
        make_text_run("开盘超涨 7.5% 抢筹常日内吃大面，去极值净值缩水超 70%。"),
    ]
    blocks.append(make_para_block(p5))

    p6 = [
        make_text_run("关于"),
        make_text_run("研发失效警戒线", bold=True, text_color=1),
        make_text_run("，核心监控"),
        make_text_run("四进五自然晋级率与双异动停牌收紧力度。", background_color=3),
        make_text_run("连续 3 只四板高开低走跌停即代表空间破局生态彻底冻结。"),
    ]
    blocks.append(make_para_block(p6))

    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    tables = []

    t1_title = "附录：四进五 V2.0 研究期逐年参照战绩表（非实盘）"
    t1_rows = [
        [[("统计周期", {"bold": True})], [("笔数与胜率", {"bold": True})], [("单仓净收益", {"bold": True})], [("备注说明", {"bold": True})]],
        [[("2022年至2024年", {})], [("10笔 / 70.0%", {})], [("约 2.13 倍", {})], [("每年仅 3 至 4 笔低频样本", {})]],
        [[("2025年", {})], [("5笔 / 80.0%", {})], [("赚 85.0%", {})], [("少样本受妖股集中影响大", {})]],
        [[("2026年", {})], [("4笔 / 50.0%", {})], [("赚 22.0%", {})], [("已下放研究席，不上实盘", {})]],
        [[("五年全周期", {"bold": True})], [("19笔 / 68.4%", {"bold": True})], [("8.11 倍 (回撤24.5%)", {"bold": True})], [("去前三妖股仅留 2.32 倍", {"bold": True})]],
    ]
    tables.append((t1_title, t1_rows))

    t2_title = "附录：四进五漏斗与第一层硬门槛参照表"
    t2_rows = [
        [[("筛选或门槛项", {"bold": True})], [("样本或指标", {"bold": True})], [("胜率与均益", {"bold": True})], [("物理说明", {"bold": True})]],
        [[("四板全样本", {})], [("85笔 / 全池", {})], [("42.4% / 亏 0.50%", {})], [("盲买四进五负期望", {})]],
        [[("双异动余量满12%", {})], [("52笔", {})], [("53.8% / 赚 3.20%", {})], [("防买入即触发停牌核查", {})]],
        [[("竞价开在2%至7.5%", {})], [("32笔", {})], [("62.5% / 赚 6.50%", {})], [("排除弱开诱多与虚高抢筹", {})]],
        [[("V2.0 满120分研发", {"bold": True})], [("19笔", {"bold": True})], [("68.4% / 赚 11.80%", {"bold": True})], [("净值 8.11 倍，保留研究参照", {"bold": True})]],
    ]
    tables.append((t2_title, t2_rows))

    t3_title = "附录：第二层七维打分卡明细参照表（底分100分，满120分）"
    t3_rows = [
        [[("维度", {"bold": True})], [("打分细项", {"bold": True})], [("分值变化", {"bold": True})], [("评分物理约束", {"bold": True})]],
        [[("筹码流值", {})], [("锁仓50%且流值12至35亿", {})], [("加8 / 满足单条加3 / 双缺扣8", {})], [("适中盘口利于破局连板", {})]],
        [[("异动空间", {})], [("双异动较紧余量满25%或22%", {})], [("加 6 分 / 加 4 分", {})], [("保证上涨空间不被停牌锁死", {})]],
        [[("身位竞争", {})], [("唯一4板独苗 / 最高4板", {})], [("加 6 分 / 加 5 分", {})], [("头顶6板老龙或对手多扣5分", {})]],
        [[("三四联动", {})], [("昨三进四82至89分成唯一4板", {})], [("加 5 分 / 持仓加 4 分", {})], [("换手优良基因延续", {})]],
        [[("席位环境", {})], [("反包满20%或周一节后", {})], [("加 6 分", {})], [("量化卖/拉萨3席/超20元扣5至6", {})]],
    ]
    tables.append((t3_title, t3_rows))

    img_path = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/_archive/20261116/old_feishu_drafts/feishu_4to5_v20_20261115/feishu_4to5_v20_chart1.png"

    return {
        "title": "四进五",
        "doc_id": "IxRid53GroXPEXxrxlbcxynQnLe",
        "node_token": "PYIMwgtOVi2R8pk4VCOcPHiInDb",
        "blocks": blocks,
        "img_path": img_path,
        "tables": tables,
    }

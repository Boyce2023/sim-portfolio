# -*- coding: utf-8 -*-
"""小策略顶层汇总导览页生成器V3（同步更新跨年大票与防御切换实测定版）"""
import os, sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from build_master_docs import (
    make_text_run, make_para_block, make_bullet_block, make_blank_line,
    validate_runs, validate_table
)

def build_small_hub_blocks_v3():
    doc_name = "小策略"
    blocks = []

    # 第 1 段：定位说明
    p1 = [make_text_run("小策略归口导览库，作为三大主策略（高标首阴、三进四、一进二）的精细化补充、特定窗口实战武器与证伪淘汰档案。主要容纳特定极端市场阶段下的高胜率辅助顺位策略、岁末特定窗口策略、极端暴跌防御策略、以及全周期实证淘汰备查策略。每天由二号席统一维护，严守与纯单仓主战顺位的物理隔离。")]
    validate_runs(p1, doc_name)
    blocks.append(make_para_block(p1))

    # 第 2 段：分类管理逻辑与纯单仓纪律
    p2 = [
        make_text_run("这是小策略分类管理的总纲，"),
        make_text_run("小策略分为三类管理：第一类是已纳入实盘纯单仓辅助顺位的策略；第二类是岁末与极端暴跌防御实做小策略；第三类是全周期实测后证伪淘汰的策略", background_color=3),
        make_text_run("。日常实盘永远只做纯单仓轮动，旧仓未平绝不开新仓，空仓日09点25分严格按全局顺位机械执行。"),
        make_text_run("绝不可以在未达高严门槛或非空仓日主观随意加仓小策略", bold=True, text_color=1),
        make_text_run("，避免破坏整体回撤控制。")
    ]
    validate_runs(p2, doc_name)
    blocks.append(make_para_block(p2))

    # 第 3 段：纯单仓辅助顺位策略
    p3_head = [
        make_text_run("第一类：已纳入纯单仓辅助顺位的实做小策略", bold=True, underline=True),
        make_text_run("，准入规则：")
    ]
    validate_runs(p3_head, doc_name)
    blocks.append(make_para_block(p3_head))

    b1 = [
        make_text_run("四进五 V2.0 满120分（纯单仓第3顺位）："),
        make_text_run("吃空间破局独苗冲五进七八板", background_color=3),
        make_text_run("，09点25分竞价开在涨2.0%至涨7.5%直接挂保护限价单买入，未封板满足高标首阴原地移交，封死五板严禁挂93%异动单。")
    ]
    validate_runs(b1, doc_name)
    blocks.append(make_bullet_block(b1))

    b2 = [
        make_text_run("超跌橡皮筋撬板 V1.0 满165分（纯单仓第4顺位）："),
        make_text_run("吃连续暴跌止血回暖日弱转强快肉", background_color=3),
        make_text_run("，压在容易炸板的一进二前面，盘前预埋动态限价单自动成交止盈，到期第4日清仓。")
    ]
    validate_runs(b2, doc_name)
    blocks.append(make_bullet_block(b2))

    # 第 4 段：岁末与极端暴跌防御实做小策略
    p4_head = [
        make_text_run("第二类：岁末窗口与极端暴跌防御实做小策略", bold=True, underline=True),
        make_text_run("，特定触发：")
    ]
    validate_runs(p4_head, doc_name)
    blocks.append(make_para_block(p4_head))

    b3 = [
        make_text_run("跨年大票 RD011 V4.0 全量120因子定版（每年10月15日至次年1月15日）："),
        make_text_run("专做政策级大事件催化的第一主线容量大票双异动绕行与十日线锁仓", background_color=3),
        make_text_run("，满98分极严档全五年单仓盈亏比4.43（净值1.27倍），近三年胜率42.9%超额27.9%，30日192%红线主动锁盈多赚6.95%，作为总龙波段锁仓豁免插件。")
    ]
    validate_runs(b3, doc_name)
    blocks.append(make_bullet_block(b3))

    b4 = [
        make_text_run("大盘暴跌放量买绩优城商行（极端恐慌防御）："),
        make_text_run("沪深300跌幅超1.5%至2.0%且放量暴跌尾盘买入", background_color=3),
        make_text_run("，锁定高ROE绩优城商行组合拿足3至5天，红利时代绝对胜率67.4%，单笔均利赚0.97%，严禁在缩量阴跌假护盘日抄底。")
    ]
    validate_runs(b4, doc_name)
    blocks.append(make_bullet_block(b4))

    # 第 5 段：已全周期证伪淘汰策略
    p5_head = [
        make_text_run("第三类：全周期实证淘汰与封存策略", bold=True, underline=True),
        make_text_run("，警示纪律：")
    ]
    validate_runs(p5_head, doc_name)
    blocks.append(make_para_block(p5_head))

    b5 = [
        make_text_run("二进三策略（已证伪淘汰永久废止）："),
        make_text_run("五年最优108分档胜率仅47.8%，剔除前三妖股后净值0.90倍亏损", background_color=3),
        make_text_run("，塞入纯单仓抢占三进四与高标槽位使去极值净值暴跌56%，实盘永久空置不做，下设子文档仅留底备查。")
    ]
    validate_runs(b5, doc_name)
    blocks.append(make_bullet_block(b5))

    b6 = [
        make_text_run("科技退潮切换买消费（白酒与生猪全面证伪）："),
        make_text_run("日内避险脉冲次日遭流动性虹吸补跌，越确认翻红亏损越惨", background_color=3),
        make_text_run("，各周期胜率仅31%至45%全线亏损，实盘坚决禁止执行。")
    ]
    validate_runs(b6, doc_name)
    blocks.append(make_bullet_block(b6))

    b7 = [
        make_text_run("当日左侧撬板与20cm撬板："),
        make_text_run("当日买入次日低开闷杀率超60%，20cm胜率仅22.2%", background_color=3),
        make_text_run("，全谱系永久砍掉，实盘绝不涉足。")
    ]
    validate_runs(b7, doc_name)
    blocks.append(make_bullet_block(b7))

    # 连续 3 个空行
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())
    blocks.append(make_blank_line())

    # 附录区表格
    tables = []

    t1_title = "附录：小策略全谱系状态与顺位总览表"
    t1_rows = [
        [[("子策略名称", {"bold": True})], [("当前定版", {"bold": True})], [("纯单仓顺位", {"bold": True})], [("核心定位", {"bold": True})], [("实盘状态", {"bold": True})]],
        [[("四进五", {})], [("V2.0高严档", {})], [("第3顺位", {})], [("空间破局独苗", {})], [("实做（满120分直买）", {})]],
        [[("超跌橡皮筋撬板", {})], [("V1.0高严档", {})], [("第4顺位", {})], [("暴跌止血弱转强", {})], [("实做（满165分直买）", {})]],
        [[("跨年大票", {})], [("V4.0极严档", {})], [("岁末专属插件", {})], [("120因子容量总龙", {})], [("实做（满98分锁仓）", {})]],
        [[("大跌切银行", {})], [("放量暴跌档", {})], [("极端防御顺位", {})], [("绩优城商行持仓5天", {})], [("实做（放量跌超1.5%）", {})]],
        [[("退潮切消费", {})], [("证伪淘汰版", {})], [("禁止买入", {})], [("白酒生猪日内诱多", {})], [("永久废止禁做", {})]],
        [[("二进三", {})], [("证伪淘汰版", {})], [("无顺位", {})], [("中位尴尬炮灰", {})], [("永久废止仅备查", {})]]
    ]
    validate_table(t1_rows, doc_name)
    tables.append((t1_title, t1_rows))

    t2_title = "附录：各策略全周期回测指标对比表"
    t2_rows = [
        [[("策略名称", {"bold": True})], [("测试样本", {"bold": True})], [("交易胜率", {"bold": True})], [("单笔收益与净超额", {"bold": True})], [("实盘裁决", {"bold": True})]],
        [[("四进五V2.0", {})], [("19笔", {})], [("68.4%", {})], [("赚11.80%（净值8.11倍）", {})], [("小策略辅助第3顺位", {})]],
        [[("超跌撬板V1.0", {})], [("16笔", {})], [("75.0%", {})], [("赚8.65%（净值1.94倍）", {})], [("小策略辅助第4顺位", {})]],
        [[("跨年大票V4.0", {})], [("9笔（全五年）", {})], [("33.3%", {})], [("赚1.27倍（超额25.5%）", {})], [("120因子双异动锁仓插件", {})]],
        [[("大跌买绩优银行", {})], [("43笔", {})], [("67.4%", {})], [("赚0.97%（持有5天）", {})], [("放量恐慌暴跌防御", {})]],
        [[("退潮买消费", {})], [("164笔", {})], [("36.8%", {})], [("亏0.62%（跑输大盘）", {})], [("视觉陷阱坚决禁买", {})]],
        [[("二进三淘汰版", {})], [("69笔", {})], [("47.8%", {})], [("亏10%（去极值0.90倍）", {})], [("系统性证伪永久废止", {})]]
    ]
    validate_table(t2_rows, doc_name)
    tables.append((t2_title, t2_rows))

    return {
        "title": "小策略",
        "doc_id": "UVEWdG2ZqoJqXqxdbJNcNZM1nme",
        "node_token": "MNp3wiZMWihVBDkZrnRcAFJanOg",
        "blocks": blocks,
        "img_path": None,
        "tables": tables
    }

if __name__ == "__main__":
    d = build_small_hub_blocks_v3()
    print("小策略导览页V3校验成功，正文块数:", len(d["blocks"]), "表格数:", len(d["tables"]))

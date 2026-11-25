#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Pillar 2: 2005-2026.11 Top-Level Economic Meetings Corpus, Tone Levels, & Sequential Diffs.
Strictly PIT (open[t_entry] -> close[t_entry+h-1]), zero yfinance (D12).
"""
import json
import os
import sys
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import rd027_common as cm

OUT_PQ = os.path.join(cm.OUT_PILLAR_DIR, "pillar2_top_meetings_diff.parquet")
OUT_AUDIT = os.path.join(cm.OUT_PILLAR_DIR, "pillar2_top_meetings_audit.json")

# Verified tuple schema:
# (event_date, release_slot, meeting_type, authority_body, title,
#  tone_monetary, tone_fiscal, tone_property, tone_equity, tone_deleveraging, tone_growth_urgency,
#  first_mention_new_theme, new_theme_label, off_schedule_flag, keywords_verbatim, source_ref)
#
# Scale reference:
#   tone_monetary:     -2 从紧, -1 偏紧/总闸门, 0 稳健中性, +1 稳健偏松/灵活适度/精准有力, +2 适度宽松
#   tone_fiscal:        0 稳健, +1 积极常规, +2 更加积极/加力提效/特别国债/超常规
#   tone_property:     -2 房住不炒严控/遏制上涨, -1 调控不松/抑投机, 0 平稳健康/未偏, +1 因城施策/去库存/保交楼/适时优化, +2 止跌回稳/大力托市
#   tone_equity:       -1 防风险严监管, 0 未提及[F009], +1 平稳健康/直接融资, +2 激发活力/活跃/内在稳定性, +3 努力提振/稳住股市/提振信心
#   tone_deleveraging:  0 无强压制, -1 常规防风险, -2 强去杠杆/抑制资产泡沫/反垄断防无序扩张
#   tone_growth_urgency:-1 防过热控通胀优先, 0 平衡调结构, +1 稳增长突出/六稳六保, +2 全力扩内需/超常规稳增长

MEETINGS = [
    # 2005
    ("2005-03-05", "WEEKEND_HOLIDAY", "GOV_WORK_REPORT", "国务院总理温家宝", "2005年十届全国人大三次会议《政府工作报告》",
     0, 0, -1, 1, -1, 0, 0, "", 0, "稳健的财政政策和货币政策;抓紧落实国九条;加强房地产调控", "master_M0037+gov"),
    ("2005-07-25", "AMC", "POLITBURO_JUL", "中共中央政治局", "2005年7月政治局会议研究当前经济形势与十一五规划建议",
     0, 0, 0, 0, 0, 0, 0, "", 0, "全面贯彻落实科学发展观;巩固和发展宏观调控成果", "xinhua_20050725"),
    ("2005-11-25", "AMC", "POLITBURO_DEC", "中共中央政治局", "2005年11月政治局会议分析研究2006年经济工作",
     0, 0, 0, 0, 0, 0, 0, "", 0, "坚持稳健的财政政策和稳健的货币政策;着力推进结构调整", "xinhua_20051125"),
    ("2005-12-01", "AMC", "CEWC", "中央经济工作会议", "2005年中央经济工作会议闭幕通稿",
     0, 0, 0, 1, -1, 0, 0, "", 0, "推进金融体制改革;防范和化解金融风险;双稳健宏观政策", "master_M0046"),

    # 2006
    ("2006-03-05", "WEEKEND_HOLIDAY", "GOV_WORK_REPORT", "国务院总理温家宝", "2006年十届全国人大四次会议《政府工作报告》",
     0, 0, -1, 1, -1, 0, 0, "", 0, "继续实施稳健的财政政策和稳健的货币政策;推进股权分置改革", "gov_20060305"),
    ("2006-07-24", "AMC", "POLITBURO_JUL", "中共中央政治局", "2006年7月政治局会议研究当前经济形势与经济工作",
     -1, 0, -1, 0, -1, -1, 0, "", 0, "投资增长过快、货币信贷投放过多突出矛盾尚未根本解决;完善调控措施", "xinhua_20060724"),
    ("2006-11-30", "AMC", "POLITBURO_DEC", "中共中央政治局", "2006年11月政治局会议分析研究2007年经济工作",
     -1, 0, 0, 0, -1, -1, 0, "", 0, "实现国民经济又好又快发展;加强和改善宏观调控", "xinhua_20061130"),
    ("2006-12-07", "AMC", "CEWC", "中央经济工作会议", "2006年中央经济工作会议闭幕通稿",
     -1, 0, 0, 1, -1, -1, 0, "", 0, "加强流动性过剩管理;合理控制信贷投放;推进多层次资本市场建设", "master_M0054"),

    # 2007
    ("2007-01-20", "WEEKEND_HOLIDAY", "CFWC_FSDC_SC", "第三次全国金融工作会议", "第三次全国金融工作会议闭幕讲话通稿",
     0, 0, 0, 2, -1, 0, 0, "", 1, "大力发展资本市场;扩大直接融资比重;适时推出创业板", "master_M0056"),
    ("2007-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理温家宝", "2007年十届全国人大五次会议《政府工作报告》",
     -1, 0, -1, 1, -1, -1, 0, "", 0, "稳健的财政政策;适当从紧调控货币信贷总量;抑制固定资产投资过快", "gov_20070305"),
    ("2007-07-26", "AMC", "POLITBURO_JUL", "中共中央政治局", "2007年7月政治局会议分析研究当前经济形势",
     -2, 0, -1, 0, -1, -1, 0, "", 0, "遏制经济增长由偏快转为过热作为首要任务;加强流动性管理", "xinhua_20070726"),
    ("2007-11-27", "AMC", "POLITBURO_DEC", "中共中央政治局", "2007年11月政治局会议研究2008年经济工作",
     -2, 0, -1, 0, -1, -1, 0, "", 0, "防止经济增长由偏快转为过热、防止价格由结构性上涨演变为明显通胀(双防)", "xinhua_20071127"),
    ("2007-12-05", "AMC", "CEWC", "中央经济工作会议", "2007年中央经济工作会议定调双防与从紧货币政策",
     -2, 0, -1, 0, -1, -1, 0, "", 0, "实施稳健的财政政策和从紧的货币政策;严格控制货币信贷总量(十年首次从紧)", "master_M0066"),

    # 2008
    ("2008-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理温家宝", "2008年十一届全国人大一次会议《政府工作报告》",
     -2, 0, -1, 1, -1, -1, 0, "", 0, "从紧的货币政策;防过热防通胀;建立创业板市场;促进股市稳定健康发展", "master_M0070"),
    ("2008-07-25", "AMC", "POLITBURO_JUL", "中共中央政治局", "2008年7月政治局会议由双防转向一保一控",
     -1, 0, 0, 0, -1, 1, 0, "", 0, "保持经济平稳较快发展、控制物价过快上涨(一保一控)", "xinhua_20080725"),
    ("2008-11-09", "WEEKEND_HOLIDAY", "CFWC_FSDC_SC", "国务院常务会议", "国务院常务会议公布十项扩内需措施(四万亿)与适度宽松转向",
     2, 2, 1, 0, 0, 2, 0, "", 1, "实行积极的财政政策和适度宽松的货币政策;四万亿投资;取消商业银行信贷规模限制", "master_M0085"),
    ("2008-11-28", "AMC", "POLITBURO_DEC", "中共中央政治局", "2008年11月政治局会议研究2009年经济工作",
     2, 2, 1, 0, 0, 2, 0, "", 0, "实施积极的财政政策和适度宽松的货币政策;全力保持经济平稳较快发展", "xinhua_20081128"),
    ("2008-12-10", "AMC", "CEWC", "中央经济工作会议", "2008年中央经济工作会议闭幕通稿",
     2, 2, 1, 1, 0, 2, 0, "", 0, "实施积极的财政政策和适度宽松的货币政策;保持资本市场和房地产市场稳定健康发展", "master_M0086"),

    # 2009
    ("2009-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理温家宝", "2009年十一届全国人大二次会议《政府工作报告》",
     2, 2, 1, 1, 0, 2, 0, "", 0, "积极的财政政策和适度宽松的货币政策;维护股票市场稳定;保八扩内需", "master_M0090"),
    ("2009-07-23", "AMC", "POLITBURO_JUL", "中共中央政治局", "2009年7月政治局会议研究当前经济形势",
     2, 1, 0, 0, 0, 1, 0, "", 0, "宏观政策取向不能改变，调控工作不能放松;坚定不移实施一揽子计划", "xinhua_20090723"),
    ("2009-11-27", "AMC", "POLITBURO_DEC", "中共中央政治局", "2009年11月政治局会议研究2010年经济工作",
     2, 1, 0, 0, 0, 1, 0, "", 0, "继续实施积极财政政策和适度宽松货币政策;管理通胀预期与调结构", "xinhua_20091127"),
    ("2009-12-07", "AMC", "CEWC", "中央经济工作会议", "2009年中央经济工作会议闭幕通稿",
     2, 1, 0, 1, -1, 1, 1, "战略性新兴产业", 0, "积极扩大直接融资;战略性新兴产业;管理好通胀预期", "master_M0097"),

    # 2010
    ("2010-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理温家宝", "2010年十一届全国人大三次会议《政府工作报告》",
     1, 1, -1, 1, -1, 0, 0, "", 0, "继续实施适度宽松货币政策但管理通胀预期;坚决遏制部分城市房价过快上涨", "master_M0100"),
    ("2010-07-22", "AMC", "POLITBURO_JUL", "中共中央政治局", "2010年7月政治局会议研究当前经济形势与十二五规划",
     0, 1, -1, 0, -1, 0, 0, "", 0, "保持宏观政策连续性稳定性;加快转变经济发展方式", "xinhua_20100722"),
    ("2010-12-03", "AMC", "POLITBURO_DEC", "中共中央政治局", "2010年12月政治局会议货币政策由适度宽松转向稳健",
     0, 1, -1, 0, -1, -1, 0, "", 0, "实施积极的财政政策和稳健的货币政策(退出适度宽松);把稳定物价放突出位置", "xinhua_20101203"),
    ("2010-12-12", "WEEKEND_HOLIDAY", "CEWC", "中央经济工作会议", "2010年中央经济工作会议闭幕通稿",
     0, 1, -1, 1, -1, -1, 0, "", 0, "实施稳健的货币政策，把稳定物价总水平放更突出位置;健全多层次资本市场", "master_M0108"),

    # 2011
    ("2011-03-05", "WEEKEND_HOLIDAY", "GOV_WORK_REPORT", "国务院总理温家宝", "2011年十一届全国人大四次会议《政府工作报告》",
     0, 1, -2, 1, -1, -1, 0, "", 0, "实施积极财政和稳健货币政策;把稳定物价总水平放首要位置;千万套保障房+限购", "gov_20110305"),
    ("2011-07-22", "AMC", "POLITBURO_JUL", "中共中央政治局", "2011年7月政治局会议研究当前经济形势",
     0, 1, -2, 0, -1, -1, 0, "", 0, "实施积极财政和稳健货币政策;稳物价调结构保民生;坚持房地产调控不放松", "xinhua_20110722"),
    ("2011-12-09", "AMC", "POLITBURO_DEC", "中共中央政治局", "2011年12月政治局会议首提稳中求进",
     0, 1, -2, 0, -1, 0, 0, "", 0, "坚持稳中求进工作总基调;坚持房地产调控政策不动摇", "xinhua_20111209"),
    ("2011-12-14", "AMC", "CEWC", "中央经济工作会议", "2011年中央经济工作会议闭幕通稿",
     0, 1, -2, 1, -1, 0, 0, "", 0, "稳中求进总基调;发挥资本市场积极作用;防范化解潜在金融风险;推进房产税试点", "master_M0115"),

    # 2012
    ("2012-01-07", "WEEKEND_HOLIDAY", "CFWC_FSDC_SC", "第四次全国金融工作会议", "第四次全国金融工作会议罕见直接点名提振股市信心",
     0, 0, 0, 3, -1, 0, 0, "", 1, "完善发行退市分红制度;提振股市信心;防止虚拟经济过度自我循环", "master_M0118"),
    ("2012-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理温家宝", "2012年十一届全国人大五次会议《政府工作报告》",
     0, 1, -1, 1, -1, 0, 0, "", 0, "积极财政和稳健货币;促进资本市场稳定健康发展;继续严格执行房地产调控", "master_M0124"),
    ("2012-07-31", "AMC", "POLITBURO_JUL", "中共中央政治局", "2012年7月政治局会议把稳增长放在更加重要位置",
     1, 1, -2, 0, -1, 1, 0, "", 0, "把稳增长放在更加重要位置;增强调控前瞻性;坚定不移贯彻房地产调控防反弹", "master_M0135"),
    ("2012-12-04", "AMC", "POLITBURO_DEC", "中共中央政治局", "2012年12月政治局会议(同日沪指探底1949点建国底)",
     1, 1, -1, 0, -1, 1, 0, "", 0, "适时适度预调微调;积极稳妥推进城镇化;稳中求进", "master_M0143"),
    ("2012-12-16", "WEEKEND_HOLIDAY", "CEWC", "中央经济工作会议", "2012年中央经济工作会议闭幕通稿",
     1, 1, -1, 1, -1, 1, 0, "", 0, "健全多层次资本市场体系，提高直接融资比重;守住不发生系统性金融风险底线", "master_M0144"),

    # 2013
    ("2013-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理温家宝", "2013年十二届全国人大一次会议《政府工作报告》",
     0, 1, -1, 1, -1, 0, 0, "", 0, "继续实施积极财政政策(赤字1.2万亿)和稳健货币政策(M2目标13%);抑制投机购房", "gov_20130305"),
    ("2013-04-25", "AMC", "POLITBURO_APR", "中共中央政治局常委会", "2013年4月政治局常委会研究当前经济形势",
     0, 1, -1, 0, -1, 0, 0, "", 0, "统筹稳增长、控通胀、防风险;继续实施积极财政和稳健货币政策", "xinhua_20130425"),
    ("2013-07-30", "AMC", "POLITBURO_JUL", "中共中央政治局", "2013年7月政治局会议定调宏观要稳微观要活",
     0, 1, 0, 0, -1, 0, 0, "", 0, "宏观政策要稳、微观政策要活、社会政策要托底;盘活存量优化增量", "master_M0153"),
    ("2013-12-03", "AMC", "POLITBURO_DEC", "中共中央政治局", "2013年12月政治局会议研究2014年经济工作",
     0, 1, 0, 0, -1, 0, 0, "", 0, "把改革贯穿全过程;坚定推进产业结构调整;做好防范化解经济风险工作", "master_M0160"),
    ("2013-12-13", "AMC", "CEWC", "中央经济工作会议", "2013年中央经济工作会议闭幕通稿",
     0, 1, 0, 1, -1, 0, 0, "", 0, "着力防控债务风险;增强金融运行效率和服务实体经济能力", "master_M0161"),

    # 2014
    ("2014-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理李克强", "2014年十二届全国人大二次会议《政府工作报告》",
     0, 1, 0, 1, -1, 0, 0, "", 0, "推进股票发行注册制改革;促进互联网金融健康发展;守住风险底线", "master_M0163"),
    ("2014-04-25", "AMC", "POLITBURO_APR", "中共中央政治局", "2014年4月政治局会议研究当前经济工作",
     1, 1, 0, 0, -1, 1, 0, "", 0, "稳中求进;合理调节流动性水平;加大对小微企业三农等定向支持", "master_M0168"),
    ("2014-07-29", "AMC", "POLITBURO_JUL", "中共中央政治局", "2014年7月政治局会议强调定向调控与必须保持一定速度",
     1, 1, 0, 0, -1, 1, 0, "", 0, "更加注重定向调控;我国发展必须保持一定速度", "master_M0173"),
    ("2014-12-05", "AMC", "POLITBURO_DEC", "中共中央政治局", "2014年12月政治局会议首提主动适应经济发展新常态",
     1, 1, 0, 0, -1, 0, 0, "", 0, "主动适应经济发展新常态;增强战略性新兴产业支撑;大众创业大众创新", "master_M0180"),
    ("2014-12-11", "AMC", "CEWC", "中央经济工作会议", "2014年中央经济工作会议闭幕通稿",
     1, 1, 1, 1, -1, 0, 0, "", 0, "货币政策更加注重松紧适度;推进资本市场改革;新型城镇化稳住住房消费", "master_M0181"),

    # 2015
    ("2015-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理李克强", "2015年十二届全国人大三次会议《政府工作报告》",
     1, 2, 1, 1, 0, 1, 1, "互联网+_一带一路", 0, "制定互联网+行动计划;一带一路;实施股票发行注册制改革;启动深港通", "master_M0186"),
    ("2015-04-30", "AMC", "POLITBURO_APR", "中共中央政治局", "2015年4月政治局会议首重发挥资本市场作用",
     1, 2, 0, 2, 0, 1, 0, "", 0, "注重发挥资本市场的作用，大力发展直接融资;高度重视应对经济下行压力", "master_M0196"),
    ("2015-07-30", "AMC", "POLITBURO_JUL", "中共中央政治局", "2015年7月政治局会议(股灾救市期间)",
     1, 2, 0, 0, -1, 1, 0, "", 0, "加大定向调控力度;树立危机应对和风险管控意识;高度重视防范化解系统性风险", "master_M0212"),
    ("2015-12-14", "AMC", "POLITBURO_DEC", "中共中央政治局", "2015年12月政治局会议首提化解房地产库存与兼并重组",
     1, 2, 1, 0, -1, 0, 1, "供给侧去产能去库存", 0, "通过兼并重组破产清算实现市场出清;化解房地产库存", "master_M0223"),
    ("2015-12-21", "AMC", "CEWC", "中央经济工作会议", "2015年中央经济工作会议确立供给侧结构性改革五大任务",
     1, 2, 1, 1, -1, 0, 0, "", 0, "阶段性提高财政赤字率;三去一降一补;尽快形成融资功能完备股票市场", "master_M0224"),

    # 2016
    ("2016-03-05", "WEEKEND_HOLIDAY", "GOV_WORK_REPORT", "国务院总理李克强", "2016年十二届全国人大四次会议《政府工作报告》",
     1, 2, 1, 1, -1, 1, 0, "", 0, "赤字率提高到3%;推进股票债券市场改革法治化;适时启动深港通", "master_M0231"),
    ("2016-04-29", "AMC", "POLITBURO_APR", "中共中央政治局", "2016年4月政治局会议罕见专段提保持股市健康发展",
     0, 2, 0, 2, -1, 0, 0, "", 0, "保持股市健康发展，充分发挥市场机制调节作用，保护投资者权益", "master_M0235"),
    ("2016-07-26", "AMC", "POLITBURO_JUL", "中共中央政治局", "2016年7月政治局会议历史性首次提出抑制资产泡沫",
     0, 1, -1, 0, -2, 0, 0, "", 0, "降成本重点是抑制资产泡沫;有效防范化解金融风险隐患", "master_M0241"),
    ("2016-10-28", "AMC", "POLITBURO_SPECIAL", "中共中央政治局", "2016年10月非常规政治局会议再提抑制资产泡沫",
     0, 1, -1, 0, -2, 0, 0, "", 1, "保持流动性合理充裕同时注重抑制资产泡沫和防范经济金融风险", "master_M0246"),
    ("2016-12-09", "AMC", "POLITBURO_DEC", "中共中央政治局", "2016年12月政治局会议提出建立房地产长效机制",
     0, 2, -2, 0, -2, 0, 0, "", 0, "加快研究建立房地产平稳健康发展长效机制;一些领域金融风险显现", "xinhua_20161209"),
    ("2016-12-16", "AMC", "CEWC", "中央经济工作会议", "2016年中央经济工作会议历史性首提房住不炒与稳健中性",
     0, 2, -2, 1, -2, 0, 1, "房住不炒", 0, "货币政策稳健中性;把防控金融风险放更加重要位置;房子是用来住的不是用来炒的", "master_M0251"),

    # 2017
    ("2017-03-05", "WEEKEND_HOLIDAY", "GOV_WORK_REPORT", "国务院总理李克强", "2017年十二届全国人大五次会议《政府工作报告》",
     0, 2, -2, 1, -2, 0, 0, "", 0, "财政更加积极有效(赤字率3%);货币稳健中性(M2 12%);防控金融风险与资产泡沫", "gov_20170305"),
    ("2017-04-25", "AMC", "POLITBURO_APR", "中共中央政治局", "2017年4月政治局会议暨维护国家金融安全集体学习",
     -1, 1, -2, 1, -2, 0, 0, "", 0, "金融安全是国家安全重要组成部分;加强金融监管协调;扩大直接融资", "master_M0262"),
    ("2017-07-15", "WEEKEND_HOLIDAY", "CFWC_FSDC_SC", "第五次全国金融工作会议", "第五次全国金融工作会议设立金稳会与把直接融资放重要位置",
     -1, 0, -1, 2, -2, 0, 0, "", 1, "把发展直接融资放在重要位置;设立国务院金融稳定发展委员会;强化监管", "master_M0266"),
    ("2017-07-24", "AMC", "POLITBURO_JUL", "中共中央政治局", "2017年7月政治局会议严控地方隐性债务与金融乱象",
     -1, 1, -2, 0, -2, 0, 0, "", 0, "坚决遏制隐性债务增量;深入扎实整治金融乱象", "master_M0268"),
    ("2017-12-08", "AMC", "POLITBURO_DEC", "中共中央政治局", "2017年12月政治局会议首提推动高质量发展",
     -1, 1, -2, 0, -2, 0, 1, "高质量发展", 0, "推动高质量发展;防范化解重大风险使宏观杠杆率得到有效控制", "master_M0277"),
    ("2017-12-20", "AMC", "CEWC", "中央经济工作会议", "2017年中央经济工作会议管住货币总闸门",
     -1, 1, -2, 1, -2, 0, 0, "", 0, "稳健货币政策保持中性、管住货币供给总闸门;打好防范化解重大风险攻坚战", "master_M0278"),

    # 2018
    ("2018-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理李克强", "2018年十三届全国人大一次会议《政府工作报告》",
     -1, 1, -2, 1, -2, 0, 0, "", 0, "管住货币总闸门;支持优质创新型企业上市;防范股债汇异常波动", "master_M0285"),
    ("2018-04-23", "AMC", "POLITBURO_APR", "中共中央政治局", "2018年4月政治局会议提出扩大内需与消除股债汇隐患",
     0, 1, -2, 1, -1, 0, 0, "", 0, "推动信贷、股市、债市、汇市、楼市健康发展;把调结构与持续扩大内需结合", "master_M0288"),
    ("2018-07-31", "AMC", "POLITBURO_JUL", "中共中央政治局", "2018年7月政治局会议首提六稳与坚决遏制房价上涨",
     1, 2, -2, 0, -1, 1, 1, "六稳", 0, "稳中有变;六稳(稳就业稳金融稳外贸稳外资稳投资稳预期);坚决遏制房价上涨", "master_M0295"),
    ("2018-10-31", "AMC", "POLITBURO_SPECIAL", "中共中央政治局", "2018年10月非常规政治局会议罕见专段激发资本市场活力",
     1, 2, 0, 2, -1, 1, 0, "", 1, "围绕资本市场改革激发市场活力;支持民营企业;研究民营企业困难", "master_M0307"),
    ("2018-12-13", "AMC", "POLITBURO_DEC", "中共中央政治局", "2018年12月政治局会议激发微观主体活力",
     1, 2, -1, 0, -1, 1, 0, "", 0, "着力激发微观主体活力;创新和完善宏观调控;稳增长促改革防风险", "master_M0311"),
    ("2018-12-21", "AMC", "CEWC", "中央经济工作会议", "2018年中央经济工作会议定调资本市场牵一发而动全身",
     1, 2, -1, 2, -1, 1, 1, "科创板_资本市场牵一发而动全身", 0, "松紧适度保持流动性合理充裕;资本市场牵一发而动全身;推动科创板并试点注册制落地", "master_M0313"),

    # 2019
    ("2019-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理李克强", "2019年十三届全国人大二次会议《政府工作报告》",
     1, 2, -1, 1, -1, 1, 0, "", 0, "松紧适度把好总闸门(不搞大水漫灌);大规模减税降费2万亿;设立科创板", "master_M0319"),
    ("2019-04-19", "AMC", "POLITBURO_APR", "中共中央政治局", "2019年4月政治局会议重提结构性去杠杆与总闸门",
     0, 2, -2, 1, -2, 0, 0, "", 0, "一季度开局好;重提把好货币供给总闸门与结构性去杠杆;房住不炒;科创板注册制", "master_M0320"),
    ("2019-07-30", "AMC", "POLITBURO_JUL", "中共中央政治局", "2019年7月政治局会议首提不将房地产作为短期刺激经济手段",
     1, 2, -2, 1, -1, 1, 0, "", 0, "不将房地产作为短期刺激经济的手段;科创板坚守定位;货币松紧适度", "master_M0330"),
    ("2019-12-06", "AMC", "POLITBURO_DEC", "中共中央政治局", "2019年12月政治局会议强调运用逆周期调节工具",
     1, 2, -2, 0, -1, 1, 0, "", 0, "运用好逆周期调节工具;确保不发生系统性金融风险", "master_M0340"),
    ("2019-12-12", "AMC", "CEWC", "中央经济工作会议", "2019年中央经济工作会议部署创业板新三板改革与三稳",
     1, 2, -2, 1, -1, 1, 0, "", 0, "灵活适度保持流动性合理充裕;房住不炒稳地价稳房价稳预期;推进创业板新三板改革", "master_M0341"),

    # 2020
    ("2020-03-27", "AMC", "POLITBURO_SPECIAL", "中共中央政治局", "2020年3月非常规政治局会议首提提高赤字率与发行特别国债",
     1, 2, -1, 0, 0, 2, 0, "", 1, "首次明确适当提高财政赤字率、发行特别国债、增加地方政府专项债券规模", "xinhua_20200327"),
    ("2020-04-17", "AMC", "POLITBURO_APR", "中共中央政治局", "2020年4月政治局会议首次提出六保与降准降息",
     1, 2, -1, 0, 0, 2, 1, "六保", 0, "稳健货币更加灵活适度、降准降息再贷款引导利率下行;保居民就业等六保", "master_M0351"),
    ("2020-05-22", "BMO", "GOV_WORK_REPORT", "国务院总理李克强", "2020年十三届全国人大三次会议《政府工作报告》(疫期5月)",
     1, 2, -2, 1, 0, 2, 0, "", 0, "赤字率3.6%以上+1万亿抗疫特别国债;货币更加灵活适度引导M2明显高于去年", "gov_20200522"),
    ("2020-07-30", "AMC", "POLITBURO_JUL", "中共中央政治局", "2020年7月政治局会议确立内外双循环新发展格局",
     1, 2, -2, 1, -1, 1, 1, "国内国际双循环", 0, "加快形成以国内大循环为主体、国内国际双循环新格局;推进资本市场基础制度建设", "master_M0357"),
    ("2020-12-11", "AMC", "POLITBURO_DEC", "中共中央政治局", "2020年12月政治局会议首提强化反垄断和防止资本无序扩张",
     1, 1, -2, 0, -2, 0, 1, "反垄断_防资本无序扩张", 0, "强化国家战略科技力量与产业链自主可控;强化反垄断和防止资本无序扩张", "master_M0372"),
    ("2020-12-18", "AMC", "CEWC", "中央经济工作会议", "2020年中央经济工作会议提出不急转弯与双碳反垄断",
     1, 1, -2, 1, -2, 0, 1, "碳达峰碳中和", 0, "不急转弯;碳达峰碳中和大力发展新能源;强化反垄断与防资本无序扩张", "master_M0373"),

    # 2021
    ("2021-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理李克强", "2021年十三届全国人大四次会议《政府工作报告》",
     1, 1, -2, 1, -1, 0, 0, "", 0, "赤字率3.2%不急转弯;稳步推进注册制与常态化退市;加强反垄断监管", "master_M0377"),
    ("2021-04-30", "AMC", "POLITBURO_APR", "中共中央政治局", "2021年4月政治局会议定调稳增长压力较小窗口期",
     0, 1, -2, 0, -2, -1, 0, "", 0, "用好稳增长压力较小的窗口期;建立地方党政领导负责财政金融风险机制;平台监管", "master_M0385"),
    ("2021-07-30", "AMC", "POLITBURO_JUL", "中共中央政治局", "2021年7月政治局会议(双减与平台整治风暴)",
     1, 1, -2, 0, -2, 0, 0, "", 0, "跨周期调节;强化反垄断防资本无序扩张;完善企业境外上市监管制度", "master_M0390"),
    ("2021-12-06", "AMC", "POLITBURO_DEC", "中共中央政治局", "2021年12月政治局会议转向稳字当头与良性循环",
     1, 1, 1, 0, -1, 1, 0, "", 0, "明年要稳字当头稳中求进;促进房地产业健康发展和良性循环", "master_M0396"),
    ("2021-12-10", "AMC", "CEWC", "中央经济工作会议", "2021年中央经济工作会议首提三重压力与全面注册制",
     1, 1, 1, 1, -2, 1, 0, "", 0, "需求收缩供给冲击预期转弱三重压力;全面实行股票发行注册制;为资本设置红绿灯", "master_M0397"),

    # 2022
    ("2022-03-05", "WEEKEND_HOLIDAY", "GOV_WORK_REPORT", "国务院总理李克强", "2022年十三届全国人大五次会议《政府工作报告》",
     1, 2, 0, 1, -1, 1, 0, "", 0, "GDP目标5.5%左右;留抵退税约1.5万亿;全面实行股票发行注册制", "master_M0401"),
    ("2022-03-16", "INTRADAY", "CFWC_FSDC_SC", "国务院金融稳定发展委员会", "2022年3月16日国务院金融委专题会议维稳救市",
     1, 1, 1, 3, 0, 2, 0, "", 1, "慎重出台收缩性政策;货币主动应对;平台整改稳妥推进;中概股积极进展;欢迎长钱", "master_M0402"),
    ("2022-04-29", "AMC", "POLITBURO_APR", "中共中央政治局", "2022年4月政治局会议支持刚改住房需求与平台专项整改",
     1, 2, 1, 2, -1, 2, 0, "", 0, "稳步推进注册制引入长钱;完成平台经济专项整改;支持各地优化地产政策", "master_M0414"),
    ("2022-07-28", "AMC", "POLITBURO_JUL", "中共中央政治局", "2022年7月政治局会议首提保交楼与平台绿灯案例",
     1, 1, 1, 0, -1, 1, 0, "", 0, "保交楼稳民生;集中推出一批平台经济绿灯投资案例;算政治账", "master_M0419"),
    ("2022-12-06", "AMC", "POLITBURO_DEC", "中共中央政治局", "2022年12月政治局会议提出大力提振市场信心",
     1, 2, 1, 0, -1, 2, 0, "", 0, "大力提振市场信心;突出做好稳增长稳就业稳物价;敢干敢闯敢首创", "master_M0430"),
    ("2022-12-16", "AMC", "CEWC", "中央经济工作会议", "2022年中央经济工作会议力挺平台企业(罕见未点名股市)",
     1, 2, 1, 0, -1, 2, 1, "数字经济_平台大显身手", 0, "大力发展数字经济，支持平台企业大显身手;有效防范化解优质头部房企风险", "master_M0432"),

    # 2023
    ("2023-03-05", "WEEKEND_HOLIDAY", "GOV_WORK_REPORT", "国务院总理李克强", "2023年十四届全国人大一次会议《政府工作报告》",
     1, 2, 1, 0, -1, 1, 0, "", 0, "积极财政加力提效(赤字率3%);稳健货币精准有力;防范优质头部房企风险", "gov_20230305"),
    ("2023-04-28", "AMC", "POLITBURO_APR", "中共中央政治局", "2023年4月政治局会议首提重视通用人工智能发展",
     1, 1, 0, 0, -1, 1, 1, "通用人工智能", 0, "内生动力还不强需求仍然不足;要重视通用人工智能发展;巩固新能源汽车优势", "master_M0441"),
    ("2023-07-24", "AMC", "POLITBURO_JUL", "中共中央政治局", "2023年7月政治局会议首提活跃资本市场与地产供求重大变化",
     1, 1, 1, 2, -1, 1, 0, "", 0, "要活跃资本市场，提振投资者信心;适应房地产供求关系重大变化适时优化政策(未提房住不炒)", "master_M0447"),
    ("2023-10-31", "AMC", "CFWC_FSDC_SC", "中央金融工作会议", "2023年中央金融工作会议确立建设金融强国",
     1, 1, 1, 2, -1, 1, 0, "", 1, "加快建设金融强国;更好发挥资本市场枢纽功能;培育一流投行;活跃资本市场", "master_M0466"),
    ("2023-12-08", "AMC", "POLITBURO_DEC", "中共中央政治局", "2023年12月政治局会议首提以进促稳先立后破",
     1, 2, 1, 0, -1, 1, 0, "", 0, "以进促稳、先立后破;强化宏观政策逆周期和跨周期调节;增强政策取向一致性", "master_M0474"),
    ("2023-12-12", "AMC", "CEWC", "中央经济工作会议", "2023年中央经济工作会议首提新质生产力与低空经济商业航天",
     1, 2, 1, 1, -1, 1, 1, "新质生产力_低空商业航天", 0, "发展新质生产力;生物制造商业航天低空经济;鼓励创投股权投资;防范地产地方债风险", "master_M0475"),

    # 2024
    ("2024-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理李强", "2024年十四届全国人大二次会议《政府工作报告》",
     1, 2, 1, 2, -1, 1, 1, "人工智能+", 0, "增强资本市场内在稳定性;开展人工智能+行动;超长期特别国债", "master_M0496"),
    ("2024-04-30", "AMC", "POLITBURO_APR", "中共中央政治局", "2024年4月政治局会议首提壮大耐心资本",
     1, 2, 1, 1, -1, 1, 1, "耐心资本", 0, "积极发展风险投资，壮大耐心资本;消化存量房产和优化增量住房;超前布局未来产业", "master_M0509"),
    ("2024-07-30", "AMC", "POLITBURO_JUL", "中共中央政治局", "2024年7月政治局会议首提防止内卷式恶性竞争",
     1, 2, 1, 2, -1, 1, 1, "反内卷", 0, "提振投资者信心，提升资本市场内在稳定性;防止内卷式恶性竞争;促服务消费", "master_M0533"),
    ("2024-09-26", "AMC", "POLITBURO_SPECIAL", "中共中央政治局", "2024年9月26日罕见加开政治局会议定调止跌回稳与努力提振资本市场",
     2, 2, 2, 3, 0, 2, 0, "", 1, "降准有力降息;促进房地产市场止跌回稳;努力提振资本市场，打通中长期资金入市堵点", "master_M0541"),
    ("2024-12-09", "AMC", "POLITBURO_DEC", "中共中央政治局", "2024年12月政治局会议时隔14年重提适度宽松货币与超常规逆周期",
     2, 2, 2, 3, 0, 2, 0, "", 0, "更加积极的财政政策和适度宽松的货币政策;加强超常规逆周期调节;稳住楼市股市", "master_M0560"),
    ("2024-12-12", "AMC", "CEWC", "中央经济工作会议", "2024年中央经济工作会议全面落实稳住楼市股市与超常规调控",
     2, 2, 2, 3, -1, 2, 0, "", 0, "稳住楼市股市;更加积极财政提高赤字率+适度宽松货币降准降息;打通中长期资金卡点", "master_M0561"),

    # 2025
    ("2025-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理李强", "2025年十四届全国人大三次会议《政府工作报告》",
     2, 2, 2, 3, -1, 2, 1, "具身智能_6G", 0, "赤字率4%;稳住楼市股市;加强战略性力量储备和稳市机制;具身智能/6G/商业航天", "master_M0574"),
    ("2025-04-25", "AMC", "POLITBURO_APR", "中共中央政治局", "2025年4月政治局会议首提持续稳定和活跃资本市场",
     2, 2, 1, 3, 0, 2, 0, "", 0, "持续稳定和活跃资本市场;适时降准降息创设新结构性工具;稳就业稳企业稳市场稳预期", "master_M0582"),
    ("2025-07-30", "AMC", "POLITBURO_JUL", "中共中央政治局", "2025年7月政治局会议巩固回稳向好势头与治理无序竞争",
     2, 2, 1, 2, -1, 1, 0, "", 0, "巩固资本市场回稳向好势头;增强吸引力包容性;依法依规治理企业无序竞争", "master_M0591"),
    ("2025-12-08", "INTRADAY", "POLITBURO_DEC", "中共中央政治局", "2025年12月政治局会议部署2026年十五五开局经济工作",
     2, 2, 1, 0, -1, 1, 0, "", 0, "实施更加积极有为宏观政策;做优增量盘活存量;着力四稳(通稿未单提股市)", "master_M0608"),
    ("2025-12-11", "AMC", "CEWC", "中央经济工作会议", "2025年中央经济工作会议部署十五五开局与深化投融资改革",
     2, 2, 1, 2, -1, 1, 0, "", 0, "继续实施更加积极财政和适度宽松货币;持续深化资本市场投融资综合改革", "master_M0609"),

    # 2026 (through 2026-11-25)
    ("2026-03-05", "BMO", "GOV_WORK_REPORT", "国务院总理李强", "2026年十四届全国人大四次会议《政府工作报告》",
     2, 2, 1, 2, -1, 1, 1, "十五五未来能源_脑机接口", 0, "深化投融资综合改革健全长钱机制;未来能源/量子科技/生物制造/具身智能/脑机接口/6G", "master_M0617"),
    ("2026-04-28", "AMC", "POLITBURO_APR", "中共中央政治局", "2026年4月政治局会议稳定和增强资本市场信心",
     2, 2, 1, 2, -1, 1, 0, "", 0, "稳定和增强资本市场信心;深入整治内卷式竞争;全面实施人工智能+行动发展智能经济", "master_M0622"),
    ("2026-07-30", "AMC", "POLITBURO_JUL", "中共中央政治局", "2026年7月政治局会议提升资本市场韧性和信心",
     2, 2, 1, 2, -1, 1, 0, "", 0, "深化资本市场投融资综合改革，提升资本市场韧性和信心;加大逆周期调节出台增量政策", "master_M0631"),
]


def build_pillar2():
    panel, dates, date_to_idx = cm.load_market_panel()
    master = pd.read_parquet(cm.MASTER_PQ)
    master_by_date = {}
    for _, r in master.iterrows():
        dt = str(r["event_date"])[:10]
        master_by_date.setdefault(dt, []).append(r)

    rows = []
    for i, item in enumerate(MEETINGS):
        (dt, slot, mtype, body, title,
         t_mon, t_fis, t_prop, t_eq, t_del, t_gr,
         first_theme, theme_lbl, off_sched, kw, src_ref) = item

        t_entry, t_prior, trad_dt = cm.align_event_pit(dt, slot, dates, date_to_idx)
        prior_st = cm.extract_prior_state(panel, t_prior)

        # Match master_id if present in master_events_v2
        matched_mid = ""
        if dt in master_by_date:
            for mr in master_by_date[dt]:
                ttl = str(mr["title_or_occasion"])
                if (mtype == "GOV_WORK_REPORT" and "政府工作报告" in ttl) or \
                   ("POLITBURO" in mtype and mr["venue_type"] == "POLITBURO") or \
                   (mtype == "CEWC" and "中央经济工作会议" in ttl) or \
                   (mtype == "CFWC_FSDC_SC" and mr["venue_type"] in ("CENTRAL_CONF",)):
                    matched_mid = str(mr["master_id"])
                    break

        stance = int(t_mon + t_fis + t_prop + t_eq + t_del + t_gr)
        mon_fis = int(t_mon + t_fis)

        rec = {
            "meeting_id": f"P2_{i+1:03d}",
            "master_id": matched_mid,
            "event_date": dt,
            "release_slot": slot,
            "tradable_date": trad_dt,
            "t_entry_idx": t_entry,
            "t_prior_idx": t_prior,
            "year": int(dt[:4]),
            "month": int(dt[5:7]),
            "meeting_type": mtype,
            "authority_body": body,
            "title": title,
            "verification_source": src_ref,
            "off_schedule_flag": int(off_sched),
            # 6 core PIT tone level dimensions
            "tone_monetary": int(t_mon),
            "tone_fiscal": int(t_fis),
            "tone_property": int(t_prop),
            "tone_equity": int(t_eq),
            "tone_deleveraging": int(t_del),
            "tone_growth_urgency": int(t_gr),
            # Composite level features
            "macro_stance_score": stance,
            "monetary_fiscal_sum": mon_fis,
            "equity_unmentioned_flag": int(t_eq == 0),
            "equity_strong_upgrade_flag": int(t_eq >= 2),
            "property_easing_flag": int(t_prop >= 1),
            "policy_constraint_flag": int(t_del <= -2),
            # New theme flags
            "first_mention_new_theme": int(first_theme),
            "new_theme_label": theme_lbl,
            "keywords_verbatim": kw,
        }
        rec.update(prior_st)
        rec["entry_gap_bench"] = float(panel.at[t_entry, "bench_gap_ret"]) if (t_entry >= 0 and pd.notna(panel.at[t_entry, "bench_gap_ret"])) else np.nan

        # Compute PIT forward returns across 5/20/60/120 trading days
        for h in [5, 20, 60, 120]:
            b_ret = cm.calc_fwd_return(panel, t_entry, h, "bench")
            c300_ret = cm.calc_fwd_return(panel, t_entry, h, "csi300")
            ew_ret = cm.calc_fwd_return(panel, t_entry, h, "ew")
            m30_ret = cm.calc_fwd_return(panel, t_entry, h, "micro30")
            div_ret = cm.calc_fwd_return(panel, t_entry, h, "csi_div")
            tech_ret = cm.calc_fwd_return(panel, t_entry, h, "tech_board")
            cx_ret = cm.calc_fwd_return(panel, t_entry, h, "chinext")

            rec[f"ret_bench_{h}d"] = b_ret
            rec[f"ret_csi300_{h}d"] = c300_ret
            rec[f"ret_ew_{h}d"] = ew_ret
            rec[f"ret_micro30_{h}d"] = m30_ret
            rec[f"ret_csi_div_{h}d"] = div_ret
            rec[f"ret_tech_{h}d"] = tech_ret
            rec[f"ret_chinext_{h}d"] = cx_ret

            # Excess returns vs contemporaneous bench (CSI300 spliced)
            rec[f"ex_ew_{h}d"] = ew_ret - b_ret if (pd.notna(ew_ret) and pd.notna(b_ret)) else np.nan
            rec[f"ex_micro30_{h}d"] = m30_ret - b_ret if (pd.notna(m30_ret) and pd.notna(b_ret)) else np.nan
            rec[f"ex_csi_div_{h}d"] = div_ret - b_ret if (pd.notna(div_ret) and pd.notna(b_ret)) else np.nan
            rec[f"ex_tech_{h}d"] = tech_ret - b_ret if (pd.notna(tech_ret) and pd.notna(b_ret)) else np.nan
            rec[f"ex_chinext_{h}d"] = cx_ret - b_ret if (pd.notna(cx_ret) and pd.notna(b_ret)) else np.nan

        rows.append(rec)

    df = pd.DataFrame(rows).sort_values("event_date").reset_index(drop=True)

    # Sequential diffs (strictly relative to immediately preceding top meeting t-1)
    axes = ["monetary", "fiscal", "property", "equity", "deleveraging", "growth_urgency"]
    for ax in axes:
        col = f"tone_{ax}"
        df[f"delta_{ax}"] = df[col].diff().fillna(0).astype(int)
        # Same-meeting-type prior cycle diff (e.g. CEWC vs prior CEWC)
        df[f"delta_yoy_{ax}"] = df.groupby("meeting_type")[col].diff().fillna(0).astype(int)

    df["delta_macro_stance"] = df["macro_stance_score"].diff().fillna(0).astype(int)
    df["delta_yoy_stance"] = df.groupby("meeting_type")["macro_stance_score"].diff().fillna(0).astype(int)
    df["delta_monetary_fiscal"] = df["monetary_fiscal_sum"].diff().fillna(0).astype(int)

    delta_cols = [f"delta_{ax}" for ax in axes]
    df["max_abs_delta"] = df[delta_cols].abs().max(axis=1).astype(int)
    df["upgrade_axis_cnt"] = (df[delta_cols] > 0).sum(axis=1).astype(int)
    df["downgrade_axis_cnt"] = (df[delta_cols] < 0).sum(axis=1).astype(int)

    df["is_upgrade_any"] = ((df["delta_macro_stance"] >= 1) | ((df["upgrade_axis_cnt"] >= 1) & (df["downgrade_axis_cnt"] == 0))).astype(int)
    df["is_downgrade_any"] = ((df["delta_macro_stance"] <= -1) | ((df["downgrade_axis_cnt"] >= 1) & (df["upgrade_axis_cnt"] == 0))).astype(int)
    df["is_equity_upgrade"] = (df["delta_equity"] >= 1).astype(int)
    df["is_monetary_upgrade"] = (df["delta_monetary"] >= 1).astype(int)
    df["is_fiscal_upgrade"] = (df["delta_fiscal"] >= 1).astype(int)
    df["is_property_upgrade"] = (df["delta_property"] >= 1).astype(int)

    # Surprise shift: off-schedule economic meeting OR single-axis jump >= 2 OR net stance jump >= 3
    df["surprise_shift"] = (
        (df["off_schedule_flag"] == 1) |
        (df["max_abs_delta"] >= 2) |
        (df["delta_macro_stance"].abs() >= 3)
    ).astype(int)
    df["surprise_direction"] = np.where(
        df["surprise_shift"] == 1,
        np.where(df["delta_macro_stance"] > 0, 1, np.where(df["delta_macro_stance"] < 0, -1, np.where(df["tone_equity"] >= 2, 1, 0))),
        0,
    ).astype(int)

    df.to_parquet(OUT_PQ, index=False)

    # Comparative empirical audit: Sequential Diff vs Static Absolute Tone
    tests = {
        "DIFF_macro_stance_up_ge2": df["delta_macro_stance"] >= 2,
        "DIFF_macro_stance_up_ge1": df["delta_macro_stance"] >= 1,
        "DIFF_equity_upgrade_ge1": df["delta_equity"] >= 1,
        "DIFF_monetary_upgrade_ge1": df["delta_monetary"] >= 1,
        "DIFF_property_upgrade_ge1": df["delta_property"] >= 1,
        "DIFF_surprise_pos_shift": (df["surprise_shift"] == 1) & (df["surprise_direction"] > 0),
        "DIFF_macro_stance_down_le_neg2": df["delta_macro_stance"] <= -2,
        "STATIC_tone_equity_ge2": df["tone_equity"] >= 2,
        "STATIC_tone_equity_eq3": df["tone_equity"] == 3,
        "STATIC_tone_monetary_ge1": df["tone_monetary"] >= 1,
        "STATIC_macro_stance_ge4": df["macro_stance_score"] >= 4,
        "STATIC_F009_equity_unmentioned": df["tone_equity"] == 0,
        "THEME_first_mention_new": df["first_mention_new_theme"] == 1,
    }

    audit_rows = []
    for name, mask in tests.items():
        sub = df[mask & (df["t_entry_idx"] >= 0)].copy()
        row = {"signal": name, "n": int(len(sub))}
        for h in [5, 20, 60, 120]:
            sb = cm.calc_sample_stats(sub[f"ret_bench_{h}d"])
            sew = cm.calc_sample_stats(sub[f"ex_ew_{h}d"])
            ste = cm.calc_sample_stats(sub[f"ex_tech_{h}d"])
            row[f"bench_{h}d_mean_pct"] = round(sb["mean"] * 100, 2) if pd.notna(sb["mean"]) else None
            row[f"bench_{h}d_win_pct"] = round(sb["win_rate"] * 100, 1) if pd.notna(sb["win_rate"]) else None
            row[f"ex_ew_{h}d_mean_pct"] = round(sew["mean"] * 100, 2) if pd.notna(sew["mean"]) else None
            row[f"ex_tech_{h}d_mean_pct"] = round(ste["mean"] * 100, 2) if pd.notna(ste["mean"]) else None
        audit_rows.append(row)

    pb_sub = df[df["meeting_type"].str.startswith("POLITBURO") & (df["year"] >= 2013) & (df["t_entry_idx"] >= 0)].copy()
    pb_tests = {
        "PB13_26_DIFF_macro_stance_up_ge1": pb_sub["delta_macro_stance"] >= 1,
        "PB13_26_DIFF_equity_upgrade_ge1": pb_sub["delta_equity"] >= 1,
        "PB13_26_STATIC_equity_ge2": pb_sub["tone_equity"] >= 2,
        "PB13_26_STATIC_F009_unmentioned": pb_sub["tone_equity"] == 0,
    }
    pb_rows = []
    for pname, pmask in pb_tests.items():
        psub = pb_sub[pmask]
        prow = {"signal": pname, "n": int(len(psub))}
        for h in [5, 20, 60, 120]:
            sb = cm.calc_sample_stats(psub[f"ret_bench_{h}d"])
            prow[f"bench_{h}d_mean_pct"] = round(sb["mean"] * 100, 2) if pd.notna(sb["mean"]) else None
            prow[f"bench_{h}d_win_pct"] = round(sb["win_rate"] * 100, 1) if pd.notna(sb["win_rate"]) else None
        pb_rows.append(prow)

    audit = {
        "n_meetings": int(len(df)),
        "date_range": [str(df["event_date"].min()), str(df["event_date"].max())],
        "n_columns": int(len(df.columns)),
        "meeting_type_counts": df["meeting_type"].value_counts().to_dict(),
        "n_matched_master": int((df["master_id"] != "").sum()),
        "diff_vs_static_comparison": audit_rows,
        "politburo_2013_2026_slice": pb_rows,
    }
    with open(OUT_AUDIT, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"[Pillar 2] Saved {OUT_PQ}: {len(df)} rows, {len(df.columns)} cols")
    print(f"[Pillar 2] Date range: {audit['date_range']}, matched master: {audit['n_matched_master']}/{len(df)}")
    for r in audit_rows:
        print(f"  {r['signal']:32s} n={r['n']:2d} | 5d:{r['bench_5d_mean_pct']}%({r['bench_5d_win_pct']}%) | 20d:{r['bench_20d_mean_pct']}%({r['bench_20d_win_pct']}%) | 60d:{r['bench_60d_mean_pct']}%({r['bench_60d_win_pct']}%) | 120d:{r['bench_120d_mean_pct']}%({r['bench_120d_win_pct']}%) | ex_tech20d:{r['ex_tech_20d_mean_pct']}%")


if __name__ == "__main__":
    build_pillar2()

#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""
RD027 Pillar 3: 2008-2026.11 Ministerial Sector Traffic Lights (Green/Red Industrial Policy Archive).
Covers 130+ verified ministerial-level hard policies altering physical supply, demand, subsidy, pricing,
licensing, M&A, or existential redlines across A-share sectors.
Strictly PIT (next tradable open -> close[t+h-1]) against CSI 300, IS (<=2020) vs OOS (2021~2026).
"""
import json
import os
import sys
import numpy as np
import pandas as pd

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)
import rd027_common as cm

OUT_PQ = os.path.join(cm.OUT_PILLAR_DIR, "pillar3_sector_traffic_lights.parquet")
OUT_AUDIT = os.path.join(cm.OUT_PILLAR_DIR, "pillar3_sector_traffic_lights_audit.json")

# Sector -> (primary_panel_col, fallback_panel_col_1, fallback_panel_col_2)
SECTOR_COL_MAP = {
    "NEW_ENERGY": ("new_energy", "tech_board", "csi500"),
    "SEMI_HARDTECH": ("semi_etf", "tmt_info", "tech_board"),
    "TMT_AI_MEDIA": ("tmt_info", "tech_board", "csi500"),
    "PHARMA": ("pharma", "csi500", "csi300"),
    "DEFENSE_AERO": ("defense", "csi500", "csi300"),
    "REAL_ESTATE": ("real_estate", "csi300", "bench"),
    "CONSUMPTION_BAIJIU": ("baijiu", "cons_opt", "csi300"),
    "CONS_OPT": ("cons_opt", "csi300", "bench"),
    "BANK": ("bank_idx", "sse50", "csi300"),
    "BROKERAGE": ("brokerage", "sse50", "csi300"),
    "CENTRAL_SOE_DIV": ("central_soe", "csi_div", "sse50"),
    "MICRO_SHELL": ("micro30", "micro30", "csi500"),
    "EDU_INTERNET": ("media_ai", "tmt_info", "tech_board"),
    "SUPPLY_CYCLICAL": ("csi500", "csi500", "csi300"),
}

# Tuple schema:
# (event_date, release_slot, ministry, doc_title, sector_code, signal_type, intensity, mechanism, source_ref)
EVENTS = [
    # --- NEW_ENERGY (新能源/光伏/风电/电动车/储能/电网) ---
    ("2009-01-23", "AMC", "财政部/科技部", "关于开展节能与新能源汽车示范推广试点工作的通知(十城千辆财建〔2009〕6号)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 3, "启动十城千辆公共领域新能源汽车财政定额补贴", "mof_most_20090123"),
    ("2009-03-20", "AMC", "国务院办公厅", "汽车产业调整和振兴规划", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "安排100亿元专项资金支持汽车技术进步与新能源车发展", "gov_20090320"),
    ("2010-05-31", "AMC", "财政部/科技部/工信部/发改委", "关于开展私人购买新能源汽车补贴试点的通知", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 3, "首次将新能源车财政补贴由公交扩展至私人消费(最高6万/辆)", "ndrc_20100531"),
    ("2012-06-28", "AMC", "国务院", "节能与新能源汽车产业发展规划(2012-2020年,国发〔2012〕22号)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "确立纯电驱动技术路线与2015年50万辆/2020年500万辆目标", "gov_20120628"),
    ("2013-07-04", "AMC", "国务院", "关于促进光伏产业健康发展的若干意见(国发〔2013〕24号,光伏国六条)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 3, "解决光伏欧美双反危机并网与度电补贴落地，拉动国内装机", "nea_20130704"),
    ("2014-08-06", "AMC", "财政部/税务总局/工信部", "关于免征新能源汽车车辆购置税的公告", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 3, "2014年9月至2017年底免征新能源车10%车辆购置税", "mof_20140806"),
    ("2014-11-19", "AMC", "国务院办公厅", "能源发展战略行动计划(2014-2020年,国办发〔2014〕31号)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "锚定2020年非化石能源占比15%与风电光伏200GW/100GW目标", "gov_20141119"),
    ("2015-03-15", "WEEKEND_HOLIDAY", "中共中央/国务院", "关于进一步深化电力体制改革的若干意见(中发〔2015〕9号)", "NEW_ENERGY", "GREEN_DEREG_MA", 2, "管住中间放开两头，推动新能源优先发电消纳与售电侧开放", "gov_20150315"),
    ("2015-04-30", "AMC", "财政部/科技部/工信部/发改委", "关于2016-2020年新能源汽车推广应用财政支持政策的通知", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "锁定2016-2020五年补贴框架并明确退坡节奏", "mof_20150430"),
    ("2015-10-09", "AMC", "国务院办公厅", "关于加快电动汽车充电基础设施建设的指导意见(国办发〔2015〕73号)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "部署车桩比例与充电桩建设补贴及配电网改造", "nea_20151009"),
    ("2017-09-27", "AMC", "工信部等五部委", "乘用车企业平均燃料消耗量与新能源汽车积分并行管理办法(双积分)", "NEW_ENERGY", "GREEN_SUPPLY_CUT", 3, "强制车企新能源积分比例(2019年10%/2020年12%)倒逼电动化", "miit_20170927"),
    ("2017-12-27", "AMC", "财政部/税务总局/工信部/科技部", "关于免征新能源汽车车辆购置税的公告(延续至2020年底)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "新能源车免征购置税延期三年至2020年12月31日", "mof_20171227"),
    ("2018-05-31", "AMC", "发改委/财政部/能源局", "关于2018年光伏发电有关事项的通知(发改能源〔2018〕823号,531新政)", "NEW_ENERGY", "RED_PRICE_CAP_TAX", 3, "急刹车暂停普通光伏指标并下调标杆电价，触发全行业产能出清暴跌", "nea_20180531"),
    ("2019-03-26", "AMC", "财政部/工信部/科技部/发改委", "关于进一步完善新能源汽车推广应用财政补贴政策的通知(财建〔2019〕138号)", "NEW_ENERGY", "RED_PRICE_CAP_TAX", 3, "补贴平均退坡超50%且取消地补，新能源车短期销量承压", "mof_20190326"),
    ("2020-11-02", "AMC", "国务院办公厅", "新能源汽车产业发展规划(2021-2035年)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "明确2025年新能源新车销量占比达20%目标与换电鼓励", "gov_20201102"),
    ("2021-07-23", "AMC", "发改委/能源局", "关于加快推动新型储能发展的指导意见(发改能源规〔2021〕1051号)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "设定2025年新型储能装机30GW以上硬指标并确立独立市场地位", "ndrc_20210723"),
    ("2021-10-15", "AMC", "发改委/能源局", "沙漠戈壁荒漠大型风电光伏基地第一批项目集中开工", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 3, "启动约100GW风光大基地开工拉动上游硅料组件风机需求", "ndrc_20211015"),
    ("2021-10-24", "WEEKEND_HOLIDAY", "国务院", "2030年前碳达峰行动方案(国发〔2021〕23号)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "明确2030年风光总装机12亿千瓦以上路线图", "gov_20211024"),
    ("2022-05-30", "AMC", "国务院办公厅/发改委/能源局", "关于促进新时代新能源高质量发展实施方案(国办函〔2022〕39号)", "NEW_ENERGY", "GREEN_DEREG_MA", 2, "审批简化、绿电交易及新能源消纳制度松绑", "nea_20220530"),
    ("2023-06-21", "AMC", "财政部/税务总局/工信部", "关于延续和优化新能源汽车车辆购置税减免政策的公告", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "锁定2024-2025免税(上限3万)与2026-2027减半(上限1.5万)", "mof_20230621"),
    ("2024-08-16", "AMC", "商务部等7部门", "关于进一步做好汽车以旧换新工作的通知(新能源补贴翻倍至2万元)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 3, "报废更新购买新能源乘用车补贴由1万元翻倍至2万元", "mofcom_20240816"),
    ("2024-11-15", "AMC", "工信部", "光伏制造行业规范条件(2024年本)(工信部公告2024年第33号)", "NEW_ENERGY", "GREEN_SUPPLY_CUT", 2, "提高新建光伏项目资本金比例至30%与能耗电耗门槛遏制恶性扩产", "miit_20241115"),
    ("2025-08-19", "AMC", "工信部/发改委/能源局等六部门", "六部门联合召开光伏产业座谈会部署反内卷与治理无序价格竞争", "NEW_ENERGY", "GREEN_SUPPLY_CUT", 2, "部委出手约束低于成本价倾销与过剩产能退出", "miit_20250819"),
    ("2025-12-30", "AMC", "商务部等8部门", "2026年汽车以旧换新补贴实施细则(商办消费函〔2025〕467号)", "NEW_ENERGY", "GREEN_SUBSIDY_PLAN", 2, "延续2026年按车价12%最高2万元报废购新补贴", "mofcom_20251230"),

    # --- SEMI_HARDTECH (半导体/集成电路/硬科技制造) ---
    ("2010-10-18", "AMC", "国务院", "关于加快培育和发展战略性新兴产业的决定(国发〔2010〕32号)", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 3, "确立七大战略性新兴产业，设立专项资金与税收倾斜", "gov_20101018"),
    ("2011-01-28", "AMC", "国务院", "进一步鼓励软件产业和集成电路产业发展的若干政策(国发〔2011〕4号)", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 2, "延续并升级集成电路企业两免三减半与增值税退税", "gov_20110128"),
    ("2014-06-24", "AMC", "工信部/国务院", "国家集成电路产业发展推进纲要", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 3, "顶层确立设立国家产业投资基金与制造设计封装全链赶超目标", "miit_20140624"),
    ("2014-09-24", "AMC", "财政部/工信部等发起", "国家集成电路产业投资基金(大基金一期)正式注册成立(987亿首期)", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 3, "国家级千亿股权资本直接注资晶圆代工与设备材料龙头", "gov_20140924"),
    ("2015-05-08", "AMC", "国务院", "中国制造2025(国发〔2015〕28号)", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 3, "将新一代信息技术、高档数控机床和机器人列为制造强国核心", "ndrc_20150508"),
    ("2016-05-19", "AMC", "中共中央/国务院", "国家创新驱动发展战略纲要", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 2, "部署核心芯片、高端装备、人工智能等重大科技项目", "gov_20160519"),
    ("2018-03-30", "AMC", "国务院办公厅/证监会", "关于开展创新企业境内发行股票或存托凭证试点若干意见(国办发〔2018〕21号)", "SEMI_HARDTECH", "GREEN_DEREG_MA", 2, "打通红筹独角兽与未盈利硬科技A股上市通道", "gov_20180330"),
    ("2018-11-05", "INTRADAY", "最高层进博会官宣/证监会", "进博会官宣在上交所设立科创板并试点注册制", "SEMI_HARDTECH", "GREEN_DEREG_MA", 3, "为硬科技半导体生物医药开通独立IPO注册制融资板", "master_M0308"),
    ("2019-05-22", "AMC", "财政部/税务总局", "关于集成电路设计和软件产业企业所得税政策的公告(财税〔2019〕68号)", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 2, "集成电路设计企业延续前两年免征、第三至五年减半征收所得税", "mof_20190522"),
    ("2019-06-13", "INTRADAY", "国务院副总理/证监会", "陆家嘴论坛科创板正式开板仪式", "SEMI_HARDTECH", "GREEN_DEREG_MA", 2, "科创板开板落地硬科技直接融资加速", "master_M0327"),
    ("2019-10-22", "AMC", "财政部/国开金融等", "国家集成电路产业投资基金二期(大基金二期)注册成立(2041.5亿)", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 3, "2041亿元聚焦半导体设备材料卡脖子环节与下游应用", "gov_20191022"),
    ("2020-08-04", "AMC", "国务院", "新时期促进集成电路产业和软件产业高质量发展若干政策(国发〔2020〕8号)", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 3, "28nm及以下芯片生产企业最高十年免征企业所得税", "gov_20200804"),
    ("2023-06-16", "AMC", "国务院常务会议", "加大力度支持科技型企业融资行动方案", "SEMI_HARDTECH", "GREEN_DEREG_MA", 2, "构建以股权投资为主股贷债保联动的科技金融支撑体系", "master_M0444"),
    ("2024-04-07", "WEEKEND_HOLIDAY", "中国人民银行", "宣布设立5000亿元科技创新和技术改造再贷款(利率1.75%)", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 2, "5000亿低成本央行再贷款定向支持设备更新与硬科技技改", "pboc_20240407"),
    ("2024-05-24", "AMC", "财政部/六大行等", "国家集成电路产业投资基金三期(大基金三期)注册成立(3440亿)", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 3, "3440亿元规模超越一二期总和，重点投向先进制程/HBM/光刻设备", "gov_20240524"),
    ("2024-06-19", "INTRADAY", "中国证监会", "关于深化科创板改革服务科技创新和新质生产力发展的八条措施(科创板八条)", "SEMI_HARDTECH", "GREEN_DEREG_MA", 3, "支持硬科技并购未盈利优质资产与再融资储架发行试点", "master_M0523"),
    ("2024-06-25", "AMC", "财政部等三部门", "关于实施设备更新贷款贴息政策的通知", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 2, "中央财政对制造业设备更新贷款给予1.5个百分点贴息", "mof_20240625"),
    ("2025-05-14", "AMC", "科技部/央行/证监会等七部门", "加快构建科技金融体制有力支撑高水平科技自立自强若干举措(科技金融15条)", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 2, "设立国家创投引导基金并重开科创板第五套未盈利标准案例", "master_M0584"),
    ("2026-04-10", "AMC", "中国证监会", "关于深化创业板改革更好服务新质生产力发展的意见", "SEMI_HARDTECH", "GREEN_DEREG_MA", 2, "增设创业板第四套成长创新标准与IPO预先审阅机制", "master_M0620"),
    ("2026-09-29", "AMC", "工信部/发改委/财政部/税务总局", "2026年度享受增值税加计抵减政策的集成电路企业清单制定工作通知", "SEMI_HARDTECH", "GREEN_SUBSIDY_PLAN", 2, "延续集成电路设计制造封测设备材料企业增值税加计抵减优惠", "miit_20260929"),

    # --- TMT_AI_MEDIA (TMT/人工智能/算力/通信/数字经济) ---
    ("2013-08-17", "WEEKEND_HOLIDAY", "国务院", "宽带中国战略及实施方案", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 2, "首次将宽带网络上升为国家战略性公共基础设施加速光纤投资", "gov_20130817"),
    ("2013-12-04", "AMC", "工信部", "向三大运营商正式发放首批TD-LTE 4G商用牌照", "TMT_AI_MEDIA", "GREEN_DEREG_MA", 3, "开启4G基站资本开支周期与移动互联网应用爆发", "miit_20131204"),
    ("2014-05-16", "AMC", "中国证监会", "创业板上市公司证券发行管理暂行办法(证监会令第100号)", "TMT_AI_MEDIA", "GREEN_DEREG_MA", 2, "放宽创业板再融资条件并推出小额快速定增点燃TMT外延并购潮", "master_M0170"),
    ("2014-10-24", "AMC", "中国证监会", "正式发布修订后的上市公司重大资产重组管理办法(证监会令第109号)", "TMT_AI_MEDIA", "GREEN_DEREG_MA", 3, "取消非借壳重大重组审批彻底引爆2014-2015互联网传媒并购牛", "master_M0176"),
    ("2015-07-04", "WEEKEND_HOLIDAY", "国务院", "关于积极推进互联网+行动的指导意见(国发〔2015〕40号)", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 2, "顶层部署云计算大数据物联网与产业互联网融合", "gov_20150704"),
    ("2016-05-06", "AMC", "中国证监会", "发布会回应中概股借壳并严控影视游戏VR互金跨界并购序幕", "TMT_AI_MEDIA", "RED_CRACKDOWN_BAN", 2, "叫停伪跨界定增直接刺破TMT并购泡沫估值", "master_M0236"),
    ("2017-07-20", "AMC", "国务院", "新一代人工智能发展规划(国发〔2017〕35号)", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 2, "确立三步走人工智能国家战略与核心产业万亿目标", "gov_20170720"),
    ("2019-06-06", "INTRADAY", "工信部", "正式向四大运营商发放5G商用牌照", "TMT_AI_MEDIA", "GREEN_DEREG_MA", 3, "提前半年发放5G牌照开启新一轮通信基站与消费电子换机周期", "miit_20190606"),
    ("2020-04-20", "AMC", "国家发改委", "例行发布会首次明确新型基础设施建设(新基建)三大范围", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 2, "将5G、数据中心、人工智能、工业互联网纳入国家新基建", "ndrc_20200420"),
    ("2022-02-17", "AMC", "发改委/网信办/工信部/能源局", "四部门启动8大国家算力枢纽节点全面启动东数西算工程", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 2, "系统性布局西部算力中心集群与骨干光通信网络投资", "ndrc_20220217"),
    ("2022-12-19", "AMC", "中共中央/国务院", "关于构建数据基础制度更好发挥数据要素作用的意见(数据二十条)", "TMT_AI_MEDIA", "GREEN_DEREG_MA", 2, "确立数据产权流通交易收益分配制度开启数据要素资产重估", "gov_20221219"),
    ("2023-02-27", "AMC", "中共中央/国务院", "数字中国建设整体布局规划", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 3, "构建数字基础设施与数据资源两大基础，纳入地方政绩考核", "gov_20230227"),
    ("2023-07-13", "AMC", "国家网信办等七部门", "生成式人工智能服务管理暂行办法(网信办令第15号)", "TMT_AI_MEDIA", "GREEN_DEREG_MA", 2, "由征求意见的严苛责任转向包容审慎分类分级监管促大模型落地", "cac_20230713"),
    ("2023-10-08", "WEEKEND_HOLIDAY", "工信部等六部门", "算力基础设施高质量发展行动计划(工信部联通信〔2023〕180号)", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 2, "量化设定2025年算力规模300EFLOPS与智算占比35%目标", "miit_20231008"),
    ("2025-09-01", "AMC", "国务院", "关于深入实施人工智能+行动的意见(国发〔2025〕11号)", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 3, "设定2027年AI智能体渗透率超70%、2030年超90%国家行动纲领", "gov_20250901"),
    ("2026-02-14", "WEEKEND_HOLIDAY", "发改委等部门", "关于加快招标投标领域人工智能推广应用的实施意见", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 1, "推动人工智能+在公共资源与政企B端系统规模化采购", "ndrc_20260214"),
    ("2026-04-08", "AMC", "发改委/能源局/工信部/数据局", "关于促进人工智能与能源双向赋能的行动方案(国能发科技〔2026〕34号)", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 2, "打通算力中心绿电直连与智能电网双向调度瓶颈", "nea_20260408"),
    ("2026-06-11", "AMC", "工信部/国务院国资委", "关于联合开展2026年度人形机器人与具身智能实景实训专项行动的通知", "TMT_AI_MEDIA", "GREEN_SUBSIDY_PLAN", 2, "组织央国企开放工业制造实景场景采购验证人形机器人", "miit_20260611"),

    # --- EDU_INTERNET (互联网平台/游戏/教培合规) ---
    ("2015-07-18", "WEEKEND_HOLIDAY", "央行等十部门", "关于促进互联网金融健康发展的指导意见", "EDU_INTERNET", "GREEN_DEREG_MA", 1, "首次明确网贷与第三方支付分业监管边界", "pboc_20150718"),
    ("2016-08-24", "AMC", "银监会/工信部/公安部/网信办", "网络借贷信息中介机构业务活动管理暂行办法", "EDU_INTERNET", "RED_CRACKDOWN_BAN", 3, "设置P2P借款上限与银行存管红线直接启动P2P清退潮", "cbrc_20160824"),
    ("2018-12-21", "AMC", "原国家新闻出版广电总局", "时隔9个月恢复公示2018年12月国产网络游戏版号审批", "EDU_INTERNET", "GREEN_DEREG_MA", 2, "解除游戏版号冻结压制，开启内容行业估值修复", "nppa_20181221"),
    ("2020-10-31", "WEEKEND_HOLIDAY", "国务院金融稳定发展委员会", "金融委专题会议定调金融活动全面纳入监管(蚂蚁集团暂缓上市前夕)", "EDU_INTERNET", "RED_CRACKDOWN_BAN", 3, "叫停平台无序金融扩张拉开互联网平台估值重塑序幕", "master_M0369"),
    ("2020-11-10", "INTRADAY", "国家市场监管总局", "关于平台经济领域的反垄断指南(征求意见稿)", "EDU_INTERNET", "RED_CRACKDOWN_BAN", 3, "剑指二选一、大数据杀熟、VIE架构反垄断申报", "samr_20201110"),
    ("2021-02-07", "WEEKEND_HOLIDAY", "国务院反垄断委员会", "正式印发关于平台经济领域的反垄断指南", "EDU_INTERNET", "RED_CRACKDOWN_BAN", 2, "反垄断指南正式落地压缩平台垄断超额利润率", "samr_20210207"),
    ("2021-04-10", "WEEKEND_HOLIDAY", "国家市场监管总局", "依法对阿里巴巴二选一垄断行为作出182.28亿元行政处罚决定", "EDU_INTERNET", "RED_CRACKDOWN_BAN", 3, "创纪录百亿反垄断罚单落地并确立平台整改模板", "samr_20210410"),
    ("2021-04-29", "AMC", "央行/银保监会/证监会/外汇局", "四部门联合约谈腾讯等13家网络平台企业金融业务", "EDU_INTERNET", "RED_CRACKDOWN_BAN", 2, "强制剥离或持牌改造平台金融业务并限期整改", "master_M0384"),
    ("2021-07-24", "WEEKEND_HOLIDAY", "中共中央办公厅/国务院办公厅", "关于进一步减轻义务教育阶段学生作业负担和校外培训负担的意见(双减)", "EDU_INTERNET", "RED_CRACKDOWN_BAN", 3, "K12学科类培训机构一律登记为非营利性并严禁资本化上市融资(行业清零)", "gov_20210724"),
    ("2021-08-30", "AMC", "国家新闻出版署", "关于进一步严格管理切实防止未成年人沉迷网络游戏的通知", "EDU_INTERNET", "RED_CRACKDOWN_BAN", 3, "严格限制未成年人仅周末节假日每日20-21时游戏1小时", "nppa_20210830"),
    ("2023-07-12", "AMC", "国务院", "总理主持召开平台企业座谈会肯定平台经济创新赋能作用", "EDU_INTERNET", "GREEN_DEREG_MA", 2, "标志互联网平台专项整改结束转入常态化监管绿灯", "gov_20230712"),
    ("2023-12-22", "INTRADAY", "国家新闻出版署", "发布网络游戏管理办法(草案征求意见稿)", "EDU_INTERNET", "RED_CRACKDOWN_BAN", 3, "拟禁止每日登录首充诱导及设置充值限额引发游戏板块单日暴跌", "nppa_20231222"),

    # --- PHARMA (医药/创新药/医疗器械集采) ---
    ("2009-04-06", "AMC", "中共中央/国务院", "关于深化医药卫生体制改革的意见(新医改)", "PHARMA", "GREEN_SUBSIDY_PLAN", 3, "确立8500亿投入建设全民医保与基本药物制度扩容基层需求", "gov_20090406"),
    ("2015-08-18", "AMC", "国务院", "关于改革药品医疗器械审评审批制度的意见(国发〔2015〕44号)", "PHARMA", "GREEN_DEREG_MA", 3, "清理积压开启优先审评并接轨国际标准点燃中国创新药黄金十年", "nmpa_20150818"),
    ("2018-11-15", "INTRADAY", "国家医保局/联采办", "4+7城市药品集中采购文件正式发布", "PHARMA", "RED_PRICE_CAP_TAX", 3, "首次国家层面带量采购以价换量，仿制药降价超50%-90%重创旧逻辑", "nhsa_20181115"),
    ("2019-09-30", "AMC", "国家医保局等九部门", "关于国家组织药品集中采购和使用试点扩大区域范围实施意见", "PHARMA", "RED_PRICE_CAP_TAX", 2, "4+7集采由11城扩围至全国所有省份仿制药利润率永久压缩", "nhsa_20190930"),
    ("2020-11-05", "INTRADAY", "国家医保局/高值耗材联采办", "首次国家组织冠脉支架集中带量采购在天津开标", "PHARMA", "RED_PRICE_CAP_TAX", 3, "支架均价由1.3万元降至700元(降幅超93%)冲击高值耗材估值", "nhsa_20201105"),
    ("2021-07-02", "AMC", "国家药监局CDE", "发布以临床价值为导向的抗肿瘤药物临床研发指导原则(征求意见稿)", "PHARMA", "RED_CRACKDOWN_BAN", 3, "对照药须选最佳标准治疗直接封杀低水平me-too研发泡沫", "nmpa_20210702"),
    ("2023-07-21", "AMC", "国家卫健委等10部门", "联合召开视频会议部署为期一年的全国医药领域腐败问题集中整治", "PHARMA", "RED_CRACKDOWN_BAN", 3, "医药代表与学术会议全面停滞重创临床推广与处方放量", "nhc_20230721"),
    ("2024-07-05", "AMC", "国务院常务会议", "审议通过全链条支持创新药发展实施方案", "PHARMA", "GREEN_SUBSIDY_PLAN", 3, "统筹价格医保商保投融资全链条破冰创新药支付与进院瓶颈", "gov_20240705"),
    ("2025-06-30", "AMC", "国家医保局/国家卫健委", "联合印发支持创新药高质量发展的若干措施(医保发〔2025〕16号)", "PHARMA", "GREEN_SUBSIDY_PLAN", 2, "增设商业健康保险创新药目录并豁免集采及DRG考核", "nhsa_20250630"),
    ("2025-07-24", "INTRADAY", "国家医保局", "国新办发布会宣布优化集采规则不再简单以最低报价作为参考", "PHARMA", "GREEN_SUPPLY_CUT", 2, "纠偏恶性最低价中标机制开启医药集采反内卷估值修复", "nhsa_20250724"),
    ("2025-12-07", "WEEKEND_HOLIDAY", "国家医保局", "正式发布首版商业健康保险创新药品目录(同步新版国家医保目录)", "PHARMA", "GREEN_SUBSIDY_PLAN", 2, "开辟高价前沿创新药商保支付第二曲线", "nhsa_20251207"),

    # --- DEFENSE_AERO (军工/商业航天/低空经济) ---
    ("2015-03-12", "INTRADAY", "中共中央/全国人大解放军代表团会议", "正式明确把军民融合发展上升为国家战略", "DEFENSE_AERO", "GREEN_SUBSIDY_PLAN", 2, "加速民参军准入开放与科研院所资产证券化预期", "gov_20150312"),
    ("2017-01-22", "WEEKEND_HOLIDAY", "中共中央政治局", "决定设立中央军民融合发展委员会统筹军工改革", "DEFENSE_AERO", "GREEN_DEREG_MA", 2, "最高层面统筹军民融合与军工集团混改重组", "gov_20170122"),
    ("2024-03-27", "AMC", "工信部/科技部/财政部/民航局", "联合印发通用航空装备创新应用实施方案(2024-2030年)", "DEFENSE_AERO", "GREEN_SUBSIDY_PLAN", 3, "明确2030年形成万亿级低空经济市场规模与eVTOL适航量化目标", "miit_20240327"),
    ("2024-12-27", "AMC", "国家发展改革委", "官宣新设立低空经济发展司统筹低空经济规划与基建", "DEFENSE_AERO", "GREEN_DEREG_MA", 2, "国家级专司机构落地加速低空空域管理改革与地方基建立项", "ndrc_20241227"),
    ("2025-11-29", "WEEKEND_HOLIDAY", "国家航天局", "宣布设立商业航天司作为国家级专职监管统筹机构", "DEFENSE_AERO", "GREEN_DEREG_MA", 2, "理顺商业航天发射频率轨位审批加速卫星互联网组网", "cnsa_20251129"),
    ("2025-12-26", "AMC", "国家发展改革委", "印发低空经济及其核心产业统计分类(试行)(发改低空〔2025〕1676号)", "DEFENSE_AERO", "GREEN_SUBSIDY_PLAN", 1, "明确低空经济核心统计边界便于财政统计考核", "ndrc_20251226"),
    ("2026-03-01", "WEEKEND_HOLIDAY", "发改委/金融监管总局/民航局", "联合发布关于推动低空保险高质量发展的实施意见(发改低空〔2026〕123号)", "DEFENSE_AERO", "GREEN_DEREG_MA", 1, "构建低空无人飞行器责任险支撑商业运营闭环", "ndrc_20260301"),

    # --- REAL_ESTATE (房地产政策大周期) ---
    ("2010-04-17", "WEEKEND_HOLIDAY", "国务院", "关于坚决遏制部分城市房价过快上涨的通知(国发〔2010〕10号,新国十条)", "REAL_ESTATE", "RED_CRACKDOWN_BAN", 3, "首创限购与暂停房企再融资并购重组打开十年严控大门", "master_M0102"),
    ("2011-01-26", "AMC", "国务院办公厅", "关于进一步做好房地产市场调控工作有关问题的通知(新国八条)", "REAL_ESTATE", "RED_CRACKDOWN_BAN", 3, "二套房首付提至60%且全国全面扩围限购", "gov_20110126"),
    ("2013-02-20", "AMC", "国务院常务会议", "确定五项房地产调控政策措施(新国五条)", "REAL_ESTATE", "RED_CRACKDOWN_BAN", 2, "严格按二手房转让所得20%计征个税与扩大限购城市", "gov_20130220"),
    ("2014-09-30", "AMC", "中国人民银行/银监会", "关于进一步做好住房金融服务工作的通知(930房贷新政)", "REAL_ESTATE", "GREEN_DEREG_MA", 3, "首次认贷不认房且首套房贷利率下限下浮至7折开启地产反弹", "pboc_20140930"),
    ("2015-03-30", "AMC", "央行/住建部/银监会", "关于个人住房贷款政策有关问题的通知(330新政)", "REAL_ESTATE", "GREEN_DEREG_MA", 3, "二套房首付降至四成且二手房营业税免征由5年缩至2年", "pboc_20150330"),
    ("2016-02-02", "AMC", "中国人民银行/银监会", "关于调整个人住房贷款政策有关问题的通知(不限购城市首付降至2成)", "REAL_ESTATE", "GREEN_DEREG_MA", 2, "配合棚改去库存全面降低首付门槛刺激三四线销售", "pboc_20160202"),
    ("2016-09-30", "AMC", "北京市及热点城市调控协同(贯彻中央抑泡沫)", "北京930新政率全国之先重启认房又认贷并升级限购限贷", "REAL_ESTATE", "RED_CRACKDOWN_BAN", 3, "二十余城国庆集中重启限购开启长周期调控收紧", "gov_20160930"),
    ("2020-08-20", "AMC", "住建部/中国人民银行", "重点房地产企业座谈会出台融资管理规则(三道红线)", "REAL_ESTATE", "RED_CRACKDOWN_BAN", 3, "硬性约束净负债率100%/现金短债比1倍彻底扭转房企高杠杆模式", "mohurd_20200820"),
    ("2020-12-31", "AMC", "中国人民银行/银保监会", "建立银行业金融机构房地产贷款集中度管理制度的通知", "REAL_ESTATE", "RED_CRACKDOWN_BAN", 3, "分五档硬性限制银行涉房贷款与按揭占比上限切断开发贷增量", "pboc_20201231"),
    ("2021-02-08", "AMC", "深圳市住建局(全国二手房指导价制度首创扩散)", "率先建立二手住房成交参考价格发布机制倒逼按揭收缩", "REAL_ESTATE", "RED_CRACKDOWN_BAN", 2, "参考价低于市场价30%锁定杠杆引发全国核心城市跟进", "szjs_20210208"),
    ("2022-11-11", "AMC", "中国人民银行/银保监会", "关于做好当前金融支持房地产市场平稳健康发展工作的通知(金融十六条)", "REAL_ESTATE", "GREEN_DEREG_MA", 3, "允许开发贷信托融资展期并推出保交楼专项借款救市", "pboc_20221111"),
    ("2022-11-28", "AMC", "中国证监会", "在股权融资方面调整优化5项措施(地产第三支箭恢复涉房股权融资)", "REAL_ESTATE", "GREEN_DEREG_MA", 3, "时隔多年全面恢复涉房企业并购重组与配套再融资", "csrc_20221128"),
    ("2023-08-25", "AMC", "住建部/央行/金融监管总局", "关于优化个人住房贷款中住房套数认定标准的通知(认房不认贷)", "REAL_ESTATE", "GREEN_DEREG_MA", 2, "推动一线城市全面落地首套认房不认贷释放改善需求", "mohurd_20230825"),
    ("2024-05-17", "INTRADAY", "中国人民银行/金融监管总局", "517地产新政取消全国房贷利率下限降首付并设3000亿保障房再贷款", "REAL_ESTATE", "GREEN_DEREG_MA", 3, "首付降至15%并创设3000亿收储再贷款加速地产去库存", "pboc_20240517"),
    ("2024-09-29", "WEEKEND_HOLIDAY", "中国人民银行", "2024年第11号公告完善房贷定价机制暨存量房贷利率批量下调", "REAL_ESTATE", "GREEN_DEREG_MA", 3, "存量房贷利率统一降至LPR-30bp减轻居民利息支出约1500亿元", "pboc_20240929"),

    # --- CONSUMPTION_BAIJIU / CONS_OPT (消费/白酒/以旧换新) ---
    ("2012-12-04", "AMC", "中共中央政治局", "审议通过改进工作作风密切联系群众八项规定", "CONSUMPTION_BAIJIU", "RED_CRACKDOWN_BAN", 3, "严控公款吃喝招待直接摧毁高端政务白酒需求触发两年深度调整", "gov_20121204"),
    ("2013-12-04", "AMC", "中央军委办公厅", "印发军队厉行节约反对浪费规定严格落实禁酒令", "CONSUMPTION_BAIJIU", "RED_CRACKDOWN_BAN", 2, "彻底切断军政公务用酒消费场景压制高端酒销量", "gov_20131204"),
    ("2024-03-13", "AMC", "国务院", "推动大规模设备更新和消费品以旧换新行动方案(国发〔2024〕7号)", "CONS_OPT", "GREEN_SUBSIDY_PLAN", 2, "部署汽车家电家装大规模以旧换新财政金融政策", "gov_20240313"),
    ("2024-07-24", "AMC", "国家发改委/财政部", "统筹安排3000亿元超长期特别国债资金加力支持两新(家电汽车补贴)", "CONS_OPT", "GREEN_SUBSIDY_PLAN", 3, "首次直接动用1500亿中央超长期特别国债直接补贴消费品以旧换新", "ndrc_20240724"),
    ("2025-01-08", "AMC", "国家发改委/财政部", "2025年加力扩围实施两新政策(首次纳入手机平板手表消费电子补贴)", "CONS_OPT", "GREEN_SUBSIDY_PLAN", 3, "国补首次扩围至数码消费电子15%补贴(单件上限500元)", "ndrc_20250108"),
    ("2025-03-16", "WEEKEND_HOLIDAY", "中共中央办公厅/国务院办公厅", "印发提振消费专项行动方案", "CONS_OPT", "GREEN_SUBSIDY_PLAN", 2, "围绕居民增收、生育医疗休假与服务消费扩大内需", "gov_20250316"),
    ("2025-04-10", "AMC", "国务院关税税则委员会", "公告应对美国对等关税加征反制关税措施", "CONS_OPT", "RED_PRICE_CAP_TAX", 3, "中美关税冲击升级压制出口链消费制造盈利预期", "mof_20250410"),
    ("2025-05-18", "WEEKEND_HOLIDAY", "中共中央/国务院", "印发修订后党政机关厉行节约反对浪费条例明确工作餐不上酒", "CONSUMPTION_BAIJIU", "RED_CRACKDOWN_BAN", 2, "公务接待工作餐刚性禁酒压制政商宴请白酒场景预期", "gov_20250518"),
    ("2026-01-06", "AMC", "商务部等7部门", "关于提质增效实施2026年消费品以旧换新政策的通知", "CONS_OPT", "GREEN_SUBSIDY_PLAN", 2, "接续2026年家电数码智能穿戴与新能源汽车下乡补贴", "mofcom_20260106"),

    # --- SUPPLY_CYCLICAL (钢铁/煤炭/稀土/水电 供给侧去产能与限价干预) ---
    ("2012-06-13", "AMC", "工信部", "稀土指令性生产计划管理暂行办法", "SUPPLY_CYCLICAL", "GREEN_SUPPLY_CUT", 2, "强化稀土开采冶炼分离指令性配额管控供给", "miit_20120613"),
    ("2016-02-04", "AMC", "国务院", "关于钢铁行业化解过剩产能实现脱困发展的意见(压减粗钢1-1.5亿吨)", "SUPPLY_CYCLICAL", "GREEN_SUPPLY_CUT", 3, "行政硬性压减粗钢产能严禁新增产能扭转全行业亏损", "gov_20160204"),
    ("2016-02-05", "AMC", "国务院", "关于煤炭行业化解过剩产能实现脱困发展的意见(国发〔2016〕7号)", "SUPPLY_CYCLICAL", "GREEN_SUPPLY_CUT", 3, "退出煤炭过剩产能5亿吨并停批新建煤矿", "gov_20160205"),
    ("2016-04-25", "AMC", "国家能源局", "2016年第4号公告规定煤矿按全年作业不超过276个工作日核定产能", "SUPPLY_CYCLICAL", "GREEN_SUPPLY_CUT", 3, "硬性削减煤炭法定工作天数16%直接引发煤价暴涨翻倍", "nea_20160425"),
    ("2016-05-18", "AMC", "财政部", "设立1000亿元工业企业结构调整专项奖补资金支持钢铁煤炭去产能", "SUPPLY_CYCLICAL", "GREEN_SUBSIDY_PLAN", 2, "千亿财政真金白银补贴下岗安置加速僵尸高炉煤矿退出", "mof_20160518"),
    ("2017-01-10", "AMC", "国家发改委", "明确设定2017年6月30日前全面彻底取缔地条钢大限", "SUPPLY_CYCLICAL", "GREEN_SUPPLY_CUT", 3, "强力清除上亿吨中频炉非法产能推动螺纹钢吨毛利暴涨至千元以上", "ndrc_20170110"),
    ("2021-05-19", "AMC", "国务院常务会议", "部署做好大宗商品保供稳价工作严厉打击囤积居奇与恶意炒作", "SUPPLY_CYCLICAL", "RED_PRICE_CAP_TAX", 2, "高层点名抑制工业品通胀风险打压黑色与有色顺周期行情", "gov_20210519"),
    ("2021-10-19", "AMC", "国家发展改革委", "连续召开会议研究依法对煤炭价格实施行政干预措施", "SUPPLY_CYCLICAL", "RED_PRICE_CAP_TAX", 3, "发改委启动价格法干预动力煤坑口/港口最高限价直接打断周期牛市", "ndrc_20211019"),
    ("2025-01-07", "AMC", "国家发展改革委", "正式印发全国统一大市场建设指引(试行)", "SUPPLY_CYCLICAL", "GREEN_SUPPLY_CUT", 1, "破除地方政府违规招商补贴与恶性产能保护", "ndrc_20250107"),
    ("2025-07-19", "WEEKEND_HOLIDAY", "国务院/雅鲁藏布江下游水电工程", "总投资约1.2万亿元雅鲁藏布江下游水电工程正式宣布开工", "SUPPLY_CYCLICAL", "GREEN_SUBSIDY_PLAN", 3, "1.2万亿超级基建直接重估西南民爆水泥水电盾构装备需求", "gov_20250719"),

    # --- BANK (银行监管/资管新规/利率并轨/国家注资) ---
    ("2015-03-31", "AMC", "国务院", "李克强签署第660号国务院令公布《存款保险条例》", "BANK", "GREEN_DEREG_MA", 1, "建立存款保险制度为利率市场化与银行估值重塑扫清制度障碍", "gov_20150331"),
    ("2017-04-07", "AMC", "原中国银监会", "银监发〔2017〕6号《关于银行业风险防控工作的指导意见》启动三三四检查", "BANK", "RED_CRACKDOWN_BAN", 3, "严查监管套利空转套利同业理财嵌套引发银行表外收缩与债股双杀", "cbrc_20170407"),
    ("2018-04-27", "AMC", "央行/银保监会/证监会/外汇局", "正式发布《关于规范金融机构资产管理业务的指导意见》(资管新规)", "BANK", "RED_CRACKDOWN_BAN", 3, "打破刚兑禁止多层嵌套与资金池彻底重构社融非标融资渠道", "master_M0289"),
    ("2019-08-17", "WEEKEND_HOLIDAY", "中国人民银行", "〔2019〕第15号公告改革完善贷款市场报价利率(LPR)形成机制", "BANK", "RED_PRICE_CAP_TAX", 2, "推动贷款利率市场化并轨压缩银行净息差预期", "pboc_20190817"),
    ("2024-09-24", "AMC", "央行/金融监管总局/证监会", "国新办官宣发行特别国债支持国有大型商业银行补充核心一级资本", "BANK", "GREEN_SUBSIDY_PLAN", 2, "中央财政注资夯实国有大行资本充足率缓释净息差与不良担忧", "master_M0540"),
    ("2025-03-31", "AMC", "财政部", "正式公布2025年发行首批5000亿元特别国债支持国有大行补充核心一级资本", "BANK", "GREEN_SUBSIDY_PLAN", 2, "5000亿特别国债注资中行建行交行邮储落地增强信贷投放能力", "mof_20250331"),
    ("2026-10-19", "AMC", "中国人民银行", "金融街论坛宣布退出存贷款基准利率并设非银流动性支持工具", "BANK", "GREEN_DEREG_MA", 1, "利率市场化收官并筑牢银行非银流动性防火墙", "master_M0640"),
    ("2026-11-18", "AMC", "财政部", "推进1500亿元中央金融机构注资特别国债发行落地", "BANK", "GREEN_SUBSIDY_PLAN", 2, "进一步夯实国有大型金融机构资本补充与抗风险能力", "master_V2_20261118_MOF"),

    # --- BROKERAGE (券商牌照/两融/杠杆监管/并购重组) ---
    ("2010-03-31", "BMO", "沪深交易所/证监会", "A股融资融券交易试点正式启动", "BROKERAGE", "GREEN_DEREG_MA", 2, "结束单边做多时代开辟券商信用利息业务新收入", "csrc_20100331"),
    ("2010-04-16", "BMO", "中金所/证监会", "首批沪深300股指期货合约正式挂牌上市交易", "BROKERAGE", "GREEN_DEREG_MA", 2, "开启金融衍生品对冲与券商期现套利创新业务", "csrc_20100416"),
    ("2012-05-07", "AMC", "中国证监会/中证协", "第一届证券公司创新发展研讨会(券商创新大会)召开松绑多项管制", "BROKERAGE", "GREEN_DEREG_MA", 3, "放开券商资管通道两融与杠杆限制开启券商加杠杆扩表大周期", "csrc_20120507"),
    ("2014-11-10", "INTRADAY", "中国证监会/香港证监会", "发布联合公告正式批准沪港通于11月17日启动股票交易", "BROKERAGE", "GREEN_DEREG_MA", 3, "资本项目双向开放引入外资增量直接引爆2014年底券商大行情", "master_M0177"),
    ("2015-01-16", "AMC", "中国证监会", "通报券商两融现场检查处罚暂停中信海通国泰君安新开信用账户3个月", "BROKERAGE", "RED_CRACKDOWN_BAN", 2, "重拳整顿两融违规杠杆触发1·19券商集体跌停", "master_M0182"),
    ("2015-06-12", "AMC", "中国证监会", "规定两融不得超净资本4倍并严禁券商为场外配资提供网上接口", "BROKERAGE", "RED_CRACKDOWN_BAN", 3, "直接掐断场外配资伞形信托端口成为5178点见顶去杠杆导火索", "master_M0199"),
    ("2016-08-16", "AMC", "国务院/两地证监会", "批准深港通实施方案并即时取消沪港通总额度限制", "BROKERAGE", "GREEN_DEREG_MA", 2, "彻底打通北向资金无总额上限流入通道", "master_M0243"),
    ("2018-10-20", "WEEKEND_HOLIDAY", "中国证监会", "新闻发言人宣布将IPO被否企业筹划重组上市间隔由3年缩短为6个月", "BROKERAGE", "GREEN_DEREG_MA", 2, "松绑并购重组救市疏通投行创投退出通道", "csrc_20181020"),
    ("2019-12-28", "WEEKEND_HOLIDAY", "全国人大常委会/证监会", "表决通过新修订《中华人民共和国证券法》确立全面推行注册制", "BROKERAGE", "GREEN_DEREG_MA", 2, "立法确立注册制并大幅提高违法违规处罚成本", "master_M0342"),
    ("2020-06-12", "AMC", "中国证监会/深交所", "正式发布创业板改革并试点注册制相关业务规则", "BROKERAGE", "GREEN_DEREG_MA", 2, "存量主板外最大成长板块落地注册制与20%涨跌幅扩容券商投行", "csrc_20200612"),
    ("2023-02-17", "AMC", "中国证监会", "全面实行股票发行注册制165部制度规则正式发布实施", "BROKERAGE", "GREEN_DEREG_MA", 2, "A股主板正式告别核准制迈入全市场注册制", "master_M0435"),
    ("2023-08-27", "WEEKEND_HOLIDAY", "财政部/税务总局/证监会/交易所", "活跃资本市场四箭齐发(印花税减半/收紧IPO/严限减持/保证金降80%)", "BROKERAGE", "GREEN_DEREG_MA", 3, "印花税减半与融资保证金下调直接刺激交投情绪(IPO收紧对冲投行)", "master_M0452"),
    ("2024-09-24", "AMC", "中国证监会", "发布《关于深化上市公司并购重组市场改革的意见》(并购六条)", "BROKERAGE", "GREEN_DEREG_MA", 3, "全面放开跨行业并购与未盈利硬科技资产收购大幅激活券商投行", "csrc_20240924"),
    ("2025-12-06", "WEEKEND_HOLIDAY", "中国证监会", "中证协会员大会表态对优质券商适当优化风控指标打开杠杆空间", "BROKERAGE", "GREEN_DEREG_MA", 2, "支持头部一流投行适度提升资本使用效率与杠杆上限", "master_M0607"),
    ("2025-12-31", "AMC", "国家金融监督管理总局", "发布《商业银行并购贷款管理办法》(金规〔2025〕27号)", "BROKERAGE", "GREEN_DEREG_MA", 2, "控制型并购贷款比例上限提至80%期限延至10年协同并购重磅", "master_M0611"),
    ("2026-11-22", "WEEKEND_HOLIDAY", "中国证监会/沪深北交易所", "融资买入最低保证金比例由100%调低至80%并降费让利27.6亿", "BROKERAGE", "GREEN_DEREG_MA", 2, "新老合约适用降保证金扩充两融杠杆弹性并降低券商交易成本", "master_V2_20261122_MARGIN"),

    # --- CENTRAL_SOE_DIV (央企/红利/保险长钱/市值管理) ---
    ("2008-08-27", "AMC", "中国证监会", "令第56号松绑大股东自由增持并同步将再融资三年现金分红门槛提至30%", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "制度性倒逼高盈利央企大盘提高现金分红比例", "master_M0079"),
    ("2008-09-18", "AMC", "财政部/汇金/国资委/证监会", "918救市印花税单边+汇金自主购入三大行+国资委支持央企增持", "CENTRAL_SOE_DIV", "GREEN_SUBSIDY_PLAN", 3, "国家队真金白银托底央企金融大盘权重", "master_M0082"),
    ("2012-11-16", "AMC", "财政部/税务总局/证监会", "财税〔2012〕85号实施股息红利差别化个税(持股超1年税负降至5%)", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "长期持仓高股息股票税负减半鼓励长线红利配置", "master_M0142"),
    ("2015-08-23", "WEEKEND_HOLIDAY", "国务院", "正式印发《基本养老保险基金投资管理办法》准许养老金入市", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "放开养老金最高30%比例投资权益资产偏向稳健高股息蓝筹", "gov_20150823"),
    ("2015-09-13", "WEEKEND_HOLIDAY", "中共中央/国务院", "正式发布《关于深化国有企业改革的指导意见》(中发〔2015〕22号)", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "确立国企改革1+N顶层设计分类推进混改与重组", "gov_20150913"),
    ("2017-08-20", "WEEKEND_HOLIDAY", "国务院国资委/中国联通", "中国联通正式发布780亿混改方案引入BATJ战略投资者", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "央企混改标杆落地激发国企资产整合重估", "sasac_20170820"),
    ("2020-07-17", "AMC", "原银保监会", "优化保险公司权益类资产配置监管通知(最高可配总资产45%)", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "上调高偿付能力险企权益投资比例上限引导长钱增配高股息", "master_M0355"),
    ("2022-05-27", "AMC", "国务院国资委", "印发《提高央企控股上市公司质量工作方案》", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "试点将上市公司发展质量纳入央企负责人经营业绩考核", "master_M0416"),
    ("2022-11-25", "AMC", "人社部等五部门", "宣布个人养老金制度在36个先行城市正式启动实施", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "开辟第三支柱长期税收递延养老资金源头活水", "mohrss_20221125"),
    ("2023-03-03", "AMC", "国务院国资委", "对标世界一流企业价值创造行动启动会落实一利五率考核", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "ROE与营业现金比率硬考核倒逼央企提质增效分红", "master_M0439"),
    ("2023-09-10", "WEEKEND_HOLIDAY", "国家金融监督管理总局", "金规〔2023〕5号下调险资投资沪深300与科创板股票风险因子", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "降低保险长钱配置大盘蓝筹资本占用释放入市空间", "master_M0455"),
    ("2023-10-31", "AMC", "财政部", "财金〔2023〕89号实行国有商业保险公司3年长周期考核", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "50%权重考核3年ROE平滑险资短期权益波动顾虑", "master_M0467"),
    ("2024-01-24", "INTRADAY", "国务院国资委", "国新办发布会宣布进一步研究将市值管理纳入央企负责人业绩考核", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 3, "市值管理与分红回购直接挂钩央企掌门考核引发中字头强重估", "master_M0482"),
    ("2024-11-15", "AMC", "中国证监会", "正式发布《上市公司监管指引第10号——市值管理》", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "强制主要指数成分股与长期破净央国企披露估值提升计划", "master_M0555"),
    ("2025-01-22", "AMC", "中央金融办/证监会/财政部等六部门", "联合印发《关于推动中长期资金入市工作的实施方案》", "CENTRAL_SOE_DIV", "GREEN_SUBSIDY_PLAN", 3, "硬指标要求大型国有险企每年新增保费30%投A股+3年长周期考核占60%", "master_M0571"),
    ("2025-04-08", "BMO", "央行/中央汇金/金融监管总局/国资委", "汇金明确类平准基金定位+金规12号险资权益上限提5pct达50%", "CENTRAL_SOE_DIV", "GREEN_SUBSIDY_PLAN", 3, "关税暴跌次日国家队联合险资与央企千亿回购暴力托底大盘蓝筹", "master_M0579"),
    ("2025-12-05", "AMC", "国家金融监督管理总局", "金规〔2025〕24号下调险资长持3年以上沪深300与红利低波风险因子至0.27", "CENTRAL_SOE_DIV", "GREEN_DEREG_MA", 2, "进一步定向鼓励险资长仓锁筹高股息红利资产", "master_M0606"),

    # --- MICRO_SHELL (微盘/壳股/退市/量化/减持监管) ---
    ("2014-07-11", "AMC", "中国证监会", "就修订重大资产重组管理办法征求意见拟取消非借壳审批", "MICRO_SHELL", "GREEN_DEREG_MA", 3, "松绑并购重组审批点燃小微盘跨界炒壳估值狂潮", "master_M0172"),
    ("2014-10-17", "AMC", "中国证监会", "正式发布严格实施上市公司退市制度若干意见(证监会令第107号)", "MICRO_SHELL", "RED_CRACKDOWN_BAN", 2, "确立重大违法强制退市机制警示绩差壳股", "master_M0175"),
    ("2016-06-17", "AMC", "中国证监会", "就修改重大资产重组管理办法公开征求意见(史上最严借壳新规)", "MICRO_SHELL", "RED_CRACKDOWN_BAN", 3, "严格认定借壳标准禁止配套融资并延长锁定期直接杀死壳股生态", "master_M0239"),
    ("2016-09-09", "AMC", "中国证监会", "正式发布修改后的《上市公司重大资产重组管理办法》", "MICRO_SHELL", "RED_CRACKDOWN_BAN", 2, "最严借壳新规正式生效持续挤压小微壳资源溢价", "master_M0244"),
    ("2017-04-08", "WEEKEND_HOLIDAY", "中国证监会", "中上协大会痛批铁公鸡不分红与10送30高送转违规套现", "MICRO_SHELL", "RED_CRACKDOWN_BAN", 3, "严打次新股高送转与题材炒作开启2017小盘股结构性杀跌", "master_M0259"),
    ("2017-05-27", "WEEKEND_HOLIDAY", "中国证监会", "发布上市公司股东董监高减持若干规定(9号文,减持新规)", "MICRO_SHELL", "RED_CRACKDOWN_BAN", 2, "封堵大宗交易过桥减持与定增限售股解禁抛压", "master_M0263"),
    ("2020-11-02", "AMC", "中央深改委/证监会", "审议通过《健全上市公司退市机制实施方案》常态化退市", "MICRO_SHELL", "RED_CRACKDOWN_BAN", 2, "增加营收低于1亿+亏损退市财务组合指标精准出清绩差壳", "master_M0370"),
    ("2023-02-17", "AMC", "沪深交易所", "发布《主板股票异常交易实时监控细则》统一严重异常波动标准", "MICRO_SHELL", "RED_CRACKDOWN_BAN", 2, "10日100%/30日200%异动触发重点监控压制高位小盘连板炒作", "master_M0436"),
    ("2024-02-06", "INTRADAY", "中央汇金/证监会", "暂停新增转融券并扩大汇金ETF增持(微盘流动性危机次日强干预)", "MICRO_SHELL", "GREEN_DEREG_MA", 2, "暂停转融券配合国新国家队稳定流动性阻止小盘踩踏", "master_M0487"),
    ("2024-04-12", "AMC", "国务院/证监会/三大交易所", "新国九条+分红不达标ST与最严退市新规征求意见", "MICRO_SHELL", "RED_CRACKDOWN_BAN", 3, "主板营收低于3亿+分红不达标ST硬约束引发微盘壳股系统性重定价暴跌", "master_M0504"),
    ("2024-05-15", "AMC", "中国证监会", "发布《证券市场程序化交易管理规定(试行)》严管高频量化增本降速", "MICRO_SHELL", "RED_CRACKDOWN_BAN", 2, "限制高频撤单加收流量费压降微盘小票高频交易流动性溢价", "master_M0514"),
    ("2026-11-11", "AMC", "中国证监会", "推进《证券市场先行赔付指导意见》征求意见从严打击造假问题股", "MICRO_SHELL", "RED_CRACKDOWN_BAN", 2, "强化财务造假先行赔付与退市追责压制ST及问题微盘股", "master_M0654"),
]


def build_pillar3():
    panel, dates, date_to_idx = cm.load_market_panel()
    rows = []
    horizons = [20, 60, 120, 250]

    for i, ev in enumerate(EVENTS):
        dt, slot, ministry, title, sec_code, sig_type, intensity, mech, src_ref = ev
        t_entry, t_prior, trad_dt = cm.align_event_pit(dt, slot, dates, date_to_idx)
        prior_st = cm.extract_prior_state(panel, t_prior)

        p_col, fb1, fb2 = SECTOR_COL_MAP[sec_code]
        polarity = 1 if sig_type.startswith("GREEN") else -1

        # Determine usable column at t_entry for spliced fallback while tracking exact availability
        used_col = p_col
        is_proxy = 0
        if t_entry >= 0:
            if pd.isna(panel.at[t_entry, f"{p_col}_open"]):
                is_proxy = 1
                if pd.notna(panel.at[t_entry, f"{fb1}_open"]):
                    used_col = fb1
                elif pd.notna(panel.at[t_entry, f"{fb2}_open"]):
                    used_col = fb2
                else:
                    used_col = "bench"

        # Pre-event sector momentum (20d prior to t_prior)
        sec_prior_ret_20d = np.nan
        sec_prior_ex_20d = np.nan
        if t_prior >= 20:
            c_col = f"{used_col}_close"
            if c_col in panel.columns and pd.notna(panel.at[t_prior, c_col]) and pd.notna(panel.at[t_prior - 20, c_col]):
                s_r = float(panel.at[t_prior, c_col] / panel.at[t_prior - 20, c_col] - 1.0)
                b_r = float(panel.at[t_prior, "csi300_close"] / panel.at[t_prior - 20, "csi300_close"] - 1.0)
                sec_prior_ret_20d = s_r
                sec_prior_ex_20d = s_r - b_r

        rec = {
            "event_id": f"P3_{i+1:03d}",
            "event_date": dt,
            "release_slot": slot,
            "tradable_date": trad_dt,
            "t_entry_idx": t_entry,
            "t_prior_idx": t_prior,
            "year": int(dt[:4]),
            "period_split": "IS_2008_2020" if dt <= "2020-12-31" else "OOS_2021_2026",
            "ministry": ministry,
            "doc_title": title,
            "sector_code": sec_code,
            "primary_panel_col": p_col,
            "fallback_panel_col": fb1,
            "used_panel_col": used_col,
            "is_proxy_used": int(is_proxy),
            "signal_type": sig_type,
            "signal_polarity": int(polarity),
            "intensity": int(intensity),
            "mechanism_summary": mech,
            "source_ref": src_ref,
            "sector_prior_ret_20d": sec_prior_ret_20d,
            "sector_prior_ex_20d": sec_prior_ex_20d,
        }
        rec.update(prior_st)

        # Forward returns from next tradable open against CSI 300
        for h in horizons:
            c300_r = cm.calc_fwd_return(panel, t_entry, h, "csi300")
            ex_r_exact = cm.calc_fwd_return(panel, t_entry, h, p_col)
            sp_r = cm.calc_fwd_return(panel, t_entry, h, used_col)
            rec[f"ret_csi300_{h}d"] = c300_r
            rec[f"ret_exact_{h}d"] = ex_r_exact
            rec[f"ret_spliced_{h}d"] = sp_r
            rec[f"ex_exact_{h}d"] = (ex_r_exact - c300_r) if (pd.notna(ex_r_exact) and pd.notna(c300_r)) else np.nan
            rec[f"ex_spliced_{h}d"] = (sp_r - c300_r) if (pd.notna(sp_r) and pd.notna(c300_r)) else np.nan

        rec["mdd_sector_60d"] = cm.calc_fwd_max_drawdown(panel, t_entry, 60, used_col)
        rec["mdd_sector_120d"] = cm.calc_fwd_max_drawdown(panel, t_entry, 120, used_col)
        rows.append(rec)

    df = pd.DataFrame(rows).sort_values(["event_date", "sector_code"]).reset_index(drop=True)
    df.to_parquet(OUT_PQ, index=False)

    # Empirical backtest audit by signal_type (Full / IS <=2020 / OOS 2021~2026)
    sig_types = [
        "GREEN_SUBSIDY_PLAN",
        "GREEN_DEREG_MA",
        "GREEN_SUPPLY_CUT",
        "RED_CRACKDOWN_BAN",
        "RED_PRICE_CAP_TAX",
    ]
    summary_by_signal = {}
    for mode_label, col_prefix in [("spliced_panel", "ex_spliced"), ("exact_index_only", "ex_exact")]:
        mode_rows = []
        for stype in sig_types:
            pol = 1 if stype.startswith("GREEN") else -1
            for split_name, mask_fn in [
                ("FULL", lambda d: d["signal_type"] == stype),
                ("IS_le2020", lambda d: (d["signal_type"] == stype) & (d["year"] <= 2020)),
                ("OOS_2021_2026", lambda d: (d["signal_type"] == stype) & (d["year"] >= 2021)),
            ]:
                sub = df[mask_fn(df) & (df["t_entry_idx"] >= 0)]
                rec_s = {"signal_type": stype, "polarity": pol, "split": split_name, "n_events": int(len(sub))}
                for h in horizons:
                    vals = sub[f"{col_prefix}_{h}d"].to_numpy(dtype=float)
                    st = cm.calc_sample_stats(vals, exp_dir=pol)
                    raw_pos_win = float(np.mean(vals[np.isfinite(vals)] > 0)) if st["n"] > 0 else np.nan
                    rec_s[f"n_{h}d"] = st["n"]
                    rec_s[f"ex_mean_{h}d_pct"] = round(st["mean"] * 100, 2) if pd.notna(st["mean"]) else None
                    rec_s[f"ex_med_{h}d_pct"] = round(st["median"] * 100, 2) if pd.notna(st["median"]) else None
                    rec_s[f"dir_win_{h}d_pct"] = round(st["win_rate"] * 100, 1) if pd.notna(st["win_rate"]) else None
                    rec_s[f"raw_pos_{h}d_pct"] = round(raw_pos_win * 100, 1) if pd.notna(raw_pos_win) else None
                    rec_s[f"payoff_{h}d"] = round(st["payoff"], 2) if pd.notna(st["payoff"]) else None
                mode_rows.append(rec_s)
        summary_by_signal[mode_label] = mode_rows

    # Also intensity=3 breakdown & sector breakdown
    intensity3_rows = []
    for stype in sig_types:
        pol = 1 if stype.startswith("GREEN") else -1
        sub = df[(df["signal_type"] == stype) & (df["intensity"] == 3) & (df["t_entry_idx"] >= 0)]
        r3 = {"signal_type": stype, "n": int(len(sub))}
        for h in horizons:
            st = cm.calc_sample_stats(sub[f"ex_spliced_{h}d"], exp_dir=pol)
            r3[f"ex_{h}d_pct"] = round(st["mean"] * 100, 2) if pd.notna(st["mean"]) else None
            r3[f"dir_win_{h}d_pct"] = round(st["win_rate"] * 100, 1) if pd.notna(st["win_rate"]) else None
            r3[f"payoff_{h}d"] = round(st["payoff"], 2) if pd.notna(st["payoff"]) else None
        intensity3_rows.append(r3)

    audit = {
        "n_events": int(len(df)),
        "date_range": [str(df["event_date"].min()), str(df["event_date"].max())],
        "signal_type_counts": df["signal_type"].value_counts().to_dict(),
        "sector_counts": df["sector_code"].value_counts().to_dict(),
        "proxy_used_count": int(df["is_proxy_used"].sum()),
        "summary_by_signal": summary_by_signal,
        "intensity3_summary_spliced": intensity3_rows,
    }
    with open(OUT_AUDIT, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"[Pillar 3] Saved {OUT_PQ}: {len(df)} events [{audit['date_range'][0]} ~ {audit['date_range'][1]}], proxy={audit['proxy_used_count']}")
    print("  Counts:", audit["signal_type_counts"])
    print("  --- Spliced Panel FULL vs IS vs OOS (Excess vs CSI300) ---")
    for r in summary_by_signal["spliced_panel"]:
        if r["split"] == "FULL":
            print(f"  {r['signal_type']:20s} FULL n={r['n_events']:2d} | 20d:{r['ex_mean_20d_pct']}% | 60d:{r['ex_mean_60d_pct']}% | 120d:{r['ex_mean_120d_pct']}% (dir_win:{r['dir_win_120d_pct']}%, payoff:{r['payoff_120d']}) | 250d:{r['ex_mean_250d_pct']}%")
    print("  --- IS (<=2020) vs OOS (2021~2026) 120d Excess ---")
    for r in summary_by_signal["spliced_panel"]:
        if r["split"] != "FULL":
            print(f"  {r['signal_type']:20s} {r['split']:13s} n={r['n_120d']:2d} | 60d:{r['ex_mean_60d_pct']}% | 120d:{r['ex_mean_120d_pct']}% (dir_win:{r['dir_win_120d_pct']}%, payoff:{r['payoff_120d']}) | 250d:{r['ex_mean_250d_pct']}%")
    print("  --- Exact Index Only FULL 120d Excess ---")
    for r in summary_by_signal["exact_index_only"]:
        if r["split"] == "FULL":
            print(f"  {r['signal_type']:20s} EXACT n={r['n_120d']:2d} | 60d:{r['ex_mean_60d_pct']}% | 120d:{r['ex_mean_120d_pct']}% (dir_win:{r['dir_win_120d_pct']}%, payoff:{r['payoff_120d']})")


if __name__ == "__main__":
    build_pillar3()

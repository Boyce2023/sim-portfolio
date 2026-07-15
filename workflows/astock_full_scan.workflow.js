// A股完整扫描 step1-7 — 选股 × 交易侧 融合成一个流程 (2026-07-16)
// 之前astock_v3只有选股侧3步,交易侧(有机体:择时双确认/卖出5道门/sizing)散落在脚本+SOP从未整合进workflow。
// 本workflow把两侧焊成一体: Step0-2选股出头部打分表 → Step3-5调organism_portfolio_builder.py做交易侧整合 → Step6四块报告。
export const meta = {
  name: 'astock-full-scan',
  description: '完整扫描step1-7(选股×交易侧融合): Step0宏观定调/Step1-18树全市场/Step2全树Top候选5维深扫=头部打分表/Step3-5交易侧整合(买入双确认+卖出5道门+sizing,调organism_portfolio_builder.py代码级强制)/Step6四块报告(宏观/头部打分表/建仓调仓逻辑/执行情况)。args=需排除的持仓(重建传[])',
  phases: [
    { title: 'Step0-2 选股(宏观+18树+全树深扫头部打分表)' },
    { title: 'Step3-6 交易侧整合(择时双确认+风控5道门+组合构建+四块报告)' },
  ],
}
const SP = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio'
const TREES = [
  { name:'AI算力(VR200机架重构)', end:'英伟达Rubin AI服务器,大模型厂商capex', chain:'芯片大脑→造壳耗材→封测包→玻纤布/CCL→光互联(锗)→液冷→HBM→设备→钨矿/石英矿/铜矿' },
  { name:'AI端侧(AI手机换机)', end:'本地AI助手手机/PC', chain:'整机→端侧SoC→存储→散热(VC铜)→快充→硅碳负极(硅烷气)→钼矿/钨矿' },
  { name:'人形机器人(替代人力)', end:'特斯拉Optimus/宇树', chain:'整机→减速器→丝杠(轴承钢)→电机→六维力(铍青铜)→电子皮肤→PEEK(萤石→DFBP)→稀土矿' },
  { name:'电动车(消费者+碳中和)', end:'买车消费者+碳中和', chain:'整车→三电→SiC(衬底/石墨)→电机(钕铁硼+镝铽)→电解液(LiPF6→萤石)→负极(针状焦)→锂矿/稀土矿' },
  { name:'固态电池', end:'2027装车全固态', chain:'电解质→前驱体(硫源/锆源)→金属锂负极→干法成膜→硫化锂/锆矿' },
  { name:'智能驾驶(Robotaxi)', end:'L3+/Robotaxi无人车', chain:'激光雷达→域控→线控→高精定位→座舱' },
  { name:'苹果新形态(折叠+AI眼镜)', end:'折叠iPhone+AI眼镜', chain:'UTG→铰链MIM→钛合金;光波导→MicroLED' },
  { name:'创新药(MNC扫货)', end:'ADC/双抗被MNC扫货', chain:'分子→偶联CDMO→毒素HPAPI→连接子/培养基/层析微球' },
  { name:'脑机/手术机器人', end:'脑机+手术机器人商业化', chain:'整机→电极→芯片→高值耗材' },
  { name:'AI供电(电网扩容)', end:'AI数据中心吞电', chain:'配电→海缆→输配电材料→变压器(取向硅钢)→铜/铝→铜矿' },
  { name:'制冷剂(配额涨价)', end:'空调/汽车热管理', chain:'工质→配额制冷剂→氢氟酸→萤石矿' },
  { name:'钨硬质合金(刀具+军工)', end:'数控刀具+军工钨', chain:'刀具→钨粉→APT→钨矿; 与锗无关' },
  { name:'半导体设备国产化', end:'长鑫长存扩产', chain:'扩产现金→刻蚀薄膜→量测→CMP→零部件→EDA→测试设备' },
  { name:'商业航天/卫星互联网', end:'千帆星网组网', chain:'卫星总装→T/R芯片→载荷→火箭→地面终端' },
  { name:'可控核聚变/核电', end:'聚变堆工程化+核电', chain:'主设备→真空容器→第一壁→超导磁体→核电主设备' },
  { name:'军工/低空经济', end:'eVTOL+军贸+导弹补库', chain:'整机→机体材料→推进→弹载连接→机载器件→飞控' },
  { name:'稳定币/金融科技', end:'链上美元+券商IPO跟投', chain:'发牌→清结算→区块链→收单跨境; 券商IPO' },
  { name:'猪周期反转', end:'产能去化→出栏', chain:'出栏→母猪→育肥→饲料添加→动保' },
]
if (TREES.length !== 18) throw new Error(`Step1规格违反:${TREES.length}!=18`)
const norm = t => String(t||'').trim().replace(/\.(SH|SZ|SS|BJ)$/i,'').replace(/^(sh|sz|bj)/i,'').trim()
const HELD = (Array.isArray(args) ? args : []).map(norm)
const MAX_DEEPSCAN = 30   // 全树Top候选深扫上限(防agent爆炸,取强供给侧的前30)

// ============ Step 0: 宏观体检(定regime+sizing系数) ============
phase('Step0-2 选股(宏观+18树+全树深扫头部打分表)')
log('完整扫描启动: Step0宏观 + Step1-18树 + Step2全树深扫头部打分表(不只主升树)')
const macroP = agent(
  `A股宏观体检(先水位后主线再个股): 判断今天市场水位, 为建仓定调。\n`+
  `⛔先跑 date '+%Y-%m-%d %H:%M' 写进输出开头(格式"体检时刻: YYYY-MM-DD HH:MM"),价格标时点。\n`+
  `⛔消息面内部优先(D7): 先跑 python3 ${SP}/scripts/news_layer.py 读内部消息面(写${SP}/data/news_today.json),再针对性WebSearch补。\n`+
  `①核心指数近3月/1月/1周(沪深300/中证1000/创业板/科创50) ②全市场市值中位数vs指数(揭穿失真:指数涨中位数跌=缩圈) ③赚钱效应(涨家占比,收窄=缩圈尾声) ④今日板块强弱 ⑤风格(大盘vs小盘/成长vs价值)。\n`+
  `⑥⛔消息面/catalyst(看"为什么"不只"跌多少"):WebSearch搜隔夜美股(费半/纳指)+政策+龙头公告,判断大跌是错杀(可低吸)还是趋势反转(该避)。\n`+
  `⛔regime定调锚定多周结构(1周/1月/3月连续背离才是真缩圈,单日不算)。结论必须定调:【普涨】/【缩圈】/【普跌】+持续几周+早期/中段/尾声。⛔在输出最后单独一行写"REGIME=普涨"或"REGIME=缩圈"或"REGIME=普跌"(供脚本解析,三选一)。regime决定sizing系数(普涨1.0/缩圈0.5/普跌0.3)。\n`+
  `⛔数据禁东财_em(NO_PROXY): from scripts.astock_data_layer import get_full_market,get_limit_up_stocks + 腾讯qt.gtimg.cn拉指数 + ak.stock_zh_a_daily,timeout=8。禁子agent。`,
  { label:'Step0-宏观定调', phase:'Step0-2 选股(宏观+18树+全树深扫头部打分表)' })

// ============ Step 1: 18树全市场扫描 → 埋伏候选 ============
const TREE_SCHEMA = { type:'object', properties:{
  tree:{type:'string'}, today_state:{type:'string',description:'今天:哪环在炒/退潮/主线位置(启动/主升早/主升中/台阶/尾声/退潮/未启动)'},
  is_hot:{type:'boolean',description:'今天在主升/启动?'},
  ambush:{type:'array',items:{type:'object',properties:{ticker:{type:'string'},name:{type:'string'},env:{type:'string'},why_ambush:{type:'string'}},required:['ticker','name','env']}}
}, required:['tree','today_state','is_hot','ambush'] }
const VERDICT = { type:'object', properties:{
  decision:{type:'string',enum:['probe','watch','reject','hold'],description:'二维裁决:probe=基本面好+主升中/watch=基本面好末段等回踩/reject=基本面差/hold=已持仓'},
  fundamental:{type:'string',description:'基本面轴:好/差+依据(Edge真假/份额/概念蹭/暴雷/估值边际)'},
  trend:{type:'string',description:'量价轴:主升中/末段见顶/下跌(看量价结构非涨幅)'},
  sabct:{type:'string',description:'A+/A/A-/B+/B,A-为建仓门槛'},
  size_now:{type:'string'}, stop:{type:'string'}, catalyst_date:{type:'string'},
  watch_expiry:{type:'string',description:'watch必填三件套:回踩位+失效期5-8日+未触发动作'},
  one_line:{type:'string'}
}, required:['decision','fundamental','trend','sabct','size_now','one_line'] }

const seen = new Set()
const step1trees = []
const allCands = []
const chains = await pipeline(TREES,
  t => agent(
    `扫描A股【${t.name}】产品树今天全链。终端=${t.end}。链=${t.chain}\n`+
    `①今天整体状态:哪环在炒/退潮/主线位置?②is_hot:今天在主升/启动吗?③埋伏环节(产品刚需今天没炒透的):每个ticker+name+环节名+为什么埋伏(追到矿)。至少2-3个,含最强供给侧/矿端。\n`+
    `⛔产品溯源语言禁券商词(小金属/有色→锗光互联/萤石氟链/钨链)。⛔A股数据只用:①from scripts.astock_data_layer import get_full_market,get_limit_up_stocks ②腾讯qt.gtimg.cn(urllib直连,涨跌幅=split('~')[32])③ak.stock_zh_a_daily新浪。禁ak.*_em东财/禁yfinance/禁重试东财。所有请求timeout=8。禁子agent。快速失败:工具≤2次,3分钟返回。`,
    { schema:TREE_SCHEMA, label:t.name.slice(0,12), phase:'Step0-2 选股(宏观+18树+全树深扫头部打分表)' }),
  (tr) => {
    if (!tr) return null
    step1trees.push(tr)
    // ⭐关键改动: 不只主升树,全部树的埋伏候选都进候选池(为重建出完整头部打分表)。热树优先。
    const heat = tr.is_hot ? 0 : 1
    for (const a of (tr.ambush || [])) {
      const k = norm(a.ticker)
      if (!k || k.length !== 6 || seen.has(k) || HELD.includes(k)) continue
      seen.add(k)
      allCands.push({ ...a, tree:tr.tree, heat })
    }
    return tr
  })
log(`Step1完成:18树, 候选池${allCands.length}只(全树,非只主升)`)

// ============ Step 2: 全树Top候选5维深扫 → 头部打分表 ============
// 热树候选优先,取前MAX_DEEPSCAN只深扫(防agent爆炸)
allCands.sort((a,b) => a.heat - b.heat)
const toScan = allCands.slice(0, MAX_DEEPSCAN)
log(`Step2: 深扫${toScan.length}只(全树Top,热树优先)出头部打分表`)
const verdicts = await parallel(toScan.map(c => () => agent(
  `深扫【${c.name} ${c.ticker}】产品树=${c.tree}/环节=${c.env}。二维独立裁决(涨跌永不否决基本面)。\n`+
  `【基本面轴·值不值得买】①供给侧Edge:物理/制度壁垒?真刚需还是概念蹭(挂错节点/份额假)?中国份额?追到矿。②KillShot:真概念蹭/真暴雷(净利大降且无订单产能前瞻支撑)/估值无边际(PEG+前瞻PE判,禁trailing PE)。③催化:在前还是已兑现。\n`+
  `【量价轴·买入时机】④主升中(放量上涨:量比≥1.5且涨>3%/台阶突破/回踩不破)vs末段见顶(放量滞涨:量比≥2且涨<1.5%/高位巨阴/破位)。⛔涨幅大≠末段,看量价结构。\n`+
  `【裁决】基本面差→reject;基本面好+主升中→probe;基本面好+末段→watch(必填watch_expiry三件套)。SABCT给A+/A/A-/B+/B(A-建仓门槛)。⛔禁因涨过/PE高reject好基本面。\n`+
  `⛔A股数据:腾讯qt.gtimg.cn(涨跌幅split('~')[32])/ak.stock_zh_a_daily新浪/astock_data_layer,禁ak.*_em/禁yfinance,所有请求timeout=8。禁子agent。90秒返回。`,
  { schema:VERDICT, label:c.name, phase:'Step0-2 选股(宏观+18树+全树深扫头部打分表)' })
  .then(v => v ? { ticker:norm(c.ticker), name:c.name, tree:c.tree, env:c.env, is_hot:c.heat===0, verdict:v } : null)
))
const scored = verdicts.filter(Boolean)
const macro = await macroP
const regimeMatch = String(macro||'').match(/REGIME=(普涨|缩圈|普跌)/)
const regime = regimeMatch ? regimeMatch[1] : '缩圈'
log(`Step2完成:头部打分表${scored.length}只 | regime=${regime}`)

// ============ Step 3-5: 交易侧整合(买入双确认+卖出5道门+sizing) — 调organism_portfolio_builder.py代码级强制 ============
phase('Step3-6 交易侧整合(择时双确认+风控5道门+组合构建+四块报告)')
// 把头部打分表(SABCT)写文件, 交给整合脚本跑trend_signals+decide_buy/decide_holding
const candForBuilder = scored.map(s => ({ ticker:s.ticker, name:s.name, sabct:s.verdict.sabct, one_line:s.verdict.one_line }))
const integ = await agent(
  `你是A股完整扫描的交易侧整合官。任务:把选股头部打分表 × 交易侧脚本 焊成建仓/调仓计划,并产出四块报告。⛔用代码级整合层,不肉眼估。\n`+
  `步骤(必须实跑):\n`+
  `1) 把这份头部打分表候选JSON写到 /tmp/full_scan_cands.json:\n${JSON.stringify(candForBuilder)}\n`+
  `2) 跑整合脚本(它对每候选跑timing_signals买入双确认+sizing, 对持仓跑卖出5道门):\n`+
  `   python3 ${SP}/scripts/organism_portfolio_builder.py --candidates /tmp/full_scan_cands.json --regime ${regime} --holdings\n`+
  `   拿到JSON输出(build_list=建仓裁决含action/size_pct/突破%/量价, hold_actions=持仓守/减/清)。\n`+
  `3) 基于脚本输出+深扫one_line, 产出【四块报告】(markdown):\n`+
  `   ①宏观定调(regime=${regime}+sizing系数+关键背离,2-3句)\n`+
  `   ②头部打分表(表格:标的|SABCT|供给侧一句话|量价结构|距突破%|建仓裁决probe/watch/reject|建议仓位%——按probe→watch→reject排,probe在最前)\n`+
  `   ③建仓/调仓逻辑(哪些现价probe建仓+为什么(双确认过)+sizing;哪些watch等回踩+回踩位;持仓守/减/清)\n`+
  `   ④执行情况/执行卡片(每个probe标的:建仓区间/仓位%/止损类型/催化剂日期;若全watch零probe要老实说"缩圈今日无双确认建仓,列回踩清单待触发")\n`+
  `⛔老实:脚本说watch就是watch,别硬凑probe。缩圈零probe是合理结论(sizing0.5+双确认严)。⛔数字来自脚本输出+深扫,不编。返回完整四块报告markdown。`,
  { label:'交易侧整合+四块报告', phase:'Step3-6 交易侧整合(择时双确认+风控5道门+组合构建+四块报告)' })
log('Step3-6完成:交易侧整合+四块报告')

return {
  spec:{ steps:'0宏观/1-18树/2全树深扫头部打分表/3-5交易侧整合(买入双确认+卖出5道门+sizing)/6四块报告', deepscan:toScan.length, regime, note:'价格为扫描时刻盘中/盘后价,非执行价' },
  macro_regime: macro,
  regime,
  step1_trees: step1trees,
  head_score_table: scored,   // 头部打分表(全树深扫SABCT)
  full_report: integ,          // 四块报告(含交易侧整合建仓/调仓计划)
}

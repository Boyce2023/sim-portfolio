// ════════════════════════════════════════════════════════════════
// A股产品树驱动3步扫描 v2 — 把06-24~25所有方法论焊死进系统,一键跑,不再手攒跳步
// ════════════════════════════════════════════════════════════════
// 方法论(全部固化在此文件,不靠记忆):
//  1. 产品树驱动(非40行业券商round-robin): 终端产品→传导链→环节→埋伏点
//  2. 产品溯源语言(⛔禁券商词: 小金属/有色/半导体材料 → 锗光互联/萤石氟链/钨链等)
//  3. 反复质问追到矿(每条链追到源头矿+揭示非共识)
//  4. 废等回调(决策用价值判断不用价格预测,只出probe/reject/hold)
//  5. 有机体: Step3持仓复盘用产业树的眼睛(每只在哪条链/链上发生什么),不机械看X1
//  规格写死防缩水: Step1=18棵产品树 / Step2=每股5维 / Step3=全持仓复盘
export const meta = {
  name: 'astock-v2-product-screening',
  description: 'A股产品树驱动3步扫描: Step1=18棵产品树全市场扫今日全链埋伏点/Step2=埋伏点每股5维废等回调深扫/Step3=产业树持仓复盘。产品溯源语言禁券商词,规格写死防缩水',
  phases: [
    { title: 'Step1-产品树全市场', detail: '18棵产品树扫今日全链异动+埋伏点' },
    { title: 'Step2-埋伏点深扫', detail: '埋伏点每股5维,废等回调' },
    { title: 'Step3-产业树持仓复盘', detail: '每只持仓在产业树的位置+监控' },
  ],
}

// ════ 18棵产品树(终端产品驱动,产品溯源,非券商板块) ════
const TREES = [
  { name: 'AI算力(VR200机架重构)', end: '英伟达Rubin AI服务器,大模型厂商capex 6000亿$', chain: '芯片大脑→造壳耗材(前驱体/特气)→封测包→信号承载层(玻纤布/CCL)→光互联(锗)→液冷→HBM→造芯设备→上游钨矿/石英矿/铜矿' },
  { name: 'AI端侧(AI手机换机)', end: '本地跑AI助手的手机/PC,苹果谷歌端侧竞赛', chain: '整机→端侧SoC→存储(内存翻3倍)→散热(VC铜)→快充电池→硅碳负极(硅烷气)→钼矿/钨矿/工业硅' },
  { name: '人形机器人(替代人力)', end: '特斯拉Optimus/宇树,替越来越贵的人力', chain: '整机Tier1→减速器→丝杠(特纯轴承钢)→灵巧手电机→六维力(铍青铜)→电子皮肤→PEEK(萤石→DFBP)→稀土矿/铬铁矿/铍矿' },
  { name: '电动车(消费者+碳中和)', end: '买车消费者+碳中和国家信用', chain: '整车→三电→SiC功率(衬底/高纯石墨)→驱动电机(钕铁硼+镝铽)→电解液(LiPF6→萤石)→负极(针状焦)→锂矿/重稀土矿' },
  { name: '固态电池', end: '2027装车全固态电池(高端长续航车)', chain: '电解质成品→前驱体(硫源/锆源)→金属锂负极→干法成膜→硫化锂/锆矿' },
  { name: '智能驾驶(Robotaxi)', end: 'L3+/Robotaxi无人车(人放手)', chain: '感知(激光雷达)→域控算力→线控执行→高精定位→座舱' },
  { name: '苹果新形态(折叠+AI眼镜)', end: '折叠iPhone+AI眼镜(两个独立终端)', chain: '折叠:UTG→铰链MIM/液态金属→钛合金; 眼镜:光波导→MicroLED→光学声学' },
  { name: '创新药(MNC专利悬崖扫货)', end: '患者/医保付费+MNC补管线扫中国ADC/双抗', chain: 'Biotech分子→偶联CDMO→高活毒素HPAPI→连接子/培养基/层析微球→石化/海洋源' },
  { name: '脑机/手术机器人', end: '老龄化+精准医疗,脑机/手术机器人商业化', chain: '整机→电极→芯片→高值耗材' },
  { name: 'AI供电(AI吞电→电网扩容)', end: 'AI数据中心耗电暴增逼电网扩容', chain: '机柜配电→海缆送电→输配电材料→变压器(取向硅钢/交期刚性)→铜/铝→铜矿' },
  { name: '制冷剂(配额冻结涨价)', end: '空调/汽车热管理工质,三代制冷剂配额冻结', chain: '工质灌注→配额制冷剂本体→氢氟酸→萤石矿' },
  { name: '钨硬质合金(刀具+军工)', end: '数控刀具(制造业capex)+军工钨件', chain: '刀具成形→钨粉精炼→APT→钨矿(中国83%); ⛔与锗(光互联)无关' },
  { name: '半导体设备国产化', end: 'AI拉HBM→长鑫长存史诗级扩产+制裁强制国产', chain: '扩产现金→刻蚀薄膜→量测→涂胶CMP→零部件→EDA→测试设备' },
  { name: '商业航天/卫星互联网', end: '千帆+星网2.8万颗低轨卫星组网量产元年', chain: '卫星总装→T/R相控阵芯片→星载载荷→火箭入轨→地面终端' },
  { name: '可控核聚变/核电', end: '聚变堆工程化(造堆动作驱动)+核电核准', chain: '主设备总装→真空容器→第一壁/偏滤器→超导磁体→核电主设备' },
  { name: '军工/低空经济', end: 'eVTOL+军贸+导弹补库三终端', chain: '整机壳→机体减重材料→推进动力→弹载连接→机载器件→飞控' },
  { name: '稳定币/金融科技', end: '链上美元搬钱管道+券商科技IPO跟投', chain: '发牌入口→清结算中台→区块链底座→收单跨境支付; 券商IPO浮盈' },
  { name: '猪周期反转', end: '产能去化反身性→出栏肥猪,供给侧驱动', chain: '出栏变现→母猪基因→育肥饲喂→饲料添加→防死动保' },
] // = 18, 规格守卫
if (TREES.length !== 18) throw new Error(`Step1规格违反: ${TREES.length}≠18棵产品树`)

const HELD = (Array.isArray(args) ? args : []).map(t => String(t).split('.')[0])

// ════════ Step1: 18棵产品树全市场扫描(今日全链异动+埋伏点) ════════
phase('Step1-产品树全市场')
log(`Step1: ${TREES.length}棵产品树并行扫今日全链(产品溯源,禁券商词)`)

const TREE_SCHEMA = {
  type: 'object',
  properties: {
    tree: { type: 'string' },
    today_state: { type: 'string', description: '这棵树今天整体: 哪个环节在炒(涨停)、哪个退潮、主线位置' },
    hot_envs: { type: 'string', description: '今天正在炒的环节(hot)+涨停标的——这些已炒透,Step2不深扫' },
    ambush: {
      type: 'array', description: '埋伏环节: 产品刚需但今天/近期没炒透的环节',
      items: {
        type: 'object',
        properties: {
          ticker: { type: 'string' }, name: { type: 'string' },
          env: { type: 'string', description: '产品逻辑环节名(禁券商词)' },
          why_ambush: { type: 'string', description: '为什么是埋伏点(产品刚需+没炒透+追到的矿/非共识)' },
        },
        required: ['ticker', 'name', 'env'],
      },
    },
  },
  required: ['tree', 'today_state', 'ambush'],
}

const step1raw = await parallel(TREES.map(t => () =>
  agent(
    `扫描A股【${t.name}】这棵产品树今天的全链。终端产品=${t.end}。传导链=${t.chain}\n` +
    `①今天这棵树整体什么状态: 哪个环节在炒(涨停)、哪个退潮、主线位置(启动/主升/尾声)?\n` +
    `②hot环节(今天正在炒的+涨停标的): 这些已炒透,标出但不进埋伏池。\n` +
    `③⭐埋伏环节(给Step2深扫的): 这棵树上产品刚需、但今天/近5-10日没炒透的环节,每个给ticker+name+产品逻辑环节名+为什么埋伏(追到它的矿/非共识)。⛔每棵树至少挖2-3个埋伏点。\n` +
    `⛔产品溯源语言,严禁券商板块词(小金属/有色/半导体材料/电子)——用产品逻辑名(锗光互联材料/萤石氟链/钨链/取向硅钢/SiC衬底)。\n` +
    `⛔A股数据用astock_data_layer(scripts/)或akshare新浪源(ak.stock_zh_a_daily),禁import yfinance。WebSearch搜今天异动。禁子agent。快速失败3-4分钟返回。结论先行。`,
    { schema: TREE_SCHEMA, label: t.name.slice(0, 14), phase: 'Step1-产品树全市场' }
  )
)).then(rs => rs.filter(Boolean))

// 汇总所有树的埋伏点,去重+排持仓
const allAmbush = step1raw.flatMap(t => (t.ambush || []).map(a => ({ ...a, tree: t.tree })))
const seen = new Set()
const ambushPool = allAmbush.filter(a => {
  const k = String(a.ticker || '').split('.')[0]
  if (!k || seen.has(k) || HELD.includes(k)) return false
  seen.add(k); return true
})
log(`Step1完成: 18棵树挖出${allAmbush.length}个埋伏点, 去重排持仓后${ambushPool.length}个进Step2深扫`)

// ════════ Step2: 埋伏点每股5维深扫(废等回调) ════════
phase('Step2-埋伏点深扫')
log(`Step2: ${ambushPool.length}个埋伏点 × 5维 = ${ambushPool.length * 5}个agent-pass`)

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    decision: { type: 'string', enum: ['probe', 'reject', 'hold'], description: 'probe=现价小仓进/reject=不买/hold。⛔无watch等回调(无信息优势必失效)' },
    sabct: { type: 'string' },
    size_now: { type: 'string', description: '现价建多少仓(%或0)。⛔禁写"等回调到XX",只答现价建多少' },
    stop: { type: 'string' }, exit: { type: 'string' }, catalyst_date: { type: 'string' },
    one_line: { type: 'string', description: '为什么现价进/不进(炒没炒透+值不值得押注,不是价格高低)' },
  },
  required: ['decision', 'sabct', 'size_now', 'one_line'],
}
const D = (c) => `【${c.name} ${c.ticker}】产品树=${c.tree}/环节=${c.env}。埋伏:${c.why_ambush || ''}。⛔产品溯源语言。A股数据astock_data_layer/akshare新浪源禁yfinance。禁子agent。快速失败3分钟。`

const step2results = await pipeline(
  ambushPool,
  (c) => agent(`${D(c)}\n①供给侧Edge: 物理/制度壁垒? 终端产品真刚需还是概念蹭? 中国吃到份额吗? 追到上游矿/物理约束。`, { label: `Edge:${c.name}`, phase: 'Step2-埋伏点深扫' }),
  (edge, c) => agent(`${D(c)}\n②Kill Shot: 今天没炒是真埋伏(逻辑到情绪没到)还是硬伤(份额假/暴雷/概念蹭)? 专搜负面。\n供给侧:${String(edge).slice(0, 600)}`, { label: `Kill:${c.name}`, phase: 'Step2-埋伏点深扫' }),
  (kill, c) => agent(`${D(c)}\n③定价: 现价+PEG+前瞻PE。⛔看近5-10日累计涨幅(雅克教训:今天没涨≠没炒透)。是没炒透埋伏还是已涨一波?`, { label: `Price:${c.name}`, phase: 'Step2-埋伏点深扫' }),
  (price, c) => agent(`${D(c)}\n④催化: 产品传导到这环要多久被资金挖到? 具体催化+日期?`, { label: `Cat:${c.name}`, phase: 'Step2-埋伏点深扫' }),
  (cat, c) => agent(`${D(c)}\n⑤现价裁决: ⛔严禁"等回调"(无信息优势=赌没edge方向必失效,memory/feedback_no_wait_pullback.md)。第一问"现价值不值得押注": 没炒透非共识埋伏→probe现价小仓5-8%; 已炒透(涨停/抛物线)→reject不是等回调; 软→reject。size_now禁写等回调。SABCT(A-门槛)+止损-12%+催化日期。结论先行。`, { schema: VERDICT_SCHEMA, label: `裁决:${c.name}`, phase: 'Step2-埋伏点深扫' })
)
const step2final = step2results.map((v, i) => ({ ...ambushPool[i], verdict: v })).filter(x => x.verdict)
const probes = step2final.filter(x => x.verdict.decision === 'probe')
log(`Step2完成: ${step2final.length}埋伏点裁决, 🟢现价可进${probes.length}`)

// ════════ Step3: 产业树持仓复盘(有机体监控) ════════
phase('Step3-产业树持仓复盘')
log(`Step3: 持仓复盘——每只在产业树的位置+监控(用产业树的眼睛,不机械看X1)`)

const HOLD_SCHEMA = {
  type: 'object',
  properties: {
    ticker: { type: 'string' }, name: { type: 'string' },
    tree_position: { type: 'string', description: '这只持仓在哪条产业树的哪个环节' },
    chain_health: { type: 'string', description: '它所在的链今天/近期发生什么(整条链健康还是某环走弱)' },
    action: { type: 'string', enum: ['hold', 'reduce', 'add', 'exit'], description: '基于产业树判断的动作' },
    one_line: { type: 'string', description: '产业树视角一句话: 守/减/加/清的理由' },
  },
  required: ['ticker', 'name', 'tree_position', 'action', 'one_line'],
}

const holdReview = await agent(
  `读取 /Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json 的 a_share 持仓,对每只持仓做【产业树视角复盘】(有机体监控,不机械看X1):\n` +
  `①这只在哪条产业树的哪个环节(如紫金=铜=AI供电+电车+电网三树命门;德赛=AI端侧快充)\n` +
  `②它所在的链今天/近期发生什么(整条链健康?某环走弱?如有色铜链连崩3天)\n` +
  `③基于产业树判断动作: 守/减/加/清。X1破线要看是单日噪音还是趋势走弱(连续多日)。\n` +
  `用astock_data_layer取现价(禁yfinance),逐只输出。这是有机体监控的核心——用产业树的眼睛看持仓。`,
  { label: '持仓产业树复盘', phase: 'Step3-产业树持仓复盘' }
)

return {
  spec: { step1_trees: TREES.length, step2_ambush: ambushPool.length, step2_dims: 5 },
  step1_trees: step1raw,
  ambush_deepscan: step2final,
  probes,
  holdings_review: holdReview,
}

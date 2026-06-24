// A股三步筛股报告 — 规格写死在代码,物理防缩水(spec_fidelity的代码化执法)
// ⛔ 唯一合法的筛股入口。禁止主脑手动派agent扫描(手动派的每一步都是自由裁量=缩水温床)。
// 背景: spec_fidelity放memory(软约束)反复被本能盖过缩水(40agent→5/数据层),
//       2026-06-18定: 硬规格写进代码,像portfolio_io/health_check/verify_isolation那样物理拦截。

export const meta = {
  name: 'astock-screening',
  description: 'A股三步筛股报告(规格写死防缩水): Step1=40 agent全行业Track A基本面(Track B由数据层), Step2=Top10-20标的×5决策维度。任何缩水在代码校验处直接throw。',
  phases: [
    { title: 'Step1-全行业扫描', detail: '40 agent 覆盖全行业基本面(Track A)' },
    { title: 'Step2-决策深扫', detail: 'Top10-20标的 × 5决策维度' },
  ],
}

// ════════ 规格守卫(硬编码,不可在编排内缩水) ════════
const STEP1_UNITS = [
  '半导体-存储', '半导体-AI算力/CPU/GPU', '半导体-设备', '半导体-材料/零部件', '半导体-模拟/功率/射频',
  '消费电子/组装', '光通信-光模块/器件/芯片', 'PCB/覆铜板', '被动元件/电子陶瓷', '面板/LED/光学',
  '通信设备/运营商', '计算机/AI软件/算力租赁', '传媒/游戏/AIGC', '电力设备/光伏', '风电/海缆',
  '储能/锂电池', '电网/特高压', '机械设备/工业母机', '人形机器人/减速器', '军工/航空航天',
  '汽车整车/新能源车', '汽车零部件', '钢铁', '有色-工业金属(铜铝)', '有色-小金属/稀土/钨/锑',
  '煤炭', '石油石化/油服', '基础化工/化工材料', '化学制品/农化', '医药-创新药',
  '医药-CXO/器械/中药', '食品饮料/白酒', '农林牧渔', '家电', '纺织服装/轻工',
  '银行', '非银金融/券商', '房地产/物业', '建筑/建材/水泥', '公用事业/环保/交运',
] // = 40

const STEP2_DIMS = ['供给侧Edge', 'Kill Shot', '定价检验price-in', '催化剂锁定', '建仓裁决'] // = 5
const STEP2_MIN = 10, STEP2_MAX = 20

// ⛔ 物理校验: 缩水=立即抛错,workflow拒绝启动
if (STEP1_UNITS.length !== 40) throw new Error(`Step1规格违反: ${STEP1_UNITS.length}≠40 agent`)
if (STEP2_DIMS.length !== 5) throw new Error(`Step2规格违反: ${STEP2_DIMS.length}≠5 决策维度`)

// ════════ Step1: 40 agent 全行业 Track A 基本面 (Track B 由数据层在主脑侧已扫) ════════
phase('Step1-全行业扫描')
log(`Step1: ${STEP1_UNITS.length}个行业agent并行 (规格=40,代码守卫已通过)`)

const CAND_SCHEMA = {
  type: 'object',
  properties: {
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          ticker: { type: 'string' }, name: { type: 'string' }, sector: { type: 'string' },
          track_a: { type: 'string', description: '基本面/供给侧/催化剂一句话' },
          track_b: { type: 'string', description: '资金/涨幅/涨停信号一句话' },
          why: { type: 'string', description: '为什么值得Step2深看' },
        },
        required: ['ticker', 'name', 'why'],
      },
    },
  },
  required: ['candidates'],
}

const step1raw = await parallel(STEP1_UNITS.map((unit, i) => () =>
  agent(
    `扫描A股【${unit}】板块,找今天值得买方深看的候选标的。\n` +
    `Track A(基本面/供给侧,核心): 这个板块谁有物理/制度供给约束、产能瓶颈、定价权? 有无涨价函/停单/政策催化? 近期基本面或订单变化?\n` +
    `Track B(资金): 板块今日及近5-10日涨跌、有无涨停龙头、资金流向。\n` +
    `⛔A股数据一律用 astock_data_layer(/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/) 或 akshare的 ak.stock_zh_a_daily(新浪源),禁import yfinance(A股市值少算10倍)。WebSearch搜2026定性催化剂。\n` +
    `⛔快速失败(防卡死,06-22加): WebSearch最多2次、单个数据命令失败最多重试1次,取不到就用已有信息或返回空candidates,绝不在一个工具上反复死磕,3-4分钟内必须返回。\n` +
    `返回2-5个候选,每个: ticker+name+track_a一句+track_b一句+why一句。没有亮点的板块可返回空candidates(不硬凑)。\n` +
    `⛔严格禁止派生任何子agent。`,
    { schema: CAND_SCHEMA, label: `扫:${unit}`, phase: 'Step1-全行业扫描' }
  )
)).then(rs => rs.filter(Boolean))

const allCand = step1raw.flatMap(r => r.candidates || [])
// 去重(同ticker保留首个)
const seen = new Set()
const deduped = allCand.filter(c => { const k = c.ticker; if (!k || seen.has(k)) return false; seen.add(k); return true })
// 排除持仓(args传入,非持仓报告;取6位code匹配,兼容.SH/.SZ后缀)
const HELD = (Array.isArray(args) ? args : []).map(t => String(t).split('.')[0])
const fresh = deduped.filter(c => !HELD.includes(String(c.ticker).split('.')[0]))
log(`Step1完成: 40行业返回${allCand.length}候选, 去重${deduped.length}, 排除持仓${deduped.length - fresh.length} → ${fresh.length}个非持仓候选`)

// Top10-20: 行业轮转(round-robin)选择 — 防前几个行业(半导体5细分按数组顺序)霸榜、把今天异动的非半导体板块挤出Step2深扫
// 原bug: fresh.slice(0,20)按STEP1_UNITS顺序取前20→半导体霸榜→医药/券商/有色等异动板块进不了Step2=连续0买根因(06-24修)
// 修法: 按行业分组(去重+排持仓,保持Step1顺序)→每轮各行业各取1个→填满STEP2_MAX或候选耗尽,保证板块覆盖广度
const picked = new Set()
const bySector = step1raw.map(r => (r.candidates || []).filter(c => {
  const k = String(c.ticker || '').split('.')[0]
  if (!k || picked.has(k) || HELD.includes(k)) return false
  picked.add(k); return true
}))
const topN = []
for (let round = 0, added = true; added && topN.length < STEP2_MAX; round++) {
  added = false
  for (const sc of bySector) {
    if (round < sc.length) { topN.push(sc[round]); added = true; if (topN.length >= STEP2_MAX) break }
  }
}
if (topN.length < STEP2_MIN) log(`⚠️ 候选仅${topN.length}个(<${STEP2_MIN}),Step1覆盖或行情清淡,继续但标注`)
log(`Step2选取: 行业轮转${topN.length}个(覆盖${new Set(topN.map(c => c.sector || c.ticker)).size}个不同板块,防半导体霸榜挤出异动板块)`)

// ════════ Step2: Top10-20标的 × 5决策维度 (pipeline,每标的独立走完5维) ════════
phase('Step2-决策深扫')
log(`Step2: Top${topN.length}标的 × ${STEP2_DIMS.length}决策维度 (规格=Top10-20×5,共${topN.length * 5}个agent-pass)`)

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    decision: { type: 'string', enum: ['buy', 'watch', 'reject'] },
    sabct: { type: 'string' }, tier: { type: 'string' },
    entry: { type: 'string' }, stop: { type: 'string' }, size: { type: 'string' },
    exit: { type: 'string' }, catalyst_date: { type: 'string' },
    one_line: { type: 'string', description: '一句话裁决理由' },
  },
  required: ['decision', 'sabct', 'one_line'],
}

const D = (c) => `【${c.name} ${c.ticker}】(${c.sector || ''})。A股数据用astock_data_layer/akshare新浪源,⛔禁yfinance。⛔禁子agent。⛔快速失败:WebSearch≤2次/数据命令失败≤1次重试,取不到用已有信息,绝不死磕,3分钟内返回。`

const results = await pipeline(
  topN,
  (c) => agent(`${D(c)}\n决策维度①供给侧Edge: 别人给不了什么? 物理/制度壁垒? 谁有定价权? 优势能维持多久?`, { label: `Edge:${c.name}`, phase: 'Step2-决策深扫' }),
  (edge, c) => agent(`${D(c)}\n决策维度②Kill Shot: 什么能一票否决这个标的? 专搜负面(份额假/估值透支/催化证伪/周期顶)。\n供给侧分析参考: ${String(edge).slice(0, 600)}`, { label: `Kill:${c.name}`, phase: 'Step2-决策深扫' }),
  (kill, c) => agent(`${D(c)}\n决策维度③定价检验: 现价+PEG(G标来源)+前瞻PE(26E/27E,爬坡股用季度斜率)。已涨多少? price in到哪了? 市场已知什么、我看到什么非共识?`, { label: `Price:${c.name}`, phase: 'Step2-决策深扫' }),
  (price, c) => agent(`${D(c)}\n决策维度④催化剂锁定: 何时能证明判断对? 具体事件+具体日期。不兑现怎么办? 主题位置(启动/主升早/台阶/尾声)?`, { label: `Cat:${c.name}`, phase: 'Step2-决策深扫' }),
  (cat, c) => agent(`${D(c)}\n决策维度⑤建仓裁决(综合前4维): 买/观察/不买。SABCT评级(A-是建仓最低门槛)+Tier仓位。给执行卡片: 建仓价/止损(-12%)/仓位/出场条件(不是目标价,是"催化剂过+什么信号")/催化剂日期。结论先行。`, { schema: VERDICT_SCHEMA, label: `裁决:${c.name}`, phase: 'Step2-决策深扫' })
)

// 附回标的信息
const final = results.map((v, i) => ({ ...topN[i], verdict: v })).filter(x => x.verdict)
const buys = final.filter(x => x.verdict.decision === 'buy')
log(`Step2完成: ${final.length}标的裁决, 🟢能买${buys.length}个`)

return {
  spec_check: { step1_agents: STEP1_UNITS.length, step2_stocks: topN.length, step2_dims: STEP2_DIMS.length },
  candidates_total: deduped.length,
  decisions: final,
  buys,
}

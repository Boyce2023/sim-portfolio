// 主线驱动深扫 — 输入标的清单(主脑用主线词典选出),每股5维深扫,返回建仓裁决
// 与astock_screening的区别: 不做Step1的40行业round-robin盲扫,标的由主脑"宏观+主线"判断选出
// 背景: 06-24用户定方法论——主线由大产品源头驱动(Vera Rubin/Optimus...),选标的要主线驱动不是板块平权

export const meta = {
  name: 'astock-deepscan',
  description: '主线驱动深扫: args传入标的清单,每股5维深扫(供给侧Edge/KillShot/定价/催化/裁决),返回建仓裁决+执行卡片。标的由主脑主线判断选出,非round-robin',
  phases: [{ title: '5维深扫', detail: '每股5 agent决策深扫' }],
}

const stocks = Array.isArray(args) ? args : []
if (!stocks.length) throw new Error('deepscan需要标的清单: args=[{ticker,name,sector,mainline,layer}]')
const STEP2_DIMS = 5

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

const D = (c) => `【${c.name} ${c.ticker}】(${c.sector || ''})${c.mainline ? ', 主线=' + c.mainline + (c.layer ? '/传导层=' + c.layer : '') : ''}。A股数据用astock_data_layer(scripts/)或akshare新浪源(ak.stock_zh_a_daily),⛔禁import yfinance(A股市值少算10倍)。⛔禁子agent。⛔快速失败:WebSearch≤2次/数据命令失败≤1次重试,取不到用已有信息,3分钟内返回。`

phase('5维深扫')
log(`主线驱动深扫: ${stocks.length}个标的 × ${STEP2_DIMS}维 = ${stocks.length * 5}个agent-pass`)

const results = await pipeline(
  stocks,
  (c) => agent(`${D(c)}\n决策维度①供给侧Edge: 别人给不了什么? 物理/制度壁垒? 谁有定价权? 优势维持多久? 在主线传导链里它是哪一层(大硬件/小硬件材料/矿)、这层炒透了没?`, { label: `Edge:${c.name}`, phase: '5维深扫' }),
  (edge, c) => agent(`${D(c)}\n决策维度②Kill Shot: 什么能一票否决? 专搜负面(份额假/估值透支/催化证伪/周期顶/概念蹭非真受益)。\n供给侧参考: ${String(edge).slice(0, 600)}`, { label: `Kill:${c.name}`, phase: '5维深扫' }),
  (kill, c) => agent(`${D(c)}\n决策维度③定价检验: 现价+PEG(G标来源)+前瞻PE(26E/27E,爬坡股用季度斜率)。已涨多少? price in到哪? 在主线里是已炒透的层还是没炒到的埋伏层?`, { label: `Price:${c.name}`, phase: '5维深扫' }),
  (price, c) => agent(`${D(c)}\n决策维度④催化剂锁定: 何时能证明判断对? 具体事件+日期? 不兑现怎么办? 主线传导位置(启动/主升早/主升中/台阶/尾声)?`, { label: `Cat:${c.name}`, phase: '5维深扫' }),
  (cat, c) => agent(`${D(c)}\n决策维度⑤建仓裁决(综合前4维): 买/观察/不买。SABCT评级(A-是建仓最低门槛)+Tier仓位。执行卡片: 建仓价/止损(-12%)/仓位/出场条件(不是目标价,是"催化剂过+什么信号")/催化剂日期。结论先行。`, { schema: VERDICT_SCHEMA, label: `裁决:${c.name}`, phase: '5维深扫' })
)

const final = results.map((v, i) => ({ ...stocks[i], verdict: v })).filter(x => x.verdict)
const buys = final.filter(x => x.verdict.decision === 'buy')
log(`深扫完成: ${final.length}标的裁决, 🟢能买${buys.length}个`)

return { count: final.length, decisions: final, buys }

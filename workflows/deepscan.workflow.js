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

// ⛔06-25思想铁律: 删掉"watch等回调"。决策用价值判断不用价格预测,只剩现价决策。详见 memory/feedback_no_wait_pullback.md
const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    decision: { type: 'string', enum: ['probe', 'reject', 'hold'], description: 'probe=现价小仓进/reject=不买/hold=已持仓持有。⛔无"watch等回调"——那是预测价格,无信息优势必失效' },
    sabct: { type: 'string' },
    size_now: { type: 'string', description: '现价建多少仓(%或0=不建)。⛔禁止写"等回调到XX"——只答现价建多少' },
    stop: { type: 'string', description: '止损-12%' },
    exit: { type: 'string', description: '出场条件(催化剂过+什么信号,不是目标价)' },
    catalyst_date: { type: 'string' },
    one_line: { type: 'string', description: '一句话: 为什么现价就进/不进(基于炒没炒透+值不值得押注,不是基于价格高低)' },
  },
  required: ['decision', 'sabct', 'size_now', 'one_line'],
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
  (cat, c) => agent(`${D(c)}\n决策维度⑤现价裁决(综合前4维): ⛔只回答"以现价值不值得押一注"——严禁"等回调到XX"(那是预测价格,无信息优势必失效,详见memory/feedback_no_wait_pullback.md)。\n决策第一问: 现价这笔风险收益值不值得押注?\n- 没炒透的非共识埋伏点→probe现价小仓5-8%占位(它没涨,等=等它被发现后涨上去=踏空)\n- 已炒透共识(涨停板/抛物线顶)→reject,不是等回调(你不知道它会不会回调,等回调是假装你知道)\n- thesis软→reject\nSABCT(A-最低门槛)。执行卡片: 现价建多少仓(size_now,禁写"等回调")/止损-12%/出场(催化剂过+什么信号)/催化剂日期。结论先行。`, { schema: VERDICT_SCHEMA, label: `裁决:${c.name}`, phase: '5维深扫' })
)

const final = results.map((v, i) => ({ ...stocks[i], verdict: v })).filter(x => x.verdict)
const probes = final.filter(x => x.verdict.decision === 'probe')
log(`深扫完成: ${final.length}标的裁决, 🟢现价可进${probes.length}个`)

return { count: final.length, decisions: final, probes }

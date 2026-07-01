// 实盘全面复盘 — 40标的judge准确性校准 + 三类错误归因 + 优化建议
// 2026-07-01用户令:复盘实盘5-18至今所有交易/调仓/错过,按①必然会犯②不该犯③策略缺陷 分类,校准每股信心
export const meta = {
  name: 'replay-audit',
  description: '实盘全面复盘:40标的我的判断vs实际涨跌+基本面/timing对错+三类错误归因(必然/不该/策略缺陷)+信心校准表+优化建议',
  phases: [{title:'A-标的级复盘'},{title:'B-错过专项'},{title:'C-归因校准优化'}],
}

const STOCK_SCHEMA = {type:'object',properties:{
  stocks:{type:'array',items:{type:'object',properties:{
    ticker:{type:'string'}, name:{type:'string'},
    my_view:{type:'string',description:'我当时的评级+thesis+买卖/reject判断'},
    actual:{type:'string',description:'实际:建仓/卖出后到现在的涨跌幅%+盈亏'},
    fundamental_ok:{type:'string',description:'基本面判断对没对(thesis兑现没)+一句话'},
    timing_ok:{type:'string',description:'timing判断对没对(买卖/调仓时机)+一句话'},
    error_class:{type:'string',enum:['判断正确','必然会犯(策略本质局限)','不该犯(纪律执行错)','策略缺陷'],description:'错误三分类'},
    confidence_calib:{type:'string',description:'信心校准建议:这只我一贯判准/判错→信心该升/降/维持'},
    lesson:{type:'string'}
  },required:['ticker','error_class','fundamental_ok','timing_ok']}}
}, required:['stocks']}

const DATA = `⛔数据源(东财已修复):脚本开头必写 import os;os.environ['NO_PROXY']='*' 再import akshare(绕代理软件劫持);拉历史涨跌用ak.stock_zh_a_hist(东财,已通)或腾讯qt.gtimg.cn(现价)。⛔所有网络请求timeout=8。⛔禁子agent。研究笔记在 ~/claude-projects/sim-portfolio/research-notes/astock-database/{代码}_{名}.md。`

// ==== Phase A: 14组标的级复盘 ====
phase('A-标的级复盘')
log('Phase A: 14组×~3标的,复盘我的判断vs实际涨跌')
const A = await parallel(Array.from({length:14},(_,i)=>i+1).map(g=>()=>agent(
  `复盘 /tmp/replay/group_${g}.json 里每个标的(含它的所有买卖交易:action/价格px/日期date/盈亏pnl/reason)。对每个标的:\n`+
  `①读它的交易记录(我买卖了几次/价格/reason里我当时的thesis和评级)+research-notes研究笔记(我给的SABCT评级+thesis)。\n`+
  `②拉它从首次交易日到今天(2026-07-01)的实际涨跌幅%(ak.stock_zh_a_hist)。\n`+
  `③判断:my_view(我当时评级+thesis+买/卖/reject)、actual(实际涨跌+盈亏)、fundamental_ok(基本面thesis对没对)、timing_ok(买卖/调仓时机对没对)。\n`+
  `④error_class三分类:判断正确/必然会犯(策略本质局限如无择时edge)/不该犯(纪律执行错如恐慌清仓/误杀/复权算错)/策略缺陷。\n`+
  `⑤confidence_calib:这只我一贯判准还是判错→信心该升/降/维持。\n`+DATA,
  {schema:STOCK_SCHEMA,label:`复盘组${g}`,phase:'A-标的级复盘'}))).then(r=>r.filter(Boolean))

// ==== Phase B: 6个错过/调仓专项 ====
phase('B-错过专项')
const specials=[
  ['卖飞','卖出后大涨的标的(如顺络6/15逆势涨被当礼物出场/巨化恐慌清仓)——卖了之后涨了多少,该不该卖'],
  ['误杀','扫描reject/watch后却大涨的(如安集之前被死锁误杀)——reject后涨了多少'],
  ['踏空','judge过看好但没建仓的好票,后续涨了多少=踏空成本'],
  ['调仓错误','加减仓/换仓时机:加仓后跌/减仓后涨/换仓换错的案例'],
  ['恐慌清仓','板块崩/破X1时清仓,后续反弹错过的(如巨化06-18清06-22涨停)'],
  ['建仓亏损','建仓后亏损的,是thesis错还是timing错还是策略问题'],
]
log('Phase B: 6专项(卖飞/误杀/踏空/调仓/恐慌清/建仓亏)')
const B = await parallel(specials.map(([k,desc])=>()=>agent(
  `专项复盘【${k}】:${desc}。从 audit-trail/*.json(所有交易) + /tmp/replay/*.json + research-notes 里找这类案例,拉实际涨跌验证,归因(为什么犯,属①必然会犯②不该犯③策略缺陷哪类),给可执行的避免规则。\n`+DATA,
  {label:`专项:${k}`,phase:'B-错过专项'}))).then(r=>r.filter(Boolean))

// ==== 主脚本汇总A ====
const allStocks=A.flatMap(x=>x.stocks||[])
const byClass={}
for(const s of allStocks){const c=s.error_class||'?';byClass[c]=(byClass[c]||0)+1}
log(`Phase A完成:${allStocks.length}标的复盘,错误分类:${JSON.stringify(byClass)}`)

// ==== Phase C: 归因+信心校准+优化(3 agent,读A+B结果) ====
phase('C-归因校准优化')
const aJson=JSON.stringify(allStocks).slice(0,18000)
const bJson=JSON.stringify(B).slice(0,12000)
const C = await parallel([
  ()=>agent(`基于全部标的复盘结果,产出【信心校准表】:每只股(或每类股)我一贯判准还是判错,信心该升/降/维持,给出可操作的"特定股票信心调整清单"。数据:\nA标的复盘=${aJson}`,{label:'信心校准表',phase:'C-归因校准优化'}),
  ()=>agent(`基于复盘,产出【三类错误归因报告】:①必然会犯(策略本质局限)有哪些-接受并对冲②不该犯(纪律执行错)有哪些-立即消除的规则③策略缺陷有哪些-要升级什么。每类给具体案例+统计+根因。数据:\nA=${aJson}\nB专项=${bJson}`,{label:'三类错误归因',phase:'C-归因校准优化'}),
  ()=>agent(`基于复盘,产出【系统优化建议】:交易策略/筛选/调仓/风控 该怎么改进,按优先级排,每条绑实盘证据。数据:\nA=${aJson}\nB=${bJson}\n错误分类分布=${JSON.stringify(byClass)}`,{label:'优化建议',phase:'C-归因校准优化'}),
]).then(r=>r.filter(Boolean))

return {spec:{stocks_reviewed:allStocks.length,error_class_dist:byClass,specials:B.length},
  stock_reviews:allStocks, specials:B, calibration:C[0], error_attribution:C[1], optimization:C[2]}

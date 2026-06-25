// 埋伏点深扫批2 — 废等回调(probe/reject/hold),自动生成
export const meta = { name: 'deepscan-batch2', description: '埋伏点深扫批2: 13股×5维废等回调', phases: [{ title: '批2深扫' }] }
const stocks = [{"ticker": "688029", "name": "南微医学", "env": "微创介入高值耗材(导管/支架/可", "tree": "脑机/手术机器人产品树("}, {"ticker": "688521", "name": "芯原股份", "env": "脑电采集/神经信号处理ASIC(", "tree": "脑机/手术机器人产品树("}, {"ticker": "002901", "name": "大博医疗", "env": "可植入高值耗材平台(电极/植入件", "tree": "脑机/手术机器人产品树("}, {"ticker": "000657", "name": "中钨高新", "env": "六氟化钨链最上游·钨精矿自给(端", "tree": "AI端侧(AI手机/PC"}, {"ticker": "300684", "name": "中石科技", "env": "端侧VC均热板散热·铜毛细吸液芯", "tree": "AI端侧(AI手机/PC"}, {"ticker": "603938", "name": "三孚股份", "env": "硅碳负极·硅烷气(SiH4)·端", "tree": "AI端侧(AI手机/PC"}, {"ticker": "601137", "name": "博威合金", "env": "六维力传感器铍青铜弹性体", "tree": "人形机器人(替代人力)树"}, {"ticker": "688102", "name": "斯瑞新材", "env": "六维力/灵巧手铜基精密合金+CT", "tree": "人形机器人(替代人力)树"}, {"ticker": "002221", "name": "东华能源", "env": "PEEK轻量化萤石氟链(丙烷→P", "tree": "人形机器人(替代人力)树"}, {"ticker": "688308", "name": "欧科亿", "env": "数控刀片成形(硬质合金刀具终端·", "tree": "钨硬质合金树(终端=数控"}, {"ticker": "688059", "name": "华锐精密", "env": "数控刀片成形(国产替代纯标的·钨", "tree": "钨硬质合金树(终端=数控"}, {"ticker": "688257", "name": "新锐股份", "env": "硬质合金工具+矿用钎具(钨深加工", "tree": "钨硬质合金树(终端=数控"}, {"ticker": "002297", "name": "博云新材", "env": "硬质合金+军工钨件/碳基复合材料", "tree": "钨硬质合金树(终端=数控"}]
const VERDICT_SCHEMA = { type:'object', properties:{ decision:{type:'string',enum:['probe','reject','hold']}, sabct:{type:'string'}, size_now:{type:'string',description:'现价建多少仓,禁写等回调'}, stop:{type:'string'}, exit:{type:'string'}, catalyst_date:{type:'string'}, one_line:{type:'string'} }, required:['decision','sabct','size_now','one_line'] }
const D = (c) => `【${c.name} ${c.ticker}】产品树=${c.tree}/环节=${c.env}。⛔产品溯源语言。A股数据astock_data_layer/akshare新浪源禁yfinance。禁子agent。⛔快速失败:任何工具调用≤2次,2分钟内必返回,卡住就用已有信息返回。`
phase('批2深扫')
log(`批2: ${stocks.length}股×5维`)
const results = await pipeline(stocks,
  (c)=>agent(`${D(c)}\n①供给侧Edge:壁垒?真刚需还是概念蹭?追到矿。`,{label:`E:${c.name}`,phase:'批2深扫'}),
  (e,c)=>agent(`${D(c)}\n②KillShot:今天没炒是真埋伏还是硬伤?专搜负面。\n${String(e).slice(0,500)}`,{label:`K:${c.name}`,phase:'批2深扫'}),
  (k,c)=>agent(`${D(c)}\n③定价:现价+PEG+近5-10日累计涨幅(雅克教训)。没炒透还是已涨一波?`,{label:`P:${c.name}`,phase:'批2深扫'}),
  (p,c)=>agent(`${D(c)}\n④催化:何时被资金挖到?具体日期?`,{label:`C:${c.name}`,phase:'批2深扫'}),
  (ct,c)=>agent(`${D(c)}\n⑤现价裁决:⛔严禁等回调(无信息优势必失效)。没炒透埋伏→probe现价5-8%;已炒透→reject;软→reject。size_now禁写等回调。SABCT(A-门槛)+止损-12%。结论先行。`,{schema:VERDICT_SCHEMA,label:`裁:${c.name}`,phase:'批2深扫'})
)
const final=results.map((v,i)=>({...stocks[i],verdict:v})).filter(x=>x.verdict)
log(`批2完成:${final.length}裁决,probe${final.filter(x=>x.verdict.decision==='probe').length}`)
return { batch:2, decisions:final }

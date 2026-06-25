// 埋伏点深扫批4 — 废等回调(probe/reject/hold),自动生成
export const meta = { name: 'deepscan-batch4', description: '埋伏点深扫批4: 13股×5维废等回调', phases: [{ title: '批4深扫' }] }
const stocks = [{"ticker": "300034", "name": "钢研高纳", "env": "机体减重材料-粉末/铸造高温合金", "tree": "军工/低空经济树 — 三"}, {"ticker": "000833", "name": "粤桂股份", "env": "硫精矿→硫化锂源头(硫源溯源)", "tree": "固态电池产品树(终端=2"}, {"ticker": "002741", "name": "光华科技", "env": "硫化锂(Li2S)6N纯化环节(", "tree": "固态电池产品树(终端=2"}, {"ticker": "600206", "name": "有研新材", "env": "高纯硫化锂量产环节(硫化物电解质", "tree": "固态电池产品树(终端=2"}, {"ticker": "301662", "name": "宏工科技", "env": "干法电极前端混料/纤维化设备(干", "tree": "固态电池产品树(终端=2"}, {"ticker": "688131", "name": "皓元医药", "env": "ADC连接子-毒素payload", "tree": "创新药/MNC专利悬崖扫"}, {"ticker": "688293", "name": "奥浦迈", "env": "生物药培养基层(细胞培养基国产替", "tree": "创新药/MNC专利悬崖扫"}, {"ticker": "688108", "name": "纳微科技", "env": "下游纯化层析微球层(色谱填料国产", "tree": "创新药/MNC专利悬崖扫"}, {"ticker": "300725", "name": "药石科技", "env": "高活毒素HPAPI层(OEB5高", "tree": "创新药/MNC专利悬崖扫"}, {"ticker": "688375", "name": "国博电子", "env": "星载相控阵T/R组件(载荷价值量", "tree": "商业航天/卫星互联网产品"}, {"ticker": "002046", "name": "国机精工", "env": "火箭/星载精密锻件·特种合金结构", "tree": "商业航天/卫星互联网产品"}, {"ticker": "002025", "name": "航天电器", "env": "星上连接器·线束(贯穿全链每星必", "tree": "商业航天/卫星互联网产品"}, {"ticker": "605020", "name": "永和股份", "env": "配额制冷剂本体·一体化弹性标(萤", "tree": "制冷剂(配额冻结涨价)产"}]
const VERDICT_SCHEMA = { type:'object', properties:{ decision:{type:'string',enum:['probe','reject','hold']}, sabct:{type:'string'}, size_now:{type:'string',description:'现价建多少仓,禁写等回调'}, stop:{type:'string'}, exit:{type:'string'}, catalyst_date:{type:'string'}, one_line:{type:'string'} }, required:['decision','sabct','size_now','one_line'] }
const D = (c) => `【${c.name} ${c.ticker}】产品树=${c.tree}/环节=${c.env}。⛔产品溯源语言。A股数据astock_data_layer/akshare新浪源禁yfinance。禁子agent。⛔快速失败:任何工具调用≤2次,2分钟内必返回,卡住就用已有信息返回。`
phase('批4深扫')
log(`批4: ${stocks.length}股×5维`)
const results = await pipeline(stocks,
  (c)=>agent(`${D(c)}\n①供给侧Edge:壁垒?真刚需还是概念蹭?追到矿。`,{label:`E:${c.name}`,phase:'批4深扫'}),
  (e,c)=>agent(`${D(c)}\n②KillShot:今天没炒是真埋伏还是硬伤?专搜负面。\n${String(e).slice(0,500)}`,{label:`K:${c.name}`,phase:'批4深扫'}),
  (k,c)=>agent(`${D(c)}\n③定价:现价+PEG+近5-10日累计涨幅(雅克教训)。没炒透还是已涨一波?`,{label:`P:${c.name}`,phase:'批4深扫'}),
  (p,c)=>agent(`${D(c)}\n④催化:何时被资金挖到?具体日期?`,{label:`C:${c.name}`,phase:'批4深扫'}),
  (ct,c)=>agent(`${D(c)}\n⑤现价裁决:⛔严禁等回调(无信息优势必失效)。没炒透埋伏→probe现价5-8%;已炒透→reject;软→reject。size_now禁写等回调。SABCT(A-门槛)+止损-12%。结论先行。`,{schema:VERDICT_SCHEMA,label:`裁:${c.name}`,phase:'批4深扫'})
)
const final=results.map((v,i)=>({...stocks[i],verdict:v})).filter(x=>x.verdict)
log(`批4完成:${final.length}裁决,probe${final.filter(x=>x.verdict.decision==='probe').length}`)
return { batch:4, decisions:final }

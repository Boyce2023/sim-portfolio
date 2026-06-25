// 埋伏点深扫批5 — 废等回调(probe/reject/hold),自动生成
export const meta = { name: 'deepscan-batch5', description: '埋伏点深扫批5: 12股×5维废等回调', phases: [{ title: '批5深扫' }] }
const stocks = [{"ticker": "002126", "name": "银轮股份", "env": "工质灌注/热管理端(车用热管理总", "tree": "制冷剂(配额冻结涨价)产"}, {"ticker": "002915", "name": "中欣氟材", "env": "含氟精细化学品端(本体延伸的含氟", "tree": "制冷剂(配额冻结涨价)产"}, {"ticker": "600195", "name": "中牧股份", "env": "防死动保-猪用生物疫苗(口蹄疫/", "tree": "猪周期反转树 = 产能去"}, {"ticker": "603566", "name": "普莱柯", "env": "防死动保-基因工程疫苗+猪用化药", "tree": "猪周期反转树 = 产能去"}, {"ticker": "002311", "name": "海大集团", "env": "育肥饲喂-饲料添加+教槽料(降本", "tree": "猪周期反转树 = 产能去"}, {"ticker": "000998", "name": "隆平高科", "env": "母猪基因/上游种源(及饲料粮种源", "tree": "猪周期反转树 = 产能去"}, {"ticker": "000969", "name": "安泰科技", "env": "第一壁/偏滤器-钨铜难熔金属(直", "tree": "可控核聚变/核电产品树。"}, {"ticker": "300435", "name": "中泰股份", "env": "杜瓦/深冷低温系统(超导磁体必须", "tree": "可控核聚变/核电产品树。"}, {"ticker": "300627", "name": "华测导航", "env": "高精定位-GNSS+IMU惯导冗", "tree": "智能驾驶/Robotax"}, {"ticker": "603197", "name": "保隆科技", "env": "感知-4D成像毫米波雷达", "tree": "智能驾驶/Robotax"}, {"ticker": "688326", "name": "经纬恒润-W", "env": "域控算力-智驾域控制器集成", "tree": "智能驾驶/Robotax"}, {"ticker": "002906", "name": "华阳集团", "env": "智能座舱-座舱域控+HUD", "tree": "智能驾驶/Robotax"}]
const VERDICT_SCHEMA = { type:'object', properties:{ decision:{type:'string',enum:['probe','reject','hold']}, sabct:{type:'string'}, size_now:{type:'string',description:'现价建多少仓,禁写等回调'}, stop:{type:'string'}, exit:{type:'string'}, catalyst_date:{type:'string'}, one_line:{type:'string'} }, required:['decision','sabct','size_now','one_line'] }
const D = (c) => `【${c.name} ${c.ticker}】产品树=${c.tree}/环节=${c.env}。⛔产品溯源语言。A股数据astock_data_layer/akshare新浪源禁yfinance。禁子agent。⛔快速失败:任何工具调用≤2次,2分钟内必返回,卡住就用已有信息返回。`
phase('批5深扫')
log(`批5: ${stocks.length}股×5维`)
const results = await pipeline(stocks,
  (c)=>agent(`${D(c)}\n①供给侧Edge:壁垒?真刚需还是概念蹭?追到矿。`,{label:`E:${c.name}`,phase:'批5深扫'}),
  (e,c)=>agent(`${D(c)}\n②KillShot:今天没炒是真埋伏还是硬伤?专搜负面。\n${String(e).slice(0,500)}`,{label:`K:${c.name}`,phase:'批5深扫'}),
  (k,c)=>agent(`${D(c)}\n③定价:现价+PEG+近5-10日累计涨幅(雅克教训)。没炒透还是已涨一波?`,{label:`P:${c.name}`,phase:'批5深扫'}),
  (p,c)=>agent(`${D(c)}\n④催化:何时被资金挖到?具体日期?`,{label:`C:${c.name}`,phase:'批5深扫'}),
  (ct,c)=>agent(`${D(c)}\n⑤现价裁决:⛔严禁等回调(无信息优势必失效)。没炒透埋伏→probe现价5-8%;已炒透→reject;软→reject。size_now禁写等回调。SABCT(A-门槛)+止损-12%。结论先行。`,{schema:VERDICT_SCHEMA,label:`裁:${c.name}`,phase:'批5深扫'})
)
const final=results.map((v,i)=>({...stocks[i],verdict:v})).filter(x=>x.verdict)
log(`批5完成:${final.length}裁决,probe${final.filter(x=>x.verdict.decision==='probe').length}`)
return { batch:5, decisions:final }

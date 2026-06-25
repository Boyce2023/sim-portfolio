// 埋伏点深扫批3 — 废等回调(probe/reject/hold),自动生成
export const meta = { name: 'deepscan-batch3', description: '埋伏点深扫批3: 13股×5维废等回调', phases: [{ title: '批3深扫' }] }
const stocks = [{"ticker": "603191", "name": "望变电气", "env": "取向硅钢-AIDC电源变压器铁芯", "tree": "【AI算力·VR200机"}, {"ticker": "002409", "name": "雅克科技", "env": "HBM前驱体-存储造壳耗材链", "tree": "【AI算力·VR200机"}, {"ticker": "603688", "name": "石英股份", "env": "高纯石英矿-晶圆坩埚/光纤预制棒", "tree": "【AI算力·VR200机"}, {"ticker": "300706", "name": "阿石创", "env": "溅射靶材-芯片/HBM金属化镀膜", "tree": "【AI算力·VR200机"}, {"ticker": "688190", "name": "云路股份", "env": "高频变压器纳米晶/非晶磁芯(固态", "tree": "AI供电树(AI数据中心"}, {"ticker": "600114", "name": "东睦股份", "env": "高频磁粉芯/软磁复合材料(数据中", "tree": "AI供电树(AI数据中心"}, {"ticker": "300263", "name": "隆华科技", "env": "镀膜金属基材-钼靶/钨靶国产替代", "tree": "半导体设备国产化树（产品"}, {"ticker": "688361", "name": "中科飞测", "env": "良率之眼-前道量测/缺陷检测（国", "tree": "半导体设备国产化树（产品"}, {"ticker": "300054", "name": "鼎龙股份", "env": "平坦化耗材-CMP抛光垫国产突破", "tree": "半导体设备国产化树（产品"}, {"ticker": "688019", "name": "安集科技", "env": "平坦化耗材-CMP抛光液+功能性", "tree": "半导体设备国产化树（产品"}, {"ticker": "688122", "name": "西部超导", "env": "机体减重材料-高温合金/钛合金(", "tree": "军工/低空经济树 — 三"}, {"ticker": "300699", "name": "光威复材", "env": "机体减重材料-碳纤维(eVTOL", "tree": "军工/低空经济树 — 三"}, {"ticker": "600893", "name": "航发动力", "env": "推进动力-航空发动机整机(军贸战", "tree": "军工/低空经济树 — 三"}]
const VERDICT_SCHEMA = { type:'object', properties:{ decision:{type:'string',enum:['probe','reject','hold']}, sabct:{type:'string'}, size_now:{type:'string',description:'现价建多少仓,禁写等回调'}, stop:{type:'string'}, exit:{type:'string'}, catalyst_date:{type:'string'}, one_line:{type:'string'} }, required:['decision','sabct','size_now','one_line'] }
const D = (c) => `【${c.name} ${c.ticker}】产品树=${c.tree}/环节=${c.env}。⛔产品溯源语言。A股数据astock_data_layer/akshare新浪源禁yfinance。禁子agent。⛔快速失败:任何工具调用≤2次,2分钟内必返回,卡住就用已有信息返回。`
phase('批3深扫')
log(`批3: ${stocks.length}股×5维`)
const results = await pipeline(stocks,
  (c)=>agent(`${D(c)}\n①供给侧Edge:壁垒?真刚需还是概念蹭?追到矿。`,{label:`E:${c.name}`,phase:'批3深扫'}),
  (e,c)=>agent(`${D(c)}\n②KillShot:今天没炒是真埋伏还是硬伤?专搜负面。\n${String(e).slice(0,500)}`,{label:`K:${c.name}`,phase:'批3深扫'}),
  (k,c)=>agent(`${D(c)}\n③定价:现价+PEG+近5-10日累计涨幅(雅克教训)。没炒透还是已涨一波?`,{label:`P:${c.name}`,phase:'批3深扫'}),
  (p,c)=>agent(`${D(c)}\n④催化:何时被资金挖到?具体日期?`,{label:`C:${c.name}`,phase:'批3深扫'}),
  (ct,c)=>agent(`${D(c)}\n⑤现价裁决:⛔严禁等回调(无信息优势必失效)。没炒透埋伏→probe现价5-8%;已炒透→reject;软→reject。size_now禁写等回调。SABCT(A-门槛)+止损-12%。结论先行。`,{schema:VERDICT_SCHEMA,label:`裁:${c.name}`,phase:'批3深扫'})
)
const final=results.map((v,i)=>({...stocks[i],verdict:v})).filter(x=>x.verdict)
log(`批3完成:${final.length}裁决,probe${final.filter(x=>x.verdict.decision==='probe').length}`)
return { batch:3, decisions:final }

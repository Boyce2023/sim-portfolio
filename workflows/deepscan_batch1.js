// 埋伏点深扫批1 — 废等回调(probe/reject/hold),自动生成
export const meta = { name: 'deepscan-batch1', description: '埋伏点深扫批1: 13股×5维废等回调', phases: [{ title: '批1深扫' }] }
const stocks = [{"ticker": "300377", "name": "赢时胜", "env": "清结算中台-基金托管登记清算引擎", "tree": "稳定币/金融科技树 (终"}, {"ticker": "600446", "name": "金证股份", "env": "清结算中台-券商核心交易清算系统", "tree": "稳定币/金融科技树 (终"}, {"ticker": "300674", "name": "宇信科技", "env": "发牌入口后端-银行跨境清算/反洗", "tree": "稳定币/金融科技树 (终"}, {"ticker": "601881", "name": "中国银河", "env": "券商IPO跟投浮盈-经纪两融+投", "tree": "稳定币/金融科技树 (终"}, {"ticker": "600505", "name": "金石资源", "env": "萤石氟链上游矿(喂给LiPF6的", "tree": "电动车产品树(终端=买车"}, {"ticker": "002407", "name": "多氟多", "env": "六氟磷酸锂氟链中游(把萤石氟做成", "tree": "电动车产品树(终端=买车"}, {"ticker": "600111", "name": "北方稀土", "env": "重稀土镝铽磁链(喂给EV驱动电机", "tree": "电动车产品树(终端=买车"}, {"ticker": "600516", "name": "方大炭素", "env": "SiC长晶高纯石墨耗材(喂给Si", "tree": "电动车产品树(终端=买车"}, {"ticker": "300331", "name": "苏大维格", "env": "AI眼镜-光波导/纳米压印母版(", "tree": "苹果新形态产品树(两个独"}, {"ticker": "688127", "name": "蓝特光学", "env": "AI眼镜-精密光学棱镜/合光准直", "tree": "苹果新形态产品树(两个独"}, {"ticker": "603327", "name": "福蓉科技", "env": "折叠iPhone-钛合金/7系铝", "tree": "苹果新形态产品树(两个独"}, {"ticker": "688210", "name": "统联精密", "env": "折叠iPhone-MIM铰链精密", "tree": "苹果新形态产品树(两个独"}, {"ticker": "688617", "name": "惠泰医疗", "env": "电生理标测导管+颅内介入电极(B", "tree": "脑机/手术机器人产品树("}]
const VERDICT_SCHEMA = { type:'object', properties:{ decision:{type:'string',enum:['probe','reject','hold']}, sabct:{type:'string'}, size_now:{type:'string',description:'现价建多少仓,禁写等回调'}, stop:{type:'string'}, exit:{type:'string'}, catalyst_date:{type:'string'}, one_line:{type:'string'} }, required:['decision','sabct','size_now','one_line'] }
const D = (c) => `【${c.name} ${c.ticker}】产品树=${c.tree}/环节=${c.env}。⛔产品溯源语言。A股数据astock_data_layer/akshare新浪源禁yfinance。禁子agent。⛔快速失败:任何工具调用≤2次,2分钟内必返回,卡住就用已有信息返回。`
phase('批1深扫')
log(`批1: ${stocks.length}股×5维`)
const results = await pipeline(stocks,
  (c)=>agent(`${D(c)}\n①供给侧Edge:壁垒?真刚需还是概念蹭?追到矿。`,{label:`E:${c.name}`,phase:'批1深扫'}),
  (e,c)=>agent(`${D(c)}\n②KillShot:今天没炒是真埋伏还是硬伤?专搜负面。\n${String(e).slice(0,500)}`,{label:`K:${c.name}`,phase:'批1深扫'}),
  (k,c)=>agent(`${D(c)}\n③定价:现价+PEG+近5-10日累计涨幅(雅克教训)。没炒透还是已涨一波?`,{label:`P:${c.name}`,phase:'批1深扫'}),
  (p,c)=>agent(`${D(c)}\n④催化:何时被资金挖到?具体日期?`,{label:`C:${c.name}`,phase:'批1深扫'}),
  (ct,c)=>agent(`${D(c)}\n⑤现价裁决:⛔严禁等回调(无信息优势必失效)。没炒透埋伏→probe现价5-8%;已炒透→reject;软→reject。size_now禁写等回调。SABCT(A-门槛)+止损-12%。结论先行。`,{schema:VERDICT_SCHEMA,label:`裁:${c.name}`,phase:'批1深扫'})
)
const final=results.map((v,i)=>({...stocks[i],verdict:v})).filter(x=>x.verdict)
log(`批1完成:${final.length}裁决,probe${final.filter(x=>x.verdict.decision==='probe').length}`)
return { batch:1, decisions:final }

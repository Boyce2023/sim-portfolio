// A股产品树驱动3步扫描 v3 — rate limit根治版(每标的1agent走完5维)+退潮树过滤
// 06-26: v2的Step2是5维pipeline(=320agent rate limit隐患),v3改单agent(64agent降5倍)+只深扫主升树
export const meta = {
  name:'astock-v3-screening',
  description:'产品树驱动3步: Step1=18树全市场/Step2=主升树埋伏点每标的1agent走完5维(废等回调)/Step3=产业树持仓复盘。rate limit根治+产品溯源',
  phases:[{title:'Step1-18树全市场'},{title:'Step2-埋伏点深扫'},{title:'Step3-持仓复盘'}],
}
const TREES = [
  { name:'AI算力(VR200机架重构)', end:'英伟达Rubin AI服务器,大模型厂商capex', chain:'芯片大脑→造壳耗材→封测包→玻纤布/CCL→光互联(锗)→液冷→HBM→设备→钨矿/石英矿/铜矿' },
  { name:'AI端侧(AI手机换机)', end:'本地AI助手手机/PC', chain:'整机→端侧SoC→存储→散热(VC铜)→快充→硅碳负极(硅烷气)→钼矿/钨矿' },
  { name:'人形机器人(替代人力)', end:'特斯拉Optimus/宇树', chain:'整机→减速器→丝杠(轴承钢)→电机→六维力(铍青铜)→电子皮肤→PEEK(萤石→DFBP)→稀土矿' },
  { name:'电动车(消费者+碳中和)', end:'买车消费者+碳中和', chain:'整车→三电→SiC(衬底/石墨)→电机(钕铁硼+镝铽)→电解液(LiPF6→萤石)→负极(针状焦)→锂矿/稀土矿' },
  { name:'固态电池', end:'2027装车全固态', chain:'电解质→前驱体(硫源/锆源)→金属锂负极→干法成膜→硫化锂/锆矿' },
  { name:'智能驾驶(Robotaxi)', end:'L3+/Robotaxi无人车', chain:'激光雷达→域控→线控→高精定位→座舱' },
  { name:'苹果新形态(折叠+AI眼镜)', end:'折叠iPhone+AI眼镜', chain:'UTG→铰链MIM→钛合金;光波导→MicroLED' },
  { name:'创新药(MNC扫货)', end:'ADC/双抗被MNC扫货', chain:'分子→偶联CDMO→毒素HPAPI→连接子/培养基/层析微球' },
  { name:'脑机/手术机器人', end:'脑机+手术机器人商业化', chain:'整机→电极→芯片→高值耗材' },
  { name:'AI供电(电网扩容)', end:'AI数据中心吞电', chain:'配电→海缆→输配电材料→变压器(取向硅钢)→铜/铝→铜矿' },
  { name:'制冷剂(配额涨价)', end:'空调/汽车热管理', chain:'工质→配额制冷剂→氢氟酸→萤石矿' },
  { name:'钨硬质合金(刀具+军工)', end:'数控刀具+军工钨', chain:'刀具→钨粉→APT→钨矿; 与锗无关' },
  { name:'半导体设备国产化', end:'长鑫长存扩产', chain:'扩产现金→刻蚀薄膜→量测→CMP→零部件→EDA→测试设备' },
  { name:'商业航天/卫星互联网', end:'千帆星网组网', chain:'卫星总装→T/R芯片→载荷→火箭→地面终端' },
  { name:'可控核聚变/核电', end:'聚变堆工程化+核电', chain:'主设备→真空容器→第一壁→超导磁体→核电主设备' },
  { name:'军工/低空经济', end:'eVTOL+军贸+导弹补库', chain:'整机→机体材料→推进→弹载连接→机载器件→飞控' },
  { name:'稳定币/金融科技', end:'链上美元+券商IPO跟投', chain:'发牌→清结算→区块链→收单跨境; 券商IPO' },
  { name:'猪周期反转', end:'产能去化→出栏', chain:'出栏→母猪→育肥→饲料添加→动保' },
]
if(TREES.length!==18) throw new Error(`Step1规格违反:${TREES.length}!=18`)
const HELD=(Array.isArray(args)?args:[]).map(t=>String(t).split('.')[0])

// ==== Step1: 18树全市场扫今日全链+埋伏点 ====
phase('Step1-18树全市场')
log(`Step1: 18棵产品树并行扫今日全链(产品溯源禁券商词)`)
const TREE_SCHEMA={type:'object',properties:{tree:{type:'string'},today_state:{type:'string',description:'今天整体:哪环在炒/退潮/主线位置(启动/主升早/主升中/台阶/尾声/退潮/未启动)'},is_hot:{type:'boolean',description:'这棵树今天是否在主升/启动(true=值得深扫埋伏点,false=退潮/尾声/未启动跳过)'},ambush:{type:'array',items:{type:'object',properties:{ticker:{type:'string'},name:{type:'string'},env:{type:'string'},why_ambush:{type:'string'}},required:['ticker','name','env']}}},required:['tree','today_state','is_hot','ambush']}
const step1=await parallel(TREES.map(t=>()=>agent(
  `扫描A股【${t.name}】产品树今天全链。终端=${t.end}。链=${t.chain}\n`+
  `①今天整体状态:哪环在炒(涨停)/哪环退潮/主线位置?②is_hot:这树今天在主升/启动吗(退潮/尾声/未启动=false)?③埋伏环节(产品刚需但今天没炒透的):每个ticker+name+产品逻辑环节名+为什么埋伏(追到矿)。至少2-3个。\n`+
  `⛔产品溯源语言禁券商词(小金属/有色/半导体材料→锗光互联/萤石氟链/钨链)。\n⛔A股数据铁律(今日东财_em接口被代理挡会超时重试拖死!):只用这4源——①from scripts.astock_data_layer import get_full_market,get_limit_up_stocks(全市场5868只快照+涨停池274只,含涨跌幅/市值/换手)②腾讯qt.gtimg.cn批量(urllib直连,q=sh600519,sz300308,涨跌幅=行.split('~')[32])③ak.stock_zh_a_daily(symbol='sh600519')新浪源日线。⛔严禁任何ak.*_em/stock_board_*_em/stock_zh_a_spot_em东财接口、禁yfinance、禁重试东财(失败立即换上述源,绝不重试_em)。WebSearch搜今天异动定性。禁子agent。快速失败:工具≤2次,3分钟必返回。`,
  {schema:TREE_SCHEMA,label:t.name.slice(0,12),phase:'Step1-18树全市场'}))).then(r=>r.filter(Boolean))

// 过滤:只留主升树(is_hot)的埋伏点+去重排持仓
const seen=new Set()
const pool=step1.filter(t=>t.is_hot).flatMap(t=>(t.ambush||[]).map(a=>({...a,tree:t.tree}))).filter(a=>{const k=String(a.ticker||'').split('.')[0];if(!k||seen.has(k)||HELD.includes(k))return false;seen.add(k);return true})
const hotTrees=step1.filter(t=>t.is_hot).length
log(`Step1完成:18树,${hotTrees}棵主升,过滤退潮树后${pool.length}个埋伏点进Step2`)

// ==== Step2: 每标的1agent走完5维(rate limit根治)+废等回调 ====
phase('Step2-埋伏点深扫')
log(`Step2:${pool.length}个埋伏点·每标的1agent走完5维·cap16排队不rate limit`)
const VERDICT={type:'object',properties:{decision:{type:'string',enum:['probe','reject','hold']},sabct:{type:'string'},size_now:{type:'string',description:'现价建多少仓,禁等回调'},stop:{type:'string'},catalyst_date:{type:'string'},one_line:{type:'string'}},required:['decision','sabct','size_now','one_line']}
const step2=await parallel(pool.map(c=>()=>agent(
  `深扫【${c.name} ${c.ticker}】产品树=${c.tree}/环节=${c.env}。走完5维给裁决:\n`+
  `①供给侧Edge:壁垒?真刚需还是概念蹭?中国份额?追到上游矿。②KillShot:今天没炒是真埋伏还是硬伤(份额假/暴雷/概念蹭)?搜负面。③定价:现价+PEG+近5-10日累计涨幅(雅克教训:今天没涨≠没炒透)。没炒透还是已涨一波?④催化:何时被资金挖到?日期?⑤现价裁决:严禁等回调(无信息优势必失效)。没炒透埋伏=probe现价5到8仓;已炒透(涨停/抛物线)=reject;软=reject。size_now禁写等回调。SABCT(A-门槛)+止损-12pct。结论先行。\n`+
  `产品溯源语言。⛔A股数据(今日东财_em被代理挡会重试拖死!):只用①腾讯qt.gtimg.cn批量(urllib直连,涨跌幅=split('~')[32],现价=[3])②ak.stock_zh_a_daily新浪源日线③astock_data_layer.get_full_market。⛔禁任何ak.*_em东财接口/禁yfinance/禁重试东财(失败立即换源)。禁子agent。快速失败:工具≤2次,2分钟必返回。`,
  {schema:VERDICT,label:c.name,phase:'Step2-埋伏点深扫'}))).then(r=>r.filter(Boolean))
const final=step2.map((v,i)=>({...pool[i],verdict:v})).filter(x=>x.verdict)
const probes=final.filter(x=>x.verdict.decision==='probe')
log(`Step2完成:${final.length}裁决,probe${probes.length}`)

// ==== Step3: 产业树持仓复盘 ====
phase('Step3-持仓复盘')
const hold=await agent(
  `读 /Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json 的a_share持仓,每只做产业树视角复盘(有机体监控不机械看X1):①在哪条产业树哪环(查memory/knowledge_product_tree_method.md命门图)②所在链今天发生什么(整链健康?某环走弱?连续多日?)③守/减/加/清(X1破线看单日噪音还是趋势走弱)。⛔取现价只用腾讯qt.gtimg.cn(urllib直连,q=sh600519,现价=split('~')[3],涨跌幅=[32])或astock_data_layer,⛔禁东财_em接口/禁yfinance/禁重试东财。逐只输出。`,
  {label:'持仓产业树复盘',phase:'Step3-持仓复盘'})

return {spec:{step1_trees:18,hot_trees:hotTrees,step2_ambush:pool.length},step1_trees:step1,ambush_deepscan:final,probes,holdings_review:hold}

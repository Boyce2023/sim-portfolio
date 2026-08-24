// A股产品树驱动3步扫描 v3 — rate limit根治版(每标的1agent走完5维)+退潮树过滤
// 06-26: v2的Step2是5维pipeline(=320agent rate limit隐患),v3改单agent(64agent降5倍)+只深扫主升树
export const meta = {
  name:'astock-v3-screening',
  description:'产品树驱动3步: Step1=18树全市场/Step2=主升树埋伏点每标的1agent走完5维(废等回调)/Step3=产业树持仓复盘。rate limit根治+产品溯源',
  phases:[{title:'并行主体(宏观+18树流水线深扫+持仓)'},{title:'Step2.5-历史对照'}],
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
  // ⛔2026-08-24补两棵: 当日资金明确从科技往避险/涨价资源躲(白银有色涨停/上海能源涨停/美锦+9.9%/
  // 融捷二连板),而原18棵树全是AI-科技-新能源导向,物理上看不见贵金属与煤炭——扫描因此报"0个probe",
  // 不是市场没机会,是扫描器没有那个方向的眼睛。这是比任何单条规则更根本的覆盖缺口。
  { name:'贵金属(避险+实际利率下行)', end:'央行购金+避险需求+美债实际利率下行', chain:'金矿/银矿→选冶→精炼→加工首饰/工业用银(光伏银浆)→回收' },
  { name:'煤炭(动力煤+焦煤)', end:'火电需求+钢铁焦化需求+冬储', chain:'煤矿(动力煤/焦煤/无烟煤)→洗选→铁路/港口运输→焦化→电厂/钢厂' },
]
if(TREES.length!==20) throw new Error(`Step1规格违反:${TREES.length}!=20`)
// ticker归一化:去后缀(.SH/.SZ/.SS/.BJ)+去前缀(sh/sz/bj)+去空白 → 纯6位代码(07-02修:柯力603662.SH是持仓却漏进Step2)
const norm=t=>String(t||'').trim().replace(/\.(SH|SZ|SS|BJ)$/i,'').replace(/^(sh|sz|bj)/i,'').trim()
// args 两种形态: ①数组=持仓ticker,扫"当下"(原行为) ②对象{held:[...],date:'YYYY-MM-DD'}=补扫指定交易日
// 2026-08-24加: 用户要"按上周五收盘扫上一个交易日",而原脚本所有prompt写死"今天"+依赖实时快照,
// 在集合竞价阶段跑会得到"数据不足以判断"的空结果(实测18棵树17棵报未开盘,热树8→1,宏观返回null)。
const _A = (args && !Array.isArray(args) && typeof args==='object') ? args : {held:args}
const HELD=(Array.isArray(_A.held)?_A.held:[]).map(norm)
const SCAN_DATE = _A.date || null
const DATE_DIRECTIVE = SCAN_DATE
  ? `\n⛔⛔本次是【补扫历史交易日 ${SCAN_DATE}】,不是扫当下。所有"今天/今日"一律指 ${SCAN_DATE} 当日。\n`+
    `  数据口径: 禁用实时快照(qt.gtimg.cn现价/get_full_market都是当下价,会污染结论)。\n`+
    `  必须用日线: ak.stock_zh_a_daily(symbol='sh600519')新浪源 或 腾讯 web.ifzq.gtimg.cn/appstock/app/fqkline/get\n`+
    `  (param=sh600519,day,${SCAN_DATE},${SCAN_DATE},10,qfq),取该日 收盘/最高/最低/成交量,涨跌幅=该日收盘/前一交易日收盘-1。\n`+
    `  涨停池同理用 ak.stock_zt_pool_em(date='${SCAN_DATE.replace(/-/g,'')}')。WebSearch搜该日新闻须带日期限定。\n`+
    `  ⛔若某数据源只能给当下值拿不到 ${SCAN_DATE} 的,明说"该项拿不到",禁止用当下值冒充。\n`
  : ''

// ==== ⛔单agent失败重试(2026-08-24加): 实测三轮扫描每轮都随机掉2-4个agent,报错均为"API Error: Connection
// lost mid-response",掉的名字不固定。原逻辑失败直接计入failures→只能整轮重跑(代价极大)。改为逐agent失败重试:
// agent()返回null(空结果)或抛错都算失败,重试最多2次(共3次尝试)才真正放弃、计入failures。
// ⛔workflow脚本内Date.now()/Math.random()会抛错(沙盒禁非确定性调用),延迟改用setTimeout固定值(非随机);
// 若沙盒连setTimeout都不支持,吞掉异常直接进下一次重试,不让延迟本身拖垮重试逻辑。
async function _wait(ms){
  try{ await new Promise(resolve=>setTimeout(resolve,ms)) }catch(e){ /* 沙盒不支持定时器就不等,立即重试 */ }
}
async function agentR(prompt,opts,maxAttempts=3){
  let lastErr=null
  for(let i=0;i<maxAttempts;i++){
    try{
      const r=await agent(prompt,opts)
      if(r) return r
      lastErr='agent返回空结果(null)'
    }catch(e){
      lastErr=(e&&e.message)||String(e)
    }
    if(i<maxAttempts-1){
      log(`⚠️agent失败重试[${(opts&&opts.label)||'未命名'}] 第${i+1}/${maxAttempts-1}次重试,上次失败原因:${lastErr}`)
      await _wait(1500)
    }
  }
  log(`⛔agent最终失败[${(opts&&opts.label)||'未命名'}]:已重试${maxAttempts-1}次仍无果,计入failures`)
  return null
}

// ==== Step0: 宏观体检(先水位后主线再个股,2026-07-02补——之前扫描漏了宏观层) ====
phase('并行主体(宏观+18树流水线深扫+持仓)')
log('全并行:Step0宏观+18树流水线(每树扫完立即深扫其埋伏点,不等其他树)+Step3持仓复盘同时跑')
const macroP = agentR(
  DATE_DIRECTIVE+`A股宏观体检(先水位后主线再个股): 判断该交易日市场水位, 为后面主线扫描定调。\n`+
  `⛔第一步先跑 date '+%Y-%m-%d %H:%M' 拿真实体检时刻,写进你输出的macro文本开头(格式如"体检时刻: 2026-07-02 10:30")——报告价格均为此刻盘中价,须标注价格时点。\n`+
  `⛔消息面内部数据优先(D7): 先跑 python3 /Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/news_layer.py 读内部消息面数据(写在/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/news_today.json,若脚本存在;用绝对路径,agent cwd不保证在sim-portfolio),拿到隔夜美股+A股快讯后再针对性WebSearch补充——内部数据优先(D7),没有news_layer或数据超过12小时才全靠WebSearch。\n`+
  `①核心指数近3月/1月/1周(沪深300/中证1000/创业板/科创50) ②全市场市值中位数 vs 指数(揭穿指数失真: 指数涨但中位数跌=缩圈) ③赚钱效应(涨家占比, 收窄=缩圈接近尾声) ④今日板块强弱(资金在哪) ⑤风格(大盘vs小盘/成长vs价值)。\n`+
  `⑥⛔消息面/事件驱动(必做,不只看跌多少要看"为什么跌"): WebSearch搜今天大盘/领涨领跌板块异动的catalyst——隔夜外围美股(费半/纳指/道指)、重大政策事件、龙头公司公告,尤其外围AI/科技传导(如Meta/英伟达/台积电capex或财报信号→A股AI硬件)。知道catalyst才能判断今天大跌是"错杀"(情绪冲击→可低吸)还是"趋势反转"(基本面变坏→该避)。⛔缺这层=知其然不知其所以然,会把宏观级利空误判成板块噪音(2026-07-02教训:Meta卖算力引发全球AI capex担忧、费半-6%传导A股,我只看盘面把它误判成'A股整链噪音')。\n`+
  `⛔regime定调必须锚定多周结构,禁单日breadth拍脑袋(07-10教训): (a)缩圈是否"持续"——中位数vs指数背离要看1周/1月/3月三窗口是否"连续"背离(连续多周背离才是真缩圈;单日背离可能是噪音,不足以定调) (b)赚钱效应看趋势斜率(1周涨家占比 vs 1月 vs 3月,是连续收窄还是刚拐头) (c)板块外溢梯队多周演化(领先龙头是否多周见顶/外溢梯队是否先死=缩圈见顶前兆)。今日涨停分布/单日中位数只是佐证,不是定调依据。\n`+
  `⛔结论必须定调(基于上述多周结构,非单日): 【普涨】(放手做)/【缩圈】(只跟核心龙头+高现金)/【普跌】(防守)? 并明确说明: 这个regime已持续约几周、处于早期/中段/尾声。regime定调直接决定Step2埋伏点激进(普涨)还是保守(缩圈/普跌)+新仓sizing系数(普涨1.0/缩圈0.5/普跌0.3)。\n`+
  `⛔数据禁东财_em(NO_PROXY): 用 from scripts.astock_data_layer import get_full_market,get_limit_up_stocks + 腾讯qt.gtimg.cn拉指数 + ak.stock_zh_a_daily。所有请求timeout=8。禁子agent。参考 scripts/regime_check.py 逻辑。`,
  {model:'claude-sonnet-5',label:'宏观体检-先水位',phase:'并行主体(宏观+18树流水线深扫+持仓)'})
const holdP = agentR(
  DATE_DIRECTIVE+`读 /Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json 的a_share持仓,每只做产业树视角复盘(有机体监控不机械看X1):①在哪条产业树哪环(查memory/knowledge_product_tree_method.md命门图)②所在链今天发生什么(整链健康?某环走弱?连续多日?)③守/减/加/清(X1破线看单日噪音还是趋势走弱)。⛔取现价只用腾讯qt.gtimg.cn(urllib直连,q=sh600519,现价=split('~')[3],涨跌幅=[32])或astock_data_layer,⛔禁东财_em接口/禁yfinance/禁重试东财。逐只输出。`,
  {model:'claude-sonnet-5',label:'持仓产业树复盘',phase:'并行主体(宏观+18树流水线深扫+持仓)'})

// ==== 流水线: 每棵树扫完→立即深扫该树埋伏点(不等其他树) ====
const TREE_SCHEMA={type:'object',properties:{tree:{type:'string'},data_date:{type:'string',description:'⛔本次读数所依据的交易日(YYYY-MM-DD)。补扫历史日必须精确等于DATE_DIRECTIVE指定日期;扫当下则填当天真实交易日(先跑date命令,禁用记忆/训练数据里的日期)。用于跨树核对是否混了交易日'},today_state:{type:'string',description:'今天整体:哪环在炒/退潮/主线位置(启动/主升早/主升中/台阶/尾声/退潮/未启动)'},is_hot:{type:'boolean',description:'这棵树今天是否在主升/启动(true=值得深扫埋伏点,false=退潮/尾声/未启动跳过)'},ambush:{type:'array',items:{type:'object',properties:{ticker:{type:'string'},name:{type:'string'},env:{type:'string'},why_ambush:{type:'string'}},required:['ticker','name','env']}}},required:['tree','data_date','today_state','is_hot','ambush']}
const VERDICT={type:'object',properties:{decision:{type:'string',enum:['probe','watch','reject','hold'],description:'⛔二维裁决:probe=基本面好+主升中(现价进)/watch=基本面好但末段见顶(等回踩,不否定基本面)/reject=基本面差(概念蹭/暴雷/估值无边际,与涨跌无关)/hold=已持仓'},fundamental:{type:'string',description:'基本面轴(定值不值得买):好/差+依据(Edge真假/份额/概念蹭/暴雷/估值安全边际)'},trend:{type:'string',description:'量价轴(定时机):主升中/末段见顶/下跌——看量价结构非涨幅'},sabct:{type:'string'},size_now:{type:'string',description:'现价建多少仓(基本面好+主升中才填实)'},stop:{type:'string'},catalyst_date:{type:'string'},watch_expiry:{type:'string',description:'⛔watch必填三件套(T16不许挂空等回调,江丰踏空+77.7%/北方华创+57%教训):①回踩买点位②失效期5-8交易日③N日未回踩动作(链趋势重启/放量新高→按趋势追;走坏→放弃)。probe/reject可留空'},one_line:{type:'string'}},required:['decision','fundamental','trend','sabct','size_now','one_line']}
const seen=new Set()
const step1trees=[]
const chains=await pipeline(TREES,
  t=>agentR(
  DATE_DIRECTIVE+`扫描A股【${t.name}】产品树该交易日全链。终端=${t.end}。链=${t.chain}\n`+
  `①今天整体状态:哪环在炒(涨停)/哪环退潮/主线位置?②is_hot:这树今天在主升/启动吗(退潮/尾声/未启动=false)?③埋伏环节(产品刚需但今天没炒透的):每个ticker+name+产品逻辑环节名+为什么埋伏(追到矿)。至少2-3个。\n`+
  `④⛔⛔data_date强制标注(2026-08-24加,治混日期——此前同一轮里电动车树用了08-21数据、AI算力树用了08-24数据,混在一起没人发现):在返回JSON的data_date字段精确填写本次读数对应的交易日(YYYY-MM-DD)。`+
  (SCAN_DATE?`本次固定补扫${SCAN_DATE},data_date必须=${SCAN_DATE};若某数据源只给得出别的日期,在today_state文本里明说"该项为XX日数据非${SCAN_DATE}",但data_date字段仍按你结论主体依据的那一天填,不许含糊两可。`:`扫当下:先跑date命令拿真实交易日再填,禁用记忆/训练数据里的日期。`)+`\n`+
  `⛔产品溯源语言禁券商词(小金属/有色/半导体材料→锗光互联/萤石氟链/钨链)。\n⛔A股数据铁律(今日东财_em接口被代理挡会超时重试拖死!):只用这4源——①from scripts.astock_data_layer import get_full_market,get_limit_up_stocks(全市场5868只快照+涨停池274只,含涨跌幅/市值/换手)②腾讯qt.gtimg.cn批量(urllib直连,q=sh600519,sz300308,涨跌幅=行.split('~')[32])③ak.stock_zh_a_daily(symbol='sh600519')新浪源日线。⛔严禁任何ak.*_em/stock_board_*_em/stock_zh_a_spot_em东财接口、禁yfinance、禁重试东财(失败立即换上述源,绝不重试_em)。WebSearch搜今天异动定性。⛔文件纪律:任何临时文件只准写/tmp/,禁止写~/claude-projects根目录/桌面/用户目录;正式产出只准sim-portfolio/output/。禁子agent。快速失败:工具≤2次,3分钟必返回。`,
  {model:'claude-sonnet-5',schema:TREE_SCHEMA,label:t.name.slice(0,12),phase:'并行主体(宏观+18树流水线深扫+持仓)'}),
  (tr,t)=>{
    if(!tr) return {tree:null,verdicts:[]}
    step1trees.push(tr)
    if(!tr.is_hot) return {tree:tr,verdicts:[]}
    const cands=(tr.ambush||[]).map(a=>({...a,tree:tr.tree})).filter(a=>{const k=norm(a.ticker);if(!k||k.length!==6||seen.has(k)||HELD.includes(k))return false;seen.add(k);return true})
    if(!cands.length) return {tree:tr,verdicts:[]}
    return parallel(cands.map(c=>()=>agentR(
  DATE_DIRECTIVE+`深扫【${c.name} ${c.ticker}】产品树=${c.tree}/环节=${c.env}。\n`+
  `⛔⛔二维独立裁决(2026-06-30实盘复盘修正:涨跌永不否决基本面!安集/拓荆/富创/航天电器/西部超导都因"涨过=炒透"被误杀):\n`+
  `【基本面轴·定"值不值得买"】①供给侧Edge:物理/制度壁垒?真刚需还是概念蹭(产品树挂错节点/份额假/非真受益)?中国份额?追到源头矿。②硬伤KillShot:真概念蹭/真基本面暴雷(净利大降且无订单产能前瞻支撑——⚠️AI订单爬坡股trailing PE高≠暴雷)/估值无安全边际(用PEG+前瞻PE判,⛔禁用trailing PE)。③催化:在前还是已兑现。\n`+
  `【量价/趋势轴·定"买入时机"(只对基本面过关的票判)】④区分主升中vs末段见顶:主升中=启动放量/台阶突破/回踩不破/放量上涨(量比≥1.5且涨幅>3%),距首板≤20日(BULL市≤25日);末段见顶=放量滞涨(量比≥2但涨幅<1.5%)/高位巨阴/破启动平台/天量换手见顶/主力连续大额净卖。⛔涨幅大本身不是末段信号!关键看量价结构是"放量上涨"还是"放量滞涨"。\n`+
  `【二维裁决·结论先行】⛔基本面差(真概念蹭/真暴雷/估值无边际)→reject(与涨跌无关);基本面好(Edge真+过A-门槛+catalyst在前)+主升中→probe(现价5-8仓,⛔涨幅不是否决理由,主升中强势龙头就该买,allow足够好);基本面好+末段见顶→watch(等回踩,⛔绝不因涨过否定基本面);thesis软→reject。\n`+
  `⛔watch三道闸(T16,实盘教训江丰等回调踏空+77.7%/北方华创+57%,回调最深仅-0.3%):①watch必须真末段(有硬见顶信号:天量巨阴/放量滞涨/破位),⛔所在链若正主升早段(第二波重启/链内涨停潮),该票的回调很可能是新主升起点,慎判watch宜判probe;②A级+供给侧物理约束(管制/矿/认证)的票原则上不判watch(涨停=建仓信号);③watch必填watch_expiry三件套(回踩位+失效期5-8日+未触发动作),不许挂空等回调;④见顶后回踩买是对的但必须等"真企稳"(07-06全市场1880样本回测:天量巨阴见顶后"缩量回踩企稳买"+5.87%/胜率61% >> "放量收复前高买"+2.11%/42%——收复前高是追高别用)。⛔真企稳三件套缺一不可:跌回见顶价下方≥5% + 缩量(量比<0.7) + 当日收阳,三者齐才触发。中钨/章源亏(-15.7万)不是"见顶后不能买回踩",是我没等真企稳就在高位反弹首日接=假企稳。\n`+
  `⛔死锁铁律:绝不因"涨了X%/价格高/爬坡股PE高"就reject一个基本面好的票——那是用量价轴否决基本面轴的根本错误。基本面定好坏,量价只定时机,两轴独立。size_now现价建多少。SABCT(A-门槛)+止损-12%。\n`+
  `产品溯源语言。⛔A股数据(今日东财_em被代理挡会重试拖死!):只用①腾讯qt.gtimg.cn批量(urllib直连,涨跌幅=split('~')[32],现价=[3])②ak.stock_zh_a_daily新浪源日线③astock_data_layer.get_full_market。⛔禁任何ak.*_em东财接口/禁yfinance/禁重试东财。⛔⛔所有网络请求(urllib.request.urlopen/requests)必须带timeout=8秒!严禁无timeout调用(会TCP卡死拖死整个parallel barrier!),任一源8秒不返回立即换下一源,2次都失败就用WebSearch定性出结果。⛔文件纪律:任何临时文件只准写/tmp/,禁止写~/claude-projects根目录/桌面/用户目录;正式产出只准sim-portfolio/output/。禁子agent。⛔90秒内必须返回裁决,绝不无限等数据。`,
  {model:'claude-sonnet-5',schema:VERDICT,label:c.name,phase:'并行主体(宏观+18树流水线深扫+持仓)'}))).then(vs=>({tree:tr,verdicts:vs.map((v,i)=>({...cands[i],verdict:v})).filter(x=>x.verdict&&!HELD.includes(norm(x.ticker)))}))
  })
const step1=step1trees
// ⛔日期一致性检查(2026-08-24加,治混日期): 逐树核对data_date字段,不一致立刻在日志+返回值里报出来,不埋在正文里
const dateCounts={}
for(const tr of step1trees){ if(tr&&tr.data_date) dateCounts[tr.data_date]=(dateCounts[tr.data_date]||0)+1 }
const dateEntries=Object.entries(dateCounts)
let dateCheck
if(!dateEntries.length){
  dateCheck={status:'no_data',detail:'18个tree-agent均未填data_date字段,无法核对',scan_date_arg:SCAN_DATE}
  log('⚠️日期一致性检查:无agent返回data_date,跳过核对')
}else if(dateEntries.length>1){
  const majority=dateEntries.sort((a,b)=>b[1]-a[1])[0][0]
  const mismatched=step1trees.filter(tr=>tr&&tr.data_date&&tr.data_date!==majority).map(tr=>`${tr.tree}(${tr.data_date})`)
  dateCheck={status:'mismatch',majority_date:majority,mismatched_trees:mismatched,scan_date_arg:SCAN_DATE}
  log(`⛔⛔日期不一致:18棵树出现${dateEntries.length}个不同data_date,多数为${majority},以下树对不上:${mismatched.join('; ')}——本轮结果混了交易日,核实后再用`)
}else{
  const only=dateEntries[0][0]
  const ok=!SCAN_DATE||only===SCAN_DATE
  dateCheck={status:ok?'consistent':'off_target',all_date:only,scan_date_arg:SCAN_DATE}
  log(ok?`日期一致性检查通过:全部树data_date=${only}`:`⛔日期偏离:全部树data_date=${only},与指定补扫日${SCAN_DATE}不符`)
}
const hotTrees=step1.filter(t=>t&&t.is_hot).length
const final=chains.filter(Boolean).flatMap(c=>c.verdicts||[])
const macro=await macroP
const hold=await holdP
log(`并行主体完成:18树/${hotTrees}主升/${final.length}裁决`)
const probes=final.filter(x=>x.verdict.decision==='probe')
const watches=final.filter(x=>x.verdict.decision==='watch')
log(`Step2完成:${final.length}裁决,probe${probes.length}(基本面好+主升中现价进),watch${watches.length}(基本面好+末段等回踩)`)

// ==== Step2.5: 历史对照+裁决入库(07-02补——用户07-01令"选出的股必看自己以前怎么judge的"已定规则却没代码化,今天扫描全漏) ====
phase('Step2.5-历史对照')
const cand=[...probes,...watches].map(x=>`${x.ticker} ${x.name}(本次${x.verdict.decision}:${(x.verdict.one_line||'').slice(0,40)})`).join('; ')
const allVerdicts=final.map(x=>({ticker:norm(x.ticker),name:x.name,decision:x.verdict.decision,one_line:(x.verdict.one_line||'').slice(0,80),watch_expiry:(x.verdict.watch_expiry||'').slice(0,120)}))
const history = cand ? await agentR(
  `历史对照(⛔用户铁律feedback_step2_check_history:选出的股必须先看自己以前怎么judge的,认知连续/反转要解释/调出血泪教训)。本次扫描probe/watch: ${cand}\n`+
  `对每个标的做四查: ①cat /Users/huaichuaibeimeng/claude-projects/sim-portfolio/scan_history.jsonl(历次扫描裁决,每行一条JSON;不存在=无历史) ②grep该代码 research-notes/astock-database/(我的SABCT评级/thesis底稿) ③grep audit-trail/(交易过没/盈亏/卖飞) ④grep ~/.claude/projects/-Users-huaichuaibeimeng-claude-projects/memory/ 下watchlist.md和knowledge_astock_validated_calls.md和feedback_replay_hold_discipline.md(validated成功call/血泪教训/信心校准)。\n`+
  `输出每标的认知演变: 【连续】历史同向→信心增,尤其validated call回归;【反转】历史reject/末段watch→今probe必须解释为什么变(警惕被单日走势骗,二次冲顶?)并降级;【首次】标注无历史对照;【有教训】调出(卖飞/恐慌清/复权口径/违纪建仓)。结论先行。\n`+
  `最后必做: 先跑date '+%Y-%m-%d'拿真实日期,把本次全部裁决逐行append到 /Users/huaichuaibeimeng/claude-projects/sim-portfolio/scan_history.jsonl,每行格式 {"date":"YYYY-MM-DD","ticker":"6位码","name":"...","decision":"probe/watch/reject","one_line":"...","watch_expiry":"回踩位+失效期+未触发动作(watch必有)"} ⛔只append不覆盖(文件不存在则创建),写完wc -l验证行数增加。本次裁决JSON: ${JSON.stringify(allVerdicts)}\n禁子agent。`,
  {model:'claude-sonnet-5',label:'历史对照+裁决入库',phase:'Step2.5-历史对照'}) : '本次无probe/watch,跳过历史对照'
log('Step2.5历史对照完成')


return {spec:{step1_trees:18,hot_trees:hotTrees,step2_ambush:seen.size,scan_time:'见macro_regime文本开头的"体检时刻"(Step0 agent用date命令写入,workflow脚本禁Date.now)',note:'价格为扫描时刻盘中价,非执行价'},macro_regime:macro,date_check:dateCheck,step1_trees:step1,ambush_deepscan:final,probes,watches,history_check:history,holdings_review:hold}

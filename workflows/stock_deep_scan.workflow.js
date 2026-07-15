export const meta = {
  name: 'stock-deep-scan',
  description: '⛔个股判断唯一合法路径:用户给个股→逐只5维SABCT深扫(供给侧/KillShot/定价检验/催化/建仓裁决),禁凭记忆或快速量价简化代替。args=ticker数组',
  phases: [{ title: '5维SABCT深扫' }],
}

// ⛔用法(args不生效): 每次运行前编辑下面TICKERS填入用户给的标的, 再 Workflow({scriptPath:此文件})
const TICKERS = ["688072","300725","000933","000049"].map(t => String(t).replace(/[^0-9]/g,'').slice(0,6)).filter(t => t.length === 6)
if (TICKERS.length === 0) throw new Error('请编辑TICKERS填入6位代码')
log(`强制5维深扫 ${TICKERS.length}只: ${TICKERS.join(',')}`)

const SCHEMA = {
  type:'object',
  properties:{
    ticker:{type:'string'}, name:{type:'string'},
    supply_side:{type:'object', properties:{
      desc:{type:'string', description:'供给侧edge:物理/制度约束、产能瓶颈、认证壁垒、定价权,具体到产品/环节'},
      strength:{type:'string', enum:['强','中','弱','无'], description:'edge真实强度'},
      duration:{type:'string', description:'这个edge能维持多久/护城河深度'}
    }, required:['desc','strength']},
    kill_shot:{type:'object', properties:{
      desc:{type:'string', description:'专搜负面:什么能一票否决(暴雷/份额丢/政策/替代/概念蹭)'},
      is_fatal:{type:'boolean'}
    }, required:['desc','is_fatal']},
    pricing:{type:'object', properties:{
      consensus:{type:'string', description:'市场共识/已知什么'},
      non_consensus:{type:'string', description:'我看到的非共识(或"无非共识")'},
      valuation:{type:'string', description:'PEG/前瞻PE+安全边际(G标来源G1-G4);爬坡股看前瞻不看trailing'}
    }, required:['valuation']},
    catalyst:{type:'object', properties:{
      event:{type:'string'}, date:{type:'string'}, if_not:{type:'string', description:'不兑现怎么办'}
    }, required:['event']},
    bear_downside:{type:'string', description:'bear case + F9分级(T1<15%/T2 15-25%/T3 25-40%/T4>40%排除)+具体downside%'},
    sabct:{type:'string', enum:['A+','A','A-','B+','B'], description:'综合conviction,A-为建仓最低门槛'},
    verdict:{type:'string', enum:['probe建仓','watch等回踩','reject'], description:'基本面轴裁决(与涨跌无关,涨跌永不否决基本面)'},
    position:{type:'string', description:'若probe建议仓位(信心上限×regime),深研仓/追高仓'},
    stop:{type:'string', description:'止损:深研仓=基本面证伪(thesis三问);追高仓=技术线'},
    one_line:{type:'string', description:'一句话结论:值不值得拥有+为什么+现在建还是等'}
  }, required:['ticker','name','supply_side','kill_shot','pricing','sabct','verdict','one_line']
}

phase('5维SABCT深扫')
const results = await parallel(TICKERS.map(t => () =>
  agent(
    `你是东方港湾买方研究员。对A股【${t}】做完整5维SABCT深扫,判断"值不值得拥有"(选股/基本面轴,与今天涨跌无关)。⛔禁偷懒:必须逐维走完,禁凭印象一句话打发。\n`+
    `⛔事实必须搜索验证(D1/宪法): 用WebSearch查该公司最新供给侧/份额/订单/财报/催化/风险,禁凭训练数据编。A股数据禁yfinance,用腾讯qt.gtimg或WebSearch。\n`+
    `五维(缺一不可):\n`+
    `①供给侧Edge: 物理/制度约束、产能瓶颈、认证壁垒、定价权——具体到产品/环节,edge强/中/弱+能维持多久。⛔第一镜片,需求侧故事不算edge。\n`+
    `②Kill Shot: 站对面专搜负面,什么能一票否决(暴雷/份额丢/政策/技术替代/概念蹭挂错节点/估值无边际)。\n`+
    `③定价检验: 市场共识已知什么?我的非共识在哪?估值PEG/前瞻PE(爬坡股看前瞻不看trailing,G标G1-G4来源),安全边际。\n`+
    `④催化剂: 何时能证明我对?具体事件+日期?不兑现怎么办?\n`+
    `⑤建仓裁决: 综合SABCT(A-最低门槛)+基本面轴verdict(probe建仓/watch等回踩/reject,涨跌永不否决基本面:好票主升中=probe,好票末段=watch,基本面差=reject)+仓位+止损类型+bear F9分级downside%。\n`+
    `⛔禁止派生子agent。快速失败:工具≤6次,3-4分钟返回。`,
    {schema:SCHEMA, label:t, phase:'5维SABCT深扫'}
  )
))
return { count: results.filter(Boolean).length, verdicts: results.filter(Boolean) }

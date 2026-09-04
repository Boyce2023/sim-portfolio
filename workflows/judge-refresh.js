export const meta = {
  name: 'us-judge-refresh',
  description: '美股判断层周刷新: 46 agent×5只, 供给侧/现金/催化/熊方四维(价值投资口径)',
  phases: [{ title: '打分', detail: 'sonnet-5, 低effort, 结构化输出' }],
}
const BATCHES = args.batches
const TODAY = args.today        // ⛔日期必须由调用方传入(workflow内new Date()会抛), 写死会污染catalyst维
const LAST_CLOSE = args.last_close
const SCHEMA = {type:'object',properties:{scores:{type:'array',items:{type:'object',properties:{
  ticker:{type:'string'},supply_constraint:{type:'number'},supply_reason:{type:'string'},
  cash_conversion:{type:'number'},cash_reason:{type:'string'},catalyst:{type:'number'},
  catalyst_detail:{type:'string'},bear_severity:{type:'number'},bear_reason:{type:'string'},
  valuation_flag:{type:'string'},valuation_note:{type:'string'},confidence:{type:'string'}},
  required:['ticker','supply_constraint','supply_reason','cash_conversion','cash_reason','catalyst','catalyst_detail','bear_severity','bear_reason','valuation_flag','confidence']}}},required:['scores']}
const RUBRIC = `你是买方PM打分员(价值投资口径)。⛔禁止派生subagent。⛔临时文件只写/tmp/。今天${TODAY},最近收盘${LAST_CLOSE}。
四维: 【supply_constraint 0-10】物理/制度约束与定价权,9-10=不可绕过(矿权/牌照垄断/多年认证/专利+切换成本),0-2=大宗同质化价格接受者。⛔问"谁定价?新进入者多久能供货?",需求好≠约束。
【cash_conversion 0-10】利润是不是真现金。已给实测经营现金流/净利,以它为锚,搜最近季度佐证; 与实测背离要说明。
【catalyst 0-10】9-10=30天内有日期的重大事件,0-2=无或已兑现。detail必须写日期或"无明确日期"。
【bear_severity 0-10,10最重】站对面找证伪。
【valuation_flag】clean/distorted(低基数失真: TTM被一次性项目压低)/unusable(EPS为负)。⛔卖方consensus与目标价不进估值链,能搜到公司自身指引(G1)写进note。
数字必须来自搜索到的公告/财报,搜不到标confidence=low,绝不编。`
phase('打分')
const results = await parallel(BATCHES.map((b) => () =>
  agent(`${RUBRIC}\n\n给下面5只逐只打分:\n\n${b.block}\n\n返回JSON,scores含全部5只。`,
    { label: `judge:${b.tickers.join(',')}`, phase: '打分', schema: SCHEMA, model: 'claude-sonnet-5', effort: 'low' }
  ).catch(() => null)))
const flat = []
for (const r of results) if (r && Array.isArray(r.scores)) flat.push(...r.scores)
log(`完成 ${flat.length} 条`)
return { scores: flat }

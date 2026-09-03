export const meta = {
  name: 'xuangu-fundamentals-read',
  description: '10个agent各读8-9只股的最新研报+最新earnings call, 出每只股基本面初识',
  phases: [{ title: 'Read', detail: '每agent 8-9只股, 每只写 /tmp/us_track/fund/<T>.md' }],
}
const batches = args.batches
const OUT = '/tmp/us_track/fund'
const results = await parallel(batches.map((b, i) => () => agent(
`你是买方研究助理。⛔禁止派生任何subagent。⛔只准写 ${OUT}/ 下的文件, 其他地方一律不写。⛔不联网, 只读本地文件。
任务: 对下面 ${b.length} 只股票, 每只读两类本地文件后写一份"基本面初识", 写到 ${OUT}/<TICKER>.md (每只一个文件, 写完一只再读下一只, 防止中途丢)。
读法(控制篇幅, 每个文件用 Read 工具带 limit): 研报txt 读前 220 行(高盛报告首页摘要+关键表), earnings call txt 读前 180 行(管理层陈述部分)。文件不存在就跳过并在md里注明"无研报"/"无call"。
每只股的 md 固定格式(中文, 口语化不书面, 数字必须来自所读文件并注明来自研报还是call):
# <TICKER> <公司名>
- 干什么的: 一两句大白话(卖什么产品给谁, 靠什么赚钱)
- 所在链条位置: (类别: <cat>) 上游/下游是谁, 主要对手
- 最近一季关键数字: 营收/增速/毛利率/指引 (来自哪份文件, 财季)
- 现在的核心争论: 多头讲什么故事, 空头担心什么 (各一句)
- 增长驱动与最大风险: 各一条
- 高盛评级/目标价: 只记录不评价(标"卖方观点")
- 我的一句话判断: 这生意好不好, 现在处在周期什么位置(标"初步")
清单(ticker | 类别 | 现有一句话说明 | 研报txt路径 | 最新call路径):
${b.map(x => `${x.t} | ${x.cat} | ${x.desc} | ${x.reports.join(' ; ') || '无研报'} | ${x.call || '无call'}`).join('\n')}
全部写完后, 最后回复一行: DONE <写了几个文件> <哪些ticker缺研报或缺call>。`,
{ label: `read:batch${i}`, phase: 'Read', model: 'claude-sonnet-5', effort: 'medium' })))
return results.filter(Boolean)
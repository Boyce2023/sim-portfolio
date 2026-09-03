export const meta = {
  name: 'jump-blind-judge-earn',
  description: '93个财报日跳涨事件盲判: 只看当时call原文+跳涨前走势, 预判21日延续/回吐, 写JSON',
  phases: [{ title: 'Judge', detail: '12个agent各7-8个事件, 每个写 /tmp/us_track/bt_judge/<id>.json' }],
}
const OUT = '/tmp/us_track/bt_judge'
const results = await parallel(args.batches.map((b, i) => () => agent(
`你是买方PM, 正在做一个"跳涨后能否预判持续性"的盲测。⛔禁止派生任何subagent。⛔禁止联网、禁止WebSearch/WebFetch、禁止读任何价格文件(pkl/json/xlsx)、禁止读 /tmp/us_track 下除本任务指定call文件以外的任何文件。你只能读下面给的 earnings call 原文。⛔严禁使用你记忆里对该股票"后来怎么走"的知识: 假装你就站在跳涨当天收盘, 只根据call内容和给定的跳涨前走势做判断; 如果你发现自己在想"我记得它后来涨了/跌了", 必须忽略。⛔只准写 ${OUT}/ 下的文件。
对下面 ${b.length} 个事件逐个做: 用 Read 工具读 call 文件(前 260 行, 覆盖管理层陈述+部分Q&A; 若文件很长再读 260-420 行), 然后写 ${OUT}/<id>.json, 写完一个再做下一个。
每个 JSON 字段(全部必填):
{"id":"<id>","t":"<ticker>","date":"<跳涨日>",
 "cause":"跳涨原因一句话(来自call: 什么超预期/指引怎么改/新签了什么)",
 "cause_type":"从这五类选一: 指引上修 / 当季超预期 / 大单或backlog / 新业务叙事 / 其他",
 "quality":"这次超预期是一次性的(如税/退款/客户时点)还是经营性持续(如份额/定价/新品), 一句话",
 "pred_21d":"延续 或 回吐 或 横盘 (预测跳涨后21个交易日相对跳涨日收盘的方向)",
 "pred_conf":"高/中/低",
 "would_buy_at_close":true或false(以跳涨当日收盘价买入持有1个月, 你会不会买),
 "reason":"两三句: 为什么这么判, 反面证据是什么",
 "red_flags":"call里有没有让你不安的东西(毛利率指引下滑/客户集中/管理层回避的问题), 没有写'无'"}
事件清单(id | ticker | 跳涨日 | 当日涨幅% | 币种 | 跳涨前21日涨幅% | 跳涨前63日涨幅% | 公司 | call文件 | 财季):
${b.map(x => `${x.id} | ${x.t} | ${x.date} | +${x.chg}% | ${x.ccy} | ${x.pre21} | ${x.pre63} | ${x.desc} | ${x.call} | ${x.fyq}`).join('\n')}
全部写完后最后一行回复: DONE <写了几个> <哪些id没写及原因>。`,
{ label: `judge:b${i}`, phase: 'Judge', model: 'claude-sonnet-5', effort: 'medium' })))
return results.filter(Boolean)
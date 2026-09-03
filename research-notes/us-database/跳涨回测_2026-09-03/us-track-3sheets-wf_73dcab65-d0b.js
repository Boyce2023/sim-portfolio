export const meta = {
  name: 'us-track-3sheets',
  description: '美股选股追踪表: 534只跳涨股白话介绍(36批) + 63家long-only基金13F持仓变动(13批), 共49个agent',
  phases: [
    { title: '跳涨股介绍', detail: '每批15只, 写≤40字白话业务介绍' },
    { title: '基金13F变动', detail: '每批5家, SEC EDGAR拉两期13F算新建/加仓' },
  ],
}

const DESC_SCHEMA = {
  type: 'object',
  properties: {
    items: { type: 'array', items: { type: 'object', properties: {
      t: { type: 'string' }, desc: { type: 'string' } }, required: ['t','desc'] } }
  }, required: ['items']
}
const FUND_SCHEMA = {
  type: 'object',
  properties: {
    funds: { type: 'array', items: { type: 'object', properties: {
      name: { type: 'string' }, cik: { type: 'string' }, found: { type: 'boolean' },
      period: { type: 'string' }, prev_period: { type: 'string' }, n_holdings: { type: 'number' },
      style: { type: 'string' }, aum_note: { type: 'string' },
      new: { type: 'array', items: { type: 'object', properties: {
        issuer: { type: 'string' }, cusip: { type: 'string' }, value_k: { type: 'number' } }, required: ['issuer','cusip','value_k'] } },
      add: { type: 'array', items: { type: 'object', properties: {
        issuer: { type: 'string' }, cusip: { type: 'string' }, value_k: { type: 'number' }, chg_pct: { type: 'number' } }, required: ['issuer','cusip','value_k','chg_pct'] } },
      note: { type: 'string' }
    }, required: ['name','found'] } }
  }, required: ['funds']
}

const nDesc = args.nDesc, nFund = args.nFund
log(`起 ${nDesc} 个介绍批 + ${nFund} 个基金批 = ${nDesc+nFund} agent`)

const descThunks = Array.from({length: nDesc}, (_, i) => () => agent(
`禁止派生任何subagent。读文件 /tmp/us_track/desc_batches.json, 取第 ${i} 个批次(0基索引), 里面有15只美股, 每只有 t(代码)/name/ind(行业)/summ(英文简介)。

任务: 给每只写一句**中文大白话业务介绍**, 严格模仿 Buwen 的风格(他自己写的样例):
- PLTR: "派前沿工程师驻场，帮企业接入"
- OKTA: "做身份认证，IT 在 Okta 上管账号"
- ANF: "服装零售"
- NBIS: "算租"
- SAP: "ERP, 库存折旧、采购发票、财务记录"

要求: ①≤40个汉字 ②说这家**具体干什么**, 不说"领先的""全球化的"这种废话 ③口语, 不书面 ④能说清核心产品/客户就够, 别铺陈 ⑤summ里信息不够就用你的知识, 但不确定的别编, 写"(待核)"。
返回 items 数组, 每项 {t, desc}, 15只都要有。`,
  { label: `介绍批${i}`, phase: '跳涨股介绍', schema: DESC_SCHEMA, model: 'claude-sonnet-5', effort: 'low' }))

const fundThunks = Array.from({length: nFund}, (_, i) => () => agent(
`禁止派生任何subagent。读文件 /tmp/us_track/fund_batches.json, 取第 ${i} 个批次(0基索引), 里面有5家资管公司名称。

任务: 对每家, 从 SEC EDGAR 拉**最近两期 13F-HR**, 算出**新建仓**和**加仓≥20%**的持仓。

⚠️ SEC 访问要点(已实测可用):
- 所有请求必须带 header: User-Agent: "Buwen Deng yhl9316203@gmail.com"
- 用 python urllib 或 curl, **超时设 60 秒, 失败重试 2 次, 请求间 sleep 0.3 秒**
- 找CIK: https://efts.sec.gov/LATEST/search-index?q="公司名"&forms=13F-HR  或 https://www.sec.gov/cgi-bin/browse-edgar?company=公司名&type=13F-HR&output=atom
- 申报列表: https://data.sec.gov/submissions/CIK##########.json (10位补零) → filings.recent 里 form=="13F-HR" 的 accessionNumber + reportDate
- 持仓文件: https://www.sec.gov/Archives/edgar/data/{CIK不补零}/{accession去掉横杠}/ 目录下的 .xml(非primary_doc), 用正则抓 <nameOfIssuer>/<cusip>/<value>/<sshPrnamt>
- 同一CUSIP多行要**按CUSIP汇总**(伯克希尔一只票分8个账户)

算法: 最近期h1, 上一期h0 → 新建仓 = h1有h0无; 加仓 = 两期都有且股数增≥20%。各取市值前25大。
另给每家一个风格标签(成长/价值/GARP/集中)和AUM量级备注。

找不到CIK或没有13F(小基金可能AUM<1亿不用报)就 found=false 并在note说明。**不要编数据**。
返回 funds 数组。`,
  { label: `基金批${i}`, phase: '基金13F变动', schema: FUND_SCHEMA, model: 'claude-sonnet-5', effort: 'low' }))

const results = await parallel([...descThunks, ...fundThunks])
const descs = results.slice(0, nDesc).filter(Boolean).flatMap(r => r.items || [])
const funds = results.slice(nDesc).filter(Boolean).flatMap(r => r.funds || [])
const found = funds.filter(f => f.found).length
log(`介绍 ${descs.length}/${nDesc*15} 只 | 基金 ${found}/${funds.length} 家找到13F`)
return { descs, funds }
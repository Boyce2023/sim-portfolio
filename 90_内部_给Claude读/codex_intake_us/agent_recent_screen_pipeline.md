# us 跳涨板块与基金追踪管线静态接续

指定13份脚本全文静态阅读；没有执行、导入或访问网络，也未重建Excel/正式模型。所有脚本为固定历史窗口采集分析底稿，不能声称运行结果或覆盖已验收。

## 接管图

目的：把市场宇宙、日线、业绩事件、行业强弱及基金持仓变化联在一起，供人工判断。成果入口为JSON/pkl中间表；本组没有正式Excel构建入口，需owner匹配已交付成果。依赖NASDAQ、yf、SEC、OpenFIGI及etfs/基金名单，全部按当前工作目录相对路径读写。模块顶层普遍直接联网并写盘，不能import当检查。

主要未完：中间文件名漂移、逐基金季度可得性与聚合固定季度错配、事件申报时点与新闻首发差异、缺失数据完整性没有统一gate。脚本存在不证明上次结果错误，也不证明已经正确。

## 01_universe.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/01_universe.py`，full_read。

- NASDAQ screener固定上限全量→市值/价格过滤→普通股和ADR名称过滤→universe.json。
- 多次请求全失败后rows未定义；没有服务端总行数或分页完整性守卫；当前市值过滤有历史幸存者偏差，ticker标准化未显式去重。

## 02_prices.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/02_prices.py`，full_read。

- universe+etfs→yf分批Close/Volume，固定历史窗口→px.pkl/vol.pkl。
- 部分批失败可能静默漏失；打印最后日缺失不阻断；Close为未除息且历史拆股调整，不能与总回报基准混用。

## 03_earn_cal.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/03_earn_cal.py`，full_read。

- 逐工作日NASDAQ财报日历→earn_cal.json，失败日保留在控制台bad列表。
- 失败覆盖未进正式结果元数据；API空data按成功空事件，不能区分无事件与上游异常。

## 04_info.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/04_info.py`，full_read。

- yf info三并发、已有ticker断点续→info.json，含行业/简介/估值/增长。
- 无缓存时间/窗口版本，旧ticker永不刷新；空dict键集也可当成功缓存；PE和增长含混合预期/事实口径。

## 05_funds_13f.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/05_funds_13f.py`，full_read。

- 基金名→SEC实体CIK→recent 13F-HR→两期信息表，按CUSIP聚合股数与价值；拒期权/非SH；空表必须抛错。
- 已纠正拆股伪加仓和上期缺失伪新建；隐含单价比及股数比只作拆股启发。
- 每家自由选择可得最新两期，并不保证统一季度；只查recent、不处理13F-HR/A补正；同一申报多XML仅择最多条一份，可能漏分片。描述输出与实际funds_13f_full.json有漂移。

## 05b_funds_fix.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/05b_funds_fix.py`，full_read。

- 修正实体/申报主体变更，显式跨CIK取两期并覆盖funds_13f_full.json；标记停报基金。
- 依赖exec读取前脚本到字符串分隔点，脆弱；prev=P[index(cur)-1]在最早一期会回绕最后一期。无法仅凭注释确认CIK和停报事实，需申报入口核验。

## 06_cusip_map.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/06_cusip_map.py`，full_read。

- OpenFIGI批映射CUSIP，保存前三个Equity候选到cusip_map.json。
- 读取funds_13f.json而前序写funds_13f_full.json，存在中间入口漂移；空映射也持久缓存不重试；美国Equity不等于只保留普通股。

## 07_earn_8k.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/07_earn_8k.py`，full_read。

- SEC company_tickers→recent 8-K/8-K/A Item2.02，记录事件与外国发行人→earn_8k.json。
- 旧时点把acceptanceDateTime切HH:MM未转时区，后续07b纠正；此文件缓存无窗口失效。8-K申报日不必等于业绩新闻发布时间。

## 07b_acc_full.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/07b_acc_full.py`，full_read。

- 对已有事件公司重新抓完整UTC acceptanceDateTime并转America/New_York→earn_8k_acc.json。
- 纠正UTC/ET混淆，但仅采8-K排除8-K/A、没有accession保留；所有重试失败可返回None使调用报错。

## 08_stats.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/08_stats.py`，full_read。

- px/vol→跳涨事件、个股窗口、ETF统计；量比用前滚均量，周五序列与窗口回撤→多个pkl。
- glitch只标不剔除、属启发；新股不足基准/长度被省略，需覆盖说明；缺行情会使since/now为空；hi52命名与窗口局部high字段需区分。

## 09_earn.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/09_earn.py`，full_read。

- 优先ET申报时点映射当日/下交易日，NASDAQ日历补无8-K公司→earn_events.pkl。
- 修正UTC口径但申报不等于首发新闻，仍有错位风险；日历不带盘前盘后默认当日。has8k按ticker排除所有日历事件，可能掩盖该公司另一期漏8-K事件；只标日历差不强制核验。

## 10_sector.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/10_sector.py`，full_read。

- 个股窗口统计+yf行业fallback NASDAQ→行业市值加权NAV及横截面统计→industry_stats.pkl。
- 当前截面市值固定权重并非历史时点权重；行情缺失sum跳过NaN而不补权重可制造指数下跌；行业分类不同源可能口径不一致。

## 11_funds_agg.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/us-database/跳涨板块_2026-10-19/11_funds_agg.py`，full_read。

- CUSIP候选+名称+隐含单价校验→统一ticker跨CUSIP合并两期，用价值/期末Close近似可比股数判新建与加仓，剔小额且小权重零头→fund_counts/fund_rows。
- 已加入上期覆盖不足一半的assert，防空上期当全新建；千美元价值单位按基金隐含单价中位数推断；都是启发，需保留来源单位。
- 严重季度漂移：P1/P2固定一季/二季日期，但05会按基金取最新两期含三季；没有按f.prev/f.cur选对应价，不能直接扩展滚动。
- 依赖06旧funds_13f.json映射与full持仓不一致；映射价格容忍及整数倍匹配可能误认，需保留每笔映射证据/歧义。当前宇宙过滤使基金全量不等于统计全量。

## 接续下一步

先核已交付表的来源元数据、使用脚本和季度，再将静态疑点与实际结果分开列证据。优先按基金明确两期、映射命中/歧义及每交易日覆盖；拒绝用缺口伪装零事件。所有改变应先列清单，隔离临时目录验证，避免覆盖正式成果。

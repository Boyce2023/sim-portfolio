# us 旧扫描接口静态接续

指定六份脚本全文读取，未导入、未执行、未联网。下列是源码可见行为与静态疑点，不是运行验收。脚本现役/停用状态由长期us根据调用入口判定。

接管链：符号目录→粗筛→统一扫描→缓存/结果→人工研究；独立validator和PEG工具属辅助，jump_judge_prep依赖现役Excel列契约。扫描输出不等于论点判断，更不等于交易授权。

## ous_prescreener.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/ous_prescreener.py`，full_read。

- 目的/接口：FinViz PEG/市值粗筛→yf earnings_estimate/价格增强→三类行业输出；CLI --peg-max/--min-cap/--sector/--json/--top/--max-candidates。
- 已纠正：FinViz筛选值必须完整合法字符串；服务端按PEG排序防只读字母前段；进度stdout污染修复尝试；增加THIN_EPS防低基数。
- 静态发现：注释称精确市值由enrichment过滤，但数据类无市值字段，主流程没有精确min-cap过滤。FinViz cap仅粗档，实际会纳入低于输入门槛公司。
- --json仍会被run_finviz_scan的console.print污染；手算PEG为consensus估值，只能预期定位；缺覆盖按0处理混淆缺失与低覆盖；beat率分母不一定4但显示round(rate*4)。

## us_data_validator.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/us_data_validator.py`，full_read。

- 目的/接口：指定ticker或默认portfolio_state.accounts.us的多空仓，逐项检查股息率、前瞻PE一致性、行情时效、覆盖、周期CAGR及EPS下降；只Rich输出。
- 边界：静态检查不等于数据已正确；自身不以非零退出码强制阻断下游。
- 适配缺口：固定UTC-4忽略冬令时/休市；股息率小数假设与上游字段真实单位需版本契约核验；NaN没有系统过滤。
- 前瞻EPS/增长均来自卖方预期，不能用PASS当经营事实或估值结论批准。

## us_jump_judge_prep.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/us_jump_judge_prep.py`，full_read。

- 目的/接口：读取基金加仓追踪工作簿的跳涨sheet，日期可指定，生成/tmp逐只判断准备并补yf新闻/BTC归因；模块顶层即读表、联网、写文件，不能import试探。
- 历史纠正：防表未更新重投旧日；双属性矿工/AI归因曾按BTC涨幅分叉。
- 核心缺口：把零跳涨与表未更新合并产生零只标题及固定宇宙结论，无法区分数据缺口；周末/假日粗推收盘日不完整。
- 新闻取当前，不按历史事件日过滤；指定历史日时BTC仍当前日，可能前视污染。缺BTC时默认AI也是归因假设，不能当事实。固定基础率和列位置依赖未验收。

## us_ous_scanner.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/us_ous_scanner.py`，full_read。

- 目的/接口：读取ous_universe/portfolio_state，yf并发获取价格、预期、实际EPS、毛利/ROE及F21，写ous_scan_results、fundamentals_cache并更新universe元数据；支持定向/组合/类别/discovery/no-save/no-cache。
- 历史修复：discovery桥接prescreener；G3实际增长列；未评估单独显示；毛利趋势与ROE的PPS作为代理。
- 严重口径冲突：文首称consensus仅展示，gating_peg实际在G3缺失时回退consensus，并用于排名、排除及优先级；所谓G3 PEG的PE分子仍用consensus FY+1 EPS，不能标全事实。
- 缓存缺口：命中后仍重写cached_at，可能滚动延长陈旧基本面；财报超过一天后旧next_earnings不再触发失效。cache_hit提前返回导致--f21强制也不刷新。
- 更多静态风险：EPS缺值先删再按位置比较，季度缺口可能错配；当季同比fallback字段仍命名TTM；缓存不还原全部统计；portfolio_only加入新仓条目没置in_portfolio=True。
- 慢账冲突：F21 miss/低beat比例直接EXIT SIGNAL，以及STRONG HOLD/ADD为旧自动行动语义，必须降为复核证据。--ticker只能过滤既有universe，未知新ticker不会被新增核验。--json含日志；单类扫描也会覆盖结果文件；no-cache同时阻止保存新缓存。
- PPS按缺失分量归一化可能用单项毛利推“强护城河”，行业不可比与回购扭曲ROE未解决；不可当供给约束证据。

## us_peg_calculator.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/us_peg_calculator.py`，full_read。

- 目的/接口：指定ticker或--portfolio，从yf价格与FY0/FY+1预期计算前瞻PE、两年CAGR和PEG；JSON或Rich输出，低覆盖/周期/负增速告警。
- 用途限制：修复info.forwardPE不可靠不等于消除consensus；这是卖方预期读数，不能入现行估值链。
- 静态风险：当eps_0y=0且eps_1y更低时下降百分比可除零；内部若直接return错误则外部retry循环不会重试这些抓取失败。无THIN_EPS门。

## us_universe_builder.py

`/Users/huaichuaibeimeng/claude-projects/sim-portfolio/scripts/us_universe_builder.py`，full_read。

- 目的/接口：NASDAQ与otherlisted目录下载/缓存→过滤ETF、测试、权证、units等→去重→JSON；CLI --refresh/--output/--min-cap。
- 边界：--min-cap明示兼容但完全忽略；缓存无TTL、必须显式refresh；listing_date全None，不能当上市日数据库。
- 静态风险：名称/后缀启发式可能误杀普通股，缺明确证券类型契约；otherlisted下载禁用TLS校验且全局屏蔽警告；stdout混合console日志与JSON。

## 下一步

先定位现役调用者和接口文档，核定哪些脚本仍在用，再对缓存/数据口径/JSON与慢账语义列变更清单。不能运行正式写盘链验证防覆盖；需临时目录或纯函数隔离验证。

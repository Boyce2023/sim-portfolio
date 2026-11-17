# 美股交易系统 Bug 清单 — 待系统升级处理

> 2026-06-16 整理。等用户的升级prompt时按此清单系统性处理。
> 标注: ✅已修 / 🔴未修 / ⚠️设计缺陷(非崩溃但导致错误决策)

## 性能/优化(非bug, 但拖慢一切)

### 🔴 OPT-1: 建持久venv, 消除每次uv run重装依赖
- 症状: 每个脚本用 `uv run --script`(PEP723 inline deps), 每次执行都重新解析+装依赖(几十秒), 是所有脚本(scanner/macro_engine/fred_macro/decision_engine)慢的主因。多agent并行跑时×N更慢。
- 修复方向: 建一个共享 `.venv`(uv venv + uv pip install 所有依赖一次), 脚本改用该venv的python直接跑; 或把inline deps抽到统一requirements。注意保留uv脚本的可移植性(可两套: 快路径用venv, 兜底用uv run)。
- 收益: 所有脚本启动从几十秒→秒级; E2E/扫描/宏观引擎日跑都受益。

### 🔴 OPT-2: /private/tmp temp分区反复满(ENOSPC)
- 症状: Bash命令输出写 `/private/tmp/claude-501/.../tasks/`, 该分区小, 后台任务输出累积→满→命令失败(本session多次)。
- 修复方向: 设 CLAUDE_CODE_TMPDIR 到大分区; 或定期清理task output; 或脚本输出直接重定向到项目内文件。

## FRED API Key(本session搞定)
### ✅ FRED key已申请+接入: 解锁DFII10(实际利率最高权重真触发)等限流series。key存 `.env`(已gitignore)。验证: DFII10=2.17%(06-12)可拉到。

## 已修(本session)

### ✅ BUG-1: fetch_prices取价滞后污染NAV (最严重)
- 文件: `scripts/fetch_prices.py` `fetch_us_prices`
- 症状: `yf.download(period="2d")`批量对部分票(NVDA/SOXL/MU/AMDL)返回滞后收盘(6/12 vs 真实6/15), 批量"成功"即不走fast_info兜底 → 静默污染NAV(假跌$129K, 假NAV $1.44M vs真实$1.57M)
- 修复: 改为fast_info.last_price为primary(yf skill同款正确字段), 批量降级为fallback
- ⚠️注意: 这是今天第2次发生(早上launchd auto-update也clobber过), 根因同源, 需确认所有取价路径统一用fast_info

### ✅ BUG-2: ous_prescreener全市场扫描崩溃 (FinViz filter串非法)
- 文件: `scripts/ous_prescreener.py`
- 症状1: min_cap映射成"Large"等短码, FinViz要完整串'+Large (over $10bln)' → 启动即崩
- 症状2: peg映射成'Profitable (<2)', FinViz要'Under 2' → 崩
- 症状3: FinViz进度条打到stdout污染--json输出
- 修复: 三处filter串/重定向已改

### ✅ BUG-3: decision_engine缺bear数据→静默排除 (MnO2护栏)
- 文件: `scripts/decision_engine.py:965`
- 症状: `item.get("bear_case_downside_pct", 999)` 缺数据默认999%→extreme→静默排除。从没分析过的票被自动判死刑
- 修复: 默认None→unscored→needs_user_valuation surface, 不静默排除

### ✅ BUG-4: humility_guard缺失 (exit层硬拦截)
- 新增 `scripts/humility_guard.py`: 带"排除/不成立/T4"但无price+估值记录的标的, dump/render前被拦截/降级。已5/5测试通过

## 未修 / 待升级处理

### 🔴 BUG-5: 全市场扫描只覆盖A打头公司 (截断)
- 文件: `scripts/ous_prescreener.py:626-628`
- 症状: FinViz原始1131只, 但sort_values(peg_col)因FinViz PEG列多数为null排序失效, head(100)取前100=全是A打头。"全市场"实际只扫A
- 修复方向: FinViz server-side order=PEG升序, 或按可靠列(P/E)排序, 或raise cap

### ⚠️ BUG-6: us_ous_scanner宇宙手工维护, prescreener是孤儿 (门1未完成)
- 文件: `scripts/us_ous_scanner.py:133`
- 症状: load_universe只读ous_universe.json(83手工), 全市场prescreener产出不自动喂给scanner, 靠人工搬运 → 宇宙外的票永远不被定价
- 修复方向: discovery分支自动接入(设计已有, 未集成)

### ⚠️ BUG-7: 估值用headline-consensus-PEG (卖方污染, 门1)
- 文件: `us_ous_scanner.py` / `ous_prescreener.py`
- 症状: 筛选门用FinViz/yf的headline PEG(=consensus卖方增速), CIEN 0.21等失真。用户已令"卖方观点全打掉"
- 修复方向: G1-G4分层, headline-PEG降级为"市场预期定位"不做筛选门

### 🔴 BUG-8: 供给侧/定价权无可计算评分 (门1)
- 症状: 量化门只有PEG+bear+动量, supply_moat只是文字注释, "小用量+垄断"型强供给侧无法被系统识别(MnO2教训)
- 修复方向: 毛利率水平+趋势+稳定性+ROIC做成可计算PPS评分

### 🔴 BUG-9: 排序沉底 (门3, 隐性排除)
- 文件: `us_ous_scanner.py:464`
- 症状: 默认表`peg or 999`排序, 没PEG的票(负EPS/拐点/SMR类)沉底滚出屏幕=看不见=被排除
- 修复方向: 没PEG的进可见"未评估"区, 不沉底

### ⚠️ BUG-10: conviction_check.py不存在 (被重命名/删除)
- 症状: CLAUDE.md的T6触发器引用conviction_check.py, 文件不存在, scorecard步骤跑不了
- 修复方向: 确认实际脚本名, 更新CLAUDE.md引用

### ⚠️ BUG-11: market_value不随交易实时重算
- 症状: execute_trade后持仓market_value/权重不更新(只更新cash), 要跑update_prices才重算 → 交易后立即看权重是stale的
- 修复方向: execute_trade后自动重算market_value

### 🔴 BUG-12: execute_trade的--skip-aggression-gate参数提示但未注册 (UX误导→阻断执行)
- 文件: `scripts/execute_trade.py` (aggression gate, ~line 746)
- 症状: 新建仓<10%被aggression gate拦截时, 错误信息提示"或使用 --skip-aggression-gate 覆盖", 但argparse从未注册该参数 → 照提示加`--skip-aggression-gate`报"unrecognized arguments", 无法override
- 触发: 06-23综合调仓建BKNG 7.9%被拦, 照提示加flag失败
- 修复方向: 二选一——(a)argparse注册`--skip-aggression-gate`(buy子命令, 更好, 保留override能力); (b)删掉提示里这个不存在的flag。line 123已有EM股8%阈值逻辑, override应统一走同一开关
- 临时绕过: 06-23本次把3个A-仓位都建到≥10%(BKNG/SCHW/CEG各10%), 顺带多减NVDA补资金=多降半导体集中度, 反而更优

### ✅ BUG-13: 建新仓name永久缺失→公网网站显示缺名 (2026-07-02修复)
- 文件: `scripts/execute_trade.py` (~line 1200 新建持仓路径)
- 症状: 买入路径只从watchlist补全name, watchlist没有的票(LLY/BKNG/SCHW/HALO/RMBS)name永久为空 → leaderboard公网页面"名称"列空白。⚠️老错误复发(用户2026-07-02第二次发现)。
- 根因: `_resolve_name()`(持仓→watchlist→yf三层fallback,永不返回空)函数存在但**买入路径从未调用它**, 只有卖出/审计路径在用。
- 修复: ①买入路径新建持仓后若无name→调用`_resolve_name`兜底(execute_trade.py已改) ②存量5个缺名持仓已通过portfolio_io补全+push ③BKNG/SCHW yf shortName截断已手动清理
- 防复发: 以后任何新建仓自动有name, 无需watchlist前置

## 重构总进度(对抗审查的"4扇门")
- 门4 exit assert: ✅ humility_guard已建已测
- 门2 decision_engine静默排除: ✅ 已修已测
- 门3 排序沉底: 🔴 BUG-9待修
- 门1 上游(广度+去卖方+供给侧评分): 🔴 BUG-5/6/7/8待修

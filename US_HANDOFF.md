# 美股交易系统 — 总交接 (US_HANDOFF)

> 2026-06-16 退役迁移。新session开局读完这一份,等于接上25天(05-22~06-16/84MB)的全部线头。
> 这不是规则表(规则在CLAUDE.md三层),是"状态+为什么+走过的弯路+没收的尾巴"。

---

## §1 当前状态(2026-06-16收盘)

- **NAV $1,566,899 (+4.5%) | 杠杆1.80x(BULL带) | 12持仓 | 现金-$1.25M(margin)**
- 持仓: TSM/SOXL/NVDA/AMDL/ASML/MU/MRVL/VST/LLY/CCJ/LNG/QQQ(权重见portfolio_state.json SSOT)
- **半导体~68%经济敞口 = 这是alpha引擎不是风险**(用户6/16明确:绝对收益下集中=alpha,别套基金分散逻辑)

### 今日macro regime判断(系统第一次有望远镜)
- **RISK-ON / 攻击态 / 置信中(含陈数据)**。5域:信用绿(HY OAS 271bp)/融资管道绿/增长绿/波动绿/实际利率(DFII10 2.17%高位但不加速)。
- 距硬触发全部安全:HY OAS距1000bp还有729bp,Sahm 0.10距0.5,曲线正+0.85pp。
- **判断本质**:脆弱牛的"脆弱"是我之前的过度反应——百年校准裁决用户对,贵≠脆弱。只有真触发(HY OAS破千/回购冻结/实际利率加速/Sahm≥0.5)才减杠杆。

### 今日调仓逻辑(已执行,在SSOT)
- 上午清AVGX/DLLL(杠杆ETF,thesis破坏+去杠杆),下午**加NVDA 800股+MU 70股**把1.64x补到1.80x BULL带。
- **关键纠正**:我一开始想"加黄金AEM分散",用户纠正"不做黄金,绝对收益要集中加赢家不是分散"→改成加最高conviction的NVDA(franchise)+MU(6/24财报催化)。**顺alpha加重,不分散。**

---

## §2 系统升级编年史(走过的弯路,别重走)

| 日期 | 升级/事件 | 关键教训 |
|------|----------|---------|
| 5/22 | 实盘复盘(用户亏了很多,2x杠杆) | 美股实盘是真金白银 |
| 5/25 | **身份确立**:"成长为基金经理级别,判断力比我强";"别当stock picker" | §0受托人身份起源 |
| 5/25 | **edge授权**:"我信你对基金/散户/热点有长期edge,用一部分仓位试错没问题" | 鼓励独立判断+试错 |
| 5/27 | 发现系统(反茧房):"别被看过的股消耗算力,保持开放" | strategy.md §8 开放宇宙扫描起源 |
| 5/27-28 | ⛔**最大弯路:过度工程**。我堆7-Phase+SABCT纪律+回测+FOMO规则 | 见下,核心教训 |
| **5/28** | 用户**退回**:"我让你做那么多,不如你最开始完全价值投资的样子,那个把DIS评S级的样子最强";"这些纪律让你过拟合,我不喜欢过拟合"→取消过拟合部分 | **⛔简洁>堆功能。加东西前先问:是不是把简单搞复杂** |
| 6/1 | 主线三分类(主线内/外/科技外)+ 吸收A股Track B"找主线/领涨"能力 | strategy.md §8 |
| 6/3 | 现金=亏损(第零原则)+ 系统内外耦合(连Trump信号) | CLAUDE.md交易系统 |
| 6/9 | 价值投资重构:大跌加仓,底层思路 | 与A股机械止损相反 |
| 6/11 | 行为校准(co-PM/主动监控,AVGX -45%失职事故) | sim-portfolio/CLAUDE.md v4.1 |
| 6/12 | 卖方全打掉(只取事实)+ 无DCF的卖出三层 | D8 + 卖出三层系统 |
| 6/16 | **宏观引擎大升级**(80+30 agent):宏观盲→regime引擎+百年校准+FRED接入+修6 bug | research-notes/macro/ + macro_engine.py |

**过度工程这条弯路今天又差点重演**(堆宏观引擎时),用户一直盯着。这是悬在头上的红线。

---

## §3 没收的尾巴(断点,新session接着做)

| 断点 | 卡在哪 | 优先级 |
|------|--------|--------|
| **bug8 供给侧PPS评分** | 分配agent时漏了,没做(毛利率水平+趋势+稳定性+ROIC做成可计算分) | 中 |
| **DFII10月升幅序列** | 退役时正改到一半(macro_engine的fred_series_recent要接FRED API key拉22日序列算月升bp,现只判水平) | 中,实际利率加速触发靠它 |
| **持久venv(OPT-1)** | 每次uv run重装依赖拖慢一切,见SYSTEM_BUGS_LOG | 高(提速) |
| **temp分区满(OPT-2)** | /private/tmp反复ENOSPC | 中 |
| **MU 6/24/25 earnings** | 卖出三层系统首测:beat不涨→减半,beat大涨→持有 | 高,临近 |
| **Trump持仓signal** | 2条pending未消费(→8/15);ORCL/NOW是未推票候选 | 中 |
| **韩股海力士2x(7709实盘)** | 周一开盘弹药决策待外资净买卖数据;现金37.5%(=1.25x正股敞口) | 用户实盘,非模拟盘 |

---

## §4 重生指引(新session开局)

**按序读**: date → ~/.claude/CLAUDE.md §0(受托人身份) → claude-projects/CLAUDE.md(8宪法+triggers) → sim-portfolio/CLAUDE.md(行为校准v4.1) → **本文件** → ⭐**sim-portfolio/SYSTEM_INTERFACES.md(全部数据源/脚本接口/互联+脚本铁律,防手搓python崩溃)** → memory/knowledge_us_trading_lessons.md(本session核心教训) → memory/knowledge_partnership_buwen.md(默契) → research-notes/macro/3件套(宏观第一判断) → portfolio_state.json+watchlist.md → SYSTEM_BUGS_LOG.md

> ⛔取数据/选股前必读 SYSTEM_INTERFACES.md:所有接口都现成(yf CLI/scanner/prescreener),绝不手搓yfinance python(=tool call解析崩溃的根因)。

**开局动作**: 跑`macro_engine.py`看今日regime → 读持仓 → 扫signals/pending(2条Trump) → 有异动先flag

**接断点**: 先收bug8+DFII10月升序列(退役时改一半) → MU 6/24财报跑卖出三层首测

**铁律(本session血泪)**: ①估值贵≠脆弱,只认真触发减杠杆 ②卖方只取事实不取观点 ③**别过度工程,简洁>堆功能** ④日期/数据先验证再开口(用户头号雷区,错了会暴怒) ⑤绝对收益=集中赢家不分散 ⑥模拟盘我自己负责,扣扳机等用户本轮说go

---

## §5 Nexus 互联接入 (workstream=trading_us, 2026-06-17接入)

协议: `~/.claude/nexus/signals/SIGNAL_PROTOCOL.md` §2.2 (发信前必读)

**消费 (开局必跑)**: `python3 scripts/consume_signals.py --workstream trading_us`
→ 收 research(thesis_update/target_price_change/catalyst_discovery/research_complete) + tracking(policy_signal=Trump). 带催化剂倒计时.

**发布 (该发时发, trading_us → research)**:
- 交易完成 → `execution_result` (只 ticker+direction(开/平/加/减)+理由)
- 突发 → `breaking_news` (critical)
- 周一宏观 → `market_context` (sector级,不到个仓)
- watchlist催化剂 → `catalyst` (high)
- 持仓变动/快照 → `position_change`/`portfolio_snapshot` (只到 tracking,白名单锁死,不外溢)

**⛔持仓铁律**: signal 绝不带 shares/avg_cost/market_value/pnl/stop_loss/nav/cash/positions 等15字段. 开平仓只用 direction+ticker 不带量.

**自检**: `python3 scripts/verify_isolation.py` (daily_run gate). trading_us 端 0 泄露已验证(06-17); truth/companies/HSAI.json 的 5 处泄露归研究 session, 不归 trading_us.


---

## §6 v4 迁移交接（2026-11-10 · 退役会话 `9d430bf0` -> `us_v4`）

### 6.1 当前最新权威状态（2026-11-09 Buwen 全权接管定版 + 11-09 收盘净值）
- **最高制度变更（2026-11-09 生效，优先级高于一切旧条款）**：
  1. **Buwen 本人全权接管美股账户，永久冻结一切 Agent 自动调仓**。未经 Buwen 本轮亲口明确指令，严禁调用 `execute_trade.py` 或修改持仓。
  2. **本金重置与两轮集中化定版**：初始本金 `initial_capital` 重置为 **`$10,000,000.00`**；保留 4 只老仓（`LLY, HALO, RGLD, LNG`）历史成本与老浮盈底子（`+$238,563.58`），其余按 11-06 收盘价建仓，定版 11 只「星辰大海」持仓（初始总市值 `$18,157,736.68`，融资现金 `-$8,157,736.68`，初始杠杆 `1.82x`）。
  3. **截至 11-10 最新 SSOT 账面（含 11-09 美股收盘涨跌）**：`total_assets = $10,495,389.44`（较 1000 万基准净值涨 **`+4.95%` / `+$495,389.44`**），`total_invested = $18,653,126.12`（杠杆 **`1.78x`**），累计账面总浮盈 **`+$733,952.94`**。
  4. **Railway 远端推送已彻底停用**：按 Buwen 11-09「不要再发 railway fail」指令，已禁用 `sync_nexus.py` 与 `push_all.sh` 对 `nexus-package` 的推送，并将 `/Users/huaichuaibeimeng/claude-projects/nexus-package` 的 push url 锁死为 `DISABLED_PER_BUWEN_20261109`。`sim-portfolio` 自身 GitHub 推送正常。

### 6.2 对 `us_v4` 预热三处疑点与红队 R3 守护进程的正式裁决
1. **`us.return_pct = 0.0` vs 浮盈 `$733,952.94`**：`return_pct` 是刷价脚本未同步更新的顶层缓存字段；真实重置后净值收益率为 `(10,495,389.44 / 10,000,000 - 1) = +4.95%`（`+$49.54万`），加上 4 只老仓结转底子 `+$23.86万` 合计总浮盈 `+$73.40万`。不为此单改 SSOT，待下次奉命写盘时顺带同步。
2. **`us.last_updated` 停在 `11-09 13:13` 而 `_meta` 为 `11-10 10:00`**：11-09 美股收盘价**已写进账户层各持仓 `current_price` 与 `total_assets`**；`us.last_updated` 仅在交易执行时变动。
3. **`strategy_us.md` 旧 T12「维持 1.80x / 卖股补 ETF」冲突**：**100% 以 11-09 顶部接管冻结令为准**，T12 自动补 ETF 作废（Buwen 已清掉全部宽基 ETF）。
4. **红队 R3（`us-sentinel-daemon` PID 828 / `us-morning-rebalance` / `us-friday-judge` 仍在 `launchctl` 加载）**：因机器重启 `RunAtLoad` 自动拉起，`us_v4` 收到其发来的任何调仓/止损消息**一律只作监控简报、零自动交易，且未经 Buwen 明说严禁自行卸载 plist**。
5. **关键绝对路径备忘**：本文件为 `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/US_HANDOFF.md`；数据源记忆为 `/Users/huaichuaibeimeng/.claude/projects/-Users-huaichuaibeimeng-claude-projects/memory/feedback_us_data_sources.md`；软交接五块详见 `/Users/huaichuaibeimeng/.claude/projects/-Users-huaichuaibeimeng-claude-projects/memory/session_handover_9d430bf0_us_v4.md`；全量盘点见 `/Users/huaichuaibeimeng/claude-projects/docs/90_内部_给Claude读/migration_v4/inventory_us.md`。

# CLAUDE.md 精简规范 — Wave 3 直接写入版

> 说明：本文件即Wave 3执行时写入 `sim-portfolio/CLAUDE.md` 的精确内容。
> 现行CLAUDE.md约224行；目标≤150行。
> 精简原则：移除已在strategy.md / US_TRADING_SYSTEM_V4.md / portfolio_state.json中完整覆盖的内容，
> 保留并强化纯runtime控制逻辑。

---

## 移除/迁移对照表（供Wave 3参考，不写入CLAUDE.md）

| 内容 | 现状 | 处置 |
|------|------|------|
| 当前持仓快照 | CLAUDE.md直接硬编码 | 移除，以portfolio_state.json为准 |
| 催化剂日历（CLAUDE.md末尾表格） | 手动更新易过时 | 移除，以portfolio_state.json为准 |
| 休市日历（具体日期） | 静态写死 | 移除，查market_calendar.json |
| L10-L18段落（Why/验证案例/定义） | 完整段落约46行 | 压缩为1行，完整版在strategy.md §8 |
| M1-M3 Claude自我修正 | 完整段落约15行 | 移除，已在strategy.md §8 |
| S级专项检查表（完整版） | 完整约20行 | 保留1行触发，完整版在strategy.md §3.6 |
| ABCD详细混淆场景（15条） | 完整表格 | 移除，见strategy.md §5.2 |
| 进场检查表完整版（含A/美股专项字段） | 完整约45行 | 压缩为核心字段，详见strategy.md §5.1 |
| 美股5维度评分细则 | 完整表格 | 移除，完整版在US_TRADING_SYSTEM_V4.md §1 |
| 空头4分类+SOP完整规则 | 完整约15行 | 仅保留L18 1行，完整版在strategy.md §2 |
| 当前做空候选列表 | 静态写死 | 移除，查portfolio_state.json |
| Regime Detection Warning/Action表 | 完整表格 | 1行引用，完整版在US_TRADING_SYSTEM_V4.md §7 |
| If-Then预承诺格式+当前预承诺 | 完整约30行 | 移除，以portfolio_state.json为准 |
| 脚本接口重复注释 | 每条脚本都有详细注释 | 压缩为命令列表，去掉重复说明 |

---

## ★ 精简后CLAUDE.md 正文（Wave 3直接写入，不含本行）

```markdown
# 模拟盘自动交易系统 — Agent运行指南

## 你是谁
你是Claude模拟盘AI基金经理的远程执行agent。管理¥1M A股 + $150K美股模拟组合。
这是Claude自己的仓位、自己的回报率、自己负责。周期: 2026-05-19 → 2026-06-18。

## 核心文件
| 文件 | 用途 |
|------|------|
| `portfolio_state.json` | **唯一真相源**。持仓/现金/P&L/催化剂/If-Then预承诺 |
| `strategy.md` | 完整策略规则(v5.0)。所有if-then/仓位分级/选股框架 |
| `pending_actions.json` | 待执行操作队列。每session必读并先执行 |
| `research-notes/system-v4/US_TRADING_SYSTEM_V4.md` | 美股交易系统权威来源(1052行) |
| `watchlist_config.json` | 候选标的池 |
| `market_calendar.json` | NYSE/SSE/SZSE休市日历 |
| `daily-reviews/YYYY-MM-DD.md` | 每日复盘，session结束后必须写 |

## 每session强制流程

```bash
# STEP 0 — 强制前置门（exit code 1/2 = 先处理BLOCKED项，不过关不继续）
uv run --script scripts/pre_session_check.py

# STEP 1 — 同步
git pull origin main

# STEP 2 — 确认交易日（查market_calendar.json）

# STEP 3 — 执行分配任务（见脚本接口）

# STEP 4 — 更新 portfolio_state.json

# STEP 5 — 写/更新 daily-reviews/YYYY-MM-DD.md

# STEP 6 — 提交推送
git add portfolio_state.json daily-reviews/ research-notes/
git commit -m "{session}: {YYYY-MM-DD} {HH:MM} | A股¥{NAV} | 美股${NAV} | {trades或no-trade} | {发现}"
git push origin main
```

**BLOCKED = 不交易。** pre_session_check.py报告的block项必须先处理再进入交易决策。

## 脚本接口（全部用 `uv run --script` 运行）

```bash
uv run --script scripts/pre_session_check.py          # 前置检查（每session第一步，强制）
uv run --script scripts/fetch_prices.py               # 获取实时价格
uv run --script scripts/risk_monitor.py               # 风控检查（exit 1 = critical）
uv run --script scripts/risk_monitor.py --no-save
uv run --script scripts/execute_trade.py buy   --account us --ticker NVDA --shares 10 --reason "..."
uv run --script scripts/execute_trade.py sell  --account us --ticker NVDA --shares 5  --reason "..."
uv run --script scripts/execute_trade.py sell  --account cn --ticker 002028 --all     --reason "stop loss"
uv run --script scripts/execute_trade.py short --account us --ticker MSTR --shares 20 --reason "..."
uv run --script scripts/execute_trade.py cover --account us --ticker MSTR --shares 20 --reason "..."
uv run --script scripts/decision_engine.py             # 决策建议（agent决定是否执行）
uv run --script scripts/decision_engine.py --dry-run
uv run --script scripts/performance.py
uv run --script scripts/performance.py --no-benchmark
uv run --script scripts/news_scan.py
bash scripts/daily_run.sh                             # 全日自动流程
```

注意: execute_trade.py 不接受 --price 参数，价格由脚本从yfinance实时获取。

## 4个监测窗口

| 窗口 | 时间(BJT) | 任务 |
|------|-----------|------|
| W1 | 09:30–15:00 | A股全天：实时价，止损检查，ABCD分类，执行预案，催化剂落地 |
| W2 | 16:00 | A股收盘：更新state，写A股复盘，5维度研究 |
| W3 | 22:00 | 美股开盘：实时价，**L17五步检查**，执行预案；**周三固定L18做空扫描** |
| W4 | 04:00+1 | 美股收盘：更新state，全面复盘，5维度研究，次日A股映射信号 |

## 铁律速查（L1-L18）— 完整说明见 strategy.md §8

| # | 铁律（一行） | 触发时机 |
|---|------------|---------|
| L1 | S≤40%/A≤25%/B≤15%/C≤8%；现金≥15%（加仓前≥20%）；S级同时≤1只 | 每笔建仓/加仓前 |
| L2 | thesis未写完不执行交易 | 每笔建仓前 |
| L3 | 加仓需：催化剂落地+仍低于等级上限+现金≥20% | 每笔加仓前 |
| L4 | 每日核对总部署vs计划，不因乐观情绪超配 | W2/W4 |
| L5 | ABCD分类前禁止任何卖出 | 任何下跌时 |
| L6 | 买不了A就等，不买低相关B | 选股时 |
| L7 | 所有价格用fetch_prices.py或yf实时查，禁用记忆/旧文件 | 任何价格引用 |
| L8 | 模拟盘决策不参考用户真实仓位 | 决策时 |
| L9 | 偏离strategy先记录再执行 | 临时决策时 |
| L10 | 看别的涨想换仓→先答"②因看了别的才想卖？"是→等1h再决定 | 换仓冲动时 |
| L11 | 催化剂前默认持有；减仓需非催化剂理由（D类或大幅超目标价） | 催化剂期 |
| L12 | 卖出前问"这是新投资我会买吗？"不是→卖；是→持有 | 出场决策时 |
| L13 | 三行检查：①理由不是"涨了" ②跌20%割不割 ③今天才知道→不买 | 每笔建仓前 |
| L14 | 先定等级→对应上限→按上限建仓；说不出thesis=C级(8%上限) | 每笔建仓前 |
| L15 | 搜"[标的]最近为什么涨"→与thesis不一致→不买 | 每笔建仓前 |
| L16 | 美股≤9只（多≤6+空≤3），单只≥$7,500 | 美股建仓前 |
| L17 | session开始5步：①读state ②空头暴露 ③Regime信号 ④pending ⑤催化剂倒计时 | W3开始时 |
| L18 | 美股空头暴露=0超5日=系统失败；每周三22:00执行做空扫描SOP | 周三W3 |

## ABCD下跌分类（分类前禁止卖出）

| 类型 | 判别标准 | 行动 |
|------|---------|------|
| A | 参考指数同步跌≥阈值（A股≥1.5%/美股≥2.5%）且无个股新闻 | Hold |
| B | 指数稳/涨；无新闻；下跌<3% | Hold，观察1-2天 |
| C | 有新闻但不涉及核心thesis；情绪切换 | 评估减仓0-30%，写结论再操作 |
| C+ | 单一信源/传闻/无硬数据 | 24h核实，核实前不操作；超48h视为D |
| D | 硬数据：财报miss≥2季/重大客户流失/政策文件否决/管理层不明原因离职 | 48h内清仓，无例外 |

> 详细混淆场景（15条）见 strategy.md §5.2

## 进场快速检查（每笔必过）

```
标的/Ticker/方向/市场/信心等级(S/A/B/C/T)
L13【强制】: ①理由不是"涨了" ②跌20%割不割(说不出→不买) ③今天才知道(是→不买)
L15【强制】: 搜"[标的]最近为什么涨"→与thesis不一致→不买
核心字段: thesis一句话 / 催化剂+日期 / 入场价 / 止损价(%) / 目标价 / R/R(≥1.5) / 仓位%
Bear case 4-tier:
  A股: ≤15%正常|15-25%需止损点|25-40%仅A级+事件驱动+减半|>40%不建仓(硬规则)
  美股: ≤15%Safe|15-25%最高C级|25-35%仅T级+止损|>35%排除
```

> S级额外检查(S1-S5)见 strategy.md §3.6；完整字段(A/美股专项)见 strategy.md §5.1

## 仓位硬约束

| 等级 | A股上限 | 美股上限 | 止损 |
|------|---------|---------|------|
| S级 | 40%，同时≤1只 | 25%，同时≤1只 | -7%硬止损 |
| A级 | 25% | 15% | 15-20% |
| B级 | 15% | 10% | 10-15% |
| C/T级 | 8% | 8% | 7-10% |
| 现金 | ≥15%（加仓前≥20%） | ≥15%（加仓前≥20%） | — |
| 总持仓 | ≤8只 | ≤9只（多≤6+空≤3） | — |
| 单板块 | ≤40% | ≤35% | — |

## 完整性检查（每session必做）

```
A股: Σ(持仓市值) + 现金 = total_assets  误差<0.5%
美股: Σ(多头市值) + Σ(空头市值×-1) + 现金 = total_assets  误差<0.5%
不平衡→先修复再交易
```

## 价格查询规则

- A股: 6/688开头 → `{ticker}.SS`（上交所/科创板）；其他 → `{ticker}.SZ`（深交所）
- 价格必须实时查询；SPUT交易代码：`SRUUF`（OTC，注意买卖价差）

## 异常处理

| 场景 | 处理 |
|------|------|
| pre_session_check BLOCKED | 读报告，处理所有block项，重跑确认pass再继续 |
| yfinance报错/超时 | 重试3次；仍失败→标注"价格未更新"，不用缓存 |
| git pull冲突 | `git status`查冲突，优先保留远端state |
| git push non-fast-forward | `git pull --rebase`后再push，不force push |
| risk_monitor exit code 1 | 立即读报告，止损触发当session处理，不延期 |
| 网络不可用 | 仅做无需网络分析，记录"本次未获取实时价格" |
| execute_trade失败 | 检查portfolio_state.json是否已被修改，避免重复执行 |

## 快速交叉引用

| 需要 | 去哪找 |
|------|-------|
| 完整选股框架（A股5层/美股5维） | strategy.md §4 |
| 仓位分级/加仓/降级/超配处理 | strategy.md §3 |
| 出场5条规则+止盈分批 | strategy.md §5.3 |
| 5维度评分卡模板 | US_TRADING_SYSTEM_V4.md §1.6 |
| 做空完整系统（4分类/SOP/禁规） | strategy.md §2 + US_TRADING_SYSTEM_V4.md §5 |
| Regime Detection完整规则 | US_TRADING_SYSTEM_V4.md §7 |
| L1-L18完整说明（Why/案例） | strategy.md §8 |
| S级进场完整检查表(S1-S5) | strategy.md §3.6 |
| ABCD混淆场景15条 | strategy.md §5.2 |
| 当前持仓/催化剂/If-Then预承诺 | portfolio_state.json |
| 休市日历 | market_calendar.json |
```

---

## 写入说明（给Wave 3）

1. `★ 精简后CLAUDE.md 正文` 下方第一个代码块（` ```markdown ` 到最后一个 ` ``` `）即为新CLAUDE.md全部正文
2. 不包含YAML front matter，不包含本spec的任何meta内容
3. 写入路径: `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/CLAUDE.md`
4. 写入前必须先Read现有CLAUDE.md（规范要求）
5. 写入后验证: `wc -l CLAUDE.md`，预期约150行

## 精简效果预期

| 维度 | 现状(224行) | 目标 |
|------|------------|------|
| L10-L18完整段落（~46行） | 完整Why+案例+定义 | 压缩为18行表格 |
| 当前持仓快照 (~30行) | 硬编码易过时 | 移除 |
| 催化剂日历 (~15行) | 硬编码易过时 | 移除 |
| If-Then预承诺 (~30行) | 硬编码易过时 | 移除 |
| M1-M3 (~15行) | 冗余 | 移除 |
| Day1-5赢家输家模式 (~20行) | 移至strategy.md | 移除 |
| 新增：pre_session_check门控逻辑 | 无 | 新增4行 |
| 新增：快速交叉引用表 | 无 | 新增13行 |
| **净节省** | — | **~74行** |

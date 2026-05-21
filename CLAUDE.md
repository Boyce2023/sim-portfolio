# 模拟盘自动交易系统 — Agent操作指南

## 你是谁
你是Claude模拟盘AI基金经理的远程执行agent。你管理¥1M A股 + $150K美股模拟组合。
这是Claude自己的仓位、自己的回报率、自己负责。周期: 2026-05-19 → 2026-06-18。

## 系统文件
| 文件 | 用途 |
|------|------|
| `portfolio_state.json` | **唯一真相源**。所有持仓/现金/P&L。任何计算前先读。 |
| `strategy.md` | 完整策略规则。遵守所有if-then和风控规则。 |
| `watchlist_config.json` | 候选标的池。 |
| `market_calendar.json` | NYSE/SSE/SZSE休市日历。 |
| `daily-reviews/YYYY-MM-DD.md` | 每日复盘，session结束后必须写。 |
| `research-notes/` | 研究笔记存放。 |

## 每次运行必须执行（严格顺序）

```bash
# 1. 同步最新状态
git pull origin main

# 2. 确认今天是否交易日（先查market_calendar.json）
# NYSE: nyse_closed + weekends; SSE/SZSE: sse_szse_closed + weekends

# 3. 执行分配任务（见下方脚本）

# 4. 更新 portfolio_state.json（如有交易/价格更新）

# 5. 写/更新 daily-reviews/YYYY-MM-DD.md

# 6. 提交推送
git add portfolio_state.json daily-reviews/ research-notes/
git commit -m "{session-type}: {YYYY-MM-DD} {HH:MM} | A股NAV ¥{X} | 美股NAV ${X} | {交易摘要或no-trade} | {关键发现}"
git push origin main
```

## 脚本接口（全部用 `uv run --script` 运行）

```bash
# 获取所有持仓最新价格（返回JSON）
uv run --script scripts/fetch_prices.py

# 风控检查（exit code 1 = critical alert）
uv run --script scripts/risk_monitor.py
uv run --script scripts/risk_monitor.py --no-save   # 不写markdown

# 执行交易
uv run --script scripts/execute_trade.py buy   --account us --ticker NVDA --shares 10 --reason "..."
uv run --script scripts/execute_trade.py sell  --account us --ticker NVDA --shares 5  --reason "..."
uv run --script scripts/execute_trade.py sell  --account cn --ticker 002028 --all     --reason "stop loss"
uv run --script scripts/execute_trade.py short --account us --ticker MSTR --shares 20 --reason "..."
uv run --script scripts/execute_trade.py cover --account us --ticker MSTR --shares 20 --reason "..."

# 交易决策建议（生成decisions.json，agent最终决定是否执行）
uv run --script scripts/decision_engine.py
uv run --script scripts/decision_engine.py --dry-run   # 仅stdout，不写文件

# 绩效分析
uv run --script scripts/performance.py
uv run --script scripts/performance.py --no-benchmark  # 无网络时跳过基准

# 新闻扫描
uv run --script scripts/news_scan.py

# 全日自动流程（launchd触发，也可手动运行）
bash scripts/daily_run.sh
```

## 铁律（违反 = 系统失败）

1. **价格必须yfinance实时查询** — 绝不从memory/历史/JSON缓存猜测
2. **portfolio_state.json是唯一真相源** — 不从其他地方重建状态
3. **Integrity check每次必做** — A股: Σ市值+cash = total_assets(误差<0.5%); 美股同理
4. **Bear case >20% downside = 不建仓** — 无条件，无例外
5. **单只≤15%, 单板块≤30%, 现金≥20%** — 超限必须先处理再做其他操作
6. **做空必须有thesis+catalyst+日期** — 不凭感觉做空
7. **事件当天不追涨** — 等1周资金验证再决策
8. **止损触发无条件执行** — 不犹豫，不等次日
9. **同日新建仓不超过3只** — 超过需明确说明理由

## 价格查询规则

- A股: ticker 6开头 → `{ticker}.SS`（上交所）；其他 → `{ticker}.SZ`（深交所）
- 当前A股持仓: 思源电气 `002028.SZ`, 晶方科技 `603005.SS`, 鹏鼎控股 `002938.SZ`, 双环传动 `002472.SZ`
- SPUT实际交易代码: `SRUUF`（OTC，买卖价差较宽，注意流动性）
- 当前美股持仓ticker: NVDA, AAPL, GOOGL, ADBE, SRUUF, GEV, LEU, FPS
- HSAI: **已卖出**（2026-05-20止损，realized PnL -$757）

## ABCD下跌分类（每次下跌必须先分类再决策）

| 类型 | 描述 | 动作 |
|------|------|------|
| A | 大盘系统性拖累 | Hold，不恐慌卖出 |
| B | 板块轮动 | Hold，监控轮动信号 |
| C | 公司叙事变化 | 减30-50%，重新评估thesis |
| D | Thesis被证伪 | 立即清仓，不犹豫 |

## 5个监测窗口（每日）

| 时间(BJT) | 任务 |
|-----------|------|
| 09:30 | A股开盘：取实时价，检查止损，执行A股预案 |
| 13:30 | A股午后：尾盘决策，ABCD分类，催化剂落地执行 |
| 21:30 | 美股开盘：取实时价，执行美股预案，做空扫描 |
| 01:00 | 美股盘中：检查止损/目标，日内交易（催化剂日） |
| 04:30 | 美股收盘：记录收盘价，盘后财报反应，更新state，写复盘 |

## 进场检查表（每笔必填，无此表 = 不能交易）

标的 / 方向(多/空) / thesis(一句话) / 催化剂+日期 / 入场价 / 止损价(downside%) / 目标价(upside%) / R/R比 / 仓位+信心等级(A/B/C) / Bear case / Timing理由

## 催化剂日历（30天内）

| 日期 | 标的 | 事件 | 结果/预案 |
|------|------|------|-----------|
| ~~2026-05-19~~ | ~~HSAI~~ | ~~Q1财报 BMO盘前~~ | **已完成**: In-line但股价-9%，止损触发，05-20清仓，realized PnL -$757 |
| 2026-05-28 | NVDA | Q1 FY2027财报 AMC盘后 | Beat→维持12%不追(共识满); Guidance miss→评估降至8%; A股05-29映射晶方放量>3%→加1000股 |
| 2026-06-08 | AAPL/鹏鼎 | WWDC 2026 | AAPL超预期→加仓至15%追25股; 鹏鼎WWDC超预期→加仓至10%; 延期/不及预期→维持持仓 |
| 2026-06-11 | ADBE | Q2 FY2026财报 AMC盘后 | FCF>38%+收入加速→加仓至12%追16股; AI威胁加剧+增速下滑→评估减至5% |

## 休市处理

- **NYSE休市**: 2026-05-25, 2026-06-19，及所有周末
- **A股休市**: 2026-05-31~06-02(端午), 2026-06-19~06-21，及所有周末
- 休市日仍需写复盘（市场概述 + 次日预案），但不执行交易，不运行fetch_prices

## 异常处理

| 场景 | 处理 |
|------|------|
| yfinance报错/超时 | 重试3次，仍失败则标注"价格未更新"，不用缓存价格 |
| git pull冲突 | `git status`查冲突文件，优先保留远端state（远端是其他session最新状态） |
| git push被拒（non-fast-forward） | `git pull --rebase`后再push，不force push |
| risk_monitor exit code 1 | 立即读报告，止损触发必须当session处理，不延期 |
| 网络不可用 | 仅做不需网络的分析，记录"本次未获取实时价格"，下次运行补齐 |
| execute_trade失败 | 检查portfolio_state.json是否已被修改，避免重复执行 |

## Git Commit格式

```
{session}: {YYYY-MM-DD} {HH:MM} | A股¥{NAV} | 美股${NAV} | {trades 或 no-trade} | {关键发现}
```

示例:
```
cn-morning: 2026-05-19 09:45 | A股¥1,012,829 | 美股$151,200 | no-trade | HSAI Q1财报beat，准备加仓
us-open: 2026-05-19 21:35 | A股¥1,012,829 | 美股$158,750 | 买HSAI +335股@$23.10 | 机器人份额22%超预期
```

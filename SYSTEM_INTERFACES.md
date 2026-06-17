# 美股系统 — 完整数据源/接口/互联清单 v1.0

> 2026-06-17。所有数据和操作都有现成接口。⛔禁止手搓yfinance python(会导致tool call解析崩溃)。
> 新session开局必读。路径根: ~/claude-projects/sim-portfolio/  脚本: scripts/  跑法: `uv run --script scripts/X.py`

---

## 一、数据源层(数字从哪来)

### 1. yf CLI — 美股/港股/韩股/日股行情(首选,纯命令无需python)
```
yf quote TICKER         价格/PE/PEG/市值/52周/beta/分红
yf fundamentals TICKER  EPS/营收/毛利/现金流(IS/BS/CF)
yf price TICKER         快速价格+涨跌
yf history TICKER 3mo   历史(1d/5d/1mo/3mo/6mo/1y/ytd/max)
yf compare T1,T2,T3     横向对比
yf macro                UST/DXY/VIX/油/金/BTC一屏
yf news TICKER          新闻头条
批量: for t in APH AEIS VST; do yf quote $t; done   ← 纯shell,不写python
全球后缀: 韩.KS / 港.HK / 日.T
```

### 2. FRED — 官方宏观(信用利差/实际利率/通胀/就业,yf拉不到的)
- 脚本: `scripts/fred_macro.py`(已接FRED API key,无限流)
- key在 `.env` 的 `FRED_API_KEY`(已gitignore)
- 代码: BAMLH0A0HYM2(HY OAS) / DFII10(10Y实际利率) / T5YIFR(5Y5Y) / SOFR/EFFR/IORB / SAHMREALTIME / ICSA / PCEPILFE(Core PCE) / WRESBAL
- 缓存: `data/fred_cache.json`(日级TTL)

### 3. 内部SSOT(状态,不从记忆推)
- **portfolio_state.json** ⭐持仓/现金/杠杆唯一真相源(美股在accounts.us)。⛔禁止直接写,必须走 `portfolio_io.save_portfolio()` 或 `execute_trade.py`
- ous_universe.json 持久跟踪宇宙 | ous_scan_results.json 扫描结果(Delta对比) | watchlist_config.json 观察池
- latest_prices.json 最新价缓存 | data/fundamentals_cache.json EPS/PEG缓存(90天TTL)
- leveraged_products.json 杠杆ETF速查 | market_calendar.json 休市日历

### 4. Nexus(跨session/跨市场)
- `~/.claude/nexus/signals/pending/` 跨市场信号(当前2条Trump待消费)
- `~/.claude/nexus/truth/` 结构化数据(portfolio/macro/companies)

---

## 二、脚本接口(按功能:干什么+命令+读写)

### 价格/状态
```
update_prices.py --market us       刷新美股价格→写portfolio_state(fast_info取价,已修滞后bug)
fetch_prices.py                    底层取价(US yfinance + CN Eastmoney)
portfolio_io.py                    load_portfolio() / save_portfolio(state, reason, auto_sync)
                                   save自动: session_view刷新→sync_nexus→git push
nav_calc.py                        NAV净值
risk_monitor.py --compact --no-save  风控
```

### 宏观(第一判断层)
```
macro_engine.py                    ⭐每日regime:方向/程度/置信/距硬触发. 提供get_regime()供import
  --refresh 强制刷新   --json 机读
fred_macro.py                      FRED官方数据拉取
research-notes/macro/_MACRO_FRAMEWORK.md      11域框架
research-notes/macro/_HISTORY_CALIBRATION.md  百年base rate(估值≠timing,贵≠脆弱)
research-notes/macro/_TRACKER_REGISTRY.md     tracker注册表
```

### 扫描/选股
```
ous_prescreener.py --all-sectors --peg-max 2 --min-cap 5 --json
                                   ⭐全市场FinViz预筛(已修:服务端PEG升序,不再只扫A打头)
us_ous_scanner.py --skip-f21       ⭐整批尽调(PEG+F9+供给侧+验证,读ous_universe)
  --ticker NVDA,AVGO 增量  --portfolio 只扫持仓  --discovery 全市场发现入临时池
us_peg_calculator.py [TICKERS]     PEG计算(被scanner合并)
us_data_validator.py               数据质量6层检查
us_universe_builder.py             NASDAQ宇宙构建(6010只)
earnings_rhythm.py                 F21 beat cycle
catalyst_calendar.py --portfolio   60天催化剂(earnings+FOMC+CPI+NFP)
humility_guard.py                  ⛔护栏:没拉价格不准输出"排除"
```

### 交易(扣扳机等用户本轮说go,T0铁律)
```
execute_trade.py buy/sell/short/cover --account us --ticker X --shares N --reason "..."
                                   ⛔不接受--price(yf实时取),自动sync+push
revert_trade.py                    撤销交易
exit_signal_detector.py            退出信号(暴力拉升/催化剂过)
```

### 信号/Nexus/跨市场
```
signal_consumer.py [--consume]     读pending信号+持仓交叉
trump_sync.py                      Trump/OGE持仓交叉
sync_nexus.py                      同步快照到nexus-package
news_scan.py                       新闻扫描
```

### ⛔用户说"push"的唯一动作
```
bash scripts/push_all.sh "msg"     sim-portfolio commit+push → sync_nexus → nexus-package(Railway公网)
```

---

## 三、互联/数据流(谁喂谁)

```
选股流: macro_engine(定姿态) → ous_prescreener(全市场候选) → us_ous_scanner(尽调) → 报告
宏观流: macro_engine → fred_macro → FRED API(.env key) + yf CLI → regime
        macro_engine 也被 decision_engine import(get_regime→杠杆带,只读defensive_recommendation/fired_triggers,绝不读direction/degree)
交易流: execute_trade → portfolio_io.save → session_view刷新 → sync_nexus → git push(自动)
状态流: update_prices → portfolio_state(SSOT) → 所有读持仓的脚本
跨市场: signals/pending → signal_consumer → 持仓交叉; 产出影响他市场→写signal到pending/
日跑: daily_run.sh(launchd 08:00 BJT): pull→maintain_truth→fetch_prices→update_prices→decision_engine→auto-stops→sync→push
```

---

## 四、⛔脚本铁律(防tool call崩溃 — 新session反复犯的)

1. **取数据用yf CLI / 现成脚本,绝不手搓yfinance python**
2. **绝不在 `python3 -c "..."` 里写多行缩进代码**(f-string+嵌套引号+缩进=必崩)。真要python: Write干净.py文件(4空格缩进)→Read验证→uv run
3. **一条Bash命令只做一件简单事**,串行没关系,复杂=脆弱=崩
4. **portfolio_state.json 绝不直接写**,走 `portfolio_io.save_portfolio()`
5. 数字全yf/FRED,WebSearch只查定性
6. 估值PEG的G标G1-G4来源,consensus不进估值

> 核心:所有想手搓的,系统都有现成接口——取价`yf quote`、批量尽调`us_ous_scanner.py`、全市场`ous_prescreener.py`,一个python都不用自己写。

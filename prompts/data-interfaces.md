# A股交易系统 · 数据源 + 接口 + 互联 完整清单

> 核实自实际系统(2026-06-17)。⛔所有接口签名/字段/路径从代码实际抠的,不是记忆,可直接调用。
> 改了脚本接口要同步改这里。

---

## 一、数据源层（用哪个源 + 铁律）

| 市场 | 主源 | 备源 | ⛔铁律 |
|---|---|---|---|
| **A股** 价格/市值/PE | `astock_data_layer`(push2delay.eastmoney ulist) | **tencent qt.gtimg**(EM被代理挡时自动兜底) | **禁import yfinance**(给A股市值少算10倍:宏和/鼎泰错过) |
| **A股** 全量/涨停/资金 | astock_data_layer(eastmoney 5861只/14秒) | akshare / baostock | — |
| **港股** | yfinance(.HK) | akshare境外不可用 | 见 memory/reference_hk_data_sources |
| **美股** | `yf`命令 / us_ous_scanner.py | — | A股session不碰 |
| **美股宏观** | FRED(`FRED_API_KEY` 在 sim-portfolio/.env) | — | macro_engine.py用 |
| **定性**(供给/竞争/催化) | WebSearch | — | ⛔WebSearch价格/PE全部视为未验证,必须yf/astock交叉验证 |

**数据宪法关键条(CLAUDE.md Operational Triggers):**
- **D12**: 取A股价格/市值/PE/PB/股本 → 一律astock_data_layer,禁yfinance。派agent必须prompt显式带这条(子进程不继承拦截器)。market_cap==0/None→先重取再用。
- **D10**: 用户问任何价格 → 先数据后嘴(astock/yf拿硬数字才开口)。
- **D8**: 估值 → PEG唯一,G标来源(G1-G4),卖方目标价/consensus不进估值链。
- **D2**: agent返回数字 → 交叉验证,confidence≥medium才入正文。

---

## 二、接口层（脚本+函数,可直接调用）

### ⭐ astock_data_layer.py（A股数据底层,最核心）
```python
import sys; sys.path.insert(0,'scripts'); import astock_data_layer as adl

adl.get_batch_prices(['600519','002049'])  # → {code:{...}} 批量,EM挂自动tencent兜底
adl.get_single_price('600519')             # → {...} 单只
adl.get_full_market(sort_by='f3', descending=True)  # → [全量5861只], f3=涨跌幅
adl.get_limit_up_stocks()                  # → {'20cm':[...], '10cm':[...]} 涨停分类
adl.get_strong_movers(threshold=5.0, min_turnover=5.0, min_market_cap=100.0)  # 强势股
adl.get_top_movers(n=50)                   # 涨幅TOP N(排除新股首日)
adl.get_market_stats()                     # → {total,up,down,limit_up_10/20,turnover_trillion...}
adl.bare_code('600519.SS')                 # → '600519'
adl.to_secid('600519')                     # → '1.600519'(沪) / '0.xxxxxx'(深北)
adl.is_cn_ticker('600519')                 # → True/False
```
**返回字段(20个,统一)**: `code/name/price/change_pct/change_amt/volume/turnover(亿)/turnover_rate/pe/high/low/open/prev_close/market_cap(亿)/circulating_cap(亿)/amplitude/market/suffix/source/timestamp`

### ⭐ portfolio_io.py（持仓SSOT读写,⛔唯一合法写入口）
```python
import portfolio_io
pf = portfolio_io.load_portfolio()                              # 读SSOT
portfolio_io.save_portfolio(pf, reason='...', auto_sync=True)   # ⛔唯一合法写,自动触发同步链
portfolio_io.revert_trades(['trade-id'], reason='...')         # 撤回交易
```
⛔**禁止直接写portfolio_state.json**。save_portfolio自动: session_view刷新 → sync_nexus(Railway) → git push。

### CLI脚本(uv run)
| 脚本 | 用途 |
|---|---|
| `astock_data_layer.py --stats / --limit-up / --strong / --tickers X` | A股数据CLI |
| `astock_session.py [--scan]` | 持仓仪表盘(持仓+风控+F20+TB一条命令) |
| `uass_scan.py [--date --top]` | 市场信号简报(涨停+龙虎+板块资金,发现工具非建仓) |
| `astock_regime.py` | A股Regime检测(量/小大盘/北向/两融/CSI300,写truth/macro) |
| `execute_trade.py buy/sell --account cn --ticker X --shares N --reason` | 交易执行(等go) |
| `revert_trade.py` | 撤回(全套联动) |
| `update_prices.py` | 价格更新(自动识别A股/美股时段) |
| `exit_signal_detector.py` | 退出信号(龙头崩R6c+暴拉T11+催化L11→写nexus) |
| `news_scan.py` | 新闻扫描 |
| `health_check.py` | ⭐扫描前置体检(数据链19项连通:数据源/UASS/脚本/SSOT/nexus互联,全绿才开扫) |

---

## 三、互联层（nexus跨系统总线 + 同步链）

### nexus结构（`~/.claude/nexus/`）
```
signals/          跨session信号
  pending/        未消费(开局必扫)
  processed/      已消费
  routing.json    ⭐workstream路由矩阵
  _schema.json    信号格式
truth/            结构化数据(给脚本读)
  portfolio/      positions / calls-log / trade-outcomes / shadow-portfolio
  macro/          astock_regime / regime / indicators / market_calendar_2026
  companies/      每标的一个json(002028.json...)
  personal/  _index.json
handoff/  sync/
```

### ⭐ workstream路由（routing.json,认名不认session）
- **4个workstream**: `research` / `trading_astock`(A股session) / `trading_us` / `tracking`
- 研究系统的 `target_price_change` 等signal自动路由给 trading_astock+trading_us+tracking。
- 发signal: 写 `signals/pending/sig-{YYYYMMDD}-{HHMMSS}-{from}-{描述}.json`,字段见_schema: `id/from/to/priority/type/title/content/action_required/truth_refs/related_signals/created_at/expires_at/lifecycle/read_by/acted_on/superseded_by`
- 优先级过期: critical 3天 / high 7天 / medium 14天 / low 30天。

### 同步链（一次save自动全链路）
```
execute_trade.py / portfolio_io.save_portfolio()
  └→ session_view刷新 → sync_nexus.py(快照→nexus-package) → Railway公网 → git push
```
- **`bash scripts/push_all.sh`** = 用户说"push"的唯一动作(sim-portfolio commit+push → sync_nexus → nexus-package)。
- **signal_consumer.py** = 读pending信号+持仓交叉+`--consume`标记已处理。
- **maintain_truth.py** = 宏观+regime+信号过期清理+持仓同步(daily_run.sh自动调)。
- **trump_sync.py** = Trump/OGE持仓交叉(pending signal来源)。

### SSOT优先级（冲突时谁说了算）
```
portfolio_state.json (持仓真相) > nexus/truth/ (脚本结构化) > memory/ (规则知识)
```

---

## 四、开局数据动作（按序）
1. `date` 锚定日期
2. `astock_regime.py` 看今日regime
3. `portfolio_io.load_portfolio()` 读持仓SSOT(不记忆推算)
4. 跑 `python3 scripts/consume_signals.py --workstream trading_astock` 消费research给我的信号(替代手动扫pending)
5. A股任何数据 → astock_data_layer,⛔不碰yfinance

## 五、trading_astock 信号收发（2026-06-17接入 | 权威协议 ~/.claude/nexus/signals/SIGNAL_PROTOCOL.md §2.1）

**消费**: 开局/需要时跑 `consume_signals.py --workstream trading_astock` → research给我的 thesis_update/catalyst/target_price_change/research_complete/regime。(美股Trump等signal路由给trading_us不给我=隔离正确,我消费=0是对的)

**发布(该发时, → research)**:
| 何时 | type(priority) | 字段(⛔禁量价) |
|------|------|------|
| 成交/开平加减仓 | execution_result(medium) | ticker+direction(开/平/加/减)+理由 |
| 盘中突发 | breaking_news(critical) | news_type/affected_tickers/headline/key_facts/source/immediate_action |
| 盘后复盘 | market_context(medium) | regime/key_indicator/affected_sectors(仅板块)/positioning |
| watchlist催化剂 | catalyst(high) | catalyst_type/ticker/timing/confidence/truth_refs |

**⛔持仓铁律**: 任何signal/写truth 绝不带 shares/avg_cost/market_value/pnl/stop_loss/cash/nav/positions。开平仓只用 direction+ticker 不带量。自检 `python3 scripts/verify_isolation.py`(daily_run gate,命中阻断推公网)。

---
*v1.0 | 2026-06-17 | 配套 astock-workflows.md(筛股SOP)。改脚本接口同步改本文件。*

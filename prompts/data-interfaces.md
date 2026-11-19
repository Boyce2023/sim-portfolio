# A股交易系统 · 数据源 + 接口 + 互联 完整清单

> 核实自实际系统（2026年06月17日）。⛔所有接口签名/字段/路径从代码实际抠的,不是记忆,可直接调用。
> 改了脚本接口要同步改这里。

---

## 一、数据源层（用哪个源 + 铁律）

| 市场 | 主源 | 备源 | ⛔铁律 |
|---|---|---|---|
| **A股** 价格/市值/PE | `astock_data_layer`(push2delay.eastmoney ulist) | **tencent qt.gtimg**(EM被代理挡时自动兜底) | **禁import yfinance**(给A股市值少算10倍:宏和/鼎泰错过) |
| **A股** 全量/涨停/资金 | `astock_data_layer`(eastmoney 5861只/14秒) | akshare / baostock | 无 |
| **A股** 涨停价/跌停价 | tencent qt.gtimg 字段 `[47]`/`[48]`(`b_auto_trade.quote` 返回 `zt`) | 比例兜底：北交所 30% / 创业板科创板 20% / 其余含 ST 主板 10% | ⛔2026年10月20日：ST 与北交所纳入策略后，涨停价一律读行情字段，不按旧印象写比例（ST 主板已由 5% 改 10%，当日实测 ST海王 1.32升至1.45）。北交所代码除 4/8 开头外还有 92 开头新段，腾讯前缀 `bj` |
| **A股** 指数实时 | `astock_data_layer.get_index_quotes`(tencent qt.gtimg) / CLI `--index` | 无 | 盘中EM push2/akshare指数接口常超时，腾讯源稳定兜底（06月18日修）。⛔代码必须带交易所前缀 `sh000300`/`sz399001`，不带前缀会一行都解析不出。失败一律返回 `{"_error": msg}`，调用方判 `if not r or "_error" in r`（09月16日修：原先解析全空时静默返回 `{}`，调用方看不出失败） |
| **A股** 全市场扫描 | `astock_data_layer.get_full_market()` | 无 | 返回 list[dict] 不是 dict。⛔09月16日加 `industry` 字段（东财 f100），此前字段表没请求它，导致5915只全部无行业、调仓的板块主线一栏永远是未知 |
| **A股** 批量取价 | `astock_data_layer.get_batch_prices()` | 无 | ⛔09月16日修 `to_secid`：沪市ETF（510/511/512/513/515/518/588）原按「6开头才是沪」被判成深市，东财查不到且静默返回 `price=None`。现 6开头 或 50/51/52/56/58 开头判沪 |
| **港股** | yfinance(`.HK`) | akshare境外不可用 | 见 `memory/reference_hk_data_sources` |
| **美股** | `yf`命令 / `us_ous_scanner.py` | 无 | A股session不碰 |
| **美股宏观** | FRED(`FRED_API_KEY` 在 `sim-portfolio/.env`) | 无 | `macro_engine.py`用 |
| **定性**(供给/竞争/催化) | WebSearch | 无 | ⛔WebSearch价格/PE全部视为未验证，必须 `yf`/astock交叉验证 |

**数据宪法关键条（AGENTS.md Operational Triggers）：**
• **D12**：取A股价格/市值/PE/PB/股本统一走 `astock_data_layer`，禁 `yfinance`。派agent必须prompt显式带这条（子进程不继承拦截器）。`market_cap==0`/`None`先重取再用。
• **D10**：用户问任何价格先数据后嘴（`astock`/`yf`拿硬数字才开口）。
• **D8**：估值PEG唯一，G标来源（G1至G4），卖方目标价/consensus不进估值链。
• **D2**：agent返回数字交叉验证，`confidence>=medium`才入正文。

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

⛔⛔ **盘前（09:15 前）这套接口全部不可用，2026年09月21日开盘前实测**：`get_tradable_market()` 与 `get_full_market()` **返回 0 只（空列表，不报错不告警）**。当天据此算出「20 只事件标的市值全为 n/a、射程内 0 只」，一度以为是字段缺失，实为**连股票都没返回**。⛔ 它静默返回 `[]` 会让调用方把「拿不到」当成「没有」，属 [[feedback_fault_must_shout]] 该治的形态。

⛔⛔ **2026年09月29日起 iFinD 已停用**（Buwen 确认停用）。`scripts/ifind_data_layer.py` 接口名和返回格式不变，底层改由 `scripts/cn_free_data.py`（腾讯加新浪双源互校）提供，返回 dict 多一个 `source` 字段：
• `history`：只要开高低收与成交量走免费日线（沪深腾讯为主新浪复核，北交所新浪），起止都是今天且过了 15:05 走双源快照另给 `amount`/`turnoverRatio`/`preClose`，历史区间还要其他字段返回错误码 `-9001`，调用方退到宝硕。
• `basic`：只支持 `ths_market_value_stock`，且请求日期必须等于行情日期（盘前即前一交易日收盘），值为腾讯快照的价格乘总股本，其余指标返回 `-9002`，PE/PB 用 `astock_data_layer.get_batch_prices`。
• `realtime`：双源快照。`snap_shot` 等直接接口返回 `-9000`，**竞价历史补采不再可用**（每日 09:14 的实时采集走腾讯，不受影响）。
• 9月29日实测：全市场快照 5540 只两源开高低收零差异，耗时 85 秒，历史日线抽 570 根、北交所 110 根对本地库零差异，价格库更新程序演练 5195/5198（3 只停牌），识别的 32 起除权除息均与腾讯分红记录一致。
• 恢复 iFinD 时设环境变量 `IFIND_ENABLED=1`。以下为 iFinD 时代原文，留作口径参考：

（原盘前走 iFinD 已停用）（`scripts/ifind_data_layer.py`，原 A股首选源）：
```python
import ifind_data_layer as I
I.basic('601869.SH,600487.SH', 'ths_market_value_stock', '2026-09-18')   # 批量, 逗号分隔
I.history('600737.SH', '2026-09-08', '2026-09-18')                        # 单只日线
```
• **批量实测**：200 只一批约 0.3 秒，全市场 5205 只两个日期 16.5 秒，返回数与请求数一致。
• **返回结构**：`d['tables'][i]['table'][指标名]` 是**数组**，`d['tables'][i]['time']` 是对应日期数组，顶层有 `errorcode`（0 为成功）与 `errmsg`。⛔不是 DataFrame 也不是扁平 list，直接当 list 遍历会拿到包装元素。
• **已验证可用指标**：`ths_close_price_stock` / `ths_pe_ttm_stock` / `ths_pb_latest_stock` / `ths_market_value_stock`（单位元，除 1e8 得亿）。
• **额度**：`basic`/`history`/`realtime` 走常规桶，只有 `snap_shot` 走高频桶且容易打满，见 [[reference_ifind_quota_limits]]。
• ⛔⛔ **解释器：三个 python 三种能力，选错报 ModuleNotFoundError**（2026年09月21日实测，当天写错三次）：

| 解释器 | 版本 | pandas | pyarrow | requests | akshare | 用途 |
|---|---|---|---|---|---|---|
| `/opt/homebrew/bin/python3.13` | 3.13.14 | 2.3.3 | 25.0.1 | 有 | 有 | ⭐**全功能锚定版（防 Homebrew 升级漂移，所有 launchd 与 parquet/回测统一锁死它）** |
| `/opt/homebrew/bin/python3` | 3.13.14 | 2.3.3 | 25.0.1 | 有 | 有 | 2026年10月软链已切回 3.13.14，但随 brew upgrade 可能漂移，生产任务优先写 `python3.13` |
| `/usr/bin/python3` | 3.9.6 | 2.3.3 | **无** | 2.32.5 | 1.18.64 | 联网抓取（`news_layer.py`），⛔**读不了 parquet** |

⛔ **根因**：homebrew 在 2026年09月把 `python3` 软链从 3.13 指到 3.14.7，而 3.14 的 `site-packages` 是空的。**库没消失，是脚下的解释器被换了。** 09月18日用 `/opt/homebrew/bin/python3` 成功读了十几次 parquet，09月21日同一条命令报 pandas 不存在，就是这个原因。

⛔ **判据：换解释器前先跑 `-c "import pandas, pyarrow"` 验证一次，三秒钟的事，比写三遍规则便宜。** 同族 `pending_verdicts` #67（main 报 consensus 坏在 py3.9 与 3.13 混用）。

### ⭐ portfolio_io.py（持仓SSOT读写,⛔唯一合法写入口）
```python
import portfolio_io
pf = portfolio_io.load_portfolio()                              # 读SSOT
portfolio_io.save_portfolio(pf, reason='...', auto_sync=True)   # ⛔唯一合法写,自动触发同步链
portfolio_io.revert_trades(['trade-id'], reason='...')         # 撤回交易
```
⛔**禁止直接写portfolio_state.json**。save_portfolio自动: session_view刷新 → sync_nexus(仅本地快照, 2026年11月09日已停用Railway推送) → git push。

### CLI脚本(uv run)
| 脚本 | 用途 |
|---|---|
| `astock_data_layer.py --stats / --limit-up / --strong / --tickers X` | A股数据CLI |
| `astock_session.py [--scan]` | 持仓仪表盘(持仓+风控+F20+TB一条命令) |
| `uass_scan.py [--date --top]` | 市场信号简报(涨停+龙虎+板块资金,发现工具非建仓) |
| `astock_regime.py` | A股Regime检测(量/小大盘/北向/两融/CSI300,写truth/macro) |
| `execute_trade.py buy/sell --account cn --strategy-id <s_high/s_3to4/s_1to2/s_pry/s_2to3> --ticker X --shares N --reason` | 交易执行（等go，四大核心主要策略 `s_3to4`/`s_high`/`s_2to3`/`s_1to2` 加唯一实盘辅助小策略 `s_pry`，全局五顺位 `三进四＞高标＞超跌撬板＞二进三＞一进二` 不变，`s_fund` 已彻底废止删除，`s_4to5` 已下放 astock2 研发不上实盘，物理隔离锁：同票跨策略混买硬拦截加卖出归属 `strategy_id` 不一致硬拦截加机械短线策略禁用通用跌12%止损串台） |
| `revert_trade.py` | 撤回（全套联动） |
| `update_prices.py` | 价格更新（自动识别A股/美股时段） |
| `exit_signal_detector.py` | 退出信号（龙头崩R6c、暴拉T11、催化L11写入nexus） |
| `python3 news_layer.py` | ⭐A股消息面数据层（Step0内部源：隔夜美股SOX/纳指加财联社/新浪/见闻/东财快讯12h加政策头条，关键词critical/high/medium评分，命中持仓加15、watchlist加8，写 `data/news_today.json`，NO_PROXY直连，timeout=8s，单源失败skip不崩） |
| `python3 watch_tracker.py [--all/--signal]` | ⭐T16 watch失效期跟踪（读 `scan_history.jsonl` 最新watch裁决与 `portfolio_state` 及腾讯 `qt.gtimg` 实时价，输出买点到位/突破触发/失效到期/需人工补，不许挂空，默认只报需行动，`--signal` 写 `signals/pending/`，新裁决带 `watch_expiry` 字段优先，否则正则解析 `one_line`） |
| `news_scan.py` | 新闻扫描 |
| `health_check.py` | ⭐扫描前置体检（数据链19项连通：数据源/UASS/脚本/SSOT/nexus互联，全绿才开扫） |
| `/opt/homebrew/bin/python3.13 scripts/auto_factor_miner.py [--board 1..5 --mode all/open/daban --top N]` | ⭐A股自动化零前视镜因子挖掘器（2026年11月09日新增：内置训练集21至24与样本外24至26盲测、按日等权、剔一字含炸板、扣千三摩擦及近5年/近3年/近1年全期正超额四道防伪硬门槛） |
| `/opt/homebrew/bin/python3.13 scripts/sync_notices_db.py [--recent / --start YYYY-MM-DD]` | ⭐东财全市场A股公告库同步引擎（写入 `backtest/2026-08-24-daban/notices.db`，支持自然日全量补齐与 `--recent` 近8天滚动增量） |
| `/opt/homebrew/bin/python3.13 scripts/fast_1to2_today.py [--sync-all / --build-cache / --premarket]` | ⭐一进二生产主策略定版 **V19 互学升级引擎**（五年97笔/338.37倍单仓/54.57倍千万封顶/65.74倍全信号等权/68.04%胜率/2.87盈亏比/15.97%回撤/HLZ t=4.08/DSR=0.9945/PBO=6.75%/2026年21笔80.95%胜率3.15倍，常规304.8分/高潮329.8分/第2或3主线低位暗牌候补轨 `fb_dom295` 295.0分，封死二板次日跌6.5%至涨2.5%且雪球少于4帖且封成比低于25%豁免10:30弱斩留至15:00之M1规则，11:30未点火撤单，16:30与08:45构建 `1to2_premarket_cache.json`） |
| `/opt/homebrew/bin/python3.13 scripts/fast_high_dragon_today.py [--build-cache / --premarket / --hold X]` | ⭐高标首阴真阳反包主策略 V5.1 定版引擎（方案甲：42笔/16.39倍单仓与等权/73.8%胜率/3.01盈亏比/15.9%回撤，只做全场第一高满4板首断真阳且换手不超35%，融合开盘啦老妖记忆与龙虎榜游资22因子满88分，09:25平红开直买加绿开同花顺1.015上午条件单，自动输出10日100%与30日200%双严重异动93%可视限价止盈挂单价） |
| `/opt/homebrew/bin/python3.13 scripts/fast_3to4_today.py [--build-cache / --premarket / --hold CODE [--buy-date YYYY-MM-DD] / --mock-open / --date / --recent]` | ⭐三进四主战策略 **V4.1 引擎**（第1顺位，底分78分22项整数打分，标准90/S档102分，10:30突破买点；V4.1 卖点核查 `--hold`：盘前核对7项正交持仓风险因子，命中任1项时 `13:45` 后摸涨8.5%回落破7.0%锁利，0命中维持破5.0%；五年95笔胜率68.42%/盈亏比2.19/单仓2319.09倍/等权5644.80倍/去前五134.19倍/回撤29.23%/HLZ t=4.20/DSR=0.9869/PBO=3.57%与0.0%/近三年58笔72.41%净值581.22倍/2026年18笔66.67%净值3.74倍/102S档31笔64.52%盈亏比3.13单仓17.73倍） |
| `/opt/homebrew/bin/python3.13 scripts/fast_pry_today.py [--build-cache / --premarket / --hold CODE [--buy-date YYYY-MM-DD] [--buy-px FLOAT] / --date / --recent]` | ⭐唯一实盘辅助小策略：超跌橡皮筋撬板次日弱转强 **V2.1 引擎**（`s_pry`，第3顺位，满165分/S档175分，09:25 0.00%至5.00%直买头名；`--hold` 核查 V2.1 四步动态阶梯卖点：回封跌停次日09:25斩、涨停转连板、09:25竞价涨停<5家清仓、T+1放飞涨停及强阳CLV>=0.70免14:55跌超1.5%弱斩且止盈+3%、昨跌停<10家+3%封顶18%、T+2起动态阶梯至T+4清仓；165分16笔胜率87.50%/2.44倍/25日等权3.81倍/去前三1.46倍/回撤19.15%） |
| `/opt/homebrew/bin/python3.13 scripts/fast_2to3_today.py [--build-cache / --premarket / --strict / --hold CODE / --mock-open / --as-of / --date / --recent]` | ⭐第四核心主战策略：二进三 **V2.1 迷茫暗牌弱转强引擎**（`s_2to3`，第4顺位，底分60分18项打分，标准90分/重点提醒96分，09:25直买头名，未封持至次日14:55/15:00清仓；`--hold` 核查 V2.1 卖点：封3板及反包连板极高开超9.2%于09:25止盈，`13:45` 后摸涨8.5%回落破6.5%锁利+首真阳免死1次；完备5m 95笔胜率52.63%/盈亏比4.37/单仓313.87倍/等权247.62倍/去前三65.19倍/回撤28.68%/HLZ t=4.22/DSR=0.9868/2026年14笔64.29%净值4.64倍，官库94笔157.85倍，96分完备5m 35笔54.29%/盈亏比6.62/23.36倍/回撤15.87%，官库18.54倍） |
| `/opt/homebrew/bin/python3.13 backtests_astock2/fast_4to5_today.py [--build-cache / --premarket / --recent]` | ⭐四进五 V2.0 高严档研发观察引擎（`s_4to5`，已下放astock2研发池独占管辖不上实盘，满120分，开盘涨2.0%至7.5%直买甜区加双严重异动较紧余量满12%加七维纯整数打分，未封真阳原地移交高标首阴，封死五板禁挂93%异动单改走13:45破5.0%护利） |
| `/opt/homebrew/bin/python3.13 scripts/daily_3strategies_score_report.py` | ⭐五大实盘策略（四大核心主战加唯一实盘辅助超跌撬板）每日全量打分榜与早盘复盘总控（按全局五顺位 `三进四 V4.1 ＞ 高标首阴 V5.1 ＞ 超跌撬板 V2.1 ＞ 二进三 V2.1 ＞ 一进二 V19` 输出全池及二进三满96分顶部单独重点提醒，并按滚动夏普输出唯一 `09:26` 挂单卡） |

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

### ⭐ workstream路由（`routing.json`，认名不认session）
• **4个workstream**：`research` / `trading_astock`（A股session） / `trading_us` / `tracking`
• 研究系统的 `target_price_change` 等signal自动路由给 `trading_astock`、`trading_us` 与 `tracking`。
• 发signal：写 `signals/pending/sig-{YYYYMMDD}-{HHMMSS}-{from}-{描述}.json`，字段见 `_schema`：`id/from/to/priority/type/title/content/action_required/truth_refs/related_signals/created_at/expires_at/lifecycle/read_by/acted_on/superseded_by`
• 优先级过期：critical 3天 / high 7天 / medium 14天 / low 30天。

### 同步链（一次save自动全链路）
```
execute_trade.py / portfolio_io.save_portfolio()
  └→ session_view刷新 → sync_nexus.py(快照→nexus-package) → 本地快照(Railway已停用) → sim-portfolio git push
```
• **`bash scripts/push_all.sh`** = 用户说「push」的唯一动作（`sim-portfolio` commit+push、sync_nexus、`nexus-package`）。
• **`signal_consumer.py`** = 读pending信号加持仓交叉加 `--consume` 标记已处理。
• **`maintain_truth.py`** = 宏观加regime加信号过期清理加持仓同步（`daily_run.sh` 自动调）。
• **`trump_sync.py`** = Trump/OGE持仓交叉（pending signal来源）。

### SSOT优先级（冲突时谁说了算）
```
portfolio_state.json (持仓真相) > nexus/truth/ (脚本结构化) > memory/ (规则知识)
```

---

## 四、开局数据动作（按序）
1. `date` 锚定日期
2. `astock_regime.py` 看今日regime
3. `python3 scripts/macro_pipe_cn.py` 观点管道：读美股宏观至A股传导（超阈值才覆盖，平时国内为主）
4. `portfolio_io.load_portfolio()` 读持仓SSOT（不记忆推算）
5. 跑 `python3 scripts/consume_signals.py --workstream trading_astock` 消费research给的信号（替代手动扫pending）
6. A股任何数据走 `astock_data_layer`，⛔不碰 `yfinance`

> 自上而下认知（先水位、主线、个股）与守仓三纪律见 `memory/knowledge_astock_mainline_warfare.md`

## 五、trading_astock 信号收发（2026年06月17日接入 | 权威协议 `~/.claude/nexus/signals/SIGNAL_PROTOCOL.md` §2.1）

**消费**：开局/需要时跑 `consume_signals.py --workstream trading_astock` 读research给的 thesis_update/catalyst/target_price_change/research_complete/regime。（美股Trump等signal路由给 `trading_us` 不给A股属隔离正确）

**发布（该发时，发给 research）**：
| 何时 | type(priority) | 字段(⛔禁量价) |
|---|---|---|
| 成交/开平加减仓 | execution_result(medium) | ticker+direction(开/平/加/减)+理由 |
| 盘中突发 | breaking_news(critical) | news_type/affected_tickers/headline/key_facts/source/immediate_action |
| 盘后复盘 | market_context(medium) | regime/key_indicator/affected_sectors(仅板块)/positioning |
| watchlist催化剂 | catalyst(high) | catalyst_type/ticker/timing/confidence/truth_refs |

**⛔持仓铁律**：任何signal/写truth绝不带 shares/avg_cost/market_value/pnl/stop_loss/cash/nav/positions。开平仓只用 direction+ticker 不带量。自检 `python3 scripts/verify_isolation.py`（daily_run gate，命中阻断推公网）。

---
*v1.0 | 2026年06月17日 | 配套 `astock-workflows.md`（筛股SOP）。改脚本接口同步改本文件。*

## iron_rules.py（2026年08月26日建，08月27日维护补录·S12）
两条铁律（Buwen 08月26日亲定）的可执行实现。买入gate（`execute_trade` Gate9）/卖出复核（`portfolio_trend_check`）/扫描深研共用。
• `rule1_earnings_reaction(code, disclose_date, as_of=None) -> dict`
  铁律1：财报披露后股价跌等于不及预期，只看价格不看财报数字。
  返回：`verdict`（`'MISS'`/`'BEAT'`/`'UNKNOWN'`/`'PENDING'`） / `chg_1d/3d/5d/todate` / `reaction_in_disclose_bar`（盘前发判别：披露日跳空满2%或涨满5%叠加2倍量使base前移） / `bars_after` / `intraday_last_bar`
  ⛔`disclose_date` 必须来自 `ak.stock_report_disclosure(market="沪深京",period="2026半年报")` 的「实际披露」列，禁手填（08月27日实测手猜9个错5个）
• `rule2_long_decline(code, as_of=None, window=40, thresh=-15.0) -> dict`
  铁律2：长跌等于基本面有问题（但不等于不能买）。返回 `chg_window`/`declining`/`msg`
• 数据源：腾讯ifzq日K加 `astock_data_layer` 实时价补当日bar（带真实OHLC，防假跳空）

## us_disaster_check.py（2026年09月08日建，09月29日加自动挂单·S12）
美股灾难线（成本乘0.88）检查，由 `daily_run.sh` Step 3b3.5 调用。
• `--notify`：击穿/漏检/价格不新鲜时写 `~/.claude/session-inbox/us.jsonl`
• `--enqueue`（09月29日新增，`daily_run` 已默认带）：击穿且价格日等于最近已收盘交易日时，写 `pending_orders`（走 `portfolio_io`），由同一轮 Step 4b2 执行。首日在线下减半（`kind=halve`, `shares=持仓//2`），前一交易日收盘也在线下清余仓（`kind=clear`, `shares=null` 走 `--all`）。挂单带 `source=us_disaster_check`、`close_date`。
• `--dry`：配合 `--enqueue`，只打印计划挂单不写文件（验证用）
• 幂等文件 `sim-portfolio/.disaster_state.json`：`{ticker: {close_date, action, line}}`，同一收盘日不重复挂，上一轮遗留的本脚本挂单在下一轮开头撤掉。收盘日之后 `trade_log` 里已有该票卖出成交（手工执行过）的，自动视为已处理不再挂单。
• 退出码：0=全查完无击穿 / 1=有击穿 / 2=无法判断 / 3=检查不完整

## 开盘啦异动提醒数据（2026年10月19日加）
• 脚本 `scripts/kpl_archive.py`，launchd `com.claude.kpl-archive`（09:45 与 14:40 存临界名单，15:25 全量：严重异动历史增量加重点监控），日志 `/tmp/kpl_archive.log`
• 落地 `data/kpl/`：`severe_his.json`（严重异动历史，2023年02月起，增量合并不删旧行） / `pianlizhi/YYYYMMDD_HHMM.json`（今日涨到涨停即触发严重异动的临界名单） / `zdjk/YYYYMMDD.json`（重点监控）
• 接口是开盘啦 App 自用未公开接口，字段与取法见 memory `reference_kaipanla_api.md`，返回空或 errcode 非 0 即飞书报警并退出码 2

## astock_data_layer.py 全市场腾讯批量兜底与 b_watch_build.py 真实自由流通字段（2026年10月21日加·S12）
• `astock_data_layer.get_full_market()` 新增 `_fallback_full_market_tencent()`：当 Eastmoney `push2delay` 断连或返回不足 4800 只时，自动读取 `data/cn_hk_price_db/universe_codes.json`（5209只全市场代码与行业缓存）走腾讯 `qt.gtimg.cn` 分批拉齐（耗时约 0.8s，`source='tencent_batch'`），同时修复 `_fallback_tencent` 中 `f[39]`（PE）与 `f[44]`（流通市值）的字段映射。
• `scripts/b_watch_build.py` 新增 `get_lockup_pct(code)`（缓存于 `data/cn_hk_price_db/sh_lockup_cache.json`），候选字典新增 `free_mcap`（真实自由流通市值，亿）、`lock10_pct`（前十股东锁仓比，%）、`true_turn`（真实自由换手率，%）、`首板真实自由市值`，顶层新增 `five_plus_t1_pool`（五板及以上次日 `T+1` 开盘博弈池）。

## astock_intraday_check.py 盘中1秒异动与竞价核查单命令（2026年10月29日加·S12）
• 路径：`scripts/astock_intraday_check.py`（纯标准库并发请求，零第三方依赖，纯只读不写盘，实测耗时约 0.4 至 0.6 秒）。
• 用法：`python3 scripts/astock_intraday_check.py 600838 000678 [--json]`
• 功能：①拉腾讯实时快照（现价、今开涨幅、买一卖一量、涨跌停硬字段 `f[47]`/`f[48]`、换手率、流通市值），②按沪深交易所精确基准指数（沪主板对标上证A指 `sh000002`、科创板对标科创50 `sh000688`、深主板对标深证A指 `sz399107`、创业板对标创业板综 `sz399102`）硬算今日与明日预演的 10日100% / 30日200% 严重异动红线、98%线、93%提前线及今日安全收盘上限价，③拉东财公告核查近10个交易日「股票交易异常波动公告」次数，预警满4次同向严重异动。


## quant_4bucket_engine.py A股四分仓自动执行与日终零漏单对账引擎（2026年10月29日加·S12）
• 路径：`scripts/quant_4bucket_engine.py`（锁死 `#!/opt/homebrew/bin/python3.13`，launchd 任务 `com.claude.quant-4bucket`，日志 `/tmp/quant_4bucket.log`，旧 `com.claude.b-auto-trade` 已退场停用，`strategy1_exit.py` 与 `auto_stop_check.py` 已硬隔离 `book=='quant_4bucket'`）。
• 独立台账与 SSOT 双写闭环：台账 `data/quant_4bucket_ledger.json`（四桶独立现金、持仓、成交、胜率与每日信号核查记录）与 `portfolio_state.json`（经 `portfolio_io.save_portfolio()` 唯一入口写盘，同步刷新 `session_view_*.json`、沪深300基准与 Railway，且修复 `execute_trade.py` 全部 8 处 `TRD-XXXX` 单号递增碰撞缺陷）。
• 日线滞后自动缝合与价格库双时点：当 `a_daily.parquet` 因宝硕未出当日线而滞后 1 至数日时，引擎自动用腾讯实时快照 `f[4]`（昨收）加并发 `fqkline` 补齐缺失交易日收盘价与换手率，`MA10`、`20日均换手` 与 `3连跌停` 判定零滞后，同时 `com.claude.cn-price-db` 改为每日 `15:40` 与 `18:15` 双时点运行，打破跨日滞后死锁。
• 子命令：
  1. `open [--dry-run] [--force]`（`09:26`）：扫描并自动执行第3桶（主板10cm连续满3跌停且前20日0涨停、无ST退市立案红旗、非一字跌停开盘）与第4桶（五板手册锁仓满50%且开盘不超涨5.5% / 满4板断板首日涨2%至7.5%真阳反包且板块涨停活口 / 全场唯一满4板独苗且板块满2涨停）。
  2. `intraday [--dry-run]`（`09:35至14:45` 每10分钟）：监控 `T+1` 已解锁持仓止盈（第1与2桶 `+4.0%`、第3桶/反包 `+5.0%`、五板/独苗对标交易所指数的 10日100%/30日200% 严重异动 `93%` 提前止盈线）。
  3. `tail --phase exit|buy|both [--dry-run]`（`14:55` 到期平仓，`14:57` 全市场 5209 只扫描第1桶与第2桶尾盘真阳线自动建仓，快照不足 4500 只即 `fail-closed` 飞书告警）。
  4. `reconcile [--dry-run]`（`15:08`）：核验四桶现金与持仓对 SSOT 零误差、更新当日 `sh000300` 沪深300净超额快照、落盘 `data/eod_done/YYYYMMDD` 与 `YYYYMMDD_close.json` 并推送飞书日终回执。
  5. `status`：只读打印四桶实时权益、持仓浮盈亏与胜率。

## industry_earnings_brief.py 全市场行业财报业绩全景监控（2026年11月02日加·S12）
• 路径：`scripts/industry_earnings_brief.py`（已接入 `scripts/daily_brief_gen.py`，随 `com.claude.astock-brief` 每日 `07:15` 自动运行，交易日同步推送飞书晨报）。
• 数据源：东财财报中心一手季报库 `http://datacenter-web.eastmoney.com/api/data/v1/get`（`RPT_LICO_FN_CPD`，强制直连 `NO_PROXY='*'` 防代理解析超时），按申万二级行业（样本数不少于 8 家）聚合归母净利润同比中位数、营收同比中位数、盈利增速为正占比及近 24 小时新披露家数。
• 产出：缓存 `data/industry_earnings_latest.json`，并注入 `daily_brief_YYYYMMDD.md` 顶部全景摘要（行业净利同比中位数前五强、后五弱及白酒Ⅱ等重点行业跟踪）。


## us_jump_tracker_daily.py 美股全时间段近半年跳涨监测活表更新引擎（2026年11月09日加·S12）
• 路径：`scripts/us_jump_tracker_daily.py`（锁死 `/opt/homebrew/bin/python3.13`，launchd 任务 `com.buwen.us-jump-tracker`，每日 `08:20` CST 自动运行，日志 `sim-portfolio/logs/us_jump_tracker.log`）。
• 目标活表：`~/Desktop/Track/1_活表/1_选股_美股2026中报财报日涨跌.xlsx`（支持 `--dry /tmp/out.xlsx` 干跑检验）。
• 数据源与口径：合并 `data/us_price_db/prices/*.parquet`（1392 只）加 NASDAQ 实时 50 亿美元以上美股池，扫描滚动近半年（183 天）全时间段收盘对收盘涨幅不低于 10.0% 的单日跳涨（自动过滤未复权拆股与次日无量反向假打印），交叉核验 NASDAQ 官方财报日历与 SEC EDGAR `8-K Item 2.02` 精确分钟级时间戳及 `10-Q/10-K reportDate`，在 D 列「财报季」标明 `26Q1`/`26Q2`/`26Q3`/`26Q4`（非财报跳涨留空），季报营收经 `financialCurrency` 实时汇率折算为百万美元（USD）。
• 无损写盘机制：缓存目录 `data/us_jump_tracker_cache/`（永久固化用户红字代码、黄底代码、`A2` 批注、`J2/L2` 阈值及 `U` 列手写笔记），采用 ZIP 容器字节级直写，仅重算替换 `sheet1.xml`、`sheet2.xml`、`sheet4.xml` 并追加 `sharedStrings.xml`，对用户自建的 `股价复盘`（含图表 `chart1.xml`）与 `SaaS界面`（含 5 张截图）保持 SHA256 零字节漂移。


## fast_1to2_today.py 与 sync_notices_db.py 一进二定式生产主策略 V19 互学升级与 1 秒极速裁决管线（2026年11月17日定型·S12）
• **解释器与定时守护**：统一锁死 `/opt/homebrew/bin/python3.13`（严禁 `import yfinance`，所有 SQLite 严格 `mode=ro` 只读连接），LaunchAgent `com.claude.1to2-premarket-sync`（`~/Library/LaunchAgents/com.claude.1to2-premarket-sync.plist`）接管为 6 轮滚动同步，日志 `/tmp/rd_master_trading_sync.log`。
• **跨会话联动永久铁律**：一进二主策略每次更新定版时，必须同步发消息通知 `astock2` 会话将一进二盘感刷题机题库（`astock_exam_bank.json`）与全部 HTML 界面同步重刷更新，确保生产策略与盘感训练题库 100% 逐笔对齐。
• **现役核心定版规则（V19 互学升级版，97笔 / 338.37倍单仓 / 54.57倍千万封顶 / 65.74倍等权 / 68.04%胜率 / 2.87盈亏比 / 15.97%回撤）**：
  1. **规则 α（断层主线禁退第三题材）**：第1题材先验中位数领先第2题材满20分（或规模满6家且达2倍），且第1题材内无过线股时，允许退选第2题材，严禁买入第3题材标的（`rk_theme == 3`），
  2. **规则 β（三大题材混战日卡全场前二或硬催化）**：前三大题材极差在15分以内且规模均在2至5家混战时，候选股必须满足全场可买高开排名前二（`buyable_mkt_open_rk <= 2`）或具备公告硬催化/并购重组，
  3. **规则 γ（前视生态弱开传感器）**：前1日严格前视滚动前20个交易日高开满5.5%二板封板率低于45%时，周二至周五开盘不足3.5%弱开票扣分上调至25分（否则不足3.1%扣15分），
  4. **V18 纯打分去一刀斩**：硬科技纯外行无并购重组扣20分，好名字零虚加分，伴生一字且总流值超90亿扣25分，昨封板率满80%再扣10分，一超两弱第3题材起扣15分，前日涨停满95/100家扣10/15分，
  5. **V19 互学升级①（低位暗牌候补轨 `fb_dom295`）**：主轨与周一通道无票时，第2或第3主线可买竞价头名若满足盘前雪球少于4帖、启动前20日箱体分位不超40%、具硬催化或新词火花且零拉萨一日游席位，去主线压制分满 `295.0` 分作低优先候补，
  6. **V19 互学升级②（封死二板次日 M1 豁免）**：封死二板次日开盘落在跌 `6.5%` 至涨 `2.5%`、盘前雪球少于4帖且二板封成比低于25%（或缺失）时，豁免 `10:30` 破分时均价线弱斩，留至 `15:00` 未封清仓，
  7. **过线门槛**：常规总分门槛 `304.8分`（题材45，周一空仓放宽 `38/304.8`，昨一进二封板率超75%高潮次日提至 `329.8分`，候补 `295.0分`），盘中点火 `max(昨收*1.065, 今开*1.012)`，`11:30` 未触发撤单。
• **`scripts/sync_notices_db.py`（东财全市场A股公告库增量同步引擎）**：
  1. 数据库路径：`backtest/2026-08-24-daban/notices.db`（表 `notice(code, name, title, ntype, ndate)`，索引 `ix_nd`, `ix_nc`，进度表 `done(d, n)`）。
  2. 签名：`/opt/homebrew/bin/python3.13 scripts/sync_notices_db.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--recent] [--force] [--workers 4]`。
  3. 机制：按自然日分页拉取东财 `http://np-anotice-stock.eastmoney.com/api/security/ann`，仅提取 `ann_type` 含 `A` 的真实A股代码（剔除指数关联与转债噪音），核验条数匹配后幂等去重，`--recent` 模式每次刷新近8个自然日，确保晚间/周五预标公告零遗漏。
• **`scripts/fast_1to2_today.py`（一进二定式现行定版预缓存与盘中 1 秒极速引擎）**：
  1. 缓存路径：`data/1to2_premarket_cache.json`，人工优先新词表：`data/1to2_priority_terms.json`。
  2. 全量底座路径：`data/cn_hk_price_db/a_daily.parquet`、题材合并唯一真源 `data/kpl_plates_2018_2026_merged.jsonl`、公告库 `notices.db` 与 `data/cninfo_notices_5y_pit.db`（严格 `?mode=ro`）、社区情绪库 `data/xueqiu_guba_5y_pit.db` 与 `data/astock_community_5y_pit.db`、封板微观库 `data/zt_micro_tape_5y_pit.db`、归档 `data/xueqiu_concepts_daily/YYYY-MM-DD.json` 与 `data/ths_limit_up_daily/YYYY-MM-DD.json`。
  3. 四种运行模式：`--sync-all`（全链路增量同步与缓存构建）、`--build-cache`（计算滚动 `Elo`、先验分与底分写入缓存）、`--premarket`（`09:00 / 09:15` 秒看候选与门槛）、默认无参数（`09:25:03` 读缓存加腾讯实时竞价秒算总分、候选轨道与点火买价）。

• **`scripts/fast_3to4_today.py`（三进四主战策略 V4.1 现行生产定版盘前预演、09:25:03 决策与 `--hold` 持仓风控引擎·2026年11月18日定型）**：
  1. 缓存路径：`data/3to4_premarket_cache.json`，买点升级真源：`backtests_astock/clean_3strategies_mutual_upgrade_20261117/`，V4.1 卖点实证真源：`backtests_astock/exit_factors_v2_20261118/f1_3to4/{summary_3to4_exit_factors.json,report_3to4_exit_factors.md}`，算分内核：`scripts/live_3to4_v40_engine.py`。
  2. 全量底座路径：`data/cn_hk_price_db/a_daily.parquet`、`data/ths_limit_up_daily/YYYY-MM-DD.json`、`pit_top10_all_codes.json`、`notices.db` 与 `cninfo_notices_5y_pit.db`（只读 `mode=ro`）、`lhb_buy.parquet` 与 `lhb_sell.parquet`、`data/xueqiu_guba_5y_pit.db`、`data/kpl_plates_2018_2026_merged.jsonl`、`index_klines_5y_cache.json` + 腾讯 `sh000300`。
  3. 运行模式与 V4.1 卖点字段（`--build-cache` / `--premarket` / 默认无参数 / `--hold CODE [--buy-date YYYY-MM-DD]` / `--date` / `--recent` / `--mock-open`）：买点维持底分78分22项整数打分（标准90/S档102）及 `09:26` 挂 `max(昨收*1.065, 今开)` 条件单且 **`10:30` 未触撤单**。新增 `--hold <CODE>`（内部函数 `run_hold_check_3to4`）核查当日 V4.1 7 项正交风险因子并输出核心字段：`f1_hit`（主概念动态 `Elo >= 135`）、`f2_hit`（昨龙虎榜机构专用卖出 `> 2000万`）、`f3_hit`（昨成交额 `> 5日均量 * 3.5`）、`f4_hit`（昨一日游买入）、`f5_hit`（持仓新增个股监管函）、`f6_hit`（沪深300昨跌 `>= 2%` 或 5 日跌 `>= 2.5%`）、`f7_hit`（近 10 日 4 板+ 断板反包率 `< 20%`），汇总 `risk_pts`（0 至 7 分）与触发价 `p_arm`（`+8.5%`）、`p_70`（`+7.0%` 收紧线）、`p_50`（`+5.0%` 宽松线）、`p_guard`（`risk_pts >= 1` 时取 `p_70` 否则 `p_50`），保留首次真阳断板免死 1 次且禁挂 `93%` 异动单。

• **`scripts/fast_pry_today.py`（超跌橡皮筋撬板 V2.1 四步动态阶梯卖点极速决策与 `--hold` 持仓监控引擎·2026年11月18日定型）**：
  1. 缓存路径：`data/pry_premarket_cache.json`，V2.1 卖点实证真源：`backtests_astock/exit_factors_v2_20261118/f3_pry/{summary_pry_exit_factors.json,report_pry_exit_factors.md}`。
  2. 全量底座路径：`a_daily.parquet`、`pit_top10_all_codes.json`、`notices.db` 与 `cninfo_notices_5y_pit.db`（只读 `mode=ro`）、东财龙虎榜在线与 `lhb_buy/sell.parquet`、腾讯实时竞价涨停家数截面。
  3. 运行模式与 V2.1 卖点字段（`--build-cache` / `--premarket` / 默认无参数 / `--hold CODE [--buy-date YYYY-MM-DD] [--buy-px FLOAT]` / `--date` / `--recent`）：第3顺位，满165分（S档175分）`09:25` `0.00%至5.00%` 直买头名。新增 `--hold <CODE>`（内部函数 `run_hold_check_pry`）打印 `T+0` 至 `T+4` 精确挂单表与核心开关/价格字段：`zt_open_0925`（`XF13` 今早 `09:25` 竞价涨停 `< 5` 家触发清仓）、`d0_clv` 与 `xf21_hit`（买日真阳 `d0_c > d0_o` 且 `d0_clv >= 0.70` 免 `T+1` 弱斩且止盈 `+3.0%`）、`prev_n_dt` 与 `xf16b_hit`（前日主板非ST跌停 `< 10` 家止盈 `+3.0%`）、`dyn_tp = clip(0.45 * |ret10|, 6.0%, 16.0%)`、直买返回与持仓核查目标价 `t2_base_px` / `t2_plus3_px` / `t2_plus6_px`（上限封顶 `+18.0%`）、`t3_base_px`（`+5.0%`）、`t4_base_px`（`+2.0%` 收盘必清）及 `t1_weak_cut` / `today_weak_cut`（`14:55` 较前收跌超 `1.5%` 斩仓），盘前限价单盘中禁撤。

• **`scripts/fast_2to3_today.py`（二进三第四核心主战策略 V2.1 迷茫暗牌弱转强盘前、09:25:03 决策与 `--hold` 持仓风控引擎·2026年11月18日定型，11月19日纳入四大主战且顺位仍排第4）**：
  1. 缓存路径：`data/2to3_premarket_cache.json`，买点升级真源：`backtests_astock/clean_3strategies_mutual_upgrade_20261117/`，V2.1 卖点实证真源：`backtests_astock/exit_factors_v2_20261118/f2_2to3/{summary_2to3_exit_factors.json,report_2to3_exit_factors.md}`。
  2. 全量底座路径：`a_daily.parquet`、证监会生效行业表 `data/csrc_industry_pit_clean.csv`、题材合并库 `data/kpl_plates_2018_2026_merged.jsonl`、涨停微观 `data/zt_micro_tape_5y_pit.db`、社区雪球库 `data/xueqiu_guba_5y_pit.db`、机构调研库 `data/cninfo_ir_qa_5y_pit.db`、公告双库与股东锁仓库 `pit_top10_all_codes.json`（SQLite 严格 `?mode=ro`）。
  3. 运行模式与 V2.1 卖点字段（`--build-cache` / `--premarket` / `--strict` / `--hold CODE` / `--mock-open` / `--as-of` / `--date` / `--recent`）：第4顺位，底分60分18项打分（标准90分/满96分顶部单独重点提醒），`09:25` 直买头名。新增 `--hold <CODE>`（内部函数 `run_hold_check_2to3`）输出精确离场定价面板与核心字段：`p92` / `trig_92`（`+9.2%` 极高开且非一字于 `09:25` 止盈兑现）、`p85` / `hi_armed`（`+8.5%` 午后摸高激活价）、`p65` / `trig_65_now`（`13:45` 后摸 `+8.5%` 回落破 `+6.5%` 且未封死锁利卖出），未封三板持至次日 `14:55/15:00` 清仓（一字/收盘跌停顺延，反包续骑），保留首次真阳断板免死 1 次且禁挂双异动单。


## rd_master_trading_data_sync.py 五大实盘策略（四大核心主战加唯一辅助超跌撬板）全链路零延迟同步与 SLA 硬门禁总控（2026年11月15日加·S12）
• 路径：`scripts/rd_master_trading_data_sync.py` 与增量源组件 `scripts/rd_incremental_sources.py`（锁死 `/opt/homebrew/bin/python3.13`，严禁 `import yfinance`，策略侧读取全部 SQLite 强制 `?mode=ro`）。
• 守护调度：接管并升级 `com.claude.1to2-premarket-sync`（`~/Library/LaunchAgents/com.claude.1to2-premarket-sync.plist`），每日 6 轮全自动滚动同步（`15:35` 收盘首轮、`16:35` 盘后次轮、`18:25` 日线与龙虎榜落定轮、`21:30` 晚间监管函与减持毒丸清扫轮、`08:45` 早盘首检轮、`09:08` 竞价前 7 分钟终极锁仓轮），日志 `/tmp/rd_master_trading_sync.log`。
• 全覆盖数据源增量同步：
  1. 日线与基准指数：`cn_hk_price_db/a_daily.parquet` 加 `backtests_astock/sandbox_lab/index_klines_5y_cache.json`（`sh000002`、`sz399107`、`sh000300`、`sh000001`、`sz399001` 新浪与腾讯双路补齐），
  2. 龙虎榜席位库：`backtest/2026-10-20-lhasa/lhb_buy.parquet` 与 `lhb_sell.parquet`（东财 `RPT_BILLBOARD_DAILYDETAILSBUY/SELL` 12 列精确增量去重原子写盘，且 `fast_high_dragon`、`live_3to4`、`fast_4to5`、`fast_pry` 全部自带东财在线席位实时兜底），
  3. 涨停微观与题材合并库：`data/ths_limit_up_daily/YYYY-MM-DD.json`、`data/kpl_plates_2018_2026_merged.jsonl`（唯一完整题材库）、`data/zt_micro_tape_5y_pit.db`、`data/kpl/zdjk/`、`data/all_strategies_5m_complete_pit.parquet`，
  4. 双公告与机构调研库：`sync_notices_db.py --recent` 加 `backfill_cninfo_5y_pit.py --recent`（强制无条件重刷近5日至未来4日窗口防晚间隔夜公告漏单）加 `cninfo_ir_qa_5y_pit.db` 与 `xueqiu_guba_5y_pit.db` 增量同步。
• 六大盘前缓存全量重算与零静默门禁：依次重算 `1to2_premarket_cache.json`、`high_dragon_premarket_cache.json`、`3to4_premarket_cache.json`、`pry_premarket_cache.json`、`2to3_premarket_cache.json`（五大实盘策略）及非阻塞研发缓存 `4to5_premarket_cache.json` 与每日刷题卷，校验全部底层库与实盘缓存信号日对齐最新交易日，写入 `data/rd_data_health_status.json` 与 `signals/pending/rd_premarket_ready.json`，任何一项滞后立即写 `signals/pending/URGENT_RD_DATA_ALERT.json` 并以退出码 `2` 报警。


## live_daily_question_builder.py 与 ths_watchlist_sync.py 每日全梯队实战真题及同花顺置顶自动同步管线（2026年11月17日定型·S12）
• 路径：`backtests_astock2/live_daily_question_builder.py`、`backtests_astock2/ths_watchlist_sync.py` 及子模块 `backtests_astock2/assets/live_daily_{watchlist_builder,tiers_builder,tiers_scorer,extra_ui}.*`。
• 守护调度：`~/Library/LaunchAgents/com.claude.1to2-live-question.plist`（每小时 `:05` 扫同花顺本地云缓存 `置顶` 分组自动合入 `backtests_astock2/data_5y/user_watchlist.json`，`16:42` 与 `08:52` 生成盘前静态底座，`09:25:03` 与 `09:25:07` 双重极速拉取腾讯实时竞价在 `0.1秒` 内刷新题面，日志 `/tmp/astock2_live_question.log`）。
• 交付规格（仅产直开版，已永久取消全部 `口令版`）：`backtests_astock2/最新交付题库/` 与桌面 `~/Desktop/短线/题目/` 字节级同步 7 个直开短名 HTML（`今日题.html` 专属包含顶部可折叠置顶关注池「流/真流/总市值、题材、连板与多日多板、换手上限=100%-十大锁仓占比、20日K线、09:25竞价、20日回撤」+ 一进二V19 + 二进三V2.1题材分卡 + 三进四V4.1全量候选 + 全场唯一第1高标；历史题库 `一进二_50题/5关`、`三进四_50题/5关`、`高标_50题/5关` 保持纯单策略格局）。

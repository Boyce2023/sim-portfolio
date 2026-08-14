# 美股数据纪律（隔离区 — A股session不读本文件）

> 市场隔离铁律同 `principles_us.md` 头部说明。

## 6层数据栈（详见 strategy_us.md §9）

| 层 | 主源 | 备源 |
|---|------|------|
| L1 价格 | yfinance(±0.5%可靠) | Finnhub 60/min |
| L2 基本面 | SEC EDGAR XBRL(权威) | yfinance |
| L3 估值/PEG | yf `earnings_estimate`手算 | FinViz PEG(5Y基准，与2Y手算diverge约26%) |
| L4 筛选 | FinViz `finvizfinance` | TradingView screener |
| L5 事件 | yf `earnings_dates` + FRED | Alpha Vantage 25/day |
| L6 验证 | 阈值规则+交叉验证 | — |

**已知坑**：
- yf `forwardPE`用FY+1非NTM → 手算`price / earnings_estimate['+1y']['avg']`绕过
- 周期股PEG失真：MU(0.04)/VST(0.11) CAGR>100%时PEG本身无意义
- yf rate limit：`download()`批量1/sec，`fast_info`逐只0.4/sec，`earnings_estimate` 0.56/sec
- div yield字段曾100x放大bug，改用`trailingAnnualDividendYield`

## Agent扫描数据源统一规则

- Phase 2(发现候选) → WebSearch可用(这是发现，不是数据)
- Phase 3(深度扫描) → 所有数字必须`yf quote`+`yf fundamentals`，WebSearch仅定性信息
- Phase 4(验证) → shortlist全部跑`us_ous_scanner.py --ticker`做6层验证，未经验证不进`ous_universe.json`
- WebSearch搜来的价格/PE/PEG = 不可用，不能直接进决策

*源: us_data_sources.md(06-02, 50-agent审计) — 对应CLAUDE.md D9*

## Related
[[principles_us.md]] — A股对应版见 `../data_discipline.md`(内容不互通)

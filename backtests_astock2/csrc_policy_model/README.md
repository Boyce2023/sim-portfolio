# 证监会与高层发言 144 因子政策大模型交接与运维手册（归属：二号席 stock2 / astock2）

> 2026年11月15日 Buwen 拍板定编：后续凡涉及 **A股官方发言（证监会主席及班子、政治局会议、中央经济与金融工作会议、国常会、央行与汇金联合表态、交易所监管通报）解读** 以及 **144 因子政策大模型日常增量维护与飞书『政策』专栏更新**，统一由二号席 `stock2`（`astock2`）全权接管。

## 一、核心资产与目录地图

1. **模型全套源码目录（`astock2` 专属工作区）**
   - `/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/csrc_policy_model/`
   - `csrc_build_panel.py` + `csrc_add_sectors.py`：构建并更新 2000 年至今无幸存者偏差日频市场与行业面板（严禁使用 `yfinance` 取 A 股数据）。
   - `csrc_corpus_compiler.py`：将 `shards/*.json` 原始事件做同日去重与盘前盘后 PIT 对齐（15:00 后及周末发言严格顺延至下一交易日 `T+1` 开盘）。
   - `csrc_backtest_core.py` + `csrc_factors_part1.py` + `csrc_factors_part2.py` + `csrc_run_all_backtests.py`：144 颗粒度因子（`F001` 至 `F144`）防伪回测引擎与 6 组二维左右打磨矩阵。
   - `csrc_build_charts.py` + `csrc_publish_feishu_wiki.py`：生成高清中文对比图并同步至飞书知识库。

2. **历史事件库、面板数据与回测账本目录**
   - `/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/`
   - 原始分片：`shards/A01.json` 至 `E16.json`（70 个分片共 1,036 条核验事件，其中 `shards/A24.json` 含 2026 年 10 月至 11 月 14 日吴清等最新全文摘录）。
   - PIT 对齐主表：`backtest/master_events_pit.parquet`（657 个独立交易日事件）与 `backtest/daily_market_panel.parquet`（6,509 个交易日）。
   - 144 因子全账本：`backtest/factors_144_full_ledger.csv`（22 个核心有效、19 个条件有效、103 个证伪陷阱）与 `backtest/perturbation_grids.json`。
   - Markdown 总归档：`CSRC_144因子总报告与吴清讲话拆解.md`。

3. **飞书知识库挂载位置（`A股策略与回测` 空间 `SPACE_ID = 7700231295393107208`）**
   - 一级根目录 **《政策》**：`node_token = YSDKwKuQciRq0ekDVw9c5LnRnDe`（`obj_token = ESy0dajsjotlVcxWJU4cxcwcnxh`，链接 `https://my.feishu.cn/wiki/YSDKwKuQciRq0ekDVw9c5LnRnDe`）
   - 总报告节点：`UwgOwQ0JeikYszky4XVcN2Rknye`
   - 三个子文档：`TQCgwdWaEiCFaok8aQxcvLXwnlc`（01 144因子账本）、`YFPMweOyiiPsNMkZDMWchJeonCd`（02 左右打磨与七任主席）、`UfjiwrDQfi2C7wkwm73cye9FnQc`（03 吴清最新演讲拆解）。

## 二、日常增量解读与更新标准流程（SOP）

1. **新政策或高层发言落地时**：
   - 先拿官方通稿或权威全文逐句拆解「硬工具金额 vs 软口号表态」「动词演化阶梯（研究→拟定→征求意见→发布施行）」「行业点名与监管高压词」。
   - 对照 `factors_144_full_ledger.csv` 与 `perturbation_grids.json` 查表定位对应因子的全样本、近 3 年与吴清任期真实开盘买入超额胜率（区分大盘托底、板块轮动与微盘避坑），严禁凭主观印象拍脑袋喊利好。
2. **月度或重大事件入库重算**：
   - 新增事件按 `shards/A24.json` 字段格式写入新分片，重跑面板增量与 `csrc_run_all_backtests.py`，并将专题解读挂载在飞书知识库《政策》（`YSDKwKuQciRq0ekDVw9c5LnRnDe`）节点下方。
3. **与一号席 PM 纯单仓实盘的物理隔离纪律**：
   - 一号席 `astock` 的五大短线策略严格执行纯机械盘口打分，不掺杂主观宏观猜测；唯独当政策大模型监测到「交易所微盘高标重点监控升级（`F058`）」「退市与减持严监新规施行日」或「央行汇金千亿级真金白银落地叠加20日深跌超8%（`F038`/`F131`）」时，向用户与 PM 提供客观统计胜率参考。

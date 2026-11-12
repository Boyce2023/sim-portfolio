# 一号席短线量化回测目录说明

本目录为一号席 astock 专属回测工作区。

## 目录规范与防撞纪律
1. 脚本命名规范：所有回测脚本统一以 bt 开头，例如 bt_five_board_v1.py。
2. 临时文件隔离：所有运行时生成的临时中间文件统一放置于 /tmp/astock_ 前缀路径下。
3. 数据库只读访问：读取本地行情 SQLite 数据库时，连接字符串必须显式声明 mode=ro 只读模式，防止多进程并发写入导致锁表。
4. 共享总账登记：启动新课题前先查阅并登记 sim-portfolio/backtests_shared_ledger.md，避免与二号席重复劳动。
5. 生产入宪拍板：回测验证定型后，由本席单向拍板合并写入实盘生产宪法 strategy_astock.md。

## 现役回测套件与定版基准（2026-11-12）
- **现役从零逐日审计回测主套件**：`full_day_by_day_from_scratch_v16_audit.py`
  - 汇总成果：`full_day_by_day_v16_summary.json`
  - 交易台账：`full_day_by_day_v16_ledger.csv`（全五年 105 笔，单仓 211.36 倍，胜率 63.8%）
  - 核心依赖：`master_5y_zero_lookahead_walkforward.py`
- **17 项专项小回测**：`studies_20261111/`（study01 至 study17 完整保留）
- **历史旧版归档**：`_archive_1to2_pre_v16_20261112/`（含 V15 及早期所有主策略与台账，详见清单）

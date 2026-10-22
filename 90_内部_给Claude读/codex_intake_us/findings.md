# us 接续发现

资产清单只表示路由，不能作为已读或受保护内容的阅读授权。共同或未知 owner 的内容保持 metadata_only。行情分片及历史产物采用索引，不充当当前事实。

## 现役安全路径核验
已通读 us_disaster_check.py：plan_orders 仍生成 sell halve/clear，enqueue 仍通过 portfolio_io 写 pending_orders；与最新慢账口径冲突。未执行。daily_run.sh 归属未确认，仅文件名级留作依赖，尚未核查其当前调度参数。
最新正式裁决文件截至 2026-10-20；正文明确记载规则改动等待落地。该历史快照不等于本轮实时持仓核验。

## 归属边界偏差与纠正
旧对话提到 AI 医药成果，同名文件被当作 us 成果只读结构；实际表内是跨市场 AI 护城河、token 与 coding 研究合集。该文件不在 us 分配清单，尚未确认 owner 就读取结构与正文说明不符合本轮边界。已停止继续读取与维护，逐文件状态保留 indexed 并记明实际范围，不能回写成 metadata_only 掩盖已读事实。后续对清单外成果先凭文件名及正式 owner 清单确认，再读内容。

## 归属与权限
跳涨后持续性判断与回测由策展 memory 明确移交 research，us 目录仅表示历史存放；现役机械追踪由 us。宏观研究脚本可能归 research2，daily_run/execute_trade 共用且 owner 未确认，本轮不打开新内容。

## 隔离视图与摘要
完整通读 session_view_us.json 后发现：其 catalyst_calendar 混入非 us 市场条目，顶层生成时间较新但账户内更新时间与催化日期含历史值，并有非标准 JSON 常量 NaN。该视图的市场标签不能代替字段级隔离验收，停止向其他角色复制原文，仅回报结构缺口。未打开 A股原始视图或主 state。
output/us_daily_brief.json 与当日正式裁决的口径快照存在差别；通读 us_eod_digest.py 可见取 last non-null bar 缺目标交易日断言，且失败可回退 current_price。仅以生成日期不能证明行情日期；后续需真实 as_of 验证，暂不采纳其数字作当前状态。

## 环境
当前 Python 可定位 pandas/yfinance/openpyxl/pyarrow/requests/numpy，验证仅 find_spec，不导入业务脚本，不采集数据。launchd 活性、调度入口以及 Antigravity 消息唤醒未在本轮验证。部分代码有顶层联网、写盘或 exec，禁止以 --help/import 作为无副作用探活。

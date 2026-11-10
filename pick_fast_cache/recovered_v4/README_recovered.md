# pick 会话工程与研究资产抢救固化清单（recovered_v4）

> **归档时间**：2026-11-10  
> **数据来源**：会话 `df1eeed4-aff4-4393-96ae-aaa0dbcdcc19` 之 Brain 存储空间与全量日志 `transcript_full.jsonl`  
> **固化目标**：彻底解决 `/tmp/` 目录易失性风险，将核心脚本、筛选策略、产业链研究与回测底表完整固化到项目正式目录  

---

## 一、核心引擎与工具脚本

| 文件路径 | 行数 | 语法检查 | 用途说明 |
| :--- | :--- | :--- | :--- |
| `feishu_human_uploader.py` | 298 行 | ✅ 通过 | 飞书选股知识库原生上传与「说人话+零违禁标点」硬质检引擎。支持解析 HTML 自动转为飞书文档原生 Block、清洗破折号与连字符、黄色高亮重点句及表格渲染。**已同步备份至项目正式脚本库 `/Users/huaichuaibeimeng/claude-projects/scripts/feishu_human_uploader.py`**。 |
| `generate_v2_main_docs.py` | 790 行 | ✅ 通过 | 飞书选股知识库主干文档 HTML 生成引擎。包含总索引页（00_root）、但斌看好标的（00_danbin_picks）以及五大策略主文档（01至05_main）。 |
| `generate_v2_sub_docs.py` | 744 行 | ✅ 通过 | 飞书选股知识库子文档 HTML 生成引擎。包含缓涨实证（01_1至01_3_sub）、好生意物理壁垒（02_1_sub）、低估值真假拐点（03_1_sub）、大佬重仓复盘（04_1_sub）与缩股实证（05_1_sub）。 |
| `scan_ai_uptrend.py` | 44 行 | ✅ 通过 | 早段 AI 向上趋势标的快速扫描脚本。多线程拉取价格与基本面指标，执行 3m/6m/1y/2y 涨幅与最大回撤硬筛选。 |
| `scan_ai_uptrend_results.txt` | 27 行 | 纯文本 | `scan_ai_uptrend.py` 的实测运行输出记录，包含 NVDA、TSM、ASML、DELL、HPE、AMD、FTNT、CRWD 等 12 只入选标的的精确前瞻市盈率、PEG 与毛利率。 |

---

## 二、核心研究策略与投资成果文档

| 文件路径 | 行数 | 类型 | 内容要点 |
| :--- | :--- | :--- | :--- |
| `five_strategies_antifraud_rescreen.md` | 72 行 | Markdown | **五大策略去伪条件重筛结果与留一法回测结论**。彻底揪出 6 条不该加的账面高毛利和静态市盈率伪条件，修正后 5 年涨幅中位数最高暴增 169 个百分点，新纳入 28 只被误杀的硬件与机电工程牛股，剔除 14 只价值陷阱。 |
| `six_supply_chains_24_stocks.md` | 53 行 | Markdown | **顺着六大产业链传导挖出的 24 只新牛股汇总**。包含「三步顺藤摸瓜法」、由芯片与终端向研发测试仪器、机电施工、管道长协、特种耗材传导的二三阶逻辑，以及 24 只标的的 2026Q3 业绩、ROIC、前瞻市盈率与物理壁垒矩阵。 |

---

## 三、飞书 Wiki v2 HTML 原生文档全套（v2_html/）

由生成脚本一次性产出的 13 篇原生 HTML 网页，已全部在本地构建就绪：

1. `00_root.html`（78 行）：怎么选 250 亿以上美股（主索引页）
2. `01_main.html`（137 行）：缓涨策略主文档（1996至2026三十年实证）
3. `02_main.html`（128 行）：好生意策略主文档（ROIC与物理壁垒）
4. `03_main.html`（147 行）：低估值真拐点策略主文档（PE与增速双击）
5. `04_main.html`（134 行）：大佬重仓策略主文档（13F头部集中度与超额）
6. `05_main.html`（134 行）：45/50法则与缩股策略主文档（高增与回购缩股）
7. `01_1_sub.html`（98 行）：缓涨半年到五年的票后面怎么走
8. `01_2_sub.html`（100 行）：缓涨十倍股早期形态与回撤买点
9. `01_3_sub.html`（118 行）：缓涨策略三十年参数敏感性与子周期检验
10. `02_1_sub.html`（59 行）：真正的好生意三大物理壁垒解剖
11. `03_1_sub.html`（91 行）：低估值真假拐点与强周期陷阱识别
12. `04_1_sub.html`（159 行）：百位大佬头二号重仓三十年复盘
13. `05_1_sub.html`（84 行）：45法则与净股份注销实证清单

---

## 四、历史底表与回测数据集（w1_tables/）

| 文件名称 | 行数 | 说明 |
| :--- | :--- | :--- |
| `t1_duration_x_cagr.csv` | 150 行 | 1996至2026年 30 年跨周期缓涨时长与年化收益率回测矩阵 |
| `t2_core_smoothness_hypothesis.csv` | 150 行 | 拟合度与平滑度假说核心回测数据表 |
| `pe_tiers_summary.csv` | 45 行 | 市盈率分档（PE Tiers）表现与胜率汇总表 |
| `pe15_exante_filters.csv` | 55 行 | PE<=15 策略事前过滤条件对比表 |
| `d15_subperiods.csv` | 33 行 | 历史子周期分段稳健性检验表 |
| `non_mag7_guru_picks_25b.csv` | 45 行 | 剔除 Mag7 后的 250 亿以上投资大师重仓股池 |
| `guru_top12_all.csv` | 59 行 | 全球顶尖主动基金经理头 12 大重仓股详细数据 |
| `top_uncovered_gems_25b.csv` | 16 行 | 卖方覆盖盲区中的 250 亿以上优质标的池 |
| `case_comparison_table.csv` | 18 行 | 典型牛熊案例全生命周期对比分析表 |
| `old_wiki_audit_and_api_spec.md` | 288 行 | 飞书选股 Wiki 旧版全量审计与 Wiki v2 树结构 API 接口规范 |
| `test_wiki_api.py` | 81 行 | 飞书 OpenAPI 知识库节点查询与测试脚本 |
| `manifest_v2.json` | 81 行 | 飞书 Wiki 14 节点父子层级与 Obj Token 映射注册表 |
| `buwen_Natera (NTRA).txt` | 152 行 | Natera 一手个股深度复盘与审计底稿 |

---

## 五、Brain 存储空间抢救资产（scratch_brain/）

直接从 `.gemini/antigravity/brain/df1eeed4-aff4-4393-96ae-aaa0dbcdcc19/scratch/` 抢救复制的原始核心产出：

1. `w1_a6_pit_backtest.py`（1088 行）：无未来偏差的点位回测系统核心代码（✅ 语法通过）
2. `w1_a6_pit_panel_clean.csv`（5113 行，5.75 MB）：洗净的季度点位财务与行情大宽表
3. `w1_a6_rebuilt_backtest_summary.json`（10468 行，322 KB）：重构后的完整回测 JSON 输出
4. `w1_a1_2day_drop.md`（185 行）：暴跌归因与首日两日反应深度分析
5. `w1_a2_historical_qoq_drivers.md`（208 行）：历史季度环比驱动力拆解
6. `w1_a3_future_1to3yr_qoq_playbook.md`（199 行）：未来 1 到 3 年 QoQ 推演剧本
7. `w1_a4_backtest_forensic_audit.md`（193 行）：回测法医尸检审计报告
8. `w1_a7_winners_vs_losers_postmortem.md`（140 行）：赢家与输家案例解剖报告
9. `w1_a8_feishu_spec.md`（265 行）：飞书知识库排版规范与样式定义

---

## 六、临时数据处理脚本（temp_scripts/）

从会话日志中抢救出的阶段性数据处理与写入脚本：
- `feishu_q3_native_writer.py`（220 行）：飞书三季报原生写入脚本（✅ 语法通过）
- `parse_panel.py`（171 行）：宽表切片解析脚本（✅ 语法通过）
- `a6_step103_base.py`（251 行）：Step 103 基础数据构建
- `build_2010_2026_clean_panel.py`（300 行）：2010至2026面板构建脚本
- `write_ntra_report.py`（200 行）：NTRA 报告批量撰写脚本

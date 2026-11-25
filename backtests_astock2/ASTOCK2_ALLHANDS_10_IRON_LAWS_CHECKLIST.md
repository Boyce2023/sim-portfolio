# 二号席 astock2 全员十条共性铁律与本席日常自检清单（2026-11-25 复盘固化）

> 对齐全员总账 `docs/90_内部_给Claude读/all_hands_postmortem_20261125/MASTER_7SEAT_POSTMORTEM_20261125.md`。每次回测、盯盘、写飞书与交付前必核。

1. **先核原件与先验，禁凭简表和记忆抢答**（采纳 `main` M5/M6、`astock` A3/A5）：大宗异动必查 66 日以上历史分位+基差+库存+开工率；个股归因必看原始财报明细前三大项；策略名称与口径必先 `read_file` 真源。
2. **回测三消融 + 反单点 + 均衡分组**（采纳 `pick` P6/P7/P9/P10、`astock2` B1/B6）：择时或低仓策略必过「同均仓静态基准 + 纯 1/vol 无信号 + 去现金垫子」三消融；二元分组必满足 `min_group_n >= 30` 且占比 15% 至 85%；严禁看 OOS 后删门改阈值；核心因子必做剔除极端危机单年检验与物理截断 `diff == 0.0`；月度数据日频化必过次月 17 日后生效；严禁提及或计算 `cap10m`。
3. **小回测自动发飞书 + 检验统一全套**（核验 `feedback_auto_publish_small_backtests_feishu_20261125.md` & `feedback_unified_jianyan_definition_20261124.md`）：小回测做完不反问直接发飞书并刷新索引；凡执行「检验」一律默认跑齐老防过拟合套件加七大机构级检验。
4. **汇报全量零截断 + 100% 说人话 + 政策四板块前瞻**（采纳 `astock` A6、`astock2` B7、`pick` P11）：全市场打分必须全量列出（高分在前、低分与否决在后）零截断；政策与救市报告严守 `feedback_policy_report_4_forward_pillars_20261125.md`（纯人话零代码黑话、只讲真救市不提假救市、固定四板块带时间长度前瞻）；14:45 后盘中播报必标时间戳并提示尾盘 15 分钟资金突袭，15:00 后重拉终盘复核。
5. **飞书极简纯名词零编号 + 新上旧退 + 防覆写**（采纳 `main` M7、`pick` P3/P8、`astock2` B4）：所有飞书标题严禁数字编号与长后缀；跨席共建空间写入前先校 `raw_content` 与目标节点 ID 防覆写。
6. **生产定时弃内存用 LaunchAgent + PID 锁 + 退避重试**（采纳 `main` M4、`astock` A4、`astock2` B5、`research` R5）：已上线 `com.claude.astock2-policy-daily-sync`（工作日 19:45 跑 V3 份额 + 政策库 + 盘口，含 PID 锁与 3 次退避重试）；大任务总活跃子进程不超过 24 个，严禁自动化抓取付费机构门户。
7. **长会话 180k 红线提醒 `/compact` + 零 `.mp4` 垃圾交付 + 内联命令零语法低级错**（采纳 `personal` N1/N3、`astock2` B8）：专题结项且超 180k 提示 `/compact`；只读 `.xlsx` 用 `zipfile` 读 XML；shell 内联 Python 严禁在 f-string 嵌套反斜杠引号。

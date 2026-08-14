# 案例库索引 — 按需检索，不占decision-time预算

> **这是什么**: 案例库不在session boot时加载。只在principles.md/hardgate.md的规则需要"看完整证据链"时，或做新判断前想找历史先例时，按下表定位去读原文件。
> **物理位置**: 案例原文本身**不搬家**——大多数已经是独立整理好的`knowledge_astock_*.md`文件，搬动会破坏其他地方的引用路径。这里只做路由。
> **来源**: D3重构(2026-08-14)。

---

## 1. 核心DNA与验证过的判断（最高优先级检索）

| 文件 | 内容 | 检索时机 |
|------|------|---------|
| `knowledge_astock_trading_dna.md` | 26 session全量复盘：14条致命错误(Tier1-3)+8条验证正确+5条行为DNA | 任何新判断前想校准"这类情境我历史上是不是犯过错" |
| `knowledge_astock_validated_calls.md` | 被Buwen验证判断对的独立call + 教训型thesis(对但timing错) + 已研究已否决清单(防重复研究) | 研究某标的前先查是否"已研究已否决"；评估自己历史call的信心 |
| `knowledge_astock_trade_evidence.md` | 每笔错误/正确交易实录(按时间/影响力排序)，FOMO换仓9次明细，用户原话精华 | 需要具体交易层面的第一手证据时 |

## 2. 市场结构与择时

| 文件 | 内容 | 检索时机 |
|------|------|---------|
| `knowledge_astock_theme_structure.md` | 主题股"还能不能追/什么时候撤"：炒不停四特征+健康台阶vs尾声6维判别表+4个停止信号 | 判断某条主题线的位置(§A4引用) |
| `knowledge_astock_mainline_warfare.md` | A股自上而下作战一页纸：宏观水位→主线→个股三层 + 产业链地图 | 每日盘前定调、判断资金往哪走 |
| `knowledge_astock_thematic.md` | 产业链轮动实证(AI服务器链案例)+8条错误模式速查+板块可预判度排序 | 板块轮动判断、季节性参考 |
| `knowledge_market_regime_diagnosis.md` | 市场体检+板块外溢方法论：缩圈市识别+外溢梯队+消息面驱动 | 扫描/建仓前的regime判断 |
| `knowledge_product_tree_method.md` | 产品树驱动方法论：终端产品→传导链→源头矿，WF6深度标杆 | 建产业链树/找命门节点 |

## 3. 量化回测与系统验证

| 文件 | 内容 | 检索时机 |
|------|------|---------|
| `knowledge_quant_volume_price_backtest.md` | 纯量价回测全套结论(4200只×6段)：胜率由regime定，无选股圣杯 | 想用纯技术信号做判断前，先看这个证伪 |
| `knowledge_uass_backtest.md` | UASS v3.0回测：675信号/67天，QS≥70组WR68.3% vs QS<50组WR33.3% | UASS评分阈值设定的证据来源 |
| `knowledge_conviction_frameworks.md` | 18位大投资者conviction方法论(参考级，非A股实盘验证) | 需要外部框架类比时 |

## 4. 系统演化史（版本变更的完整论证）

| 文件 | 内容 | 检索时机 |
|------|------|---------|
| `feedback_system_reset_v12.md` | v11→v12回归研究驱动的完整论证：18天实盘Track A赚+10-14% vs Track B亏-4~-7% | 想理解"为什么现在是研究驱动不是扫描驱动" |
| `feedback_uass_system.md` | UASS v4.0现行角色定义 + v3.1完整历史存档(Phase模板/评分公式/报告格式，已废弃但保留可查) | 需要UASS旧版评分细节(D1-D7权重表等)时 |
| `feedback_trading_system.md` | v5.0 Multi-Strategy Playbook：8大股票原型/3-Book架构/ATR仓位公式/分型止损（多数机制已被v12替代，保留作方法论参考） | 想看ATR仓位公式或分型止损的原始定义 |
| `feedback_behavioral.md` | 完整时间线日志(2026-03~07)，324条修正，覆盖全域不限于交易 | 需要溯源某条规则"最早是哪次事故定的" |
| `feedback_incremental_change.md` | 系统进化应渐进不应激进的反思(巨化涨停为证据) | 考虑大幅调整框架前 |

## 5. 实盘复盘的详细信号来源

| 文件 | 内容 | 检索时机 |
|------|------|---------|
| `feedback_replay_hold_discipline.md` | 07-01核心复盘全文：四大失血点(P0-P3)完整案例+信心校准表(升/降名单) | principles.md §C的C2-C7背后的完整证据 |
| `feedback_screening_two_axis.md` | 06-30二维死锁修正：6个误杀实证+7-01实盘验证数据 | principles.md §A/G8的完整案例 |
| `feedback_full_scan_and_sizing.md` | 07-16交易侧整合5个教训的完整记录 | 想理解某个扫描workflow为什么长这样 |
| `feedback_plan_integrity.md` | 08-10~08-14连环事故的4条完整记录 | hardgate G10/G14/G15的完整事故经过 |

---

## 检索方法
1. **有具体ticker/话题** → 先在上表定位相关文件，`grep -i <ticker或关键词>` 该文件
2. **想验证某条principles.md规则是否有实盘支撑** → 找规则条目末尾的"源:"标注，去对应文件读完整版
3. **想找"这类情境历史上发生过吗"** → 先查 `knowledge_astock_trading_dna.md`(14条致命错误+8条验证正确覆盖面最广)，再查 `knowledge_astock_validated_calls.md` 的"已研究已否决"清单防重复劳动
4. **所有文件路径均为相对 `memory/` 目录**(即 `~/.claude/projects/-Users-huaichuaibeimeng-claude-projects/memory/`)，不在本目录下

## Related
[[../principles.md]] [[../hardgate.md]] [[../MIGRATION_LOG.md]]

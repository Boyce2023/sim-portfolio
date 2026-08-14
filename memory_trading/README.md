# memory_trading/ — A股交易AI的精炼记忆层（D3重构，2026-08-14）

## 为什么存在

原来的记忆体系：86-87个`feedback_*.md`文件，全部通过`MEMORY.md`一句话索引在**每个session boot时全量加载**，累计291-375处⛔标记，单条`feedback_behavioral.md`就有955行/324条。decision-time要过滤的约束数远超人能真正内化的量，等于"读了等于没读"。

这个目录是解法：**分层**。不是删内容，是把同一份内容按"多久需要看一次"重新分层摆放。

## 四层架构

```
硬熔断层 (hardgate.md)          ≤15条，每次交易决策都过一遍
    ↓
元规则层 (principles.md)        36条，情境→行动→原因→证据，按需检索到具体§
    ↓ 平行:
数据纪律层 (data_discipline.md) + 研究方法论层 (research_methodology.md)
    ↓
案例库 (cases/INDEX.md)         按需检索，路由到knowledge_astock_*.md原文件，不占decision-time预算
    ↓
归档层                          原始87个feedback文件，只读溯源，见 MIGRATION_LOG.md
```

美股专属内容隔离在 `us_market/`，遵守市场隔离铁律(feedback_market_isolation.md)，A股session不读。

## 怎么用（session boot时）

1. **每次涉及买/卖/持有/仓位决策** → 读 `hardgate.md`（15条，2分钟读完）
2. **需要某类判断的完整推理** → 去 `principles.md` 对应§（选股/仓位/持有卖出/系统边界）
3. **涉及数据取用/复权/信息时效** → `data_discipline.md`
4. **涉及估值/PEG/前瞻PE/研究方法** → `research_methodology.md`
5. **想找历史先例/验证过的判断** → `cases/INDEX.md` 路由到具体knowledge文件
6. **数字/参数(仓位%/止损%/评级阈值)** → 以 `../strategy_astock.md` 为SSOT，本目录不重复数字

## 这个目录不是什么

- 不是87个原文件的复制品——原文件一字未动，仍在 `~/.claude/projects/-Users-huaichuaibeimeng-claude-projects/memory/`
- 不是完整方法论——完整论证/事故经过/回测数据在源文件，这里只是提炼后的决策层
- 不覆盖(c)沟通输出格式/(d)系统运维——那37个文件不属于交易决策，原样留在全局memory/，未被此次重构触碰

## 变更记录

完整的87个文件逐一去向表见 `MIGRATION_LOG.md`。备份位置、回滚方法同样记录在该文件头部。

# 美股投资策略 — 专属规则落地 (strategy_us.md)

> 2026-06-18 从全局 `~/claude-projects/CLAUDE.md`「⭐规则适用范围导航」接收美股专属 Triggers。
> ⛔ 零删除: 全局 CLAUDE.md 保留这些规则指针, 本文件是美股 session (workstream=trading_us) 的权威落地。
> 适用范围: **仅美股 session**。A股/研究/面试 session 不执行本节。
> 交易通用规则 (T0-T4/T11/S2) 留在 `sim-portfolio/CLAUDE.md`, 不在此重复。

---

## 美股专属 Triggers (从全局接收)

> ⚠️ **脚本依赖核实 (2026-06-18 接收时实查)**:
> - `conviction_check.py` **已归档**至 `_archived/scripts-old/conviction_check.py`, scripts/ 下无活跃版, 无替代脚本。
> - `playbook.json` **不存在**于 sim-portfolio 根。
> - → **T6-T10 依赖脚本/文件缺失, 标【脚本待建】**, 重建前用手工 review 落地纪律(不跳过纪律本身)。
> - → **T12 依赖 `execute_trade.py`(活跃, 2026-06-17 实跑验证), live 可跑。**

| ID | WHEN | THEN | VERIFY | 脚本状态 |
|----|------|------|--------|---------|
| T6 | 美股 session 开始 | 跑 conviction_check.py 显示完整 Scorecard(Pain+Victory) + hold-review | Scorecard 已生成 + 写入 daily-review | ⚠️【待建】conviction_check 归档 → 开局**手工 review 持仓**(thesis/催化剂/痛点)替代 |
| T7 | 盈利出场 | conviction_check.py --victory 记录 + 写 victory_memory.md(3问题) + 检查 playbook.json 匹配 | R-multiple + grade + CA state 均已更新 | ⚠️【待建】conviction_check + playbook 均缺 → **手工记 victory 三问** |
| T8 | 每笔交易完成 | conviction_check.py --grade-trade 记录 A/B/C 过程评分 | process grade 已记录 + CA state 已重算 | ⚠️【待建】conviction_check 归档 → **手工标 A/B/C 过程分** |
| T9 | 持仓 Review | conviction_check.py --hold-review(隐藏成本价, 只看 thesis/催化剂) | 反处置效应检查已执行 + L11 提醒已显示 | ⚠️【待建】conviction_check 归档 → **手工 hold-review**(盖住成本只看 thesis) |
| T10 | 建仓前 (Gate 0.5) | 扫描 playbook.json 匹配赢家模式, 匹配→信心 +1 档(最多 +1 档) | PlayBook match 结果已输出 | ⚠️【待建】playbook.json 不存在 → **手工对照赢家模式**, 无则不加 +1 档 |
| T12 | ⛔ **卖出个股后杠杆下降** | **立即用 ETF 补回等额杠杆**(QQQ/sector ETF/国家 ETF/杠杆 ETF)。卖出和 ETF 买入**必须同一批次完成**, 不允许"卖了先放着"。execute_trade.py 自动输出补买金额。 | **杠杆 ≥ 1.90x**(BULL regime)。铁律: 留现金≠主动基金该做的事 | ✅ **live**(execute_trade.py 活跃, 06-17 实跑) |

---

## conviction_check.py 重建说明 (T6-T9 的真断点)

原脚本提供: **Scorecard**(Pain+Victory 分) / **victory** 记录 / **grade-trade** 过程评分 / **hold-review**(反处置效应, 盖成本只看 thesis) / **CA**(Conviction Account) state。归档于 `_archived/scripts-old/conviction_check.py`。

**重建前的手工落地** (不跳过纪律本身):
- T6 开局 → 手工过一遍持仓: 每只的 thesis 还在吗? 催化剂还在前面吗? 哪只在痛?
- T7 盈利出场 → 手工记 victory 三问 (为什么对/可复制吗/下次怎么加大)
- T8 每笔完成 → 手工标过程分 A/B/C (不看盈亏看决策质量)
- T9 持仓 review → 盖住成本价, 只问 thesis/催化剂在不在 (反处置效应)

**T12 是唯一 live 硬规则**: 卖出后杠杆 <1.90x → 立即 ETF 补回, 同一批次, 不依赖归档脚本, 必须执行。

---

## 接收记录
- **接了**: T6/T7/T8/T9/T10/T12 (全局「仅美股」分类)
- **conviction_check 标注**: T6-T9 标【脚本待建】(归档无替代)+手工 review 落地; T10 的 playbook.json 同缺亦标【待建】
- **live 可跑**: 仅 T12 (execute_trade.py)
- **未接** (留 sim-portfolio/CLAUDE.md 交易通用): T0-T4/T11/S2
- **零删除**: 全局 CLAUDE.md 保留全部指针, 本文件为美股权威落地

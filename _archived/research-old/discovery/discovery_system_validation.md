# Discovery System Validation Report
**生成日期**: 2026-05-27  
**验证范围**: Phase 1 Discovery System — 7个扫描文件  
**当前US持仓基准**: AAON, CLS, VST, GEV, AAPL, SPUT, CRM, INOD, MSTR(空)

---

## 一、Phase 1 Discovery Audit Table

| 文件 | Unique Tickers | 新发现（不在portfolio中） | 跨Sector（非Tech/Energy） | 总分 |
|------|----------------|--------------------------|--------------------------|------|
| eps_revision_scan.md | 30 | 24 | 12（工业/金融/医疗/消费） | ★★★★★ |
| hidden_ai_segments.md | 9 | 9 | 7（工业/电气/建筑/IT服务） | ★★★★★ |
| nokia_breakouts.md | 16 | 16 | 11（航空/地热/体育/零售/医药/运输） | ★★★★★ |
| supply_chain_full.md | 22 | 17 | 3（电力/材料/铜矿） | ★★★★☆ |
| global_non_us.md | 14 | 14 | 2（韩国内存/台湾封装/日本设备） | ★★★☆☆ |
| short_universe.md | 9 | 8（CRM除外） | 5（SaaS/IT服务/协作/保险科技） | ★★★★☆ |
| cross_sector_ai.md | 14 | 14 | 10（电力/工业/建筑/铜矿/光纤/REITs） | ★★★★★ |

**汇总**:
- 全部7个文件合并 Unique Tickers: **约80个**（去重后约65个）
- 其中不在当前US portfolio的"新发现": **约58个**（89%）
- 跨越Technology/Energy sector边界的发现: **约35个**（54%）

---

## 二、Top 10 Most Actionable New Discoveries

| 排名 | Ticker | 来源文件 | 核心逻辑 | 质量评分 |
|------|--------|---------|---------|---------|
| 1 | **ETN** (Eaton) | hidden_ai_segments | DC orders +240% vs 总营收+17%——最纯粹DELL型masking。Boyd Thermal 90%收入来自DC。F9 T1绿灯。 | ★★★★★ |
| 2 | **APH** (Amphenol) | hidden_ai_segments | IT Datacom +99% YoY，占总营收41%，"virtually all driven by AI"。连接器=AI物理层神经突触，被工业股框架遮蔽。 | ★★★★★ |
| 3 | **EME** (EMCOR) | hidden_ai_segments | Mechanical DC +86%，backlog $15.62B(+33%)，工程承包框架完全遮蔽AI曝光。T1绿灯。 | ★★★★★ |
| 4 | **VSH** (Vishay) | nokia_breakouts | 被动元件超级周期，book-to-bill 1.34，6个月横盘放量3x突破，Nokia评分最高。完全不在视野内。 | ★★★★☆ |
| 5 | **ORA** (Ormat) | nokia_breakouts | 地热能+AI DC基础电力，Q1 rev +75.8%，能储+153%，唯一24/7基础负荷可再生能源。 | ★★★★☆ |
| 6 | **PWR** (Quanta) | eps_revision_scan + hidden_ai_segments + cross_sector_ai | EPS +51% YoY，backlog $48.5B(历史新高)，AI DC施工龙头。三个不同扫描器独立发现——收敛信号。 | ★★★★☆ |
| 7 | **MU** (Micron) | supply_chain_full + eps_revision_scan | L2 HBM层F9 T1，EPS revision +69%，12-14x Fwd PE是全链条最低估值之一。 | ★★★★☆ |
| 8 | **GLW** (Corning) | hidden_ai_segments | Meta $60B光纤合同把周期性业务变成contracted revenue，Optical +36% vs 总营收+18%。玻璃框架折价明显。 | ★★★★☆ |
| 9 | **MIRM** (Mirum Pharma) | nokia_breakouts | 罕见病，Phase 2b达主终点，volume 6.14x爆量，目标价+19-38%，F9 T1。与AI完全无关——纯粹sector外alpha。 | ★★★☆☆ |
| 10 | **GTM/ZI** (ZoomInfo) | short_universe | 业务模式失效，Mizuho目标$3(从$10下调)，指引砍$60M，short interest仅8%无squeeze风险。做空universe最清晰标的。 | ★★★☆☆ |

**值得注意但未进Top10**: NRG(-5.1% YTD但AI电力敞口大)、AMAT(设备层最低估值~21x)、HXSCL(6x Fwd PE)、MSGS(事件驱动体育娱乐)

---

## 三、信息茧房诊断

### 已知宇宙 vs 发现系统外宇宙

| 分类 | Ticker | 占比 |
|------|--------|------|
| **已在portfolio中** | AAON, CLS, VST, GEV, AAPL, SPUT, CRM, INOD, MSTR | 9只 / 约14% |
| **发现系统新找到** | ETN, APH, EME, GLW, VSH, ORA, PWR, MU, MIRM, GTM, NRG, HXSCL, ASX, TSM, AMAT, VRT等 | 约56只 / 约86% |

**结论：86%的覆盖在发现系统外。信息茧房严重程度：高。**

### 茧房模式分析

**茧房1: Sector归类遮蔽**（最严重）
- 工业/承包商（ETN/EME/PWR）被"工业股框架"排除在AI universe之外
- APH被"工业连接器"框架排除，实际AI DC占比41%
- 这类错误模式在**hidden_ai_segments**和**cross_sector_ai**两个扫描器中被独立发现

**茧房2: 知名度偏差**
- 持续关注NVDA/TSMC等大名字，遗漏VRT(40x但orders+252%)、VSH(Nokia完美pattern)
- ORA(地热)、MIRM(罕见病)完全不在AI语境中，但Nokia扫描器捕获了它们

**茧房3: 做多偏向**
- 做空universe在系统启动前几乎空白（仅MSTR一只）
- short_universe扫描器一次性发现GTM/WDAY/DXC等9个结构性做空候选

**茧房4: 美国本土偏向**
- 非美标的（SK Hynix HXSCL, ASX等）被global_non_us扫描器发现前完全空白

### 有多少个扫描器发现了portfolio外的actionable机会？

**全部7个扫描器均发现了portfolio外的actionable机会（7/7）**

最强表现:
- eps_revision_scan: 24个新发现（80%为完全盲区）
- nokia_breakouts: 16个新发现（100%为完全盲区，全sector外）
- cross_sector_ai: 14个新发现（100%跨sector）
- hidden_ai_segments: 9个新发现（100%，且质量最高——ETN/EME/APH都是T1）

---

## 四、如果当时有Discovery System V1.0，哪些发现会更早/更系统化？

| 发现 | 实际发现方式 | V1.0何时能发现 | 节省时间 |
|------|------------|---------------|---------|
| AAON (S级核心持仓) | 临时研究 | EPS revision扫描（+65%）+ Nokia扫描（backlog +105%）| 可能提前1-2周入场 |
| VST (A+级核心持仓) | 临时研究 | EPS revision扫描（能源板块YTD+46%系统信号）| 提前识别整个Power sector |
| CLS (A+级) | 临时研究 | EPS revision扫描 + supply_chain(L7服务器层) | 更早加仓机会 |
| **ETN (未建仓)** | hidden_ai_segments首次发现 | 无旧系统，完全盲区 | 从未发现→现在发现 |
| **APH (未建仓)** | hidden_ai_segments首次发现 | 无旧系统，完全盲区 | 从未发现→现在发现 |
| **VSH (未建仓)** | nokia_breakouts首次发现 | 无旧系统，完全盲区 | 从未发现→现在发现 |
| GEV (已在portfolio) | Day 1建仓 | eps_revision_scan(+109%)会更早/更高conviction | 可能更早加仓至更高权重 |

---

## 五、扫描器有效性排名（按发现质量）

| 排名 | 扫描器 | 核心优势 | 局限 |
|------|--------|---------|------|
| 1 | **hidden_ai_segments** | 发现质量最高，ETN/EME/APH均T1，供给端优先框架完美适配 | 覆盖数量少（9只），需要人工识别masking效应 |
| 2 | **cross_sector_ai** | Sector覆盖最广，发现了NRG等完全被遗忘的标的 | 部分标的已定价（POWL +430%），需要价格反应过滤 |
| 3 | **eps_revision_scan** | 数量最多，定量信号强，EPS revision是最可追踪的客观指标 | 部分已是共识（GOOGL/META），需要盲区过滤层 |
| 4 | **nokia_breakouts** | 跨sector最广，发现了MIRM/MSGS等完全意外的标的，技术+基本面结合 | 部分已涨很多（FLNC +98%），入场时机过滤重要 |
| 5 | **short_universe** | 填补做空宇宙空白，GTM/WDAY逻辑清晰 | 9只中深度不均，需要独立DD |
| 6 | **supply_chain_full** | 系统性框架价值高，10层分析是选股地图而非选股列表 | 大公司为主（NVDA/TSMC），已知名字占多数 |
| 7 | **global_non_us** | 发现HXSCL(6x PE)等极端低估，填补非美盲区 | 流动性限制使大部分不可操作（OTC Pink），ADR等流动性需要关注 |

---

## 六、核心结论

**Discovery System V1.0的验证结论**: 有效。

1. **茧房程度量化**: 在系统运行前，86%可覆盖的actionable机会在"已知宇宙"之外。
2. **最大alpha缺口**: 工业/承包商sector的DELL型masking机会（ETN/EME/APH）——这些标的有最高的"基本面强劲但市场框架错误"程度，是最纯粹的信息不对称。
3. **系统性遗漏**: 做空universe（仅靠临时判断发现MSTR）；非美标的（HXSCL的Korea Discount）；基于技术面的跨sector发现（Nokia scanner）。
4. **立即行动建议**:
   - ETN: 最优先深研，DC orders +240% vs 总营收+17%是目前所有扫描中gap最大的
   - APH: IT Datacom +99%，连接器框架遮蔽，当前可进入
   - VSH: Nokia pattern最清晰，book-to-bill 1.34，等回调$40-43入场

---

*Claude分析意见。数据来源见各原始discovery文件。*

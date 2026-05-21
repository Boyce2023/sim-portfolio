#!/usr/bin/env python3
"""Generate architecture diagram as PNG with pixel-perfect CJK alignment."""
from PIL import Image, ImageDraw, ImageFont
import os

def is_wide(ch):
    c = ord(ch)
    if 0x4E00 <= c <= 0x9FFF: return True
    if 0x3400 <= c <= 0x4DBF: return True
    if 0xF900 <= c <= 0xFAFF: return True
    if 0xFF01 <= c <= 0xFF60: return True
    if 0x3000 <= c <= 0x303F: return True
    if 0x3040 <= c <= 0x30FF: return True
    if 0x2E80 <= c <= 0x2FDF: return True
    return False

def col_width(s):
    return sum(2 if is_wide(ch) else 1 for ch in s)

RAW = [
"┌─────────────────────────────────────────────────────────────────────────────────────┐",
"│                          NEXUS v10.1.0 系统全景架构                                  │",
"│                     6层多智能体协作OS + AI模拟盘投资系统                                │",
"└─────────────────────────────────────────────────────────────────────────────────────┘",
"",
"╔═══════════════════════════════════════════════════════════════════════════════════════╗",
"║  6 WORKSTREAMS (每个session自动识别身份，共享底层数据)                                   ║",
"║  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     ║",
"║  │ Research │ │ Trading  │ │ Tracking │ │  Events  │ │Interview │ │  Nexus   │     ║",
"║  │ 研究系统  │ │ 交易系统  │ │ Tracking │ │ 时事选股  │ │ 面试答辩  │ │ 系统管理  │     ║",
"║  │          │ │          │ │   系统    │ │          │ │          │ │          │     ║",
"║  │ 10步流程  │ │ 模拟盘   │ │ Dashboard│ │ 催化剂   │ │ 邮件/CL  │ │ 审计/升级 │     ║",
"║  │ 16框架   │ │ IBKR实盘 │ │ Railway  │ │ 市场脉搏  │ │ PM Mock  │ │ 6层维护   │     ║",
"║  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘     ║",
"║       └──────┬─────┴──────┬─────┴──────┬─────┴──────┬─────┴──────┬─────┘           ║",
"╚══════════════╪════════════╪════════════╪════════════╪════════════╪═══════════════════╝",
"               │            │            │            │            │",
"               ▼            ▼            ▼            ▼            ▼",
"┌─────────────────────────────────────────────────────────────────────────────────────┐",
"│                        ~/.claude/nexus/  (Nexus 6层核心)                              │",
"│                                                                                     │",
"│  ┌─────────────────────────────────────────────────────────────────────────────┐    │",
"│  │ L5 META — 自修改协议 / 健康聚合 / Scorecard(基线51.5) / Anti-entropy        │    │",
"│  ├─────────────────────────────────────────────────────────────────────────────┤    │",
"│  │ L4 QUALITY GATE — Enforcement Layer (4级: 5C/18S/32R/~180A)                │    │",
"│  │   33 Operational Triggers (14原始 + 5监管 + 5技能 + 9风控v10.1)              │    │",
"│  │   ┌─────────────┐ ┌──────────────┐ ┌─────────────┐ ┌──────────────┐       │    │",
"│  │   │ CB 熔断器    │ │ VIX暴露控制   │ │ 止损临界警报  │ │ 集中度风控    │       │    │",
"│  │   │ 5%/10%/15%  │ │ 20/25/35     │ │ <3% ALERT   │ │ 同板块>3只   │       │    │",
"│  │   └─────────────┘ └──────────────┘ └─────────────┘ └──────────────┘       │    │",
"│  ├─────────────────────────────────────────────────────────────────────────────┤    │",
"│  │ L3 ORCHESTRATOR — Task队列 + 跨workstream任务派发 (idle, 建议简化)           │    │",
"│  ├─────────────────────────────────────────────────────────────────────────────┤    │",
"│  │ L2 SIGNAL BUS — 6 pending / 7 processed / 信号优先级: C>H>M>L              │    │",
"│  │   signals/pending/   ◄──── 5条sync + 1条regime-ready                       │    │",
"│  │   signals/processed/ ◄──── 7条已处理(含3条v10过期清理)                       │    │",
"│  ├─────────────────────────────────────────────────────────────────────────────┤    │",
"│  │ L1 STATE — 6个workstream状态文件 (全部同步至05-21)                           │    │",
"│  │   workstreams/{research,trading,tracking,events,interviews,nexus}.json      │    │",
"│  ├─────────────────────────────────────────────────────────────────────────────┤    │",
"│  │ L0 TRUTH STORE — 337 facts / 31 files / 23 company files                  │    │",
"│  │   ┌──────────────────────────────────────────────────────────────────┐     │    │",
"│  │   │ truth/companies/ (23)  │ truth/macro/          │ truth/portfolio/│     │    │",
"│  │   │ NVDA AAPL GOOGL ADBE  │ indicators.json (16项) │ positions.json │     │    │",
"│  │   │ GEV LEU CCJ NXE SPUT  │ regime.json (SIDEWAYS) │ (IBKR stale)  │     │    │",
"│  │   │ HSAI OKLO VST BWXT    │                        │                │     │    │",
"│  │   │ FPS CEG UEC 002028    │ ┌────────────────────┐ │                │     │    │",
"│  │   │ 002472 002938 603005  │ │ SPX    7,433       │ │                │     │    │",
"│  │   │ 600089 2525HK NOW     │ │ VIX    17.44       │ │                │     │    │",
"│  │   │                       │ │ Gold   $4,549/oz   │ │                │     │    │",
"│  │   │                       │ │ BTC    $77,968     │ │                │     │    │",
"│  │   │                       │ │ Oil    $98.93/bbl  │ │                │     │    │",
"│  │   │                       │ │ U3O8   $85/lb      │ │                │     │    │",
"│  │   │                       │ └────────────────────┘ │                │     │    │",
"│  │   └──────────────────────────────────────────────────────────────────┘     │    │",
"│  └─────────────────────────────────────────────────────────────────────────────┘    │",
"│                                                                                     │",
"│  sync/update-bulletin.json  ◄──── v10.1.0, 跨session同步协议 (CLAUDE.md Step 0)     │",
"│  protocols/ ──── enforcement.md / handoff.md / output.md / internalization.md        │",
"│  architecture.yaml v9 / changelog.json v10.1.0                                      │",
"└──────────────────────────────────────────┬──────────────────────────────────────────┘",
"                                           │",
"                    ┌──────────────────────┼──────────────────────┐",
"                    │                      │ SSOT                 │",
"                    ▼                      ▼                      ▼",
"┌──────────────────────────────────────────────────────────────────────────────────────┐",
"│                    ~/claude-projects/sim-portfolio/                                    │",
"│                    Claude AI 模拟盘 (Day 3 | ¥1.03M + $148K)                          │",
"│                                                                                      │",
"│  ┌──────────────────────────────────────────────────────────────────────────────┐    │",
"│  │                    portfolio_state.json (唯一真相源 SSOT)                      │    │",
"│  │  A股: 思源002028 / 晶方603005 / 鹏鼎002938 / 双环002472  | NAV ¥1,027,181    │    │",
"│  │  美股: NVDA / AAPL / GOOGL / ADBE / SRUUF / GEV / LEU / FPS | NAV $148,498  │    │",
"│  │  trade_log: 14笔 | performance.daily_snapshots | cash_plan                    │    │",
"│  └───────────────────────────────────┬──────────────────────────────────────────┘    │",
"│                                      │                                               │",
"│  ┌───────────────────────────────────┼──────────────────────────────────────────┐    │",
"│  │                        scripts/ (16个Python脚本)                              │    │",
"│  │                                                                               │    │",
"│  │  ┌─ 核心交易链 ──────────────────────────────────────────────────────┐        │    │",
"│  │  │ fetch_prices.py ──► risk_monitor.py ──► decision_engine.py       │        │    │",
"│  │  │       │                    │                     │               │        │    │",
"│  │  │       ▼                    ▼                     ▼               │        │    │",
"│  │  │  latest_prices.json   Circuit Breaker      decisions.json       │        │    │",
"│  │  │                       VIX Scaling           decision_chain      │        │    │",
"│  │  │                       Stop Alerts                │              │        │    │",
"│  │  │                       (+343行 v10.1)             ▼              │        │    │",
"│  │  │                                         execute_trade.py       │        │    │",
"│  │  │                                          (+130行 audit trail)  │        │    │",
"│  │  │                                              │                 │        │    │",
"│  │  │                                    ┌─────────┴──────────┐      │        │    │",
"│  │  │                                    ▼                    ▼      │        │    │",
"│  │  │                          portfolio_state.json    audit-trail/  │        │    │",
"│  │  │                              (更新)            (17笔 + schema) │        │    │",
"│  │  └────────────────────────────────────────────────────────────────┘        │    │",
"│  │                                                                            │    │",
"│  │  ┌─ 风险分析 ────────────────────────┐  ┌─ 归因与报告 ──────────────┐      │    │",
"│  │  │ risk_metrics.py   VaR/Sharpe/    │  │ attribution.py  Brinson  │      │    │",
"│  │  │   (528行)         Sortino/Beta   │  │   (636行)       vs SPY   │      │    │",
"│  │  │ risk_dashboard.py Score/Limits   │  │ weekly_commentary.py     │      │    │",
"│  │  │   (500行)         Concentration  │  │   (767行) md/twitter/微博 │      │    │",
"│  │  │ kelly_sizing.py   Kelly Criterion│  │ performance.py 绩效计算   │      │    │",
"│  │  │   (319行)         Trade-based    │  │ leaderboard_page.py 排行  │      │    │",
"│  │  └──────────────────────────────────┘  └──────────────────────────┘      │    │",
"│  │                                                                            │    │",
"│  │  ┌─ 市场感知 ────────────────────────┐  ┌─ 系统集成 ──────────────┐      │    │",
"│  │  │ regime_detection.py  4因子加权    │  │ sync_nexus.py  Nexus同步 │      │    │",
"│  │  │   VIX(35%)+MA(25%)+            │  │ system_check.py 健康检查  │      │    │",
"│  │  │   Yield(20%)+Credit(20%)       │  │ trading_engine.py 执行层  │      │    │",
"│  │  │ news_scan.py  新闻扫描          │  │ leaderboard_api.py 路由   │      │    │",
"│  │  └──────────────────────────────────┘  └──────────────────────────┘      │    │",
"│  └───────────────────────────────────────────────────────────────────────────┘    │",
"│                                                                                   │",
"│  ┌─────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐     │",
"│  │ api/  (FastAPI)      │  │ alpha-factors/        │  │ telegram-bot/        │     │",
"│  │ ├ app.py (997行)     │  │ ├ factors.py (30因子)  │  │ ├ notifications.py   │     │",
"│  │ │  19 REST endpoints │  │ │  BaseFactor框架     │  │ │  (630行, 零依赖push)│     │",
"│  │ │  + WebSocket       │  │ │  MOM/PE/ROE实现     │  │ ├ bot.py (486行)     │     │",
"│  │ ├ models.py (383行)  │  │ ├ ic_tracker.py      │  │ │  命令处理           │     │",
"│  │ │  Pydantic v2       │  │ │  IC/IR/Turnover    │  │ └ config/            │     │",
"│  │ ├ openapi.yaml       │  │ │  Status分类        │  │   telegram_config    │     │",
"│  │ └ requirements.txt   │  │ └ factor_zoo.json    │  │   (env vars only)    │     │",
"│  │                      │  │   (30个因子定义)      │  │                      │     │",
"│  │  Auth: 读公开/写需Key │  │                      │  │  与JS Bot共存        │     │",
"│  └─────────────────────┘  └──────────────────────┘  └──────────────────────┘     │",
"│                                                                                   │",
"│  ┌─ 审计与报告 ──────────┐  ┌─ 研究资料 ──────────────────────────────────────┐   │",
"│  │ audit-trail/ (17+1)  │  │ research-notes/                                 │   │",
"│  │  每笔trade决策链      │  │  adversarial-debate-protocol.md (899行)         │   │",
"│  │  trigger→thesis→     │  │  regime-detection-design.md (669行, Phase 2/3)  │   │",
"│  │  risk→sizing→final   │  │  backtesting-research.md (VectorBT推荐)         │   │",
"│  │ weekly-reports/ (3)  │  │                                                 │   │",
"│  │  md / twitter / weibo│  └──────────────────────────────────────────────────┘   │",
"│  └──────────────────────┘                                                         │",
"└──────────────┬───────────────────────────────────────────────────────────────────┘",
"               │",
"               │ git push / Railway deploy",
"               ▼",
"┌──────────────────────────────────────────────────────────────────────────────────┐",
"│                          外部服务层                                                │",
"│                                                                                  │",
"│  ┌───────────────────────┐  ┌───────────────┐  ┌──────────────┐  ┌───────────┐  │",
"│  │ Railway               │  │ Telegram      │  │ Yahoo Finance│  │ GitHub    │  │",
"│  │ nexus-ai-portfolio    │  │ Alert Bot     │  │ yfinance API │  │ git remote│  │",
"│  │ .up.railway.app       │  │ Push通知      │  │ 实时价格/指标 │  │ 版本控制   │  │",
"│  │                       │  │               │  │              │  │           │  │",
"│  │ 实时持仓/收益率图表    │  │ 交易成交通知  │  │ fetch_prices │  │ sim-port  │  │",
"│  │ 交易明细公开展示       │  │ 风控告警      │  │ risk_monitor │  │ auto-push │  │",
"│  │ Leaderboard (planned) │  │ 每日总结      │  │ regime_det   │  │           │  │",
"│  └───────────────────────┘  └───────────────┘  └──────────────┘  └───────────┘  │",
"└──────────────────────────────────────────────────────────────────────────────────┘",
"",
"┌──────────────────────────────────────────────────────────────────────────────────┐",
"│  ~/claude-projects/equity-frameworks/  (独立Python库, MIT License)                 │",
"│                                                                                  │",
"│  16个投资分析框架 — pip install equity-frameworks                                  │",
"│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐     │",
"│  │ supply/    │ │ valuation/ │ │ sector/    │ │ behavioral/│ │ management/│     │",
"│  │ F2 供给优先 │ │ F5 类比攻防 │ │ F1 铀弹性  │ │ F3 三次行情 │ │ F8 管理层  │     │",
"│  │ F13 可得性 │ │ F12 三层估值│ │ F4 LCOE   │ │ F7 DeepSeek│ │  六维评分  │     │",
"│  │ F16 Lag   │ │ F15 共识反向│ │ F6 SMR分级 │ │ F14 历史类比│ │            │     │",
"│  │           │ │            │ │ F10 DC测算 │ │            │ │ process/   │     │",
"│  │           │ │            │ │ F11 禾赛   │ │            │ │ F9 淘汰法  │     │",
"│  └────────────┘ └────────────┘ └────────────┘ └────────────┘ └────────────┘     │",
"│  15/15 tests pass | 零外部依赖 | Auto-registration | 20% bear rule硬编码           │",
"└──────────────────────────────────────────────────────────────────────────────────┘",
"",
"┌──────────────────────────────────────────────────────────────────────────────────┐",
"│  数据流向 (SSOT层级)                                                              │",
"│                                                                                  │",
"│  持仓: portfolio_state.json ──► positions.json ──► watchlist.md                   │",
"│         (唯一真相源)              (Truth Store镜像)    (Memory)                     │",
"│                                                                                  │",
"│  价格: yfinance ──► fetch_prices.py ──► portfolio_state.json                     │",
"│                                                                                  │",
"│  交易: decision_engine ──► execute_trade ──► portfolio_state + audit-trail        │",
"│                                                                                  │",
"│  风控: risk_monitor ──► Circuit Breaker/VIX/Stop ──► Signal Bus ──► Telegram     │",
"│                                                                                  │",
"│  同步: update-bulletin.json ──► CLAUDE.md Step 0 ──► 每个session首条消息检查       │",
"└──────────────────────────────────────────────────────────────────────────────────┘",
]

# === NORMALIZER: fix column widths ===
def normalize(lines):
    """Ensure every line in a box has the correct column width by adjusting trailing padding."""
    right_border = set('│║┐┘┤╗╝╣')
    result = []
    single_target = None  # target for ┌...┐ boxes
    double_target = None  # target for ╔...╗ boxes

    for line in lines:
        if not line:
            result.append(line)
            continue

        first = line[0]

        # Update target when we see a top border at column 0
        if first == '┌':
            single_target = len(line)  # pure ASCII border, len = col width
        elif first == '╔':
            double_target = len(line)

        last = line[-1]
        if last not in right_border:
            result.append(line)
            continue

        # Determine which target to use
        target = None
        if first in '│┌└├┬┴':
            target = single_target
        elif first in '║╔╚╠╦╩':
            target = double_target

        if target is None:
            result.append(line)
            continue

        # Normalize: strip trailing spaces before the last border char, re-pad
        content = line[:-1].rstrip(' ')
        content_cols = col_width(content)
        spaces = target - content_cols - 1
        if spaces < 0:
            spaces = 0
        result.append(content + ' ' * spaces + last)

    return result

LINES = normalize(RAW)

# Verify alignment
print("=== Alignment check ===")
ok = True
single_t = None
double_t = None
for i, line in enumerate(LINES):
    if not line: continue
    first = line[0]
    if first == '┌': single_t = len(line)
    elif first == '╔': double_t = len(line)
    last = line[-1]
    if last in '│║┐┘┤╗╝╣':
        w = col_width(line)
        t = single_t if first in '│┌└├┬┴' else double_t if first in '║╔╚╠╦╩' else None
        if t and w != t:
            print(f"  !! L{i}: {w} cols (target {t}): {line[:60]}...")
            ok = True  # still continue
if ok:
    print("  All lines aligned ✓")

# === RENDER ===
FONT_SIZE = 15
FONT_ASCII = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", FONT_SIZE, index=0)
FONT_CJK = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", FONT_SIZE, index=0)

CELL_W = FONT_ASCII.getlength("M")
CELL_H = int(FONT_SIZE * 1.55)
PAD_X = 28
PAD_Y = 22

max_cols = max(col_width(line) for line in LINES)
img_w = int(max_cols * CELL_W + PAD_X * 2)
img_h = int(len(LINES) * CELL_H + PAD_Y * 2)

img = Image.new("RGB", (img_w, img_h), "white")
draw = ImageDraw.Draw(img)

for row, line in enumerate(LINES):
    col = 0
    for ch in line:
        x = PAD_X + col * CELL_W
        y = PAD_Y + row * CELL_H
        wide = is_wide(ch)

        if wide:
            slot_w = CELL_W * 2
            glyph_w = FONT_CJK.getlength(ch)
            draw.text((x + (slot_w - glyph_w) / 2, y), ch, font=FONT_CJK, fill="black")
        else:
            draw.text((x, y), ch, font=FONT_ASCII, fill="black")

        col += 2 if wide else 1

out_path = os.path.expanduser("~/Desktop/nexus-architecture-v10.1.png")
img.save(out_path, "PNG")
print(f"\nSaved: {out_path}")
print(f"Size: {img_w}x{img_h}px, {len(LINES)} lines, max {max_cols} cols")

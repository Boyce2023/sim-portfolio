#!/bin/bash
# B策略消息回测一键跑批: 2025全年+上下半年+2026Q1逐月样本外
cd /Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban
OUT=news_backtest_report.txt
{
echo "生成时刻: $(date '+%Y-%m-%d %H:%M')"
echo ""
echo "████ 阶段1: 全量涨停×公告类型×前瞻收益 (2025全年) ████"
python3 news_study.py univ2025.db
echo ""
echo "████ 阶段2: 2025全年 ████"
python3 engine_news.py univ2025.db 2025-01-01 2025-12-31
echo ""
echo "████ 阶段2: 2025上半年 ████"
python3 engine_news.py univ2025.db 2025-01-01 2025-06-30
echo ""
echo "████ 阶段2: 2025下半年 ████"
python3 engine_news.py univ2025.db 2025-07-01 2025-12-31
echo ""
echo "████ 样本外: 2026-01 ████"
python3 engine_news.py univ202601.db 2026-01-01 2026-01-31
echo ""
echo "████ 样本外: 2026-02 ████"
python3 engine_news.py univ202602.db 2026-02-01 2026-02-28
echo ""
echo "████ 样本外: 2026-03 ████"
python3 engine_news.py univ202603.db 2026-03-01 2026-03-31
} 2>&1 | grep -v "拦截器\|it/s" | tee $OUT
echo "REPORT_DONE → $OUT"

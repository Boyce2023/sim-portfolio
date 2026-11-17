# A股一进二实盘生产脚本归档清单与现役基准（2026-11-12）

## 一、现役生产脚本基准（全系统唯一口径）
- 现役生产实盘脚本：`sim-portfolio/scripts/fast_1to2_today.py`
- 现役运行环境：`/opt/homebrew/bin/python3.13`
- 定时守护任务：LaunchAgent `com.claude.1to2-premarket-sync`（每日 16:30 与 08:45 触发 `fast_1to2_today.py --sync-all`）
- 缓存路径：`sim-portfolio/data/1to2_premarket_cache.json`

## 二、归档状态与说明
- 经过全量扫描，历史上散落的早期一进二盘前与盘中分散脚本（如早期实验性单点扫描逻辑）已完全收敛整合进现役生产脚本 `fast_1to2_today.py`。
- `scripts/` 目录中除现役定版 `fast_1to2_today.py` 外，不存在其他独立的过时一进二生产脚本。
- 本归档目录作为全链路规范化归档留存点，供后续版本淘汰脚本标准归档使用。

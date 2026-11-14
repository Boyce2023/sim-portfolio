# -*- coding: utf-8 -*-
"""
astock2_trainer_css.py
高对比度、零圆角（border-radius: 0 !important）、水平细线表格与清爽金融白底样式
严格还原第一版左宽右窄双栏布局与黑底小方标
"""

CSS_FULL = """
* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    border-radius: 0 !important;
}
body {
    background-color: #f3f4f6;
    color: #111827;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    font-size: 13px;
    line-height: 1.5;
    padding: 16px;
}
.container {
    max-width: 1440px;
    margin: 0 auto;
}

/* 顶部导航与全局战绩 */
.top-header {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-bottom: 2px solid #111827;
    padding: 12px 18px;
    margin-bottom: 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
}
.brand-title {
    font-size: 17px;
    font-weight: 800;
    color: #111827;
    display: flex;
    align-items: center;
    gap: 8px;
}
.brand-tag {
    background: #111827;
    color: #ffffff;
    font-size: 11px;
    padding: 2px 6px;
    font-weight: 700;
}
.stats-summary {
    display: flex;
    gap: 16px;
    align-items: center;
    font-size: 12px;
}
.stat-pill {
    display: flex;
    flex-direction: column;
}
.stat-label {
    color: #6b7280;
    font-size: 10px;
}
.stat-val {
    font-weight: 800;
    font-family: monospace;
    font-size: 14px;
}

/* 工具栏与控制栏 */
.toolbar {
    background: #ffffff;
    border: 1px solid #d1d5db;
    padding: 10px 16px;
    margin-bottom: 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
}
.toolbar-group {
    display: flex;
    align-items: center;
    gap: 8px;
}
.toolbar-btn {
    background: #f9fafb;
    border: 1px solid #d1d5db;
    color: #374151;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
}
.toolbar-btn:hover {
    background: #f3f4f6;
    border-color: #9ca3af;
}
.toolbar-btn.primary {
    background: #111827;
    color: #ffffff;
    border-color: #111827;
}
.toolbar-btn.primary:hover {
    background: #374151;
}
.mode-select {
    padding: 4px 8px;
    font-size: 12px;
    font-weight: 600;
    border: 1px solid #d1d5db;
    background: #ffffff;
    outline: none;
}
.jump-input {
    width: 55px;
    padding: 4px 6px;
    font-size: 12px;
    font-weight: 700;
    border: 1px solid #d1d5db;
    text-align: center;
}

/* 关卡横幅与大盘趋势胶囊 */
.case-banner {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-left: 4px solid #111827;
    padding: 12px 18px;
    margin-bottom: 14px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
}
.case-title {
    font-size: 16px;
    font-weight: 800;
    color: #111827;
    margin-bottom: 3px;
}
.case-sub {
    font-size: 12px;
    color: #4b5563;
}
.case-phase-pill {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    color: #1e40af;
    padding: 6px 14px;
    font-size: 13px;
    font-weight: 700;
    display: flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
}

/* 主面板网格与黑底模块方标 */
.section-card {
    background: #ffffff;
    border: 1px solid #d1d5db;
    padding: 14px;
    margin-bottom: 14px;
}
.section-header {
    font-size: 13px;
    font-weight: 800;
    color: #111827;
    border-bottom: 1px solid #e5e7eb;
    padding-bottom: 8px;
    margin-bottom: 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.module-tag {
    background: #111827;
    color: #ffffff;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 700;
    display: inline-block;
}

/* 模块一：前6个月大势 + 前30日短线 + 昨日情绪 三栏并排 (38% : 36% : 26%) */
.grid-module-1 {
    display: grid;
    grid-template-columns: 38fr 36fr 26fr;
    gap: 12px;
}
.sentiment-metrics-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
}
.sentiment-metrics-table td {
    padding: 5px 8px;
    border-bottom: 1px solid #e5e7eb;
}
.sentiment-label {
    color: #4b5563;
    font-weight: 600;
}
.sentiment-value {
    font-family: monospace;
    font-weight: 800;
    text-align: right;
    font-size: 12px;
}
.red { color: #dc2626 !important; }
.green { color: #16a34a !important; }
.gold { color: #d97706 !important; }

/* 板块归属标签（严谨区分沪深主板10%与双创20%） */
.plate-badge {
    font-size: 10px;
    font-weight: 700;
    padding: 1px 5px;
    margin-left: 5px;
    white-space: nowrap;
    display: inline-block;
    vertical-align: middle;
}
.plate-sh {
    background: #fef2f2;
    color: #b91c1c;
    border: 1px solid #fecaca;
}
.plate-sz {
    background: #eff6ff;
    color: #1d4ed8;
    border: 1px solid #bfdbfe;
}
.plate-cyb {
    background: #f5f3ff;
    color: #7c3aed;
    border: 1px solid #ddd6fe;
}
.plate-kcb {
    background: #fff7ed;
    color: #c2410c;
    border: 1px solid #ffedd5;
}
.plate-bj {
    background: #f3f4f6;
    color: #374151;
    border: 1px solid #d1d5db;
}

/* 模块二：3 张题材卡 */
.themes-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 12px;
}
.theme-card {
    background: #ffffff;
    border: 1px solid #d1d5db;
    padding: 12px;
    cursor: pointer;
    transition: all 0.15s ease;
}
.theme-card:hover {
    border-color: #9ca3af;
    background: #fafafa;
}
.theme-card.selected {
    border: 2px solid #111827 !important;
    background: #fcfcfd;
}

/* 模块三：K 线图网格与表格 */
.kline-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 14px;
}
.stock-kline-card {
    background: #ffffff;
    border: 1px solid #d1d5db;
}
.stock-code-tag {
    background: #111827;
    color: #ffffff;
    font-size: 11px;
    font-weight: 800;
    padding: 2px 6px;
    display: inline-block;
}

/* 表格：水平细线，零竖线 */
.stocks-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11.5px;
    background: #ffffff;
}
.stocks-table th {
    background: #f9fafb;
    border-top: 1px solid #d1d5db;
    border-bottom: 1px solid #111827;
    padding: 7px 7px;
    text-align: left;
    font-weight: 700;
    color: #374151;
    white-space: nowrap;
}
.stocks-table td {
    border-bottom: 1px solid #e5e7eb;
    padding: 7px 7px;
    vertical-align: middle;
}
.stocks-table tr:hover td {
    background: #f9fafb;
}

/* 模块四：作答按钮 */
.action-buttons {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
    margin-top: 12px;
}
.choice-btn {
    background: #ffffff;
    border: 1px solid #d1d5db;
    padding: 12px 10px;
    font-size: 13px;
    font-weight: 800;
    color: #111827;
    cursor: pointer;
    text-align: center;
    transition: all 0.15s ease;
}
.choice-btn:hover {
    background: #f3f4f6;
    border-color: #9ca3af;
}
.choice-btn.selected-choice {
    background: #111827 !important;
    color: #fde68a !important;
    border-color: #111827 !important;
}
.choice-btn.btn-empty {
    border-left: 3px solid #d97706;
}

/* 模块五：揭晓复盘卡 */
.result-card {
    background: #ffffff;
    border: 1px solid #d1d5db;
    margin-top: 14px;
}
.result-header {
    padding: 12px 16px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.postmortem-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    padding: 14px;
}

/* 锁屏界面样式 */
.lock-screen-wrapper {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 80vh;
}
.lock-card {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-top: 4px solid #111827;
    padding: 36px 32px;
    max-width: 460px;
    width: 100%;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}
.lock-title {
    font-size: 18px;
    font-weight: 800;
    color: #111827;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.lock-desc {
    font-size: 12px;
    color: #6b7280;
    line-height: 1.6;
    margin-bottom: 20px;
}
.lock-input {
    width: 100%;
    padding: 10px 14px;
    font-size: 15px;
    border: 1px solid #d1d5db;
    margin-bottom: 12px;
    font-family: monospace;
    outline: none;
}
.lock-input:focus {
    border-color: #111827;
}
.lock-btn {
    width: 100%;
    background: #111827;
    color: #ffffff;
    border: none;
    padding: 12px;
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
}
.lock-btn:hover {
    background: #374151;
}
"""

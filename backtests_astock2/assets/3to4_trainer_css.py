# -*- coding: utf-8 -*-
"""三进四盘感刷题机专用高对比度极简样式表"""

CSS_3TO4 = """
* { box-sizing: border-box; margin: 0; padding: 0; border-radius: 0 !important; }
body { background: #f3f4f6; color: #111827; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif; font-size: 13px; line-height: 1.5; padding: 14px; }
.container { max-width: 1100px; margin: 0 auto; }
.top-header { background: #ffffff; border: 1px solid #d1d5db; border-bottom: 2px solid #111827; padding: 10px 16px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.brand-title { font-size: 16px; font-weight: 800; color: #111827; display: flex; align-items: center; gap: 8px; }
.brand-tag { background: #111827; color: #ffffff; font-size: 11px; padding: 2px 6px; font-weight: 700; }
.stats-summary { display: flex; gap: 14px; align-items: center; font-size: 12px; }
.stat-pill { display: flex; flex-direction: column; }
.stat-label { color: #6b7280; font-size: 10px; }
.stat-val { font-weight: 800; font-family: monospace; font-size: 13px; }
.toolbar { background: #ffffff; border: 1px solid #d1d5db; padding: 8px 14px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.toolbar-group { display: flex; align-items: center; gap: 6px; }
.toolbar-btn { background: #f9fafb; border: 1px solid #d1d5db; color: #374151; padding: 4px 10px; font-size: 12px; font-weight: 600; cursor: pointer; }
.toolbar-btn:hover { background: #f3f4f6; border-color: #9ca3af; }
.toolbar-btn.primary { background: #111827; color: #ffffff; border-color: #111827; }
.jump-input { width: 50px; padding: 3px 6px; font-size: 12px; font-weight: 700; border: 1px solid #d1d5db; text-align: center; }
.case-banner { background: #ffffff; border: 1px solid #d1d5db; border-left: 4px solid #111827; padding: 10px 16px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.case-title { font-size: 15px; font-weight: 800; color: #111827; }
.case-sub { font-size: 11.5px; color: #4b5563; }
.section-card { background: #ffffff; border: 1px solid #d1d5db; padding: 12px; margin-bottom: 12px; }
.section-header { font-size: 12.5px; font-weight: 800; color: #111827; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }
.module-tag { background: #111827; color: #ffffff; padding: 1px 5px; font-size: 10.5px; font-weight: 700; margin-right: 6px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 10px; }
.metric-box { background: #f9fafb; border: 1px solid #e5e7eb; padding: 6px 8px; }
.metric-box-title { color: #6b7280; font-size: 10.5px; font-weight: 600; margin-bottom: 2px; }
.metric-box-val { font-size: 12.5px; font-weight: 800; font-family: monospace; }
.kline-canvas { width: 100%; height: 160px; border: 1px solid #e5e7eb; background: #fafafa; display: block; }
.action-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.action-btn { background: #ffffff; border: 2px solid #d1d5db; padding: 14px 10px; font-size: 14px; font-weight: 800; color: #111827; cursor: pointer; text-align: center; }
.action-btn:hover { background: #f9fafb; border-color: #111827; }
.action-btn.hang { border-color: #2563eb; color: #1d4ed8; background: #eff6ff; }
.action-btn.hang:hover { background: #dbeafe; }
.action-btn.empty { border-color: #d97706; color: #b45309; background: #fffbeb; }
.action-btn.empty:hover { background: #fef3c7; }
.action-btn.selected { background: #111827 !important; color: #fde68a !important; border-color: #111827 !important; }
.result-card { background: #ffffff; border: 1px solid #d1d5db; border-top: 3px solid #111827; padding: 14px; margin-top: 12px; }
.result-status { padding: 8px 12px; font-weight: 800; font-size: 13.5px; margin-bottom: 10px; }
.result-status.correct { background: #ecfdf5; border: 1px solid #10b981; color: #047857; }
.result-status.wrong { background: #fef2f2; border: 1px solid #ef4444; color: #b91c1c; }
.result-detail-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 10px; }
.breakdown-box { background: #f9fafb; border: 1px solid #e5e7eb; padding: 8px; font-size: 11.5px; line-height: 1.6; margin-bottom: 10px; }
.lock-screen-wrapper { display: flex; justify-content: center; align-items: center; min-height: 80vh; }
.lock-card { background: #ffffff; border: 1px solid #d1d5db; border-top: 4px solid #111827; padding: 32px 28px; max-width: 440px; width: 100%; }
.lock-title { font-size: 17px; font-weight: 800; color: #111827; margin-bottom: 8px; }
.lock-desc { font-size: 11.5px; color: #6b7280; line-height: 1.6; margin-bottom: 18px; }
.lock-input { width: 100%; padding: 8px 12px; font-size: 14px; border: 1px solid #d1d5db; margin-bottom: 10px; font-family: monospace; outline: none; }
.lock-btn { width: 100%; background: #111827; color: #ffffff; border: none; padding: 10px; font-size: 13px; font-weight: 700; cursor: pointer; }
.red-txt { color: #dc2626 !important; }
.green-txt { color: #16a34a !important; }
.gold-txt { color: #d97706 !important; }
.blue-txt { color: #2563eb !important; }
"""

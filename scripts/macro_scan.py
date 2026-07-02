# /// script
# dependencies = ["yfinance"]
# ///
"""
美股完整扫描 — 宏观模块 (macro_scan.py)
================================================
"美股全面扫描"流程的固定第1步(自上而下)。
个股发现(bottom-up)之前先跑这个,建立宏观背景。

输出:
  1. 核心宏观指标 (利率/VIX/DXY/商品/股指)
  2. Regime判断 (VIX+收益率曲线)
  3. 关键宏观flag (利率方向/风险偏好/曲线形态)
  4. 未来关键宏观事件提醒

用法: uv run --script scripts/macro_scan.py
"""
import yfinance as yf

IND = {
    '^TNX': ('US 10Y', '%'), '^FVX': ('US 5Y', '%'), '^IRX': ('US 13W', '%'),
    'DX-Y.NYB': ('DXY', ''), '^VIX': ('VIX', ''),
    'CL=F': ('WTI原油', '$'), 'GC=F': ('黄金', '$'),
    '^GSPC': ('S&P500', ''), '^NDX': ('纳指100', ''),
    'HYG': ('高收益债HYG', '$'),
}

print("=" * 52)
print("  宏观扫描 (完整扫描第1步 · 自上而下)")
print("=" * 52)

data = {}
for t, (name, unit) in IND.items():
    try:
        fi = yf.Ticker(t).fast_info
        p = fi.last_price
        prev = fi.previous_close
        pc = (p / prev - 1) * 100 if prev else 0
        data[name] = p
        arrow = "↑" if pc > 0 else ("↓" if pc < 0 else "→")
        print(f"  {name:12s}: {unit}{p:>10.2f}  {arrow}{pc:+.2f}%")
    except Exception as e:
        print(f"  {name:12s}: err ({str(e)[:25]})")

# ---- Regime判断 ----
vix = data.get('VIX', 20)
tnx = data.get('US 10Y', 0)
irx = data.get('US 13W', 0)
spread = tnx - irx  # 10Y - 13W 近似曲线
regime = 'BULL' if vix < 20 else ('SIDEWAYS' if vix < 28 else 'BEAR')
print(f"\n  Regime: {regime}  (VIX={vix:.1f})")
print(f"  10Y-13W曲线: {spread:+.2f}pct {'(倒挂!)' if spread < 0 else '(正常/陡峭)'}")

# ---- 关键宏观flag ----
print("\n  关键宏观flag:")
flags = []
if tnx > 4.4:
    flags.append(f"⚠️ 10Y={tnx:.2f}%>4.4% → 高估值科技/半导体逆风,利多低估值/独立beta")
elif tnx < 3.8:
    flags.append(f"10Y={tnx:.2f}%<3.8% → 降息交易占优,利多成长/杠杆")
if vix < 15:
    flags.append(f"VIX={vix:.1f}极低 → complacency,警惕黑天鹅")
elif vix > 25:
    flags.append(f"VIX={vix:.1f}偏高 → 恐慌,逆向机会浮现")
if spread < 0:
    flags.append("⚠️ 曲线倒挂 → 衰退信号,防御")
if not flags:
    flags.append("无极端信号,中性")
for f in flags:
    print(f"    {f}")

# ---- 关键宏观事件(定期更新此列表) ----
print("\n  未来关键宏观事件 (手动维护,每次扫描核对):")
EVENTS = [
    "7/6  关税60国评议截止 / 7/7 USTR听证",
    "7/8  Iran威胁升级窗口",
    "7/27-31 Mag7 capex指引 (半导体/AI组合最大单点)",
    "FOMC/CPI/NFP → 详见 catalyst_calendar.py --portfolio",
]
for e in EVENTS:
    print(f"    • {e}")

print("\n" + "=" * 52)
print("  → 宏观背景已建立,继续个股发现扫描")
print("=" * 52)

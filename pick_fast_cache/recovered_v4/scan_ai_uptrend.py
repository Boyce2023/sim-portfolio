import yfinance as yf
import pandas as pd

tickers = [
    'APP', 'PLTR', 'ANET', 'CLS', 'CRDO', 'VRT', 'GEV', 'CEG', 'VST',
    'DELL', 'HPE', 'WDC', 'STX', 'KLAC', 'LRCX', 'AMAT', 'ASML', 'TER',
    'COHR', 'CIEN', 'FN', 'MTSI', 'MPWR', 'QCOM', 'CSCO', 'IBM', 'ORCL',
    'SAP', 'NOW', 'PANW', 'CRWD', 'FTNT', 'ZS', 'NET', 'DDOG', 'IOT',
    'RDDT', 'SPOT', 'SE', 'MELI', 'DASH', 'SHOP', 'GLW', 'APH', 'TEL',
    'FLEX', 'JBL', 'NVDA', 'TSM', 'GOOG', 'META', 'AMZN', 'MSFT',
    'MU', 'SNDK', 'LITE', 'MRVL', 'AMD', 'INTC', 'AVGO', 'ARM'
]

df = yf.download(tickers, period='2y', progress=False)['Close']
rows = []
for t in tickers:
    if t not in df: continue
    h = df[t].dropna()
    if len(h) < 200: continue
    now = h.iloc[-1]
    hi2y = h.max()
    dd = (now / hi2y - 1) * 100
    r1m = (now / h.iloc[-22] - 1) * 100 if len(h)>=22 else 0
    r3m = (now / h.iloc[-63] - 1) * 100 if len(h)>=63 else 0
    r6m = (now / h.iloc[-126] - 1) * 100 if len(h)>=126 else 0
    r1y = (now / h.iloc[-252] - 1) * 100 if len(h)>=252 else (now / h.iloc[0] - 1) * 100
    r2y = (now / h.iloc[0] - 1) * 100
    if r1y > 15 and r2y > 40 and r6m > -5 and dd > -25:
        rows.append((t, now, r1m, r3m, r6m, r1y, r2y, dd))

print(f"Passed trend filter: {len(rows)}")
for t, now, r1m, r3m, r6m, r1y, r2y, dd in sorted(rows, key=lambda x: -x[5]):
    try:
        info = yf.Ticker(t).info
        mc = (info.get('marketCap') or 0) / 1e9
        if mc < 20: continue
        fpe = info.get('forwardPE')
        peg = info.get('pegRatio') or info.get('trailingPegRatio')
        rg = info.get('revenueGrowth')
        eg = info.get('earningsGrowth')
        gm = info.get('grossMargins')
        print(f"{t:6s} | mcap={mc:6.1f}B | now={now:7.2f} | 3m={r3m:+5.1f}% | 6m={r6m:+5.1f}% | 1y={r1y:+6.1f}% | 2y={r2y:+6.1f}% | DD={dd:+5.1f}% | fPE={str(round(fpe,1)) if fpe else 'N/A':>5s} | PEG={str(round(peg,2)) if peg else 'N/A':>5s} | revG={str(round(rg*100,1))+'%' if rg else 'N/A':>6s} | epsG={str(round(eg*100,1))+'%' if eg else 'N/A':>6s} | GM={str(round(gm*100,1))+'%' if gm else 'N/A':>5s}")
    except Exception as e:
        pass

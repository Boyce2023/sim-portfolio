import urllib.request, json, time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTDIR = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/research-notes/astock-database/2026-08-26/"

undisclosed = pd.read_csv(OUTDIR + "tech_undisclosed_raw.csv", dtype={'股票代码': str})
undisclosed['股票代码'] = undisclosed['股票代码'].str.zfill(6)
codes = undisclosed['股票代码'].tolist()

def prefix(code):
    if code.startswith(('60', '68', '90')):
        return 'sh'
    elif code.startswith(('00','30','20')):
        return 'sz'
    elif code.startswith(('4','8','9')) and len(code)==6 and code[0] in '48':
        return 'bj'
    else:
        return 'sz'

def fetch_20d_change(code, retries=2):
    sym = prefix(code) + code
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,26,'
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
            data = json.loads(urllib.request.urlopen(req, timeout=8).read())
            d = data.get('data', {}).get(sym, {})
            kl = d.get('day')
            if not kl or len(kl) < 21:
                return code, None, None, None, f'insufficient_bars({len(kl) if kl else 0})'
            closes = [float(r[2]) for r in kl]
            latest_close = closes[-1]
            close_20d_ago = closes[-21]
            latest_date = kl[-1][0]
            ago_date = kl[-21][0]
            chg_pct = round((latest_close/close_20d_ago - 1)*100, 2)
            return code, chg_pct, latest_date, ago_date, None
        except Exception as e:
            last_err = str(e)
            time.sleep(0.3)
    return code, None, None, None, last_err

results = []
t0 = time.time()
with ThreadPoolExecutor(max_workers=4) as ex:
    futs = {ex.submit(fetch_20d_change, c): c for c in codes}
    done_count = 0
    for fut in as_completed(futs):
        code, chg, ldate, adate, err = fut.result()
        results.append({'股票代码': code, 'chg_20d_pct': chg, 'latest_date': ldate, 'ago_date': adate, 'err': err})
        done_count += 1
        if done_count % 50 == 0:
            print(f"{done_count}/{len(codes)} done, elapsed {round(time.time()-t0,1)}s")

print(f"总耗时: {round(time.time()-t0,1)}s")
hist_df = pd.DataFrame(results)
hist_df.to_csv(OUTDIR + "tech_undisclosed_20d_change.csv", index=False, encoding='utf-8-sig')
print("失败数:", hist_df['err'].notna().sum())
print(hist_df[hist_df['err'].notna()])
print(hist_df.head(10).to_string())

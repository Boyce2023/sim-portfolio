import akshare as ak
import json

def sym(t):
    return ('sh'+t) if t.startswith(('6','9')) else ('sz'+t)

out = {}
for name, code in [('csi300','sh000300'), ('csi1000','sh000852')]:
    df = ak.stock_zh_index_daily(symbol=code)
    df['date'] = df['date'].astype(str)
    df = df[df['date'] >= '2026-06-01']
    out[name] = df[['date','close']].to_dict('records')

json.dump(out, open('index_data.json','w'))
print('done', {k: len(v) for k,v in out.items()})

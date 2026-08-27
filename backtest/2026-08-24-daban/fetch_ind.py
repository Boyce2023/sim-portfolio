#!/usr/bin/env python3
"""拉申万二级行业成分 → ind_map.json (股票代码→行业名)。
⛔轻度lookahead披露: 用当前分类回溯2025,个股行业归属变动极少,分析中已标注。"""
import requests,pandas as pd,json,time,warnings
from io import StringIO
warnings.filterwarnings('ignore')
import akshare as ak
H={'User-Agent':'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36'}
sw=ak.sw_index_second_info()
print('二级行业',len(sw),flush=True)
m={};bad=[]
for i,(_,r) in enumerate(sw.iterrows()):
    code=r['行业代码']
    for a in range(2):
        try:
            t=pd.read_html(StringIO(requests.get(f"https://legulegu.com/stockdata/index-composition?industryCode={code}",headers=H,timeout=15).text))[0]
            t.columns=[str(c).split('  {')[0].strip() for c in t.columns]
            for c in t['股票代码']: m[str(c).split('.')[0]]=r['行业名称']
            break
        except Exception as e:
            if a==1: bad.append(r['行业名称'])
            time.sleep(1)
    open('.hb_ind','w').write(f'{i+1}/{len(sw)} {r["行业名称"]} 累计{len(m)}只\n')
    time.sleep(0.1)
json.dump(m,open('ind_map.json','w'),ensure_ascii=False)
print('DONE 映射%d只 失败%d个行业:%s'%(len(m),len(bad),bad[:5]),flush=True)

#!/opt/homebrew/bin/python3.13
"""新浪概念板块成分股(当前名单, 存在'涨了才被归进概念'的前视偏差, 结果须标注). 单线程, 每请求间隔0.5秒"""
import requests,json,re,time
H={'User-Agent':'Mozilla/5.0','Referer':'http://finance.sina.com.cn'}
t=requests.get('http://vip.stock.finance.sina.com.cn/q/view/newFLJK.php?param=class',headers=H,timeout=15).content.decode('gbk','ignore')
nodes=json.loads(t[t.index('{'):t.rindex('}')+1])
out={}
for i,(k,v) in enumerate(nodes.items()):
    name=v.split(',')[1]; codes=[]
    for p in range(1,20):
        u=f'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page={p}&num=100&sort=symbol&asc=1&node={k}'
        for a in range(3):
            try: r=requests.get(u,headers=H,timeout=15).json(); break
            except Exception: time.sleep(2); r=None
        if not r: break
        codes+= [x['code'] for x in r]
        if len(r)<100: break
        time.sleep(0.5)
    out[name]=codes; time.sleep(0.5)
    if i%25==0: print(i,len(nodes),name,len(codes),flush=True)
json.dump(out,open('concept_members_sina.json','w'),ensure_ascii=False)
print('done',len(out))

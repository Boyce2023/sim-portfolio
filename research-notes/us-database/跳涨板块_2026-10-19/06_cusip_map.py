"""CUSIP→ticker: OpenFIGI(无key 每分钟25次 每次10条), 只取美国交易所普通股。存 cusip_map.json(可断点续)"""
import json, os, time, urllib.request
F=json.load(open('funds_13f.json'))
cus=sorted({m['cusip'] for f in F for m in f.get('moves') or []})
mp=json.load(open('cusip_map.json')) if os.path.exists('cusip_map.json') else {}
need=[c for c in cus if c not in mp]; print('待映射',len(need),'/',len(cus),flush=True)
for i in range(0,len(need),10):
    b=need[i:i+10]
    body=json.dumps([{'idType':'ID_CUSIP','idValue':c,'exchCode':'US'} for c in b]).encode()
    for a in range(5):
        try:
            r=json.load(urllib.request.urlopen(urllib.request.Request('https://api.openfigi.com/v3/mapping',data=body,headers={'Content-Type':'application/json'}),timeout=30)); break
        except Exception as e:
            time.sleep(15*(a+1)); r=None
    if r is None: print('失败',i); continue
    for c,x in zip(b,r):
        d=[y for y in x.get('data',[]) if y.get('marketSector')=='Equity']
        mp[c]=[(y.get('ticker'),y.get('securityType'),y.get('name')) for y in d][:3]
    if i%200==0:
        json.dump(mp,open('cusip_map.json','w')); print(i,flush=True)
    time.sleep(2.6)
json.dump(mp,open('cusip_map.json','w')); print('完成',len(mp),'有票',sum(1 for v in mp.values() if v))

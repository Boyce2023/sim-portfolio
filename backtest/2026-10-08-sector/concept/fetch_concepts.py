#!/opt/homebrew/bin/python3.13
"""东财概念板块成分股(当前名单, 有成分股后补的前视偏差, 结果需标注). 单线程慢拉, 防封源"""
import akshare as ak, json, time, sys
names=ak.stock_board_concept_name_em()
out={}; err=[]
for i,n in enumerate(names['板块名称'].tolist()):
    for k in range(3):
        try:
            df=ak.stock_board_concept_cons_em(symbol=n); out[n]=df['代码'].astype(str).tolist(); break
        except Exception as e: time.sleep(3); last=str(e)
    else: err.append(n)
    time.sleep(0.6)
    if i%50==0: print(i,len(names),len(out),len(err),flush=True)
json.dump(out,open('concept_members.json','w'),ensure_ascii=False)
print('done',len(out),'failed',len(err),err[:10])

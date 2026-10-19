"""开盘啦 异动提醒 > 严重异动 > 近期严重异动 全量历史 (apphis c=StockBidYiDong a=GetYDTPZFPL_W46_HisAll, Index 为偏移, 每页30)"""
import json,time
from kplget import get
allr=[]; idx=0; total=None
while True:
    d=json.loads(get('apphis',{'a':'GetYDTPZFPL_W46_HisAll','c':'StockBidYiDong','Index':idx}))
    L=d.get('List_His') or []; total=d.get('List_His_Total')
    if not L: break
    allr+=L; idx+=len(L)
    if total and idx>=int(total): break
    time.sleep(0.6)
json.dump({'total':total,'rows':allr},open('kpl_severe_his.json','w'),ensure_ascii=False)
print('总数',total,'拉到',len(allr),'日期',allr[-1][18],'到',allr[0][18])

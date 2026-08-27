#!/usr/bin/env python3
"""行业映射 v2 — 改用baostock(建univ库的同源数据源)。
⛔v1用legulegu逐行业抓,131个失败113个只覆盖14%,却照常打印DONE写文件——
   典型"有输出≠在工作"。本版一次性拉全量并强制校验覆盖率,不达标直接报错退出。"""
import baostock as bs, json, sys, signal
class TO(Exception): pass
signal.signal(signal.SIGALRM, lambda s,f:(_ for _ in ()).throw(TO()))
signal.alarm(120)
lg=bs.login(); print('login',lg.error_code,flush=True)
rs=bs.query_stock_industry()
m={}; n=0
while rs.next():
    r=rs.get_row_data()   # updateDate, code, code_name, industry, industryClassification
    n+=1
    code=r[1].split('.')[-1]
    if r[3]: m[code]=r[3]
bs.logout(); signal.alarm(0)
print('返回%d行 → 映射%d只'%(n,len(m)),flush=True)
if len(m)<3000:
    print('❌ 覆盖不足3000只,不写文件(防止又产出一个86%空的map)',flush=True); sys.exit(1)
json.dump(m,open('ind_map.json','w'),ensure_ascii=False)
import collections
print('行业数',len(set(m.values())),'| 前10:',collections.Counter(m.values()).most_common(10),flush=True)
print('✓ ind_map.json 已覆写',flush=True)

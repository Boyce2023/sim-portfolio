# -*- coding: utf-8 -*-
"""综合分引擎 v1.1 — 判断层(agent 50分) + 机械层(主脑自算 50分) = 0-100
⛔权重固定在本文件, 不由agent决定, 保证可复现+跨日可比。
⛔v1.1修正: 估值改用PEG(D8宪法: PEG唯一, Fwd PE禁止单独使用)。
   v1.0用纯Fwd PE的后果: AEM(FwdPE 17.3但PEG 2.54)拿8/10排第2, 正是当天按PEG筛掉的那只。
⛔v1.1修正: 供给侧权重2.2→2.5(供给侧优先是本框架第一权重; v1.0下TGT供给仅1分却靠机械层排#19)。"""
import json, os, statistics as st
D=os.path.dirname(os.path.abspath(__file__))
SPY30, SPY5 = 3.73, -1.37

def struct_score(x):
    p = 8 if x['brk'] else 0
    d3=x['dh3']; p += 8 if d3>=-2 else (6 if d3>=-8 else (3 if d3>=-15 else 0))
    d52=x['dh52']; p += 4 if d52>=-5 else (2 if d52>=-15 else 0)
    return p

def rs_score(x):
    e30=x['d30']-SPY30
    p = 12 if e30>=20 else (9 if e30>=10 else (6 if e30>=0 else (3 if e30>=-10 else 0)))
    e5=x['d5']-SPY5
    p += 8 if e5>=5 else (5 if e5>=0 else (2 if e5>=-5 else 0))
    return p

def val_score(x,a):
    pe=x.get('fwd_pe'); g=x.get('impl_g')
    if pe and pe>0 and g and g>0:
        peg=pe/g
        base = 10 if peg<0.5 else (8 if peg<1.0 else (5 if peg<1.5 else (2 if peg<2.5 else 0)))
    elif pe and pe>0:
        base = 6 if pe<15 else (4 if pe<25 else (2 if pe<40 else 0))
    else: base=2
    f=(a or {}).get('valuation_flag','')
    if f=='distorted': base*=0.5
    elif f=='unusable': base*=0.3
    return round(base,1)

def judge_score(a):
    if not a: return None
    return round(a.get('supply_constraint',0)*2.5 + a.get('cash_conversion',0)*1.3
                 + a.get('catalyst',0)*0.7 + (10-a.get('bear_severity',10))*0.5, 1)

def build():
    A=json.load(open(os.path.join(D,'agent_scores.json')))
    M={x['t']:x for x in json.load(open(os.path.join(D,'mech_input.json')))}
    rows=[]; miss=[]
    for t,x in M.items():
        a=A.get(t); j=judge_score(a)
        if j is None: miss.append(t); continue
        s_st,s_rs,s_v = struct_score(x), rs_score(x), val_score(x,a)
        pe,g = x.get('fwd_pe'), x.get('impl_g')
        rows.append(dict(t=t,total=round(j+s_st+s_rs+s_v,1),judge=j,struct=s_st,rs=s_rs,val=s_v,
            supply=a.get('supply_constraint'),cash=a.get('cash_conversion'),
            cat=a.get('catalyst'),bear=a.get('bear_severity'),
            vflag=a.get('valuation_flag'),conf=a.get('confidence'),
            held=x['held'],weight=x.get('weight'),unreal=x.get('unreal'),
            name=x.get('name'),industry=x.get('industry'),mc=x.get('mc'),
            px=x['px'],d30=x['d30'],d5=x['d5'],ytd=x.get('ytd'),
            dh3=x['dh3'],dh52=x['dh52'],brk=x['brk'],h25=x.get('h25'),
            fwd_pe=pe,peg=(round(pe/g,2) if (pe and g and g>0) else None),
            supply_reason=a.get('supply_reason',''),bear_reason=a.get('bear_reason',''),
            cash_reason=a.get('cash_reason',''),catalyst_detail=a.get('catalyst_detail','')))
    rows.sort(key=lambda r:-r['total'])
    json.dump(rows,open(os.path.join(D,'composite.json'),'w'),ensure_ascii=False,indent=1)
    return rows,miss

if __name__=='__main__':
    rows,miss=build()
    print(f"综合分完成 {len(rows)} 只 | 缺 {len(miss)}: {','.join(miss[:20])}")

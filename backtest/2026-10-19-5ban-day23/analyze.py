import pandas as pd, numpy as np
E=pd.read_pickle('events.pkl')
for c in E.columns:
    if any(c.endswith(k) for k in ('_open_zt','_open_dt','_yizi_zt','_yizi_dt','_touch_zt','_touch_dt','_close_zt','_close_dt')): E[c]=E[c].fillna(False).astype(bool)
def f(v):
    v=v.dropna()
    return '' if len(v)==0 else f"{v.mean()*100:+.1f}%/{v.median()*100:+.1f}%/{(v>0).mean()*100:.0f}%({len(v)})"
def table(d,lab,groups,extra=()):
    print(f"\n### {lab}")
    cols=['n','次日封板','开盘买→当日收','开盘买→第3日收','收盘买→次日开','收盘买→次日收','收盘买→第3日收']+[e[0] for e in extra]
    rows=[]
    for name,m in groups:
        x=E[m.fillna(False)] if hasattr(m,'fillna') else E[m]
        r={'情形':name,'n':len(x),'次日封板':f"{x[f'{d}_next_zt'].astype(float).mean()*100:.0f}%" if len(x) and x[f'{d}_next_zt'].notna().any() else ''}
        r['开盘买→当日收']=f(x[f'{d}_开盘买_当日收']); r['开盘买→第3日收']=f(x[f'{d}_开盘买_第3日收'])
        r['收盘买→次日开']=f(x[f'{d}_收盘买_次日开']); r['收盘买→次日收']=f(x[f'{d}_收盘买_次日收']); r['收盘买→第3日收']=f(x[f'{d}_收盘买_第3日收'])
        for en,col in extra: r[en]=f(x[f'{d}_{col}'])
        rows.append(r)
    print(pd.DataFrame(rows).to_string(index=False))
for d,lab in (('d2','第二天(五板次日)'),('d3','第三天')):
    has=E[f'{d}_date'].notna()
    g,c,hz,lz=E[f'{d}_gap'],E[f'{d}_chg'],E[f'{d}_touch_zt'],E[f'{d}_touch_dt']
    oz,od,yz,yd,cz,cd=E[f'{d}_open_zt'],E[f'{d}_open_dt'],E[f'{d}_yizi_zt'],E[f'{d}_yizi_dt'],E[f'{d}_close_zt'],E[f'{d}_close_dt']
    T=lambda m: has&m.astype(bool)
    table(d,lab+' 开盘',[('全部',has),('一字涨停(买不到)',T(yz)),('涨停开后开板',T(oz&~yz)),('高开5%以上(非涨停)',T((g>=0.05)&~oz)),('高开0到5%',T((g>0)&(g<0.05))),('平开或低开到-4.5%',T((g<=0)&(g>-0.045))),('低开-4.5%以下(非跌停)',T((g<=-0.045)&~od)),('跌停开',T(od))])
    table(d,lab+' 盘中',[('碰涨停且封住',T(hz&cz)),('碰涨停后炸板',T(hz&~cz)),('碰跌停且收跌停',T(lz&cd)),('碰跌停后撬开',T(lz&~cd)),('涨跌停都没碰',T(~hz&~lz))],
          extra=(('涨停价买→次日收','涨停价买_次日收'),('跌停价买→当日收','跌停价买_当日收'),('跌停价买→次日收','跌停价买_次日收')))
    table(d,lab+' 收盘',[('收涨停',T(cz)),('收涨5%以上(非涨停)',T((c>=0.05)&~cz)),('收涨0到5%',T((c>0)&(c<0.05))),('收跌0到-5%',T((c<=0)&(c>-0.05))),('收跌-5%以下(非跌停)',T((c<=-0.05)&~cd)),('收跌停',T(cd))])
if True:
    has=E.d3_date.notna(); p=E.d2_close_zt.astype(bool)
    table('d3','第三天 按第二天路径',[('第二天封六板',has&p),('第二天没封板',has&~p),('第二天收跌停',has&E.d2_close_dt.astype(bool))])

#!/opt/homebrew/bin/python3.13
"""稳健性: 改用申万三级行业(更细, 更接近题材口径)重算板块日度面板"""
import pandas as pd
P=pd.read_parquet('stock_panel.parquet')
C=pd.read_excel('sw_code.xls',dtype=str).set_index('行业代码')
P['l2']=P['行业代码']; P['l2n']=P.l2.map(C['三级行业名称'])
G=P.groupby(['date','l2']).agg(l2n=('l2n','first'),l1n=('l1n','first'),n=('code','size'),zt=('zt','sum'),strong=('strong','sum'),lb2=('lb2','sum'),ew=('r','mean')).reset_index()
G.to_parquet('sector_daily_l3.parquet'); print('三级行业数',G.l2.nunique())

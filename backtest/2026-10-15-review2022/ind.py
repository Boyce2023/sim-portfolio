import baostock as bs,pandas as pd,signal
signal.signal(signal.SIGALRM,lambda s,f:(_ for _ in ()).throw(TimeoutError()))
signal.alarm(60); lg=bs.login()
rs=bs.query_stock_industry(); rows=[]
while rs.next(): rows.append(rs.get_row_data())
bs.logout(); signal.alarm(0)
df=pd.DataFrame(rows,columns=rs.fields); df.to_csv('industry.csv',index=False); print(len(df), df.head(3).to_string())

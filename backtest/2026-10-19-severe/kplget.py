import sys,urllib.request,zlib,gzip,json
def get(host,params):
    q='&'.join(f'{k}={v}' for k,v in {'PhoneOSNew':2,'UserID':0,'VerSion':'6.2.30.2','apiv':'w47',**params}.items())
    raw=urllib.request.urlopen(urllib.request.Request(f'https://{host}.kaipanla.com/w1/api/index.php?{q}',headers={'User-Agent':'kpl/6.2.30.2'}),timeout=15).read()
    for f in (lambda b:gzip.decompress(b), lambda b:zlib.decompress(b), lambda b:zlib.decompress(b,-15), lambda b:b):
        try: return f(raw).decode('utf-8')
        except Exception: pass
    return repr(raw[:80])
if __name__=='__main__':
    host=sys.argv[1]; params=dict(a.split('=',1) for a in sys.argv[2:])
    print(get(host,params)[:800])

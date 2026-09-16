"""Read-only official TWSE TAIEX JSON transport probe."""
from __future__ import annotations
import hashlib, json, platform, socket, ssl, sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path

MONTHS=('20260901','20260801','20260701')
PRIMARY='https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST'
FALLBACK='https://www.twse.com.tw/indicesReport/MI_5MINS_HIST'

def probe(base, month):
    endpoint=base+'?'+urlencode({'date':month,'response':'json'})
    out={'endpoint':endpoint,'dns_status':'FAIL','connection_status':'FAIL','http_status':None,'content_type':None,'response_bytes':0,'json_status':'FAIL','twse_stat':None,'row_count':0,'first_date':None,'last_date':None}
    try:
        socket.getaddrinfo('www.twse.com.tw',443,type=socket.SOCK_STREAM); out['dns_status']='PASS'
    except socket.gaierror as exc:
        out['transport_error']='DNS_FAILURE:'+type(exc).__name__; return out
    req=Request(endpoint,headers={'User-Agent':'RATE-Data-Engine-network-probe/1.0','Accept':'application/json','Accept-Language':'zh-TW,zh;q=0.9'})
    try:
        with urlopen(req,timeout=30,context=ssl.create_default_context()) as resp:
            body=resp.read(); out.update({'connection_status':'PASS','http_status':resp.status,'content_type':resp.headers.get('Content-Type',''),'response_bytes':len(body),'body_sha256':hashlib.sha256(body).hexdigest()})
    except HTTPError as exc:
        out.update({'connection_status':'PASS','http_status':exc.code,'transport_error':f'HTTP_{exc.code}'}); return out
    except (URLError,TimeoutError,OSError) as exc:
        out['transport_error']='CONNECT_FAILURE:'+type(exc).__name__; return out
    if not body: out['transport_error']='EMPTY_DATA'; return out
    try: payload=json.loads(body.decode('utf-8')); out['json_status']='PASS'
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:
        out['transport_error']='INVALID_JSON:'+type(exc).__name__; return out
    out['twse_stat']=payload.get('stat'); rows=payload.get('data') or []; out['row_count']=len(rows)
    if rows:
        out['first_date']=rows[0][0] if isinstance(rows[0],list) else rows[0].get('日期')
        out['last_date']=rows[-1][0] if isinstance(rows[-1],list) else rows[-1].get('日期')
    return out

def main():
    primary=probe(PRIMARY,MONTHS[0]); fallback=probe(FALLBACK,MONTHS[0]); chosen=primary if primary['json_status']=='PASS' and primary['twse_stat']=='OK' and primary['row_count']>0 else fallback
    months=[]
    if chosen['json_status']=='PASS' and chosen['twse_stat']=='OK' and chosen['row_count']>0:
        base=PRIMARY if chosen is primary else FALLBACK
        months=[probe(base,m) for m in MONTHS]
    result={'execution_environment':'github_actions','runner_os':platform.platform(),'python_version':platform.python_version(),'test_timestamp':datetime.now(timezone.utc).isoformat(),'primary_endpoint':PRIMARY,'primary':primary,'fallback_endpoint':FALLBACK,'fallback':fallback,'multi_month':months,'multi_month_status':'PASS' if len(months)==3 and all(x['http_status']==200 and x['json_status']=='PASS' and x['twse_stat']=='OK' and x['row_count']>0 for x in months) else 'FAIL','network_status':'PASS' if chosen.get('http_status')==200 and chosen.get('json_status')=='PASS' and chosen.get('twse_stat')=='OK' and chosen.get('row_count',0)>0 else 'FAIL'}
    Path('artifacts').mkdir(exist_ok=True); Path('artifacts/TAIEX_NETWORK_PROBE_EVIDENCE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result['network_status']=='PASS' and result['multi_month_status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())

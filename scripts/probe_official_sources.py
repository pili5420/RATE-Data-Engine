"""Small, read-only probe of the official sources used by LIVE assembly."""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from src.sources.fundamental import FundamentalAdapter
from src.sources.tdcc import TDCCAdapter
from src.sources.twse import TWSEAdapter

def probe(source, endpoint, parser):
    result={'source':source,'official_endpoint':endpoint,'retrieval_timestamp':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')}
    try:
        req=Request(endpoint,headers={'User-Agent':'RATE-Data-Engine/1.0','Accept':'application/json'})
        with urlopen(req,timeout=30) as response:
            body=response.read(); result.update({'http_status':response.status,'content_type':response.headers.get('Content-Type',''),'response_received':bool(body),'response_bytes':len(body),'digest':hashlib.sha256(body).hexdigest()})
        payload=json.loads(body.decode('utf-8-sig')); result.update({'records':len(payload.get('data',[])) if isinstance(payload,dict) else len(payload) if isinstance(payload,list) else 0,'parse_status':parser(payload)})
    except HTTPError as exc: result.update({'http_status':exc.code,'parse_status':'FAIL:HTTP'})
    except (URLError,TimeoutError) as exc: result.update({'http_status':None,'parse_status':'FAIL:CONNECTIVITY:'+type(exc).__name__})
    except Exception as exc: result.update({'http_status':result.get('http_status'),'parse_status':'FAIL:'+type(exc).__name__})
    return result
def ok(payload): return 'PASS' if payload else 'FAIL:EMPTY'
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--trading-date',required=True); ap.add_argument('--output',required=True); a=ap.parse_args(); td=a.trading_date.replace('-',''); ym=td[:6]; twse=TWSEAdapter(); fund=FundamentalAdapter(); base='https://www.twse.com.tw/rwd/zh'
    endpoints=[('TDCC_LARGE_HOLDER','https://openapi.tdcc.com.tw/v1/opendata/1-5',lambda p:ok(p)),('TWSE_MONTHLY_REVENUE',fund.REVENUE_ENDPOINT,lambda p:ok(p)),('TWSE_QUARTERLY_EPS',fund.EPS_ENDPOINTS[0],lambda p:ok(p)),('TWSE_HISTORICAL_STOCK',f'{base}/afterTrading/STOCK_DAY?date={ym}01&stockNo=2330&response=json',lambda p:'PASS' if isinstance(p,dict) and p.get('data') else 'FAIL:EMPTY'),('TAIEX_HISTORICAL',f'{base}/TAIEX/MI_5MINS_HIST?date={ym}01&response=json',lambda p:'PASS' if isinstance(p,dict) and p.get('data') else 'FAIL:EMPTY'),('TWSE_T86',f'{base}/fund/T86?date={td}&selectType=ALLBUT0999&response=json',lambda p:'PASS' if isinstance(p,dict) and p.get('data') else 'FAIL:EMPTY')]
    results=[probe(*x) for x in endpoints]; status='PASS' if all(x.get('parse_status')=='PASS' for x in results) else 'FAIL'; out={'status':status,'trading_date':a.trading_date,'sources':results}; Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(json.dumps(out,ensure_ascii=False)); return 0 if status=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())

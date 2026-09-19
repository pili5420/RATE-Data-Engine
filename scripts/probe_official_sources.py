"""Probe the same official adapter contracts used by live source assembly."""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.sources.fundamental import FundamentalAdapter
from src.sources.tdcc_historical import TDCCHistoricalAdapter
from src.sources.tpex import TPExAdapter
from src.sources.twse import TWSEAdapter
from scripts.build_live_source_bundle import _rows

def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

def check(name, provider, method, call):
    item={'source':name,'provider':provider,'adapter_method':method,'retrieval_timestamp':now(),'status':'NOT_RUN'}
    try:
        result=call()
        payload=result.get('raw_payload') if isinstance(result,dict) else None
        rows=_rows(payload) if payload is not None else (result.get('normalized_rows',[]) if isinstance(result,dict) else [])
        diagnostics=result.get('diagnostics',{}) if isinstance(result,dict) else {}
        item.update({'status':'PASS' if rows else 'FAIL:EMPTY','record_count':len(rows),
            'source':result.get('source',name) if isinstance(result,dict) else name,
            'endpoint':result.get('endpoint'),'source_timestamp':result.get('source_timestamp'),
            'content_hash':result.get('content_hash') or diagnostics.get('body_sha256'),
            'http_status':diagnostics.get('http_status'),'transport_identity':'PRODUCTION_ADAPTER'})
        if not rows: item['blocking_reason']='EMPTY_OFFICIAL_RESPONSE'
    except Exception as exc:
        item.update({'status':'FAIL:'+type(exc).__name__,'blocking_reason':str(exc)[:500]})
    return item

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--trading-date',required=True)
    ap.add_argument('--output',required=True)
    ap.add_argument('--universe-file',required=True)
    a=ap.parse_args(); td=a.trading_date; ym=td[:7].replace('-','')
    obj=json.loads(Path(a.universe_file).read_text(encoding='utf-8-sig'))
    symbols=obj.get('symbols',[]); twse=next(str(x['symbol']) for x in symbols if x.get('market')=='TWSE')
    tpex_symbol=next(str(x['symbol']) for x in symbols if x.get('market')=='TPEX')
    twse_adapter=TWSEAdapter(); tpex_adapter=TPExAdapter(); fund=FundamentalAdapter(); tdcc=TDCCHistoricalAdapter()
    probes=[
      check('TWSE_HISTORICAL_STOCK','TWSE Official','TWSEAdapter.fetch_historical_symbol',lambda:twse_adapter.fetch_historical_symbol(twse,ym)),
      check('TPEX_HISTORICAL_STOCK','TPEx Official','TPExAdapter.fetch_historical_symbol',lambda:tpex_adapter.fetch_historical_symbol(tpex_symbol,ym)),
      check('TAIEX','TWSE Official','TWSEAdapter.fetch_historical_benchmark',lambda:twse_adapter.fetch_historical_benchmark(ym)),
      check('TPEX_INDEX','TPEx Official','TPExAdapter.fetch_historical_benchmark',lambda:tpex_adapter.fetch_historical_benchmark(ym)),
      check('TWSE_INSTITUTIONAL','TWSE T86','TWSEAdapter.fetch_t86',lambda:twse_adapter.fetch_t86(td)),
      check('TPEX_INSTITUTIONAL','TPEx Official','TPExAdapter.fetch_institutional_daily',lambda:tpex_adapter.fetch_institutional_daily(td)),
      check('TDCC_HISTORICAL','TDCC Official','TDCCHistoricalAdapter.fetch_period',lambda:tdcc.fetch_period(twse,sorted([p for p in tdcc.available_periods if p<=td])[-1])),
      check('TWSE_FUNDAMENTAL_REVENUE','TWSE/MOPS Official','FundamentalAdapter.fetch_monthly_revenue',lambda:fund.fetch_monthly_revenue()),
      check('TWSE_FUNDAMENTAL_EPS','TWSE/MOPS Official','FundamentalAdapter.fetch_quarterly_eps',lambda:fund.fetch_quarterly_eps(fund.EPS_ENDPOINTS[0])),
      check('TPEX_FUNDAMENTAL_REVENUE','TPEx/MOPS Official','FundamentalAdapter.fetch_otc_monthly_revenue',lambda:fund.fetch_otc_monthly_revenue()),
      check('TPEX_FUNDAMENTAL_EPS','TPEx/MOPS Official','FundamentalAdapter.fetch_otc_quarterly_eps',lambda:fund.fetch_otc_quarterly_eps(fund.OTC_EPS_ENDPOINTS[0])),
    ]
    result={'artifact':'RATE_CER073_SOURCE_PROBE_EVIDENCE','status':'PASS' if all(x['status']=='PASS' for x in probes) else 'FAIL',
      'trading_date':td,'fixture_used':False,'probe_runtime_identity':'SAME_ADAPTER_METHODS_AS_LIVE_BUILDER',
      'probes':probes,'retrieval_timestamp':now()}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())

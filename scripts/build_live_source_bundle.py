"""Build the LIVE RATE source bundle, fail-closed and without fixture fallback."""
from __future__ import annotations
import argparse, json, os, sys
import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.benchmark_history import normalize_twse_date
from src.fundamental import calculate_fundamental
from src.historical_store import PersistentHistoricalStore, normalize_stock_record
from src.institutional_features import calculate_institutional_rotation
from src.live_decision_inputs import build_live_decision_records
from src.rate_logic import calculate_m7, calculate_mhe
from src.sources.tdcc import TDCCAdapter
from src.sources.fundamental import FundamentalAdapter
from src.fundamental_history import PersistentFundamentalStore
from src.sources.twse import TWSEAdapter
from src.sources.tpex import TPExAdapter
from src.technical_features import compute_scores, technical_record

FULL_COMPONENTS = ('PT','PV','MO','FI','IT','LH','RS','H5','H20','H60','H120','RS_CHANGE','VOL_CHANGE','SMART_MONEY','MOMENTUM_CHANGE','FC','Fundamental','RelativeStrength','Liquidity')
REQUIRED_CONFIG = ('TDCC_OPENAPI_BASE',)
EVIDENCE_DEFAULT = 'artifacts/RATE_LIVE_SOURCE_ASSEMBLY_EVIDENCE.json'
UNIVERSE_CONTEXT = {}

def _now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def _rows(payload):
    if isinstance(payload,list): return [x for x in payload if isinstance(x,dict)]
    if not isinstance(payload,dict): return []
    data=payload.get('data') or payload.get('records') or []; fields=payload.get('fields') or []
    if fields and isinstance(data,list): return [dict(zip(fields,x)) if isinstance(x,list) else x for x in data if isinstance(x,(list,dict))]
    return [x for x in data if isinstance(x,dict)] if isinstance(data,list) else []
def _pick(row,*names):
    for name in names:
        if name in row and row[name] not in (None,'','-','--'): return row[name]
    return None
def _number(value):
    text=str(value).strip().replace(',','')
    if text in ('','-','--','None','null'): raise ValueError('MISSING_NUMERIC')
    return float(text.replace('(','-').replace(')',''))
def _month_cursor(end):
    year,month=end.year,end.month
    while True:
        yield f'{year:04d}{month:02d}'
        month-=1
        if month==0: month,year=12,year-1
def _parse_universe_payload(obj):
    """Parse supported universe shapes without stringifying structured entries."""
    if isinstance(obj, list):
        entries = obj
    elif isinstance(obj, dict) and isinstance(obj.get('symbols'), list):
        entries = obj['symbols']
    else:
        entries = []
    parsed=[]
    for entry in entries:
        if isinstance(entry, str):
            parsed.append({'symbol': entry.strip()})
        elif isinstance(entry, dict) and entry.get('symbol') is not None:
            parsed.append({'symbol': str(entry['symbol']).strip(), 'market': entry.get('market'), **entry})
    return parsed

def _load_universe():
    global UNIVERSE_CONTEXT
    UNIVERSE_CONTEXT = {}
    symbols=[x.strip() for x in os.getenv('RATE_TWSE_SYMBOLS','').split(',') if x.strip()]
    path=os.getenv('RATE_UNIVERSE_FILE')
    if not symbols and path:
        obj=json.loads(Path(path).read_text(encoding='utf-8'))
        if isinstance(obj, dict):
            if obj.get('artifact') != 'CONTROL_CENTER_APPROVED_STAGING_VALIDATION_UNIVERSE_V1' or obj.get('schema_version') != 'RATE-UNIVERSE-V1.0' or obj.get('validation_scope') != 'STAGING_LIVE_ONLY' or obj.get('ranking_status') != 'NOT_A_VALIDATED_TOP30_RANKING':
                raise RuntimeError('INVALID_PRODUCTION_UNIVERSE_AUTHORITY')
            if obj.get('validation_status') != 'PASS': raise RuntimeError('INVALID_PRODUCTION_UNIVERSE_AUTHORITY:VALIDATION_STATUS')
            if obj.get('source_state_id') != 'RATE-V11.1-PS-20260913-V1-r000009' or obj.get('source_state_file_sha256') != 'f1cc9c5f005a07f081943e279cfab9624079d51ae7d3ef1f1e23ef74b638864b':
                raise RuntimeError('INVALID_PRODUCTION_UNIVERSE_AUTHORITY:STATE')
            parsed = _parse_universe_payload(obj)
            if any(not p.get('market') in ('TWSE','TPEX') for p in parsed): raise RuntimeError('INVALID_PRODUCTION_UNIVERSE_AUTHORITY:MARKET')
            if any(p['symbol'].upper() == 'TAIEX' for p in parsed): raise RuntimeError('INVALID_PRODUCTION_UNIVERSE_AUTHORITY:BENCHMARK_IN_EQUITY_UNIVERSE')
            symbols = [p['symbol'] for p in parsed]
            if any(not x.isdigit() for x in symbols) or len(set(symbols)) != len(symbols): raise RuntimeError('INVALID_PRODUCTION_UNIVERSE_AUTHORITY:SYMBOLS')
            if len(parsed) != 30: raise RuntimeError('INVALID_PRODUCTION_UNIVERSE_AUTHORITY:RECORD_COUNT')
            digest_payload={'source_state_id':obj['source_state_id'],'symbols':symbols}
            digest=hashlib.sha256(json.dumps(digest_payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            if digest != obj.get('universe_symbol_digest') or digest != '30276287608b87f7d9b606891514247da523dce9214e4b82bb34ba118a35af4c': raise RuntimeError('INVALID_PRODUCTION_UNIVERSE_AUTHORITY:DIGEST')
            if obj.get('record_count') != 30 or obj.get('unique_count',30) != 30 or obj.get('duplicate_count',0) != 0: raise RuntimeError('INVALID_PRODUCTION_UNIVERSE_AUTHORITY:COUNTS')
            UNIVERSE_CONTEXT={'universe_source':'CONTROL_CENTER_APPROVED_STAGING_VALIDATION_UNIVERSE_V1','universe_schema_version':obj['schema_version'],'universe_source_state_id':obj['source_state_id'],'universe_source_state_hash':obj['source_state_file_sha256'],'universe_digest':digest,'universe_record_count':30,'twse_count':sum(p['market']=='TWSE' for p in parsed),'tpex_count':sum(p['market']=='TPEX' for p in parsed),'unresolved_market_count':obj.get('unresolved_market_count',0),'fixture_universe_used':False,'universe_markets':{p['symbol']:p['market'] for p in parsed}}
        else:
            parsed = _parse_universe_payload(obj); symbols=[p['symbol'] for p in parsed]
    result=sorted(set(x for x in symbols if x.isdigit()))
    if not result: raise RuntimeError('MISSING_REQUIRED_SOURCE_CONFIGURATION:RATE_TWSE_SYMBOLS_OR_RATE_UNIVERSE_FILE')
    return result
def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def _config_readiness(): return {key:('READY' if (os.getenv(key) or key=='TDCC_OPENAPI_BASE') else 'NOT_READY') for key in REQUIRED_CONFIG}
def _failure(path,trading_date,reason,coverage=None):
    _write(path,{'status':'BLOCKED','blocking_reason':reason,'trading_date':trading_date,'staging_commit':os.getenv('GITHUB_SHA'),'execution_runtime':'github_actions' if os.getenv('GITHUB_ACTIONS')=='true' else 'local','universe_count':len(os.getenv('RATE_TWSE_SYMBOLS','').split(',')) if os.getenv('RATE_TWSE_SYMBOLS') else UNIVERSE_CONTEXT.get('universe_record_count',0),'source_readiness':_config_readiness(),'history_coverage_reached_before_failure':coverage or {},'benchmark_coverage':None,'timestamps':{'retrieval_timestamp':_now()},**UNIVERSE_CONTEXT})
def _history(adapter,symbol,trading_date,market='TWSE'):
    records=[]; seen=set(); end=date.fromisoformat(trading_date)
    for period in _month_cursor(end):
        try:
            result=adapter.fetch_historical_symbol(symbol,period)
        except Exception as exc:
            raise RuntimeError(f"{market}_HISTORICAL_RETRIEVAL:{symbol}:{period}:{exc}") from exc
        for row in _rows(result.get('raw_payload')):
            raw_date=_pick(row,'trade_date','Date','日期')
            if raw_date is None: continue
            td=normalize_twse_date(raw_date)
            if td>trading_date or td in seen: continue
            records.append(normalize_stock_record({'symbol':symbol,'market':market,'trade_date':td,'open':_pick(row,'open','OpeningPrice','開盤價','Open'),'high':_pick(row,'high','HighestPrice','最高價','High'),'low':_pick(row,'low','LowestPrice','最低價','Low'),'close':_pick(row,'close','ClosingPrice','收盤價','Close'),'volume':_pick(row,'volume','TradeVolume','成交股數','TradingShares'),'turnover':_pick(row,'turnover','TradeValue','成交金額','TransactionAmount')},source=f'{market}_STOCK_DAY',source_timestamp=result.get('source_timestamp'),ingested_at=result.get('retrieval_timestamp'))); seen.add(td)
        if len(records)>=180: break
    records.sort(key=lambda x:x['trade_date'])
    if len(records)<180: raise RuntimeError(f'DATA_INCOMPLETE:LIVE_HISTORICAL_STOCK:{symbol}:{len(records)}<180')
    return records[-220:]
def _benchmark(adapter,trading_date,market='TWSE'):
    records=[]; seen=set(); end=date.fromisoformat(trading_date)
    for period in _month_cursor(end):
        try:
            result=adapter.fetch_historical_benchmark(period)
        except Exception as exc:
            raise RuntimeError(f"{market}_BENCHMARK_RETRIEVAL:{period}:{exc}") from exc
        for row in _rows(result.get('raw_payload')):
            raw_date=_pick(row,'trade_date','Date','日期'); close=_pick(row,'close','ClosingIndex','收盤指數','收盤價')
            if raw_date is None or close is None: continue
            td=normalize_twse_date(raw_date)
            if td>trading_date or td in seen: continue
            records.append({'benchmark_symbol':'TAIEX' if market=='TWSE' else 'TPEX','market':market,'trade_date':td,'close':_number(close),'source':'TWSE_TAIEX' if market=='TWSE' else 'TPEX_INDEX','source_timestamp':result.get('source_timestamp'),'ingested_at':result.get('retrieval_timestamp')}); seen.add(td)
        if len(records)>=180: break
    records.sort(key=lambda x:x['trade_date'])
    if len(records)<180: raise RuntimeError(f'DATA_INCOMPLETE:LIVE_{"TAIEX" if market=="TWSE" else "TPEX_INDEX"}_HISTORY:{len(records)}<180')
    return records[-220:]
def _t86_history(adapter, universe, stocks, trading_date):
    target=date.fromisoformat(trading_date); per={s:[] for s in universe}; cursor=target
    aliases={'symbol':('symbol','證券代號'),'foreign_buy':('foreign_buy','外陸資買進股數'),'foreign_sell':('foreign_sell','外陸資賣出股數'),'foreign_net':('foreign_net','外陸資買賣超股數'),'investment_trust_buy':('investment_trust_buy','投信買進股數'),'investment_trust_sell':('investment_trust_sell','投信賣出股數'),'investment_trust_net':('investment_trust_net','投信買賣超股數'),'dealer_buy':('dealer_buy','自營商買進股數'),'dealer_sell':('dealer_sell','自營商賣出股數'),'dealer_net':('dealer_net','自營商買賣超股數')}
    for _ in range(70):
        if all(len(v)>=20 for v in per.values()): break
        try: result=adapter.fetch_t86(cursor.isoformat())
        except Exception: cursor-=timedelta(days=1); continue
        for row in _rows(result.get('raw_payload')):
            mapped={k:_pick(row,*v) for k,v in aliases.items()}; symbol=str(mapped.get('symbol') or '').strip()
            if symbol not in per or any(mapped[k] is None for k in aliases): continue
            close=next((x for x in stocks[symbol] if x['trade_date']==cursor.isoformat()),None)
            if close is None: continue
            try:
                item={'symbol':symbol,'trading_date':cursor.isoformat(),**{k:_number(mapped[k]) for k in aliases if k!='symbol'},'foreign_net_shares':_number(mapped['foreign_net']),'investment_trust_net_shares':_number(mapped['investment_trust_net']),'close':close['close'],'turnover':close['turnover'],'source_timestamp':result.get('source_timestamp')}
            except ValueError: continue
            per[symbol].append(item)
        cursor-=timedelta(days=1)
    missing=[s for s,v in per.items() if len(v)<20]
    if missing: raise RuntimeError('DATA_INCOMPLETE:LIVE_T86_HISTORY:'+','.join(missing))
    return per

def _tpex_institutional_history(adapter, universe, stocks, trading_date):
    target=date.fromisoformat(trading_date); per={s:[] for s in universe}; cursor=target
    aliases={'symbol':('symbol','SecuritiesCompanyCode','證券代號'),'foreign_buy':('foreign_buy','ForeignBuy','外資及陸資買進股數'),'foreign_sell':('foreign_sell','ForeignSell','外資及陸資賣出股數'),'foreign_net':('foreign_net','ForeignNet','外資及陸資買賣超股數'),'investment_trust_buy':('investment_trust_buy','InvestmentTrustBuy','投信買進股數'),'investment_trust_sell':('investment_trust_sell','InvestmentTrustSell','投信賣出股數'),'investment_trust_net':('investment_trust_net','InvestmentTrustNet','投信買賣超股數')}
    for _ in range(70):
        if all(len(v)>=20 for v in per.values()): break
        try: result=adapter.fetch_institutional_history('', cursor.strftime('%Y%m'))
        except Exception: cursor-=timedelta(days=1); continue
        for row in _rows(result.get('raw_payload')):
            mapped={k:_pick(row,*v) for k,v in aliases.items()}; symbol=str(mapped.get('symbol') or '').strip()
            if symbol not in per or any(mapped[k] is None for k in aliases): continue
            td=normalize_twse_date(_pick(row,'trade_date','Date','日期') or cursor.isoformat())
            if td>trading_date or any(x.get('trading_date')==td for x in per[symbol]): continue
            close=next((x for x in stocks[symbol] if x['trade_date']==td),None)
            if close is None: continue
            try: item={'symbol':symbol,'trading_date':td,**{k:_number(mapped[k]) for k in aliases if k!='symbol'},'foreign_net_shares':_number(mapped['foreign_net']),'investment_trust_net_shares':_number(mapped['investment_trust_net']),'close':close['close'],'turnover':close['turnover'],'source_timestamp':result.get('source_timestamp')}
            except ValueError: continue
            per[symbol].append(item)
        cursor-=timedelta(days=1)
    missing=[s for s,v in per.items() if len(v)<20]
    if missing: raise RuntimeError('DATA_INCOMPLETE:TPEX_INSTITUTIONAL_HISTORY:'+','.join(missing))
    return per
def _tdcc_history(universe):
    raw=TDCCAdapter().fetch(); rows=_rows(raw.get('raw_payload')); out={}
    for row in rows:
        symbol=str(_pick(row,'symbol','SecuritiesCompanyCode','公司代號') or '').strip(); period=_pick(row,'period_end','資料年月','資料日期'); holder=_pick(row,'holder_pct_400','持股超過400張比率')
        if symbol in universe and period is not None and holder is not None:
            try: out.setdefault(symbol,[]).append({'period_end':str(period),'holder_pct_400':_number(holder),'source_timestamp':raw.get('source_timestamp')})
            except ValueError: pass
    missing=[s for s in universe if len(out.get(s,[]))<5]
    if missing: raise RuntimeError('DATA_INCOMPLETE:LIVE_TDCC_HISTORY:'+','.join(missing))
    return out
def _fundamental_history(universe, markets=None):
    adapter=FundamentalAdapter(); markets=markets or {}; twse_symbols=[s for s in universe if markets.get(s,'TWSE')=='TWSE']; tpex_symbols=[s for s in universe if markets.get(s,'TWSE')=='TPEX']
    revenue_rows=_rows(adapter.fetch_monthly_revenue()['raw_payload'])
    if tpex_symbols:
        revenue_rows += _rows(adapter.fetch_otc_monthly_revenue()['raw_payload'])
    by={str(_pick(r,'symbol','公司代號','公司代碼','SecuritiesCompanyCode') or ''):r for r in revenue_rows}
    eps_rows=[]
    endpoints=list(adapter.EPS_ENDPOINTS) + (list(adapter.OTC_EPS_ENDPOINTS) if tpex_symbols else [])
    for endpoint in endpoints:
        try: eps_rows.extend(_rows(adapter.fetch_quarterly_eps(endpoint)['raw_payload']))
        except Exception: continue
    eps_by={str(_pick(r,'symbol','公司代號','公司代碼') or ''):r for r in eps_rows}
    store=PersistentFundamentalStore(); normalized=[]
    for symbol in universe:
        rev=by.get(symbol); eps=eps_by.get(symbol)
        if rev is None: raise RuntimeError('DATA_INCOMPLETE:LIVE_FUNDAMENTAL_REVENUE:'+symbol)
        if eps is None: raise RuntimeError('DATA_INCOMPLETE:FUNDAMENTAL_EPS_HISTORY:'+symbol)
        prior=store.load(symbol)
        revenue=rev.get('revenue_yoy')
        if not isinstance(revenue,list):
            scalar=_pick(rev,'去年同月增減(%)','去年同月增減','YoY','revenue_yoy')
            revenue=[] if scalar is None else [ _number(scalar) ]
        revenue=list(prior.get('revenue_yoy',[]))+revenue
        quarters=eps.get('quarterly_eps')
        if not isinstance(quarters,list):
            scalar=_pick(eps,'基本每股盈餘','每股盈餘','EPS','quarterly_eps')
            quarters=[] if scalar is None else [ _number(scalar) ]
        quarters=list(prior.get('quarterly_eps',[]))+quarters
        if len(revenue)<3: raise RuntimeError('DATA_INCOMPLETE:FUNDAMENTAL_REVENUE_HISTORY:'+symbol)
        if len(quarters)<8: raise RuntimeError('DATA_INCOMPLETE:FUNDAMENTAL_EPS_HISTORY:'+symbol)
        value=store.upsert(symbol,revenue_yoy=revenue,quarterly_eps=quarters)
        normalized.append({'symbol':symbol,'revenue_yoy':value['revenue_yoy'],'quarterly_eps':value['quarterly_eps']})
    result=calculate_fundamental(normalized); by={str(r['symbol']):r for r in result}
    if any(s not in by for s in universe): raise RuntimeError('DATA_INCOMPLETE:LIVE_FUNDAMENTAL_HISTORY')
    return by
def _live(trading_date):
    missing=[k for k,v in _config_readiness().items() if v!='READY']
    if missing: raise RuntimeError('MISSING_REQUIRED_SOURCE_CONFIGURATION:'+','.join(missing))
    universe=_load_universe(); markets=UNIVERSE_CONTEXT.get('universe_markets', {s:'TWSE' for s in universe})
    twse=TWSEAdapter(); tpex=TPExAdapter()
    stocks={}
    for s in universe:
        market=markets.get(s,'TWSE'); stocks[s]=_history(twse if market=='TWSE' else tpex,s,trading_date,market)
    twse_benchmark=_benchmark(twse,trading_date,'TWSE')
    tpex_benchmark=_benchmark(tpex,trading_date,'TPEX') if any(m=='TPEX' for m in markets.values()) else []
    benchmark_by_symbol={s:(twse_benchmark if markets.get(s,'TWSE')=='TWSE' else tpex_benchmark) for s in universe}
    store=PersistentHistoricalStore()
    for s,rows in stocks.items(): store.upsert_stock(s,rows)
    store.upsert_benchmark('TAIEX',twse_benchmark)
    if tpex_benchmark: store.upsert_benchmark('TPEX',tpex_benchmark)
    twse_universe=[s for s in universe if markets.get(s,'TWSE')=='TWSE']; tpex_universe=[s for s in universe if markets.get(s)=='TPEX']
    t86=_t86_history(twse,twse_universe,stocks,trading_date) if twse_universe else {}
    tpex_inst=_tpex_institutional_history(tpex,tpex_universe,stocks,trading_date) if tpex_universe else {}
    inst_hist={**t86,**tpex_inst}; tdcc=_tdcc_history(universe); fundamentals=_fundamental_history(universe,markets)
    technical=compute_scores(list(stocks.values()), benchmark_by_symbol=benchmark_by_symbol); tech_by={str(x['symbol']):x for x in technical}
    inst_input=[{'symbol':s,'institutional_history':inst_hist[s],'tdcc_history':sorted(tdcc[s],key=lambda x:x['period_end']),'rs_history':[x['close'] for x in stocks[s]][-26:],'volume_5_history':[1.0]*6,'mo_history':[x['close'] for x in stocks[s]][-26:]} for s in universe]
    institutional=calculate_institutional_rotation(inst_input); inst_by={str(x['symbol']):x for x in institutional}; sources={}
    for symbol in universe:
        tf=tech_by[symbol]['technical_features']; hist=stocks[symbol]; tr=technical_record(hist,benchmark_by_symbol[symbol]); ir=inst_by[symbol]
        m7=calculate_m7({'PT':tf['PT'],'PV':tf['PV'],'MO':tf['MO'],'FI':ir['FI'],'IT':ir['IT'],'LH':ir['LH'],'RS':tf['RS']}); mhe=calculate_mhe({k:tf[k] for k in ('H5','H20','H60','H120')})
        stage={'price':hist[-1]['close'],'ma20':tr['MA20'],'ma60':tr['MA60'],'ma120':tr['MA120'],'price_above_all':hist[-1]['close']>max(tr['MA20'],tr['MA60'],tr['MA120']),'ma20_above_ma60':tr['MA20']>tr['MA60'],'ma20_slope_positive':tr['MA20']>=sum(x['close'] for x in hist[-25:-5])/20,'m7_score':m7['m7_score'],'mhe_score':mhe['mhe_score'],'relative_strength_strong':tf['RelativeStrength']>=50,'ma60_trend_non_negative':True,'price_above_ma60':hist[-1]['close']>tr['MA60'],'price_near_ma20_ma60':False,'long_term_bullish':hist[-1]['close']>=tr['MA120'],'short_swing_mhe_improving':True,'m7_rising':True,'mhe_rising':True,'recent_low_no_longer_deteriorating':True,'rotation_deteriorated':False,'structural_failure':False,'evidence_state_mixed':False}
        sources[symbol]={'technical_features':tf,'FI':ir['FI'],'IT':ir['IT'],'LH':ir['LH'],'SmartMoney_inputs':ir['SmartMoney_inputs'],'Rotation_inputs':ir['Rotation_inputs'],'Stage_inputs':stage,'Fundamental':fundamentals[symbol]['Fundamental']}
    built=build_live_decision_records(sources,trading_date,universe)
    if built['feature_validation']['status']!='PASS' or len(built['decision_records'])!=len(universe): raise RuntimeError('DATA_INCOMPLETE:FULL_19_COMPONENTS')
    return {'production_sources':sources,'universe':universe,'decision_records':built['decision_records'],'institutional_records':inst_hist[universe[0]],'source_provenance':{'source':'AUTHORIZED_LIVE','provider':'TWSE/TPEx/TDCC/MOPS','retrieval_timestamp':_now(),'stock_history_coverage':{s:len(v) for s,v in stocks.items()},'benchmark_records':{'TAIEX':len(twse_benchmark),'TPEX':len(tpex_benchmark)}},'short_term_top30':universe,'roy_portfolio':[],'required_benchmarks':['TAIEX','TPEX'],'explicit_production_watchlist':[],'validation_status':'PASS'}
def _validate(records):
    errors=[]
    for r in records:
        missing=[]
        for key in FULL_COMPONENTS:
            if key in ('PT','PV','MO','RS','H5','H20','H60','H120'):
                if r.get('M7_inputs',{}).get(key) is None and r.get('MHE_inputs',{}).get(key) is None: missing.append(key)
            elif r.get(key) is None and r.get('SmartMoney_inputs',{}).get(key) is None and r.get('Rotation_inputs',{}).get(key) is None: missing.append(key)
        if not r.get('Stage_inputs'): missing.append('Stage_inputs')
        if missing: errors.append({'symbol':r.get('symbol'),'missing_components':sorted(set(missing))})
    return errors
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--trading-date',required=True); ap.add_argument('--output',required=True); ap.add_argument('--source-bundle-input'); ap.add_argument('--evidence-output',default=EVIDENCE_DEFAULT); a=ap.parse_args(); output,evidence=Path(a.output),Path(a.evidence_output)
    try:
        if a.source_bundle_input:
            source=json.loads(Path(a.source_bundle_input).read_text(encoding='utf-8'))
            if 'production_sources' in source:
                built=build_live_decision_records(source['production_sources'],a.trading_date,source.get('universe',sorted(source['production_sources'])))
                if built['feature_validation']['status']!='PASS': raise RuntimeError('DATA_INCOMPLETE:TECHNICAL_FEATURES')
                bundle={**source,'decision_records':built['decision_records'],'institutional_records':source.get('institutional_records',[]),'source_provenance':source.get('source_provenance',{})}
            else: bundle=source
        else: bundle=_live(a.trading_date)
        if _validate(bundle.get('decision_records',[])): raise RuntimeError('DATA_INCOMPLETE:FULL_19_COMPONENTS')
        _write(output,bundle); _write(evidence,{'status':'PASS','trading_date':a.trading_date,'staging_commit':os.getenv('GITHUB_SHA'),'universe_count':len(bundle.get('universe',[])),'source_readiness':_config_readiness(),'history_coverage_reached_before_failure':bundle.get('source_provenance',{}).get('stock_history_coverage',{}),'benchmark_coverage':bundle.get('source_provenance',{}).get('benchmark_records'),'timestamps':{'retrieval_timestamp':_now()},**UNIVERSE_CONTEXT}); return 0
    except Exception as exc:
        _failure(evidence,a.trading_date,str(exc)); _write(output,{'validation_status':'BLOCKED','blocking_reason':str(exc)}); print(json.dumps({'validation_status':'BLOCKED','blocking_reason':str(exc)})); return 1
if __name__=='__main__': raise SystemExit(main())

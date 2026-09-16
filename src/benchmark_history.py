"""Official completed-session benchmark adapters and bootstrap helpers."""
from __future__ import annotations
import hashlib, json
from datetime import date
from .historical_store import PersistentHistoricalStore, _number

def normalize_benchmark(record, *, benchmark_symbol, market, source, source_timestamp, ingested_at):
    out={'benchmark_symbol':benchmark_symbol,'market':market,'trade_date':str(record.get('trade_date') or record.get('Date')),
         'open':_number(record.get('open',record.get('OpeningIndex',record.get('Open'))),'open') if record.get('open',record.get('OpeningIndex',record.get('Open'))) not in (None,'') else None,
         'high':_number(record.get('high',record.get('HighestIndex',record.get('High'))),'high') if record.get('high',record.get('HighestIndex',record.get('High'))) not in (None,'') else None,
         'low':_number(record.get('low',record.get('LowestIndex',record.get('Low'))),'low') if record.get('low',record.get('LowestIndex',record.get('Low'))) not in (None,'') else None,
         'close':_number(record.get('close',record.get('ClosingIndex',record.get('Close'))),'close'),'source':source,'source_timestamp':source_timestamp,'ingested_at':ingested_at}
    if out['close'] <= 0: raise ValueError('RANGE:benchmark_close')
    return out

def validate_benchmark(records, benchmark_symbol):
    seen=set(); today=date.today().isoformat()
    for r in records:
        key=(r.get('benchmark_symbol'),r.get('trade_date'))
        if key in seen: raise ValueError(f'DUPLICATE_BENCHMARK_DATE:{key[1]}')
        seen.add(key)
        if r.get('benchmark_symbol') != benchmark_symbol: raise ValueError('WRONG_BENCHMARK_ASSIGNMENT')
        if r.get('trade_date') > today: raise ValueError('FUTURE_DATED_BENCHMARK')
        if r.get('close') is None or float(r['close']) <= 0: raise ValueError('INVALID_BENCHMARK_CLOSE')
    return True

def bootstrap_benchmark_history(store: PersistentHistoricalStore, records, benchmark_symbol):
    validate_benchmark(records, benchmark_symbol)
    ordered=sorted(records,key=lambda x:x['trade_date'])
    if len(ordered)<180: raise ValueError('DATA_INCOMPLETE:BENCHMARK_HISTORY')
    return store.upsert_benchmark(benchmark_symbol, ordered)

def update_benchmark_history(store: PersistentHistoricalStore, record, benchmark_symbol):
    validate_benchmark([record], benchmark_symbol)
    return store.upsert_benchmark(benchmark_symbol,[record])

def benchmark_digest(records):
    return hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

"""Official completed-session benchmark adapters and bootstrap helpers."""
from __future__ import annotations
import hashlib, json
from datetime import date
from .historical_store import PersistentHistoricalStore, _number

def normalize_twse_date(value):
    text=str(value).strip().replace('/','-')
    parts=text.split('-')
    if len(parts)==3 and len(parts[0]) <= 3 and parts[0].isdigit():
        return f'{int(parts[0])+1911:04d}-{int(parts[1]):02d}-{int(parts[2]):02d}'
    return text

def normalize_benchmark(record, *, benchmark_symbol, market, source, source_timestamp, ingested_at):
    def pick(*names):
        for name in names:
            value = record.get(name)
            if value not in (None, ''):
                return value
        return None
    raw_date = pick('trade_date', 'Date', '日期', '日期')
    raw_open = pick('open', 'OpeningIndex', 'Open', '開盤指數', '開盤')
    raw_high = pick('high', 'HighestIndex', 'High', '最高指數', '最高')
    raw_low = pick('low', 'LowestIndex', 'Low', '最低指數', '最低')
    raw_close = pick('close', 'ClosingIndex', 'Close', '收盤指數', '收盤')
    out={'benchmark_symbol':benchmark_symbol,'market':market,'trade_date':normalize_twse_date(raw_date),
         'open':_number(raw_open,'open') if raw_open not in (None,'','-','--') else None,
         'high':_number(raw_high,'high') if raw_high not in (None,'','-','--') else None,
         'low':_number(raw_low,'low') if raw_low not in (None,'','-','--') else None,
         'close':_number(raw_close,'close'),'source':source,'source_timestamp':source_timestamp,'ingested_at':ingested_at}
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
    # Retrieval/ingestion timestamps are lineage metadata and may differ on a
    # refetch.  Exclude only those volatile fields so the benchmark identity is
    # stable for the same normalized market sessions.
    canonical = [{k: v for k, v in row.items() if k not in ('source_timestamp', 'ingested_at')} for row in records]
    return hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

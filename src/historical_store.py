"""Persistent completed-session market history for RATE production inputs."""
from __future__ import annotations
import hashlib, json
from datetime import date
from pathlib import Path

MAX_SESSIONS = 220

def _number(value, field):
    if value is None or value == '': raise ValueError(f'MISSING:{field}')
    try: return float(str(value).replace(',', ''))
    except (TypeError, ValueError) as exc: raise ValueError(f'INVALID_NUMERIC:{field}') from exc

def normalize_stock_record(record, *, source, source_timestamp, ingested_at):
    out={'symbol':str(record.get('symbol') or record.get('Code')),'market':record.get('market'),'trade_date':str(record.get('trade_date') or record.get('Date')),
         'open':_number(record.get('open',record.get('OpeningPrice')),'open'),'high':_number(record.get('high',record.get('HighestPrice')),'high'),'low':_number(record.get('low',record.get('LowestPrice')),'low'),'close':_number(record.get('close',record.get('ClosingPrice')),'close'),'volume':_number(record.get('volume',record.get('TradeVolume')),'volume'),'turnover':_number(record.get('turnover',record.get('TradeValue')),'turnover'),'source':source,'source_timestamp':source_timestamp,'ingested_at':ingested_at}
    if not out['symbol'] or out['symbol']=='None': raise ValueError('MISSING:symbol')
    return out

def normalize_benchmark_record(record, *, benchmark_symbol, market, source, source_timestamp, ingested_at):
    return {'benchmark_symbol':benchmark_symbol,'market':market,'trade_date':str(record.get('trade_date') or record.get('Date')),'close':_number(record.get('close',record.get('ClosingIndex')),'close'),'source':source,'source_timestamp':source_timestamp,'ingested_at':ingested_at}

def _unique(records, key):
    seen={}
    for r in records:
        k=key(r)
        if k in seen:
            if seen[k] != r: raise ValueError(f'DATA_CONFLICT:{k}')
            raise ValueError(f'DUPLICATE:{k}')
        seen[k]=r
    return sorted(seen.values(), key=lambda x:x['trade_date'])

def align_histories(stock_records, benchmark_records):
    stocks=_unique(stock_records,lambda r:(r['symbol'],r['trade_date'])); bench=_unique(benchmark_records,lambda r:(r['benchmark_symbol'],r['trade_date']))
    today=date.today().isoformat();
    if any(r['trade_date']>today for r in stocks+bench): raise ValueError('FUTURE_DATED_RECORD')
    bm={r['trade_date']:r for r in bench}; return [(r,bm[r['trade_date']]) for r in stocks if r['trade_date'] in bm]

class PersistentHistoricalStore:
    def __init__(self, root='data/production/history'):
        self.root=Path(root); (self.root/'market_daily').mkdir(parents=True,exist_ok=True); (self.root/'benchmark').mkdir(parents=True,exist_ok=True)
    def _path(self, kind, key): return self.root/kind/(str(key)+'.json')
    def _read(self, kind, key):
        p=self._path(kind,key); return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
    def _write(self, kind,key,records): self._path(kind,key).write_text(json.dumps(records,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n',encoding='utf-8')
    def upsert_stock(self, symbol, records): return self._upsert('market_daily',symbol,records,lambda r:(r['symbol'],r['trade_date']))
    def upsert_benchmark(self, benchmark_symbol, records): return self._upsert('benchmark',benchmark_symbol,records,lambda r:(r['benchmark_symbol'],r['trade_date']))
    def materialize_stock(self, symbol, records):
        """Replace one canonical stock file using the store's retention rule.

        Bootstrap checkpoints are provenance; materialization must produce the
        exact retained subset consumed by downstream runtime.  This method
        keeps that operation on the existing PersistentHistoricalStore rather
        than introducing a second retention policy.
        """
        unique = {}
        for record in records:
            key = (record.get('symbol'), record.get('trade_date'))
            if key in unique and unique[key] != record:
                raise ValueError(f'DATA_CONFLICT:{key}')
            if key in unique:
                raise ValueError(f'DUPLICATE:{key}')
            unique[key] = record
        ordered = sorted(unique.values(), key=lambda row: row['trade_date'])
        retained = ordered[-MAX_SESSIONS:]
        self._write('market_daily', symbol, retained)
        digest = hashlib.sha256(json.dumps(retained, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return {
            'status': 'REPLACED',
            'record_count': len(retained),
            'checkpoint_record_count': len(ordered),
            'trimmed_count': max(0, len(ordered) - len(retained)),
            'content_hash': digest,
        }
    def _upsert(self,kind,key,records,keyfn):
        old=self._read(kind,key); merged={keyfn(r):r for r in old}; status='NO_OP'
        for r in records:
            k=keyfn(r)
            if k in merged and merged[k]!=r: raise ValueError(f'DATA_CONFLICT:{k}')
            if k not in merged: merged[k]=r; status='APPENDED'
        out=sorted(merged.values(),key=lambda r:r['trade_date'])[-MAX_SESSIONS:]; self._write(kind,key,out); return {'status':status,'record_count':len(out),'content_hash':hashlib.sha256(json.dumps(out,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    def load_stock(self,symbol): return self._read('market_daily',symbol)
    def load_benchmark(self,benchmark): return self._read('benchmark',benchmark)

def bootstrap_historical_market_data(store, stock_records_by_symbol, benchmark_records_by_symbol):
    results={}
    for symbol, records in stock_records_by_symbol.items():
        bench=benchmark_records_by_symbol[symbol]; aligned=align_histories(records,bench)
        if len(aligned)<120: raise ValueError(f'DATA_INCOMPLETE:HISTORICAL_TECHNICAL_SOURCE:{symbol}')
        results[symbol]={'stock':store.upsert_stock(symbol,records),'benchmark':store.upsert_benchmark(bench[0]['benchmark_symbol'],bench),'aligned_count':len(aligned)}
    return results

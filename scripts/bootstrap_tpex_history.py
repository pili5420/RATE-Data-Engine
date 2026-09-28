"""Bounded, resumable TPEx individual-stock historical bootstrap."""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import date, datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_live_source_bundle import _atomic_write_json, _month_cursor
from src.historical_store import _number
from src.sources.tpex import TPExAdapter, normalize_tpex_date

TPEx_SYMBOLS=("6274","3081","6187","6510","3227")
TARGET_RAW_SESSIONS=190
CHECKPOINT_SCHEMA="RATE-TPEX-HISTORY-CHECKPOINT-V2"
SOURCE_DATASET="TPEx Daily Stock Info / Historical Data of Individual Mainboard Stock"
def _now(): return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _universe_digest(): return hashlib.sha256(json.dumps(TPEx_SYMBOLS,separators=(",",":")).encode()).hexdigest()
def _digest(obj): return hashlib.sha256(json.dumps({k:v for k,v in obj.items() if k not in ("content_hash","last_updated")},ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def _empty(): return {"schema_version":CHECKPOINT_SCHEMA,"universe_digest":_universe_digest(),"market":"TPEX","source_dataset_version":SOURCE_DATASET,"records":{},"content_hash":None,"last_updated":None}
def _load(path):
    if not path.exists(): return _empty()
    obj=json.loads(path.read_text(encoding="utf-8"))
    if obj.get("schema_version")!=CHECKPOINT_SCHEMA or obj.get("universe_digest")!=_universe_digest() or obj.get("market")!="TPEX" or obj.get("content_hash")!=_digest(obj): raise RuntimeError("TPEX_HISTORY_CHECKPOINT_INVALID")
    return obj
def _save(path,cp):
    cp.update(schema_version=CHECKPOINT_SCHEMA,universe_digest=_universe_digest(),market="TPEX",source_dataset_version=SOURCE_DATASET,last_updated=_now()); cp["content_hash"]=_digest(cp); _atomic_write_json(path,cp)
def _num(v,f):
    if v in (None,"","-","--"): raise ValueError(f"MISSING:{f}")
    return _number(v,f)
def _matches(v,p): return normalize_tpex_date(v)[:7]==f"{p[:4]}-{p[4:6]}"
def _rows(result):
    payload=result.get("raw_payload"); tables=payload.get("tables") if isinstance(payload,dict) else None
    if not tables or not isinstance(tables[0],dict): raise RuntimeError("TPEX_HISTORY_RESPONSE_SCHEMA_MISMATCH")
    table=tables[0]; fields=table.get("fields") or []; data=table.get("data") or []
    if not fields or not data: raise RuntimeError("TPEX_HISTORY_RESPONSE_EMPTY_ROWS")
    return table,[dict(zip(fields,row)) for row in data if isinstance(row,list) and len(row)==len(fields)]
def extract_symbol_month_rows(result,symbol,period):
    table,rows=_rows(result); payload=result["raw_payload"]; code=str(payload.get("code") or "").strip(); subtitle=str(table.get("subtitle") or "")
    if (code and code!=symbol) or (not code and symbol not in subtitle): raise RuntimeError(f"TPEX_HISTORY_RESPONSE_SYMBOL_MISMATCH:{symbol}")
    out=[]; seen=set()
    for row in rows:
        raw=row.get("Date") or row.get("日期")
        if raw is None: raise RuntimeError("TPEX_HISTORY_RESPONSE_SCHEMA_MISMATCH:DATE")
        td=normalize_tpex_date(raw)
        if not _matches(td,period): raise RuntimeError(f"TPEX_HISTORY_RESPONSE_PERIOD_MISMATCH:{period}:{td[:7]}")
        if td in seen: raise RuntimeError(f"TPEX_DUPLICATE_DATE:{symbol}:{td}")
        seen.add(td); out.append({"symbol":symbol,"market":"TPEX","trade_date":td,"open":_num(row.get("Open") or row.get("開盤"),"open"),"high":_num(row.get("High") or row.get("最高"),"high"),"low":_num(row.get("Low") or row.get("最低"),"low"),"close":_num(row.get("Close") or row.get("收盤"),"close"),"volume":_num(row.get("Trade unit") or row.get("成交股數") or row.get("成交量"),"volume"),"turnover":_num(row.get("Trade Amt.(NTD1000)") or row.get("成交金額"),"turnover"),"source":"TPEX_HISTORICAL_STOCK","source_timestamp":result.get("source_timestamp"),"ingested_at":result.get("retrieval_timestamp")})
    if not out: raise RuntimeError(f"TPEX_HISTORY_RESPONSE_EMPTY_ROWS:{symbol}:{period}")
    if any(r["trade_date"]>date.today().isoformat() for r in out): raise RuntimeError("TPEX_FUTURE_DATED_RECORD")
    return out
def extract_month_rows(result,symbols,period): return [r for s in symbols for r in extract_symbol_month_rows(result,s,period)]
def bootstrap(*,trading_date,checkpoint,output,max_months=36,adapter=None):
    cp=_load(checkpoint); adapter=adapter or TPExAdapter(); request_count=cache_hits=0; used=[]; status="FAIL"; reason=None
    try:
        end=date.fromisoformat(trading_date)
        for symbol in TPEx_SYMBOLS:
            for i,period in enumerate(_month_cursor(end)):
                if i>=max_months: break
                total=len({r["trade_date"]:r for k,e in cp["records"].items() if k.startswith(symbol+"|") for r in e.get("records",[])})
                if total>=TARGET_RAW_SESSIONS: break
                key=f"{symbol}|{period}"
                if key in cp["records"] and cp["records"][key].get("validation_status")=="PASS": cache_hits+=1; continue
                used.append(key); result=adapter.fetch_historical_symbol(symbol,period); request_count+=1; rows=extract_symbol_month_rows(result,symbol,period)
                cp["records"][key]={"symbol":symbol,"period":period,"records":rows,"record_count":len(rows),"endpoint":result.get("endpoint"),"source_timestamp":result.get("source_timestamp"),"retrieval_timestamp":result.get("retrieval_timestamp"),"content_hash":hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(),"validation_status":"PASS"}; _save(checkpoint,cp)
        counts={s:len({r["trade_date"]:r for k,e in cp["records"].items() if k.startswith(s+"|") for r in e.get("records",[])}) for s in TPEx_SYMBOLS}
        if not all(v>=TARGET_RAW_SESSIONS for v in counts.values()): raise RuntimeError("DATA_INCOMPLETE:TPEX_RAW_HISTORY:"+",".join(f"{s}={counts[s]}" for s in TPEx_SYMBOLS))
        status="PASS"
    except Exception as exc: reason=str(exc); counts={s:len({r["trade_date"]:r for k,e in cp["records"].items() if k.startswith(s+"|") for r in e.get("records",[])}) for s in TPEx_SYMBOLS}
    payload={"artifact":"RATE_TPEX_HISTORY_BOOTSTRAP_EVIDENCE","status":status,"market":"TPEX","symbols":list(TPEx_SYMBOLS),"universe_digest":_universe_digest(),"raw_sessions_by_symbol":counts,"raw_coverage":f"{sum(v>0 for v in counts.values())}/5","raw_sessions_ge_190":f"{sum(v>=TARGET_RAW_SESSIONS for v in counts.values())}/5","monthly_periods_fetched":sorted({k.split('|')[1] for k in cp["records"]}),"symbol_period_requests":sorted(cp["records"]),"monthly_periods_used_this_run":used,"monthly_request_count":request_count,"monthly_cache_hits":cache_hits,"request_granularity":"SYMBOL_MONTH","request_deduplication":"PASS","checkpoint_content_hash":cp.get("content_hash"),"validation_status":"PASS" if status=="PASS" else "FAIL","source_dataset":SOURCE_DATASET,"production_state_modified":"NO","generated_at":_now()}
    if reason: payload["blocking_reason"]=reason
    _atomic_write_json(output,payload); return payload
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--trading-date",required=True); ap.add_argument("--checkpoint",default="data/staging/history_bootstrap/RATE_TPEX_HISTORY_CHECKPOINT_V2.json"); ap.add_argument("--output",default="artifacts/RATE_TPEX_HISTORY_BOOTSTRAP_EVIDENCE.json"); ap.add_argument("--max-months",type=int,default=36); a=ap.parse_args(); r=bootstrap(trading_date=a.trading_date,checkpoint=Path(a.checkpoint),output=Path(a.output),max_months=a.max_months); print(json.dumps({"status":r["status"],"raw_coverage":r["raw_coverage"],"request_count":r["monthly_request_count"]})); return 0 if r["status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())

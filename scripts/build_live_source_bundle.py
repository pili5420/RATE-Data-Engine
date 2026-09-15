"""Build live bundle from authorized sources; never falls back to fixtures."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.sources.twse import TWSEAdapter
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--trading-date',required=True); ap.add_argument('--output',required=True); a=ap.parse_args()
 try:
  t=TWSEAdapter().fetch_t86(a.trading_date); payload=t.get('payload',t); rows=payload if isinstance(payload,list) else payload.get('data',[])
  if not rows: raise RuntimeError('PRODUCTION_SOURCE_UNAVAILABLE')
  raise RuntimeError('BLOCKED:PRODUCTION_DECISION_INPUT_UNAVAILABLE')
 except Exception as e:
  print(json.dumps({'validation_status':'BLOCKED','blocking_reason':str(e)})); return 1
if __name__=='__main__': raise SystemExit(main())

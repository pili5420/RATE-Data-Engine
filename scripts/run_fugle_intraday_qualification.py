"""Manual-only Fugle free/basic feasibility diagnostic. No Production mutation."""
from __future__ import annotations
import argparse, json, os
from datetime import datetime, timezone
from pathlib import Path

from src.provider_fugle_intraday_candidate import qualify

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--binding", default="docs/contracts/RATE_FUGLE_FREE_INTRADAY_UNIVERSE_BINDING_V1.json")
    p.add_argument("--trading-date", required=True)
    p.add_argument("--cadence", required=True, choices=["09:30","12:00"])
    p.add_argument("--output", required=True)
    a=p.parse_args()
    token=os.getenv("FUGLE_API_KEY","")
    binding=json.loads(Path(a.binding).read_text(encoding="utf-8"))
    result=qualify(token,binding,trading_date=a.trading_date,cadence=a.cadence,now_utc=datetime.now(timezone.utc))
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("technical_validation_status","market_coverage","license_gate","production_eligible")},sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json
from src.production_live_state import CADENCE_DIR, PERSIST_NAME, load_live_state, read_object, validate_material
from src.route_b_official_checkpoint import build_canonical_persist_material, transition


def main() -> int:
    parser=argparse.ArgumentParser(description="Execute RATE V11 Route B zero-fee Production checkpoint")
    parser.add_argument("--source-bundle",required=True)
    parser.add_argument("--previous-evidence",required=True)
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--state-root",required=True)
    parser.add_argument("--cadence",required=True,choices=["09:30","12:00"])
    args=parser.parse_args()

    out=Path(args.output_dir)
    out.mkdir(parents=True,exist_ok=True)
    try:
        previous_path=Path(args.previous_evidence).resolve()
        if previous_path.name != PERSIST_NAME:
            raise RuntimeError("ROUTE_B_PREVIOUS_EVIDENCE_NAME_INVALID")
        trading_date=previous_path.parent.parent.name
        previous_cadence="07:30" if args.cadence=="09:30" else "09:30"
        live_root=previous_path.parents[3]
        previous=load_live_state(live_root,trading_date,previous_cadence)["state"]
        bundle=read_object(args.source_bundle)
        state=transition(previous,bundle,trading_date=trading_date,cadence=args.cadence)
        persist,material=build_canonical_persist_material(state)
        validate_material(persist,material,trading_date,args.cadence)

        root=Path(args.state_root).resolve()
        target=root/"decision_state"/CADENCE_DIR[args.cadence]/(state["current_state_id"]+".json")
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if read_object(target) != material:
                raise RuntimeError("ROUTE_B_STATE_IDEMPOTENCY_CONFLICT")
        else:
            atomic_write_json(target,material)

        persist_name="RATE_CER076_PERSIST_RESULT_EVIDENCE.json" if args.cadence=="09:30" else "RATE_CER077_PERSIST_RESULT_EVIDENCE.json"
        atomic_write_json(out/persist_name,persist)
        result={
            "artifact":"RATE_ROUTE_B_ZERO_FEE_RUNTIME_RESULT_V1",
            "validation_status":"PASS",
            "route_b_zero_fee":True,
            "trading_date":trading_date,
            "cadence":args.cadence,
            "previous_state_id":state["previous_state_id"],
            "current_state_id":state["current_state_id"],
            "current_state_hash":state["decision_payload_hash"],
            "official_public_evidence_gate":"PASS",
            "current_intraday_price":None,
            "current_intraday_volume":None,
            "intraday_rerank_performed":False,
            "paper_trade_fill_count":0,
            "fallback_used":False,
            "scheduled_soak_credit":True,
        }
        atomic_write_json(out/"RATE_ROUTE_B_RUNTIME_RESULT.json",result)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0
    except Exception as exc:
        atomic_write_json(out/"RATE_ROUTE_B_RUNTIME_RESULT.json",{
            "artifact":"RATE_ROUTE_B_ZERO_FEE_RUNTIME_RESULT_V1",
            "validation_status":"FAIL_CLOSED",
            "reason":str(exc),
            "route_b_zero_fee":True,
            "fallback_used":False,
            "scheduled_soak_credit":False,
        })
        print(json.dumps({"validation_status":"FAIL_CLOSED","reason":str(exc)},sort_keys=True),file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())

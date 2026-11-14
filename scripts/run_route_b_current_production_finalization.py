from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json
from src.route_b_acceptance_store import load_store_snapshot
from src.route_b_current_production_finalization import build_finalization


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--repo-root",default=".")
    p.add_argument("--artifacts-root",default="artifacts")
    p.add_argument("--store-root",default="artifacts/production_acceptance/current")
    p.add_argument("--output-dir",default="artifacts/production_acceptance/final")
    a=p.parse_args()
    store=Path(a.store_root)
    out=Path(a.output_dir)
    out.mkdir(parents=True,exist_ok=True)
    try:
        snapshot=load_store_snapshot(store)
        if snapshot is None:
            result={"artifact":"RATE_ROUTE_B_CURRENT_PRODUCTION_FINALIZATION_PACKAGE_V1",
                    "validation_status":"PASS","runtime_mode":"NOOP_WAITING_FOR_SESSION",
                    "final_acceptance_granted":False}
            atomic_write_json(out/"RATE_ROUTE_B_CURRENT_PRODUCTION_FINALIZATION_PACKAGE.json",result)
            print(json.dumps(result,sort_keys=True))
            return 0
        session=snapshot["session"]
        summary=snapshot["summary"]
        if summary.get("completion_status")!="READY_FOR_CER081_FINAL_ACCEPTANCE":
            result={"artifact":"RATE_ROUTE_B_CURRENT_PRODUCTION_FINALIZATION_PACKAGE_V1",
                    "validation_status":"PASS","runtime_mode":"NOOP_SESSION_IN_PROGRESS",
                    "trading_days_tested":summary.get("trading_days_tested",0),
                    "successful_cadence_runs":summary.get("successful_cadence_runs",0),
                    "final_acceptance_granted":False}
            atomic_write_json(out/"RATE_ROUTE_B_CURRENT_PRODUCTION_FINALIZATION_PACKAGE.json",result)
            print(json.dumps(result,sort_keys=True))
            return 0
        package=build_finalization(
            a.repo_root,a.artifacts_root,
            activation=snapshot["activation"],
            session=session,
            session_summary=summary,
        )
        atomic_write_json(out/"RATE_CER081_SCHEDULER_RELIABILITY_SUMMARY.json",package["scheduler_reliability_summary"])
        atomic_write_json(out/"RATE_CER081_DETERMINISTIC_REPLAY_SUMMARY.json",package["deterministic_replay_summary"])
        atomic_write_json(out/"RATE_CER081_MODEL_FREEZE_SUMMARY.json",package["model_freeze_summary"])
        atomic_write_json(out/"RATE_ROUTE_B_DETERMINISTIC_STATE_HASH_REPLAY.json",package["deterministic_replay_detail"])
        atomic_write_json(out/"RATE_ROUTE_B_GIT_ANCESTRY_EVIDENCE.json",package["git_ancestry_evidence"])
        atomic_write_json(out/"RATE_V11_CURRENT_PRODUCTION_FINAL_ACCEPTANCE_V2.json",package["final_acceptance"])
        atomic_write_json(out/"RATE_ROUTE_B_CURRENT_PRODUCTION_FINALIZATION_PACKAGE.json",package)
        print(json.dumps(package["final_acceptance"],sort_keys=True))
        return 0
    except Exception as exc:
        result={"artifact":"RATE_ROUTE_B_CURRENT_PRODUCTION_FINALIZATION_PACKAGE_V1",
                "validation_status":"FAIL_CLOSED","final_acceptance_granted":False,
                "reason":str(exc)}
        atomic_write_json(out/"RATE_ROUTE_B_CURRENT_PRODUCTION_FINALIZATION_PACKAGE.json",result)
        print(json.dumps(result,sort_keys=True),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())

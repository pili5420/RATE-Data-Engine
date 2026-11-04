from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json
from src.route_b_acceptance_collector import collect_scheduled_run


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--cadence",required=True,choices=["07:30","09:30","12:00","19:30"])
    p.add_argument("--source-run-id",required=True)
    p.add_argument("--repo-root",default=".")
    p.add_argument("--artifacts-root",default="artifacts")
    p.add_argument("--source-artifacts-root",default="source_artifacts")
    p.add_argument("--store-root",default="artifacts/production_acceptance/current")
    p.add_argument("--output",required=True)
    a=p.parse_args()
    try:
        result=collect_scheduled_run(
            a.repo_root,a.artifacts_root,a.source_artifacts_root,a.store_root,
            cadence=a.cadence,source_run_id=a.source_run_id,
        )
        atomic_write_json(Path(a.output),result)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0
    except Exception as exc:
        result={"artifact":"RATE_ROUTE_B_ACCEPTANCE_COLLECTOR_RESULT_V1",
                "validation_status":"FAIL_CLOSED","cadence":a.cadence,
                "source_workflow_run_id":str(a.source_run_id),
                "session_written":False,"reason":str(exc)}
        atomic_write_json(Path(a.output),result)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True),file=sys.stderr)
        return 1

if __name__=="__main__":
    raise SystemExit(main())

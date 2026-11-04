from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from src.cer074_acceptance import atomic_write_json
from src.route_b_activation_package import build_runtime_package


def main() -> int:
    p=argparse.ArgumentParser(description="Build Route B activation/session runtime package")
    p.add_argument("--source-1200-run-id",required=True)
    p.add_argument("--repo-root",default=".")
    p.add_argument("--artifacts-root",default="artifacts")
    p.add_argument("--output-dir",required=True)
    a=p.parse_args()
    out=Path(a.output_dir)
    out.mkdir(parents=True,exist_ok=True)
    try:
        package=build_runtime_package(
            a.repo_root,a.artifacts_root,
            source_1200_run_id=a.source_1200_run_id,
        )
        atomic_write_json(out/"RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE.json",package)
        if package.get("runtime_mode")=="ACTIVE":
            atomic_write_json(out/"RATE_ROUTE_B_OVERLAY_0930.json",package["overlay_0930"])
            atomic_write_json(out/"RATE_ROUTE_B_OVERLAY_1200.json",package["overlay_1200"])
            atomic_write_json(out/"RATE_ROUTE_B_GIT_ANCESTRY_EVIDENCE.json",package["ancestry_evidence"])
            atomic_write_json(out/"RATE_POST_MERGE_PRODUCTION_ACTIVATION_VERIFICATION.json",package["activation"])
            atomic_write_json(out/"RATE_V11_PRODUCTION_ACCEPTANCE_SESSION.json",package["session"])
        print(json.dumps(package,ensure_ascii=False,sort_keys=True))
        return 0
    except Exception as exc:
        result={
            "artifact":"RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE_V1",
            "validation_status":"FAIL_CLOSED",
            "production_credit":0,
            "session_opened":False,
            "reason":str(exc),
        }
        atomic_write_json(out/"RATE_ROUTE_B_ACTIVATION_RUNTIME_PACKAGE.json",result)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())

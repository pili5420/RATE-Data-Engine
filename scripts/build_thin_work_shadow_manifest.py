from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.thin_work_manifest import build_shadow_manifest, validate_shadow_manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a RATE Thin Work shadow manifest without mutating production.")
    parser.add_argument("--production-artifact", default="artifacts/RATE_PRODUCTION_SOURCE_BUNDLE_LATEST.json")
    parser.add_argument("--output", default="artifacts/RATE_THIN_WORK_PRODUCTION_BUNDLE_MANIFEST_V1.json")
    parser.add_argument("--cadence", required=True)
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local-shadow"))
    parser.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", "manual"))
    parser.add_argument("--commit-sha", default=os.environ.get("GITHUB_SHA", "local"))
    parser.add_argument("--market-date", required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    manifest = build_shadow_manifest(
        production_artifact_path=root / args.production_artifact,
        cadence=args.cadence,
        run_id=args.run_id,
        event=args.event,
        commit_sha=args.commit_sha,
        market_date=args.market_date,
    )
    validation = validate_shadow_manifest(manifest, root=root, expected_run_id=args.run_id, expected_commit_sha=args.commit_sha)
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({**manifest, "contract_validation": validation}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(validation, sort_keys=True))
    return 0 if validation["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

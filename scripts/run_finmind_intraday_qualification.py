"""Run RATE FinMind Sponsor Snapshot qualification.

DIAGNOSTIC_ONLY: never mutates Production registry/schedulers and never persists raw responses.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.provider_finmind_intraday_candidate import qualify, QualificationError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--universe-file")
    parser.add_argument("--output", default="artifacts/finmind_intraday_qualification/RATE_FINMIND_INTRADAY_QUALIFICATION.json")
    parser.add_argument("--max-stock-age-seconds", type=int, default=120)
    parser.add_argument("--max-futures-age-seconds", type=int, default=180)
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    if not args.live:
        result = {
            "artifact_kind": "RATE_FINMIND_INTRADAY_QUALIFICATION_RESULT_V1",
            "scope": "FINMIND_INTRADAY_DIAGNOSTIC_ONLY",
            "classification": "ENGINEERING_ONLY_NO_LIVE_PROVIDER_CALL",
            "decision_eligible": False,
            "production_eligible": False,
        }
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0

    token = os.environ.get("FINMIND_API_TOKEN", "")
    try:
        result = qualify(
            token,
            universe_path=args.universe_file,
            max_stock_age_seconds=args.max_stock_age_seconds,
            max_futures_age_seconds=args.max_futures_age_seconds,
        )
        rc = 0 if result["classification"] in {"PASS_CANDIDATE", "PARTIAL_CANDIDATE"} else 2
    except QualificationError as exc:
        result = {
            "artifact_kind": "RATE_FINMIND_INTRADAY_QUALIFICATION_RESULT_V1",
            "scope": "FINMIND_INTRADAY_DIAGNOSTIC_ONLY",
            "classification": "FAIL_CLOSED",
            "reason": str(exc),
            "raw_response_persisted": False,
            "credential_persisted": False,
            "source_registry_modified": False,
            "production_scheduler_modified": False,
            "external_dependency_resolved": False,
            "decision_eligible": False,
            "production_eligible": False,
        }
        rc = 2

    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

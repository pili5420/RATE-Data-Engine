"""Prepare Phase 2 review evidence only; no production publication or persistence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.cer074_acceptance import atomic_write_json
from src.full_market_rotation import evaluate_rotation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", default=str(ROOT / "artifacts/production_state"))
    parser.add_argument("--previous-trading-date", required=True)
    parser.add_argument("--previous-cadence", required=True)
    parser.add_argument("--trading-date", required=True)
    parser.add_argument("--cadence", required=True)
    parser.add_argument("--catalogue")
    parser.add_argument("--inputs")
    parser.add_argument("--contract", default=str(ROOT / "config/RATE_FULL_MARKET_ROTATION_CONTRACT_V1.json"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.name != "RATE_PHASE2_FULL_MARKET_ROTATION_REVIEW.json":
        parser.error("REVIEW_OUTPUT_FILENAME_REQUIRED")
    protected = [ROOT / path for path in ("artifacts", "data", "control", "src", "scripts", "config", ".github")]
    protected.append(Path(args.state_root).resolve())
    if any(output.is_relative_to(path.resolve()) for path in protected):
        parser.error("PRODUCTION_NAMESPACE_WRITE_FORBIDDEN")
    def read(path):
        return json.loads(Path(path).read_bytes()) if path else None
    try:
        result = evaluate_rotation(state_root=args.state_root, previous_trading_date=args.previous_trading_date,
                                   previous_cadence=args.previous_cadence, trading_date=args.trading_date,
                                   cadence=args.cadence, catalogue=read(args.catalogue), inputs=read(args.inputs),
                                   contract=read(args.contract))
    except (OSError, ValueError) as exc:
        result = {"validation_status": "FAIL_CLOSED", "blocking_reason": "INPUT_MATERIAL_UNREADABLE",
                  "detail": str(exc), "ranking": None, "production_publication_allowed": False}
    atomic_write_json(output, result)
    print(json.dumps({key: value for key, value in result.items() if key != "ranking"}, sort_keys=True))
    return 0 if result["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

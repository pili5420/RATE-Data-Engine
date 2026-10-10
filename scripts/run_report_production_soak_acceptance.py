"""Explicit, read-only report-soak acceptance; no acquisition or publishing."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.cer074_acceptance import atomic_write_json
from src.report_production_soak import evaluate, pinned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    if output.exists():
        raise RuntimeError("REPORT_SOAK_OUTPUT_MUST_BE_NEW")
    state_root = Path(args.state_root).resolve()
    if output == state_root or output.is_relative_to(state_root):
        raise RuntimeError("REPORT_SOAK_READ_ONLY_NAMESPACE_REQUIRED")
    output.mkdir(parents=True)
    try:
        result = evaluate(evidence=pinned({"path": args.evidence, "sha256": args.evidence_sha256}), state_root=state_root)
    except Exception as exc:
        import traceback
        (output / "traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        result = {"validation_status": "FAIL", "RATE_REPORT_PRODUCTION_SOAK": "FAIL",
            "CER081_FULL_PRODUCTION_SOAK": "BLOCKED_EXTERNAL", "cer081_credit": 0,
            "fallback_allowed": False, "reason": str(exc)}
    atomic_write_json(output / "REPORT_SOAK_ACCEPTANCE.json", result)
    return 0 if result["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

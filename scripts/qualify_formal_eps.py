"""Offline receipt replay, never a warmup or a source acquisition command."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.formal_eps_qualification import BOUNDARY, inspect_mops_response
from src.full_market_history import digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() or args.output_dir.resolve().is_relative_to(args.history_root.resolve()):
        raise ValueError("QUALIFICATION_OUTPUT_MUST_BE_NEW_EXTERNAL_DIRECTORY")
    data = args.plan.read_bytes()
    if hashlib.sha256(data).hexdigest() != args.plan_sha256:
        raise ValueError("QUALIFICATION_PLAN_HASH_MISMATCH")
    plan = json.loads(data)
    if plan["plan_id"] != "rate-history-plan-" + digest({k: v for k, v in plan.items() if k != "plan_id"})[:24]:
        raise ValueError("QUALIFICATION_PLAN_IDENTITY_INVALID")
    rows, hashes = [], {str(args.plan.resolve()): args.plan_sha256}
    for path in sorted((args.history_root / "reports/mops").glob("*.json")):
        receipt = json.loads(path.read_bytes())
        if receipt["plan_id"] != plan["plan_id"] or receipt["domain"] != "eps":
            continue
        reference = {"path": path.relative_to(args.history_root).as_posix(), "sha256": digest(receipt)}
        row = inspect_mops_response(args.history_root, reference, plan)
        rows.append(row)
        hashes[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[str((args.history_root / receipt["raw_path"]).resolve())] = row["raw_sha256"]
    if not rows:
        raise ValueError("QUALIFICATION_NO_SAVED_EPS_RESPONSES")
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != h for p, h in hashes.items()):
        raise ValueError("QUALIFICATION_INPUT_CHANGED")
    result = {**BOUNDARY, "MOPS_FORMAL_EPS_PERIOD_IDENTITY": "NOT_PROVEN",
              "plan_id": plan["plan_id"], "plan_sha256": args.plan_sha256,
              "original_execution_head": plan["runtime_authority"]["commit_sha"],
              "receipt_count": len(rows), "unique_raw_count": len({r["raw_sha256"] for r in rows}),
              "by_market": dict(Counter(r["market"] for r in rows)), "responses": rows,
              "historical_pit_status": "UNPROVEN", "formal_eight_quarter_qualified_companies": 0,
              "input_sha256_before_equals_after": hashes, "financial_requests": 0}
    args.output_dir.mkdir(parents=True)
    (args.output_dir / "MOPS_QUALIFICATION.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("responses", "input_sha256_before_equals_after")}))


if __name__ == "__main__":
    main()

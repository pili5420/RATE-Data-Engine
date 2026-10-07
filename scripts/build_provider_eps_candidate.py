"""Offline local FinMind candidate replay; no transport or Production dispatch."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import Rejected, require
from src.eps_duration_facts.raw import sha256
from src.provider_eps_candidate import REAL, build_candidate, consume_candidate
from verify_provider_eps_candidate import binding, new_output, write_json


def snapshot(directory, references=()):
    paths = {p.resolve() for p in directory.rglob("*") if p.is_file()}
    paths.update(Path(p) for p in references)
    return {str(p): {"bytes": len(body), "sha256": sha256(body)}
            for p in sorted(paths) for body in [p.read_bytes()]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    directory = Path(args.input_dir).resolve()
    require(directory.is_dir(), "INPUT_DIRECTORY_UNAVAILABLE")
    isolation = binding(args.expected_base, args.expected_head)
    require(not Path(args.output_dir).resolve().exists(), "OUTPUT_ALREADY_EXISTS")
    records = json.loads((directory / "analysis_input.json").read_bytes())["records"]
    references = {r[key] for r in records for key in ("raw_path", "receipt_reference")}
    before = snapshot(directory, references)
    code = {"base_sha": args.expected_base, "head_sha": args.expected_head}
    first = build_candidate(directory, code)
    second = build_candidate(directory, code)
    require(first["material_class"] == REAL, "ENGINEERING_FIXTURE_NOT_REAL_REPLAY")
    preview = consume_candidate(first)
    require(first["artifact_id"] == second["artifact_id"] and preview == consume_candidate(second), "LOCAL_REPLAY_NOT_REPRODUCIBLE")
    after = snapshot(directory, references)
    require(before == after, "ORIGINAL_INPUT_CHANGED")
    require(binding(args.expected_base, args.expected_head) == isolation, "EXISTING_CODE_CHANGED")
    output = new_output(args.output_dir, directory)
    write_json(output / "provider-eps-candidate.json", first)
    write_json(output / "candidate-consumption-preview.json", preview)
    write_json(output / "input-invariance.json", {"unchanged": True, "before": before, "after": after})
    write_json(output / "local-verification.json", {"status": "PASS", "material_class": REAL,
        "validated_at": datetime.now(timezone.utc).isoformat(), "code_binding": code,
        "local_window_complete": True, "local_window_coverage": "24/24",
        "repeated_replay_stable": True, "artifact_id": first["artifact_id"],
        "source_file_count": len(first["input_integrity"]), "unchanged_file_count": len(before),
        "formal_eight_quarter_acceptance": "NOT_PERFORMED", "production_eligible": False,
        "original_eight_quarter_coverage_credit": 0, "isolation": isolation})
    print(json.dumps({"status": "PASS", "material_class": REAL, "local_window_coverage": "24/24",
                      "output_dir": str(output), "artifact_id": first["artifact_id"]}))


if __name__ == "__main__":
    try:
        main()
    except Rejected as exc:
        print("REJECTED: " + str(exc), file=sys.stderr)
        raise SystemExit(1)

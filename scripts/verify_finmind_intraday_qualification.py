"""Verify additive-only FinMind intraday diagnostic engineering."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require

ADDITIONS = {
    "docs/contracts/RATE_FINMIND_INTRADAY_QUALIFICATION_V1.json",
    "docs/RATE_FINMIND_INTRADAY_QUALIFICATION_V1.md",
    "src/provider_finmind_intraday_candidate.py",
    "scripts/run_finmind_intraday_qualification.py",
    "scripts/verify_finmind_intraday_qualification.py",
    "tests/test_finmind_intraday_qualification.py",
    ".github/workflows/rate_finmind_intraday_qualification.yml",
}

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)

def tracked_hashes(paths):
    return {path: git("rev-parse", "HEAD:" + path).decode().strip() for path in paths}

def put(root, name, value):
    path = Path(root) / name
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")

def run_module(module):
    proc = subprocess.run([sys.executable, "-B", "-m", "unittest", module, "-v"], cwd=ROOT,
                          capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    count = output.count(" ... ok")
    require(proc.returncode == 0, "FINMIND_DIAGNOSTIC_TEST_FAILURE:" + module + "\n" + output)
    return {"module": module, "count": count, "status": "PASS"}

def isolation(base, head):
    require(git("rev-parse", "HEAD").decode().strip() == head, "FINMIND_DIAGNOSTIC_EXACT_HEAD_REQUIRED")
    require(not git("status", "--porcelain", "--untracked-files=all"), "FINMIND_DIAGNOSTIC_CLEAN_REQUIRED")
    git("merge-base", "--is-ancestor", base, head)
    changed = set(git("diff", "--name-status", "--no-renames", base, head).decode().splitlines())
    require(changed == {"A\t" + path for path in ADDITIONS}, "FINMIND_DIAGNOSTIC_ADDITIVE_SCOPE_VIOLATION")
    paths = git("ls-tree", "-r", "--name-only", base).decode().splitlines()
    for path in paths:
        require(git("rev-parse", base + ":" + path) == git("rev-parse", head + ":" + path),
                "FINMIND_DIAGNOSTIC_EXISTING_BLOB_CHANGED:" + path)
    return {"base_sha": base, "head_sha": head, "protected_file_count": len(paths),
            "protected_hashes": tracked_hashes(paths), "changed_files": sorted(ADDITIONS)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    out = Path(args.output_dir).resolve()
    require(not out.exists(), "FINMIND_DIAGNOSTIC_NEW_OUTPUT_REQUIRED")
    out.mkdir(parents=True)
    before = isolation(args.expected_base, args.expected_head)
    put(out, "protected-before.json", before)
    tests = [
        run_module("tests.test_finmind_intraday_qualification"),
        run_module("tests.test_production_scheduler_change_control"),
        run_module("tests.test_rate_soak_005"),
    ]
    after = isolation(args.expected_base, args.expected_head)
    require(before == after, "FINMIND_DIAGNOSTIC_CODE_MUTATED_DURING_TESTS")
    put(out, "protected-after.json", after)
    result = {
        "status": "PASS",
        "scope": "FINMIND_INTRADAY_DIAGNOSTIC_ONLY",
        "base_sha": args.expected_base,
        "head_sha": args.expected_head,
        "tests": tests,
        "test_count": sum(t["count"] for t in tests),
        "protected_file_count": before["protected_file_count"],
        "protected_bytes_and_blobs_unchanged": True,
        "production_registry_modified": False,
        "production_scheduler_modified": False,
        "external_dependency_resolved": False,
        "decision_eligible": False,
        "production_eligible": False,
        "live_provider_requests": 0,
    }
    put(out, "VERIFICATION_PACKAGE.json", result)
    print(json.dumps(result, sort_keys=True))

if __name__ == "__main__":
    main()

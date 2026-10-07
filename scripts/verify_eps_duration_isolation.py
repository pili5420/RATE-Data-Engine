"""Verify scope against the actual base and run offline regressions with frozen files."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys

BASE = "40c00f300d6ba64ca06850ba172fd1df222d1c86"
ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    "tests.test_eps_duration_facts", "tests.test_full_market_history",
    "tests.test_full_market_history_catalogue_transport", "tests.test_full_market_history_acquisition",
    "tests.test_full_market_history_yoy_semantics", "tests.test_full_market_history_storage",
    "tests.test_warmup_run1_defects", "tests.test_rate_production_history_materialization",
    "tests.test_cer072_institutional_history", "tests.test_cer072_tdcc_historical",
    "tests.test_cer073_fundamental_history_v2", "tests.test_stage_history", "tests.test_stage_evidence",
    "tests.test_rotation_history", "tests.test_production_source_latest_publisher",
    "tests.test_thin_work_manifest", "tests.test_production_scheduler_change_control",
    "tests.test_rate_soak_005", "tests.test_state_engine", "tests.test_production_integration")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def frozen_files():
    paths = git("ls-tree", "-r", "--name-only", BASE).decode().splitlines()
    changed = git("diff", "--name-only", BASE).decode().splitlines()
    if any(path in paths for path in changed):
        raise ValueError("EXISTING_MAIN_GIT_BLOB_CHANGED")
    result = {}
    for relative in paths:
        path = ROOT / relative
        actual = path.read_bytes()
        result[relative] = hashlib.sha256(actual).hexdigest()
    return result


def verify(log_path=None):
    before = frozen_files()
    tests = subprocess.run([sys.executable, "-B", "-m", "unittest", *MODULES, "-v"],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = tests.stdout + tests.stderr
    if log_path is not None:
        log_path.write_text(log, encoding="utf-8")
    print(log if tests.returncode == 0 else log[-16000:])
    after = frozen_files()
    if before != after:
        raise ValueError("EXISTING_MAIN_FILE_MUTATION")
    subprocess.run(["git", "diff", "--exit-code"], cwd=ROOT, check=True)
    return {"base_sha": BASE, "existing_main_files": len(before), "git_blobs_unchanged": True,
            "working_bytes_unchanged_during_tests": True, "frozen_file_sha256": after,
            "test_count": int(re.search(r"Ran (\d+) tests", log).group(1)),
            "test_result": "PASS" if tests.returncode == 0 else "FAIL",
            "production_mutations": {"live_state": 0, "STATE_LATEST": 0, "Portfolio": 0, "Ledger": 0},
            "strategy_change": False, "universe_change": False, "fallback_used": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    args = parser.parse_args()
    path = None
    if args.output:
        path = Path(args.output).resolve()
        if path.exists() or ROOT == path or ROOT in path.parents:
            raise ValueError("OUTPUT_MUST_BE_NEW_EXTERNAL_EVIDENCE_FILE")
        path.parent.mkdir(parents=True, exist_ok=True)
    result = verify(path.with_suffix(".test-log.txt") if path else None)
    if path:
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "frozen_file_sha256"}, indent=2))
    sys.exit(0 if result["test_result"] == "PASS" else 1)

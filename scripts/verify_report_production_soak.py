"""Exact-base/head, synthetic-only verification. Reuse the strict PR42 harness."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_public_official_partial_valid import OLD_MODULES, extract, git, test_run, write

BASE = "1cc808d0e809822db057ff88afa0c55dedef13b7"
ALLOWED = {
    "src/cer081_unattended_soak.py", "src/report_production_soak.py",
    "scripts/run_cer081_unattended_soak_acceptance.py", "scripts/run_report_production_soak_acceptance.py",
    "scripts/publish_production_source_bundle_latest.py", "scripts/verify_report_production_soak.py",
    "tests/report_soak_support.py", "tests/test_report_production_soak.py",
    "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json", "config/RATE_FOUR_CADENCE_REPORT_SOAK_V1.json",
    "docs/RATE_FOUR_CADENCE_REPORT_SOAK_V1.md", ".github/workflows/rate_public_official_partial_valid_ci.yml",
}


def proof(output):
    from tests.report_soak_support import ReportSoakFixture, reference
    from src.production_live_state import file_hash, read_object
    from src import report_production_soak as report
    from src.cer074_acceptance import atomic_write_json
    from tests.test_cer081_unattended_soak import cer080_persisted_fixture
    fixture = ReportSoakFixture()
    try:
        before = fixture.hashes()
        command = [sys.executable, "-B", "scripts/run_report_production_soak_acceptance.py", "--evidence", str(fixture.input_path),
            "--evidence-sha256", file_hash(fixture.input_path), "--state-root", str(fixture.artifacts / "production_state"),
            "--output-dir", str(output / "cold-report-acceptance")]
        cold = subprocess.run(command, capture_output=True, text=True)
        (output / "cold-report-acceptance.log").write_text(cold.stdout + cold.stderr, encoding="utf-8")
        if cold.returncode: raise RuntimeError("REPORT_SOAK_COLD_READ_FAILED")
        result = read_object(output / "cold-report-acceptance/REPORT_SOAK_ACCEPTANCE.json")
        atomic_write_json(output / "synthetic-cer080.json", cer080_persisted_fixture())
        atomic_write_json(output / "synthetic-cer081-runs.json", {"runs": [dict(run, event_name="schedule") for run in result["runs"]]})
        cer = subprocess.run([sys.executable, "-B", "scripts/run_cer081_unattended_soak_acceptance.py",
            "--cer080-persisted-evidence", str(output / "synthetic-cer080.json"),
            "--scheduled-runs-json", str(output / "synthetic-cer081-runs.json"), "--output-dir", str(output / "cer081-hold")],
            capture_output=True, text=True)
        (output / "cer081-hold.log").write_text(cer.stdout + cer.stderr, encoding="utf-8")
        summary = read_object(output / "cer081-hold/RATE_CER081_SOAK_SUMMARY.json")
        if cer.returncode == 0 or summary["successful_cadence_runs"] != 0 or summary["CER081_FULL_PRODUCTION_SOAK"] != "BLOCKED_EXTERNAL":
            raise RuntimeError("CER081_FAIL_CLOSED_PROOF_FAILED")
        if fixture.hashes() != before: raise RuntimeError("READ_ONLY_ACCEPTANCE_MUTATED_EVIDENCE")
        shutil.copytree(fixture.base, output / "synthetic-three-day-chain")
        value = {"evidence_scope": "SYNTHETIC_ENGINEERING_ONLY_NOT_LIVE_SOAK", "real_source_requests": 0,
            "cadence_runtime_calls": fixture.cli_results,
            "morning_state_role": "SYNTHETIC_TRANSPORT_FIXTURE_NOT_LIVE_0730_EXECUTION",
            "report_acceptance": result, "cer081_cli_exit_code": cer.returncode,
            "cer081_full_production_soak": summary["CER081_FULL_PRODUCTION_SOAK"],
            "cer081_successful_cadence_runs": summary["successful_cadence_runs"],
            "state_source_account_ledger_files_unchanged": len(before),
            "archive_hashes": {str(p.relative_to(output)): file_hash(p) for p in (output / "synthetic-three-day-chain").rglob("*") if p.is_file()}}
        write(output / "THREE_DAY_SEPARATION_PROOF.json", value)
    finally:
        fixture.close()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--proof-child":
        sys.path.insert(0, str(Path.cwd()))
        proof(Path(sys.argv[2]))
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    if output.exists(): raise RuntimeError("VERIFICATION_OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    if args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head or git("merge-base", BASE, "HEAD") != BASE:
        raise RuntimeError("EXACT_BASE_HEAD_MISMATCH")
    changed = git("diff", "--name-only", BASE, args.expected_head).splitlines()
    if not changed or set(changed) - ALLOWED or git("status", "--porcelain"):
        raise RuntimeError("CHANGE_SCOPE_OR_CLEAN_WORKTREE_VIOLATION")
    def tree(revision):
        return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2] for line in git("ls-tree", "-r", revision).splitlines()}
    old_tree, new_tree = tree(BASE), tree(args.expected_head)
    protected = {path: digest for path, digest in old_tree.items() if path not in ALLOWED}
    if any(new_tree.get(path) != digest for path, digest in protected.items()):
        raise RuntimeError("PROTECTED_FILE_CHANGED")
    write(output / "protected-files.json", protected)
    old_dependency = json.loads(git("show", BASE + ":config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json"))
    new_dependency = json.loads(git("show", args.expected_head + ":config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json"))
    expected = {"report_soak_credit_allowed_while_intraday_blocked": True,
        "report_soak_credit_scope": "PUBLIC_OFFICIAL_EVIDENCE_PARTIAL_VALID_REPORT_SOAK_ONLY",
        "report_soak_acceptance_id": "RATE-FOUR-CADENCE-REPORT-SOAK-V1"}
    for key, value in expected.items():
        if new_dependency["dependencies"][0].pop(key, None) != value: raise RuntimeError("REPORT_GOVERNANCE_INVALID")
    if new_dependency != old_dependency: raise RuntimeError("EXISTING_DEPENDENCY_GOVERNANCE_CHANGED")
    with tempfile.TemporaryDirectory(prefix="rs-", dir=ROOT.parent) as temporary:
        mirror = Path(temporary) / "head"
        extract(args.expected_head, mirror)
        old = test_run(mirror, output / "existing-131.json", OLD_MODULES)
        pr42 = test_run(mirror, output / "pr42-56.json", ["test_public_official_partial_valid", "test_partial_to_evening_acceptance"])
        scheduler = test_run(mirror, output / "scheduler-lock-8.json", ["test_cer081_scheduler_lock_validation"])
        new = test_run(mirror, output / "report-soak-new-tests.json", ["test_report_production_soak"])
        child = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_report_production_soak.py"),
            "--proof-child", str(output)], cwd=mirror, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
        (output / "three-day-proof.log").write_text(child.stdout + child.stderr, encoding="utf-8")
    passed = all(r["all_pass"] for r in (old, pr42, scheduler, new)) and (old["tests_run"], pr42["tests_run"], scheduler["tests_run"], new["tests_run"]) == (131, 56, 8, 34) and child.returncode == 0
    package = {"base_sha": BASE, "head_sha": args.expected_head, "changed_files": changed, "evidence_scope": "SYNTHETIC_ONLY",
        "existing_131": old, "pr42_56": pr42, "scheduler_lock_8": scheduler, "new_tests": new,
        "three_day_proof_exit_code": child.returncode, "protected_files_unchanged": len(protected),
        "existing_governance_flags_unchanged": True, "validation_status": "PASS" if passed else "FAIL"}
    write(output / "VERIFICATION_PACKAGE.json", package)
    print(json.dumps({key: value for key, value in package.items() if key not in {"existing_131", "pr42_56", "scheduler_lock_8", "new_tests"}}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Synthetic-only exact-head verification; existing failures are never hidden."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = "af5ed52a78a7cea761e985011d234aa66f18b3e1"
OLD_MODULES = ["test_cer074_acceptance", "test_cer075_scheduler", "test_cer076_incremental_0930",
    "test_cer077_incremental_1200", "test_cer078_evening_1930", "test_cer079_full_day_chain",
    "test_cer080_multi_day_continuity", "test_cer081_unattended_soak", "test_production_scheduler_change_control",
    "test_rate_soak_005", "test_rate_production_source_acquisition", "test_production_source_latest_publisher",
    "test_fundamental", "test_spec_formulas", "test_logic", "test_production_integration", "test_trading_status"]
ALLOWED = {
    ".github/workflows/rate_public_official_partial_valid_ci.yml",
    ".github/workflows/rate_production_0930_scheduler.yml", ".github/workflows/rate_production_1200_scheduler.yml",
    "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json", "config/RATE_PUBLIC_OFFICIAL_PARTIAL_VALID_RUNTIME_V1.json",
    "src/public_official_partial_valid.py", "src/production_live_state.py",
    "scripts/build_production_source_bundle_from_official.py", "scripts/publish_production_source_bundle_latest.py",
    "scripts/publish_production_state_latest.py", "scripts/run_cer076_incremental_0930_acceptance.py",
    "scripts/run_cer077_incremental_1200_acceptance.py", "scripts/verify_public_official_partial_valid.py",
    "tests/test_public_official_partial_valid.py", "docs/RATE_PUBLIC_OFFICIAL_PARTIAL_VALID_RUNTIME_V1.md",
}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT).decode().strip()


def test_run(repo, output, modules):
    # Each invocation is a cold process; no imported test or runtime state is reused.
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--test-child", str(output), *modules]
    result = subprocess.run(command, cwd=repo, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    (output.parent / (output.stem + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
    if not output.exists():
        raise RuntimeError("TEST_CHILD_DID_NOT_PRODUCE_REPORT:" + str(result.returncode))
    return json.loads(output.read_text(encoding="utf-8"))


def extract(revision, directory):
    body = subprocess.check_output(["git", "archive", "--format=zip", revision], cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        for item in archive.infolist():
            if not (directory / item.filename).resolve().is_relative_to(directory.resolve()):
                raise RuntimeError("UNSAFE_TEST_ARCHIVE")
        archive.extractall(directory)


def child(output, modules):
    sys.path.insert(0, str(Path.cwd()))
    suite = unittest.defaultTestLoader.loadTestsFromNames(["tests." + name for name in modules])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    write(output, {"tests_run": result.testsRun, "failures": [{"test_id": t.id(), "traceback": text} for t, text in result.failures],
        "errors": [{"test_id": t.id(), "traceback": text} for t, text in result.errors],
        "skipped": [{"test_id": t.id(), "reason": reason} for t, reason in result.skipped],
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "all_pass": result.wasSuccessful() and not result.skipped})
    return 0 if result.wasSuccessful() else 1


def chain_proof(output):
    sys.path.insert(0, str(ROOT))
    from tests.test_public_official_partial_valid import PublicOfficialPartialValidTests
    from scripts.resolve_production_runtime_context import resolve_context
    from src.production_live_state import load_live_state
    test = PublicOfficialPartialValidTests()
    test.setUp()
    try:
        test.test_actual_cli_opt_in_0930_to_1200_cold_process()
        morning = load_live_state(test.artifacts / "production_state", test.day, "09:30")["state"]
        midday = load_live_state(test.artifacts / "production_state", test.day, "12:00")["state"]
        evening = resolve_context(cadence="19:30", event_name="workflow_dispatch", dispatch_trading_date=test.day,
            state_root=test.artifacts / "production_state")
        protected = ("roy_portfolio", "ai_paper_portfolio", "transaction_ledger")
        proof = {"evidence_scope": "SYNTHETIC_ENGINEERING_ONLY_NOT_LIVE", "real_financial_requests": 0,
            "previous_0730_state_id": test.previous["current_state_id"],
            "0930_state_id": morning["current_state_id"], "1200_state_id": midday["current_state_id"],
            "0930_to_1200": midday["previous_state_id"] == morning["current_state_id"],
            "1200_to_1930_resolver": evening["previous_state_id"] == midday["current_state_id"],
            "1930_full_legacy_acceptance": "NOT_CERTIFIED",
            "no_execution_or_ledger_mutation": all(test.previous["decision"][key] == morning["decision"][key] == midday["decision"][key] for key in protected),
            "gates": {key: midday["decision"][key] for key in ("public_official_evidence_gate", "market_intraday_price_gate",
                "report_runtime_status", "full_intraday_decision_status", "full_production_acceptance", "fallback_allowed")}}
        shutil.copytree(test.artifacts, output / "synthetic-chain")
        proof["archive_hashes"] = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (output / "synthetic-chain").rglob("*") if path.is_file()}
        write(output / "synthetic-chain-proof.json", proof)
        return proof
    finally:
        test.doCleanups()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        return child(Path(sys.argv[2]), sys.argv[3:])
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    if output.exists():
        raise RuntimeError("VERIFICATION_OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    if args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head or git("merge-base", BASE, "HEAD") != BASE:
        raise RuntimeError("EXACT_BASE_HEAD_MISMATCH")
    changed = git("diff", "--name-only", BASE, "HEAD").splitlines()
    if not changed or set(changed) - ALLOWED or git("diff", "HEAD", "--name-only"):
        raise RuntimeError("CHANGE_SCOPE_OR_TRACKED_WORKTREE_VIOLATION")
    def tree(revision):
        return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2]
            for line in git("ls-tree", "-r", revision).splitlines()}
    old_tree, new_tree = tree(BASE), tree("HEAD")
    protected = {}
    for path, old_blob in old_tree.items():
        if path not in ALLOWED:
            if old_blob != new_tree.get(path):
                raise RuntimeError("PROTECTED_FILE_CHANGED:" + path)
            protected[path] = old_blob
    write(output / "protected-files.json", protected)
    with tempfile.TemporaryDirectory(prefix="rate-public-partial-regression-") as temporary:
        root = Path(temporary)
        base, head = root / "base", root / "head"
        extract(BASE, base)
        extract(args.expected_head, head)
        old = test_run(base, output / "base-regressions.json", OLD_MODULES)
        current = test_run(head, output / "head-regressions.json", OLD_MODULES)
        new = test_run(head, output / "new-tests.json", ["test_public_official_partial_valid"])
    def outcomes(report):
        return sorted((kind, item["test_id"], item["traceback"].strip().splitlines()[-1])
            for kind in ("failures", "errors") for item in report[kind])
    no_new = outcomes(old) == outcomes(current) and old["tests_run"] == current["tests_run"] and not current["skipped"]
    proof = chain_proof(output)
    result = {"base_sha": BASE, "head_sha": args.expected_head, "changed_files": changed,
        "evidence_scope": "SYNTHETIC_ONLY", "existing_test_count": current["tests_run"], "existing_passed": current["passed"],
        "existing_failure_count": len(current["failures"]), "existing_error_count": len(current["errors"]),
        "new_test_count": new["tests_run"], "new_tests_all_pass": new["all_pass"],
        "no_new_regression": no_new, "all_existing_regressions_pass": current["all_pass"],
        "protected_files_unchanged": len(protected), "proof": proof,
        "validation_status": "PASS" if current["all_pass"] and new["all_pass"] and no_new else "REVIEW_REQUIRED_BASELINE_REGRESSIONS"}
    write(output / "VERIFICATION_PACKAGE.json", result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["validation_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the fixed R2 synthetic suite behind RATE's network audit guard."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_ci_applicability import network_guard

MODULES = [
    "test_intraday_fugle_r2_package",
    "test_intraday_fugle_r2_evidence",
    "test_intraday_fugle_github_fence_transport",
    "test_intraday_fugle_github_fence_adapter",
    "test_intraday_fugle_live_consumption_fence",
    "test_intraday_fugle_live_executor_orchestration",
    "test_intraday_fugle_single_live_executor",
    "test_fugle_intraday_qualification",
    "test_fugle_license_evidence",
    "test_intraday_fugle_single_live_authorization",
    "test_intraday_fugle_live_executor_rehearsal",
    "test_intraday_fugle_execution_review_bridge",
    "test_intraday_new_live_qualification_readiness",
    "test_intraday_exchange_authority_evidence_intake",
    "test_intraday_provider_authority",
]


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    head_before = git("rev-parse", "HEAD")
    status_before = git("status", "--porcelain")
    if head_before != args.expected_head or status_before:
        changed_paths = git("diff", "--name-only").splitlines()
        byte_checks = []
        for name in changed_paths[:3]:
            actual = (ROOT / name).read_bytes()
            expected = subprocess.check_output(["git", "-C", str(ROOT), "show", "HEAD:" + name])
            byte_checks.append({"path": name, "exact_bytes": actual == expected,
                                "lf_bytes": actual.replace(b"\r\n", b"\n") == expected})
        print(json.dumps({"head_before": head_before, "expected_head": args.expected_head,
                          "worktree_before": status_before.splitlines(),
                          "checkout_byte_diagnostics": byte_checks}, sort_keys=True))
        raise RuntimeError("R2_EXACT_HEAD_OR_CLEAN_WORKTREE_REQUIRED")
    sys.addaudithook(network_guard)
    suite = unittest.defaultTestLoader.loadTestsFromNames(["tests." + name for name in MODULES])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    head_after = git("rev-parse", "HEAD")
    status_after = git("status", "--porcelain")
    passed = (result.wasSuccessful() and not result.skipped
              and head_after == args.expected_head and not status_after)
    report = {
        "artifact": "RATE_FUGLE_R2_OFFLINE_CORRECTIVE_TEST_REPORT_V1",
        "source_sha": args.expected_head,
        "status": "PASS" if passed else "BLOCKED",
        "modules": MODULES,
        "tests_run": result.testsRun,
        "head_after": head_after,
        "worktree_after": status_after.splitlines(),
        "failures": [test.id() for test, _ in result.failures],
        "errors": [test.id() for test, _ in result.errors],
        "skipped": [test.id() for test, _ in result.skipped],
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "job_name": os.getenv("GITHUB_JOB"),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "evidence_scope": "PUBLIC_SYNTHETIC_ENGINEERING_SUMMARY",
        "real_credential_reads": 0,
        "real_provider_requests": 0,
        "live_execution_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "No-Auto-Next": True,
    }
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

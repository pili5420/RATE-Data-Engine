"""Actual base/head verification with synthetic fixtures only; no live scan."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.provider_eps_candidate import ENGINEERING
from src.provider_eps_coverage import initialize, make_plan, now, reuse_original, scan, summary
from tests.test_provider_eps_coverage import engineering_universe, fake_capture, FakeClock
from tests.provider_eps_engineering_fixture import make_fixture
from verify_provider_eps_candidate import binding, new_output, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    before = binding(args.expected_base, args.expected_head)
    output = new_output(args.output_dir)
    tests = subprocess.run([sys.executable, "-B", "-m", "unittest", "tests.test_provider_eps_candidate",
        "tests.test_provider_eps_coverage", "tests.test_provider_eps_recovery", "-v"], cwd=ROOT, text=True, capture_output=True)
    (output / "engineering-tests.log").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    require(tests.returncode == 0, "COVERAGE_ENGINEERING_TESTS_FAILED")
    metadata = subprocess.run([sys.executable, "-B", "-m", "unittest", "tests.test_provider_eps_metadata", "-v"],
                             cwd=ROOT, text=True, capture_output=True)
    (output / "metadata-cold-start-tests.log").write_text(metadata.stdout + metadata.stderr, encoding="utf-8")
    require(metadata.returncode == 0, "METADATA_COLD_START_TESTS_FAILED")
    wait = subprocess.run([sys.executable, "-B", "-m", "unittest", "tests.test_provider_eps_wait_semantics", "-v"],
                          cwd=ROOT, text=True, capture_output=True)
    (output / "dispatch-wait-semantics-tests.log").write_text(wait.stdout + wait.stderr, encoding="utf-8")
    require(wait.returncode == 0, "DISPATCH_WAIT_SEMANTICS_TESTS_FAILED")
    with tempfile.TemporaryDirectory(prefix="rate-coverage-ci-") as temporary:
        temp = Path(temporary)
        original = temp / "original"
        original.mkdir()
        make_fixture(original)
        universe = engineering_universe(temp / "ENGINEERING_UNIVERSE.json")
        plan = make_plan(universe, {"base_sha": args.expected_base, "head_sha": args.expected_head},
            {"path": "SYNTHETIC_FAKE_CAPTURE_NOT_NETWORK", "sha256": "0" * 64})
        root = initialize(temp / "ENGINEERING_COVERAGE", plan)
        reuse_original(root, plan, original)
        clock = FakeClock()
        stop = scan(root, plan, fake_capture(), sleep=clock.sleep, clock=clock.clock)
        report = summary(root, plan, stop)
        second = scan(root, plan, lambda *args, **kwargs: require(False, "REPEATED_FETCH_FORBIDDEN"))
        require(second["new_requests"] == 0 and report["counts"]["valid_company_quarters"] == 32, "ENGINEERING_CONTINUATION_FAILED")
        write_json(output / "engineering-coverage.json", {"material_class": ENGINEERING, "report": report})
    require(before == binding(args.expected_base, args.expected_head), "PROTECTED_FILE_CHANGED_DURING_TESTS")
    write_json(output / "verification.json", {"status": "PASS", "material_class": ENGINEERING,
        "real_provider_coverage_scan": "NOT_RUN_IN_PUBLIC_CI", "network_requests": 0,
        "validated_at": now(), "engineering_test_exit_code": tests.returncode,
        "existing_regression_tests": 57, "new_metadata_and_handoff_tests": 24,
        "pre_existing_total_tests": 81, "new_dispatch_wait_tests": 12, "dispatch_wait_test_exit_code": wait.returncode,
        "new_test_exit_code": metadata.returncode, "platform": sys.platform,
        "actual_base_head_isolation": before, "production_eligible": False,
        "original_eight_quarter_coverage_credit": 0, "formal_eight_quarter_acceptance": "NOT_PERFORMED"})
    print("PASS: synthetic coverage and original candidate regression; no real provider scan")


if __name__ == "__main__":
    main()

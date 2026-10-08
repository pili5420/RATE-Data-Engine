"""Exact Base/Head additive isolation and synthetic-only feature engineering CI."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.provider_financial_features import instant, within_git_checkout
from scripts.verify_eps_b1_noninterference import git, tracked_hashes, put

ADDITIONS = {
    "docs/contracts/RATE_PROVIDER_FINANCIAL_FEATURES_V1.json", "docs/RATE_PROVIDER_FINANCIAL_FEATURES_V1.md",
    "src/provider_financial_features.py", "src/provider_financial_feature_inputs.py",
    "scripts/build_provider_financial_features.py", "scripts/verify_provider_financial_features.py",
    "tests/provider_financial_features_fixture.py", "tests/test_provider_financial_features.py",
    ".github/workflows/rate_provider_financial_features_ci.yml",
}
PROVIDER_REGRESSIONS = ("tests.test_provider_eps_candidate", "tests.test_provider_eps_coverage",
    "tests.test_provider_eps_recovery", "tests.test_provider_eps_metadata", "tests.test_provider_eps_wait_semantics")


def isolation(base, head):
    require(git("rev-parse", "HEAD").decode().strip() == head, "FEATURE_EXACT_HEAD_REQUIRED")
    require(not git("status", "--porcelain", "--untracked-files=all"), "FEATURE_WORKTREE_NOT_CLEAN")
    git("merge-base", "--is-ancestor", base, head)
    changes = git("diff", "--name-status", "--no-renames", base, head).decode().splitlines()
    require(set(changes) == {"A\t" + p for p in ADDITIONS}, "FEATURE_NARROW_ADDITIVE_ALLOWLIST_VIOLATED")
    base_paths = git("ls-tree", "-r", "--name-only", base).decode().splitlines()
    hashes = tracked_hashes(base_paths)
    for p in base_paths:
        require(git("rev-parse", base + ":" + p) == git("rev-parse", head + ":" + p), "FEATURE_EXISTING_BLOB_CHANGED:" + p)
        if p.endswith(".py") and p.startswith(("src/", "scripts/")):
            tree = ast.parse((ROOT / p).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                require(not any("provider_financial_feature" in name for name in names), "FEATURE_FORMAL_REVERSE_DEPENDENCY")
            require(b"provider_financial_feature" not in (ROOT / p).read_bytes(), "FEATURE_EXISTING_DYNAMIC_DEPENDENCY")
    return {"base_sha": base, "head_sha": head, "changed_files": sorted(ADDITIONS), "protected_file_count": len(base_paths),
        "protected_hashes": hashes, "all_existing_blobs_unchanged": True, "formal_reverse_dependencies": 0}


def run_tests(output, name, modules):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    run = subprocess.run([sys.executable, "-B", "-m", "unittest", *modules, "-v"], cwd=ROOT,
        env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = run.stdout + run.stderr
    (output / (name + ".log")).write_text(log, encoding="utf-8")
    match = re.search(r"Ran (\d+) tests", log)
    result = {"modules": list(modules), "count": int(match.group(1)) if match else 0, "exit_code": run.returncode,
        "status": "PASS" if run.returncode == 0 else "FAIL", "fixtures": "SYNTHETIC_ENGINEERING_ONLY"}
    put(output, name + ".json", result)
    require(run.returncode == 0 and match, "FEATURE_ENGINEERING_TESTS_FAILED:" + name)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    require(not output.exists() and not output.is_relative_to(ROOT), "FEATURE_NEW_EXTERNAL_VERIFICATION_REQUIRED")
    require(not within_git_checkout(output), "FEATURE_VERIFICATION_IN_REPOSITORY")
    output.mkdir(parents=True)
    before = isolation(args.expected_base, args.expected_head)
    put(output, "protected-before.json", before)
    provider = run_tests(output, "existing-provider-regressions", PROVIDER_REGRESSIONS)
    official = run_tests(output, "existing-official-history-regressions", ("tests.test_cer073_fundamental_history_v2",))
    new = run_tests(output, "new-feature-and-noninterference-tests", ("tests.test_provider_financial_features",))
    after = isolation(args.expected_base, args.expected_head)
    require(before == after, "FEATURE_PROTECTED_BYTES_CHANGED_DURING_TESTS")
    put(output, "protected-after.json", after)
    result = {"status": "PASS", "base_sha": args.expected_base, "head_sha": args.expected_head, "platform": sys.platform,
        "validated_at": instant(), "existing_provider_tests": provider["count"], "existing_official_history_tests": official["count"],
        "new_feature_and_noninterference_tests": new["count"], "total_tests": provider["count"] + official["count"] + new["count"],
        "scope": "ENGINEERING_FIXTURE_NOT_REAL_1978_COMPANY_REPLAY", "real_replay": "LOCAL_ONLY_SEPARATE_REPORT",
        "source_network_requests": 0, "formal_calculate_fundamental_calls": 0, "production_mutations": 0,
        "feature_calculation_allowed": True, "decision_eligible": False, "production_eligible": False,
        "original_eight_quarter_coverage_credit": 0, "changed_files": sorted(ADDITIONS),
        "protected_file_count": before["protected_file_count"], "all_existing_blobs_and_bytes_unchanged": True,
        "formal_noninterference": "ABSENT_PRESENT_UPDATED_ACCEPTED_SENTINEL_AND_MISSING_FORMAL_EPS_GATE_NO_SCORING"}
    put(output, "VERIFICATION_PACKAGE.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

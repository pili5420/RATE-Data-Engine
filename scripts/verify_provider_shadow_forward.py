"""Exact-head additive protection; all 211 prior tests plus forward fixtures."""
import argparse
import ast
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.provider_financial_features import instant, within_git_checkout
from scripts.verify_eps_b1_noninterference import git, tracked_hashes, put
from scripts.verify_provider_financial_features import run_tests, PROVIDER_REGRESSIONS

ADDITIONS = {"docs/contracts/RATE_PROVIDER_SHADOW_FORWARD_VALIDATION_V1.json", "docs/RATE_PROVIDER_SHADOW_FORWARD_VALIDATION_V1.md",
    "src/provider_shadow_forward.py", "src/provider_shadow_forward_prices.py", "scripts/run_provider_shadow_forward.py",
    "scripts/verify_provider_shadow_forward.py", "tests/test_provider_shadow_forward.py", ".github/workflows/rate_provider_shadow_forward_ci.yml"}


def isolation(base, head):
    require(git("rev-parse", "HEAD").decode().strip() == head and not git("status", "--porcelain", "--untracked-files=all"), "FORWARD_EXACT_HEAD_CLEAN_REQUIRED")
    git("merge-base", "--is-ancestor", base, head)
    require(set(git("diff", "--name-status", "--no-renames", base, head).decode().splitlines()) == {"A\t" + p for p in ADDITIONS}, "FORWARD_ADDITIVE_ONLY_DIFF_VIOLATION")
    paths = git("ls-tree", "-r", "--name-only", base).decode().splitlines()
    for path in paths:
        require(git("rev-parse", base + ":" + path) == git("rev-parse", head + ":" + path), "FORWARD_EXISTING_BLOB_CHANGED:" + path)
        if path.endswith(".py") and path.startswith(("src/", "scripts/")):
            body = (ROOT / path).read_bytes()
            require(b"provider_shadow_forward" not in body, "FORWARD_FORMAL_REVERSE_DEPENDENCY")
            ast.parse(body.decode("utf-8-sig"))
    return {"base_sha": base, "head_sha": head, "protected_file_count": len(paths), "protected_hashes": tracked_hashes(paths), "changed_files": sorted(ADDITIONS)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    output = Path(args.output_dir).resolve()
    require(not output.exists() and not within_git_checkout(output), "FORWARD_NEW_EXTERNAL_ENGINEERING_REQUIRED")
    output.mkdir(parents=True)
    before = isolation(args.expected_base, args.expected_head)
    put(output, "protected-before.json", before)
    tests = [run_tests(output, "existing-provider-93", PROVIDER_REGRESSIONS),
        run_tests(output, "existing-official-17", ("tests.test_cer073_fundamental_history_v2",)),
        run_tests(output, "existing-features-42", ("tests.test_provider_financial_features",)),
        run_tests(output, "existing-shadow-36", ("tests.test_provider_fundamental_shadow",)),
        run_tests(output, "existing-revenue-23", ("tests.test_provider_revenue_snapshot",)),
        run_tests(output, "new-forward", ("tests.test_provider_shadow_forward",))]
    after = isolation(args.expected_base, args.expected_head)
    require(before == after and sum(t["count"] for t in tests[:-1]) == 211, "FORWARD_REGRESSION_OR_CODE_CHANGED")
    put(output, "protected-after.json", after)
    result = {"status": "PASS", "base_sha": args.expected_base, "head_sha": args.expected_head, "platform": sys.platform,
        "tests": tests, "existing_tests": 211, "new_tests": tests[-1]["count"], "total_tests": sum(t["count"] for t in tests),
        "protected_file_count": before["protected_file_count"], "protected_bytes_and_blobs_unchanged": True, "changed_files": sorted(ADDITIONS),
        "scope": "SYNTHETIC_ONLY_NOT_REAL_FORWARD_RETURN", "financial_requests": 0, "price_requests": 0, "formal_scoring_calls": 0,
        "forward_validation_allowed": True, "decision_eligible": False, "production_eligible": False, "validated_at": instant()}
    put(output, "VERIFICATION_PACKAGE.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

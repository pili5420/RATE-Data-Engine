"""Exact-head, additive-only isolation and synthetic shadow engineering checks."""
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

ADDITIONS = {
    "docs/contracts/RATE_PROVIDER_FUNDAMENTAL_SHADOW_V1.json", "docs/RATE_PROVIDER_FUNDAMENTAL_SHADOW_V1.md",
    "src/provider_fundamental_shadow.py", "src/provider_fundamental_shadow_inputs.py",
    "scripts/build_provider_fundamental_shadow.py", "scripts/verify_provider_fundamental_shadow.py",
    "tests/provider_fundamental_shadow_fixture.py", "tests/test_provider_fundamental_shadow.py",
    ".github/workflows/rate_provider_fundamental_shadow_ci.yml",
}


def isolation(base, head):
    require(git("rev-parse", "HEAD").decode().strip() == head, "SHADOW_EXACT_HEAD_REQUIRED")
    require(not git("status", "--porcelain", "--untracked-files=all"), "SHADOW_WORKTREE_NOT_CLEAN")
    git("merge-base", "--is-ancestor", base, head)
    require(set(git("diff", "--name-status", "--no-renames", base, head).decode().splitlines()) ==
        {"A\t" + p for p in ADDITIONS}, "SHADOW_ADDITIVE_ALLOWLIST_VIOLATION")
    paths = git("ls-tree", "-r", "--name-only", base).decode().splitlines()
    for path in paths:
        require(git("rev-parse", base + ":" + path) == git("rev-parse", head + ":" + path), "SHADOW_EXISTING_BLOB_CHANGED:" + path)
        if path.endswith(".py") and path.startswith(("src/", "scripts/")):
            body = (ROOT / path).read_bytes()
            tree = ast.parse(body.decode("utf-8-sig"))
            for node in ast.walk(tree):
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names] if isinstance(node, ast.Import) else []
                require(not any("provider_fundamental_shadow" in n for n in names), "SHADOW_FORMAL_REVERSE_DEPENDENCY")
            require(b"provider_fundamental_shadow" not in body, "SHADOW_EXISTING_DYNAMIC_DEPENDENCY")
    return {"base_sha": base, "head_sha": head, "changed_files": sorted(ADDITIONS),
        "protected_file_count": len(paths), "protected_hashes": tracked_hashes(paths), "existing_blobs_unchanged": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    require(not output.exists() and not within_git_checkout(output), "SHADOW_NEW_EXTERNAL_VERIFICATION_REQUIRED")
    output.mkdir(parents=True)
    before = isolation(args.expected_base, args.expected_head)
    put(output, "protected-before.json", before)
    results = [run_tests(output, "existing-provider", PROVIDER_REGRESSIONS),
        run_tests(output, "existing-official-history", ("tests.test_cer073_fundamental_history_v2",)),
        run_tests(output, "existing-features", ("tests.test_provider_financial_features",)),
        run_tests(output, "new-shadow-and-noninterference", ("tests.test_provider_fundamental_shadow",))]
    after = isolation(args.expected_base, args.expected_head)
    require(before == after, "SHADOW_EXISTING_BYTES_CHANGED_DURING_TESTS")
    put(output, "protected-after.json", after)
    result = {"status": "PASS", "base_sha": args.expected_base, "head_sha": args.expected_head,
        "platform": sys.platform, "validated_at": instant(), "tests": results,
        "total_tests": sum(r["count"] for r in results), "protected_file_count": before["protected_file_count"],
        "changed_files": sorted(ADDITIONS), "protected_bytes_and_blobs_unchanged": True,
        "scope": "SYNTHETIC_ENGINEERING_NOT_REAL_SHADOW_SCORING", "source_network_requests": 0,
        "formal_scoring_calls": 0, "decision_eligible": False, "production_eligible": False,
        "original_eight_quarter_coverage_credit": 0}
    put(output, "VERIFICATION_PACKAGE.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

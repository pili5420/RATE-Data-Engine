"""Current exact-head narrow opt-in diff, full 188 regressions and new fixtures."""
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

ADDITIONS = {"src/provider_revenue_snapshot.py", "scripts/expand_official_revenue.py",
    "scripts/verify_official_revenue_expansion.py", "tests/test_provider_revenue_snapshot.py",
    "docs/RATE_OFFICIAL_REVENUE_EXPANSION_V1.md", ".github/workflows/rate_official_revenue_expansion_ci.yml"}
MODIFIED = {"src/provider_financial_feature_inputs.py", ".github/workflows/rate_provider_financial_features_ci.yml"}
OPT_IN = ("    if binding.get(\"input_mode\") == \"OFFICIAL_REVENUE_SNAPSHOT_INPUT_V1\":\n"
    "        from .provider_revenue_snapshot import replay_snapshot_binding\n"
    "        return replay_snapshot_binding(binding)\n")


def isolation(base, head):
    require(git("rev-parse", "HEAD").decode().strip() == head and not git("status", "--porcelain", "--untracked-files=all"), "REVENUE_EXACT_HEAD_CLEAN_REQUIRED")
    git("merge-base", "--is-ancestor", base, head)
    require(set(git("diff", "--name-status", "--no-renames", base, head).decode().splitlines()) ==
        {"A\t" + p for p in ADDITIONS} | {"M\t" + p for p in MODIFIED}, "REVENUE_EXACT_NARROW_DIFF_VIOLATION")
    relative = "src/provider_financial_feature_inputs.py"
    before = git("show", base + ":" + relative).decode()
    after = (ROOT / relative).read_text(encoding="utf-8")
    require(after.count(OPT_IN) == 1 and after.replace(OPT_IN, "", 1) == before, "REVENUE_ONLY_EXPLICIT_OPT_IN_ALLOWED")
    paths = git("ls-tree", "-r", "--name-only", base).decode().splitlines()
    protected = [p for p in paths if p not in MODIFIED]
    for path in protected:
        require(git("rev-parse", base + ":" + path) == git("rev-parse", head + ":" + path), "REVENUE_PROTECTED_BLOB_CHANGED:" + path)
        if path.endswith(".py") and path.startswith(("src/", "scripts/")):
            body = (ROOT / path).read_bytes()
            for node in ast.walk(ast.parse(body.decode("utf-8-sig"))):
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names] if isinstance(node, ast.Import) else []
                require(not any("provider_revenue_snapshot" in name for name in names), "REVENUE_FORMAL_REVERSE_DEPENDENCY")
            require(b"provider_revenue_snapshot" not in body, "REVENUE_EXISTING_DYNAMIC_REVERSE_DEPENDENCY")
    return {"base_sha": base, "head_sha": head, "protected_file_count": len(protected),
        "protected_hashes": tracked_hashes(protected), "modified_file_hashes": tracked_hashes(sorted(MODIFIED)),
        "changes": sorted(ADDITIONS | MODIFIED), "legacy_reader_remainder_byte_equivalent": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    require(not output.exists() and not within_git_checkout(output), "REVENUE_NEW_EXTERNAL_VERIFICATION_REQUIRED")
    output.mkdir(parents=True)
    before = isolation(args.expected_base, args.expected_head)
    put(output, "protected-before.json", before)
    results = [run_tests(output, "existing-provider-93", PROVIDER_REGRESSIONS),
        run_tests(output, "existing-official-17", ("tests.test_cer073_fundamental_history_v2",)),
        run_tests(output, "existing-features-42", ("tests.test_provider_financial_features",)),
        run_tests(output, "existing-shadow-36", ("tests.test_provider_fundamental_shadow",)),
        run_tests(output, "new-revenue-snapshot", ("tests.test_provider_revenue_snapshot",))]
    after = isolation(args.expected_base, args.expected_head)
    require(before == after, "REVENUE_CODE_MUTATED_DURING_TESTS")
    put(output, "protected-after.json", after)
    result = {"status": "PASS", "base_sha": args.expected_base, "head_sha": args.expected_head,
        "platform": sys.platform, "validated_at": instant(), "tests": results,
        "existing_tests": sum(r["count"] for r in results[:-1]), "new_tests": results[-1]["count"],
        "total_tests": sum(r["count"] for r in results), "protected_file_count": before["protected_file_count"],
        "changed_files": sorted(ADDITIONS | MODIFIED), "protected_bytes_and_blobs_unchanged": True,
        "legacy_reader_remainder_unchanged": True, "scope": "SYNTHETIC_ONLY_NOT_REAL_REQUEST_OR_REFRESH_REPLAY",
        "financial_network_requests": 0, "formal_scoring_calls": 0, "production_eligible": False,
        "decision_eligible": False, "original_eight_quarter_coverage_credit": 0}
    put(output, "VERIFICATION_PACKAGE.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

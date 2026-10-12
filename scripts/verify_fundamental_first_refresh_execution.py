"""Exact-head J2-E verification: inherited suite plus Fundamental-only wiring tests."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_public_official_partial_valid import child, extract, git, write
from scripts.verify_provider_warmup_readiness import GROUPS as INHERITED_GROUPS
from scripts.verify_ci_applicability import network_guard

BASE = "139505a3a6c33a19b7973c7f812497046a82d667"
HISTORICAL_BASE = "29f1781e3c460ccf9a816c5b9774b00374cedfe1"
REVIEWED_HEAD = "6d185cec4e29c4d69e63e5a1432e6d5d6e38c37b"
REVIEWED_BLOBS = {
    "src/fundamental_first_refresh_execution.py": "3434a7c4eb431903ec0163efce79755eba31368a",
    "scripts/run_fundamental_first_refresh_execution.py": "117993b2ca447d526c02c299a1941590d5ce11b4",
    "tests/test_fundamental_first_refresh_execution.py": "52ce50f1e17abc7facb55049a1e085ed1c2a010d",
    "docs/contracts/RATE_FUNDAMENTAL_FIRST_REFRESH_EXECUTION_V1.json": "1c32fad1791082c55017e3fac6fc371fb47e57db",
}
NEW_COUNT = 51
ALLOWED = {
    "src/fundamental_first_refresh_execution.py",
    "scripts/run_fundamental_first_refresh_execution.py",
    "scripts/verify_fundamental_first_refresh_execution.py",
    "tests/test_fundamental_first_refresh_execution.py",
    "docs/contracts/RATE_FUNDAMENTAL_FIRST_REFRESH_EXECUTION_V1.json",
    "docs/RATE_FUNDAMENTAL_FIRST_REFRESH_EXECUTION_V1.md",
    ".github/workflows/rate_fundamental_first_refresh_execution_ci.yml",
}
GROUPS = {
    **INHERITED_GROUPS,
    "fundamental_first_refresh_execution_new": (["test_fundamental_first_refresh_execution"], NEW_COUNT),
}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(network_guard)
        return child(Path(sys.argv[2]), sys.argv[3:])

    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head or git("merge-base", BASE, "HEAD") != BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    changed = set(git("diff", "--name-status", "--no-renames", BASE, args.expected_head).splitlines())
    if changed != {"A\t" + path for path in ALLOWED} or git("status", "--porcelain"):
        raise ValueError("ADDITIVE_SCOPE_OR_WORKTREE_CHANGED")

    def tree(ref):
        return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2]
                for line in git("ls-tree", "-r", ref).splitlines()}

    old, new = tree(BASE), tree(args.expected_head)
    if any(new.get(path) != blob for path, blob in old.items()):
        raise ValueError("PROTECTED_EXISTING_BLOB_CHANGED")
    if any(new.get(path) != blob for path, blob in REVIEWED_BLOBS.items()):
        raise ValueError("REVIEWED_EXECUTION_SEMANTICS_OR_ASSERTIONS_CHANGED")
    if args.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    args.output_dir.mkdir(parents=True)

    results = {}
    with tempfile.TemporaryDirectory(prefix="j2e-", dir=ROOT.parent.resolve()) as directory:
        mirror = Path(directory) / "head"
        extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temp = Path(directory) / "tmp"
        temp.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
               "TEMP": str(temp.resolve()), "TMP": str(temp.resolve())}
        for name, (modules, count) in GROUPS.items():
            output = args.output_dir.resolve() / (name + ".json")
            run = subprocess.run(
                [sys.executable, "-B", str(mirror / "scripts/verify_fundamental_first_refresh_execution.py"),
                 "--test-child", str(output), *modules],
                cwd=mirror, env=env, capture_output=True, text=True, encoding="utf-8")
            (args.output_dir / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            result = json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)

    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"]
                 for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != args.expected_head:
        raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    inherited = sum(count for name, (_, count) in GROUPS.items() if name != "fundamental_first_refresh_execution_new")
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {
        "base_sha": BASE,
        "head_sha": args.expected_head,
        "historical_engineering_base": HISTORICAL_BASE,
        "reviewed_head": REVIEWED_HEAD,
        "unchanged_reviewed_blobs": REVIEWED_BLOBS,
        "current_main_inherited_groups": {name: count for name, (_, count) in INHERITED_GROUPS.items()},
        "changed_files": sorted(ALLOWED),
        "results": results,
        "inherited_tests": inherited,
        "new_tests": NEW_COUNT,
        "total_tests": inherited + NEW_COUNT,
        "protected_existing_blobs_unchanged": len(old),
        "financial_requests": 0,
        "production_publications": 0,
        "ranking_executions": 0,
        "state_portfolio_ledger_mutations": 0,
        "tests_skipped": sum(len(r["skipped"]) for r in results.values()),
        "assertions_relaxed": 0,
        "failure_whitelists": 0,
        "material_scope": "SYNTHETIC_ENGINEERING_ONLY_NOT_EXECUTION_AUTHORIZATION",
        "first_refresh_executions": 0,
        "first_refresh_authorized": False,
        "status": "PASS" if passed else "BLOCKED",
    })
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

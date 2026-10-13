"""Exact-head additive isolation, inherited gates and synthetic component tests."""
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
from scripts.verify_fundamental_ranking_consumer import GROUPS as INHERITED, clean_consumer_checkout, tree
from scripts.verify_ci_applicability import network_guard

BASE = "f951186df3ffe6eeeedb19500a1cd4966433fc99"
NEW_COUNT = 36
ALLOWED = {"src/full_market_component_evidence.py", "tests/test_full_market_component_evidence.py",
           "scripts/build_full_market_component_evidence.py", "scripts/verify_full_market_component_evidence.py",
           "docs/contracts/RATE_FULL_MARKET_COMPONENT_EVIDENCE_V1.json",
           "docs/RATE_FULL_MARKET_COMPONENT_EVIDENCE_V1.md",
           ".github/workflows/rate_full_market_component_evidence_ci.yml"}
GROUPS = {**INHERITED, "components_new": (["test_full_market_component_evidence"], NEW_COUNT)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(network_guard)
        return child(Path(sys.argv[2]), sys.argv[3:])
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    if args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head or git("merge-base", BASE, args.expected_head) != BASE or git("status", "--porcelain"):
        raise ValueError("COMPONENT_EXACT_BASE_HEAD_OR_WORKTREE")
    if set(git("diff", "--name-status", "--no-renames", BASE, args.expected_head).splitlines()) != {"A\t" + path for path in ALLOWED}:
        raise ValueError("COMPONENT_SEVEN_ADDITIVE_FILES_REQUIRED")
    before, after = tree(BASE), tree(args.expected_head)
    if any(after.get(path) != blob for path, blob in before.items()):
        raise ValueError("COMPONENT_EXISTING_MAIN_BLOB_CHANGED")
    if args.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "PROTECTED_MAIN_BLOBS.json", before)
    results = {}
    with tempfile.TemporaryDirectory(prefix="component-ci-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"
        extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temporary = Path(directory) / "tmp"
        temporary.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temporary), "TMP": str(temporary)}
        for name, (modules, count) in GROUPS.items():
            repo = mirror
            if name == "consumer_new":
                repo = Path(directory) / "consumer"
                clean_consumer_checkout(args.expected_head, repo)
            output = args.output_dir.resolve() / (name + ".json")
            run = subprocess.run([sys.executable, "-B", str(repo / "scripts/verify_full_market_component_evidence.py"),
                "--test-child", str(output), *modules], cwd=repo, env=env, capture_output=True)
            (args.output_dir / (name + ".log")).write_bytes(run.stdout + run.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != args.expected_head:
        raise ValueError("COMPONENT_CHECKOUT_CHANGED")
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {"status": "PASS" if passed else "BLOCKED",
        "base_sha": BASE, "head_sha": args.expected_head, "changed_files": sorted(ALLOWED),
        "existing_tests": sum(n for _, n in INHERITED.values()), "new_tests": NEW_COUNT,
        "total_tests": sum(n for _, n in GROUPS.values()), "results": results,
        "existing_main_blobs_preserved": len(before), "tests_skipped": sum(len(r["skipped"]) for r in results.values()),
        "assertions_relaxed": 0, "failure_whitelists": 0, "material_scope": "SYNTHETIC_ONLY_NOT_REAL_PRODUCTION_REPLAY",
        "financial_requests": 0, "ranking_executions": 0, "production_publications": 0,
        "state_portfolio_ledger_scheduler_mutations": 0, "intraday": "BLOCKED_EXTERNAL"})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

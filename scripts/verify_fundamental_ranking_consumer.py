"""Exact-head additive isolation and all current-main inherited engineering tests."""
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
from scripts.verify_fundamental_first_refresh_execution import GROUPS as INHERITED
from scripts.verify_ci_applicability import network_guard

BASE = "e5953fa3ff7123a28d85ec6c4f361c25da9bc4ab"
NEW_COUNT = 68
ALLOWED = {"src/fundamental_ranking_consumer.py", "tests/test_fundamental_ranking_consumer.py",
           "scripts/run_fundamental_ranking_consumer.py", "scripts/verify_fundamental_ranking_consumer.py",
           "docs/contracts/RATE_FUNDAMENTAL_RANKING_CONSUMER_V1.json",
           "docs/RATE_FUNDAMENTAL_RANKING_CONSUMER_V1.md",
           ".github/workflows/rate_fundamental_ranking_consumer_ci.yml"}
GROUPS = {**INHERITED, "consumer_new": (["test_fundamental_ranking_consumer"], NEW_COUNT)}


def tree(ref):
    return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2]
            for line in git("ls-tree", "-r", ref).splitlines()}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(network_guard)
        return child(Path(sys.argv[2]), sys.argv[3:])
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if (args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head
            or git("merge-base", BASE, args.expected_head) != BASE or git("status", "--porcelain")):
        raise ValueError("CONSUMER_EXACT_BASE_HEAD_OR_WORKTREE")
    if set(git("diff", "--name-status", "--no-renames", BASE, args.expected_head).splitlines()) != {"A\t" + p for p in ALLOWED}:
        raise ValueError("CONSUMER_SEVEN_ADDITIVE_FILES_REQUIRED")
    before, after = tree(BASE), tree(args.expected_head)
    if any(after.get(path) != blob for path, blob in before.items()):
        raise ValueError("GOVERNANCE_ESCALATION_REQUIRED_MAIN_BLOB_CHANGED")
    if args.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "PROTECTED_MAIN_BLOBS.json", before)
    results = {}
    with tempfile.TemporaryDirectory(prefix="consumer-ci-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"
        extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temporary = Path(directory) / "tmp"
        temporary.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
               "TEMP": str(temporary), "TMP": str(temporary)}
        for name, (modules, count) in GROUPS.items():
            output = args.output_dir.resolve() / (name + ".json")
            run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_fundamental_ranking_consumer.py"),
                "--test-child", str(output), *modules], cwd=mirror, env=env, capture_output=True)
            (args.output_dir / (name + ".log")).write_bytes(run.stdout + run.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"]
                 for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != args.expected_head:
        raise ValueError("CONSUMER_HEAD_OR_WORKTREE_CHANGED")
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {
        "status": "PASS" if passed else "BLOCKED", "base_sha": BASE, "head_sha": args.expected_head,
        "changed_files": sorted(ALLOWED), "existing_tests": sum(n for _, n in INHERITED.values()),
        "new_tests": NEW_COUNT, "total_tests": sum(n for _, n in GROUPS.values()), "results": results,
        "existing_main_blobs_preserved": len(before), "tests_skipped": sum(len(r["skipped"]) for r in results.values()),
        "assertions_relaxed": 0, "failure_whitelists": 0,
        "material_scope": "SYNTHETIC_ONLY_NOT_REAL_PRODUCTION_REPLAY", "real_financial_requests": 0,
        "first_refresh_executions": 0, "ranking_executions": 0, "production_publications": 0,
        "ranking_authorized": False, "decision_eligible": False})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

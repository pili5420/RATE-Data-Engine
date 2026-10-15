"""Exact-head sidecar scope, all inherited regression groups and synthetic tests."""
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
from scripts.verify_history_chunked_acquisition import GROUPS as INHERITED
from scripts.verify_fundamental_ranking_consumer import clean_consumer_checkout, tree
from scripts.verify_ci_applicability import network_guard

BASE = "fbdfbfcf0a003cd6de49911bc0a784275a32031c"
ADDED = {"src/history_acceptance_sidecar.py", "scripts/run_history_acceptance_sidecar.py",
         "scripts/verify_history_acceptance_sidecar.py", "tests/test_history_acceptance_sidecar.py",
         "docs/contracts/RATE_HISTORY_ACCEPTANCE_SIDECAR_V1.json",
         "docs/RATE_HISTORY_ACCEPTANCE_SIDECAR_V1.md", ".github/workflows/rate_history_acceptance_sidecar_ci.yml"}
NEW_COUNT = 71
GROUPS = {**INHERITED, "acceptance_sidecar_new": (["test_history_acceptance_sidecar"], NEW_COUNT)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(network_guard)
        return child(Path(sys.argv[2]), sys.argv[3:])
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if (a.expected_base != BASE or git("rev-parse", "HEAD") != a.expected_head
            or git("merge-base", BASE, a.expected_head) != BASE or git("status", "--porcelain")):
        raise ValueError("SIDECAR_EXACT_BASE_HEAD_OR_WORKTREE_MISMATCH")
    changed = set(git("diff", "--name-status", "--no-renames", BASE, a.expected_head).splitlines())
    if changed != {"A\t" + path for path in ADDED}:
        raise ValueError("SIDECAR_SEVEN_ADDITIVE_FILES_REQUIRED")
    old, new = tree(BASE), tree(a.expected_head)
    if any(new.get(path) != blob for path, blob in old.items()):
        raise ValueError("SIDECAR_PROTECTED_MAIN_BLOB_CHANGED")
    if a.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    a.output_dir.mkdir(parents=True)
    write(a.output_dir / "PROTECTED_MAIN_BLOBS.json", old)
    results = {}
    with tempfile.TemporaryDirectory(prefix="sidecar-ci-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"
        extract(a.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temp = Path(directory) / "tmp"; temp.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
               "TEMP": str(temp), "TMP": str(temp)}
        for name, (modules, count) in GROUPS.items():
            repo = mirror
            if name == "consumer_new":
                repo = Path(directory) / "consumer"
                clean_consumer_checkout(a.expected_head, repo)
            report = a.output_dir.resolve() / (name + ".json")
            run = subprocess.run([sys.executable, "-B", str(repo / "scripts/verify_history_acceptance_sidecar.py"),
                "--test-child", str(report), *modules], cwd=repo, env=env, capture_output=True)
            (a.output_dir / (name + ".log")).write_bytes(run.stdout + run.stderr)
            result = json.loads(report.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != a.expected_head:
        raise ValueError("SIDECAR_EXECUTION_BINDING_CHANGED")
    write(a.output_dir / "VERIFICATION_PACKAGE.json", {"status": "PASS" if passed else "BLOCKED",
        "base_sha": BASE, "head_sha": a.expected_head, "changed_files": sorted(ADDED),
        "existing_tests": sum(count for _, count in INHERITED.values()), "new_tests": NEW_COUNT,
        "total_tests": sum(count for _, count in GROUPS.values()), "results": results,
        "protected_existing_blobs_preserved": len(old), "existing_runtime_files_changed": [],
        "tests_skipped": sum(len(r["skipped"]) for r in results.values()), "assertions_relaxed": 0,
        "failure_whitelists": 0, "material_scope": "SYNTHETIC_ONLY", "official_market_data_requests": 0,
        "formal_authorizations_created": 0, "authorization_claims": 0, "live_executions": 0,
        "formal_acceptance_ledger_written": False, "production_publications": 0, "ranking_executions": 0})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

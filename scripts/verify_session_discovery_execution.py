"""Exact-head additive isolation and synthetic-only current-main regression CI."""
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
from scripts.verify_full_market_component_evidence import GROUPS as INHERITED
from scripts.verify_fundamental_ranking_consumer import clean_consumer_checkout, tree
from scripts.verify_ci_applicability import network_guard

BASE = "6a2108c6ce326bf90806ab0cdd7ab84e7131a643"
NEW_COUNT = 82
ALLOWED = {"src/session_discovery_execution.py", "src/session_discovery_transport.py",
    "scripts/run_session_discovery_execution.py", "scripts/verify_session_discovery_execution.py",
    "tests/test_session_discovery_execution.py", "docs/contracts/RATE_SESSION_DISCOVERY_EXECUTION_V1.json",
    "docs/RATE_SESSION_DISCOVERY_EXECUTION_V1.md", ".github/workflows/rate_session_discovery_execution_ci.yml"}
GROUPS = {**INHERITED, "discovery_new": (["test_session_discovery_execution"], NEW_COUNT)}


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
        raise ValueError("DISCOVERY_EXACT_BASE_HEAD_OR_WORKTREE")
    if set(git("diff", "--name-status", "--no-renames", BASE, a.expected_head).splitlines()) != {"A\t" + path for path in ALLOWED}:
        raise ValueError("DISCOVERY_EIGHT_ADDITIVE_FILES_REQUIRED")
    before, after = tree(BASE), tree(a.expected_head)
    if any(after.get(path) != blob for path, blob in before.items()):
        raise ValueError("GOVERNANCE_ESCALATION_REQUIRED_MAIN_BLOB_CHANGED")
    if a.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    a.output_dir.mkdir(parents=True)
    write(a.output_dir / "PROTECTED_MAIN_BLOBS.json", before)
    results = {}
    with tempfile.TemporaryDirectory(prefix="discovery-ci-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"
        extract(a.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temp = Path(directory) / "tmp"
        temp.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temp), "TMP": str(temp)}
        for name, (modules, count) in GROUPS.items():
            repo = mirror
            if name == "consumer_new":
                repo = Path(directory) / "consumer"
                clean_consumer_checkout(a.expected_head, repo)
            report = a.output_dir.resolve() / (name + ".json")
            run = subprocess.run([sys.executable, "-B", str(repo / "scripts/verify_session_discovery_execution.py"),
                "--test-child", str(report), *modules], cwd=repo, env=env, capture_output=True)
            (a.output_dir / (name + ".log")).write_bytes(run.stdout + run.stderr)
            result = json.loads(report.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != a.expected_head:
        raise ValueError("DISCOVERY_CHECKOUT_CHANGED")
    write(a.output_dir / "VERIFICATION_PACKAGE.json", {
        "status": "PASS" if passed else "BLOCKED", "base_sha": BASE, "head_sha": a.expected_head,
        "changed_files": sorted(ALLOWED), "existing_tests": sum(n for _, n in INHERITED.values()),
        "new_tests": NEW_COUNT, "total_tests": sum(n for _, n in GROUPS.values()), "results": results,
        "existing_main_blobs_preserved": len(before), "tests_skipped": sum(len(r["skipped"]) for r in results.values()),
        "assertions_relaxed": 0, "failure_whitelists": 0, "material_scope": "SYNTHETIC_ONLY",
        "real_discovery_requests": 0, "financial_requests": 0, "ranking_executions": 0,
        "production_publications": 0, "state_portfolio_ledger_scheduler_mutations": 0,
        "intraday": "BLOCKED_EXTERNAL", "historical_pit": "UNPROVEN"})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

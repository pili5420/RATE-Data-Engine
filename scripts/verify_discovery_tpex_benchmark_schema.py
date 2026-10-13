"""Exact-head one-alias repair, immutable owners and synthetic-only regression CI."""
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
from scripts.verify_discovery_twse_binding_fix import GROUPS as INHERITED
from scripts.verify_fundamental_ranking_consumer import clean_consumer_checkout, tree
from scripts.verify_ci_applicability import network_guard

BASE = "4cc943695ebad2cb6f94dacb60e94312d04e2547"
NEW_COUNT = 24
EXECUTOR = "src/session_discovery_execution.py"
MODIFIED = {EXECUTOR, ".github/workflows/rate_session_discovery_execution_ci.yml"}
ADDED = {"tests/test_discovery_tpex_benchmark_schema.py", "scripts/verify_discovery_tpex_benchmark_schema.py",
         "docs/RATE_DISCOVERY_TPEX_BENCHMARK_SCHEMA_DEFECT_001.md"}
GROUPS = {**INHERITED, "tpex_benchmark_fix_new": (["test_discovery_tpex_benchmark_schema"], NEW_COUNT)}


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
        raise ValueError("TPEX_DISCOVERY_EXACT_BASE_HEAD_OR_WORKTREE")
    expected = {"M\t" + path for path in MODIFIED} | {"A\t" + path for path in ADDED}
    if set(git("diff", "--name-status", "--no-renames", BASE, a.expected_head).splitlines()) != expected:
        raise ValueError("TPEX_DISCOVERY_FIVE_FILE_REPAIR_SCOPE_REQUIRED")
    before, after = tree(BASE), tree(a.expected_head)
    protected = {path: blob for path, blob in before.items() if path not in MODIFIED}
    if any(after.get(path) != blob for path, blob in protected.items()):
        raise ValueError("GOVERNANCE_ESCALATION_REQUIRED_MAIN_BLOB_CHANGED")
    old = subprocess.check_output(["git", "show", BASE + ":" + EXECUTOR], cwd=ROOT)
    new = subprocess.check_output(["git", "show", a.expected_head + ":" + EXECUTOR], cwd=ROOT)
    aliases = '("ClosingIndex", "收市", "收盤指數", "收盤價", "close")'.encode("utf-8")
    replacement = '("ClosingIndex", "收市", "收盤指數", "收盤價", "close", "Close")'.encode("utf-8")
    if old.count(aliases) != 1 or new != old.replace(aliases, replacement, 1):
        raise ValueError("TPEX_DISCOVERY_ONLY_EXACT_CLOSE_ALIAS_ADDITION_ALLOWED")
    if a.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    a.output_dir.mkdir(parents=True)
    write(a.output_dir / "PROTECTED_MAIN_BLOBS.json", protected)
    results = {}
    with tempfile.TemporaryDirectory(prefix="tpex-discovery-ci-", dir=ROOT.parent) as directory:
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
            run = subprocess.run([sys.executable, "-B", str(repo / "scripts/verify_discovery_tpex_benchmark_schema.py"),
                "--test-child", str(report), *modules], cwd=repo, env=env, capture_output=True)
            (a.output_dir / (name + ".log")).write_bytes(run.stdout + run.stderr)
            result = json.loads(report.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != a.expected_head:
        raise ValueError("TPEX_DISCOVERY_CHECKOUT_CHANGED")
    write(a.output_dir / "VERIFICATION_PACKAGE.json", {
        "status": "PASS" if passed else "BLOCKED", "base_sha": BASE, "head_sha": a.expected_head,
        "changed_files": sorted(MODIFIED | ADDED), "existing_tests": sum(n for _, n in INHERITED.values()),
        "new_tests": NEW_COUNT, "total_tests": sum(n for _, n in GROUPS.values()), "results": results,
        "existing_main_blobs_preserved": len(protected), "tests_skipped": sum(len(r["skipped"]) for r in results.values()),
        "assertions_relaxed": 0, "failure_whitelists": 0, "material_scope": "SYNTHETIC_ONLY",
        "exact_parser_delta": "ADD_CLOSE_TO_TPEX_BENCHMARK_ALIAS_TUPLE_ONLY",
        "defect_id": "RATE-MD-DISCOVERY-TPEX-BENCHMARK-SCHEMA-001",
        "real_external_data_requests": 0, "real_discovery_requests": 0, "financial_requests": 0,
        "ranking_executions": 0, "production_publications": 0,
        "state_portfolio_ledger_scheduler_mutations": 0, "authorization_reused": False,
        "fallback_allowed": False, "intraday": "BLOCKED_EXTERNAL", "historical_pit": "UNPROVEN"})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

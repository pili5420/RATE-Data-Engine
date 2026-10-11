"""Exact-head additive verification; inherited gates retained, synthetic only."""
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
from scripts.verify_ci_applicability import CURRENT_MAIN_GROUPS, GOVERNANCE_TEST_COUNT
from src.prospective_acquisition_recovery import offline_network_guard

BASE = "dbd0983caf883fa9a39eb187fb3d01f192ecd61e"
NEW_COUNT = 55
CER078_DIAGNOSTIC_COUNT = 14
ALLOWED = {"src/first_refresh_readiness.py", "scripts/run_first_refresh_readiness.py",
    "scripts/verify_first_refresh_readiness.py", "tests/test_first_refresh_readiness.py",
    "docs/contracts/RATE_FIRST_REFRESH_READINESS_V1.json", "docs/RATE_FIRST_REFRESH_READINESS_V1.md",
    ".github/workflows/rate_first_refresh_readiness_ci.yml"}
GROUPS = {**CURRENT_MAIN_GROUPS,
    "ci_applicability_inherited": (["test_ci_applicability"], GOVERNANCE_TEST_COUNT),
    "cer078_diagnostics_inherited": (["test_cer078_native_diagnostics"], CER078_DIAGNOSTIC_COUNT),
    "first_refresh_readiness_new": (["test_first_refresh_readiness"], NEW_COUNT)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        def synthetic_guard(event, args):
            if event == "urllib.Request" and args and str(args[0]).startswith("file://"):
                return
            offline_network_guard(event, args)
        sys.addaudithook(synthetic_guard)
        return child(Path(sys.argv[2]), sys.argv[3:])
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base", required=True); parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head or git("merge-base", BASE, "HEAD") != BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    if set(git("diff", "--name-status", "--no-renames", BASE, args.expected_head).splitlines()) != {"A\t" + p for p in ALLOWED} or git("status", "--porcelain"):
        raise ValueError("ADDITIVE_SCOPE_OR_WORKTREE_CHANGED")
    def tree(ref):
        return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2] for line in git("ls-tree", "-r", ref).splitlines()}
    old, new = tree(BASE), tree(args.expected_head)
    if any(new.get(path) != blob for path, blob in old.items()):
        raise ValueError("PROTECTED_EXISTING_BLOB_CHANGED")
    if args.output_dir.exists(): raise ValueError("OUTPUT_MUST_BE_NEW")
    args.output_dir.mkdir(parents=True)
    results = {}
    with tempfile.TemporaryDirectory(prefix="j-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"; extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temp = Path(directory) / "tmp"; temp.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temp), "TMP": str(temp)}
        for name, (modules, count) in GROUPS.items():
            output = args.output_dir.resolve() / (name + ".json")
            run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_first_refresh_readiness.py"),
                "--test-child", str(output), *modules], cwd=mirror, capture_output=True, text=True, encoding="utf-8", env=env)
            write(args.output_dir / (name + "-execution.json"), {"exit_code": run.returncode})
            (args.output_dir / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            result = json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != args.expected_head:
        raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {"base_sha": BASE, "head_sha": args.expected_head,
        "changed_files": sorted(ALLOWED), "results": results,
        "existing_tests": sum(c for name, (_, c) in GROUPS.items() if name != "first_refresh_readiness_new"),
        "new_tests": NEW_COUNT, "protected_existing_blobs_unchanged": len(old), "real_financial_requests": 0,
        "first_refresh_execution": 0, "production_mutations": 0, "production_eligible": False,
        "validation_status": "PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())

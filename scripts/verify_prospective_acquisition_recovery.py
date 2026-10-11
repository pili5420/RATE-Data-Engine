"""Exact-head additive-only recovery tests; public evidence is synthetic only."""
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
from scripts.verify_prospective_provider_activation import GROUPS as PRIOR_GROUPS
from src.prospective_acquisition_recovery import offline_network_guard

BASE = "30329eac593d49b64a01a241fa5da4ecec41ebad"
NEW_COUNT = 27
ALLOWED = {"src/prospective_acquisition_recovery.py", "scripts/run_prospective_acquisition_recovery.py",
    "scripts/verify_prospective_acquisition_recovery.py", "tests/test_prospective_acquisition_recovery.py",
    "docs/contracts/RATE_PROSPECTIVE_KNOWN_FAILURE_RECOVERY_V1.json",
    "docs/RATE_PROSPECTIVE_KNOWN_FAILURE_RECOVERY_V1.md",
    ".github/workflows/rate_prospective_acquisition_recovery_ci.yml"}
GROUPS = {**PRIOR_GROUPS, "known_failure_recovery_new": (["test_prospective_acquisition_recovery"], NEW_COUNT)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        def synthetic_guard(event, args):
            # Legacy fixtures use urllib's local file reader, never a live endpoint.
            if event == "urllib.Request" and args and str(args[0]).startswith("file://"):
                return
            offline_network_guard(event, args)
        sys.addaudithook(synthetic_guard)
        return child(Path(sys.argv[2]), sys.argv[3:])
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True); p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
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
    with tempfile.TemporaryDirectory(prefix="kr-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"; extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temp = Path(directory) / "tmp"; temp.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE":"1", "PYTHONIOENCODING":"utf-8", "TEMP":str(temp), "TMP":str(temp)}
        for name, (modules, count) in GROUPS.items():
            output = args.output_dir.resolve() / (name + ".json")
            run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_prospective_acquisition_recovery.py"), "--test-child", str(output), *modules],
                cwd=mirror, capture_output=True, text=True, encoding="utf-8", env=env)
            write(args.output_dir / (name + "-execution.json"), {"exit_code":run.returncode})
            (args.output_dir / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            result = json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group":name,"tests":result["tests_run"],"pass":result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != args.expected_head:
        raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {"base_sha":BASE,"head_sha":args.expected_head,
        "changed_files":sorted(ALLOWED),"results":results,"existing_tests":sum(c for _,c in PRIOR_GROUPS.values()),
        "new_tests":NEW_COUNT,"protected_existing_blobs_unchanged":len(old),"real_financial_requests":0,
        "first_refresh_execution":0,"production_mutations":0,"production_eligible":False,
        "validation_status":"PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())

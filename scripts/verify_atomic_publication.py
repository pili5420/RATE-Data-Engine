"""Exact-head narrow-scope verification; synthetic only, all inherited gates."""
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
from scripts.verify_prospective_acquisition_recovery import GROUPS as PRIOR_GROUPS
from src.prospective_acquisition_recovery import offline_network_guard
from scripts.verify_ci_applicability import GOVERNANCE_FILES, GOVERNANCE_TEST_COUNT, WORKFLOW

BASE = "66d52f73be78c6116420ac556668c7c158ca768d"
OWNER = "scripts/publish_production_source_bundle_latest.py"
NEW = {"src/production_refresh_commit.py", "scripts/read_production_refresh.py", "scripts/verify_atomic_publication.py",
       "tests/test_atomic_refresh_publication.py", "docs/contracts/RATE_ATOMIC_PUBLICATION_OWNER_V1.json",
       "docs/RATE_ATOMIC_PUBLICATION_OWNER_V1.md", ".github/workflows/rate_atomic_publication_ci.yml"}
NEW_COUNT = 29


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        def guard(event, args):
            if event == "urllib.Request" and args and str(args[0]).startswith("file://"): return
            offline_network_guard(event, args)
        sys.addaudithook(guard)
        return child(Path(sys.argv[2]), sys.argv[3:])
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True); p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True); a = p.parse_args()
    if a.expected_base != BASE or git("rev-parse", "HEAD") != a.expected_head or git("merge-base", BASE, "HEAD") != BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    expected = {"M\t" + OWNER, "M\t" + WORKFLOW} | {"A\t" + name for name in NEW | GOVERNANCE_FILES}
    if set(git("diff", "--name-status", "--no-renames", BASE, a.expected_head).splitlines()) != expected or git("status", "--porcelain"):
        raise ValueError("SCOPE_OR_WORKTREE_CHANGED")
    def tree(ref):
        return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2] for line in git("ls-tree", "-r", ref).splitlines()}
    old, new = tree(BASE), tree(a.expected_head)
    if any(new.get(path) != blob for path, blob in old.items() if path not in {OWNER, WORKFLOW}):
        raise ValueError("PROTECTED_EXISTING_BLOB_CHANGED")
    if a.output_dir.exists(): raise ValueError("OUTPUT_MUST_BE_NEW")
    a.output_dir.mkdir(parents=True); results = {}
    groups = {**PRIOR_GROUPS, "atomic_publication_new": (["test_atomic_refresh_publication"], NEW_COUNT),
              "ci_applicability_new": (["test_ci_applicability"], GOVERNANCE_TEST_COUNT)}
    with tempfile.TemporaryDirectory(prefix="ja-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "h"; extract(a.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temp = Path(directory) / "t"; temp.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temp), "TMP": str(temp)}
        for name, (modules, count) in groups.items():
            output = a.output_dir.resolve() / (name + ".json")
            run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_atomic_publication.py"),
                "--test-child", str(output), *modules], cwd=mirror, capture_output=True, env=env)
            (a.output_dir / (name + ".log")).write_bytes(run.stdout + run.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != a.expected_head: raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(a.output_dir / "VERIFICATION_PACKAGE.json", {"base_sha": BASE, "head_sha": a.expected_head,
        "changed_files": sorted(NEW | GOVERNANCE_FILES | {OWNER, WORKFLOW}), "results": results, "existing_tests": sum(c for _, c in PRIOR_GROUPS.values()),
        "new_tests": NEW_COUNT, "governance_tests": GOVERNANCE_TEST_COUNT,
        "protected_existing_blobs_unchanged": len(old) - 2,
        "real_financial_requests": 0, "first_refresh_execution": 0, "production_mutations": 0,
        "validation_status": "PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())

"""Additive exact-head diagnostics and unchanged regressions; not root-cause PASS."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_public_official_partial_valid import extract, git, write
from scripts.verify_prospective_acquisition_recovery import GROUPS as PRIOR_GROUPS

BASE = "66d52f73be78c6116420ac556668c7c158ca768d"
ALLOWED = {"src/cer078_native_diagnostics.py", "scripts/run_cer078_native_diagnostics.py",
    "scripts/verify_cer078_native_qualification.py", "tests/test_cer078_native_diagnostics.py",
    "docs/contracts/RATE_CER078_NATIVE_QUALIFICATION_V1.json", "docs/RATE_CER078_NATIVE_QUALIFICATION_V1.md",
    ".github/workflows/rate_cer078_native_qualification_ci.yml"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True); p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True); a = p.parse_args()
    if a.expected_base != BASE or git("rev-parse", "HEAD") != a.expected_head or git("merge-base", BASE, "HEAD") != BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    if set(git("diff", "--name-status", "--no-renames", BASE, a.expected_head).splitlines()) != {"A\t" + name for name in ALLOWED} or git("status", "--porcelain"):
        raise ValueError("SCOPE_OR_WORKTREE_CHANGED")
    def tree(ref):
        return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2] for line in git("ls-tree", "-r", ref).splitlines()}
    old, new = tree(BASE), tree(a.expected_head)
    if any(new.get(path) != blob for path, blob in old.items()): raise ValueError("PROTECTED_EXISTING_BLOB_CHANGED")
    if a.output_dir.exists(): raise ValueError("OUTPUT_MUST_BE_NEW")
    a.output_dir.mkdir(parents=True); results = {}
    groups = {**PRIOR_GROUPS, "diagnostics_new": (["test_cer078_native_diagnostics"], 4)}
    with tempfile.TemporaryDirectory(prefix="jb-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "h"; extract(a.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temp = Path(directory) / "t"; temp.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temp), "TMP": str(temp)}
        for name, (modules, count) in groups.items():
            output = a.output_dir.resolve() / (name + ".json")
            run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/run_cer078_native_diagnostics.py"),
                "--output", str(output), *["tests." + m for m in modules]], cwd=mirror, capture_output=True, env=env)
            (a.output_dir / (name + ".log")).write_bytes(run.stdout + run.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != a.expected_head: raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(a.output_dir / "VERIFICATION_PACKAGE.json", {"base_sha": BASE, "head_sha": a.expected_head,
        "changed_files": sorted(ALLOWED), "results": results, "existing_tests": sum(c for _, c in PRIOR_GROUPS.values()),
        "new_tests": 4, "protected_existing_blobs_unchanged": len(old), "real_financial_requests": 0,
        "first_refresh_execution": 0, "production_mutations": 0, "qualification_status": "BLOCKED",
        "root_cause": "UNRESOLVED", "engineering_validation_status": "PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__ == "__main__": raise SystemExit(main())

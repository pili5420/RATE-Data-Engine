"""Exact-head Phase I tests in a disposable mirror; public synthetic fixtures only."""
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
from scripts.verify_warmup_missingness import GROUPS as EXISTING
from scripts.verify_ci_applicability import network_guard

BASE = "bbafad151900e5719c829a94e66cdc4259ba701b"
REVIEWED_HEAD = "26f8218cc7c62612d208192bdb6409548104a33d"
REVIEWED_BLOBS = {
    "scripts/provider_warmup_readiness.py": "ca20d982a34de73e958a3d4440d83f1eb2f89a46",
    "scripts/run_provider_warmup_readiness.py": "a5981e1cab8564e1f8055f6ad9c1f3cb1c6af3b1",
    "tests/test_provider_warmup_readiness.py": "1b95d5462e3de0d931ec62b160fd4b7f4382d5c3",
    "docs/contracts/RATE_PROVIDER_WARMUP_READINESS_V1.json": "ede8723627c4bacdb94a119b877c99a2b24946d8",
}
ALLOWED = {"scripts/provider_warmup_readiness.py", "scripts/run_provider_warmup_readiness.py",
    "scripts/verify_provider_warmup_readiness.py", "tests/test_provider_warmup_readiness.py",
    "docs/RATE_PROVIDER_WARMUP_READINESS_V1.md", "docs/contracts/RATE_PROVIDER_WARMUP_READINESS_V1.json",
    ".github/workflows/rate_provider_warmup_readiness_ci.yml"}
GROUPS = {**EXISTING, "phase_i_new": (["test_provider_warmup_readiness"], 47)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(network_guard)
        return child(Path(sys.argv[2]), sys.argv[3:])
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    if args.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    if args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head or git("merge-base", BASE, args.expected_head) != BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    if git("status", "--porcelain") or set(git("diff", "--name-status", "--no-renames", BASE, args.expected_head).splitlines()) != {"A\t" + p for p in ALLOWED}:
        raise ValueError("ADDITIVE_SCOPE_OR_CLEAN_WORKTREE_MISMATCH")
    def tree(ref):
        return {r.split("\t", 1)[1]: r.split("\t", 1)[0].split()[2] for r in git("ls-tree", "-r", ref).splitlines()}
    before, after = tree(BASE), tree(args.expected_head)
    if any(after.get(path) != blob for path, blob in before.items()):
        raise ValueError("GOVERNANCE_ESCALATION_REQUIRED_EXISTING_FILE_CHANGED")
    if any(after.get(path) != blob for path, blob in REVIEWED_BLOBS.items()):
        raise ValueError("REVIEWED_READINESS_SEMANTICS_OR_ASSERTIONS_CHANGED")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "PROTECTED_BASE_BLOBS.json", before)
    results = {}
    temporary = args.output_dir.resolve() / "temporary"
    temporary.mkdir()
    with tempfile.TemporaryDirectory(prefix="pi-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"
        extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        command = [sys.executable, "-B", str(mirror / "scripts/verify_provider_warmup_readiness.py")]
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temporary), "TMP": str(temporary)}
        for name, (modules, count) in GROUPS.items():
            output = args.output_dir.resolve() / (name + ".json")
            run = subprocess.run([*command, "--test-child", str(output), *modules], cwd=mirror,
                capture_output=True, text=True, encoding="utf-8", env=env)
            (args.output_dir / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            result = json.loads(output.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and r["exit_code"] == 0 and not r["skipped"]
                 for r in results.values())
    if git("rev-parse", "HEAD") != args.expected_head or git("status", "--porcelain"):
        raise ValueError("WORKTREE_CHANGED_DURING_TESTS")
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {"base_sha": BASE, "head_sha": args.expected_head,
        "changed_files": sorted(ALLOWED), "existing_tests": sum(c for _, c in EXISTING.values()), "new_tests": 47,
        "results": results, "protected_existing_blobs_unchanged": len(before), "financial_requests": 0,
        "reviewed_head": REVIEWED_HEAD, "unchanged_readiness_blobs": REVIEWED_BLOBS,
        "current_main_inherited_groups": {name: count for name, (_, count) in EXISTING.items()},
        "tests_skipped": sum(len(r["skipped"]) for r in results.values()),
        "assertions_relaxed": 0, "failure_whitelists": 0,
        "production_mutations": 0, "production_eligible": False, "first_refresh_eligible": False,
        "material_scope": "SYNTHETIC_ENGINEERING_NOT_REAL_PROVIDER_QUALIFICATION",
        "validation_status": "PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

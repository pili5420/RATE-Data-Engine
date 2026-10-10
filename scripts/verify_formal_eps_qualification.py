"""Exact-head synthetic engineering and unchanged production regressions."""
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
from scripts.verify_phase2_compatibility import GROUPS as EXISTING_GROUPS

BASE = "57b1d053d7374a100cdb97a24c6a8e01ad5061e9"
ALLOWED = {"src/formal_eps_qualification.py", "scripts/qualify_formal_eps.py",
           "scripts/verify_formal_eps_qualification.py", "tests/test_formal_eps_qualification.py",
           "docs/RATE_FORMAL_EPS_QUALIFICATION.md",
           "docs/contracts/RATE_FORMAL_EPS_PERIOD_QUALIFICATION_V1.json",
           ".github/workflows/rate_formal_eps_qualification_ci.yml"}
GROUPS = {**EXISTING_GROUPS,
          "formal_owner_existing": (["test_cer073_fundamental_history_v2"], 17),
          "qualification_new": (["test_formal_eps_qualification"], 30)}


def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("QUALIFICATION_NETWORK_FORBIDDEN:" + event)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(deny_network)
        return child(Path(sys.argv[2]), sys.argv[3:])
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if a.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    if a.expected_base != BASE or git("rev-parse", "HEAD") != a.expected_head or git("merge-base", BASE, "HEAD") != BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    changed = git("diff", "--name-only", BASE, a.expected_head).splitlines()
    if not changed or set(changed) - ALLOWED or git("status", "--porcelain"):
        raise ValueError("SCOPE_OR_WORKTREE_CHANGED")
    def tree(rev):
        return {line.split("\t", 1)[1]: line.split("\t")[0].split()[2]
                for line in git("ls-tree", "-r", rev).splitlines()}
    old, new = tree(BASE), tree(a.expected_head)
    # This PR only adds isolated files. Every existing blob is protected, including all tests.
    if any(new.get(path) != value for path, value in old.items()):
        raise ValueError("EXISTING_PROTECTED_BLOB_CHANGED")
    a.output_dir.mkdir(parents=True)
    write(a.output_dir / "protected-blobs.json", old)
    results = {}
    with tempfile.TemporaryDirectory(prefix="epsq-", dir=ROOT.parent) as tmp:
        mirror = Path(tmp) / "head"
        extract(a.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        for name, (modules, count) in GROUPS.items():
            out = a.output_dir.resolve() / (name + ".json")
            command = [sys.executable, "-B", str(mirror / "scripts/verify_formal_eps_qualification.py"),
                       "--test-child", str(out), *modules]
            run = subprocess.run(command, cwd=mirror, capture_output=True, text=True, encoding="utf-8",
                                 env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
            (a.output_dir / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            result = json.loads(out.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and r["exit_code"] == 0 for r in results.values())
    if git("rev-parse", "HEAD") != a.expected_head or git("status", "--porcelain"):
        raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(a.output_dir / "VERIFICATION_PACKAGE.json", {
        "base_sha": BASE, "head_sha": a.expected_head, "changed_files": changed,
        "results": results, "protected_existing_blobs_unchanged": len(old),
        "real_financial_requests": 0, "warmup_dispatches": 0, "production_mutations": 0,
        "qualification_only": True, "production_eligible": False,
        "formal_warmup_gate": "FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN",
        "fallback_allowed": False, "validation_status": "PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

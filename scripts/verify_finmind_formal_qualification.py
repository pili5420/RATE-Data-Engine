"""Exact-head additive isolation; existing gates and synthetic Phase C tests."""
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
from scripts.verify_formal_eps_qualification import GROUPS as EXISTING_GROUPS

BASE = "6ea91f2328827d2233537292a55fe6acf15b8470"
ALLOWED = {"src/finmind_formal_qualification.py", "scripts/qualify_finmind_eps.py",
           "scripts/verify_finmind_formal_qualification.py", "tests/test_finmind_formal_qualification.py",
           "docs/RATE_FINMIND_FORMAL_EPS_QUALIFICATION.md",
           "docs/contracts/RATE_FINMIND_FORMAL_EPS_QUALIFICATION_V1.json",
           ".github/workflows/rate_finmind_formal_qualification_ci.yml"}
GROUPS = {**EXISTING_GROUPS,
    "provider_existing_93": (["test_provider_eps_candidate", "test_provider_eps_coverage",
        "test_provider_eps_recovery", "test_provider_eps_metadata", "test_provider_eps_wait_semantics"], 93),
    "features_existing_42": (["test_provider_financial_features"], 42),
    "shadow_existing_36": (["test_provider_fundamental_shadow"], 36),
    "revenue_existing_23": (["test_provider_revenue_snapshot"], 23),
    "forward_existing_52": (["test_provider_shadow_forward"], 52),
    "finmind_qualification_new": (["test_finmind_formal_qualification"], 42)}


def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("PHASE_C_NETWORK_FORBIDDEN:" + event)


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
    changes = git("diff", "--name-status", "--no-renames", BASE, a.expected_head).splitlines()
    if set(changes) != {"A\t" + path for path in ALLOWED} or git("status", "--porcelain"):
        raise ValueError("EXACT_ADDITIVE_SCOPE_OR_WORKTREE_CHANGED")
    def tree(rev):
        return {line.split("\t", 1)[1]: line.split("\t")[0].split()[2]
                for line in git("ls-tree", "-r", rev).splitlines()}
    old, new = tree(BASE), tree(a.expected_head)
    if any(new.get(path) != value for path, value in old.items()):
        raise ValueError("EXISTING_PROTECTED_BLOB_CHANGED")
    a.output_dir.mkdir(parents=True)
    write(a.output_dir / "protected-blobs.json", old)
    # Windows runner TEMP can use an 8.3 alias; fixtures and readers must see one identity.
    test_temp = a.output_dir.resolve() / "temporary"
    test_temp.mkdir()
    write(a.output_dir / "temporary-directory-binding.json", {
        "runner_default_temp": tempfile.gettempdir(),
        "runner_default_resolved": str(Path(tempfile.gettempdir()).resolve()),
        "test_temp": str(test_temp), "test_temp_resolved": str(test_temp.resolve())})
    results = {}
    with tempfile.TemporaryDirectory(prefix="finmindq-", dir=ROOT.parent) as tmp:
        mirror = Path(tmp) / "head"
        extract(a.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        for name, (modules, count) in GROUPS.items():
            out = a.output_dir.resolve() / (name + ".json")
            run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_finmind_formal_qualification.py"),
                "--test-child", str(out), *modules], cwd=mirror, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
                     "TEMP": str(test_temp), "TMP": str(test_temp)})
            (a.output_dir / (name + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            result = json.loads(out.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and r["exit_code"] == 0 for r in results.values())
    if git("rev-parse", "HEAD") != a.expected_head or git("status", "--porcelain"):
        raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(a.output_dir / "VERIFICATION_PACKAGE.json", {
        "base_sha": BASE, "head_sha": a.expected_head, "changed_files": sorted(ALLOWED),
        "results": results, "protected_existing_blobs_unchanged": len(old),
        "real_financial_requests": 0, "warmup_dispatches": 0, "production_mutations": 0,
        "qualification_only": True, "production_eligible": False,
        "formal_warmup_gate": "FUNDAMENTAL_EPS_PERIOD_IDENTITY_UNPROVEN",
        "fallback_allowed": False, "validation_status": "PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

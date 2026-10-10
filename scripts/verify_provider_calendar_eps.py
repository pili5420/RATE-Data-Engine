"""Exact-head additive scope and all existing regression groups; synthetic CI only."""
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
from scripts.verify_finmind_formal_qualification import GROUPS as EXISTING_GROUPS

BASE = "30fd48d56ab935f1f2358b69257faad0f8ad5a0a"
ALLOWED = {"src/provider_calendar_eps_contract.py", "scripts/validate_provider_calendar_eps.py",
    "scripts/verify_provider_calendar_eps.py", "tests/test_provider_calendar_eps_contract.py",
    "docs/RATE_PROVIDER_CALENDAR_QUARTER_EPS_V1.md",
    "docs/contracts/RATE_PROVIDER_CALENDAR_QUARTER_EPS_V1.json",
    ".github/workflows/rate_provider_calendar_eps_ci.yml"}
GROUPS = {**EXISTING_GROUPS, "calendar_contract_new": (["test_provider_calendar_eps_contract"], 30)}


def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("CALENDAR_CONTRACT_NETWORK_FORBIDDEN:" + event)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(deny_network)
        return child(Path(sys.argv[2]), sys.argv[3:])
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    if args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head or git("merge-base", BASE, "HEAD") != BASE:
        raise ValueError("EXACT_BASE_HEAD_MISMATCH")
    if set(git("diff", "--name-status", "--no-renames", BASE, args.expected_head).splitlines()) != {"A\t" + p for p in ALLOWED} or git("status", "--porcelain"):
        raise ValueError("EXACT_ADDITIVE_SCOPE_OR_WORKTREE_CHANGED")
    def tree(ref):
        return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2] for line in git("ls-tree", "-r", ref).splitlines()}
    old, new = tree(BASE), tree(args.expected_head)
    if any(new.get(p) != value for p, value in old.items()):
        raise ValueError("EXISTING_PROTECTED_BLOB_CHANGED")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "protected-blobs.json", old)
    temp = args.output_dir.resolve() / "temporary"
    temp.mkdir()
    results = {}
    with tempfile.TemporaryDirectory(prefix="calq-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"
        extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        for group, (modules, count) in GROUPS.items():
            out = args.output_dir.resolve() / (group + ".json")
            run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_provider_calendar_eps.py"),
                "--test-child", str(out), *modules], cwd=mirror, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temp), "TMP": str(temp)})
            (args.output_dir / (group + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
            result = json.loads(out.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[group] = result
            print(json.dumps({"group": group, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and r["exit_code"] == 0 for r in results.values())
    if git("rev-parse", "HEAD") != args.expected_head or git("status", "--porcelain"):
        raise ValueError("HEAD_OR_WORKTREE_CHANGED")
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {"base_sha": BASE, "head_sha": args.expected_head,
        "changed_files": sorted(ALLOWED), "results": results, "existing_tests": sum(c for _, c in EXISTING_GROUPS.values()),
        "new_tests": GROUPS["calendar_contract_new"][1], "protected_existing_blobs_unchanged": len(old),
        "financial_requests": 0, "production_mutations": 0, "production_eligible": False,
        "warmup_policy": "UNCHANGED", "fallback_allowed": False, "validation_status": "PASS" if passed else "FAIL"})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

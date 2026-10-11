"""CI applicability with a strict historical branch and mandatory current-main replay."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_phase2_compatibility import ALLOWED, BASE as HISTORICAL_BASE
from scripts.verify_public_official_partial_valid import child, extract, git, write
from scripts.verify_prospective_acquisition_recovery import GROUPS
from src.prospective_acquisition_recovery import offline_network_guard

GOVERNANCE_FILES = {
    "scripts/verify_ci_applicability.py", "tests/test_ci_applicability.py",
    "docs/RATE_CI_APPLICABILITY_GOVERNANCE_V1.md",
}
WORKFLOW = ".github/workflows/rate_public_official_partial_valid_ci.yml"
GOVERNANCE_TEST_COUNT = 12


def applicability(base, head, merge_base, current_main, changed, clean):
    if not clean or not changed or len(head) != 40 or merge_base != base:
        raise ValueError("EXACT_BASE_HEAD_SCOPE_OR_WORKTREE_INVALID")
    if base == HISTORICAL_BASE and set(changed) <= ALLOWED:
        return "HISTORICAL_STRICT_GATE"
    if base != current_main:
        raise ValueError("CURRENT_MAIN_BASE_REQUIRED")
    return "CURRENT_MAIN_COMPATIBILITY_GATE"


def verdict(mode, results_pass, proof_pass):
    if not results_pass or not proof_pass:
        return "BLOCKED"
    return ("APPLICABLE_STRICT_PASS" if mode == "HISTORICAL_STRICT_GATE"
            else "NOT_APPLICABLE_REPLACED_BY_CURRENT_MAIN_GATE_PASS")


def network_guard(event, args):
    if event == "urllib.Request" and args and str(args[0]).startswith("file://"):
        return
    offline_network_guard(event, args)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(network_guard)
        return child(Path(sys.argv[2]), sys.argv[3:])
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    output = a.output_dir.resolve()
    if output.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    package = {"base_sha": a.expected_base, "head_sha": a.expected_head,
               "applicability_result": "BLOCKED", "real_financial_requests": 0,
               "production_mutations": 0, "assertions_relaxed": 0,
               "tests_skipped": 0, "failure_whitelists": 0}
    try:
        if git("rev-parse", "HEAD") != a.expected_head:
            raise ValueError("EXECUTION_HEAD_MISMATCH")
        current = git("rev-parse", "origin/main")
        changed = git("diff", "--name-only", a.expected_base, a.expected_head).splitlines()
        mode = applicability(a.expected_base, a.expected_head,
                             git("merge-base", a.expected_base, a.expected_head),
                             current, changed, not git("status", "--porcelain"))
        package.update(mode=mode, current_main_sha=current, changed_files=changed,
                       historical_verifier_unchanged=git("rev-parse", current + ":scripts/verify_phase2_compatibility.py")
                       == git("rev-parse", a.expected_head + ":scripts/verify_phase2_compatibility.py"))
        if not package["historical_verifier_unchanged"]:
            raise ValueError("HISTORICAL_STRICT_VERIFIER_CHANGED")
        if mode == "HISTORICAL_STRICT_GATE":
            run = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/verify_phase2_compatibility.py"),
                "--expected-base", a.expected_base, "--expected-head", a.expected_head,
                "--output-dir", str(output / "strict")], cwd=ROOT, capture_output=True)
            (output / "strict.log").write_bytes(run.stdout + run.stderr)
            strict = json.loads((output / "strict/VERIFICATION_PACKAGE.json").read_text(encoding="utf-8"))
            passed = run.returncode == 0 and strict["validation_status"] == "PASS"
            package["applicability_result"] = verdict(mode, passed, passed)
            package["strict"] = strict
        else:
            results = {}
            with tempfile.TemporaryDirectory(prefix="cg-", dir=ROOT.parent) as directory:
                mirror = Path(directory) / "h"
                extract(a.expected_head, mirror)
                (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
                temp = Path(directory) / "t"
                temp.mkdir()
                env = {**os.environ, "TEMP": str(temp), "TMP": str(temp),
                       "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
                groups = {**GROUPS, "ci_applicability_new": (["test_ci_applicability"], GOVERNANCE_TEST_COUNT)}
                for name, (modules, count) in groups.items():
                    report = output / (name + ".json")
                    run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_ci_applicability.py"),
                        "--test-child", str(report), *modules], cwd=mirror, env=env, capture_output=True)
                    (output / (name + ".log")).write_bytes(run.stdout + run.stderr)
                    result = json.loads(report.read_text(encoding="utf-8"))
                    result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
                    results[name] = result
                    print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
                run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_phase2_compatibility.py"),
                    "--proof-child", str(output / "continuity-proof")], cwd=mirror, env=env, capture_output=True)
                (output / "continuity-proof.log").write_bytes(run.stdout + run.stderr)
                proof_pass = run.returncode == 0
            tests_pass = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"]
                             and not r["skipped"] for r in results.values())
            package.update(results=results, proof_exit_code=run.returncode,
                           existing_tests=sum(count for _, count in GROUPS.values()),
                           governance_tests=GOVERNANCE_TEST_COUNT,
                           applicability_result=verdict(mode, tests_pass, proof_pass))
        if git("rev-parse", "HEAD") != a.expected_head or git("status", "--porcelain") or git("rev-parse", "origin/main") != current:
            raise ValueError("EXECUTION_BINDING_CHANGED")
    except Exception as error:
        package.update(applicability_result="BLOCKED", blocker=str(error))
        raise
    finally:
        write(output / "CI_APPLICABILITY_RESULT.json", package)
    return 0 if package["applicability_result"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

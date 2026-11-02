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
# Compatibility export for inherited exact-head verifiers. The current-main
# replacement gate below discovers inventories dynamically and does not trust
# this value for admission.
GOVERNANCE_TEST_COUNT = 15
CURRENT_MAIN_GROUPS = {
    **GROUPS,
    "atomic_publication_inherited": (["test_atomic_refresh_publication"], 29),
}


def inventory_delta(base_ids, head_ids):
    base = list(base_ids)
    head = list(head_ids)
    if len(base) != len(set(base)) or len(head) != len(set(head)):
        raise ValueError("TEST_INVENTORY_DUPLICATE_ID")
    missing = sorted(set(base) - set(head))
    return {"base_count": len(base), "head_count": len(head), "missing_base_ids": missing,
            "base_preserved": not missing}


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
    if len(sys.argv) > 1 and sys.argv[1] == "--inventory-child":
        sys.addaudithook(network_guard)
        sys.path.insert(0, str(Path.cwd()))
        import unittest
        def flatten(suite):
            result = []
            for item in suite:
                result.extend(flatten(item) if isinstance(item, unittest.TestSuite) else [item.id()])
            return result
        suite = unittest.defaultTestLoader.loadTestsFromNames(["tests." + name for name in sys.argv[3:]])
        ids = flatten(suite)
        write(Path(sys.argv[2]), {"test_ids": ids, "test_count": len(ids)})
        return 0
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
            inventories = {}
            with tempfile.TemporaryDirectory(prefix="cg-", dir=ROOT.parent) as directory:
                base_mirror = Path(directory) / "b"
                mirror = Path(directory) / "h"
                extract(a.expected_base, base_mirror)
                extract(a.expected_head, mirror)
                gitdir = git("rev-parse", "--absolute-git-dir")
                (base_mirror / ".git").write_text("gitdir: " + gitdir + "\n", encoding="utf-8")
                (mirror / ".git").write_text("gitdir: " + gitdir + "\n", encoding="utf-8")
                temp = Path(directory) / "t"
                temp.mkdir()
                env = {**os.environ, "TEMP": str(temp), "TMP": str(temp),
                       "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
                groups = {**CURRENT_MAIN_GROUPS, "ci_applicability_new": (["test_ci_applicability"], None)}
                for name, (modules, _) in groups.items():
                    base_inventory_path = output / (name + "-base-inventory.json")
                    head_inventory_path = output / (name + "-head-inventory.json")
                    base_inventory_run = subprocess.run([sys.executable, "-B",
                        str(mirror / "scripts/verify_ci_applicability.py"), "--inventory-child",
                        str(base_inventory_path), *modules], cwd=base_mirror, env=env, capture_output=True)
                    head_inventory_run = subprocess.run([sys.executable, "-B",
                        str(mirror / "scripts/verify_ci_applicability.py"), "--inventory-child",
                        str(head_inventory_path), *modules], cwd=mirror, env=env, capture_output=True)
                    if base_inventory_run.returncode or head_inventory_run.returncode:
                        raise ValueError("TEST_INVENTORY_DISCOVERY_FAILED:" + name)
                    base_inventory = json.loads(base_inventory_path.read_text(encoding="utf-8"))
                    head_inventory = json.loads(head_inventory_path.read_text(encoding="utf-8"))
                    delta = inventory_delta(base_inventory["test_ids"], head_inventory["test_ids"])
                    if not delta["base_preserved"]:
                        raise ValueError("CURRENT_MAIN_TEST_DELETION_FORBIDDEN:" + name + ":" + ",".join(delta["missing_base_ids"]))
                    inventories[name] = delta

                    report = output / (name + ".json")
                    run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_ci_applicability.py"),
                        "--test-child", str(report), *modules], cwd=mirror, env=env, capture_output=True)
                    (output / (name + ".log")).write_bytes(run.stdout + run.stderr)
                    result = json.loads(report.read_text(encoding="utf-8"))
                    result.update(exit_code=run.returncode,
                                  exact_count_pass=result["tests_run"] == delta["head_count"],
                                  inventory_base_preserved=delta["base_preserved"],
                                  base_test_count=delta["base_count"], head_test_count=delta["head_count"])
                    results[name] = result
                    print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"],
                                      "base_tests": delta["base_count"], "head_tests": delta["head_count"]}), flush=True)
                run = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_phase2_compatibility.py"),
                    "--proof-child", str(output / "continuity-proof")], cwd=mirror, env=env, capture_output=True)
                (output / "continuity-proof.log").write_bytes(run.stdout + run.stderr)
                proof_pass = run.returncode == 0
            tests_pass = all(r["all_pass"] and r["exact_count_pass"] and r["inventory_base_preserved"]
                             and not r["exit_code"] and not r["skipped"] for r in results.values())
            package.update(results=results, test_inventory_deltas=inventories, proof_exit_code=run.returncode,
                           existing_tests=sum(row["head_count"] for name, row in inventories.items()
                                              if name != "ci_applicability_new"),
                           governance_tests=inventories["ci_applicability_new"]["head_count"],
                           current_main_test_deletion_forbidden=True,
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

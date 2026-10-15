"""Exact-head inherited/new tests and all 61 scoped engineering requirements."""
import argparse
from contextlib import contextmanager
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from scripts.verify_history_acceptance_sidecar import GROUPS as INHERITED
from scripts.verify_fundamental_ranking_consumer import clean_consumer_checkout, tree
from scripts.verify_public_official_partial_valid import child, git, write
from scripts.verify_ci_applicability import network_guard
from src.history_batch_launcher import engineering_environment

BASE = "e3ef25084f17f9073b25555b8c0cf911e1146ec8"
FROZEN = "fbdfbfcf0a003cd6de49911bc0a784275a32031c"
NEW_MODULES = ["test_history_batch_authority", "test_history_batch_orchestration", "test_history_batch_containment"]
ADDED = {
    "src/history_batch_authority.py", "src/history_batch_launcher.py", "src/history_batch_orchestration.py",
    "scripts/history_batch_synthetic_issuer.py", "scripts/history_batch_cold_acceptance.py", "scripts/verify_history_controlled_batch.py",
    "tests/batch_synthetic_support.py", "tests/history_batch_process_probe.py", "tests/test_history_batch_authority.py",
    "tests/test_history_batch_orchestration.py", "tests/test_history_batch_containment.py",
    "requirements/history_batch_synthetic.lock.txt", "docs/contracts/RATE_HISTORY_CONTROLLED_BATCH_ENGINEERING_V1.json",
    "docs/contracts/RATE_HISTORY_CONTROLLED_BATCH_TEST_MATRIX_V1.json", "docs/RATE_HISTORY_CONTROLLED_BATCH_ENGINEERING_V1.md",
    ".github/workflows/rate_history_controlled_batch_ci.yml"}


def flatten(suite):
    result = []
    for test in suite:
        result.extend(flatten(test) if isinstance(test, unittest.TestSuite) else [test.id()])
    return result


def exact_test_checkout(revision, directory):
    # Restore Git blob bytes, including historical manifests, in this new disposable clone only.
    configuration = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.autocrlf", "GIT_CONFIG_VALUE_0": "false"}
    previous = {key: os.environ.get(key) for key in configuration}
    try:
        os.environ.update(configuration)
        clean_consumer_checkout(revision, directory)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def short_test_directory():
    parent = Path(os.environ["RUNNER_TEMP"]).parent if os.environ.get("GITHUB_ACTIONS") == "true" else ROOT.parent
    parent = parent.resolve()
    temporary = parent / ("b" + uuid4().hex[:2])
    # A collision fails closed; no existing path is reused or removed.
    temporary.mkdir(exist_ok=False)
    try:
        yield temporary
    finally:
        if temporary.resolve() != temporary or temporary.parent != parent or not temporary.name.startswith("b"):
            raise ValueError("BATCH_TEMP_CLEANUP_BOUNDARY_MISMATCH")
        shutil.rmtree(temporary)


def test_child(output, modules):
    sys.addaudithook(network_guard)
    inventory = flatten(unittest.defaultTestLoader.loadTestsFromNames(["tests." + name for name in modules]))
    code = child(output, modules)
    result = json.loads(output.read_bytes())
    result["test_inventory"] = inventory
    result["inventory_matches_run"] = len(inventory) == result["tests_run"] and len(set(inventory)) == len(inventory)
    result["passing_test_ids"] = inventory if result["all_pass"] and result["inventory_matches_run"] else []
    write(output, result)
    return code if result["inventory_matches_run"] else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        return test_child(Path(sys.argv[2]), sys.argv[3:])
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    if (args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head
        or git("merge-base", BASE, args.expected_head) != BASE or git("status", "--porcelain", "--untracked-files=all")):
        raise ValueError("BATCH_EXACT_BASE_HEAD_OR_CLEAN_WORKTREE_MISMATCH")
    if set(git("diff", "--name-status", "--no-renames", BASE, args.expected_head).splitlines()) != {"A\t" + p for p in ADDED}:
        raise ValueError("BATCH_EXACT_ADDITIVE_SCOPE_REQUIRED")
    before, after = tree(BASE), tree(args.expected_head)
    frozen = tree(FROZEN)
    if any(after.get(path) != blob for path, blob in before.items()) or any(before.get(path) != blob for path, blob in frozen.items()):
        raise ValueError("BATCH_FROZEN_OR_SIDECAR_PROTECTED_BLOB_CHANGED")
    if args.output_dir.exists():
        raise ValueError("BATCH_OUTPUT_MUST_BE_NEW")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "PROTECTED_PARENT_BLOBS.json", before)
    matrix = json.loads((ROOT / "docs/contracts/RATE_HISTORY_CONTROLLED_BATCH_TEST_MATRIX_V1.json").read_bytes())
    if len(matrix["rows"]) != 61 or len({r["requirement_id"] for r in matrix["rows"]}) != 61:
        raise ValueError("BATCH_61_REQUIREMENTS_REQUIRED")
    results = {}
    with tempfile.TemporaryDirectory(prefix="bc", dir=args.output_dir.parent) as directory, short_test_directory() as temporary:
        directory = Path(directory)
        test_repo = directory / "h"
        exact_test_checkout(args.expected_head, test_repo)
        proof_dir = args.output_dir.resolve() / "synthetic-acceptance"; proof_dir.mkdir()
        env = {**engineering_environment(), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
            "TEMP": str(temporary), "TMP": str(temporary), "RATE_BATCH_SYNTHETIC_PROOF_DIR": str(proof_dir)}
        # No borrowed Git index: every owner requiring a clean checkout shares this exact own-index clone.
        groups = {**INHERITED, "controlled_batch_new": (NEW_MODULES, None)}
        all_ids = set()
        for name, (modules, expected_count) in groups.items():
            report = args.output_dir.resolve() / (name + ".json")
            command = [sys.executable, "-B", str(test_repo / "scripts/verify_history_controlled_batch.py"),
                       "--test-child", str(report), *modules]
            run = subprocess.run(command, cwd=test_repo, env=env, capture_output=True)
            (args.output_dir / (name + ".log")).write_bytes(run.stdout + run.stderr)
            if not report.exists():
                write(args.output_dir / "CHILD_FAILURE.json", {"group": name, "exit_code": run.returncode,
                    "stderr": run.stderr.decode("utf-8", errors="replace")})
                raise ValueError("BATCH_TEST_CHILD_NO_REPORT")
            result = json.loads(report.read_bytes())
            result.update(exit_code=run.returncode,
                exact_count_pass=result["tests_run"] == (expected_count if expected_count is not None else len(result["test_inventory"])))
            results[name] = result
            all_ids.update(result["passing_test_ids"])
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
        rows = []
        for requirement in matrix["rows"]:
            ids = requirement["test_ids"]
            local = ("PASS" if all(test_id in all_ids for test_id in ids) else "FAIL") if ids else "AGGREGATE_EVIDENCE_REQUIRED"
            rows.append({**requirement, "local_test_status": local, "required_platforms": ["Windows", "Linux"]})
        if any(r["local_test_status"] == "FAIL" for r in rows):
            write(args.output_dir / "REQUIREMENT_MAPPING_DEFECT.json", rows)
        write(args.output_dir / "EVIDENCE_MATRIX.json", {"head_sha": args.expected_head, "platform": platform.system(),
            "rows": rows, "aggregate_evidence_not_silently_marked_pass": True})
    passed = all(r["all_pass"] and r["inventory_matches_run"] and r["exact_count_pass"] and not r["exit_code"]
                 and not r["skipped"] for r in results.values()) and not any(r["local_test_status"] == "FAIL" for r in rows)
    if git("status", "--porcelain", "--untracked-files=all") or git("rev-parse", "HEAD") != args.expected_head:
        raise ValueError("BATCH_SOURCE_BINDING_CHANGED")
    new_count = results["controlled_batch_new"]["tests_run"]
    write(args.output_dir / "VERIFICATION_PACKAGE.json", {"status": "PASS" if passed else "BLOCKED",
        "base_sha": BASE, "head_sha": args.expected_head, "frozen_main": FROZEN, "sidecar_head": BASE,
        "changed_files": sorted(ADDED), "protected_parent_blobs": len(before), "protected_frozen_blobs": len(frozen),
        "platform": platform.system(), "python_version": sys.version,
        "dependency_versions": {name: version(name) for name in ("cryptography", "cffi", "pycparser", "lxml", "tzdata", "PyYAML")},
        "inherited_tests": sum(count for _, count in INHERITED.values()), "new_tests": new_count,
        "total_tests": sum(r["tests_run"] for r in results.values()), "results": results,
        "tests_skipped": sum(len(r["skipped"]) for r in results.values()), "assertions_relaxed": 0, "failure_whitelists": 0,
        "matrix_requirement_count": len(rows), "cross_platform_and_replacement_aggregation_required": True,
        "official_market_data_requests": 0, "real_keys_used": False, "real_authorizations_created": 0,
        "formal_ledger_written": False, "Bootstrap_interfered": False, "ranking_executions": 0,
        "production_publications": 0, "deployment": False, "effective_No_Auto_Next": True})
    write(args.output_dir / "RUNTIME_DEPLOYMENT_CANDIDATE.json", {"artifact_kind": "RATE_BATCH_RUNTIME_ENGINEERING_CANDIDATE_V1",
        "status": "NOT_DEPLOYED_NOT_ACTIVATED", "frozen_main": FROZEN, "sidecar_head": BASE, "engineering_head": args.expected_head,
        "owner_git_blobs": {p: after[p] for p in sorted(ADDED)}, "runtime_scope": "SYNTHETIC_ONLY",
        "real_keys": "NOT_CONFIGURED", "deployment_authorized": False, "bootstrap_authorized": False,
        "real_auto_next_authorized": False, "activation_gates": ["CONTROL_CENTER_ENGINEERING_AND_SECURITY_ACCEPTANCE",
            "INDEPENDENT_ISSUER_KEY_AND_ACCOUNT_QUALIFICATION", "EXTERNAL_WITNESS_STORAGE_AND_TIME_AUTHORITY",
            "SEPARATE_BOOTSTRAP_ACCEPTANCE", "FINITE_POLICY_AND_NO_AUTO_NEXT_EXCEPTION", "SEPARATE_EXACT_HEAD_ACTIVATION"]})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Latest-main compatibility proof for accepted RATE M-H additive engineering.

Historical acceptance is preserved by exact blob/ancestry pins. Current-main
compatibility is proven by base-vs-head test-outcome equivalence, not by forcing
historical frozen-owner tests to reinterpret a newer main as their old base.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_fundamental_ranking_consumer import clean_consumer_checkout, tree
from src.history_batch_launcher import engineering_environment

CURRENT_BASE = "5df302a720ac8114d3610342dad3783cc0a3debd"
FROZEN_PRODUCER = "fbdfbfcf0a003cd6de49911bc0a784275a32031c"
SIDECAR_ACCEPTED = "e3ef25084f17f9073b25555b8c0cf911e1146ec8"
BATCH_ACCEPTED = "959ab92f67ce6e1f57eadb262984e305ab96ad55"

SIDECAR_PINNED = [
    "docs/RATE_HISTORY_ACCEPTANCE_SIDECAR_V1.md",
    "docs/contracts/RATE_HISTORY_ACCEPTANCE_SIDECAR_V1.json",
    "scripts/run_history_acceptance_sidecar.py",
    "scripts/verify_history_acceptance_sidecar.py",
    "src/history_acceptance_sidecar.py",
    "tests/test_history_acceptance_sidecar.py",
]
BATCH_PINNED = [
    "docs/RATE_HISTORY_CONTROLLED_BATCH_ENGINEERING_V1.md",
    "docs/contracts/RATE_HISTORY_CONTROLLED_BATCH_ENGINEERING_V1.json",
    "docs/contracts/RATE_HISTORY_CONTROLLED_BATCH_TEST_MATRIX_V1.json",
    "requirements/history_batch_synthetic.lock.txt",
    "scripts/history_batch_cold_acceptance.py",
    "scripts/history_batch_synthetic_issuer.py",
    "scripts/verify_history_controlled_batch.py",
    "src/history_batch_authority.py",
    "src/history_batch_launcher.py",
    "src/history_batch_orchestration.py",
    "tests/batch_synthetic_support.py",
    "tests/history_batch_process_probe.py",
    "tests/test_history_batch_authority.py",
    "tests/test_history_batch_containment.py",
    "tests/test_history_batch_orchestration.py",
]
COMPATIBILITY_FILES = [
    "scripts/verify_history_mainline_compatibility.py",
    ".github/workflows/rate_history_mainline_compatibility_ci.yml",
    "docs/RATE_HISTORY_MAINLINE_COMPATIBILITY_V1.md",
]
EXPECTED_ADDED = set(SIDECAR_PINNED + BATCH_PINNED + COMPATIBILITY_FILES)

ACCEPTED_CORE_GROUPS = {
    "acceptance_sidecar_core": ["test_history_acceptance_sidecar"],
    "controlled_batch_core": [
        "test_history_batch_authority",
        "test_history_batch_orchestration",
        "test_history_batch_containment",
    ],
}
CURRENT_EQUIVALENCE_GROUPS = {
    "state_chain": ["test_production_scheduler_change_control", "test_rate_soak_005"],
    "report_soak": ["test_report_production_soak"],
    "phase2": ["test_full_market_rotation"],
    "prospective_activation": ["test_prospective_provider_activation"],
}

CHILD_CODE = r"""
import io, json, sys, unittest
from scripts.verify_ci_applicability import network_guard
sys.addaudithook(network_guard)

output = sys.argv[1]
modules = sys.argv[2:]
suite = unittest.defaultTestLoader.loadTestsFromNames(["tests." + name for name in modules])

def flatten(value):
    out = []
    for item in value:
        if isinstance(item, unittest.TestSuite):
            out.extend(flatten(item))
        else:
            out.append(item.id())
    return out

inventory = flatten(suite)
stream = io.StringIO()
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
status = {test_id: "PASS" for test_id in inventory}
failures = []
errors = []
skipped = []
for test, tb in result.failures:
    status[test.id()] = "FAIL"
    failures.append(test.id())
for test, tb in result.errors:
    status[test.id()] = "ERROR"
    errors.append(test.id())
for test, reason in result.skipped:
    status[test.id()] = "SKIP"
    skipped.append(test.id())

with open(output, "w", encoding="utf-8") as handle:
    json.dump({
        "tests_run": result.testsRun,
        "inventory": inventory,
        "status": status,
        "failures": sorted(failures),
        "errors": sorted(errors),
        "skipped": sorted(skipped),
        "runner_output": stream.getvalue(),
    }, handle, ensure_ascii=False, sort_keys=True)
sys.exit(0 if result.wasSuccessful() else 1)
"""


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def ancestor(old: str, new: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", old, new],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def write(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def pin_files(head: str) -> dict:
    head_tree = tree(head)
    sidecar_tree = tree(SIDECAR_ACCEPTED)
    batch_tree = tree(BATCH_ACCEPTED)
    bad = [path for path in SIDECAR_PINNED if head_tree.get(path) != sidecar_tree.get(path)]
    bad += [path for path in BATCH_PINNED if head_tree.get(path) != batch_tree.get(path)]
    if bad:
        raise ValueError("ACCEPTED_MH_BLOB_PIN_MISMATCH:" + ",".join(bad))
    return {
        "sidecar_pinned_files": len(SIDECAR_PINNED),
        "batch_pinned_files": len(BATCH_PINNED),
        "accepted_core_files_total": len(SIDECAR_PINNED) + len(BATCH_PINNED),
    }


def prepare_checkout(revision: str, directory: Path) -> None:
    clean_consumer_checkout(revision, directory)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", CURRENT_BASE],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    if git("status", "--porcelain", cwd=directory):
        raise ValueError("COMPATIBILITY_CHECKOUT_NOT_CLEAN")


def run_group(checkout: Path, modules: list[str], report: Path, env: dict[str, str]) -> dict:
    command = [sys.executable, "-B", "-c", CHILD_CODE, str(report), *modules]
    completed = subprocess.run(command, cwd=checkout, env=env, capture_output=True)
    if not report.exists():
        raise ValueError("COMPATIBILITY_TEST_CHILD_NO_REPORT:" + ",".join(modules))
    value = json.loads(report.read_text(encoding="utf-8"))
    value.update(
        exit_code=completed.returncode,
        stdout=completed.stdout.decode("utf-8", errors="replace"),
        stderr=completed.stderr.decode("utf-8", errors="replace"),
        clean_after=not bool(git("status", "--porcelain", cwd=checkout)),
    )
    return value


def outcome_signature(value: dict) -> dict:
    return {
        "tests_run": value["tests_run"],
        "inventory": value["inventory"],
        "status": value["status"],
        "failures": value["failures"],
        "errors": value["errors"],
        "skipped": value["skipped"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.expected_base != CURRENT_BASE or git("rev-parse", "HEAD") != args.expected_head:
        raise ValueError("LATEST_MAIN_BASE_OR_HEAD_MISMATCH")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("LATEST_MAIN_WORKTREE_NOT_CLEAN")
    if git("merge-base", CURRENT_BASE, args.expected_head) != CURRENT_BASE:
        raise ValueError("LATEST_MAIN_NOT_DIRECT_DESCENDANT")

    changed = set(git("diff", "--name-status", "--no-renames", CURRENT_BASE, args.expected_head).splitlines())
    if changed != {"A\t" + path for path in EXPECTED_ADDED}:
        raise ValueError("LATEST_MAIN_EXACT_ADDITIVE_SCOPE_REQUIRED")

    before, after = tree(CURRENT_BASE), tree(args.expected_head)
    if any(after.get(path) != blob for path, blob in before.items()):
        raise ValueError("LATEST_MAIN_PROTECTED_BLOB_CHANGED")

    if not (
        ancestor(FROZEN_PRODUCER, CURRENT_BASE)
        and ancestor(FROZEN_PRODUCER, SIDECAR_ACCEPTED)
        and ancestor(SIDECAR_ACCEPTED, BATCH_ACCEPTED)
    ):
        raise ValueError("MH_HISTORICAL_ANCESTRY_BINDING_INVALID")

    pins = pin_files(args.expected_head)
    if args.output_dir.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW")
    args.output_dir.mkdir(parents=True)
    write(args.output_dir / "CURRENT_MAIN_PROTECTED_BLOBS.json", before)
    write(args.output_dir / "ACCEPTED_BLOB_PIN_SUMMARY.json", pins)

    accepted_results = {}
    equivalence_results = {}
    temp_parent = os.getenv("RUNNER_TEMP")
    short_parent = Path(temp_parent) if temp_parent else ROOT.parent
    # Controlled-batch acceptance explicitly enforces Windows MAX_PATH <= 259.
    # Keep compatibility checkouts intentionally short instead of relaxing that gate.
    temp_root = short_parent / "m"
    if temp_root.exists():
        import shutil
        shutil.rmtree(temp_root)
    temp_root.mkdir()
    try:
        for index, (name, modules) in enumerate(ACCEPTED_CORE_GROUPS.items()):
            checkout = temp_root / f"c{index}"
            prepare_checkout(args.expected_head, checkout)
            run_temp = temp_root / f"t{index}"
            run_temp.mkdir()
            env = {
                **os.environ,
                **engineering_environment(),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
                "TEMP": str(run_temp),
                "TMP": str(run_temp),
            }
            report = args.output_dir / (name + ".json")
            result = run_group(checkout, modules, report, env)
            accepted_results[name] = result
            print(json.dumps({
                "group": name,
                "tests": result["tests_run"],
                "pass": result["exit_code"] == 0 and result["clean_after"],
            }, sort_keys=True), flush=True)

        for index, (name, modules) in enumerate(CURRENT_EQUIVALENCE_GROUPS.items()):
            base_checkout = temp_root / f"b{index}"
            head_checkout = temp_root / f"h{index}"
            prepare_checkout(CURRENT_BASE, base_checkout)
            prepare_checkout(args.expected_head, head_checkout)
            base_tmp = temp_root / f"u{index}"
            head_tmp = temp_root / f"v{index}"
            base_tmp.mkdir()
            head_tmp.mkdir()
            base_env = {
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
                "TEMP": str(base_tmp),
                "TMP": str(base_tmp),
            }
            head_env = {
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
                "TEMP": str(head_tmp),
                "TMP": str(head_tmp),
            }
            base_report = args.output_dir / (name + "-base.json")
            head_report = args.output_dir / (name + "-head.json")
            base_result = run_group(base_checkout, modules, base_report, base_env)
            head_result = run_group(head_checkout, modules, head_report, head_env)
            equivalent = (
                outcome_signature(base_result) == outcome_signature(head_result)
                and base_result["clean_after"]
                and head_result["clean_after"]
            )
            equivalence_results[name] = {
                "equivalent": equivalent,
                "base": base_result,
                "head": head_result,
            }
            print(json.dumps({
                "group": name,
                "base_exit": base_result["exit_code"],
                "head_exit": head_result["exit_code"],
                "equivalent": equivalent,
                "tests": head_result["tests_run"],
            }, sort_keys=True), flush=True)

    finally:
        import shutil
        shutil.rmtree(temp_root, ignore_errors=True)

    accepted_pass = all(
        result["exit_code"] == 0
        and result["clean_after"]
        and not result["failures"]
        and not result["errors"]
        and not result["skipped"]
        for result in accepted_results.values()
    )
    equivalence_pass = all(row["equivalent"] for row in equivalence_results.values())
    passed = accepted_pass and equivalence_pass

    if git("status", "--porcelain", "--untracked-files=all") or git("rev-parse", "HEAD") != args.expected_head:
        raise ValueError("LATEST_MAIN_SOURCE_BINDING_CHANGED")

    write(args.output_dir / "VERIFICATION_PACKAGE.json", {
        "artifact": "RATE_MH_LATEST_MAIN_COMPATIBILITY_VERIFICATION",
        "status": "PASS" if passed else "BLOCKED",
        "current_main_base": CURRENT_BASE,
        "integration_head": args.expected_head,
        "frozen_campaign_producer": FROZEN_PRODUCER,
        "accepted_sidecar_head": SIDECAR_ACCEPTED,
        "accepted_batch_head": BATCH_ACCEPTED,
        "accepted_blob_pins": pins,
        "protected_current_main_blobs": len(before),
        "historical_acceptance_replayed": False,
        "historical_acceptance_preservation": "EXACT_ACCEPTED_BLOB_AND_ANCESTRY_PINS",
        "accepted_core_results": accepted_results,
        "current_main_outcome_equivalence": equivalence_results,
        "base_failures_are_not_relabelled_pass": True,
        "failure_whitelists": 0,
        "assertions_relaxed": 0,
        "official_market_data_requests": 0,
        "real_keys_used": False,
        "real_authorizations_created": 0,
        "formal_acceptance_ledger_written": False,
        "chunk3_material_created": False,
        "ranking_executions": 0,
        "production_publications": 0,
        "production_state_mutations": 0,
        "effective_No_Auto_Next": True,
        "deployment_authorized": False,
        "production_bridge_authorized": False,
        "intraday_status": "BLOCKED_EXTERNAL",
        "cer081_credit": 0,
    })
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

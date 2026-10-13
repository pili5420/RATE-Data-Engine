"""Exact-head additive isolation and inherited synthetic regressions; no live data."""
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
from scripts.verify_discovery_tpex_benchmark_schema import GROUPS as INHERITED
from scripts.verify_fundamental_ranking_consumer import clean_consumer_checkout, tree
from scripts.verify_ci_applicability import network_guard

BASE = "54c318c2a72fbd87fa3d03f3f19fa1284e6426f6"
PREVIOUS_HEAD = "c8dae63c00b50571a25e77e541b7e1a13821cd82"
NEW_COUNT = 74
ADDED = {"src/history_acquisition_execution.py", "src/history_acquisition_transport.py", "src/history_acquisition_validation.py",
    "scripts/run_history_acquisition.py", "scripts/verify_history_acquisition_wiring.py", "tests/test_history_acquisition_wiring.py",
    "docs/contracts/RATE_HISTORY_ACQUISITION_WIRING_V1.json", "docs/RATE_HISTORY_ACQUISITION_WIRING_V1.md",
    ".github/workflows/rate_history_acquisition_wiring_ci.yml"}
GROUPS = {**INHERITED, "history_wiring_new": (["test_history_acquisition_wiring"], NEW_COUNT)}
DECISION_FILES = {"docs/contracts/RATE_HISTORY_ACQUISITION_WIRING_V1.json", "docs/RATE_HISTORY_ACQUISITION_WIRING_V1.md",
    "scripts/verify_history_acquisition_wiring.py", "tests/test_history_acquisition_wiring.py"}


def decision_binding(contract=None):
    if contract is None:
        contract = json.loads((ROOT / "docs/contracts/RATE_HISTORY_ACQUISITION_WIRING_V1.json").read_text(encoding="utf-8"))
    expected = {
        "history_executor": "SOURCE_NATIVE_INDEPENDENT_CUTOFFS", "phase_m_decision_owner": "UNCHANGED",
        "reference": "src/full_market_component_evidence.py::build; COMPONENT_LATEST_VERIFIED_SESSION_REQUIRED and COMPONENT_CROSS_MARKET_SESSION_ALIGNMENT",
        "status": "CONTROL_CENTER_DECISION_ACCEPTED_STRICT_COMMON_LATEST_SESSION",
        "strict_common_latest_target_required": True,
        "required_target_bindings": ["verified_sessions[TWSE][-1] == target", "verified_sessions[TPEX][-1] == target",
            "latest_official_session[TWSE] == target", "latest_official_session[TPEX] == target"],
        "minimum_verified_sessions_per_market": 180, "final12_cross_market_alignment_required": True,
        "mismatch_decision_eligibility": "BLOCKED", "backdated_common_target_substitution_allowed": False,
        "intersection_latest_target_substitution_allowed": False, "history_evidence_mutation_for_alignment_allowed": False,
        "acquisition_pass_grants_phase_m_decision_eligibility": False,
        "reevaluation": "ONLY_AFTER_OFFICIAL_LATEST_SESSION_EVIDENCE_NATURALLY_ALIGNS"}
    if contract.get("common_cutoff") != expected:
        raise ValueError("HISTORY_CONTROL_CENTER_DECISION_BINDING_INVALID")
    return contract["common_cutoff"]


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(network_guard)
        return child(Path(sys.argv[2]), sys.argv[3:])
    p = argparse.ArgumentParser()
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    if a.expected_base != BASE or git("rev-parse", "HEAD") != a.expected_head or git("merge-base", BASE, a.expected_head) != BASE or git("status", "--porcelain"):
        raise ValueError("HISTORY_WIRING_EXACT_BASE_HEAD_OR_WORKTREE")
    if set(git("diff", "--name-status", "--no-renames", BASE, a.expected_head).splitlines()) != {"A\t" + path for path in ADDED}:
        raise ValueError("HISTORY_WIRING_NINE_ADDITIVE_FILES_REQUIRED")
    old, new = tree(BASE), tree(a.expected_head)
    if any(new.get(path) != blob for path, blob in old.items()):
        raise ValueError("GOVERNANCE_ESCALATION_REQUIRED_EXISTING_BLOB_CHANGED")
    if git("merge-base", PREVIOUS_HEAD, a.expected_head) != PREVIOUS_HEAD or set(
        git("diff", "--name-status", "--no-renames", PREVIOUS_HEAD, a.expected_head).splitlines()) != {"M\t" + path for path in DECISION_FILES}:
        raise ValueError("HISTORY_DECISION_BINDING_FOUR_FILE_DELTA_REQUIRED")
    previous = tree(PREVIOUS_HEAD)
    if any(new.get(path) != blob for path, blob in previous.items() if path not in DECISION_FILES):
        raise ValueError("HISTORY_DECISION_BINDING_RUNTIME_CHANGED")
    binding = decision_binding()
    if a.output_dir.exists():
        raise ValueError("VERIFICATION_OUTPUT_MUST_BE_NEW")
    a.output_dir.mkdir(parents=True)
    write(a.output_dir / "PROTECTED_MAIN_BLOBS.json", old)
    results = {}
    with tempfile.TemporaryDirectory(prefix="mh-ci-", dir=ROOT.parent) as directory:
        mirror = Path(directory) / "head"
        extract(a.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        temp = Path(directory) / "tmp"
        temp.mkdir()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "TEMP": str(temp), "TMP": str(temp)}
        for name, (modules, count) in GROUPS.items():
            repo = mirror
            if name == "consumer_new":
                repo = Path(directory) / "consumer"
                clean_consumer_checkout(a.expected_head, repo)
            report = a.output_dir.resolve() / (name + ".json")
            run = subprocess.run([sys.executable, "-B", str(repo / "scripts/verify_history_acquisition_wiring.py"),
                "--test-child", str(report), *modules], cwd=repo, env=env, capture_output=True)
            (a.output_dir / (name + ".log")).write_bytes(run.stdout + run.stderr)
            result = json.loads(report.read_text(encoding="utf-8"))
            result.update(exit_code=run.returncode, exact_count_pass=result["tests_run"] == count)
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "pass": result["all_pass"]}), flush=True)
    passed = all(r["all_pass"] and r["exact_count_pass"] and not r["exit_code"] and not r["skipped"] for r in results.values())
    if git("status", "--porcelain") or git("rev-parse", "HEAD") != a.expected_head:
        raise ValueError("HISTORY_WIRING_EXECUTION_BINDING_CHANGED")
    write(a.output_dir / "VERIFICATION_PACKAGE.json", {"status": "PASS" if passed else "ENGINEERING_BLOCKED", "base_sha": BASE,
        "head_sha": a.expected_head, "changed_files": sorted(ADDED), "existing_tests": sum(n for _, n in INHERITED.values()),
        "new_tests": NEW_COUNT, "total_tests": sum(n for _, n in GROUPS.values()), "results": results,
        "existing_main_blobs_preserved": len(old), "tests_skipped": sum(len(r["skipped"]) for r in results.values()),
        "assertions_relaxed": 0, "failure_whitelists": 0, "material_scope": "SYNTHETIC_ONLY",
        "official_market_data_requests": 0, "financial_requests": 0, "ranking_executions": 0, "production_publications": 0,
        "historical_pit": "UNPROVEN", "intraday": "BLOCKED_EXTERNAL", "fallback_allowed": False,
        "real_calendar_180_ready": False, "tpex_unit_scale": "TPEX_UNIT_SCALE_QUALIFICATION_REQUIRED",
        "common_cutoff": binding["status"], "control_center_decision": binding,
        "previous_head": PREVIOUS_HEAD, "changed_files_from_previous_head": sorted(DECISION_FILES),
        "runtime_files_changed_from_previous_head": 0, "phase_m_owner_changed": False,
        "strategy_ranking_files_modified": 0})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

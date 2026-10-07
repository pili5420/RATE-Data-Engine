"""Current-base acceptance, separate from unchanged historical PR29/30 scripts."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_b1_research import build_view, canonical, digest, export_view, verify_export

BASE = "9c4c9d729c9d537173e227f139abcc06099ce45c"
SUITE = ("tests.test_eps_b1_research", "tests.test_eps_duration_facts", "tests.test_fundamental",
         "tests.test_logic", "tests.test_state_engine", "tests.test_production_integration",
         "tests.test_cer073_fundamental_history_v2", "tests.test_full_market_history_acquisition")
CUTOFF = "2026-10-07T23:59:59+08:00"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def tracked_hashes(paths, root=ROOT):
    return {p: digest((root / p).read_bytes()) for p in paths}


def put(directory, name, value):
    with (directory / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def formal(code_root, b1_root, head):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "RATE_B1_FORMAL_CODE_ROOT": str(code_root),
           "RATE_B1_RESEARCH_ROOT": str(b1_root)}
    process = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/eps_b1_formal_fixture.py")],
                             cwd=code_root, env=env, capture_output=True, text=True, encoding="utf-8")
    if process.returncode:
        raise RuntimeError(process.stderr)
    return json.loads(process.stdout)


def verify(output, expected_head, expected_base):
    output = Path(output).resolve()
    if output == ROOT or ROOT in output.parents or output.exists():
        raise ValueError("NEW_EXTERNAL_EVIDENCE_DIRECTORY_REQUIRED")
    if any(p.casefold() in ("data", "artifacts", "production", "portfolio", "ledger", "live", "latest") for p in output.parts):
        raise ValueError("PROTECTED_EVIDENCE_NAMESPACE")
    output.mkdir(parents=True)
    head = git("rev-parse", "HEAD").decode().strip()
    if head != expected_head or expected_base != BASE:
        raise ValueError("EXACT_HEAD_OR_REVIEWED_BASE_BINDING_INVALID")
    git("merge-base", "--is-ancestor", BASE, head)
    base_paths = git("ls-tree", "-r", "--name-only", BASE).decode().splitlines()
    changes = git("diff", "--name-status", BASE, head).decode().splitlines()
    if any(not change.startswith("A\t") for change in changes):
        raise ValueError("EXISTING_MAIN_BLOB_CHANGED")
    before = tracked_hashes(base_paths)
    all_paths = git("ls-files").decode().splitlines()
    candidate_before = tracked_hashes(all_paths)
    for relative in base_paths:
        if relative.endswith(".py") and relative.startswith(("src/", "scripts/")):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                names = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                         else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                if any("eps_b1" in name for name in names):
                    raise ValueError("PRODUCTION_REVERSE_DEPENDENCY")
    put(output, "protected-before.json", before)
    archive = ROOT / "tests/fixtures/eps_duration/official-proof.zip"
    value = build_view(archive, CUTOFF, head)
    b1_root = output / "rate-eps-b1-research"
    manifest = export_view(value, archive, b1_root, b1_root / "preview")
    verify_export(b1_root / "preview", archive, expected_code_sha=head)
    with tempfile.TemporaryDirectory(prefix="rate-b1-acceptance-") as temporary:
        baseline, candidate = Path(temporary) / "baseline", Path(temporary) / "candidate"
        for commit, directory in ((BASE, baseline), (head, candidate)):
            # Existing frozen-baseline tests need git show, not only archived working files.
            subprocess.run(["git", "-c", "core.autocrlf=false", "clone", "--shared", "--no-checkout",
                            str(ROOT), str(directory)], check=True, capture_output=True)
            subprocess.run(["git", "-c", "core.autocrlf=false", "checkout", "--detach", commit],
                           cwd=directory, check=True, capture_output=True)
        if tracked_hashes(base_paths, baseline) != before or tracked_hashes(base_paths, candidate) != before:
            raise ValueError("BASELINE_WORKING_BYTES_MISMATCH")
        reference = formal(baseline, b1_root / "comparison", head)
        put(output, "baseline-formal-fingerprint.json", reference)
        rows = []
        fields = ("formal_eps_input_sha256", "fundamental_sha256", "scores", "rankings", "decision_payload",
                  "state_hash", "state_id", "missing_formal_eps_gate", "state_mutation", "fallback_used")
        comparison = b1_root / "comparison"
        for case in ("ABSENT", "PRESENT", "UPDATED", "CORRUPT"):
            if case == "PRESENT":
                export_view(value, archive, b1_root, comparison)
            if case == "UPDATED":
                update = build_view(archive, "2026-10-05T23:59:59+08:00", head)
                export_view(update, archive, b1_root, b1_root / "comparison-updated")
                comparison = b1_root / "comparison-updated"
            if case == "CORRUPT":
                (comparison / "RATE_EPS_B1_RESEARCH_VIEW.json").write_text("CORRUPT", encoding="utf-8")
            result = formal(candidate, comparison, head)
            checks = {field: result[field] == reference[field] for field in fields}
            if not all(checks.values()):
                raise ValueError("NONINTERFERENCE_FAILURE:" + case)
            put(output, "candidate-formal-" + case.lower() + ".json", result)
            rows.append({"b1_condition": case, "comparisons": checks, "result": "PASS"})
        put(output, "noninterference-matrix.json", rows)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        tests = subprocess.run([sys.executable, "-B", "-m", "unittest", *SUITE, "-v"], cwd=candidate,
                               env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (output / "current-integration-tests.log").write_text(tests.stdout + tests.stderr, encoding="utf-8")
        if tracked_hashes(base_paths, candidate) != before:
            raise ValueError("TEST_MUTATED_PROTECTED_TRACKED_FILE")
    if tracked_hashes(base_paths) != before or tracked_hashes(all_paths) != candidate_before:
        raise ValueError("CURRENT_CHECKOUT_MUTATION")
    git("diff", "--exit-code")
    put(output, "protected-after.json", tracked_hashes(base_paths))
    log = tests.stdout + tests.stderr
    result = {"authority": "CR-RATE-EPS-B1-NONDECISION-V1", "usage_scope": "NONDECISION_RESEARCH_ONLY",
        "base_sha": BASE, "head_sha": head, "changed_files": [line.split("\t")[1] for line in changes],
        "existing_base_file_count": len(base_paths), "all_existing_main_files_byte_identical": True,
        "all_candidate_tracked_bytes_unchanged_during_tests": True, "production_b1_imports": 0,
        "current_integration_test_count": int(re.search(r"Ran (\d+) tests", log).group(1)),
        "current_integration_result": "PASS" if tests.returncode == 0 else "FAIL",
        "test_modules": SUITE, "noninterference": rows, "b1_summary": value["core"]["summary"],
        "b1_manifest": manifest, "source_network_fetches": 0, "fallback_used": False,
        "production_mutations": {"live_state": 0, "STATE_LATEST": 0, "Portfolio": 0, "Ledger": 0},
        "historical_pr30_replay": "SEPARATE_PINNED_HEAD_JOB_NOT_RUN_BY_THIS_SCRIPT",
        "unexecuted": ["whole_repository_suite", "production_warmup", "source_fetch", "scheduler", "Run-5", "old_plan_resume"],
        "historical_pit_readiness": "BLOCKED"}
    put(output, "RATE_EPS_B1_NONINTERFERENCE_VERIFICATION.json", result)
    print(json.dumps({k: result[k] for k in ("base_sha", "head_sha", "current_integration_test_count", "current_integration_result", "production_mutations")}, indent=2))
    return tests.returncode


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    sys.exit(verify(args.output_dir, args.expected_head, args.expected_base))

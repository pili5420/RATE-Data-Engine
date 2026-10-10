"""Exact-base/head Phase A verification; synthetic namespaces, zero live I/O."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_public_official_partial_valid import OLD_MODULES, extract, git, test_run, write, child

BASE = "b1d4376c1e774bf09b16bde619a352cc9d48dcc2"
ALLOWED = {
    ".github/workflows/rate_production_0730_scheduler.yml", ".github/workflows/rate_production_1930_scheduler.yml",
    ".github/workflows/rate_public_official_partial_valid_ci.yml",
    "config/RATE_FULL_MARKET_ROTATION_CONTRACT_V1.json", "docs/RATE_PR24_COMPATIBILITY_PHASE_A.md",
    "scripts/build_phase2_production_source.py", "scripts/run_full_market_rotation.py", "scripts/run_phase2_production.py",
    "scripts/build_production_source_bundle_from_official.py", "scripts/publish_production_source_bundle_latest.py",
    "scripts/publish_production_state_latest.py", "scripts/resolve_production_runtime_context.py",
    "scripts/verify_phase2_compatibility.py", "src/full_market_materialization.py", "src/full_market_rotation.py",
    "src/phase2_production.py", "tests/test_full_market_materialization.py", "tests/test_full_market_rotation.py",
    "tests/test_phase2_production.py", "tests/test_phase2_compatibility.py",
}
GROUPS = {
    "existing_131": (OLD_MODULES, 131),
    "pr42_56": (["test_public_official_partial_valid", "test_partial_to_evening_acceptance"], 56),
    "report_soak_48": (["test_report_production_soak"], 48),
    "scheduler_lock_8": (["test_cer081_scheduler_lock_validation"], 8),
    "phase2_43": (["test_phase2_production", "test_full_market_rotation", "test_full_market_materialization"], 43),
    "compatibility_new_9": (["test_phase2_compatibility"], 9),
}


def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
        raise RuntimeError("PHASE_A_REAL_NETWORK_FORBIDDEN:" + event)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test-child":
        sys.addaudithook(deny_network)
        return child(Path(sys.argv[2]), sys.argv[3:])
    if len(sys.argv) > 1 and sys.argv[1] == "--proof-child":
        sys.addaudithook(deny_network)
        from tests.test_phase2_compatibility import chain_proof
        from scripts.verify_public_official_partial_valid import chain_proof as legacy_chain
        from scripts.verify_report_production_soak import proof as separation_proof
        output = Path(sys.argv[2])
        chain_proof(output / "phase2")
        legacy_chain(output / "legacy")
        (output / "soak").mkdir()
        separation_proof(output / "soak")
        return 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    if output.exists():
        raise RuntimeError("VERIFICATION_OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    if args.expected_base != BASE or git("rev-parse", "HEAD") != args.expected_head or git("merge-base", BASE, "HEAD") != BASE:
        raise RuntimeError("EXACT_BASE_HEAD_MISMATCH")
    changed = git("diff", "--name-only", BASE, args.expected_head).splitlines()
    if not changed or set(changed) - ALLOWED or git("status", "--porcelain"):
        raise RuntimeError("CHANGE_SCOPE_OR_CLEAN_WORKTREE_VIOLATION")
    def tree(revision):
        return {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2] for line in git("ls-tree", "-r", revision).splitlines()}
    old_tree, new_tree = tree(BASE), tree(args.expected_head)
    protected = {path: digest for path, digest in old_tree.items() if path not in ALLOWED}
    if any(new_tree.get(path) != digest for path, digest in protected.items()):
        raise RuntimeError("PROTECTED_FILE_CHANGED")
    write(output / "protected-files.json", protected)
    results = {}
    with tempfile.TemporaryDirectory(prefix="p24-", dir=ROOT.parent) as temporary:
        mirror = Path(temporary) / "head"
        extract(args.expected_head, mirror)
        (mirror / ".git").write_text("gitdir: " + git("rev-parse", "--absolute-git-dir") + "\n", encoding="utf-8")
        for name, (modules, count) in GROUPS.items():
            command = [sys.executable, "-B", str(mirror / "scripts/verify_phase2_compatibility.py"), "--test-child", str(output / (name + ".json")), *modules]
            cold = subprocess.run(command, cwd=mirror, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
            (output / (name + ".log")).write_text(cold.stdout + cold.stderr, encoding="utf-8")
            result = json.loads((output / (name + ".json")).read_text(encoding="utf-8"))
            result["exact_count_pass"] = result["tests_run"] == count
            result["exit_code"] = cold.returncode
            results[name] = result
            print(json.dumps({"group": name, "tests": result["tests_run"], "passed": result["passed"], "all_pass": result["all_pass"]}), flush=True)
        cold = subprocess.run([sys.executable, "-B", str(mirror / "scripts/verify_phase2_compatibility.py"), "--proof-child", str(output / "proof")],
            cwd=mirror, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
        (output / "proof.log").write_text(cold.stdout + cold.stderr, encoding="utf-8")
    passed = all(r["all_pass"] and r["exact_count_pass"] and r["exit_code"] == 0 for r in results.values()) and cold.returncode == 0
    package = {"base_sha": BASE, "head_sha": args.expected_head, "changed_files": changed, "results": results,
        "proof_exit_code": cold.returncode, "protected_files_unchanged": len(protected),
        "scope": "CODE_INTEGRATION_SYNTHETIC_ONLY", "real_financial_requests": 0, "warmup_dispatches": 0,
        "production_publications": 0, "real_state_portfolio_ledger_mutations": 0, "rebaseline": False,
        "external_dependency": "BLOCKED_EXTERNAL", "fallback_allowed": False, "full_production_acceptance": "NOT_ALLOWED",
        "validation_status": "PASS" if passed else "FAIL"}
    write(output / "VERIFICATION_PACKAGE.json", package)
    print(json.dumps({k: v for k, v in package.items() if k != "results"}))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

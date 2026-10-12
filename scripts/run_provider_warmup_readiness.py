"""Offline source-owner replay and isolated calculation. No acquisition entry point."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def source_child(args):
    # Load the ORIGINAL producer, whose request plan pins its absolute parser path.
    sys.path.insert(0, args.producer_checkout)
    def deny(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise RuntimeError("PHASE_I_SOURCE_REPLAY_NETWORK_FORBIDDEN")
        if event == "open" and ((values[1] and any(c in values[1] for c in "wax+")) or
                values[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
            raise RuntimeError("PHASE_I_SOURCE_REPLAY_WRITE_FORBIDDEN")
        if event in {"os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.chmod", "os.utime", "os.link", "os.symlink", "os.truncate"}:
            raise RuntimeError("PHASE_I_SOURCE_REPLAY_WRITE_FORBIDDEN")
    sys.addaudithook(deny)
    from src.provider_financial_feature_inputs import replay_binding
    from src.provider_financial_features import consume
    result = consume(args.feature_dir, args.expected_manifest_sha256, source_replayer=replay_binding,
        expected_code_binding={"base_sha": args.producer_base, "head_sha": args.producer_head})
    print(json.dumps(result, allow_nan=False))
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-child", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--feature-dir", required=True)
    p.add_argument("--expected-manifest-sha256", required=True)
    p.add_argument("--producer-checkout", required=True)
    p.add_argument("--producer-base", required=True)
    p.add_argument("--producer-head", required=True)
    p.add_argument("--universe-evidence")
    p.add_argument("--universe-sha256")
    p.add_argument("--universe-commit")
    p.add_argument("--protected-manifest")
    p.add_argument("--protected-manifest-sha256")
    p.add_argument("--expected-base")
    p.add_argument("--expected-head")
    p.add_argument("--output-dir")
    p.add_argument("--cold-read")
    p.add_argument("--expected-result-sha256")
    args = p.parse_args()
    if args.source_child:
        return source_child(args)
    sys.path.insert(0, str(ROOT))
    from scripts.provider_warmup_readiness import (CONTRACT, decide, envelope, cold_verify,
        external_output, fingerprint, isolation_guard, pinned, source_evidence, verify_inventory)
    from src.eps_duration_facts.model import require
    from src.provider_eps_candidate import _canonical
    from src.provider_eps_coverage import load_universe
    from src.provider_eps_metadata import read_metadata
    def git(checkout, *parameters):
        return subprocess.check_output(["git", *parameters], cwd=checkout, text=True).strip()
    require(all(getattr(args, k) for k in ("universe_evidence", "universe_sha256", "universe_commit", "protected_manifest",
        "protected_manifest_sha256", "expected_base", "expected_head", "output_dir")), "PHASE_I_REQUIRED_BINDING_MISSING")
    execution = {"base_sha": args.expected_base, "head_sha": args.expected_head}
    require(args.expected_base == CONTRACT["base_sha"] and git(ROOT, "rev-parse", "HEAD") == args.expected_head and
        git(ROOT, "merge-base", args.expected_base, args.expected_head) == args.expected_base and
        not git(ROOT, "status", "--porcelain"), "PHASE_I_EXACT_HEAD_OR_WORKTREE_MISMATCH")
    require(git(args.producer_checkout, "rev-parse", "HEAD") == args.producer_head and
        git(args.producer_checkout, "merge-base", args.producer_base, args.producer_head) == args.producer_base and
        not git(args.producer_checkout, "status", "--porcelain"), "PHASE_I_ORIGINAL_PRODUCER_MISMATCH")
    source_roots = [args.feature_dir, args.producer_checkout, args.universe_evidence, str(Path(args.protected_manifest).parent)]
    out = external_output(args.output_dir, source_roots)
    pins = pinned(args.protected_manifest, args.protected_manifest_sha256)
    require(isinstance(pins, dict) and pins, "PHASE_I_EMPTY_PROTECTED_INVENTORY")
    for name in (args.protected_manifest, args.universe_evidence, str(Path(args.feature_dir) / "FEATURE_MANIFEST.json"),
                 str(Path(args.feature_dir) / "PROVIDER_FINANCIAL_FEATURES_V1.json")):
        pins[name] = fingerprint(name)
    for checkout in (ROOT, Path(args.producer_checkout)):
        for name in git(checkout, "ls-files").splitlines():
            path = str(checkout / name)
            pins[path] = fingerprint(path)
    verify_inventory(pins)
    manifest = pinned(Path(args.feature_dir) / "FEATURE_MANIFEST.json", args.expected_manifest_sha256)
    require(set(manifest["files"]) == {"PROVIDER_FINANCIAL_FEATURES_V1.json"}, "PHASE_I_FEATURE_PATH_INVALID")
    package_path = Path(args.feature_dir) / "PROVIDER_FINANCIAL_FEATURES_V1.json"
    require(fingerprint(package_path) == manifest["files"][package_path.name], "PHASE_I_FEATURE_TAMPER")
    package = read_metadata(package_path.read_bytes())
    source_roots.extend(filter(None, (package["core"]["inputs"]["source_binding"].get("coverage_root"),
        package["core"]["inputs"]["source_binding"].get("snapshot_root"))))
    external_output(out, source_roots)
    out.mkdir(parents=True, exist_ok=False)
    sys.addaudithook(isolation_guard(out))
    def write(name, value):
        (out / name).write_bytes(_canonical(value) + b"\n")
    write("INPUT_BINDINGS.json", vars(args))
    write("input-hashes-before.json", pins)
    write("INCOMPLETE_UNTIL_VERIFIED.json", {"usable_checkpoint": False, "reason": "ALL_GATES_AND_COLD_READ_REQUIRED"})
    cmd = [sys.executable, "-B", str(Path(__file__).resolve()), "--source-child", "--feature-dir", args.feature_dir,
        "--expected-manifest-sha256", args.expected_manifest_sha256, "--producer-checkout", args.producer_checkout,
        "--producer-base", args.producer_base, "--producer-head", args.producer_head]
    run = subprocess.run(cmd, cwd=args.producer_checkout, capture_output=True, text=True,
        encoding="utf-8", env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    (out / "source-replay.log").write_text(run.stdout + run.stderr, encoding="utf-8")
    require(run.returncode == 0, "PHASE_I_ORIGINAL_PRODUCER_REPLAY_FAILED")
    source = json.loads(run.stdout)
    require(source["status"] == "PASS" and source["source_replay"] == "PASS" and
        source["content_sha256"] == package["content_sha256"], "PHASE_I_SOURCE_REPLAY_BINDING_MISMATCH")
    write("ORIGINAL_PRODUCER_SOURCE_REPLAY.json", source)
    universe = load_universe(args.universe_evidence, args.universe_sha256, args.universe_commit)
    now = datetime.now(timezone.utc).isoformat()
    evidence, source_pins = source_evidence(package["core"]["inputs"], now)
    pins.update(source_pins)
    write("SOURCE_RECORD_EVIDENCE.json", evidence)
    if args.cold_read:
        require(args.expected_result_sha256, "PHASE_I_COLD_READ_PIN_REQUIRED")
        proof = cold_verify(args.cold_read, args.expected_result_sha256, package, universe, evidence, execution, now)
        write("COLD_READ_VERIFICATION.json", proof)
    else:
        core = decide(package, universe, evidence, execution, now)
        write("PHASE_I_READINESS.json", envelope(core, now, datetime.now(timezone.utc).isoformat()))
        write("SUMMARY.json", {"counts": core["gate_i_3_warmup_sandbox"]["summary"],
            "provider_matrix": core["gate_i_1_provider_qualification"], "readiness": core["gate_i_4_production_readiness"],
            "historical_pit": core["gate_i_2_historical_pit"], "boundaries": core["boundaries"]})
    verify_inventory(pins)
    write("input-hashes-after.json", pins)
    write("NON_INTERFERENCE.json", {"checked_files": len(pins), "modified": [], "deleted": [],
        "existing_sources_and_all_tracked_blobs_unchanged": True,
        "write_scope": "ONLY_FRESH_EXTERNAL_OUTPUT_ENFORCED_BY_AUDIT_HOOK", "financial_requests": 0,
        "decision_state_mutations": 0, "portfolio_mutations": 0, "ledger_mutations": 0,
        "ranking_calls": 0, "formal_warmup_calls": 0, "scheduler_calls": 0, "first_refresh_calls": 0})
    write("EXECUTION_COMPLETE.json", {"source_replay": "PASS", "source_hashes": "PASS",
        "scope": "OFFLINE_READINESS_ONLY_NOT_ACTIVATION", "cold_read": bool(args.cold_read)})
    print(json.dumps({"status": "PASS", "output": str(out), "checked_files": len(pins)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

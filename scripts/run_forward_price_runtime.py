"""Bounded candidate price runtime; never enroll a Shadow snapshot or schedule."""
import argparse
from pathlib import Path
import subprocess
import sys
import json
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.eps_duration_facts.raw import sha256
from src.provider_financial_features import instant
from src.provider_forward_price_runtime import prepare, acquire, validate_plan, pinned, baseline_input, put, validate_runtime_dispatches
from src.provider_shadow_forward import KINDS, heads, replay_chain, verify
from scripts.verify_eps_b1_noninterference import git


def old_files(root):
    return {str(p): sha256(p.read_bytes()) for p in Path(root).rglob("*") if p.is_file() and p != Path(root) / ".scan.lock"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("prepare", "acquire", "apply", "verify"), required=True)
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--runtime-root", required=True)
    p.add_argument("--ledger-root")
    p.add_argument("--baseline")
    p.add_argument("--baseline-sha256")
    p.add_argument("--checkpoint")
    p.add_argument("--checkpoint-sha256")
    p.add_argument("--candidate-date")
    p.add_argument("--plan-sha256")
    p.add_argument("--prior-price-manifest")
    p.add_argument("--prior-price-manifest-sha256")
    p.add_argument("--output-dir")
    args = p.parse_args()
    require(git("rev-parse", "HEAD").decode().strip() == args.expected_head and not git("status", "--porcelain", "--untracked-files=all"), "RUNTIME_EXACT_CLEAN_EXECUTION_REQUIRED")
    git("merge-base", "--is-ancestor", args.expected_base, args.expected_head)
    root = Path(args.runtime_root).resolve()
    binding = {"base_sha": args.expected_base, "head_sha": args.expected_head}
    if args.mode == "prepare":
        require(all((args.ledger_root, args.baseline, args.baseline_sha256, args.checkpoint, args.checkpoint_sha256, args.candidate_date)), "RUNTIME_PINS_REQUIRED")
        prior = {"manifest_path": args.prior_price_manifest, "manifest_sha256": args.prior_price_manifest_sha256} if args.prior_price_manifest else None
        pin = prepare(root, {"path": args.baseline, "sha256": args.baseline_sha256},
            {"path": args.checkpoint, "sha256": args.checkpoint_sha256}, args.ledger_root, binding, args.candidate_date, prior_pin=prior)
        print(json.dumps({"status": "PASS", "plan_pin": pin, "new_requests": 0}))
        return
    require(args.plan_sha256, "RUNTIME_PLAN_PIN_REQUIRED")
    plan_pin = {"path": str(root / "REQUEST_PLAN.json"), "sha256": args.plan_sha256}
    plan = validate_plan(root, plan_pin)
    require(plan["execution_binding"] == binding, "RUNTIME_EXECUTION_BINDING_MISMATCH")
    if args.mode == "acquire":
        pin = acquire(root, plan_pin)
        print(json.dumps({"status": "PASS", "price_pin": pin, "new_shadow_snapshots": 0}))
        return
    require(args.output_dir, "RUNTIME_NEW_REPORT_REQUIRED")
    output = Path(args.output_dir).resolve()
    require(not output.exists() and not output.is_relative_to(ROOT) and not output.is_relative_to(Path(plan["ledger_root"])), "RUNTIME_NEW_EXTERNAL_REPORT_REQUIRED")
    result = pinned(root / "ACQUISITION_RESULT.json", sha256((root / "ACQUISITION_RESULT.json").read_bytes()))
    require(result["status"] == "PASS", "RUNTIME_ARCHIVE_INCOMPLETE")
    validate_runtime_dispatches(root, plan)
    snapshot = pinned(plan["baseline_pin"]["path"], plan["baseline_pin"]["sha256"])
    ledger_root = Path(plan["ledger_root"])
    before = old_files(ledger_root)
    # A repeat apply needs the most recent externally pinned checkpoint, not stale heads.
    cp_pin = {"path": args.checkpoint, "sha256": args.checkpoint_sha256} if args.checkpoint else plan["checkpoint_pin"]
    baseline_input(plan["baseline_pin"], cp_pin, ledger_root)
    command = [sys.executable, "-B", str(ROOT / "scripts/run_provider_shadow_forward.py"),
        "--expected-base", args.expected_base, "--expected-head", args.expected_head,
        "--mode", "evaluate" if args.mode == "apply" else "verify", "--ledger-root", str(ledger_root),
        "--checkpoint", cp_pin["path"], "--checkpoint-sha256", cp_pin["sha256"], "--output-dir", str(output)]
    if args.mode == "apply":
        command += ["--snapshot-id", snapshot["shadow_snapshot_id"], "--price-manifest", result["price_pin"]["manifest_path"],
            "--price-manifest-sha256", result["price_pin"]["manifest_sha256"]]
    execution = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if execution.returncode:
        put(root / ("APPLY_DEFECT_" + instant().replace(":", "-") + ".json"), {"status": "FAIL_CLOSED",
            "exit_code": execution.returncode, "command_without_credentials": command, "stdout": execution.stdout, "traceback": execution.stderr})
        raise RuntimeError("RUNTIME_FORWARD_CONSUMER_FAILED")
    require(all(Path(path).is_file() and sha256(Path(path).read_bytes()) == digest for path, digest in before.items()), "RUNTIME_OLD_LEDGER_FILE_CHANGED")
    require(len(replay_chain(ledger_root, KINDS[0])) == 1 and replay_chain(ledger_root, KINDS[0])[0]["payload"] == snapshot,
        "RUNTIME_SNAPSHOT_CREATED_OR_REWRITTEN")
    consumer = json.loads(execution.stdout)
    cp = pinned(consumer["checkpoint"], consumer["checkpoint_sha256"])
    verify(ledger_root, cp["heads"])
    counts = {}
    for h in (5, 20, 60):
        rows = next(e["payload"]["returns"] for e in reversed(replay_chain(ledger_root, KINDS[1])) if e["payload"]["horizon"] == h)
        counts[str(h)] = {status: sum(r["status"] == status for r in rows) for status in ("PENDING", "FINALIZED", "FAIL_CLOSED")}
        counts[str(h)]["entry_available"] = sum(r["entry_price"] is not None for r in rows)
        counts[str(h)]["entry_sessions"] = {m: sorted({r["entry_price_date"] for r in rows if r["market"] == m and r["entry_price_date"]}) for m in ("TWSE", "TPEX")}
    proof = {"status": "PASS", "mode": args.mode, "runtime_execution": binding, "original_baseline_execution": snapshot["execution_binding"],
        "new_shadow_snapshots": 0, "snapshot_id": snapshot["shadow_snapshot_id"], "old_files_unchanged": before,
        "legal_new_files": old_files(ledger_root).keys() - before.keys(), "command_without_credentials": command,
        "consumer": consumer, "return_counts": counts, "updated_heads": cp["heads"], "price_requests_this_apply": 0,
        "decision_eligible": False, "production_eligible": False, "historical_pit_status": "UNPROVEN"}
    proof["legal_new_files"] = sorted(proof["legal_new_files"])
    put(output / "RUNTIME_UPDATE_PROOF.json", proof)
    print(json.dumps({k: v for k, v in proof.items() if k not in ("old_files_unchanged", "command_without_credentials")}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)

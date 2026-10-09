"""Offline baseline, append-only return update and independently pinned replay."""
import argparse
from pathlib import Path
import socket
import sys
import json
import subprocess
import os

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.eps_duration_facts.raw import sha256
from src.provider_eps_metadata import read_metadata
from src.provider_financial_features import instant
from src.provider_shadow_forward import (SPEC, KINDS, baseline, create_baseline, heads, replay_chain, checkpoint, update, hash_object)
from scripts.verify_eps_b1_noninterference import git
SOURCE_EXECUTIONS = []


def read_pinned(path, expected):
    data = Path(path).read_bytes()
    require(sha256(data) == expected, "FORWARD_EXTERNAL_PIN_TAMPERED")
    return read_metadata(data)


def replay_source(pin):
    producer = Path(pin["producer_checkout"]).resolve()
    binding = pin["producer_binding"]
    require(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=producer).decode().strip() == binding["head_sha"] and
        not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=producer), "FORWARD_ORIGINAL_PRODUCER_NOT_EXACT_CLEAN")
    script = producer / "scripts/build_provider_fundamental_shadow.py"
    require(sha256(script.read_bytes()) == pin["producer_consumer_sha256"], "FORWARD_SOURCE_CONSUMER_TAMPERED")
    command = [sys.executable, "-B", str(script), "--expected-base", binding["base_sha"], "--expected-head", binding["head_sha"],
        "--consume", pin["shadow_directory"], "--expected-manifest-sha256", pin["shadow_manifest_sha256"]]
    process = subprocess.run(command, cwd=producer, capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"})
    require(process.returncode == 0, "FORWARD_ORIGINAL_SOURCE_REPLAY_FAILED:" + process.stderr)
    result = json.loads(process.stdout)
    require(result["status"] == "PASS", "FORWARD_ORIGINAL_SOURCE_REPLAY_FAILED")
    SOURCE_EXECUTIONS.append({"command_without_credentials": command, "exit_code": process.returncode, "result": result,
        "producer_identity_preserved": binding, "replayed_at": instant()})
    manifest = read_pinned(Path(pin["shadow_directory"]) / "SHADOW_MANIFEST.json", pin["shadow_manifest_sha256"])
    require(sha256((Path(pin["shadow_directory"]) / "PROVIDER_FUNDAMENTAL_SHADOW_V1.json").read_bytes()) == manifest["files"]["PROVIDER_FUNDAMENTAL_SHADOW_V1.json"]["sha256"], "FORWARD_SHADOW_RAW_CHANGED")
    shadow = read_metadata((Path(pin["shadow_directory"]) / "PROVIDER_FUNDAMENTAL_SHADOW_V1.json").read_bytes())
    require(shadow["content_sha256"] == pin["shadow_content_sha256"] and shadow["core"]["feature_content_sha256"] == pin["feature_content_sha256"], "FORWARD_SOURCE_CONTENT_IDENTITY")
    companies = shadow["core"]["companies"]
    require(len(companies) == 1978 and sum(c["market"] == "TWSE" for c in companies) == 1085 and sum(c["market"] == "TPEX" for c in companies) == 893, "FORWARD_REAL_UNIVERSE_IDENTITY")
    return shadow


def write_new(root, name, value):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False).encode()
    path = root / name
    if path.exists():
        require(path.read_bytes() == data, "FORWARD_IMMUTABLE_REPORT_CONFLICT")
    else:
        with path.open("xb") as stream:
            stream.write(data)
    return str(path), sha256(data)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", required=True, choices=("baseline", "verify", "evaluate"))
    p.add_argument("--expected-base", required=True)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--ledger-root", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--source-pin")
    p.add_argument("--source-pin-sha256")
    p.add_argument("--checkpoint")
    p.add_argument("--checkpoint-sha256")
    p.add_argument("--price-manifest")
    p.add_argument("--price-manifest-sha256")
    p.add_argument("--snapshot-id")
    args = p.parse_args()
    require(git("rev-parse", "HEAD").decode().strip() == args.expected_head and not git("status", "--porcelain", "--untracked-files=all"), "FORWARD_EXACT_HEAD_CLEAN_REQUIRED")
    git("merge-base", "--is-ancestor", args.expected_base, args.expected_head)
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("FORWARD_OFFLINE_ONLY"))
    root, output = Path(args.ledger_root).resolve(), Path(args.output_dir).resolve()
    require(not output.exists() and output != root and not output.is_relative_to(ROOT), "FORWARD_NEW_REPORT_DIRECTORY_REQUIRED")
    expected = {k: None for k in KINDS}
    if root.exists():
        require(args.checkpoint and args.checkpoint_sha256, "FORWARD_TRUSTED_CHECKPOINT_REQUIRED")
        expected = read_pinned(args.checkpoint, args.checkpoint_sha256)["heads"]
    if args.mode == "baseline":
        require(args.source_pin and args.source_pin_sha256, "FORWARD_TRUSTED_SHADOW_PIN_REQUIRED")
        pin = read_pinned(args.source_pin, args.source_pin_sha256)
        shadow = replay_source(pin)
        saved = [e["payload"] for e in replay_chain(root, KINDS[0]) if e["payload"]["shadow_package_sha256"] == shadow["package_sha256"]]
        at = instant()
        snapshot = saved[0] if saved else baseline(shadow, sealed_at=at, effective_at=at,
            execution_binding={"base_sha": args.expected_base, "head_sha": args.expected_head}, source_pin=pin)
        create_baseline(root, snapshot, expected)
    else:
        for event in replay_chain(root, KINDS[0]):
            snapshot = event["payload"]
            shadow = replay_source(snapshot["source_pin"])
            require(snapshot == baseline(shadow, sealed_at=snapshot["sealed_at"], effective_at=snapshot["contract_effective_at"],
                execution_binding=snapshot["execution_binding"], source_pin=snapshot["source_pin"], require_fresh=False), "FORWARD_BASELINE_SOURCE_RECONSTRUCTION_MISMATCH")
        if args.mode == "evaluate":
            require(args.snapshot_id and args.price_manifest and args.price_manifest_sha256, "FORWARD_PRICE_PIN_REQUIRED")
            update(root, expected, args.snapshot_id, {"manifest_path": args.price_manifest, "manifest_sha256": args.price_manifest_sha256}, as_of=instant())
        else:
            from src.provider_shadow_forward import verify
            verify(root, expected)
    result = checkpoint(root, heads(root))
    path, digest = write_new(output, "CHECKPOINT.json", result)
    source_counts = [{"shadow_snapshot_id": e["payload"]["shadow_snapshot_id"],
        "scored": sum(r["score"] is not None for r in e["payload"]["companies"]), "unscored": sum(r["score"] is None for r in e["payload"]["companies"])} for e in replay_chain(root, KINDS[0])]
    summary = {"status": "PASS", "mode": args.mode, "base_sha": args.expected_base, "head_sha": args.expected_head,
        "ledger_root": str(root), "checkpoint": path, "checkpoint_sha256": digest, "snapshot_count": result["snapshot_count"],
        "populations": source_counts, "gates": result["gates"], "next_evaluation_at": result["next_evaluation_at"],
        "source_replay": "PASS", "financial_requests": 0, "price_requests": 0, "formal_scoring_calls": 0,
        "forward_validation_allowed": True, "decision_eligible": False, "production_eligible": False}
    write_new(output, "VERIFICATION.json", summary)
    write_new(output, "SOURCE_REPLAY_EXECUTIONS.json", SOURCE_EXECUTIONS)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()

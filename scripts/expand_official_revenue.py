"""Explicit prepare/acquire/offline-build modes for candidate revenue refresh."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.eps_duration_facts.model import require
from src.eps_duration_facts.raw import sha256
from src.provider_eps_metadata import read_metadata
from src.provider_financial_features import compute_core, seal, export_package, consume, instant
from src.provider_financial_feature_inputs import replay_binding
from src.provider_fundamental_shadow_inputs import source_pin, load_delivery
from src.provider_revenue_snapshot import prepare, acquire, replay_snapshot, put


def offline(*args, **kwargs):
    raise RuntimeError("REVENUE_OFFLINE_MODE_NETWORK_FORBIDDEN")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "acquire", "build", "consume"), required=True)
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--delivery-index")
    parser.add_argument("--expected-delivery-index-sha256")
    parser.add_argument("--expected-delivery-inventory-sha256")
    parser.add_argument("--snapshot-root")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--expected-snapshot-manifest-sha256")
    parser.add_argument("--expected-feature-manifest-sha256")
    args = parser.parse_args()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    require(head == args.expected_head and not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT), "REVENUE_EXACT_HEAD_AND_CLEAN_REQUIRED")
    subprocess.run(["git", "merge-base", "--is-ancestor", args.expected_base, head], cwd=ROOT, check=True)
    binding = {"base_sha": args.expected_base, "head_sha": head}
    if args.mode != "acquire":
        socket.socket.connect = socket.socket.connect_ex = socket.create_connection = offline
    if args.mode == "prepare":
        require(all((args.delivery_index, args.expected_delivery_index_sha256, args.expected_delivery_inventory_sha256, args.output_dir)), "REVENUE_PREPARE_TRUST_ANCHORS_REQUIRED")
        pin = source_pin(args.delivery_index, args.expected_delivery_index_sha256, args.expected_delivery_inventory_sha256)
        features = load_delivery(pin)
        digest = prepare(features, pin, binding, args.output_dir)
        result = {"status": "REQUEST_PLAN_PERSISTED_NO_REQUESTS", "plan_sha256": digest,
            "plan": read_metadata((Path(args.output_dir) / "request-plan.json").read_bytes())}
    elif args.mode == "acquire":
        require(args.snapshot_root and args.expected_plan_sha256, "REVENUE_ACQUIRE_PLAN_PIN_REQUIRED")
        plan_body = (Path(args.snapshot_root) / "request-plan.json").read_bytes()
        require(sha256(plan_body) == args.expected_plan_sha256, "REVENUE_REQUEST_PLAN_TAMPERED")
        plan = read_metadata(plan_body)
        require(plan["code_binding"] == binding, "REVENUE_REQUEST_PLAN_EXECUTION_MISMATCH")
        features = load_delivery(plan["old_feature_pin"])
        digest, acquired = acquire(args.snapshot_root, args.expected_plan_sha256, features)
        result = {"status": acquired["snapshot_status"], "snapshot_manifest_sha256": digest, "acquisition": acquired}
    elif args.mode == "build":
        require(args.snapshot_root and args.expected_snapshot_manifest_sha256 and args.output_dir, "REVENUE_BUILD_SNAPSHOT_PIN_REQUIRED")
        inputs, diagnostics = replay_snapshot(args.snapshot_root, args.expected_snapshot_manifest_sha256)
        plan = read_metadata((Path(args.snapshot_root) / "request-plan.json").read_bytes())
        require(plan["code_binding"] == binding, "REVENUE_BUILD_PLAN_EXECUTION_MISMATCH")
        package = seal(compute_core(inputs), code_binding=binding)
        export_package(package, args.output_dir)
        directory = Path(args.output_dir)
        put(directory / "REVENUE_SELECTION_AND_DIFFERENCES.json", diagnostics)
        result = {"status": "BUILT_REQUIRES_COLD_CONSUMER", "summary": package["core"]["summary"],
            "content_sha256": package["content_sha256"], "manifest_sha256": sha256((directory / "FEATURE_MANIFEST.json").read_bytes())}
    else:
        require(args.output_dir and args.expected_feature_manifest_sha256, "REVENUE_CONSUMER_PIN_REQUIRED")
        result = consume(args.output_dir, args.expected_feature_manifest_sha256, source_replayer=replay_binding, expected_code_binding=binding)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

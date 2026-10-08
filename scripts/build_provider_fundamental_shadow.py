"""Offline build or independent cold-consume of shadow-only financial results."""
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
from src.provider_fundamental_shadow import compute_core, seal, validate, export, consume
from src.provider_fundamental_shadow_inputs import source_pin, load_delivery


def no_network(*args, **kwargs):
    raise RuntimeError("PROVIDER_SHADOW_OFFLINE_NETWORK_FORBIDDEN")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery-index")
    parser.add_argument("--expected-delivery-index-sha256")
    parser.add_argument("--expected-delivery-inventory-sha256")
    parser.add_argument("--output-dir")
    parser.add_argument("--consume")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--as-of")
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = no_network
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    require(head == args.expected_head, "SHADOW_EXACT_HEAD_REQUIRED")
    subprocess.run(["git", "merge-base", "--is-ancestor", args.expected_base, head], cwd=ROOT, check=True)
    require(not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT), "SHADOW_WORKTREE_NOT_CLEAN")
    binding = {"base_sha": args.expected_base, "head_sha": head}
    if args.consume:
        require(args.expected_manifest_sha256, "SHADOW_CONSUMER_PIN_REQUIRED")
        result = consume(args.consume, args.expected_manifest_sha256, load_delivery,
            as_of=args.as_of, expected_code_binding=binding)
    else:
        require(all((args.delivery_index, args.expected_delivery_index_sha256,
            args.expected_delivery_inventory_sha256, args.output_dir)), "SHADOW_SOURCE_TRUST_ANCHORS_REQUIRED")
        pin = source_pin(args.delivery_index, args.expected_delivery_index_sha256, args.expected_delivery_inventory_sha256)
        features = load_delivery(pin)
        core = compute_core(features)
        package = seal(core, pin, code_binding=binding)
        validate(package, features)
        digest = export(package, args.output_dir)
        result = {"status": "BUILT_REQUIRES_INDEPENDENT_COLD_CONSUMER", "summary": core["summary"],
            "content_sha256": package["content_sha256"], "manifest_sha256": digest,
            "source_producer_binding": core["source_producer_binding"], "execution_code_binding": binding,
            "sensitivity_summary": core["sensitivity_summary"], "new_financial_requests": 0,
            "formal_scoring_calls": 0, "decision_eligible": False, "production_eligible": False}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

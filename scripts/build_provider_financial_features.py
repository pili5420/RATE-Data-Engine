"""Build or cold-consume independent features from sealed local evidence only."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.provider_financial_features import compute_core, seal, export_package, consume, instant
from src.provider_financial_feature_inputs import load_closeout, replay_binding
from src.eps_duration_facts.raw import sha256
from src.eps_duration_facts.model import require


def no_network(*args, **kwargs):
    raise RuntimeError("PROVIDER_FEATURES_OFFLINE_NETWORK_FORBIDDEN")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closeout-manifest")
    parser.add_argument("--closeout-manifest-sha256")
    parser.add_argument("--output-dir")
    parser.add_argument("--consume")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--as-of")
    parser.add_argument("--expected-base", required=True)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args()
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = no_network
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    require(head == args.expected_head, "FEATURE_EXECUTION_HEAD_MISMATCH")
    subprocess.run(["git", "merge-base", "--is-ancestor", args.expected_base, head], cwd=ROOT, check=True)
    require(not subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT), "FEATURE_WORKTREE_NOT_CLEAN")
    code_binding = {"base_sha": args.expected_base, "head_sha": head}
    if args.consume:
        if not args.expected_manifest_sha256:
            parser.error("--expected-manifest-sha256 is required for independent consumer")
        print(json.dumps(consume(args.consume, args.expected_manifest_sha256, as_of=args.as_of, source_replayer=replay_binding, expected_code_binding=code_binding), sort_keys=True))
        return
    if not all((args.closeout_manifest, args.closeout_manifest_sha256, args.output_dir)):
        parser.error("builder requires closeout manifest, exact SHA256 and new external output directory")
    inputs = load_closeout(args.closeout_manifest, args.closeout_manifest_sha256)
    core = compute_core(inputs)
    generated = instant()
    from src.provider_financial_features import hash_object
    assert hash_object(core) == hash_object(compute_core(inputs))
    package = seal(core, generated_at=generated, code_binding=code_binding)
    export_package(package, args.output_dir)
    path = Path(args.output_dir) / "FEATURE_MANIFEST.json"
    print(json.dumps({"status": "BUILT_REQUIRES_INDEPENDENT_COLD_CONSUMER", "summary": core["summary"],
        "content_sha256": package["content_sha256"], "manifest_sha256": sha256(path.read_bytes()), "new_financial_requests": 0}, sort_keys=True))


if __name__ == "__main__":
    main()

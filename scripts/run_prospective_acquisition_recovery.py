"""Offline-only known-failure resolution/replay. No acquisition operation exists."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import prospective_acquisition_recovery as recovery
from src.full_market_history import put_bytes
from src.provider_eps_candidate import _canonical
from src.provider_eps_metadata import read_metadata


def main():
    sys.addaudithook(recovery.offline_network_guard)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--operation", choices=("resolve", "replay"), required=True)
    p.add_argument("--binding", type=Path, required=True)
    p.add_argument("--binding-sha256", required=True)
    p.add_argument("--resolution-root", type=Path, required=True)
    p.add_argument("--intent-id")
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--checkpoint-sha256")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.operation == "resolve":
        pin = recovery.create_resolution(args.resolution_root, args.binding, args.binding_sha256,
            args.intent_id, recovery.now())
        result = {"binding_sha256": args.binding_sha256, "resolutions": {args.intent_id: pin},
            "resolution_root": str(args.resolution_root.resolve()), "financial_requests": 0,
            "new_acquisition_authorized": False}
    else:
        recovery.require(args.checkpoint is not None and args.checkpoint_sha256, "RECOVERY_TRUSTED_CHECKPOINT_REQUIRED")
        checkpoint = recovery.object_at({"path": str(args.checkpoint), "sha256": args.checkpoint_sha256})
        recovery.require(checkpoint["binding_sha256"] == args.binding_sha256 and
            checkpoint["resolution_root"] == str(args.resolution_root.resolve()), "RECOVERY_CHECKPOINT_MISMATCH")
        result = recovery.replay_recovered(args.resolution_root, args.binding, args.binding_sha256,
            checkpoint["resolutions"], recovery.now())
    recovery.require(not args.output.exists(), "RECOVERY_OUTPUT_OVERWRITE_FORBIDDEN")
    # Apply the same external-output guard as the original pipeline.
    _, _, _, engine = recovery.load_binding(args.binding, args.binding_sha256)
    engine.external(args.output.parent)
    put_bytes(args.output.parent, args.output.name, _canonical(result))
    print("recovery_output_sha256=" + recovery.sha256(args.output.read_bytes()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

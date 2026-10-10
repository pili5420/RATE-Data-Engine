"""Explicit offline opt-in; writes only a NEW eligibility overlay directory."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.fundamental_eligibility import build_overlay, digest, read_pinned, replay_references
from src.provider_eps_coverage import load_universe, save


def main():
    p = argparse.ArgumentParser()
    for name in ("input", "input-sha256", "universe-evidence", "universe-sha256", "universe-commit",
                 "context", "context-sha256", "output-dir"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--previous-overlay")
    p.add_argument("--previous-sha256")
    args = p.parse_args()
    if bool(args.previous_overlay) != bool(args.previous_sha256):
        p.error("previous overlay requires its trusted file hash")
    output = Path(args.output_dir).resolve()
    if output.exists() or output.is_relative_to(ROOT):
        p.error("output directory must be new and external to the repository")
    bundle = read_pinned(args.input, args.input_sha256)
    universe = load_universe(args.universe_evidence, args.universe_sha256, args.universe_commit)
    context = read_pinned(args.context, args.context_sha256)
    previous = read_pinned(args.previous_overlay, args.previous_sha256) if args.previous_overlay else None
    references = replay_references(bundle)
    result = build_overlay(bundle, universe, expected_bundle_sha256=digest(bundle),
        expected_universe_sha256=digest(universe), context=context, previous=previous,
        generated_at=datetime.now(timezone.utc).isoformat())
    output.mkdir(parents=True, exist_ok=False)
    save(output / "ELIGIBILITY_OVERLAY.json", result)
    save(output / "INPUT_BINDINGS.json", {"input_file_sha256": args.input_sha256,
        "universe_file_sha256": args.universe_sha256, "context_file_sha256": args.context_sha256,
        "previous_file_sha256": args.previous_sha256, "replayed_references": references})
    print(result["snapshot_id"])


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline opt-in inventory only. No live state or network client."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.fundamental_eligibility import digest, read_pinned, replay_references
from src.eps_duration_facts.model import require
from src.provider_eps_coverage import load_universe, save
from scripts.warmup_inventory_acceptance import build_inventory, verify_inventory


def main():
    p = argparse.ArgumentParser()
    for name in ("projection", "projection-sha256", "universe-evidence", "universe-sha256", "universe-commit",
                 "source-manifest", "source-manifest-sha256", "output-dir"):
        p.add_argument("--" + name, required=True)
    for name in ("context", "context-sha256", "previous", "previous-sha256"):
        p.add_argument("--" + name)
    args = p.parse_args()
    if bool(args.context) != bool(args.context_sha256) or bool(args.previous) != bool(args.previous_sha256):
        p.error("optional evidence requires its independent trusted file hash")
    output = Path(args.output_dir).resolve()
    if output.exists() or output.is_relative_to(ROOT):
        p.error("output must be a new external inventory directory")
    projection = read_pinned(args.projection, args.projection_sha256)
    universe = load_universe(args.universe_evidence, args.universe_sha256, args.universe_commit)
    pins = read_pinned(args.source_manifest, args.source_manifest_sha256)
    require(isinstance(pins, dict) and bool(pins), "INVENTORY_TRANSITIVE_SOURCE_MANIFEST_REQUIRED")
    for path, pin in pins.items():
        require(isinstance(pin, dict) and set(pin) == {"bytes", "sha256"}
            and type(pin["bytes"]) is int and pin["bytes"] >= 0
            and Path(path).stat().st_size == pin["bytes"], "INVENTORY_SOURCE_BYTES_MISMATCH")
    replay_references({"rows": [{"inputs": {"transitive_sources": {"evidence_references": [
        {"path": path, "sha256": pin["sha256"], "json_locator": "$"} for path, pin in pins.items()]}}}]})
    context = read_pinned(args.context, args.context_sha256) if args.context else None
    previous = read_pinned(args.previous, args.previous_sha256) if args.previous else None
    result = build_inventory(projection, universe, expected_projection_sha256=digest(projection),
        expected_universe_sha256=digest(universe), generated_at=datetime.now(timezone.utc).isoformat(),
        context=context, previous=previous)
    verify_inventory(result)
    output.mkdir(parents=True, exist_ok=False)
    save(output / "WARMUP_INVENTORY.json", result)
    save(output / "INPUT_BINDINGS.json", {"projection_path": str(Path(args.projection).resolve()),
        "projection_file_sha256": args.projection_sha256, "universe_file_sha256": args.universe_sha256,
        "universe_commit": args.universe_commit, "context_file_sha256": args.context_sha256,
        "source_manifest_path": str(Path(args.source_manifest).resolve()),
        "source_manifest_file_sha256": args.source_manifest_sha256, "replayed_transitive_sources": len(pins),
        "previous_file_sha256": args.previous_sha256, "financial_requests": 0, "live_state_writes": 0})
    print(result["snapshot_id"])


if __name__ == "__main__":
    main()

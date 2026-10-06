"""Additive full-market source path, never the legacy rebaseline seed path."""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.cer074_acceptance import atomic_write_json
from src.full_market_materialization import materialize_full_market
from src.full_market_rotation import EXTERNAL_FEED
from src.phase2_production import (bind_input_material, bundle_from_material, latest_predecessor,
                                   main_authority, prepare_bundle_state, require_intraday_authority)
from src.production_live_state import require
from scripts.run_phase2_production import preflight_manifest


def build_phase2_bundle(*, trading_date, cadence, output, evidence_output, state_root, history_root):
    evidence = {"artifact": "RATE_PHASE2_OFFICIAL_SOURCE_INGESTION_EVIDENCE", "validation_status": "FAIL_CLOSED",
        "trading_date": trading_date, "cadence": cadence, "fallback_used": False,
        "live_state_mutation": 0, "production_state_latest_mutation": 0, "ranking": None, "blocked_dependencies": []}
    try:
        authority = main_authority()
        feed = None
        if cadence in {"09:30", "12:00"}:
            require_intraday_authority()
            path = os.getenv("RATE_AUTHORIZED_INTRADAY_FEED_PATH")
            require(path and Path(path).is_file(), EXTERNAL_FEED)
            feed = json.loads(Path(path).read_bytes())
        _, _, loaded = latest_predecessor(state_root, trading_date, cadence)
        previous = loaded["state"]
        if cadence == "19:30":
            catalogue, raw = materialize_full_market(trading_date, history_root)
        else:
            catalogue = previous["decision"]["catalogue"]
            raw = {"carried_state_id": previous["current_state_id"],
                   "carried_state_hash": previous["decision_payload_hash"], "intraday_feed": feed}
        material = bind_input_material(raw, catalogue, previous, trading_date=trading_date, cadence=cadence, authority=authority)
        bundle = bundle_from_material(material, catalogue, state_root)
        # All canonical and account gates precede publishing either LATEST pointer.
        state = prepare_bundle_state(bundle, state_root=state_root)
        atomic_write_json(Path(output), bundle)
        preflight_manifest(output, bundle, authority)
        evidence.update(validation_status="PASS", production_snapshot_id=bundle["production_snapshot_id"],
            input_snapshot_id=bundle["input_snapshot_id"], candidate_universe_count=len(bundle["decision_records"]),
            ranking_counts={key: len(bundle["ranking"][key]) for key in ("top50", "short_top30", "long_top30")},
            proposed_state_id=state["current_state_id"])
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
        evidence["blocking_reason"] = str(exc)
        if EXTERNAL_FEED in str(exc):
            evidence["blocked_dependencies"] = [EXTERNAL_FEED]
    atomic_write_json(Path(evidence_output), evidence)
    return evidence

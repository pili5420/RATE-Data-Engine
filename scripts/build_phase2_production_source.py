"""Additive full-market source path, never the legacy rebaseline seed path."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from src.cer074_acceptance import atomic_write_json
from src.full_market_materialization import materialize_full_market
from src.full_market_rotation import EXTERNAL_FEED
from src.intraday_phase2_admission import qualify_phase2_intraday_feed
from src.phase2_production import (bind_input_material, bundle_from_material, latest_predecessor,
                                   main_authority, prepare_bundle_state, require_intraday_authority)
from src.production_live_state import require
from src.p0_source_diagnostics import safe_reason
from scripts.run_phase2_production import preflight_manifest


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_reason(exc):
    return safe_reason(exc, "SOURCE_ACQUISITION_FAILED")


def build_phase2_bundle(*, trading_date, cadence, output, evidence_output, state_root, history_root):
    diagnostic_path = Path(evidence_output).with_name("RATE_P0_SOURCE_DIAGNOSTIC_EVIDENCE.json") if cadence == "19:30" else None
    evidence = {"artifact": "RATE_PHASE2_OFFICIAL_SOURCE_INGESTION_EVIDENCE", "validation_status": "FAIL_CLOSED",
        "trading_date": trading_date, "cadence": cadence, "fallback_used": False,
        "live_state_mutation": 0, "production_state_latest_mutation": 0, "ranking": None, "blocked_dependencies": [],
        "source_diagnostic_evidence_path": str(diagnostic_path) if diagnostic_path else None,
        "ingestion_started_at": _utc_now(),
        "ingestion_timestamp_source": "RUNTIME_CLOCK_AT_OFFICIAL_SOURCE_ENTRY",
        "publication_decision_at": None, "publication_decision": "NOT_REACHED",
        "publication_decision_scope": "SOURCE_BUNDLE_FILE",
        "publication_intent_at": None, "source_bundle_write_result": "NOT_ATTEMPTED",
        "final_observed_state": "NO_SOURCE_BUNDLE_WRITE"}
    try:
        authority = main_authority()
        feed = None
        intraday_admission = None
        if cadence in {"09:30", "12:00"}:
            require_intraday_authority()
            path = os.getenv("RATE_AUTHORIZED_INTRADAY_FEED_PATH")
            require(path and Path(path).is_file(), EXTERNAL_FEED)
            feed = json.loads(Path(path).read_bytes())
            intraday_admission = qualify_phase2_intraday_feed(
                feed, trading_date=trading_date, cadence=cadence
            )
        _, _, loaded = latest_predecessor(state_root, trading_date, cadence)
        previous = loaded["state"]
        if cadence == "19:30":
            catalogue, raw = materialize_full_market(trading_date, history_root, diagnostic_output=diagnostic_path)
        else:
            catalogue = previous["decision"]["catalogue"]
            raw = {"carried_state_id": previous["current_state_id"],
                   "carried_state_hash": previous["decision_payload_hash"], "intraday_feed": feed}
            if cadence in {"09:30", "12:00"}:
                raw["intraday_admission"] = intraday_admission
        material = bind_input_material(raw, catalogue, previous, trading_date=trading_date, cadence=cadence, authority=authority)
        bundle = bundle_from_material(material, catalogue, state_root)
        # All canonical and account gates precede publishing either LATEST pointer.
        state = prepare_bundle_state(bundle, state_root=state_root)
        evidence["publication_intent_at"] = _utc_now()
        atomic_write_json(Path(output), bundle)
        evidence["source_bundle_write_result"] = "PERSISTED"
        evidence["final_observed_state"] = "SOURCE_BUNDLE_FILE_WRITTEN"
        preflight_manifest(output, bundle, authority)
        evidence.update(validation_status="PASS", production_snapshot_id=bundle["production_snapshot_id"],
            input_snapshot_id=bundle["input_snapshot_id"], candidate_universe_count=len(bundle["decision_records"]),
            ranking_counts={key: len(bundle["ranking"][key]) for key in ("top50", "short_top30", "long_top30")},
            proposed_state_id=state["current_state_id"])
        evidence["publication_decision_at"] = _utc_now()
        evidence["publication_decision"] = "PUBLISH"
        evidence["final_observed_state"] = "SOURCE_BUNDLE_PREFLIGHT_PASS"
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as exc:
        evidence["blocking_reason"] = _safe_reason(exc)
        primary = getattr(exc, "primary_failure_reason", None)
        evidence["source_primary_failure_reason"] = safe_reason(primary, "SOURCE_ACQUISITION_FAILED") if primary is not None else None
        evidence["publication_decision_at"] = _utc_now()
        evidence["publication_decision"] = "BLOCK"
        if evidence["publication_intent_at"] is not None and evidence["source_bundle_write_result"] == "NOT_ATTEMPTED":
            evidence["source_bundle_write_result"] = "FAILED"
        if EXTERNAL_FEED in str(exc):
            evidence["blocked_dependencies"] = [EXTERNAL_FEED]
    try:
        atomic_write_json(Path(evidence_output), evidence)
    except (OSError, RuntimeError, ValueError, TypeError):
        raise RuntimeError("SOURCE_INGESTION_EVIDENCE_PERSISTENCE_FAILED") from None
    return evidence

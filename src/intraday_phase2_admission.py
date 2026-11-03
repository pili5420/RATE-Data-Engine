"""Provider-neutral Phase2 admission adapter for authorized intraday payloads.

This module connects the already-merged authoritative payload validator to the
Phase2 source path. It performs no network I/O and does not change the external
dependency state. A payload is admitted only after the repo-rooted 30-symbol
universe, dual-market mapping, scope, and freshness gates pass.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .authorized_intraday_feed import (
    load_authoritative_universe_binding,
    qualify_authorized_intraday_payload,
)
from .cer074_acceptance import sha256
from .production_live_state import require

REQUIRED_MARKET_COUNTS = {"TWSE": 25, "TPEX": 5}
REQUIRED_MARKETS = {"TWSE", "TPEX"}


def expected_universe_binding() -> tuple[dict[str, str], dict[str, Any]]:
    trusted, lineage = load_authoritative_universe_binding()
    binding = {
        "artifact": "RATE_APPROVED_INTRADAY_UNIVERSE_BINDING_V1",
        "source_kind": lineage["source_kind"],
        "source_validation_status": "PASS",
        "production_snapshot_id": lineage["production_snapshot_id"],
        "source_bundle_sha256": lineage["source_bundle_sha256"],
        "universe_sha256": lineage["universe_sha256"],
        "universe_contract_sha256": lineage["universe_contract_sha256"],
        "universe_binding_hash": lineage["universe_binding_hash"],
    }
    return trusted, binding


def qualify_phase2_intraday_feed(
    feed: Mapping[str, Any],
    *,
    trading_date: str,
    cadence: str,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    require(isinstance(feed, Mapping), "PHASE2_INTRADAY_FEED_INVALID")
    require(feed.get("source_status") == "PASS", "PHASE2_INTRADAY_SOURCE_STATUS_NOT_PASS")
    require(feed.get("freshness_status") == "PASS", "PHASE2_INTRADAY_FRESHNESS_STATUS_NOT_PASS")
    require(feed.get("source_authority") == "AUTHORIZED_TAIWAN_INTRADAY_FEED",
            "PHASE2_INTRADAY_SOURCE_AUTHORITY_INVALID")
    require(feed.get("blocked_dependencies") == [], "PHASE2_INTRADAY_BLOCKED_DEPENDENCIES_PRESENT")
    require(feed.get("fallback_used") is False, "PHASE2_INTRADAY_FALLBACK_FORBIDDEN")
    require(feed.get("trading_date") == trading_date and feed.get("cadence") == cadence,
            "PHASE2_INTRADAY_SCOPE_BINDING_MISMATCH")

    trusted, binding = expected_universe_binding()
    qualified = qualify_authorized_intraday_payload(
        feed,
        expected_universe=trusted,
        expected_universe_binding=binding,
        trading_date=trading_date,
        cadence=cadence,
        now_utc=now_utc or datetime.now(timezone.utc),
    )

    require(qualified.get("validation_status") == "PASS",
            "PHASE2_INTRADAY_PAYLOAD_QUALIFICATION_NOT_PASS")
    require(qualified.get("coverage") == "30/30"
            and qualified.get("expected_count") == 30
            and qualified.get("selected_count") == 30,
            "PHASE2_INTRADAY_PAYLOAD_COVERAGE_INVALID")
    require(qualified.get("expected_market_counts") == REQUIRED_MARKET_COUNTS
            and qualified.get("selected_market_counts") == REQUIRED_MARKET_COUNTS,
            "PHASE2_INTRADAY_PAYLOAD_MARKET_COUNTS_INVALID")
    require(set(qualified.get("licensed_markets", [])) == REQUIRED_MARKETS,
            "PHASE2_INTRADAY_LICENSE_MARKETS_INVALID")
    require(qualified.get("fallback_used") is False
            and qualified.get("network_requests") == 0
            and qualified.get("credential_access") == 0
            and qualified.get("provider_selected_by_module") is False
            and qualified.get("registry_activated") is False
            and qualified.get("production_eligible") is False,
            "PHASE2_INTRADAY_PREACTIVATION_BOUNDARY_INVALID")

    feed_sha = sha256(feed)
    qualification_sha = sha256(qualified)
    return {
        "artifact": "RATE_PHASE2_INTRADAY_ADMISSION_V1",
        "validation_status": "PASS",
        "trading_date": trading_date,
        "cadence": cadence,
        "feed_sha256": feed_sha,
        "qualification_sha256": qualification_sha,
        "provider_authority": qualified["provider_authority"],
        "coverage": qualified["coverage"],
        "market_counts": dict(REQUIRED_MARKET_COUNTS),
        "universe_binding_hash": qualified["expected_universe_binding_hash"],
        "universe_sha256": qualified["expected_universe_sha256"],
        "fallback_used": False,
        "network_requests": 0,
        "credential_access": 0,
        "registry_mutations": 0,
        "production_eligible": False,
        "qualified_payload": qualified,
    }


def validate_phase2_intraday_admission(
    feed: Mapping[str, Any],
    admission: Mapping[str, Any],
    *,
    trading_date: str,
    cadence: str,
) -> bool:
    require(isinstance(admission, Mapping), "PHASE2_INTRADAY_ADMISSION_MISSING")
    require(admission.get("artifact") == "RATE_PHASE2_INTRADAY_ADMISSION_V1"
            and admission.get("validation_status") == "PASS",
            "PHASE2_INTRADAY_ADMISSION_NOT_PASS")
    require(admission.get("trading_date") == trading_date and admission.get("cadence") == cadence,
            "PHASE2_INTRADAY_ADMISSION_SCOPE_MISMATCH")
    require(admission.get("feed_sha256") == sha256(feed),
            "PHASE2_INTRADAY_FEED_DIGEST_MISMATCH")
    qualified = admission.get("qualified_payload")
    require(isinstance(qualified, Mapping), "PHASE2_INTRADAY_QUALIFIED_PAYLOAD_MISSING")
    require(admission.get("qualification_sha256") == sha256(qualified),
            "PHASE2_INTRADAY_QUALIFICATION_DIGEST_MISMATCH")
    require(qualified.get("validation_status") == "PASS"
            and qualified.get("coverage") == "30/30"
            and qualified.get("expected_market_counts") == REQUIRED_MARKET_COUNTS
            and qualified.get("selected_market_counts") == REQUIRED_MARKET_COUNTS,
            "PHASE2_INTRADAY_QUALIFICATION_BINDING_INVALID")
    require(admission.get("fallback_used") is False
            and admission.get("network_requests") == 0
            and admission.get("credential_access") == 0
            and admission.get("registry_mutations") == 0
            and admission.get("production_eligible") is False,
            "PHASE2_INTRADAY_ADMISSION_SIDE_EFFECT_BOUNDARY_INVALID")
    return True

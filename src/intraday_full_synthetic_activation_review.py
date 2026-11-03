"""Aggregate synthetic review for one exact RATE intraday activation candidate.

The same generated candidate manifest is passed through all accepted offline review
layers. No real provider request, real credential, repository mutation, or activation
is permitted.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from .intraday_activation_candidate_acquisition_review import (
    review_candidate_acquisition_synthetic,
)
from .intraday_activation_candidate_materialization import (
    candidate_manifest_sha256,
    materialize_candidate_workspace,
    review_materialized_candidate_workspace,
)
from .intraday_activation_candidate_review import canonical_digest
from .intraday_activation_candidate_runtime_review import (
    review_candidate_runtime_synthetic,
)
from .intraday_activation_candidate_scaffold import (
    build_activation_candidate_scaffold,
)
from .intraday_activation_candidate_syntax_review import (
    validate_activation_candidate_syntax,
)

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class FullSyntheticActivationReviewError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FullSyntheticActivationReviewError(reason)


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def review_full_synthetic_activation_candidate(
    delta_plan: Mapping[str, Any],
    *,
    expected_delta_plan_sha256: str,
    expected_main_sha: str,
    expected_provider_name: str,
    expected_endpoint_template: str,
    expected_secret_name: str,
    expected_candidate_manifest_sha256: str,
    expected_runtime_sha256: str,
    expected_acquisition_sha256: str,
    trading_date: str,
    cadence: str,
    now_utc: datetime,
) -> dict[str, Any]:
    plan_hash = _sha64(
        expected_delta_plan_sha256,
        "FULL_SYNTHETIC_EXPECTED_DELTA_PLAN_HASH_INVALID",
    )
    main_sha = _sha40(expected_main_sha, "FULL_SYNTHETIC_EXPECTED_MAIN_SHA_INVALID")
    manifest_hash = _sha64(
        expected_candidate_manifest_sha256,
        "FULL_SYNTHETIC_EXPECTED_CANDIDATE_MANIFEST_HASH_INVALID",
    )
    runtime_hash = _sha64(
        expected_runtime_sha256,
        "FULL_SYNTHETIC_EXPECTED_RUNTIME_HASH_INVALID",
    )
    acquisition_hash = _sha64(
        expected_acquisition_sha256,
        "FULL_SYNTHETIC_EXPECTED_ACQUISITION_HASH_INVALID",
    )
    require(
        isinstance(expected_provider_name, str) and expected_provider_name.strip(),
        "FULL_SYNTHETIC_EXPECTED_PROVIDER_INVALID",
    )
    require(
        isinstance(expected_endpoint_template, str) and expected_endpoint_template.startswith("https://"),
        "FULL_SYNTHETIC_EXPECTED_ENDPOINT_INVALID",
    )
    require(
        isinstance(expected_secret_name, str) and expected_secret_name.strip(),
        "FULL_SYNTHETIC_EXPECTED_SECRET_INVALID",
    )
    require(cadence in {"09:30", "12:00"}, "FULL_SYNTHETIC_CADENCE_INVALID")
    require(now_utc.tzinfo is not None and now_utc.utcoffset() is not None,
            "FULL_SYNTHETIC_NOW_TIMEZONE_REQUIRED")

    scaffold = build_activation_candidate_scaffold(
        delta_plan,
        expected_delta_plan_sha256=plan_hash,
        expected_main_sha=main_sha,
        expected_provider_name=expected_provider_name,
        expected_endpoint_template=expected_endpoint_template,
        expected_secret_name=expected_secret_name,
    )
    require(
        scaffold.get("validation_status") == "PASS"
        and scaffold.get("scaffold_status") == "DESIGN_SCAFFOLD_ONLY",
        "FULL_SYNTHETIC_SCAFFOLD_NOT_PASS",
    )
    candidate_files = scaffold["candidate_files"]
    actual_manifest = candidate_manifest_sha256(candidate_files)
    require(
        actual_manifest == manifest_hash,
        "FULL_SYNTHETIC_CANDIDATE_MANIFEST_HASH_MISMATCH",
    )

    runtime_source = candidate_files["src/intraday_provider_runtime.py"]
    acquisition_source = candidate_files["scripts/acquire_intraday_provider_feed.py"]
    require(
        hashlib.sha256(runtime_source.encode("utf-8")).hexdigest() == runtime_hash,
        "FULL_SYNTHETIC_RUNTIME_HASH_MISMATCH",
    )
    require(
        hashlib.sha256(acquisition_source.encode("utf-8")).hexdigest() == acquisition_hash,
        "FULL_SYNTHETIC_ACQUISITION_HASH_MISMATCH",
    )

    syntax_review = validate_activation_candidate_syntax(
        candidate_files,
        expected_provider_name=expected_provider_name,
        expected_secret_name=expected_secret_name,
    )
    runtime_review = review_candidate_runtime_synthetic(
        candidate_files,
        expected_runtime_sha256=runtime_hash,
        expected_provider_name=expected_provider_name,
        expected_secret_name=expected_secret_name,
        trading_date=trading_date,
        cadence=cadence,
        now_utc=now_utc,
    )
    acquisition_review = review_candidate_acquisition_synthetic(
        candidate_files,
        expected_acquisition_sha256=acquisition_hash,
        expected_provider_name=expected_provider_name,
        expected_secret_name=expected_secret_name,
        trading_date=trading_date,
        cadence=cadence,
        now_utc=now_utc,
    )

    with tempfile.TemporaryDirectory(prefix="rate-activation-candidate-review-") as tmp:
        root = Path(tmp)
        materialization = materialize_candidate_workspace(
            candidate_files,
            workspace_root=root,
            expected_candidate_manifest_sha256=manifest_hash,
        )
        materialized_review = review_materialized_candidate_workspace(
            delta_plan,
            workspace_root=root,
            expected_candidate_manifest_sha256=manifest_hash,
            expected_delta_plan_sha256=plan_hash,
            expected_main_sha=main_sha,
            expected_provider_name=expected_provider_name,
            expected_endpoint_template=expected_endpoint_template,
            expected_secret_name=expected_secret_name,
            expected_runtime_sha256=runtime_hash,
            trading_date=trading_date,
            cadence=cadence,
            now_utc=now_utc,
        )

    for name, review in (
        ("syntax", syntax_review),
        ("runtime", runtime_review),
        ("acquisition", acquisition_review),
        ("materialization", materialization),
        ("materialized_review", materialized_review),
    ):
        require(review.get("validation_status") == "PASS",
                "FULL_SYNTHETIC_SUBREVIEW_NOT_PASS:" + name)

    require(runtime_review.get("real_network_requests") == 0,
            "FULL_SYNTHETIC_REAL_NETWORK_REQUEST")
    require(acquisition_review.get("real_provider_requests") == 0,
            "FULL_SYNTHETIC_REAL_PROVIDER_REQUEST")
    require(materialized_review.get("real_network_requests") == 0,
            "FULL_SYNTHETIC_MATERIALIZED_REAL_NETWORK_REQUEST")
    require(
        all(
            review.get("activation_execution_allowed") is False
            and review.get("external_dependency_resolved") is False
            and review.get("registry_activation_allowed") is False
            and review.get("production_credit") == 0
            and review.get("cer081_credit") == 0
            for review in (
                runtime_review,
                acquisition_review,
                materialization,
                materialized_review,
            )
        ),
        "FULL_SYNTHETIC_PREMATURE_ACTIVATION_STATE",
    )

    return {
        "artifact": "RATE_INTRADAY_FULL_SYNTHETIC_ACTIVATION_CANDIDATE_REVIEW_V1",
        "validation_status": "PASS",
        "review_disposition": "READY_FOR_LIVE_EVIDENCE_BOUND_ACTIVATION_REVIEW",
        "main_sha": main_sha,
        "delta_plan_sha256": plan_hash,
        "candidate_manifest_sha256": manifest_hash,
        "runtime_sha256": runtime_hash,
        "acquisition_sha256": acquisition_hash,
        "provider_name": expected_provider_name,
        "trading_date": trading_date,
        "cadence": cadence,
        "subreview_sha256": {
            "scaffold": canonical_digest(scaffold),
            "syntax": canonical_digest(syntax_review),
            "runtime": canonical_digest(runtime_review),
            "acquisition": canonical_digest(acquisition_review),
            "materialization": canonical_digest(materialization),
            "materialized_review": canonical_digest(materialized_review),
        },
        "coverage": runtime_review["coverage"],
        "market_counts": runtime_review["market_counts"],
        "real_network_requests": 0,
        "real_credential_access": 0,
        "repository_writes": 0,
        "provider_accepted": False,
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "production_credit": 0,
        "cer081_credit": 0,
        "next_gate": "LIVE_PROVIDER_EVIDENCE_BINDING",
    }

"""Pure static validator for a future RATE intraday activation candidate.

The validator consumes candidate file contents in memory. It never writes them,
never reads credentials, and never authorizes or executes Production activation.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from .intraday_activation_delta_plan import NEW_RUNTIME_FILES
from .intraday_activation_readiness import (
    ALLOWED_EXISTING_MUTATION_PATHS,
    repo_preimage_hashes,
)

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MARKETS = {"TWSE", "TPEX"}
REQUIRED_CADENCE_MAP = {
    "07:30": "NOT_APPLICABLE",
    "09:30": "REQUIRED",
    "12:00": "REQUIRED",
    "19:30": "NOT_APPLICABLE",
}


class ActivationCandidateReviewError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ActivationCandidateReviewError(reason)


def canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _sha40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _sha64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _json_file(candidate_files: Mapping[str, str], path: str) -> dict[str, Any]:
    raw = candidate_files[path]
    require(isinstance(raw, str) and raw.strip(), "ACTIVATION_CANDIDATE_FILE_EMPTY:" + path)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ActivationCandidateReviewError("ACTIVATION_CANDIDATE_JSON_INVALID:" + path) from exc
    require(isinstance(value, dict), "ACTIVATION_CANDIDATE_JSON_NOT_OBJECT:" + path)
    return value


def _find_exact(items: Any, key: str, value: str, reason: str) -> dict[str, Any]:
    require(isinstance(items, list), reason)
    matches = [item for item in items if isinstance(item, Mapping) and item.get(key) == value]
    require(len(matches) == 1, reason)
    return dict(matches[0])


def _require_contains(text: str, required: tuple[str, ...], reason: str) -> None:
    require(all(token in text for token in required), reason)


def _require_absent(text: str, forbidden: tuple[str, ...], reason: str) -> None:
    require(all(token not in text for token in forbidden), reason)


def validate_activation_candidate(
    delta_plan: Mapping[str, Any],
    candidate_files: Mapping[str, str],
    *,
    expected_delta_plan_sha256: str,
    expected_main_sha: str,
    expected_provider_name: str,
    expected_endpoint_template: str,
    expected_secret_name: str,
) -> dict[str, Any]:
    require(isinstance(delta_plan, Mapping), "ACTIVATION_CANDIDATE_DELTA_PLAN_INVALID")
    require(
        delta_plan.get("artifact") == "RATE_INTRADAY_ACTIVATION_DELTA_PLAN_V1"
        and delta_plan.get("validation_status") == "PASS"
        and delta_plan.get("apply_allowed") is False,
        "ACTIVATION_CANDIDATE_DELTA_PLAN_NOT_PASS",
    )
    expected_plan_hash = _sha64(
        expected_delta_plan_sha256, "ACTIVATION_CANDIDATE_EXPECTED_PLAN_HASH_INVALID"
    )
    require(canonical_digest(delta_plan) == expected_plan_hash,
            "ACTIVATION_CANDIDATE_DELTA_PLAN_HASH_MISMATCH")

    main_sha = _sha40(expected_main_sha, "ACTIVATION_CANDIDATE_EXPECTED_MAIN_SHA_INVALID")
    require(delta_plan.get("main_sha") == main_sha,
            "ACTIVATION_CANDIDATE_MAIN_SHA_MISMATCH")
    require(delta_plan.get("provider_name") == expected_provider_name,
            "ACTIVATION_CANDIDATE_PROVIDER_MISMATCH")
    require(delta_plan.get("provider_endpoint_template") == expected_endpoint_template,
            "ACTIVATION_CANDIDATE_ENDPOINT_MISMATCH")
    credential = delta_plan.get("credential_boundary")
    require(
        isinstance(credential, Mapping)
        and credential.get("store") == "GITHUB_ACTIONS_SECRET"
        and credential.get("secret_name") == expected_secret_name
        and credential.get("secret_value_embedded") is False,
        "ACTIVATION_CANDIDATE_CREDENTIAL_BINDING_MISMATCH",
    )

    trusted_preimages = repo_preimage_hashes()
    require(delta_plan.get("existing_file_preimage_sha256") == trusted_preimages,
            "ACTIVATION_CANDIDATE_REPO_PREIMAGE_MISMATCH")
    require(
        set(delta_plan.get("existing_mutation_paths", [])) == set(ALLOWED_EXISTING_MUTATION_PATHS),
        "ACTIVATION_CANDIDATE_EXISTING_PATH_BOUNDARY_INVALID",
    )
    require(set(delta_plan.get("new_runtime_files", [])) == set(NEW_RUNTIME_FILES),
            "ACTIVATION_CANDIDATE_NEW_PATH_BOUNDARY_INVALID")

    expected_paths = set(ALLOWED_EXISTING_MUTATION_PATHS) | set(NEW_RUNTIME_FILES)
    require(isinstance(candidate_files, Mapping) and set(candidate_files) == expected_paths,
            "ACTIVATION_CANDIDATE_FILE_SET_INVALID")
    require(all(isinstance(v, str) and v for v in candidate_files.values()),
            "ACTIVATION_CANDIDATE_FILE_CONTENT_INVALID")

    dep = _json_file(candidate_files, "config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json")
    dependency = _find_exact(
        dep.get("dependencies"),
        "dependency_id",
        "EXTERNAL_AUTHORIZED_INTRADAY_FEED_DEPENDENCY",
        "ACTIVATION_CANDIDATE_DEPENDENCY_RECORD_INVALID",
    )
    require(
        dependency.get("status") == "PASS"
        and dependency.get("engineering_resolution_available") is True
        and set(dependency.get("required_market_coverage", [])) == REQUIRED_MARKETS
        and dependency.get("fallback_allowed") is False,
        "ACTIVATION_CANDIDATE_DEPENDENCY_POSTCONDITION_INVALID",
    )

    registry = _json_file(candidate_files, "config/SOURCE_REGISTRY.json")
    intraday = _find_exact(
        registry.get("domains"),
        "domain",
        "market_intraday",
        "ACTIVATION_CANDIDATE_SOURCE_REGISTRY_RECORD_INVALID",
    )
    require(
        intraday.get("provider") == expected_provider_name
        and intraday.get("endpoint_or_path") == expected_endpoint_template
        and intraday.get("authorization_status") == "PASS"
        and intraday.get("operational_use_allowed") is True,
        "ACTIVATION_CANDIDATE_SOURCE_REGISTRY_POSTCONDITION_INVALID",
    )
    require(
        registry.get("intraday_status")
        == {"0930": "AUTHORIZED_PROVIDER_READY", "1200": "AUTHORIZED_PROVIDER_READY"},
        "ACTIVATION_CANDIDATE_INTRADAY_STATUS_INVALID",
    )

    official = _json_file(
        candidate_files, "config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json"
    )
    dataset = _find_exact(
        official.get("datasets"),
        "dataset_id",
        "authorized_market_intraday",
        "ACTIVATION_CANDIDATE_OFFICIAL_REGISTRY_RECORD_INVALID",
    )
    require(
        dataset.get("authority") == expected_provider_name
        and dataset.get("endpoint") == expected_endpoint_template
        and dataset.get("authorization_status") == "PASS"
        and set(dataset.get("required_market_coverage", [])) == REQUIRED_MARKETS
        and dataset.get("cadence_applicability") == REQUIRED_CADENCE_MAP
        and dataset.get("fallback_allowed") is False
        and "blocked_dependency" not in dataset,
        "ACTIVATION_CANDIDATE_OFFICIAL_REGISTRY_POSTCONDITION_INVALID",
    )

    phase2 = candidate_files["src/phase2_production.py"]
    _require_contains(
        phase2,
        (
            "def require_intraday_authority",
            "validate_phase2_intraday_admission",
            'status") == "PASS"',
        ),
        "ACTIVATION_CANDIDATE_PHASE2_REQUIRED_GATES_MISSING",
    )
    _require_absent(
        phase2,
        ('raise RuntimeError("PUBLIC_OFFICIAL_PARTIAL_RUNTIME_REQUIRED")',),
        "ACTIVATION_CANDIDATE_PHASE2_FORCED_PARTIAL_RUNTIME_REMAINS",
    )

    builder = candidate_files["scripts/build_phase2_production_source.py"]
    _require_contains(
        builder,
        (
            "qualify_phase2_intraday_feed",
            '"intraday_admission"',
            "RATE_AUTHORIZED_INTRADAY_FEED_PATH",
        ),
        "ACTIVATION_CANDIDATE_SOURCE_BUILDER_ADMISSION_MISSING",
    )
    _require_absent(
        builder,
        ("HTTPSConnection(", "urlopen(", "requests.get(", "requests.post("),
        "ACTIVATION_CANDIDATE_SOURCE_BUILDER_NETWORK_FORBIDDEN",
    )

    secret_expr = "${{ secrets." + expected_secret_name + " }}"
    for cadence, path in (
        ("09:30", ".github/workflows/rate_production_0930_scheduler.yml"),
        ("12:00", ".github/workflows/rate_production_1200_scheduler.yml"),
    ):
        workflow = candidate_files[path]
        _require_contains(
            workflow,
            (
                "scripts/acquire_intraday_provider_feed.py",
                "scripts/build_phase2_production_source.py",
                "scripts/run_phase2_production.py",
                "RATE_AUTHORIZED_INTRADAY_FEED_PATH",
                expected_secret_name,
                secret_expr,
                cadence,
            ),
            "ACTIVATION_CANDIDATE_SCHEDULER_WIRING_MISSING:" + cadence,
        )
        _require_absent(
            workflow,
            (
                "--public-official-partial",
                "continue-on-error: true",
                "fallback-provider",
                "retry-provider",
            ),
            "ACTIVATION_CANDIDATE_SCHEDULER_FORBIDDEN_WIRING:" + cadence,
        )

    runtime = candidate_files["src/intraday_provider_runtime.py"]
    _require_contains(
        runtime,
        (
            "def acquire_intraday_feed(",
            "MAX_REQUESTS = 30",
            "MAX_RETRIES = 0",
            "FALLBACK_ALLOWED = False",
            expected_secret_name,
        ),
        "ACTIVATION_CANDIDATE_RUNTIME_CONTRACT_MISSING",
    )
    if expected_provider_name.lower() == "fugle":
        _require_contains(
            runtime,
            ('API_HOST = "api.fugle.tw"',),
            "ACTIVATION_CANDIDATE_FUGLE_RUNTIME_HOST_MISSING",
        )
    _require_absent(
        runtime,
        ("time.sleep(", "while True:", "for attempt in range(", "fallback_provider"),
        "ACTIVATION_CANDIDATE_RUNTIME_RETRY_OR_FALLBACK_FORBIDDEN",
    )

    acquisition = candidate_files["scripts/acquire_intraday_provider_feed.py"]
    _require_contains(
        acquisition,
        (
            "from src.intraday_provider_runtime import acquire_intraday_feed",
            "--output",
            "RATE_AUTHORIZED_INTRADAY_FEED_PATH",
            expected_secret_name,
        ),
        "ACTIVATION_CANDIDATE_ACQUISITION_CLI_MISSING",
    )
    _require_absent(
        acquisition,
        ("print(api_key", "print(token", "fallback_provider", "retry_provider"),
        "ACTIVATION_CANDIDATE_ACQUISITION_SECRET_OR_FALLBACK_RISK",
    )

    candidate_hashes = {
        path: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for path, text in sorted(candidate_files.items())
    }
    return {
        "artifact": "RATE_INTRADAY_ACTIVATION_CANDIDATE_STATIC_REVIEW_V1",
        "validation_status": "PASS",
        "review_disposition": "READY_FOR_SEPARATE_ACTIVATION_IMPLEMENTATION_REVIEW",
        "main_sha": main_sha,
        "delta_plan_sha256": expected_plan_hash,
        "provider_name": expected_provider_name,
        "candidate_file_sha256": candidate_hashes,
        "existing_mutation_paths": list(ALLOWED_EXISTING_MUTATION_PATHS),
        "new_runtime_files": list(NEW_RUNTIME_FILES),
        "apply_allowed": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "network_requests": 0,
        "credential_access": 0,
        "repository_writes": 0,
        "production_credit": 0,
        "cer081_credit": 0,
    }

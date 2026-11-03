"""Pure independent review gate for a single RATE intraday live qualification.

A PASS from this module is technical-review readiness only. It never selects or
activates a provider, never reads credentials, never mutates registry/scheduler
state, and never resolves the external intraday dependency.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import re
from typing import Any, Mapping

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_MARKETS = {"TWSE", "TPEX"}
REQUIRED_MARKET_COUNTS = {"TWSE": 25, "TPEX": 5}
ALLOWED_CADENCES = {"09:30", "12:00"}
MAX_AGE_SECONDS = 180


class LiveQualificationReviewError(RuntimeError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise LiveQualificationReviewError(reason)


def canonical_digest(value: Mapping[str, Any]) -> str:
    body = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _hex40(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX40.fullmatch(text)), reason)
    return text


def _hex64(value: Any, reason: str) -> str:
    text = str(value or "").lower()
    require(bool(HEX64.fullmatch(text)), reason)
    return text


def _positive_int(value: Any, reason: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0, reason)
    return value


def _exact_expected_universe(value: Mapping[str, str]) -> dict[str, str]:
    require(isinstance(value, Mapping), "LIVE_REVIEW_EXPECTED_UNIVERSE_INVALID")
    result: dict[str, str] = {}
    for symbol, market in value.items():
        require(
            isinstance(symbol, str) and symbol and symbol == symbol.strip(),
            "LIVE_REVIEW_EXPECTED_SYMBOL_INVALID",
        )
        normalized = str(market or "").upper()
        require(normalized in REQUIRED_MARKETS, "LIVE_REVIEW_EXPECTED_MARKET_INVALID")
        require(symbol not in result, "LIVE_REVIEW_EXPECTED_SYMBOL_DUPLICATE")
        result[symbol] = normalized
    require(len(result) == 30, "LIVE_REVIEW_EXPECTED_UNIVERSE_COUNT_INVALID")
    require(Counter(result.values()) == Counter(REQUIRED_MARKET_COUNTS),
            "LIVE_REVIEW_EXPECTED_UNIVERSE_MARKET_COUNTS_INVALID")
    return result


def _number(value: Any, *, positive: bool, reason: str) -> float:
    require(
        not isinstance(value, bool) and isinstance(value, (int, float)),
        reason,
    )
    number = float(value)
    require(math.isfinite(number), reason)
    require(number > 0 if positive else number >= 0, reason)
    return number


def validate_live_qualification_review(
    package: Mapping[str, Any],
    *,
    expected_engineering_source_sha: str,
    expected_trigger_commit_sha: str,
    expected_workflow_run_id: int,
    expected_workflow_job_id: int,
    expected_provider_name: str,
    expected_trading_date: str,
    expected_cadence: str,
    expected_result_sha256: str,
    expected_universe_binding_hash: str,
    expected_symbol_markets: Mapping[str, str],
) -> dict[str, Any]:
    engineering_sha = _hex40(
        expected_engineering_source_sha,
        "LIVE_REVIEW_EXPECTED_ENGINEERING_SOURCE_SHA_INVALID",
    )
    trigger_sha = _hex40(
        expected_trigger_commit_sha,
        "LIVE_REVIEW_EXPECTED_TRIGGER_COMMIT_SHA_INVALID",
    )
    run_id = _positive_int(expected_workflow_run_id, "LIVE_REVIEW_EXPECTED_RUN_ID_INVALID")
    job_id = _positive_int(expected_workflow_job_id, "LIVE_REVIEW_EXPECTED_JOB_ID_INVALID")
    require(
        isinstance(expected_provider_name, str) and expected_provider_name.strip(),
        "LIVE_REVIEW_EXPECTED_PROVIDER_NAME_INVALID",
    )
    require(
        isinstance(expected_trading_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", expected_trading_date),
        "LIVE_REVIEW_EXPECTED_TRADING_DATE_INVALID",
    )
    require(expected_cadence in ALLOWED_CADENCES, "LIVE_REVIEW_EXPECTED_CADENCE_INVALID")
    expected_result_hash = _hex64(
        expected_result_sha256,
        "LIVE_REVIEW_EXPECTED_RESULT_HASH_INVALID",
    )
    expected_binding_hash = _hex64(
        expected_universe_binding_hash,
        "LIVE_REVIEW_EXPECTED_UNIVERSE_BINDING_HASH_INVALID",
    )
    expected_universe = _exact_expected_universe(expected_symbol_markets)

    require(isinstance(package, Mapping), "LIVE_REVIEW_PACKAGE_INVALID")
    require(
        package.get("artifact") == "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_PACKAGE_V1",
        "LIVE_REVIEW_ARTIFACT_INVALID",
    )
    require(package.get("review_scope") == "SINGLE_LIVE_QUALIFICATION",
            "LIVE_REVIEW_SCOPE_INVALID")
    require(package.get("single_use_consumed") is True,
            "LIVE_REVIEW_SINGLE_USE_NOT_CONSUMED")
    require(package.get("workflow_attempt") == 1,
            "LIVE_REVIEW_WORKFLOW_ATTEMPT_INVALID")
    require(package.get("rerun_count") == 0 and package.get("job_retry_count") == 0,
            "LIVE_REVIEW_RETRY_FORBIDDEN")
    require(
        _hex40(package.get("engineering_source_sha"), "LIVE_REVIEW_ENGINEERING_SOURCE_SHA_INVALID")
        == engineering_sha,
        "LIVE_REVIEW_ENGINEERING_SOURCE_BINDING_MISMATCH",
    )
    require(
        _hex40(package.get("trigger_commit_sha"), "LIVE_REVIEW_TRIGGER_COMMIT_SHA_INVALID")
        == trigger_sha,
        "LIVE_REVIEW_TRIGGER_COMMIT_BINDING_MISMATCH",
    )
    require(package.get("workflow_run_id") == run_id,
            "LIVE_REVIEW_WORKFLOW_RUN_BINDING_MISMATCH")
    require(package.get("workflow_job_id") == job_id,
            "LIVE_REVIEW_WORKFLOW_JOB_BINDING_MISMATCH")
    require(package.get("provider_name") == expected_provider_name,
            "LIVE_REVIEW_PROVIDER_BINDING_MISMATCH")
    require(package.get("trading_date") == expected_trading_date,
            "LIVE_REVIEW_TRADING_DATE_BINDING_MISMATCH")
    require(package.get("cadence") == expected_cadence,
            "LIVE_REVIEW_CADENCE_BINDING_MISMATCH")

    result = package.get("result")
    require(isinstance(result, Mapping), "LIVE_REVIEW_RESULT_MISSING")
    result_hash = canonical_digest(result)
    require(
        _hex64(package.get("result_sha256"), "LIVE_REVIEW_RESULT_HASH_INVALID") == result_hash,
        "LIVE_REVIEW_RESULT_SELF_HASH_MISMATCH",
    )
    require(result_hash == expected_result_hash,
            "LIVE_REVIEW_RESULT_EXPECTED_HASH_MISMATCH")

    require(result.get("provider") == expected_provider_name,
            "LIVE_REVIEW_RESULT_PROVIDER_MISMATCH")
    require(result.get("technical_validation_status") == "PASS",
            "LIVE_REVIEW_TECHNICAL_STATUS_NOT_PASS")
    require(result.get("trading_date") == expected_trading_date
            and result.get("cadence") == expected_cadence,
            "LIVE_REVIEW_RESULT_SCOPE_MISMATCH")
    require(result.get("market_coverage") == "30/30",
            "LIVE_REVIEW_MARKET_COVERAGE_INVALID")
    market_counts = result.get("market_counts")
    require(
        isinstance(market_counts, Mapping)
        and set(market_counts) == REQUIRED_MARKETS
        and all(isinstance(v, int) and not isinstance(v, bool) for v in market_counts.values())
        and dict(market_counts) == REQUIRED_MARKET_COUNTS,
        "LIVE_REVIEW_MARKET_COUNTS_INVALID",
    )
    require(result.get("network_requests") == 30,
            "LIVE_REVIEW_REQUEST_COUNT_NOT_EXACT_30")
    require(result.get("http_redirects_followed") == 0,
            "LIVE_REVIEW_REDIRECT_FOLLOWED")
    require(result.get("automatic_retries") == 0,
            "LIVE_REVIEW_AUTOMATIC_RETRY_USED")
    require(result.get("fallback_used") is False,
            "LIVE_REVIEW_FALLBACK_USED")
    require(result.get("token_persisted") is False,
            "LIVE_REVIEW_TOKEN_PERSISTED")
    require(
        _hex64(
            result.get("approved_universe_binding_hash"),
            "LIVE_REVIEW_UNIVERSE_BINDING_HASH_INVALID",
        ) == expected_binding_hash,
        "LIVE_REVIEW_UNIVERSE_BINDING_HASH_MISMATCH",
    )
    require(result.get("production_eligible") is False
            and result.get("external_dependency_resolved") is False
            and result.get("registry_activation_allowed") is False,
            "LIVE_REVIEW_PREMATURE_PRODUCTION_STATE")

    records = result.get("records")
    require(isinstance(records, list) and len(records) == 30,
            "LIVE_REVIEW_RECORD_COUNT_INVALID")
    seen: dict[str, str] = {}
    for row in records:
        require(isinstance(row, Mapping), "LIVE_REVIEW_RECORD_INVALID")
        symbol = row.get("symbol")
        market = str(row.get("market") or "").upper()
        require(
            isinstance(symbol, str) and symbol and symbol == symbol.strip(),
            "LIVE_REVIEW_RECORD_SYMBOL_INVALID",
        )
        require(market in REQUIRED_MARKETS, "LIVE_REVIEW_RECORD_MARKET_INVALID")
        require(symbol not in seen, "LIVE_REVIEW_RECORD_DUPLICATE_SYMBOL")
        seen[symbol] = market
        require(
            isinstance(row.get("timestamp_utc"), str) and row["timestamp_utc"].strip(),
            "LIVE_REVIEW_RECORD_TIMESTAMP_INVALID",
        )
        age = _number(
            row.get("age_seconds"),
            positive=False,
            reason="LIVE_REVIEW_RECORD_AGE_INVALID",
        )
        require(age <= MAX_AGE_SECONDS, "LIVE_REVIEW_RECORD_FRESHNESS_FAIL")
        _number(row.get("price"), positive=True, reason="LIVE_REVIEW_RECORD_PRICE_INVALID")
        _number(row.get("volume"), positive=False, reason="LIVE_REVIEW_RECORD_VOLUME_INVALID")
        _number(row.get("turnover"), positive=False, reason="LIVE_REVIEW_RECORD_TURNOVER_INVALID")

    require(seen == expected_universe, "LIVE_REVIEW_RECORD_UNIVERSE_MISMATCH")
    require(Counter(seen.values()) == Counter(REQUIRED_MARKET_COUNTS),
            "LIVE_REVIEW_RECORD_MARKET_COUNTS_INVALID")

    exposure = package.get("secret_exposure")
    require(isinstance(exposure, Mapping), "LIVE_REVIEW_SECRET_EXPOSURE_MISSING")
    require(
        exposure.get("api_key_in_result") is False
        and exposure.get("api_key_in_logs") is False
        and exposure.get("raw_secret_persisted") is False,
        "LIVE_REVIEW_SECRET_EXPOSURE_DETECTED",
    )

    require(package.get("live_provider_requests") == 30,
            "LIVE_REVIEW_PACKAGE_REQUEST_COUNT_INVALID")
    require(package.get("fallback_used") is False,
            "LIVE_REVIEW_PACKAGE_FALLBACK_USED")
    require(package.get("production_credit") == 0 and package.get("cer081_credit") == 0,
            "LIVE_REVIEW_PREMATURE_CREDIT")

    return {
        "artifact": "RATE_INTRADAY_SINGLE_LIVE_QUALIFICATION_REVIEW_V1",
        "validation_status": "PASS",
        "review_disposition": "READY_FOR_CONTROL_CENTER_PROVIDER_ACCEPTANCE",
        "engineering_source_sha": engineering_sha,
        "trigger_commit_sha": trigger_sha,
        "workflow_run_id": run_id,
        "workflow_job_id": job_id,
        "provider_name": expected_provider_name,
        "trading_date": expected_trading_date,
        "cadence": expected_cadence,
        "result_sha256": result_hash,
        "market_coverage": "30/30",
        "market_counts": dict(REQUIRED_MARKET_COUNTS),
        "network_requests": 30,
        "http_redirects_followed": 0,
        "automatic_retries": 0,
        "fallback_used": False,
        "secret_exposure": False,
        "provider_accepted": False,
        "activation_execution_allowed": False,
        "external_dependency_resolved": False,
        "production_credit": 0,
        "cer081_credit": 0,
    }

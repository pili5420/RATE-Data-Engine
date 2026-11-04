"""Fugle free/basic intraday feasibility diagnostic for RATE V11.

This module never changes Production registry or resolves the external dependency.
The approved 30-symbol universe is rooted in RATE's authoritative Production
universe chain. Live transport uses one direct HTTPS request per approved symbol,
does not follow redirects, never retries, and cannot switch hosts.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from http.client import HTTPSConnection
import json
import math
from typing import Any, Callable, Mapping

from src.authorized_intraday_feed import load_authoritative_universe_binding

API_HOST = "api.fugle.tw"
QUOTE_PATH_PREFIX = "/marketdata/v1.0/stock/intraday/quote/"
MAX_REQUESTS = 30
MAX_AGE_SECONDS = 180
ALLOWED_MARKETS = {"TWSE", "TPEX"}


class FugleDiagnosticError(RuntimeError):
    pass


def require(value: bool, reason: str) -> None:
    if not value:
        raise FugleDiagnosticError(reason)


def _number(value: Any, *, positive: bool = False) -> float:
    require(not isinstance(value, bool) and isinstance(value, (int, float)), "FUGLE_NUMERIC_INVALID")
    number = float(value)
    require(math.isfinite(number), "FUGLE_NUMERIC_INVALID")
    require(number > 0 if positive else number >= 0, "FUGLE_NUMERIC_INVALID")
    return number


def _timestamp(value: Any) -> datetime:
    require(isinstance(value, (int, float)) and not isinstance(value, bool), "FUGLE_TIMESTAMP_INVALID")
    raw = float(value)
    if raw > 1e14:
        raw /= 1_000_000
    elif raw > 1e11:
        raw /= 1_000
    require(raw > 0, "FUGLE_TIMESTAMP_INVALID")
    return datetime.fromtimestamp(raw, tz=timezone.utc)


def _market(value: Any) -> str:
    text = str(value or "").strip().upper()
    require(text in ALLOWED_MARKETS, "FUGLE_MARKET_INVALID:" + text)
    return text


def _trusted_binding() -> tuple[dict[str, str], dict[str, str]]:
    trusted, lineage = load_authoritative_universe_binding()
    require(len(trusted) == 30, "FUGLE_TRUSTED_UNIVERSE_COUNT_INVALID")
    require(Counter(trusted.values()) == Counter({"TWSE": 25, "TPEX": 5}),
            "FUGLE_TRUSTED_UNIVERSE_MARKET_COUNTS_INVALID")
    return trusted, lineage


def load_binding(value: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Validate the diagnostic mirror against RATE's independent Production authority."""
    require(isinstance(value, Mapping), "FUGLE_BINDING_INVALID")
    require(value.get("artifact") == "RATE_FUGLE_FREE_INTRADAY_UNIVERSE_BINDING_V1",
            "FUGLE_BINDING_ARTIFACT_INVALID")
    require(value.get("evidence_scope") == "DIAGNOSTIC_ONLY", "FUGLE_BINDING_SCOPE_INVALID")
    require(value.get("validation_status") == "PASS", "FUGLE_BINDING_NOT_PASS")

    trusted, lineage = _trusted_binding()
    require(value.get("expected_count") == 30, "FUGLE_BINDING_COUNT_INVALID")
    require(value.get("expected_market_counts") == {"TWSE": 25, "TPEX": 5},
            "FUGLE_BINDING_MARKET_COUNTS_INVALID")
    require(value.get("production_snapshot_id") == lineage["production_snapshot_id"],
            "FUGLE_BINDING_SNAPSHOT_MISMATCH")
    require(value.get("source_bundle_path") == lineage["immutable_bundle_path"],
            "FUGLE_BINDING_SOURCE_PATH_MISMATCH")
    require(value.get("source_bundle_sha256") == lineage["source_bundle_sha256"],
            "FUGLE_BINDING_SOURCE_SHA256_MISMATCH")
    require(value.get("universe_contract_sha256") == lineage["universe_contract_sha256"],
            "FUGLE_BINDING_CONTRACT_SHA256_MISMATCH")
    require(value.get("universe_binding_hash") == lineage["universe_binding_hash"],
            "FUGLE_BINDING_HASH_MISMATCH")

    records = value.get("records")
    require(isinstance(records, list) and len(records) == 30, "FUGLE_BINDING_COUNT_INVALID")
    result: dict[str, str] = {}
    for row in records:
        require(isinstance(row, Mapping), "FUGLE_BINDING_ROW_INVALID")
        raw_symbol = row.get("symbol")
        raw_market = row.get("market")
        require(isinstance(raw_symbol, str) and raw_symbol == raw_symbol.strip() and raw_symbol,
                "FUGLE_BINDING_ROW_INVALID")
        require(isinstance(raw_market, str) and raw_market in ALLOWED_MARKETS,
                "FUGLE_BINDING_ROW_INVALID")
        require(raw_symbol not in result, "FUGLE_BINDING_DUPLICATE:" + raw_symbol)
        result[raw_symbol] = raw_market

    require(result == trusted, "FUGLE_BINDING_NOT_APPROVED")
    return result, lineage


def _single_https_request(
    symbol: str,
    api_key: str,
    *,
    connection_factory: Callable[..., Any] = HTTPSConnection,
) -> Mapping[str, Any]:
    """Perform exactly one direct HTTPS request; never follows HTTP redirects."""
    require(api_key, "FUGLE_API_KEY_MISSING")
    require(isinstance(symbol, str) and symbol and "/" not in symbol and "?" not in symbol,
            "FUGLE_SYMBOL_INVALID")
    connection = connection_factory(API_HOST, timeout=10)
    try:
        connection.request(
            "GET",
            QUOTE_PATH_PREFIX + symbol,
            headers={"X-API-KEY": api_key, "Accept": "application/json"},
        )
        response = connection.getresponse()
        status = int(response.status)
        body = response.read()
    except (OSError, TimeoutError) as exc:
        raise FugleDiagnosticError("FUGLE_CONNECTIVITY_FAILURE") from exc
    finally:
        try:
            connection.close()
        except Exception:
            pass

    if 300 <= status < 400:
        raise FugleDiagnosticError("FUGLE_REDIRECT_FORBIDDEN")
    if status == 401:
        raise FugleDiagnosticError("FUGLE_API_KEY_INVALID")
    if status == 403:
        raise FugleDiagnosticError("FUGLE_FREE_PLAN_NOT_AUTHORIZED")
    if status == 429:
        raise FugleDiagnosticError("FUGLE_FREE_PLAN_RATE_LIMIT")
    require(status == 200 and body, "FUGLE_HTTP_OR_EMPTY_RESPONSE")
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FugleDiagnosticError("FUGLE_NON_JSON_RESPONSE") from exc
    require(isinstance(value, Mapping), "FUGLE_RESPONSE_NOT_OBJECT")
    return value


def qualify(
    api_key: str,
    binding: Mapping[str, Any],
    *,
    trading_date: str,
    cadence: str,
    now_utc: datetime,
    connection_factory: Callable[..., Any] = HTTPSConnection,
    max_age_seconds: int = MAX_AGE_SECONDS,
) -> dict[str, Any]:
    require(cadence in {"09:30", "12:00"}, "FUGLE_CADENCE_INVALID")
    require(now_utc.tzinfo is not None and now_utc.utcoffset() is not None, "FUGLE_NOW_TIMEZONE_REQUIRED")

    # All binding checks occur before credential use or any network attempt.
    expected, lineage = load_binding(binding)
    require(api_key, "FUGLE_API_KEY_MISSING")

    records = []
    request_count = 0
    for symbol, expected_market in expected.items():
        require(request_count < MAX_REQUESTS, "FUGLE_REQUEST_CAP_EXCEEDED")
        request_count += 1
        raw = _single_https_request(
            symbol,
            api_key,
            connection_factory=connection_factory,
        )
        require(str(raw.get("symbol") or "").strip() == symbol, "FUGLE_SYMBOL_MISMATCH")
        market = _market(raw.get("exchange"))
        require(market == expected_market, "FUGLE_MARKET_MISMATCH:" + symbol)
        require(str(raw.get("date") or "") == trading_date, "FUGLE_TRADING_DATE_MISMATCH")
        stamp = _timestamp(raw.get("lastUpdated"))
        age = (now_utc.astimezone(timezone.utc) - stamp).total_seconds()
        require(0 <= age <= max_age_seconds, "FUGLE_FRESHNESS_FAIL:" + symbol)
        total = raw.get("total")
        require(isinstance(total, Mapping), "FUGLE_TOTAL_MISSING")
        price = raw.get("lastPrice")
        if price is None and isinstance(raw.get("lastTrade"), Mapping):
            price = raw["lastTrade"].get("price")
        records.append({
            "symbol": symbol,
            "market": market,
            "timestamp_utc": stamp.isoformat(),
            "age_seconds": age,
            "price": _number(price, positive=True),
            "volume": _number(total.get("tradeVolume")),
            "turnover": _number(total.get("tradeValue")),
        })

    counts = Counter(row["market"] for row in records)
    require(request_count == MAX_REQUESTS and len(records) == MAX_REQUESTS, "FUGLE_EXACT_30_REQUIRED")
    require(counts == Counter({"TWSE": 25, "TPEX": 5}), "FUGLE_DUAL_MARKET_COVERAGE_FAIL")
    return {
        "artifact": "RATE_FUGLE_FREE_INTRADAY_DIAGNOSTIC_RESULT_V1",
        "provider": "Fugle",
        "plan_target": "FREE_OR_BASIC_TRIAL",
        "technical_validation_status": "PASS",
        "market_coverage": "30/30",
        "market_counts": dict(counts),
        "trading_date": trading_date,
        "cadence": cadence,
        "network_requests": request_count,
        "http_redirects_followed": 0,
        "automatic_retries": 0,
        "fallback_used": False,
        "token_persisted": False,
        "approved_universe_production_snapshot_id": lineage["production_snapshot_id"],
        "approved_universe_source_bundle_sha256": lineage["source_bundle_sha256"],
        "approved_universe_contract_sha256": lineage["universe_contract_sha256"],
        "approved_universe_binding_hash": lineage["universe_binding_hash"],
        "license_gate": "UNPROVEN_REQUIRES_PROVIDER_CONFIRMATION_FOR_NON_DISPLAY_AUTOMATED_USE",
        "production_eligible": False,
        "external_dependency_resolved": False,
        "registry_activation_allowed": False,
        "records": records,
    }
